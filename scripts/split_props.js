#!/usr/bin/env node
// Deploy-time "data diet" for data/betting_lines_2026.js (site audit 2026-11-23 #9).
//
// _WEEKLY_PROPS_2026 (weekly player props, one block per week) is ~88% of the file
// (1.28 of 1.45 MB raw, 11-24) and the phone's first rankings rows wait for it. Only
// the active week is read on the first render (weekly board Book PPG, Start/Sit, the
// line-movers box use the newest week); older weeks are only read by the player card's
// LINES tab (latest week that has the player).
//
// IN THE DEPLOY ARTIFACT ONLY (like scripts/split_app.js): the repo file, the pull job
// (scripts/pull_betting_lines.py) and local dev stay unchanged.
//   - data/betting_lines_2026.js keeps the KEEP newest weeks of _WEEKLY_PROPS_2026
//   - data/betting_props_hist_2026.js gets the rest and merges them into
//     window.BETTING_2026.weeklyProps (never overwriting a week already there)
//   - index.html: that file joins window._LATE_DATA_FILES (loaded right after first
//     paint; 'mff:latedata' then repaints an open card / Start/Sit), with the same ?v=
//     as the betting_lines tag so the service worker caches it per data version.
//
//   node scripts/split_props.js            # rewrite in place (deploy: run in the checkout)
//   node scripts/split_props.js <siteDir>  # same, on a copied site (local preview)
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
function req(name) {
  for (const base of [path.join(ROOT, '.build-tools', 'node_modules'), path.join(ROOT, 'node_modules')]) {
    try { return require(path.join(base, name)); } catch (e) {}
  }
  return require(name);
}
const acorn = req('acorn');

const KEEP = 3;                    // newest weeks left in the first-paint file
const SRC = 'data/betting_lines_2026.js';
const HIST = 'data/betting_props_hist_2026.js';
const VAR = '_WEEKLY_PROPS_2026';

const dir = path.resolve(process.argv[2] || ROOT);
const srcPath = path.join(dir, SRC);
const idxPath = path.join(dir, 'index.html');
const fail = msg => { console.error('split_props: ' + msg); process.exit(1); };

const src = fs.readFileSync(srcPath, 'utf8');
const ast = acorn.parse(src, { ecmaVersion: 2022, sourceType: 'script' });
let obj = null;
for (const st of ast.body) {
  if (st.type !== 'VariableDeclaration') continue;
  for (const dc of st.declarations) if (dc.id && dc.id.name === VAR && dc.init && dc.init.type === 'ObjectExpression') obj = dc.init;
}
if (!obj) fail(VAR + ' object literal not found in ' + SRC);

const weekOf = p => {
  if (p.type !== 'Property' || p.computed) return NaN;
  const k = p.key.type === 'Literal' ? p.key.value : p.key.type === 'Identifier' ? p.key.name : null;
  return /^\d+$/.test(String(k)) ? +k : NaN;
};
const props = obj.properties;
if (props.some(p => isNaN(weekOf(p)))) fail(VAR + ' has a key that is not a week number; not splitting');
const weeks = props.map(weekOf);
const keep = new Set([...weeks].sort((a, b) => b - a).slice(0, KEEP));
const kept = props.filter(p => keep.has(weekOf(p)));
const moved = props.filter(p => !keep.has(weekOf(p)));
if (!moved.length) { console.log('split_props: ' + weeks.length + ' week(s), nothing to move'); process.exit(0); }

const text = p => src.slice(p.start, p.end);
const core = src.slice(0, obj.start) + '{\n  ' + kept.map(text).join(',\n  ') + '\n}' + src.slice(obj.end);
const hist = '// Deploy-built by scripts/split_props.js: weeks ' + moved.map(weekOf).join(', ') + ' of ' + VAR
  + ' (newest ' + KEEP + ' stay in betting_lines_2026.js). Loaded after first paint.\n'
  + '(function () {\n  var B = window.BETTING_2026; if (!B) return;\n  var W = B.weeklyProps || (B.weeklyProps = {});\n'
  + '  var H = {\n  ' + moved.map(text).join(',\n  ') + '\n  };\n'
  + '  for (var k in H) if (!Object.prototype.hasOwnProperty.call(W, k)) W[k] = H[k];\n})();\n';

// Both outputs must still parse, and core + hist together must equal the original weeks.
acorn.parse(core, { ecmaVersion: 2022, sourceType: 'script' });
acorn.parse(hist, { ecmaVersion: 2022, sourceType: 'script' });
const vm = require('vm');
const run = (code, ctx) => { vm.runInNewContext(code, ctx); return ctx; };
const orig = run(src, { window: {} }).window.BETTING_2026.weeklyProps;
const ctx = run(core, { window: {} });
const before = Object.keys(ctx.window.BETTING_2026.weeklyProps).length;
run(hist, ctx);
const merged = ctx.window.BETTING_2026.weeklyProps;
if (JSON.stringify(Object.keys(merged).sort()) !== JSON.stringify(Object.keys(orig).sort())) fail('week keys differ after merge');
for (const k of Object.keys(orig)) if (JSON.stringify(merged[k]) !== JSON.stringify(orig[k])) fail('week ' + k + ' differs after merge');
if (before !== kept.length) fail('core kept ' + before + ' weeks, expected ' + kept.length);

// index.html: add the hist file to _LATE_DATA_FILES with the betting_lines ?v=.
let html = fs.readFileSync(idxPath, 'utf8');
const vm1 = /data\/betting_lines_2026\.js\?v=([^"'\s]+)/.exec(html);
if (!vm1) fail('betting_lines_2026.js?v= not found in index.html');
const anchor = 'window._LATE_DATA_FILES = [';
const at = html.indexOf(anchor);
if (at < 0 || html.indexOf(anchor, at + 1) >= 0) fail('expected exactly one "' + anchor + '" in index.html');
html = html.slice(0, at + anchor.length) + "\n  '" + HIST + '?v=' + vm1[1] + "'," + html.slice(at + anchor.length);

fs.writeFileSync(srcPath, core);
fs.writeFileSync(path.join(dir, HIST), hist);
fs.writeFileSync(idxPath, html);
const kb = s => Math.round(Buffer.byteLength(s) / 1024);
console.log('split_props: kept weeks ' + [...keep].sort((a, b) => a - b).join(', ') + ' in ' + SRC + ' (' + kb(src) + ' -> ' + kb(core) + ' KB raw); '
  + 'weeks ' + moved.map(weekOf).join(', ') + ' -> ' + HIST + ' (' + kb(hist) + ' KB raw), added to _LATE_DATA_FILES ?v=' + vm1[1]);
