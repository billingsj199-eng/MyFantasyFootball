// Preview VOR from Clay 2026 projections to sanity-check the cutoffs.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const DATA_DIR = '/sessions/charming-determined-goldberg/mnt/MyFantasyFootball Files/data';

function loadVar(filename, varName) {
  const text = fs.readFileSync(path.join(DATA_DIR, filename), 'utf8');
  const sandbox = {};
  const ctx = vm.createContext(sandbox);
  const munged = text.replace(new RegExp('(?:const|var|let)\\s+' + varName + '\\s*='), varName + ' =');
  vm.runInContext(munged + '; this.__OUT__ = ' + varName + ';', ctx);
  return sandbox.__OUT__;
}

const CLAY = loadVar('mike_clay_projections.js', 'MIKE_CLAY_PROJ');
console.error('Loaded ' + Object.keys(CLAY).length + ' Clay projections');

const REPL = { QB: 12, RB: 30, WR: 42, TE: 13 };
const byPos = { QB: [], RB: [], WR: [], TE: [] };
Object.keys(CLAY).forEach(name => {
  const cp = CLAY[name];
  if (!cp || !cp.pos || !byPos[cp.pos]) return;
  if (cp.pts == null) return;
  byPos[cp.pos].push({ name, tm: cp.tm, gm: cp.gm, pts: cp.pts });
});

console.log('');
console.log('REPLACEMENT LEVELS (BBM 12-team)');
console.log('');
['QB','RB','WR','TE'].forEach(pos => {
  byPos[pos].sort((a, b) => b.pts - a.pts);
  const replIdx = REPL[pos] - 1;
  const repl = byPos[pos][replIdx];
  console.log(`${pos}: replacement = ${pos}${REPL[pos]} = ${repl.name} (${repl.tm}) at ${repl.pts} pts over ${repl.gm} games`);
});

console.log('');
console.log('TOP 5 VOR PER POSITION');
['QB','RB','WR','TE'].forEach(pos => {
  const replPts = byPos[pos][REPL[pos] - 1].pts;
  console.log('');
  console.log(`${pos}  (replacement: ${replPts} pts)`);
  console.log('RANK  PLAYER                          TM   GP   PTS    VOR');
  byPos[pos].slice(0, 5).forEach((p, i) => {
    const vor = p.pts - replPts;
    console.log(
      String(i + 1).padStart(4) + '  ' +
      p.name.padEnd(30).slice(0, 30) + '  ' +
      (p.tm || '').padEnd(3) + '  ' +
      String(p.gm).padStart(2) + '  ' +
      String(p.pts).padStart(3) + '  ' +
      (vor > 0 ? '+' : '') + Math.round(vor)
    );
  });
});

// Also show notable injured/limited-GP players to verify the active-week
// approach gives them correct VOR (not inflated by phantom games).
console.log('');
console.log('LIMITED-GP PLAYERS (Clay gm < 17 — VOR uses ACTUAL projected total)');
console.log('PLAYER                          POS  TM   GP   PTS    VOR');
const limited = [];
['QB','RB','WR','TE'].forEach(pos => {
  byPos[pos].forEach(p => {
    if (p.gm < 17) limited.push({ ...p, pos });
  });
});
limited.sort((a, b) => b.pts - a.pts);
limited.slice(0, 12).forEach(p => {
  const replPts = byPos[p.pos][REPL[p.pos] - 1].pts;
  const vor = p.pts - replPts;
  console.log(
    p.name.padEnd(30).slice(0, 30) + '  ' +
    p.pos + '   ' +
    (p.tm || '').padEnd(3) + '  ' +
    String(p.gm).padStart(2) + '  ' +
    String(p.pts).padStart(3) + '  ' +
    (vor > 0 ? '+' : '') + Math.round(vor)
  );
});
