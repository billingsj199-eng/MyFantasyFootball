#!/usr/bin/env node
// app.js code-splitting (mobile perf plan, phase 3 — 2026-10-13).
//
// app.js stays ONE source file. Lazy sections are fenced with marker lines:
//
//     //#chunk research
//     ...code that only the Research page needs...
//     //#endchunk research
//
// At deploy (.github/workflows/static.yml, before terser) `--build` cuts the fenced
// regions out into app-chunk-<name>.js files and writes the remaining core back to
// app.js with a manifest line (`window._MFF_CHUNKS = [...]`). Without that manifest —
// local dev, the unsplit source — window._ensureChunk() resolves immediately because
// every chunk is already inline. So local dev keeps running exactly today's code; use
// `--site-copy` to preview the split build locally.
//
// Safety gate (both modes): parses app.js with acorn and FAILS when code outside a
// chunk uses a chunk's top-level declarations or window.X exports without a guard
// (`typeof X`, `window.X &&`, `if (window.X)`, optional call). Each chunk loads only
// on demand, so an unguarded reference throws ReferenceError / TypeError in production.
// References reviewed as safe go in scripts/split_app_allow.json ("<chunk>:<name>").
//
// Usage:
//   npm i --no-save --prefix .build-tools acorn@8.12.1 acorn-walk@8.3.4   (once)
//   node scripts/split_app.js --analyze research:71498-74834 [more ranges...]
//   node scripts/split_app.js --check                 # markers + gate, no writes
//   node scripts/split_app.js --build                 # CI: rewrites app.js + writes app-chunk-*.js
//   node scripts/split_app.js --site-copy .split-preview   # local split preview (copies the site)
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
const walk = req('acorn-walk');

const args = process.argv.slice(2);
const mode = args[0];
const SRC = path.join(ROOT, 'app.js');
const ALLOW_FILE = path.join(ROOT, 'scripts', 'split_app_allow.json');

function readSource(file) { return fs.readFileSync(file, 'utf8'); }

// ---- markers -------------------------------------------------------------------------
function findMarkers(src) {
  const lines = src.split('\n');
  const chunks = []; let open = null;
  lines.forEach((l, i) => {
    const m = /^\/\/#(chunk|endchunk)\s+([a-z0-9-]+)\s*\r?$/.exec(l);
    if (!m) { if (/^\s*\/\/#(end)?chunk\b/.test(l)) throw new Error(`line ${i + 1}: malformed chunk marker: ${l.trim()}`); return; }
    const [, kind, name] = m;
    if (kind === 'chunk') {
      if (open) throw new Error(`line ${i + 1}: chunk "${name}" opened inside chunk "${open.name}"`);
      if (chunks.some(c => c.name === name)) throw new Error(`line ${i + 1}: chunk "${name}" defined twice`);
      open = { name, start: i + 1 };
    } else {
      if (!open || open.name !== name) throw new Error(`line ${i + 1}: //#endchunk ${name} without matching //#chunk`);
      chunks.push({ name, start: open.start, end: i + 1 }); open = null;
    }
  });
  if (open) throw new Error(`chunk "${open.name}" (line ${open.start}) never closed`);
  return chunks;
}

// ---- analysis ------------------------------------------------------------------------
function declNames(stmt) {
  const out = [];
  const pat = p => {
    if (!p) return;
    if (p.type === 'Identifier') out.push(p.name);
    else if (p.type === 'ObjectPattern') p.properties.forEach(q => pat(q.type === 'RestElement' ? q.argument : q.value));
    else if (p.type === 'ArrayPattern') p.elements.forEach(pat);
    else if (p.type === 'AssignmentPattern') pat(p.left);
    else if (p.type === 'RestElement') pat(p.argument);
  };
  if (stmt.type === 'FunctionDeclaration' || stmt.type === 'ClassDeclaration') out.push(stmt.id.name);
  if (stmt.type === 'VariableDeclaration') stmt.declarations.forEach(d => pat(d.id));
  return out;
}
const isWindowMember = (n, name) => n && n.type === 'MemberExpression' && !n.computed && n.object.type === 'Identifier' &&
  (n.object.name === 'window' || n.object.name === 'globalThis' || n.object.name === 'self') && n.property.name === (name || n.property.name);

// Does `test` check for the existence of `name` (typeof name / window.name truthiness)?
function testChecks(test, name) {
  let hit = false;
  walk.full(test, n => {
    if (n.type === 'UnaryExpression' && n.operator === 'typeof' &&
        ((n.argument.type === 'Identifier' && n.argument.name === name) || isWindowMember(n.argument, name))) hit = true;
    if (isWindowMember(n, name)) hit = true;
    if (n.type === 'Identifier' && n.name === name) hit = true;
  });
  return hit;
}
function guarded(ancestors, name) {
  // ancestors: outermost → node
  const node = ancestors[ancestors.length - 1];
  for (let i = ancestors.length - 2; i >= 0; i--) {
    const a = ancestors[i], child = ancestors[i + 1];
    if (a.type === 'UnaryExpression' && a.operator === 'typeof') return true;
    if (a.type === 'ChainExpression') return true;                          // window.X?.()
    if ((a.type === 'CallExpression' || a.type === 'MemberExpression') && a.optional) return true;
    if (a.type === 'LogicalExpression' && (a.operator === '&&') && child === a.right && testChecks(a.left, name)) return true;
    if (a.type === 'LogicalExpression' && (a.operator === '||' || a.operator === '??') && child === a.left && isWindowMember(child, name)) return true;
    if ((a.type === 'IfStatement' || a.type === 'ConditionalExpression') && child !== a.test && testChecks(a.test, name)) {
      // `if (!X) return;` style negations are not handled — they count as unguarded (conservative)
      return true;
    }
    if (a.type === 'IfStatement' && child === a.test) return true;          // the existence test itself
    if (a.type === 'ConditionalExpression' && child === a.test) return true;
  }
  void node;
  return false;
}
function insideFunction(ancestors) {
  return ancestors.slice(0, -1).some(a => /Function/.test(a.type));
}

function analyze(src, ranges) {
  const ast = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'script', locations: true, allowHashBang: true });
  const inRange = (stmt, r) => stmt.loc.start.line >= r.start && stmt.loc.end.line <= r.end;
  const straddle = [];
  for (const s of ast.body) for (const r of ranges) {
    const a = s.loc.start.line, b = s.loc.end.line;
    if ((a < r.start && b >= r.start) || (a <= r.end && b > r.end)) straddle.push(`${r.name}: statement at lines ${a}-${b} crosses the chunk boundary ${r.start}-${r.end}`);
  }
  const report = {};
  for (const r of ranges) {
    const stmts = ast.body.filter(s => inRange(s, r));
    const decls = new Set(stmts.flatMap(declNames));
    const exports = new Set();
    stmts.forEach(s => walk.full(s, n => {
      if (n.type === 'AssignmentExpression' && isWindowMember(n.left)) exports.add(n.left.property.name);
    }));
    const names = new Set([...decls, ...exports]);
    const refs = [];
    for (const s of ast.body) {
      if (inRange(s, r)) continue;
      walk.ancestor(s, {
        Identifier(n, st, anc) {
          if (!names.has(n.name)) return;
          const p = anc[anc.length - 2];
          if (p && p.type === 'MemberExpression' && p.property === n && !p.computed) return;   // obj.X
          if (p && (p.type === 'Property' || p.type === 'MethodDefinition') && p.key === n && !p.computed) return;
          if (p && /Function/.test(p.type) && (p.id === n || p.params.includes(n))) return;
          if (p && p.type === 'VariableDeclarator' && p.id === n) return;
          refs.push({ name: n.name, line: n.loc.start.line, guarded: guarded(anc, n.name), runtime: insideFunction(anc), kind: decls.has(n.name) ? 'decl' : 'export' });
        },
        MemberExpression(n, st, anc) {
          if (!isWindowMember(n) || !exports.has(n.property.name)) return;
          const p = anc[anc.length - 2];
          if (p && p.type === 'AssignmentExpression' && p.left === n) return;                  // outside code re-assigning it
          refs.push({ name: n.property.name, line: n.loc.start.line, guarded: guarded(anc, n.property.name), runtime: insideFunction(anc), kind: 'window.' });
        }
      });
    }
    // a chunk's own top-level declarations must not shadow/duplicate core ones
    const coreDecls = new Set(ast.body.filter(s => !ranges.some(q => inRange(s, q))).flatMap(declNames));
    const dupes = [...decls].filter(d => coreDecls.has(d));
    const chunkLines = src.split('\n').slice(r.start - 1, r.end);
    const timing = [];
    chunkLines.forEach((l, i) => {
      if (/addEventListener\(\s*['"](DOMContentLoaded|load)['"]/.test(l) && !/readyState/.test(chunkLines.slice(Math.max(0, i - 3), i + 1).join('\n'))) timing.push(`${l.match(/DOMContentLoaded|load/)[0]}@${r.start + i}`);
      if (/new MutationObserver\(/.test(l)) timing.push(`MutationObserver@${r.start + i}`);
    });
    report[r.name] = { range: `${r.start}-${r.end}`, bytes: chunkLines.join('\n').length, topDecls: [...decls], exports: [...exports], refs, dupes, timing };
  }
  return { report, straddle };
}

function printReport({ report, straddle }, allow) {
  let bad = straddle.length;
  straddle.forEach(s => console.log('  !! ' + s));
  for (const [name, r] of Object.entries(report)) {
    const unguarded = r.refs.filter(x => !x.guarded && !allow.has(`${name}:${x.name}`));
    console.log(`\n== chunk ${name} (lines ${r.range}, ${Math.round(r.bytes / 1024)} KB): ${r.topDecls.length} top-level decls, ${r.exports.length} window exports, ${r.refs.length} outside refs (${unguarded.length} unguarded)`);
    if (r.dupes.length) { bad++; console.log('  !! declared both in chunk and core: ' + r.dupes.join(', ')); }
    const by = {};
    unguarded.forEach(x => { (by[x.name] = by[x.name] || []).push(x.line + (x.runtime ? '' : ' (LOAD-TIME)')); });
    Object.entries(by).forEach(([n, ls]) => { bad++; console.log(`  !! unguarded ${n}: lines ${ls.slice(0, 12).join(', ')}${ls.length > 12 ? ' …' : ''}`); });
    const g = r.refs.filter(x => x.guarded).length;
    if (g) console.log(`  ok ${g} guarded refs (${[...new Set(r.refs.filter(x => x.guarded).map(x => x.name))].slice(0, 10).join(', ')})`);
    // Guarded but evaluated while app.js first runs: with the chunk lazy these silently
    // become no-ops, so a one-time init could be skipped. Informational — review by hand.
    const lt = r.refs.filter(x => x.guarded && !x.runtime);
    if (lt.length) console.log(`  note load-time guarded refs (no-op until the chunk loads): ${lt.map(x => x.name + '@' + x.line).slice(0, 12).join(', ')}`);
    // Load-timing patterns inside the chunk: a lazy chunk runs after DOMContentLoaded and
    // possibly after its page was activated, so DCL listeners / class-change observers can
    // miss their only event. Informational — each needs an "already happened" fallback.
    if (r.timing.length) console.log(`  note load-timing patterns (need a fallback for "already happened"): ${r.timing.slice(0, 8).join(', ')}`);
  }
  return bad;
}

function loadAllow() {
  try { return new Set(JSON.parse(fs.readFileSync(ALLOW_FILE, 'utf8')).allow || []); } catch (e) { return new Set(); }
}

// ---- build ---------------------------------------------------------------------------
function split(src, chunks) {
  const lines = src.split('\n');
  const keep = lines.slice();
  const out = {};
  for (const c of chunks) {
    out[c.name] = lines.slice(c.start, c.end - 1).join('\n');   // between the marker lines
    for (let i = c.start - 1; i < c.end; i++) keep[i] = '';
    keep[c.start - 1] = `// [chunk ${c.name}: lines ${c.start}-${c.end} → app-chunk-${c.name}.js, loaded on demand by window._ensureChunk]`;
  }
  const manifest = `window._MFF_CHUNKS = ${JSON.stringify(chunks.map(c => c.name))};`;
  return { core: manifest + '\n' + keep.join('\n'), chunks: out };
}

// index.html: <script>/<link rel=preload> tags carrying data-split-lazy="<key>" are eager in the
// source (local dev = today's behaviour) but lazy in the split build: drop them and expose
// their URLs as window._SPLIT_LAZY_DATA[<key>] (read by loaders like window._loadEpRetired).
function transformIndex(file) {
  let html = fs.readFileSync(file, 'utf8');
  const map = {};
  html = html.replace(/<(script|link)\b([^>]*\bdata-split-lazy="([a-z0-9-]+)"[^>]*)>(<\/script>)?\r?\n?/g, (m, tag, attrs, key) => {
    const url = /\b(?:src|href)="([^"]+)"/.exec(attrs);
    if (!url) throw new Error('data-split-lazy tag without src/href: ' + m.slice(0, 120));
    if (tag === 'script') map[key] = url[1];
    else if (!map[key]) map[key] = url[1];
    return '';
  });
  if (!Object.keys(map).length) return {};
  const inject = `<script>window._SPLIT_LAZY_DATA = ${JSON.stringify(map)};</script>\n`;
  if (html.indexOf('</head>') < 0) throw new Error('index.html has no </head>');
  html = html.replace('</head>', inject + '</head>');
  fs.writeFileSync(file, html);
  return map;
}

function main() {
  const src = readSource(SRC);
  if (mode === '--analyze') {
    const ranges = args.slice(1).map(a => { const m = /^([a-z0-9-]+):(\d+)-(\d+)$/.exec(a); if (!m) throw new Error('bad range ' + a); return { name: m[1], start: +m[2], end: +m[3] }; });
    printReport(analyze(src, ranges), new Set());
    return;
  }
  const chunks = findMarkers(src);
  if (!chunks.length) { console.log('split_app: no //#chunk markers — nothing to split'); if (mode === '--build' || mode === '--site-copy') { /* fall through: copy still useful */ } else return; }
  if (chunks.length) {
    const bad = printReport(analyze(src, chunks), loadAllow());
    if (bad) { console.error(`\nsplit_app: ${bad} problem(s) — refusing to split (fix, guard, or allowlist in scripts/split_app_allow.json)`); process.exit(1); }
  }
  if (mode === '--check') { console.log('\nsplit_app: check passed'); return; }
  let outDir = ROOT;
  if (mode === '--site-copy') {
    outDir = path.resolve(args[1] || path.join(ROOT, '.split-preview'));
    const skip = new Set(['.git', '.build-tools', '.split-preview', 'node_modules', '.claude', '.nflverse_cache']);
    const copy = (from, to) => {
      fs.mkdirSync(to, { recursive: true });
      for (const e of fs.readdirSync(from, { withFileTypes: true })) {
        if (skip.has(e.name) || (from === path.join(ROOT, 'tests') && e.name === 'node_modules')) continue;
        const a = path.join(from, e.name), b = path.join(to, e.name);
        if (e.isDirectory()) copy(a, b); else if (e.isFile()) fs.copyFileSync(a, b);
      }
    };
    copy(ROOT, outDir);
    console.log('split_app: site copied to ' + outDir);
  } else if (mode !== '--build') {
    console.error('usage: --analyze <name:a-b>... | --check | --build | --site-copy [dir]'); process.exit(2);
  }
  if (!chunks.length) return;
  const { core, chunks: parts } = split(src, chunks);
  fs.writeFileSync(path.join(outDir, 'app.js'), core);
  for (const [name, code] of Object.entries(parts)) {
    fs.writeFileSync(path.join(outDir, `app-chunk-${name}.js`), `// app-chunk-${name}.js — generated from app.js by scripts/split_app.js; edit app.js, not this file.\n` + code + '\n');
  }
  const lazyData = transformIndex(path.join(outDir, 'index.html'));
  const kb = s => Math.round(Buffer.byteLength(s) / 1024);
  console.log(`split_app: core ${kb(core)} KB` + Object.entries(parts).map(([n, c]) => `, ${n} ${kb(c)} KB`).join('') + ` → ${outDir}`);
  if (Object.keys(lazyData).length) console.log('split_app: index.html lazy data → ' + JSON.stringify(lazyData));
}

try { main(); } catch (e) { console.error('split_app: ' + e.message); process.exit(1); }
