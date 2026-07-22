// Companion to fix_fpts_basis.js for data/legend_careers.js.
//
// The 2026-07-21 WSR name-collision repair (commit 816f276) rebuilt the
// Franken-careers (David Johnson, Kevin Smith, Zach Miller, Chris Henry,
// Ben Watson) from cleaned weekly logs on a FULL-PPR basis, while the app
// treats every career[].fpts as half-PPR — and fix_fpts_basis.js only
// normalized all_players.js. Because _careerReplaces breaks length ties by
// higher fpts sum, the inflated LEGEND careers win the boot merge for these
// retired players (DJ 2016 rendered 405.8 half / 445.8 "PPR" instead of
// 365.8 / 405.8).
//
// Same decisive classifier as fix_fpts_basis.js: flip fpts -= 0.5*rc when
// the stored value is explained by full-PPR components, recompute ppg.
// Idempotent. Run: node scripts/fix_legend_fpts_basis.js [--write]

const fs = require('fs');
const path = require('path');

const FILE = path.join(__dirname, '..', 'data', 'legend_careers.js');
const WRITE = process.argv.includes('--write');
const src = fs.readFileSync(FILE, 'utf8');
const PREFIX = 'const LEGEND_CAREERS=';
if (!src.startsWith(PREFIX)) throw new Error('unexpected legend_careers.js prefix');
const DB = JSON.parse(src.slice(PREFIX.length).replace(/;\s*$/, ''));

const r1 = (v) => Math.round(v * 10) / 10;
let flipped = 0;
const flippedPlayers = new Set();

for (const [name, career] of Object.entries(DB)) {
  for (const y of career || []) {
    const rc = y.rc || 0;
    if (!rc || typeof y.fpts !== 'number' || !y.fpts) continue;
    const halfV = (y.py || 0) / 25 + (y.ptd || 0) * 4 + (y.int || 0) * -2
      + (y.ry || 0) / 10 + (y.rtd || 0) * 6 + rc * 0.5
      + (y.rcy || 0) / 10 + (y.rctd || 0) * 6 - (y.fl || 0) * 2;
    const dH = Math.abs(y.fpts - halfV);
    const dF = Math.abs(y.fpts - halfV - rc * 0.5);
    if (dF < dH - 1.0 && dF <= Math.max(2.0, 0.2 * rc)) {
      y.fpts = r1(y.fpts - rc * 0.5);
      if (y.gp > 0 && typeof y.ppg === 'number') y.ppg = r1(y.fpts / y.gp);
      flipped++;
      flippedPlayers.add(name);
    }
  }
}

console.log(`flipped ${flipped} full-PPR seasons across ${flippedPlayers.size} players: ${[...flippedPlayers].join(', ')}`);
if (WRITE) {
  fs.writeFileSync(FILE, PREFIX + JSON.stringify(DB) + ';', 'utf8');
  console.log('WROTE ' + FILE);
} else {
  console.log('dry run — pass --write to apply');
}
