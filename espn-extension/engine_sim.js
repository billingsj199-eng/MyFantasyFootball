// GENERATED from sim_lab/engine.js (source sha256 36ddddb02cd38dd6) by export_sleeper_extension_data.py.
// Comments removed, data global named GAME_ENV_2026. Edit the sim_lab original, never this copy.
(function () {
  'use strict';

  var SEASON = 2026;
  var WEEKS = 18;
  var VEGAS_ELASTICITY = 0.5;
  var RESID_SHRINK = 0.9;

  var CORR = {
    gV: 0.50,
    fV: { QB: 0.63, WR: 0.24, TE: 0.22, RB: 0.06, K: 0.10 },
    fH_QB: 0.65,
    fG: { WR: 0.58, TE: 0.60, RB: 0.30 },
    fR_RB: 0.25,
    fDST_oppV: -0.25
  };

  var POS_SIGMA = { QB: 0.42, RB: 0.52, WR: 0.62, TE: 0.70, K: 0.45, DST: 0.75 };
  var SIGMA_CAL = { QB: 1.0, RB: 1.15, WR: 1.15, TE: 1.10, K: 1.28 };
  var DST_SIGMA_CAL = 1.34;
  var DST_SHIFT = 4;

  var BOOM_BUST = {
    QB: { boom: 25, bust: 10 }, RB: { boom: 20, bust: 6 }, WR: { boom: 20, bust: 5 },
    TE: { boom: 15, bust: 4 }, K: { boom: 12, bust: 4 }, DST: { boom: 12, bust: 2 }
  };

  var TEAM_ALIAS = { ARZ: 'ARI', WSH: 'WAS', JAC: 'JAX', LA: 'LAR', HST: 'HOU', BLT: 'BAL', CLV: 'CLE', SD: 'LAC', OAK: 'LV', STL: 'LAR' };
  function normTeam(t) { return TEAM_ALIAS[t] || t; }

  var DST_NAMES = { ARI:'Cardinals', ATL:'Falcons', BAL:'Ravens', BUF:'Bills', CAR:'Panthers', CHI:'Bears', CIN:'Bengals', CLE:'Browns', DAL:'Cowboys', DEN:'Broncos', DET:'Lions', GB:'Packers', HOU:'Texans', IND:'Colts', JAX:'Jaguars', KC:'Chiefs', LAC:'Chargers', LAR:'Rams', LV:'Raiders', MIA:'Dolphins', MIN:'Vikings', NE:'Patriots', NO:'Saints', NYG:'Giants', NYJ:'Jets', PHI:'Eagles', PIT:'Steelers', SEA:'Seahawks', SF:'49ers', TB:'Buccaneers', TEN:'Titans', WAS:'Commanders' };

  function norm(n) {
    return String(n || '').toLowerCase()
      .replace(/\./g, '').replace(/'/g, '').replace(/-/g, ' ')
      .replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '')
      .replace(/\s+/g, ' ').trim();
  }

  var CLAY_NORM_ALIAS = { 'ken walker': 'kenneth walker', 'cameron ward': 'cam ward', 'chigoziem okonkwo': 'chig okonkwo', 'kyle t williams': 'kyle williams' };

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

  function buildSchedule() {
    var gt = (window.GAME_ENV_2026 && window.GAME_ENV_2026.gameTotals) || {};
    var sched = {}, games = {};
    Object.keys(gt).forEach(function (key) {
      var m = key.match(/^W(\d+)_([A-Z]+)_([A-Z]+)$/);
      if (!m) return;
      var wk = +m[1], away = normTeam(m[2]), home = normTeam(m[3]);
      var rec = gt[key];
      if (!rec || typeof rec.total !== 'number') return;
      var total = rec.total, spread = typeof rec.spread === 'number' ? rec.spread : 0;
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
    var sum = 0, n = 0, gameWeeks = {};
    Object.keys(sched).forEach(function (tm) {
      Object.keys(sched[tm]).forEach(function (wk) { var s0 = sched[tm][wk]; sum += (s0.bookImplied != null ? s0.bookImplied : s0.implied); n++; });
      gameWeeks[tm] = Object.keys(sched[tm]).map(Number).sort(function (a, b) { return a - b; });
    });
    return { byTeam: sched, byWeek: games, avgImplied: n ? sum / n : 22.5, gameWeeks: gameWeeks };
  }

  var INJ_EXIT = { frac: 0.60, minMed: 50, newsDays: 10,
                   limitRe: /snap count|pitch count|limited (snaps|role|workload|reps|usage)|ease[sd]? (him |her )?(back|in)|reduced (role|workload|snaps)|split (work|reps)|managed workload/i };
  function prepInjuryExits() {
    var w = typeof window !== 'undefined' ? window : null;
    if (!w || w.SIM_INJ_EXIT === false) return;
    var SN = w.SIM_SNAPS_2026, S26 = w.SIM_2026 && w.SIM_2026.players, IS = w.SIM_INJ_SIGNALS;
    if (!SN || !IS || !IS.prac) return;
    if (w._injExitSrc === SN) return;
    w._injExitSrc = SN;
    w._injExits = {};
    var now = Date.now(), news = (w.SIM_NEWS_2026 && w.SIM_NEWS_2026.items) || [];
    Object.keys(SN).forEach(function (name) {
      var rec = SN[name];
      if (!rec || !rec.w) return;
      var wks = Object.keys(rec.w).filter(function (k) { return typeof rec.w[k] === 'number'; });
      if (wks.length < 3) return;
      var vals = wks.map(function (k) { return rec.w[k]; }).sort(function (a, b) { return a - b; });
      var med = vals[Math.floor(vals.length / 2)];
      if (!(med >= INJ_EXIT.minMed)) return;
      var nk = norm(name);
      var limited = news.some(function (it) {
        if (!it || norm(it.player || '') !== nk) return false;
        var t = Date.parse((it.date || '') + 'T12:00:00Z');
        if (!(t > now - INJ_EXIT.newsDays * 864e5)) return false;
        return INJ_EXIT.limitRe.test(String(it.headline || '') + ' ' + String(it.take || ''));
      });
      if (limited) return;
      var exits = wks.filter(function (k) {
        if (!(rec.w[k] < INJ_EXIT.frac * med)) return false;
        var a = IS.prac[k] && IS.prac[k][nk], b = IS.prac[String(+k + 1)] && IS.prac[String(+k + 1)][nk];
        var listed = function (r) { return !!r && !/rest|not injury/i.test(String(r.inj || '')) && (r.gs || r.seq || r.inj); };
        return listed(a) || listed(b);
      });
      if (!exits.length) return;
      w._injExits[name] = exits.map(Number);
      exits.forEach(function (k) {
        delete rec.w[k];
        var xf = w.SIM_XFP_2026 && w.SIM_XFP_2026[nk]; if (xf && xf.w) delete xf.w[k];
        var rr = w.SIM_ROUTES_2026 && w.SIM_ROUTES_2026[nk]; if (rr) delete rr[k];
        var q = S26 && S26[nk];
        if (q && q.wf && typeof q.wf[k] === 'number') {
          var drop = q.wf[k], oldPpg = q.ppg;
          delete q.wf[k];
          if (Array.isArray(q.wks)) q.wks = q.wks.filter(function (x) { return String(x) !== String(k); });
          var rest = Object.keys(q.wf).map(function (x) { return q.wf[x]; }).filter(function (v) { return typeof v === 'number'; });
          if (rest.length) {
            q.g = rest.length;
            q.ppg = Math.round(rest.reduce(function (t, v) { return t + v; }, 0) / rest.length * 100) / 100;
            if (q.pg && oldPpg > 0) Object.keys(q.pg).forEach(function (m) { q.pg[m] = q.pg[m] * q.ppg / oldPpg; });
            if (typeof q.l8 === 'number' && q.l8g > 1) { q.l8 = (q.l8 * q.l8g - drop) / (q.l8g - 1); q.l8g -= 1; }
          }
        }
      });
      var left = Object.keys(rec.w).map(function (k) { return rec.w[k]; }).filter(function (v) { return typeof v === 'number'; });
      if (left.length && typeof rec.s === 'number') rec.s = Math.round(left.reduce(function (t, v) { return t + v; }, 0) / left.length * 10) / 10;
    });
  }

  function buildPlayers(schedule) {
    prepInjuryExits();
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
    var dpl = (typeof window !== 'undefined' && window.SIM_DEPTH_POOL_ON !== false && window.SIM_DEPTH_POOL) || null;
    var dplAdded = {};
    if (dpl) { clay = Object.assign({}, clay); Object.keys(dpl).forEach(function (nm) { if (!clay[nm]) { clay[nm] = dpl[nm]; dplAdded[nm] = 1; } }); }
    var chartOn = !(typeof window !== 'undefined' && window.SIM_CHART_TEAMS === false);
    var dAll = chartOn && typeof window !== 'undefined' && window.SIM_DEPTH_2026 && window.SIM_DEPTH_2026.teams;
    var keyOf = function (nm) { var k = norm(nm); return CLAY_NORM_ALIAS[k] || k; };
    var chartAt = {}, chartAlias = [], teamMoves = [];
    if (dAll) {
      var lastFi = function (k) { var parts = k.split(' '); return parts.length >= 2 ? parts[parts.length - 1] + '|' + parts[0].charAt(0) : null; };
      var sheet = {};
      Object.keys(clay).forEach(function (nm) { var c0 = clay[nm]; sheet[keyOf(nm)] = { name: nm, pos: c0.pos === 'PK' ? 'K' : c0.pos, tm: normTeam(c0.tm) }; });
      var onChart = {};
      Object.keys(dAll).forEach(function (t) { var byp = dAll[t] || {}; Object.keys(byp).forEach(function (ps) { (byp[ps] || []).forEach(function (nm) { onChart[keyOf(nm)] = 1; }); }); });
      var byLf = {};
      Object.keys(sheet).forEach(function (k) { var lf = lastFi(k); if (lf) (byLf[sheet[k].pos + '|' + lf] = byLf[sheet[k].pos + '|' + lf] || []).push(k); });
      Object.keys(dAll).forEach(function (t) {
        var tmN = normTeam(t), byp = dAll[t] || {};
        Object.keys(byp).forEach(function (ps) {
          var lst = byp[ps] || [];
          lst.forEach(function (nm, i) {
            var k = keyOf(nm);
            if (!sheet[k]) {
              var lf = lastFi(k), cands = lf ? (byLf[ps + '|' + lf] || []) : [];
              var same = cands.filter(function (sk) { return sheet[sk].tm === tmN && !onChart[sk]; });
              var anyT = cands.filter(function (sk) { return !onChart[sk]; });
              var hit = same.length === 1 ? same[0] : (same.length === 0 && anyT.length === 1 ? anyT[0] : null);
              if (hit) {
                lst[i] = CLAY_NORM_ALIAS[norm(sheet[hit].name)] ? hit : sheet[hit].name;
                onChart[hit] = 1; chartAlias.push(nm + ' -> ' + sheet[hit].name); k = hit;
              }
            }
            if (chartAt[k] === undefined) chartAt[k] = { tm: tmN, pos: ps };
            else if (chartAt[k] && chartAt[k].tm !== tmN) chartAt[k] = null;
          });
        });
      });
    }
    var kChart = {}, dChart = dpl && typeof window !== 'undefined' && window.SIM_DEPTH_2026 && window.SIM_DEPTH_2026.teams;
    if (dChart) Object.keys(dChart).forEach(function (t) { var kl = dChart[t] && dChart[t].K; if (kl && kl.length) kChart[normTeam(t)] = kl.map(norm); });
    var kOff = [];
    Object.keys(clay).forEach(function (name) {
      var c = clay[name];
      var pos = c.pos === 'PK' ? 'K' : c.pos;
      if (!POS_SIGMA[pos]) return;
      if (pos === 'K' && !dplAdded[name] && kChart[normTeam(c.tm)] && kChart[normTeam(c.tm)].indexOf(norm(name)) < 0 && !(chartAt[keyOf(name)] && chartAt[keyOf(name)].pos === 'K')) { kOff.push(name); return; }
      var nk = norm(name), clayNk = nk;
      if (CLAY_NORM_ALIAS[nk]) nk = CLAY_NORM_ALIAS[nk];
      var sl = slByNorm[nk];
      var sg = sigByNorm[nk];
      var age = sl && typeof sl.age === 'number' ? sl.age : null;
      var mt = (typeof window !== 'undefined' && window.SIM_SLEEPER_META && sl && sl.sid)
        ? window.SIM_SLEEPER_META[String(sl.sid)] : null;
      var exp = mt && typeof mt.exp === 'number' ? mt.exp : null;
      var isRookie = exp != null ? exp === 0 : (!sg && age != null && age <= 23);
      var sigmaPct, sigmaSrc;
      var histPpg = null, histGames = 0;
      if (sg && sg.sigma_pct) {
        var games = sg.games || 30;
        sigmaPct = sg.sigma_pct * (1 + 0.25 * (1 - Math.min(1, games / 30)));
        sigmaSrc = 'history';
        histPpg = sg.mean_ppg || null;
        histGames = games;
      } else if (isRookie) {
        sigmaPct = POS_SIGMA[pos] * 1.20;
        sigmaSrc = 'rookie-wide';
      } else {
        sigmaPct = POS_SIGMA[pos] * 1.10;
        sigmaSrc = 'no-history';
      }
      if (age != null && age <= 23) sigmaPct *= 1.10;
      else if (age === 24) sigmaPct *= 1.05;
      sigmaPct *= SIGMA_CAL[pos] || 1;
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
        draftPick: (mt && mt.dy === SEASON && typeof mt.dp === 'number') ? mt.dp : null,
        tmNow: sl && sl.sTm ? normTeam(sl.sTm) : null,
        injFlag: mt ? (mt.inj || '') + '|' + (mt.st || '') : '',
        histPpg: histPpg, histGames: histGames,
        ktc1qb: sl && typeof sl.ktc1qb === 'number' ? sl.ktc1qb : null,
        ktcSf: sl && typeof sl.ktcSf === 'number' ? sl.ktcSf : null,
        depthExtra: !!dplAdded[name]
      };
      if (chartOn) {
        var ca = chartAt[nk], curTm = ca ? ca.tm : (ca === undefined && sl && sl.sTm ? normTeam(sl.sTm) : null);
        if (curTm && curTm !== p.tm) { p.teamMoved = p.tm; teamMoves.push(name + ' ' + p.tm + '->' + curTm); p.tm = curTm; }
      }
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
      var ssD = (typeof window !== 'undefined') ? window.SIM_STAT_SHAPE : null;
      if (ssD && window.SIM_STAT_SHAPE_ON !== false && ssD.on && ssD.on.indexOf(pos) >= 0 && ssD.players) {
        var ssR = ssD.players[nk] || ssD.players[clayNk];
        if (ssR && ssR.pos === pos && ssR.sh) {
          var ssV = { py: 0.04, ptd: 4, ry: 0.1, rtd: 6, rec: 0.5, rcy: 0.1, rctd: 6 }, ssTot = 0;
          Object.keys(ssV).forEach(function (k) { ssTot += ssV[k] * (p.comps[k] || 0); });
          if (ssTot > 0) { Object.keys(ssV).forEach(function (k) { p.comps[k] = +((ssR.sh[k] || 0) * ssTot).toFixed(2); }); p.compsSrc = 'gamelog'; }
        }
      }
      players.push(p);
      if (!byNorm[nk]) byNorm[nk] = p;
      if (clayNk !== nk && !byNorm[clayNk]) byNorm[clayNk] = p;
      if (p.sid) bySid[p.sid] = p;
    });

    Object.keys(DST_NAMES).forEach(function (tm) {
      var p = {
        name: DST_NAMES[tm] + ' D/ST', norm: norm(DST_NAMES[tm] + ' D/ST'), pos: 'DST', tm: tm,
        comps: {}, ptsPPR: 0, clayGames: 17,
        sigmaPct: POS_SIGMA.DST * DST_SIGMA_CAL
          * ((typeof window !== 'undefined' && window.SIM_TUNING && window.SIM_TUNING.sigmaMult
              && typeof window.SIM_TUNING.sigmaMult.DST === 'number') ? window.SIM_TUNING.sigmaMult.DST : 1),
        sigmaSrc: 'pos-default',
        sid: tm, adp: null, isDST: true
      };
      players.push(p);
      byNorm[p.norm] = p;
      bySid[tm] = p;
    });

    players.forEach(function (p) { if (!bySid[p.norm]) bySid[p.norm] = p; });

    applyQbWindows(players, byNorm);
    applyInjuryWindows(players);
    applyRookieRamps(players);

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
    _roster = players; _rosterByTm = null; _tmQb1 = null;
    _poolByNorm = byNorm;
    return { list: players, byNorm: byNorm, bySid: bySid, recByTeam: recByTeam, schedule: schedule, chartAlias: chartAlias, teamMoves: teamMoves, kOff: kOff,
             _ix: buildIndex(players, recByTeam, schedule) };
  }

  function buildIndex(list, recByTeam, schedule) {
    var teams = [], tIdx = Object.create(null);
    function teamSlot(tm) {
      if (tm == null) return -1;
      var i = tIdx[tm];
      if (i === undefined) { i = teams.length; teams.push(tm); tIdx[tm] = i; }
      return i;
    }
    var bw = (schedule && schedule.byWeek) || {};
    Object.keys(bw).forEach(function (wk) {
      bw[wk].forEach(function (g0) { teamSlot(g0.away); teamSlot(g0.home); });
    });
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
      p._relW = Math.sqrt(Math.pow(RESID_SHRINK * p.sigmaPct, 2) + 0.04);
    });
    return { teams: teams, tIdx: tIdx, recByTi: recByTi, nRec: nRec };
  }
  function ensureIndex(players) {
    return players._ix ||
      (players._ix = buildIndex(players.list || [], players.recByTeam || {}, players.schedule));
  }

  function applyInjuryWindows(players) {
    var ov = (typeof window !== 'undefined' && window.INJURY_WINDOW_OVERRIDES) || {};
    players.forEach(function (p) {
      if (p.qbWindow || p.isDST) return;
      var o = ov[p.name];
      if (o != null) {
        if (o > 0) p.qbWindow = { s: o + 1, e: 17, games: 17 - o, src: 'override' };
        return;
      }
      if (!/PUP|IR|NFI|Injured Reserve|Non Football|Out|Doubtful|Questionable|Sus/i.test(p.injFlag)) return;
      var gm = p.clayGames;
      if (!(gm >= 2 && gm <= 16)) return;
      p.qbWindow = { s: 17 - gm + 1, e: 17, games: gm, src: 'injury-start' };
    });
  }

  var QB_SPLIT_MIN_PTS = 40;
  var QB_BACKUP_RATE = 0.85;
  function applyQbWindows(players, byNorm) {
    var rooms = {};
    players.forEach(function (p) {
      if (p.pos === 'QB' && p.ptsPPR >= QB_SPLIT_MIN_PTS && !p.depthExtra && !p.teamMoved) (rooms[p.tm] = rooms[p.tm] || []).push(p);
    });
    var overrides = (typeof window !== 'undefined' && window.QB_ROOM_OVERRIDES) || {};
    Object.keys(rooms).forEach(function (tm) {
      if (overrides[tm]) {
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
      var adjB = other.ptsPPR / QB_BACKUP_RATE;
      var gB = Math.min(12, Math.max(2, Math.round(17 * adjB / (lead.ptsPPR + adjB))));
      var gL = 17 - gB;
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
      if (!p.isRookie) return;
      if (p.pos !== 'RB' && p.pos !== 'WR' && p.pos !== 'TE') return;
      if (p.ptsPPR < 0.6 * (lead[p.tm + '|' + p.pos] || 0)) p.ramp = 'buried';
    });
  }

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
      bonus_rec_te: num(ls.bonus_rec_te, 0),
      dst: dstScoringFrom(ls)
    };
  }
  function num(v, d) { return typeof v === 'number' ? v : d; }

  function clayDiv(p) {
    if (typeof window !== 'undefined' && window.SIM_CLAY_GM === false) return 17;
    var g = p.clayGames;
    return (typeof g === 'number' && g >= 4 && g < 17) ? g : 17;
  }
  function seasonPoints(p, sc) {
    if (p.isDST) return 0;
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

  var _defAdj = null;
  function defenseAdj() {
    if (_defAdj) return _defAdj;
    var g = (typeof window !== 'undefined' && window.CLAY_TEAM_GRADES_2026) || {};
    var blends = {}, sums = { QB: 0, RB: 0, WR: 0, TE: 0 }, n = 0;
    Object.keys(g).forEach(function (tm) {
      var t = g[tm];
      if (t.cb == null) return;
      var b = {
        QB: t.cb * 0.45 + t.s * 0.25 + t.ed * 0.30,
        WR: t.cb * 0.50 + t.s * 0.30 + t.ed * 0.20,
        RB: t.di * 0.40 + t.lb * 0.35 + t.ed * 0.25,
        TE: t.s * 0.40 + t.lb * 0.35 + t.cb * 0.25
      };
      blends[normTeam(tm)] = b;
      sums.QB += b.QB; sums.RB += b.RB; sums.WR += b.WR; sums.TE += b.TE; n++;
    });
    _defAdj = {};
    Object.keys(blends).forEach(function (tm) {
      _defAdj[tm] = {};
      ['QB', 'RB', 'WR', 'TE'].forEach(function (pos) {
        var m = 1 - 0.01 * (blends[tm][pos] - sums[pos] / n);
        _defAdj[tm][pos] = Math.min(1.04, Math.max(0.96, m));
      });
    });
    return _defAdj;
  }

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
        if (r.st && r.st !== 'Active') return;
        if (/^(Out|Doubtful)/i.test(r.inj || '')) return;
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

  var OL_OUT_DOCK = { rb1: 0.98, rb2: 0.95, other2: 0.97 };
  var _olOut = null;
  function olOutDock(tm, pos) {
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

  var SNAP_W = [0.5, 0.3, 0.2];
  var CTX_MIN_GARBAGE = 6;
  function ctxOf(p, w) {
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_BLOWOUT_CTX === false || !wnd.SIM_GAMECTX_2026) return null;
    var t = wnd.SIM_GAMECTX_2026[p.tm]; var c = t && (t[w] || t[String(w)]);
    return c || null;
  }
  function ctxShare(pct, c, dropbacks) {
    var tot = dropbacks ? c.db : c.pl, gar = dropbacks ? c.gdb : c.gp;
    if (!tot || gar < CTX_MIN_GARBAGE) return { pct: pct, wt: 1 };
    var comp = tot - gar, cnt = pct / 100 * tot;
    var adj = cnt <= comp + 0.5 ? Math.min(100, 100 * cnt / comp) : pct;
    return { pct: cnt >= 0.85 * comp ? adj : pct, wt: comp / tot, adjusted: cnt >= 0.85 * comp && adj > pct + 0.5 };
  }
  function ctxNote(p, wk) {
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
    return Math.min(1.30, Math.max(0.75, 1 + 1.0 * (recent - seasonAvg) / 100));
  }

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

  var PRESSURE_BOOST = 1.05;
  var PRESSURE_THR   = -0.02;
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
      _pressLg = n >= 1000 ? p / n : -1;
    }
    if (_pressLg < 0) return 1;
    var v = m[opp] || m[normTeam(opp)];
    if (!v || v[1] < 80) return 1;
    var dev = v[0] / v[1] - _pressLg;
    if (dev > PRESSURE_THR) return 1;
    return 1 + (PRESSURE_BOOST - 1) * Math.min(1, v[1] / 250);
  }

  if (typeof window !== 'undefined' && window.SIM_TD_LUCK === undefined) window.SIM_TD_LUCK = false;
  var TDLUCK_K = 0.75;
  var TDLUCK_K_REC = 1.0;
  var TDLUCK_K_QB = 0.5;
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
    var g = (rec && rec.g) ? rec.g : r.g;
    var luck = (r.xtd - r.td) / r.g;
    var tdPts = isQb ? ((sc && sc.pass_td) || 4)
      : isRec ? ((sc && sc.rec_td) || 6)
      : (((sc && sc.rush_td) || 6) + ((sc && sc.rec_td) || 6)) / 2;
    var k = isQb ? TDLUCK_K_QB : isRec ? TDLUCK_K_REC : TDLUCK_K;
    return k * tdPts * luck * (g / (JS_PRIOR_STRENGTH + g));
  }

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

  function paceMult(p) {
    var d = (typeof window !== 'undefined' && window.SIM_PACE_2026) || null;
    var t = d && d.teams && d.teams[p.tm];
    if (!t || !t.cur || !t.games || p.isDST || p.pos === 'K') return 1;
    var b = t.base || {}, c = t.cur, m = 1;
    if (c.plays && b.plays) {
      m *= Math.min(1.06, Math.max(0.94, 1 + 0.5 * (c.plays - b.plays) / b.plays));
    }
    if (c.npr != null && b.npr != null) {
      var dp = c.npr - b.npr;
      if (p.pos === 'RB') m *= Math.min(1.05, Math.max(0.95, 1 - 0.5 * dp));
      else m *= Math.min(1.05, Math.max(0.95, 1 + 0.8 * dp));
    }
    if (p.pos === 'TE' && c.te2 != null && b.te2 != null) {
      m *= Math.min(1.04, Math.max(0.96, 1 + 0.4 * (c.te2 - b.te2)));
    }
    return 1 + Math.min(1, t.games / 6) * (m - 1);
  }

  var JS_PRIOR_STRENGTH = 5;
  var JS_FPA_FULL_TRUST = 8;
  function jsData() { return (typeof window !== 'undefined' && window.SIM_2026) || {}; }
  var SHADOW_AGE = {"reg":{"QB":[1.3645,0.5086,1.0357],"RB":[0.0147,0.9393,1.1103],"WR":[-0.2146,1.0429,1.0902],"TE":[0.0646,0.9158,1.0838]},"age":{"QB":{"22":1.04,"23":1.037,"24":1.017,"25":0.978,"26":0.921,"27":0.908,"28":0.939,"29":0.993,"30":1.011,"31":1.003,"32":1.0,"33":0.976,"34":0.966,"35":0.958},"RB":{"22":1.026,"23":0.996,"24":0.973,"25":0.935,"26":0.908,"27":0.89,"28":0.866,"29":0.852,"30":0.864,"31":0.843},"WR":{"21":1.068,"22":1.121,"23":1.052,"24":1.03,"25":0.956,"26":0.924,"27":0.872,"28":0.854,"29":0.847,"30":0.868,"31":0.824,"32":0.813,"33":0.794},"TE":{"22":0.974,"23":1.011,"24":1.023,"25":1.022,"26":0.958,"27":0.917,"28":0.906,"29":0.885,"30":0.893,"31":0.896}},"exp":{},"useReg":true,"useAge":true,"useExp":false,"src":"backtest_age_exp.py 2026-09-15 16:53"};
  var NC_SHADOW = {
    P: { QB: 12, RB: 5, WR: 8, TE: 8 },
    k: 0.8,
    adpGate: 200,
    posMean: { QB: 17.415, RB: 9.94, WR: 8.585, TE: 6.282 },
    rookie: { QB: [16.352, -0.688], RB: [19.764, -2.617], WR: [13.031, -1.518], TE: [11.170, -1.358] },
    adpCurve: { QB: [35.434, -3.8335], RB: [22.8287, -3.151], WR: [22.719, -3.0549], TE: [19.9698, -2.6563] },
    adpW: 0.75, adpWYr2: 0.5, adpMax: 181,
    rookieStr: { RB: [18.1294, -1.1986, -5.7632, -6.8114], WR: [13.971, -1.5426, -1.995, -0.7776] },
    vetDock: { RB: { 2: 0.8, 3: 0.4 }, WR: { 2: 0.6, 3: 0.6 }, TE: { 2: 0.8 } },
    rookieRamp: [0.7, 0.8],
    yr2LowSnap: { max: 0.40, mult: 1.2 },
    wrGrade: { c0: 56.095, c1: 1.9876, cut: 2.649, mult: 1.1 },
    qbBackupPpg: 1.0,
    qRet: { mult: 0.85 },
    noChart: { mult: 0.8, games: 4 },
    qbOutWrDock: { star: 0.15, other: 0.05, starAdp: 60 },
    qbOppLeg: { w: 0.5, kYpa: 328, kYpc: 22, eDef: 0.76, fpaPriorG: 4, minStarts: 1, startAtt: 10, intPts: -2, shortW: 0.4, hlShort: 3, hlLong: 10,
                attOls: [8.8, 0.441, -0.029, 0.222], ptdOls: [-0.483, 0.088], rtdOls: [-0.098, 0.045], lg: { ypa: 7.28, ypc: 6.02, intr: 0.0216, att: 34, plays: 62 } },
    earlyP: { WR: { mult: 5, games: 1 } },
    vegEvK: 1,
    rankMixW: 0.5,
    qbTotalC: 0.03,
    usageLam: { RB: [1.0, 0.3, 0.25], WR: [1.0, 0.08, 0.25] },
    ridgeW2: { RB: 0.75, lateQbAdp: 100, lateQbW: 0.25 },
    noAdpPos: { QB: false, RB: false, WR: false, TE: true },
    ridgeW: { QB: 0, RB: 0.5, WR: 0.5, TE: 0.5 },
    vacatedK: { QB: 1.0, RB: 0.75, WR: 0.75, TE: 0.75 },
    depthW: [1.6, 1.0, 0.5],
    next: { qbMover: 0.90, lowTot: [19, 0.75], rookieWr: 0.90, rbCarry: [0.30, 0.90], early: [2, 5], snapE: 0.3, snapEFar: { WR: 0, TE: 0.3 }, snapClamp: [0.7, 1.4],
      teDockK: 0.5,
            qbMoverFar: 0.84, teTilt: 0.04, rbSnapCarry: true,
            snapNoDockAdp: 30,
            blowNoDockAdp: 150, blowMinShare: 0.15,
            struct: { minGames: 3, rbMidP: 2.5, wrMidP: 0.6, mid: [60, 100], qbYr2P: 0.75, wrLateLam: 0.25, late: [100, 150], teLevel: 1.10, teBand: [30, 60],
                      wrLateColdP: 0.4, rbPlays: 0.04, rbBackup: 1.04, rbBackupAdp: 150,
                      rookieP: { RB: 1.6, TE: 2.5 },
                      rbCurve: { k: 1.0, c: 70, w: 25 } },
            snapLvl: { WR: { edges: [4.87, 6.22, 7.4, 8.68, 9.93, 11.23, 12.87], ref: [45.9, 59.7, 67.2, 72.6, 79.8, 83.3, 83.7, 85.0] },
                       TE: { edges: [3.85, 4.66, 5.4, 6.28, 7.17, 8.04, 9.48], ref: [52.6, 57.7, 64.9, 68.2, 71.7, 74.7, 76.9, 83.8] } } },
    src: 'backtest_noclay_weekly.py + backtest_rookie_prior.py 2026-09-16'
  };
  var _poolByNorm = null;
  var _ncCache = {}, _ncPass = false;
  function qbOppLeg(p, wk, sc, schedule, slot) {
    var Q = NC_SHADOW.qbOppLeg, wnd = typeof window !== 'undefined' ? window : null;
    if (!Q || !wnd || !p || p.pos !== 'QB' || p.isDST || !slot || !sc) return null;
    var XF = wnd.SIM_XFP_2026 || {}, x = XF[p.norm], J = jsData(), rec = J.players && J.players[p.norm];
    if (!x || !x.w || !rec || !rec.pg || !(rec.g > 0)) return null;
    var weeks = Object.keys(x.w).map(Number).filter(function (w) { return w < wk && x.w[w] && (x.w[w][0] > 0 || x.w[w][3] > 0); }).sort(function (a, b) { return a - b; });
    if (!weeks.length) return null;
    var teamAttWk = function (w) {
      var t = 0, seen = {};
      if (_poolByNorm) Object.keys(_poolByNorm).forEach(function (k) { var q = _poolByNorm[k]; if (!q || q.pos !== 'QB' || q.tm !== p.tm || seen[q.norm]) return; seen[q.norm] = 1; var xq = XF[q.norm]; if (xq && xq.w && xq.w[w]) t += xq.w[w][0] || 0; });
      return t;
    };
    var attTot = 0, carTot = 0, starts = 0, nS = 0, dS = 0, nL = 0, dL = 0, n = weeks.length;
    weeks.forEach(function (w, i) {
      var r = x.w[w], a = r[0] || 0, c = r[3] || 0, ta = Math.max(a, teamAttWk(w));
      attTot += a; carTot += c; if (a >= Q.startAtt) starts++;
      var ago = n - 1 - i, wS = Math.pow(0.5, ago / Q.hlShort), wL = Math.pow(0.5, ago / Q.hlLong);
      if (ta > 0) { nS += wS * a; dS += wS * ta; nL += wL * a; dL += wL * ta; }
    });
    if (starts < Q.minStarts) return null;
    var shS = dS > 0 ? nS / dS : 1, shL = dL > 0 ? nL / dL : 1, attSh = Math.max(0, Math.min(1, Q.shortW * shS + (1 - Q.shortW) * shL));
    var pyTot = (rec.pg.py || 0) * rec.g, ryTot = (rec.pg.ry || 0) * rec.g;
    var ypa = (pyTot + Q.kYpa * Q.lg.ypa) / (attTot + Q.kYpa), ypc = (ryTot + Q.kYpc * Q.lg.ypc) / (carTot + Q.kYpc), carPg = carTot / n;
    var pv = wnd.SIM_PACE_2026 && wnd.SIM_PACE_2026.teams && wnd.SIM_PACE_2026.teams[p.tm], vol = pv && pv.cur && pv.cur.vol;
    var paceAtt = (vol && vol.games >= 1 && vol.att != null) ? vol.att : Q.lg.att, plays = (vol && vol.games >= 1 && vol.plays != null) ? vol.plays : Q.lg.plays;
    var imp = slot.implied, oimp = slot.oppImplied; if (!(typeof imp === 'number' && typeof oimp === 'number')) return null;
    var tspread = oimp - imp, total = imp + oimp, A = Q.attOls;
    var teamAtt = Math.max(5, A[0] + A[1] * paceAtt + A[2] * tspread + A[3] * total);
    var teamPtd = Math.max(0.2, Q.ptdOls[0] + Q.ptdOls[1] * imp), teamRtd = Math.max(0.1, Q.rtdOls[0] + Q.rtdOls[1] * imp);
    var fp = J.fpa && J.fpa[slot.opp], lg = J.lgFpa && J.lgFpa.QB, relIn = 1, gIn = 0;
    if (fp && lg > 0 && fp.QB != null && fp._g > 0) { relIn = fp.QB / lg; gIn = fp._g; }
    var relPr = 1, PR = wnd.SIM_FPA_PRIOR && wnd.SIM_FPA_PRIOR.pos && wnd.SIM_FPA_PRIOR.pos.QB;
    if (PR && PR[slot.opp] != null) { var ks = Object.keys(PR), sm = 0; ks.forEach(function (t) { sm += PR[t]; }); if (ks.length && sm > 0) relPr = PR[slot.opp] / (sm / ks.length); }
    var rel = (relIn * gIn + relPr * Q.fpaPriorG) / (gIn + Q.fpaPriorG), opp = Math.pow(Math.max(0.5, Math.min(1.5, rel)), Q.eDef);
    var att = attSh * teamAtt, csh = carPg / Math.max(5, plays - paceAtt);
    var leg = att * ((sc.pass_yd || 0) * ypa * opp + Q.intPts * Q.lg.intr) + (sc.pass_td || 0) * attSh * teamPtd
            + carPg * (sc.rush_yd || 0) * ypc + (sc.rush_td || 0) * Math.min(1, csh) * teamRtd;
    return leg > 0 ? leg : null;
  }
  var _qbfMu = {}, _qbfPass = false;
  function qbShadowMu(wk, sc, schedule) {
    var ck = ncCacheKey(wk, sc);
    if (_qbfMu[ck] !== undefined) return _qbfMu[ck];
    if (!_poolByNorm) return null;
    var seen = [], vals = [];
    _qbfPass = true;
    try {
      Object.keys(_poolByNorm).forEach(function (k) {
        var q = _poolByNorm[k]; if (!q || q.pos !== 'QB' || q.isDST || seen.indexOf(q) >= 0) return; seen.push(q);
        var r = weeklyProjection(q, wk, sc, schedule); if (r && r.ncMean > 0) vals.push(r.ncMean);
      });
    } finally { _qbfPass = false; }
    vals.sort(function (x, y) { return y - x; }); vals = vals.slice(0, 32);
    _qbfMu[ck] = vals.length >= 20 ? vals.reduce(function (x, y) { return x + y; }, 0) / vals.length : null;
    return _qbfMu[ck];
  }
  function ncCacheKey(wk, sc) { return wk + '|' + [sc.rec, sc.pass_td, sc.pass_yd, sc.rush_yd, sc.rec_yd, sc.rush_td, sc.rec_td, sc.bonus_rec_te || 0].join(','); }
  function ncCacheReset() { _ncCache = {}; _peckCache = {}; _qbfMu = {}; }

  var PECK = { WR: { fromRank: 3, mult: 0.92 }, RB: { fromRank: 2, mult: 0.97 }, fadeFrom: 4, fadeTo: 5, minTeammate: 0.5 };
  var _peckCache = {}, _peckPass = false;
  function peckDock(p, wk, sc, schedule, jsRaw, jsHalf) {
    var rule = PECK[p.pos], out = { m: 1, rank: null };
    if (!rule || p.isDST) return out;
    var wnd = typeof window !== 'undefined' ? window : null;
    if (wnd && (wnd.SIM_PECK_DOCK === false || (p.pos === 'WR' && wnd.SIM_PECK_WR3 === false) || (p.pos === 'RB' && wnd.SIM_PECK_RB2 === false))) return out;
    var ck = ncCacheKey(wk, sc), C = _peckCache[ck] || (_peckCache[ck] = {});
    C[p.norm] = jsRaw;
    if (_peckPass || _ncPass || !_poolByNorm) return out;
    var keys = Object.keys(_poolByNorm), grp = [];
    for (var i = 0; i < keys.length; i++) { var q = _poolByNorm[keys[i]]; if (q !== p && q.tm === p.tm && q.pos === p.pos && !q.isDST && grp.indexOf(q) < 0) grp.push(q); }
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
  function shadowOut(p, wk) {
    if (!p || (typeof window !== 'undefined' && window.SIM_NC_OUT === false)) return null;
    if (_inj && _inj.week >= 1 && wk > _inj.week && !(typeof window !== 'undefined' && window.SIM_NC_RETURN === false)) return null;
    var ov = (typeof window !== 'undefined' && window.IN_SEASON_OUT_OVERRIDES) ? window.IN_SEASON_OUT_OVERRIDES[p.name] : null;
    if (ov && ov.length >= 2 && !(_inj && _inj.week > ov[1])) return (wk >= ov[0] && wk <= ov[1]) ? 'override' : null;
    var f = String(p.injFlag || '').split('|'), inj = f[0] || '', st = f[1] || '';
    if (/^(Out|NA)$/i.test(inj) && _inj && wk === _inj.week && !(typeof window !== 'undefined' && window.SIM_NC_OUTUNCONF === false)) {
      var im = _inj.map[p.norm];
      if (im && /-unconfirmed$/.test(im.src || '') && im.mult > 0) return null;
    }
    if (/^(IR|PUP|NFI|Out|Sus|DNR|COV)$/i.test(inj)) return inj.toLowerCase();
    if (st && !/^Active$/i.test(st)) return st.toLowerCase();
    if (/^NA$/i.test(inj) && injAdj(p, wk) === 0) return 'na';
    return null;
  }
  function chartAvailable(nm, wk) {
    var nk = norm(nm);
    if (injAdj({ norm: nk }, wk) === 0) return false;
    var q = _poolByNorm && _poolByNorm[nk];
    if (!q) return true;
    if (shadowOut(q, wk)) return false;
    var flag = String(q.injFlag || ''), designated = /Questionable|Doubtful|Out/i.test(flag) || /\|(IR|PUP|NFI|Sus|NA|Inactive|Reserve)/i.test(flag);
    if (!designated) return true;
    var d = jsData(), rec = d.players && d.players[nk];
    return !!(rec && rec.g > 0);
  }
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
      var back = false; for (var w2 = cw + 1; w2 <= WEEKS && !back; w2++) if (injAdj(q, w2) > 0) back = true;
      if (!back) return;
      var pre = CP[q.norm], idx = null;
      if (pre && pre.pos === pos && normTeam(pre.tm) === normTeam(tm)) idx = pre.i;
      else {
        var rec = jsData().players ? jsData().players[q.norm] : null;
        if (!(rec && rec.g > 0) && q.adp != null) { idx = 0; room.forEach(function (t) { if (t !== q && t.adp != null && t.adp < q.adp) idx++; }); }
      }
      if (idx == null) return;
      var cur = nowIdx[q.norm];
      if (cur != null && cur <= idx) return;
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
  function ncNoAdp(pos) {
    var g = typeof window !== 'undefined' ? window.SIM_NC_NOADP : undefined;
    return g === true ? true : g === false ? false : !!(NC_SHADOW.noAdpPos && NC_SHADOW.noAdpPos[pos]);
  }
  function ridgePrior(p, wk, oppHalf) {
    var R0 = typeof window !== 'undefined' ? window.SIM_RIDGE_PRIOR : null;
    var R = (R0 && R0.noAdp && ncNoAdp(p.pos)) ? R0.noAdp : R0, M = R && R.models ? R.models[p.pos] : null;
    if (!M || !R.feats) return null;
    var jsRec = jsData().players ? jsData().players[p.norm] : null;
    var h3 = (p.histPpg != null && p.histGames >= 8) ? p.histPpg : null, l8 = (jsRec && jsRec.l8 != null && jsRec.l8g >= 4) ? jsRec.l8 : null;
    var hist = (h3 != null && l8 != null) ? 0.5 * h3 + 0.5 * l8 : (l8 != null ? l8 : h3);
    var adpOk = p.adp != null && p.adp <= 181, ds = depthString(p), dsk = ds == null ? null : Math.min(3, ds);
    var spr = (p.exp === 1 && typeof window !== 'undefined' && window.SIM_SNAPS_PRIOR && typeof window.SIM_SNAPS_PRIOR[p.norm] === 'number') ? window.SIM_SNAPS_PRIOR[p.norm] : null;
    var f = { ladp: Math.log(adpOk ? p.adp : 181), no_adp: adpOk ? 0 : 1, hist: hist, h3: h3, l8: l8, age: p.age != null ? p.age : null, exp: p.exp != null ? p.exp : null, rookie: p.isRookie ? 1 : 0,
              lpick: Math.log(p.isRookie && p.draftPick != null ? p.draftPick : 262), str1: dsk === 1 ? 1 : 0, str2: dsk === 2 ? 1 : 0, str3: dsk === 3 ? 1 : 0, nostr: dsk == null ? 1 : 0, oppcal: oppHalf, yr2_late: spr,
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
  var ROOKIE_LEVEL = { QB: 1.08, RB: 1.08 };
  function rookieLevel(p) {
    if (!p || !p.isRookie || !ROOKIE_LEVEL[p.pos]) return 1;
    if (typeof window !== 'undefined' && window.SIM_ROOKIE_LEVEL === false) return 1;
    var d = jsData(), rec = d.players && d.players[p.norm];
    return rec && rec.g >= 1 ? ROOKIE_LEVEL[p.pos] : 1;
  }
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
    var wp = weeklyProjection(p, wk, PRESETS.half, schedule);
    if (!wp || !wp.why) return null;
    var w = wp.why;
    try { return learnedShadowCorr(p, wk, PRESETS.half, wp.slot, { clayPg: w.clayPg, mult: w.veg, rbU: w.usage, iA: w.iA, jsMean: w.jsMean, explain: true }); } catch (_) { return null; }
  }
  var BUDGET_ALLOC = { d: 0.9, rhoT: 0.25, rhoC: 0.6, e: 0.75, clip: [0.6, 1.8], xpt: { RB: 1.129, WR: 1.418, TE: 1.368 }, xpc: { RB: 0.621, WR: 0.559, TE: 0.747 }, K: 25 };
  function budgetAllocRatio(p, wk, schedule) {
    var B = BUDGET_ALLOC, wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || !_inj || !_poolByNorm || !schedule || !schedule.gameWeeks) return null;
    var XF = wnd.SIM_XFP_2026 || {}, SN = wnd.SIM_SNAPS_2026 || {}, cw = cwOf(p);
    var weeks = (schedule.gameWeeks[p.tm] || []).filter(function (w) { return w < cw; });
    if (!weeks.length) return null;
    var mem = [], seenN = {};
    Object.keys(_poolByNorm).forEach(function (k) { var q = _poolByNorm[k]; if (q && !q.isDST && q.tm === p.tm && (q.pos === 'RB' || q.pos === 'WR' || q.pos === 'TE') && !seenN[q.norm]) { seenN[q.norm] = 1; mem.push(q); } });
    var row = function (q, w) { var x = XF[q.norm]; return x && x.w ? x.w[w] || x.w[String(w)] : null; };
    var present = function (q, w) { var sn = SN[q.name]; return !!(row(q, w) || (sn && sn.w && (sn.w[w] || sn.w[String(w)]) > 0)); };
    var T = {}, sh = {}, first = {};
    weeks.forEach(function (w) {
      var tt = 0, tc = 0; mem.forEach(function (q) { var r = row(q, w); if (r) { tt += r[0] || 0; tc += r[4] || 0; } }); T[w] = [tt, tc];
      mem.forEach(function (q) { if (!present(q, w)) return; var r = row(q, w) || [0, 0, 0, 0, 0]; (sh[q.norm] = sh[q.norm] || {})[w] = [tt > 0 ? (r[0] || 0) / tt : 0, tc > 0 ? (r[4] || 0) / tc : 0]; if (first[q.norm] == null) first[q.norm] = w; });
    });
    if (!sh[p.norm]) return null;
    var M = mem.filter(function (q) { return !!sh[q.norm]; }), nk = weeks.length, age = {};
    weeks.forEach(function (w, i) { age[w] = nk - 1 - i; });
    var factor = function (q, pres, w, u, rho) {
      var ms = 0, us = 0; M.forEach(function (x) { if (first[x.norm] > w || x.pos !== q.pos) return; var ux = u[x.norm] || 0; if (pres(x)) us += ux; else ms += ux; });
      return 1 + (us > 1e-9 ? rho * ms / us : 0);
    };
    var est = function (j, rho, u) {
      var out = {}; M.forEach(function (q) { var num = 0, den = 0; Object.keys(sh[q.norm]).forEach(function (w) { w = +w; var f = factor(q, function (x) { return !!(sh[x.norm] && sh[x.norm][w]); }, w, u, rho), wt = Math.pow(B.d, age[w]); num += wt * sh[q.norm][w][j] / f; den += wt; }); out[q.norm] = den > 0 ? num / den : 0; });
      return out;
    };
    var raw = function (j) { var out = {}; M.forEach(function (q) { var num = 0, den = 0; Object.keys(sh[q.norm]).forEach(function (w) { var wt = Math.pow(B.d, age[+w]); num += wt * sh[q.norm][w][j]; den += wt; }); out[q.norm] = den > 0 ? num / den : 0; }); return out; };
    var ut = raw(0), uc = raw(1), rt = raw(0), rc = raw(1);
    for (var it = 0; it < 2; it++) { ut = est(0, B.rhoT, ut); uc = est(1, B.rhoC, uc); }
    var presNow = function (x) { return injAdj(x, wk) > 0 && injPlay(x, wk) >= 0.5 && !shadowOut(x, wk); };
    var ft = factor(p, presNow, wk, ut, B.rhoT), fc = factor(p, presNow, wk, uc, B.rhoC);
    var Vt = 0, Vc = 0; weeks.forEach(function (w) { Vt += T[w][0]; Vc += T[w][1]; }); Vt /= nk; Vc /= nk;
    var tg = 0, car = 0, xr = 0, xc = 0; weeks.forEach(function (w) { var r = row(p, w); if (r) { tg += r[0] || 0; car += r[4] || 0; xr += 0.5 * (r[1] || 0) + 0.1 * (r[2] || 0) + 6 * (r[3] || 0); xc += 0.1 * (r[5] || 0) + 6 * (r[6] || 0); } });
    var xpt = (xr + B.K * (B.xpt[p.pos] || 1.3)) / (tg + B.K), xpc = (xc + B.K * (B.xpc[p.pos] || 0.6)) / (car + B.K);
    var bud = Vt * ut[p.norm] * ft * xpt + Vc * uc[p.norm] * fc * xpc, budN = Vt * rt[p.norm] * xpt + Vc * rc[p.norm] * xpc;
    if (!(budN > 0)) return null;
    return { ratio: bud / budN, ft: ft, fc: fc, bud: bud, budN: budN };
  }
  var VAC_FADE = { c: 4, pos: { RB: 1, WR: 1 } };
  function vacFadeF(p, Z, wk) {
    var out = { f: 1, seen: 0 };
    if (!_inj || !(_inj.week >= 1) || !(wk > cwOf(p)) || !VAC_FADE.pos[p.pos]) return out;
    if (typeof window !== 'undefined' && window.SIM_NC_VACFADE === false) return out;
    var pl = jsData().players || {}, mine = pl[p.norm], his = pl[Z.norm];
    if (!mine || !mine.wks || !his || !his.wks || !his.wks.length) return out;
    var seen = 0;
    var vfCw = cwOf(p); mine.wks.forEach(function (w0) { if (w0 < vfCw && his.wks.indexOf(w0) < 0) seen++; });
    out.seen = seen; out.f = Math.max(0, 1 - seen / VAC_FADE.c);
    return out;
  }
  var FILLIN = { boost: { RB: 1.26, WR: 1.08 }, minAdp: { WR: 100 }, regMin: 5.0, regMargin: 1.1, minStale: 2, backP: 0.5,
    ncBoost: { RB: 2.0, WR: 1.7 } };
  var PRIOR_HEALTH = { a: 0.5, cap: 2.0, minHurt: 3, minHealthy: 4, pos: { WR: 1, TE: 1 }, src: 'backtest_qb_injury_usage.py --refine 2026-10-07' };
  var VOLUME_CTX = { eExc: 0.03, eAtt: 0.04, eBox: 0.04, boxAdp: 60, minGames: 2, lo: 0.8, hi: 1.2, pos: { WR: 1, TE: 1 } };
  var BASE_BLEND = { w: { QB: 1.0, RB: 1.0, WR: 1.0, TE: 1.0 }, wNow: { QB: 1.0, RB: 1.0, WR: 1.0, TE: 1.0 }, scope: 'all' };
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
    if (z.box != null && p.adp != null && p.adp <= VOLUME_CTX.boxAdp && !(typeof window !== 'undefined' && window.SIM_BOX_CTX === false)) m *= Math.max(VOLUME_CTX.lo, Math.min(VOLUME_CTX.hi, 1 + VOLUME_CTX.eBox * z.box));
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
        if (!q || q === p || seen[q.norm] || q.isDST || q.depthExtra || q.teamMoved || q.pos !== p.pos || q.tm !== p.tm) continue;
        seen[q.norm] = 1;
        var lq = lvl(q); if (lq >= FILLIN.regMin && lq > mine * ((typeof window !== 'undefined' && window.SIM_FILLIN_MARGIN === false) ? 1 : FILLIN.regMargin)) regs.push(q);
      }
      if (regs.length) {
        var back = regs.filter(function (q) { return injAdj(q, wk) >= FILLIN.backP; });
        var stale = [];
        rec.wks.forEach(function (w) {
          if (w >= wk) return;
          if (back.some(function (q) { var r = d.players[q.norm]; return !(r && r.wks && r.wks.indexOf(w) >= 0); })) stale.push(w);
        });
        if (stale.length >= FILLIN.minStale) res = { weeks: stale, B: B };
        var pb = {}, nPb = 0;
        rec.wks.forEach(function (w) {
          if (w >= wk) return;
          var notBack = 1, missed = false;
          regs.forEach(function (q) { var r = d.players[q.norm]; if (!(r && r.wks && r.wks.indexOf(w) >= 0)) { missed = true; notBack *= 1 - Math.max(0, Math.min(1, injPlay(q, wk))); } });
          if (missed && notBack < 1) { pb[w] = 1 - notBack; nPb++; }
        });
        if (nPb >= FILLIN.minStale) { res = res || { weeks: [], B: B }; res.pb = pb; }
      }
    }
    _fillinCache[ck] = res;
    return res;
  }
  function fillinPtsF(p, wk) {
    var fs = fillinStale(p, wk); if (!fs) return 1;
    var rec = jsData().players[p.norm], wf = rec && rec.wf; if (!wf) return 1;
    var tot = 0, st = 0;
    Object.keys(wf).forEach(function (w) { var v = +wf[w]; if (+w >= wk || !isFinite(v)) return; tot += v; if (fs.weeks.indexOf(+w) >= 0) st += v; });
    return tot > 0 ? Math.max(0, (tot - st * (1 - 1 / fs.B)) / tot) : 1;
  }
  function ncFillinOn() { return !(typeof window !== 'undefined' && (window.SIM_NC_FILLIN === false || window.SIM_FILLIN === false)); }
  function ncFillinGameF(fs, p, w) {
    var B = FILLIN.ncBoost[p.pos], pb = fs && fs.pb ? fs.pb[w] : null;
    return (B && pb) ? 1 - (1 - 1 / B) * pb : 1;
  }
  function ncFillinPtsF(p, wk) {
    if (!ncFillinOn() || !FILLIN.ncBoost[p.pos]) return 1;
    var fs = fillinStale(p, wk); if (!fs || !fs.pb) return 1;
    var rec = jsData().players[p.norm], wf = rec && rec.wf; if (!wf) return 1;
    var tot = 0, keep = 0;
    Object.keys(wf).forEach(function (w) { var v = +wf[w]; if (+w >= wk || !isFinite(v)) return; tot += v; keep += v * ncFillinGameF(fs, p, +w); });
    return tot > 0 ? Math.max(0, keep / tot) : 1;
  }
  function jsBasePg(p, sc, clayPg, priorP, usage, ptsF, evid) {
    var PS = priorP != null ? priorP : JS_PRIOR_STRENGTH;
    var d = jsData();
    var rec = d.players && d.players[p.norm];
    if (!rec || !rec.g) return clayPg;
    var pg = rec.pg || {};
    var ppg = rec.ppg;
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
    if (ptsF != null && ptsF !== 1) ppg *= ptsF;
    if (usage && usage.ptsScale != null) ppg *= usage.ptsScale;
    if (usage && usage.lam > 0 && usage.xfpPg != null) ppg = usage.lam * usage.xfpPg + (1 - usage.lam) * ppg;
    return (PS * clayPg + gEv * ppg) / (PS + gEv);
  }
  var _pqCache = {};
  var NMU = { minShare: 0.10, minTeamTgt: 20, trail: 3, mult: { 1: 1.04, 2: 0.99, 3: 0.99, 4: 1.03, 5: 1.03, 6: 1.03 } };
  var _nmuCache = { src: null, t: {} };
  function nextManUpMult(p, wk, schedule) {
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_NMU === false || !_inj || wk !== cwOf(p) || !_poolByNorm) return 1;
    if (p.isDST || (p.pos !== 'WR' && p.pos !== 'TE' && p.pos !== 'RB')) return 1;
    if (injAdj(p, wk) === 0) return 1;
    if (_nmuCache.src !== _inj) _nmuCache = { src: _inj, t: {} };
    var T = _nmuCache.t[p.tm];
    if (T === undefined) {
      T = null;
      var X = wnd.SIM_XFP_2026, gw = (schedule && schedule.gameWeeks && schedule.gameWeeks[p.tm]) || [];
      var prev = gw.filter(function (w) { return w < wk; }).slice(-NMU.trail);
      if (X && prev.length === NMU.trail) {
        var trail = [], seen = {}, teamTgt = 0;
        Object.keys(_poolByNorm).forEach(function (k) {
          var q = _poolByNorm[k]; if (!q || seen[q.norm] || q.tm !== p.tm || (q.pos !== 'WR' && q.pos !== 'TE' && q.pos !== 'RB')) return; seen[q.norm] = 1;
          var xr = X[q.norm]; if (!xr || !xr.w) return;
          var g = 0, t = 0; prev.forEach(function (w) { var r = xr.w[w] || xr.w[String(w)]; if (r) { g++; t += +r[0] || 0; } });
          teamTgt += t / NMU.trail;
          if (g >= 2) trail.push({ q: q, tgt: t / g });
        });
        if (teamTgt >= NMU.minTeamTgt && trail.length) {
          trail.sort(function (a, b) { return b.tgt - a.tgt; });
          var rbSp = wnd.SIM_RB_NOSPILL === false;
          var out = trail.some(function (e) { return (rbSp || e.q.pos !== 'RB') && e.tgt / teamTgt >= NMU.minShare && injAdj(e.q, wk) === 0; });
          if (out) { T = {}; trail.forEach(function (e, i) { T[e.q.norm] = i + 1; }); }
        }
      }
      _nmuCache.t[p.tm] = T;
    }
    if (!T || !T[p.norm]) return 1;
    return NMU.mult[T[p.norm]] || 1;
  }
  var PROMO = { mult: { RB: 1.034, WR: 1.071, TE: 1.207 }, regMin: 5.0 };
  var _promoCache = { src: null, c: {} };
  function promotedMult(p, wk) {
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_PROMO === false || !_poolByNorm || p.isDST) return 1;
    var M = PROMO.mult[p.pos]; if (!M) return 1;
    if (injAdj(p, wk) === 0) return 1;
    if (_promoCache.src !== _inj) _promoCache = { src: _inj, c: {} };
    var ck = p.norm + '|' + wk;
    if (_promoCache.c[ck] !== undefined) return _promoCache.c[ck];
    var lvl = function (q) { var dv = clayDiv(q); return dv > 0 ? seasonPoints(q, PRESETS.half) / dv : 0; };
    var mine = lvl(p), res = 1, keys = Object.keys(_poolByNorm), seen = {};
    for (var i = 0; i < keys.length && res === 1; i++) {
      var q = _poolByNorm[keys[i]];
      if (!q || q === p || seen[q.norm] || q.isDST || q.depthExtra || q.teamMoved || q.pos !== p.pos || q.tm !== p.tm) continue;
      seen[q.norm] = 1;
      var lq = lvl(q);
      if (lq >= PROMO.regMin && lq > mine && injAdj(q, wk) === 0) res = M;
    }
    _promoCache.c[ck] = res;
    return res;
  }
  var TEAM_VAC = { k: 0.2, minShare: 0.10, trail: 3, minTeamTgt: 20 };
  var _tvCache = { src: null, t: {} };
  function teamVacMult(p, wk, schedule) {
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_TEAM_VAC === false || !_inj || !_poolByNorm || p.isDST) return 1;
    if (p.pos !== 'WR' && p.pos !== 'TE' && p.pos !== 'RB') return 1;
    if (injAdj(p, wk) === 0) return 1;
    if (_tvCache.src !== _inj) _tvCache = { src: _inj, t: {} };
    var key = p.tm + '|' + wk;
    var T = _tvCache.t[key];
    if (T === undefined) {
      T = 0;
      var X = wnd.SIM_XFP_2026, gw = (schedule && schedule.gameWeeks && schedule.gameWeeks[p.tm]) || [];
      var ref = Math.min(wk, cwOf(p) || wk);
      var prev = gw.filter(function (w) { return w < ref; }).slice(-TEAM_VAC.trail);
      if (X && prev.length === TEAM_VAC.trail) {
        var seen = {}, teamTgt = 0, rows = [];
        Object.keys(_poolByNorm).forEach(function (k) {
          var q = _poolByNorm[k]; if (!q || seen[q.norm] || q.tm !== p.tm || (q.pos !== 'WR' && q.pos !== 'TE' && q.pos !== 'RB')) return; seen[q.norm] = 1;
          var xr = X[q.norm]; if (!xr || !xr.w) return;
          var g = 0, t = 0; prev.forEach(function (w) { var r = xr.w[w] || xr.w[String(w)]; if (r) { g++; t += +r[0] || 0; } });
          teamTgt += t; if (g >= 2) rows.push({ q: q, t: t });
        });
        if (teamTgt / TEAM_VAC.trail >= TEAM_VAC.minTeamTgt) {
          rows.forEach(function (e) { var sh = e.t / teamTgt; if ((wnd.SIM_RB_NOSPILL === false || e.q.pos !== 'RB') && sh >= TEAM_VAC.minShare && injAdj(e.q, wk) === 0) T += sh; });
        }
      }
      _tvCache.t[key] = T;
    }
    return T > 0 ? 1 + TEAM_VAC.k * T : 1;
  }
  var TOP_OUT_TRIM = { mult: 0.91, ranks: 2, trail: 3 };
  var _totCache = { src: null, t: {} };
  function topOutTrimMult(p, wk, schedule) {
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_TOP_OUT_TRIM === false || !_inj || wk !== cwOf(p) || !_poolByNorm || p.pos !== 'WR') return 1;
    if (injAdj(p, wk) === 0) return 1;
    if (_totCache.src !== _inj) _totCache = { src: _inj, t: {} };
    var T = _totCache.t[p.tm];
    if (T === undefined) {
      T = null;
      var X = wnd.SIM_XFP_2026, gw = (schedule && schedule.gameWeeks && schedule.gameWeeks[p.tm]) || [];
      var prev = gw.filter(function (w) { return w < wk; }).slice(-TOP_OUT_TRIM.trail);
      if (X && prev.length === TOP_OUT_TRIM.trail) {
        var rows = [], seen = {};
        Object.keys(_poolByNorm).forEach(function (k) {
          var q = _poolByNorm[k]; if (!q || seen[q.norm] || q.tm !== p.tm || (q.pos !== 'WR' && q.pos !== 'TE' && q.pos !== 'RB')) return; seen[q.norm] = 1;
          var xr = X[q.norm]; if (!xr || !xr.w) return;
          var g = 0, t = 0; prev.forEach(function (w) { var r = xr.w[w] || xr.w[String(w)]; if (r) { g++; t += +r[0] || 0; } });
          if (g >= 2) rows.push({ q: q, t: t });
        });
        rows.sort(function (a, b) { return b.t - a.t; });
        if (rows.length && rows[0].q.pos === 'WR' && injAdj(rows[0].q, wk) === 0) {
          T = {};
          rows.filter(function (e) { return e.q.pos === 'WR' && injAdj(e.q, wk) !== 0; }).slice(0, TOP_OUT_TRIM.ranks).forEach(function (e) { T[e.q.norm] = 1; });
        }
      }
      _totCache.t[p.tm] = T;
    }
    return T && T[p.norm] ? TOP_OUT_TRIM.mult : 1;
  }
  var QB_TE_OUT = { mult: 1.06, minShare: 0.10, trail: 3 };
  var _qtCache = { src: null, t: {} };
  function qbTeOutMult(p, wk, schedule) {
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_QB_TE_OUT === false || !_inj || !_poolByNorm || p.pos !== 'QB') return 1;
    if (injAdj(p, wk) === 0) return 1;
    if (_qtCache.src !== _inj) _qtCache = { src: _inj, t: {} };
    var key = p.tm + '|' + wk;
    if (_qtCache.t[key] !== undefined) return _qtCache.t[key];
    var res = 1, X = wnd.SIM_XFP_2026, gw = (schedule && schedule.gameWeeks && schedule.gameWeeks[p.tm]) || [];
    var ref = Math.min(wk, cwOf(p) || wk), prev = gw.filter(function (w) { return w < ref; }).slice(-QB_TE_OUT.trail);
    if (X && prev.length === QB_TE_OUT.trail) {
      var seen = {}, teamTgt = 0, tes = [];
      Object.keys(_poolByNorm).forEach(function (k) {
        var q = _poolByNorm[k]; if (!q || seen[q.norm] || q.tm !== p.tm || (q.pos !== 'WR' && q.pos !== 'TE' && q.pos !== 'RB')) return; seen[q.norm] = 1;
        var xr = X[q.norm]; if (!xr || !xr.w) return;
        var g = 0, t = 0; prev.forEach(function (w) { var r = xr.w[w] || xr.w[String(w)]; if (r) { g++; t += +r[0] || 0; } });
        teamTgt += t; if (q.pos === 'TE' && g >= 2) tes.push({ q: q, t: t });
      });
      if (teamTgt > 0 && tes.some(function (e) { return e.t / teamTgt >= QB_TE_OUT.minShare && injAdj(e.q, wk) === 0; })) res = QB_TE_OUT.mult;
    }
    _qtCache.t[key] = res;
    return res;
  }
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
    var pv = [];
    if (P) Object.keys(P).forEach(function (tm) { var c = P[tm] && P[tm].cur; if (c && c.games >= ROS_TILT.minGames && typeof c.plays === 'number') pv.push([normTeam(tm), c.plays]); });
    out.plays = z(pv);
    _rosZ = out; return out;
  }
  function rosTilt(p, wk) {
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_ROS_TILT === false || !_inj || !(_inj.week >= 1) || wk <= cwOf(p)) return 1;
    var e = ROS_TILT[p.pos]; if (!e || p.isDST) return 1;
    var Z = rosTiltZ(), z = p.pos === 'QB' ? Z.qb[p.norm] : Z.team[p.tm];
    if (typeof z !== 'number') return 1;
    var ramp = Math.min(1, (wk - cwOf(p)) / 2);
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
    if (c.qb.qbWindow) return false;
    return !chartAvailable(c.qb.name, wk);
  }
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
  function shadowVegasScale(p, wk, schedule) {
    if (typeof window !== 'undefined' && window.SIM_NC_VEGEV === false) return null;
    var k = NC_SHADOW.vegEvK; if (!k) return null;
    var d = jsData(), rec = d.players && d.players[p.norm], bt = schedule && schedule.byTeam && schedule.byTeam[p.tm];
    if (!rec || !rec.wf || !bt) return null;
    var raw = 0, adj = 0, n = 0;
    Object.keys(rec.wf).forEach(function (w) {
      if (+w >= wk) return; var pts = +rec.wf[w]; if (!isFinite(pts)) return;
      var s0 = bt[w] || bt[+w], m = s0 && s0.implied != null ? vegasMult(s0.implied, schedule.avgImplied, p.pos, vegasTeamAvg(p, schedule)) : 1;
      raw += pts; adj += pts / Math.pow(Math.max(0.6, Math.min(1.6, m)), k); n++;
    });
    if (!n || !(raw > 0)) return null;
    return Math.max(0.75, Math.min(1.35, adj / raw));
  }
  var LIVE_USAGE = {
    WR: { c: [0.37, 0.53, 0.005, 0.050], lam: [[1, 0.8], [2, 0.8], [3, 0.6], [5, 0.6], [8, 0.5], [99, 0.3]] },
    TE: { c: [-1.87, 0.47, 0.023, 0.057], lam: [[99, 0.3]], lamOld: [[3, 0], [5, 0.3], [8, 0.3], [99, 0.3]] }
  };
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
    if (!xr || !xr.w || !sn || !sn.w || !rr) return null;
    var H = PRESETS.half, xh = 0, xs = 0, nX = 0, wX = 0, sSum = 0, nS = 0, wS = 0, rSum = 0, nR = 0, nHurt = 0;
    var fsU = fillinStale(p, wk);
    Object.keys(xr.w).forEach(function (k) {
      if (+k >= wk) return; var r = xr.w[k]; if (!r) return; nX++;
      var fk = (fsU && fsU.weeks.indexOf(+k) >= 0) ? 1 / fsU.B : 1;
      var hw = hurtGameW(p, +k, wk, sn); if (hw < 1) nHurt++; wX += hw;
      xh += hw * fk * (H.rec * (r[1] || 0) + H.rec_yd * (r[2] || 0) + H.rec_td * (r[3] || 0) + H.rush_yd * (r[5] || 0) + H.rush_td * (r[6] || 0));
      var xsk = sc.rec * (r[1] || 0) + sc.rec_yd * (r[2] || 0) + sc.rec_td * (r[3] || 0) + sc.rush_yd * (r[5] || 0) + sc.rush_td * (r[6] || 0);
      if (p.pos === 'TE' && sc.bonus_rec_te) xsk += sc.bonus_rec_te * (r[1] || 0);
      xs += hw * fk * xsk;
    });
    Object.keys(sn.w).forEach(function (k) { if (+k < wk && typeof sn.w[k] === 'number') { var hw = hurtGameW(p, +k, wk, sn); sSum += hw * sn.w[k]; nS++; wS += hw; } });
    Object.keys(rr).forEach(function (k) { if (+k < wk && typeof rr[k] === 'number') { rSum += rr[k]; nR++; } });
    if (!nX || !nS || !nR) return null;
    var gN = Math.max(rec.g, nX) - nX + wX, c = cfg.c, snapAvg = wS > 0 ? sSum / wS : sSum / nS;
    var uHalf = Math.max(0, c[0] + c[1] * (xh / gN) + c[2] * (rSum / nR) + c[3] * snapAvg);
    var toSheet = xh > 0 ? xs / xh : 1;
    return { xfpPg: uHalf * toSheet, lam: lam, half: uHalf, snap: snapAvg, route: rSum / nR, xfpHalf: xh / gN, hurtG: nHurt };
  }
  function shadowUsage(p, wk, sc) {
    if (typeof window !== 'undefined' && window.SIM_NC_USAGE === false) return null;
    var sch = NC_SHADOW.usageLam[p.pos]; if (!sch) return null;
    var X = typeof window !== 'undefined' ? window.SIM_XFP_2026 : null, xr = X && X[p.norm], d = jsData(), rec = d.players && d.players[p.norm];
    if (!xr || !xr.w || !rec || !rec.g) return null;
    var tot = 0, nW = 0, fsN = (ncFillinOn() && FILLIN.ncBoost[p.pos]) ? fillinStale(p, wk) : null;
    Object.keys(xr.w).forEach(function (k) {
      if (+k >= wk) return; var r = xr.w[k]; if (!r) return; nW++;
      var fk = fsN ? ncFillinGameF(fsN, p, +k) : 1;
      tot += fk * (sc.rec * (r[1] || 0) + sc.rec_yd * (r[2] || 0) + sc.rec_td * (r[3] || 0) + sc.rush_yd * (r[5] || 0) + sc.rush_td * (r[6] || 0));
      if (p.pos === 'TE' && sc.bonus_rec_te) tot += fk * sc.bonus_rec_te * (r[1] || 0);
    });
    if (!nW) return null;
    var gN = Math.max(rec.g, nW), lam = Math.max(sch[2], sch[0] - sch[1] * Math.max(0, rec.g - 1));
    return { xfpPg: tot / gN, lam: lam };
  }
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
        if (qb) t.ry += r[4] || 0;
        else { t.rec += r[1] || 0; t.rcy += r[2] || 0; t.ry += r[5] || 0; }
      });
      if (nW) { var gN = Math.max(rec.g, nW); u = { ry: t.ry / gN, rec: t.rec / gN, rcy: t.rcy / gN }; }
    }
    return { g: rec.g, a: rec.pg, u: u };
  }
  var JS_FPA_ELASTICITY = 0.25;
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

  var VEGAS_ELAS = { QB: 0.25, RB: 0.50, WR: 0.25, TE: 0.25, K: 0.50 };
  var VEGAS_ELAS_SPLIT = { QB: 0.50, RB: 0.50, WR: 0.375, TE: 0.375, K: 0.50 };
  var VEGAS_SPLIT_K = 2;
  function vegasSplitOn() { return !(typeof window !== 'undefined' && window.SIM_VEGAS_SPLIT === false); }
  function vegasTeamAvg(p, schedule) {
    if (!vegasSplitOn() || !p || p.isDST || p.pos === 'K' || !schedule || !schedule.byTeam) return null;
    var cw = cwOf(p); if (!(cw >= 2)) return null;
    var bt = schedule.byTeam[p.tm]; if (!bt) return null;
    var cache = _inj ? (_inj.vegTA = _inj.vegTA || {}) : null, key = p.tm + '|' + cw;
    if (cache && cache[key] && cache[key].s === schedule) return cache[key].v;
    var lg = schedule.avgImplied || 22.5, sum = 0, n = 0;
    Object.keys(bt).forEach(function (w) {
      if (!(+w < cw)) return; var s0 = bt[w], v = s0 ? (s0.bookImplied != null ? s0.bookImplied : s0.implied) : null;
      if (typeof v === 'number' && isFinite(v)) { sum += v; n++; }
    });
    var v = n ? (sum + VEGAS_SPLIT_K * lg) / (n + VEGAS_SPLIT_K) : null;
    if (cache) cache[key] = { s: schedule, v: v };
    return v;
  }
  function vegasMult(implied, avgImplied, pos, teamAvg) {
    var split = teamAvg != null && vegasSplitOn();
    var E_ = split ? VEGAS_ELAS_SPLIT : VEGAS_ELAS, e = E_[pos] != null ? E_[pos] : VEGAS_ELASTICITY;
    var m = 1 + e * ((implied - (split ? teamAvg : avgImplied)) / avgImplied);
    return Math.min(1.35, Math.max(0.7, m));
  }
  var DST_DEFAULT = { sack: 1, int: 2, fum_rec: 2, ff: 0, def_td: 6, safe: 2, blk_kick: 2 };
  var DST_COUNT = {
    sack: [4.3772, -0.08788], int: [1.2205, -0.02023], fum_rec: [0.7457, -0.00998], ff: [1.0494, -0.01180],
    def_td: [0.2479, -0.00546], safe: [0.0519, -0.00105], blk_kick: [0.0770, -0.00096]
  };
  var DST_PA = { a: -0.1704, b: 1.0213, sd: 9.123 };
  var DST_PA_BUCKETS = [
    ['pts_allow_0', -1, 0, 10], ['pts_allow_1_6', 0, 6, 7], ['pts_allow_7_13', 6, 13, 4], ['pts_allow_14_20', 13, 20, 1],
    ['pts_allow_21_27', 20, 27, 0], ['pts_allow_28_34', 27, 34, -1], ['pts_allow_35p', 34, 999, -4]
  ];
  function dstScoringFrom(ls) {
    var out = {};
    Object.keys(DST_DEFAULT).forEach(function (k) { out[k] = num(ls[k], DST_DEFAULT[k]); });
    DST_PA_BUCKETS.forEach(function (b) { out[b[0]] = num(ls[b[0]], b[3]); });
    return out;
  }
  function normCdf(x) {
    var z = Math.abs(x) / Math.SQRT2, t = 1 / (1 + 0.3275911 * z);
    var e = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-z * z);
    return x >= 0 ? 0.5 * (1 + e) : 0.5 * (1 - e);
  }
  function dstScoringDelta(oppImplied, sc) {
    var r = sc && sc.dst;
    if (!r || (typeof window !== 'undefined' && window.SIM_DST_LEAGUE_SCORING === false)) return 0;
    var d = 0;
    Object.keys(DST_DEFAULT).forEach(function (k) {
      var dv = r[k] - DST_DEFAULT[k];
      if (dv) d += dv * Math.max(0, DST_COUNT[k][0] + DST_COUNT[k][1] * oppImplied);
    });
    var mu = DST_PA.a + DST_PA.b * oppImplied, sd = DST_PA.sd;
    DST_PA_BUCKETS.forEach(function (b) {
      var dv = r[b[0]] - b[3];
      if (!dv) return;
      var pHi = normCdf((b[2] + 0.5 - mu) / sd), pLo = b[1] < 0 ? 0 : normCdf((b[1] + 0.5 - mu) / sd);
      d += dv * (pHi - pLo);
    });
    return d;
  }
  function dstWeeklyMean(oppImplied, sc) {
    var m = 16.2 - 0.436 * oppImplied;
    if (typeof window !== 'undefined' && window.SIM_TUNING && typeof window.SIM_TUNING.dstShift === 'number') m += window.SIM_TUNING.dstShift;
    m = Math.max(1.0, m);
    var d = dstScoringDelta(oppImplied, sc);
    return d ? Math.max(0.5, m + d) : m;
  }

  var PROP_W            = 0.70;
  var PROP_COVERAGE_MIN = 0.60;
  var PROP_ATD_JUICE    = 1.06;
  var PROP_MAX_AGE_DAYS = 8;
  var PROP_DOCKED_MAX_AGE_DAYS = 2;
  var PROP_STATS = ['py', 'ry', 'rcy', 'rec'];
  var PROP_SC    = { py: 'pass_yd', ry: 'rush_yd', rcy: 'rec_yd', rec: 'rec' };
  var PROP_LINE_SCALE = { py: 1.0, ptd: 1.0, ry: 1.0, rec: 1.0, rcy: 1.0 };
  function propLineScale(k) {
    var o = (typeof window !== 'undefined' && window.SIM_PROP_LINE_SCALE) || null;
    if (o && typeof o[k] === 'number' && o[k] > 0) return o[k];
    return PROP_LINE_SCALE[k] != null ? PROP_LINE_SCALE[k] : 1.0;
  }

  var _propWkCache = {};
  function propCacheReset() { _propWkCache = {}; }
  function propMap(wk) {
    var props = (typeof window !== 'undefined' && window.GAME_ENV_2026 &&
      window.GAME_ENV_2026.weeklyProps && window.GAME_ENV_2026.weeklyProps[String(wk)]) || null;
    var c = _propWkCache[wk];
    if (c && c.src === props) return c.map;
    var map = {};
    if (props) Object.keys(props).forEach(function (nm) { map[norm(nm)] = props[nm]; });
    _propWkCache[wk] = { src: props, map: map };
    return map;
  }
  function propConsensus(entry, k) {
    var vals = [];
    ['UD', 'PP', 'DK', 'FD', 'MGM'].forEach(function (b) {
      if (entry[b] && typeof entry[b][k] === 'number') vals.push(entry[b][k]);
    });
    if (!vals.length) return null;
    vals.sort(function (a, b) { return a - b; });
    return vals[Math.floor(vals.length / 2)];
  }
  function gammaMedRatio(p) {
    var rel = p._relW !== undefined ? p._relW
      : Math.sqrt(Math.pow(RESID_SHRINK * (p.sigmaPct || 0.5), 2) + 0.04);
    var k = 1 / (rel * rel);
    return Math.min(1.0, Math.max(0.75, (3 * k - 0.8) / (3 * k + 0.2)));
  }
  function amToProb(odds) { return odds < 0 ? -odds / (-odds + 100) : 100 / (odds + 100); }
  function propWeight(p) {
    var ov = (typeof window !== 'undefined' && window.PROP_ANCHOR_OVERRIDES) || {};
    var w = ov[p.name] != null ? ov[p.name]
      : (typeof window !== 'undefined' && typeof window.PROP_W_OVERRIDE === 'number')
        ? window.PROP_W_OVERRIDE
      : (typeof window !== 'undefined' && window.SIM_TUNING && window.SIM_TUNING.propW
         && typeof window.SIM_TUNING.propW[p.pos] === 'number')
        ? window.SIM_TUNING.propW[p.pos] : PROP_W;
    return w > 0 ? Math.min(1, w) : 0;
  }

  function propImpliedFp(p, entry, sc, compsWk) {
    var medRatio = gammaMedRatio(p);
    var useGamma = (typeof window !== 'undefined' && window.SIM_PROP_GAMMA_RATIO === true);
    function lineMean(k, line) { return useGamma ? line / medRatio : line * propLineScale(k); }
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
    var ptdLine = propConsensus(entry, 'ptd');
    fp += (ptdLine != null && ptdLine > 0 ? lineMean('ptd', ptdLine) : (compsWk.ptd || 0)) * sc.pass_td;
    var atd = propConsensus(entry, 'atd');
    var rtdM = compsWk.rtd || 0, rctdM = compsWk.rctd || 0;
    if (atd != null) {
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
    var maxAge = maxAgeDays != null ? maxAgeDays : PROP_MAX_AGE_DAYS;
    if (entry.asOf && new Date(entry.asOf).getTime() < Date.now() - maxAge * 86400000) return null;
    var w = propWeight(p);
    if (!w) return null;
    var fp = propImpliedFp(p, entry, sc, compsWk);
    if (fp == null) return null;
    var ovMap = (typeof window !== 'undefined' && window.PROP_ANCHOR_OVERRIDES) || {};
    var TU = (typeof window !== 'undefined' && window.SIM_TUNING) || null;
    if (TU && typeof TU.belowW === 'number' && ovMap[p.name] == null
        && fp - base >= BELOW_GAP && fp >= BELOW_STARTER_MIN) w = Math.min(w, Math.max(0, TU.belowW));
    if (TU && typeof TU.aboveW === 'number' && ovMap[p.name] == null
        && ABOVE_POS[p.pos] && base - fp >= ABOVE_GAP && fp < ABOVE_MARKET_MAX) w = Math.max(w, Math.min(1, TU.aboveW));
    p._propWUsed = w;
    var anchored = w * fp + (1 - w) * base;
    if (!(typeof window !== 'undefined' && window.SIM_BOOK_CAP === false) && !p._vacBoost && bookLinesFull(p, entry) && anchored > fp * (1 + BOOK_CAP.above)) {
      anchored = fp * (1 + BOOK_CAP.above); p._bookCapped = true;
    } else p._bookCapped = false;
    return anchored;
  }
  var WORKHORSE = { share: 0, car: 0.40, cap: 8 };
  var BOOK_CAP = { above: 0.20, need: { QB: ['py', 'ptd', 'ry'], RB: ['ry', 'rec', 'rcy', 'atd'], WR: ['rec', 'rcy', 'atd'], TE: ['rec', 'rcy', 'atd'] } };
  function bookLinesFull(p, entry) {
    var need = BOOK_CAP.need[p.pos];
    if (!need || !entry) return false;
    for (var i = 0; i < need.length; i++) {
      var k = need[i];
      if (k === 'atd') {
        var has = Object.keys(entry).some(function (b) { var r = entry[b]; return r && typeof r === 'object' && typeof r.atd === 'number' && r.atd !== 0; });
        if (!has) return false;
      } else {
        var v = propConsensus(entry, k);
        if (!(v != null && v > 0)) return false;
      }
    }
    return true;
  }
  var BELOW_GAP = 3.0;
  var BELOW_STARTER_MIN = 8.0;
  var ABOVE_GAP = 1.0;
  var ABOVE_POS = { WR: 1 };
  var ABOVE_MARKET_MAX = 12.0;

  var MKT_HALF_LIFE  = 3;
  var MKT_FULL_TRUST = 2;

  var MKT_CTX_MIN_PPG = 3.0;
  var MKT_CTX_MIN_REL = 0.30;
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
    if (gi <= 0) return false;
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
    var wp = (wnd && wnd.GAME_ENV_2026 && wnd.GAME_ENV_2026.weeklyProps) || {};
    var obs = [];
    Object.keys(wp).forEach(function (k) {
      var owk = +k;
      if (!owk || owk === wk) return;
      var entry = propMap(owk)[p.norm];
      if (!entry) return;
      var slot = schedule.byTeam[p.tm] && schedule.byTeam[p.tm][owk];
      if (!slot) return;
      var gi = (schedule.gameWeeks[p.tm] || []).indexOf(owk) + 1;
      if (p.qbWindow && (gi < p.qbWindow.s || gi > p.qbWindow.e)) return;
      if (marketObsContaminated(p, owk, wk, schedule)) return;
      var perGameDiv = p.qbWindow ? p.qbWindow.games : clayDiv(p);
      var rampF = 1;
      if (p.ramp) {
        var R = RAMP[p.ramp];
        rampF = (gi > 0 && gi <= R.head.length) ? R.head[gi - 1] : R.tail;
      }
      var f = vegasMult(slot.implied, schedule.avgImplied, p.pos, vegasTeamAvg(p, schedule))
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

  var _inj = null;
  function teamCurWeeks(list, schedule, cw) {
    var wnd = typeof window !== 'undefined' ? window : {}, out = {};
    if (wnd.SIM_TEAM_CURWK === false || !(cw >= 1) || !list) return out;
    var KOall = wnd.SIM_KICKOFFS_2026, KO = KOall && KOall[cw], nowMs = +wnd.SIM_NOW_MS || Date.now();
    var bt = schedule && schedule.byTeam, pl = jsData().players || {}, recN = {};
    if (!KO) list.forEach(function (p) { var r = pl[p.norm]; if (p.tm && r && r.wks && r.wks.indexOf(cw) >= 0) recN[p.tm] = (recN[p.tm] || 0) + 1; });
    list.forEach(function (p) {
      var tm = p.tm; if (!tm || out[tm] !== undefined) return;
      var hasGame = bt ? !!(bt[tm] && bt[tm][cw]) : (KO ? !!(KO[normTeam(tm)] || KO[tm]) : true);
      var done = false;
      if (!hasGame) done = true;
      else if (KO) { var iso = KO[normTeam(tm)] || KO[tm], t0 = iso ? Date.parse(iso) : NaN; done = isFinite(t0) && nowMs >= t0 + 4.5 * 3600000; }
      else done = (recN[tm] || 0) >= 3;
      out[tm] = done ? cw + 1 : cw;
    });
    return out;
  }
  function cwOf(p) { return (_inj && _inj.teamCw && p && _inj.teamCw[p.tm]) || (_inj ? _inj.week : 0); }
  var NEW_TEAM_DEBUT = { mult: 0.7, pos: { RB: 1, WR: 1, TE: 1 } };
  function newTeamDebutMult(p, wk, schedule) {
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_NEW_TEAM_DEBUT === false || !_inj || !p || p.isDST || !NEW_TEAM_DEBUT.pos[p.pos]) return 1;
    var TW = wnd.SIM_TEAM_WEEKS_2026, tw = TW && TW[p.name]; if (!tw) return 1;
    var mine = normTeam(p.tm), cw = cwOf(p), lastW = 0, lastT = null, onNew = false;
    Object.keys(tw).forEach(function (k) { var w = +k, t = normTeam(tw[k]); if (!(w < cw)) return; if (t === mine) onNew = true; if (w > lastW) { lastW = w; lastT = t; } });
    if (!lastT || onNew || lastT === mine) return 1;
    var bt = schedule && schedule.byTeam && schedule.byTeam[p.tm]; if (!bt) return 1;
    for (var w = cw; w <= WEEKS; w++) if (bt[w]) return wk === w ? NEW_TEAM_DEBUT.mult : 1;
    return 1;
  }
  var INJ_SHARE = { QB: 0.85, RB: 0.60, WR: 0.60, TE: 0.60 };
  var BANGED = {"Q-FP":{"QB":{"play":0.824,"cond":0.951},"RB":{"play":0.898,"cond":0.952},"WR":{"play":0.885,"cond":0.961},"TE":{"play":0.863,"cond":0.955}},"Q-LP":{"QB":{"play":0.539,"cond":0.941},"RB":{"play":0.715,"cond":0.942},"WR":{"play":0.763,"cond":0.943},"TE":{"play":0.765,"cond":0.933}},"Q-DNP":{"QB":{"play":0.424,"cond":0.891},"RB":{"play":0.444,"cond":0.877},"WR":{"play":0.523,"cond":0.884},"TE":{"play":0.497,"cond":0.891}},"D":{"QB":{"play":0.006,"cond":1.0},"RB":{"play":0.005,"cond":1.0},"WR":{"play":0.02,"cond":1.0},"TE":{"play":0.006,"cond":1.0}}};
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
  function injGroup(p, wk) {
    var S = injSig(); if (!S) return '';
    var r = S.prac && S.prac[wk] ? S.prac[wk][p.norm] : null;
    if (r && r.g) return r.g;
    var b = S.body ? S.body[p.norm] : null;
    return (b && b.g) || '';
  }
  var _luCache = {};
  function linesUp(p, wk) {
    var B = (typeof window !== 'undefined' && window.GAME_ENV_2026 && window.GAME_ENV_2026.weeklyProps) || null;
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
  function injSignalInfo(p, wk) {
    var S = injSig(); if (!S) return null;
    var r = S.prac && S.prac[wk] ? S.prac[wk][p.norm] : null, b = S.body ? S.body[p.norm] : null, n = S.news ? S.news[p.norm] : null;
    var m = _inj && _inj.map ? _inj.map[p.norm] : null;
    return { g: injGroup(p, wk), seq: r ? r.seq : '', gs: r ? r.gs : '', inj: r ? r.inj : '', body: b ? (b.b + (b.n ? ' (' + b.n + ')' : '')) : '', news: n || null, lines: linesUp(p, wk), src: m ? m.src : '', note: m ? (m.note || '') : '' };
  }
  var Q_STREAK = { 1: -0.24, 2: -0.45, 3: -0.33 };
  function bangedDock(cls, pos, g, newsPlay, streak) {
    var t = BANGED[cls], d = t && (t[pos] || t.WR);
    if (!d) return null;
    var play = d.play, w = typeof window !== 'undefined' ? window : {};
    if (w.SIM_INJ_TYPE !== false && INJ_PLAY[cls]) {
      play = INJ_PLAY[cls][pos] || play;
      var s = (g && INJ_TYPE[cls]) ? (INJ_TYPE[cls][g] || 0) : 0;
      if (s) play = _sgm(_lgt(play) + s);
    }
    if (streak >= 1 && cls !== 'D' && w.SIM_Q_STREAK !== false) play = _sgm(_lgt(play) + Q_STREAK[Math.min(3, streak)]);
    if (newsPlay && cls !== 'D') play = Math.max(play, NEWS_PLAY);
    return { mult: +(play * d.cond).toFixed(3), play: +play.toFixed(3), cond: d.cond };
  }
  var POOL = {
    RB: { lead: { tgtSame: [0.28, 0.18], carSame: [0.28, 0.16, 0.10], tgtOther: 0 },
          sec:  { tgtSame: [0.28, 0.18], carSame: [0.28, 0.16, 0.10], tgtOther: 0 } },
    WR: { lead: { tgtSame: [0.09, 0.15, 0.16, 0.10], carSame: [], tgtOther: 0.08 },
          sec:  { tgtSame: [0.00, 0.11, 0.15, 0.10], carSame: [], tgtOther: 0.00 } },
    TE: { lead: { tgtSame: [0.25, 0.10], carSame: [], tgtOther: 0.36 },
          sec:  { tgtSame: [0.00, 0.22], carSame: [], tgtOther: 0.00 } }
  };
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
  var POOL_LEVEL_FLOOR = 4.0;
  var POOL_CR  = { RB: 0.77, WR: 0.63, TE: 0.68 };
  var POOL_YPC = { RB: 4.3, WR: 6.0, TE: 5.0 };
  function poolStats(p, div) {
    var c = p.comps || {};
    var tgt = (c.rec || 0) / (POOL_CR[p.pos] || 0.65) / div;
    var car = (c.ry || 0) / (POOL_YPC[p.pos] || 4.5) / div;
    var rpts = ((c.rec || 0) * 1 + (c.rcy || 0) * 0.1 + (c.rctd || 0) * 6) / div;
    var cpts = ((c.ry || 0) * 0.1 + (c.rtd || 0) * 6) / div;
    return { tgt: tgt, car: car, ppt: tgt > 0 ? rpts / tgt : 0, ppc: car > 0 ? cpts / car : 0 };
  }
  var QS_CAND = { min: 2.0, max: 6, pos: { QB: 1, RB: 1, WR: 1, TE: 1 } };
  function qsCandidates(players, cw, schedule, opts) {
    opts = opts || {};
    var list = players.list || players, wnd = typeof window !== 'undefined' ? window : {};
    var prRaw = wnd.SIM_PRACTICE_2026, prN = {};
    if (prRaw && prRaw.players && (!prRaw.week || +prRaw.week === +cw)) Object.keys(prRaw.players).forEach(function (n) { prN[n.toLowerCase()] = prRaw.players[n]; });
    var cand0 = list.filter(function (p) {
      if (p.isDST || !QS_CAND.pos[p.pos]) return false;
      if (opts.skipTeam && opts.skipTeam(p.tm)) return false;
      var t = String(p.injFlag || '').toLowerCase().split('|')[0], g = String((prN[p.name.toLowerCase()] || {}).gs || '').toLowerCase();
      if (!(/questionable|doubtful|^out$/.test(t) || /questionable|doubtful/.test(g))) return false;
      return injAdj(p, cw) > 0;
    });
    var byTm = {}, lvl = {};
    if (cand0.length) {
      var allIn = {}; cand0.forEach(function (q) { allIn[q.name] = 'in'; });
      applyInSeasonInjuries(players, cw, { active: true, force: allIn });
      cand0.forEach(function (q) { var h = weeklyProjection(q, cw, PRESETS.half, schedule); lvl[q.name] = h ? effMean(h) : 0; });
      applyInSeasonInjuries(players, cw, opts.restore || { active: true });
      cand0.filter(function (q) { return lvl[q.name] >= QS_CAND.min; }).sort(function (a, b) { return lvl[b.name] - lvl[a.name]; })
        .forEach(function (q) { var a = byTm[q.tm] || (byTm[q.tm] = []); if (a.length < QS_CAND.max) a.push(q); });
    }
    return { byTm: byTm, lvl: lvl };
  }
  function qsForce(players, cw, schedule, outNames, opts) {
    var C = qsCandidates(players, cw, schedule, opts), outN = {}, force = {}, list = players.list || players;
    (outNames || []).forEach(function (n) { var k = norm(n); outN[k] = 1; if (CLAY_NORM_ALIAS[k]) outN[CLAY_NORM_ALIAS[k]] = 1; Object.keys(CLAY_NORM_ALIAS).forEach(function (a) { if (CLAY_NORM_ALIAS[a] === k) outN[a] = 1; }); });
    Object.keys(C.byTm).forEach(function (tm) { C.byTm[tm].forEach(function (q) { force[q.name] = outN[q.norm] ? 'out' : 'in'; }); });
    list.forEach(function (p) { if (!p.isDST && outN[p.norm]) force[p.name] = 'out'; });
    return { force: force, cands: C };
  }
  function qbChartWindows(list, sched, cw) {
    var wnd = typeof window !== 'undefined' ? window : {};
    list.forEach(function (p) { if (p.pos === 'QB' && p._qbWinOrig !== undefined) p.qbWindow = p._qbWinOrig; });
    var D = wnd.SIM_DEPTH_2026 && wnd.SIM_DEPTH_2026.teams;
    if (wnd.SIM_QB_CHART === false || !D || !sched || !sched.gameWeeks || !(cw >= 1)) return [];
    var rooms = {}, changed = [];
    list.forEach(function (p) { if (p.pos === 'QB' && !p.isDST && p.qbWindow) rooms[p.tm] = true; });
    Object.keys(rooms).forEach(function (tm) {
      var ct = Object.keys(D).filter(function (t) { return normTeam(t) === tm; })[0];
      var chart = ct && D[ct].QB ? D[ct].QB.map(norm) : [];
      if (!chart.length) return;
      var room = list.filter(function (p) { return p.pos === 'QB' && !p.isDST && p.tm === tm; });
      var q1 = room.filter(function (p) { return p.norm === chart[0]; })[0];
      if (!q1) return;
      var gw = sched.gameWeeks[tm] || [], curG = 0, nG = gw.length;
      for (var i = 0; i < gw.length; i++) if (gw[i] >= cw) { curG = i + 1; break; }
      if (!curG) return;
      room.forEach(function (p) {
        var w = p._qbWinOrig !== undefined ? p._qbWinOrig : (p.qbWindow || null);
        if (p === q1) {
          if (w && w.s >= 1 && w.s <= curG && w.e >= nG) return;
          if (p._qbWinOrig === undefined) p._qbWinOrig = p.qbWindow || null;
          p.qbWindow = { s: (w && w.s >= 1 && w.s < curG) ? w.s : curG, e: nG, games: (w && w.games) || p.clayGames || 17, src: (w && w.src) || 'override', chart: true };
          changed.push(p.name + ' starts g' + p.qbWindow.s + '-' + nG);
        } else if (w) {
          if (p._qbWinOrig === undefined) p._qbWinOrig = p.qbWindow || null;
          p.qbWindow = null;
          changed.push(p.name + ' backup (window dropped)');
        }
      });
    });
    return changed;
  }
  function applyInSeasonInjuries(players, currentWeek, opts) {
    _ncCache = {}; _qbfMu = {};
    _fillinCache = {};
    _chartPreCache = {};
    _peckCache = {};
    opts = opts || {};
    var list = players.list || players;
    var wnd = typeof window !== 'undefined' ? window : {};
    _inj = { week: currentWeek, map: {}, adj: {}, play: {}, zeros: [] };
    _inj.teamCw = teamCurWeeks(list, players.schedule || null, currentWeek);
    _inj.qbChart = qbChartWindows(list, players.schedule || null, currentWeek);
    if (opts.active === false || wnd.SIM_INJ_LAYER === false || !(currentWeek >= 1)) return _inj;
    var ov = wnd.IN_SEASON_OUT_OVERRIDES || {};
    var map = _inj.map;
    var bangedOn = wnd.SIM_BANGED !== false;
    var SIG = injSig(), newsOn = wnd.SIM_NEWS_WINDOWS !== false && SIG && SIG.news;
    var newsPlayOf = function (p) { var n = newsOn ? SIG.news[p.norm] : null; return !!(n && n.flag && n.flag.k === 'play'); };
    var missStreak = function (p) {
      var rec = jsData().players ? jsData().players[p.norm] : null, wks = rec && rec.wks ? rec.wks : [];
      var gw = (players.schedule && players.schedule.gameWeeks && players.schedule.gameWeeks[p.tm]) || [], k = 0;
      if (wks.filter(function (w0) { return w0 < currentWeek; }).length < 2) return 0;
      for (var gi = gw.length - 1; gi >= 0; gi--) {
        if (gw[gi] >= currentWeek) continue;
        if (wks.indexOf(gw[gi]) >= 0) break;
        k++;
      }
      return k;
    };
    var Q_NEXT = { 'Q-FP': { QB: 0.965, RB: 0.919, WR: 0.926, TE: 0.909 }, 'Q-LP': { QB: 0.888, RB: 0.846, WR: 0.852, TE: 0.836 }, 'Q-DNP': { QB: 0.817, RB: 0.778, WR: 0.784, TE: 0.769 } };
    var putDock = function (p, cls, src, legacy) {
      var g = injGroup(p, currentWeek), np = newsPlayOf(p), qk = cls !== 'D' ? missStreak(p) : 0;
      var d = bangedOn ? bangedDock(cls, p.pos, g, np, qk) : null;
      if (d) {
        map[p.norm] = { from: currentWeek, to: currentWeek, mult: d.mult, play: d.play, cond: d.cond, src: src, g: g, qk: qk, note: np ? 'news: expected to play' : '' };
        var qn = Q_NEXT[cls] ? Q_NEXT[cls][p.pos] : null;
        if (qn && wnd.SIM_Q_NEXT !== false && ((_inj.teamCw && _inj.teamCw[p.tm]) || currentWeek) === currentWeek) {
          var qgw = (players.schedule && players.schedule.gameWeeks && players.schedule.gameWeeks[p.tm]) || [];
          var qnx = qgw.filter(function (w0) { return w0 > currentWeek; })[0];
          if (qnx) { map[p.norm].curve = {}; map[p.norm].curve[qnx] = qn; }
        }
        return;
      }
      if (legacy < 1) map[p.norm] = { from: currentWeek, to: currentWeek, mult: legacy, src: src };
    };
    var ovAsOf = String(wnd.IN_SEASON_OUT_OVERRIDES_ASOF || '');
    var prMap = {};
    var prRaw = wnd.SIM_PRACTICE_2026 || null;
    if (prRaw && prRaw.players && (!prRaw.week || +prRaw.week === +currentWeek)) {
      Object.keys(prRaw.players).forEach(function (nm) { prMap[norm(nm)] = prRaw.players[nm]; });
    }
    var force = opts.force || null;
    list.forEach(function (p) {
      if (p.isDST) return;
      if (force && force[p.name] === 'in') return;
      if (force && force[p.name] === 'out') { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0, src: 'scenario-out' }; return; }
      if (force && force[p.name] === 'season-out') { map[p.norm] = { from: currentWeek, to: WEEKS, mult: 0, src: 'scenario-season-out' }; return; }
      if (force && force[p.name] && typeof force[p.name] === 'object' && force[p.name].back != null) {
        var fb = +force[p.name].back;
        if (fb > currentWeek) map[p.norm] = { from: currentWeek, to: Math.min(WEEKS, fb - 1), mult: 0, src: 'scenario-back' };
        return;
      }
      var o = ov[p.name];
      var t = String(p.injFlag || '').toLowerCase();
      var pr = prMap[p.norm] || null;
      var gs = pr ? String(pr.gs || '').toLowerCase() : '';
      var practiced = pr ? String(pr.pr || '') : '';
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
      var oLand = o && o.length >= 2 && o[3] !== 'firm' && (typeof o[3] === 'number' ? o[3] : o[1] + 3) >= currentWeek;
      if (o && o.length >= 2 && !newsNewer && (o[1] >= currentWeek || oLand)) {
        var practicing0 = practiced === 'LP' || practiced === 'FP';
        var firm = o[3] === 'firm' || practicing0;
        if (o[1] < currentWeek && firm) {   }
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
          map[p.norm] = { from: currentWeek, to: currentWeek, mult: ncv[currentWeek], play: ncv[currentWeek], cond: 1, src: 'news-return', curve: ncv, note: nwin.date + ' ' + nwin.hl };
          return;
        }
      }
      var dxB = SIG && SIG.body ? SIG.body[p.norm] : null;
      var dxHl = nws && nws.win && nws.win.hl ? String(nws.win.hl) : '';
      var dxTear = !!dxB && (reserve || /surg|\btorn\b|\btear\b|ruptur/i.test(dxB.n || '')
        || /\b(torn|tore|tears?|ruptured?)\s+(?:(?:his|her|the|a|left|right|full|complete|partial(?:ly)?)\s+)*(achilles|acl)\b|\b(achilles|acl)(?:\s+tendon)?\s+(tear|rupture)/i.test(dxHl));
      if (wnd.SIM_DX_SEASON !== false && dxB && outish && wks0.length && /\b(acl|achilles)\b/i.test(dxB.b || '') && (wnd.SIM_DX_STRICT === false || dxTear)) {
        map[p.norm] = { from: currentWeek, to: WEEKS, mult: 0, src: 'dx-season', note: SIG.body[p.norm].b + (SIG.body[p.norm].n ? ' (' + SIG.body[p.norm].n + ')' : '') };
        return;
      }
      if (nws && nws.out && (tInj !== '' || pr)) { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0, src: 'news-out', note: nws.out.date + ' ' + nws.out.hl }; return; }
      if (t && t !== '|') {
        if (/\bir\b|injured reserve|\bpup\b|\bnfi\b|non football/.test(t)) { map[p.norm] = { from: currentWeek, to: Math.min(WEEKS, currentWeek + 3), mult: 0, src: 'ir' }; return; }
        if (/\bsus\b|suspend/.test(t)) { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0, src: 'sus' }; return; }
        if (/^na\b|\bna\|/.test(t)) {
          var swk2 = wnd.SIM_SLEEPER_WEEKLY || null, sw2 = swk2 && swk2.p && (+swk2.week === +currentWeek) ? swk2.p[p.norm] : null;
          if (!(swk2 && swk2.p && (+swk2.week === +currentWeek)) || sw2 == null || sw2 <= 0) { map[p.norm] = { from: currentWeek, to: Math.min(WEEKS, currentWeek + 3), mult: 0, src: 'na' }; return; }
          map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0.75, src: 'na-unconfirmed' }; return;
        }
        if (/\bout\b/.test(t)) {
          var swk = wnd.SIM_SLEEPER_WEEKLY || null;
          var swOK = swk && swk.p && (+swk.week === +currentWeek);
          var swProj = swOK ? swk.p[p.norm] : null;
          if (!swOK || swProj == null || swProj <= 0 || gs === 'out') { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0, src: 'out' }; return; }
          if (gs === 'doubtful') { putDock(p, 'D', 'nfl-doubtful', 0.5); return; }
          if (wnd.SIM_OUTUNCONF_TIERS !== false) {
            var KO = wnd.SIM_KICKOFFS_2026, kIso = KO && KO[currentWeek] ? (KO[currentWeek][normTeam(p.tm)] || KO[currentWeek][p.tm]) : null;
            var nowMs = +wnd.SIM_NOW_MS || Date.now(), hrs = kIso ? (Date.parse(kIso) - nowMs) / 3600000 : null;
            if (hrs != null && hrs < 36) { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0, src: 'out-gameday', note: 'Sleeper Out ' + Math.max(0, Math.round(hrs)) + ' h before kickoff (inactive list)' }; return; }
            var rec0 = jsData().players ? jsData().players[p.norm] : null;
            var playedPrev = !!(rec0 && rec0.wks && rec0.wks.indexOf(currentWeek - 1) >= 0);
            map[p.norm] = { from: currentWeek, to: currentWeek, mult: playedPrev ? 0.2 : 0.5, src: 'out-unconfirmed', note: playedPrev ? 'new injury (played last game)' : 'Out lingering (missed last game)' }; return;
          }
          map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0.75, src: 'out-unconfirmed' }; return;
        }
        if (/doubtful/.test(t)) {
          var swk3 = wnd.SIM_SLEEPER_WEEKLY || null, sw3ok = swk3 && swk3.p && (+swk3.week === +currentWeek), sw3 = sw3ok ? swk3.p[p.norm] : null;
          if (gs === 'out') { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0, src: 'nfl-out' }; return; }
          if (gs === 'doubtful' || (sw3ok && (sw3 == null || sw3 <= 0))) { putDock(p, 'D', 'doubtful', 0.5); return; }
          if (gs !== 'questionable') { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0.5, src: 'doubtful-unconfirmed' }; return; }
        }
      }
      if (gs === 'out') { map[p.norm] = { from: currentWeek, to: currentWeek, mult: 0, src: 'nfl-out' }; return; }
      if (gs === 'doubtful') { putDock(p, 'D', 'nfl-doubtful', 0.5); return; }
      var questionable = gs === 'questionable' || /questionable/.test(t);
      if (questionable && gs === 'questionable') {
        if (practiced === 'DNP') putDock(p, 'Q-DNP', 'q-dnp', 0.75);
        else if (practiced === 'LP') putDock(p, 'Q-LP', 'q-lp', 1);
        else putDock(p, 'Q-FP', 'q-fp', 1);
      } else if (questionable && practiced === 'DNP') map[p.norm] = { from: currentWeek, to: currentWeek, mult: newsPlayOf(p) ? NEWS_PLAY : 0.75, src: 'q-dnp', note: newsPlayOf(p) ? 'news: expected to play' : '' };
    });
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
    var sched = players.schedule || null;
    var inWindow = function (p, wk) {
      if (!p.qbWindow) return true;
      if (!sched || !sched.gameWeeks) return true;
      var gi = (sched.gameWeeks[p.tm] || []).indexOf(wk) + 1;
      return gi > 0 && gi >= p.qbWindow.s && gi <= p.qbWindow.e;
    };
    var AVAIL_CONT = { 1: 0.65, 2: 0.72, 3: 0.77, 4: 0.77, 5: 0.75, 6: 0.87, 7: 0.86, 8: 0.89 }, AVAIL_H = 8;
    _inj.avail = {};
    if (wnd.SIM_AVAIL_CURVE !== false) {
      var gwOf = function (tm) { return (sched && sched.gameWeeks && sched.gameWeeks[tm]) || []; };
      var availV2 = wnd.SIM_AVAIL_V2 !== false;
      var contOf = function (k, pos, g) {
        var kk = Math.min(8, Math.max(1, k));
        var c = (availV2 && AVAIL_POS[pos]) ? AVAIL_POS[pos][kk - 1] : AVAIL_CONT[kk];
        var sh = (availV2 && g && AVAIL_GRP[g]) ? AVAIL_GRP[g][Math.min(3, kk) - 1] : 0;
        return sh ? _sgm(_lgt(c) + sh) : c;
      };
      list.forEach(function (p) {
        var m = map[p.norm];
        if (!m || m.src !== 'override' || m.firm || m.to >= WEEKS) return;
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
        var nearZero = m && (m.mult === 0 || (m.play != null && m.play <= 0.05));
        if (!m || !nearZero || ['out', 'nfl-out', 'ir', 'na', 'news-out', 'doubtful', 'nfl-doubtful'].indexOf(m.src) < 0) return;
        var rec = jsData().players ? jsData().players[p.norm] : null, wks = rec && rec.wks ? rec.wks : [];
        var gw = gwOf(p.tm), k = 0, seenPlay = false, first = null, lastPlayed = null;
        for (var gi = gw.length - 1; gi >= 0; gi--) {
          var w0 = gw[gi]; if (w0 >= currentWeek) continue;
          if (wks.indexOf(w0) >= 0) { seenPlay = true; lastPlayed = w0; break; }
          k++; first = w0;
        }
        if (!seenPlay && k > 0) k = Math.min(k, 3);
        for (var w1 = m.from; w1 <= m.to; w1++) if (gw.indexOf(w1) >= 0) { k++; if (first == null) first = w1; }
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
        if (!inWindow(p, wk)) return;
        var base = (p.ptsPPR || 0) / (p.qbWindow ? (p.qbWindow.games || 17) : (p.clayGames || 17));
        if (!(base > 0)) return;
        var g = p.tm + '|' + p.pos, mult = multOf(p);
        if (mult < 1) lost[g] = (p.pos === 'QB' && wnd.SIM_NC_QB_ONESLOT !== false) ? Math.max(lost[g] || 0, base * (1 - mult)) : (lost[g] || 0) + base * (1 - mult);
        else {
          healthyW[g] = (healthyW[g] || 0) + base * depthW(p);
          if (p.pos === 'QB') {
            var cur = nextQb[g];
            var wpBase = (p.ptsPPR || 0) / (p.qbWindow ? (p.qbWindow.games || 17) : 17);
            if (!cur || depthRankOf(p) < depthRankOf(cur) || (depthRankOf(p) === depthRankOf(cur) && wpBase > cur._injBase)) { p._injBase = wpBase; nextQb[g] = p; }
          }
        }
      });
      var usePool = wnd.SIM_POOL !== false;
      var gainT = {}, gainC = {};
      if (usePool) {
        var vac = {};
        var topTgt = {};
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
          if (own > 0 && gained > 0) f = 1 + gained / Math.max(own, POOL_LEVEL_FLOOR);
        } else if (mult === 1 && INJ_SHARE[p.pos] && lost[g] && inWindow(p, wk)) {
          if (p.pos === 'QB') {
            if (nextQb[g] === p) f = 1 + INJ_SHARE.QB * lost[g] / p._injBase;
          } else if (!usePool && healthyW[g] > 0) {
            f = Math.min(2.0, 1 + INJ_SHARE[p.pos] * lost[g] * depthW(p) / healthyW[g]);
          }
        }
        if (f !== 1) (_inj.adj[p.norm] = _inj.adj[p.norm] || {})[wk] = f;
        var mp = map[p.norm];
        if (mp && mp.play != null && mult < 1 && wk >= mp.from && wk <= mp.to) (_inj.play[p.norm] = _inj.play[p.norm] || {})[wk] = mp.play;
      });
    });
    list.forEach(function (p) { var m = map[p.norm]; if (m) _inj.zeros.push({ name: p.name, tm: p.tm, pos: p.pos, from: m.from, to: m.to, mult: m.mult, play: m.play, cond: m.cond, src: m.src, curve: m.curve || null, missed: m.missed, g: m.g || '', note: m.note || '' }); });
    list.forEach(function (p) { var m = map[p.norm]; if (m && m.curve) { _inj.avail[p.norm] = m.curve; var pl = _inj.play[p.norm] = _inj.play[p.norm] || {}; Object.keys(m.curve).forEach(function (cw) { pl[cw] = m.curve[cw]; }); } });
    return _inj;
  }
  function injAvail(p, wk) {
    if (!_inj || !_inj.avail) return 1;
    var a = _inj.avail[p.norm];
    return a && a[wk] != null ? a[wk] : 1;
  }
  var RETURN_RAMP = { '1': { QB: [0.95] }, '2-3': { QB: [0.90], RB: [0.90], WR: [0.90] }, '4+': { QB: [0.85, 0.92, 0.96], RB: [0.85, 0.92, 0.96], WR: [0.85, 0.92, 0.96] } };
  function returnDock(p, wk, schedule) {
    if (p.isDST || !RETURN_RAMP['4+'][p.pos]) return 1;
    var wnd = typeof window !== 'undefined' ? window : null;
    if (!wnd || wnd.SIM_RETURN_RAMP === false || !_inj || !(_inj.week >= 2)) return 1;
    var rec = jsData().players ? jsData().players[p.norm] : null, wks = rec && rec.wks ? rec.wks : null;
    if (!wks || !wks.length) return 1;
    if (seasonPoints(p, PRESETS.half) / 17 < 5) return 1;
    var gw = (schedule && schedule.gameWeeks && schedule.gameWeeks[p.tm]) || [];
    var rdCw = cwOf(p), playedW = function (w) { return w < rdCw ? wks.indexOf(w) >= 0 : injAdj(p, w) > 0; };
    var back = 0, k = 0, gi = gw.length - 1;
    while (gi >= 0 && gw[gi] >= wk) gi--;
    while (gi >= 0 && playedW(gw[gi])) { back++; gi--; }
    while (gi >= 0 && !playedW(gw[gi])) { k++; gi--; }
    if (!k || gi < 0) return 1;
    var ramp = RETURN_RAMP[k === 1 ? '1' : k <= 3 ? '2-3' : '4+'][p.pos];
    return (ramp && back < ramp.length) ? ramp[back] : 1;
  }
  function injAdj(p, wk) {
    if (!_inj) return 1;
    var a = _inj.adj[p.norm];
    return a && a[wk] != null ? a[wk] : 1;
  }
  function injPlay(p, wk) {
    if (!_inj) return 1;
    var a = _inj.play && _inj.play[p.norm];
    return a && a[wk] != null ? a[wk] : Math.min(1, injAdj(p, wk));
  }
  function injuryState() { return _inj; }

  var NEWS_DAYS = 10;
  function newsFlags(p, days) {
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
    if (p.isDST || ['WR', 'TE', 'RB'].indexOf(p.pos) < 0) return false;
    if (!(p.age != null && p.age <= 25) || !(p.exp != null && p.exp <= 3)) return false;
    return snapMult(p, wk) >= 1.05 && routeMult(p, wk) >= 1.03;
  }

  function weeklyProjection(p, wk, sc, schedule) {
    var slot = schedule.byTeam[p.tm] && schedule.byTeam[p.tm][wk];
    if (!slot) return null;
    var weeksList = schedule.gameWeeks[p.tm] || [];
    var gameIdx = weeksList.indexOf(wk) + 1;
    if (p.qbWindow && (gameIdx < p.qbWindow.s || gameIdx > p.qbWindow.e)) return null;
    var mult, mean;
    if (p.isDST) {
      mult = 1;
      mean = dstWeeklyMean(slot.oppImplied, sc);
      return { mean: mean, mult: mult, slot: slot, comps: {} };
    }
    var vegTA = vegasTeamAvg(p, schedule);
    mult = vegasMult(slot.implied, schedule.avgImplied, p.pos, vegTA);
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
    var iA = injAdj(p, wk);
    var factor = mult * dAdj * cbM * sM * rampF * iA;
    var clayPg0 = seasonPoints(p, sc) / perGameDiv;
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
    var qbInh = 0, iAc = iA;
    if (p.pos === 'QB' && iA > 1) { qbInh = (iA - 1) * seasonPoints(p, sc) / (p.qbWindow ? (p.qbWindow.games || 17) : 17); iAc = 1; }
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
    var qbJoin = function (own) {
      if (!qb2On) return own + qbInh;
      if (qb2Cap != null && own > qb2Cap) own = qb2Cap;
      return qbInh > 0 ? Math.max(own, qbInh) : own;
    };
    var mQbf = 1;
    if (p.pos === 'QB' && !(qbInh > 0) && !(iA > 1) && clayPg > 0) { var cf = qbFloor(clayPg, sc); mQbf = cf / clayPg; }
    var mRos = rosTilt(p, wk); mQbf *= mRos;
    mean = qbJoin(clayPg * mQbf) * (factor / iA * iAc) * rookieLevel(p);
    var lvU = liveUsage(p, wk, sc);
    var livePs = (p.pos === 'WR' && lvU && (p.adp == null || p.adp > 60)
                  && !(typeof window !== 'undefined' && window.SIM_LIVE_BLEND_POS === false)) ? 4 : null;
    var fiF = fillinPtsF(p, wk);
    var jsBaseNoU = jsBasePg(p, sc, clayPg, null, null, fiF, winEvid), jsBase0 = lvU ? jsBasePg(p, sc, clayPg, livePs, lvU, fiF, winEvid) : jsBaseNoU, mRook = rookieLevel(p);
    var jsPg = jsBase0 * mRook;
    var jsPgPre = jsPg;
    if (p.pos === 'QB' && !(qbInh > 0) && !(iA > 1)) { jsPg = qbFloor(jsPg, sc); mQbf = jsPgPre > 0 ? jsPg / jsPgPre : 1; }
    if (mRos !== 1) { jsPg *= mRos; mQbf *= mRos; }
    var jsPgRook = jsPg;
    var rbU = rbUsagePg(p, wk);
    if (rbU) {
      var uScale = rbU.halfPg > 0 && clayPg > 0 ? clayPg / rbU.halfPg : 1;
      jsPg = (1 - RB_USAGE.w) * jsPg + RB_USAGE.w * rbU.half * uScale;
    }
    var oppM = jsOppMult(slot.opp, p.pos, dAdj);
    var jsChain = mult * oppM * cbM * sM * rampF * iAc;
    var jsPgOwn = jsPg;
    jsPg = qbJoin(jsPg);
    var luckFull = (qb2Cap != null && !(qbInh > 0)) ? 0 : tdLuckAdj(p, sc) * Math.min(1, iA);
    var luckAdj = luckFull * (lvU ? 1 - lvU.lam : 1);
    var jsMean = Math.max(0, jsPg * jsChain + luckAdj);
    var jsNoUse = lvU ? Math.max(0, (jsBaseNoU * mRook + qbInh) * jsChain + luckFull) : null;
    var jsRawPk = jsMean;
    var pkHalf = seasonPoints(p, PRESETS.half) / perGameDiv, peckR = peckDock(p, wk, sc, schedule, jsRawPk, (pkHalf > 0 && clayPg0 > 0) ? jsRawPk * pkHalf / clayPg0 : jsRawPk);
    var mPeck = peckR.m, mVol = volumeMult(p, slot), mDock = mPeck * mVol;
    if (mDock !== 1) { mean *= mDock; jsMean = jsRawPk * mDock; if (jsNoUse != null) jsNoUse *= mDock; }
    var lcCorr = null;
    try { lcCorr = learnedShadowCorr(p, wk, sc, slot, { clayPg: clayPg0, mult: mult, rbU: rbU, iA: iA, jsMean: jsRawPk }); } catch (_) { lcCorr = null; }
    var ncSrc = 'clay-fallback', ncPrior = clayPg0;
    var halfPg = seasonPoints(p, PRESETS.half) / perGameDiv, scale = (halfPg > 0 && clayPg0 > 0) ? clayPg0 / halfPg : 1;
    var jsRec = jsData().players ? jsData().players[p.norm] : null;
    var h3 = (p.histPpg != null && p.histGames >= 8) ? p.histPpg * scale : null;
    var l8 = (jsRec && jsRec.l8 != null && jsRec.l8g >= 4) ? jsRec.l8 * scale : null;
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
    var hlthSkipOpp = hTag !== '' && hPrev && hPrev[2] >= 3;
    if (h3 != null && l8 != null) { ncPrior = 0.5 * h3 + 0.5 * l8; ncSrc = 'hist+l8' + hTag; }
    else if (l8 != null) { ncPrior = l8; ncSrc = 'l8' + hTag; }
    else if (h3 != null) { ncPrior = h3; ncSrc = 'hist' + hTag; }
    var ncRawHist = ncPrior;
    if (ncSrc !== 'clay-fallback') {
      var sa = shadowAgeAdjust(p, ncPrior / scale);
      ncPrior = sa.v * scale; ncSrc += sa.tag;
      var opd = typeof window !== 'undefined' ? window.SIM_OPP_PRIOR_2026 : null;
      var opr = opd && opd.players ? opd.players[p.norm] : null, occ = opd && opd.cal ? opd.cal[p.pos] : null;
      if (opr && occ && occ.length === 3 && ncPrior / scale >= 4 && !hlthSkipOpp && !(typeof window !== 'undefined' && window.SIM_SHADOW_OPP === false)) {
        var opHist = (h3 != null && !(typeof window !== 'undefined' && window.SIM_NC_OPPHIST === false)) ? shadowAgeAdjust(p, h3 / scale).v : ncPrior / scale;
        var hbo = occ[0] + occ[1] * opHist + occ[2] * opr.half;
        if (hbo > 0) { ncPrior = hbo * scale; ncSrc += '+opp'; }
      }
    }
    var ncV2 = !(typeof window !== 'undefined' && window.SIM_NC_V2 === false) && p.adp != null && p.adp <= NC_SHADOW.adpGate, ncPm = NC_SHADOW.posMean[p.pos];
    if (ncV2 && ncSrc === 'clay-fallback' && ncPm != null) {
      var rc = NC_SHADOW.rookie[p.pos];
      if (p.isRookie && rc) {
        var pk = p.draftPick != null ? p.draftPick : 262;
        ncPrior = Math.max(0.5, rc[0] + rc[1] * Math.log(pk)) * scale; ncSrc = p.draftPick != null ? 'rookie-pick' : 'rookie-udfa';
        var rs = NC_SHADOW.rookieStr[p.pos];
        if (rs && !(typeof window !== 'undefined' && window.SIM_NC_DEPTH === false)) {
          var ds = effectiveString(p, wk), dsk = ds == null ? 3 : Math.min(3, ds);
          ncPrior = Math.max(0.5, rs[0] + rs[1] * Math.log(pk) + (dsk === 2 ? rs[2] : 0) + (dsk >= 3 ? rs[3] : 0)) * scale;
          ncSrc += '+str' + (ds == null ? 'x' : dsk);
        }
      } else { ncPrior = ncPm * scale; ncSrc = 'pos-mean'; }
    }
    var ncAc = NC_SHADOW.adpCurve[p.pos];
    if (ncV2 && ncAc && !p.isRookie && /^(hist|l8)/.test(ncSrc) && p.adp <= NC_SHADOW.adpMax && !ncNoAdp(p.pos) && !(typeof window !== 'undefined' && window.SIM_NC_ADP === false)) {
      var mkt = Math.max(0.5, ncAc[0] + ncAc[1] * Math.log(p.adp)), wA = p.exp === 1 ? NC_SHADOW.adpWYr2 : NC_SHADOW.adpW;
      ncPrior = ((1 - wA) * (ncPrior / scale) + wA * mkt) * scale; ncSrc += '+adp';
    }
    var ncVd = NC_SHADOW.vetDock[p.pos];
    if (ncVd && !p.isRookie && ncSrc !== 'clay-fallback' && !(typeof window !== 'undefined' && window.SIM_NC_VETDOCK === false)) {
      var vds = effectiveString(p, wk);
      if (vds != null && vds >= 2) { var vdk = Math.min(3, vds); if (ncVd[vdk] != null) { ncPrior *= ncVd[vdk]; ncSrc += '+dock' + vdk; } }
    }
    if (ncV2 && p.exp === 1 && /^(hist|l8)/.test(ncSrc) && !(typeof window !== 'undefined' && window.SIM_NC_YR2 === false)) {
      var spr = typeof window !== 'undefined' && window.SIM_SNAPS_PRIOR ? window.SIM_SNAPS_PRIOR[p.norm] : null;
      if (typeof spr === 'number' && spr < NC_SHADOW.yr2LowSnap.max) { ncPrior *= NC_SHADOW.yr2LowSnap.mult; ncSrc += '+yr2lo'; }
    }
    if (ncV2 && p.pos === 'WR' && !p.isRookie && /^(hist|l8)/.test(ncSrc) && !(typeof window !== 'undefined' && window.SIM_NC_GRADE === false)) {
      var gpr = typeof window !== 'undefined' && window.SIM_PFF_ROUTE_PRIOR ? window.SIM_PFF_ROUTE_PRIOR[p.norm] : null, wg = NC_SHADOW.wrGrade;
      if (typeof gpr === 'number' && gpr - (wg.c0 + wg.c1 * (ncPrior / scale)) > wg.cut) { ncPrior *= wg.mult; ncSrc += '+grade'; }
    }
    if (p.pos === 'QB' && ncSrc !== 'clay-fallback' && !(iA > 1) && !(typeof window !== 'undefined' && window.SIM_NC_QB2 === false)) {
      var qd = typeof window !== 'undefined' ? window.SIM_DEPTH_2026 : null, qds = effectiveString(p, wk);
      var charted = qd && qd.teams && qd.teams[p.tm] && qd.teams[p.tm].QB && qd.teams[p.tm].QB.length;
      if (charted && (qds == null || qds >= 2)) { var qbCap = NC_SHADOW.qbBackupPpg * scale; if (ncPrior > qbCap) { ncPrior = qbCap; ncSrc += '+qb' + (qds == null ? 'x' : qds); } }
    }
    if (ncV2 && ncSrc !== 'clay-fallback' && ncPm != null) { ncPrior = (ncPm + NC_SHADOW.k * (ncPrior / scale - ncPm)) * scale; ncSrc += '+shr'; }
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
        if (/\+qb/.test(ncSrc)) ncPrior = Math.min(ncPrior, NC_SHADOW.qbBackupPpg * scale);
      }
    }
    var ncRos = !!(_inj && _inj.week >= 1 && wk > cwOf(p)) && !(typeof window !== 'undefined' && window.SIM_NC_ROS === false);
    var ncSM = sM;
    var ncPrune = !(typeof window !== 'undefined' && window.SIM_NC_PRUNE === false);
    if (ncPrune && p.pos === 'WR') ncSM = 1;
    if (ncRos && p.pos === 'RB' && NC_SHADOW.next.rbSnapCarry) {
      var rsSn = (typeof window !== 'undefined' && window.SIM_SNAPS_2026) ? window.SIM_SNAPS_2026[p.name] : null;
      var rsLast = rsSn && rsSn.w ? Math.max.apply(null, Object.keys(rsSn.w).map(Number).filter(function (w) { return w < wk; }).concat([0])) : 0;
      if (rsLast >= cwOf(p) - 3 && rsLast > 0) ncSM = snapMult(p, rsLast + 1);
    }
    var ncBlowOn = !(typeof window !== 'undefined' && window.SIM_NC_BLOW === false);
    var ncBlowLast = function (lw) {
      var c = lw > 0 ? ctxOf(p, lw) : null;
      return !!(c && c.pl > 0 && c.gp >= CTX_MIN_GARBAGE && c.gp / c.pl >= NC_SHADOW.next.blowMinShare);
    };
    if (ncBlowOn && p.pos === 'RB' && ncSM < 1 && p.adp != null && p.adp <= NC_SHADOW.next.blowNoDockAdp) {
      var blSn = (typeof window !== 'undefined' && window.SIM_SNAPS_2026) ? window.SIM_SNAPS_2026[p.name] : null;
      var blLast = blSn && blSn.w ? Math.max.apply(null, Object.keys(blSn.w).map(Number).filter(function (w) { return w < wk; }).concat([0])) : 0;
      if (ncBlowLast(blLast)) { ncSM = 1; ncSrc += '+blow'; }
    }
    if (p.pos === 'RB' && p.adp != null && p.adp <= NC_SHADOW.next.snapNoDockAdp && ncSM < 1 && (typeof window !== 'undefined' && window.SIM_NC_ELITE_TREND === true)) { ncSM = 1; ncSrc += '+elitetrend'; }
    var teDockK = (p.pos === 'TE' && NC_SHADOW.next.teDockK != null && !(typeof window !== 'undefined' && window.SIM_NC_TE_DOCKS === false)) ? NC_SHADOW.next.teDockK : 1;
    if (teDockK !== 1 && Math.abs(ncSM - 1) > 1e-9) { ncSM = Math.pow(ncSM, teDockK); ncSrc += '+tedock'; }
    var ncChain = sM ? jsChain / sM * ncSM : jsChain, ncChainNoIA = mult * oppM * cbM * ncSM * rampF;
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
        var rsCv = rsS.rbCurve && !(typeof window !== 'undefined' && window.SIM_NC_RBCURVE === false) ? rsS.rbCurve : null;
        var rsRbK = p.pos !== 'RB' ? 1 : rsCv ? 1 + rsCv.k * Math.exp(-0.5 * Math.pow((p.adp - rsCv.c) / rsCv.w, 2)) : (rsMid ? rsS.rbMidP : 1);
        if (ncP != null && p.pos === 'RB') { if (rsRbK > 1.005) { ncP *= rsRbK; ncSrc += '+rsP'; } }
        else if (ncP != null && p.pos === 'WR' && rsMid) { ncP *= rsS.wrMidP; ncSrc += '+rsP'; }
        else if (ncP != null && p.pos === 'QB' && p.exp === 1) { ncP *= rsS.qbYr2P; ncSrc += '+rsP'; }
        var rsRk = p.isRookie && rsS.rookieP ? rsS.rookieP[p.pos] : null;
        if (ncP != null && rsRk) {
          var rsHad = p.pos === 'RB' ? rsRbK : 1;
          if (rsRk > rsHad) { ncP *= rsRk / rsHad; ncSrc += '+rsRk'; }
        }
        if (p.pos === 'WR' && p.adp > rsS.late[0] && p.adp <= rsS.late[1] && ncUse && ncUse.lam > rsS.wrLateLam) { ncUse.lam = rsS.wrLateLam; ncSrc += '+rsLam'; }
        if (ncP != null && p.pos === 'WR' && p.adp > rsS.late[0] && p.adp <= rsS.late[1] && ncPrior > 0) {
          var rsEv = (jsBasePg(p, sc, ncPrior, ncP, ncUse) * (ncP + rsRec.g) - ncP * ncPrior) / rsRec.g;
          if (rsEv < ncPrior) { ncP *= rsS.wrLateColdP; ncSrc += '+rsCold'; }
        }
      }
    }
    var ncFiF = ncFillinPtsF(p, wk); if (ncFiF < 0.9999) ncSrc += '+fillin';
    var ncBaseW = jsBasePg(p, sc, ncPrior, ncP, ncUse, ncFiF), ncVk = NC_SHADOW.vacatedK[p.pos];
    if (rsOn && p.pos === 'TE' && p.adp > rsS.teBand[0] && p.adp <= rsS.teBand[1]) { ncBaseW *= rsS.teLevel; ncSrc += '+rsTE'; }
    if (ncRos && p.pos === 'TE' && !(typeof window !== 'undefined' && window.SIM_NC_TE_TDFLOOR === false)) {
      var tfRec = jsData().players ? jsData().players[p.norm] : null, tfG = tfRec && tfRec.g ? tfRec.g : 0, tfPg = tfRec && tfRec.pg ? tfRec.pg : null;
      if (tfG >= 3 && tfPg) {
        var tfSn = (typeof window !== 'undefined' && window.SIM_SNAPS_2026) ? window.SIM_SNAPS_2026[p.name] : null, tfSnapW = tfSn && tfSn.w ? Object.keys(tfSn.w).filter(function (w) { return +w < wk && typeof tfSn.w[w] === 'number'; }).map(function (w) { return tfSn.w[w]; }) : [];
        var tfSnap = tfSnapW.length ? tfSnapW.reduce(function (a, b) { return a + b; }, 0) / tfSnapW.length : 0, tfTgt = tfPg.tgt || 0;
        if (tfSnap >= 70 || tfTgt >= 4.5) {
          var tfTd = 6 * ((tfPg.rctd || 0) + (tfPg.rtd || 0)), tfLift = 1 + 0.08 * Math.max(0, 1.8 - tfTd);
          if (tfLift > 1.004) { ncBaseW *= tfLift; ncSrc += '+tdfloor'; }
        }
      }
    }
    if (rsOn && p.pos === 'RB') {
      var rsZ = rosTiltZ(), rsPz = rsZ && rsZ.plays ? rsZ.plays[p.tm] : null;
      if (typeof rsPz === 'number' && Math.abs(rsPz) > 0.05) { ncBaseW *= 1 - rsS.rbPlays * rsPz; ncSrc += '+rsVol'; }
      if (p.adp <= rsS.rbBackupAdp) { var rsDs = effectiveString(p, wk); if (rsDs != null && rsDs >= 2) { ncBaseW *= rsS.rbBackup; ncSrc += '+rsBk'; } }
    }
    var ncLuckScale = 1;
    if (!(typeof window !== 'undefined' && window.SIM_NC_LUCKFIX === false)) {
      var lkRec = jsData().players ? jsData().players[p.norm] : null, lkG = lkRec && lkRec.g ? lkRec.g : 0;
      if (lkG > 0) {
        var lkLam = (ncUse && ncUse.lam > 0 && ncUse.xfpPg != null) ? ncUse.lam : 0, lkP = ncP != null ? ncP : JS_PRIOR_STRENGTH;
        var lkLive = lkG / (JS_PRIOR_STRENGTH + lkG), lkShadow = (1 - lkLam) * lkG / (lkP + lkG);
        ncLuckScale = lkLive > 0 ? Math.max(0, Math.min(1.5, lkShadow / lkLive)) : 1;
      }
    }
    if (ncVd && !p.isRookie && ncSrc !== 'clay-fallback' && depthString(p) == null && !(typeof window !== 'undefined' && window.SIM_NC_NOCHART === false)) {
      var ncRec = jsData().players ? jsData().players[p.norm] : null, ncGp = ncRec && ncRec.wks ? ncRec.wks.filter(function (w) { return w < wk; }).length : 0;
      if (ncGp < NC_SHADOW.noChart.games) { ncBaseW *= NC_SHADOW.noChart.mult; ncSrc += '+nochart'; }
    }
    if (ncSrc !== 'clay-fallback' && !(typeof window !== 'undefined' && window.SIM_NC_NEXT === false)) {
      var nx = NC_SHADOW.next, nxRec = jsData().players ? jsData().players[p.norm] : null;
      var nxG = nxRec && nxRec.wks ? nxRec.wks.filter(function (w) { return w < wk; }).length : 0;
      if (_inj && _inj.week >= 1 && wk > cwOf(p)) {
        var nxGw = (schedule.gameWeeks && schedule.gameWeeks[p.tm]) || [], nxCw = cwOf(p);
        nxG += nxGw.filter(function (w) { return w >= nxCw && w < wk && !(nxRec && nxRec.wks && nxRec.wks.indexOf(w) >= 0); }).length;
      }
      var nxEarly = nxG >= nx.early[0] && nxG <= nx.early[1];
      if (p.pos === 'QB') {
        var nxS = injSig(), nxPrev = nxS && nxS.prevTm ? nxS.prevTm[p.norm] : null;
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
            var ci = (xr.pos === 'QB' || q.pos === 'QB') ? 3 : 4;
            nxWks.forEach(function (k) { if (xr.w[k]) nxTeam += xr.w[k][ci] || 0; });
          });
          if (nxTeam >= 20 && nxMine / nxTeam < nx.rbCarry[0]) { ncBaseW *= nx.rbCarry[1]; ncSrc += '+lowcar'; }
        }
      }
      if (p.pos === 'TE' && ncRos && nx.teTilt) {
        var nxZ = rosTiltZ(), nxz = nxZ && nxZ.team ? nxZ.team[p.tm] : null;
        if (typeof nxz === 'number' && Math.abs(nxz) > 0.05) { ncBaseW *= 1 - nx.teTilt * Math.min(1, (wk - cwOf(p)) / 2) * nxz; ncSrc += '+rtilt'; }
      }
      if ((p.pos === 'WR' || p.pos === 'TE') && nxG >= 1) {
        var nxSn = (typeof window !== 'undefined' && window.SIM_SNAPS_2026) ? window.SIM_SNAPS_2026[p.name] : null, nxT = nx.snapLvl[p.pos];
        if (nxSn && nxSn.w && nxT) {
          var nxPast = Object.keys(nxSn.w).map(Number).filter(function (w) { return w < wk && typeof nxSn.w[w] === 'number'; }).sort(function (a, b) { return b - a; });
          if (nxPast.length) {
            var nxLv = ncBaseW * ncChainNoIA * (seasonPoints(p, PRESETS.half) / Math.max(1e-9, seasonPoints(p, sc))), nxB = 0;
            while (nxB < nxT.edges.length && nxLv >= nxT.edges[nxB]) nxB++;
            var nxFar = !!(_inj && _inj.week >= 1 && wk > cwOf(p));
            var nxE = nxFar ? (ncRos ? (nx.snapEFar[p.pos] || 0) : 0.15) : nx.snapE;
            var nxC = ncBlowOn ? ctxOf(p, nxPast[0]) : null, nxShare = nxC ? ctxShare(nxSn.w[nxPast[0]], nxC, false).pct : nxSn.w[nxPast[0]];
            var nxM = Math.min(nx.snapClamp[1], Math.max(nx.snapClamp[0], 1 + nxE * (nxShare - nxT.ref[nxB]) / 100));
            if (nxM < 1 && p.adp != null && p.adp <= nx.snapNoDockAdp && !(typeof window !== 'undefined' && window.SIM_NC_ELITE === false)) nxM = 1;
            if (nxM < 1 && ncBlowOn && p.adp != null && p.adp <= nx.blowNoDockAdp && ncBlowLast(nxPast[0])) { nxM = 1; ncSrc += '+blow'; }
            if (teDockK !== 1 && !nxFar && Math.abs(nxM - 1) > 0.004) { nxM = Math.pow(nxM, teDockK); if (!/\+tedock/.test(ncSrc)) ncSrc += '+tedock'; }
            if (Math.abs(nxM - 1) > 0.004) { ncBaseW *= nxM; ncSrc += '+snaplv'; }
          }
        }
      }
    }
    var ncOut = shadowOut(p, wk);
    var ncMean, ncVfadeD = 0, ncVfadeSeen = 0, ncAtVac = null, ncBalloc = null;
    if (ncVk != null && !(typeof window !== 'undefined' && window.SIM_NC_EXACT === false)) {
      var ncFull = Math.max(0, ncBaseW * ncChainNoIA + tdLuckAdj(p, sc) * ncLuckScale), ncCap = ncOut ? 0 : Math.min(1, iA), ncOwn = ncFull * ncCap;
      var ck = ncCacheKey(wk, sc), C = _ncCache[ck] || (_ncCache[ck] = {});
      var ncC = p.comps || {}, ncRp = (ncC.rec || 0) * 1 + (ncC.rcy || 0) * 0.1 + (ncC.rctd || 0) * 6, ncCp = (ncC.ry || 0) * 0.1 + (ncC.rtd || 0) * 6;
      var ncRf = (ncRp + ncCp) > 0 ? ncRp / (ncRp + ncCp) : (p.pos === 'RB' ? 0.35 : 1);
      C[p.norm] = { full: ncFull, own: ncOwn, cap: ncCap, str: effectiveString(p, wk), pos: p.pos, rf: ncRf };
      ncMean = ncOwn;
      if (!_ncPass && _poolByNorm && ncCap === 1) {
        var grp = [], keys = Object.keys(_poolByNorm), skillP = p.pos !== 'QB';
        for (var gi2 = 0; gi2 < keys.length; gi2++) { var q = _poolByNorm[keys[gi2]]; if (q !== p && q.tm === p.tm && !q.isDST && (skillP ? !!POOL[q.pos] : q.pos === 'QB')) grp.push(q); }
        _ncPass = true;
        try { for (var gj = 0; gj < grp.length; gj++) if (!C[grp[gj].norm]) weeklyProjection(grp[gj], wk, sc, schedule); } finally { _ncPass = false; }
        var all = grp.concat([p]).filter(function (q) { return !!C[q.norm]; }), meC = C[p.norm], gained = 0, gainedU = 0, vfSeen = 0, bestQb = null, bestQbC = null, whCap = false;
        if (!skillP) {
          var lost = 0, oneSlot = !(typeof window !== 'undefined' && window.SIM_NC_QB_ONESLOT === false);
          all.forEach(function (q) { var c = C[q.norm]; if (c.cap < 1) { var l0 = c.full * (1 - c.cap); lost = oneSlot ? Math.max(lost, l0) : lost + l0; } });
          if (lost > 0) {
            all.filter(function (q) { return C[q.norm].cap === 1; }).forEach(function (q) { var c = C[q.norm], s = c.str == null ? 99 : c.str; if (!bestQb || s < (bestQbC.str == null ? 99 : bestQbC.str) || (s === (bestQbC.str == null ? 99 : bestQbC.str) && c.own > bestQbC.own)) { bestQb = q; bestQbC = c; } });
            if (bestQb === p) gained = INJ_SHARE.QB * lost;
          }
        } else {
          var recLvl = function (q) { var c = C[q.norm]; return c.full * c.rf; }, topRec = 0;
          all.forEach(function (q) { if (recLvl(q) > topRec) topRec = recLvl(q); });
          var healthy = all.filter(function (q) { return C[q.norm].cap === 1; }), strOf = function (q) { var s = C[q.norm].str; return s == null ? 99 : s; };
          all.forEach(function (Z) {
            var cz = C[Z.norm]; if (cz.cap >= 1) return;
            var lostRec = cz.full * cz.rf * (1 - cz.cap), lostRush = cz.full * (1 - cz.rf) * (1 - cz.cap);
            var zSec = !(recLvl(Z) >= topRec - 1e-9), rule = POOL[Z.pos][zSec ? 'sec' : 'lead'];
            var multiAbs = !(typeof window !== 'undefined' && window.SIM_NC_MULTI_ABS === false);
            var same = (multiAbs ? all.filter(function (q) { if (q === Z || q.pos !== Z.pos) return false; if (C[q.norm].cap === 1) return true; if (C[q.norm].cap !== 0) return false; var jr = jsData().players && jsData().players[q.norm]; return !!(jr && jr.wks && jr.wks.some(function (w0) { return w0 >= wk - 3 && w0 < wk; })); }) : healthy.filter(function (q) { return q.pos === Z.pos; }))
              .sort(function (a, b) { var d = strOf(a) - strOf(b); return d !== 0 ? d : C[b.norm].full - C[a.norm].full; });
            var i = same.indexOf(p);
            var whOn = !(typeof window !== 'undefined' && window.SIM_WORKHORSE === false), carSh = rule.carSame[i] || 0;
            if (whOn && Z.pos === 'RB' && p.pos === 'RB' && i === 0) {
              var roomRush = 0; all.forEach(function (q) { if (q.pos === 'RB') { var cq = C[q.norm]; roomRush += cq.full * (1 - cq.rf); } });
              if (roomRush > 0 && cz.full * (1 - cz.rf) / roomRush >= WORKHORSE.share) { carSh = WORKHORSE.car; whCap = true; }
            }
            var gZ = 0;
            if (i >= 0) gZ += poolTgtShare(rule, Z.pos, zSec, i, p) * lostRec * POOL_EFF_T + carSh * lostRush * POOL_EFF_C;
            if (rule.tgtOther > 0 && p.pos !== Z.pos && p.pos !== 'RB') {
              var others = healthy.filter(function (q) { return q.pos !== Z.pos && q.pos !== 'RB'; }), tot = 0;
              others.forEach(function (q) { tot += C[q.norm].own * C[q.norm].rf; });
              if (tot > 0) gZ += rule.tgtOther * lostRec * (meC.own * meC.rf) / tot * POOL_EFF_T;
            }
            var fZ = vacFadeF(p, Z, wk);
            if (fZ.seen > vfSeen) vfSeen = fZ.seen;
            gainedU += gZ; gained += gZ * fZ.f;
          });
        }
        var qbMax = !skillP && !(typeof window !== 'undefined' && window.SIM_NC_QBMAX === false);
        var bAlloc = (skillP && typeof window !== 'undefined' && window.SIM_NC_BUDGET_ALLOC === true && _inj && !(wk > cwOf(p))) ? budgetAllocRatio(p, wk, schedule) : null;
        if (bAlloc) { ncBalloc = Math.min(BUDGET_ALLOC.clip[1], Math.max(BUDGET_ALLOC.clip[0], Math.pow(bAlloc.ratio, BUDGET_ALLOC.e))); ncMean = ncOwn * ncBalloc; ncSrc += '+balloc'; gained = 0; gainedU = 0; }
        else if (gained > 0) { ncMean = skillP ? ncOwn + Math.min(whCap ? Math.max(ncOwn, WORKHORSE.cap) : ncOwn, ncVk * gained) : (qbMax ? Math.max(ncOwn, gained) : ncOwn + gained); ncSrc += whCap ? '+vacx+wh' : '+vacx'; }
        if (skillP && gainedU > gained + 1e-9) {
          var ncMeanU = ncOwn + Math.min(whCap ? Math.max(ncOwn, WORKHORSE.cap) : ncOwn, ncVk * gainedU);
          ncVfadeD = Math.max(0, ncMeanU - Math.max(ncMean, ncOwn)); ncVfadeSeen = vfSeen;
          if (ncVfadeD > 0) ncSrc += '+vfade' + vfSeen;
        }
      }
      ncMean = Math.max(0, ncMean);
    } else {
      if (iA > 1 && ncVk != null && ncVk !== 1 && !(typeof window !== 'undefined' && window.SIM_NC_VAC === false)) { ncChain = ncChain * Math.pow(iA, ncVk - 1); ncSrc += '+vac'; }
      ncMean = Math.max(0, ncBaseW * ncChain + luckFull * ncLuckScale);
    }
    ncAtVac = ncMean;
    if (ncMean != null && ncMean > 0) { var nmuM = nextManUpMult(p, wk, schedule); if (nmuM !== 1) { ncMean *= nmuM; ncSrc += '+nmu' + (nmuM > 1 ? '+' : '-'); } }
    if (ncMean != null && ncMean > 0) { var pbM = promotedMult(p, wk); if (pbM !== 1) { ncMean *= pbM; ncSrc += '+promo'; } }
    if (ncMean != null && ncMean > 0) { var tvM = teamVacMult(p, wk, schedule); if (tvM !== 1) { ncMean *= tvM; ncSrc += '+tvac'; } }
    if (ncMean != null && ncMean > 0 && p.pos === 'WR') { var ttM = topOutTrimMult(p, wk, schedule); if (ttM !== 1) { ncMean *= ttM; ncSrc += '+toptrim'; } }
    if (ncMean != null && ncMean > 0 && p.pos === 'QB') { var qtM = qbTeOutMult(p, wk, schedule); if (qtM !== 1) { ncMean *= qtM; ncSrc += '+qbte'; } }
    if (p.pos === 'WR' && ncMean > 0 && !(typeof window !== 'undefined' && window.SIM_NC_QBOUT === false) && teamPrimaryQbOut(p.tm, wk)) {
      var qod = NC_SHADOW.qbOutWrDock, qStar = p.adp != null && p.adp <= qod.starAdp;
      ncMean *= (1 - (qStar ? qod.star : qod.other)); ncSrc += '+qbout' + (qStar ? 'S' : '');
    }
    if (p.pos === 'QB' && ncMean > 0 && !(typeof window !== 'undefined' && window.SIM_NC_TOTAL === false)) {
      var gtz = gameTotalZ(schedule, wk, p.tm);
      var totElite = p.adp != null && p.adp <= NC_SHADOW.next.snapNoDockAdp && !(typeof window !== 'undefined' && window.SIM_NC_TOTAL_ELITE === false);
      if (gtz != null && !totElite) { ncMean *= Math.exp(NC_SHADOW.qbTotalC * gtz); ncSrc += '+tot'; }
    }
    if (ncMean != null && mVol !== 1 && !(typeof window !== 'undefined' && window.SIM_NC_VOL === false)) { ncMean = Math.max(0, ncMean * mVol); ncSrc += '+vol'; }
    var ncLater = !!(_inj && _inj.week >= 1 && wk > cwOf(p));
    var ncPeckM = 1, ncPeckRk = null, ncQbfM = 1;
    if ((p.pos === 'WR' || p.pos === 'RB') && ncMean > 0 && !ncLater && typeof ncOwn === 'number' && !_ncPass && !_qbfPass && !(typeof window !== 'undefined' && window.SIM_NC_PECK === false)) {
      var pkC = _ncCache[ncCacheKey(wk, sc)], pkSc = scale > 0 ? scale : 1;
      if (pkC && _poolByNorm) {
        var pkRank = 1, pkSeen = [];
        Object.keys(_poolByNorm).forEach(function (k) {
          var q = _poolByNorm[k]; if (!q || q === p || q.pos !== p.pos || q.tm !== p.tm || pkSeen.indexOf(q) >= 0) return; pkSeen.push(q);
          var c = pkC[q.norm]; if (c && c.own / pkSc >= 0.5 && c.own > ncOwn) pkRank++;
        });
        var pkFrom = p.pos === 'WR' ? 3 : 2, pkMult = p.pos === 'WR' ? 0.92 : 0.94;
        ncPeckRk = pkRank;
        if (pkRank >= pkFrom) {
          var pkFade = Math.max(0, Math.min(1, ncOwn / pkSc - 4));
          if (pkFade > 0) { ncPeckM = 1 - (1 - pkMult) * pkFade; ncMean *= ncPeckM; ncSrc += '+peck' + pkRank; }
        }
      }
    }
    if (p.pos === 'QB' && ncLater && ncMean > 0 && Math.abs(iA - 1) < 1e-9 && !/\+vacx/.test(ncSrc) && !/\+qb[0-9x]/.test(ncSrc) && !(effectiveString(p, wk) >= 2) && !ncOut && !_ncPass && !_qbfPass && !(typeof window !== 'undefined' && window.SIM_NC_QBFLOOR === false)) {
      var qfSc = scale > 0 ? scale : 1, qfMu = (ncMean / qfSc >= 5) ? qbShadowMu(wk, sc, schedule) : null;
      if (qfMu != null && ncMean < qfMu) { var qf0 = ncMean; ncMean = qfMu + 0.70 * (ncMean - qfMu); ncQbfM = qf0 > 0 ? ncMean / qf0 : 1; ncSrc += '+qbfl'; }
    }
    if (ncMean != null && ncMean > 0 && !ncOut) { var dbM = newTeamDebutMult(p, wk, schedule); if (dbM !== 1) { ncMean *= dbM; ncSrc += '+debut'; } }
    if (p.pos === 'QB' && ncMean != null && ncMean > 0 && !ncOut && !(effectiveString(p, wk) >= 2) && !/\+qb[0-9x]/.test(ncSrc)
        && !(typeof window !== 'undefined' && window.SIM_QB_OPP_LEG === false)) {
      var qbLeg = qbOppLeg(p, wk, sc, schedule, slot);
      if (qbLeg != null && qbLeg > 0) { var qoW = NC_SHADOW.qbOppLeg.w; ncMean = qoW * qbLeg + (1 - qoW) * ncMean; ncSrc += '+qbopp'; }
    }
    if (ncOut) { ncMean = 0; ncSrc += '+out:' + ncOut; }
    var bbW = 0, jsPre = jsMean, bbRatio = 1;
    var bbCfg = typeof window !== 'undefined' ? window.SIM_BASE_BLEND : undefined;
    if (bbCfg !== false && !p.isDST && !(inWin && winEvid) && jsMean != null && ncMean != null && ncMean > 0 && !ncOut && iA > 0) {
      var bbwRaw = (bbCfg && bbCfg.w != null) ? bbCfg.w : BASE_BLEND.w, bbs = (bbCfg && bbCfg.scope) ? bbCfg.scope : BASE_BLEND.scope;
      var bbLater = _inj && _inj.week >= 1 && wk > cwOf(p);
      if (!bbLater && BASE_BLEND.wNow && !(bbCfg && bbCfg.w != null) && !(typeof window !== 'undefined' && window.SIM_WEEKLY_NO_BLEND === false)) bbwRaw = BASE_BLEND.wNow;
      var bbw = typeof bbwRaw === 'number' ? bbwRaw : (bbwRaw && bbwRaw[p.pos] != null ? bbwRaw[p.pos] : 0.7);
      if (bbw > 0 && (bbs === 'all' || bbLater)) { bbW = bbw; jsMean = bbw * ncMean + (1 - bbw) * jsMean; bbRatio = jsPre > 0 ? jsMean / jsPre : 1; }
    }
    else if (wk >= 2 && /^Questionable/i.test(String(p.injFlag || '')) && !(typeof window !== 'undefined' && window.SIM_NC_QRET === false)) {
      var qrRec = jsData().players ? jsData().players[p.norm] : null, playedLast = !!(qrRec && qrRec.wks && qrRec.wks.indexOf(wk - 1) >= 0);
      if (!playedLast) { ncMean *= NC_SHADOW.qRet.mult; ncSrc += '+qret'; }
    }
    var compsWk = {};
    factor = factor * mDock;
    Object.keys(p.comps).forEach(function (k) {
      if (p.comps[k]) compsWk[k] = +(p.comps[k] / perGameDiv * factor).toFixed(2);
    });
    compsWk.rrtd = +(((p.comps.rtd || 0) + (p.comps.rctd || 0)) / perGameDiv * factor).toFixed(3);
    var cwScale = 1, COMP_LEVEL_POS = { RB: 1, WR: 1, TE: 1 };
    if (COMP_LEVEL_POS[p.pos] && jsMean > 0 && !(typeof window !== 'undefined' && window.SIM_COMP_LEVEL === false)) {
      var cwSum = (compsWk.py || 0) * (sc.pass_yd || 0) + (compsWk.ptd || 0) * (sc.pass_td || 0) + (compsWk.ry || 0) * (sc.rush_yd || 0) + (compsWk.rtd || 0) * (sc.rush_td || 0) + (compsWk.rec || 0) * ((sc.rec || 0) + (p.pos === 'TE' ? (sc.bonus_rec_te || 0) : 0)) + (compsWk.rcy || 0) * (sc.rec_yd || 0) + (compsWk.rctd || 0) * (sc.rec_td || 0);
      if (cwSum > 0.5) { cwScale = Math.min(2.5, Math.max(0.4, jsMean / cwSum)); if (Math.abs(cwScale - 1) > 0.002) Object.keys(compsWk).forEach(function (k) { compsWk[k] = +(compsWk[k] * cwScale).toFixed(k === 'rrtd' ? 3 : 2); }); else cwScale = 1; }
    }
    var compsU = null, cuE = compUsage(p, wk);
    if (cuE) {
      compsU = {}; Object.keys(compsWk).forEach(function (k) { compsU[k] = compsWk[k]; });
      ['ry', 'rec', 'rcy'].forEach(function (k) {
        if (p.pos === 'QB' && k !== 'ry') return;
        var prior = (p.comps[k] || 0) / perGameDiv * cwScale, act = cuE.a[k]; if (typeof act !== 'number') return;
        var lm = COMP_USAGE.lam[k]; if (typeof lm === 'object') lm = lm[p.pos] != null ? lm[p.pos] : 0.25;
        var ev = cuE.u ? lm * cuE.u[k] + (1 - lm) * act : act;
        if (!prior && !ev) return;
        compsU[k] = +(((COMP_USAGE.P * prior + cuE.g * ev) / (COMP_USAGE.P + cuE.g)) * factor).toFixed(2);
      });
    }
    var propMean = null;
    var baseM = jsMean != null ? jsMean : mean;
    p._vacBoost = /\+(vacx|promo)/.test(ncSrc || '') && !(typeof window !== 'undefined' && window.SIM_VAC_BOOKCAP_SKIP === false);
    if (iA >= 1) propMean = propAnchorMean(p, wk, sc, compsWk, baseM);
    else if (iA > 0) {
      var compsPlay = {};
      var iP = Math.max(iA, Math.min(1, injPlay(p, wk)));
      Object.keys(compsWk).forEach(function (k) { compsPlay[k] = compsWk[k] / iP; });
      var anchoredPlay = propAnchorMean(p, wk, sc, compsPlay, baseM / iP, PROP_DOCKED_MAX_AGE_DAYS);
      if (anchoredPlay != null) propMean = anchoredPlay * iP;
    }
    var propSrc = propMean != null ? 'line' : null;
    var propWUsed = propMean != null ? p._propWUsed : null;
    if (propMean == null && iA > 0 && qb2Cap == null) {
      var mkt = marketRate(p, wk, sc, schedule);
      if (mkt) {
        var mw = propWeight(p) * mkt.conf;
        if (mw > 0) {
          propMean = Math.max(0, (mw * mkt.rate + (1 - mw) * jsPg * bbRatio * mDock) * jsChain + (1 - mw) * luckAdj * mDock);
          propSrc = 'rate';
        }
      }
    }
    var espnPts = null, rmMean = null, rmFinal = null;
    var EWk = typeof window !== 'undefined' ? window.SIM_ESPN_WEEKLY : null;
    if (EWk && EWk.p && +EWk.week === +wk && !(typeof window !== 'undefined' && window.SIM_RANKMIX === false)) {
      var eRow = EWk.p[p.norm];
      if (eRow && eRow.length === 3 && eRow[2] != null && eRow[1] != null) { espnPts = eRow[2] + sc.rec * (eRow[1] - eRow[2]); if (p.pos === 'TE' && sc.bonus_rec_te) espnPts += sc.bonus_rec_te * (eRow[1] - eRow[2]); }
    }
    if (ncMean != null) {
      rmMean = (espnPts != null && espnPts > 0.5 && ncMean > 0) ? NC_SHADOW.rankMixW * ncMean + (1 - NC_SHADOW.rankMixW) * espnPts : ncMean;
      rmFinal = (propSrc === 'line' && propMean != null && propWUsed != null) ? Math.max(0, propMean + (1 - propWUsed) * (rmMean - baseM)) : rmMean;
    }
    return { balloc: ncBalloc, vfade: ncVfadeD > 0 && ncAtVac > 0 ? ncVfadeD * ncMean / ncAtVac : 0, ncPeck: ncPeckM, ncPeckRank: ncPeckRk, ncQbf: ncQbfM, qb2: qb2Tag, mean: mean, mult: mult, slot: slot, comps: compsWk, compsU: compsU, gameIdx: gameIdx, jsMean: jsMean, propMean: propMean, propSrc: propSrc, propW: propWUsed, luckAdj: luckAdj, ncMean: ncMean, ncSrc: ncSrc, rmMean: rmMean, rmFinal: rmFinal, espnPts: espnPts, lcCorr: lcCorr, peck: mPeck, peckRank: peckR.rank, use: lvU, jsNoUse: jsNoUse, ret: mRet, qbf: mQbf, health: hLift, vol: mVol, bb: bbW, jsPre: jsPre,
      why: { clayPg: clayPg, clayPg0: clayPg0, health: hLift, jsBase: jsBase0, rook: mRook, jsPgRook: jsPgRook, usage: rbU, jsPg: qbInh > 0 ? jsPgOwn : jsPg, veg: mult, implied: slot.implied, avgImplied: schedule.avgImplied, vegTeamAvg: vegTA,
             opp: oppM, dAdj: dAdj, cbShadow: mCbS, cb1Out: mCb1, olOut: mOl, pressure: mPr, weather: mWx, ret: mRet, avail: injAvail(p, wk), qbFloor: mQbf, rosTilt: mRos, snap: mSnap, route: mRoute, ramp: rampF, iA: (qbInh > 0 && jsPgOwn > 0) ? jsPg / jsPgOwn : iA,
             luck: luckAdj, jsMean: jsMean, jsPre: jsPre, bb: bbW, ncMean: ncMean, perGameDiv: perGameDiv, peck: mPeck, peckRank: peckR.rank, vol: mVol, vfade: ncVfadeD > 0 && ncAtVac > 0 ? ncVfadeD * ncMean / ncAtVac : 0, vfadeSeen: ncVfadeSeen, balloc: ncBalloc } };
  }

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
      var gz = p._gi >= 0 ? env.g[p._gi] : rng.normal();
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

  function effMean(wkProj) {
    var w = typeof window !== 'undefined' ? window : null;
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
      var mS = m + DST_SHIFT;
      return rng.gamma((mS * mS) / (sd * sd), (sd * sd) / mS) - DST_SHIFT;
    }
    var k = (m * m) / (sd * sd), th = (sd * sd) / m;
    return rng.gamma(k, th);
  }

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
      var arr = res[i].sort();
      var mean = arr.reduce(function (t, v) { return t + v; }, 0) / arr.length;
      var bb = BOOM_BUST[p.pos] || { boom: 20, bust: 5 };
      var nBoom = 0, nBust = 0;
      for (var q = 0; q < arr.length; q++) {
        if (arr[q] >= bb.boom) nBoom++;
        if (arr[q] < bb.bust) nBust++;
      }
      return {
        player: p, week: wk, mean: mean,
        proj: p._wk.mean, jsProj: p._wk.jsMean, propProj: p._wk.propMean != null ? p._wk.propMean : null, propW: p._wk.propW != null ? p._wk.propW : null,
        luck: p._wk.luckAdj != null ? p._wk.luckAdj : 0,
        ncProj: p._wk.ncMean != null ? p._wk.ncMean : null, ncSrc: p._wk.ncSrc || null,
        rmProj: p._wk.rmMean != null ? p._wk.rmMean : null, rmFinal: p._wk.rmFinal != null ? p._wk.rmFinal : null, espnPts: p._wk.espnPts != null ? p._wk.espnPts : null,
        lcCorr: p._wk.lcCorr != null ? p._wk.lcCorr : null,
        useLam: p._wk.use ? p._wk.use.lam : null, usePg: p._wk.use ? p._wk.use.xfpPg : null, jsNoUse: p._wk.jsNoUse != null ? p._wk.jsNoUse : null,
        peck: p._wk.peck != null ? p._wk.peck : 1, peckRank: p._wk.peckRank != null ? p._wk.peckRank : null,
        ncPeck: p._wk.ncPeck != null ? p._wk.ncPeck : 1, ncPeckRank: p._wk.ncPeckRank != null ? p._wk.ncPeckRank : null,
        vol: p._wk.vol != null ? p._wk.vol : 1, health: p._wk.health != null ? p._wk.health : 0, useHurt: p._wk.use && p._wk.use.hurtG != null ? p._wk.use.hurtG : 0, bb: p._wk.bb || 0, jsPre: p._wk.jsPre != null ? p._wk.jsPre : null,
        ret: p._wk.ret != null ? p._wk.ret : 1,
        qbf: p._wk.qbf != null ? p._wk.qbf : 1,
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

  var SHOCK = { wreckLo: 0.05, wreckHi: 0.50 };
  var SHOCK_EPLUS_TABLE = [0.22299, 0.22053, 0.21690, 0.20863, 0.20030, 0.19190,
    0.18346, 0.17511, 0.16654, 0.15813, 0.14950, 0.14105, 0.13236, 0.12389,
    0.11522, 0.10994];
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

  var TEAM_SHOCK = { k: { RB: 0.35, WR: 0.35, TE: 0.35 }, room: { RB: 0.25, WR: 0.20, TE: 0 }, roomN: { RB: 3, WR: 4, TE: 2 }, floor: 0.05 };
  function teamShockOn() { return !(typeof window !== 'undefined' && window.SIM_TEAM_SHOCK === false); }
  function teamShockCtx(list) {
    var by = {};
    list.forEach(function (x) {
      var p = x.p; if (!p || p.isDST || p.pos === 'K' || !p.tm || !(x.v > 0)) return;
      var t = by[p.tm] = by[p.tm] || { QB: [], RB: [], WR: [], TE: [] };
      if (t[p.pos]) t[p.pos].push({ key: p.sid || p.norm, p: p, v: x.v });
    });
    var teams = {}, inRoom = {};
    Object.keys(by).forEach(function (tm) {
      var t = by[tm], rooms = {};
      ['RB', 'WR', 'TE'].forEach(function (pos) {
        rooms[pos] = t[pos].sort(function (a, b) { return b.v - a.v; }).slice(0, TEAM_SHOCK.roomN[pos]);
        rooms[pos].forEach(function (e) { inRoom[e.key] = 1; });
      });
      var qb = t.QB.sort(function (a, b) { return b.v - a.v; })[0] || null;
      if (qb) inRoom[qb.key] = 1;
      teams[tm] = { qb: qb, rooms: rooms };
    });
    return { teams: teams, inRoom: inRoom };
  }
  function drawTeamShocks(rng, ctx) {
    var shock = {}, hub = {};
    Object.keys(ctx.teams).forEach(function (tm) {
      var t = ctx.teams[tm], raw = {};
      if (t.qb) { raw[t.qb.key] = drawSeasonShock(rng, halfPtsOf(t.qb.p)); shock[t.qb.key] = raw[t.qb.key]; }
      ['RB', 'WR', 'TE'].forEach(function (pos) { t.rooms[pos].forEach(function (e) { raw[e.key] = drawSeasonShock(rng, halfPtsOf(e.p)); }); });
      var gq = t.qb ? raw[t.qb.key] : 1;
      ['RB', 'WR', 'TE'].forEach(function (pos) {
        var room = t.rooms[pos], s = TEAM_SHOCK.room[pos], k = TEAM_SHOCK.k[pos];
        var tot = room.reduce(function (a, e) { return a + e.v; }, 0);
        room.forEach(function (j) {
          var g = raw[j.key];
          if (s > 0 && room.length > 1) {
            room.forEach(function (i) { if (i !== j) g += s * (1 - raw[i.key]) * i.v / (tot - i.v); });
            g = Math.max(TEAM_SHOCK.floor, g);
          }
          shock[j.key] = g;
        });
        hub[tm + '|' + pos] = Math.max(TEAM_SHOCK.floor, 1 + k * (gq - 1));
      });
      ['RB', 'WR', 'TE'].forEach(function (pos) { t.rooms[pos].forEach(function (e) { shock[e.key] *= hub[tm + '|' + pos]; }); });
    });
    return { shock: shock, hub: hub };
  }
  function coupledShock(rng, draw, p) {
    var key = p.sid || p.norm;
    if (draw.shock[key] != null) return draw.shock[key];
    var g = drawSeasonShock(rng, halfPtsOf(p)), h = draw.hub[p.tm + '|' + p.pos];
    return h != null ? g * h : g;
  }

  function simSeason(opts) {
    var sims = opts.sims || 300, sc = opts.scoring || PRESETS.half;
    var rng = makeRng(opts.seed != null ? opts.seed : null);
    var schedule = opts.schedule, players = opts.players;
    var wFrom = Math.max(1, Math.min(WEEKS, opts.weekFrom || 1));
    var wTo = Math.max(wFrom, Math.min(WEEKS, opts.weekTo || WEEKS));

    var ACT = opts.actuals !== undefined ? opts.actuals
      : ((typeof window !== 'undefined' && window.SIM_BANK_PLAYED !== false && window.SIM_ACTUALS_2026) || null);
    var actDone = {};
    if (ACT && ACT.done) Object.keys(ACT.done).forEach(function (w) { actDone[w] = {}; (ACT.done[w] || []).forEach(function (t) { actDone[w][normTeam(t)] = 1; }); });
    var bankedOf = function (p, w) {
      if (!ACT || !actDone[w] || !actDone[w][p.tm]) return null;
      if (!(schedule.byTeam[p.tm] && schedule.byTeam[p.tm][w])) return null;
      var row = ACT.weeks && ACT.weeks[w] ? ACT.weeks[w][p.sid] : null;
      if (!row && !p.isDST && !p.sid) {
        var jr = jsData().players ? jsData().players[p.norm] : null, wfv = jr && jr.wf ? jr.wf[w] : null;
        return { pts: wfv != null ? wfv : 0, row: null };
      }
      if (!row) return p.isDST ? null : { pts: 0, row: null };
      var v = row[0];
      if (!p.isDST && p.pos !== 'K') v += (sc.rec || 0) * row[1] + ((sc.pass_td != null ? sc.pass_td : 4) - 4) * row[2] + (p.pos === 'TE' ? (sc.bonus_rec_te || 0) * row[1] : 0);
      return { pts: v, row: row };
    };

    var gpInSeasonOff = Object.keys(actDone).length > 0 && !(typeof window !== 'undefined' && window.SIM_SEASON_GP_INSEASON === true);
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
      var seasonMean = wks.reduce(function (t, x) { return t + effMean(x.wp); }, 0);
      if (!p.isDST && seasonMean < 0.3 * wks.length && !(banked > 0)) return;
      var gm = Math.min(17, Math.max(2, p.clayGames || 17));
      var useInj = !p.qbWindow && !p.isDST && gm < 17 && !(gpInSeasonOff);
      pool.push({
        p: p, wks: wks, seasonMean: seasonMean, banked: banked, bankedWeeks: bankedWeeks,
        shocked: !p.isDST && p.pos !== 'K',
        inf: (useInj && clayDiv(p) === 17) ? 17 / gm : 1, pPlay: useInj ? gm / 17 : 1,
        totals: new Float64Array(sims), rankSum: 0, rankCounts: {}
      });
    });

    var byPos = {};
    pool.forEach(function (e, i) { (byPos[e.p.pos] = byPos[e.p.pos] || []).push(i); });
    var posGroups = Object.keys(byPos).map(function (pos) { return byPos[pos]; });
    var nWks = wTo - wFrom + 1, envByWeek = new Array(nWks), sNow = 0;
    function cmpTotals(a, b) { return pool[b].totals[sNow] - pool[a].totals[sNow]; }

    var tsCtx = teamShockOn() ? teamShockCtx(pool.filter(function (e) { return e.shocked; }).map(function (e) { return { p: e.p, v: e.seasonMean }; })) : null;
    for (var s = 0; s < sims; s++) {
      for (var w2 = wFrom; w2 <= wTo; w2++) envByWeek[w2 - wFrom] = drawWeekEnv(schedule.byWeek[w2] || [], rng, players);
      var tsDraw = tsCtx ? drawTeamShocks(rng, tsCtx) : null;
      for (var i = 0; i < pool.length; i++) {
        var e = pool[i], tot = e.banked, wks = e.wks;
        var scale = (e.shocked ? (tsDraw ? coupledShock(rng, tsDraw, e.p) : drawSeasonShock(rng, halfPtsOf(e.p))) : 1) * e.inf;
        for (var j = 0; j < wks.length; j++) {
          if (e.pPlay < 1 && rng.rand() >= e.pPlay) continue;
          tot += samplePlayerScore(e.p, wks[j].wp, envByWeek[wks[j].wi], rng, scale);
        }
        e.totals[s] = tot;
      }
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
      var arr = e.totals.slice().sort();
      var mean = arr.reduce(function (t, v) { return t + v; }, 0) / sims;
      function topN(n) {
        var c = 0;
        for (var r = 1; r <= n; r++) c += e.rankCounts[r] || 0;
        return c / sims;
      }
      var _med = pct(arr, 0.50), _nB = 0, _nD = 0;
      if (_med > 0) {
        for (var q = 0; q < sims; q++) {
          if (arr[q] >= _med * 1.25) _nB++;
          if (arr[q] <= _med * 0.75) _nD++;
        }
      }
      return {
        player: e.p, games: e.wks.length + e.bankedWeeks.length, gamesSim: e.wks.length, banked: e.banked, bankedWeeks: e.bankedWeeks,
        seasonProj: e.seasonMean * e.pPlay + e.banked, clayPts: seasonPoints(e.p, sc),
        seasonBoom: _med > 0 ? _nB / sims : null, seasonBust: _med > 0 ? _nD / sims : null,
        mean: mean, p10: pct(arr, 0.10), p25: pct(arr, 0.25), p50: pct(arr, 0.50),
        p75: pct(arr, 0.75), p90: pct(arr, 0.90),
        avgRank: e.rankSum / sims, rankCounts: e.rankCounts,
        top1: topN(1), top3: topN(3), top12: topN(12), top24: topN(24),
        weeks: e.wks, sims: sims
      };
    }).sort(function (a, b) { return b.mean - a.mean; });
  }

  function bracketRounds(n) { var r = 0, p = 1; while (p < n) { p *= 2; r++; } return r; }
  function bracketOrder(n) {
    var order = [1];
    while (order.length < n) {
      var m = order.length * 2 + 1;
      order = order.reduce(function (a, s) { a.push(s, m - s); return a; }, []);
    }
    return order;
  }

  function simLeague(opts) { return simLeagueStart(opts).finish(); }
  var _lgAsyncTail = null;
  function simLeagueAsync(opts, ctl) {
    ctl = ctl || {};
    var batch = ctl.batch > 0 ? Math.floor(ctl.batch) : 0;
    function sliceMs() { var v = typeof ctl.sliceMs === 'function' ? ctl.sliceMs() : ctl.sliceMs; return v > 0 ? v : 16; }
    function wait() {
      if (typeof ctl.yieldFn === 'function') return Promise.resolve(ctl.yieldFn());
      if (typeof scheduler !== 'undefined' && scheduler && typeof scheduler.yield === 'function') return Promise.resolve(scheduler.yield());
      return new Promise(function (r) { setTimeout(r, 0); });
    }
    function stale() { return typeof ctl.isStale === 'function' && !!ctl.isStale(); }
    function runOne() {
      return wait().then(function () {
        if (stale()) return null;
        return typeof opts === 'function' ? opts() : opts;
      }).then(function (o) {
        if (o == null || stale()) return null;
        var run = simLeagueStart(o);
        return new Promise(function (resolve, reject) {
          function slice() {
            try {
              if (stale()) { run.cancel(); resolve(null); return; }
              var done;
              if (!batch) done = run.stepFor(sliceMs());
              else if (run.ready()) done = run.step(batch);
              else { run.setupFor(sliceMs()); done = false; }
              if (typeof ctl.onProgress === 'function') ctl.onProgress(run.completed(), run.sims, run.ready());
              if (done) { resolve(run.finish()); return; }
              wait().then(slice, reject);
            } catch (e) { reject(e); }
          }
          slice();
        });
      });
    }
    var p = (ctl.queue === false || !_lgAsyncTail) ? runOne() : _lgAsyncTail.then(runOne);
    if (ctl.queue !== false) _lgAsyncTail = p.then(function () {}, function () {});
    return p;
  }
  function simLeagueStart(opts) {
    var sims = opts.sims || 100, sc = opts.scoring, rng = makeRng(opts.seed != null ? opts.seed : null);
    var schedule = opts.schedule, players = opts.players;
    var teams = opts.teams, pairsByWeek = opts.pairsByWeek;
    var regWeeks = opts.regWeeks;
    var playoffTeams = opts.playoffTeams || 6;
    var playoffStart = opts.playoffStart || 15;
    var reseed = !!opts.playoffReseed;
    var lineupSlots = opts.lineupSlots;
    var unavailable = opts.unavailable || {};
    var currentWeek = opts.currentWeek || (regWeeks.length ? regWeeks[0] : 1);
    var lockedPts = opts.lockedPts || null, lockedTeams = opts.lockedTeams || {};
    var lockedReal = opts.lockedReal || null;
    var meanFor = typeof opts.meanFor === 'function' ? opts.meanFor : null;
    function mkCand(p, wk, rid) {
      var wp = weeklyProjection(p, wk, sc, schedule);
      if (meanFor && wp) {
        var mo = meanFor(p, wk);
        if (mo != null && isFinite(mo)) {
          if (!(mo > 0.05)) wp = null;
          else { var wq = {}; for (var kq in wp) wq[kq] = wp[kq]; wq.propMean = mo; if (!(wq.mean > 0.05)) wq.mean = mo; wp = wq; }
        }
      }
      var isLocked = lockedPts && wk === currentWeek && lockedTeams[p.tm];
      if (isLocked) {
        var fb = lockedPts[p.sid] != null ? lockedPts[p.sid] : 0;
        var real = lockedReal && rid != null && lockedReal[rid] ? lockedReal[rid][p.sid] : null;
        if (real) {
          if (!real.start) return null;
          var pts = real.pts != null ? real.pts : fb;
          return { p: p, wp: wp || { mean: pts, sd: 0 }, locked: pts, force: 1 };
        }
        if (lockedReal && rid == null) return null;
        return wp ? { p: p, wp: wp, locked: fb } : null;
      }
      return wp ? { p: p, wp: wp } : null;
    }

    var allWeeks = regWeeks.slice(), poRounds = bracketRounds(playoffTeams);
    for (var w = playoffStart; w < playoffStart + poRounds; w++) allWeeks.push(w);
    var prep = {};
    var playoffProj = {};
    var curShocks;
    var tsCtx = null, tsDraw = null;
    function* setupSteps() {
      var candsBy = {};
      for (var cti = 0; cti < teams.length; cti++) {
        var cT = teams[cti];
        candsBy[cT.rosterId] = {};
        var roster = cT.playerIds.map(function (sid) { return players.bySid[sid]; }).filter(Boolean)
          .filter(function (p) { return unavailable[p.sid] !== 'ir'; });
        for (var cwi = 0; cwi < allWeeks.length; cwi++) {
          var cWk = allWeeks[cwi], cList = [];
          for (var cri = 0; cri < roster.length; cri++) {
            if (cWk === currentWeek && unavailable[roster[cri].sid] === 'out') continue;
            var cand = mkCand(roster[cri], cWk, cT.rosterId);
            if (cand) cList.push(cand);
            yield;
          }
          candsBy[cT.rosterId][cWk] = cList.sort(function (a, b) { return ((b.force || 0) - (a.force || 0)) || (effMean(b.wp) - effMean(a.wp)); });
        }
      }

      var STREAM_TOL = 1.0;
      var waiversOn = typeof window === 'undefined' || window.SIM_WAIVER_FILLS !== false;
      var rosteredIds = {};
      teams.forEach(function (t) { t.playerIds.forEach(function (id) { rosteredIds[id] = 1; }); });
      function* waiverPool(list, wk) {
        var out = [];
        for (var i = 0; i < list.length; i++) {
          var p = list[i];
          if (unavailable[p.sid] === 'ir') continue;
          if (wk === currentWeek && unavailable[p.sid] === 'out') continue;
          var c = mkCand(p, wk);
          if (c) out.push(c);
          yield;
        }
        return out.sort(function (a, b) { return ((b.force || 0) - (a.force || 0)) || (effMean(b.wp) - effMean(a.wp)); });
      }
      var hasDefSlot = lineupSlots.some(function (s) { return (SLOT_ELIGIBLE[s] || []).indexOf('DST') >= 0; });
      if (waiversOn && hasDefSlot) {
        var waiverDsts = players.list.filter(function (p) { return p.isDST && !rosteredIds[p.sid]; });
        for (var dwi = 0; dwi < allWeeks.length; dwi++) {
          var dPool = yield* waiverPool(waiverDsts, allWeeks[dwi]);
          if (dPool.length) (function (wk, pool) {
            var order = teams.map(function (t) {
              var have = -1;
              candsBy[t.rosterId][wk].forEach(function (c) {
                if (c.p.isDST) have = Math.max(have, effMean(c.wp));
              });
              return { rid: t.rosterId, have: have };
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
          })(allWeeks[dwi], dPool);
        }
      }

      var waiverByPos = {};
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
          if (!elig.length) return;
          for (var i = 0; i < cands.length; i++) {
            if (used[i]) continue;
            if (elig.indexOf(cands[i].p.pos) >= 0) { used[i] = 1; return; }
          }
          un.push(o.s);
        });
        return un;
      }
      if (waiversOn) for (var hwi = 0; hwi < allWeeks.length; hwi++) {
        var hWk = allWeeks[hwi];
        var pools = {};
        var claimed = {};
        for (var hti = 0; hti < teams.length; hti++) {
          var hCands = candsBy[teams[hti].rosterId][hWk];
          var holes = unfilledSlots(hCands, lineupSlots);
          if (!holes.length) continue;
          var changed = false;
          for (var hsi = 0; hsi < holes.length; hsi++) {
            var best = null, elig = SLOT_ELIGIBLE[holes[hsi]] || [];
            for (var hei = 0; hei < elig.length; hei++) {
              var hPos = elig[hei];
              if (!(hPos in pools)) pools[hPos] = yield* waiverPool(waiverByPos[hPos] || [], hWk);
              for (var hpi = 0; hpi < pools[hPos].length; hpi++) {
                var hc = pools[hPos][hpi];
                if (claimed[hc.p.sid]) continue;
                if (!best || effMean(hc.wp) > effMean(best.wp)) best = hc;
                break;
              }
            }
            if (best) {
              claimed[best.p.sid] = 1;
              hCands.push(best);
              changed = true;
            }
          }
          if (changed) hCands.sort(function (a, b) { return ((b.force || 0) - (a.force || 0)) || (effMean(b.wp) - effMean(a.wp)); });
        }
      }

      teams.forEach(function (t) {
        prep[t.rosterId] = {};
        allWeeks.forEach(function (wk) {
          prep[t.rosterId][wk] = pickLineup(candsBy[t.rosterId][wk], lineupSlots);
        });
      });

      teams.forEach(function (t) {
        playoffProj[t.rosterId] = {};
        for (var w2 = playoffStart; w2 < playoffStart + poRounds; w2++) {
          var lu = prep[t.rosterId][w2] || [];
          playoffProj[t.rosterId][w2] = lu.reduce(function (s2, slot) { return s2 + effMean(slot.wp); }, 0);
        }
      });

      if (teamShockOn()) {
        var tsWeeks = allWeeks.slice(0, 3), tsList = [];
        for (var tsi = 0; tsi < players.list.length; tsi++) {
          var tsP = players.list[tsi];
          if (tsP.isDST || tsP.pos === 'K') continue;
          var tsV = 0;
          for (var tswi = 0; tswi < tsWeeks.length; tswi++) {
            var tsWp = weeklyProjection(tsP, tsWeeks[tswi], sc, schedule);
            if (tsWp) tsV += effMean(tsWp);
            yield;
          }
          tsList.push({ p: tsP, v: tsV });
        }
        tsCtx = teamShockCtx(tsList);
      }
    }

    function getShock(p) {
      if (p.isDST || p.pos === 'K') return 1;
      var k = p.sid || p.norm;
      if (!(k in curShocks)) curShocks[k] = tsDraw ? coupledShock(rng, tsDraw, p) : drawSeasonShock(rng, halfPtsOf(p));
      return curShocks[k];
    }

    var tally = {};
    var weekTally = {};
    teams.forEach(function (t) {
      tally[t.rosterId] = {
        team: t, wins: 0, pf: 0, playoffs: 0, byes: 0, titles: 0, finals: 0,
        pfLead: 0, pfs: new Float64Array(sims),
        seedCounts: {}, winCounts: {}, placeCounts: {}
      };
      weekTally[t.rosterId] = {};
    });

    function runSim(s) {
      curShocks = {};
      tsDraw = tsCtx ? drawTeamShocks(rng, tsCtx) : null;
      var rec = {};
      teams.forEach(function (t) {
        rec[t.rosterId] = { w: t.record ? t.record.w : 0, l: t.record ? t.record.l : 0, pf: t.record ? t.record.pf : 0 };
      });
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
      var pfBest = null;
      teams.forEach(function (t) {
        if (pfBest === null || rec[t.rosterId].pf > rec[pfBest].pf) pfBest = t.rosterId;
      });
      tally[pfBest].pfLead++;
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
      var seeds = order.slice(0, playoffTeams).map(function (t) { return t.rosterId; });
      var champ = simBracket(seeds, playoffStart, prep, schedule, rng, tally);
      tally[champ].titles++;
    }

    var setupIt = setupSteps(), setupDone = false, sDone = 0, dropped = false, broken = false, built = null;
    function nowMs() { return typeof performance !== 'undefined' && performance && typeof performance.now === 'function' ? performance.now() : Date.now(); }
    function work(simEnd, ms) {
      if (broken) throw new Error('simLeague run failed earlier; start a new one');
      var t0 = ms != null ? nowMs() : 0;
      try {
        while (!setupDone) {
          if (setupIt.next().done) { setupDone = true; setupIt = null; }
          if (ms != null && nowMs() - t0 >= ms) return false;
        }
        while (sDone < simEnd) {
          runSim(sDone); sDone++;
          if (ms != null && nowMs() - t0 >= ms) break;
        }
      } catch (e) { broken = true; throw e; }
      return sDone >= sims;
    }
    function step(n) {
      if (dropped) return true;
      return work(n == null ? sims : Math.min(sims, sDone + Math.max(1, Math.floor(n) || 1)), null);
    }
    function stepFor(ms) {
      if (dropped) return true;
      return work(sims, ms > 0 ? ms : 0);
    }
    function setupFor(ms) {
      if (dropped) return true;
      if (!setupDone) work(sDone, ms > 0 ? ms : 0);
      return setupDone;
    }
    function finish() {
      if (dropped) return null;
      if (!built) { work(sims, null); built = buildResults(); }
      return built;
    }
    return {
      sims: sims, step: step, stepFor: stepFor, setupFor: setupFor, finish: finish,
      cancel: function () { dropped = true; built = null; setupIt = null; },
      completed: function () { return sDone; },
      ready: function () { return setupDone; },
      isDone: function () { return setupDone && sDone >= sims; },
      cancelled: function () { return dropped; }
    };

    function buildResults() {
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
    }

    function teamScore(lineup, env, rng2) {
      var total = 0;
      (lineup || []).forEach(function (slot) { total += slot.locked != null ? slot.locked : samplePlayerScore(slot.p, slot.wp, env, rng2, getShock(slot.p)); });
      return total;
    }

    function playWeekScore(rosterId, wk, env, rng2) {
      return teamScore(prep[rosterId][wk], env, rng2);
    }

    function simBracket(seeds, startWk, prepIgnored, schedule2, rng2, tally2) {
      var n = seeds.length;
      if (n < 2) return seeds[0];
      var slots = bracketOrder(n).map(function (s) { return s <= n ? seeds[s - 1] : null; });
      var wk = startWk;
      while (slots.length > 1) {
        if (reseed && wk > startWk && slots.length > 2) {
          var srt = slots.slice().sort(function (x, y) { return seeds.indexOf(x) - seeds.indexOf(y); }), rs = [];
          for (var q = 0; q < srt.length / 2; q++) rs.push(srt[q], srt[srt.length - 1 - q]);
          slots = rs;
        }
        if (slots.length === 2) slots.forEach(function (r) { if (r != null) tally2[r].finals++; });
        var next = [];
        for (var i = 0; i < slots.length; i += 2) {
          var a = slots[i], b = slots[i + 1];
          if (a == null || b == null) {
            var adv = a == null ? b : a;
            if (adv != null && wk === startWk) tally2[adv].byes++;
            next.push(adv);
          } else next.push(duel(a, b, wk));
        }
        slots = next; wk++;
      }
      return slots[0];

      function duel(ra, rb, week) {
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

  function simBestBall(opts) {
    var sims = opts.sims || 300, sc = opts.scoring || PRESETS.half;
    var rng = makeRng(opts.seed != null ? opts.seed : null);
    var schedule = opts.schedule, players = opts.players;
    var regTo = Math.min(17, Math.max(4, opts.regTo || 14));
    var wTo = Math.min(17, regTo + 3);
    var squads = opts.squads, teams = opts.teams;
    var sqSf = opts.sqSf || [];
    var fromWeek = Math.max(1, Math.min(wTo, opts.fromWeek || 1));
    var actuals = opts.actualsBySid || {};
    var unavailable = opts.unavailable || {};

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
    var S = new Float64Array(nE * wTo);
    var envs = new Array(wTo);
    var sqReg = new Float64Array(squads.length);

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
        elimCurve: t.elim ? new Float64Array(wTo) : null, elimFinal: 0, elimWin: 0,
        fieldPo: (t.collectFieldPo && t.field && t.field.length)
          ? poWeeks.map(function () { return new Float64Array(t.field.length * sims); }) : null
      };
    });

    function elimSim(tm, r) {
      var field = tm.field, n = field.length;
      if (!n) return;
      var members = [tm.squad].concat(field), M = members.length;
      var sc2 = new Array(M), w = new Array(M), nw = new Array(M);
      for (var m0 = 0; m0 < M; m0++) sc2[m0] = bbWeekPoints(sqEntries[members[m0]], 1, sqSf[members[m0]]);
      for (var m1 = 0; m1 < M; m1++) {
        var beat = 0;
        for (var f1 = 0; f1 < M; f1++) if (sc2[f1] > sc2[m1]) beat++;
        w[m1] = beat < 6 ? 1 : 0;
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
        r.elimWin += w[0] * p1 * p1;
      }
    }

    for (var s = 0; s < sims; s++) {
      for (var w1 = fromWeek; w1 <= wTo; w1++) envs[w1 - 1] = drawWeekEnv(schedule.byWeek[w1] || [], rng, players);
      for (var e = 0; e < nE; e++) {
        var en = entries[e], base = e * wTo;
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
  var BB_POS_CODE = { QB: 0, RB: 1, WR: 2, TE: 3, FB: 1 };

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
  function bbFieldAddWeek(roster, vals, banked, sign) {
    var posC = roster.players.map(function (p) { return BB_POS_CODE[p.pos] != null ? BB_POS_CODE[p.pos] : 4; });
    var start = roster.start, ix = roster.ix;
    var sg = sign < 0 ? -1 : 1;
    for (var q = 0; q < banked.length; q++) banked[q] += sg * bbLineup(ix, start[q], start[q + 1], vals, posC);
  }

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
    var po = (opts.playoff && opts.all && nW > 0) ? opts.playoff : null;
    var lastWk = po ? Math.max(regTo, Math.min(18, po.lastWeek || regTo + 3)) : regTo;
    var nWA = Math.max(0, lastWk - fromWeek + 1);

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
    var S = [];
    for (var w0 = 0; w0 < nWA; w0++) S.push(new Float64Array(Math.max(1, nE)));
    var envs = new Array(nWA);

    var T = mine.length, a = new Float64Array(T), mt = new Float64Array(T);
    var bucket = new Float64Array(T + 1), suf = new Float64Array(T + 2);
    var HB = 20, HN = 4096 * HB, hist = new Float64Array(HN);
    var cutOut = new Float64Array(cutRanks.length), rankOut = new Float64Array(T);
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
        rankOut[m2] = 1 + suf[lo2];
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
      var wkIdx = nW;
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
        advBuf[nB++] = wq;
      }
      shuffle(advBuf, nB);
      var nC = 0;
      for (base = 0; base < nB; base += po.g3) {
        m = Math.min(po.g3, nB - base);
        for (i = 0; i < m; i++) {
          bq = advBuf[base + i];
          scoreBuf[i] = bbLineup(ix, start[bq], start[bq + 1], S[wkIdx + 1], posC);
          grp[i] = i;
        }
        for (i = 1; i < m; i++) {
          var gi = grp[i], gs = scoreBuf[gi];
          for (j = i - 1; j >= 0 && scoreBuf[grp[j]] < gs; j--) grp[j + 1] = grp[j];
          grp[j + 1] = gi;
        }
        var winner = advBuf[base + grp[0]];
        for (i = 1; i < m; i++) A.poEv[advBuf[base + grp[i]]] += inv * (i < po.r3Prize.length ? po.r3Prize[i] : po.r3Prize[po.r3Prize.length - 1]);
        A.adv3[winner] += inv;
        advBuf[nC++] = winner;
      }
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
        if (locked) S[0][e] = lockVals[e];
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

  var SLOT_ELIGIBLE = {
    QB: ['QB'], RB: ['RB'], WR: ['WR'], TE: ['TE'], K: ['K'], DEF: ['DST'], DST: ['DST'],
    FLEX: ['RB', 'WR', 'TE'], WRRB_FLEX: ['RB', 'WR'], REC_FLEX: ['WR', 'TE'],
    SUPER_FLEX: ['QB', 'RB', 'WR', 'TE'], IDP_FLEX: []
  };
  function pickLineup(cands, slots) {
    var used = {}, lineup = [];
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

  window.SimEngine = {
    SEASON: SEASON, WEEKS: WEEKS, PRESETS: PRESETS, BOOM_BUST: BOOM_BUST,
    norm: norm, normTeam: normTeam, makeRng: makeRng,
    buildSchedule: buildSchedule, buildPlayers: buildPlayers,
    applyInSeasonInjuries: applyInSeasonInjuries, qsCandidates: qsCandidates, qsForce: qsForce, injAdj: injAdj, injAvail: injAvail, injGroup: injGroup, linesUp: linesUp, injSignalInfo: injSignalInfo, bangedDock: bangedDock, returnDock: returnDock, injuryState: injuryState, newsFlags: newsFlags, ascendingFlag: ascendingFlag, injPlay: injPlay, rookieLevel: rookieLevel, rbUsagePg: rbUsagePg, learnedShadowCorr: learnedShadowCorr, lgbPredict: lgbPredict, lgbExplain: lgbExplain, learnedShadowExplain: learnedShadowExplain, ctxNote: ctxNote,
    scoringFromLeague: scoringFromLeague, seasonPoints: seasonPoints, dstWeeklyMean: dstWeeklyMean, dstScoringDelta: dstScoringDelta,
    weeklyProjection: weeklyProjection, vegasMult: vegasMult, vegasTeamAvg: vegasTeamAvg, defenseAdj: defenseAdj, cbShadowMult: cbShadowMult, cb1OutBoost: cb1OutBoost, olOutDock: olOutDock, pressureMult: pressureMult, tdLuckAdj: tdLuckAdj, weatherMult: weatherMult, snapMult: snapMult, routeMult: routeMult, paceMult: paceMult,
    jsBasePg: jsBasePg, jsOppMult: jsOppMult, ncCacheReset: ncCacheReset,
    propAnchorMean: propAnchorMean, gammaMedRatio: gammaMedRatio, marketRate: marketRate, propImpliedFp: propImpliedFp, propCacheReset: propCacheReset,
    marketObsContaminated: marketObsContaminated,
    simWeek: simWeek, simSeason: simSeason, simLeague: simLeague, simLeagueStart: simLeagueStart, simLeagueAsync: simLeagueAsync, bracketRounds: bracketRounds, simBestBall: simBestBall, simBBField: simBBField, bbFieldRun: bbFieldRun, bbFieldAddWeek: bbFieldAddWeek, bbRosterOf: bbRosterOf, bbSleeperIndex: bbSleeperIndex, bbResolveSid: bbResolveSid, bbAliasNorm: bbAliasNorm, pickLineup: pickLineup,
    drawWeekEnv: drawWeekEnv, samplePlayerScore: samplePlayerScore, effMean: effMean, CORR: CORR,
    drawSeasonShock: drawSeasonShock, teamShockCtx: teamShockCtx, drawTeamShocks: drawTeamShocks, coupledShock: coupledShock, SLOT_ELIGIBLE: SLOT_ELIGIBLE
  };
})();
