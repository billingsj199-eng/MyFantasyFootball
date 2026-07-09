// Rookie sigma% by NFL draft round (from sigma_data.json + COMBINE_DATA join)
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const DATA_DIR = '/sessions/charming-determined-goldberg/mnt/MyFantasyFootball Files/data';

function loadIndependent(filename, varName) {
  const text = fs.readFileSync(path.join(DATA_DIR, filename), 'utf8');
  const sandbox = {};
  const ctx = vm.createContext(sandbox);
  const munged = text.replace(new RegExp('(?:const|var|let)\\s+' + varName + '\\s*='), varName + ' =');
  vm.runInContext(munged + '; this.__OUT__ = ' + varName + ';', ctx);
  return sandbox.__OUT__;
}
const COMBINE = loadIndependent('combine_data.js', 'COMBINE_DATA');
const sigmaData = JSON.parse(fs.readFileSync('/sessions/charming-determined-goldberg/mnt/outputs/sigma_data.json', 'utf8'));
const rookies = sigmaData.filter(r => r.expYear === 1);
console.error('Rookie player-seasons in sample: ' + rookies.length);
let withDraft = 0;
rookies.forEach(r => {
  const cd = COMBINE[r.name];
  if (cd && cd.draft != null && !isNaN(cd.draft)) { r.draftPick = cd.draft; withDraft++; }
});
console.error('  with draft pick from COMBINE_DATA: ' + withDraft);

function median(arr) {
  if (!arr.length) return null;
  const s = arr.slice().sort((a,b)=>a-b);
  const m = Math.floor(s.length/2);
  return s.length % 2 ? s[m] : (s[m-1]+s[m])/2;
}

const ROUNDS = [
  [1, 32, 'R1'],
  [33, 64, 'R2'],
  [65, 105, 'R3'],
  [106, 150, 'R4-5'],
  [151, 260, 'R6-7'],
  [261, 9999, 'UDFA-est'],
];

console.log('');
console.log('Rookie sigma% by NFL draft round (joined to COMBINE_DATA)');
console.log('');
console.log('POS  ROUND     N    MEAN_PPG  SIGMA_PCT(mean)  SIGMA_PCT(median)');
console.log('---  --------  ---  --------  ---------------  -----------------');
['QB','RB','WR','TE'].forEach(pos => {
  ROUNDS.forEach(r => {
    const rows = rookies.filter(x => x.pos === pos && x.draftPick != null && x.draftPick >= r[0] && x.draftPick <= r[1]);
    if (!rows.length) {
      console.log(pos.padEnd(3) + '  ' + r[2].padEnd(8) + '  ' + '0'.padStart(3) + '  (no data)');
      return;
    }
    const meanPpg = rows.reduce((s,x)=>s+x.mean,0)/rows.length;
    const pctVals = rows.filter(x=>x.sigmaPct!=null).map(x=>x.sigmaPct);
    const pctMean = pctVals.reduce((s,v)=>s+v,0)/pctVals.length;
    const pctMed = median(pctVals);
    console.log(
      pos.padEnd(3) + '  ' + r[2].padEnd(8) + '  ' +
      String(rows.length).padStart(3) + '  ' +
      meanPpg.toFixed(2).padStart(8) + '  ' +
      (pctMean*100).toFixed(1).padStart(11) + '%    ' +
      (pctMed*100).toFixed(1).padStart(13) + '%'
    );
  });
  console.log('');
});

// Also: same-PPG-tier comparison: do rookies of each tier differ from vets?
console.log('');
console.log('Same-PPG-tier sigma% — rookies vs experienced players');
console.log('(holds role constant; isolates pure experience effect)');
console.log('');
console.log('POS  TIER         ROOKIE_N  ROOKIE_PCT  VET_N  VET_PCT  ROOKIE-VET');
console.log('---  -----------  --------  ----------  -----  -------  ----------');
const TIERS = {
  RB: [[14, 99, 'Workhorse'], [10, 14, 'Lead'], [6, 10, 'Committee'], [0, 6, 'Depth']],
  WR: [[13, 99, 'Alpha'], [9, 13, 'Starter'], [5, 9, 'Rotation'], [0, 5, 'Depth']],
  TE: [[10, 99, 'Top'], [6, 10, 'Starter'], [0, 6, 'Depth']],
  QB: [[17, 99, 'Top'], [13, 17, 'Starter'], [0, 13, 'Depth']],
};
['QB','RB','WR','TE'].forEach(pos => {
  TIERS[pos].forEach(t => {
    const rookieRows = sigmaData.filter(r => r.pos === pos && r.expYear === 1 && r.mean >= t[0] && r.mean < t[1]);
    const vetRows    = sigmaData.filter(r => r.pos === pos && r.expYear >= 4 && r.mean >= t[0] && r.mean < t[1]);
    const rookiePct = rookieRows.length ? rookieRows.reduce((s,x)=>s+x.sigmaPct,0)/rookieRows.length : null;
    const vetPct    = vetRows.length    ? vetRows.reduce((s,x)=>s+x.sigmaPct,0)/vetRows.length    : null;
    const delta     = (rookiePct != null && vetPct != null) ? (rookiePct - vetPct) * 100 : null;
    console.log(
      pos.padEnd(3) + '  ' + t[2].padEnd(11) + '  ' +
      String(rookieRows.length).padStart(8) + '  ' +
      (rookiePct != null ? (rookiePct*100).toFixed(1).padStart(8) + '%' : '     -') + '  ' +
      String(vetRows.length).padStart(5) + '  ' +
      (vetPct != null ? (vetPct*100).toFixed(1).padStart(5) + '%' : '   -') + '  ' +
      (delta != null ? (delta >= 0 ? '+' : '') + delta.toFixed(1) + 'pp' : '   -')
    );
  });
  console.log('');
});
