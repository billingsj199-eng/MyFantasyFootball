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
const out = {};
const qbs = players.list.filter(p => p.pos === 'QB' && !p.isDST);
const teams = [...new Set(qbs.map(p => p.tm))];
teams.forEach(tm => {
  out[tm] = {};
  for (let wk = cur; wk <= 18; wk++) {
    const c = [];
    qbs.filter(p => p.tm === tm).forEach(p => {
      const w = E.weeklyProjection(p, wk, sc, schedule); if (!w) return;          // bye, or outside his window
      const a = Math.max(0, Math.min(1, E.injPlay(p, wk)));
      const lvl = (p.ptsPPR || 0) / (p.qbWindow ? (p.qbWindow.games || 17) : 17);
      const dr = depth[tm + '|' + p.norm];
      c.push({ name: p.name, a, lvl, dr: dr == null ? 99 : dr, win: p.qbWindow ? 1 : 0 });
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
