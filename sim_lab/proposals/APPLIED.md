

## P-20261013-2 - Fade the vacancy boost in LATER weeks by games already played without the absent regular
- What: shadow vacancy gain for weeks after the current one x f, f = max(0, 1 - seen / 4), seen = games this player already played
  on this team while the absent regular (largest absent share) sat. Current week unchanged.
- File / knob: engine.js shadow vacx gain (and live pool iA > 1 part) for wk > _inj.week; new NC_SHADOW.next.vacSeenFade 4.
- Evidence (research_volume_budget_c.py, volume_budget_c.log part C2; ROS harness, 4+ games left): -0.63% (6/7, fwd 3/4);
  LOYO across fades -0.56% (6/7), forward -0.34% (3/4), MAE -0.40%, rank .6287 -> .6317. Pool rows by seen games, ROS act/proj:
  seen 0 1.014, 1 1.004, 2 0.981, 3-4 0.958, 5+ 0.961 (RB 0.896). NEXT GAME the fade FAILS (LOYO keeps the boost 5/7) -
  do not apply to the current week.
- Caveat: harness ROS carries the next-week boost flat; the engine already decays absences with the availability curve, so the
  live effect is smaller - re-grade on the engine form. Confidence: medium. Expiry: 2026-11-10.
- APPLIED 2026-10-13 (Jack approved). ENGINE-FORM RE-GRADE (research_vacfade_ctx_regrade.py, vacfade_ctx_regrade_p2*.log): per-future-week
  availability, 4,665 rest-of-season checkpoints. All positions c 4: -0.48% (6/7, fwd 4/4) but TE alone FAILS (+0.39%, 3/7, fwd 1/4) ->
  shipped RB / WR only: -0.52% (6/7, fwd 4/4), affected checkpoints -1.54% (6/7, 4/4), LOYO -0.52% (5/7) fwd -0.47% (3/4).
  Folds (RB/WR, c 4): 2019 +0.07 | 2020 -0.27 | 2021 -1.35 | 2022 -1.97 | 2023 -0.34 | 2024 -0.01 | 2025 -0.26 (%).
  LOSING SEASON 2019 (+0.07%): James Washington PIT wk10-12 (JuJu out; 2nd-year WR kept growing into the role, seen 5),
  Miles Sanders PHI wk12 (rookie, took Jordan Howard's job for good), Anthony Miller CHI wk12 (2nd-year, Gabriel out), McCaffrey wk9
  (tiny). Pattern = young players who WIN the job during the absence (consistent with project_injury_volume_persist: organic /
  young job winners keep it) - possible exemption for rookies / 2nd-year absorbers; n small, mostly noise at +0.07%.
  Wired: engine.js VAC_FADE {c 4, RB/WR} + vacFadeF(); faded per absent teammate (seen = his 2026 games before the current week
  without that teammate; only teammates with 1+ game); current week untouched; tag +vfadeN; why.vfade / vfadeSeen; app.js ntWhy
  step 'vfade' split out of the blend step (sum unchanged) + NOTES chip. Kill window.SIM_NC_VACFADE = false.
  Backups engine.js / app.js .bak_pre_vacfade_20261013. W6 headless: 237 later-week player-weeks / 63 players move, current week
  0 (parity with the pre-change engine on all 423 W6 rows); Kamara W7 10.25 -> 9.05, Ollie Gordon -1.0/wk, E. Wilson W7 -0.9,
  Miller W7 6.38 -> 5.82, Donaldson 2.21 -> 1.99.

## P-20261014-1 - TreVeyon Henderson (NE RB) out-window W6-W7, soft return by W9 (NEWS)
- What: add an IN_SEASON_OUT_OVERRIDES entry so the sim stops treating his stale W5 "Ankle, Out" tag as a one-week x0.75 and
  returns him at full strength W7.
- File / knob: sim_lab/overrides.js IN_SEASON_OUT_OVERRIDES -> `'TreVeyon Henderson': [6, 7, '2026-10-12', 9],` (high ankle,
  Schefter "multiple weeks", no surgery). Group redistribution (RB 60%) goes to Stevenson / Kiner automatically.
- Size (current export 2026-10-13 14:05Z): W6 5.9 -> 0, W7 8.4 -> 0, W8 9.3 -> ~4.7 (50% landing), W9 9.2 -> ~8.3 (90%).
  Teammates W7 rise (Stevenson 11.4 today assumes Henderson back).
- Evidence: news 2026-10-12 Schefter via camp_news ("high ankle sprain ... will cost him 'multiple weeks'; no surgery needed");
  the feed did NOT tag it (avail = none), so build_injury_signals has no window. Sim row: inj src out-unconfirmed m .75 for W6
  only (Sleeper W6 proj h 6.0 still present, so the out-flag guard correctly refused to zero). W5 usage confirms in-game injury:
  4 carries / 1 target vs 8-16 carries W2-4. Hit rate: timeline windows played 8% (news_status.log, 5/62) -> zero inside the
  window is the right size; "multiple weeks" = at least 2 games, high-ankle no-surgery typically 2-4 -> latest expected W9.
- Confidence: high (insider timeline + usage). Expiry: 2026-10-18 (W6 kickoff Sunday) - if not applied by then, re-size as [7,7,...].
- APPLIED 2026-10-14 (Jack "approve P-20261014-1"): overrides.js entry added (backup overrides.js.bak_pre_henderson_20261014). Dry-run export: W6 5.9->0, W7 8.4->0, W8 9.3->4.1, W9 9.2->8.1; Stevenson W7 11.4->13.4. NOT YET LIVE: shared checkout stuck mid-rebase since 10-13 15:50, all automation pushes failing.

## P-20261014-2 - Out-unconfirmed level: tier it (0 near kickoff / .50 lingering / .20 new) instead of flat x0.75
- What: the engine prices a Sleeper "Out" that Sleeper still projects and the NFL report hasn't called Out/Doubtful at
  x0.75 ('out-unconfirmed', feedback_out_flag_guard). Measured, that state played 34% of the time, and it is really three states:
  (a) within 36 h of HIS kickoff -> 0 (this is the gameday inactive list: Sleeper tags Out ~90 min before kickoff before it
      pulls his projection, so the pre-kickoff export FROZE x0.75 rows for inactives - Puka Nacua W2, Keenan Allen W4,
      Addison + Dowdle W5);
  (b) earlier in the week, he MISSED his previous game (Out lingering from last week) -> 0.50;
  (c) earlier in the week, he PLAYED his previous game (new injury, Sleeper tagged Out after it) -> 0.20.
  Teammates follow automatically (vacancy = 1 - level, since the 10-14 shadowOut fix).
- File / knob: engine.js applyInSeasonInjuries `out-unconfirmed` branch (~3115): mult from hours-to-kickoff (kickoffs are in the
  exporter; engine needs them passed or read from SIM kick data) + played-previous-game (jsData wks / sim_2026). Keep the src
  name + NOTES chip; add the tier to the chip text. Same for 'na-unconfirmed'? (not measured - leave).
- Evidence (research_out_unconfirmed.py, _tmp/out_unconfirmed.log; every committed Sleeper injury snapshot 09-01..10-14 x weekly
  Sleeper proj x NFL practice report, W1-W5 graded on snap counts): 115 player-weeks / 298 export-time states.
    <36 h before kickoff: 0 / 43 played (CI 0-.08)        36-96 h: 0 / 4
    >96 h, missed previous game: 37 / 69 = .54 (CI .42-.65)   >96 h, played previous game: 2 / 11 = .18 (CI .05-.48)
  Brier (state level): flat .75 (live) .386 | flat .33 .229 | tiered .50/.10/0 .178.
  Leave-one-week-out (rates fit on the other weeks, late tier 0): tiered beats flat .75 in 5/5 weeks, pooled .180 vs .386;
  fitted rates stable: lingering .49-.53, new injury .14-.25.
- Not graded: projection POINTS (only availability). Small cells: new-injury n=11. 2026 only (Sleeper tag history doesn't exist
  for older seasons).
- Confidence: high for (a) and for dropping .75; medium for the exact .50 / .20. Note (a) zeroes a player before an NFL "Out"
  - but the inactive list IS out; this is Jack's never-zero-before-Out rule, so his call. Expiry: 2026-12-31.
- APPLIED 2026-10-14 (Jack "approve P-20261014-2"): engine.js out-unconfirmed branch -> 'out-gameday' x0 within 36 h of his kickoff
  (needs window.SIM_KICKOFFS_2026 + SIM_NOW_MS, set by export_site_proj.js), else x.50 missed last game / x.20 played last game
  (sim_2026 wks, bye = missed). Kill SIM_OUTUNCONF_TIERS = false. NOTES chip shows the tier. Backups *.bak_pre_outtiers_20261014
  (engine, exporter, app). Harness check W6: Taylor 16.8 -> 3.4 (Wed) / 0 (Sun 12pm), D. Smith 10.8 -> 5.4 / 0, McGowan 2.2 ->
  5.6 / 6.7. Helpers synced: Sleeper 0.29.47, ESPN 0.20.58, Yahoo 0.9.48. simlab-backup 023198b; Sim Lab redeployed.

## P-20261023-1 -  Vegas layer: price the GAME deviation, drop the standing TEAM tilt after week 1

**What changes (engine.js):**
- `vegasMult(implied, avgImplied, pos)` -> `vegasMult(implied, avgImplied, pos, teamAvg)` with
  `m = 1 + e'[pos] x (implied - teamAvg) / avgImplied`, clip .7-1.35 (unchanged clip).
- `teamAvg` = walk-forward mean of this team's `bookImplied` over PLAYED weeks (w < current week), shrunk 2 games toward
  `avgImplied`: `teamAvg = (sum(played implied) + 2 x avgImplied) / (nPlayed + 2)`. Week 1 (no played games) = `avgImplied`,
  i.e. identical to today. Same `teamAvg` for every future week of that team (ROS weeks use the re-rated future implied minus it).
- `VEGAS_ELAS`: QB .25 -> .50, WR .25 -> .375, TE .25 -> .375, RB .50 (unchanged), K .50 (unchanged, untested).
- `wp.why` / ntWhy: the Vegas line split into "team level (already in base)" = 0 after week 1 and "game vs team avg" = the new
  factor; `ntPlayerChips` chip "VEG game +x%" on NOTES. Waterfall still sums (single multiplicative factor replaces the old one).
- Kill switch suggestion: `window.SIM_VEGAS_SPLIT = false` -> old form.

**Why (research_matchup_swing_calibration.py, calibration regression act - baseline = a + b x swing, top-150, final week out):**
- The weekly swing as a whole is over-moved (b 0.78 [0.62, 0.92], 2019-25; 0.78 on 2012-25) but by the WRONG part: split the
  Vegas swing into TEAM level (team's season avg implied vs league) and GAME deviation (this game vs the team's own avg):
  b GAME = 1.35 [1.08, 1.56] (QB 2.26, RB 1.01, WR 1.51, TE 1.83), b TEAM = -0.29 [-0.62, 0.03] (RB -0.39).
  The base (season-to-date PPG + history) already carries the team's scoring level; adding the league-relative tilt every week
  double counts it, while the true matchup move is ~35% too small (QB ~2x).
- On the shipped Clay-blend base the same: b GAME 1.29 [1.07, 1.50], b TEAM -0.46 [-0.72, -0.17].
- 2026 W1-6 locks (736 top-150 rows): b 1.58 [0.96, 2.17] - conservative this season, consistent with wk 1-4 history (b 1.15).

**Backtest (LOYO, top-150 by preseason ADP, next game, 2019-25; nothing fitted - round elasticities):**

| fold | MAE shipped -> split | top-60 MAE | rank rho | MSE |
|---|---|---|---|---|
| 2019 | 5.693 -> 5.668 (-0.42%) | -0.37% | .3973 -> .4042 (+.0069) | -0.61% |
| 2020 | 5.676 -> 5.660 (-0.30%) | -0.67% | .4076 -> .4150 (+.0073) | -0.55% |
| 2021 | 5.630 -> 5.610 (-0.35%) | -0.53% | .3895 -> .3875 (-.0021) | -0.30% |
| 2022 | 5.450 -> 5.438 (-0.23%) | -0.54% | .4132 -> .4175 (+.0043) | -0.24% |
| 2023 | 5.301 -> 5.266 (-0.66%) | -0.50% | .3596 -> .3711 (+.0115) | -1.25% |
| 2024 | 5.470 -> 5.478 (+0.13%) | +0.04% | .3411 -> .3468 (+.0057) | +0.08% |
| 2025 | 5.448 -> 5.429 (-0.35%) | -0.47% | .3593 -> .3673 (+.0080) | -0.51% |
| mean | **-0.31% (6/7)** | -0.43% (6/7) | **+.0060 (6/7)** | -0.48% (6/7) |

Level-weighted MAE -0.42% (6/7). Forward 2022-25: MAE -0.28% (3/4), rho +0.0074 (4/4). By position: QB -0.44% MAE / rho +.014,
RB -0.44%, WR -0.13%, TE -0.30%. By week: wk 1-4 flat (identical by construction), wk 5-9 -0.34%, wk 10+ -0.47% (rho .401 -> .414),
playoffs -0.37%. Clay-blend base: MAE -0.38% (6/7), rho +.0063 (7/7), top-60 -0.57% (6/7), fwd -0.34% (3/4) / rho 4/4.
Split with the OLD elasticities alone: -0.24% (6/7) - most of the gain is removing the double count; e' adds the rank gain.
ROS proxy (player's mean over remaining games, 3+): dropping the team tilt from future weeks MAE 2.960 -> 2.949, rho .546 -> .552.
Recalibrated b after the fix: ALL 0.93, QB 1.01, RB 0.98, TE 1.10, WR 0.73.

**Not changed:** opponent layer (jsOppMult .25 / trust 8) - bO ~0.8-1.0 overall, position rescale adds nothing (consistent with
10-05 rejection); WR points-allowed part carries ~0 but removing it was not tested here. Book guardrail / Out-flag guard unaffected.

Extended 2012-25 pool (25.6k top-150 rows): b GAME 1.43 [1.27, 1.59], b TEAM -0.31 [-0.53, -0.08]; split k=2 e' MAE -0.32% (13/14),
weighted MAE -0.40% (13/14), rho +.0049 (11/14), MSE -0.46% (12/14), top-60 -0.36% (12/14), forward 2015+ -0.33% (10/11), rho 10/11;
2024 is the only losing season in every run (+0.13%).

**Confidence:** medium-high (6/7 + 4/4 forward on 2019-25, 13/14 on 2012-25, both bases). Size: mean |swing| rises
0.61 -> 0.64 pts; QB weekly matchup moves roughly double (mean |QB swing| 0.79 -> 1.09 pts).
**Expiry:** none (structural). **Needs before shipping:** engine wiring + ntWhy chip, export + extension sync, spot-check QBs on
high-total teams (league avg 22.5, team averaging 26 over 6 games -> teamAvg 25.1: a 28-pt implied game is +6.1% today, +6.4%
proposed; a 22-pt game for the same QB is -0.6% today, -6.9% proposed; a 22-pt game for a QB on a 20-pt team is -0.6% today,
+3.1% proposed).
- Queued 2026-10-23 from DRAFT_matchup_2026-10-23.md (research_matchup_swing_calibration.py; memory project_matchup_swing_calibration.md).
- **WIRED 2026-10-23, deploy pending Jack's spot-check OK** (Jack "approve P-20261023-1"). engine.js: `VEGAS_ELAS_SPLIT` {QB .50, RB .50,
  WR .375, TE .375, K .50}, `VEGAS_SPLIT_K` 2, `vegasTeamAvg(p, schedule)` = walk-forward mean of the team's BOOK implied over weeks
  w < cwOf(p) shrunk 2 games to league (null = week 1 / switch off -> old form), `vegasMult(implied, avgImplied, pos, teamAvg)`;
  same form at the three call sites (weeklyProjection, shadowVegasScale evidence cleaning, marketRate rebuild). why.vegTeamAvg;
  app.js ntWhy 'vegasTeam' (0, team level in base) + 'vegas' (game vs own avg) steps, NOTES chip 'VEG game +x%'. Kill
  window.SIM_VEGAS_SPLIT = false. Backups engine.js / app.js .bak_pre_vegassplit_20261023. Spot-check _tmp/vegas_split_spotcheck.md
  (engine week W7): switch OFF = pre-change engine on 482 current-week / 6160 all-week rows (0 differ); week-1 run identical ON
  (9349 rows); factor range .883-1.123, nothing at the clip, no NaN. Biggest QB next-game moves: Lawrence +0.80 (JAX 27.5 vs own
  23.45), Mahomes -0.62 (KC 19.75 vs own 24.63), Watson +0.48, Stroud +0.43; Gibbs W7 27.77 -> 26.68 (DET team tilt out, RB .50).
  Mean |delta| next game QB .17 / RB .22 / WR .09 / TE .10 / K .11 pts; ROS per week QB .09 / RB .20 / WR .08 / TE .07.
  NOT yet: site export, extension sync, simlab-backup, Sim Lab redeploy (after Jack's OK).

- P-20261023-1 DEPLOY 2026-10-23 13:01: Jack OK'd the spot-check; kickers EXCLUDED from the split (p.pos === 'K' -> league-relative form; K rows byte-identical to the pre-change engine, 369 rows; non-K rows identical to the split build, 5791 rows). Exported + pushed b8bd2b51 (sim_proj_2026.js/.json); extensions synced (engine_sim.js x3, manifests Sleeper 0.29.49 / ESPN 0.20.60 / Yahoo 0.9.50); Sim Lab redeploy + simlab-backup snapshot run the same hour.
