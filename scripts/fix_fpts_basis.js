// One-off data repair: normalize ALL_PLAYERS_DB career fpts to HALF-PPR basis.
//
// The app assumes career[].fpts is half-PPR everywhere (buildCareerTable's
// recAdj, _seasonPosRank's leaderboards), but ~3.7k player-seasons were stored
// as FULL PPR (fpts already includes 1.0/rec) — e.g. Ja'Marr Chase 2024 stored
// 403.0 = exact full-PPR, so the card's PPR view double-added receptions
// (27.4 PPG instead of 23.7) and HALF view silently showed full-PPR numbers.
//
// Classification per season (rc > 0 only; rc = 0 bases are identical):
//   halfV = components at 0.5/rec; dH = |fpts - halfV|; dF = |fpts - halfV - 0.5*rc|
//   Flip to half iff dF < dH - 1.0 AND dF <= 2.0
// The margin keeps QB rows with 1-2 receptions (0.5-pt swing, ambiguous under
// bonus-point noise like 2-pt conversions) untouched, and the dF cap refuses
// to flip rows whose stored fpts isn't actually explained by full-PPR
// components (those are reported, not guessed at).
//
// Flipped rows: fpts -= 0.5*rc (preserves any bonus points baked into the
// stored number) and ppg is recomputed. Run: node scripts/fix_fpts_basis.js

const fs = require('fs');
const path = require('path');

const FILE = path.join(__dirname, '..', 'data', 'all_players.js');
const src = fs.readFileSync(FILE, 'utf8');
const PREFIX = 'const ALL_PLAYERS_DB = ';
if (!src.startsWith(PREFIX)) throw new Error('unexpected all_players.js prefix');
const DB = JSON.parse(src.slice(PREFIX.length).replace(/;\s*$/, ''));

const r1 = (v) => Math.round(v * 10) / 10;
let flipped = 0, skippedUnexplained = 0;
const flippedPlayers = new Set();
const skipSamples = [];

for (const p of DB) {
  for (const y of (p.career || [])) {
    const rc = y.rc || 0;
    if (!rc || typeof y.fpts !== 'number') continue;
    const halfV = (y.py || 0) / 25 + (y.ptd || 0) * 4 + (y.int || 0) * -2
      + (y.ry || 0) / 10 + (y.rtd || 0) * 6 + rc * 0.5
      + (y.rcy || 0) / 10 + (y.rctd || 0) * 6 - (y.fl || 0) * 2;
    const dH = Math.abs(y.fpts - halfV);
    const dF = Math.abs(y.fpts - halfV - rc * 0.5);
    if (dF < dH - 1.0) {
      // dF is bonus-point noise (2-pt conversions, return TDs) not in the
      // components; allow more of it when the rec volume makes the full-vs-
      // half gap (0.5*rc) decisively larger than any plausible bonus.
      if (dF <= Math.max(2.0, 0.2 * rc)) {
        y.fpts = r1(y.fpts - rc * 0.5);
        if (y.gp > 0 && typeof y.ppg === 'number') y.ppg = r1(y.fpts / y.gp);
        flipped++;
        flippedPlayers.add(p.name);
      } else {
        skippedUnexplained++;
        if (skipSamples.length < 8) {
          skipSamples.push(`${p.name} ${y.yr} (rc ${rc}, dF ${dF.toFixed(1)})`);
        }
      }
    }
  }
}

fs.writeFileSync(FILE, PREFIX + JSON.stringify(DB) + ';', 'utf8');
console.log(`flipped ${flipped} full-PPR seasons across ${flippedPlayers.size} players to half basis`);
console.log(`skipped ${skippedUnexplained} full-leaning rows whose fpts components don't reconcile (left as-is)`);
if (skipSamples.length) console.log('  e.g. ' + skipSamples.join(' | '));
