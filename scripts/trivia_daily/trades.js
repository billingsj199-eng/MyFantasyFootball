// Daily Trivia — NFL trade + draft history (nflverse, free), for list boards
// that are not stat leaderboards: "traded for a first-round pick", "top-10
// picks who got traded". Jack 2026-10-28: news boards don't have to be
// stats, and the player in the news must be on the board.
//
// Sources (public GitHub release assets, all positions, 2002+ trades /
// 1980+ draft picks):
//   https://github.com/nflverse/nflverse-data/releases/download/trades/trades.csv
//   https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv
// Cached for 24 h OUTSIDE the repo (E:\MyFantasyFootball\trivia_daily_cache),
// so the nightly job never touches git. nflverse lags real trades by days,
// so a trade in tonight's news is injected from the news item itself.
//
// Encoding gotcha: nflverse writes a traded pick that was LATER USED as the
// player it became (the 2018 Mack trade lists "Josh Jacobs" for the 2019
// first), so an asset is a pick when its player's draft came after the
// trade; only assets drafted before the trade are real players.
'use strict';

const fs = require('fs');
const path = require('path');

const CACHE_DIR = process.env.MFF_TRIVIA_CACHE_DIR || 'E:\\MyFantasyFootball\\trivia_daily_cache';
const SOURCES = {
  trades: 'https://github.com/nflverse/nflverse-data/releases/download/trades/trades.csv',
  picks: 'https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv',
};
const MAX_AGE_MS = 24 * 3600 * 1000;
// nflverse → site team codes (the site keeps STL/SD/OAK for old seasons).
const TEAM_FIX = { LA: 'LAR', JAC: 'JAX', WSH: 'WAS' };
const fixTeam = t => TEAM_FIX[t] || t || '';

function parseCsv(text) {
  const rows = [];
  let row = [], field = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else q = false; }
      else field += c;
    } else if (c === '"') q = true;
    else if (c === ',') { row.push(field); field = ''; }
    else if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; }
    else if (c !== '\r') field += c;
  }
  if (field.length || row.length) { row.push(field); rows.push(row); }
  const head = rows.shift();
  return rows.filter(r => r.length === head.length).map(r => { const o = {}; head.forEach((h, i) => o[h] = r[i]); return o; });
}

async function fetchCached(name, url, log) {
  fs.mkdirSync(CACHE_DIR, { recursive: true });
  const file = path.join(CACHE_DIR, name + '.csv');
  let fresh = false;
  try { fresh = (Date.now() - fs.statSync(file).mtimeMs) < MAX_AGE_MS; } catch (_) {}
  if (!fresh) {
    try {
      const r = await fetch(url, { redirect: 'follow' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const text = await r.text();
      if (text.length < 1000) throw new Error('short response');
      fs.writeFileSync(file, text);
      log && log('nflverse ' + name + ': downloaded ' + Math.round(text.length / 1024) + ' KB');
    } catch (e) {
      log && log('nflverse ' + name + ': download failed (' + e.message + ')' + (fs.existsSync(file) ? ', using cached copy' : ''));
    }
  }
  if (!fs.existsSync(file)) return null;
  return parseCsv(fs.readFileSync(file, 'utf8'));
}

// The draft happens late April; a same-season trade dated before May 1 that
// lists a player of that draft class is a pick trade.
function wasPickAtTrade(draft, trade) {
  if (!draft) return false;
  if (draft.year > trade.season) return true;
  if (draft.year === trade.season && (trade.date || '') < trade.season + '-05-01') return true;
  return false;
}

// opts.isKnownPlayer(name) → true when the site knows the name; used only
// to keep undrafted real players (and drop coaches like Sean Payton).
async function loadNflTrades(opts) {
  const o = opts || {};
  const log = o.log;
  const known = o.isKnownPlayer || (() => false);
  const tradeRows = await fetchCached('trades', SOURCES.trades, log);
  const pickRows = await fetchCached('draft_picks', SOURCES.picks, log);
  if (!tradeRows) return null;
  const draftByPfr = {};
  const draftByName = {};
  (pickRows || []).forEach(r => {
    if (!r.pfr_player_id) return;
    const d = { year: +r.season, round: +r.round, pick: +r.pick, team: fixTeam(r.team), pos: r.position, name: r.pfr_player_name, pfr: r.pfr_player_id };
    draftByPfr[r.pfr_player_id] = d;
    if (!draftByName[d.name]) draftByName[d.name] = d;
  });

  const trades = {};
  tradeRows.forEach(r => {
    const t = trades[r.trade_id] || (trades[r.trade_id] = { id: r.trade_id, season: +r.season, date: r.trade_date, assets: [] });
    const a = { gave: fixTeam(r.gave), received: fixTeam(r.received) };
    if (r.pfr_name) { a.name = r.pfr_name; a.pfr = r.pfr_id; }
    else if (r.pick_round) { a.pick = { season: +r.pick_season, round: +r.pick_round, number: r.pick_number ? +r.pick_number : null, conditional: r.conditional === 'TRUE' }; }
    t.assets.push(a);
  });
  // Classify assets: pick (raw or later-used) vs real player.
  Object.values(trades).forEach(t => {
    t.assets.forEach(a => {
      if (a.pick) { a.kind = 'pick'; return; }
      const d = draftByPfr[a.pfr];
      if (wasPickAtTrade(d, t)) { a.kind = 'pick'; a.pick = { season: d.year, round: d.round, number: d.pick, becameName: d.name }; return; }
      if (d || known(a.name)) { a.kind = 'player'; a.draft = d || null; return; }
      a.kind = 'other';
    });
  });
  const all = Object.values(trades).sort((a, b) => (b.date || '').localeCompare(a.date || ''));

  // Players traded for a first-round pick: a real player went one way and a
  // round-1 pick came back the other way in the same trade.
  const tradedForFirst = [];
  all.forEach(t => {
    const firsts = t.assets.filter(a => a.kind === 'pick' && a.pick.round === 1);
    if (!firsts.length) return;
    t.assets.filter(a => a.kind === 'player').forEach(p => {
      const back = firsts.find(f => f.gave === p.received && f.received === p.gave);
      if (!back) return;
      const nFirsts = firsts.filter(f => f.gave === p.received && f.received === p.gave).length;
      tradedForFirst.push({ name: p.name, pfr: p.pfr, year: t.season, date: t.date, from: p.gave, to: p.received, pickSeason: back.pick.season, firsts: nFirsts, pos: p.draft ? p.draft.pos : '' });
    });
  });

  // Top-10 picks later traded (first trade of each player).
  const top10Traded = [];
  const seen = new Set();
  all.forEach(t => {
    t.assets.filter(a => a.kind === 'player' && a.draft).forEach(p => {
      const d = p.draft;
      if (d.pick > 10 || seen.has(p.pfr)) return;
      seen.add(p.pfr);
      top10Traded.push({ name: p.name, pfr: p.pfr, year: t.season, date: t.date, from: p.gave, to: p.received, draftYear: d.year, pick: d.pick, draftTeam: d.team, pos: d.pos });
    });
  });

  return { trades: all, tradedForFirst, top10Traded, draftByPfr, draftByName, updated: all.length ? all[0].date : '' };
}

// Board items (same shape _triviaLockAsDaily saves). `category` is the cell
// header, `hint` the line under the logo, `team` the logo.
function itemsTradedForFirst(list, count) {
  return list.slice(0, count).map(r => ({
    rank: '', value: '', headshot: '',
    answer: r.name,
    category: String(r.year),
    hint: r.from + ' → ' + r.to + (r.firsts > 1 ? ' for ' + r.firsts + ' 1sts' : ' for a 1st'),
    team: r.to,
  }));
}
function itemsTop10Traded(list, count) {
  return list.slice(0, count).map(r => ({
    rank: '', value: '', headshot: '',
    answer: r.name,
    category: 'Pick #' + r.pick + ' · ' + r.draftYear,
    hint: r.from + ' → ' + r.to + ' (' + r.year + ')',
    team: r.to,
  }));
}

module.exports = { loadNflTrades, itemsTradedForFirst, itemsTop10Traded, CACHE_DIR, fixTeam };
