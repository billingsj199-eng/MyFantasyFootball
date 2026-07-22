// Rebuild hp.js _bestByTeam from canonical all_players.js careers.
//
// Why: hp.js was generated in two eras. Old entries carry FULL-PPR fpts
// (e.g. Michael Thomas NO 2019 = 373.6) while the Fantasy Game assumes all
// stored fpts are HALF-PPR and adds 0.5/rec on the fly in PPR mode — so old
// WR/RB/TE entries double-count receptions (MT showed 448.1 instead of 374.6).
// Newer entries were rebuilt with half-PPR values but bucketed seasons by the
// name-keyed PLAYER_TEAM_HISTORY, which is polluted by name collisions
// (David Johnson RB inherited the TE's PIT/LAC years, so his ARI best-by-team
// skipped 2015-2017 and landed on 2018 instead of his 365.8-pt 2016).
//
// Strategy, per HP player:
//  1. Match to all_players.js by name+pos. Career rows there are half-PPR
//     (post fix_fpts_basis) and carry per-season tm — the ground truth for
//     which team a season belongs to. Coverage starts 1999.
//  2. For each team, the best career row REPLACES the stored row when the
//     stored row's year falls inside career coverage (>= player's first
//     career year). Teams present in career but missing from _bestByTeam are
//     added; _teams gains the modern team name.
//  3. Rows we can't rebuild (unmatched player, or pre-1999 season) are kept,
//     but if the stored fpts matches the half-PPR formula + 1.0/rec signature
//     (i.e. it's a full-PPR number), we subtract 0.5*rc to restore half-PPR.
//     Rows matching neither formula are left alone and reported.
//  4. _yrs end is corrected from all_players `last` for matched players
//     (MT said 2016-2024; he last played 2023). Start only ever extends down.
//
// Run: node scripts/rebuild_hp_bestbyteam.js          (report only)
//      node scripts/rebuild_hp_bestbyteam.js --write  (rewrite data/hp.js)

const fs = require('fs');
const path = require('path');
const BASE = path.join(__dirname, '..', 'data');
const WRITE = process.argv.includes('--write');

function loadJS(file, globalName) {
  const txt = fs.readFileSync(path.join(BASE, file), 'utf8');
  const sandbox = { window: {} };
  new Function('s', 'window', txt.replace(/^const\s+/, 'var ') + `\n;s.${globalName}=${globalName};`)(sandbox, sandbox.window);
  return sandbox[globalName];
}

const HP = loadJS('hp.js', 'HP');
const ALL = loadJS('all_players.js', 'ALL_PLAYERS_DB');
const TEAM_ABBR_MAP = loadJS('team_abbr_map.js', 'TEAM_ABBR_MAP');

const TEAM_ALIASES = {
  'St. Louis Rams': 'Los Angeles Rams',
  'San Diego Chargers': 'Los Angeles Chargers',
  'Oakland Raiders': 'Las Vegas Raiders',
  'Houston Oilers': 'Tennessee Titans',
  'Phoenix Cardinals': 'Arizona Cardinals',
  'St. Louis Cardinals': 'Arizona Cardinals',
  'Los Angeles Raiders': 'Las Vegas Raiders',
  'Baltimore Colts': 'Indianapolis Colts',
  'Boston Patriots': 'New England Patriots'
};
const ABBR_TO_FULL = {};
Object.entries(TEAM_ABBR_MAP).forEach(([full, abbr]) => { ABBR_TO_FULL[abbr] = full; });
// all_players uses nflverse-normalized abbrs; LA = Rams (1999-2024 rows), LAR appears 2025+
ABBR_TO_FULL['LA'] = 'Los Angeles Rams';
ABBR_TO_FULL['LAR'] = 'Los Angeles Rams';

function abbrToModern(abbr) {
  const full = ABBR_TO_FULL[abbr] || abbr;
  return TEAM_ALIASES[full] || full;
}
function keyToModern(teamKey) { return TEAM_ALIASES[teamKey] || teamKey; }

const byNamePos = {};
ALL.forEach(p => { byNamePos[p.name + '|' + p.pos] = p; });

const round1 = x => Math.round(x * 10) / 10;
function halfPts(r) {
  return round1((r.py || 0) / 25 + (r.ptd || 0) * 4 - (r.int || 0) * 2 +
    (r.ry || 0) / 10 + (r.rtd || 0) * 6 +
    (r.rcy || 0) / 10 + (r.rctd || 0) * 6 + 0.5 * (r.rc || 0) - (r.fl || 0) * 2);
}

// Season row in _bestByTeam shape from an all_players career row
function toRow(s) {
  return {
    yr: s.yr, gp: s.gp || 0, py: s.py || 0, ptd: s.ptd || 0, int: s.int || 0,
    ra: s.ra || 0, ry: s.ry || 0, rtd: s.rtd || 0,
    rc: s.rc || 0, rcy: s.rcy || 0, rctd: s.rctd || 0, fl: s.fl || 0,
    fpts: s.fpts != null ? s.fpts : 0,
    ppg: s.ppg != null ? s.ppg : (s.gp ? round1((s.fpts || 0) / s.gp) : 0),
    pc: s.pc || 0, pa: s.pa || 0, tgt: s.tgt || 0
  };
}

const stats = { rebuilt: 0, added: 0, basisFixed: 0, keptPre: 0, unmatched: 0, unexplained: 0, yrsFixed: 0 };
const unexplainedExamples = [], bigChanges = [];

HP.forEach(h => {
  const ap = byNamePos[h.n + '|' + h.s];
  const career = (ap && ap.career) ? ap.career.filter(s => s.tm) : [];
  const careerMin = career.length ? Math.min(...career.map(s => s.yr)) : null;

  // Best career row per modern team
  const bestByModern = {};
  career.forEach(s => {
    const mt = abbrToModern(s.tm);
    if (!bestByModern[mt] || (s.fpts || 0) > (bestByModern[mt].fpts || 0)) bestByModern[mt] = s;
  });

  if (!ap) stats.unmatched++;

  const bbt = h._bestByTeam || {};
  const coveredModern = new Set();

  Object.entries(bbt).forEach(([teamKey, row]) => {
    const modern = keyToModern(teamKey);
    coveredModern.add(modern);
    const cand = bestByModern[modern];
    const rebuildable = cand && careerMin != null && row.yr >= careerMin;

    if (rebuildable) {
      const nrow = toRow(cand);
      if (nrow.yr !== row.yr || round1(nrow.fpts) !== round1(row.fpts)) {
        if (Math.abs((nrow.fpts || 0) - (row.fpts || 0)) > 20 || nrow.yr !== row.yr) {
          bigChanges.push(`${h.n} (${h.s}) ${teamKey}: yr ${row.yr}->${nrow.yr} fpts ${row.fpts}->${nrow.fpts}`);
        }
        stats.rebuilt++;
      }
      bbt[teamKey] = nrow;
      return;
    }

    // Pre-coverage or unmatched: normalize basis in place if it bears the
    // full-PPR signature (stored = halfFormula + 0.5*rec).
    const half = halfPts(row);
    const rec = row.rc || 0;
    const dHalf = Math.abs((row.fpts || 0) - half);
    const dFull = Math.abs((row.fpts || 0) - (half + 0.5 * rec));
    const dStd = Math.abs((row.fpts || 0) - (half - 0.5 * rec));
    if (dHalf <= 2.0) {
      stats.keptPre++;                      // already half-PPR
    } else if (rec >= 10 && dFull <= 2.0) { // clear full-PPR signature
      row.fpts = round1((row.fpts || 0) - 0.5 * rec);
      if (row.gp) row.ppg = round1(row.fpts / row.gp);
      stats.basisFixed++;
    } else if (rec >= 10 && dStd <= 2.0) {  // clear standard-scoring signature
      row.fpts = round1((row.fpts || 0) + 0.5 * rec);
      if (row.gp) row.ppg = round1(row.fpts / row.gp);
      stats.basisFixed++;
    } else {
      stats.unexplained++;                  // QB formula quirks etc — rec-neutral, leave
      if (rec >= 10 && unexplainedExamples.length < 15) {
        unexplainedExamples.push(`${h.n} (${h.s}) ${teamKey} yr${row.yr} stored=${row.fpts} half=${half} full=${round1(half + 0.5 * rec)}`);
      }
    }

    // A pre-coverage row can be beaten by a covered season for the same team
    if (cand && (cand.fpts || 0) > (row.fpts || 0)) {
      bbt[teamKey] = toRow(cand);
      stats.rebuilt++;
    }
  });

  // Teams in career but absent from _bestByTeam
  Object.entries(bestByModern).forEach(([modern, s]) => {
    if (coveredModern.has(modern)) return;
    bbt[modern] = toRow(s);
    if (!(h._teams || []).some(t => keyToModern(t) === modern)) {
      h._teams = (h._teams || []).concat(modern);
    }
    stats.added++;
  });
  h._bestByTeam = bbt;

  // _yrs correction from all_players debut/last (end is exact for any matched
  // player since coverage runs through the present; start only extends down)
  if (ap && h._yrs && /^\d{4}-\d{4}$/.test(h._yrs)) {
    const [y1, y2] = h._yrs.split('-').map(Number);
    const n1 = Math.min(y1, ap.debut || y1);
    const n2 = ap.last || y2;
    if (n1 !== y1 || n2 !== y2) {
      h._yrs = n1 + '-' + n2;
      stats.yrsFixed++;
    }
  }
});

console.log('HP players:', HP.length, '| no all_players match:', stats.unmatched);
console.log('rows rebuilt from career:', stats.rebuilt);
console.log('team entries added:', stats.added);
console.log('pre-coverage rows basis-fixed (full->half):', stats.basisFixed);
console.log('pre-coverage rows already half:', stats.keptPre);
console.log('rows left as-is (no formula match):', stats.unexplained);
console.log('_yrs corrected:', stats.yrsFixed);
console.log('\nSpot checks:');
['Michael Thomas', 'David Johnson', 'Brandin Cooks'].forEach(n => {
  const h = HP.find(x => x.n === n);
  if (h) console.log(' ', n, h._yrs, JSON.stringify(Object.fromEntries(Object.entries(h._bestByTeam).map(([t, r]) => [t, { yr: r.yr, fpts: r.fpts, rc: r.rc }]))));
});
console.log('\nBiggest rebuild changes (yr changed or >20 pts):', bigChanges.length);
bigChanges.slice(0, 40).forEach(c => console.log('  ', c));
if (unexplainedExamples.length) {
  console.log('\nUnexplained rows with rec>=10 (worth eyeballing):');
  unexplainedExamples.forEach(c => console.log('  ', c));
}

if (WRITE) {
  fs.writeFileSync(path.join(BASE, 'hp.js'), 'const HP = ' + JSON.stringify(HP) + ';\n');
  console.log('\nWrote data/hp.js');
} else {
  console.log('\nDry run — re-run with --write to save.');
}
