// verify_noclay_shadow.js - headless check of the Clay-free shadow v2 (NC_SHADOW): the live mean must not move,
// every QB/RB/WR/TE row gets a Clay-free prior, and the named examples read sensibly. Run: node verify_noclay_shadow.js
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm');
global.window = global;
const src = fs.readFileSync(path.join(__dirname, 'export_site_proj.js'), 'utf8');
const files = src.match(/\[\s*((?:'data\/[^']+',\s*)+'overrides\.js',\s*'engine\.js')\s*\]/)[1].match(/'([^']+)'/g).map(s => s.slice(1, -1));
files.forEach(f => vm.runInThisContext(fs.readFileSync(path.join(__dirname, f), 'utf8'), { filename: f }));
const E = global.SimEngine;
const WK = parseInt(process.argv[2] || '2', 10), sc = E.PRESETS.half;
function run(v2) {
  global.SIM_NC_V2 = v2;
  const schedule = E.buildSchedule(), players = E.buildPlayers(schedule);
  E.applyInSeasonInjuries(players, WK, { active: true });
  const out = {};
  players.list.forEach(p => { const wp = E.weeklyProjection(p, WK, sc, schedule); if (wp) out[p.name + '|' + p.pos] = { pos: p.pos, mean: wp.mean, js: wp.jsMean, prop: wp.propMean, nc: wp.ncMean, src: wp.ncSrc, rookie: p.isRookie, pick: p.draftPick, adp: p.adp }; });
  return out;
}
const v1 = run(false), v2 = run(true);
let moved = 0, n = 0, gatedFb = 0; const mix = {}, diffs = [];
Object.keys(v2).forEach(k => {
  const a = v1[k], b = v2[k]; if (!a) return; n++;
  if (Math.abs((a.mean || 0) - (b.mean || 0)) > 1e-9 || Math.abs((a.js || 0) - (b.js || 0)) > 1e-9 || Math.abs((a.prop || 0) - (b.prop || 0)) > 1e-9) moved++;
  if (/^(QB|RB|WR|TE)$/.test(b.pos)) { const s = String(b.src || 'null').split('+')[0]; mix[s] = (mix[s] || 0) + 1; if (b.nc != null && a.nc != null) diffs.push(b.nc - a.nc); if (s === 'clay-fallback' && b.adp != null && b.adp <= 200) gatedFb++; }
});
const avg = diffs.reduce((s, x) => s + x, 0) / diffs.length, mad = diffs.reduce((s, x) => s + Math.abs(x), 0) / diffs.length;
console.log(`week ${WK}: ${n} players | live mean/js/prop moved on ${moved} rows (must be 0) | v2 prior sources`, mix);
console.log(`Clay fallback rows inside the ADP<=200 gate: ${gatedFb} (must be 0)`);
console.log(`ncMean v2 - v1: avg ${avg.toFixed(2)}, mean |diff| ${mad.toFixed(2)} on ${diffs.length} rows`);
['Josh Allen|QB', 'Ja\'Marr Chase|WR', 'Josh Jacobs|RB', 'Parker Washington|WR', 'Jeremiyah Love|RB', 'Ashton Jeanty|RB', 'Caleb Williams|QB', 'Jalon Daniels|QB', 'Kaleb Johnson|RB', 'Derrick Henry|RB', 'Fernando Mendoza|QB'].forEach(k => {
  const a = v1[k], b = v2[k]; if (!b) { console.log('  ' + k + ': not projected'); return; }
  console.log(`  ${k.padEnd(22)} live ${b.mean.toFixed(1).padStart(5)}  js ${(b.js == null ? '-' : b.js.toFixed(1)).padStart(5)} | shadow v1 ${(a.nc == null ? '-' : a.nc.toFixed(1)).padStart(5)} (${a.src}) -> v2 ${(b.nc == null ? '-' : b.nc.toFixed(1)).padStart(5)} (${b.src})${b.rookie ? '  rookie pick ' + b.pick : ''}`);
});
const rk = Object.keys(v2).filter(k => /rookie-/.test(String(v2[k].src))).sort((a, b) => v2[b].mean - v2[a].mean).slice(0, 10);
console.log('rookie fallback rows (top 10 by live mean): ' + rk.map(k => k.split('|')[0] + ' live ' + v2[k].mean.toFixed(1) + ' -> shadow ' + (v2[k].nc == null ? '-' : v2[k].nc.toFixed(1)) + ' (' + v2[k].src + ', pick ' + v2[k].pick + ')').join(' | '));
const dk = Object.keys(v2).filter(k => /\+dock/.test(String(v2[k].src))).sort((a, b) => v2[b].mean - v2[a].mean);
console.log('docked veterans (' + dk.length + '), top 10 by live mean: ' + dk.slice(0, 10).map(k => k.split('|')[0] + ' live ' + v2[k].mean.toFixed(1) + ' shadow v1 ' + (v1[k].nc == null ? '-' : v1[k].nc.toFixed(1)) + ' -> ' + (v2[k].nc == null ? '-' : v2[k].nc.toFixed(1)) + ' (' + v2[k].src.match(/dock\d/)[0] + ')').join(' | '));
const rp = Object.keys(v2).filter(k => /\+ramp/.test(String(v2[k].src))).sort((a, b) => v2[b].mean - v2[a].mean);
console.log('ramped buried rookies (' + rp.length + '): ' + rp.slice(0, 8).map(k => k.split('|')[0] + ' live ' + v2[k].mean.toFixed(1) + ' shadow v1 ' + (v1[k].nc == null ? '-' : v1[k].nc.toFixed(1)) + ' -> ' + (v2[k].nc == null ? '-' : v2[k].nc.toFixed(1)) + ' (' + v2[k].src + ')').join(' | '));
const y2 = Object.keys(v2).filter(k => /\+yr2lo/.test(String(v2[k].src))).sort((a, b) => v2[b].mean - v2[a].mean);
console.log('2nd-year low-snap boosts (' + y2.length + '): ' + y2.slice(0, 8).map(k => k.split('|')[0] + ' live ' + v2[k].mean.toFixed(1) + ' shadow v1 ' + (v1[k].nc == null ? '-' : v1[k].nc.toFixed(1)) + ' -> ' + (v2[k].nc == null ? '-' : v2[k].nc.toFixed(1))).join(' | '));
const gd = Object.keys(v2).filter(k => /\+grade/.test(String(v2[k].src))).sort((a, b) => v2[b].mean - v2[a].mean);
console.log('WR route-grade boosts (' + gd.length + '): ' + gd.slice(0, 10).map(k => k.split('|')[0] + ' live ' + v2[k].mean.toFixed(1) + ' shadow v1 ' + (v1[k].nc == null ? '-' : v1[k].nc.toFixed(1)) + ' -> ' + (v2[k].nc == null ? '-' : v2[k].nc.toFixed(1))).join(' | '));
process.exit(moved === 0 && gatedFb === 0 ? 0 : 1);
