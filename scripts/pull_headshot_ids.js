#!/usr/bin/env node
/* pull_headshot_ids.js — bake the HeadshotFix roster lookups into a data file.
 *
 * The runtime HeadshotFix in app.js re-verifies every espncdn _slImg in D
 * against 32 live ESPN team rosters ON EVERY SESSION (sessionStorage cache
 * only) — 32 API calls per visit resolving the same names. This script runs
 * the identical lookup offline and emits data/headshot_espn_ids.js:
 *
 *   window.BAKED_ESPN_IDS    = { "Player Name": "espnId", ... }
 *   window.BAKED_ESPN_MISSES = [ "Name", ... ]   // roster lookup found nothing
 *
 * app.js seeds its caches from these, so a normal boot makes ZERO roster
 * calls. Players added to d.js after the last bake still fall through to the
 * live roster fetch, so re-running this is an optimization, not a correctness
 * requirement. Re-run after big roster churn (draft, cut-downs, trades):
 *
 *   node scripts/pull_headshot_ids.js
 *
 * then bump the ?v= on data/headshot_espn_ids.js in index.html.
 * Matching logic mirrors app.js matchAndApply(): exact normalized name →
 * suffix-stripped → same first + last word. FALLBACK_IDS wins on exact names
 * (mirrors the runtime override loop).
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..');

function loadGlobal(file, sandboxExtra) {
  const ctx = vm.createContext(Object.assign({ window: {}, console }, sandboxExtra || {}));
  vm.runInContext(fs.readFileSync(path.join(ROOT, file), 'utf8'), ctx, { filename: file });
  return ctx;
}

const dCtx = loadGlobal('data/d.js');
const D = dCtx.D || dCtx.window.D;
if (!D || !D.length) { console.error('Could not load D from data/d.js'); process.exit(1); }

const fbCtx = loadGlobal('data/fallback_espn_ids.js');
const FALLBACK_IDS = fbCtx.FALLBACK_IDS || fbCtx.window.FALLBACK_IDS || {};

const normName = (n) => n.replace(/['‘’]/g, "'").replace(/\s+/g, ' ').trim();

// Same target set as app.js playersToFix (retired-with-known-id exclusion is
// skipped — extra entries are harmless cache seeds).
const targets = D.filter((p) => ((p._slImg && p._slImg.includes('espncdn.com')) || (p.s === 'K' && !p._slImg)) && p.n && !p.n.includes('D/ST'));
console.log('Players with espncdn headshots in D: ' + targets.length);

const TEAM_IDS = [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,33,34];
const nameToId = {};
for (const [k, v] of Object.entries(FALLBACK_IDS)) nameToId[normName(k)] = String(v);

function parseRoster(data) {
  if (!data) return;
  if (data.athletes && Array.isArray(data.athletes)) {
    data.athletes.forEach((group) => {
      const items = group.items || group.athletes || [];
      items.forEach((player) => {
        if (player.id && (player.displayName || player.fullName)) {
          const name = player.displayName || player.fullName;
          nameToId[normName(name)] = String(player.id);
          if (player.fullName && player.fullName !== name) nameToId[normName(player.fullName)] = String(player.id);
        }
      });
    });
  }
  if (data.items && Array.isArray(data.items)) {
    data.items.forEach((player) => {
      if (player.id && (player.displayName || player.fullName)) {
        nameToId[normName(player.displayName || player.fullName)] = String(player.id);
      }
    });
  }
}

async function main() {
  for (let i = 0; i < TEAM_IDS.length; i += 8) {
    await Promise.all(TEAM_IDS.slice(i, i + 8).map(async (tid) => {
      try {
        const r = await fetch('https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/' + tid + '/roster');
        if (r.ok) parseRoster(await r.json());
      } catch (e) {
        console.error('Team ' + tid + ' fetch failed: ' + e.message);
      }
    }));
    console.log('Fetched ' + Math.min(i + 8, TEAM_IDS.length) + '/' + TEAM_IDS.length + ' rosters, ' + Object.keys(nameToId).length + ' names');
  }

  const resolved = {};
  const misses = [];
  for (const p of targets) {
    const nn = normName(p.n);
    let id = FALLBACK_IDS[p.n] ? String(FALLBACK_IDS[p.n]) : nameToId[nn];
    if (!id) id = nameToId[nn.replace(/ Jr\.?$| Sr\.?$| III$| II$| IV$| V$/i, '').trim()];
    if (!id) {
      const parts = nn.split(' ');
      if (parts.length >= 2) {
        const first = parts[0].toLowerCase();
        const last = parts[parts.length - 1].toLowerCase();
        for (const [k, v] of Object.entries(nameToId)) {
          const kp = k.toLowerCase().split(' ');
          if (kp.length >= 2 && kp[kp.length - 1] === last && kp[0] === first) { id = v; break; }
        }
      }
    }
    if (id) resolved[p.n] = id; else misses.push(p.n);
  }

  const stamp = new Date().toISOString().slice(0, 10);
  const out = '/* Generated ' + stamp + ' by scripts/pull_headshot_ids.js — baked ESPN roster\n' +
    '   lookups so app.js HeadshotFix boots without fetching 32 rosters.\n' +
    '   Regenerate: node scripts/pull_headshot_ids.js (then bump ?v= in index.html). */\n' +
    'window.BAKED_ESPN_IDS = ' + JSON.stringify(resolved) + ';\n' +
    'window.BAKED_ESPN_MISSES = ' + JSON.stringify(misses) + ';\n';
  fs.writeFileSync(path.join(ROOT, 'data', 'headshot_espn_ids.js'), out);
  console.log('Resolved ' + Object.keys(resolved).length + '/' + targets.length + ' (misses: ' + misses.length + ') -> data/headshot_espn_ids.js');
  if (misses.length) console.log('Misses: ' + misses.join(', '));
}

main();
