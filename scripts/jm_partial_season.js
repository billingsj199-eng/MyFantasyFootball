/**
 * jm_partial_season.js - how stable / accurate is JM when the final college season is only N games old?
 *
 * The current class is graded in-season (about 9-10 games by mid-November). For every 2017-2024 drafted
 * skill player, this rebuilds his FINAL college season from only the first N logged games
 * (COLLEGE_STATS counting stats + gp, and COLLEGE_WEEKLY cut to those games), re-grades with the real
 * site model, and compares with the full-season grade:
 *   stab   Spearman(JM after N games, JM after the full season) within the position
 *   |d|    mean absolute JM change;  tier  share whose JM tier label changes
 *   rho    Spearman(JM, graded NFL career) for the N-game grade vs the full-season grade, same players
 * N = 0 drops the final season entirely (what a prospect looks like before it starts).
 * Eligible: a final season with >= 10 logged games that have a week number, whose logged fantasy points
 * are within 20% of the season row (so the game logs really cover the season). PFF season grades and
 * PFF-derived fields (yprr, route grade ...) can't be cut down and stay full-season.
 * Real draft picks are kept, so only the stats move. With --devy every player is graded as a no-pick
 * devy prospect instead (window._JM_EXP.asDevy).
 * Optional --exp '{"partialShrink": k}' passes experiment flags (see calcJM / buildProspectData).
 *
 *   node scripts/jm_partial_season.js [--ns 0,3,6,9] [--devy] [--exp JSON] [--out file.json]
 *        [--repo <checkout to serve>] [--node-modules <dir with playwright + http-server>] [--port 8919]
 *
 * Result 2026-11-18 (368 eligible players; jm_partial_season_2026-11-18.json / _devy.json):
 *   With the real pick (main weights): very stable. After 3 games rank agreement with the full-season
 *   grade is .945-.982, after 9 games .993-.998 (mean |JM change| <= 1.1, tier changes <= 6%), and the
 *   N-game grade predicts NFL careers as well as the full-season one from 3 games on.
 *   No pick (devy weights, 2028-type prospects): early grades swing. After 3 games: rank agreement
 *   .88-.95, mean |change| 4-7.6, tier changes 15-53% (RB worst), accuracy down .01-.07. After 7-9 games
 *   it settles (agreement >= .96 / .98, accuracy within .02 of full season).
 *   Before the final season starts (N = 0) accuracy is .02-.05 lower with a pick, .07-.15 lower without.
 *   Mid-November grades (9-10 games) can be trusted; September / early-October devy grades are noisy.
 */
const path = require('path'); const fs = require('fs'); const { spawn } = require('child_process');
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 && args[i + 1] ? args[i + 1] : d; };
const ROOT = path.resolve(opt('--repo', path.join(__dirname, '..')));
const NM = opt('--node-modules', path.join(ROOT, 'tests', 'node_modules'));
const PORT = parseInt(opt('--port', '8919'), 10);
const NS = opt('--ns', '0,3,6,9').split(',').map(Number);
const DEVY = args.includes('--devy');
const EXP = opt('--exp') ? JSON.parse(opt('--exp')) : null;
const OUT = opt('--out', null);
const GRADES = JSON.parse(fs.readFileSync(path.join(__dirname, 'jm_outcome_grades.json'), 'utf8')).players;
const { chromium } = require(path.join(NM, 'playwright'));
const POS = ['QB', 'RB', 'WR', 'TE'];

function spearman(xs, ys) {
  const n = xs.length; if (n < 5) return NaN;
  const rank = a => { const idx = a.map((v, i) => [v, i]).sort((p, q) => p[0] - q[0]); const r = new Array(n); let i = 0;
    while (i < n) { let j = i; while (j + 1 < n && idx[j + 1][0] === idx[i][0]) j++; for (let k = i; k <= j; k++) r[idx[k][1]] = (i + j) / 2; i = j + 1; } return r; };
  const rx = rank(xs), ry = rank(ys); const mx = rx.reduce((s, v) => s + v, 0) / n, my = ry.reduce((s, v) => s + v, 0) / n;
  let num = 0, dx = 0, dy = 0; for (let i = 0; i < n; i++) { num += (rx[i] - mx) * (ry[i] - my); dx += (rx[i] - mx) ** 2; dy += (ry[i] - my) ** 2; }
  return dx && dy ? num / Math.sqrt(dx * dy) : NaN;
}

(async () => {
  const server = spawn(process.execPath, [path.join(NM, 'http-server', 'bin', 'http-server'), ROOT, '-p', String(PORT), '-c-1', '--silent'], { stdio: 'ignore' });
  for (let i = 0; i < 40; i++) { try { const r = await fetch(`http://127.0.0.1:${PORT}/index.html`); if (r.ok) break; } catch (e) {} await new Promise(r => setTimeout(r, 500)); }
  let browser; try { browser = await chromium.launch({ headless: true }); } catch (e) { browser = await chromium.launch({ headless: true, channel: 'msedge' }); }
  const page = await (await browser.newContext({ serviceWorkers: 'block' })).newPage();
  await page.addInitScript(() => { try { localStorage.setItem('mff_seen_intro', '1'); } catch (e) {} });
  page.on('pageerror', e => console.log('  [pageerror]', String(e).slice(0, 160)));
  await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => typeof window.buildProspectData === 'function' && window._POS_TIERS, null, { timeout: 120000 });
  await page.evaluate(async () => { const b = document.querySelector('button.nav-btn[data-page="prospect"]'); if (b) b.click(); const w = []; for (const f of ['_ensureCollegeStatsData', '_ensureBacktestOutcomes', '_ensureProspectStats', '_ensurePffData']) if (window[f]) w.push(window[f]()); await Promise.all(w); });
  await page.waitForFunction(() => typeof BACKTEST_OUTCOMES !== 'undefined' && typeof COLLEGE_STATS !== 'undefined' && typeof COLLEGE_WEEKLY !== 'undefined', null, { timeout: 120000 });
  await new Promise(r => setTimeout(r, 4000));
  const elig = await page.evaluate(([devy, exp]) => {
    const nrm = s => String(s || '').toLowerCase().replace(/(jr\.?|sr\.?|ii|iii|iv|v)/g, '').replace(/[^a-z0-9]/g, '');
    const CNT = ['pa', 'pc', 'py', 'ptd', 'int', 'ra', 'ry', 'rtd', 'rec', 'rcy', 'rctd', 'fl'];
    const fp = g => (g.py || 0) / 25 + (g.ptd || 0) * 4 - (g.int || 0) * 2 + (g.ry || 0) / 10 + (g.rtd || 0) * 6 + (g.rec || 0) * 0.5 + (g.rcy || 0) / 10 + (g.rctd || 0) * 6 - (g.fl || 0) * 2;
    const key = (obj, n) => obj[n] ? n : Object.keys(obj).find(k => nrm(k) === nrm(n));
    window.__base = devy ? { asDevy: true } : null;
    window.__ps = [];   // eligible players: {n, yr, csKey, wkKey, season, games(sorted), row index}
    Object.keys(BACKTEST_OUTCOMES).forEach(yr => BACKTEST_OUTCOMES[yr].forEach(r => {
      if (['QB', 'RB', 'WR', 'TE'].indexOf(r.pos) < 0) return;
      const ck = key(COLLEGE_STATS, r.n), wk = key(COLLEGE_WEEKLY, r.n);
      if (!ck || !wk) return;
      const rows = COLLEGE_STATS[ck].filter(s => s.yr < +yr); if (!rows.length) return;
      const season = Math.max(...rows.map(s => s.yr));
      const ri = COLLEGE_STATS[ck].findIndex(s => s.yr === season);
      const gl = (COLLEGE_WEEKLY[wk] || {})[season];
      if (!Array.isArray(gl)) return;
      const games = gl.filter(g => g && g.wk != null).sort((a, b) => a.wk - b.wk);
      if (games.length < 10) return;
      const logged = games.reduce((s, g) => s + fp(g), 0), row = fp(COLLEGE_STATS[ck][ri]);
      if (!(row > 0) || Math.abs(logged - row) / row > 0.2) return;
      window.__ps.push({ n: r.n, yr: +yr, ck, wk, season, ri, games, orig: JSON.parse(JSON.stringify(COLLEGE_STATS[ck][ri])), origW: gl });
    }));
    window.__cut = (N) => window.__ps.forEach(p => {
      if (N == null) { COLLEGE_STATS[p.ck][p.ri] = JSON.parse(JSON.stringify(p.orig)); COLLEGE_WEEKLY[p.wk][p.season] = p.origW; return; }
      if (N === 0) {   // final season not played yet
        COLLEGE_STATS[p.ck][p.ri] = { yr: p.season, tm: p.orig.tm, conf: p.orig.conf, gp: 0 };
        COLLEGE_WEEKLY[p.wk][p.season] = []; return;
      }
      const first = p.games.slice(0, N), row = JSON.parse(JSON.stringify(p.orig));
      CNT.forEach(f => { const v = first.reduce((s, g) => s + (g[f] || 0), 0); if (v || row[f] != null) row[f] = v; });
      row.gp = first.length;
      if (row.ra) row.rypc = Math.round(row.ry / row.ra * 10) / 10;
      COLLEGE_STATS[p.ck][p.ri] = row; COLLEGE_WEEKLY[p.wk][p.season] = first;
    });
    window.__run = (N) => {
      window.__cut(N);
      window._JM_EXP = Object.assign({}, window.__base || {}, exp || {});
      if (window._jmClearCache) window._jmClearCache();
      const data = window.buildProspectData(), by = {};
      data.forEach(p => { if (p.jm != null) { by[p.name] = p; by[nrm(p.name)] = p; } });
      const tierOf = (jm, pos) => { const t = (window._POS_TIERS[pos] || []).find(t => jm >= t.min); return t ? t.label : null; };
      const out = window.__ps.map(p => { const q = by[p.n] || by[nrm(p.n)]; return q ? [q.name, q.pos, p.yr, q.jm, tierOf(q.jm, q.pos)] : null; }).filter(Boolean);
      window.__cut(null);
      return out;
    };
    return window.__ps.length;
  }, [DEVY, EXP]);
  console.log(`eligible players: ${elig}${DEVY ? ' (graded as no-pick devy)' : ''}${EXP ? ' exp ' + JSON.stringify(EXP) : ''}`);
  // warm-up: late async data can still move a few grades; rebuild until two full-season builds match
  let prev = JSON.stringify(await page.evaluate(() => window.__run(null)));
  for (let i = 0; i < 12; i++) { await new Promise(r => setTimeout(r, 3000)); const cur = JSON.stringify(await page.evaluate(() => window.__run(null))); if (cur === prev) break; prev = cur; }
  const full = await page.evaluate(() => window.__run(null));
  const byN = {};
  for (const N of NS) byN[N] = await page.evaluate(n => window.__run(n), N);
  const again = await page.evaluate(() => window.__run(null));
  if (JSON.stringify(again) !== JSON.stringify(full)) console.log('WARNING: full-season grades changed during the run');
  await browser.close(); server.kill();

  const F = {}; full.forEach(r => { F[r[0] + '|' + r[2]] = r; });
  const res = { full: {}, byN: {} };
  console.log('\n' + 'N'.padEnd(6) + POS.map(p => `${p}: stab  |d|  tier  rho(N) rho(full)  n`.padEnd(46)).join(''));
  for (const N of NS) {
    res.byN[N] = {};
    let line = String(N).padEnd(6);
    POS.forEach(pos => {
      const rows = byN[N].filter(r => r[1] === pos && F[r[0] + '|' + r[2]]);
      const g = rows.map(r => GRADES[r[0] + '|' + r[2]]);
      const ok = rows.filter((r, i) => g[i] && g[i].grade != null);
      const gr = ok.map(r => GRADES[r[0] + '|' + r[2]].grade);
      const m = {
        n: rows.length,
        stab: spearman(rows.map(r => r[3]), rows.map(r => F[r[0] + '|' + r[2]][3])),
        absd: rows.reduce((s, r) => s + Math.abs(r[3] - F[r[0] + '|' + r[2]][3]), 0) / rows.length,
        tier: rows.filter(r => r[4] !== F[r[0] + '|' + r[2]][4]).length / rows.length,
        rhoN: spearman(ok.map(r => r[3]), gr), rhoFull: spearman(ok.map(r => F[r[0] + '|' + r[2]][3]), gr),
        meanShift: rows.reduce((s, r) => s + (r[3] - F[r[0] + '|' + r[2]][3]), 0) / rows.length,
      };
      res.byN[N][pos] = m;
      line += `${m.stab.toFixed(3)} ${m.absd.toFixed(1).padStart(5)} ${(m.tier * 100).toFixed(0).padStart(4)}%  ${m.rhoN.toFixed(3)}  ${m.rhoFull.toFixed(3)} ${String(m.n).padStart(4)}`.padEnd(46);
    });
    console.log(line);
  }
  if (OUT) { fs.writeFileSync(OUT, JSON.stringify({ date: new Date().toISOString().slice(0, 10), devy: DEVY, exp: EXP, ns: NS, eligible: elig, results: res.byN, full, byN }, null, 1)); console.log('wrote', OUT); }
})().catch(e => { console.error(e); process.exit(1); });
