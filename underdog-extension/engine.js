/* MFF Underdog Draft Helper — Recommendation Engine
 *
 * Pure logic, no DOM. Same module is used by:
 *   - sidebar.js (live drafts)
 *   - mock.html (offline tests)
 *
 * Inputs:
 *   players[]      — slim player records {n, s, t, rank, udA, age, bye}
 *   draftedSet     — Set of player names already off the board
 *   myRoster[]     — players I've drafted so far (subset of players)
 *   pickNum        — overall pick number coming up next (1-based)
 *   slot           — my draft slot (1..teamSize)
 *   teamSize       — # teams (Underdog Best Ball Mania = 12)
 *
 * Output: recommend(...) returns top N {player, score, why[]}
 *
 * Format: Underdog Best Ball Mania
 *   18 rounds, 1QB / 2RB / 3WR / 1TE / 1FLEX / 12BN
 *   No starting lineup decision once drafted — purely roster-construction-driven.
 *   Best ball auto-starts the highest-scoring lineup each week, so DEPTH AT
 *   FLEX positions (RB/WR/TE) is more valuable than 1-and-done QB/TE.
 */

(function (global) {
  "use strict";

  // ---------- Constants ----------
  // v0.9.72: realigned to match sidebar.js recommendedRoster defaults
  // (2/7/8/1 = 18, anchored at TE: 1). Earlier the engine carried TE: 2 /
  // RB: 6 / WR: 7 = 17 which contradicted the new optimal-roster widget.
  const FORMAT = {
    rounds: 18,
    teamSize: 12,
    // Standard BBM 12-team (1QB / 2RB / 3WR / 1TE / 1FLEX, 18 rounds)
    slots: { QB: 2, RB: 7, WR: 8, TE: 1, K: 0, DST: 0 }, // sums to 18
    minPos: { QB: 1, RB: 4, WR: 5, TE: 1 }, // hard floor counts
    maxPos: { QB: 3, RB: 9, WR: 10, TE: 3 }, // soft ceiling
  };

  // v0.9.67: SF target distribution differs (1QB / 2RB / 2WR / 1TE / 1FLEX / 1SF)
  // — fewer required WRs, more QBs. SF wants 3 QBs (1 starter + 1 SF + 1 backup),
  // dial back WR target since 2 starters means less depth need.
  const FORMAT_SF = {
    rounds: 18,
    teamSize: 12,
    slots: { QB: 3, RB: 7, WR: 7, TE: 1, K: 0, DST: 0 }, // sums to 18
    minPos: { QB: 2, RB: 4, WR: 4, TE: 1 },
    maxPos: { QB: 4, RB: 9, WR: 9, TE: 3 },
  };

  function fmt(isSuperflex) {
    return isSuperflex ? FORMAT_SF : FORMAT;
  }

  // v0.10.56: Regular-redraft profile (weekly lineups, waivers exist).
  // Starters are 1QB/2RB/3WR/1TE + flex; bench value dies fast — the 2nd
  // QB/TE is bye insurance only and a 3rd is a dead roster spot, unlike
  // best ball where surplus depth keeps scoring weeks.
  const FORMAT_RD = {
    rounds: 18,
    teamSize: 12,
    slots: { QB: 2, RB: 6, WR: 8, TE: 2, K: 0, DST: 0 }, // sums to 18
    minPos: { QB: 1, RB: 3, WR: 4, TE: 1 },
    maxPos: { QB: 2, RB: 8, WR: 9, TE: 2 },
  };

  function fmtMode(isSuperflex, mode) {
    return mode === "rd" ? FORMAT_RD : fmt(isSuperflex);
  }

  // v0.9.67: VOR / UP getters that pick the format-specific variant
  // baked into players.json. Standard uses `vor`/`up` (QB12/WR42 cutoffs),
  // superflex uses `vorSf`/`upSf` (QB24/WR30 cutoffs — late QBs jump
  // ~+45 VOR, late WRs drop ~-18 VOR).
  function playerVor(p, isSuperflex) {
    if (!p) return null;
    if (isSuperflex && p.vorSf != null) return p.vorSf;
    return p.vor != null ? p.vor : null;
  }
  function playerUp(p, isSuperflex) {
    if (!p) return null;
    if (isSuperflex && p.upSf != null) return p.upSf;
    return p.up != null ? p.up : null;
  }

  // v0.9.67: VOR tier-break detection. If this player's VOR is meaningfully
  // higher than the next 3 same-position players (sorted by rank/ADP order
  // they'd be drafted), flag as a tier cliff — "take now or accept the
  // drop." Surfaces in player card as a TIER tag so the user sees scarcity
  // signals beyond pure rank.
  function detectVorTier(player, available, isSuperflex) {
    const v = playerVor(player, isSuperflex);
    if (v == null) return null;
    const samePos = available
      .filter(p => p.s === player.s && playerVor(p, isSuperflex) != null)
      .sort((a, b) => (a.rank || 9999) - (b.rank || 9999));
    const idx = samePos.indexOf(player);
    if (idx < 0) return null;
    const next3 = samePos.slice(idx + 1, idx + 4);
    if (next3.length < 3) return null;
    const avgNext = next3.reduce((s, p) => s + (playerVor(p, isSuperflex) || 0), 0) / next3.length;
    const drop = v - avgNext;
    if (drop >= 30) return { type: "cliff", drop: Math.round(drop) };
    if (drop >= 18) return { type: "soft-cliff", drop: Math.round(drop) };
    return null;
  }

  // v0.9.67: roster VOR per position — sum of banked VOR at each pos.
  // Surfaces "you're loaded at WR (+450) but thin at RB (+80)" in the
  // sidebar so users can rebalance late.
  function rosterVorByPos(roster, isSuperflex) {
    const out = { QB: 0, RB: 0, WR: 0, TE: 0 };
    for (const p of roster) {
      const v = playerVor(p, isSuperflex);
      if (out[p.s] != null && v != null) out[p.s] += v;
    }
    return out;
  }

  // v0.9.67: best available VOR per position. Used to pick which
  // position-of-need to address first — "next RB is +80 VOR, next WR
  // is +30, take RB."
  function bestVorAvailable(players, draftedSet, isSuperflex) {
    const out = { QB: -9999, RB: -9999, WR: -9999, TE: -9999 };
    for (const p of players) {
      if (draftedSet.has(p.n) || p.ir) continue;
      const v = playerVor(p, isSuperflex);
      if (v == null || out[p.s] == null) continue;
      if (v > out[p.s]) out[p.s] = v;
    }
    return out;
  }

  // v0.9.68: Position-level analysis — combines VOR (current + next-pick
  // projection), roster balance, and slot need into a single "urgency"
  // score per position. Surfaces to the user the position to draft next
  // based on where the value is, not just rank-ordering.
  //
  // Method:
  //   1. Sort all available by rank — assume opponents draft by rank
  //      (typical Underdog ADP behavior). Project the top N to be drafted
  //      before user's next pick, where N = picksUntilNext.
  //   2. For each position, compute bestNow vs bestNext (= best VOR
  //      among players NOT in the projected-drafted set), giving a
  //      dropoff number. Big dropoff = scarcity = take now.
  //   3. Combine bestNow + dropoff bonus + slots-open-bonus − over-bank
  //      penalty into urgency score. Position with highest urgency
  //      gets recommended.
  //
  // This naturally captures the user's heuristic: "if QB+WR are stacked
  // and RB has a big dropoff, recommend RB. If TE is empty but the next
  // good TE is close in value, you can wait." High banked VOR at one
  // position pushes the recommendation toward other positions.
  function analyzePositions(myRoster, players, draftedSet, pickNum, slot, teamSize, isSuperflex) {
    const counts = rosterCounts(myRoster);
    const banked = rosterVorByPos(myRoster, isSuperflex);
    const f = fmt(isSuperflex);
    const target = f.slots;
    const ts = teamSize || 12;
    const sl = slot || Math.ceil(ts / 2);
    const picksUntil = Math.max(0, picksUntilNext(pickNum, sl, ts));

    // Forward-simulate by rank — opponents are assumed to draft the
    // best-ranked available (matches typical Underdog ADP behavior).
    const avail = players
      .filter(p => !draftedSet.has(p.n) && !p.ir)
      .sort((a, b) => (a.rank || 9999) - (b.rank || 9999));
    const projDrafted = new Set(avail.slice(0, picksUntil).map(p => p.n));

    const out = {};
    for (const pos of ["QB", "RB", "WR", "TE"]) {
      const samePos = avail.filter(p => p.s === pos);
      // Best VOR among ALL available at this pos
      let bestNow = -9999, bestNowName = null;
      for (const p of samePos) {
        const v = playerVor(p, isSuperflex);
        if (v != null && v > bestNow) { bestNow = v; bestNowName = p.n; }
      }
      // Best VOR among players NOT projected to be drafted before next pick
      let bestNext = -9999;
      for (const p of samePos) {
        if (projDrafted.has(p.n)) continue;
        const v = playerVor(p, isSuperflex);
        if (v != null && v > bestNext) bestNext = v;
      }
      const dropoff = bestNow - bestNext;
      const have = counts[pos] || 0;
      const tgt = target[pos] || 0;
      const slotsOpen = Math.max(0, tgt - have);

      // Urgency components:
      //   bestNow:      40% — raw value at the pick
      //   dropoff:      35% — scarcity bonus (only positive contributes)
      //   need:         25% — structural need (slots open) minus over-bank penalty
      const dropoffBonus = Math.max(0, dropoff);
      const needScore = (slotsOpen * 25) - (banked[pos] || 0) * 0.05;
      const urgency = 0.4 * (bestNow + 50)         // shift so range starts ~0
                    + 0.35 * dropoffBonus
                    + 0.25 * needScore;

      out[pos] = {
        bestNow: bestNow > -9999 ? bestNow : null,
        bestNowName,
        bestNext: bestNext > -9999 ? bestNext : null,
        dropoff: bestNow > -9999 && bestNext > -9999 ? Math.round(dropoff) : null,
        banked: Math.round(banked[pos] || 0),
        have,
        target: tgt,
        slotsOpen,
        urgency: Math.round(urgency * 10) / 10
      };
    }
    return { positions: out, picksUntil };
  }

  // v0.9.68: Roster volatility profile. Derive each drafted player's
  // weekly σ% from cPpg/pPg (cPpg = pPg + σ_per_week, so σ_pct ≈
  // (cPpg - pPg) / pPg). Average σ% across the roster classifies the
  // user's draft tendency as upside-heavy (lots of rookies / boom-bust)
  // vs safe-heavy (locked-in vets). Use to nudge the next pick:
  //   avg σ% ≥ 0.65 → "lean safer next" (roster has too many dart throws)
  //   avg σ% ≤ 0.45 → "lean upside next" (roster is all floor, no ceiling)
  //   middle        → balanced (no nudge)
  // Round-aware: only flags imbalance after 4+ picks, since 1-3 picks
  // doesn't establish a tendency.
  function analyzeRosterVolatility(roster) {
    const sigmas = [];
    for (const p of roster || []) {
      if (p.cPpg != null && p.pPg != null && p.pPg > 0.5) {
        const sigmaPct = (p.cPpg - p.pPg) / p.pPg;
        if (!isNaN(sigmaPct) && sigmaPct >= 0 && sigmaPct < 2) {
          sigmas.push({ name: p.n, pct: sigmaPct });
        }
      }
    }
    if (sigmas.length < 4) return { avgPct: null, lean: null, n: sigmas.length };
    const avg = sigmas.reduce((s, x) => s + x.pct, 0) / sigmas.length;
    let lean = "balanced";
    if (avg >= 0.65) lean = "safer";  // too risky — recommend safe pick
    else if (avg <= 0.45) lean = "upside";  // too vanilla — recommend swing
    // Count of "high-σ" players (volatile / boom-bust)
    const highSigCount = sigmas.filter(x => x.pct >= 0.7).length;
    return {
      avgPct: Math.round(avg * 100) / 100,
      lean,
      n: sigmas.length,
      highSigCount,
      highSigShare: Math.round(highSigCount / sigmas.length * 100) / 100
    };
  }

  // v0.9.68: Translate the per-position analysis into a single recommended
  // position with a human-readable rationale. Caller surfaces this above
  // the player recs as a position-level suggestion.
  function suggestPosition(analysis, roster) {
    if (!analysis || !analysis.positions) return null;
    const candidates = Object.entries(analysis.positions)
      .filter(([_, a]) => a.slotsOpen > 0 && a.bestNow != null);
    if (candidates.length === 0) return null;
    candidates.sort((a, b) => b[1].urgency - a[1].urgency);
    const [pos, info] = candidates[0];
    const reasons = [];
    if (info.dropoff != null && info.dropoff >= 30) {
      reasons.push("big VOR cliff (-" + info.dropoff + " to next pick)");
    } else if (info.dropoff != null && info.dropoff >= 15) {
      reasons.push("moderate dropoff (-" + info.dropoff + ")");
    } else if (info.dropoff != null && info.dropoff < 8) {
      reasons.push("can also wait — only -" + info.dropoff + " to next pick");
    }
    if (info.slotsOpen >= 3) reasons.push(info.slotsOpen + " slots open");
    else if (info.slotsOpen >= 1 && info.have === 0) reasons.push("no " + pos + " yet");
    if (info.bestNow != null && info.bestNow >= 100) {
      reasons.push("elite VOR (+" + Math.round(info.bestNow) + ") available");
    }
    return { pos, info, reasons, all: analysis.positions };
  }

  // Round-by-round position guidance — DAMPENED so rank stays the primary signal.
  // Range narrowed to ±5% (was ±30%) — a top-ranked QB at pick 5 should still beat
  // a worse-ranked RB just because it's "RB round."
  const ROUND_PRIOR = {
    1: { RB: 1.03, WR: 1.02, QB: 0.95, TE: 0.97 },
    2: { RB: 1.03, WR: 1.02, QB: 0.96, TE: 0.97 },
    3: { RB: 1.02, WR: 1.03, QB: 0.97, TE: 0.99 },
    4: { RB: 1.00, WR: 1.03, QB: 0.99, TE: 1.01 },
    5: { RB: 1.00, WR: 1.02, QB: 1.00, TE: 1.02 },
    6: { RB: 1.00, WR: 1.02, QB: 1.02, TE: 1.02 },
    7: { RB: 1.00, WR: 1.00, QB: 1.03, TE: 1.02 },
    8: { RB: 1.00, WR: 1.00, QB: 1.03, TE: 1.02 },
  };

  // ---------- Helpers ----------
  function pickToRound(pickNum, teamSize) {
    return Math.ceil(pickNum / teamSize);
  }

  // For snake drafts, picks come in a pattern — compute the round-pick-in-round
  // and how many picks until your next selection.
  function picksUntilNext(currentPick, mySlot, teamSize) {
    // currentPick is the pick about to happen overall. Return # picks AFTER
    // the user's current pick until they pick again, helpful for "should I
    // pivot or hope X falls."
    const round = pickToRound(currentPick, teamSize);
    const isOdd = round % 2 === 1;
    const slotPick = isOdd ? mySlot : (teamSize - mySlot + 1);
    const myPickInRound = (round - 1) * teamSize + slotPick;
    // Find next pick in next round
    const nextRound = round + 1;
    const nextIsOdd = nextRound % 2 === 1;
    const nextSlotPick = nextIsOdd ? mySlot : (teamSize - mySlot + 1);
    const myNextPick = (nextRound - 1) * teamSize + nextSlotPick;
    return myNextPick - myPickInRound - 1;
  }

  function rosterCounts(roster) {
    const c = { QB: 0, RB: 0, WR: 0, TE: 0 };
    for (const p of roster) c[p.s] = (c[p.s] || 0) + 1;
    return c;
  }

  function byeBreakdown(roster) {
    const bye = {};
    for (const p of roster) {
      if (p.bye == null) continue;
      bye[p.bye] = (bye[p.bye] || 0) + 1;
    }
    return bye;
  }

  // Position-need score: SUBTLE adjustment, rank dominates.
  // Returns a multiplier (1.0 = neutral, range tightened to keep rank as primary).
  function positionNeedMult(pos, counts, round) {
    const f = FORMAT.slots;
    const min = FORMAT.minPos;
    const max = FORMAT.maxPos;
    const have = counts[pos] || 0;
    const target = f[pos] || 0;

    // Hard ceiling: never go above max position count
    if (have >= max[pos]) return 0.20;

    // Soft mild boost only when truly missing a position late in the draft.
    // Range capped at 1.10 so rank stays primary.
    if (have === 0 && round >= 8 && (pos === "QB" || pos === "TE")) return 1.10;
    if (have === 0 && round >= 6 && (pos === "RB" || pos === "WR")) return 1.10;
    if (have < min[pos] && round >= 10) return 1.05;

    // At or above target but below max — slight penalty (don't overload at one position)
    if (have >= target) return 0.92;

    return 1.0;
  }

  // ADP-vs-rank value: when Underdog ranks a player much higher than Jack,
  // taking them is "expensive." When Jack ranks much higher than UD,
  // it's a steal worth flagging.
  function adpValue(player, pickNum) {
    if (player.udA == null) return { tag: null, multiplier: 1.0 };
    const ud = player.udA;
    const myRank = player.rank;
    const diff = ud - myRank; // +ve = UD has them later than Jack (Jack high on them)
    if (diff >= 24) return { tag: "STEAL", multiplier: 1.20 };
    if (diff >= 12) return { tag: "Value", multiplier: 1.10 };
    if (diff <= -18) return { tag: "Reach", multiplier: 0.85 };
    if (diff <= -10) return { tag: "Stretch", multiplier: 0.95 };
    return { tag: null, multiplier: 1.0 };
  }

  // Bye-week clustering penalty: if I already have N at a position
  // and this player shares their bye with M of those, the lineup gets
  // hurt that week. Best ball still scores everyone, but stacking too many
  // byes wastes draft capital.
  function byeMult(player, roster) {
    if (player.bye == null) return 1.0;
    const sameBye = roster.filter(p => p.bye === player.bye).length;
    const samePosBye = roster.filter(p => p.bye === player.bye && p.s === player.s).length;
    if (samePosBye >= 2) return 0.85;       // 3 of same pos sharing bye = bad
    if (sameBye >= 4) return 0.92;          // crowded bye week
    return 1.0;
  }

  // Stack bonus: QB on same team as my WR/TE (or vice versa) for week 16/17 correlation.
  // Currently checks any-week, but once schedule is loaded we'll bias toward W16/17 games.
  function stackBonus(player, roster) {
    if (!player.t) return 1.0;
    if (player.s === "QB") {
      const targets = roster.filter(p => p.t === player.t && (p.s === "WR" || p.s === "TE"));
      if (targets.length >= 2) return 1.10;
      if (targets.length === 1) return 1.05;
    } else if (player.s === "WR" || player.s === "TE") {
      const qb = roster.find(p => p.t === player.t && p.s === "QB");
      if (qb) return 1.05;
    }
    return 1.0;
  }

  // v0.10.54: Roster-aware REC scoring (powers the sidebar "REC" sort).
  // Rank is still the base signal; these multipliers re-order nearby players:
  //   +  stack boost      — completing/extending a QB↔pass-catcher stack
  //   +  need boost       — below the format floor / open slots, grows late
  //   −  saturation nerf  — at/over target count (banked-VOR saturation
  //                         moved to recValueMults in v0.10.56)
  function recPositionMults(myRoster, isSuperflex, round, mode) {
    const f = fmtMode(isSuperflex, mode);
    const counts = rosterCounts(myRoster);
    const out = {};
    for (const pos of ["QB", "RB", "WR", "TE"]) {
      const have = counts[pos] || 0;
      const target = f.slots[pos] || 0;
      const min = f.minPos[pos] || 0;
      const max = f.maxPos[pos] || 0;
      // Hard ceiling — never push players at a maxed-out position
      if (have >= max) { out[pos] = 0.25; continue; }
      let m = 1.0;
      if (have < min) {
        // Deficit vs the hard floor, more urgent as the draft ages
        const deficit = min - have;
        m *= 1 + Math.min(0.15, 0.04 * deficit + 0.01 * Math.max(0, round - 4));
      } else if (have < target) {
        m *= 1.02;
      }
      if (have >= target) m *= 0.85; // slots filled — fade further adds
      out[pos] = m;
    }
    return out;
  }

  // v0.10.56: Per-position VALUE CHART + heavy buff/nerf multipliers.
  // Two signals per position:
  //   AVAIL — value still on the shelf: avg VOR of the top-3 available at
  //           the position, compared cross-position. Significantly above
  //           the other positions → heavy buff (value pocket); a value
  //           desert → nerf.
  //   FILL  — how full the position already is: banked-VOR share vs its
  //           fair share of roster slots, plus (redraft) raw counts.
  // Format-aware per Jack's spec:
  //   Best ball — surplus depth keeps scoring weeks, so fill nerfs are
  //               moderate and share-based.
  //   Redraft   — bench value dies fast: a 2nd QB/TE is bye insurance, a
  //               3rd is a dead pick. Fill nerfs are much heavier and the
  //               avail buff/nerf responds harder (waivers can't replace a
  //               missed value pocket at RB/WR mid-draft).
  function recValueMults(available, myRoster, isSuperflex, mode) {
    const rd = mode === "rd";
    const f = fmtMode(isSuperflex, mode);
    const counts = rosterCounts(myRoster);
    const banked = rosterVorByPos(myRoster, isSuperflex);
    let totalBanked = 0;
    for (const pos of ["QB", "RB", "WR", "TE"]) totalBanked += Math.max(0, banked[pos] || 0);

    // Available value on the shelf: avg of the top-3 VOR at each position.
    // Top-3 (not the single best) so one outlier doesn't define the pocket.
    const avail3 = {};
    for (const pos of ["QB", "RB", "WR", "TE"]) {
      const vs = [];
      for (const p of available || []) {
        if (p.s !== pos) continue;
        const v = playerVor(p, isSuperflex);
        if (v != null) vs.push(v);
      }
      vs.sort((a, b) => b - a);
      avail3[pos] = vs.length
        ? vs.slice(0, 3).reduce((s, v) => s + v, 0) / Math.min(3, vs.length)
        : null;
    }
    const vals = ["QB", "RB", "WR", "TE"].map(p => avail3[p]).filter(v => v != null);
    const avgAvail = vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length : null;

    const out = {};
    for (const pos of ["QB", "RB", "WR", "TE"]) {
      const have = counts[pos] || 0;
      const target = f.slots[pos] || 0;
      // AVAIL: linear in (this pos − cross-pos average), clamped
      let relMult = 1.0, relVal = null;
      if (avail3[pos] != null && avgAvail != null) {
        relVal = avail3[pos] - avgAvail;
        relMult = 1 + relVal / (rd ? 100 : 120);
        const lo = rd ? 0.70 : 0.78, hi = rd ? 1.30 : 1.22;
        relMult = Math.max(lo, Math.min(hi, relMult));
      }
      // FILL
      let fillMult = 1.0;
      const share = totalBanked > 0 ? Math.max(0, banked[pos] || 0) / totalBanked : 0;
      const expShare = target > 0 ? target / f.rounds : 0.01;
      const shareRatio = expShare > 0 ? share / expShare : 0;
      if (rd) {
        // Count-based bench death first
        if (pos === "QB" || pos === "TE") {
          if (have >= 2) fillMult = 0.30;
          else if (have >= 1) fillMult = 0.80;
        } else {
          if (have >= target) fillMult = 0.45;
          else if (have >= target - 1) fillMult = 0.75;
        }
        // Banked-value share nerf, heavier than best ball
        if (totalBanked >= 60 && have >= 2) {
          if (shareRatio >= 2.2) fillMult *= 0.70;
          else if (shareRatio >= 1.6) fillMult *= 0.82;
          else if (shareRatio >= 1.25) fillMult *= 0.92;
        }
      } else {
        if (totalBanked >= 60 && have >= 2) {
          if (shareRatio >= 2.2) fillMult = 0.70;
          else if (shareRatio >= 1.6) fillMult = 0.82;
          else if (shareRatio >= 1.25) fillMult = 0.92;
        }
      }
      const mult = Math.max(0.25, Math.min(1.35, relMult * fillMult));
      out[pos] = {
        avail: avail3[pos] != null ? Math.round(avail3[pos]) : null,
        rel: relVal != null ? Math.round(relVal) : null,
        relMult: Math.round(relMult * 100) / 100,
        fillMult: Math.round(fillMult * 100) / 100,
        fillPct: target > 0 ? Math.round(Math.min(1, have / target) * 100) : 0,
        shareRatio: Math.round(shareRatio * 100) / 100,
        have: have, target: target,
        mult: Math.round(mult * 100) / 100
      };
    }
    return out;
  }

  // Stack multiplier for the REC score — stronger than the visual stackBonus
  // so completing a stack actually re-orders close calls in the rec list.
  function recStackMult(player, roster) {
    if (!player || !player.t) return 1.0;
    if (player.s === "QB") {
      const targets = roster.filter(p => p.t === player.t && (p.s === "WR" || p.s === "TE"));
      if (targets.length >= 2) return 1.12;
      if (targets.length === 1) return 1.07;
    } else if (player.s === "WR" || player.s === "TE") {
      const qb = roster.find(p => p.t === player.t && p.s === "QB");
      if (qb) {
        const pieces = roster.filter(p => p.t === player.t && (p.s === "WR" || p.s === "TE")).length;
        return pieces >= 2 ? 1.03 : 1.07; // 3rd+ catcher of the same stack adds little
      }
    }
    return 1.0;
  }

  // v0.16.1 (Jack's rule): "STACK NOW" — when a WR/TE is already rostered
  // and that team's QB's market window is RIGHT NOW, the stack-completing QB
  // should shoot to the top of the recs. "Right now" = his ADP is within the
  // next couple of picks (≤ actPick + STACK_NOW_WINDOW) AND he won't survive
  // to your next turn (adp < waitPick — otherwise you can wait and recWaitMult
  // handles it). Deliberately much stronger than recStackMult: this is a
  // take-him-or-lose-the-stack moment, not a tiebreaker.
  const STACK_NOW_WINDOW = 5;
  function stackNowMult(player, roster, actPick, waitPick, isSuperflex) {
    if (!player || !player.t || player.s !== "QB") return 1.0;
    const catchers = (roster || []).filter(p => p.t === player.t && (p.s === "WR" || p.s === "TE"));
    if (!catchers.length) return 1.0;
    const adp = (isSuperflex && player.sfa != null) ? player.sfa : player.udA;
    if (adp == null || actPick == null) return 1.0;
    if (adp > actPick + STACK_NOW_WINDOW) return 1.0;      // window not here yet — wait
    if (waitPick != null && adp >= waitPick) return 1.0;   // survives to next turn — no urgency
    return catchers.length >= 2 ? 1.5 : 1.35;
  }

  // v0.10.55: ADP-aware "wait" fade for the REC score. If the market says
  // a player goes well after the pick where the user will actually act,
  // he shouldn't be the recommended pick right now — you can take scarcer
  // value and come back for him. Uses UD ADP (sfa in superflex).
  //   adp ≥ waitPick+5 → 0.75  (likely survives to your NEXT turn — wait)
  //   adp ≥ waitPick   → 0.85  (coin-flip to survive your next turn)
  //   adp ≥ actPick+ts → 0.93  (goes a round+ later, but gone before your
  //                             next turn — mild reach fade only)
  function recWaitMult(player, actPick, waitPick, teamSize, isSuperflex) {
    const adp = (isSuperflex && player.sfa != null) ? player.sfa : player.udA;
    if (adp == null) return 1.0;
    if (waitPick != null) {
      if (adp >= waitPick + 5) return 0.75;
      if (adp >= waitPick) return 0.85;
    }
    if (actPick != null && adp - actPick >= (teamSize || 12)) return 0.93;
    return 1.0;
  }

  // First pick belonging to `slot` at or after `fromPick` (snake order).
  function userPickAtOrAfter(fromPick, slot, teamSize) {
    const ts = teamSize || 12;
    for (let pk = fromPick; pk <= fromPick + ts * 2; pk++) {
      const round = Math.ceil(pk / ts);
      const idx = pk - (round - 1) * ts; // 1..ts within the round
      const slotAt = (round % 2 === 1) ? idx : (ts - idx + 1);
      if (slotAt === slot) return pk;
    }
    return fromPick + ts;
  }

  // v0.10.57: BBM-data value mults — replaces VOR as the value signal for
  // standard best ball. For each position, the REAL historical advance
  // rate (BBM II–VI, 2.6M Underdog teams) of taking your NEXT player at
  // that position in the current round, blended 50/30/20 QF/SF/Finals and
  // compared across positions: significantly above the rest → heavy buff,
  // significantly below → heavy nerf. "Filled up" is baked into the data
  // itself — the tables key on your Nth positional pick, so a 3rd QB in
  // R8 carries its true (terrible) history instead of a synthetic nerf.
  // n-weighted blend of a pick cell with its round neighbors. Single cells
  // carry visible noise even at n~150k — WR#3-in-R8 (15.46%) sits BELOW both
  // R7 (16.81%) and R9 (16.34%), and that dip alone was steering picks.
  function _bbmPickCellSmoothed(pos, nth, rd) {
    if (typeof BBM_PICK_BY_RANK_ROUND === "undefined") return null;
    const tbl = BBM_PICK_BY_RANK_ROUND[pos.toLowerCase()];
    const row = tbl && tbl[nth];
    if (!row) return null;
    let n = 0, qf = 0, sf = 0, sfN = 0, fin = 0, finN = 0;
    for (let d = -1; d <= 1; d++) {
      const cell = row[rd + d];
      if (!cell || cell.qf == null || !cell.n) continue;
      n += cell.n; qf += cell.n * cell.qf;
      if (cell.sf != null) { sfN += cell.n; sf += cell.n * cell.sf; }
      if (cell.fin != null) { finN += cell.n; fin += cell.n * cell.fin; }
    }
    if (!n) return null;
    return { qf: qf / n, sf: sfN ? sf / sfN : null, fin: finN ? fin / finN : null, n: n };
  }
  function _bbmPickLift(cell) {
    if (!cell || cell.qf == null) return null;
    const baseQf = BBM_BASELINE_QF_RATE;
    const baseSf = (typeof BBM_BASELINE_SF_RATE !== "undefined") ? BBM_BASELINE_SF_RATE : 0.01320;
    const baseFin = (typeof BBM_BASELINE_FIN_RATE !== "undefined") ? BBM_BASELINE_FIN_RATE : 0.00082;
    const qL = cell.qf / baseQf;
    const sL = cell.sf != null ? cell.sf / baseSf : qL;
    const fL = cell.fin != null ? cell.fin / baseFin : qL;
    return 0.5 * qL + 0.3 * sL + 0.2 * fL;
  }

  // DEFERRAL PRICING (Jack, 2026-08-05): "does it take into account the
  // difference between taking a WR3 in round 8 vs 9+?" It didn't — valueM
  // priced only the current round's cell and re-priced next round when it
  // arrived, so 'who can I wait on' was invisible at decision time. This term
  // compares taking your Nth positional pick NOW (smoothed cell) against the
  // n-weighted tail of every LATER round — 9+ rather than just 9, per Jack,
  // because the tail is the empirical distribution of when teams that waited
  // actually got around to it, cliff rounds included. Waiting on a position
  // whose tail holds up (WR3) fades it now; a position whose value decays if
  // deferred (RB4) gets pushed now.
  function recDeferralMults(counts, round) {
    if (typeof BBM_PICK_BY_RANK_ROUND === "undefined" || typeof BBM_BASELINE_QF_RATE === "undefined") return null;
    const r = Math.max(1, Math.min(18, round || 1));
    if (r >= 17) return null;                      // no meaningful tail left
    const out = {};
    for (const pos of ["QB", "RB", "WR", "TE"]) {
      const nth = (counts[pos] || 0) + 1;
      const nowL = _bbmPickLift(_bbmPickCellSmoothed(pos, nth, r));
      if (nowL == null) continue;
      const tbl = BBM_PICK_BY_RANK_ROUND[pos.toLowerCase()];
      const row = tbl && tbl[nth];
      if (!row) continue;
      let n = 0, acc = 0;
      for (let rd = r + 1; rd <= 18; rd++) {
        const cell = row[rd];
        if (!cell || !cell.n) continue;
        const L = _bbmPickLift(cell);
        if (L == null) continue;
        n += cell.n; acc += cell.n * L;
      }
      if (n < 5000) continue;                      // thin tail: no verdict
      const tailL = acc / n;
      out[pos] = {
        mult: Math.max(0.90, Math.min(1.10, 1 + 0.7 * (nowL - tailL))),
        now: Math.round(nowL * 1000) / 1000,
        tail: Math.round(tailL * 1000) / 1000,
        tailN: n,
      };
    }
    return Object.keys(out).length >= 2 ? out : null;
  }

  function recBbmValueMults(myRoster, round) {
    if (typeof BBM_PICK_BY_RANK_ROUND === "undefined" || typeof BBM_BASELINE_QF_RATE === "undefined") return null;
    const counts = rosterCounts(myRoster);
    const baseQf = BBM_BASELINE_QF_RATE;
    const baseSf = (typeof BBM_BASELINE_SF_RATE !== "undefined") ? BBM_BASELINE_SF_RATE : 0.01320;
    const baseFin = (typeof BBM_BASELINE_FIN_RATE !== "undefined") ? BBM_BASELINE_FIN_RATE : 0.00082;
    const r = Math.max(1, Math.min(18, round || 1));
    const lifts = {};
    for (const pos of ["QB", "RB", "WR", "TE"]) {
      const tbl = BBM_PICK_BY_RANK_ROUND[pos.toLowerCase()];
      const nextRank = (counts[pos] || 0) + 1;
      // Smoothed over the neighboring rounds so one noisy cell can't steer
      // the pick on its own (see _bbmPickCellSmoothed).
      let cell = _bbmPickCellSmoothed(pos, nextRank, r);
      // Sparse rows (n<200 cells are absent): nearest round with data is a
      // fair proxy before giving up entirely.
      if (!cell && tbl && tbl[nextRank]) {
        for (let d = 2; d <= 4 && !cell; d++) {
          cell = tbl[nextRank][r - d] || tbl[nextRank][r + d];
        }
      }
      if (!cell || cell.qf == null) { lifts[pos] = null; continue; }
      const qL = cell.qf / baseQf;
      const sL = cell.sf != null ? cell.sf / baseSf : qL;
      const fL = cell.fin != null ? cell.fin / baseFin : qL;
      lifts[pos] = { lift: 0.5 * qL + 0.3 * sL + 0.2 * fL, nextRank: nextRank, n: cell.n };
    }
    const vals = ["QB", "RB", "WR", "TE"].map(p => lifts[p]).filter(Boolean).map(x => x.lift);
    if (vals.length < 2) return null;
    const avg = vals.reduce((s, v) => s + v, 0) / vals.length;
    const out = {};
    for (const pos of ["QB", "RB", "WR", "TE"]) {
      const L = lifts[pos];
      if (!L) { out[pos] = { lift: null, rel: null, nextRank: (counts[pos] || 0) + 1, n: null, have: counts[pos] || 0, mult: 1.0 }; continue; }
      const rel = L.lift - avg;
      const mult = Math.max(0.55, Math.min(1.35, 1 + rel * 0.8));
      out[pos] = {
        lift: Math.round(L.lift * 100) / 100,
        rel: Math.round(rel * 100) / 100,
        nextRank: L.nextRank, n: L.n,
        have: counts[pos] || 0,
        mult: Math.round(mult * 100) / 100
      };
    }
    return out;
  }

  // v0.10.57: unified value-chart source. Standard best ball → real BBM
  // history (recBbmValueMults); Superflex / Redraft → VOR-based model
  // (BBM tables are STD-best-ball only). Both shapes expose .mult per pos.
  function recValueChartData(available, myRoster, isSuperflex, mode, round) {
    if (mode !== "rd" && !isSuperflex) {
      const bbm = recBbmValueMults(myRoster, round);
      if (bbm) return { source: "bbm", positions: bbm };
    }
    return { source: "vor", positions: recValueMults(available, myRoster, isSuperflex, mode) };
  }

  // ---------- Core scoring ----------
  // When isSuperflex is true:
  //   - "ud"        → use player.sfa (Underdog Superflex ADP) instead of udA
  //   - "jacks"/etc → use player.sfRank (derived from sfa) instead of player.rank
  //                   (with fallback to standard rank if sfRank/sfa missing)
  // The fallback matters because some players (devy, deep bench) don't have
  // an Underdog superflex ADP — we still want them ranked, just at the bottom
  // of the superflex board.
  function rankFromSource(player, src, isSuperflex) {
    if (isSuperflex) {
      if (src === "ud") return player.sfa != null ? Math.round(player.sfa) : (player.udA != null ? Math.round(player.udA) + 200 : 9999);
      // Jack's / FP / Consensus all use sfRank when available; otherwise fall
      // back to standard rank with a heavy penalty so non-SF-ranked players
      // sink to the bottom rather than disappearing.
      const sfFallback = (player.rank || 9999) + 200;
      if (src === "fp") return player.sfRank || (player.fpR ? player.fpR + 100 : sfFallback);
      if (src === "sleeper") return player.sfRank || (player.slR ? player.slR + 100 : sfFallback);
      if (src === "consensus") {
        const arr = [];
        if (player.sfRank) arr.push(player.sfRank);
        if (player.sfa != null) arr.push(Math.round(player.sfa));
        if (arr.length) return arr.reduce((a, b) => a + b, 0) / arr.length;
        return sfFallback;
      }
      // default = jack's superflex. sfRank (bridge personal board / ADP fill)
      // wins when the site bridge ran; jSf is Jack's official SF board baked
      // at export time so the SF order is right even with no bridge sync.
      return player.sfRank || player.jSf || sfFallback;
    }
    if (src === "ud") return player.udA != null ? Math.round(player.udA) : 9999;
    if (src === "fp") return player.fpR || 9999;
    if (src === "sleeper") return player.slR || 9999;
    if (src === "consensus") {
      const arr = [];
      if (player.rank) arr.push(player.rank);
      if (player.fpR) arr.push(player.fpR);
      if (player.slR) arr.push(player.slR);
      if (player.udA != null) arr.push(Math.round(player.udA));
      return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 9999;
    }
    // Standard = best ball: prefer Jack's official bestball board (jBb,
    // baked at export) over the d.js redraft order. Bridge myRank overrides
    // still land on player.rank, so jBb-missing players keep working.
    return player.jBb || player.rank || 9999;
  }

  // NEED = short at the position AND the position is actually drying up.
  //
  // The old version asked only "do I have fewer than N?", so on a roster the
  // helper couldn't read it lit up EVERY position at once, and even on a good
  // read it shouted QB at you while 6 of 12 starting QB jobs were still
  // unfilled leaguewide. Jack, 2026-08-05: "if I have a QB and only 6 are off
  // the board I don't need another QB yet."
  //
  // `gone` is how many at that position have left the board. Compare it to the
  // leaguewide STARTING JOBS at the position (teams x starters) to get a
  // depletion share, and require that share to clear a bar that eases as the
  // draft ages — late on there are fewer picks left to fix a hole, so a
  // thinner run is enough to make it urgent.
  const NEED_STARTERS = { QB: 1, RB: 2, WR: 3, TE: 1 };
  function detectNeed(pos, counts, round, isSuperflex, teamSize, gone, rosterKnown, quality) {
    if (round < 6) return null;
    // A roster we failed to read is not evidence of need. Claiming every
    // position is a need off an empty roster is worse than saying nothing.
    if (rosterKnown === false) return null;
    const starters = pos === "QB" && isSuperflex ? 2 : NEED_STARTERS[pos];
    if (!starters) return null;
    // WHICH ones you took, not how many. QB1 closes the position outright;
    // QB12 as your only QB does not. Four RBs who are RB29/30/42/43 still
    // leave you needing a real one (Jack, 2026-08-05). `quality` is the sum of
    // e^-(posRank-1)/6 over what you own at the position, so 1st ~1.00, 3rd
    // ~0.72, 12th ~0.16, 30th ~0.01 — a pile of late bodies barely registers.
    const fill = ((quality && quality[pos]) || 0) / starters;
    if (fill >= 0.8) return null;
    const ts = teamSize || 12;
    const jobs = ts * starters;
    const depletion = jobs > 0 ? ((gone && gone[pos]) || 0) / jobs : 1;
    const bar = Math.max(0.45, 0.85 - 0.04 * (round - 6));
    return depletion >= bar ? pos.toLowerCase() : null;
  }

  // PREFIX-BUILD multiplier (v0.10.71). recBbmValueMults already asks "what did
  // your Nth player at this position, taken this round, historically advance
  // at?" — but it's blind to the ORDER you got there. by_prefix_build knows the
  // difference between RRR→RB and WWW→RB: same 4th pick, very different teams.
  //
  // bbmNextPickRates() already does the hard part (prefix-conditional lookup
  // across every reachable final build, n-weighted, with MIN_POS/MAX_POS
  // filtering and by-round fallbacks); it was only ever used to decide which
  // card to HIGHLIGHT. This turns it into an actual score term.
  //
  // Naturally self-limiting: prefixes top out at 6 characters, so once you're
  // 6 picks in, `prefix + pos` truncates back to the same string for all four
  // positions, every rate comes out equal, and the multiplier settles at 1.0.
  // It's an opening-sequence signal and it stops pretending otherwise.
  // BUILD-CONDITIONAL next-pick rates. The prefix table only knows your first
  // six picks; this is its analogue for the rest of the draft — for each
  // candidate position, aggregate the real advance rate of every FINAL build
  // reachable from (your current counts + that position), n-weighted, over
  // 2.5M BBM teams. Unlike bbmOptimalBuild's optimalRate ("the rate if you
  // play perfectly from here"), this can actually tell the four positions
  // apart, because adding a 4th TE genuinely closes off the builds that won.
  function bbmBuildConditionalRates(counts, slot) {
    if (typeof window === "undefined" || !window.BBM_DATA) return null;
    const data = window.BBM_DATA;
    const generic = data.by_build_w || data.by_build;
    if (!generic) return null;
    const need4 = (pos) => ({
      QB: (counts.QB || 0) + (pos === "QB" ? 1 : 0),
      RB: (counts.RB || 0) + (pos === "RB" ? 1 : 0),
      WR: (counts.WR || 0) + (pos === "WR" ? 1 : 0),
      TE: (counts.TE || 0) + (pos === "TE" ? 1 : 0),
    });
    const scan = (src, sfx, need) => {
      let totN = 0, weighted = 0;
      for (const key in src) {
        let bkey = key;
        if (sfx) {
          if (key.length <= sfx.length || key.indexOf(sfx) !== key.length - sfx.length) continue;
          bkey = key.slice(0, -sfx.length);
        }
        const ps = bkey.split("/").map(Number);
        if (ps.length !== 4) continue;
        if (ps[0] < need.QB || ps[1] < need.RB || ps[2] < need.WR || ps[3] < need.TE) continue;
        if (ps[0] < BBM_MIN_POS.QB || ps[1] < BBM_MIN_POS.RB ||
            ps[2] < BBM_MIN_POS.WR || ps[3] < BBM_MIN_POS.TE) continue;
        if (ps[0] > BBM_MAX_POS.QB || ps[1] > BBM_MAX_POS.RB ||
            ps[2] > BBM_MAX_POS.WR || ps[3] > BBM_MAX_POS.TE) continue;
        const st = src[key];
        if (!st || !st.n) continue;
        const r = st.q_rate_w != null ? st.q_rate_w : st.q_rate;
        if (r == null) continue;
        totN += st.n;
        weighted += st.n * r;
      }
      return totN >= 1000 ? { rate: weighted / totN, n: totN } : null;
    };
    const run = (src, sfx) => {
      const out = {};
      for (const pos of ["QB", "RB", "WR", "TE"]) {
        const need = need4(pos);
        if (need[pos] > BBM_MAX_POS[pos]) continue;
        const cell = scan(src, sfx, need);
        if (cell) out[pos] = cell;
      }
      return Object.keys(out).length >= 2 ? out : null;
    };
    // Slot-conditioned history (by_construct_slot, build@slot) when the user's
    // draft slot is known — turn-of-the-snake teams win with different shapes
    // than middle picks. ALL-OR-NOTHING: if any candidate position lacks slot
    // sample, drop back to the generic table for every position, because
    // mixing slot cells for one position with generic cells for another is the
    // cross-table comparison the prefix guard exists to prevent.
    if (slot != null && data.by_construct_slot) {
      const posN = ["QB", "RB", "WR", "TE"].filter(p => need4(p)[p] <= BBM_MAX_POS[p]).length;
      const slotOut = run(data.by_construct_slot, "@" + slot);
      if (slotOut && Object.keys(slotOut).length === posN) return slotOut;
    }
    return run(generic, null);
  }

  const POS_LETTER = { QB: 'Q', RB: 'R', WR: 'W', TE: 'T' };

  // ---------- measured-history multipliers (v0.12.0) ----------
  // Wires in the last of the shipped BBM aggregation tables, which were loaded
  // on every page and consumed by NOTHING: bbm_path_optimal.js (RB path, QB/TE
  // timing, WR pacing), bbm_stack_comp_multistage.js (stack composition) and
  // bbm_structural_multistage.js (bye concentration + same-team
  // cannibalization). All standard-best-ball data -> stdBB gate only.
  const BBM_BASE_RATES = { qf: 0.16668, sf: 0.01320, fin: 0.00082 };
  // Blended lift for one {qf,sf,fin,n} cell, 50/30/20 QF/SF/Finals — the same
  // blend the value chart uses. Rare-event levels only vote when the sample
  // could actually contain them (same thresholds as bbmNextPickRates): a
  // fin=0 on n=2,000 is 1.6 expected finals teams, i.e. noise, and blending
  // it in would crush the lift.
  function _bbmLift(cell) {
    if (!cell || !cell.n || cell.n < 1000 || cell.qf == null) return null;
    let acc = 0.5 * (cell.qf / BBM_BASE_RATES.qf), w = 0.5;
    if (cell.sf != null && cell.n >= 5000) { acc += 0.3 * (cell.sf / BBM_BASE_RATES.sf); w += 0.3; }
    if (cell.fin != null && cell.n >= 30000) { acc += 0.2 * (cell.fin / BBM_BASE_RATES.fin); w += 0.2; }
    return acc / w;
  }
  function _bbmWavg(cells, filter) {
    let totN = 0, acc = 0;
    for (const k in cells) {
      if (filter && !filter(k, cells[k])) continue;
      const L = _bbmLift(cells[k]);
      if (L == null) continue;
      totN += cells[k].n;
      acc += cells[k].n * L;
    }
    return totN ? { lift: acc / totN, n: totN } : null;
  }

  // TIMING / PACING (bbm_path_optimal.js). Every mult is WITHIN one table and
  // one conditioning key — "teams on my path that ended with one more at this
  // position" vs "all teams on my path" — never a cross-table comparison.
  // Path reconstruction needs no slot: in a snake draft every team picks once
  // per round, so my kth pick IS round k and roster order = round order.
  function bbmTimingMults(myRoster, counts, round) {
    if (typeof BBM_QB_TIMING_LIFT === "undefined") return null;
    const roster = myRoster || [];
    const firstRound = (pos) => {
      for (let i = 0; i < roster.length; i++) if (roster[i].s === pos) return i + 1;
      return null;
    };
    const qbBucket = (r) => r <= 3 ? "early" : r <= 6 ? "mid" : r <= 9 ? "late" : r <= 12 ? "late2" : "verylate";
    const teBucket = (r) => r <= 4 ? "early" : r <= 8 ? "mid" : r <= 12 ? "late" : "verylate";
    const out = {};
    // First QB/TE: taking him NOW locks the timing bucket — compare that
    // bucket's outcome to the n-weighted average over all timings. This is
    // where "rounds 4-6 are the QB dead zone" lives in the data.
    const firstPickMult = (table, bucket) => {
      const mine = _bbmWavg(table[bucket]);
      if (!mine) return null;
      let accL = 0, accN = 0;
      for (const b in table) {
        const w = _bbmWavg(table[b]);
        if (w) { accL += w.lift * w.n; accN += w.n; }
      }
      return accN ? mine.lift / (accL / accN) : null;
    };
    const nextMult = (table, key, have) => {
      const cells = table[key];
      if (!cells) return null;
      const more = _bbmWavg(cells, (k) => parseInt(k, 10) >= have + 1);
      const all = _bbmWavg(cells);
      return more && all && all.lift > 0 ? more.lift / all.lift : null;
    };
    {
      const have = counts.QB || 0;
      const m = have === 0
        ? firstPickMult(BBM_QB_TIMING_LIFT, qbBucket(round))
        : nextMult(BBM_QB_TIMING_LIFT, qbBucket(firstRound("QB") || round), have);
      if (m != null) out.QB = m;
    }
    if (typeof BBM_TE_TIMING_LIFT !== "undefined") {
      const have = counts.TE || 0;
      const m = have === 0
        ? firstPickMult(BBM_TE_TIMING_LIFT, teBucket(round))
        : nextMult(BBM_TE_TIMING_LIFT, teBucket(firstRound("TE") || round), have);
      if (m != null) out.TE = m;
    }
    if (typeof BBM_RB_PATH_LIFT !== "undefined") {
      const have = counts.RB || 0;
      const byR4 = round > 4
        ? roster.slice(0, 4).filter(p => p.s === "RB").length
        : Math.min(have, 4);
      const m = nextMult(BBM_RB_PATH_LIFT, Math.min(byR4, 4), have);
      if (m != null) out.RB = m;
    }
    if (typeof BBM_WR_PACING_LIFT !== "undefined") {
      const have = counts.WR || 0;
      const byR6 = round > 6 ? roster.slice(0, 6).filter(p => p.s === "WR").length : have;
      const m = nextMult(BBM_WR_PACING_LIFT, byR6 <= 2 ? "slow" : byR6 <= 4 ? "med" : "heavy", have);
      if (m != null) out.WR = m;
    }
    for (const k in out) out[k] = Math.max(0.85, Math.min(1.18, out[k]));
    return out;
  }

  // STACK COMPOSITION (bbm_stack_comp_multistage.js) — replaces the hand-tuned
  // 1.07/1.12 guesses with measured pattern rates. The headline the heuristic
  // could never know: the SECOND same-team WR is a measured NEGATIVE
  // (wr1_and_wr2 advances at 13.5% vs 19.1% for wr1_only) — over-concentration
  // loses, while the heuristic still paid a bonus for it.
  // Multi-QB stacking increments (scripts/_bbm_multi_qb_stacks.json, n=2.02M):
  // teams by COUNT of stacked QBs advanced 0.937 / 0.969 / 0.990 / 1.075 /
  // 1.023 — each ADDITIONAL stack is worth its step ratio. The 2->3 step
  // (x1.086) is the curve's sweet spot. Per-year splits wobble (BBM V is
  // flat), so this stays a modest increment, not another big lever.
  const BBM_MULTI_STACK_STEP = [1.034, 1.022, 1.086, 0.951];
  function _qbStackCount(roster) {
    let k = 0;
    for (const q of roster || []) {
      if (q.s !== "QB" || !q.t) continue;
      if ((roster || []).some(p => p !== q && p.t === q.t && (p.s === "WR" || p.s === "TE"))) k++;
    }
    return k;
  }
  function bbmStackMultFor(player, roster) {
    if (typeof BBM_STACK_COMP_MULTI === "undefined" || !player || !player.t) return null;
    const L = (k) => _bbmLift(BBM_STACK_COMP_MULTI[k]);
    const qbs = (roster || []).filter(p => p.s === "QB" && p.t);
    if (player.s === "QB") {
      const mates = (roster || []).filter(p => p.t === player.t && (p.s === "WR" || p.s === "TE"));
      if (!mates.length) return null;
      if (!qbs.length) {
        // first QB, catchers already waiting: the primary-stack pattern table
        const a = L(mates.some(p => p.s === "WR") ? "wr1_only" : "te1_only"), b = L("no_stack");
        return a != null && b != null && b > 0 ? a / b : null;
      }
      // an ADDITIONAL QB completing another stack: multi-stack step ratio
      return BBM_MULTI_STACK_STEP[Math.min(_qbStackCount(roster), 3)];
    }
    // Catcher/RB: match against ANY of my QBs, not just the first (QB2 stacks
    // were invisible before this — a Jack's-audit find, 2026-08-05).
    const qbMate = qbs.find(q => q.t === player.t);
    if (!qbMate) return null;
    const isPrimary = qbMate === qbs[0];
    const mates = roster.filter(p => p !== qbMate && p.t === qbMate.t && p.s !== "QB");
    if (!mates.length) {
      if (!isPrimary) {
        // first mate for a LATER QB = creating one more stack
        return BBM_MULTI_STACK_STEP[Math.min(_qbStackCount(roster), 3)];
      }
      const key = player.s === "TE" ? "te1_only" : player.s === "RB" ? "rb1_only" : "wr1_only";
      const a = L(key), b = L("no_stack");
      return a != null && b != null && b > 0 ? a / b : null;
    }
    // adding to an existing stack: pattern table (approximated for QB2+ stacks
    // by the same per-stack composition rates)
    const hasWR = mates.some(p => p.s === "WR"), hasTE = mates.some(p => p.s === "TE");
    const curKey = hasWR ? "wr1_only" : hasTE ? "te1_only" : "rb1_only";
    let newKey = null;
    if (hasWR && player.s === "WR") newKey = "wr1_and_wr2";
    else if (hasWR && player.s === "TE") newKey = "wr1_and_te1";
    else if (hasWR && player.s === "RB") newKey = "wr1_and_rb1";
    else if (hasTE && player.s === "WR") newKey = "wr1_and_te1";
    if (!newKey) return null;
    const a = L(newKey), b = L(curKey);
    return a != null && b != null && b > 0 ? a / b : null;
  }

  // STRUCTURE (bbm_structural_multistage.js): bye-week concentration (finally
  // scoring — byeMult was computed and never used), same-NFL-team RB
  // cannibalization, and same-team WRs WITHOUT that team's QB.
  function bbmStructMultFor(player, roster) {
    if (typeof BBM_STRUCT_MULTI === "undefined" || !player) return null;
    const ratio = (group, curK, newK) => {
      const g = BBM_STRUCT_MULTI[group];
      if (!g) return null;
      const a = _bbmLift(g[String(newK)]), b = _bbmLift(g[String(curK)]);
      return a != null && b != null && b > 0 ? a / b : null;
    };
    let m = 1.0, any = false;
    if (player.bye != null) {
      const byBye = {};
      for (const p of roster || []) if (p.bye != null) byBye[p.bye] = (byBye[p.bye] || 0) + 1;
      let curMax = 0;
      for (const b in byBye) curMax = Math.max(curMax, byBye[b]);
      const newSame = (byBye[player.bye] || 0) + 1;
      if (newSame > curMax) {
        // table starts at 3 — an 18-round roster almost always has 3+ sharing
        const r = ratio("bye", Math.max(curMax, 3), Math.max(newSame, 3));
        if (r != null) { m *= r; any = true; }
      }
    }
    if (player.s === "RB" && player.t) {
      const cur = (roster || []).filter(p => p.s === "RB" && p.t === player.t).length;
      if (cur >= 1) {
        const r = ratio("rb", cur, cur + 1);
        if (r != null) { m *= r; any = true; }
      }
    }
    if (player.s === "WR" && player.t) {
      const hasQB = (roster || []).some(p => p.s === "QB" && p.t === player.t);
      if (!hasQB) {
        const cur = (roster || []).filter(p => p.s === "WR" && p.t === player.t).length;
        if (cur >= 1) {
          const r = ratio("wr", cur, cur + 1);
          if (r != null) { m *= r; any = true; }
        }
      }
    }
    return any ? Math.max(0.85, Math.min(1.10, m)) : null;
  }

  // BRING-BACK (Jack's May-2026 study, scripts/_bbm_bringback_playoffs.json).
  // A bring-back = a player whose NFL team plays AGAINST your QB stack in
  // BBM's quarterfinal week (W15). The study's headline is that the COUNT is
  // noise (lifts 0.99-1.04 across 0/1/2/3+), and the GAME TOTAL is the signal:
  //   QF->SF lift vs no-bringback:  total >=47  1.117
  //                                 43-46       0.806
  //                                 <=42        0.733
  // Damping, deliberately asymmetric: the boost is halved because the lifts
  // are conditioned on already reaching QF; the penalties are quartered
  // because a low total partly indicts the STACK's own offense — which is
  // already on the roster and not something taxing this candidate can fix.
  // W16/SF->Fin shows the same direction but on ~30x less sample, so it is
  // not blended in. Uses MFF_PLAYOFF_SOS (live-refetched Vegas lines) and the
  // sidebar's teamAbbr() from the shared content-script scope.
  function bbmBringbackMultFor(player, roster) {
    if (typeof window === "undefined" || !window.MFF_PLAYOFF_SOS) return null;
    if (typeof teamAbbr !== "function") return null;
    if (!player || !player.t) return null;
    if (player.s !== "WR" && player.s !== "TE" && player.s !== "RB") return null;
    const qb1 = (roster || []).find(p => p.s === "QB" && p.t);
    if (!qb1 || player.t === qb1.t) return null;
    // A bring-back needs something to bring back to: QB1 + a same-team catcher
    const stacked = (roster || []).some(p => p !== qb1 && p.t === qb1.t && (p.s === "WR" || p.s === "TE"));
    if (!stacked) return null;
    const sAb = teamAbbr(qb1.t), pAb = teamAbbr(player.t);
    if (!sAb || !pAb) return null;
    const sos = window.MFF_PLAYOFF_SOS[sAb];
    const tbl = sos && (sos.QB || sos.WR);
    const g15 = tbl && (tbl["15"] || tbl[15]);
    if (!g15 || g15.opp !== pAb || g15.gameTotal == null) return null;
    const t = g15.gameTotal;
    if (t >= 47) return 1.058;
    if (t <= 42) return 0.933;
    return 0.951;
  }
  const PREFIX_MULT_LO = 0.80, PREFIX_MULT_HI = 1.25, PREFIX_MULT_K = 0.6;
  function recPrefixBuildMults(myRoster, opts) {
    if (typeof window === "undefined" || !window.BBM_DATA) return null;
    const roster = myRoster || [];
    const counts = rosterCounts(roster);
    const prefix = roster.slice(0, 6)
      .map(p => (p.s || "").charAt(0).toUpperCase())
      .filter(c => c === "Q" || c === "R" || c === "W" || c === "T")
      .join("");
    const rates = bbmNextPickRates(counts, null, roster.length,
      Object.assign({ prefix: prefix }, opts || {}));
    if (!rates || !rates.detail) return null;
    // Only compare LIKE WITH LIKE. bbmNextPickRates falls back per position —
    // prefix-conditional, then by-first-QB/TE-team-pick, then by-round, and
    // finally an OPTIMISTIC "rate if you play perfectly afterward" when it has
    // nothing. Those live on different scales, so cross-position comparison is
    // only valid among positions that all resolved to real prefix history.
    // Mixing them produced nonsense like three positions at 8-9% against a
    // 16.7% baseline purely because they'd fallen through to a different table.
    const usable = {};
    for (const pos of ["QB", "RB", "WR", "TE"]) {
      const d = rates.detail[pos];
      const r = rates[pos];
      if (!d || d.realRate == null || !d.realSrc) continue;
      if (String(d.realSrc).indexOf("prefix:") !== 0) continue;
      if (r == null || !(r > 0)) continue;
      usable[pos] = { rate: r, n: d.realN || 0, src: d.realSrc };
    }
    let pool = usable;
    let source = "prefix";
    let keys = Object.keys(pool);
    const spread = keys.length >= 2
      ? Math.max.apply(null, keys.map(k => pool[k].rate)) -
        Math.min.apply(null, keys.map(k => pool[k].rate))
      : 0;
    if (keys.length < 2 || spread <= 1e-9) {
      // Prefix keys cap at 6 characters, so from your 7th pick on `prefix+pos`
      // truncates to the SAME string for all four positions, every rate comes
      // back identical and this signal quietly dies — exactly when a 12-round
      // best ball draft still has most of its decisions left (Jack, 2026-08-05:
      // "did we add all the roster construction data?" — we had, but it was
      // inert by pick 90). Fall back to the BUILD-conditional rate, which keys
      // on your CURRENT roster counts rather than the opening sequence and so
      // keeps discriminating for the whole draft. Still like-for-like: every
      // position's number comes from the same bbmOptimalBuild call.
      const bc = bbmBuildConditionalRates(counts, opts && opts.slot != null ? opts.slot : null);
      if (!bc) return null;
      pool = {};
      for (const pos in bc) pool[pos] = { rate: bc[pos].rate, n: bc[pos].n, src: "build" };
      source = "build";
      keys = Object.keys(pool);
      if (keys.length < 2) return null;
    }
    const avg = keys.reduce((a, k) => a + pool[k].rate, 0) / keys.length;
    if (!(avg > 0)) return null;
    const out = {};
    for (const pos of ["QB", "RB", "WR", "TE"]) {
      const u = pool[pos];
      if (!u) { out[pos] = { mult: 1.0, rate: null, rel: null, src: null }; continue; }
      const rel = u.rate / avg - 1;
      out[pos] = {
        mult: Math.max(PREFIX_MULT_LO, Math.min(PREFIX_MULT_HI, 1 + rel * PREFIX_MULT_K)),
        rate: Math.round(u.rate * 10000) / 100,     // as a %
        rel: Math.round(rel * 1000) / 10,           // % vs the compared average
        n: u.n,
        src: u.src,
      };
    }
    out._prefix = prefix;
    out._source = source;
    out._recommended = rates.recommended || null;
    return out;
  }

  function scorePlayer(player, ctx) {
    const { round, counts, roster, pickNum, rankSrc = "jacks", isSuperflex = false, teamSize = FORMAT.teamSize, available = null, posMults = null, actPick = null, waitPick = null, valueMults = null, prefixMults = null, gone = null, rosterKnown = true, quality = null, timingMults = null, stdBB = false, needPos = null, deferMults = null, mode = "bb" } = ctx;
    const r = rankFromSource(player, rankSrc, isSuperflex);
    const base = 100 * Math.exp(-Math.pow(r / 80, 1.0));
    const adp = adpValue(player, pickNum);
    const bye = byeMult(player, roster);
    const stack = stackBonus(player, roster);
    const score = base;
    const needFlag = needPos && player.s === needPos ? needPos.toLowerCase() : null;
    const tierInfo = available ? detectVorTier(player, available, isSuperflex) : null;
    // v0.10.54: roster-aware REC score — rank base × need/saturation × stack.
    // v0.10.55: × ADP wait fade (don't recommend players you can get later).
    // v0.10.56: × value-chart mult (avail-value pocket buff / fill nerf).
    const posM = (posMults && posMults[player.s] != null) ? posMults[player.s] : 1.0;
    let stackM = recStackMult(player, roster);
    if (stdBB) {
      const ms = bbmStackMultFor(player, roster);
      if (ms != null) stackM = Math.max(0.85, Math.min(1.15, ms));
    }
    const waitM = recWaitMult(player, actPick, waitPick, teamSize, isSuperflex);
    // v0.16.1: STACK NOW — big urgency boost for the QB who completes an
    // existing WR/TE stack while his ADP window is at the current pick.
    // BEST BALL ONLY (Jack): W16/17 stack correlation is a tournament edge;
    // in redraft (mode "rd" — Weekly Winner etc.) stacking is not worth a
    // reach, so the urgency boost must never fire there.
    const stackNowM = mode !== "rd" ? stackNowMult(player, roster, actPick, waitPick, isSuperflex) : 1.0;
    // v0.16.3 (Jack, live draft 2026-08-05): with a strong QB1 already
    // banked, an UNSTACKED QB2 was still topping the recs on pure board rank
    // (Hurts #1 at R7 with Josh Allen rostered — the QB slot target is 2, so
    // the fill logic even mildly BOOSTED him). Rule: in 1QB modes, once you
    // hold a QB with elite banked quality (quality.QB ≥ .45 ≈ top-5), a QB
    // sharing no team with your WR/TEs is a dead mid-round pick — nerf hard,
    // tapering back to neutral by R13 when the real QB2 window opens. A QB
    // who WOULD stack with a rostered catcher is exempt: stacking is the
    // whole point of QB2 in best ball.
    let qb2M = 1.0;
    if (player.s === "QB" && !isSuperflex && counts && (counts.QB || 0) >= 1) {
      const hasStackPiece = (roster || []).some(p => p.t === player.t && (p.s === "WR" || p.s === "TE"));
      const qbQual = (quality && quality.QB) || 0;
      if (!hasStackPiece && qbQual >= 0.45) {
        const late = Math.max(0, Math.min(1, (round - 9) / 4)); // full nerf thru R9 → gone by R13
        qb2M = 0.78 + 0.22 * late;
      }
    }
    const valueM = (valueMults && valueMults[player.s]) ? valueMults[player.s].mult : 1.0;
    // NOTE: adpValue()'s multiplier (STEAL 1.20 / Value 1.10 / Stretch 0.95 /
    // Reach 0.85) is deliberately NOT applied. It scores board-vs-market
    // disagreement, and per Jack the only thing ADP should decide is whether a
    // player survives to your next pick — which is waitM's job, above. The
    // .tag still renders on the cards as information.
    // Tier-cliff mult: the last man before a big VOR dropoff at his position
    // is worth taking NOW — the alternative after the cliff is much worse.
    const tierM = tierInfo ? (tierInfo.type === "cliff" ? 1.06 : 1.03) : 1.0;
    const prefixM = (prefixMults && prefixMults[player.s]) ? prefixMults[player.s].mult : 1.0;
    const timingM = (stdBB && timingMults && timingMults[player.s] != null) ? timingMults[player.s] : 1.0;
    const structM = stdBB ? (bbmStructMultFor(player, roster) || 1.0) : 1.0;
    const deferM = (stdBB && deferMults && deferMults[player.s]) ? deferMults[player.s].mult : 1.0;
    const bringM = stdBB ? (bbmBringbackMultFor(player, roster) || 1.0) : 1.0;
    const recScore = base * posM * stackM * stackNowM * qb2M * waitM * valueM * tierM * prefixM * timingM * structM * deferM * bringM;
    const why = [];
    if (stackNowM > 1.0) why.push("STACK NOW");
    if (qb2M < 1.0) why.push("QB2 LATER");
    if (bringM >= 1.03) why.push("BRINGBACK");
    if (adp.tag) why.push(adp.tag);
    if (tierInfo) why.push(tierInfo.type === "cliff" ? "TIER!" : "TIER");
    return {
      score: Math.round(score * 10) / 10,
      base: Math.round(base * 10) / 10,
      r,
      recScore: Math.round(recScore * 10) / 10,
      recMult: Math.round(posM * stackM * stackNowM * qb2M * waitM * valueM * tierM * prefixM * timingM * structM * deferM * bringM * 100) / 100,
      prefixM: Math.round(prefixM * 100) / 100,
      deferM: Math.round(deferM * 100) / 100,
      bringM: Math.round(bringM * 100) / 100,
      timingM: Math.round(timingM * 100) / 100,
      structM: Math.round(structM * 100) / 100,
      flags: { stack: stack > 1.0, stackNow: stackNowM > 1.0, need: needFlag, bye: bye < 1.0, tier: tierInfo, wait: waitM < 1.0 ? waitM : null },
      why
    };
  }

  function recommend(args) {
    const {
      players, draftedSet, myRoster,
      pickNum = 1, slot = 6, teamSize = FORMAT.teamSize, topN = 6,
      rankSrc = "jacks", isSuperflex = false, mode = "bb"
    } = args;
    const round = pickToRound(pickNum, teamSize);
    const counts = rosterCounts(myRoster);
    const available = players.filter(p => !draftedSet.has(p.n) && !p.ir);
    const posMults = recPositionMults(myRoster, isSuperflex, round, mode);
    // v0.10.57: real-BBM-history value mults for standard best ball, VOR
    // model for SF/redraft.
    const valueMults = recValueChartData(available, myRoster, isSuperflex, mode, round).positions;
    // v0.10.55: the pick where the user will actually act (now, if on the
    // clock) and their following turn — drives the ADP wait fade.
    const actPick = userPickAtOrAfter(pickNum, slot, teamSize);
    const waitPick = userPickAtOrAfter(actPick + 1, slot, teamSize);
    // v0.10.71: order-conditional history. Same STD-best-ball gate as the
    // value chart — the BBM tables are standard-format only, so superflex and
    // redraft must not read them.
    const stdBB = mode !== "rd" && !isSuperflex;
    const prefixMults = stdBB ? recPrefixBuildMults(myRoster, { slot: slot }) : null;
    const timingMults = stdBB ? bbmTimingMults(myRoster, counts, round) : null;
    const deferMults = stdBB ? recDeferralMults(counts, round) : null;
    // How many at each position have already left the board — the supply side
    // of the need test above.
    const gone = { QB: 0, RB: 0, WR: 0, TE: 0 };
    for (const p of players) {
      if (gone[p.s] != null && draftedSet.has(p.n)) gone[p.s]++;
    }
    // If picks have been made but we matched NONE of them to this team, our
    // roster read is broken (usually an unset draft slot) — suppress need
    // rather than inventing one for every position.
    const rosterKnown = (myRoster && myRoster.length > 0) || pickNum <= teamSize;
    // Positional rank of every player on the active board, so what you already
    // own can be judged on quality rather than headcount.
    const posRank = new Map(), posRankByName = Object.create(null);
    {
      const byPos = {};
      for (const p of players) {
        const r = rankFromSource(p, rankSrc, isSuperflex);
        if (r == null || r >= 9999) continue;
        (byPos[p.s] = byPos[p.s] || []).push([p, r]);
      }
      for (const k in byPos) {
        byPos[k].sort((a, b) => a[1] - b[1]);
        byPos[k].forEach((e, i) => { posRank.set(e[0], i + 1); posRankByName[e[0].n] = i + 1; });
      }
    }
    const quality = { QB: 0, RB: 0, WR: 0, TE: 0 };
    // Decay half-life scales with the position's STARTER POOL (teams x
    // starters / 2): a flat /6 said De'Von Achane (RB8 of ~120) fills only a
    // third of one starter slot, which is how "NEED RB" fired at a roster
    // holding three real RBs. QB/TE keep the tight curve (pool 12); RB
    // relaxes to /12, WR to /18 — RB24 is a borderline starter in a 12-team
    // league and should read as roughly half a slot, not as nothing.
    const _qDecay = (pos) => {
      const st = pos === "QB" && isSuperflex ? 2 : NEED_STARTERS[pos];
      return Math.max(6, ((teamSize || 12) * (st || 1)) / 2);
    };
    for (const p of myRoster || []) {
      if (quality[p.s] == null) continue;
      const n = posRank.get(p) || posRankByName[p.n];
      if (!n) continue;
      quality[p.s] += Math.exp(-(n - 1) / _qDecay(p.s));
    }
    // NEED is a priority marker, not a checklist (Jack, 2026-08-05, twice):
    // "below the quality bar at a depleted position" is true nearly everywhere
    // by mid-draft, so flagging every qualifier lit up the whole board. Rank
    // the qualifiers by how empty x how depleted, and badge ONLY the winner —
    // the one position you are thinnest at right now.
    let needPos = null, needUrg = -1;
    for (const pos of ["QB", "RB", "WR", "TE"]) {
      const f = detectNeed(pos, counts, round, isSuperflex, teamSize, gone, rosterKnown, quality);
      if (!f) continue;
      const st = pos === "QB" && isSuperflex ? 2 : NEED_STARTERS[pos];
      const fill = ((quality && quality[pos]) || 0) / (st || 1);
      const jobs = (teamSize || 12) * (st || 1);
      const dep = jobs ? ((gone && gone[pos]) || 0) / jobs : 0;
      const urg = (1 - Math.min(1, fill)) * dep;
      if (urg > needUrg) { needUrg = urg; needPos = pos; }
    }
    const ctx = { round, counts, roster: myRoster, pickNum, rankSrc, isSuperflex, teamSize, available, posMults, actPick, waitPick, valueMults, prefixMults, gone, rosterKnown, quality, timingMults, stdBB, needPos, deferMults, mode };
    const candidates = [];
    for (const p of available) {
      const s = scorePlayer(p, ctx);
      candidates.push({ player: p, ...s });
    }
    candidates.sort((a, b) => (a.r || 9999) - (b.r || 9999));
    // ---- leapfrog guard (Jack, 2026-08-03) ----
    // A later-board candidate may only carry a HIGHER recScore than an
    // earlier-board one when the timing play is real: the better player's UD
    // ADP says he likely survives to your NEXT turn (take the one who won't
    // last, bank the better one) AND the two are ranked very close.
    // Cross-position: same test, except a position of NEED may jump a
    // position with abundant close-rank supply left. Otherwise the better
    // board player keeps the higher recScore no matter what the mults say.
    const guardList = candidates.slice(0, 30);
    for (let gi = 1; gi < guardList.length; gi++) {
      for (let gj = 0; gj < gi; gj++) {
        const better = guardList[gj], later = guardList[gi];
        // v0.16.3: two deliberate exemptions. A STACK NOW candidate may
        // leapfrog — the urgency boost IS the timing play the guard exists
        // to police. And a QB2-LATER-nerfed player forfeits protection —
        // his nerf is the engine saying "not now", so clamping everyone
        // else beneath him would keep him #1 and defeat the nerf.
        if (later.flags && later.flags.stackNow) continue;
        if (better.why && better.why.indexOf("QB2 LATER") >= 0) continue;
        if ((later.recScore || 0) <= (better.recScore || 0)) continue;
        const bAdp = (isSuperflex && better.player.sfa != null) ? better.player.sfa : better.player.udA;
        const survives = waitPick != null && bAdp != null && bAdp >= waitPick + 3;
        const close = ((later.r || 9999) - (better.r || 9999)) <= 6;
        let ok = survives && close;
        if (!ok && later.player.s !== better.player.s) {
          const needFlag = detectNeed(later.player.s, counts, round, isSuperflex, teamSize);
          if (needFlag) {
            const bR = better.r || 9999;
            ok = guardList.filter((c) => c.player.s === better.player.s &&
              (c.r || 9999) <= bR + (teamSize || 12) * 2).length >= 5;
          }
        }
        if (!ok) {
          later.recScore = Math.round(Math.max(0, (better.recScore || 0) - 0.1) * 10) / 10;
        }
      }
    }
    return candidates.slice(0, topN);
  }

  global.MFFEngine_detectNeed = detectNeed;

  function rosterReport(myRoster, pickNum, teamSize, isSuperflex, players, draftedSet) {
    if (teamSize == null) teamSize = FORMAT.teamSize;
    const counts = rosterCounts(myRoster);
    const byeMap = byeBreakdown(myRoster);
    const round = pickToRound(pickNum, teamSize);
    const totalPicks = myRoster.length;
    const f = fmt(isSuperflex);
    const remaining = f.rounds - totalPicks;
    const vorByPos = rosterVorByPos(myRoster, isSuperflex);
    const bestAvail = (players && draftedSet)
      ? bestVorAvailable(players, draftedSet, isSuperflex)
      : null;
    return {
      counts, byes: byeMap, round, pickNum, totalPicks, remaining,
      vorByPos, bestAvail,
      format: { rounds: f.rounds, slots: f.slots, isSuperflex: !!isSuperflex },
      flags: rosterFlags(counts, totalPicks, remaining, isSuperflex)
    };
  }

  function rosterFlags(counts, totalPicks, remaining, isSuperflex) {
    const flags = [];
    const sf = !!isSuperflex;
    if (totalPicks >= 6) {
      if ((counts.RB || 0) === 0) flags.push({ level: "warn", msg: "0 RBs through 6 rounds" });
      if ((counts.WR || 0) === 0) flags.push({ level: "warn", msg: "0 WRs through 6 rounds" });
    }
    if (totalPicks >= 10) {
      if ((counts.QB || 0) === 0) flags.push({ level: "warn", msg: "Still no QB by R10" });
      if ((counts.TE || 0) === 0) flags.push({ level: "warn", msg: "Still no TE by R10" });
    }
    if (totalPicks >= 14) {
      const qbTarget = sf ? 2 : 1;
      if ((counts.QB || 0) < qbTarget) flags.push({ level: "warn", msg: sf ? "Need a 2nd QB by R14" : "Still no QB late" });
      if ((counts.TE || 0) < 1) flags.push({ level: "warn", msg: "0 TE through R14" });
    }
    return flags;
  }

  // ============================================================
  // BBM (Best Ball Mania) historical advance-rate analysis
  // Computed from 2.5M Underdog BBM rosters (BBM II–VI, 2021–2025)
  // Powered by data/bbm_data.js → window.BBM_DATA
  // ============================================================

  // Hard caps based on actual BBM data analysis (advance rate by count):
  //   QB:  3 max (4 QBs = 0.91x baseline — never historically optimal)
  //   RB:  7 max (8+ RBs = 0.74x baseline — RB depth dies hard)
  //   WR: 10 max (11+ WRs = 0.64x baseline — too thin elsewhere)
  //   TE:  3 max (4+ TEs averaged 0.97x; 5+ = 0.72x; not worth the rare upside)
  const BBM_MAX_POS = { QB: 3, RB: 7, WR: 10, TE: 3 };
  // v0.9.94: practical minimums. Single-QB / single-TE builds appear in
  // the data but are bye-week / injury suicide in best ball — never
  // recommend them even if a tiny sample shows a fluky high advance rate.
  const BBM_MIN_POS = { QB: 2, RB: 3, WR: 4, TE: 2 };

  function _bbmReachableBuilds(currentCounts, picksMade, byBuild, minN) {
    minN = minN || 1000;
    const remaining = 18 - (picksMade || 0);
    const out = [];
    for (const build in byBuild) {
      const parts = build.split('/');
      if (parts.length !== 4) continue;
      const q = +parts[0], r = +parts[1], w = +parts[2], t = +parts[3];
      if (q + r + w + t !== 18) continue;
      const cQ = currentCounts.QB || 0, cR = currentCounts.RB || 0;
      const cW = currentCounts.WR || 0, cT = currentCounts.TE || 0;
      if (q < cQ || r < cR || w < cW || t < cT) continue;
      // v0.9.94: enforce min/max caps — never recommend < 2 QB or < 2 TE.
      if (q < BBM_MIN_POS.QB || r < BBM_MIN_POS.RB || w < BBM_MIN_POS.WR || t < BBM_MIN_POS.TE) continue;
      if (q > BBM_MAX_POS.QB || r > BBM_MAX_POS.RB || w > BBM_MAX_POS.WR || t > BBM_MAX_POS.TE) continue;
      const need = (q - cQ) + (r - cR) + (w - cW) + (t - cT);
      if (need !== remaining) continue;
      const stats = byBuild[build];
      if (stats.n < minN) continue;
      out.push({ build: build, q: q, r: r, w: w, t: t,
                 n: stats.n, q_rate: stats.q_rate,
                 s_rate: stats.s_rate, f_rate: stats.f_rate });
    }
    return out;
  }

  // Optimal final build given (currentCounts, slot, picksMade).
  // Returns {QB, RB, WR, TE, q_rate, n, build} or null.
  function bbmOptimalBuild(currentCounts, slot, picksMade, opts) {
    if (typeof window === 'undefined' || !window.BBM_DATA) return null;
    opts = opts || {};
    const data = window.BBM_DATA;
    // v0.9.93: level-aware. opts.level ∈ 'q' (top-2 / made_quarters), 's'
    // (made_semis), 'f' (made_finals). Default 'q' preserves prior behavior.
    const _lvl = (opts.level === 's' || opts.level === 'f') ? opts.level : 'q';
    const _F = _lvl + '_rate';      // unweighted field name e.g. 'q_rate'
    const _FW = _lvl + '_rate_w';   // recency-weighted field name
    const _LBASE = { q: 'made_quarters', s: 'made_semis', f: 'made_finals' }[_lvl];
    let byBuild = data.by_build;
    if (opts.year && data.by_build_year && data.by_build_year[opts.year]) {
      byBuild = data.by_build_year[opts.year];
    }
    // v0.10.0: sample-size floors scale with the rarity of the level.
    // Finals baseline is ~0.08% (200x rarer than QF's 16.7%), so n=1000
    // means only ~0.8 expected advancers — pure noise. We require enough
    // sample so the cohort has >=30 expected advancers in every level.
    //   QF baseline ~16.7% → 1000 teams ≈ 167 advancers ✓
    //   SF baseline ~1.32% → 5000 teams ≈ 66 advancers ✓
    //   Fin baseline ~0.08% → 30000 teams ≈ 25 advancers ✓
    // Without this fix, exotic small-sample builds (e.g. 3/3/9/3, n=2700)
    // win the Finals lottery on noise.
    const _LEVEL_MIN_N = { q: 1000, s: 5000, f: 30000 };
    const _LEVEL_FALLBACK_N = { q: 500, s: 2000, f: 10000 };
    const minN = _LEVEL_MIN_N[_lvl] || 1000;
    const fallbackN = _LEVEL_FALLBACK_N[_lvl] || 500;
    let reach = _bbmReachableBuilds(currentCounts, picksMade || 0, byBuild, minN);
    if (!reach.length) reach = _bbmReachableBuilds(currentCounts, picksMade || 0, byBuild, fallbackN);
    if (!reach.length) return null;

    // Pick the best build SHAPE using overall (slot-agnostic) advance rate.
    // Slot mostly affects which players you get, not which roster shape wins —
    // year-to-year top builds at any slot are very similar. Slot baseline rate
    // is exposed separately for the UI so users can see both signals.
    // PREFIX-CONDITIONAL: when caller passes opts.prefix (the position-letter
    // string of picks 1..K like "RRQ"), use the historical advance rate of
    // teams that had this exact pick prefix AND ended at each candidate
    // build. This is the order-aware signal — "RRQ" predicts a different
    // optimal completion than "WWQ" even when both are 1Q/2R/0W/0T.
    const prefix = (opts.prefix || '').toUpperCase().replace(/[^QRWT]/g, '').slice(0, 6);
    // Prefer recency-weighted prefix data (2024-2025 = 2-2.5x weight) when available
    const useWeighted = (opts.weighted !== false);
    const pDataW = (prefix && data.by_prefix_build_w) ? data.by_prefix_build_w[prefix] : null;
    const pData = (prefix && data.by_prefix_build) ? data.by_prefix_build[prefix] : null;
    const usePrefixW = useWeighted && !!(pDataW && Object.keys(pDataW).length >= 3);
    const usePrefix = !!(pData && Object.keys(pData).length >= 3);
    // Recency-weighted by_build (slot-agnostic) — fallback if prefix weighted unavailable
    const bbW = (useWeighted && data.by_build_w) ? data.by_build_w : null;

    // STATISTICAL SHRINKAGE: regularize rates toward baseline based on sample size.
    // adjusted = (n*observed + K*baseline) / (n + K). K=2000 means small-sample
    // builds (e.g. n=138) get pulled hard toward 16.7% baseline; high-n builds
    // (e.g. n=300k) barely move. Prevents recommending exotic 5-TE builds based
    // on noise from a tiny sample of weirdos.
    const baseline = (data.meta && data.meta.level_baselines && data.meta.level_baselines[_LBASE]) || ({q:0.1667, s:0.013, f:0.000809}[_lvl]);
    // v0.10.0: shrinkage K also scales with level rarity. At Finals stage,
    // single-cohort variance is huge — even n=10k builds can swing the
    // observed f_rate by 30%+. Stronger prior pulls these back to baseline
    // so the recommendation is structurally sound, not lottery-driven.
    const _LEVEL_SHRINK_PREFIX = { q: 5000, s: 15000, f: 50000 };
    const _LEVEL_SHRINK_GLOBAL = { q:  500, s:  3000, f: 15000 };
    const SHRINK_K_PREFIX = _LEVEL_SHRINK_PREFIX[_lvl] || 5000;
    const SHRINK_K_GLOBAL = _LEVEL_SHRINK_GLOBAL[_lvl] || 500;
    function shrink(observedRate, n, K) {
      if (n == null || !isFinite(n) || n <= 0) return baseline;
      return (n * observedRate + K * baseline) / (n + K);
    }
    // Hard minimum sample so we don't even consider absolute noise
    const MIN_PREFIX_N = 300;

    // Two-pass approach:
    //   PASS 1: find global-best reachable build (high-sample, proven)
    //   PASS 2: check if prefix-best has a meaningful edge over global-best
    //           (>= 1.5pp after shrinkage). If so, use it. Otherwise stick
    //           with global-best — avoids exotic small-sample builds winning
    //           on noisy prefix-conditional data.
    let globalBest = null;
    for (let i = 0; i < reach.length; i++) {
      const b = reach[i];
      const wRate = (bbW && bbW[b.build] && bbW[b.build][_FW] != null) ? bbW[b.build][_FW] : b[_F];
      const wN = (bbW && bbW[b.build]) ? bbW[b.build].n : b.n;
      const shrunk = shrink(wRate, wN, SHRINK_K_GLOBAL);
      if (!globalBest || shrunk > globalBest.rate) {
        globalBest = { rate: shrunk, n: wN, build: b.build, q: b.q, r: b.r, w: b.w, t: b.t, src: bbW && bbW[b.build] ? 'global-w' : 'global' };
      }
    }

    let prefixBest = null;
    if (usePrefixW || usePrefix) {
      for (let i = 0; i < reach.length; i++) {
        const b = reach[i];
        let pStat = null, isW = false;
        if (usePrefixW && pDataW[b.build]) { pStat = pDataW[b.build]; isW = true; }
        else if (usePrefix && pData[b.build]) { pStat = pData[b.build]; }
        if (!pStat || pStat.n < MIN_PREFIX_N) continue;
        const rawRate = isW ? pStat[_FW] : pStat[_F];
        if (rawRate == null) continue;
        const shrunk = shrink(rawRate, pStat.n, SHRINK_K_PREFIX);
        if (!prefixBest || shrunk > prefixBest.rate) {
          prefixBest = { rate: shrunk, n: pStat.n, build: b.build, q: b.q, r: b.r, w: b.w, t: b.t, src: (isW ? 'prefix-w:' : 'prefix:') + prefix };
        }
      }
    }

    // Use prefix recommendation only if it beats global by >= 1.5pp meaningful threshold.
    const PREFIX_EDGE_REQUIRED = 0.015;
    let bestRate, bestN, bestBuild, bestSrc, bestQ, bestR, bestW, bestT;
    if (prefixBest && globalBest && prefixBest.rate >= globalBest.rate + PREFIX_EDGE_REQUIRED) {
      bestRate = prefixBest.rate; bestN = prefixBest.n; bestBuild = prefixBest.build;
      bestSrc = prefixBest.src;
      bestQ = prefixBest.q; bestR = prefixBest.r; bestW = prefixBest.w; bestT = prefixBest.t;
    } else if (globalBest) {
      bestRate = globalBest.rate; bestN = globalBest.n; bestBuild = globalBest.build;
      bestSrc = globalBest.src;
      bestQ = globalBest.q; bestR = globalBest.r; bestW = globalBest.w; bestT = globalBest.t;
    } else {
      return null;
    }
    // Lookup slot-specific rate for THIS build (informational, not used for selection)
    let slotRate = null, slotN = null, slotBaseline = null;
    if (slot && data.by_construct_slot) {
      const sk = bestBuild + '@' + slot;
      const ss = data.by_construct_slot[sk];
      if (ss && ss.n >= 200 && ss[_F] != null) { slotRate = ss[_F]; slotN = ss.n; }
    }
    if (slot && data.by_slot && data.by_slot[String(slot)] && data.by_slot[String(slot)][_F] != null) {
      slotBaseline = data.by_slot[String(slot)][_F];
    }
    return { QB: bestQ, RB: bestR, WR: bestW, TE: bestT,
             q_rate: bestRate, rate: bestRate, level: _lvl,
             n: bestN, build: bestBuild,
             slot_rate: slotRate, slot_n: slotN, slot_baseline: slotBaseline,
             source: bestSrc, prefix: prefix || null };
  }

  // For the upcoming pick, compute expected advance rate IF you take each
  // position next. Uses the BEST achievable build from the new state
  // (assumes optimal subsequent play). For early picks (1-6), also factors
  // in position-timing data (when did first QB/TE come) for realism.
  // Returns {QB, RB, WR, TE, recommended} where each value is a probability
  // or null if that position isn't valid/sampled.
  function bbmNextPickRates(currentCounts, slot, picksMade, opts) {
    if (typeof window === 'undefined' || !window.BBM_DATA) return null;
    opts = opts || {};
    const data = window.BBM_DATA;
    // v0.9.93: level-aware. Same level handling as bbmOptimalBuild.
    const _lvl = (opts.level === 's' || opts.level === 'f') ? opts.level : 'q';
    const _F = _lvl + '_rate';
    const _FW = _lvl + '_rate_w';
    // v0.10.0: per-level minimum sample so rare-event levels (Finals 0.08%
    // baseline) don't accept noisy small-sample cohorts.
    const _NXT_MIN = { q: 1000, s: 5000, f: 30000 }[_lvl] || 1000;
    const _NXT_MIN_TP = { q: 500, s: 3000, f: 20000 }[_lvl] || 500;
    let byBuild = data.by_build;
    if (opts.year && data.by_build_year && data.by_build_year[opts.year]) {
      byBuild = data.by_build_year[opts.year];
    }
    const out = { QB: null, RB: null, WR: null, TE: null };
    const detail = {};
    const buildOut = {};  // best build per position choice
    const positions = ['QB','RB','WR','TE'];
    const nextTeamPick = (picksMade || 0) + 1;

    for (let pi = 0; pi < positions.length; pi++) {
      const pos = positions[pi];
      const newCounts = {
        QB: (currentCounts.QB||0) + (pos==='QB'?1:0),
        RB: (currentCounts.RB||0) + (pos==='RB'?1:0),
        WR: (currentCounts.WR||0) + (pos==='WR'?1:0),
        TE: (currentCounts.TE||0) + (pos==='TE'?1:0)
      };
      if (newCounts[pos] > BBM_MAX_POS[pos]) continue;
      // Best build achievable from new state, incl. the hypothetical pick.
      // Pass null slot but include prefix so order-conditional data wins.
      // BUGFIX v0.10.71: this appended the two-letter position NAME, so
      // prefix "R" + "WR" became "RWR" — a valid-but-wrong sequence
      // (RB-WR-RB) — and "R" + "QB" became "RQB", which matches no key at
      // all and silently fell through to the by-round fallback. Prefix keys
      // are single letters Q/R/W/T.
      const newPrefix = ((opts.prefix||'') + POS_LETTER[pos]).slice(0, 6);
      const best = bbmOptimalBuild(newCounts, null, nextTeamPick, Object.assign({}, opts, { prefix: newPrefix }));
      if (!best) continue;
      // v0.9.92: PRIMARY rate is now the actual historical advance rate of
      // teams that started with this exact position prefix (e.g. "RRRR"
      // after taking a 4th RB on top of an RRR start). Previously the
      // primary was best.q_rate — the rate IF you played optimally
      // afterward — which inflated bad early picks (QB R1 displayed at
      // ~11.7% when teams that took QB R1 historically advanced ~6%).
      // Now we use the prefix-conditional realRate that captures the
      // RRR→RB-vs-RRR→WR distinction the user actually cares about.
      // The optimal hypothetical rate is preserved as detail.optimalRate
      // for secondary display.
      const optimalRate = best.q_rate;
      const newPrefixForRate = ((opts.prefix || '') + POS_LETTER[pos]).slice(0, 6);
      let realRate = null, realN = null, realSrc = null;
      // 1) prefix-conditional aggregate across all final builds reachable
      //    from this prefix. Captures RRRR (4th RB) vs WWWR (1st RB) etc.
      const prefData = (data.by_prefix_build_w && data.by_prefix_build_w[newPrefixForRate]) ||
                       (data.by_prefix_build && data.by_prefix_build[newPrefixForRate]) || null;
      if (prefData) {
        let totN = 0, weighted = 0;
        for (const bk in prefData) {
          const ps = bk.split('/').map(Number);
          if (ps.length !== 4) continue;
          // Only count builds reachable from new counts (pos counts ≥ newCounts).
          if (ps[0] < newCounts.QB || ps[1] < newCounts.RB ||
              ps[2] < newCounts.WR || ps[3] < newCounts.TE) continue;
          // v0.9.94: enforce MIN_POS so bye-week-suicide single-QB / single-TE
          // builds never contribute to the recommended next-pick rate.
          if (ps[0] < BBM_MIN_POS.QB || ps[1] < BBM_MIN_POS.RB ||
              ps[2] < BBM_MIN_POS.WR || ps[3] < BBM_MIN_POS.TE) continue;
          if (ps[0] > BBM_MAX_POS.QB || ps[1] > BBM_MAX_POS.RB ||
              ps[2] > BBM_MAX_POS.WR || ps[3] > BBM_MAX_POS.TE) continue;
          const stat = prefData[bk];
          if (!stat || !stat.n) continue;
          const r = stat[_FW] != null ? stat[_FW] : stat[_F];
          if (r == null) continue;
          totN += stat.n;
          weighted += stat.n * r;
        }
        // v0.10.0: per-level minimum so rare-event levels filter out small samples
        if (totN >= _NXT_MIN) {
          realRate = weighted / totN;
          realN = totN;
          realSrc = 'prefix:' + newPrefixForRate;
        }
      }
      // 2) Fallback: by-team-pick (QB / TE only) or by-round (all positions).
      const willBeFirst = ((currentCounts[pos]||0) === 0);
      if (realRate == null && willBeFirst) {
        const tpKey = String(nextTeamPick);
        let tpData = null;
        if (pos === 'QB' && data.by_first_qb_tp) tpData = data.by_first_qb_tp[tpKey];
        else if (pos === 'TE' && data.by_first_te_tp) tpData = data.by_first_te_tp[tpKey];
        if (tpData && tpData.n >= _NXT_MIN_TP && tpData[_F] != null) {
          realRate = tpData[_F]; realN = tpData.n; realSrc = 'first_' + pos.toLowerCase() + '_tp';
        } else {
          const rdKey = String(Math.ceil(nextTeamPick / 12));
          const rdMap = data['by_first_' + pos.toLowerCase() + '_round'];
          if (rdMap && rdMap[rdKey] && rdMap[rdKey].n >= _NXT_MIN_TP && rdMap[rdKey][_F] != null) {
            realRate = rdMap[rdKey][_F]; realN = rdMap[rdKey].n; realSrc = 'first_' + pos.toLowerCase() + '_round';
          }
        }
      }
      // Display the historical reality if we have it; otherwise fall back
      // to the optimistic best-build rate so the cell isn't blank.
      out[pos] = realRate != null ? realRate : optimalRate;
      buildOut[pos] = best.QB + '/' + best.RB + '/' + best.WR + '/' + best.TE;
      detail[pos] = {
        n: best.n,
        build: buildOut[pos],
        optimalRate: optimalRate,
        realRate: realRate,
        realN: realN,
        realSrc: realSrc
      };
    }
    let rec = null, recRate = -1;
    for (let pi = 0; pi < positions.length; pi++) {
      const pos = positions[pi];
      if (out[pos] != null && out[pos] > recRate) { rec = pos; recRate = out[pos]; }
    }
    return { QB: out.QB, RB: out.RB, WR: out.WR, TE: out.TE,
             recommended: rec, detail: detail, builds: buildOut };
  }

  function bbmStartingBuild(slot, opts) {
    return bbmOptimalBuild({QB:0,RB:0,WR:0,TE:0}, slot, 0, opts);
  }

  // ============================================================
  // BBM positional value-cliff alerts
  // ============================================================
  // Cliffs computed from 2023+2024 BBM data (avg season fantasy points by
  // ADP round). Each cliff = "drafting in round X gets you Y more points
  // than waiting one more round". Big cliffs = scarcity windows.
  // ============================================================

  // BBM_MILESTONES — only TRUE cliffs (drop >= 45 pts in single-round transition).
  // Each entry: "by team pick `byPick`, you should have `min` of `pos`."
  // This is what the data actually supports — no speculation, no staircase noise.
  //
  // Methodology: combined 2023+2024 BBM season points by ADP round, only
  // single-round transitions with drop >= 45 pts qualify as cliffs.
  // Source: bbm_analysis/players/ extracts of Round 1 pick_points.
  const BBM_MILESTONES = [
    // WR — alpha receiver tier; biggest single-round cliff in fantasy (-67 pts)
    { pos: 'WR', min: 1, byPick: 2,  cliffDrop: 67,
      label: 'WR1 by pick 2',
      rationale: 'Alpha WR1 averages 165 pts; WR2 averages 97. Biggest pos cliff in the data.' },
    // QB — elite top-3 tier (-65 pts after R3)
    { pos: 'QB', min: 1, byPick: 3,  cliffDrop: 65,
      label: 'QB1 by pick 3 — OR plan to wait until pick 10',
      rationale: 'Top-3 QBs (Allen/Lamar/Mahomes) avg 233 pts; R4-R8 QBs avg 95-170 with high variance. Either pay up or punt.' },
    // RB — tier 2 collapse (-50 pts at R7-R8 zone)
    { pos: 'RB', min: 2, byPick: 7,  cliffDrop: 50,
      label: '2 RBs by pick 7',
      rationale: 'RB scoring drops from ~110 pts (R5-R7) to ~70 pts after R8. Get your starter pair before this transition.' },
    // QB — late-bloomer window (-67 pts after R10)
    { pos: 'QB', min: 1, byPick: 10, cliffDrop: 67,
      label: 'QB1 by pick 10 (if not from elite tier)',
      rationale: 'R9-R10 had the Lamar/Burrow late-bloomers (~160+ pts). After R10, QB output drops to 60-95 pt range.' },
    // WR — late depth cliff (-48 pts at R13)
    { pos: 'WR', min: 4, byPick: 12, cliffDrop: 48,
      label: '4 WRs by pick 12',
      rationale: 'WRs drafted in R13+ avg under 30 pts. Lock down your usable WR depth before R13.' },
  ];

  // Backward-compat: keep old structure but stripped to true cliffs only
  const BBM_CLIFFS = {
    QB: [
      { round: 4,  drop: 65, kind: 'cliff', label: 'Elite QB tier ends' },
      { round: 11, drop: 67, kind: 'cliff', label: 'Late QB window closing' },
    ],
    RB: [
      { round: 8,  drop: 50, kind: 'cliff', label: 'RB tier-2 cliff' },
    ],
    WR: [
      { round: 2,  drop: 67, kind: 'cliff', label: 'WR1 separation cliff' },
      { round: 13, drop: 48, kind: 'cliff', label: 'Late WR cliff' },
    ],
    TE: [],
  };

  // Hard floors — minimum count needed by end of draft.
  const BBM_FLOOR = { QB: 2, RB: 4, WR: 5, TE: 1 };

  // Compute milestone status for the user's current draft state.
  // Returns array of { pos, min, byPick, status, picksLeft, label, rationale }
  // where status is one of:
  //   'done'    — already have >= min at this position before deadline
  //   'on-track' — don't have it yet but still have picks left before deadline
  //   'at-risk' — next pick IS the deadline pick and we don't have it
  //   'missed'  — past the deadline and don't have it (cliff already happened)
  //   'pending' — deadline not reached yet, we already have min
  function bbmMilestones(currentCounts, picksMade) {
    const out = [];
    const nextPick = (picksMade || 0) + 1;
    for (let i = 0; i < BBM_MILESTONES.length; i++) {
      const m = BBM_MILESTONES[i];
      const have = currentCounts[m.pos] || 0;
      const picksLeft = m.byPick - nextPick + 1; // how many picks until and including byPick
      let status;
      if (have >= m.min) status = 'done';
      else if (picksLeft <= 0) status = 'missed';
      else if (picksLeft === 1) status = 'at-risk';
      else status = 'on-track';
      out.push({
        pos: m.pos, min: m.min, byPick: m.byPick, have: have, status: status,
        picksLeft: picksLeft, cliffDrop: m.cliffDrop,
        label: m.label, rationale: m.rationale
      });
    }
    return out;
  }

  // Legacy alert function for backward compatibility — not used by new UI
  function bbmValueAlerts(currentCounts, picksMade) {
    const alerts = [];
    const nextTeamPick = (picksMade || 0) + 1;
    const remaining = 18 - (picksMade || 0);
    if (nextTeamPick > 18) return alerts;

    for (const pos of ['QB','RB','WR','TE']) {
      const have = currentCounts[pos] || 0;
      const floor = BBM_FLOOR[pos];
      const need = Math.max(0, floor - have);
      const cliffs = BBM_CLIFFS[pos] || [];

      for (const cliff of cliffs) {
        // Cliff round = ROUND in which value drops (drafting in cliff.round-1 is +drop pts)
        // Active if: nextTeamPick is at or just before the cliff round AND we have unmet need
        const distance = cliff.round - nextTeamPick; // 0 = at cliff, 1 = next-pick-after = pre-cliff
        if (distance < 0) continue;       // already past
        if (distance > 2) continue;       // too far away

        // Skip if position is filled past its floor by a comfortable margin
        if (have >= floor + 1 && cliff.drop < 50) continue;
        // Hard skip if absolute max
        if ((pos === 'QB' && have >= 4) || (pos === 'TE' && have >= 4)) continue;

        const kind = cliff.kind || 'cliff';
        let level = 'info';
        // Only 'cliff' kind events generate urgent alerts; 'step' is info, 'soft' is soft
        if (kind === 'cliff') {
          if (distance === 0 && need > 0) level = 'urgent';
          else if (distance === 0) level = 'soft';
          else if (distance === 1 && need > 0) level = 'urgent';
          else if (distance === 1) level = 'soft';
          else level = 'info';
        } else if (kind === 'soft') {
          if (distance <= 1 && need > 0) level = 'soft';
          else level = 'info';
        } else { // 'step'
          if (distance === 0 && need > 0) level = 'soft';
          else level = 'info';
        }

        const cur = pos + ':' + have;
        const msg = '[' + pos + '] ' + cliff.label +
                    (distance === 0 ? ' (NOW — pick ' + nextTeamPick + ')'
                                    : ' (in ' + distance + ' pick' + (distance>1?'s':'') + ')') +
                    ' • ~' + cliff.drop + ' pts dropped if you wait';
        alerts.push({ level: level, position: pos, message: msg, drop: cliff.drop, distance: distance, have: have });
      }
    }
    // Sort by urgency, then by drop magnitude
    const order = { urgent: 0, soft: 1, info: 2 };
    alerts.sort(function(a,b) {
      if (order[a.level] !== order[b.level]) return order[a.level] - order[b.level];
      return b.drop - a.drop;
    });
    return alerts;
  }

  // ============================================================
  // BBM Stacking Analysis
  // ============================================================
  // Given a roster (array of player objects with .s position and .t NFL team),
  // computes stack category and historical advance rate from BBM 2024 data.
  // Stacking categories (per BBM_DATA.stacks):
  //   no_stack    — no QB has same-team WR/TE
  //   onesie      — 1 QB has +1 same-team pass catcher
  //   full2       — 1 QB has +2 same-team pass catchers
  //   full3plus   — 1 QB has +3 or more same-team pass catchers
  // Multi-QB stacking (n_stacked_qbs) is also tracked.
  // ============================================================
  function bbmStackStats(myRoster) {
    if (!myRoster || !myRoster.length) return null;
    if (typeof window === 'undefined' || !window.BBM_DATA || !window.BBM_DATA.stacks) return null;
    const data = window.BBM_DATA.stacks;

    // Identify QBs and their NFL teams; count same-team pass catchers
    const qbs = myRoster.filter(function(p) { return p && p.s === 'QB' && p.t; });
    const passCatchers = myRoster.filter(function(p) { return p && (p.s === 'WR' || p.s === 'TE') && p.t; });

    const stacks = qbs.map(function(qb) {
      const sameTeam = passCatchers.filter(function(pc) { return pc.t === qb.t; });
      return {
        qb: qb.n,
        team: qb.t,
        size: sameTeam.length,
        catchers: sameTeam.map(function(p) { return { n: p.n, s: p.s }; })
      };
    });

    let maxStack = 0;
    let nStackedQbs = 0;
    for (let i = 0; i < stacks.length; i++) {
      if (stacks[i].size > maxStack) maxStack = stacks[i].size;
      if (stacks[i].size >= 1) nStackedQbs += 1;
    }

    let category;
    if (qbs.length === 0) category = 'no_qb_yet';
    else if (maxStack === 0) category = 'no_stack';
    else if (maxStack === 1) category = 'onesie';
    else if (maxStack === 2) category = 'full2';
    else category = 'full3plus';

    const catData = data.by_category[category];
    const stackedData = data.by_n_stacked_qbs[String(nStackedQbs)];
    const baseline = data.baseline;

    return {
      category: category,
      max_stack: maxStack,
      n_stacked_qbs: nStackedQbs,
      qb_count: qbs.length,
      stacks: stacks,
      // Historical advance rate at this stack profile
      cat_rate: catData ? catData.q_rate : null,
      cat_n: catData ? catData.n : 0,
      cat_lift: catData && baseline ? catData.q_rate / baseline : null,
      stacked_rate: stackedData ? stackedData.q_rate : null,
      stacked_lift: stackedData && baseline ? stackedData.q_rate / baseline : null,
      baseline: baseline
    };
  }

  // Suggest the best stack opportunity from currently-available picks.
  // Given: my roster + best-available player list. Returns recommended pick to
  // build/extend a stack with the highest historical advance lift.
  function bbmStackOpportunities(myRoster, available) {
    if (!myRoster || !available) return null;
    return null;
  }
  global.MFFEngine = {
    FORMAT: FORMAT, FORMAT_SF: FORMAT_SF, fmt: fmt,
    recommend: recommend, rosterReport: rosterReport, rosterCounts: rosterCounts, byeBreakdown: byeBreakdown,
    pickToRound: pickToRound, picksUntilNext: picksUntilNext, scorePlayer: scorePlayer,
    playerVor: playerVor, playerUp: playerUp, detectVorTier: detectVorTier,
    rosterVorByPos: rosterVorByPos, bestVorAvailable: bestVorAvailable,
    analyzePositions: analyzePositions, suggestPosition: suggestPosition,
    recPositionMults: recPositionMults, recStackMult: recStackMult,
    recWaitMult: recWaitMult, userPickAtOrAfter: userPickAtOrAfter,
    recValueMults: recValueMults, FORMAT_RD: FORMAT_RD, fmtMode: fmtMode,
    recPrefixBuildMults: recPrefixBuildMults,
    bbmTimingMults: bbmTimingMults,
    recDeferralMults: recDeferralMults,
    bbmBringbackMultFor: bbmBringbackMultFor,
    bbmStackMultFor: bbmStackMultFor,
    bbmStructMultFor: bbmStructMultFor,
    bbmBuildConditionalRates: bbmBuildConditionalRates,
    recBbmValueMults: recBbmValueMults, recValueChartData: recValueChartData,
    analyzeRosterVolatility: analyzeRosterVolatility,
    bbmOptimalBuild: bbmOptimalBuild,
    bbmNextPickRates: bbmNextPickRates,
    bbmStartingBuild: bbmStartingBuild,
    bbmMilestones: bbmMilestones,
    bbmValueAlerts: bbmValueAlerts,
    bbmStackStats: bbmStackStats,
    bbmStackOpportunities: bbmStackOpportunities
  };
})(typeof window !== "undefined" ? window : globalThis);
