/**
 * a16_jm_eval.js - RESEARCH ONLY (A16, 2026-11-24). Re-scores past prospects' JM with a PROJECTED pick swapped in
 * for the real one, for every scored prospect in a draft class (drafted or not), so the A15 kNN backtest can be
 * rerun on pre-draft information.
 *
 * Same mechanism as the site repo's scripts/jm_projpick_eval.js (which only returns the drafted BACKTEST_OUTCOMES
 * players): boots the site headlessly from the repo checkout, sets COMBINE_DATA[name].draft in memory, rebuilds the
 * prospect data, restores. Nothing on disk in the site repo is changed; the only file written is --out.
 *
 *   node a16_jm_eval.js --scenarios s.json --out rows.json [--repo <site repo>] [--port 8931]
 *
 * s.json: { "scenario": { "picks": { "Name|2021": 34, "Other|2021": "U" }, "strip": ["ras", "forty"], "stripYears": [2017, 2025] } }
 *         (names = site names; strip removes those COMBINE_DATA fields in memory for the listed draft years, restored after)
 * out:    { "real": [[name, pos, draftYr, jm, usedPick, lowConfidence, storedDraft], ...], "scenario": [...] }
 */
const path = require('path'); const fs = require('fs'); const { spawn } = require('child_process');
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 && args[i + 1] ? args[i + 1] : d; };
const ROOT = path.resolve(opt('--repo', 'E:\\MyFantasyFootball\\MyFantasyFootball Files'));
const PORT = parseInt(opt('--port', '8931'), 10);
const SCEN = JSON.parse(fs.readFileSync(opt('--scenarios'), 'utf8'));
const OUT = opt('--out');
const Y0 = 2017, Y1 = 2025;
const { chromium } = require(path.join(ROOT, 'tests', 'node_modules', 'playwright'));

(async () => {
  const hs = path.join(ROOT, 'tests', 'node_modules', 'http-server', 'bin', 'http-server');
  const server = spawn(process.execPath, [hs, ROOT, '-p', String(PORT), '-c-1', '--silent'], { stdio: 'ignore' });
  for (let i = 0; i < 40; i++) { try { const r = await fetch(`http://127.0.0.1:${PORT}/index.html`); if (r.ok) break; } catch (e) {} await new Promise(r => setTimeout(r, 500)); }
  let browser; try { browser = await chromium.launch({ headless: true }); } catch (e) { browser = await chromium.launch({ headless: true, channel: 'msedge' }); }
  try {
    const ctx = await browser.newContext({ serviceWorkers: 'block' }); const page = await ctx.newPage();
    await page.addInitScript(() => { try { localStorage.setItem('mff_seen_intro', '1'); } catch (e) {} });
    page.on('pageerror', e => console.log('  [pageerror]', String(e).slice(0, 160)));
    await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => typeof window.buildProspectData === 'function' && window._POS_TIERS && window._JM_WEIGHTS && window._JM_CEILING_WEIGHTS, null, { timeout: 120000 });
    await page.evaluate(async () => { const btn = document.querySelector('button.nav-btn[data-page="prospect"]'); if (btn) btn.click(); const w = []; for (const f of ['_ensureCollegeStatsData', '_ensureBacktestOutcomes', '_ensureProspectStats', '_ensurePffData']) if (window[f]) w.push(window[f]()); await Promise.all(w); });
    await page.waitForFunction(() => typeof BACKTEST_OUTCOMES !== 'undefined' && typeof COLLEGE_STATS !== 'undefined', null, { timeout: 120000 });
    await new Promise(r => setTimeout(r, 4000));
    await page.evaluate(([y0, y1]) => {
      window.__realDraft = {};   // shipped value of every key a scenario touches
      const restorePicks = () => Object.keys(window.__realDraft).forEach(n => { COMBINE_DATA[n].draft = window.__realDraft[n]; });
      window.__run = (cfg) => {
        restorePicks();
        const picks = (cfg && cfg.picks) || {};
        let applied = 0; const missing = []; const yrFix = [];
        Object.keys(picks).forEach(key => {
          const n = key.slice(0, key.lastIndexOf('|'));
          if (!COMBINE_DATA[n]) { missing.push(n); return; }
          if (!(n in window.__realDraft)) window.__realDraft[n] = COMBINE_DATA[n].draft;
          COMBINE_DATA[n].draft = picks[key]; applied++;
          // a COMBINE_DATA entry with no stored pick can carry a placeholder yr (e.g. 2000); once it has a pick the site
          // reads the draft year from cb.yr, so hold cb.yr at the prospect's real class for the rebuild
          const ky = parseInt(key.slice(key.lastIndexOf('|') + 1));
          if (ky && COMBINE_DATA[n].yr !== ky) { yrFix.push([n, COMBINE_DATA[n].yr]); COMBINE_DATA[n].yr = ky; }
        });
        // strip: remove combine-testing fields (in memory) for every COMBINE_DATA entry in the listed draft years
        const stripped = [];
        if (cfg && cfg.strip && cfg.stripYears) {
          Object.keys(COMBINE_DATA).forEach(n => {
            const cb = COMBINE_DATA[n]; if (!cb || cb.yr < cfg.stripYears[0] || cb.yr > cfg.stripYears[1]) return;
            cfg.strip.forEach(f => { if (cb[f] !== undefined) { stripped.push([n, f, cb[f]]); delete cb[f]; } });
          });
        }
        if (window._jmClearCache) window._jmClearCache();
        const data = window.buildProspectData();
        stripped.forEach(([n, f, v]) => { COMBINE_DATA[n][f] = v; });
        yrFix.forEach(([n, y]) => { COMBINE_DATA[n].yr = y; });
        const out = [];
        data.forEach(p => {
          if (p.jm == null || !p.draftYr || p.draftYr < y0 || p.draftYr > y1) return;
          const cb = COMBINE_DATA[p.name];
          out.push([p.name, p.pos, p.draftYr, p.jm, p.dr == null ? null : p.dr, p.lowConfidence ? 1 : 0, cb ? (window.__realDraft[p.name] !== undefined ? window.__realDraft[p.name] : cb.draft) : null]);
        });
        restorePicks();
        if (window._jmClearCache) window._jmClearCache();
        return { rows: out, applied, nStripped: stripped.length, missing: missing.slice(0, 20), nMissing: missing.length };
      };
    }, [Y0, Y1]);
    const sig = rows => JSON.stringify(rows.map(r => [r[0], r[2], r[3]]));
    // late async data (Firestore bios / DC edits) can move a few QB grades up to a minute after boot:
    // wait for 8 identical builds in a row, 4 s apart
    let prev = sig((await page.evaluate(() => window.__run(null))).rows), same = 0, stable = false;
    for (let i = 0; i < 40 && !stable; i++) {
      await new Promise(r => setTimeout(r, 4000));
      const cur = sig((await page.evaluate(() => window.__run(null))).rows);
      same = cur === prev ? same + 1 : 0; prev = cur; stable = same >= 8;
    }
    console.log(stable ? 'live JM stable' : 'WARNING: live JM still moving after warm-up');
    const results = {};
    for (const name of ['real', ...Object.keys(SCEN)]) {
      const res = await page.evaluate(c => window.__run(c), name === 'real' ? null : SCEN[name]);
      results[name] = res.rows;
      console.log(`${name.padEnd(28)} rows ${res.rows.length}  picks applied ${res.applied}  fields stripped ${res.nStripped}  missing ${res.nMissing}${res.nMissing ? ' e.g. ' + res.missing.slice(0, 5).join(', ') : ''}`);
    }
    const after = await page.evaluate(() => window.__run(null));
    if (sig(after.rows) !== sig(results.real)) {
      const was = {}; results.real.forEach(r => { was[r[0] + '|' + r[2]] = r[3]; });
      const moved = after.rows.filter(r => was[r[0] + '|' + r[2]] !== r[3]).map(r => `${r[0]} ${was[r[0] + '|' + r[2]]}->${r[3]}`);
      console.log(`WARNING: live JM changed during the run (${moved.length} of ${after.rows.length}): ${moved.slice(0, 12).join(', ')}`);
      results.real_after = after.rows;
    }
    else console.log('real JM identical before and after the scenarios (picks restored)');
    fs.writeFileSync(OUT, JSON.stringify(results));
  } finally {
    await browser.close(); server.kill();
  }
})().catch(e => { console.error(e); process.exit(1); });
