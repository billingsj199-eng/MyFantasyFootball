// One-off (10-10): freeze the season-opening ESPN depth chart for the dynasty in-season
// fill-in fold. Source = the repo's data/depth_charts_2026.js at commit c9e3392 (the
// first daily pull with all positions, 2026-09-11 before the week-1 Sunday games),
// extracted to the session scratchpad. Usage: node freeze_open_chart.js <snapshot.js>
const fs = require('fs');
global.window = {};
eval(fs.readFileSync(process.argv[2], 'utf8'));
const A = window.DEPTH_2026;
fs.writeFileSync(__dirname + '/depth_chart_2026_open.json', JSON.stringify({
  note: 'ESPN depth chart frozen at the 2026 season opening (repo commit c9e3392, pulled ' + A.updated
    + '). Regulars for the dynasty in-season fill-in fold (build_dynasty_sim.py FILLIN_F). Do not refresh mid-season.',
  updated: A.updated, teams: A.teams }));
console.log('frozen', Object.keys(A.teams).length, 'teams');
