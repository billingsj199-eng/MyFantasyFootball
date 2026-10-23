// DX-STRICT live check (2026-10-20): which players' injury windows change when INJURY SIGNALS 4 requires a tear
// signal (window.SIM_DX_STRICT, default on) vs the old body-part-only rule (SIM_DX_STRICT = false).
// Also runs with the manual Mike Evans override removed, to show the rule alone no longer ends his season.
// Usage: node check_dx_strict.js [week]
const fs = require('fs'), path = require('path'), vm = require('vm');
global.window = global;
['data/mike_clay_projections.js','data/player_weekly_sigma.js','data/betting_lines_2026.js','data/sim_future_totals.js','data/clay_team_grades_2026.js','data/sleeper_players.js','data/sleeper_meta.js','data/ridge_prior.js','data/jm_scores.js','data/sim_snaps.js','data/sim_routes.js','data/sim_weather.js','data/sim_practice.js','data/sim_injury_signals.js','data/sim_news.js','data/sim_context.js','data/opp_prior_2026.js','data/learned_shadow_model.js','data/sim_depth.js','data/sim_2026.js','data/sim_actuals_2026.js','data/pace_2026.js','data/sim_tuning.js','data/sim_prior_health.js','overrides.js','engine.js'].forEach(f => vm.runInThisContext(fs.readFileSync(path.join(__dirname, f), 'utf8'), { filename: f }));
const E = global.SimEngine, schedule = E.buildSchedule(), players = E.buildPlayers(schedule);
const wk = +(process.argv[2] || (global.SIM_INJ_SIGNALS && global.SIM_INJ_SIGNALS.week) || 7);
const run = () => {
  const s = E.applyInSeasonInjuries(players, wk, { active: true });
  const m = {};
  s.zeros.forEach(z => { m[z.name] = z.src + ' wk' + z.from + '-' + z.to + (z.mult ? ' x' + z.mult : ''); });
  return m;
};
const diff = (a, b, label) => {
  const names = [...new Set([...Object.keys(a), ...Object.keys(b)])].filter(n => a[n] !== b[n]).sort();
  console.log('\n== ' + label + ': ' + names.length + ' change(s)');
  names.forEach(n => console.log('  ' + n.padEnd(24) + (a[n] || '(none)').padEnd(34) + ' -> ' + (b[n] || '(none)')));
};
global.SIM_DX_STRICT = false; const oldR = run();
global.SIM_DX_STRICT = true; const newR = run();
diff(oldR, newR, 'week ' + wk + ': old rule -> strict rule (overrides as filed)');
const ov = global.IN_SEASON_OUT_OVERRIDES, keep = ov['Mike Evans']; delete ov['Mike Evans'];
global.SIM_DX_STRICT = false; const oldN = run();
global.SIM_DX_STRICT = true; const newN = run();
ov['Mike Evans'] = keep;
diff(oldN, newN, 'week ' + wk + ': same, WITHOUT the manual Mike Evans override');
const dx = Object.entries(newR).filter(([, v]) => /^dx-season/.test(v)).map(([n]) => n);
console.log('\nstill season-ending by diagnosis under the strict rule (' + dx.length + '): ' + dx.join(', '));
