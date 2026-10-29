// Daily Trivia — franchise leaderboards built from WITH-TEAM totals.
//
// Why not the site generator's team filter: it keeps players whose primary
// team is X and ranks them by FULL-CAREER totals (Ricky Williams's 9,978
// includes New Orleans), and it only sees players in its main table, so
// legends who exist only in LEGEND_CAREERS (Mercury Morris, Jim Kiick) never
// make a Dolphins board. Jack 2026-10-28: "the list wasn't even close".
//
// This module sums each player's seasons WITH the team. Coverage is
// complete for 1999+ (ALL_PLAYERS_DB = every nflverse skill player), so the
// boards are titled "Since 1999" rather than claiming all-time. The current
// season is added from WEEKLY_STATS_ACTIVE. A quality floor rejects a thin
// tail (a franchise's 16th-best rusher with 500 yards is not trivia).
'use strict';

const { evalDataFile } = require('./signals');

const SINCE = 1999;
const STAT_LABEL = { py: 'Passing Yards', ptd: 'Passing TDs', ry: 'Rushing Yards', rtd: 'Rushing TDs', rcy: 'Receiving Yards', rec: 'Receptions', rctd: 'Receiving TDs', fpts: 'Fantasy Points', totalTd: 'Total TDs' };
const STAT_SHORT = { py: 'pass yds', ptd: 'pass td', ry: 'rush yds', rtd: 'rush td', rcy: 'rec yds', rec: 'rec', rctd: 'rec td', fpts: 'fpts', totalTd: 'total td' };
// 16th-place floor per stat (anything below is a weak board).
const FLOOR = { py: 3000, ry: 1000, rcy: 1000, rec: 100, ptd: 20, rtd: 10, rctd: 10, fpts: 300, totalTd: 15 };
const POS_LABEL = { QB: 'QB', RB: 'RB', WR: 'WR/TE', TE: 'WR/TE' };

const fmt = (n) => Number.isInteger(n) ? Number(n).toLocaleString('en-US') : Number(n).toFixed(1);
function val(row, stat) {
  if (stat === 'totalTd') return (row.ptd || 0) + (row.rtd || 0) + (row.rctd || 0);
  if (stat === 'rec') return row.rc != null ? (row.rc || 0) : (row.rec || 0);
  return row[stat] || 0;
}

let _ctx = null;
function context(repoDir, log) {
  if (_ctx && _ctx.repoDir === repoDir) return _ctx;
  const AP = evalDataFile(repoDir, 'data/all_players.js', ['ALL_PLAYERS_DB']).ALL_PLAYERS_DB || [];
  const D = evalDataFile(repoDir, 'data/d.js', ['D']).D || [];
  const TEAM_ABBR_MAP = evalDataFile(repoDir, 'data/team_abbr_map.js', ['TEAM_ABBR_MAP']).TEAM_ABBR_MAP || {};
  const WS = evalDataFile(repoDir, 'data/weekly_stats_active.js', ['WEEKLY_STATS_ACTIVE']).WEEKLY_STATS_ACTIVE || {};
  let LC = null;
  try { LC = evalDataFile(repoDir, 'data/legend_careers.js', ['LEGEND_CAREERS']).LEGEND_CAREERS; } catch (_) {}
  const dByName = {}; D.forEach(d => { if (d && d.n) dByName[d.n] = d; });
  // Player → { pos, seasons: [{yr, tm, ...stats}] } from ALL_PLAYERS_DB,
  // then d.js careers for anyone AP lacks (rookies), then this season.
  const players = {};
  AP.forEach(p => { if (p && p.name && p.career) players[p.name] = { pos: p.pos || (dByName[p.name] || {}).s || '', seasons: p.career.slice() }; });
  D.forEach(d => {
    if (!d || !d.n || !d.career || !d.career.length) return;
    if (!players[d.n]) players[d.n] = { pos: d.s || '', seasons: d.career.map(s => Object.assign({}, s, { tm: s.tm || TEAM_ABBR_MAP[d.t] || '' })) };
    else if (!players[d.n].pos) players[d.n].pos = d.s || '';
  });
  // Current season (not in any career array yet): weekly rows, team from
  // the row or the player's current team.
  const curYear = Object.keys(WS).reduce((m, n) => { const s = WS[n].seasons || {}; return Object.keys(s).reduce((mm, y) => Math.max(mm, +y), m); }, 0);
  for (const name in WS) {
    const rows = WS[name].seasons && WS[name].seasons[String(curYear)];
    if (!rows || !rows.length) continue;
    const p = players[name] || (players[name] = { pos: WS[name].pos || (dByName[name] || {}).s || '', seasons: [] });
    if (p.seasons.some(s => s.yr === curYear)) continue;
    const byTeam = {};
    rows.forEach(w => {
      if (!w || !(w.fpts > 0 || w.py > 0 || w.ry > 0 || w.rec > 0)) return;
      const tm = w.tm || TEAM_ABBR_MAP[(dByName[name] || {}).t] || '';
      if (!tm) return;
      const t = byTeam[tm] || (byTeam[tm] = { yr: curYear, tm, gp: 0, py: 0, ptd: 0, ry: 0, rtd: 0, rc: 0, rcy: 0, rctd: 0, fpts: 0 });
      t.gp++; t.py += w.py || 0; t.ptd += w.ptd || 0; t.ry += w.ry || 0; t.rtd += w.rtd || 0; t.rc += w.rec || 0; t.rcy += w.rcy || 0; t.rctd += w.rctd || 0; t.fpts += w.fpts || 0;
    });
    Object.values(byTeam).forEach(t => p.seasons.push(t));
  }
  _ctx = { repoDir, log, players, LC, TEAM_ABBR_MAP, curYear };
  return _ctx;
}

// Franchise leaderboard: sum of seasons with `abbr` since SINCE.
// Returns {key, title, desc, items} or null (too thin / floor not met).
function teamLeaders(ctx, abbr, nick, stat, positions, count) {
  const posSet = positions && positions.length ? new Set(positions) : null;
  const rows = [];
  for (const name in ctx.players) {
    const p = ctx.players[name];
    if (posSet && !posSet.has(p.pos)) continue;
    let v = 0; const yrs = [];
    p.seasons.forEach(s => { if (s && s.tm === abbr && s.yr >= SINCE) { v += val(s, stat); yrs.push(s.yr); } });
    if (v > 0) rows.push({ name, v: Math.round(v * 10) / 10, yrs });
  }
  rows.sort((a, b) => b.v - a.v);
  const top = rows.slice(0, count || 20);
  if (top.length < 16) return null;
  if (top[15].v < (FLOOR[stat] || 0)) return { thin: true, sixteenth: top[15] };
  // Cross-check: for players also in LEGEND_CAREERS, the with-team sum from
  // that independent source must agree (within 2%) for the top 10.
  // Fantasy points differ by scoring convention between the two sources
  // (INT -1 vs -2 era rules), so only counting stats are cross-checked.
  const disagreements = [];
  if (ctx.LC && stat !== 'fpts') {
    top.slice(0, 10).forEach(r => {
      const lc = ctx.LC[r.name];
      if (!lc) return;
      let lv = 0;
      lc.forEach(s => { if (s && s.tm === abbr && s.yr >= SINCE && s.yr < ctx.curYear) lv += val(s, stat); });
      const cur = ctx.players[r.name].seasons.filter(s => s.yr === ctx.curYear && s.tm === abbr).reduce((t, s) => t + val(s, stat), 0);
      if (lv > 0 && Math.abs((lv + cur) - r.v) > Math.max(2, 0.02 * r.v)) disagreements.push(r.name + ' ' + r.v + ' vs legends ' + Math.round(lv + cur));
    });
  }
  const posLabel = positions && positions.length ? (positions.length === 1 ? positions[0] : (positions.includes('WR') && positions.includes('TE') && positions.length === 2 ? 'WR/TE' : positions.join('/'))) : '';
  const items = top.map((r, i) => ({
    rank: '', value: '', headshot: '', logo: '',
    answer: r.name + ' (' + Math.min(...r.yrs) + '–' + Math.max(...r.yrs) + ')',
    category: '#' + (i + 1),
    hint: fmt(r.v) + ' ' + STAT_SHORT[stat],
    team: abbr,
  }));
  return {
    key: 'team|' + abbr + '|' + stat + '|' + (positions || []).join(''),
    title: nick + ' ' + STAT_LABEL[stat] + ' Leaders · Since ' + SINCE + (posLabel ? ' · ' + posLabel : ''),
    desc: 'Yards and points WITH the ' + nick + ', ' + SINCE + ' to today',
    items, disagreements, status: disagreements.length ? 'cross-mismatch' : 'cross-ok',
  };
}

module.exports = { context, teamLeaders, SINCE, FLOOR, STAT_LABEL };
