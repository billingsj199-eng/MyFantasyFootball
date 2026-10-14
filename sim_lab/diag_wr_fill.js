'use strict';
// W5 2026 WR fill-in examples (research only; engine untouched): base vs forced-out projections, PPR.
const fs = require('fs'), path = require('path'), vm = require('vm');
global.window = global;
const log = console.log; console.log = () => {}; console.warn = () => {};
const src = fs.readFileSync(path.join(__dirname, 'export_site_proj.js'), 'utf8');
const files = eval(src.match(/\[\s*'data\/mike_clay_projections\.js'[\s\S]*?'engine\.js'\s*\]/)[0]).filter(f => f !== 'data/sim_future_totals.js');
files.forEach(f => vm.runInThisContext(fs.readFileSync(path.join(__dirname, f), 'utf8'), { filename: f }));
const E = global.SimEngine;
const schedule = E.buildSchedule(), players = E.buildPlayers(schedule);
const sc = E.PRESETS.ppr || E.PRESETS.full || E.PRESETS.half;
const find = n => players.list.find(p => p.name === n) || players.list.find(p => p.name && p.name.toLowerCase().startsWith(n.toLowerCase()));
const SC = [
  ['PHI', ['DeVonta Smith'], ['Dontayvion Wicks', 'Makai Lemon', 'Darius Cooper', 'A.J. Brown', 'Dallas Goedert']],
  ['WAS', ['Stefon Diggs'], ['Terry McLaurin', 'Antonio Williams']],
  ['LV', ['Jalen Nailor'], ['Tre Tucker', 'Brock Bowers', 'Jack Bech']],
  ['LAC', ['Quentin Johnston', 'Tre Harris'], ['Ladd McConkey', 'Oronde Gadsden II']],
];
for (const [tm, outs, names] of SC) {
  const force = {}; outs.forEach(n => { const p = find(n); force[p ? p.name : n] = 'out'; });
  const row = (tag) => names.forEach(n => { const p = find(n); if (!p) return log(tm, tag, n, 'MISSING');
    const w = E.weeklyProjection(p, 5, sc, schedule); log(tm, tag.padEnd(5), p.name.padEnd(22), 'eff', E.effMean(w).toFixed(2), 'nc', w.ncMean != null ? w.ncMean.toFixed(2) : '-', w.ncSrc || ''); });
  E.applyInSeasonInjuries(players, 5, { active: true }); row('BASE');
  E.applyInSeasonInjuries(players, 5, { active: true, force }); row('OUT');
  log('  forced out:', JSON.stringify(force));
}
// trailing target leader per team (wk 2-4) from SIM_XFP_2026, to tell the engine's lead / sec rule
const X = global.SIM_XFP_2026 || {};
for (const [tm] of SC) {
  const rows = players.list.filter(p => p.tm === tm && ['WR','TE','RB'].includes(p.pos)).map(p => { const x = X[p.norm]; let t = 0; if (x && x.w) [2,3,4].forEach(w => { const r = x.w[w] || x.w[String(w)]; if (r) t += +r[0] || 0; }); return [p.name, t]; }).sort((a, b) => b[1] - a[1]).slice(0, 6);
  log(tm, 'trailing targets wk2-4:', rows.map(r => r[0] + ' ' + r[1]).join(', '));
}
