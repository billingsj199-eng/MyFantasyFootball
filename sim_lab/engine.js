// ============================================================================
// SIM LAB ENGINE — projections + Monte Carlo simulation core.
// Private research tool. Not part of the deployed MFF site.
//
// Projection model (per player per week):
//   mean  = (Clay season PPR pts, rescored to league settings) / 17
//           x Vegas game-environment multiplier (team implied total vs league avg)
//   sigma = player-specific sigma_pct from PLAYER_WEEKLY_SIGMA (3yr weighted,
//           trend-corrected), fallback to position defaults for rookies
//   dist  = gamma (non-negative, right-skewed) around the env-shifted mean
//
// Correlation structure (per sim, per NFL game) — QB-hub model, backtested
// vs 2019-25 actual weekly correlations (see CORR block + backtest_correlations.py):
//   V team passing environment (game-correlated), per-receiver draws that
//   flow into the QB via receiving-share weights, an antisymmetric
//   rush-script factor for RBs, DST inverse on the opponent's V.
// ============================================================================
(function () {
  'use strict';

  var SEASON = 2026;
  var WEEKS = 18;
  var VEGAS_ELASTICITY = 0.5; // weekly mean elasticity vs implied-total delta
  var RESID_SHRINK = 0.9;   // common factors absorb ~10% of player sigma

  // ---------- correlation structure (QB-hub) ----------
  // BACKTESTED 2019-25 (backtest_correlations.py, ~19k player-week pairs):
  // the old uniform team-environment model was wrong in shape — QB<->his
  // receivers boom together at r ~.27-.35 (we said .15), while non-QB
  // teammate pairs are ~0 or negative (target/carry competition cancels the
  // shared environment; we said +.10-.18), QB-vs-opposing-QB is +.20 (we
  // said .08) and RB-vs-opposing-RB is NEGATIVE -.08 (we said +.05).
  // New structure (loadings are FRACTIONS of each player's total weekly sd,
  // so marginals are preserved exactly):
  //   V   passing environment per team, correlated across a game (gV=.50)
  //   G_r per-receiver draw that also flows into the QB via receiving-share
  //       weights (QB points ARE receiver points -> links QB to each
  //       receiver WITHOUT linking the receivers to each other)
  //   R   antisymmetric rush-script game factor (one team controls clock)
  //   DST loads negatively on the OPPONENT's passing environment.
  // Fit: mean |corr error| same-team .128 -> .042, opponent .042 -> .020.
  var CORR = {
    gV: 0.50,
    fV: { QB: 0.63, WR: 0.24, TE: 0.22, RB: 0.06, K: 0.10 },
    fH_QB: 0.65,
    fG: { WR: 0.58, TE: 0.60, RB: 0.30 },
    fR_RB: 0.25,
    fDST_oppV: -0.25
  };

  var POS_SIGMA = { QB: 0.42, RB: 0.52, WR: 0.62, TE: 0.70, K: 0.45, DST: 0.75 };
  // Weekly-width calibration (backtest_weekly_sigma.py, 2019-25, realized-mean
  // basis so mean-drift doesn't contaminate): per-position scale on sigmaPct
  // that puts p10-p90 coverage on the 80% target — QB was already right
  // (engine ran ~10% wide there), RB/WR ~5% narrow + the gamma family is
  // mildly thin-tailed both sides, so they need +15%; TE +10%. The 3-yr
  // player-specific sigma itself VALIDATED: corr +.52 with realized CV vs
  // +.41 for position defaults.
  // K/DST calibrated separately from pbp-reconstructed weekly scores
  // (backtest_k_dst_sigma.py): realized K CV .572 vs engine .417 -> K 1.28
  // (on top of the 1.10 no-history mult every kicker gets); realized DST CV
  // .93 vs .72 -> DST 1.34 (applied at DST creation; DST also samples from
  // a SHIFTED gamma, see samplePlayerScore — 8.3% of real DST weeks are
  // NEGATIVE, which a floor-at-zero gamma cannot produce).
  var SIGMA_CAL = { QB: 1.0, RB: 1.15, WR: 1.15, TE: 1.10, K: 1.28 };
  var DST_SIGMA_CAL = 1.34;
  var DST_SHIFT = 4; // shifted-gamma offset for DST sampling

  // Position-specific boom/bust thresholds (half-PPR frame): a 4-pt QB week
  // basically never happens, while 15 is already a boom for a TE.
  var BOOM_BUST = {
    QB: { boom: 25, bust: 10 }, RB: { boom: 20, bust: 6 }, WR: { boom: 20, bust: 5 },
    TE: { boom: 15, bust: 4 }, K: { boom: 12, bust: 4 }, DST: { boom: 12, bust: 2 }
  };

  var TEAM_ALIAS = { ARZ: 'ARI', WSH: 'WAS', JAC: 'JAX', LA: 'LAR', HST: 'HOU', BLT: 'BAL', CLV: 'CLE', SD: 'LAC', OAK: 'LV', STL: 'LAR' };
  function normTeam(t) { return TEAM_ALIAS[t] || t; }

  var DST_NAMES = { ARI:'Cardinals', ATL:'Falcons', BAL:'Ravens', BUF:'Bills', CAR:'Panthers', CHI:'Bears', CIN:'Bengals', CLE:'Browns', DAL:'Cowboys', DEN:'Broncos', DET:'Lions', GB:'Packers', HOU:'Texans', IND:'Colts', JAX:'Jaguars', KC:'Chiefs', LAC:'Chargers', LAR:'Rams', LV:'Raiders', MIA:'Dolphins', MIN:'Vikings', NE:'Patriots', NO:'Saints', NYG:'Giants', NYJ:'Jets', PHI:'Eagles', PIT:'Steelers', SEA:'Seahawks', SF:'49ers', TB:'Buccaneers', TEN:'Titans', WAS:'Commanders' };

  // ---------- name normalization (mirrors sleeper-extension norm) ----------
  function norm(n) {
    return String(n || '').toLowerCase()
      .replace(/\./g, '').replace(/'/g, '').replace(/-/g, ' ')
      .replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '')
      .replace(/\s+/g, ' ').trim();
  }

  // ---------- RNG (seedable) ----------
  function mulberry32(seed) {
    var a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function makeRng(seed) {
    var rand = seed != null ? mulberry32(seed) : Math.random;
    var spare = null;
    function normal() {
      if (spare != null) { var s = spare; spare = null; return s; }
      var u = 0, v = 0;
      do { u = rand(); } while (u <= 1e-12);
      v = rand();
      var r = Math.sqrt(-2 * Math.log(u));
      spare = r * Math.sin(2 * Math.PI * v);
      return r * Math.cos(2 * Math.PI * v);
    }
    // Marsaglia-Tsang gamma(shape k, scale th)
    function gamma(k, th) {
      if (k < 1) {
        var u1; do { u1 = rand(); } while (u1 <= 1e-12);
        return gamma(1 + k, th) * Math.pow(u1, 1 / k);
      }
      var d = k - 1 / 3, c = 1 / Math.sqrt(9 * d);
      for (;;) {
        var x, v2;
        do { x = normal(); v2 = 1 + c * x; } while (v2 <= 0);
        v2 = v2 * v2 * v2;
        var u = rand();
        if (u < 1 - 0.0331 * x * x * x * x) return d * v2 * th;
        if (Math.log(u) < 0.5 * x * x + d * (1 - v2 + Math.log(v2))) return d * v2 * th;
      }
    }
    return { rand: rand, normal: normal, gamma: gamma };
  }

  // ---------- schedule from Vegas game totals ----------
  // sched[team][week] = { opp, home, total, spread, implied, oppImplied, gameKey }
  function buildSchedule() {
    var gt = (window.BETTING_2026 && window.BETTING_2026.gameTotals) || {};
    var sched = {}, games = {}; // games[week] = [{away,home,total,spread,key}]
    Object.keys(gt).forEach(function (key) {
      var m = key.match(/^W(\d+)_([A-Z]+)_([A-Z]+)$/);
      if (!m) return;
      var wk = +m[1], away = normTeam(m[2]), home = normTeam(m[3]);
      var rec = gt[key];
      if (!rec || typeof rec.total !== 'number') return;
      var total = rec.total, spread = typeof rec.spread === 'number' ? rec.spread : 0;
      var homeImp = (total - spread) / 2, awayImp = (total + spread) / 2;
      (games[wk] = games[wk] || []).push({ away: away, home: home, total: total, spread: spread, key: key });
      sched[home] = sched[home] || {}; sched[away] = sched[away] || {};
      sched[home][wk] = { opp: away, home: true, total: total, spread: spread, implied: homeImp, oppImplied: awayImp, gameKey: key };
      sched[away][wk] = { opp: home, home: false, total: total, spread: spread, implied: awayImp, oppImplied: homeImp, gameKey: key };
    });
    // league-average implied total (for the Vegas multiplier)
    var sum = 0, n = 0, gameWeeks = {};
    Object.keys(sched).forEach(function (tm) {
      Object.keys(sched[tm]).forEach(function (wk) { sum += sched[tm][wk].implied; n++; });
      gameWeeks[tm] = Object.keys(sched[tm]).map(Number).sort(function (a, b) { return a - b; });
    });
    return { byTeam: sched, byWeek: games, avgImplied: n ? sum / n : 22.5, gameWeeks: gameWeeks };
  }

  // ---------- player table ----------
  // Merge Clay components + sigma table + sleeper ids/ADP + DST synthetics.
  function buildPlayers(schedule) {
    var players = [], byNorm = {}, bySid = {};
    var sigma = (typeof PLAYER_WEEKLY_SIGMA !== 'undefined') ? PLAYER_WEEKLY_SIGMA : {};
    var sigByNorm = {};
    Object.keys(sigma).forEach(function (nm) { sigByNorm[norm(nm)] = sigma[nm]; });

    var sleeper = (window.SIM_SLEEPER && window.SIM_SLEEPER.players) || [];
    var slByNorm = {};
    sleeper.forEach(function (p) {
      var k = norm(p.n);
      if (!slByNorm[k]) slByNorm[k] = p;
    });

    var clay = (typeof MIKE_CLAY_PROJ !== 'undefined') ? MIKE_CLAY_PROJ : {};
    Object.keys(clay).forEach(function (name) {
      var c = clay[name];
      var pos = c.pos === 'PK' ? 'K' : c.pos;
      if (!POS_SIGMA[pos]) return;
      var nk = norm(name);
      var sl = slByNorm[nk];
      var sg = sigByNorm[nk];
      var age = sl && typeof sl.age === 'number' ? sl.age : null;
      // TRUE rookie = years_exp 0 from Sleeper metadata (a 2nd-year player
      // with a tiny sample — Jeanty types — is NOT a rookie). Fallback when
      // metadata is missing: no NFL history + age <= 23.
      var mt = (typeof window !== 'undefined' && window.SIM_SLEEPER_META && sl && sl.sid)
        ? window.SIM_SLEEPER_META[String(sl.sid)] : null;
      var exp = mt && typeof mt.exp === 'number' ? mt.exp : null;
      var isRookie = exp != null ? exp === 0 : (!sg && age != null && age <= 23);
      // Volatility: past tendencies where we have them, widened for youth /
      // thin samples. Gamma sampling is floored at 0, so extra sigma mostly
      // fattens the BOOM tail — which is exactly the breakout case.
      var sigmaPct, sigmaSrc;
      var histPpg = null, histGames = 0;
      if (sg && sg.sigma_pct) {
        // low-sample widening: <30 games of history -> up to +25% sigma
        var games = sg.games || 30;
        sigmaPct = sg.sigma_pct * (1 + 0.25 * (1 - Math.min(1, games / 30)));
        sigmaSrc = 'history';
        histPpg = sg.mean_ppg || null; // 3yr weighted half-PPR PPG — the JS Weekly prior
        histGames = games;
      } else if (isRookie) {
        sigmaPct = POS_SIGMA[pos] * 1.20; // true rookie: breakout-wide
        sigmaSrc = 'rookie-wide';
      } else {
        sigmaPct = POS_SIGMA[pos] * 1.10; // vet with no usable sample
        sigmaSrc = 'no-history';
      }
      if (age != null && age <= 23) sigmaPct *= 1.10;
      else if (age === 24) sigmaPct *= 1.05;
      sigmaPct *= SIGMA_CAL[pos] || 1;
      // slow weekly tuner: band-coverage multiplier per position (data/sim_tuning.js)
      if (typeof window !== 'undefined' && window.SIM_TUNING && window.SIM_TUNING.sigmaMult
          && typeof window.SIM_TUNING.sigmaMult[pos] === 'number') sigmaPct *= window.SIM_TUNING.sigmaMult[pos];
      sigmaPct = Math.min(1.35, Math.max(0.28, sigmaPct));
      var p = {
        name: name, norm: nk, pos: pos, tm: normTeam(c.tm),
        comps: { py: c.py || 0, ptd: c.ptd || 0, ry: c.ry || 0, rtd: c.rtd || 0, rec: c.rec || 0, rcy: c.rcy || 0, rctd: c.rctd || 0, fgm: c.fgm || 0, xpm: c.xpm || 0 },
        ptsPPR: c.pts || 0, clayGames: c.gm || 17,
        sigmaPct: sigmaPct, sigmaSrc: sigmaSrc,
        sid: sl && sl.sid ? String(sl.sid) : null,
        adp: sl && typeof sl.a === 'number' ? sl.a : null,
        age: age, exp: exp, isRookie: isRookie,
        injFlag: mt ? (mt.inj || '') + '|' + (mt.st || '') : '',
        histPpg: histPpg, histGames: histGames,
        ktc1qb: sl && typeof sl.ktc1qb === 'number' ? sl.ktc1qb : null,
        ktcSf: sl && typeof sl.ktcSf === 'number' ? sl.ktcSf : null
      };
      // slow weekly tuner (data/sim_tuning.js, tune_weekly.py): per-position
      // TD-rate multipliers and a kicker level multiplier, applied to the Clay
      // PRIOR's components with season points kept consistent (Clay PPR basis:
      // pass TD 4, rush/rec TD 6; K pts = 3*FGM + XPM). jsBasePg blends this
      // calibrated prior with the player's ACTUAL per-game mix, so realized
      // rates still dominate as the sample grows. Jack 2026-09-14.
      var TU = (typeof window !== 'undefined' && window.SIM_TUNING) || null;
      if (TU && TU.tdMult && TU.tdMult[pos]) {
        var tdm = TU.tdMult[pos];
        [['ptd', 4], ['rtd', 6], ['rctd', 6]].forEach(function (kv) {
          var m = tdm[kv[0]];
          if (typeof m === 'number' && m > 0 && p.comps[kv[0]]) {
            p.ptsPPR += p.comps[kv[0]] * (m - 1) * kv[1];
            p.comps[kv[0]] = +(p.comps[kv[0]] * m).toFixed(2);
          }
        });
      }
      if (TU && pos === 'K' && typeof TU.kLevel === 'number' && TU.kLevel > 0) {
        p.ptsPPR *= TU.kLevel;
        p.comps.fgm = +(p.comps.fgm * TU.kLevel).toFixed(2);
        p.comps.xpm = +(p.comps.xpm * TU.kLevel).toFixed(2);
      }
      players.push(p);
      if (!byNorm[nk]) byNorm[nk] = p;
      if (p.sid) bySid[p.sid] = p;
    });

    // DST synthetics — mean derived weekly from opponent implied total.
    Object.keys(DST_NAMES).forEach(function (tm) {
      var p = {
        name: DST_NAMES[tm] + ' D/ST', norm: norm(DST_NAMES[tm] + ' D/ST'), pos: 'DST', tm: tm,
        comps: {}, ptsPPR: 0, clayGames: 17,
        sigmaPct: POS_SIGMA.DST * DST_SIGMA_CAL
          * ((typeof window !== 'undefined' && window.SIM_TUNING && window.SIM_TUNING.sigmaMult
              && typeof window.SIM_TUNING.sigmaMult.DST === 'number') ? window.SIM_TUNING.sigmaMult.DST : 1), // weekly tuner
        sigmaSrc: 'pos-default',
        sid: tm, adp: null, isDST: true
      };
      players.push(p);
      byNorm[p.norm] = p;
      bySid[tm] = p; // Sleeper DEF player_id IS the team abbr
    });

    // Norm-name aliases so leagues imported by NAME (ESPN) can address players
    // with no Sleeper id through the same bySid map. Lowercase norm keys can't
    // collide with numeric Sleeper ids or uppercase DST team abbrs.
    players.forEach(function (p) { if (!bySid[p.norm]) bySid[p.norm] = p; });

    applyQbWindows(players, byNorm);
    applyInjuryWindows(players);
    applyRookieRamps(players);

    // receiving-share weights per team for the QB-hub correlation: w_r =
    // sqrt(share of team PPR receiving points), so sum(w^2) = 1 and the
    // hub factor (sum w_r * g_r) has unit variance.
    var recByTeam = {};
    players.forEach(function (p) {
      if (p.isDST || (p.pos !== 'WR' && p.pos !== 'TE' && p.pos !== 'RB')) return;
      var rp = (p.comps.rec || 0) + 0.1 * (p.comps.rcy || 0) + 6 * (p.comps.rctd || 0);
      if (rp <= 0) return;
      (recByTeam[p.tm] = recByTeam[p.tm] || []).push({ key: p.sid || p.norm, rp: rp });
    });
    Object.keys(recByTeam).forEach(function (tm2) {
      var tot = recByTeam[tm2].reduce(function (s, r) { return s + r.rp; }, 0);
      recByTeam[tm2].forEach(function (r) { r.w = Math.sqrt(r.rp / tot); delete r.rp; });
    });
    _roster = players; _rosterByTm = null; _tmQb1 = null; // rate-track teammate guard
    return { list: players, byNorm: byNorm, bySid: bySid, recByTeam: recByTeam, schedule: schedule,
             _ix: buildIndex(players, recByTeam, schedule) };
  }

  // ---------- Monte-Carlo fast-path index ----------
  // The sampler used to key each sim's environment off strings — env.v['KC'],
  // env.g[sleeperId] — which meant ~2M dictionary inserts and lookups per
  // season sim. Profiling put that layout at ~55% of the runtime against ~17%
  // for the actual random draws. Everything the inner loop touches is resolved
  // to an integer slot ONCE here so the hot path reads Float64Arrays by index.
  // Draw order, draw count and every resulting number are unchanged — this is
  // purely a memory-layout change.
  function buildIndex(list, recByTeam, schedule) {
    var teams = [], tIdx = Object.create(null);
    function teamSlot(tm) {
      if (tm == null) return -1;
      var i = tIdx[tm];
      if (i === undefined) { i = teams.length; teams.push(tm); tIdx[tm] = i; }
      return i;
    }
    // every team that plays a game gets a slot first, so drawWeekEnv can never
    // meet an abbreviation it has no column for
    var bw = (schedule && schedule.byWeek) || {};
    Object.keys(bw).forEach(function (wk) {
      bw[wk].forEach(function (g0) { teamSlot(g0.away); teamSlot(g0.home); });
    });
    // receiver hub slots, grouped by team index
    var recByTi = [], nRec = 0, keySlot = Object.create(null);
    Object.keys(recByTeam).forEach(function (tm) {
      var ti = teamSlot(tm), arr = recByTeam[tm];
      arr.forEach(function (r) { r.i = nRec++; keySlot[r.key] = r.i; });
      recByTi[ti] = arr;
    });
    for (var t = 0; t < teams.length; t++) if (!recByTi[t]) recByTi[t] = null;
    list.forEach(function (p) {
      p._ti = teamSlot(p.tm);
      var gi = keySlot[p.sid || p.norm];
      p._gi = gi === undefined ? -1 : gi;
      p._fv = CORR.fV[p.pos] || 0;
      p._fg = CORR.fG[p.pos] || 0;
      // relative width is a pure function of the player; samplePlayerScore
      // used to recompute this pow+sqrt on every one of millions of draws
      p._relW = Math.sqrt(Math.pow(RESID_SHRINK * p.sigmaPct, 2) + 0.04);
    });
    return { teams: teams, tIdx: tIdx, recByTi: recByTi, nRec: nRec };
  }
  function ensureIndex(players) {
    return players._ix ||
      (players._ix = buildIndex(players.list || [], players.recByTeam || {}, players.schedule));
  }

  // ---------- injury start-of-season windows ----------
  // A player carrying ANY current injury/suspension designation whom Clay
  // ALSO projects for <17 games (Charbonnet PUP + gm 11, Kittle PUP + gm 15,
  // Nabers Questionable + gm 15) is missing games at the START of the season
  // — window = the LAST gm games, at his true per-game rate. Camp PUP with
  // gm 17 (Kraft, Pierce types) = Clay expects a full season, so no window.
  // Both signals must agree — a healthy gm<17 hedge (backup QB mop-up) stays
  // spread across the season, and a flag alone with gm 17 does nothing.
  // Override per news in overrides.js: INJURY_WINDOW_OVERRIDES['Name'] =
  // games missed at the start (0 = force full season).
  function applyInjuryWindows(players) {
    var ov = (typeof window !== 'undefined' && window.INJURY_WINDOW_OVERRIDES) || {};
    players.forEach(function (p) {
      if (p.qbWindow || p.isDST) return;
      var o = ov[p.name];
      if (o != null) {
        if (o > 0) p.qbWindow = { s: o + 1, e: 17, games: 17 - o, src: 'override' };
        return; // 0 = confirmed healthy, full season
      }
      if (!/PUP|IR|NFI|Injured Reserve|Non Football|Out|Doubtful|Questionable|Sus/i.test(p.injFlag)) return;
      var gm = p.clayGames;
      if (!(gm >= 2 && gm <= 16)) return;
      p.qbWindow = { s: 17 - gm + 1, e: 17, games: gm, src: 'injury-start' };
    });
  }

  // ---------- QB starter windows ----------
  // Clay's gm is 17 for nearly every QB — his STARTER SPLIT lives in the point
  // totals (real committee rooms have two QBs >=40 pts; pure backups sit at
  // ~7-11). For those rooms we estimate each QB's starts from the point split
  // and sequence them: the VETERAN opens the season (Cousins before Mendoza,
  // Tua before Penix), the other takes over when the vet's games run out.
  // During his window a QB projects at his true per-start rate, not season/17.
  // Manual override (as camp news breaks): window.QB_ROOM_OVERRIDES in
  // overrides.js — { LV: [['Kirk Cousins', 4], ['Fernando Mendoza', 13]] }.
  var QB_SPLIT_MIN_PTS = 40;      // both QBs need this many season pts
  var QB_BACKUP_RATE = 0.85;      // 2nd QB's per-start rate vs the leader's
  function applyQbWindows(players, byNorm) {
    var rooms = {};
    players.forEach(function (p) {
      if (p.pos === 'QB' && p.ptsPPR >= QB_SPLIT_MIN_PTS) (rooms[p.tm] = rooms[p.tm] || []).push(p);
    });
    var overrides = (typeof window !== 'undefined' && window.QB_ROOM_OVERRIDES) || {};
    Object.keys(rooms).forEach(function (tm) {
      if (overrides[tm]) {
        var g0 = 0;
        overrides[tm].forEach(function (entry) {
          var p = byNorm[norm(entry[0])];
          var g = entry[1];
          if (!p || !g) return;
          p.qbWindow = { s: g0 + 1, e: g0 + g, games: g, src: 'override' };
          g0 += g;
        });
        return;
      }
      var room = rooms[tm].sort(function (a, b) { return b.ptsPPR - a.ptsPPR; });
      if (room.length < 2) return;
      var lead = room[0], other = room[1];
      // closed-form split: pts_L = r*g_L, pts_B = 0.85r*g_B, g_L + g_B = 17
      var adjB = other.ptsPPR / QB_BACKUP_RATE;
      var gB = Math.min(12, Math.max(2, Math.round(17 * adjB / (lead.ptsPPR + adjB))));
      var gL = 17 - gB;
      // Week-1 starter: the veteran; if both are vets (or both rookies), the older one
      var otherFirst;
      if (lead.isRookie && !other.isRookie) otherFirst = true;
      else if (other.isRookie && !lead.isRookie) otherFirst = false;
      else otherFirst = (other.age || 0) > (lead.age || 0);
      var first = otherFirst ? other : lead, gFirst = otherFirst ? gB : gL;
      var second = otherFirst ? lead : other, gSecond = otherFirst ? gL : gB;
      first.qbWindow = { s: 1, e: gFirst, games: gFirst, src: 'clay-split' };
      second.qbWindow = { s: gFirst + 1, e: gFirst + gSecond, games: gSecond, src: 'clay-split' };
    });
  }

  // ---------- rookie ramps ----------
  // Young players with no NFL sample start slow and ramp up — harder if
  // they're buried on the depth chart (<60% of the team's position leader).
  // Head factors by GAME NUMBER; tail is renormalized so season totals are
  // preserved exactly (only the weekly shape changes).
  // Only rookies BURIED on the depth chart ramp — a projected lead rookie
  // (Love, Jeanty types) is full-go from Week 1.
  var RAMP = {
    buried: { head: [0.55, 0.70, 0.85, 0.95], tail: (17 - 3.05) / 13 }
  };
  function applyRookieRamps(players) {
    var lead = {};
    players.forEach(function (p) {
      if (p.isDST) return;
      var k = p.tm + '|' + p.pos;
      lead[k] = Math.max(lead[k] || 0, p.ptsPPR);
    });
    players.forEach(function (p) {
      if (!p.isRookie) return; // years_exp 0 only — 2nd-year players are NOT rookies
      if (p.pos !== 'RB' && p.pos !== 'WR' && p.pos !== 'TE') return; // QBs use windows
      if (p.ptsPPR < 0.6 * (lead[p.tm + '|' + p.pos] || 0)) p.ramp = 'buried';
    });
  }

  // ---------- scoring ----------
  // Clay pts baseline = ESPN full PPR (rec 1, pass TD 4, 0.04/py, 0.1/ry+rcy, 6/td).
  // Rescore by adjusting deltas off that baseline using the stat components.
  var PRESETS = {
    ppr:  { rec: 1,   pass_td: 4, pass_yd: 0.04, rush_yd: 0.1, rec_yd: 0.1, rush_td: 6, rec_td: 6, bonus_rec_te: 0 },
    half: { rec: 0.5, pass_td: 4, pass_yd: 0.04, rush_yd: 0.1, rec_yd: 0.1, rush_td: 6, rec_td: 6, bonus_rec_te: 0 },
    std:  { rec: 0,   pass_td: 4, pass_yd: 0.04, rush_yd: 0.1, rec_yd: 0.1, rush_td: 6, rec_td: 6, bonus_rec_te: 0 }
  };
  function scoringFromLeague(ls) {
    ls = ls || {};
    return {
      rec: num(ls.rec, 0), pass_td: num(ls.pass_td, 4), pass_yd: num(ls.pass_yd, 0.04),
      rush_yd: num(ls.rush_yd, 0.1), rec_yd: num(ls.rec_yd, 0.1),
      rush_td: num(ls.rush_td, 6), rec_td: num(ls.rec_td, 6),
      bonus_rec_te: num(ls.bonus_rec_te, 0)
    };
  }
  function num(v, d) { return typeof v === 'number' ? v : d; }

  function seasonPoints(p, sc) {
    if (p.isDST) return 0; // handled weekly
    var c = p.comps, pts = p.ptsPPR;
    pts += (sc.rec - 1) * c.rec;
    pts += (sc.pass_td - 4) * c.ptd;
    pts += (sc.pass_yd - 0.04) * c.py;
    pts += (sc.rush_yd - 0.1) * c.ry;
    pts += (sc.rec_yd - 0.1) * c.rcy;
    pts += (sc.rush_td - 6) * c.rtd;
    pts += (sc.rec_td - 6) * c.rctd;
    if (p.pos === 'TE' && sc.bonus_rec_te) pts += sc.bonus_rec_te * c.rec;
    return Math.max(0, pts);
  }

  // ---------- opponent defense adjustment (Clay unit grades) ----------
  // CLAY_TEAM_GRADES_2026: 1-10 grades per defensive unit (di/ed/lb/cb/s).
  // Each position keys off the units that actually defend it. Kept SMALL
  // (±2%/grade pt, capped ±8%) — Vegas lines already price most of the
  // defense; this is the position-specific residual.
  var _defAdj = null;
  function defenseAdj() {
    if (_defAdj) return _defAdj;
    var g = (typeof window !== 'undefined' && window.CLAY_TEAM_GRADES_2026) || {};
    var blends = {}, sums = { QB: 0, RB: 0, WR: 0, TE: 0 }, n = 0;
    Object.keys(g).forEach(function (tm) {
      var t = g[tm];
      if (t.cb == null) return;
      var b = {
        QB: t.cb * 0.45 + t.s * 0.25 + t.ed * 0.30,   // coverage + pass rush
        WR: t.cb * 0.50 + t.s * 0.30 + t.ed * 0.20,
        RB: t.di * 0.40 + t.lb * 0.35 + t.ed * 0.25,  // run front
        TE: t.s * 0.40 + t.lb * 0.35 + t.cb * 0.25    // seam coverage
      };
      blends[normTeam(tm)] = b;
      sums.QB += b.QB; sums.RB += b.RB; sums.WR += b.WR; sums.TE += b.TE; n++;
    });
    _defAdj = {};
    Object.keys(blends).forEach(function (tm) {
      _defAdj[tm] = {};
      ['QB', 'RB', 'WR', 'TE'].forEach(function (pos) {
        // HALVED to 1%/grade-pt cap +-4% (was 2%/+-8%): the testable analog
        // of preseason defense identity — prior-season positional FPA —
        // showed NO predictive signal (backtest_snap_defense.py, e=0 best,
        // 17.6k player-weeks). Clay's personnel grades are plausibly better
        // than that proxy but untestable historically, so the layer stays
        // at half size rather than zero.
        var m = 1 - 0.01 * (blends[tm][pos] - sums[pos] / n);
        _defAdj[tm][pos] = Math.min(1.04, Math.max(0.96, m));
      });
    });
    return _defAdj;
  }

  // ---------- elite shadow-corner dock ----------
  // backtest_cb_shadow.py (2019-25, 45 elite-CB defense-seasons, weekly
  // on/off from DEFENSIVE snap counts): opposing WRs hit 0.954 of
  // expectation with an elite CB on the field vs 1.049 when the SAME
  // defense played without him (~6% paired within defense-season), and the
  // in-season FPA layer at e=.25 is too small/slow to catch it. The raw
  // MSE-optimal dock was x0.94, but that base carried no Vegas or Clay-CB-
  // grade layer — live those overlap, so the shipped dock is the
  // incremental x0.96. WR ONLY: WR1s were NOT hit harder than the rest of
  // the corps (whole-secondary effect; no public data says who a corner
  // actually shadowed), and QB/TE were untested.
  // List: ELITE_CBS_2026 (overrides.js, Sleeper full names); team + weekly
  // availability auto-resolve via refresh_data.py -> SIM_CB_STATUS. A CB
  // who is Out/Doubtful or off the active roster (IR/PUP/Sus) docks
  // nothing; Questionable still docks (they usually play).
  // SLOT-GRADUATED (research_cb_wr_side.py): the suppression is an OUTSIDE
  // phenomenon — elite corners play outside, slot targets avoid them. Raw
  // per-bucket MSE optima x0.92 outside / x0.96 mixed / x1.00 slot; after
  // the same live-overlap attenuation as the flat dock (raw 0.94 -> 0.96):
  // outside <30% slot rate x0.95, mixed 30-60% x0.97, slot >=60% NO dock.
  // Slot rates = latest PFF season via refresh_data.py -> SIM_WR_SLOT;
  // unknown (rookies / thin routes) = flat 0.96.
  // QB EXTENSION (research_cb_qb_te.py): QBs inherit ~the full WR effect —
  // elite-CB-active weeks 0.949 vs 1.075 control (raw MSE opt x0.94, same
  // as WR), and it VANISHES when the corner sits (out 1.122) — corner-
  // driven, so QB gets the same attenuated flat x0.96 (no slot dimension:
  // the QB aggregates the whole route tree). TE: NO dock — TEs vs these
  // defenses stay equally suppressed with the elite CB out (1.026 vs
  // control 1.093), i.e. a team effect Clay grades + FPA already price.
  // Kill switch: window.SIM_CB_DOCK = false.
  var ELITE_CB_DOCK = { outside: 0.95, mixed: 0.97, slot: 1.0, unknown: 0.96, qb: 0.96 };
  var _cbDock = null;
  function cbShadowMult(opp, pos, p) {
    if (pos !== 'WR' && pos !== 'QB') return 1;
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_CB_DOCK === false) return 1;
    if (!_cbDock) {
      _cbDock = {};
      var st = wnd.SIM_CB_STATUS || {};
      Object.keys(st).forEach(function (nm) {
        var r = st[nm];
        if (!r || !r.tm) return;
        if (r.st && r.st !== 'Active') return;             // IR / PUP / Sus / NFI
        if (/^(Out|Doubtful)/i.test(r.inj || '')) return;  // won't play this week
        _cbDock[normTeam(r.tm)] = 1;
      });
    }
    if (!_cbDock[opp]) return 1;
    if (pos === 'QB') return ELITE_CB_DOCK.qb;
    var sr = p && wnd.SIM_WR_SLOT ? wnd.SIM_WR_SLOT[p.norm] : null;
    if (sr == null) return ELITE_CB_DOCK.unknown;
    return sr >= 60 ? ELITE_CB_DOCK.slot :
           sr >= 30 ? ELITE_CB_DOCK.mixed : ELITE_CB_DOCK.outside;
  }

  // ---------- CB1-out boost ----------
  // backtest_cb1_boost.py (2019-25, 855 CB1-out WR-weeks vs 6,331 active):
  // when a defense's TOP-SNAP corner is out — any CB1, not just an elite
  // one — opposing WRs beat the base×FPA expectation by +7.5% (MSE-optimal
  // flat ×1.04), while CB1-active weeks need nothing (×1.00-1.02 flat).
  // The slot pattern INVERTS vs the dock: slot WRs gain most (+15.5%, opt
  // ×1.10), outside least (×1.02) — the depth chart cascades and the
  // backup lands in the slot. Shipped a shave under the optima (weekly CB
  // absence is barely market-priced, but estimation noise is real):
  // outside ×1.02, mixed ×1.04, slot ×1.08, unknown ×1.04.
  // SIM_CB1_2026 (refresh_data.py): in-season CB1 from 2026 defensive snap
  // counts, preseason from 2025 profiles mapped through current Sleeper
  // teams; `out` = Sleeper Out/Doubtful or off the active roster. Current
  // status applies to every projected week (same limitation as the dock).
  // Composes with the elite dock: elite CB1 out ⇒ dock off AND boost on
  // (backtested: elite CB1-out weeks ran +11.9%).
  // QB EXTENSION (research_cb_qb_te.py): transfers — CB1-out QB weeks run
  // 1.116 vs 1.048 active (+6.5% relative, raw opt x1.08) -> shipped flat
  // x1.04. TE: NO boost (+2% relative only, below the ship bar).
  // Kill switch: window.SIM_CB1_BOOST = false.
  var CB1_BOOST = { outside: 1.02, mixed: 1.04, slot: 1.08, unknown: 1.04, qb: 1.04 };
  var _cb1Out = null;
  function cb1OutBoost(opp, pos, p) {
    if (pos !== 'WR' && pos !== 'QB') return 1;
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_CB1_BOOST === false) return 1;
    if (!_cb1Out) {
      _cb1Out = {};
      var m = wnd.SIM_CB1_2026 || {};
      Object.keys(m).forEach(function (tm) {
        if (m[tm] && m[tm].out) _cb1Out[normTeam(tm)] = 1;
      });
    }
    if (!_cb1Out[opp]) return 1;
    if (pos === 'QB') return CB1_BOOST.qb;
    var sr = p && wnd.SIM_WR_SLOT ? wnd.SIM_WR_SLOT[p.norm] : null;
    if (sr == null) return CB1_BOOST.unknown;
    return sr >= 60 ? CB1_BOOST.slot :
           sr >= 30 ? CB1_BOOST.mixed : CB1_BOOST.outside;
  }

  // ---------- OL-availability dock (own team) ----------
  // backtest_ol_out.py (2019-25, 15k own-team player-weeks; starting five
  // = top-5 C/G/T by games at off_pct>=.6): season-level OL GRADES are
  // already priced (backtest_pff_layers.py — run/pass block flat-to-hurts),
  // but OL AVAILABILITY is a weekly transient. Week-controlled (injuries
  // accumulate late while the blend base tightens — raw buckets confound):
  // RB is dose-responsive (full five +5.5% rel, 1 missing -8%, 2+ -12%);
  // QB/WR/TE flat at 0-1 missing, -3-5% at 2+. Docks ONLY (no full-line
  // boost: preseason everyone reads healthy and a uniform boost would just
  // bias the baseline), shaved for partial market pricing:
  // RB x0.98 (1 missing) / x0.95 (2+); QB/WR/TE x0.97 (2+).
  // SIM_OL_2026 (refresh_data.py): starting five from 2026 snaps
  // in-season, 2025 profiles -> current Sleeper teams preseason; teams
  // whose five can't resolve are absent = no adjustment.
  // Kill switch: window.SIM_OL_DOCK = false.
  var OL_OUT_DOCK = { rb1: 0.98, rb2: 0.95, other2: 0.97 };
  var _olOut = null;
  function olOutDock(tm, pos) {
    if (pos !== 'QB' && pos !== 'RB' && pos !== 'WR' && pos !== 'TE') return 1;
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_OL_DOCK === false) return 1;
    if (!_olOut) {
      _olOut = {};
      var m = wnd.SIM_OL_2026 || {};
      Object.keys(m).forEach(function (t) { _olOut[normTeam(t)] = m[t]; });
    }
    var n = _olOut[tm];
    if (n == null || n < 1) return 1;
    if (pos === 'RB') return n >= 2 ? OL_OUT_DOCK.rb2 : OL_OUT_DOCK.rb1;
    return n >= 2 ? OL_OUT_DOCK.other2 : 1;
  }

  // ---------- in-season snap usage trend ----------
  // Self-activating once data/sim_snaps.js has 2026 weeks (empty preseason).
  // Compares a player's weighted recent snap share (last 3 recorded games
  // BEFORE the projected week, 0.5/0.3/0.2) to his season-to-date average —
  // catching role changes (committee shifts, rookie takeovers) faster than
  // Clay's guide updates. Stale data (last game >3 weeks back) = no adjust;
  // the injury layer owns absences. RB/WR/TE only.
  var SNAP_W = [0.5, 0.3, 0.2];
  // ---------- blowout context (Jack 2026-09-15) ----------
  // SIM_GAMECTX_2026[team][wk] = {pl, gp, db, gdb}: offensive plays / dropbacks and the
  // garbage-time subset (Q4 |margin| >= 17, Q3 >= 28). A share measured in a blowout week
  // is re-measured against COMPETITIVE plays when the player's count fits inside them
  // (a pulled starter: 42 of 42 competitive snaps, not 42 of 66) and the week's weight in
  // the trend is scaled by its competitive share. Never penalizes, never inflates a
  // part-timer (his count exceeds nothing). Kill: window.SIM_BLOWOUT_CTX = false.
  var CTX_MIN_GARBAGE = 6;
  function ctxOf(p, w) {
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_BLOWOUT_CTX === false || !wnd.SIM_GAMECTX_2026) return null;
    var t = wnd.SIM_GAMECTX_2026[p.tm]; var c = t && (t[w] || t[String(w)]);
    return c || null;
  }
  function ctxShare(pct, c, dropbacks) {
    // -> {pct, wt} for one week: pct re-measured on competitive plays if it fits, wt = competitive share
    var tot = dropbacks ? c.db : c.pl, gar = dropbacks ? c.gdb : c.gp;
    if (!tot || gar < CTX_MIN_GARBAGE) return { pct: pct, wt: 1 };
    var comp = tot - gar, cnt = pct / 100 * tot;
    var adj = cnt <= comp + 0.5 ? Math.min(100, 100 * cnt / comp) : pct;   // fits inside competitive plays -> that is his real share
    return { pct: cnt >= 0.85 * comp ? adj : pct, wt: comp / tot, adjusted: cnt >= 0.85 * comp && adj > pct + 0.5 };
  }
  function ctxNote(p, wk) {
    // weeks whose snap or route share was re-measured (NOTES chip)
    var out = [];
    var sn = (typeof window !== 'undefined' && window.SIM_SNAPS_2026) ? window.SIM_SNAPS_2026[p.name] : null;
    if (sn && sn.w) Object.keys(sn.w).forEach(function (w) { var c = ctxOf(p, +w); if (c && +w < wk && ctxShare(sn.w[w], c, false).adjusted) out.push('wk' + w); });
    return out;
  }
  function snapMult(p, wk) {
    if (p.pos !== 'RB' && p.pos !== 'WR' && p.pos !== 'TE') return 1;
    var sn = (typeof window !== 'undefined' && window.SIM_SNAPS_2026) ? window.SIM_SNAPS_2026[p.name] : null;
    if (!sn || !sn.w) return 1;
    var past = Object.keys(sn.w).map(Number).filter(function (w) { return w < wk; }).sort(function (a, b) { return b - a; });
    if (past.length < 2 || past[0] < wk - 3) return 1;
    var val = {}, wt = {};
    past.forEach(function (w) { var c = ctxOf(p, w); var r = c ? ctxShare(sn.w[w], c, false) : { pct: sn.w[w], wt: 1 }; val[w] = r.pct; wt[w] = r.wt; });
    var recent = 0, wsum = 0;
    past.slice(0, 3).forEach(function (w, i) { recent += val[w] * SNAP_W[i] * wt[w]; wsum += SNAP_W[i] * wt[w]; });
    recent /= wsum;
    var seasonAvg = past.reduce(function (t, w) { return t + val[w] * wt[w]; }, 0) / past.reduce(function (t, w) { return t + wt[w]; }, 0);
    // 1.0%/snap-pt: backtested 2019-25 vs nflverse snap history
    // (backtest_snap_defense.py) — monotonic dose-response, empirical slope
    // 1.09%/pt, the original 0.8 was the only UNDERSIZED layer in the engine.
    return Math.min(1.30, Math.max(0.75, 1 + 1.0 * (recent - seasonAvg) / 100));
  }

  // ---------- TE route-participation trend ----------
  // backtest_route_trend.py (2023-25, 6,761 player-weeks with both route and
  // snap trends from nflverse participation): route delta correlates .92
  // with snap delta — for WR (e=0 best) and RB (noise) the shipped snap
  // trend already carries it. TE is the exception: TEs block, so snap %
  // overstates a blocking TE's usage, and the route trend adds a real
  // increment ON TOP of snapMult (TE MSE 27.90 -> 27.58 at e=1.0,
  // monotone; +15 route-pt risers beat even the snap-adjusted base by 29%
  // — route share is the leading indicator for TE role changes). Same
  // construction as snapMult: weighted last-3 (0.5/0.3/0.2) vs season
  // average, >=2 past games, stale >3 wks = no-op, clamp [0.75, 1.30],
  // 1.0%/route-pt. Data: SIM_ROUTES_2026 (data/sim_routes.js, built by
  // pull_pace_tracker.py from 2026 pbp+participation — empty preseason so
  // the layer is a provable no-op). Kill switch: window.SIM_ROUTE_TREND = false.
  function routeMult(p, wk) {
    if (p.pos !== 'TE') return 1;
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_ROUTE_TREND === false) return 1;
    var rr = wnd.SIM_ROUTES_2026 ? wnd.SIM_ROUTES_2026[p.norm] : null;
    if (!rr) return 1;
    var past = Object.keys(rr).map(Number).filter(function (w) { return w < wk; }).sort(function (a, b) { return b - a; });
    if (past.length < 2 || past[0] < wk - 3) return 1;
    var val = {}, wt = {};
    past.forEach(function (w) { var c = ctxOf(p, w); var r = c ? ctxShare(rr[w], c, true) : { pct: rr[w], wt: 1 }; val[w] = r.pct; wt[w] = r.wt; });
    var recent = 0, wsum = 0;
    past.slice(0, 3).forEach(function (w, i) { recent += val[w] * SNAP_W[i] * wt[w]; wsum += SNAP_W[i] * wt[w]; });
    recent /= wsum;
    var avg = past.reduce(function (t, w) { return t + val[w] * wt[w]; }, 0) / past.reduce(function (t, w) { return t + wt[w]; }, 0);
    return Math.min(1.30, Math.max(0.75, 1 + 1.0 * (recent - avg) / 100));
  }

  // ---------- soft-pass-rush QB boost ----------
  // backtest_pressure.py (2018-25, 2,263 QB player-weeks): the pressure
  // effect is ONE-SIDED. QBs facing the softest pass rushes (opp pressure
  // rate >=3pts UNDER league average, season-to-date) beat the FPA-adjusted
  // base by ~+10%; high-pressure defenses show NO suppression beyond what
  // FPA/Vegas already price (pressure-resistant QBs offset, r=.44 skill).
  // Asymmetric boost, raw MSE optimum x1.08 (-0.46% on the FPA base,
  // consistent at every opp sample depth), shipped shaved to x1.05 for
  // Vegas overlap. Trust ramps with observed opp dropbacks (n/250, gate
  // n>=80). Defense pressure rate is NOT a stable identity (in-season
  // r=.31) which is why this reads season-to-date, not priors — and why
  // there is no dock side. WR tested: nothing (e=0). Data:
  // SIM_PRESSURE_2026 {def: [pressured, dropbacks]} in sim_routes.js
  // (pull_pace_tracker.py) — empty preseason, provable no-op.
  // Kill switch: window.SIM_PRESSURE_BOOST = false.
  // 2026-09-14 PROXY REWIRE (backtest_pressure_proxy.py): was_pressure lives
  // in nflverse pbp_participation, which (FTN, 2023+) is published only
  // AFTER the postseason — the map was empty all season. SIM_PRESSURE_2026
  // is now (qb_hit OR sack)/dropbacks from nightly pbp: def-season corr
  // +0.68 vs true pressure, same one-sided shape; sweep on the identical
  // 2,263 rows: best thr -0.020 x1.08 (-0.37%), shipped x1.05 = -0.36%
  // (bootstrap 90% CI [-0.68, -0.04], P(improve) .97; true-flag shipped
  // was -0.39%, .98). Thresholds sit at the same ~0.65 sd depth (proxy
  // rate sd .030 vs .047). Gates unchanged (n>=80 opp dropbacks -> first
  // boosts land ~Week 3; trust n/250).
  var PRESSURE_BOOST = 1.05;
  var PRESSURE_THR   = -0.02;   // PROXY units (hit|sack rate); was -0.03 on was_pressure
  var _pressLg = null;
  function pressureMult(opp, pos) {
    if (pos !== 'QB') return 1;
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_PRESSURE_BOOST === false) return 1;
    var m = wnd.SIM_PRESSURE_2026 || null;
    if (!m) return 1;
    if (_pressLg == null) {
      var p = 0, n = 0;
      Object.keys(m).forEach(function (t) { p += m[t][0]; n += m[t][1]; });
      _pressLg = n >= 1000 ? p / n : -1;   // -1 = not enough league data yet
    }
    if (_pressLg < 0) return 1;
    var v = m[opp] || m[normTeam(opp)];
    if (!v || v[1] < 80) return 1;
    var dev = v[0] / v[1] - _pressLg;
    if (dev > PRESSURE_THR) return 1;
    return 1 + (PRESSURE_BOOST - 1) * Math.min(1, v[1] / 250);
  }

  // ---------- RB TD-luck mean reversion ----------
  // backtest_rb_role.py (2026-09-14, 4,405 RB player-weeks 2019-25, P=5 base
  // x Vegas): a back's realized PPG carries TD luck his red-zone USAGE says
  // should regress. xTD = league TD rate per touch by yardline bucket (pooled
  // pbp 2018-25) summed over his season-to-date carries + targets; luck =
  // (xTD - TD)/g. Unlucky tercile (+0.16/g) runs actual/base 1.134, lucky
  // tercile 0.996. Additive correction on the REALIZED half of the blend:
  //   + TDLUCK_K * tdPts * luck * g/(P+g)
  // LOYO -0.36%, 5/7 years, k picks .5-1.0 every fold; identical when luck is
  // centered per season (pure per-player mean reversion, not a level fix -
  // the level is the weekly tuner's tdMult job). Same size class as the
  // pressure boost. Every game-script ROLE interaction (closer x favored,
  // passing-down back x underdog, goal-line share) graded WORSE - not shipped.
  // Data: SIM_RB_TDLUCK_2026 {norm: {xtd, td, g, n}} in sim_routes.js
  // (pull_pace_tracker.py, nightly pbp) - empty preseason, provable no-op.
  // Applied AFTER the chain (the backtest added it to base x Vegas), scaled by
  // availability so a zeroed/docked player is not handed TD points back.
  // Kill switch: window.SIM_TD_LUCK = false.
  // RECEIVERS (backtest_wr_tdluck.py, 2026-09-14, 10,597 WR/TE player-weeks):
  // the same regression is LARGER for pass-catchers - xTD per target from a
  // yardline x end-zone-throw table (depth matters: EZ throw from the 30 =
  // .27 vs a screen at the 30 = .03). Unlucky tercile runs actual/base WR
  // 1.112 / TE 1.186, lucky 0.954 / 0.974. LOYO -0.93% (WR -0.79%, TE
  // -1.26%), 7/7 years, k=1.0 every fold, identical centered per season
  // (pure regression). The biggest single-layer gain in the lab. Data:
  // SIM_REC_TDLUCK_2026 (same file). Kill: window.SIM_TD_LUCK_REC = false
  // (SIM_TD_LUCK = false kills both).
  // QB (backtest_qb_tdluck.py, 2026-09-14, 2,554 QB player-weeks): PASSING
  // TD luck only - xPassTD from his targets' yardline x end-zone-throw
  // probabilities (throwaways 0); QB RUSH luck graded flat (+0.02%) and is
  // excluded. Unlucky tercile actual/base 1.097, lucky 0.991. LOYO pass-
  // only -0.44% (5/7), k=.5 x pass-TD value, every fold picks .5-.75.
  // NOT centered: subtracting the live season-to-date league mean graded
  // weaker (-0.34%) than the plain form, so QB matches RB/WR/TE exactly.
  // Data: SIM_QB_TDLUCK_2026. Kill: window.SIM_TD_LUCK_QB = false.
  var TDLUCK_K = 0.75;        // RB (backtest_rb_role.py)
  var TDLUCK_K_REC = 1.0;     // WR/TE (backtest_wr_tdluck.py)
  var TDLUCK_K_QB = 0.5;      // QB passing (backtest_qb_tdluck.py)
  function tdLuckAdj(p, sc) {
    var isRec = p.pos === 'WR' || p.pos === 'TE', isQb = p.pos === 'QB';
    if (p.pos !== 'RB' && !isRec && !isQb) return 0;
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_TD_LUCK === false) return 0;
    if (isRec && wnd.SIM_TD_LUCK_REC === false) return 0;
    if (isQb && wnd.SIM_TD_LUCK_QB === false) return 0;
    var m = (isQb ? wnd.SIM_QB_TDLUCK_2026 : isRec ? wnd.SIM_REC_TDLUCK_2026 : wnd.SIM_RB_TDLUCK_2026) || null;
    var r = m ? m[p.norm] : null;
    if (!r || !r.g) return 0;
    var d = jsData();
    var rec = d.players && d.players[p.norm];
    var g = (rec && rec.g) ? rec.g : r.g;            // games in the P=5 blend
    var luck = (r.xtd - r.td) / r.g;
    var tdPts = isQb ? ((sc && sc.pass_td) || 4)
      : isRec ? ((sc && sc.rec_td) || 6)
      : (((sc && sc.rush_td) || 6) + ((sc && sc.rec_td) || 6)) / 2;
    var k = isQb ? TDLUCK_K_QB : isRec ? TDLUCK_K_REC : TDLUCK_K;
    return k * tdPts * luck * (g / (JS_PRIOR_STRENGTH + g));
  }

  // ---------- weather (wind) docks ----------
  // backtest_weather.py (2019-25, pbp game weather, 97% outdoor coverage):
  // wind dose-response survives BOTH Vegas adjustment (books underprice
  // wind for player scoring) and week-of-season control (windy games
  // cluster late — the confound the OL backtest exposed): week-controlled
  // relative ratios at wind 15+ QB .906 / WR .875 / TE .926, at 10-15
  // ~.965-.975. RB immune (slightly BETTER in wind/cold — teams run).
  // K (pbp-reconstructed weeks vs own mean): ~-0.5 pts in any 10+ wind.
  // NO dome boost: indoor buckets read +3-4% but that is venue-mix
  // composition (dome players' own baselines already contain their dome
  // games); wind docks are event-rare vs each player's mixed baseline, so
  // they are safe. Cold skipped v1 (wind-correlated; would double-dock).
  // Shipped shaved: wind>=15 QB x0.94 / WR x0.93 / TE x0.95; 10-15
  // x0.97/x0.97/x0.98; K x0.95 at >=10. Data: SIM_WEATHER_2026
  // (data/sim_weather.js, refresh_data.py) — Open-Meteo kickoff-hour
  // forecasts per OUTDOOR home stadium, 16-day horizon; missing entry
  // (dome, beyond horizon, preseason) = no-op.
  // Kill switch: window.SIM_WEATHER = false.
  var WEATHER_DOCK = {
    QB: { w15: 0.94, w10: 0.97 },
    WR: { w15: 0.93, w10: 0.97 },
    TE: { w15: 0.95, w10: 0.98 },
    K:  { w15: 0.95, w10: 0.95 }
  };
  function weatherMult(p, wk, slot) {
    var d = WEATHER_DOCK[p.pos];
    if (!d || !slot) return 1;
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_WEATHER === false) return 1;
    var m = wnd.SIM_WEATHER_2026 || null;
    if (!m) return 1;
    var home = slot.home ? p.tm : slot.opp;
    var t = m[home] || m[normTeam(home)];
    var w = t && (t[wk] || t[String(wk)]);
    if (!w || w.wind == null) return 1;
    if (w.wind >= 15) return d.w15;
    if (w.wind >= 10) return d.w10;
    return 1;
  }

  // ---------- in-season team pace / play-calling trend ----------
  // data/pace_2026.js (pull_pace_tracker.py): season-to-date team tendencies
  // vs a coach-research-aware baseline (same coach -> own 2025; new coach ->
  // his prior pace identity + the roster's pass mix). Validated 2019-25:
  // early-season drift vs baseline PERSISTS to the rest of the season
  // (no-huddle r .78, 2+TE .75, PROE .61, neutral pass rate .57, plays .44).
  // MULTIPLIERS BACKTESTED NEGATIVE (backtest_pace_layer.py, wks 5/9/13
  // 2019-25): applying them to player means was +0.2-0.5% WORSE MAE with a
  // ~49% win rate and monotonically worse at higher elasticity — Vegas totals
  // and realized PPG already carry the information at player level. So
  // paceMult exists for the TEAM PACE tab's intel display but is NOT applied
  // in weeklyProjection. Do not re-enable without a passing backtest.
  function paceMult(p) {
    var d = (typeof window !== 'undefined' && window.SIM_PACE_2026) || null;
    var t = d && d.teams && d.teams[p.tm];
    if (!t || !t.cur || !t.games || p.isDST || p.pos === 'K') return 1;
    var b = t.base || {}, c = t.cur, m = 1;
    if (c.plays && b.plays) {
      m *= Math.min(1.06, Math.max(0.94, 1 + 0.5 * (c.plays - b.plays) / b.plays));
    }
    if (c.npr != null && b.npr != null) {
      var dp = c.npr - b.npr; // absolute pass-rate drift (e.g. +0.04)
      if (p.pos === 'RB') m *= Math.min(1.05, Math.max(0.95, 1 - 0.5 * dp));
      else m *= Math.min(1.05, Math.max(0.95, 1 + 0.8 * dp));
    }
    if (p.pos === 'TE' && c.te2 != null && b.te2 != null) {
      m *= Math.min(1.04, Math.max(0.96, 1 + 0.4 * (c.te2 - b.te2)));
    }
    return 1 + Math.min(1, t.games / 6) * (m - 1);
  }

  // ---------- JS Weekly (in-season model) ----------
  // Preseason it EQUALS Clay (the 2021-25 backtest showed any preseason
  // history blend loses to Clay alone — see backtest_hybrid.py). In-season
  // it becomes its own model from live factors:
  //   base   = Bayesian shrink of Clay per-game toward actual 2026 PPG
  //            (prior strength = JS_PRIOR_STRENGTH games; by week ~8 the
  //            season, not the summer guide, is doing the talking)
  //   opp    = actual fantasy points ALLOWED per game by position, blended
  //            over the Clay unit grades as the defense's sample grows
  //   plus the shared live layers: Vegas, snap trend, windows/byes.
  // Player efficiency/usage (tgt, carries) is embedded in realized PPG and
  // the snap trend; per-game stat mix is also captured for exact rescoring.
  var JS_PRIOR_STRENGTH = 5;   // Clay prior worth ~5 games of evidence
  var JS_FPA_FULL_TRUST = 8;   // defense FPA gets full weight after 8 games
  function jsData() { return (typeof window !== 'undefined' && window.SIM_2026) || {}; }
  function jsBasePg(p, sc, clayPg) {
    var d = jsData();
    var rec = d.players && d.players[p.norm];
    if (!rec || !rec.g) return clayPg; // no 2026 sample yet -> pure Clay
    var pg = rec.pg || {};
    var ppg = rec.ppg; // half-PPR actuals -> league scoring via ACTUAL stat mix
    ppg += (sc.rec - 0.5) * (pg.rec || 0);
    ppg += (sc.pass_td - 4) * (pg.ptd || 0);
    ppg += (sc.pass_yd - 0.04) * (pg.py || 0);
    ppg += (sc.rush_yd - 0.1) * (pg.ry || 0);
    ppg += (sc.rec_yd - 0.1) * (pg.rcy || 0);
    ppg += (sc.rush_td - 6) * (pg.rtd || 0);
    ppg += (sc.rec_td - 6) * (pg.rctd || 0);
    if (p.pos === 'TE' && sc.bonus_rec_te) ppg += sc.bonus_rec_te * (pg.rec || 0);
    ppg = Math.max(0, ppg);
    return (JS_PRIOR_STRENGTH * clayPg + rec.g * ppg) / (JS_PRIOR_STRENGTH + rec.g);
  }
  var JS_FPA_ELASTICITY = 0.25; // backtested (backtest_snap_defense.py):
  // in-season FPA carries real matchup signal but at 25% of the raw
  // deviation — full-strength application graded WORSE than no adjustment.
  function jsOppMult(opp, pos, clayMult) {
    if (pos === 'K' || pos === 'DST') return 1;
    var d = jsData();
    var fpa = d.fpa && d.fpa[opp];
    var lg = d.lgFpa && d.lgFpa[pos];
    if (!fpa || !lg || fpa[pos] == null || !fpa._g) return clayMult;
    var actual = 1 + JS_FPA_ELASTICITY * (Math.min(1.25, Math.max(0.8, fpa[pos] / lg)) - 1);
    var w = Math.min(1, fpa._g / JS_FPA_FULL_TRUST);
    return w * actual + (1 - w) * clayMult;
  }

  // ---------- weekly projection ----------
  // Vegas elasticity BACKTESTED vs historical closing lines 2019-25
  // (backtest_vegas_layer.py, 17.6k player-weeks): the old uniform 0.5 was
  // twice too hot for pass positions — implied totals correlate with team
  // quality Clay already prices, and the exploitable matchup residual has
  // slope ~0.20-0.25. RB is the exception at 0.50: game script is real
  // (favorites feed their backs, trailing teams abandon the run). K kept at
  // 0.5 untested — kicker points are nearly a direct share of team points.
  var VEGAS_ELAS = { QB: 0.25, RB: 0.50, WR: 0.25, TE: 0.25, K: 0.50 };
  function vegasMult(implied, avgImplied, pos) {
    var e = VEGAS_ELAS[pos] != null ? VEGAS_ELAS[pos] : VEGAS_ELASTICITY;
    var m = 1 + e * ((implied - avgImplied) / avgImplied);
    return Math.min(1.35, Math.max(0.7, m));
  }
  function dstWeeklyMean(oppImplied) {
    // refit on 3,625 pbp-reconstructed DST weeks vs closing implied totals:
    // realized 16.2 - 0.436x (engine's synthesized 15.5 - 0.42x was ~0.35
    // pts low but the slope was dead on)
    var m = 16.2 - 0.436 * oppImplied;
    // slow weekly tuner (data/sim_tuning.js): additive DST level shift, shrunk to 0
    if (typeof window !== 'undefined' && window.SIM_TUNING && typeof window.SIM_TUNING.dstShift === 'number') m += window.SIM_TUNING.dstShift;
    return Math.max(1.0, m);
  }

  // ---------- prop anchor (market-anchored weekly mean) ----------
  // See PROP_ANCHOR_SPEC.md. Where weekly prop lines exist
  // (BETTING_2026.weeklyProps — UD/PP stat medians + DK anytime-TD odds),
  // the shipped weekly mean blends toward the market. The CLEAN model and
  // JS Weekly keep racing in every lock, and comps are never touched, so
  // the vsBooks grading and the LINES divergence view stay non-circular.
  // weeklyProps is empty preseason -> the whole layer is a provable no-op
  // until Week 1 lines land. Kill switch: window.SIM_PROP_ANCHOR = false;
  // per-player weight override: PROP_ANCHOR_OVERRIDES (overrides.js).
  var PROP_W            = 0.70; // market weight; retroactively tunable from lock history
  var PROP_COVERAGE_MIN = 0.60; // covered non-TD share of model points required
  var PROP_ATD_JUICE    = 1.06; // flat devig on anytime-TD implied probability
  var PROP_MAX_AGE_DAYS = 8;    // freshness guard: entries whose asOf is older
  var PROP_DOCKED_MAX_AGE_DAYS = 2; // docked players (Doubtful / Q+DNP): only lines posted
                                    // since the designation could have landed (2026-09-11)
  // are ignored — weeklyProps has been seen carrying preseason-game lines
  // mis-keyed to future regular-season weeks (13 W15 entries dated 08-20);
  // real slates re-pull pregame so live entries are always days old at most
  var PROP_STATS = ['py', 'ry', 'rcy', 'rec']; // non-TD anchor stats
  var PROP_SC    = { py: 'pass_yd', ry: 'rush_yd', rcy: 'rec_yd', rec: 'rec' };

  var _propWkCache = {};
  function propCacheReset() { _propWkCache = {}; }
  function propMap(wk) {
    var props = (typeof window !== 'undefined' && window.BETTING_2026 &&
      window.BETTING_2026.weeklyProps && window.BETTING_2026.weeklyProps[String(wk)]) || null;
    var c = _propWkCache[wk];
    if (c && c.src === props) return c.map; // per-week cache — marketRate walks many weeks per call
    var map = {};
    // No stale filtering here: the direct anchor applies PROP_MAX_AGE_DAYS
    // itself, while the market rate track reads old entries on purpose.
    if (props) Object.keys(props).forEach(function (nm) { map[norm(nm)] = props[nm]; });
    _propWkCache[wk] = { src: props, map: map };
    return map;
  }
  // Consensus line per stat = median across books — same rule as the LINES
  // view and the scoreWeek grading.
  function propConsensus(entry, k) {
    var vals = [];
    ['UD', 'PP', 'DK', 'FD', 'MGM'].forEach(function (b) {
      if (entry[b] && typeof entry[b][k] === 'number') vals.push(entry[b][k]);
    });
    if (!vals.length) return null;
    vals.sort(function (a, b) { return a - b; });
    return vals[Math.floor(vals.length / 2)];
  }
  // Closed-form gamma median/mean ratio from the player's SAMPLED weekly
  // shape (same total relative sd as samplePlayerScore) — converts a prop
  // line (a median) to mean scale without running a sim. Also used by the
  // LINES view so its divergence read stays pure-model when the anchor is on.
  function gammaMedRatio(p) {
    var rel = p._relW !== undefined ? p._relW
      : Math.sqrt(Math.pow(RESID_SHRINK * (p.sigmaPct || 0.5), 2) + 0.04);
    var k = 1 / (rel * rel);
    return Math.min(1.0, Math.max(0.75, (3 * k - 0.8) / (3 * k + 0.2)));
  }
  function amToProb(odds) { return odds < 0 ? -odds / (-odds + 100) : 100 / (odds + 100); }
  // Prop-implied blended weekly mean for player p in week wk, or null when
  // there is no anchor (no lines / K / DST / coverage gate / override 0).
  // base = what effMean would return without the anchor (jsMean in-season,
  // Clay-layer mean preseason). compsWk = the CLEAN per-week component means.
  // Market weight for player p: per-player override -> global console
  // override -> PROP_W. 0 disables ALL market influence for the player
  // (direct anchor AND the market rate track).
  function propWeight(p) {
    var ov = (typeof window !== 'undefined' && window.PROP_ANCHOR_OVERRIDES) || {};
    var w = ov[p.name] != null ? ov[p.name]
      : (typeof window !== 'undefined' && typeof window.PROP_W_OVERRIDE === 'number')
        ? window.PROP_W_OVERRIDE
      // slow weekly tuner (tune_weekly.py -> data/sim_tuning.js): per-position
      // market weight re-fit on every scored week, shrunk to PROP_W with a
      // 4-week-equivalent prior. Jack 2026-09-14: "slowly implement each week".
      : (typeof window !== 'undefined' && window.SIM_TUNING && window.SIM_TUNING.propW
         && typeof window.SIM_TUNING.propW[p.pos] === 'number')
        ? window.SIM_TUNING.propW[p.pos] : PROP_W;
    return w > 0 ? Math.min(1, w) : 0;
  }

  // Prop-implied fantasy MEAN for one player + one week's prop entry, in
  // the given scoring — or null when the lines can't carry it (no K lines /
  // coverage gate). compsWk = that week's CLEAN model component means; the
  // uncovered stats fall back to them, so fp is on the same weekly-mean
  // scale as compsWk (this is what lets the rate track divide the factor
  // back out exactly).
  function propImpliedFp(p, entry, sc, compsWk) {
    var medRatio = gammaMedRatio(p);
    // Kickers (Phase 3): a kicking-points line IS the fantasy stat — no
    // coverage gate (one line is full coverage). FG-made fallback: 3/FG +
    // the model's XP mean.
    if (p.pos === 'K') {
      var kpts = propConsensus(entry, 'kpts');
      var fgmL = propConsensus(entry, 'fgm');
      if (kpts != null && kpts > 0) return kpts / medRatio;
      if (fgmL != null && fgmL > 0) return (fgmL / medRatio) * 3 + (compsWk.xpm || 0);
      return null;
    }
    function scv(k) {
      var v = sc[PROP_SC[k]];
      if (k === 'rec' && p.pos === 'TE' && sc.bonus_rec_te) v += sc.bonus_rec_te;
      return v;
    }
    // Non-TD stats: line (median -> mean scale) where posted, model comp
    // (already mean scale) where not. Gate: posted lines must cover >=60%
    // of the model's non-TD points or we don't anchor at all.
    var covered = 0, modelNonTd = 0, fp = 0;
    PROP_STATS.forEach(function (k) {
      var mPts = (compsWk[k] || 0) * scv(k);
      modelNonTd += mPts;
      var line = propConsensus(entry, k);
      if (line != null && line > 0) {
        covered += mPts;
        fp += (line / medRatio) * scv(k);
      } else {
        fp += mPts;
      }
    });
    if (!(modelNonTd > 0) || covered / modelNonTd < PROP_COVERAGE_MIN) return null;
    // Pass TDs: the posted line when there is one, else the model.
    var ptdLine = propConsensus(entry, 'ptd');
    fp += (ptdLine != null && ptdLine > 0 ? ptdLine / medRatio : (compsWk.ptd || 0)) * sc.pass_td;
    // Rush+rec TDs: devigged anytime-TD odds -> Poisson mean, split rush/rec
    // by the model's own ratio; raw 0.5 rtd/rctd novelty lines are ignored.
    var atd = propConsensus(entry, 'atd');
    var rtdM = compsWk.rtd || 0, rctdM = compsWk.rctd || 0;
    if (atd != null) {
      var pTd = Math.min(0.85, Math.max(0.01, amToProb(atd) / PROP_ATD_JUICE));
      var lam = -Math.log(1 - pTd);
      var tot = rtdM + rctdM;
      var rushShare = tot > 0 ? rtdM / tot : (p.pos === 'QB' ? 1 : p.pos === 'RB' ? 0.85 : 0.03);
      fp += lam * rushShare * sc.rush_td + lam * (1 - rushShare) * sc.rec_td;
    } else {
      fp += rtdM * sc.rush_td + rctdM * sc.rec_td;
    }
    return fp;
  }

  function propAnchorMean(p, wk, sc, compsWk, base, maxAgeDays) {
    if (p.isDST || !(base > 0)) return null;
    var entry = propMap(wk)[p.norm];
    if (!entry) return null;
    // Freshness guard for the DIRECT anchor only: an outdated line is not
    // the market's current view of THIS week. (The rate track deliberately
    // reads old entries — past weeks' lines are archival observations.)
    var maxAge = maxAgeDays != null ? maxAgeDays : PROP_MAX_AGE_DAYS;
    if (entry.asOf && new Date(entry.asOf).getTime() < Date.now() - maxAge * 86400000) return null;
    var w = propWeight(p);
    if (!w) return null;
    var fp = propImpliedFp(p, entry, sc, compsWk);
    if (fp == null) return null;
    // Conditional weight (Jack 2026-09-14, weekly tuner `belowW`): when the
    // CLEAN model sits well BELOW the market on a STARTER (gap >= BELOW_GAP
    // pts, market >= BELOW_STARTER_MIN), W1 vs-books grading showed the
    // actual landing on the model's side 14/18 — so the tuner fits a
    // separate market weight for that case, shrunk to PROP_W. Per-player
    // overrides still win. The applied weight is exposed (p._propWUsed) so
    // lock rows can store it and the tuner reconstructs the market exactly.
    var ovMap = (typeof window !== 'undefined' && window.PROP_ANCHOR_OVERRIDES) || {};
    var TU = (typeof window !== 'undefined' && window.SIM_TUNING) || null;
    if (TU && typeof TU.belowW === 'number' && ovMap[p.name] == null
        && fp - base >= BELOW_GAP && fp >= BELOW_STARTER_MIN) w = Math.min(1, Math.max(0, TU.belowW));
    p._propWUsed = w;
    return w * fp + (1 - w) * base;
  }
  var BELOW_GAP = 3.0;          // half-PPR pts the market must sit above the clean model
  var BELOW_STARTER_MIN = 8.0;  // market-implied mean that counts as a starter

  // ---------- Phase 4: market rate track ----------
  // A weekly prop is the market's estimate of the player's per-game rate,
  // conditional on playing. Divide each observed week's prop-implied mean
  // by that week's known multipliers -> a matchup-free neutral rate; EWMA
  // the observations (recency half-life MKT_HALF_LIFE weeks) into the
  // market's standing opinion, blended into the base rate for weeks with
  // NO direct lines (future weeks in simSeason/simLeague, and un-lined
  // players). Weight = propWeight x confidence, confidence ramping to 1 at
  // MKT_FULL_TRUST effective observations — one slate gets half the direct
  // anchor's weight. Injury/games stay owned by the availability layers:
  // props are conditional on playing, so this anchors RATE only.
  // Kill switch: window.SIM_MKT_RATE = false (independent of the direct
  // anchor's SIM_PROP_ANCHOR).
  var MKT_HALF_LIFE  = 3; // weeks; EWMA recency half-life
  var MKT_FULL_TRUST = 2; // effective observations for full market weight

  // ---------- teammate-context guard for the rate track (2026-09-11) ----------
  // A prop line is conditional on WHO ELSE plays that week. Stevenson's W1
  // lines were posted with Henderson (ankle) ruled out, so the "neutral
  // rate" backed out of them carried a lone-back workload into all 17
  // weeks (season PPG 12.8 -> 15.1 while Henderson misses one game). An
  // observed week is skipped when a meaningful position-group teammate —
  // same pos, or the team's starting QB for a RB/WR/TE — was absent that
  // week but is NOT absent in the projected week, or the reverse. Absence
  // = in-season designation (Out/Doubtful/IR map), an injury-start window
  // that skips the game, or, for played weeks, no 2026 stat row while the
  // team played (SIM_2026 wks). Season-long absences (IR/PUP/NFI flag and
  // zero 2026 games) are the new normal on both sides and never
  // contaminate. Kill switch: window.SIM_MKT_CTX = false.
  var MKT_CTX_MIN_PPG = 3.0;   // teammate per-game PPR level that matters ...
  var MKT_CTX_MIN_REL = 0.30;  // ... and >= this share of the player's own level
  var _roster = null, _rosterByTm = null, _tmQb1 = null, _playedCache = null;
  function _ppgLevel(q) { return (q.ptsPPR || 0) / (q.qbWindow ? (q.qbWindow.games || 17) : 17); }
  function _rosterIdx() {
    if (_rosterByTm || !_roster) return _rosterByTm;
    _rosterByTm = {}; _tmQb1 = {};
    _roster.forEach(function (q) {
      if (q.isDST) return;
      (_rosterByTm[q.tm] = _rosterByTm[q.tm] || []).push(q);
      if (q.pos === 'QB' && (!_tmQb1[q.tm] || _ppgLevel(q) > _ppgLevel(_tmQb1[q.tm]))) _tmQb1[q.tm] = q;
    });
    return _rosterByTm;
  }
  // PER TEAM: "week w is in the books" only for teams whose own game has
  // rows (Wed/Thu teams play days before the rest — a league-wide flag made
  // every unplayed team's teammates look absent and silenced the whole track).
  function _playedTeamWeeks() {
    var d = jsData();
    if (_playedCache && _playedCache.src === d && _playedCache.roster === _roster) return _playedCache.set;
    var set = {}, ps = d.players || {};
    (_roster || []).forEach(function (q) {
      var row = ps[q.norm];
      if (row && row.wks) row.wks.forEach(function (w) { set[q.tm + '|' + w] = 1; });
    });
    _playedCache = { src: d, roster: _roster, set: set };
    return set;
  }
  function _longTermOut(q) {
    if (!/PUP|IR|NFI|Injured Reserve|Non Football/i.test(q.injFlag || '')) return false;
    var row = (jsData().players || {})[q.norm];
    return !row || !(row.g > 0);
  }
  function _absentInWeek(q, w, schedule) {
    var gi = (schedule.gameWeeks[q.tm] || []).indexOf(w) + 1;
    if (gi <= 0) return false; // bye — nothing to compare
    if (q.qbWindow && (q.qbWindow.src === 'injury-start' || q.qbWindow.src === 'override') &&
        (gi < q.qbWindow.s || gi > q.qbWindow.e)) return true;
    var m = _inj && _inj.map[q.norm];
    if (m && w >= m.from && w <= m.to && m.mult <= 0.5) return true;
    if (_playedTeamWeeks()[q.tm + '|' + w]) {
      var row = (jsData().players || {})[q.norm];
      if (!row || !row.wks || row.wks.indexOf(w) < 0) return true;
    }
    return false;
  }
  // true = week owk's lines were posted under a different teammate context
  // than the projected week wk, so its rate observation must not carry over.
  function marketObsContaminated(p, owk, wk, schedule) {
    var wnd = typeof window !== 'undefined' ? window : null;
    if (wnd && wnd.SIM_MKT_CTX === false) return false;
    if (p.isDST || p.pos === 'QB') return false;
    var idx = _rosterIdx();
    if (!idx) return false;
    var mates = idx[p.tm] || [], lvl = _ppgLevel(p), qb1 = _tmQb1[p.tm] || null;
    for (var i = 0; i < mates.length; i++) {
      var q = mates[i];
      if (q === p) continue;
      if (q.pos === 'QB') { if (q !== qb1) continue; }
      else if (q.pos !== p.pos) continue;
      var ql = _ppgLevel(q);
      if (q.pos !== 'QB' && (ql < MKT_CTX_MIN_PPG || ql < MKT_CTX_MIN_REL * lvl)) continue;
      if (_longTermOut(q)) continue;
      if (_absentInWeek(q, owk, schedule) !== _absentInWeek(q, wk, schedule)) return true;
    }
    return false;
  }

  function marketRate(p, wk, sc, schedule) {
    if (p.isDST) return null;
    var wnd = typeof window !== 'undefined' ? window : null;
    if (wnd && wnd.SIM_MKT_RATE === false) return null;
    var wp = (wnd && wnd.BETTING_2026 && wnd.BETTING_2026.weeklyProps) || {};
    var obs = [];
    Object.keys(wp).forEach(function (k) {
      var owk = +k;
      if (!owk || owk === wk) return; // the projected week itself is the direct anchor's job
      var entry = propMap(owk)[p.norm];
      if (!entry) return;
      // rebuild that week's factor exactly as weeklyProjection builds it
      var slot = schedule.byTeam[p.tm] && schedule.byTeam[p.tm][owk];
      if (!slot) return;
      var gi = (schedule.gameWeeks[p.tm] || []).indexOf(owk) + 1;
      if (p.qbWindow && (gi < p.qbWindow.s || gi > p.qbWindow.e)) return;
      if (marketObsContaminated(p, owk, wk, schedule)) return; // teammate out that week (or this one) — not the same player
      var perGameDiv = p.qbWindow ? p.qbWindow.games : 17;
      var rampF = 1;
      if (p.ramp) {
        var R = RAMP[p.ramp];
        rampF = (gi > 0 && gi <= R.head.length) ? R.head[gi - 1] : R.tail;
      }
      var f = vegasMult(slot.implied, schedule.avgImplied, p.pos)
        * ((defenseAdj()[slot.opp] || {})[p.pos] || 1)
        * cbShadowMult(slot.opp, p.pos, p) * cb1OutBoost(slot.opp, p.pos, p)
        * olOutDock(p.tm, p.pos) * pressureMult(slot.opp, p.pos)
        * weatherMult(p, owk, slot)
        * snapMult(p, owk) * routeMult(p, owk) * rampF;
      if (!(f > 0)) return;
      var cw = {};
      Object.keys(p.comps).forEach(function (ck) { if (p.comps[ck]) cw[ck] = p.comps[ck] / perGameDiv * f; });
      var fp = propImpliedFp(p, entry, sc, cw);
      if (fp == null) return;
      obs.push({ wk: owk, rate: fp / f });
    });
    if (!obs.length) return null;
    var maxWk = 0;
    obs.forEach(function (o) { if (o.wk > maxWk) maxWk = o.wk; });
    var wsum = 0, rsum = 0;
    obs.forEach(function (o) {
      var wt = Math.pow(0.5, (maxWk - o.wk) / MKT_HALF_LIFE);
      wsum += wt; rsum += wt * o.rate;
    });
    return { rate: rsum / wsum, conf: Math.min(1, wsum / MKT_FULL_TRUST), n: obs.length };
  }

  // ---------- in-season availability + vacated opportunity ----------
  // Moved into the engine 2026-09-09 (was export_site_proj.js only, which
  // left the Sim Lab week sim and the auto-lock projecting ruled-out
  // players — TreVeyon Henderson Out for the W1 opener still carried 9.4
  // while Stevenson's share never moved). Every surface now shares it.
  //   Out / Sus            -> 0 for the current week
  //   Doubtful             -> x0.5 for the current week
  //   IR / PUP / NFI       -> 0 for current week .. current+3
  //   IN_SEASON_OUT_OVERRIDES['Name'] = [from, to] wins; 0/null = healthy
  // Vacated opportunity: a zeroed/docked player's season per-game level is
  // partially redistributed within his team position group for those weeks
  // — QB 85% to the remaining QB(s); RB/WR/TE 60% spread in proportion to
  // the healthy players' own levels (cap x2). The factor scales mean, sd
  // and every stat comp together, and a docked player skips the prop
  // anchor (his designation is fresher than his lines). Call
  // applyInSeasonInjuries(players, currentWeek, {active}) after
  // buildPlayers; `active` = designations are for THIS week's games (from
  // ~4 days before the week's first kickoff) — preseason camp tags stay
  // with the start-of-season windows above. Kill: window.SIM_INJ_LAYER=false.
  // 2026-09-15 (Jack): Sleeper "Out" needs Sleeper's own weekly projection at 0 (SIM_SLEEPER_WEEKLY)
  // or the NFL report to zero; otherwise x0.75 'out-unconfirmed'.
  var _inj = null;
  var INJ_SHARE = { QB: 0.85, RB: 0.60, WR: 0.60, TE: 0.60 };
  // ---------- TEAM OPPORTUNITY POOL (2026-09-11, Jack: Clay-style) ----------
  // Replaces the flat "60% of his fantasy points to his position group, 1.6x
  // to the listed next man" rule for RB/WR/TE absences with a redistribution
  // of VACATED TARGETS AND CARRIES, calibrated on the site's weekly DB
  // 2019-25 (backtest_vacated_pool.py, 671 one-absence team-weeks):
  //   absent WR: team keeps 0.68 of his targets; healthy WR1 absorbs 3%,
  //              WR2 12%, WR3 15%, no-baseline bodies 46% — volume flows
  //              DOWN the depth chart, not to the top remaining receiver
  //   absent RB: team keeps 0.71 of his carries (next RB 28%, RB3 18%) and
  //              throws MORE (targets 1.33x: 0.25 to other RBs, 0.19 to WR/TE)
  //   absent TE: team keeps 0.71 of his targets; TE2 takes the bulk
  //   absorbers convert added targets at 0.83-0.95 of their own rate
  //   starting QB absent: team targets 1.05x, receivers' efficiency 0.98x
  //              -> no receiver dampener; the backup inherits 85% (below)
  // Stat units come from Clay comps: targets = rec / catch rate, carries =
  // rush yds / YPC. Weights by depth-chart rank among HEALTHY in-window
  // players of the position (unlisted fall in after the listed, by level).
  // Points gained = absorbed targets x the absorber's own PPR pts/target x
  // POOL_EFF_T + absorbed carries x his own pts/carry. Factor f = 1 +
  // gained / own per-game pts (scales mean, sd and comps together, as
  // before). Kill switch: window.SIM_POOL = false -> old INJ_SHARE rule.
  // Weights = fraction of the VACATED volume (not of a retained pool) that
  // each healthy same-position player absorbs by depth rank, straight from
  // the backtest's established-player rows; the untracked remainder (bodies
  // outside the Clay pool, incompletions, more runs) is left unprojected.
  // Split by whether the absent player was his team's LEAD target-getter
  // (backtest: WR lead out -> healthy WR1 +0.09, WR2 +0.15, WR3 +0.16, other
  // positions +0.08; secondary WR out -> WR1 +0.00, WR2 +0.11, WR3 +0.15;
  // TE lead out -> TE2 +0.25, WRs +0.36; secondary TE out -> TE1 nothing,
  // TE3 +0.22; RB out -> RB2 +0.28 car/+0.28 tgt, RB3 +0.16, WR/TE +0.15 tgt).
  // The 4th-WR slot stands in for the "no-baseline bodies" bucket (+0.37/+0.51).
  var POOL = {
    RB: { lead: { tgtSame: [0.28, 0.18], carSame: [0.28, 0.16, 0.10], tgtOther: 0.15 },
          sec:  { tgtSame: [0.28, 0.18], carSame: [0.28, 0.16, 0.10], tgtOther: 0.15 } },
    WR: { lead: { tgtSame: [0.09, 0.15, 0.16, 0.10], carSame: [], tgtOther: 0.08 },
          sec:  { tgtSame: [0.00, 0.11, 0.15, 0.10], carSame: [], tgtOther: 0.00 } },
    TE: { lead: { tgtSame: [0.25, 0.10], carSame: [], tgtOther: 0.36 },
          sec:  { tgtSame: [0.00, 0.22], carSame: [], tgtOther: 0.00 } }
  };
  var POOL_EFF_T = 0.92, POOL_EFF_C = 1.00;
  var POOL_LEVEL_FLOOR = 4.0; // PPR pts/g — denominator floor for the gained-points ratio
  var POOL_CR  = { RB: 0.77, WR: 0.63, TE: 0.68 };   // catch rate -> targets from Clay rec
  var POOL_YPC = { RB: 4.3, WR: 6.0, TE: 5.0 };      // carries from Clay rush yds
  function poolStats(p, div) {
    var c = p.comps || {};
    var tgt = (c.rec || 0) / (POOL_CR[p.pos] || 0.65) / div;
    var car = (c.ry || 0) / (POOL_YPC[p.pos] || 4.5) / div;
    var rpts = ((c.rec || 0) * 1 + (c.rcy || 0) * 0.1 + (c.rctd || 0) * 6) / div;
    var cpts = ((c.ry || 0) * 0.1 + (c.rtd || 0) * 6) / div;
    return { tgt: tgt, car: car, ppt: tgt > 0 ? rpts / tgt : 0, ppc: car > 0 ? cpts / car : 0 };
  }
  function applyInSeasonInjuries(players, currentWeek, opts) {
    opts = opts || {};
    var list = players.list || players;
    var wnd = typeof window !== 'undefined' ? window : {};
    _inj = { week: currentWeek, map: {}, adj: {}, zeros: [] };
    if (opts.active === false || wnd.SIM_INJ_LAYER === false || !(currentWeek >= 1)) return _inj;
    var ov = wnd.IN_SEASON_OUT_OVERRIDES || {};
    var map = _inj.map;
    // PRACTICE REPORT (data/sim_practice.js <- nfl.com/injuries, 2026-09-09):
    // latest practice participation + the NFL's own game status. Rules on
    // top of Sleeper's designation: NFL Out/Doubtful counts even if Sleeper
    // hasn't flipped yet; Questionable + DNP (didn't practice on the latest
    // report) -> x0.75 and no prop anchor (a real coin flip / decoy risk);
    // Questionable + Limited/Full -> plays, no change. Only the CURRENT
    // week's report (the page is week-scoped) — stale weeks are ignored.
    var prMap = {};
    var prRaw = wnd.SIM_PRACTICE_2026 || null;
    if (prRaw && prRaw.players && (!prRaw.week || +prRaw.week === +currentWeek)) {
      Object.keys(prRaw.players).forEach(function (nm) { prMap[norm(nm)] = prRaw.players[nm]; });
    }
    list.forEach(function (p) {
      if (p.isDST) return;
      var o = ov[p.name];
      if (o && o.length === 2) { map[p.norm] = { from: o[0], to: o[1], mult: 0, src: 'override' }; return; }
      if (o === null || o === 0) return;
      var t = String(p.injFlag || '').toLowerCase();
      var pr = prMap[p.norm] || null;
      var gs = pr ? String(pr.gs || '').toLowerCase() : '';
      var practiced = pr ? String(pr.pr || '') : '';
      if (t && t !== '|') {
        if (/\bir\b|injured reserve|\bpup\b|\bnfi\b|non football/.test(t)) { map[p.norm] = { from: currentWeek, to: Math.min(WEEKS, currentWeek + 3), mult: 0, src: 'ir' }; return; }
        if (/\bsus\b|suspend/.test(t)) { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0, src: 'sus' }; return; }
        if (/\bout\b/.test(t)) {
          // Jack 2026-09-15: never zero a player before he is actually out (or at least doubtful).
          // Sleeper's injury_status "Out" lingers from last week's inactives and gets applied
          // early after Monday news, so it only zeroes when Sleeper has ALSO pulled the player's
          // own projection for this week (SIM_SLEEPER_WEEKLY: absent / 0 = ruled out) or the NFL
          // report says Out/Doubtful below. Otherwise x0.75 'out-unconfirmed' (same handling
          // as Questionable + DNP: no prop anchor, chip on the card) until a report confirms.
          var swk = wnd.SIM_SLEEPER_WEEKLY || null;
          var swOK = swk && swk.p && (+swk.week === +currentWeek);
          var swProj = swOK ? swk.p[p.norm] : null;
          if (!swOK || swProj == null || swProj <= 0 || gs === 'out') { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0, src: 'out' }; return; }
          if (gs === 'doubtful') { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0.5, src: 'nfl-doubtful' }; return; }
          map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0.75, src: 'out-unconfirmed' }; return;
        }
        if (/doubtful/.test(t)) { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0.5, src: 'doubtful' }; return; }
      }
      // NFL report as a second opinion (Sleeper lagging the official status)
      if (gs === 'out') { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0, src: 'nfl-out' }; return; }
      if (gs === 'doubtful') { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0.5, src: 'nfl-doubtful' }; return; }
      var questionable = gs === 'questionable' || /questionable/.test(t);
      if (questionable && practiced === 'DNP') map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0.75, src: 'q-dnp' };
    });
    // DEPTH CHART WEIGHTS (data/sim_depth.js <- ESPN depth charts): the
    // vacated share flows to the healthy group in proportion to each
    // player's own level x his depth rank — the listed next man up gets the
    // bulk, deep reserves a sliver. Unlisted = deep reserve.
    var DEPTH_W = [1.6, 1.0, 0.5];
    var depthRank = {};
    var dRaw = wnd.SIM_DEPTH_2026 || null;
    if (dRaw && dRaw.teams) {
      Object.keys(dRaw.teams).forEach(function (tm) {
        var byPos = dRaw.teams[tm] || {};
        Object.keys(byPos).forEach(function (pos) {
          (byPos[pos] || []).forEach(function (nm, i) { var k = normTeam(tm) + '|' + pos + '|' + norm(nm); if (depthRank[k] == null) depthRank[k] = i; });
        });
      });
    }
    var depthW = function (p) {
      if (!dRaw || !dRaw.teams) return 1;
      var r = depthRank[p.tm + '|' + p.pos + '|' + p.norm];
      return r == null ? 0.25 : (DEPTH_W[r] != null ? DEPTH_W[r] : 0.25);
    };
    var depthRankOf = function (p) { var r = depthRank[p.tm + '|' + p.pos + '|' + p.norm]; return r == null ? 99 : r; };
    // WINDOW GATE (2026-09-09): a player whose start-of-season / QB-room
    // window (p.qbWindow — Penix ACL behind Tua, Charbonnet PUP, Pacheco,
    // Tyson) already excludes this week's game was never in the week's
    // projection, so his designation vacates NOTHING here — counting his
    // season per-game level again double-paid the next man up (Tua 15 -> 19).
    // Likewise only healthy players inside their window can absorb a share.
    // Windowed players use their per-start rate, as weeklyProjection does.
    var sched = players.schedule || null;
    var inWindow = function (p, wk) {
      if (!p.qbWindow) return true;
      if (!sched || !sched.gameWeeks) return true;
      var gi = (sched.gameWeeks[p.tm] || []).indexOf(wk) + 1;
      return gi > 0 && gi >= p.qbWindow.s && gi <= p.qbWindow.e;
    };
    var weeks = {};
    Object.keys(map).forEach(function (n) { for (var w = map[n].from; w <= map[n].to; w++) weeks[w] = 1; });
    Object.keys(weeks).forEach(function (wkS) {
      var wk = +wkS, lost = {}, healthyW = {}, nextQb = {};
      var multOf = function (p) { var m = map[p.norm]; return (m && wk >= m.from && wk <= m.to) ? m.mult : 1; };
      list.forEach(function (p) {
        if (p.isDST || !INJ_SHARE[p.pos]) return;
        if (!inWindow(p, wk)) return; // not projected this week — nothing to vacate or absorb
        var base = (p.ptsPPR || 0) / (p.qbWindow ? (p.qbWindow.games || 17) : (p.clayGames || 17));
        if (!(base > 0)) return;
        var g = p.tm + '|' + p.pos, mult = multOf(p);
        if (mult < 1) lost[g] = (lost[g] || 0) + base * (1 - mult);
        else {
          healthyW[g] = (healthyW[g] || 0) + base * depthW(p);
          // QB NEXT MAN UP (2026-09-11, Tua out -> Cooper Rush): one QB
          // starts, so the healthy in-window QB with the best depth rank
          // (tie: higher level) is the room's only absorber — tracked here.
          if (p.pos === 'QB') {
            var cur = nextQb[g];
            // level on weeklyProjection's own scale (season/17 without a
            // window) — `base` above divides by Clay's games, which for a
            // 2-game backup is 8x too generous.
            var wpBase = (p.ptsPPR || 0) / (p.qbWindow ? (p.qbWindow.games || 17) : 17);
            if (!cur || depthRankOf(p) < depthRankOf(cur) || (depthRankOf(p) === depthRankOf(cur) && wpBase > cur._injBase)) { p._injBase = wpBase; nextQb[g] = p; }
          }
        }
      });
      // ---- opportunity pool (RB/WR/TE): vacated targets/carries -> healthy absorbers ----
      var usePool = wnd.SIM_POOL !== false;
      var gainT = {}, gainC = {};
      if (usePool) {
        var vac = {};  // tm|pos of the ABSENT player -> { tgt, car, lead }
        var topTgt = {}; // tm -> highest per-game target estimate among in-window pass catchers
        list.forEach(function (p) {
          if (p.isDST || !POOL[p.pos] || !inWindow(p, wk)) return;
          var t = poolStats(p, p.qbWindow ? (p.qbWindow.games || 17) : (p.clayGames || 17)).tgt;
          if (!(topTgt[p.tm] >= t)) topTgt[p.tm] = t;
        });
        list.forEach(function (p) {
          if (p.isDST || !POOL[p.pos] || !inWindow(p, wk)) return;
          var mult = multOf(p);
          if (mult >= 1) return;
          var st = poolStats(p, p.qbWindow ? (p.qbWindow.games || 17) : (p.clayGames || 17));
          var g = p.tm + '|' + p.pos;
          var v = vac[g] = vac[g] || { tgt: 0, car: 0, lead: false };
          v.tgt += st.tgt * (1 - mult); v.car += st.car * (1 - mult);
          if (st.tgt >= (topTgt[p.tm] || 0) - 1e-9) v.lead = true;
        });
        Object.keys(vac).forEach(function (g) {
          var tm = g.split('|')[0], apos = g.split('|')[1], v = vac[g], rule = POOL[apos][v.lead ? 'lead' : 'sec'];
          var healthy = list.filter(function (q) { return !q.isDST && q.tm === tm && POOL[q.pos] && multOf(q) === 1 && inWindow(q, wk); });
          var same = healthy.filter(function (q) { return q.pos === apos; });
          var lvl = function (q) { return (q.ptsPPR || 0) / (q.qbWindow ? (q.qbWindow.games || 17) : (q.clayGames || 17)); };
          same.sort(function (a, b) { var ra = depthRankOf(a), rb = depthRankOf(b); return ra !== rb ? ra - rb : lvl(b) - lvl(a); });
          same.forEach(function (q, i) {
            var wt = rule.tgtSame[i], wc = rule.carSame[i];
            if (wt) gainT[q.norm] = (gainT[q.norm] || 0) + v.tgt * wt;
            if (wc) gainC[q.norm] = (gainC[q.norm] || 0) + v.car * wc;
          });
          if (rule.tgtOther > 0) {
            var others = healthy.filter(function (q) { return q.pos !== apos && q.pos !== 'RB'; });
            var tot = 0, st = {};
            others.forEach(function (q) { st[q.norm] = poolStats(q, q.qbWindow ? (q.qbWindow.games || 17) : (q.clayGames || 17)).tgt; tot += st[q.norm]; });
            if (tot > 0) others.forEach(function (q) { gainT[q.norm] = (gainT[q.norm] || 0) + v.tgt * rule.tgtOther * st[q.norm] / tot; });
          }
        });
      }
      list.forEach(function (p) {
        if (p.isDST) return;
        var g = p.tm + '|' + p.pos, mult = multOf(p), f = mult;
        if (usePool && mult === 1 && POOL[p.pos] && (gainT[p.norm] || gainC[p.norm]) && inWindow(p, wk)) {
          var div = p.qbWindow ? (p.qbWindow.games || 17) : (p.clayGames || 17);
          var own = (p.ptsPPR || 0) / div;
          var st2 = poolStats(p, div);
          var gained = (gainT[p.norm] || 0) * st2.ppt * POOL_EFF_T + (gainC[p.norm] || 0) * st2.ppc * POOL_EFF_C;
          // Ratio against a LEVEL FLOOR: a deep reserve's Clay level (1 pt/g)
          // understates his active-week role (his snap/route multipliers
          // already lift him), so an absolute 1.3-pt gain must not read as
          // x2.2 on top of that. Floor = POOL_LEVEL_FLOOR PPR/g.
          if (own > 0 && gained > 0) f = 1 + gained / Math.max(own, POOL_LEVEL_FLOOR);
        } else if (mult === 1 && INJ_SHARE[p.pos] && lost[g] && inWindow(p, wk)) {
          if (p.pos === 'QB') {
            // Winner-take-all and UNCAPPED: the next man up inherits 85% of
            // the starter's per-game level on top of his own. A 1-pt Clay
            // backup (Rush) under the x2 cap below projected at nothing.
            if (nextQb[g] === p) f = 1 + INJ_SHARE.QB * lost[g] / p._injBase;
          } else if (!usePool && healthyW[g] > 0) {
            // LEGACY (SIM_POOL=false): share x lost x (my depth weight /
            // group's weighted level) — the group absorbs exactly `share`.
            f = Math.min(2.0, 1 + INJ_SHARE[p.pos] * lost[g] * depthW(p) / healthyW[g]);
          }
        }
        if (f !== 1) (_inj.adj[p.norm] = _inj.adj[p.norm] || {})[wk] = f;
      });
    });
    list.forEach(function (p) { var m = map[p.norm]; if (m) _inj.zeros.push({ name: p.name, tm: p.tm, pos: p.pos, from: m.from, to: m.to, mult: m.mult, src: m.src }); });
    return _inj;
  }
  function injAdj(p, wk) {
    if (!_inj) return 1;
    var a = _inj.adj[p.norm];
    return a && a[wk] != null ? a[wk] : 1;
  }
  function injuryState() { return _inj; }

  // ---- SHADOW FLAGS (2026-09-15, Jack: "young and ascending, only good reports ... increasing
  // snaps, targets, routes"). INTEL ONLY until the Tuesday scorecard shows the flagged rows
  // beat their projection: backtest_fprr.py graded the analytic ascending flag at +9% actual
  // over projection on 474 rows but a flat LOYO multiplier (noise), and beat reports have no
  // history to grade, so both are logged on every locked row (rep / asc) and shown as chips.
  var NEWS_DAYS = 10;
  function newsFlags(p, days) {
    // {riser, faller, injury, role, last} from SIM_NEWS_2026 items for this player in the last N days
    var N = typeof window !== 'undefined' ? window.SIM_NEWS_2026 : null;
    if (!N || !N.items || !N.items.length) return null;
    var cut = Date.now() - (days || NEWS_DAYS) * 86400000, nk = p.norm, out = { riser: 0, faller: 0, injury: 0, role: 0, last: null };
    for (var i = 0; i < N.items.length; i++) {
      var it = N.items[i]; if (!it || !it.player || norm(it.player) !== nk) continue;
      var t = Date.parse(it.date || ''); if (!(t >= cut)) continue;
      if (it.tag === 'riser') out.riser++; else if (it.tag === 'faller') out.faller++; else if (it.tag === 'injury') out.injury++; else if (it.tag === 'role') out.role++;
      if (!out.last || it.date > out.last.date) out.last = { date: it.date, tag: it.tag, headline: it.headline };
    }
    return (out.riser || out.faller || out.injury || out.role) ? out : null;
  }
  function ascendingFlag(p, wk) {
    // analytic "ascending": 25 or younger, 3 seasons or fewer, snap trend AND route trend up
    if (p.isDST || ['WR', 'TE', 'RB'].indexOf(p.pos) < 0) return false;
    if (!(p.age != null && p.age <= 25) || !(p.exp != null && p.exp <= 3)) return false;
    return snapMult(p, wk) >= 1.05 && routeMult(p, wk) >= 1.03;
  }

  // Weekly mean + per-stat component means for player p in week wk.
  // Returns null on bye / no game.
  function weeklyProjection(p, wk, sc, schedule) {
    var slot = schedule.byTeam[p.tm] && schedule.byTeam[p.tm][wk];
    if (!slot) return null;
    // game number for this team (byes don't count) — drives windows + ramps
    var weeksList = schedule.gameWeeks[p.tm] || [];
    var gameIdx = weeksList.indexOf(wk) + 1;
    if (p.qbWindow && (gameIdx < p.qbWindow.s || gameIdx > p.qbWindow.e)) return null; // not the starter yet / anymore
    var mult, mean;
    if (p.isDST) {
      mult = 1;
      mean = dstWeeklyMean(slot.oppImplied);
      return { mean: mean, mult: mult, slot: slot, comps: {} };
    }
    mult = vegasMult(slot.implied, schedule.avgImplied, p.pos);
    var perGameDiv = p.qbWindow ? p.qbWindow.games : 17;
    var dAdj = (defenseAdj()[slot.opp] || {})[p.pos] || 1;
    var cbM = cbShadowMult(slot.opp, p.pos, p) * cb1OutBoost(slot.opp, p.pos, p)
      * olOutDock(p.tm, p.pos) * pressureMult(slot.opp, p.pos)
      * weatherMult(p, wk, slot);
    var sM = snapMult(p, wk) * routeMult(p, wk);
    var rampF = 1;
    if (p.ramp) {
      var R = RAMP[p.ramp];
      rampF = (gameIdx > 0 && gameIdx <= R.head.length) ? R.head[gameIdx - 1] : R.tail;
    }
    var iA = injAdj(p, wk); // in-season availability / vacated-opportunity factor
    var factor = mult * dAdj * cbM * sM * rampF * iA;
    var clayPg = seasonPoints(p, sc) / perGameDiv;
    mean = clayPg * factor;
    // JS Weekly (in-season model): Clay prior shrunk toward 2026 actuals,
    // actual FPA-by-position opponent adj replacing Clay unit grades as the
    // sample grows. Preseason (no 2026 data) both terms collapse to Clay's,
    // so jsMean === mean until real games exist.
    var jsPg = jsBasePg(p, sc, clayPg);
    var jsChain = mult * jsOppMult(slot.opp, p.pos, dAdj) * cbM * sM * rampF * iA;
    // TD-luck mean reversion (RB/WR/TE/QB), additive after the chain. Scaled by
    // AVAILABILITY only: iA also carries the vacated-opportunity boost for
    // backups (>1, Cooper Rush x210 on a near-zero base) which must not
    // multiply a points term - min(1, iA) keeps Out/Doubtful docks and drops the boost.
    var luckAdj = tdLuckAdj(p, sc) * Math.min(1, iA);
    var jsMean = Math.max(0, jsPg * jsChain + luckAdj);
    var compsWk = {};
    Object.keys(p.comps).forEach(function (k) {
      if (p.comps[k]) compsWk[k] = +(p.comps[k] / perGameDiv * factor).toFixed(2);
    });
    compsWk.rrtd = +(((p.comps.rtd || 0) + (p.comps.rctd || 0)) / perGameDiv * factor).toFixed(3);
    // Prop anchor (see PROP_ANCHOR_SPEC.md): blend toward the books' weekly
    // lines where they exist. Base = what effMean would pick without it.
    // A ZEROED player (iA 0) skips the market: the designation is fresher
    // than lines the books may not have pulled yet.
    // DOCKED (0 < iA < 1: Doubtful x0.5, Questionable+DNP x0.75) — 2026-09-11
    // (Jack): the books referee the conditional-on-playing rate too. Undo
    // the dock, anchor that rate to lines no older than
    // PROP_DOCKED_MAX_AGE_DAYS (posted since the designation could exist),
    // then re-apply the availability multiplier. McMillan W1: model 3.3 vs
    // books-implied 8.2 x 0.5 -> ~4.0.
    var propMean = null;
    var baseM = jsMean != null ? jsMean : mean;
    if (iA >= 1) propMean = propAnchorMean(p, wk, sc, compsWk, baseM);
    else if (iA > 0) {
      var compsPlay = {};
      Object.keys(compsWk).forEach(function (k) { compsPlay[k] = compsWk[k] / iA; });
      var anchoredPlay = propAnchorMean(p, wk, sc, compsPlay, baseM / iA, PROP_DOCKED_MAX_AGE_DAYS);
      if (anchoredPlay != null) propMean = anchoredPlay * iA;
    }
    var propSrc = propMean != null ? 'line' : null;
    var propWUsed = propMean != null ? p._propWUsed : null;
    if (propMean == null && iA > 0) {
      // Phase 4: no lines for THIS week — fall back to the market's standing
      // per-game rate from other observed weeks, re-multiplied through this
      // week's own JS chain (Vegas/FPA/snaps/ramp/availability), confidence-weighted.
      // (jsChain carries iA, so a docked player's rate is docked here too.)
      var mkt = marketRate(p, wk, sc, schedule);
      if (mkt) {
        var mw = propWeight(p) * mkt.conf;
        if (mw > 0) {
          propMean = Math.max(0, (mw * mkt.rate + (1 - mw) * jsPg) * jsChain + (1 - mw) * luckAdj);
          propSrc = 'rate';
        }
      }
    }
    return { mean: mean, mult: mult, slot: slot, comps: compsWk, gameIdx: gameIdx, jsMean: jsMean, propMean: propMean, propSrc: propSrc, propW: propWUsed, luckAdj: luckAdj };
  }

  // ---------- correlated sampling ----------
  // One draw of the week's common factors: per-team passing environment V
  // (correlated across each game), per-receiver draws g + the QB hub
  // (share-weighted sum of his receivers' g), antisymmetric rush script.
  // v/hub/rush are indexed by team slot, g by receiver slot (see buildIndex).
  function drawWeekEnv(gamesThisWeek, rng, players) {
    var ix = ensureIndex(players || {});
    var nT = ix.teams.length;
    var v = new Float64Array(nT), hub = new Float64Array(nT), rush = new Float64Array(nT);
    var g = new Float64Array(ix.nRec);
    var a = Math.sqrt(CORR.gV), b = Math.sqrt(1 - CORR.gV);
    var gl = gamesThisWeek || [], live = [], seen = new Uint8Array(nT);
    for (var i = 0; i < gl.length; i++) {
      var ai = ix.tIdx[gl[i].away], hi = ix.tIdx[gl[i].home];
      if (ai === undefined || hi === undefined) continue;
      var zGame = rng.normal();
      v[ai] = a * zGame + b * rng.normal();
      v[hi] = a * zGame + b * rng.normal();
      var zR = rng.normal();
      rush[hi] = zR;
      rush[ai] = -zR;
      if (!seen[ai]) { seen[ai] = 1; live.push(ai); }
      if (!seen[hi]) { seen[hi] = 1; live.push(hi); }
    }
    for (var j = 0; j < live.length; j++) {
      var ti = live[j], rs = ix.recByTi[ti];
      if (!rs) continue;
      var h = 0;
      for (var r = 0; r < rs.length; r++) {
        var z = rng.normal();
        g[rs[r].i] = z;
        h += rs[r].w * z;
      }
      hub[ti] = h;
    }
    return { v: v, hub: hub, g: g, rush: rush, ti: ix.tIdx };
  }

  // Fills and returns the shared _LD scratch {L, f2} — the common-factor draw
  // and its variance share. Reused rather than freshly allocated because this
  // runs once per sampled player-week (millions per season sim).
  var _LD = { L: 0, f2: 0 };
  function playerLoading(p, wkProj, env, rng) {
    if (p.isDST) {
      var oi = env.ti[wkProj.slot.opp];
      var vo = oi === undefined ? 0 : env.v[oi];
      _LD.L = CORR.fDST_oppV * vo;
      _LD.f2 = CORR.fDST_oppV * CORR.fDST_oppV;
      return _LD;
    }
    var ti = p._ti, L = 0, f2 = 0;
    var fv = p._fv;
    L += fv * (ti >= 0 ? env.v[ti] : 0);
    f2 += fv * fv;
    if (p.pos === 'QB') {
      L += CORR.fH_QB * (ti >= 0 ? env.hub[ti] : 0);
      f2 += CORR.fH_QB * CORR.fH_QB;
    } else if (p._fg) {
      var gz = p._gi >= 0 ? env.g[p._gi] : rng.normal(); // outside the hub pool
      L += p._fg * gz;
      f2 += p._fg * p._fg;
    }
    if (p.pos === 'RB') {
      L += CORR.fR_RB * (ti >= 0 ? env.rush[ti] : 0);
      f2 += CORR.fR_RB * CORR.fR_RB;
    }
    _LD.L = L; _LD.f2 = f2;
    return _LD;
  }

  // meanScale (optional): scales the player's whole level for this draw —
  // used by the season sim's shock/injury layers. Mean AND sd scale together.
  // Total per-player weekly variance is the SAME as the pre-QB-hub engine
  // ((0.9 sigma)^2 + 0.04); the loadings only re-apportion it between common
  // factors and idiosyncratic residual, so marginal calibration is untouched.
  //
  // IN-SEASON the sampler centers on the JS Weekly blend (Clay prior shrunk
  // toward actual 2026 PPG, prior strength 5, + live FPA opponent adj) — the
  // P5 blend beat pure Clay at EVERY mid-season checkpoint in the 2019-25
  // backtests (backtest_midseason.py, backtest_blend_weekly.py). Preseason
  // jsMean === mean identically, so this is a provable no-op until real
  // games exist. Kill switch for A/B: window.SIM_USE_JS_MEAN = false.
  function effMean(wkProj) {
    var w = typeof window !== 'undefined' ? window : null;
    // Prop anchor first (default ON, kill switch window.SIM_PROP_ANCHOR =
    // false) — null propMean (no lines / gate / K / DST) falls through.
    if ((!w || w.SIM_PROP_ANCHOR !== false) && wkProj.propMean != null) return wkProj.propMean;
    var useJs = !w || w.SIM_USE_JS_MEAN !== false;
    return (useJs && wkProj.jsMean != null) ? wkProj.jsMean : wkProj.mean;
  }
  function samplePlayerScore(p, wkProj, env, rng, meanScale) {
    if (!wkProj || wkProj.mean <= 0.05) return 0;
    var base = effMean(wkProj) * (meanScale || 1);
    var totalRel = p._relW !== undefined ? p._relW
      : Math.sqrt(Math.pow(RESID_SHRINK * p.sigmaPct, 2) + 0.04);
    var ld = playerLoading(p, wkProj, env, rng);
    var m = base * Math.max(0.25, 1 + totalRel * ld.L);
    var sd = base * totalRel * Math.sqrt(Math.max(0.06, 1 - ld.f2));
    if (sd <= 0.01) return m;
    if (p.isDST) {
      // shifted gamma: real DST weeks go negative (pick-sixes against, -4
      // PA bucket); draw around m+DST_SHIFT and shift back down.
      var mS = m + DST_SHIFT;
      return rng.gamma((mS * mS) / (sd * sd), (sd * sd) / mS) - DST_SHIFT;
    }
    var k = (m * m) / (sd * sd), th = (sd * sd) / m;
    return rng.gamma(k, th);
  }

  // ---------- WEEK SIM ----------
  // Simulate every projectable player for one NFL week. Returns per-player dists.
  function simWeek(opts) {
    var wk = opts.week, sims = opts.sims || 100, sc = opts.scoring || PRESETS.half;
    var rng = makeRng(opts.seed != null ? opts.seed : null);
    var schedule = opts.schedule, players = opts.players;
    var pool = players.list.filter(function (p) {
      var wp = weeklyProjection(p, wk, sc, schedule);
      if (!wp) return false;
      p._wk = wp;
      return wp.mean > (p.isDST ? 0 : 0.4);
    });
    var res = pool.map(function () { return new Float64Array(sims); });
    var games = schedule.byWeek[wk] || [];
    for (var s = 0; s < sims; s++) {
      var env = drawWeekEnv(games, rng, players);
      for (var i = 0; i < pool.length; i++) {
        res[i][s] = samplePlayerScore(pool[i], pool[i]._wk, env, rng);
      }
    }
    return pool.map(function (p, i) {
      var arr = res[i].sort(); // typed array: numeric ascending, no comparator
      var mean = arr.reduce(function (t, v) { return t + v; }, 0) / arr.length;
      var bb = BOOM_BUST[p.pos] || { boom: 20, bust: 5 };
      // one pass for both tails instead of two filter() allocations
      var nBoom = 0, nBust = 0;
      for (var q = 0; q < arr.length; q++) {
        if (arr[q] >= bb.boom) nBoom++;
        if (arr[q] < bb.bust) nBust++;
      }
      return {
        player: p, week: wk, mean: mean,
        proj: p._wk.mean, jsProj: p._wk.jsMean, propProj: p._wk.propMean != null ? p._wk.propMean : null, propW: p._wk.propW != null ? p._wk.propW : null,
        luck: p._wk.luckAdj != null ? p._wk.luckAdj : 0,   // TD-luck points inside jsProj (live grading: luck_scorecard.py)
        propSrc: p._wk.propSrc || null,
        mult: p._wk.mult, slot: p._wk.slot, comps: p._wk.comps,
        p10: pct(arr, 0.10), p25: pct(arr, 0.25), p50: pct(arr, 0.50),
        p75: pct(arr, 0.75), p90: pct(arr, 0.90),
        boomAt: bb.boom, bustAt: bb.bust,
        boom: nBoom / arr.length,
        bust: nBust / arr.length
      };
    });
  }
  function pct(sorted, q) {
    if (!sorted.length) return 0;
    var idx = Math.min(sorted.length - 1, Math.max(0, Math.round(q * (sorted.length - 1))));
    return sorted[idx];
  }

  // ---------- SEASON SIM ----------
  // Simulate every player's FULL season, week by week, with the same
  // correlated game environments as the week sim — but shared across all 18
  // weeks of a single simulated season, so a player's boom weeks line up with
  // his team's shootouts. Everything the weekly model knows (byes, Vegas
  // implied totals, defense adj, QB/injury windows, rookie ramps, snap trend)
  // shapes each week; the sim adds the volatility on top. Returns per-player
  // season-total distributions + positional finish odds (rank vs everyone
  // else IN THE SAME SIM, so the correlations carry into the finish odds).
  //
  // Two layers exist ONLY here (backtested on 2019-25 preseason Clay guides
  // vs actuals — backtest_sim_calibration.py):
  //  * SEASON SHOCK: one wrecked-season-mixture multiplier per player per
  //    simulated season (QB/RB/WR/TE, see drawSeasonShock), scaling every
  //    week's mean+sd together — the persistent role/health/breakout drift
  //    independent weekly draws can't produce. Without it only 31% of real
  //    season totals landed in our p10-p90; the mixture hits 82.5% with
  //    below-p10 at 10.3% (on target — the plain gamma left it at 18.7%).
  //  * GAMES-PLAYED DRAW: players Clay projects for <17 games (and who don't
  //    already carry an explicit start-of-season window) play each week with
  //    prob gm/17 at their TRUE per-game rate (mean x 17/gm) — season mean
  //    preserved, variance moved into the tails where it belongs.
  // Season shock = wrecked-season MIXTURE (backtest_sim_calibration.py,
  // 2019-25): with prob wreckP the season busts to U(wreckLo, wreckHi) of
  // projection (major injury / role collapse — the downside-fat tail a
  // right-skewed gamma can't produce); otherwise a mild gamma drift (cv tau)
  // scaled so E[shock] is exactly 1.
  // v3 upside trim: draws above 1 keep only a fraction u of their excess,
  // u PROJECTION-SCALED — elite projections have less relative headroom
  // (a 350-pt stud can't 1.6x; a bench flyer can). u = clamp(1.05 -
  // halfPts/400, 0.40, 1.0), then renormalized so E[shock] stays exactly 1.
  // v4 (2026-07-31) ELITE-BUCKET recalibration: the flat wreckP=.20 / tau=.30
  // were fit on the whole >=40-pt pool and hid a large elite error (top-6
  // projected 2019-25: real <50%-of-proj rate ~11% vs model 18%, real >1.5x
  // rate 1.2% vs model 11% — a p90 that beat CMC-2019's all-time season by
  // 26% was being sold as 1-in-10). Both knobs now scale with projection the
  // way the trim already did (sweep winner QP2TP: pooled cov 80.4 / below-p10
  // 10.6 / above-p90 8.9 — all best-yet; elite below/above 6.0/7.1, Brier12
  // .1144 unchanged). Milder wreck DEPTHS backtested worse (deep pool needs
  // the deep wrecks) — depth stays U(0.05, 0.50) for everyone.
  // E[shock]=1 exactly: gamma branch scaled by (1-0.275q)/(1-q); the trim
  // renorm divisor EPLUS = E[(shock-1)+] of the untrimmed mixture is now a
  // function of halfPts -> precomputed table (20M-draw MC per knot, linear
  // interp, constant beyond half=300; the old flat-shock constant was .19414).
  var SHOCK = { wreckLo: 0.05, wreckHi: 0.50 };
  var SHOCK_EPLUS_TABLE = [0.22299, 0.22053, 0.21690, 0.20863, 0.20030, 0.19190,
    0.18346, 0.17511, 0.16654, 0.15813, 0.14950, 0.14105, 0.13236, 0.12389,
    0.11522, 0.10994]; // halfPts = 0, 20, ..., 300
  function shockWreckP(halfPts) {
    return Math.min(0.26, Math.max(0.12, 0.28 - (halfPts || 0) / 1800));
  }
  function shockTau(halfPts) {
    return Math.min(0.30, Math.max(0.15, 0.30 - (halfPts || 0) / 2000));
  }
  function shockEplus(halfPts) {
    var h = Math.max(0, Math.min(300, halfPts || 0)) / 20;
    var i = Math.floor(h), f = h - i;
    return i >= 15 ? SHOCK_EPLUS_TABLE[15]
                   : SHOCK_EPLUS_TABLE[i] * (1 - f) + SHOCK_EPLUS_TABLE[i + 1] * f;
  }
  function shockTrimU(halfPts) {
    return Math.min(1, Math.max(0.40, 1.05 - (halfPts || 0) / 400));
  }
  function drawSeasonShock(rng, halfPts) {
    var g, q = shockWreckP(halfPts);
    if (rng.rand() < q) {
      g = SHOCK.wreckLo + (SHOCK.wreckHi - SHOCK.wreckLo) * rng.rand();
    } else {
      var tau = shockTau(halfPts);
      g = rng.gamma(1 / (tau * tau), tau * tau) * (1 - 0.275 * q) / (1 - q);
    }
    var u = shockTrimU(halfPts);
    if (u < 1) {
      if (g > 1) g = 1 + (g - 1) * u;
      g /= 1 - (1 - u) * shockEplus(halfPts);
    }
    return g;
  }
  function halfPtsOf(p) {
    if (p._half == null) p._half = Math.max(0, p.ptsPPR - 0.5 * ((p.comps && p.comps.rec) || 0));
    return p._half;
  }

  function simSeason(opts) {
    var sims = opts.sims || 300, sc = opts.scoring || PRESETS.half;
    var rng = makeRng(opts.seed != null ? opts.seed : null);
    var schedule = opts.schedule, players = opts.players;
    // any week range works: full season (1-18), a playoff stretch (15-17), one month…
    var wFrom = Math.max(1, Math.min(WEEKS, opts.weekFrom || 1));
    var wTo = Math.max(wFrom, Math.min(WEEKS, opts.weekTo || WEEKS));

    // Precompute each player's playable weeks (null = bye / outside window).
    var pool = [];
    players.list.forEach(function (p) {
      var wks = [];
      for (var w = wFrom; w <= wTo; w++) {
        var wp = weeklyProjection(p, w, sc, schedule);
        if (wp && wp.mean > 0.05) wks.push({ wk: w, wi: w - wFrom, wp: wp });
      }
      if (!wks.length) return;
      var seasonMean = wks.reduce(function (t, x) { return t + x.wp.mean; }, 0);
      if (!p.isDST && seasonMean < 0.3 * wks.length) return; // camp bodies — noise only
      // games-played layer: Clay gm<17 without an explicit window = spread
      // risk -> Bernoulli weeks at the true per-game rate (17/gm inflation)
      var gm = Math.min(17, Math.max(2, p.clayGames || 17));
      var useInj = !p.qbWindow && !p.isDST && gm < 17;
      pool.push({
        p: p, wks: wks, seasonMean: seasonMean,
        shocked: !p.isDST && p.pos !== 'K',
        inf: useInj ? 17 / gm : 1, pPlay: useInj ? gm / 17 : 1,
        totals: new Float64Array(sims), rankSum: 0, rankCounts: {}
      });
    });

    var byPos = {};
    pool.forEach(function (e, i) { (byPos[e.p.pos] = byPos[e.p.pos] || []).push(i); });
    // one scratch array per position, sorted IN PLACE every sim — the
    // membership never changes, only the order, so re-slicing each sim was
    // pure allocation (and leaving them near-sorted speeds the next sort up)
    var posGroups = Object.keys(byPos).map(function (pos) { return byPos[pos]; });
    var nWks = wTo - wFrom + 1, envByWeek = new Array(nWks), sNow = 0;
    function cmpTotals(a, b) { return pool[b].totals[sNow] - pool[a].totals[sNow]; }

    for (var s = 0; s < sims; s++) {
      // one env draw per NFL game of this simulated season, shared league-wide
      for (var w2 = wFrom; w2 <= wTo; w2++) envByWeek[w2 - wFrom] = drawWeekEnv(schedule.byWeek[w2] || [], rng, players);
      for (var i = 0; i < pool.length; i++) {
        var e = pool[i], tot = 0, wks = e.wks;
        var scale = (e.shocked ? drawSeasonShock(rng, halfPtsOf(e.p)) : 1) * e.inf;
        for (var j = 0; j < wks.length; j++) {
          if (e.pPlay < 1 && rng.rand() >= e.pPlay) continue; // missed game
          tot += samplePlayerScore(e.p, wks[j].wp, envByWeek[wks[j].wi], rng, scale);
        }
        e.totals[s] = tot;
      }
      // positional finish THIS season
      sNow = s;
      for (var gi = 0; gi < posGroups.length; gi++) {
        var idxs = posGroups[gi];
        idxs.sort(cmpTotals);
        for (var r = 0; r < idxs.length; r++) {
          var e2 = pool[idxs[r]];
          e2.rankSum += r + 1;
          e2.rankCounts[r + 1] = (e2.rankCounts[r + 1] || 0) + 1;
        }
      }
    }

    return pool.map(function (e) {
      // typed-array sort is numeric-ascending by default — no comparator
      // callback and no Float64Array -> Array copy
      var arr = e.totals.slice().sort();
      var mean = arr.reduce(function (t, v) { return t + v; }, 0) / sims;
      function topN(n) {
        var c = 0;
        for (var r = 1; r <= n; r++) c += e.rankCounts[r] || 0;
        return c / sims;
      }
      // Median-relative season tails (site export): boom = >=125% of own
      // median season, bust = <=75% (seasons are tighter than single weeks,
      // so the band is +/-25% where the weekly one is +/-50%). Additive
      // fields — the Sim Lab UI ignores them.
      var _med = pct(arr, 0.50), _nB = 0, _nD = 0;
      if (_med > 0) {
        for (var q = 0; q < sims; q++) {
          if (arr[q] >= _med * 1.25) _nB++;
          if (arr[q] <= _med * 0.75) _nD++;
        }
      }
      return {
        player: e.p, games: e.wks.length, seasonProj: e.seasonMean, clayPts: seasonPoints(e.p, sc),
        seasonBoom: _med > 0 ? _nB / sims : null, seasonBust: _med > 0 ? _nD / sims : null,
        mean: mean, p10: pct(arr, 0.10), p25: pct(arr, 0.25), p50: pct(arr, 0.50),
        p75: pct(arr, 0.75), p90: pct(arr, 0.90),
        avgRank: e.rankSum / sims, rankCounts: e.rankCounts,
        top1: topN(1), top3: topN(3), top12: topN(12), top24: topN(24),
        weeks: e.wks, sims: sims
      };
    }).sort(function (a, b) { return b.mean - a.mean; });
  }

  // ---------- LEAGUE SIM ----------
  // teams: [{rosterId, name, playerIds:[sid], record:{w,l,pf} (optional actuals)}]
  // schedulePairs: {week: [{a: rosterId, b: rosterId}]}
  // Each simulated season draws a per-player SEASON SHOCK (same wrecked-season
  // mixture as simSeason via drawSeasonShock, QB/RB/WR/TE) that persists
  // across every remaining week and the playoffs of that sim —
  // backtest_midseason.py showed rest-of-season outcomes need the full shock
  // at ANY point in the season; without it playoff/title odds run hot.
  // Lineups are still picked by projected mean — managers can't see shocks.
  function simLeague(opts) {
    var sims = opts.sims || 100, sc = opts.scoring, rng = makeRng(opts.seed != null ? opts.seed : null);
    var schedule = opts.schedule, players = opts.players;
    var teams = opts.teams, pairsByWeek = opts.pairsByWeek;
    var regWeeks = opts.regWeeks;           // array of week numbers left to sim
    var playoffTeams = opts.playoffTeams || 6;
    var playoffStart = opts.playoffStart || 15;
    var lineupSlots = opts.lineupSlots;     // e.g. ['QB','RB','RB','WR','WR','TE','FLEX','K','DEF']
    // unavailable: {sid: 'out'|'ir'} — 'out' = ruled out for the CURRENT week
    // only; 'ir' = gone for every remaining week (re-pulled on each league load,
    // so activations come back automatically). No Questionable/Doubtful guessing.
    var unavailable = opts.unavailable || {};
    var currentWeek = opts.currentWeek || (regWeeks.length ? regWeeks[0] : 1);

    // Precompute each team's optimal starters + weekly projections per week.
    // Starters chosen by projected mean (that's how real managers set lineups).
    var allWeeks = regWeeks.slice();
    for (var w = playoffStart; w < playoffStart + 3; w++) allWeeks.push(w);
    var candsBy = {}; // candsBy[rosterId][week] = sorted candidate list
    teams.forEach(function (t) {
      candsBy[t.rosterId] = {};
      var roster = t.playerIds.map(function (sid) { return players.bySid[sid]; }).filter(Boolean)
        .filter(function (p) { return unavailable[p.sid] !== 'ir'; });
      allWeeks.forEach(function (wk) {
        candsBy[t.rosterId][wk] = roster.filter(function (p) {
          return !(wk === currentWeek && unavailable[p.sid] === 'out');
        }).map(function (p) {
          var wp = weeklyProjection(p, wk, sc, schedule);
          return wp ? { p: p, wp: wp } : null;
        }).filter(Boolean).sort(function (a, b) { return effMean(b.wp) - effMean(a.wp); });
      });
    });

    // ---- D/ST streaming (league-size aware) ----
    // Real managers churn D/ST weekly, and the model already says DST value is
    // pure matchup (dstWeeklyMean = f(opp implied)) — so a roster locked to one
    // DST would eat bad matchups and a bye week that nobody actually eats.
    // Each week: teams whose rostered DST projects STREAM_TOL points below the
    // best D/ST still on waivers (or whose DST is on bye) claim a DISTINCT
    // waiver DST — worst rostered unit claims first, mirroring waiver priority —
    // while close calls keep the rostered unit. The pool is the truly
    // unrostered DSTs, so a deeper league (or 2-DST rosters) gets a thinner
    // streaming baseline automatically. Claimed DSTs are real player objects,
    // so sampling, sigma and game correlations all price normally.
    // "significantly worse" threshold, in projected pts. Backtested
    // (backtest_stream_tol.py, 2019-25 closing lines + pbp DST actuals):
    // projected gap → realized points at slope ~1.07 (the edge is real at
    // every size), and the season policy sweep is FLAT from TOL 1.5 down to
    // 0 (±0.3 ppg noise) — 1.0 sits within 2.3 season pts of the noisy
    // optimum while modeling that managers don't churn for slivers.
    var STREAM_TOL = 1.0;
    // A/B kill switch (mirrors SIM_USE_JS_MEAN): window.SIM_WAIVER_FILLS = false
    // reverts to fully roster-locked lineups (no DST streaming, no hole fills).
    var waiversOn = typeof window === 'undefined' || window.SIM_WAIVER_FILLS !== false;
    var rosteredIds = {};
    teams.forEach(function (t) { t.playerIds.forEach(function (id) { rosteredIds[id] = 1; }); });
    // waiver pool for a position in a week: unrostered, playing, not IR/out
    function waiverPool(list, wk) {
      return list.filter(function (p) {
        if (unavailable[p.sid] === 'ir') return false;
        if (wk === currentWeek && unavailable[p.sid] === 'out') return false;
        return true;
      }).map(function (p) {
        var wp = weeklyProjection(p, wk, sc, schedule);
        return wp ? { p: p, wp: wp } : null;
      }).filter(Boolean).sort(function (a, b) { return effMean(b.wp) - effMean(a.wp); });
    }
    var hasDefSlot = lineupSlots.some(function (s) { return (SLOT_ELIGIBLE[s] || []).indexOf('DST') >= 0; });
    if (waiversOn && hasDefSlot) {
      var waiverDsts = players.list.filter(function (p) { return p.isDST && !rosteredIds[p.sid]; });
      allWeeks.forEach(function (wk) {
        var pool = waiverPool(waiverDsts, wk);
        if (!pool.length) return;
        var order = teams.map(function (t) {
          var have = -1;
          candsBy[t.rosterId][wk].forEach(function (c) {
            if (c.p.isDST) have = Math.max(have, effMean(c.wp));
          });
          return { rid: t.rosterId, have: have }; // -1 = no DST playing (bye / none rostered)
        }).sort(function (a, b) { return a.have - b.have; });
        var next = 0;
        order.forEach(function (o) {
          if (next >= pool.length) return;
          var claim = pool[next];
          if (o.have < 0 || effMean(claim.wp) - o.have > STREAM_TOL) {
            var cands = candsBy[o.rid][wk];
            cands.push(claim);
            cands.sort(function (a, b) { return effMean(b.wp) - effMean(a.wp); });
            next++;
          }
        });
      });
    }

    // ---- lineup-hole fills (every slot) ----
    // The objective: NO simulated team ever fields an incomplete lineup.
    // A slot the roster literally cannot fill this week (byes, IR/Out
    // exclusions, thin rosters — QB with no backup, TE hole, empty FLEX)
    // gets the best eligible player still on waivers, because that's what a
    // real manager does rather than start an empty slot. No tolerance and no
    // upgrade streaming here — rostered players always keep their jobs; only
    // genuinely unfillable slots trigger a claim. Claims are distinct across
    // teams within a week (shared byes = waiver contention), and the pool is
    // this league's actual unrostered list, so replacement level scales with
    // league size and roster depth automatically.
    var waiverByPos = {}; // pos -> unrostered players (DST handled above too)
    players.list.forEach(function (p) {
      if (rosteredIds[p.sid]) return;
      (waiverByPos[p.pos] = waiverByPos[p.pos] || []).push(p);
    });
    function unfilledSlots(cands, slots) {
      var used = {}, un = [];
      var order = slots.map(function (s, i) { return { s: s, i: i }; })
        .sort(function (a, b) {
          var fa = a.s.indexOf('FLEX') >= 0 ? 1 : 0, fb = b.s.indexOf('FLEX') >= 0 ? 1 : 0;
          return fa - fb || a.i - b.i;
        });
      order.forEach(function (o) {
        var elig = SLOT_ELIGIBLE[o.s] || [];
        if (!elig.length) return; // IDP etc. — can never fill, don't count
        for (var i = 0; i < cands.length; i++) {
          if (used[i]) continue;
          if (elig.indexOf(cands[i].p.pos) >= 0) { used[i] = 1; return; }
        }
        un.push(o.s);
      });
      return un;
    }
    if (waiversOn) allWeeks.forEach(function (wk) {
      var pools = {};   // pos -> sorted waiver pool this week (lazy)
      var claimed = {}; // sid -> 1, distinct claims across teams this week
      teams.forEach(function (t) {
        var cands = candsBy[t.rosterId][wk];
        var holes = unfilledSlots(cands, lineupSlots);
        if (!holes.length) return;
        var changed = false;
        holes.forEach(function (slot) {
          var best = null;
          (SLOT_ELIGIBLE[slot] || []).forEach(function (pos) {
            if (!(pos in pools)) pools[pos] = waiverPool(waiverByPos[pos] || [], wk);
            for (var i = 0; i < pools[pos].length; i++) {
              var c = pools[pos][i];
              if (claimed[c.p.sid]) continue;
              if (!best || effMean(c.wp) > effMean(best.wp)) best = c;
              break; // pools are sorted — first unclaimed is that pos's best
            }
          });
          if (best) {
            claimed[best.p.sid] = 1;
            cands.push(best);
            changed = true;
          }
        });
        if (changed) cands.sort(function (a, b) { return effMean(b.wp) - effMean(a.wp); });
      });
    });

    var prep = {}; // prep[rosterId][week] = [{p, wp}]
    teams.forEach(function (t) {
      prep[t.rosterId] = {};
      allWeeks.forEach(function (wk) {
        prep[t.rosterId][wk] = pickLineup(candsBy[t.rosterId][wk], lineupSlots);
      });
    });

    // deterministic projected score per playoff week (sum of starter means)
    var playoffProj = {};
    teams.forEach(function (t) {
      playoffProj[t.rosterId] = {};
      for (var w2 = playoffStart; w2 < playoffStart + 3; w2++) {
        var lu = prep[t.rosterId][w2] || [];
        playoffProj[t.rosterId][w2] = lu.reduce(function (s2, slot) { return s2 + effMean(slot.wp); }, 0);
      }
    });

    var curShocks; // per-sim {playerKey: seasonShock}, persists reg season + playoffs
    function getShock(p) {
      if (p.isDST || p.pos === 'K') return 1;
      var k = p.sid || p.norm;
      if (!(k in curShocks)) curShocks[k] = drawSeasonShock(rng, halfPtsOf(p));
      return curShocks[k];
    }

    var tally = {};
    var weekTally = {}; // weekTally[rosterId][week] = {opp, w, pf, pa}
    teams.forEach(function (t) {
      tally[t.rosterId] = {
        team: t, wins: 0, pf: 0, playoffs: 0, byes: 0, titles: 0, finals: 0,
        pfLead: 0, pfs: new Float64Array(sims), // per-sim season PF -> O/U totals lines
        seedCounts: {}, winCounts: {}, placeCounts: {}
      };
      weekTally[t.rosterId] = {};
    });

    for (var s = 0; s < sims; s++) {
      curShocks = {};
      var rec = {};
      teams.forEach(function (t) {
        rec[t.rosterId] = { w: t.record ? t.record.w : 0, l: t.record ? t.record.l : 0, pf: t.record ? t.record.pf : 0 };
      });
      // regular season
      regWeeks.forEach(function (wk) {
        var env = drawWeekEnv(schedule.byWeek[wk] || [], rng, players);
        var scores = {};
        teams.forEach(function (t) { scores[t.rosterId] = teamScore(prep[t.rosterId][wk], env, rng); });
        (pairsByWeek[wk] || []).forEach(function (m) {
          var sa = scores[m.a], sb = scores[m.b];
          rec[m.a].pf += sa; rec[m.b].pf += sb;
          var wa = weekTally[m.a][wk] = weekTally[m.a][wk] || { opp: m.b, w: 0, pf: 0, pa: 0 };
          var wb = weekTally[m.b][wk] = weekTally[m.b][wk] || { opp: m.a, w: 0, pf: 0, pa: 0 };
          wa.pf += sa; wa.pa += sb; wb.pf += sb; wb.pa += sa;
          if (sa === sb) sa += rng.rand() < 0.5 ? 0.01 : -0.01;
          if (sa > sb) { rec[m.a].w++; rec[m.b].l++; wa.w++; } else { rec[m.b].w++; rec[m.a].l++; wb.w++; }
        });
      });
      // scoring title: who led the league in PF this sim (incl. carried actuals)
      var pfBest = null;
      teams.forEach(function (t) {
        if (pfBest === null || rec[t.rosterId].pf > rec[pfBest].pf) pfBest = t.rosterId;
      });
      tally[pfBest].pfLead++;
      // standings + seeds
      var order = teams.slice().sort(function (a, b) {
        var ra = rec[a.rosterId], rb = rec[b.rosterId];
        return (rb.w - ra.w) || (rb.pf - ra.pf);
      });
      order.forEach(function (t, i) {
        var tl = tally[t.rosterId];
        tl.wins += rec[t.rosterId].w;
        tl.pf += rec[t.rosterId].pf;
        tl.pfs[s] = rec[t.rosterId].pf;
        tl.winCounts[rec[t.rosterId].w] = (tl.winCounts[rec[t.rosterId].w] || 0) + 1;
        tl.placeCounts[i + 1] = (tl.placeCounts[i + 1] || 0) + 1;
        if (i < playoffTeams) {
          tl.playoffs++;
          tl.seedCounts[i + 1] = (tl.seedCounts[i + 1] || 0) + 1;
        }
      });
      // playoffs
      var seeds = order.slice(0, playoffTeams).map(function (t) { return t.rosterId; });
      var champ = simBracket(seeds, playoffStart, prep, schedule, rng, tally);
      tally[champ].titles++;
    }

    return teams.map(function (t) {
      var tl = tally[t.rosterId];
      var weekly = {};
      Object.keys(weekTally[t.rosterId]).forEach(function (wk) {
        var w = weekTally[t.rosterId][wk];
        weekly[wk] = { opp: w.opp, winPct: w.w / sims, avgPf: w.pf / sims, avgPa: w.pa / sims };
      });
      return {
        team: t,
        avgWins: tl.wins / sims, avgPF: tl.pf / sims,
        playoffOdds: tl.playoffs / sims, byeOdds: tl.byes / sims,
        titleOdds: tl.titles / sims, finalsOdds: tl.finals / sims,
        pfLeadOdds: tl.pfLead / sims, pfDist: tl.pfs,
        winCounts: tl.winCounts, placeCounts: tl.placeCounts, seedCounts: tl.seedCounts,
        weekly: weekly, playoffProj: playoffProj[t.rosterId], playoffOpps: tl.pOpp || {}, sims: sims
      };
    }).sort(function (a, b) { return b.titleOdds - a.titleOdds || b.avgWins - a.avgWins; });

    function teamScore(lineup, env, rng2) {
      var total = 0;
      (lineup || []).forEach(function (slot) { total += samplePlayerScore(slot.p, slot.wp, env, rng2, getShock(slot.p)); });
      return total;
    }

    function playWeekScore(rosterId, wk, env, rng2) {
      return teamScore(prep[rosterId][wk], env, rng2);
    }

    function simBracket(seeds, startWk, prepIgnored, schedule2, rng2, tally2) {
      var n = seeds.length;
      var wk = startWk;
      var alive, byes = [];
      if (n >= 6) { byes = seeds.slice(0, n - 4 > 2 ? 2 : n - 4); } // 6 -> top2 bye
      if (n === 6) {
        byes = [seeds[0], seeds[1]];
        byes.forEach(function (r) { tally2[r].byes++; });
        var w1 = duel(seeds[2], seeds[5], wk), w2 = duel(seeds[3], seeds[4], wk);
        wk++;
        var f1 = duel(seeds[0], w2, wk), f2 = duel(seeds[1], w1, wk);
        wk++;
        tally2[f1].finals++; tally2[f2].finals++;
        return duel(f1, f2, wk);
      }
      if (n === 4) {
        var a = duel(seeds[0], seeds[3], wk), b = duel(seeds[1], seeds[2], wk);
        wk++;
        tally2[a].finals++; tally2[b].finals++;
        return duel(a, b, wk);
      }
      if (n === 8) {
        var r1 = [duel(seeds[0], seeds[7], wk), duel(seeds[3], seeds[4], wk), duel(seeds[1], seeds[6], wk), duel(seeds[2], seeds[5], wk)];
        wk++;
        var s1 = duel(r1[0], r1[1], wk), s2 = duel(r1[2], r1[3], wk);
        wk++;
        tally2[s1].finals++; tally2[s2].finals++;
        return duel(s1, s2, wk);
      }
      // 2 teams or odd sizes: just duel down
      alive = seeds.slice();
      while (alive.length > 1) {
        var next = [];
        for (var i = 0; i < alive.length; i += 2) {
          if (i + 1 >= alive.length) { next.push(alive[i]); continue; }
          next.push(duel(alive[i], alive[i + 1], wk));
        }
        alive = next; wk++;
      }
      return alive[0];

      function duel(ra, rb, week) {
        // record the pairing so the UI can show playoff-opponent odds
        [[ra, rb], [rb, ra]].forEach(function (pair) {
          var t2 = tally2[pair[0]];
          t2.pOpp = t2.pOpp || {};
          var wkMap = t2.pOpp[week] = t2.pOpp[week] || {};
          wkMap[pair[1]] = (wkMap[pair[1]] || 0) + 1;
        });
        var env = drawWeekEnv(schedule2.byWeek[week] || [], rng2, players);
        var sa = playWeekScore(ra, week, env, rng2), sb = playWeekScore(rb, week, env, rng2);
        if (sa === sb) return rng2.rand() < 0.5 ? ra : rb;
        return sa > sb ? ra : rb;
      }
    }
  }

  // ---------- BEST BALL SIM (Underdog-style) ----------
  // squads: array of rosters (arrays of engine player refs) — the user's
  // imported teams AND any synthetic field teams, all in one list so a
  // player shared between squads is sampled ONCE per sim and scores
  // identically everywhere (portfolio + pod correlation is real).
  // teams: [{ key, squad: squadIdx, field: [squadIdx...]|null, advN }]
  // Lineup auto-picked per week: 1 QB / 2 RB / 3 WR / 1 TE / 1 FLEX.
  // Regular season = weeks 1..regTo (Underdog BBM: 14), playoff weeks
  // regTo+1..regTo+3 simmed separately per team. Same season layers as
  // simSeason: shared league-wide envs, wrecked-season shock mixture,
  // missed-game Bernoulli draws for Clay gm<17.
  function simBestBall(opts) {
    var sims = opts.sims || 300, sc = opts.scoring || PRESETS.half;
    var rng = makeRng(opts.seed != null ? opts.seed : null);
    var schedule = opts.schedule, players = opts.players;
    var regTo = Math.min(17, Math.max(4, opts.regTo || 14));
    var wTo = Math.min(17, regTo + 3);
    var squads = opts.squads, teams = opts.teams;
    var sqSf = opts.sqSf || []; // per-squad superflex-lineup flag
    // Mid-season continuation: weeks < fromWeek use ACTUAL points (banked,
    // identical in every sim) from actualsBySid[wk][sid]; only fromWeek..wTo
    // are sampled. unavailable[sid] = 'ir' zeroes every remaining week
    // (news the preseason Clay guide can't know), 'out' just this week.
    var fromWeek = Math.max(1, Math.min(wTo, opts.fromWeek || 1));
    var actuals = opts.actualsBySid || {};
    var unavailable = opts.unavailable || {};

    // one entry per unique player across every squad
    var entries = [], eIx = {};
    function entryOf(p) {
      var k = p.sid || p.norm;
      if (eIx[k] !== undefined) return eIx[k];
      var wps = new Array(wTo + 1), any = false;
      for (var w = 1; w <= wTo; w++) {
        var wp = weeklyProjection(p, w, sc, schedule);
        wps[w] = (wp && wp.mean > 0.05) ? wp : null;
        if (wps[w]) any = true;
      }
      var gm = Math.min(17, Math.max(2, p.clayGames || 17));
      var useInj = !p.qbWindow && !p.isDST && gm < 17;
      var act = null;
      if (fromWeek > 1) {
        act = new Float64Array(fromWeek - 1);
        for (var w0 = 1; w0 < fromWeek; w0++) {
          var wkMap = actuals[w0];
          act[w0 - 1] = (wkMap && p.sid != null && wkMap[p.sid] != null) ? wkMap[p.sid] : 0;
        }
      }
      eIx[k] = entries.length;
      entries.push({
        p: p, wps: any ? wps : null, act: act,
        unav: p.sid != null ? (unavailable[p.sid] || null) : null,
        shocked: !p.isDST && p.pos !== 'K',
        inf: useInj ? 17 / gm : 1, pPlay: useInj ? gm / 17 : 1
      });
      return eIx[k];
    }
    var sqEntries = squads.map(function (sq) { return sq.map(entryOf); });

    var nE = entries.length;
    var S = new Float64Array(nE * wTo); // sampled scores [e*wTo + wk-1]
    var envs = new Array(wTo);
    var sqReg = new Float64Array(squads.length);

    // Underdog lineup from this week's sampled scores: keep the top few at
    // each position (module scratch arrays, no allocation), then
    //   standard:  1QB + 2RB + 3WR + 1TE + FLEX(best leftover RB/WR/TE)
    //   superflex: the above + a SUPERFLEX slot (best leftover incl. QB2)
    var _qbT = [0, 0], _rbT = [0, 0, 0, 0], _wrT = [0, 0, 0, 0, 0], _teT = [0, 0, 0];
    function topInsert(arr, v) {
      for (var i = 0; i < arr.length; i++) {
        if (v > arr[i]) {
          for (var j = arr.length - 1; j > i; j--) arr[j] = arr[j - 1];
          arr[i] = v;
          return;
        }
      }
    }
    function bbWeekPoints(ixs, wk, sf) {
      _qbT[0] = _qbT[1] = 0;
      _rbT[0] = _rbT[1] = _rbT[2] = _rbT[3] = 0;
      _wrT[0] = _wrT[1] = _wrT[2] = _wrT[3] = _wrT[4] = 0;
      _teT[0] = _teT[1] = _teT[2] = 0;
      for (var i = 0; i < ixs.length; i++) {
        var e = ixs[i], v = S[e * wTo + wk - 1];
        if (v <= 0) continue;
        var pos = entries[e].p.pos;
        if (pos === 'QB') topInsert(_qbT, v);
        else if (pos === 'RB') topInsert(_rbT, v);
        else if (pos === 'WR') topInsert(_wrT, v);
        else if (pos === 'TE') topInsert(_teT, v);
      }
      var flex = Math.max(_rbT[2], Math.max(_wrT[3], _teT[1]));
      var total = _qbT[0] + _rbT[0] + _rbT[1] + _wrT[0] + _wrT[1] + _wrT[2] + _teT[0] + flex;
      if (sf) {
        var sfSlot;
        if (flex > 0 && flex === _rbT[2]) sfSlot = Math.max(_qbT[1], Math.max(_rbT[3], Math.max(_wrT[3], _teT[1])));
        else if (flex > 0 && flex === _wrT[3]) sfSlot = Math.max(_qbT[1], Math.max(_rbT[2], Math.max(_wrT[4], _teT[1])));
        else sfSlot = Math.max(_qbT[1], Math.max(_rbT[2], Math.max(_wrT[3], _teT[2])));
        total += sfSlot;
      }
      return total;
    }

    var poWeeks = [];
    for (var w0b = regTo + 1; w0b <= wTo; w0b++) poWeeks.push(w0b);
    var res = teams.map(function (t) {
      return {
        key: t.key, regTotals: new Float64Array(sims),
        adv: 0, win: 0, rankCounts: {}, fieldSum: 0, advF: new Uint8Array(sims),
        po: poWeeks.map(function () { return new Float64Array(sims); }),
        // Eliminator survivor chain (teams flagged elim, field required):
        // per-sim P(alive through wk k) chained probabilistically so 1-in-65k
        // tails resolve without 65k sims.
        elimCurve: t.elim ? new Float64Array(wTo) : null, elimFinal: 0, elimWin: 0,
        // pooled FIELD playoff-week scores (ladder-mode EV derives its advance
        // cutoffs from these at the tournament's structural selectivity — so a
        // superflex field's higher scoring raises its own cutoffs automatically)
        fieldPo: (t.collectFieldPo && t.field && t.field.length)
          ? poWeeks.map(function () { return new Float64Array(t.field.length * sims); }) : null
      };
    });

    // Eliminator: wk1 = top-6 of the 12-team pod by WEEK-1 score; wks 2..16 =
    // 50% head-to-head cut vs a random SURVIVOR; wk17 = 3-person final,
    // highest score wins. Weekly win odds are chained as FRACTIONS (not
    // Bernoulli draws) so the ~1/65,536 tail resolves at a few hundred sims.
    // Survivor-quality bias is handled with a mean-field pod model: every pod
    // member carries a survival WEIGHT (wk1 indicator, then x its own weekly
    // win fraction), and each week's win odds are computed against the
    // survival-WEIGHTED field — so late-week opponents are implicitly the
    // healthy/hot teams, not random pod members. In a symmetric pod this
    // reproduces the structural 0.5^15 chain exactly; naive unweighted
    // chaining inflated a strong team's finals odds ~70x.
    function elimSim(tm, r) {
      var field = tm.field, n = field.length;
      if (!n) return;
      var members = [tm.squad].concat(field), M = members.length;
      var sc2 = new Array(M), w = new Array(M), nw = new Array(M);
      for (var m0 = 0; m0 < M; m0++) sc2[m0] = bbWeekPoints(sqEntries[members[m0]], 1, sqSf[members[m0]]);
      for (var m1 = 0; m1 < M; m1++) {
        var beat = 0;
        for (var f1 = 0; f1 < M; f1++) if (sc2[f1] > sc2[m1]) beat++;
        w[m1] = beat < 6 ? 1 : 0; // top-6 of 12 advance wk1
      }
      r.elimCurve[0] += w[0];
      for (var wk = 2; wk <= Math.min(16, wTo); wk++) {
        if (w[0] <= 0) return;
        for (var m2 = 0; m2 < M; m2++) sc2[m2] = bbWeekPoints(sqEntries[members[m2]], wk, sqSf[members[m2]]);
        for (var m3 = 0; m3 < M; m3++) {
          if (w[m3] <= 0) { nw[m3] = 0; continue; }
          var num = 0, den = 0;
          for (var f2 = 0; f2 < M; f2++) {
            if (f2 === m3) continue;
            den += w[f2];
            if (sc2[f2] < sc2[m3]) num += w[f2];
            else if (sc2[f2] === sc2[m3]) num += 0.5 * w[f2];
          }
          nw[m3] = w[m3] * (den > 0 ? num / den : 0.5);
        }
        for (var m4 = 0; m4 < M; m4++) w[m4] = nw[m4];
        r.elimCurve[wk - 1] += w[0];
      }
      if (w[0] > 0 && wTo >= 17) {
        for (var m5 = 0; m5 < M; m5++) sc2[m5] = bbWeekPoints(sqEntries[members[m5]], 17, sqSf[members[m5]]);
        var num2 = 0, den2 = 0;
        for (var f3 = 1; f3 < M; f3++) {
          den2 += w[f3];
          if (sc2[f3] < sc2[0]) num2 += w[f3];
          else if (sc2[f3] === sc2[0]) num2 += 0.5 * w[f3];
        }
        var p1 = den2 > 0 ? num2 / den2 : 0.5;
        r.elimFinal += w[0];
        r.elimWin += w[0] * p1 * p1; // beat both other finalists
      }
    }

    for (var s = 0; s < sims; s++) {
      for (var w1 = fromWeek; w1 <= wTo; w1++) envs[w1 - 1] = drawWeekEnv(schedule.byWeek[w1] || [], rng, players);
      for (var e = 0; e < nE; e++) {
        var en = entries[e], base = e * wTo;
        // banked weeks: real points, identical every sim
        for (var wb = 1; wb < fromWeek; wb++) S[base + wb - 1] = en.act ? en.act[wb - 1] : 0;
        if (!en.wps || en.unav === 'ir') { for (var wz = fromWeek; wz <= wTo; wz++) S[base + wz - 1] = 0; continue; }
        var scale = (en.shocked ? drawSeasonShock(rng, halfPtsOf(en.p)) : 1) * en.inf;
        for (var w2 = fromWeek; w2 <= wTo; w2++) {
          var wp2 = en.wps[w2];
          S[base + w2 - 1] = (!wp2 || (en.unav === 'out' && w2 === fromWeek) || (en.pPlay < 1 && rng.rand() >= en.pPlay)) ? 0
            : samplePlayerScore(en.p, wp2, envs[w2 - 1], rng, scale);
        }
      }
      for (var q = 0; q < squads.length; q++) {
        var tot = 0;
        for (var w3 = 1; w3 <= regTo; w3++) tot += bbWeekPoints(sqEntries[q], w3, sqSf[q]);
        sqReg[q] = tot;
      }
      for (var t = 0; t < teams.length; t++) {
        var tm = teams[t], r = res[t];
        var mine = sqReg[tm.squad];
        r.regTotals[s] = mine;
        if (tm.field && tm.field.length) {
          var beat = 0;
          for (var f = 0; f < tm.field.length; f++) {
            var fv = sqReg[tm.field[f]];
            r.fieldSum += fv;
            if (fv > mine) beat++;
          }
          var rank = beat + 1;
          r.rankCounts[rank] = (r.rankCounts[rank] || 0) + 1;
          if (rank <= (tm.advN || 2)) { r.adv++; r.advF[s] = 1; }
          if (rank === 1) r.win++;
        }
        for (var pw = 0; pw < poWeeks.length; pw++) {
          r.po[pw][s] = bbWeekPoints(sqEntries[tm.squad], poWeeks[pw], sqSf[tm.squad]);
          if (r.fieldPo) {
            var nFf = tm.field.length;
            for (var ff = 0; ff < nFf; ff++) {
              r.fieldPo[pw][s * nFf + ff] = bbWeekPoints(sqEntries[tm.field[ff]], poWeeks[pw], sqSf[tm.field[ff]]);
            }
          }
        }
        if (tm.elim && tm.field && tm.field.length) elimSim(tm, r);
      }
    }

    return res.map(function (r, t) {
      var arr = r.regTotals.slice().sort();
      var mean = arr.reduce(function (a, v) { return a + v; }, 0) / sims;
      var nF = (teams[t].field || []).length;
      return {
        key: r.key, sims: sims, regTo: regTo, fromWeek: fromWeek,
        mean: mean, p10: pct(arr, 0.10), p25: pct(arr, 0.25), p50: pct(arr, 0.50),
        p75: pct(arr, 0.75), p90: pct(arr, 0.90),
        adv: nF ? r.adv / sims : null, win: nF ? r.win / sims : null,
        rankCounts: r.rankCounts, podSize: nF ? nF + 1 : null,
        fieldAvg: nF ? r.fieldSum / (sims * nF) : null,
        advFlags: nF ? r.advF : null, poRaw: r.po,
        fieldPo: r.fieldPo,
        elim: (r.elimCurve && nF) ? {
          curve: Array.prototype.slice.call(r.elimCurve, 0, 16).map(function (v) { return v / sims; }),
          pFinal: r.elimFinal / sims, pWin: r.elimWin / sims
        } : null,
        po: poWeeks.map(function (w, i) {
          var a = r.po[i].slice().sort();
          var m = a.reduce(function (x, v) { return x + v; }, 0) / sims;
          return { wk: w, mean: m, p10: pct(a, 0.10), p50: pct(a, 0.50), p90: pct(a, 0.90) };
        })
      };
    });
  }

  // Fill lineup slots greedily from mean-sorted candidates.
  var SLOT_ELIGIBLE = {
    QB: ['QB'], RB: ['RB'], WR: ['WR'], TE: ['TE'], K: ['K'], DEF: ['DST'], DST: ['DST'],
    FLEX: ['RB', 'WR', 'TE'], WRRB_FLEX: ['RB', 'WR'], REC_FLEX: ['WR', 'TE'],
    SUPER_FLEX: ['QB', 'RB', 'WR', 'TE'], IDP_FLEX: []
  };
  function pickLineup(cands, slots) {
    var used = {}, lineup = [];
    // strict slots first, flexes last so studs land in strict spots
    var order = slots.map(function (s, i) { return { s: s, i: i }; })
      .sort(function (a, b) {
        var fa = a.s.indexOf('FLEX') >= 0 ? 1 : 0, fb = b.s.indexOf('FLEX') >= 0 ? 1 : 0;
        return fa - fb || a.i - b.i;
      });
    order.forEach(function (o) {
      var elig = SLOT_ELIGIBLE[o.s] || [];
      for (var i = 0; i < cands.length; i++) {
        if (used[i]) continue;
        if (elig.indexOf(cands[i].p.pos) >= 0) { used[i] = 1; lineup.push(cands[i]); break; }
      }
    });
    return lineup;
  }

  // ---------- exports ----------
  window.SimEngine = {
    SEASON: SEASON, WEEKS: WEEKS, PRESETS: PRESETS, BOOM_BUST: BOOM_BUST,
    norm: norm, normTeam: normTeam, makeRng: makeRng,
    buildSchedule: buildSchedule, buildPlayers: buildPlayers,
    applyInSeasonInjuries: applyInSeasonInjuries, injAdj: injAdj, injuryState: injuryState, newsFlags: newsFlags, ascendingFlag: ascendingFlag, ctxNote: ctxNote,
    scoringFromLeague: scoringFromLeague, seasonPoints: seasonPoints,
    weeklyProjection: weeklyProjection, vegasMult: vegasMult, defenseAdj: defenseAdj, cbShadowMult: cbShadowMult, cb1OutBoost: cb1OutBoost, olOutDock: olOutDock, pressureMult: pressureMult, tdLuckAdj: tdLuckAdj, weatherMult: weatherMult, snapMult: snapMult, routeMult: routeMult, paceMult: paceMult,
    jsBasePg: jsBasePg, jsOppMult: jsOppMult,
    propAnchorMean: propAnchorMean, gammaMedRatio: gammaMedRatio, marketRate: marketRate, propImpliedFp: propImpliedFp, propCacheReset: propCacheReset,
    marketObsContaminated: marketObsContaminated,
    simWeek: simWeek, simSeason: simSeason, simLeague: simLeague, simBestBall: simBestBall, pickLineup: pickLineup,
    drawWeekEnv: drawWeekEnv, samplePlayerScore: samplePlayerScore, effMean: effMean, CORR: CORR,
    drawSeasonShock: drawSeasonShock, SLOT_ELIGIBLE: SLOT_ELIGIBLE
  };
})();
