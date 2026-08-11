// COPY of ../sim_lab/engine.js (synced 2026-08-11 10:56:31 by export_sleeper_extension_data.py — edit the sim_lab original)
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
      players.push(p);
      if (!byNorm[nk]) byNorm[nk] = p;
      if (p.sid) bySid[p.sid] = p;
    });

    // DST synthetics — mean derived weekly from opponent implied total.
    Object.keys(DST_NAMES).forEach(function (tm) {
      var p = {
        name: DST_NAMES[tm] + ' D/ST', norm: norm(DST_NAMES[tm] + ' D/ST'), pos: 'DST', tm: tm,
        comps: {}, ptsPPR: 0, clayGames: 17,
        sigmaPct: POS_SIGMA.DST * DST_SIGMA_CAL, sigmaSrc: 'pos-default',
        sid: tm, adp: null, isDST: true
      };
      players.push(p);
      byNorm[p.norm] = p;
      bySid[tm] = p; // Sleeper DEF player_id IS the team abbr
    });

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
    return { list: players, byNorm: byNorm, bySid: bySid, recByTeam: recByTeam };
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

  // ---------- in-season snap usage trend ----------
  // Self-activating once data/sim_snaps.js has 2026 weeks (empty preseason).
  // Compares a player's weighted recent snap share (last 3 recorded games
  // BEFORE the projected week, 0.5/0.3/0.2) to his season-to-date average —
  // catching role changes (committee shifts, rookie takeovers) faster than
  // Clay's guide updates. Stale data (last game >3 weeks back) = no adjust;
  // the injury layer owns absences. RB/WR/TE only.
  var SNAP_W = [0.5, 0.3, 0.2];
  function snapMult(p, wk) {
    if (p.pos !== 'RB' && p.pos !== 'WR' && p.pos !== 'TE') return 1;
    var sn = (typeof window !== 'undefined' && window.SIM_SNAPS_2026) ? window.SIM_SNAPS_2026[p.name] : null;
    if (!sn || !sn.w) return 1;
    var past = Object.keys(sn.w).map(Number).filter(function (w) { return w < wk; }).sort(function (a, b) { return b - a; });
    if (past.length < 2 || past[0] < wk - 3) return 1;
    var recent = 0, wsum = 0;
    past.slice(0, 3).forEach(function (w, i) { recent += sn.w[w] * SNAP_W[i]; wsum += SNAP_W[i]; });
    recent /= wsum;
    var seasonAvg = past.reduce(function (t, w) { return t + sn.w[w]; }, 0) / past.length;
    // 1.0%/snap-pt: backtested 2019-25 vs nflverse snap history
    // (backtest_snap_defense.py) — monotonic dose-response, empirical slope
    // 1.09%/pt, the original 0.8 was the only UNDERSIZED layer in the engine.
    return Math.min(1.30, Math.max(0.75, 1 + 1.0 * (recent - seasonAvg) / 100));
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
    return Math.max(1.0, 16.2 - 0.436 * oppImplied);
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
    var sM = snapMult(p, wk);
    var rampF = 1;
    if (p.ramp) {
      var R = RAMP[p.ramp];
      rampF = (gameIdx > 0 && gameIdx <= R.head.length) ? R.head[gameIdx - 1] : R.tail;
    }
    var factor = mult * dAdj * sM * rampF;
    var clayPg = seasonPoints(p, sc) / perGameDiv;
    mean = clayPg * factor;
    // JS Weekly (in-season model): Clay prior shrunk toward 2026 actuals,
    // actual FPA-by-position opponent adj replacing Clay unit grades as the
    // sample grows. Preseason (no 2026 data) both terms collapse to Clay's,
    // so jsMean === mean until real games exist.
    var jsMean = jsBasePg(p, sc, clayPg) * mult * jsOppMult(slot.opp, p.pos, dAdj) * sM * rampF;
    var compsWk = {};
    Object.keys(p.comps).forEach(function (k) {
      if (p.comps[k]) compsWk[k] = +(p.comps[k] / perGameDiv * factor).toFixed(2);
    });
    compsWk.rrtd = +(((p.comps.rtd || 0) + (p.comps.rctd || 0)) / perGameDiv * factor).toFixed(3);
    return { mean: mean, mult: mult, slot: slot, comps: compsWk, gameIdx: gameIdx, jsMean: jsMean };
  }

  // ---------- correlated sampling ----------
  // One draw of the week's common factors: per-team passing environment V
  // (correlated across each game), per-receiver draws g + the QB hub
  // (share-weighted sum of his receivers' g), antisymmetric rush script.
  function drawWeekEnv(gamesThisWeek, rng, players) {
    var env = { v: {}, hub: {}, g: {}, rush: {} };
    var a = Math.sqrt(CORR.gV), b = Math.sqrt(1 - CORR.gV);
    (gamesThisWeek || []).forEach(function (g0) {
      var zGame = rng.normal();
      env.v[g0.away] = a * zGame + b * rng.normal();
      env.v[g0.home] = a * zGame + b * rng.normal();
      var zR = rng.normal();
      env.rush[g0.home] = zR;
      env.rush[g0.away] = -zR;
    });
    var rbt = (players && players.recByTeam) || {};
    Object.keys(env.v).forEach(function (tm2) {
      var hub = 0;
      (rbt[tm2] || []).forEach(function (r) {
        var z = rng.normal();
        env.g[r.key] = z;
        hub += r.w * z;
      });
      env.hub[tm2] = hub;
    });
    return env;
  }

  function playerLoading(p, wkProj, env, rng) {
    // returns {L, f2}: the common-factor draw and its variance share
    if (p.isDST) {
      var vo = env.v[wkProj.slot.opp] || 0;
      return { L: CORR.fDST_oppV * vo, f2: CORR.fDST_oppV * CORR.fDST_oppV };
    }
    var L = 0, f2 = 0;
    var fv = CORR.fV[p.pos] || 0;
    L += fv * (env.v[p.tm] || 0);
    f2 += fv * fv;
    if (p.pos === 'QB') {
      L += CORR.fH_QB * (env.hub[p.tm] || 0);
      f2 += CORR.fH_QB * CORR.fH_QB;
    } else if (CORR.fG[p.pos]) {
      var gz = env.g[p.sid || p.norm];
      if (gz == null) gz = rng.normal(); // receiver outside the hub pool
      L += CORR.fG[p.pos] * gz;
      f2 += CORR.fG[p.pos] * CORR.fG[p.pos];
    }
    if (p.pos === 'RB') {
      L += CORR.fR_RB * (env.rush[p.tm] || 0);
      f2 += CORR.fR_RB * CORR.fR_RB;
    }
    return { L: L, f2: f2 };
  }

  // meanScale (optional): scales the player's whole level for this draw —
  // used by the season sim's shock/injury layers. Mean AND sd scale together.
  // Total per-player weekly variance is the SAME as the pre-QB-hub engine
  // ((0.9 sigma)^2 + 0.04); the loadings only re-apportion it between common
  // factors and idiosyncratic residual, so marginal calibration is untouched.
  function samplePlayerScore(p, wkProj, env, rng, meanScale) {
    if (!wkProj || wkProj.mean <= 0.05) return 0;
    var base = wkProj.mean * (meanScale || 1);
    var totalRel = Math.sqrt(Math.pow(RESID_SHRINK * p.sigmaPct, 2) + 0.04);
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
    var res = pool.map(function () { return []; });
    var games = schedule.byWeek[wk] || [];
    for (var s = 0; s < sims; s++) {
      var env = drawWeekEnv(games, rng, players);
      for (var i = 0; i < pool.length; i++) {
        res[i].push(samplePlayerScore(pool[i], pool[i]._wk, env, rng));
      }
    }
    return pool.map(function (p, i) {
      var arr = res[i].sort(function (a, b) { return a - b; });
      var mean = arr.reduce(function (t, v) { return t + v; }, 0) / arr.length;
      var bb = BOOM_BUST[p.pos] || { boom: 20, bust: 5 };
      return {
        player: p, week: wk, mean: mean,
        proj: p._wk.mean, jsProj: p._wk.jsMean, mult: p._wk.mult, slot: p._wk.slot, comps: p._wk.comps,
        p10: pct(arr, 0.10), p25: pct(arr, 0.25), p50: pct(arr, 0.50),
        p75: pct(arr, 0.75), p90: pct(arr, 0.90),
        boomAt: bb.boom, bustAt: bb.bust,
        boom: arr.filter(function (v) { return v >= bb.boom; }).length / arr.length,
        bust: arr.filter(function (v) { return v < bb.bust; }).length / arr.length
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
        if (wp && wp.mean > 0.05) wks.push({ wk: w, wp: wp });
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

    for (var s = 0; s < sims; s++) {
      // one env draw per NFL game of this simulated season, shared league-wide
      var envByWeek = {};
      for (var w2 = wFrom; w2 <= wTo; w2++) envByWeek[w2] = drawWeekEnv(schedule.byWeek[w2] || [], rng, players);
      for (var i = 0; i < pool.length; i++) {
        var e = pool[i], tot = 0;
        var scale = (e.shocked ? drawSeasonShock(rng, halfPtsOf(e.p)) : 1) * e.inf;
        for (var j = 0; j < e.wks.length; j++) {
          if (e.pPlay < 1 && rng.rand() >= e.pPlay) continue; // missed game
          tot += samplePlayerScore(e.p, e.wks[j].wp, envByWeek[e.wks[j].wk], rng, scale);
        }
        e.totals[s] = tot;
      }
      // positional finish THIS season
      Object.keys(byPos).forEach(function (pos) {
        var idxs = byPos[pos].slice().sort(function (a, b) { return pool[b].totals[s] - pool[a].totals[s]; });
        for (var r = 0; r < idxs.length; r++) {
          var e2 = pool[idxs[r]];
          e2.rankSum += r + 1;
          e2.rankCounts[r + 1] = (e2.rankCounts[r + 1] || 0) + 1;
        }
      });
    }

    return pool.map(function (e) {
      var arr = Array.prototype.slice.call(e.totals).sort(function (a, b) { return a - b; });
      var mean = arr.reduce(function (t, v) { return t + v; }, 0) / sims;
      function topN(n) {
        var c = 0;
        for (var r = 1; r <= n; r++) c += e.rankCounts[r] || 0;
        return c / sims;
      }
      return {
        player: e.p, games: e.wks.length, seasonProj: e.seasonMean, clayPts: seasonPoints(e.p, sc),
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
    var prep = {}; // prep[rosterId][week] = [{p, wp}]
    teams.forEach(function (t) {
      prep[t.rosterId] = {};
      var roster = t.playerIds.map(function (sid) { return players.bySid[sid]; }).filter(Boolean)
        .filter(function (p) { return unavailable[p.sid] !== 'ir'; });
      var allWeeks = regWeeks.slice();
      for (var w = playoffStart; w < playoffStart + 3; w++) allWeeks.push(w);
      allWeeks.forEach(function (wk) {
        var cands = roster.filter(function (p) {
          return !(wk === currentWeek && unavailable[p.sid] === 'out');
        }).map(function (p) {
          var wp = weeklyProjection(p, wk, sc, schedule);
          return wp ? { p: p, wp: wp } : null;
        }).filter(Boolean).sort(function (a, b) { return b.wp.mean - a.wp.mean; });
        prep[t.rosterId][wk] = pickLineup(cands, lineupSlots);
      });
    });

    // deterministic projected score per playoff week (sum of starter means)
    var playoffProj = {};
    teams.forEach(function (t) {
      playoffProj[t.rosterId] = {};
      for (var w2 = playoffStart; w2 < playoffStart + 3; w2++) {
        var lu = prep[t.rosterId][w2] || [];
        playoffProj[t.rosterId][w2] = lu.reduce(function (s2, slot) { return s2 + slot.wp.mean; }, 0);
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
      // standings + seeds
      var order = teams.slice().sort(function (a, b) {
        var ra = rec[a.rosterId], rb = rec[b.rosterId];
        return (rb.w - ra.w) || (rb.pf - ra.pf);
      });
      order.forEach(function (t, i) {
        var tl = tally[t.rosterId];
        tl.wins += rec[t.rosterId].w;
        tl.pf += rec[t.rosterId].pf;
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
    scoringFromLeague: scoringFromLeague, seasonPoints: seasonPoints,
    weeklyProjection: weeklyProjection, vegasMult: vegasMult, defenseAdj: defenseAdj, snapMult: snapMult, paceMult: paceMult,
    jsBasePg: jsBasePg, jsOppMult: jsOppMult,
    simWeek: simWeek, simSeason: simSeason, simLeague: simLeague, pickLineup: pickLineup,
    drawWeekEnv: drawWeekEnv, samplePlayerScore: samplePlayerScore, CORR: CORR,
    drawSeasonShock: drawSeasonShock, SLOT_ELIGIBLE: SLOT_ELIGIBLE
  };
})();
