// Weekly-vs-season cross-validation repairs (2026-07-22 audit).
//
// Summing reg-season weekly game logs (independent source) against every
// ALL_PLAYERS_DB season row surfaced two corruption shapes this fixes:
//
// 1) GUTTED rows — stat fields missing wholesale while weekly logs prove the
//    production. Detector: fully-covered season (weekly reg-game count == gp)
//    where weekly sums exceed the row by >100 yds in any yardage field or >3
//    in any count field. Found: Alex Smith 2013 (row held the TE Alex
//    Smith's receiving scraps — py 0 vs 3,313 proven; another name-collision
//    graft) and Rodney Smith 2021 (1 gp, 5/48 receiving missing). Repair:
//    rebuild all stat fields from reg-season weekly sums, fpts recomputed
//    from components (half-PPR, -2/int — the season-side convention).
//
// 2) ZERO-fpts rows whose own stat fields score >5 — fpts was zeroed but the
//    stats are present (Ronald Jones II 2022, Jordan Thomas 2020). Repair:
//    fpts = components, ppg recomputed. Rows where stored fpts sits a few
//    points BELOW components (fumble-basis noise, ~24 rows) are left alone —
//    ambiguous which side is right.
//
// NOT repaired (documented, structural): weekly files score INTs at -1 vs
// -2 in season rows (QB weekly sums run ~1pt/INT hot), and return-specialist
// season totals legitimately carry return-TD points absent from the weekly
// field set.
//
// Idempotent. Run: node scripts/fix_weekly_xcheck_rows.js [--write]

const fs = require('fs');
const path = require('path');

const AP_FILE = path.join(__dirname, '..', 'data', 'all_players.js');
const WRITE = process.argv.includes('--write');

const apSrc = fs.readFileSync(AP_FILE, 'utf8');
const AP_PREFIX = 'const ALL_PLAYERS_DB = ';
if (!apSrc.startsWith(AP_PREFIX)) throw new Error('unexpected all_players.js prefix');
const APDB = JSON.parse(apSrc.slice(AP_PREFIX.length).replace(/;\s*$/, ''));

global.window = global;
const APW = global.ALL_PLAYERS_WEEKLY = {}; // files 2-5 assign into the global directly
for (let i = 1; i <= 5; i++) {
  const src = fs.readFileSync(path.join(__dirname, '..', 'data', `all_players_weekly_${i}.js`), 'utf8');
  eval(src + '; Object.assign(APW, ALL_PLAYERS_WEEKLY);'); // file 1 shadows with its own const
}

const regCut = (yr) => yr >= 2021 ? 18 : 17;
const r1 = (v) => Math.round(v * 10) / 10;
const SUM_FIELDS = ['pc', 'pa', 'py', 'ptd', 'int', 'ra', 'ry', 'rtd', 'rec', 'rcy', 'rctd', 'fl', 'tgt'];

function components(y) {
  const rc = y.rc != null ? y.rc : (y.rec || 0);
  return (y.py || 0) / 25 + (y.ptd || 0) * 4 + (y.int || 0) * -2
    + (y.ry || 0) / 10 + (y.rtd || 0) * 6 + rc * 0.5
    + (y.rcy || 0) / 10 + (y.rctd || 0) * 6 - (y.fl || 0) * 2;
}

let rebuilt = 0, fptsFixed = 0;

for (const p of APDB) {
  const w = APW[p.name];
  for (const s of p.career || []) {
    if (s.yr == null) continue;

    // 2) zero-fpts with live components
    if ((s.fpts || 0) === 0 && components(s) > 5) {
      s.fpts = r1(components(s));
      if (s.gp > 0) s.ppg = r1(s.fpts / s.gp);
      fptsFixed++;
      console.log(`fpts-zeroed: ${p.name} ${s.yr} -> fpts ${s.fpts}`);
      continue;
    }

    // 1) gutted rows — only when this year has a single stint row and full
    // weekly coverage, so the weekly sum maps 1:1 onto this row
    const weeks = w && w.seasons && w.seasons[s.yr];
    if (!weeks || !weeks.length) continue;
    if ((p.career || []).filter(x => x.yr === s.yr).length !== 1) continue;
    const ws = { games: 0 };
    for (const x of weeks) {
      if ((x.wk || 0) > regCut(s.yr)) continue;
      ws.games++;
      for (const f of SUM_FIELDS) ws[f] = (ws[f] || 0) + (x[f] || 0);
    }
    if (ws.games !== (s.gp || 0)) continue;
    const rowRec = s.rc != null ? s.rc : (s.rec || 0);
    const bigMiss = ['py', 'ry', 'rcy'].some(f => (ws[f] || 0) - (s[f] || 0) > 100)
      || ((ws.ptd || 0) - (s.ptd || 0) > 3) || ((ws.rtd || 0) - (s.rtd || 0) > 3)
      || ((ws.rctd || 0) - (s.rctd || 0) > 3) || ((ws.rec || 0) - rowRec > 3);
    if (!bigMiss) continue;
    for (const f of SUM_FIELDS) {
      if (f === 'rec') { if (s.rc != null) s.rc = ws.rec || 0; else s.rec = ws.rec || 0; }
      else s[f] = ws[f] || 0;
    }
    s.fpts = r1(components(s));
    if (s.gp > 0) s.ppg = r1(s.fpts / s.gp);
    rebuilt++;
    console.log(`gutted-rebuilt: ${p.name} ${s.yr} -> gp ${s.gp}, py ${s.py}, ry ${s.ry}, rcy ${s.rcy}, fpts ${s.fpts}`);
  }
}

console.log(`rebuilt ${rebuilt} gutted rows, fixed ${fptsFixed} zeroed-fpts rows`);
if (WRITE) {
  fs.writeFileSync(AP_FILE, AP_PREFIX + JSON.stringify(APDB) + ';', 'utf8');
  console.log('WROTE ' + AP_FILE);
} else {
  console.log('dry run — pass --write to apply');
}
