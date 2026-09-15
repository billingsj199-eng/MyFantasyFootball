// ============================================================================
// export_site_proj.js — headless Sim Lab -> site weekly projections export.
//
// Runs the Sim Lab engine (engine.js) under Node with a window shim, computes
// every player's per-week projection (all 18 weeks, h/p/s scoring) plus
// boom/bust % from 1,000 correlated Monte Carlo draws per week, and writes
//   <repo>/data/sim_proj_2026.js    (window.SIM_PROJ_2026 — consumed by the
//                                    player-card LOGS tab 2026 view)
//   <repo>/data/sim_proj_2026.json  (state file: same payload + teamOf map,
//                                    used for the freeze merge on later runs)
//
// FREEZE RULE (per team, per week): once a team's kickoff for week W has
// passed (ESPN scoreboard timestamps, cached in data/kickoffs_2026.json),
// that team's player rows for week W are carried forward from the previous
// state file verbatim — later runs never rewrite a started game's PROJ.
// No kickoff data (fetch failed, no cache) -> fallback: week W freezes at
// its Thursday 8:00 PM ET (first kickoff of the week).
//
// IN-SEASON INJURY LAYER (engine E.applyInSeasonInjuries, shared with the Sim
// Lab week sim + the auto-lock; armed from 4 days before the current week's
// first kickoff — August camp tags stay with the engine's start-of-season windows):
//   Out            -> 0 for the current week
//   Doubtful       -> x0.5 for the current week
//   IR/PUP/NFI     -> 0 for current week .. current+3 (4-game IR minimum)
//   Sus(pended)    -> 0 for the current week
//   IN_SEASON_OUT_OVERRIDES['Name'] = [fromWk, toWk]  (overrides.js) wins
//   over all of the above — set it when the news has a real timeline
//   ("out 2 weeks"), clear it (delete / set null) when they're back.
// Teammate redistribution: a zeroed player's projected points are partially
// redistributed within his team position group for those weeks — QB: 85% to
// the next QB; RB/WR/TE: 60% spread proportional to the healthy group's
// projections. Redistribution scales mean AND sd together (meanScale), so
// boom/bust % for the bumped players price the bigger role.
//
// Usage: node export_site_proj.js [--repo "E:/MyFantasyFootball/MyFantasyFootball Files"] [--sims 1000]
// ============================================================================
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ARGS = process.argv.slice(2);
function argOf(flag, dflt) {
  const i = ARGS.indexOf(flag);
  return i >= 0 && ARGS[i + 1] ? ARGS[i + 1] : dflt;
}
const REPO = argOf('--repo', 'E:/MyFantasyFootball/MyFantasyFootball Files');
const SIMS = parseInt(argOf('--sims', '1000'), 10);
const OUT_JS = path.join(REPO, 'data', 'sim_proj_2026.js');
const OUT_JSON = path.join(REPO, 'data', 'sim_proj_2026.json');
const KICKOFF_CACHE = path.join(__dirname, 'data', 'kickoffs_2026.json');
const SEASON = 2026;
const WEEKS = 18;
// Test hooks (2026-09-09): --now <ISO> pretends the clock reads that instant
// (freeze merge + auto-lock), --snapdir <dir> redirects the auto-lock files.
const NOW_OVERRIDE = argOf('--now', null);
const SNAP_DIR = argOf('--snapdir', path.join(__dirname, 'data', 'snapshots'));

// ---------- load Sim Lab data + engine under a window shim ----------
global.window = global;
[
  'data/mike_clay_projections.js',
  'data/player_weekly_sigma.js',
  'data/betting_lines_2026.js',
  'data/clay_team_grades_2026.js',
  'data/sleeper_players.js',
  'data/sleeper_meta.js',
  'data/sim_snaps.js',
  'data/sim_routes.js',
  'data/sim_weather.js',
  'data/sim_practice.js',
  'data/sim_depth.js',
  'data/sim_2026.js',
  'data/pace_2026.js',
  'data/sim_tuning.js',
  'overrides.js',
  'engine.js'
].forEach(f => {
  vm.runInThisContext(fs.readFileSync(path.join(__dirname, f), 'utf8'), { filename: f });
});
const E = global.SimEngine;
if (!E) { console.error('SimEngine failed to load'); process.exit(1); }

// ---------- kickoff times (ESPN scoreboard, cached 24h) ----------
async function loadKickoffs() {
  try {
    const st = fs.statSync(KICKOFF_CACHE);
    if (Date.now() - st.mtimeMs < 24 * 3600 * 1000) {
      return JSON.parse(fs.readFileSync(KICKOFF_CACHE, 'utf8'));
    }
  } catch (_) {}
  const out = {};
  try {
    for (let wk = 1; wk <= WEEKS; wk++) {
      const url = `https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?seasontype=2&week=${wk}&dates=${SEASON}`;
      const r = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const j = await r.json();
      const wkMap = {};
      (j.events || []).forEach(ev => {
        const comp = ev.competitions && ev.competitions[0];
        if (!comp) return;
        (comp.competitors || []).forEach(c => {
          const ab = E.normTeam((c.team && c.team.abbreviation || '').toUpperCase());
          if (ab) wkMap[ab] = ev.date; // ISO kickoff
        });
      });
      if (Object.keys(wkMap).length) out[wk] = wkMap;
      await new Promise(res => setTimeout(res, 250));
    }
    fs.writeFileSync(KICKOFF_CACHE, JSON.stringify(out));
    console.log('kickoffs: fetched fresh from ESPN (' + Object.keys(out).length + ' weeks)');
    return out;
  } catch (e) {
    console.warn('kickoffs: ESPN fetch failed (' + e.message + ')');
    try { return JSON.parse(fs.readFileSync(KICKOFF_CACHE, 'utf8')); } catch (_) { return {}; }
  }
}

// Fallback week-start when no kickoff data: Thursday 8:00 PM ET of week W.
// Week 1 Thursday = 2026-09-10. ET fixed at UTC-4 (EDT covers Sep-Oct;
// Nov+ is 1h early, which only makes the freeze conservative).
function weekFallbackStart(wk) {
  return new Date(Date.UTC(2026, 8, 11, 0, 0)).getTime() + (wk - 1) * 7 * 24 * 3600 * 1000;
}

function kickoffMs(kicks, wk, tm) {
  const w = kicks[wk];
  if (w && w[tm]) return new Date(w[tm]).getTime();
  return weekFallbackStart(wk);
}

// ---------- in-season injury layer ----------
// Lives in the engine since 2026-09-09 (E.applyInSeasonInjuries / E.injAdj):
// Out/Sus -> 0, Doubtful -> x0.5, IR/PUP/NFI -> 0 for 4 weeks,
// IN_SEASON_OUT_OVERRIDES wins, vacated share redistributed within the
// team position group. Armed in main() from 4 days before the current
// week's first kickoff so game-week designations count and camp tags don't.

// ---------- main ----------
(async function main() {
  const kicks = await loadKickoffs();
  const now = NOW_OVERRIDE ? Date.parse(NOW_OVERRIDE) : Date.now();
  if (NOW_OVERRIDE) console.log('NOW override:', new Date(now).toISOString());
  const seasonStart = kickoffMs(kicks, 1, Object.keys(kicks[1] || { _: 1 })[0]) || weekFallbackStart(1);
  const seasonStarted = now >= Math.min(seasonStart, weekFallbackStart(1));
  // current week = first week whose LAST kickoff (+6h) is still in the future
  let currentWeek = 1;
  for (let wk = 1; wk <= WEEKS; wk++) {
    const w = kicks[wk];
    const last = w ? Math.max(...Object.values(w).map(d => new Date(d).getTime())) : weekFallbackStart(wk) + 4.5 * 24 * 3600 * 1000;
    if (now < last + 6 * 3600 * 1000) { currentWeek = wk; break; }
    currentWeek = wk;
  }
  console.log('season started:', seasonStarted, '| current week:', currentWeek, '| sims:', SIMS);

  const schedule = E.buildSchedule();
  const players = E.buildPlayers(schedule);
  const scH = E.PRESETS.half, scP = E.PRESETS.ppr, scS = E.PRESETS.std;
  // In-season availability + vacated opportunity now lives in the engine
  // (E.applyInSeasonInjuries — shared with the Sim Lab week sim and the
  // auto-lock). Designations count from 4 days before the current week's
  // first kickoff (game-week statuses), never for August camp tags.
  const wkFirstKick = (() => { const w = kicks[currentWeek]; return w ? Math.min(...Object.values(w).map(d => new Date(d).getTime())) : weekFallbackStart(currentWeek); })();
  const injActive = now >= wkFirstKick - 4 * 24 * 3600 * 1000;
  const injState = E.applyInSeasonInjuries(players, currentWeek, { active: injActive });
  if (injState.zeros.length) console.log('in-season injury layer (wk ' + currentWeek + ', active ' + injActive + '):', injState.zeros.map(z => z.name + ' wk' + z.from + '-' + z.to + (z.mult ? ' x' + z.mult : '') + ' [' + z.src + ']').join('; '));
  else console.log('in-season injury layer: ' + (injActive ? 'no designations' : 'inactive until ' + new Date(wkFirstKick - 4 * 24 * 3600 * 1000).toISOString()));

  // previous state for the freeze merge
  let prev = null;
  try { prev = JSON.parse(fs.readFileSync(OUT_JSON, 'utf8')); } catch (_) {}

  const weeksOut = {};
  const teamOf = {};
  const round1 = v => Math.round(v * 10) / 10;
  // Sim season PPG per format: mean of the player's weekly sim means across
  // his playable weeks (QB-window backups average over their starts only).
  // Feeds the rankings PROJ PPG column — a projection, so always fresh
  // (injury-zeroed weeks are excluded; absence risk lives in seasonSim).
  const seasonAgg = {};

  for (let wk = 1; wk <= WEEKS; wk++) {
    const rows = {};
    // per-player weekly projections in all three formats
    const pool = [];
    players.list.forEach(p => {
      const wpH = E.weeklyProjection(p, wk, scH, schedule);
      if (!wpH) return;
      // Zeroed by the engine's injury layer: keep an explicit 0 row so the
      // site's PROJ reads 0 (a missing row would fall back to consensus).
      if (!p.isDST && E.injAdj(p, wk) === 0) {
        const zkey = p.name;
        rows[zkey] = [0, 0, 0, null, null];
        teamOf[zkey] = p.tm;
        return;
      }
      const mH = E.effMean(wpH);
      if (!(mH > (p.isDST ? 0 : 0.4))) return;
      const wpP = E.weeklyProjection(p, wk, scP, schedule);
      const wpS = E.weeklyProjection(p, wk, scS, schedule);
      pool.push({
        p, wpH,
        mH, mP: wpP ? E.effMean(wpP) : mH, mS: wpS ? E.effMean(wpS) : mH,
        adj: 1 // availability/redistribution already inside the projection (engine injAdj)
      });
    });

    // Monte Carlo (half frame, correlated env, deterministic seed per week).
    // Boom/bust are MEDIAN-RELATIVE (Jack's spec 2026-08-26): boom = share of
    // draws >= 150% of the player's own median outcome that week, bust =
    // share <= 50% of it — a per-player volatility read (steady QBs low on
    // both; wide-range TEs/DSTs high on both), not a positional bar.
    const BOOM_MULT = 1.5, BUST_MULT = 0.5;
    const rng = E.makeRng(20260000 + wk);
    const games = schedule.byWeek[wk] || [];
    const draws = pool.map(r => r.adj > 0 ? new Float64Array(SIMS) : null);
    for (let s = 0; s < SIMS; s++) {
      const env = E.drawWeekEnv(games, rng, players);
      for (let i = 0; i < pool.length; i++) {
        const r = pool[i];
        if (r.adj <= 0) continue;
        draws[i][s] = E.samplePlayerScore(r.p, r.wpH, env, rng, r.adj);
      }
    }

    pool.forEach((r, i) => {
      const key = r.p.isDST ? 'DST_' + r.p.tm : r.p.name;
      teamOf[key] = r.p.tm;
      // REST-OF-SEASON only (Jack's spec): in week 5 the PPG is the mean of
      // weeks 5-18, not the games already played. Preseason = all weeks.
      if (wk >= currentWeek) {
        const ag = seasonAgg[key] || (seasonAgg[key] = { h: 0, p: 0, s: 0, n: 0 });
        ag.h += r.mH; ag.p += r.mP; ag.s += r.mS; ag.n++;
      }
      if (r.adj <= 0) { rows[key] = [0, 0, 0, null, null]; return; }
      const a = draws[i].sort();
      const med = a[Math.floor(SIMS / 2)];
      let boomN = 0, bustN = 0;
      if (med > 0) {
        const hi = med * BOOM_MULT, lo = med * BUST_MULT;
        for (let s = 0; s < SIMS; s++) {
          if (a[s] >= hi) boomN++;
          if (a[s] <= lo) bustN++;
        }
      }
      rows[key] = [
        round1(r.mH * r.adj), round1(r.mP * r.adj), round1(r.mS * r.adj),
        Math.round(100 * boomN / SIMS), Math.round(100 * bustN / SIMS)
      ];
    });

    // freeze merge: teams whose week-wk kickoff has passed keep previous rows
    if (prev && prev.weeks && prev.weeks[wk]) {
      const prevRows = prev.weeks[wk];
      const prevTeam = prev.teamOf || {};
      let frozen = 0;
      Object.keys(prevRows).forEach(key => {
        const tm = prevTeam[key] || teamOf[key];
        if (!tm) return;
        if (now >= kickoffMs(kicks, wk, tm)) {
          rows[key] = prevRows[key];
          teamOf[key] = tm;
          frozen++;
        }
      });
      if (frozen) console.log('wk ' + wk + ': ' + frozen + ' rows frozen (games started)');
    }

    weeksOut[wk] = rows;
    if (wk === 1 || wk === WEEKS) console.log('wk ' + wk + ': ' + Object.keys(rows).length + ' players');
  }

  // ---------- AUTO PER-GAME LOCK (Sim Lab tracking snapshots, 2026-09-09) ----------
  // Mirrors the Sim Lab UI's "Lock" button (app.js lockGames): for every
  // current-week game that has kicked off or kicks off within LOCK_LEAD_MIN,
  // freeze the week sim's per-player rows (mean / p10 / p50 / p90, Clay / JS /
  // prop-anchor means, stat comps, the prop lines on the board) into
  //   data/snapshots/simlab_snapshot_w<wk>.json   (+ index.json listing weeks)
  // — the same shape the UI downloads — so the TRACKING tab can grade the
  // week after the games without anyone clicking Lock. A game already in the
  // file is never re-locked. The pre-kickoff export runs (~35 min before
  // every kickoff slot) make this fire once per game on the freshest lines;
  // sim_proj_task.ps1 redeploys Sim Lab whenever a snapshot file changed and
  // the UI merges the files into its localStorage snapshots on boot.
  try {
    const LOCK_LEAD_MIN = 75;
    const snapDir = SNAP_DIR;
    const lwk = currentWeek;
    const lgames = schedule.byWeek[lwk] || [];
    const due = lgames.filter(g => {
      const k = Math.min(kickoffMs(kicks, lwk, g.home) || Infinity, kickoffMs(kicks, lwk, g.away) || Infinity);
      return isFinite(k) && now >= k - LOCK_LEAD_MIN * 60000;
    });
    const snapPath = path.join(snapDir, 'simlab_snapshot_w' + lwk + '.json');
    let snap = null;
    try { snap = JSON.parse(fs.readFileSync(snapPath, 'utf8')); } catch (_) {}
    if (!snap || typeof snap !== 'object') snap = { week: lwk, season: SEASON, preset: 'half', sims: 2000, lockedGames: {}, players: [], auto: true };
    snap.lockedGames = snap.lockedGames || {};
    snap.players = snap.players || [];
    const todo = due.map(g => g.key).filter(k => !snap.lockedGames[k]);
    if (todo.length) {
      const lockSc = E.PRESETS[snap.preset] || scH;
      const lres = E.simWeek({ week: lwk, sims: snap.sims || 2000, scoring: lockSc, schedule, players, seed: 20261000 + lwk });
      const lprops = (global.BETTING_2026 && global.BETTING_2026.weeklyProps && global.BETTING_2026.weeklyProps[String(lwk)]) || {};
      const propByNorm = {};
      Object.keys(lprops).forEach(nm => { propByNorm[E.norm(nm)] = lprops[nm]; });
      const nowIso = new Date(now).toISOString();
      let added = 0;
      lres.forEach(r => {
        if (todo.indexOf(r.slot.gameKey) < 0) return;
        if (!(r.mean >= 2 || propByNorm[r.player.norm])) return;
        snap.players.push({
          name: r.player.name, sid: r.player.sid, pos: r.player.pos, tm: r.player.tm,
          opp: r.slot.opp, implied: +r.slot.implied.toFixed(1), game: r.slot.gameKey, lockedAt: nowIso,
          mean: +r.mean.toFixed(2), p10: +r.p10.toFixed(2), p50: +r.p50.toFixed(2), p90: +r.p90.toFixed(2),
          jsMean: r.jsProj != null ? +r.jsProj.toFixed(2) : null,
          clayMean: r.proj != null ? +r.proj.toFixed(2) : null,
          propMean: r.propProj != null ? +r.propProj.toFixed(2) : null,
          propSrc: r.propSrc || null,
          luck: r.luck != null ? +r.luck.toFixed(3) : 0,   // TD-luck points inside jsMean at lock (luck_scorecard.py grades the layer live)
          comps: r.comps, lines: propByNorm[r.player.norm] || null,
          // tuner values LIVE at lock (tune_weekly.py divides them back out so
          // next week's evidence is measured against the raw prior)
          tun: global.SIM_TUNING ? {
            wa: r.propW != null ? +r.propW.toFixed(3) : undefined,   // market weight actually applied (belowW may differ from propW)
            w: (global.SIM_TUNING.propW || {})[r.player.pos], s: (global.SIM_TUNING.sigmaMult || {})[r.player.pos],
            td: (global.SIM_TUNING.tdMult || {})[r.player.pos] || null,
            k: r.player.pos === 'K' ? global.SIM_TUNING.kLevel : undefined,
            d: r.player.pos === 'DST' ? global.SIM_TUNING.dstShift : undefined, asOf: global.SIM_TUNING.asOf
          } : null
        });
        added++;
      });
      todo.forEach(k => { snap.lockedGames[k] = nowIso; });
      snap.lockedAt = snap.lockedAt || nowIso;
      snap.auto = true;
      fs.mkdirSync(snapDir, { recursive: true });
      fs.writeFileSync(snapPath, JSON.stringify(snap));
      const idxPath = path.join(snapDir, 'index.json');
      let idx = null;
      try { idx = JSON.parse(fs.readFileSync(idxPath, 'utf8')); } catch (_) {}
      if (!idx || !Array.isArray(idx.weeks)) idx = { weeks: [] };
      if (idx.weeks.indexOf(lwk) < 0) idx.weeks.push(lwk);
      idx.weeks.sort((a, b) => a - b);
      idx.updated = nowIso;
      fs.writeFileSync(idxPath, JSON.stringify(idx));
      console.log('auto-lock wk ' + lwk + ': ' + todo.join(', ') + ' (' + added + ' player rows) -> ' + path.basename(snapPath));
    } else {
      console.log('auto-lock wk ' + lwk + ': nothing due (' + Object.keys(snap.lockedGames).length + '/' + lgames.length + ' games locked)');
    }
  } catch (e) { console.warn('auto-lock skipped: ' + e.message); }

  // Full-season sim (season shock + games-played layers): per-player median /
  // floor(p10) / ceiling(p90) season totals (half frame), median-relative
  // season boom/bust (+/-25% of own median), and top-12 positional finish
  // odds. Always recomputed fresh — no per-game freeze semantics apply.
  console.log('season sim (400 seasons)...');
  const seasonRes = E.simSeason({ schedule, players, sims: 400, seed: 20269999, scoring: scH });
  const seasonSim = {};
  const pc = v => v != null ? Math.round(100 * v) : null;
  seasonRes.forEach(r => {
    const key = r.player.isDST ? 'DST_' + r.player.tm : r.player.name;
    seasonSim[key] = [
      Math.round(r.p50), Math.round(r.p10), Math.round(r.p90),
      pc(r.seasonBoom), pc(r.seasonBust), pc(r.top12), r.games
    ];
  });
  console.log('season sim: ' + Object.keys(seasonSim).length + ' players');

  const seasonPpg = {};
  Object.keys(seasonAgg).forEach(key => {
    const ag = seasonAgg[key];
    if (ag.n > 0) seasonPpg[key] = [round1(ag.h / ag.n), round1(ag.p / ag.n), round1(ag.s / ag.n)];
  });

  // Original (preseason) PPG — tracks seasonPpg until the season's first
  // kickoff, then frozen forever: the "what we said before Week 1" baseline
  // for the in-season accuracy tracking.
  const baselinePpg = (seasonStarted && prev && prev.baselinePpg) ? prev.baselinePpg : seasonPpg;

  // LIVE in-game remaining model (backtest_live_remaining.py -> data/live_model.json):
  // per-position-class [a, b, m] over the game-fraction grid. The helpers'
  // live projections read it off this export; absent file = helpers keep
  // their built-in heuristic.
  let liveModel = null;
  try {
    const lmPath = path.join(__dirname, 'data', 'live_model.json');
    if (fs.existsSync(lmPath)) {
      const lm = JSON.parse(fs.readFileSync(lmPath, 'utf8'));
      if (lm && lm.grid && lm.pos) liveModel = { version: lm.version, built: lm.built, grid: lm.grid, pos: lm.pos, form: lm.form,
        liveVar: lm.liveVar || null,    // v3: win-odds variance table (backtest_live_variance.py)
        liveCorr: lm.liveCorr || null }; // v4: same-game correlation table (backtest_live_corr.py)
    }
  } catch (e) { console.warn('live_model.json skipped: ' + e.message); }

  // TD / FG luck for the site's player card (2026-09-15): season-to-date
  // expected TDs from touch locations vs actual (RB/WR/TE/QB) with the points
  // the engine's tdLuckAdj adds to THIS week's half-PPR mean; kickers carry
  // expected-vs-actual kicking points (intel only, no adjustment). Maps come
  // from sim_routes.js (pull_pace_tracker.py). Row = [pos, expected, actual, g, adjHalf|null].
  const luck = {};
  (players.list || []).forEach(p => {
    if (p.isDST) return;
    if (p.pos === 'QB' || p.pos === 'RB' || p.pos === 'WR' || p.pos === 'TE') {
      const m = p.pos === 'QB' ? global.SIM_QB_TDLUCK_2026 : (p.pos === 'RB' ? global.SIM_RB_TDLUCK_2026 : global.SIM_REC_TDLUCK_2026);
      const r = m && m[p.norm];
      if (r && r.g) luck[p.name] = [p.pos, +(+r.xtd).toFixed(2), r.td, r.g, +E.tdLuckAdj(p, scH).toFixed(2), r.w || null];   // [5] = {wk: [xtd, td]} for the card's xFP column
    } else if (p.pos === 'K') {
      const r = global.SIM_K_LUCK_2026 && global.SIM_K_LUCK_2026[p.norm];
      if (r && r.g) luck[p.name] = ['K', +(+r.xpts).toFixed(1), r.pts, r.g, null];
    }
  });
  console.log('luck rows for the card: ' + Object.keys(luck).length);
  // Standard expected-fantasy-point components per game (SIM_XFP_2026, pull_pace_tracker.py):
  // RB/WR/TE [tg, xrec, xrecyd, xrectd, car, xruyd, xrutd]; QB [att, xpyd, xptd, car, xruyd, xrutd].
  // Board players only, keyed like the weeks rows; the site scores them in the viewer's format.
  const xfp = {};
  const XM = global.SIM_XFP_2026 || {};
  (players.list || []).forEach(p => { if (!p.isDST && XM[p.norm] && XM[p.norm].w) xfp[p.name] = XM[p.norm].w; });
  console.log('xFP rows for the card: ' + Object.keys(xfp).length);

  const payload = {
    updated: new Date().toISOString(),
    season: SEASON,
    sims: SIMS,
    currentWeek: currentWeek,
    liveModel: liveModel,
    boomBust: { basis: 'median', boomMult: 1.5, bustMult: 0.5 },
    seasonBoomBust: { basis: 'median', boomMult: 1.25, bustMult: 0.75, sims: 400 },
    weeks: weeksOut,
    seasonSim: seasonSim,
    seasonPpg: seasonPpg,
    baselinePpg: baselinePpg,
    teamOf: teamOf,
    luck: luck,
    xfp: xfp
  };
  fs.writeFileSync(OUT_JSON, JSON.stringify(payload));
  const jsHeader =
    '// Auto-generated by sim_lab/export_site_proj.js — do not hand-edit.\n' +
    '// Per-week Sim Lab projections + boom/bust % for the 2026 LOGS view.\n' +
    '// weeks[wk][name] = [half, ppr, std, boom%, bust%]; DST keyed DST_<abbr>.\n' +
    '// Rows for teams whose game already kicked off are FROZEN at their\n' +
    '// pre-kickoff values by the exporter (never recomputed).\n' +
    '// luck[name] = [pos, expectedTD|expectedKickPts, actual, games, adjThisWeekHalf|null, weekly xtd/td map|null] (card TD/FG LUCK box).\n' +
    '// xfp[name][wk] = expected components: RB/WR/TE tg,xrec,xrecyd,xrectd,car,xruyd,xrutd; QB att,xpyd,xptd,car,xruyd,xrutd (card xFP column).\n';
  fs.writeFileSync(OUT_JS, jsHeader + 'window.SIM_PROJ_2026 = ' + JSON.stringify(payload) + ';\n');
  const kb = Math.round(fs.statSync(OUT_JS).size / 1024);
  console.log('wrote ' + OUT_JS + ' (' + kb + ' KB)');
})().catch(e => { console.error(e); process.exit(1); });
