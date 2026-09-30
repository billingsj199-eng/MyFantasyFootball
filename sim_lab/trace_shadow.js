// In-memory instrumented copy of engine.js: records the shadow's intermediate values for named players. Nothing on disk changes.
const fs = require('fs'), path = require('path'), vm = require('vm'); global.window = global; const dir = __dirname;
const src = fs.readFileSync(path.join(dir, 'export_site_proj.js'), 'utf8');
const files = src.match(/\[\s*((?:'data\/[^']+',\s*)+'overrides\.js',\s*'engine\.js')\s*\]/)[1].match(/'([^']+)'/g).map(s => s.slice(1, -1));
global.__T = {};
files.forEach(f => {
  let code = fs.readFileSync(path.join(dir, f), 'utf8');
  if (f === 'engine.js') {
    const mark = (tag, expr) => `if (window.__T && window.__TN && window.__TN[p.norm]) { (window.__T[p.norm] = window.__T[p.norm] || []).push(['${tag}', ${expr}]); }\n`;
    const ins = (needle, tag, expr, after) => { const i = code.indexOf(needle); if (i < 0) { console.log('MISSING needle for', tag); return; } const at = after ? code.indexOf('\n', i) + 1 : i; code = code.slice(0, at) + mark(tag, expr) + code.slice(at); };
    ins("    if (ncSrc !== 'clay-fallback') {\n      var sa = shadowAgeAdjust", 'raw history prior (0.5 x 3yr + 0.5 x last 8)', 'ncPrior / scale', false);
    ins("    var ncV2 = !(typeof window !== 'undefined' && window.SIM_NC_V2 === false)", 'after regression + age curve + opportunity prior', 'ncPrior / scale', false);
    ins("    // v2.3: demoted veterans", 'after the ADP market blend', 'ncPrior / scale', false);
    ins("    if (ncV2 && ncSrc !== 'clay-fallback' && ncPm != null) { ncPrior = (ncPm + NC_SHADOW.k", 'before the shrink (after docks / grade / 2nd-yr)', 'ncPrior / scale', false);
    ins("    // v2.15: LEARNED SEASON PRIOR", 'after the 0.8 shrink toward the position mean (' + "' + ncPm + '" + ')', 'ncPrior / scale', false);
    ins("    var ncP = ncV2 ? NC_SHADOW.P[p.pos] : null, ncEp", 'after the ridge mix = FINAL PRIOR', 'ncPrior / scale', false);
    ins("    var ncBaseW = jsBasePg(p, sc, ncPrior, ncP, ncUse)", 'blended rate (prior + week-1 evidence)', 'ncBaseW / scale', true);
    ins("    var ncBaseW = jsBasePg(p, sc, ncPrior, ncP, ncUse)", 'prior strength P used / evidence', "'P=' + ncP + ' usage=' + JSON.stringify(ncUse)", true);
  }
  vm.runInThisContext(code, { filename: f });
});
const E = global.SimEngine, WK = +(process.argv[2] || 2), sc = E.PRESETS.half, schedule = E.buildSchedule(), players = E.buildPlayers(schedule); E.applyInSeasonInjuries(players, WK, { active: true });
const names = process.argv.slice(3).length ? process.argv.slice(3) : ['Zay Flowers', 'Justin Jefferson', "Ja'Marr Chase"];
global.__TN = {}; names.forEach(nm => { const p = players.list.find(x => x.name === nm); if (p) global.__TN[p.norm] = 1; });
names.forEach(nm => {
  const p = players.list.find(x => x.name === nm); if (!p) { console.log(nm, 'not found'); return; }
  global.__T[p.norm] = []; const w = E.weeklyProjection(p, WK, sc, schedule);
  console.log(`\n=== ${nm} (${p.pos} ${p.tm}, ADP ${Math.round(p.adp)}) -> shadow ${w.ncMean.toFixed(2)} | tags ${w.ncSrc}`);
  const seen = {}; (global.__T[p.norm] || []).forEach(([t, v]) => { if (seen[t]) return; seen[t] = 1; console.log(`   ${t.padEnd(62)} ${typeof v === 'number' ? v.toFixed(2) : v}`); });
  console.log(`   chain this week: Vegas ${w.why ? w.why.veg.toFixed(3) : '-'} | shadow / blended rate = ${(w.ncMean / ((global.__T[p.norm].find(x => /blended rate/.test(x[0])) || [0, NaN])[1])).toFixed(3)} (all multipliers incl. matchup, vacated, tilts)`);
});
