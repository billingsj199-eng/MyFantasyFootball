/**
 * jm_eval_cfgs.js - score named weight configurations with the REAL site model.
 *
 * Boots the site headlessly (as jm_optimize.js does), then for every configuration in
 * the input file swaps the floor / ceiling weight tables (only the positions given;
 * the rest stay live), rebuilds the prospect data and scores the backtest:
 *
 *   all      Spearman(JM, NFL outcome score), every drafted player 2017-2024
 *   top100   the same among top-100 picks (where the pick itself says less)
 *   yr       n-weighted mean of the per-draft-year Spearman
 *   pen      tier penalty from jm_optimize.js (monotone hit rates, top-tier busts, late hits lost)
 *   top5     hit rate of the five highest grades per class
 *
 *   node scripts/jm_eval_cfgs.js --cfgs file.json [--out results.json] [--rows] [--port 8915]
 *   (--rows also stores every player's grade per configuration, for leave-one-year-out assembly)
 *
 * file.json: { "name": { "floor": { "RB": {dc: .45, ...} }, "ceiling": { "RB": {...} } }, ... }
 * A "live" row is always reported first. Nothing on disk is changed.
 */
const path = require('path'); const fs = require('fs'); const { spawn } = require('child_process');
const ROOT = path.resolve(__dirname, '..');
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 && args[i + 1] ? args[i + 1] : d; };
const PORT = parseInt(opt('--port', '8915'), 10);
const CFGS = JSON.parse(fs.readFileSync(opt('--cfgs'), 'utf8'));
const OUT = opt('--out', null);
const POSITIONS = ['QB', 'RB', 'WR', 'TE'];
const { chromium } = require(path.join(ROOT, 'tests', 'node_modules', 'playwright'));

function spearman(xs, ys) {
  const n = xs.length; if (n < 3) return 0;
  const rank = a => { const idx = a.map((v, i) => [v, i]).sort((p, q) => p[0] - q[0]); const r = new Array(n); let i = 0;
    while (i < n) { let j = i; while (j + 1 < n && idx[j + 1][0] === idx[i][0]) j++; const avg = (i + j) / 2 + 1; for (let k = i; k <= j; k++) r[idx[k][1]] = avg; i = j + 1; } return r; };
  const rx = rank(xs), ry = rank(ys);
  const mx = rx.reduce((s, v) => s + v, 0) / n, my = ry.reduce((s, v) => s + v, 0) / n;
  let num = 0, dx = 0, dy = 0;
  for (let i = 0; i < n; i++) { num += (rx[i] - mx) * (ry[i] - my); dx += (rx[i] - mx) ** 2; dy += (ry[i] - my) ** 2; }
  return dx && dy ? num / Math.sqrt(dx * dy) : 0;
}
function tierPenalty(rows, tiers) {
  const buckets = tiers.map(() => ({ n: 0, hit: 0, bust: 0, ppg: 0, ppgN: 0 }));
  const tierIdx = jm => { for (let i = 0; i < tiers.length; i++) if (jm >= tiers[i].min) return i; return tiers.length - 1; };
  let lateHits = 0, lateHitsLost = 0, top3 = 0, top3Bust = 0;
  rows.forEach(r => {
    const i = tierIdx(r.jm), b = buckets[i];
    b.n++; if (r.verdict === 'stud' || r.verdict === 'hit') b.hit++; if (r.verdict === 'bust') b.bust++;
    if (r.ppg > 0) { b.ppg += r.ppg; b.ppgN++; }
    if (i < 3) { top3++; if (r.verdict === 'bust') top3Bust++; }
    if (r.pick >= 65 && (r.verdict === 'stud' || r.verdict === 'hit')) { lateHits++; if (i >= tiers.length - 2) lateHitsLost++; }
  });
  const rate = b => b.n >= 5 ? b.hit / b.n : null, brate = b => b.n >= 5 ? b.bust / b.n : null, prate = b => b.ppgN >= 5 ? b.ppg / b.ppgN : null;
  let inv = 0, pinv = 0, binv = 0;
  for (let i = 0; i + 1 < buckets.length; i++) {
    const hi = buckets[i], lo = buckets[i + 1];
    if (rate(hi) != null && rate(lo) != null) { inv += Math.max(0, rate(lo) - rate(hi)); binv += Math.max(0, brate(hi) - brate(lo)); }
    if (prate(hi) != null && prate(lo) != null) pinv += Math.max(0, prate(lo) - prate(hi)) / 20;
  }
  return inv + pinv + binv + (top3 ? top3Bust / top3 : 0) + (lateHits ? lateHitsLost / lateHits : 0);
}
function metrics(rows, tiers) {
  const ev = rows.filter(r => r.verdict !== 'pending' && r.cs != null);
  const pk = r => (typeof r.pick === 'number' ? r.pick : 300);
  const top = ev.filter(r => pk(r) <= 100);
  let yr = 0, yn = 0; const byYr = {};
  ev.forEach(r => { (byYr[r.yr] = byYr[r.yr] || []).push(r); });
  let h5 = 0, n5 = 0;
  Object.values(byYr).forEach(g => {
    if (g.length >= 8) { yr += spearman(g.map(r => r.jm), g.map(r => r.cs)) * g.length; yn += g.length; }
    g.slice().sort((a, b) => b.jm - a.jm).slice(0, 5).forEach(r => { n5++; if (r.verdict === 'stud' || r.verdict === 'hit') h5++; });
  });
  return { n: ev.length, all: spearman(ev.map(r => r.jm), ev.map(r => r.cs)), top100: spearman(top.map(r => r.jm), top.map(r => r.cs)),
    yr: yn ? yr / yn : 0, pen: tierPenalty(ev, tiers), top5: n5 ? h5 / n5 : 0 };
}

(async () => {
  const hs = path.join(ROOT, 'tests', 'node_modules', 'http-server', 'bin', 'http-server');
  const server = spawn(process.execPath, [hs, ROOT, '-p', String(PORT), '-c-1', '--silent'], { stdio: 'ignore' });
  for (let i = 0; i < 40; i++) { try { const r = await fetch(`http://127.0.0.1:${PORT}/index.html`); if (r.ok) break; } catch (e) {} await new Promise(r => setTimeout(r, 500)); }
  let browser; try { browser = await chromium.launch({ headless: true }); } catch (e) { browser = await chromium.launch({ headless: true, channel: 'msedge' }); }
  const ctx = await browser.newContext({ serviceWorkers: 'block' }); const page = await ctx.newPage();
  await page.addInitScript(() => { try { localStorage.setItem('mff_seen_intro', '1'); } catch (e) {} });
  page.on('pageerror', e => console.log('  [pageerror]', String(e).slice(0, 160)));
  await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => typeof window.buildProspectData === 'function' && window._POS_TIERS && window._JM_WEIGHTS && window._JM_CEILING_WEIGHTS, null, { timeout: 120000 });
  await page.evaluate(async () => { const btn = document.querySelector('button.nav-btn[data-page="prospect"]'); if (btn) btn.click(); const w = []; for (const f of ['_ensureCollegeStatsData', '_ensureBacktestOutcomes', '_ensureProspectStats', '_ensurePffData']) if (window[f]) w.push(window[f]()); await Promise.all(w); });
  await page.waitForFunction(() => typeof BACKTEST_OUTCOMES !== 'undefined' && typeof COLLEGE_STATS !== 'undefined', null, { timeout: 120000 });
  await new Promise(r => setTimeout(r, 4000));
  const tiers = await page.evaluate(() => {
    window.__live = { floor: JSON.parse(JSON.stringify(window._JM_WEIGHTS)), ceiling: JSON.parse(JSON.stringify(window._JM_CEILING_WEIGHTS)) };
    const nrm = s => String(s || '').toLowerCase().replace(/(jr\.?|sr\.?|ii|iii|iv|v)/g, '').replace(/[^a-z0-9]/g, '');
    window.__run = (cfg) => {
      ['floor', 'ceiling'].forEach(track => {
        const root = track === 'floor' ? window._JM_WEIGHTS : window._JM_CEILING_WEIGHTS;
        Object.keys(window.__live[track]).forEach(pos => {
          const src = (cfg && cfg[track] && cfg[track][pos]) || window.__live[track][pos];
          const t = root[pos]; Object.keys(t).forEach(k => delete t[k]); Object.keys(src).forEach(k => { t[k] = src[k]; });
        });
      });
      if (window._jmClearCache) window._jmClearCache();
      const data = window.buildProspectData();
      const byName = {}, byNrm = {};
      data.forEach(p => { if (p.jm != null && !p.lowConfidence) { byName[p.name] = p; byNrm[nrm(p.name)] = p; } });
      const out = [];
      Object.keys(BACKTEST_OUTCOMES).forEach(yr => BACKTEST_OUTCOMES[yr].forEach(r => {
        const p = byName[r.n] || byNrm[nrm(r.n)]; if (!p) return;
        out.push({ n: r.n, pos: r.pos, jm: p.jm, verdict: r.verdict, cs: r.curveScore, pick: r.pick, yr: parseInt(yr), ppg: r.avgPpg });
      }));
      return out;
    };
    return Object.fromEntries(Object.keys(window._POS_TIERS).map(p => [p, window._POS_TIERS[p].map(t => ({ label: t.label, min: t.min }))]));
  });
  const results = {};
  const names = ['live', ...Object.keys(CFGS)];
  for (const name of names) {
    const rows = await page.evaluate(c => window.__run(c), name === 'live' ? null : CFGS[name]);
    results[name] = {};
    POSITIONS.forEach(pos => { results[name][pos] = metrics(rows.filter(r => r.pos === pos), tiers[pos]); });
    if (args.includes('--rows')) results[name]._rows = rows.map(r => [r.n, r.pos, r.yr, r.jm, r.cs, r.verdict, r.pick]);
  }
  await page.evaluate(() => window.__run(null));
  POSITIONS.forEach(pos => {
    const touched = names.filter(nm => nm === 'live' || (CFGS[nm].floor && CFGS[nm].floor[pos]) || (CFGS[nm].ceiling && CFGS[nm].ceiling[pos]));
    if (touched.length < 2) return;
    console.log(`\n=== ${pos} (n ${results.live[pos].n}) ===   ${''.padEnd(30)}   all  top100     yr    pen  top5`);
    touched.forEach(nm => { const m = results[nm][pos];
      console.log('  ' + nm.padEnd(40) + [m.all, m.top100, m.yr, m.pen, m.top5].map(v => v.toFixed(3).padStart(7)).join('')); });
  });
  if (OUT) fs.writeFileSync(OUT, JSON.stringify(results, null, 1));
  await browser.close(); server.kill();
})().catch(e => { console.error(e); process.exit(1); });
