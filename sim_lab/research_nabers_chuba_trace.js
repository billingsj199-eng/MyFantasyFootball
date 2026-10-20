// 2026-10-20 (Jack: "nabers and chuba are still too low"): layer-by-layer shadow trace for named players, current week = CUR,
// weeks 7..18. In-memory instrumented engine copy; nothing on disk changes. Usage:
//   node research_nabers_chuba_trace.js <curWeek> <wk,wk,...> "Name" "Name" [KILL=SIM_X,SIM_Y]
// Fixes vs trace_shadow.js: strips // comments before the file-list regex; injury week = CUR (not the traced week).
const fs = require('fs'), path = require('path'), vm = require('vm'); global.window = global; const dir = __dirname;
let src = fs.readFileSync(path.join(dir, 'export_site_proj.js'), 'utf8').replace(/\/\/[^\n]*/g, '');
const files = src.match(/\[\s*((?:'data\/[^']+',\s*)+'overrides\.js',\s*'engine\.js')\s*\]/)[1].match(/'([^']+)'/g).map(s => s.slice(1, -1));
const args = process.argv.slice(2);
const CUR = +(args[0] || 6), WKS = (args[1] || '7,9,12,15').split(',').map(Number);
const kills = args.filter(a => /^KILL=/.test(a)).map(a => a.slice(5).split(',')).flat();
const names = args.slice(2).filter(a => !/^(KILL|DROP)=/.test(a));
kills.forEach(k => { if (k) global[k] = false; });
global.__T = {};
files.forEach(f => {
  let code = fs.readFileSync(path.join(dir, f), 'utf8');
  if (f === 'engine.js') {
    const mark = (tag, expr) => `if (window.__T && window.__TN && window.__TN[p.norm] && !_ncPass) { (window.__T[p.norm] = window.__T[p.norm] || []).push(['${tag}', ${expr}]); }\n`;
    const ins = (needle, tag, expr, after) => { const i = code.indexOf(needle); if (i < 0) { console.log('MISSING needle for', tag); return; } const at = after ? code.indexOf('\n', i) + 1 : i; code = code.slice(0, at) + mark(tag, expr) + code.slice(at); };
    ins("    var ncRawHist = ncPrior;", 'raw history (h3/l8 blend)', "[ncPrior / scale, h3 != null ? h3 / scale : null, l8 != null ? l8 / scale : null, ncSrc]", false);
    ins("    var ncV2 = !(typeof window !== 'undefined' && window.SIM_NC_V2 === false)", 'after age curve + opp prior', '[ncPrior / scale, ncSrc]', false);
    ins("    // v2.3: demoted veterans", 'after ADP market blend', '[ncPrior / scale, ncSrc]', false);
    ins("    if (ncV2 && ncSrc !== 'clay-fallback' && ncPm != null) { ncPrior = (ncPm + NC_SHADOW.k", 'before shrink (docks/grade)', '[ncPrior / scale, ncSrc]', false);
    ins("    // v2.15: LEARNED SEASON PRIOR", 'after .8 shrink', '[ncPrior / scale]', false);
    ins("    // v2.5: swap the live (Clay-defined) rookie ramp", 'FINAL PRIOR (after ridge)', "[ncPrior / scale, typeof rgp === 'number' ? rgp : null]", false);
    ins("    var ncFiF = ncFillinPtsF(p, wk);", 'P / usage / evidence', "[ncP, ncUse ? JSON.stringify({x: ncUse.xfpPg && +(ncUse.xfpPg / scale).toFixed(2), lam: ncUse.lam, ps: ncUse.ptsScale && +ncUse.ptsScale.toFixed(3)}) : null, (jsData().players[p.norm] || {}).g, (jsData().players[p.norm] || {}).ppg]", false);
    ins("    var ncBaseW = jsBasePg(p, sc, ncPrior, ncP, ncUse, ncFiF), ncVk", 'blended rate ncBaseW', '[ncBaseW / scale]', true);
    ins("    // v2.22 TD-LUCK SCALE FOR THE SHADOW", 'ncBaseW after tdfloor/rsVol/rsBk', '[ncBaseW / scale, ncSrc]', false);
    ins("    var ncOut = shadowOut(p, wk);", 'ncBaseW after next layers; chainNoIA; iA', '[ncBaseW / scale, ncChainNoIA, iA, tdLuckAdj(p, sc) * ncLuckScale / scale]', false);
    ins("    ncAtVac = ncMean;", 'ncMean after vacancy', '[ncMean / scale]', false);
    ins("    var ncLater = !!(_inj && _inj.week >= 1 && wk > _inj.week);", 'ncMean after nmu/promo/qbout/vol', '[ncMean / scale, ncSrc]', false);
  }
  vm.runInThisContext(code, { filename: f });
});
// DROP=Name:1,2,3 removes those 2026 weeks from the player's evidence (SIM_2026 wf/wks/g/ppg and SIM_XFP_2026); half-PPR only (pg left as is)
args.filter(a => /^DROP=/.test(a)).forEach(a => { const [nm, wks] = a.slice(5).split(':'); const ws = wks.split(',').map(Number); const nk = Object.keys(global.SIM_2026.players).find(k => k === nm.toLowerCase().replace(/[^a-z ]/g, '').replace(/\s+/g, ' ').trim()) || nm.toLowerCase();
  const r = global.SIM_2026.players[nk]; if (!r) { console.log('DROP: no record', nk); return; }
  ws.forEach(w => { delete r.wf[w]; }); r.wks = r.wks.filter(w => ws.indexOf(w) < 0); r.g = r.wks.length; r.ppg = +(r.wks.reduce((s, w) => s + r.wf[w], 0) / r.g).toFixed(2);
  const x = global.SIM_XFP_2026 && global.SIM_XFP_2026[nk]; if (x && x.w) ws.forEach(w => { delete x.w[w]; delete x.w[String(w)]; });
  console.log('DROP', nk, 'weeks', ws.join(','), '-> g', r.g, 'ppg', r.ppg); });
const E = global.SimEngine, sc = E.PRESETS.half, schedule = E.buildSchedule(), players = E.buildPlayers(schedule);
global.SIM_NOW_MS = Date.parse('2026-10-20T12:00:00Z');
try { global.SIM_KICKOFFS_2026 = JSON.parse(fs.readFileSync(path.join(dir, 'data', 'kickoffs_2026.json'), 'utf8')); } catch (_) {}
E.applyInSeasonInjuries(players, CUR, { active: true });
global.__TN = {}; names.forEach(nm => { const p = players.list.find(x => x.name === nm); if (p) global.__TN[p.norm] = 1; });
const f2 = v => v == null ? '-' : (typeof v === 'number' ? v.toFixed(2) : String(v));
names.forEach(nm => {
  const p = players.list.find(x => x.name === nm); if (!p) { console.log(nm, 'not found'); return; }
  const rec = (global.SIM_2026.players || {})[p.norm] || {};
  console.log(`\n##### ${nm} ${p.pos} ${p.tm} ADP ${Math.round(p.adp)} exp ${p.exp} | 2026 g ${rec.g} ppg ${f2(rec.ppg)} l8 ${f2(rec.l8)} (${rec.l8g}) wf ${JSON.stringify(rec.wf)} | histPpg ${f2(p.histPpg)} (${p.histGames}) injFlag ${p.injFlag || '-'} | kills ${kills.join(',') || 'none'}`);
  WKS.forEach(wk => {
    global.__T[p.norm] = [];
    const w = E.weeklyProjection(p, wk, sc, schedule); if (!w) { console.log(`  W${wk}: bye/none`); return; }
    const eff = E.effMean(w);
    console.log(`  --- W${wk} (cur ${CUR}) EXPORT=${f2(eff)} | ncMean ${f2(w.ncMean)} jsPre(Clay form) ${f2(w.jsPre)} jsMean(after base blend bb ${w.bb}) ${f2(w.jsMean)} prop ${f2(w.propMean)} [${w.propSrc || '-'} w ${f2(w.propW)} cap ${p._bookCapped ? 'Y' : 'n'}] | Vegas ${f2(w.mult)} imp ${f2(w.slot && w.slot.implied)} opp ${w.slot && w.slot.opp}`);
    console.log(`      tags ${w.ncSrc}`);
    const seen = {}; (global.__T[p.norm] || []).forEach(([t, v]) => { if (seen[t]) return; seen[t] = 1; console.log(`      ${t.padEnd(44)} ${Array.isArray(v) ? v.map(f2).join(' | ') : f2(v)}`); });
    const wy = w.why || {}; console.log(`      why: avail ${f2(wy.avail)} iA ${f2(wy.iA)} ret ${f2(wy.ret)} wx ${f2(wy.weather)} snap ${f2(wy.snap)} route ${f2(wy.route)} vol ${f2(wy.vol)} peck ${f2(wy.peck)} opp ${f2(wy.opp)} luck ${f2(wy.luck)}`);
  });
});
