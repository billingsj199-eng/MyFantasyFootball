// RANK MIX weekly read (2026-09-17). Usage: node rankmix_week.js <week> [topN]
// NOTE: the LIVE BOARD number = propMean when book lines exist, else jsMean (engine effMean); weeklyProjection().mean is the raw Clay stack.
// Prints, per position, the rankings from the rank mix (50% Clay-free shadow + 50% ESPN, book anchor on top) beside the live board,
// the shadow and ESPN, and lists where the mix's RANK differs most from the live board. Top 150 by ADP only (Jack's focus).
const fs = require('fs'), path = require('path'), vm = require('vm'); global.window = global; const dir = __dirname;
const src = fs.readFileSync(path.join(dir, 'export_site_proj.js'), 'utf8');
const files = src.match(/\[\s*((?:'data\/[^']+',\s*)+'overrides\.js',\s*'engine\.js')\s*\]/)[1].match(/'([^']+)'/g).map(s => s.slice(1, -1));
files.forEach(f => vm.runInThisContext(fs.readFileSync(path.join(dir, f), 'utf8'), { filename: f }));
const E = global.SimEngine, WK = +(process.argv[2] || 2), TOPN = +(process.argv[3] || 0), sc = E.PRESETS.half;
const schedule = E.buildSchedule(), players = E.buildPlayers(schedule); E.applyInSeasonInjuries(players, WK, { active: true });
const rows = [];
players.list.forEach(p => {
  if (!/^(QB|RB|WR|TE)$/.test(p.pos) || p.adp == null || p.adp > 150) return;
  const w = E.weeklyProjection(p, WK, sc, schedule); if (!w || !(w.mean > 0.5) || w.ncMean == null) return;
  rows.push({ n: p.name, pos: p.pos, tm: p.tm, adp: Math.round(p.adp), live: (w.propMean != null ? w.propMean : (w.jsMean != null ? w.jsMean : w.mean)), clay: (w.jsMean != null ? w.jsMean : w.mean), nc: w.ncMean, espn: w.espnPts, mix: w.rmMean, mixb: w.rmFinal, lined: w.propSrc === 'line' });
});
const withEspn = rows.filter(r => r.espn != null && r.espn > 0.5).length;
console.log(`WEEK ${WK} rank mix | top-150 players ${rows.length} | with an ESPN projection ${withEspn} | with direct book lines ${rows.filter(r => r.lined).length}`);
const N = { QB: 16, RB: 30, WR: 36, TE: 14 };
['QB', 'RB', 'WR', 'TE'].forEach(ps => {
  const r = rows.filter(x => x.pos === ps); const rk = key => { const s = [...r].sort((a, b) => (b[key] ?? -1) - (a[key] ?? -1)); const m = {}; s.forEach((x, i) => m[x.n] = i + 1); return m; };
  const rL = rk('live'), rM = rk('mixb'), rS = rk('nc'), rE = rk('espn');
  console.log(`\n=== ${ps}: rank mix + books (rank | pts)   live board rank | shadow rank | ESPN rank ===`);
  [...r].sort((a, b) => b.mixb - a.mixb).slice(0, TOPN || N[ps]).forEach(x => {
    const d = rL[x.n] - rM[x.n];
    console.log(`  ${String(rM[x.n]).padStart(2)}. ${x.n.padEnd(22)} ${String(x.tm).padEnd(4)} ${x.mixb.toFixed(1).padStart(5)}  | live ${String(rL[x.n]).padStart(2)} (${x.live.toFixed(1)})  shadow ${String(rS[x.n]).padStart(2)} (${x.nc.toFixed(1)})  ESPN ${x.espn != null ? String(rE[x.n]).padStart(2) + ' (' + x.espn.toFixed(1) + ')' : ' -'}${Math.abs(d) >= 4 ? (d > 0 ? '   UP ' + d + ' vs live' : '   DOWN ' + (-d) + ' vs live') : ''}`);
  });
});
const all = rows.map(r => ({ ...r, d: r.mixb - r.live })).sort((a, b) => Math.abs(b.d) - Math.abs(a.d));
console.log('\n=== biggest point differences, rank mix + books vs the live board ===');
all.slice(0, 14).forEach(x => console.log(`  ${x.n.padEnd(22)} ${x.pos} ${String(x.tm).padEnd(4)} adp ${String(x.adp).padStart(3)} | live ${x.live.toFixed(1).padStart(5)} -> mix ${x.mixb.toFixed(1).padStart(5)} (${x.d >= 0 ? '+' : ''}${x.d.toFixed(1)}) | shadow ${x.nc.toFixed(1)} ESPN ${x.espn != null ? x.espn.toFixed(1) : '-'}${x.lined ? ' [books]' : ''}`));
const md = rows.reduce((s, r) => s + Math.abs(r.mixb - r.live), 0) / rows.length;
console.log(`\nmean |mix - live| ${md.toFixed(2)} pts | on book-lined players ${(rows.filter(r => r.lined).reduce((s, r) => s + Math.abs(r.mixb - r.live), 0) / Math.max(1, rows.filter(r => r.lined).length)).toFixed(2)} | un-lined ${(rows.filter(r => !r.lined).reduce((s, r) => s + Math.abs(r.mixb - r.live), 0) / Math.max(1, rows.filter(r => !r.lined).length)).toFixed(2)}`);
