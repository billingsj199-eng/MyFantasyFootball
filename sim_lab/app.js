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
        if (st.zeros.length) {
          $('status').textContent += ' · wk ' + cur + ' injury layer: ' + st.zeros.length + ' out/docked';
          $('status').title = st.zeros.map(function (z) { return z.name + ' (' + z.tm + ' ' + z.pos + ') wk' + z.from + (z.to > z.from ? '-' + z.to : '') + (z.mult ? ' x' + z.mult : '') + ' [' + z.src + ']'; }).join('\n');
        } else if (active) {
          $('status').textContent += ' · wk ' + cur + ' injury layer: no designations';
        }
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
    { h: 'Our median', k: 'ours', get: function (o) { return o.ours; } },
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
      // closed-form CLEAN median ratio — the sim run's p50/mean carries the
      // prop anchor's level when it's on, which would soften the divergence
      var ratio = E.gammaMedRatio(r.player);
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
      (ss.key ? '' : ' · sorted by biggest % discrepancy') + ' · both sides are medians · click a column header to sort (# = back to the discrepancy order)</p>' +
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
      '<p class="dim" style="font-size:11px">Line = median across UD/PP/DK. Our median = CLEAN model stat mean × the player\'s closed-form ' +
      'gamma median ratio (unaffected by the prop anchor). Anytime TD compares PROBABILITIES: the books\' odds converted to implied % (juice included — books ' +
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
      $('sn-note').textContent = state.seasonResults.length + ' players × ' + label + ' simmed ' + sims +
        'x in ' + state.seasonMeta.ms.toFixed(0) + 'ms (' + $('sn-scoring').value.toUpperCase() + '). Click a row for the week-by-week path.';
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
      var ratio = r.mean > 1 ? r.p50 / r.mean : 1;
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
        var f = raw > 1 ? r.p50 / raw : 1;
        Object.keys(m).forEach(function (k) { m[k] *= f; });
      }
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
    Object.keys(raw).forEach(function (sid) {
      var c = raw[sid];
      var p = state.players.bySid[sid];
      // PUP players with an injury-start window (Clay projects a return)
      // are governed by the window, not blanket-excluded.
      var windowed = p && p.qbWindow && p.qbWindow.src === 'injury-start';
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
        lineupSlots: slots, scoring: E.scoringFromLeague(league.scoring_settings),
        synthSchedule: !anyPairs, demo: false,
        unavailable: unavailable, currentWeek: curWeek,
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
      var regCount = ss.regularSeasonMatchupPeriodCount || 14;
      var playoffStart = regCount + 1;
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
        synthSchedule: !anyPairs, demo: false, platform: 'espn',
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
    var scoring = E.scoringFromLeague({ rec: typeof fmt.ppr === 'number' ? fmt.ppr : 0.5 });

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
    var playoffSrc = +lg.playoffStart ? 'site snapshot' : (+slSet.playoff_week_start ? 'Sleeper (live)' : 'assumed');
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

    state.league = {
      id: 'mff:' + (lg.leagueId || lg.name), name: lg.name || 'MFF League', teams: teams,
      pairsByWeek: realPairs || roundRobin(teams.map(function (t2) { return t2.rosterId; }), regWeeks),
      regWeeks: simWeeks, playoffStart: playoffStart, playoffTeams: playoffTeams,
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
      ' · rec=' + scoring.rec + ' from the site format (pass TD assumed 4) · playoffs wk' + playoffStart + ' / ' + playoffTeams + ' teams (' + playoffSrc + ')' +
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
        playoffTeams: L.playoffTeams, playoffStart: L.playoffStart, lineupSlots: L.lineupSlots,
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
      pairsByWeek: L.pairsByWeek, regWeeks: L.regWeeks, playoffTeams: L.playoffTeams,
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

  function renderLeagueTeams() {
    var L = state.league;
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
    runBlocking('lg-run', 'lg-note', 'Simulating "' + L.name + '" ' + sims + 'x…', function () {
      var t0 = performance.now();
      state.leagueResults = E.simLeague({
        sims: sims, scoring: L.scoring, schedule: state.schedule, players: state.players,
        teams: L.teams, pairsByWeek: L.pairsByWeek, regWeeks: L.regWeeks,
        playoffTeams: L.playoffTeams, playoffStart: L.playoffStart, lineupSlots: L.lineupSlots,
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

      $('lg-note').textContent = '"' + L.name + '" — ' + sims + ' season sims in ' + ms.toFixed(0) + 'ms.' +
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
    var roundName = {};
    roundName[L.playoffStart] = 'Round 1';
    roundName[L.playoffStart + 1] = 'Semis';
    roundName[L.playoffStart + 2] = 'Championship';
    if (L.playoffTeams <= 4) { roundName[L.playoffStart] = 'Semis'; roundName[L.playoffStart + 1] = 'Championship'; delete roundName[L.playoffStart + 2]; }
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
  // Cameron, Chig→Chigoziem, Kenny/Ken→Kenneth), then same last name + first
  // initial when that leaves exactly one candidate. Position-gated whenever
  // the CSV/cloud row carries one, so name twins at other positions can't
  // steal the match.
  var _bbMatchCache = {};
  function bbMatchPlayer(name, pos) {
    var ck = name + '|' + (pos || '');
    if (ck in _bbMatchCache) return _bbMatchCache[ck];
    var m = bbMatchUncached(name, pos);
    _bbMatchCache[ck] = m;
    return m;
  }
  function bbMatchUncached(name, pos) {
    var nk = E.norm(name);
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
    var init = cands.filter(function (c) { return c.norm[0] === first[0]; });
    if (init.length === 1) return init[0];
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
  //  * RE-DRAFT playoffs (BBM itself, since BBM IV): every playoff round is
  //    a FRESH 18-pick draft (Dec timestamps in the rd2-rd4 files) — your
  //    drafted roster only plays wks 1-14, so playoff equity conditional on
  //    advancing is ~flat: EV = advCash x P(adv) + perAdvEV x P(adv).
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
    if (/best ball mania|bbm/i.test(title || '')) return 'redraft';
    return 'ladder';
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
  var PRIZE_PRESETS = [
    { re: /puppy/i, model: {
      adv15N: 10, adv16N: 10, finalsSize: 333, advCash: 0,
      ftiers: [{ top: 1, prize: 50000 }, { top: 10, prize: 2500 }, { top: 50, prize: 400 }],
      minCash: 100, perAdvEV: 25, pFinGivenAdv: 0.01
    } }
  ];
  function prizeFor(title) {
    var all = loadLS('simlab_bb_prize', {});
    var saved = all[title] || {};
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
        '<option value="redraft"' + (m.mode === 'redraft' ? ' selected' : '') + '>re-draft playoffs (BBM-style)</option>' +
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
      'Shares = where opponents target this defense (season-to-date, shrunk toward its 2025 shares) vs league; pts/tgt = half-PPR receiving points allowed per target in that zone vs league, shrunk toward 1.0x. Click a header to sort.</p>';
    wireSort('zn-body', COLS, ss, renderZonesTab);
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
      if (p.pos === 'QB') x += sc.pass_yd * c[1] + sc.pass_td * c[2] + sc.rush_yd * c[4] + sc.rush_td * c[5];
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
    else if (iA < 1) chips.push('docked ×' + ntF(iA, 2));
    else if (iA > 1.02) chips.push('role boost ×' + ntF(iA, 2));
    if (p.isDST) return chips;
    var l = E.tdLuckAdj(p, sc) * Math.min(1, iA);
    if (Math.abs(l) >= 0.05) chips.push('TD luck ' + ntSigned(l, 1));
    var w = E.weatherMult(p, wk, slot); if (w !== 1) chips.push('weather ×' + ntF(w, 2));
    var pr = E.pressureMult(slot.opp, p.pos); if (pr !== 1) chips.push('soft rush ×' + ntF(pr, 2));
    var cs = E.cbShadowMult(slot.opp, p.pos, p); if (cs !== 1) chips.push('CB shadow ×' + ntF(cs, 2));
    var cb = E.cb1OutBoost(slot.opp, p.pos, p); if (cb !== 1) chips.push('CB1 out ×' + ntF(cb, 2));
    var ol = E.olOutDock(p.tm, p.pos); if (ol !== 1) chips.push('OL out ×' + ntF(ol, 2));
    var sn = E.snapMult(p, wk); if (Math.abs(sn - 1) >= 0.02) chips.push('snap trend ×' + ntF(sn, 2));
    var rt = E.routeMult(p, wk); if (Math.abs(rt - 1) >= 0.02) chips.push('route trend ×' + ntF(rt, 2));
    if (wp && wp.propMean != null && wp.jsMean != null && Math.abs(wp.propMean - wp.jsMean) >= 1.5) {
      chips.push('market ' + (wp.propMean > wp.jsMean ? 'higher' : 'lower') + ' (' + ntF(wp.propMean, 1) + ' vs model ' + ntF(wp.jsMean, 1) + ')');
    }
    return chips;
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
      rows.push({ p: p, eff: eff, wp: wp, chips: chips, read: read, xf: xf });
    });
    rows.sort(function (x, y) { return y.eff - x.eff; });
    html += '<table style="margin-top:10px"><thead><tr><th class="l">Player</th><th>Tm</th><th>Pos</th><th>PROJ</th><th>Model</th><th>Market</th><th title="Expected fantasy points per game, 2026 to date (standard usage-based xFP)">xFP/g</th><th title="Actual PPG minus xFP/g: + = scoring over his usage, - = under (due up)">FPOE/g</th><th class="l">Why / notes</th><th class="l">Zone read</th></tr></thead><tbody>';
    T.push(''); T.push('PLAYERS (PROJ ' + $('nt-scoring').value + '):');
    rows.forEach(function (o) {
      html += '<tr><td class="l"><b>' + esc(o.p.name) + '</b></td><td>' + o.p.tm + '</td><td>' + o.p.pos + '</td><td><b>' + ntF(o.eff, 1) + '</b></td><td class="dim">' +
        ntF(o.wp.jsMean, 1) + '</td><td class="dim">' + (o.wp.propMean != null ? ntF(o.wp.propMean, 1) : '—') + '</td>' +
        '<td class="dim">' + (o.xf ? ntF(o.xf.xfpg, 1) : '—') + '</td>' +
        '<td' + (o.xf && o.xf.fpoeg != null ? ' style="color:' + (o.xf.fpoeg <= -1.5 ? 'var(--acc)' : o.xf.fpoeg >= 1.5 ? '#f85149' : 'var(--dim)') + '"' : ' class="dim"') + '>' + (o.xf && o.xf.fpoeg != null ? ntSigned(o.xf.fpoeg, 1) : '—') + '</td>' +
        '<td class="l" style="font-size:11px;white-space:normal;min-width:220px">' + o.chips.map(function (c) {
          var col = /OUT|docked|×0\.|luck -|lower|shadow/.test(c) ? '#f85149' : (/boost|×1\.|luck \+|higher|soft/.test(c) ? 'var(--acc)' : 'var(--dim)');
          return '<span style="border:1px solid ' + col + ';color:' + col + ';border-radius:9px;padding:0 6px;margin:1px 3px 1px 0;display:inline-block">' + esc(c) + '</span>';
        }).join('') + '</td><td class="l" style="font-size:11px;white-space:normal;min-width:220px">' + esc(o.read) + '</td></tr>';
      var line = '  ' + o.p.name + ' (' + o.p.tm + ' ' + o.p.pos + ') ' + ntF(o.eff, 1);
      if (o.xf && o.xf.fpoeg != null) line += ' · xFP ' + ntF(o.xf.xfpg, 1) + '/g (' + ntSigned(o.xf.fpoeg, 1) + ' over expected)';
      if (o.chips.length) line += ' [' + o.chips.join(', ') + ']';
      if (o.read) line += ' — ' + o.read;
      T.push(line);
    });
    html += '</tbody></table>';
    if (lg) {
      html += '<div style="display:flex;gap:28px;flex-wrap:wrap;align-items:flex-start;margin-top:12px">' +
        '<div>' + znDefCard(Z, g.home, lg, g.home + ' defense zones (vs ' + g.away + ')') + '</div>' +
        '<div>' + znDefCard(Z, g.away, lg, g.away + ' defense zones (vs ' + g.home + ')') + '</div></div>';
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

        comps: r.comps, lines: propByNorm[r.player.norm] || null
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
