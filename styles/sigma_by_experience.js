// Computes weekly fantasy-points sigma by NFL experience year x position.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const DATA_DIR = '/sessions/charming-determined-goldberg/mnt/MyFantasyFootball Files/data';

// Load ALL_PLAYERS_DB first (independent file)
function loadIndependent(filename, varName) {
  const text = fs.readFileSync(path.join(DATA_DIR, filename), 'utf8');
  const sandbox = {};
  const ctx = vm.createContext(sandbox);
  const munged = text.replace(new RegExp('(?:const|var|let)\\s+' + varName + '\\s*='), varName + ' =');
  vm.runInContext(munged + '; this.__OUT__ = ' + varName + ';', ctx);
  return sandbox.__OUT__;
}

console.error('Loading all_players.js...');
const ALL = loadIndependent('all_players.js', 'ALL_PLAYERS_DB');
console.error('  ' + ALL.length + ' players');

const debutByName = new Map();
const positionByName = new Map();
ALL.forEach(p => { if (p.name) { debutByName.set(p.name, p.debut); positionByName.set(p.name, p.pos); } });

// For weekly stats, share a `window` across all four files so the
// Object.assign chain in the retired files lands in the same target.
const sharedSandbox = { window: {}, console };
const sharedCtx = vm.createContext(sharedSandbox);
const WEEKLY_FILES = [
  'weekly_stats_active.js',
  'weekly_stats_retired_1.js',
  'weekly_stats_retired_2.js',
  'weekly_stats_retired_3.js',
];
WEEKLY_FILES.forEach(fname => {
  console.error('Loading ' + fname + '...');
  const text = fs.readFileSync(path.join(DATA_DIR, fname), 'utf8');
  // Strip top-level `const/var/let WEEKLY_STATS_xyz =` so it lands as a
  // plain global on the sandbox (still accessible via this).
  const munged = text.replace(/(?:const|var|let)\s+(WEEKLY_STATS\w*)\s*=/, '$1 =');
  vm.runInContext(munged, sharedCtx);
});
const ACTIVE = sharedSandbox.WEEKLY_STATS_ACTIVE || sharedSandbox.window.WEEKLY_STATS_ACTIVE || {};
const RETIRED = sharedSandbox.window.WEEKLY_STATS_RETIRED || sharedSandbox.WEEKLY_STATS_RETIRED || {};
console.error('  ACTIVE: ' + Object.keys(ACTIVE).length + ' players');
console.error('  RETIRED: ' + Object.keys(RETIRED).length + ' players');

const buckets = {};
function bucketKey(pos, expYear) {
  if (!buckets[pos]) buckets[pos] = {};
  if (!buckets[pos][expYear]) buckets[pos][expYear] = [];
  return buckets[pos][expYear];
}
const MIN_GAMES = 8;
const MIN_MEAN_PPG = { QB: 6, RB: 4, WR: 3.5, TE: 3 };
let totalProcessed = 0, droppedNoDebut = 0, droppedFewGames = 0, droppedLowMean = 0;

function processBag(bag) {
  Object.keys(bag).forEach(name => {
    const player = bag[name];
    if (!player || !player.seasons) return;
    const pos = player.pos || positionByName.get(name);
    if (!pos || !['QB','RB','WR','TE'].includes(pos)) return;
    const debut = debutByName.get(name);
    if (debut == null) { droppedNoDebut++; return; }
    Object.keys(player.seasons).forEach(yrStr => {
      const yr = parseInt(yrStr);
      if (!yr || yr < debut) return;
      const expYear = yr - debut + 1;
      const games = player.seasons[yrStr];
      if (!Array.isArray(games) || games.length < MIN_GAMES) { droppedFewGames++; return; }
      const fpts = games.map(g => Number(g.fpts) || 0);
      const n = fpts.length;
      const mean = fpts.reduce((s, v) => s + v, 0) / n;
      if (mean < MIN_MEAN_PPG[pos]) { droppedLowMean++; return; }
      const variance = fpts.reduce((s, v) => s + (v - mean) * (v - mean), 0) / n;
      const sigma = Math.sqrt(variance);
      const sigmaPct = mean > 0 ? sigma / mean : null;
      bucketKey(pos, expYear).push({ name, season: yr, games: n, mean, sigma, sigmaPct });
      totalProcessed++;
    });
  });
}
processBag(ACTIVE);
processBag(RETIRED);
console.error('Processed: ' + totalProcessed + ' player-seasons');
console.error('  dropped (no debut): ' + droppedNoDebut);
console.error('  dropped (< ' + MIN_GAMES + ' games): ' + droppedFewGames);
console.error('  dropped (low mean PPG): ' + droppedLowMean);

function bucketExp(y) {
  if (y === 1) return '1 (Rookie)';
  if (y === 2) return '2 (Sophomore)';
  if (y === 3) return '3';
  if (y >= 4 && y <= 6) return '4-6';
  return '7+';
}
function median(arr) {
  if (!arr.length) return null;
  const s = arr.slice().sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m-1] + s[m]) / 2;
}

const groups = {};
Object.keys(buckets).forEach(pos => {
  groups[pos] = {};
  Object.keys(buckets[pos]).forEach(yr => {
    const key = bucketExp(parseInt(yr));
    if (!groups[pos][key]) groups[pos][key] = [];
    groups[pos][key].push(...buckets[pos][yr]);
  });
});

const ORDER = ['1 (Rookie)', '2 (Sophomore)', '3', '4-6', '7+'];
console.log('');
console.log('Weekly fantasy-points sigma by NFL experience year x position');
console.log('(player-season level; min ' + MIN_GAMES + ' games, min mean PPG by pos)');
console.log('');
console.log('POS  EXP             N    MEAN_PPG  SIGMA_ABS  SIGMA_PCT(mean)  SIGMA_PCT(median)');
console.log('---  --------------  ---  --------  ---------  ---------------  -----------------');
['QB','RB','WR','TE'].forEach(pos => {
  ORDER.forEach(key => {
    const rows = (groups[pos] && groups[pos][key]) || [];
    if (!rows.length) {
      console.log(pos.padEnd(3) + '  ' + key.padEnd(14) + '  ' + '0'.padStart(3) + '  (no data)');
      return;
    }
    const meanPpg = rows.reduce((s, r) => s + r.mean, 0) / rows.length;
    const sigmaAbs = rows.reduce((s, r) => s + r.sigma, 0) / rows.length;
    const pctVals = rows.filter(r => r.sigmaPct != null).map(r => r.sigmaPct);
    const pctMean = pctVals.reduce((s, v) => s + v, 0) / pctVals.length;
    const pctMed = median(pctVals);
    console.log(
      pos.padEnd(3) + '  ' + key.padEnd(14) + '  ' +
      String(rows.length).padStart(3) + '  ' +
      meanPpg.toFixed(2).padStart(8) + '  ' +
      sigmaAbs.toFixed(2).padStart(9) + '  ' +
      (pctMean*100).toFixed(1).padStart(11) + '%    ' +
      (pctMed*100).toFixed(1).padStart(13) + '%'
    );
  });
  console.log('');
});

console.log('');
console.log('Rookie sigma% by ACTUAL rookie-year mean PPG tier');
console.log('');
console.log('POS  TIER         N    MEAN_PPG  SIGMA_PCT(mean)  SIGMA_PCT(median)');
console.log('---  -----------  ---  --------  ---------------  -----------------');
const TIERS = {
  RB: [[14, 99, 'Workhorse'], [10, 14, 'Lead'], [6, 10, 'Committee'], [0, 6, 'Depth']],
  WR: [[13, 99, 'Alpha'], [9, 13, 'Starter'], [5, 9, 'Rotation'], [0, 5, 'Depth']],
  TE: [[10, 99, 'Top'], [6, 10, 'Starter'], [0, 6, 'Depth']],
  QB: [[17, 99, 'Top'], [13, 17, 'Starter'], [0, 13, 'Depth']],
};
['QB','RB','WR','TE'].forEach(pos => {
  const rookieRows = (buckets[pos] && buckets[pos][1]) || [];
  TIERS[pos].forEach(t => {
    const tierRows = rookieRows.filter(r => r.mean >= t[0] && r.mean < t[1]);
    if (!tierRows.length) {
      console.log(pos.padEnd(3) + '  ' + t[2].padEnd(11) + '  ' + '0'.padStart(3) + '  (no data)');
      return;
    }
    const meanPpg = tierRows.reduce((s, r) => s + r.mean, 0) / tierRows.length;
    const pctVals = tierRows.filter(r => r.sigmaPct != null).map(r => r.sigmaPct);
    const pctMean = pctVals.reduce((s, v) => s + v, 0) / pctVals.length;
    const pctMed = median(pctVals);
    console.log(
      pos.padEnd(3) + '  ' + t[2].padEnd(11) + '  ' +
      String(tierRows.length).padStart(3) + '  ' +
      meanPpg.toFixed(2).padStart(8) + '  ' +
      (pctMean*100).toFixed(1).padStart(11) + '%    ' +
      (pctMed*100).toFixed(1).padStart(13) + '%'
    );
  });
  console.log('');
});

const outPath = '/sessions/charming-determined-goldberg/mnt/outputs/sigma_data.json';
const flat = [];
Object.keys(buckets).forEach(pos => {
  Object.keys(buckets[pos]).forEach(yr => {
    buckets[pos][yr].forEach(r => flat.push(Object.assign({}, r, { pos, expYear: parseInt(yr) })));
  });
});
fs.writeFileSync(outPath, JSON.stringify(flat));
console.error('Wrote ' + flat.length + ' rows to ' + outPath);
