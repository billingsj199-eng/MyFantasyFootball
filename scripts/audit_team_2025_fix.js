#!/usr/bin/env node
/* Audit + fix the _2025_TEAM_FIX override map (player -> 2025 team).
 *
 * The map lives in data/team_2025_fix.js (SOURCE — bundle_lookups.py folds it
 * into data/_bundle_lookups.js, the copy the site actually loads) and wins
 * over ACTIVE_TEAM_HISTORY / PLAYER_TEAM_HISTORY / WEEKLY_STATS per-game tm
 * in _getTeamForPlayerYear, so a stale entry silently corrupts Compare-page
 * teammate splits and every team-by-year lookup.
 *
 * Ground truth, derived fresh each run:
 *   - WEEKLY_STATS_ACTIVE 2025 season: majority non-blank per-game tm
 *   - PLAYER_TEAM_HISTORY: span with y1 <= 2025 <= y2
 * A correction is proposed only when at least one source disagrees with the
 * map AND every available source agrees on the same replacement. Defensive/OL
 * entries have no WEEKLY_STATS row, so PLAYER_TEAM_HISTORY alone decides for
 * them; players with neither source (missed 2025) are reported and left.
 *
 * Usage:
 *   node scripts/audit_team_2025_fix.js            # dry-run report
 *   node scripts/audit_team_2025_fix.js --write    # rewrite team_2025_fix.js
 *                                                  # (then regen the bundle!)
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..');
const FIX_PATH = path.join(ROOT, 'data', 'team_2025_fix.js');
const BUNDLE_PATH = path.join(ROOT, 'data', '_bundle_lookups.js');
const PTH_PATH = path.join(ROOT, 'data', 'player_team_history.js');
const WEEKLY_PATH = path.join(ROOT, 'data', 'weekly_stats_active.js');

const norm = n => n.toLowerCase().replace(/[.'`-]/g, '')
  .replace(/\s+(jr|sr|ii|iii|iv|v)$/, '').replace(/\s+/g, ' ').trim();

function extractMap(src, label) {
  const m = src.match(/_2025_TEAM_FIX\s*=\s*\{[\s\S]*?\};/);
  if (!m) throw new Error(`_2025_TEAM_FIX literal not found in ${label}`);
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext('var ' + m[0], sandbox);
  return sandbox._2025_TEAM_FIX;
}

function loadPTH() {
  const sandbox = {};
  vm.createContext(sandbox);
  // const-declared in the file, so it never lands on the sandbox — take it as
  // the script's completion value instead.
  const PTH = vm.runInContext(
    fs.readFileSync(PTH_PATH, 'utf8') + ';PLAYER_TEAM_HISTORY', sandbox);
  const byNorm = {};
  for (const [name, spans] of Object.entries(PTH)) {
    byNorm[norm(name)] = spans;
  }
  return byNorm;
}

function loadWeekly2025() {
  let src = fs.readFileSync(WEEKLY_PATH, 'utf8');
  src = src.slice(src.indexOf('=') + 1).trim().replace(/;\s*$/, '');
  const obj = JSON.parse(src);
  const byNorm = {};
  for (const [name, rec] of Object.entries(obj)) {
    const games = (rec.seasons || {})['2025'] || [];
    const counts = {};
    for (const g of games) if (g.tm) counts[g.tm] = (counts[g.tm] || 0) + 1;
    const best = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
    if (best) byNorm[norm(name)] = best[0];
  }
  return byNorm;
}

function main() {
  const write = process.argv.includes('--write');
  const fixSrc = fs.readFileSync(FIX_PATH, 'utf8');
  const map = extractMap(fixSrc, 'team_2025_fix.js');
  const bundleMap = extractMap(fs.readFileSync(BUNDLE_PATH, 'utf8'), '_bundle_lookups.js');

  const syncDiffs = Object.keys({ ...map, ...bundleMap })
    .filter(k => map[k] !== bundleMap[k]);
  console.log(`  entries: ${Object.keys(map).length} (source) / ${Object.keys(bundleMap).length} (bundle)`
    + (syncDiffs.length ? `  !! OUT OF SYNC: ${syncDiffs.join(', ')}` : '  [in sync]'));

  const pth = loadPTH();
  const weekly = loadWeekly2025();

  const changes = [], clean = [], unverifiable = [], conflicts = [];
  for (const [name, cur] of Object.entries(map)) {
    const k = norm(name);
    const w = weekly[k] || null;
    const spans = pth[k] || [];
    const span = spans.find(s => s.y1 <= 2025 && 2025 <= s.y2);
    const p = span ? span.t : null;
    if (!w && !p) { unverifiable.push(`${name} (${cur}) — no 2025 data in either source`); continue; }
    if (w && p && w !== p) { conflicts.push(`${name}: weekly=${w} pth=${p} map=${cur}`); continue; }
    const truth = w || p;
    if (truth === cur) { clean.push(name); continue; }
    changes.push({ name, old: cur, new: truth,
      via: w && p ? 'weekly+pth' : (w ? 'weekly' : 'pth') });
  }

  console.log(`  clean: ${clean.length}   stale: ${changes.length}   `
    + `conflicting sources: ${conflicts.length}   unverifiable: ${unverifiable.length}\n`);
  for (const c of changes)
    console.log(`    ${c.name.padEnd(24)} ${c.old.padEnd(4)} -> ${c.new.padEnd(4)} [${c.via}]`);
  for (const c of conflicts) console.log(`    CONFLICT (untouched): ${c}`);
  for (const u of unverifiable) console.log(`    UNVERIFIABLE (untouched): ${u}`);

  if (!changes.length) { console.log('  nothing to fix'); return; }
  if (!write) { console.log('\n  dry-run — rerun with --write, then regen the bundle:\n'
    + '    python scripts/bundle_lookups.py'); return; }

  let out = fixSrc;
  for (const c of changes) {
    // keys are single-quoted with \' escapes; value is the 2-4 char abbr
    const keyLit = `'${c.name.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`;
    const oldPair = `${keyLit}:'${c.old}'`;
    const newPair = `${keyLit}:'${c.new}'`;
    const n = out.split(oldPair).length - 1;
    if (n !== 1) throw new Error(`expected exactly one ${oldPair}, found ${n}`);
    out = out.replace(oldPair, newPair);
  }
  const verify = extractMap(out, 'rewritten source');
  for (const c of changes)
    if (verify[c.name] !== c.new) throw new Error(`verify failed for ${c.name}`);
  fs.writeFileSync(FIX_PATH, out);
  console.log(`\n  wrote ${changes.length} fixes to team_2025_fix.js (verified). `
    + 'Now regen the bundle: python scripts/bundle_lookups.py');
}

main();
