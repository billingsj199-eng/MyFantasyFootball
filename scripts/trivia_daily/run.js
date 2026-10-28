#!/usr/bin/env node
// Daily Trivia — news-driven board for TOMORROW.
//
//   node scripts/trivia_daily/run.js plan  [--date YYYY-MM-DD] [--offline]
//       read the signals, print every candidate theme (no browser, no write)
//   node scripts/trivia_daily/run.js build [--date YYYY-MM-DD] [--theme KEY] [--out FILE]
//       plan + build the winning board headlessly, save the lock doc as JSON
//   node scripts/trivia_daily/run.js lock  [--date YYYY-MM-DD] [--theme KEY]
//       plan + build + write trivia_daily/{date} (the scheduled job's command)
//
// Dates are US Eastern. Default date = tomorrow. The job never overwrites a
// board Jack locked by hand (the Cloud Function refuses with 409); it does
// replace an earlier auto board for the same date so fresher news wins.
'use strict';

const fs = require('fs');
const path = require('path');
const cal = require('./calendar');
const { collectSignals } = require('./signals');
const { pickThemes } = require('./themes');
const { buildFirstPassing } = require('./build_board');
const { postLock, LOCK_URL } = require('./lock');

const VERSION = '2026-10-28';
const REPO_DIR = path.resolve(__dirname, '..', '..');

function arg(name, def) {
  const i = process.argv.indexOf('--' + name);
  if (i === -1) return def;
  const v = process.argv[i + 1];
  return (v === undefined || v.startsWith('--')) ? true : v;
}
function log(msg) { console.log('[' + new Date().toISOString().slice(11, 19) + '] ' + msg); }

function summarize(sig, themes) {
  const c = sig.calendar;
  log('date ' + sig.date + ' (ET) · season ' + c.seasonYear + ' · NFL week ' + (c.nflWeek || '—') + ' · weekday ' + c.weekday);
  const flags = Object.keys(c).filter(k => c[k] === true).join(', ');
  log('calendar flags: ' + (flags || 'none'));
  log('news: ' + sig.news.recent.length + ' items in the last 3 days (' + sig.news.source + ', updated ' + sig.news.updated + ')');
  if (sig.bigGames.week) log('big games wk ' + sig.bigGames.week + ': ' + (sig.bigGames.games.slice(0, 3).map(g => g.name + ' ' + g.value + ' ' + g.label).join('; ') || 'none'));
  if (sig.mostTraded) log('most traded (fantasy): ' + sig.mostTraded.name + ' ×' + sig.mostTraded.count);
  const already = sig.history.find(h => h.date === sig.date);
  if (already) log('ALREADY LOCKED for ' + sig.date + ': "' + already.title + '" (' + already.source + ')');
  log('recent locks: ' + (sig.history.slice(0, 5).map(h => h.date + ' ' + (h.source === 'auto' ? '[auto] ' : '') + h.title).join(' | ') || 'none'));
  if (!themes.length) { log('candidates: none → nothing to lock, the template cycle runs'); return; }
  log('candidates:');
  themes.forEach((t, i) => {
    log('  ' + (i + 1) + '. [' + t.score + '] ' + t.kind + ' — ' + t.reason + (t.skipped ? ' — SKIPPED: ' + t.skipped : ''));
    if (t.mustInclude) log('       must include: ' + t.mustInclude);
    t.variants.forEach(v => log('       · ' + v.key + ' → "' + v.title + '"' + (v.kind === 'list' ? (v.items ? ' (' + v.items.length + ' rows)' : ' (college, built on demand)') : '')));
  });
}

async function main() {
  const cmd = process.argv[2] || 'plan';
  const date = arg('date', cal.addDays(cal.todayET(), 1));
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new Error('bad --date');
  const offline = !!arg('offline', false);
  const themeKey = arg('theme', null);
  log('trivia daily v' + VERSION + ' · ' + cmd + ' · repo ' + REPO_DIR);

  const sig = await collectSignals({ repoDir: REPO_DIR, date, offline, log });
  let themes = pickThemes(sig);
  if (themeKey) {
    themes = themes.filter(t => t.kind === themeKey || t.key === themeKey || t.variants.some(v => v.key === themeKey));
    themes.forEach(t => { t.skipped = null; if (t.variants.some(v => v.key === themeKey)) t.variants = t.variants.filter(v => v.key === themeKey); });
    if (!themes.length) throw new Error('no candidate matches --theme ' + themeKey);
  }
  summarize(sig, themes);
  if (cmd === 'plan') return;

  const already = sig.history.find(h => h.date === date);
  if (already && already.source !== 'auto' && !themeKey) {
    log('Jack locked ' + date + ' by hand — leaving it alone.');
    return;
  }
  const live = themes.filter(t => !t.skipped);
  if (!live.length) { log('nothing qualifies → no lock (template cycle runs)'); return; }

  const built = await buildFirstPassing(live, { siteDir: REPO_DIR, log });
  if (!built.theme) { log('no candidate produced a passing board → no lock'); return; }
  const { theme, variant, result, judged } = built;
  const doc = {
    date,
    title: result.title || variant.title,
    desc: (variant.kind === 'list' && theme.kind !== 'trade' && variant.desc) ? variant.desc : (theme.desc || ''),
    items: result.items,
    itemCount: result.items.length,
    colorway: theme.colorway || 'purple',
    customColor: null,
    layout: result.layout || 'auto',
    lockedBy: 'auto-trivia-daily',
    lockedByEmail: '',
    lockedAt: new Date().toISOString(),
    source: 'auto',
    auto: {
      version: VERSION,
      key: variant.key,
      kind: theme.kind,
      score: theme.score,
      reason: theme.reason,
      hook: theme.hook || null,
      filters: variant.filters,
      verify: { status: judged.status, banner: result.bannerStatus, bannerText: result.bannerText || '', alt: result.alt || null },
      topN: result.topN,
      tried: built.tried,
      newsSource: sig.news.source,
    },
  };
  log('board: "' + doc.title + '" · ' + doc.itemCount + ' items · ' + judged.status + ' · ' + theme.reason);
  log('desc: ' + doc.desc);
  log('top 5: ' + result.topN.slice(0, 5).map(x => x.name + ' ' + x.val).join(', '));

  const out = arg('out', null) || (cmd === 'build' ? path.join(require('os').tmpdir(), 'trivia_daily_' + date + '.json') : null);
  if (out) { fs.writeFileSync(out, JSON.stringify(doc, null, 1)); log('wrote ' + out); }
  if (cmd !== 'lock') return;

  const res = await postLock(doc);
  if (res.status === 200 && res.body && res.body.ok) {
    log('LOCKED ' + date + (res.body.replaced ? ' (replaced earlier auto board)' : '') + ' via ' + LOCK_URL);
  } else if (res.status === 409) {
    log('not written: ' + ((res.body && res.body.error) || 'conflict') + ' (Jack\'s lock stands)');
  } else {
    throw new Error('lock failed: HTTP ' + res.status + ' ' + JSON.stringify(res.body));
  }
}

main().catch(e => { console.error('[trivia-daily] FAILED: ' + (e && e.stack || e)); process.exit(1); });
