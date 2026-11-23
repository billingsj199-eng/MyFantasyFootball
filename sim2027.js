/* 2027 SIM RANKINGS — admin-only data + info bar (2026-11-21; on the real rankings table 2026-11-23).
 *
 * Loaded on demand by the "2027 SIMS" tab in the rankings Format row (_sim2027Open in app.js),
 * which only un-hides for admins. The board itself is the normal rankings table: app.js runs it as
 * the read-only computed version `sim27` (see "2027 SIMS" in app.js). This file only
 *   - reads the private file from Firestore (admin_sims/rankings_2027, field `csv`),
 *   - parses it into rows and hands them to app.js (opts.onRows),
 *   - draws the slim bar above the table: "2027 · Preliminary", the info / scoring notes,
 *     1QB / SUPERFLEX, UPDATE FILE -> preview -> SAVE / DISCARD, and the empty / locked / loading
 *     messages (the table is hidden while there is nothing to show).
 * This file is public like the rest of the static site, but it contains NO ranking data. The
 * numbers live in Firestore, and firestore.rules lets only Jack's verified Google account read or
 * write that collection (isJack()). Anyone else gets "permission denied" whatever they do in the
 * browser. Never commit the rankings CSV/JSON to this repo: it would be public.
 *
 * Updating: on the tab, UPDATE FILE -> choose the CSV the Sim Lab refresh wrote
 * (sim_lab\preseason2027\output\2027_inhouse_early.csv), check the preview board, then SAVE.
 *
 * CSV columns read: name, pos, team, age, games, ppg26, p_bench, sf12_rank, provisional / rookie,
 * rec_pg; half-PPR ppg, total, tot_p10, tot_p90, rank, pos_rank; and when present the same six with
 * _ppr / _std suffixes (per-scoring numbers + order). Unknown columns are ignored.
 *
 * API: window.MFFSim2027.mount(containerEl, {sf, onRows(rows|null, {perFmt}), onFmt(sf)})
 *      .unmount() / .setNote(infoText, scoringText)
 */
(function () {
  'use strict';
  var ADMIN_EMAILS = ['billingsj199@gmail.com']; // shown-or-hidden only; the real lock is firestore.rules
  var COLL = 'admin_sims', DOC = 'rankings_2027';
  var MAX_CSV_BYTES = 900000; // a Firestore document tops out near 1 MB
  // Local testing only: lets the file preview run without an admin sign-in. Nothing is read from the database.
  var LOCAL = location.protocol === 'file:' || /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);

  var CSS = [
    '.s27-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 2rem 10px;font-family:"DM Sans",sans-serif}',
    '.s27-bar *{box-sizing:border-box}',
    '.s27-tag{font-size:.6875rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:2px 8px;border-radius:4px;white-space:nowrap}',
    '.s27-tag.pre{color:var(--accent);background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.35)}',
    '.s27-tag.prev{color:var(--red);background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.4)}',
    '.s27-tag.sc{color:var(--text2);background:var(--elev-2);border:1px solid var(--border-strong);text-transform:none;letter-spacing:0;font-weight:600}',
    '.s27-tag.sc:empty{display:none}',
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
    '.s27-empty{width:100%;padding:2.5rem 1rem;text-align:center;color:var(--text2);font-size:.85rem;line-height:1.5}',
    '.s27-empty b{display:block;color:var(--text);font-size:.95rem;margin-bottom:4px}',
    '.s27-bar [hidden]{display:none!important}',
    /* While the 2027 board is on (body.sim2027-on, set by _sim2027Open in app.js): the columns with
       no 2027 meaning (Cons, SOS, P-SOS, +/-) and the STATS views other than FANTASY are hidden,
       and so is TABLE / TIER CARDS (tier cards read this season's stats). */
    'body.sim2027-on #pageRankings #adminViewToggle,' +
    'body.sim2027-on #pageRankings .rnk-statmode-btn:not([data-rnkstatmode="fantasy"]),' +
    'body.sim2027-on #pageRankings #adpHeader,body.sim2027-on #pageRankings td.cons-cell,' +
    'body.sim2027-on #pageRankings #psosHeader,body.sim2027-on #pageRankings td.psos-cell,' +
    'body.sim2027-on #pageRankings #ppsosHeader,body.sim2027-on #pageRankings td.ppsos-cell,' +
    'body.sim2027-on #pageRankings thead th[data-sort="diff"],body.sim2027-on #pageRankings td.diff-cell{display:none!important}',
    /* Nothing loaded yet (no saved file / locked / loading): the bar's message instead of the table. */
    'body.sim2027-on.s27-nodata #pageRankings .table-wrap,body.sim2027-on.s27-nodata #pageRankings #empty{display:none!important}',
    '@media (max-width:600px){.s27-bar{padding:8px 10px 10px}.s27-info{width:100%}}'
  ].join('\n');

  var HTML =
    '<div class="s27-bar">' +
      '<span class="s27-tag pre" title="Preliminary board from the in-house Sim Lab preseason model. Can\'t know free agency, coaching changes, the draft or 2027 depth charts until they happen.">2027 · Preliminary</span>' +
      '<span class="s27-tag prev" data-s="previewTag" hidden>Preview, not saved</span>' +
      '<span class="s27-tag sc" data-s="scoring"></span>' +
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
      '<div class="s27-empty" data-s="empty" hidden><b data-s="emptyTitle"></b><span data-s="emptyBody"></span></div>' +
    '</div>';

  var root = null, db = null, mountId = 0, opts = {};
  var state = null;
  function fresh() { return { rows: [], saved: null, pending: null, sf: false, meta: null, note: '' }; }
  function $(k) { return root ? root.querySelector('[data-s="' + k + '"]') : null; }

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
  // One scoring's six numbers ('' = the half-PPR base columns, '_ppr' / '_std').
  function fmtCols(o, sfx) {
    return { ppg: num(o['ppg' + sfx]), total: num(o['total' + sfx]), p10: num(o['tot_p10' + sfx]), p90: num(o['tot_p90' + sfx]),
      rank: num(o['rank' + sfx]), posRank: num(o['pos_rank' + sfx]) };
  }
  // Fill any missing ranks of one scoring from its season total so every order is complete.
  function fillRanks(out, k) {
    var have = out.filter(function (p) { return p.fmt[k]; });
    have.slice().sort(function (a, b) { return (b.fmt[k].total || 0) - (a.fmt[k].total || 0); })
      .forEach(function (p, i) { if (p.fmt[k].rank == null) p.fmt[k].rank = i + 1; });
    ['QB', 'RB', 'WR', 'TE'].forEach(function (pos) {
      have.filter(function (p) { return p.pos === pos; })
        .sort(function (a, b) { return a.fmt[k].rank - b.fmt[k].rank; })
        .forEach(function (p, i) { if (p.fmt[k].posRank == null) p.fmt[k].posRank = i + 1; });
    });
  }

  // Turns the Sim Lab CSV into rows: { name, pos, team, age, games, prev (ppg26), bench, sfRank,
  // rookie, recPg, fmt: { half, ppr|null, std|null } }. perFmt = the file has PPR and STD columns.
  function toRows(csvText) {
    var t = parseCsv(csvText);
    if (t.length < 2) throw new Error('The file has no rows.');
    var head = t[0].map(function (h) { return h.trim(); });
    ['name', 'pos', 'total'].forEach(function (k) {
      if (head.indexOf(k) === -1) throw new Error('This doesn\'t look like the Sim Lab rankings file (no "' + k + '" column).');
    });
    var has = function (k) { return head.indexOf(k) !== -1; };
    var perFmt = has('ppg_ppr') && has('total_ppr') && has('ppg_std') && has('total_std');
    var out = [];
    for (var r = 1; r < t.length; r++) {
      var o = {};
      for (var c = 0; c < head.length; c++) o[head[c]] = t[r][c];
      var name = String(o.name || '').trim();
      if (!name) continue;
      var prov = truthy(o.provisional) || truthy(o.rookie) || /provisional/i.test(name) || /provisional/i.test(o.status || '');
      var fmt = { half: fmtCols(o, ''), ppr: null, std: null };
      if (perFmt) {
        var pp = fmtCols(o, '_ppr'), ps = fmtCols(o, '_std');
        if (pp.total != null || pp.ppg != null) fmt.ppr = pp;
        if (ps.total != null || ps.ppg != null) fmt.std = ps;
      }
      out.push({
        name: name.replace(/\s*[\[(]?\s*provisional\s*[\])]?\s*/i, ' ').trim(),
        pos: String(o.pos || '').trim().toUpperCase(),
        team: String(o.team || '').trim(),
        games: num(o.games), prev: num(o.ppg26), age: num(o.age),
        bench: num(o.p_bench), sfRank: num(o.sf12_rank), recPg: num(o.rec_pg),
        rookie: prov, fmt: fmt
      });
    }
    if (!out.length) throw new Error('No players found in the file.');
    ['half', 'ppr', 'std'].forEach(function (k) { fillRanks(out, k); });
    return { rows: out, perFmt: perFmt };
  }

  // ---------- bar ----------
  function drawFmt() {
    var hasSf = state.rows.some(function (p) { return p.sfRank != null; });
    var wrap = $('fmt');
    wrap.hidden = !hasSf;
    Array.prototype.forEach.call(wrap.querySelectorAll('button'), function (b) {
      b.classList.toggle('active', b.getAttribute('data-fmt') === (state.sf ? 'SF' : '1QB'));
    });
  }
  function drawInfo() {
    if (!root) return;
    var bits = [];
    if (state.rows.length && state.note) bits.push(state.note);
    var meta = state.meta;
    if (state.rows.length && meta && meta.savedAt) bits.push('saved ' + new Date(meta.savedAt).toLocaleDateString());
    else if (state.rows.length && meta && meta.fileName) bits.push(meta.fileName);
    $('info').textContent = bits.join(' · ');
    $('info').title = (meta && meta.fileName ? 'File: ' + meta.fileName + '.' : '') +
      (meta && meta.fileDate ? ' File dated ' + new Date(meta.fileDate).toLocaleString() + '.' : '');
  }
  function showData(parsed, meta, isPreview) {
    if (!root) return;
    state.rows = parsed.rows; state.meta = meta;
    $('previewTag').hidden = !isPreview;
    $('empty').hidden = true;
    drawFmt(); drawInfo();
    if (opts.onRows) opts.onRows(parsed.rows, { perFmt: parsed.perFmt, preview: !!isPreview });
  }
  function showEmpty(title, body) {
    if (!root) return;
    state.rows = [];
    $('empty').hidden = false;
    $('emptyTitle').textContent = title; $('emptyBody').textContent = body;
    $('fmt').hidden = true;
    $('scoring').textContent = '';
    drawInfo();
    if (opts.onRows) opts.onRows(null, {});
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
        var parsed = toRows(text);
        var bytes = new Blob([text]).size;
        if (bytes > MAX_CSV_BYTES) throw new Error('The file is too large to save (' + Math.round(bytes / 1024) + ' KB; the limit is ' + Math.round(MAX_CSV_BYTES / 1024) + ' KB).');
        state.pending = { csv: text, fileName: f.name, fileDate: f.lastModified || null, rowCount: parsed.rows.length };
        setPreviewButtons(true);
        var canSave = !!db && isAdminUser(currentUser());
        $('btnSave').disabled = !canSave;
        setMsg('Previewing ' + parsed.rows.length + ' rows from ' + f.name + '. ' + (canSave ? 'Nothing is saved until you press SAVE.' : 'Saving needs the admin sign-in and the database.'));
        showData(parsed, state.pending, true);
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
    else showEmpty(NO_SAVED[0], LOCAL && !isAdminUser(currentUser()) ? 'Local preview: press UPDATE FILE to preview a file.' : NO_SAVED[1]);
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
      setMsg('Saved ' + doc.rowCount + ' rows to the private database.', 'ok');
    }).catch(function (e) {
      if (my !== mountId || !root) return;
      btn.disabled = false;
      setMsg(e && e.code === 'permission-denied'
        ? 'Not saved: the admin_sims database rule isn\'t deployed yet, or this account isn\'t the admin.'
        : 'Not saved: ' + ((e && e.message) || 'unknown error'), 'err');
    });
  }

  function mount(container, o) {
    if (!container) return;
    unmount();
    if (!document.getElementById('s27Style')) {
      var st = document.createElement('style'); st.id = 's27Style'; st.textContent = CSS; document.head.appendChild(st);
    }
    mountId++;
    state = fresh();
    opts = o || {};
    state.sf = !!opts.sf;
    container.innerHTML = HTML;
    root = container.querySelector('.s27-bar');
    $('file').addEventListener('change', onFile);
    $('btnFile').addEventListener('click', function () { $('file').click(); });
    $('btnDiscard').addEventListener('click', onDiscard);
    $('btnSave').addEventListener('click', onSave);
    $('fmt').addEventListener('click', function (e) {
      var b = e.target.closest('button[data-fmt]'); if (!b) return;
      state.sf = b.getAttribute('data-fmt') === 'SF';
      drawFmt();
      if (opts.onFmt) opts.onFmt(state.sf);
    });

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
    root = null; state = fresh(); opts = {};
  }
  // app.js: the matched-player / placeholder line and the scoring note.
  function setNote(info, scoring) {
    if (!root || !state) return;
    state.note = info || '';
    $('scoring').textContent = state.rows.length ? (scoring || '') : '';
    drawInfo();
  }

  window.MFFSim2027 = { mount: mount, unmount: unmount, setNote: setNote };
})();
