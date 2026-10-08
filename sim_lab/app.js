// ============================================================================
// SIM LAB APP — UI wiring, Sleeper + ESPN + Yahoo league import, tracking & accuracy.
// Private research tool. Everything persists to localStorage + JSON exports;
// nothing here touches the MFF site.
// ============================================================================
(function () {
  'use strict';
  var E = window.SimEngine;
  var API = 'https://api.sleeper.app/v1';

  var state = {
    schedule: null, players: null,
    weekResults: null, weekMeta: null,
    seasonResults: null, seasonMeta: null,
    league: null, leagueResults: null,
    snapshots: loadLS('simlab_snapshots', {}),
    accuracy: loadLS('simlab_accuracy', {})
  };

  function loadLS(k, d) { try { return JSON.parse(localStorage.getItem(k)) || d; } catch (e) { return d; } }
  function saveLS(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  function $(id) { return document.getElementById(id); }
  function fmt(v, d) { return (v == null || isNaN(v)) ? '—' : v.toFixed(d == null ? 1 : d); }
  function pctf(v) { return (v == null || isNaN(v)) ? '—' : (100 * v).toFixed(1) + '%'; }
  // long-shot odds read better as 1-in-N than as 0.00%
  function fmtOdds(p) {
    if (p == null || isNaN(p)) return '—';
    if (p > 0 && p < 0.0005) return '1/' + Math.round(1 / p).toLocaleString();
    return (100 * p).toFixed(p < 0.01 ? 2 : 1) + '%';
  }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

  // ---------------- boot ----------------
  document.addEventListener('DOMContentLoaded', function () {
    state.schedule = E.buildSchedule();
    state.players = E.buildPlayers(state.schedule);
    var nGames = Object.keys(state.schedule.byWeek).reduce(function (t, w) { return t + state.schedule.byWeek[w].length; }, 0);
    $('status').textContent = state.players.list.length + ' players · ' + nGames + ' Vegas games · avg implied ' +
      state.schedule.avgImplied.toFixed(1) + ' · data ' + (window.SIM_DATA_REFRESHED || '?');
    // In-season injury layer (2026-09-09): same zeros + vacated-opportunity
    // redistribution the site export applies, keyed on the current week
    // from the exporter's ESPN kickoff cache (deployed alongside). Active
    // from 4 days before the week's first kickoff; camp tags never count.
    (async function armInjuryLayer() {
      try {
        var kicks = await (await fetch('data/kickoffs_2026.json?t=' + Date.now())).json();
        var now = Date.now(), cur = 1, firstKick = null;
        for (var w = 1; w <= 18; w++) {
          var kw = kicks[w]; if (!kw) continue;
          var ts = Object.keys(kw).map(function (t) { return new Date(kw[t]).getTime(); });
          var last = Math.max.apply(null, ts);
          cur = w; firstKick = Math.min.apply(null, ts);
          if (now < last + 6 * 3600 * 1000) break;
        }
        var active = firstKick != null && now >= firstKick - 4 * 24 * 3600 * 1000;
        var st = E.applyInSeasonInjuries(state.players, cur, { active: active });
        state.injuryWeek = cur;
        state.injuryActive = active; // the field-sim workers re-apply the same layer
        // 2026-09-27: current-week games already final (kickoff 5h+ ago) -> league sims bank the real scores
        try {
          var doneTm = {}, kc = kicks[cur] || {};
          Object.keys(kc).forEach(function (t) { if (now >= new Date(kc[t]).getTime() + 5 * 3600 * 1000) doneTm[t] = new Date(kc[t]).getTime(); }); // value = kickoff ms
          if (Object.keys(doneTm).length) {
            var lst = await (await fetch(API + '/stats/nfl/regular/' + E.SEASON + '/' + cur)).json();
            state.locked = { week: cur, teams: doneTm, stats: lst };
            $('status').textContent += ' · wk ' + cur + ' banked: ' + Object.keys(doneTm).join('/');
          }
        } catch (eL) { /* no stats feed — week stays fully simmed */ }
        if (st.zeros.length) {
          $('status').textContent += ' · wk ' + cur + ' injury layer: ' + st.zeros.length + ' out/docked';
          $('status').title = st.zeros.map(function (z) { return z.name + ' (' + z.tm + ' ' + z.pos + ') wk' + z.from + (z.to > z.from ? '-' + z.to : '') + (z.mult ? ' x' + z.mult : '') + ' [' + z.src + ']'; }).join('\n');
        } else if (active) {
          $('status').textContent += ' · wk ' + cur + ' injury layer: no designations';
        }
        // 2026-10-01: the NOTES sheet is first drawn at boot, before this layer arms — redraw it so it never shows
        // ruled-out players at their healthy numbers (Pierce 7.9 behind an active out-window until the week was re-picked)
        try { if ($('nt-week') && $('nt-week').options.length) renderNotesTab(); } catch (eN) { /* notes not built yet */ }
        if (state.weekResults) $('wk-note').textContent += ' — injury layer armed after this run; re-run to apply';
      } catch (e) { /* no kickoff cache deployed — layer stays off */ }
    })();
    var wkSel = $('wk-week'), tkSel = $('tk-week');
    for (var w = 1; w <= 18; w++) {
      wkSel.add(new Option('Week ' + w, w));
      tkSel.add(new Option('Week ' + w, w));
      $('sn-from').add(new Option('Wk ' + w, w));
      $('sn-to').add(new Option('Wk ' + w, w));
    }
    $('sn-to').value = 18;
    try { var cwSn = (window.SIM_INJ_SIGNALS && window.SIM_INJ_SIGNALS.week) || (window.SIM_PRACTICE_2026 && window.SIM_PRACTICE_2026.week); if (cwSn >= 1 && cwSn <= 18) $('sn-from').value = cwSn; } catch (e) {}   // Season Sim defaults to the current week (ROS audit 10-01 open item, fixed 10-07): played weeks are banked, not re-simulated
    document.querySelectorAll('.tab').forEach(function (b) {
      b.addEventListener('click', function () { showTab(b.dataset.tab); });
    });
    // Auto-locked snapshots (2026-09-09): export_site_proj.js locks every game
    // ~35 min before kickoff into data/snapshots/simlab_snapshot_w<wk>.json
    // (deployed with the site). Merge them into the browser's snapshots —
    // games this browser locked itself always win, games it never locked
    // take the file's rows — so the TRACKING tab grades every week even
    // when nobody pressed Lock. Re-fetched on every boot (no-cache hosting).
    (async function mergeAutoLocks() {
      try {
        var idx = await (await fetch('data/snapshots/index.json?t=' + Date.now())).json();
        if (!idx || !Array.isArray(idx.weeks)) return;
        var merged = 0;
        for (var i = 0; i < idx.weeks.length; i++) {
          var w = idx.weeks[i];
          try {
            var f = await (await fetch('data/snapshots/simlab_snapshot_w' + w + '.json?t=' + Date.now())).json();
            if (!f || !f.lockedGames) continue;
            var local = state.snapshots[w];
            if (!local) { state.snapshots[w] = f; merged++; continue; }
            local.lockedGames = local.lockedGames || {};
            local.players = local.players || [];
            var m = 0;
            Object.keys(f.lockedGames).forEach(function (k) {
              if (local.lockedGames[k]) return;
              local.lockedGames[k] = f.lockedGames[k];
              (f.players || []).filter(function (p) { return p.game === k; }).forEach(function (p) { local.players.push(p); });
              m++;
            });
            if (m) { local.lockedAt = local.lockedAt || f.lockedAt; merged++; }
          } catch (e2) { /* week file missing — skip */ }
        }
        if (merged) {
          saveLS('simlab_snapshots', state.snapshots);
          try { renderGameList(); renderTracking(); } catch (e3) {}
          console.log('[simlab] merged auto-locked snapshots for ' + merged + ' week(s)');
        }
      } catch (e) { /* no snapshots deployed yet */ }
    })();
    $('wk-run').addEventListener('click', runWeekSim);
    $('wk-search').addEventListener('input', renderWeekTable);
    $('wk-pos').addEventListener('change', renderWeekTable);
    $('wk-view').addEventListener('change', renderWeekTable);
    // GAME filter (2026-09-09): one game's players in every week view —
    // pair with "Median vs Lines" for that game's prop board vs the sim.
    fillGameSelect();
    wkSel.addEventListener('change', fillGameSelect);
    $('wk-game').addEventListener('change', renderWeekTable);
    $('sn-run').addEventListener('click', runSeasonSim);
    $('sn-search').addEventListener('input', renderSeasonTable);
    $('sn-pos').addEventListener('change', renderSeasonTable);
    $('sn-view').addEventListener('change', renderSeasonTable);
    $('sn-odds').addEventListener('change', renderSeasonTable);
    $('lg-load').addEventListener('click', function () { loadLeague($('lg-id').value.trim()); });
    $('lg-espn-load').addEventListener('click', function () { loadEspnLeague($('lg-espn-id').value.trim()); });
    $('lg-yahoo-load').addEventListener('click', function () { loadYahooLeague($('lg-yahoo-id').value.trim()); });
    $('lg-mff').addEventListener('click', loadMffLeagues);
    $('lg-mff-pick').addEventListener('change', function () {
      var l = state.mffLeagues && state.mffLeagues[+this.value];
      if (l) applyMffLeague(l);
    });
    $('lg-demo').addEventListener('click', loadDemoLeague);
    $('lg-run').addEventListener('click', runLeagueSim);
    $('lg-week').addEventListener('change', renderWeekMatchups);
    $('lg-week-view').addEventListener('change', function () { renderLeagueTable(); renderWeekMatchups(); });
    $('tr-a').addEventListener('change', function () { fillTradePlayers('a'); fillTradePicks('a'); });
    $('tr-b').addEventListener('change', function () { fillTradePlayers('b'); fillTradePicks('b'); });
    $('tr-run').addEventListener('click', analyzeTrade);
    $('tk-lock').addEventListener('click', function () { lockGames(unlockedGameKeys()); });
    $('tk-lock-sel').addEventListener('click', function () {
      var keys = Array.from(document.querySelectorAll('#tk-games input:checked')).map(function (c) { return c.value; });
      if (!keys.length) { $('tk-note').textContent = 'Check at least one game first.'; return; }
      lockGames(keys);
    });
    $('tk-score').addEventListener('click', scoreWeek);
    $('tk-export').addEventListener('click', exportTracking);
    tkSel.addEventListener('change', renderGameList);
    $('bb-file').addEventListener('change', importBBFile);
    $('bb-mff').addEventListener('click', loadFromMff);
    $('bb-run').addEventListener('click', runBBSim);
    $('bb-clear').addEventListener('click', clearBB);
    $('bb-user').value = String(loadLS('simlab_bb_user', '') || '');
    $('bb-user').addEventListener('change', onBBUserChange);
    $('bb-show').addEventListener('change', renderBBTable);
    $('bb-tourney').addEventListener('change', renderBBTable);
    if ($('bbf-file')) { // a cached older index.html has no OVERALL STANDINGS block
      $('bbf-file').addEventListener('change', importBBFieldFile);
      $('bbf-run').addEventListener('click', runBBFieldSim);
      $('bbf-find').addEventListener('click', bbfLookup);
      $('bbf-user').addEventListener('keydown', function (ev) { if (ev.key === 'Enter') bbfLookup(); });
      if ($('bbf-mine')) $('bbf-mine').addEventListener('change', bbfToggleMine);
      if ($('bbf-view')) $('bbf-view').addEventListener('change', bbfSetView);
      if ($('bbf-refresh')) {
        $('bbf-refresh').addEventListener('click', function () { if (state.bbField) { state.bbField.nowAt = 0; bbfRefreshNow(); } });
        setInterval(function () {
          if (!document.hidden && $('pane-bb') && $('pane-bb').classList.contains('on')) bbfMaybeRefresh();
        }, 60000);
      }
      if ($('bbf-forget')) {
        $('bbf-forget').addEventListener('click', bbfForget);
        bbfBootSaved();
      }
    }
    loadBBFromLS();
    renderGameList();
    renderTracking();
    renderPaceTab();
    renderZonesTab();
    renderNotesTab();
  });

  function showTab(name) {
    document.querySelectorAll('.tab').forEach(function (b) { b.classList.toggle('on', b.dataset.tab === name); });
    document.querySelectorAll('.pane').forEach(function (p) { p.classList.toggle('on', p.id === 'pane-' + name); });
    if (name === 'bb') { bbfAutoLoad(); bbfMaybeRefresh(); }
  }

  function currentScoring(sel) {
    return E.PRESETS[$(sel).value] || E.PRESETS.half;
  }

  // ---------------- BLOCKING RUNS ----------------
  // The sims are synchronous number-crunching — 100ms for a small week sim up
  // to a few seconds for 2000 season sims — and they hold the main thread the
  // whole time. Without a forced paint first, the click produced no visible
  // response at all and the page just looked hung. rAF + setTimeout(0)
  // guarantees one rendered frame (the note + the disabled button) before the
  // thread goes away, and the disable also stops an impatient second click
  // from queueing another full run.
  function runBlocking(btnId, noteId, msg, work) {
    var btn = $(btnId);
    btn.disabled = true;
    $(noteId).textContent = msg;
    // setTimeout, not requestAnimationFrame: rAF never fires while the tab
    // isn't rendering (backgrounded tab, hidden preview pane, headless), so
    // sims would hang at "Simulating…" until it became visible. A short
    // timeout still gives visible tabs a frame to paint the note first.
    setTimeout(function () {
      try { work(); } finally { btn.disabled = false; }
    }, 30);
  }

  // ---------------- SORTABLE TABLES ----------------
  // Click a column header to sort by it, click again to flip direction.
  // Sorting happens BEFORE the 400-row display cap, so "sort by Δ" surfaces
  // the extreme deltas from the whole pool, not just within the default view.
  // Column spec: { h: header, k: sort key (omit = not sortable), get: value
  // accessor, dir: first-click direction (default 'desc'), l: left-aligned }.
  function thRow(cols, ss) {
    return '<tr>' + cols.map(function (c) {
      var arrow = (ss.key && c.k === ss.key) ? (ss.dir === 'asc' ? ' ▲' : ' ▼') : '';
      return '<th' + (c.l ? ' class="l"' : '') +
        (c.k ? ' data-sort="' + c.k + '" style="cursor:pointer"' : '') + '>' + c.h + arrow + '</th>';
    }).join('') + '</tr>';
  }
  function applySort(rows, cols, ss) {
    var col = null;
    cols.forEach(function (c) { if (c.k && c.k === ss.key) col = c; });
    if (!col) return rows;
    var sorted = rows.slice().sort(function (a, b) {
      var va = col.get(a), vb = col.get(b);
      if (typeof va === 'string') {
        va = va.toLowerCase(); vb = String(vb).toLowerCase();
        return va < vb ? -1 : va > vb ? 1 : 0;
      }
      return va - vb;
    });
    if (ss.dir === 'desc') sorted.reverse();
    return sorted;
  }
  function wireSort(containerId, cols, ss, rerender) {
    document.querySelectorAll('#' + containerId + ' th[data-sort]').forEach(function (th) {
      th.addEventListener('click', function () {
        var k = th.dataset.sort, col = null;
        cols.forEach(function (c) { if (c.k === k) col = c; });
        if (ss.key === k) { ss.dir = ss.dir === 'desc' ? 'asc' : 'desc'; }
        else { ss.key = k; ss.dir = (col && col.dir) || 'desc'; }
        rerender();
      });
    });
  }

  // ---------------- WEEK SIM ----------------
  function runWeekSim() {
    var wk = +$('wk-week').value, sims = Math.max(10, Math.min(20000, +$('wk-sims').value || 100));
    runBlocking('wk-run', 'wk-note', 'Simulating week ' + wk + ' ' + sims + 'x…', function () {
      var t0 = performance.now();
      state.weekResults = E.simWeek({
        week: wk, sims: sims, scoring: currentScoring('wk-scoring'),
        schedule: state.schedule, players: state.players
      }).sort(function (a, b) { return b.mean - a.mean; });
      state.weekMeta = { week: wk, sims: sims, preset: $('wk-scoring').value, ms: performance.now() - t0 };
      $('wk-note').textContent = state.weekResults.length + ' players simmed ' + sims + 'x in ' +
        state.weekMeta.ms.toFixed(0) + 'ms (' + $('wk-scoring').value.toUpperCase() + ')';
      renderWeekTable();
    });
  }

  var WEEK_COLS = [
    { h: '#' },
    { h: 'Player', l: 1, k: 'player', dir: 'asc', get: function (r) { return r.player.name; } },
    { h: 'Pos', k: 'pos', dir: 'asc', get: function (r) { return r.player.pos; } },
    { h: 'Tm', k: 'tm', dir: 'asc', get: function (r) { return r.player.tm; } },
    { h: 'Opp', l: 1, k: 'opp', dir: 'asc', get: function (r) { return r.slot.opp; } },
    { h: 'Imp', k: 'imp', get: function (r) { return r.slot.implied; } },
    { h: 'Mean', k: 'mean', get: function (r) { return r.mean; } },
    { h: 'p10', k: 'p10', get: function (r) { return r.p10; } },
    { h: 'Median', k: 'p50', get: function (r) { return r.p50; } },
    { h: 'p90', k: 'p90', get: function (r) { return r.p90; } },
    { h: 'Boom', k: 'boom', get: function (r) { return r.boom; } },
    { h: 'Bust', k: 'bust', get: function (r) { return r.bust; } },
    { h: '&sigma; src' }
  ];
  // Week-view GAME filter: the schedule's games for the selected week, labelled
  // "AWAY @ HOME · total · favorite -pts". Keeps the current pick across week
  // changes when the same key exists (it won't — keys carry the week).
  function fillGameSelect() {
    var sel = $('wk-game');
    if (!sel || !state.schedule) return;
    var wk = +$('wk-week').value, cur = sel.value;
    var games = (state.schedule.byWeek[wk] || []).slice().sort(function (a, b) { return (a.away + a.home).localeCompare(b.away + b.home); });
    sel.innerHTML = '<option value="">All games</option>' + games.map(function (g) {
      var pts = Math.abs(g.spread), fav = g.spread < 0 ? g.home : g.away;
      return '<option value="' + esc(g.key) + '">' + esc(g.away + ' @ ' + g.home) + ' · ' + g.total + (pts ? ' · ' + fav + ' -' + pts : ' · PK') + '</option>';
    }).join('');
    sel.value = games.some(function (g) { return g.key === cur; }) ? cur : '';
  }
  function gameHeaderHtml(gk) {
    var wk = +$('wk-week').value;
    var g = (state.schedule.byWeek[wk] || []).filter(function (x) { return x.key === gk; })[0];
    if (!g) return '';
    var homeImp = (g.total - g.spread) / 2, awayImp = (g.total + g.spread) / 2;
    return '<p style="font-size:13px;margin:0 0 8px"><b>' + esc(g.away + ' @ ' + g.home) + '</b> · total <b>' + g.total +
      '</b> · spread ' + (g.spread > 0 ? '+' : '') + g.spread + ' (home) · implied ' + esc(g.away) + ' <b>' + awayImp.toFixed(1) +
      '</b> / ' + esc(g.home) + ' <b>' + homeImp.toFixed(1) + '</b>' +
      ($('wk-view').value === 'lines' ? '' : ' <span class="dim">— switch the view to "Median vs Lines" for this game\'s prop board vs the sim</span>') + '</p>';
  }
  function renderWeekTable() {
    if (!state.weekResults) return;
    var q = E.norm($('wk-search').value), pos = $('wk-pos').value, gk = $('wk-game') ? $('wk-game').value : '';
    var filtered = state.weekResults.filter(function (r) {
      if (pos !== 'ALL' && r.player.pos !== pos) return false;
      if (gk && (!r.slot || r.slot.gameKey !== gk)) return false;
      if (q && r.player.norm.indexOf(q) < 0) return false;
      return true;
    });
    var finish = function () { if (gk) $('wk-table').insertAdjacentHTML('afterbegin', gameHeaderHtml(gk)); };
    if ($('wk-view').value === 'stats') { renderStatLineView(filtered); finish(); return; }
    if ($('wk-view').value === 'compare') { renderCompareView(filtered.slice(0, 400)); finish(); return; }
    if ($('wk-view').value === 'lines') { renderLinesView(filtered.slice(0, 400)); finish(); return; }
    var ss = state.weekSort = state.weekSort || { key: null, dir: 'desc' };
    var rows = applySort(filtered, WEEK_COLS, ss).slice(0, 400);
    var html = '<table><thead>' + thRow(WEEK_COLS, ss) + '</thead><tbody>';
    rows.forEach(function (r, i) {
      var s = r.slot;
      html += '<tr><td>' + (i + 1) + '</td><td class="l"><b>' + esc(r.player.name) + '</b></td><td>' + r.player.pos +
        '</td><td>' + r.player.tm + '</td><td class="l">' + (s.home ? 'vs ' : '@ ') + s.opp +
        '</td><td>' + fmt(s.implied) + '</td><td><b>' + fmt(r.mean) + '</b></td><td class="dim">' + fmt(r.p10) +
        '</td><td>' + fmt(r.p50) + '</td><td class="dim">' + fmt(r.p90) +
        '</td><td>' + pctf(r.boom) + ' <span class="dim">≥' + r.boomAt + '</span>' +
        '</td><td>' + pctf(r.bust) + ' <span class="dim">&lt;' + r.bustAt + '</span>' +
        '</td><td class="dim">' + (r.player.sigmaSrc === 'history' ? '3yr' : (r.player.sigmaSrc === 'rookie-wide' ? 'rookie' : 'thin')) + '</td></tr>';
    });
    var bb = E.BOOM_BUST;
    $('wk-table').innerHTML = html + '</tbody></table>' +
      '<p class="dim" style="font-size:11px">Boom/bust thresholds by position: ' +
      Object.keys(bb).map(function (k) { return k + ' ≥' + bb[k].boom + ' / <' + bb[k].bust; }).join(' · ') + '</p>';
    wireSort('wk-table', WEEK_COLS, ss, renderWeekTable);
    finish();
  }

  // Median stat-line view: each component mean scaled by the player's own
  // p50/mean ratio from the sim, so the line is the MEDIAN week. The first
  // column re-scores that exact stat line under the active preset — the
  // stats shown always add up to the points shown.
  // Targets are ESTIMATED from projected receptions (Clay has no target
  // projections): RB 76% / WR 62% / TE 66% catch rate.
  var CATCH_RATE = { RB: 0.76, WR: 0.62, TE: 0.66 };
  function statCol(h, k) { return { h: h, k: k, get: function (o) { return o.m[k] || 0; } }; }
  var WEEK_STAT_COLS = [
    { h: '#' },
    { h: 'Med FPts', k: 'fpts', get: function (o) { return o.fpts; } },
    { h: 'Player', l: 1, k: 'player', dir: 'asc', get: function (o) { return o.r.player.name; } },
    { h: 'Pos', k: 'pos', dir: 'asc', get: function (o) { return o.r.player.pos; } },
    { h: 'Tm', k: 'tm', dir: 'asc', get: function (o) { return o.r.player.tm; } },
    { h: 'Opp', l: 1, k: 'opp', dir: 'asc', get: function (o) { return o.r.slot.opp; } },
    statCol('Pass Yd', 'py'), statCol('Pass TD', 'ptd'),
    statCol('Rush Yd', 'ry'), statCol('Rush TD', 'rtd'),
    statCol('Tgt*', 'tgt'), statCol('Rec', 'rec'),
    statCol('Rec Yd', 'rcy'), statCol('Rec TD', 'rctd'), statCol('Ru+Rec TD', 'rrtd')
  ];
  function renderStatLineView(rows) {
    var sc = E.PRESETS[(state.weekMeta && state.weekMeta.preset) || 'half'];
    var ss = state.weekStatSort = state.weekStatSort || { key: 'fpts', dir: 'desc' };
    var html = '<table><thead>' + thRow(WEEK_STAT_COLS, ss) + '</thead><tbody>';
    var out = rows.map(function (r) {
      var c = r.comps || {};
      var ratio = r.mean > 0.5 ? r.p50 / r.mean : 1;
      var m = {
        py: (c.py || 0) * ratio, ptd: (c.ptd || 0) * ratio,
        ry: (c.ry || 0) * ratio, rtd: (c.rtd || 0) * ratio,
        rec: (c.rec || 0) * ratio, rcy: (c.rcy || 0) * ratio, rctd: (c.rctd || 0) * ratio
      };
      var fpts = r.p50; // the true sim median — both views always agree
      if (r.player.pos !== 'K' && r.player.pos !== 'DST') {
        // Re-score the raw line, then scale the stats so they sum EXACTLY to
        // the median projection. (Clay's totals include INTs/fumbles we don't
        // itemize, so raw component sums run a touch high — mostly for QBs.)
        var raw = sc.pass_yd * m.py + sc.pass_td * m.ptd + sc.rush_yd * m.ry + sc.rush_td * m.rtd +
          sc.rec * m.rec + sc.rec_yd * m.rcy + sc.rec_td * m.rctd +
          (r.player.pos === 'TE' && sc.bonus_rec_te ? sc.bonus_rec_te * m.rec : 0);
        var f = raw > 0.1 ? r.p50 / raw : 1;
        Object.keys(m).forEach(function (k) { m[k] *= f; });
      }
      m.tgt = CATCH_RATE[r.player.pos] ? m.rec / CATCH_RATE[r.player.pos] : null;
      m.rrtd = m.rtd + m.rctd;
      return { r: r, m: m, fpts: fpts };
    });
    out = applySort(out, WEEK_STAT_COLS, ss).slice(0, 400);
    out.forEach(function (o, i) {
      var r = o.r, m = o.m, p = r.player, s = r.slot;
      function st(v, d, min) { return (v && v >= (min == null ? 0.05 : min)) ? v.toFixed(d == null ? 1 : d) : '<span class="dim">—</span>'; }
      html += '<tr><td>' + (i + 1) + '</td><td><b>' + o.fpts.toFixed(1) + '</b></td><td class="l"><b>' + esc(p.name) +
        '</b></td><td>' + p.pos + '</td><td>' + p.tm + '</td><td class="l">' + (s.home ? 'vs ' : '@ ') + s.opp + '</td>' +
        '<td>' + st(m.py, 0, 1) + '</td><td>' + st(m.ptd, 2) + '</td>' +
        '<td>' + st(m.ry, 1, 0.5) + '</td><td>' + st(m.rtd, 2) + '</td>' +
        '<td>' + (m.tgt ? st(m.tgt, 1) : '<span class="dim">—</span>') + '</td><td>' + st(m.rec, 1) + '</td>' +
        '<td>' + st(m.rcy, 1, 0.5) + '</td><td>' + st(m.rctd, 2) + '</td>' +
        '<td>' + ((p.pos !== 'QB' && p.pos !== 'K' && p.pos !== 'DST') ? st(m.rrtd, 2) : '<span class="dim">—</span>') + '</td></tr>';
    });
    $('wk-table').innerHTML = html + '</tbody></table>' +
      '<p class="dim" style="font-size:11px">* Targets estimated from projected receptions (RB 76% / WR 62% / TE 66% catch rate) — Clay does not publish target projections. ' +
      'Med FPts IS the sim median from the outcomes view; the stat line is scaled so it re-scores to exactly that number ' +
      '(QB yardage runs ~3-5% under raw pace because INTs are absorbed into the line rather than itemized). Click a column header to sort.</p>';
    wireSort('wk-table', WEEK_STAT_COLS, ss, renderWeekTable);
  }

  // Clay vs JS Weekly comparison — same environment factors, different
  // baseline (Clay projected role vs 3-yr actual per-game production).
  function renderCompareView(rows) {
    var both = rows.filter(function (r) { return r.jsProj != null; });
    var diffs = both.map(function (r) { return Math.abs(r.proj - r.jsProj); }).sort(function (a, b) { return a - b; });
    var medAbs = diffs.length ? diffs[Math.floor(diffs.length / 2)] : 0;
    var within2 = both.length ? both.filter(function (r) { return Math.abs(r.proj - r.jsProj) <= 2; }).length / both.length : 0;
    var sorted = rows.slice().sort(function (a, b) {
      var da = a.jsProj != null ? Math.abs(a.proj - a.jsProj) : -1;
      var db = b.jsProj != null ? Math.abs(b.proj - b.jsProj) : -1;
      return db - da;
    });
    var html = '<p class="dim" style="font-size:12px"><b>' + both.length + '</b> players have both models · median |Δ| <b>' +
      medAbs.toFixed(1) + '</b> pts · within 2 pts of each other: <b>' + pctf(within2) + '</b> · sorted by biggest disagreement</p>' +
      '<table><thead><tr><th>#</th><th class="l">Player</th><th>Pos</th><th>Tm</th><th class="l">Opp</th>' +
      '<th>Clay μ</th><th>JS μ</th><th>Δ (JS−Clay)</th><th class="l">JS says</th><th>Hist gms</th></tr></thead><tbody>';
    sorted.slice(0, 300).forEach(function (r, i) {
      var p = r.player, s = r.slot;
      var js = r.jsProj;
      var d = js != null ? js - r.proj : null;
      var col = d == null ? 'var(--dim)' : (d > 1.5 ? 'var(--acc)' : (d < -1.5 ? '#f85149' : 'var(--tx)'));
      var verdict = js == null ? 'no history — Clay only' :
        (d > 1.5 ? 'history says MORE' : (d < -1.5 ? 'history says LESS' : 'models agree'));
      html += '<tr><td>' + (i + 1) + '</td><td class="l"><b>' + esc(p.name) + '</b></td><td>' + p.pos +
        '</td><td>' + p.tm + '</td><td class="l">' + (s.home ? 'vs ' : '@ ') + s.opp +
        '</td><td>' + fmt(r.proj) + '</td><td>' + (js != null ? fmt(js) : '—') +
        '</td><td><b style="color:' + col + '">' + (d != null ? (d > 0 ? '+' : '') + d.toFixed(1) : '—') + '</b>' +
        '</td><td class="l dim">' + verdict + '</td><td class="dim">' + (p.histGames || '—') + '</td></tr>';
    });
    $('wk-table').innerHTML = html + '</tbody></table>' +
      '<p class="dim" style="font-size:11px">Clay μ = Clay projected role ÷ games × environment. JS μ = the IN-SEASON model: ' +
      'Clay prior shrunk toward actual 2026 PPG (prior worth ~5 games of evidence), opponent adj = actual fantasy points ' +
      'allowed per game by position (blended over Clay unit grades as each defense\'s sample grows), plus the shared Vegas ' +
      'and snap-trend layers. PRESEASON THE MODELS ARE IDENTICAL by design — the 2021-25 backtest showed preseason history ' +
      'blends lose to Clay alone. Divergence starts Week 2 and grows as the season outweighs the summer guide.</p>';
  }

  // Median vs Lines: our median stat projections against the books' weekly
  // prop lines, sorted by biggest discrepancy — one row per player-stat.
  // Both sides are medians, so this is the apples-to-apples comparison.
  // floor = normalization denominator so tiny lines don't produce fake 1000%
  // edges; minLine drops novelty micro-lines (0.5-yd WR rush props etc.)
  var LINE_STATS = {
    py:   { label: 'Pass Yd',   floor: 60,  minLine: 100 },
    ry:   { label: 'Rush Yd',   floor: 15,  minLine: 8 },
    rcy:  { label: 'Rec Yd',    floor: 15,  minLine: 8 },
    ptd:  { label: 'Pass TD',   floor: 1,   minLine: 0 },
    rrtd: { label: 'Ru+Rec TD', floor: 0.5, minLine: 0 },
    fgm:  { label: 'FG Made',   floor: 1,   minLine: 0.5 }
  };
  var LINES_COLS = [
    { h: '#', k: 'disc', get: function (o) { return o.key; } }, // = the default normalized-discrepancy order
    { h: 'Player', l: 1, k: 'player', dir: 'asc', get: function (o) { return o.r.player.name; } },
    { h: 'Pos', k: 'pos', dir: 'asc', get: function (o) { return o.r.player.pos; } },
    { h: 'Opp', l: 1, k: 'opp', dir: 'asc', get: function (o) { return o.r.slot.opp; } },
    { h: 'Stat', l: 1, k: 'stat', dir: 'asc', get: function (o) { return o.isProb ? 'Anytime TD' : LINE_STATS[o.stat].label; } },
    { h: 'Ours', k: 'ours', get: function (o) { return o.ours; } },
    { h: 'Line', k: 'line', get: function (o) { return o.line; } },
    { h: 'Edge', k: 'edge', get: function (o) { return o.edge; } },
    { h: 'Lean', k: 'lean', get: function (o) { return o.ours > o.line ? 1 : 0; } },
    { h: 'Books', k: 'books', get: function (o) { return o.books; } }
  ];
  function renderLinesView(rows) {
    var wk = state.weekMeta ? state.weekMeta.week : +$('wk-week').value;
    var props = (window.BETTING_2026 && window.BETTING_2026.weeklyProps && window.BETTING_2026.weeklyProps[String(wk)]) || {};
    var propByNorm = {};
    Object.keys(props).forEach(function (nm) { propByNorm[E.norm(nm)] = props[nm]; });
    if (!Object.keys(propByNorm).length) {
      $('wk-table').innerHTML = '<p class="dim">No weekly prop lines for week ' + wk +
        ' yet — they land in betting_lines_2026.js when pull_betting_lines.py --weekly-props runs (auto pregame in-season).</p>';
      return;
    }
    var out = [];
    rows.forEach(function (r) {
      var lines = propByNorm[r.player.norm];
      if (!lines || !r.comps) return;
      // CLEAN comps at face value (2026-10-07): W1-4 locks showed actual/line
      // 1.03-1.06 on every stat but rec yards, i.e. the books already shade
      // the median-vs-mean skew, so medianizing our mean with gammaMedRatio
      // (x0.88 median) made the model read LOW on every line. Mirrors the
      // engine's PROP_LINE_SCALE change; window.SIM_PROP_GAMMA_RATIO = true
      // restores the old read here too. Still never the sim run's p50/mean
      // (that carries the anchor's level).
      var ratio = window.SIM_PROP_GAMMA_RATIO === true ? E.gammaMedRatio(r.player) : 1;
      Object.keys(LINE_STATS).forEach(function (k) {
        if (r.comps[k] == null) return;
        var books = [];
        ['UD', 'PP', 'DK', 'FD', 'MGM'].forEach(function (b) {
          if (lines[b] && typeof lines[b][k] === 'number') books.push(lines[b][k]);
        });
        if (!books.length) return;
        books.sort(function (a, b) { return a - b; });
        var line = books[Math.floor(books.length / 2)];
        var cfg = LINE_STATS[k];
        if (line <= 0 || line < cfg.minLine) return;
        if (k === 'rrtd') return; // handled below via anytime-TD odds
        var ours = r.comps[k] * ratio;
        var edge = (ours - line) / line;
        var key = Math.abs(ours - line) / Math.max(line, cfg.floor);
        out.push({ r: r, stat: k, ours: ours, line: line, edge: edge, key: key, books: books.length });
      });
      // Anytime TD: books price this via ODDS, not the 0.5 line — convert
      // american odds -> implied probability, vs our P(TD) = 1 - e^(-lambda)
      // with lambda = our median rush+rec TD rate. Fantasy-relevant players only.
      if (r.comps.rrtd != null && r.mean >= 6) {
        var odds = [];
        ['UD', 'DK', 'PP'].forEach(function (b) {
          if (lines[b] && typeof lines[b].atd === 'number') odds.push(lines[b].atd);
        });
        if (odds.length) {
          var probs = odds.map(function (o) { return o < 0 ? -o / (-o + 100) : 100 / (o + 100); }).sort(function (a, b) { return a - b; });
          var pBook = probs[Math.floor(probs.length / 2)];
          var pOurs = 1 - Math.exp(-r.comps.rrtd); // Poisson on the Vegas-adjusted mean TD rate
          out.push({ r: r, stat: 'atd', ours: pOurs, line: pBook, edge: pOurs - pBook,
                     key: 0, books: odds.length, isProb: true });
        }
      }
    });
    // Center anytime-TD edges on the slate-wide median edge — that removes
    // book juice + any systematic model lean, so the sort surfaces players
    // whose TD odds disagree with us MORE than the rest of the slate does.
    var atdEdges = out.filter(function (o) { return o.isProb; }).map(function (o) { return o.edge; }).sort(function (a, b) { return a - b; });
    var medAtd = atdEdges.length ? atdEdges[Math.floor(atdEdges.length / 2)] : 0;
    out.forEach(function (o) { if (o.isProb) o.key = Math.abs(o.edge - medAtd) / 0.30; });
    out.sort(function (a, b) { return b.key - a.key; }); // default: biggest normalized discrepancy
    var ss = state.weekLinesSort = state.weekLinesSort || { key: null, dir: 'desc' };
    out = applySort(out, LINES_COLS, ss);
    var html = '<p class="dim" style="font-size:12px"><b>' + out.length + '</b> player-stat lines compared for week ' + wk +
      (ss.key ? '' : ' · sorted by biggest % discrepancy') + ' · lines at face value vs our clean stat mean · click a column header to sort (# = back to the discrepancy order)</p>' +
      '<table><thead>' + thRow(LINES_COLS, ss) + '</thead><tbody>';
    out.slice(0, 250).forEach(function (o, i) {
      var p = o.r.player, s = o.r.slot;
      var over = o.ours > o.line;
      var col = over ? 'var(--acc)' : '#f85149';
      var oursTxt, lineTxt, edgeTxt, statTxt;
      if (o.isProb) {
        statTxt = 'Anytime TD';
        oursTxt = (100 * o.ours).toFixed(0) + '%';
        lineTxt = (100 * o.line).toFixed(0) + '%';
        edgeTxt = (o.edge >= 0 ? '+' : '') + (100 * o.edge).toFixed(0) + 'pp';
      } else {
        statTxt = LINE_STATS[o.stat].label;
        oursTxt = o.ours.toFixed(1);
        lineTxt = String(o.line);
        edgeTxt = ((o.ours - o.line) >= 0 ? '+' : '') + (o.ours - o.line).toFixed(1) +
          ' (' + (o.edge >= 0 ? '+' : '') + (100 * o.edge).toFixed(0) + '%)';
      }
      html += '<tr><td>' + (i + 1) + '</td><td class="l"><b>' + esc(p.name) + '</b></td><td>' + p.pos +
        '</td><td class="l">' + (s.home ? 'vs ' : '@ ') + s.opp + '</td><td class="l">' + statTxt +
        '</td><td>' + oursTxt + '</td><td>' + lineTxt +
        '</td><td><b style="color:' + col + '">' + edgeTxt + '</b>' +
        '</td><td style="color:' + col + '"><b>' + (over ? 'OVER' : 'UNDER') + '</b></td><td class="dim">' + o.books + '</td></tr>';
    });
    $('wk-table').innerHTML = html + '</tbody></table>' +
      '<p class="dim" style="font-size:11px">Line = median across UD/PP/DK, at face value. Ours = CLEAN model stat mean (unaffected by the prop anchor; no median ' +
      'scaling since 2026-10-07 — W1-4 showed the books\' lines already sit at the mean, actual/line 1.03-1.06 on all but rec yards). Anytime TD compares PROBABILITIES: the books\' odds converted to implied % (juice included — books ' +
      'run ~5-8% hot on these) vs our Poisson P(≥1 TD) from the median rush+rec TD rate, so a small UNDER lean there is just vig. ' +
      'Big edges are EITHER a potential prop lean OR a model miss — the weekly SCORE grading tells you which over time.</p>';
    wireSort('wk-table', LINES_COLS, ss, renderWeekTable);
  }

  // ---------------- SEASON SIM ----------------
  // Full-season (or any week range) outcome per player: season-total
  // distribution + positional finish odds, ranked within each sim.
  function runSeasonSim() {
    var from = +$('sn-from').value, to = +$('sn-to').value;
    if (to < from) { var t = from; from = to; to = t; $('sn-from').value = from; $('sn-to').value = to; }
    var sims = Math.max(50, Math.min(2000, +$('sn-sims').value || 300));
    var label = (from === 1 && to === 18) ? 'full season' : 'weeks ' + from + '–' + to;
    runBlocking('sn-run', 'sn-note', 'Simulating ' + label + ' ' + sims + 'x…', function () {
      var t0 = performance.now();
      state.seasonResults = E.simSeason({
        sims: sims, scoring: currentScoring('sn-scoring'),
        schedule: state.schedule, players: state.players,
        weekFrom: from, weekTo: to
      });
      state.seasonMeta = { from: from, to: to, sims: sims, preset: $('sn-scoring').value, ms: performance.now() - t0 };
      // games already played are banked at their real results, never re-simulated (data/sim_actuals_2026.js)
      var AC = (window.SIM_BANK_PLAYED !== false && window.SIM_ACTUALS_2026) || null, bankTxt = '';
      if (AC && AC.done) {
        var bw = Object.keys(AC.done).map(Number).filter(function (w) { return w >= from && w <= to; }).sort(function (a, b) { return a - b; });
        var full = bw.filter(function (w) { return AC.done[w].length >= ((state.schedule.byWeek[w] || []).length * 2); });
        var part = bw.filter(function (w) { return full.indexOf(w) < 0; });
        if (bw.length) bankTxt = ' Played games use real results, not sims: ' +
          (full.length ? 'week' + (full.length > 1 ? 's ' + full[0] + '–' + full[full.length - 1] : ' ' + full[0]) : '') +
          (part.length ? (full.length ? ' + ' : '') + part.map(function (w) { return 'week ' + w + ' (' + AC.done[w].join('/') + ')'; }).join(', ') : '') + '.';
      }
      $('sn-note').textContent = state.seasonResults.length + ' players × ' + label + ' simmed ' + sims +
        'x in ' + state.seasonMeta.ms.toFixed(0) + 'ms (' + $('sn-scoring').value.toUpperCase() + ').' + bankTxt + ' Click a row for the week-by-week path.';
      $('sn-detail').innerHTML = '';
      renderSeasonTable();
    });
  }

  // median from a {value: count} distribution (finish ranks, win totals,
  // league places). The mean of these is dragged toward the tail by wreck
  // seasons; the median is the "typical season" and pairs with the Median
  // points column — both are shown side by side.
  function medianFromCounts(counts, n) {
    var half = n / 2, cum = 0;
    var keys = Object.keys(counts).map(Number).sort(function (a, b) { return a - b; });
    for (var i = 0; i < keys.length; i++) {
      cum += counts[keys[i]];
      if (cum >= half) return keys[i];
    }
    return keys.length ? keys[keys.length - 1] : 0;
  }
  function medianRank(r) {
    return medianFromCounts(r.rankCounts, r.sims);
  }

  function seasonClayRef(r) { return r.clayPts * r.games / 17; }
  var SEASON_COLS = [
    { h: '#' },
    { h: 'Player', l: 1, k: 'player', dir: 'asc', get: function (r) { return r.player.name; } },
    { h: 'Pos', k: 'pos', dir: 'asc', get: function (r) { return r.player.pos; } },
    { h: 'Tm', k: 'tm', dir: 'asc', get: function (r) { return r.player.tm; } },
    { h: 'Gms', k: 'gms', get: function (r) { return r.games; } },
    { h: 'Clay', k: 'clay', get: seasonClayRef },
    { h: 'Mean', k: 'mean', get: function (r) { return r.mean; } },
    { h: '&Delta;', k: 'delta', get: function (r) { return r.mean - seasonClayRef(r); } },
    { h: 'p10', k: 'p10', get: function (r) { return r.p10; } },
    { h: 'Median', k: 'p50', get: function (r) { return r.p50; } },
    { h: 'p90', k: 'p90', get: function (r) { return r.p90; } },
    { h: 'Avg fin', k: 'avgfin', dir: 'asc', get: function (r) { return r.avgRank; } },
    { h: 'Med fin', k: 'medfin', dir: 'asc', get: function (r) { return medianRank(r); } },
    { h: '#1', k: 'top1', get: function (r) { return r.top1; } },
    { h: 'Top 3', k: 'top3', get: function (r) { return r.top3; } },
    { h: 'Top 12', k: 'top12', get: function (r) { return r.top12; } },
    { h: 'Top 24', k: 'top24', get: function (r) { return r.top24; } }
  ];
  function renderSeasonTable() {
    if (!state.seasonResults) return;
    var q = E.norm($('sn-search').value), pos = $('sn-pos').value;
    var filtered = state.seasonResults.filter(function (r) {
      if (pos !== 'ALL' && r.player.pos !== pos) return false;
      if (q && r.player.norm.indexOf(q) < 0) return false;
      return true;
    });
    if ($('sn-view').value === 'stats') { renderSeasonStatView(filtered); return; }
    var book = $('sn-odds').value === 'book';
    var odds = book ? mlBook : pctf; // finish odds as futures prices vs raw sim %
    var ss = state.seasonSort = state.seasonSort || { key: null, dir: 'desc' };
    var rows = applySort(filtered, SEASON_COLS, ss).slice(0, 400);
    var html = '<table><thead>' + thRow(SEASON_COLS, ss) + '</thead><tbody>';
    rows.forEach(function (r, i) {
      var p = r.player;
      // Clay pace prorated to the games this player has IN the chosen range,
      // so Δ reads the same for a 3-week stretch as for the full season.
      var clayRef = r.clayPts * r.games / 17;
      var d = r.mean - clayRef;
      var dCol = Math.abs(d) < Math.max(1, 3 * r.games / 17) ? 'var(--dim)' : (d > 0 ? 'var(--acc)' : '#f85149');
      html += '<tr data-i="' + state.seasonResults.indexOf(r) + '" style="cursor:pointer"><td>' + (i + 1) +
        '</td><td class="l"><b>' + esc(p.name) + '</b></td><td>' + p.pos + '</td><td>' + p.tm +
        '</td><td class="dim">' + r.games + '</td><td class="dim">' + fmt(clayRef, 0) +
        '</td><td><b>' + fmt(r.mean, 0) + '</b></td><td style="color:' + dCol + '">' + (d >= 0 ? '+' : '') + d.toFixed(0) +
        '</td><td class="dim">' + fmt(r.p10, 0) + '</td><td>' + fmt(r.p50, 0) + '</td><td class="dim">' + fmt(r.p90, 0) +
        '</td><td class="dim">' + p.pos + Math.round(r.avgRank) + '</td><td><b>' + p.pos + medianRank(r) + '</b>' +
        '</td><td>' + odds(r.top1) + '</td><td>' + odds(r.top3) +
        '</td><td><b>' + odds(r.top12) + '</b></td><td>' + odds(r.top24) + '</td></tr>';
    });
    $('sn-table').innerHTML = html + '</tbody></table>' +
      '<p class="dim" style="font-size:11px">Clay = season points rescored to this preset, prorated to the games the player ' +
      'has in the chosen range (season/17 &times; gms). &Delta; = sim mean vs that naive pace — what the schedule layer adds or removes ' +
      'in THESE weeks (Vegas implied totals, positional defense, QB/injury windows, ramps). ' +
      'Finish odds are positional ranks WITHIN each simulated season, so correlated booms/busts are priced in. Click a column header to sort.' +
      (book ? ' #1/Top-3/Top-12/Top-24 are futures-style prices (~20-cent vig + board rounding; — = never happened in the sims).' : '') + '</p>';
    document.querySelectorAll('#sn-table tbody tr').forEach(function (tr) {
      tr.addEventListener('click', function () { renderSeasonDetail(+tr.dataset.i); });
    });
    wireSort('sn-table', SEASON_COLS, ss, renderSeasonTable);
  }

  // Median season stat line: per-week component means summed over the range,
  // scaled by each player's p50/mean ratio and re-scored so the stats add up
  // to EXACTLY the sim's median season points (same recipe as the weekly
  // "Median stat line" view). Targets estimated via catch rates.
  var SEASON_STAT_COLS = [
    { h: '#' },
    { h: 'Med FPts', k: 'fpts', get: function (o) { return o.r.p50; } },
    { h: 'FPPG', k: 'fppg', get: function (o) { return o.r.p50 / o.r.games; } },
    { h: 'Player', l: 1, k: 'player', dir: 'asc', get: function (o) { return o.r.player.name; } },
    { h: 'Pos', k: 'pos', dir: 'asc', get: function (o) { return o.r.player.pos; } },
    { h: 'Tm', k: 'tm', dir: 'asc', get: function (o) { return o.r.player.tm; } },
    { h: 'Gms', k: 'gms', get: function (o) { return o.r.games; } },
    statCol('Pass Yd', 'py'), statCol('Pass TD', 'ptd'),
    statCol('Rush Yd', 'ry'), statCol('Rush TD', 'rtd'),
    statCol('Tgt*', 'tgt'), statCol('Rec', 'rec'),
    statCol('Rec Yd', 'rcy'), statCol('Rec TD', 'rctd'), statCol('Ru+Rec TD', 'rrtd')
  ];
  function renderSeasonStatView(rows) {
    var sc = E.PRESETS[(state.seasonMeta && state.seasonMeta.preset) || 'half'];
    var ss = state.seasonStatSort = state.seasonStatSort || { key: 'fpts', dir: 'desc' };
    var html = '<table><thead>' + thRow(SEASON_STAT_COLS, ss) + '</thead><tbody>';
    var out = rows.map(function (r) {
      var tot = {};
      r.weeks.forEach(function (x) {
        var c = x.wp.comps || {};
        Object.keys(c).forEach(function (k) { tot[k] = (tot[k] || 0) + c[k]; });
      });
      // games already played are banked at their real points (engine simSeason): only the part still to play is
      // a projection, so it is scaled to the median of THAT part and the real stat lines are added on top
      var bk = r.banked || 0, simMean = r.mean - bk, simMed = r.p50 - bk;
      var ratio = simMean > 1 ? simMed / simMean : 1;
      var m = {
        py: (tot.py || 0) * ratio, ptd: (tot.ptd || 0) * ratio,
        ry: (tot.ry || 0) * ratio, rtd: (tot.rtd || 0) * ratio,
        rec: (tot.rec || 0) * ratio, rcy: (tot.rcy || 0) * ratio, rctd: (tot.rctd || 0) * ratio
      };
      var p = r.player;
      if (p.pos !== 'K' && p.pos !== 'DST') {
        var raw = sc.pass_yd * m.py + sc.pass_td * m.ptd + sc.rush_yd * m.ry + sc.rush_td * m.rtd +
          sc.rec * m.rec + sc.rec_yd * m.rcy + sc.rec_td * m.rctd +
          (p.pos === 'TE' && sc.bonus_rec_te ? sc.bonus_rec_te * m.rec : 0);
        var f = raw > 1 ? simMed / raw : 1;
        Object.keys(m).forEach(function (k) { m[k] *= f; });
      }
      (r.bankedWeeks || []).forEach(function (b) {   // row = [pts_std, rec, pass_td, pass_yd, rush_yd, rush_td, rec_yd, rec_td]
        var a = b.row; if (!a) return;
        m.rec += a[1]; m.ptd += a[2]; m.py += a[3]; m.ry += a[4]; m.rtd += a[5]; m.rcy += a[6]; m.rctd += a[7];
      });
      m.tgt = CATCH_RATE[p.pos] ? m.rec / CATCH_RATE[p.pos] : null;
      m.rrtd = m.rtd + m.rctd;
      return { r: r, m: m };
    });
    out = applySort(out, SEASON_STAT_COLS, ss).slice(0, 400);
    out.forEach(function (o, i) {
      var r = o.r, m = o.m, p = r.player;
      function st(v, d, min) { return (v && v >= (min == null ? 0.4 : min)) ? v.toFixed(d == null ? 0 : d) : '<span class="dim">—</span>'; }
      html += '<tr><td>' + (i + 1) + '</td><td><b>' + r.p50.toFixed(0) + '</b></td><td><b>' + (r.p50 / r.games).toFixed(1) +
        '</b></td><td class="l"><b>' + esc(p.name) + '</b></td><td>' + p.pos + '</td><td>' + p.tm +
        '</td><td class="dim">' + r.games + '</td>' +
        '<td>' + st(m.py, 0, 20) + '</td><td>' + st(m.ptd, 1, 0.3) + '</td>' +
        '<td>' + st(m.ry, 0, 10) + '</td><td>' + st(m.rtd, 1, 0.2) + '</td>' +
        '<td>' + (m.tgt ? st(m.tgt, 0, 2) : '<span class="dim">—</span>') + '</td><td>' + st(m.rec, 0, 2) + '</td>' +
        '<td>' + st(m.rcy, 0, 10) + '</td><td>' + st(m.rctd, 1, 0.2) + '</td>' +
        '<td>' + ((p.pos !== 'QB' && p.pos !== 'K' && p.pos !== 'DST') ? st(m.rrtd, 1, 0.2) : '<span class="dim">—</span>') + '</td></tr>';
    });
    $('sn-table').innerHTML = html + '</tbody></table>' +
      '<p class="dim" style="font-size:11px">Med FPts IS the sim median from the outcomes view; the stat line is the ' +
      'range\'s weekly component means (Vegas/defense/windows included) scaled so it re-scores to exactly that number under ' +
      'the active preset. FPPG = median points ÷ scheduled games in the range — the injury layer means actual games played ' +
      'can be fewer, so true per-played-game pace runs a touch higher. * Targets estimated from receptions ' +
      '(RB 76% / WR 62% / TE 66% catch rate — Clay publishes no target projections). K/DST show points only. Click a column header to sort.</p>';
    document.querySelectorAll('#sn-table tbody tr').forEach(function (tr, i) {
      tr.style.cursor = 'pointer';
      tr.addEventListener('click', function () {
        var r = out[i] && out[i].r;
        if (r) renderSeasonDetail(state.seasonResults.indexOf(r));
      });
    });
    wireSort('sn-table', SEASON_STAT_COLS, ss, renderSeasonTable);
  }

  // Week-by-week projected path + finish distribution for one player.
  function renderSeasonDetail(idx) {
    var r = state.seasonResults && state.seasonResults[idx];
    if (!r) return;
    var p = r.player;
    var html = '<h3>' + esc(p.name) + ' (' + p.pos + ', ' + p.tm + ') — week-by-week path</h3>' +
      '<table style="max-width:640px"><thead><tr><th>Wk</th><th class="l">Opp</th><th>Implied</th>' +
      '<th>Env mult</th><th>Proj mean</th></tr></thead><tbody>';
    (r.bankedWeeks || []).forEach(function (b) {   // already played: the real score, not a projection
      var s0 = state.schedule.byTeam[p.tm] && state.schedule.byTeam[p.tm][b.wk];
      html += '<tr><td>' + b.wk + '</td><td class="l">' + (s0 ? (s0.home ? 'vs ' : '@ ') + s0.opp : '') +
        '</td><td class="dim" colspan="2">played' + (b.row ? '' : ' — no stat line (did not play)') +
        '</td><td><b>' + fmt(b.pts) + '</b> <span class="dim">actual</span></td></tr>';
    });
    r.weeks.forEach(function (x) {
      var s = x.wp.slot;
      html += '<tr><td>' + x.wk + '</td><td class="l">' + (s.home ? 'vs ' : '@ ') + s.opp +
        '</td><td>' + fmt(s.implied) + '</td><td class="dim">' + fmt(x.wp.mult, 2) +
        '</td><td><b>' + fmt(x.wp.mean) + '</b></td></tr>';
    });
    html += '</tbody></table>';
    // finish distribution: first 12 ranks + everything after
    var sims = r.sims, tail = 0, modeP = 0;
    for (var rk = 13; rk <= 500; rk++) tail += r.rankCounts[rk] || 0;
    for (var rk2 = 1; rk2 <= 12; rk2++) modeP = Math.max(modeP, (r.rankCounts[rk2] || 0) / sims);
    modeP = Math.max(modeP, tail / sims);
    html += '<h3>Positional finish distribution (' + p.pos + ')</h3>' +
      '<table style="max-width:820px"><thead><tr>';
    for (rk2 = 1; rk2 <= 12; rk2++) html += '<th>' + p.pos + rk2 + '</th>';
    html += '<th>13+</th></tr></thead><tbody><tr>';
    for (rk2 = 1; rk2 <= 12; rk2++) {
      var pp = (r.rankCounts[rk2] || 0) / sims;
      html += '<td' + (pp === modeP && pp > 0 ? ' style="color:var(--acc);font-weight:700"' : (pp < 0.02 ? ' class="dim"' : '')) + '>' +
        (pp > 0 ? (100 * pp).toFixed(1) + '%' : '—') + '</td>';
    }
    var tp = tail / sims;
    html += '<td' + (tp === modeP && tp > 0 ? ' style="color:var(--acc);font-weight:700"' : (tp < 0.02 ? ' class="dim"' : '')) + '>' +
      (tp > 0 ? (100 * tp).toFixed(1) + '%' : '—') + '</td>';
    html += '</tr></tbody></table>' +
      '<p class="dim" style="font-size:11px">Proj mean is the pre-sample weekly mean (Vegas × defense × windows/ramps/snap trend). ' +
      'Missing weeks = bye or outside the player\'s starter/injury window.</p>';
    $('sn-detail').innerHTML = html;
    $('sn-detail').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // ---------------- SLEEPER LEAGUE ----------------
  async function sleeper(path) {
    var r = await fetch(API + path);
    if (!r.ok) throw new Error('Sleeper API ' + r.status + ' on ' + path);
    return r.json();
  }

  // Injury availability from Sleeper's player DB (~5MB, so trimmed to our
  // player pool and cached 12h in localStorage). DEFINITIVE statuses only —
  // Questionable/Doubtful are ignored on purpose, and camp PUP (preseason) is
  // NOT an exclusion since most of those players are activated by Week 1:
  //   'sus'/'ir' -> excluded always
  //   'pup'      -> excluded only once the regular season has started (4-game min)
  //   'out'      -> sit for the upcoming week, regular season only
  async function getInjuryMap() {
    var cache = loadLS('simlab_injuries_v2', null);
    if (cache && cache.at && (Date.now() - cache.at) < 12 * 3600 * 1000) return cache.by;
    var all = await (await fetch(API + '/players/nfl')).json();
    var by = {};
    Object.keys(state.players.bySid).forEach(function (sid) {
      var rec = all[sid];
      if (!rec) return;
      var inj = rec.injury_status || '', st = rec.status || '';
      if (/Suspended/i.test(st) || /^Sus$/i.test(inj)) by[sid] = 'sus';
      else if (/Injured Reserve|Non Football/i.test(st) || /^(IR|NFI|DNR|NA|COV)$/i.test(inj)) by[sid] = 'ir';
      else if (/PUP/i.test(st) || /^PUP$/i.test(inj)) by[sid] = 'pup';
      else if (/^Out$/i.test(inj)) by[sid] = 'out';
    });
    saveLS('simlab_injuries_v2', { at: Date.now(), by: by });
    return by;
  }
  // Collapse granular statuses to what the engine uses ('ir' = season-long,
  // 'out' = this week), given whether the regular season is underway.
  function effectiveUnavailable(raw, inSeason) {
    var eff = {};
    var ov = window.IN_SEASON_OUT_OVERRIDES || {};
    Object.keys(raw).forEach(function (sid) {
      var c = raw[sid];
      var p = state.players.bySid[sid];
      // PUP players with an injury-start window (Clay projects a return)
      // are governed by the window, not blanket-excluded.
      var windowed = p && p.qbWindow && p.qbWindow.src === 'injury-start';
      // 2026-09-27: a reported timeline in IN_SEASON_OUT_OVERRIDES ([from,to])
      // governs the season sim too — the injury layer zeroes exactly those
      // weeks via weeklyProjection, so a Sleeper IR tag must not wipe the
      // rest of the season for a player with a known return. 0/null = healthy.
      if (p && Object.prototype.hasOwnProperty.call(ov, p.name)) return;
      // 2026-10-01: same for a timeline read off the news feed or a season-ending diagnosis (src news* / dx-*) —
      // the injury layer already zeroes exactly those weeks, a blanket season exclusion would overstate it.
      var injSt = E.injuryState ? E.injuryState() : null;
      if (p && injSt && injSt.map && injSt.map[p.norm] && /^(news|dx-)/.test(injSt.map[p.norm].src || '')) return;
      if (c === 'ir' || c === 'sus') eff[sid] = 'ir';
      else if (c === 'pup' && inSeason && !windowed) eff[sid] = 'ir';
      else if (c === 'out' && inSeason) eff[sid] = 'out';
    });
    return eff;
  }

  async function loadLeague(lid) {
    if (!lid) { $('lg-note').textContent = 'Paste a Sleeper league ID (the number in the league URL).'; return; }
    $('lg-note').textContent = 'Loading league…';
    try {
      var league = await sleeper('/league/' + lid);
      var users = await sleeper('/league/' + lid + '/users');
      var rosters = await sleeper('/league/' + lid + '/rosters');
      var nflState = await sleeper('/state/nfl').catch(function () { return null; });
      var tradedPicks = await sleeper('/league/' + lid + '/traded_picks').catch(function () { return []; });
      // mid-season: carry real records and only sim the weeks still to play
      var curWeek = (nflState && nflState.season_type === 'regular' && nflState.week > 0) ? nflState.week : 1;
      var userById = {};
      users.forEach(function (u) { userById[u.user_id] = u; });

      var playoffStart = (league.settings && league.settings.playoff_week_start) || 15;
      var playoffTeams = (league.settings && league.settings.playoff_teams) || 6;
      var regWeeks = [];
      for (var w = 1; w < playoffStart; w++) regWeeks.push(w);
      var simWeeks = regWeeks.filter(function (w2) { return w2 >= curWeek; });

      // matchup pairings for every regular-season week (empty in the offseason)
      var pairsByWeek = {}, anyPairs = false;
      var matchupLists = await Promise.all(regWeeks.map(function (w) {
        return sleeper('/league/' + lid + '/matchups/' + w).catch(function () { return []; });
      }));
      // real lineups for the current week (games already final get banked as the manager set them)
      var lockedReal = {};
      (matchupLists[regWeeks.indexOf(curWeek)] || []).forEach(function (m) {
        var stx = {}, o = {};
        (m.starters || []).forEach(function (id) { stx[String(id)] = 1; });
        (m.players || []).forEach(function (id) { var pv = (m.players_points || {})[id]; o[String(id)] = { start: !!stx[String(id)], pts: pv != null ? +pv : null }; });
        lockedReal[m.roster_id] = o;
      });
      regWeeks.forEach(function (w, i) {
        var byMid = {};
        (matchupLists[i] || []).forEach(function (m) {
          if (m.matchup_id == null) return;
          (byMid[m.matchup_id] = byMid[m.matchup_id] || []).push(m.roster_id);
        });
        var pairs = Object.keys(byMid).map(function (mid) { return { a: byMid[mid][0], b: byMid[mid][1] }; })
          .filter(function (p) { return p.a != null && p.b != null; });
        if (pairs.length) { pairsByWeek[w] = pairs; anyPairs = true; }
      });

      var unavailable = {};
      try {
        var inSeason = !!(nflState && nflState.season_type === 'regular');
        unavailable = effectiveUnavailable(await getInjuryMap(), inSeason);
      } catch (e) { /* sim proceeds without injury data */ }

      var teams = rosters.map(function (r) {
        var u = userById[r.owner_id] || {};
        var name = (u.metadata && u.metadata.team_name) || u.display_name || ('Roster ' + r.roster_id);
        // league-enforced IR/taxi slots can't start — drop them outright
        var benched = {};
        (r.reserve || []).concat(r.taxi || []).forEach(function (id) { benched[String(id)] = 1; });
        return {
          rosterId: r.roster_id, name: name,
          playerIds: (r.players || []).map(String).filter(function (id) { return !benched[id]; }),
          record: r.settings ? { w: r.settings.wins || 0, l: r.settings.losses || 0, pf: (r.settings.fpts || 0) + (r.settings.fpts_decimal || 0) / 100 } : null
        };
      });

      if (!anyPairs) {
        pairsByWeek = roundRobin(teams.map(function (t) { return t.rosterId; }), regWeeks);
      }

      // actual pick inventory: everyone starts with their own 2027/2028 picks,
      // then Sleeper's traded_picks moves them (orig team stays attached — it
      // drives the pick's value via that team's projected finish)
      var pickInventory = {};
      teams.forEach(function (t) { pickInventory[t.rosterId] = []; });
      [2027, 2028].forEach(function (y) {
        for (var rd = 1; rd <= 4; rd++) {
          teams.forEach(function (t) { pickInventory[t.rosterId].push({ year: y, round: rd, orig: t.rosterId }); });
        }
      });
      tradedPicks.forEach(function (tp) {
        var y = +tp.season, rd = tp.round, orig = tp.roster_id, owner = tp.owner_id;
        if ((y !== 2027 && y !== 2028) || rd > 4 || orig == null || owner == null || orig === owner) return;
        var from = pickInventory[orig] || [];
        var idx = from.findIndex(function (p) { return p.year === y && p.round === rd && p.orig === orig; });
        if (idx >= 0) from.splice(idx, 1);
        if (pickInventory[owner]) pickInventory[owner].push({ year: y, round: rd, orig: orig });
      });

      var slots = (league.roster_positions || []).filter(function (s) { return s !== 'BN' && s !== 'IR' && s !== 'TAXI'; });
      state.league = {
        id: lid, name: league.name, league: league, teams: teams, pairsByWeek: pairsByWeek,
        regWeeks: simWeeks, playoffStart: playoffStart, playoffTeams: playoffTeams,
        playoffReseed: +(league.settings && league.settings.playoff_seed_type) === 1,
        lineupSlots: slots, scoring: E.scoringFromLeague(league.scoring_settings),
        synthSchedule: !anyPairs, demo: false,
        unavailable: unavailable, currentWeek: curWeek, lockedReal: lockedReal,
        pickInventory: pickInventory, tradedPickCount: tradedPicks.length
      };
      var matched = 0, total = 0, nOut = 0, nIR = 0;
      teams.forEach(function (t) {
        t.playerIds.forEach(function (id) {
          total++;
          if (state.players.bySid[id]) matched++;
          if (unavailable[id] === 'out') nOut++; else if (unavailable[id] === 'ir') nIR++;
        });
      });
      $('lg-note').textContent = '"' + league.name + '" loaded — ' + teams.length + ' teams, ' + simWeeks.length +
        ' of ' + regWeeks.length + ' regular-season weeks left to sim, ' + playoffTeams + ' playoff spots' +
        (state.league.synthSchedule ? ' · NO SCHEDULE YET (offseason) — using synthesized round-robin' : '') +
        ' · ' + matched + '/' + total + ' rostered players matched to projections' +
        ' · injuries: ' + nOut + ' OUT this week, ' + nIR + ' IR/PUP/Susp excluded' +
        ' · rec=' + state.league.scoring.rec + ', passTD=' + state.league.scoring.pass_td;
      renderLeagueTeams();
    } catch (e) {
      $('lg-note').textContent = 'Failed: ' + e.message + (location.protocol === 'file:' ? ' — if fetch is blocked, serve this folder over http (python -m http.server).' : '');
    }
  }

  function roundRobin(ids, weeks) {
    var arr = ids.slice();
    if (arr.length % 2) arr.push(null);
    var n = arr.length, half = n / 2, pairsByWeek = {};
    weeks.forEach(function (wk, i) {
      var pairs = [];
      for (var j = 0; j < half; j++) {
        var a = arr[j], b = arr[n - 1 - j];
        if (a != null && b != null) pairs.push({ a: a, b: b });
      }
      pairsByWeek[wk] = pairs;
      arr.splice(1, 0, arr.pop()); // rotate all but first
    });
    return pairsByWeek;
  }

  // ---------------- ESPN LEAGUE ----------------
  // Public leagues only: ESPN's lm-api-reads endpoint reflects our Origin in
  // Access-Control-Allow-Origin (same trick as the MFF site's direct My Teams
  // sync), so no proxy or extension is needed. Private leagues 401 — cookies
  // can't cross origins — and those stay unsupported here.
  // Players are matched by NORMALIZED NAME + position into the projection pool
  // (engine bySid carries norm-name aliases); DSTs match by pro-team abbr.
  var ESPN_PRO_TEAM = {
    1: 'ATL', 2: 'BUF', 3: 'CHI', 4: 'CIN', 5: 'CLE', 6: 'DAL', 7: 'DEN',
    8: 'DET', 9: 'GB', 10: 'TEN', 11: 'IND', 12: 'KC', 13: 'LV', 14: 'LAR',
    15: 'MIA', 16: 'MIN', 17: 'NE', 18: 'NO', 19: 'NYG', 20: 'NYJ', 21: 'PHI',
    22: 'ARI', 23: 'PIT', 24: 'LAC', 25: 'SF', 26: 'SEA', 27: 'TB', 28: 'WSH',
    29: 'CAR', 30: 'JAX', 33: 'BAL', 34: 'HOU'
  };
  var ESPN_POS = { 1: 'QB', 2: 'RB', 3: 'WR', 4: 'TE', 5: 'K', 16: 'DST' };
  // lineupSlotId -> engine slot label. The engine understands the narrow
  // flexes natively, so 3 (RB/WR) and 5 (WR/TE) keep their real eligibility
  // instead of collapsing to full FLEX. IDP/exotic slots map to nothing.
  var ESPN_SLOT = {
    0: 'QB', 1: 'QB' /* TQB */, 2: 'RB', 3: 'WRRB_FLEX', 4: 'WR',
    5: 'REC_FLEX', 6: 'TE', 7: 'SUPER_FLEX' /* OP */, 16: 'DEF', 17: 'K',
    23: 'FLEX' /* RB/WR/TE */
  };
  // scoringItems statId -> the engine scoring keys that actually move points
  var ESPN_STAT = { 3: 'pass_yd', 4: 'pass_td', 24: 'rush_yd', 25: 'rush_td', 42: 'rec_yd', 43: 'rec_td', 53: 'rec' };

  // NFL fantasy season: ESPN's new seasonId takes over in February.
  function espnSeason() { var d = new Date(); return d.getMonth() >= 1 ? d.getFullYear() : d.getFullYear() - 1; }

  function espnStatPoints(it) {
    // same override rule the battle-tested extension normalizer uses
    return it.pointsOverrides && it.pointsOverrides['16'] != null ? it.pointsOverrides['16'] : it.points;
  }
  function espnScoring(settings) {
    var sc = E.scoringFromLeague(null); // engine defaults; unlisted stat = default
    try {
      (settings.scoringSettings.scoringItems || []).forEach(function (it) {
        var key = ESPN_STAT[it.statId];
        if (!key) return;
        var pts = espnStatPoints(it);
        if (typeof pts === 'number') sc[key] = pts;
      });
      // receptions absent from scoringItems = a true standard league
      var hasRec = (settings.scoringSettings.scoringItems || []).some(function (it) { return it.statId === 53; });
      if (!hasRec) sc.rec = 0;
    } catch (e) { /* keep defaults */ }
    return sc;
  }

  function espnSlots(settings) {
    var out = [];
    try {
      var counts = settings.rosterSettings.lineupSlotCounts || {};
      // strict slots first, flexes after (pickLineup re-sorts anyway)
      ['0', '1', '2', '4', '6', '3', '5', '23', '7', '17', '16'].forEach(function (slotId) {
        var label = ESPN_SLOT[slotId], n = parseInt(counts[slotId], 10) || 0;
        if (!label || n <= 0) return;
        for (var i = 0; i < n; i++) out.push(label);
      });
    } catch (e) {}
    return out;
  }

  function espnTeamName(t) {
    if (t.name && t.name.trim()) return t.name.trim();
    var parts = [t.location, t.nickname].filter(function (s) { return s && s.trim(); });
    return parts.join(' ').trim() || ('Team ' + t.id);
  }

  async function loadEspnLeague(raw) {
    if (!raw) { $('lg-note').textContent = 'Paste an ESPN league ID (or the fantasy.espn.com league URL).'; return; }
    var urlMatch = raw.match(/leagueId=(\d+)/i);
    var lid = urlMatch ? urlMatch[1] : (raw.match(/^\d+$/) || [''])[0];
    if (!lid) { $('lg-note').textContent = 'That doesn\'t look like an ESPN league ID or URL.'; return; }
    $('lg-note').textContent = 'Loading ESPN league…';
    try {
      var season = espnSeason();
      var resp = await fetch('https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/' + season +
        '/segments/0/leagues/' + lid + '?view=mTeam&view=mRoster&view=mSettings&view=mMatchup');
      if (resp.status === 401) throw new Error('this league is private — make it viewable-to-public in ESPN league settings, then retry.');
      if (resp.status === 404) throw new Error('league not found for the ' + season + ' season — double-check the ID.');
      if (!resp.ok) throw new Error('ESPN returned ' + resp.status + ' — try again in a minute.');
      var lg = await resp.json();
      if (Array.isArray(lg)) lg = lg[0];
      if (!lg || !lg.id || !Array.isArray(lg.teams)) throw new Error('that response didn\'t look like a fantasy football league.');
      var settings = lg.settings || {};

      // schedule shape: mid-season the sim keeps real records + remaining weeks
      var nflState = await sleeper('/state/nfl').catch(function () { return null; });
      var inSeason = !!(nflState && nflState.season_type === 'regular');
      var curWeek = (inSeason && nflState.week > 0) ? nflState.week : 1;
      var ss = settings.scheduleSettings || {};
      // ESPN's key is matchupPeriodCount (regular-season periods; verified on a live league 2026-10-05 — the old
      // regularSeasonMatchupPeriodCount read never existed and always fell back to 14); matchupPeriods maps a
      // period to its NFL weeks, so the first playoff week is period (count + 1)'s first week.
      var regCount = ss.matchupPeriodCount || ss.regularSeasonMatchupPeriodCount || 14;
      var nextPer = ss.matchupPeriods && ss.matchupPeriods[String(regCount + 1)];
      var playoffStart = nextPer && nextPer.length ? nextPer[0] : regCount + 1;
      var playoffTeams = ss.playoffTeamCount || 6;
      var regWeeks = [];
      for (var w = 1; w < playoffStart; w++) regWeeks.push(w);
      var simWeeks = regWeeks.filter(function (w2) { return w2 >= curWeek; });

      // real matchup pairings from the mMatchup schedule (matchup periods =
      // NFL weeks during the regular season)
      var pairsByWeek = {}, anyPairs = false;
      (lg.schedule || []).forEach(function (m) {
        var wk = m.matchupPeriodId;
        if (!wk || wk >= playoffStart) return;
        var a = m.away && m.away.teamId, h = m.home && m.home.teamId;
        if (a == null || h == null) return;
        (pairsByWeek[wk] = pairsByWeek[wk] || []).push({ a: a, b: h });
        anyPairs = true;
      });

      var unavailable = {};
      try { unavailable = effectiveUnavailable(await getInjuryMap(), inSeason); } catch (e) { /* sim proceeds without injury data */ }

      var matched = 0, total = 0;
      var teams = lg.teams.map(function (t) {
        var ids = [];
        ((t.roster && t.roster.entries) || []).forEach(function (en) {
          if (en.lineupSlotId === 21) return; // league-enforced IR slot can't start
          var p = en.playerPoolEntry && en.playerPoolEntry.player;
          if (!p) return;
          var pos = ESPN_POS[p.defaultPositionId];
          if (!pos) return; // IDP etc. — nothing to project
          total++;
          if (pos === 'DST') {
            var tm = E.normTeam(ESPN_PRO_TEAM[p.proTeamId] || '');
            if (state.players.bySid[tm]) { ids.push(tm); matched++; }
            return;
          }
          // QB/RB/WR/TE ride the Best Ball nickname-tier matcher (Kenny↔
          // Kenneth Gainwell, Kenneth↔Ken Walker III); kickers stay exact-norm
          // because bbMatchPlayer deliberately excludes K/DST from its pool.
          var cand = pos === 'K' ? state.players.byNorm[E.norm(p.fullName)] : bbMatchPlayer(p.fullName, pos);
          if (cand && cand.pos === pos) { ids.push(cand.sid || cand.norm); matched++; }
        });
        var rec = (t.record && t.record.overall) || null;
        return {
          rosterId: t.id, name: espnTeamName(t), playerIds: ids,
          record: rec ? { w: rec.wins || 0, l: rec.losses || 0, pf: Math.round((rec.pointsFor || 0) * 100) / 100 } : null
        };
      });

      if (!anyPairs) pairsByWeek = roundRobin(teams.map(function (t2) { return t2.rosterId; }), regWeeks);

      var slots = espnSlots(settings);
      if (!slots.length) slots = ['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'FLEX', 'K', 'DEF'];
      var scoring = espnScoring(settings);
      state.league = {
        id: 'espn:' + lid, name: (settings.name || ('ESPN League ' + lid)), teams: teams,
        pairsByWeek: pairsByWeek, regWeeks: simWeeks, playoffStart: playoffStart,
        playoffTeams: playoffTeams, lineupSlots: slots, scoring: scoring,
        synthSchedule: !anyPairs, demo: false, platform: 'espn', playoffReseed: ss.playoffReseed === true,
        unavailable: unavailable, currentWeek: curWeek
        // no pickInventory — trade analyzer falls back to own-picks (ESPN has
        // no traded-picks API; these are redraft leagues anyway)
      };
      var nOut = 0, nIR = 0;
      teams.forEach(function (t) {
        t.playerIds.forEach(function (id) {
          if (unavailable[id] === 'out') nOut++; else if (unavailable[id] === 'ir') nIR++;
        });
      });
      $('lg-note').textContent = '"' + state.league.name + '" (ESPN) loaded — ' + teams.length + ' teams, ' +
        simWeeks.length + ' of ' + regWeeks.length + ' regular-season weeks left to sim, ' + playoffTeams + ' playoff spots' +
        (state.league.synthSchedule ? ' · NO SCHEDULE IN PAYLOAD — using synthesized round-robin' : '') +
        ' · ' + matched + '/' + total + ' rostered players matched to projections (by name)' +
        ' · injuries: ' + nOut + ' OUT this week, ' + nIR + ' IR/PUP/Susp excluded' +
        ' · rec=' + scoring.rec + ', passTD=' + scoring.pass_td;
      renderLeagueTeams();
    } catch (e) {
      $('lg-note').textContent = 'ESPN load failed: ' + e.message +
        (e instanceof TypeError ? ' — network/CORS error; check the connection (and serve over http, not file://).' : '');
    }
  }

  // ---------------- YAHOO LEAGUE ----------------
  // Link-viewable leagues only, relayed through the site's yahooProxy Cloud
  // Function (Yahoo sends no CORS headers for any of our origins; the proxy
  // allowlists the pub-api settings/teams JSON + the /f1/ league pages).
  // Rosters exist only in the server-rendered team pages, so the flow is:
  // settings JSON (exact scoring + lineup slots + playoff spots) → league
  // home HTML (standings: team ids/names/records) → one page per team
  // (rosters), parsed by data/yahoo_normalize.js (refresh_data.py copies the
  // site's synced normalizer in). No matchup route passes the proxy allowlist,
  // so the schedule is a synthesized round-robin — real W/L/PF from the
  // standings still anchor mid-season sims.
  var YAHOO_PROXY = 'https://us-central1-jackb933-website.cloudfunctions.net/yahooProxy?url=';
  // settings stat_id → engine scoring key (verified against league 1301476:
  // 4 passYds .04, 5 passTD, 9 rushYds, 10 rushTD, 11 rec, 12 recYds, 13 recTD)
  var YAHOO_STAT = { 4: 'pass_yd', 5: 'pass_td', 9: 'rush_yd', 10: 'rush_td', 11: 'rec', 12: 'rec_yd', 13: 'rec_td' };

  async function yahooProxyFetch(url) {
    var r = await fetch(YAHOO_PROXY + encodeURIComponent(url));
    if (r.status === 403) throw new Error('this league isn\'t publicly viewable — set "Make league viewable to public" to Yes in Yahoo commissioner settings, then retry.');
    if (r.status === 404) throw new Error('league not found — double-check the ID.');
    if (!r.ok) throw new Error('Yahoo returned ' + r.status + ' — try again in a minute.');
    return r;
  }

  async function loadYahooLeague(raw) {
    if (!raw) { $('lg-note').textContent = 'Paste a Yahoo league ID (or the football.fantasysports.yahoo.com league URL).'; return; }
    var urlMatch = raw.match(/\/f1\/(\d+)/);
    var lid = urlMatch ? urlMatch[1] : (raw.match(/^\d+$/) || [''])[0];
    if (!lid) { $('lg-note').textContent = 'That doesn\'t look like a Yahoo league ID or URL.'; return; }
    if (!window.MFF_YAHOO) { $('lg-note').textContent = 'data/yahoo_normalize.js missing — run refresh_data.py.'; return; }
    var N = window.MFF_YAHOO;
    try {
      // 1) settings JSON — exact scoring, lineup slots, playoff spots
      $('lg-note').textContent = 'Loading Yahoo league…';
      var sResp = await yahooProxyFetch('https://pub-api.fantasysports.yahoo.com/fantasy/v3/settings/nfl/' + lid + '?format=rawjson');
      var sJson = await sResp.json().catch(function () { return null; });
      var svc = (sJson && (sJson.service || sJson)) || {};
      if (!svc.league_id && !svc.name) throw new Error('league not found — double-check the ID.');
      var st = svc.settings || {};
      var scoring = E.scoringFromLeague(null); // engine defaults; unlisted stat = default
      (st.stat_categories || []).forEach(function (c) {
        var key = YAHOO_STAT[Number(c.stat_id)];
        if (!key) return;
        var v = parseFloat(c.stat_modifier);
        if (!isNaN(v)) scoring[key] = v;
      });
      var slots = [];
      (st.roster_positions || []).forEach(function (r) {
        var lbl = N.SLOT_MAP[String(r.position || '').toUpperCase().replace(/\s+/g, '')];
        if (!lbl || lbl === 'BN' || lbl === 'IR') return;
        var n = parseInt(r.count, 10) || 0;
        for (var i = 0; i < n; i++) slots.push(lbl);
      });
      if (!slots.length) slots = ['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'FLEX', 'K', 'DEF'];
      var playoffTeams = parseInt(st.num_playoff_teams, 10) || 6;
      var playoffStart = 15; // Yahoo's fixed default; not exposed in the settings JSON

      // 2) league home HTML — team ids/names/records; teams-API fallback
      //    (names only) for page skins without a standings module
      $('lg-note').textContent = 'Reading standings…';
      var homeResp = await yahooProxyFetch('https://football.fantasysports.yahoo.com/f1/' + lid);
      var homeDoc = new DOMParser().parseFromString(await homeResp.text(), 'text/html');
      var standings = N.parseStandingsDoc(homeDoc, lid);
      if (!standings.teams.length) {
        var tResp = await yahooProxyFetch('https://pub-api.fantasysports.yahoo.com/fantasy/v3/teams/nfl/' + lid + '?format=rawjson');
        var tJson = await tResp.json().catch(function () { return null; });
        var list = (tJson && tJson.service && tJson.service.team_list) || [];
        standings.teams = list.map(function (t) { return { teamId: t.id, name: t.teamname || ('Team ' + t.id), wins: 0, losses: 0, fpts: 0 }; });
      }
      if (!standings.teams.length) throw new Error('no teams found — double-check the league ID.');

      // 3) one page per team for rosters (the JSON API has no roster route)
      var matched = 0, total = 0, teams = [];
      for (var ti = 0; ti < standings.teams.length; ti++) {
        var t = standings.teams[ti];
        $('lg-note').textContent = 'Reading rosters… ' + (ti + 1) + '/' + standings.teams.length;
        var ids = [];
        try {
          var tr = await yahooProxyFetch('https://football.fantasysports.yahoo.com/f1/' + lid + '/' + t.teamId);
          var doc = new DOMParser().parseFromString(await tr.text(), 'text/html');
          var parsed = N.parseTeamDoc(doc);
          (parsed ? parsed.roster : []).forEach(function (pl) {
            if (!pl.pos) return;
            total++;
            if (pl.pos === 'D/ST') {
              // normalizer emits fixAbbr'd team codes (WSH etc.) — normTeam undoes that
              var tm = E.normTeam(pl.team);
              if (state.players.bySid[tm]) { ids.push(tm); matched++; }
              return;
            }
            if (pl.pos === 'K') {
              var kc = state.players.byNorm[E.norm(pl.name)];
              if (kc && kc.pos === 'K') { ids.push(kc.sid || kc.norm); matched++; }
              return;
            }
            var cand = bbMatchPlayer(pl.name, pl.pos);
            if (cand && cand.pos === pl.pos) { ids.push(cand.sid || cand.norm); matched++; }
          });
        } catch (e2) { /* team page failed — roster stays empty */ }
        teams.push({
          rosterId: t.teamId, name: t.name, playerIds: ids,
          record: { w: t.wins || 0, l: t.losses || 0, pf: Math.round((t.fpts || 0) * 100) / 100 }
        });
      }

      var nflState = await sleeper('/state/nfl').catch(function () { return null; });
      var inSeason = !!(nflState && nflState.season_type === 'regular');
      var curWeek = (inSeason && nflState.week > 0) ? nflState.week : 1;
      var regWeeks = [];
      for (var w = 1; w < playoffStart; w++) regWeeks.push(w);
      var simWeeks = regWeeks.filter(function (w2) { return w2 >= curWeek; });
      var unavailable = {};
      try { unavailable = effectiveUnavailable(await getInjuryMap(), inSeason); } catch (e3) { /* sim proceeds without injury data */ }

      state.league = {
        id: 'yahoo:' + lid, name: svc.name || standings.name || ('Yahoo League ' + lid), teams: teams,
        pairsByWeek: roundRobin(teams.map(function (t2) { return t2.rosterId; }), regWeeks),
        regWeeks: simWeeks, playoffStart: playoffStart, playoffTeams: playoffTeams,
        lineupSlots: slots, scoring: scoring,
        synthSchedule: true, demo: false, platform: 'yahoo',
        unavailable: unavailable, currentWeek: curWeek
        // no pickInventory — trade analyzer falls back to own picks
      };
      var nOut = 0, nIR = 0;
      teams.forEach(function (t3) {
        t3.playerIds.forEach(function (id) {
          if (unavailable[id] === 'out') nOut++; else if (unavailable[id] === 'ir') nIR++;
        });
      });
      $('lg-note').textContent = '"' + state.league.name + '" (Yahoo) loaded — ' + teams.length + ' teams, ' +
        simWeeks.length + ' of ' + regWeeks.length + ' regular-season weeks left to sim, ' + playoffTeams + ' playoff spots' +
        ' · NO MATCHUP FEED — synthesized round-robin schedule (records still real)' +
        ' · ' + matched + '/' + total + ' rostered players matched to projections (by name)' +
        ' · injuries: ' + nOut + ' OUT this week, ' + nIR + ' IR/PUP/Susp excluded' +
        ' · rec=' + scoring.rec + ', passTD=' + scoring.pass_td;
      renderLeagueTeams();
    } catch (e) {
      $('lg-note').textContent = 'Yahoo load failed: ' + e.message +
        (e instanceof TypeError ? ' — network/CORS error; check the connection.' : '');
    }
  }

  // ---------------- MFF CLOUD LEAGUES (site-synced, incl. PRIVATE) ----------------
  // The MFF site saves every league imported on My Teams — extension-bridged
  // PRIVATE ESPN/Yahoo leagues included — to Firestore:
  //   user_game_data/{uid}.savedLeagues[key] = { leagueId ('espn_123',
  //     'yahoo_45', or a bare Sleeper id), name, season, format {type, sf,
  //     ppr, rosterPositions}, teams [{id, owner, isMyTeam, players
  //     [canonical site-name strings], slIds [raw Sleeper ids — Sleeper
  //     leagues only], wins, losses, fpts}], savedAt }
  // LOAD FROM MFF signs into the same Firebase project (reusing the Best Ball
  // tab's ensureFirebase bootstrap) and converts those snapshots. Rosters are
  // as-of the last site sync — re-sync there for fresh ones. ESPN snapshots
  // synced with extension v0.20.19+ (site 2026-08-31w+) carry the REAL
  // schedule ({week,home,away} teamId pairs); older snapshots fall back to a
  // synthesized round-robin. Still not stored by the site: playoff settings
  // (defaults wk15 / 6 teams) and non-rec scoring detail (pass TD assumed 4).
  async function loadMffLeagues() {
    var btn = $('lg-mff');
    btn.disabled = true;
    try {
      $('lg-note').textContent = 'Loading Firebase…';
      await ensureFirebase();
      // let persisted auth restore before deciding to pop the sign-in window
      var user = await new Promise(function (res) {
        var un = firebase.auth().onAuthStateChanged(function (u) { un(); res(u); });
      });
      if (!user) {
        $('lg-note').textContent = 'Sign in with the Google account you use on the MFF site…';
        user = (await firebase.auth().signInWithPopup(new firebase.auth.GoogleAuthProvider())).user;
      }
      $('lg-note').textContent = 'Reading your saved leagues…';
      var doc = await firebase.firestore().collection('user_game_data').doc(user.uid).get();
      var saved = doc.exists && doc.data().savedLeagues ? doc.data().savedLeagues : null;
      var leagues = saved ? Object.values(saved).filter(function (l) { return l && l.teams && l.teams.length; }) : [];
      if (!leagues.length) {
        $('lg-note').textContent = 'No saved leagues for ' + (user.email || 'this account') +
          ' — import one on the MFF site (My Teams tab) first.';
        return;
      }
      leagues.sort(function (a, b) { return (b.savedAt || '').localeCompare(a.savedAt || ''); });
      state.mffLeagues = leagues;
      var sel = $('lg-mff-pick');
      sel.innerHTML = '';
      leagues.forEach(function (l, i) {
        var when = (l.savedAt || '').slice(0, 10);
        sel.add(new Option(l.name + (when ? ' · ' + when : ''), i));
      });
      sel.style.display = '';
      await applyMffLeague(leagues[0]);
    } catch (e) {
      var msg = (e && (e.code || e.message)) || String(e);
      if (/unauthorized-domain/.test(msg)) {
        msg += ' — open Sim Lab via localhost, or add this domain under Firebase console → Authentication → Settings → Authorized domains.';
      }
      $('lg-note').textContent = 'MFF load failed: ' + msg;
    } finally { btn.disabled = false; }
  }

  // "<Full Franchise Name> D/ST" (the site's canonical DST form) → engine abbr,
  // built by inverting the Yahoo normalizer's ABBR_FULL map (already loaded).
  var _mffDstAbbr = null;
  function mffDstAbbr(name) {
    if (!_mffDstAbbr) {
      _mffDstAbbr = {};
      var full = (window.MFF_YAHOO && window.MFF_YAHOO.ABBR_FULL) || {};
      Object.keys(full).forEach(function (ab) { _mffDstAbbr[E.norm(full[ab] + ' D/ST')] = E.normTeam(ab); });
    }
    return _mffDstAbbr[E.norm(name)] || null;
  }

  async function applyMffLeague(lg) {
    var fmt = lg.format || {};
    var slots = (fmt.rosterPositions || []).filter(function (s) { return s !== 'BN' && s !== 'IR' && s !== 'TAXI'; });
    if (!slots.length) slots = ['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'FLEX', 'K', 'DEF'];
    // Scoring: the snapshot's per-stat `scoring` map (Sleeper keys; site saves it since 2026-10-05) wins; older
    // snapshots fall back to the format's rec + passTd + tep (TE premium per catch, saved since 2026-09-02).
    var scSrc = lg.scoring && typeof lg.scoring === 'object' ? 'league settings' : 'site format';
    var scoring = E.scoringFromLeague(Object.assign({
      rec: typeof fmt.ppr === 'number' ? fmt.ppr : 0.5,
      pass_td: typeof fmt.passTd === 'number' ? fmt.passTd : 4,
      bonus_rec_te: typeof fmt.tep === 'number' ? fmt.tep : 0
    }, scSrc === 'league settings' ? lg.scoring : {}));

    var nflState = await sleeper('/state/nfl').catch(function () { return null; });
    var inSeason = !!(nflState && nflState.season_type === 'regular');
    var curWeek = (inSeason && nflState.week > 0) ? nflState.week : 1;
    // Playoff shape: newer site snapshots persist it; Sleeper leagues (saved
    // under their bare numeric id) fall back to a live /league read;
    // otherwise Yahoo/ESPN-typical defaults.
    var slId = /^\d+$/.test(String(lg.leagueId || '')) ? String(lg.leagueId) : null;
    var slLeague = slId ? await sleeper('/league/' + slId).catch(function () { return null; }) : null;
    var slSet = (slLeague && slLeague.settings) || {};
    var playoffStart = +lg.playoffStart || +slSet.playoff_week_start || 15;
    var playoffTeams = +lg.playoffTeams || +slSet.playoff_teams || 6;
    var playoffReseed = lg.playoffReseed != null ? !!lg.playoffReseed : +slSet.playoff_seed_type === 1;
    var playoffSrc = (+lg.playoffStart || +lg.playoffTeams)
      ? 'site snapshot' + (+lg.playoffStart ? '' : ', start wk assumed')
      : (+slSet.playoff_week_start ? 'Sleeper (live)' : 'assumed');
    // older Sleeper snapshots without a scoring map: the live league's scoring_settings are exact
    if (scSrc !== 'league settings' && slLeague && slLeague.scoring_settings) {
      scoring = E.scoringFromLeague(slLeague.scoring_settings);
      scSrc = 'Sleeper league (live)';
    }
    var regWeeks = []; for (var w = 1; w < playoffStart; w++) regWeeks.push(w);
    var simWeeks = regWeeks.filter(function (w2) { return w2 >= curWeek; });
    var unavailable = {};
    try { unavailable = effectiveUnavailable(await getInjuryMap(), inSeason); } catch (e) { /* sim proceeds without injury data */ }

    var matched = 0, total = 0;
    var teams = (lg.teams || []).map(function (t, i) {
      var ids = [];
      if (t.slIds && t.slIds.length) {
        // Sleeper-sourced snapshot — raw Sleeper ids match the pool directly
        t.slIds.map(String).forEach(function (id) {
          total++;
          if (state.players.bySid[id]) { ids.push(id); matched++; }
        });
      } else {
        (t.players || []).forEach(function (name) {
          if (!name) return;
          total++;
          if (/ D\/ST$/i.test(name)) {
            var ab = mffDstAbbr(name);
            var dp = ab ? state.players.bySid[ab] : state.players.byNorm[E.norm(name)];
            if (dp) { ids.push(dp.sid || dp.norm); matched++; }
            return;
          }
          // exact-name hit first (covers kickers, which bbMatchPlayer excludes),
          // then the nickname-tier matcher; no pos stored in the snapshot
          var cand = state.players.byNorm[E.norm(name)] || bbMatchPlayer(name, null);
          if (cand) { ids.push(cand.sid || cand.norm); matched++; }
        });
      }
      return {
        rosterId: t.id != null ? t.id : i + 1,
        name: t.owner || ('Team ' + (i + 1)),
        playerIds: ids,
        record: { w: t.wins || 0, l: t.losses || 0, pf: Math.round((t.fpts || 0) * 100) / 100 }
      };
    });

    // Real head-to-head schedule when the snapshot carries one — the site
    // persists the slim {week, home, away} teamId pairs on ESPN leagues
    // synced with extension v0.20.19+ (site build 2026-08-31w+). teamIds are
    // the same ids used as rosterId above. Round-robin synth otherwise.
    var realPairs = null;
    if (Array.isArray(lg.schedule) && lg.schedule.length) {
      var pb = {}, anyReal = false;
      lg.schedule.forEach(function (g) {
        if (!g || !g.week || g.week >= playoffStart) return;
        if (g.home == null || g.away == null) return;
        (pb[g.week] = pb[g.week] || []).push({ a: g.away, b: g.home });
        anyReal = true;
      });
      if (anyReal) realPairs = pb;
    }
    // Sleeper snapshots saved before the site persisted schedules: pull the
    // real matchup pairings straight from Sleeper (roster ids = team ids).
    var schedSrc = realPairs ? 'the site snapshot' : null;
    if (!realPairs && slId) {
      var lists = await Promise.all(regWeeks.map(function (w3) {
        return sleeper('/league/' + slId + '/matchups/' + w3).catch(function () { return []; });
      }));
      var pb2 = {}, any2 = false;
      regWeeks.forEach(function (w3, i) {
        var byMid = {};
        (lists[i] || []).forEach(function (m) {
          if (m.matchup_id == null) return;
          (byMid[m.matchup_id] = byMid[m.matchup_id] || []).push(m.roster_id);
        });
        var pairs = Object.keys(byMid).map(function (mid) { return { a: byMid[mid][0], b: byMid[mid][1] }; })
          .filter(function (p) { return p.a != null && p.b != null; });
        if (pairs.length) { pb2[w3] = pairs; any2 = true; }
      });
      if (any2) { realPairs = pb2; schedSrc = 'Sleeper (live)'; }
    }

    // lg.lockedLineups {teamId: [{name, start, pts}]} = real lineup calls on players whose game is final
    var lockedRealM = null;
    if (lg.lockedLineups) {
      lockedRealM = {};
      Object.keys(lg.lockedLineups).forEach(function (tid) {
        var o = {};
        (lg.lockedLineups[tid] || []).forEach(function (r) {
          var c2;
          if (/ D\/ST$/i.test(r.name)) { var ab2 = mffDstAbbr(r.name); c2 = ab2 ? state.players.bySid[ab2] : state.players.byNorm[E.norm(r.name)]; }
          else c2 = state.players.byNorm[E.norm(r.name)] || bbMatchPlayer(r.name, null);
          if (c2) o[c2.sid || c2.norm] = { start: !!r.start, pts: r.pts != null ? +r.pts : null };
        });
        lockedRealM[tid] = o;
      });
    }
    // No explicit payload: the site snapshot's own lineup (teams[].starters, names — ESPN/Yahoo
    // normalizers since 2026-09-02). Lineups lock at kickoff, so a snapshot synced AFTER a game
    // kicked off holds the real call on that game's players; runLeagueSim checks savedAt vs kickoff.
    var lockedRealAt = null;
    if (!lockedRealM && (lg.teams || []).some(function (t) { return Array.isArray(t.starters) && t.starters.length; })) {
      lockedRealM = {};
      var mId = function (name) {
        if (!name) return null;
        var c3;
        if (/ D\/ST$/i.test(name)) { var ab3 = mffDstAbbr(name); c3 = ab3 ? state.players.bySid[ab3] : state.players.byNorm[E.norm(name)]; }
        else c3 = state.players.byNorm[E.norm(name)] || bbMatchPlayer(name, null);
        return c3 ? (c3.sid || c3.norm) : null;
      };
      (lg.teams || []).forEach(function (t, i) {
        if (!Array.isArray(t.starters) || !t.starters.length) return;
        var stx = {}, o = {};
        t.starters.forEach(function (n) { var id = mId(n); if (id != null) stx[id] = 1; });
        (t.players || []).forEach(function (n) { var id = mId(n); if (id != null) o[id] = { start: !!stx[id], pts: null }; });
        lockedRealM[t.id != null ? t.id : i + 1] = o;
      });
      lockedRealAt = lg.savedAt ? new Date(lg.savedAt).getTime() : null;
      if (!lockedRealAt) lockedRealM = null;
    }
    state.league = {
      lockedReal: lockedRealM, lockedRealAt: lockedRealAt,
      id: 'mff:' + (lg.leagueId || lg.name), name: lg.name || 'MFF League', teams: teams,
      pairsByWeek: realPairs || roundRobin(teams.map(function (t2) { return t2.rosterId; }), regWeeks),
      regWeeks: simWeeks, playoffStart: playoffStart, playoffTeams: playoffTeams, playoffReseed: playoffReseed,
      lineupSlots: slots, scoring: scoring,
      synthSchedule: !realPairs, demo: false, platform: 'mff',
      unavailable: unavailable, currentWeek: curWeek
      // no pickInventory — trade analyzer falls back to own picks
    };
    var nOut = 0, nIR = 0;
    teams.forEach(function (t3) {
      t3.playerIds.forEach(function (id) {
        if (unavailable[id] === 'out') nOut++; else if (unavailable[id] === 'ir') nIR++;
      });
    });
    var when = (lg.savedAt || '').slice(0, 10);
    $('lg-note').textContent = '"' + state.league.name + '" (MFF cloud' + (when ? ', synced ' + when : '') + ') loaded — ' +
      teams.length + ' teams, ' + simWeeks.length + ' of ' + regWeeks.length + ' regular-season weeks left to sim' +
      ' · ' + matched + '/' + total + ' players matched to projections' +
      ' · injuries: ' + nOut + ' OUT this week, ' + nIR + ' IR/PUP/Susp excluded' +
      ' · scoring from the ' + scSrc + ': rec ' + scoring.rec + ', pass TD ' + scoring.pass_td + ', pass yd ' + scoring.pass_yd + (scoring.bonus_rec_te ? ', TE premium +' + scoring.bonus_rec_te : '') +
      ' · playoffs wk' + playoffStart + ' / ' + playoffTeams + ' teams' + (state.league.playoffReseed ? ', re-seeded' : '') + ' (' + playoffSrc + (playoffSrc === 'assumed' ? ' — re-sync the league on My Teams, or set the Playoffs boxes' : '') + ')' +
      (state.league.synthSchedule
        ? ' · SYNTHESIZED round-robin schedule — ' + (slId ? 'Sleeper has not posted matchups yet' : 're-sync the league on My Teams (ESPN helper v0.20.19+) to sync the real one')
        : ' · REAL schedule from ' + schedSrc) +
      ' · rosters as-of the last site sync — re-sync there for fresh ones';
    renderLeagueTeams();
  }

  window._mffApplyLeague = applyMffLeague; // test hook: drive a saved-league payload without auth

  // Demo league: 12 teams snake-draft by ADP — for testing before your league has data.
  function loadDemoLeague() {
    var slots = ['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'FLEX', 'K', 'DEF'];
    var caps = { QB: 2, RB: 5, WR: 6, TE: 2, K: 1, DST: 1 };
    var pool = state.players.list.filter(function (p) { return p.adp != null || p.isDST; })
      .sort(function (a, b) { return (a.adp || 400) - (b.adp || 400); });
    var kdst = state.players.list.filter(function (p) { return (p.pos === 'K' || p.pos === 'DST'); })
      .sort(function (a, b) { return E.seasonPoints(b, E.PRESETS.half) - (E.seasonPoints(a, E.PRESETS.half)) || (b.isDST ? 1 : 0); });
    pool = pool.concat(kdst.filter(function (p) { return pool.indexOf(p) < 0; }));
    var T = 12, R = 17;
    var teams = [];
    for (var t = 0; t < T; t++) teams.push({ rosterId: t + 1, name: 'Demo Team ' + (t + 1), playerIds: [], counts: {}, record: null });
    var taken = {};
    for (var r = 0; r < R; r++) {
      var order = (r % 2 === 0) ? teams : teams.slice().reverse();
      order.forEach(function (tm) {
        for (var i = 0; i < pool.length; i++) {
          var p = pool[i];
          if (taken[p.norm] || !p.sid) continue;
          var c = tm.counts[p.pos] || 0;
          if (c >= (caps[p.pos] || 0)) continue;
          taken[p.norm] = 1; tm.counts[p.pos] = c + 1;
          tm.playerIds.push(p.sid);
          break;
        }
      });
    }
    var regWeeks = []; for (var w = 1; w < 15; w++) regWeeks.push(w);
    state.league = {
      id: 'demo', name: 'Demo League (12tm, ADP snake)', teams: teams,
      pairsByWeek: roundRobin(teams.map(function (t2) { return t2.rosterId; }), regWeeks),
      regWeeks: regWeeks, playoffStart: 15, playoffTeams: 6,
      lineupSlots: slots, scoring: E.PRESETS.half, synthSchedule: true, demo: true
    };
    $('lg-note').textContent = 'Demo league built: 12 teams, snake by Underdog ADP, half PPR, 14-week season, 6 playoff spots.';
    renderLeagueTeams();
  }

  // ---------------- TRADE ANALYZER ----------------
  function fillTradeSelects() {
    var L = state.league;
    $('lg-trade-wrap').style.display = '';
    ['tr-a', 'tr-b'].forEach(function (id, i) {
      var sel = $(id);
      sel.innerHTML = '';
      L.teams.forEach(function (t) { sel.add(new Option(t.name, t.rosterId)); });
      sel.selectedIndex = Math.min(i, L.teams.length - 1);
    });
    // finish distribution for team-aware pick values (one quick sim per league load)
    if (state.tradeFinishFor !== L.id) {
      var res = E.simLeague({
        teams: L.teams, sims: 1500, seed: 99, scoring: L.scoring, schedule: state.schedule,
        players: state.players, pairsByWeek: L.pairsByWeek, regWeeks: L.regWeeks,
        playoffTeams: L.playoffTeams, playoffReseed: !!L.playoffReseed, playoffStart: L.playoffStart, lineupSlots: L.lineupSlots,
        unavailable: L.unavailable || {}, currentWeek: L.currentWeek || 1
      });
      state.tradeFinish = {};
      res.forEach(function (r) { state.tradeFinish[r.team.rosterId] = { placeCounts: r.placeCounts, sims: 1500 }; });
      state.tradeFinishFor = L.id;
    }
    fillTradePlayers('a');
    fillTradePlayers('b');
    fillTradePicks('a');
    fillTradePicks('b');
    $('tr-result').innerHTML = '';
  }

  // ---- team-aware pick valuation ----
  // Draft order = inverse of simmed finish (worst team picks 1st). The pick's
  // expected value integrates the WHOLE finish distribution over a slot-value
  // curve interpolated through the KTC Early/Mid/Late anchors — so a team
  // with tail risk of collapsing gets extra credit (early slots are convex).
  // 2028 picks regress 50% toward league-average (two years of roster churn).
  var ROUND_KEYS = ['1st', '2nd', '3rd', '4th'];
  function pickAnchors(year, round, sf) {
    var list = (window.SIM_SLEEPER && window.SIM_SLEEPER.pickAssets) || [];
    function v(tier) {
      var pk = list.find(function (p) { return p.n === year + ' ' + tier + ' ' + round; });
      return pk ? pickVal(pk, sf) : null;
    }
    var e = v('Early'), m = v('Mid'), l = v('Late');
    return (e != null && m != null && l != null) ? { e: e, m: m, l: l } : null;
  }
  function slotValue(slot, a, n) {
    var s1 = n * 2.5 / 12, s2 = n * 6.5 / 12, s3 = n * 10.5 / 12; // anchor slots, scaled to league size
    if (slot <= s1) return a.e;
    if (slot >= s3) return a.l;
    if (slot <= s2) return a.e + (a.m - a.e) * (slot - s1) / (s2 - s1);
    return a.m + (a.l - a.m) * (slot - s2) / (s3 - s2);
  }
  function teamPickValue(rid, year, round, sf) {
    var a = pickAnchors(year, round, sf);
    if (!a) return null;
    var L = state.league, n = L.teams.length;
    var f = state.tradeFinish && state.tradeFinish[rid];
    if (!f) return Math.round((a.e + a.m + a.l) / 3);
    var blend = year >= 2028 ? 0.5 : 0;
    var ev = 0, tot = 0;
    for (var place = 1; place <= n; place++) {
      var p = (f.placeCounts[place] || 0) / f.sims;
      p = (1 - blend) * p + blend / n;
      ev += p * slotValue(n + 1 - place, a, n);
      tot += p;
    }
    return Math.round(ev / (tot || 1));
  }
  function fillTradePicks(side) {
    var L = state.league;
    if (!L) return;
    var sf = tradeIsSF();
    var rid = +$('tr-' + side).value;
    var sel = $('tr-' + side + '-picks');
    sel.innerHTML = '';
    var nameById = {};
    L.teams.forEach(function (t) { nameById[t.rosterId] = t.name; });
    // real inventory (Sleeper traded_picks applied); fallback = own picks
    var inv = (L.pickInventory && L.pickInventory[rid]);
    if (!inv) {
      inv = [];
      [2027, 2028].forEach(function (y) { for (var rd = 1; rd <= 4; rd++) inv.push({ year: y, round: rd, orig: rid }); });
    }
    inv.slice().sort(function (a, b) { return (a.year - b.year) || (a.round - b.round); }).forEach(function (pk) {
      var rKey = ROUND_KEYS[pk.round - 1];
      if (!rKey) return;
      var v = teamPickValue(pk.orig, pk.year, rKey, sf);
      if (v == null) return;
      var label = pk.year + ' ' + rKey + (pk.orig !== rid ? ' via ' + (nameById[pk.orig] || pk.orig) : '') + ' (' + v.toLocaleString() + ')';
      sel.add(new Option(label, 'dyn|' + pk.year + '|' + rKey + '|' + pk.orig));
    });
    // 2026 picks (draft already run / order known): keep the generic tiers
    ((window.SIM_SLEEPER && window.SIM_SLEEPER.pickAssets) || [])
      .filter(function (p) { return p.n.indexOf('2026') === 0; })
      .sort(function (a, b) { return pickVal(b, sf) - pickVal(a, sf); })
      .forEach(function (pk) { sel.add(new Option(pk.n + ' (' + pickVal(pk, sf).toLocaleString() + ')', pk.n)); });
  }
  function tradeIsSF() {
    var L = state.league;
    return !!(L && L.lineupSlots && L.lineupSlots.indexOf('SUPER_FLEX') >= 0);
  }
  function pickVal(pk, sf) { return (sf ? pk.ktcSf : pk.ktc1qb) || 0; }
  function playerKtc(sid, sf) {
    var p = state.players.bySid[sid];
    if (!p) return 0;
    return (sf ? p.ktcSf : p.ktc1qb) || 0;
  }
  function fillTradePlayers(side) {
    var L = state.league;
    if (!L) return;
    var rid = +$('tr-' + side).value;
    var t = L.teams.find(function (x) { return x.rosterId === rid; });
    var sel = $('tr-' + side + '-players');
    sel.innerHTML = '';
    if (!t) return;
    var ps = t.playerIds.map(function (id) { return state.players.bySid[id]; }).filter(Boolean)
      .sort(function (a, b) { return E.seasonPoints(b, L.scoring) - E.seasonPoints(a, L.scoring); });
    ps.forEach(function (p) {
      sel.add(new Option(p.name + ' (' + p.pos + ', ' + E.seasonPoints(p, L.scoring).toFixed(0) + ')', p.sid));
    });
  }
  function analyzeTrade() {
    var L = state.league;
    if (!L) { $('tr-note').textContent = 'Load a league first.'; return; }
    var aId = +$('tr-a').value, bId = +$('tr-b').value;
    if (aId === bId) { $('tr-note').textContent = 'Pick two different teams.'; return; }
    var giveA = Array.from($('tr-a-players').selectedOptions).map(function (o) { return o.value; });
    var giveB = Array.from($('tr-b-players').selectedOptions).map(function (o) { return o.value; });
    var pickA = Array.from($('tr-a-picks').selectedOptions).map(function (o) { return o.value; });
    var pickB = Array.from($('tr-b-picks').selectedOptions).map(function (o) { return o.value; });
    if (!giveA.length && !giveB.length && !pickA.length && !pickB.length) { $('tr-note').textContent = 'Select at least one player or pick.'; return; }
    var sims = 3000, seed = 1234; // same seed both runs -> deltas are less noisy
    var opts = {
      sims: sims, seed: seed, scoring: L.scoring, schedule: state.schedule, players: state.players,
      pairsByWeek: L.pairsByWeek, regWeeks: L.regWeeks, playoffTeams: L.playoffTeams, playoffReseed: !!L.playoffReseed,
      playoffStart: L.playoffStart, lineupSlots: L.lineupSlots,
      unavailable: L.unavailable || {}, currentWeek: L.currentWeek || 1
    };
    var t0 = performance.now();
    var base = E.simLeague(Object.assign({ teams: L.teams }, opts));
    var mod = L.teams.map(function (t) {
      return { rosterId: t.rosterId, name: t.name, record: t.record, playerIds: t.playerIds.slice() };
    });
    var A = mod.find(function (t) { return t.rosterId === aId; });
    var B = mod.find(function (t) { return t.rosterId === bId; });
    A.playerIds = A.playerIds.filter(function (id) { return giveA.indexOf(id) < 0; }).concat(giveB);
    B.playerIds = B.playerIds.filter(function (id) { return giveB.indexOf(id) < 0; }).concat(giveA);
    var after = E.simLeague(Object.assign({ teams: mod }, opts));
    var ms = performance.now() - t0;

    function ppgOf(r) {
      var wks = Object.keys(r.weekly);
      return wks.length ? wks.reduce(function (s, w) { return s + r.weekly[w].avgPf; }, 0) / wks.length : 0;
    }
    function nm(sid) { var p = state.players.bySid[sid]; return p ? p.name : sid; }
    var METRICS = [
      ['Avg wins', function (r) { return r.avgWins; }, 2],
      ['PPG', ppgOf, 1],
      ['Playoff odds', function (r) { return r.playoffOdds; }, 'pct'],
      ['Bye odds', function (r) { return r.byeOdds; }, 'pct'],
      ['Finals odds', function (r) { return r.finalsOdds; }, 'pct'],
      ['Title odds', function (r) { return r.titleOdds; }, 'pct']
    ];
    function prettyPick(e) { return e.indexOf('dyn|') === 0 ? e.split('|').slice(1, 3).join(' ') : e; }
    var sideAtxt = giveA.map(nm).concat(pickA.map(prettyPick)).join(', ') || 'nothing';
    var sideBtxt = giveB.map(nm).concat(pickB.map(prettyPick)).join(', ') || 'nothing';
    var html = '<p class="dim" style="font-size:12px">' +
      esc(sideAtxt) + ' &#8646; ' + esc(sideBtxt) +
      ' · ' + sims + ' sims each side in ' + ms.toFixed(0) + 'ms</p>' +
      '<table style="max-width:820px"><thead><tr><th class="l">Metric</th>';
    [aId, bId].forEach(function (rid) {
      var t = L.teams.find(function (x) { return x.rosterId === rid; });
      html += '<th colspan="3" class="l">' + esc(t.name) + '</th>';
    });
    html += '</tr><tr><th></th><th>Before</th><th>After</th><th>&Delta;</th><th>Before</th><th>After</th><th>&Delta;</th></tr></thead><tbody>';
    METRICS.forEach(function (m) {
      html += '<tr><td class="l">' + m[0] + '</td>';
      [aId, bId].forEach(function (rid) {
        var rb = base.find(function (r) { return r.team.rosterId === rid; });
        var ra = after.find(function (r) { return r.team.rosterId === rid; });
        var vb = m[1](rb), va = m[1](ra), d = va - vb;
        var dTxt = m[2] === 'pct' ? (d >= 0 ? '+' : '') + (100 * d).toFixed(1) + 'pp' : (d >= 0 ? '+' : '') + d.toFixed(m[2]);
        var col = Math.abs(m[2] === 'pct' ? d * 100 : d) < 0.05 ? 'var(--dim)' : (d > 0 ? 'var(--acc)' : '#f85149');
        html += '<td>' + (m[2] === 'pct' ? pctf(vb) : vb.toFixed(m[2])) + '</td><td>' + (m[2] === 'pct' ? pctf(va) : va.toFixed(m[2])) +
          '</td><td><b style="color:' + col + '">' + dTxt + '</b></td>';
      });
      html += '</tr>';
    });
    html += '</tbody></table>';

    // ---- dynasty value ledger (KTC): players + picks on one scale ----
    var sf = tradeIsSF();
    var pkMap = {};
    ((window.SIM_SLEEPER && window.SIM_SLEEPER.pickAssets) || []).forEach(function (pk) { pkMap[pk.n] = pk; });
    function pickWorth(entry) {
      if (entry.indexOf('dyn|') === 0) {
        var parts = entry.split('|'); // dyn|year|round|origRosterId
        return teamPickValue(+parts[3], +parts[1], parts[2], sf) || 0;
      }
      return pkMap[entry] ? pickVal(pkMap[entry], sf) : 0;
    }
    function sumPlayers(ids) { return ids.reduce(function (s, id) { return s + playerKtc(id, sf); }, 0); }
    function sumPicks(entries) { return entries.reduce(function (s, e) { return s + pickWorth(e); }, 0); }
    var aOutP = sumPlayers(giveA), aOutK = sumPicks(pickA), aIn = sumPlayers(giveB) + sumPicks(pickB);
    var bOutP = sumPlayers(giveB), bOutK = sumPicks(pickB), bIn = sumPlayers(giveA) + sumPicks(pickA);
    html += '<h3>Dynasty value (KTC ' + (sf ? 'Superflex' : '1QB') + ')</h3>' +
      '<table style="max-width:720px"><thead><tr><th class="l">Team</th><th>Players out</th><th>Picks out</th>' +
      '<th>Value out</th><th>Value in</th><th>Net</th></tr></thead><tbody>';
    [[aId, aOutP, aOutK, aIn], [bId, bOutP, bOutK, bIn]].forEach(function (row) {
      var t = L.teams.find(function (x) { return x.rosterId === row[0]; });
      var net = row[3] - (row[1] + row[2]);
      var col = Math.abs(net) < 200 ? 'var(--dim)' : (net > 0 ? 'var(--acc)' : '#f85149');
      html += '<tr><td class="l"><b>' + esc(t.name) + '</b></td><td>' + row[1].toLocaleString() +
        '</td><td>' + row[2].toLocaleString() + '</td><td>' + (row[1] + row[2]).toLocaleString() +
        '</td><td>' + row[3].toLocaleString() + '</td><td><b style="color:' + col + '">' +
        (net >= 0 ? '+' : '') + net.toLocaleString() + '</b></td></tr>';
    });
    html += '</tbody></table>' +
      '<p class="dim" style="font-size:11px">Same 3000 sim seeds on both sides, so sim deltas isolate the trade. Picks score ZERO in the 2026 season sim — ' +
      'their worth lives in the dynasty ledger. 2027/2028 picks are valued from the SENDING team\'s simmed finish distribution ' +
      '(draft order = inverse standings, full distribution over the KTC early/mid/late curve — a rebuilder\'s 1st &gt; a contender\'s 1st; ' +
      '2028s regress 50% to league average). 2026 picks use generic tiers (order already known). Pick lists show each team\'s ACTUAL ' +
      'inventory from Sleeper\'s traded-picks record — picks dealt away are gone, acquired picks show "via" the original team and are ' +
      'valued by THAT team\'s projected finish. Players without a KTC value count 0. ' +
      'Read the panels together: the sim prices THIS season, the ledger prices the future.</p>';
    $('tr-result').innerHTML = html;
  }

  // Playoff shape override (Jack 2026-10-05: 14-team ESPN league with 7 spots loaded as the assumed 6). The
  // loader's numbers are the default; the Playoffs boxes override them per league id (localStorage, this browser).
  function poKey(L) { return 'simlab_po_' + L.id; }
  function applyPlayoffShape(L, nTeams, start) {
    nTeams = Math.max(2, Math.min(L.teams.length, Math.round(nTeams) || L.playoffTeams));
    start = Math.max(2, Math.min(18, Math.round(start) || L.playoffStart));
    if (start !== L.playoffStart) {
      var all = []; for (var w = 1; w < start; w++) all.push(w);
      if (L.synthSchedule) L.pairsByWeek = roundRobin(L.teams.map(function (t) { return t.rosterId; }), all);
      L.regWeeks = all.filter(function (w2) { return w2 >= (L.currentWeek || 1); });
    }
    L.playoffTeams = nTeams; L.playoffStart = start;
  }
  function syncPlayoffInputs() {
    var L = state.league;
    if (!L.poDefault) {
      L.poDefault = { teams: L.playoffTeams, start: L.playoffStart };
      try {
        var sv = JSON.parse(localStorage.getItem(poKey(L)) || 'null');
        if (sv && sv.teams && sv.start) applyPlayoffShape(L, sv.teams, sv.start);
      } catch (e) { /* storage blocked — loader numbers stand */ }
    }
    $('lg-po-teams').value = L.playoffTeams; $('lg-po-start').value = L.playoffStart;
  }
  function readPlayoffInputs() {
    var L = state.league;
    applyPlayoffShape(L, +$('lg-po-teams').value, +$('lg-po-start').value);
    $('lg-po-teams').value = L.playoffTeams; $('lg-po-start').value = L.playoffStart;
    try {
      if (L.poDefault && L.playoffTeams === L.poDefault.teams && L.playoffStart === L.poDefault.start) localStorage.removeItem(poKey(L));
      else localStorage.setItem(poKey(L), JSON.stringify({ teams: L.playoffTeams, start: L.playoffStart }));
    } catch (e) { /* storage blocked — override lasts this load only */ }
  }

  function renderLeagueTeams() {
    var L = state.league;
    syncPlayoffInputs();
    $('lg-teams-h').style.display = '';
    fillTradeSelects();
    var unav = L.unavailable || {};
    var html = '<table><thead><tr><th class="l">Team</th><th>Roster</th><th>Matched</th><th class="l">Top players</th><th class="l">Out / IR (excluded)</th></tr></thead><tbody>';
    L.teams.forEach(function (t) {
      var ps = t.playerIds.map(function (id) { return state.players.bySid[id]; }).filter(Boolean);
      var top = ps.slice().sort(function (a, b) { return E.seasonPoints(b, L.scoring) - E.seasonPoints(a, L.scoring); })
        .slice(0, 4).map(function (p) { return p.name; }).join(', ');
      var flagged = ps.filter(function (p) { return unav[p.sid]; })
        .map(function (p) { return p.name + ' (' + unav[p.sid].toUpperCase() + ')'; }).join(', ');
      html += '<tr><td class="l"><b>' + esc(t.name) + '</b></td><td>' + t.playerIds.length + '</td><td>' + ps.length +
        '</td><td class="l dim">' + esc(top) + '</td><td class="l dim">' + esc(flagged || '—') + '</td></tr>';
    });
    $('lg-teams').innerHTML = html + '</tbody></table>';
  }

  function runLeagueSim() {
    var L = state.league;
    if (!L) { $('lg-note').textContent = 'Load a league (or the demo) first.'; return; }
    var sims = Math.max(10, Math.min(10000, +$('lg-sims').value || 100));
    readPlayoffInputs();
    runBlocking('lg-run', 'lg-note', 'Simulating "' + L.name + '" ' + sims + 'x…', function () {
      var t0 = performance.now();
      var lockedPts = null, lockedTeams = null, LK = state.locked;
      if (LK && LK.week === (L.currentWeek || 1) && window.SIM_LOCK_PLAYED !== false) {
        lockedPts = {}; lockedTeams = {};
        Object.keys(LK.teams).forEach(function (t) { lockedTeams[t] = 1; });
        var scL = L.scoring || {};
        Object.keys(state.players.bySid).forEach(function (sid) {
          var s2 = LK.stats[sid], p2 = state.players.bySid[sid];
          if (!s2 || s2.pts_std == null) return;
          var v = s2.pts_std;
          if (!p2.isDST && p2.pos !== 'K') v += (scL.rec != null ? scL.rec : 1) * (s2.rec || 0) + ((scL.pass_td != null ? scL.pass_td : 4) - 4) * (s2.pass_td || 0) + (p2.pos === 'TE' ? (scL.bonus_rec_te || 0) * (s2.rec || 0) : 0);
          lockedPts[sid] = +v.toFixed(2);
        });
      }
      // snapshot-sourced lineups only count for games that had kicked off by the time of the sync
      var lockedRealUse = lockedTeams ? (L.lockedReal || null) : null, staleReal = 0;
      if (lockedRealUse && L.lockedRealAt) {
        var flt = {};
        Object.keys(lockedRealUse).forEach(function (rid) {
          flt[rid] = {};
          Object.keys(lockedRealUse[rid]).forEach(function (sid) {
            var p3 = state.players.bySid[sid], kick = p3 ? LK.teams[p3.tm] : null;
            if (!kick) return;
            if (L.lockedRealAt >= kick) flt[rid][sid] = lockedRealUse[rid][sid]; else staleReal++;
          });
        });
        lockedRealUse = flt;
      }
      state.leagueResults = E.simLeague({
        lockedPts: lockedPts, lockedTeams: lockedTeams, lockedReal: lockedRealUse,
        sims: sims, scoring: L.scoring, schedule: state.schedule, players: state.players,
        teams: L.teams, pairsByWeek: L.pairsByWeek, regWeeks: L.regWeeks,
        playoffTeams: L.playoffTeams, playoffReseed: !!L.playoffReseed, playoffStart: L.playoffStart, lineupSlots: L.lineupSlots,
        unavailable: L.unavailable || {}, currentWeek: L.currentWeek || 1
      });
      var ms = performance.now() - t0;
      // PPG + SOS from the weekly tallies (SOS = avg opponent score faced —
      // includes their byes, correlations, everything). Rank 1 = hardest.
      state.leagueResults.forEach(function (r) {
        var wks = Object.keys(r.weekly);
        var pf = 0, pa = 0;
        wks.forEach(function (wk) { pf += r.weekly[wk].avgPf; pa += r.weekly[wk].avgPa; });
        r.ppg = wks.length ? pf / wks.length : 0;
        r.sos = wks.length ? pa / wks.length : 0;
      });
      var sosOrder = state.leagueResults.slice().sort(function (a, b) { return b.sos - a.sos; });
      state.leagueResults.forEach(function (r) { r.sosRank = sosOrder.indexOf(r) + 1; });

      var poByes = Math.pow(2, E.bracketRounds(L.playoffTeams)) - L.playoffTeams;
      $('lg-note').textContent = '"' + L.name + '" — ' + sims + ' season sims in ' + ms.toFixed(0) + 'ms.' +
        ' Playoffs: ' + L.playoffTeams + ' teams from wk ' + L.playoffStart + (poByes ? ', top ' + (poByes > 1 ? poByes + ' seeds get' : 'seed gets') + ' a bye' : ', no byes') + '.' + (lockedTeams ? ' Wk ' + LK.week + ' played games banked (' + Object.keys(LK.teams).join('/') + (L.lockedReal ? ', real lineups' + (L.lockedRealAt ? ' from the site sync' : '') + (staleReal ? ' — ' + staleReal + ' players synced BEFORE kickoff use sim lineups, re-sync the league' : '') : ', sim lineups') + ').' : '') +
        (L.synthSchedule ? (L.platform === 'yahoo' || L.platform === 'mff'
          ? ' Schedule is synthesized round-robin (no matchup feed on this import path).'
          : ' Schedule is synthesized round-robin until the platform publishes real matchups.') : '');
      $('lg-detail').innerHTML = '';
      renderLeagueTable();
      populateLeagueWeeks();
    });
  }

  var LEAGUE_COLS = [
    { h: '#' },
    { h: 'Team', l: 1, k: 'team', dir: 'asc', get: function (r) { return r.team.name; } },
    { h: 'Avg W', k: 'avgw', get: function (r) { return r.avgWins; } },
    { h: 'Med W', k: 'medw', get: function (r) { return medianFromCounts(r.winCounts, r.sims); } },
    { h: 'PPG', k: 'ppg', get: function (r) { return r.ppg; } },
    { h: 'Avg PF', k: 'pf', get: function (r) { return r.avgPF; } },
    { h: 'SOS (opp PPG)', k: 'sos', get: function (r) { return r.sos; } },
    { h: 'Playoffs', k: 'po', get: function (r) { return r.playoffOdds; } },
    { h: 'Bye', k: 'bye', get: function (r) { return r.byeOdds; } },
    { h: 'Finals', k: 'fin', get: function (r) { return r.finalsOdds; } },
    { h: 'Title', k: 'title', get: function (r) { return r.titleOdds; } },
    { h: 'Med fin', k: 'medfin', dir: 'asc', get: function (r) { return medianFromCounts(r.placeCounts, r.sims); } },
    { h: 'Most likely finish', l: 1 }
  ];
  // book-style O/U market cell: .5 line + over/under prices (vigged)
  function ouCell(line, pOver) {
    return fmtLine(line) + ' <span class="dim">o' + mlBook(pOver) + '/u' + mlBook(1 - pOver) + '</span>';
  }
  // finish-position O/U: the k.5 line where the finish distribution splits
  // closest to 50/50 (under = finishing k-th or better)
  function finOuCell(r, nTeams) {
    var cum = 0, best = null;
    for (var k = 1; k < nTeams; k++) {
      cum += (r.placeCounts[k] || 0);
      var pU = cum / r.sims;
      if (!best || Math.abs(pU - 0.5) < Math.abs(best.pU - 0.5)) best = { line: k + 0.5, pU: pU };
    }
    return best ? ouCell(best.line, 1 - best.pU) : '—';
  }
  // win-total O/U: the k.5 line where the win distribution splits closest to 50/50
  function winOuCell(r) {
    var keys = Object.keys(r.winCounts).map(Number);
    if (!keys.length) return '—';
    var maxW = Math.max.apply(null, keys);
    var cum = 0, best = null;
    for (var k = 0; k < maxW; k++) {
      cum += (r.winCounts[k] || 0);
      var pU = cum / r.sims; // under = k wins or fewer
      if (!best || Math.abs(pU - 0.5) < Math.abs(best.pU - 0.5)) best = { line: k + 0.5, pU: pU };
    }
    return best ? ouCell(best.line, 1 - best.pU) : '—';
  }
  // season-PF O/U: line = median sim PF snapped to the .5 grid
  function pfOuCell(r) {
    if (!r.pfDist || !r.pfDist.length) return fmt(r.avgPF, 0);
    if (!r._pfSorted) r._pfSorted = Float64Array.from(r.pfDist).sort();
    var a = r._pfSorted;
    var L = Math.floor(a[a.length >> 1]) + 0.5;
    var lo = 0, hi = a.length;
    while (lo < hi) { var m = (lo + hi) >> 1; if (a[m] > L) hi = m; else lo = m + 1; }
    return ouCell(L, (a.length - lo) / a.length);
  }

  function renderLeagueTable() {
    if (!state.leagueResults) return;
    var book = bookMode();
    var odds = book ? mlBook : pctf; // futures board vs raw sim percentages
    var ss = state.leagueSort = state.leagueSort || { key: null, dir: 'desc' };
    var rows = applySort(state.leagueResults, LEAGUE_COLS, ss);
    var html = '<table><thead>' + thRow(LEAGUE_COLS, ss) + '</thead><tbody>';
    rows.forEach(function (r, i) {
      var sims = r.sims;
      var best = Object.keys(r.placeCounts).sort(function (a, b) { return r.placeCounts[b] - r.placeCounts[a]; })[0];
      var medPlace = medianFromCounts(r.placeCounts, sims);
      var sosCol = r.sosRank <= 3 ? '#f85149' : (r.sosRank >= state.leagueResults.length - 2 ? 'var(--acc)' : 'var(--tx)');
      html += '<tr data-i="' + state.leagueResults.indexOf(r) + '"><td>' + (i + 1) + '</td><td class="l"><b>' + esc(r.team.name) + '</b></td><td class="dim">' + fmt(r.avgWins) +
        '</td><td>' + (book ? winOuCell(r) : '<b>' + fmt(medianFromCounts(r.winCounts, sims), 0) + '</b>') +
        '</td><td><b>' + fmt(r.ppg) + '</b></td><td class="dim">' + (book ? pfOuCell(r) : fmt(r.avgPF, 0)) +
        '</td><td style="color:' + sosCol + '">' + fmt(r.sos) + ' <span class="dim">#' + r.sosRank + '</span>' +
        '</td><td>' + odds(r.playoffOdds) + '</td><td>' + odds(r.byeOdds) +
        '</td><td>' + odds(r.finalsOdds) + '</td><td><b>' + odds(r.titleOdds) + '</b></td>' +
        '<td>' + (book ? finOuCell(r, state.leagueResults.length) : medPlace + getOrdinal(medPlace)) + '</td>' +
        '<td class="l dim">' + best + getOrdinal(+best) + ' (' + pctf(r.placeCounts[best] / sims) + ')</td></tr>';
    });
    html += '</tbody></table>' +
      '<p class="dim" style="font-size:11px">Click a team to see its week-by-week win odds; click a column header to sort. PPG/SOS cover the simmed (remaining) regular-season weeks — ' +
      'SOS = average opponent score actually faced (#1 = hardest schedule, red; green = softest).' +
      (book ? ' Playoffs/Bye/Finals/Title are futures-style prices (same ~20-cent vig as the weekly board; — = never happened in the sims). ' +
        'MED W, AVG PF and MED FIN become O/U markets: a .5 line set where the sim distribution splits closest to 50/50, with vigged over/under prices ' +
        '(win total over = more wins; finish under = that place or better).' : '') + '</p>';

    // ---- season futures board: every season market as odds ----
    var nTeams = state.leagueResults.length;
    var cell = book
      ? function (p) { return mlBook(p); }
      : function (p) { return pctf(p) + ' <span class="dim">' + mlFair(p) + '</span>'; };
    html += '<h3>Season futures</h3>' +
      '<table style="max-width:960px"><thead><tr><th class="l">Team</th><th>Most PF</th><th>Reg-season 1st</th>' +
      '<th>Playoffs</th><th>Bye</th><th>Finals</th><th>Title</th><th>Last place</th></tr></thead><tbody>';
    state.leagueResults.forEach(function (r, ri) {
      var reg1 = (r.placeCounts[1] || 0) / r.sims;
      var last = (r.placeCounts[nTeams] || 0) / r.sims;
      html += '<tr data-i="' + ri + '"><td class="l"><b>' + esc(r.team.name) + '</b></td>' +
        '<td>' + cell(r.pfLeadOdds || 0) + '</td><td>' + cell(reg1) + '</td>' +
        '<td>' + cell(r.playoffOdds) + '</td><td>' + cell(r.byeOdds) + '</td>' +
        '<td>' + cell(r.finalsOdds) + '</td><td><b>' + cell(r.titleOdds) + '</b></td>' +
        '<td>' + cell(last) + '</td></tr>';
    });
    html += '</tbody></table>' +
      '<p class="dim" style="font-size:11px">Season markets priced from the same sims, ordered by title odds. Most PF = leads the league in total points ' +
      '(the PPG/scoring title — includes any banked mid-season points); Reg-season 1st / Last place come from the finish distribution ' +
      '(click a team for the full spread). ' +
      (book ? 'Book view: ~20-cent vig + board rounding, — = never happened in the sims.'
            : 'Model view: raw sim % with the exact fair (no-vig) line beside it; flip the toggle for a vigged book board.') + '</p>';
    $('lg-table').innerHTML = html;
    document.querySelectorAll('#lg-table tbody tr').forEach(function (tr) {
      tr.style.cursor = 'pointer';
      tr.addEventListener('click', function () { renderWeekDetail(+tr.dataset.i); });
    });
    wireSort('lg-table', LEAGUE_COLS, ss, renderLeagueTable);
  }

  // ---- Weekly breakdown: pick a week, see every matchup's proj + win odds ----
  function populateLeagueWeeks() {
    var res = state.leagueResults, sel = $('lg-week');
    var prev = sel.value;
    sel.innerHTML = '';
    var wkSet = {};
    (res || []).forEach(function (r) { Object.keys(r.weekly).forEach(function (wk) { wkSet[wk] = 1; }); });
    var wks = Object.keys(wkSet).map(Number).sort(function (a, b) { return a - b; });
    wks.forEach(function (wk) { sel.add(new Option('Week ' + wk, wk)); });
    $('lg-week-wrap').style.display = wks.length ? '' : 'none';
    if (!wks.length) { $('lg-week-table').innerHTML = ''; return; }
    sel.value = wks.indexOf(+prev) >= 0 ? prev : String(wks[0]);
    renderWeekMatchups();
  }

  // win% -> American moneyline: exact fair (no-vig) conversion, book sign convention.
  // p>=.5 -> -100p/(1-p), else +100(1-p)/p — so 52% reads −108, not a rounded −110.
  function mlOdds(p) {
    p = Math.min(0.99, Math.max(0.01, p));
    var v = p >= 0.5 ? -100 * p / (1 - p) : 100 * (1 - p) / p;
    return (v > 0 ? '+' : '−') + Math.round(Math.abs(v));
  }

  // book-style price: standard ~20-cent two-way vig (a 50/50 game reads −110/−110),
  // then board rounding (nearest 5, coarser as the number grows — +1266 posts as +1300)
  function mlBook(p) {
    if (p <= 0.001) return '—'; // off the board
    var q = Math.min(0.985, Math.max(0.015, p * 1.0455));
    var v = q >= 0.5 ? -100 * q / (1 - q) : 100 * (1 - q) / q;
    var a = Math.abs(v);
    var step = a >= 1000 ? 100 : a >= 500 ? 50 : a >= 200 ? 10 : 5;
    a = Math.round(a / step) * step;
    if (a === 100) return 'EVEN'; // no board posts −100/+100
    return (v > 0 ? '+' : '−') + a;
  }
  function bookMode() { return $('lg-week-view').value === 'book'; }
  // exact fair line for futures-sized probabilities (no weekly-range clamp)
  function mlFair(p) {
    if (p <= 0.001) return '—';
    if (p >= 0.999) return '−99900';
    var v = p >= 0.5 ? -100 * p / (1 - p) : 100 * (1 - p) / p;
    return (v > 0 ? '+' : '−') + Math.round(Math.abs(v));
  }
  function fmtLine(x) { return x % 1 ? x.toFixed(1) : String(x); } // 16.5 / 16, book-style

  function renderWeekMatchups() {
    var L = state.league, res = state.leagueResults;
    if (!L || !res) return;
    var wk = +$('lg-week').value;
    var nameById = {};
    L.teams.forEach(function (t) { nameById[t.rosterId] = t.name; });
    var byId = {};
    res.forEach(function (r, i) { byId[r.team.rosterId] = { r: r, idx: i }; });
    var seen = {}, games = [];
    res.forEach(function (r) {
      var w = r.weekly[wk];
      if (!w) return;
      var a = r.team.rosterId, b = w.opp;
      // id-type-agnostic pair key (MFF/Yahoo imports can carry string team ids)
      var key = String(a) < String(b) ? a + '|' + b : b + '|' + a;
      if (seen[key]) return;
      seen[key] = 1;
      var o = byId[b], wo = o && o.r.weekly[wk];
      var fav = { id: a, idx: byId[a].idx, win: w.winPct, pf: w.avgPf };
      var dog = { id: b, idx: o ? o.idx : -1, win: wo ? wo.winPct : 1 - w.winPct, pf: w.avgPa };
      if (dog.win > fav.win) { var tmp = fav; fav = dog; dog = tmp; }
      games.push({ fav: fav, dog: dog, total: fav.pf + dog.pf, margin: fav.pf - dog.pf });
    });
    if (!games.length) { $('lg-week-table').innerHTML = '<p class="dim">No matchups simmed for week ' + wk + '.</p>'; return; }
    games.sort(function (a, b) { return a.fav.win - b.fav.win; }); // closest game first
    var maxTotal = games.reduce(function (m, g) { return Math.max(m, g.total); }, 0);
    function teamCell(side, bold) {
      var tag = bold ? 'b' : 'span';
      return '<td class="l"><' + tag + ' class="lgwk-t" data-t="' + side.idx + '" style="cursor:pointer">' +
        esc(nameById[side.id] || ('Roster ' + side.id)) + '</' + tag + '></td>';
    }
    function tagsFor(g, i) {
      var tags = [];
      if (i === 0 && games.length > 1) tags.push('<span style="color:var(--acc)">GAME OF THE WEEK</span>');
      if (g.total === maxTotal && games.length > 1) tags.push('<span style="color:#d29922">TOP TOTAL</span>');
      return tags.join(' ');
    }
    var html;
    if (bookMode()) {
      html = '<table style="max-width:880px"><thead><tr><th class="l">Favorite</th><th>Spread</th><th>ML</th>' +
        '<th class="l">Underdog</th><th>Spread</th><th>ML</th><th>O/U</th><th class="l"></th></tr></thead><tbody>';
      games.forEach(function (g, i) {
        var sp = Math.round(g.margin * 2) / 2; // half-point board
        var spFav = sp === 0 ? 'PK' : (sp > 0 ? '−' : '+') + fmtLine(Math.abs(sp));
        var spDog = sp === 0 ? 'PK' : (sp > 0 ? '+' : '−') + fmtLine(Math.abs(sp));
        html += '<tr>' + teamCell(g.fav, true) + '<td>' + spFav + '</td><td><b>' + mlBook(g.fav.win) + '</b></td>' +
          teamCell(g.dog, false) + '<td>' + spDog + '</td><td>' + mlBook(g.dog.win) + '</td>' +
          '<td>' + fmtLine(Math.round(g.total * 2) / 2) + '</td><td class="l">' + tagsFor(g, i) + '</td></tr>';
      });
      html += '</tbody></table>' +
        '<p class="dim" style="font-size:11px">Book-style board, closest game first: ML carries a standard ~20-cent vig ' +
        '(a coin-flip game posts −110/−110) with board rounding; spread = the sims\' projected margin to the half point (PK = pick\'em); ' +
        'O/U = projected combined total. Flip to Model odds for the fair lines, win % and projected scores. Click a team for its week-by-week drawer.</p>';
    } else {
      html = '<table style="max-width:980px"><thead><tr><th class="l">Favorite</th><th>Win %</th><th>ML</th><th>Proj</th>' +
        '<th class="l">Underdog</th><th>Win %</th><th>ML</th><th>Proj</th><th>Proj total</th><th>Margin</th><th class="l"></th></tr></thead><tbody>';
      games.forEach(function (g, i) {
        var favCol = g.fav.win >= 0.6 ? 'var(--acc)' : 'var(--tx)';
        html += '<tr>' + teamCell(g.fav, true) +
          '<td><b style="color:' + favCol + '">' + pctf(g.fav.win) + '</b></td><td>' + mlOdds(g.fav.win) + '</td><td>' + fmt(g.fav.pf) + '</td>' +
          teamCell(g.dog, false) +
          '<td>' + pctf(g.dog.win) + '</td><td>' + mlOdds(g.dog.win) + '</td><td class="dim">' + fmt(g.dog.pf) + '</td>' +
          '<td>' + fmt(g.total) + '</td><td>' + fmt(Math.round(g.margin * 10) / 10 + 0) + '</td><td class="l">' + tagsFor(g, i) + '</td></tr>';
      });
      html += '</tbody></table>' +
        '<p class="dim" style="font-size:11px">All matchups for the selected week, closest game first. Win % and projected scores come straight from the season sims ' +
        '(correlations, byes, injury windows and each sim\'s season shock included); ML is the exact fair (no-vig) American moneyline for that win % — ' +
        'the Sportsbook view shows the same games as a vigged book board. ' +
        'Margin = favorite\'s proj minus underdog\'s. Playoff rounds aren\'t fixed matchups — click a team (here or in the standings) for its playoff-week odds.</p>';
    }
    $('lg-week-table').innerHTML = html;
    document.querySelectorAll('#lg-week-table .lgwk-t').forEach(function (el) {
      el.addEventListener('click', function () { if (+el.dataset.t >= 0) renderWeekDetail(+el.dataset.t); });
    });
  }

  // Week-by-week win odds for one team (click a row in the sim results).
  function renderWeekDetail(idx) {
    var L = state.league, r = state.leagueResults[idx];
    if (!r) return;
    var nameById = {};
    L.teams.forEach(function (t) { nameById[t.rosterId] = t.name; });
    var wks = Object.keys(r.weekly).map(Number).sort(function (a, b) { return a - b; });
    var html = '<h3>' + esc(r.team.name) + ' — week-by-week (' + wks.length + ' matchups simmed)</h3>' +
      '<table style="max-width:640px"><thead><tr><th>Wk</th><th class="l">Opponent</th><th>Win %</th>' +
      '<th>Proj score</th><th>Opp proj</th></tr></thead><tbody>';
    wks.forEach(function (wk) {
      var w = r.weekly[wk];
      var col = w.winPct >= 0.6 ? 'var(--acc)' : (w.winPct <= 0.4 ? '#f85149' : 'var(--tx)');
      html += '<tr><td>' + wk + '</td><td class="l">' + esc(nameById[w.opp] || ('Roster ' + w.opp)) +
        '</td><td><b style="color:' + col + '">' + pctf(w.winPct) + '</b></td>' +
        '<td>' + fmt(w.avgPf) + '</td><td class="dim">' + fmt(w.avgPa) + '</td></tr>';
    });
    html += '</tbody></table>';

    // full regular-season finish distribution (the modal "most likely finish"
    // in the standings undersells teams whose outcomes are spread out)
    var sims = r.sims || 1;
    var nTeams = L.teams.length;
    var modeP = 0;
    for (var pl = 1; pl <= nTeams; pl++) modeP = Math.max(modeP, (r.placeCounts[pl] || 0) / sims);
    html += '<h3>Regular-season finish distribution</h3>' +
      '<table style="max-width:820px"><thead><tr>';
    for (pl = 1; pl <= nTeams; pl++) html += '<th>' + pl + getOrdinal(pl) + '</th>';
    html += '</tr></thead><tbody><tr>';
    for (pl = 1; pl <= nTeams; pl++) {
      var pp = (r.placeCounts[pl] || 0) / sims;
      var hot = pp === modeP && pp > 0;
      var dimmed = pp < 0.02;
      html += '<td' + (hot ? ' style="color:var(--acc);font-weight:700"' : (dimmed ? ' class="dim"' : '')) + '>' +
        (pp > 0 ? (100 * pp).toFixed(1) + '%' : '—') + '</td>';
    }
    html += '</tr></tbody></table>';

    // playoff weeks: projected score + who you'd face and how often you're alive
    var roundName = {}, nRounds = E.bracketRounds(L.playoffTeams);
    for (var ri = 0; ri < nRounds; ri++) {
      var fromEnd = nRounds - 1 - ri;
      roundName[L.playoffStart + ri] = ['Championship', 'Semis', 'Quarterfinals'][fromEnd] || ('Round ' + (ri + 1));
    }
    var pWks = Object.keys(roundName).map(Number).sort(function (a, b) { return a - b; });
    html += '<h3>Playoff weeks (if the bracket goes your way)</h3>' +
      '<table style="max-width:760px"><thead><tr><th>Wk</th><th class="l">Round</th><th>Alive</th>' +
      '<th>Proj score</th><th class="l">Most likely opponents</th></tr></thead><tbody>';
    pWks.forEach(function (wk) {
      var opps = r.playoffOpps[wk] || {};
      var alive = Object.keys(opps).reduce(function (s, k) { return s + opps[k]; }, 0) / sims;
      var top = Object.keys(opps).sort(function (a, b) { return opps[b] - opps[a]; }).slice(0, 3)
        .map(function (rid) { return esc(nameById[rid] || rid) + ' (' + pctf(opps[rid] / sims) + ')'; }).join(', ');
      var proj = r.playoffProj ? r.playoffProj[wk] : null;
      html += '<tr><td>' + wk + '</td><td class="l">' + roundName[wk] + '</td><td>' + pctf(alive) +
        '</td><td>' + (proj != null ? fmt(proj) : '—') + '</td><td class="l dim">' + (top || '—') + '</td></tr>';
    });
    html += '</tbody></table>' +
      '<p class="dim" style="font-size:11px">"Alive" = % of sims this team played in that round (byes reduce Round 1 for top seeds — a bye week means no game, not elimination). ' +
      'Opponent odds are % of ALL sims, so they sum to the alive rate. Proj score = optimal lineup means for that NFL week (byes/injury windows included).</p>';
    $('lg-detail').innerHTML = html;
    $('lg-detail').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  function getOrdinal(n) { var s = ['th', 'st', 'nd', 'rd'], v = n % 100; return s[(v - 20) % 10] || s[v] || s[0]; }

  // ---------------- BEST BALL PORTFOLIO (Underdog import) ----------------
  // Two Underdog CSV shapes import here (mix freely, multiple files at once):
  //  * EXPOSURE / portfolio export — one row per pick YOU made across all
  //    your drafts (teams grouped by the Draft column). Opponents unknown,
  //    so the optional synthetic ADP pod supplies advance odds.
  //  * FULL DRAFT BOARD export — every pick of one draft (12x18 = 216 rows).
  //    Slots are derived from the snake pick numbers, so all 12 REAL rosters
  //    come in and advance odds are simmed against the actual opponents.
  //    Your team is spotted by your UD username (bar input, if the CSV has a
  //    drafter column) or by an exposure import of the same draft id.
  // Every player is sampled ONCE per sim and shared across all squads, so
  // portfolio-level and pod-level correlation is real.
  var BB_REG_TO = 14; // Underdog BBM regular season = weeks 1-14
  var BB_USER_COLS = ['Username', 'Picked By', 'Drafted By', 'User', 'Entry Name', 'Team Name', 'Display Name'];

  function importBBFile(ev) {
    var files = Array.prototype.slice.call(ev.target.files || []);
    if (!files.length) return;
    var texts = [], pending = files.length;
    files.forEach(function (f, i) {
      var reader = new FileReader();
      reader.onload = function () {
        texts[i] = String(reader.result);
        if (--pending === 0) {
          try { importBBTexts(texts); }
          catch (e) { $('bb-note').textContent = 'Import failed: ' + e.message; }
          ev.target.value = '';
        }
      };
      reader.readAsText(f);
    });
  }

  function importBBTexts(texts) {
    if (!state.bb) state.bb = { drafts: {}, teams: [], results: null };
    var drafts = state.bb.drafts || {};
    texts.forEach(function (t) {
      parseBBCsv(t).forEach(function (d) { mergeBBDraft(drafts, d); });
    });
    state.bb = { drafts: drafts, results: null };
    saveBB();
    rebuildBBTeams();
    $('bb-table').innerHTML = '';
    $('bb-summary').innerHTML = '';
    $('bb-detail').innerHTML = '';
    renderBBSummary('Imported ');
  }
  window._bbImportText = function (text) { importBBTexts([text]); }; // test hook

  // A full board replaces an exposure import of the same draft (it's a
  // superset) but inherits the exposure's slot as "mine"; an exposure import
  // landing on an existing full board just marks which slot is yours.
  function mergeBBDraft(drafts, d) {
    var ex = drafts[d.id];
    if (ex && ex.full && !d.full) { ex.userSlot = d.userSlot; return; }
    if (ex && !ex.full && d.full && d.userSlot == null) d.userSlot = ex.userSlot;
    drafts[d.id] = d;
  }

  function saveBB() {
    saveLS('simlab_bb_import', { at: Date.now(), v: 2, drafts: state.bb.drafts });
  }

  function loadBBFromLS() {
    var saved = loadLS('simlab_bb_import', null);
    if (!saved) return;
    var drafts = saved.drafts;
    if (!drafts && saved.teams) { // v1 format: exposure-only team list
      drafts = {};
      saved.teams.forEach(function (t) {
        drafts[t.id] = { id: t.id, title: t.title, fee: t.fee, size: t.size, date: t.date,
          full: false, userSlot: t.slot, picks: t.picks };
      });
    }
    if (!drafts || !Object.keys(drafts).length) return;
    state.bb = { drafts: drafts, results: null };
    rebuildBBTeams();
    renderBBSummary('Loaded saved import (' + new Date(saved.at).toISOString().slice(0, 10) + ') — ');
  }

  function clearBB() {
    localStorage.removeItem('simlab_bb_import');
    state.bb = null;
    $('bb-table').innerHTML = '';
    $('bb-summary').innerHTML = '';
    $('bb-detail').innerHTML = '';
    $('bb-note').textContent = 'Import cleared.';
  }

  // ---------------- MFF cloud portfolio (extension-synced) ----------------
  // The Underdog Draft Helper extension syncs the portfolio to the MFF site,
  // which mirrors it to Firestore: user_game_data/{uid}.underdogPortfolio
  // (own account) + shared/jacks_portfolio (any authed read). LOAD FROM MFF
  // signs into the same Firebase project and pulls it — no CSV needed.
  // NOTE: the site strips allTeams before the cloud save, so cloud drafts
  // carry YOUR picks only — they get the synthetic pod; real opponents still
  // need a full-draft-board CSV.
  var FB_CFG = {
    apiKey: "AIzaSyD9D_Rhb5hEpz2cBWqQr7hcFCDoluwq6uY",
    authDomain: "jackb933-website.firebaseapp.com",
    projectId: "jackb933-website",
    storageBucket: "jackb933-website.firebasestorage.app",
    messagingSenderId: "732824763527",
    appId: "1:732824763527:web:2a4b344d01ee89cf668c22"
  };
  var FB_V = 'https://www.gstatic.com/firebasejs/10.12.2/';
  var _fbLoading = null;
  function ensureFirebase() {
    if (window.firebase && firebase.apps && firebase.apps.length) return Promise.resolve();
    if (_fbLoading) return _fbLoading;
    function loadScript(src) {
      return new Promise(function (res, rej) {
        var s = document.createElement('script');
        s.src = src; s.async = true; s.onload = res;
        s.onerror = function () { rej(new Error('failed to load ' + src)); };
        document.head.appendChild(s);
      });
    }
    _fbLoading = loadScript(FB_V + 'firebase-app-compat.js')
      .then(function () {
        return Promise.all([
          loadScript(FB_V + 'firebase-auth-compat.js'),
          loadScript(FB_V + 'firebase-firestore-compat.js')
        ]);
      })
      .then(function () {
        if (!firebase.apps.length) firebase.initializeApp(FB_CFG);
      });
    return _fbLoading;
  }

  async function loadFromMff() {
    var note = $('bb-note');
    var btn = $('bb-mff');
    btn.disabled = true;
    try {
      note.textContent = 'Loading Firebase…';
      await ensureFirebase();
      // let persisted auth restore before deciding to pop the sign-in window
      var user = await new Promise(function (res) {
        var un = firebase.auth().onAuthStateChanged(function (u) { un(); res(u); });
      });
      if (!user) {
        note.textContent = 'Sign in with the Google account you use on the MFF site…';
        user = (await firebase.auth().signInWithPopup(new firebase.auth.GoogleAuthProvider())).user;
      }
      note.textContent = 'Reading your synced portfolio…';
      var db = firebase.firestore();
      var payload = null, src = '';
      var own = await db.collection('user_game_data').doc(user.uid).get();
      if (own.exists && own.data().underdogPortfolio) {
        payload = own.data().underdogPortfolio;
        src = 'your account';
      }
      if (!payload || !payload.drafts || !payload.drafts.length) {
        var sh = await db.collection('shared').doc('jacks_portfolio').get();
        if (sh.exists && sh.data() && sh.data().drafts) { payload = sh.data(); src = 'shared/jacks_portfolio'; }
      }
      if (!payload || !payload.drafts || !payload.drafts.length) {
        note.textContent = 'No synced portfolio in the cloud for ' + (user.email || 'this account') +
          ' — sync from the extension on the MFF site first, or import a CSV.';
        return;
      }
      applyCloudPortfolio(payload, src);
    } catch (e) {
      var msg = (e && (e.code || e.message)) || String(e);
      if (/unauthorized-domain/.test(msg)) {
        msg += ' — open Sim Lab via localhost, or add this domain under Firebase console → Authentication → Settings → Authorized domains.';
      }
      note.textContent = 'MFF load failed: ' + msg;
    } finally {
      btn.disabled = false;
    }
  }

  function applyCloudPortfolio(payload, src) {
    if (!state.bb) state.bb = { drafts: {}, teams: [], results: null };
    var n = 0;
    (payload.drafts || []).forEach(function (cd) {
      if (!cd || !cd.id || !Array.isArray(cd.picks) || !cd.picks.length) return;
      var picks = cd.picks.map(function (p) {
        return { name: p.name, pos: p.pos || '', tm: p.team || p.tm || '', pick: parseInt(p.pick || 0, 10) || 0, user: '' };
      }).sort(function (a, b) { return a.pick - b.pick; });
      var size = cd.size || 12;
      mergeBBDraft(state.bb.drafts, {
        id: cd.id,
        title: cd.tournament || cd.title || 'Underdog',
        teamName: cd.teamName || null,
        fee: parseFloat(cd.entry_fee != null ? cd.entry_fee : (cd.fee || 0)) || 0,
        size: size,
        date: (cd.date || '').slice(0, 10),
        phase: cd.phase || 'pre',
        full: false,
        userSlot: (picks[0] && picks[0].pick <= size) ? picks[0].pick : null,
        picks: picks
      });
      n++;
    });
    state.bb.results = null;
    saveBB();
    rebuildBBTeams();
    $('bb-table').innerHTML = '';
    $('bb-summary').innerHTML = '';
    $('bb-detail').innerHTML = '';
    renderBBSummary('Loaded ' + n + ' drafts from MFF cloud (' + src + ') — ');
  }
  window._bbLoadCloudPayload = applyCloudPortfolio; // test hook

  function onBBUserChange() {
    saveLS('simlab_bb_user', $('bb-user').value.trim());
    if (!state.bb) return;
    rebuildBBTeams();
    state.bb.results = null;
    $('bb-table').innerHTML = '';
    $('bb-summary').innerHTML = '';
    $('bb-detail').innerHTML = '';
    renderBBSummary('');
  }

  function parseBBCsv(text) {
    var lines = text.split(/\r?\n/);
    if (lines.length < 2) throw new Error('empty CSV');
    var headers = splitCsvLine(lines[0]);
    var ix = {};
    headers.forEach(function (h, i) { ix[h.trim()] = i; });
    ['Pick Number', 'Draft'].forEach(function (c) {
      if (ix[c] === undefined) throw new Error('missing column "' + c + '" — is this an Underdog export?');
    });
    var nameFL = ix['First Name'] != null && ix['Last Name'] != null;
    var nameCol = nameFL ? null : (ix['Player'] != null ? ix['Player'] : ix['Player Name']);
    if (!nameFL && nameCol == null) throw new Error('no player-name column — is this an Underdog export?');
    var userCol = null;
    BB_USER_COLS.forEach(function (c) { if (userCol == null && ix[c] != null) userCol = ix[c]; });
    var drafts = {};
    for (var i = 1; i < lines.length; i++) {
      if (!lines[i].trim()) continue;
      var c = splitCsvLine(lines[i]);
      var id = (c[ix['Draft']] || '').trim();
      var name = nameFL
        ? ((c[ix['First Name']] || '').trim() + ' ' + (c[ix['Last Name']] || '').trim()).trim()
        : (c[nameCol] || '').trim();
      if (!id || !name) continue;
      var d = drafts[id];
      if (!d) {
        d = drafts[id] = {
          id: id,
          title: (ix['Tournament Title'] != null && (c[ix['Tournament Title']] || '').trim()) || 'Draft',
          fee: ix['Tournament Entry Fee'] != null ? (parseFloat(c[ix['Tournament Entry Fee']] || '0') || 0) : 0,
          size: ix['Draft Size'] != null ? (parseInt(c[ix['Draft Size']] || '0', 10) || 0) : 0,
          date: ix['Picked At'] != null ? (c[ix['Picked At']] || '').slice(0, 10) : '',
          picks: []
        };
      }
      d.picks.push({
        name: name,
        pos: ix['Position'] != null ? (c[ix['Position']] || '').trim() : '',
        tm: ix['Team'] != null ? (c[ix['Team']] || '').trim() : '',
        pick: parseInt(c[ix['Pick Number']] || '0', 10) || 0,
        user: userCol != null ? (c[userCol] || '').trim() : ''
      });
    }
    var out = Object.keys(drafts).map(function (k) {
      var d = drafts[k];
      d.picks.sort(function (a, b) { return a.pick - b.pick; });
      // Draft Size column missing on some exports — infer from an 18-round board
      if (!d.size) d.size = (d.picks.length > 30 && d.picks.length % 18 === 0) ? d.picks.length / 18 : 12;
      d.full = d.picks.length > d.size * 1.5; // more rows than one roster = full board
      if (d.full) {
        d.picks.forEach(function (p) { p.slot = snakeSlot(p.pick, d.size); });
        d.userSlot = null; // resolved later by username or exposure merge
      } else {
        d.userSlot = (d.picks[0] && d.picks[0].pick <= d.size) ? d.picks[0].pick : null;
      }
      return d;
    });
    if (!out.length) throw new Error('no teams found in that CSV');
    return out;
  }

  function snakeSlot(pick, size) {
    var r = Math.floor((pick - 1) / size), p = (pick - 1) % size;
    return r % 2 === 0 ? p + 1 : size - p;
  }

  function splitCsvLine(line) {
    var out = [], cur = '', inQ = false;
    for (var i = 0; i < line.length; i++) {
      var ch = line[i];
      if (ch === '"') { inQ = !inQ; continue; }
      if (ch === ',' && !inQ) { out.push(cur); cur = ''; continue; }
      cur += ch;
    }
    out.push(cur);
    return out;
  }

  // Drafts -> flat team list: one team per exposure draft, ALL slots of a
  // full board (yours flagged). Engine player refs attached; picks with no
  // Clay projection are hurt/unrostered and correctly project 0.
  function rebuildBBTeams() {
    var myName = String(loadLS('simlab_bb_user', '') || '').toLowerCase().replace(/^@/, '').trim();
    var teams = [];
    Object.keys(state.bb.drafts).map(function (k) { return state.bb.drafts[k]; })
      .sort(function (a, b) { return a.date < b.date ? -1 : a.date > b.date ? 1 : 0; })
      .forEach(function (d) {
        if (!d.full) { teams.push(mkBBTeam(d, d.picks, d.userSlot, true, null)); return; }
        var bySlot = {};
        d.picks.forEach(function (p) { (bySlot[p.slot] = bySlot[p.slot] || []).push(p); });
        var mySlot = d.userSlot;
        if (myName) {
          Object.keys(bySlot).forEach(function (s) {
            var u = (bySlot[s][0] && bySlot[s][0].user) || '';
            if (u && u.toLowerCase().replace(/^@/, '').trim() === myName) mySlot = +s;
          });
        }
        Object.keys(bySlot).map(Number).sort(function (a, b) { return a - b; }).forEach(function (s) {
          teams.push(mkBBTeam(d, bySlot[s], s, s === mySlot, (bySlot[s][0] && bySlot[s][0].user) || null));
        });
      });
    state.bb.teams = teams;
    // tournament filter options (from your teams), preserving the selection
    var sel = $('bb-tourney'), cur = sel.value || 'ALL';
    var titles = [];
    teams.forEach(function (t) {
      if (t.isMine && titles.indexOf(t.title) < 0) titles.push(t.title);
    });
    titles.sort();
    sel.innerHTML = '<option value="ALL">All tournaments</option>' +
      titles.map(function (x) { return '<option' + (x === cur ? ' selected' : '') + '>' + esc(x) + '</option>'; }).join('');
    if (sel.value !== cur) sel.value = 'ALL';
  }

  // Nickname-tolerant matching (Jack: Chig Okonkwo / Kenneth Walker / Cam
  // Ward / Kenny Gainwell ARE in the Clay guide — as Chigoziem Okonkwo, Ken
  // Walker III, Cameron Ward, Kenneth Gainwell). Tiers after the exact norm
  // match: same last name + shared first-name prefix of >=3 chars (Cam→
  // Cameron, Chig→Chigoziem, Kenny/Ken→Kenneth), exactly one candidate.
  // Position-gated whenever the CSV/cloud row carries one, so name twins at
  // other positions can't steal the match. Underdog-only nicknames
  // (Hollywood Brown) go through the engine's alias table first.
  // The old last tier — same last name + first INITIAL when unique — is gone
  // (2026-10-02): against the full 617-player Underdog field it handed real
  // players to the wrong man — J'Mari Taylor → Jonathan Taylor, Josh
  // Williams → Javonte Williams, Trevor → Travis Etienne, Kyle → Ke'Shawn
  // Williams, Tyler → Tez Johnson — giving those rosters a star's points and
  // projection. Every legitimate nickname in that field clears the prefix
  // tier; a player with no pool match is simply unprojected.
  var _bbMatchCache = {};
  function bbMatchPlayer(name, pos) {
    var ck = name + '|' + (pos || '');
    if (ck in _bbMatchCache) return _bbMatchCache[ck];
    var m = bbMatchUncached(name, pos);
    _bbMatchCache[ck] = m;
    return m;
  }
  function bbMatchUncached(name, pos) {
    var nk = E.bbAliasNorm(name);
    var exact = state.players.byNorm[nk];
    if (exact && (exact.isDST || exact.pos === 'K')) exact = null;
    if (exact && (!pos || exact.pos === pos)) return exact;
    var parts = nk.split(' ');
    if (parts.length < 2) return exact;
    var first = parts[0], last = parts.slice(1).join(' ');
    var cands = state.players.list.filter(function (c) {
      if (c.isDST || c.pos === 'K') return false;
      if (pos && c.pos !== pos) return false;
      var cp = c.norm.split(' ');
      return cp.length >= 2 && cp.slice(1).join(' ') === last;
    });
    var pref = cands.filter(function (c) {
      var cf = c.norm.split(' ')[0], n = 0;
      while (n < first.length && n < cf.length && first[n] === cf[n]) n++;
      return n >= 3;
    });
    if (pref.length === 1) return pref[0];
    return exact; // pos-mismatched exact name beats no match at all
  }

  function mkBBTeam(d, picks, slot, isMine, user) {
    var players = [], unmatched = [];
    picks.forEach(function (pk) {
      var p = bbMatchPlayer(pk.name, pk.pos || null);
      if (p) players.push(p);
      else unmatched.push(pk.name);
    });
    return {
      id: d.id + '#' + (slot || 0), draftId: d.id, title: d.title, fee: d.fee, size: d.size,
      date: d.date, slot: slot, user: user, isMine: !!isMine, full: !!d.full,
      phase: d.phase || 'pre', teamName: d.teamName || null,
      picks: picks, players: players, unmatched: unmatched
    };
  }

  // Superflex contests start an extra QB-eligible slot — cloud drafts carry
  // the phase; CSV imports fall back to the tournament title.
  function isSfTeam(t) {
    return t.phase === 'superflex' || /superflex/i.test((t.title || '') + ' ' + (t.teamName || ''));
  }

  function renderBBSummary(prefix) {
    if (!state.bb) return;
    var teams = state.bb.teams || [];
    var mine = teams.filter(function (t) { return t.isMine; });
    var ids = Object.keys(state.bb.drafts);
    var fullIds = ids.filter(function (k) { return state.bb.drafts[k].full; });
    var noMine = fullIds.filter(function (k) {
      return !teams.some(function (t) { return t.draftId === k && t.isMine; });
    }).length;
    var fees = mine.reduce(function (s, t) { return s + (t.fee || 0); }, 0);
    var unm = mine.reduce(function (s, t) { return s + t.unmatched.length; }, 0);
    var picksN = mine.reduce(function (s, t) { return s + t.picks.length; }, 0);
    $('bb-note').textContent = (prefix || '') + ids.length + ' drafts' +
      (fullIds.length ? ' (' + fullIds.length + ' full boards — real opponents)' : '') +
      ' · ' + mine.length + ' of your teams · $' + fees.toFixed(0) + ' in entries' +
      (picksN ? ' · ' + (picksN - unm) + '/' + picksN + ' of your players projected' : '') +
      (unm ? ' (' + unm + ' hurt/unrostered, score 0)' : '') +
      (noMine ? ' · ⚠ ' + noMine + ' full board' + (noMine > 1 ? 's' : '') +
        ' where your team is unknown — type your UD username or also import your exposure CSV' : '') +
      '. RUN PORTFOLIO SIM when ready.';
  }

  // Synthetic pod for EXPOSURE-ONLY teams: 11 opponents snake-drafting from
  // ADP around your slot. Deterministic per draft id, so the same team always
  // meets the same field. Opponents pick among the top-4 available by ADP
  // (weighted 50/25/15/10) with realistic roster shapes.
  var BB_FIELD_MIN = { QB: 2, RB: 5, WR: 6, TE: 2 };
  var BB_FIELD_MAX = { QB: 3, RB: 9, WR: 11, TE: 4 };
  function bbSeed(str) {
    var h = 5381;
    for (var i = 0; i < str.length; i++) h = ((h << 5) + h + str.charCodeAt(i)) | 0;
    return h >>> 0;
  }
  function draftFieldSquads(team) {
    var mine = {};
    team.players.forEach(function (p) { mine[p.norm] = 1; });
    var pool = state.players.list.filter(function (p) {
      return BB_FIELD_MAX[p.pos] && p.adp != null && !mine[p.norm];
    }).sort(function (a, b) { return a.adp - b.adp; });
    var rng = E.makeRng(bbSeed(team.id));
    var size = team.size || 12, rounds = team.picks.length || 18;
    var mySlot = team.slot || 1;
    var opp = [];
    for (var i = 0; i < size - 1; i++) opp.push({ players: [], have: { QB: 0, RB: 0, WR: 0, TE: 0 } });
    var taken = {};
    for (var r = 0; r < rounds; r++) {
      for (var s0 = 0; s0 < size; s0++) {
        var slot = (r % 2 === 0) ? s0 + 1 : size - s0;
        if (slot === mySlot) continue; // the user's pick — his players are already out of the pool
        var o = opp[slot > mySlot ? slot - 2 : slot - 1];
        var left = rounds - r;
        var need = 0;
        Object.keys(BB_FIELD_MIN).forEach(function (pp) { need += Math.max(0, BB_FIELD_MIN[pp] - o.have[pp]); });
        var mustFill = need >= left;
        var cands = [];
        for (var pi = 0; pi < pool.length && cands.length < 4; pi++) {
          var p = pool[pi];
          if (taken[p.norm]) continue;
          if (o.have[p.pos] >= BB_FIELD_MAX[p.pos]) continue;
          if (mustFill && o.have[p.pos] >= BB_FIELD_MIN[p.pos]) continue;
          cands.push(p);
        }
        if (!cands.length) continue;
        var u = rng.rand();
        var ci = u < 0.5 ? 0 : u < 0.75 ? 1 : u < 0.9 ? 2 : 3;
        var chosen = cands[Math.min(ci, cands.length - 1)];
        taken[chosen.norm] = 1;
        o.players.push(chosen);
        o.have[chosen.pos]++;
      }
    }
    return opp.map(function (o) { return o.players; });
  }

  // ---------------- prize models + tournament EV ----------------
  // Deliberately crude (Jack: "I know it won't be super accurate but fun"):
  // EV = advance-min-cash x P(advance)
  //    + finals-avg-prize x P(advance AND wk15 > cutoff AND wk16 > cutoff)
  // where the cutoffs are LAST SEASON'S median advancing scores in the
  // playoff weeks — editable per tournament (defaults are placeholders, put
  // the real BBM historical numbers in). Computed from the per-sim raw
  // arrays, so cutoff edits recompute instantly without re-simming.
  // Two prize-model shapes (BBM VI full data, computed 2026-08-25):
  //  * SAME-ROSTER playoffs: finals are a payout LADDER — tiers map a W17
  //    score cutoff to a prize (cut 0 = finals min-cash), first matching
  //    tier from the top pays. Cutoff defaults = REAL BBM VI numbers
  //    (advancing W15 median 165.0, W16 175.1; finals winner 187.9, top-10
  //    171.6, top-50 152.9 — redraft teams, but the best anchor we have).
  //  * CORRECTED 2026-10-02 (Jack: "there are no redrafts — you keep your
  //    team"): BBM playoffs are SAME-ROSTER. The Dec timestamps in the
  //    rd2-rd4 files are when Underdog creates the playoff GROUPS, not new
  //    drafts. BBM now defaults to the ladder with its own preset below, and
  //    a saved BBM model left in re-draft mode is put back on it. What
  //    follows describes the old flat-equity mode, kept only as a manual
  //    option:
  //  * FLAT-EQUITY mode (was "re-draft"): treats playoff equity conditional
  //    on advancing as flat: EV = advCash x P(adv) + perAdvEV x P(adv).
  //    STRUCTURE CHANGES YEARLY (Jack 2026-08-25: "adjust for that"):
  //      W15 gates: II 2-of-18 (verified per-pod: 1440 pods x 18, 2 advanced
  //      from every one) -> III 1/10,1/16 -> IV 1/16,1/16 -> V/VI 1/13,1/16
  //      (539 finals)
  //      BBM VII (2026, per 4for4 guide): 2/12 reg, W15 1-of-14, W16 1-of-12,
  //      667-team finals -> P(finals|adv) = 1/168 = 0.595%.
  //    Cutoff defaults = BBM V/VI score distributions read AT BBM VII
  //    selectivity (W15 92.86 pctile ~161, W16 91.67 pctile ~164), not the
  //    raw prior-year advancing medians (those embed the old structure).
  //    perAdvEV ~$120: ~90% of a ~$15M pool paid from W15 on / ~112k advancers.
  //    Auto-detected for "Best Ball Mania" titles; toggleable per tournament.
  //  * ELIMINATOR (weekly survivor): top-6 of the 12-pod in wk1, then a 50%
  //    head-to-head cut EVERY week to a 3-person wk17 final (per-entry
  //    P(final) = 2^-16 = 1/65,536). The engine chains per-week win
  //    fractions vs the pod field, so those tails resolve at ~300 sims.
  //    EV = P(win) x winner prize + P(finalist, not winner) x finalist prize.
  // LADDER MODE v2 (Jack 2026-08-25: "each format, advance pods, and actual
  // prize money for each contest is different — the Field General is
  // superflex so the score to advance needs to be higher"): ladder models no
  // longer store ABSOLUTE score cutoffs. They store the STRUCTURE — W15/W16
  // advance rates (1-in-N), finals size, and prizes by finals PLACEMENT —
  // and the score cutoffs are derived at run time from the tournament's own
  // simulated field distribution at those selectivities. A superflex field
  // scores ~15 pts/wk higher, so its cutoffs rise automatically; and because
  // your score and the cutoff come from the same engine, the Clay-optimism
  // level bias cancels instead of inflating finals odds.
  var DEF_PRIZE = {
    advCash: 0,
    adv15N: 10, adv16N: 10, finalsSize: 500,
    ftiers: [{ top: 1, prize: 25000 }, { top: 10, prize: 2500 }, { top: 50, prize: 500 }],
    minCash: 25,
    perAdvEV: 120, pFinGivenAdv: 1 / 168,
    elimWin: 100000, elimFinal: 15000
  };
  // mode auto-detect from the tournament title; saved models override
  function defaultMode(title) {
    if (/eliminator/i.test(title || '')) return 'eliminator';
    return 'ladder'; // BBM included — same rosters all the way through
  }
  // Per-tournament structural presets (2026 structures), matched by title
  // when no saved model exists — the structure differs per tournament:
  //  * The Puppy: 2/12 reg, W15 1-of-10, W16 1-of-10 -> P(finals|adv)=1/100;
  //    cutoffs = BBM V/VI distributions at 90th pctile (157.5/156.0 W15,
  //    159.2/164.0 W16); ~$5 entry / ~$1M pool -> perAdvEV ~$25 if re-draft.
  //    Couldn't verify whether Puppy playoffs re-draft — defaults to the
  //    same-roster ladder; tick the re-draft box if the app says otherwise.
  //  * The Eliminator: weekly SURVIVOR (top-6 of pod wk1, then 50% cut every
  //    week, 3-person final) — the advance/finals model doesn't apply; no
  //    preset, EV column will mislead there.
  var BBM_RE = /best ball mania|\bbbm\b/i;
  var PRIZE_PRESETS = [
    // BBM VII (Underdog rules page): top 2 of 12 advance ($25 floor for every
    // advancer), W15 1-of-14, W16 1-of-12, 667-team final paid by placement
    { re: BBM_RE, model: {
      adv15N: 14, adv16N: 12, finalsSize: 667, advCash: 25,
      ftiers: [{ top: 1, prize: 2000000 }, { top: 2, prize: 1000000 }, { top: 3, prize: 500000 }, { top: 4, prize: 400000 },
               { top: 5, prize: 300000 }, { top: 6, prize: 250000 }, { top: 7, prize: 200000 }, { top: 8, prize: 150000 },
               { top: 9, prize: 125000 }, { top: 10, prize: 100240 }, { top: 15, prize: 90000 }, { top: 20, prize: 70000 },
               { top: 30, prize: 50000 }, { top: 40, prize: 25000 }, { top: 50, prize: 15150 }, { top: 100, prize: 7500 },
               { top: 200, prize: 5500 }, { top: 300, prize: 4500 }],
      minCash: 3750
    } },
    { re: /puppy/i, model: {
      adv15N: 10, adv16N: 10, finalsSize: 333, advCash: 0,
      ftiers: [{ top: 1, prize: 50000 }, { top: 10, prize: 2500 }, { top: 50, prize: 400 }],
      minCash: 100, perAdvEV: 25, pFinGivenAdv: 0.01
    } }
  ];
  function prizeFor(title) {
    var all = loadLS('simlab_bb_prize', {});
    var saved = all[title] || {};
    // a BBM model saved in the old re-draft mode carries a structure that
    // never existed — drop it and fall back to the BBM preset
    if (BBM_RE.test(title || '') && (saved.mode === 'redraft' || saved.redraft === true)) saved = {};
    var base = Object.assign({}, DEF_PRIZE);
    for (var pi = 0; pi < PRIZE_PRESETS.length; pi++) {
      if (PRIZE_PRESETS[pi].re.test(title || '')) { Object.assign(base, PRIZE_PRESETS[pi].model); break; }
    }
    var m = Object.assign(base, saved);
    // placement tiers; legacy score-cut tiers / finalsEV models are ignored
    // (they stored absolute scores, superseded by the structural model)
    if (!Array.isArray(saved.ftiers) || !saved.ftiers.length) m.ftiers = base.ftiers;
    m.ftiers = m.ftiers.map(function (t) { return { top: Math.max(1, +t.top || 1), prize: +t.prize || 0 }; })
      .sort(function (a, b) { return a.top - b.top; });
    if (!m.mode) {
      m.mode = saved.redraft === true ? 'redraft'
        : saved.redraft === false ? 'ladder'
        : defaultMode(title);
    }
    m.redraft = m.mode === 'redraft'; // legacy field kept in sync
    return m;
  }
  function savePrize(title, m) {
    var all = loadLS('simlab_bb_prize', {});
    all[title] = m;
    saveLS('simlab_bb_prize', all);
  }
  function computeTeamEV(r, t) {
    if (!t.isMine) return null;
    var m = prizeFor(t.title);
    if (m.mode === 'eliminator') {
      if (!r.elim) return null;
      var pF2 = r.elim.pFinal, pW2 = r.elim.pWin;
      return {
        ev: pW2 * (m.elimWin || 0) + Math.max(0, pF2 - pW2) * (m.elimFinal || 0),
        pFinals: pF2, mode: 'eliminator', elim: r.elim, tiers: [], tierP: []
      };
    }
    if (r.adv == null || !r.advFlags || !r.poRaw || r.poRaw.length < 3) return null;
    // structural "even odds" baseline: what a hypothetically average team in
    // this contest's format advances/reaches finals at (eliminators excluded
    // — different format entirely)
    var baseAdv = (((t.size || 12) >= 10 ? 2 : 1)) / (t.size || 12);
    if (m.mode === 'redraft') {
      // playoff rounds are fresh drafts -> flat equity per advance
      var pfa = m.pFinGivenAdv != null ? m.pFinGivenAdv : 0.0048;
      return {
        ev: (m.advCash + (m.perAdvEV || 0)) * r.adv,
        pFinals: r.adv * pfa,
        baseAdv: baseAdv, baseFin: baseAdv * pfa,
        redraft: true, mode: 'redraft', tiers: [], tierP: []
      };
    }
    // LADDER: SMOOTH advance curves, not hard cutoffs. Validated on BBM
    // III-VI full data (2026-08-25): P(advance a top-1-of-N pod | score s) =
    // F(s)^(N-1), where F is the week's field score CDF — matched the
    // empirical advance-rate-by-score curves within 1-4 points at every
    // 10-pt bin, every year, both playoff weeks. Here F comes from THIS
    // contest's own simulated field (r.fieldPo), so superflex fields and the
    // Clay level bias self-adjust, and the structure inputs (1-in-N, finals
    // size) retarget the curve exactly the way the historical data says.
    if (!r.fieldPo) return null;
    if (!r._fq) {
      r._fq = r.fieldPo.map(function (a) {
        var c = Array.prototype.slice.call(a);
        c.sort(function (x, y) { return x - y; });
        return c;
      });
    }
    function Fcdf(i, s) { // fraction of the pooled field below s
      var a = r._fq[i], lo = 0, hi = a.length;
      while (lo < hi) { var mid = (lo + hi) >> 1; if (a[mid] < s) lo = mid + 1; else hi = mid; }
      return a.length ? lo / a.length : 0;
    }
    function fq(i, p) {
      var a = r._fq[i];
      if (!a.length) return 0;
      return a[Math.min(a.length - 1, Math.max(0, Math.round(p * (a.length - 1))))];
    }
    function phi(z) { // standard normal CDF (A&S 7.1.26 erf approx)
      var t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2);
      var e = 1 - t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429)))) * Math.exp(-z * z / 2);
      return z >= 0 ? 0.5 + 0.5 * e : 0.5 - 0.5 * e;
    }
    var m15 = Math.max(1, (m.adv15N || 10) - 1), m16 = Math.max(1, (m.adv16N || 10) - 1);
    var fs2 = Math.max(2, m.finalsSize || 500), mF = fs2 - 1;
    var ft = m.ftiers, minCash = m.minCash || 0;
    var nFin = 0, prizeSum = 0;
    var tierN = ft.map(function () { return 0; });
    for (var s = 0; s < r.sims; s++) {
      if (!r.advFlags[s]) continue;
      var reach = Math.pow(Fcdf(0, r.poRaw[0][s]), m15) * Math.pow(Fcdf(1, r.poRaw[1][s]), m16);
      if (reach < 1e-12) continue;
      var q = 1 - Fcdf(2, r.poRaw[2][s]); // fraction of finalists beating me
      var mu = mF * q, sd = Math.sqrt(Math.max(1e-9, mF * q * (1 - q)));
      var prev = 0, pay = 0;
      for (var i = 0; i < ft.length; i++) {
        var Pt = q <= 0 ? 1 : (q >= 1 ? 0 : phi((ft[i].top - 0.5 - mu) / sd)); // P(rank <= top_i)
        Pt = Math.min(1, Math.max(prev, Pt));
        pay += (Pt - prev) * ft[i].prize;
        tierN[i] += reach * (Pt - prev);
        prev = Pt;
      }
      pay += (1 - prev) * minCash;
      nFin += reach;
      prizeSum += reach * pay;
    }
    function s50(i, mm) { return fq(i, Math.pow(0.5, 1 / mm)); } // score at 50% advance odds
    return {
      ev: m.advCash * r.adv + prizeSum / r.sims, pFinals: nFin / r.sims, mode: 'ladder',
      baseAdv: baseAdv, baseFin: baseAdv / ((m.adv15N || 10) * (m.adv16N || 10)),
      c15: s50(0, m15), c16: s50(1, m16), minCash: minCash,
      curve: {
        w15: [25, 50, 90].map(function (p) { return { p: p, s: fq(0, Math.pow(p / 100, 1 / m15)) }; }),
        w16: [25, 50, 90].map(function (p) { return { p: p, s: fq(1, Math.pow(p / 100, 1 / m16)) }; })
      },
      tiers: ft.map(function (t2, i) { return { top: t2.top, prize: t2.prize, score: fq(2, 1 - Math.min(1, t2.top / fs2)) }; }),
      tierP: tierN.map(function (n) { return n / r.sims; })
    };
  }

  // ---------------- mid-season context ----------------
  // Once the regular season is underway: weeks already played are BANKED at
  // the real Sleeper actuals (pts_std + 0.5/rec = Underdog scoring incl.
  // 4-pt pass TD and -1 INT), only the remaining weeks are sampled — and
  // full-board pods keep their real opponents, so this is a live race.
  // Completed weeks are immutable -> cached in localStorage forever.
  // Current Sleeper IR/Sus designations zero a player's remaining weeks
  // (news the preseason Clay guide can't know); 'Out' sits him this week.
  async function getBankedContext() {
    try {
      var st = await (await fetch(API + '/state/nfl')).json();
      if (!st || st.season_type !== 'regular' || !(st.week > 1)) return { fromWeek: 1 };
      var fromWeek = Math.min(18, st.week), season = st.season;
      var actuals = {};
      for (var w = 1; w < fromWeek; w++) {
        var key = 'simlab_bb_actuals_' + season + '_' + w;
        var cached = loadLS(key, null);
        if (!cached) {
          var stats = await (await fetch(API + '/stats/nfl/regular/' + season + '/' + w)).json();
          cached = {};
          Object.keys(state.players.bySid).forEach(function (sid) {
            var s2 = stats[sid];
            if (s2) cached[sid] = +(((s2.pts_std || 0) + 0.5 * (s2.rec || 0)).toFixed(2));
          });
          saveLS(key, cached);
        }
        actuals[w] = cached;
      }
      var unavailable = {};
      try { unavailable = effectiveUnavailable(await getInjuryMap(), true); } catch (e2) {}
      return { fromWeek: fromWeek, actualsBySid: actuals, unavailable: unavailable };
    } catch (e) {
      return { fromWeek: 1, err: e && e.message };
    }
  }

  async function runBBSim() {
    var teams = state.bb && state.bb.teams;
    if (!teams || !teams.length) { $('bb-note').textContent = 'Import your Underdog CSV(s) first.'; return; }
    var sims = Math.max(50, Math.min(2000, +$('bb-sims').value || 300));
    var usePod = $('bb-pod').checked;
    $('bb-note').textContent = 'Checking NFL week / banked scores…';
    var ctx = await getBankedContext();
    runBlocking('bb-run', 'bb-note', 'Simulating ' + teams.length + ' teams ' + sims + 'x…', function () {
      var t0 = performance.now();
      var squads = [], sqSf = [], engTeams = [], sqIdx = {}, byDraft = {};
      teams.forEach(function (t) {
        sqIdx[t.id] = squads.length;
        squads.push(t.players);
        sqSf.push(isSfTeam(t));
        (byDraft[t.draftId] = byDraft[t.draftId] || []).push(t);
      });
      teams.forEach(function (t, i) {
        var field = null;
        var tMode = t.isMine ? prizeFor(t.title).mode : null;
        var isElim = tMode === 'eliminator';
        if (t.full) {
          field = byDraft[t.draftId].filter(function (o) { return o.id !== t.id; })
            .map(function (o) { return sqIdx[o.id]; });
        } else if (usePod || isElim) { // eliminator NEEDS a field for the survival chain
          var sf = isSfTeam(t);
          field = draftFieldSquads(t).map(function (sq) { squads.push(sq); sqSf.push(sf); return squads.length - 1; });
        }
        engTeams.push({
          key: i, squad: sqIdx[t.id], field: field, advN: (t.size || 12) >= 10 ? 2 : 1,
          elim: isElim, collectFieldPo: tMode === 'ladder' && !!(field && field.length)
        });
      });
      state.bb.results = E.simBestBall({
        sims: sims, scoring: E.PRESETS.half, regTo: BB_REG_TO,
        schedule: state.schedule, players: state.players,
        squads: squads, sqSf: sqSf, teams: engTeams,
        fromWeek: ctx.fromWeek, actualsBySid: ctx.actualsBySid, unavailable: ctx.unavailable
      });
      state.bb.meta = { sims: sims, pod: usePod, fromWeek: ctx.fromWeek, ms: performance.now() - t0 };
      var nMine = teams.filter(function (t) { return t.isMine; }).length;
      var nFull = teams.filter(function (t) { return t.full; }).length;
      $('bb-note').textContent = teams.length + ' teams (' + nMine + ' yours) simmed ' + sims + 'x in ' +
        state.bb.meta.ms.toFixed(0) + 'ms (Underdog half PPR, reg = wks 1–' + BB_REG_TO + ').' +
        (ctx.fromWeek > 1 ? ' Wks 1–' + (ctx.fromWeek - 1) + ' BANKED at real Sleeper scores; wks ' +
          ctx.fromWeek + '+ simmed (IR/Sus zeroed, Out sits this week).' : '') +
        (nFull ? ' Full-board pods use the REAL opponents.' : '') +
        (usePod && nFull < teams.length ? ' Exposure-only teams use a synthetic ADP pod.' : '') +
        ' Click a team for its roster.';
      $('bb-detail').innerHTML = '';
      renderBBTable();
    });
  }

  // ---------------- BEST BALL: OVERALL STANDINGS ----------------
  // Underdog pays the top OVERALL Round-1 scores (the regular-season prize) —
  // a race against all ~672k entries, not the 12-team pod. Input is a field
  // file (mff_bbm_leaderboard_*.json, kind 'mff_ud_leaderboard'): the
  // tournament leaderboard with each team's place, official points, payout
  // and 18-man roster, plus the user's own entries. Rosters never change
  // after the drafts close, so ONE file lasts the season: its points are
  // rolled forward at run time by adding each completed week since the pull
  // from Sleeper stats, then the remaining weeks are simmed for every team
  // at once (engine bbFieldRun) — each of your teams gets a final-rank
  // distribution against the exact field.
  //   pages:   [[page, weight]...]  weight = leaderboard pages it stands for
  //            (all 1 in a complete file; >1 only in a partial/sampled one)
  //   apps:    [[name, pos, seasonPts]...]
  //   entries: [[page, place, points, payout, username, [appIdx...]]...]
  //            (v1 files carry an index into `pages` instead of the page no.)
  //   mine:    [{draftId, title, points, podPlace, payoutText, apps:[appIdx...]}]
  function importBBFieldFile(ev) {
    var f = ev.target.files && ev.target.files[0];
    if (!f) return;
    $('bbf-note').textContent = 'Reading ' + f.name + ' (' + (f.size / 1048576).toFixed(0) + ' MB)…';
    var reader = new FileReader();
    reader.onload = function () {
      try {
        var d = JSON.parse(String(reader.result));
        if (d && d.kind === 'mff_ud_mypods') bbfImportPods(d);
        else {
          loadBBField(d);
          bbfSaveFile(f);
          bbfApplySavedPods().then(bbfRefreshNow);
        }
      } catch (e) { $('bbf-note').textContent = 'Import failed: ' + e.message; }
      ev.target.value = '';
    };
    reader.readAsText(f);
  }
  window._bbFieldLoad = function (obj) { loadBBField(obj); }; // test hook

  // ---- saved field file ----
  // The file is 60+ MB — far past localStorage — so the picked File itself
  // goes into IndexedDB (this device + browser only; never uploaded). It is
  // NOT parsed at page load (that costs seconds and ~300 MB on every visit):
  // boot reads only the small 'meta' record, and the blob is parsed the first
  // time RUN OVERALL SIM or FIND TEAMS needs it.
  var BBF_DB = 'simlab_bbfield', BBF_STORE = 'files';
  function bbfDb(mode, fn) {
    return new Promise(function (resolve, reject) {
      var rq = indexedDB.open(BBF_DB, 1);
      rq.onupgradeneeded = function () { rq.result.createObjectStore(BBF_STORE); };
      rq.onerror = function () { reject(rq.error); };
      rq.onsuccess = function () {
        var db = rq.result, tx = db.transaction(BBF_STORE, mode), out = fn(tx.objectStore(BBF_STORE));
        tx.oncomplete = function () { db.close(); resolve(out && out.result); };
        tx.onerror = tx.onabort = function () { db.close(); reject(tx.error); };
      };
    });
  }
  function bbfSavedLine(meta) {
    return meta.tournament + ' field file saved on this device (' + (meta.teams || 0).toLocaleString() + ' teams, pulled ' +
      String(meta.pulledAt || '').slice(0, 10) + ', ' + (meta.size / 1048576).toFixed(0) + ' MB)';
  }
  function bbfSaveFile(file) {
    var f = state.bbField, note = $('bbf-note').textContent;
    var meta = { name: file.name, size: file.size, savedAt: Date.now(), pulledAt: f.meta.pulledAt,
                 tournament: f.meta.tournament, teams: f.nField };
    bbfDb('readwrite', function (st) { st.put(file, 'blob'); st.put(meta, 'meta'); }).then(function () {
      state.bbfSaved = meta;
      $('bbf-forget').style.display = '';
      if ($('bbf-note').textContent === note) $('bbf-note').textContent = note + ' Saved on this device — no need to pick it again.';
      // ask the browser not to evict it under storage pressure (no prompt in Chrome)
      if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(function () {});
    }).catch(function (e) {
      if ($('bbf-note').textContent === note) $('bbf-note').textContent = note + ' (Could not save it on this device: ' + ((e && e.message) || e) + ' — it will need re-picking after a reload.)';
    });
  }
  function bbfBootSaved() {
    if (!window.indexedDB) return;
    bbfDb('readonly', function (st) { return st.get('meta'); }).then(function (meta) {
      if (!meta || state.bbField) return;
      state.bbfSaved = meta;
      $('bbf-forget').style.display = '';
      $('bbf-note').textContent = bbfSavedLine(meta) + ' — it loads itself when you open this tab.';
      if ($('pane-bb') && $('pane-bb').classList.contains('on')) bbfAutoLoad();
    }).catch(function () {});
  }
  // Parse the saved blob; false = nothing saved. One load at a time — the
  // tab-open auto-load and a RUN / FIND click share the same promise.
  function bbfEnsureLoaded() {
    if (state.bbField) return Promise.resolve(true);
    if (!state.bbfSaved) return Promise.resolve(false);
    if (!state.bbfLoadP) {
      state.bbfLoadP = (async function () {
        $('bbf-note').textContent = 'Loading the saved field file (' + (state.bbfSaved.size / 1048576).toFixed(0) + ' MB)…';
        await new Promise(function (r) { setTimeout(r, 30); }); // let the note paint
        var blob = await bbfDb('readonly', function (st) { return st.get('blob'); });
        if (!blob) { state.bbfSaved = null; return false; }
        loadBBField(JSON.parse(await blob.text()));
        $('bbf-note').textContent += ' (Loaded from the copy saved on this device.)';
        await bbfApplySavedPods();
        bbfRefreshNow();
        return true;
      })();
      state.bbfLoadP.then(function () { state.bbfLoadP = null; }, function () { state.bbfLoadP = null; });
    }
    return state.bbfLoadP;
  }
  // Opening the BEST BALL tab loads the saved file by itself, so the section
  // is ready without a pick or a click. Only then — never at page boot — as
  // the parse costs a second or two and ~300 MB.
  function bbfAutoLoad() {
    if (state.bbField || !state.bbfSaved || state.bbfLoadP) return;
    bbfEnsureLoaded().catch(function (e) {
      $('bbf-note').textContent = 'Could not load the saved field file: ' + ((e && e.message) || e) + ' — pick it again.';
    });
  }
  function bbfForget() {
    bbfDb('readwrite', function (st) { st.delete('blob'); st.delete('meta'); st.delete('pods'); }).then(function () {
      state.bbfSaved = null;
      $('bbf-forget').style.display = 'none';
      $('bbf-note').textContent = 'Saved field file removed from this device' +
        (state.bbField ? ' (still loaded until you reload the page).' : '. Pick a file to load one.');
    }).catch(function (e) { $('bbf-note').textContent = 'Could not remove it: ' + ((e && e.message) || e); });
  }

  // NFL weeks roll on Tuesday morning; anything pulled after Thursday's
  // kickoff already has part of the current week inside its points.
  var BBF_WEEK_MS = 7 * 86400000, BBF_WEEK_ANCHOR = Date.UTC(2026, 8, 8, 9); // Tue Sep 8 2026, 5am ET
  function bbfWeekIdx(t) { return Math.floor((t - BBF_WEEK_ANCHOR) / BBF_WEEK_MS); }

  function loadBBField(d) {
    if (!d || d.kind !== 'mff_ud_leaderboard' || !Array.isArray(d.entries) || !Array.isArray(d.apps) || !Array.isArray(d.pages)) {
      throw new Error('not a field file (expected an mff_bbm_leaderboard_*.json file)');
    }
    if (!d.mine || !d.mine.length) throw new Error('the file has none of your own entries in it');
    var POS = { QB: 1, RB: 1, WR: 1, TE: 1 }, unmatched = [];
    // appearance -> index into the unique roster-player list. A player with no
    // projection stays on the roster as a STUB: he never sims, but real weeks
    // (roll-forward, finished games) still score him.
    var plist = [], plIx = {}, appPl = new Int32Array(d.apps.length);
    d.apps.forEach(function (a, i) {
      var p = bbMatchPlayer(a[0], POS[a[1]] ? a[1] : null), k;
      if (p) k = 'p:' + (p.sid || p.norm);
      else {
        unmatched.push(a[0]);
        p = { name: a[0], pos: a[1] === 'FB' ? 'RB' : a[1], sid: null, stub: true };
        k = 's:' + a[0] + '|' + a[1];
      }
      if (plIx[k] === undefined) { plIx[k] = plist.length; plist.push(p); }
      appPl[i] = plIx[k];
    });
    // Underdog's season points per player as of the pull (for the team pop-up)
    var plPulled = new Float64Array(plist.length);
    d.apps.forEach(function (a, i) { if (a[2] != null && a[2] > plPulled[appPl[i]]) plPulled[appPl[i]] = a[2]; });
    var v2 = (d.v || 1) >= 2, wOf = {};
    if (v2) d.pages.forEach(function (pg) { wOf[pg[0]] = pg[1]; });
    function wFor(e0) { return v2 ? (wOf[e0] || 1) : (d.pages[e0] || [0, 1])[1]; }

    var E0 = d.entries, nF = E0.length, nM = d.mine.length, nQ = nF + nM, nPicks = 0, i, j;
    for (i = 0; i < nF; i++) nPicks += E0[i][5].length;
    for (i = 0; i < nM; i++) nPicks += d.mine[i].apps.length;
    var start = new Int32Array(nQ + 1), ix = new Int32Array(nPicks), n = 0;
    var pulled = new Float64Array(nQ), weight = new Float64Array(nQ), place = new Int32Array(nQ), users = new Array(nQ);
    // your own entries also sit somewhere on the leaderboard — find them by
    // roster + points so they aren't counted twice (and to read their place)
    var mineSig = {}, minePts = {}, minePlace = new Array(nM).fill(0);
    function sigOf(apps) { return apps.slice().sort(function (a, b) { return a - b; }).join(','); }
    d.mine.forEach(function (m, mi) { mineSig[sigOf(m.apps)] = mi; minePts[(+m.points).toFixed(2)] = 1; });
    var payPlace = [], payAmt = [], fieldW = 0, lastPaid = 0;
    // draft group ("pod") per team — v3 files only; the Round-1 advance and the
    // playoff sim need to know which 12 teams drafted together
    var pod = new Int32Array(nQ).fill(-1), nPodded = 0;
    for (i = 0; i < nF; i++) {
      var e = E0[i], apps = e[5];
      if (e[6] != null && e[6] >= 0) { pod[i] = e[6]; nPodded++; }
      start[i] = n;
      for (j = 0; j < apps.length; j++) { var pl = appPl[apps[j]]; if (pl >= 0) ix[n++] = pl; }
      pulled[i] = e[2]; place[i] = e[1]; users[i] = e[4]; weight[i] = wFor(e[0]);
      if (e[3] > 0) { payPlace.push(e[1]); payAmt.push(e[3]); if (e[1] > lastPaid) lastPaid = e[1]; }
      if (minePts[e[2].toFixed(2)]) {
        var mi2 = mineSig[sigOf(apps)];
        if (mi2 !== undefined && !minePlace[mi2]) { minePlace[mi2] = e[1]; weight[i] = 0; pod[nF + mi2] = pod[i]; }
      }
      fieldW += weight[i];
    }
    var teams = [], own = [];
    d.mine.forEach(function (m, mi) {
      var q = nF + mi;
      start[q] = n;
      for (j = 0; j < m.apps.length; j++) { var pl2 = appPl[m.apps[j]]; if (pl2 >= 0) ix[n++] = pl2; }
      pulled[q] = m.points; weight[q] = 1; place[q] = minePlace[mi];
      users[q] = (d.me && d.me.username) || 'me';
      if (pod[q] < 0 && m.pod != null && m.pod >= 0) pod[q] = m.pod;
      own.push(q);
      teams.push({ own: true, title: m.title || m.draftId, podPlace: m.podPlace, place: minePlace[mi],
                   picks: m.apps.map(function (a) { return d.apps[a]; }),
                   inactive: m.apps.filter(function (a) { return plist[appPl[a]].stub; }).length });
    });
    start[nQ] = n;
    // place -> payout exactly as the leaderboard shows it (paid places only;
    // anything past the last paid place is $0). In a partial file a rank
    // between two pulled places takes the next pulled place's payout.
    var ord = payPlace.map(function (_, k) { return k; }).sort(function (a, b) { return payPlace[a] - payPlace[b]; });
    var pp = ord.map(function (k) { return payPlace[k]; }), pa = ord.map(function (k) { return payAmt[k]; });
    var tiers = [];
    for (i = 0; i < pp.length; i++) {
      var last = tiers[tiers.length - 1];
      if (last && last.amt === pa[i]) last.to = pp[i];
      else tiers.push({ from: pp[i], to: pp[i], amt: pa[i] });
    }
    state.bbField = {
      meta: { pulledAt: d.pulledAt, tournament: (d.tournament && d.tournament.title) || 'Tournament',
              total: d.total || (d.tournament && d.tournament.entry_count) || null, complete: d.complete !== false,
              me: (d.me && d.me.username) || null },
      roster: { players: plist, start: start.subarray(0, nQ + 1), ix: ix.subarray(0, n) },
      pulled: pulled, banked: Float64Array.from(pulled), weight: weight, place: place, users: users,
      nField: nF, nQ: nQ, own: own, teams: teams,
      // board state: everything visible (own entries' leaderboard twins are
      // hidden — weight 0 — the titled copies at the end stand in for them)
      vis: Int32Array.from(Array.from(weight).map(function (w, q) { return w > 0 ? q : -1; }).filter(function (q) { return q >= 0; })),
      curPts: Float64Array.from(pulled), curRank: Int32Array.from(place),
      view: { user: '', mine: false, page: 0, key: 'cur', dir: 'asc' }, all: null, ownRes: null, projRank: null, runId: 0,
      pod: pod, hasPods: nPodded > nF * 0.9, podRank: null, podExact: null, plKeyIx: plIx,
      plPulled: plPulled, plNow: null, nowWeek: null, lockMask: null,
      po: bbfPlayoffCfg((d.tournament && d.tournament.title) || ''),
      payPlace: pp, payAmt: pa, tiers: tiers, lastPaid: lastPaid, fieldW: fieldW + nM,
      unmatched: unmatched, userIx: null, results: null
    };
    $('bbf-summary').innerHTML = '';
    $('bbf-table').innerHTML = '';
    $('bbf-detail').innerHTML = '';
    $('bbf-lookup').innerHTML = '';
    if ($('bbf-now')) $('bbf-now').textContent = '';
    var m = state.bbField.meta, pulledMs = Date.parse(m.pulledAt), warn = [];
    if (!m.complete) warn.push('PARTIAL file — the pulled teams stand in for the rest, so deep ranks and username look-ups are incomplete');
    var found = minePlace.filter(function (x) { return x > 0; }).length;
    $('bbf-note').textContent = m.tournament + ': ' + nF.toLocaleString() + ' field teams' +
      (m.complete ? ' (the whole field)' : ' standing in for ' + Math.round(m.total ? Math.min(fieldW, +m.total) : fieldW).toLocaleString() +
        (m.total ? ' of ' + (+m.total).toLocaleString() : '') + ' entries') + ' + ' + teams.length + ' of yours' +
      (found ? ' (' + found + ' located on the leaderboard)' : '') +
      ' · pulled ' + String(m.pulledAt || '').slice(0, 16).replace('T', ' ') + ' UTC' +
      (lastPaid ? ' · regular-season prizes pay through place ' + lastPaid.toLocaleString() : ' · no payouts in the file') +
      (unmatched.length ? ' · ' + unmatched.length + ' player' + (unmatched.length === 1 ? '' : 's') + ' with no projection (real points count in played weeks, 0 in simmed weeks)' : '') +
      (state.bbField.hasPods ? ' · draft groups included (playoff sim on)' : ' · no draft groups in this file — load a draft-groups file too (Draft Helper → Pull my draft groups, ~2 min) for your teams\' playoff odds') +
      (warn.length ? ' — ⚠ ' + warn.join('; ') : '') + '. Press RUN OVERALL SIM.';
    bbfPodRanks(state.bbField);
    if ($('bbf-mine')) $('bbf-mine').checked = false;
    if ($('bbf-view')) $('bbf-view').value = 'now';
    renderBBFieldTable();
  }

  // Tournament bracket + playoff prizes, keyed on the tournament title.
  // BBM VII (Underdog rules page + the lobby line "2/12 - 1/14 - 1/12 - 667
  // Seat Final"): top 2 of each 12-team draft -> 112,056 teams in 14-team
  // groups on week 15, winners -> 8,004 teams in 12-team groups on week 16,
  // winners -> a 667-team final on week 17. Same rosters throughout. Prizes
  // by finishing place: the final 1st..667th as listed; Round-3 groups 2nd
  // $1,000 / 3rd $500 / 4th-12th $70; every other Round-2 team $25. The
  // tiers add up to the $13.5M playoff pool ($15M less the $1.5M paid on the
  // regular-season leaderboard).
  function bbfPlayoffCfg(title) {
    if (!/best ball mania vii\b/i.test(title)) return null;
    var tiers = [[1, 2000000], [2, 1000000], [3, 500000], [4, 400000], [5, 300000], [6, 250000], [7, 200000], [8, 150000],
                 [9, 125000], [10, 100240], [15, 90000], [20, 70000], [30, 50000], [40, 25000], [50, 15150], [100, 7500],
                 [200, 5500], [300, 4500], [667, 3750]];
    var finalPrize = [], from = 1;
    tiers.forEach(function (t) { for (var pl = from; pl <= t[0]; pl++) finalPrize.push(t[1]); from = t[0] + 1; });
    // reps: playoff replays per simulated regular season (cheap, and the
    // only way the prize EV settles — one team takes $2M every run).
    // entryFee / pool: for the "return on entries" line ($15M over ~672k
    // $25 entries = an average team gets back ~89 cents on the dollar).
    return { adv1: 2, g2: 14, g3: 12, lastWeek: BB_REG_TO + 3, r2Prize: 25, r3Prize: [0, 1000, 500, 70], finalPrize: finalPrize,
             reps: 12, entryFee: 25, pool: 15000000 };
  }
  // DRAFT GROUPS FROM A QUICK PULL (kind 'mff_ud_mypods'): the user's own
  // drafts, all 12 rosters each. Every roster is found on the loaded field by
  // its players (order-free), which gives those ~1,800 teams their REAL draft
  // group — so the user's own Round-1 advance odds are exact. Everyone else
  // gets a random stand-in group of 12: fine as playoff opposition (the top 2
  // of random groups look just like the top 2 of real ones), but their own
  // advance numbers are estimates, flagged ~ on the board.
  function bbfApplyPods(f, pd) {
    if (!pd || pd.kind !== 'mff_ud_mypods' || !Array.isArray(pd.mine) || !Array.isArray(pd.apps)) throw new Error('not a draft-groups file');
    var POS = { QB: 1, RB: 1, WR: 1, TE: 1 }, r = f.roster, vis = f.vis;
    var toPl = pd.apps.map(function (a) {
      var p = bbMatchPlayer(a[0], POS[a[1]] ? a[1] : null);
      var k = p ? 'p:' + (p.sid || p.norm) : 's:' + a[0] + '|' + a[1];
      return f.plKeyIx[k] !== undefined ? f.plKeyIx[k] : -1;
    });
    function hashOf(arr, from, to) { var h = 0; for (var i = from; i < to; i++) { var x = arr[i] + 1; h += x * x * 31 + x * 7919; } return h; }
    var byHash = new Map(), i, q;
    for (i = 0; i < vis.length; i++) {
      q = vis[i];
      var h = hashOf(r.ix, r.start[q], r.start[q + 1]), l = byHash.get(h);
      if (l) l.push(q); else byHash.set(h, [q]);
    }
    function sortedKey(arr, from, to) { return Array.prototype.slice.call(arr, from, to).sort(function (a, b) { return a - b; }).join(','); }
    var pod = new Int32Array(f.nQ).fill(-1), exact = new Uint8Array(f.nQ), matched = 0, wanted = 0, withMine = 0;
    pd.mine.forEach(function (m, pi) {
      var hasOwn = false;
      (m.podRosters || []).forEach(function (ro) {
        wanted++;
        var pl = ro.map(function (a) { return toPl[a]; });
        if (pl.indexOf(-1) >= 0) return;
        var cands = byHash.get(hashOf(pl, 0, pl.length)) || [], key = sortedKey(pl, 0, pl.length);
        for (var c = 0; c < cands.length; c++) {
          var cq = cands[c];
          if (pod[cq] >= 0 || sortedKey(r.ix, r.start[cq], r.start[cq + 1]) !== key) continue;
          pod[cq] = pi; exact[cq] = 1; matched++;
          if (cq >= f.nField) hasOwn = true;
          break;
        }
      });
      if (hasOwn) withMine++;
    });
    if (matched < wanted * 0.5) throw new Error('only ' + matched + ' of ' + wanted + ' teams in that file were found on the loaded field — is it the same tournament?');
    // random stand-in groups of 12 for everyone else (fixed seed: same groups every load)
    var rest = [], rng = E.makeRng(20261002);
    for (i = 0; i < vis.length; i++) if (pod[vis[i]] < 0) rest.push(vis[i]);
    for (i = rest.length - 1; i > 0; i--) { var j = (rng.rand() * (i + 1)) | 0, t = rest[i]; rest[i] = rest[j]; rest[j] = t; }
    var nExact = pd.mine.length;
    for (i = 0; i < rest.length; i++) pod[rest[i]] = nExact + ((i / 12) | 0);
    f.pod = pod; f.podExact = exact; f.hasPods = true;
    f.podInfo = { groups: nExact, matched: matched, wanted: wanted, withMine: withMine, pulledAt: pd.pulledAt };
    f.runId++;
    bbfPodRanks(f);
    return f.podInfo;
  }
  function bbfPodsLine(info) {
    return 'Your ' + info.groups + ' real draft groups are applied (' + info.matched.toLocaleString() + ' of ' + info.wanted.toLocaleString() +
      ' teams found on the field) — your teams\' advance and playoff odds use their actual opponents; every other team sits in a random stand-in group (~ on the board).';
  }
  function bbfImportPods(pd) {
    bbfEnsureLoaded().then(function (ok) {
      if (!ok) { $('bbf-note').textContent = 'Load the field file (mff_bbm_leaderboard_*.json) first, then this draft-groups file.'; return; }
      var info = bbfApplyPods(state.bbField, pd);
      $('bbf-note').textContent = bbfPodsLine(info) + ' Press RUN OVERALL SIM.';
      renderBBFieldTable();
      state.bbField.nowAt = 0;
      bbfRefreshNow();
      bbfDb('readwrite', function (st) { st.put(pd, 'pods'); }).then(function () {
        $('bbf-note').textContent += ' Saved on this device.';
      }).catch(function () {});
    }).catch(function (e) { $('bbf-note').textContent = 'Could not apply the draft groups: ' + ((e && e.message) || e); });
  }
  // a field file without its own draft groups picks up the saved quick pull
  function bbfApplySavedPods() {
    var f = state.bbField;
    if (!f || f.hasPods || !window.indexedDB) return Promise.resolve();
    return bbfDb('readonly', function (st) { return st.get('pods'); }).then(function (pd) {
      if (!pd || state.bbField !== f || f.hasPods) return;
      var info = bbfApplyPods(f, pd);
      $('bbf-note').textContent += ' ' + bbfPodsLine(info);
      renderBBFieldTable();
    }).catch(function () {});
  }

  // Each team's place in its own draft group on current points (1 = leading).
  function bbfPodRanks(f) {
    if (!f.hasPods) { f.podRank = null; return; }
    var vis = f.vis, pts = f.curPts, pod = f.pod, by = {}, pr = new Int8Array(f.nQ);
    for (var i = 0; i < vis.length; i++) { var q = vis[i]; if (pod[q] >= 0) (by[pod[q]] = by[pod[q]] || []).push(q); }
    Object.keys(by).forEach(function (k) {
      var m = by[k];
      m.sort(function (a, b) { return pts[b] - pts[a]; });
      for (var j = 0; j < m.length; j++) pr[m[j]] = (j > 0 && pts[m[j]] === pts[m[j - 1]]) ? pr[m[j - 1]] : j + 1;
    });
    f.podRank = pr;
  }
  // A file pulled part-way through a week already holds the games that were
  // final by then. Returns those players' points for that week so the run can
  // take them back out and add the week whole (or lock it) like any other.
  // "Final by then" = kicked off more than 4.5 hours before the pull.
  async function bbfPrePull(f, season, wk, pulledMs) {
    var fin = {}, nFinal = 0, live = 0;
    try {
      var sb = await (await fetch('https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?seasontype=2&week=' + wk + '&dates=' + season)).json();
      (sb.events || []).forEach(function (ev) {
        var comp = ev.competitions && ev.competitions[0], ko = Date.parse(ev.date);
        if (!comp || !ko) return;
        if (ko < pulledMs + 3 * 3600000 && ko > pulledMs - 4.5 * 3600000) live++;
        if (ko >= pulledMs - 4.5 * 3600000) return;
        nFinal++;
        (comp.competitors || []).forEach(function (c) {
          var ab = E.normTeam(String((c.team && c.team.abbreviation) || '').toUpperCase());
          if (ab) fin[ab] = 1;
        });
      });
    } catch (e) { return { err: (e && e.message) || String(e), nFinal: 0 }; }
    if (!nFinal) return { nFinal: 0, live: live };
    var all = await bbfWeekVals(f, season, wk, wk), vals = new Float64Array(all.length);
    for (var i = 0; i < all.length; i++) if (f.pTeams[i] && fin[f.pTeams[i]]) vals[i] = all[i];
    return { nFinal: nFinal, live: live, vals: vals };
  }

  function bbFieldPayout(f, rank) {
    var r = Math.round(rank), pl = f.payPlace, lo = 0, hi = pl.length;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (pl[mid] < r) lo = mid + 1; else hi = mid; }
    return lo < pl.length ? f.payAmt[lo] : 0;
  }
  function bbfSquadPicks(f, q) {
    var out = [], r = f.roster;
    for (var i = r.start[q]; i < r.start[q + 1]; i++) out.push([r.players[r.ix[i]].name, r.players[r.ix[i]].pos, null]);
    return out;
  }

  // A Sleeper id (and current team) for EVERY roster player — pool players
  // carry one, stubs and id-less pool players are looked up by name in
  // Sleeper's full player list. Kept in localStorage for a day.
  async function bbfResolveSids(f) {
    if (f.sids) return;
    var P = f.roster.players;
    var sids = P.map(function (p) { return p.sid != null ? String(p.sid) : null; });
    var teams = P.map(function (p) { return p.stub ? null : (E.normTeam(p.tmNow || p.tm || '') || null); });
    var need = [];
    P.forEach(function (p, i) { if (!sids[i]) need.push(i); });
    if (need.length) {
      var cache = loadLS('simlab_bbf_sidmap', null), by = (cache && Date.now() - cache.at < 86400000) ? cache.by : null;
      var keyOf = function (p) { return p.name + '|' + p.pos; };
      if (!by || need.some(function (i) { return by[keyOf(P[i])] === undefined; })) {
        var index = E.bbSleeperIndex(await (await fetch(API + '/players/nfl')).json());
        by = {};
        need.forEach(function (i) {
          var hit = E.bbResolveSid(index, P[i].name, P[i].pos);
          by[keyOf(P[i])] = hit ? [hit.sid, hit.team] : 0;
        });
        saveLS('simlab_bbf_sidmap', { at: Date.now(), by: by });
      }
      need.forEach(function (i) {
        var hit = by[keyOf(P[i])];
        if (!hit) return;
        sids[i] = hit[0];
        if (!teams[i] && hit[1]) teams[i] = E.normTeam(hit[1]);
      });
    }
    f.sids = sids; f.pTeams = teams;
  }
  // One week's REAL points for every roster player (Underdog half PPR out of
  // Sleeper stats — reproduces Underdog's own team totals for 99.9% of the
  // field). A finished week is cached: for good once it is two weeks old, for
  // a day while stat corrections can still land.
  async function bbfWeekVals(f, season, wk, cur) {
    var key = 'simlab_bbf_wk_' + season + '_' + wk, done = wk < cur;
    var c = done ? loadLS(key, null) : null;
    var fresh = c && (wk < cur - 1 || Date.now() - c.at < 86400000) &&
      !f.sids.some(function (sid) { return sid != null && c.by[sid] === undefined; });
    if (!fresh) {
      var stats = await (await fetch(API + '/stats/nfl/regular/' + season + '/' + wk)).json();
      c = { at: Date.now(), by: {} };
      f.sids.forEach(function (sid) {
        if (sid == null) return;
        var s = stats[sid];
        c.by[sid] = s ? +(((s.pts_std || 0) + 0.5 * (s.rec || 0)).toFixed(2)) : 0;
      });
      if (done) saveLS(key, c);
    }
    return Float64Array.from(f.sids, function (sid) { return sid != null ? (c.by[sid] || 0) : 0; });
  }
  // The week in progress: which games are FINAL (ESPN scoreboard)? Players on
  // those teams are locked at their real points for the week; everyone else
  // is still simmed. Games in progress count as not played yet.
  async function bbfLockWeek(f, season, wk) {
    var fin = {}, nGames = 0, nFinal = 0;
    try {
      var sb = await (await fetch('https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?seasontype=2&week=' + wk + '&dates=' + season)).json();
      (sb.events || []).forEach(function (ev) {
        var comp = ev.competitions && ev.competitions[0];
        if (!comp) return;
        nGames++;
        var stt = comp.status || ev.status || {};
        if (!(stt.type && stt.type.completed)) return;
        nFinal++;
        (comp.competitors || []).forEach(function (c) {
          var ab = E.normTeam(String((c.team && c.team.abbreviation) || '').toUpperCase());
          if (ab) fin[ab] = 1;
        });
      });
    } catch (e) { return { err: (e && e.message) || String(e), nFinal: 0 }; }
    if (!nFinal) return { nGames: nGames, nFinal: 0 };
    var mask = new Uint8Array(f.sids.length);
    f.roster.players.forEach(function (p, i) { if (p.stub || (f.pTeams[i] && fin[f.pTeams[i]])) mask[i] = 1; });
    return { nGames: nGames, nFinal: nFinal, mask: mask, vals: await bbfWeekVals(f, season, wk, wk) };
  }

  // ---- the sim across CPU cores ----
  // One sim of the whole field takes 1.5-3 s on one core. The sims are
  // independent, so they are dealt out to Web Workers (bbf_worker.js): each
  // loads the same data scripts + engine as this page, rebuilds the player
  // pool, runs its share with its own seed and hands back its running sums,
  // which add straight together. Costs ~120 MB of memory per worker.
  function bbfCores(sims) {
    if (!window.Worker) return 1;
    var want = +($('bbf-cores') && $('bbf-cores').value) || 0;
    // measured on a 20-thread machine: 1 core 2.0 s/sim, 8 -> 0.42, 16 -> 0.31
    // (memory bandwidth flattens it), so auto stops at 12
    var auto = Math.max(1, Math.min(12, (navigator.hardwareConcurrency || 4) - 2));
    return Math.max(1, Math.min(want > 0 ? want : auto, 16, sims));
  }
  function bbfDist(arr) {
    var d = Float64Array.from(arr).sort(), sum = 0, n = d.length;
    for (var i = 0; i < n; i++) sum += d[i];
    function pc(q) { return d[Math.min(n - 1, Math.max(0, Math.round(q * (n - 1))))]; }
    return { mean: sum / n, p10: pc(0.10), p25: pc(0.25), p50: pc(0.50), p75: pc(0.75), p90: pc(0.90), min: d[0], max: d[n - 1] };
  }
  function bbfRunParallel(f, o, cores, onProgress) {
    return new Promise(function (resolve, reject) {
      var scripts = Array.prototype.slice.call(document.scripts).map(function (sc) { return sc.src; })
        .filter(function (src) { return src && /\/(data\/[^/]+|overrides|engine)\.js(\?|$)/.test(src); });
      var ver = (scripts[scripts.length - 1] || '').split('?')[1] || '';
      var rp = f.roster.players.map(function (p) {
        return p.stub ? { stub: 1, name: p.name, pos: p.pos } : { sid: p.sid != null ? p.sid : null, norm: p.norm, name: p.name, pos: p.pos };
      });
      var ix16 = Uint16Array.from(f.roster.ix); // player indexes fit 16 bits: half the copy per worker
      var per = Math.floor(o.sims / cores), extra = o.sims - per * cores, seed0 = (Date.now() ^ (Math.random() * 1e9)) >>> 0;
      var workers = [], parts = new Array(cores), done = new Array(cores).fill(0), left = cores, failed = false;
      function fail(err) {
        if (failed) return;
        failed = true;
        workers.forEach(function (w) { try { w.terminate(); } catch (e) {} });
        reject(err);
      }
      for (var c = 0; c < cores; c++) (function (c) {
        var w = new Worker('bbf_worker.js' + (ver ? '?' + ver : ''));
        workers.push(w);
        w.onerror = function (ev) { fail(new Error(ev.message || 'worker error')); };
        w.onmessage = function (ev) {
          var m = ev.data;
          if (m.type === 'progress') {
            done[c] = m.done;
            onProgress(done.reduce(function (a, b) { return a + b; }, 0), cores);
          } else if (m.type === 'error') fail(new Error(m.message));
          else if (m.type === 'done') {
            parts[c] = m; w.terminate();
            if (--left === 0 && !failed) resolve(bbfMergeParts(parts));
          }
        };
        w.postMessage({
          cmd: 'run', scripts: scripts, players: rp, start: f.roster.start, ix: ix16,
          injury: state.injuryWeek ? { week: state.injuryWeek, active: !!state.injuryActive } : null,
          sims: per + (c < extra ? 1 : 0), seed: (seed0 + c * 7919) >>> 0,
          regTo: o.regTo, banked: o.banked, weight: o.weight, mine: o.mine, fromWeek: o.fromWeek, unavailable: o.unavailable,
          cutRanks: o.cutRanks, lockMask: o.lockMask, lockVals: o.lockVals, all: o.all, playoff: o.playoff
        });
      })(c);
    });
  }
  // Add the workers' results together into one engine-shaped result.
  function bbfMergeParts(parts) {
    var p0 = parts[0], sims = 0, A = {}, MIN = { best: 1, finBest: 1 };
    parts.forEach(function (p) { sims += p.sims; });
    Object.keys(p0.A).forEach(function (k) {
      var out = p0.A[k];
      if (k !== 'nowTot') {
        for (var j = 1; j < parts.length; j++) {
          var src = parts[j].A[k], n = out.length, i;
          if (MIN[k]) { for (i = 0; i < n; i++) if (src[i] < out[i]) out[i] = src[i]; }
          else for (i = 0; i < n; i++) out[i] += src[i];
        }
      }
      A[k] = out;
    });
    function cat(get) {
      var out = new Float64Array(sims), at = 0;
      parts.forEach(function (p) { var a = get(p); out.set(a, at); at += a.length; });
      return out;
    }
    var T = p0.squads.length, teams = [];
    for (var t = 0; t < T; t++) (function (t) {
      var totals = cat(function (p) { return p.totals.subarray(t * p.sims, (t + 1) * p.sims); });
      var ranks = cat(function (p) { return p.ranks.subarray(t * p.sims, (t + 1) * p.sims); });
      teams.push({ squad: p0.squads[t], banked: p0.banked[t], curRank: p0.curRank[t], totals: totals, ranks: ranks,
                   total: bbfDist(totals), rank: bbfDist(ranks) });
    })(t);
    var cuts = p0.cuts.map(function (c, ci) {
      return { rank: c.rank, cur: c.cur, final: bbfDist(cat(function (p) { return p.cuts[ci].raw; })) };
    });
    var po = null;
    if (p0.playoff) {
      po = { nPods: p0.playoff.nPods, advancers: 0, round3: 0, finalists: 0 };
      parts.forEach(function (p) { ['advancers', 'round3', 'finalists'].forEach(function (k) { po[k] += p.playoff[k] * p.sims / sims; }); });
    }
    return { sims: sims, fromWeek: p0.fromWeek, regTo: p0.regTo, weeksSimmed: p0.weeksSimmed, nSquads: p0.nSquads,
             fieldWeight: p0.fieldWeight, nPlayers: p0.nPlayers, teams: teams, cuts: cuts, all: A, simsDone: sims, playoff: po };
  }

  // ---- standings from games already played ----
  // Bring the file's points up to this minute, no sim involved:
  //   pulled points
  //   - any games of the pull week that were already inside them (bbfPrePull)
  //   + every week finished since, whole (Sleeper stats)
  // and work out which of the current week's games are final (bbfLockWeek).
  // Keyed to week NUMBERS, so a late or early Sleeper week rollover can never
  // add a week twice. f.banked = points through the last finished week.
  async function bbfBankNow(f) {
    var st = await (await fetch(API + '/state/nfl')).json();
    var inSeason = !!st && st.season_type === 'regular';
    var cur = inSeason ? Math.min(18, st.week || 1) : 1;
    await bbfResolveSids(f);
    var pulledMs = Date.parse(f.meta.pulledAt);
    var pullWeek = pulledMs ? Math.max(1, bbfWeekIdx(pulledMs) + 1) : cur, added = [];
    var banked = Float64Array.from(f.pulled), plNow = Float64Array.from(f.plPulled), pi;
    var pre = (pulledMs && inSeason && pullWeek <= BB_REG_TO) ? await bbfPrePull(f, st.season, pullWeek, pulledMs) : null;
    if (pre && pre.nFinal) {
      E.bbFieldAddWeek(f.roster, pre.vals, banked, -1);
      for (pi = 0; pi < plNow.length; pi++) plNow[pi] -= pre.vals[pi];
    }
    for (var wk = pullWeek; wk < cur && wk <= BB_REG_TO; wk++) {
      var wv = await bbfWeekVals(f, st.season, wk, cur);
      E.bbFieldAddWeek(f.roster, wv, banked);
      for (pi = 0; pi < plNow.length; pi++) plNow[pi] += wv[pi];
      added.push(wk);
    }
    // the week in progress: finished games count for real
    var lock = (inSeason && cur >= pullWeek && cur <= BB_REG_TO) ? await bbfLockWeek(f, st.season, cur) : null;
    if (lock && lock.nFinal) for (pi = 0; pi < plNow.length; pi++) if (lock.mask[pi]) plNow[pi] += lock.vals[pi];
    f.banked = banked; // swapped in whole, so a failed refresh never leaves half-added weeks
    f.plNow = plNow; f.nowWeek = cur; f.lockMask = (lock && lock.nFinal) ? lock.mask : null;
    return { st: st, cur: cur, added: added, lock: lock, pre: pre, pullWeek: pullWeek };
  }
  // Points + overall rank + place in the draft group for every team, from
  // f.banked plus this week's finished games. Ties share the better place
  // (Underdog's "T-1253"); totals are rounded to the cent first so float
  // dust from adding weeks can't split a tie.
  function bbfSetStandings(f, B, pts) {
    if (!pts) {
      pts = Float64Array.from(f.banked);
      if (B.lock && B.lock.nFinal) {
        var vals = new Float64Array(B.lock.vals.length);
        for (var i = 0; i < vals.length; i++) if (B.lock.mask[i]) vals[i] = B.lock.vals[i];
        E.bbFieldAddWeek(f.roster, vals, pts);
      }
    }
    for (var k = 0; k < pts.length; k++) pts[k] = Math.round(pts[k] * 100) / 100;
    var by = Int32Array.from(f.vis), rk = new Int32Array(f.nQ);
    by.sort(function (a, b) { return pts[b] - pts[a]; });
    for (var o = 0; o < by.length; o++) rk[by[o]] = (o > 0 && pts[by[o]] === pts[by[o - 1]]) ? rk[by[o - 1]] : o + 1;
    f.curPts = pts; f.curRank = rk; f.runId++;
    f.added = B.added; f.lockInfo = B.lock; f.pre = B.pre;
    f.nowAt = Date.now();
    bbfPodRanks(f);
    if ($('bbf-now')) $('bbf-now').textContent = bbfNowLine(f, B);
  }
  function bbfNowLine(f, B) {
    var a = B.added, lk = B.lock, parts = ['Underdog\'s points at the pull (' + String(f.meta.pulledAt || '').slice(0, 10) + ')'];
    if (a.length) parts.push('week' + (a.length > 1 ? 's ' + a[0] + '–' + a[a.length - 1] : ' ' + a[0]) + ' from game stats');
    if (lk && lk.nGames) parts.push('week ' + B.cur + ': ' + (lk.nFinal || 0) + ' of ' + lk.nGames + ' games final');
    return 'Standings as of ' + new Date(f.nowAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) + ' = ' + parts.join(' + ') +
      (lk && lk.err ? ' (could not read this week\'s game status: ' + lk.err + ')' : '') +
      (B.pre && B.pre.live ? ' — ⚠ games were live around the pull, some points may be off' : '') +
      '. Games count once they are final; this refreshes whenever you open the tab, or press UPDATE STANDINGS.';
  }
  // Runs on its own after a file loads, when the tab is opened, every 10
  // minutes while it stays open, and from the UPDATE STANDINGS button.
  async function bbfRefreshNow() {
    var f = state.bbField;
    if (!f || f.running || f.refreshing) return;
    f.refreshing = true;
    try {
      if ($('bbf-now') && !f.nowAt) $('bbf-now').textContent = 'Updating the standings from finished games…';
      var B = await bbfBankNow(f);
      if (state.bbField !== f || f.running) return;
      bbfSetStandings(f, B);
      renderBBFieldTable();
    } catch (e) {
      if ($('bbf-now')) $('bbf-now').textContent = 'Could not update the standings from game stats (' + ((e && e.message) || e) + ') — showing the last points in hand.';
    } finally { f.refreshing = false; }
  }
  function bbfMaybeRefresh() {
    var f = state.bbField;
    if (f && (!f.nowAt || Date.now() - f.nowAt > 10 * 60000)) bbfRefreshNow();
  }

  async function runBBFieldSim() {
    try {
      if (!(await bbfEnsureLoaded())) { $('bbf-note').textContent = 'Load a field file (mff_bbm_leaderboard_*.json) first.'; return; }
    } catch (e0) { $('bbf-note').textContent = 'Could not load the saved field file: ' + ((e0 && e0.message) || e0); return; }
    var f = state.bbField;
    if (f.running) return;
    var sims = Math.max(20, Math.min(10000, +$('bbf-sims').value || 100));
    $('bbf-note').textContent = 'Checking NFL week / weekly stats…';
    var btn = $('bbf-run');
    btn.disabled = true; f.running = true;
    try {
      var ctx = await getBankedContext(); // injuries for the simmed weeks
      var B = await bbfBankNow(f), cur = B.cur, added = B.added, lock = B.lock, pre = B.pre, pullWeek = B.pullWeek;
      var cutRanks = [1, 10, 100, 1000];
      if (f.lastPaid && cutRanks.indexOf(f.lastPaid) < 0) cutRanks.push(f.lastPaid);
      cutRanks = cutRanks.filter(function (r) { return r <= f.fieldW; });
      var mine = f.own, t0 = performance.now();
      var runOpts = {
        sims: sims, regTo: BB_REG_TO, banked: f.banked, weight: f.weight, mine: mine,
        fromWeek: Math.min(cur, BB_REG_TO + 1), unavailable: ctx.unavailable || {}, cutRanks: cutRanks,
        lockMask: (lock && lock.mask) || null, lockVals: (lock && lock.vals) || null,
        all: { payPlace: f.payPlace, payAmt: f.payAmt },
        playoff: (f.hasPods && f.po) ? { pod: f.pod, adv1: f.po.adv1, g2: f.po.g2, g3: f.po.g3, lastWeek: f.po.lastWeek,
                                         r2Prize: f.po.r2Prize, r3Prize: f.po.r3Prize, finalPrize: f.po.finalPrize, reps: f.po.reps } : null
      };
      var nTeams = (f.roster.start.length - 1).toLocaleString();
      function progress(nDone, cores) {
        $('bbf-note').textContent = 'Simulating ' + nTeams + ' teams' + (cores > 1 ? ' on ' + cores + ' cores' : '') + ' — sim ' + nDone + ' of ' + sims +
          (nDone > 1 ? ' · about ' + Math.max(1, Math.round((performance.now() - t0) / nDone * (sims - nDone) / 1000)) + 's left' : '') + '…';
      }
      var cores = bbfCores(sims), res = null, coresUsed = 1;
      if (cores > 1) {
        try { res = await bbfRunParallel(f, runOpts, cores, progress); coresUsed = cores; }
        catch (eW) { console.warn('[overall sim] workers failed, running on one core:', eW); res = null; }
      }
      if (!res) {
        var run = E.bbFieldRun(Object.assign({ scoring: E.PRESETS.half, schedule: state.schedule, players: state.players, roster: f.roster }, runOpts));
        var nDone = 0;
        await new Promise(function (resolve, reject) {
          (function tick() {
            try {
              var t = performance.now();
              do { nDone = run.step(1); } while (!run.done() && performance.now() - t < 350);
              progress(nDone, 1);
              if (run.done()) resolve(); else setTimeout(tick, 0);
            } catch (e) { reject(e); }
          })();
        });
        res = run.result();
      }
      f.coresUsed = coresUsed;
      res.teams.forEach(function (r, i) {
        var top100 = 0, top1k = 0, cash = 0, ev = 0;
        for (var s = 0; s < sims; s++) {
          var rk = r.ranks[s], p = bbFieldPayout(f, rk);
          if (rk <= 100) top100++;
          if (rk <= 1000) top1k++;
          if (p > 0) { cash++; ev += p; }
        }
        r.i = i;
        r.t = f.teams[i];
        r.top100 = top100 / sims; r.top1k = top1k / sims; r.cash = cash / sims; r.ev = ev / sims;
        r.payNow = bbFieldPayout(f, r.curRank);
      });
      // whole-field results for the board: today's points + exact standings
      // rank (ties share the better place, like Underdog's T-1253), and each
      // team's place by projected final total
      f.all = res.all; f.simsDone = sims; f.runId++;
      f.ownRes = {};
      res.teams.forEach(function (r) { f.ownRes[r.squad] = r; });
      bbfSetStandings(f, B, res.all.nowTot);
      var vis = f.vis, sumLog = res.all.sumLogRank;
      f.projRank = new Float64Array(f.nQ);
      for (var o = 0; o < vis.length; o++) f.projRank[vis[o]] = Math.exp(sumLog[vis[o]] / sims); // typical simmed finish
      // projected season leaderboard: every team's place by projected final points
      var sumTot = res.all.sumTot, byProj = Int32Array.from(vis);
      byProj.sort(function (x, y) { return sumTot[y] - sumTot[x]; });
      f.projPtsRank = new Int32Array(f.nQ);
      for (var o2 = 0; o2 < byProj.length; o2++) f.projPtsRank[byProj[o2]] = o2 + 1;
      if (f.view.mode === 'proj') { f.view.key = 'ppr'; f.view.dir = 'asc'; f.view.page = 0; }
      f.results = res;
      $('bbf-note').textContent = f.meta.tournament + ': ' + f.own.length + ' of your teams' +
        ' ranked against ' + f.nField.toLocaleString() +
        ' field teams, ' + sims + ' sims in ' + ((performance.now() - t0) / 1000).toFixed(1) + 's' +
        (f.coresUsed > 1 ? ' on ' + f.coresUsed + ' cores' : '') + '. ' +
        (added.length ? 'Week' + (added.length > 1 ? 's ' + added[0] + '–' + added[added.length - 1] : ' ' + added[0]) +
          ' added to the file\'s points from Sleeper stats. ' : 'Points as pulled from Underdog. ') +
        (lock && lock.nFinal ? 'Week ' + cur + ': ' + lock.nFinal + ' of ' + lock.nGames + ' games final — real points in for those players, the other games simmed. '
          : (lock && lock.err ? 'Could not read this week\'s game status (' + lock.err + ') — week ' + cur + ' simmed as unplayed. ' : '')) +
        (pre && pre.nFinal ? 'The file was pulled with ' + pre.nFinal + ' week-' + pullWeek + ' game' + (pre.nFinal === 1 ? '' : 's') + ' already played — handled' +
          (pre.live ? ', but ' + pre.live + ' game' + (pre.live === 1 ? ' was' : 's were') + ' LIVE around the pull, so some points may be off' : '') + '. ' : '') +
        (res.weeksSimmed ? 'Weeks ' + res.fromWeek + '–' + res.regTo + ' simmed' + (res.playoff ? ', then the playoffs (weeks ' + (res.regTo + 1) + '–' + f.po.lastWeek + ') played out' : '') + '.'
          : 'Regular season is over — these are the final standings.') +
        ' The table is the whole leaderboard — tick My teams for yours.';
      $('bbf-detail').innerHTML = '';
      renderBBFieldTable();
    } catch (e) {
      $('bbf-note').textContent = 'Sim failed: ' + (e && e.message || e);
    } finally {
      btn.disabled = false; f.running = false;
    }
  }

  function bbfRank(v) { return Math.round(v).toLocaleString(); }

  // ---- the board: the WHOLE leaderboard, 150 a page ----
  // Every team in the tournament with its username, like Underdog's own
  // overall leaderboard, plus (after a sim) where each one projects. Filters:
  // "my teams", or one username = that player's portfolio with a summary on
  // top. Any column sorts the whole filtered set, not just the page.
  var BBF_PAGE = 150;
  // Each column renders its own cell, so a view is just an ordering of ids.
  //   now  = current standings first (Underdog's leaderboard, kept current)
  //   proj = PROJECTED standings first: teams ranked by projected final points
  var BBF_EST = ' class="dim" title="random stand-in draft group — an estimate"';
  var BBF_BOARD_COLS = [
    { id: 'cur', h: 'Rank now', k: 'cur', dir: 'asc', cell: function (f, q) { return f.curRank[q] ? bbfRank(f.curRank[q]) : '—'; } },
    { id: 'ppr', h: 'Proj pts rank', k: 'ppr', dir: 'asc', sim: 1, cell: function (f, q) { return '<b>' + bbfRank(f.projPtsRank[q]) + '</b>'; } },
    { id: 'mv', h: 'vs now', k: 'mv', sim: 1, cell: function (f, q) {
        var d = (f.curRank[q] || 0) - f.projPtsRank[q];
        return !f.curRank[q] || !d ? '<span class="dim">—</span>'
          : '<span style="color:' + (d > 0 ? 'var(--acc)' : '#f85149') + '">' + (d > 0 ? '▲ ' : '▼ ') + Math.abs(d).toLocaleString() + '</span>';
      } },
    { id: 'user', h: 'User / team', l: 1, cell: function (f, q, st, own) {
        return (own ? '<b>' + esc(own.title) + '</b> ' : '') + '<a href="#" data-u="' + esc(f.users[q]) + '" title="open this player\'s portfolio" style="text-decoration:none;color:' + (own ? 'var(--dim)' : '#58a7ff') + '">@' + esc(f.users[q]) + '</a>' +
          (own && own.inactive ? ' <span class="dim" title="no projection — hurt/unrostered, 0 in simmed weeks">' + own.inactive + ' inactive</span>' : '');
      } },
    { id: 'pts', h: 'Pts now', k: 'pts', cell: function (f, q) { return fmt(f.curPts[q], 2); } },
    { id: 'pay', h: 'Paying now', k: 'pay', cell: function (f, q) {
        var pay = bbFieldPayout(f, f.curRank[q] || 1e9);
        return pay > 0 ? '<span style="color:var(--acc)">' + bbfMoney(pay) + '</span>' : '<span class="dim">—</span>';
      } },
    { id: 'proj', h: 'Proj final pts', k: 'proj', sim: 1, cell: function (f, q, st) { return '<b>' + fmt(st.proj, 0) + '</b>'; } },
    { id: 'prank', h: 'Typical finish', k: 'prank', dir: 'asc', sim: 1, cell: function (f, q, st) { return bbfRank(st.prank); } },
    { id: 'best', h: 'Top finish', k: 'best', dir: 'asc', sim: 1, cell: function (f, q, st) { return bbfRank(st.best); } },
    { id: 't100', h: 'Top 100', k: 't100', sim: 1, cell: function (f, q, st) { return fmtOdds(st.t100); } },
    { id: 't1k', h: 'Top 1,000', k: 't1k', sim: 1, cell: function (f, q, st) { return fmtOdds(st.t1k); } },
    { id: 'cash', h: 'Cash %', k: 'cash', sim: 1, cell: function (f, q, st) { return fmtOdds(st.cash); } },
    { id: 'ev', h: 'Reg EV $', k: 'ev', sim: 1, cell: function (f, q, st) { return st.ev > 0 ? bbfMoney(st.ev) : '<span class="dim">$0</span>'; } },
    { id: 'podr', h: 'Pod now', k: 'podr', dir: 'asc', pods: 1, cell: function (f, q) {
        var prk = f.podRank[q];
        if (f.podExact && !f.podExact[q]) return '<span' + BBF_EST + '>~' + (prk || '—') + '</span>';
        return prk ? (prk <= 2 ? '<span style="color:var(--acc)">' + prk + '</span>' : String(prk)) : '—';
      } },
    { id: 'adv1', h: 'Adv %', k: 'adv1', po: 1, cell: function (f, q, st) {
        return (f.podExact && !f.podExact[q]) ? '<span' + BBF_EST + '>~' + fmtOdds(st.po.adv1) + '</span>' : '<b>' + fmtOdds(st.po.adv1) + '</b>';
      } },
    { id: 'adv2', h: 'Rd 3 %', k: 'adv2', po: 1, cell: function (f, q, st) { return fmtOdds(st.po.adv2); } },
    { id: 'adv3', h: 'Final %', k: 'adv3', po: 1, cell: function (f, q, st) { return fmtOdds(st.po.adv3); } },
    { id: 'favg', h: 'Avg final', k: 'favg', dir: 'asc', po: 1, cell: function (f, q, st) { return st.po.favg != null ? bbfRank(st.po.favg) : '<span class="dim">—</span>'; } },
    { id: 'fbest', h: 'Best final', k: 'fbest', dir: 'asc', po: 1, cell: function (f, q, st) { return st.po.fbest != null ? bbfRank(st.po.fbest) : '<span class="dim">—</span>'; } },
    { id: 'win', h: 'Win %', k: 'win', po: 1, cell: function (f, q, st) { return fmtOdds(st.po.win); } },
    { id: 'poev', h: 'Playoff EV $', k: 'poev', po: 1, cell: function (f, q, st) { return bbfMoney(st.po.ev); } },
    { id: 'tev', h: 'Total EV $', k: 'tev', po: 1, cell: function (f, q, st) { return '<b>' + bbfMoney(st.po.ev + st.ev) + '</b>'; } }
  ];
  var BBF_VIEW_ORDER = {
    now: ['cur', 'user', 'pts', 'pay', 'proj', 'ppr', 'prank', 'best', 't100', 't1k', 'cash', 'ev', 'podr', 'adv1', 'adv2', 'adv3', 'favg', 'fbest', 'win', 'poev', 'tev'],
    proj: ['ppr', 'mv', 'user', 'proj', 'cur', 'pts', 'pay', 'prank', 'best', 't100', 't1k', 'cash', 'ev', 'podr', 'adv1', 'adv2', 'adv3', 'favg', 'fbest', 'win', 'poev', 'tev']
  };
  function bbfColOn(f, c) {
    if (c.pods) return !!f.podRank;
    if (c.po) return !!(f.all && f.all.adv1);
    return !c.sim || !!f.all;
  }
  function bbfViewCols(f) {
    var byId = {};
    BBF_BOARD_COLS.forEach(function (c) { byId[c.id] = c; });
    return BBF_VIEW_ORDER[(f.view.mode === 'proj' && f.all) ? 'proj' : 'now'].map(function (id) { return byId[id]; })
      .filter(function (c) { return bbfColOn(f, c); });
  }
  // sim results for squad q (null before a run). Your own teams use their
  // exact per-sim ranks; everyone else the whole-field running sums.
  function bbfStat(f, q) {
    var A = f.all;
    if (!A) return null;
    var n = f.simsDone, own = f.ownRes && f.ownRes[q];
    return {
      proj: A.sumTot[q] / n, prank: own ? own.rank.p50 : f.projRank[q], best: own ? own.rank.min : A.best[q],
      t100: own ? own.top100 : A.top100[q] / n, t1k: own ? own.top1k : A.top1k[q] / n,
      cash: own ? own.cash : A.cash[q] / n, ev: own ? own.ev : A.ev[q] / n,
      // playoffs (null without draft groups)
      po: A.adv1 ? { adv1: A.adv1[q] / n, adv2: A.adv2[q] / n, adv3: A.adv3[q] / n, win: A.win[q] / n,
                     favg: A.adv3[q] ? A.finSum[q] / A.adv3[q] : null, fbest: A.adv3[q] ? A.finBest[q] : null,
                     ev: A.poEv[q] / n } : null
    };
  }
  function bbfSortKey(f, key, q) {
    var A = f.all;
    switch (key) {
      case 'pts': return f.curPts[q];
      case 'pay': return bbFieldPayout(f, f.curRank[q] || 1e9);
      case 'proj': return A.sumTot[q];
      case 'prank': return f.projRank[q];
      case 'ppr': return f.projPtsRank[q];
      case 'mv': return (f.curRank[q] || 0) - f.projPtsRank[q];
      case 'best': return A.best[q];
      case 't100': return A.top100[q];
      case 't1k': return A.top1k[q];
      case 'cash': return A.cash[q];
      case 'ev': return A.ev[q];
      case 'podr': return f.podRank[q] || 99;
      case 'adv1': return A.adv1[q];
      case 'adv2': return A.adv2[q];
      case 'adv3': return A.adv3[q];
      case 'win': return A.win[q];
      case 'favg': return A.adv3[q] ? A.finSum[q] / A.adv3[q] : 1e9;
      case 'fbest': return A.adv3[q] ? A.finBest[q] : 1e9;
      case 'poev': return A.poEv[q];
      case 'tev': return A.poEv[q] + A.ev[q];
      default: return f.curRank[q] || 1e9;
    }
  }
  function bbfUserSquads(f, name) {
    if (!f.userIx) {
      f.userIx = new Map();
      for (var i = 0; i < f.vis.length; i++) {
        var q = f.vis[i], u = String(f.users[q]).toLowerCase(), arr = f.userIx.get(u);
        if (!arr) f.userIx.set(u, arr = []);
        arr.push(q);
      }
    }
    return f.userIx.get(String(name).toLowerCase()) || [];
  }
  // filtered + sorted squad list for the current view (cached until it changes)
  function bbfBoardList(f) {
    var v = f.view, col = null;
    BBF_BOARD_COLS.forEach(function (c) { if (c.k === v.key) col = c; });
    if (!col || !bbfColOn(f, col)) { v.key = 'cur'; v.dir = 'asc'; }
    var sig = [v.user, v.mine, v.key, v.dir, f.runId || 0].join('|');
    if (f._list && f._listSig === sig) return f._list;
    var base = v.user ? Int32Array.from(bbfUserSquads(f, v.user)) : (v.mine ? Int32Array.from(f.own) : f.vis);
    var n = base.length, keys = new Float64Array(n), idx = new Int32Array(n), sgn = v.dir === 'asc' ? 1 : -1;
    for (var i = 0; i < n; i++) { keys[i] = sgn * bbfSortKey(f, v.key, base[i]); idx[i] = i; }
    var cr = f.curRank;
    idx.sort(function (a, b) { return (keys[a] - keys[b]) || ((cr[base[a]] || 1e9) - (cr[base[b]] || 1e9)); });
    var out = new Int32Array(n);
    for (var j = 0; j < n; j++) out[j] = base[idx[j]];
    f._list = out; f._listSig = sig;
    return out;
  }
  function bbfMoney(v) { return '$' + (v >= 100 ? Math.round(v).toLocaleString() : v.toFixed(v < 10 ? 2 : 0)); }
  // "What do these teams pay back?" — regular-season EV + playoff EV against
  // their entry fees. Without draft groups there is no playoff sim, so the
  // total is regular season only and says so.
  // A steadier playoff EV. The simmed figure pays each team by where it
  // actually finished, and one $2M winner per run makes that jumpy even over
  // thousands of playoff replays. This one keeps the sim's odds of advancing
  // and of winning a week-15 group (many events, stable) and pays every
  // Round-3 team the AVERAGE Round-3-and-beyond prize instead of its own
  // finish: r2Prize x P(out in Round 2) + avgR3 x P(reach Round 3). It ignores
  // a team being better or worse than average once it is in Round 3.
  function bbfSmoothPo(f, adv1, adv2) {
    var po = f.po, pl = f.results && f.results.playoff;
    if (!po || !pl || !pl.round3) return null;
    var nFin = Math.round(pl.finalists), finalPool = 0;
    for (var i = 0; i < nFin; i++) finalPool += po.finalPrize[Math.min(i, po.finalPrize.length - 1)];
    var r3Pool = 0;
    for (var k = 1; k < po.g3; k++) r3Pool += po.r3Prize[Math.min(k, po.r3Prize.length - 1)];
    var avgR3 = (finalPool + r3Pool * nFin) / pl.round3;
    return po.r2Prize * Math.max(0, adv1 - adv2) + avgR3 * adv2;
  }
  function bbfReturnCards(f, card, nTeams, regEv, poEv, poSmooth) {
    var hasPo = poEv != null, total = regEv + (hasPo ? poEv : 0);
    var fee = (f.po && f.po.entryFee) || 0, fees = fee * nTeams;
    var avg = (fee && f.po.pool && f.meta.total) ? 100 * f.po.pool / (+f.meta.total * fee) : null;
    var st = poSmooth != null ? regEv + poSmooth : null;
    return card('Total expected return', bbfMoney(total),
        hasPo ? 'regular season ' + bbfMoney(regEv) + ' + playoffs ' + bbfMoney(poEv) + (st != null ? ' · steadier estimate ' + bbfMoney(st) : '')
          : 'regular season only — the playoff money needs a file with draft groups') +
      (fees ? card('Entry fees', bbfMoney(fees), nTeams + ' × $' + fee) : '') +
      (fees && hasPo ? card('Return on entries', (100 * total / fees).toFixed(1) + '%',
        (total >= fees ? '+' : '−') + bbfMoney(Math.abs(total - fees)) + ' expected net' +
        (st != null ? ' · steadier estimate ' + (100 * st / fees).toFixed(1) + '%' : '') +
        (avg ? ' · an average team returns ' + avg.toFixed(1) + '%' : '')) : '');
  }
  function bbfPortfolioHtml(f, list) {
    var v = f.view, n = list.length, pts = 0, payN = 0, pay = 0, bestNow = 1e9, expCash = 0, ev = 0, likely = 0, bestProj = 1e9, expo = {}, r = f.roster;
    var advNow = 0, expAdv = 0, expR3 = 0, expFin = 0, expWin = 0, poEv = 0, bestFin = 1e9, hasPo = false;
    for (var i = 0; i < n; i++) {
      var q = list[i], p = bbFieldPayout(f, f.curRank[q] || 1e9), s = bbfStat(f, q);
      pts += f.curPts[q];
      if (f.podRank && f.podRank[q] && f.podRank[q] <= 2) advNow++;
      if (s && s.po) {
        hasPo = true; expAdv += s.po.adv1; expR3 += s.po.adv2; expFin += s.po.adv3; expWin += s.po.win; poEv += s.po.ev;
        if (s.po.fbest != null && s.po.fbest < bestFin) bestFin = s.po.fbest;
      }
      if (p > 0) { payN++; pay += p; }
      if (f.curRank[q] && f.curRank[q] < bestNow) bestNow = f.curRank[q];
      if (s) { expCash += s.cash; ev += s.ev; if (s.cash >= 0.5) likely++; if (s.prank < bestProj) bestProj = s.prank; }
      for (var k = r.start[q]; k < r.start[q + 1]; k++) expo[r.ix[k]] = (expo[r.ix[k]] || 0) + 1;
    }
    var top = Object.keys(expo).sort(function (a, b) { return expo[b] - expo[a]; }).slice(0, 20);
    function card(label, val, sub) {
      return '<div style="background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 16px;min-width:110px">' +
        '<div style="font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.5px">' + label + '</div>' +
        '<div style="font-size:19px;font-weight:700">' + val + '</div>' +
        (sub ? '<div style="font-size:11px;color:var(--dim)">' + sub + '</div>' : '') + '</div>';
    }
    var isMe = v.mine || (f.meta.me && String(v.user).toLowerCase() === String(f.meta.me).toLowerCase());
    var podNow = (!f.podRank && isMe) ? f.teams.filter(function (t) { return t.podPlace && t.podPlace <= 2; }).length : null;
    return '<h3 style="margin-bottom:6px">' + (v.user ? '@' + esc(f.users[list[0]]) : 'My teams') +
      ' <button id="bbf-clear" style="padding:2px 9px;font-weight:normal">× show everyone</button></h3>' +
      '<div style="display:flex;gap:10px;flex-wrap:wrap;margin:2px 0 8px">' +
      card('Teams', n, 'avg ' + fmt(pts / n) + ' pts · best rank ' + (bestNow < 1e9 ? bbfRank(bestNow) : '—')) +
      card('In the money now', payN, bbfMoney(pay) + ' at current ranks') +
      (f.all ? card('Projected in the money', expCash.toFixed(expCash < 10 ? 2 : 1), likely + ' team' + (likely === 1 ? '' : 's') + ' better than 50/50') : '') +
      (f.all ? card('Projected winnings', bbfMoney(ev), 'reg-season EV · best proj rank ' + bbfRank(bestProj)) : '') +
      (podNow != null ? card('Top 2 in pod', podNow, 'advancing to Round 2 as of the pull') : '') +
      (f.podRank ? card('Advancing now', advNow, 'top 2 in their draft · ' + (100 * advNow / n).toFixed(1) + '% (even = 16.7%)') : '') +
      (hasPo ? card('Projected advancing', expAdv.toFixed(expAdv < 10 ? 2 : 1), (100 * expAdv / n).toFixed(1) + '% of teams') : '') +
      (hasPo ? card('Projected in Round 3', expR3.toFixed(2), 'win a week-15 group') : '') +
      (hasPo ? card('Projected finalists', expFin.toFixed(2), 'best final place ' + (bestFin < 1e9 ? bbfRank(bestFin) : '—') + ' · win ' + fmtOdds(expWin)) : '') +
      (hasPo ? card('Playoff EV', bbfMoney(poEv), 'as simmed · steadier estimate ' + bbfMoney(bbfSmoothPo(f, expAdv, expR3) || 0)) : '') +
      (f.all ? bbfReturnCards(f, card, n, ev, hasPo ? poEv : null, hasPo ? bbfSmoothPo(f, expAdv, expR3) : null) : '') +
      '</div>' +
      (f.all ? '' : '<p class="dim" style="font-size:11px;margin:0 0 6px">Run the sim to add projected finishes for these teams.</p>') +
      '<p style="font-size:12px;margin:0 0 6px"><b>Exposure:</b> ' + top.map(function (k) {
        return esc(r.players[k].name) + ' <span class="dim">' + (100 * expo[k] / n).toFixed(0) + '%</span>';
      }).join(' · ') + '</p>' +
      '<p class="dim" style="font-size:11px;margin:0 0 8px">"In the money" = inside the overall regular-season paid places.' +
      (f.podRank ? ' Advancing = top 2 of the team\'s own 12-team draft.' +
        ((f.podExact && !isMe) ? ' <b>These teams sit in random stand-in draft groups</b> (only your own drafts\' real groups are loaded), so their advancing and playoff figures are estimates.' : '')
        : ' Pod advancing (top 2 of each 12-team draft) and the playoff sim need draft groups — load a draft-groups file (Draft Helper → Pull my draft groups).') + '</p>';
  }
  function renderBBFieldBoard() {
    var f = state.bbField;
    if (!f) return;
    var v = f.view, list = bbfBoardList(f), n = list.length;
    $('bbf-lookup').innerHTML = (v.user || v.mine) && n ? bbfPortfolioHtml(f, list) : '';
    if ($('bbf-clear')) $('bbf-clear').addEventListener('click', function () {
      v.user = ''; v.mine = false; v.page = 0; $('bbf-mine').checked = false; $('bbf-user').value = '';
      renderBBFieldBoard();
    });
    var pages = Math.max(1, Math.ceil(n / BBF_PAGE));
    v.page = Math.max(0, Math.min(pages - 1, v.page));
    var from = v.page * BBF_PAGE, to = Math.min(n, from + BBF_PAGE);
    var cols = bbfViewCols(f);
    function pager() {
      return '<div class="bar bbf-pager" style="margin:6px 0"><button data-pg="first">«</button><button data-pg="prev">‹ Prev</button> ' +
        '<label>Page <input type="number" class="bbf-pgnum" value="' + (v.page + 1) + '" min="1" max="' + pages + '" style="width:76px"> of ' +
        pages.toLocaleString() + '</label> <button data-pg="next">Next ›</button><button data-pg="last">»</button> ' +
        '<span class="dim">' + (n ? (from + 1).toLocaleString() + '–' + to.toLocaleString() + ' of ' : '') + n.toLocaleString() + ' teams' +
        (v.user ? ' for @' + esc(v.user) : (v.mine ? ' (yours)' : '')) + '</span></div>';
    }
    var html = pager() + '<table><thead>' + thRow(cols, { key: v.key, dir: v.dir }) + '</thead><tbody>';
    for (var i = from; i < to; i++) {
      var q = list[i], own = q >= f.nField ? f.teams[q - f.nField] : null, st = bbfStat(f, q);
      html += '<tr data-q="' + q + '" style="cursor:pointer">';
      for (var ci = 0; ci < cols.length; ci++) html += '<td' + (cols[ci].l ? ' class="l"' : '') + '>' + cols[ci].cell(f, q, st, own) + '</td>';
      html += '</tr>';
    }
    html += '</tbody></table>' + (to - from > 25 ? pager() : '') +
      '<p class="dim" style="font-size:11px">Rank / Pts now = ' + (f.nowAt ? 'Underdog\'s points at pull time plus every game finished since (Sleeper stats — the same method reproduces Underdog\'s own totals for 99.9% of teams), kept current without running a sim'
        : 'as pulled from Underdog — updating from finished games') +
      '. Paying now = the regular-season prize at the current rank. ' +
      (f.all ? 'Proj final pts = average simmed final total; Proj pts rank = where that total places among every team (the projected season leaderboard — pick the Projected standings view to lead with it; "vs now" = places gained or lost against the current rank). ' +
        'Averages bunch much tighter than any one real season does, so a single season usually lands a team worse than its Proj pts rank: Typical finish = the team\'s typical simmed place (the median for your own teams, the geometric mean of the simmed ranks for everyone else). Top finish = the best overall place the team reached in any of the ' +
        f.simsDone + ' sims. Top 100 / Top 1,000 / Cash % = share of sims finishing there; EV $ = average regular-season payout (the Round-2 advance prize is separate). ' +
        '0% means "not once in ' + f.simsDone + ' sims", not impossible. ' : '') +
      (f.podRank ? 'Pod now = place in its own 12-team draft on current points (top 2 advance). ' : '') +
      (f.podExact ? 'Only YOUR drafts\' real groups are loaded: a ~ marks a team in a random stand-in group, so its pod place, advance odds and playoff ' +
        'numbers are estimates (yours are exact). ' : '') +
      (f.all && f.all.adv1 ? 'Adv % = finishes top 2 in its draft; Rd 3 % = also wins its 14-team week-15 group; Final % = also wins its 12-team week-16 group and ' +
        'reaches the 667-team week-17 final; Avg / Best final = its average and best finishing place in the finals it reached; Win % = takes first. Playoff groups are ' +
        're-drawn at random, and each simulated regular season\'s playoffs are replayed ' + ((f.po && f.po.reps) || 1) + ' times so the prize money settles. ' +
        'Playoff EV = average playoff prize; Total EV adds the regular-season EV. ' : '') +
      'Click a column to sort the whole list, a username for that player\'s portfolio, a row for the roster.</p>';
    $('bbf-table').innerHTML = html;
    document.querySelectorAll('#bbf-table .bbf-pager button').forEach(function (b) {
      b.addEventListener('click', function () {
        var p = b.dataset.pg;
        v.page = p === 'first' ? 0 : p === 'last' ? pages - 1 : v.page + (p === 'next' ? 1 : -1);
        renderBBFieldBoard();
      });
    });
    document.querySelectorAll('#bbf-table .bbf-pgnum').forEach(function (inp) {
      inp.addEventListener('change', function () { v.page = (+inp.value || 1) - 1; renderBBFieldBoard(); });
    });
    document.querySelectorAll('#bbf-table a[data-u]').forEach(function (a) {
      a.addEventListener('click', function (ev) {
        ev.preventDefault(); ev.stopPropagation();
        $('bbf-user').value = a.dataset.u;
        bbfLookup();
      });
    });
    document.querySelectorAll('#bbf-table tbody tr').forEach(function (tr) {
      tr.addEventListener('click', function () { renderBBFieldDetail(+tr.dataset.q); });
    });
    document.querySelectorAll('#bbf-table th[data-sort]').forEach(function (th) {
      th.addEventListener('click', function () {
        var k = th.dataset.sort, col = null;
        BBF_BOARD_COLS.forEach(function (c) { if (c.k === k) col = c; });
        if (v.key === k) v.dir = v.dir === 'desc' ? 'asc' : 'desc';
        else { v.key = k; v.dir = (col && col.dir) || 'desc'; }
        v.page = 0;
        renderBBFieldBoard();
      });
    });
  }

  // cards + cut lines for YOUR teams (after a run), then the board
  function renderBBFieldTable() {
    var f = state.bbField;
    if (!f) return;
    if (!f.results) { $('bbf-summary').innerHTML = ''; renderBBFieldBoard(); return; }
    var res = f.results, ownRows = res.teams;
    function card(label, val, sub) {
      return '<div style="background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 16px;min-width:110px">' +
        '<div style="font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.5px">' + label + '</div>' +
        '<div style="font-size:19px;font-weight:700">' + val + '</div>' +
        (sub ? '<div style="font-size:11px;color:var(--dim)">' + sub + '</div>' : '') + '</div>';
    }
    var evSum = 0, cashSum = 0, payNow = 0, nPayNow = 0, best = ownRows[0], top = ownRows[0];
    ownRows.forEach(function (r) {
      var pn = bbFieldPayout(f, f.curRank[r.squad] || 1e9);
      evSum += r.ev; cashSum += r.cash; payNow += pn;
      if (pn > 0) nPayNow++;
      if ((f.curRank[r.squad] || 1e9) < (f.curRank[best.squad] || 1e9)) best = r;
      if (r.rank.min < top.rank.min) top = r;
    });
    var html = '<div style="display:flex;gap:10px;flex-wrap:wrap;margin:2px 0 10px">' +
      card('Your teams', ownRows.length, esc(f.meta.tournament)) +
      card('Best rank now', bbfRank(f.curRank[best.squad]), esc(best.t.title) + ' · ' + fmt(f.curPts[best.squad]) + ' pts') +
      card('Paying now', '$' + payNow.toFixed(0), nPayNow + ' team' + (nPayNow === 1 ? '' : 's') + ' inside the paid places') +
      card('Expected cashes', cashSum.toFixed(2), 'teams finishing in the paid places') +
      card('Reg-season EV', '$' + evSum.toFixed(evSum < 10 ? 2 : 0), 'all ' + ownRows.length + ' teams') +
      card('Top finish', bbfRank(top.rank.min), esc(top.t.title) + ' — best place in any sim') +
      '</div>';
    if (f.all && f.all.adv1) {
      var A = f.all, nS = f.simsDone, a1 = 0, a2 = 0, a3 = 0, w = 0, pe = 0, advNow = 0, bf = 1e9;
      f.own.forEach(function (q) {
        a1 += A.adv1[q] / nS; a2 += A.adv2[q] / nS; a3 += A.adv3[q] / nS; w += A.win[q] / nS; pe += A.poEv[q] / nS;
        if (f.podRank[q] && f.podRank[q] <= 2) advNow++;
        if (A.adv3[q] && A.finBest[q] < bf) bf = A.finBest[q];
      });
      html += '<div style="display:flex;gap:10px;flex-wrap:wrap;margin:2px 0 10px">' +
        card('Advancing now', advNow, 'of ' + f.own.length + ' · top 2 in their draft') +
        card('Projected advancing', a1.toFixed(1), (100 * a1 / f.own.length).toFixed(1) + '% (even = 16.7%)') +
        card('Projected in Round 3', a2.toFixed(2), 'win a week-15 group') +
        card('Projected finalists', a3.toFixed(2), 'best final place ' + (bf < 1e9 ? bbfRank(bf) : '—')) +
        card('Title odds', fmtOdds(w), 'any of your teams wins it') +
        card('Playoff EV', bbfMoney(pe), 'as simmed · steadier estimate ' + bbfMoney(bbfSmoothPo(f, a1, a2) || 0)) +
        '</div>';
    }
    html += '<div style="display:flex;gap:10px;flex-wrap:wrap;margin:2px 0 10px">' +
      bbfReturnCards(f, card, ownRows.length, evSum, (f.all && f.all.adv1) ? pe : null, (f.all && f.all.adv1) ? bbfSmoothPo(f, a1, a2) : null) + '</div>' +
      ((f.all && f.all.adv1) ? '<p class="dim" style="font-size:11px;margin:-4px 0 10px">Playoff EV "as simmed" pays each team by where it actually finished — one team wins $2M ' +
        'every run, so it stays jumpy even over thousands of playoff replays. The steadier estimate keeps the simmed odds of advancing and of winning a week-15 group but pays every ' +
        'Round-3 team the average Round-3-and-beyond prize. The truth is most likely between the two; more sims pull them together.</p>' : '');
    html += '<table style="margin-bottom:10px"><thead><tr><th class="l">Overall place</th><th>Score now</th><th>Projected final</th>' +
      '<th>p10</th><th>p90</th><th>Pts/wk from here</th></tr></thead><tbody>';
    res.cuts.forEach(function (c) {
      html += '<tr><td class="l">' + (c.rank === f.lastPaid ? 'Last paid place (' + bbfRank(c.rank) + ')' : (c.rank === 1 ? '1st' : 'Place ' + bbfRank(c.rank))) +
        '</td><td>' + fmt(c.cur) + '</td><td><b>' + fmt(c.final.mean, 0) + '</b></td><td class="dim">' + fmt(c.final.p10, 0) +
        '</td><td class="dim">' + fmt(c.final.p90, 0) + '</td><td>' +
        (res.weeksSimmed ? fmt((c.final.mean - c.cur) / res.weeksSimmed) : '—') + '</td></tr>';
    });
    html += '</tbody></table>';
    if (f.tiers.length) {
      html += '<p class="dim" style="font-size:11px;margin:0 0 10px"><b>Regular-season payouts on the leaderboard:</b> ' +
        f.tiers.map(function (t) {
          return (t.from === t.to ? bbfRank(t.from) : bbfRank(t.from) + '–' + bbfRank(t.to)) + ': $' + t.amt.toLocaleString();
        }).join(' · ') + '</p>';
    }
    $('bbf-summary').innerHTML = html;
    renderBBFieldBoard();
  }

  // TEAM POP-UP: click a row -> the roster with every player's points so far
  // and projected points the rest of the regular season, plus the team's own
  // numbers. "Proj rest" = the sum of the engine's weekly means for the weeks
  // still to play (this week skipped once the player's game is final).
  // Player projections add up to MORE than the team's projected points —
  // best ball only counts the top 8 scores each week.
  function bbfPlayerRows(f, q) {
    var r = f.roster, rows = [], cur = f.nowWeek || state.injuryWeek || 1, pts = f.plNow || f.plPulled;
    for (var i = r.start[q]; i < r.start[q + 1]; i++) {
      var k = r.ix[i], p = r.players[k], rest = 0, wks = 0;
      if (!p.stub) {
        for (var wk = cur; wk <= BB_REG_TO; wk++) {
          if (wk === cur && f.lockMask && f.lockMask[k]) continue; // already played this week
          var wp = E.weeklyProjection(p, wk, E.PRESETS.half, state.schedule);
          if (wp) { rest += E.effMean(wp); wks++; }
        }
      }
      rows.push({ name: p.name, pos: p.pos, tm: (f.pTeams && f.pTeams[k]) || (p.stub ? '' : E.normTeam(p.tmNow || p.tm || '')), now: pts[k] || 0,
                  rest: rest, wks: wks, stub: !!p.stub, played: !!(f.lockMask && f.lockMask[k]) });
    }
    return rows;
  }
  function bbfCloseModal() { var m = $('bbf-modal'); if (m) m.style.display = 'none'; }
  function renderBBFieldDetail(q) {
    var f = state.bbField;
    if (!f) return;
    var m = $('bbf-modal');
    if (!m) {
      m = document.createElement('div');
      m.id = 'bbf-modal';
      m.style.cssText = 'display:none;position:fixed;inset:0;background:rgba(0,0,0,.62);z-index:1000;overflow:auto;padding:4vh 12px';
      m.addEventListener('click', function (ev) { if (ev.target === m) bbfCloseModal(); });
      document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') bbfCloseModal(); });
      document.body.appendChild(m);
    }
    var own = q >= f.nField ? f.teams[q - f.nField] : null, r = f.ownRes && f.ownRes[q], s = bbfStat(f, q);
    var pay = bbFieldPayout(f, f.curRank[q] || 1e9);
    function stat(label, val, sub) {
      return '<div style="background:var(--bg,#0d1117);border:1px solid var(--line);border-radius:8px;padding:6px 12px;min-width:92px">' +
        '<div style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.5px">' + label + '</div>' +
        '<div style="font-size:16px;font-weight:700">' + val + '</div>' + (sub ? '<div style="font-size:10px;color:var(--dim)">' + sub + '</div>' : '') + '</div>';
    }
    var html = '<div style="max-width:900px;margin:0 auto;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px">' +
      '<div style="display:flex;align-items:baseline;gap:10px;margin-bottom:10px"><h3 style="margin:0;flex:1">' + (own ? esc(own.title) + ' <span class="dim" style="font-weight:normal">· ' : '') +
      '@' + esc(f.users[q]) + (own ? '</span>' : '') + '</h3>' +
      '<button id="bbf-modal-user" style="padding:2px 9px">portfolio</button><button id="bbf-modal-x" style="padding:2px 9px">✕</button></div>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">' +
      stat('Rank now', f.curRank[q] ? bbfRank(f.curRank[q]) : '—', fmt(f.curPts[q], 2) + ' pts' + (pay > 0 ? ' · paying ' + bbfMoney(pay) : '')) +
      (f.podRank && f.podRank[q] ? stat('In its draft', ((f.podExact && !f.podExact[q]) ? '~' : '') + f.podRank[q] + ' of 12', f.podRank[q] <= 2 ? 'advancing now' : 'top 2 advance') : '') +
      (s ? stat('Proj final', fmt(s.proj, 0) + ' pts', 'proj-points rank ' + bbfRank(f.projPtsRank[q])) +
           stat('Typical finish', bbfRank(s.prank), 'top finish ' + bbfRank(s.best)) +
           stat('Cash %', fmtOdds(s.cash), 'reg-season EV ' + bbfMoney(s.ev)) : '') +
      (s && s.po ? stat('Advance', fmtOdds(s.po.adv1), 'Rd 3 ' + fmtOdds(s.po.adv2) + ' · final ' + fmtOdds(s.po.adv3)) +
                   stat('Total EV', bbfMoney(s.po.ev + s.ev), 'playoffs ' + bbfMoney(s.po.ev) + ' · win ' + fmtOdds(s.po.win)) : '') +
      '</div>';
    var rows = bbfPlayerRows(f, q), order = { QB: 0, RB: 1, WR: 2, TE: 3 }, sumNow = 0, sumRest = 0;
    rows.sort(function (x, y) { return (order[x.pos] - order[y.pos]) || ((y.now + y.rest) - (x.now + x.rest)); });
    html += '<table><thead><tr><th class="l">Player</th><th>Pos</th><th>Team</th><th>Proj season pts</th><th>Pts so far</th><th>Proj rest of season</th><th>Proj / wk</th></tr></thead><tbody>';
    var lastPos = null;
    rows.forEach(function (x) {
      sumNow += x.now; sumRest += x.rest;
      html += '<tr' + (lastPos && lastPos !== x.pos ? ' style="border-top:2px solid var(--line)"' : '') + '><td class="l">' + (x.stub ? '<span class="dim">' + esc(x.name) + '</span>' : '<b>' + esc(x.name) + '</b>') +
        (x.played ? ' <span class="dim" title="this week\'s game is final">✓ wk ' + (f.nowWeek || '') + '</span>' : '') +
        '</td><td class="dim">' + esc(x.pos) + '</td><td class="dim">' + esc(x.tm || '—') + '</td><td><b>' + fmt(x.now + x.rest) + '</b></td><td>' + fmt(x.now) + '</td><td>' +
        (x.stub ? '<span class="dim" title="no projection — hurt or unrostered">—</span>' : fmt(x.rest)) + '</td><td class="dim">' + (x.wks ? fmt(x.rest / x.wks) : '—') +
        '</td></tr>';
      lastPos = x.pos;
    });
    html += '<tr style="border-top:2px solid var(--line)"><td class="l dim" colspan="3">All ' + rows.length + ' players</td><td class="dim">' + fmt(sumNow + sumRest) + '</td><td class="dim">' + fmt(sumNow) + '</td><td class="dim">' + fmt(sumRest) +
      '</td><td></td></tr></tbody></table>' +
      '<p class="dim" style="font-size:11px;margin:8px 0 0">Proj season pts = the player\'s projected total for the regular season (weeks 1–' + BB_REG_TO + '): what he has scored plus what he is projected to add. Pts so far = every point the player has scored this season (Underdog\'s count at the pull, plus games finished since). ' +
      'Proj rest of season = his projected points for the regular-season weeks still to play (through week ' + BB_REG_TO + '). The team\'s own total is lower than the players\' sum — ' +
      'best ball only counts the best QB, 2 RB, 3 WR, TE and flex each week' + (s ? ', which is what "Proj final" simulates' : '') + '.</p>';
    if (r) {
      var edges = [10, 100, 1000, 10000, 100000], counts = new Array(edges.length + 1).fill(0);
      for (var i = 0; i < r.ranks.length; i++) {
        var bk = 0;
        while (bk < edges.length && r.ranks[i] > edges[bk]) bk++;
        counts[bk]++;
      }
      var labels = ['Top 10', '11–100', '101–1,000', '1,001–10,000', '10,001–100,000', '100,001+'];
      html += '<table style="margin-top:12px"><thead><tr>' + labels.map(function (l) { return '<th>' + l + '</th>'; }).join('') + '</tr></thead><tbody><tr>' +
        counts.map(function (c) { return '<td>' + fmtOdds(c / r.ranks.length) + '</td>'; }).join('') + '</tr></tbody></table>' +
        '<p class="dim" style="font-size:11px;margin:6px 0 0">Where this team finished overall across ' + r.ranks.length + ' sims · median ' + bbfRank(r.rank.p50) +
        ' · good run (10th pct) ' + bbfRank(r.rank.p10) + ' · final total ' + fmt(r.total.p10, 0) + ' / ' + fmt(r.total.p50, 0) + ' / ' + fmt(r.total.p90, 0) + ' (p10 / median / p90).</p>';
    }
    m.innerHTML = html + '</div>';
    m.style.display = 'block';
    m.scrollTop = 0;
    $('bbf-modal-x').addEventListener('click', bbfCloseModal);
    $('bbf-modal-user').addEventListener('click', function () { bbfCloseModal(); $('bbf-user').value = f.users[q]; bbfLookup(); });
  }

  // ---- username look-up: anyone's portfolio = the board filtered to them ----
  async function bbfLookup() {
    try {
      if (!(await bbfEnsureLoaded())) { $('bbf-note').textContent = 'Load a field file first.'; return; }
    } catch (e0) { $('bbf-note').textContent = 'Could not load the saved field file: ' + ((e0 && e0.message) || e0); return; }
    var f = state.bbField, name = $('bbf-user').value.trim().replace(/^@/, '').toLowerCase();
    if (name && !bbfUserSquads(f, name).length) {
      $('bbf-lookup').innerHTML = '<p class="dim">No teams for <b>' + esc(name) + '</b> in this file' +
        (f.meta.complete ? ' — check the spelling (exact Underdog username).' : ' — it is a PARTIAL file, so they may simply not have been pulled.') + '</p>';
      return;
    }
    f.view.user = name; f.view.mine = false; f.view.page = 0;
    $('bbf-mine').checked = false;
    $('bbf-detail').innerHTML = '';
    renderBBFieldBoard();
  }
  // Current standings <-> projected standings (teams ranked by projected final points)
  function bbfSetView() {
    var f = state.bbField, mode = $('bbf-view').value;
    if (!f) return;
    if (mode === 'proj' && !f.all) {
      $('bbf-view').value = 'now';
      $('bbf-note').textContent = 'The projected standings need a sim — press RUN OVERALL SIM first.';
      return;
    }
    f.view.mode = mode;
    f.view.key = mode === 'proj' ? 'ppr' : 'cur'; f.view.dir = 'asc'; f.view.page = 0;
    renderBBFieldBoard();
  }
  function bbfToggleMine() {
    var f = state.bbField;
    if (!f) return;
    f.view.mine = $('bbf-mine').checked; f.view.user = ''; f.view.page = 0;
    $('bbf-user').value = '';
    renderBBFieldBoard();
  }

  function bbLabel(t) {
    return (t.isMine ? '★ ' : '') + t.title + (t.teamName ? ' – ' + t.teamName : '') +
      (isSfTeam(t) ? ' [SF]' : '') + (t.slot ? ' · slot ' + t.slot : '') +
      (t.user ? ' · @' + t.user : '') + (t.date ? ' · ' + t.date : '');
  }
  var BB_COLS = [
    { h: '#' },
    { h: 'Team', l: 1, k: 'team', dir: 'asc', get: function (o) { return bbLabel(o.t); } },
    { h: 'Fee', k: 'fee', get: function (o) { return o.t.isMine ? o.t.fee : -1; } },
    { h: 'Reg mean', k: 'mean', get: function (o) { return o.r.mean; } },
    { h: 'p10', k: 'p10', get: function (o) { return o.r.p10; } },
    { h: 'Median', k: 'p50', get: function (o) { return o.r.p50; } },
    { h: 'p90', k: 'p90', get: function (o) { return o.r.p90; } },
    { h: 'PPG', k: 'ppg', get: function (o) { return o.r.p50 / o.r.regTo; } },
    { h: 'vs field', k: 'vf', get: function (o) { return o.r.fieldAvg != null ? o.r.mean - o.r.fieldAvg : -1e9; } },
    { h: 'Adv %', k: 'adv', get: function (o) { return o.r.adv != null ? o.r.adv : -1; } },
    { h: 'Finals %', k: 'fin', get: function (o) { return o.ev ? o.ev.pFinals : -1; } },
    { h: 'EV $', k: 'ev', get: function (o) { return o.ev ? o.ev.ev : -1; } },
    { h: 'Pod win', k: 'win', get: function (o) { return o.r.win != null ? o.r.win : -1; } },
    { h: 'W15 med', k: 'w15', get: function (o) { return o.r.po[0] ? o.r.po[0].p50 : 0; } },
    { h: 'W16 med', k: 'w16', get: function (o) { return o.r.po[1] ? o.r.po[1].p50 : 0; } },
    { h: 'W17 med', k: 'w17', get: function (o) { return o.r.po[2] ? o.r.po[2].p50 : 0; } }
  ];
  // Header cards for the current tournament filter: entries, fees, expected
  // advancers, prize EV vs the fees — plus the editable prize model.
  function renderBBSummaryStats(out, tf) {
    var mine = out.filter(function (o) { return o.t.isMine; });
    if (!mine.length) { $('bb-summary').innerHTML = ''; return; }
    var fees = 0, advSum = 0, advN = 0, evSum = 0, finSum = 0, evN = 0;
    var baseAdvSum = 0, baseFinSum = 0, baseN = 0;
    mine.forEach(function (o) {
      fees += o.t.fee || 0;
      var isElim = o.ev && o.ev.mode === 'eliminator';
      // eliminators excluded from advance/finals averages — different format
      if (o.r.adv != null && !isElim) { advSum += o.r.adv; advN++; }
      if (o.ev && !isElim) { finSum += o.ev.pFinals; }
      if (o.ev) { evSum += o.ev.ev; evN++; }
      if (o.ev && o.ev.baseAdv != null) { baseAdvSum += o.ev.baseAdv; baseFinSum += o.ev.baseFin; baseN++; }
    });
    function card(label, val, sub) {
      return '<div style="background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 16px;min-width:110px">' +
        '<div style="font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.5px">' + label + '</div>' +
        '<div style="font-size:19px;font-weight:700">' + val + '</div>' +
        (sub ? '<div style="font-size:11px;color:var(--dim)">' + sub + '</div>' : '') + '</div>';
    }
    var net = evSum - fees;
    var html = '<div style="display:flex;gap:10px;flex-wrap:wrap;margin:2px 0 10px">' +
      card('Teams', mine.length, tf === 'ALL' ? 'all tournaments' : esc(tf)) +
      card('Entry fees', '$' + fees.toFixed(0), '') +
      (advN ? card('Avg advance', (100 * advSum / advN).toFixed(1) + '%',
        'exp. ' + advSum.toFixed(1) + ' teams' +
        (baseN ? ' · even ' + (100 * baseAdvSum / baseN).toFixed(1) + '% = ' + baseAdvSum.toFixed(1) + ' teams' : '')) : '') +
      (advN ? card('Avg finals', (100 * finSum / advN).toFixed(2) + '%',
        'exp. ' + finSum.toFixed(2) + ' teams' +
        (baseN ? ' · even ' + (100 * baseFinSum / baseN).toFixed(2) + '% = ' + baseFinSum.toFixed(2) + ' teams' : '')) : '') +
      (evN ? card('Prize EV', '$' + evSum.toFixed(0), 'vs $' + fees.toFixed(0) + ' in') : '') +
      (evN ? card('Net EV', (net >= 0 ? '+$' : '−$') + Math.abs(net).toFixed(0),
        fees > 0 ? (100 * evSum / fees).toFixed(0) + '% of fees' : '') : '') +
      '</div>';
    if (tf !== 'ALL') {
      var m = prizeFor(tf);
      html += '<div class="bar" style="margin-bottom:4px;font-size:12px;color:var(--dim)">Prize model for <b style="color:var(--tx)">' + esc(tf) +
        '</b>: <select id="bb-pz-mode">' +
        '<option value="ladder"' + (m.mode === 'ladder' ? ' selected' : '') + '>same-roster playoffs (score ladder)</option>' +
        '<option value="redraft"' + (m.mode === 'redraft' ? ' selected' : '') + '>flat $ per advancer (no bracket)</option>' +
        '<option value="eliminator"' + (m.mode === 'eliminator' ? ' selected' : '') + '>eliminator (weekly survivor)</option>' +
        '</select>' +
        (m.mode !== 'eliminator' ? '<label>$ per advance <input type="number" id="bb-pz-adv" value="' + m.advCash + '" step="10"></label>' : '') +
        (m.mode === 'redraft'
          ? '<label>avg playoff $ per advancer <input type="number" id="bb-pz-pae" value="' + (m.perAdvEV || 0) + '" step="10"></label>' +
            '<label>P(finals | advance) <input type="number" id="bb-pz-pfa" value="' + (m.pFinGivenAdv != null ? m.pFinGivenAdv : 0.0048) + '" step="0.001" style="width:80px"></label>'
          : '') +
        (m.mode === 'eliminator'
          ? '<label>winner $ <input type="number" id="bb-pz-ew" value="' + (m.elimWin || 0) + '" step="1000"></label>' +
            '<label>other finalist $ <input type="number" id="bb-pz-ef" value="' + (m.elimFinal || 0) + '" step="500"></label>'
          : '') +
        (m.mode === 'ladder'
          ? '<label>W15 advance 1-in-<input type="number" id="bb-pz-a15" value="' + (m.adv15N || 10) + '" min="2" step="1" style="width:60px"></label>' +
            '<label>W16 1-in-<input type="number" id="bb-pz-a16" value="' + (m.adv16N || 10) + '" min="2" step="1" style="width:60px"></label>' +
            '<label>finals size <input type="number" id="bb-pz-fs" value="' + (m.finalsSize || 500) + '" min="2" step="1" style="width:70px"></label>'
          : '') +
        '</div>';
      if (m.mode === 'eliminator') {
        html += '<div class="note" style="margin-bottom:8px">Weekly survivor: top-6 of your 12-pod in wk 1, then a 50% head-to-head cut EVERY week to a ' +
          '3-person wk-17 final (baseline 1-in-65,536). The sim chains each week\'s win odds vs the pod field (real opponents on full boards, ADP-synthetic ' +
          'otherwise; survivor-quality bias ignored — late-week odds read a touch optimistic). Consistency wins here: high weekly FLOORS, not BBM ceilings. ' +
          'EV = P(win) × winner $ + P(other finalist) × finalist $ — prize defaults are placeholders, put the real payouts in.</div>';
      } else if (m.mode === 'redraft') {
        html += '<div class="note" style="margin-bottom:8px">BBM playoff rounds are FRESH 18-pick drafts (true since BBM IV, per the full datasets) — ' +
          'your drafted roster only plays wks 1–14, so playoff equity conditional on advancing is ~flat. EV = (advance $ + avg playoff $) × Adv%. ' +
          'P(finals | advance) default 0.595% = BBM VII structure (W15 1-of-14 × W16 1-of-12, 667-team finals) — the structure changes yearly, adjust here when it does.</div>';
      } else {
        // sim-derived cutoffs shown from the first team of this tournament with results
        var cutInfo = '';
        if (state.bb.results) {
          for (var ri = 0; ri < state.bb.results.length; ri++) {
            var rr = state.bb.results[ri], tt = state.bb.teams[rr.key];
            if (tt.title !== tf || !tt.isMine) continue;
            var evv = computeTeamEV(rr, tt);
            if (evv && evv.mode === 'ladder') {
              cutInfo = ' · <b style="color:var(--tx)">this run\'s 50/50 advance scores: W15 ' + evv.c15.toFixed(0) +
                ', W16 ' + evv.c16.toFixed(0) + '</b> (smooth score→odds curves from this contest\'s own field — validated on BBM III–VI: ' +
                'P(adv) = F(score)^(pod−1) matched history within 1–4 pts everywhere; superflex fields set a higher bar automatically)';
              break;
            }
          }
        }
        html += '<div class="bar" style="margin-bottom:8px;font-size:12px;color:var(--dim)">Finals payout by placement: ' +
          m.ftiers.map(function (t2, i) {
            return '<span style="white-space:nowrap">top <input type="number" class="bb-pz-t" data-i="' + i + '" data-k="top" value="' + t2.top +
              '" min="1" step="1" style="width:60px"> → $<input type="number" class="bb-pz-t" data-i="' + i + '" data-k="prize" value="' + t2.prize +
              '" step="100" style="width:96px"><button class="bb-pz-del" data-i="' + i + '" title="remove tier" style="padding:2px 7px;margin-left:2px">×</button></span>';
          }).join(' ') +
          ' <button id="bb-pz-add" style="padding:2px 9px">+ tier</button>' +
          ' <label>min cash $<input type="number" id="bb-pz-mc" value="' + (m.minCash || 0) + '" step="5" style="width:70px"></label>' +
          ' <span>enter the CONTEST\'s real structure + payouts (prizes are placeholders)' + cutInfo + '</span></div>';
      }
    } else if (evN) {
      html += '<div class="note">EV uses each tournament\'s saved prize model — pick a tournament in the filter to edit its cutoffs and payout ladder.</div>';
    }
    $('bb-summary').innerHTML = html;
    if (tf !== 'ALL') {
      function readAndSave(mutate) {
        var m2 = prizeFor(tf);
        if ($('bb-pz-mode')) m2.mode = $('bb-pz-mode').value;
        m2.redraft = m2.mode === 'redraft';
        if ($('bb-pz-adv')) m2.advCash = +$('bb-pz-adv').value || 0;
        if ($('bb-pz-a15')) m2.adv15N = Math.max(2, +$('bb-pz-a15').value || 10);
        if ($('bb-pz-a16')) m2.adv16N = Math.max(2, +$('bb-pz-a16').value || 10);
        if ($('bb-pz-fs')) m2.finalsSize = Math.max(2, +$('bb-pz-fs').value || 500);
        if ($('bb-pz-mc')) m2.minCash = +$('bb-pz-mc').value || 0;
        if ($('bb-pz-pae')) m2.perAdvEV = +$('bb-pz-pae').value || 0;
        if ($('bb-pz-pfa')) m2.pFinGivenAdv = +$('bb-pz-pfa').value || 0;
        if ($('bb-pz-ew')) m2.elimWin = +$('bb-pz-ew').value || 0;
        if ($('bb-pz-ef')) m2.elimFinal = +$('bb-pz-ef').value || 0;
        var tierEls = document.querySelectorAll('#bb-summary .bb-pz-t[data-k="top"]');
        if (tierEls.length) {
          var ftiers = [];
          tierEls.forEach(function (el) {
            var i = +el.dataset.i;
            var pz = document.querySelector('#bb-summary .bb-pz-t[data-i="' + i + '"][data-k="prize"]');
            ftiers.push({ top: Math.max(1, +el.value || 1), prize: pz ? (+pz.value || 0) : 0 });
          });
          m2.ftiers = ftiers;
        }
        delete m2.finalsEV;
        delete m2.tiers; // legacy absolute-score tiers superseded
        if (mutate) mutate(m2);
        savePrize(tf, m2);
        renderBBTable();
      }
      ['bb-pz-a15', 'bb-pz-a16', 'bb-pz-fs', 'bb-pz-mc', 'bb-pz-adv', 'bb-pz-pae', 'bb-pz-pfa', 'bb-pz-mode', 'bb-pz-ew', 'bb-pz-ef'].forEach(function (id) {
        var el = $(id);
        if (el) el.addEventListener('change', function () { readAndSave(); });
      });
      document.querySelectorAll('#bb-summary .bb-pz-t').forEach(function (el) {
        el.addEventListener('change', function () { readAndSave(); });
      });
      document.querySelectorAll('#bb-summary .bb-pz-del').forEach(function (el) {
        el.addEventListener('click', function () {
          var i = +el.dataset.i;
          readAndSave(function (m2) { if (m2.ftiers.length > 1) m2.ftiers.splice(i, 1); });
        });
      });
      var addBtn = $('bb-pz-add');
      if (addBtn) addBtn.addEventListener('click', function () {
        readAndSave(function (m2) { m2.ftiers.push({ top: m2.finalsSize || 500, prize: 0 }); });
      });
    }
  }

  function renderBBTable() {
    if (!state.bb || !state.bb.results) return;
    var show = $('bb-show').value, tf = $('bb-tourney').value;
    var podHasMine = {};
    state.bb.teams.forEach(function (t) { if (t.isMine) podHasMine[t.draftId] = 1; });
    var out = state.bb.results.map(function (r) {
      var t = state.bb.teams[r.key];
      return { r: r, t: t, ev: computeTeamEV(r, t) };
    }).filter(function (o) {
      if (tf !== 'ALL' && o.t.title !== tf) return false;
      if (show === 'all') return true;
      // "My teams": yours, plus every slot of a full board whose owner is unknown
      return o.t.isMine || (o.t.full && !podHasMine[o.t.draftId]);
    });
    renderBBSummaryStats(out, tf);
    var ss = state.bbSort = state.bbSort || { key: 'mean', dir: 'desc' };
    out = applySort(out, BB_COLS, ss);
    var html = '<table><thead>' + thRow(BB_COLS, ss) + '</thead><tbody>';
    out.forEach(function (o, i) {
      var r = o.r, t = o.t;
      var vf = r.fieldAvg != null ? r.mean - r.fieldAvg : null;
      var vfCol = vf == null ? 'var(--dim)' : (vf > 10 ? 'var(--acc)' : (vf < -10 ? '#f85149' : 'var(--tx)'));
      var nameCell = t.isMine ? '<b>' + esc(bbLabel(t)) + '</b>' : '<span class="dim">' + esc(bbLabel(t)) + '</span>';
      html += '<tr data-i="' + r.key + '" style="cursor:pointer"><td>' + (i + 1) +
        '</td><td class="l">' + nameCell +
        (t.isMine && t.unmatched.length ? ' <span class="dim" title="no Clay projection — hurt/unrostered, score 0">' + t.unmatched.length + ' inactive</span>' : '') +
        '</td><td class="dim">' + (t.isMine ? '$' + (t.fee || 0).toFixed(0) : '—') +
        '</td><td><b>' + fmt(r.mean, 0) + '</b></td><td class="dim">' + fmt(r.p10, 0) +
        '</td><td>' + fmt(r.p50, 0) + '</td><td class="dim">' + fmt(r.p90, 0) +
        '</td><td>' + fmt(r.p50 / r.regTo) +
        '</td><td style="color:' + vfCol + '">' + (vf == null ? '—' : (vf >= 0 ? '+' : '') + vf.toFixed(0)) +
        '</td><td>' + (r.adv != null ? '<b>' + pctf(r.adv) + '</b>' +
          (o.ev && o.ev.baseAdv != null ? ' <span class="dim" title="even-odds baseline for this format">/' + (100 * o.ev.baseAdv).toFixed(1) + '</span>' : '') : '—') +
        '</td><td class="dim">' + (o.ev ? fmtOdds(o.ev.pFinals) +
          (o.ev.baseFin != null ? ' <span title="even-odds baseline">/' + fmtOdds(o.ev.baseFin) + '</span>' : '') : '—') +
        '</td><td>' + (o.ev ? '<b>$' + o.ev.ev.toFixed(o.ev.ev < 10 ? 2 : 0) + '</b>' : '—') +
        '</td><td>' + (r.win != null ? pctf(r.win) : '—') +
        '</td><td>' + (r.po[0] ? fmt(r.po[0].p50) : '—') +
        '</td><td>' + (r.po[1] ? fmt(r.po[1].p50) : '—') +
        '</td><td>' + (r.po[2] ? fmt(r.po[2].p50) : '—') + '</td></tr>';
    });
    $('bb-table').innerHTML = html + '</tbody></table>' +
      '<p class="dim" style="font-size:11px">Reg = weeks 1–' + BB_REG_TO + ' best-ball total (1QB/2RB/3WR/1TE/1FLEX auto-picked ' +
      'per sampled week, Underdog half-PPR). Full-board drafts: vs field / Adv % / Pod win are simmed against the REAL 11 ' +
      'opponents (Adv = top-2). Exposure-only drafts: the pod is 11 synthetic opponents snake-drafted from ADP around your ' +
      'slot (deterministic per draft) — good for ranking your own teams, not real entrants. W15–17 = playoff-week score ' +
      'distributions (unconditional — not filtered on advancing). Finals % = P(advance AND beat the W15 cutoff AND the W16 ' +
      'cutoff in the same sim, cutoffs derived from the CONTEST\'S OWN simulated field at its 1-in-N advance rates — so a ' +
      'superflex field sets a higher bar automatically); EV $ pays finals sims by placement tier from the tournament\'s ' +
      'editable structure+payout model — deliberately rough, for comparing your own teams. In-season, played weeks are ' +
      'banked at real scores and only ' +
      'the remaining weeks are simmed. Click a column header to sort, a row for the roster.</p>';
    document.querySelectorAll('#bb-table tbody tr').forEach(function (tr) {
      tr.addEventListener('click', function () { renderBBDetail(+tr.dataset.i); });
    });
    wireSort('bb-table', BB_COLS, ss, renderBBTable);
  }

  function renderBBDetail(idx) {
    var t = state.bb && state.bb.teams[idx];
    if (!t) return;
    var r = (state.bb.results || []).filter(function (x) { return x.key === idx; })[0];
    var sc = E.PRESETS.half;
    var html = '<h3>' + esc(t.title) + ' — ' + (t.slot ? 'slot ' + t.slot + ', ' : '') + t.size + '-man' +
      (t.user ? ', @' + esc(t.user) : '') + (t.date ? ', drafted ' + t.date : '') +
      (t.isMine ? (t.fee ? ', $' + t.fee.toFixed(0) : '') : ' — <span class="dim">opponent team</span>') + '</h3>';
    if (r && r.rankCounts && r.podSize) {
      var ranks = [];
      for (var rk = 1; rk <= r.podSize; rk++) ranks.push(((r.rankCounts[rk] || 0) / r.sims * 100).toFixed(0) + '%');
      html += '<p class="dim" style="font-size:12px">Pod finish distribution (1st → ' + r.podSize + 'th): ' + ranks.join(' · ') + '</p>';
    }
    var ev = r ? computeTeamEV(r, t) : null;
    if (ev && ev.mode === 'eliminator') {
      var cv = ev.elim.curve;
      html += '<p class="dim" style="font-size:12px">Eliminator survival: ' +
        [1, 2, 4, 6, 8, 10, 12, 14, 16].filter(function (w) { return cv[w - 1] != null; })
          .map(function (w) { return 'wk' + w + ' ' + fmtOdds(cv[w - 1]); }).join(' · ') +
        ' · <b style="color:var(--tx)">final ' + fmtOdds(ev.elim.pFinal) + ' · WIN ' + fmtOdds(ev.elim.pWin) +
        '</b> · EV $' + ev.ev.toFixed(2) + ' on a $' + (t.fee || 0).toFixed(0) + ' entry (baseline final odds 1/65,536 — high weekly floors beat high ceilings here)</p>';
    } else if (ev && ev.redraft) {
      html += '<p class="dim" style="font-size:12px">Playoffs are re-drafts (BBM-style) — this roster only plays wks 1–14. ' +
        'Structural finals odds ' + pctf(ev.pFinals) + ' · <b style="color:var(--tx)">EV $' + ev.ev.toFixed(0) +
        '</b> on a $' + (t.fee || 0).toFixed(0) + ' entry (EV scales with Adv% only).</p>';
    } else if (ev) {
      var tierSum = ev.tierP.reduce(function (a, v) { return a + v; }, 0);
      function curveStr(c) { return c.map(function (x) { return x.s.toFixed(0) + '→' + x.p + '%'; }).join(' '); }
      html += '<p class="dim" style="font-size:12px">Finals ' + fmtOdds(ev.pFinals) +
        ' · advance curve vs this contest\'s own field (score→odds): W15 ' + curveStr(ev.curve.w15) +
        ' · W16 ' + curveStr(ev.curve.w16) +
        ' · placement odds: ' +
        ev.tiers.map(function (t2, i) {
          return 'top ' + t2.top + ' ($' + t2.prize.toLocaleString() + ', ≥' + t2.score.toFixed(0) + '): ' + fmtOdds(ev.tierP[i]);
        }).join(' · ') +
        ' · min-cash ($' + ev.minCash.toLocaleString() + '): ' + fmtOdds(Math.max(0, ev.pFinals - tierSum)) +
        ' · <b style="color:var(--tx)">EV $' + ev.ev.toFixed(ev.ev < 10 ? 2 : 0) + '</b> on a $' + (t.fee || 0).toFixed(0) + ' entry</p>';
    }
    html += '<table style="max-width:860px"><thead><tr><th>Pk</th><th>Rd</th><th class="l">Player</th><th>Pos</th>' +
      '<th>Tm</th><th>ADP</th><th>Clay pts</th><th>Reg proj</th><th class="l">Notes</th></tr></thead><tbody>';
    t.picks.forEach(function (pk) {
      var p = bbMatchPlayer(pk.name, pk.pos || null);
      var matched = !!p;
      var rd = t.size ? Math.ceil(pk.pick / t.size) : '—';
      var regProj = null, notes = [];
      if (matched) {
        regProj = 0;
        for (var w = 1; w <= BB_REG_TO; w++) {
          var wp = E.weeklyProjection(p, w, sc, state.schedule);
          if (wp) regProj += wp.mean;
        }
        if (p.qbWindow) notes.push(p.qbWindow.src === 'injury-start' ? 'misses wks 1–' + (p.qbWindow.s - 1) :
          'starter wks ' + p.qbWindow.s + '–' + p.qbWindow.e);
        if (p.ramp) notes.push('rookie ramp');
        if (p.clayGames < 17 && !p.qbWindow) notes.push('Clay ' + p.clayGames + ' gms');
      } else {
        notes.push('no Clay projection — hurt/unrostered, scores 0');
      }
      html += '<tr' + (matched ? '' : ' style="color:var(--dim)"') + '><td>' + pk.pick + '</td><td class="dim">' + rd +
        '</td><td class="l"><b>' + esc(pk.name) + '</b></td><td>' + (matched ? p.pos : pk.pos) +
        '</td><td>' + (matched ? p.tm : pk.tm) + '</td><td class="dim">' + (matched && p.adp != null ? p.adp : '—') +
        '</td><td class="dim">' + (matched ? fmt(E.seasonPoints(p, sc), 0) : '0') +
        '</td><td>' + (regProj != null ? '<b>' + fmt(regProj, 0) + '</b>' : '<b>0</b>') +
        '</td><td class="l dim">' + notes.join(' · ') + '</td></tr>';
    });
    html += '</tbody></table>' +
      '<p class="dim" style="font-size:11px">Reg proj = sum of pre-sample weekly means, weeks 1–' + BB_REG_TO +
      ' (Vegas × defense × windows/ramps). The best-ball lineup only starts 8 of these players each week, so the team total ' +
      'sits well below this column\'s sum — the column is for spotting who actually carries the roster.</p>';
    $('bb-detail').innerHTML = html;
    $('bb-detail').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // ---------------- TEAM PACE TRACKER ----------------
  // Renders data/pace_2026.js: season-to-date team tendencies vs the
  // coach-aware baseline, plus the multipliers the engine actually applies.
  function renderPaceTab() {
    var d = window.SIM_PACE_2026;
    if (!d || !d.teams) {
      $('pc-note').textContent = 'No pace data — run pull_pace_tracker.py.';
      return;
    }
    var live = Object.keys(d.teams).filter(function (t) { return d.teams[t].games > 0; }).length;
    $('pc-note').textContent = 'Updated ' + d.updated + ' — ' + (live ? live + ' teams with 2026 games.' :
      'no 2026 games yet: baselines only.') + ' Intel only — does not move projections.';
    function pcts(v) { return v == null ? '—' : (100 * v).toFixed(1); }
    function delta(cur, base, isPct) {
      if (cur == null || base == null) return '';
      var dv = cur - base;
      var txt = isPct ? (dv >= 0 ? '+' : '') + (100 * dv).toFixed(1) + 'pp' : (dv >= 0 ? '+' : '') + dv.toFixed(1);
      var big = Math.abs(isPct ? dv * 100 : dv) >= (isPct ? 3 : 3);
      var col = !big ? 'var(--dim)' : (dv > 0 ? 'var(--acc)' : '#f85149');
      return ' <span style="color:' + col + '">' + txt + '</span>';
    }
    // sort on the displayed value: 2026 season-to-date when it exists,
    // otherwise the baseline (preseason the whole table is baselines)
    function shown(o, m) {
      var c = o.r.cur || {}, b = o.r.base || {};
      return c[m] != null ? c[m] : (b[m] != null ? b[m] : -1);
    }
    function paceCol(h, m) { return { h: h, k: m, get: function (o) { return shown(o, m); } }; }
    var PACE_COLS = [
      { h: 'Team', l: 1, k: 'team', dir: 'asc', get: function (o) { return o.t; } },
      { h: 'Play-caller', l: 1, k: 'caller', dir: 'asc', get: function (o) { return o.r.caller || o.r.coach || ''; } },
      { h: 'Gms', k: 'gms', get: function (o) { return o.r.games || 0; } },
      paceCol('Plays/gm', 'plays'), paceCol('Neutral pass%', 'npr'), paceCol('PROE', 'proe'),
      paceCol('No-huddle%', 'huddle'), paceCol('2+TE%', 'te2'),
      { h: 'Baseline', l: 1, k: 'src', dir: 'asc', get: function (o) { return o.r.baseSrc || ''; } }
    ];
    var ss = state.paceSort = state.paceSort || { key: 'team', dir: 'asc' };
    var rows = applySort(Object.keys(d.teams).sort().map(function (t) { return { t: t, r: d.teams[t] }; }), PACE_COLS, ss)
      .map(function (o) { return o.t; });
    var html = '<table><thead>' + thRow(PACE_COLS, ss) + '</thead><tbody>';
    rows.forEach(function (t) {
      var r = d.teams[t], c = r.cur || {}, b = r.base || {};
      html += '<tr><td class="l"><b>' + t + '</b></td><td class="l dim" title="HC: ' + esc(r.coach || '?') + '">' + esc(r.caller || r.coach || '?') +
        '</td><td>' + (r.games || 0) +
        '</td><td>' + (c.plays != null ? c.plays.toFixed(1) : (b.plays != null ? '<span class="dim">' + b.plays.toFixed(1) + '</span>' : '—')) + delta(c.plays, b.plays, false) +
        '</td><td>' + (c.npr != null ? pcts(c.npr) : '<span class="dim">' + pcts(b.npr) + '</span>') + delta(c.npr, b.npr, true) +
        '</td><td>' + (c.proe != null ? c.proe.toFixed(1) : '<span class="dim">' + (b.proe != null ? b.proe.toFixed(1) : '—') + '</span>') +
        '</td><td>' + (c.huddle != null ? pcts(c.huddle) : '<span class="dim">' + pcts(b.huddle) + '</span>') + delta(c.huddle, b.huddle, true) +
        '</td><td>' + (c.te2 != null ? pcts(c.te2) : '<span class="dim">' + pcts(b.te2) + '</span>') + delta(c.te2, b.te2, true) +
        '</td><td class="l dim" style="font-size:11px">' + esc(r.baseSrc || '') + '</td></tr>';
    });
    $('pc-table').innerHTML = html + '</tbody></table>' +
      '<p class="dim" style="font-size:11px">Dim values = baseline (no 2026 sample yet). INTEL ONLY — projection multipliers ' +
      'from this drift were backtested (backtest_pace_layer.py, weeks 5/9/13 of 2019–25) and made player means WORSE ' +
      '(~49% win rate, monotonically worse at higher elasticity): Vegas totals + realized PPG already price it at player level. ' +
      'The drift itself is real and persistent (wk≤8 drift predicts wk9+ at r .44–.78) — use it for start/sit and trade reads, ' +
      'and expect Clay/consensus to lag it by weeks. Baselines follow the PLAY-CALLER (OC, or HC if he calls plays — hover the name for the HC): ' +
      'a returning caller keeps his own 2025 numbers even if his title changed, a new caller brings the pace identity of his last ' +
      'play-calling stop, a first-time caller inherits the offense he trained under (his tree\'s trend). Pass mix (neutral pass%, PROE) always stays with the roster — the QB decides those. Click a column header to sort.</p>';
    wireSort('pc-table', PACE_COLS, ss, renderPaceTab);
  }

  // ---------------- ZONES (target-area intel) ----------------
  // Renders data/zones_2026.js (pull_pace_tracker.py build_zones_2026):
  // defense funnel + pts/tgt allowed by depth/side, receiver target mix.
  // INTEL ONLY - backtest_target_area.py graded the matchup multiplier flat
  // (LOYO +0.03%, 2/7 years) because per-zone defense efficiency does not
  // persist (r ~0); the funnel and the receiver profiles DO, so this tab
  // exists for start/sit + video reads. Nothing here touches projections.
  var ZN_DEPTH = [['bl', 'Behind LOS'], ['sh', 'Short 0-9'], ['in', 'Int 10-19'], ['dp', 'Deep 20+']];
  var ZN_SIDE = [['left', 'Left'], ['middle', 'Middle'], ['right', 'Right']];
  var ZN_K_DEF = 60, ZN_K_PLR = 40;
  function znLg(Z) {
    // league share + pts/tgt per zone: 2026 season-to-date, 2025 when empty
    var L = (Z.lg && Z.lg.N >= 500) ? Z.lg : Z.lgPrior;
    var out = { depth: {}, side: {} };
    ['depth', 'side'].forEach(function (k) {
      Object.keys(L[k]).forEach(function (z) {
        var c = L[k][z];
        out[k][z] = { share: c.n / L.N, rate: c.n ? c.p / c.n : 0 };
      });
    });
    return out;
  }
  function znDef(Z, team, lg) {
    // funnel share (shrunk toward 2025 own share, K=60 tgts) + efficiency
    // ratio (shrunk toward 1, K=60) per zone; null when no data at all
    var c = Z.def[team], p = Z.defPrior[team];
    if (!c && !p) return null;
    var out = { N: c ? c.N : 0, gms: c ? c.gms : 0, depth: {}, side: {} };
    ['depth', 'side'].forEach(function (k) {
      Object.keys(lg[k]).forEach(function (z) {
        var cn = c ? c[k][z].n : 0, cp = c ? c[k][z].p : 0, N = c ? c.N : 0;
        var ps = p && p.N ? p[k][z].n / p.N : lg[k][z].share;
        var share = N ? (N * (cn / N) + ZN_K_DEF * ps) / (N + ZN_K_DEF) : ps;
        var raw = cn ? (cp / cn) / lg[k][z].rate : 1;
        var eff = (cn * raw + ZN_K_DEF) / (cn + ZN_K_DEF);
        var pr = (p && p[k][z].n) ? (p[k][z].p / p[k][z].n) / lg[k][z].rate : null;
        out[k][z] = { share: share, cur: N ? cn / N : null, prior: ps, n: cn, eff: eff, rawEff: cn ? raw : null, priorEff: pr };
      });
    });
    return out;
  }
  function znPlayer(Z, nk, lg) {
    var c = Z.players[nk], p = Z.playersPrior[nk];
    if (!c && !p) return null;
    var out = { N: c ? c.N : 0, Np: p ? p.N : 0, depth: {}, side: {}, adot: null, adotPrior: p && p.N ? p.ay / p.N : null,
      ppt: c && c.N ? c.p / c.N : null, name: (c || p).name, pos: (c || p).pos, tm: (c || p).tm };
    var n = c ? c.N : 0;
    var ayc = c ? c.ay : 0, ayp = p ? p.ay : 0;
    out.adot = (n + (p ? p.N : 0)) ? (ayc + ayp * (ZN_K_PLR / Math.max(ZN_K_PLR, p ? p.N : 0)) * (p ? 1 : 0)) / (n + (p ? Math.min(ZN_K_PLR, p.N) : 0)) : null;
    ['depth', 'side'].forEach(function (k) {
      Object.keys(lg[k]).forEach(function (z) {
        var cv = n ? ((c[k][z] || 0) / n) : null;
        var pv = (p && p.N) ? ((p[k][z] || 0) / p.N) : lg[k][z].share;
        out[k][z] = cv == null ? pv : (n * cv + ZN_K_PLR * pv) / (n + ZN_K_PLR);
      });
    });
    return out;
  }
  function znPP(v) { return v == null ? '—' : (100 * v).toFixed(0) + '%'; }
  function znDelta(v, lgv, thr) {
    if (v == null) return '';
    var d = 100 * (v - lgv);
    var col = Math.abs(d) < thr ? 'var(--dim)' : (d > 0 ? 'var(--acc)' : '#f85149');
    return ' <span style="color:' + col + ';font-size:11px">' + (d >= 0 ? '+' : '') + d.toFixed(0) + '</span>';
  }
  function znEff(e, n) {
    if (e == null) return '<span class="dim">—</span>';
    var col = Math.abs(e - 1) < 0.10 ? 'var(--dim)' : (e > 1 ? '#f85149' : 'var(--acc)');
    return '<span style="color:' + col + '" title="pts/target allowed vs league in this zone, shrunk toward 1 (n=' + n + ' targets). NOISY - per-zone efficiency does not persist.">' + e.toFixed(2) + 'x</span>';
  }
  function znReads(pl, d, lg) {
    // one-line strengths / matchup callouts for videos
    var r = [];
    ZN_DEPTH.forEach(function (zz) {
      var z = zz[0], w = pl.depth[z], L = lg.depth[z].share;
      if (w >= L + 0.08) r.push(zz[1] + ' guy (' + znPP(w) + ' of targets, lg ' + znPP(L) + ')');
      else if (w <= L - 0.08 && L > 0.12 && pl.pos !== 'RB') r.push('rarely ' + zz[1].toLowerCase() + ' (' + znPP(w) + ')');
    });
    ZN_SIDE.forEach(function (zz) {
      var z = zz[0], w = pl.side[z], L = lg.side[z].share;
      if (w >= L + 0.10) r.push(zz[1].toLowerCase() + '-heavy (' + znPP(w) + ')');
    });
    if (d) {
      ZN_DEPTH.forEach(function (zz) {
        var z = zz[0], w = pl.depth[z], L = lg.depth[z].share, dz = d.depth[z];
        if (w >= L + 0.05 && dz.share >= L + 0.03) r.push('D funnels ' + zz[1].toLowerCase() + ' (' + znPP(dz.share) + ' of targets faced)');
        if (w >= L + 0.05 && dz.rawEff != null && dz.n >= 25 && dz.rawEff >= 1.2) r.push('D leaky ' + zz[1].toLowerCase() + ' so far (' + dz.rawEff.toFixed(2) + 'x, noisy)');
        if (w >= L + 0.05 && dz.rawEff != null && dz.n >= 25 && dz.rawEff <= 0.8) r.push('D stingy ' + zz[1].toLowerCase() + ' so far (' + dz.rawEff.toFixed(2) + 'x, noisy)');
      });
    }
    return r.join(' · ');
  }
  function znDefCard(Z, team, lg, title) {
    var d = znDef(Z, team, lg);
    if (!d) return '<h3>' + esc(title) + '</h3><p class="dim">No target data for ' + esc(team) + '.</p>';
    var html = '<h3>' + esc(title) + ' <span class="dim" style="font-weight:normal;font-size:12px">' + d.N + ' targets faced, ' + d.gms + ' gms</span></h3>' +
      '<table style="width:auto"><thead><tr><th class="l">Zone</th><th>Share faced</th><th>vs lg</th><th>2025 share</th><th>Pts/tgt allowed</th><th>2025</th></tr></thead><tbody>';
    ZN_DEPTH.concat([['__', null]]).concat(ZN_SIDE).forEach(function (zz) {
      if (!zz[1]) { html += '<tr><td colspan="6" style="padding:2px"></td></tr>'; return; }
      var k = zz[0].length === 2 ? 'depth' : 'side', z = zz[0], v = d[k][z], L = lg[k][z];
      html += '<tr><td class="l">' + zz[1] + '</td><td>' + znPP(v.share) + '</td><td>' + znDelta(v.share, L.share, 3) + ' <span class="dim" style="font-size:11px">(lg ' + znPP(L.share) + ')</span></td>' +
        '<td class="dim">' + znPP(v.prior) + '</td><td>' + znEff(v.rawEff != null ? v.eff : null, v.n) + '</td><td class="dim">' + (v.priorEff != null ? v.priorEff.toFixed(2) + 'x' : '—') + '</td></tr>';
    });
    return html + '</tbody></table>';
  }
  function znPlayerRows(Z, team, lg, posF, d) {
    var rows = [];
    var seen = {};
    state.players.list.forEach(function (p) {
      if (p.isDST || p.tm !== team || ['WR', 'TE', 'RB'].indexOf(p.pos) < 0) return;
      if (posF && p.pos !== posF) return;
      var pl = znPlayer(Z, p.norm, lg);
      if (!pl || (pl.N + pl.Np) < 10) return;
      seen[p.norm] = 1;
      rows.push({ p: p, pl: pl });
    });
    rows.sort(function (a, b) { return (b.pl.N * 10 + b.pl.Np) - (a.pl.N * 10 + a.pl.Np); });
    if (!rows.length) return '<p class="dim">No receivers with target data.</p>';
    var html = '<table><thead><tr><th class="l">Receiver</th><th>Pos</th><th>2026 tgts</th><th>2025</th><th>aDOT</th>' +
      ZN_DEPTH.map(function (z) { return '<th>' + z[1] + '</th>'; }).join('') +
      ZN_SIDE.map(function (z) { return '<th>' + z[1] + '</th>'; }).join('') + '<th class="l">Read</th></tr></thead><tbody>';
    rows.forEach(function (o) {
      var pl = o.pl;
      html += '<tr><td class="l"><b>' + esc(o.p.name) + '</b></td><td>' + o.p.pos + '</td><td>' + pl.N + '</td><td class="dim">' + pl.Np + '</td><td>' + (pl.adot != null ? pl.adot.toFixed(1) : '—') + '</td>' +
        ZN_DEPTH.map(function (z) { return '<td>' + znPP(pl.depth[z[0]]) + znDelta(pl.depth[z[0]], lg.depth[z[0]].share, 5) + '</td>'; }).join('') +
        ZN_SIDE.map(function (z) { return '<td>' + znPP(pl.side[z[0]]) + znDelta(pl.side[z[0]], lg.side[z[0]].share, 6) + '</td>'; }).join('') +
        '<td class="l" style="font-size:11px;white-space:normal;min-width:260px">' + esc(znReads(pl, d, lg)) + '</td></tr>';
    });
    return html + '</tbody></table>';
  }
  function renderZonesTab() {
    var Z = window.SIM_ZONES_2026;
    if (!Z || (!Z.lg && !Z.lgPrior)) { $('zn-note').textContent = 'No zone data — run pull_pace_tracker.py.'; return; }
    var lg = znLg(Z);
    var wkSel = $('zn-week'), gSel = $('zn-game');
    if (!wkSel.options.length) {
      for (var w = 1; w <= 18; w++) wkSel.add(new Option('Week ' + w, w));
      var cur = state.injuryWeek || ((Z.weeks && Z.weeks.length) ? Math.min(18, Z.weeks[Z.weeks.length - 1] + 1) : 1);
      wkSel.value = cur;
      wkSel.addEventListener('change', function () { state.znGame = ''; renderZonesTab(); });
      gSel.addEventListener('change', function () { state.znGame = gSel.value; renderZonesTab(); });
      $('zn-pos').addEventListener('change', renderZonesTab);
    }
    var wk = +wkSel.value;
    var games = (state.schedule.byWeek[wk] || []);
    gSel.innerHTML = '<option value="">All defenses</option>' + games.map(function (g) {
      return '<option value="' + g.key + '">' + g.away + ' @ ' + g.home + '</option>';
    }).join('');
    gSel.value = state.znGame || '';
    var posF = $('zn-pos').value;
    var nData = Z.weeks && Z.weeks.length ? 'weeks ' + Z.weeks[0] + '-' + Z.weeks[Z.weeks.length - 1] : 'no 2026 targets yet (2025 profiles shown)';
    $('zn-note').textContent = 'Updated ' + Z.updated + ' — 2026 ' + nData + '. League mix: ' +
      ZN_DEPTH.map(function (z) { return z[1] + ' ' + znPP(lg.depth[z[0]].share); }).join(' · ') + ' · ' +
      ZN_SIDE.map(function (z) { return z[1] + ' ' + znPP(lg.side[z[0]].share); }).join(' · ') + '. Intel only — does not move projections.';
    var g = null;
    games.forEach(function (x) { if (x.key === gSel.value) g = x; });
    if (g) {
      $('zn-body').innerHTML =
        '<div style="display:flex;gap:28px;flex-wrap:wrap;align-items:flex-start">' +
        '<div>' + znDefCard(Z, g.home, lg, g.home + ' defense (vs ' + g.away + ' receivers)') + '</div>' +
        '<div style="flex:1;min-width:520px">' + '<h3>' + esc(g.away) + ' receivers</h3>' + znPlayerRows(Z, g.away, lg, posF, znDef(Z, g.home, lg)) + '</div></div>' +
        '<div style="display:flex;gap:28px;flex-wrap:wrap;align-items:flex-start;margin-top:26px">' +
        '<div>' + znDefCard(Z, g.away, lg, g.away + ' defense (vs ' + g.home + ' receivers)') + '</div>' +
        '<div style="flex:1;min-width:520px">' + '<h3>' + esc(g.home) + ' receivers</h3>' + znPlayerRows(Z, g.home, lg, posF, znDef(Z, g.away, lg)) + '</div></div>' +
        (scS() ? '<h2 style="margin-top:30px">Scheme &amp; alignment (PFF)</h2>' + scMatchupBlock(scS(), g.home, g.away, posF) + scMatchupBlock(scS(), g.away, g.home, posF) : '') +
        '<p class="dim" style="font-size:11px">Share columns: green/red = 3+ points off the league share (defense funnel) or 5+/6+ (receiver mix). Pts/tgt allowed: red = leaky, green = stingy, ' +
        'shrunk toward 1.0x with a 60-target prior — treat as "so far"; the backtest found NO year-to-year or early-to-late persistence in per-zone efficiency. ' +
        'Receiver mixes are shrunk toward their 2025 profile (40-target prior) — those DO persist (deep share r .75, behind-LOS .88).</p>';
      return;
    }
    // league table: every defense, funnel by depth (+ middle share) and efficiency
    var ss = state.znSort = state.znSort || { key: 'team', dir: 'asc' };
    var teams = Object.keys(Z.def).length ? Object.keys(Z.def) : Object.keys(Z.defPrior);
    var rows = teams.map(function (t) { return { t: t, d: znDef(Z, t, lg) }; }).filter(function (o) { return o.d; });
    var COLS = [{ h: 'Defense', l: 1, k: 'team', dir: 'asc', get: function (o) { return o.t; } },
                { h: 'Tgts', k: 'N', get: function (o) { return o.d.N; } }];
    ZN_DEPTH.forEach(function (z) {
      COLS.push({ h: z[1] + ' share', k: 's_' + z[0], get: function (o) { return o.d.depth[z[0]].share; } });
      COLS.push({ h: z[1] + ' pts/tgt', k: 'e_' + z[0], get: function (o) { return o.d.depth[z[0]].eff; } });
    });
    ZN_SIDE.forEach(function (z) { COLS.push({ h: z[1] + ' share', k: 's_' + z[0], get: function (o) { return o.d.side[z[0]].share; } }); });
    var sorted = applySort(rows, COLS, ss);
    var html = '<table><thead>' + thRow(COLS, ss) + '</thead><tbody>';
    sorted.forEach(function (o) {
      html += '<tr><td class="l"><b>' + o.t + '</b></td><td>' + o.d.N + '</td>' +
        ZN_DEPTH.map(function (z) {
          var v = o.d.depth[z[0]];
          return '<td>' + znPP(v.share) + znDelta(v.share, lg.depth[z[0]].share, 3) + '</td><td>' + znEff(v.rawEff != null ? v.eff : null, v.n) + '</td>';
        }).join('') +
        ZN_SIDE.map(function (z) { var v = o.d.side[z[0]]; return '<td>' + znPP(v.share) + znDelta(v.share, lg.side[z[0]].share, 3) + '</td>'; }).join('') + '</tr>';
    });
    $('zn-body').innerHTML = html + '</tbody></table>' +
      '<p class="dim" style="font-size:11px">Pick a game above for the matchup view (defense zone card next to the opposing receivers\' target mixes with auto-generated reads). ' +
      'Shares = where opponents target this defense (season-to-date, shrunk toward its 2025 shares) vs league; pts/tgt = half-PPR receiving points allowed per target in that zone vs league, shrunk toward 1.0x. Click a header to sort.</p>' +
      (scS() ? scLeagueTable(scS()) : '') + scBacktestBlock();
    wireSort('zn-body', COLS, ss, renderZonesTab);
    if (scS()) wireSort('zn-scheme', [], state.scSort, renderZonesTab);
  }


  // ---------------- SCHEME (PFF Premium weekly facets -> build_scheme.py -> scheme_2026.js) ----------------
  // Jack 2026-09-15: "alignments and where each defense gets targeted or what type of
  // runs outside/inside zone etc ... maybe pff" -> "do it". INTEL ONLY: per-player
  // man/zone splits, per-zone and per-lane defense efficiency all graded as noise in
  // the LOYO backtests (README), so nothing here touches a projection. What IS shown:
  // what a defense does (man rate, blitz, pressure, safety-in-box, lanes it gets run
  // at, run D results) and what a player does (man/zone YPRR, slot share, gap vs
  // zone, lanes, yards after contact, QB under pressure / vs blitz).
  function scS() { var S = window.SIM_SCHEME_2026; return (S && S.def && Object.keys(S.def).length) ? S : null; }
  function scPct(v, d) { return v == null ? '\u2014' : (100 * v).toFixed(d == null ? 0 : d) + '%'; }
  function scNum(v, d) { return v == null ? '\u2014' : (+v).toFixed(d == null ? 1 : d); }
  function scGet(d, key, sub) { if (!d) return null; var v = sub ? (d[sub] ? d[sub][key] : null) : d[key]; return v == null ? null : v; }
  function scRank(S, key, sub, val) {
    // 1 = highest value league-wide (32 defenses); null when val missing
    if (val == null) return null;
    var vals = [];
    Object.keys(S.def).forEach(function (t) { var v = scGet(S.def[t], key, sub); if (v != null) vals.push(v); });
    vals.sort(function (a, b) { return b - a; });
    return { r: vals.indexOf(val) + 1, n: vals.length };
  }
  function scDelta(v, lg, pct, thr) {
    // colored difference vs league (pct = percentage points, else raw units)
    if (v == null || lg == null) return '';
    var d = pct ? 100 * (v - lg) : v - lg;
    var col = Math.abs(d) < thr ? 'var(--dim)' : (d > 0 ? 'var(--acc)' : '#f85149');
    return ' <span style="color:' + col + ';font-size:11px">' + (d >= 0 ? '+' : '') + d.toFixed(pct ? 0 : 1) + '</span>';
  }
  // [key, label, sub, pct?, threshold for color, tooltip]
  var SC_DEF_ROWS = [
    ['man', 'Man coverage', null, 1, 5, 'share of coverage snaps in man coverage (PFF charting); lg ~25%'],
    ['blitz', 'Blitz rate', null, 1, 5, 'share of opponent dropbacks with a blitz (PFF, from the QBs this defense faced)'],
    ['prs', 'Pressure rate', null, 1, 5, 'share of opponent dropbacks pressured (PFF)'],
    ['prwr', 'Rusher win rate', null, 1, 2, 'pass-rush wins / pass-rush opportunities summed over the whole front'],
    ['sBox', 'Safety in box', null, 1, 6, 'share of safety snaps aligned in the box (run-stopping / heavy looks)'],
    ['mtRate', 'Missed-tackle rate', null, 1, 3, 'missed tackles / (tackles + assists + missed)'],
    ['ypc', 'Run D: yds/carry', 'run', 0, 0.5, 'yards per carry allowed to RB/WR/FB carries (QB runs excluded)'],
    ['yco', 'Run D: after contact/att', 'run', 0, 0.4, 'yards after contact per carry allowed'],
    ['gap', 'Gap runs faced', 'run', 1, 8, 'share of carries against this defense that were gap/power scheme (rest zone)'],
    ['edge', 'Edge runs faced', 'run', 1, 8, 'share of carries against this defense to LE/RE (incl. jet sweeps / end-arounds)'],
    ['exp', 'Explosive run % allowed', 'run', 1, 4, 'PFF explosive carries (10+ yds) / carries faced'],
    ['mtf', 'Missed tackles forced/att', 'run', 0, 0.06, 'avoided tackles by the backs it faced, per carry'],
    ['slotYd', 'Slot share of rec yds', null, 1, 8, 'share of receiving yards allowed that came on slot routes'],
    ['grCov', 'PFF coverage grade', null, 0, 5, 'snap-weighted coverage grade'],
    ['grRun', 'PFF run-D grade', null, 0, 5, 'snap-weighted run-defense grade'],
    ['grPrsh', 'PFF pass-rush grade', null, 0, 5, 'snap-weighted pass-rush grade']
  ];
  var SC_LANES = ['LE', 'LT', 'LG', 'ML', 'MR', 'RG', 'RT', 'RE'];
  function scLaneMix(lanes) {
    if (!lanes) return null;
    var n = 0; SC_LANES.forEach(function (l) { n += (lanes[l] || [0, 0])[0]; });
    if (!n) return null;
    var out = { n: n, share: {}, ypc: {} };
    SC_LANES.forEach(function (l) { var v = lanes[l] || [0, 0]; out.share[l] = v[0] / n; out.ypc[l] = v[0] ? v[1] / v[0] : null; });
    return out;
  }
  function scLaneLine(lanes, lgShare, lgYpc, withYpc) {
    var m = scLaneMix(lanes); if (!m) return '';
    return SC_LANES.map(function (l) {
      var s = m.share[l], L = lgShare ? lgShare[l] : null;
      var col = (L != null && Math.abs(s - L) >= 0.06) ? (s > L ? 'var(--acc)' : '#f85149') : 'inherit';
      return '<span style="color:' + col + '" title="' + l + ': ' + (100 * s).toFixed(0) + '% of carries' + (L != null ? ' (lg ' + (100 * L).toFixed(0) + '%)' : '') +
        (withYpc && m.ypc[l] != null ? ', ' + m.ypc[l].toFixed(1) + ' yds/att' + (lgYpc && lgYpc[l] != null ? ' (lg ' + lgYpc[l].toFixed(1) + ')' : '') : '') + '">' +
        l + ' ' + (100 * s).toFixed(0) + '%' + (withYpc && m.ypc[l] != null ? ' <span class="dim">(' + m.ypc[l].toFixed(1) + ')</span>' : '') + '</span>';
    }).join(' \u00b7 ') + ' <span class="dim">(' + m.n + ' carries' + (withYpc ? ', yds/att in parens' : '') + ')</span>';
  }
  // ---- prior season (Jack 2026-09-15: "see if there are any similarities to week 1 because
  // then that team defense or offensive players will be somewhat reliable") ----
  var SC_IDENTITY = ['man', 'blitz', 'dbRush', 'sBox', 'prwr', 'run.gap', 'run.edge', 'run.mtf'];   // scheme choices, not results
  function scPrior(S, team) { return S.defPrior ? S.defPrior[team] : null; }
  // ---- coaches / playcallers (build_scheme.py <- pbp_cache/coaches.json via pull_coaches.py, PFR) ----
  // Jack 2026-09-15: "make sure we are aware of coaches and playcallers ... assign tendencies".
  // The prior a card compares against travels with the PLAYCALLER: same DC -> the team's
  // prior season; new DC -> his last defense (priorSrc says where from); no history -> team
  // prior flagged weak. coachHist = every season each playcaller has in the data.
  function scCoach(S, team) { return S.coaches ? S.coaches[team] : null; }
  function scSrc(S, team, kind) { return S.priorSrc && S.priorSrc[team] ? S.priorSrc[team][kind || 'def'] : null; }
  function scYearsIn(S, team, kind) {
    // consecutive seasons the current playcaller has been in this seat here (1 = first year)
    var c = scCoach(S, team); if (!c) return null;
    var H = S.coachHist && S.coachHist[kind || 'def'], who = c[kind === 'off' ? 'ocPlay' : 'dcPlay']; if (!H || !who || !H[who]) return 1;
    var n = 1, y = S.season - 1;
    var seasons = {}; H[who].forEach(function (h) { seasons[h.season] = h.team; });
    while (seasons[y] === team) { n++; y--; }
    return n;
  }
  function scCoachLine(S, team, kind) {
    // "DC Christian Parker (new; prior = DEN 2025 under Parker)" / "DC Brian Flores (4th yr)"
    var c = scCoach(S, team); if (!c) return '';
    var who = c[kind === 'off' ? 'ocPlay' : 'dcPlay']; if (!who) return '';
    var hc = c.hc && who === c.hc ? 'HC ' : (kind === 'off' ? 'OC ' : 'DC ');
    var src = scSrc(S, team, kind), yrs = scYearsIn(S, team, kind);
    var ord = function (n) { return n === 1 ? '1st' : n === 2 ? '2nd' : n === 3 ? '3rd' : n + 'th'; };
    var out = hc + who;
    if (!src || src.mode === 'same') out += ' (' + ord(yrs || 1) + ' yr here)';
    else if (src.mode === 'coach') out += ' (new; prior = ' + src.from + ' ' + src.season + ' under him' + (src.prev ? ', replaced ' + src.prev : '') + ')';
    else if (src.mode === 'new-no-history') out += ' (new, no playcalling history in the data' + (src.prev ? '; replaced ' + src.prev : '') + ' \u2014 prior = team ' + src.season + ', weak)';
    return out;
  }
  function scCoachHist(S, team, kind) {
    // tendency line across the playcaller's seasons: "Flores: blitz 45%/41%/48%, man 38%/35%/30% (2023 MIN, 2024 MIN, 2025 MIN)"
    var c = scCoach(S, team); if (!c) return '';
    var H = S.coachHist && S.coachHist[kind || 'def'], who = c[kind === 'off' ? 'ocPlay' : 'dcPlay']; if (!H || !who || !H[who] || H[who].length < 1) return '';
    var rows = H[who].filter(function (h) { return h.season < S.season; }).sort(function (a, b) { return a.season - b.season; });
    if (!rows.length) return '';
    var m = kind === 'off' ? [['manSeen', 'sees man'], ['screen', 'screens'], ['run.gap', 'gap runs'], ['run.edge', 'edge runs']]
                           : [['man', 'man'], ['blitz', 'blitz'], ['prs', 'pressure'], ['sBox', 'S in box'], ['run.gap', 'gap faced'], ['run.edge', 'edge faced']];
    var parts = m.map(function (mm) {
      var vals = rows.map(function (h) { var v = mm[0].indexOf('run.') === 0 ? (h.run ? h.run[mm[0].slice(4)] : null) : h[mm[0]]; return v == null ? '\u2014' : (100 * v).toFixed(0) + '%'; });
      return mm[1] + ' ' + vals.join('/');
    });
    return who + ' as playcaller: ' + parts.join(' \u00b7 ') + ' (' + rows.map(function (h) { return h.season + ' ' + h.team; }).join(', ') + ')';
  }
  function scLgOf(S, key, sub, prior) { var L = prior ? S.lgPrior : S.lg; if (!L) return null; return sub ? (L[sub] ? L[sub][key] : null) : L[key]; }
  function scAgree(v, p, lg, lgp, pct, thr) {
    // both on the same side of the league by >= thr -> 1 (match), opposite sides -> -1, else 0 (neither leans / mixed)
    if (v == null || p == null || lg == null || lgp == null) return null;
    var a = pct ? 100 * (v - lg) : v - lg, b = pct ? 100 * (p - lgp) : p - lgp;
    var la = Math.abs(a) >= thr ? (a > 0 ? 1 : -1) : 0, lb = Math.abs(b) >= thr ? (b > 0 ? 1 : -1) : 0;
    if (la && lb) return la === lb ? 1 : -1;
    if (!la && !lb) return 1;
    return 0;
  }
  function scPersist(S, key, sub) { var P = S.persist && S.persist[(sub ? sub + '.' : '') + key]; return P && P.r != null ? P.r : null; }
  function scPersistTag(r) {
    if (r == null) return '';
    var col = r >= 0.3 ? 'var(--acc)' : (r >= 0.15 ? 'var(--dim)' : '#f85149');
    return ' <span style="color:' + col + ';font-size:10px" title="league-wide correlation of this metric, 2026 to date vs 2025 full season (32 defenses); >= .30 = a real identity you can quote, ~0 = noise so far">r ' + r.toFixed(2) + '</span>';
  }
  function scReliability(S, team) {
    // how many identity metrics keep their 2025 lean -> RELIABLE / MIXED / NEW LOOK
    var d = S.def[team], p = scPrior(S, team); if (!d || !p) return null;
    var n = 0, ok = 0, flips = [];
    SC_DEF_ROWS.forEach(function (r) {
      var id = (r[2] ? r[2] + '.' : '') + r[0]; if (SC_IDENTITY.indexOf(id) < 0) return;
      var a = scAgree(scGet(d, r[0], r[2]), scGet(p, r[0], r[2]), scLgOf(S, r[0], r[2], false), scLgOf(S, r[0], r[2], true), r[3], r[4]);
      if (a == null) return; n++; if (a === 1) ok++; else if (a === -1) flips.push(r[1]);
    });
    if (!n) return null;
    var f = ok / n;
    return { n: n, ok: ok, flips: flips, label: f >= 0.7 ? 'RELIABLE' : (f <= 0.4 ? 'NEW LOOK' : 'MIXED'), col: f >= 0.7 ? 'var(--acc)' : (f <= 0.4 ? '#f85149' : 'var(--dim)') };
  }
  function scBlendRec(cur, pri, K) {
    // season-to-date counts + prior season scaled so the prior never outweighs K routes
    if (!cur && !pri) return null;
    var out = {}; var keys = ['mR', 'zR', 'mT', 'zT', 'mY', 'zY', 'mRec', 'zRec', 'mTd', 'zTd', 'sl', 'wd', 'il', 'scT', 'scY', 'slT', 'slY'];
    var pr = pri ? (pri.mR + pri.zR) : 0, f = pr ? Math.min(1, K / pr) : 0;
    keys.forEach(function (k) { out[k] = ((cur && cur[k]) || 0) + ((pri && pri[k]) || 0) * f; });
    out.tm = (cur || pri).tm; out.pos = (cur || pri).pos; out.g = cur ? cur.g : 0; out.gPrior = pri ? pri.g : 0;
    return out;
  }
  function scBlendRb(cur, pri, K) {
    if (!cur && !pri) return null;
    var out = {}; var keys = ['att', 'yds', 'gap', 'zone', 'yco', 'exp', 'mtf', 'brkY'];
    var f = pri && pri.att ? Math.min(1, K / pri.att) : 0;
    keys.forEach(function (k) { out[k] = ((cur && cur[k]) || 0) + ((pri && pri[k]) || 0) * f; });
    out.lanes = {};
    SC_LANES.forEach(function (l) { var c = cur && cur.lanes ? cur.lanes[l] || [0, 0] : [0, 0], p = pri && pri.lanes ? pri.lanes[l] || [0, 0] : [0, 0]; out.lanes[l] = [c[0] + p[0] * f, c[1] + p[1] * f]; });
    out.elu = cur && cur.elu != null ? cur.elu : (pri ? pri.elu : null);
    out.tm = (cur || pri).tm; out.pos = (cur || pri).pos; out.g = cur ? cur.g : 0; out.gPrior = pri ? pri.g : 0;
    return out;
  }
  function scBlendQb(cur, pri, K) {
    if (!cur && !pri) return null;
    var out = {}; var keys = ['db', 'bDb', 'pDb', 'pAtt', 'pY', 'pTd', 'pInt', 'pSk', 'pTwp', 'nAtt', 'nY', 'nTd', 'nInt', 'bAtt', 'bY', 'bTd', 'nbAtt', 'nbY', 'nbTd'];
    var f = pri && pri.db ? Math.min(1, K / pri.db) : 0;
    keys.forEach(function (k) { out[k] = ((cur && cur[k]) || 0) + ((pri && pri[k]) || 0) * f; });
    ['pGr', 'nGr', 'bGr', 'nbGr'].forEach(function (k) {
      var wc = cur ? (k === 'pGr' ? cur.pDb : k === 'nGr' ? cur.db - cur.pDb : k === 'bGr' ? cur.bDb : cur.db - cur.bDb) : 0;
      var wp = pri ? (k === 'pGr' ? pri.pDb : k === 'nGr' ? pri.db - pri.pDb : k === 'bGr' ? pri.bDb : pri.db - pri.bDb) * f : 0;
      var vc = cur && cur[k] != null ? cur[k] : null, vp = pri && pri[k] != null ? pri[k] : null;
      out[k] = (vc != null && vp != null && wc + wp) ? (vc * wc + vp * wp) / (wc + wp) : (vc != null ? vc : vp);
    });
    out.p2s = out.pDb ? out.pSk / out.pDb : null;
    out.tm = (cur || pri).tm; out.g = cur ? cur.g : 0; out.gPrior = pri ? pri.g : 0;
    return out;
  }
  function scDefCard(S, team, title) {
    var d = S.def[team];
    if (!d) return '<h3>' + esc(title) + '</h3><p class="dim">No PFF scheme data for ' + esc(team) + '.</p>';
    var p = scPrior(S, team), rel = scReliability(S, team), src = scSrc(S, team, 'def');
    var priorLabel = src && src.mode === 'coach' ? src.from + ' ' + src.season : String(S.prior || 2025);
    var html = '<h3>' + esc(title) + ' <span class="dim" style="font-weight:normal;font-size:12px">' + d.g + ' gm' + (d.g > 1 ? 's' : '') + ', PFF</span>' +
      (rel ? ' <span style="font-size:12px;color:' + rel.col + '" title="identity metrics (man, blitz, DB/LB rush, S in box, rusher win, gap/edge/MTF faced) that keep their prior lean vs the league; prior = ' + esc(priorLabel) + (src && src.coach ? ' under ' + esc(src.coach) : '') + (rel.flips.length ? '; flipped: ' + esc(rel.flips.join(', ')) : '') + '">' + rel.label + ' vs ' + esc(priorLabel) + ' (' + rel.ok + '/' + rel.n + ')</span>' : '') + '</h3>' +
      (scCoach(S, team) ? '<div style="font-size:12px;margin:-2px 0 6px">' + esc(scCoachLine(S, team, 'def')) + (src && src.weak ? ' <span style="color:#f85149">weak prior</span>' : '') + '</div>' : '') +
      '<table style="width:auto"><thead><tr><th class="l">Metric</th><th>Value</th><th>vs lg</th><th>Rank</th>' + (p ? '<th title="prior season for THIS playcaller: ' + esc(priorLabel) + (src && src.coach ? ' under ' + esc(src.coach) : '') + '">' + esc(priorLabel) + '</th><th title="same lean vs the league as the prior? check = yes, arrows = flipped, ~ = one side neutral">vs prior</th>' : '') + '</tr></thead><tbody>';
    SC_DEF_ROWS.forEach(function (r) {
      var v = scGet(d, r[0], r[2]); if (v == null) return;
      var lg = scLgOf(S, r[0], r[2], false), fmt = function (x) { return r[3] ? scPct(x) : scNum(x, r[0].indexOf('gr') === 0 ? 1 : 2); };
      var rk = scRank(S, r[0], r[2], v);
      var pv = p ? scGet(p, r[0], r[2]) : null, ag = p ? scAgree(v, pv, lg, scLgOf(S, r[0], r[2], true), r[3], r[4]) : null;
      html += '<tr title="' + esc(r[5]) + '"><td class="l">' + r[1] + scPersistTag(scPersist(S, r[0], r[2])) + '</td><td><b>' + fmt(v) + '</b></td>' +
        '<td>' + scDelta(v, lg, r[3], r[4]) + ' <span class="dim" style="font-size:11px">(lg ' + fmt(lg) + ')</span></td>' +
        '<td class="dim">' + (rk ? '#' + rk.r + '/' + rk.n : '\u2014') + '</td>' +
        (p ? '<td class="dim">' + (pv != null ? fmt(pv) + scDelta(pv, scLgOf(S, r[0], r[2], true), r[3], r[4]) : '\u2014') + '</td><td>' +
          (ag == null ? '<span class="dim">\u2014</span>' : ag === 1 ? '<span style="color:var(--acc)">\u2713</span>' : ag === -1 ? '<span style="color:#f85149">\u2195 flip</span>' : '<span class="dim">~</span>') + '</td>' : '') + '</tr>';
    });
    html += '</tbody></table>';
    if (d.run && d.run.lanes) html += '<div style="font-size:12px;margin-top:6px"><b>Gets run at:</b> ' + scLaneLine(d.run.lanes, S.lg.lanes, S.lg.laneYpc, true) + '</div>';
    if (p && p.run && p.run.lanes) html += '<div style="font-size:11px;margin-top:3px" class="dim"><b>' + esc(priorLabel) + ':</b> ' + scLaneLine(p.run.lanes, S.lgPrior ? S.lgPrior.lanes : null, null, false) + '</div>';
    var ch = scCoachHist(S, team, 'def');
    if (ch) html += '<div style="font-size:11px;margin-top:4px" class="dim"><b>Tendencies:</b> ' + esc(ch) + '</div>';
    return html;
  }
  // ---- player profiles ----
  var SC_K_REC = 200, SC_K_RB = 100, SC_K_QB = 200;   // prior-season cap (routes / carries / dropbacks) in the blend
  function scRecOf(r) {
    if (!r) return null;
    var R = r.mR + r.zR, al = (r.sl || 0) + (r.wd || 0) + (r.il || 0), T = r.mT + r.zT;
    return { raw: r, routes: R, manSeen: R ? r.mR / R : null, mTgR: r.mR ? r.mT / r.mR : null, zTgR: r.zR ? r.zT / r.zR : null,
      mYprr: r.mR ? r.mY / r.mR : null, zYprr: r.zR ? r.zY / r.zR : null, slot: al ? r.sl / al : null, inline: al ? r.il / al : null,
      screen: T && r.scT != null ? r.scT / T : null, tg: T };
  }
  function scRec(S, nk) {
    var c = S.rec[nk], p = S.recPrior ? S.recPrior[nk] : null; if (!c && !p) return null;
    var o = scRecOf(scBlendRec(c, p, SC_K_REC)); o.cur = scRecOf(c); o.pri = scRecOf(p); return o;
  }
  function scRbOf(r) {
    if (!r) return null;
    var gz = r.gap + r.zone, m = scLaneMix(r.lanes);
    return { raw: r, att: r.att, ypc: r.att ? r.yds / r.att : null, gap: gz ? r.gap / gz : null, yco: r.att ? r.yco / r.att : null,
      exp: r.att ? r.exp / r.att : null, mtf: r.att ? r.mtf / r.att : null, brk: r.yds ? r.brkY / r.yds : null,
      edge: m ? m.share.LE + m.share.RE : null, lanes: m, elu: r.elu };
  }
  function scRb(S, nk) {
    var c = S.rb[nk], p = S.rbPrior ? S.rbPrior[nk] : null; if (!c && !p) return null;
    var o = scRbOf(scBlendRb(c, p, SC_K_RB)); o.cur = scRbOf(c); o.pri = scRbOf(p); return o;
  }
  function scQbOf(q) {
    if (!q) return null;
    return { raw: q, db: q.db, blitz: q.db ? q.bDb / q.db : null, prs: q.db ? q.pDb / q.db : null,
      pYpa: q.pAtt ? q.pY / q.pAtt : null, nYpa: q.nAtt ? q.nY / q.nAtt : null, bYpa: q.bAtt ? q.bY / q.bAtt : null, nbYpa: q.nbAtt ? q.nbY / q.nbAtt : null,
      pGr: q.pGr, nGr: q.nGr, bGr: q.bGr, nbGr: q.nbGr, p2s: q.p2s };
  }
  function scQb(S, nk) {
    var c = S.qb[nk], p = S.qbPrior ? S.qbPrior[nk] : null; if (!c && !p) return null;
    var o = scQbOf(scBlendQb(c, p, SC_K_QB)); o.cur = scQbOf(c); o.pri = scQbOf(p); return o;
  }
  function scPriTag(cur, pri, test) {
    // '(2025 too)' when last season alone also qualifies, '(new)' when it had enough volume and did not
    if (!pri) return '';
    return test(pri) ? ' (2025 too)' : (test(pri, true) ? ' (new vs 2025)' : '');
  }
  function scReads(S, p, prof, D) {
    // strengths / weaknesses + matchup callouts for videos; D = opposing defense entry
    var r = [], lg = S.lg, L = lg.rec || {}, LR = lg.run || {}, LQ = lg.qb || {};
    var dman = scGet(D, 'man'), dbl = scGet(D, 'blitz'), dprs = scGet(D, 'prs');
    if (p.pos === 'QB') {
      var q = prof; if (!q || q.db < 20) return '';
      if (q.pGr != null && q.nGr != null) {
        var ptag = scPriTag(q.cur, q.pri, function (p, vol) { if (!p || p.db < 150 || p.pGr == null || p.nGr == null) return false; if (vol) return true; return (q.nGr - q.pGr >= 35) ? (p.nGr - p.pGr >= 28) : (p.nGr - p.pGr <= 18); });
        if (q.nGr - q.pGr >= 35) r.push('falls apart under pressure (grade ' + scNum(q.pGr, 0) + ' vs ' + scNum(q.nGr, 0) + ' clean)' + ptag);
        else if (q.nGr - q.pGr <= 12) r.push('holds up under pressure (grade ' + scNum(q.pGr, 0) + ' vs ' + scNum(q.nGr, 0) + ' clean)' + ptag);
      }
      if (q.bYpa != null && q.nbYpa != null && q.raw.bAtt >= 10) {
        if (q.bYpa >= q.nbYpa + 1.5) r.push('punishes the blitz (' + scNum(q.bYpa) + ' YPA vs ' + scNum(q.nbYpa) + ' no blitz)');
        else if (q.bYpa <= q.nbYpa - 1.5) r.push('struggles vs blitz (' + scNum(q.bYpa) + ' YPA vs ' + scNum(q.nbYpa) + ')');
      }
      if (q.p2s != null && q.raw.pDb >= 15 && q.p2s >= 0.26) r.push('pressure-to-sack ' + scPct(q.p2s) + ' (takes sacks)');
      if (D) {
        if (dbl != null && lg.blitz != null && dbl >= lg.blitz + 0.08) r.push('D blitzes ' + scPct(dbl) + ' (#' + scRank(S, 'blitz', null, dbl).r + ')' + (q.bYpa != null && q.nbYpa != null && q.raw.bAtt >= 10 ? (q.bYpa >= q.nbYpa + 1 ? ' \u2014 GOOD SPOT' : q.bYpa <= q.nbYpa - 1 ? ' \u2014 TOUGH SPOT' : '') : ''));
        if (dprs != null && lg.prs != null && dprs >= lg.prs + 0.06) r.push('D pressure ' + scPct(dprs) + ' (#' + scRank(S, 'prs', null, dprs).r + ')' + (q.pGr != null && q.nGr != null && q.nGr - q.pGr >= 35 ? ' \u2014 TOUGH SPOT' : ''));
        else if (dprs != null && lg.prs != null && dprs <= lg.prs - 0.08) r.push('D pressure only ' + scPct(dprs) + ' (clean pockets)');
        if (dman != null && lg.man != null && dman >= lg.man + 0.10) r.push('D plays man ' + scPct(dman) + ' (#' + scRank(S, 'man', null, dman).r + ')');
      }
      return r.join(' \u00b7 ');
    }
    if (p.pos === 'RB' && prof && prof.rb && prof.rb.att >= 8) {
      var b = prof.rb;
      if (b.gap != null && LR.gap != null) {
        var gtag = scPriTag(b.cur, b.pri, function (p, vol) { if (!p || p.att < 40) return false; if (vol) return true; return b.gap >= 0.62 ? p.gap >= 0.55 : p.gap <= 0.38; });
        if (b.gap >= 0.62) r.push('gap/power back (' + scPct(b.gap) + ' gap)' + gtag); else if (b.gap <= 0.30) r.push('zone-scheme back (' + scPct(1 - b.gap) + ' zone)' + gtag);
      }
      if (b.edge != null && LR.edge != null) { if (b.edge >= LR.edge + 0.12) r.push('bounces outside (edge ' + scPct(b.edge) + ', lg ' + scPct(LR.edge) + ')'); else if (b.edge <= LR.edge - 0.15) r.push('between the tackles (edge ' + scPct(b.edge) + ')'); }
      if (b.yco != null && LR.yco != null && b.att >= 15) { if (b.yco >= LR.yco + 0.7) r.push('contact-balance back (' + scNum(b.yco, 2) + ' after contact/att, lg ' + scNum(LR.yco, 2) + ')'); else if (b.yco <= LR.yco - 0.7) r.push('needs a lane (' + scNum(b.yco, 2) + ' after contact/att)'); }
      if (b.mtf != null && LR.mtf != null && b.att >= 15 && b.mtf >= LR.mtf + 0.08) r.push('makes people miss (' + scNum(b.mtf, 2) + ' MTF/att)');
      if (D && D.run) {
        var dr = D.run, dm = scLaneMix(dr.lanes);
        if (dr.yco != null && LR.yco != null && dr.att >= 40 && dr.yco >= LR.yco + 0.5) r.push('D allows ' + scNum(dr.yco, 2) + ' after contact/att (lg ' + scNum(LR.yco, 2) + ', noisy)');
        if (dr.ypc != null && LR.ypc != null && dr.att >= 40) { if (dr.ypc >= LR.ypc + 0.7) r.push('D leaky vs run so far (' + scNum(dr.ypc, 1) + ' ypc)'); else if (dr.ypc <= LR.ypc - 0.7) r.push('D stingy vs run so far (' + scNum(dr.ypc, 1) + ' ypc)'); }
        if (b.edge != null && LR.edge != null && b.edge >= LR.edge + 0.08 && dm && dm.n >= 40) {
          var eY = ((dr.lanes.LE || [0, 0])[1] + (dr.lanes.RE || [0, 0])[1]) / Math.max(1, (dr.lanes.LE || [0, 0])[0] + (dr.lanes.RE || [0, 0])[0]);
          var lgE = (lg.laneYpc && lg.laneYpc.LE != null && lg.laneYpc.RE != null) ? (lg.laneYpc.LE + lg.laneYpc.RE) / 2 : null;
          if (lgE != null) r.push('D on edge runs: ' + scNum(eY, 1) + ' yds/att (lg ' + scNum(lgE, 1) + ', noisy)');
        }
        if (scGet(D, 'mtRate') != null && lg.mtRate != null && scGet(D, 'mtRate') >= lg.mtRate + 0.03 && b.mtf != null && LR.mtf != null && b.mtf >= LR.mtf + 0.05) r.push('D misses tackles (' + scPct(scGet(D, 'mtRate')) + ') \u2014 GOOD SPOT');
        if (scGet(D, 'sBox') != null && lg.sBox != null && scGet(D, 'sBox') >= lg.sBox + 0.10) r.push('D lives in heavy boxes (S in box ' + scPct(scGet(D, 'sBox')) + ')');
      }
    }
    var w = prof && prof.rec;
    if (w && w.routes >= 25) {
      if (w.slot != null) { if (w.slot >= 0.65 && p.pos !== 'RB') r.push('slot (' + scPct(w.slot) + ')'); else if (p.pos === 'WR' && w.slot <= 0.12) r.push('outside only (' + scPct(w.slot) + ' slot)'); if (p.pos === 'TE' && w.inline != null && w.inline <= 0.35) r.push('detached TE (' + scPct(w.inline) + ' inline)'); }
      if (w.screen != null && w.tg >= 8 && w.screen >= 0.25) r.push('screen guy (' + scPct(w.screen) + ' of targets)');
      var manOK = w.raw.mR >= 15 && w.raw.zR >= 15;
      var beater = null;
      if (manOK && w.mYprr != null && w.zYprr != null) {
        if (w.mYprr >= w.zYprr * 1.35 && w.mYprr >= (L.mYprr || 1.5)) beater = 'man';
        else if (w.zYprr >= w.mYprr * 1.35 && w.zYprr >= (L.zYprr || 1.5)) beater = 'zone';
        if (beater) r.push(beater + '-beater (YPRR ' + scNum(w.mYprr, 2) + ' vs man, ' + scNum(w.zYprr, 2) + ' vs zone' + (w.cur && w.cur.routes < 100 ? '; small n' : '') + ')' +
          scPriTag(w.cur, w.pri, function (p, vol) { if (!p || p.raw.mR < 40 || p.raw.zR < 40) return false; if (vol) return true;
            return beater === 'man' ? (p.mYprr >= p.zYprr * 1.25) : (p.zYprr >= p.mYprr * 1.25); }));
      }
      if (D && dman != null && lg.man != null) {
        if (dman >= lg.man + 0.10) r.push('D plays man ' + scPct(dman) + ' (#' + scRank(S, 'man', null, dman).r + ')' + (beater === 'man' ? ' \u2014 GOOD SPOT' : beater === 'zone' ? ' \u2014 TOUGH SPOT' : ''));
        else if (dman <= lg.man - 0.10) r.push('D zone-heavy (man ' + scPct(dman) + ')' + (beater === 'zone' ? ' \u2014 GOOD SPOT' : beater === 'man' ? ' \u2014 TOUGH SPOT' : ''));
      }
      if (D && w.slot != null && w.slot >= 0.55 && scGet(D, 'slotYd') != null && lg.slotYd != null && scGet(D, 'slotYd') >= lg.slotYd + 0.10) r.push('D bleeds slot yards (' + scPct(scGet(D, 'slotYd')) + ' of rec yds, lg ' + scPct(lg.slotYd) + ', noisy)');
    }
    return r.join(' \u00b7 ');
  }
  function scProfile(S, p) {
    var prof = { rec: null, rb: null, qb: null };
    if (p.pos === 'QB') prof.qb = scQb(S, p.norm);
    else { prof.rec = scRec(S, p.norm); if (p.pos === 'RB') prof.rb = scRb(S, p.norm); }
    if (!prof.rec && !prof.rb && !prof.qb) return null;
    return prof;
  }
  function scRead(S, p, D) {
    var prof = scProfile(S, p); if (!prof) return '';
    return scReads(S, p, p.pos === 'QB' ? prof.qb : prof, D);
  }
  function scPlayerRows(S, team, posF, D) {
    var L = S.lg.rec || {}, LR = S.lg.run || {}, LQ = S.lg.qb || {};
    var rows = [];
    state.players.list.forEach(function (p) {
      if (p.isDST || p.tm !== team || ['QB', 'RB', 'WR', 'TE'].indexOf(p.pos) < 0) return;
      if (posF && p.pos !== posF && p.pos !== 'QB') return;
      var prof = scProfile(S, p); if (!prof) return;
      var vol = prof.qb ? prof.qb.db : ((prof.rec ? prof.rec.routes : 0) + (prof.rb ? prof.rb.att * 2 : 0));
      if (vol < 10) return;
      rows.push({ p: p, prof: prof, vol: vol });
    });
    rows.sort(function (a, b) { return (a.p.pos === 'QB' ? 1 : 0) - (b.p.pos === 'QB' ? 1 : 0) || b.vol - a.vol; });
    if (!rows.length) return '<p class="dim">No PFF profiles for ' + esc(team) + ' yet.</p>';
    var html = '<table><thead><tr><th class="l">Player</th><th>Pos</th><th title="routes run (WR/TE/RB) or dropbacks (QB): 2026 to date + 2025 scaled to at most 200 routes / 100 carries / 200 dropbacks (the blend every column uses); parens = 2026 only">Vol</th>' +
      '<th title="WR/TE/RB: share of routes vs man coverage. QB: share of dropbacks blitzed">Man seen / Blitz%</th>' +
      '<th title="WR/TE/RB: yards per route run vs man | vs zone. RB: gap-scheme carry share. QB: pressure rate faced">YPRR man | zone / Gap% / Prs%</th>' +
      '<th title="WR/TE/RB: slot share of alignment snaps. RB: edge (LE+RE) carry share. QB: PFF pass grade under pressure | clean">Slot% / Edge% / Grade prs | clean</th>' +
      '<th title="WR/TE/RB: screen share of targets. RB: yards after contact per att. QB: YPA vs blitz | no blitz">Screen% / YCO / YPA blitz | none</th>' +
      '<th class="l">Read</th></tr></thead><tbody>';
    rows.forEach(function (o) {
      var p = o.p, w = o.prof.rec, b = o.prof.rb, q = o.prof.qb, c = [];
      if (q) {
        c = [Math.round(q.db) + (q.pri ? ' db <span class="dim">(' + Math.round(q.cur ? q.cur.db : 0) + ' this yr)</span>' : ' db'), scPct(q.blitz) + scDelta(q.blitz, LQ.blitz, 1, 5), scPct(q.prs) + scDelta(q.prs, LQ.prs, 1, 5),
             scNum(q.pGr, 0) + ' | ' + scNum(q.nGr, 0), scNum(q.bYpa) + ' | ' + scNum(q.nbYpa)];
      } else if (p.pos === 'RB') {
        c = [(w ? Math.round(w.routes) + ' rt' : '') + (b ? (w ? ' / ' : '') + Math.round(b.att) + ' car' : '') + ((w && w.pri) || (b && b.pri) ? ' <span class="dim">(' + ((w && w.cur) ? Math.round(w.cur.routes) : 0) + (b ? '/' + ((b.cur) ? Math.round(b.cur.att) : 0) : '') + ' this yr)</span>' : ''),
             w ? scPct(w.manSeen) : '\u2014',
             b ? scPct(b.gap) + scDelta(b.gap, LR.gap, 1, 8) : '\u2014',
             b ? scPct(b.edge) + scDelta(b.edge, LR.edge, 1, 8) : '\u2014',
             b ? scNum(b.yco, 2) + scDelta(b.yco, LR.yco, 0, 0.4) : '\u2014'];
      } else {
        c = [Math.round(w.routes) + ' rt' + (w.pri ? ' <span class="dim">(' + (w.cur ? Math.round(w.cur.routes) : 0) + ' this yr)</span>' : ''), scPct(w.manSeen) + scDelta(w.manSeen, L.manSeen, 1, 6),
             scNum(w.mYprr, 2) + ' | ' + scNum(w.zYprr, 2),
             scPct(w.slot) + (p.pos === 'TE' && w.inline != null ? ' <span class="dim">(inline ' + scPct(w.inline) + ')</span>' : ''),
             scPct(w.screen)];
      }
      html += '<tr><td class="l"><b>' + esc(p.name) + '</b></td><td>' + p.pos + '</td>' + c.map(function (x) { return '<td>' + x + '</td>'; }).join('') +
        '<td class="l" style="font-size:11px;white-space:normal;min-width:260px">' + esc(scReads(S, p, q ? q : o.prof, D)) + '</td></tr>';
    });
    html += '</tbody></table>';
    var off = S.off[team];
    if (off) {
      var bits = [];
      if (off.run) bits.push('run game ' + scPct(off.run.gap) + ' gap' + scDelta(off.run.gap, LR.gap, 1, 8) + ', edge ' + scPct(off.run.edge) + scDelta(off.run.edge, LR.edge, 1, 8) + ', ' + scNum(off.run.ypc, 1) + ' ypc');
      if (off.manSeen != null) bits.push('sees man ' + scPct(off.manSeen) + scDelta(off.manSeen, L.manSeen, 1, 6));
      if (off.screen != null) bits.push('screens ' + scPct(off.screen) + ' of targets');
      if (off.blitzFaced != null) bits.push('blitzed ' + scPct(off.blitzFaced) + ', pressured ' + scPct(off.prsFaced));
      html += '<div style="font-size:12px;margin-top:6px"><b>' + esc(team) + ' offense:</b> ' + bits.join(' \u00b7 ') +
        (off.run && off.run.lanes ? '<br><b>Runs to:</b> ' + scLaneLine(off.run.lanes, S.lg.lanes, null, false) : '') +
        (scCoach(S, team) ? '<br>' + esc(scCoachLine(S, team, 'off')) + (scCoachHist(S, team, 'off') ? '<br><span class="dim" style="font-size:11px">' + esc(scCoachHist(S, team, 'off')) + '</span>' : '') : '') + '</div>';
    }
    return html;
  }
  function scMatchupBlock(S, defTeam, offTeam, posF) {
    return '<div style="display:flex;gap:28px;flex-wrap:wrap;align-items:flex-start;margin-top:14px">' +
      '<div>' + scDefCard(S, defTeam, defTeam + ' defense scheme (vs ' + offTeam + ')') + '</div>' +
      '<div style="flex:1;min-width:520px"><h3>' + esc(offTeam) + ' offense profiles</h3>' + scPlayerRows(S, offTeam, posF, S.def[defTeam]) + '</div></div>';
  }
  function scLeagueTable(S) {
    var ss = state.scSort = state.scSort || { key: 'team', dir: 'asc' };
    var rows = Object.keys(S.def).map(function (t) { return { t: t, d: S.def[t] }; });
    var COLS = [{ h: 'Defense', l: 1, k: 'team', dir: 'asc', get: function (o) { return o.t; } }];
    if (S.coaches) COLS.push({ h: 'DC / playcaller', l: 1, k: 'dc', dir: 'asc', tip: 'defensive playcaller (PFR staff; HC when he calls it per coach_overrides.json)', get: function (o) { var c = scCoach(S, o.t); return c ? (c.dcPlay || '') : ''; }, dc: 1 });
    if (S.defPrior) COLS.push({ h: 'vs prior', k: 'rel', tip: 'identity metrics keeping their prior lean (RELIABLE >= 70%, NEW LOOK <= 40%); prior = last season under the SAME playcaller (his previous team when he moved)', get: function (o) { var r = scReliability(S, o.t); return r ? r.ok / r.n : -1; }, rel: 1 });
    SC_DEF_ROWS.forEach(function (r) {
      if (['grCov', 'grRun', 'grPrsh', 'slotYd'].indexOf(r[0]) >= 0) return;
      COLS.push({ h: r[1].replace('Run D: ', 'Run '), k: r[0], sub: r[2], pct: r[3], thr: r[4], tip: r[5], get: function (o) { var v = scGet(o.d, r[0], r[2]); return v == null ? -999 : v; } });
    });
    var sorted = applySort(rows, COLS, ss);
    var html = '<h3 style="margin-top:26px">Defense scheme (PFF, ' + esc(S.updated) + ')</h3>';
    if (S.persist) {
      var ps = Object.keys(S.persist).filter(function (k) { return S.persist[k].r != null; }).sort(function (a, b) { return S.persist[b].r - S.persist[a].r; });
      if (S.persistSplit) {
        var sp = S.persistSplit, ks = ['man', 'blitz', 'dbRush', 'sBox', 'prs'];
        html += '<p class="dim" style="font-size:11px;margin:0 0 4px"><b>Same DC vs new DC</b> (r vs the team\'s 2025; ' + sp.nSame + ' kept their playcaller, ' + sp.nNew + ' changed): ' +
          ks.map(function (k) { var a = sp.sameDC[k], b = sp.newDC[k]; return k + ' ' + (a && a.r != null ? a.r.toFixed(2) : '\u2014') + ' / ' + (b && b.r != null ? b.r.toFixed(2) : '\u2014'); }).join(' \u00b7 ') +
          '. Tendencies travel with the coach, so the prior below follows the playcaller.</p>';
      }
      html += '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>What carried over from the prior</b> (league-wide r, 2026 to date vs each playcaller\'s prior season): ' +
        ps.map(function (k) { var r = S.persist[k].r; return '<span style="color:' + (r >= 0.3 ? 'var(--acc)' : r >= 0.15 ? 'inherit' : '#f85149') + '">' + k.replace('run.', 'run ') + ' ' + r.toFixed(2) + '</span>'; }).join(' \u00b7 ') +
        '. Quote the green ones as identities; the red ones have not separated from noise yet this season.</p>';
    }
    html += '<div id="zn-scheme"><table><thead>' + thRow(COLS, ss) + '</thead><tbody>';
    sorted.forEach(function (o) {
      html += '<tr><td class="l"><b>' + o.t + '</b></td>' + COLS.slice(1).map(function (c) {
        if (c.dc) { var cc = scCoach(S, o.t), sx = scSrc(S, o.t, 'def'); return '<td class="l" style="font-size:11px" title="' + esc(scCoachLine(S, o.t, 'def')) + '">' + (cc ? esc(cc.dcPlay || '\u2014') + (sx && sx.mode !== 'same' ? ' <span style="color:#f85149">new</span>' : ' <span class="dim">' + scYearsIn(S, o.t, 'def') + 'y</span>') : '<span class="dim">\u2014</span>') + '</td>'; }
        if (c.rel) { var rl = scReliability(S, o.t); return '<td title="' + esc(c.tip) + (rl && rl.flips.length ? '; flipped: ' + esc(rl.flips.join(', ')) : '') + '">' + (rl ? '<span style="color:' + rl.col + '">' + rl.label + ' ' + rl.ok + '/' + rl.n + '</span>' : '<span class="dim">\u2014</span>') + '</td>'; }
        var v = scGet(o.d, c.k, c.sub), lg = c.sub ? (S.lg[c.sub] ? S.lg[c.sub][c.k] : null) : S.lg[c.k];
        return '<td title="' + esc(c.tip) + '">' + (v == null ? '<span class="dim">\u2014</span>' : (c.pct ? scPct(v) : scNum(v, 2)) + scDelta(v, lg, c.pct, c.thr)) + '</td>';
      }).join('') + '</tr>';
    });
    html += '</tbody></table></div><p class="dim" style="font-size:11px">Man / blitz / pressure / rusher win rate / safety-in-box are scheme identities (they persist); run-D results, missed tackles and per-lane yards are "so far" (per-lane and per-zone efficiency graded as noise in the backtests). ' +
      'Blitz and pressure come from the QBs each defense faced (nflverse opponent map), so they lag a night behind PFF. Click a header to sort.</p>';
    return html;
  }
  // ---- backtest verdicts on the site (Jack 2026-09-15 "make sure to put all this info in the simlab site") ----
  function scBacktestBlock() {
    var B = window.SIM_SCHEME_BT; if (!B || !B.loyo) return '';
    var r2 = function (v) { return v == null ? '\u2014' : (+v).toFixed(2); };
    var rc = function (v) { return v == null ? 'var(--dim)' : (v >= 0.4 ? 'var(--acc)' : v >= 0.2 ? 'inherit' : '#f85149'); };
    var html = '<h3 style="margin-top:26px">Scheme backtest (backtest_scheme.py, ' + esc(B.updated || '') + ')</h3>' +
      '<p class="dim" style="font-size:12px;margin:0 0 8px"><b>' + esc(B.summary || '') + '</b> Ship bar: LOYO MSE ' + (B.bar ? B.bar.pct : -0.3) + '% or better with ' + (B.bar ? B.bar.wins : 5) + '+ of 7 years better. ' +
      'Everything here is graded on top of the SHIPPED weekly base (P=5 blend x Vegas x in-season FPA), leave-one-year-out 2019-25, same as every layer in the engine.</p>';
    // persistence
    if (B.persist && B.persist.length) {
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Defense metric</th><th title="weeks 1-4 vs weeks 5+ of the same season, all seasons pooled">Early&rarr;late r</th><th title="full season vs the previous full season, same franchise">YoY r</th>' +
        '<th title="YoY r for teams that kept their defensive playcaller">same DC</th><th title="YoY r for teams whose DC changed, vs the OLD team profile">new DC vs old team</th><th title="YoY r for teams whose DC changed, vs the new DC\'s OWN previous defense">new DC vs his last D</th><th class="l">Read</th></tr></thead><tbody>';
      B.persist.forEach(function (p) {
        var id = (p.yoy != null && p.yoy >= 0.4) ? 'IDENTITY \u2014 quote it' : (p.yoy != null && p.yoy >= 0.2 ? 'soft identity' : 'noise \u2014 "so far" only');
        var coach = (p.newHis != null && p.newOld != null) ? (p.newHis - p.newOld >= 0.15 ? '; travels with the coach' : (p.newOld - p.newHis >= 0.15 ? '; stays with the roster' : '')) : '';
        html += '<tr><td class="l">' + esc(p.key.replace('run.', 'run ')) + '</td>' +
          '<td style="color:' + rc(p.e2l) + '">' + r2(p.e2l) + ' <span class="dim" style="font-size:10px">n' + p.nE2l + '</span></td>' +
          '<td style="color:' + rc(p.yoy) + '">' + r2(p.yoy) + ' <span class="dim" style="font-size:10px">n' + p.nYoy + '</span></td>' +
          '<td style="color:' + rc(p.same) + '">' + r2(p.same) + (p.nSame ? ' <span class="dim" style="font-size:10px">n' + p.nSame + '</span>' : '') + '</td>' +
          '<td style="color:' + rc(p.newOld) + '">' + r2(p.newOld) + (p.nNew ? ' <span class="dim" style="font-size:10px">n' + p.nNew + '</span>' : '') + '</td>' +
          '<td style="color:' + rc(p.newHis) + '">' + r2(p.newHis) + (p.nMoved ? ' <span class="dim" style="font-size:10px">n' + p.nMoved + '</span>' : '') + '</td>' +
          '<td class="l" style="font-size:11px">' + id + coach + '</td></tr>';
      });
      html += '</tbody></table></div>';
    }
    // LOYO verdicts
    html += '<div style="overflow-x:auto;margin-top:10px"><table style="width:auto"><thead><tr><th class="l">Interaction</th><th class="l">Form</th><th>n</th><th title="multiplier exponent / slope / flagged-row multiplier picked on pooled data">best k</th><th title="leave-one-year-out MSE vs the shipped base; negative = better">LOYO MSE</th><th>Years better</th><th>Verdict</th></tr></thead><tbody>';
    B.loyo.forEach(function (r) {
      var col = r.verdict === 'PASS' ? 'var(--acc)' : (r.verdict === 'lean' ? 'inherit' : '#f85149');
      html += '<tr><td class="l">' + esc(r.pos) + '</td><td class="l dim" style="font-size:11px">' + esc(r.family) + '</td><td>' + r.n + '</td><td>' + (r.best >= 0 ? '+' : '') + r.best.toFixed(2) + '</td>' +
        '<td style="color:' + col + '">' + (r.pct >= 0 ? '+' : '') + r.pct.toFixed(2) + '%</td><td>' + r.wins + '/' + r.years + '</td><td style="color:' + col + '"><b>' + r.verdict + '</b></td></tr>';
    });
    html += '</tbody></table></div>';
    if (B.scan && B.scan.length) {
      html += '<h4 style="margin:14px 0 4px">Correlation scan</h4><p class="dim" style="font-size:11px;margin:0 0 6px">Every defense metric (D:, vs league), every player profile feature (P:) and every D x P cross term (residualised on its parts) against actual / shipped, per position. ' +
        'Top 12 by |r| shown; anything under |r| .05 is noise at these sample sizes, and the top 3 per position were re-graded LOYO above (rows starting "scan").</p>' +
        '<div style="display:flex;gap:20px;flex-wrap:wrap">';
      B.scan.forEach(function (sc) {
        html += '<table style="width:auto"><thead><tr><th class="l">' + esc(sc.pos) + ' (' + sc.scanned + ' scanned)</th><th>r</th><th>n</th></tr></thead><tbody>' +
          sc.top.map(function (t) { var col = Math.abs(t.r) >= 0.08 ? 'var(--acc)' : Math.abs(t.r) >= 0.05 ? 'inherit' : 'var(--dim)'; return '<tr><td class="l" style="font-size:11px">' + esc(t.k) + '</td><td style="color:' + col + '">' + (t.r >= 0 ? '+' : '') + t.r.toFixed(3) + '</td><td class="dim">' + t.n + '</td></tr>'; }).join('') +
          '</tbody></table>';
      });
      html += '</div>';
    }
    var F = window.SIM_FPRR_BT;
    if (F && F.loyo) {
      html += '<h4 style="margin:14px 0 4px">Fantasy points per route run + ascending players (backtest_fprr.py, ' + esc(F.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(F.summary || '') + '</b> Routes are projected from routes only (last 3 games + season to date); FP/RR is shrunk toward last season and the position prior, so an efficient part-timer stays a part-timer until his routes move (Jack 09-15).</p>';
      if (F.buckets && F.buckets.length) {
        html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">FP/RR tercile x 3-game route trend</th><th>n</th><th title="actual / shipped projection; 1.00 = the model had it right">act / proj</th></tr></thead><tbody>' +
          F.buckets.map(function (b) { var col = b.ratio == null ? 'var(--dim)' : (b.ratio >= 1.08 ? 'var(--acc)' : b.ratio <= 0.96 ? '#f85149' : 'inherit'); return '<tr><td class="l">' + esc(b.name) + '</td><td class="dim">' + b.n + '</td><td style="color:' + col + '">' + (b.ratio == null ? '\u2014' : b.ratio.toFixed(3)) + '</td></tr>'; }).join('') + '</tbody></table></div>';
      }
      html += '<div style="overflow-x:auto;margin-top:8px"><table style="width:auto"><thead><tr><th class="l">Test</th><th class="l">Form</th><th>n</th><th>best</th><th>LOYO MSE</th><th>Years better</th><th>Verdict</th></tr></thead><tbody>' +
        F.loyo.map(function (r) { var col = r.verdict === 'PASS' ? 'var(--acc)' : (r.verdict === 'lean' ? 'inherit' : '#f85149'); return '<tr><td class="l">' + esc(r.pos) + '</td><td class="l dim" style="font-size:11px">' + esc(r.family) + '</td><td>' + r.n + '</td><td>' + (r.best >= 0 ? '+' : '') + r.best.toFixed(2) + '</td><td style="color:' + col + '">' + (r.pct >= 0 ? '+' : '') + r.pct.toFixed(2) + '%</td><td>' + r.wins + '/' + r.years + '</td><td style="color:' + col + '"><b>' + r.verdict + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      var ff = Object.keys(F.flags || {});
      if (ff.length) html += '<p class="dim" style="font-size:11px">Flag rows (actual / projection): ' + ff.map(function (k) { var v = F.flags[k]; return esc(k) + ' n' + v.n + (v.ratio != null ? ' (' + v.ratio.toFixed(3) + ')' : '') + (v.verdict ? ' ' + v.verdict : ''); }).join(' \u00b7 ') + '.</p>';
    }
    var DV = window.SIM_DEFAV_BT;
    if (DV && DV.loyo) {
      html += '<h4 style="margin:14px 0 4px">Defense availability (backtest_def_avail.py, ' + esc(DV.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(DV.summary || '') + '</b> Regulars are found walk-forward from PFF snap shares (no lookahead), weighted by their PFF unit grade above replacement. ' +
        '"known" rows use only absences knowable before the Sim Lab lock: final injury report Out or Doubtful, reserve lists (IR, PUP, exempt, suspended), or the game-day inactive list. REL compares flagged rows with unflagged rows of the same position and week band, because injuries pile up late in seasons.</p>';
      if (DV.buckets && DV.buckets.length) {
        html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Pos</th><th class="l">Opposing defense state</th><th>n</th><th title="actual / shipped projection">act / proj</th><th title="flagged ratio divided by unflagged ratio, same position and week band">REL</th></tr></thead><tbody>' +
          DV.buckets.map(function (b) {
            var v = b.pos === 'DST' ? b.diff : b.rel;
            var col = v == null ? 'var(--dim)' : b.pos === 'DST' ? (v <= -0.5 ? '#f85149' : v >= 0.5 ? 'var(--acc)' : 'inherit') : (v >= 1.04 ? 'var(--acc)' : v <= 0.96 ? '#f85149' : 'inherit');
            return '<tr><td class="l">' + esc(b.pos) + '</td><td class="l">' + esc(b.name) + '</td><td class="dim">' + b.n + '</td><td>' + (b.ratio == null ? '\u2014' : b.ratio.toFixed(3)) + '</td><td style="color:' + col + '">' +
              (b.pos === 'DST' ? (b.diff >= 0 ? '+' : '') + b.diff.toFixed(2) + ' pts' : (b.rel == null ? '\u2014' : b.rel.toFixed(3))) + '</td></tr>';
          }).join('') + '</tbody></table></div>';
      }
      html += '<div style="overflow-x:auto;margin-top:8px"><table style="width:auto"><thead><tr><th class="l">Test</th><th class="l">Form</th><th>n</th><th>best</th><th>LOYO MSE</th><th>Years better</th><th>Verdict</th></tr></thead><tbody>' +
        DV.loyo.map(function (r) { var col = r.verdict === 'PASS' ? 'var(--acc)' : (r.verdict === 'lean' ? 'inherit' : '#f85149'); return '<tr><td class="l">' + esc(r.pos) + '</td><td class="l dim" style="font-size:11px">' + esc(r.family) + '</td><td>' + r.n + '</td><td>' + (r.best >= 0 ? '+' : '') + r.best.toFixed(2) + '</td><td style="color:' + col + '">' + (r.pct >= 0 ? '+' : '') + r.pct.toFixed(2) + '%</td><td>' + r.wins + '/' + r.years + '</td><td style="color:' + col + '"><b>' + r.verdict + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
    }
    var BU = window.SIM_BANGED_BT;
    if (BU && BU.loyo) {
      html += '<h4 style="margin:14px 0 4px">Banged up: injury designation x practice (backtest_banged_up.py, ' + esc(BU.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(BU.summary || '') + '</b> Classes come from the final injury report and the latest practice: Q = Questionable, D = Doubtful, FP / LP / DNP = full, limited, did not practice; "none-LP" = limited practice with no game designation. ' +
        'Play rates count players averaging 40%+ of offensive snaps. REL compares players in the class who played with healthy players of the same position and week band. Implied = P(play) x REL, the expected-value multiplier a projection should carry before kickoff.</p>';
      if (BU.implied && BU.implied.length) {
        html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Class</th><th>Pos</th><th>P(play)</th><th title="actual / projection when they play, vs healthy">REL if plays</th><th title="P(play) x REL">Implied</th><th>Shipped dock</th></tr></thead><tbody>' +
          BU.implied.map(function (r) {
            var gap = r.ev - r.shipped, col = Math.abs(gap) < 0.05 ? 'inherit' : (gap < 0 ? '#f85149' : 'var(--acc)');
            return '<tr><td class="l">' + esc(r.cls) + '</td><td>' + esc(r.pos) + '</td><td>' + r.play.toFixed(2) + '</td><td>' + r.rel.toFixed(3) + '</td><td style="color:' + col + '"><b>' + r.ev.toFixed(2) + '</b></td><td class="dim">x' + r.shipped.toFixed(2) + '</td></tr>';
          }).join('') + '</tbody></table></div>';
      }
      if (BU.snaps && BU.snaps.length) {
        html += '<p class="dim" style="font-size:11px;margin:6px 0">Snap share when they play (game day / prior 3 games, vs healthy): ' +
          BU.snaps.filter(function (x) { return x.pos === 'ALL'; }).map(function (x) { return esc(x.cls) + ' ' + x.rel.toFixed(3) + ' (n ' + x.n + ')'; }).join(' \u00b7 ') + '.</p>';
      }
      var tb = (BU.buckets || []).filter(function (b) { return /teammate|QB played/.test(b.name); });
      if (tb.length) html += '<p class="dim" style="font-size:11px;margin:6px 0">Teammates (own player healthy, no same-group teammate sat): ' + tb.map(function (b) { return esc(b.pos + ' ' + b.name) + ' REL ' + (b.rel == null ? '\u2014' : b.rel.toFixed(3)) + ' (n ' + b.n + ')'; }).join(' \u00b7 ') + '.</p>';
      html += '<div style="overflow-x:auto;margin-top:8px"><table style="width:auto"><thead><tr><th class="l">Test</th><th class="l">Form</th><th>n</th><th>best</th><th>LOYO MSE</th><th>Years better</th><th>Verdict</th></tr></thead><tbody>' +
        BU.loyo.map(function (r) { var col = r.verdict === 'PASS' ? 'var(--acc)' : (r.verdict === 'lean' ? 'inherit' : '#f85149'); return '<tr><td class="l">' + esc(r.pos) + '</td><td class="l dim" style="font-size:11px">' + esc(r.family) + '</td><td>' + r.n + '</td><td>' + (r.best >= 0 ? '+' : '') + r.best.toFixed(2) + '</td><td style="color:' + col + '">' + (r.pct >= 0 ? '+' : '') + r.pct.toFixed(2) + '%</td><td>' + r.wins + '/' + r.years + '</td><td style="color:' + col + '"><b>' + r.verdict + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
    }
    var AG = window.SIM_AGEEXP_BT;
    if (AG && AG.loyo) {
      html += '<h4 style="margin:14px 0 4px">Age x experience workload curves (backtest_age_exp.py, ' + esc(AG.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(AG.summary || '') + '</b> In-season rows are graded on the shipped projection times the shipped snap-trend layer, so they show only what age or experience would add. ' +
        'REL = that group\'s actual / projection divided by its whole position in the same week band. Season-over-season curves multiply the player\'s own 3-year weighted PPG, the prior the no-Clay shadow uses.</p>';
      var wl = (AG.workload || []).filter(function (w) { return w.kind === 'exp' && w.snap; });
      if (wl.length) {
        html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Pos</th><th class="l">Season</th><th title="snap share weeks 7-12 / weeks 2-6, same player">Snaps wk7-12</th><th title="weeks 13-18 / weeks 2-6">Snaps wk13-18</th><th title="touches per game weeks 7-12 / weeks 2-6">Touches wk7-12</th><th>Touches wk13-18</th><th>n</th></tr></thead><tbody>' +
          wl.map(function (w) {
            var c = function (v) { return v == null ? '\u2014' : '<span style="color:' + (v >= 1.05 ? 'var(--acc)' : v <= 0.95 ? '#f85149' : 'inherit') + '">' + v.toFixed(2) + '</span>'; };
            return '<tr><td class="l">' + esc(w.pos) + '</td><td class="l">' + esc(w.bucket) + '</td><td>' + c(w.snap[0]) + '</td><td>' + c(w.snap[1]) + '</td><td>' + c(w.tou ? w.tou[0] : null) + '</td><td>' + c(w.tou ? w.tou[1] : null) + '</td><td class="dim">' + w.snap[2] + '</td></tr>';
          }).join('') + '</tbody></table></div>';
      }
      if (AG.yoy) {
        html += '<p class="dim" style="font-size:11px;margin:6px 0 2px"><b>Season-over-season PPG multiplier on the 3-year prior, by age</b> (touches multiplier / share keeping a 6+ game role in parens):</p>';
        ['QB', 'RB', 'WR', 'TE'].forEach(function (p) {
          var rows = AG.yoy[p] || []; if (!rows.length) return;
          html += '<div style="font-size:11px;margin:1px 0"><b>' + p + '</b> ' + rows.map(function (r) {
            var col = r.ppg >= 1.04 ? 'var(--acc)' : r.ppg <= 0.94 ? '#f85149' : 'inherit';
            return r.age + ': <span style="color:' + col + '">' + r.ppg.toFixed(2) + '</span><span class="dim"> (' + (r.tou != null ? r.tou.toFixed(2) : '\u2014') + ' / ' + (r.avail != null ? Math.round(100 * r.avail) + '%' : '\u2014') + ')</span>';
          }).join(' \u00b7 ') + '</div>';
        });
      }
      if (AG.yoyExp) {
        html += '<div style="font-size:11px;margin:4px 0" class="dim"><b>By season number:</b> ' + ['QB', 'RB', 'WR', 'TE'].map(function (p) { return p + ' ' + (AG.yoyExp[p] || []).map(function (r) { return r.season + ' ' + r.ppg.toFixed(2); }).join(', '); }).join(' \u00b7 ') + '</div>';
      }
      html += '<div style="overflow-x:auto;margin-top:8px"><table style="width:auto"><thead><tr><th class="l">Test</th><th class="l">Form</th><th>n</th><th>LOYO MSE</th><th>Years better</th><th>Verdict</th></tr></thead><tbody>' +
        AG.loyo.map(function (r) { var col = r.verdict === 'PASS' ? 'var(--acc)' : (r.verdict === 'lean' ? 'inherit' : '#f85149'); return '<tr><td class="l">' + esc(r.pos) + '</td><td class="l dim" style="font-size:11px">' + esc(r.family) + '</td><td>' + r.n + '</td><td style="color:' + col + '">' + (r.pct >= 0 ? '+' : '') + r.pct.toFixed(2) + '%</td><td>' + r.wins + '/' + r.years + '</td><td style="color:' + col + '"><b>' + r.verdict + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
    }
    var UC = window.SIM_USAGE_BT;
    if (UC && UC.loyo) {
      html += '<h4 style="margin:14px 0 4px">Usage in context: snaps by field zone, dropback, game script, personnel, spread (backtest_usage_context.py, ' + esc(UC.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(UC.summary || '') + '</b> Every play 2018-25 is placed in a cell: goal line (inside the 5) / red zone / field, dropback / run, neutral score (within 8) / lopsided. ' +
        'League points per on-field snap by cell turn each player\'s snaps into a usage projection. Graded on top of the shipped projection x snap trend; team totals are already in through the Vegas multiplier.</p>';
      if (UC.values) {
        html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Points per on-field snap</th>' +
          ['gl|db|neu', 'gl|run|neu', 'rz|db|neu', 'rz|run|neu', 'fd|db|neu', 'fd|run|neu', 'fd|db|lop', 'fd|run|lop'].map(function (c) { return '<th>' + esc(c.replace(/\|/g, ' ')) + '</th>'; }).join('') + '<th>overall</th></tr></thead><tbody>' +
          ['RB', 'WR', 'TE'].map(function (p) {
            var v = UC.values[p] || {};
            return '<tr><td class="l">' + p + '</td>' + ['gl|db|neu', 'gl|run|neu', 'rz|db|neu', 'rz|run|neu', 'fd|db|neu', 'fd|run|neu', 'fd|db|lop', 'fd|run|lop'].map(function (c) { return '<td>' + (v[c] != null ? v[c].toFixed(3) : '\u2014') + '</td>'; }).join('') + '<td class="dim">' + (v.all != null ? v.all.toFixed(3) : '\u2014') + '</td></tr>';
          }).join('') + '</tbody></table></div>';
      }
      var ub = (UC.buckets || []).filter(function (b) { return b.terciles; });
      if (ub.length) html += '<p class="dim" style="font-size:11px;margin:6px 0">Terciles (actual / projection for low, mid, high thirds of each feature; a real edge slopes): ' +
        ub.map(function (b) { return esc(b.pos + ' ' + b.feature) + ' ' + b.terciles.map(function (t) { return t.toFixed(3); }).join(' / '); }).join(' \u00b7 ') + '.</p>';
      var sb = (UC.buckets || []).filter(function (b) { return b.ratio != null; });
      if (sb.length) html += '<p class="dim" style="font-size:11px;margin:6px 0">Spread: ' + sb.map(function (b) { return esc(b.pos + ' ' + b.feature) + ' ' + b.ratio.toFixed(3) + ' vs ' + b.rest.toFixed(3) + ' (n ' + b.n + ')'; }).join(' \u00b7 ') + '.</p>';
      html += '<div style="overflow-x:auto;margin-top:8px"><table style="width:auto"><thead><tr><th class="l">Test</th><th class="l">Form</th><th>n</th><th>best</th><th>LOYO MSE</th><th>Years better</th><th>Verdict</th></tr></thead><tbody>' +
        UC.loyo.map(function (r) { var col = r.verdict === 'PASS' ? 'var(--acc)' : (r.verdict === 'lean' ? 'inherit' : '#f85149'); return '<tr><td class="l">' + esc(r.pos) + '</td><td class="l dim" style="font-size:11px">' + esc(r.family) + '</td><td>' + r.n + '</td><td>' + (r.best >= 0 ? '+' : '') + r.best.toFixed(2) + '</td><td style="color:' + col + '">' + (r.pct >= 0 ? '+' : '') + r.pct.toFixed(2) + '%</td><td>' + r.wins + '/' + r.years + '</td><td style="color:' + col + '"><b>' + r.verdict + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
    }
    var RC = window.SIM_ROLECHG_BT;
    if (RC && RC.loyo) {
      html += '<h4 style="margin:14px 0 4px">Ascending / descending players (backtest_role_change.py, ' + esc(RC.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(RC.summary || '') + '</b> Last 10 played games (any season) vs his career window (3 prior seasons before them), on snap share and PPG. ' +
        'Ascending = snap share up 20+ points and PPG up 50%+; descending = the reverse. "Teammate ahead was hurt" = a same-position teammate who out-snapped him sat those games and later returned; a teammate who left the team counts as an organic opening.</p>';
      if (RC.buckets && RC.buckets.length) {
        html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Pos</th><th class="l">Group</th><th>n</th><th>Career PPG</th><th>Last-10 PPG</th><th>Projected</th><th>Scored</th><th title="actual / projection vs the whole position">REL</th></tr></thead><tbody>' +
          RC.buckets.map(function (b) { var col = b.rel >= 1.05 ? 'var(--acc)' : b.rel <= 0.95 ? '#f85149' : 'inherit'; return '<tr><td class="l">' + esc(b.pos) + '</td><td class="l">' + esc(b.name) + '</td><td class="dim">' + b.n + '</td><td>' + b.carPpg.toFixed(1) + '</td><td>' + b.recPpg.toFixed(1) + '</td><td>' + b.proj.toFixed(1) + '</td><td>' + b.act.toFixed(1) + '</td><td style="color:' + col + '"><b>' + b.rel.toFixed(3) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      }
      html += '<div style="overflow-x:auto;margin-top:8px"><table style="width:auto"><thead><tr><th class="l">Test</th><th class="l">Form</th><th>n</th><th>best</th><th>LOYO MSE</th><th>Years better</th><th>Verdict</th></tr></thead><tbody>' +
        RC.loyo.map(function (r) { var col = r.verdict === 'PASS' ? 'var(--acc)' : (r.verdict === 'lean' ? 'inherit' : '#f85149'); return '<tr><td class="l">' + esc(r.pos) + '</td><td class="l dim" style="font-size:11px">' + esc(r.family) + '</td><td>' + r.n + '</td><td>' + (r.best >= 0 ? '+' : '') + r.best.toFixed(2) + '</td><td style="color:' + col + '">' + (r.pct >= 0 ? '+' : '') + r.pct.toFixed(2) + '%</td><td>' + r.wins + '/' + r.years + '</td><td style="color:' + col + '"><b>' + r.verdict + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
    }
    var OP = window.SIM_OPPPRIOR_BT;
    if (OP && OP.segments) {
      html += '<h4 style="margin:14px 0 4px">Opportunity prior vs Clay (backtest_opp_prior.py, ' + esc(OP.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(OP.summary || '') + '</b> Preseason season-PPG projections for RB / WR / TE, graded 2019-25 with every fit refit without the test season. ' +
        'OPP = projected target and carry shares (last year, vacated work, team change, age; rookies by draft pick) x team volume x value per opportunity (site xFP) x efficiency. HIST = 3-year weighted PPG, HISTREG = regressed to the position mean, SHADOW = HISTREG for veterans and OPP for rookies. CAL = linear calibration fit on the training seasons (Clay\'s per-game number carries missed games, so raw Clay is off in scale, not ranking); + = regression blend; SHADOWCAL = the Clay-free prior. Lower MSE is better; the parenthesis counts seasons it beat calibrated Clay.</p>';
      var models = ['CLAY', 'CLAYCAL', 'HISTCAL', 'OPPCAL', 'HIST+OPP', 'CLAY+OPP', 'SHADOWCAL'];
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Segment</th><th>Pos</th><th>n</th>' + models.map(function (m) { return '<th>' + esc(m) + '</th>'; }).join('') + '</tr></thead><tbody>' +
        OP.segments.map(function (sg) {
          var best = null; Object.keys(sg.models).forEach(function (m) { if (best == null || sg.models[m].mse < sg.models[best].mse) best = m; });
          return '<tr><td class="l">' + esc(sg.seg) + '</td><td>' + esc(sg.pos) + '</td><td class="dim">' + sg.n + '</td>' + models.map(function (m) {
            var v = sg.models[m]; if (!v) return '<td class="dim">\u2014</td>';
            var col = m === best ? 'var(--acc)' : (sg.models.CLAYCAL && v.mse > sg.models.CLAYCAL.mse ? '#f85149' : 'inherit');
            return '<td style="color:' + col + '">' + (m === best ? '<b>' : '') + v.mse.toFixed(2) + (m === best ? '</b>' : '') + ' <span class="dim" style="font-size:10px">(' + esc(v.beatsClayYears) + ')</span></td>';
          }).join('') + '</tr>';
        }).join('') + '</tbody></table></div>';
    }
    var OW = window.SIM_OPPWEEKLY_BT;
    if (OW && OW.loyo) {
      html += '<h4 style="margin:14px 0 4px">Opportunity prior on the WEEKLY projection (backtest_opp_weekly.py, ' + esc(OW.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(OW.summary || '') + '</b> The Clay per-game number inside the shipped weekly blend is scaled by the out-of-sample Clay + OPP / calibrated Clay season ratio to the power k (k from the other seasons). ' +
        'The ratio rarely moves Clay more than 5%, and the blend hands weight to the season-to-date PPG after a few games, so the weekly effect is tiny. Graded on RB / WR / TE player-weeks 2019-25 vs the shipped projection.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Test</th><th class="l">Form</th><th>n</th><th>best k</th><th>LOYO MSE</th><th>Years better</th><th>Verdict</th></tr></thead><tbody>' +
        OW.loyo.map(function (r) { var col = r.verdict === 'PASS' ? 'var(--acc)' : (r.verdict === 'lean' ? 'inherit' : '#f85149'); return '<tr><td class="l">' + esc(r.pos) + '</td><td class="l dim" style="font-size:11px">' + esc(r.family) + '</td><td>' + r.n + '</td><td>' + r.best.toFixed(2) + '</td><td style="color:' + col + '">' + (r.pct >= 0 ? '+' : '') + r.pct.toFixed(2) + '%</td><td>' + r.wins + '/' + r.years + '</td><td style="color:' + col + '"><b>' + r.verdict + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (OW.bands) html += '<p class="dim" style="font-size:11px;margin:6px 0">By week band at k = 1: ' + OW.bands.map(function (b) { return esc(b.band) + ' ' + (b.pct >= 0 ? '+' : '') + b.pct.toFixed(2) + '% (n ' + b.n + ')'; }).join(' \u00b7 ') + '.</p>';
    }
    var CM = window.SIM_CTXMODEL_BT;
    if (CM && CM.tests) {
      var cmCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      var cmPct = function (p) { return (p >= 0 ? '+' : '') + p.toFixed(2) + '%'; };
      html += '<h4 style="margin:14px 0 4px">Joint context model: every variable at once (backtest_context_model.py, ' + esc(CM.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(CM.summary || '') + '</b> One model learns how far actual points land from the shipped projection (x snap trend) using ' + CM.features + ' variables together: usage and shares, last season, team pass rate, head coach / playcaller changes and the playcaller\'s own history, injury vacancies and inheritance, starting QB out, the offensive line lineman by lineman (last season PFF block grades, starters on the injury report swapped for replacement level), own injury tag, prospect (draft pick, JM score, age, experience), Vegas / weather, and coverage matchup (opponent man rate x the player\'s man vs zone yards per route). ' +
        'Each season is predicted by a model trained on the other six (and a shrink picked on a held-out season); FORWARD trains on earlier seasons only. CAL = the same model with only the projection-level variables, so the gap between them is what context adds. Research only - nothing here is in the live projection.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Model</th><th>Pos</th><th>n</th><th>Shipped MSE</th><th>Model MSE</th><th>Change</th><th>Seasons better</th><th>Verdict</th></tr></thead><tbody>' +
        CM.tests.map(function (r) { return '<tr><td class="l">' + esc(r.family) + '</td><td>' + esc(r.pos) + '</td><td class="dim">' + r.n + '</td><td>' + r.base.toFixed(2) + '</td><td>' + r.mse.toFixed(2) + '</td><td style="color:' + cmCol(r.verdict) + '">' + cmPct(r.pct) + '</td><td>' + r.wins + '/' + r.years + '</td><td style="color:' + cmCol(r.verdict) + '"><b>' + r.verdict + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (CM.increment && CM.increment.length) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>What is actually new.</b> The historical base lacks layers the live engine already has (TD-luck regression, snap trend, banged-up docks, rookie level, the vacancy pool, weather / Vegas). REF = the model with only those signals; each row adds groups on top. The ship test is vs REF, and forward (train on past seasons only) must also improve:</p><div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Model</th><th>Variables</th><th>vs shipped</th><th>vs REF</th><th>Seasons better vs REF</th><th>Forward vs REF</th><th>Verdict</th></tr></thead><tbody>' +
        CM.increment.map(function (r) { var col = r.verdict === 'REF' ? 'inherit' : cmCol(r.verdict); return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.features + '</td><td>' + cmPct(r.vsBase2) + '</td><td style="color:' + col + '">' + (r.label === 'REF' ? '\u2014' : cmPct(r.vsRef)) + '</td><td>' + (r.label === 'REF' ? '\u2014' : r.winsVsRef + '/7') + '</td><td>' + (r.label === 'REF' ? '\u2014' : cmPct(r.fwdVsRef) + ' (' + r.fwdWinsVsRef + '/5)') + '</td><td style="color:' + col + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (CM.subsets && CM.subsets.length) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>New situations</b> (actual / shipped shows whether the shipped number ran high or low there):</p><div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Situation</th><th>n</th><th>Actual / shipped</th><th>Context model</th><th>Calibration only</th></tr></thead><tbody>' +
        CM.subsets.map(function (s) { return '<tr><td class="l">' + esc(s.label) + '</td><td class="dim">' + s.n + '</td><td>' + s.actOverBase.toFixed(3) + '</td><td style="color:' + cmCol(s.verdict) + '">' + cmPct(s.gbmPct) + ' (' + s.gbmWins + '/' + s.years + ')</td><td>' + cmPct(s.calPct) + ' (' + s.calWins + '/' + s.years + ')</td></tr>'; }).join('') + '</tbody></table></div>';
      if (CM.ablation && CM.ablation.length) html += '<p class="dim" style="font-size:11px;margin:6px 0">What each group adds (model error without it; + = the group helped): ' + CM.ablation.map(function (g) { return esc(g.group) + ' ' + cmPct(g.helpPct); }).join(' \u00b7 ') + '.</p>';
      if (CM.importance && CM.importance.length) html += '<p class="dim" style="font-size:11px;margin:6px 0">Share of model splits by group: ' + CM.importance.map(function (g) { return esc(g.group) + ' ' + (100 * g.share).toFixed(0) + '%' + (g.top.length ? ' (' + esc(g.top.join(', ')) + ')' : ''); }).join(' \u00b7 ') + '.</p>';
      if (CM.forward && CM.forward.length) html += '<p class="dim" style="font-size:11px;margin:6px 0">Forward (train on earlier seasons only): ' + CM.forward.map(function (f) { return f.year + ' ' + cmPct((f.gbm / f.base - 1) * 100); }).join(' \u00b7 ') + (CM.forwardSummary ? ' \u00b7 pooled ' + cmPct(CM.forwardSummary.pct) + ' (' + CM.forwardSummary.wins + '/' + CM.forwardSummary.years + '), calibration only ' + cmPct(CM.forwardSummary.calPct) : '') + '.</p>';
    }
    var LB = window.SIM_LEARNED_BT;
    if (LB && LB.models) {
      var lbPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var lbCol = function (p) { return p <= -0.3 ? 'var(--acc)' : (p >= 0 ? '#f85149' : 'inherit'); };
      var lbName = { 'STRENGTH': 'Refit layer strengths (+ position scale)', 'STRENGTH-NS': 'Refit layer strengths only', 'CAL': 'Recalibrate the hand stack (per position)', 'GBM+HAND': 'Learned correction on top of the hand stack', 'GBM': 'Learned replacement of the hand stack' };
      html += '<h4 style="margin:14px 0 4px">Learned combination vs the hand-tuned live layers (backtest_learned_combo.py, ' + esc(LB.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(LB.summary || '') + '</b> The live stack (TD luck, banged-up docks, rookie level, RB snap usage, wind, opportunity pool, backup-QB inheritance) was rebuilt with the engine\'s own constants on every graded player-week. ' +
        'Not replayable: the 70% player-prop anchor, availability of players who sat, forecast wind, the TE route trend. So a pass here earns a live shadow graded by the weekly scorecard, not a swap.</p>';
      if (LB.ladder) html += '<p class="dim" style="font-size:11px;margin:4px 0">Hand stack, one layer at a time: ' + LB.ladder.slice(1).map(function (s) { return esc(s.step.replace('+ ', '').replace(' = HAND', '')) + ' <span style="color:' + lbCol(s.pct) + '">' + lbPct(s.pct) + '</span> (' + s.wins + '/7)'; }).join(' \u00b7 ') + '.</p>';
      var lbAll = LB.models.filter(function (r) { return r.pos === 'ALL'; });
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Learned version</th><th>vs hand</th><th>Seasons better</th><th>Forward</th><th>QB</th><th>RB</th><th>WR</th><th>TE</th><th>Verdict</th></tr></thead><tbody>' +
        lbAll.map(function (r) {
          var byPos = function (p) { var x = LB.models.filter(function (m) { return m.model === r.model && m.pos === p; })[0]; return x ? '<td style="color:' + lbCol(x.pct) + '">' + lbPct(x.pct) + '</td>' : '<td>\u2014</td>'; };
          var vc = r.verdict === 'PASS' ? 'var(--acc)' : (r.verdict === 'lean' ? 'inherit' : '#f85149');
          return '<tr><td class="l">' + esc(lbName[r.model] || r.model) + '</td><td style="color:' + lbCol(r.pct) + '">' + lbPct(r.pct) + '</td><td>' + r.wins + '/7</td><td style="color:' + lbCol(r.fwdPct) + '">' + lbPct(r.fwdPct) + ' (' + r.fwdWins + '/5)</td>' + byPos('QB') + byPos('RB') + byPos('WR') + byPos('TE') + '<td style="color:' + vc + '"><b>' + esc(r.verdict) + '</b></td></tr>';
        }).join('') + '</tbody></table></div>';
      if (LB.subsets && LB.subsets.length) html += '<p class="dim" style="font-size:11px;margin:6px 0">Where layers are active (learned correction vs hand): ' + LB.subsets.map(function (s) { return esc(s.label) + ' ' + lbPct(s['GBM+HAND']) + ' (n ' + s.n + ', actual/hand ' + s.actOverHand.toFixed(3) + ')'; }).join(' \u00b7 ') + '.</p>';
    }
    var LT = window.SIM_LSTUNE;
    if (LT && LT.shap) {
      var ltPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      html += '<h4 style="margin:14px 0 4px">Learned shadow tuning (tune_learned_shadow.py, ' + esc(LT.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(LT.summary || '') + '</b>' + (LT.adopted ? ' Adopted: ' + esc(LT.adopted.change) + ' (LOYO ' + ltPct(LT.adopted.loyo) + ', forward ' + ltPct(LT.adopted.fwd) + ') - ' + esc(LT.adopted.why) + '.' : '') + '</p>';
      if (LT.levelSignal) html += '<p class="dim" style="font-size:11px;margin:4px 0">Level vs player signal (vs the hand stack): ' + LT.levelSignal.map(function (x) { return esc(x.label) + ' ' + ltPct(x.pct) + ' (' + x.wins + '/7)'; }).join(' \u00b7 ') + '.</p>';
      html += '<p class="dim" style="font-size:11px;margin:4px 0">What drives the correction (share of attribution; direction + = higher value pushes the projection up): ' + LT.shap.slice(0, 12).map(function (s) { return esc(s.feature) + ' ' + (100 * s.share).toFixed(0) + '%' + (s.dir != null ? ' (' + (s.dir >= 0 ? '+' : '') + s.dir.toFixed(2) + ')' : ''); }).join(' \u00b7 ') + '.</p>';
      if (LT.quintiles) html += LT.quintiles.slice(0, 4).map(function (q) { return '<div class="dim" style="font-size:11px;margin:1px 0"><b>' + esc(q.feature) + '</b> quintiles: ' + q.bins.map(function (b) { return b.lo + '-' + b.hi + ' actual/hand ' + b.actOverHand.toFixed(3) + ' corr ' + (b.contrib >= 0 ? '+' : '') + b.contrib.toFixed(2); }).join(' \u00b7 ') + '</div>'; }).join('');
      if (LT.audit) html += '<p class="dim" style="font-size:11px;margin:6px 0 2px"><b>Hand-layer audit</b> (REL = actual/hand vs same-position rows where the layer is off; below 1 = the layer is too generous there):</p><div class="dim" style="font-size:11px">' + LT.audit.map(function (x) { var c = x.rel != null && x.rel < 0.95 ? '#f85149' : (x.rel != null && x.rel > 1.05 ? 'var(--acc)' : 'inherit'); return esc(x.layer) + ' ' + esc(x.bin) + ' <span style="color:' + c + '">' + (x.rel != null ? x.rel.toFixed(3) : '\u2014') + '</span> (n ' + x.n + ')'; }).join(' \u00b7 ') + '</div>';
      if (LT.sweeps) html += '<div style="overflow-x:auto;margin-top:6px"><table style="width:auto"><thead><tr><th class="l">Tweak</th><th>LOYO vs hand</th><th>Seasons</th><th>Forward</th><th>Beats current on both</th></tr></thead><tbody>' +
        LT.sweeps.map(function (s) { return '<tr><td class="l">' + esc(s.label) + '</td><td>' + ltPct(s.loyo) + '</td><td>' + s.wins + '/7</td><td>' + ltPct(s.fwd) + ' (' + s.fwdWins + '/5)</td><td>' + (s.better ? '<b style="color:var(--acc)">yes</b>' : 'no') + '</td></tr>'; }).join('') + '</tbody></table></div>';
      if (LT.seedcheck) html += '<p class="dim" style="font-size:11px;margin:6px 0">Seed check (3 random seeds each; run-to-run noise is about \u00b10.08%): ' + LT.seedcheck.map(function (s) { return esc(s.label) + ' LOYO ' + ltPct(s.loyoMean) + ' / forward ' + ltPct(s.fwdMean); }).join(' \u00b7 ') + '. Drop-one-feature gains of 0.1-0.17% were noise: removing them all together scored worse.</p>';
    }
    var LF = window.SIM_LAYERFIX_BT;
    if (LF && LF.tests) {
      var lfPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      html += '<h4 style="margin:14px 0 4px">Hand-layer fixes: pool cap, Questionable no-practice dock, wind strength (backtest_layer_fixes.py, ' + esc(LF.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px">The three fixes the learned-shadow audit pointed at, graded on the rebuilt live stack (17,657 player-weeks 2019-25). Strength picked on the other seasons (LOYO) and on earlier seasons only (forward); flagged = rows the fix touches. None pass: the audit ratios compared rows with different mixes (position, week), and once the fix is graded directly the gains vanish or reverse forward.</p>' +
        '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Fix</th><th>Flagged rows</th><th>LOYO all</th><th>LOYO flagged</th><th>Forward all</th><th>Forward flagged</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        LF.tests.map(function (t) { var vc = /PASS/.test(t.verdict) ? 'var(--acc)' : (t.verdict === 'lean' ? 'inherit' : '#f85149'); return '<tr><td class="l">' + esc(t.label) + '</td><td class="dim">' + t.nFlag + '</td><td>' + lfPct(t.loyo_all) + ' (' + t.loyo_all_wins + '/7)</td><td>' + lfPct(t.loyo_flag) + ' (' + (t.loyo_flag_wins || 0) + '/7)</td><td>' + lfPct(t.fwd_all) + '</td><td>' + lfPct(t.fwd_flag) + ' (' + (t.fwd_flag_wins || 0) + '/5)</td><td class="dim" style="font-size:10px">' + esc((t.loyo_picks || []).join(' ')) + '</td><td style="color:' + vc + '"><b>' + esc(t.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
    }
    var NC = window.SIM_NOCLAY_BT;
    if (NC && NC.variants) {
      var ncPct = function (p) { return p == null ? '—' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var ncCol = function (p) { return p == null ? 'inherit' : (p <= 0.3 ? 'var(--acc)' : (p >= 3 ? '#f85149' : 'inherit')); };
      html += '<h4 style="margin:14px 0 4px">Clay-free weekly ladder: how far is the shadow from Clay, and where (backtest_noclay_weekly.py, ' + esc(NC.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(NC.summary || '') + '</b> The live Clay-free shadow (ncMean: own 3-yr PPG + last-8-games prior, age curve, opportunity prior) rebuilt walk-forward on every Clay-pool player-week 2019-25 (' + NC.n + ' rows, week 1 included) inside the same P=5 blend and Vegas / FPA layers, graded against the shipped Clay blend. ' +
        '"Clay fallback" = rows with no history still use Clay (the live shadow); "CLAY-FREE" swaps the fallback for a position mean, a draft-round rookie mean, or the rookie opportunity prior. Positive = worse than Clay. The combined candidate is wired as SHADOW v2 (engine NC_SHADOW, ADP-gated; Clay stays live) and graded from the W2 scorecard on.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Prior</th><th>MSE</th><th>vs shipped</th><th>Seasons better</th><th>QB</th><th>RB</th><th>WR</th><th>TE</th></tr></thead><tbody>' +
        NC.variants.map(function (v) { return '<tr><td class="l">' + esc(v.label) + '</td><td>' + v.mse.toFixed(2) + '</td><td style="color:' + ncCol(v.pct) + '">' + ncPct(v.pct) + '</td><td>' + v.wins + '/' + v.years + '</td>' + ['QB', 'RB', 'WR', 'TE'].map(function (ps) { return '<td style="color:' + ncCol(v.byPos[ps]) + '">' + ncPct(v.byPos[ps]) + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>';
      if (NC.bands) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>By week of season</b> (MSE vs shipped: live shadow | fully Clay-free | Clay-free at the LOYO-best prior strength P=' + (NC.bestP != null ? NC.bestP : '?') + '):</p><div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Band</th><th>n</th><th>Live shadow</th><th>Clay-free</th><th>Clay-free, best P</th><th>QB</th><th>RB</th><th>WR</th><th>TE</th></tr></thead><tbody>' +
        NC.bands.map(function (b) { return '<tr><td class="l">' + esc(b.band) + '</td><td class="dim">' + b.n + '</td><td style="color:' + ncCol(b.live) + '">' + ncPct(b.live) + '</td><td style="color:' + ncCol(b.free) + '">' + ncPct(b.free) + '</td><td style="color:' + ncCol(b.freeBestP) + '">' + ncPct(b.freeBestP) + '</td>' + ['QB', 'RB', 'WR', 'TE'].map(function (ps) { return '<td style="color:' + ncCol(b['free_' + ps]) + '">' + ncPct(b['free_' + ps]) + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>';
      if (NC.segments) html += '<p class="dim" style="font-size:11px;margin:6px 0">By situation (actual / shipped, then live shadow | Clay-free vs shipped): ' + NC.segments.map(function (s) { return esc(s.seg) + ' n' + s.n + ' ' + s.actOverShip.toFixed(3) + ' <span style="color:' + ncCol(s.live) + '">' + ncPct(s.live) + '</span> | <span style="color:' + ncCol(s.free) + '">' + ncPct(s.free) + '</span>'; }).join(' · ') + '.</p>';
      if (NC.fallback) html += '<p class="dim" style="font-size:11px;margin:6px 0">Rows with no Clay-free prior (rookies + no history), by band: ' + NC.fallback.map(function (f) { return esc(f.band) + ' ' + f.fbPct.toFixed(1) + '% (' + f.rookies + ' rookie, ' + f.others + ' other)'; }).join(' · ') + '. The last-8-games prior picks a rookie up after his 4th game, so the fallback empties itself by midseason.</p>';
      if (NC.sweeps) html += '<div style="overflow-x:auto;margin-top:6px"><table style="width:auto"><thead><tr><th class="l">Knob (Clay-free version)</th><th>n</th><th>Current</th><th>Current vs shipped</th><th>LOYO best vs shipped</th><th>Seasons better than Clay</th><th>Picks</th></tr></thead><tbody>' +
        NC.sweeps.map(function (s) { return '<tr><td class="l">' + esc(s.label) + '</td><td class="dim">' + s.n + '</td><td>' + s.current + '</td><td style="color:' + ncCol(s.curPct) + '">' + ncPct(s.curPct) + '</td><td style="color:' + ncCol(s.loyoPct) + '">' + ncPct(s.loyoPct) + '</td><td>' + s.wins + '/' + s.years + '</td><td class="dim" style="font-size:10px">' + esc(s.picks.join(' ')) + '</td></tr>'; }).join('') + '</tbody></table></div>';
    }
    var RP = window.SIM_ROOKIEPRIOR_BT;
    if (RP && RP.priorAlone) {
      var rpPct = function (p) { return p == null ? '—' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var rpCol = function (p) { return p == null ? 'inherit' : (p <= -0.3 ? 'var(--acc)' : (p >= 1 ? '#f85149' : 'inherit')); };
      html += '<h4 style="margin:14px 0 4px">Market-informed prior: preseason ADP for rookies (rejected) and for veterans (shadow v2.1) (backtest_rookie_prior.py, ' + esc(RP.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(RP.summary || '') + '</b> Preseason ADP (FFC 12-team, 2019-25) and the JM prospect score as Clay-free rookie priors, fit per position on the other seasons, graded as the prior alone on rookie weeks 1-4 and inside the full Clay-free shadow. Then the same ADP curve (fit on everyone) blended into the veterans\' history prior. Research only; the veteran blend is wired as shadow v2.1 (Clay stays live).</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Rookie prior (weeks 1-4, prior alone)</th><th>n</th><th>MSE</th><th>vs Clay</th><th>QB</th><th>RB</th><th>WR</th><th>TE</th><th>ADP-listed</th><th>unlisted</th></tr></thead><tbody>' +
        RP.priorAlone.map(function (r) { return '<tr><td class="l">' + esc(r.model) + '</td><td class="dim">' + r.n + '</td><td>' + r.mse.toFixed(2) + '</td><td style="color:' + rpCol(r.vsClay) + '">' + rpPct(r.vsClay) + '</td>' + ['QB', 'RB', 'WR', 'TE'].map(function (ps) { return '<td>' + rpPct(r.byPos[ps]) + '</td>'; }).join('') + '<td>' + rpPct(r.listed) + '</td><td>' + rpPct(r.unlisted) + '</td></tr>'; }).join('') + '</tbody></table></div>';
      if (RP.blended) html += '<p class="dim" style="font-size:11px;margin:6px 0">Inside the Clay-free shadow (all rows vs shipped | rookie rows | week 1): ' + RP.blended.map(function (r) { return esc(r.model) + ' <span style="color:' + rpCol(r.pct) + '">' + rpPct(r.pct) + '</span> | ' + rpPct(r.rookie) + ' | ' + rpPct(r.wk1); }).join(' · ') + '. Every ADP rookie model loses to the draft pick alone, so rookies keep the pick fallback.</p>';
      if (RP.vets) html += '<div style="overflow-x:auto;margin-top:6px"><table style="width:auto"><thead><tr><th class="l">Veterans: ADP weight in the history prior</th><th>n</th><th>No ADP (current)</th><th>LOYO best vs shipped</th><th>Seasons better than Clay</th><th>Picks</th></tr></thead><tbody>' +
        RP.vets.map(function (s) { return '<tr><td class="l">' + esc(s.label) + '</td><td class="dim">' + s.n + '</td><td>' + rpPct(s.curPct) + '</td><td style="color:' + rpCol(s.loyoPct) + '">' + rpPct(s.loyoPct) + '</td><td>' + s.wins + '/' + s.years + '</td><td class="dim" style="font-size:10px">' + esc(s.picks.join(' ')) + '</td></tr>'; }).join('') + '</tbody></table></div>';
      if (RP.v21) { var v = RP.v21; html += '<p class="dim" style="font-size:11px;margin:6px 0"><b>Shadow v2.1</b> (vets ADP weight ' + v.wVet + ', 2nd-year ' + v.wYr2 + ', rookies by pick): <span style="color:' + rpCol(v.pct) + '">' + rpPct(v.pct) + '</span> vs shipped (' + v.wins + '/' + v.years + '), vs shadow v2 ' + rpPct(v.vsV2) + ' (' + v.vsV2Wins + '/' + v.years + '), forward ' + rpPct(v.forward.pct) + ' (' + v.forward.wins + '/' + v.forward.years + '). By position ' + ['QB', 'RB', 'WR', 'TE'].map(function (ps) { return ps + ' ' + rpPct(v.byPos[ps]); }).join(', ') + '. By week: ' + v.bands.map(function (b) { return esc(b.band) + ' ' + rpPct(b.v2) + ' → <span style="color:' + rpCol(b.pct) + '">' + rpPct(b.pct) + '</span>'; }).join(' · ') + '. Situations: ' + v.segments.map(function (s) { return esc(s.seg) + ' ' + rpPct(s.v2) + ' → ' + rpPct(s.pct); }).join(' · ') + '.</p>'; }
    }
    var RD = window.SIM_ROOKIEDEPTH_BT;
    if (RD && RD.priorAlone) {
      var rdPct = function (p) { return p == null ? '—' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var rdCol = function (p) { return p == null ? 'inherit' : (p <= -0.3 ? 'var(--acc)' : (p >= 1 ? '#f85149' : 'inherit')); };
      html += '<h4 style="margin:14px 0 4px">Live depth-chart slot for rookies (backtest_rookie_depth_live.py, ' + esc(RD.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(RD.summary || '') + '</b> The real pre-game depth charts 2019-25 (nflverse weekly charts, the same ESPN charts the engine reads live) as a rookie feature: string 1 = starter, 2 = second string, 3+ = deeper. Fit per position on the other seasons on top of the draft-pick prior; graded as the prior alone on rookie weeks 1-4 and inside the Clay-free shadow v2.1. Wired as shadow v2.2 for RB and WR (Clay stays live).</p>';
      if (RD.buckets) html += '<p class="dim" style="font-size:11px;margin:4px 0">Rookie weeks 1-4, actual / pick prior (actual / Clay) by string: ' + RD.buckets.filter(function (b) { return b.pos !== 'ALL'; }).map(function (b) { return esc(b.pos) + ' ' + esc(b.string) + ' n' + b.n + ' ' + b.actOverPick.toFixed(2) + ' (' + b.actOverClay.toFixed(2) + ')'; }).join(' · ') + '.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Rookie prior (weeks 1-4, prior alone)</th><th>n</th><th>MSE</th><th>vs Clay</th><th>vs pick</th><th>QB</th><th>RB</th><th>WR</th><th>TE</th><th>2nd/3rd-string rows</th></tr></thead><tbody>' +
        RD.priorAlone.map(function (r) { return '<tr><td class="l">' + esc(r.model) + '</td><td class="dim">' + r.n + '</td><td>' + r.mse.toFixed(2) + '</td><td style="color:' + rdCol(r.vsClay) + '">' + rdPct(r.vsClay) + '</td><td style="color:' + rdCol(r.vsPick) + '">' + rdPct(r.vsPick) + '</td>' + ['QB', 'RB', 'WR', 'TE'].map(function (ps) { return '<td>' + rdPct(r.byPos[ps]) + '</td>'; }).join('') + '<td>' + rdPct(r.deep) + '</td></tr>'; }).join('') + '</tbody></table></div>';
      if (RD.blended) html += '<p class="dim" style="font-size:11px;margin:6px 0">Inside the shadow (all rows vs shipped | vs v2.1 | rookie rows | week 1): ' + RD.blended.map(function (r) { return esc(r.model) + ' ' + rdPct(r.pct) + ' | <span style="color:' + rdCol(r.vsRef) + '">' + rdPct(r.vsRef) + '</span> (' + r.vsRefWins + '/' + r.years + ')' + (r.forward ? ', fwd ' + rdPct(r.forward.vsRef) : '') + ' | ' + rdPct(r.rookie) + ' | ' + rdPct(r.wk1); }).join(' · ') + '.</p>';
      if (RD.vets) html += '<p class="dim" style="font-size:11px;margin:6px 0">Veterans by pre-game string (weeks 1-8, actual / shadow prior, actual / shipped): ' + RD.vets.map(function (v) { return esc(v.pos) + ' ' + esc(v.string) + ' n' + v.n + ' ' + v.actOverPrior.toFixed(2) + ' (' + v.actOverShipped.toFixed(2) + ')'; }).join(' · ') + (RD.vetDock ? '. Demoted-vet dock on the shadow: LOYO ' + rdPct(RD.vetDock.loyoPct) + ' vs shipped (' + RD.vetDock.wins + '/' + RD.vetDock.years + ') — Clay still reads demotions better; not shipped.' : '') + '</p>';
    }
    var DV = window.SIM_DEMOTED_BT;
    if (DV && DV.sweeps) {
      var dvPct = function (p) { return p == null ? '—' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var dvCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">Demoted veterans on the Clay-free shadow (backtest_demoted_vets.py, ' + esc(DV.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(DV.summary || '') + '</b> Veterans with a history prior, by pre-game depth string (nflverse charts 2019-25 = the ESPN charts the engine reads live). Layers act on the shadow PRIOR and are graded against shadow v2.2 itself (the number they change), with the shipped Clay blend as context. Wired as shadow v2.3 (Clay stays live).</p>';
      if (DV.reads) html += '<p class="dim" style="font-size:11px;margin:4px 0">Actual / shadow prior (actual / shipped) by string: ' + DV.reads.map(function (r) { return esc(r.pos) + ' ' + esc(r.string) + ' n' + r.n + ' ' + r.actOverPrior.toFixed(2) + ' (' + r.actOverShipped.toFixed(2) + ')'; }).join(' · ') + '.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Layer</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped → new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        DV.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + dvCol(r.verdict) + '">' + dvPct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + dvPct(r.shadowVsShip) + ' → ' + dvPct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + dvCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (DV.candidate && DV.candidate.bands) { var cd = DV.candidate; html += '<p class="dim" style="font-size:11px;margin:6px 0"><b>Shadow v2.3</b> (docks ' + esc(JSON.stringify(cd.dock)) + '): ' + dvPct(cd.vsRef) + ' vs shadow v2.2 (' + cd.vsRefWins + '/' + cd.years + '), ' + dvPct(cd.pct) + ' vs shipped (' + cd.wins + '/' + cd.years + '), forward ' + dvPct(cd.forward.vsRef) + ' vs shadow (' + cd.forward.vsRefWins + '/' + cd.forward.years + '), demoted rows forward ' + dvPct(cd.forward.demotedVsRef) + '. By week vs shipped: ' + cd.bands.map(function (b) { return esc(b.band) + ' ' + dvPct(b.refVsShip) + ' → ' + dvPct(b.vsShip); }).join(' · ') + '. Situations: ' + cd.segments.map(function (s) { return esc(s.seg) + ' ' + dvPct(s.refVsShip) + ' → ' + dvPct(s.vsShip); }).join(' · ') + '.</p>'; }
    }
    var NCV = window.SIM_NOCHART_BT;
    if (NCV && NCV.causes) {
      var ncvPct = function (p) { return p == null ? '—' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var ncvCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">Veterans without a depth-chart entry (backtest_nochart_vets.py, ' + esc(NCV.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(NCV.summary || '') + '</b> The 1,180 veteran player-weeks with a history prior but no pre-game chart string, split by cause, then the fixes graded against shadow v2.3. Verdict: read the chart on the player\'s current team (engine depthString now falls back to Sleeper\'s team, then any team); no dock for the truly unlisted.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Cause</th><th>n</th><th>Actual / shadow prior</th><th>Actual / shipped</th><th>Shadow vs shipped</th></tr></thead><tbody>' +
        NCV.causes.map(function (c) { return '<tr><td class="l">' + esc(c.cause) + '</td><td class="dim">' + c.n + '</td><td>' + (c.actOverPrior == null ? '—' : c.actOverPrior.toFixed(3)) + '</td><td>' + (c.actOverShipped == null ? '—' : c.actOverShipped.toFixed(3)) + '</td><td>' + ncvPct(c.vsShip) + '</td></tr>'; }).join('') + '</tbody></table></div>';
      html += '<div style="overflow-x:auto;margin-top:6px"><table style="width:auto"><thead><tr><th class="l">Layer</th><th>n affected</th><th>All rows vs shadow</th><th>Seasons better</th><th>Affected rows</th><th>Verdict</th></tr></thead><tbody>' +
        NCV.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td>' + ncvPct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + (r.affectedPct != null ? ncvPct(r.affectedPct) : (r.shadowVsShip != null ? ncvPct(r.shadowVsShip) + ' → ' + ncvPct(r.newVsShip) + ' vs shipped' : '—')) + '</td><td style="color:' + ncvCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (NCV.candidate && NCV.candidate.segments) { var cn = NCV.candidate; html += '<p class="dim" style="font-size:11px;margin:6px 0"><b>Shadow v2.4</b> (current-team chart lookup): ' + ncvPct(cn.vsRef) + ' vs shadow v2.3 (' + cn.vsRefWins + '/' + cn.years + '), ' + ncvPct(cn.pct) + ' vs shipped (' + cn.wins + '/' + cn.years + '). ' + cn.segments.map(function (s) { return esc(s.seg) + ' n' + s.n + ' ' + ncvPct(s.refVsShip) + ' → ' + ncvPct(s.vsShip); }).join(' · ') + (cn.forward ? '. Unlisted dock forward: ' + ncvPct(cn.forward.vsRef) + ' (' + cn.forward.vsRefWins + '/' + cn.forward.years + ') — not shipped.' : '.') + '</p>'; }
    }
    var DP = window.SIM_DROPPED_BT;
    if (DP && DP.reads) {
      var dpPct = function (p) { return p == null ? '—' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var dpCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">Dropped-off-the-chart veterans (backtest_dropped_vets.py, ' + esc(DP.updated || '') + ') — REJECTED</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(DP.summary || '') + '</b> Veterans listed on their team\'s chart 1-3 weeks earlier but not this week (n ' + (DP.candidate && DP.candidate.droppedN) + '). The official injury reports were joined and the live injury docks (Doubtful x.5, Questionable + DNP x.75) applied to both sides, so any layer here is what the chart drop adds beyond the designation. Nothing ships.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Designation</th><th>Dropped n</th><th>Dropped actual / prior</th><th>Listed n</th><th>Listed actual / prior</th></tr></thead><tbody>' +
        DP.reads.filter(function (r) { return r.droppedN || r.listedN; }).map(function (r) { return '<tr><td class="l">' + esc(r.cls) + '</td><td class="dim">' + r.droppedN + '</td><td>' + (r.droppedRatio == null ? '—' : r.droppedRatio.toFixed(2)) + '</td><td class="dim">' + r.listedN + '</td><td>' + (r.listedRatio == null ? '—' : r.listedRatio.toFixed(3)) + '</td></tr>'; }).join('') + '</tbody></table></div>';
      html += '<div style="overflow-x:auto;margin-top:6px"><table style="width:auto"><thead><tr><th class="l">Layer</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped → new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        DP.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + dpCol(r.verdict) + '">' + dpPct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + dpPct(r.shadowVsShip) + ' → ' + dpPct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + dpCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (DP.candidate && DP.candidate.forward) html += '<p class="dim" style="font-size:11px;margin:6px 0">Best candidate (' + esc(DP.candidate.mask) + ' x' + DP.candidate.m + '): ' + dpPct(DP.candidate.vsRef) + ' vs shadow v2.4 (' + DP.candidate.vsRefWins + '/' + DP.candidate.years + '), forward ' + dpPct(DP.candidate.forward.vsRef) + ' (' + DP.candidate.forward.vsRefWins + '/' + DP.candidate.forward.years + '). Only RBs show a signal (n 45), too thin to ship. The "listed vets Q-LP / Q-DNP" rows check whether the live docks are calibrated on the shadow: Q-LP x.9 lean, Q-DNP x1.1 noise.</p>';
    }
    var W1 = window.SIM_WEEK1_BT;
    if (W1 && W1.reads) {
      var w1Pct = function (p) { return p == null ? '—' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var w1Col = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">Week 1 on the Clay-free shadow: the buried-rookie ramp (backtest_week1.py, ' + esc(W1.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(W1.summary || '') + '</b> Week 1 is the only week where the shadow is pure prior. Reads by position / situation / ADP / string, then every week-1 knob swept LOYO against shadow v2.4. Wired as shadow v2.5: a chart-defined ramp for rookies at 2nd string or deeper that replaces the live Clay-defined ramp inside the shadow (Clay stays live).</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Rows</th><th>n</th><th>Actual / shadow</th><th>Actual / shipped</th><th>Shadow vs shipped</th></tr></thead><tbody>' +
        W1.reads.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td>' + r.actOverShadow.toFixed(3) + '</td><td>' + r.actOverShipped.toFixed(3) + '</td><td style="color:' + (r.vsShip > 3 ? '#f85149' : (r.vsShip < -1 ? 'var(--acc)' : 'inherit')) + '">' + w1Pct(r.vsShip) + '</td></tr>'; }).join('') + '</tbody></table></div>';
      html += '<div style="overflow-x:auto;margin-top:6px"><table style="width:auto"><thead><tr><th class="l">Knob</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped → new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        W1.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + w1Col(r.verdict) + '">' + w1Pct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + w1Pct(r.shadowVsShip) + ' → ' + w1Pct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + w1Col(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (W1.rampCandidate) { var rc = W1.rampCandidate; html += '<p class="dim" style="font-size:11px;margin:6px 0"><b>Shadow v2.5</b> buried-rookie ramp ' + esc(JSON.stringify(rc.ramp)) + ': ' + w1Pct(rc.vsRef) + ' vs shadow v2.4 (' + rc.vsRefWins + '/' + rc.years + '), ' + w1Pct(rc.pct) + ' vs shipped (' + rc.wins + '/' + rc.years + '); week 1 ' + w1Pct(rc.wk1VsShip) + ' vs shipped; buried rookies weeks 1-4 ' + w1Pct(rc.buriedVsRef) + ' vs shadow. Forward: all rows ' + w1Pct(rc.forward.vsRef) + ' (' + rc.forward.vsRefWins + '/' + rc.forward.years + '), buried rookies ' + w1Pct(rc.forward.buriedVsRef) + ' (' + rc.forward.buriedWins + '/' + rc.forward.years + '), week-1 rows ' + w1Pct(rc.forward.wk1VsRef) + ' (' + rc.forward.wk1Wins + '/' + rc.forward.years + ').</p>'; }
      if (W1.combined) html += '<p class="dim" style="font-size:11px;margin:6px 0">Not shipped: a TE week-1 level x.9 passes on TE rows (5/7) but forward only 2/5 on its own; a global level, more shrink, heavier market weights and a 1st-string rookie level all fail. ' + W1.combined.map(function (c) { return 'TE x' + c.teM + ' + rookies(' + esc(c.rookies) + ') x' + c.rkM + ': week 1 ' + w1Pct(c.wk1VsRef) + ' (' + c.wk1Wins + '/' + c.years + '), fwd ' + w1Pct(c.fwdWk1VsRef) + ' (' + c.fwdWk1Wins + '/' + c.fwdYears + ')'; }).join(' · ') + '.</p>';
    }
    var Y2 = window.SIM_YR2_BT;
    if (Y2 && Y2.reads) {
      var y2Pct = function (p) { return p == null ? '—' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var y2Col = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">Second-year role growth (backtest_second_year.py, ' + esc(Y2.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(Y2.summary || '') + '</b> Second-year players on shadow v2.5: reads by position / week / depth-chart promotion (last season\'s late string vs now) / rookie-season snap share and trend, then each candidate signal swept LOYO against the shadow. Shipped as shadow v2.6: only the late-snap-share boost (its own rows forward -1.3%, 4/5); the snap trend fails forward, chart promotion adds nothing the market did not already price.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Rows</th><th>n</th><th>Actual / shadow</th><th>Actual / shipped</th><th>Shadow vs shipped</th></tr></thead><tbody>' +
        Y2.reads.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td>' + r.actOverShadow.toFixed(3) + '</td><td>' + r.actOverShipped.toFixed(3) + '</td><td>' + y2Pct(r.vsShip) + '</td></tr>'; }).join('') + '</tbody></table></div>';
      html += '<div style="overflow-x:auto;margin-top:6px"><table style="width:auto"><thead><tr><th class="l">Signal</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped → new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        Y2.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + y2Col(r.verdict) + '">' + y2Pct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + y2Pct(r.shadowVsShip) + ' → ' + y2Pct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + y2Col(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (Y2.pieceForward) html += '<p class="dim" style="font-size:11px;margin:6px 0">Forward, each passing piece alone (2021-25, multiplier picked on earlier seasons): ' + Y2.pieceForward.map(function (f) { return esc(f.label) + ' its rows ' + y2Pct(f.rowsVsRef) + ' (' + f.rowsWins + '/' + f.years + '), 2nd-year rows ' + y2Pct(f.yr2VsRef) + ' (' + f.yr2Wins + '/' + f.years + ')'; }).join(' · ') + '.</p>';
    }
    var TEB = window.SIM_TE_BT;
    if (TEB && TEB.reads) {
      var tePct = function (p) { return p == null ? '—' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var teCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">Tight ends on the Clay-free shadow (backtest_te_layer.py, ' + esc(TEB.updated || '') + ') — nothing to ship</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(TEB.summary || '') + '</b> TE player-weeks on shadow v2.6, read by week, situation, string, age, ADP and last season\'s route participation (share of the team\'s pass plays with the TE on the field, from the play-by-play participation files), then every TE-only knob swept LOYO against the shadow. TEs already sit slightly below Clay; no knob passes.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Rows</th><th>n</th><th>Actual / shadow</th><th>Actual / shipped</th><th>Shadow vs shipped</th></tr></thead><tbody>' +
        TEB.reads.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td>' + r.actOverShadow.toFixed(3) + '</td><td>' + r.actOverShipped.toFixed(3) + '</td><td>' + tePct(r.vsShip) + '</td></tr>'; }).join('') + '</tbody></table></div>';
      html += '<div style="overflow-x:auto;margin-top:6px"><table style="width:auto"><thead><tr><th class="l">Knob</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped → new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        TEB.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + teCol(r.verdict) + '">' + tePct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + tePct(r.shadowVsShip) + ' → ' + tePct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + teCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
    }
    var PD = window.SIM_POOLDEF_BT, NP = window.SIM_NOCLAY_POOL;
    if (PD && PD.rules) {
      var pdPct = function (p) { return p == null ? '—' : (100 * p).toFixed(1) + '%'; };
      html += '<h4 style="margin:14px 0 4px">Clay-free pool definition: who gets a projection without Clay\'s sheet (backtest_pool_definition.py, ' + esc(PD.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(PD.summary || '') + '</b> Membership rules from Clay-free sources, scored 2019-25 on the share of fantasy-relevant player-weeks they contain (STARTER = weekly top QB12 / RB24 / WR36 / TE12 in the full weekly database; ROSTERABLE = top 24 / 48 / 72 / 24). DYN = with in-season adds (anyone who posted a 10-point game joins from the next week). Clay\'s pool is the sheet the engine projects today.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Rule</th><th>Players / season</th><th>Starter weeks</th><th>Starter week 1</th><th>Starter DYN</th><th>Rosterable</th><th>Rosterable DYN</th><th>Points share</th></tr></thead><tbody>' +
        PD.rules.map(function (r) { var hi = /ROOKIE$/.test(r.rule) || /^CLAY/.test(r.rule); return '<tr' + (hi ? ' style="font-weight:600"' : '') + '><td class="l">' + esc(r.rule) + '</td><td>' + r.size + '</td><td>' + pdPct(r.starterAll) + '</td><td>' + pdPct(r.starterWk1) + '</td><td>' + pdPct(r.starterDyn) + '</td><td>' + pdPct(r.rosterAll) + '</td><td>' + pdPct(r.rosterDyn) + '</td><td>' + pdPct(r.ptsShare) + '</td></tr>'; }).join('') + '</tbody></table></div>';
      if (PD.missed) html += '<p class="dim" style="font-size:11px;margin:6px 0">Starters the candidate pool missed most (starter weeks; * = Clay had him): ' + PD.missed.map(function (m) { return m.season + ': ' + m.top.slice(0, 4).map(function (t) { return esc(t.name) + ' ' + esc(t.pos) + ' ' + t.starterWeeks + (t.inClay ? '*' : ''); }).join(', '); }).join(' · ') + '.</p>';
      if (NP && NP.counts) {
        var c = NP.counts;
        html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>2026 Clay-free pool</b> (build_noclay_pool.py, ' + esc(NP.updated || '') + '; ADP ≤ ' + NP.rule.adpMax + ', chart string ≤ ' + NP.rule.chartString + ', ' + esc(NP.rule.hist) + ', rookies pick ≤ ' + NP.rule.rookiePickMax + ', must have a team): <b>' + c.members + ' members</b> vs Clay\'s ' + c.clay + ' skill players — in both ' + c.both + ', pool-only ' + c.poolOnly + ', Clay-only ' + c.clayOnly + '. By position: ' + ['QB', 'RB', 'WR', 'TE'].map(function (ps) { return ps + ' ' + c.byPos[ps].members + ' vs ' + c.byPos[ps].clay; }).join(', ') + '. Sources: ' + Object.keys(c.bySrc).map(function (k) { return k + ' ' + c.bySrc[k]; }).join(', ') + '. Each member carries a history-based per-game stat mix (the comps a Clay-free engine needs). Research only — the engine still projects Clay\'s sheet.</p>';
        if (NP.clayOnly && NP.clayOnly.length) html += '<p class="dim" style="font-size:11px;margin:4px 0">Clay-only (Clay projects, the rule does not; by Clay points): ' + NP.clayOnly.slice(0, 20).map(function (x) { return esc(x.n) + ' ' + esc(x.pos) + ' ' + (x.pts == null ? '' : x.pts); }).join(', ') + (NP.clayOnly.length > 20 ? ' …' : '') + '.</p>';
        if (NP.poolOnly && NP.poolOnly.length) html += '<p class="dim" style="font-size:11px;margin:4px 0">Pool-only (the rule projects, Clay does not; sample): ' + NP.poolOnly.slice(0, 25).map(function (x) { return esc(x.n) + ' ' + esc(x.pos) + ' (' + esc(x.src.join('/')) + ')'; }).join(', ') + (NP.poolOnly.length > 25 ? ' …' : '') + '.</p>';
      }
    }
    var CH = window.SIM_CORR_HORIZONS;
    if (CH && CH.season) {
      var chR = function (r) { return (r >= 0 ? '+' : '') + (+r).toFixed(2); };
      var chCol = function (r) { return Math.abs(r) >= 0.4 ? 'var(--acc)' : (Math.abs(r) < 0.1 ? 'var(--dim)' : 'inherit'); };
      html += '<h4 style="margin:14px 0 4px">What correlates with scoring: season-long vs weekly, by position (research_corr_horizons.py, ' + esc(CH.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px">2019-25. SEASON = one row per player-season (points per game over played weeks) against what was known before week 1. WEEKLY = one row per player-week (weeks 2+) against everything known before kickoff. r = Pearson, rho = Spearman (rank). ADP, draft pick and depth string are "lower = better", so their correlations are negative. Clay\'s preseason number is included as a reference, not a Clay-free input.</p>';
      ['QB', 'RB', 'WR', 'TE'].forEach(function (ps) {
        var S = CH.season[ps] || [], W = CH.weekly[ps] || [], C = CH.compare[ps] || [];
        html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>' + ps + '</b> \u2014 season n ' + (CH.n[ps] || {}).season + ' player-seasons, weekly n ' + (CH.n[ps] || {}).weekly + ' player-weeks</p>';
        html += '<div style="display:flex;gap:18px;flex-wrap:wrap"><div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Season-long: top correlates</th><th>r</th><th>rho</th></tr></thead><tbody>' +
          S.slice(0, 10).map(function (d) { return '<tr><td class="l">' + esc(d.label) + '</td><td style="color:' + chCol(d.r) + '">' + chR(d.r) + '</td><td>' + chR(d.rho) + '</td></tr>'; }).join('') + '</tbody></table></div>' +
          '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Weekly: top correlates</th><th>r</th><th>rho</th></tr></thead><tbody>' +
          W.slice(0, 14).map(function (d) { return '<tr><td class="l">' + esc(d.label) + '</td><td style="color:' + chCol(d.r) + '">' + chR(d.r) + '</td><td>' + chR(d.rho) + '</td></tr>'; }).join('') + '</tbody></table></div>' +
          '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Same preseason feature, both horizons</th><th>season r</th><th>weekly r</th></tr></thead><tbody>' +
          C.slice(0, 12).map(function (d) { return '<tr><td class="l">' + esc(d.label) + '</td><td style="color:' + chCol(d.season_r) + '">' + chR(d.season_r) + '</td><td style="color:' + chCol(d.weekly_r) + '">' + chR(d.weekly_r) + '</td></tr>'; }).join('') + '</tbody></table></div></div>';
      });
    }
    var QV = window.SIM_QBVEG_BT;
    if (QV && QV.sweeps) {
      var qvPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var qvCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">QB implied-total layer on the Clay-free shadow (backtest_qb_vegas.py, ' + esc(QV.updated || '') + ') \u2014 the live elasticity already fits</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(QV.summary || '') + '</b> The team implied total is the top weekly QB correlate, so the question was whether the shadow (history + market base) wants a stronger Vegas elasticity than the Clay base does. Elasticity swept on QB rows LOYO against shadow v2.6, by week band, with a spread term, the QB prior strength, the other positions as a control, and the same sweep on the shipped Clay blend as a reference.</p>';
      if (QV.reads) html += '<p class="dim" style="font-size:11px;margin:4px 0">QB actual / shadow (actual / shipped) by game: ' + QV.reads.map(function (r) { return esc(r.label) + ' n' + r.n + ' ' + r.actOverShadow.toFixed(3) + ' (' + r.actOverShipped.toFixed(3) + '), ' + r.meanAct.toFixed(1) + ' pts'; }).join(' \u00b7 ') + '.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Sweep</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped \u2192 new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        QV.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + qvCol(r.verdict) + '">' + qvPct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + qvPct(r.shadowVsShip) + ' \u2192 ' + qvPct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + qvCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (QV.candidate && QV.candidate.forward) html += '<p class="dim" style="font-size:11px;margin:6px 0">Best candidate (e ' + QV.candidate.e + ', P ' + QV.candidate.P + '): QB rows ' + qvPct(QV.candidate.qbVsRef) + ' vs shadow (' + QV.candidate.qbWins + '/' + QV.candidate.years + '), forward ' + qvPct(QV.candidate.forward.qbVsRef) + ' (' + QV.candidate.forward.qbWins + '/' + QV.candidate.forward.years + '). Not shipped: e stays .25 for QBs on the shadow as on the Clay base.</p>';
    }
    var RV = window.SIM_RBVEG_BT;
    if (RV && RV.sweeps) {
      var rvPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var rvCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">RB elasticity layer on the Clay-free shadow (backtest_rb_vegas.py, ' + esc(RV.updated || '') + ') \u2014 flat, no change</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(RV.summary || '') + '</b> RB Vegas elasticity (live .5) swept on RB rows LOYO against shadow v2.6, by week band and depth string, with a spread term for game script, and the same sweep on the shipped Clay blend as a reference.</p>';
      if (RV.reads) html += '<p class="dim" style="font-size:11px;margin:4px 0">RB actual / shadow (actual / shipped) by game: ' + RV.reads.map(function (r) { return esc(r.label) + ' n' + r.n + ' ' + r.actOverShadow.toFixed(3) + ' (' + r.actOverShipped.toFixed(3) + '), ' + r.meanAct.toFixed(1) + ' pts'; }).join(' \u00b7 ') + '.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Sweep</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped \u2192 new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        RV.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + rvCol(r.verdict) + '">' + rvPct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + rvPct(r.shadowVsShip) + ' \u2192 ' + rvPct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + rvCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (RV.candidate && RV.candidate.forward) html += '<p class="dim" style="font-size:11px;margin:6px 0">Best candidate (e ' + RV.candidate.e + ', spread k ' + RV.candidate.k + '): RB rows ' + rvPct(RV.candidate.rbVsRef) + ' vs shadow (' + RV.candidate.rbWins + '/' + RV.candidate.years + '), forward ' + rvPct(RV.candidate.forward.rbVsRef) + ' (' + RV.candidate.forward.rbWins + '/' + RV.candidate.forward.years + '). Not shipped: .5 stays.</p>';
    }
    var CA = window.SIM_CORR_ADV;
    if (CA && CA.season) {
      var caR = function (r) { return (r >= 0 ? '+' : '') + (+r).toFixed(2); };
      var caCol = function (r) { return Math.abs(r) >= 0.4 ? 'var(--acc)' : (Math.abs(r) < 0.1 ? 'var(--dim)' : 'inherit'); };
      html += '<h4 style="margin:14px 0 4px">Advanced stats, route share and alignment-by-offense: correlations with scoring, by position (research_corr_advanced.py, ' + esc(CA.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px">2019-25. PFF season files (route rate, YPRR, targets per route, aDOT, route / offense / run grades, slot / wide / inline rates, YAC, drops, contested catches; RB yards after contact, elusive rating, breakaway %, gap-scheme share), route share from the play-by-play participation files (season-to-date and last 3), team pass plays / 11- and 12-personnel / shotgun rates (prior year and season-to-date), and alignment x offense interactions. The basics from the first study (prior-year PPG, target / carry share, season-to-date PPG) are shown in each list for reference. r = Pearson, rho = Spearman.</p>';
      ['QB', 'RB', 'WR', 'TE'].forEach(function (ps) {
        var S = CA.season[ps] || [], W = CA.weekly[ps] || [], b = CA.beats[ps] || {};
        html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>' + ps + '</b> \u2014 ' + (b.seasonBestAdv ? 'best advanced at season: ' + esc(b.seasonBestAdv.label) + ' ' + caR(b.seasonBestAdv.r) + ' vs prior-year PPG ' + (b.seasonBasic ? caR(b.seasonBasic.r) : '\u2014') : '') + (b.weeklyBestAdv ? '; weekly: ' + esc(b.weeklyBestAdv.label) + ' ' + caR(b.weeklyBestAdv.r) + ' vs ' + esc(b.weeklyBasic.label.replace(' (basic, for reference)', '')) + ' ' + caR(b.weeklyBasic.r) : '') + '</p>';
        html += '<div style="display:flex;gap:18px;flex-wrap:wrap"><div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Season-long</th><th>r</th><th>rho</th><th>n</th></tr></thead><tbody>' +
          S.slice(0, 12).map(function (d) { return '<tr><td class="l">' + esc(d.label) + '</td><td style="color:' + caCol(d.r) + '">' + caR(d.r) + '</td><td>' + caR(d.rho) + '</td><td class="dim">' + d.n + '</td></tr>'; }).join('') + '</tbody></table></div>' +
          '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Weekly</th><th>r</th><th>rho</th><th>n</th></tr></thead><tbody>' +
          W.slice(0, 14).map(function (d) { return '<tr><td class="l">' + esc(d.label) + '</td><td style="color:' + caCol(d.r) + '">' + caR(d.r) + '</td><td>' + caR(d.rho) + '</td><td class="dim">' + d.n + '</td></tr>'; }).join('') + '</tbody></table></div></div>';
      });
      html += '<p class="dim" style="font-size:11px;margin:6px 0">Read: prior-year PPG stays the best single season-long correlate everywhere; targets volume and the PFF route / offense grades sit just behind for WR/TE (.64-.66 / .57-.65), YPRR and targets per route next (.48-.58). Alignment is weak on its own (TE inline -.24, TE slot +.23, WR slot -.10) and team personnel / pass volume / shotgun rates are near zero for skill players; route share x team pass plays is just routes per game. Weekly, route share (.31-.38) trails target share (.43) and season PPG, but a prior-year PFF route grade (.38 WR) is nearly as good as target share before the season\'s own data accumulates. QB advanced = rushing (elusive rating .35): mobile QBs score more; QB route share is only the starter flag.</p>';
    }
    var PG = window.SIM_PFFGRADE_BT;
    if (PG && PG.sweeps) {
      var pgPct = function (p) { return p == null ? '—' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var pgCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">Prior-year PFF route grade on the Clay-free shadow (backtest_pff_route_grade.py, ' + esc(PG.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(PG.summary || '') + '</b> The prior season\'s PFF route grade (>= 50 routes) as a shadow-prior ingredient for WR / TE (RB control): tercile multipliers, a grade-to-points curve blend (all weeks and weeks 1-4 only), young high-grade players, and the grade RESIDUAL beyond what the history prior already implies. Shipped as shadow v2.7: WR residual top tercile x1.1 only (Clay stays live).</p>';
      if (PG.reads) html += '<p class="dim" style="font-size:11px;margin:4px 0">Actual / shadow prior by grade tercile (weeks 1-8, vets): ' + PG.reads.map(function (r) { return esc(r.pos) + ' ' + esc(r.tercile) + ' n' + r.n + ' ' + r.actOverPrior.toFixed(3); }).join(' · ') + '.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Sweep</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped → new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        PG.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + pgCol(r.verdict) + '">' + pgPct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + pgPct(r.shadowVsShip) + ' → ' + pgPct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + pgCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (PG.candidate && PG.candidate.forward) html += '<p class="dim" style="font-size:11px;margin:6px 0">Candidate (' + esc(Object.keys(PG.candidate.cfg || {}).map(function (k) { return k.trim() + ' = ' + PG.candidate.cfg[k]; }).join(', ')) + '): affected rows n' + PG.candidate.affectedN + ' ' + pgPct(PG.candidate.affectedVsRef) + ' vs shadow (' + PG.candidate.affectedWins + '/' + PG.candidate.years + '), forward ' + pgPct(PG.candidate.forward.affectedVsRef) + ' (' + PG.candidate.forward.affectedWins + '/' + PG.candidate.forward.years + '); all rows ' + pgPct(PG.candidate.vsRef) + '.' + (PG.engine ? ' Engine: WR residual = grade − (' + PG.engine.WR.c0 + ' + ' + PG.engine.WR.c1 + ' × prior half-PPR), boost x' + PG.engine.WR.mult + ' above ' + PG.engine.WR.cut + '.' : '') + '</p>';
    }
    var TG = window.SIM_TEGRADE_BT;
    if (TG && TG.sweeps) {
      var tgPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var tgCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">TE route grade layer (backtest_te_route_grade.py, ' + esc(TG.updated || '') + ') \u2014 REJECTED</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(TG.summary || '') + '</b> The TE forms of the route-grade idea on their own: residual top tercile and top half, bottom tercile, raw grade, early-weeks residual, curve blends, and the two lean pieces combined. Graded LOYO against shadow v2.6, then forward. Nothing reaches five seasons and the best form reverses forward.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Sweep</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped \u2192 new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        TG.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + tgCol(r.verdict) + '">' + tgPct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + tgPct(r.shadowVsShip) + ' \u2192 ' + tgPct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + tgCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (TG.candidate && TG.candidate.forward) html += '<p class="dim" style="font-size:11px;margin:6px 0">Best form (' + esc(TG.candidate.label) + ' = ' + TG.candidate.value + '): affected rows ' + tgPct(TG.candidate.affectedVsRef) + ' vs shadow (' + TG.candidate.affectedWins + '/' + TG.candidate.years + '), FORWARD ' + tgPct(TG.candidate.forward.affectedVsRef) + ' (' + TG.candidate.forward.affectedWins + '/' + TG.candidate.forward.years + '). Not shipped.</p>';
    }
    var WC = window.SIM_WRCURVE_BT;
    if (WC && WC.sweeps) {
      var wcPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var wcCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">WR route-grade curve blend (backtest_wr_curve.py, ' + esc(WC.updated || '') + ') \u2014 REJECTED</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(WC.summary || '') + '</b> The grade-to-points curve blended into the WR prior in every form: all rows, high-residual rows, young receivers, weeks 1-4 only, as a replacement for part of the market weight, and a curve of grade plus routes volume. Graded LOYO against shadow v2.6 (which already carries the v2.7 residual boost\'s inputs), then forward. Nothing passes; the residual boost already holds what the grade knows.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Form</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped \u2192 new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        WC.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + wcCol(r.verdict) + '">' + wcPct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + wcPct(r.shadowVsShip) + ' \u2192 ' + wcPct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + wcCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (WC.candidate && WC.candidate.forward) html += '<p class="dim" style="font-size:11px;margin:6px 0">Best form (' + esc(WC.candidate.label) + ' = ' + WC.candidate.value + '): affected rows ' + wcPct(WC.candidate.affectedVsRef) + ' vs shadow (' + WC.candidate.affectedWins + '/' + WC.candidate.years + '), forward ' + wcPct(WC.candidate.forward.affectedVsRef) + ' (' + WC.candidate.forward.affectedWins + '/' + WC.candidate.forward.years + '). Not shipped.</p>';
    }
    var RVL = window.SIM_ROUTESVOL_BT;
    if (RVL && RVL.sweeps) {
      var rvlPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var rvlCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">Prior-year routes volume on the Clay-free shadow (backtest_routes_volume.py, ' + esc(RVL.updated || '') + ') \u2014 REJECTED</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(RVL.summary || '') + '</b> Last season\'s route count (PFF, >= 50 routes) as a shadow-prior ingredient for WR / TE / RB: tercile levels, a routes-to-points curve (all weeks and weeks 1-4), young high-route players, and routes above / below what the history prior implies. LOYO against shadow v2.6. Nothing passes: the prior already carries the opportunity that routes measure.</p>';
      if (RVL.reads) html += '<p class="dim" style="font-size:11px;margin:4px 0">Actual / shadow prior by routes tercile (weeks 1-8, vets): ' + RVL.reads.map(function (r) { return esc(r.pos) + ' ' + esc(r.tercile) + ' n' + r.n + ' ' + r.actOverPrior.toFixed(3); }).join(' \u00b7 ') + '.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Sweep</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped \u2192 new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        RVL.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + rvlCol(r.verdict) + '">' + rvlPct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + rvlPct(r.shadowVsShip) + ' \u2192 ' + rvlPct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + rvlCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
    }
    var TLR = window.SIM_TELOWROUTE_BT;
    if (TLR && TLR.sweeps) {
      var tlPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var tlCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">Low-route tight ends (backtest_te_lowroute.py, ' + esc(TLR.updated || '') + ') \u2014 REJECTED</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(TLR.summary || '') + '</b> The blocking-tight-end read in every form: bottom-tercile routes, bottom-tercile PFF route RATE (share of the team\'s pass plays he runs a route on), both together, low routes with a low grade, early weeks only, by depth string, and a route-rate curve. LOYO against shadow v2.6, then forward. The route rate carries nothing and the routes dock reverses forward.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Form</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped \u2192 new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        TLR.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + tlCol(r.verdict) + '">' + tlPct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + tlPct(r.shadowVsShip) + ' \u2192 ' + tlPct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + tlCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (TLR.candidate && TLR.candidate.forward) html += '<p class="dim" style="font-size:11px;margin:6px 0">Best form (' + esc(TLR.candidate.label) + ' = ' + TLR.candidate.value + '): affected rows ' + tlPct(TLR.candidate.affectedVsRef) + ' vs shadow (' + TLR.candidate.affectedWins + '/' + TLR.candidate.years + '), FORWARD ' + tlPct(TLR.candidate.forward.affectedVsRef) + ' (' + TLR.candidate.forward.affectedWins + '/' + TLR.candidate.forward.years + '). Not shipped.</p>';
    }
    var WY = window.SIM_WRYOUNG_BT;
    if (WY && WY.sweeps) {
      var wyPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var wyCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">Young high-route receivers (backtest_wr_young_routes.py, ' + esc(WY.updated || '') + ') \u2014 not shipped</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(WY.summary || '') + '</b> The young high-route WR read in every form: routes vs route rate, the breakout read (high routes, low prior), with a high grade, by experience year, early weeks only, and all ages as a control. LOYO against shadow v2.6, then forward. The one passing form fails forward and overlaps the v2.7 grade boost.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Form</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped \u2192 new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        WY.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + wyCol(r.verdict) + '">' + wyPct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + wyPct(r.shadowVsShip) + ' \u2192 ' + wyPct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + wyCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (WY.candidate && WY.candidate.forward) html += '<p class="dim" style="font-size:11px;margin:6px 0">Best form (' + esc(WY.candidate.label) + ' = ' + WY.candidate.value + '): affected rows n' + WY.candidate.affectedN + ' ' + wyPct(WY.candidate.affectedVsRef) + ' vs shadow (' + WY.candidate.affectedWins + '/' + WY.candidate.years + '), FORWARD ' + wyPct(WY.candidate.forward.affectedVsRef) + ' (' + WY.candidate.forward.affectedWins + '/' + WY.candidate.forward.years + '). Not shipped: forward under the bar, and these are largely the receivers the v2.7 grade residual already boosts.</p>';
    }
    var W2R = window.SIM_WRYR2_BT;
    if (W2R && W2R.sweeps) {
      var w2Pct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var w2Col = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">2nd-year high-route receivers (backtest_wr_yr2_routes.py, ' + esc(W2R.updated || '') + ') \u2014 REJECTED</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(W2R.summary || '') + '</b> The 2nd-year receiver who ran a full-time route load as a rookie, in every threshold form (tercile, median, 300 and 400 routes, route rate), with and without the grade, 2nd year alone vs 2nd + 3rd, and controls. LOYO against shadow v2.6, then forward. The 155-row lean does not survive a wider threshold; the one passing form is 77 rows and fails forward.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Form</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped \u2192 new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        W2R.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + w2Col(r.verdict) + '">' + w2Pct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + w2Pct(r.shadowVsShip) + ' \u2192 ' + w2Pct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + w2Col(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (W2R.candidate && W2R.candidate.forward) html += '<p class="dim" style="font-size:11px;margin:6px 0">Best form (' + esc(W2R.candidate.label) + ' = ' + W2R.candidate.value + '): affected rows n' + W2R.candidate.affectedN + ' ' + w2Pct(W2R.candidate.affectedVsRef) + ' vs shadow (' + W2R.candidate.affectedWins + '/' + W2R.candidate.years + '), FORWARD ' + w2Pct(W2R.candidate.forward.affectedVsRef) + ' (' + W2R.candidate.forward.affectedWins + '/' + W2R.candidate.forward.years + '). Not shipped: too few rows and fails forward.</p>';
    }
    var W2L = window.SIM_WRYR2LOW_BT;
    if (W2L && W2L.sweeps) {
      var wlPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var wlCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">2nd-year low-route receivers (backtest_wr_yr2_lowroutes.py, ' + esc(W2L.updated || '') + ') \u2014 REJECTED, v2.6 boost confirmed</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(W2L.summary || '') + '</b> The 2nd-year receiver with a bottom-tercile rookie route count, split by whether the v2.6 part-timer boost (x1.2, under 40% late snaps) already applies, plus route rate, absolute thresholds, grade splits and 2nd + 3rd year. LOYO against shadow v2.6, then forward. The lean was a mixture: docking the boosted rows hurts, docking the rest does nothing.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Form</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped \u2192 new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        W2L.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + wlCol(r.verdict) + '">' + wlPct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + wlPct(r.shadowVsShip) + ' \u2192 ' + wlPct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + wlCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (W2L.candidate && W2L.candidate.forward) html += '<p class="dim" style="font-size:11px;margin:6px 0">Best form (' + esc(W2L.candidate.label) + ' = ' + W2L.candidate.value + '): affected rows n' + W2L.candidate.affectedN + ' ' + wlPct(W2L.candidate.affectedVsRef) + ' vs shadow (' + W2L.candidate.affectedWins + '/' + W2L.candidate.years + '), FORWARD ' + wlPct(W2L.candidate.forward.affectedVsRef) + ' (' + W2L.candidate.forward.affectedWins + '/' + W2L.candidate.forward.years + '). Not shipped.</p>';
    }
    var WLG = window.SIM_WRLOWGRADE_BT;
    if (WLG && WLG.sweeps) {
      var lgPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var lgCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">Bottom-tercile low-grade WR boost (backtest_wr_lowgrade_boost.py, ' + esc(WLG.updated || '') + ') \u2014 REJECTED, with a placebo</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(WLG.summary || '') + '</b> A subgroup of a subgroup (2nd-year, bottom-tercile rookie routes, low route grade; 304 rows), tested with two guards: the same group for 3rd-year-plus and for all receivers (does it generalise?), and a PLACEBO of 20 random 2nd-year groups of the same size run through the same LOYO procedure (what does noise look like?).</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Form</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped \u2192 new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        WLG.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + lgCol(r.verdict) + '">' + lgPct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + lgPct(r.shadowVsShip) + ' \u2192 ' + lgPct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + lgCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (WLG.placebo) html += '<p class="dim" style="font-size:11px;margin:6px 0"><b>Placebo</b>: 20 random 2nd-year WR groups of n ' + WLG.placebo.n + ', same procedure: mean ' + lgPct(WLG.placebo.meanPct) + ', best ' + lgPct(WLG.placebo.bestPct) + '; ' + Math.round(100 * WLG.placebo.share_le_minus03) + '% of random groups reach \u22120.3%, ' + Math.round(100 * WLG.placebo.share_wins_ge4) + '% get 4+ seasons better, ' + Math.round(100 * WLG.placebo.share_wins_ge5) + '% get 5+. A "lean" on a few hundred rows is inside this noise; the 5-season bar is what separates a layer from a coincidence.' + (WLG.candidate && WLG.candidate.forward ? ' Candidate forward ' + lgPct(WLG.candidate.forward.affectedVsRef) + ' (' + WLG.candidate.forward.affectedWins + '/' + WLG.candidate.forward.years + '). Not shipped.' : '') + '</p>';
    }
    var OL = window.SIM_OUTLIERS;
    if (OL && OL.rows) {
      var olFmt = function (v) { return (v >= 0 ? '+' : '') + (+v).toFixed(1); };
      var hi = OL.rows.filter(function (r) { return r.diff > 0; }).sort(function (a, b) { return b.diff - a.diff; }).slice(0, 12), lo = OL.rows.filter(function (r) { return r.diff < 0; }).sort(function (a, b) { return a.diff - b.diff; }).slice(0, 12);
      html += '<h4 style="margin:14px 0 4px">Week ' + OL.week + ': where the Clay-free shadow disagrees with the live number (outliers_week.js, ' + esc(String(OL.updated || '').slice(0, 16).replace('T', ' ')) + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px">Live = the shipped Clay-based mean (half-PPR); shadow = ncMean, the Clay-free base with the same layers. Tags are the shadow\'s own prior sources (hist / l8 = own history, adp = market curve, opp = opportunity prior, dock2/3 = depth-string dock, qb2 = backup QB on the chart, ramp = buried-rookie ramp, yr2lo = 2nd-year part-timer boost, grade = route-grade residual, shr = shrink). Rerun any week: node outliers_week.js N.</p>';
      var tbl = function (title, rs) { return '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">' + title + '</th><th>Pos</th><th>Tm</th><th>Live</th><th>Shadow</th><th>Diff</th><th class="l">Shadow prior</th></tr></thead><tbody>' + rs.map(function (r) { return '<tr><td class="l">' + esc(r.n) + '</td><td>' + esc(r.pos) + '</td><td class="dim">' + esc(r.tm) + '</td><td>' + r.live.toFixed(1) + '</td><td>' + r.nc.toFixed(1) + '</td><td style="color:' + (r.diff > 0 ? 'var(--acc)' : '#f85149') + '">' + olFmt(r.diff) + '</td><td class="l dim" style="font-size:10px">' + esc(r.src) + '</td></tr>'; }).join('') + '</tbody></table></div>'; };
      html += '<div style="display:flex;gap:18px;flex-wrap:wrap">' + tbl('Shadow HIGHER than live', hi) + tbl('Shadow LOWER than live', lo) + '</div>';
      html += '<p class="dim" style="font-size:11px;margin:6px 0">' + ['QB', 'RB', 'WR', 'TE'].map(function (ps) { var pr = OL.rows.filter(function (r) { return r.pos === ps; }); if (!pr.length) return ps + ' —'; var mean = pr.reduce(function (s, r) { return s + r.diff; }, 0) / pr.length, mad = pr.reduce(function (s, r) { return s + Math.abs(r.diff); }, 0) / pr.length; return ps + ' n' + pr.length + ' avg ' + olFmt(mean) + ', mean |diff| ' + mad.toFixed(2) + ', 3+ pts apart: ' + pr.filter(function (r) { return Math.abs(r.diff) >= 3; }).length; }).join(' · ') + '.</p>';
    }
    var QD = window.SIM_QD_BT;
    if (QD && QD.sweeps) {
      var qdPct = function (p) { return p == null ? '—' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var qdCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">Questionable / Doubtful on the Clay-free shadow (backtest_qd_shadow.py, ' + esc(QD.updated || '') + ') — shadow v2.10: returning-player dock</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(QD.summary || '') + '</b> Each game-week designation graded on the shadow with the live docks (Doubtful x.5, Questionable + DNP x.75) already applied, so every sweep is the EXTRA multiplier the shadow wants; split by practice status, starter vs backup, position, and whether the player played last week. Official reports 2019-25. Shipped: Questionable and missed last week x.85 (any practice status).</p>';
      if (QD.reads) html += '<p class="dim" style="font-size:11px;margin:4px 0">Actual / shadow by designation: ' + QD.reads.filter(function (r) { return r.cls !== 'none'; }).map(function (r) { return esc(r.cls) + ' ' + esc(r.split) + ' n' + r.n + ' ' + r.actOverShadow.toFixed(3); }).join(' · ') + '.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Class</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped → new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        QD.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + qdCol(r.verdict) + '">' + qdPct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + qdPct(r.shadowVsShip) + ' → ' + qdPct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + qdCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (QD.pieceForward && QD.pieceForward.length) html += '<p class="dim" style="font-size:11px;margin:6px 0">Forward (2021-25, multiplier picked on earlier seasons): ' + QD.pieceForward.map(function (f) { return esc(f.label) + ' its rows ' + qdPct(f.rowsVsRef) + ' (' + f.rowsWins + '/' + f.years + '), all rows ' + qdPct(f.allVsRef) + ' (' + f.allWins + '/' + f.years + ')'; }).join(' · ') + '.</p>';
    }
    var VA = window.SIM_VACATED_BT;
    if (VA && VA.sweeps) {
      var vaPct = function (p) { return p == null ? '—' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var vaCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">Vacated role on the Clay-free shadow (backtest_vacated_shadow.py, ' + esc(VA.updated || '') + ') — shadow v2.11: boost^0.75</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(VA.summary || '') + '</b> The live layer redistributes a zeroed player\'s share to healthy teammates by depth rank, and the shadow inherited that multiplier at full strength. Graded on the shadow with the share-rebuilt multiplier (Clay-free by construction): shadow x boost^k, by position and by size of the boost, then forward. The shadow wants k = .75 (RB/WR/TE); backup-QB inheritance (11 rows) keeps the live strength. Since v2.12 the redistribution is computed in shadow units (lost = the out teammates’ shadow-as-healthy number; QB 85% to the next available QB, RB/WR/TE 60% by own x depth weight, x.75, gain capped at own) via a cached team pass; tag +vacx.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Sweep</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs shipped → new</th><th>Picks (k)</th><th>Verdict</th></tr></thead><tbody>' +
        VA.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + vaCol(r.verdict) + '">' + vaPct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + vaPct(r.shadowVsShip) + ' → ' + vaPct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + vaCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (VA.candidate && VA.candidate.forward) html += '<p class="dim" style="font-size:11px;margin:6px 0">Candidate boost^' + VA.candidate.k + ': boosted rows n' + VA.candidate.affectedN + ' ' + vaPct(VA.candidate.affectedVsRef) + ' vs shadow (' + VA.candidate.affectedWins + '/' + VA.candidate.years + '), all rows ' + vaPct(VA.candidate.vsRef) + ' (' + VA.candidate.vsRefWins + '/' + VA.candidate.years + '), ' + vaPct(VA.candidate.pct) + ' vs shipped; forward boosted rows ' + vaPct(VA.candidate.forward.affectedVsRef) + ' (' + VA.candidate.forward.affectedWins + '/' + VA.candidate.forward.years + '), all rows ' + vaPct(VA.candidate.forward.vsRef) + '.</p>';
    }
    var CS = window.SIM_CLAYSEG;
    if (CS && CS.families) {
      var csPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var csTag = function (r) { return (r.pct > 0.5 && r.wins <= Math.floor(r.years / 2)) ? 'CLAY' : ((r.pct < -0.5 && r.wins > Math.floor(r.years / 2)) ? 'SHADOW' : 'even'); };
      var csCol = function (t) { return t === 'SHADOW' ? 'var(--acc)' : (t === 'CLAY' ? '#f85149' : 'inherit'); };
      var csRow = function (r, pre) { var t = csTag(r); return '<tr><td class="l">' + (pre ? '<span class="dim">' + esc(pre) + '</span> ' : '') + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td>' + r.actMean.toFixed(1) + '</td><td style="color:' + csCol(t) + '">' + csPct(r.pct) + '</td><td>' + r.wins + '/' + r.years + '</td><td class="dim">' + r.biasShip.toFixed(3) + ' / ' + r.biasShad.toFixed(3) + '</td><td style="color:' + csCol(t) + '"><b>' + t + '</b></td></tr>'; };
      var csHead = '<thead><tr><th class="l">Player type</th><th>n</th><th>Actual</th><th>Shadow vs Clay (MSE)</th><th>Seasons shadow wins</th><th>Bias act/proj Clay / shadow</th><th>Edge</th></tr></thead>';
      html += '<h4 style="margin:14px 0 4px">Where Clay beats the Clay-free shadow, by player type (research_clay_vs_shadow.py, ' + esc(CS.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(CS.summary || '') + '</b> Same 2019-25 harness as the ladder (' + (CS.overall ? CS.overall.n : '') + ' Clay-pool player-weeks, half-PPR, Vegas x FPA on both sides): shipped = P=5 blend of Clay\u2019s season PPG with season-to-date; shadow = the v2.11 harness form. Negative = shadow better. CLAY = Clay better by more than 0.5% and in most seasons. Caveat: Clay\u2019s harness PPG is season points over 17 games, so his blend runs low on players who miss games (bias above 1); part of the shadow\u2019s edge at the bottom of the pool is that denominator, not information.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto">' + csHead + '<tbody>' + CS.families.map(function (f) { return f.rows.map(function (r) { return csRow(r, f.name); }).join(''); }).join('') + '</tbody></table></div>';
      if (CS.byPos) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>By position</b> (Clay vs the player\u2019s own history, season-to-date vs Clay after 3+ games, string, ADP):</p><div style="overflow-x:auto"><table style="width:auto">' + csHead + '<tbody>' + Object.keys(CS.byPos).map(function (ps) { return CS.byPos[ps].map(function (r) { return csRow(r, ps); }).join(''); }).join('') + '</tbody></table></div>';
    }
    var BC = window.SIM_BEATCLAY_BT;
    if (BC && BC.sweeps) {
      var bcPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var bcCol = function (v) { return v === 'PASS' ? 'var(--acc)' : (v === 'lean' ? 'inherit' : '#f85149'); };
      html += '<h4 style="margin:14px 0 4px">Beat Clay where he still wins (backtest_beat_clay.py, ' + esc(BC.updated || '') + ') \u2014 shadow v2.14: no-chart veterans x0.8, first 4 games</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(BC.summary || '') + '</b> Five Clay-free fixes for the cuts Clay still won (week 1, no chart entry, WRs with no history, TEs the market rates far above their history), each LOYO vs the shadow itself. Week 1 cannot be bought from the market: leaning on the ADP curve or shrinking to the position mean both lose. The one repair is veterans with no depth-chart entry in their first 4 games of a season (late signings, camp bodies, returning vets the chart has not placed): the shadow over-projects them by ~25% and a x0.8 dock fixes it; after 4 games the data has already fixed it (x1.0). Forward on that subset -14.6% (4/5); 0 of 300 random same-size groups reach the bar. Kill: window.SIM_NC_NOCHART = false.</p>';
      if (BC.gaps && BC.gaps.length) html += '<p class="dim" style="font-size:11px;margin:0 0 6px">The gaps before the fix (shadow vs Clay, MSE): ' + BC.gaps.map(function (r) { return esc(r.label) + ' n' + r.n + ' ' + bcPct(r.pct) + ' (shadow ' + r.wins + '/' + r.years + ')'; }).join(' \u00b7 ') + '.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Sweep</th><th>n</th><th>LOYO vs shadow</th><th>Seasons better</th><th>Shadow vs Clay \u2192 new</th><th>Picks</th><th>Verdict</th></tr></thead><tbody>' +
        BC.sweeps.map(function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + bcCol(r.verdict) + '">' + bcPct(r.loyoPct) + '</td><td>' + r.wins + '/' + r.years + '</td><td>' + bcPct(r.shadowVsShip) + ' \u2192 ' + bcPct(r.newVsShip) + '</td><td class="dim" style="font-size:10px">' + esc(r.picks.join(' ')) + '</td><td style="color:' + bcCol(r.verdict) + '"><b>' + esc(r.verdict) + '</b></td></tr>'; }).join('') + '</tbody></table></div>';
      if (BC.forward && BC.forward.length) html += '<p class="dim" style="font-size:11px;margin:6px 0">Forward (2021-25, picked on earlier seasons): ' + BC.forward.map(function (f) { return esc(f.label) + ' n' + f.n + ' ' + bcPct(f.pct) + ' (' + f.wins + '/' + f.years + ')'; }).join(' \u00b7 ') + '.</p>';
    }
    var SL = window.SIM_SEASON_BT;
    if (SL && SL.models) {
      var slPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(1) + '%'; };
      var slCol = function (r) { return (r.pct <= -3 && r.wins > r.years / 2) ? 'var(--acc)' : (r.pct >= 3 ? '#f85149' : 'inherit'); };
      var slRow = function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td>' + r.mse.toFixed(2) + ' / ' + r.mseClay.toFixed(2) + '</td><td style="color:' + slCol(r) + '"><b>' + slPct(r.pct) + '</b></td><td>' + r.wins + '/' + r.years + '</td><td>' + r.rho.toFixed(3) + ' / ' + r.rhoClay.toFixed(3) + '</td><td>' + r.hit.toFixed(2) + ' / ' + r.hitClay.toFixed(2) + '</td><td class="dim">' + r.bias.toFixed(3) + '</td></tr>'; };
      var slHead = '<thead><tr><th class="l">Prior</th><th>n</th><th>MSE ours / Clay</th><th>vs Clay</th><th>Seasons won</th><th>Rank corr ours / Clay</th><th>Top-N hit ours / Clay</th><th>Bias</th></tr></thead>';
      html += '<h4 style="margin:14px 0 4px">Season-long: Clay\u2019s sheet vs Clay-free preseason priors (backtest_season_long.py, ' + esc(SL.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(SL.summary || '') + '</b> One row per player-season 2019-25 on Clay\u2019s pool (' + (SL.n && SL.n.all) + '), target = actual full-season half-PPR points per game (4+ games), games-weighted MSE; Clay = his season points over his projected games. Every candidate is walk-forward: hand priors use leave-one-year-out constants, learned priors are fit per position on the other six seasons, and the FORWARD block fits on earlier seasons only (2021-25). Rank corr = Spearman inside each season x position; top-N hit = share of the actual top 24 (TE 12) the prior had in its top 24. Read: the small ridge on ADP, history, age, draft pick and week-1 string beats Clay; every richer feature set (coach, OL, xFP, PFF advanced) overfits 1,400 rows and loses forward.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto">' + slHead + '<tbody>' + SL.models.map(slRow).join('') + '</tbody></table></div>';
      if (SL.forward && SL.forward.length) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>Forward 2021-25</b> (fit on earlier seasons only):</p><div style="overflow-x:auto"><table style="width:auto">' + slHead + '<tbody>' + SL.forward.map(slRow).join('') + '</tbody></table></div>';
      if (SL.byPos) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>By position</b> (leave-one-year-out):</p><div style="overflow-x:auto"><table style="width:auto">' + slHead + '<tbody>' + Object.keys(SL.byPos).map(function (ps) { return SL.byPos[ps].map(slRow).join(''); }).join('') + '</tbody></table></div>';
      if (SL.segments && SL.segments.length) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>Segments</b> (ridge basic vs Clay):</p><div style="overflow-x:auto"><table style="width:auto">' + slHead + '<tbody>' + SL.segments.map(slRow).join('') + '</tbody></table></div>';
      if (SL.features) html += '<p class="dim" style="font-size:11px;margin:6px 0">Strongest standardized ridge coefficients (full feature set, whole sample): ' + Object.keys(SL.features).map(function (ps) { return '<b>' + ps + '</b> ' + SL.features[ps].slice(0, 6).map(function (f) { return esc(f.feat) + ' ' + (f.coef >= 0 ? '+' : '') + f.coef.toFixed(2); }).join(', '); }).join(' \u00b7 ') + '.</p>';
    }
    var LP = window.SIM_LPRIOR_BT;
    if (LP && LP.stages) {
      var lpPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var lpCol = function (v, w, y) { return (v <= -0.3 && w > y / 2) ? 'var(--acc)' : (v >= 0.3 ? '#f85149' : 'inherit'); };
      var lpRow = function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + lpCol(r.vsShadow, r.shadowWins, r.years) + '"><b>' + lpPct(r.vsShadow) + '</b> (' + r.shadowWins + '/' + r.years + ')</td><td style="color:' + lpCol(r.vsClay, r.clayWins, r.years) + '">' + lpPct(r.vsClay) + ' (' + r.clayWins + '/' + r.years + ')</td><td class="dim">' + lpPct(r.shadowVsClay) + '</td></tr>'; };
      var lpHead = '<thead><tr><th class="l">Cut</th><th>n</th><th>vs shadow (seasons won)</th><th>vs Clay blend</th><th>shadow alone vs Clay</th></tr></thead>';
      html += '<h4 style="margin:14px 0 4px">Learned season prior inside the weekly shadow, week 1 included (backtest_learned_prior_weekly.py, ' + esc(LP.updated || '') + ') \u2014 shadow v2.15: 50/50 ridge + hand prior</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(LP.summary || '') + '</b> The season-long ridge (ADP, history, age, rookie pick, week-1 string, opportunity prior, 2nd-year snaps) replaces the shadow\u2019s hand-built preseason prior inside the weekly harness; the mix sweep wants 0.5-0.75 ridge. Forward at 0.5 (ridge fit on earlier seasons only): all weeks -0.48% vs shadow (4/5), week 1 -1.35% (5/5) and -1.94% vs Clay (4/5), games 1-3 -1.74% (5/5); full replacement fails forward because the early fits have 50-130 rows per position. Shipped shadow-only at 0.5 (NC_SHADOW.ridgeW; data/ridge_prior.js; tag +ridge; kill window.SIM_NC_RIDGE = false).</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto">' + lpHead + '<tbody>' + LP.stages.map(lpRow).join('') + '</tbody></table></div>';
      if (LP.week1) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>Week 1 head-to-head</b> (no season data yet; the one cut Clay still won):</p><div style="overflow-x:auto"><table style="width:auto">' + lpHead + '<tbody>' + LP.week1.map(lpRow).join('') + '</tbody></table></div>';
      if (LP.byPos) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>By position</b> (full ridge replacement, LOYO):</p><div style="overflow-x:auto"><table style="width:auto">' + lpHead + '<tbody>' + LP.byPos.map(lpRow).join('') + '</tbody></table></div>';
      if (LP.forward) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>Forward 2021-25</b> (full replacement; the shipped 0.5 mix is in the note above):</p><div style="overflow-x:auto"><table style="width:auto">' + lpHead + '<tbody>' + LP.forward.map(lpRow).join('') + '</tbody></table></div>';
      if (LP.sweeps && LP.sweeps.length) html += '<p class="dim" style="font-size:11px;margin:6px 0">Mix sweeps (LOYO vs shadow, a = ridge weight): ' + LP.sweeps.map(function (r) { return esc(r.label.trim()) + ' best ' + r.pooledBest + ' ' + lpPct(r.loyoPct) + ' (' + r.wins + '/' + r.years + ', ' + r.verdict + ')'; }).join(' \u00b7 ') + '.</p>';
    }
    var RZ = window.SIM_RISERS_BT;
    if (RZ && RZ.tiers) {
      var rzPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var rzCol = function (v, w, y) { return (v <= -0.3 && w > y / 2) ? 'var(--acc)' : (v >= 0.3 ? '#f85149' : 'inherit'); };
      var rzRow = function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + rzCol(r.vsBase, r.baseWins, r.years) + '">' + rzPct(r.vsBase) + ' (' + r.baseWins + '/' + r.years + ')</td><td style="color:' + rzCol(r.vsClay, r.clayWins, r.years) + '"><b>' + rzPct(r.vsClay) + '</b> (' + r.clayWins + '/' + r.years + ')</td></tr>'; };
      var rzHead = '<thead><tr><th class="l">Tier: candidate</th><th>n</th><th>vs live ridge (seasons)</th><th>vs Clay (seasons)</th></tr></thead>';
      html += '<h4 style="margin:14px 0 4px">Risers in the top 60-150: can a Clay-free season prior catch what Clay catches? (backtest_risers.py, ' + esc(RZ.updated || '') + ') \u2014 NOTHING SHIPS</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(RZ.summary || '') + '</b> Jack\u2019s rule: grade on the top 150 by ADP, the 60-100 band most. Clay\u2019s season-long edge in the top 60 lives in 24 player-seasons he projected 2+ points above our ridge (Gibbs, Bijan, Henry 2019, Kelce 2020, Andrews 2023, Allen 2021, Chubb 2020): ascending 2nd / 3rd-year players whose role grew. Growth terms, a linear ADP term inside the top 60, a young / veteran split and a top-150-only fit all fail to move those rows (mean prediction 13.0-13.3 vs actual 15.2, Clay 15.6) and all lose forward. Season-long the top 150 stays Clay\u2019s (+6% forward for the ridge); only the 50/50 Clay + ridge ensemble beats him there (top 60 -1.1%, 61-100 -6.9%, top 150 -5.4%, 5/7). WEEKLY is a different story: the v2.15 shadow beats the corrected Clay blend in every tier (top 60 -1.05% 6/7, 61-100 -1.38% 5/7, 101-150 -1.24%, top 150 -1.17% 5/7; QB top-150 -0.23% is the soft spot).</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto">' + rzHead + '<tbody>' + RZ.tiers.map(rzRow).join('') + '</tbody></table></div>';
      if (RZ.forward && RZ.forward.length) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>Forward 2021-25</b>:</p><div style="overflow-x:auto"><table style="width:auto">' + rzHead + '<tbody>' + RZ.forward.map(rzRow).join('') + '</tbody></table></div>';
    }
    var VB = window.SIM_VACBUMP_BT;
    if (VB && VB.bump) {
      var vbPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var vbCol = function (v, w, y) { return (v <= -0.3 && w > y / 2) ? 'var(--acc)' : (v >= 0.3 ? '#f85149' : 'inherit'); };
      var vbRow = function (r) { return '<tr><td class="l">' + esc(r.label) + '</td><td class="dim">' + r.n + '</td><td style="color:' + vbCol(r.vsBase, r.baseWins, r.years) + '"><b>' + vbPct(r.vsBase) + '</b> (' + r.baseWins + '/' + r.years + ')</td><td style="color:' + vbCol(r.vsClay, r.clayWins, r.years) + '">' + vbPct(r.vsClay) + ' (' + r.clayWins + '/' + r.years + ')</td><td class="dim">' + vbPct(r.baseVsClay) + '</td></tr>'; };
      var vbHead = '<thead><tr><th class="l">Tier: candidate</th><th>n</th><th>vs shadow prior (seasons)</th><th>vs Clay (seasons)</th><th>shadow vs Clay</th></tr></thead>';
      html += '<h4 style="margin:14px 0 4px">Vacated volume x depth chart at the start of the season (backtest_vacated_bump.py, ' + esc(VB.updated || '') + ') \u2014 REJECTED</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(VB.summary || '') + '</b> Jack: "add a vacated volume / depth chart check at the beginning of seasons to give players a bump." Per player-season 2019-25: the team\u2019s vacated carry share (RB) or target share (WR/TE) from players who left, whether last year\u2019s leader at the position left, the player\u2019s last-year share rank on the team, and his week-1 depth string. Tried as ridge features and as three bump rules on the v2.15 shadow prior (string-1 x vacated, promotion flag, vacated share alone), k per position leave-one-year-out on top-150 rows. Every version is worse in the top 150 and the LOYO k picks are 0 almost everywhere. The reason is in the riser rows themselves: the 24 top-60 player-seasons Clay got right had LESS vacated volume than the average top-60 player (0.30 vs 0.32) and fewer promotions (25% vs 35%) \u2014 Aaron Jones 2019, Chubb 2020, Kelce 2020, Henry 2019, Bijan 2024, Kamara 2024 all rose inside a stable roster by coaching decision, while the big vacated-share cases (Mike Davis 2021 at 1.14, Montgomery 2019 at 0.78) busted. Departures are not the signal; the opportunity prior already carried the allocated vacated share.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto">' + vbHead + '<tbody>' + VB.bump.filter(function (r) { return !/^top 150 (QB|RB|WR|TE)/.test(r.label); }).map(vbRow).join('') + '</tbody></table></div>';
      if (VB.ridge) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>As ridge features</b> (LOYO):</p><div style="overflow-x:auto"><table style="width:auto">' + vbHead + '<tbody>' + VB.ridge.map(vbRow).join('') + '</tbody></table></div>';
      if (VB.forward) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>Forward 2021-25</b>:</p><div style="overflow-x:auto"><table style="width:auto">' + vbHead + '<tbody>' + VB.forward.map(vbRow).join('') + '</tbody></table></div>';
    }
    var TW = window.SIM_T150_BT;
    if (TW && TW.rows) {
      var twPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var twCol = function (v, w, y) { return (v <= -0.3 && w > y / 2) ? 'var(--acc)' : (v >= 0.3 ? '#f85149' : 'inherit'); };
      var twGroup = function (rows) {
        var by = {}; rows.forEach(function (r) { var k = r.label.split(' | ')[0]; (by[k] = by[k] || []).push(r); });
        return Object.keys(by).map(function (k) { return '<tr><td class="l">' + esc(k) + '</td>' + by[k].map(function (r) { return '<td style="color:' + twCol(r.vsClay, r.clayWins, r.years) + '"><b>' + twPct(r.vsClay) + '</b> (' + r.clayWins + '/' + r.years + ')<br><span class="dim">' + twPct(r.vsBase) + ' vs v2.15</span></td>'; }).join('') + '</tr>'; }).join('');
      };
      var twHead = '<thead><tr><th class="l">Candidate</th><th>top 60</th><th>ADP 61-100</th><th>ADP 101-150</th><th>top 150</th></tr></thead>';
      html += '<h4 style="margin:14px 0 4px">Top-150, importance-weighted season prior (backtest_top150_weighted.py, ' + esc(TW.updated || '') + ') \u2014 NOTHING SHIPS</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(TW.summary || '') + '</b> Jack: "focus on the top 150 and heavily weight the higher scoring players." Weights = games x LEVEL^p, LEVEL = the ADP-curve implied PPG (position-relative); the ridge is refit with the weights and every cell below is graded with the same importance-weighted MSE vs Clay\u2019s season sheet (cell = vs Clay, seasons won; grey = vs the current shadow v2.15). Weighting the fit changes almost nothing: the best LOYO variant (LEVEL^1, ridge 75%) is -1.2% vs v2.15 in the top 150 but +3.3% worse forward; at the shipped 50/50 mix the weighted fits are within 0.2% of the plain fit both ways. Under this weighting Clay wins the top 150 season-long (+4.0% LOYO, +1.7% forward for us) and the 50/50 shadow + Clay ensemble beats him (-3.0% / -3.9%). WEEKLY under the same weights the v2.15 shadow beats the corrected Clay blend in every tier: top 60 -1.17% (5/7), 61-100 -1.10% (5/7), 101-150 -0.94% (5/7), top 150 -1.13% (6/7); RB -1.54% (6/7), WR -1.09% (6/7), TE -1.06%, QB -0.35% (3/7).</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto">' + twHead + '<tbody>' + twGroup(TW.rows) + '</tbody></table></div>';
      if (TW.forward) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>Forward 2021-25</b>:</p><div style="overflow-x:auto"><table style="width:auto">' + twHead + '<tbody>' + twGroup(TW.forward) + '</tbody></table></div>';
    }
    var WU = window.SIM_W1USAGE_BT;
    if (WU && WU.rows) {
      var wuPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var wuCol = function (v, w, y) { return (v <= -0.3 && w > y / 2) ? 'var(--acc)' : (v >= 0.3 ? '#f85149' : 'inherit'); };
      var wuGroup = function (rows) {
        var by = {}, order = []; rows.forEach(function (r) { var k = r.label.split(' | ')[0]; if (!by[k]) { by[k] = []; order.push(k); } by[k].push(r); });
        return order.map(function (k) { return '<tr><td class="l">' + esc(k) + '</td>' + by[k].map(function (r) { return '<td style="color:' + wuCol(r.vsClay, r.clayWins, r.years) + '"><b>' + wuPct(r.vsClay) + '</b> (' + r.clayWins + '/' + r.years + ')<br><span class="dim" style="color:' + wuCol(r.vsBase, r.baseWins, r.years) + '">' + wuPct(r.vsBase) + ' vs v2.16</span></td>'; }).join('') + '</tr>'; }).join('');
      };
      var wuHead = '<thead><tr><th class="l">Candidate</th><th>top 60</th><th>61-100</th><th>101-150</th><th>top 150</th><th>top 150 WR</th><th>top 150 RB</th><th>top 150 TE</th></tr></thead>';
      html += '<h4 style="margin:14px 0 4px">Week-1 usage as a preseason-chart stand-in (backtest_week1_usage.py, ' + esc(WU.updated || '') + ') \u2014 NOTHING SHIPS</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(WU.summary || '') + '</b> Jack: "use route data for week one just to back test, and next season I can set up the depth charts." The ESPN chart cannot order receivers and no August charts exist for 2019-24, so week-1 usage stands in for what a good preseason chart would show: PFF week-1 route participation, routes vs the team\u2019s top route runner, team route rank at WR+TE, and nflverse week-1 snap share with the team rank at the position. Target = PPG over the games AFTER the first game, so the usage is never graded against its own week. Cell = vs Clay (seasons won), grey = vs the v2.16 prior; importance-weighted. Routes help receivers (top-150 WR -1.7% LOYO 5/7, forward -0.3%) and the 61-150 bands (-1.1 / -1.8% LOYO, -1.7 / -1.6% forward), do nothing for backs, and the top 150 as a whole is flat forward (+0.03%). The 47 top-60 rows Clay projected 2+ above the prior do not move at all (13.32 -> 13.27 vs actual 15.0): Aaron Jones, Henry, Kamara and Kelce had ordinary week-1 usage and their roles grew over the season. A perfect preseason chart would not have caught the risers.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto">' + wuHead + '<tbody>' + wuGroup(WU.rows) + '</tbody></table></div>';
      if (WU.forward) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>Forward 2021-25</b>:</p><div style="overflow-x:auto"><table style="width:auto">' + wuHead + '<tbody>' + wuGroup(WU.forward) + '</tbody></table></div>';
    }
    var AS = window.SIM_ANCHOR_SWEEP;
    if (AS && AS.clay && AS.clay.length) {
      var asLine = function (rows, key) { var b = rows.reduce(function (a, r) { return (!a || r[key] < a[key]) ? r : a; }, null); return rows.map(function (r) { var on = r === b; return '<td style="' + (on ? 'color:var(--acc);font-weight:700' : (Math.abs(r.w - 0.7) < 1e-9 ? 'text-decoration:underline' : '')) + '">' + r[key].toFixed(2) + '</td>'; }).join(''); };
      var asHead = '<thead><tr><th class="l">Base under the anchor</th><th>n</th>' + AS.clay.map(function (r) { return '<th>w ' + r.w.toFixed(1) + '</th>'; }).join('') + '</tr></thead>';
      var asGroup = function (rows) { var by = {}, ord = []; rows.forEach(function (r) { if (!by[r.base]) { by[r.base] = []; ord.push(r.base); } by[r.base].push(r); }); return ord.map(function (k) { return '<tr><td class="l">' + esc(k) + ' <span class="dim">(weighted)</span></td><td class="dim">' + by[k][0].n + '</td>' + asLine(by[k], 'wmse') + '</tr><tr><td class="l dim">' + esc(k) + ' (plain)</td><td></td>' + asLine(by[k], 'mse') + '</tr>'; }).join(''); };
      html += '<h4 style="margin:14px 0 4px">Book-anchor weight sweep over the scored locks (anchor_sweep.py, ' + esc(AS.updated || '') + ') \u2014 re-runs every Tuesday</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(AS.summary || '') + '</b> The shipped mean is 70% market / 30% model; that weight was a prior (no prop history exists before 2026). Each cell is the MSE of w x market + (1-w) x base against actual half-PPR points on rows with direct lines; the market mean is backed out of the lock. Green = best w, underlined = the shipped 0.7. Weighted = Jack\u2019s rule (projection level squared, position-relative). Weeks scored: ' + (AS.weeks || []).map(function (w) { return 'W' + w.wk + ' n=' + w.n + (w.withShadow ? ' (' + w.withShadow + ' with shadow)' : ''); }).join(', ') + '. One week is not enough to move the weight; the shadow rows start with the W2 lock.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto">' + asHead + '<tbody>' + asGroup(AS.clay) + asGroup(AS.byPos || []) + asGroup(AS.shadow || []) + '</tbody></table></div>';
      if (AS.headToHead && AS.headToHead.length) html += '<p class="dim" style="font-size:11px;margin:6px 0">Anchored shadow vs anchored Clay (weighted / plain): ' + AS.headToHead.map(function (r) { return 'w ' + r.w.toFixed(1) + ' ' + (r.shadowVsClay >= 0 ? '+' : '') + r.shadowVsClay.toFixed(2) + '% / ' + (r.shadowVsClayPlain >= 0 ? '+' : '') + r.shadowVsClayPlain.toFixed(2) + '%'; }).join(' \u00b7 ') + '.</p>';
    }
    var QC = window.SIM_QBCOMP_BT;
    if (QC && QC.sweeps) {
      var qcPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var qcCol = function (v, w, y) { return (v <= -0.3 && w > y / 2) ? 'var(--acc)' : (v >= 0.3 ? '#f85149' : 'inherit'); };
      var qcCuts = ['QB top 150 (weighted)', 'elite QB, ADP <= 60', 'QB ADP 61-150', 'QB week 1', 'QB games 1-3', 'QB games 4+'];
      var qcGroup = function (rows) { var by = {}, ord = []; rows.forEach(function (r) { if (!by[r.label]) { by[r.label] = {}; ord.push(r.label); } by[r.label][r.cut] = r; }); return ord.map(function (k) { return '<tr><td class="l">' + esc(k) + '</td>' + qcCuts.map(function (c) { var r = by[k][c]; return r ? '<td style="color:' + qcCol(r.vsShadow, r.shadowWins, r.years) + '"><b>' + qcPct(r.vsShadow) + '</b> (' + r.shadowWins + '/' + r.years + ')<br><span class="dim">' + qcPct(r.vsClay) + ' vs Clay</span></td>' : '<td></td>'; }).join('') + '</tr>'; }).join(''); };
      var qcHead = '<thead><tr><th class="l">QB-only change</th>' + qcCuts.map(function (c) { return '<th>' + esc(c) + '</th>'; }).join('') + '</tr></thead>';
      html += '<h4 style="margin:14px 0 4px">QB compression in the shadow (backtest_qb_compression.py, ' + esc(QC.updated || '') + ') \u2014 shadow v2.17: no ridge half for QBs</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(QC.summary || '') + '</b> Jack: "fix the QB compression in the shadow." A veteran QB\u2019s prior passes through a 75% log-ADP market curve, the 0.8 shrink, the 50% ridge half and prior strength P = 12; each was swept for QBs only. Weekly the shadow is NOT compressed at QB (slope of actual on prediction 0.91; Clay 0.76): un-shrinking (k 0.9-1.1) and a weaker P both make QBs worse. What hurts is the ridge half: dropping it for QBs is -0.65% on the weighted top-150 QBs LOYO (6/7), -1.41% forward (5/5), elite QBs -1.1% / -1.8%. A lower ADP-curve weight adds more pooled but swings by season (+1.5% in 2020, -2.9% in 2023 and 2025) so it is not applied. Cell = vs the current shadow (seasons won), grey = vs the corrected Clay blend. Shipped shadow-only: NC_SHADOW.ridgeW is now per position (QB 0, RB / WR / TE 0.5).</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto">' + qcHead + '<tbody>' + qcGroup(QC.sweeps) + qcGroup(QC.final || []) + '</tbody></table></div>';
      if (QC.forward) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>Forward 2021-25</b>:</p><div style="overflow-x:auto"><table style="width:auto">' + qcHead + '<tbody>' + qcGroup(QC.forward) + '</tbody></table></div>';
      if (QC.diag) html += '<p class="dim" style="font-size:11px;margin:6px 0">Level by ADP tier, QB player-weeks (actual / shadow / Clay blend): ' + QC.diag.map(function (d) { return esc(d.cut) + ' ' + d.act.toFixed(1) + ' / ' + d.shadow.toFixed(1) + ' / ' + d.clay.toFixed(1); }).join(' \u00b7 ') + '.</p>';
    }
    var IU = window.SIM_INSEASON_BT;
    if (IU && IU.curve) {
      var iuPct = function (p) { return p == null ? '\u2014' : (p >= 0 ? '+' : '') + (+p).toFixed(2) + '%'; };
      var iuCol = function (v, w, y) { return (v <= -0.3 && w > y / 2) ? 'var(--acc)' : (v >= 0.3 ? '#f85149' : 'inherit'); };
      var iuCuts = ['1 game', '2 games', '3 games', '4-5 games', '6-8 games', '9+ games', 'ALL games 1+'];
      var iuGroup = function (rows) { var by = {}, ord = []; rows.forEach(function (r) { if (!by[r.model]) { by[r.model] = {}; ord.push(r.model); } by[r.model][r.cut] = r; }); return ord.map(function (k) { return '<tr><td class="l">' + esc(k) + '</td>' + iuCuts.map(function (c) { var r = by[k][c]; if (!r) return '<td></td>'; var base = /^shadow/.test(k); return '<td style="color:' + (base ? iuCol(r.vsClay, r.clayWins, r.years) : iuCol(r.vsShadow, r.shadowWins, r.years)) + '"><b>' + (base ? iuPct(r.vsClay) + '</b> (' + r.clayWins + '/' + r.years + ') vs Clay' : iuPct(r.vsShadow) + '</b> (' + r.shadowWins + '/' + r.years + ')<br><span class="dim">' + iuPct(r.vsClay) + ' vs Clay</span>') + '</td>'; }).join('') + '</tr>'; }).join(''); };
      var iuHead = '<thead><tr><th class="l">Evidence in the shadow</th>' + iuCuts.map(function (c) { return '<th>' + esc(c) + '</th>'; }).join('') + '</tr></thead>';
      html += '<h4 style="margin:14px 0 4px">In-season usage evidence: the learning curve by games played (backtest_inseason_usage.py, ' + esc(IU.updated || '') + ') \u2014 shadow v2.18</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(IU.summary || '') + '</b> Jack: "use the previous weeks information (routes run, snaps, target share) and see how the model does as the season goes on." Walk-forward: week 1 is the preseason prior alone; each later week sees only the weeks before it. Importance-weighted top 150. First row = the current shadow vs the corrected Clay blend at each stage; other rows = vs that shadow (seasons won), grey = vs Clay. Pure usage (xFP/g instead of points) wins only after ONE game and is +18% worse by 9 games: points carry skill. A learned usage model on 20 features (shares, red zone, air yards, snaps, routes, trends) overfits and loses 3-5%. What works is one smooth schedule per position for the weight on xFP/g inside the evidence: WR 100% after 1 game, fading 8 points per game to a 25% floor; RB 100% after 1 game, fading 30 per game to 25%; QB and TE none. LOYO -0.49% (6/7), forward -0.45% (5/5); RB -0.54% and WR -0.72%, each 6/7. Shipped shadow-only (NC_SHADOW.usageLam, tag +xfp, kill window.SIM_NC_USAGE = false).</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto">' + iuHead + '<tbody>' + iuGroup(IU.curve) + '</tbody></table></div>';
      if (IU.forward) html += '<p class="dim" style="font-size:11px;margin:8px 0 2px"><b>Forward 2021-25</b>:</p><div style="overflow-x:auto"><table style="width:auto">' + iuHead + '<tbody>' + iuGroup(IU.forward) + '</tbody></table></div>';
    }
    var MR = window.SIM_MATCHUP_RANK_BT;
    if (MR && MR.ablation) {
      var mrS = function (v, d) { return v == null ? '\u2014' : (v >= 0 ? '+' : '') + (+v).toFixed(d); };
      var mrPass = function (t) { return t.dRho >= 0.004 && t.wins >= 5 && t.fwd && t.fwd.dRho > 0 && t.fwd.wins >= 3; };
      var mrRow = function (t) { var ok = mrPass(t); return '<tr><td class="l">' + esc(t.label) + '</td><td>' + esc(t.pos) + '</td><td style="color:' + (ok ? 'var(--acc)' : (t.dRho < -0.002 ? '#f85149' : 'inherit')) + '"><b>' + mrS(t.dRho, 4) + '</b> (' + t.wins + '/' + t.years + ')</td><td>' + mrS(t.dPair, 2) + '</td><td class="dim">' + mrS(t.dMsePct, 2) + '%</td><td>' + mrS(t.fwd.dRho, 4) + ' (' + t.fwd.wins + '/' + t.fwd.years + ')</td><td class="dim">' + esc((t.picks || []).filter(function (v, i, a) { return a.indexOf(v) === i; }).join(', ')) + '</td></tr>'; };
      var mrHead = '<thead><tr><th class="l">Signal</th><th>Pos</th><th>Spearman change LOYO (seasons)</th><th>Pairs right, pts</th><th>Points MSE</th><th>Forward Spearman</th><th>Picks</th></tr></thead>';
      var ab = {}; MR.ablation.forEach(function (r) { (ab[r.layers] = ab[r.layers] || {})[r.pos] = r; });
      html += '<h4 style="margin:14px 0 4px">Do defensive data and advanced analytics help the weekly RANKINGS? (backtest_matchup_rank.py, ' + esc(MR.updated || '') + ') \u2014 shadow v2.19: QB game-total tilt</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(MR.summary || '') + '</b> Jack: "maximize our in season week specific rankings \u2014 do any of the defensive data or advanced analytics help?" Objective = mean Spearman between projected and actual order inside each position each week, top 150, 2019-25; pairs ordered correctly and points MSE ride along. The shipped Vegas and FPA layers are worth a lot for ranking (QB .269 \u2192 .307, RB .486 \u2192 .505, WR .339 \u2192 .348, TE .325 \u2192 .335), almost all of it the Vegas implied total; re-tuning their strength for rank fails. Of 42 new position-level tilts only the QB game total is credible (same pick every fold, both rank measures up, 6/7 and 4/5): fixed at c = .03 it adds +.0115 Spearman (6/7) and +0.42 pts of pairs (6/7) for +0.17% MSE. PFF opponent coverage / pass-rush / run-defense grades, pass-rush win rate, man-rate x YPRR gap, OL grades, spread, wind and dome do not help; the two other nominal passes (QB vs run-defense grade, TE vs own pass-blocking) are small, sign-implausible and expected from 42 tries.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Layers applied</th><th>QB rho</th><th>RB rho</th><th>WR rho</th><th>TE rho</th></tr></thead><tbody>' + Object.keys(ab).map(function (k) { return '<tr><td class="l">' + esc(k) + '</td>' + ['QB', 'RB', 'WR', 'TE'].map(function (ps) { return '<td>' + (ab[k][ps] ? ab[k][ps].rho.toFixed(4) : '') + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>';
      html += '<div style="overflow-x:auto;margin-top:8px"><table style="width:auto">' + mrHead + '<tbody>' + (MR.retune || []).map(mrRow).join('') + (MR.tilts || []).map(mrRow).join('') + '</tbody></table></div>';
      if (MR.qbFine) html += '<p class="dim" style="font-size:11px;margin:6px 0">QB fixed-strength sweep: ' + MR.qbFine.map(function (r) { return esc(r.feat) + ' c ' + r.c.toFixed(2) + ': rho ' + mrS(r.dRho, 4) + ' (' + r.rhoWins + '/7), pairs ' + mrS(r.dPair, 2) + ' (' + r.pairWins + '/7), MSE ' + mrS(r.dMsePct, 2) + '%'; }).join(' \u00b7 ') + '.</p>';
    }
    var AM = window.SIM_ALIGN_BT;
    if (AM && AM.tests) {
      var amS = function (v, d) { return v == null ? '\u2014' : (v >= 0 ? '+' : '') + (+v).toFixed(d); };
      html += '<h4 style="margin:14px 0 4px">Alignment matchups: slot / outside / inline vs what each defense allows there (backtest_alignment_matchup.py, ' + esc(AM.updated || '') + ') \u2014 NOT APPLIED</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(AM.summary || '') + '</b> Jack: "so matchups dont really matter individually \u2014 example x z or slot?" Every WR / TE week in PFF (slot, wide, inline route shares) is charged to the defense he faced, giving each defense\u2019s half-PPR points allowed per route by alignment, walk-forward and shrunk to last season; a receiver\u2019s score = his own alignment mix x the opponent\u2019s alignment z, and the alignment-specific version subtracts the opponent\u2019s overall z (the part position FPA cannot see). Graded on the weekly rank objective, top 150. The catch is persistence: what a defense allows to an alignment beyond its overall level barely repeats from the first half of a season to the second. Slot WRs lean the right way (actual / projected 1.03 vs soft slot defenses, 0.98 vs tough) but the rank gain is +.0016; outside WRs show nothing (the fit even picks the wrong sign); inline-heavy TEs are the one real lean (1.12 vs 0.91, rank +.0044, 5/7, forward +.0027) but those are mostly blocking tight ends, few of them startable, and the gain is under the bar used elsewhere once seven tests are allowed for.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Test</th><th>Pos</th><th>Spearman LOYO (seasons)</th><th>Pairs, pts</th><th>MSE</th><th>Forward (seasons)</th><th>Picks</th></tr></thead><tbody>' +
        AM.tests.map(function (t) { return '<tr><td class="l">' + esc(t.label) + '</td><td>' + esc(t.pos) + '</td><td style="color:' + (t.pass ? 'var(--acc)' : (t.dRho < -0.002 ? '#f85149' : 'inherit')) + '"><b>' + amS(t.dRho, 4) + '</b> (' + t.wins + '/' + t.years + ')</td><td>' + amS(t.dPair, 2) + '</td><td class="dim">' + amS(t.dMsePct, 2) + '%</td><td>' + amS(t.fwd.dRho, 4) + ' (' + t.fwd.wins + '/' + t.fwd.years + ')</td><td class="dim">' + esc(t.picks.filter(function (v, i, a) { return a.indexOf(v) === i; }).join(', ')) + '</td></tr>'; }).join('') + '</tbody></table></div>';
      html += '<p class="dim" style="font-size:11px;margin:6px 0">' + (AM.diag || []).map(function (d) { return d.r != null ? ('persistence ' + esc(d.what) + ' r ' + amS(d.r, 2)) : (esc(d.what) + ': soft ' + d.soft.toFixed(3) + ' (n ' + d.nSoft + ') / tough ' + d.tough.toFixed(3) + ' (n ' + d.nTough + ')'); }).join(' \u00b7 ') + '.</p>';
    }
    var EP = window.SIM_EARLYPRIOR_BT;
    if (EP && EP.stages) {
      var epS = function (v, d) { return v == null ? '\u2014' : (v >= 0 ? '+' : '') + (+v).toFixed(d); };
      var epCol = function (v, w, y) { return (v <= -0.3 && w > y / 2) ? 'var(--acc)' : (v >= 0.3 ? '#f85149' : 'inherit'); };
      var epStages = ['1 game', '2 games', '3 games', '4-5 games', '6+ games', 'games 1-3', 'ALL (incl week 1)'];
      var epFixed = function (rows) { var by = {}, ord = []; rows.forEach(function (r) { if (!by[r.cand]) { by[r.cand] = {}; ord.push(r.cand); } by[r.cand][r.stage] = r; }); return ord.map(function (k) { return '<tr><td class="l">' + esc(k) + '</td>' + epStages.map(function (st) { var r = by[k][st]; return r ? '<td style="color:' + epCol(r.mse, r.wins, r.years) + '"><b>' + epS(r.mse, 2) + '%</b> (' + r.wins + '/' + r.years + ')<br><span class="dim">rho ' + epS(r.dRho, 4) + ', pairs ' + epS(r.dPair, 2) + '</span></td>' : '<td></td>'; }).join('') + '</tr>'; }).join(''); };
      html += '<h4 style="margin:14px 0 4px">Early-season prior: is the shadow over-reacting to the first games? (backtest_early_prior.py, ' + esc(EP.updated || '') + ') \u2014 shadow v2.21: WR prior x5 after one game</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(EP.summary || '') + '</b> Prompt: against its own frozen preseason number the shadow\u2019s in-season updates ordered pairs correctly only 49% of the time in weeks 2-4, and after one game its error was 1.1% worse than not updating. Delays, early boosts and tapers on the prior strength were tried per position. Choosing among 22 settings per fold FAILS (summary line above), because QBs and RBs gain from updating early (-2.1% / -1.7% vs a frozen prior over games 1-3) and TE is noise. The stable piece is wide receivers after exactly ONE game: every fixed variant wins 7 of 7 seasons and the gain grows the more week 1 is ignored. Shipped shadow-only: prior strength x5 for a WR\u2019s projection after one game (tag +earlyP, kill window.SIM_NC_EARLYP = false); nothing changes from game 2 on. Table = WR only, fixed settings, no selection; cell = weighted MSE vs the current shadow (seasons better), rank and pairs below.</p>';
      if (EP.wrFixed) html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">WR, fixed setting</th>' + epStages.map(function (st) { return '<th>' + esc(st) + '</th>'; }).join('') + '</tr></thead><tbody>' + epFixed(EP.wrFixed) + '</tbody></table></div>';
      if (EP.diag) html += '<p class="dim" style="font-size:11px;margin:6px 0">Current shadow by games played (vs frozen prior / vs Clay blend): ' + EP.diag.map(function (d) { return esc(d.stage) + ' ' + epS(d.vsFrozen, 2) + '% / ' + epS(d.vsClay, 2) + '%'; }).join(' \u00b7 ') + '.</p>';
    }
    var B36 = window.SIM_BAND3160_BT;
    if (B36 && B36.bands) {
      var b3S = function (v) { return v == null ? '\u2014' : (v >= 0 ? '+' : '') + (+v).toFixed(2) + '%'; };
      var b3Bands = ['ADP 1-30', 'ADP 31-60', 'ADP 61-100', 'ADP 101-150', 'ADP 151+', 'EVERYONE'];
      var b3Group = function (rows) { var by = {}, ord = []; rows.forEach(function (r) { if (!by[r.variant]) { by[r.variant] = {}; ord.push(r.variant); } by[r.variant][r.band] = r; }); return ord.map(function (k) { return '<tr><td class="l">' + esc(k) + '</td>' + b3Bands.map(function (b) { var r = by[k][b]; return r ? '<td style="color:' + ((r.vsShadow <= -0.3 && r.wins > r.years / 2) ? 'var(--acc)' : (r.vsShadow >= 0.3 ? '#f85149' : 'inherit')) + '">' + b3S(r.vsShadow) + ' (' + r.wins + '/' + r.years + ')<br><span class="dim">' + b3S(r.vsClay) + ' vs Clay</span></td>' : '<td></td>'; }).join('') + '</tr>'; }).join(''); };
      html += '<h4 style="margin:14px 0 4px">The ADP 31-60 band (backtest_band3160.py, ' + esc(B36.updated || '') + ') \u2014 NO Clay-free fix; the blend is the fix</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(B36.summary || '') + '</b> Jack: "lets work on the 31-60 band" \u2014 the shadow\u2019s soft band (week 2 worse than today\u2019s Clay blend in 5 of 7 seasons; start/sit disagreements 49.8%). Diagnosis: our prior sits 4.8% low there (the hand prior shrinks everyone toward the whole-pool position mean) and the log-ADP market curve is the wrong shape (+10.6% too high at picks 1-12, -7.8% at 37-48). Fixing either \u2014 a flexible curve, shrinking toward the market value, lighter shrink for the top 60 \u2014 brings the level to within 1% and changes the error by under 0.1%, worse forward: the level is not the problem. By week, the weakness is weeks 1-3, where Clay\u2019s PRESEASON number is simply better in this band (correlation with the player\u2019s season rate QB .48 vs -.14, TE .47 vs .27, RB .19 vs .15, WR .13 vs .11; n 175 player-seasons); from week 4 on we are level or ahead. A two-stage blend weight (more Clay early) does not beat a flat one: flat 70/30 is picked in every held-out season and takes 31-60 from -0.86% (5/7) to -1.34% (6/7) and top-60 weeks 1-3 from -1.30% to -2.24%.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Hand-prior variant (LOYO, all weeks)</th>' + b3Bands.map(function (b) { return '<th>' + esc(b) + '</th>'; }).join('') + '</tr></thead><tbody>' + b3Group(B36.bands) + '</tbody></table></div>';
      if (B36.curve) html += '<p class="dim" style="font-size:11px;margin:6px 0">Market-curve residual by ADP bucket, weeks 1-4 (log-linear / flexible): ' + B36.curve.map(function (r) { return esc(r.band) + ' ' + (r.log >= 0 ? '+' : '') + r.log.toFixed(2) + ' / ' + (r.flex >= 0 ? '+' : '') + r.flex.toFixed(2); }).join(' \u00b7 ') + '.</p>';
    }
    var VE = window.SIM_VS_ESPN_BT;
    if (VE && VE.overall) {
      var veM = ['ESPN', 'Clay blend today', 'shadow v2.21 (Clay-free)', '70/30 blend'];
      var veRow = function (r) { return '<tr><td class="l">' + esc(r.cut) + '</td><td class="dim">' + r.n + '</td>' + veM.map(function (k) { var c = r[k]; if (!c) return '<td></td>'; if (k === 'ESPN') return '<td><b>' + c.rmse.toFixed(2) + '</b></td>'; return '<td style="color:' + ((c.vsEspn <= -0.3 && c.wins > c.years / 2) ? 'var(--acc)' : (c.vsEspn >= 0.3 ? '#f85149' : 'inherit')) + '">' + c.rmse.toFixed(2) + ' <span class="dim">(' + (c.vsEspn >= 0 ? '+' : '') + c.vsEspn.toFixed(2) + '%, ' + c.wins + '/' + c.years + ')</span></td>'; }).join('') + '</tr>'; };
      var veHead = '<thead><tr><th class="l">Cut</th><th>n</th><th>ESPN miss</th><th>Clay blend today</th><th>Shadow (Clay-free)</th><th>70/30 blend</th></tr></thead>';
      var veSec = function (t, rows) { return rows && rows.length ? '<tr><td class="l dim" colspan="6" style="padding-top:6px"><b>' + esc(t) + '</b></td></tr>' + rows.map(veRow).join('') : ''; };
      html += '<h4 style="margin:14px 0 4px">Us vs ESPN\u2019s weekly projections, 2019-25 (backtest_vs_espn.py, ' + esc(VE.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(VE.summary || '') + '</b> Jack: "is it possible to see how we do historically vs a fantasy site like espn". ESPN\u2019s API still serves the projection it showed for every past week (pull_espn_hist_proj.py, ~590 players a week with the projected stat line), rescored here to our half-PPR and matched to ' + VE.coverage.matched + ' of ' + VE.coverage.rows + ' harness player-weeks (' + VE.coverage.espnZero + ' where ESPN projected ~0 for a player who played are excluded). Typical miss in points; brackets = error vs ESPN (negative = better than ESPN) and seasons better than ESPN. ESPN beats every one of our pre-book models on points: the Clay blend as it runs today loses in all 7 seasons; the shadow and the 70/30 blend close two thirds of the gap, tie ESPN in the top 60 and on weekly ranking (Spearman .378 each), and lose in week 1, weeks 15-18 and the late rounds. FAIRNESS: ESPN\u2019s stored number is its final pre-kickoff projection, which already knows the inactives and injury news; ours sees closing Vegas lines and known absences only, and the LIVE board adds the book lines, which cannot be backtested. ESPN and ours carry different information: 50/50 of our blend with ESPN beats ESPN alone by ' + ((VE.info || []).filter(function (r) { return /0\.5 ours/.test(r.mix); })[0] || {vsEspn: 0}).vsEspn.toFixed(2) + '% (6/7).</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto">' + veHead + '<tbody>' + veSec('Overall', VE.overall) + veSec('By ADP band', VE.bands) + veSec('By position, top 150', VE.pos) + veSec('By part of the season, top 150', VE.stage) + veSec('By season, top 150', VE.season) + '</tbody></table></div>';
      if (VE.info) html += '<p class="dim" style="font-size:11px;margin:6px 0">Blends with ESPN (top 150, error vs ESPN alone): ' + VE.info.map(function (r) { return esc(r.mix) + ' ' + (r.vsEspn >= 0 ? '+' : '') + r.vsEspn.toFixed(2) + '% (' + r.wins + '/7)'; }).join(' \u00b7 ') + '.</p>';
    }
    var DKH = window.SIM_DECAYHIST_BT;
    if (DKH && DKH.weekly) {
      var dkCuts = ['TOP 150 wtd', 'ADP 1-30', '31-60', '61-100', '101-150', 'games 1-3', 'games 4+'];
      var dkTab = function (rows, yrs) { var by = {}; rows.forEach(function (r) { (by[r.variant] = by[r.variant] || {})[r.cut] = r; }); return Object.keys(by).filter(function (k) { return k !== 'current shadow'; }).map(function (k) { return '<tr><td class="l">' + esc(k) + '</td>' + dkCuts.map(function (c) { var r = by[k][c]; if (!r) return '<td></td>'; return '<td style="color:' + ((r.d <= -0.3 && r.wins > yrs / 2) ? 'var(--acc)' : (r.d >= 0.3 ? '#f85149' : 'inherit')) + '">' + (r.d >= 0 ? '+' : '') + r.d.toFixed(2) + '% <span class="dim">(' + r.wins + '/' + yrs + ')</span></td>'; }).join('') + '</tr>'; }).join(''); };
      var dkHead = '<thead><tr><th class="l">Variant</th>' + dkCuts.map(function (c) { return '<th>' + esc(c) + '</th>'; }).join('') + '</tr></thead>';
      html += '<h4 style="margin:14px 0 4px">Decayed-games history inside the full shadow (backtest_decayed_history.py, ' + esc(DKH.updated || '') + ') \u2014 NOT APPLIED</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(DKH.summary || '') + '</b> Jack: "lets build the decayed history". As a stand-alone predictor the decayed average of past games (half-life 12) is clearly better: refitting the veterans\u2019 history + opportunity blend on it cuts that blend\u2019s error ' + (DKH.blend && DKH.blend.length > 2 ? ((DKH.blend[2].mse / DKH.blend[0].mse - 1) * 100).toFixed(1) : '') + '% and the opportunity model\u2019s weight falls to about zero (the decayed history already carries it). But inside the finished shadow the history is a minor input \u2014 75% ADP market curve, 0.8 shrink, half the prior from the ridge (which already weighs 3-season and last-8 separately), and the in-season blend takes over after a few games \u2014 so nothing moves: every variant is within \u00b10.15% of today\u2019s shadow and weekly rank accuracy is flat to slightly worse. Swapping the ridge\u2019s three history features for the one decayed number loses information (+0.1%). Verdict: no live game-log feed built; shadow unchanged. Cells = error vs the current shadow (negative = better) and seasons better.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto">' + dkHead + '<tbody><tr><td class="l dim" colspan="8"><b>Leave-one-season-out, 2019-25</b></td></tr>' + dkTab(DKH.weekly, 7) + '<tr><td class="l dim" colspan="8" style="padding-top:6px"><b>Forward, 2021-25</b></td></tr>' + dkTab(DKH.forward, 5) + '</tbody></table></div>';
    }
    var FPO = window.SIM_FPLAYOFF_BT;
    if (FPO && FPO.stage) {
      var fpM = ['Clay blend today', 'shadow', '70/30 blend', 'rank mix (shadow + ESPN)'];
      var fpRow = function (r) { return '<tr><td class="l">' + esc(r.stage) + '</td><td class="dim">' + r.n + '</td><td><b>' + r.ESPN.rmse.toFixed(2) + '</b> <span class="dim">\u03c1 ' + r.ESPN.rho.toFixed(3) + '</span></td>' + fpM.map(function (k) { var c = r[k]; return '<td style="color:' + ((c.vsEspn <= -0.3 && c.wins > c.years / 2) ? 'var(--acc)' : (c.vsEspn >= 0.3 ? '#f85149' : 'inherit')) + '">' + c.rmse.toFixed(2) + ' <span class="dim">(' + (c.vsEspn >= 0 ? '+' : '') + c.vsEspn.toFixed(2) + '%, ' + c.wins + '/' + c.years + ') \u03c1 ' + c.rho.toFixed(3) + '</span></td>'; }).join('') + '</tr>'; };
      html += '<h4 style="margin:14px 0 4px">Fantasy-playoff weeks, final week dropped (backtest_fantasy_playoffs.py, ' + esc(FPO.updated || '') + ')</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(FPO.summary || '') + '</b> Jack: "dont worry about the final week of every season \u2026 the weeks besides last historically are very important as its fantasy playoffs". Final week = 17 (2019-20) / 18 (2021+), playoffs = the three weeks before it. Top 150, typical miss; brackets = error vs ESPN and seasons better than ESPN; \u03c1 = weekly within-position rank. With the final week out the rank mix beats ESPN on points in all 7 seasons and has the best ranking at every stage after week 1; in the playoffs every one of our own models trails ESPN on points (+2.6%) but ties it on ranking, and the mix is the best ranking we have (\u03c1 .421). The playoff loss sits with players whose last 4 games ran 3+ below their season rate (+8% vs ESPN; QBs and TEs over-projected ~1.5 points): cold finishes persist, hot ones regress. A cold-only recency term is right in direction but worth only \u22120.1 to \u22120.2% (4-5/7) with no rank gain, and symmetric recency, shorter in-season windows and a lighter late prior all lose \u2014 NOT applied.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Stage</th><th>n</th><th>ESPN</th><th>Clay blend today</th><th>Shadow</th><th>70/30 blend</th><th>Rank mix</th></tr></thead><tbody>' + FPO.stage.map(fpRow).join('') + '</tbody></table></div>';
      if (FPO.asym) html += '<p class="dim" style="font-size:11px;margin:6px 0">Cold-streak variants (top 150 weighted error vs the shadow, playoffs | all non-final weeks): ' + FPO.asym.map(function (r) { return esc(r.variant) + ' ' + (r.playoffs.d >= 0 ? '+' : '') + r.playoffs.d.toFixed(2) + '% (' + r.playoffs.wins + '/7) | ' + (r['all non-final'].d >= 0 ? '+' : '') + r['all non-final'].d.toFixed(2) + '% (' + r['all non-final'].wins + '/7)'; }).join(' \u00b7 ') + '.</p>';
    }
    var EVC = window.SIM_EVCLEAN_BT;
    if (EVC && EVC.rows) {
      var evCuts = ['ALL weeks 2+ (no final)', 'weeks 2-4', 'weeks 5-9', '10 to playoffs', 'PLAYOFFS', 'ADP 1-60', 'ADP 61-150'];
      var evRow = function (r) { return '<tr><td class="l">' + esc(r.variant) + '</td>' + evCuts.map(function (c) { var x = r[c]; if (!x) return '<td></td>'; return '<td style="color:' + ((x.d <= -0.25 && x.wins >= 5) ? 'var(--acc)' : (x.d >= 0.15 ? '#f85149' : 'inherit')) + '">' + (x.d >= 0 ? '+' : '') + x.d.toFixed(2) + '% <span class="dim">(' + x.wins + '/7) \u03c1 ' + (x.drho >= 0 ? '+' : '') + x.drho.toFixed(4) + '</span></td>'; }).join('') + '</tr>'; };
      html += '<h4 style="margin:14px 0 4px">Cleaning the in-season evidence (backtest_evidence_clean.py, ' + esc(EVC.updated || '') + ') \u2014 Vegas-adjusted evidence SHIPPED shadow-only (v2.24)</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(EVC.summary || '') + '</b> Jack: "lets build the in season evidence test". Three ways the season-to-date average is dirty, each inside the full shadow, final week dropped, top 150 importance-weighted vs the current shadow (seasons better) and change in weekly rank. <b>A. Opponent / environment-adjusted</b>: each past game divided by the matchup multiplier the model gave that game \u2014 PASSES, and all of it is the Vegas half (points scored in a 30-point team total count for less); the points-allowed half does nothing. Strength 1 (the same multiplier the forecast uses, no new number) is shipped; 1.5 is a hair better, 3 is too much. <b>B. Partial games</b> (snap share under half / two thirds of his norm; ' + (EVC.notes ? (100 * EVC.notes.p50 / EVC.notes.games).toFixed(1) : '') + '% of games): dropping or rescaling them makes the projection WORSE \u2014 a player who leaves early or gets eased in keeps scoring below his full-game rate, the partial game is information. <b>C. Teammate context</b> (past games played with a star teammate or the QB in a different state from this week count less): no gain. Live projections unchanged; kill window.SIM_NC_VEGEV = false.' + (EVC.live ? ' <b>Same fix on the LIVE Clay blend (not applied, Jack’s call):</b> ' + EVC.live.filter(function (r) { return r.variant === 'A Vegas-only k=1'; }).map(function (r) { return esc(r.cut) + ' ' + (r.d >= 0 ? '+' : '') + r.d.toFixed(2) + '% (' + r.wins + '/7)'; }).join(' · ') + '.' : '') + '</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Variant</th>' + evCuts.map(function (c) { return '<th>' + esc(c) + '</th>'; }).join('') + '</tr></thead><tbody>' + EVC.rows.map(evRow).join('') + '</tbody></table></div>';
      if (EVC.pos) html += '<p class="dim" style="font-size:11px;margin:6px 0">By position: ' + EVC.pos.map(function (r) { return esc(r.variant.replace('A Vegas-only ', '')) + ' ' + r.pos + ' ' + (r.d >= 0 ? '+' : '') + r.d.toFixed(2) + '% (' + r.wins + '/7)'; }).join(' \u00b7 ') + '.</p>';
    }
    var LCB = window.SIM_LIVECAND_BT;
    if (LCB && LCB.ladder) {
      var lcFw = {}; (LCB.forward || []).forEach(function (r) { lcFw[r.model] = r; });
      var lcRow = function (r) { var f = lcFw[r.model], hot = /^5|^6/.test(r.model); return '<tr' + (hot ? ' style="font-weight:600"' : '') + '><td class="l">' + esc(r.model) + '</td><td style="color:' + (r.d <= -0.3 && r.wins >= 5 ? 'var(--acc)' : 'inherit') + '">' + (r.d >= 0 ? '+' : '') + r.d.toFixed(2) + '% <span class="dim">(' + r.wins + '/7)</span></td><td class="dim">' + (r.step != null ? (r.step >= 0 ? '+' : '') + r.step.toFixed(2) : '') + '</td><td>' + r.rho.toFixed(4) + '</td><td>' + r.pairs.toFixed(2) + '%</td><td>' + r.rmse.toFixed(3) + '</td><td class="dim">' + (f ? (f.d >= 0 ? '+' : '') + f.d.toFixed(2) + '% (' + f.wins + '/5)' : '') + '</td></tr>'; };
      html += '<h4 style="margin:14px 0 4px">The combined LIVE CANDIDATE (backtest_live_candidate.py, ' + esc(LCB.updated || '') + ') \u2014 NOT applied, Jack\u2019s decision</h4>' +
        '<p class="dim" style="font-size:11px;margin:0 0 6px"><b>' + esc(LCB.summary || '') + '</b> Jack: "lets build the combined live candidate". The five fixes that each passed alone, stacked one at a time on today\u2019s live pre-book number (Clay per-game prior, 5-game strength, x Vegas x points-allowed); top 150 importance-weighted, final week dropped; last column = the same ladder with the shadow\u2019s learned prior fitted on earlier seasons only, 2021-25. The gains stack almost fully: steps 1-3 touch only the Clay blend (\u22121.6%, 7/7), step 4 adds nothing and can be skipped, the 70/30 mix with the shadow takes it to \u22122.5% (7/7; forward \u22122.7%, 5/5), and mixing ESPN 50/50 on top reaches \u22123.3% (7/7) with the best ranking measured. Once ESPN is in, the Clay side adds nothing (candidate + ESPN = shadow + ESPN). Weakest cuts: fantasy playoffs (\u22121.0%, 4/7 without ESPN; \u22122.8%, 6/7 with it), QB and TE (4/7). The live board then anchors 70% to book lines where they exist; that layer cannot be backtested and sits on top of whichever base is chosen.</p>';
      html += '<div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Step</th><th>Error vs today</th><th>Step</th><th>Rank \u03c1</th><th>Pairs right</th><th>Typical miss</th><th>Forward 2021-25</th></tr></thead><tbody>' + LCB.ladder.map(lcRow).join('') + '</tbody></table></div>';
      if (LCB.espn) html += '<p class="dim" style="font-size:11px;margin:6px 0">vs ESPN on ESPN-graded rows: ' + LCB.espn.filter(function (r) { return r.model !== 'ESPN'; }).map(function (r) { return esc(r.cut) + ' \u2014 ' + esc(r.model.split(':')[0]) + ' ' + (r.vsEspn >= 0 ? '+' : '') + r.vsEspn.toFixed(2) + '% (' + r.wins + '/7)'; }).join(' \u00b7 ') + '.</p>';
    }
    var few = Object.keys(B.flags || {}).filter(function (k) { return B.flags[k].verdict === 'too few'; });
    if (few.length) html += '<p class="dim" style="font-size:11px">Flags with too few player-weeks to grade (actual/shipped in parens): ' + few.map(function (k) { return esc(k) + ' n' + B.flags[k].n + (B.flags[k].ratio != null ? ' (' + B.flags[k].ratio.toFixed(2) + ')' : ''); }).join(' \u00b7 ') + '.</p>';
    if (B.buckets && B.buckets.length) {
      html += '<p class="dim" style="font-size:11px"><b>Tercile checks</b> (actual/shipped for low / mid / high thirds of each feature; a real edge would slope): ' +
        B.buckets.map(function (b) { return esc(b.name) + ' ' + b.terciles.map(function (t) { return t == null ? '\u2014' : t.toFixed(3); }).join(' / ') + ' (r ' + (b.corr >= 0 ? '+' : '') + b.corr.toFixed(3) + ')'; }).join(' \u00b7 ') + '.</p>';
    }
    return html;
  }
  function scNotesLines(S, team, opp) {
    // one line for the opposing defense + one for this offense (NOTES sheet)
    var out = [], d = S.def[opp], o = S.off[team], lg = S.lg, LR = lg.run || {}, L = lg.rec || {};
    function rk(k, sub, v) { var r = scRank(S, k, sub, v); return r ? ' #' + r.r : ''; }
    if (d) {
      var bits = [];
      var p = scPrior(S, opp), rel = scReliability(S, opp);
      function p25(k) { var v = p ? p[k] : null; return v != null ? ', 2025 ' + scPct(v) : ''; }
      if (d.man != null) bits.push('man ' + scPct(d.man) + rk('man', null, d.man) + ' (lg ' + scPct(lg.man) + p25('man') + ')');
      if (d.blitz != null) bits.push('blitz ' + scPct(d.blitz) + rk('blitz', null, d.blitz) + (p25('blitz') ? ' (' + p25('blitz').slice(2) + ')' : ''));
      if (d.prs != null) bits.push('pressure ' + scPct(d.prs) + rk('prs', null, d.prs) + (p25('prs') ? ' (' + p25('prs').slice(2) + ')' : ''));
      if (d.prwr != null) bits.push('rusher win ' + scPct(d.prwr));
      if (d.sBox != null) bits.push('S in box ' + scPct(d.sBox));
      if (d.run) {
        bits.push('run D ' + scNum(d.run.ypc, 1) + ' ypc' + rk('ypc', 'run', d.run.ypc) + ', ' + scNum(d.run.yco, 1) + ' after contact, edge runs ' + scPct(d.run.edge) + ' of carries faced');
        var m = scLaneMix(d.run.lanes);
        if (m && lg.lanes) {
          var hot = SC_LANES.filter(function (l) { return m.share[l] >= (lg.lanes[l] || 0) + 0.06; });
          if (hot.length) bits.push('gets run at ' + hot.map(function (l) { return l + ' ' + scPct(m.share[l]); }).join('/'));
        }
      }
      if (d.mtRate != null && lg.mtRate != null && d.mtRate >= lg.mtRate + 0.03) bits.push('missed tackles ' + scPct(d.mtRate) + ' (lg ' + scPct(lg.mtRate) + ')');
      var srcD = scSrc(S, opp, 'def'), pl = srcD && srcD.mode === 'coach' ? srcD.from + ' ' + srcD.season : '2025';
      out.push(opp + ' D scheme (PFF, ' + d.g + ' gm' + (rel ? '; ' + rel.label + ' vs ' + pl + ' ' + rel.ok + '/' + rel.n + (rel.flips.length ? ', flipped ' + rel.flips.join('/') : '') : '') + '): ' + bits.join(' \u00b7 '));
      if (scCoach(S, opp)) { var cl = scCoachLine(S, opp, 'def'), chh = scCoachHist(S, opp, 'def'); if (cl) out.push(opp + ' ' + cl + (chh ? ' \u2014 ' + chh : '')); }
    }
    if (o && (o.run || o.manSeen != null)) {
      var b2 = [];
      if (o.run) b2.push(scPct(o.run.gap) + ' gap / ' + scPct(1 - o.run.gap) + ' zone, edge ' + scPct(o.run.edge) + ', ' + scNum(o.run.ypc, 1) + ' ypc');
      if (o.manSeen != null) b2.push('sees man ' + scPct(o.manSeen) + ' (lg ' + scPct(L.manSeen) + ')');
      if (o.screen != null) b2.push('screens ' + scPct(o.screen));
      if (o.blitzFaced != null) b2.push('blitzed ' + scPct(o.blitzFaced) + ' / pressured ' + scPct(o.prsFaced));
      out.push(team + ' O style (PFF): ' + b2.join(' \u00b7 '));
      if (scCoach(S, team)) { var clo = scCoachLine(S, team, 'off'), cho = scCoachHist(S, team, 'off'); if (clo) out.push(team + ' ' + clo + (cho ? ' \u2014 ' + cho : '')); }
    }
    return out;
  }

  // ---------------- NOTES (video prep: TD-luck leaderboard + per-game sheet) ----------------
  // Jack 2026-09-15: "build the LUCK leaderboard and per-game notes sheet".
  // Leaderboard reads the shipped luck maps (sim_routes.js: SIM_RB_TDLUCK_2026 /
  // SIM_REC_TDLUCK_2026 / SIM_QB_TDLUCK_2026) and the engine's tdLuckAdj for the
  // points actually added this week. The game sheet calls the SAME engine
  // functions weeklyProjection uses (weatherMult, pressureMult, cbShadowMult,
  // cb1OutBoost, olOutDock, snapMult, routeMult, injAdj, tdLuckAdj) so every
  // chip is exactly what moved the number. Intel only.
  var NT_MIN_N = { QB: 30, RB: 10, WR: 8, TE: 8 };
  function ntF(v, d) { return (v == null || isNaN(v)) ? '—' : (+v).toFixed(d == null ? 1 : d); }
  function ntSigned(v, d) { return (v >= 0 ? '+' : '') + ntF(v, d); }
  function ntLuckRows(pos, sc) {
    var wnd = window;
    var m = pos === 'QB' ? wnd.SIM_QB_TDLUCK_2026 : (pos === 'RB' ? wnd.SIM_RB_TDLUCK_2026 : wnd.SIM_REC_TDLUCK_2026);
    if (!m) return [];
    var rows = [];
    Object.keys(m).forEach(function (nk) {
      var r = m[nk];
      var p = state.players.byNorm[nk];
      if (!p || p.pos !== pos || !r.g || (r.n || 0) < NT_MIN_N[pos]) return;
      rows.push({ p: p, nk: nk, r: r, luck: (r.xtd - r.td) / r.g, adj: E.tdLuckAdj(p, sc) });
    });
    return rows;
  }
  function ntLuckTable(rows, title, sc) {
    var html = '<table style="width:auto;min-width:420px"><thead><tr><th class="l" colspan="8">' + title + '</th></tr>' +
      '<tr><th class="l">Player</th><th>Tm</th><th>G</th><th>Touches</th><th>xTD</th><th>TD</th><th>Luck/g</th><th>Adj</th></tr></thead><tbody>';
    rows.forEach(function (o) {
      var col = o.adj > 0.05 ? 'var(--acc)' : (o.adj < -0.05 ? '#f85149' : 'var(--dim)');
      html += '<tr><td class="l"><b>' + esc(o.p.name) + '</b></td><td>' + o.p.tm + '</td><td>' + o.r.g + '</td><td>' + o.r.n + '</td><td>' + ntF(o.r.xtd, 2) +
        '</td><td>' + o.r.td + '</td><td>' + ntSigned(o.luck, 2) + '</td><td style="color:' + col + '"><b>' + ntSigned(o.adj, 2) + '</b></td></tr>';
    });
    return html + '</tbody></table>';
  }
  function renderLuckBoard(sc) {
    var html = '', text = [];
    ['QB', 'RB', 'WR', 'TE'].forEach(function (pos) {
      var rows = ntLuckRows(pos, sc);
      if (!rows.length) return;
      rows.sort(function (x, y) { return y.luck - x.luck; });
      // one side each: unlucky (luck > 0) vs lucky (luck < 0) - thin early-season pools must not overlap
      var up = rows.filter(function (o) { return o.luck >= 0.05; }).slice(0, 8);        // >= 1 TD over/under per 20 games is the floor
      var down = rows.filter(function (o) { return o.luck <= -0.05; }).sort(function (x, y) { return x.luck - y.luck; }).slice(0, 8);
      html += '<div style="display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start;margin-bottom:14px">' +
        '<div>' + ntLuckTable(up, pos + ' — DUE UP (unlucky so far)', sc) + '</div>' +
        '<div>' + ntLuckTable(down, pos + ' — DUE DOWN (lucky so far)', sc) + '</div></div>';
      text.push(pos + ' DUE UP: ' + up.slice(0, 5).map(function (o) { return o.p.name + ' (' + o.r.td + ' TD on ' + ntF(o.r.xtd, 1) + ' xTD, ' + ntSigned(o.adj, 1) + ')'; }).join('; '));
      text.push(pos + ' DUE DOWN: ' + down.slice(0, 5).map(function (o) { return o.p.name + ' (' + o.r.td + ' TD on ' + ntF(o.r.xtd, 1) + ' xTD, ' + ntSigned(o.adj, 1) + ')'; }).join('; '));
    });
    // Kickers: FG/XP luck = expected points from attempt distances - actual (backtest_k_fgluck.py:
    // accuracy over expected does NOT persist YoY, r .09). INTEL ONLY - the live K mean has no
    // realized half to correct, so there is no engine adjustment; ADJ shows the luck in points/game.
    var km = window.SIM_K_LUCK_2026 || {};
    var krows = Object.keys(km).map(function (nk) { var r = km[nk]; return { nk: nk, r: r, luck: r.g ? (r.xpts - r.pts) / r.g : 0 }; })
      .filter(function (o) { return o.r.g >= 1 && (o.r.att + o.r.xp) >= 4; });
    if (krows.length) {
      krows.sort(function (x, y) { return y.luck - x.luck; });
      var kup = krows.filter(function (o) { return o.luck >= 0.5; }).slice(0, 8);
      var kdown = krows.filter(function (o) { return o.luck <= -0.5; }).sort(function (x, y) { return x.luck - y.luck; }).slice(0, 8);
      function ktable(rows, title) {
        var h = '<table style="width:auto;min-width:420px"><thead><tr><th class="l" colspan="7">' + title + '</th></tr>' +
          '<tr><th class="l">Kicker</th><th>G</th><th>FGA</th><th>XPA</th><th>xPts</th><th>Pts</th><th>Luck/g</th></tr></thead><tbody>';
        rows.forEach(function (o) {
          var col = o.luck >= 0.5 ? 'var(--acc)' : (o.luck <= -0.5 ? '#f85149' : 'var(--dim)');
          h += '<tr><td class="l"><b>' + esc(o.r.name) + '</b></td><td>' + o.r.g + '</td><td>' + o.r.att + '</td><td>' + o.r.xp + '</td><td>' + ntF(o.r.xpts, 1) +
            '</td><td>' + o.r.pts + '</td><td style="color:' + col + '"><b>' + ntSigned(o.luck, 1) + '</b></td></tr>';
        });
        return h + '</tbody></table>';
      }
      html += '<div style="display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start;margin-bottom:14px">' +
        '<div>' + ktable(kup, 'K — DUE UP (missed kicks the distances say he makes)') + '</div>' +
        '<div>' + ktable(kdown, 'K — DUE DOWN (made more than the distances say)') + '</div></div>' +
        '<p class="dim" style="font-size:11px;margin-top:-6px">Kicker accuracy over expected does not persist (YoY r .09; backtest_k_fgluck.py) — a miss streak is luck, not a slump. Intel only: the engine\'s kicker mean is Clay × level × Vegas × kicking-points lines and carries no realized half to correct.</p>';
      text.push('K DUE UP: ' + kup.slice(0, 5).map(function (o) { return o.r.name + ' (' + o.r.pts + ' pts on ' + ntF(o.r.xpts, 1) + ' expected, ' + ntSigned(o.luck, 1) + '/g)'; }).join('; '));
      text.push('K DUE DOWN: ' + kdown.slice(0, 5).map(function (o) { return o.r.name + ' (' + o.r.pts + ' pts on ' + ntF(o.r.xpts, 1) + ' expected, ' + ntSigned(o.luck, 1) + '/g)'; }).join('; '));
    }
    // DST: points riding def/ST TDs (backtest_dst_regression.py: TDs early->late r .06, YoY .11 -
    // pure noise; NO realized component beats the Vegas-only DST mean). INTEL ONLY.
    var dm = window.SIM_DST_LUCK_2026 || {};
    var drows = Object.keys(dm).map(function (t) { var r = dm[t]; return { t: t, r: r, tdpg: r.g ? r.td / r.g : 0, ppg: r.g ? r.pts / r.g : 0 }; })
      .filter(function (o) { return o.r.g >= 1; });
    if (drows.length) {
      drows.sort(function (x, y) { return y.tdpg - x.tdpg; });
      var riding = drows.filter(function (o) { return o.tdpg >= 3; }).slice(0, 8);        // >= half a TD per game over the .73 league rate
      var dtable = '<table style="width:auto;min-width:460px"><thead><tr><th class="l" colspan="7">DST — RIDING TDs (def/ST TD points are noise: YoY r .11)</th></tr>' +
        '<tr><th class="l">Team</th><th>G</th><th>Pts/g</th><th>TD pts/g</th><th>Sacks/g</th><th>TO pts/g</th><th>PA pts/g</th></tr></thead><tbody>';
      riding.forEach(function (o) {
        var g = o.r.g;
        dtable += '<tr><td class="l"><b>' + o.t + '</b></td><td>' + g + '</td><td>' + ntF(o.ppg, 1) + '</td><td style="color:#f85149"><b>' + ntF(o.tdpg, 1) + '</b> <span class="dim" style="font-size:11px">(lg 0.7)</span></td><td>' +
          ntF(o.r.sack / g, 1) + '</td><td>' + ntF(o.r.to / g, 1) + '</td><td>' + ntF(o.r.pa / g, 1) + '</td></tr>';
      });
      dtable += '</tbody></table>';
      html += '<div style="margin-bottom:14px">' + (riding.length ? dtable : '<p class="dim">No DST is riding defensive TDs right now.</p>') +
        '<p class="dim" style="font-size:11px">A DST whose season-to-date points come from return/defensive TDs is over-rated by everyone else; the sims never counted them (DST mean = opponent implied total only).</p></div>';
      if (riding.length) text.push('DST RIDING TDs: ' + riding.slice(0, 5).map(function (o) { return o.t + ' (' + ntF(o.tdpg, 1) + ' TD pts/g of ' + ntF(o.ppg, 1) + ')'; }).join('; '));
    }
    // xFP leaderboard: points over / under expected per game (standard usage-based xFP,
    // SIM_XFP_2026 components) with the TD share of the gap - the part that regresses.
    var xrows = [];
    state.players.list.forEach(function (p) {
      if (p.isDST || ['QB', 'RB', 'WR', 'TE'].indexOf(p.pos) < 0) return;
      var xf = ntXfp(p, sc);
      if (!xf || xf.fpoeg == null || xf.g < 1) return;
      var m = p.pos === 'QB' ? window.SIM_QB_TDLUCK_2026 : (p.pos === 'RB' ? window.SIM_RB_TDLUCK_2026 : window.SIM_REC_TDLUCK_2026);
      var r = m && m[p.norm];
      var tdPts = p.pos === 'QB' ? sc.pass_td : sc.rec_td;
      var tdPart = (r && r.g) ? -tdPts * (r.xtd - r.td) / r.g : null;   // TD points over expected per game
      xrows.push({ p: p, xf: xf, tdPart: tdPart });
    });
    if (xrows.length) {
      function xtable(rows, title) {
        var h = '<table style="width:auto;min-width:520px"><thead><tr><th class="l" colspan="8">' + title + '</th></tr>' +
          '<tr><th class="l">Player</th><th>Tm</th><th>G</th><th>PPG</th><th>xFP/g</th><th>FPOE/g</th><th>TD part</th><th>Skill part</th></tr></thead><tbody>';
        rows.forEach(function (o) {
          var f = o.xf.fpoeg, col = f <= -1.5 ? 'var(--acc)' : (f >= 1.5 ? '#f85149' : 'var(--dim)');
          h += '<tr><td class="l"><b>' + esc(o.p.name) + '</b> <span class="dim">' + o.p.pos + '</span></td><td>' + o.p.tm + '</td><td>' + o.xf.g + '</td><td>' + ntF(o.xf.ppg, 1) +
            '</td><td>' + ntF(o.xf.xfpg, 1) + '</td><td style="color:' + col + '"><b>' + ntSigned(f, 1) + '</b></td>' +
            '<td>' + (o.tdPart != null ? ntSigned(o.tdPart, 1) : '—') + '</td><td>' + (o.tdPart != null ? ntSigned(f - o.tdPart, 1) : '—') + '</td></tr>';
        });
        return h + '</tbody></table>';
      }
      var byPos = {};
      xrows.forEach(function (o) { (byPos[o.p.pos] = byPos[o.p.pos] || []).push(o); });
      html += '<h3 style="margin-top:6px">EXPECTED FANTASY POINTS <span class="dim" style="font-weight:normal;font-size:12px">2026 to date · standard usage-based xFP · FPOE = actual − expected · TD part regresses, skill part mostly repeats</span></h3>';
      ['QB', 'RB', 'WR', 'TE'].forEach(function (pos) {
        var rows = byPos[pos]; if (!rows) return;
        rows.sort(function (x, y) { return y.xf.fpoeg - x.xf.fpoeg; });
        var over = rows.filter(function (o) { return o.xf.fpoeg >= 1.5; }).slice(0, 8);
        var under = rows.filter(function (o) { return o.xf.fpoeg <= -1.5; }).sort(function (x, y) { return x.xf.fpoeg - y.xf.fpoeg; }).slice(0, 8);
        html += '<div style="display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start;margin-bottom:14px">' +
          '<div>' + xtable(under, pos + ' — UNDER EXPECTED (scoring below his usage)') + '</div>' +
          '<div>' + xtable(over, pos + ' — OVER EXPECTED (scoring above his usage)') + '</div></div>';
        text.push('XFP UNDER ' + pos + ': ' + under.slice(0, 5).map(function (o) { return o.p.name + ' (' + ntF(o.xf.ppg, 1) + ' vs ' + ntF(o.xf.xfpg, 1) + ' xFP, ' + ntSigned(o.xf.fpoeg, 1) + (o.tdPart != null ? ', TD ' + ntSigned(o.tdPart, 1) : '') + ')'; }).join('; '));
        text.push('XFP OVER ' + pos + ': ' + over.slice(0, 5).map(function (o) { return o.p.name + ' (' + ntF(o.xf.ppg, 1) + ' vs ' + ntF(o.xf.xfpg, 1) + ' xFP, ' + ntSigned(o.xf.fpoeg, 1) + (o.tdPart != null ? ', TD ' + ntSigned(o.tdPart, 1) : '') + ')'; }).join('; '));
      });
    }
    $('nt-luck').innerHTML = html || '<p class="dim">No luck data yet (maps fill after the first 2026 games).</p>';
    return text;
  }
  function ntPressure(team) {
    var m = window.SIM_PRESSURE_2026; if (!m || !m[team]) return null;
    var p = 0, n = 0; Object.keys(m).forEach(function (t) { p += m[t][0]; n += m[t][1]; });
    if (n < 500 || m[team][1] < 40) return null;
    return { rate: m[team][0] / m[team][1], lg: p / n, n: m[team][1] };
  }
  function ntPace(team) {
    var d = window.SIM_PACE_2026; var t = d && d.teams && d.teams[team]; if (!t || !t.cur || !t.games) return null;
    return t;
  }
  function ntFpa(def) {
    var d = window.SIM_2026; if (!d || !d.fpa || !d.fpa[def] || !d.lgFpa) return null;
    return { f: d.fpa[def], lg: d.lgFpa };
  }
  function ntTeamBlock(team, opp, wk, slot) {
    var lines = [];
    var pc = ntPace(team);
    if (pc) {
      var c = pc.cur, b = pc.base || {};
      lines.push('Pace (' + pc.games + ' gm): ' + ntF(c.plays, 1) + ' plays/gm' + (b.plays != null ? ' (base ' + ntF(b.plays, 1) + ', ' + ntSigned(c.plays - b.plays, 1) + ')' : '') +
        ' · neutral pass ' + ntF(100 * c.npr, 0) + '%' + (b.npr != null ? ' (base ' + ntF(100 * b.npr, 0) + '%)' : '') +
        ' · PROE ' + ntSigned(c.proe, 1) + (b.proe != null ? ' (base ' + ntSigned(b.proe, 1) + ')' : ''));
    }
    var fp = ntFpa(opp);
    if (fp) {
      lines.push('vs ' + opp + ' D allows (' + (fp.f._g || '?') + ' gm): ' + ['QB', 'RB', 'WR', 'TE'].map(function (pos) {
        var v = fp.f[pos], l = fp.lg[pos]; if (v == null || !l) return pos + ' —';
        var pct = 100 * (v / l - 1); return pos + ' ' + ntF(v, 1) + ' (' + ntSigned(pct, 0) + '%)';
      }).join(' · '));
    }
    var pr = ntPressure(opp);
    if (pr) lines.push(opp + ' pass rush: ' + ntF(100 * pr.rate, 1) + '% hit/sack rate vs lg ' + ntF(100 * pr.lg, 1) + '%' + (pr.rate <= pr.lg - 0.02 ? ' — SOFT (QB boost live)' : (pr.rate >= pr.lg + 0.03 ? ' — heavy' : '')));
    var cb = window.SIM_CB1_2026 && window.SIM_CB1_2026[opp];
    if (cb) lines.push(opp + ' CB1: ' + cb.name + (cb.out ? ' — OUT (WR boost live)' : ' active'));
    var ol = window.SIM_OL_2026 && window.SIM_OL_2026[team];
    if (ol) lines.push(team + ' OL: ' + ol + ' starter' + (ol > 1 ? 's' : '') + ' out (dock live)');
    if (scS()) scNotesLines(scS(), team, opp).forEach(function (s) { lines.push(s); });
    // DEFENSE AVAILABILITY intel (sleeper_meta.js SIM_DEF_AVAIL_2026; backtest_def_avail.py). Confirmed = IR/PUP/NA/Sus
    // or the current week's NFL report Out/Doubtful; Sleeper Out/Doubtful alone = unconfirmed ("?").
    var DA = window.SIM_DEF_AVAIL_2026;
    if (DA && DA.teams && DA.teams[opp]) {
      var miss = [], qlost = 0;
      DA.teams[opp].forEach(function (d) {
        var gs = String(d.gs || '').toLowerCase(), sl = String(d.sl || '');
        var nflNow = DA.prWeek != null && +DA.prWeek === +wk;
        var conf = /\b(IR|PUP|NFI|NA|Sus)/i.test(sl) || /inactive/i.test(sl) || (nflNow && (gs === 'out' || gs === 'doubtful'));
        var unconf = !conf && /^(Out|Doubtful)/i.test(sl);
        var q = !conf && !unconf && (/^Questionable/i.test(sl) || (nflNow && gs === 'questionable'));
        if (!conf && !unconf && !q) return;
        var lab = conf ? (nflNow && gs ? gs.charAt(0).toUpperCase() + gs.slice(1) : sl) : unconf ? sl + '?' : 'Q';
        miss.push({ t: d.pos + ' ' + d.n + ' (' + (d.g != null ? d.g.toFixed(0) : '?') + ', ' + lab + ')', g: d.g || 0, out: conf || unconf });
        if (conf || unconf) qlost += Math.max(0, (d.g || 55) - 55) / 10 * (d.sh || 0.8);
      });
      if (miss.length) {
        miss.sort(function (x, y) { return (y.out - x.out) || (y.g - x.g); });
        lines.push(opp + ' D availability: ' + miss.map(function (m) { return m.t; }).join(' \u00b7 ') + (qlost >= 0.5 ? ' \u2014 quality lost ' + qlost.toFixed(1) + ' (grade pts above 55 / 10, snap-weighted)' : '') + ' [intel]');
      }
    }
    return lines;
  }
  function ntWeather(home, wk) {
    var m = window.SIM_WEATHER_2026; var t = m && (m[home] || m[E.normTeam(home)]); var w = t && (t[wk] || t[String(wk)]);
    if (!w) return 'Weather: dome / no forecast in window';
    return 'Weather @' + home + ': wind ' + w.wind + ' mph' + (w.gust != null ? ' (gusts ' + w.gust + ')' : '') + ', ' + w.temp + '°F' + (w.pop != null ? ', ' + w.pop + '% precip' : '') +
      (w.wind >= 15 ? ' — WIND DOCK live (QB/WR/TE/K)' : (w.wind >= 10 ? ' — mild wind dock live' : ''));
  }
  // Season-to-date expected fantasy points per game (standard xFP, the same
  // per-game components the site card uses: SIM_XFP_2026 from
  // pull_pace_tracker.py) and points over expected vs the player's actual
  // PPG (SIM_2026, re-scored to the sheet's format like jsBasePg does).
  function ntXfp(p, sc) {
    var X = window.SIM_XFP_2026 && window.SIM_XFP_2026[p.norm];
    if (!X || !X.w || p.pos === 'K' || p.pos === 'DST') return null;
    var n = 0, x = 0;
    Object.keys(X.w).forEach(function (wk) {
      var c = X.w[wk]; n++;
      if (p.pos === 'QB') x += sc.pass_yd * c[1] + sc.pass_td * c[2] + sc.rush_yd * c[4] + sc.rush_td * c[5] - 1 * (c[6] || 0);   // c[6] = expected INTs (Sleeper -1 each, like the ppg below)
      else x += sc.rec * c[1] + sc.rec_yd * c[2] + sc.rec_td * c[3] + sc.rush_yd * c[5] + sc.rush_td * c[6];
    });
    if (!n) return null;
    var d = (window.SIM_2026 && window.SIM_2026.players) ? window.SIM_2026.players[p.norm] : null;
    var ppg = null;
    if (d && d.g) {
      var pg = d.pg || {};
      ppg = d.ppg + (sc.rec - 0.5) * (pg.rec || 0) + (sc.pass_td - 4) * (pg.ptd || 0) + (sc.pass_yd - 0.04) * (pg.py || 0)
        + (sc.rush_yd - 0.1) * (pg.ry || 0) + (sc.rec_yd - 0.1) * (pg.rcy || 0) + (sc.rush_td - 6) * (pg.rtd || 0) + (sc.rec_td - 6) * (pg.rctd || 0);
    }
    return { g: n, xfpg: x / n, ppg: ppg, fpoeg: ppg != null ? ppg - x / n : null };
  }
  function ntPlayerChips(p, wk, sc, slot, wp) {
    var chips = [];
    var iA = E.injAdj(p, wk);
    if (iA === 0) chips.push('OUT');
    else if (iA < 1) {
      var im = E.injuryState() && E.injuryState().map ? E.injuryState().map[p.norm] : null;
      chips.push((im && im.src === 'out-unconfirmed' ? 'OUT flag unconfirmed (Sleeper still projects him) ×' : im && /^q-(dnp|lp|fp)$/.test(im.src || '') ? ('Q + ' + im.src.slice(2).toUpperCase() + (im.play != null ? ' (plays ' + Math.round(100 * im.play) + '%, x' + im.cond.toFixed(2) + ' if he plays)' : '') + ' ×') : im && /doubtful/.test(im.src || '') ? ('DOUBTFUL' + (im.play != null ? ' (plays ' + Math.round(100 * im.play) + '%)' : im.src === 'doubtful-unconfirmed' ? ' unconfirmed' : '') + ' ×') : 'docked ×') + ntF(iA, 2));
    }
    else if (iA > 1.02) chips.push('role boost ×' + ntF(iA, 2));
    if (wp && /\+nmu\+/.test(wp.ncSrc || '')) chips.push('next man up: target-share teammate out (lift)');
    else if (wp && /\+nmu-/.test(wp.ncSrc || '')) chips.push('next man up: target-share teammate out (#2-3 trim)');
    if (p.isDST) return chips;
    // INJURY SIGNALS (2026-10-01): injury on the report, day-by-day practice, books with lines up, the news read
    if (E.injSignalInfo) {
      var isg = E.injSignalInfo(p, wk), desig = /Questionable|Doubtful|Out|IR|PUP/i.test(String(p.injFlag || ''));
      if (isg && (iA < 1 || isg.seq || isg.news || desig)) {
        var ib = [];
        if (isg.inj || isg.body) ib.push(isg.inj || isg.body);
        if (isg.seq) ib.push('practice ' + isg.seq);
        if (isg.lines != null && (iA < 1 || isg.gs || desig)) ib.push(isg.lines ? 'lines up at ' + isg.lines + ' book' + (isg.lines > 1 ? 's' : '') : 'no lines up');
        if (isg.news && isg.news.flag) ib.push('news: ' + ({ play: 'expected to play', doubt: 'unlikely to play', gtd: 'game-time decision' }[isg.news.flag.k] || isg.news.flag.k));
        if (isg.news && isg.news.expert) ib.push('analyst: ' + String(isg.news.expert.hl || '').slice(0, 70));
        if (/^(news|dx-)/.test(isg.src || '') && isg.note) ib.push(({ 'news-season': 'out for the season', 'dx-season': 'out for the season', 'news-out': 'ruled out', 'news-return': 'return window', news: 'reported timeline' }[isg.src] || isg.src) + ' (' + isg.note.slice(0, 80) + ')');
        if (ib.length) chips.push('INJ: ' + ib.join(' · '));
      }
    }
    var l = E.tdLuckAdj(p, sc) * Math.min(1, iA);
    if (Math.abs(l) >= 0.05) chips.push('TD luck ' + ntSigned(l, 1));
    var w = E.weatherMult(p, wk, slot); if (w !== 1) chips.push('weather ×' + ntF(w, 2));
    var pr = E.pressureMult(slot.opp, p.pos); if (pr !== 1) chips.push('soft rush ×' + ntF(pr, 2));
    var cs = E.cbShadowMult(slot.opp, p.pos, p); if (cs !== 1) chips.push('CB shadow ×' + ntF(cs, 2));
    var cb = E.cb1OutBoost(slot.opp, p.pos, p); if (cb !== 1) chips.push('CB1 out ×' + ntF(cb, 2));
    var ol = E.olOutDock(p.tm, p.pos); if (ol !== 1) chips.push('OL out ×' + ntF(ol, 2));
    if (wp && wp.health > 0) chips.push('healthy-prior +' + ntF(wp.health, 1) + '/g');   // banged-up prior lift (2026-10-07)
    if (wp && wp.use && wp.use.hurtG > 0) chips.push('usage: ' + wp.use.hurtG + ' banged-up game' + (wp.use.hurtG > 1 ? 's' : '') + ' ×0.5');
    if (wp && wp.vol != null && Math.abs(wp.vol - 1) >= 0.005) chips.push('pass volume ×' + ntF(wp.vol, 2));   // volume context (2026-10-07)
    if (wp && wp.bb) chips.push('base: ' + Math.round(100 * wp.bb) + '% Clay-free shadow (' + ntF(wp.ncMean, 1) + ') for weeks ahead');
    var sn = E.snapMult(p, wk); if (Math.abs(sn - 1) >= 0.02) chips.push('snap trend ×' + ntF(sn, 2));
    var rkL = E.rookieLevel ? E.rookieLevel(p) : 1; if (rkL !== 1) chips.push('rookie level ×' + ntF(rkL, 2));
    var rbU = E.rbUsagePg ? E.rbUsagePg(p, wk) : null; if (rbU) chips.push('snap usage ' + ntF(rbU.share, 0) + '% x ' + ntF(rbU.plays, 0) + ' plays = ' + ntF(rbU.half, 1) + ' half-PPR/g (15% blend)');
    var cx = E.ctxNote(p, wk); if (cx.length) chips.push('blowout ' + cx.join('/') + ': role read on competitive snaps');
    var rt = E.routeMult(p, wk); if (Math.abs(rt - 1) >= 0.02) chips.push('route trend ×' + ntF(rt, 2));
    if (E.ascendingFlag(p, wk)) chips.push('ASCENDING (age ' + p.age + ', yr ' + (p.exp + 1) + ', snaps+routes up) - shadow');
    var nf = E.newsFlags(p);
    if (nf) { var np_ = []; if (nf.riser) np_.push('+' + nf.riser + ' riser'); if (nf.faller) np_.push(nf.faller + ' faller'); if (!nf.riser && !nf.faller) { if (nf.injury) np_.push(nf.injury + ' injury'); if (nf.role) np_.push(nf.role + ' role'); } chips.push('REPORTS ' + np_.join(', ') + ' (10d) - shadow'); }
    if (wp && wp.propMean != null && wp.jsMean != null && Math.abs(wp.propMean - wp.jsMean) >= 1.5) {
      chips.push('market ' + (wp.propMean > wp.jsMean ? 'higher' : 'lower') + ' (' + ntF(wp.propMean, 1) + ' vs model ' + ntF(wp.jsMean, 1) + ')');
    }
    return chips;
  }
  // ---------------- WHY notes + MATCHUP EDGES (Jack 2026-09-16: "build the per-player why notes for videos ... also
  // highlight players with the biggest advanced weekly matchups positives and negatives") ----------------
  // ntWhy turns weeklyProjection's why pieces into a points waterfall in the engine's own order, so the steps add up
  // to the model number exactly; the market step closes the gap to PROJ. ntShadowWhy adds the learned shadow's top
  // drivers (half-PPR, path attribution; shadow only). ntMatchup scores the week's matchup in % of the projection:
  // PRICED = layers already inside PROJ (opponent FPA / Clay grade, pass rush, CB, OL, wind); INTEL = advanced reads
  // the backtests did NOT validate as projection inputs (coverage fit, pressure vs the QB's splits, run defense,
  // target zones, defensive injuries) - for content, not for changing the number.
  var NT_FEAT_LABEL = { HAND: 'size of the projection', snap_l1: 'last-game snap share', snap_std: 'season snap share', snap_trend: 'snap trend', plays_pg_std: 'team pace',
    clay: 'Clay level', ppg: 'PPG so far', g: 'games played', wk: 'week of season', blend: 'Clay/PPG blend', veg: 'team total', implied: 'team total', game_total: 'game total',
    spread: 'spread', fpa_mult: 'opponent FPA', snapmult: 'snap-trend layer', td_luck_pg: 'TD luck', td_luck_adj: 'TD luck', cond_mult: 'injury tag', rep_q: 'Questionable tag',
    prac_dnp: 'missed practice', prac_lim: 'limited practice', rookie_mult: 'rookie', usage_half: 'snap usage', weather_mult: 'wind', wind: 'wind', pool_mult: 'vacated work',
    qb_inherit_mult: 'backup QB role', pos_qb: 'position', pos_rb: 'position', pos_wr: 'position', pos_te: 'position' };
  function ntWhy(p, wk, sc, slot, wp) {
    var w = wp && wp.why; if (!w || p.isDST) return null;
    var steps = [], all = [], run = w.clayPg0 != null ? w.clayPg0 : w.clayPg;   // start from Clay's own number; the banged-up lift is its own step
    // lab = Sim Lab wording (NOTES); pub = plain wording for the main-site player card
    var push = function (key, d, lab, pub) { all.push({ key: key, d: d, lab: lab, pub: pub || lab }); if (Math.abs(d) >= 0.1) steps.push({ key: key, d: d, lab: lab, pub: pub || lab }); };
    var rec = window.SIM_2026 && window.SIM_2026.players ? window.SIM_2026.players[p.norm] : null;
    if (w.health > 0) push('health', w.health, 'healthy prior +' + ntF(w.health, 1) + ' (last season he outscored this baseline when healthy; 3+ games played hurt)', 'last season he outscored his preseason baseline in the games he was healthy');
    if (rec && rec.g) push('form', w.jsBase - w.clayPg, '2026 form (' + ntF(rec.ppg, 1) + ' half PPG in ' + rec.g + ' gm, ' + Math.round(100 * rec.g / (5 + rec.g)) + '% weight)',
      '2026 production so far (' + rec.g + ' game' + (rec.g > 1 ? 's' : '') + ', ' + Math.round(100 * rec.g / (5 + rec.g)) + '% weight vs the preseason baseline)');
    push('rookie', w.jsPgRook - w.jsBase, 'rookie level x' + ntF(w.rook, 2), 'rookie role growth (rookies outscore their early numbers)');
    if (w.usage) push('usage', w.jsPg - w.jsPgRook, 'snap usage ' + ntF(w.usage.share, 0) + '% x ' + ntF(w.usage.plays, 0) + ' plays', 'snap share ' + ntF(w.usage.share, 0) + '% of ' + ntF(w.usage.plays, 0) + ' team plays per game');
    run = w.jsPg;
    var fp = ntFpa(slot.opp), oppLab = 'opp ' + slot.opp, oppPub = slot.opp + ' defense';
    if (fp && fp.f[p.pos] != null && fp.lg[p.pos]) { var fpp = ntSigned(100 * (fp.f[p.pos] / fp.lg[p.pos] - 1), 0); oppLab += ' allows ' + fpp + '% to ' + p.pos + 's (' + (fp.f._g || '?') + ' gm)'; oppPub = slot.opp + ' allows ' + fpp + '% fantasy points to ' + p.pos + 's (' + (fp.f._g || '?') + ' gm, blended with its preseason grade)'; }
    else if (Math.abs(w.dAdj - 1) >= 0.01) { oppLab += ' (Clay unit grade x' + ntF(w.dAdj, 2) + ')'; oppPub = slot.opp + ' defense grade vs ' + p.pos + 's'; }
    var im = E.injuryState() && E.injuryState().map ? E.injuryState().map[p.norm] : null;
    var avLab = w.iA > 1 ? (p.pos === 'QB' ? 'starting QB out: backup inherits 85% of his level' : 'vacated work from injured teammates x' + ntF(w.iA, 2)) : (im ? 'availability ' + (im.src || '') + ' x' + ntF(w.iA, 2) : 'availability x' + ntF(w.iA, 2));
    var avPub = w.iA > 1 ? (p.pos === 'QB' ? 'starting QB out - he takes over the job' : 'extra targets / carries from injured teammates') : 'injury status (' + (im && im.src ? String(im.src).replace(/-/g, ' ') : 'designated') + ')';
    var sn = window.SIM_SNAPS_2026 ? window.SIM_SNAPS_2026[p.name] : null, snLab = 'snap trend', snPub = 'snap share trend';
    if (sn && sn.w) { var sw = Object.keys(sn.w).map(Number).filter(function (x) { return x < wk; }).sort(function (x, y) { return x - y; }); if (sw.length >= 2) { var sLast = ntF(sn.w[sw[sw.length - 1]], 0), sAvg = ntF(sw.reduce(function (t, x) { return t + sn.w[x]; }, 0) / sw.length, 0); snLab += ' (last ' + sLast + '% vs avg ' + sAvg + '%)'; snPub += ' (last game ' + sLast + '% vs ' + sAvg + '% season)'; } }
    [['vegas', w.veg, 'Vegas (' + p.tm + ' implied ' + ntF(w.implied, 1) + ' vs avg ' + ntF(w.avgImplied, 1) + ')', 'Vegas team total (' + p.tm + ' ' + ntF(w.implied, 1) + ' vs ' + ntF(w.avgImplied, 1) + ' league avg)'],
     ['opp', w.opp, oppLab, oppPub], ['cbShadow', w.cbShadow, 'CB shadow', 'shadowed by a top cornerback'],
     ['cb1Out', w.cb1Out, slot.opp + ' CB1 out', slot.opp + ' top cornerback out'], ['olOut', w.olOut, p.tm + ' OL starters out', p.tm + ' offensive line starters out'],
     ['pressure', w.pressure, 'soft pass rush', slot.opp + ' soft pass rush'], ['weather', w.weather, 'wind', 'wind forecast'],
     ['snap', w.snap, snLab, snPub], ['route', w.route, 'route trend', 'route share trend'], ['ramp', w.ramp, 'return-from-injury ramp', 'first games back from injury'], ['avail', w.iA, avLab, avPub], ['vol', w.vol, 'pass-volume context (' + p.tm + ' script-driven throws' + (slot.spread > 0 ? ', underdog' : '') + ')', 'team pass volume so far that tends not to last']].forEach(function (m) {
      if (m[1] == null || m[1] === 1) return;
      var d = run * (m[1] - 1); run *= m[1]; push(m[0], d, m[2], m[3]);
    });
    var lm = (p.pos === 'QB' ? window.SIM_QB_TDLUCK_2026 : (p.pos === 'RB' ? window.SIM_RB_TDLUCK_2026 : window.SIM_REC_TDLUCK_2026)) || null, lr = lm ? lm[p.norm] : null;
    push('luck', w.luck, 'TD luck (' + (lr ? lr.td + ' TD on ' + ntF(lr.xtd, 1) + ' expected' : 'regression') + ')',
      'TD regression (' + (lr ? lr.td + ' TD' + (lr.td === 1 ? '' : 's') + ' on ' + ntF(lr.xtd, 1) + ' expected from where he got the ball' : 'scoring back toward his usage') + ')');
    var modelPre = Math.max(0, run + w.luck);
    if (w.bb) push('blend', w.jsMean - modelPre, Math.round(100 * w.bb) + '% Clay-free shadow (' + ntF(w.ncMean, 1) + ') for weeks ahead', 'blended with our history-based model for the weeks ahead');
    var model = w.bb ? w.jsMean : modelPre, eff = E.effMean(wp);
    var mk = eff - model;
    var mkLab = wp.propSrc === 'line' ? 'books\' lines (' + ntF(wp.propMean, 1) + ', anchored ' + Math.round(100 * (wp.propW || 0.7)) + '%)' : wp.propSrc === 'rate' ? 'market rate from other weeks (' + ntF(wp.propMean, 1) + ')' : 'market / effective mean';
    var mkPub = wp.propSrc === 'line' ? 'sportsbook player props (they imply ' + ntF(wp.propMean, 1) + ')' : wp.propSrc === 'rate' ? 'sportsbook props from his other weeks' : 'market adjustment';
    all.push({ key: 'market', d: mk, lab: mkLab, pub: mkPub });
    if (Math.abs(mk) >= 0.1) steps.push({ key: 'market', d: mk, lab: mkLab, pub: mkPub });
    var top = steps.slice().sort(function (x, y) { return Math.abs(y.d) - Math.abs(x.d); })[0];
    var clay0 = w.clayPg0 != null ? w.clayPg0 : w.clayPg;
    var text = 'PROJ ' + ntF(eff, 1) + ' = Clay ' + ntF(clay0, 1) + steps.map(function (s) { return ' \u00b7 ' + s.lab + ' ' + ntSigned(s.d, 1); }).join('') +
      (top ? ' \u2014 biggest driver: ' + top.lab.split(' (')[0] + ' ' + ntSigned(top.d, 1) : '');
    return { text: text, steps: steps, all: all, model: model, eff: eff, top: top, clay: clay0 };
  }
  // main-site export (export_notes.js --repo -> data/proj_why_2026.json, player card WEEKLY tab "Why this projection")
  window.SimLabWhy = function (wk) {
    wk = +wk || +(document.getElementById('nt-week') || {}).value || state.injuryWeek || 1;
    var fmts = [E.PRESETS.half, E.PRESETS.ppr, E.PRESETS.std], out = {};
    var r2 = function (v) { return Math.round(v * 100) / 100; };
    state.players.list.forEach(function (p) {
      if (p.isDST || ['QB', 'RB', 'WR', 'TE'].indexOf(p.pos) < 0) return;
      var slot = state.schedule.byTeam[p.tm] && state.schedule.byTeam[p.tm][wk]; if (!slot) return;
      var ws = fmts.map(function (sc) { var wp = E.weeklyProjection(p, wk, sc, state.schedule); return wp ? ntWhy(p, wk, sc, slot, wp) : null; });
      if (!ws[0] || ws[0].eff < 1) return;
      var keys = [], lab = {};
      ws.forEach(function (x) { if (x) x.all.forEach(function (s) { if (keys.indexOf(s.key) < 0) { keys.push(s.key); lab[s.key] = s.pub; } }); });
      var steps = keys.map(function (k) {
        var d = ws.map(function (x) { if (!x) return 0; var s = x.all.filter(function (y) { return y.key === k; })[0]; return s ? r2(s.d) : 0; });
        return { k: k, l: lab[k], d: d };
      }).filter(function (s) { return s.d.some(function (v) { return Math.abs(v) >= 0.1; }); });
      out[p.name] = { pos: p.pos, tm: p.tm, opp: slot.opp, home: !!slot.home, c: ws.map(function (x) { return x ? r2(x.clay) : null; }), p: ws.map(function (x) { return x ? r2(x.eff) : null; }), s: steps };
    });
    return { week: wk, generated: new Date().toISOString(), players: out };
  };
  function ntShadowWhy(p, wk) {
    if (!E.learnedShadowExplain || p.isDST) return null;
    var x = E.learnedShadowExplain(p, wk, state.schedule); if (!x || x.corr == null || Math.abs(x.corr) < 0.3) return null;
    var g = {};
    Object.keys(x.contrib).forEach(function (k) { var lab = NT_FEAT_LABEL[k] || k; g[lab] = (g[lab] || 0) + x.contrib[k]; });
    var top = Object.keys(g).map(function (k) { return [k, g[k]]; }).filter(function (t) { return Math.abs(t[1]) >= 0.1; }).sort(function (u, v) { return Math.abs(v[1]) - Math.abs(u[1]); }).slice(0, 3);
    return 'learned shadow ' + ntSigned(x.corr, 1) + ' half-PPR (not in PROJ)' + (top.length ? ': ' + top.map(function (t) { return t[0] + ' ' + ntSigned(t[1], 1); }).join(', ') : '');
  }
  var NT_COV = { CB: 1, S: 1, FS: 1, SS: 1, DB: 1, NB: 1 }, NT_FRONT = { DE: 1, DT: 1, DL: 1, NT: 1, EDGE: 1, LB: 1, ILB: 1, OLB: 1, MLB: 1 };
  function ntClamp(v, a) { return Math.max(-a, Math.min(a, v)); }
  var NT_PRIOR_G = 4;   // prior season (playcaller-aware) worth 4 games of 2026 defense
  function ntDefRate(S, team, key, sub) {
    // blended defense rate + blended league rate: (g x 2026 + 4 x prior) / (g + 4); {v, lg, g, cur, pri}
    var D = S.def[team], P = scPrior(S, team), g = D && D.g ? D.g : 0;
    var cur = D ? scGet(D, key, sub) : null, pri = P ? scGet(P, key, sub) : null;
    var lc = scLgOf(S, key, sub, false), lp = scLgOf(S, key, sub, true);
    if (cur == null && pri == null) return null;
    if (cur == null) return { v: pri, lg: lp != null ? lp : lc, g: 0, cur: null, pri: pri };
    if (pri == null) return g >= 3 ? { v: cur, lg: lc, g: g, cur: cur, pri: null } : null;
    var wv = function (x, y) { return (x == null || y == null) ? (x != null ? x : y) : (g * x + NT_PRIOR_G * y) / (g + NT_PRIOR_G); };
    return { v: wv(cur, pri), lg: wv(lc, lp), g: g, cur: cur, pri: pri };
  }
  function ntRateLab(S, team, r, name) {
    return team + ' ' + name + ' ' + scPct(r.v) + ' (' + (r.cur != null ? r.g + ' gm ' + scPct(r.cur) : 'no 2026') + (r.pri != null ? ', prior ' + scPct(r.pri) : '') + '; lg ' + scPct(r.lg) + ')';
  }
  function ntMatchup(p, wk, sc, slot, wp) {
    var w = wp && wp.why; if (!w || p.isDST || ['QB', 'RB', 'WR', 'TE'].indexOf(p.pos) < 0) return null;
    var it = [];
    var add = function (pct, lab, priced) { if (Math.abs(pct) >= 1) it.push({ pct: pct, lab: lab, priced: priced }); };
    // ---- priced (already inside PROJ) ----
    var fp = ntFpa(slot.opp);
    var fpPct = fp && fp.f[p.pos] != null && fp.lg[p.pos] ? 100 * (fp.f[p.pos] / fp.lg[p.pos] - 1) : null;
    add(100 * (w.opp - 1), fpPct != null && Math.abs(fpPct) >= 5 ? slot.opp + ' allows ' + ntSigned(fpPct, 0) + '% to ' + p.pos + 's (' + (fp.f._g || '?') + ' gm, priced at 25%)' : slot.opp + ' defense grade vs ' + p.pos + 's', true);
    add(100 * (w.pressure - 1), 'soft pass rush', true); add(100 * (w.cbShadow - 1), 'CB shadow', true); add(100 * (w.cb1Out - 1), slot.opp + ' CB1 out', true);
    add(100 * (w.olOut - 1), p.tm + ' OL starters out', true); add(100 * (w.weather - 1), 'wind', true);
    // ---- intel (advanced reads, not validated as projection inputs) ----
    var S = scS(), D = S ? S.def[slot.opp] : null, prof = S ? scProfile(S, p) : null, lg = S ? S.lg : null;
    if (S && D && prof) {
      var rMan = ntDefRate(S, slot.opp, 'man'), rPrs = ntDefRate(S, slot.opp, 'prs'), rBl = ntDefRate(S, slot.opp, 'blitz');
      var r = prof.rec, isRb = p.pos === 'RB';
      if (p.pos !== 'QB' && r && r.routes >= (isRb ? 60 : 25) && r.raw.mR >= (isRb ? 25 : 15) && r.raw.zR >= (isRb ? 25 : 15) && r.mYprr != null && r.zYprr && rMan && rMan.lg != null) {
        var dev = rMan.v - rMan.lg, gap = Math.max(-1, Math.min(1, r.mYprr / r.zYprr - 1));
        if (Math.abs(dev) >= 0.04 && Math.abs(gap) >= 0.2) add(ntClamp(dev / 0.10 * gap * 10 * (isRb ? 0.35 : 1), 10), ntRateLab(S, slot.opp, rMan, 'man') + ' vs his YPRR ' + scNum(r.mYprr, 2) + ' man / ' + scNum(r.zYprr, 2) + ' zone', false);
      }
      var rSlot = ntDefRate(S, slot.opp, 'slotYd');
      if (p.pos !== 'QB' && r && r.slot != null && r.slot >= 0.55 && rSlot && rSlot.lg != null && rSlot.v >= rSlot.lg + 0.08) add(4, ntRateLab(S, slot.opp, rSlot, 'slot share of rec yds allowed'), false);
      var q = prof.qb;
      if (p.pos === 'QB' && q && q.db >= 20) {
        if (rPrs && rPrs.lg != null && q.pGr != null && q.nGr != null) {
          var pdev = rPrs.v - rPrs.lg, sens = Math.max(-1, Math.min(2, (q.nGr - q.pGr - 20) / 15));
          if (pdev >= 0.03) add(-ntClamp(pdev / 0.06 * Math.max(0.3, sens) * 5, 10), ntRateLab(S, slot.opp, rPrs, 'pressure') + ', his grade ' + scNum(q.pGr, 0) + ' pressured vs ' + scNum(q.nGr, 0) + ' clean', false);
          else if (pdev <= -0.04) add(ntClamp(-pdev / 0.06 * 3, 6), ntRateLab(S, slot.opp, rPrs, 'pressure') + ' - clean pockets', false);
        }
        if (rBl && rBl.lg != null && q.bYpa != null && q.nbYpa != null && q.raw.bAtt >= 10 && rBl.v >= rBl.lg + 0.05) add(ntClamp((rBl.v - rBl.lg) / 0.08 * (q.bYpa - q.nbYpa) / 1.5 * 5, 8), ntRateLab(S, slot.opp, rBl, 'blitz') + ' vs his ' + scNum(q.bYpa, 1) + ' YPA blitzed / ' + scNum(q.nbYpa, 1) + ' not', false);
      }
      var b = prof.rb, LR = lg.run || {};
      if (p.pos === 'RB' && b && b.att >= 8 && D.run) {
        var dr = D.run;
        var PR = scPrior(S, slot.opp), prr = PR && PR.run ? PR.run : null, LRp = (S.lgPrior && S.lgPrior.run) || LR;
        var runB = function (k) {   // carries-weighted: prior season worth 150 carries
          var c = dr[k], pv = prr ? prr[k] : null, n = dr.att || 0;
          if (c == null && pv == null) return null;
          var v = c == null ? pv : pv == null ? (n >= 40 ? c : null) : (n * c + 150 * pv) / (n + 150);
          var L = LR[k] == null ? LRp[k] : LRp[k] == null ? LR[k] : (n * LR[k] + 150 * LRp[k]) / (n + 150);
          return v == null || L == null ? null : { v: v, lg: L, n: n, cur: c, pri: pv };
        };
        var ry = runB('ypc'), rc = runB('yco');
        if (ry) add(ntClamp((ry.v - ry.lg) / 0.7 * 6, 10), slot.opp + ' run D ' + scNum(ry.v, 1) + ' ypc blended (' + Math.round(ry.n) + ' car ' + scNum(ry.cur, 1) + (ry.pri != null ? ', prior ' + scNum(ry.pri, 1) : '') + '; lg ' + scNum(ry.lg, 1) + ')', false);
        if (rc && Math.abs(rc.v - rc.lg) >= 0.2) add(ntClamp((rc.v - rc.lg) / 0.5 * 3, 5), slot.opp + ' allows ' + scNum(rc.v, 2) + ' after contact/att blended (lg ' + scNum(rc.lg, 2) + ')', false);
        var rMt = ntDefRate(S, slot.opp, 'mtRate'), rBox = ntDefRate(S, slot.opp, 'sBox');
        if (rMt && rMt.lg != null && rMt.v >= rMt.lg + 0.03 && b.mtf != null && LR.mtf != null && b.mtf >= LR.mtf + 0.05) add(4, ntRateLab(S, slot.opp, rMt, 'missed-tackle rate') + ' vs an elusive back', false);
        if (rBox && rBox.lg != null && rBox.v >= rBox.lg + 0.08) add(-4, ntRateLab(S, slot.opp, rBox, 'safety in box'), false);
      }
    }
    var Z = window.SIM_ZONES_2026;
    if (Z && (Z.lg || Z.lgPrior) && p.pos !== 'QB') {
      var zlg = znLg(Z), pl = znPlayer(Z, p.norm, zlg), zd = znDef(Z, slot.opp, zlg);
      if (pl && zd && (pl.N + pl.Np) >= 10) {
        ZN_DEPTH.forEach(function (zz) {
          var z = zz[0], sh = pl.depth[z], L = zlg.depth[z].share, dz = zd.depth[z];
          if (sh >= L + 0.05 && dz && dz.rawEff != null && dz.n >= 25 && Math.abs(dz.rawEff - 1) >= 0.15) add(ntClamp((dz.rawEff - 1) * 12, 8), slot.opp + ' ' + (dz.rawEff > 1 ? 'leaky' : 'stingy') + ' ' + zz[1].toLowerCase() + ' (' + dz.rawEff.toFixed(2) + 'x pts/tgt, his ' + Math.round(100 * sh) + '% of targets)', false);
        });
      }
    }
    var DA = window.SIM_DEF_AVAIL_2026;
    if (DA && DA.teams && DA.teams[slot.opp]) {
      var qCov = 0, qFront = 0, names = [];
      DA.teams[slot.opp].forEach(function (d) {
        var gs = String(d.gs || '').toLowerCase(), sl = String(d.sl || ''), nflNow = DA.prWeek != null && +DA.prWeek === +wk;
        var out = /\b(IR|PUP|NFI|NA|Sus)/i.test(sl) || /inactive/i.test(sl) || (nflNow && (gs === 'out' || gs === 'doubtful')) || /^(Out|Doubtful)/i.test(sl);
        if (!out) return;
        var ql = Math.max(0, (d.g || 55) - 55) / 10 * (d.sh || 0.8);
        if (ql < 0.3) return;
        var ps = String(d.pos || '').toUpperCase();
        if (NT_COV[ps]) qCov += ql; else if (NT_FRONT[ps]) qFront += ql; else return;
        names.push(ps + ' ' + d.n + ' (' + (d.g != null ? d.g.toFixed(0) : '?') + ')');
      });
      var ql2 = (p.pos === 'WR' || p.pos === 'TE') ? qCov : p.pos === 'RB' ? qFront : 0.5 * (qCov + qFront);
      if (ql2 >= 0.3) add(Math.min(10, ql2 * 3), slot.opp + ' missing ' + names.join(', '), false);
    }
    if (!it.length) return { pct: 0, priced: 0, intel: 0, items: [] };
    var pr = 0, inl = 0; it.forEach(function (x) { if (x.priced) pr += x.pct; else inl += x.pct; });
    it.sort(function (x, y) { return Math.abs(y.pct) - Math.abs(x.pct); });
    return { pct: pr + inl, priced: pr, intel: inl, items: it };
  }
  function ntMatchupText(mu) {
    return mu.items.slice(0, 4).map(function (x) { return x.lab + ' ' + ntSigned(x.pct, 0) + '%' + (x.priced ? '' : ' [intel]'); }).join('; ');
  }
  function ntMatchupRows(wk, sc) {
    var rows = [];
    state.players.list.forEach(function (p) {
      if (p.isDST || ['QB', 'RB', 'WR', 'TE'].indexOf(p.pos) < 0) return;
      var slot = state.schedule.byTeam[p.tm] && state.schedule.byTeam[p.tm][wk]; if (!slot) return;
      var wp = E.weeklyProjection(p, wk, sc, state.schedule); if (!wp) return;
      if (E.injAdj(p, wk) === 0) return;
      var eff = E.effMean(wp); if (eff < (p.pos === 'QB' ? 12 : 6)) return;
      var mu = ntMatchup(p, wk, sc, slot, wp); if (!mu || !mu.items.length) return;
      rows.push({ p: p, slot: slot, eff: eff, mu: mu });
    });
    return rows;
  }
  // main-site export (export_notes.js --repo -> data/matchup_edges_2026.js, Start/Sit page MATCHUP EDGES)
  window.SimLabMatchupEdges = function (wk, scKey) {
    var sc = E.PRESETS[scKey || 'half'] || E.PRESETS.half;
    wk = +wk || +(document.getElementById('nt-week') || {}).value || state.injuryWeek || 1;
    return { week: wk, scoring: scKey || 'half', generated: new Date().toISOString(),
      rows: ntMatchupRows(wk, sc).map(function (r) {
        return { n: r.p.name, pos: r.p.pos, tm: r.p.tm, opp: r.slot.opp, home: !!r.slot.home, proj: +r.eff.toFixed(1),
          pct: +r.mu.pct.toFixed(1), priced: +r.mu.priced.toFixed(1), intel: +r.mu.intel.toFixed(1),
          items: r.mu.items.slice(0, 5).map(function (x) { return { pct: +x.pct.toFixed(1), lab: x.lab, priced: !!x.priced }; }) };
      }).sort(function (x, y) { return y.pct - x.pct; }) };
  };
  function ntMatchupBoard(wk, sc) {
    var rows = ntMatchupRows(wk, sc);
    var pos = rows.filter(function (r) { return r.mu.pct > 0; }).sort(function (x, y) { return y.mu.pct - x.mu.pct; }).slice(0, 15);
    var neg = rows.filter(function (r) { return r.mu.pct < 0; }).sort(function (x, y) { return x.mu.pct - y.mu.pct; }).slice(0, 15);
    var table = function (list, title, col) {
      return '<h3 style="margin:10px 0 4px;color:' + col + '">' + title + '</h3><div style="overflow-x:auto"><table style="width:auto"><thead><tr><th class="l">Player</th><th>Pos</th><th>Matchup</th><th>PROJ</th><th title="% of the projection: priced = already inside PROJ">Edge</th><th>Priced</th><th>Intel</th><th class="l">Why</th></tr></thead><tbody>' +
        list.map(function (r) { return '<tr><td class="l"><b>' + esc(r.p.name) + '</b></td><td>' + r.p.pos + '</td><td>' + r.p.tm + (r.slot.home ? ' vs ' : ' @ ') + r.slot.opp + '</td><td>' + ntF(r.eff, 1) + '</td><td style="color:' + col + '"><b>' + ntSigned(r.mu.pct, 0) + '%</b></td><td class="dim">' + ntSigned(r.mu.priced, 0) + '%</td><td class="dim">' + ntSigned(r.mu.intel, 0) + '%</td><td class="l" style="font-size:11px;white-space:normal;min-width:280px">' + esc(ntMatchupText(r.mu)) + '</td></tr>'; }).join('') +
        '</tbody></table></div>';
    };
    var html = '<div style="border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-bottom:18px"><h3 style="margin:0 0 4px">Matchup edges \u2014 week ' + wk + '</h3>' +
      '<p class="dim" style="font-size:11px;margin:0">Matchup score in % of each player\'s projection (QB 12+ / others 6+ PROJ). Priced = already inside PROJ (opponent FPA or Clay grade at the backtested 25%, soft pass rush, CB, OL, wind). Intel = advanced reads the backtests did not validate as projection inputs: coverage fit (opponent man rate x his man/zone YPRR), pressure and blitz vs the QB\'s splits, run defense vs RBs, target zones, and defensive injuries by unit. Use for video angles, not as projection changes; early-season defense samples are small.</p>' +
      table(pos, 'Best matchups', 'var(--acc)') + table(neg, 'Toughest matchups', '#f85149') + '</div>';
    var T = ['MATCHUP EDGES (week ' + wk + ', % of projection; [intel] = advanced read not in PROJ):', '  BEST:'];
    pos.forEach(function (r) { T.push('    ' + r.p.name + ' (' + r.p.tm + ' ' + r.p.pos + (r.slot.home ? ' vs ' : ' @ ') + r.slot.opp + ') PROJ ' + ntF(r.eff, 1) + ' edge ' + ntSigned(r.mu.pct, 0) + '% (priced ' + ntSigned(r.mu.priced, 0) + ', intel ' + ntSigned(r.mu.intel, 0) + '): ' + ntMatchupText(r.mu)); });
    T.push('  TOUGHEST:');
    neg.forEach(function (r) { T.push('    ' + r.p.name + ' (' + r.p.tm + ' ' + r.p.pos + (r.slot.home ? ' vs ' : ' @ ') + r.slot.opp + ') PROJ ' + ntF(r.eff, 1) + ' edge ' + ntSigned(r.mu.pct, 0) + '% (priced ' + ntSigned(r.mu.priced, 0) + ', intel ' + ntSigned(r.mu.intel, 0) + '): ' + ntMatchupText(r.mu)); });
    return { html: html, text: T.join('\n') };
  }
  function ntGameSheet(g, wk, sc) {
    var Z = window.SIM_ZONES_2026, lg = (Z && (Z.lg || Z.lgPrior)) ? znLg(Z) : null;
    var slotA = state.schedule.byTeam[g.away] && state.schedule.byTeam[g.away][wk];
    var slotH = state.schedule.byTeam[g.home] && state.schedule.byTeam[g.home][wk];
    if (!slotA || !slotH) return { html: '<p class="dim">No line for ' + esc(g.away + ' @ ' + g.home) + '.</p>', text: '' };
    var fav = g.spread === 0 ? 'pick' : (g.spread < 0 ? g.home + ' by ' + ntF(-g.spread, 1) : g.away + ' by ' + ntF(g.spread, 1));
    var head = g.away + ' @ ' + g.home + ' — total ' + ntF(g.total, 1) + ', ' + fav + ' · implied ' + g.away + ' ' + ntF(slotA.implied, 1) + ' / ' + g.home + ' ' + ntF(slotH.implied, 1);
    var T = [head, ntWeather(g.home, wk)];
    var html = '<div style="border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-bottom:18px">' +
      '<h3 style="margin:0 0 6px">' + esc(head) + '</h3><div class="dim" style="font-size:12px">' + esc(T[1]) + '</div>';
    [[g.away, g.home, slotA], [g.home, g.away, slotH]].forEach(function (pair) {
      var team = pair[0], opp = pair[1];
      var lines = ntTeamBlock(team, opp, wk, pair[2]);
      html += '<div style="margin-top:10px"><b>' + team + ' offense vs ' + opp + ' defense</b><ul style="margin:4px 0 0 18px;padding:0;font-size:12px">' +
        lines.map(function (s) { return '<li>' + esc(s) + '</li>'; }).join('') + '</ul></div>';
      T.push(''); T.push(team + ' offense vs ' + opp + ' defense'); lines.forEach(function (s) { T.push('  - ' + s); });
    });
    // players of both teams
    var rows = [];
    state.players.list.forEach(function (p) {
      if (p.tm !== g.away && p.tm !== g.home) return;
      var wp = E.weeklyProjection(p, wk, sc, state.schedule); if (!wp) return;
      var slot = p.tm === g.away ? slotA : slotH;
      var eff = E.effMean(wp);
      if (eff < 3 && !p.isDST) return;
      var chips = ntPlayerChips(p, wk, sc, slot, wp);
      var xf = ntXfp(p, sc);
      var read = '';
      if (lg && !p.isDST && ['WR', 'TE', 'RB'].indexOf(p.pos) >= 0) {
        var pl = znPlayer(Z, p.norm, lg); if (pl && (pl.N + pl.Np) >= 10) read = znReads(pl, znDef(Z, slot.opp, lg), lg);
      }
      if (scS() && !p.isDST) { var sr = scRead(scS(), p, scS().def[slot.opp]); if (sr) read = read ? read + ' \u00b7 ' + sr : sr; }
      var why = ntWhy(p, wk, sc, slot, wp), swhy = ntShadowWhy(p, wk), mu = ntMatchup(p, wk, sc, slot, wp);
      rows.push({ p: p, eff: eff, wp: wp, chips: chips, read: read, xf: xf, why: why, swhy: swhy, mu: mu });
    });
    rows.sort(function (x, y) { return y.eff - x.eff; });
    html += '<table style="margin-top:10px"><thead><tr><th class="l">Player</th><th>Tm</th><th>Pos</th><th>PROJ</th><th>Model</th><th>Market</th><th title="Expected fantasy points per game, 2026 to date (standard usage-based xFP)">xFP/g</th><th title="Actual PPG minus xFP/g: + = scoring over his usage, - = under (due up)">FPOE/g</th><th class="l">Why / notes</th><th class="l">Zone / scheme read</th></tr></thead><tbody>';
    T.push(''); T.push('PLAYERS (PROJ ' + $('nt-scoring').value + '):');
    rows.forEach(function (o) {
      html += '<tr><td class="l"><b>' + esc(o.p.name) + '</b></td><td>' + o.p.tm + '</td><td>' + o.p.pos + '</td><td><b>' + ntF(o.eff, 1) + '</b></td><td class="dim">' +
        ntF(o.wp.jsMean, 1) + '</td><td class="dim">' + (o.wp.propMean != null ? ntF(o.wp.propMean, 1) : '—') + '</td>' +
        '<td class="dim">' + (o.xf ? ntF(o.xf.xfpg, 1) : '—') + '</td>' +
        '<td' + (o.xf && o.xf.fpoeg != null ? ' style="color:' + (o.xf.fpoeg <= -1.5 ? 'var(--acc)' : o.xf.fpoeg >= 1.5 ? '#f85149' : 'var(--dim)') + '"' : ' class="dim"') + '>' + (o.xf && o.xf.fpoeg != null ? ntSigned(o.xf.fpoeg, 1) : '—') + '</td>' +
        '<td class="l" style="font-size:11px;white-space:normal;min-width:220px">' + o.chips.map(function (c) {
          var col = /- shadow$/.test(c) ? (/faller/.test(c) ? '#f85149' : '#58a7ff') : /OUT|docked|×0\.|luck -|lower|shadow/.test(c) ? '#f85149' : (/boost|×1\.|luck \+|higher|soft/.test(c) ? 'var(--acc)' : 'var(--dim)');
          return '<span style="border:1px solid ' + col + ';color:' + col + ';border-radius:9px;padding:0 6px;margin:1px 3px 1px 0;display:inline-block">' + esc(c) + '</span>';
        }).join('') + '</td><td class="l" style="font-size:11px;white-space:normal;min-width:220px">' + esc(o.read) + '</td></tr>';
      if (o.why || o.swhy || (o.mu && o.mu.items.length)) html += '<tr><td colspan="10" class="l dim" style="font-size:11px;white-space:normal;padding:0 8px 6px 18px;border-top:none">' +
        (o.why ? '<b>Why:</b> ' + esc(o.why.text) : '') + (o.mu && o.mu.items.length ? '<br><b>Matchup ' + ntSigned(o.mu.pct, 0) + '%</b> (priced ' + ntSigned(o.mu.priced, 0) + ', intel ' + ntSigned(o.mu.intel, 0) + '): ' + esc(ntMatchupText(o.mu)) : '') +
        (o.swhy ? '<br><span style="color:#58a7ff">' + esc(o.swhy) + '</span>' : '') + '</td></tr>';
      var line = '  ' + o.p.name + ' (' + o.p.tm + ' ' + o.p.pos + ') ' + ntF(o.eff, 1);
      if (o.xf && o.xf.fpoeg != null) line += ' · xFP ' + ntF(o.xf.xfpg, 1) + '/g (' + ntSigned(o.xf.fpoeg, 1) + ' over expected)';
      if (o.chips.length) line += ' [' + o.chips.join(', ') + ']';
      if (o.read) line += ' — ' + o.read;
      T.push(line);
      if (o.why) T.push('      why: ' + o.why.text);
      if (o.mu && o.mu.items.length) T.push('      matchup ' + ntSigned(o.mu.pct, 0) + '% (priced ' + ntSigned(o.mu.priced, 0) + ', intel ' + ntSigned(o.mu.intel, 0) + '): ' + ntMatchupText(o.mu));
      if (o.swhy) T.push('      ' + o.swhy);
    });
    html += '</tbody></table>';
    if (lg) {
      html += '<div style="display:flex;gap:28px;flex-wrap:wrap;align-items:flex-start;margin-top:12px">' +
        '<div>' + znDefCard(Z, g.home, lg, g.home + ' defense zones (vs ' + g.away + ')') + '</div>' +
        '<div>' + znDefCard(Z, g.away, lg, g.away + ' defense zones (vs ' + g.home + ')') + '</div></div>';
    }
    if (scS()) {
      html += '<div style="display:flex;gap:28px;flex-wrap:wrap;align-items:flex-start;margin-top:12px">' +
        '<div>' + scDefCard(scS(), g.home, g.home + ' defense scheme (vs ' + g.away + ')') + '</div>' +
        '<div>' + scDefCard(scS(), g.away, g.away + ' defense scheme (vs ' + g.home + ')') + '</div></div>';
    }
    html += '</div>';
    return { html: html, text: T.join('\n') };
  }
  function renderNotesTab() {
    var wkSel = $('nt-week'), gSel = $('nt-game');
    if (!wkSel.options.length) {
      for (var w = 1; w <= 18; w++) wkSel.add(new Option('Week ' + w, w));
      var Z = window.SIM_ZONES_2026;
      wkSel.value = state.injuryWeek || ((Z && Z.weeks && Z.weeks.length) ? Math.min(18, Z.weeks[Z.weeks.length - 1] + 1) : 1);
      wkSel.addEventListener('change', function () { state.ntGame = ''; renderNotesTab(); });
      gSel.addEventListener('change', function () { state.ntGame = gSel.value; renderNotesTab(); });
      $('nt-scoring').addEventListener('change', renderNotesTab);
      $('nt-copy').addEventListener('click', function () {
        var txt = $('nt-text').value;
        var done = function () { $('nt-copied').textContent = 'copied ' + txt.length + ' chars'; setTimeout(function () { $('nt-copied').textContent = ''; }, 2500); };
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(done, function () { $('nt-text').select(); document.execCommand('copy'); done(); });
        else { $('nt-text').select(); document.execCommand('copy'); done(); }
      });
    }
    var wk = +wkSel.value, sc = currentScoring('nt-scoring');
    var games = state.schedule.byWeek[wk] || [];
    gSel.innerHTML = '<option value="__all">All games (long)</option>' + games.map(function (g) { return '<option value="' + g.key + '">' + g.away + ' @ ' + g.home + '</option>'; }).join('');
    if (!state.ntGame && games.length) state.ntGame = games[0].key;
    gSel.value = state.ntGame || '__all';
    var luckText = renderLuckBoard(sc);
    var pick = gSel.value === '__all' ? games : games.filter(function (g) { return g.key === gSel.value; });
    var html = '', T = ['SIM LAB NOTES — Week ' + wk + ' (' + $('nt-scoring').value + ') — ' + new Date().toISOString().slice(0, 16).replace('T', ' '), ''];
    T.push('TD LUCK (top 5 each way):'); luckText.forEach(function (s) { T.push('  ' + s); }); T.push('');
    var board = ntMatchupBoard(wk, sc); html += board.html; T.push(board.text); T.push('');
    pick.forEach(function (g) { var r = ntGameSheet(g, wk, sc); html += r.html; T.push(r.text); T.push(''); });
    $('nt-body').innerHTML = html || '<p class="dim">No games with lines for this week.</p>';
    $('nt-text').value = T.join('\n');
    $('nt-note').textContent = games.length + ' games with lines in week ' + wk + (state.injuryWeek ? ' · injury layer armed for week ' + state.injuryWeek : '') + ' · intel only — nothing here changes projections.';
  }

  // ---------------- TRACKING & ACCURACY ----------------
  // Lock PER GAME: freeze projections + prop lines for chosen games as they
  // stand right now (TNF Thursday, Sunday slate Sunday morning, MNF Monday) —
  // late-breaking injury news never forces an early lock of the whole week.
  // A locked game is FROZEN: it can't be re-locked. Score grades whatever's
  // in the snapshot after the games.
  function weekGames(wk) { return state.schedule.byWeek[wk] || []; }
  function unlockedGameKeys() {
    var wk = +$('tk-week').value;
    var snap = state.snapshots[wk];
    var locked = (snap && snap.lockedGames) || {};
    return weekGames(wk).map(function (g) { return g.key; }).filter(function (k) { return !locked[k]; });
  }

  function renderGameList() {
    var wk = +$('tk-week').value;
    var snap = state.snapshots[wk];
    var locked = (snap && snap.lockedGames) || {};
    var html = weekGames(wk).map(function (g) {
      var lk = locked[g.key];
      return '<label style="display:inline-block;margin:2px 10px 2px 0;font-size:12px;' + (lk ? 'color:var(--acc)' : '') + '">' +
        (lk ? '&#10003; ' : '<input type="checkbox" value="' + g.key + '" style="vertical-align:-2px"> ') +
        g.away + ' @ ' + g.home +
        (lk ? ' <span class="dim">(locked ' + lk.slice(5, 10) + ')</span>' : '') + '</label>';
    }).join('');
    $('tk-games').innerHTML = html || '<span class="dim">No Vegas games for this week.</span>';
  }

  function lockGames(keys) {
    var wk = +$('tk-week').value;
    var snap = state.snapshots[wk];
    if (!snap) {
      snap = { week: wk, season: E.SEASON, preset: $('tk-scoring').value, sims: 2000, lockedGames: {}, players: [] };
    }
    snap.lockedGames = snap.lockedGames || {};
    var todo = keys.filter(function (k) { return !snap.lockedGames[k]; });
    if (!todo.length) { $('tk-note').textContent = 'Nothing to lock — those games are already locked.'; return; }
    if (snap.players.length && snap.preset !== $('tk-scoring').value) {
      $('tk-note').textContent = 'This week was started in ' + snap.preset.toUpperCase() + ' — keeping that preset for consistency.';
    }
    var sc = E.PRESETS[snap.preset] || E.PRESETS.half;
    var results = E.simWeek({ week: wk, sims: snap.sims, scoring: sc, schedule: state.schedule, players: state.players });
    var props = (window.BETTING_2026 && window.BETTING_2026.weeklyProps && window.BETTING_2026.weeklyProps[String(wk)]) || {};
    var propByNorm = {};
    Object.keys(props).forEach(function (nm) { propByNorm[E.norm(nm)] = props[nm]; });

    var now = new Date().toISOString(), added = 0;
    results.forEach(function (r) {
      if (todo.indexOf(r.slot.gameKey) < 0) return;
      if (!(r.mean >= 2 || propByNorm[r.player.norm])) return;
      snap.players.push({
        name: r.player.name, sid: r.player.sid, pos: r.player.pos, tm: r.player.tm,
        opp: r.slot.opp, implied: +r.slot.implied.toFixed(1), game: r.slot.gameKey, lockedAt: now,
        mean: +r.mean.toFixed(2), p10: +r.p10.toFixed(2), p50: +r.p50.toFixed(2), p90: +r.p90.toFixed(2),
        jsMean: r.jsProj != null ? +r.jsProj.toFixed(2) : null,
        // clean Clay-layer mean: sp.mean is the SHIPPED sim mean (centers on
        // JS in-season / prop anchor when on), so head-to-heads need the raw
        // model stored separately or they degenerate to self-comparison
        clayMean: r.proj != null ? +r.proj.toFixed(2) : null,
        propMean: r.propProj != null ? +r.propProj.toFixed(2) : null,
        propSrc: r.propSrc || null,
        luck: r.luck != null ? +r.luck.toFixed(3) : 0,   // TD-luck points inside jsMean at lock (luck_scorecard.py grades the layer live) // 'line' = direct anchor, 'rate' = market rate track
        useLam: r.useLam != null ? +r.useLam.toFixed(2) : undefined, usePg: r.usePg != null ? +r.usePg.toFixed(2) : undefined, jsNoUse: r.jsNoUse != null ? +r.jsNoUse.toFixed(2) : undefined,   // live usage evidence inside jsMean at lock (usage_scorecard.py)
        peck: r.peck != null && r.peck !== 1 ? +r.peck.toFixed(3) : undefined, peckRank: r.peckRank != null ? r.peckRank : undefined,   // pecking-order dock inside jsMean at lock + rank on his team (peck_scorecard.py)
        vol: r.vol != null && r.vol !== 1 ? +r.vol.toFixed(3) : undefined, health: r.health ? +r.health.toFixed(2) : undefined, useHurt: r.useHurt || undefined,
        bb: r.bb || undefined, jsPre: r.jsPre != null ? +r.jsPre.toFixed(2) : undefined,   // weeks-ahead / all-weeks base blend: jsMean = bb x shadow + (1 - bb) x jsPre (the Clay-blend model before the blend)   // 2026-10-07 layers for per-layer grading
        ret: r.ret != null && r.ret !== 1 ? +r.ret.toFixed(3) : undefined,   // return ramp inside the number at lock (return_scorecard.py)
        qbf: r.qbf != null && r.qbf !== 1 ? +r.qbf.toFixed(3) : undefined,   // QB starter floor inside the number at lock (return_scorecard.py)
        ncMean: r.ncProj != null ? +r.ncProj.toFixed(2) : null, ncSrc: r.ncSrc || null,   // SHADOW: Clay-free base (own 3-yr PPG prior)
        rmMean: r.rmProj != null ? +r.rmProj.toFixed(2) : null, rmFinal: r.rmFinal != null ? +r.rmFinal.toFixed(2) : null, espn: r.espnPts != null ? +r.espnPts.toFixed(2) : null,   // RANK MIX: 50% shadow + 50% ESPN; with the book anchor; ESPN alone
        lcCorr: r.lcCorr != null ? +r.lcCorr.toFixed(2) : null, lcMean: r.lcCorr != null ? +Math.max(0, r.mean + r.lcCorr).toFixed(2) : null,   // SHADOW: learned correction on the hand stack (build_learned_shadow.py)
        rep: (function () { var nf = E.newsFlags(r.player); return nf ? nf.riser - nf.faller : 0; })(),   // SHADOW: beat-report riser minus faller count, last 10 days
        asc: E.ascendingFlag(r.player, wk) ? 1 : 0,   // SHADOW: young + snaps/routes trending up

        comps: r.comps, compsU: r.compsU || null, lines: propByNorm[r.player.norm] || null
      });
      added++;
    });
    todo.forEach(function (k) { snap.lockedGames[k] = now; });
    snap.lockedAt = snap.lockedAt || now;
    state.snapshots[wk] = snap;
    saveLS('simlab_snapshots', state.snapshots);
    download('simlab_snapshot_w' + wk + '_' + now.slice(0, 10) + '.json', snap);
    var nLocked = Object.keys(snap.lockedGames).length;
    $('tk-note').textContent = 'Locked ' + todo.length + ' game(s), ' + added + ' players — ' +
      nLocked + '/' + weekGames(wk).length + ' games locked for week ' + wk + '. Snapshot saved + downloaded.';
    renderGameList();
    renderTracking();
  }

  async function scoreWeek() {
    var wk = +$('tk-week').value;
    var snap = state.snapshots[wk];
    if (!snap) { $('tk-note').textContent = 'No locked snapshot for week ' + wk + ' — lock it before the games.'; return; }
    $('tk-note').textContent = 'Fetching week ' + wk + ' actuals from Sleeper…';
    try {
      var stats = await (await fetch(API + '/stats/nfl/regular/' + snap.season + '/' + wk)).json();
      var sc = E.PRESETS[snap.preset] || E.PRESETS.half;
      var STAT_MAP = { py: 'pass_yd', ry: 'rush_yd', rcy: 'rec_yd', ptd: 'pass_td', fgm: 'fgm' };
      // Two graders: mean (expected value) and median (p50 — the apples-to-apples
      // comparison, since a book line is the market's median).
      var rows = [], propDetail = {};
      var vb = { mean: { w: 0, l: 0, t: 0 }, med: { w: 0, l: 0, t: 0 } };
      var acc = { mean: { e: 0, e2: 0, b: 0 }, med: { e: 0, e2: 0, b: 0 } };
      var js = { e: 0, e2: 0, b: 0, n: 0, headWins: 0, headLosses: 0 }; // JS Weekly vs Clay head-to-head
      var pm = { e: 0, e2: 0, b: 0, n: 0, headWins: 0, headLosses: 0, jsWins: 0, jsLosses: 0 }; // prop anchor vs Clay + vs JS
      var nPts = 0, inBand = 0;

      snap.players.forEach(function (sp) {
        if (!sp.sid) return;
        var st = stats[sp.sid];
        if (!st || (st.gp == null && st.pts_std == null)) return; // didn't play / no data
        var actual = (st.pts_std || 0) + sc.rec * (st.rec || 0) + (sc.pass_td - 4) * (st.pass_td || 0);
        if (sp.pos === 'TE' && sc.bonus_rec_te) actual += sc.bonus_rec_te * (st.rec || 0);
        [['mean', sp.mean], ['med', sp.p50]].forEach(function (pair) {
          var err = pair[1] - actual;
          acc[pair[0]].e += Math.abs(err); acc[pair[0]].e2 += err * err; acc[pair[0]].b += err;
        });
        // clean Clay-layer reference for head-to-heads (falls back to the
        // shipped sim mean on pre-2026-08-31 snapshots that lack clayMean)
        var clayRef = sp.clayMean != null ? sp.clayMean : sp.mean;
        if (sp.jsMean != null) {
          var jsErr = sp.jsMean - actual;
          js.e += Math.abs(jsErr); js.e2 += jsErr * jsErr; js.b += jsErr; js.n++;
          var clayErr = Math.abs(clayRef - actual);
          if (Math.abs(jsErr) < clayErr) js.headWins++; else if (Math.abs(jsErr) > clayErr) js.headLosses++;
        }
        if (sp.propMean != null) {
          var pErr = sp.propMean - actual;
          pm.e += Math.abs(pErr); pm.e2 += pErr * pErr; pm.b += pErr; pm.n++;
          var cErr = Math.abs(clayRef - actual);
          if (Math.abs(pErr) < cErr) pm.headWins++; else if (Math.abs(pErr) > cErr) pm.headLosses++;
          if (sp.jsMean != null) {
            var jErr2 = Math.abs(sp.jsMean - actual);
            if (Math.abs(pErr) < jErr2) pm.jsWins++; else if (Math.abs(pErr) > jErr2) pm.jsLosses++;
          }
        }
        nPts++;
        if (actual >= sp.p10 && actual <= sp.p90) inBand++;

        // vs the books, stat by stat — component medians approximated by
        // scaling component means with the player's p50/mean ratio
        var medRatio = sp.mean > 0.5 ? sp.p50 / sp.mean : 1;
        var propRows = [];
        if (sp.lines) {
          Object.keys(STAT_MAP).forEach(function (k) {
            var books = [];
            ['UD', 'PP', 'DK', 'FD', 'MGM'].forEach(function (b) {
              if (sp.lines[b] && typeof sp.lines[b][k] === 'number') books.push(sp.lines[b][k]);
            });
            if (!books.length || sp.comps[k] == null) return;
            books.sort(function (a, b) { return a - b; });
            var line = books[Math.floor(books.length / 2)];
            var act = st[STAT_MAP[k]] || 0;
            var bookErr = Math.abs(line - act);
            var ourMean = sp.comps[k], ourMed = sp.comps[k] * medRatio;
            propDetail[k] = propDetail[k] || { mean: { w: 0, l: 0, t: 0 }, med: { w: 0, l: 0, t: 0 } };
            [['mean', ourMean], ['med', ourMed]].forEach(function (pair) {
              var ourErr = Math.abs(pair[1] - act);
              var key = ourErr < bookErr ? 'w' : (ourErr > bookErr ? 'l' : 't');
              vb[pair[0]][key]++; propDetail[k][pair[0]][key]++;
            });
            propRows.push({ stat: k, ourMean: +ourMean.toFixed(1), ourMed: +ourMed.toFixed(1), line: line, actual: act });
          });
        }
        rows.push({ name: sp.name, pos: sp.pos, mean: sp.mean, med: sp.p50, p10: sp.p10, p90: sp.p90, actual: +actual.toFixed(2), props: propRows });
      });

      var report = {
        week: wk, scoredAt: new Date().toISOString(), players: nPts,
        mae: nPts ? acc.mean.e / nPts : null, rmse: nPts ? Math.sqrt(acc.mean.e2 / nPts) : null,
        bias: nPts ? acc.mean.b / nPts : null,
        maeMed: nPts ? acc.med.e / nPts : null, rmseMed: nPts ? Math.sqrt(acc.med.e2 / nPts) : null,
        biasMed: nPts ? acc.med.b / nPts : null,
        jsModel: js.n ? { players: js.n, mae: js.e / js.n, rmse: Math.sqrt(js.e2 / js.n), bias: js.b / js.n,
                          headWins: js.headWins, headLosses: js.headLosses } : null,
        propModel: pm.n ? { players: pm.n, mae: pm.e / pm.n, rmse: Math.sqrt(pm.e2 / pm.n), bias: pm.b / pm.n,
                            headWins: pm.headWins, headLosses: pm.headLosses,
                            jsWins: pm.jsWins, jsLosses: pm.jsLosses } : null,
        calibration80: nPts ? inBand / nPts : null,
        vsBooks: { wins: vb.mean.w, losses: vb.mean.l, ties: vb.mean.t,
                   med: { wins: vb.med.w, losses: vb.med.l, ties: vb.med.t }, byStat: propDetail },
        rows: rows.sort(function (a, b) { return Math.abs(b.mean - b.actual) - Math.abs(a.mean - a.actual); })
      };
      state.accuracy[wk] = report;
      saveLS('simlab_accuracy', state.accuracy);
      var nGames = (state.schedule.byWeek[wk] || []).length;
      var nLocked = snap.lockedGames ? Object.keys(snap.lockedGames).length : nGames;
      $('tk-note').textContent = 'Week ' + wk + ' scored: ' + nPts + ' players graded.' +
        (nLocked < nGames ? ' WARNING: only ' + nLocked + '/' + nGames + ' games were locked — unlocked games are not graded.' : '');
      renderTracking();
    } catch (e) {
      $('tk-note').textContent = 'Scoring failed: ' + e.message + ' (actuals only exist once the week has been played)';
    }
  }

  function renderTracking() {
    var wks = Object.keys(state.snapshots).map(Number).sort(function (a, b) { return a - b; });
    var html = '';
    if (!wks.length) {
      html = '<p class="dim">No snapshots yet. Before each week\'s games: pick the week, hit LOCK. After the games: hit SCORE. ' +
        'Everything stays local (localStorage + downloaded JSON) — nothing is published.</p>';
    } else {
      html = '<table><thead><tr><th>Wk</th><th>Locked</th><th>Players</th><th>MAE mean</th><th>MAE med</th><th>MAE JS</th>' +
        '<th>JS vs Clay</th><th>MAE PROP</th><th>PROP vs Clay/JS</th><th>Bias mean</th><th>Bias med</th><th>80% band hit</th>' +
        '<th>vs Books (mean)</th><th>vs Books (median)</th></tr></thead><tbody>';
      wks.forEach(function (wk) {
        var s = state.snapshots[wk], a = state.accuracy[wk];
        var vb = a ? a.vsBooks : null;
        var vbm = vb && vb.med ? vb.med : null;
        function cell(v) { return v && (v.wins + v.losses) ? v.wins + '-' + v.losses + '-' + v.ties + ' (<b>' + pctf(v.wins / (v.wins + v.losses)) + '</b>)' : '—'; }
        var lockLbl = s.lockedGames
          ? Object.keys(s.lockedGames).length + '/' + (state.schedule.byWeek[wk] || []).length + ' games'
          : s.lockedAt.slice(0, 10);
        var jm = a && a.jsModel;
        var pmR = a && a.propModel;
        function h2h(w, l) { return w + '-' + l + (w + l ? ' (' + pctf(w / (w + l)) + ')' : ''); }
        html += '<tr><td>' + wk + '</td><td class="dim">' + lockLbl + '</td><td>' + s.players.length +
          '</td><td>' + (a ? fmt(a.mae, 2) : '—') + '</td><td>' + (a && a.maeMed != null ? fmt(a.maeMed, 2) : '—') +
          '</td><td>' + (jm ? fmt(jm.mae, 2) : '—') +
          '</td><td>' + (jm ? h2h(jm.headWins, jm.headLosses) : '—') +
          '</td><td>' + (pmR ? fmt(pmR.mae, 2) + ' <span class="dim">(' + pmR.players + 'p)</span>' : '—') +
          '</td><td>' + (pmR ? h2h(pmR.headWins, pmR.headLosses) + ' / ' + h2h(pmR.jsWins, pmR.jsLosses) : '—') +
          '</td><td>' + (a ? fmt(a.bias, 2) : '—') + '</td><td>' + (a && a.biasMed != null ? fmt(a.biasMed, 2) : '—') +
          '</td><td>' + (a ? pctf(a.calibration80) : '—') +
          '</td><td>' + cell(vb) + '</td><td>' + cell(vbm) + '</td></tr>';
      });
      html += '</tbody></table>';
      // season rollup — median is the apples-to-apples read vs the books
      var tot = { w: 0, l: 0, t: 0, mw: 0, ml: 0, mt: 0, mae: 0, maeMed: 0, n: 0, band: 0, bn: 0 };
      wks.forEach(function (wk) {
        var a = state.accuracy[wk];
        if (!a) return;
        tot.w += a.vsBooks.wins; tot.l += a.vsBooks.losses; tot.t += a.vsBooks.ties;
        if (a.vsBooks.med) { tot.mw += a.vsBooks.med.wins; tot.ml += a.vsBooks.med.losses; tot.mt += a.vsBooks.med.ties; }
        tot.mae += a.mae * a.players; tot.maeMed += (a.maeMed || a.mae) * a.players; tot.n += a.players;
        tot.band += a.calibration80 * a.players; tot.bn += a.players;
      });
      if (tot.n) {
        html += '<p><b>Season so far:</b> MAE mean ' + (tot.mae / tot.n).toFixed(2) + ' / median ' + (tot.maeMed / tot.n).toFixed(2) +
          ' · 80% band hit ' + pctf(tot.band / tot.bn) + ' (target ~80%)' +
          ' · vs books mean ' + tot.w + '-' + tot.l + '-' + tot.t +
          (tot.w + tot.l ? ' (' + pctf(tot.w / (tot.w + tot.l)) + ')' : '') +
          ' · <b>median ' + tot.mw + '-' + tot.ml + '-' + tot.mt +
          (tot.mw + tot.ml ? ' (' + pctf(tot.mw / (tot.mw + tot.ml)) + ' — the fair comparison; need >52-55% sustained before going public)' : '') + '</b></p>';
      }
      // worst misses of most recent scored week
      var lastScored = wks.filter(function (w) { return state.accuracy[w]; }).pop();
      if (lastScored) {
        var a2 = state.accuracy[lastScored];
        html += '<h3>Week ' + lastScored + ' biggest misses</h3><table><thead><tr><th class="l">Player</th><th>Pos</th>' +
          '<th>Mean</th><th>Median</th><th>Actual</th><th>Miss (mean)</th></tr></thead><tbody>';
        a2.rows.slice(0, 12).forEach(function (r) {
          html += '<tr><td class="l">' + esc(r.name) + '</td><td>' + r.pos + '</td><td>' + fmt(r.mean) +
            '</td><td>' + (r.med != null ? fmt(r.med) : '—') + '</td><td>' + fmt(r.actual) + '</td><td>' + fmt(r.mean - r.actual) + '</td></tr>';
        });
        html += '</tbody></table>';
      }
    }
    $('tk-body').innerHTML = html;
  }

  function exportTracking() {
    download('simlab_tracking_export_' + new Date().toISOString().slice(0, 10) + '.json',
      { snapshots: state.snapshots, accuracy: state.accuracy });
    $('tk-note').textContent = 'Full tracking history exported.';
  }

  function download(name, obj) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(obj, null, 1)], { type: 'application/json' }));
    a.download = name;
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 5000);
  }
})();
