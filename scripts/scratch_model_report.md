# Scratch weekly projection model vs the live Sim Lab engine — 2026 Weeks 1-7

*2026-10-27. Proposal only: nothing in engine.js, the sim export, the extensions or the site was changed. Code lives in `E:\MyFantasyFootball\sim_lab\scratch_model\` (unversioned); rerun end to end with `python run_all.py` (or `--quick` to regrade 2026 with the cached fit).*

## TL;DR

- A clean-sheet model built from the raw play-by-play (opportunity x efficiency, fitted on 2017-2024, forward-checked on 2025, then applied as-of to 2026) **ties the live engine on error and loses to it on ordering**. Top-150, importance-weighted, 805 player-weeks with full book lines: weighted MAE 6.48 (scratch) vs 6.51 (live); Spearman within position-week 0.353 vs 0.391; start/sit pairs where the two disagree: live right 59%, scratch 41%.
- The live engine's edge is **RB and WR ordering** (RB rho .527 vs .460, WR pair accuracy 66% vs 59%), and it is real model skill, not just the market anchor: the books alone order RBs at .472.
- The scratch model **wins at QB** (MAE 6.41 vs 6.68, pairs 63% vs 52%, better 4 of 7 weeks on both MAE and rank) and is **better on TE error** (5.37 vs 5.55, 5 of 7 weeks) with mixed TE ordering.
- The new `def_zones` input, rebuilt leak-free for 2017-2026, **carries no general projection value**: switching it off inside the scratch model costs nothing on history (MAE 6.095 -> 6.100) and the leave-one-week-out exponent on top of the live number is 0 in all 7 weeks. It is a card/matchup read, not a projection layer.
- A pure machine-learning read of the same inputs (LightGBM, 100+ features) is **worse than both** out of sample (MAE 6.63) - there is no hidden signal the hand-built models are missing; preseason ADP and season-to-date points/snap level explain most of the variance it can find.
- Nothing here clears Jack's bar for a straight port (multi-season harness, forward weeks, top-100 weight). Two leads are worth an engine-harness replay: the QB opportunity base, and the QB over-market lean (live sits +1.6 above the books, and where it sits 2+ above them the actual lands 1.2 below the live number).

## What was built

**Inputs (all as-of: only games before the week, plus the week's own public line and injury report).** nflverse play-by-play 2016-2026 (`pbp_cache`) rebuilt into player-game and team-game tables: targets by depth, end-zone and red-zone targets, carries by field position, air yards, yards after catch, pass attempts, sacks, fumbles, two-point plays, garbage-time flags; snap shares (`snap_counts` parquets); closing spread/total -> implied totals (the same source as the engine's Vegas layer); roof/wind; the official injury report (`injuries_{Y}` parquets, 2026 from `practice_seq_2026.json`); preseason ADP (FFC history, Underdog 2026 from the accuracy tracker's preseason lock); prior-season per-game levels. From these the rolling state produces, for every played player-week, 119 features: short (half-life 3 games) and long (10 games) EWMA shares of team targets/carries/end-zone targets/goal-line carries/air yards, snap share, points, shrinkage sums, team pace and pass rate, opponent points allowed by position and **per-opportunity zone rates** (RB rush yards/carry, RB/TE/WR yards/target, QB yards/attempt, pass/rush TD rate) shrunk to the prior season and league, vacated teammate share, status.

**Model 1 - STRUCT (the proposal candidate).** Transparent, ~25 constants, every one fitted by Powell search on importance-weighted MSE (ADP curve cubed, top-150) over 2017-2024:

1. Team volume this game = OLS on as-of EWMA attempts/carries + spread + total (targets: +0.22 per point of total, -0.04 per point of spread; carries: -0.12 per point of spread).
2. Player share = 0.40 x short EWMA + 0.60 x long EWMA (fitted; recency matters less than expected), times a vacated-share redistribution whose fitted weight is **0** (the data does not want it - consistent with the rejected vacated-pool layers).
3. Efficiency = player's own rate shrunk to position: catch rate fully trusted (k=0), yards/target k=33, yards/carry k=22, QB yards/attempt k=328 (QB efficiency is almost all league-rate), INT rate k=249.
4. Touchdowns = team expected TDs from the implied total (0.088 pass TD per implied point) x the player's TD share = blend of plain share and end-zone/goal-line share (weights .41/.56, shrunk by opportunities seen).
5. Opponent = zone yardage rate ^ 0.76 (fitted) on yards; **TD-rate elasticity fitted to 0**.
6. Prior = ADP curve (log-linear per position) blended 19% with last season's per-game level; combined with the evidence by effective games with prior strength QB 1.5 / RB 2.1 / WR 4.2 / TE 3.4 games.
7. Questionable x 0.86, limited-practice-no-tag x 0.97; per-position linear calibration.

**Model 2 - GBM.** LightGBM per position on all 119 features (regularised after the first fit overfit badly: in-sample MAE 3.6 vs forward 6.4). Gain importance: ADP 21-29%, ADP-curve level 12-22%, season-to-date points 10-15%, last game's snap share 4-8%, carry/target share 4-8%, opponent 1-2%.

**Honesty rules.** Constants fitted on 2017-2024, checked forward on 2025 (STRUCT MAE 6.13 vs naive season PPG 6.44, rho .368 vs .318), then refitted through 2025 for 2026. 2026 is never fitted. Blend weights between scratch, live and market are leave-one-week-out. Market = median of the books' lines the engine saw at lock, face value (house rule), anytime-TD devigged 1.06 -> Poisson mean. Grading universe = players the live sim published AND who played; final-week rule not relevant yet. Half-PPR throughout (site consensus converted from PPR with the sim's expected receptions).

## Numbers

### Headline — top-150 ADP, 805 player-weeks with full book lines, importance-weighted

| model | MAE (wtd) | MAE raw | bias | Spearman | top-6 hit | top-12 hit | pair acc |
|---|---|---|---|---|---|---|---|
| LIVE Sim Lab (published) | 6.507 | 5.744 | -0.01 | **0.391** | 0.452 | **0.670** | 0.645 |
| STRUCT (scratch) | 6.484 | 5.770 | -0.39 | 0.353 | **0.494** | 0.636 | 0.607 |
| GBM (scratch ML) | 6.629 | 5.819 | -0.83 | 0.350 | 0.464 | 0.608 | 0.600 |
| MARKET (books, face value) | **6.395** | **5.637** | -0.71 | 0.341 | 0.440 | 0.630 | **0.646** |
| STRUCT + MARKET (lowo) | 6.424 | 5.679 | -0.54 | 0.358 | 0.458 | 0.639 | 0.627 |
| LIVE + MARKET (lowo) | 6.523 | 5.728 | -0.32 | 0.364 | 0.446 | 0.654 | 0.628 |
| STRUCT + LIVE (lowo) | 6.497 | 5.728 | -0.14 | 0.378 | 0.458 | 0.664 | 0.638 |
| GBM + LIVE (lowo) | 6.524 | 5.733 | -0.13 | 0.397 | 0.464 | 0.670 | 0.641 |
| Site consensus (Sleeper/ESPN/CBS/FP, 697 rows, no W5) | 6.554 | 5.739 | +0.10 | 0.328 | 0.458 | 0.623 | 0.637 |

Full live universe without the line requirement (832 top-150 rows): LIVE 6.492 / rho .389 / pair .641; STRUCT 6.484 / .353 / .612; consensus 6.551 / .329 / .634. The live engine's own pieces on the same rows: clean JS 6.481 / .385, Clay-free shadow 6.322 / .377, Clay 6.453 / .341.

### By position — top-150, full-line rows

| pos | n | LIVE MAE / rho / pair | STRUCT | MARKET | consensus |
|---|---|---|---|---|---|
| QB | 138 | 6.675 / .373 / .516 | **6.406 / .392 / .628** | 6.419 / .306 / .527 | 6.337 / .381 / .622 |
| RB | 246 | 6.709 / **.527** / .657 | 6.753 / .460 / .621 | **6.605** / .472 / **.669** | 6.779 / .453 / .639 |
| WR | 324 | 6.539 / .392 / **.660** | 6.588 / .374 / .593 | **6.444** / .393 / .650 | 6.701 / .370 / .642 |
| TE | 97 | 5.545 / **.271** / .585 | **5.373** / .187 / **.657** | 5.537 / .191 / .620 | 5.584 / .107 / .547 |

### By ADP band — all live rows, weighted MAE / rho

| band | n | LIVE | STRUCT | MARKET (subset) | consensus |
|---|---|---|---|---|---|
| 1-12 | 66 | 8.14 / .193 | 8.03 / .142 | 7.98 / .089 | 8.33 / .113 |
| 13-30 | 91 | **6.02 / .231** | 6.28 / .153 | 6.03 / .092 | 6.40 / .165 |
| 31-60 | 181 | 6.20 / **.254** | 6.12 / .191 | **6.08** / .202 | 6.37 / .067 |
| 61-100 | 213 | 5.36 / .200 | 5.35 / .194 | **5.12** / .189 | 4.97 / .224 |
| 101-150 | 281 | 5.60 / **.306** | 5.56 / .157 | 5.60 / .295 | 5.51 / .262 |

### By week — top-150, weighted MAE / rho

| wk | n | LIVE | STRUCT | MARKET |
|---|---|---|---|---|
| 1 | 143 | 7.24 / **.408** | 7.34 / .280 | **7.01** / .387 |
| 2 | 133 | 6.88 / .226 | 6.75 / .234 | **6.60** / **.278** |
| 3 | 130 | **6.27 / .334** | 6.48 / .281 | 6.35 / .301 |
| 4 | 122 | **5.95 / .544** | 6.06 / .386 | 6.29 / .343 |
| 5 | 109 | 6.84 / .428 | 6.94 / **.528** | **6.54** / .475 |
| 6 | 103 | 5.73 / .360 | 5.73 / .345 | **5.64** / .269 |
| 7 | 92 | 6.21 / **.425** | **5.62** / .415 | 5.92 / .331 |

### Start/sit decision test

Same-position pairs from the week's top-24 by live projection (top-12 QB/TE), both played, the two models disagree on the order by at least 0.5 each way:

| pos | pairs | STRUCT right | LIVE right | MARKET right | consensus right |
|---|---|---|---|---|---|
| QB | 52 | **60%** | 40% | 62% | 62% |
| RB | 182 | 35% | **65%** | 53% | 39% |
| WR | 142 | 37% | **63%** | 46% | 37% |
| TE | 51 | **55%** | 45% | 44% | 35% |
| ALL | 427 | 41% | **59%** | 51% | 41% |

### Where they disagree most (top-150, gap >= 3 points, 58 rows)

Scratch closer 48% overall; 64% at QB, 36% at RB, 57% at WR, 60% at TE; 80% on Questionable players (10 rows - the live number docks them harder than the fitted 0.86). The live model wins the big RB role calls (Jeanty W5 5.7 vs scratch 13.3, actual 9.2; Javonte W1/W4, Hubbard W2-W4) because it reads the depth chart, practice reports and overrides that the as-of stat state cannot see, and because its usage layers read a growing role faster (rows where live is 1.15-1.5x the scratch number: actual 14.1, live 13.7, scratch 11.1, n=70). Scratch wins the QB over-reads (Burrow W1, Murray W3-4, Darnold W4-5, Caleb Williams W6 where live had 9.2). Full list: `scratch_model/out/disagree.csv`.

## What the scratch model does differently from engine.js, and what that bought

| design choice | scratch | engine.js | verdict from the data |
|---|---|---|---|
| base level | ADP curve + last season, blended by effective games | Clay-free shadow (history prior, usage evidence, many docks) + market anchor | engine better on RB/WR ordering; scratch equal on error |
| volume | explicit team attempts/carries model (pace + Vegas) x player share | per-player points evidence x Vegas elasticity | explicit volume is what makes the scratch QB good; no edge on top of the live number elsewhere |
| opponent | per-opportunity zone rates as-of (def_zones rebuilt leak-free) | FPA position layer + Clay unit grades + Vegas | **zone rates add nothing**: history ablation -0.005 MAE, lowo exponent 0/7 weeks on the live number |
| TDs | team expected TDs (Vegas) x end-zone / goal-line share | stat comps + TD-luck regression | small plus on history, neutral 2026 |
| vacated usage | fitted weight 0 | next-man-up + vacancy layers | agrees with the rejected-layers hub: the stat state does not want it |
| injuries | Q x 0.86, LP x 0.97 only | full injury window / practice sequence / status logic | engine's extra news is worth real points on the biggest misses |
| market | not inside the model; blended after, lowo | prop anchor + BOOK_CAP | market-anchored scratch still orders RB worse than the live engine |

## Ranked proposals (none cleared for a straight port; all are engine-harness replays for Jack to approve)

Checked against `hub_sim_backtests_rejected`, `hub_shadow_model`, `hub_sim_model` before listing. The QB market knobs (propW, belowW, INT/FL devig, ESPN/Vegas blends, shrink) were all REJECTED 10-23 with a re-check pencilled for ~W10 - none of those are re-pitched.

1. **QB opportunity base as a second QB leg** (`qbBase = teamAttempts(pace, spread, total) x shrunkYPA(k~330) x oppPassRate^.76 + 4 x teamExpTD(implied) x attemptShare + rush`), averaged 50/50 with the current QB number. 2026: MAE better 6 of 7 weeks (6.68 -> 6.52), pair accuracy .516 -> .577, rank flat (3/7). Scratch QB alone: 4/7 MAE, 4/7 rank, pair .628. Evidence is 138 rows of one season, so it needs the 2013-25 engine-parity harness before anything ships; the component is cheap to build there because every input already exists in `bt_common`.
2. **QB over-market lean, data for the W10 re-check** (not a knob): the live QB number sits +1.57 above the face-value market on average (every week, +0.7 to +2.3); on the 51 rows where it sits 2+ above, actual lands 1.23 below live and 1.23 above market. Live bias by week +1.5/+1.5/+1.1/+2.8/-1.4/+0.9/+0.4. The scratch model has no such lean (bias -0.10). This is the same gap the 10-23 study found and is still open; the QB base in (1) would close about half of it.
3. **TE level**: scratch TE error better 5 of 7 weeks and pair accuracy .684 vs .618 on 100 rows; both models run low (bias -0.5 live, -0.9 scratch); the scratch read is target-share x team attempts with the TD share from end-zone targets. Too few rows per week to call ordering; worth a look only alongside the TE items already in the roadmap.
4. **def_zones as a projection input: do not port.** Rebuilt leak-free for ten seasons, the zone yardage multiplier earns nothing on top of the live number (lowo exponent 0 in all 7 weeks; fixed e=1: MAE +0.008, rho +.004 - noise). Position cuts: TE 4/7 MAE and 5/7 rank, QB 4/7 MAE, RB 2/7, WR 2/7 - a TE-only lean on 100 rows is not evidence. Keep it where it is (card MATCHUP tab, Start/Sit edges).
5. **Vacated-share redistribution** fitted to zero on 2017-25 inside a clean model - supports the vacancy-fade and conservation findings already on file; nothing to add to the engine.
6. **ADP stays the prior**: the scratch model loses 0.25 MAE and .03 rho on 2026 without the preseason prior, and GBM puts ADP at 21-29% of its gain at every position. Matches the 10-20 "ADP still earns at week 8" finding.

## What the live engine should keep doing

RB/WR ordering (roles, pecking order, usage evidence, injury/news handling) is the engine's measurable edge over a clean rebuild, the books and the sites; the W1 preseason machinery (rho .408 vs scratch .280) and the W4 read (.544 vs .386) are the clearest cases.

## Caveats

- 7 weeks of one season is a small sample by Jack's standing rule; the history fit (2017-25) backs the scratch design, but there is no live-engine number on history, so scratch-vs-live is 2026-only.
- The live locks are what the engine published each week; layers shipped since (e.g. the 10-23 Vegas split, 10-20 per-team current week) are not in the earlier locks.
- Market = my face-value conversion of the lock lines (QB INT at 0.75, missing anytime-TD lines filled with position rates); it tracks the engine's propMean at r=.977, 0.5 lower on average.
- Week 5 site locks were never archived, so the consensus rows exclude W5.
- Actuals are nflverse half-PPR from the scoring components (match the tracker's PPR actuals within 0.1 on average).

## Files

- `sim_lab/scratch_model/features.py` (pbp -> tables), `asof.py` (leak-free rows), `model.py` (STRUCT, GBM, Jack's grading), `fit_history.py`, `refit_gbm.py`, `backtest.py` (2026), `layers.py` (ablations + layers on the live number), `run_all.py`.
- Outputs: `out/fit_history.log` (history fit + 2025 forward), `out/bt_tables.md` (all 2026 tables), `out/layers.md` (ablations, layer-on-live tests, QB deep dive, RB/WR edge), `out/bt_rows.csv` (every graded row, every model), `out/disagree.csv`, `out/params.json`.


---

# Harness replay (2026-10-27, Jack approved replaying proposals 1 and 3)

*Still proposal only. Script: `E:\MyFantasyFootball\sim_lab\backtest_scratch_legs.py` (default = the 2019-25 engine-parity harness; `SIM_BT_YEARS=2012-2025` = the extended 2013-25 harness from `_bt_ext/X_cache_ext2012_2025_tf.pkl`; `SCRATCH_QB_OPP=fpa` = the engine-available opponent input). Logs: `sim_lab/scratch_model/out/harness_legs.log`, `harness_legs_ext2012_2025_tf.log` and their `_fpaopp` twins.*

**Method.** Baseline = `backtest_shadow_next.shadow(X)`, the engine-parity next-game number every other layer was graded against. Each leg is joined to the harness rows by gsis id and week (100% of QB rows, 99% of TE rows) and blended `w x leg + (1 - w) x shadow`, w = .25 / .50 / .75, in two forms: **EV** = the opportunity formula alone (rows with 1+ games of evidence) and **FULL** = the scratch model's calibrated number (its ADP prior blended in). The team-volume OLS and the league rates are refit on the training seasons of every fold; the five shrink constants (k_ypa 328, k_int 249, k_ypc 22, k_ypt 33, e_def .76) are the 2017-25 fit, so they are in-sample for 2017-25 and out-of-sample for 2013-16 (the leg still wins there). Grading = the house `test()` rules: leave-one-season-out pick, forward pick (earlier seasons only), error on the rows the leg touches, whole-board top-150 weighted guard, top-100 cubed, weekly within-position rank rho, final week out, no elite dock possible (a blend never pushes a player below the lower of the two numbers). Ship bar: LOSO better in 5+ of 7 (ext 11+ of 13) AND forward 3+, touched-row error -0.3%+, guard <= +0.02%.

**Rejected-knob check.** The leg has no market input, so it does not reduce to the 10-23 QB market knobs (propW, belowW, INT/FL/2-pt devig, ESPN or Vegas-only blends, shrink). It is not the 10-08 "QB ridge prior / share-scaled evidence" (rejected 0/7) either: that scaled the points evidence by target or route share; this reconstructs attempts x efficiency from the team's pace and the Vegas line and sits next to the shadow as a second number.

## QB leg: SHIP at 50/50, EV form

| harness | opponent input | form | LOSO touched | seasons better | forward | seasons better | guard | top-100 cubed | QB rank rho | pick |
|---|---|---|---|---|---|---|---|---|---|---|
| 2019-25 | pbp yards/attempt | EV | -1.79% | 7/7 | -2.02% | 4/4 | -0.22% | -0.16% | +.010 | w .50 every fold |
| 2019-25 | pbp yards/attempt | FULL | -1.44% | 7/7 | -1.82% | 4/4 | -0.25% | -0.18% | +.012 | w .50 |
| 2013-25 | pbp yards/attempt | EV | -1.89% | 12/13 | -1.95% | 11/11 | -0.15% | -0.07% | +.013 | w .50 |
| 2013-25 | pbp yards/attempt | FULL | -2.63% | 12/13 | -2.61% | 10/11 | -0.20% | -0.12% | +.018 | w .50 |
| 2019-25 | **FPA QB points allowed (engine input)** | EV | -1.85% | 7/7 | -2.30% | 4/4 | -0.24% | -0.17% | +.018 | w .50 |
| 2013-25 | **FPA QB points allowed (engine input)** | EV | -1.80% | 12/13 | -1.85% | 10/11 | -0.14% | -0.06% | +.017 | w .50 |

Per season on the 2013-25 harness, QB top-150 rows, weighted MAE / within-week Spearman / pair accuracy (EV form, pbp opponent; each season's leg built from the other seasons):

| season | n | shadow | w .25 | w .50 | w .75 | leg alone |
|---|---|---|---|---|---|---|
| 2013 | 270 | 5.888 / .277 / .635 | 5.830 / .303 / .616 | 5.796 / .296 / .608 | 5.800 / .303 / .596 | 5.841 / .292 / .571 |
| 2014 | 250 | 5.996 / .166 / .638 | 5.971 / .184 / .629 | 5.985 / .183 / .636 | 6.023 / .198 / .645 | 6.100 / .192 / .612 |
| 2015 | 242 | 5.866 / .285 / .532 | 5.845 / .309 / .549 | 5.847 / .297 / .566 | 5.875 / .299 / .591 | 5.931 / .289 / .608 |
| 2016 | 292 | 5.441 / .184 / .548 | 5.406 / .203 / .555 | 5.389 / .212 / .567 | 5.397 / .211 / .558 | 5.421 / .210 / .583 |
| 2017 | 246 | 5.582 / .180 / .555 | 5.474 / .210 / .603 | 5.395 / .252 / .666 | 5.346 / .286 / .663 | 5.318 / .286 / .656 |
| 2018 | 262 | 6.213 / .273 / .576 | 6.189 / .279 / .543 | 6.180 / .275 / .567 | 6.214 / .300 / .536 | 6.286 / .293 / .537 |
| 2019 | 265 | 6.450 / .251 / .590 | 6.391 / .264 / .582 | 6.360 / .261 / .607 | 6.349 / .270 / .596 | 6.370 / .247 / .589 |
| 2020 | 259 | 6.524 / .328 / .592 | 6.487 / .333 / .640 | 6.466 / .342 / .626 | 6.466 / .331 / .641 | 6.485 / .323 / .623 |
| 2021 | 282 | 6.277 / .428 / .464 | 6.258 / .431 / .518 | 6.268 / .418 / .500 | 6.300 / .406 / .515 | 6.384 / .393 / .525 |
| 2022 | 259 | 5.670 / .408 / .713 | 5.650 / .392 / .717 | 5.661 / .387 / .693 | 5.686 / .366 / .673 | 5.757 / .346 / .642 |
| 2023 | 239 | 5.978 / .293 / .597 | 5.946 / .306 / .612 | 5.923 / .318 / .607 | 5.934 / .306 / .630 | 5.970 / .293 / .615 |
| 2024 | 300 | 6.314 / .291 / .615 | 6.245 / .312 / .615 | 6.197 / .328 / .617 | 6.164 / .328 / .633 | 6.160 / .338 / .627 |
| 2025 | 304 | 6.177 / .235 / .571 | 6.168 / .250 / .588 | 6.172 / .258 / .573 | 6.194 / .244 / .538 | 6.225 / .247 / .527 |
| **wins (MAE / rho / pair)** | | | 13 / 12 / 7 of 13 | 13 / 11 / 10 of 13 | 8 / 10 / 8 of 13 | 7 / 7 / 7 of 13 |
| ALL | 3730 | 6.054 / .279 / .584 | 6.014 / .291 / .592 | 5.997 / .297 / .598 | 6.007 / .297 / .593 | 6.044 / .293 / .582 |

2019-25 default harness, same layout: shadow 6.213 / .330 / .567 -> w .50 6.149 / .340 / .592 (MAE better 6 of 7, rho 4 of 7, pair 4 of 7; w .25 MAE better 7 of 7). With the FPA opponent input: w .50 6.153 / .348 / .599, MAE 6 of 7, rho 6 of 7, pair 5 of 7.

**Is 50/50 the right split?** Yes. The leave-one-season-out pick is w .50 in every fold on both harnesses, both forms and both opponent inputs; the forward pick is .25 in the earliest folds (three training seasons) and .50 from 2018 on. w .75 and the leg alone give back the rank and pair gains (the leg alone is +1.3% to +2.0% worse than the shadow on error): it is a second opinion, not a replacement. **EV over FULL:** FULL wins more error on the touched rows (-2.6% vs -1.9% on 2013-25) but carries a second ADP prior next to the engine's own; EV is the clean formula and passes everything. FULL at .50 is the alternative if Jack wants the extra error.

**Opponent input:** nothing is missing. The harness ran the leg with the pbp yards-per-attempt rate allowed (not an engine input) and with the FPA points-allowed-to-QBs relative level the engine already loads (`fpa_2026.js` QB_tdn over `fpa_prior_2025.js`), and the FPA version passes the same bar with the better QB rank (+.017 / +.018). Ship with the FPA input.

**2026 sanity check only (not the decision):** QB MAE 6.68 -> 6.52 at 50/50 with the live number, better 6 of 7 weeks, pair accuracy .516 -> .577, rank flat.

**The engine.js change (pseudo-code, not applied).** A QB opportunity leg next to the Clay-free shadow, averaged in before the market anchor; everything downstream (prop anchor, BOOK_CAP, QB floor, in/out scenarios, extensions sync) runs on the averaged number as today.

```
// --- QB OPPORTUNITY LEG (scratch_model harness replay 2026-10-27: LOSO 7/7 + 12/13, forward 4/4 + 10/11, w .50 every fold)
var QB_OPP_LEG = { w: 0.50, kYpa: 328, kInt: 249, kYpc: 22, eDef: 0.76, minGames: 1,
                   attOls: [8.8, 0.441, -0.029, 0.222],     // team pass attempts ~ a + b x EWMA attempts (hl 4 games) + c x team spread + d x total (refit each season)
                   ptdOls: [-0.483, 0.088],                 // team pass TDs ~ a + b x implied total
                   rtdOls: [-0.098, 0.045],                 // team rush TDs ~ a + b x implied total
                   lg: { ypa: 7.1, intr: 0.023, ypc: 4.4 } };   // league per-attempt / per-carry rates, refreshed from the pbp cache each season
function qbOppLeg(p, wk, sc, schedule) {
  if (p.pos !== 'QB' || gamesPlayed(p, wk) < QB_OPP_LEG.minGames) return null;
  var line = gameLine(p.tm, wk);                                           // BETTING_2026 / FUTURE_TOTALS: team spread, total, implied
  var paceAtt = teamAttemptsEwma(p.tm, wk);                                // SIM_PACE_2026.teams[tm].cur.vol (att per game, season to date)
  var A = QB_OPP_LEG.attOls, teamAtt = Math.max(5, A[0] + A[1] * paceAtt + A[2] * line.spread + A[3] * line.total);
  var teamPtd = Math.max(0.2, QB_OPP_LEG.ptdOls[0] + QB_OPP_LEG.ptdOls[1] * line.implied);
  var teamRtd = Math.max(0.1, QB_OPP_LEG.rtdOls[0] + QB_OPP_LEG.rtdOls[1] * line.implied);
  var S = seasonToDate(p, wk);                                             // att, py, int, car, ry, i10 carries from the game logs, weeks < wk
  var attSh = 0.40 * S.attShare_hl3 + 0.60 * S.attShare_hl10;              // his share of team attempts, short + long EWMA
  var ypa  = (S.py  + QB_OPP_LEG.kYpa * QB_OPP_LEG.lg.ypa)  / (S.att + QB_OPP_LEG.kYpa);
  var intr = (S.int + QB_OPP_LEG.kInt * QB_OPP_LEG.lg.intr) / (S.att + QB_OPP_LEG.kInt);
  var ypc  = (S.ry  + QB_OPP_LEG.kYpc * QB_OPP_LEG.lg.ypc)  / (S.car + QB_OPP_LEG.kYpc);
  var opp = Math.pow(fpaQbRelative(p.opp, wk), QB_OPP_LEG.eDef);           // (FPA QB_tdn as-of + 4 games of last season's prior) / league
  var att = attSh * teamAtt;
  return att * (sc.pass_yd * ypa * opp - 2 * intr)                         // yards and INTs
       + sc.pass_td * attSh * teamPtd                                      // pass TDs = team expected x his attempt share
       + S.carEwma * sc.rush_yd * ypc                                      // rushing yards
       + sc.rush_td * S.rushTdShare * teamRtd;                             // rush TDs: .56 x goal-line carry share + .44 x carry share, shrunk by i10 carries seen
}
// weeklyProjection, after the shadow is final (after the '+debut' line) and before propAnchorMean():
if (p.pos === 'QB' && ncMean > 0 && !ncOut && !(typeof window !== 'undefined' && window.SIM_QB_OPP_LEG === false)) {
  var qbLeg = qbOppLeg(p, wk, sc, schedule);
  if (qbLeg != null) { ncMean = QB_OPP_LEG.w * qbLeg + (1 - QB_OPP_LEG.w) * ncMean; ncSrc += '+qbopp'; }
}
```

Kill switch `window.SIM_QB_OPP_LEG = false`; the export must be byte-identical with it off. The three OLS rows and the league rates are season-start fits (the harness refit them per season and the picks did not move); `fpaQbRelative` is the same read the opponent grade already does. Fill-in and window QBs: `gamesPlayed` counts his own starts, so a backup with no games gets no leg (shadow only), matching the harness rows that were untouched.

## TE leg: DON'T SHIP

| harness | form | LOSO touched | seasons better | forward | seasons better | guard | TE rank rho | per-season MAE / rho / pair wins | bar |
|---|---|---|---|---|---|---|---|---|---|
| 2019-25 | EV | -0.98% | 6/7 | -0.89% | 3/4 | -0.04% | +.014 | 5 / 5 / 3 of 7 (w .25) | passes, barely |
| 2019-25 | FULL | -1.14% | 7/7 | -0.62% | 3/4 | -0.09% | +.007 | 4 / 5 / 3 of 7 (w .50) | passes, barely |
| 2013-25 | EV | -0.94% | 10/13 | -0.95% | 8/11 | -0.03% | **-.003** | 7 / 4 / 6 of 13 (w .25) | **FAIL** |
| 2013-25 | FULL | -0.97% | 12/13 | -0.99% | 11/11 | -0.08% | **-.006** | 6 / 5 / 7 of 13 (w .50) | error bar only |

On the long harness the EV form fails outright (10 of 13, rank negative). The FULL form clears the error bar (12/13, 11/11) but every rank measure goes the wrong way: TE rank rho -.006, Spearman better in only 5 of 13 seasons, 2016-17 and 2022 clearly worse, and the leg alone is +5.7% worse than the shadow. The error gain is a small MSE improvement on deep TEs the shadow runs high on, not a better TE1-TE12 order, and the in-season objective is rank order inside the position. Verdict: DON'T SHIP. The 2026 TE lead in the first section (better error 5 of 7 weeks, n=100) does not survive the long sample as a ranking layer; do not re-pitch it as one.

## Caveats

- The leg's five shrink constants were fitted on 2017-25 as-of rows; 2013-16 are a true out-of-sample check and the leg wins all four on error and three of four on rank.
- Both harnesses grade the shadow without the market anchor (no prop lines before 2026); the 2026 check in the first section is the only look at the leg next to the anchored number, and there it helped by the same margin.
- Blend weights were compared on the training seasons with the all-season leg (the per-fold legs differ only in the OLS rows and league rates); the held-out season always used its own fold's leg.
