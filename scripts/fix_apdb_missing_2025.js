// Data repair: graft missing 2025 season rows into ALL_PLAYERS_DB from the
// weekly game logs (re-runnable, idempotent, --write gated).
//
// 2026-09-02 (Jack: "fix the missing 2025 seasons in the career database"):
// six players who played 2025 had no 2025 career row — Lamar Jackson plus
// five suffix names (Kenneth Walker III, Marvin Mims Jr., Calvin Austin III,
// John Metchie III, Isaiah Williams). Their 2025 game logs ARE in
// WEEKLY_STATS_ACTIVE, so the season row is rebuilt from them exactly the way
// the sibling 2025 rows were built (weekly fpts sum = half-PPR, the DB basis;
// regular-season weeks only, wk <= 18; gp = games with a stat line).
//
// Rule: a player gets a 2025 row iff he has NO 2025 career row, HAS a 2025
// weekly season with >= 1 stat-line game, and the weekly entry's position
// matches. Team comes from ACTIVE_TEAM_HISTORY's 2025 stint (abbreviated),
// else the weekly rows' tm, else ''. p.last is recomputed.
//
// Run:   node scripts/fix_apdb_missing_2025.js          (report only)
//        node scripts/fix_apdb_missing_2025.js --write  (rewrite data/all_players.js)

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..');
const APDB_FILE = path.join(ROOT, 'data', 'all_players.js');
const WEEKLY_FILE = path.join(ROOT, 'data', 'weekly_stats_active.js');
const ATH_FILE = path.join(ROOT, 'data', 'active_team_history.js');
const WRITE = process.argv.includes('--write');

const PREFIX = 'const ALL_PLAYERS_DB = ';
const src = fs.readFileSync(APDB_FILE, 'utf8');
if (!src.startsWith(PREFIX)) throw new Error('unexpected all_players.js prefix');
const DB = JSON.parse(src.slice(PREFIX.length).replace(/;\s*$/, ''));

function loadGlobal(file, name) {
  const sb = { window: {}, document: { addEventListener() {} } };
  sb.self = sb;
  vm.createContext(sb);
  vm.runInContext(fs.readFileSync(file, 'utf8').replace(/^(const|let) /mg, 'var '), sb);
  return sb[name] || sb.window[name];
}
const WEEKLY = loadGlobal(WEEKLY_FILE, 'WEEKLY_STATS_ACTIVE');
const ATH = loadGlobal(ATH_FILE, 'ACTIVE_TEAM_HISTORY');

const ABBR = {
  'Arizona Cardinals': 'ARI', 'Atlanta Falcons': 'ATL', 'Baltimore Ravens': 'BAL', 'Buffalo Bills': 'BUF',
  'Carolina Panthers': 'CAR', 'Chicago Bears': 'CHI', 'Cincinnati Bengals': 'CIN', 'Cleveland Browns': 'CLE',
  'Dallas Cowboys': 'DAL', 'Denver Broncos': 'DEN', 'Detroit Lions': 'DET', 'Green Bay Packers': 'GB',
  'Houston Texans': 'HOU', 'Indianapolis Colts': 'IND', 'Jacksonville Jaguars': 'JAX', 'Kansas City Chiefs': 'KC',
  'Las Vegas Raiders': 'LV', 'Los Angeles Chargers': 'LAC', 'Los Angeles Rams': 'LAR', 'Miami Dolphins': 'MIA',
  'Minnesota Vikings': 'MIN', 'New England Patriots': 'NE', 'New Orleans Saints': 'NO', 'New York Giants': 'NYG',
  'New York Jets': 'NYJ', 'Philadelphia Eagles': 'PHI', 'Pittsburgh Steelers': 'PIT', 'San Francisco 49ers': 'SF',
  'Seattle Seahawks': 'SEA', 'Tampa Bay Buccaneers': 'TB', 'Tennessee Titans': 'TEN', 'Washington Commanders': 'WSH'
};
function team2025(name, games) {
  const stints = ATH && ATH[name];
  if (Array.isArray(stints)) {
    const st = stints.find(s => s.y1 <= 2025 && s.y2 >= 2025);
    if (st && ABBR[st.t]) return ABBR[st.t];
  }
  const tm = games.map(g => g.tm).filter(Boolean);
  return tm.length ? tm[tm.length - 1] : '';
}

const YEAR = 2025;
const active = g => (g.pa || 0) + (g.ra || 0) + (g.rec || 0) + (g.rc || 0) + (g.tgt || 0) > 0 || (g.fpts || 0) !== 0;
const r1 = v => Math.round(v * 10) / 10;
const sum = (games, k) => games.reduce((t, g) => t + (g[k] || 0), 0);

let added = 0, skippedPos = 0;
const report = [];
for (const p of DB) {
  if (!p || !p.name || !Array.isArray(p.career)) continue;
  if (p.career.some(s => s.yr === YEAR)) continue;
  const w = WEEKLY && WEEKLY[p.name];
  const season = w && w.seasons && w.seasons[YEAR];
  if (!Array.isArray(season) || !season.length) continue;
  if (w.pos && p.pos && w.pos !== p.pos) { skippedPos++; report.push(`SKIP pos mismatch: ${p.name} apdb ${p.pos} weekly ${w.pos}`); continue; }
  // Era guard: a weekly key that matches a long-retired name is a different
  // person (bare "Marvin Harrison" = the Hall of Famer; the 2025 logs belong
  // to Marvin Harrison Jr.). Only graft onto careers still active in 2023+.
  const prevLast = Math.max.apply(null, p.career.map(s => s.yr || 0));
  if (YEAR - prevLast > 2) { skippedPos++; report.push(`SKIP era gap: ${p.name} (${p.pos}) last season ${prevLast} — weekly 2025 logs belong to someone else`); continue; }
  const games = season.filter(g => (g.wk || 0) >= 1 && (g.wk || 0) <= 18 && active(g));
  if (!games.length) continue;
  const row = {
    yr: YEAR,
    gp: games.length,
    tm: team2025(p.name, games),
    py: sum(games, 'py'), ptd: sum(games, 'ptd'), int: sum(games, 'int'),
    ra: sum(games, 'ra'), ry: sum(games, 'ry'), rtd: sum(games, 'rtd'),
    rc: sum(games, 'rec') + sum(games, 'rc'), rcy: sum(games, 'rcy'), rctd: sum(games, 'rctd'),
    fl: sum(games, 'fl'),
    fpts: r1(sum(games, 'fpts')),
    ppg: 0,
    pc: sum(games, 'pc'), pa: sum(games, 'pa'), tgt: sum(games, 'tgt')
  };
  row.ppg = r1(row.fpts / row.gp);
  p.career.push(row);
  p.career.sort((a, b) => a.yr - b.yr);
  p.last = Math.max(p.last || 0, YEAR);
  added++;
  report.push(`ADD ${p.name} (${p.pos}) 2025: ${row.gp} GP ${row.tm || '??'} · ${row.fpts} fpts ${row.ppg} ppg · py ${row.py} ry ${row.ry} rec ${row.rc}/${row.rcy}`);
}

console.log(report.join('\n'));
console.log(`\n${added} season row(s) to add, ${skippedPos} skipped (position mismatch / era gap).`);
if (!WRITE) { console.log('Dry run — pass --write to rewrite data/all_players.js'); process.exit(0); }
if (!added) { console.log('Nothing to write.'); process.exit(0); }
fs.writeFileSync(APDB_FILE, PREFIX + JSON.stringify(DB) + ';', 'utf8');
console.log('Wrote', APDB_FILE);
