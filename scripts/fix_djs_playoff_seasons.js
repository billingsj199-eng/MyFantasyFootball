// One-off data repair: replace playoff-contaminated d.js career/s25 rows with
// the regular-season values from ALL_PLAYERS_DB.
//
// The career arrays baked into data/d.js were originally summed from weekly
// data that included playoff weeks, so 109 players / 221 seasons carry
// inflated gp + stats (Kelce 2020: 128 rec / 307.9 half-PPR = 105 rec reg
// season + 2 playoff games; Saquon 2024: 373 ra / 2128 ry vs 345 / 2005).
// ALL_PLAYERS_DB rows are reg-season official and were just normalized to
// half-PPR + validated against weekly sums (scripts/fix_fpts_basis.js), so
// they're the ground truth here. Because _careerReplaces breaks length ties
// by HIGHER fpts sum, the inflated d.js careers were systematically winning
// the boot merge — cards and the Fantasy Game rendered playoff-padded
// seasons for 83 of those players.
//
// A row is replaced when the same player+year exists in ALL_PLAYERS_DB
// (stints summed) and gp OR any stat field disagrees:
//   gp_d > gp_ap  -> playoff contamination (the 221 rows above)
//   gp_d < gp_ap  -> d.js weekly undercoverage (Josh Allen 2019 14 vs 16)
//   gp equal, stats differ -> partially-padded rows (Kelce 2022 gp 17 both
//   sides but d.js rc 116 vs reg-season 110) and stale weekly-derived sums
// Stat fields (gp/py/ptd/int/ra/ry/rtd/rc/rcy/rctd/fl/fpts) are copied from
// the ALL_PLAYERS_DB aggregate, ppg recomputed; yr and the PFF yrr field
// (which only d.js carries) are preserved. Guards: position must agree when
// both sides have one (same-name-collision safety), and zeroed ap aggregates
// never overwrite a non-zero d row.
//
// Idempotent (after a write, gp matches and every row no-ops).
// Run: node scripts/fix_djs_playoff_seasons.js [--write]

const fs = require('fs');
const path = require('path');

const D_FILE = path.join(__dirname, '..', 'data', 'd.js');
const AP_FILE = path.join(__dirname, '..', 'data', 'all_players.js');
const WRITE = process.argv.includes('--write');

const dSrc = fs.readFileSync(D_FILE, 'utf8');
const D_PREFIX = 'const D = ';
if (!dSrc.startsWith(D_PREFIX)) throw new Error('unexpected d.js prefix');
const arrEnd = dSrc.indexOf('];');
if (arrEnd < 0) throw new Error('d.js array terminator not found');
const dTail = dSrc.slice(arrEnd + 2); // "\n// comment...\nwindow.D = D;\n"
const D = JSON.parse(dSrc.slice(D_PREFIX.length, arrEnd + 1));

const apSrc = fs.readFileSync(AP_FILE, 'utf8');
const AP_PREFIX = 'const ALL_PLAYERS_DB = ';
if (!apSrc.startsWith(AP_PREFIX)) throw new Error('unexpected all_players.js prefix');
const APDB = JSON.parse(apSrc.slice(AP_PREFIX.length).replace(/;\s*$/, ''));

const apByName = {};
for (const p of APDB) if (!apByName[p.name]) apByName[p.name] = p;

const r1 = (v) => Math.round(v * 10) / 10;
const STAT_FIELDS = ['py', 'ptd', 'int', 'ra', 'ry', 'rtd', 'rc', 'rcy', 'rctd', 'fl'];

// Sum a player's ALL_PLAYERS_DB rows per year (mid-season trades = one stint
// row per team; the d.js row is the full-season total).
function apYearAggregates(ap) {
  const byYr = {};
  for (const s of ap.career || []) {
    if (s.yr == null) continue;
    const a = byYr[s.yr] || (byYr[s.yr] = { gp: 0, fpts: 0, py: 0, ptd: 0, int: 0, ra: 0, ry: 0, rtd: 0, rc: 0, rcy: 0, rctd: 0, fl: 0 });
    a.gp += s.gp || 0;
    a.fpts += s.fpts || 0;
    for (const f of STAT_FIELDS) a[f] += s[f] || 0;
  }
  return byYr;
}

function repairRow(row, agg) {
  row.gp = agg.gp;
  for (const f of STAT_FIELDS) row[f] = agg[f];
  row.fpts = r1(agg.fpts);
  row.ppg = agg.gp > 0 ? r1(agg.fpts / agg.gp) : 0;
}

function rowDiffers(row, agg) {
  if ((row.gp || 0) !== agg.gp) return 'gp-' + ((row.gp || 0) > agg.gp ? 'inflated' : 'undercount');
  for (const f of STAT_FIELDS) if ((row[f] || 0) !== agg[f]) return 'stats';
  if (Math.abs((row.fpts || 0) - agg.fpts) > 0.05) return 'stats';
  return null;
}

let inflated = 0, undercount = 0, statsOnly = 0, s25Fixed = 0;
const touchedPlayers = new Set();
const samples = [];

for (const d of D) {
  const ap = apByName[d.n];
  if (!ap) continue;
  if (ap.pos && d.s && ap.pos !== d.s) continue; // same-name different player
  const byYr = apYearAggregates(ap);

  for (const row of d.career || []) {
    const agg = byYr[row.yr];
    if (!agg || agg.gp <= 0) continue;
    if (agg.fpts === 0 && (row.fpts || 0) > 0) continue; // zeroed-ap guard
    const dir = rowDiffers(row, agg);
    if (!dir) continue;
    if (dir === 'gp-inflated') inflated++; else if (dir === 'gp-undercount') undercount++; else statsOnly++;
    if (samples.length < 12) {
      samples.push(`${d.n} ${row.yr} [${dir}]: gp ${row.gp}->${agg.gp}, fpts ${row.fpts}->${r1(agg.fpts)}`);
    }
    repairRow(row, agg);
    touchedPlayers.add(d.n);
  }

  // s25 carries the same weekly-derived 2025 season block
  if (d.s25 && d.s25.yr === 2025) {
    const agg = byYr[2025];
    if (agg && agg.gp > 0 && !(agg.fpts === 0 && (d.s25.fpts || 0) > 0) && rowDiffers(d.s25, agg)) {
      repairRow(d.s25, agg);
      s25Fixed++;
      touchedPlayers.add(d.n);
    }
  }
}

console.log(`career rows repaired: ${inflated} playoff-inflated + ${undercount} undercounted + ${statsOnly} stats-only across ${touchedPlayers.size} players; s25 blocks: ${s25Fixed}`);
if (samples.length) console.log('  ' + samples.join('\n  '));

if (WRITE) {
  fs.writeFileSync(D_FILE, D_PREFIX + JSON.stringify(D) + ';' + dTail, 'utf8');
  console.log('WROTE ' + D_FILE);
} else {
  console.log('dry run — pass --write to apply');
}
