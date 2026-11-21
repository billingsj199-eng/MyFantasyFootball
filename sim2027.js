/* 2027 SIM RANKINGS — admin-only view (2026-11-21).
 *
 * Loaded on demand by the "2027 SIMS" tab in the rankings Format row (_sim2027Open in app.js),
 * which only un-hides for admins. This file is public like the rest of the static site, but it
 * contains NO ranking data. The numbers live in Firestore at admin_sims/rankings_2027, and
 * firestore.rules lets only Jack's verified Google account read or write that collection
 * (isJack()). Anyone else gets "permission denied" from the database whatever they do in the
 * browser. Never commit the rankings CSV/JSON to this repo: it would be public.
 *
 * Updating: open the tab, choose the CSV the Sim Lab refresh wrote
 * (sim_lab\preseason2027\output\2027_inhouse_early.csv), check the preview, then Save.
 *
 * API: window.MFFSim2027.mount(containerEl) / .unmount()
 */
(function () {
  'use strict';
  var ADMIN_EMAILS = ['billingsj199@gmail.com']; // shown-or-hidden only; the real lock is firestore.rules
  var COLL = 'admin_sims', DOC = 'rankings_2027';
  var MAX_CSV_BYTES = 900000; // a Firestore document tops out near 1 MB
  // Local testing only: lets the file preview run without an admin sign-in. Nothing is read from the database.
  var LOCAL = location.protocol === 'file:' || /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);

  var CSS = [
    '.s27{max-width:1180px;margin:0 auto;padding:14px 14px 60px;color:var(--text);font:14px/1.45 "DM Sans",-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}',
    '.s27 *{box-sizing:border-box}',
    '.s27 .s27-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;margin-top:12px}',
    '.s27 .s27-note{border-left:3px solid var(--accent2);background:rgba(245,158,11,.08);padding:9px 12px;border-radius:0 8px 8px 0}',
    '.s27 .s27-note b{color:var(--accent2)}',
    '.s27 .s27-meta{color:var(--text2);font-size:12px;margin-top:8px}',
    '.s27 .s27-pill{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;letter-spacing:.4px;text-transform:uppercase}',
    '.s27 .s27-prov{background:rgba(251,191,36,.16);color:var(--accent2);margin-left:6px}',
    '.s27 .s27-preview{background:rgba(239,68,68,.16);color:var(--red);border:1px solid rgba(239,68,68,.4)}',
    '.s27 .s27-controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:14px}',
    '.s27 .s27-tabs{display:flex;border:1px solid var(--border);border-radius:8px;overflow:hidden}',
    '.s27 .s27-tabs button{font:inherit;cursor:pointer;border:0;border-right:1px solid var(--border);background:transparent;color:var(--text);padding:7px 13px}',
    '.s27 .s27-tabs button:last-child{border-right:0}',
    '.s27 .s27-tabs button.on{background:var(--accent);color:var(--accent-ink);font-weight:700}',
    '.s27 input[type=search]{font:inherit;background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:7px 10px;min-width:190px}',
    '.s27 label.s27-chk{color:var(--text2);display:inline-flex;gap:6px;align-items:center;cursor:pointer}',
    '.s27 .s27-count{color:var(--text2);margin-left:auto;font-size:12px}',
    '.s27 .s27-tablewrap{overflow-x:auto;margin-top:12px;border:1px solid var(--border);border-radius:10px}',
    /* table-layout:auto on purpose: main.css sets table{table-layout:fixed} under 600px for the
       rankings table, which would squeeze these columns until names run under the next cell. */
    '.s27 table{border-collapse:collapse;width:100%;min-width:860px;table-layout:auto}',
    '.s27 th,.s27 td{padding:7px 10px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--border)}',
    '.s27 th{background:var(--surface2);color:var(--text2);font-size:11px;text-transform:uppercase;letter-spacing:.4px;cursor:pointer;user-select:none;font-weight:600}',
    '.s27 th.l,.s27 td.l{text-align:left}',
    '.s27 th.sorted{color:var(--accent)}',
    '.s27 tbody tr:hover{background:var(--elev-1)}',
    '.s27 tbody tr:last-child td{border-bottom:0}',
    '.s27 td.s27-name{font-weight:600}',
    '.s27 td.s27-rank{color:var(--text2);width:44px}',
    '.s27 .s27-pos{display:inline-block;min-width:38px;text-align:center;padding:1px 6px;border-radius:5px;font-size:11px;font-weight:700;color:#0a0e17}',
    '.s27 .s27-pos.QB{background:var(--qb)}.s27 .s27-pos.RB{background:var(--rb)}.s27 .s27-pos.WR{background:var(--wr)}.s27 .s27-pos.TE{background:var(--te)}',
    '.s27 .s27-range{display:inline-flex;align-items:center;gap:8px}',
    '.s27 .s27-bar{position:relative;width:110px;height:6px;background:var(--elev-2);border-radius:3px}',
    '.s27 .s27-bar i{position:absolute;top:0;bottom:0;background:var(--border-strong);border-radius:3px}',
    '.s27 .s27-bar b{position:absolute;top:-3px;width:2px;height:12px;background:var(--accent)}',
    '.s27 .s27-dim{color:var(--text2)}',
    '.s27 .s27-hi{color:var(--red)}.s27 .s27-mid{color:var(--accent2)}',
    '.s27 .s27-upd h2{font-size:15px;margin:0 0 6px;font-family:inherit;letter-spacing:0}',
    '.s27 .s27-upd p{color:var(--text2);margin:0 0 10px}',
    '.s27 .s27-row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}',
    '.s27 .s27-btn{font:inherit;cursor:pointer;border-radius:8px;border:1px solid var(--border-strong);background:var(--surface2);color:var(--text);padding:8px 14px}',
    '.s27 .s27-btn.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-ink);font-weight:700}',
    '.s27 .s27-btn:disabled{opacity:.5;cursor:default}',
    '.s27 .s27-msg{margin-top:10px;font-size:13px}',
    '.s27 .s27-msg.ok{color:var(--green)}.s27 .s27-msg.err{color:var(--red)}',
    '.s27 code{background:var(--surface2);padding:1px 5px;border-radius:4px;font-size:12px}',
    '.s27 [hidden]{display:none!important}'
  ].join('\n');

  var HTML =
    '<div class="s27">' +
      '<div class="s27-card" data-s="empty" hidden><b data-s="emptyTitle"></b><div class="s27-meta" data-s="emptyBody"></div></div>' +
      '<div data-s="dataArea" hidden>' +
        '<div class="s27-card"><div class="s27-note" data-s="stageNote"></div>' +
          '<div class="s27-meta"><span data-s="metaLine"></span> <span class="s27-pill s27-preview" data-s="previewPill" hidden>Preview, not saved</span></div></div>' +
        '<div class="s27-controls">' +
          '<div class="s27-tabs" data-s="posTabs"></div>' +
          '<div class="s27-tabs" data-s="fmtTabs" hidden></div>' +
          '<input type="search" data-s="q" placeholder="Search player or team" aria-label="Search player or team">' +
          '<label class="s27-chk" data-s="rookWrap" hidden><input type="checkbox" data-s="rookOnly"> Rookies only</label>' +
          '<span class="s27-count" data-s="count"></span>' +
        '</div>' +
        '<div class="s27-tablewrap"><table><thead><tr data-s="thead"></tr></thead><tbody data-s="tbody"></tbody></table></div>' +
      '</div>' +
      '<div class="s27-card s27-upd">' +
        '<h2>Update the rankings</h2>' +
        '<p>Choose the file the Sim Lab refresh wrote: <code>sim_lab\\preseason2027\\output\\2027_inhouse_early.csv</code>. Check the preview above, then save. The file is stored in the private database, never on the public site.</p>' +
        '<div class="s27-row">' +
          '<input type="file" data-s="file" accept=".csv,text/csv" aria-label="Sim Lab rankings file">' +
          '<button type="button" class="s27-btn primary" data-s="btnSave" disabled>Save to private database</button>' +
          '<button type="button" class="s27-btn" data-s="btnDiscard" hidden>Discard preview</button>' +
        '</div>' +
        '<div class="s27-msg" data-s="updMsg"></div>' +
      '</div>' +
    '</div>';

  var root = null, db = null, mountId = 0;
  var state = null;
  function fresh() { return { rows: [], saved: null, pending: null, pos: 'ALL', fmt: '1QB', q: '', rookOnly: false, sort: null, dir: 1 }; }
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
  var COLS = [
    { k: 'rk', t: '#', get: function (p) { return state.fmt === 'SF' && p.sfRank != null ? p.sfRank : p.rank; } },
    { k: 'name', t: 'Player', l: true },
    { k: 'pos', t: 'Pos', l: true },
    { k: 'team', t: 'Team', l: true },
    { k: 'posRank', t: 'Pos rank' },
    { k: 'ppg', t: 'PPG' },
    { k: 'games', t: 'Games' },
    { k: 'total', t: 'Season total' },
    { k: 'p10', t: 'Range (10th to 90th)', l: true, nosort: true },
    { k: 'prev', t: '2026 PPG' },
    { k: 'age', t: 'Age' },
    { k: 'bench', t: 'Bench risk' }
  ];
  var DASH = '<span class="s27-dim">—</span>';
  function fmt1(n) { return n == null ? DASH : n.toFixed(1); }
  function fmt0(n) { return n == null ? DASH : Math.round(n).toString(); }

  function visibleRows() {
    var q = state.q.trim().toLowerCase();
    var rows = state.rows.filter(function (p) {
      if (state.pos !== 'ALL' && p.pos !== state.pos) return false;
      if (state.rookOnly && !p.rookie) return false;
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
    if (!root) return;
    var rows = visibleRows();
    var maxHi = Math.max.apply(null, state.rows.map(function (p) { return p.p90 || p.total || 0; })) || 1;
    var sortKey = state.sort || 'rk';
    $('thead').innerHTML = COLS.map(function (c) {
      return '<th class="' + (c.l ? 'l ' : '') + (c.k === sortKey ? 'sorted' : '') + '" data-k="' + c.k + '"' + (c.nosort ? ' data-nosort="1"' : '') + '>' +
        esc(c.t) + (c.k === sortKey ? (state.dir === 1 ? ' ▲' : ' ▼') : '') + '</th>';
    }).join('');
    var html = rows.map(function (p) {
      var rk = state.fmt === 'SF' && p.sfRank != null ? p.sfRank : p.rank;
      var range = DASH;
      if (p.p10 != null && p.p90 != null) {
        var l = Math.max(0, p.p10 / maxHi * 100), w = Math.max(1, (p.p90 - p.p10) / maxHi * 100), m = Math.min(100, (p.total || 0) / maxHi * 100);
        range = '<span class="s27-range"><span class="s27-bar"><i style="left:' + l.toFixed(1) + '%;width:' + w.toFixed(1) + '%"></i><b style="left:' + m.toFixed(1) + '%"></b></span>' +
          '<span class="s27-dim">' + Math.round(p.p10) + ' to ' + Math.round(p.p90) + '</span></span>';
      }
      var bench = DASH;
      if (p.bench != null) {
        var pct = Math.round(p.bench * 100);
        bench = '<span class="' + (pct >= 40 ? 's27-hi' : pct >= 25 ? 's27-mid' : '') + '">' + pct + '%</span>';
      }
      var extra = [];
      if (p.school) extra.push(p.school);
      if (p.jm != null) extra.push('JM ' + p.jm.toFixed(1));
      if (p.round) extra.push('Rd ' + p.round);
      if (p.status) extra.push(p.status);
      return '<tr>' +
        '<td class="s27-rank">' + (rk == null ? '' : rk) + '</td>' +
        '<td class="l s27-name">' + esc(p.name) + (p.rookie ? '<span class="s27-pill s27-prov" title="Rookie placeholder: no draft pick or team yet">Provisional</span>' : '') +
          (extra.length ? ' <span class="s27-dim" style="font-weight:400;font-size:12px">' + esc(extra.join(' · ')) + '</span>' : '') + '</td>' +
        '<td class="l"><span class="s27-pos ' + esc(p.pos) + '">' + esc(p.pos) + (p.posRank != null ? p.posRank : '') + '</span></td>' +
        '<td class="l s27-dim">' + esc(p.team) + '</td>' +
        '<td>' + (p.posRank == null ? DASH : p.posRank) + '</td>' +
        '<td>' + fmt1(p.ppg) + '</td>' +
        '<td>' + fmt1(p.games) + '</td>' +
        '<td><b>' + fmt0(p.total) + '</b></td>' +
        '<td class="l">' + range + '</td>' +
        '<td class="s27-dim">' + fmt1(p.prev) + '</td>' +
        '<td class="s27-dim">' + fmt1(p.age) + '</td>' +
        '<td>' + bench + '</td>' +
        '</tr>';
    }).join('');
    $('tbody').innerHTML = html || '<tr><td class="l s27-dim" colspan="' + COLS.length + '">No players match.</td></tr>';
    $('count').textContent = rows.length + ' of ' + state.rows.length + ' players';
  }

  function tabs(el, items, cur, onPick) {
    el.innerHTML = items.map(function (it) { return '<button type="button" data-v="' + it[0] + '" class="' + (it[0] === cur ? 'on' : '') + '">' + esc(it[1]) + '</button>'; }).join('');
    el.onclick = function (e) { var b = e.target.closest('button'); if (!b) return; onPick(b.getAttribute('data-v')); };
  }
  function drawControls() {
    tabs($('posTabs'), [['ALL', 'Overall'], ['QB', 'QB'], ['RB', 'RB'], ['WR', 'WR'], ['TE', 'TE']], state.pos, function (v) { state.pos = v; drawControls(); render(); });
    var hasSf = state.rows.some(function (p) { return p.sfRank != null; });
    $('fmtTabs').hidden = !hasSf;
    if (hasSf) tabs($('fmtTabs'), [['1QB', '1QB'], ['SF', 'Superflex']], state.fmt, function (v) { state.fmt = v; state.sort = null; state.dir = 1; drawControls(); render(); });
    $('rookWrap').hidden = !state.rows.some(function (p) { return p.rookie; });
  }

  function showData(rows, meta, isPreview) {
    if (!root) return;
    state.rows = rows;
    $('previewPill').hidden = !isPreview;
    $('empty').hidden = true;
    $('dataArea').hidden = false;
    var rook = rows.filter(function (p) { return p.rookie; }).length;
    $('stageNote').innerHTML = '<b>Preliminary.</b> Half-PPR, 12-team. Built from the in-house Sim Lab model with no ADP input. ' +
      (rook ? rook + ' rookies are placeholders with no draft pick or team yet. ' : 'No 2027 rookies are in this file yet. ') +
      'It can\'t know free agency, coaching changes, the draft or 2027 depth charts until they happen.';
    var bits = [rows.length + ' players'];
    if (meta && meta.fileName) bits.push('file: ' + meta.fileName);
    if (meta && meta.savedAt) bits.push('saved ' + new Date(meta.savedAt).toLocaleString());
    if (meta && meta.fileDate) bits.push('file dated ' + new Date(meta.fileDate).toLocaleString());
    $('metaLine').textContent = bits.join(' · ');
    drawControls(); render();
  }
  function showEmpty(title, body) {
    if (!root) return;
    $('dataArea').hidden = true; $('empty').hidden = false;
    $('emptyTitle').textContent = title; $('emptyBody').textContent = body;
  }
  function setMsg(text, kind) { var m = $('updMsg'); if (!m) return; m.textContent = text || ''; m.className = 's27-msg' + (kind ? ' ' + kind : ''); }
  var NO_SAVED = ['No rankings saved yet.', 'Use "Update the rankings" below to load the latest Sim Lab file.'];

  // ---------- data ----------
  function loadSaved() {
    var my = mountId;
    if (!db) return;
    db.collection(COLL).doc(DOC).get().then(function (snap) {
      if (my !== mountId || !root) return;
      if (!snap.exists) { state.saved = null; showEmpty(NO_SAVED[0], NO_SAVED[1]); return; }
      var d = snap.data();
      state.saved = d;
      if (state.pending) return; // a file preview is on screen; don't replace it
      try { showData(toRows(d.csv || ''), d, false); }
      catch (e) { showEmpty('The saved file couldn\'t be read.', e.message); }
    }).catch(function (e) {
      if (my !== mountId || !root || state.pending) return;
      if (e && e.code === 'permission-denied') {
        showEmpty('The private database isn\'t open to this account.',
          'Only the admin account can load these rankings. If you are signed in as the admin, the admin_sims database rule may not be deployed yet. You can still preview a file below.');
      } else {
        showEmpty('Couldn\'t load the rankings.', (e && e.message) || 'Unknown error. Check your connection and try again.');
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
        $('btnSave').disabled = !db || !isAdminUser(currentUser());
        $('btnDiscard').hidden = false;
        setMsg('Previewing ' + rows.length + ' players from ' + f.name + '. Nothing is saved until you press Save.');
      } catch (e) {
        state.pending = null; $('btnSave').disabled = true;
        setMsg(e.message, 'err');
      }
    };
    rd.onerror = function () { setMsg('Couldn\'t read that file.', 'err'); };
    rd.readAsText(f);
  }
  function onDiscard() {
    state.pending = null; $('file').value = ''; $('btnSave').disabled = true; $('btnDiscard').hidden = true; setMsg('');
    $('previewPill').hidden = true;
    if (state.saved) { try { showData(toRows(state.saved.csv || ''), state.saved, false); } catch (e) { showEmpty('The saved file couldn\'t be read.', e.message); } }
    else showEmpty(NO_SAVED[0], NO_SAVED[1]);
  }
  function onSave() {
    var p = state.pending, btn = $('btnSave'), u = currentUser(), my = mountId;
    if (!p || !db || !isAdminUser(u)) return;
    btn.disabled = true; setMsg('Saving…');
    var doc = { csv: p.csv, fileName: p.fileName, fileDate: p.fileDate, rowCount: p.rowCount, savedAt: new Date().toISOString(), savedBy: u.email };
    db.collection(COLL).doc(DOC).set(doc).then(function () {
      if (my !== mountId || !root) return;
      state.saved = doc; state.pending = null; $('file').value = ''; $('btnDiscard').hidden = true;
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
  function onSortClick(e) {
    var th = e.target.closest('th'); if (!th || th.getAttribute('data-nosort')) return;
    var k = th.getAttribute('data-k');
    var asc = (k === 'rk' || k === 'posRank' || k === 'name' || k === 'pos' || k === 'team' || k === 'age');
    if ((state.sort || 'rk') === k) state.dir = -state.dir; else { state.sort = k; state.dir = asc ? 1 : -1; }
    if (k === 'rk' && state.dir === 1) state.sort = null;
    render();
  }

  function mount(container) {
    if (!container) return;
    unmount();
    if (!document.getElementById('s27Style')) {
      var st = document.createElement('style'); st.id = 's27Style'; st.textContent = CSS; document.head.appendChild(st);
    }
    mountId++;
    state = fresh();
    container.innerHTML = HTML;
    root = container.querySelector('.s27');
    $('file').addEventListener('change', onFile);
    $('btnDiscard').addEventListener('click', onDiscard);
    $('btnSave').addEventListener('click', onSave);
    $('q').addEventListener('input', function () { state.q = this.value; render(); });
    $('rookOnly').addEventListener('change', function () { state.rookOnly = this.checked; render(); });
    $('thead').addEventListener('click', onSortClick);

    var admin = isAdminUser(currentUser());
    if (!admin && !LOCAL) { showEmpty('This view isn\'t available for this account.', 'Sign in with the admin Google account on the site, then open the tab again.'); return; }
    if (!admin) { showEmpty('Local preview, not signed in as admin.', 'Choose a file below to preview it. Nothing is read from or saved to the database.'); return; }
    showEmpty('Loading the saved rankings…', '');
    var my = mountId;
    var go = function () {
      if (my !== mountId || !root) return;
      try { db = firebase.firestore(); } catch (e) { db = null; }
      if (!db) { showEmpty('The database isn\'t available right now.', 'Reload the site and open the tab again. You can still preview a file below.'); return; }
      loadSaved();
    };
    if (typeof window._whenFirebaseReady === 'function') window._whenFirebaseReady(go); else go();
  }
  function unmount() {
    mountId++;
    if (root && root.parentNode) root.parentNode.innerHTML = '';
    root = null; state = fresh();
  }

  window.MFFSim2027 = { mount: mount, unmount: unmount };
})();
