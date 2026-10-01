/**
 * jm_optimize.js — offline JM prospect-model weight tuner with leave-one-year-out validation.
 *
 * Drives the REAL site in headless Chromium (Playwright from tests/node_modules) so every
 * candidate weight set is scored by the production calcJM (stretch, day-3 shrink, bust /
 * sleeper adjustments, DC curves, class bonus...) — nothing is re-implemented here.
 *
 *   node scripts/jm_optimize.js [--pos QB,RB,WR,TE] [--passes 2] [--no-loyo] [--no-provisional] [--out file.json]
 *
 * Per position: coordinate descent over the non-zero JM_WEIGHTS (floor) and
 * JM_CEILING_WEIGHTS keys (delta ±0.03 then ±0.015, others renormalised so the
 * track sums to 1). Objective on the backtest players 2017-2024, judged on the GRADED
 * career outcome (Oct 1 2026 - no stud / hit / bust labels):
 *
 *   outcome = career grade 0-100 from data/jm_career_grades.js (window.JM_CAREER_GRADES,
 *             built by scripts/build_outcome_grades.py): best four of the first six NFL
 *             seasons weighted 40/30/20/10, so elite seasons and consistency count and one
 *             big volume year tops out at 40. Classes with fewer than four seasons are
 *             provisional; drop them with --no-provisional.
 *
 *   loss = (1 - spearman(jm, career grade))          continuous outcome agreement
 *        + 0.5 * tierPenalty(current POS_TIERS)       tiers out of order by average career
 *                                                     grade, empty careers (grade < 10) in
 *                                                     the top three tiers, strong late-pick
 *                                                     careers (pick 65+, grade 45+) lost to
 *                                                     the bottom two tiers
 *
 * Rows in the results file keep a `verdict` field for the companion scripts
 * (jm_segment_analysis.py, jm_feature_discovery.py, jm_sos_analysis.py): it is now a BAND of
 * the career grade (stud 70+, hit 45+, contributor 20+, bust below), never "pending", and
 * `cs` is the career grade. The stored BACKTEST_OUTCOMES verdict and curve score ride along
 * as verdictOld / csOld for reference only.
 *
 * Validation: for each draft year Y the descent runs on the other years and the
 * tuned vs deployed weights are compared on Y alone (spearman + tier penalty).
 * Pooled out-of-year spearman is the ship/no-ship number. A final full-sample
 * fit is reported for application. Nothing on disk is changed by this script.
 *
 * All four positions are perturbed in the same rebuild (their JM scores are
 * independent), so one buildProspectData() call scores one candidate per position.
 */
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const PORT = 8907;
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const POSITIONS = (opt('--pos', 'QB,RB,WR,TE')).split(',');
const PASSES = parseInt(opt('--passes', '2'), 10);
const LOYO = !args.includes('--no-loyo');
const EXP = args.includes('--exp');
const NO_REGEN = args.includes('--no-regen');   // legacy flag: outcomes no longer come from the regenerated verdicts, so this is a no-op
const NO_PROV = args.includes('--no-provisional');   // drop classes with fewer than four NFL seasons played out
const OUT = opt('--out', path.join(ROOT, 'scripts', `jm_optimize_results_${new Date().toISOString().slice(0, 10)}.json`));
const DELTAS = [0.03, -0.03, 0.015, -0.015];
const MIN_KEY_W = 0.02;   // only perturb keys carrying real weight

const { chromium } = require(path.join(ROOT, 'tests', 'node_modules', 'playwright'));

// ------------------------------------------------------------------ stats
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

// tiers: [{label,min}] high → low. rows: evaluated rows for one position.
function tierPenalty(rows, tiers) {
  // Graded version: rows carry cs = career grade (0-100).
  const buckets = tiers.map(() => ({ n: 0, sum: 0 }));
  const tierIdx = jm => { for (let i = 0; i < tiers.length; i++) if (jm >= tiers[i].min) return i; return tiers.length - 1; };
  let lateStrong = 0, lateLostN = 0, top3 = 0, top3EmptyN = 0;
  rows.forEach(r => {
    const i = tierIdx(r.jm), b = buckets[i];
    b.n++; b.sum += r.cs;
    if (i < 3) { top3++; if (r.cs < 10) top3EmptyN++; }
    if (r.pick >= 65 && r.cs >= 45) { lateStrong++; if (i >= tiers.length - 2) lateLostN++; }
  });
  const avg = b => b.n >= 5 ? b.sum / b.n : null;
  let inv = 0;
  for (let i = 0; i + 1 < buckets.length; i++) {
    const hi = avg(buckets[i]), lo = avg(buckets[i + 1]);
    if (hi != null && lo != null) inv += Math.max(0, lo - hi) / 100;   // lower tier out-averaging the tier above it
  }
  const top3Empty = top3 ? top3EmptyN / top3 : 0;
  const lateLost = lateStrong ? lateLostN / lateStrong : 0;
  // top3BustRate kept as an alias so older readers of the results JSON still find a number
  return { pen: inv + top3Empty + lateLost, inv, top3Empty, top3BustRate: top3Empty, lateLost };
}

function score(rows, tiers) {
  const ev = rows.filter(r => r.cs != null);
  if (ev.length < 20) return { loss: 9, n: ev.length, rho: 0, pen: 9 };
  const rho = spearman(ev.map(r => r.jm), ev.map(r => r.cs));
  const tp = tierPenalty(ev, tiers);
  return { loss: (1 - rho) + 0.5 * tp.pen, n: ev.length, rho, pen: tp.pen, ...tp };
}

function renorm(w, key, delta) {
  const out = { ...w };
  const cur = out[key] || 0;
  const nv = Math.max(0, cur + delta);
  const otherSum = Object.keys(out).filter(k => k !== key).reduce((s, k) => s + out[k], 0);
  const target = 1 - nv;
  if (otherSum <= 0 || target <= 0) return null;
  Object.keys(out).forEach(k => { if (k !== key) out[k] = out[k] * target / otherSum; });
  out[key] = nv;
  return out;
}

// ------------------------------------------------------------------ page driver
async function boot() {
  const hs = path.join(ROOT, 'tests', 'node_modules', 'http-server', 'bin', 'http-server');
  const server = spawn(process.execPath, [hs, ROOT, '-p', String(PORT), '-c-1', '--silent'], { stdio: 'ignore' });
  for (let i = 0; i < 40; i++) {
    try { const r = await fetch(`http://127.0.0.1:${PORT}/index.html`); if (r.ok) break; } catch (e) {}
    await new Promise(r => setTimeout(r, 500));
    if (i === 39) throw new Error('local http-server did not come up on port ' + PORT);
  }
  let browser;
  try { browser = await chromium.launch({ headless: true }); }
  catch (e) { console.log('bundled chromium failed (' + String(e).split('\n')[0] + ') - trying Edge'); browser = await chromium.launch({ headless: true, channel: 'msedge' }); }
  const ctx = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1400, height: 900 } });
  const page = await ctx.newPage();
  await page.addInitScript(() => { try { localStorage.setItem('mff_seen_intro', '1'); } catch (e) {} });
  page.on('pageerror', e => console.log('  [pageerror]', String(e).slice(0, 160)));
  await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'domcontentloaded' });
  try {
    await page.waitForFunction(() => typeof window.buildProspectData === 'function' && window._POS_TIERS && window._JM_WEIGHTS && window._JM_CEILING_WEIGHTS, null, { timeout: 120000 });
  } catch (e) {
    const st = await page.evaluate(() => ({ build: typeof window.buildProspectData, tiers: !!window._POS_TIERS, w: !!window._JM_WEIGHTS, cw: !!window._JM_CEILING_WEIGHTS, D: typeof D }));
    throw new Error('site hooks missing after 120s: ' + JSON.stringify(st));
  }
  await page.evaluate(async () => {
    const btn = document.querySelector('button.nav-btn[data-page="prospect"]'); if (btn) btn.click();
    const waits = [];
    if (window._ensureCollegeStatsData) waits.push(window._ensureCollegeStatsData());
    if (window._ensureBacktestOutcomes) waits.push(window._ensureBacktestOutcomes());
    if (window._ensureProspectStats) waits.push(window._ensureProspectStats());
    if (window._ensurePffData) waits.push(window._ensurePffData());
    await Promise.all(waits);
  });
  await page.waitForFunction(() => typeof BACKTEST_OUTCOMES !== 'undefined' && typeof COLLEGE_STATS !== 'undefined', null, { timeout: 120000 });
  await new Promise(r => setTimeout(r, 3000));
  await page.evaluate((noProv) => {
    window.__jmNoProv = noProv;
    window.__jmApply = (cfg) => {
      ['floor', 'ceiling'].forEach(track => {
        const root = track === 'floor' ? window._JM_WEIGHTS : window._JM_CEILING_WEIGHTS;
        Object.keys(cfg[track] || {}).forEach(pos => {
          const t = root[pos]; if (!t) return;
          Object.keys(t).forEach(k => delete t[k]);
          Object.keys(cfg[track][pos]).forEach(k => { t[k] = cfg[track][pos][k]; });
        });
      });
      if (window.__jmCfgOnly) return null;
      window._JM_EXP = cfg.exp || null;
      if (window._jmClearCache) window._jmClearCache();
      return window.__jmCollect(window.buildProspectData());
    };
    // Own join of BACKTEST_OUTCOMES x prospect records (no dependency on the admin
    // backtest page's _btCollect, which lives in a closure that may not be exposed).
    const nrm = s => String(s || '').toLowerCase().replace(/(jr\.?|sr\.?|ii|iii|iv|v)/g, '').replace(/[^a-z0-9]/g, '');
    window.__jmCollect = (data, withComps) => {
      const CG = window.JM_CAREER_GRADES;
      if (!CG) throw new Error('window.JM_CAREER_GRADES missing - run scripts/build_outcome_grades.py --js data/jm_career_grades.js --bump');
      const byName = {}, byNrm = {};
      data.forEach(p => { if (p.jm != null && !p.lowConfidence) { byName[p.name] = p; byNrm[nrm(p.name)] = p; } });
      const out = [];
      Object.keys(BACKTEST_OUTCOMES).forEach(yr => BACKTEST_OUTCOMES[yr].forEach(r => {
        const p = byName[r.n] || byNrm[nrm(r.n)]; if (!p) return;
        // graded career outcome, keyed by the prospect-model name
        const g = CG[p.name + '|' + yr] || CG[r.n + '|' + yr];
        if (!g) return;
        if (window.__jmNoProv && g[3]) return;       // --no-provisional
        const band = g[0] >= 70 ? 'stud' : g[0] >= 45 ? 'hit' : g[0] >= 20 ? 'contributor' : 'bust';
        const row = { n: r.n, pos: r.pos, jm: p.jm, verdict: band, cs: g[0], elite: g[1], starter: g[2], prov: !!g[3],
          pick: r.pick, yr: parseInt(yr), ppg: r.avgPpg, verdictOld: r.verdict, csOld: r.curveScore };
        if (withComps) row.comps = p.compScores || null;
        out.push(row);
      }));
      return out;
    };
    window.__jmBaselineRows = () => window.__jmCollect(window.buildProspectData(), true);
    window.__jmState = () => ({
      floor: JSON.parse(JSON.stringify(window._JM_WEIGHTS)),
      ceiling: JSON.parse(JSON.stringify(window._JM_CEILING_WEIGHTS)),
      tiers: Object.fromEntries(Object.keys(window._POS_TIERS).map(p => [p, window._POS_TIERS[p].map(t => ({ label: t.label, min: t.min }))])),
    });
  }, NO_PROV);
  return { page, browser, server };
}

// ------------------------------------------------------------------ optimiser
async function evalCfg(page, cfg) {
  const t0 = Date.now();
  const rows = await page.evaluate(c => window.__jmApply(c), cfg);
  evalCfg.ms = Date.now() - t0; evalCfg.count = (evalCfg.count || 0) + 1;
  return rows;
}

function byPos(rows, years) {
  const out = {};
  POSITIONS.forEach(p => { out[p] = rows.filter(r => r.pos === p && (!years || years.has(r.yr))); });
  return out;
}

async function descent(page, base, tiers, years, label) {
  // base: {floor:{pos:{}}, ceiling:{pos:{}}}; returns tuned cfg + per-pos scores
  const cfg = JSON.parse(JSON.stringify(base));
  let rows = await evalCfg(page, cfg);
  const cur = {};
  const rp = byPos(rows, years);
  POSITIONS.forEach(p => { cur[p] = score(rp[p], tiers[p]); });
  const start = JSON.parse(JSON.stringify(cur));
  for (let pass = 0; pass < PASSES; pass++) {
    const deltas = pass === 0 ? DELTAS.slice(0, 2) : DELTAS.slice(2);
    for (const track of ['floor', 'ceiling']) {
      const keysByPos = {};
      POSITIONS.forEach(p => { keysByPos[p] = Object.keys(cfg[track][p] || {}).filter(k => cfg[track][p][k] >= MIN_KEY_W); });
      const maxKeys = Math.max(...POSITIONS.map(p => keysByPos[p].length));
      for (let ki = 0; ki < maxKeys; ki++) {
        for (const d of deltas) {
          // one candidate per position in a single rebuild
          const cand = JSON.parse(JSON.stringify(cfg));
          const touched = {};
          POSITIONS.forEach(p => {
            const k = keysByPos[p][ki]; if (!k) return;
            const w = renorm(cfg[track][p], k, d); if (!w) return;
            cand[track][p] = w; touched[p] = k;
          });
          if (!Object.keys(touched).length) continue;
          const r = byPos(await evalCfg(page, cand), years);
          POSITIONS.forEach(p => {
            if (!touched[p]) return;
            const s = score(r[p], tiers[p]);
            if (s.loss < cur[p].loss - 1e-4) { cfg[track][p] = cand[track][p]; cur[p] = s; }
          });
        }
      }
    }
    console.log(`  [${label}] pass ${pass + 1}: ` + POSITIONS.map(p => `${p} loss ${start[p].loss.toFixed(3)}→${cur[p].loss.toFixed(3)} rho ${start[p].rho.toFixed(3)}→${cur[p].rho.toFixed(3)}`).join(' | ') + `  (${evalCfg.count} evals, ${evalCfg.ms} ms/eval)`);
  }
  return { cfg, start, end: cur };
}

(async () => {
  const { page, browser, server } = await boot();
  try {
    const state = await page.evaluate(() => window.__jmState());
    const tiers = state.tiers;
    const base = { floor: state.floor, ceiling: state.ceiling };
    const rows0 = await evalCfg(page, base);
    // Component-vs-outcome correlation (Spearman of each component score with the career grade), per position.
    const compRows = await page.evaluate(() => window.__jmBaselineRows());
    const corr = {};
    POSITIONS.forEach(p => {
      const ev = compRows.filter(r => r.pos === p && r.cs != null && r.comps);
      const keys = new Set(); ev.forEach(r => Object.keys(r.comps).forEach(k => { if (r.comps[k] != null) keys.add(k); }));
      corr[p] = {};
      keys.forEach(k => {
        const sub = ev.filter(r => r.comps[k] != null);
        if (sub.length < 25) return;
        corr[p][k] = { rho: +spearman(sub.map(r => r.comps[k]), sub.map(r => r.cs)).toFixed(3), n: sub.length,
                       floorW: +(state.floor[p] && state.floor[p][k] || 0).toFixed(3), ceilW: +(state.ceiling[p] && state.ceiling[p][k] || 0).toFixed(3) };
      });
      const ranked = Object.entries(corr[p]).sort((a, b) => b[1].rho - a[1].rho);
      console.log(`  correlation ${p} (n ${ev.length}): ` + ranked.map(([k, v]) => `${k} ${v.rho} [w ${v.floorW}/${v.ceilW}]`).join(', '));
    });
    const years = [...new Set(rows0.map(r => r.yr))].sort();
    console.log(`backtest rows: ${rows0.length} graded careers (years ${years.join(',')}${NO_PROV ? ', provisional classes dropped' : ''}), eval ${evalCfg.ms} ms`);
    if (NO_REGEN) console.log('  note: --no-regen is a no-op now that outcomes are career grades');
    const results = { date: new Date().toISOString(), outcome: 'career grade (data/jm_career_grades.js)', noProvisional: NO_PROV, positions: POSITIONS, years, passes: PASSES, baseline: {}, correlation: corr, rows: compRows, loyo: {}, full: null };
    const rp0 = byPos(rows0, null);
    POSITIONS.forEach(p => { results.baseline[p] = score(rp0[p], tiers[p]); console.log(`  baseline ${p}: n ${results.baseline[p].n} rho ${results.baseline[p].rho.toFixed(3)} pen ${results.baseline[p].pen.toFixed(3)} loss ${results.baseline[p].loss.toFixed(3)}`); });

    if (EXP) {
      // Grid of flag-gated model experiments, deployed weights fixed. Per position, the config is
      // chosen on the 7 fit years (loss) and scored on the held-out year; pooled = ship/no-ship.
      const grid = [{ label: 'baseline', exp: null }];
      for (const k of [0.05, 0.1, 0.15, 0.2]) grid.push({ label: `tmComp WR k=${k}`, exp: { tmComp: { WR: k } } });
      for (const k of [0.05, 0.1, 0.15, 0.2]) grid.push({ label: `tmComp RB k=${k}`, exp: { tmComp: { RB: k } } });
      grid.push({ label: 'rbSos', exp: { rbSos: true } });
      for (const k of [0.05, 0.1, 0.15]) grid.push({ label: `rbSos + tmComp RB k=${k}`, exp: { rbSos: true, tmComp: { RB: k } } });
      const rowsBy = {};
      for (const g of grid) {
        rowsBy[g.label] = await evalCfg(page, { ...base, exp: g.exp });
        const rp = byPos(rowsBy[g.label], null);
        console.log(`  ${g.label.padEnd(26)} ` + POSITIONS.map(p => { const sc = score(rp[p], tiers[p]); return `${p} rho ${sc.rho.toFixed(3)} pen ${sc.pen.toFixed(3)}`; }).join(' | '));
      }
      results.experiments = { grid: grid.map(g => g.label), full: {}, loyo: {}, pooled: {} };
      for (const g of grid) {
        const rp = byPos(rowsBy[g.label], null);
        results.experiments.full[g.label] = Object.fromEntries(POSITIONS.map(p => [p, score(rp[p], tiers[p])]));
      }
      POSITIONS.forEach(p => {
        const pooledBase = [], pooledSel = [], picks = {};
        for (const y of years) {
          const fit = new Set(years.filter(v => v !== y));
          let best = null;
          for (const g of grid) {
            const sc = score(byPos(rowsBy[g.label], fit)[p], tiers[p]);
            if (!best || sc.loss < best.loss - 1e-6) best = { label: g.label, loss: sc.loss };
          }
          picks[y] = best.label;
          byPos(rowsBy['baseline'], new Set([y]))[p].filter(r => r.cs != null).forEach(r => pooledBase.push(r));
          byPos(rowsBy[best.label], new Set([y]))[p].filter(r => r.cs != null).forEach(r => pooledSel.push(r));
        }
        const sb = score(pooledBase, tiers[p]), ss = score(pooledSel, tiers[p]);
        results.experiments.pooled[p] = { base: sb, selected: ss, picks };
        console.log(`POOLED out-of-year ${p}: rho ${sb.rho.toFixed(3)} -> ${ss.rho.toFixed(3)}  pen ${sb.pen.toFixed(3)} -> ${ss.pen.toFixed(3)}  picks: ${Object.values(picks).join(' / ')}`);
      });
      fs.writeFileSync(OUT, JSON.stringify(results, null, 1));
      console.log('wrote', OUT, `(${evalCfg.count} evals)`);
      return;
    }
    if (LOYO) {
      const pooledBase = {}, pooledTuned = {};
      POSITIONS.forEach(p => { pooledBase[p] = []; pooledTuned[p] = []; });
      for (const y of years) {
        const fit = new Set(years.filter(v => v !== y));
        const { cfg } = await descent(page, base, tiers, fit, `LOYO ${y}`);
        const held = new Set([y]);
        const rt = byPos(await evalCfg(page, cfg), held);
        const rb = byPos(await evalCfg(page, base), held);
        results.loyo[y] = {};
        POSITIONS.forEach(p => {
          const sb = score(rb[p], tiers[p]), st = score(rt[p], tiers[p]);
          results.loyo[y][p] = { base: sb, tuned: st };
          rb[p].filter(r => r.cs != null).forEach(r => pooledBase[p].push(r));
          rt[p].filter(r => r.cs != null).forEach(r => pooledTuned[p].push(r));
        });
        console.log(`  held-out ${y}: ` + POSITIONS.map(p => `${p} rho ${results.loyo[y][p].base.rho.toFixed(3)}→${results.loyo[y][p].tuned.rho.toFixed(3)}`).join(' | '));
      }
      results.pooled = {};
      POSITIONS.forEach(p => {
        const sb = score(pooledBase[p], tiers[p]), st = score(pooledTuned[p], tiers[p]);
        results.pooled[p] = { base: sb, tuned: st };
        console.log(`POOLED out-of-year ${p}: rho ${sb.rho.toFixed(3)} → ${st.rho.toFixed(3)}  pen ${sb.pen.toFixed(3)} → ${st.pen.toFixed(3)}  (${sb.n} players)`);
      });
    }
    const { cfg, start, end } = await descent(page, base, tiers, null, 'FULL');
    results.full = { weights: cfg, start, end };
    fs.writeFileSync(OUT, JSON.stringify(results, null, 1));
    console.log('wrote', OUT, `(${evalCfg.count} evals)`);
  } finally {
    await browser.close();
    try { server.kill(); } catch (e) {}
    try { spawn('taskkill', ['/F', '/T', '/PID', String(server.pid)], { stdio: 'ignore' }); } catch (e) {}
  }
})().catch(e => { console.error('FAILED', e); process.exit(1); });
