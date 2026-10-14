'use strict';
// QB + TE OUT check (2026-10-09): team QB with / without his TE1 forced out, week 5, PPR.
const fs = require('fs'), path = require('path'), vm = require('vm');
global.window = global;
const log = console.log; console.log = () => {}; console.warn = () => {};
const src = fs.readFileSync(path.join(__dirname, 'export_site_proj.js'), 'utf8');
const files = eval(src.match(/\[\s*'data\/mike_clay_projections\.js'[\s\S]*?'engine\.js'\s*\]/)[0]).filter(f => f !== 'data/sim_future_totals.js');
files.forEach(f => vm.runInThisContext(fs.readFileSync(path.join(__dirname, f), 'utf8'), { filename: f }));
const E = global.SimEngine, schedule = E.buildSchedule(), players = E.buildPlayers(schedule), sc = E.PRESETS.ppr;
for (const [te, tm] of [['Brock Bowers', 'LV'], ['George Kittle', 'SF'], ['Trey McBride', 'ARI']]) {
  const qbs = players.list.filter(p => p.tm === tm && p.pos === 'QB');
  for (const force of [{}, { [te]: 'out' }]) {
    E.applyInSeasonInjuries(players, 5, { active: true, force });
    qbs.forEach(q => { const w = E.weeklyProjection(q, 5, sc, schedule); if (w && E.effMean(w) > 5) log(te, Object.keys(force).length ? 'OUT' : 'in ', q.name, E.effMean(w).toFixed(2), 'nc', w.ncMean && w.ncMean.toFixed(2), /qbte/.test(w.ncSrc || '') ? '+qbte' : ''); });
  }
}
