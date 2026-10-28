// Daily Trivia theme picker — news / stats / market signals.
//
// Everything here reads the SAME site data the trivia templates use, from the
// repo checkout on disk (data/*.js evaluated in a sandbox) plus the daily
// news-scan feed. The news feed is fetched from the live site first (the
// cloud routine commits it at ~6pm ET and GitHub Pages serves it minutes
// later) with the on-disk copy as fallback, so a stale local pull never
// hides tonight's news.
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const cal = require('./calendar');

const LIVE_BASE = 'https://www.myfantasyfootball.co/';
const FIRESTORE_PROJECT = 'jackb933-website';
// Public web API key (the one index.html ships to every visitor). Reads of
// trivia_daily are allowed to everyone by firestore.rules; this key grants
// nothing beyond that.
const FIREBASE_WEB_KEY = 'AIzaSyD9D_Rhb5hEpz2cBWqQr7hcFCDoluwq6uY';

function evalDataFile(repoDir, rel, globalsWanted) {
  const src = fs.readFileSync(path.join(repoDir, rel), 'utf8');
  const out = {};
  const sandbox = { console: { log() {}, warn() {}, error() {} }, document: { addEventListener() {} }, __capture: (o) => Object.assign(out, o) };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  // Top-level `const`/`let` declarations stay in the script's own scope (not
  // on the sandbox object), so capture them from inside the same script.
  const tail = '\n;__capture({' + globalsWanted.map(g => g + ': (typeof ' + g + ' !== "undefined" ? ' + g + ' : undefined)').join(',') + '});';
  vm.runInContext(src + tail, sandbox, { filename: rel });
  return out;
}

async function fetchJson(url, timeoutMs) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs || 15000);
  try {
    const r = await fetch(url, { signal: ctl.signal, headers: { 'cache-control': 'no-cache' } });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.json();
  } finally { clearTimeout(t); }
}

// --- players (d.js) ---
function loadPlayers(repoDir) {
  const { D } = evalDataFile(repoDir, 'data/d.js', ['D']);
  const { TEAM_ABBR_MAP } = evalDataFile(repoDir, 'data/team_abbr_map.js', ['TEAM_ABBR_MAP']);
  const byName = Object.create(null);
  const norm = (n) => String(n || '').toLowerCase().replace(/\s+(jr\.?|sr\.?|ii|iii|iv|v)$/i, '').replace(/[^a-z ]/g, '').replace(/\s+/g, ' ').trim();
  const byNorm = Object.create(null);
  (D || []).forEach(d => {
    if (!d || !d.n) return;
    byName[d.n] = d;
    const k = norm(d.n);
    if (!byNorm[k]) byNorm[k] = d;
  });
  const abbrToFull = {};
  Object.keys(TEAM_ABBR_MAP || {}).forEach(full => { abbrToFull[TEAM_ABBR_MAP[full]] = full; });
  function find(name) {
    if (!name) return null;
    return byName[name] || byNorm[norm(name)] || null;
  }
  function teamAbbr(d) {
    if (!d || !d.t) return '';
    return TEAM_ABBR_MAP[d.t] || (d.t.length <= 3 ? d.t : '');
  }
  // "Star" = a player people are actually talking about: top-60 overall or a
  // fantasy starter at his position. General rule, no per-player list.
  function isStar(d) {
    if (!d) return false;
    if (typeof d.a === 'number' && d.a <= 60) return true;
    const m = /^([A-Z]+)(\d+)$/.exec(d.r || '');
    if (!m) return false;
    const pos = m[1], rk = parseInt(m[2], 10);
    if (pos === 'QB' || pos === 'TE') return rk <= 12;
    if (pos === 'RB' || pos === 'WR') return rk <= 24;
    return false;
  }
  return { D, find, teamAbbr, abbrToFull, TEAM_ABBR_MAP, isStar, norm };
}

// --- news feed (daily NFL fantasy news scan) ---
async function loadNews(repoDir, opts) {
  const o = opts || {};
  let feed = null, source = '';
  if (!o.offline) {
    try {
      feed = await fetchJson(LIVE_BASE + 'data/camp_news_2026.json?d=' + Date.now());
      source = 'live';
    } catch (e) { feed = null; }
  }
  if (!feed) {
    try {
      feed = JSON.parse(fs.readFileSync(path.join(repoDir, 'data/camp_news_2026.json'), 'utf8'));
      source = 'disk';
    } catch (e) { feed = { items: [] }; source = 'none'; }
  }
  return { items: feed.items || [], updated: feed.updated || '', source };
}

// --- weekly stats (current season game logs) ---
// Returns the latest week with a real slate plus every notable single-game
// line in it. Thresholds are per-stat and deliberately high: a 175-yard
// rushing day or a five-TD passing game is "lean into it" territory.
const BIG_GAME_RULES = [
  { stat: 'ry',   min: 175, label: 'rushing yards' },
  { stat: 'rcy',  min: 175, label: 'receiving yards' },
  { stat: 'py',   min: 400, label: 'passing yards' },
  { stat: 'rtd',  min: 3,   label: 'rushing TDs' },
  { stat: 'rctd', min: 3,   label: 'receiving TDs' },
  { stat: 'ptd',  min: 5,   label: 'passing TDs' },
  { stat: 'fpts', min: 40,  label: 'fantasy points' },
];

function loadBigGames(repoDir, seasonYear, players) {
  let WS;
  try { WS = evalDataFile(repoDir, 'data/weekly_stats_active.js', ['WEEKLY_STATS_ACTIVE']).WEEKLY_STATS_ACTIVE; }
  catch (e) { return { week: null, games: [] }; }
  if (!WS) return { week: null, games: [] };
  const key = String(seasonYear);
  const counts = {};
  const rows = [];
  for (const name in WS) {
    const s = WS[name] && WS[name].seasons && WS[name].seasons[key];
    if (!s) continue;
    for (const w of s) {
      if (!w || !(w.fpts > 0)) continue;
      counts[w.wk] = (counts[w.wk] || 0) + 1;
      rows.push({ name, pos: WS[name].pos || '', wk: w.wk, opp: w.opp || '', w });
    }
  }
  // Latest week with a full slate (>= 60 scoring players ≈ 8+ games played).
  const weeks = Object.keys(counts).map(Number).filter(wk => counts[wk] >= 60).sort((a, b) => b - a);
  const week = weeks.length ? weeks[0] : null;
  if (!week) return { week: null, games: [] };
  const games = [];
  rows.filter(r => r.wk === week).forEach(r => {
    for (const rule of BIG_GAME_RULES) {
      const v = r.w[rule.stat] || 0;
      if (v >= rule.min) {
        const d = players.find(r.name);
        games.push({ name: r.name, pos: (d && d.s) || r.pos, team: players.teamAbbr(d), opp: r.opp, stat: rule.stat, value: v, label: rule.label, ratio: v / rule.min, week });
      }
    }
  });
  games.sort((a, b) => b.ratio - a.ratio);
  return { week, games };
}

// --- fantasy trade market (Sleeper redraft crawl) ---
function loadMostTraded(repoDir, players) {
  let j;
  try { j = JSON.parse(fs.readFileSync(path.join(repoDir, 'data/real_trades_redraft.json'), 'utf8')); }
  catch (e) { return null; }
  const trades = j.trades || [];
  if (!trades.length) return null;
  // Same cutoff the site uses: the most recent Tuesday 04:00 UTC.
  const now = new Date();
  const cut = new Date(now);
  const day = cut.getUTCDay(); // 0 Sun … 2 Tue
  let back = (day - 2 + 7) % 7;
  if (back === 0 && (cut.getUTCHours() < 4)) back = 7;
  cut.setUTCDate(cut.getUTCDate() - back);
  cut.setUTCHours(4, 0, 0, 0);
  const counts = {};
  trades.forEach(t => {
    if (!t.date || new Date(t.date) < cut) return;
    [].concat(t.s1 || [], t.s2 || []).forEach(p => {
      if (!p || !p.n || p.p === 'FAAB') return;
      counts[p.n] = (counts[p.n] || 0) + 1;
    });
  });
  const top = Object.keys(counts).map(n => ({ name: n, count: counts[n] })).sort((a, b) => b.count - a.count);
  if (!top.length) return null;
  const d = players.find(top[0].name);
  return { name: top[0].name, count: top[0].count, pos: (d && d.s) || '', team: players.teamAbbr(d), since: cut.toISOString(), generated: j.generated || '' };
}

// --- locked-daily history (Firestore, public read) ---
async function loadLockHistory(limit) {
  const body = {
    structuredQuery: {
      from: [{ collectionId: 'trivia_daily' }],
      select: { fields: [{ fieldPath: 'date' }, { fieldPath: 'title' }, { fieldPath: 'source' }, { fieldPath: 'itemCount' }, { fieldPath: 'auto' }] },
      orderBy: [{ field: { fieldPath: 'date' }, direction: 'DESCENDING' }],
      limit: limit || 30,
    },
  };
  const url = 'https://firestore.googleapis.com/v1/projects/' + FIRESTORE_PROJECT + '/databases/(default)/documents:runQuery?key=' + FIREBASE_WEB_KEY;
  const r = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error('Firestore query HTTP ' + r.status);
  const rows = await r.json();
  const val = (f) => {
    if (!f) return undefined;
    if ('stringValue' in f) return f.stringValue;
    if ('integerValue' in f) return parseInt(f.integerValue, 10);
    if ('doubleValue' in f) return f.doubleValue;
    if ('booleanValue' in f) return f.booleanValue;
    if ('mapValue' in f) { const o = {}; const m = f.mapValue.fields || {}; for (const k in m) o[k] = val(m[k]); return o; }
    return undefined;
  };
  return rows.filter(r => r.document).map(r => {
    const f = r.document.fields || {};
    return { date: val(f.date), title: val(f.title), source: val(f.source) || 'admin', itemCount: val(f.itemCount), auto: val(f.auto) || null };
  });
}

async function collectSignals(opts) {
  const repoDir = opts.repoDir;
  const date = opts.date;
  const players = loadPlayers(repoDir);
  const calendar = cal.calendarContext(date);
  const news = await loadNews(repoDir, { offline: !!opts.offline });
  // News lookback: the scan runs once a day, so take the last 3 feed dates.
  const since = cal.addDays(date, -3);
  const recentNews = news.items.filter(i => i && i.date && i.date >= since && i.date <= date);
  const bigGames = calendar.postGameDays ? loadBigGames(repoDir, calendar.seasonYear, players) : { week: null, games: [] };
  const mostTraded = calendar.inSeason ? loadMostTraded(repoDir, players) : null;
  let history = [];
  if (!opts.offline) {
    try { history = await loadLockHistory(30); } catch (e) { history = []; opts.log && opts.log('history unavailable: ' + e.message); }
  }
  return { date, repoDir, players, calendar, news: { source: news.source, updated: news.updated, recent: recentNews }, bigGames, mostTraded, history };
}

module.exports = { collectSignals, loadPlayers, loadNews, loadBigGames, loadMostTraded, loadLockHistory, evalDataFile, BIG_GAME_RULES, LIVE_BASE };
