// Daily Trivia — college football boards + college images.
//
// Jack 2026-10-28: "we can also add college football since we have plenty of
// stats … it doesn't need to just be stats, can also be team or awards
// based … I would like college images."
//
// Data (all already in the repo or free):
//   data/college_stats.js      COLLEGE_STATS  name → [{yr, tm (school), conf, py, ry, rec, rcy, …}]
//                               5.5k players, 2004–2025 (dense from 2007) — college years of
//                               NFL / draft-pool players, so "all-time" here means that pool.
//   data/college_weekly_*.js   COLLEGE_WEEKLY name → {yr: [{wk, tm, opp, …}]} game logs
//   data/combine_data.js       COMBINE_DATA   name → {yr (draft year), pos, school, draft}
//   Wikipedia                  List of Heisman Trophy winners (year, name, school, pos, photo)
//   ESPN (keyless)             college-football teams (school → logo) and player search
//                               (college headshots for names the NFL id maps never see)
// Everything fetched is cached outside the repo in E:\MyFantasyFootball\trivia_daily_cache.
'use strict';

const fs = require('fs');
const path = require('path');
const { evalDataFile } = require('./signals');

const CACHE_DIR = process.env.MFF_TRIVIA_CACHE_DIR || 'E:\\MyFantasyFootball\\trivia_daily_cache';
const UA = 'mff-trivia/1.0 (myfantasyfootball.co)';
const STAT_LABEL = { py: 'Passing Yards', ptd: 'Passing TDs', ry: 'Rushing Yards', rtd: 'Rushing TDs', rcy: 'Receiving Yards', rec: 'Receptions', rctd: 'Receiving TDs' };
const STAT_SHORT = { py: 'pass yds', ptd: 'pass td', ry: 'rush yds', rtd: 'rush td', rcy: 'rec yds', rec: 'rec', rctd: 'rec td' };
const FIRST_DENSE_YEAR = 2007;

function cachePath(name) { fs.mkdirSync(CACHE_DIR, { recursive: true }); return path.join(CACHE_DIR, name); }
function readCache(name, maxAgeMs) {
  const p = cachePath(name);
  try { if (Date.now() - fs.statSync(p).mtimeMs < maxAgeMs) return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (_) {}
  return null;
}
function writeCache(name, obj) { fs.writeFileSync(cachePath(name), JSON.stringify(obj)); }
async function getJson(url) {
  const r = await fetch(url, { headers: { 'user-agent': UA } });
  if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + url);
  return r.json();
}

// ---------- stats ----------
function loadCollege(repoDir) {
  const CS = evalDataFile(repoDir, 'data/college_stats.js', ['COLLEGE_STATS']).COLLEGE_STATS || {};
  const CD = evalDataFile(repoDir, 'data/combine_data.js', ['COMBINE_DATA']).COMBINE_DATA || {};
  const D = evalDataFile(repoDir, 'data/d.js', ['D']).D || [];
  const dPos = {}; D.forEach(d => { if (d.n && d.s) dPos[d.n] = d.s; });
  const pos = (name, seasons) => {
    if (dPos[name]) return dPos[name];
    if (CD[name] && CD[name].pos) return CD[name].pos;
    // No label on file: read it off the stat line.
    let py = 0, ry = 0, rcy = 0;
    (seasons || []).forEach(s => { py += s.py || 0; ry += s.ry || 0; rcy += s.rcy || 0; });
    if (py > ry && py > rcy) return 'QB';
    if (ry > rcy) return 'RB';
    return rcy > 0 ? 'WR' : '';
  };
  const seasons = [];
  const careers = {};
  for (const name in CS) {
    const arr = CS[name];
    if (!Array.isArray(arr) || !arr.length) continue;
    const p = pos(name, arr);
    const c = { name, pos: p, py: 0, ptd: 0, ry: 0, rtd: 0, rec: 0, rcy: 0, rctd: 0, yrs: [], schools: {}, confs: {} };
    arr.forEach(s => {
      if (!s || !s.yr) return;
      const row = { name, pos: p, yr: s.yr, school: s.tm || '', conf: s.conf || '', py: s.py || 0, ptd: s.ptd || 0, ry: s.ry || 0, rtd: s.rtd || 0, rec: s.rec || 0, rcy: s.rcy || 0, rctd: s.rctd || 0, gp: s.gp || 0 };
      seasons.push(row);
      ['py', 'ptd', 'ry', 'rtd', 'rec', 'rcy', 'rctd'].forEach(k => { c[k] += row[k]; });
      c.yrs.push(s.yr);
      if (row.school) c.schools[row.school] = (c.schools[row.school] || 0) + 1;
      if (row.conf) c.confs[row.conf] = (c.confs[row.conf] || 0) + 1;
    });
    careers[name] = c;
  }
  const draftYear = (name) => (CD[name] && CD[name].yr) || null;
  const maxYear = seasons.reduce((m, r) => Math.max(m, r.yr), 0);
  return { seasons, careers, CD, dPos, draftYear, maxYear, isNflName: (n) => !!dPos[n] };
}

function loadCollegeGames(repoDir) {
  const files = ['data/college_weekly_1.js', 'data/college_weekly_2.js', 'data/college_weekly_3.js', 'data/college_weekly_devy.js'];
  const games = [];
  const seen = new Set();
  files.forEach(f => {
    let CW;
    try { CW = evalDataFile(repoDir, f, ['COLLEGE_WEEKLY']).COLLEGE_WEEKLY; } catch (_) { return; }
    if (!CW) return;
    for (const name in CW) {
      const bySeason = CW[name];
      for (const yr in bySeason) {
        (bySeason[yr] || []).forEach(g => {
          if (!g) return;
          const key = name + '|' + yr + '|' + g.wk + '|' + (g.opp || '');
          if (seen.has(key)) return;
          seen.add(key);
          games.push({ name, yr: +yr, wk: g.wk, school: g.tm || '', opp: g.opp || '', py: g.py || 0, ptd: g.ptd || 0, ry: g.ry || 0, rtd: g.rtd || 0, rec: g.rec || 0, rcy: g.rcy || 0, rctd: g.rctd || 0 });
        });
      }
    }
  });
  return games;
}

// ---------- ESPN school logos ----------
let _teamMap = null;
async function schoolMap(log) {
  if (_teamMap) return _teamMap;
  let teams = readCache('espn_cfb_teams.json', 7 * 86400000);
  if (!teams) {
    try {
      const j = await getJson('https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=1000');
      teams = j.sports[0].leagues[0].teams.map(x => ({ id: x.team.id, location: x.team.location, display: x.team.displayName, short: x.team.shortDisplayName, abbr: x.team.abbreviation, nickname: x.team.nickname }));
      writeCache('espn_cfb_teams.json', teams);
      log && log('espn college teams: ' + teams.length);
    } catch (e) { log && log('espn college teams unavailable: ' + e.message); teams = []; }
  }
  const map = {};
  const put = (k, t) => { if (k && !map[k]) map[k] = t; };
  // FBS-first ordering: lower ESPN ids are the majors; also prefer exact display matches.
  teams.sort((a, b) => (+a.id) - (+b.id));
  teams.forEach(t => { put(t.location, t); put(t.display, t); put(t.short, t); });
  // Spellings the stats use.
  const alias = { 'Miami (FL)': 'Miami', 'Miami (OH)': 'Miami (OH)', 'Ole Miss': 'Ole Miss', 'Pitt': 'Pittsburgh', 'UConn': 'Connecticut', 'USC': 'USC', 'LSU': 'LSU', 'TCU': 'TCU', 'SMU': 'SMU', 'BYU': 'BYU', 'UCF': 'UCF', 'UNLV': 'UNLV', 'UTSA': 'UTSA', 'UTEP': 'UTEP', 'UAB': 'UAB', 'FIU': 'Florida International', 'Florida International': 'Florida International', 'UL Monroe': 'UL Monroe', 'Louisiana': 'Louisiana', 'Hawaii': "Hawai'i", 'San Jose State': 'San José State', 'Appalachian State': 'Appalachian State', 'Southern Miss': 'Southern Miss', 'NC State': 'NC State', 'Texas A&M': 'Texas A&M', 'Army': 'Army', 'Navy': 'Navy' };
  _teamMap = {
    find(school) {
      if (!school) return null;
      return map[school] || map[alias[school]] || map[school.replace(/ State$/, ' St')] || null;
    },
    logo(school) { const t = this.find(school); return t ? 'https://a.espncdn.com/i/teamlogos/ncaa/500/' + t.id + '.png' : ''; },
  };
  return _teamMap;
}

// ---------- Heisman winners (Wikipedia) ----------
async function heismanWinners(log) {
  const cached = readCache('heisman.json', 7 * 86400000);
  if (cached) return cached;
  const j = await getJson('https://en.wikipedia.org/w/api.php?action=parse&page=List_of_Heisman_Trophy_winners&prop=wikitext&format=json&formatversion=2');
  const w = j.parse.wikitext;
  const rows = [];
  w.split(/\n\|-/).forEach(block => {
    const yr = /\[\[(\d{4}) (?:NCAA Division I FBS football season|college football season|NCAA (?:University|Division I-A) Division football season)\|\1\]\]/.exec(block) || /\[\[(\d{4}) [^\]|]*season\|\1\]\]/.exec(block);
    const nm = /\{\{sortname\|([^|}]+)\|([^|}]+)/.exec(block);
    if (!yr || !nm) return;
    const school = (/\[\[\d{4} [^\]|]*? football team\|([^\]]+)\]\]/.exec(block) || [])[1] || '';
    const posm = block.match(/\[\[[^\]|]+\|([A-Z]{1,3})\]\]/g) || [];
    const pos = posm.map(x => x.replace(/^.*\|/, '').replace(/\]\]$/, '')).filter(x => /^(QB|RB|HB|FB|WR|TE|CB|DB|S|LB|DE|DT|OL|E|B|TB|K|P|WB|G|T|C)$/.test(x)).join('/');
    const file = (/\[\[File:([^|\]]+)/.exec(block) || [])[1] || '';
    rows.push({ year: +yr[1], name: (nm[1] + ' ' + nm[2]).replace(/\s+/g, ' ').trim(), school: school.replace(/\s*\(\d+\)\s*$/, ''), pos, file });
  });
  rows.sort((a, b) => b.year - a.year);
  const out = rows.filter(r => r.year >= 1935);
  if (out.length < 40) throw new Error('Heisman parse found only ' + out.length + ' rows');
  writeCache('heisman.json', out);
  log && log('heisman winners parsed: ' + out.length + ' (latest ' + out[0].year + ' ' + out[0].name + ')');
  return out;
}

// ---------- images ----------
// Resolve a college headshot for a name the NFL id maps never see. Order:
// a Wikimedia Commons photo when the caller has one (Heisman table) →
// ESPN's keyless search, college-football result with an image. Cached
// 30 days, negatives too, so a nightly run makes a handful of requests.
// `schools` (the player's college(s)) must appear in ESPN's subtitle
// ("Ohio Bobcats") for a college-football hit to count — the same name at
// another school is a different person. An NFL hit is accepted only when it
// is the single football result for that exact name.
async function collegeHeadshot(name, opts) {
  const o = opts || {};
  const cache = readCache('college_headshots_v2.json', 1e12) || {};
  const schools = (o.schools || []).filter(Boolean);
  const key = name + '|' + schools.join('/');
  const hit = cache[key];
  if (hit && Date.now() - hit.at < 30 * 86400000) return hit.url;
  let url = '';
  if (o.commonsFile) {
    const u = 'https://commons.wikimedia.org/wiki/Special:FilePath/' + encodeURIComponent(o.commonsFile.replace(/ /g, '_')) + '?width=350';
    try { const r = await fetch(u, { method: 'HEAD', redirect: 'follow', headers: { 'user-agent': UA } }); if (r.ok) url = u; } catch (_) {}
  }
  if (!url) {
    try {
      const j = await getJson('https://site.web.api.espn.com/apis/search/v2?query=' + encodeURIComponent(name) + '&limit=8&type=player');
      const players = ((j.results || []).find(x => x.type === 'player') || {}).contents || [];
      const norm = s => String(s || '').toLowerCase().replace(/[^a-z ]/g, '').replace(/\s+/g, ' ').trim();
      const want = norm(name);
      const exact = players.filter(p => norm(p.displayName) === want && /football/.test(p.sport || ''));
      const schoolOk = (p) => {
        const sub = norm(p.subtitle);
        return !!sub && schools.some(sc => sub.startsWith(norm(sc)) || sub.includes(norm(sc)));
      };
      let pick = exact.find(p => p.defaultLeagueSlug === 'college-football' && p.image && p.image.default && schoolOk(p));
      if (!pick && exact.length === 1 && exact[0].image && exact[0].image.default) pick = exact[0];
      if (pick) url = pick.image.default;
    } catch (_) {}
  }
  cache[key] = { url, at: Date.now() };
  writeCache('college_headshots_v2.json', cache);
  return url;
}

// Fill `headshot` (non-NFL names only; NFL names resolve on the site) and
// `logo` on a list of items.
async function decorate(items, ctx) {
  const schools = await schoolMap(ctx.log);
  for (const it of items) {
    if (!it.logo && it.school) it.logo = schools.logo(it.school);
    if (!it.headshot && !ctx.college.isNflName(it.answer.split(/[\(\,]/)[0].trim())) {
      it.headshot = await collegeHeadshot(it.answer.split(/[\(\,]/)[0].trim(), { commonsFile: it._commons, schools: it._schools || [it.school] });
    }
    delete it._commons; delete it._schools;
  }
  return items;
}

const fmt = (n) => Number(n).toLocaleString('en-US');
function item(answer, category, hint, school, extra) {
  return Object.assign({ rank: '', value: '', headshot: '', logo: '', answer, category, hint, team: school || '', school: school || '' }, extra || {});
}

// ---------- boards (return {key, title, desc, items} or null) ----------
async function seasonLeaders(ctx, year, stat, count) {
  const rows = ctx.college.seasons.filter(r => r.yr === year && r[stat] > 0).sort((a, b) => b[stat] - a[stat]).slice(0, count || 20);
  if (rows.length < 16) return null;
  const items = rows.map((r, i) => item(r.name + ' (' + r.school + ')', '#' + (i + 1), fmt(r[stat]) + ' ' + STAT_SHORT[stat] + ' · ' + r.yr, r.school));
  return { key: 'cfb|season|' + year + '|' + stat, title: year + ' College ' + STAT_LABEL[stat] + ' Leaders', desc: 'Top ' + items.length + ' in college football that season', items: await decorate(items, ctx) };
}
async function careerLeaders(ctx, stat, count) {
  const rows = Object.values(ctx.college.careers).filter(c => c[stat] > 0 && Math.min(...c.yrs) >= FIRST_DENSE_YEAR).sort((a, b) => b[stat] - a[stat]).slice(0, count || 20);
  if (rows.length < 16) return null;
  const items = rows.map((c, i) => { const sch = Object.keys(c.schools).sort((a, b) => c.schools[b] - c.schools[a])[0]; return item(c.name + ' (' + Math.min(...c.yrs) + '–' + Math.max(...c.yrs) + ')', '#' + (i + 1), fmt(c[stat]) + ' ' + STAT_SHORT[stat] + ' · ' + sch, sch, { _schools: Object.keys(c.schools) }); });
  return { key: 'cfb|career|' + stat, title: 'College Career ' + STAT_LABEL[stat] + ' Leaders · Since ' + FIRST_DENSE_YEAR, desc: 'Career college totals, players who went on to the NFL draft pool', items: await decorate(items, ctx) };
}
async function schoolLeaders(ctx, school, stat, count) {
  const rows = Object.values(ctx.college.careers).map(c => {
    let v = 0; const yrs = [];
    ctx.college.seasons.forEach(r => { if (r.name === c.name && r.school === school) { v += r[stat]; yrs.push(r.yr); } });
    return { name: c.name, v, yrs };
  }).filter(x => x.v > 0).sort((a, b) => b.v - a.v).slice(0, count || 20);
  if (rows.length < 16) return null;
  const items = rows.map((r, i) => item(r.name + ' (' + Math.min(...r.yrs) + '–' + Math.max(...r.yrs) + ')', '#' + (i + 1), fmt(r.v) + ' ' + STAT_SHORT[stat], school));
  return { key: 'cfb|school|' + school + '|' + stat, title: school + ' ' + STAT_LABEL[stat] + ' Leaders · Since ' + FIRST_DENSE_YEAR, desc: 'The ' + school + ' greats of the last two decades, by college ' + STAT_SHORT[stat], items: await decorate(items, ctx) };
}
async function conferenceSeason(ctx, conf, year, stat, count) {
  const rows = ctx.college.seasons.filter(r => r.conf === conf && r.yr === year && r[stat] > 0).sort((a, b) => b[stat] - a[stat]).slice(0, count || 20);
  if (rows.length < 16) return null;
  const items = rows.map((r, i) => item(r.name + ' (' + r.school + ')', '#' + (i + 1), fmt(r[stat]) + ' ' + STAT_SHORT[stat], r.school));
  return { key: 'cfb|conf|' + conf + '|' + year + '|' + stat, title: year + ' ' + conf + ' ' + STAT_LABEL[stat] + ' Leaders', desc: 'Top ' + items.length + ' in the ' + conf + ' that season', items: await decorate(items, ctx) };
}
async function bestGames(ctx, stat, count) {
  const games = ctx.college.games || (ctx.college.games = loadCollegeGames(ctx.repoDir));
  const rows = games.filter(g => g[stat] > 0 && g.yr >= FIRST_DENSE_YEAR).sort((a, b) => b[stat] - a[stat]).slice(0, count || 20);
  if (rows.length < 16) return null;
  const items = rows.map((g, i) => item(g.name + ' (' + g.yr + (g.opp ? ' vs ' + g.opp : '') + ')', '#' + (i + 1), fmt(g[stat]) + ' ' + STAT_SHORT[stat] + ' · ' + g.school, g.school));
  return { key: 'cfb|game|' + stat, title: 'Best Single-Game College ' + STAT_LABEL[stat] + ' · Since ' + FIRST_DENSE_YEAR, desc: 'One-game college explosions by future NFL players', items: await decorate(items, ctx), repeatRule: true };
}
async function heismanBoard(ctx, count) {
  const winners = await heismanWinners(ctx.log);
  const rows = winners.slice(0, count || 20);
  const items = rows.map(r => item(r.name, String(r.year), r.school + (r.pos ? ' · ' + r.pos : ''), r.school, { _commons: r.file }));
  return { key: 'cfb|heisman|' + rows[rows.length - 1].year, title: 'Heisman Trophy Winners · ' + rows[rows.length - 1].year + '–' + rows[0].year, desc: 'Name the Heisman winner for each year', items: await decorate(items, ctx) };
}
async function draftClassCollege(ctx, draftYear, stat, count) {
  const names = Object.keys(ctx.college.CD).filter(n => ctx.college.CD[n].yr === draftYear);
  const rows = names.map(n => ctx.college.careers[n]).filter(c => c && c[stat] > 0).sort((a, b) => b[stat] - a[stat]).slice(0, count || 20);
  if (rows.length < 16) return null;
  const items = rows.map((c, i) => { const sch = Object.keys(c.schools).sort((a, b) => c.schools[b] - c.schools[a])[0]; return item(c.name + ' (' + sch + ')', '#' + (i + 1), fmt(c[stat]) + ' college ' + STAT_SHORT[stat], sch, { _schools: Object.keys(c.schools) }); });
  return { key: 'cfb|class|' + draftYear + '|' + stat, title: draftYear + ' NFL Draft Class · College ' + STAT_LABEL[stat], desc: 'The ' + draftYear + ' class ranked by college career ' + STAT_SHORT[stat], items: await decorate(items, ctx) };
}

// Context shared by the builders (loaded once per run).
function context(repoDir, log) {
  return { repoDir, log, college: loadCollege(repoDir) };
}

module.exports = { context, seasonLeaders, careerLeaders, schoolLeaders, conferenceSeason, bestGames, heismanBoard, draftClassCollege, heismanWinners, schoolMap, collegeHeadshot, STAT_LABEL, FIRST_DENSE_YEAR };
