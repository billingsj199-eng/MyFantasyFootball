// Helper for build_own_totals.py: for every team and every week from the current one on, the quarterbacks who can
// start and the probability each one does - depth-chart order x availability (injury layer: out-windows, news
// timelines, the availability curve, quarterback-room windows). Prints one JSON object:
//   {TEAM: {wk: [[name, P(starts), rank], ...]}}   rank 0 = the planned starter that week, 1+ = starts only because
//   someone ahead of him is unavailable (probabilities sum to <= 1; the rest = nobody listed is available)
// Usage: node dump_team_state.js <currentWeek>
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm');
const cur = parseInt(process.argv[2] || '1', 10);
global.window = global;
const log = console.log; console.log = () => {}; console.warn = () => {};
const src = fs.readFileSync(path.join(__dirname, 'export_site_proj.js'), 'utf8');
const files = eval(src.match(/\[\s*'data\/mike_clay_projections\.js'[\s\S]*?'engine\.js'\s*\]/)[0]).filter(f => f !== 'data/sim_future_totals.js');
files.forEach(f => vm.runInThisContext(fs.readFileSync(path.join(__dirname, f), 'utf8'), { filename: f }));
const E = global.SimEngine, sc = E.PRESETS.half;
const schedule = E.buildSchedule(), players = E.buildPlayers(schedule);
E.applyInSeasonInjuries(players, cur, { active: true });
const norm = s => String(s || '').toLowerCase().replace(/\./g, '').replace(/'/g, '').replace(/-/g, ' ').replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '').replace(/\s+/g, ' ').trim();
const depth = {};
const D = global.SIM_DEPTH_2026;
if (D && D.teams) Object.keys(D.teams).forEach(tm => { (D.teams[tm].QB || []).forEach((nm, i) => { const k = E.normTeam(tm) + '|' + norm(nm); if (depth[k] == null) depth[k] = i; }); });
// Opening-day chart (2026-11-03): the live chart drops an injured starter below his backups (Lamar 4th behind
// Fagnano / Slovis), and ordering every future week by it meant he never got the job back once healthy.
const open = {};
try {
  const O = JSON.parse(fs.readFileSync(path.join(__dirname, '_dyn_cache', 'depth_chart_2026_open.json'), 'utf8'));
  Object.keys(O.teams || {}).forEach(tm => { (O.teams[tm].QB || []).forEach((nm, i) => { const k = E.normTeam(tm) + '|' + norm(nm); if (open[k] == null) open[k] = i; }); });
} catch (e) {}
const out = {};
const qbs = players.list.filter(p => p.pos === 'QB' && !p.isDST);
const teams = [...new Set(qbs.map(p => p.tm))];
teams.forEach(tm => {
  out[tm] = {};
  // A quarterback who is OUT now and sits below someone he was ahead of on the opening chart (or who wasn't on it)
  // lost that slot to the injury, not a benching: in future weeks he goes back just ahead of the highest of them,
  // and his availability curve decides how often he starts. Healthy quarterbacks keep the live order (benchings stick).
  const tq = qbs.filter(p => p.tm === tm), key = {};
  tq.forEach(p => {
    const k = tm + '|' + p.norm, dr = depth[k];
    key[k] = dr == null ? 99 : dr;
    if (dr == null || open[k] == null) return;
    let wk0 = cur; while (wk0 <= 18 && !E.weeklyProjection(p, wk0, sc, schedule)) wk0++;
    if (wk0 > 18 || E.injPlay(p, wk0) >= 0.5) return;
    tq.forEach(o => {
      const ko = tm + '|' + o.norm, dro = depth[ko];
      if (o === p || dro == null || dro >= dr) return;
      if (open[ko] == null || open[ko] > open[k]) key[k] = Math.min(key[k], dro - 0.5);
    });
  });
  for (let wk = cur; wk <= 18; wk++) {
    const c = [];
    tq.forEach(p => {
      const w = E.weeklyProjection(p, wk, sc, schedule); if (!w) return;          // bye, or outside his window
      const a = Math.max(0, Math.min(1, E.injPlay(p, wk)));
      const lvl = (p.ptsPPR || 0) / (p.qbWindow ? (p.qbWindow.games || 17) : 17);
      c.push({ name: p.name, a, lvl, dr: key[tm + '|' + p.norm], win: p.qbWindow ? 1 : 0 });
    });
    if (!c.length) continue;
    // a quarterback whose window covers this week is the planned starter; then the depth chart; then level
    c.sort((x, y) => (y.win - x.win) || (x.dr - y.dr) || (y.lvl - x.lvl));
    let left = 1; const row = [];
    c.forEach((q, i) => { const p = left * q.a; if (p > 0.005) row.push([q.name, +p.toFixed(3), i]); left *= (1 - q.a); });
    out[tm][wk] = row;
  }
});
log(JSON.stringify(out));
