// Helper for build_future_totals.py: which quarterback the engine projects to start for every team in every
// week from the current one on (injury layer, IN_SEASON_OUT_OVERRIDES and QB-room windows applied), plus the
// team's MAIN quarterback = the highest preseason Clay total on the roster. Prints one JSON object.
// Usage: node dump_qb_state.js <currentWeek>
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
const out = {};
players.list.filter(p => p.pos === 'QB' && !p.isDST).forEach(p => {
  const t = out[p.tm] = out[p.tm] || { main: null, mainPts: -1, weeks: {} };
  if ((p.ptsPPR || 0) > t.mainPts) { t.mainPts = p.ptsPPR || 0; t.main = p.name; }
  for (let wk = cur; wk <= 18; wk++) {
    const w = E.weeklyProjection(p, wk, sc, schedule); if (!w) continue;
    const v = E.effMean(w);
    if (!(v > 1)) continue;
    const c = t.weeks[wk];
    if (!c || v > c[1]) t.weeks[wk] = [p.name, +v.toFixed(1)];
  }
});
log(JSON.stringify(out));
