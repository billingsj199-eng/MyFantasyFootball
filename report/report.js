/* MFF Report — admin dashboard for revenue, members, accounts and traffic.
 * Data comes from the adminReport Cloud Function (functions/admin_report.js),
 * which pulls Stripe, Firebase Auth, Firestore and GA4 server-side and only
 * answers Jack's verified account. All days are America/New_York.
 * ?demo=1 renders generated data without signing in (layout testing only). */
(function () {
  'use strict';
  const ADMIN_EMAILS = ['billingsj199@gmail.com'];
  const TZ = 'America/New_York';
  const ALL_START = '2026-01-01';
  const LS_KEY = 'mff_report_prefs';
  const DEMO = /[?&]demo=1\b/.test(location.search);
  const $ = (id) => document.getElementById(id);

  // ---------- dates ----------
  const _dayFmt = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' });
  const todayET = () => _dayFmt.format(new Date());
  const parse = (ds) => { const [y, m, d] = ds.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d)); };
  const fmtDs = (dt) => dt.toISOString().slice(0, 10);
  const addDays = (ds, n) => { const d = parse(ds); d.setUTCDate(d.getUTCDate() + n); return fmtDs(d); };
  const daysBetween = (a, b) => Math.round((parse(b) - parse(a)) / 86400000);
  const dayList = (a, b) => { const out = []; for (let d = a; d <= b; d = addDays(d, 1)) out.push(d); return out; };
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const shortDay = (ds) => { const d = parse(ds); return MON[d.getUTCMonth()] + ' ' + d.getUTCDate(); };
  const longDay = (ds) => shortDay(ds) + ', ' + ds.slice(0, 4);
  function weekStart(ds) { const d = parse(ds); const dow = (d.getUTCDay() + 6) % 7; d.setUTCDate(d.getUTCDate() - dow); return fmtDs(d); }
  function bucketOf(ds, g) { return g === 'month' ? ds.slice(0, 7) : g === 'week' ? weekStart(ds) : ds; }
  function bucketLabel(k, g, short) {
    if (g === 'month') { const [y, m] = k.split('-'); return MON[+m - 1] + (short ? " '" + y.slice(2) : ' ' + y); }
    if (g === 'week') return (short ? '' : 'Week of ') + shortDay(k);
    return short ? shortDay(k) : longDay(k);
  }

  function presetRange(p) {
    const t = todayET();
    const y = +t.slice(0, 4), m = +t.slice(5, 7);
    switch (p) {
      case 'today': return [t, t];
      case 'yesterday': { const d = addDays(t, -1); return [d, d]; }
      case '7d': return [addDays(t, -6), t];
      case '30d': return [addDays(t, -29), t];
      case '90d': return [addDays(t, -89), t];
      case 'mtd': return [t.slice(0, 8) + '01', t];
      case 'lastmonth': { const first = t.slice(0, 8) + '01'; const end = addDays(first, -1); return [end.slice(0, 8) + '01', end]; }
      case 'season': { const sy = m >= 3 ? y : y - 1; return [sy + '-08-01' > t ? (sy - 1) + '-08-01' : sy + '-08-01', t]; }
      case 'ytd': return [y + '-01-01', t];
      case 'all': return [ALL_START, t];
      default: return null;
    }
  }
  const PRESETS = [['today', 'Today'], ['yesterday', 'Yesterday'], ['7d', 'Last 7 days'], ['30d', 'Last 30 days'], ['90d', 'Last 90 days'],
    ['mtd', 'This month'], ['lastmonth', 'Last month'], ['season', 'Season (Aug 1)'], ['ytd', 'Year to date'], ['all', 'All time'], ['custom', 'Custom…']];
  const autoGrain = (a, b) => { const n = daysBetween(a, b) + 1; return n <= 45 ? 'day' : n <= 200 ? 'week' : 'month'; };

  // ---------- formatting ----------
  const nf0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
  const nf1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
  const money = (c) => { if (c == null || isNaN(c)) return '—'; const v = c / 100; return (v < 0 ? '−$' : '$') + (Math.abs(v) >= 1000 ? nf0.format(Math.abs(v)) : Math.abs(v).toFixed(2)); };
  const moneyAxis = (c) => { const v = c / 100; return '$' + (v >= 1000 ? nf1.format(v / 1000) + 'k' : nf0.format(v)); };
  const num = (v) => (v == null || isNaN(v) ? '—' : nf0.format(v));
  const numAxis = (v) => (v >= 1000 ? nf1.format(v / 1000) + 'k' : nf0.format(v));
  const pct = (v, d = 1) => (v == null || !isFinite(v) ? '—' : (v * 100).toFixed(d) + '%');
  const dur = (s) => { if (!s || !isFinite(s)) return '—'; const m = Math.floor(s / 60), r = Math.round(s % 60); return m ? m + 'm ' + r + 's' : r + 's'; };
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function delta(cur, prev, mode) {
    if (cur == null || prev == null || !isFinite(cur) || !isFinite(prev)) return '';
    if (mode === 'pp') { const d = (cur - prev) * 100; if (Math.abs(d) < 0.05) return '<span>±0 pp</span>'; return '<span class="' + (d > 0 ? 'up' : 'dn') + '">' + (d > 0 ? '▲ ' : '▼ ') + Math.abs(d).toFixed(1) + ' pp</span>'; }
    if (mode === 'abs') { const d = cur - prev; if (!d) return '<span>±0</span>'; return '<span class="' + (d > 0 ? 'up' : 'dn') + '">' + (d > 0 ? '▲ +' : '▼ −') + nf0.format(Math.abs(d)) + '</span>'; }
    if (prev === 0) return cur > 0 ? '<span class="up">▲ new</span>' : '<span>±0%</span>';
    const d = (cur - prev) / Math.abs(prev);
    if (Math.abs(d) < 0.0005) return '<span>±0%</span>';
    return '<span class="' + (d > 0 ? 'up' : 'dn') + '">' + (d > 0 ? '▲ ' : '▼ ') + (Math.abs(d) * 100).toFixed(Math.abs(d) < 0.1 ? 1 : 0) + '%</span>';
  }

  // ---------- state ----------
  let prefs = { preset: '30d', grain: null, cmp: true, start: null, end: null };
  try { Object.assign(prefs, JSON.parse(localStorage.getItem(LS_KEY) || '{}')); } catch (e) { /* storage blocked */ }
  const savePrefs = () => { try { localStorage.setItem(LS_KEY, JSON.stringify(prefs)); } catch (e) { /* ignore */ } };
  let DATA = null;
  const clientCache = new Map();
  let reqSeq = 0;

  function curRange() {
    if (prefs.preset === 'custom' && prefs.start && prefs.end) return [prefs.start, prefs.end];
    return presetRange(prefs.preset) || presetRange('30d');
  }

  // ---------- plans ----------
  const PLANS = [
    { key: 'season', label: 'Season Pass', color: 'var(--s1)' },
    { key: 'monthly', label: 'Monthly (new)', color: 'var(--s2)' },
    { key: 'yearly', label: 'Yearly (new)', color: 'var(--s3)' },
    { key: 'renewal', label: 'Renewals', color: 'var(--s4)' },
    { key: 'lineskip', label: 'Ask Jack skip', color: 'var(--s5)' },
    { key: 'other', label: 'Other', color: 'var(--s7)' },
  ];
  const planKey = (k) => (/_renewal$/.test(k) ? 'renewal' : PLANS.some((p) => p.key === k) ? k : 'other');

  // ---------- per-day metrics ----------
  function dayRow(ds) {
    const s = DATA.stripe && DATA.stripe.ok ? DATA.stripe : null;
    const a = DATA.auth && DATA.auth.ok ? DATA.auth : null;
    const g = DATA.ga4 && DATA.ga4.ok ? DATA.ga4 : null;
    const q = DATA.askjack && DATA.askjack.ok ? DATA.askjack : null;
    const m = (s && s.daily[ds]) || {};
    const r = {
      gross: s ? m.gross || 0 : null, net: s ? m.net || 0 : null, fees: s ? m.fees || 0 : null, refunds: s ? m.refunds || 0 : null,
      newPaid: s ? (s.newPaid[ds] || 0) : null, members: s ? s.members[ds] : null,
      signups: a ? (a.signups[ds] || 0) : null, totalAccounts: a ? a.totalAt[ds] : null,
      dau: null, newUsers: null, sessions: null, views: null, engSec: null,
      askjack: q ? Object.values(q.daily[ds] || {}).reduce((x, y) => x + y, 0) : null,
      plans: {},
    };
    if (s && s.byPlan[ds]) for (const [k, v] of Object.entries(s.byPlan[ds])) { const pk = planKey(k); r.plans[pk] = (r.plans[pk] || 0) + v; }
    if (g) {
      const gd = g.daily[ds];
      if (gd) { r.dau = gd.activeUsers; r.newUsers = gd.newUsers; r.sessions = gd.sessions; r.views = gd.views; r.engSec = gd.engSec; }
      else if (ds <= todayET()) { r.dau = 0; r.newUsers = 0; r.sessions = 0; r.views = 0; r.engSec = 0; }
    }
    return r;
  }
  const SUM = ['gross', 'net', 'fees', 'refunds', 'newPaid', 'signups', 'newUsers', 'sessions', 'views', 'engSec', 'askjack'];
  function agg(days) {
    const rows = days.map(dayRow);
    const o = { plans: {}, days: days.length };
    for (const k of SUM) { const vals = rows.map((r) => r[k]).filter((v) => v != null); o[k] = vals.length ? vals.reduce((x, y) => x + y, 0) : null; }
    const dv = rows.map((r) => r.dau).filter((v) => v != null);
    o.dau = dv.length ? dv.reduce((x, y) => x + y, 0) / dv.length : null;
    const last = rows[rows.length - 1] || {};
    o.members = last.members != null ? last.members : null;
    o.totalAccounts = last.totalAccounts != null ? last.totalAccounts : null;
    for (const r of rows) for (const [k, v] of Object.entries(r.plans)) o.plans[k] = (o.plans[k] || 0) + v;
    return o;
  }
  function buckets(days, g) {
    const map = new Map();
    for (const d of days) { const k = bucketOf(d, g); if (!map.has(k)) map.set(k, []); map.get(k).push(d); }
    return [...map.entries()].map(([k, ds]) => ({ key: k, days: ds, m: agg(ds) }));
  }

  // ---------- chart (SVG) ----------
  const SVGNS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs, parent) { const e = document.createElementNS(SVGNS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }
  // Tick step from ~4 intervals, snapped to 1/2/2.5/5 × 10^k (2.5 only when it stays whole).
  function niceStep(v) {
    const raw = Math.max(v, 1) / 4;
    const p = Math.pow(10, Math.floor(Math.log10(raw)));
    for (const c of [1, 2, 2.5, 5, 10]) { if (c === 2.5 && p < 10) continue; if (raw <= c * p) return c * p; }
    return 10 * p;
  }
  /* opts: {labels[], tipLabels[], stacks:[{label,color,values}], lines:[{label,color,values,dashed}], fmt, axisFmt, height} */
  function drawChart(host, opts) {
    host.innerHTML = '';
    const n = opts.labels.length;
    const hasData = (opts.stacks || []).some((s) => s.values.some((v) => v)) || (opts.lines || []).some((s) => s.values.some((v) => v != null && v !== 0));
    if (!n || !hasData) { host.innerHTML = '<div class="empty">' + (opts.emptyMsg || 'No data in this range') + '</div>'; return; }
    const W = Math.max(280, host.clientWidth || 600), H = opts.height || 220;
    const ml = 46, mr = 8, mt = 8, mb = 24;
    const pw = W - ml - mr, ph = H - mt - mb;
    let max = 0;
    for (let i = 0; i < n; i++) {
      let s = 0; for (const st of opts.stacks || []) s += st.values[i] || 0; max = Math.max(max, s);
      for (const ln of opts.lines || []) if (ln.values[i] != null) max = Math.max(max, ln.values[i]);
    }
    const tStep = niceStep(max * 1.05);
    const nTicks = Math.max(1, Math.ceil((max * 1.05) / tStep));
    max = tStep * nTicks;
    const y = (v) => mt + ph - (v / max) * ph;
    const band = pw / n;
    const xc = (i) => ml + band * i + band / 2;
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, height: H, role: 'img', 'aria-label': opts.aria || '' }, host);
    // grid + y labels
    for (let t = 0; t <= nTicks; t++) {
      const v = tStep * t, yy = y(v);
      el('line', { x1: ml, x2: W - mr, y1: yy, y2: yy, stroke: t ? 'var(--grid)' : 'var(--axis)', 'stroke-width': 1 }, svg);
      const tx = el('text', { x: ml - 6, y: yy + 4, 'text-anchor': 'end', 'font-size': 11, fill: 'var(--muted)' }, svg);
      tx.textContent = (opts.axisFmt || numAxis)(v);
    }
    // x labels (~7)
    const step = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(pw / 78))));
    for (let i = 0; i < n; i += step) {
      const tx = el('text', { x: xc(i), y: H - 6, 'text-anchor': 'middle', 'font-size': 11, fill: 'var(--muted)' }, svg);
      tx.textContent = opts.labels[i];
    }
    const hl = el('rect', { x: 0, y: mt, width: band, height: ph, fill: 'rgba(255,255,255,.04)', visibility: 'hidden' }, svg);
    // stacked bars
    if (opts.stacks && opts.stacks.length) {
      const bw = Math.max(2, Math.min(28, band * 0.7));
      for (let i = 0; i < n; i++) {
        let base = 0;
        const segs = opts.stacks.map((s) => ({ v: s.values[i] || 0, c: s.color })).filter((s) => s.v > 0);
        segs.forEach((s, j) => {
          const y0 = y(base), y1 = y(base + s.v);
          const top = j === segs.length - 1;
          const gap = j > 0 ? 2 : 0;
          const h = Math.max(1, y0 - y1 - gap);
          const x0 = xc(i) - bw / 2, r = top ? Math.min(4, bw / 2, h) : 0;
          const yb = y0 - gap, yt = yb - h;
          const d = r
            ? `M${x0},${yb} V${yt + r} Q${x0},${yt} ${x0 + r},${yt} H${x0 + bw - r} Q${x0 + bw},${yt} ${x0 + bw},${yt + r} V${yb} Z`
            : `M${x0},${yb} V${yt} H${x0 + bw} V${yb} Z`;
          el('path', { d, fill: s.c }, svg);
          base += s.v;
        });
      }
    }
    // lines
    const dots = [];
    for (const ln of opts.lines || []) {
      let d = '', pen = false;
      for (let i = 0; i < n; i++) {
        const v = ln.values[i];
        if (v == null) { pen = false; continue; }
        d += (pen ? 'L' : 'M') + xc(i).toFixed(1) + ',' + y(v).toFixed(1) + ' ';
        pen = true;
      }
      el('path', { d, fill: 'none', stroke: ln.color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', 'stroke-dasharray': ln.dashed ? '5 4' : 'none', opacity: ln.dashed ? 0.8 : 1 }, svg);
      if (n === 1 && ln.values[0] != null) el('circle', { cx: xc(0), cy: y(ln.values[0]), r: 4, fill: ln.color }, svg);
      const dot = el('circle', { r: 4.5, fill: ln.color, stroke: 'var(--surface)', 'stroke-width': 2, visibility: 'hidden' }, svg);
      dots.push({ dot, ln });
    }
    // hover
    const tip = document.createElement('div'); tip.className = 'tip'; host.appendChild(tip);
    const hit = el('rect', { x: ml, y: mt, width: pw, height: ph, fill: 'transparent' }, svg);
    const fmt = opts.fmt || num;
    function show(ev) {
      const rect = svg.getBoundingClientRect();
      const sx = (ev.clientX - rect.left) * (W / rect.width);
      const i = Math.max(0, Math.min(n - 1, Math.floor((sx - ml) / band)));
      hl.setAttribute('x', ml + band * i); hl.setAttribute('visibility', 'visible');
      let rows = '';
      let total = 0;
      for (const s of opts.stacks || []) { const v = s.values[i] || 0; total += v; if (v) rows += `<div class="row"><span><i style="background:${s.color}"></i>${esc(s.label)}</span><b>${fmt(v)}</b></div>`; }
      if ((opts.stacks || []).length > 1) rows += `<div class="row"><span>Total</span><b>${fmt(total)}</b></div>`;
      if ((opts.stacks || []).length && !total) rows += `<div class="row"><span>No sales</span><b>${fmt(0)}</b></div>`;
      for (const { dot, ln } of dots) {
        const v = ln.values[i];
        if (v == null) { dot.setAttribute('visibility', 'hidden'); continue; }
        dot.setAttribute('cx', xc(i)); dot.setAttribute('cy', y(v)); dot.setAttribute('visibility', 'visible');
        const lbl = ln.dashed && ln.tipLabels ? ln.label + ' (' + ln.tipLabels[i] + ')' : ln.label;
        rows += `<div class="row"><span><i style="background:${ln.color}"></i>${esc(lbl)}</span><b>${fmt(v)}</b></div>`;
      }
      tip.innerHTML = `<div class="tt">${esc((opts.tipLabels || opts.labels)[i])}</div>${rows}`;
      tip.style.display = 'block';
      const hostR = host.getBoundingClientRect();
      const px = ev.clientX - hostR.left, tw = tip.offsetWidth;
      tip.style.left = Math.max(0, Math.min(hostR.width - tw, px + 14 + tw > hostR.width ? px - tw - 14 : px + 14)) + 'px';
      tip.style.top = Math.max(0, ev.clientY - hostR.top - 20) + 'px';
    }
    function hide() { tip.style.display = 'none'; hl.setAttribute('visibility', 'hidden'); for (const { dot } of dots) dot.setAttribute('visibility', 'hidden'); }
    hit.addEventListener('mousemove', show);
    hit.addEventListener('mouseleave', hide);
    hit.addEventListener('touchstart', (e) => { show(e.touches[0]); }, { passive: true });
    hit.addEventListener('touchmove', (e) => { show(e.touches[0]); }, { passive: true });
  }
  function legend(host, items) {
    host.innerHTML = items.map((it) => `<span><i class="${it.dashed ? 'dash' : it.line ? 'ln' : ''}" style="background:${it.color}"></i>${esc(it.label)}</span>`).join('');
  }

  // ---------- render ----------
  function render() {
    if (!DATA) return;
    const R = DATA.range;
    const g = prefs.grain || autoGrain(R.start, R.end);
    const cmp = prefs.cmp;
    const curDays = dayList(R.start, R.end);
    const prevDays = dayList(R.prevStart, R.prevEnd);
    const cur = agg(curDays), prev = agg(prevDays);
    const bk = buckets(curDays, g), pbk = buckets(prevDays, g);
    const S = DATA.stripe && DATA.stripe.ok ? DATA.stripe : null;
    const A = DATA.auth && DATA.auth.ok ? DATA.auth : null;
    const G = DATA.ga4 && DATA.ga4.ok ? DATA.ga4 : null;
    const P = DATA.premium && DATA.premium.ok ? DATA.premium : null;
    const Q = DATA.askjack && DATA.askjack.ok ? DATA.askjack : null;

    document.querySelectorAll('#grain button').forEach((b) => b.classList.toggle('on', b.dataset.g === g));
    $('rangeLbl').innerHTML = `<b>${longDay(R.start)}${R.start !== R.end ? ' – ' + longDay(R.end) : ''}</b> · ${R.days} day${R.days > 1 ? 's' : ''}`
      + (cmp ? ` · compared with ${longDay(R.prevStart)}${R.prevStart !== R.prevEnd ? ' – ' + longDay(R.prevEnd) : ''}` : '')
      + (R.end === todayET() ? ' · today is still in progress' : '') + ' · Eastern time';
    $('genAt').textContent = 'updated ' + new Date(DATA.generatedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

    // notices
    const notes = [];
    if (DATA.ga4 && !DATA.ga4.ok) {
      const sa = (DATA.ga4.setup && DATA.ga4.setup.serviceAccount) || '732824763527-compute@developer.gserviceaccount.com';
      notes.push(`<b>Traffic (GA4) isn't connected yet</b> — daily active users, sessions and sources need two one-time steps:<ol>
        <li><a href="https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com?project=jackb933-website" target="_blank" rel="noopener">Enable the Google Analytics Data API</a> on project jackb933-website.</li>
        <li>In <a href="https://analytics.google.com/analytics/web/#/a389327222p530487711/admin/suggested-permissions" target="_blank" rel="noopener">GA4 → Admin → Property access management</a>, add <code>${esc(sa)}</code> as a <b>Viewer</b>.</li></ol>
        <div style="margin-top:6px;color:var(--muted);font-size:12px">Error: ${esc(DATA.ga4.error || '')}</div>`);
    }
    if (S && S.livemode === false) notes.push('<b>Stripe is in TEST mode</b> — these revenue numbers are test payments, not real money.');
    for (const [name, sec] of [['Stripe', DATA.stripe], ['Firebase Auth', DATA.auth], ['Firestore premium', DATA.premium], ['Ask Jack', DATA.askjack]]) {
      if (sec && !sec.ok) notes.push(`<b>${name} failed to load:</b> ${esc(sec.error || 'unknown error')}`);
    }
    $('notices').innerHTML = notes.map((n) => `<div class="notice">${n}</div>`).join('');

    // tiles
    const tile = (k, v, d, sub, na) => `<div class="tile${na ? ' na' : ''}"><div class="k">${k}</div><div class="v">${v}</div>${cmp && d ? `<div class="d">${d} <span>vs prev</span></div>` : ''}${sub ? `<div class="sub">${sub}</div>` : ''}</div>`;
    const membersBefore = S ? S.members[R.prevEnd] : null;
    const payingNow = S ? S.snapshot.payingNow : null;
    $('tilesMoney').innerHTML = [
      tile('Gross revenue', S ? money(cur.gross) : '—', S && delta(cur.gross, prev.gross), S ? `${num(sumPayments(curDays))} payments` : 'Stripe unavailable', !S),
      tile('Net revenue', S ? money(cur.net) : '—', S && delta(cur.net, prev.net), S ? `after ${money(cur.fees)} fees${cur.refunds ? ' · ' + money(cur.refunds) + ' refunded' : ''}` : '', !S),
      tile('New paid members', S ? num(cur.newPaid) : '—', S && delta(cur.newPaid, prev.newPaid), 'first purchases (no renewals / skips)', !S),
      tile('Paying members now', S ? num(payingNow) : '—', S && membersBefore != null ? delta(payingNow, membersBefore, 'abs') : '', S ? `${num(S.snapshot.seasonActive)} season · ${num(S.snapshot.subs.monthly)} monthly · ${num(S.snapshot.subs.yearly)} yearly` : '', !S),
      tile('MRR', S ? money(S.snapshot.mrr) : '—', '', S ? `subscriptions only · ${money(S.snapshot.mrr * 12)} / yr run-rate` : '', !S),
      tile('Avg revenue / day', S ? money(cur.gross / Math.max(1, R.days)) : '—', S && delta(cur.gross / R.days, prev.gross / R.days), S ? `lifetime checkout ${money(S.snapshot.lifetimeCheckout)}` : '', !S),
    ].join('');
    const signupRate = cur.newUsers ? cur.signups / cur.newUsers : null, pSignupRate = prev.newUsers ? prev.signups / prev.newUsers : null;
    const payConv = cur.signups ? cur.newPaid / cur.signups : null, pPayConv = prev.signups ? prev.newPaid / prev.signups : null;
    const gt = G ? G.totals : null;
    const engPerUser = gt && gt.cur.activeUsers ? gt.cur.userEngagementDuration / gt.cur.activeUsers : null;
    const pEngPerUser = gt && gt.prev.activeUsers ? gt.prev.userEngagementDuration / gt.prev.activeUsers : null;
    $('tilesUsers').innerHTML = [
      tile('Avg daily active users', G ? num(cur.dau) : '—', G && delta(cur.dau, prev.dau), G ? 'GA4, mean of each day' : 'GA4 not connected', !G),
      tile('Unique visitors', gt ? num(gt.cur.activeUsers) : '—', gt && delta(gt.cur.activeUsers, gt.prev.activeUsers), gt ? `${num(gt.cur.newUsers)} first-time` : '', !G),
      tile('Sessions', gt ? num(gt.cur.sessions) : '—', gt && delta(gt.cur.sessions, gt.prev.sessions), gt ? `${num(gt.cur.screenPageViews)} page views` : '', !G),
      tile('Engagement / user', gt ? dur(engPerUser) : '—', gt && delta(engPerUser, pEngPerUser), gt && gt.cur.sessions ? `${pct(gt.cur.engagedSessions / gt.cur.sessions, 0)} engaged sessions` : '', !G),
      tile('Active right now', G && G.realtime != null ? num(G.realtime) : '—', '', 'GA4 realtime, last 30 min', !G || G.realtime == null),
      tile('New accounts', A ? num(cur.signups) : '—', A && delta(cur.signups, prev.signups), A ? `${pct(signupRate)} of new visitors` : 'Auth unavailable', !A),
      tile('Total accounts', A ? num(A.total) : '—', A && prev.totalAccounts != null ? delta(cur.totalAccounts, prev.totalAccounts, 'abs') : '', A ? `${num(A.active7)} signed in last 7 days` : '', !A),
      tile('Paid conversion', S && A ? pct(payConv) : '—', S && A ? delta(payConv, pPayConv, 'pp') : '', 'new paid members ÷ new accounts', !(S && A)),
      tile('Ask Jack questions', Q ? num(cur.askjack) : '—', Q && delta(cur.askjack, prev.askjack), Q ? tierSplit(curDays) : '', !Q),
      tile('Gifted premium', P ? num(P.gifted) : '—', '', 'active gifts / redeem codes', !P),
    ].join('');

    // charts
    const labels = bk.map((b) => bucketLabel(b.key, g, true));
    const tipLabels = bk.map((b) => bucketLabel(b.key, g, false) + (b.days.length < (g === 'week' ? 7 : g === 'month' ? 28 : 1) ? ' (partial)' : ''));
    const prevTip = bk.map((_, i) => (pbk[i] ? bucketLabel(pbk[i].key, g, true) : ''));
    const planOn = PLANS.filter((p) => bk.some((b) => b.m.plans[p.key]));
    legend($('lgRev'), planOn);
    drawChart($('chRev'), {
      labels, tipLabels, fmt: money, axisFmt: moneyAxis, aria: 'Revenue by plan',
      stacks: planOn.map((p) => ({ label: p.label, color: p.color, values: bk.map((b) => b.m.plans[p.key] || 0) })),
      emptyMsg: S ? 'No sales in this range' : 'Stripe data unavailable',
    });
    const withPrev = (key, color, label) => {
      const lines = [{ label, color, values: bk.map((b) => b.m[key]) }];
      if (cmp) lines.push({ label: 'Previous period', color: 'var(--muted)', dashed: true, tipLabels: prevTip, values: bk.map((_, i) => (pbk[i] ? pbk[i].m[key] : null)) });
      return lines;
    };
    const lgLines = (label, color) => [{ label, color, line: true }].concat(cmp ? [{ label: 'Previous period', color: 'var(--muted)', dashed: true }] : []);
    legend($('lgDau'), lgLines(g === 'day' ? 'Active users' : 'Avg daily active users', 'var(--s1)'));
    $('hintDau').textContent = g === 'day' ? 'GA4 active users per day.' : 'GA4 active users — average per day in each ' + g + '.';
    drawChart($('chDau'), { labels, tipLabels, lines: withPrev('dau', 'var(--s1)', 'Active users'), fmt: (v) => nf0.format(v), aria: 'Daily active users', emptyMsg: G ? 'No traffic in this range' : 'GA4 not connected yet' });
    legend($('lgSign'), [{ label: 'New accounts', color: 'var(--s3)' }].concat(cmp ? [{ label: 'Previous period', color: 'var(--muted)', dashed: true }] : []));
    drawChart($('chSign'), {
      labels, tipLabels, aria: 'New accounts',
      stacks: [{ label: 'New accounts', color: 'var(--s3)', values: bk.map((b) => b.m.signups || 0) }],
      lines: cmp ? [{ label: 'Previous period', color: 'var(--muted)', dashed: true, tipLabels: prevTip, values: bk.map((_, i) => (pbk[i] ? pbk[i].m.signups : null)) }] : [],
      emptyMsg: A ? 'No sign-ups in this range' : 'Auth data unavailable',
    });
    legend($('lgMem'), lgLines('Paying members', 'var(--s7)'));
    drawChart($('chMem'), { labels, tipLabels, lines: withPrev('members', 'var(--s7)', 'Paying members'), aria: 'Paying members', emptyMsg: S ? 'No paying members yet' : 'Stripe data unavailable' });

    // period table
    $('periodTitle').textContent = 'By ' + g;
    const cols = [
      ['Period', (b) => bucketLabel(b.key, g, false), 'l'],
      ['Gross', (b) => money(b.m.gross)], ['Net', (b) => money(b.m.net)], ['New paid', (b) => num(b.m.newPaid)],
      ['Paying (end)', (b) => num(b.m.members)], ['New accounts', (b) => num(b.m.signups)], ['Total accounts', (b) => num(b.m.totalAccounts)],
      [g === 'day' ? 'Active users' : 'Avg DAU', (b) => num(b.m.dau)], ['New visitors', (b) => num(b.m.newUsers)], ['Sessions', (b) => num(b.m.sessions)],
      ['Views', (b) => num(b.m.views)], ['Ask Jack Qs', (b) => num(b.m.askjack)],
    ];
    const totRow = { key: 'Total', days: curDays, m: cur };
    $('tblPeriods').innerHTML = '<thead><tr>' + cols.map((c) => `<th class="${c[2] || ''}">${c[0]}</th>`).join('') + '</tr></thead><tbody>'
      + bk.slice().reverse().map((b) => '<tr>' + cols.map((c) => `<td class="${c[2] || ''}">${c[1](b)}</td>`).join('') + '</tr>').join('')
      + (bk.length > 1 ? '<tr class="tot">' + cols.map((c, i) => `<td class="${c[2] || ''}">${i === 0 ? 'Total / avg' : c[1](totRow)}</td>`).join('') + '</tr>' : '')
      + '</tbody>';
    lastCsv = [cols.map((c) => c[0])].concat(bk.map((b) => [b.key, b.m.gross != null ? (b.m.gross / 100).toFixed(2) : '', b.m.net != null ? (b.m.net / 100).toFixed(2) : '', b.m.newPaid, b.m.members, b.m.signups, b.m.totalAccounts, b.m.dau != null ? Math.round(b.m.dau) : '', b.m.newUsers, b.m.sessions, b.m.views, b.m.askjack].map((v) => (v == null ? '' : v))));

    // plans table
    const planRows = PLANS.map((p) => ({ p, c: cur.plans[p.key] || 0, v: prev.plans[p.key] || 0 })).filter((r) => r.c || r.v);
    const planTot = planRows.reduce((s, r) => s + r.c, 0), planPrevTot = planRows.reduce((s, r) => s + r.v, 0);
    $('tblPlans').innerHTML = !S ? '<tbody><tr><td class="l dim">Stripe unavailable</td></tr></tbody>' : !planRows.length ? '<tbody><tr><td class="l dim">No sales in this range</td></tr></tbody>'
      : `<thead><tr><th class="l">Plan</th><th>Revenue</th><th>Share</th>${cmp ? '<th>Prev</th><th>Change</th>' : ''}</tr></thead><tbody>`
      + planRows.map((r) => `<tr><td class="l"><span class="tbar" style="background:${r.p.color};width:10px;margin:0 6px 0 0"></span>${r.p.label}</td><td>${money(r.c)}</td><td class="dim">${pct(planTot ? r.c / planTot : 0, 0)}</td>${cmp ? `<td class="dim">${money(r.v)}</td><td>${delta(r.c, r.v)}</td>` : ''}</tr>`).join('')
      + `<tr class="tot"><td class="l">Total</td><td>${money(planTot)}</td><td></td>${cmp ? `<td class="dim">${money(planPrevTot)}</td><td>${delta(planTot, planPrevTot)}</td>` : ''}</tr></tbody>`;

    // snapshot table
    const nowRows = [];
    if (S) {
      const sn = S.snapshot;
      nowRows.push(['Paying members', num(sn.payingNow)], ['· Season Pass (active)', num(sn.seasonActive)], ['· Monthly subscriptions', num(sn.subs.monthly)], ['· Yearly subscriptions', num(sn.subs.yearly)]);
      if (sn.subs.other) nowRows.push(['· Other subscriptions', num(sn.subs.other)]);
      nowRows.push(['Subscriptions set to cancel', num(sn.canceling)], ['Past due', num(sn.pastDue)], ['MRR (subscriptions)', money(sn.mrr)], ['Season Passes sold (all time)', num(sn.seasonSold)]);
    }
    if (P) {
      nowRows.push(['Premium in Firestore (paid)', num(P.paid) + ' <span class="dim">' + Object.entries(P.byPlan).map(([k, v]) => k + ' ' + v).join(' · ') + '</span>']);
      nowRows.push(['Gifted / redeemed premium', num(P.gifted)]);
    }
    if (A) {
      nowRows.push(['Total accounts', num(A.total)], ['Signed in · last 24 h', num(A.active1)], ['Signed in · last 7 days', num(A.active7)], ['Signed in · last 30 days', num(A.active30)]);
      nowRows.push(['Sign-in methods', Object.entries(A.providers).sort((a, b) => b[1] - a[1]).map(([k, v]) => k.replace('.com', '') + ' ' + num(v)).join(' · ')]);
    }
    if (Q) nowRows.push(['Ask Jack open (asked in range)', num(Q.openInRange)]);
    $('tblNow').innerHTML = '<tbody>' + nowRows.map((r) => `<tr><td class="l">${r[0]}</td><td>${r[1]}</td></tr>`).join('') + '</tbody>';

    // GA tables
    const gaNA = '<tbody><tr><td class="l dim">GA4 not connected</td></tr></tbody>';
    const splitTable = (rows, metric, label) => {
      if (!G) return gaNA;
      rows = rows.filter((r) => r.name && r.name !== '(not set)' || (r.cur[metric] || 0) > 0).sort((a, b) => (b.cur[metric] || 0) - (a.cur[metric] || 0));
      if (!rows.length) return '<tbody><tr><td class="l dim">No data</td></tr></tbody>';
      const mx = Math.max(...rows.map((r) => r.cur[metric] || 0), 1);
      return `<thead><tr><th class="l">${label}</th><th>${metric === 'sessions' ? 'Sessions' : 'Count'}</th><th>Users</th>${cmp ? '<th>Change</th>' : ''}</tr></thead><tbody>`
        + rows.map((r) => `<tr><td class="l" title="${esc(r.name)}">${esc(r.name)}</td><td>${num(r.cur[metric] || 0)}<span class="tbar" style="width:${Math.round(40 * (r.cur[metric] || 0) / mx)}px"></span></td><td class="dim">${num(r.cur.activeUsers != null ? r.cur.activeUsers : r.cur.totalUsers)}</td>${cmp ? `<td>${delta(r.cur[metric] || 0, r.prev[metric] || 0)}</td>` : ''}</tr>`).join('') + '</tbody>';
    };
    $('tblChannels').innerHTML = splitTable(G ? G.channels : [], 'sessions', 'Channel');
    $('tblSources').innerHTML = splitTable(G ? G.sources : [], 'sessions', 'Source');
    if (G) {
      const devTot = G.devices.reduce((s, d) => s + d.users, 0) || 1;
      $('tblDevices').innerHTML = '<thead><tr><th class="l">Device</th><th>Users</th><th>Share</th></tr></thead><tbody>' + G.devices.sort((a, b) => b.users - a.users).map((d) => `<tr><td class="l">${esc(d.name)}</td><td>${num(d.users)}</td><td class="dim">${pct(d.users / devTot, 0)}<span class="tbar" style="width:${Math.round(50 * d.users / devTot)}px"></span></td></tr>`).join('') + '</tbody>';
      const pgMax = Math.max(1, ...G.pages.map((p) => p.views));
      $('tblPages').innerHTML = '<thead><tr><th class="l">Page</th><th>Views</th><th>Users</th></tr></thead><tbody>' + G.pages.map((p) => `<tr><td class="l" title="${esc(p.name)}">${esc(p.name)}</td><td>${num(p.views)}<span class="tbar" style="width:${Math.round(40 * p.views / pgMax)}px"></span></td><td class="dim">${num(p.users)}</td></tr>`).join('') + '</tbody>';
      const KEY = ['sign_up', 'login', 'sign_in_open', 'premium_cta', 'begin_checkout', 'purchase', 'askjack_submit'];
      const evs = G.events.slice().sort((a, b) => {
        const ka = KEY.indexOf(a.name), kb = KEY.indexOf(b.name);
        if ((ka >= 0) !== (kb >= 0)) return ka >= 0 ? -1 : 1;
        if (ka >= 0) return ka - kb;
        return (b.cur.eventCount || 0) - (a.cur.eventCount || 0);
      });
      $('tblEvents').innerHTML = `<thead><tr><th class="l">Event</th><th>Count</th><th>Users</th>${cmp ? '<th>Change</th>' : ''}</tr></thead><tbody>`
        + evs.map((e) => `<tr><td class="l">${KEY.includes(e.name) ? '★ ' : ''}${esc(e.name)}</td><td>${num(e.cur.eventCount || 0)}</td><td class="dim">${num(e.cur.totalUsers || 0)}</td>${cmp ? `<td>${delta(e.cur.eventCount || 0, e.prev.eventCount || 0)}</td>` : ''}</tr>`).join('') + '</tbody>';
    } else {
      $('tblDevices').innerHTML = gaNA; $('tblPages').innerHTML = gaNA; $('tblEvents').innerHTML = gaNA;
    }

    // recent payments (range only)
    if (S) {
      const lo = dayStartGuess(R.start), hi = dayStartGuess(addDays(R.end, 1));
      const rec = S.recent.filter((r) => r.at >= lo && r.at < hi);
      const planLabel = (k) => (PLANS.find((p) => p.key === planKey(k || '')) || {}).label || '';
      $('tblRecent').innerHTML = !rec.length ? '<tbody><tr><td class="l dim">No payments in this range</td></tr></tbody>'
        : '<thead><tr><th class="l">When</th><th>Amount</th><th>Net</th><th class="l">Plan</th><th class="l">Customer</th><th class="l">Description</th></tr></thead><tbody>'
        + rec.map((r) => `<tr><td class="l">${new Date(r.at).toLocaleString('en-US', { timeZone: TZ, month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</td><td>${money(r.amount)}</td><td class="dim">${money(r.net)}</td><td class="l">${esc(r.plan ? planLabel(r.plan) : (/Subscription/i.test(r.desc) ? 'Renewal' : ''))}</td><td class="l">${esc(r.email)}</td><td class="l dim" title="${esc(r.desc)}">${esc(r.desc)}</td></tr>`).join('') + '</tbody>';
    } else $('tblRecent').innerHTML = '<tbody><tr><td class="l dim">Stripe unavailable</td></tr></tbody>';

    // source pills
    const pill = (name, sec, extra) => `<span class="pill ${!sec ? 'warn' : sec.ok ? 'ok' : 'err'}"><span class="dot"></span>${name}${extra ? ' · ' + extra : ''}</span>`;
    $('srcStatus').innerHTML = [
      pill('Stripe', DATA.stripe, S ? (S.livemode === false ? 'TEST mode' : 'live') : 'error'),
      pill('Firebase Auth', DATA.auth, A ? num(A.total) + ' accounts' : 'error'),
      pill('Firestore premium', DATA.premium),
      pill('Ask Jack', DATA.askjack),
      pill('Google Analytics 4', DATA.ga4, G ? 'property 530487711' : 'not connected'),
    ].join('') + `<span class="pill">cached up to 5 min · ↻ Refresh forces a new pull</span>`;

    function sumPayments(days) { let c = 0; for (const d of days) c += (S.daily[d] && S.daily[d].payments) || 0; return c; }
    function tierSplit(days) {
      const t = {};
      for (const d of days) for (const [k, v] of Object.entries(Q.daily[d] || {})) t[k] = (t[k] || 0) + v;
      return Object.entries(t).sort((a, b) => b[1] - a[1]).map(([k, v]) => v + ' ' + k).join(' · ') || 'none';
    }
  }
  // Approximate ET midnight for filtering payment timestamps (±1h at DST edges is fine here).
  function dayStartGuess(ds) {
    const d = parse(ds).getTime();
    const etHourAtUtcNoon = +new Date(d + 12 * 3600e3).toLocaleString('en-US', { timeZone: TZ, hour: 'numeric', hourCycle: 'h23' });
    return d + (12 - etHourAtUtcNoon) * 3600e3;
  }
  let lastCsv = null;

  // ---------- data ----------
  let callFn = null;
  async function load(force) {
    const [start, end] = curRange();
    const key = start + '|' + end;
    if (!force && clientCache.has(key)) { DATA = clientCache.get(key); render(); return; }
    const seq = ++reqSeq;
    document.body.classList.add('busy');
    $('refreshBtn').disabled = true;
    try {
      const data = DEMO ? demoData(start, end) : (await callFn({ start, end, force: !!force })).data;
      if (seq !== reqSeq) return;
      clientCache.set(key, data);
      DATA = data;
      render();
    } catch (e) {
      if (seq !== reqSeq) return;
      console.error('[report]', e);
      $('notices').innerHTML = `<div class="notice"><b>Couldn't load the report:</b> ${esc((e && e.message) || e)}</div>`;
    } finally {
      if (seq === reqSeq) { document.body.classList.remove('busy'); $('refreshBtn').disabled = false; }
    }
  }

  // ---------- controls ----------
  function syncControls() {
    $('presets').querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.p === prefs.preset));
    $('customBox').classList.toggle('show', prefs.preset === 'custom');
    const [s, e] = curRange();
    $('cStart').value = s; $('cEnd').value = e;
    $('cStart').max = $('cEnd').max = todayET();
    $('cmp').checked = !!prefs.cmp;
  }
  function initControls() {
    $('presets').innerHTML = PRESETS.map(([k, l]) => `<button data-p="${k}">${l}</button>`).join('');
    $('presets').addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      const p = b.dataset.p;
      if (p === 'custom') { const [s, en] = curRange(); prefs.start = s; prefs.end = en; prefs.preset = 'custom'; syncControls(); savePrefs(); return; }
      prefs.preset = p; prefs.grain = null; savePrefs(); syncControls(); load();
    });
    $('cApply').addEventListener('click', () => {
      let s = $('cStart').value, e = $('cEnd').value;
      if (!s || !e) return;
      if (s > e) [s, e] = [e, s];
      const t = todayET(); if (e > t) e = t;
      if (daysBetween(s, e) + 1 > 1500) s = addDays(e, -1499);
      prefs.start = s; prefs.end = e; prefs.preset = 'custom'; prefs.grain = null; savePrefs(); syncControls(); load();
    });
    $('grain').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; prefs.grain = b.dataset.g; savePrefs(); render(); });
    $('cmp').addEventListener('change', () => { prefs.cmp = $('cmp').checked; savePrefs(); render(); });
    $('refreshBtn').addEventListener('click', () => load(true));
    $('csvBtn').addEventListener('click', () => {
      if (!lastCsv) return;
      const csv = lastCsv.map((r) => r.map((v) => (/[",\n]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : v)).join(',')).join('\n');
      const a = document.createElement('a');
      const [s, en] = curRange();
      a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
      a.download = `mff_report_${s}_${en}_${prefs.grain || autoGrain(s, en)}.csv`;
      a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    });
    let rt; window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(render, 150); });
    syncControls();
  }

  function showApp(who) {
    $('gate').style.display = 'none';
    $('app').style.display = '';
    $('refreshBtn').style.display = '';
    $('who').textContent = who || '';
    initControls();
    load();
  }

  // ---------- boot ----------
  async function boot() {
    if (DEMO) { showApp('demo data'); return; }
    const ok = await window._REP_FB_READY;
    if (!ok) { $('gateMsg').textContent = 'Could not load Firebase. Check your connection or ad-blocker.'; return; }
    const auth = firebase.auth();
    let started = false;
    const signIn = async () => {
      try { await auth.signInWithPopup(new firebase.auth.GoogleAuthProvider()); }
      catch (e) { $('gateMsg').insertAdjacentHTML('beforeend', `<div style="color:var(--bad);margin-top:8px">${esc(e.message)}</div>`); }
    };
    auth.onAuthStateChanged((u) => {
      const admin = !!(u && ADMIN_EMAILS.includes((u.email || '').toLowerCase()));
      $('signOutBtn').style.display = u ? '' : 'none';
      if (admin) {
        if (started) return;
        started = true;
        callFn = firebase.app().functions('us-central1').httpsCallable('adminReport', { timeout: 130000 });
        showApp(u.email);
      } else {
        $('app').style.display = 'none'; $('gate').style.display = '';
        $('gateMsg').innerHTML = u
          ? `Signed in as ${esc(u.email)} — this page is for the site admin only.`
          : '<p style="margin:0 0 14px">Sign in with the admin Google account to view revenue, members and traffic.</p><button class="primary" id="gSignIn">Sign in with Google</button>';
        const b = $('gSignIn'); if (b) b.onclick = signIn;
      }
    });
    $('signOutBtn').onclick = () => auth.signOut().then(() => location.reload());
  }

  // ---------- demo data (layout testing only; never shown with real sign-in) ----------
  function demoData(start, end) {
    const len = daysBetween(start, end) + 1;
    const prevStart = addDays(start, -len), prevEnd = addDays(start, -1);
    const days = dayList(prevStart, end);
    let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const daily = {}, byPlan = {}, newPaid = {}, members = {}, signups = {}, totalAt = {}, ga = {}, qa = {};
    let mem = 20, tot = 900;
    const recent = [];
    for (const d of days) {
      const t = parse(d).getTime(); const season = d >= '2026-08-01' ? 1 : 0.25;
      const dau = Math.round((60 + 140 * season) * (0.8 + rnd() * 0.5) * ([0, 6].includes(parse(d).getUTCDay()) ? 1.35 : 1));
      ga[d] = { activeUsers: dau, newUsers: Math.round(dau * 0.45), sessions: Math.round(dau * 1.6), views: Math.round(dau * 6.2), engaged: Math.round(dau), engSec: dau * 160 };
      const su = Math.round(dau * 0.05 * rnd() * 2); signups[d] = su; tot += su; totalAt[d] = tot;
      const p = {}; let paid = 0;
      if (rnd() < 0.35 * season) { p.season = 2499 * (1 + (rnd() < 0.2)); paid++; }
      if (rnd() < 0.12) { p.monthly = 499; paid++; }
      if (rnd() < 0.05) { p.yearly = 6999; paid++; }
      if (rnd() < 0.1) p.monthly_renewal = 499 * Math.ceil(rnd() * 3);
      if (rnd() < 0.08) p.lineskip = 499;
      byPlan[d] = p; newPaid[d] = paid; mem += paid - (rnd() < 0.05 ? 1 : 0); members[d] = mem;
      const gross = Object.values(p).reduce((a, b) => a + b, 0);
      const fees = Math.round(gross * 0.035 + (gross ? 30 : 0));
      daily[d] = { gross, fees, net: gross - fees, refunds: 0, payments: Object.keys(p).length };
      for (const [k, v] of Object.entries(p)) recent.push({ at: t + 5 * 3600e3 + rnd() * 18 * 3600e3, amount: v, net: v - Math.round(v * 0.035 + 30), plan: k.replace('_renewal', ''), email: 'demo' + Math.floor(rnd() * 900) + '@example.com', desc: k.includes('renewal') ? 'Subscription update' : 'Checkout' });
      if (rnd() < 0.6) qa[d] = { free: Math.ceil(rnd() * 3), premium: rnd() < 0.4 ? 1 : 0 };
    }
    recent.sort((a, b) => b.at - a.at);
    const sumGa = (a, b, k) => dayList(a, b).reduce((s, d) => s + (ga[d] ? ga[d][k] : 0), 0);
    const tot2 = (a, b) => ({ activeUsers: Math.round(sumGa(a, b, 'activeUsers') * 0.42), newUsers: sumGa(a, b, 'newUsers'), sessions: sumGa(a, b, 'sessions'), screenPageViews: sumGa(a, b, 'views'), engagedSessions: sumGa(a, b, 'engaged'), userEngagementDuration: sumGa(a, b, 'engSec') });
    const sp = (name, c, p) => ({ name, cur: { sessions: c, activeUsers: Math.round(c * 0.7), eventCount: c, totalUsers: Math.round(c * 0.5) }, prev: { sessions: p, activeUsers: Math.round(p * 0.7), eventCount: p, totalUsers: Math.round(p * 0.5) } });
    return {
      generatedAt: Date.now(), tz: TZ, range: { start, end, prevStart, prevEnd, days: len },
      stripe: { ok: true, livemode: true, daily, byPlan, newPaid, members, recent: recent.slice(0, 25), snapshot: { subs: { monthly: 9, yearly: 4, other: 0 }, mrr: 9 * 499 + Math.round(4 * 6999 / 12), canceling: 2, pastDue: 0, seasonActive: mem - 13, seasonSold: mem - 10, lifetimeCheckout: 412300, payingNow: mem } },
      auth: { ok: true, total: tot, signups, totalAt, active1: 41, active7: 188, active30: 520, providers: { 'google.com': Math.round(tot * 0.8), password: Math.round(tot * 0.2) }, firstAccount: '2026-04-27' },
      premium: { ok: true, byPlan: { season: mem - 13, monthly: 9, yearly: 4 }, paid: mem, gifted: 6, total: mem + 6 },
      askjack: { ok: true, daily: qa, openInRange: 4 },
      ga4: {
        ok: true, daily: ga, totals: { cur: tot2(start, end), prev: tot2(prevStart, prevEnd) }, realtime: 7,
        channels: [sp('Direct', 3400, 3000), sp('Organic Social', 900, 700), sp('Organic Search', 600, 640), sp('Referral', 120, 90)],
        sources: [sp('(direct)', 3400, 3000), sp('google', 588, 600), sp('tiktok.com', 580, 420), sp('instagram.com', 68, 40), sp('chatgpt.com', 38, 12)],
        pages: [['/#trade', 2900], ['/#myteams', 1800], ['/#startsit', 1300], ['/#rankings', 790], ['/#compare', 420], ['/#mockdraft', 300]].map(([n, v]) => ({ name: n, views: v, users: Math.round(v * 0.3) })),
        devices: [{ name: 'mobile', users: 1100 }, { name: 'desktop', users: 240 }, { name: 'tablet', users: 30 }],
        events: [sp('page_view', 9000, 8000), sp('login', 60, 44), sp('sign_in_open', 140, 120), sp('premium_cta', 31, 12), sp('trade_calc', 2100, 1900), sp('session_start', 5200, 4700)],
      },
    };
  }

  boot();
})();
