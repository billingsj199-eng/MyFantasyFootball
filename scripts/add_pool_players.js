#!/usr/bin/env node
/* add_pool_players.js — add in-season fill-ins to the site pool (data/d.js).
 *
 * The pool is built pre-season, so a player who earns a role in-season
 * (Drew Lock 09-16, Raheim Sanders 09-30, Brycen Tremayne 10-04) is not
 * rankable until he has a D row. This appends the same minimal object the
 * hand recipe used and bakes his ESPN headshot id:
 *
 *   node scripts/add_pool_players.js --suggest            # who is missing?
 *   node scripts/add_pool_players.js "Brycen Tremayne" "Cody White"
 *   node scripts/add_pool_players.js --all                # add every --suggest hit
 *   (--dry-run on either add form prints the rows without writing)
 *
 * Names are matched against the 32 live ESPN rosters (id, team, position,
 * age, experience) plus the ESPN athlete record (draft round); careers come
 * from data/all_players.js with 2024+ seasons filled from Sleeper season
 * totals, the season points from Clay when he has a row.
 * New rows go to the END of D with a = 240 and the next free position rank,
 * so they land last on every saved board until Jack ranks them.
 *
 * Missing school / height / weight on the player's COMBINE_DATA row (the card
 * bio) is filled from the roster too.
 *
 * After a run: python scripts/pull_postgame_stats.py (2026 game logs for the
 * new names; earlier seasons' weekly logs arrive with Tuesday's
 * data/fetch_weekly_stats.py, or run it by hand from data/), then bump ?v= on
 * d.js (preload + tag), headshot_espn_ids.js, combine_data.js (preload + tag)
 * and weekly_stats_active.js in index.html.
 *
 * --suggest rule (RB / WR / TE not in D, alias-checked by last name + team):
 * consensus weekly projection >= 1.5, or a Sim Lab week >= 2.0, or >= 6
 * half-PPR points this season, or ESPN depth chart RB1-2 / WR1-3. QBs: every
 * depth-chart QB2, plus anyone with >= 10 points this season.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..');
const read = (f) => fs.readFileSync(path.join(ROOT, f), 'utf8');
// Data files declare top-level const/var, which a vm context does not expose —
// append the expression to read back.
const evalData = (f, expr) => vm.runInNewContext(read(f) + '\n;' + expr, { window: {} });

const SUFFIX_RE = /\s+(jr|sr|ii|iii|iv|v)$/;
const norm = (s) => s.toLowerCase().replace(/[.'‘’]/g, '').replace(/\s+/g, ' ').trim();
const bare = (s) => norm(s).replace(SUFFIX_RE, '');
const lastName = (s) => bare(s).split(' ').pop();

const TEAM_IDS = [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,33,34];
const POS_MAP = { QB: 'QB', RB: 'RB', FB: 'RB', WR: 'WR', TE: 'TE' };

async function loadRosters() {
  const out = {};   // bare name -> [{name,id,pos,team,abbr,age,exp}]
  for (let i = 0; i < TEAM_IDS.length; i += 8) {
    await Promise.all(TEAM_IDS.slice(i, i + 8).map(async (tid) => {
      const r = await fetch('https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/' + tid + '/roster');
      if (!r.ok) throw new Error('ESPN roster ' + tid + ' HTTP ' + r.status);
      const j = await r.json();
      for (const g of j.athletes || []) for (const a of g.items || []) {
        const pos = POS_MAP[a.position && a.position.abbreviation];
        if (!pos || !a.fullName) continue;
        (out[bare(a.fullName)] = out[bare(a.fullName)] || []).push({
          name: a.fullName, id: String(a.id), pos, team: j.team.displayName, abbr: j.team.abbreviation,
          age: a.age != null ? a.age : null, exp: a.experience && a.experience.years != null ? a.experience.years : null,
          school: a.college && a.college.name || null, ht: a.height ? Math.floor(a.height / 12) + '-' + Math.round(a.height % 12) : null,
          wt: a.weight || null, debut: a.debutYear || null,
        });
      }
    }));
  }
  return out;
}

// D.dr = draft round, 'U' for undrafted. The roster feed has no draft block; the athlete record does.
async function draftRound(id) {
  const r = await fetch('https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/athletes/' + id);
  if (!r.ok) throw new Error('ESPN athlete ' + id + ' HTTP ' + r.status);
  const j = await r.json();
  return j.draft && j.draft.round ? j.draft.round : 'U';
}
// all_players.js is not league-complete for recent seasons (2025 was appended for pool players
// only), so a fill-in's missing 2024+ seasons come from Sleeper season totals (half-PPR, same basis).
const SEASON = 2026;
const BACKFILL_YEARS = [];
for (let y = 2024; y < SEASON; y++) BACKFILL_YEARS.push(y);

async function getJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + ' HTTP ' + r.status);
  return r.json();
}

async function loadSleeper() {
  const [db, ...seasons] = await Promise.all([getJson('https://api.sleeper.app/v1/players/nfl')]
    .concat(BACKFILL_YEARS.map((y) => getJson('https://api.sleeper.app/v1/stats/nfl/regular/' + y))));
  const byName = {};
  for (const [sid, p] of Object.entries(db)) {
    const pos = POS_MAP[p.position];
    const full = p.full_name || ((p.first_name || '') + ' ' + (p.last_name || '')).trim();
    if (pos && full) (byName[bare(full)] = byName[bare(full)] || []).push({ sid, pos, team: p.team === 'WAS' ? 'WSH' : p.team, active: !!p.active });
  }
  // Same name + position; the one on his ESPN team wins, then the active one.
  const sidFor = (e) => {
    const c = (byName[bare(e.name)] || []).filter((x) => x.pos === e.pos)
      .sort((a, b) => (b.team === e.abbr) - (a.team === e.abbr) || b.active - a.active);
    return c.length ? c[0].sid : null;
  };
  const seasonRow = (sid, i) => {
    const s = seasons[i][sid];
    if (!s || !s.gp) return null;
    const fpts = Math.round((s.pts_half_ppr || 0) * 10) / 10;
    return { yr: BACKFILL_YEARS[i], gp: s.gp, fpts, ppg: Math.round(fpts / s.gp * 10) / 10, py: s.pass_yd || 0, ptd: s.pass_td || 0, int: s.pass_int || 0,
      ra: s.rush_att || 0, ry: s.rush_yd || 0, rtd: s.rush_td || 0, rc: s.rec || 0, rcy: s.rec_yd || 0, rctd: s.rec_td || 0, fl: s.fum_lost || 0 };
  };
  return { sidFor, seasonRow };
}

const CAREER_KEYS = ['yr', 'gp', 'fpts', 'ppg', 'py', 'ptd', 'int', 'ra', 'ry', 'rtd', 'rc', 'rcy', 'rctd', 'fl'];

function suggest(D, rosters) {
  const have = new Set(D.map((d) => bare(d.n)));
  const dTeamLast = new Set(D.map((d) => lastName(d.n) + '|' + d.t + '|' + d.s + '|' + norm(d.n)[0]));
  const cand = {};
  const add = (n, k, v) => {
    const key = bare(n);
    if (have.has(key)) return;
    const c = cand[key] = cand[key] || {};
    if (c[k] == null || v > c[k] || typeof v === 'string') c[k] = v;
  };
  const depth = evalData('data/depth_charts_2026.js', 'window.DEPTH_2026').teams;
  for (const t of Object.values(depth)) for (const [pos, arr] of Object.entries(t)) arr.forEach((n, i) => add(n, 'dc', pos + (i + 1)));
  const adv = evalData('data/adv_stats_2026.js', 'window.ADV_STATS[2026]');
  for (const pos of ['QB', 'RB', 'WR', 'TE']) {
    const fi = adv[pos].f.indexOf('fpt');
    for (const r of adv[pos].r) add(r[0], 'fpt', r[fi] || 0);
  }
  const wp = JSON.parse(read('data/weekly_projections.json')).players;
  for (const [n, v] of Object.entries(wp)) add(n, 'wp', v.h || 0);
  const sim = JSON.parse(read('data/sim_proj_2026.json'));
  for (const w of Object.values(sim.weeks)) for (const [n, v] of Object.entries(w)) if (Array.isArray(v)) add(n, 'sim', v[0] || 0);

  const rows = [];
  for (const [key, c] of Object.entries(cand)) {
    const hits = rosters[key];
    if (!hits || hits.length !== 1) continue;   // not on an active roster (or ambiguous) — add by hand
    const e = hits[0];
    // Same last name + team + position + first initial already in D = a spelling alias (Kenny/Kenneth Gainwell).
    if (dTeamLast.has(lastName(e.name) + '|' + e.team + '|' + e.pos + '|' + norm(e.name)[0])) continue;
    const dcN = c.dc && c.dc.startsWith(e.pos) ? +c.dc.replace(/\D/g, '') : 99;
    const ok = e.pos === 'QB'
      ? dcN === 2 || (c.fpt || 0) >= 10
      : (c.wp || 0) >= 1.5 || (c.sim || 0) >= 2 || (c.fpt || 0) >= 6 || (e.pos === 'RB' && dcN <= 2) || (e.pos === 'WR' && dcN <= 3);
    if (ok) rows.push(Object.assign({ name: e.name, pos: e.pos, abbr: e.abbr }, c));
  }
  const ord = { QB: 0, RB: 1, WR: 2, TE: 3 };
  return rows.sort((a, b) => ord[a.pos] - ord[b.pos] || Math.max(b.wp || 0, b.sim || 0) - Math.max(a.wp || 0, a.sim || 0));
}

async function main() {
  const args = process.argv.slice(2);
  const flag = (f) => args.includes(f);
  const names = args.filter((a) => !a.startsWith('--'));
  if (!names.length && !flag('--suggest') && !flag('--all')) {
    console.error('usage: node scripts/add_pool_players.js --suggest | --all | "Name" ["Name" ...]  [--dry-run]');
    process.exit(1);
  }

  const dRaw = read('data/d.js');
  const D = evalData('data/d.js', 'D');
  const rosters = await loadRosters();

  let targets = names;
  if (flag('--suggest') || flag('--all')) {
    const rows = suggest(D, rosters);
    for (const r of rows) {
      console.log([r.pos, r.abbr.padEnd(3), r.name.padEnd(24), 'depth ' + (r.dc || '-').padEnd(4), 'pts ' + String(r.fpt != null ? r.fpt : '-').padEnd(5),
        'wk proj ' + String(r.wp != null ? r.wp : '-').padEnd(4), 'sim ' + (r.sim != null ? r.sim : '-')].join('  '));
    }
    console.log(rows.length + ' candidates');
    if (!flag('--all')) return;
    targets = rows.map((r) => r.name);
  }

  const allPlayers = evalData('data/all_players.js', 'ALL_PLAYERS_DB');
  const clay = evalData('data/mike_clay_projections.js', 'MIKE_CLAY_PROJ');
  const sleeper = await loadSleeper();
  const clayByName = {};
  for (const [n, v] of Object.entries(clay)) clayByName[bare(n)] = v;

  const have = new Set(D.map((d) => bare(d.n)));
  const nextRank = {};
  for (const d of D) {
    const m = /^([A-Z]+)(\d+)$/.exec(d.r || '');
    if (m) nextRank[m[1]] = Math.max(nextRank[m[1]] || 0, +m[2]);
  }

  const added = [];
  for (const raw of targets) {
    const key = bare(raw);
    if (have.has(key)) { console.log('SKIP (already in pool): ' + raw); continue; }
    const hits = rosters[key] || [];
    if (hits.length !== 1) { console.log('SKIP (' + (hits.length ? 'ambiguous on' : 'not on') + ' ESPN rosters): ' + raw); continue; }
    const e = hits[0];
    // all_players.js can hold two players with one name — take the position match that played most recently.
    const ap = allPlayers.filter((p) => bare(p.name) === key && p.pos === e.pos && p.last >= 2020).sort((a, b) => b.last - a.last)[0];
    const career = (ap ? ap.career : []).map((c) => { const o = {}; for (const k of CAREER_KEYS) o[k] = c[k] != null ? c[k] : 0; return o; });
    const sid = sleeper.sidFor(e);
    BACKFILL_YEARS.forEach((yr, i) => {
      const row = sid && !career.some((c) => c.yr === yr) && sleeper.seasonRow(sid, i);
      if (row) career.push(row);
    });
    career.sort((a, b) => a.yr - b.yr);
    const ppg = (yr) => { const c = career.find((x) => x.yr === yr); return c ? c.ppg : 0; };
    const s25 = career.find((c) => c.yr === 2025) || { yr: 2025, gp: 0, fpts: 0, ppg: 0, py: 0, ptd: 0, int: 0, ra: 0, ry: 0, rtd: 0, rc: 0, rcy: 0, rctd: 0, fl: 0 };
    const cl = clayByName[key];
    nextRank[e.pos] = (nextRank[e.pos] || 0) + 1;
    const row = {
      n: e.name, a: 240, p: cl && cl.pts > 1 ? cl.pts : 1, s: e.pos, r: e.pos + nextRank[e.pos], t: e.team,
      p25: ppg(2025), p24: ppg(2024), p23: ppg(2023), age: e.age, cyr: null, out: null, sal: null,
      dr: await draftRound(e.id), exp: e.exp, role: null, inj: null,
      s25: Object.assign({}, s25), career, da: null, sa: null, slDy: null, slDsf: null,
    };
    added.push({ row, id: e.id, bio: e });
    have.add(key);
    console.log('ADD ' + row.n.padEnd(24) + row.r.padEnd(6) + e.abbr.padEnd(4) + 'age ' + row.age + '  exp ' + row.exp + '  dr ' + row.dr +
      '  clay ' + row.p + '  career ' + (career.length ? career[0].yr + '-' + career[career.length - 1].yr : 'none') + '  espn ' + e.id);
  }
  if (!added.length) { console.log('Nothing to add.'); return; }
  if (flag('--dry-run')) { console.log('--dry-run: ' + added.length + ' rows not written'); return; }

  // d.js: splice the new objects in front of the closing `];` — every other byte is untouched.
  const end = dRaw.lastIndexOf('}];');
  if (end < 0) throw new Error('d.js: closing }]; not found');
  const dNew = dRaw.slice(0, end + 1) + added.map((a) => ',' + JSON.stringify(a.row)).join('') + dRaw.slice(end + 1);
  if (vm.runInNewContext(dNew + '\n;D', { window: {} }).length !== D.length + added.length) throw new Error('d.js: row count mismatch after splice');
  fs.writeFileSync(path.join(ROOT, 'data/d.js'), dNew);

  const hsFile = 'data/headshot_espn_ids.js';
  const hsRaw = read(hsFile);
  const m = /\};?(\r?\nwindow\.BAKED_ESPN_MISSES)/.exec(hsRaw);
  if (!m) throw new Error('headshot_espn_ids.js: end of BAKED_ESPN_IDS not found');
  const known = evalData(hsFile, 'window.BAKED_ESPN_IDS');
  const ins = added.filter((a) => !known[a.row.n]).map((a) => ',' + JSON.stringify(a.row.n) + ':' + JSON.stringify(a.id)).join('');
  fs.writeFileSync(path.join(ROOT, hsFile), hsRaw.slice(0, m.index) + ins + hsRaw.slice(m.index));

  // Card bio (PROSPECT tab: school / height / weight) reads COMBINE_DATA. Undrafted players often
  // have a bare {yr, ras} row there — fill the blanks from the ESPN roster; drilled values are never
  // overwritten. No row at all: create one only for a past class with a known debut year (a current
  // rookie row would switch on the site's rookie-class logic).
  const cbFile = 'data/combine_data.js';
  let cbRaw = read(cbFile);
  const combine = evalData(cbFile, 'COMBINE_DATA');
  const cbKeys = {};
  for (const k of Object.keys(combine)) if (!combine[k].devy) (cbKeys[bare(k)] = cbKeys[bare(k)] || []).push(k);
  const bioNotes = [];
  for (const a of added) {
    const b = a.bio;
    const fill = { school: b.school, ht: b.ht, wt: b.wt };
    const keys = combine[a.row.n] ? [a.row.n] : (cbKeys[bare(a.row.n)] || []);
    if (keys.length === 1) {
      const cur = combine[keys[0]];
      const miss = Object.keys(fill).filter((k) => fill[k] && !cur[k]);
      if (!miss.length) continue;
      const at = cbRaw.indexOf(JSON.stringify(keys[0]) + ':' + JSON.stringify(cur));
      if (at < 0) { bioNotes.push(a.row.n + ' (row not byte-matched)'); continue; }
      const next = Object.assign({}, cur);
      for (const k of miss) next[k] = fill[k];
      cbRaw = cbRaw.slice(0, at) + JSON.stringify(keys[0]) + ':' + JSON.stringify(next) + cbRaw.slice(at + (JSON.stringify(keys[0]) + ':' + JSON.stringify(cur)).length);
      console.log('BIO ' + a.row.n + ': ' + miss.map((k) => k + ' ' + fill[k]).join(', '));
    } else if (!keys.length && b.debut && b.debut < SEASON && b.school) {
      const end = cbRaw.lastIndexOf('}');
      cbRaw = cbRaw.slice(0, end) + ',' + JSON.stringify(a.row.n) + ':' + JSON.stringify({ yr: b.debut, school: b.school, ht: b.ht, wt: b.wt }) + cbRaw.slice(end);
      console.log('BIO ' + a.row.n + ': new row (' + b.debut + ' ' + b.school + ')');
    } else bioNotes.push(a.row.n + (keys.length ? ' (ambiguous combine rows)' : ' (no combine row)'));
  }
  const cbCount = Object.keys(vm.runInNewContext(cbRaw + '\n;COMBINE_DATA', { window: {} })).length;
  if (cbCount < Object.keys(combine).length) throw new Error('combine_data.js: rows lost after bio patch');
  if (cbRaw !== read(cbFile)) fs.writeFileSync(path.join(ROOT, cbFile), cbRaw);
  if (bioNotes.length) console.log('No bio written for: ' + bioNotes.join(', '));

  console.log('Wrote ' + added.length + ' rows to data/d.js + headshot ids. Next: python scripts/pull_postgame_stats.py, then bump ?v= in index.html.');
}

main().catch((e) => { console.error(e.message || e); process.exit(1); });
