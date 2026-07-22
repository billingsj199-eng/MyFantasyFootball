// Normalize + repair data/player_team_history.js against all_players.js career truth.
//
// Two bug families (found 2026-07-22 chasing the David Johnson / Michael Thomas
// Fantasy Game scores):
//  1. DIALECT ABBRS: many entries use PFR-style codes (HST, BLT, ARZ, CLV, SD,
//     OAK, STL, LA...). The Fantasy Game's abbr resolver only knows
//     TEAM_ABBR_MAP's standard codes and FAILS CLOSED on unknown ones — every
//     season in an unresolvable range gets excluded from that team's best-season
//     pick (the exact DJ failure mode). Fix: rewrite all codes to standard.
//  2. WRONG HISTORIES: name collisions and stale/garbled ranges (Chris Johnson
//     mapped to LV during his 2009 TEN 2,006-yd year; Roy Williams holds the
//     safety's DAL years; Latavius Murray's NO years credited to MIN...).
//     Fix: for entries that still disagree with all_players career[].tm after
//     dialect normalization, rebuild the ranges from the career rows themselves.
//     Pre-1999 ranges (before all_players coverage) are preserved as-is.
//
// Run: node scripts/fix_player_team_history.js          (report only)
//      node scripts/fix_player_team_history.js --write  (rewrite the file)

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

const ALL = loadJS('all_players.js', 'ALL_PLAYERS_DB');
const FILE = path.join(BASE, 'player_team_history.js');
const src = fs.readFileSync(FILE, 'utf8');

// dialect/legacy code -> standard code (what TEAM_ABBR_MAP + the FG resolve)
const DIALECT = {
  ARZ: 'ARI', CRD: 'ARI', BLT: 'BAL', RAV: 'BAL', CLV: 'CLE', HST: 'HOU',
  HOI: 'HOU', JAC: 'JAX', WSH: 'WAS', OAK: 'LV', RAI: 'LV', SD: 'LAC',
  SDG: 'LAC', STL: 'LAR', LA: 'LAR', RAM: 'LAR', SL: 'LAR'
};
const norm = t => DIALECT[t] || t;

const byName = {};
ALL.forEach(p => { (byName[p.name] = byName[p.name] || []).push(p); });
function candidate(name) {
  const c = byName[name];
  if (!c) return null;
  const score = p => (p.career || []).reduce((t, r) => t + (r.fpts || 0), 0);
  return c.slice().sort((a, b) => score(b) - score(a))[0];
}

// Build ranges from career rows (>= coverage start), gap years inherit the
// previous team so lookups stay contiguous like the existing entries.
function rebuiltRanges(p) {
  const rows = (p.career || []).filter(s => s.tm).sort((a, b) => a.yr - b.yr);
  if (!rows.length) return null;
  const ranges = [];
  rows.forEach(s => {
    const t = norm(s.tm);
    const last = ranges[ranges.length - 1];
    if (last && last.t === t) last.y2 = Math.max(last.y2, s.yr);
    else if (last && last.y2 >= s.yr) { /* two teams same yr: keep first */ }
    else {
      if (last) last.y2 = s.yr - 1; // extend through gap
      ranges.push({ t, y1: s.yr, y2: s.yr });
    }
  });
  return ranges;
}

function entryMatchesCareer(ranges, p) {
  let bad = 0;
  (p.career || []).forEach(s => {
    if (!s.tm) return;
    const h = ranges.find(h => s.yr >= h.y1 && s.yr <= h.y2);
    if (h && norm(h.t) !== norm(s.tm)) bad++;
  });
  return bad === 0;
}

const fmt = ranges => '[' + ranges.map(r => `{t:'${r.t}',y1:${r.y1},y2:${r.y2}}`).join(',') + ']';

const lines = src.split('\n');
let normalized = 0, rebuilt = 0, unmatchedKept = 0;
const rebuiltNames = [];

const out = lines.map(line => {
  const m = line.match(/^(\s*)'((?:[^'\\]|\\.)*)'\s*:\s*(\[.*\]),(\s*)$/);
  if (!m) return line;
  const [, indent, name, arrSrc] = m;
  let ranges;
  try { ranges = new Function('return ' + arrSrc)(); } catch (e) { return line; }

  const before = JSON.stringify(ranges);
  ranges = ranges.map(r => ({ t: norm(r.t), y1: r.y1, y2: r.y2 }));
  const didNorm = JSON.stringify(ranges) !== before;

  const p = candidate(name.replace(/\\'/g, "'"));
  if (p) {
    if (!entryMatchesCareer(ranges, p)) {
      const nr = rebuiltRanges(p);
      if (nr) {
        const covMin = nr[0].y1;
        const covMax = nr[nr.length - 1].y2;
        // preserve pre-coverage history (e.g. a legend's pre-1999 teams)
        const pre = ranges.filter(r => r.y2 < covMin);
        const preStraddle = ranges.find(r => r.y1 < covMin && r.y2 >= covMin);
        if (preStraddle) pre.push({ t: preStraddle.t, y1: preStraddle.y1, y2: covMin - 1 });
        // preserve post-coverage history (name-collision entries whose other
        // player's years lie beyond this career, or fictional-timeline moves
        // all_players doesn't carry yet)
        const post = ranges.filter(r => r.y1 > covMax);
        // a straddling tail ending in the open-ended 2099 sentinel is not a
        // real future claim — drop it and let active-detection re-add 2099
        const postStraddle = ranges.find(r => r.y1 <= covMax && r.y2 > covMax && r.y2 < 2099);
        if (postStraddle) post.unshift({ t: postStraddle.t, y1: covMax + 1, y2: postStraddle.y2 });
        let merged = pre.concat(nr, post);
        // active players keep the open-ended sentinel like the rest of the file
        const active = (p.last || covMax) >= 2025;
        if (active) merged[merged.length - 1].y2 = Math.max(merged[merged.length - 1].y2, 2099);
        // merge adjacent same-team ranges
        merged = merged.reduce((acc, r) => {
          const last = acc[acc.length - 1];
          if (last && last.t === r.t && r.y1 <= last.y2 + 1) last.y2 = Math.max(last.y2, r.y2);
          else acc.push({ ...r });
          return acc;
        }, []);
        rebuilt++;
        rebuiltNames.push(name + ': ' + arrSrc + ' -> ' + fmt(merged));
        return `${indent}'${name}': ${fmt(merged)},`;
      }
    }
  } else {
    unmatchedKept++;
  }
  if (didNorm) {
    normalized++;
    return `${indent}'${name}': ${fmt(ranges)},`;
  }
  return line;
});

console.log('entries dialect-normalized only:', normalized);
console.log('entries rebuilt from career truth:', rebuilt);
console.log('entries with no all_players match (normalized only):', unmatchedKept);
console.log('\nRebuilt entries:');
rebuiltNames.forEach(n => console.log('  ' + n));

if (WRITE) {
  fs.writeFileSync(FILE, out.join('\n'));
  console.log('\nWrote data/player_team_history.js');
} else {
  console.log('\nDry run — re-run with --write to save.');
}
