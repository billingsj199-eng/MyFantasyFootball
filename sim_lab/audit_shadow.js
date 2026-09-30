// SHADOW AUDIT (2026-09-17, after the TD-luck double count): run an in-memory instrumented copy of engine.js over every top-150 player and
// check that the final shadow number is fully explained by  blended rate x chain + scaled luck  and the tagged post-steps. Anything
// unexplained is a candidate bug. Also sanity-checks each input against simple invariants. Usage: node audit_shadow.js <week>
const fs = require('fs'), path = require('path'), vm = require('vm'); global.window = global; const dir = __dirname;
const src = fs.readFileSync(path.join(dir, 'export_site_proj.js'), 'utf8');
const files = src.match(/\[\s*((?:'data\/[^']+',\s*)+'overrides\.js',\s*'engine\.js')\s*\]/)[1].match(/'([^']+)'/g).map(s => s.slice(1, -1));
global.__A = {};
files.forEach(f => {
  let code = fs.readFileSync(path.join(dir, f), 'utf8');
  if (f === 'engine.js') {
    const needle = "    var espnPts = null, rmMean = null, rmFinal = null;";
    if (code.indexOf(needle) < 0) throw new Error('audit needle missing');
    code = code.replace(needle, "    if (window.__A) window.__A[p.norm] = { prior: ncPrior / scale, base: ncBaseW / scale, scale: scale, chain: ncChain, chainNoIA: ncChainNoIA, iA: iA, luck: luckAdj, luckScale: ncLuckScale, P: ncP, use: ncUse, veg: mult, opp: oppM, cb: cbM, sm: sM, ramp: rampF, clayPg: clayPg, jsPg: jsPg, out: (typeof ncOut !== 'undefined' ? ncOut : null) };\n" + needle);
  }
  vm.runInThisContext(code, { filename: f });
});
const E = global.SimEngine, WK = +(process.argv[2] || 2), sc = E.PRESETS.half, schedule = E.buildSchedule(), players = E.buildPlayers(schedule); E.applyInSeasonInjuries(players, WK, { active: true });
const rows = [];
players.list.forEach(p => {
  if (!/^(QB|RB|WR|TE)$/.test(p.pos) || p.adp == null || p.adp > 150) return;
  const w = E.weeklyProjection(p, WK, sc, schedule); const a = global.__A[p.norm]; if (!w || w.ncMean == null || !a) return;
  rows.push({ p, w, a });
});
console.log(`audited ${rows.length} top-150 players, week ${WK}`);
// 1. reconstruction: expected = base x chain + luck x luckScale, then tagged post-multipliers
const known = { '+tot': 1, '+qbout': 1, '+qboutS': 1, '+nochart': 1, '+qret': 1, '+vacx': 1, '+out': 1 };
let unexplained = [];
rows.forEach(({ p, w, a }) => {
  const s = String(w.ncSrc || ''); let exp = Math.max(0, a.base * a.scale * a.chain + a.luck * a.luckScale);
  const post = []; if (/\+tot/.test(s)) post.push('game total'); if (/\+qbout/.test(s)) post.push('backup QB'); if (/\+nochart/.test(s)) post.push('no chart'); if (/\+qret/.test(s)) post.push('Q return'); if (/\+vacx/.test(s)) post.push('vacated'); if (/\+out/.test(s)) post.push('out');
  const ratio = exp > 0.05 ? w.ncMean / exp : (w.ncMean > 0.05 ? Infinity : 1);
  if (Math.abs(ratio - 1) > 0.005 && post.length === 0) unexplained.push({ n: p.name, pos: p.pos, nc: w.ncMean, exp, ratio, s });
});
console.log(`\n1) RECONSTRUCTION: shadow = blended rate x chain + scaled TD luck, then tagged steps. Players off by more than 0.5% with NO tag explaining it: ${unexplained.length}`);
unexplained.slice(0, 15).forEach(r => console.log(`   ${r.n.padEnd(22)} ${r.pos} shadow ${r.nc.toFixed(2)} vs rebuilt ${r.exp.toFixed(2)} (x${r.ratio.toFixed(3)}) ${r.s}`));
// 2. invariants on the inputs
const flag = (title, list, fmt) => { console.log(`\n${title}: ${list.length}`); list.slice(0, 12).forEach(r => console.log('   ' + fmt(r))); };
flag('2) prior far from BOTH Clay and the blended live base (|prior / clayPg - 1| > 45%) - possible bad input', rows.filter(({ a }) => a.clayPg > 4 && Math.abs(a.prior * a.scale / a.clayPg - 1) > 0.45),
  ({ p, w, a }) => `${p.name.padEnd(22)} ${p.pos} adp ${Math.round(p.adp)} prior ${a.prior.toFixed(1)} vs Clay ${(a.clayPg / a.scale).toFixed(1)} | ${w.ncSrc}`);
flag('3) still on the CLAY FALLBACK inside the top 150 (the shadow is not Clay-free for these)', rows.filter(({ w }) => /clay-fallback/.test(String(w.ncSrc))), ({ p, w }) => `${p.name.padEnd(22)} ${p.pos} adp ${Math.round(p.adp)} shadow ${w.ncMean.toFixed(1)}`);
flag('4) scoring scale far from 1 on the half-PPR sheet (should be exactly 1)', rows.filter(({ a }) => Math.abs(a.scale - 1) > 1e-6), ({ p, a }) => `${p.name.padEnd(22)} scale ${a.scale.toFixed(4)}`);
flag('5) availability above 1 inside the shadow chain (live role boost leaking in; should be capped at 1 when redistribution is on)', rows.filter(({ a, w }) => a.iA > 1.001 && Math.abs(a.chain / a.chainNoIA - Math.min(1, a.iA)) > 0.01 && !/\+vacx/.test(String(w.ncSrc))),
  ({ p, w, a }) => `${p.name.padEnd(22)} ${p.pos} iA ${a.iA.toFixed(2)} chain/noIA ${(a.chain / a.chainNoIA).toFixed(2)} shadow ${w.ncMean.toFixed(1)} | ${w.ncSrc}`);
flag('6) usage evidence missing for an RB / WR who has played (falls back to points; luck scale differs)', rows.filter(({ p, a }) => /^(RB|WR)$/.test(p.pos) && !a.use && ((global.SIM_2026 || {}).players || {})[p.norm] && ((global.SIM_2026 || {}).players || {})[p.norm].g > 0),
  ({ p, w }) => `${p.name.padEnd(22)} ${p.pos} shadow ${w.ncMean.toFixed(1)} | ${w.ncSrc}`);
flag('7) usage xFP/g wildly off the points/g it replaces (> 2.5x or < 0.3x, both > 4) - check the xFP feed / name match', rows.filter(({ p, a }) => { const r = ((global.SIM_2026 || {}).players || {})[p.norm]; return a.use && r && r.ppg > 4 && a.use.xfpPg > 0 && (a.use.xfpPg / r.ppg > 2.5 || a.use.xfpPg / r.ppg < 0.3); }),
  ({ p, a }) => { const r = global.SIM_2026.players[p.norm]; return `${p.name.padEnd(22)} ${p.pos} xFP/g ${a.use.xfpPg.toFixed(1)} vs points/g ${r.ppg.toFixed(1)} (g ${r.g})`; });
flag('8) ESPN number present but the mix did not use it, or mix outside its two inputs', rows.filter(({ w }) => w.espnPts != null && w.espnPts > 0.5 && w.ncMean > 0 && (w.rmMean < Math.min(w.ncMean, w.espnPts) - 1e-6 || w.rmMean > Math.max(w.ncMean, w.espnPts) + 1e-6)),
  ({ p, w }) => `${p.name.padEnd(22)} shadow ${w.ncMean.toFixed(1)} ESPN ${w.espnPts.toFixed(1)} mix ${w.rmMean.toFixed(1)}`);
flag('9) Questionable / docked players (availability < 1) - by design, listed so they are not mistaken for bugs', rows.filter(({ a }) => a.iA < 0.999 && a.iA > 0), ({ p, w, a }) => `${p.name.padEnd(22)} ${p.pos} ${String(p.injFlag || '').padEnd(20)} availability ${a.iA.toFixed(2)} shadow ${w.ncMean.toFixed(1)}`);
