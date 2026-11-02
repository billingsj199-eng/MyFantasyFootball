// Weekly LIVE-board refresh for the frozen Daily Trivia library (2026-11-02,
// Jack: "can we have 2026 update every week").
//
// The library (data/trivia_library.js) is frozen, so boards whose window reaches the
// season being played went stale: this season's season boards, the all-time single
// games, the career all-time / current-decade / since-2010 / postseason boards and every
// franchise board (active players keep adding yards). This rebuilds ONLY those with
// build_library.js and swaps them in; every other board stays exactly as audited.
// Reviewed flags live in Firestore by board id and are untouched.
//
// Two fixed entry points (scheduled-task rule: identical command strings):
//   node scripts/trivia_library/refresh_live.js build   rebuild live boards -> E:/MyFantasyFootball/trivia_library_cache (git-free)
//   node scripts/trivia_library/refresh_live.js merge   swap them into data/trivia_library.js + bump its ?v= in index.html
// The task wrapper (scripts/trivia_library_weekly_task.ps1) runs build before the repo
// turn and merge + commit inside it.
//
// Merge guard: a rebuilt board that lost items (< 16) or changed more than
// MAX_NEW_NAMES names in one go keeps its frozen copy and is reported — a week of games
// moves a player or two, a broken data load moves the whole board.
'use strict';

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..', '..');
const LIB = path.join(ROOT, 'data', 'trivia_library.js');
const INDEX = path.join(ROOT, 'index.html');
// Build output stays outside the repo (the task runs in the main checkout).
const CACHE = 'E:\\MyFantasyFootball\\trivia_library_cache';
fs.mkdirSync(CACHE, { recursive: true });
const OUT = path.join(CACHE, '_live_build.js');
const REPORT = path.join(CACHE, '_live_report.md');
const LOG = path.join(CACHE, '_live_build_log.json');
const MIN_ITEMS = 16;
const MAX_NEW_NAMES = 8;

// The season being played: Mar-Dec = this year, Jan-Feb = last year's playoffs.
function currentSeason(d = new Date()) { return d.getMonth() >= 2 ? d.getFullYear() : d.getFullYear() - 1; }
function liveRegex() {
  const cur = currentSeason();
  const decade = Math.floor(cur / 10) * 10;
  return '^(s' + cur + '-|g' + cur + '-|g-all-|c-all-|c-' + decade + 's-|c-since2010-|c-post-|t-)';
}

function load(file) {
  const w = {};
  new Function('window', fs.readFileSync(file, 'utf8'))(w);
  return w.TRIVIA_LIBRARY;
}
const nameOf = it => String(it.answer || '').replace(/\s*\(.*$/, '').trim();

function build() {
  const re = liveRegex();
  console.log('live boards: /' + re + '/');
  execFileSync(process.execPath, [path.join(__dirname, 'build_library.js'), '--only', re, '--out', OUT, '--report', REPORT, '--log', LOG],
    { cwd: ROOT, stdio: ['ignore', 'pipe', 'inherit'], maxBuffer: 64 * 1024 * 1024 });
  const B = load(OUT);
  console.log('built ' + B.boards.length + ' live boards -> ' + path.relative(ROOT, OUT));
}

function merge() {
  if (!fs.existsSync(OUT)) { console.log('no ' + path.relative(ROOT, OUT) + ' - run build first'); process.exit(1); }
  const src = fs.readFileSync(LIB, 'utf8');
  const A = load(LIB), B = load(OUT);
  const fresh = Object.fromEntries(B.boards.map(b => [b.id, b]));
  const re = new RegExp(liveRegex());
  let swapped = 0, same = 0;
  const held = [];
  const boards = A.boards.map(o => {
    const n = fresh[o.id];
    if (!n || !re.test(o.id)) return o;
    if (JSON.stringify(n.items) === JSON.stringify(o.items) && n.title === o.title) { same++; return o; }
    const oldNames = new Set(o.items.map(nameOf));
    const added = n.items.map(nameOf).filter(x => !oldNames.has(x));
    if (n.items.length < MIN_ITEMS || added.length > MAX_NEW_NAMES) {
      held.push(o.id + ' (' + n.items.length + ' items, ' + added.length + ' new names)');
      return o;
    }
    swapped++;
    return Object.assign({}, n, { reviewed: o.reviewed });
  });
  if (!swapped) {
    console.log('no live board changed (' + same + ' unchanged' + (held.length ? ', HELD ' + held.join('; ') : '') + ')');
    return;
  }
  const header = src.slice(0, src.indexOf('window.TRIVIA_LIBRARY'))
    .replace(/\/\/ Live boards refreshed [^\n]*\n/, '')
    .replace(/(\/\/ reviewed flags:[^\n]*\n)/, '$1// Live boards refreshed ' + new Date().toISOString().slice(0, 10) + ' by scripts/trivia_library/refresh_live.js (weekly).\n');
  fs.writeFileSync(LIB, header + 'window.TRIVIA_LIBRARY = {\n"built": ' + JSON.stringify(A.built) + ',\n"count": ' + boards.length +
    ',\n"boards": [\n' + boards.map(b => JSON.stringify(b)).join(',\n') + '\n]};\n');
  // Bump the library's cache-bust (read from disk right now — other jobs bump index.html too).
  const html = fs.readFileSync(INDEX, 'utf8');
  const v = 'v=' + new Date().toISOString().slice(0, 10) + '-live';
  const bumped = html.replace(/(data\/trivia_library\.js\?)v=[^'"]*/, '$1' + v);
  if (bumped === html && !html.includes('trivia_library.js?' + v)) { console.log('WARNING: trivia_library.js ?v= not found in index.html'); }
  fs.writeFileSync(INDEX, bumped);
  console.log('swapped ' + swapped + ' live boards, ' + same + ' unchanged' + (held.length ? ', HELD ' + held.join('; ') : '') + ' · ?' + v);
}

const cmd = process.argv[2];
if (cmd === 'build') build();
else if (cmd === 'merge') merge();
else { console.log('usage: node scripts/trivia_library/refresh_live.js build|merge'); process.exit(1); }
