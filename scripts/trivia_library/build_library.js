// Daily Trivia — pre-built, audited, frozen BOARD LIBRARY (2026-10-29).
//
// Jack's decision (2026-10-28): build every season / career / era / team board
// ONCE with the site's own structured generator, audit each one once, freeze
// the lot in a static file, and let the Daily Trivia draw from the frozen
// boards — nothing is re-aggregated or re-checked at runtime.
//
// Same approach as scripts/trivia_daily/build_board.js (copied, not shared):
// Playwright serves THIS checkout under a fake origin, opens #trivia, sets the
// builder's selects exactly as _triviaApplyTemplate does, runs
// _triviaGenerate(), reads _triviaData back together with the structured
// verifier result (window._triviaVerifyBoard — the reference table +
// LEGEND_CAREERS / SEASON_LEADERS cross-check that paints the GREEN / AMBER
// banner for admins). The AI / custom-prompt generator is never touched.
//
// Output
//   data/trivia_library.js             window.TRIVIA_LIBRARY = {built, count, boards:[…]}
//   scripts/trivia_library/audit_report.md   ONLY the amber / mismatch boards, name-level diffs
//   scripts/trivia_library/last_build.json   skips + timing (small)
//
// Usage (from the checkout root):
//   node scripts/trivia_library/build_library.js                # full matrix
//   node scripts/trivia_library/build_library.js --only "^s2007" --limit 5 --out /tmp/x.js
//   node scripts/trivia_library/build_library.js --no-weekly    # skip the single-game boards
//   --site <dir>  serve another checkout (default: this script's repo)
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const MAIN_CHECKOUT = 'E:\\MyFantasyFootball\\MyFantasyFootball Files';
const ORIGIN = 'https://mff-trivia.local';
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.woff2': 'font/woff2', '.woff': 'font/woff', '.webmanifest': 'application/manifest+json', '.txt': 'text/plain; charset=utf-8' };

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------
const argv = process.argv.slice(2);
const opt = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] != null ? argv[i + 1] : def; };
const flag = (name) => argv.includes(name);
const SITE_DIR = path.resolve(opt('--site', ROOT));
const OUT_FILE = path.resolve(opt('--out', path.join(ROOT, 'data', 'trivia_library.js')));
const REPORT_FILE = path.resolve(opt('--report', path.join(__dirname, 'audit_report.md')));
const LOG_FILE = path.resolve(opt('--log', path.join(__dirname, 'last_build.json')));
const ONLY = opt('--only', null) ? new RegExp(opt('--only')) : null;
const LIMIT = parseInt(opt('--limit', '0'), 10) || 0;
const NO_WEEKLY = flag('--no-weekly');
const COUNT = 20;
const MIN_ITEMS = 16;

const log = (m) => console.log('[' + new Date().toISOString().slice(11, 19) + '] ' + m);

// ---------------------------------------------------------------------------
// Matrix
// ---------------------------------------------------------------------------
const POS = { all: ['QB', 'RB', 'WR', 'TE'], qb: ['QB'], rb: ['RB'], wrte: ['WR', 'TE'] };
const POS_WORD = { all: 'All Positions', qb: 'QB', rb: 'RB', wrte: 'WR/TE' };
const STAT_WORD = { fpts: 'Fantasy Points', ry: 'Rushing Yards', rcy: 'Receiving Yards', py: 'Passing Yards', totalTd: 'Total TDs' };
const FIRST_SEASON = 1970, LAST_SEASON = 2026, LAST_COMPLETE = 2025, FIRST_WEEKLY = 1999;
// Season boards: the stat × position pairs that make a sensible list.
const SEASON_MATRIX = [['fpts', 'all'], ['fpts', 'qb'], ['fpts', 'rb'], ['fpts', 'wrte'], ['ry', 'rb'], ['rcy', 'wrte'], ['py', 'qb'], ['totalTd', 'all']];
const CAREER_MATRIX = [['ry', 'rb'], ['rcy', 'wrte'], ['py', 'qb'], ['fpts', 'all']];
const TEAM_MATRIX = [['ry', 'rb'], ['rcy', 'wrte'], ['py', 'qb']];
const GAME_MATRIX = [['fpts', 'all'], ['ry', 'rb'], ['rcy', 'wrte'], ['py', 'qb']];
// key, label, builder era value (null = postseason, era all)
const ERAS = [
  ['all', 'All-Time', 'all'],
  ['1970s', '1970s', '1970-1979'], ['1980s', '1980s', '1980-1989'], ['1990s', '1990s', '1990-1999'],
  ['2000s', '2000s', '2000-2009'], ['2010s', '2010s', '2010-2019'], ['2020s', '2020s', '2020-2029'],
  ['since2010', 'Since 2010', 'since-2010'],
  ['post', 'Postseason', null],
];
const TEAMS = [['ARI', 'Cardinals'], ['ATL', 'Falcons'], ['BAL', 'Ravens'], ['BUF', 'Bills'], ['CAR', 'Panthers'], ['CHI', 'Bears'], ['CIN', 'Bengals'], ['CLE', 'Browns'], ['DAL', 'Cowboys'], ['DEN', 'Broncos'], ['DET', 'Lions'], ['GB', 'Packers'], ['HOU', 'Texans'], ['IND', 'Colts'], ['JAX', 'Jaguars'], ['KC', 'Chiefs'], ['LAC', 'Chargers'], ['LAR', 'Rams'], ['LV', 'Raiders'], ['MIA', 'Dolphins'], ['MIN', 'Vikings'], ['NE', 'Patriots'], ['NO', 'Saints'], ['NYG', 'Giants'], ['NYJ', 'Jets'], ['PHI', 'Eagles'], ['PIT', 'Steelers'], ['SF', '49ers'], ['SEA', 'Seahawks'], ['TB', 'Buccaneers'], ['TEN', 'Titans'], ['WAS', 'Commanders']];

const baseFilters = () => ({ type: 'season', stat: 'fpts', year: 'all', era: 'all', count: COUNT, conf: 'all', team: 'all', week: 'all', seasonType: 'reg', positions: POS.all });

function buildMatrix() {
  const specs = [];
  // 1. Season boards 1970-2026
  for (let yr = FIRST_SEASON; yr <= LAST_SEASON; yr++) {
    for (const [stat, pk] of SEASON_MATRIX) {
      specs.push({
        id: 's' + yr + '-' + stat.toLowerCase() + '-' + pk, kind: 'season', season: yr, stat, posKey: pk, era: String(yr),
        title: yr + ' ' + STAT_WORD[stat] + ' · ' + POS_WORD[pk],
        desc: 'Top ' + COUNT + ' · ' + yr + ' regular season',
        filters: Object.assign(baseFilters(), { type: 'season', stat, year: String(yr), positions: POS[pk] }),
        audit: 'verifier',
      });
    }
  }
  // 2. Career / era / postseason boards
  for (const [ek, elabel, eval_] of ERAS) {
    for (const [stat, pk] of CAREER_MATRIX) {
      const post = ek === 'post';
      const title = ek === 'all' ? 'All-Time ' + STAT_WORD[stat] + ' · ' + POS_WORD[pk]
        : post ? 'Career Playoff ' + STAT_WORD[stat] + ' · ' + POS_WORD[pk]
        : ek === 'since2010' ? STAT_WORD[stat] + ' Since 2010 · ' + POS_WORD[pk]
        : elabel + ' ' + STAT_WORD[stat] + ' · ' + POS_WORD[pk];
      const desc = ek === 'all' ? 'Career totals, all-time'
        : post ? 'Career postseason totals'
        : ek === 'since2010' ? 'Career totals, 2010 to today'
        : 'Career totals, ' + eval_.replace('-', '–') + ' seasons only';
      specs.push({
        id: 'c-' + ek + '-' + stat.toLowerCase() + '-' + pk, kind: 'career', season: null, stat, posKey: pk, era: elabel,
        title, desc,
        filters: Object.assign(baseFilters(), { type: 'career', stat, year: 'all', era: post ? 'all' : eval_, seasonType: post ? 'post' : 'reg', positions: POS[pk] }),
        audit: 'verifier',
      });
    }
  }
  // 3. Team all-time boards (the generator writes "… Since 1999" when its pool
  //    cannot cover the franchise's early years — keep ITS title for these).
  for (const [abbr, nick] of TEAMS) {
    for (const [stat, pk] of TEAM_MATRIX) {
      specs.push({
        id: 't-' + abbr.toLowerCase() + '-' + stat.toLowerCase() + '-' + pk, kind: 'team', season: null, stat, posKey: pk, era: 'All-Time', team: abbr,
        title: null, // generator's
        desc: 'Career totals with the ' + nick,
        filters: Object.assign(baseFilters(), { type: 'career', stat, year: 'all', era: 'all', team: abbr, positions: POS[pk] }),
        audit: 'verifier',
      });
    }
  }
  // 4. Single-game boards (1999+ logs). No reference table on the site either.
  if (!NO_WEEKLY) {
    for (let yr = FIRST_WEEKLY; yr <= LAST_COMPLETE; yr++) {
      specs.push({
        id: 'g' + yr + '-fpts-all', kind: 'game', season: yr, stat: 'fpts', posKey: 'all', era: String(yr),
        title: yr + ' Best Single Games · Fantasy Points',
        desc: 'Top ' + COUNT + ' single-game scores of ' + yr,
        filters: Object.assign(baseFilters(), { type: 'game', stat: 'fpts', year: String(yr), positions: POS.all }),
        audit: 'none',
      });
    }
    for (const [stat, pk] of GAME_MATRIX) {
      specs.push({
        id: 'g-all-' + stat.toLowerCase() + '-' + pk, kind: 'game', season: null, stat, posKey: pk, era: 'Since 1999',
        title: 'Best Single Games Ever · ' + STAT_WORD[stat] + ' · ' + POS_WORD[pk],
        desc: 'Top ' + COUNT + ' single games, 1999 to today',
        filters: Object.assign(baseFilters(), { type: 'game', stat, year: 'all', positions: POS[pk] }),
        audit: 'none',
      });
    }
  }
  return specs;
}

// ---------------------------------------------------------------------------
// Browser
// ---------------------------------------------------------------------------
function requirePlaywright() {
  const tries = [
    path.join(SITE_DIR, 'tests', 'node_modules', 'playwright'),
    path.join(MAIN_CHECKOUT, 'tests', 'node_modules', 'playwright'),
    path.join(SITE_DIR, 'tests', 'node_modules', '@playwright', 'test'),
    path.join(MAIN_CHECKOUT, 'tests', 'node_modules', '@playwright', 'test'),
    'playwright',
  ];
  const errs = [];
  for (const t of tries) {
    try { const m = require(t); if (m && m.chromium) return m; } catch (e) { errs.push(t + ': ' + String(e && e.message || e).split('\n')[0]); }
  }
  throw new Error('playwright not found: ' + errs.join(' | '));
}

async function launchBrowser(chromium) {
  const tries = [['bundled headless shell', {}], ['bundled chromium', { channel: 'chromium' }], ['installed Edge', { channel: 'msedge' }], ['installed Chrome', { channel: 'chrome' }]];
  const errs = [];
  for (const [label, o] of tries) {
    try { const b = await chromium.launch(Object.assign({ headless: true }, o)); log('browser: ' + label); return b; }
    catch (e) { errs.push(label + ': ' + String(e && e.message || e).split('\n')[0]); }
  }
  throw new Error('no browser could be launched | ' + errs.join(' | '));
}

// Serve the checkout from disk under ORIGIN; drop third-party images/fonts
// (logos, headshots) so a 600-board run does not hammer the CDNs.
async function routeSite(context) {
  await context.route('**/*', async (route) => {
    const req = route.request();
    const u = new URL(req.url());
    if (u.origin !== ORIGIN) {
      const t = req.resourceType();
      if (t === 'image' || t === 'media' || t === 'font') return route.abort();
      return route.continue();
    }
    let p = decodeURIComponent(u.pathname);
    if (p === '/' || p === '') p = '/index.html';
    const file = path.join(SITE_DIR, p.replace(/^\/+/, ''));
    if (!file.startsWith(SITE_DIR) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) return route.fulfill({ status: 404, body: 'not found' });
    const ext = path.extname(file).toLowerCase();
    return route.fulfill({ status: 200, body: fs.readFileSync(file), headers: { 'content-type': MIME[ext] || 'application/octet-stream', 'cache-control': 'no-store' } });
  });
}

// ---------------------------------------------------------------------------
// Runs inside the page: apply filters, generate, read board + verifier.
// ---------------------------------------------------------------------------
async function pageBuild(spec) {
  const f = spec.filters;
  const setVal = (id, v) => { const el = document.getElementById(id); if (el && v != null) { el.value = v; el.dispatchEvent(new Event('change', { bubbles: true })); } return el ? el.value : undefined; };
  const applied = {};
  applied.type = setVal('triviaFilterType', f.type);
  applied.stat = setVal('triviaFilterStat', f.stat);
  applied.year = setVal('triviaFilterYear', f.year);
  applied.era = setVal('triviaFilterEra', f.era || 'all');
  applied.count = setVal('triviaFilterCount', String(f.count));
  applied.conf = setVal('triviaFilterConf', f.conf || 'all');
  applied.team = setVal('triviaFilterTeam', f.team || 'all');
  applied.week = setVal('triviaFilterWeek', f.week || 'all');
  applied.seasonType = setVal('triviaFilterSeasonType', f.seasonType || 'reg');
  const bad = Object.keys(applied).filter(k => applied[k] === '' || applied[k] === undefined);
  if (bad.length) return { error: 'filter not accepted by the page: ' + bad.join(',') };
  const wanted = new Set(f.positions);
  document.querySelectorAll('#triviaFilterPos input[type="checkbox"]').forEach(cb => {
    const should = wanted.has(cb.value);
    if (cb.checked !== should) { cb.checked = should; cb.dispatchEvent(new Event('change', { bubbles: true })); }
  });
  const cust = document.getElementById('triviaCustomPromptToggle');
  if (cust && cust.checked) { cust.checked = false; cust.dispatchEvent(new Event('change', { bubbles: true })); }
  const nameEl = document.getElementById('triviaGameName');
  if (nameEl) nameEl.value = '';
  const lo = document.getElementById('triviaLayout');
  if (lo) lo.value = 'auto';
  window._triviaData = null;
  const t0 = performance.now();
  await window._triviaGenerate();
  const data = window._triviaData;
  const ms = Math.round(performance.now() - t0);
  if (!data || !data.items) return { error: 'generator produced no board', area: ((document.getElementById('triviaBoardArea') || {}).textContent || '').trim().slice(0, 200), ms };
  let verify = null;
  try { verify = (typeof window._triviaVerifyBoard === 'function') ? window._triviaVerifyBoard(data) : null; } catch (e) { verify = { error: String(e && e.message || e) }; }
  const pick = (c) => c ? { ok: !!c.ok, depth: c.depth, exact: c.exact, missing: c.missing || [], extra: c.extra || [], key: c.key || undefined } : null;
  // Season boards: PFR checks of our own, sharper than the site's set-equal
  // cross-check. Two sources — SEASON_LEADERS (PFR top-25 per yards category,
  // 1966-2025; a player can be absent simply because PFR's table was cut by
  // receptions, so only names the table ranks ABOVE the board's 10th spot count
  // as missing) and, before 1999, SEASON_TOTALS_7098 (the whole league, same
  // half-PPR basis as LEGEND_CAREERS, so fantasy-point boards get a check too).
  // A board top-10 value that disagrees with PFR by more than 1% is reported
  // as well: a right name with a wrong hint is still a wrong board.
  const pfr = [];
  try {
    if (f.type === 'season' && f.year !== 'all' && (f.seasonType || 'reg') === 'reg') {
      const yr = +f.year, stat = f.stat, positions = new Set(f.positions);
      const dPos = {}; D.forEach(d => { if (d.n && d.s) dPos[d.n] = d.s; });
      const norm = n => String(n || '').replace(/\s*\(.*$/, '').replace(/\s+(Sr\.?|Jr\.?|II|III|IV|V)$/i, '').replace(/[.'’]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
      const topN = (data._topN || []).map(x => ({ key: norm(x.name), name: x.name, val: +x.val || 0 }));
      const boardKeys = new Set(data.items.map(it => norm(it.answer)));
      const cut = topN.length >= 10 ? topN[9].val : null;
      const run = (source, rows) => {
        if (!rows.length || cut == null) return;
        rows.sort((a, b) => b.val - a.val);
        const missing = rows.filter(r => r.val > cut && !boardKeys.has(norm(r.name))).map(r => r.name + ' ' + Math.round(r.val * 10) / 10);
        const byKey = {}; rows.forEach(r => { const k = norm(r.name); if (!(k in byKey) || byKey[k] < r.val) byKey[k] = r.val; });
        const valueDiffs = [];
        topN.slice(0, 10).forEach(t => {
          if (!(t.key in byKey)) return;
          const s = byKey[t.key];
          if (Math.abs(t.val - s) > Math.max(2, 0.01 * s)) valueDiffs.push(t.name + ' board ' + Math.round(t.val * 10) / 10 + ' vs PFR ' + Math.round(s * 10) / 10);
        });
        pfr.push({ source, ok: !missing.length && !valueDiffs.length, depth: 10, missing, valueDiffs, top: rows.slice(0, 10).map(r => r.name + ' ' + Math.round(r.val * 10) / 10) });
      };
      const SL_MAP = { py: ['passing', 'pass_yds'], ptd: ['passing', 'pass_td'], ry: ['rushing', 'rush_yds'], rtd: ['rushing', 'rush_td'], rcy: ['receiving', 'rec_yds'], rec: ['receiving', 'rec'], rctd: ['receiving', 'rec_td'] };
      if (typeof SEASON_LEADERS !== 'undefined' && SEASON_LEADERS[String(yr)] && SL_MAP[stat]) {
        const [cat, field] = SL_MAP[stat];
        const rows = [];
        (SEASON_LEADERS[String(yr)][cat] || []).forEach(r => {
          if (!r || !r.name) return;
          const pfrPos = (r.pos || '').toUpperCase();
          const pos = dPos[r.name] || (['QB', 'RB', 'WR', 'TE'].includes(pfrPos) ? pfrPos : '') || (cat === 'passing' ? 'QB' : cat === 'rushing' ? 'RB' : 'WR');
          if (!positions.has(pos)) return;
          rows.push({ name: r.name, val: +r[field] || 0 });
        });
        run('PFR season leaders (SEASON_LEADERS)', rows);
      }
      if (yr < 1999 && typeof SEASON_TOTALS_7098 !== 'undefined') {
        const val = s => stat === 'totalTd' ? (s.ptd || 0) + (s.rtd || 0) + (s.rctd || 0) : stat === 'rec' ? (s.rc || 0) : (s[stat] || 0);
        const rows = [];
        for (const id in SEASON_TOTALS_7098) {
          const p = SEASON_TOTALS_7098[id];
          const s = (p.seasons || []).find(x => x && x.yr === yr);
          if (!s) continue;
          // The file's own (unified) position: a D[] label by name would hand the
          // 1984 Lions RB James Jones the Packers WR's position.
          if (!positions.has(p.pos)) continue;
          const v = val(s);
          if (v > 0) rows.push({ name: p.n, val: v });
        }
        run('PFR 1970-98 season totals (SEASON_TOTALS_7098)', rows);
      }
    }
  } catch (e) { pfr.push({ source: 'pfr check', error: String(e && e.message || e) }); }
  return {
    pfr,
    title: data.title || '',
    items: data.items.map(it => ({ answer: it.answer || '', team: it.team || '', category: it.category || '', hint: it.hint || '', yr: it.yr || null })),
    filter: data._filter || null,
    topN: (data._topN || []).slice(0, 25).map(x => ({ name: x.name, val: x.val, pos: x.pos, team: x.team })),
    verify: verify ? { ref: pick(verify.ref), cross: pick(verify.cross), error: verify.error } : null,
    ms,
  };
}

function statusFrom(spec, r) {
  const v = r.verify;
  const none = { status: 'none', diff: null };
  const na = { status: 'na', diff: null };
  if (spec.audit === 'none') return { verifier: none, pfr: na };
  const diffs = [];
  const checks = [];
  if (spec.kind === 'season') {
    // Season boards: the build's own PFR checks (see pageBuild) replace the
    // site's set-equal cross-check.
    const srcs = (r.pfr || []).filter(p => !p.error);
    if (!srcs.length) return { verifier: none, pfr: na };
    srcs.forEach(p => {
      checks.push(p.source + ' top-' + p.depth);
      if (!p.ok) diffs.push({ source: p.source, missing: p.missing, extra: [], valueDiffs: p.valueDiffs, sourceTop: p.top });
    });
    const status = diffs.length ? 'amber' : 'green';
    return { verifier: { status, checks, diff: diffs.length ? diffs : null }, pfr: { status, diff: diffs.length ? { missing: [].concat(...diffs.map(d => d.missing)), valueDiffs: [].concat(...diffs.map(d => d.valueDiffs)) } : null } };
  }
  if (!v || (!v.ref && !v.cross)) return { verifier: none, pfr: na };
  if (v.ref) { checks.push('record book top-' + v.ref.depth); if (!v.ref.ok) diffs.push({ source: 'NFL record book (_TRIVIA_KNOWN_LEADERS)', missing: v.ref.missing, extra: v.ref.extra }); }
  if (v.cross) {
    checks.push('LEGEND_CAREERS direct top-' + v.cross.depth);
    if (!v.cross.ok) diffs.push({ source: 'LEGEND_CAREERS direct', missing: v.cross.missing, extra: v.cross.extra });
  }
  // Career / team boards have no PFR leaderboard to meet.
  return { verifier: { status: diffs.length ? 'amber' : 'green', checks, diff: diffs.length ? diffs : null }, pfr: na };
}

// ---------------------------------------------------------------------------
async function main() {
  const t0 = Date.now();
  let specs = buildMatrix();
  if (ONLY) specs = specs.filter(s => ONLY.test(s.id));
  if (LIMIT) specs = specs.slice(0, LIMIT);
  log('site: ' + SITE_DIR);
  log('matrix: ' + specs.length + ' boards' + (ONLY ? ' (filtered ' + ONLY + ')' : ''));
  if (!specs.length) throw new Error('nothing to build');

  const { chromium } = requirePlaywright();
  const browser = await launchBrowser(chromium);
  const boards = [], skips = [], timing = [];
  try {
    const context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1400, height: 900 } });
    await context.addInitScript(() => { try { localStorage.setItem('mff_seen_intro', '1'); } catch (_) {} });
    await routeSite(context);
    const page = await context.newPage();
    const pageErrors = [];
    page.on('pageerror', e => pageErrors.push(String(e).split('\n')[0]));
    await page.goto(ORIGIN + '/index.html?r=' + Date.now() + '#trivia', { waitUntil: 'load', timeout: 120000 });
    await page.waitForFunction(() => typeof window._triviaGenerate === 'function', null, { timeout: 60000 });
    await page.evaluate(async () => {
      try { if (typeof switchPage === 'function') switchPage('trivia'); } catch (_) {}
      const ps = [];
      if (typeof window._loadRetiredData === 'function') ps.push(window._loadRetiredData());
      if (typeof window._loadWeeklyData === 'function') ps.push(window._loadWeeklyData());
      if (typeof window._ensureSeasonLeaders === 'function') ps.push(window._ensureSeasonLeaders());
      if (typeof window._loadSeasonTotals7098 === 'function') ps.push(window._loadSeasonTotals7098());
      if (typeof window._loadWeeklyLegacy === 'function') { try { ps.push(window._loadWeeklyLegacy()); } catch (_) {} }
      await Promise.all(ps);
    });
    await page.waitForFunction(() => typeof LEGEND_CAREERS !== 'undefined' && typeof D !== 'undefined' && D.some(d => d._retired && d.career && d.career.length > 5) && typeof WEEKLY_STATS !== 'undefined' && Object.keys(WEEKLY_STATS).length > 2000 && typeof SEASON_LEADERS !== 'undefined', null, { timeout: 180000 });
    const stats = await page.evaluate(() => {
      // Latest week with a played game this season (the in-season boards say so).
      let wk = 0;
      try {
        const yr = String(new Date().getFullYear());
        for (const n in WEEKLY_STATS) { const s = WEEKLY_STATS[n] && WEEKLY_STATS[n].seasons && WEEKLY_STATS[n].seasons[yr]; if (!s) continue; for (const w of s) if (w && (w.fpts > 0 || w.py > 0 || w.ry > 0 || w.rec > 0) && +w.wk > wk) wk = +w.wk; }
      } catch (_) {}
      return { D: D.length, legends: Object.keys(LEGEND_CAREERS).length, weekly: Object.keys(WEEKLY_STATS).length, seasonLeaders: Object.keys(SEASON_LEADERS).length, totals7098: typeof SEASON_TOTALS_7098 !== 'undefined' ? Object.keys(SEASON_TOTALS_7098).length : 0, verifier: typeof window._triviaVerifyBoard === 'function', thisSeasonWeek: wk };
    });
    log('site data: ' + JSON.stringify(stats));
    if (!stats.verifier) log('WARNING: window._triviaVerifyBoard missing — every board will audit as none');
    if (pageErrors.length) log('page errors (' + pageErrors.length + '): ' + pageErrors.slice(0, 3).join(' | '));
    const thisYear = new Date().getFullYear();

    let n = 0;
    for (const spec of specs) {
      n++;
      let r;
      try { r = await page.evaluate(pageBuild, spec); }
      catch (e) { r = { error: 'evaluate failed: ' + String(e && e.message || e).split('\n')[0] }; }
      timing.push(r.ms || 0);
      if (r.error) { skips.push({ id: spec.id, reason: r.error }); log(n + '/' + specs.length + ' SKIP ' + spec.id + ' — ' + r.error); continue; }
      if (r.items.length < MIN_ITEMS) { skips.push({ id: spec.id, reason: 'only ' + r.items.length + ' items', items: r.items.length }); log(n + '/' + specs.length + ' SKIP ' + spec.id + ' — only ' + r.items.length + ' items'); continue; }
      const st = statusFrom(spec, r);
      const board = {
        id: spec.id, kind: spec.kind, title: spec.title || r.title, desc: spec.desc, era: spec.era,
        season: spec.season, stat: spec.stat, pos: spec.posKey, team: spec.team || null,
        filters: spec.filters, layout: 'auto',
        items: r.items,
        genTitle: r.title,
        verifier: st.verifier, pfr: st.pfr, audit: spec.audit,
        reviewed: false,
      };
      if (spec.kind === 'season' && spec.season === thisYear) {
        board.partial = { throughWeek: stats.thisSeasonWeek, note: 'season in progress — rebuild after the season' };
        board.desc = 'Top ' + COUNT + ' · ' + spec.season + ' through Week ' + stats.thisSeasonWeek + ' (in progress)';
        board.verifier = { status: 'none', diff: null, checks: [] };
        board.pfr = { status: 'na', diff: null };
      }
      boards.push(board);
      const tag = board.verifier.status.toUpperCase() + (board.pfr.status !== 'na' ? '/pfr:' + board.pfr.status : '');
      log(n + '/' + specs.length + ' ' + spec.id + ' ' + tag + ' ' + r.items.length + ' items ' + r.ms + 'ms — ' + board.title + (board.verifier.diff ? ' | ' + board.verifier.diff.map(d => 'missing: ' + d.missing.join(', ') + '; extra: ' + d.extra.join(', ')).join(' || ') : ''));
    }
  } finally {
    await browser.close().catch(() => {});
  }

  // ---- write the library ----------------------------------------------------
  const built = new Date().toISOString();
  const header = '// Daily Trivia — pre-built, audited, FROZEN board library. Generated by\n' +
    '// scripts/trivia_library/build_library.js on ' + built + ' from the site\'s own\n' +
    '// structured generator (no AI). Lazy-loaded by index.html _loadTriviaLibrary.\n' +
    '// Do not hand-edit: re-run the build, then review scripts/trivia_library/audit_report.md.\n' +
    '// reviewed flags: Jack\'s admin toggle writes Firestore trivia_library/overrides, which wins over the flag here.\n';
  const body = 'window.TRIVIA_LIBRARY = {\n"built": ' + JSON.stringify(built) + ',\n"count": ' + boards.length + ',\n"boards": [\n' +
    boards.map(b => JSON.stringify(b)).join(',\n') + '\n]};\n';
  fs.mkdirSync(path.dirname(OUT_FILE), { recursive: true });
  fs.writeFileSync(OUT_FILE, header + body);
  const sizeMb = (fs.statSync(OUT_FILE).size / 1048576).toFixed(2);

  // ---- audit report (amber / mismatch boards only) ----------------------------
  const count = (k, s) => boards.filter(b => b[k].status === s).length;
  const amber = boards.filter(b => b.verifier.status === 'amber');
  const partial = boards.filter(b => b.partial);
  const lines = [];
  lines.push('# Trivia Board Library — audit report');
  lines.push('');
  lines.push('Built ' + built + ' · ' + boards.length + ' boards · ' + (Date.now() - t0 > 60000 ? Math.round((Date.now() - t0) / 60000) + ' min' : Math.round((Date.now() - t0) / 1000) + ' s') + ' · ' + sizeMb + ' MB');
  lines.push('');
  lines.push('| verifier | boards |  | PFR cross-check | boards |');
  lines.push('|---|---|---|---|---|');
  lines.push('| green | ' + count('verifier', 'green') + ' |  | green | ' + count('pfr', 'green') + ' |');
  lines.push('| amber | ' + count('verifier', 'amber') + ' |  | amber | ' + count('pfr', 'amber') + ' |');
  lines.push('| none (no reference available) | ' + count('verifier', 'none') + ' |  | n/a | ' + count('pfr', 'na') + ' |');
  lines.push('');
  lines.push('Green = every check that could run agreed with the board (set-equal on the top 10: rank swaps never flag; a name missing or extra does).');
  lines.push('Only the amber boards are listed below — everything else passed or had no reference to meet (single-game boards, 1999+ fantasy-point / total-TD season boards, in-season boards).');
  lines.push('');
  lines.push('## How to review');
  lines.push('');
  lines.push('1. Trivia page (admin) → BOARD LIBRARY · ADMIN REVIEW → status filter **Amber**. Each row shows the diff; PREVIEW plays the board.');
  lines.push('2. Board right (the check is the one that is off) → tick **reviewed**. Board wrong → leave it unticked (it never enters the daily rotation) and note the data fix.');
  lines.push('3. **✓ APPROVE ALL GREEN** marks every green, complete board reviewed in one write — that is the daily pool.');
  lines.push('4. Marks go to Firestore `trivia_library/overrides` (deploy `firestore.rules` once). Rebuilding the file never clears them.');
  lines.push('');
  lines.push('Checks, by board kind: season boards 1966-2025 yards/TD stats → PFR top-25 tables (`SEASON_LEADERS`), plus the full-league PFR season totals (`SEASON_TOTALS_7098`) before 1999; career / era / team boards → the site verifier (record-book table + `LEGEND_CAREERS` direct aggregation). "VALUE differs" = a name in both lists whose number is off by more than 1 %.');
  lines.push('');
  lines.push('Known causes seen in this build (decide once, then tick or fix):');
  lines.push('- 1999-2000 season boards: the game logs (nflverse) miss games those years, so yards run short of PFR (Kurt Warner 1999: 3,956 vs 4,353). PFR is right; the hint is low.');
  lines.push('- 2022 Bengals / Bills: the site counts the cancelled Week 17 game (Burrow 4,527 vs PFR 4,475).');
  lines.push('- Career / team boards: the cross-check reads `LEGEND_CAREERS` with D[] positions and no in-season rows, so it can be the wrong side (Mel Gray is a WR; Jarvis Landry\'s 3,560 Browns yards are right).');
  lines.push('');
  lines.push('## Amber boards (' + amber.length + ') — review these');
  lines.push('');
  if (!amber.length) lines.push('_none_');
  const byKind = {};
  amber.forEach(b => { (byKind[b.kind] = byKind[b.kind] || []).push(b); });
  for (const kind of Object.keys(byKind)) {
    lines.push('### ' + kind + ' (' + byKind[kind].length + ')');
    lines.push('');
    for (const b of byKind[kind]) {
      lines.push('- [ ] **' + b.id + '** — ' + b.title);
      for (const d of b.verifier.diff) {
        const parts = [];
        if (d.missing && d.missing.length) parts.push('MISSING from board: ' + d.missing.join(', '));
        if (d.extra && d.extra.length) parts.push('EXTRA on board: ' + d.extra.join(', '));
        if (d.valueDiffs && d.valueDiffs.length) parts.push('VALUE differs: ' + d.valueDiffs.join('; '));
        lines.push('  - vs ' + d.source + ': ' + parts.join(' · '));
      }
      lines.push('  - board top 10: ' + b.items.slice(0, 10).map(it => it.answer.replace(/\s*\(.*$/, '') + ' ' + it.hint.replace(/\s.*$/, '')).join(', '));
    }
    lines.push('');
  }
  if (partial.length) {
    lines.push('## In-season boards (' + partial.length + ') — frozen mid-season, rebuild when ' + thisYearOf(partial) + ' ends');
    lines.push('');
    lines.push(partial.map(b => b.id).join(', '));
    lines.push('');
  }
  lines.push('## Skipped (' + skips.length + ') — fewer than ' + MIN_ITEMS + ' items or no board');
  lines.push('');
  if (!skips.length) lines.push('_none_');
  skips.forEach(s => lines.push('- ' + s.id + ' — ' + s.reason));
  lines.push('');
  fs.mkdirSync(path.dirname(REPORT_FILE), { recursive: true });
  fs.writeFileSync(REPORT_FILE, lines.join('\n'));

  const avg = timing.length ? Math.round(timing.reduce((a, b) => a + b, 0) / timing.length) : 0;
  const summary = { built, site: SITE_DIR, out: OUT_FILE, sizeMb: +sizeMb, boards: boards.length, totalSeconds: Math.round((Date.now() - t0) / 1000), avgBoardMs: avg, maxBoardMs: Math.max(0, ...timing), verifier: { green: count('verifier', 'green'), amber: count('verifier', 'amber'), none: count('verifier', 'none') }, pfr: { green: count('pfr', 'green'), amber: count('pfr', 'amber'), na: count('pfr', 'na') }, partial: partial.length, skips };
  fs.writeFileSync(LOG_FILE, JSON.stringify(summary, null, 1));
  log('wrote ' + OUT_FILE + ' (' + sizeMb + ' MB, ' + boards.length + ' boards)');
  log('report ' + REPORT_FILE + ' · amber ' + amber.length + ' · skips ' + skips.length);
  log('done in ' + summary.totalSeconds + ' s (avg ' + avg + ' ms / board, max ' + summary.maxBoardMs + ' ms)');
}

function thisYearOf(partial) { return partial.length ? partial[0].season : new Date().getFullYear(); }

main().catch(e => { console.error(e && e.stack || e); process.exit(1); });
