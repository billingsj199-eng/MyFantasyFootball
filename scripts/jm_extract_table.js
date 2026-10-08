/**
 * jm_extract_table.js - dump the JM modelling table from the REAL site code.
 *
 * Boots the site headlessly (same as jm_optimize.js), runs buildProspectData(), and
 * writes one row per backtest player (BACKTEST_OUTCOMES, verdict != pending) with:
 * raw inputs, every component score, floor / ceiling / final JM, the additive
 * adjustments, and the NFL outcome. Offline analysis (scripts/jm_model_lab.py) reads it.
 *
 *   node scripts/jm_extract_table.js [--out scripts/jm_table.json] [--port 8913]
 */
const path = require('path'); const fs = require('fs'); const { spawn } = require('child_process');
const ROOT = path.resolve(__dirname, '..');
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 && args[i + 1] ? args[i + 1] : d; };
const PORT = parseInt(opt('--port', '8913'), 10);
const OUT = opt('--out', path.join(ROOT, 'scripts', 'jm_table.json'));
const { chromium } = require(path.join(ROOT, 'tests', 'node_modules', 'playwright'));
(async () => {
  const hs = path.join(ROOT, 'tests', 'node_modules', 'http-server', 'bin', 'http-server');
  const server = spawn(process.execPath, [hs, ROOT, '-p', String(PORT), '-c-1', '--silent'], { stdio: 'ignore' });
  for (let i = 0; i < 40; i++) { try { const r = await fetch(`http://127.0.0.1:${PORT}/index.html`); if (r.ok) break; } catch (e) {} await new Promise(r => setTimeout(r, 500)); }
  let browser; try { browser = await chromium.launch({ headless: true }); } catch (e) { browser = await chromium.launch({ headless: true, channel: 'msedge' }); }
  const ctx = await browser.newContext({ serviceWorkers: 'block' }); const page = await ctx.newPage();
  await page.addInitScript(() => { try { localStorage.setItem('mff_seen_intro', '1'); } catch (e) {} });
  page.on('pageerror', e => console.log('  [pageerror]', String(e).slice(0, 160)));
  await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => typeof window.buildProspectData === 'function' && window._POS_TIERS && window._JM_WEIGHTS, null, { timeout: 120000 });
  await page.evaluate(async () => { const btn = document.querySelector('button.nav-btn[data-page="prospect"]'); if (btn) btn.click(); const w = []; for (const f of ['_ensureCollegeStatsData', '_ensureBacktestOutcomes', '_ensureProspectStats', '_ensurePffData']) if (window[f]) w.push(window[f]()); await Promise.all(w); });
  await page.waitForFunction(() => typeof BACKTEST_OUTCOMES !== 'undefined' && typeof COLLEGE_STATS !== 'undefined', null, { timeout: 120000 });
  await new Promise(r => setTimeout(r, 4000));
  const out = await page.evaluate(() => {
    if (window._jmClearCache) window._jmClearCache();
    const data = window.buildProspectData();
    const nrm = s => String(s || '').toLowerCase().replace(/(jr\.?|sr\.?|ii|iii|iv|v)/g, '').replace(/[^a-z0-9]/g, '');
    const byName = {}, byNrm = {};
    data.forEach(p => { if (p.jm != null) { byName[p.name] = p; byNrm[nrm(p.name)] = p; } });
    const flat = p => { const o = {}; Object.keys(p).forEach(k => { const v = p[k]; if (v == null || typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean') o[k] = v; }); o.comps = p.compScores || null; return o; };
    const rows = [];
    Object.keys(BACKTEST_OUTCOMES).forEach(yr => BACKTEST_OUTCOMES[yr].forEach(r => {
      const p = byName[r.n] || byNrm[nrm(r.n)]; if (!p) return;
      rows.push(Object.assign(flat(p), { o_verdict: r.verdict, o_cs: r.curveScore, o_pick: r.pick, o_yr: parseInt(yr), o_ppg: r.avgPpg, o_regen: r.regen || null, o_raw: r }));
    }));
    const pool = data.filter(p => p.jm != null).map(flat);
    return { rows, pool, weights: { floor: window._JM_WEIGHTS, ceiling: window._JM_CEILING_WEIGHTS }, tiers: Object.fromEntries(Object.keys(window._POS_TIERS).map(k => [k, window._POS_TIERS[k].map(t => ({ label: t.label, min: t.min }))])) };
  });
  fs.writeFileSync(OUT, JSON.stringify(out));
  console.log('rows', out.rows.length, 'pool', out.pool.length, '->', OUT);
  await browser.close(); server.kill();
})().catch(e => { console.error(e); process.exit(1); });
