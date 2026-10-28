// Daily Trivia — build a board with the SITE'S OWN generator.
//
// Rather than re-implementing the career/season/game aggregation (three data
// sources, name-collision fixes, team attribution…), this drives the real
// trivia page headlessly: the checkout on disk is served to a Playwright
// browser under a fake origin, the structured filters are applied exactly as
// _triviaApplyTemplate does, _triviaGenerate() builds the board, and the
// verifier banner _renderBoard draws is read back. The locked snapshot is
// therefore identical to what LOCK AS DAILY would save from the admin UI.
//
// Browser: Playwright from tests/node_modules; bundled Chromium is invisible
// to Task Scheduler (lives in the Claude app's private AppData), so fall back
// to the installed Edge / Chrome like sim_lab/export_notes.js does.
'use strict';

const fs = require('fs');
const path = require('path');

const MAIN_CHECKOUT = 'E:\\MyFantasyFootball\\MyFantasyFootball Files';
const ORIGIN = 'https://mff-trivia.local';
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.woff2': 'font/woff2', '.woff': 'font/woff', '.webmanifest': 'application/manifest+json', '.txt': 'text/plain; charset=utf-8' };

function requirePlaywright(repoDir) {
  const tries = [
    path.join(repoDir, 'tests', 'node_modules', 'playwright'),
    path.join(MAIN_CHECKOUT, 'tests', 'node_modules', 'playwright'),
    'playwright',
  ];
  const errs = [];
  for (const t of tries) {
    try { return require(t); } catch (e) { errs.push(t + ': ' + (e && e.message || e).split('\n')[0]); }
  }
  throw new Error('playwright not found: ' + errs.join(' | '));
}

async function launchBrowser(chromium, log) {
  const tries = [['bundled headless shell', {}], ['bundled chromium', { channel: 'chromium' }], ['installed Edge', { channel: 'msedge' }], ['installed Chrome', { channel: 'chrome' }]];
  const errs = [];
  for (const [label, opt] of tries) {
    try {
      const b = await chromium.launch(Object.assign({ headless: true }, opt));
      log('browser: ' + label + (errs.length ? ' (fallback)' : ''));
      return b;
    } catch (e) { errs.push(label + ': ' + String(e && e.message || e).split('\n')[0]); }
  }
  throw new Error('no browser could be launched | ' + errs.join(' | '));
}

// Serve the checkout from disk under ORIGIN (no http-server process to leak).
async function routeSite(context, siteDir) {
  await context.route(ORIGIN + '/**', async (route) => {
    const u = new URL(route.request().url());
    let p = decodeURIComponent(u.pathname);
    if (p === '/' || p === '') p = '/index.html';
    const file = path.join(siteDir, p.replace(/^\/+/, ''));
    if (!file.startsWith(siteDir) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      return route.fulfill({ status: 404, body: 'not found' });
    }
    const ext = path.extname(file).toLowerCase();
    return route.fulfill({ status: 200, body: fs.readFileSync(file), headers: { 'content-type': MIME[ext] || 'application/octet-stream', 'cache-control': 'no-store' } });
  });
}

// Runs inside the page: mirror _triviaApplyTemplate, generate, read back.
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
  if (f.draftRound != null) applied.draftRound = setVal('triviaFilterDraftRound', f.draftRound);
  applied.seasonType = setVal('triviaFilterSeasonType', f.seasonType || 'reg');
  // Every select must have accepted its value — an unknown option leaves
  // '' behind and the generator would silently build the wrong board.
  const bad = Object.keys(applied).filter(k => applied[k] === '' || applied[k] === undefined);
  if (bad.length) return { error: 'filter not accepted by the page: ' + bad.join(',') };
  const wanted = new Set(f.positions || ['QB', 'RB', 'WR', 'TE']);
  const wrap = document.getElementById('triviaFilterPos');
  wrap.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    const should = wanted.has(cb.value);
    if (cb.checked !== should) { cb.checked = should; cb.dispatchEvent(new Event('change', { bubbles: true })); }
  });
  const cust = document.getElementById('triviaCustomPromptToggle');
  if (cust && cust.checked) { cust.checked = false; cust.dispatchEvent(new Event('change', { bubbles: true })); }
  const nameEl = document.getElementById('triviaGameName');
  if (nameEl) nameEl.value = spec.title || '';
  const cw = document.getElementById('triviaColorway');
  if (cw && spec.colorway) cw.value = spec.colorway;
  const lo = document.getElementById('triviaLayout');
  if (lo) lo.value = 'auto';
  window._triviaData = null;
  await window._triviaGenerate();
  const data = window._triviaData;
  if (!data || !data.items) return { error: 'generator produced no board', area: (document.getElementById('triviaBoardArea') || {}).textContent };
  // Verifier banner drawn by _renderBoard: green = verified, amber = flagged.
  const banner = document.getElementById('triviaVerifyBanner');
  let bannerStatus = 'none', bannerText = '';
  if (banner) {
    const bg = banner.style.background || '';
    bannerStatus = /34,\s*197,\s*94/.test(bg) ? 'verified' : /245,\s*158,\s*11/.test(bg) ? 'flagged' : 'unknown';
    bannerText = (banner.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 600);
  }
  // Independent team cross-check (the site's cross-check ignores the team
  // filter, so a team board always trips it): aggregate LEGEND_CAREERS +
  // D[].career per player, credit each season to its team, keep players
  // whose primary team is the board's team, and compare the top-10 SET.
  let alt = null;
  if (f.type === 'career' && f.team && f.team !== 'all' && !f.seasonType) {
    const dPos = {}; D.forEach(d => { if (d.n && d.s) dPos[d.n] = d.s; });
    const positions = new Set(f.positions || []);
    const stat = f.stat;
    const val = s => { if (stat === 'totalTd') return (s.ptd || 0) + (s.rtd || 0) + (s.rctd || 0); if (stat === 'rec') return s.rc || 0; if (stat === 'ppg' || stat === 'fpts') return s.fpts || 0; return s[stat] || 0; };
    // Same source rule as the site's D[].career bind (_bestCareer): the
    // longer career wins, total fantasy points break a tie — LEGEND_CAREERS
    // for retired players, d.js for active ones whose legend entry is short.
    const fsum = c => c.reduce((t, s) => t + ((s && s.fpts) || 0), 0);
    const better = (a, b) => !b ? a : !a ? b : (a.length > b.length || (a.length === b.length && fsum(a) >= fsum(b))) ? a : b;
    const src = {};
    if (typeof LEGEND_CAREERS !== 'undefined') for (const n in LEGEND_CAREERS) if (LEGEND_CAREERS[n] && LEGEND_CAREERS[n].length) src[n] = LEGEND_CAREERS[n];
    D.forEach(d => { if (d.career && d.career.length) src[d.n] = better(d.career, src[d.n]); });
    // Career arrays end at the last completed season; the generator also
    // counts this season's weekly rows, so top those up from WEEKLY_STATS for
    // seasons the career array does not cover (and only those).
    const wval = w => { if (stat === 'totalTd') return (w.ptd || 0) + (w.rtd || 0) + (w.rctd || 0); if (stat === 'rec') return w.rec || 0; if (stat === 'ppg' || stat === 'fpts') return w.fpts || 0; return w[stat] || 0; };
    const out = [];
    for (const name in src) {
      if (!positions.has(dPos[name] || '')) continue;
      let total = 0; const byTeam = {}; const have = new Set();
      for (const s of src[name]) {
        if (!s || !s.yr) continue;
        have.add(+s.yr);
        const v = val(s); total += v;
        const tm = s.tm || (typeof getCareerTeamAbbr === 'function' ? getCareerTeamAbbr(name, s.yr, '') : '');
        if (tm) byTeam[tm] = (byTeam[tm] || 0) + v;
      }
      const ws = (typeof WEEKLY_STATS !== 'undefined') ? WEEKLY_STATS[name] : null;
      if (ws && ws.seasons) {
        for (const yr in ws.seasons) {
          if (have.has(+yr)) continue;
          for (const w of ws.seasons[yr]) {
            if (!w || !(w.fpts > 0 || w.py > 0 || w.ry > 0 || w.rec > 0)) continue;
            const v = wval(w); total += v;
            const tm = w.tm || (typeof getCareerTeamAbbr === 'function' ? getCareerTeamAbbr(name, +yr, '') : '');
            if (tm) byTeam[tm] = (byTeam[tm] || 0) + v;
          }
        }
      }
      let best = '', bv = -1;
      for (const tm in byTeam) if (byTeam[tm] > bv) { bv = byTeam[tm]; best = tm; }
      if (best === f.team && total > 0) out.push({ name, val: total });
    }
    const norm = n => (n || '').replace(/\s+(Sr\.?|Jr\.?|II|III|IV)$/i, '').trim().toLowerCase();
    // The site merges suffix variants of one player ("Marvin Jones" /
    // "Marvin Jones Jr." carry the same career twice); keep one per name.
    const byNorm = {};
    out.forEach(x => { const k = norm(x.name); if (!byNorm[k] || byNorm[k].val < x.val) byNorm[k] = x; });
    out.length = 0; Object.values(byNorm).forEach(x => out.push(x));
    out.sort((a, b) => b.val - a.val);
    const depth = Math.min(10, out.length, (data._topN || []).length);
    const a = new Set((data._topN || []).slice(0, depth).map(x => norm(x.name)));
    const b = new Set(out.slice(0, depth).map(x => norm(x.name)));
    const missing = [...b].filter(x => !a.has(x)), extra = [...a].filter(x => !b.has(x));
    alt = { depth, ok: depth >= 10 && missing.length === 0 && extra.length === 0, missing, extra, altCount: out.length, altTop: out.slice(0, 12).map(x => x.name + ' ' + Math.round(x.val)) };
  }
  const items = data.items.map(it => ({
    rank: it.rank != null ? it.rank : '',
    answer: it.answer || '',
    value: it.value != null ? it.value : '',
    hint: it.hint || '',
    team: it.team || '',
    category: it.category || '',
    headshot: it.headshot || '',
  }));
  return { title: data.title || '', items, filter: data._filter || null, topN: (data._topN || []).slice(0, 12), bannerStatus, bannerText, alt, layout: lo ? lo.value : 'auto' };
}

const normName = n => String(n || '').split(/[\(\,]/)[0].replace(/\s+(Sr\.?|Jr\.?|II|III|IV)$/i, '').replace(/[^a-z ]/gi, '').replace(/\s+/g, ' ').trim().toLowerCase();
function hasPlayer(items, name) {
  const k = normName(name);
  return !!k && items.some(it => normName(it.answer) === k);
}

function judge(variant, r, mustInclude) {
  if (r.error) return { ok: false, why: r.error };
  if (r.items.length < 16) return { ok: false, why: 'only ' + r.items.length + ' items' };
  // News boards must carry the player in the news (Jack 2026-10-28).
  if (mustInclude && !hasPlayer(r.items, mustInclude)) return { ok: false, why: mustInclude + ' is not on the board', missingPlayer: true };
  if (variant.kind === 'list') return { ok: true, status: 'list' };
  // A single-game board where one player owns a quarter of the cells
  // (a franchise list of Derrick Henry games) is a bad guessing game.
  if (variant.kind === 'game') {
    const counts = {};
    r.items.forEach(it => { const k = normName(it.answer); counts[k] = (counts[k] || 0) + 1; });
    const top = Object.keys(counts).sort((a, b) => counts[b] - counts[a])[0];
    if (top && counts[top] > r.items.length / 4) return { ok: false, why: top + ' holds ' + counts[top] + ' of ' + r.items.length + ' cells' };
  }
  if (r.bannerStatus === 'flagged' && variant.kind !== 'team') return { ok: false, why: 'verifier flagged: ' + r.bannerText.slice(0, 200) };
  if (variant.kind === 'team') {
    if (!r.alt) return { ok: false, why: 'team cross-check did not run' };
    if (!r.alt.ok) return { ok: false, why: 'team cross-check mismatch (missing: ' + r.alt.missing.join(', ') + '; extra: ' + r.alt.extra.join(', ') + '; alt top: ' + r.alt.altTop.slice(0, 10).join(', ') + ')' };
    return { ok: true, status: 'cross-ok' };
  }
  if (variant.kind === 'career' || variant.kind === 'post') {
    if (r.bannerStatus !== 'verified') return { ok: false, why: 'no green verifier banner (' + r.bannerStatus + ')' };
    return { ok: true, status: 'verified' };
  }
  // game / week / draft boards have no reference table on the site either —
  // same standard as the template pool's own single-game and draft entries.
  return { ok: true, status: 'unchecked' };
}

// Build the first variant of each theme (in order) that passes. Returns
// { theme, variant, result, judged, tried: [...] } or null.
async function buildFirstPassing(themes, opts) {
  const log = opts.log || (() => {});
  const siteDir = path.resolve(opts.siteDir);
  const tried = [];
  let browser = null, page = null;
  // List-only candidates need no browser at all.
  const needSite = themes.some(t => !t.skipped && t.variants.some(v => v.kind !== 'list'));
  try {
    if (needSite) {
    const { chromium } = requirePlaywright(siteDir);
    browser = await launchBrowser(chromium, log);
    const context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1400, height: 900 } });
    await context.addInitScript(() => { try { localStorage.setItem('mff_seen_intro', '1'); } catch (_) {} });
    await routeSite(context, siteDir);
    page = await context.newPage();
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
      await Promise.all(ps);
    });
    await page.waitForFunction(() => typeof LEGEND_CAREERS !== 'undefined' && typeof D !== 'undefined' && D.some(d => d._retired && d.career && d.career.length > 5) && typeof WEEKLY_STATS !== 'undefined' && Object.keys(WEEKLY_STATS).length > 2000, null, { timeout: 120000 });
    const stats = await page.evaluate(() => ({ D: D.length, legends: Object.keys(LEGEND_CAREERS).length, weekly: Object.keys(WEEKLY_STATS).length, seasonLeaders: typeof SEASON_LEADERS !== 'undefined' }));
    log('site data: D=' + stats.D + ' legends=' + stats.legends + ' weekly=' + stats.weekly + ' seasonLeaders=' + stats.seasonLeaders);
    if (pageErrors.length) log('page errors (' + pageErrors.length + '): ' + pageErrors.slice(0, 3).join(' | '));
    }

    for (const theme of themes) {
      if (theme.skipped) { log('skip ' + theme.kind + ' (' + theme.reason + '): ' + theme.skipped); continue; }
      // Pass 1 requires the news player on the board; themes marked
      // includeSoft (big game, record) get a second pass without him
      // rather than losing the theme altogether.
      const passes = theme.mustInclude ? (theme.includeSoft ? [theme.mustInclude, null] : [theme.mustInclude]) : [null];
      for (const mustInclude of passes) {
      if (mustInclude === null && passes.length > 1) log('no board carried ' + theme.mustInclude + ' — retrying without him');
      for (const variant of theme.variants) {
        if (variant.kind === 'list') {
          // Built in Node from nflverse data; no site generator involved.
          log('list ' + variant.key + ' — "' + variant.title + '" (' + variant.items.length + ' items)');
          const result = { title: variant.title, items: variant.items, filter: null, topN: [], bannerStatus: 'none', bannerText: '', alt: null, layout: 'auto' };
          const judged = judge(variant, result, mustInclude);
          tried.push({ theme: theme.kind, variant: variant.key, ok: judged.ok, why: judged.why || judged.status, items: result.items.length, banner: 'none' });
          log('  → ' + (judged.ok ? 'OK (list, ' + result.items.length + ' items)' : 'rejected: ' + judged.why));
          if (judged.ok) return { theme, variant, result, judged, tried };
          continue;
        }
        if (!page) { log('skip ' + variant.key + ': no browser for site boards'); continue; }
        // A news player outside the top 20 gets the board widened to 25,
        // then 30 (the site's count options) before the variant is dropped.
        const counts = mustInclude ? [variant.filters.count || 20, 25, 30] : [variant.filters.count || 20];
        for (const count of counts) {
          const filters = Object.assign({}, variant.filters, { count });
          log('build ' + variant.key + (count !== (variant.filters.count || 20) ? ' (top ' + count + ')' : '') + ' — "' + variant.title + '"');
          const result = await page.evaluate(pageBuild, { filters, title: variant.title, colorway: theme.colorway || 'purple' });
          const judged = judge(variant, result, mustInclude);
          tried.push({ theme: theme.kind, variant: variant.key, count, ok: judged.ok, why: judged.why || judged.status, items: result.items ? result.items.length : 0, banner: result.bannerStatus });
          log('  → ' + (judged.ok ? 'OK (' + judged.status + ', ' + result.items.length + ' items)' : 'rejected: ' + judged.why + (result.topN ? ' | rendered top: ' + result.topN.slice(0, 10).map(x => x.name + ' ' + Math.round(x.val)).join(', ') : '')));
          if (judged.ok) return { theme, variant: Object.assign({}, variant, { filters }), result, judged, tried };
          if (!judged.missingPlayer) break; // widening only helps the missing-player case
        }
      }
      }
    }
    return { theme: null, variant: null, result: null, judged: null, tried };
  } finally {
    if (browser) await browser.close().catch(() => {});
  }
}

module.exports = { buildFirstPassing, judge, hasPlayer, normName, ORIGIN };
