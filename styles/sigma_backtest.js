// Backtest the new rookie sigma% lookup against 2024 rookie actuals.
// Predicts sigma% from the lookup table using each player's ACTUAL
// 2024 mean PPG as the role-tier signal (best-case predictor since
// preseason Clay would be noisier), then compares to observed sigma%.
const fs = require('fs');
const data = JSON.parse(fs.readFileSync('/sessions/charming-determined-goldberg/mnt/outputs/sigma_data.json', 'utf8'));

// New empirical lookup (matches the table in index.html v0.9.64).
const ROOKIE_TIERS = {
  RB: [[14, 0.50], [10, 0.62], [6, 0.80], [0, 0.91]],
  WR: [[13, 0.56], [9,  0.66], [5, 0.80], [0, 0.99]],
  TE: [[10, 0.53], [6,  0.70],            [0, 0.91]],
  QB: [[17, 0.41], [13, 0.47],            [0, 0.65]],
};

// Old heuristic for comparison
const OLD_BASE = { QB: 0.30, RB: 0.50, WR: 0.55, TE: 0.60 };
function oldSigmaPct(pos, mean) {
  let scale = 1.0;
  if (pos === 'RB') {
    if (mean >= 14) scale = 0.85;
    else if (mean >= 10) scale = 0.95;
    else if (mean >= 6) scale = 1.05;
    else scale = 1.20;
  } else if (pos === 'WR') {
    if (mean >= 13) scale = 0.85;
    else if (mean >= 9) scale = 0.95;
    else if (mean >= 5) scale = 1.05;
    else scale = 1.20;
  } else if (pos === 'TE') {
    if (mean >= 10) scale = 0.85;
    else if (mean >= 6) scale = 0.95;
    else scale = 1.10;
  } else if (pos === 'QB') {
    if (mean >= 17) scale = 0.85;
    else if (mean >= 13) scale = 0.95;
    else scale = 1.10;
  }
  return (OLD_BASE[pos] || 0.5) * scale;
}
function newSigmaPct(pos, mean) {
  const tiers = ROOKIE_TIERS[pos];
  if (!tiers) return OLD_BASE[pos] || 0.5;
  for (const [thresh, pct] of tiers) if (mean >= thresh) return pct;
  return tiers[tiers.length - 1][1];
}

// Holdout: use rookie seasons from a chosen year as test set; the lookup
// was calibrated on ALL years so this is in-sample for any single year.
// To get a true out-of-sample read, leave-one-year-out: for each year,
// recalibrate from the OTHER years and predict the held-out year.
function leaveOneYearOut(testYr) {
  const train = data.filter(r => r.expYear === 1 && r.season !== testYr);
  // Build the per-(pos,tier) mean from train data
  const newTbl = {};
  ['QB','RB','WR','TE'].forEach(pos => {
    newTbl[pos] = ROOKIE_TIERS[pos].map(([thresh, _]) => [thresh, []]);
  });
  train.forEach(r => {
    const tiers = newTbl[r.pos];
    if (!tiers) return;
    for (let i = 0; i < tiers.length; i++) {
      const next = i + 1 < tiers.length ? tiers[i+1][0] : -1;
      if (r.mean >= tiers[i][0] && (next < 0 || r.mean < tiers[i][0] && false)) { } // structural check
      if (r.mean >= tiers[i][0]) { tiers[i][1].push(r.sigmaPct); break; }
    }
  });
  // Convert to mean-σ% lookup
  const tbl = {};
  Object.keys(newTbl).forEach(pos => {
    tbl[pos] = newTbl[pos].map(([t, arr]) => [t, arr.length ? arr.reduce((s,v)=>s+v,0)/arr.length : null]);
  });
  return tbl;
}

function tierLookup(tbl, pos, mean) {
  const tiers = tbl[pos];
  if (!tiers) return null;
  for (const [thresh, pct] of tiers) if (mean >= thresh && pct != null) return pct;
  return null;
}

function rmse(arr) {
  if (!arr.length) return null;
  const ss = arr.reduce((s, e) => s + e * e, 0);
  return Math.sqrt(ss / arr.length);
}
function mae(arr) {
  if (!arr.length) return null;
  return arr.reduce((s, e) => s + Math.abs(e), 0) / arr.length;
}

// Run leave-one-year-out for years with reasonable rookie sample
const rookies = data.filter(r => r.expYear === 1);
const yearsByCount = {};
rookies.forEach(r => yearsByCount[r.season] = (yearsByCount[r.season] || 0) + 1);
const targetYears = Object.entries(yearsByCount)
  .filter(([_, c]) => c >= 30)
  .map(([y]) => parseInt(y))
  .sort();

console.log('');
console.log('Leave-one-year-out backtest of rookie sigma% lookup');
console.log('(predicted sigma% is the mean of all OTHER years\' rookies in that pos+tier)');
console.log('');
console.log('YEAR  POS  N    MEAN_PPG  ACTUAL_SIG  PRED(NEW)  ERR_NEW  PRED(OLD)  ERR_OLD');
console.log('----  ---  ---  --------  ----------  ---------  -------  ---------  -------');

const allErrsNew = { QB:[], RB:[], WR:[], TE:[] };
const allErrsOld = { QB:[], RB:[], WR:[], TE:[] };
targetYears.forEach(yr => {
  const tbl = leaveOneYearOut(yr);
  ['QB','RB','WR','TE'].forEach(pos => {
    const test = rookies.filter(r => r.season === yr && r.pos === pos);
    if (!test.length) return;
    const errsNew = [];
    const errsOld = [];
    let predSumNew = 0, predSumOld = 0, actSum = 0, meanSum = 0;
    test.forEach(r => {
      const predNew = tierLookup(tbl, pos, r.mean);
      const predOld = oldSigmaPct(pos, r.mean);
      const actual = r.sigmaPct;
      if (predNew == null || actual == null) return;
      errsNew.push(predNew - actual);
      errsOld.push(predOld - actual);
      predSumNew += predNew;
      predSumOld += predOld;
      actSum += actual;
      meanSum += r.mean;
      allErrsNew[pos].push(predNew - actual);
      allErrsOld[pos].push(predOld - actual);
    });
    if (errsNew.length === 0) return;
    const n = errsNew.length;
    console.log(
      String(yr).padEnd(4) + '  ' + pos.padEnd(3) + '  ' +
      String(n).padStart(3) + '  ' +
      (meanSum/n).toFixed(2).padStart(8) + '  ' +
      (actSum/n*100).toFixed(1).padStart(8) + '%  ' +
      (predSumNew/n*100).toFixed(1).padStart(7) + '%  ' +
      (rmse(errsNew)*100).toFixed(1).padStart(5) + 'pp  ' +
      (predSumOld/n*100).toFixed(1).padStart(7) + '%  ' +
      (rmse(errsOld)*100).toFixed(1).padStart(5) + 'pp'
    );
  });
});

console.log('');
console.log('OVERALL RMSE (leave-one-year-out, all years pooled)');
console.log('');
console.log('POS  N    RMSE_NEW  RMSE_OLD  IMPROVEMENT  MAE_NEW  MAE_OLD');
console.log('---  ---  --------  --------  -----------  -------  -------');
['QB','RB','WR','TE'].forEach(pos => {
  const nE = allErrsNew[pos];
  const oE = allErrsOld[pos];
  if (!nE.length) return;
  const rN = rmse(nE), rO = rmse(oE);
  const mN = mae(nE), mO = mae(oE);
  console.log(
    pos.padEnd(3) + '  ' + String(nE.length).padStart(3) + '  ' +
    (rN*100).toFixed(1).padStart(6) + 'pp  ' +
    (rO*100).toFixed(1).padStart(6) + 'pp  ' +
    ((rO - rN)/rO*100).toFixed(1).padStart(9) + '%   ' +
    (mN*100).toFixed(1).padStart(5) + 'pp  ' +
    (mO*100).toFixed(1).padStart(5) + 'pp'
  );
});

// Calibration plot data: predicted vs actual buckets
console.log('');
console.log('Calibration: actual sigma% by predicted bucket (all positions, leave-one-year-out)');
console.log('');
console.log('PRED_BUCKET    N    PRED_MEAN  ACTUAL_MEAN  DIFF');
console.log('-------------  ---  ---------  -----------  -----');
const bucketRows = { '40-50%':[], '50-60%':[], '60-70%':[], '70-80%':[], '80-90%':[], '90%+':[] };
targetYears.forEach(yr => {
  const tbl = leaveOneYearOut(yr);
  rookies.filter(r => r.season === yr).forEach(r => {
    const p = tierLookup(tbl, r.pos, r.mean);
    if (p == null) return;
    let bucket;
    if (p < 0.50) bucket = '40-50%';
    else if (p < 0.60) bucket = '50-60%';
    else if (p < 0.70) bucket = '60-70%';
    else if (p < 0.80) bucket = '70-80%';
    else if (p < 0.90) bucket = '80-90%';
    else bucket = '90%+';
    bucketRows[bucket].push({ pred: p, actual: r.sigmaPct });
  });
});
Object.entries(bucketRows).forEach(([b, rows]) => {
  if (!rows.length) return;
  const pm = rows.reduce((s,x)=>s+x.pred,0)/rows.length;
  const am = rows.reduce((s,x)=>s+x.actual,0)/rows.length;
  console.log(
    b.padEnd(13) + '  ' +
    String(rows.length).padStart(3) + '  ' +
    (pm*100).toFixed(1).padStart(7) + '%  ' +
    (am*100).toFixed(1).padStart(9) + '%  ' +
    ((am-pm)*100>=0?'+':'') + ((am-pm)*100).toFixed(1).padStart(4) + 'pp'
  );
});
