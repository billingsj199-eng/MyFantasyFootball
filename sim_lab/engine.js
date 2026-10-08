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

  // Clay nickname -> the name every other feed uses (Sleeper, nflverse pbp,
  // injuries, props, depth charts). Clay keys are the pool's names, so without
  // this these players silently missed ids/ADP/sigma/usage/TD luck/xFP/injury
  // data (2026-09-23: Ken Walker III showed no xFP on the site).
  var CLAY_NORM_ALIAS = { 'ken walker': 'kenneth walker', 'cameron ward': 'cam ward', 'chigoziem okonkwo': 'chig okonkwo' };

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
      // FUTURE TOTALS RE-RATED (build_future_totals.py, 2026-09-29): the book's lines for far-out weeks are the May / July
      // look-ahead numbers (198 of 208 games from week 5 on had not moved since preseason). Each team's offense / defense
      // shift is measured from the games the book HAS re-lined this season and added to the stale future lines; a line
      // the book moved in the last 10 days is not in the file and stays as posted. backtest_future_totals.py: miss vs the
      // eventual closing line -13% standing after week 4 (6/7 seasons), -23% after week 8 (7/7); points-scored MSE -2.9% /
      // -4.8%; real 2026 preseason lines -7% to -12%. Kill: window.SIM_FUTURE_TOTALS_OFF = true.
      var ft = (window.SIM_FUTURE_TOTALS_OFF !== true && window.SIM_FUTURE_TOTALS && window.SIM_FUTURE_TOTALS.games) ? window.SIM_FUTURE_TOTALS.games[key] : null;
      var bookTotal = total, bookSpread = spread;
      if (ft && typeof ft.total === 'number' && typeof ft.spread === 'number') { total = ft.total; spread = ft.spread; }
      var homeImp = (total - spread) / 2, awayImp = (total + spread) / 2;
      (games[wk] = games[wk] || []).push({ away: away, home: home, total: total, spread: spread, key: key });
      sched[home] = sched[home] || {}; sched[away] = sched[away] || {};
      var reRated = total !== bookTotal || spread !== bookSpread;
      sched[home][wk] = { opp: away, home: true, total: total, spread: spread, implied: homeImp, oppImplied: awayImp, gameKey: key, reRated: reRated, bookImplied: (bookTotal - bookSpread) / 2 };
      sched[away][wk] = { opp: home, home: false, total: total, spread: spread, implied: awayImp, oppImplied: homeImp, gameKey: key, reRated: reRated, bookImplied: (bookTotal + bookSpread) / 2 };
    });
    // league-average implied total (for the Vegas multiplier)
    var sum = 0, n = 0, gameWeeks = {};
    Object.keys(sched).forEach(function (tm) {
      // league average from the BOOK's lines, re-rated or not: the normalizer must not move when future weeks are re-rated,
      // or the current week's numbers would shift with it (and cross the below-market threshold: D. Jones +0.8 in testing)
      Object.keys(sched[tm]).forEach(function (wk) { var s0 = sched[tm][wk]; sum += (s0.bookImplied != null ? s0.bookImplied : s0.implied); n++; });
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
      var nk = norm(name), clayNk = nk;
      if (CLAY_NORM_ALIAS[nk]) nk = CLAY_NORM_ALIAS[nk];
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
        draftPick: (mt && mt.dy === SEASON && typeof mt.dp === 'number') ? mt.dp : null,   // this year's draft slot (Clay-free shadow rookie prior)
        tmNow: sl && sl.sTm ? normTeam(sl.sTm) : null,   // Sleeper's current team (fresher than Clay's after a trade; depth-chart lookup fallback)
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
      // CLAY-FREE KICKER (2026-10-08, backtest_kicker_vegas.py): kicker points are near-noise week to week; on 2020-25 a line on the team's implied total
      // (5.04 + .145 x implied) matches or beats Clay's FG / XP line x kLevel (2026 W1-4 MAE 3.55 vs 3.66, rank order nil for every candidate). Base = that
      // line at the team's season-average implied total x 17 games, split fgm / xpm at the 2025 league shares per point (.2009 / .2612); the game chain
      // (Vegas / weather) and the kpts anchor sit on top as before. kLevel applies only once the tuner has re-fit it on this base (TU.kBase === 'vegas').
      // Kill: window.SIM_K_CLAYFREE = false (restores Clay's line + kLevel). Backup engine.js.bak_pre_kvegas_20261008.
      var kVegas = false;
      if (pos === 'K' && !(typeof window !== 'undefined' && window.SIM_K_CLAYFREE === false) && schedule && schedule.byTeam) {
        var kbt = schedule.byTeam[p.tm], kImp = [], kAvg = schedule.avgImplied || 22.5;
        if (kbt) Object.keys(kbt).forEach(function (w) { var s0 = kbt[w]; if (s0 && typeof s0.implied === 'number' && s0.implied > 0) kImp.push(s0.implied); });
        var kSeason = kImp.length ? kImp.reduce(function (a, b) { return a + b; }, 0) / kImp.length : kAvg, kPg = 5.04 + 0.145 * kSeason;
        p.ptsPPR = +(kPg * 17).toFixed(1); p.clayGames = 17; p.comps.fgm = +(kPg * 17 * 0.2009).toFixed(2); p.comps.xpm = +(kPg * 17 * 0.2612).toFixed(2); p.kSrc = 'vegas'; kVegas = true;
      }
      if (TU && pos === 'K' && typeof TU.kLevel === 'number' && TU.kLevel > 0 && (!kVegas || TU.kBase === 'vegas')) {
        p.ptsPPR *= TU.kLevel;
        p.comps.fgm = +(p.comps.fgm * TU.kLevel).toFixed(2);
        p.comps.xpm = +(p.comps.xpm * TU.kLevel).toFixed(2);
      }
      players.push(p);
      if (!byNorm[nk]) byNorm[nk] = p;
      if (clayNk !== nk && !byNorm[clayNk]) byNorm[clayNk] = p;   // Clay spelling still resolves
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
    _poolByNorm = byNorm;   // for the shadow's chart-availability check (effectiveString)
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
        // games = the per-start RATE divisor (Clay's implied starts from the
        // auto split, else his games), NOT the window length: stretching
        // Penix to 15 starts must not spread Clay's ~9-start points thin
        // (2026-09-23: 12.4/start had become 9.5). 0 games = benched all year.
        var auto = {};
        var ar = rooms[tm].slice().sort(function (a, b) { return b.ptsPPR - a.ptsPPR; });
        if (ar.length >= 2) {
          var aB = ar[1].ptsPPR / QB_BACKUP_RATE;
          var agB = Math.min(12, Math.max(2, Math.round(17 * aB / (ar[0].ptsPPR + aB))));
          auto[ar[0].norm] = 17 - agB; auto[ar[1].norm] = agB;
        }
        var g0 = 0;
        overrides[tm].forEach(function (entry) {
          var p = byNorm[norm(entry[0])];
          var g = entry[1];
          if (!p) return;
          var rate = auto[p.norm] || p.clayGames || 17;
          if (!g) { p.qbWindow = { s: 0, e: -1, games: rate, src: 'override' }; return; }
          p.qbWindow = { s: g0 + 1, e: g0 + g, games: rate, src: 'override' };
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

  // CLAY GAMES DIVISOR (2026-09-16, Jack: "lets do it if it actually improves the numbers"): the weekly mean is Clay's
  // season points over the games HE projects (his sheet's gm), not over 17 - a player he expects to miss time was
  // projecting 13-70% low every week he does play, and the injury layer docks the absence again. Harness 2019-25:
  // -0.74% MSE (6/7 seasons), QB affected rows -3.8%, gm <= 10 rows -19%, Clay bias act/proj 1.047 -> 0.998. The
  // season sim's games-played draw keeps pPlay = gm/17 but no longer re-inflates the mean (it is already per game).
  // gm < 4 is treated as unreliable (17). Kill: window.SIM_CLAY_GM = false.
  function clayDiv(p) {
    if (typeof window !== 'undefined' && window.SIM_CLAY_GM === false) return 17;
    var g = p.clayGames;
    return (typeof g === 'number' && g >= 4 && g < 17) ? g : 17;
  }
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
    // TE removed 2026-09-30 (backtest_te_ol_dock.py, 'OL' label fixed): TEs with 2+ linemen out ran 1.00 week-controlled
    // on the snap harness and 1.10-1.19 on the pre-kickoff Out/Doubtful harness (checkdowns); a dock had no support.
    // QB (.98 / .99) is marginal too; RB (.90 / .91) and WR (.96) keep theirs.
    if (pos !== 'QB' && pos !== 'RB' && pos !== 'WR') return 1;
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
  // SHADOW AGING (backtest_age_exp.py, 2026-09-15): season-over-season regression toward the position
  // mean + residual age / experience curves, graded LOYO 2019-25 against the player's own 3-yr prior.
  // Used ONLY by the Clay-free shadow prior (ncMean); refreshed by scratch patch_shadow_age.py from
  // data/age_exp_backtest.js. Kill: window.SIM_SHADOW_AGE = false.
  var SHADOW_AGE = {"reg":{"QB":[1.3645,0.5086,1.0357],"RB":[0.0147,0.9393,1.1103],"WR":[-0.2146,1.0429,1.0902],"TE":[0.0646,0.9158,1.0838]},"age":{"QB":{"22":1.04,"23":1.037,"24":1.017,"25":0.978,"26":0.921,"27":0.908,"28":0.939,"29":0.993,"30":1.011,"31":1.003,"32":1.0,"33":0.976,"34":0.966,"35":0.958},"RB":{"22":1.026,"23":0.996,"24":0.973,"25":0.935,"26":0.908,"27":0.89,"28":0.866,"29":0.852,"30":0.864,"31":0.843},"WR":{"21":1.068,"22":1.121,"23":1.052,"24":1.03,"25":0.956,"26":0.924,"27":0.872,"28":0.854,"29":0.847,"30":0.868,"31":0.824,"32":0.813,"33":0.794},"TE":{"22":0.974,"23":1.011,"24":1.023,"25":1.022,"26":0.958,"27":0.917,"28":0.906,"29":0.885,"30":0.893,"31":0.896}},"exp":{},"useReg":true,"useAge":true,"useExp":false,"src":"backtest_age_exp.py 2026-09-15 16:53"};
  // CLAY-FREE SHADOW v2 (backtest_noclay_weekly.py, 2026-09-16; 19,064 player-weeks 2019-25, week 1 included):
  // the v1 shadow (own history + age + opportunity, Clay where no history) ran +0.36% MSE vs the shipped Clay
  // blend. Three knobs closed it: shrink the prior toward the position mean (k .8, picked in 7/7 folds),
  // a per-position prior strength (QB 12 in 6/7 folds, WR/TE 8, RB 5) and a Clay-free fallback for rookies
  // (ppg = a + b ln(draft pick), half-PPR, fit 2019-25 rookies) / the position mean for anyone else without
  // history. Combined: -0.03% vs shipped (forward 2021-25 -0.17%), -0.39% vs the v1 shadow (5/7). The gap
  // that remains is week 1 (+5.9%) and weeks 2-4 (+0.7%): Clay still knows rookies and team-changers better
  // before they play. SHADOW ONLY - never feeds effMean. Kill: window.SIM_NC_V2 = false (reverts to v1).
  var NC_SHADOW = {
    P: { QB: 12, RB: 5, WR: 8, TE: 8 },
    k: 0.8,
    adpGate: 200,                                                                    // Clay-free "in the pool" test (consensus ADP)
    posMean: { QB: 17.415, RB: 9.94, WR: 8.585, TE: 6.282 },                       // half-PPR pool mean 2019-25
    rookie: { QB: [16.352, -0.688], RB: [19.764, -2.617], WR: [13.031, -1.518], TE: [11.170, -1.358] },   // a + b ln(pick)
    // v2.1 MARKET PRIOR for veterans (backtest_rookie_prior.py, 2026-09-16): E[half-PPR PPG | preseason ADP] fit on
    // every listed player 2019-25 (FFC 12-team ADP, a + b ln(adp)), blended into the history prior at .75 (2nd-year
    // players .5): -0.66% vs shipped (5/7), forward -0.80% (4/5), -0.54% vs v2 (7/7); team-changers wanted 1.0, QB 7/7.
    // Only listed players (ADP <= adpMax, the FFC range); rookies keep the draft-pick fallback (every rookie ADP
    // model lost to the pick alone). Kill: window.SIM_NC_ADP = false.
    adpCurve: { QB: [35.434, -3.8335], RB: [22.8287, -3.151], WR: [22.719, -3.0549], TE: [19.9698, -2.6563] },
    adpW: 0.75, adpWYr2: 0.5, adpMax: 181,
    // v2.2 ROOKIE DEPTH STRING (backtest_rookie_depth_live.py, 2026-09-16; nflverse weekly depth charts 2019-25 =
    // the same ESPN charts sim_depth.js carries): a + b ln(pick) + c [2nd string] + d [3rd string or deeper] on rookie
    // weeks 1-4 cut error -4.6% vs the pick alone and -1.3% vs Clay (starter rookie RBs ran 1.39x the pick prior, 2nd
    // string .82x); inside the shadow -0.10% vs v2.1 (6/7), forward -0.03%. RB and WR only (QB flat, TE worse, small
    // n). Unlisted on the live chart = deep (d). Kill: window.SIM_NC_DEPTH = false.
    rookieStr: { RB: [18.1294, -1.1986, -5.7632, -6.8114], WR: [13.971, -1.5426, -1.995, -0.7776] },
    // v2.3 DEMOTED VETERANS (backtest_demoted_vets.py, 2026-09-16): a veteran with a history prior who sits 2nd or
    // 3rd+ string on the pre-game chart scores .58-.90 of the prior. Prior x m, per position and string, picked
    // LOYO vs the shadow itself: -0.28% vs v2.2 (7/7), demoted rows -1.7%, forward (docks picked on earlier seasons)
    // -0.15% (5/5). A level blend was weaker; the promotion side (string 1 with a low prior) showed nothing.
    // Unlisted = no dock. Kill: window.SIM_NC_VETDOCK = false.
    vetDock: { RB: { 2: 0.8, 3: 0.4 }, WR: { 2: 0.6, 3: 0.6 }, TE: { 2: 0.8 } },
    // v2.5 WEEK 1 = CHART-DEFINED BURIED-ROOKIE RAMP (backtest_week1.py, 2026-09-16): week 1's whole gap was buried
    // rookies (2nd string act/shadow .74, +25% vs shipped) - a level, more shrink and heavier market weights all
    // failed. Rookies at 2nd string or deeper (or unlisted) x.7 in game 1 (-10.5%, 5/7), x.8 in game 2 (-1.5%, 4/7),
    // nothing after (wk3+ 0-1/7). Forward: buried rookies wks 1-4 -4.1% (4/5), week-1 rows -1.05% (4/5); week 1 goes
    // +0.53% -> -0.38% vs shipped. Inside the shadow it REPLACES the live Clay-defined ramp (RAMP.buried keys on
    // Clay's projection vs the team leader) so a rookie is never ramped twice. 1st-string rookies: no ramp
    // (x1.1 wanted, 0/7). Kill: window.SIM_NC_RAMP = false (shadow keeps the live ramp).
    rookieRamp: [0.7, 0.8],
    // v2.6 SECOND-YEAR ROLE GROWTH (backtest_second_year.py, 2026-09-16): a 2nd-year player who was a part-timer late in
    // his rookie season (mean offensive snap share over his last 4 games < 40%) outscores the shadow prior 1.18x - the
    // history prior is his part-time season, the role grew. Prior x1.2 on those rows: -1.36% vs shadow (6/7), forward
    // (picked on earlier seasons) its rows -1.31% (4/5). Level, recency, ADP weight, chart promotion (the market already
    // prices it) and the snap TREND all fail or fail forward. Data: SIM_SNAPS_PRIOR (sim_snaps.js, last season's late
    // snap share by norm name, from the site's snap_counts.js). Kill: window.SIM_NC_YR2 = false.
    yr2LowSnap: { max: 0.40, mult: 1.2 },
    // v2.7 WR ROUTE GRADE RESIDUAL (backtest_pff_route_grade.py, 2026-09-16): a receiver whose prior-season PFF route
    // grade (>= 50 routes) sits above what his shadow prior implies (residual = grade - (c0 + c1 x prior half-PPR),
    // top tercile = above cut) gets prior x1.1: -0.43% vs shadow on those rows (5/6), forward -0.26% (4/5); all
    // rows -0.04%. Tercile levels, curve blends, TE and RB versions fail or lean. Marginal and shadow-only. Data:
    // SIM_PFF_ROUTE_PRIOR (sleeper_meta.js, last season's WR route grade by norm name). Kill: window.SIM_NC_GRADE = false.
    wrGrade: { c0: 56.095, c1: 1.9876, cut: 2.649, mult: 1.1 },
    // v2.8 BACKUP QB RULE (2026-09-16, Jack's W2 outlier read): the shadow's "higher than Clay" list was all backup QBs
    // (Mariota 14.5, Winston 14.1, Mac Jones 13.2 vs live 0.5) - their history is their starting days and the shadow
    // never asked whether they start. Clay-free answer = the depth chart: a QB at string 2+ (or unlisted on a charted
    // team) gets a backup-level prior (qbBackupPpg, half-PPR) unless the injury layer says he inherits the starter's
    // role (iA > 1). The harness could not see this: backups who did not play are never graded. Same session: the
    // string docks (vetDock) now apply to EVERY non-rookie with a chart position, gated or not, pos-mean rows too.
    qbBackupPpg: 1.0,
    // v2.10 RETURNING-QUESTIONABLE DOCK (backtest_qd_shadow.py, 2026-09-16): with the live game-week docks already applied,
    // a Questionable player who MISSED last week scores .80-.84 of the shadow (one who played last week ~.94-1.0; the
    // live Q+DNP x.75 already fits). Extra x.85 on those rows: -8.1% vs shadow (5/7), forward -10.1% (5/5). Missed = no
    // 2026 game in wk-1 (sim_2026 players[norm].wks; no record = missed; a bye counts, as in the harness). Doubtful was
    // untestable (n 3) - the live x.5 stands. Kill: window.SIM_NC_QRET = false.
    qRet: { mult: 0.85 },
    noChart: { mult: 0.8, games: 4 },   // v2.14 no-chart veterans, first 4 games (kill: window.SIM_NC_NOCHART = false)
    qbOutWrDock: { star: 0.15, other: 0.05, starAdp: 60 },   // v2.20 WRs when the team's projected starting QB is unavailable: MSE -9.3% on those weeks (7/7 seasons), calibrated 9.20 vs actual 9.22 (kill: window.SIM_NC_QBOUT = false)
    earlyP: { WR: { mult: 5, games: 1 } },   // v2.21 prior strength x5 for a WR's projection after exactly one game (kill: window.SIM_NC_EARLYP = false)
    vegEvK: 1,   // v2.24 Vegas-adjusted points evidence: each past game / its own Vegas multiplier ^ k (kill: window.SIM_NC_VEGEV = false)
    rankMixW: 0.5,                      // rank mix: weight on the shadow vs the ESPN weekly projection (kill: window.SIM_RANKMIX = false)
    qbTotalC: 0.03,                     // v2.19 QB shootout tilt: exp(c x z of the game total within the week) (kill: window.SIM_NC_TOTAL = false)
    usageLam: { RB: [1.0, 0.3, 0.25], WR: [1.0, 0.08, 0.25] },   // v2.18 [start, slope per game, floor] weight on xFP/g in the shadow's evidence (kill: window.SIM_NC_USAGE = false)
    // v2.30 (backtest_jm_ridge.py, 2026-10-02): RB takes .75 of the learned prior (its rows -0.25% next game 6/7, -0.73% / -0.22%
    // rest of season 5/7; top-150 weighted better in 5-6 of 7 at every horizon), and QBs drafted after pick 100 take .25 of it
    // (their rows -0.5% next game, -2.5% / -2.1% rest of season, 6/7 each; QBs drafted in the top 100 get WORSE on it, +0.8% /
    // +3%, so they stay at 0). WR / TE .5 confirmed. JM itself: the prior rebuilt without it is worse in 7 of 7 seasons next
    // game (RB the whole effect, WR / TE flat). Kill: window.SIM_NC_RIDGE2 = false.
    ridgeW2: { RB: 0.75, lateQbAdp: 100, lateQbW: 0.25 },
    ridgeW: { QB: 0, RB: 0.5, WR: 0.5, TE: 0.5 },   // v2.15 learned season prior weight in the shadow prior (kill: window.SIM_NC_RIDGE = false).
                                        // v2.17 (backtest_qb_compression.py, 09-17): QB = 0 - the ridge half hurt quarterbacks: top-150 QB weighted -0.65% LOYO (6/7), -1.41% fwd (5/5),
                                        // elite QBs -1.1% / -1.8%; un-shrinking (k up) and a weaker P both made QBs worse, so the shrink and P = 12 stay.
    // v2.11 VACATED ROLE (backtest_vacated_shadow.py, 2026-09-16): the live layer's teammate boost (iA > 1, a zeroed
    // player's share redistributed by depth rank) reaches the shadow at the live strength. Graded on the shadow with the
    // share-rebuilt multiplier: best strength k = .75 (shadow x boost^.75): boosted rows -1.07% vs no layer (6/7),
    // forward -1.46% (5/5); RB -4.0% (k .75), WR / TE weaker (k .5, 3-4/7); boosts <= x1.05 nothing, > x1.15 -4.2%.
    // Backup-QB inheritance (n 11) untestable -> QB keeps k 1. Docks (iA < 1) untouched. Kill: window.SIM_NC_VAC = false.
    vacatedK: { QB: 1.0, RB: 0.75, WR: 0.75, TE: 0.75 },
    // v2.12 exact shadow-unit redistribution (see weeklyProjection): depth weights by effective string for the absorbers.
    depthW: [1.6, 1.0, 0.5],
    // v2.25 next layers (weeklyProjection, backtest_shadow_next.py 2026-10-02): QB mover / low-total docks, rookie WR and
    // low-carry RB early docks (games 2-5), WR / TE snap-share level (edges = half-PPR weekly projection octiles,
    // ref = the snap share players in that bin averaged, 2019-25). qbFill: a fill-in QB takes the LARGER of his own
    // number and 85% of the starter's, never both (43 fill-in starts: actual 14.7, own 14.3, added 26.4).
    next: { qbMover: 0.90, lowTot: [19, 0.75], rookieWr: 0.90, rbCarry: [0.30, 0.90], early: [2, 5], snapE: 0.3, snapEFar: { WR: 0, TE: 0.3 }, snapClamp: [0.7, 1.4],
      teDockK: 0.5,   // 2026-10-08 TE snap-trend + snap-level multipliers at this exponent (backtest_te_shadow_core.py: docked TE rows scored 1.089 of the shadow; halved docks + the luck term -1.0% next game, -5.7% rest of season, rank +.012/+.018 5/7 both; shadow TE gap to Clay +7.9% -> +1.7% ROS). Kill: window.SIM_NC_TE_DOCKS = false.
            // v2.26 REST OF SEASON (backtest_shadow_ros.py, 8,542 checkpoints with 3-10 games played, graded on the per-game number
            // for the rest of the season, with and without a 4-games-left filter): weeks after the current one use qbMoverFar,
            // the TE team pass-rate tilt and, for RBs, the snap trend as it stands today (the trend layer goes stale 3 weeks out).
            qbMoverFar: 0.84, teTilt: 0.04, rbSnapCarry: true,
            // v2.31 (research_elite_docks.py, 2026-10-02; Jack: 'elite players like jefferson should not be projected very low if
            // he plays'): WR / TE drafted in the top 30 whose snap share calls for a 5%+ dock scored .998 of the UNDOCKED number
            // (1.112 of the docked one, 93 rows); the dock is right from pick 61 on (.875 undocked). So no snap-level dock for
            // the top 30. The boost side is untouched. Kill: window.SIM_NC_ELITE = false.
            snapNoDockAdp: 30,
            // v2.32 BLOWOUTS (research_excused_games.py, 2026-10-02; Jack: 'make sure we dont hurt players snap and target share
            // for injuries and blowouts'). The game after a blowout in which a top-150 player sat (21+ final margin, under 85% of
            // his snap share): RB 1.109 of a number the snap trend had docked 7% (carried rest of season: +10.1% error, 1/6);
            // WR / TE 1.011 with no level dock, 1.053 with it. So for the top 150, a last game with real garbage time (15%+ of
            // the team's plays, 6+) cannot dock the snap level (read on competitive plays) or the RB snap trend. Injury exits are
            // NOT excused below the top 30: the next game runs .79 of the undocked number (6/6 seasons) and leaving those games
            // out of the evidence is +1.9% (1/7). Kill: window.SIM_NC_BLOW = false.
            blowNoDockAdp: 150, blowMinShare: 0.15,
            // v2.27 STRUCTURE BY DRAFT SLOT, later weeks, 3+ games played (backtest_shadow_ros.py section 7; each fixed setting
            // better in 5-7 of 7 seasons with and without the 4-games-left filter): prior weight x2.5 for RBs drafted 61-100
            // (-4.5% / -4.7%), x0.6 for WRs drafted 61-100 (-3.1% / -2.5%), x0.75 for second-year QBs (-2.4% / -2.5%); usage
            // weight capped at .25 for WRs drafted 101-150 (-3.1% / -2.7%, rank order +.15); TEs drafted 31-60 x1.10
            // (-24.5% / -17.9% on 139-165 rows - small sample). Kill: window.SIM_NC_ROS2 = false.
            // v2.28 (section 9, leads from inside the weak spots): a WR drafted 101-150 who is BELOW his preseason level gets prior
            // weight x0.4 - the cold start is believed (-6.9% / -6.2% on those rows, 5-6 of 7; closes the Clay gap in that band);
            // RBs come down on high play-volume offenses and up on low ones, e .04 per sd of team plays a game (-1.5% / -1.5%,
            // 5-6 of 7, forward 3/4 and 4/4); RB backups drafted in the top 150 x1.04 (-4.2% / -2.9%, 6/7 both - the weakest).
            struct: { minGames: 3, rbMidP: 2.5, wrMidP: 0.6, mid: [60, 100], qbYr2P: 0.75, wrLateLam: 0.25, late: [100, 150], teLevel: 1.10, teBand: [30, 60],
                      wrLateColdP: 0.4, rbPlays: 0.04, rbBackup: 1.04, rbBackupAdp: 150,
                      // v2.33 (section 11, Jack: 'do we feel like the weights are correct on each player'): the weight the model puts
                      // on this season matches the best fit for QB (34 / 34%) and WR (46 / 45%) and by stage, but not for ROOKIES - a
                      // rookie's first games say far less than his draft-capital level (best-fit weight on the season: RB 18% vs the
                      // model's 49%, TE 8% vs 43%). Prior weight x1.6 for rookie RBs (-2.2% / -1.9%, 5/7 both runs) and x2.5 for rookie
                      // TEs (-1.9% / -1.1%, forward 3/4 both). QB and WR rookies did not hold up and are unchanged.
                      rookieP: { RB: 1.6, TE: 2.5 } },
            snapLvl: { WR: { edges: [4.87, 6.22, 7.4, 8.68, 9.93, 11.23, 12.87], ref: [45.9, 59.7, 67.2, 72.6, 79.8, 83.3, 83.7, 85.0] },
                       TE: { edges: [3.85, 4.66, 5.4, 6.28, 7.17, 8.04, 9.48], ref: [52.6, 57.7, 64.9, 68.2, 71.7, 74.7, 76.9, 83.8] } } },
    // v2.9 IR / PUP / OUT layer: see shadowOut() - the shadow holds IR / PUP / Out / non-Active players at 0 while the
    // status persists (no 4-week cap), releases them when the status changes; overrides win. Kill: SIM_NC_OUT = false.
    src: 'backtest_noclay_weekly.py + backtest_rookie_prior.py 2026-09-16'
  };
  // Depth string on the live ESPN chart (data/sim_depth.js, flattened slot-by-depth by pull_depth_charts.py):
  // 1 = starter, 2 = second string, 3 = deeper; WR has 3 slots so string = floor(index / 3) + 1. null = not listed.
  // Lookup order: Clay's team, Sleeper's current team, then any team's chart (backtest_nochart_vets.py: 464 of
  // 1,180 "no chart" veteran weeks were on another team's chart - a traded player; reading it there cut those rows'
  // error -2.4%). Truly unlisted stays null (a flat dock there failed RB 0/7 and forward).
  // EFFECTIVE string (Jack 2026-09-16): the chart only ranks players who are AVAILABLE this week. A chart player is
  // skipped while he is zeroed by the injury layer (Out / IR / PUP / suspended) or carries a designation (Questionable /
  // Doubtful / non-Active status) and has not played a 2026 game yet ("keep them out until we get a report they are
  // playing"). So Tua is ATL's effective QB1 while Penix (Questionable, no game yet) sits first on the chart; once
  // Penix plays or the tag clears he moves back to QB1 and Tua becomes the backup. Used by every shadow rule that
  // reads the chart (backup QB, string docks, rookie string, buried-rookie ramp); the pool builder keeps the raw chart.
  var _poolByNorm = null;
  // v2.12: per-(week, scoring) cache of shadow numbers for the exact redistribution pass; reset whenever the injury
  // state is rebuilt (applyInSeasonInjuries) and by E.ncCacheReset() for tests.
  var _ncCache = {}, _ncPass = false;
  function ncCacheKey(wk, sc) { return wk + '|' + [sc.rec, sc.pass_td, sc.pass_yd, sc.rush_yd, sc.rec_yd, sc.rush_td, sc.rec_td, sc.bonus_rec_te || 0].join(','); }
  function ncCacheReset() { _ncCache = {}; _peckCache = {}; }

  // PECKING-ORDER DOCKS (backtest_role_age.py, 2026-09-29; Jack: "add the wr3 and rb2 docks with kill switches").
  // 14,494 player-weeks 2019-25, rank = the player's projection among teammates at his position who play that week:
  // a team's 3rd-or-lower WR scored .888 of projection (under in 7 of 7 seasons; held-out x0.88 = -2.3% MSE on those
  // rows, 7/7) and its 2nd RB .953 (6/7; held-out x0.94 = -0.5%, 6/7). WR2, leads, age and experience = nothing.
  // Shipped SHAVED: WR 3rd+ x0.92, RB 2nd+ x0.97 (RB 3rd+ had 6 rows - it takes the RB2 dock so the order cannot flip).
  // Model side only: the books already price the role, so the market half of the anchor and the market rate stay clean.
  // Tested on projections >= 5 half-PPR, so the dock fades in between 4 and 5. Lock rows store `peck` (peck_scorecard.py).
  // Kill: window.SIM_PECK_DOCK = false (both), window.SIM_PECK_WR3 = false, window.SIM_PECK_RB2 = false.
  var PECK = { WR: { fromRank: 3, mult: 0.92 }, RB: { fromRank: 2, mult: 0.97 }, fadeFrom: 4, fadeTo: 5, minTeammate: 0.5 };
  var _peckCache = {}, _peckPass = false;
  function peckDock(p, wk, sc, schedule, jsRaw, jsHalf) {
    var rule = PECK[p.pos], out = { m: 1, rank: null };
    if (!rule || p.isDST) return out;
    var wnd = typeof window !== 'undefined' ? window : null;
    if (wnd && (wnd.SIM_PECK_DOCK === false || (p.pos === 'WR' && wnd.SIM_PECK_WR3 === false) || (p.pos === 'RB' && wnd.SIM_PECK_RB2 === false))) return out;
    var ck = ncCacheKey(wk, sc), C = _peckCache[ck] || (_peckCache[ck] = {});
    C[p.norm] = jsRaw;
    if (_peckPass || _ncPass || !_poolByNorm) return out;   // inside a teammate pass: record the number, never recurse
    var keys = Object.keys(_poolByNorm), grp = [];
    for (var i = 0; i < keys.length; i++) { var q = _poolByNorm[keys[i]]; if (q !== p && q.tm === p.tm && q.pos === p.pos && !q.isDST && grp.indexOf(q) < 0) grp.push(q); }   // the pool carries alias keys: one entry per player
    _peckPass = true;
    try { for (var j = 0; j < grp.length; j++) if (C[grp[j].norm] == null) weeklyProjection(grp[j], wk, sc, schedule); } finally { _peckPass = false; }
    var rank = 1;
    for (var k = 0; k < grp.length; k++) { var v = C[grp[k].norm]; if (v != null && v >= PECK.minTeammate && v > jsRaw) rank++; }
    out.rank = rank;
    if (rank >= rule.fromRank) {
      var fade = Math.max(0, Math.min(1, (jsHalf - PECK.fadeFrom) / (PECK.fadeTo - PECK.fadeFrom)));
      out.m = 1 - (1 - rule.mult) * fade;
    }
    return out;
  }
  // SHADOW IR / PUP / OUT LAYER (Jack 2026-09-16: "if a player is on IR or PUP or listed as out we keep them out until we
  // get a report they are playing, and vice versa"). The live injury layer zeroes IR / PUP for the 4-week minimum and
  // then lets the projection return; the Clay-free shadow instead holds a player at zero for as long as the status
  // persists (Sleeper injury_status IR / PUP / NFI / Out / Sus / DNR / COV, or a non-Active roster status), and
  // releases him the day the status changes - the daily Sleeper pull IS the report. IN_SEASON_OUT_OVERRIDES wins
  // when set (out inside its window, playing outside it). NA (exempt list) follows the live layer's read.
  // Kill: window.SIM_NC_OUT = false.
  // RETURN TIMING (Jack 2026-10-02: "add a return timing that we just created with all the injury reports / past
  // data"). The hold above is a THIS-WEEK rule; applied to every later week it left the shadow with no rest-of-season
  // number for anyone currently out (Hall / Etienne / Mayfield at 0 through week 18, their work handed to teammates
  // all year). For weeks AFTER the current one the shadow now takes its availability from the injury layer like the
  // live number does - manual out-windows, news timelines, the season-ending diagnosis rule and the availability
  // curve by position + injury (P(plays) scales the week, the rest flows to teammates), then the return ramp.
  // backtest_shadow_return.py, 1,668 absence states 2019-25, next four games: held out Brier .422, curve .222
  // (-47%); expected games 1.91 vs actual 1.84 (hold 0.00). Kill: window.SIM_NC_RETURN = false (hold every week).
  function shadowOut(p, wk) {
    if (!p || (typeof window !== 'undefined' && window.SIM_NC_OUT === false)) return null;
    if (_inj && _inj.week >= 1 && wk > _inj.week && !(typeof window !== 'undefined' && window.SIM_NC_RETURN === false)) return null;   // later weeks: the injury layer (iA) decides
    var ov = (typeof window !== 'undefined' && window.IN_SEASON_OUT_OVERRIDES) ? window.IN_SEASON_OUT_OVERRIDES[p.name] : null;
    if (ov && ov.length >= 2 && !(_inj && _inj.week > ov[1])) return (wk >= ov[0] && wk <= ov[1]) ? 'override' : null;   // a running window speaks; an expired one falls through to the status (as the live layer does)
    var f = String(p.injFlag || '').split('|'), inj = f[0] || '', st = f[1] || '';
    if (/^(IR|PUP|NFI|Out|Sus|DNR|COV)$/i.test(inj)) return inj.toLowerCase();
    if (st && !/^Active$/i.test(st)) return st.toLowerCase();
    if (/^NA$/i.test(inj) && injAdj(p, wk) === 0) return 'na';
    return null;
  }
  function chartAvailable(nm, wk) {
    var nk = norm(nm);
    if (injAdj({ norm: nk }, wk) === 0) return false;
    var q = _poolByNorm && _poolByNorm[nk];
    if (!q) return true;   // not in the pool: nothing says he is out
    if (shadowOut(q, wk)) return false;   // IR / PUP / Out beyond the live layer's 4-week window
    var flag = String(q.injFlag || ''), designated = /Questionable|Doubtful|Out/i.test(flag) || /\|(IR|PUP|NFI|Sus|NA|Inactive|Reserve)/i.test(flag);
    if (!designated) return true;
    var d = jsData(), rec = d.players && d.players[nk];
    return !!(rec && rec.g > 0);   // designated but already played this season -> available
  }
  // PRE-INJURY CHART SPOT (Jack 2026-10-02, "do it"). ESPN drops a player down or off the depth chart while he is
  // out (Etienne RB1 -> 4th, Pierce WR1 -> 8th, Reed 2nd -> 7th). Read as it stands, the shadow's string rules call
  // that a demotion and keep docking him after his projected return (dock3 = x0.4 for an RB) while his fill-ins keep
  // the starter's string. For weeks AFTER the current one the chart is read with every player who is out NOW put
  // back at the spot he held going into his last game (SIM_INJ_SIGNALS.chartPre, build_injury_signals.py from the
  // repo's chart history); a player who has not played this season goes back at his ADP rank in the room. The weeks
  // he misses are still priced by the injury layer, and the return ramp (first three games back .85 / .92 / .96
  // after 4+ missed, backtest_return_ramp.py) covers the games right after. Kill: window.SIM_NC_CHARTPRE = false.
  var _chartPreCache = {};
  function chartListFor(tm, pos, wk) {
    var d = typeof window !== 'undefined' ? window.SIM_DEPTH_2026 : null;
    var lst = d && d.teams && tm && d.teams[tm] ? d.teams[tm][pos] : null;
    if (!lst || !lst.length) return lst || null;
    if (window.SIM_NC_CHARTPRE === false || !_inj || !(_inj.week >= 1) || !(wk > _inj.week) || !_poolByNorm) return lst;
    var ck = tm + '|' + pos;
    if (_chartPreCache[ck]) return _chartPreCache[ck];
    var S = injSig(), CP = (S && S.chartPre) || {}, cw = _inj.week, moves = [], seen = {}, room = [];
    var keys = Object.keys(_poolByNorm);
    for (var i = 0; i < keys.length; i++) { var q = _poolByNorm[keys[i]]; if (q && !q.isDST && q.pos === pos && q.tm === tm && !seen[q.norm]) { seen[q.norm] = 1; room.push(q); } }
    var nowIdx = {}; for (var j = 0; j < lst.length; j++) nowIdx[norm(lst[j])] = j;
    room.forEach(function (q) {
      var m = _inj.map[q.norm];
      var outNow = (m && m.mult === 0 && m.from <= cw && m.to >= cw) || !!shadowOut(q, cw);
      if (!outNow) return;
      // only a player who is projected BACK this season is put back: one who is out for every remaining week never
      // takes a spot, and restoring him would price his full starter number as "lost" on top of a replacement the
      // chart already lists first (Dart / Winston: the fill-in's own starter prior + 85% of Dart's)
      var back = false; for (var w2 = cw + 1; w2 <= WEEKS && !back; w2++) if (injAdj(q, w2) > 0) back = true;
      if (!back) return;
      var pre = CP[q.norm], idx = null;
      if (pre && pre.pos === pos && normTeam(pre.tm) === normTeam(tm)) idx = pre.i;
      else {
        var rec = jsData().players ? jsData().players[q.norm] : null;
        if (!(rec && rec.g > 0) && q.adp != null) { idx = 0; room.forEach(function (t) { if (t !== q && t.adp != null && t.adp < q.adp) idx++; }); }   // no game this season: his ADP rank in the room
      }
      if (idx == null) return;
      var cur = nowIdx[q.norm];
      if (cur != null && cur <= idx) return;   // the chart already has him at or above that spot
      moves.push({ nk: q.norm, name: q.name, i: idx });
    });
    if (!moves.length) return (_chartPreCache[ck] = lst);
    var out = lst.filter(function (nm) { var nk = norm(nm); return !moves.some(function (mv) { return mv.nk === nk; }); });
    moves.sort(function (a, b) { return a.i - b.i; }).forEach(function (mv) { out.splice(Math.min(mv.i, out.length), 0, mv.name); });
    return (_chartPreCache[ck] = out);
  }
  function effectiveString(p, wk) {
    var d = typeof window !== 'undefined' ? window.SIM_DEPTH_2026 : null;
    if (!d || !d.teams) return null;
    var find = function (tm) {
      var lst = chartListFor(tm, p.pos, wk);
      if (!lst || !lst.length) return null;
      var avail = [];
      for (var i = 0; i < lst.length; i++) { var nk = norm(lst[i]); if (nk === p.norm || chartAvailable(lst[i], wk)) avail.push(nk); }
      for (var j = 0; j < avail.length; j++) if (avail[j] === p.norm) return Math.floor(j / (p.pos === 'WR' ? 3 : 1)) + 1;
      return null;
    };
    var s = find(p.tm);
    if (s == null && p.tmNow && p.tmNow !== p.tm) s = find(p.tmNow);
    if (s == null) { var tms = Object.keys(d.teams); for (var k = 0; k < tms.length && s == null; k++) if (tms[k] !== p.tm && tms[k] !== p.tmNow) s = find(tms[k]); }
    return s;
  }
  function depthString(p) {
    var d = typeof window !== 'undefined' ? window.SIM_DEPTH_2026 : null;
    if (!d || !d.teams) return null;
    var find = function (tm) {
      var lst = tm && d.teams[tm] && d.teams[tm][p.pos];
      if (!lst || !lst.length) return null;
      for (var i = 0; i < lst.length; i++) if (norm(lst[i]) === p.norm) return Math.floor(i / (p.pos === 'WR' ? 3 : 1)) + 1;
      return null;
    };
    var s = find(p.tm);
    if (s == null && p.tmNow && p.tmNow !== p.tm) s = find(p.tmNow);
    if (s == null) { var tms = Object.keys(d.teams); for (var j = 0; j < tms.length && s == null; j++) if (tms[j] !== p.tm && tms[j] !== p.tmNow) s = find(tms[j]); }
    return s;
  }
  // v2.15 learned season prior (data/ridge_prior.js, build_ridge_prior.py): rebuilds the harness feature vector live.
  // Feature conventions mirror backtest_season_long.build_table: ADP = consensus, unlisted / > 181 -> 181 + flag;
  // hist = 0.5 x 3-yr PPG + 0.5 x last-8 (half-PPR, raw); pick = rookie draft pick else 262; string = raw chart
  // (any team) 1 / 2 / 3+ / none; oppcal = the opportunity-prior blend when it applies; yr2 snap share for exp 1.
  function ridgePrior(p, wk, oppHalf) {
    var R = typeof window !== 'undefined' ? window.SIM_RIDGE_PRIOR : null, M = R && R.models ? R.models[p.pos] : null;
    if (!M || !R.feats) return null;
    var jsRec = jsData().players ? jsData().players[p.norm] : null;
    var h3 = (p.histPpg != null && p.histGames >= 8) ? p.histPpg : null, l8 = (jsRec && jsRec.l8 != null && jsRec.l8g >= 4) ? jsRec.l8 : null;
    var hist = (h3 != null && l8 != null) ? 0.5 * h3 + 0.5 * l8 : (l8 != null ? l8 : h3);
    var adpOk = p.adp != null && p.adp <= 181, ds = depthString(p), dsk = ds == null ? null : Math.min(3, ds);
    var spr = (p.exp === 1 && typeof window !== 'undefined' && window.SIM_SNAPS_PRIOR && typeof window.SIM_SNAPS_PRIOR[p.norm] === 'number') ? window.SIM_SNAPS_PRIOR[p.norm] : null;
    var f = { ladp: Math.log(adpOk ? p.adp : 181), no_adp: adpOk ? 0 : 1, hist: hist, h3: h3, l8: l8, age: p.age != null ? p.age : null, exp: p.exp != null ? p.exp : null, rookie: p.isRookie ? 1 : 0,
              lpick: Math.log(p.isRookie && p.draftPick != null ? p.draftPick : 262), str1: dsk === 1 ? 1 : 0, str2: dsk === 2 ? 1 : 0, str3: dsk === 3 ? 1 : 0, nostr: dsk == null ? 1 : 0, oppcal: oppHalf, yr2_late: spr,
              // v2.16: JM prospect score (data/jm_scores.js from the site's prospect model; missing -> median + indicator, like the harness)
              jm: (typeof window !== 'undefined' && window.SIM_JM && typeof window.SIM_JM[p.norm] === 'number') ? window.SIM_JM[p.norm] : null };
    var x = [], k;
    for (k = 0; k < R.feats.length; k++) { var v = f[R.feats[k]]; x.push(v == null || isNaN(v) ? null : v); }
    var z = [], j;
    for (j = 0; j < x.length; j++) z.push(x[j] == null ? M.med[j] : x[j]);
    for (j = 0; j < M.miss.length; j++) z.push(x[M.miss[j]] == null ? 1 : 0);
    var s = M.b;
    for (j = 0; j < z.length; j++) s += M.coef[j] * (z[j] - M.mu[j]) / M.sd[j];
    return Math.max(0.5, s);
  }
  function shadowAgeAdjust(p, halfPg) {
    if (!(halfPg >= 4) || (typeof window !== 'undefined' && window.SIM_SHADOW_AGE === false)) return { v: halfPg, tag: '' };
    var v = halfPg, tag = '';
    var rg = SHADOW_AGE.useReg && SHADOW_AGE.reg[p.pos];
    if (rg) { v = Math.exp(rg[0] + rg[1] * Math.log(v)) * rg[2]; tag += '+reg'; }
    var ac = SHADOW_AGE.useAge && SHADOW_AGE.age[p.pos];
    if (ac && p.age != null) {
      var ks = Object.keys(ac).map(Number).sort(function (a, b) { return a - b; });
      if (ks.length) { var a = Math.min(ks[ks.length - 1], Math.max(ks[0], Math.floor(p.age))); if (ac[a] != null) { v *= ac[a]; tag += '+age'; } }
    }
    var ec = SHADOW_AGE.useExp && SHADOW_AGE.exp[p.pos];
    if (ec && p.exp != null && p.exp >= 1 && p.exp <= 3 && ec[p.exp] != null) { v *= ec[p.exp]; tag += '+exp'; }
    return { v: v, tag: tag };
  }
  // ROOKIE LEVEL (backtest_age_exp.py, 2026-09-15): on the shipped base x snap trend, rookies with a game
  // played beat their projection in every week band (QB 1.13-1.15, RB 1.08-1.12, TE 1.01-1.17, WR 1.02-1.12)
  // - a level gap, not a slope: the season-to-date average lags a role that keeps growing (rookie RB
  // touches +38% by weeks 13-18). LOYO passes for QB (x1.12-1.15, -0.50%, 6/7) and RB (x1.12, -0.35%,
  // 5/7); TE lean (-0.16%), WR flat, 2nd-year nothing. Shipped shaved to x1.08 on the MODEL side only
  // (Clay stack + JS base; the market rate and this week's lines already see the rookie), and only once
  // he has a 2026 game (the tested rows). Kill: window.SIM_ROOKIE_LEVEL = false.
  var ROOKIE_LEVEL = { QB: 1.08, RB: 1.08 };
  function rookieLevel(p) {
    if (!p || !p.isRookie || !ROOKIE_LEVEL[p.pos]) return 1;
    if (typeof window !== 'undefined' && window.SIM_ROOKIE_LEVEL === false) return 1;
    var d = jsData(), rec = d.players && d.players[p.norm];
    return rec && rec.g >= 1 ? ROOKIE_LEVEL[p.pos] : 1;
  }
  // RB SNAP-USAGE BLEND (backtest_usage_context.py, 2026-09-15; Jack: "heavily take into consideration
  // snap counts, not just past production"). On the shipped base x snap trend, blending a snap-volume
  // projection into RB means cut LOYO MSE -0.65% (6/7, w .2-.3 every fold); valuing the snaps by field zone
  // x dropback x game script did WORSE (-0.48%) and needs post-season participation data, so the live
  // layer uses plain snaps: season-to-date snap share x team plays per game x league half-PPR points per
  // on-field RB snap (.315, participation 2018-25), rescaled to the sheet by the Clay stat mix. WR leaned
  // (-0.25%), TE flat. Shipped at w .15 after >= 3 games of 2026 snaps. Kill: window.SIM_RB_USAGE = false.
  var RB_USAGE = { w: 0.15, ptsPerSnap: 0.315, minWeeks: 3 };
  function rbUsagePg(p, wk) {
    if (!p || p.pos !== 'RB' || p.isDST) return null;
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_RB_USAGE === false) return null;
    var sn = wnd.SIM_SNAPS_2026 ? wnd.SIM_SNAPS_2026[p.name] : null;
    var pace = wnd.SIM_PACE_2026 && wnd.SIM_PACE_2026.teams ? wnd.SIM_PACE_2026.teams[p.tm] : null;
    if (!sn || !sn.w || !pace || !pace.cur || !(pace.cur.plays > 0)) return null;
    var wks = Object.keys(sn.w).map(Number).filter(function (w) { return w < wk && sn.w[w] > 0; });
    if (wks.length < RB_USAGE.minWeeks) return null;
    var avg = wks.reduce(function (t, w) { return t + sn.w[w]; }, 0) / wks.length;
    var halfPg = seasonPoints(p, PRESETS.half) / clayDiv(p);
    return { half: avg / 100 * pace.cur.plays * RB_USAGE.ptsPerSnap, halfPg: halfPg, share: avg, plays: pace.cur.plays, games: wks.length };
  }
  // LEARNED SHADOW (build_learned_shadow.py, 2026-09-16; Jack: "build the live shadow"). A LightGBM correction on
  // top of the hand-tuned stack, trained on actual - (rebuilt live layers) over 17,657 player-weeks 2019-25 with only
  // features the engine computes the same way: LOYO -0.94% (7/7), forward -0.78% (4/5) vs the hand stack
  // (backtest_learned_combo.py). The history can't replay the prop anchor, so it is SHADOW ONLY: weeklyProjection
  // returns lcCorr (half-PPR points, availability-scaled) and the lock rows log lcMean = shipped mean + lcCorr for
  // score_week.py to grade. Half-PPR, QB/RB/WR/TE, week 2+, players with a 2026 game. Kill: window.SIM_LEARNED_SHADOW = false.
  function lgbTree(n, x) {
    while (typeof n !== 'number') {
      var v = x[n[0]], isNan = v == null || v !== v;
      if (isNan && n[3] !== 2) { v = 0; isNan = false; }
      if ((n[3] === 1 && Math.abs(v) <= 1e-35) || (n[3] === 2 && isNan)) n = n[2] ? n[4] : n[5];
      else n = v <= n[1] ? n[4] : n[5];
    }
    return n;
  }
  function lgbExplain(M, x) {
    // Saabas path attribution: each split credits its feature with (child value - node value); needs node values ([6])
    var c = {}, bias = 0;
    for (var i = 0; i < M.trees.length; i++) {
      var n = M.trees[i];
      if (typeof n === 'number') { bias += n; continue; }
      bias += n[6] || 0;
      while (typeof n !== 'number') {
        var v = x[n[0]], isNan = v == null || v !== v;
        if (isNan && n[3] !== 2) { v = 0; isNan = false; }
        var nx = ((n[3] === 1 && Math.abs(v) <= 1e-35) || (n[3] === 2 && isNan)) ? (n[2] ? n[4] : n[5]) : (v <= n[1] ? n[4] : n[5]);
        var nv = typeof nx === 'number' ? nx : (nx[6] || 0);
        var f = M.features[n[0]];
        c[f] = (c[f] || 0) + nv - (n[6] || 0);
        n = nx;
      }
    }
    return { bias: bias, contrib: c };
  }
  function lgbPredict(M, x) {
    var s = 0;
    for (var i = 0; i < M.trees.length; i++) s += lgbTree(M.trees[i], x);
    return s;
  }
  var _lcPrac = { src: null, map: null };
  function learnedShadowCorr(p, wk, sc, slot, o) {
    var wnd = typeof window !== 'undefined' ? window : null;
    var M = wnd ? wnd.SIM_LEARNED_SHADOW : null;
    if (!M || !M.trees || !M.features || sc !== PRESETS.half || !slot) return null;
    if (p.isDST || ['QB', 'RB', 'WR', 'TE'].indexOf(p.pos) < 0 || !(wk >= 2) || !(o.iA > 0)) return null;
    var d = jsData(), rec = d.players && d.players[p.norm];
    if (!rec || !(rec.g >= 1)) return null;
    var f = {};
    f.pos_qb = p.pos === 'QB' ? 1 : 0; f.pos_rb = p.pos === 'RB' ? 1 : 0; f.pos_wr = p.pos === 'WR' ? 1 : 0; f.pos_te = p.pos === 'TE' ? 1 : 0;
    f.wk = wk; f.g = rec.g; f.ppg = rec.ppg; f.clay = o.clayPg;
    f.blend = jsBasePg(p, sc, o.clayPg); f.veg = o.mult;
    var fp = d.fpa && d.fpa[slot.opp], lg = d.lgFpa && d.lgFpa[p.pos];
    f.fpa_mult = 1;
    if (fp && lg && fp[p.pos] != null && fp._g) f.fpa_mult = 1 + Math.min(1, fp._g / JS_FPA_FULL_TRUST) * JS_FPA_ELASTICITY * (Math.min(1.25, Math.max(0.8, fp[p.pos] / lg)) - 1);
    f.snapmult = snapMult(p, wk);
    var sn = wnd.SIM_SNAPS_2026 ? wnd.SIM_SNAPS_2026[p.name] : null, sv = [];
    if (sn && sn.w) Object.keys(sn.w).map(Number).filter(function (w) { return w < wk; }).sort(function (a, b) { return a - b; }).forEach(function (w) { sv.push(+sn.w[w]); });
    var mean = function (a) { return a.reduce(function (t, v) { return t + v; }, 0) / a.length; };
    f.snap_std = sv.length ? mean(sv) : NaN; f.snap_l1 = sv.length ? sv[sv.length - 1] : NaN;
    f.snap_trend = sv.length >= 3 ? mean(sv.slice(-3)) - f.snap_std : NaN;
    var lm = (p.pos === 'QB' ? wnd.SIM_QB_TDLUCK_2026 : (p.pos === 'RB' ? wnd.SIM_RB_TDLUCK_2026 : wnd.SIM_REC_TDLUCK_2026)) || null, lr = lm ? lm[p.norm] : null;
    f.td_luck_pg = lr && lr.g ? (lr.xtd - lr.td) / lr.g : 0;
    f.td_luck_adj = tdLuckAdj(p, sc);
    var st = injuryState(), ie = st && st.map ? st.map[p.norm] : null;
    f.cond_mult = ie && ie.cond != null && wk >= ie.from && wk <= ie.to ? ie.cond : 1;
    var pr = wnd.SIM_PRACTICE_2026;
    if (_lcPrac.src !== pr) { _lcPrac.src = pr; _lcPrac.map = {}; if (pr && pr.players) Object.keys(pr.players).forEach(function (nm) { _lcPrac.map[norm(nm)] = pr.players[nm]; }); }
    var pe = pr && (!pr.week || +pr.week === +wk) ? _lcPrac.map[p.norm] : null;
    f.rep_q = pe && /questionable/i.test(pe.gs || '') ? 1 : 0;
    f.prac_dnp = pe && pe.pr === 'DNP' ? 1 : 0; f.prac_lim = pe && pe.pr === 'LP' ? 1 : 0;
    f.rookie_mult = rookieLevel(p);
    f.usage_half = o.rbU ? o.rbU.half : NaN;
    var pace = wnd.SIM_PACE_2026 && wnd.SIM_PACE_2026.teams ? wnd.SIM_PACE_2026.teams[p.tm] : null;
    f.plays_pg_std = pace && pace.cur && pace.cur.plays > 0 ? pace.cur.plays : NaN;
    f.weather_mult = weatherMult(p, wk, slot);
    var wx = wnd.SIM_WEATHER_2026, home = slot.home ? p.tm : slot.opp, wt = wx ? (wx[home] || wx[normTeam(home)]) : null, ww = wt ? (wt[wk] || wt[String(wk)]) : null;
    f.wind = ww && ww.wind != null ? +ww.wind : 0;
    f.pool_mult = p.pos !== 'QB' && o.iA > 1 ? o.iA : 1;
    f.qb_inherit_mult = p.pos === 'QB' && o.iA > 1 ? o.iA : 1;
    f.implied = slot.implied; f.spread = slot.implied - slot.oppImplied; f.game_total = slot.implied + slot.oppImplied;
    // the model learned on games PLAYED: condition the hand number on playing, then scale the correction back by P(plays)
    var iP = o.iA < 1 ? Math.max(0.05, Math.max(o.iA, Math.min(1, injPlay(p, wk)))) : 1;
    f.HAND = o.jsMean / iP;
    var x = M.features.map(function (k) { return f[k]; });
    if (o.explain) {
      var ex = lgbExplain(M, x), kk = (M.k != null ? M.k : 1) * iP, out = {};
      Object.keys(ex.contrib).forEach(function (k2) { out[k2] = ex.contrib[k2] * kk; });
      return { corr: (M.k != null ? M.k : 1) * lgbPredict(M, x) * iP, bias: ex.bias * kk, contrib: out, features: f };
    }
    var corr = (M.k != null ? M.k : 1) * lgbPredict(M, x) * iP;
    return isFinite(corr) ? corr : null;
  }
  function learnedShadowExplain(p, wk, schedule) {
    // half-PPR learned-shadow correction with per-feature contributions (for NOTES why lines)
    var wp = weeklyProjection(p, wk, PRESETS.half, schedule);
    if (!wp || !wp.why) return null;
    var w = wp.why;
    try { return learnedShadowCorr(p, wk, PRESETS.half, wp.slot, { clayPg: w.clayPg, mult: w.veg, rbU: w.usage, iA: w.iA, jsMean: w.jsMean, explain: true }); } catch (_) { return null; }
  }
  // FILL-IN EVIDENCE RESCALE (backtest_fillin_usage.py / fillin_usage.log, 2026-10-05; Jack: "players were only used because
  // the starter was out ... we need context around usage so far"). 2019-25 on the live form: once the starter is back, a backup
  // whose evidence holds fill-in games lands at RB .87 / WR .92 of projection next game (RB .69 when those games are half his
  // evidence). Fill-in game = he played while a same-team, same-position REGULAR (Clay half-PPR per game >= 5.0 and above his own)
  // sat; STALE = that regular is back for the week being projected (injury layer: plays with P >= .5). With 2+ stale games in his
  // evidence, those games' points (and xFP) are divided by the position's vacated-role boost (RB 1.26, WR 1.08) - the game count
  // stays (excluding or down-weighting them FAILED: the blend falls back to a Clay number that over-projects these backups too).
  // LOYO starter-back rows: next game -0.61% (7/7), rest of season 4+ games left -1.59% (7/7), no filter -1.76% (6/7); forward
  // 2022-25 4/4, 4/4, 3/4; whole board -0.05% / -0.12%. TE mixed (n~100) -> not applied. Fill-in games while the regular is
  // STILL out are untouched (that evidence is right). Kill: window.SIM_FILLIN = false. Backup engine.js.bak_pre_fillin_20261005.
  // ADP bands (fillin_usage.log section 5, Jack: "top 30, 60 and 100 are our main focus"): never fires in the top 30; RB better in
  // every band with rows; WRs drafted 31-100 keep producing after the starter returns (actual / projected 1.0-1.03) and the rescale
  // HURT their rest of season (+2.3% to +4.8%, n 9-43) -> the WR half only applies past ADP 100 (or no ADP): next game -0.77% (5/7,
  // fwd 3/4), rest of season -1.04% / -0.91% (4/7 - marginal).
  var FILLIN = { boost: { RB: 1.26, WR: 1.08 }, minAdp: { WR: 100 }, regMin: 5.0, minStale: 2, backP: 0.5 };
  var PRIOR_HEALTH = { a: 0.5, cap: 2.0, minHurt: 3, minHealthy: 4, pos: { WR: 1, TE: 1 }, src: 'backtest_qb_injury_usage.py --refine 2026-10-07' };
  // VOLUME CONTEXT (backtest_volume_context.py, 2026-10-07; Jack: "run the volume context test" -> "wire it"). The live number
  // over-credits team pass volume: WR / TE on the highest-attempt offenses scored .925 of it, the lowest .934 -> 1.034, and the part
  // that does not persist is SCRIPT-driven volume (attempts above neutral pass rate x plays) and realized volume on teams the
  // market expects to trail. Two model-side multipliers on WR / TE, team season-to-date (2+ team games), z across the 32 teams:
  //   1 - .03 x z(script excess att/g) for everyone, and 1 - .04 x z(att/g) when his team is this week's underdog (spread > 0).
  // 2019-25, top-150 weighted: stacked -0.33% whole board (7/7), WR/TE rows -0.75% (7/7), forward 2022-25 -0.50% (4/4); every
  // season better; mean move .4/g, max 2.2. Pace / neutral pass rate alone, favorites, volume-cleaned evidence all failed.
  // Data: SIM_PACE_2026.teams[t].cur.vol = {games, att, plays, nrate, exc} (build_pace_vol.py, run by pull_pace_tracker.py).
  // Kill: window.SIM_VOLUME_CTX = false. Backup engine.js.bak_pre_volume_20261007.
  var VOLUME_CTX = { eExc: 0.03, eAtt: 0.04, eBox: 0.04, boxAdp: 60, minGames: 2, lo: 0.8, hi: 1.2, pos: { WR: 1, TE: 1 } };
  // BOX COUNT FACED (backtest_box_context.py, 2026-10-07): WR / TE on offenses that see heavier boxes (defenders in the box, season to
  // date) out-produce the number: 1 + .04 z(box) -> -0.43% (6/7), forward -0.50% (4/4), board -0.19% on 2019-25 participation data;
  // the FTN screen agreed (-0.64% 4/4). Live source = FTN charting (cur.vol.box via build_pace_vol.py). Kill: window.SIM_BOX_CTX = false.
  // BASE BLEND FOR THE WEEKS AHEAD (backtest_base_remeasure.py + backtest_shadow_ros.py, 2026-10-07; Jack: "wire it"). The public
  // rest-of-season numbers (season PPG, VOR, season sims) ran on the Clay blend alone; the Clay-free shadow rate beats it 7.8% (7/7)
  // on rest of season and the 70/30 shadow + Clay blend is the most accurate next-game base (-1.05% 7/7, LOYO .6-.7 every fold).
  // For weeks after the current one the model number becomes w x shadow + (1 - w) x Clay-blend model; the book anchor, docks and
  // availability sit on top as before. scope 'later' = weeks ahead only (the current week keeps its anchored number);
  // 'all' = every week. Kill: window.SIM_BASE_BLEND = false; override: window.SIM_BASE_BLEND = { w: .7, scope: 'later' | 'all' }.
  // Backup engine.js.bak_pre_baseblend_20261007.
  var BASE_BLEND = { w: { QB: 1.0, RB: 1.0, WR: 1.0, TE: 1.0 }, wNow: { QB: 1.0, RB: 1.0, WR: 1.0, TE: 1.0 }, scope: 'all' };   // 2026-10-08 09:15 SEASON BLEND DROPPED too (Jack "get rid of the season blend"): backtest_shadow_ros.py section 12 - on the rest-of-season harness WITH the shadow's later-week structure, the wired weights (.5/.8/.7/0) were +1.81% WORSE than the shadow alone (top 150; rank .593 vs .607), QB .5 +6.4% (0/7), TE on Clay +16%; LOYO per-position picks QB 1.0 every fold, forward pick +0.9% worse than shadow alone. Every week = shadow alone. Restore the blend: window.SIM_BASE_BLEND = { w: { QB: .5, RB: .8, WR: .7, TE: 0 }, scope: 'all' } (wNow is bypassed by an override).   // 2026-10-08 (Jack "drop the blend on the weekly"): wNow = the CURRENT week's weight = shadow alone (Clay-free weekly number; cost on history ~+0.3% error, rank-neutral, project_clay_free_roadmap); later weeks keep w. Kill wNow only: window.SIM_WEEKLY_NO_BLEND = false (falls back to w).   // 2026-10-07 late: QB .5 (LOYO pick in 6/7 folds), RB .8 (5/7), from backtest_base_remeasure.py per-position fits   // 2026-10-07 evening: scope 'all' (Jack: "switch the current week to the blend too"); TE .3 (every cut of the re-measure had tight ends as Clay's: at .7 the TE number was +0.4% worse than the live number, at .3 -0.1%)   // 2026-10-08: TE 0 - the rank re-grade (backtest_te_blend_rank.py) had TE .3 at -.008 rho (2/7), forward picks 0 every fold, and the error pick did not hold out of sample; Clay-side live form alone for tight ends
  function volumeZ() {
    var d = (typeof window !== 'undefined' && window.SIM_PACE_2026) || null, T = d && d.teams; if (!T) return null;
    var keys = [], ex = [], at = [], bxKeys = [], bx = [];
    Object.keys(T).forEach(function (t) {
      var v = T[t].cur && T[t].cur.vol;
      if (v && v.games >= VOLUME_CTX.minGames && v.exc != null && v.att != null) { keys.push(t); ex.push(v.exc); at.push(v.att); }
      if (v && v.games >= VOLUME_CTX.minGames && v.box != null) { bxKeys.push(t); bx.push(v.box); }
    });
    if (keys.length < 16) return null;
    var z = function (arr) {
      var m = 0, i; for (i = 0; i < arr.length; i++) m += arr[i]; m /= arr.length;
      var s = 0; for (i = 0; i < arr.length; i++) s += (arr[i] - m) * (arr[i] - m); s = Math.sqrt(s / arr.length);
      if (!(s > 0)) return null;
      return arr.map(function (v) { return Math.max(-2.5, Math.min(2.5, (v - m) / s)); });
    };
    var zE = z(ex), zA = z(at); if (!zE || !zA) return null;
    var out = {}; keys.forEach(function (t, i) { out[t] = { exc: zE[i], att: zA[i] }; });
    var zB = bxKeys.length >= 16 ? z(bx) : null; if (zB) bxKeys.forEach(function (t, i) { if (out[t]) out[t].box = zB[i]; else out[t] = { box: zB[i] }; });
    return out;
  }
  function volumeMult(p, slot) {
    if (typeof window !== 'undefined' && window.SIM_VOLUME_CTX === false) return 1;
    if (!p || p.isDST || !VOLUME_CTX.pos[p.pos]) return 1;
    var Z = volumeZ(), z = Z && Z[p.tm]; if (!z) return 1;
    var m = 1;
    if (z.exc != null && z.att != null) {
      m = Math.max(VOLUME_CTX.lo, Math.min(VOLUME_CTX.hi, 1 - VOLUME_CTX.eExc * z.exc));
      if (slot && typeof slot.spread === 'number' && slot.spread > 0) m *= Math.max(VOLUME_CTX.lo, Math.min(VOLUME_CTX.hi, 1 - VOLUME_CTX.eAtt * z.att));
    }
    if (z.box != null && p.adp != null && p.adp <= VOLUME_CTX.boxAdp && !(typeof window !== 'undefined' && window.SIM_BOX_CTX === false)) m *= Math.max(VOLUME_CTX.lo, Math.min(VOLUME_CTX.hi, 1 + VOLUME_CTX.eBox * z.box));   // box: ADP <= 60 only (backtest_pressure_proxy.py 2: 61-150 was +0.17% worse, 0/7 LOYO)
    return m;
  }
  var _fillinCache = {};
  function fillinStale(p, wk) {
    var B = FILLIN.boost[p.pos];
    if (!B || p.isDST || !_poolByNorm || (typeof window !== 'undefined' && window.SIM_FILLIN === false)) return null;
    var ma = FILLIN.minAdp[p.pos]; if (ma != null && p.adp != null && p.adp <= ma) return null;
    var ck = p.norm + '|' + wk;
    if (_fillinCache[ck] !== undefined) return _fillinCache[ck];
    var d = jsData(), rec = d.players && d.players[p.norm], res = null;
    if (rec && rec.wks && rec.wks.length) {
      var lvl = function (q) { var dv = clayDiv(q); return dv > 0 ? seasonPoints(q, PRESETS.half) / dv : 0; };
      var mine = lvl(p), regs = [], keys = Object.keys(_poolByNorm), seen = {};
      for (var i = 0; i < keys.length; i++) {
        var q = _poolByNorm[keys[i]];
        if (!q || q === p || seen[q.norm] || q.isDST || q.pos !== p.pos || q.tm !== p.tm) continue;
        seen[q.norm] = 1;
        var lq = lvl(q); if (lq >= FILLIN.regMin && lq > mine) regs.push(q);
      }
      if (regs.length) {
        var back = regs.filter(function (q) { return injAdj(q, wk) >= FILLIN.backP; });
        var stale = [];
        rec.wks.forEach(function (w) {
          if (w >= wk) return;
          if (back.some(function (q) { var r = d.players[q.norm]; return !(r && r.wks && r.wks.indexOf(w) >= 0); })) stale.push(w);
        });
        if (stale.length >= FILLIN.minStale) res = { weeks: stale, B: B };
      }
    }
    _fillinCache[ck] = res;
    return res;
  }
  // points factor on his season-to-date evidence: the stale games' half-PPR points divided by the boost
  function fillinPtsF(p, wk) {
    var fs = fillinStale(p, wk); if (!fs) return 1;
    var rec = jsData().players[p.norm], wf = rec && rec.wf; if (!wf) return 1;
    var tot = 0, st = 0;
    Object.keys(wf).forEach(function (w) { var v = +wf[w]; if (+w >= wk || !isFinite(v)) return; tot += v; if (fs.weeks.indexOf(+w) >= 0) st += v; });
    return tot > 0 ? Math.max(0, (tot - st * (1 - 1 / fs.B)) / tot) : 1;
  }
  function jsBasePg(p, sc, clayPg, priorP, usage, ptsF, evid) {
    // evid (optional, 2026-10-07): { g, ppgHalf } replaces the season-to-date evidence - used for a QB inside a planned start
    // window whose season games so far are cameos (0-2 pts in relief), which otherwise drag his window number toward 0.
    // priorP (optional): prior strength in games. Live = JS_PRIOR_STRENGTH (5, twice backtested for the
    // Clay prior); the Clay-free shadow passes its own per-position strength (backtest_noclay_weekly.py).
    var PS = priorP != null ? priorP : JS_PRIOR_STRENGTH;
    var d = jsData();
    var rec = d.players && d.players[p.norm];
    if (!rec || !rec.g) return clayPg; // no 2026 sample yet -> pure Clay
    var pg = rec.pg || {};
    var ppg = rec.ppg; // half-PPR actuals -> league scoring via ACTUAL stat mix
    var gEv = rec.g;
    if (evid && evid.g != null) { if (!(evid.g > 0)) return clayPg; gEv = evid.g; ppg = evid.ppgHalf; }
    ppg += (sc.rec - 0.5) * (pg.rec || 0);
    ppg += (sc.pass_td - 4) * (pg.ptd || 0);
    ppg += (sc.pass_yd - 0.04) * (pg.py || 0);
    ppg += (sc.rush_yd - 0.1) * (pg.ry || 0);
    ppg += (sc.rec_yd - 0.1) * (pg.rcy || 0);
    ppg += (sc.rush_td - 6) * (pg.rtd || 0);
    ppg += (sc.rec_td - 6) * (pg.rctd || 0);
    if (p.pos === 'TE' && sc.bonus_rec_te) ppg += sc.bonus_rec_te * (pg.rec || 0);
    ppg = Math.max(0, ppg);
    if (ptsF != null && ptsF !== 1) ppg *= ptsF;   // live FILL-IN rescale (fillinPtsF)
    // v2.18 (shadow only): usage evidence. usage = { xfpPg, lam } -> the evidence is lam x xFP/g + (1 - lam) x points/g
    if (usage && usage.ptsScale != null) ppg *= usage.ptsScale;   // v2.24 Vegas-adjusted points evidence (shadow only)
    if (usage && usage.lam > 0 && usage.xfpPg != null) ppg = usage.lam * usage.xfpPg + (1 - usage.lam) * ppg;
    return (PS * clayPg + gEv * ppg) / (PS + gEv);
  }
  // v2.18 IN-SEASON USAGE EVIDENCE (backtest_inseason_usage.py, 2026-09-17; Jack: 'use the previous weeks information ... see how the
  // model does as the season goes on'). Early in the season the volume a player saw (xFP/g: targets, air yards, carries, red zone)
  // predicts better than the points he scored; points carry skill and take over as games accumulate. One smooth schedule per
  // position, lam(g) = max(floor, start - slope x (g - 1)), chosen LOYO: WR 1.0 / .08 / .25 (6 of 7 folds), RB 1.0 / .3 / .25 (4 of 7);
  // QB 0 (xFP worse at every horizon), TE 0 (no gain). Weighted top 150 vs the v2.17 shadow: -0.49% LOYO (6/7), -0.45% forward (5/5);
  // RB -0.54% (6/7), WR -0.72% (6/7); after 1 game -1.8%. Pure xFP replacement is +10% worse and a learned usage model +3-5% worse.
  // the team's projected starting QB (highest Clay season projection on the roster) is unavailable this week (injury / IR / Out), per the
  // same availability test the depth chart uses. A planned start window (qbWindow) is NOT an outage - Clay's receivers already price it.
  var _pqCache = {};
  // QB STARTER FLOOR (backtest_qb_shrink_cartrend.py, 2026-09-30; Jack: "go build the qb shrink"). Quarterbacks projected
  // BELOW the league's starting-QB mean scored well over it 2019-25 (projection 5-12 half-PPR: 1.39x; the top tier was
  // fair at 1.00), so a two-sided shrink lost at the top. One-sided: pred = mu + k x (base - mu) for bases under mu,
  // k = 0.70 in all seven held-out folds: QB MSE -2.33% (7/7 seasons), MAE -1.11%, low tier 1.39 -> 1.15, top tier
  // untouched; ranks unchanged (monotonic). mu = mean per-game level of the pool's top-32 QBs by season points.
  // Applied to the model side only (Clay stack + JS base), and NOT to a backup who is already inheriting the
  // starter's role (that boost covers the same gap). Kill: window.SIM_QB_FLOOR = false.
  var QB_FLOOR = { k: 0.70, topN: 32, min: 5 };
  var _qbMuCache = {};
  function qbFloorMu(sc, perGameDivOf) {
    var key = [sc.rec, sc.pass_td, sc.pass_yd, sc.rush_yd, sc.rush_td].join(',');
    var c = _qbMuCache[key];
    if (c && c.src === _poolByNorm) return c.mu;
    var lv = [], seen = [];
    if (_poolByNorm) Object.keys(_poolByNorm).forEach(function (k) {
      var q = _poolByNorm[k]; if (!q || q.pos !== 'QB' || q.isDST || seen.indexOf(q) >= 0) return;
      seen.push(q); lv.push(seasonPoints(q, sc) / (q.qbWindow ? (q.qbWindow.games || 17) : 17));
    });
    lv.sort(function (a, b) { return b - a; });
    var top = lv.slice(0, QB_FLOOR.topN), mu = top.length ? top.reduce(function (s, v) { return s + v; }, 0) / top.length : 0;
    _qbMuCache[key] = { src: _poolByNorm, mu: mu };
    return mu;
  }
  // REST-OF-SEASON VOLUME TILT (backtest_ros_quality_volume.py, 2026-09-30; the metric atlas). Standing at any week,
  // the per-game live number extrapolates raw volume over the horizon: QBs with the most pass attempts scored .963 of
  // it the rest of the way (fewest 1.143), TEs on pass-heavy teams .945 (run-heavy 1.186). LOYO on rest-of-season MSE:
  // QB attempt tilt e .06 -> -4.7% (6/7) on top of the floor; TE team neutral pass-rate tilt e .08 -> -4.0% (5/7).
  // Applied to weeks AFTER the current one only (the current week keeps its own graded number), ramping in over two
  // weeks ahead: mult = 1 - e x z, z = the player's attempts per game (QB) / his team's season-to-date neutral pass
  // rate (TE) standardized across the league, clipped to +-2. Model side (Clay stack + JS base). Kill:
  // window.SIM_ROS_TILT = false.
  var ROS_TILT = { QB: 0.06, TE: 0.08, minGames: 2, clip: 2 };
  var _rosZ = null;
  function rosTiltZ() {
    var wnd = typeof window !== 'undefined' ? window : null;
    if (_rosZ && _rosZ.src === _poolByNorm) return _rosZ;
    var out = { src: _poolByNorm, qb: {}, team: {} };
    var X = wnd && wnd.SIM_XFP_2026, vals = [], seen = [];
    if (X && _poolByNorm) Object.keys(_poolByNorm).forEach(function (k) {
      var q = _poolByNorm[k]; if (!q || q.pos !== 'QB' || seen.indexOf(q) >= 0) return; seen.push(q);
      var xr = X[q.norm]; if (!xr || !xr.w) return;
      var wk = Object.keys(xr.w).filter(function (w) { return xr.w[w] && xr.w[w][0] >= 10; });
      if (wk.length < ROS_TILT.minGames) return;
      var att = wk.reduce(function (s, w) { return s + xr.w[w][0]; }, 0) / wk.length;
      vals.push([q.norm, att]);
    });
    var z = function (arr) {
      if (arr.length < 8) return {};
      var m = arr.reduce(function (s, a) { return s + a[1]; }, 0) / arr.length, sd = Math.sqrt(arr.reduce(function (s, a) { return s + (a[1] - m) * (a[1] - m); }, 0) / arr.length) || 1, o = {};
      arr.forEach(function (a) { o[a[0]] = Math.max(-ROS_TILT.clip, Math.min(ROS_TILT.clip, (a[1] - m) / sd)); });
      return o;
    };
    out.qb = z(vals);
    var P = wnd && wnd.SIM_PACE_2026 && wnd.SIM_PACE_2026.teams, tv = [];
    if (P) Object.keys(P).forEach(function (tm) { var c = P[tm] && P[tm].cur; if (c && c.games >= ROS_TILT.minGames && typeof c.npr === 'number') tv.push([normTeam(tm), c.npr]); });
    out.team = z(tv);
    var pv = [];   // team plays a game (v2.28 RB volume tilt, shadow only)
    if (P) Object.keys(P).forEach(function (tm) { var c = P[tm] && P[tm].cur; if (c && c.games >= ROS_TILT.minGames && typeof c.plays === 'number') pv.push([normTeam(tm), c.plays]); });
    out.plays = z(pv);
    _rosZ = out; return out;
  }
  function rosTilt(p, wk) {
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_ROS_TILT === false || !_inj || !(_inj.week >= 1) || wk <= _inj.week) return 1;
    var e = ROS_TILT[p.pos]; if (!e || p.isDST) return 1;
    var Z = rosTiltZ(), z = p.pos === 'QB' ? Z.qb[p.norm] : Z.team[p.tm];
    if (typeof z !== 'number') return 1;
    var ramp = Math.min(1, (wk - _inj.week) / 2);   // one week ahead = half, two or more = full
    return 1 - e * ramp * z;
  }
  function qbFloor(base, sc) {
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_QB_FLOOR === false) return base;
    var mu = qbFloorMu(sc);
    if (!(mu > 0) || !(base >= QB_FLOOR.min) || base >= mu) return base;
    return mu + QB_FLOOR.k * (base - mu);
  }
  function teamPrimaryQbOut(tm, wk) {
    if (!tm || !_poolByNorm) return false;
    var c = _pqCache[tm];
    if (!c || c.src !== _poolByNorm) {
      var best = null, bp = -1;
      Object.keys(_poolByNorm).forEach(function (k) { var q = _poolByNorm[k]; if (!q || q.pos !== 'QB' || q.tm !== tm) return; var v = seasonPoints(q, PRESETS.half); if (v > bp) { bp = v; best = q; } });
      c = _pqCache[tm] = { src: _poolByNorm, qb: best };
    }
    if (!c.qb) return false;
    if (c.qb.qbWindow) return false;   // a planned start window is not an outage
    return !chartAvailable(c.qb.name, wk);
  }
  // standardized Vegas game total for a team's game this week (z across the week's games); null when the week has < 6 priced games
  var _gtzCache = {};
  function gameTotalZ(schedule, wk, tm) {
    var bt = schedule && schedule.byTeam; if (!bt || !bt[tm] || !bt[tm][wk]) return null;
    var c = _gtzCache[wk];
    if (!c || c.src !== bt) {
      var seen = {}, v = [];
      Object.keys(bt).forEach(function (t) { var s0 = bt[t][wk]; if (!s0 || s0.implied == null || s0.oppImplied == null) return; var k = s0.gameKey || [t, s0.opp].sort().join('@'); if (seen[k]) return; seen[k] = 1; v.push(s0.implied + s0.oppImplied); });
      var m = 0, sd = 0; v.forEach(function (x) { m += x; }); m = v.length ? m / v.length : 0; v.forEach(function (x) { sd += (x - m) * (x - m); }); sd = v.length ? Math.sqrt(sd / v.length) : 0;
      c = _gtzCache[wk] = { src: bt, n: v.length, m: m, sd: sd };
    }
    if (c.n < 6 || !(c.sd > 0)) return null;
    var s1 = bt[tm][wk]; return Math.max(-2.5, Math.min(2.5, ((s1.implied + s1.oppImplied) - c.m) / c.sd));
  }
  // v2.24 VEGAS-ADJUSTED EVIDENCE (backtest_evidence_clean.py, 2026-09-17; Jack: 'lets build the in season evidence test'). The points a
  // player has scored this season were scored in specific game environments; the forecast multiplies by this week's Vegas multiplier,
  // so the evidence it multiplies should be environment-neutral. Each past game is divided by the Vegas multiplier the model gave THAT
  // game (same elasticities, no new number). Top 150 weighted, final week dropped: -0.30% (6/7 seasons), rank +.0026, QB -0.69% (6/7),
  // RB -0.43% (6/7), weeks 10-to-playoffs -0.45% (6/7); on the 14% of rows it moves by 0.3+ points: -1.36% (6/7). The FPA half of the
  // matchup adds nothing (multiplier too small); dropping / rescaling partial games and teammate-context weights all FAIL.
  // Returns the ratio adjusted / raw points per game (half-PPR), or null.
  function shadowVegasScale(p, wk, schedule) {
    if (typeof window !== 'undefined' && window.SIM_NC_VEGEV === false) return null;
    var k = NC_SHADOW.vegEvK; if (!k) return null;
    var d = jsData(), rec = d.players && d.players[p.norm], bt = schedule && schedule.byTeam && schedule.byTeam[p.tm];
    if (!rec || !rec.wf || !bt) return null;
    var raw = 0, adj = 0, n = 0;
    Object.keys(rec.wf).forEach(function (w) {
      if (+w >= wk) return; var pts = +rec.wf[w]; if (!isFinite(pts)) return;
      var s0 = bt[w] || bt[+w], m = s0 && s0.implied != null ? vegasMult(s0.implied, schedule.avgImplied, p.pos) : 1;
      raw += pts; adj += pts / Math.pow(Math.max(0.6, Math.min(1.6, m)), k); n++;
    });
    if (!n || !(raw > 0)) return null;
    return Math.max(0.75, Math.min(1.35, adj / raw));
  }
  // LIVE USAGE EVIDENCE (backtest_usage_live.py, 2026-09-29; Jack: "we should definitely factor in route share, snap
  // share etc"). Until now the live model only read the TREND of snaps / TE routes (+ the RB snap-volume blend); the
  // LEVEL of a receiver's role was shadow-only. 10,952 player-weeks 2019-25 on the live form, every season held out:
  // evidence = lam x usage-implied points per game + (1 - lam) x actual points per game, usage-implied = a linear mix
  // of xFP/g (targets, air yards, carries), route rate and snap share. WR MSE -0.76% (7 of 7 seasons), top-150 weighted
  // -1.79%, after 2 games -3.7%; TE -0.58% (5/7), top-150 -1.14% (TE had too few rows to test games 1-3, so it starts
  // at game 4). Snap share carries most of it, route rate adds little once snaps + targets are in. RB 4/7 = not added
  // (RB_USAGE already blends snap volume). Held-out weights came out 1.0 / 1.0 / .7 / .7 / .55 / .33 - shipped SHAVED.
  // TD-luck is scaled by (1 - lam): usage evidence carries no touchdown luck to take back out (the v2.22 lesson).
  // Kill: window.SIM_LIVE_USAGE = false.
  var LIVE_USAGE = {
    WR: { c: [0.37, 0.53, 0.005, 0.050], lam: [[1, 0.8], [2, 0.8], [3, 0.6], [5, 0.6], [8, 0.5], [99, 0.3]] },
    // TE FROM GAME 1 (backtest_qb_injury_usage.py 3a, 2026-10-07; Jack: "increase the usage in the projections"): .3 from the first
    // game instead of 0 through 3 games. 2019-25 live form: TE next game -0.09% (5/7), rest of season -0.26% (5/7), forward 3/4;
    // .5 and heavier WR schedules were worse everywhere (WR held-out weights +0.9% ROS, 0/7). Kill: window.SIM_TE_USE_G1 = false.
    TE: { c: [-1.87, 0.47, 0.023, 0.057], lam: [[99, 0.3]], lamOld: [[3, 0], [5, 0.3], [8, 0.3], [99, 0.3]] }
  };
  // OWN BANGED-UP GAMES x0.5 IN THE USAGE INPUTS (same backtest, 3b; Jack: "make sure usage is hyper aware of situation"): a game he
  // played while listed Questionable, with a Limited / DNP final practice, or at < 75% of his own median snap share describes his role
  // less well. xFP and snap share from those games get weight .5 (route rate untouched, points evidence untouched - 2c: docking the
  // points was worse on the next game). 2019-25: WR/TE rest of season -0.62% (6/7, forward 4/4), next game -0.03%; x0 was better on
  // ROS but worse next game and in ADP 61-100. Kill: window.SIM_HURT_USAGE = false.
  var HURT_USAGE = { w: 0.5, snapFrac: 0.75 };
  function hurtGameW(p, k, wk, sn) {
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_HURT_USAGE === false) return 1;
    var S = injSig(), r = S && S.prac && S.prac[k] ? S.prac[k][p.norm] : null, hurt = false;
    if (r) {
      if (r.gs === 'Questionable') hurt = true;
      var sq = typeof r.seq === 'string' ? r.seq.split('-') : [], last = sq.length ? sq[sq.length - 1] : '';
      if (last === 'LP' || last === 'DNP') hurt = true;
    }
    if (!hurt && sn && sn.w && typeof sn.w[k] === 'number') {
      var vals = [];
      Object.keys(sn.w).forEach(function (q) { if (+q < wk && typeof sn.w[q] === 'number' && sn.w[q] > 0) vals.push(sn.w[q]); });
      if (vals.length >= 3) {
        vals.sort(function (a, b) { return a - b; });
        var med = vals.length % 2 ? vals[(vals.length - 1) / 2] : 0.5 * (vals[vals.length / 2 - 1] + vals[vals.length / 2]);
        if (sn.w[k] > 0 && sn.w[k] < HURT_USAGE.snapFrac * med) hurt = true;
      }
    }
    return hurt ? HURT_USAGE.w : 1;
  }
  function liveUsage(p, wk, sc) {
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_LIVE_USAGE === false) return null;
    var cfg = LIVE_USAGE[p.pos]; if (!cfg) return null;
    var d = jsData(), rec = d.players && d.players[p.norm]; if (!rec || !rec.g) return null;
    var lamS = (p.pos === 'TE' && wnd.SIM_TE_USE_G1 === false && cfg.lamOld) ? cfg.lamOld : cfg.lam;
    var lam = 0; for (var i = 0; i < lamS.length; i++) { if (rec.g <= lamS[i][0]) { lam = lamS[i][1]; break; } }
    if (!(lam > 0)) return null;
    var xr = wnd.SIM_XFP_2026 ? wnd.SIM_XFP_2026[p.norm] : null, sn = wnd.SIM_SNAPS_2026 ? wnd.SIM_SNAPS_2026[p.name] : null, rr = wnd.SIM_ROUTES_2026 ? wnd.SIM_ROUTES_2026[p.norm] : null;
    if (!xr || !xr.w || !sn || !sn.w || !rr) return null;   // all three or nothing: the mix was fit on rows that had them all
    var H = PRESETS.half, xh = 0, xs = 0, nX = 0, wX = 0, sSum = 0, nS = 0, wS = 0, rSum = 0, nR = 0, nHurt = 0;
    var fsU = fillinStale(p, wk);   // FILL-IN rescale: stale games' xFP / boost, like their points
    Object.keys(xr.w).forEach(function (k) {
      if (+k >= wk) return; var r = xr.w[k]; if (!r) return; nX++;
      var fk = (fsU && fsU.weeks.indexOf(+k) >= 0) ? 1 / fsU.B : 1;
      var hw = hurtGameW(p, +k, wk, sn); if (hw < 1) nHurt++; wX += hw;   // banged-up game: half weight in the usage inputs
      xh += hw * fk * (H.rec * (r[1] || 0) + H.rec_yd * (r[2] || 0) + H.rec_td * (r[3] || 0) + H.rush_yd * (r[5] || 0) + H.rush_td * (r[6] || 0));
      var xsk = sc.rec * (r[1] || 0) + sc.rec_yd * (r[2] || 0) + sc.rec_td * (r[3] || 0) + sc.rush_yd * (r[5] || 0) + sc.rush_td * (r[6] || 0);
      if (p.pos === 'TE' && sc.bonus_rec_te) xsk += sc.bonus_rec_te * (r[1] || 0);
      xs += hw * fk * xsk;
    });
    Object.keys(sn.w).forEach(function (k) { if (+k < wk && typeof sn.w[k] === 'number') { var hw = hurtGameW(p, +k, wk, sn); sSum += hw * sn.w[k]; nS++; wS += hw; } });
    Object.keys(rr).forEach(function (k) { if (+k < wk && typeof rr[k] === 'number') { rSum += rr[k]; nR++; } });
    if (!nX || !nS || !nR) return null;
    // gN: games with no xFP row still count as zero-usage games (as before); the hurt games count at their weight
    var gN = Math.max(rec.g, nX) - nX + wX, c = cfg.c, snapAvg = wS > 0 ? sSum / wS : sSum / nS;
    var uHalf = Math.max(0, c[0] + c[1] * (xh / gN) + c[2] * (rSum / nR) + c[3] * snapAvg);
    var toSheet = xh > 0 ? xs / xh : 1;   // half-PPR -> this scoring sheet, by his own expected stat mix
    return { xfpPg: uHalf * toSheet, lam: lam, half: uHalf, snap: snapAvg, route: rSum / nR, xfpHalf: xh / gN, hurtG: nHurt };
  }
  function shadowUsage(p, wk, sc) {
    if (typeof window !== 'undefined' && window.SIM_NC_USAGE === false) return null;
    var sch = NC_SHADOW.usageLam[p.pos]; if (!sch) return null;
    var X = typeof window !== 'undefined' ? window.SIM_XFP_2026 : null, xr = X && X[p.norm], d = jsData(), rec = d.players && d.players[p.norm];
    if (!xr || !xr.w || !rec || !rec.g) return null;
    var tot = 0, nW = 0;
    Object.keys(xr.w).forEach(function (k) {
      if (+k >= wk) return; var r = xr.w[k]; if (!r) return; nW++;
      tot += sc.rec * (r[1] || 0) + sc.rec_yd * (r[2] || 0) + sc.rec_td * (r[3] || 0) + sc.rush_yd * (r[5] || 0) + sc.rush_td * (r[6] || 0);
      if (p.pos === 'TE' && sc.bonus_rec_te) tot += sc.bonus_rec_te * (r[1] || 0);
    });
    if (!nW) return null;
    var gN = Math.max(rec.g, nW), lam = Math.max(sch[2], sch[0] - sch[1] * Math.max(0, rec.g - 1));
    return { xfpPg: tot / gN, lam: lam };
  }
  // STAT-LINE USAGE UPDATE (backtest_comp_usage.py, 2026-09-20; Jack: 'usage should be involved in our sims').
  // compsWk is the PRESEASON Clay stat line per game x matchup x availability for all 18 weeks - the fantasy mean learns in
  // season, the stat lines that grade against the books never did (W2: the model faded Coker / Vele / Douglas, full-time
  // receivers the August line still called part-timers). Per stat: post = (P x prior + g x (lam x usage-expected per game +
  // (1 - lam) x actual per game)) / (P + g), usage = SIM_XFP_2026 (targets x cp x (air + xYAC), carries x field position),
  // actual = SIM_2026 pg. Walk-forward 2019-25 vs the static line: rush yds -13.8% MSE (7/7, fwd -15.1% 5/5), receptions
  // -10.9% (7/7, fwd -11.2%; the one stat with a real historical Clay line), rec yds -8.0% (7/7, fwd -8.4%); after ONE game
  // -1.7 to -2.2%, growing every bucket; when the two numbers disagree by 20%+ the actual lands on the updated side ~2 in 3.
  // Best P was 2-5 everywhere and flat; P 5 shipped (the yardage prior in the backtest is a proxy weaker than Clay's real
  // line, which biases P low; 5 = the live fantasy blend). TDs untouched (the TD-luck layers own them). OUTPUT = compsU,
  // a parallel set: comps stays as it was for the prop anchor + the old grading; vs_books_week.py grades both every week.
  // Kill: window.SIM_COMP_USAGE = false.
  var COMP_USAGE = { P: 5, lam: { ry: 0.25, rec: 0.5, rcy: { RB: 0.75, WR: 0.25, TE: 0.25 } }, src: 'backtest_comp_usage.py 2026-09-20' };
  function compUsage(p, wk) {
    if (typeof window !== 'undefined' && window.SIM_COMP_USAGE === false) return null;
    if (p.pos !== 'QB' && p.pos !== 'RB' && p.pos !== 'WR' && p.pos !== 'TE') return null;
    var d = jsData(), rec = d.players && d.players[p.norm]; if (!rec || !rec.g || !rec.pg) return null;
    var X = typeof window !== 'undefined' ? window.SIM_XFP_2026 : null, xr = X && X[p.norm], u = null;
    if (xr && xr.w) {
      var nW = 0, t = { ry: 0, rec: 0, rcy: 0 }, qb = p.pos === 'QB';
      Object.keys(xr.w).forEach(function (k) {
        if (+k >= wk) return; var r = xr.w[k]; if (!r) return; nW++;
        if (qb) t.ry += r[4] || 0;                                   // QB rows: [att, xPassYds, xPassTD, carries, xRushYds, xRushTD, xInt]
        else { t.rec += r[1] || 0; t.rcy += r[2] || 0; t.ry += r[5] || 0; }
      });
      if (nW) { var gN = Math.max(rec.g, nW); u = { ry: t.ry / gN, rec: t.rec / gN, rcy: t.rcy / gN }; }
    }
    return { g: rec.g, a: rec.pg, u: u };
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
  // Line scale (2026-10-07). Prop lines are medians, so the anchor used to
  // divide every line by the player's closed-form gamma median/mean ratio
  // (gammaMedRatio, 0.75-1.0 -> x1.05-x1.33, median x1.14) to put it on
  // mean scale. Four weeks of locks (968 anchored QB/RB/WR/TE player-weeks,
  // W1-4 2026) say the books already shade for the skew: actual/line ran
  // 1.03-1.06 on every stat except receiving yards (WR 1.20 / RB 1.23), and
  // the inflated market sat +0.60 pts HIGH (MAE 4.89) while the face-value
  // lines sat -0.40 (MAE 4.66, tied with the clean model). At face value the
  // tuned-weight blend improved MAE on all four positions with within-
  // position rank order flat, so lines now enter at face value times a
  // per-stat scale (default 1.0 everywhere; rcy 1.1-1.2 traded MAE for
  // bias and was not taken). window.SIM_PROP_LINE_SCALE = {rcy: 1.1}
  // overrides per stat; window.SIM_PROP_GAMMA_RATIO = true restores the old
  // divisor. Kickers keep the gamma divisor (one line; kLevel owns their level).
  var PROP_LINE_SCALE = { py: 1.0, ptd: 1.0, ry: 1.0, rec: 1.0, rcy: 1.0 };
  function propLineScale(k) {
    var o = (typeof window !== 'undefined' && window.SIM_PROP_LINE_SCALE) || null;
    if (o && typeof o[k] === 'number' && o[k] > 0) return o[k];
    return PROP_LINE_SCALE[k] != null ? PROP_LINE_SCALE[k] : 1.0;
  }

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
    // Skill-position lines: face value x per-stat scale (see PROP_LINE_SCALE);
    // the gamma divisor only on the opt-in switch.
    var useGamma = (typeof window !== 'undefined' && window.SIM_PROP_GAMMA_RATIO === true);
    function lineMean(k, line) { return useGamma ? line / medRatio : line * propLineScale(k); }
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
    // Non-TD stats: line (face value x scale, see PROP_LINE_SCALE) where
    // posted, model comp (mean scale) where not. Gate: posted lines must
    // cover >=60% of the model's non-TD points or we don't anchor at all.
    var covered = 0, modelNonTd = 0, fp = 0;
    PROP_STATS.forEach(function (k) {
      var mPts = (compsWk[k] || 0) * scv(k);
      modelNonTd += mPts;
      var line = propConsensus(entry, k);
      if (line != null && line > 0) {
        covered += mPts;
        fp += lineMean(k, line) * scv(k);
      } else {
        fp += mPts;
      }
    });
    if (!(modelNonTd > 0) || covered / modelNonTd < PROP_COVERAGE_MIN) return null;
    // Pass TDs: the posted line when there is one, else the model.
    var ptdLine = propConsensus(entry, 'ptd');
    fp += (ptdLine != null && ptdLine > 0 ? lineMean('ptd', ptdLine) : (compsWk.ptd || 0)) * sc.pass_td;
    // Rush+rec TDs: devigged anytime-TD odds -> Poisson mean, split rush/rec
    // by the model's own ratio; raw 0.5 rtd/rctd novelty lines are ignored.
    var atd = propConsensus(entry, 'atd');
    var rtdM = compsWk.rtd || 0, rctdM = compsWk.rctd || 0;
    if (atd != null) {
      // Devig: flat PROP_ATD_JUICE unless the weekly tuner has fit a
      // per-position factor (SIM_TUNING.atdJuice, 2026-10-07: RB books ran
      // ~11% hot on TD counts W1-4 — Σλ 120 vs 107 scored at 1.06).
      var TUj = (typeof window !== 'undefined' && window.SIM_TUNING && window.SIM_TUNING.atdJuice) || null;
      var juice = (TUj && typeof TUj[p.pos] === 'number' && TUj[p.pos] >= 1) ? TUj[p.pos] : PROP_ATD_JUICE;
      var pTd = Math.min(0.85, Math.max(0.01, amToProb(atd) / juice));
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
        && fp - base >= BELOW_GAP && fp >= BELOW_STARTER_MIN) w = Math.min(w, Math.max(0, TU.belowW));   // min: belowW only ever LOWERS the weight (RB/TE propW sits under it since 2026-09-29)
    // Mirror image (Jack 2026-10-07, tuner `aboveW`): when the CLEAN model
    // sits ABOVE the face-value market on a WR by >= ABOVE_GAP, W1-4 2026
    // had the market closer 67% of the time (n=94, every week; MAE-best
    // weight 1.0) — all WR3/WR4s the model likes more than the books
    // (pecking-order optimism). A separate, HIGHER market weight applies
    // there. WR only: RB/TE/QB above-market rows showed no side (model
    // closer 41-54%). Not on WR1-level markets (>= ABOVE_MARKET_MAX): there
    // the model was the closer side (5/8, JSN/St. Brown/Jefferson booms) and
    // Jack's rule is never to dock elite players. max(): only ever RAISES.
    if (TU && typeof TU.aboveW === 'number' && ovMap[p.name] == null
        && ABOVE_POS[p.pos] && base - fp >= ABOVE_GAP && fp < ABOVE_MARKET_MAX) w = Math.max(w, Math.min(1, TU.aboveW));
    p._propWUsed = w;
    return w * fp + (1 - w) * base;
  }
  var BELOW_GAP = 3.0;          // half-PPR pts the market must sit above the clean model
  var BELOW_STARTER_MIN = 8.0;  // market-implied mean that counts as a starter
  var ABOVE_GAP = 1.0;          // half-PPR pts the clean model must sit above the market
  var ABOVE_POS = { WR: 1 };    // positions the aboveW rule applies to
  var ABOVE_MARKET_MAX = 12.0;  // market-implied mean at or above this = WR1 market, rule off

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
      var perGameDiv = p.qbWindow ? p.qbWindow.games : clayDiv(p);
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
  // BANGED-UP DOCKS (backtest_banged_up.py, 2026-09-15). Final-report designation x latest practice:
  //   play = P(plays) by position, nflverse injuries x snap counts 2019-25, players averaging 40%+ of
  //          snaps (Doubtful 1%, Q+DNP 48%, Q+LP 72% - QB 47%, Q+FP 87%), shrunk K=50 to the pooled rate;
  //   cond = production when he plays vs healthy, same position + week band (Q+FP .91, Q+LP .88,
  //          Q+DNP .78; snap share .96/.92/.90), shrunk K=150, shaved halfway for line overlap.
  // mult = play x cond replaces the 09-09 judgment docks (Doubtful x0.5, Q+DNP x0.75, Q+LP/FP none) only
  // when the CURRENT week's NFL report carries the status; the prop anchor undoes only `play`.
  // Kill: window.SIM_BANGED = false.
  var BANGED = {"Q-FP":{"QB":{"play":0.824,"cond":0.951},"RB":{"play":0.898,"cond":0.952},"WR":{"play":0.885,"cond":0.961},"TE":{"play":0.863,"cond":0.955}},"Q-LP":{"QB":{"play":0.539,"cond":0.941},"RB":{"play":0.715,"cond":0.942},"WR":{"play":0.763,"cond":0.943},"TE":{"play":0.765,"cond":0.933}},"Q-DNP":{"QB":{"play":0.424,"cond":0.891},"RB":{"play":0.444,"cond":0.877},"WR":{"play":0.523,"cond":0.884},"TE":{"play":0.497,"cond":0.891}},"D":{"QB":{"play":0.006,"cond":1.0},"RB":{"play":0.005,"cond":1.0},"WR":{"play":0.02,"cond":1.0},"TE":{"play":0.006,"cond":1.0}}};
  // ---------- INJURY SIGNALS (2026-10-01, Jack: "practice reports of all teams everyday ... what kind of injury
  // they have ... the big accounts ... sportsbooks adding lines for the players or not") ----------
  // Data: data/sim_injury_signals.js (build_injury_signals.py, end of refresh_data.py) = Sleeper's diagnosis
  // (body part + notes), the official practice report by week with the day-by-day sequence, and the availability
  // read off the news feed. Four pieces, each with its own kill switch:
  //  1. INJURY TYPE -> plays this week (backtest_injury_type_play.py, 1,641 Questionable starter rows 2019-25):
  //     play odds by designation x practice x position re-fit with recent seasons weighted (half-life 3; Q + limited
  //     fell 76% -> 65% since 2023, Q + no practice rose 44% -> 54%) plus a shrunk logit shift by injury group
  //     (Q + limited: calf / quad / back / groin / hip play more, hamstring / shoulder / concussion less; Q + no
  //     practice: illness plays, ankle sits). Forward test (train on earlier seasons) Brier -1.26%, 4/4 seasons;
  //     leave-one-season-out -0.86%, 5/7. Kill: window.SIM_INJ_TYPE = false.
  //  2. AVAILABILITY CURVE v2 (backtest_avail_recency.py): P(misses the next game | missed k) by position, with a
  //     logit shift by the injury on his report (straight to IR without ever being listed = 'unlisted' is the
  //     longest; concussion the shortest). Forward Brier next game -2.50%, next four -3.58% (4/4); LOSO -2.34% /
  //     -3.82% (6/7). Weighting recent seasons did NOT help the curve (+0.1%; missed 4+ -> 80% miss the next in
  //     2019-22, 84% in 2023-25), so it is fit on all seven. Kill: window.SIM_AVAIL_V2 = false.
  //  3. NEWS WINDOWS: a reported timeline ("out 4-6 weeks", "out until week 7", "out for the season") zeroes those
  //     weeks and lands softly after the reported minimum; "ruled out" zeroes the week; "expected to play" lifts a
  //     Questionable dock to NEWS_PLAY. News never acts alone: the player's own designation has to agree (a
  //     healthy tag, a practicing Questionable or a game played since the report voids it - weeks 1-3 had two
  //     wrong timeline items, both on players Sleeper listed healthy). Single-week reads weeks 1-3: ruled out
  //     played 1/25, expected to play 15/16. A manual IN_SEASON_OUT_OVERRIDES entry wins unless the news is
  //     newer than the entry's date. Kill: window.SIM_NEWS_WINDOWS = false.
  //  4. SEASON-ENDING DIAGNOSIS: Sleeper body part ACL / Achilles on a player who has played this season and is
  //     on a reserve list or Out = out through week 18 (the generic rule gave Achane four weeks and a ramp).
  //     Kill: window.SIM_DX_SEASON = false.
  var INJ_PLAY = { 'Q-FP': { QB: 0.830, RB: 0.898, WR: 0.868, TE: 0.857 }, 'Q-LP': { QB: 0.528, RB: 0.715, WR: 0.737, TE: 0.750 }, 'Q-DNP': { QB: 0.466, RB: 0.481, WR: 0.537, TE: 0.523 } };
  var INJ_TYPE = { 'Q-FP': { knee: 0.24, concussion: -0.26 },
                   'Q-LP': { calf: 0.38, quad: 0.27, back: 0.26, groin: 0.23, hip: 0.21, hamstring: -0.22, shoulder: -0.26, concussion: -0.30 },
                   'Q-DNP': { illness: 0.32, ankle: -0.25 } };
  var NEWS_PLAY = 0.90;
  var AVAIL_POS = { QB: [0.691, 0.741, 0.793, 0.836, 0.786, 0.889, 0.911, 0.870], RB: [0.677, 0.694, 0.719, 0.722, 0.765, 0.863, 0.821, 0.909],
                    WR: [0.609, 0.712, 0.764, 0.746, 0.727, 0.868, 0.874, 0.926], TE: [0.634, 0.772, 0.799, 0.805, 0.720, 0.857, 0.843, 0.867] };
  var AVAIL_GRP = { ankle: [0, 0.22, -0.52], concussion: [-0.59, 0, -0.24], foot: [0.15, 0, 0.62], hamstring: [0.23, -0.20, -0.71], hand: [0, 0, -0.13],
                    knee: [0.19, -0.21, 0.16], neck: [0, 0, 0.43], shoulder: [0, -0.55, 0.23], unlisted: [0.20, 0.55, 0.44] };
  function _lgt(p) { p = Math.min(0.995, Math.max(0.005, p)); return Math.log(p / (1 - p)); }
  function _sgm(z) { return 1 / (1 + Math.exp(-z)); }
  function injSig() { return (typeof window !== 'undefined' && window.SIM_INJ_SIGNALS) || null; }
  // injury group for a week: the official report's own text, else Sleeper's body part
  function injGroup(p, wk) {
    var S = injSig(); if (!S) return '';
    var r = S.prac && S.prac[wk] ? S.prac[wk][p.norm] : null;
    if (r && r.g) return r.g;
    var b = S.body ? S.body[p.norm] : null;
    return (b && b.g) || '';
  }
  // how many books have a yardage / reception line up for him this week (0 = none; null = no props file for the week)
  var _luCache = {};
  function linesUp(p, wk) {
    var B = (typeof window !== 'undefined' && window.BETTING_2026 && window.BETTING_2026.weeklyProps) || null;
    if (!B || !B[wk]) return null;
    var c = _luCache[wk];
    if (!c || c.src !== B[wk]) {
      c = _luCache[wk] = { src: B[wk], m: {} };
      Object.keys(B[wk]).forEach(function (nm) {
        var rec = B[wk][nm], n = 0;
        Object.keys(rec || {}).forEach(function (bk) { var v = rec[bk]; if (v && typeof v === 'object' && (v.py != null || v.ry != null || v.rcy != null || v.rec != null)) n++; });
        c.m[norm(nm)] = n;
      });
    }
    return c.m[p.norm] || 0;
  }
  // everything the NOTES chips need for one player-week
  function injSignalInfo(p, wk) {
    var S = injSig(); if (!S) return null;
    var r = S.prac && S.prac[wk] ? S.prac[wk][p.norm] : null, b = S.body ? S.body[p.norm] : null, n = S.news ? S.news[p.norm] : null;
    var m = _inj && _inj.map ? _inj.map[p.norm] : null;
    return { g: injGroup(p, wk), seq: r ? r.seq : '', gs: r ? r.gs : '', inj: r ? r.inj : '', body: b ? (b.b + (b.n ? ' (' + b.n + ')' : '')) : '', news: n || null, lines: linesUp(p, wk), src: m ? m.src : '', note: m ? (m.note || '') : '' };
  }
  function bangedDock(cls, pos, g, newsPlay) {
    var t = BANGED[cls], d = t && (t[pos] || t.WR);
    if (!d) return null;
    var play = d.play, w = typeof window !== 'undefined' ? window : {};
    if (w.SIM_INJ_TYPE !== false && INJ_PLAY[cls]) {
      play = INJ_PLAY[cls][pos] || play;
      var s = (g && INJ_TYPE[cls]) ? (INJ_TYPE[cls][g] || 0) : 0;
      if (s) play = _sgm(_lgt(play) + s);
    }
    if (newsPlay && cls !== 'D') play = Math.max(play, NEWS_PLAY);
    return { mult: +(play * d.cond).toFixed(3), play: +play.toFixed(3), cond: d.cond };
  }
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
  // TE BACKUP SHARE (backtest_te_vacated.py / te_vacated.log, 2026-10-05; Jack: "ship the te rule"). With the starting TE out,
  // his backup ran 1.40x the live projection next game (156 rows, 6 of 7 seasons under): when the absent TE is not his team's
  // top target-getter (the 'sec' rule, 140 of 156 rows) the TE2 got 0.00 of his targets - the 09-11 split had sent backups with
  // no trailing baseline to 'new bodies'; measured directly TE2 absorbs +0.39. Fix: the sec-rule TE2 takes the lead rule's .25,
  // only for a true backup (own Clay < 4.0 half-PPR a game; co-starters were about right). Fixed value, not fitted: next game
  // -12.1% (5/7, fwd 3/4), ROS 4+ left -21.8% (5/6, 3/4), ROS -22.4% (5/7, 3/4); TE board -0.64%; ADP 1-100: 0 rows touched
  // (it moves only the TE2's own number). Fitted shares failed the season counts (4/7). Kill: window.SIM_TE_SEC2 = false.
  // Backup engine.js.bak_pre_tesec_20261005.
  var TE_SEC2 = { share: 0.25, maxOwnHalf: 4.0 };
  function poolTgtShare(rule, apos, sec, i, q) {
    var wt = rule.tgtSame[i] || 0;
    if (apos === 'TE' && sec && i === 0 && !wt && !(typeof window !== 'undefined' && window.SIM_TE_SEC2 === false)) {
      var dv = clayDiv(q), own = dv > 0 ? seasonPoints(q, PRESETS.half) / dv : 0;
      if (own < TE_SEC2.maxOwnHalf) wt = TE_SEC2.share;
    }
    return wt;
  }
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
    _ncCache = {};   // v2.12: the shadow redistribution cache follows the injury state
    _fillinCache = {};   // fill-in rescale: "back" reads the injury layer
    _chartPreCache = {};   // so do the pre-injury chart spots (who is out now)
    _peckCache = {}; // pecking-order ranks follow it too (an absent WR2 promotes the WR3)
    opts = opts || {};
    var list = players.list || players;
    var wnd = typeof window !== 'undefined' ? window : {};
    _inj = { week: currentWeek, map: {}, adj: {}, play: {}, zeros: [] };
    if (opts.active === false || wnd.SIM_INJ_LAYER === false || !(currentWeek >= 1)) return _inj;
    var ov = wnd.IN_SEASON_OUT_OVERRIDES || {};
    var map = _inj.map;
    var bangedOn = wnd.SIM_BANGED !== false;
    var SIG = injSig(), newsOn = wnd.SIM_NEWS_WINDOWS !== false && SIG && SIG.news;
    var newsPlayOf = function (p) { var n = newsOn ? SIG.news[p.norm] : null; return !!(n && n.flag && n.flag.k === 'play'); };
    var putDock = function (p, cls, src, legacy) {
      var g = injGroup(p, currentWeek), np = newsPlayOf(p);
      var d = bangedOn ? bangedDock(cls, p.pos, g, np) : null;
      if (d) { map[p.norm] = { from: currentWeek, to: currentWeek, mult: d.mult, play: d.play, cond: d.cond, src: src, g: g, note: np ? 'news: expected to play' : '' }; return; }
      if (legacy < 1) map[p.norm] = { from: currentWeek, to: currentWeek, mult: legacy, src: src };
    };
    var ovAsOf = String(wnd.IN_SEASON_OUT_OVERRIDES_ASOF || '');
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
      var t = String(p.injFlag || '').toLowerCase();
      var pr = prMap[p.norm] || null;
      var gs = pr ? String(pr.gs || '').toLowerCase() : '';
      var practiced = pr ? String(pr.pr || '') : '';
      // ---- news read, gated by the player's own designation (INJURY SIGNALS 3) ----
      var nws = newsOn ? SIG.news[p.norm] : null, nwin = null;
      var tInj = t.split('|')[0] || '', tSt = t.split('|')[1] || '';
      var reserve = /^(ir|pup|nfi|na|sus|dnr|cov)$/.test(tInj) || (tSt !== '' && tSt !== 'active');
      var outish = reserve || /^(out|doubtful)$/.test(tInj) || gs === 'out' || gs === 'doubtful';
      var rec0 = jsData().players ? jsData().players[p.norm] : null, wks0 = rec0 && rec0.wks ? rec0.wks : [];
      if (nws && nws.win) {
        var w = nws.win, practicing = practiced === 'LP' || practiced === 'FP';
        var playedSince = wks0.some(function (x) { return x >= w.from; });
        var agrees = w.k === 'season' ? outish : (outish || (tInj === 'questionable' && !practicing) || practiced === 'DNP');
        if (!playedSince && agrees) nwin = w;
      }
      var oDate = (o && o.length >= 3 && o[2]) ? String(o[2]) : ovAsOf;
      var newsNewer = !!(nwin && nwin.date > oDate);
      // manual window: wins while it is running, unless the news is newer than the entry. An EXPIRED window no
      // longer speaks for the player (2026-10-01: Dowdle, Out + no practice, projected at full strength behind an
      // expired [3, 3]) - the current designation takes over.
      // 2026-10-05 (Jack: "IR players don't return the first week eligible"): a manual window no longer
      // ends in a guaranteed full return - the weeks after it get a soft landing (built in the curve block
      // below) unless the entry says 'firm' or the current team report has him practicing (LP / FP).
      // The landing keeps speaking AFTER the window ends, through its own weeks (lmax, else to + 3): an IR player still listed
      // IR the week after his window used to fall to the designation (IR = 4 more zeroed weeks) - the very "not the first week
      // eligible" read inverted. In that phase: practicing (LP / FP) or a 'firm' entry -> the designation decides (Questionable
      // docks still apply); the NFL report's game status Out -> this week is zeroed and the landing starts after it.
      var oLand = o && o.length >= 2 && o[3] !== 'firm' && (typeof o[3] === 'number' ? o[3] : o[1] + 3) >= currentWeek;
      if (o && o.length >= 2 && !newsNewer && (o[1] >= currentWeek || oLand)) {
        var practicing0 = practiced === 'LP' || practiced === 'FP';
        var firm = o[3] === 'firm' || practicing0;
        if (o[1] < currentWeek && firm) { /* landing phase, practicing: fall through to the designation */ }
        else {
          var oTo = (o[1] < currentWeek && gs === 'out') ? currentWeek : o[1];
          map[p.norm] = { from: o[0], to: oTo, mult: 0, src: 'override', firm: firm, lmax: typeof o[3] === 'number' ? Math.max(o[3], oTo + 1) : null, note: firm && o[3] !== 'firm' ? 'practicing (' + practiced + ')' : '' };
          return;
        }
      }
      if ((o === null || o === 0) && !newsNewer) return;
      if (nwin) {
        var ncv = {}; Object.keys(nwin.curve || {}).forEach(function (cw) { if (+cw > nwin.to) ncv[+cw] = nwin.curve[cw]; });
        if (nwin.to >= currentWeek) {
          map[p.norm] = { from: nwin.from, to: nwin.to, mult: 0, src: nwin.k === 'season' ? 'news-season' : 'news', curve: ncv, note: nwin.date + ' ' + nwin.hl };
          return;
        }
        if (ncv[currentWeek] != null && outish) {
          // past the reported minimum but not activated yet: the soft landing prices this week
          map[p.norm] = { from: currentWeek, to: currentWeek, mult: ncv[currentWeek], play: ncv[currentWeek], cond: 1, src: 'news-return', curve: ncv, note: nwin.date + ' ' + nwin.hl };
          return;
        }
      }
      // ---- season-ending diagnosis from Sleeper's body part (INJURY SIGNALS 4) ----
      if (wnd.SIM_DX_SEASON !== false && SIG && SIG.body && SIG.body[p.norm] && outish && wks0.length && /\b(acl|achilles)\b/i.test(SIG.body[p.norm].b || '')) {
        map[p.norm] = { from: currentWeek, to: WEEKS, mult: 0, src: 'dx-season', note: SIG.body[p.norm].b + (SIG.body[p.norm].n ? ' (' + SIG.body[p.norm].n + ')' : '') };
        return;
      }
      if (nws && nws.out && (tInj !== '' || pr)) { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0, src: 'news-out', note: nws.out.date + ' ' + nws.out.hl }; return; }
      if (t && t !== '|') {
        if (/\bir\b|injured reserve|\bpup\b|\bnfi\b|non football/.test(t)) { map[p.norm] = { from: currentWeek, to: Math.min(WEEKS, currentWeek + 3), mult: 0, src: 'ir' }; return; }
        if (/\bsus\b|suspend/.test(t)) { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0, src: 'sus' }; return; }
        if (/^na\b|\bna\|/.test(t)) {
          // 'NA' = not active for a non-injury reason (exempt list / personal / league discipline);
          // indefinite like IR, corroborated by Sleeper's own weekly projection like Out
          var swk2 = wnd.SIM_SLEEPER_WEEKLY || null, sw2 = swk2 && swk2.p && (+swk2.week === +currentWeek) ? swk2.p[p.norm] : null;
          if (!(swk2 && swk2.p && (+swk2.week === +currentWeek)) || sw2 == null || sw2 <= 0) { map[p.norm] = { from: currentWeek, to: Math.min(WEEKS, currentWeek + 3), mult: 0, src: 'na' }; return; }
          map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0.75, src: 'na-unconfirmed' }; return;
        }
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
          if (gs === 'doubtful') { putDock(p, 'D', 'nfl-doubtful', 0.5); return; }
          map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0.75, src: 'out-unconfirmed' }; return;
        }
        if (/doubtful/.test(t)) {
          // Sleeper Doubtful: the calibrated near-zero dock only when corroborated (current NFL report Doubtful,
          // or Sleeper has pulled his weekly projection); a current Questionable report is fresher and falls
          // through to the questionable classes; otherwise the old x0.5 'doubtful-unconfirmed'.
          var swk3 = wnd.SIM_SLEEPER_WEEKLY || null, sw3ok = swk3 && swk3.p && (+swk3.week === +currentWeek), sw3 = sw3ok ? swk3.p[p.norm] : null;
          if (gs === 'out') { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0, src: 'nfl-out' }; return; }
          if (gs === 'doubtful' || (sw3ok && (sw3 == null || sw3 <= 0))) { putDock(p, 'D', 'doubtful', 0.5); return; }
          if (gs !== 'questionable') { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0.5, src: 'doubtful-unconfirmed' }; return; }
        }
      }
      // NFL report as a second opinion (Sleeper lagging the official status)
      if (gs === 'out') { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0, src: 'nfl-out' }; return; }
      if (gs === 'doubtful') { putDock(p, 'D', 'nfl-doubtful', 0.5); return; }
      var questionable = gs === 'questionable' || /questionable/.test(t);
      if (questionable && gs === 'questionable') {
        // the current week's NFL report says Questionable: calibrated by the latest practice
        if (practiced === 'DNP') putDock(p, 'Q-DNP', 'q-dnp', 0.75);
        else if (practiced === 'LP') putDock(p, 'Q-LP', 'q-lp', 1);
        else putDock(p, 'Q-FP', 'q-fp', 1);
      } else if (questionable && practiced === 'DNP') map[p.norm] = { from: currentWeek, to: currentWeek, mult: newsPlayOf(p) ? NEWS_PLAY : 0.75, src: 'q-dnp', note: newsPlayOf(p) ? 'news: expected to play' : '' };
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
    // AVAILABILITY CURVE (backtest_avail_curve.py, 2026-09-30; Jack: "do injuries (how long out for) an issue?").
    // A player tagged Out was projected back at full strength the very next week and an IR player right after
    // his four games. 1,668 absence states 2019-25 (starters): after one missed game 65% miss the next too,
    // after two 72%, three 77%, four 77%, six 87%. Chain P(plays j games from now) = 1 - CONT[k] x ... x
    // CONT[k+j-1] (k = games missed so far); LOYO Brier .231 vs .578 for the engine's assumption, expected
    // games over the next four 1.94 vs actual 1.84 (engine 4.00). Applied to the weeks AFTER a designation's
    // own window for Out / NFL-Out / IR / NA (not overrides - Jack sets those - and not unconfirmed or
    // Doubtful docks), out to AVAIL_H more weeks; the vacated share flows to teammates in those weeks like
    // any other dock. The current week never changes. Kill: window.SIM_AVAIL_CURVE = false.
    var AVAIL_CONT = { 1: 0.65, 2: 0.72, 3: 0.77, 4: 0.77, 5: 0.75, 6: 0.87, 7: 0.86, 8: 0.89 }, AVAIL_H = 8;
    _inj.avail = {};
    if (wnd.SIM_AVAIL_CURVE !== false) {
      var gwOf = function (tm) { return (sched && sched.gameWeeks && sched.gameWeeks[tm]) || []; };
      // v2 (INJURY SIGNALS 2): per-position table + a logit shift by the injury on his report, band k = 1 / 2 / 3+
      var availV2 = wnd.SIM_AVAIL_V2 !== false;
      var contOf = function (k, pos, g) {
        var kk = Math.min(8, Math.max(1, k));
        var c = (availV2 && AVAIL_POS[pos]) ? AVAIL_POS[pos][kk - 1] : AVAIL_CONT[kk];
        var sh = (availV2 && g && AVAIL_GRP[g]) ? AVAIL_GRP[g][Math.min(3, kk) - 1] : 0;
        return sh ? _sgm(_lgt(c) + sh) : c;
      };
      // OVERRIDE LANDING (2026-10-05): after a manual window, P(plays) = .60 / .80 / .90 over his next three
      // games - the same landing as a news "back week N" item (build_injury_signals.py) - or, when the entry
      // names a latest week ([from, to, date, lmax]), 50% rising to 90% by that week like a reported range.
      // 'firm' entries and players practicing on the current report return at full strength. The return ramp
      // (returnDock) still stacks on his first games back.
      list.forEach(function (p) {
        var m = map[p.norm];
        if (!m || m.src !== 'override' || m.firm || m.to >= WEEKS) return;
        // landing weeks count from the end of the window (a landing already under way keeps its step), shown from this week on
        var gw = gwOf(p.tm), tail = gw.filter(function (w) { return w > m.to; }), curve = {};
        if (m.lmax && m.lmax > m.to) {
          var span = tail.filter(function (w) { return w <= m.lmax; }).slice(0, 6);
          span.forEach(function (w, j) { curve[w] = span.length > 1 ? +(0.5 + 0.4 * j / (span.length - 1)).toFixed(2) : 0.6; });
          var nx = tail.filter(function (w) { return w > (span.length ? span[span.length - 1] : m.lmax); });
          if (span.length === 1 && nx.length) curve[nx[0]] = 0.85;
        } else {
          tail.slice(0, 3).forEach(function (w, j) { curve[w] = [0.6, 0.8, 0.9][j]; });
        }
        Object.keys(curve).forEach(function (w) { if (+w < currentWeek) delete curve[w]; });
        if (Object.keys(curve).length) m.curve = curve;
      });
      list.forEach(function (p) {
        var m = map[p.norm];
        // Out / IR / exempt designations, a news "ruled out", and a corroborated Doubtful (plays 1%: he is one missed game in)
        var nearZero = m && (m.mult === 0 || (m.play != null && m.play <= 0.05));
        if (!m || !nearZero || ['out', 'nfl-out', 'ir', 'na', 'news-out', 'doubtful', 'nfl-doubtful'].indexOf(m.src) < 0) return;
        var rec = jsData().players ? jsData().players[p.norm] : null, wks = rec && rec.wks ? rec.wks : [];
        var gw = gwOf(p.tm), k = 0, seenPlay = false, first = null, lastPlayed = null;
        for (var gi = gw.length - 1; gi >= 0; gi--) {   // games missed in a row before the current week (a bye is not a game)
          var w0 = gw[gi]; if (w0 >= currentWeek) continue;
          if (wks.indexOf(w0) >= 0) { seenPlay = true; lastPlayed = w0; break; }
          k++; first = w0;
        }
        if (!seenPlay && k > 0) k = Math.min(k, 3);   // never played this season: a camp injury, not an in-season streak
        for (var w1 = m.from; w1 <= m.to; w1++) if (gw.indexOf(w1) >= 0) { k++; if (first == null) first = w1; }   // his designation's own zeroed games
        // the injury group the curve was fit on: what the report said the week he first sat (or the report before
        // it); on a reserve list without ever being listed = 'unlisted'; never played this season = no shift
        var g = '';
        if (availV2 && seenPlay && SIG && SIG.prac && first != null) {
          var r1 = (SIG.prac[first] && SIG.prac[first][p.norm]) || (lastPlayed != null && SIG.prac[lastPlayed] ? SIG.prac[lastPlayed][p.norm] : null);
          var bg = SIG.body && SIG.body[p.norm] ? SIG.body[p.norm].g : '';
          g = r1 ? (r1.g || bg) : ((m.src === 'ir' || m.src === 'na') ? 'unlisted' : bg);
        }
        var surv = 1, curve = {}, ahead = 0;
        for (var w2 = m.to + 1; w2 <= WEEKS && ahead < AVAIL_H; w2++) {
          if (gw.indexOf(w2) < 0) continue;
          surv *= contOf(k + ahead, p.pos, g); ahead++;
          curve[w2] = +(1 - surv).toFixed(3);
        }
        if (ahead) { m.curve = curve; m.missed = k; m.g = g || m.g || ''; }
      });
    }
    var weeks = {};
    Object.keys(map).forEach(function (n) { for (var w = map[n].from; w <= map[n].to; w++) weeks[w] = 1; if (map[n].curve) Object.keys(map[n].curve).forEach(function (cw) { weeks[cw] = 1; }); });
    Object.keys(weeks).forEach(function (wkS) {
      var wk = +wkS, lost = {}, healthyW = {}, nextQb = {};
      var multOf = function (p) { var m = map[p.norm]; if (!m) return 1; if (wk >= m.from && wk <= m.to) return m.mult; return (m.curve && m.curve[wk] != null) ? m.curve[wk] : 1; };
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
            var wt = poolTgtShare(rule, apos, !v.lead, i, q), wc = rule.carSame[i];
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
        var mp = map[p.norm];
        if (mp && mp.play != null && mult < 1 && wk >= mp.from && wk <= mp.to) (_inj.play[p.norm] = _inj.play[p.norm] || {})[wk] = mp.play;
      });
    });
    list.forEach(function (p) { var m = map[p.norm]; if (m) _inj.zeros.push({ name: p.name, tm: p.tm, pos: p.pos, from: m.from, to: m.to, mult: m.mult, play: m.play, cond: m.cond, src: m.src, curve: m.curve || null, missed: m.missed, g: m.g || '', note: m.note || '' }); });
    list.forEach(function (p) { var m = map[p.norm]; if (m && m.curve) { _inj.avail[p.norm] = m.curve; var pl = _inj.play[p.norm] = _inj.play[p.norm] || {}; Object.keys(m.curve).forEach(function (cw) { pl[cw] = m.curve[cw]; }); } });   // curve weeks: the whole dock is availability (the prop anchor undoes only `play`)
    return _inj;
  }
  // availability-curve weight for a week (P plays), 1 when the curve does not apply - the site's PPG export
  // divides those weeks' means by it so a rest-of-season PPG stays a per-game rate.
  function injAvail(p, wk) {
    if (!_inj || !_inj.avail) return 1;
    var a = _inj.avail[p.norm];
    return a && a[wk] != null ? a[wk] : 1;
  }
  // RETURN RAMP (backtest_return_ramp.py, 2026-09-30; the 09-15 first-game-back dock finally wired). Game 1
  // back after 2-3 missed team games scored .90 of projection, after 4+ missed .835 / .95 / .98 over the first
  // three games back (QB .77 / WR .73 in game 1); after one missed game only QBs dip (.90; RB 1.08, WR 1.01).
  // TE showed nothing (1.00). Shipped: missed 1 -> QB x0.95; missed 2-3 -> x0.90; missed 4+ -> x0.85 / x0.92 /
  // x0.96 (QB/RB/WR): MSE on the ramp rows -2.8% (7/7 seasons), QB -3.9%, RB -2.2%, WR -2.6%. Missed games
  // are team games with no 2026 game row (sim_2026 players[norm].wks); weeks from the current one on count as
  // played when the injury layer does not zero them, so a player out now takes the ramp on his projected
  // return. Kill: window.SIM_RETURN_RAMP = false.
  var RETURN_RAMP = { '1': { QB: [0.95] }, '2-3': { QB: [0.90], RB: [0.90], WR: [0.90] }, '4+': { QB: [0.85, 0.92, 0.96], RB: [0.85, 0.92, 0.96], WR: [0.85, 0.92, 0.96] } };
  function returnDock(p, wk, schedule) {
    if (p.isDST || !RETURN_RAMP['4+'][p.pos]) return 1;
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_RETURN_RAMP === false || !_inj || !(_inj.week >= 2)) return 1;
    var rec = jsData().players ? jsData().players[p.norm] : null, wks = rec && rec.wks ? rec.wks : null;
    if (!wks || !wks.length) return 1;                       // no game yet this season: a camp injury / debut, not a return
    if (seasonPoints(p, PRESETS.half) / 17 < 5) return 1;   // backups drift in and out of the box score; the ramp was measured on starters
    var gw = (schedule && schedule.gameWeeks && schedule.gameWeeks[p.tm]) || [];
    var playedW = function (w) { return w < _inj.week ? wks.indexOf(w) >= 0 : injAdj(p, w) > 0; };
    var back = 0, k = 0, gi = gw.length - 1;
    while (gi >= 0 && gw[gi] >= wk) gi--;
    while (gi >= 0 && playedW(gw[gi])) { back++; gi--; }
    while (gi >= 0 && !playedW(gw[gi])) { k++; gi--; }
    if (!k || gi < 0) return 1;                               // no absence, or nothing played before it
    var ramp = RETURN_RAMP[k === 1 ? '1' : k <= 3 ? '2-3' : '4+'][p.pos];
    return (ramp && back < ramp.length) ? ramp[back] : 1;
  }
  function injAdj(p, wk) {
    if (!_inj) return 1;
    var a = _inj.adj[p.norm];
    return a && a[wk] != null ? a[wk] : 1;
  }
  function injPlay(p, wk) {
    // availability part of the dock (P plays); equals min(1, injAdj) for docks without a production split
    if (!_inj) return 1;
    var a = _inj.play && _inj.play[p.norm];
    return a && a[wk] != null ? a[wk] : Math.min(1, injAdj(p, wk));
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
    var perGameDiv = p.qbWindow ? p.qbWindow.games : clayDiv(p);
    var dAdj = (defenseAdj()[slot.opp] || {})[p.pos] || 1;
    var mCbS = cbShadowMult(slot.opp, p.pos, p), mCb1 = cb1OutBoost(slot.opp, p.pos, p), mOl = olOutDock(p.tm, p.pos),
      mPr = pressureMult(slot.opp, p.pos), mWx = weatherMult(p, wk, slot), mRet = returnDock(p, wk, schedule);
    var cbM = mCbS * mCb1 * mOl * mPr * mWx * mRet;
    var mSnap = snapMult(p, wk), mRoute = routeMult(p, wk);
    var sM = mSnap * mRoute;
    var rampF = 1;
    if (p.ramp) {
      var R = RAMP[p.ramp];
      rampF = (gameIdx > 0 && gameIdx <= R.head.length) ? R.head[gameIdx - 1] : R.tail;
    }
    var iA = injAdj(p, wk); // in-season availability / vacated-opportunity factor
    var factor = mult * dAdj * cbM * sM * rampF * iA;
    var clayPg0 = seasonPoints(p, sc) / perGameDiv;
    // BANGED-UP PRIOR (backtest_qb_injury_usage.py --refine, 2026-10-07; Jack, London / Bowers: "last year brock bowers was banged up
    // many games and underperformed for it"): Clay's per-game prior for a WR / TE who played 3+ games last season listed Questionable,
    // with a Limited / DNP final practice, or at < 75% of his own median snap share, and whose HEALTHY games (4+) averaged more than
    // Clay's number, is lifted by .5 x (healthy ppg - all ppg), floored at 0 and capped at 2.0 half-PPR a game (converted to this
    // sheet's scoring). The live form under-projected these players 5-15% (WR ADP 1-30: actual 1.10-1.15 x projection, 0/6 seasons
    // the other way). 2019-25, every season out: WR next game -1.1% (6/7), rest of season -7.4% (6/7), forward 4/4; TE -0.2% / -3.4%
    // (4/5), forward 3/3; ADP 1-30 -11% ROS (6/6); still -4% once 8+ games are in. RB failed (+1 to +6%) and is excluded. Data:
    // data/sim_prior_health.js (2025 tags, rebuilt each January by the same script). Kill: window.SIM_HEALTH_PRIOR = false (the data object is window.SIM_PRIOR_HEALTH).
    var hLift = 0;
    if (!p.isDST && PRIOR_HEALTH.pos[p.pos] && clayPg0 > 0 && !(typeof window !== 'undefined' && window.SIM_HEALTH_PRIOR === false)) {
      var PH = typeof window !== 'undefined' && window.SIM_PRIOR_HEALTH, hRow = PH && PH.p ? (PH.p[p.name] || PH.p[p.norm]) : null;
      if (hRow && hRow[0] != null && hRow[2] >= PRIOR_HEALTH.minHurt && hRow[3] >= PRIOR_HEALTH.minHealthy) {
        var clayHalf = seasonPoints(p, PRESETS.half) / perGameDiv;
        if (clayHalf > 0 && hRow[0] > clayHalf) {
          var liftHalf = Math.min(PRIOR_HEALTH.cap, Math.max(0, PRIOR_HEALTH.a * (hRow[0] - hRow[1])));
          hLift = liftHalf * clayPg0 / clayHalf;
        }
      }
    }
    var clayPg = clayPg0 + hLift;
    // QB NEXT MAN UP = ADDITIVE POINTS (2026-09-18, Drew Lock 30.5 / W3 202.7, Cooper Rush 69.8): the QB boost is
    // 1 + 85% x lost / the backup's own Clay level (season / 17, ~0.5), i.e. a x28 ratio that only means "his level +
    // 85% of the starter's". Once the backup has a 2026 game the JS base (2.5) and the market rate (15) are no longer
    // that Clay level, and the ratio multiplied them to 68 / 202. Convert it back to the inherited points on the scale
    // it was sized on and add them to the base; the chain then carries no availability factor for him.
    var qbInh = 0, iAc = iA;
    if (p.pos === 'QB' && iA > 1) { qbInh = (iA - 1) * seasonPoints(p, sc) / (p.qbWindow ? (p.qbWindow.games || 17) : 17); iAc = 1; }
    // LIVE BACKUP-QB RULE (2026-10-05, Jack: "Mariota was only used because the starter was out - Daniels is back next
    // week ... we need context around usage so far"). The live number had no starter check: a backup's fill-in starts
    // become his JS base (Mariota 15/g), that base was projected EVERY week (two WAS QBs at 15 and 19 once Daniels
    // returns), the inherited 85% of the starter was ADDED on top of it, and the market-rate fallback replayed the lines
    // the books set while he started. Now, as in the shadow (v2.8 backup cap + v2.25 qbFill): a QB at string 2+ on his
    // team's chart for THIS week (effectiveString - available players only; for later weeks a starter who is out now is
    // put back at his pre-injury spot) is held to backup level, and a fill-in takes the LARGER of his own number and the
    // inherited 85%, never both (43 fill-in starts: actual 14.7, own 14.3, added 26.4). This week's posted lines still win.
    // Kill: window.SIM_LIVE_QB2 = false. Backup engine.js.bak_pre_liveqb2_20261005.
    // PLANNED START WINDOW (ROS audit 10-01 open item, fixed 2026-10-07): a QB with a QB_ROOM_OVERRIDES / injury-start / Clay-split
    // window IS the starter for the weeks inside it - the depth-chart backup cap must not apply there (Sanders W12+ read 0.9 with a
    // 14.5 Clay window prior), and his relief cameos (0-2 pts) are not evidence of his level as a starter. Kill: window.SIM_QB_WINDOW_FIX = false.
    var inWin = p.pos === 'QB' && p.qbWindow && (p.qbWindow.src === 'override' || p.qbWindow.src === 'injury-start' || p.qbWindow.src === 'clay-split') && wk >= p.qbWindow.s && wk <= p.qbWindow.e && !(typeof window !== 'undefined' && window.SIM_QB_WINDOW_FIX === false);
    var winEvid = null;
    if (inWin) {
      var wrec = jsData().players ? jsData().players[p.norm] : null;
      if (wrec && wrec.wf) {
        var ks = Object.keys(wrec.wf).filter(function (k) { return +k < wk && isFinite(+wrec.wf[k]); }), starts = ks.filter(function (k) { return +wrec.wf[k] >= 2; });
        if (starts.length < ks.length) { var sum = 0; starts.forEach(function (k) { sum += +wrec.wf[k]; }); winEvid = { g: starts.length, ppgHalf: starts.length ? sum / starts.length : 0 }; }
      }
    }
    var qb2Cap = null, qb2Tag = null, qb2On = p.pos === 'QB' && !inWin && !(typeof window !== 'undefined' && window.SIM_LIVE_QB2 === false);
    if (qb2On) {
      var qdL = typeof window !== 'undefined' ? window.SIM_DEPTH_2026 : null;
      var chL = qdL && qdL.teams && qdL.teams[p.tm] && qdL.teams[p.tm].QB && qdL.teams[p.tm].QB.length;
      if (chL) {
        var qsL = effectiveString(p, wk);
        if (qsL == null || qsL >= 2) {
          var hpL = seasonPoints(p, PRESETS.half) / perGameDiv;
          qb2Cap = NC_SHADOW.qbBackupPpg * ((hpL > 0 && clayPg > 0) ? clayPg / hpL : 1);
          qb2Tag = qsL == null ? 'x' : String(qsL);
        }
      }
    }
    var qbJoin = function (own) {   // own per-game number + the inherited role, the live backup-QB way
      if (!qb2On) return own + qbInh;
      if (qb2Cap != null && own > qb2Cap) own = qb2Cap;
      return qbInh > 0 ? Math.max(own, qbInh) : own;
    };
    var mQbf = 1;
    if (p.pos === 'QB' && !(qbInh > 0) && !(iA > 1) && clayPg > 0) { var cf = qbFloor(clayPg, sc); mQbf = cf / clayPg; }
    var mRos = rosTilt(p, wk); mQbf *= mRos;   // rest-of-season volume tilt rides the same model-side multiplier (weeks ahead only)
    mean = qbJoin(clayPg * mQbf) * (factor / iA * iAc) * rookieLevel(p);
    // JS Weekly (in-season model): Clay prior shrunk toward 2026 actuals,
    // actual FPA-by-position opponent adj replacing Clay unit grades as the
    // sample grows. Preseason (no 2026 data) both terms collapse to Clay's,
    // so jsMean === mean until real games exist.
    var lvU = liveUsage(p, wk, sc);   // WR / TE: the level of his role (targets, routes, snaps) as part of the evidence
    // LATE-ROUND WR PRIOR (backtest_live_blend_pos.py, 2026-10-05; Jack: "do the late round WR change"). WRs drafted after
    // pick 60 or undrafted, with the usage evidence on: Clay prior worth 4 games instead of 5. 2019-25 on the live form,
    // fixed 4 better in 6 of 7 seasons on next game, rest of season with and without the survivor filter (forward 3 of 4);
    // 3 scored more (next game -0.15% everyone, -0.67% on its rows) but 4 keeps ~55% of the gain at less risk. Rows WITHOUT
    // usage evidence get worse, so the condition requires it. Usage branch only: JS_PRIOR_STRENGTH (also the TD-luck weight),
    // jsBaseNoU / jsNoUse (the usage scorecard's comparison) are unchanged. Off switch: window.SIM_LIVE_BLEND_POS = false.
    // Backup engine.js.bak_pre_wrlate_20261005.
    var livePs = (p.pos === 'WR' && lvU && (p.adp == null || p.adp > 60)
                  && !(typeof window !== 'undefined' && window.SIM_LIVE_BLEND_POS === false)) ? 4 : null;
    var fiF = fillinPtsF(p, wk);   // FILL-IN rescale (1 unless 2+ stale fill-in games)
    var jsBaseNoU = jsBasePg(p, sc, clayPg, null, null, fiF, winEvid), jsBase0 = lvU ? jsBasePg(p, sc, clayPg, livePs, lvU, fiF, winEvid) : jsBaseNoU, mRook = rookieLevel(p);
    var jsPg = jsBase0 * mRook;
    var jsPgPre = jsPg;
    if (p.pos === 'QB' && !(qbInh > 0) && !(iA > 1)) { jsPg = qbFloor(jsPg, sc); mQbf = jsPgPre > 0 ? jsPg / jsPgPre : 1; }
    if (mRos !== 1) { jsPg *= mRos; mQbf *= mRos; }
    var jsPgRook = jsPg;
    var rbU = rbUsagePg(p, wk);
    if (rbU) {
      var uScale = rbU.halfPg > 0 && clayPg > 0 ? clayPg / rbU.halfPg : 1;   // half-PPR -> this sheet's scoring
      jsPg = (1 - RB_USAGE.w) * jsPg + RB_USAGE.w * rbU.half * uScale;
    }
    var oppM = jsOppMult(slot.opp, p.pos, dAdj);
    var jsChain = mult * oppM * cbM * sM * rampF * iAc;
    var jsPgOwn = jsPg;   // before the inherited QB role (WHY waterfall)
    jsPg = qbJoin(jsPg);
    // TD-luck mean reversion (RB/WR/TE/QB), additive after the chain. Scaled by
    // AVAILABILITY only: iA also carries the vacated-opportunity boost for
    // backups (>1, Cooper Rush x210 on a near-zero base) which must not
    // multiply a points term - min(1, iA) keeps Out/Doubtful docks and drops the boost.
    var luckFull = (qb2Cap != null && !(qbInh > 0)) ? 0 : tdLuckAdj(p, sc) * Math.min(1, iA);   // a held backup carries no TD luck from his fill-in starts
    var luckAdj = luckFull * (lvU ? 1 - lvU.lam : 1);   // only the points share of the evidence carries touchdown luck
    var jsMean = Math.max(0, jsPg * jsChain + luckAdj);
    var jsNoUse = lvU ? Math.max(0, (jsBaseNoU * mRook + qbInh) * jsChain + luckFull) : null;   // the same number without the usage evidence (usage_scorecard.py)
    var jsRawPk = jsMean;   // before the pecking-order dock: the learned shadow was fit on this number
    var pkHalf = seasonPoints(p, PRESETS.half) / perGameDiv, peckR = peckDock(p, wk, sc, schedule, jsRawPk, (pkHalf > 0 && clayPg0 > 0) ? jsRawPk * pkHalf / clayPg0 : jsRawPk);
    var mPeck = peckR.m, mVol = volumeMult(p, slot), mDock = mPeck * mVol;   // model-side docks: pecking order x volume context
    if (mDock !== 1) { mean *= mDock; jsMean = jsRawPk * mDock; if (jsNoUse != null) jsNoUse *= mDock; }
    var lcCorr = null;
    try { lcCorr = learnedShadowCorr(p, wk, sc, slot, { clayPg: clayPg0, mult: mult, rbU: rbU, iA: iA, jsMean: jsRawPk }); } catch (_) { lcCorr = null; }   // SHADOW (learned correction)
    // CLAY-FREE SHADOW BASE (2026-09-15): same blend and chain, but the prior is the
    // player's OWN 3-yr weighted PPG (player_weekly_sigma mean_ppg, half-PPR, rescaled to
    // this sheet by the Clay stat mix) instead of Clay. Graded every Tuesday next to the
    // shipped mean (score_week.py "No-Clay shadow"); the season ledger decides whether
    // Clay can go. No history -> Clay prior, flagged 'clay-fallback'.
    var ncSrc = 'clay-fallback', ncPrior = clayPg0;   // the Clay-free shadow never sees the banged-up lift
    var halfPg = seasonPoints(p, PRESETS.half) / perGameDiv, scale = (halfPg > 0 && clayPg0 > 0) ? clayPg0 / halfPg : 1;
    var jsRec = jsData().players ? jsData().players[p.norm] : null;
    var h3 = (p.histPpg != null && p.histGames >= 8) ? p.histPpg * scale : null;          // 3-yr weighted PPG
    var l8 = (jsRec && jsRec.l8 != null && jsRec.l8g >= 4) ? jsRec.l8 * scale : null;      // last 8 played games (2024-26)
    // HEALTHY-GAMES HISTORY (backtest_shadow_healthy_prior.py V3, 2026-10-07; Jack: "let's do it in order", item 1). SHADOW ONLY.
    // The history pieces are rebuilt from games he was not listed Questionable / limited-DNP / under 75% of his median snaps:
    // h3 -> healthy 3-yr weighted PPG, l8 -> last 8 healthy prior-season games + every game this season (V1 form). Vets on the
    // opportunity prior with 3+ hurt games last season keep the healthy history instead of the opp blend. 2019-25 harness shadow:
    // rest of season -1.07% (7/7), forward -0.63% (4/4), whole board -0.55%; next game -0.17% (7/7). Data: SIM_PRIOR_HEALTH.h.
    // Kill: window.SIM_NC_HEALTHY = false. Backup engine.js.bak_pre_nchealthy_20261007.
    var hlthOn = !(typeof window !== 'undefined' && window.SIM_NC_HEALTHY === false), PHd = typeof window !== 'undefined' ? window.SIM_PRIOR_HEALTH : null;
    var hRow = (hlthOn && PHd && PHd.h) ? (PHd.h[p.name] || PHd.h[p.norm]) : null, hPrev = (PHd && PHd.p) ? (PHd.p[p.name] || PHd.p[p.norm]) : null, hTag = '';
    if (hRow && !p.isRookie) {
      if (hRow.h3h != null && hRow.h3g >= 8) { h3 = hRow.h3h * scale; hTag = '+hlth'; }
      if (hRow.l8h && hRow.l8h.length) {
        var tailH = hRow.l8h.slice();
        if (jsRec && jsRec.wf) Object.keys(jsRec.wf).map(Number).sort(function (a, b) { return a - b; }).forEach(function (w) { if (w < wk && isFinite(+jsRec.wf[w])) tailH.push(+jsRec.wf[w]); });
        tailH = tailH.slice(-8);
        if (tailH.length >= 4) { var sumH = 0; for (var ti = 0; ti < tailH.length; ti++) sumH += tailH[ti]; l8 = (sumH / tailH.length) * scale; hTag = '+hlth'; }
      }
    }
    var hlthSkipOpp = hTag !== '' && hPrev && hPrev[2] >= 3;   // 3+ hurt games last season: the healthy history replaces the opportunity blend
    if (h3 != null && l8 != null) { ncPrior = 0.5 * h3 + 0.5 * l8; ncSrc = 'hist+l8' + hTag; }
    else if (l8 != null) { ncPrior = l8; ncSrc = 'l8' + hTag; }
    else if (h3 != null) { ncPrior = h3; ncSrc = 'hist' + hTag; }
    var ncRawHist = ncPrior;   // raw history blend before the age / regression curves (v2.23 parity)
    if (ncSrc !== 'clay-fallback') {
      var sa = shadowAgeAdjust(p, ncPrior / scale);   // curves live in half-PPR units
      ncPrior = sa.v * scale; ncSrc += sa.tag;
      // OPPORTUNITY PRIOR (backtest_opp_prior.py / build_opp_prior.py, 2026-09-15): for veterans the calibrated
      // HIST + OPP blend beat the history prior 8.32 vs 9.06 season MSE (calibrated Clay 7.08 still best, so SHADOW
      // ONLY). cal = [a, b history, c opportunity] in half-PPR. Rookies are not in the file (OPP lost to Clay there).
      var opd = typeof window !== 'undefined' ? window.SIM_OPP_PRIOR_2026 : null;
      var opr = opd && opd.players ? opd.players[p.norm] : null, occ = opd && opd.cal ? opd.cal[p.pos] : null;
      if (opr && occ && occ.length === 3 && ncPrior / scale >= 4 && !hlthSkipOpp && !(typeof window !== 'undefined' && window.SIM_SHADOW_OPP === false)) {   // >= 4 half PPG like the age curve: the calibration was fit on real roles and lifts deep backups; hlthSkipOpp = healthy history instead (2026-10-07)
        // v2.23 PARITY (2026-09-17, audit after Jack's 'are there any other bugs like that'): the HIST + OPP calibration (backtest_opp_prior.py)
        // was FITTED on HISTREG = the 3-season weighted PPG (.5 / .3 / .2, NO last-8) after the regression curve, and the weekly harness uses that fitted value
        // (SHADOWCAL) directly. Live was feeding it the age-adjusted 50/50 blend of 3-season and LAST 8, so one bad stretch hit a veteran's
        // prior about twice as hard as the graded form (Jefferson: 3-season 12.6, last 8 9.0). History-window test the same day: when the
        // last 8 sits 3+ below the 3-season level the next season comes in at 14.6 vs 15.2 / 11.2 - best-fit weight on the last 8 is 0.18.
        // Kill: window.SIM_NC_OPPHIST = false.
        var opHist = (h3 != null && !(typeof window !== 'undefined' && window.SIM_NC_OPPHIST === false)) ? shadowAgeAdjust(p, h3 / scale).v : ncPrior / scale;   // HISTREG = the 3-season history through the same regression + age curve
        var hbo = occ[0] + occ[1] * opHist + occ[2] * opr.half;
        if (hbo > 0) { ncPrior = hbo * scale; ncSrc += '+opp'; }
      }
    }
    // v2 (NC_SHADOW): Clay-free fallback (rookies by draft pick, else the position mean), then shrink every
    // Clay-free prior toward the position mean, then blend at the position's own prior strength.
    // RELEVANCE GATE: the backtest population is Clay's >= 40-pt pool (~ the fantasy-drafted top 200); the live
    // pool also carries deep backups (Clay 0.5 PPG) whom a position mean or a rookie curve would lift to
    // starter numbers (UDFA QB3 -> 12.8 in the first headless run). Clay-free gate = consensus ADP <= adpGate;
    // ungated players keep the v1 prior (own history, else the Clay fallback) unshrunk.
    var ncV2 = !(typeof window !== 'undefined' && window.SIM_NC_V2 === false) && p.adp != null && p.adp <= NC_SHADOW.adpGate, ncPm = NC_SHADOW.posMean[p.pos];
    if (ncV2 && ncSrc === 'clay-fallback' && ncPm != null) {
      var rc = NC_SHADOW.rookie[p.pos];
      if (p.isRookie && rc) {
        var pk = p.draftPick != null ? p.draftPick : 262;   // undrafted = pick 262
        ncPrior = Math.max(0.5, rc[0] + rc[1] * Math.log(pk)) * scale; ncSrc = p.draftPick != null ? 'rookie-pick' : 'rookie-udfa';
        var rs = NC_SHADOW.rookieStr[p.pos];
        if (rs && !(typeof window !== 'undefined' && window.SIM_NC_DEPTH === false)) {   // v2.2: depth string (RB/WR)
          var ds = effectiveString(p, wk), dsk = ds == null ? 3 : Math.min(3, ds);
          ncPrior = Math.max(0.5, rs[0] + rs[1] * Math.log(pk) + (dsk === 2 ? rs[2] : 0) + (dsk >= 3 ? rs[3] : 0)) * scale;
          ncSrc += '+str' + (ds == null ? 'x' : dsk);
        }
      } else { ncPrior = ncPm * scale; ncSrc = 'pos-mean'; }
    }
    // v2.1: market prior for veterans WITH a history prior (not the fallbacks, not rookies)
    var ncAc = NC_SHADOW.adpCurve[p.pos];
    if (ncV2 && ncAc && !p.isRookie && /^(hist|l8)/.test(ncSrc) && p.adp <= NC_SHADOW.adpMax && !(typeof window !== 'undefined' && window.SIM_NC_ADP === false)) {
      var mkt = Math.max(0.5, ncAc[0] + ncAc[1] * Math.log(p.adp)), wA = p.exp === 1 ? NC_SHADOW.adpWYr2 : NC_SHADOW.adpW;
      ncPrior = ((1 - wA) * (ncPrior / scale) + wA * mkt) * scale; ncSrc += '+adp';
    }
    // v2.3: demoted veterans (2nd / 3rd+ string on the live chart) - dock the prior, evidence still overrides via the blend
    var ncVd = NC_SHADOW.vetDock[p.pos];
    if (ncVd && !p.isRookie && ncSrc !== 'clay-fallback' && !(typeof window !== 'undefined' && window.SIM_NC_VETDOCK === false)) {   // v2.8: any non-rookie with a Clay-free prior, gated or not
      var vds = effectiveString(p, wk);
      if (vds != null && vds >= 2) { var vdk = Math.min(3, vds); if (ncVd[vdk] != null) { ncPrior *= ncVd[vdk]; ncSrc += '+dock' + vdk; } }
    }
    // v2.6: 2nd-year role growth - part-timer late in the rookie year (last-4-game snap share < .40) -> prior x1.2
    if (ncV2 && p.exp === 1 && /^(hist|l8)/.test(ncSrc) && !(typeof window !== 'undefined' && window.SIM_NC_YR2 === false)) {
      var spr = typeof window !== 'undefined' && window.SIM_SNAPS_PRIOR ? window.SIM_SNAPS_PRIOR[p.norm] : null;
      if (typeof spr === 'number' && spr < NC_SHADOW.yr2LowSnap.max) { ncPrior *= NC_SHADOW.yr2LowSnap.mult; ncSrc += '+yr2lo'; }
    }
    // v2.7: WR route grade above what the prior implies -> prior x1.1
    if (ncV2 && p.pos === 'WR' && !p.isRookie && /^(hist|l8)/.test(ncSrc) && !(typeof window !== 'undefined' && window.SIM_NC_GRADE === false)) {
      var gpr = typeof window !== 'undefined' && window.SIM_PFF_ROUTE_PRIOR ? window.SIM_PFF_ROUTE_PRIOR[p.norm] : null, wg = NC_SHADOW.wrGrade;
      if (typeof gpr === 'number' && gpr - (wg.c0 + wg.c1 * (ncPrior / scale)) > wg.cut) { ncPrior *= wg.mult; ncSrc += '+grade'; }
    }
    // v2.8: backup QB on the chart -> backup-level prior (unless inheriting the starter's role via the injury layer)
    if (p.pos === 'QB' && ncSrc !== 'clay-fallback' && !(iA > 1) && !(typeof window !== 'undefined' && window.SIM_NC_QB2 === false)) {
      var qd = typeof window !== 'undefined' ? window.SIM_DEPTH_2026 : null, qds = effectiveString(p, wk);
      var charted = qd && qd.teams && qd.teams[p.tm] && qd.teams[p.tm].QB && qd.teams[p.tm].QB.length;
      if (charted && (qds == null || qds >= 2)) { var qbCap = NC_SHADOW.qbBackupPpg * scale; if (ncPrior > qbCap) { ncPrior = qbCap; ncSrc += '+qb' + (qds == null ? 'x' : qds); } }
    }
    if (ncV2 && ncSrc !== 'clay-fallback' && ncPm != null) { ncPrior = (ncPm + NC_SHADOW.k * (ncPrior / scale - ncPm)) * scale; ncSrc += '+shr'; }
    // v2.15: LEARNED SEASON PRIOR (build_ridge_prior.py; backtest_season_long.py beats Clay's season sheet -10% LOYO /
    // -5% fwd; backtest_learned_prior_weekly.py: 50/50 with the hand prior -0.5% LOYO 6/7, fwd -0.48% 4/5, week 1 -1.35% 5/5).
    // Ridge on log ADP, history, age, experience, rookie pick, week-1 string, opportunity prior, 2nd-year snap share.
    if (ncV2 && ncSrc !== 'clay-fallback' && !(typeof window !== 'undefined' && window.SIM_NC_RIDGE === false)) {
      var rgp = ridgePrior(p, wk, (typeof hbo === 'number' && hbo > 0) ? hbo : null);
      var rgW = typeof NC_SHADOW.ridgeW === 'object' ? NC_SHADOW.ridgeW[p.pos] : NC_SHADOW.ridgeW;
      if (!(typeof window !== 'undefined' && window.SIM_NC_RIDGE2 === false)) {
        var rg2 = NC_SHADOW.ridgeW2;
        if (p.pos === 'RB') rgW = rg2.RB;
        else if (p.pos === 'QB' && p.adp != null && p.adp > rg2.lateQbAdp) rgW = rg2.lateQbW;
      }
      if (rgp != null && rgW > 0) {
        ncPrior = (rgW * rgp + (1 - rgW) * (ncPrior / scale)) * scale; ncSrc += '+ridge';
        if (/\+qb/.test(ncSrc)) ncPrior = Math.min(ncPrior, NC_SHADOW.qbBackupPpg * scale);   // the backup-QB cap survives the mix
      }
    }
    // v2.5: swap the live (Clay-defined) rookie ramp for the chart-defined one inside the shadow
    // v2.26: an RB's snap trend rides every later week (live sM returns 1 once the last snap week is 3+ weeks behind the week
    // projected). Rest-of-season test: -4.0% on RB rows, 6/7 seasons, forward -4.4% 4/4. Kill: window.SIM_NC_ROS = false.
    var ncRos = !!(_inj && _inj.week >= 1 && wk > _inj.week) && !(typeof window !== 'undefined' && window.SIM_NC_ROS === false);
    var ncSM = sM;
    // v2.29 PRUNE (ablate_shadow_next.py, 2026-10-02; Jack: 'take out anything that overall hurts the backtest'). On the shadow
    // base a WR's snap TREND and snap LEVEL are substitutes and the trend is the one that hurts: level only = top-150 weighted
    // -0.26% (5/7), rank order +.0076 vs neither; both = +0.40%, rank -.0019. So the WR snap trend leaves the shadow chain (the
    // live chain keeps it). The rookie-WR games 2-5 dock also goes: better on its own rows, worse on the whole board (top-150
    // weighted +0.01%, 2/7 seasons, rank -.0003). Restore both: window.SIM_NC_PRUNE = false.
    var ncPrune = !(typeof window !== 'undefined' && window.SIM_NC_PRUNE === false);
    if (ncPrune && p.pos === 'WR') ncSM = 1;
    if (ncRos && p.pos === 'RB' && NC_SHADOW.next.rbSnapCarry) {
      var rsSn = (typeof window !== 'undefined' && window.SIM_SNAPS_2026) ? window.SIM_SNAPS_2026[p.name] : null;
      var rsLast = rsSn && rsSn.w ? Math.max.apply(null, Object.keys(rsSn.w).map(Number).filter(function (w) { return w < wk; }).concat([0])) : 0;
      if (rsLast >= _inj.week - 3 && rsLast > 0) ncSM = snapMult(p, rsLast + 1);
    }
    var ncBlowOn = !(typeof window !== 'undefined' && window.SIM_NC_BLOW === false);
    var ncBlowLast = function (lw) {   // his last game had real garbage time
      var c = lw > 0 ? ctxOf(p, lw) : null;
      return !!(c && c.pl > 0 && c.gp >= CTX_MIN_GARBAGE && c.gp / c.pl >= NC_SHADOW.next.blowMinShare);
    };
    if (ncBlowOn && p.pos === 'RB' && ncSM < 1 && p.adp != null && p.adp <= NC_SHADOW.next.blowNoDockAdp) {
      var blSn = (typeof window !== 'undefined' && window.SIM_SNAPS_2026) ? window.SIM_SNAPS_2026[p.name] : null;
      var blLast = blSn && blSn.w ? Math.max.apply(null, Object.keys(blSn.w).map(Number).filter(function (w) { return w < wk; }).concat([0])) : 0;
      if (ncBlowLast(blLast)) { ncSM = 1; ncSrc += '+blow'; }
    }
    var teDockK = (p.pos === 'TE' && NC_SHADOW.next.teDockK != null && !(typeof window !== 'undefined' && window.SIM_NC_TE_DOCKS === false)) ? NC_SHADOW.next.teDockK : 1;   // 2026-10-08 TE docks at half strength (see NC_SHADOW.next.teDockK)
    if (teDockK !== 1 && Math.abs(ncSM - 1) > 1e-9) { ncSM = Math.pow(ncSM, teDockK); ncSrc += '+tedock'; }
    var ncChain = sM ? jsChain / sM * ncSM : jsChain, ncChainNoIA = mult * oppM * cbM * ncSM * rampF;   // the chain without the availability factor
    if (ncV2 && p.isRookie && !(typeof window !== 'undefined' && window.SIM_NC_RAMP === false)) {
      var rds = effectiveString(p, wk), rr = NC_SHADOW.rookieRamp, ncRamp = 1;
      if ((rds == null || rds >= 2) && gameIdx > 0 && gameIdx <= rr.length) ncRamp = rr[gameIdx - 1];
      ncChain = (sM ? jsChain / sM * ncSM : jsChain) / (rampF || 1) * ncRamp; ncChainNoIA = mult * oppM * cbM * ncSM * ncRamp;
      if (ncRamp !== 1) ncSrc += '+ramp' + gameIdx;
    }
    var ncUse = (ncV2 && ncSrc !== 'clay-fallback') ? shadowUsage(p, wk, sc) : null;
    if (ncUse && ncUse.lam > 0) ncSrc += '+xfp' + Math.round(ncUse.lam * 100);
    var ncVegEv = (ncV2 && ncSrc !== 'clay-fallback') ? shadowVegasScale(p, wk, schedule) : null;
    if (ncVegEv != null && Math.abs(ncVegEv - 1) > 1e-9) { ncUse = ncUse || { xfpPg: null, lam: 0 }; ncUse.ptsScale = ncVegEv; ncSrc += '+vegEv'; }
    // v2.21 EARLY-SEASON PRIOR (backtest_early_prior.py, 2026-09-17; Jack: 'test the early-season prior'). After exactly ONE game a wide
    // receiver's week-1 line is nearly pure noise: prior strength x5 for that one projection -> top-150 WR weighted MSE -1.87% (7/7 seasons),
    // within-week rank +.0122, pairs +0.72; forward -2.07% (5/5), rank +.0312, pairs +1.20; zero effect from game 2 on. QB and RB benefit
    // from updating early (-2.1% / -1.7% vs a frozen prior) and TE is noise, so WR only; blanket delays / tapers chosen per fold fail.
    var ncP = ncV2 ? NC_SHADOW.P[p.pos] : null, ncEp = NC_SHADOW.earlyP[p.pos];
    if (ncP != null && ncEp && !(typeof window !== 'undefined' && window.SIM_NC_EARLYP === false)) {
      var epRec = jsData().players ? jsData().players[p.norm] : null;
      if (epRec && epRec.g >= 1 && epRec.g <= ncEp.games) { ncP *= ncEp.mult; ncSrc += '+earlyP'; }
    }
    var rsS = NC_SHADOW.next.struct, rsOn = false;
    if (ncV2 && ncRos && ncSrc !== 'clay-fallback' && p.adp != null && !(typeof window !== 'undefined' && window.SIM_NC_ROS2 === false)) {
      var rsRec = jsData().players ? jsData().players[p.norm] : null;
      rsOn = !!(rsRec && rsRec.g >= rsS.minGames);
      if (rsOn) {
        var rsMid = p.adp > rsS.mid[0] && p.adp <= rsS.mid[1];
        if (ncP != null && p.pos === 'RB' && rsMid) { ncP *= rsS.rbMidP; ncSrc += '+rsP'; }
        else if (ncP != null && p.pos === 'WR' && rsMid) { ncP *= rsS.wrMidP; ncSrc += '+rsP'; }
        else if (ncP != null && p.pos === 'QB' && p.exp === 1) { ncP *= rsS.qbYr2P; ncSrc += '+rsP'; }
        var rsRk = p.isRookie && rsS.rookieP ? rsS.rookieP[p.pos] : null;
        if (ncP != null && rsRk) {
          var rsHad = (p.pos === 'RB' && rsMid) ? rsS.rbMidP : 1;   // a rookie RB drafted 61-100 already carries the larger band weight
          if (rsRk > rsHad) { ncP *= rsRk / rsHad; ncSrc += '+rsRk'; }
        }
        if (p.pos === 'WR' && p.adp > rsS.late[0] && p.adp <= rsS.late[1] && ncUse && ncUse.lam > rsS.wrLateLam) { ncUse.lam = rsS.wrLateLam; ncSrc += '+rsLam'; }
        if (ncP != null && p.pos === 'WR' && p.adp > rsS.late[0] && p.adp <= rsS.late[1] && ncPrior > 0) {
          var rsEv = (jsBasePg(p, sc, ncPrior, ncP, ncUse) * (ncP + rsRec.g) - ncP * ncPrior) / rsRec.g;   // the evidence rate on its own
          if (rsEv < ncPrior) { ncP *= rsS.wrLateColdP; ncSrc += '+rsCold'; }
        }
      }
    }
    var ncBaseW = jsBasePg(p, sc, ncPrior, ncP, ncUse), ncVk = NC_SHADOW.vacatedK[p.pos];
    if (rsOn && p.pos === 'TE' && p.adp > rsS.teBand[0] && p.adp <= rsS.teBand[1]) { ncBaseW *= rsS.teLevel; ncSrc += '+rsTE'; }
    if (rsOn && p.pos === 'RB') {
      var rsZ = rosTiltZ(), rsPz = rsZ && rsZ.plays ? rsZ.plays[p.tm] : null;
      if (typeof rsPz === 'number' && Math.abs(rsPz) > 0.05) { ncBaseW *= 1 - rsS.rbPlays * rsPz; ncSrc += '+rsVol'; }
      if (p.adp <= rsS.rbBackupAdp) { var rsDs = effectiveString(p, wk); if (rsDs != null && rsDs >= 2) { ncBaseW *= rsS.rbBackup; ncSrc += '+rsBk'; } }
    }
    // v2.22 TD-LUCK SCALE FOR THE SHADOW (2026-09-17, found tracing Justin Jefferson W2: prior 13.4 -> shadow 11.2 with no injury flag).
    // tdLuckAdj() is sized for the LIVE blend, whose evidence is points at weight g / (5 + g). The shadow's weight on POINTS is
    // (1 - lam) x g / (P + g): with the usage evidence (v2.18, lam = 1 for RB / WR after one game) and the WR one-game prior (v2.21, P = 40)
    // it is ~0, so the shadow was subtracting touchdown luck it never added. Scale the adjustment by the shadow's own weight on points.
    // The backtests of v2.18 / v2.21 never contained a luck term, so this restores parity with the graded form. Kill: window.SIM_NC_LUCKFIX = false.
    var ncLuckScale = 1;
    if (!(typeof window !== 'undefined' && window.SIM_NC_LUCKFIX === false)) {
      var lkRec = jsData().players ? jsData().players[p.norm] : null, lkG = lkRec && lkRec.g ? lkRec.g : 0;
      if (lkG > 0) {
        var lkLam = (ncUse && ncUse.lam > 0 && ncUse.xfpPg != null) ? ncUse.lam : 0, lkP = ncP != null ? ncP : JS_PRIOR_STRENGTH;
        var lkLive = lkG / (JS_PRIOR_STRENGTH + lkG), lkShadow = (1 - lkLam) * lkG / (lkP + lkG);
        ncLuckScale = lkLive > 0 ? Math.max(0, Math.min(1.5, lkShadow / lkLive)) : 1;
      }
    }
    // v2.14: veterans with NO depth-chart entry on any team, first 4 games of their season -> x0.8 (RB/WR/TE). backtest_beat_clay.py:
    // the only cut where Clay still beat the shadow that a Clay-free fix repairs (n228 -9.0% LOYO 5/7, fwd -14.6% 4/5, placebo 0/300)
    if (ncVd && !p.isRookie && ncSrc !== 'clay-fallback' && depthString(p) == null && !(typeof window !== 'undefined' && window.SIM_NC_NOCHART === false)) {
      var ncRec = jsData().players ? jsData().players[p.norm] : null, ncGp = ncRec && ncRec.wks ? ncRec.wks.filter(function (w) { return w < wk; }).length : 0;
      if (ncGp < NC_SHADOW.noChart.games) { ncBaseW *= NC_SHADOW.noChart.mult; ncSrc += '+nochart'; }
    }
    // v2.25 NEXT LAYERS (backtest_shadow_next.py, 2026-10-02; Jack: "lets do it"). Five corrections that passed on the
    // shadow itself, 2019-25, the setting picked leave-one-season-out AND forward (earlier seasons only, 2022-25),
    // judged on the rows each one touches:
    //   QB who changed teams since last season x.90              (touched rows -3.0% 5/7, forward -3.5% 3/4)
    //   QB on a team implied under 19: x(1 - .75 x (19 - implied) / 19)        (-1.7% 6/7, forward -1.0% 3/4)
    //   rookie WR in his games 2-5 x.90                                         (-1.3% 5/7, forward -2.5% 3/4)
    //   RB under 30% of his team's carries, games 2-5 x.90                      (-1.5% 6/7, forward -2.0% 4/4)
    //   WR / TE snap-share LEVEL: x(1 + .3 x (last game's share - what players at his projection usually play) / 100),
    //     clamp .7-1.4 - the trend layer reads change, this reads level      (-0.6% 6/7, forward -0.6% 3/4, rank rho +.003)
    // Stacked: top-150 weighted error -0.21% (5/7), all rows -0.49%, weekly rank rho .384 -> .388. Tested and
    // REJECTED in the same run: TE / QB usage (xFP) evidence, target-share level, QB with no ADP, WR on low-total
    // teams, a different WR evidence mix, WR under 12% of targets, WR target trend, team shift.
    // Kill: window.SIM_NC_NEXT = false.
    if (ncSrc !== 'clay-fallback' && !(typeof window !== 'undefined' && window.SIM_NC_NEXT === false)) {
      var nx = NC_SHADOW.next, nxRec = jsData().players ? jsData().players[p.norm] : null;
      var nxG = nxRec && nxRec.wks ? nxRec.wks.filter(function (w) { return w < wk; }).length : 0;
      if (_inj && _inj.week >= 1 && wk > _inj.week) {   // a later week: he will have played the games in between
        var nxGw = (schedule.gameWeeks && schedule.gameWeeks[p.tm]) || [];
        nxG += nxGw.filter(function (w) { return w >= _inj.week && w < wk && !(nxRec && nxRec.wks && nxRec.wks.indexOf(w) >= 0); }).length;
      }
      var nxEarly = nxG >= nx.early[0] && nxG <= nx.early[1];
      if (p.pos === 'QB') {
        var nxS = injSig(), nxPrev = nxS && nxS.prevTm ? nxS.prevTm[p.norm] : null;
        // later weeks x.84: rest-of-season test picked .86 / .82 in every fold (-27%, 6/7; forward -25%, 4/4)
        if (nxPrev && !p.isRookie && normTeam(nxPrev) !== p.tm) { ncBaseW *= ncRos ? nx.qbMoverFar : nx.qbMover; ncSrc += '+mover'; }
        if (slot && slot.implied < nx.lowTot[0]) { ncBaseW *= 1 - nx.lowTot[1] * (nx.lowTot[0] - slot.implied) / nx.lowTot[0]; ncSrc += '+lowtot'; }
      } else if (p.pos === 'WR' && p.isRookie && nxEarly && !ncPrune) { ncBaseW *= nx.rookieWr; ncSrc += '+rkwr'; }
      else if (p.pos === 'RB' && nxEarly) {
        var nxX = typeof window !== 'undefined' ? window.SIM_XFP_2026 : null, nxMe = nxX && nxX[p.norm];
        if (nxMe && nxMe.w && _poolByNorm) {
          var nxMine = 0, nxTeam = 0, nxWks = Object.keys(nxMe.w).filter(function (k) { return +k < wk && nxMe.w[k]; });
          nxWks.forEach(function (k) { nxMine += nxMe.w[k][4] || 0; });
          Object.keys(_poolByNorm).forEach(function (nk) {
            var q = _poolByNorm[nk]; if (!q || q.isDST || q.tm !== p.tm || q.norm !== nk) return;
            var xr = nxX[q.norm]; if (!xr || !xr.w) return;
            var ci = (xr.pos === 'QB' || q.pos === 'QB') ? 3 : 4;   // carries: skill rows [tgt, xRec, xRecYd, xRecTD, CAR, ...], QB rows [att, xPassYd, xPassTD, CAR, ...]
            nxWks.forEach(function (k) { if (xr.w[k]) nxTeam += xr.w[k][ci] || 0; });
          });
          if (nxTeam >= 20 && nxMine / nxTeam < nx.rbCarry[0]) { ncBaseW *= nx.rbCarry[1]; ncSrc += '+lowcar'; }
        }
      }
      if (p.pos === 'TE' && ncRos && nx.teTilt) {
        // tight ends on pass-heavy teams come down over the rest of the season, run-heavy teams' go up (the live number has
        // this as ROS_TILT; the shadow did not). e .04: -0.8% 5/7, forward -3.0% 3/4; no-filter run -0.4% 5/7, forward -1.8% 3/4.
        var nxZ = rosTiltZ(), nxz = nxZ && nxZ.team ? nxZ.team[p.tm] : null;
        if (typeof nxz === 'number' && Math.abs(nxz) > 0.05) { ncBaseW *= 1 - nx.teTilt * Math.min(1, (wk - _inj.week) / 2) * nxz; ncSrc += '+rtilt'; }
      }
      if ((p.pos === 'WR' || p.pos === 'TE') && nxG >= 1) {
        var nxSn = (typeof window !== 'undefined' && window.SIM_SNAPS_2026) ? window.SIM_SNAPS_2026[p.name] : null, nxT = nx.snapLvl[p.pos];
        if (nxSn && nxSn.w && nxT) {
          var nxPast = Object.keys(nxSn.w).map(Number).filter(function (w) { return w < wk && typeof nxSn.w[w] === 'number'; }).sort(function (a, b) { return b - a; });
          if (nxPast.length) {
            // the reference bins are half-PPR weekly numbers
            var nxLv = ncBaseW * ncChainNoIA * (seasonPoints(p, PRESETS.half) / Math.max(1e-9, seasonPoints(p, sc))), nxB = 0;
            while (nxB < nxT.edges.length && nxLv >= nxT.edges[nxB]) nxB++;
            // weeks past the next one read it at half strength (backtest_snap_level_horizon.py: e .3 is -0.70% 7/7 for the next
            // game, flat from 3 games out; e .15 holds -0.10 to -0.21% at every distance). A game he left hurt stays in: the next
            // game after one ran .75 of the shadow, and the dock cut that error 9.6% (6/7).
            // v2.26, later weeks by position: TE keeps e .3 (rest-of-season -1.8% 6/7, forward -2.7% 4/4), WR drops it (0/7).
            var nxFar = !!(_inj && _inj.week >= 1 && wk > _inj.week);
            var nxE = nxFar ? (ncRos ? (nx.snapEFar[p.pos] || 0) : 0.15) : nx.snapE;
            var nxC = ncBlowOn ? ctxOf(p, nxPast[0]) : null, nxShare = nxC ? ctxShare(nxSn.w[nxPast[0]], nxC, false).pct : nxSn.w[nxPast[0]];   // share on competitive plays
            var nxM = Math.min(nx.snapClamp[1], Math.max(nx.snapClamp[0], 1 + nxE * (nxShare - nxT.ref[nxB]) / 100));
            if (nxM < 1 && p.adp != null && p.adp <= nx.snapNoDockAdp && !(typeof window !== 'undefined' && window.SIM_NC_ELITE === false)) nxM = 1;
            if (nxM < 1 && ncBlowOn && p.adp != null && p.adp <= nx.blowNoDockAdp && ncBlowLast(nxPast[0])) { nxM = 1; ncSrc += '+blow'; }
            if (teDockK !== 1 && Math.abs(nxM - 1) > 0.004) { nxM = Math.pow(nxM, teDockK); if (!/\+tedock/.test(ncSrc)) ncSrc += '+tedock'; }   // 2026-10-08 TE level dock / lift at half strength
            if (Math.abs(nxM - 1) > 0.004) { ncBaseW *= nxM; ncSrc += '+snaplv'; }
          }
        }
      }
    }
    var ncOut = shadowOut(p, wk);   // v2.9: IR / PUP / Out -> 0 while the status persists
    var ncMean;
    if (ncVk != null && !(typeof window !== 'undefined' && window.SIM_NC_EXACT === false)) {
      // v2.12 EXACT SHADOW-UNIT REDISTRIBUTION: the vacated role computed from shadow numbers, not the live ratio.
      // ncFull = this player as if healthy (chain without iA); ncOwn = ncFull x availability (docks / zero / shadowOut).
      // Per team|position group: lost = sum of teammates' ncFull x (1 - availability); QB -> 85% to the next available
      // QB on the chart; RB/WR/TE -> 60% spread over healthy teammates by ncOwn x depth weight (1.6 / 1.0 / .5 by
      // effective string, unlisted .25); gained points x strength k (vacatedK), capped at the player's own number.
      // Teammates come from a per-(week, scoring) cache filled by a guarded pass over the pool.
      var ncFull = Math.max(0, ncBaseW * ncChainNoIA + tdLuckAdj(p, sc) * ncLuckScale), ncCap = ncOut ? 0 : Math.min(1, iA), ncOwn = ncFull * ncCap;
      var ck = ncCacheKey(wk, sc), C = _ncCache[ck] || (_ncCache[ck] = {});
      // rf = receiving fraction of the player's production (Clay stat mix, a shape only): splits a lost number into
      // receiving points (targets) and rushing points (carries) for the POOL rules
      var ncC = p.comps || {}, ncRp = (ncC.rec || 0) * 1 + (ncC.rcy || 0) * 0.1 + (ncC.rctd || 0) * 6, ncCp = (ncC.ry || 0) * 0.1 + (ncC.rtd || 0) * 6;
      var ncRf = (ncRp + ncCp) > 0 ? ncRp / (ncRp + ncCp) : (p.pos === 'RB' ? 0.35 : 1);
      C[p.norm] = { full: ncFull, own: ncOwn, cap: ncCap, str: effectiveString(p, wk), pos: p.pos, rf: ncRf };
      ncMean = ncOwn;
      if (!_ncPass && _poolByNorm && ncCap === 1) {
        // the pass covers the QB room for a QB, and ALL pass catchers (RB/WR/TE) for a skill player - v2.13 cross-position flow
        var grp = [], keys = Object.keys(_poolByNorm), skillP = p.pos !== 'QB';
        for (var gi2 = 0; gi2 < keys.length; gi2++) { var q = _poolByNorm[keys[gi2]]; if (q !== p && q.tm === p.tm && !q.isDST && (skillP ? !!POOL[q.pos] : q.pos === 'QB')) grp.push(q); }
        _ncPass = true;
        try { for (var gj = 0; gj < grp.length; gj++) if (!C[grp[gj].norm]) weeklyProjection(grp[gj], wk, sc, schedule); } finally { _ncPass = false; }
        var all = grp.concat([p]).filter(function (q) { return !!C[q.norm]; }), meC = C[p.norm], gained = 0, bestQb = null, bestQbC = null;
        if (!skillP) {
          var lost = 0;
          all.forEach(function (q) { var c = C[q.norm]; if (c.cap < 1) lost += c.full * (1 - c.cap); });
          if (lost > 0) {
            all.filter(function (q) { return C[q.norm].cap === 1; }).forEach(function (q) { var c = C[q.norm], s = c.str == null ? 99 : c.str; if (!bestQb || s < (bestQbC.str == null ? 99 : bestQbC.str) || (s === (bestQbC.str == null ? 99 : bestQbC.str) && c.own > bestQbC.own)) { bestQb = q; bestQbC = c; } });
            if (bestQb === p) gained = INJ_SHARE.QB * lost;   // the next man up inherits outright (no cap, as live)
          }
        } else {
          // v2.13 EXACT CROSS-POSITION FLOW in shadow units, mirroring the live POOL rules: an absent pass catcher's lost
          // receiving points go tgtSame[i] to same-position teammates by depth rank (i = rank among healthy), tgtOther to the
          // other non-RB pass catchers in proportion to their receiving level, lost rushing points carSame[i] to RBs by rank;
          // lead / sec rule by whether the absent player was the team's top receiving level; x POOL_EFF; strength k; gain <= own.
          var recLvl = function (q) { var c = C[q.norm]; return c.full * c.rf; }, topRec = 0;
          all.forEach(function (q) { if (recLvl(q) > topRec) topRec = recLvl(q); });
          var healthy = all.filter(function (q) { return C[q.norm].cap === 1; }), strOf = function (q) { var s = C[q.norm].str; return s == null ? 99 : s; };
          all.forEach(function (Z) {
            var cz = C[Z.norm]; if (cz.cap >= 1) return;
            var lostRec = cz.full * cz.rf * (1 - cz.cap), lostRush = cz.full * (1 - cz.rf) * (1 - cz.cap);
            var zSec = !(recLvl(Z) >= topRec - 1e-9), rule = POOL[Z.pos][zSec ? 'sec' : 'lead'];
            var same = healthy.filter(function (q) { return q.pos === Z.pos; }).sort(function (a, b) { var d = strOf(a) - strOf(b); return d !== 0 ? d : C[b.norm].own - C[a.norm].own; });
            var i = same.indexOf(p);
            if (i >= 0) gained += poolTgtShare(rule, Z.pos, zSec, i, p) * lostRec * POOL_EFF_T + (rule.carSame[i] || 0) * lostRush * POOL_EFF_C;
            if (rule.tgtOther > 0 && p.pos !== Z.pos && p.pos !== 'RB') {
              var others = healthy.filter(function (q) { return q.pos !== Z.pos && q.pos !== 'RB'; }), tot = 0;
              others.forEach(function (q) { tot += C[q.norm].own * C[q.norm].rf; });
              if (tot > 0) gained += rule.tgtOther * lostRec * (meC.own * meC.rf) / tot * POOL_EFF_T;
            }
          });
        }
        // QB FILL-IN (backtest_shadow_next.py): his own number OR 85% of the starter's, whichever is larger - adding
        // them projected 26.4 for fill-ins who scored 14.7 (McCarthy 27.3 / Flacco 14.1 in week 2). Kill: SIM_NC_QBMAX = false.
        var qbMax = !skillP && !(typeof window !== 'undefined' && window.SIM_NC_QBMAX === false);
        if (gained > 0) { ncMean = skillP ? ncOwn + Math.min(ncOwn, ncVk * gained) : (qbMax ? Math.max(ncOwn, gained) : ncOwn + gained); ncSrc += '+vacx'; }
      }
      ncMean = Math.max(0, ncMean);
    } else {
      // v2.11 fallback: the live boost (iA > 1) softened to boost^k on the shadow; docks (iA <= 1) as they are
      if (iA > 1 && ncVk != null && ncVk !== 1 && !(typeof window !== 'undefined' && window.SIM_NC_VAC === false)) { ncChain = ncChain * Math.pow(iA, ncVk - 1); ncSrc += '+vac'; }
      ncMean = Math.max(0, ncBaseW * ncChain + luckFull * ncLuckScale);   // the shadow keeps the full luck term (its own scale)
    }
    // v2.20 BACKUP-QB DOCK FOR WIDE RECEIVERS (backtest_qb_out_receivers.py, 2026-09-17; Jack: 'is there any projection change when there
    // are backup qbs or does the team totals account for that'). 1,443 skill weeks 2019-25 with the team's primary QB out: Vegas does move
    // (implied 23.1 -> 19.1) but WRs still land at 0.90 of projection (shadow AND Clay blend; 6 of 7 seasons under 1.0; ADP 1-60 WRs .86,
    // first game with the backup .86, later games .92). TE 1.03 and RB 1.00 = no effect. LOYO dock picks .15-.20 every fold: weighted MSE
    // -0.53% on all top-150 WR rows (6/7), -9.2% on the QB-out rows. Shipped at the low pick.
    if (p.pos === 'WR' && ncMean > 0 && !(typeof window !== 'undefined' && window.SIM_NC_QBOUT === false) && teamPrimaryQbOut(p.tm, wk)) {
      var qod = NC_SHADOW.qbOutWrDock, qStar = p.adp != null && p.adp <= qod.starAdp;   // tiered: the top-60 receivers take most of the hit (.86 vs .94 of projection)
      ncMean *= (1 - (qStar ? qod.star : qod.other)); ncSrc += '+qbout' + (qStar ? 'S' : '');
    }
    // v2.19 QB SHOOTOUT TILT (backtest_matchup_rank.py, 2026-09-17; Jack: 'maximize our in season week specific rankings'). Graded on RANK:
    // x exp(c z), z = this game's Vegas total standardized across the week's games. QB only: within-week Spearman +.0115 (6/7 seasons),
    // pairs ordered correctly +0.42 pts (6/7), points MSE +0.17%; c .04 = +.0121 / +0.48 (7/7) / +0.48%. 41 other defensive / advanced tilts failed
    // (PFF coverage, pass-rush, run-defense grades, man-rate x YPRR gap, OL grades, spread, wind, dome; re-tuned Vegas / FPA exponents).
    if (p.pos === 'QB' && ncMean > 0 && !(typeof window !== 'undefined' && window.SIM_NC_TOTAL === false)) {
      var gtz = gameTotalZ(schedule, wk, p.tm);
      if (gtz != null) { ncMean *= Math.exp(NC_SHADOW.qbTotalC * gtz); ncSrc += '+tot'; }
    }
    // VOLUME CONTEXT ON THE SHADOW (backtest_shadow_ports.py 3b, 2026-10-07): the same two WR / TE multipliers as the live number
    // (script-excess .03z everyone, att/g .04z underdogs) re-graded on the harness shadow: -0.65% (6/7), forward -0.19% (3/4), board -0.29%.
    // Kill: window.SIM_NC_VOL = false. Backup engine.js.bak_pre_ncvol_20261007.
    if (ncMean != null && mVol !== 1 && !(typeof window !== 'undefined' && window.SIM_NC_VOL === false)) { ncMean = Math.max(0, ncMean * mVol); ncSrc += '+vol'; }
    if (ncOut) { ncMean = 0; ncSrc += '+out:' + ncOut; }
    // BASE BLEND (weeks ahead): the shadow joins the model number before the market steps
    var bbW = 0, jsPre = jsMean, bbRatio = 1;
    var bbCfg = typeof window !== 'undefined' ? window.SIM_BASE_BLEND : undefined;
    if (bbCfg !== false && !p.isDST && !(inWin && winEvid) && jsMean != null && ncMean != null && ncMean > 0 && !ncOut && iA > 0) {   // window QB with cameo-only evidence: the shadow has no planned-window concept and would halve him - skip the blend for him only
      var bbwRaw = (bbCfg && bbCfg.w != null) ? bbCfg.w : BASE_BLEND.w, bbs = (bbCfg && bbCfg.scope) ? bbCfg.scope : BASE_BLEND.scope;
      var bbLater = _inj && _inj.week >= 1 && wk > _inj.week;
      if (!bbLater && BASE_BLEND.wNow && !(bbCfg && bbCfg.w != null) && !(typeof window !== 'undefined' && window.SIM_WEEKLY_NO_BLEND === false)) bbwRaw = BASE_BLEND.wNow;   // 2026-10-08 current week: shadow alone
      var bbw = typeof bbwRaw === 'number' ? bbwRaw : (bbwRaw && bbwRaw[p.pos] != null ? bbwRaw[p.pos] : 0.7);   // one weight, or per position
      if (bbw > 0 && (bbs === 'all' || bbLater)) { bbW = bbw; jsMean = bbw * ncMean + (1 - bbw) * jsMean; bbRatio = jsPre > 0 ? jsMean / jsPre : 1; }
    }
    else if (wk >= 2 && /^Questionable/i.test(String(p.injFlag || '')) && !(typeof window !== 'undefined' && window.SIM_NC_QRET === false)) {   // v2.10
      var qrRec = jsData().players ? jsData().players[p.norm] : null, playedLast = !!(qrRec && qrRec.wks && qrRec.wks.indexOf(wk - 1) >= 0);
      if (!playedLast) { ncMean *= NC_SHADOW.qRet.mult; ncSrc += '+qret'; }
    }
    var compsWk = {};
    factor = factor * mDock;  // stat lines carry the pecking-order and volume docks like every other model-side dock
    Object.keys(p.comps).forEach(function (k) {
      if (p.comps[k]) compsWk[k] = +(p.comps[k] / perGameDiv * factor).toFixed(2);
    });
    compsWk.rrtd = +(((p.comps.rtd || 0) + (p.comps.rctd || 0)) / perGameDiv * factor).toFixed(3);
    // COMPONENT LEVEL (2026-10-08, grade_stat_shape.py --level): the stat lines were Clay's per-game line x the chain = the Clay-LAYER level, while the
    // published mean is now the shadow's. Rescaling the same split to the model mean cut the per-stat error on the W1-4 locks (RB 6.26 -> 6.18, WR 5.28 -> 5.15,
    // TE 4.09 -> 4.04; QB was worse, so QB keeps Clay's level). cwScale also lifts the usage prior below. Kill: window.SIM_COMP_LEVEL = false.
    var cwScale = 1, COMP_LEVEL_POS = { RB: 1, WR: 1, TE: 1 };
    if (COMP_LEVEL_POS[p.pos] && jsMean > 0 && !(typeof window !== 'undefined' && window.SIM_COMP_LEVEL === false)) {
      var cwSum = (compsWk.py || 0) * (sc.pass_yd || 0) + (compsWk.ptd || 0) * (sc.pass_td || 0) + (compsWk.ry || 0) * (sc.rush_yd || 0) + (compsWk.rtd || 0) * (sc.rush_td || 0) + (compsWk.rec || 0) * ((sc.rec || 0) + (p.pos === 'TE' ? (sc.bonus_rec_te || 0) : 0)) + (compsWk.rcy || 0) * (sc.rec_yd || 0) + (compsWk.rctd || 0) * (sc.rec_td || 0);
      if (cwSum > 0.5) { cwScale = Math.min(2.5, Math.max(0.4, jsMean / cwSum)); if (Math.abs(cwScale - 1) > 0.002) Object.keys(compsWk).forEach(function (k) { compsWk[k] = +(compsWk[k] * cwScale).toFixed(k === 'rrtd' ? 3 : 2); }); else cwScale = 1; }
    }
    // usage-updated twin of compsWk (see COMP_USAGE): same matchup x availability factor on an in-season per-game base
    var compsU = null, cuE = compUsage(p, wk);
    if (cuE) {
      compsU = {}; Object.keys(compsWk).forEach(function (k) { compsU[k] = compsWk[k]; });
      ['ry', 'rec', 'rcy'].forEach(function (k) {
        if (p.pos === 'QB' && k !== 'ry') return;
        var prior = (p.comps[k] || 0) / perGameDiv * cwScale, act = cuE.a[k]; if (typeof act !== 'number') return;   // prior at the component level (cwScale, 2026-10-08)
        var lm = COMP_USAGE.lam[k]; if (typeof lm === 'object') lm = lm[p.pos] != null ? lm[p.pos] : 0.25;
        var ev = cuE.u ? lm * cuE.u[k] + (1 - lm) * act : act;
        if (!prior && !ev) return;                                  // never had the stat, never produced it: leave the key absent
        compsU[k] = +(((COMP_USAGE.P * prior + cuE.g * ev) / (COMP_USAGE.P + cuE.g)) * factor).toFixed(2);
      });
    }
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
      // Undo only the AVAILABILITY part (P plays, 2026-09-15): this week's lines are posted after the
      // designation and already price playing hurt, so the model side keeps its production dock (cond)
      // and the lines are not docked twice. Docks without a split: iP = iA, as before.
      var iP = Math.max(iA, Math.min(1, injPlay(p, wk)));
      Object.keys(compsWk).forEach(function (k) { compsPlay[k] = compsWk[k] / iP; });
      var anchoredPlay = propAnchorMean(p, wk, sc, compsPlay, baseM / iP, PROP_DOCKED_MAX_AGE_DAYS);
      if (anchoredPlay != null) propMean = anchoredPlay * iP;
    }
    var propSrc = propMean != null ? 'line' : null;
    var propWUsed = propMean != null ? p._propWUsed : null;
    if (propMean == null && iA > 0 && qb2Cap == null) {   // a backup QB's standing market rate is his fill-in starts' lines: never for a held backup
      // Phase 4: no lines for THIS week — fall back to the market's standing
      // per-game rate from other observed weeks, re-multiplied through this
      // week's own JS chain (Vegas/FPA/snaps/ramp/availability), confidence-weighted.
      // (jsChain carries iA, so a docked player's rate is docked here too.)
      var mkt = marketRate(p, wk, sc, schedule);
      if (mkt) {
        var mw = propWeight(p) * mkt.conf;
        if (mw > 0) {
          propMean = Math.max(0, (mw * mkt.rate + (1 - mw) * jsPg * bbRatio * mDock) * jsChain + (1 - mw) * luckAdj * mDock);   // mDock = model side only; bbRatio = the weeks-ahead shadow blend
          propSrc = 'rate';
        }
      }
    }
    // RANK MIX (backtest_best_rankings.py, 2026-09-17; Jack: build the rankings mix). A THIRD graded number beside the live mean and the
    // shadow: 50% Clay-free shadow + 50% ESPN weekly projection, then the same book anchor the live mean gets. Seven seasons, top 150,
    // ranking inside each position each week: rho .3874 vs ESPN .3777, our shadow .3776, Clay blend today .3655; better than ESPN in 6 of 7
    // seasons; best pairs ordered (64.86%), top-N hit and points captured; Clay adds nothing once ESPN is in. Never feeds the live mean.
    var espnPts = null, rmMean = null, rmFinal = null;
    var EWk = typeof window !== 'undefined' ? window.SIM_ESPN_WEEKLY : null;
    if (EWk && EWk.p && +EWk.week === +wk && !(typeof window !== 'undefined' && window.SIM_RANKMIX === false)) {
      var eRow = EWk.p[p.norm];
      if (eRow && eRow.length === 3 && eRow[2] != null && eRow[1] != null) { espnPts = eRow[2] + sc.rec * (eRow[1] - eRow[2]); if (p.pos === 'TE' && sc.bonus_rec_te) espnPts += sc.bonus_rec_te * (eRow[1] - eRow[2]); }
    }
    if (ncMean != null) {
      rmMean = (espnPts != null && espnPts > 0.5 && ncMean > 0) ? NC_SHADOW.rankMixW * ncMean + (1 - NC_SHADOW.rankMixW) * espnPts : ncMean;
      rmFinal = (propSrc === 'line' && propMean != null && propWUsed != null) ? Math.max(0, propMean + (1 - propWUsed) * (rmMean - baseM)) : rmMean;   // same market, our base swapped in
    }
    return { qb2: qb2Tag, mean: mean, mult: mult, slot: slot, comps: compsWk, compsU: compsU, gameIdx: gameIdx, jsMean: jsMean, propMean: propMean, propSrc: propSrc, propW: propWUsed, luckAdj: luckAdj, ncMean: ncMean, ncSrc: ncSrc, rmMean: rmMean, rmFinal: rmFinal, espnPts: espnPts, lcCorr: lcCorr, peck: mPeck, peckRank: peckR.rank, use: lvU, jsNoUse: jsNoUse, ret: mRet, qbf: mQbf, health: hLift, vol: mVol, bb: bbW, jsPre: jsPre,
      // WHY (2026-09-16, NOTES per-player why notes): every factor of the JS model in engine order - app.js ntWhy turns it into a points waterfall
      why: { clayPg: clayPg, clayPg0: clayPg0, health: hLift, jsBase: jsBase0, rook: mRook, jsPgRook: jsPgRook, usage: rbU, jsPg: qbInh > 0 ? jsPgOwn : jsPg, veg: mult, implied: slot.implied, avgImplied: schedule.avgImplied,
             opp: oppM, dAdj: dAdj, cbShadow: mCbS, cb1Out: mCb1, olOut: mOl, pressure: mPr, weather: mWx, ret: mRet, avail: injAvail(p, wk), qbFloor: mQbf, rosTilt: mRos, snap: mSnap, route: mRoute, ramp: rampF, iA: (qbInh > 0 && jsPgOwn > 0) ? jsPg / jsPgOwn : iA,
             luck: luckAdj, jsMean: jsMean, jsPre: jsPre, bb: bbW, ncMean: ncMean, perGameDiv: perGameDiv, peck: mPeck, peckRank: peckR.rank, vol: mVol } };
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
        ncProj: p._wk.ncMean != null ? p._wk.ncMean : null, ncSrc: p._wk.ncSrc || null,   // Clay-free shadow base
        rmProj: p._wk.rmMean != null ? p._wk.rmMean : null, rmFinal: p._wk.rmFinal != null ? p._wk.rmFinal : null, espnPts: p._wk.espnPts != null ? p._wk.espnPts : null,   // rank mix (shadow + ESPN), with books, and ESPN alone
        lcCorr: p._wk.lcCorr != null ? p._wk.lcCorr : null,   // learned-correction shadow (half-PPR points)
        useLam: p._wk.use ? p._wk.use.lam : null, usePg: p._wk.use ? p._wk.use.xfpPg : null, jsNoUse: p._wk.jsNoUse != null ? p._wk.jsNoUse : null,   // live usage evidence (usage_scorecard.py)
        peck: p._wk.peck != null ? p._wk.peck : 1, peckRank: p._wk.peckRank != null ? p._wk.peckRank : null,   // pecking-order dock (peck_scorecard.py)
        vol: p._wk.vol != null ? p._wk.vol : 1, health: p._wk.health != null ? p._wk.health : 0, useHurt: p._wk.use && p._wk.use.hurtG != null ? p._wk.use.hurtG : 0, bb: p._wk.bb || 0, jsPre: p._wk.jsPre != null ? p._wk.jsPre : null,   // 2026-10-07 layers: volume context, banged-up prior lift (pts/g), hurt games in the usage inputs
        ret: p._wk.ret != null ? p._wk.ret : 1,   // return ramp (return_scorecard.py)
        qbf: p._wk.qbf != null ? p._wk.qbf : 1,   // QB starter floor (return_scorecard.py)
        propSrc: p._wk.propSrc || null,
        mult: p._wk.mult, slot: p._wk.slot, comps: p._wk.comps, compsU: p._wk.compsU,
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

    // GAMES ALREADY PLAYED ARE NEVER RE-SIMULATED (Jack 2026-10-02). data/sim_actuals_2026.js (build_actuals.py)
    // lists the teams whose game is final each week and every pool player's real stat line; such a team-week is
    // banked at his real points under this sim's scoring (the league sim's formula: pts_std + rec x receptions +
    // (pass TD pts - 4) x pass TDs + TE premium), 0 when his team played and he has no line. Only the games still
    // to play are sampled, and the season shock / missed-game draws apply to those alone. opts.actuals overrides
    // the file (null = sample everything); kill: window.SIM_BANK_PLAYED = false.
    var ACT = opts.actuals !== undefined ? opts.actuals
      : ((typeof window !== 'undefined' && window.SIM_BANK_PLAYED !== false && window.SIM_ACTUALS_2026) || null);
    var actDone = {};
    if (ACT && ACT.done) Object.keys(ACT.done).forEach(function (w) { actDone[w] = {}; (ACT.done[w] || []).forEach(function (t) { actDone[w][normTeam(t)] = 1; }); });
    var bankedOf = function (p, w) {
      if (!ACT || !actDone[w] || !actDone[w][p.tm]) return null;                 // his team has not played that week yet
      if (!(schedule.byTeam[p.tm] && schedule.byTeam[p.tm][w])) return null;      // bye
      var row = ACT.weeks && ACT.weeks[w] ? ACT.weeks[w][p.sid] : null;
      if (!row && !p.isDST && !p.sid) {                                           // not in the Sleeper id map: his half-PPR week from the weekly stats file
        var jr = jsData().players ? jsData().players[p.norm] : null, wfv = jr && jr.wf ? jr.wf[w] : null;
        return { pts: wfv != null ? wfv : 0, row: null };
      }
      if (!row) return p.isDST ? null : { pts: 0, row: null };                    // no stat line: did not play (a missing team-defense row = data gap, sample it)
      var v = row[0];
      if (!p.isDST && p.pos !== 'K') v += (sc.rec || 0) * row[1] + ((sc.pass_td != null ? sc.pass_td : 4) - 4) * row[2] + (p.pos === 'TE' ? (sc.bonus_rec_te || 0) * row[1] : 0);
      return { pts: v, row: row };
    };

    // Precompute each player's playable weeks (null = bye / outside window).
    var pool = [];
    players.list.forEach(function (p) {
      var wks = [], banked = 0, bankedWeeks = [];
      for (var w = wFrom; w <= wTo; w++) {
        var bk = bankedOf(p, w);
        if (bk) { banked += bk.pts; bankedWeeks.push({ wk: w, pts: bk.pts, row: bk.row }); continue; }
        var wp = weeklyProjection(p, w, sc, schedule);
        if (wp && wp.mean > 0.05) wks.push({ wk: w, wi: w - wFrom, wp: wp });
      }
      if (!wks.length && !(banked > 0)) return;
      var seasonMean = wks.reduce(function (t, x) { return t + x.wp.mean; }, 0);
      if (!p.isDST && seasonMean < 0.3 * wks.length && !(banked > 0)) return; // camp bodies — noise only
      // games-played layer: Clay gm<17 without an explicit window = spread
      // risk -> Bernoulli weeks at the true per-game rate (17/gm inflation)
      var gm = Math.min(17, Math.max(2, p.clayGames || 17));
      var useInj = !p.qbWindow && !p.isDST && gm < 17;
      pool.push({
        p: p, wks: wks, seasonMean: seasonMean, banked: banked, bankedWeeks: bankedWeeks,
        shocked: !p.isDST && p.pos !== 'K',
        inf: (useInj && clayDiv(p) === 17) ? 17 / gm : 1, pPlay: useInj ? gm / 17 : 1,
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
        var e = pool[i], tot = e.banked, wks = e.wks;   // real points for the games already played
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
        player: e.p, games: e.wks.length + e.bankedWeeks.length, gamesSim: e.wks.length, banked: e.banked, bankedWeeks: e.bankedWeeks,   // games = scheduled in the range (played + to play)
        seasonProj: e.seasonMean * e.pPlay + e.banked, clayPts: seasonPoints(e.p, sc),   // real points so far + per-game means x games-played prob
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
  // playoff rounds for a field of n (byes included): 2 -> 1, 3-4 -> 2, 5-8 -> 3, 9-16 -> 4
  function bracketRounds(n) { var r = 0, p = 1; while (p < n) { p *= 2; r++; } return r; }
  // standard bracket seed order for the next power of two >= n: 8 -> [1,8,4,5,2,7,3,6]
  function bracketOrder(n) {
    var order = [1];
    while (order.length < n) {
      var m = order.length * 2 + 1;
      order = order.reduce(function (a, s) { a.push(s, m - s); return a; }, []);
    }
    return order;
  }

  function simLeague(opts) {
    var sims = opts.sims || 100, sc = opts.scoring, rng = makeRng(opts.seed != null ? opts.seed : null);
    var schedule = opts.schedule, players = opts.players;
    var teams = opts.teams, pairsByWeek = opts.pairsByWeek;
    var regWeeks = opts.regWeeks;           // array of week numbers left to sim
    var playoffTeams = opts.playoffTeams || 6;
    var playoffStart = opts.playoffStart || 15;
    var reseed = !!opts.playoffReseed;
    var lineupSlots = opts.lineupSlots;     // e.g. ['QB','RB','RB','WR','WR','TE','FLEX','K','DEF']
    // unavailable: {sid: 'out'|'ir'} — 'out' = ruled out for the CURRENT week
    // only; 'ir' = gone for every remaining week (re-pulled on each league load,
    // so activations come back automatically). No Questionable/Doubtful guessing.
    var unavailable = opts.unavailable || {};
    var currentWeek = opts.currentWeek || (regWeeks.length ? regWeeks[0] : 1);
    // 2026-09-27 (Jack): games already played in the CURRENT week (Thursday) are banked at
    // the real score — lockedTeams {tm: 1} = game final, lockedPts {sid: league-scored pts}
    // (absent = 0, he did not play). Lineups are still picked by the pre-game projection.
    var lockedPts = opts.lockedPts || null, lockedTeams = opts.lockedTeams || {};
    // lockedReal {rosterId: {sid: {start, pts}}} = the manager's REAL lineup call on a player whose
    // game is final: started -> forced into the lineup at his real points, benched -> cannot start.
    var lockedReal = opts.lockedReal || null;
    function mkCand(p, wk, rid) {
      var wp = weeklyProjection(p, wk, sc, schedule);
      var isLocked = lockedPts && wk === currentWeek && lockedTeams[p.tm];
      if (isLocked) {
        var fb = lockedPts[p.sid] != null ? lockedPts[p.sid] : 0;
        var real = lockedReal && rid != null && lockedReal[rid] ? lockedReal[rid][p.sid] : null;
        if (real) {
          if (!real.start) return null;
          var pts = real.pts != null ? real.pts : fb;
          return { p: p, wp: wp || { mean: pts, sd: 0 }, locked: pts, force: 1 };
        }
        if (lockedReal && rid == null) return null; // game is over — nobody claims him off waivers now
        return wp ? { p: p, wp: wp, locked: fb } : null;
      }
      return wp ? { p: p, wp: wp } : null;
    }

    // Precompute each team's optimal starters + weekly projections per week.
    // Starters chosen by projected mean (that's how real managers set lineups).
    var allWeeks = regWeeks.slice(), poRounds = bracketRounds(playoffTeams);
    for (var w = playoffStart; w < playoffStart + poRounds; w++) allWeeks.push(w);
    var candsBy = {}; // candsBy[rosterId][week] = sorted candidate list
    teams.forEach(function (t) {
      candsBy[t.rosterId] = {};
      var roster = t.playerIds.map(function (sid) { return players.bySid[sid]; }).filter(Boolean)
        .filter(function (p) { return unavailable[p.sid] !== 'ir'; });
      allWeeks.forEach(function (wk) {
        candsBy[t.rosterId][wk] = roster.filter(function (p) {
          return !(wk === currentWeek && unavailable[p.sid] === 'out');
        }).map(function (p) { return mkCand(p, wk, t.rosterId); }).filter(Boolean).sort(function (a, b) { return ((b.force || 0) - (a.force || 0)) || (effMean(b.wp) - effMean(a.wp)); });
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
      }).map(function (p) { return mkCand(p, wk); }).filter(Boolean).sort(function (a, b) { return ((b.force || 0) - (a.force || 0)) || (effMean(b.wp) - effMean(a.wp)); });
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
            cands.sort(function (a, b) { return ((b.force || 0) - (a.force || 0)) || (effMean(b.wp) - effMean(a.wp)); });
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
        if (changed) cands.sort(function (a, b) { return ((b.force || 0) - (a.force || 0)) || (effMean(b.wp) - effMean(a.wp)); });
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
      for (var w2 = playoffStart; w2 < playoffStart + poRounds; w2++) {
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
      (lineup || []).forEach(function (slot) { total += slot.locked != null ? slot.locked : samplePlayerScore(slot.p, slot.wp, env, rng2, getShock(slot.p)); });
      return total;
    }

    function playWeekScore(rosterId, wk, env, rng2) {
      return teamScore(prep[rosterId][wk], env, rng2);
    }

    // Fixed (non-reseeding) bracket for ANY field size, the ESPN/Sleeper/Yahoo default: the field is padded to
    // the next power of two in standard seed order (1v8, 4v5, 2v7, 3v6 ...) and the empty slots are first-round
    // byes for the top seeds — 7 teams = seed 1 bye, 6 = seeds 1-2, 5 = seeds 1-3, 12 = seeds 1-4. Same pairings
    // as the old hard-coded 4/6/8 brackets; 2026-10-05 (Jack's 14-team, 7-spot league) any other size used to
    // fall into a 1v2/3v4 duel-down with no byes credited.
    function simBracket(seeds, startWk, prepIgnored, schedule2, rng2, tally2) {
      var n = seeds.length;
      if (n < 2) return seeds[0];
      var slots = bracketOrder(n).map(function (s) { return s <= n ? seeds[s - 1] : null; });
      var wk = startWk;
      while (slots.length > 1) {
        // re-seeding leagues (opts.playoffReseed: ESPN playoffReseed / Sleeper playoff_seed_type 1): after round 1
        // the best surviving seed plays the worst, second-best the second-worst, ...
        if (reseed && wk > startWk && slots.length > 2) {
          var srt = slots.slice().sort(function (x, y) { return seeds.indexOf(x) - seeds.indexOf(y); }), rs = [];
          for (var q = 0; q < srt.length / 2; q++) rs.push(srt[q], srt[srt.length - 1 - q]);
          slots = rs;
        }
        if (slots.length === 2) slots.forEach(function (r) { if (r != null) tally2[r].finals++; });
        var next = [];
        for (var i = 0; i < slots.length; i += 2) {
          var a = slots[i], b = slots[i + 1];
          if (a == null || b == null) {                       // bye: the seed advances without a game
            var adv = a == null ? b : a;
            if (adv != null && wk === startWk) tally2[adv].byes++;
            next.push(adv);
          } else next.push(duel(a, b, wk));
        }
        slots = next; wk++;
      }
      return slots[0];

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
        inf: (useInj && clayDiv(p) === 17) ? 17 / gm : 1, pPlay: useInj ? gm / 17 : 1
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

  // ---------- BEST BALL: OVERALL-FIELD STANDINGS ----------
  // Tournament-wide regular-season race (Underdog pays the top overall
  // Round-1 scores). The field is every roster in play — the user's entries
  // plus the rest of the tournament, either all ~672k real entries or a
  // WEIGHTED sample (weight[q] = how many real entries squad q stands for).
  // banked[q] = points already scored (weeks < fromWeek); weeks fromWeek..regTo
  // are sampled with the same shared draws / season shock / missed-game
  // layers as simBestBall, so a player on 40,000 rosters scores identically
  // on all of them. Per sim, each `mine` squad's rank = 1 + the weight of
  // squads that outscored it. Standard lineup only (1QB/2RB/3WR/1TE/FLEX).
  //
  // Rosters come flat (a 672k-team field can't be 672k JS arrays):
  //   roster = { players: [engine player...], start: Int32Array(nQ+1),
  //              ix: Int32Array }   squad q = ix[start[q] .. start[q+1])
  // (opts.squads — arrays of player refs — is still accepted for small fields.)
  // cutRanks: overall places whose score is tracked (current + simmed final).
  function bbRosterOf(squads) {
    var players = [], pIx = {}, start = new Int32Array(squads.length + 1), flat = [];
    for (var q = 0; q < squads.length; q++) {
      start[q] = flat.length;
      for (var j = 0; j < squads[q].length; j++) {
        var p = squads[q][j], k = p.sid || p.norm;
        if (pIx[k] === undefined) { pIx[k] = players.length; players.push(p); }
        flat.push(pIx[k]);
      }
    }
    start[squads.length] = flat.length;
    return { players: players, start: start, ix: Int32Array.from(flat) };
  }
  var BB_POS_CODE = { QB: 0, RB: 1, WR: 2, TE: 3, FB: 1 }; // Underdog slots fullbacks as RBs

  // Sleeper name index over ALL NFL skill players — not just the projection
  // pool — so a roster's fringe players (no projection, or a pool player with
  // no Sleeper id) still get their REAL points in completed weeks. Same three
  // tiers the field-scoring script validated on 12M BBM picks: name|pos,
  // collapsed name|pos (hyphen/space variants), then unique initial+last|pos.
  // Name twins resolve to whoever is on a team / active.
  function bbSleeperIndex(all) {
    var byNP = {}, byCP = {}, byIP = {};
    Object.keys(all).forEach(function (pid) {
      var p = all[pid];
      if (!p || typeof p !== 'object') return;
      var pos = p.position === 'FB' ? 'RB' : p.position;
      if (pos !== 'QB' && pos !== 'RB' && pos !== 'WR' && pos !== 'TE') return;
      var nm = norm((p.first_name || '') + ' ' + (p.last_name || ''));
      if (!nm) return;
      var rec = { sid: String(pid), team: p.team || null, live: (p.team ? 2 : 0) + (p.active ? 1 : 0) };
      var k1 = nm + '|' + pos, k2 = nm.replace(/ /g, '') + '|' + pos;
      if (!byNP[k1] || rec.live > byNP[k1].live) byNP[k1] = rec;
      if (!byCP[k2] || rec.live > byCP[k2].live) byCP[k2] = rec;
      var parts = nm.split(' ');
      if (parts.length >= 2) {
        var ik = parts[0].charAt(0) + '|' + parts.slice(1).join(' ') + '|' + pos;
        (byIP[ik] = byIP[ik] || []).push(rec);
      }
    });
    return { byNP: byNP, byCP: byCP, byIP: byIP };
  }
  // Underdog lists a few players under a nickname nobody else uses.
  var BB_NAME_ALIAS = { 'hollywood brown': 'marquise brown', 'bam knight': 'zonovan knight', 'juice wells': 'antwane wells' };
  function bbAliasNorm(name) {
    var nk = norm(name);
    return BB_NAME_ALIAS[nk] || nk;
  }
  function bbResolveSid(index, name, pos) {
    pos = pos === 'FB' ? 'RB' : pos;
    var nk = bbAliasNorm(name);
    var hit = index.byNP[nk + '|' + pos] || index.byCP[nk.replace(/ /g, '') + '|' + pos];
    if (hit) return hit;
    var parts = nk.split(' ');
    if (parts.length < 2) return null;
    var c = index.byIP[parts[0].charAt(0) + '|' + parts.slice(1).join(' ') + '|' + pos] || [];
    if (c.length > 1) c = c.filter(function (r) { return r.team; });
    return c.length === 1 ? c[0] : null;
  }
  // best-ball lineup total for one squad from a per-player value array
  function bbLineup(ix, from, to, vals, posC) {
    var qb = 0, r0 = 0, r1 = 0, r2 = 0, w0 = 0, w1 = 0, w2 = 0, w3 = 0, t0 = 0, t1 = 0;
    for (var i = from; i < to; i++) {
      var e = ix[i], v = vals[e];
      if (v <= 0) continue;
      switch (posC[e]) {
        case 0: if (v > qb) qb = v; break;
        case 1:
          if (v > r0) { r2 = r1; r1 = r0; r0 = v; }
          else if (v > r1) { r2 = r1; r1 = v; }
          else if (v > r2) r2 = v;
          break;
        case 2:
          if (v > w0) { w3 = w2; w2 = w1; w1 = w0; w0 = v; }
          else if (v > w1) { w3 = w2; w2 = w1; w1 = v; }
          else if (v > w2) { w3 = w2; w2 = v; }
          else if (v > w3) w3 = v;
          break;
        case 3:
          if (v > t0) { t1 = t0; t0 = v; }
          else if (v > t1) t1 = v;
          break;
      }
    }
    var flex = r2 > w3 ? r2 : w3;
    if (t1 > flex) flex = t1;
    return qb + r0 + r1 + w0 + w1 + w2 + t0 + flex;
  }
  // Add one REAL week to every squad's banked total: vals[i] = that week's
  // actual points for roster.players[i]. Used to roll a roster file forward
  // week by week without pulling the field again.
  function bbFieldAddWeek(roster, vals, banked, sign) {
    var posC = roster.players.map(function (p) { return BB_POS_CODE[p.pos] != null ? BB_POS_CODE[p.pos] : 4; });
    var start = roster.start, ix = roster.ix;
    var sg = sign < 0 ? -1 : 1; // -1 takes a (part-)week back out
    for (var q = 0; q < banked.length; q++) banked[q] += sg * bbLineup(ix, start[q], start[q + 1], vals, posC);
  }

  // Stepper so a big field can run in slices without freezing the page:
  //   var run = bbFieldRun(opts); while (!run.done()) run.step(1); run.result()
  // roster.players may hold STUBS ({name, pos, stub:true}) — rostered players
  // with no projection: they never sim, but keep their place on the roster so
  // real weeks score them.
  // Part-played current week: opts.lockMask[e] = 1 means player e's game this
  // week (fromWeek) is over — he scores opts.lockVals[e] (his real points) in
  // every sim instead of being sampled, and still competes for a lineup slot
  // with teammates who haven't played yet. "Now" totals include those points.
  function bbFieldRun(opts) {
    var sims = opts.sims || 200, sc = opts.scoring || PRESETS.half;
    var rng = makeRng(opts.seed != null ? opts.seed : null);
    var schedule = opts.schedule, players = opts.players;
    var regTo = Math.min(17, Math.max(1, opts.regTo || 14));
    var fromWeek = Math.max(1, opts.fromWeek || 1);
    var roster = opts.roster || bbRosterOf(opts.squads);
    var banked = opts.banked, weight = opts.weight, mine = opts.mine;
    var unavailable = opts.unavailable || {};
    var cutRanks = (opts.cutRanks || []).slice().sort(function (a, b) { return a - b; });
    var start = roster.start, ix = roster.ix;
    var nQ = start.length - 1, nW = Math.max(0, regTo - fromWeek + 1), nE = roster.players.length;
    // opts.playoff (needs opts.all): after each sim's regular season, play the
    // tournament out — see playoffPass. Only while Round 1 is still running.
    var po = (opts.playoff && opts.all && nW > 0) ? opts.playoff : null;
    var lastWk = po ? Math.max(regTo, Math.min(18, po.lastWeek || regTo + 3)) : regTo;
    var nWA = Math.max(0, lastWk - fromWeek + 1); // weeks sampled (regular + playoff)

    var lockMask = (nW > 0 && opts.lockMask) || null, lockVals = opts.lockVals || null;
    var nowVals = null;
    if (lockMask) {
      nowVals = new Float64Array(Math.max(1, nE));
      for (var l0 = 0; l0 < nE; l0++) if (lockMask[l0]) nowVals[l0] = lockVals[l0];
    }
    var posC = new Array(nE);
    var entries = roster.players.map(function (p, e) {
      posC[e] = BB_POS_CODE[p.pos] != null ? BB_POS_CODE[p.pos] : 4;
      var wps = new Array(nWA), any = false;
      for (var w = 0; w < nWA && !p.stub; w++) {
        var wp = weeklyProjection(p, fromWeek + w, sc, schedule);
        wps[w] = (wp && wp.mean > 0.05) ? wp : null;
        if (wps[w]) any = true;
      }
      var gm = Math.min(17, Math.max(2, p.clayGames || 17));
      var useInj = !p.qbWindow && !p.isDST && gm < 17;
      return {
        p: p, wps: any ? wps : null,
        unav: p.sid != null ? (unavailable[p.sid] || null) : null,
        shocked: !p.isDST && p.pos !== 'K',
        inf: (useInj && clayDiv(p) === 17) ? 17 / gm : 1, pPlay: useInj ? gm / 17 : 1
      };
    });
    // sampled scores, one contiguous slice per week: S[w][e]
    var S = [];
    for (var w0 = 0; w0 < nWA; w0++) S.push(new Float64Array(Math.max(1, nE)));
    var envs = new Array(nWA);

    // One pass over the field ranks the tracked squads and reads the cut
    // lines — no nQ-sized sort. Tracked totals sorted ascending in `a`;
    // bucket[k] = field weight sitting above exactly k of them. Cut lines
    // come off a 0.05-pt histogram of every squad's total.
    var T = mine.length, a = new Float64Array(T), mt = new Float64Array(T);
    var bucket = new Float64Array(T + 1), suf = new Float64Array(T + 2);
    var HB = 20, HN = 4096 * HB, hist = new Float64Array(HN);
    var cutOut = new Float64Array(cutRanks.length), rankOut = new Float64Array(T);
    // opts.all = { payPlace, payAmt } turns on per-squad results for the WHOLE
    // field (leaderboard view): every squad's rank each sim is read off the
    // same histogram — exact to a 0.05-pt bin, ties inside a bin split at the
    // middle — and folded into running sums, so 672k squads cost ~30 bytes
    // each rather than a rank per sim. sumLogRank -> exp(mean) is the team's
    // TYPICAL finish (geometric mean of its simmed ranks, close to the median);
    // ranking teams by average projected total instead would flatter everyone
    // near the top — averages bunch far tighter than any single season does.
    var all = opts.all || null, totS = null, above = null, A = null, lastPaid = 0;
    if (all) {
      totS = new Float64Array(nQ); above = new Float64Array(HN);
      A = { nowTot: new Float64Array(nQ), sumTot: new Float64Array(nQ), sumLogRank: new Float64Array(nQ), best: new Int32Array(nQ).fill(1073741824),
            top100: new Uint32Array(nQ), top1k: new Uint32Array(nQ), cash: new Uint32Array(nQ), ev: new Float64Array(nQ) };
      lastPaid = all.payPlace.length ? all.payPlace[all.payPlace.length - 1] : 0;
    }
    function payoutOf(rank) {
      var r = Math.round(rank), pl = all.payPlace, lo = 0, hi = pl.length;
      while (lo < hi) { var mid = (lo + hi) >> 1; if (pl[mid] < r) lo = mid + 1; else hi = mid; }
      return lo < pl.length ? all.payAmt[lo] : 0;
    }
    function total(q, live) {
      var t = banked[q];
      if (live) for (var w = 0; w < nW; w++) t += bbLineup(ix, start[q], start[q + 1], S[w], posC);
      else if (nowVals) t += bbLineup(ix, start[q], start[q + 1], nowVals, posC);
      return t;
    }
    function binOf(x) { var h = (x * HB) | 0; return h < 0 ? 0 : (h >= HN ? HN - 1 : h); }
    function rankPass(live) {
      for (var m = 0; m < T; m++) { mt[m] = total(mine[m], live); a[m] = mt[m]; }
      a.sort();
      bucket.fill(0);
      hist.fill(0);
      for (var q = 0; q < nQ; q++) {
        var wq = weight[q];
        if (wq <= 0) continue;
        var x = total(q, live), lo = 0, hi = T;
        while (lo < hi) { var mid = (lo + hi) >> 1; if (a[mid] < x) lo = mid + 1; else hi = mid; }
        bucket[lo] += wq;
        hist[binOf(x)] += wq;
        if (all) totS[q] = x;
      }
      suf[T + 1] = 0;
      for (var k = T; k >= 0; k--) suf[k] = suf[k + 1] + bucket[k];
      for (var m2 = 0; m2 < T; m2++) {
        var lo2 = 0, hi2 = T, x2 = mt[m2];
        while (lo2 < hi2) { var mid2 = (lo2 + hi2) >> 1; if (a[mid2] <= x2) lo2 = mid2 + 1; else hi2 = mid2; }
        rankOut[m2] = 1 + suf[lo2]; // lo2 = tracked totals <= x2; squads above x2 sit above more than that
      }
      var c = 0, ci = 0;
      for (var b = HN - 1; b >= 0; b--) {
        if (all) above[b] = c;
        else if (ci >= cutRanks.length) break;
        c += hist[b];
        while (ci < cutRanks.length && c >= cutRanks[ci]) { cutOut[ci] = b / HB; ci++; }
      }
      for (; ci < cutRanks.length; ci++) cutOut[ci] = 0;
      if (!all) return;
      if (!live) { A.nowTot.set(totS); return; }
      for (var q2 = 0; q2 < nQ; q2++) {
        var w2 = weight[q2];
        if (w2 <= 0) continue;
        var x3 = totS[q2], h3 = binOf(x3), top = 1 + above[h3], midRank = top + (hist[h3] - w2) * 0.5;
        A.sumTot[q2] += x3;
        A.sumLogRank[q2] += Math.log(midRank);
        if (top < A.best[q2]) A.best[q2] = top;
        if (midRank <= 1000) { A.top1k[q2]++; if (midRank <= 100) A.top100[q2]++; }
        if (midRank <= lastPaid) { var py = payoutOf(midRank); if (py > 0) { A.cash[q2]++; A.ev[q2] += py; } }
      }
    }

    // ---- PLAYOFFS (same rosters, like the real tournament) ----
    // po = { pod: Int32Array(nQ) draft-group index per squad (-1 = unknown),
    //        adv1: teams advancing per draft group (2),
    //        g2, g3: Round-2 / Round-3 group sizes (14, 12), one winner each,
    //        r2Prize: paid to every Round-2 team that goes no further,
    //        r3Prize: [by place in the Round-3 group, index 0 = winner (unused)],
    //        finalPrize: [by final place, index 0 = 1st] }
    // Each sim: top `adv1` of every draft group by regular-season total go
    // through; they are dealt at random into Round-2 groups scored on the
    // first playoff week, winners dealt at random into Round-3 groups scored
    // on the next, and those winners meet in one final scored on the last.
    // Groups are re-dealt every sim (the real draw isn't known until it
    // happens), so the odds average over every draw a team could get.
    // po.reps (default 1): the playoffs are replayed that many times per sim —
    // fresh player scores for the playoff weeks, fresh group draws — for the
    // SAME set of advancers. The regular season is the expensive part (every
    // roster, every week); a playoff replay is ~1% of that. And the prize EV
    // needs it: one team takes $2M each run, so a portfolio's playoff payout
    // swings by tens of thousands of dollars between single runs. Each replay
    // counts 1/reps, so the per-sim sums stay "per regular season".
    var podStart = null, podMem = null, nPods = 0, advBuf = null, scoreBuf = null, grp = null;
    var poTot = { adv: 0, r3: 0, fin: 0 };
    if (po) {
      var pod = po.pod, cnt, q0;
      for (q0 = 0; q0 < nQ; q0++) if (weight[q0] > 0 && pod[q0] >= nPods) nPods = pod[q0] + 1;
      cnt = new Int32Array(nPods + 1);
      for (q0 = 0; q0 < nQ; q0++) if (weight[q0] > 0 && pod[q0] >= 0) cnt[pod[q0] + 1]++;
      for (var pc = 0; pc < nPods; pc++) cnt[pc + 1] += cnt[pc];
      podStart = cnt; podMem = new Int32Array(podStart[nPods]);
      var fill = new Int32Array(nPods);
      for (q0 = 0; q0 < nQ; q0++) if (weight[q0] > 0 && pod[q0] >= 0) podMem[podStart[pod[q0]] + fill[pod[q0]]++] = q0;
      advBuf = new Int32Array(nPods * po.adv1 + 16); scoreBuf = new Float64Array(advBuf.length);
      advAll = new Int32Array(advBuf.length);
      grp = new Int32Array(Math.max(po.g2, po.g3) + 1);
      A.adv1 = new Uint32Array(nQ); A.adv2 = new Float64Array(nQ); A.adv3 = new Float64Array(nQ);
      A.win = new Float64Array(nQ); A.finSum = new Float64Array(nQ); A.finBest = new Int32Array(nQ).fill(1073741824);
      A.poEv = new Float64Array(nQ);
    }
    var advAll = advAll || null, scaleOf = new Float64Array(Math.max(1, nE));
    // fresh player scores for the playoff weeks only (same season shock)
    function redrawPlayoffWeeks() {
      for (var w = nW; w < nWA; w++) envs[w] = drawWeekEnv(schedule.byWeek[fromWeek + w] || [], rng, players);
      for (var e = 0; e < nE; e++) {
        var en = entries[e];
        if (!en.wps || en.unav === 'ir') continue;
        for (var w2 = nW; w2 < nWA; w2++) {
          var wp = en.wps[w2];
          S[w2][e] = (!wp || (en.pPlay < 1 && rng.rand() >= en.pPlay)) ? 0 : samplePlayerScore(en.p, wp, envs[w2], rng, scaleOf[e]);
        }
      }
    }
    function shuffle(arr, n) {
      for (var i = n - 1; i > 0; i--) { var j = (rng.rand() * (i + 1)) | 0, t = arr[i]; arr[i] = arr[j]; arr[j] = t; }
    }
    function playoffPass() {
      // Round 1 (once per sim): top adv1 of each draft group on regular-season total
      var nA0 = 0, k, i, j;
      for (var p = 0; p < nPods; p++) {
        var s0 = podStart[p], s1 = podStart[p + 1];
        for (k = 0; k < po.adv1 && k < s1 - s0; k++) {
          var bi = -1, bv = -1;
          for (i = s0; i < s1; i++) {
            var q = podMem[i], dup = false;
            for (j = nA0 - k; j < nA0; j++) if (advAll[j] === q) { dup = true; break; }
            if (!dup && totS[q] > bv) { bv = totS[q]; bi = q; }
          }
          if (bi < 0) break;
          advAll[nA0++] = bi;
          A.adv1[bi]++;
        }
      }
      var reps = Math.max(1, po.reps | 0), inv = 1 / reps;
      for (var rp = 0; rp < reps; rp++) {
        if (rp > 0) redrawPlayoffWeeks();
        advBuf.set(advAll.subarray(0, nA0));
        playoffRounds(nA0, inv);
      }
    }
    function playoffRounds(nA, inv) {
      var i, j;
      var wkIdx = nW; // first playoff week's slot in S
      // Round 2: random groups of g2, best score in the first playoff week wins
      shuffle(advBuf, nA);
      var nB = 0, base, m, best, bq, sc2, wi;
      for (base = 0; base < nA; base += po.g2) {
        m = Math.min(po.g2, nA - base); best = -1; wi = base;
        for (i = 0; i < m; i++) {
          bq = advBuf[base + i];
          sc2 = bbLineup(ix, start[bq], start[bq + 1], S[wkIdx], posC);
          if (sc2 > best) { best = sc2; wi = base + i; }
        }
        for (i = 0; i < m; i++) if (base + i !== wi) A.poEv[advBuf[base + i]] += po.r2Prize * inv;
        var wq = advBuf[wi];
        A.adv2[wq] += inv;
        advBuf[nB++] = wq; // winners packed to the front (nB never passes base)
      }
      // Round 3: random groups of g3 on the second playoff week; place in the
      // group decides the consolation prize
      shuffle(advBuf, nB);
      var nC = 0;
      for (base = 0; base < nB; base += po.g3) {
        m = Math.min(po.g3, nB - base);
        for (i = 0; i < m; i++) {
          bq = advBuf[base + i];
          scoreBuf[i] = bbLineup(ix, start[bq], start[bq + 1], S[wkIdx + 1], posC);
          grp[i] = i;
        }
        for (i = 1; i < m; i++) { // insertion sort, best first
          var gi = grp[i], gs = scoreBuf[gi];
          for (j = i - 1; j >= 0 && scoreBuf[grp[j]] < gs; j--) grp[j + 1] = grp[j];
          grp[j + 1] = gi;
        }
        var winner = advBuf[base + grp[0]];
        for (i = 1; i < m; i++) A.poEv[advBuf[base + grp[i]]] += inv * (i < po.r3Prize.length ? po.r3Prize[i] : po.r3Prize[po.r3Prize.length - 1]);
        A.adv3[winner] += inv;
        advBuf[nC++] = winner; // packed to the front (nC never passes base)
      }
      // Final: everyone left, ranked on the last playoff week
      var ord = new Array(nC);
      for (i = 0; i < nC; i++) {
        bq = advBuf[i];
        scoreBuf[i] = bbLineup(ix, start[bq], start[bq + 1], S[wkIdx + 2], posC);
        ord[i] = i;
      }
      ord.sort(function (x, y) { return scoreBuf[y] - scoreBuf[x]; });
      for (i = 0; i < nC; i++) {
        bq = advBuf[ord[i]];
        var place = i + 1;
        A.finSum[bq] += place * inv;
        if (place < A.finBest[bq]) A.finBest[bq] = place;
        if (place === 1) A.win[bq] += inv;
        A.poEv[bq] += inv * (i < po.finalPrize.length ? po.finalPrize[i] : po.finalPrize[po.finalPrize.length - 1]);
      }
      poTot.adv += nA * inv; poTot.r3 += nB * inv; poTot.fin += nC * inv;
    }

    // standings as they are right now (banked points only)
    rankPass(false);
    var res = mine.map(function (q, m) {
      return { squad: q, banked: mt[m], curRank: rankOut[m],
               totals: new Float64Array(sims), ranks: new Float64Array(sims) };
    });
    var cuts = cutRanks.map(function (r, i) { return { rank: r, cur: cutOut[i], sims: new Float64Array(sims) }; });
    var fieldW = suf[0], sDone = 0;

    function oneSim(s) {
      for (var w1 = 0; w1 < nWA; w1++) envs[w1] = drawWeekEnv(schedule.byWeek[fromWeek + w1] || [], rng, players);
      for (var e = 0; e < nE; e++) {
        var en = entries[e], locked = lockMask && lockMask[e];
        if (!en.wps || en.unav === 'ir') {
          for (var wz = 0; wz < nWA; wz++) S[wz][e] = 0;
        } else {
          var scale = (en.shocked ? drawSeasonShock(rng, halfPtsOf(en.p)) : 1) * en.inf;
          scaleOf[e] = scale;
          for (var w2 = locked ? 1 : 0; w2 < nWA; w2++) {
            var wp2 = en.wps[w2];
            S[w2][e] = (!wp2 || (en.unav === 'out' && w2 === 0) || (en.pPlay < 1 && rng.rand() >= en.pPlay)) ? 0
              : samplePlayerScore(en.p, wp2, envs[w2], rng, scale);
          }
        }
        if (locked) S[0][e] = lockVals[e]; // his game is over: real points, every sim
      }
      rankPass(true);
      if (po) playoffPass();
      for (var m = 0; m < T; m++) { res[m].totals[s] = mt[m]; res[m].ranks[s] = rankOut[m]; }
      for (var c2 = 0; c2 < cuts.length; c2++) cuts[c2].sims[s] = cutOut[c2];
    }
    function dist(arr) {
      var d = arr.slice().sort(), sum = 0;
      for (var i = 0; i < d.length; i++) sum += d[i];
      return { mean: sum / d.length, p10: pct(d, 0.10), p25: pct(d, 0.25), p50: pct(d, 0.50),
               p75: pct(d, 0.75), p90: pct(d, 0.90), min: d[0], max: d[d.length - 1] };
    }
    return {
      sims: sims,
      done: function () { return sDone >= sims; },
      step: function (n) {
        for (var k = 0; k < n && sDone < sims; k++) oneSim(sDone++);
        return sDone;
      },
      result: function () {
        return {
          sims: sims, fromWeek: fromWeek, regTo: regTo, weeksSimmed: nW,
          nSquads: nQ, fieldWeight: fieldW, nPlayers: nE,
          teams: res.map(function (r) {
            return { squad: r.squad, banked: r.banked, curRank: r.curRank,
                     totals: r.totals, ranks: r.ranks, total: dist(r.totals), rank: dist(r.ranks) };
          }),
          cuts: cuts.map(function (c) { return { rank: c.rank, cur: c.cur, final: dist(c.sims), raw: c.sims }; }),
          all: A, simsDone: sDone,
          playoff: po ? { nPods: nPods, advancers: poTot.adv / Math.max(1, sDone), round3: poTot.r3 / Math.max(1, sDone),
                          finalists: poTot.fin / Math.max(1, sDone) } : null
        };
      }
    };
  }
  function simBBField(opts) {
    var run = bbFieldRun(opts);
    run.step(run.sims);
    return run.result();
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
    applyInSeasonInjuries: applyInSeasonInjuries, injAdj: injAdj, injAvail: injAvail, injGroup: injGroup, linesUp: linesUp, injSignalInfo: injSignalInfo, bangedDock: bangedDock, returnDock: returnDock, injuryState: injuryState, newsFlags: newsFlags, ascendingFlag: ascendingFlag, injPlay: injPlay, rookieLevel: rookieLevel, rbUsagePg: rbUsagePg, learnedShadowCorr: learnedShadowCorr, lgbPredict: lgbPredict, lgbExplain: lgbExplain, learnedShadowExplain: learnedShadowExplain, ctxNote: ctxNote,
    scoringFromLeague: scoringFromLeague, seasonPoints: seasonPoints,
    weeklyProjection: weeklyProjection, vegasMult: vegasMult, defenseAdj: defenseAdj, cbShadowMult: cbShadowMult, cb1OutBoost: cb1OutBoost, olOutDock: olOutDock, pressureMult: pressureMult, tdLuckAdj: tdLuckAdj, weatherMult: weatherMult, snapMult: snapMult, routeMult: routeMult, paceMult: paceMult,
    jsBasePg: jsBasePg, jsOppMult: jsOppMult, ncCacheReset: ncCacheReset,
    propAnchorMean: propAnchorMean, gammaMedRatio: gammaMedRatio, marketRate: marketRate, propImpliedFp: propImpliedFp, propCacheReset: propCacheReset,
    marketObsContaminated: marketObsContaminated,
    simWeek: simWeek, simSeason: simSeason, simLeague: simLeague, bracketRounds: bracketRounds, simBestBall: simBestBall, simBBField: simBBField, bbFieldRun: bbFieldRun, bbFieldAddWeek: bbFieldAddWeek, bbRosterOf: bbRosterOf, bbSleeperIndex: bbSleeperIndex, bbResolveSid: bbResolveSid, bbAliasNorm: bbAliasNorm, pickLineup: pickLineup,
    drawWeekEnv: drawWeekEnv, samplePlayerScore: samplePlayerScore, effMean: effMean, CORR: CORR,
    drawSeasonShock: drawSeasonShock, SLOT_ELIGIBLE: SLOT_ELIGIBLE
  };
})();
