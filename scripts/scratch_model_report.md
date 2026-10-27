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
