/* MFF ACCURACY TRACKER — admin-only page (/accuracy/).
   Data: accuracy/data/season_2026.json + w{N}.json (built by scripts/build_accuracy.py).
   Jack's WEEKLY boards are read live from Firestore rankings_history (admin-read):
   for each game, the newest board saved before that game's kickoff whose _week
   matches. Everything is graded on FULL PPR, QB/RB/WR/TE only. */
(function () {
  'use strict';
  const SEASON = 2026;
  const ADMIN_EMAILS = ['billingsj199@gmail.com'];
  const POS = ['QB', 'RB', 'WR', 'TE'];
  const POOL_N = { QB: 24, RB: 48, WR: 60, TE: 24 };   // pool = union of each source's top-N at the position
  const HIT_K = { QB: 12, RB: 24, WR: 24, TE: 12 };   // "hit" = source top-K that finished top-K
  const MIN_PROJ = 5;                                  // weekly pool floor (site consensus or MFF sim PPR)
  const SRC_PRE = [
    { k: 'jack', l: "Jack's original board" }, { k: 'sl', l: 'Sleeper' }, { k: 'fp', l: 'FantasyPros ECR' },
    { k: 'ud', l: 'Underdog ADP' }, { k: 'espn', l: 'ESPN' }, { k: 'cbs', l: 'CBS' }, { k: 'yahoo', l: 'Yahoo' }];
  const SRC_PJ = [
    { k: 'sim', l: 'MFF sim' }, { k: 'clay', l: 'Mike Clay' }, { k: 'sl', l: 'Sleeper' }, { k: 'espn', l: 'ESPN' }, { k: 'cbs', l: 'CBS' }];
  const SRC_WK = [
    { k: 'jack', l: 'Jack weekly', type: 'rank' }, { k: 'fpecr', l: 'FP expert ranks', type: 'rank' },
    { k: 'sim', l: 'MFF sim', type: 'proj' }, { k: 'cons', l: 'Site consensus', type: 'proj' },
    { k: 'sl', l: 'Sleeper', type: 'proj' }, { k: 'espn', l: 'ESPN', type: 'proj' },
    { k: 'cbs', l: 'CBS', type: 'proj' }, { k: 'fp', l: 'FantasyPros', type: 'proj' }];
  const COLOR = { jack: '#3987e5', fpecr: '#d95926', sim: '#199e70', cons: '#c98500', sl: '#d55181', espn: '#2fa52f', cbs: '#9085e9', fp: '#e66767' };

  const $ = (s, el) => (el || document).querySelector(s);
  const isNum = (x) => typeof x === 'number' && isFinite(x);
  const avg = (a) => a.length ? a.reduce((s, x) => s + x, 0) / a.length : null;
  const f1 = (x) => isNum(x) ? x.toFixed(1) : '—';
  const f2 = (x) => isNum(x) ? x.toFixed(2) : '—';
  const pct = (x) => isNum(x) ? Math.round(x * 100) + '%' : '—';
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  const S = { season: null, weeks: {}, jack: {}, jackMeta: {}, tab: 'season', user: null,
    ctl: { pos: 'RB', basis: 'total', n: 0, wk: 0, wpos: 'ALL', metric: 'mae', tpos: 'ALL', q: '' } };

  // ------------------------------------------------------------------ auth
  async function boot() {
    const ok = await window._ACC_FB_READY;
    if (!ok) { $('#gateMsg').textContent = 'Firebase failed to load (blocked CDN?). Reload to retry.'; return; }
    const auth = firebase.auth();
    $('#btnSignIn').onclick = async () => {
      try { await auth.signInWithPopup(new firebase.auth.GoogleAuthProvider()); }
      catch (e) { $('#gateMsg').textContent = 'Sign-in failed: ' + (e && e.message); }
    };
    $('#btnSignOut').onclick = () => auth.signOut();
    auth.onAuthStateChanged((u) => {
      S.user = u;
      const admin = !!(u && ADMIN_EMAILS.includes((u.email || '').toLowerCase()));
      $('#who').textContent = u ? (u.email || '') : '';
      $('#btnSignIn').style.display = u ? 'none' : '';
      $('#btnSignOut').style.display = u ? '' : 'none';
      if (!admin) {
        $('#app').style.display = 'none'; $('#gate').style.display = '';
        $('#gateMsg').textContent = u ? 'This account is not an admin.' : 'Sign in with the admin Google account to view.';
        return;
      }
      $('#gate').style.display = 'none'; $('#app').style.display = '';
      if (!S.season) loadAll().catch((e) => { setStatus('Load failed: ' + (e && e.message)); console.error(e); });
    });
  }
  function setStatus(t) { $('#status').textContent = t; }

  // ------------------------------------------------------------------ data
  async function getJSON(path) {
    const r = await fetch(path + '?v=' + Date.now(), { cache: 'no-store' });
    if (!r.ok) throw new Error(path + ' ' + r.status);
    return r.json();
  }
  async function loadAll() {
    setStatus('Loading data…');
    S.season = await getJSON('data/season_' + SEASON + '.json');
    const played = S.season.weeks.filter((w) => w.played > 0);
    await Promise.all(played.map(async (w) => { S.weeks[w.week] = await getJSON('data/w' + w.week + '.json'); }));
    S.ctl.wk = played.length ? played[played.length - 1].week : 0;
    bindTabs();
    render();
    setStatus('Reading Jack\'s weekly boards…');
    for (const w of played) {
      try { await loadJackWeek(w.week); }
      catch (e) { console.warn('[acc] jack week', w.week, e); S.jackMeta[w.week] = { error: (e && (e.code || e.message)) || 'error' }; }
      render();
    }
    setStatus('Updated ' + new Date(S.season.updated).toLocaleString());
  }

  // Jack's weekly board per game: newest rankings_history save before the game's
  // kickoff whose jacks.weekly._week === week. Cached in localStorage once the
  // week is fully kicked off (boards can't change for games already played).
  const idOf = (iso) => new Date(iso).toISOString().replace(/[:.]/g, '-');
  async function loadJackWeek(week) {
    const wd = S.weeks[week];
    const meta = S.season.weeks.find((w) => w.week === week);
    const key = 'acc_jack_' + SEASON + '_w' + week;
    const lastKo = meta && meta.last ? new Date(meta.last).getTime() : 0;
    const complete = lastKo && Date.now() > lastKo + 6 * 3600e3;
    if (complete) {
      try { const c = JSON.parse(localStorage.getItem(key) || 'null'); if (c && c.ranks) { S.jack[week] = c.ranks; S.jackMeta[week] = c.meta; return; } } catch (e) { /* ignore */ }
    }
    const db = firebase.firestore();
    const first = meta && meta.first ? new Date(meta.first) : null;
    if (!first) { S.jackMeta[week] = { error: 'no kickoffs' }; return; }
    const start = idOf(new Date(first.getTime() - 7 * 86400e3));
    const end = idOf(new Date((lastKo || first.getTime()) + 3600e3));
    const snap = await db.collection('rankings_history')
      .orderBy(firebase.firestore.FieldPath.documentId()).startAt(start).endAt(end).get();
    const boards = [];
    snap.forEach((doc) => {
      try {
        const d = doc.data(); const obj = JSON.parse(d.data || '{}');
        const wk = obj.jacks && obj.jacks.weekly;
        if (wk && Array.isArray(wk._order)) boards.push({ id: doc.id, week: wk._week, order: wk._order, at: d.updatedAt });
      } catch (e) { /* skip bad doc */ }
    });
    boards.sort((a, b) => a.id < b.id ? -1 : 1);
    const ranks = {}; const used = new Set(); let nRanked = 0;
    const posOrderCache = {};
    function posRanks(b) {
      if (posOrderCache[b.id]) return posOrderCache[b.id];
      const m = {}; const cnt = { QB: 0, RB: 0, WR: 0, TE: 0 };
      b.order.forEach((n) => { const p = S.season.players[n]; if (p && cnt[p.pos] !== undefined) { cnt[p.pos]++; m[n] = cnt[p.pos]; } });
      return (posOrderCache[b.id] = m);
    }
    Object.entries(wd.players).forEach(([n, p]) => {
      if (!p.ko) return;
      const koId = idOf(p.ko);
      let b = null;
      for (const cand of boards) { if (cand.id < koId && cand.week === week) b = cand; }
      if (!b) return;
      used.add(b.id);
      const r = posRanks(b)[n];
      if (r) { ranks[n] = r; nRanked++; }
    });
    S.jack[week] = ranks;
    S.jackMeta[week] = { docs: boards.length, used: [...used].sort(), ranked: nRanked, at: new Date().toISOString() };
    if (complete) { try { localStorage.setItem(key, JSON.stringify({ ranks, meta: S.jackMeta[week] })); } catch (e) { /* quota */ } }
  }

  // ------------------------------------------------------------------ math
  function spearman(a, b) {
    const n = a.length; if (n < 3) return null;
    const ra = avgRanks(a), rb = avgRanks(b);
    const ma = avg(ra), mb = avg(rb);
    let num = 0, da = 0, db = 0;
    for (let i = 0; i < n; i++) { const x = ra[i] - ma, y = rb[i] - mb; num += x * y; da += x * x; db += y * y; }
    return (da && db) ? num / Math.sqrt(da * db) : null;
  }
  function avgRanks(v) {  // fractional ranks (ties averaged), 1 = smallest
    const idx = v.map((x, i) => i).sort((i, j) => v[i] - v[j]);
    const out = new Array(v.length); let i = 0;
    while (i < idx.length) { let j = i; while (j + 1 < idx.length && v[idx[j + 1]] === v[idx[i]]) j++; const r = (i + j) / 2 + 1; for (let k = i; k <= j; k++) out[idx[k]] = r; i = j + 1; }
    return out;
  }
  function pearson(a, b) {
    const n = a.length; if (n < 3) return null;
    const ma = avg(a), mb = avg(b); let num = 0, da = 0, db = 0;
    for (let i = 0; i < n; i++) { const x = a[i] - ma, y = b[i] - mb; num += x * y; da += x * x; db += y * y; }
    return (da && db) ? num / Math.sqrt(da * db) : null;
  }
  // rows: [{act, r:{src: rank|null}}] for ONE position pool. Returns per-source rank metrics.
  function rankMetrics(rows, srcs, K, jackKey) {
    const n = rows.length; if (!n) return {};
    const actOrder = rows.map((r, i) => i).sort((i, j) => rows[j].act - rows[i].act);
    const actRank = new Array(n); actOrder.forEach((i, k) => { actRank[i] = k + 1; });
    const srcRank = {};
    srcs.forEach((s) => {
      const has = rows.map((r, i) => i).filter((i) => isNum(rows[i].r[s]));
      has.sort((i, j) => rows[i].r[s] - rows[j].r[s]);
      const rk = new Array(n).fill(has.length + 1);
      has.forEach((i, k) => { rk[i] = k + 1; });
      srcRank[s] = { rk, has: has.length };
    });
    const out = {};
    srcs.forEach((s) => {
      const { rk, has } = srcRank[s]; if (!has) { out[s] = null; return; }
      const kk = Math.min(K, n);
      let hits = 0, abs = 0;
      for (let i = 0; i < n; i++) { abs += Math.abs(rk[i] - actRank[i]); if (rk[i] <= kk && actRank[i] <= kk) hits++; }
      let w = 0, l = 0, t = 0;
      if (jackKey && s !== jackKey && srcRank[jackKey] && srcRank[jackKey].has) {
        const jr = srcRank[jackKey].rk;
        for (let i = 0; i < n; i++) {
          if (!isNum(rows[i].r[s]) || !isNum(rows[i].r[jackKey])) continue;
          const es = Math.abs(rk[i] - actRank[i]), ej = Math.abs(jr[i] - actRank[i]);
          if (es < ej) w++; else if (es > ej) l++; else t++;
        }
      }
      out[s] = { n, has, rho: spearman(rk, actRank), mae: abs / n, hits, K: kk, hitPct: hits / kk, h2h: [w, l, t], rk, actRank };
    });
    return out;
  }
  function projMetrics(pairs) {  // [[proj, act], ...]
    const n = pairs.length; if (n < 3) return null;
    let abs = 0, bias = 0, sq = 0;
    pairs.forEach(([p, a]) => { const e = p - a; abs += Math.abs(e); bias += e; sq += e * e; });
    return { n, mae: abs / n, bias: bias / n, rmse: Math.sqrt(sq / n), r: pearson(pairs.map((x) => x[0]), pairs.map((x) => x[1])) };
  }

  // ------------------------------------------------------------------ season model
  function seasonPool(pos, basis, N) {
    const P = S.season.players;
    const names = Object.keys(P).filter((n) => P[n].pos === pos);
    // position rank per source over everyone at the position who has that source's value
    const posRank = {};
    SRC_PRE.forEach(({ k }) => {
      const has = names.filter((n) => P[n].pre && isNum(P[n].pre[k]));
      has.sort((a, b) => P[a].pre[k] - P[b].pre[k]);
      posRank[k] = {}; has.forEach((n, i) => { posRank[k][n] = i + 1; });
    });
    const gamesPlayed = Math.max(...S.season.weeks.filter((w) => w.played > 0).map((w) => w.week), 0);
    const minG = basis === 'ppg' ? Math.max(1, Math.ceil(gamesPlayed / 2)) : 0;
    const rows = [];
    names.forEach((n) => {
      const inPool = SRC_PRE.some(({ k }) => posRank[k][n] && posRank[k][n] <= N);
      if (!inPool) return;
      const wk = (P[n].act && P[n].act.wk) || {};
      const pts = Object.values(wk); const g = pts.length; const tot = pts.reduce((s, x) => s + x, 0);
      if (basis === 'ppg' && g < minG) return;
      const r = {}; SRC_PRE.forEach(({ k }) => { r[k] = posRank[k][n] || null; });
      rows.push({ n, tm: P[n].tm, act: basis === 'ppg' ? (g ? tot / g : 0) : tot, tot, g, r, pj: P[n].pj || {} });
    });
    return { rows, minG, gamesPlayed };
  }
  function renderSeason() {
    const c = S.ctl; const N = c.n || POOL_N[c.pos];
    const { rows, minG, gamesPlayed } = seasonPool(c.pos, c.basis, N);
    const srcs = SRC_PRE.map((s) => s.k);
    const m = rankMetrics(rows, srcs, HIT_K[c.pos], 'jack');
    const html = [];
    html.push('<div class="controls">'
      + '<label>Position ' + sel('s-pos', POS, c.pos) + '</label>'
      + '<label>Actual = ' + sel('s-basis', [['total', 'Season total'], ['ppg', 'Points per game']], c.basis) + '</label>'
      + '<label>Pool: top ' + sel('s-n', [[0, 'default (' + POOL_N[c.pos] + ')'], 12, 24, 36, 48, 60, 80], c.n) + ' by any source</label>'
      + '<span class="muted">' + rows.length + ' players · through week ' + gamesPlayed + (c.basis === 'ppg' ? ' · min ' + minG + ' game' + (minG > 1 ? 's' : '') : '') + '</span>'
      + '</div>');
    // leaderboard
    const lb = srcs.filter((s) => m[s]).map((s) => ({ s, ...m[s] })).sort((a, b) => (b.rho || -9) - (a.rho || -9));
    html.push('<div class="card"><h2>Preseason ranks vs results — ' + esc(c.pos) + '</h2><div class="tablewrap"><table><thead><tr>'
      + '<th class="l">Source</th><th>Ranked in pool</th><th>Rank corr (ρ)</th><th>Avg rank miss</th><th>Top-' + HIT_K[c.pos] + ' hits</th><th>vs Jack (W-L-T)</th></tr></thead><tbody>');
    lb.forEach((x) => {
      const lab = SRC_PRE.find((z) => z.k === x.s).l;
      html.push('<tr' + (x.s === 'jack' ? ' class="me"' : '') + '><td class="l">' + esc(lab) + '</td><td>' + x.has + '/' + x.n + '</td><td>' + f2(x.rho) + '</td><td>' + f1(x.mae) + '</td><td>' + x.hits + '/' + x.K + ' <span class="muted">(' + pct(x.hitPct) + ')</span></td><td>' + (x.s === 'jack' ? '—' : x.h2h.join('-')) + '</td></tr>');
    });
    html.push('</tbody></table></div><p class="note">Pool = every player any source ranked top-' + N + ' at ' + esc(c.pos) + ' on ' + esc(S.season.preseason.consDay) + ' (the day of the Week 1 opener). Within the pool each source is re-ranked 1..n; players a source left unranked share the bottom rank. ρ = Spearman rank correlation with the actual finish. Avg rank miss = mean |source rank − actual rank|. Hits = of the source\'s top-' + HIT_K[c.pos] + ', how many actually finished top-' + HIT_K[c.pos] + '. vs Jack = players where the source\'s rank miss was smaller / larger / equal. Players with no games count as 0 points on the season-total basis.</p></div>');

    // season projections
    const pj = {};
    SRC_PJ.forEach(({ k }) => { pj[k] = projMetrics(rows.filter((r) => r.g > 0 && isNum(r.pj[k])).map((r) => [r.pj[k], r.tot / r.g])); });
    html.push('<div class="card"><h2>Preseason season projections (PPG, full PPR) vs actual PPG — ' + esc(c.pos) + '</h2><div class="tablewrap"><table><thead><tr>'
      + '<th class="l">Source</th><th>n</th><th>MAE</th><th>Bias</th><th>RMSE</th><th>r</th></tr></thead><tbody>');
    SRC_PJ.map((s) => ({ s: s.k, l: s.l, m: pj[s.k] })).filter((x) => x.m).sort((a, b) => a.m.mae - b.m.mae).forEach((x) => {
      html.push('<tr' + (x.s === 'sim' ? ' class="me"' : '') + '><td class="l">' + esc(x.l) + '</td><td>' + x.m.n + '</td><td>' + f2(x.m.mae) + '</td><td>' + (x.m.bias >= 0 ? '+' : '') + f2(x.m.bias) + '</td><td>' + f2(x.m.rmse) + '</td><td>' + f2(x.m.r) + '</td></tr>');
    });
    html.push('</tbody></table></div><p class="note">Season totals ÷ 17 (Clay ÷ his projected games; MFF sim = season PPG) frozen at commit ' + esc(S.season.preseason.commit) + ', compared with each pooled player\'s actual PPG so far. Early-season PPG is noisy; this table firms up as games accumulate.</p></div>');

    // player table
    const sk = S.sort.season || { k: 'act', d: -1 };
    const cols = [{ k: 'n', l: 'Player', left: true }, { k: 'tm', l: 'Tm', left: true }, { k: 'act', l: c.basis === 'ppg' ? 'PPG' : 'Pts' }, { k: 'g', l: 'G' }, { k: 'actRank', l: 'Fin' }]
      .concat(SRC_PRE.map((s) => ({ k: 'r_' + s.k, l: s.l.replace("Jack's original board", 'Jack').replace('FantasyPros ECR', 'FP').replace('Underdog ADP', 'UD') })));
    const trs = rows.map((r, i) => {
      const o = { n: r.n, tm: r.tm || '', act: r.act, g: r.g, actRank: m.jack ? m.jack.actRank[i] : (m[srcs.find((s) => m[s])] || {}).actRank[i] };
      srcs.forEach((s) => { o['r_' + s] = m[s] ? (isNum(r.r[s]) ? m[s].rk[i] : null) : null; });
      return o;
    });
    trs.sort((a, b) => cmp(a[sk.k], b[sk.k]) * sk.d);
    html.push('<div class="card"><h2>Players — ' + esc(c.pos) + ' pool</h2><div class="tablewrap"><table id="t-season"><thead><tr>');
    cols.forEach((col) => html.push('<th data-k="' + col.k + '" class="' + (col.left ? 'l ' : '') + (sk.k === col.k ? 'sorted' : '') + '">' + esc(col.l) + '</th>'));
    html.push('</tr></thead><tbody>');
    trs.forEach((o) => {
      html.push('<tr><td class="l"><a href="#" data-player="' + esc(o.n) + '">' + esc(o.n) + '</a></td><td class="l dim">' + esc(o.tm) + '</td><td>' + f1(o.act) + '</td><td>' + o.g + '</td><td>' + o.actRank + '</td>');
      srcs.forEach((s) => {
        const v = o['r_' + s];
        if (!isNum(v)) { html.push('<td class="dim">—</td>'); return; }
        const e = v - o.actRank; const cls = Math.abs(e) >= Math.max(6, HIT_K[c.pos] / 2) ? (e < 0 ? 'err-hi' : 'err-lo') : '';
        html.push('<td class="' + cls + '" title="' + (e > 0 ? 'ranked ' + e + ' spots too low' : e < 0 ? 'ranked ' + (-e) + ' spots too high' : 'exact') + '">' + v + '</td>');
      });
      html.push('</tr>');
    });
    html.push('</tbody></table></div><p class="note">Red = the source ranked him well ABOVE where he finished (too optimistic); blue = well below (too pessimistic). Click a header to sort, a name for his weekly detail.</p></div>');
    $('#tab-season').innerHTML = html.join('');
    $('#s-pos').onchange = (e) => { c.pos = e.target.value; render(); };
    $('#s-basis').onchange = (e) => { c.basis = e.target.value; render(); };
    $('#s-n').onchange = (e) => { c.n = +e.target.value; render(); };
    bindSort('#t-season', 'season');
  }

  // ------------------------------------------------------------------ weekly model
  function wkVals(p) {
    const s = p.site || [], sim = p.sim;
    const rec = sim ? (sim[4] || 0) : 0;
    const v = { sl: s[0], espn: s[1], cbs: s[2], fp: s[3], fpecr: s[4] };
    v.sim = sim && isNum(sim[0]) ? sim[0] + 0.5 * rec : null;
    const legs = [v.sl, v.espn, v.cbs, v.fp].filter(isNum); v.cons = legs.length ? avg(legs) : null;
    return v;
  }
  // rows for one (week, pos): played players inside the pool
  function weekRows(week, pos) {
    const wd = S.weeks[week]; if (!wd) return [];
    const jack = S.jack[week] || {};
    const N = POOL_N[pos];
    const rows = [];
    Object.entries(wd.players).forEach(([n, p]) => {
      if (p.pos !== pos || !isNum(p.act)) return;
      const v = wkVals(p); const jr = jack[n] || null;
      const inPool = (isNum(v.cons) && v.cons >= MIN_PROJ) || (isNum(v.sim) && v.sim >= MIN_PROJ) || (jr && jr <= N) || (isNum(v.fpecr) && v.fpecr <= N);
      if (!inPool) return;
      const r = { jack: jr, fpecr: isNum(v.fpecr) ? v.fpecr : null };
      SRC_WK.filter((s) => s.type === 'proj').forEach((s) => { r[s.k] = isNum(v[s.k]) ? -v[s.k] : null; }); // rank by projection desc
      rows.push({ n, tm: p.tm, opp: p.opp, act: p.act, v, r });
    });
    return rows;
  }
  function weekMetrics(weeks, poses) {
    const acc = {};
    SRC_WK.forEach((s) => { acc[s.k] = { rhoSum: 0, rhoN: 0, absSum: 0, n: 0, hits: 0, K: 0, h2h: [0, 0, 0], pairs: [] }; });
    weeks.forEach((w) => poses.forEach((pos) => {
      const rows = weekRows(w, pos); if (!rows.length) return;
      const m = rankMetrics(rows, SRC_WK.map((s) => s.k), HIT_K[pos], 'jack');
      SRC_WK.forEach((s) => {
        const x = m[s.k]; if (!x) return; const a = acc[s.k];
        if (isNum(x.rho)) { a.rhoSum += x.rho * x.n; a.rhoN += x.n; }
        a.absSum += x.mae * x.n; a.n += x.n; a.hits += x.hits; a.K += x.K;
        a.h2h[0] += x.h2h[0]; a.h2h[1] += x.h2h[1]; a.h2h[2] += x.h2h[2];
        if (s.type === 'proj') rows.forEach((r) => { if (isNum(r.v[s.k])) a.pairs.push([r.v[s.k], r.act]); });
      });
    }));
    const out = {};
    SRC_WK.forEach((s) => {
      const a = acc[s.k]; if (!a.n) { out[s.k] = null; return; }
      out[s.k] = { n: a.n, rho: a.rhoN ? a.rhoSum / a.rhoN : null, mae: a.absSum / a.n, hits: a.hits, K: a.K, hitPct: a.K ? a.hits / a.K : null, h2h: a.h2h, pm: projMetrics(a.pairs) };
    });
    return out;
  }
  function renderWeekly() {
    const c = S.ctl;
    const played = S.season.weeks.filter((w) => w.played > 0).map((w) => w.week);
    if (!played.length) { $('#tab-weekly').innerHTML = '<div class="card">No completed weeks yet.</div>'; return; }
    const weeks = c.wk === 0 ? played : [c.wk];
    const poses = c.wpos === 'ALL' ? POS : [c.wpos];
    const m = weekMetrics(weeks, poses);
    const html = [];
    html.push('<div class="controls">'
      + '<label>Week ' + sel('w-wk', [[0, 'All weeks']].concat(played.map((w) => [w, 'Week ' + w])), c.wk) + '</label>'
      + '<label>Position ' + sel('w-pos', ['ALL'].concat(POS), c.wpos) + '</label>'
      + jackNote(weeks) + '</div>');
    // KPI strip: Jack vs FP ECR vs consensus
    const j = m.jack, fe = m.fpecr, co = m.cons, si = m.sim;
    html.push('<div class="kpis">'
      + kpi('Jack rank corr', f2(j && j.rho), j ? j.n + ' ranked players' : 'no board found')
      + kpi('FP experts rank corr', f2(fe && fe.rho), fe ? fe.n + ' players' : '')
      + kpi('Jack vs FP experts', j && fe ? fe.h2h[1] + '-' + fe.h2h[0] + '-' + fe.h2h[2] : '—', 'W-L-T by rank miss')
      + kpi('MFF sim MAE', f2(si && si.pm && si.pm.mae), si && si.pm ? 'consensus ' + f2(co && co.pm && co.pm.mae) : '')
      + '</div>');
    html.push('<div class="card"><h2>Weekly leaderboard — ' + (c.wk ? 'week ' + c.wk : 'all weeks') + ' · ' + esc(c.wpos) + '</h2><div class="tablewrap"><table><thead><tr>'
      + '<th class="l">Source</th><th>Type</th><th>n</th><th>Rank corr (ρ)</th><th>Avg rank miss</th><th>Top-K hits</th><th>vs Jack (W-L-T)</th><th>MAE pts</th><th>Bias</th><th>RMSE</th><th>r</th></tr></thead><tbody>');
    SRC_WK.map((s) => ({ ...s, m: m[s.k] })).filter((x) => x.m).sort((a, b) => (b.m.rho || -9) - (a.m.rho || -9)).forEach((x) => {
      const pm = x.m.pm;
      html.push('<tr' + (x.k === 'jack' || x.k === 'sim' ? ' class="me"' : '') + '><td class="l"><i class="swatch" style="background:' + COLOR[x.k] + '"></i>' + esc(x.l) + '</td><td class="dim">' + (x.type === 'rank' ? 'ranks' : 'projection') + '</td><td>' + x.m.n + '</td><td>' + f2(x.m.rho) + '</td><td>' + f1(x.m.mae) + '</td><td>' + x.m.hits + '/' + x.m.K + ' <span class="muted">(' + pct(x.m.hitPct) + ')</span></td><td>' + (x.k === 'jack' ? '—' : x.m.h2h.join('-')) + '</td>'
        + (pm ? '<td>' + f2(pm.mae) + '</td><td>' + (pm.bias >= 0 ? '+' : '') + f2(pm.bias) + '</td><td>' + f2(pm.rmse) + '</td><td>' + f2(pm.r) + '</td>' : '<td class="dim">—</td><td class="dim">—</td><td class="dim">—</td><td class="dim">—</td>') + '</tr>');
    });
    html.push('</tbody></table></div><p class="note">Pool per week and position = players who PLAYED and had a site-consensus or MFF sim projection ≥ ' + MIN_PROJ + ' PPR, or sat inside Jack\'s / FantasyPros\' top-' + POOL_N.QB + '/' + POOL_N.RB + '/' + POOL_N.WR + '/' + POOL_N.TE + '. Projection sources are ranked by their projection; "Site consensus" = mean of Sleeper/ESPN/CBS/FantasyPros. Every site number is the last version published before that player\'s kickoff; the MFF sim is the Sim Lab pre-kickoff lock (half-PPR mean + 0.5 × projected receptions). Top-K = 12 for QB/TE, 24 for RB/WR. Byes and DNPs are not graded.</p></div>');

    // player table for a single week
    if (c.wk) {
      const sk = S.sort.weekly || { k: 'act', d: -1 };
      const rows = [];
      poses.forEach((pos) => {
        const rr = weekRows(c.wk, pos); if (!rr.length) return;
        const mm = rankMetrics(rr, SRC_WK.map((s) => s.k), HIT_K[pos], 'jack');
        rr.forEach((r, i) => {
          const o = { n: r.n, pos, tm: r.tm || '', opp: r.opp || '', act: r.act, fin: mm.cons ? mm.cons.actRank[i] : (mm.sim ? mm.sim.actRank[i] : null), jack: r.r.jack, fpecr: r.r.fpecr };
          SRC_WK.filter((s) => s.type === 'proj').forEach((s) => { o[s.k] = isNum(r.v[s.k]) ? r.v[s.k] : null; });
          rows.push(o);
        });
      });
      rows.sort((a, b) => cmp(a[sk.k], b[sk.k]) * sk.d);
      const cols = [{ k: 'n', l: 'Player', left: true }, { k: 'pos', l: 'Pos', left: true }, { k: 'tm', l: 'Tm', left: true }, { k: 'opp', l: 'Opp', left: true }, { k: 'act', l: 'Actual' }, { k: 'fin', l: 'Pos fin' }, { k: 'jack', l: 'Jack rk' }, { k: 'fpecr', l: 'FP rk' }]
        .concat(SRC_WK.filter((s) => s.type === 'proj').map((s) => ({ k: s.k, l: s.l.replace('Site consensus', 'Cons').replace('FantasyPros', 'FP').replace('MFF sim', 'MFF') })));
      html.push('<div class="card"><h2>Week ' + c.wk + ' players — ' + esc(c.wpos) + '</h2><div class="tablewrap"><table id="t-weekly"><thead><tr>');
      cols.forEach((col) => html.push('<th data-k="' + col.k + '" class="' + (col.left ? 'l ' : '') + (sk.k === col.k ? 'sorted' : '') + '">' + esc(col.l) + '</th>'));
      html.push('</tr></thead><tbody>');
      rows.forEach((o) => {
        const projs = SRC_WK.filter((s) => s.type === 'proj').map((s) => [s.k, o[s.k]]).filter((x) => isNum(x[1]));
        let best = null, worst = null;
        if (projs.length > 1) { projs.sort((a, b) => Math.abs(a[1] - o.act) - Math.abs(b[1] - o.act)); best = projs[0][0]; worst = projs[projs.length - 1][0]; }
        html.push('<tr><td class="l"><a href="#" data-player="' + esc(o.n) + '">' + esc(o.n) + '</a></td><td class="l dim">' + o.pos + '</td><td class="l dim">' + esc(o.tm) + '</td><td class="l dim">' + esc(o.opp) + '</td><td><b>' + f1(o.act) + '</b></td><td>' + (o.fin || '—') + '</td><td>' + (o.jack || '<span class="dim">—</span>') + '</td><td>' + (o.fpecr || '<span class="dim">—</span>') + '</td>');
        SRC_WK.filter((s) => s.type === 'proj').forEach((s) => { const v = o[s.k]; html.push('<td class="' + (s.k === best ? 'best' : s.k === worst ? 'worst' : '') + '">' + f1(v) + '</td>'); });
        html.push('</tr>');
      });
      html.push('</tbody></table></div><p class="note">Green = closest projection to the actual score on that row, red = furthest. Ranks are positional (Jack\'s weekly board, FantasyPros PPR expert consensus).</p></div>');
    }
    $('#tab-weekly').innerHTML = html.join('');
    $('#w-wk').onchange = (e) => { c.wk = +e.target.value; render(); };
    $('#w-pos').onchange = (e) => { c.wpos = e.target.value; render(); };
    bindSort('#t-weekly', 'weekly');
  }
  function jackNote(weeks) {
    return '<span class="muted">' + weeks.map((w) => {
      const jm = S.jackMeta[w];
      if (!jm) return 'W' + w + ': reading Jack\'s board…';
      if (jm.error) return 'W' + w + ': Jack board unavailable (' + esc(jm.error) + ')';
      return 'W' + w + ': Jack board from ' + jm.used.length + ' save' + (jm.used.length === 1 ? '' : 's') + (jm.used.length ? ' (latest ' + esc(jm.used[jm.used.length - 1].slice(0, 16).replace('T', ' ')) + ')' : '') + ', ' + jm.ranked + ' played players ranked';
    }).join(' · ') + '</span>';
  }
  function kpi(l, v, s) { return '<div class="kpi"><div class="l">' + esc(l) + '</div><div class="v">' + v + '</div><div class="s">' + esc(s || '') + '</div></div>'; }

  // ------------------------------------------------------------------ trend
  function renderTrend() {
    const c = S.ctl;
    const played = S.season.weeks.filter((w) => w.played > 0).map((w) => w.week);
    const poses = c.tpos === 'ALL' ? POS : [c.tpos];
    const series = SRC_WK.filter((s) => c.metric === 'mae' ? s.type === 'proj' : true);
    const data = played.map((w) => { const m = weekMetrics([w], poses); const o = { w }; series.forEach((s) => { const x = m[s.k]; o[s.k] = !x ? null : c.metric === 'mae' ? (x.pm ? x.pm.mae : null) : c.metric === 'rho' ? x.rho : x.hitPct; }); return o; });
    const html = [];
    html.push('<div class="controls"><label>Metric ' + sel('t-metric', [['rho', 'Rank correlation (ρ)'], ['hit', 'Top-K hit rate'], ['mae', 'Projection MAE (pts)']], c.metric) + '</label>'
      + '<label>Position ' + sel('t-pos', ['ALL'].concat(POS), c.tpos) + '</label></div>');
    html.push('<div class="card"><h2>' + { rho: 'Rank correlation by week', hit: 'Top-K hit rate by week', mae: 'Projection MAE by week' }[c.metric] + ' — ' + esc(c.tpos) + '</h2>'
      + '<div class="chartwrap"><canvas id="trendCanvas"></canvas><div class="tip" id="trendTip"></div></div><div class="legend">'
      + series.map((s) => '<span><i style="background:' + COLOR[s.k] + '"></i>' + esc(s.l) + '</span>').join('') + '</div></div>');
    html.push('<div class="card"><h2>Table</h2><div class="tablewrap"><table><thead><tr><th class="l">Week</th>' + series.map((s) => '<th>' + esc(s.l) + '</th>').join('') + '</tr></thead><tbody>');
    data.forEach((o) => { html.push('<tr><td class="l">W' + o.w + '</td>' + series.map((s) => '<td>' + (c.metric === 'hit' ? pct(o[s.k]) : f2(o[s.k])) + '</td>').join('') + '</tr>'); });
    html.push('</tbody></table></div><p class="note">' + (c.metric === 'mae' ? 'Lower is better. Mean absolute error in PPR points over the week\'s pool.' : c.metric === 'rho' ? 'Higher is better. Spearman correlation between each source\'s positional order and the actual finish, averaged across positions weighted by pool size.' : 'Higher is better. Share of the source\'s top-K (12 QB/TE, 24 RB/WR) that finished top-K.') + '</p></div>');
    $('#tab-trend').innerHTML = html.join('');
    $('#t-metric').onchange = (e) => { c.metric = e.target.value; render(); };
    $('#t-pos').onchange = (e) => { c.tpos = e.target.value; render(); };
    drawTrend(data, series, c.metric);
  }
  function drawTrend(data, series, metric) {
    const cv = $('#trendCanvas'); if (!cv) return;
    const dpr = window.devicePixelRatio || 1; const W = cv.clientWidth, H = cv.clientHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    const ctx = cv.getContext('2d'); ctx.scale(dpr, dpr);
    const padL = 44, padR = 16, padT = 14, padB = 30;
    const xs = data.map((d) => d.w);
    const vals = []; data.forEach((d) => series.forEach((s) => { if (isNum(d[s.k])) vals.push(d[s.k]); }));
    if (!vals.length) { ctx.fillStyle = '#898781'; ctx.fillText('No data yet', padL, H / 2); return; }
    let lo = metric === 'mae' ? 0 : Math.min(0, ...vals), hi = Math.max(...vals);
    if (metric === 'hit') { lo = 0; hi = 1; } else if (metric === 'rho') { lo = Math.min(lo, 0); hi = Math.max(hi, 1); } else { hi = Math.ceil(hi + 1); }
    const x = (w) => xs.length > 1 ? padL + (W - padL - padR) * (xs.indexOf(w) / (xs.length - 1)) : (padL + W - padR) / 2;
    const y = (v) => padT + (H - padT - padB) * (1 - (v - lo) / (hi - lo || 1));
    ctx.strokeStyle = '#2c2c2a'; ctx.lineWidth = 1; ctx.fillStyle = '#898781'; ctx.font = '11px sans-serif'; ctx.textAlign = 'right';
    const ticks = 5;
    for (let i = 0; i <= ticks; i++) { const v = lo + (hi - lo) * i / ticks; ctx.beginPath(); ctx.moveTo(padL, y(v)); ctx.lineTo(W - padR, y(v)); ctx.stroke(); ctx.fillText(metric === 'hit' ? Math.round(v * 100) + '%' : v.toFixed(metric === 'mae' ? 0 : 1), padL - 6, y(v) + 4); }
    ctx.textAlign = 'center'; xs.forEach((w) => ctx.fillText('W' + w, x(w), H - 10));
    ctx.strokeStyle = '#383835'; ctx.beginPath(); ctx.moveTo(padL, y(lo)); ctx.lineTo(W - padR, y(lo)); ctx.stroke();
    series.forEach((s) => {
      ctx.strokeStyle = COLOR[s.k]; ctx.fillStyle = COLOR[s.k]; ctx.lineWidth = 2; ctx.beginPath(); let started = false;
      data.forEach((d) => { if (!isNum(d[s.k])) { started = false; return; } if (!started) { ctx.moveTo(x(d.w), y(d[s.k])); started = true; } else ctx.lineTo(x(d.w), y(d[s.k])); });
      ctx.stroke();
      data.forEach((d) => { if (!isNum(d[s.k])) return; ctx.beginPath(); ctx.arc(x(d.w), y(d[s.k]), 4, 0, Math.PI * 2); ctx.fill(); ctx.strokeStyle = '#1a1a19'; ctx.lineWidth = 2; ctx.stroke(); ctx.strokeStyle = COLOR[s.k]; });
    });
    const tip = $('#trendTip');
    cv.onmousemove = (ev) => {
      const r = cv.getBoundingClientRect(); const mx = ev.clientX - r.left;
      let best = null; xs.forEach((w) => { const d = Math.abs(x(w) - mx); if (best === null || d < best.d) best = { w, d }; });
      if (!best || best.d > 40) { tip.style.display = 'none'; return; }
      const d = data.find((o) => o.w === best.w);
      tip.innerHTML = '<b>Week ' + best.w + '</b><br>' + series.map((s) => '<span style="color:' + COLOR[s.k] + '">●</span> ' + esc(s.l) + ': ' + (metric === 'hit' ? pct(d[s.k]) : f2(d[s.k]))).join('<br>');
      tip.style.display = 'block'; tip.style.left = Math.min(mx + 12, W - 200) + 'px'; tip.style.top = (ev.clientY - r.top + 12) + 'px';
    };
    cv.onmouseleave = () => { tip.style.display = 'none'; };
  }

  // ------------------------------------------------------------------ player
  function renderPlayer() {
    const c = S.ctl; const P = S.season.players;
    const html = ['<div class="controls"><label>Player <input id="p-q" list="p-names" value="' + esc(c.q) + '" placeholder="type a name" style="min-width:240px"></label><datalist id="p-names">'
      + Object.keys(P).sort().map((n) => '<option value="' + esc(n) + '">').join('') + '</datalist></div>'];
    const n = c.q && P[c.q] ? c.q : null;
    if (!n) { html.push('<div class="card muted">Pick a player to see every source\'s number against his actual scores.</div>'); }
    else {
      const p = P[n];
      html.push('<div class="card"><h2>' + esc(n) + ' <span class="pill">' + p.pos + (p.tm ? ' · ' + p.tm : '') + '</span></h2>');
      if (p.pre) {
        html.push('<table><thead><tr>' + SRC_PRE.map((s) => '<th>' + esc(s.l) + '</th>').join('') + '</tr></thead><tbody><tr>' + SRC_PRE.map((s) => '<td>' + (isNum(p.pre[s.k]) ? (s.k === 'ud' ? p.pre[s.k].toFixed(1) + ' ADP' : '#' + p.pre[s.k] + ' ovr') : '—') + '</td>').join('') + '</tr></tbody></table>');
      }
      if (p.pj) html.push('<p class="note">Preseason PPG projections: ' + SRC_PJ.map((s) => esc(s.l) + ' ' + f1(p.pj[s.k])).join(' · ') + '</p>');
      html.push('</div>');
      const rows = [];
      Object.keys(S.weeks).map(Number).sort((a, b) => a - b).forEach((w) => {
        const wp = S.weeks[w].players[n]; if (!wp) return;
        const v = wkVals(wp); const jr = (S.jack[w] || {})[n];
        rows.push({ w, opp: wp.opp || '', act: wp.act, jack: jr || null, fpecr: v.fpecr, sim: v.sim, cons: v.cons, sl: v.sl, espn: v.espn, cbs: v.cbs, fp: v.fp, p10: wp.sim ? wp.sim[1] + 0.5 * (wp.sim[4] || 0) : null, p90: wp.sim ? wp.sim[3] + 0.5 * (wp.sim[4] || 0) : null });
      });
      html.push('<div class="card"><h2>Week by week</h2><div class="tablewrap"><table><thead><tr><th class="l">Wk</th><th class="l">Opp</th><th>Actual</th><th>Jack rk</th><th>FP rk</th><th>MFF sim</th><th>MFF p10–p90</th><th>Cons</th><th>Sleeper</th><th>ESPN</th><th>CBS</th><th>FP</th></tr></thead><tbody>');
      rows.forEach((r) => {
        html.push('<tr><td class="l">W' + r.w + '</td><td class="l dim">' + esc(r.opp) + '</td><td><b>' + (isNum(r.act) ? f1(r.act) : '<span class="dim">DNP</span>') + '</b></td><td>' + (r.jack || '—') + '</td><td>' + (r.fpecr || '—') + '</td><td>' + f1(r.sim) + '</td><td class="dim">' + (isNum(r.p10) ? f1(r.p10) + '–' + f1(r.p90) : '—') + '</td><td>' + f1(r.cons) + '</td><td>' + f1(r.sl) + '</td><td>' + f1(r.espn) + '</td><td>' + f1(r.cbs) + '</td><td>' + f1(r.fp) + '</td></tr>');
      });
      html.push('</tbody></table></div></div>');
    }
    $('#tab-player').innerHTML = html.join('');
    const inp = $('#p-q');
    inp.onchange = (e) => { c.q = e.target.value.trim(); render(); };
    inp.onkeydown = (e) => { if (e.key === 'Enter') { c.q = inp.value.trim(); render(); } };
  }

  // ------------------------------------------------------------------ plumbing
  S.sort = {};
  function sel(id, opts, cur) {
    return '<select id="' + id + '">' + opts.map((o) => { const [v, l] = Array.isArray(o) ? o : [o, o]; return '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(l) + '</option>'; }).join('') + '</select>';
  }
  function cmp(a, b) {
    const na = a === null || a === undefined || a === '', nb = b === null || b === undefined || b === '';
    if (na && nb) return 0; if (na) return 1; if (nb) return -1;
    if (typeof a === 'number' && typeof b === 'number') return a - b;
    return String(a).localeCompare(String(b));
  }
  function bindSort(tableSel, key) {
    const t = $(tableSel); if (!t) return;
    t.querySelectorAll('th[data-k]').forEach((th) => {
      th.onclick = () => {
        const k = th.dataset.k; const cur = S.sort[key] || {};
        // numeric columns default descending, text ascending; ranks ascending
        const rankCol = /^r_|^jack$|^fpecr$|^fin$|^actRank$/.test(k);
        const d = cur.k === k ? -cur.d : (['n', 'tm', 'pos', 'opp'].includes(k) || rankCol) ? 1 : -1;
        S.sort[key] = { k, d }; render();
      };
    });
  }
  function bindTabs() {
    document.querySelectorAll('nav.tabs button').forEach((b) => { b.onclick = () => { S.tab = b.dataset.tab; render(); }; });
    document.body.addEventListener('click', (e) => {
      const a = e.target.closest('a[data-player]'); if (!a) return;
      e.preventDefault(); S.ctl.q = a.dataset.player; S.tab = 'player'; render(); window.scrollTo(0, 0);
    });
  }
  function render() {
    document.querySelectorAll('nav.tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === S.tab));
    ['season', 'weekly', 'trend', 'player'].forEach((t) => { $('#tab-' + t).style.display = t === S.tab ? '' : 'none'; });
    if (S.tab === 'season') renderSeason();
    else if (S.tab === 'weekly') renderWeekly();
    else if (S.tab === 'trend') renderTrend();
    else renderPlayer();
  }
  window.addEventListener('resize', () => { if (S.tab === 'trend' && S.season) renderTrend(); });
  boot();
})();
