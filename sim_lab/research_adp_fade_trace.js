// 2026-11-17 ADP-fade what-if (research_adp_fade.py companion). In-memory engine copy, nothing on disk changes.
//   node research_adp_fade_trace.js <curWeek> <variant> "Name" ...     variant: wired | lin:k | hyp:k | off (wA = 0)
// g = the player's 2026 games played (SIM_2026.players[norm].g). Prints next game + ROS weekly export numbers.
const fs = require('fs'), path = require('path'), vm = require('vm'); global.window = global; const dir = __dirname;
let src = fs.readFileSync(path.join(dir, 'export_site_proj.js'), 'utf8').replace(/\/\/[^\n]*/g, '');
const files = src.match(/\[\s*((?:'data\/[^']+',\s*)+'overrides\.js',\s*'engine\.js')\s*\]/)[1].match(/'([^']+)'/g).map(s => s.slice(1, -1));
const args = process.argv.slice(2), CUR = +args[0], VAR = args[1], names = args.slice(2);
const needle = "wA = p.exp === 1 ? NC_SHADOW.adpWYr2 : NC_SHADOW.adpW;";
global.__ADPK = function (p) {
  const r = (global.SIM_2026 && global.SIM_2026.players || {})[p.norm] || {}, g = r.g || 0;
  if (VAR === 'wired') return 1; if (VAR === 'off') return 0;
  const [t, k] = VAR.split(':'); return t === 'lin' ? Math.max(0, 1 - g / +k) : (+k) / (+k + g);
};
global.__TRACE = {};
files.forEach(f => {
  let code = fs.readFileSync(path.join(dir, f), 'utf8');
  if (f === 'engine.js') {
    if (code.indexOf(needle) < 0) throw new Error('needle missing');
    code = code.replace(needle, needle + " var __k = window.__ADPK(p); wA *= __k; if (window.__TN && window.__TN[p.norm]) window.__TRACE[p.norm] = {k: __k, mkt: mkt, pre: ncPrior / scale};");
  }
  vm.runInThisContext(code, { filename: f });
});
const E = global.SimEngine, sc = E.PRESETS.half, schedule = E.buildSchedule(), players = E.buildPlayers(schedule);
global.SIM_NOW_MS = Date.parse('2026-11-17T12:00:00Z');
try { global.SIM_KICKOFFS_2026 = JSON.parse(fs.readFileSync(path.join(dir, 'data', 'kickoffs_2026.json'), 'utf8')); } catch (_) {}
E.applyInSeasonInjuries(players, CUR, { active: true });
global.__TN = {}; names.forEach(nm => { const p = players.list.find(x => x.name === nm); if (p) global.__TN[p.norm] = 1; });
names.forEach(nm => {
  const p = players.list.find(x => x.name === nm); if (!p) { console.log(nm, 'not found'); return; }
  const rows = [];
  for (let wk = CUR; wk <= 18; wk++) { const w = E.weeklyProjection(p, wk, sc, schedule); if (!w) continue; rows.push([wk, E.effMean(w), w.ncMean, w.propSrc || '-']); }
  const avg = (a) => a.length ? a.reduce((s, r) => s + r[1], 0) / a.length : NaN;
  const t = global.__TRACE[p.norm] || {};
  const rec = (global.SIM_2026.players || {})[p.norm] || {};
  console.log(`${VAR.padEnd(6)} ${nm.padEnd(16)} ADP ${Math.round(p.adp)} g ${rec.g} k ${t.k != null ? t.k.toFixed(3) : '-'} (pre-ADP ${t.pre != null ? t.pre.toFixed(2) : '-'} mkt ${t.mkt != null ? t.mkt.toFixed(2) : '-'}) | W${CUR} ${rows[0] ? rows[0][1].toFixed(2) : '-'} | avg W${CUR}-18 ${avg(rows).toFixed(2)} | avg W${CUR + 1}-18 ${avg(rows.filter(r => r[0] > CUR)).toFixed(2)} | avg W${CUR + 1}-17 ${avg(rows.filter(r => r[0] > CUR && r[0] < 18)).toFixed(2)} | weeks ${rows.map(r => r[0] + ':' + r[1].toFixed(1) + (r[3] === 'line' ? 'L' : r[3] === 'rate' ? 'r' : '')).join(' ')}`);
});
