/**
 * jm_projpick_eval.js - score the JM backtest with PROJECTED picks swapped in for the real ones.
 *
 * Boots the site headlessly (same as scripts/jm_eval_cfgs.js), then for every scenario:
 *   - sets COMBINE_DATA[name].draft to the scenario's pick for each backtest player it lists
 *     (number, or 'U' = off every board); players not listed keep their real pick
 *   - optionally swaps floor / ceiling weight tables (same format as jm_eval_cfgs.js)
 *   - optionally scales the draft-capital weight (dcScale k: dc x k in every table, rest re-spread)
 *   - rebuilds the prospect data and returns one row per backtest player
 * Real picks and weights are restored after every scenario. Nothing on disk is changed.
 * Used by scripts/jm_projpick_study.py (November projected picks) and, with an empty scenario
 * file, to dump the live JM rows that scripts/jm_competition_study.py reads.
 *
 *   node scripts/jm_projpick_eval.js --scenarios s.json --out rows.json [--repo <checkout with tests/node_modules>] [--port 8917]
 *
 * s.json: { "name": { "picks": { "Name|2021": 34, "Other|2021": "U" }, "floor": {...}, "ceiling": {...}, "dcScale": 0.5 } }
 * out:    { "name": [[n, pos, yr, jm, realPick, usedPick], ...] }
 */
const path = require('path'); const fs = require('fs'); const { spawn } = require('child_process');
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 && args[i + 1] ? args[i + 1] : d; };
const ROOT = path.resolve(opt('--repo', path.join(__dirname, '..')));
const PORT = parseInt(opt('--port', '8917'), 10);
const SCEN = JSON.parse(fs.readFileSync(opt('--scenarios'), 'utf8'));
const OUT = opt('--out');
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
  await page.waitForFunction(() => typeof window.buildProspectData === 'function' && window._POS_TIERS && window._JM_WEIGHTS && window._JM_CEILING_WEIGHTS, null, { timeout: 120000 });
  await page.evaluate(async () => { const btn = document.querySelector('button.nav-btn[data-page="prospect"]'); if (btn) btn.click(); const w = []; for (const f of ['_ensureCollegeStatsData', '_ensureBacktestOutcomes', '_ensureProspectStats', '_ensurePffData']) if (window[f]) w.push(window[f]()); await Promise.all(w); });
  await page.waitForFunction(() => typeof BACKTEST_OUTCOMES !== 'undefined' && typeof COLLEGE_STATS !== 'undefined', null, { timeout: 120000 });
  await new Promise(r => setTimeout(r, 4000));
  await page.evaluate(() => {
    window.__live = { floor: JSON.parse(JSON.stringify(window._JM_WEIGHTS)), ceiling: JSON.parse(JSON.stringify(window._JM_CEILING_WEIGHTS)) };
    const nrm = s => String(s || '').toLowerCase().replace(/(jr\.?|sr\.?|ii|iii|iv|v)/g, '').replace(/[^a-z0-9]/g, '');
    // Real picks as stored, so every scenario starts from (and returns to) the shipped data.
    window.__realDraft = {};
    Object.keys(BACKTEST_OUTCOMES).forEach(yr => BACKTEST_OUTCOMES[yr].forEach(r => {
      const cb = COMBINE_DATA[r.n]; if (cb) window.__realDraft[r.n] = cb.draft;
    }));
    const setWeights = cfg => ['floor', 'ceiling'].forEach(track => {
      const root = track === 'floor' ? window._JM_WEIGHTS : window._JM_CEILING_WEIGHTS;
      Object.keys(window.__live[track]).forEach(pos => {
        const src = (cfg && cfg[track] && cfg[track][pos]) || window.__live[track][pos];
        const t = root[pos]; Object.keys(t).forEach(k => delete t[k]); Object.keys(src).forEach(k => { t[k] = src[k]; });
      });
    });
    const restorePicks = () => Object.keys(window.__realDraft).forEach(n => { COMBINE_DATA[n].draft = window.__realDraft[n]; });
    // dcScale: multiply the draft-capital weight by k in every floor / ceiling table, re-spread the rest.
    const scaleDc = k => [window._JM_WEIGHTS, window._JM_CEILING_WEIGHTS].forEach(root => Object.values(root).forEach(t => {
      if (!t || t.dc == null) return;
      const dc = t.dc, rest = 1 - dc, ndc = dc * k;
      Object.keys(t).forEach(key => { if (key !== 'dc' && rest > 0) t[key] = t[key] * (1 - ndc) / rest; });
      t.dc = ndc;
    }));
    window.__run = (cfg) => {
      restorePicks(); setWeights(cfg);
      if (cfg && cfg.dcScale != null) scaleDc(cfg.dcScale);
      const picks = (cfg && cfg.picks) || {};
      let applied = 0, missing = [];
      Object.keys(picks).forEach(key => {
        const n = key.slice(0, key.lastIndexOf('|'));
        if (!COMBINE_DATA[n]) { missing.push(n); return; }
        // remember the shipped value under the SAME key we change (site names can differ from
        // BACKTEST_OUTCOMES names, e.g. "Brian Thomas Jr." vs "Brian Thomas")
        if (!(n in window.__realDraft)) window.__realDraft[n] = COMBINE_DATA[n].draft;
        COMBINE_DATA[n].draft = picks[key]; applied++;
      });
      if (window._jmClearCache) window._jmClearCache();
      const data = window.buildProspectData();
      const byName = {}, byNrm = {};
      data.forEach(p => { if (p.jm != null && !p.lowConfidence) { byName[p.name] = p; byNrm[nrm(p.name)] = p; } });
      const out = [];
      Object.keys(BACKTEST_OUTCOMES).forEach(yr => BACKTEST_OUTCOMES[yr].forEach(r => {
        const p = byName[r.n] || byNrm[nrm(r.n)]; if (!p) return;
        out.push([p.name, r.pos, parseInt(yr), p.jm, r.pick, p.dr]);
      }));
      restorePicks(); setWeights(null);
      if (window._jmClearCache) window._jmClearCache();
      return { rows: out, applied, missing: missing.slice(0, 20), nMissing: missing.length };
    };
  });
  // Late async data (Firestore bios / DC edits, lazy chunks) can still land after the fixed wait and
  // move a few JM grades (seen 2026-11-18: 5-11 QBs). Rebuild until two builds in a row match.
  const sig = rows => JSON.stringify(rows.map(r => [r[0], r[2], r[3]]));
  let prev = sig((await page.evaluate(() => window.__run(null))).rows), stable = false;
  for (let i = 0; i < 12 && !stable; i++) {
    await new Promise(r => setTimeout(r, 3000));
    const cur = sig((await page.evaluate(() => window.__run(null))).rows);
    stable = cur === prev; prev = cur;
  }
  console.log(stable ? 'live JM stable' : 'WARNING: live JM still moving after warm-up');
  const results = {};
  for (const name of ['real', ...Object.keys(SCEN)]) {
    const res = await page.evaluate(c => window.__run(c), name === 'real' ? null : SCEN[name]);
    results[name] = res.rows;
    console.log(`${name.padEnd(28)} rows ${res.rows.length}  picks applied ${res.applied}  missing ${res.nMissing}${res.nMissing ? ' e.g. ' + res.missing.slice(0, 5).join(', ') : ''}`);
  }
  const after = await page.evaluate(() => window.__run(null));
  if (sig(after.rows) !== sig(results.real)) {
    const was = {}; results.real.forEach(r => { was[r[0] + '|' + r[2]] = r[3]; });
    const moved = after.rows.filter(r => was[r[0] + '|' + r[2]] !== r[3]).map(r => `${r[0]} ${was[r[0] + '|' + r[2]]}->${r[3]}`);
    console.log(`WARNING: live JM changed during the run (${moved.length}): ${moved.slice(0, 8).join(', ')}`);
  }
  fs.writeFileSync(OUT, JSON.stringify(results));
  await browser.close(); server.kill();
})().catch(e => { console.error(e); process.exit(1); });
