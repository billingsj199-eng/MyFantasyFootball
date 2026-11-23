/* 2027 SIM RANKINGS — admin-only board (2026-11-21; inline like the other formats 2026-11-23).
 *
 * Loaded on demand by the "2027 SIMS" tab in the rankings Format row (_sim2027Open in app.js),
 * which only un-hides for admins. It renders in place of the rankings table, with the page's own
 * table look, and follows the page's Position pills and search box (app.js forwards them through
 * setFilter / setQuery). This file is public like the rest of the static site, but it contains NO
 * ranking data. The numbers live in Firestore at admin_sims/rankings_2027, and firestore.rules lets
 * only Jack's verified Google account read or write that collection (isJack()). Anyone else gets
 * "permission denied" from the database whatever they do in the browser. Never commit the
 * rankings CSV/JSON to this repo: it would be public.
 *
 * Updating: on the tab, UPDATE FILE -> choose the CSV the Sim Lab refresh wrote
 * (sim_lab\preseason2027\output\2027_inhouse_early.csv), check the preview board, then SAVE.
 *
 * API: window.MFFSim2027.mount(containerEl, {pos, q, sf}) / .unmount() / .setFilter(pos) / .setQuery(q)
 */
(function () {
  'use strict';
  var ADMIN_EMAILS = ['billingsj199@gmail.com']; // shown-or-hidden only; the real lock is firestore.rules
  var COLL = 'admin_sims', DOC = 'rankings_2027';
  var MAX_CSV_BYTES = 900000; // a Firestore document tops out near 1 MB
  // Local testing only: lets the file preview run without an admin sign-in. Nothing is read from the database.
  var LOCAL = location.protocol === 'file:' || /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);

  // Only what the page's own table styles (main.css: table / thead th / tbody td / .rank-cell /
  // .player-cell / .pos-badge) don't already cover.
  var CSS = [
    '.s27{padding:0 2rem 2rem}',
    '.s27 *{box-sizing:border-box}',
    '.s27-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 0 10px;font-family:"DM Sans",sans-serif}',
    '.s27-tag{font-size:.6875rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:2px 8px;border-radius:4px;white-space:nowrap}',
    '.s27-tag.pre{color:var(--accent);background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.35)}',
    '.s27-tag.prev{color:var(--red);background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.4)}',
    '.s27-info{font-size:.75rem;color:var(--text2);line-height:1.4}',
    '.s27-sp{flex:1 1 auto}',
    '.s27-fmt{display:inline-flex;gap:4px}',
    '.s27-btn{padding:3px 9px;font-family:"DM Sans",sans-serif;font-weight:600;text-transform:uppercase;font-size:.6875rem;letter-spacing:.04em;border-radius:4px;cursor:pointer;border:1px solid var(--accent);background:transparent;color:var(--accent);white-space:nowrap;min-height:26px}',
    '.s27-btn.go{border-color:#22c55e;color:#22c55e}',
    '.s27-btn.no{border-color:var(--border-strong);color:var(--text2)}',
    '.s27-btn:disabled{opacity:.45;cursor:default}',
    '.s27-msg{font-size:.75rem;width:100%}',
    '.s27-msg:empty{display:none}',
    '.s27-msg.ok{color:var(--green)}.s27-msg.err{color:var(--red)}',
    /* No scroll box of its own, same as the main table: #pageRankings is the scroller (both ways),
       and main.css pins #pageRankings thead th at --rnk-sticky-top, under the sticky filter rows.
       An overflow box here would become the sticky scrollport and push the header down the table. */
    /* table-layout:auto on purpose: main.css sets table{table-layout:fixed} under 600px for the
       rankings table, which would squeeze these columns until names run under the next cell. */
    '.s27 table{min-width:980px;table-layout:auto}',
    '.s27 tbody tr:nth-child(even){background:rgba(255,255,255,.018)}',
    '.s27 td.num,.s27 th.num{text-align:right}',
    '.s27 .s27-dim{color:var(--text2)}',
    /* Pos Rank reads as plain text next to the Pos badge on desktop; phones (no Pos column) keep the badge. */
    '@media (min-width:601px){.s27 .pos-badge.s27-prb{background:none;color:var(--text);padding:0;font-weight:400;font-size:.8rem;letter-spacing:0}}',
    '.s27 .s27-prov{display:inline-block;margin-left:5px;padding:0 5px;font-size:.625rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;border-radius:3px;line-height:1.5;vertical-align:middle;background:rgba(245,158,11,.15);color:var(--accent);cursor:help}',
    '.s27 .s27-range{display:inline-flex;align-items:center;gap:8px}',
    '.s27 .s27-rbar{position:relative;width:96px;height:6px;background:var(--elev-2);border-radius:3px}',
    '.s27 .s27-rbar i{position:absolute;top:0;bottom:0;background:var(--border-strong);border-radius:3px}',
    '.s27 .s27-rbar b{position:absolute;top:-3px;width:2px;height:12px;background:var(--accent)}',
    '.s27 .s27-hi{color:var(--red)}.s27 .s27-mid{color:var(--accent)}',
    '.s27-empty{padding:2.5rem 1rem;text-align:center;color:var(--text2);font-size:.85rem;line-height:1.5}',
    '.s27-empty b{display:block;color:var(--text);font-size:.95rem;margin-bottom:4px}',
    '.s27 [hidden]{display:none!important}',
    /* The main board's stats line (Showing / Moved counts) and TABLE / TIER CARDS toggle describe
       the hidden table, not this board. body.sim2027-on is set by _sim2027Open in app.js. */
    'body.sim2027-on #pageRankings .stats-bar,body.sim2027-on #adminViewToggle{display:none!important}',
    /* Phones: main.css turns #pageRankings rows into cards (tbody tr = flex card, thead hidden, the
       first cell = the main board's drag handle hidden). Same card here: # · player · pos rank ·
       PPG · season, the rest stays on desktop. */
    '@media (max-width:600px){.s27{padding:0 0 1rem}.s27-bar{padding:8px 10px 10px}.s27-info{width:100%}' +
      '#pageRankings .s27 table{min-width:0;table-layout:auto}' +
      '#pageRankings .s27 tbody td{display:none;padding:0}' +
      '#pageRankings .s27 tbody td.c-rk,#pageRankings .s27 tbody td.c-posRank,#pageRankings .s27 tbody td.c-ppg,#pageRankings .s27 tbody td.c-total{display:block;flex:0 0 auto}' +
      '#pageRankings .s27 tbody td.c-name{display:block;flex:1 1 auto;min-width:0}' +
      /* main.css styles the card's first cell as the drag-handle strip and force-hides cell 4 */
      '#pageRankings .s27 tbody tr td.c-rk{display:block;flex:0 0 26px;width:26px;margin:0;align-self:center;text-align:center;font-family:"Bebas Neue",sans-serif;font-size:1.05rem;letter-spacing:1px;color:var(--text2)}' +
      '#pageRankings .s27 tbody tr td.c-posRank{display:block!important}' +
      '#pageRankings .s27 .player-name,#pageRankings .s27 .player-team{white-space:normal}' +
      '#pageRankings .s27 tbody td.c-ppg,#pageRankings .s27 tbody td.c-total{min-width:42px;text-align:right}' +
      '#pageRankings .s27 tbody td.c-ppg::before,#pageRankings .s27 tbody td.c-total::before{display:block;font-size:.5625rem;font-weight:600;letter-spacing:.04em;color:var(--text2)}' +
      '#pageRankings .s27 tbody td.c-ppg::before{content:"PPG"}#pageRankings .s27 tbody td.c-total::before{content:"SEASON"}' +
      '#pageRankings .s27 tbody td[colspan]{display:block;width:100%}}'
  ].join('\n');

  var HTML =
    '<div class="s27">' +
      '<div class="s27-bar">' +
        '<span class="s27-tag pre" title="Preliminary board from the in-house Sim Lab preseason model">2027 · Preliminary</span>' +
        '<span class="s27-tag prev" data-s="previewTag" hidden>Preview, not saved</span>' +
        '<span class="s27-info" data-s="info"></span>' +
        '<span class="s27-sp"></span>' +
        '<span class="s27-fmt" data-s="fmt" hidden>' +
          '<button type="button" class="mff-mode-chip" data-fmt="1QB">1QB</button>' +
          '<button type="button" class="mff-mode-chip" data-fmt="SF">SUPERFLEX</button>' +
        '</span>' +
        '<input type="file" data-s="file" accept=".csv,text/csv" hidden aria-label="Sim Lab rankings file">' +
        '<button type="button" class="s27-btn" data-s="btnFile" title="Load the file the Sim Lab refresh wrote: sim_lab\\preseason2027\\output\\2027_inhouse_early.csv. It shows as a preview first; nothing is saved until you press SAVE. The file is stored in the private database, never on the public site.">Update file</button>' +
        '<button type="button" class="s27-btn go" data-s="btnSave" hidden>Save</button>' +
        '<button type="button" class="s27-btn no" data-s="btnDiscard" hidden>Discard</button>' +
        '<div class="s27-msg" data-s="msg"></div>' +
      '</div>' +
      '<div class="s27-empty" data-s="empty" hidden><b data-s="emptyTitle"></b><span data-s="emptyBody"></span></div>' +
      '<div class="s27-scroll" data-s="tableArea" hidden><table><thead><tr data-s="thead"></tr></thead><tbody data-s="tbody"></tbody></table></div>' +
    '</div>';

  var root = null, db = null, mountId = 0;
  var state = null;
  function fresh() { return { rows: [], saved: null, pending: null, pos: 'ALL', fmt: '1QB', q: '', sort: null, dir: 1, meta: null }; }
  function $(k) { return root ? root.querySelector('[data-s="' + k + '"]') : null; }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function currentUser() { try { return (window.firebase && firebase.auth) ? firebase.auth().currentUser : null; } catch (e) { return null; } }
  function isAdminUser(u) {
    return !!(u && u.email && u.emailVerified === true && ADMIN_EMAILS.indexOf(u.email.toLowerCase()) !== -1);
  }

  // ---------- CSV ----------
  function parseCsv(text) {
    var rows = [], row = [], cur = '', inQ = false, i, c;
    text = text.replace(/^﻿/, '');
    for (i = 0; i < text.length; i++) {
      c = text[i];
      if (inQ) {
        if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else inQ = false; }
        else cur += c;
      } else if (c === '"') inQ = true;
      else if (c === ',') { row.push(cur); cur = ''; }
      else if (c === '\n' || c === '\r') {
        if (c === '\r' && text[i + 1] === '\n') i++;
        row.push(cur); cur = '';
        if (row.length > 1 || row[0] !== '') rows.push(row);
        row = [];
      } else cur += c;
    }
    if (cur !== '' || row.length) { row.push(cur); rows.push(row); }
    return rows;
  }
  function num(v) { if (v === '' || v == null) return null; var n = Number(v); return isFinite(n) ? n : null; }
  function truthy(v) { if (v == null) return false; var s = String(v).trim().toLowerCase(); return !(s === '' || s === '0' || s === '0.0' || s === 'false' || s === 'no' || s === 'nan'); }

  // Turns the Sim Lab CSV into rows. Unknown columns are ignored and missing ones show as blank,
  // so the view keeps working as the model adds columns (rookies, JM, stage).
  function toRows(csvText) {
    var t = parseCsv(csvText);
    if (t.length < 2) throw new Error('The file has no rows.');
    var head = t[0].map(function (h) { return h.trim(); });
    ['name', 'pos', 'total'].forEach(function (k) {
      if (head.indexOf(k) === -1) throw new Error('This doesn\'t look like the Sim Lab rankings file (no "' + k + '" column).');
    });
    var out = [];
    for (var r = 1; r < t.length; r++) {
      var o = {};
      for (var c = 0; c < head.length; c++) o[head[c]] = t[r][c];
      var name = String(o.name || '').trim();
      if (!name) continue;
      var prov = truthy(o.provisional) || truthy(o.rookie) || /provisional/i.test(name) || /provisional/i.test(o.status || '');
      out.push({
        name: name.replace(/\s*[\[(]?\s*provisional\s*[\])]?\s*/i, ' ').trim(),
        pos: String(o.pos || '').trim().toUpperCase(),
        team: String(o.team || '').trim() || '—',
        rank: num(o.rank), posRank: num(o.pos_rank),
        ppg: num(o.ppg), games: num(o.games), total: num(o.total),
        p10: num(o.tot_p10), p90: num(o.tot_p90),
        prev: num(o.ppg26), age: num(o.age),
        bench: num(o.p_bench),
        sfRank: num(o.sf12_rank),
        rookie: prov,
        jm: num(o.jm != null ? o.jm : o.jm_score), school: String(o.school || '').trim(),
        status: String(o.class_status || o.status || '').trim(),
        round: String(o.implied_round || o.draft_round || '').trim()
      });
    }
    if (!out.length) throw new Error('No players found in the file.');
    // Fill any missing ranks from the season total so the table always has an order.
    out.slice().sort(function (a, b) { return (b.total || 0) - (a.total || 0); })
       .forEach(function (p, i) { if (p.rank == null) p.rank = i + 1; });
    ['QB', 'RB', 'WR', 'TE'].forEach(function (pos) {
      out.filter(function (p) { return p.pos === pos; })
         .sort(function (a, b) { return a.rank - b.rank; })
         .forEach(function (p, i) { if (p.posRank == null) p.posRank = i + 1; });
    });
    return out;
  }

  // ---------- render ----------
  function boardRank(p) { return state.fmt === 'SF' && p.sfRank != null ? p.sfRank : p.rank; }
  var COLS = [
    { k: 'rk', t: '#', get: boardRank },
    { k: 'name', t: 'Player' },
    { k: 'pos', t: 'Pos' },
    { k: 'posRank', t: 'Pos Rank' },
    { k: 'ppg', t: 'Proj PPG', n: 1, g: 'Sim Lab projected fantasy points per game for 2027 (half-PPR).' },
    { k: 'games', t: 'Games', n: 1, g: 'Projected games played in 2027.' },
    { k: 'total', t: 'Season', n: 1, g: 'Projected 2027 season total (half-PPR) = the number the board is ranked by.' },
    { k: 'p10', t: 'Range', nosort: true, g: 'Season-total range across the sims: 10th to 90th percentile. The amber tick is the projection.' },
    { k: 'prev', t: '\'26 PPG', n: 1, g: 'Fantasy points per game so far in 2026.' },
    { k: 'age', t: 'Age', n: 1 },
    { k: 'bench', t: 'Bench Risk', n: 1, g: 'Chance he loses the starting job / meaningful role in 2027.' }
  ];
  var DASH = '<span class="s27-dim">—</span>';
  function fmt1(n) { return n == null ? DASH : n.toFixed(1); }
  function fmt0(n) { return n == null ? DASH : Math.round(n).toString(); }

  // The page's Position pills: ALL / QB / RB / WR / TE / FLEX / ROOKIE map onto the sim rows;
  // K, D/ST and DEVY have no 2027 sims.
  function posOk(p) {
    var f = state.pos;
    if (f === 'ALL') return true;
    if (f === 'FLEX') return p.pos === 'RB' || p.pos === 'WR' || p.pos === 'TE';
    if (f === 'ROOKIE') return p.rookie;
    return p.pos === f;
  }
  function visibleRows() {
    var q = state.q.trim().toLowerCase();
    var rows = state.rows.filter(function (p) {
      if (!posOk(p)) return false;
      if (q && (p.name + ' ' + p.team + ' ' + p.school).toLowerCase().indexOf(q) === -1) return false;
      return true;
    });
    var col = state.sort ? COLS.filter(function (c) { return c.k === state.sort; })[0] : COLS[0];
    var get = col.get || function (p) { return p[col.k]; };
    var dir = state.sort ? state.dir : 1;
    rows.sort(function (a, b) {
      var x = get(a), y = get(b);
      if (x == null && y == null) return a.rank - b.rank;
      if (x == null) return 1; if (y == null) return -1;
      if (typeof x === 'string') return dir * x.localeCompare(y);
      return dir * (x - y) || a.rank - b.rank;
    });
    return rows;
  }

  function render() {
    if (!root || !state.rows.length) return;
    var rows = visibleRows();
    var maxHi = Math.max.apply(null, state.rows.map(function (p) { return p.p90 || p.total || 0; })) || 1;
    var sortKey = state.sort || 'rk';
    $('thead').innerHTML = COLS.map(function (c) {
      var on = c.k === sortKey;
      var label = c.g ? '<span data-gloss="' + esc(c.g) + '" title="' + esc(c.g) + '">' + esc(c.t) + '</span>' : esc(c.t);
      return '<th class="c-' + c.k + (c.n ? ' num' : '') + (on ? ' sorted' : '') + '"' + (c.nosort ? '' : ' data-sort="' + c.k + '" tabindex="0"') +
        ' aria-sort="' + (on ? (state.dir === 1 ? 'ascending' : 'descending') : 'none') + '">' +
        label + (c.nosort ? '' : ' <span class="arrow">' + (on ? (state.dir === 1 ? '▲' : '▼') : '') + '</span>') + '</th>';
    }).join('');
    if (!rows.length) {
      var why = (state.pos === 'K' || state.pos === 'DST' || state.pos === 'DEVY')
        ? 'The 2027 sims cover QB, RB, WR and TE.' : 'No players match.';
      $('tbody').innerHTML = '<tr><td class="s27-dim" colspan="' + COLS.length + '" style="padding:2rem;text-align:center">' + why + '</td></tr>';
      return;
    }
    $('tbody').innerHTML = rows.map(function (p) {
      var rk = boardRank(p);
      var range = DASH;
      if (p.p10 != null && p.p90 != null) {
        var l = Math.max(0, p.p10 / maxHi * 100), w = Math.max(1, (p.p90 - p.p10) / maxHi * 100), m = Math.min(100, (p.total || 0) / maxHi * 100);
        range = '<span class="s27-range"><span class="s27-rbar"><i style="left:' + l.toFixed(1) + '%;width:' + w.toFixed(1) + '%"></i><b style="left:' + m.toFixed(1) + '%"></b></span>' +
          '<span class="s27-dim">' + Math.round(p.p10) + '–' + Math.round(p.p90) + '</span></span>';
      }
      var bench = DASH;
      if (p.bench != null) {
        var pct = Math.round(p.bench * 100);
        bench = '<span class="' + (pct >= 40 ? 's27-hi' : pct >= 25 ? 's27-mid' : '') + '">' + pct + '%</span>';
      }
      var sub = [p.team];
      if (p.school) sub.push(p.school);
      if (p.jm != null) sub.push('JM ' + p.jm.toFixed(1));
      if (p.round) sub.push('Rd ' + p.round);
      if (p.status) sub.push(p.status);
      var posCls = /^(QB|RB|WR|TE)$/.test(p.pos) ? p.pos : '';
      return '<tr>' +
        '<td class="rank-cell c-rk">' + (rk == null ? '' : rk) + '</td>' +
        '<td class="c-name"><div class="player-cell"><span class="player-name">' + esc(p.name) +
          (p.rookie ? '<span class="s27-prov" title="Rookie placeholder: no draft pick or team yet">Provisional</span>' : '') +
          '</span><span class="player-team">' + esc(sub.join(' · ')) + '</span></div></td>' +
        '<td class="c-pos"><span class="pos-badge ' + posCls + '">' + esc(p.pos) + '</span></td>' +
        '<td class="c-posRank">' + (p.posRank == null ? DASH : '<span class="pos-badge s27-prb ' + posCls + '">' + esc(p.pos) + p.posRank + '</span>') + '</td>' +
        '<td class="num c-ppg">' + fmt1(p.ppg) + '</td>' +
        '<td class="num c-games">' + fmt1(p.games) + '</td>' +
        '<td class="num c-total"><b>' + fmt0(p.total) + '</b></td>' +
        '<td class="c-p10">' + range + '</td>' +
        '<td class="num s27-dim c-prev">' + fmt1(p.prev) + '</td>' +
        '<td class="num s27-dim c-age">' + fmt1(p.age) + '</td>' +
        '<td class="num c-bench">' + bench + '</td>' +
        '</tr>';
    }).join('');
  }

  function drawFmt() {
    var hasSf = state.rows.some(function (p) { return p.sfRank != null; });
    var wrap = $('fmt');
    wrap.hidden = !hasSf;
    Array.prototype.forEach.call(wrap.querySelectorAll('button'), function (b) {
      b.classList.toggle('active', b.getAttribute('data-fmt') === state.fmt);
    });
  }

  function showData(rows, meta, isPreview) {
    if (!root) return;
    state.rows = rows; state.meta = meta;
    $('previewTag').hidden = !isPreview;
    $('empty').hidden = true;
    $('tableArea').hidden = false;
    var rook = rows.filter(function (p) { return p.rookie; }).length;
    var bits = ['Half-PPR, 12-team', rows.length + ' players', 'Sim Lab model, no ADP'];
    bits.push(rook ? rook + ' rookies are placeholders (no pick or team yet)' : 'no 2027 rookies yet');
    if (meta && meta.savedAt) bits.push('saved ' + new Date(meta.savedAt).toLocaleDateString());
    else if (meta && meta.fileName) bits.push(meta.fileName);
    $('info').textContent = bits.join(' · ');
    $('info').title = 'Can\'t know free agency, coaching changes, the draft or 2027 depth charts until they happen.' +
      (meta && meta.fileName ? ' File: ' + meta.fileName + '.' : '') +
      (meta && meta.fileDate ? ' File dated ' + new Date(meta.fileDate).toLocaleString() + '.' : '');
    drawFmt(); render();
  }
  function showEmpty(title, body) {
    if (!root) return;
    state.rows = [];
    $('tableArea').hidden = true; $('empty').hidden = false;
    $('emptyTitle').textContent = title; $('emptyBody').textContent = body;
    $('info').textContent = '';
    $('fmt').hidden = true;
  }
  function setMsg(text, kind) { var m = $('msg'); if (!m) return; m.textContent = text || ''; m.className = 's27-msg' + (kind ? ' ' + kind : ''); }
  var NO_SAVED = ['No 2027 rankings saved yet.', 'Press UPDATE FILE above and choose sim_lab\\preseason2027\\output\\2027_inhouse_early.csv.'];
  function setPreviewButtons(on) {
    $('btnSave').hidden = !on; $('btnDiscard').hidden = !on; $('btnFile').hidden = on;
  }

  // ---------- data ----------
  function loadSaved() {
    var my = mountId;
    if (!db) return;
    db.collection(COLL).doc(DOC).get().then(function (snap) {
      if (my !== mountId || !root) return;
      if (!snap.exists) { state.saved = null; if (!state.pending) showEmpty(NO_SAVED[0], NO_SAVED[1]); return; }
      var d = snap.data();
      state.saved = d;
      if (state.pending) return; // a file preview is on screen; don't replace it
      try { showData(toRows(d.csv || ''), d, false); }
      catch (e) { showEmpty('The saved file couldn\'t be read.', e.message); }
    }).catch(function (e) {
      if (my !== mountId || !root || state.pending) return;
      if (e && e.code === 'permission-denied') {
        showEmpty('The 2027 rankings database is locked for this account.',
          'Only the admin account can read it. If you are signed in as the admin, the admin_sims rule in firestore.rules hasn\'t been deployed yet. You can still preview a file with UPDATE FILE.');
      } else {
        showEmpty('Couldn\'t load the 2027 rankings.', (e && e.message) || 'Check your connection and try again.');
      }
    });
  }

  function onFile() {
    var f = this.files && this.files[0];
    setMsg('');
    if (!f) return;
    var rd = new FileReader();
    rd.onload = function () {
      if (!root) return;
      try {
        var text = String(rd.result);
        var rows = toRows(text);
        var bytes = new Blob([text]).size;
        if (bytes > MAX_CSV_BYTES) throw new Error('The file is too large to save (' + Math.round(bytes / 1024) + ' KB; the limit is ' + Math.round(MAX_CSV_BYTES / 1024) + ' KB).');
        state.pending = { csv: text, fileName: f.name, fileDate: f.lastModified || null, rowCount: rows.length };
        showData(rows, state.pending, true);
        setPreviewButtons(true);
        var canSave = !!db && isAdminUser(currentUser());
        $('btnSave').disabled = !canSave;
        setMsg('Previewing ' + rows.length + ' players from ' + f.name + '. ' + (canSave ? 'Nothing is saved until you press SAVE.' : 'Saving needs the admin sign-in and the database.'));
      } catch (e) {
        state.pending = null;
        setMsg(e.message, 'err');
      }
    };
    rd.onerror = function () { setMsg('Couldn\'t read that file.', 'err'); };
    rd.readAsText(f);
  }
  function onDiscard() {
    state.pending = null; $('file').value = ''; setPreviewButtons(false); setMsg('');
    $('previewTag').hidden = true;
    if (state.saved) { try { showData(toRows(state.saved.csv || ''), state.saved, false); } catch (e) { showEmpty('The saved file couldn\'t be read.', e.message); } }
    else if (db) loadSaved();
    else showEmpty(NO_SAVED[0], NO_SAVED[1]);
  }
  function onSave() {
    var p = state.pending, btn = $('btnSave'), u = currentUser(), my = mountId;
    if (!p || !db || !isAdminUser(u)) return;
    btn.disabled = true; setMsg('Saving…');
    var doc = { csv: p.csv, fileName: p.fileName, fileDate: p.fileDate, rowCount: p.rowCount, savedAt: new Date().toISOString(), savedBy: u.email };
    db.collection(COLL).doc(DOC).set(doc).then(function () {
      if (my !== mountId || !root) return;
      state.saved = doc; state.pending = null; $('file').value = ''; setPreviewButtons(false);
      showData(toRows(doc.csv), doc, false);
      setMsg('Saved ' + doc.rowCount + ' players to the private database.', 'ok');
    }).catch(function (e) {
      if (my !== mountId || !root) return;
      btn.disabled = false;
      setMsg(e && e.code === 'permission-denied'
        ? 'Not saved: the admin_sims database rule isn\'t deployed yet, or this account isn\'t the admin.'
        : 'Not saved: ' + ((e && e.message) || 'unknown error'), 'err');
    });
  }
  function onSort(e) {
    if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
    var th = e.target.closest('th[data-sort]'); if (!th) return;
    if (e.type === 'keydown') e.preventDefault();
    var k = th.getAttribute('data-sort');
    var asc = (k === 'rk' || k === 'posRank' || k === 'name' || k === 'pos' || k === 'age');
    if ((state.sort || 'rk') === k) state.dir = -state.dir; else { state.sort = k; state.dir = asc ? 1 : -1; }
    if (k === 'rk' && state.dir === 1) state.sort = null;
    render();
  }

  function mount(container, opts) {
    if (!container) return;
    unmount();
    if (!document.getElementById('s27Style')) {
      var st = document.createElement('style'); st.id = 's27Style'; st.textContent = CSS; document.head.appendChild(st);
    }
    mountId++;
    state = fresh();
    opts = opts || {};
    if (opts.pos) state.pos = opts.pos;
    if (opts.q) state.q = String(opts.q);
    if (opts.sf) state.fmt = 'SF';
    container.innerHTML = HTML;
    root = container.querySelector('.s27');
    $('file').addEventListener('change', onFile);
    $('btnFile').addEventListener('click', function () { $('file').click(); });
    $('btnDiscard').addEventListener('click', onDiscard);
    $('btnSave').addEventListener('click', onSave);
    $('fmt').addEventListener('click', function (e) {
      var b = e.target.closest('button[data-fmt]'); if (!b) return;
      state.fmt = b.getAttribute('data-fmt'); state.sort = null; state.dir = 1; drawFmt(); render();
    });
    $('thead').addEventListener('click', onSort);
    $('thead').addEventListener('keydown', onSort);

    var admin = isAdminUser(currentUser());
    if (!admin && !LOCAL) { $('btnFile').hidden = true; showEmpty('This board isn\'t available for this account.', 'Sign in with the admin Google account, then open the tab again.'); return; }
    if (!admin) { showEmpty('Local preview, not signed in as admin.', 'Press UPDATE FILE to preview a file. Nothing is read from or saved to the database.'); return; }
    showEmpty('Loading the 2027 rankings…', '');
    var my = mountId;
    var go = function () {
      if (my !== mountId || !root) return;
      try { db = firebase.firestore(); } catch (e) { db = null; }
      if (!db) { showEmpty('The database isn\'t available right now.', 'Reload the site and open the tab again. You can still preview a file with UPDATE FILE.'); return; }
      loadSaved();
    };
    if (typeof window._whenFirebaseReady === 'function') window._whenFirebaseReady(go); else go();
  }
  function unmount() {
    mountId++;
    if (root && root.parentNode) root.parentNode.innerHTML = '';
    root = null; state = fresh();
  }
  function setFilter(pos) { if (!state) return; state.pos = pos || 'ALL'; render(); }
  function setQuery(q) { if (!state) return; state.q = String(q || ''); render(); }

  window.MFFSim2027 = { mount: mount, unmount: unmount, setFilter: setFilter, setQuery: setQuery };
})();
