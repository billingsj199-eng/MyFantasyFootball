// Per-layer live effect: switch one layer off, recompute the model number (PPR, before the book anchor), report who moves and how much.
const fs = require('fs'), path = require('path'), vm = require('vm');
global.window = global;
['data/mike_clay_projections.js','data/player_weekly_sigma.js','data/betting_lines_2026.js','data/sim_future_totals.js','data/clay_team_grades_2026.js','data/sleeper_players.js','data/sleeper_meta.js','data/ridge_prior.js','data/jm_scores.js','data/sim_snaps.js','data/sim_routes.js','data/sim_weather.js','data/sim_practice.js','data/sim_injury_signals.js','data/sim_news.js','data/sim_context.js','data/opp_prior_2026.js','data/learned_shadow_model.js','data/sim_depth.js','data/sim_2026.js','data/sim_actuals_2026.js','data/pace_2026.js','data/sim_tuning.js','data/sim_prior_health.js','overrides.js','engine.js'].forEach(f => vm.runInThisContext(fs.readFileSync(path.join(__dirname, f), 'utf8'), { filename: f }));
const E = global.SimEngine, schedule = E.buildSchedule(), players = E.buildPlayers(schedule), sc = E.PRESETS.ppr;
global.SIM_PROP_ANCHOR = false;
const LAYERS = [
  ['PLAYER', 'SIM_SHADOW_OPP', 'opportunity prior (preseason projected share x team volume)'], ['MATCHUP', 'SIM_NC_VEGEV', 'Vegas implied total'], ['MATCHUP', 'SIM_NC_TOTAL', 'QB shootout tilt (game total)'],
  ['MATCHUP', 'SIM_WEATHER', 'weather (wind / rain / cold)'], ['MATCHUP', 'SIM_CB_DOCK', 'shadow CB coverage'], ['MATCHUP', 'SIM_CB1_BOOST', "opponent's CB1 out"],
  ['MATCHUP', 'SIM_OL_DOCK', 'own O-line starters out'], ['MATCHUP', 'SIM_PRESSURE_BOOST', 'opponent pass-rush pressure'], ['MATCHUP', 'SIM_BLOWOUT_CTX', 'blowout / garbage-time context'],
  ['TEAM', 'SIM_NC_VOL', 'team pass volume vs script (+ underdog att)'], ['TEAM', 'SIM_BOX_CTX', 'defenders in the box faced'],
  ['ROLE', 'SIM_NC_USAGE', 'usage evidence (targets / xFP / routes)'], ['ROLE', 'SIM_NC_DEPTH', 'depth-chart string docks'], ['ROLE', 'SIM_PECK_DOCK', 'pecking order (WR3 / RB2)'],
  ['ROLE', 'SIM_NC_TE_DOCKS', 'TE snap docks at half strength'], ['ROLE', 'SIM_NC_ELITE_TREND', 'no RB snap-trend dock for top-30'], ['ROLE', 'SIM_NC_BLOW', 'RB snap dip excused after a blowout'],
  ['ROLE', 'SIM_NC_PRUNE', 'WR snap trend removed'], ['ROLE', 'SIM_ROUTE_TREND', 'route-share trend'],
  ['TEAMMATES', 'SIM_NC_EXACT', 'vacated targets / carries (pool)'], ['TEAMMATES', 'SIM_NMU', 'next man up (rank cells)'], ['TEAMMATES', 'SIM_NC_QBOUT', 'backup QB dock on WRs'],
  ['TEAMMATES', 'SIM_NC_MULTI_ABS', 'multi-absence split'], ['TEAMMATES', 'SIM_FILLIN', 'fill-in games rescaled'], ['TEAMMATES', 'SIM_NC_QBMAX', 'QB fill-in = max(own, 85% starter)'],
  ['HEALTH', 'SIM_HEALTH_PRIOR', 'banged-up prior (healthy-game lift)'], ['HEALTH', 'SIM_HURT_USAGE', 'hurt games down-weighted in usage'], ['HEALTH', 'SIM_RETURN_RAMP', 'first games back from injury'],
  ['HEALTH', 'SIM_BANGED', 'Questionable / Doubtful dock by practice'], ['HEALTH', 'SIM_NEWS_WINDOWS', 'news-reported timelines'],
  ['PLAYER', 'SIM_TD_LUCK', 'TD luck regression'], ['PLAYER', 'SIM_QB_FLOOR', 'QB rushing floor'], ['PLAYER', 'SIM_NC_RIDGE', 'ridge career prior'], ['PLAYER', 'SIM_SHADOW_AGE', 'age / experience curve'],
  ['PLAYER', 'SIM_NC_YR2', 'second-year bump'], ['PLAYER', 'SIM_ROOKIE_LEVEL', 'rookie level by draft capital'], ['PLAYER', 'SIM_NC_VETDOCK', 'demoted veteran dock'], ['PLAYER', 'SIM_NC_ELITE', 'elite protection'],
  ['ROS', 'SIM_NC_TE_TDFLOOR', 'TE touchdown floor (later weeks)'], ['ROS', 'SIM_ROS_TILT', 'rest-of-season volume tilt'], ['ROS', 'SIM_NC_ROS', 'RB snap trend carried forward'], ['ROS', 'SIM_AVAIL_CURVE', 'availability curve after an absence'],
];
function run(wk) {
  E.applyInSeasonInjuries(players, 5, { active: true });
  const out = {};
  players.list.forEach(p => { if (p.isDST || p.pos === 'K') return; const w = E.weeklyProjection(p, wk, sc, schedule); if (w) out[p.name] = [E.effMean(w), p.pos, p.tm, p.adp]; });
  return out;
}
const res = [];
for (const wk of [5, 8]) {
  const base = run(wk);
  const top = Object.keys(base).filter(n => base[n][0] >= 5);
  for (const [grp, sw, lab] of LAYERS) {
    if (wk === 8 && grp !== 'ROS') continue;
    if (wk === 5 && grp === 'ROS') continue;
    global[sw] = false; const alt = run(wk); delete global[sw];
    const mv = top.map(n => [n, base[n][0] - (alt[n] ? alt[n][0] : base[n][0]), base[n]]).filter(x => Math.abs(x[1]) >= 0.1);
    mv.sort((a, b) => b[1] - a[1]);
    res.push({ wk, grp, sw, lab, n: mv.length, of: top.length, up: mv.filter(x => x[1] > 0).length, dn: mv.filter(x => x[1] < 0).length,
      avg: mv.length ? mv.reduce((s, x) => s + Math.abs(x[1]), 0) / mv.length : 0,
      plus: mv.slice(0, 3).map(x => x[0] + ' ' + (x[1] > 0 ? '+' : '') + x[1].toFixed(1)), minus: mv.slice(-3).reverse().filter(x => x[1] < 0).map(x => x[0] + ' ' + x[1].toFixed(1)) });
  }
}
fs.writeFileSync(path.join(__dirname, 'layer_effects_w5.json'), JSON.stringify(res, null, 1));
res.forEach(r => console.log(`W${r.wk} ${r.grp.padEnd(9)} ${r.lab.padEnd(44)} moved ${String(r.n).padStart(3)}/${r.of} (+${r.up} / -${r.dn}) avg ${r.avg.toFixed(2)} | ${r.plus.join(', ')} || ${r.minus.join(', ')}`));
