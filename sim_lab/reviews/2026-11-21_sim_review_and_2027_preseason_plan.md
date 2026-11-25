# Sim review and 2027 preseason plan (2026-11-21)

Owner: sim engineer. Asked by Jack on 2026-11-21: "can they look over the sims and start working on next years sims (pre season sims) based on backtest look at how general sims work, how sportsbooks get lines, etc. Obviously look at sims for in season too." The scope then grew to 28 parts.

**Ground rules this pass:**
- Nothing live changed: not engine.js, overrides.js, the site export (data/sim_proj_2026.*), the helpers, or anything deployed. Nothing was pushed or deployed.
- sim_lab is not a git repo, so nothing was committed.
- All new code is in `E:\MyFantasyFootball\sim_lab\preseason2027\`.
- Every live-engine change below is a proposal for Jack to approve.
- Only public line data was used, read from public pages. No sign-ins were needed and none failed.

**Status labels used in every part**
- **FULL** = fully backtested.
- **PARTLY** = partly done: some new or cited backtest, but pieces missing.
- **DESIGN** = design only, no backtest possible yet.

## Status table

| # | Part | Status |
|---|---|---|
| 1 | Audit of current sims (weekly engine, shadow, season/league/dynasty) | FULL on history (cited + new pairwise/ROS); 2026 live read |
| 2 | Research: sims + sportsbooks | done (cited) |
| 3 | 2027 preseason prototype | PARTLY: working walk-forward backtest; v0 does not beat ADP alone |
| 4 | Ranked in-season proposals | done |
| 5 | Dynasty | PARTLY (cited backtests + new age/persistence) |
| 6 | League sims | PARTLY (73 real 2026 matchups; title odds can't be graded until week 17) |
| 7 | Trade sims | DESIGN (logic audited, no verdict backtest possible from stored data) |
| 8 | Season sims (NFL team + fantasy season ranges) | FULL for NFL team sims (new prototype); PARTLY for fantasy season ranges |
| 9 | Best ball | PARTLY (weekly shape/spike rates tested; advance odds not) |
| 10 | Draft sims | DESIGN (+ ADP-baseline numbers from part 3) |
| 11 | Playoff sims | FULL for NFL bracket/advance odds (prototype); DESIGN for fantasy playoff calibration |
| 12 | Waivers | DESIGN (cited evidence) |
| 13 | Start/sit | FULL (236k pairs, 2019-25) |
| 14 | ROS rankings | FULL (history) + 2026 lock read |
| 15 | DFS | DESIGN + PARTLY (DK-scored distributions + correlations tested) |
| 16 | Player props | PARTLY (2026 prop backtests cited; no new run) |
| 17 | Game sims | FULL for the market inputs (engine has no game sim) |
| 18 | Auction | DESIGN |
| 19 | Keeper | PARTLY (surplus backtest 2016-25) |
| 20 | Devy / prospects | PARTLY (JM vs draft capital, leave-one-class-out) |
| 21 | Superflex | PARTLY (format VOR 2015-25) |
| 22 | TE premium | PARTLY (format VOR 2015-25) |
| 23 | IDP | DESIGN (no IDP in the engine) |
| 24 | Kicker + D/ST | PARTLY (existing backtests cited) |
| 25 | Guillotine | DESIGN |
| 26 | Survivor | PARTLY (market-only replay 2013-25; no pick-popularity data) |
| 27 | Pick'em (SU / ATS / confidence) + 27b confidence pools | FULL on market data; 27b PARTLY (field model assumed) |
| 28 | Brackets: (a) NFL, (b) March Madness | (a) FULL (13 postseasons, tiny); (b) DESIGN |

Logs for every new number are next to the code:
- `preseason_backtest.log`
- `team_sims.log`
- `decisions_backtest.log`
- `nfl_pools.log`
- `confidence_pool.log`
- `nfl_bracket.log`

---

## Part 1. Audit of the current sims

### 1.1 What is live

**Weekly number.** This is the Clay-free shadow (`ncMean`) plus the wired layers. Clay was retired as the weekly base on 10-08, and the per-position blend now applies only to later weeks. The layers include:
- the opportunity pool / vacancy
- the market guard
- the QB opportunity leg
- the split Vegas form (P-20261023-1)
- injury signals
- the Q streak and next-game docks
- the new-team debut dock

The live number is then prop-anchored (book anchor, face-value lines, `BOOK_CAP` +20%).

**Season sim.** It includes:
- the coupled team season shocks (QB hub .35, RB room .25, WR room .20)
- banked actual weeks
- season scenarios

**League sim.** `simLeague` (engine.js ~4897). It uses:
- correlated weekly draws
- greedy lineups on means
- D/ST streaming
- standings by W then PF
- a fixed bracket

**Dynasty.** `build_dynasty_sim.py`: comps WIN3 + 1.5 x YOUTH, folded in-season, feeding MFF VALUE / FAIR.

### 1.2 Accuracy where it stands

**Weekly points vs the industry (history, `backtest_vs_espn.py`, 2019-25, top 150).**
- Typical miss: ESPN 7.11, the 70/30 blend 7.14, the shadow 7.14. ESPN beats our pre-book base by about 1%.
- Rank is tied (rho .378).
- A 50/50 shadow + ESPN mix is the best weekly ranking we ever measured: rho .388, 6/7 seasons.
- Weak spots vs ESPN:
  - week 1 (+2.9%)
  - weeks 15-18 (+3.2%)
  - ADP 61-150
  - RBs

**2026 weeks 1-10 (`sim_lab/scorecards/w*.log`).**
- Same-row example, W10, 158 rows:

| Source | MAE |
|---|---|
| Prop-anchored | 5.63 |
| FantasyPros | 5.63 |
| ESPN | 5.64 |
| Shipped | 5.74 |
| Consensus | 5.73 |

- Pooled W1-10 by source (row sets differ per source, so read only roughly): shadow 5.44, prop-anchored 5.45, consensus 5.51, FP 5.59, ESPN 5.61, shipped 5.71.
- Reading: we are at par with the sites. The book anchor helps. The shipped mean has run slightly behind its own components on the rows it covers. That points to the blend/anchor weights, not the base, and is worth re-tuning after week 12 (proposal 4.3).

**Start/sit calibration (new, part 13).** Excellent:
- the model's favourite wins 58.3% of 236k close pairs, against a predicted 58.5%
- every calibration bin is within 1-2 points

**ROS ranks (new, part 14).**
- The model beats preseason ADP from week 2 and season-to-date PPG at every week through 13.
- ESPN catches up around weeks 9-11 and passes us from week 14.

**Weekly distributions.**
- p10-p90 coverage is 81.2% (`backtest_shadow_coverage.py`).
- Gamma spike rates match reality (part 9), except QB dud weeks (real 3-5%, gamma 0.2-2%).
- Teammate correlations: the engine's targets QB-WR1 .32 / oppQB .19 / WR1-WR2 .06 compare with real residual correlations of +.34 / +.25 / +.01 (part 15). The structure is right. The opposing-QB link is a little weak.

**Season ranges.**
- Player season p10-p90 coverage is about 80-82% (`backtest_sim_calibration.py`); ROS coverage at weeks 5/9/13 is 81.6-84% (`backtest_midseason.py`).
- Team-total coverage rose from 68% to 83% after coupled shocks (10-14).

**2026 ROS locks (`grade_ros_lock.py`, weeks 5-7).**
- The model beats season-to-date PPG (MAE 2.77 vs 3.21) and ties Clay-form.
- Bias: RB actual/model 1.14-1.15 (we are LOW on RBs) and TE 0.87-0.94 (we are HIGH on TEs).
- This is one season, so per the "judge on history" rule it is a watch item, not a fix. It is the thing most likely to put a wrong TE on a tier board (part 14).

**Engine week-1 base (new, part 3).** On the 2019-25 ADP top-150, the shadow preseason prior reads ~9% LOW (actual/pred 1.095) and has the worst MAE (2.591) of all preseason sources. Live week 1 in 2026 leaned on Clay + books, so this did not hurt 2026. It must be fixed before a Clay-free 2027 week 1.

### 1.3 Where the engine is weakest, and why

1. **Week 1 and the preseason prior.** Our own preseason level is low and loses to ADP, Clay and ESPN (part 3). There is no market (win totals, season props) in the prior today.
2. **The fantasy playoffs (weeks 15-17).** ESPN is about 3% better. The ROS table shows ESPN level with us from week ~9 and ahead from week 14. The likely cause is late-season rest, injury news and role changes that ESPN's pre-kickoff number already has and ours partly misses.
3. **Decisions are graded only as projections.** Trade verdicts, draft recommendations, waiver calls and title odds have never been scored against outcomes (parts 6, 7, 10, 12).
4. **No team / game layer of its own.** The engine takes team context from book lines. Far-out weeks use re-rated lines (`build_future_totals.py`, which is good: two weeks out, MAE 1.35 vs 1.96 stale). There are no NFL team ratings, no game outcomes and no plays. That caps NFL-side products (part 17).
5. **Questionable players are mean-scaled rather than drawn in/out.** This understates variance in league, best ball and guillotine sims.

---

## Part 2. Research: how general sims and sportsbooks work (cited)

Full briefs came from two research agents. URLs are inline. Items marked "unverified" came from search snippets.

### General sims

**538 Elo.**
- K 20 with a ln(MOV+1) multiplier.
- Each offseason the rating regresses 1/3 toward 1505. From 2019 the preseason rating was 2:1 weighted toward the Vegas win-total rating (https://fivethirtyeight.com/features/how-our-nfl-predictions-work).
- 25 Elo is about 1 point (https://nfeloapp.com/nfl-power-ratings).

**ESPN FPI.** The preseason prior is mainly Vegas win totals. The prior's weight fades in-season. 10k sims (https://global.espn.com/blog/statsinfo/post/_/id/123048/a-guide-to-nfl-fpi).

**nflseedR.**
- Sims update ratings inside each sim ("hot").
- Margin ~ N(Elo diff/25, 13).
- Full tiebreak chain (https://nflseedr.com/articles/nflsim.html, https://nflseedr.com/articles/tiebreaker.html).

**Market blending.** nfelo found a ~65% market blend beats both the model and the market on Brier (https://www.nfeloapp.com/analysis/using-market-regression-to-improve-prediction-accuracy-in-the-nfl/).

**Margin SD.** About 13.45-13.86 (Stern 1991; https://arxiv.org/pdf/2212.08116).

**Shrinkage / stability.**
- YPC stabilizes only after ~2,000 carries; YPA after ~400 attempts (https://www.footballguys.com/article/HarstadRegression02).
- WR year-over-year R²: PPG .57, target share .40, yards per target .03, TD per target .01 (https://www.sharpfootballanalysis.com/fantasy/wide-receiver-stats-that-matter-fantasy-football-2024/).
- Practical rule: volume carries over, efficiency mostly does not. That matches our rejected-layer history.

**Aging.**
- The delta method has survivorship bias (https://www.rotowire.com/football/article/the-stats-room-at-what-age-do-players-decline-29538).
- RB collapse risk by age, Harstad's "mortality table": 27 15%, 29 26%, 31 42% (https://www.footballguys.com/article/HarstadDiP18).
- 4for4 peaks: RB ~26, WR 26-28, TE ~26 (https://4for4.com/2025/preseason/production-curves-positional-breakouts-prime-years-and-falloffs-age).

**Calibration.** Maximize sharpness subject to calibration; check with PIT, CRPS and interval coverage (Gneiting 2007).

### Sportsbooks

**Openers.** Power-rating difference plus home field. Market makers open at low limits and move toward sharp money; retail books copy them (https://unabated.com/articles/who-sets-the-sports-betting-line-market-makers).

**Home field.** It fell from ~3.3 points in 2006 to ~1.5-2 now (https://operations.nfl.com/gameday/analytics/stats-articles/what-does-the-nfl-s-home-field-advantage-look-like-in-2020).

**Key numbers.** 3 = 15.1% and 7 = 9.0% of margins, 1999-2025 (https://www.deucescracked.com/blog/nfl-margin-of-victory-data-1999-2025).

**The close is the benchmark.** Pinnacle treats beating the close as the sign of long-run edge (https://www.pinnacle.com/betting-resources/en/educational/efficient-market-hypothesis-in-sports-betting-why-early-bets-beat-the-market).

**De-vig methods** (https://cran.r-project.org/web/packages/implied/vignettes/introduction.html):
- Multiplicative for two-way markets.
- Power or Shin for multi-way futures.
- Always renormalize to the known count (14 playoff berths, 1 champion per division).

**Hold.**
- Sides ~4.5%.
- Division futures ~9%; big futures 20-50% (https://www.thelines.com/betting/futures-hold-vig/).
- Our measured win-total hold: 4.4% (448 lines).

**Win totals.** MAE ~2.2 wins vs results (numberFire via snippet; https://the33rdteam.com/?p=13531). We measured 2.16 from our de-vigged lines (part 8).

**Season player props.** Unders hit 61% in 2021-22 closing lines (QB passing yards unders 74%), because books price as if players stay healthy (https://www.4for4.com/2023/preseason/key-winning-season-long-player-props). Clay puts ~80% of industry projections over the prop (https://www.espn.com/chalk/story/_/id/32008915/volume-volatility-how-approach-player-prop-bets).

### Worth borrowing (what this review acts on)

1. **The market as the prior.** The ADP curve, win totals, and season props once posted, with our model explaining only the residual. Part 3 shows this "market-anchored" form is the only one that gets close to ADP.
2. **De-vigged win totals become team ratings, then hot season sims.** Part 8: beats Elo, and only hot ratings give honest ranges.
3. **Season props are medians of an injury-truncated distribution.** Compare them to our sim MEDIAN with a games-missed draw, never to our mean (part 16).
4. **Grade decisions against the close.**
   - Game layer: the closing spread/ML.
   - Weekly players: closing props.
   - Draft: closing ADP, which is closing-line value for drafts.
5. **Ensembles weighted by past error** (ATC-style). Consensus wins early in a season, our signal late (FantasyPros 2010 study, https://www.fantasypros.com/2011/01/expert-consensus-rankings-accuracy). Our data says the opposite for the late season (ESPN ahead weeks 11+), which argues for a late-season consensus weight (proposal 4.2).

---

## Part 3. The 2027 preseason prototype

### 3.1 What was built

All of it is in `sim_lab/preseason2027/`. It is read-only on every shared cache.

**`build_player_weeks.py`.** Player-game table 2012-2025 from nflverse pbp (72,421 rows), with:
- half-PPR (house scoring), PPR and DraftKings points (bonuses included)
- usage: targets, carries, attempts, team targets and carries

It also builds a team-game table (7,326 rows) with plays, dropbacks, closing spread/total and moneyline.

Checked against known seasons: 2023 CeeDee Lamb 403.2 PPR and McCaffrey 391.3 both match.

**`data/win_totals_2012_2025.csv`.** All 448 preseason win totals with juice, parsed from the public SportsOddsHistory pages (now at covers.com/sportsoddshistory). The pages say early-September "as of" lines, i.e. close to the preseason close. De-vig: two-way multiplicative, then expected wins = line + 2.0·Φ⁻¹(p_over), renormalized so the league sums to 16 x games.

**`preseason_model.py`.** Walk-forward over 2015-2025. Each target season Y is fit only on seasons before Y, with a 4-season half-life weight. Per position:

- **Features, all known before week 1:**
  - Y-1/Y-2/Y-3 PPG and games
  - Marcel-style 5/3/2 weighted history
  - Y-1 targets, carries and attempts per game, target and carry share, QB rush yards, TD and yardage rates
  - age, age², experience, rookie flag, log draft pick, round 1/2, undrafted
  - week-1 depth-chart rank (nflverse 2012-24; the ESPN pre-opener chart for 2025)
  - team change
  - de-vigged team expected wins
  - team Y-1 pass/rush volume and points
  - vacated target/carry share
  - QB1 identity, new-QB flag, QB1's Y-1 PPG
  - market: FFC ADP (log) and positional ADP rank
- **Models:**
  - ridge, stats only
  - ridge + ADP
  - GBM + ADP
  - ensemble
  - **market-anchored**: an isotonic ADP→PPG curve as the prior, plus a heavily shrunk ridge/GBM residual
  - a games-played model
  - season total = PPG x games
- **Baselines:**
  - the walk-forward ADP curve
  - naive last-season PPG
  - 2019-25 only: ESPN's week-1 projection, Clay's season sheet (fair per game), and the live engine's week-1 base (shadow preseason prior, from `season_long_table.parquet`)
- **Ranges:** walk-forward ratio quantiles from earlier test seasons only.

### 3.2 First backtest numbers

ADP top-150 pool, 2015-25, PPG weighted by games played, 4+ games. "Yrs < ADP" is the number of seasons a model beat the ADP curve on MAE.

| Model | MAE | RMSE | bias | rho | top-12 hit | yrs < ADP |
|---|---|---|---|---|---|---|
| **ADP curve (the bar)** | **2.494** | 3.157 | 1.007 | **.550** | .675 | - |
| 50/50 model + ADP | 2.490 | 3.146 | 1.003 | .543 | .671 | 5/11 |
| market-anchored (anchor_mix) | 2.531 | 3.195 | 0.999 | .549 | .665 | 2/11 |
| ensemble (ridge+GBM, with ADP) | 2.577 | 3.248 | 0.999 | .510 | .649 | 1/11 |
| ridge, stats only (no market) | 2.713 | 3.460 | 1.024 | .441 | .631 | 1/11 |
| naive last-season PPG | 3.103 | 3.936 | 0.976 | .411 | .619 | 0/11 |

**By ADP band (anchor vs ADP curve, MAE):**
- 1-30: 2.837 vs 2.760, 5/11.
- 31-100: 2.447 vs 2.399, 3/11.
- **101-150: 2.444 vs 2.452, 6/11, rho .175 vs flat.** This is the only cell where the model beats the market, in the deep tier where ADP stops ordering anyone.

**By position (anchor vs ADP curve, MAE):**
- QB: 2.535 vs 2.542 (tie)
- RB: 2.920 vs 2.839
- WR: 2.344 vs 2.322
- TE: 1.878 vs 1.870 (rho .564 vs .489, a better ordering)
- Rookies: 2.896 vs 2.794. ADP wins for rookies.

**2019-25 against the outside numbers** (same 676 rows; beat-Clay seasons in brackets):

| Source | MAE | rho |
|---|---|---|
| Clay season sheet (best single source) | 2.393 | .615 |
| ADP curve | 2.437 | .597 |
| anchor | 2.444 | .584 |
| ESPN week 1 | 2.461 | .612 |
| engine week-1 base | 2.591 (bias 1.095) | .581 |

Ensembles (813 rows):
- 1/3 anchor + 1/3 ESPN + 1/3 Clay: **2.356, rho .619. That is -2.1% vs Clay, 5/6 seasons.**
- anchor + ESPN: 2.372 (5/6).

**Season totals** (what a draft buys; zero for players who never played):
- ADP curve: MAE 49.7, rho .501, top-24 hit .659.
- Ours: MAE 50.5, rho .469, top-24 hit .634.
- The games-played model is the weak link (corr .23 with actual games).

**Ranges.** p10-p90 covered 82.8% of PPG and 84.7% of season totals (target 80, so slightly wide; QB 78%, RB/TE 84%).

**Verdict, stated plainly.** The v0 prototype does **not** beat preseason ADP on its own. This matches the 09-16 season-long harness, where Clay owned the top 150. The market is the hardest baseline in fantasy, just as the closing line is in betting.

The prototype is still useful in three ways:
1. As a 1/3 ensemble member with ESPN and Clay, it is the best preseason number we have measured (-2.1% vs Clay).
2. It beats the market in ADP 101-150 and on TE ordering.
3. It is a fully walk-forward, Clay-free pipeline we can now improve with the right inputs.

### 3.3 Design of the full 2027 preseason sim

**Week-0 build order (each step feeds the next):**

1. **Team layer (part 8/17).** De-vigged win totals give a team rating, from which come:
   - schedule-based game environments for all 18 weeks: spread, implied total and plays, via the measured script elasticities in part 17
   - updated to real look-ahead lines once books post them (May)
2. **Player prior** = the market-anchored model:
   - ADP curve prior + shrunk residual, as in 3.2, plus three new inputs:
     - (a) season player props once posted (June-August): de-vigged, read as medians, converted with a games-missed draw
     - (b) consensus season projections (ESPN, Clay, FantasyPros), used as ensemble members
     - (c) depth charts and camp role
   - Ensemble weights fit walk-forward by ADP band, ATC-style.
3. **Volume consistency.** Player shares x the team environment must reproduce the team's pass/rush volume. This is a check, not a model: volume-first as a model was rejected 10-08, at +9.6%.
4. **Games-played model.** Rebuild it on injury history (`sim_prior_health.js` already exists in-season), age and position. Today's corr is .23, and this is where ADP beats us on totals.
5. **Season sim.** The existing engine `simSeason` with:
   - the coupled team shocks
   - team season shocks seeded from the team-rating uncertainty (sd ≈ 2.0-2.5 wins, part 8)
   - hot updating
6. **Hand-off to in-season (the update rule, parts 8/14).**
   - Keep the shadow's existing per-position, games-played prior strengths (P), which are already tested: WR prior x5 after one game, QB/RB update early.
   - Swap only the prior they shrink toward, from the current shadow prior to the part-3 ensemble.
   - Re-test the P values on the new prior before week 1.

**Remaining steps, in order:**
1. Fix the games model (injury history, age).
2. Add the ESPN/Clay/FP season projection archive for 2019-25 as features/members. ESPN week 1 is already cached; FantasyPros season history would need a public pull (ask first).
   - **Superseded 2026-11-21 (Jack: "Keep it in-house"):** outside projections do NOT go into the prior as features or members. They are benchmarks only (see Decisions below).
3. Add season props. No free history exists (research part 5), so start a 2027 capture in the daily betting pull once books post them, and grade on 2027 only.
4. Feed the 2027 prior into the shadow harness as the week-1 prior and re-run `backtest_noclay_weekly.py` / `ablate_shadow_next.py` on 2019-25.
5. Build the team-rating → 18-week environment generator (part 17) and wire it as a fallback for weeks with no posted line.
6. Formats and values (parts 10, 18, 21, 22): a settings-driven VOR layer over the season distribution.

---

## Part 4. Ranked in-season proposals (live engine; Jack approves)

Only items with backtest evidence are listed. "Gain" is the measured or best-estimate effect on the graded objective.

| Rank | Proposal | Evidence | Est. gain | Confidence |
|---|---|---|---|---|
| 4.1 | **Add ESPN's weekly projection as an ensemble member** of the weekly number (50/50 with the shadow, before the book anchor) | `backtest_best_rankings.py` 09-17: rho .388 vs .378 each alone, 6/7 seasons, best at every position from week 5. New pairwise (part 13): ESPN's side wins 51.7% of the 20.8% of start/sit pairs where we disagree (-0.36 pts per such decision for us). ESPN weekly is already pulled live (consensus board). | rho +.010, MAE ~-1.5% | high (long-standing; Jack's call because it is no longer purely our model) |
| 4.2 | **Late-season consensus weight**: from week 14 on (fantasy playoffs), raise the consensus/ESPN share, even if 4.1 is not taken | ROS table (part 14): ours ahead weeks 2-13 (weeks 11-13 .565-.594 vs ESPN .536-.583), ESPN ahead weeks 14-15 (.543/.494 vs .522/.453); vs-ESPN harness: weeks 15-18 +3.2% worse | ~2-3% MAE in weeks 15-17 | medium (needs a LOYO by week cell before wiring) |
| 4.3 | **Re-tune the book-anchor weight (propW) on 2026 W1-12** | 2026 pooled: shipped 5.71 vs its components 5.44-5.45 on their own rows. `anchor_sweep.py` exists. Book guardrail W1-4 only. | unknown; up to ~2% if the anchor is over-weighted | low (current season only; re-tune is routine) |
| 4.4 | **QB dud mixture test** (injury exit / benching): a q≈.03 near-zero component for QBs only, in the sampler (ranges, league, best ball sims), not the mean | Part 9: real QB rate of scoring < .25x projection is 3.4-5.2% vs gamma 0.2-2.0% in every QB band (n 2,173). The earlier rejected dud mixture was RB/WR low-band only and did not test QBs. | CRPS on QB rows, unknown; matters for superflex and title odds | medium (run CRPS + coverage LOYO first) |
| 4.5 | **Opposing-QB correlation up** (engine game factor: oppQB .19 → ~.25) | Part 15: real QB1-oppQB1 residual r +.25 (n 1,724) vs engine fit .19 | small; mostly DFS / best ball game stacks | medium |
| 4.6 | Existing queue: P-20261023-2 (QB inherit history level), P-20261110-1 (QB ROS tilt), P-20261013-3 (ctxShare re-measure) | see proposals/PENDING.md | as listed there | as listed (unchanged by this review) |

Watch items, not proposals:
- 2026 RB ROS model-low / TE model-high bias (part 14).
- Engine week-1 base 9% low. This is a 2027 item, handled by part 3.

---

## Part 5. Dynasty sims — PARTLY

**What exists.** `build_dynasty_sim.py`: WIN3 (E[VOR] years 0-2 from 30 comps) + 1.5 x YOUTH (years 3-4). It folds in-season, uses conditional JM for rookies, and swaps in the weekly-sim ROS for year 0. It feeds MFF VALUE / FAIR (0.5·M3 + 0.3·sim + 0.5·KTC on log ranks), live on the site. All of this was validated earlier (see `project_dynasty_sim_value`). Spearman vs realized VOR, FFC dynasty pool 2015-23:

| Model | Spearman |
|---|---|
| Market (FFC dynasty ADP) | .538 |
| Sim v1 | .481 |
| Local-linear | .515 |
| Conditional JM | .554 |
| 75% market blend | .547 |

- ELITE ODDS x market beats the market 9/9 on elite seasons (not live).
- The sim-market gap predicts next-year market moves, Spearman +.25.
- The market still beats the sim on QBs (SF .527 vs .383) and age 30+ (.42 vs .25).

**New this pass (`decisions_backtest.py` F).**
- Age curves, delta method on survivors, median PPG change by age:
  - RB: -7% at 24, -15% at 25, then -20 to -24% from 27.
  - WR: roughly flat to 24, -10 to -16% from 25-29, -29% at 31.
  - TE: +9% at 24, then -15 to -19% from 25.
  - QB: roughly flat 23-32.
- Survival, the share of 10+ PPG players still at 8+ games and 8+ PPG next year:
  - RB: 86% at 24, 67% at 26-27, **45% at 28**.
  - WR: ~80% through 29, 55% at 31.
  - This matches Harstad's RB table (research).
- PPG persistence: r .78 / .74 / .71 at 1 / 2 / 3 years (survivors only, so it is optimistic).

**Verdict.** The comps approach already encodes these curves. The real gaps are QB and age 30+ (the market knows who keeps going) and draft-pick values, which have no history to backtest against.

**Research to borrow.**
- Value = Σ δ^t · survival(age+t) · E[VOR_t] with δ ≈ .85-.90 (Harstad, https://www.footballguys.com/article/HarstadDiP21).
- FantasyCalc builds values from real trades and fits an exponential value scale (https://fantasycalc.com/about).
- KTC applies a consolidation adjustment (part 7).

**2027: should the preseason prior feed dynasty?** Yes, as year 0 only:
- Replace WIN3's year-0 comp value with the part-3 ensemble season total (VOR) in the offseason.
- Keep comps for years 1-4.
- Rookies get the part-20 capital+JM prior.

**Proposals (ranked):**
1. A QB-specific market weight in FAIR. The market beats the sim .527 vs .383 on SF QBs, so raise the KTC share for QBs. Evidence: the existing dynasty backtests. Test with `backtest_fair_qb_weight.py` (exists).
2. A 30+ age band market weight (same logic: .42 vs .25).
3. Pick values: start capturing KTC/FantasyCalc pick prices weekly now, so a pick-value backtest exists by 2028. There is no history today.

---

## Part 6. League sims — PARTLY

**What exists.** `simLeague` (engine.js ~4897):
- correlated player draws
- greedy lineups by mean
- D/ST streaming
- holes filled from waivers
- standings W then PF
- fixed bracket (re-seed optional)

Used by the Sim Lab, the newspaper, and the Sleeper/ESPN/Yahoo SIMS tabs (`pkRunSim` in `sleeper-extension/sidebar.js` ~3196).

**New backtest (`decisions_backtest.py` H).** The stored newspaper moneylines for weeks 5, 6 and 10 (`league_exports/newspaper/cache/*_lines_w*.json`, `*_simlab_w*.json`) were matched to the real results in the ESPN pulls: 4 leagues, 73 matchups.

| Measure | Result |
|---|---|
| Favourite won | 61.6% (predicted 62.5%) |
| Brier, sim | **.211** |
| Brier, points-for-to-date baseline (sd 30) | .233 |
| Brier, coin | .250 |
| Margin MAE vs sim spread | 26.4 |
| SD of the miss | 33.6 |
| Calibration | .55→.38 (n29), .63→.73 (n30), .73→.80 (n10), .85→1.00 (n4) |

- The margin miss matches the ~32.5 benchmark (research).
- The near-coin-flip bin underperformed, which is noise at n 29.

**Verdict.** The weekly matchup odds beat the obvious baseline. Seventy-three games is far too few to tune on. Playoff and title odds cannot be graded until 2026 week 17.

**Gaps (from the code audit):**
- no two-week championship rounds
- no median / all-play games
- no division winners or H2H tiebreakers
- Yahoo uses a synthetic schedule
- ESPN imports miss TE premium
- Questionable players are mean-scaled, not drawn in/out
- no in-season trades or waivers beyond hole-fills

**Research to borrow.**
- The better team wins ~58% of matchups, and the best team wins the title only ~1/3 of the time (https://www.footballguys.com/article/2024-dynasty-in-theory-should-best-team-win).
- A favourite above ~35-40% title odds in a 12-team league is a warning sign of too little variance.

**2027.** Draft-day league odds = `simLeague` on drafted rosters with the part-3 season distributions. The part-3 ranges (82.8% coverage) are honest enough for that.

**Proposals:**
1. **Pre-register a 2026 end-of-season grade** of the week-4/9/10 title and playoff odds already saved in `league_exports/newspaper/cache/*_simlab_w*.json`. Script it now (Brier vs the PF baseline) and run it after week 17.
2. Draw Questionable players in/out per sim (play odds from INJ_PLAY) instead of mean-scaling.
3. Add two-week finals, median games and division tiebreakers as league settings.

---

## Part 7. Trade sims — DESIGN

**What exists (read, not changed).**
- **Site calculator** (`MyFantasyFootball Files/app.js`):
  - `_getTradeValue` ~37882 is a board rank through a Flock-fit curve.
  - `_packageAdjustedTotal` ~37933 handles 2-for-1 by discounting extra pieces by a roster-spot cost and weighting them extraPieceW^k (0.875 redraft / 0.96 dynasty).
  - `_vorTradeImpact` ~17851 checks roster fit week by week on means.
  - No title-odds delta on the site.
- **Sim Lab Trade Analyzer and the Sleeper helper** (`tradeImpactRun`, sidebar.js ~5762) do a same-seed before/after `simLeague`, giving ΔW / Δplayoffs / Δtitle.
- **Dynasty:** MFF VALUE (KTC-blended FAIR).

**Audit.**
- Redraft values are not sim-driven. They come from a board-rank curve fit to another calculator, which is calibration to a tool, not to outcomes.
- No trade verdict has ever been graded.
- Stored real trades are an 8-day rolling window with names only (`data/real_trades_redraft.json`), so no verdict backtest is possible today.

**Research to borrow.**
- Roster-aware value: Σ over weeks of optimal-lineup points after minus before, plus the freed bench slot (a genetic-algorithm trade search, https://arxiv.org/abs/2511.17535v1).
- Same-seed Δtitle with common random numbers.
- Show fair (sim) vs market (KTC) side by side. Market price vs fair value is exactly the sportsbook idea.

**2027.** In the offseason and at draft time, redraft trade values should come from the part-3 season VOR. Dynasty values come from part 5, with the part-3 year 0.

**Proposals:**
1. **Start logging every synced-league trade with timestamps** (Cloud Function `exportLeagueTrades` already exists), plus the sim's ΔROS / Δtitle at the time. After 8+ weeks, grade whether the side the sim favoured gained ROS points and title odds. This is the only way to get a verdict backtest.
2. Replace the redraft value curve with sim ROS VOR (keeping consolidation via the lineup method), then A/B it against the current curve on the logged trades.
3. Show Δtitle on the site calculator for synced leagues (the engine already computes it in the helper).

---

## Part 8. Season sims — NFL team sims FULL; fantasy season ranges PARTLY

### 8.1 NFL team season sims (new: `team_sims.py`, 2013-2025)

No NFL team season sim exists in the engine today. The prototype:
- Ratings: MARKET ratings solved so the de-vigged win totals hold over the real schedule, vs 538-style ELO, vs a 2/3:1/3 BLEND.
- 10,000 sims of the real schedule each.
- "Hot" variant: in-sim rating updates of 0.08 x the margin surprise.

| Model | wins MAE | RMSE | p10-p90 cover | Brier P(over) | Brier playoffs | Brier division |
|---|---|---|---|---|---|---|
| MARKET (frozen) | 2.160 | 2.642 | **70.4%** | .2454 | .2163 | .1608 |
| **MARKET hot** | 2.162 | 2.642 | 87.7% | .2459 | **.2063** | **.1567** |
| ELO hot | 2.328 | 2.820 | 83.9% | .2686 | .2153 | .1658 |
| BLEND hot | 2.183 | 2.660 | 87.3% | .2487 | .2060 | .1574 |
| market's own P(over) | - | - | - | .2460 | - | - |
| no-information | - | - | - | .2500 | .2398 | .1875 |

- Playoff calibration (MARKET hot): .07→.06, .18→.27, .33→.32, .50→.44, .66→.65, .81→.81.

**Findings.**
- The market beats Elo on every measure.
- Blending Elo in adds nothing preseason; the market already prices last year.
- **Frozen ratings give ranges that are far too narrow (70%).** The sim must carry rating uncertainty (hot updates or a season rating shock). With k .08 coverage overshoots to 88%, so the right k is ~.04-.05.
- We cannot beat the win-total market on overs/unders (.2459 vs .2460). That is the expected, honest answer.

**In-season update (Part C: banked results plus simulated rest):**

| Week | Model | ROS wins MAE | playoff Brier |
|---|---|---|---|
| 4 | frozen preseason | 1.863 | .1742 |
| 4 | Elo-updated | 1.899 | .1658 |
| 4 | closing-spread ratings | 1.829 | .1660 |
| 8 | frozen | 1.519 | .1411 |
| 8 | Elo-updated | **1.456** | **.1270** |
| 8 | spreads | 1.476 | .1301 |
| 12 | frozen | 1.054 | .1059 |
| 12 | Elo | **.970** | **.0970** |
| 12 | spreads | 1.007 | .0983 |

- Updating on results is worth a lot by week 4.
- Elo on results and the market's spreads are about equal (spreads beat Elo in 7/13 seasons at week 8).
- **Update rule for 2027:** start at the market rating and update with Elo-style K≈20 on results. The FPI/538 practice (prior weight fading) is confirmed.

### 8.2 Fantasy season and ROS player sims

**What exists.**
- `simSeason`: banked weeks, coupled shocks, scenarios.
- Coverage evidence: season ~80-82%, ROS at weeks 5/9/13 81.6-84%.
- Team-total coverage 83% after coupled shocks.
- The 2026 ROS locks are graded weekly (`grade_ros_lock.py`).

What the sim models today:
- injury and games missed: yes, via the season shock mixture and INJ_PLAY
- teammate correlation: yes
- schedule strength: through the re-rated future team totals

**2027 update rule.** The preseason prior (part 3) becomes the shadow's prior. Per-position games-played shrinkage stays as tested (WR x5 after game 1, QB/RB update fast).

**Proposals:**
1. If an NFL team sim ships (survivor, pick'em, playoff odds for the NFL channel), use market ratings with in-sim rating uncertainty, k≈.05, tuned to 80% coverage.
2. Pre-register the 2026 end-of-season grade of the stored fantasy season-sim playoff/title odds (part 6).

---

## Part 9. Best ball — PARTLY

**What exists.**
- `simBestBall` (engine ~5270): best-ball weekly max, Eliminator chain, pods.
- `bbFieldRun` / `simBBField` (~5633/5954).
- Sim Lab BEST BALL tab.
- Site Underdog standings (actual points only).
- Underdog helper with BBM advance-rate tables (`underdog-extension/engine.js` `bbmBuildConditionalRates` ~833).
- Teammate coupling is OFF for best ball (independent season shocks).
- No backtest of advance odds vs realized BBM outcomes exists, even though `E:\MyFantasyFootball\MyFantasyFootball Files\Best Ball Mania Files` (BBM VI) and `bbm_field/bbm7_field_v3.json` are on disk.

**New: weekly shape and spike rates (`decisions_backtest.py` C, 2019-25).** Real outcomes vs a moment-matched gamma, half-PPR:

| pos / proj band | CV | P(≥2x) real / gamma | P(≥proj+10) real / gamma | P(<.25x) real / gamma |
|---|---|---|---|---|
| QB 12-16 | .50 | .031 / .043 | .112 / .094 | **.052 / .020** |
| QB 20+ | .37 | .004 / .012 | .108 / .116 | **.020 / .002** |
| RB 8-12 | .68 | .103 / .085 | .110 / .085 | .070 / .077 |
| WR 8-12 | .68 | .098 / .087 | .093 / .086 | .092 / .081 |
| TE 8-12 | .69 | .110 / .088 | .101 / .080 | .075 / .084 |

- Gamma reproduces RB/WR/TE ceilings well, slightly short on 2x weeks in the mid bands (~1-2 points).
- QB dud weeks are badly under-sampled (proposal 4.4).

**Research to borrow.**
- Week 17 decides most of the money.
- Game stacks raise final-win odds ~50%.
- Construction 2-3 QB / 5-6 RB / 7-9 WR / 2-3 TE.
- Closing-ADP value is the process metric (https://establishtherun.com/best-ball-mania-manifesto-a-guide-to-winning-big-on-underdog-fantasy/, 4for4 BBM V guide).

**2027 (drafts open in spring).** By ~March 2027, the part-3 prior must deliver:
- season PPG and total distributions
- weekly distributions from the part-9 shape table
- a playoff-week (15-17) schedule view from the part-17 team environments

It must update weekly through August as ADP moves.

**Proposals:**
1. **Backtest `simBestBall` advance odds on BBM VI** using the on-disk rounds CSVs with each team's real roster and real weekly points, to check calibration of P(advance).
2. Turn teammate coupling on for best ball (it is off), at least for week-17 game stacks. Test on BBM VI.
3. QB dud mixture (4.4).
4. Add a closing-ADP-value report per portfolio.

---

## Part 10. Draft sims — DESIGN

**What exists (read only).**
- Site mock draft (`app.js` `cpuPick` ~44151): ADP plus needs and archetype; a random pick among the top 3 with weights 0.6^i.
- Grades by board rank minus pick (`gradePickValue`).
- Sleeper `recommendPicks` (sidebar.js ~1270): VOR, tiers, capital shares, ADP-trust decay.
- "Should last" check: deterministic, ADP > next pick + 2.
- Underdog `recWaitMult`.
- No availability-odds model, no draft-forward sim, and no backtest of recommendations or grades.

**Audit with what we have.** Part 3 shows the market (ADP) is the best single draft-order predictor for the top 150. Our edge is in the deep tier (ADP 101-150) and in TE ordering. A recommender that leans on ADP early and on the model late matches the evidence (Sleeper's ADP-trust decay to round 12 has the right shape).

**Research to borrow.**
- FFC ADP SD ≈ 0.1 x ADP in rounds 2-11, wider late and for QB/TE (https://fantasyfootballcalculator.com/adp/standard/12-team/all/2020).
- P(available at pick k) = 1 − Φ((k − 0.5 − ADP)/SD).
- Start-count VBD baselines (https://www.footballguys.com/article/HarstadVBDBaselines).
- Draft grades are worth only about ±5 points of win% (Yahoo 2023).

**2027: what the prior must deliver, and when.** The draft tools are the main consumer:
- By late July: rankings, tiers (Gaussian-mixture on the ensemble), ranges and VOR by format (part 21/22 layer), updated daily from ADP.
- Feeds draft-day league odds (part 6) and best ball (part 9).

**Proposals:**
1. Availability odds from ADP + SD. FFC publishes stdev, high and low; we cache only the mean, so ask before a new pull.
2. Replace "ADP > next pick + 2" with P(available) ≥ 50% in the helpers.
3. Grade mock-draft grades and helper recommendations on 2026 synced leagues after week 17 (stored drafts: `newspaper/cache/*_draft*.json`).

---

## Part 11. Playoff sims

### (a) Fantasy playoffs — DESIGN

**What exists.**
- `simLeague` bracket: seeds by W then PF, byes, optional re-seed, single-week rounds.
- Playoff SOS: `_mtBuildPlayoffSos`, site app.js ~65398.
- Fantasy-playoff weeks graded on rank (`backtest_fantasy_playoffs.py`: tie with ESPN).

**Gaps.**
- two-week rounds
- H2H/division tiebreakers
- late-season rest risk for locked-in NFL teams: only via the week-18 exclusion; week 17 rest is not modelled
- the week 15-17 ESPN gap (part 1)

**Proposals:** 4.2 (late-season consensus weight); the part-6 pre-registered grade; the two-week round setting.

### (b) NFL playoffs — FULL (prototype)

There is no NFL playoff sim in the engine.

**Preseason.** The `team_sims.py` playoff odds:
- Brier .206 vs no-information .240.
- Market beats Elo; calibration is shown in part 8.

**At bracket time (`nfl_bracket_sim.py`).** Ratings from all regular-season closing spreads, 20k sims with re-seeding, 13 postseasons:
- Advance-odds calibration .08→.06 (n345), .28→.29, .50→.55, .68→.83. Brier .099.
- Sim favourite title odds 18-35%, consistent with the research guard to keep ≤ ~25-30%.
- Slight under-confidence at the top.

**Week 4/8/12 updates** (part 8): Elo / spread updates cut playoff Brier from .174 to .127 to .097.

**2027.** Week-0 NFL playoff odds come straight from the win-total ratings. A weeks 15-17 schedule-strength view for draft season comes from the part-17 environments.

---

## Part 12. Waiver sims — DESIGN

**What exists (read only).**
- My Teams waiver wire `_mtRenderWaivers` (app.js ~68568): FA PPG ≥ weakest starter + 0.5.
- SIM VOR waivers and UPSIDE VOR (stash) at ~17240-17272.
- Helper `waiverRecs`: Sleeper ~2798, ESPN ~2854, Yahoo ~1605.
- Social waiver builder: `tiktok_bot/src/posts/monday.js`, with static FAAB ranges.
- Ask Jack waivers: humans answer.
- No FAAB model, no waiver-priority model, and no saved waiver-call backtest (the 10-12 scratch study, e.g. TE route ≥75% + target share ≥25% → TE12 ROS 32%, was not saved).

**Evidence that bears on waivers.**
- The role-news study: news tags give no bump (next 3 games x0.96-1.02).
- The fill-in volume reversion rule.
- `backtest_option_vor.py`: stash top-12 +5/+8 points.

**Research to borrow.**
- Median winning bids per $1,000: WR $29, RB $21, QB $21, TE $20, DST $10, K $3. Big bids rarely pay. Adds volume peaks in week 6 (https://www.fantasypros.com/2025/09/fantasy-football-waiver-wire-pickups-win-championships/).
- Bid = argmax (V − b)·F_maxrival(b), a first-price sealed-bid auction with shading.

**2027.** Week-1 waiver values come from the part-3 prior's deep tier (ADP 101-150, where the model beats ADP). Usage takes over at the tested shadow update speeds.

**Proposals:**
1. Save and re-run the waiver-call backtest (ROS VOR of the top-ranked FA vs the 2nd-5th FA and vs the user's worst starter) on 2019-25 harness rows.
2. A FAAB model seeded from the public bid medians, scaled by league budget and the user's own lineup gain.
3. Grade helper `waiverRecs` on synced leagues (logged recommendations needed).

---

## Part 13. Start/sit sims — FULL

**What exists.**
- Site Start/Sit (`app.js` `_sstRender` ~35507): highest sim mean wins, shown with book projection, spread, team total and weather.
- Helpers: `optimalLineup` greedy on means.
- Sleeper matchup win% is a normal approximation (`matchupOddsOf` ~2354).
- No pairwise P(A > B) and no floor/ceiling advice on the site, although Sim Lab samples full distributions.

**New backtest (`decisions_backtest.py` A).**
- 236,411 player pairs, 2019-25, both players projected ≥7, |gap| ≤5, different teams.
- Model = harness "live" number.
- P(A > B) from a leave-one-season-out spread model.

| Measure | Result |
|---|---|
| Favourite wins | **58.3%**, predicted 58.5%, Brier .2393 (coin .25) |
| Calibration bins | .52→.52, .57→.57, .62→.62, .67→.66, .70→.68 |
| Close calls (gap <1) | 52% |
| Clear calls (gap ≥3) | 64% |
| Same position vs flex | identical (58.2 / 58.5%) |
| vs ESPN | ESPN 59.0%. On the 20.8% of pairs where they disagree, the model's pick wins 48.3% (−0.36 pts per decision) |
| vs season-to-date PPG | model +1.45 pts per decision where they disagree (wins 55.6%) |

**Verdict.**
- The odds are honest: a 65% call hits ~65%.
- Following our mean is a sound start/sit rule, slightly behind ESPN's final number on the pre-book base.
- The live book anchor (2026: prop-anchored MAE ≈ ESPN) likely closes most of that gap, but it cannot be replayed historically.

**Design: matchup-aware advice.**
- Show P(A > B) (already computable).
- When the user's matchup win probability is below 40%, break near-ties (|gap| < ~0.3σ) toward higher variance and toward players correlated with his own stack; above 60%, the reverse (research: Footballguys variance theses, https://www.footballguys.com/article/2026-dynasty-in-theory-week06-13-theses-on-variance).

**Proposals:**
1. Add a pairwise P(A > B) to Start/Sit and the helpers (sd model as in A).
2. Proposal 4.1 (ESPN member).
3. Risk-mode tie-breaks (design; needs the league sim's win probability on the page).

---

## Part 14. ROS rankings — FULL (history) + 2026 read

**What exists.**
- ROS = the mean of remaining weekly rows (site `seasonPpg`, helpers "Proj ROS").
- ROS locks graded weekly (`grade_ros_lock.py`).
- Tier boards use these ROS numbers.

**New backtest (`decisions_backtest.py` B).**
- Week-k number vs actual per-game rest of season (3+ games left), within position.
- Pool: ADP top 150 or projected ≥8.
- Spearman, 2019-25:

| Week | model | season-to-date PPG | preseason ADP | ESPN week-k |
|---|---|---|---|---|
| 2 | **.602** | .282 | .592 | .593 |
| 4 | **.609** | .468 | .557 | .555 |
| 6 | **.620** | .532 | .583 | .572 |
| 8 | **.615** | .557 | .518 | .591 |
| 10 | .598 | .556 | .516 | .593 |
| 12 | .594 | .542 | .506 | .583 |
| 14 | .522 | .531 | .472 | **.543** |
| 15 | .453 | .454 | .401 | **.494** |

**Crossovers.**
- The model beats ADP from week 2.
- Season-to-date PPG passes ADP at week 7.
- ESPN matches the model around weeks 9-11 and passes it from week 14.
- By position, the model's edge over ADP at week 8 is largest for RB (.675 vs .561) and QB (.475 vs .366).

**Stability and reaction.**
- Median week-to-week move within the top 36 is 2 spots (90th percentile 7).
- The ROS miss vs the last game's surprise has slope +.025 (QB +.035, RB +.029, WR +.016, TE +.022). That is a very slight under-reaction: no overreaction to one game, and no meaningful lag.

**What a ROS number has to handle, and status:**

| Item | Status |
|---|---|
| Remaining schedule | handled (re-rated future totals) |
| Byes | handled (no row) |
| Injury return dates | handled (windows, ramp) |
| Role changes | handled (vacancy pool, fill-in rules) |
| Rookies' late growth | partly (rookie level x1.08 QB/RB) |
| Late-season rest | not modelled |
| Per-game vs total weighting | the site's ROS PPG is per-game; totals live in the season sim |

**Tier-board flag.** The 2026 locks run RB actual/model 1.14-1.15 and TE 0.87-0.94. On a tier board that would rank TEs too high and RBs too low. Before the next ROS tier video:
- check the TE tier against the books and consensus
- do not move the engine on one season

**2027 hand-off.** Week-0 ROS = the part-3 season distribution; then the shadow updates weekly.

**Proposals:**
1. 4.2 (late-season consensus weight, weeks 14+).
2. Add ESPN's ROS or FantasyPros ROS as a member from week 14, ATC-weighted.
3. Grade the 2026 RB/TE lock bias on history: does the shadow's later-weeks RB number run low on 2019-25 at weeks 5-7? If yes, it's a layer test.

---

## Part 15. DFS — DESIGN + PARTLY

**What exists.** No DFS product: no salaries, no ownership, no optimizer, no pick'em higher/lower logic. The engine's correlated weekly sampler is the core a DFS tool would need.

**New backtests.**
- DraftKings-scored weekly shape (part 9 table, DK rows): gamma fits DK spike rates as well as half-PPR. QB duds again under-sampled (real 1.6-4.5% vs gamma 0.3-1.4%).
- Residual correlations, half / DK:

| Pair | half | DK |
|---|---|---|
| QB1-WR1 | +.341 | +.351 |
| QB1-WR2 | +.323 | +.322 |
| QB1-TE1 | +.291 | +.278 |
| QB1-RB1 | +.038 | - |
| WR1-WR2 | +.011 | - |
| RB1-RB2 | +.007 | - |
| RB1-WR1 | −.029 | - |
| opposing QB-QB | **+.251** | - |
| opposing RB1-RB1 | −.097 | - |

The engine's structure matches. Bring-back (opposing QB) is under-weighted (4.5).

**Research to borrow.**
- Lineup sims against a modelled field; ownership leverage.
- Opponent modelling with Dirichlet ownership (Haugh & Singal, https://pubsonline.informs.org/doi/pdf/10.1287/mnsc.2019.3528).
- Top-heavy contests want correlated, high-variance lineups (https://arxiv.org/abs/1604.01455v3).
- Salaries and pick'em lines are set off sportsbook props.
- Legal note, as a fact: DFS and pick'em rules vary by state. A site tool would give projections and lineups only.

**2027 verdict.** Not worth building as a product before best ball and start/sit pairwise odds land. Missing pieces and effort:
- salary/slate feed
- ownership model
- DK/FD scoring variants (trivial)
- optimizer + field sim

That is ~3-4 weeks. Parts 9 and 13 deliver the distributions and correlation for free.

---

## Part 16. Player props — PARTLY

**What exists.**
- The engine anchors to props (`propAnchorMean`, face-value lines since 10-07, `BOOK_CAP` +20%).
- Sim Lab LINES view (model vs lines).
- Tail-market harness `backtest_tail_markets.py`.
- No prop-pick product on the site.

**Cited 2026 results (W1-6, `data/tail_backtest_latest.txt`, 1,758 player-weeks).**
- Anytime-TD Poisson vs the 2+ market: the 2+ market read is worse (+0.04 pts MAE, CI excludes 0), so keep Poisson.
- Heavy favourites (P ≥ .55) score 1.01 TD/g vs Poisson .84 (n 82, watch).
- Price-skewed means are not better than face value for any stat (rec −0.03, CI touches 0; rcy +0.21; ry +0.40). Keep face value.
- Juiced side landed 60% on receptions (n 104), which is suggestive only.
- W1-4 face-value market and model MAE tied 4.66.
- The model is closer when it is below the market on RB/TE.
- The model loses when 1+ above the market on WR3/4 (`project_prop_line_face_value`).

**Not run.** A hit-rate-vs-52.4% test of the sim's over/under leans by stat with an out-of-sample split. Weeks 1-11 of 2026 lines exist (`betting_lines_2026.json` weeklyProps), and that is the next step. Be strict: one season and many stats means a lean must clear a pre-registered bar.

**Use for the engine.**
- Closing props are the best free benchmark. Grade the weekly projections (part 1) and start/sit (part 13) against them every week.
- History before 2026 is the gap. There is no free archive (research part 5), so the daily capture we already run is the dataset.
- Season props tie to part 3: capture them in 2027.

**2027.** A sim-vs-line view (median vs line, our P(over), de-vigged market P) is cheap (~1 week) on the LINES view. It suits videos as information. Legal note: betting legality varies by state; this would be information, not betting advice.

**Proposals:**
1. Over/under lean hit-rate backtest, 2026 W1-11, stats pre-registered.
2. Season-prop capture in 2027.
3. Re-check the heavy-favourite TD cell at the end of 2026.

---

## Part 17. Game sims — FULL (market inputs)

**What exists.** The engine does not sim games:
- It takes team context from book lines, plus re-rated future totals for weeks with no line.
- `drawWeekEnv` draws a correlated game factor, but never a score or a winner.
- No team ratings, plays or pass-rate model.

**New backtest (`team_sims.py` Part A), REG 2013-2025, 3,407 games, the closing market as the benchmark.**

| Item | Result |
|---|---|
| Margin − closing spread | mean +0.04, **sd 12.87**, MAE 9.94 |
| Total − closing total | mean +0.39, sd 13.24, MAE 10.50, skew +0.31 |
| Win prob from closing spread (normal, walk-forward sd) | Brier **.2114**, log loss .6125 |
| De-vigged moneyline | Brier **.2106**, log loss .6106 (hold 3.0%) |
| Calibration (spread) | .15→.16, .27→.23, .36→.32, .43→.43, .57→.54, .65→.66, .74→.77, .85→.91 |
| Key numbers, real vs normal sim | margin 3: **14.4% vs 5.5%**; 7: 8.5% vs 5.0%; OT 5.6% |
| Blowouts ≥21 | 16.8% real vs 15.2% sim |
| Shootouts (≥ total + 14) | 15.3% vs 14.6% |
| Duds | 13.6% vs 14.4% |
| Implied team total vs points | bias +0.19, MAE 7.31, sd 9.23, r .39; flat by band (actual/implied .99-1.02) |
| Game script, pregame | dropback rate −0.52 pts per point of expected margin; plays +0.31 per point of implied total |
| Game script, realized | a 14-point surprise moves pass rate −6.0 pts; team plays sd 8.5; corr(plays, opp plays) −.43 |

**Verdict.**
- The closing market is calibrated and unbiased. Beating it is not a realistic goal.
- Elo (no market) is clearly worse: Brier .2203, 64.7% straight-up vs 66.6%.
- **Anchor every game environment to the de-vigged market whenever a line exists.** Use our ratings only for weeks with no line yet (far-out weeks, rest of season, the 2027 preseason). The engine already does this; keep it.
- A normal margin model misses the key numbers by a factor of 2.5. If a game sim is built, sample margins from the empirical distribution around the spread. This matters for DST/K and game-script features.

**Effects on other parts.**
- Part 1 / part 13: already market-anchored.
- Part 8 / part 11: team ratings from win totals then spreads.
- Part 9 / part 15: the week-17 environment for stacks.
- Part 16: team totals feed props.

**2027.** Preseason team ratings (part 8) plus the schedule give spread and total for all 18 weeks. Use the script coefficients above for plays and pass rate. Replace with the May look-ahead lines, then weekly closes. In-season, update ratings with Elo-style K≈20 between lines.

**Proposals:**
1. Build `team_env.py`: ratings → spread/total/plays/pass rate for unlined weeks. Feed `buildSchedule` as a fallback behind book lines (no change when lines exist).
2. Empirical margin sampler (key numbers) for any game-outcome product.
3. A play-by-play sim is not worth its cost over this top-down, market-anchored layer.

---

## Part 18. Auction drafts — DESIGN

**What exists.** No auction values anywhere:
- The site's draft board says "Auction drafts aren't supported on the board view yet" (`app.js` ~68715).
- The helpers detect auction drafts but have no dollar logic.

**Design.**
- Dollars = (VOR from the part-21/22 settings layer) mapped to the league budget. Classic: $1 per roster slot, the rest split by VOR share among starters, with a calibrated starter/bench split (~85-90% on starters).
- Then a star premium fit to real AAV: real auctions pay convexly for elites.
- Live inflation = (money left − $1 x slots left) / (VOR left).
- Simulated bidders = AAV + noise, with budget depletion.

**Backtest status.** No historical AAV is on disk. Proposal: capture public AAV (ESPN/Yahoo/Sleeper average auction values) through the 2027 preseason before building the stars-and-scrubs vs balanced backtest.

**2027 deliverable.** Dollar values by format with ranges and tiers by late July, tied to part 10 tiers, part 5 keeper cost and part 6 draft-day odds.

---

## Part 19. Keeper leagues — PARTLY

**What exists.**
- Keeper is treated as dynasty on the site (`app.js` ~5348, ~66152).
- No keeper-cost logic, no "who should I keep" tool, and no keeper-adjusted draft pool.

**New backtest (`decisions_backtest.py` E).**
- 12-team half-PPR, keep at last year's draft round.
- Pick value curve: walk-forward isotonic of VOR on ADP.
- 1,308 player-seasons 2016-25.

| Measure | Result |
|---|---|
| Market-implied surplus (this year's ADP value − round cost) vs realized surplus | r .385, Spearman .416 |
| Quintiles, predicted → realized | −26→−21, −7→−6, 0→+5, +6→+12, **+26→+24** (56% positive) |
| Late-round keepers (round 10+) | +8 VOR mean, 32% positive; with a 1-round penalty +6 |
| Round 1-2 players kept at their cost | −3 realized (market said −10); stars are slightly better keepers than the curve implies |

**Verdict.** Ranking keepers by ADP-implied surplus works (top quintile is clearly positive). Part 3's model should add value in the deep tier, where late-round keepers live.

**Design / 2027.** Keeper decisions are due in August, so the following must be ready by early August:
- the part-3 values
- a pick-value curve by format
- the dynasty multi-year view for multi-year keepers

The tool needs:
- the league's keeper rules (round penalty, years limit, auction price escalation)
- re-pricing the draft pool after everyone's keepers

That is ~1-2 weeks of work on top of parts 3 and 10.

---

## Part 20. Devy / prospect model — PARTLY

**What exists (site, read only).**
- JM score (`data/jm_scores.json`, 21 hand-weighted college/combine/draft components).
- Devy board: `jm_devy_ceiling.js`, `jm_devy_floor.js`.
- Career grades (`data/jm_career_grades.js`).
- Prospect pages.
- In the engine, JM enters the shadow ridge prior (RB weight .75) and the dynasty conditional JM.

**New backtest (`decisions_backtest.py` G).** Drafted QB/RB/WR/TE 2014-23 with a JM score (512 of 791). Target = NFL years 1-3 half-PPR points. Leave-one-class-out ridge:

| Pos | n | rho capital only | rho capital + JM | MAE capital → +JM | starter-season rate R1 / R2 / R3 / R4+ |
|---|---|---|---|---|---|
| QB | 73 | .679 | .705 | 144 → 142 | 58 / 20 / 0 / 8% |
| RB | 140 | .638 | .636 | 135 → 129 | 82 / 65 / 43 / 12% |
| WR | 205 | .590 | .619 | 108 → 108 | 62 / 28 / 28 / 3% |
| TE | 94 | .574 | **.653** | 67 → 61 | 44 / 15 / 19 / 4% |

**Verdict.** JM adds real information on top of draft capital for TE (+.08 rho) and WR/QB (+.03). It adds none for RB, where capital is everything.

**Caveat.** JM's weights were hand-tuned with these classes visible. The 10-01 graded LOYO re-tune was no better out-of-year, so the true out-of-sample gain is likely smaller than shown.

**Not done.** The true devy test (freshman/sophomore score → eventual capital and NFL outcome, with widening uncertainty). This needs the college-year snapshots the site has (`college_stats.js`, college weekly files).

**Hand-off.**
- Rookie prior = capital + JM (+ landing-spot team environment from part 17), with honest ranges, into part 3 (preseason rookies) and part 5 (dynasty).
- Rookie drafts (part 10) and pick values (part 7) read it.

**2027 calendar:**

| Date | Item |
|---|---|
| Dec 2026 | end of the college season |
| Jan 2027 | declarations |
| late Feb - Mar | combine |
| late Apr | NFL draft; the capital-based prior goes live |
| May | rookie drafts |

**Proposals:**
1. A true devy backtest from the college-year snapshots.
2. Use the mock-draft consensus as projected capital before the draft (`data/draft_proj.js` exists) and grade it vs real capital.
3. Keep JM out of RB rookie pricing beyond capital (no gain).

---

## Part 21. Superflex — PARTLY

**Today.**
- Engine/league sims: a SUPER_FLEX lineup slot (`SLOT_ELIGIBLE`) and `scoringFromLeague`. League odds use the real lineup.
- Dynasty: separate SF value builds.
- Site/helpers: SF ADP (`sfa`) and SF capital shares in Sleeper `recommendPicks`.
- The SF consensus blends 1QB ROS + a QB bump (no FP ROS SF list).
- So: a real re-pricing in sims, and part-flat bumps in rankings.

**New (`decisions_backtest.py` D), season VOR 2015-25, 12-team PPR.**
- QB starters go from 12 → 24.
- QB replacement drops from 258 to 178 points.
- QB share of the top-36 VOR goes from .09 to **.34**.
- SF QB replacement by league size: 10 teams 205, 12 teams 178, **14 teams 139**. Scarcity grows fast with league size.
- 2QB is the same as SF at the season level here, because the SF slot is always a QB.

**Gaps.**
- No historical SF ADP/KTC to compare market vs results. Start capturing.
- QB dud risk (4.4) matters more in SF.

**Proposals (and which sim):**
1. A settings-driven VOR layer (see part 22) for rankings and trade, replacing QB bumps.
2. QB dud mixture (engine sampler).
3. The dynasty SF QB market weight (part 5).

---

## Part 22. TE premium — PARTLY

**Today.**
- TEP is a scoring setting in the engine (`scoringFromLeague` TE bonus).
- Dynasty TEP-specific KTC maps.
- ESPN imports miss TEP.
- Ranking surfaces mostly apply flat TE bumps.

**New (`decisions_backtest.py` D), season VOR 2015-25, 12-team, PPR base:**

| Format | TE starters (incl. flex) | TE repl | TE share of top-36 VOR | TE1-3 VOR / TE4-12 VOR |
|---|---|---|---|---|
| PPR | 12.2 | 133 | .09 | 1.40 |
| TEP 1.5 | 15.0 | 146 | .14 | 1.05 |
| TEP 1.75 | 16.6 | 148 | .18 | 0.90 |
| TEP 2.0 | 18.5 | 150 | .22 | 0.81 |
| 2-TE, TEP 1.5 | 24.0 | 110 | .21 | 0.68 |
| SF + TEP 1.5 | 15.1 | 146 | .10 | 1.05 |

- TEP pushes TEs into the flex (12 → 15-18.5 starters).
- **TEP flattens the elite-vs-mid gap** (1.40 → 0.81) rather than widening it, because the premium is per reception and mid TEs catch plenty.
- TEP 1.5 adds 1.29 pts/g on average and 2.86 for 5+ rec/g TEs. Target-driven TEs gain; TD-driven TEs don't.
- Weekly slices (ex post): the TE ranked 13-18 averages 11.0 under TEP 1.5 vs RB25-30 at 10.2 and WR37-42 at 10.4, so a TE2 is a real flex play under TEP, which is not true in PPR (9.2 vs 10.2-10.4).

**One settings-driven value layer (answering the general question): yes.**
- Price every player from the league's own scoring and lineup: replacement by start counts, flex allocation, superflex, TEP, PPR/half/standard, first downs, bonuses.
- Build it once over the season and weekly distributions, instead of per-format patches.
- It needs one module (VOR by greedy weekly lineup allocation over sim draws) used by rankings, draft, auction, trade and waivers.
- ~2 weeks of work. IDP fits the same layer (part 23).

**2027 deliverable.** Rankings/tiers/values by TEP variant and league size by late July. Rookie TE pricing via part 20 (TE year 2-3 breakout curve: the part-5 TE age table shows +9% at 24).

---

## Part 23. IDP — DESIGN

**Today.** The engine has no IDP projections. The only IDP references are `IDP_FLEX: []` and a lineup-fill skip (engine.js ~5047, ~5964).

**Design.**
- Role first: snap share, alignment (every-down LB, box safety, slot CB, edge pass-rush snaps).
- Then tackle opportunity from opponent plays and run/pass mix (part 17 outputs).
- Then pressure → sack conversion, regressed.
- Big plays (INT, FF, TD) close to random.
- Data: snap counts 2012-26 and participation 2016-25 are on disk (`pbp_cache`). Platform position labels need a mapping table.
- The home-scorer tackle bias needs a stadium adjustment.

**Verdict for 2027.** Only worth building if Jack's leagues or audience use IDP. ~3-4 weeks for a first version. It plugs into the part-22 value layer.

---

## Part 24. Kicker and D/ST — PARTLY (cited)

### Kickers

**Today.** The engine kicker has been Clay-free since 10-08: (5.04 + .145 x season-average implied) x 17, split FG/XP; kLevel tuner.

**Evidence (`backtest_kicker_vegas.py`, 2,506 kicker-weeks).**
- MAE 3.57 vs constant 3.60. Within-week rho .12-.15.
- The implied total explains ~1%.
- A kicker's own history is nearly worthless (`backtest_k_fgluck.py`: league prior P=40 best).

**Honest answer.** Kicker weeks are barely predictable beyond the market and the dome.

### D/ST

**Today.** Engine mean = 16.2 − 0.436 x opponent implied total + tuner. Site model `21.691 − 0.7057 x opp implied + 0.0411 x own implied` (season).

**Evidence.**
- Weekly R² ~.09-.14 (Vegas only).
- The opponent matters ~2.7x more than the defense.
- TDs are noise.
- Realized components add nothing (`backtest_dst_regression.py`).
- Sack-proneness rejected 11-21 (`backtest_dst_opp_sack.py`).

### Both

- Streaming pick backtest: `backtest_stream_tol.py` exists (D/ST streaming threshold 1.0); no K streaming backtest.
- The game layer must output team points, plus opponent pass attempts and points for D/ST (part 17).

**Proposals:** none for the mean. A K/DST playoff-week (15-17) schedule view from part 17 for draft season.

---

## Part 25. Guillotine — DESIGN

**Today.** No guillotine sim.

**Reuse.** `simLeague`'s correlated weekly team scores give P(lowest scorer among the teams left) directly: count the sims where a team is last.

**What is new.**
- An elimination loop with chopped rosters returned to waivers.
- A FAAB sequential-auction model: value of a player to this roster's survival and title odds vs the option value of money.
- A start/sit objective = minimize P(last). This is floor-seeking when the team is safe and ceiling-seeking when it is the likely chop.

**Backtest path.**
- Calibrate chop odds on past seasons by simming drafted rosters (needs real guillotine drafts; none on disk).
- Until then, the part-6 matchup calibration is the proxy for weekly distribution honesty.

**2027.** Worth it only if Jack plays or covers guillotine. ~2 weeks on top of `simLeague`.

---

## Part 26. Survivor pools — PARTLY

**Today.** No survivor sim.

**New backtest (`nfl_pools_backtest.py`), 2013-25, closing moneylines for the week picked:**

| Strategy | weeks survived (real) mean / median | simulated expected weeks | P(10+ weeks) | P(survive all) |
|---|---|---|---|---|
| Greedy (biggest de-vigged favourite available) | 4.6 / 4 | **4.18** | 12.4% | 2.41% |
| Season plan (assignment over all weeks: close this week, preseason market ratings later) | 3.7 / 3 | 3.85 | 11.0% | 2.41% |

- Planning with preseason ratings for future weeks lost to greedy in 11/13 seasons.
- The cause: preseason ratings for weeks 8-17 are too stale to plan around.

**Design implications.**
- Future-value planning needs in-season-updated ratings (part 8 Elo/spread updates) and look-ahead lines, re-solved each week.
- A pick-popularity model is the other half (the big contests publish pick percentages). We have none.

**Proposals:**
1. Re-run the plan with ratings updated through the current week.
2. Capture public pick percentages weekly from 2027.
3. Pool-size-aware expected-value picks.

Legal note: paid pools are subject to state law; this would be information, not betting advice.

**Channel idea only.** A weekly "sim survivor pick" short with a tracked record suits @jackb933nfl.

---

## Part 27. Pick'em — FULL (market) ; 27b confidence pools — PARTLY

**Today.** No pick'em sim. Jack's own @jackb933nfl picks record (`social_agent/series/series_log.md`) starts at Week 11 and is not yet graded (0-0). There is nothing to compare yet.

### Straight-up (2013-25)

| Pick the favourite of | Win rate | Season range | Brier |
|---|---|---|---|
| De-vigged moneyline | **66.6%** | 62.1-71.7% | .2106 |
| Closing spread | 66.6% | - | - |
| Elo | 64.7% | - | .2203 |

The gain from picking differently is small. Pool wins come from the strategy below.

### Against the spread

- Elo side vs the closing spread: **50.5%** (n 3,322; break-even 52.4%).
- |Elo − close| ≥5: 53.1% (n 388; noise-level).
- By season: 45-56%.
- Home 49.1%, favourites 48.9%.
- **No edge**, as expected.

Fixed early-week pool spreads: line movement to the close is the one reliable edge. There are no opening lines on disk, so it is not testable here.

### 27b Confidence pools (`confidence_pool_sim.py`)

**Point assignment (1..n per week, 213 weeks).**
- Ranking by the closing p: expected 70.84% of max, actual 71.60%.
- A pure over- or under-confidence error costs nothing, because the order is unchanged.
- Ordering noise of ±.07 in p costs ~1.2 points of % (≈1.5-2 points a week).
- Ranked by ML beats ranked by Elo in 62% of weeks and 10/13 seasons.
- Typical week: 2.2 games with the favourite under 55%, 4.9 under 60%.

**Pool sims with a modelled field** (300 replays per season).
- Field = rivals reading closing p + N(0,.07) noise. No public confidence-pick history exists on disk, so the field is an assumption.

| Pool size | Strategy | weekly prize vs fair | season prize vs fair |
|---|---|---|---|
| 10 | CHALK | 0.27x | **2.35x** |
| 10 | UPSET1 (1 dog, lowest pts) | 0.32x | 2.32x |
| 10 | DOG_MID (1 dog at mid points) | 1.14x | 1.10x |
| 10 | FADE_FAV (dog vs biggest favourite <70%, low pts) | **1.21x** | 0.89x |
| 50 | CHALK | 0.01x | 0.41x |
| 50 | DOG_MID | 1.19x | **1.24x** |
| 50 | FADE_FAV | **1.76x** | 0.86x |
| 500 | CHALK | 0.01x | 0.00x |
| 500 | FADE_FAV | 1.10x | **1.54x** |

**Reading.**
- For a season prize in a small pool, play chalk (expected points win).
- For weekly prizes, or any pool of 50+, take one well-chosen underdog per week. That is 1 of ~16 picks, from the 2-5 games under 60%. Give it low-to-mid confidence, not the top points.
- Chalk almost never wins a weekly prize, because it sits in the middle of the field.

These ratios depend on the assumed field. A chalkier real field makes contrarian picks worth more.

**Rules that change the answer** (design notes):
- Drop-worst-week favours variance.
- Thursday games lock first, so use the Thursday close.
- Playoff confidence pools with rising points favour chalk on the high-value rounds.
- Bowl pools have no ratings in this engine.

**2027.** A pick'em tool (SU picks, confidence order, pool-win odds) is ~1-2 weeks on top of the part-17 market-anchored probabilities and the survivor field model (part 26). A sim-backed weekly picks set with an honest tracked record could feed Jack's picks series (idea only). Legal note: paid pools are subject to state law; information only.

---

## Part 28. Brackets

### (a) NFL playoff brackets — FULL (13 postseasons; read ranges)

**`nfl_bracket_sim.py`.**
- Ratings from all regular-season closing spreads.
- Re-seeding, byes, neutral Super Bowl, 20k sims.
- Seeds approximated from W/L + rating (not the exact NFL seeding rules).

**Bracket strategies** (1-2-4-8 scoring):

| Strategy | mean pts | % of max | range |
|---|---|---|---|
| All higher seeds | 14.1 | 49% | 5-26 |
| Sim most-likely | 13.8 | 48% | - |
| Max expected points | 14.0 | 48% | - |

All three are statistically the same. With 13 games a year, bracket strategy beyond the favourites is noise.

**Calibration.** Advance odds .08→.06, .28→.29, .50→.55, .68→.83 (Brier .099).

**Playoff fantasy formats.** The key input is expected games per team. The sim gives it directly (part 11). The NFL playoff piece for January 2027 falls straight out of parts 8/11.

### (b) March Madness — DESIGN

sim_lab is an NFL engine with no basketball ratings, so this is design only. It would be a new, separate basketball module.

**Team strength.** Adjusted offensive/defensive efficiency and tempo (KenPom/Torvik style). Win odds from the rating gap. Matching de-vigged lines and futures is the goal.

**Tournament sim.** 68 teams including the First Four; round-by-round odds. Calibrate on past tournaments with pre-tournament ratings: 5-12 games, upsets by round, champion seeds. One tournament a year (67 games), so use many replays.

**Pool strategy.**
- Use the big contests' public pick percentages.
- The champion pick decides most pools.
- Test chalk vs a strong low-owned champion by pool size (10 / 50 / 500 / 10k+) and scoring system (1-2-4-8-16-32, seed multipliers, upset bonuses) against a modelled field. Reuse the 27b field sim.

**Bracketology** is a different problem: predicting the committee from resume metrics, quadrants and the NET. Bracketologists are graded by the Bracket Matrix scoring. The @jackb933hoops Bracketology series is owned by jackb933hoops-social. Its files were not changed.

**Later extensions, one line each:**
- Women's tournament: same module, different ratings.
- NIT: low interest.
- Conference tournaments: reuse the game model.

**2027 verdict.** For March 2027 it must be ready by early March. Data feeds:
- team efficiency ratings (public)
- lines/futures
- public pick percentages

Rough effort ~2-3 weeks. It could give the hoops channel a sim-backed bracket, upset picks and champion odds (idea only). Legal note: paid pools are subject to state law; information only.

---

## Decisions (2026-11-21)

Jack, answering "Blend ESPN's projections into the sim numbers?": **"Keep it in-house."**
- **Proposal 4.1 (ESPN as a 50/50 weekly ensemble member): DECLINED.**
- **The 2027 preseason prior stays in-house.** No ESPN, Clay or FantasyPros projections as ensemble members or features. The "1/3 anchor + ESPN + Clay" result in part 3 is kept as a benchmark only.
- Outside projections and ADP can still be used as **benchmarks to grade against**. They don't go into the numbers.
- **Not ruled on, left as they are:** Vegas lines and props, which the engine already uses (book anchor, team totals, win totals as inputs).
- **Proposal 4.2 (raise the consensus weight from week 14): needs Jack's call, because it uses outside consensus.** It is neither approved nor declined. Note that it falls under the same in-house question as 4.1.
- **Still undecided:** proposals 4.3, 4.4, 4.5 and the data pulls listed below.
- Parts 13 and 14, which cite 4.1 as a start/sit or ROS proposal, should be read with 4.1 declined.

The list below is the original 2026-11-21 list, left as written; the Decisions note above takes precedence.

## What needs Jack's approval

1. Part 4 proposals 4.1-4.5. Top pick: **4.1, ESPN as a weekly ensemble member**, which is his call because it is no longer purely our model.
2. Whether to pursue the 2027 preseason prior as an **ensemble with ESPN/Clay/FantasyPros season projections** (best measured, −2.1% vs Clay) rather than a pure in-house prior.
3. New public data pulls, each needing an OK:
   - FFC ADP stdev/high/low (draft availability odds)
   - FantasyPros season projection history
   - weekly KTC/FantasyCalc pick prices
   - AAV capture
   - public survivor / pick'em pick percentages
   - 2027 season-prop capture in the betting pull
4. Building any new product: NFL team sim for the channel, pick'em/survivor, best ball advance-odds backtest, March Madness module.

## What's next (in order)

1. Pre-register and script the 2026 end-of-season grades: league title/playoff odds (part 6), draft grades (part 10), the D/ST V8 check (existing).
2. Part 3 (preseason v1, in-house only per the 2026-11-21 decision): games model, then feed the prior into the shadow harness. ESPN, Clay, FantasyPros and ADP are used only as grading benchmarks.
3. `team_env.py` (part 17) for unlined weeks, with tuned season-sim rating uncertainty k≈.05.
4. Settings-driven VOR layer (parts 21/22), used by draft, auction, keeper and trade.
5. BBM VI advance-odds backtest (part 9); start/sit pairwise odds on the site (part 13).
6. Prop over/under lean backtest on 2026 W1-11 (part 16).


---

## Addendum (2026-11-21, later): in-house decision, games model, proposals 2-5, data pulls, product builds

Everything here follows Jack's "keep it in-house" decision (see Decisions above). Nothing live was changed: engine.js, overrides.js, the site export, the helpers and anything deployed are all untouched. Nothing was pushed or committed. No sign-ins were needed and none failed.

### A1. What "outside consensus" is in the live numbers today

**Not in the live number: ESPN, FantasyPros and CBS weekly projections.**
- ESPN's weekly projection feeds only the "rank mix" (`rmMean`, 50% shadow / 50% ESPN, engine.js ~4405). That is a third graded number. It is never published as the projection and never feeds the live mean.
- The site's CONSENSUS board is a separate page.

**In the live number, and heavily: preseason ADP.**
- For veterans with a history prior, the shadow's prior is 25% history + **75% the ADP market curve** (`NC_SHADOW.adpW` .75, or .5 for second-year players; engine.js ~3911; ncSrc tag `+adp`).
- In-season evidence then updates that prior game by game.
- ADP is the drafting market, i.e. consensus market data, not anyone's projection. Jack may not have known it is in the number.
- Earlier tests found that removing or fading it costs +1.5-2.3% rest-of-season error (10-20 and 11-17 tests; project_role_prior, project_no_adp_anchor).

**Also in the live number: Vegas data.**
- The prop anchor, with tuned weights (median QB .68, RB .14, WR .47, TE .26).
- Implied team totals.
- Re-rated future totals.

**Clay:** retired as the weekly base on 10-08. He remains only as the fallback for the rare player with no Clay-free prior (1 of 158 rows in W10).

### A2. Games-played model (in-house) — PARTLY: it works, with a small gain

**Where it lives**
- Code: `preseason2027/games_model.py`.
- Logs: `games_model.log` (first pass: `games_model_v1.log`).
- Rows: `data/games_model_rows.parquet`.

**Inputs**
- Only nflverse data already on disk: weekly rosters (status), injury reports, snap counts, draft picks.
- No outside projections.
- ADP is never an input. It only defines the ADP top-150 grading pool.
- Vegas win totals are kept.

**Target and models**
- Target: games with a stat line in weeks 1 to second-to-last.
- RIDGE on games share, trained on an in-house relevance pool: chart 1-2, a real role last year, or a top-64 rookie.
- DIST: a multinomial model over missed-game bins 0-1 / 2-3 / 4-7 / 8+, shrunk 20% toward base rates. The shrink was picked on 2015-18.
- MAIN = .75 ridge + .25 dist, picked on 2015-18 and frozen.

**Why games are missed (ADP top 150, 2015-25)**

| Depth | Injury | Role (active, no stat line) | Off roster | Missed 4+ games |
|---|---|---|---|---|
| 1 | 1.92 | 0.25 | 0.31 | 34% |
| 2 | 1.62 | 0.63 | 0.48 | 39% |
| 3+ / none | 3.38 | 0.89 | 1.72 | 70% |

**Games played (walk-forward 2015-25, ADP top 150, n 1,591)**

| Model | Games MAE | Corr | Spearman |
|---|---|---|---|
| **New in-house MAIN** | 2.81 | **.310** | **.236** |
| New, without injury-history inputs | 2.82 | .308 | .245 |
| Old prototype games model (used ADP) | **2.73** | .250 | .207 |
| Last season's games | 3.55 | .159 | .135 |
| Flat position average | 3.96 | −.020 | .079 |

- Correlation by position, new vs old: QB .40 vs .33, RB .30 vs .26, WR .25 vs .16, TE .24 vs .16.
- On the whole relevance pool, the new model matches the old ADP-informed model without using ADP (MAE 3.14 vs 3.12, corr .626 vs .628).
- On the ADP pool it still runs 0.3 games low (12.31 vs 12.64). This is a selection effect: drafted players are the healthy, employed ones, and an in-house model can't see that the market chose them.

**What held up and what didn't**
- Held up:
  - the week-1 depth chart (the biggest coefficient)
  - not being on the active roster in week 1 (cut, practice squad, reserve/PUP)
  - last season's games share
  - age
  - the rookie flag
- Did not hold up: injury history over 1-3 seasons adds nothing out of sample (without it, MAE 2.82 vs 2.81, Spearman .245 vs .236).
- As Jack expected, position, age and role carry most of it. Keep injury-history inputs out of v2, except perhaps for the long-absence tail of the distribution.

**Distribution calibration**
- P(miss 4+ games), predicted → actual:

| Predicted | Actual | n |
|---|---|---|
| .18 | .29 | 59 |
| .25 | .25 | 334 |
| .35 | .36 | 419 |
| .45 | .35 | 344 |
| .58 | .44 | 332 |
| .82 | .75 | 122 |

- Brier .2257 vs base-rate .2349.
- P(full season): predicted .346 vs actual .377.
- P(8+ missed): predicted .216 vs actual .157. The long-absence risk is overstated.
- Next fix: isotonic recalibration, fit walk-forward.

**Season totals (in-house PPG `ridge_stats`, no ADP, × games; ADP top 150, 2015-25)**

| Total model | MAE | Spearman (pos-season) | Top-12 | Top-24 |
|---|---|---|---|---|
| In-house PPG × **new** games | 52.35 | **.446** | .462 | **.640** |
| In-house PPG × old games | 52.33 | .424 | .443 | .612 |
| In-house PPG × flat games | 61.11 | .425 | .470 | .629 |
| **ADP (benchmark)** | **49.69** | **.501** | .534 | .657 |
| Comparison only: ADP-anchored PPG × new games | 50.04 | .501 | .515 | .650 |
| Comparison only: ADP-anchored PPG × old games | 50.54 | .469 | .504 | .634 |

- The new games model closes 29% of the in-house rank gap to ADP: the gap shrinks from .077 to .055.
- By ADP band (pooled Spearman, in-house new / old / ADP):

| Band | New | Old | ADP |
|---|---|---|---|
| 1-30 | **.245** | .187 | .213 |
| 31-100 | .451 | .446 | .455 |
| 101-150 | .455 | .441 | .456 |

- In-house now beats ADP on ordering in the top 30 and ties it in 31-150.
- MAE is still 3-4 points worse than ADP in every band, because of the level bias above.
- Per-game numbers did not move; the PPG model is unchanged.
- Season-total p10-p90 coverage from the games distribution × PPG draws: **83.7%** (target 80, so slightly wide).

**Verdict:** a real but modest improvement. The in-house total still trails ADP (Spearman .446 vs .501, MAE 52.4 vs 49.7).

**Next weakest piece:** the in-house per-game model (PPG MAE 2.713 vs ADP 2.494). It is worst for RBs and rookies and its level runs low. After that comes the calibration of the games distribution.

### A3. Proposals 2-5: tested, nothing shipped (PENDING.md P-20261121-1 to 4)

**Proposal 3: re-tune the book-anchor weight**
- Data: **2026 only**, the W1-11 locks (2,227 lined rows). No other season has prop lines, on disk or free online.
- Result:
  - The curve is flat: pooled MAE moves only .058 across w .3-.8.
  - The tuner's weights are already near the in-sample best: QB .68 vs .7, RB .14 vs .1, WR .47 vs .4, TE .26 vs .4.
  - Tune on W1-6, score W7-10: +0.22% (worse). Reversed: −0.40%.
  - The best weight swings between 0 and .8 week to week.
- Verdict: **don't re-tune.** Leave it to the weekly tuner. Provisional; re-check after week 17 for the 13-17 band.

**Proposal 4: QB-only dud component**
- Data: 2019-25; q fit on 2019-22, scored on 2023-25.
- Result:
  - The gap is QB-only; RB, WR and TE are fine.
  - Holdout dud rate: 1.4% → 4.2% (real 4.1%).
  - p10-p90 coverage: 75.6% → 79.4%.
  - CRPS: −0.5%.
  - Start/sit QB pairs: neutral (Brier .2448 → .2446).
  - Fantasy team-score sd: 25.0 → 25.4.
- Causes of QB duds:
  - 56% left early or shared snaps (half injury exits, half benchings)
  - 37% blowouts
  - 10% wind
- Verdict: **recommend q = .03** (dud draw = U(0, .25) × mean; gamma rescaled so the mean is unchanged). Replay it in the engine sampler before wiring.

**Proposal 5: opposing-QB correlation**
- Data: 862 games, 2019-25.
- Result:
  - Real correlation +.252 (90% range .197 to .309). By season .14 to .34; no pattern by game-total tercile.
  - Engine: .195 at gV .50 → .249 at gV .63.
  - QB to opposing WR1: .074 → .094 (real .118).
  - Stack sd +0.8%.
  - The correlation matrix stays valid.
- Verdict: **recommend gV .63, low priority.** The gain in the correlation itself is measurable; the downstream gain is within noise.

**Proposal 2: consensus weight from week 14/15**
- Data: 2019-25 played games, leave-one-season-out.
- Result:
  - ESPN at w .6, weeks 15-17: MAE −1.52% (better in 5 of 7 seasons), rank correlation .456 → .480.
  - In-house fixes (per-case multipliers, faster usage reaction, a level fix) recover none of it: +0.5% to +0.65%.
  - The gap is spread across every case, not concentrated in one.
- Verdict: **needs Jack's call**, because it crosses the in-house line. If in-house stands, leave as is. The cost is about 1.5% MAE in the playoff weeks.

**Side finding from proposal 4:** QB start/sit pair odds are about 2.5 points over-confident (58.4-58.8% predicted vs 56.2% won, 2023-25). The all-position calibration from part 13 still holds; QB pairs alone do not. Proposal 4 doesn't fix this. Any pairwise-odds build should add a QB-specific spread term.

### A4. Data pulls: scoped, nothing pulled

The scoping was done by a research agent, read-only, one sample per source, nothing stored.

**Rule slips to disclose to Jack.** The agent read three pages before checking their robots/terms (one page each, nothing kept):
- The FFC API, whose robots.txt has `Disallow: /api/`, while FFC's help page says the API is free to use.
- A Yahoo pick'em page. Yahoo's robots.txt blocks ClaudeBot, and its terms ban automated access.
- An NFL.com transactions page. Its terms ban systematic retrieval.

Category: **(a)** benchmark only, **(b)** market data (ADP, prices, lines), **(c)** model input.

| Rank | Pull | Cat | Access / terms | What it unlocks | Timing | Effort | Recommendation |
|---|---|---|---|---|---|---|---|
| 1 | **FantasyCalc values incl. picks** (api.fantasycalc.com) | b | Undocumented public JSON; no robots file on the API host; no ToS found | The market for trades (part 7) and dynasty/picks (part 5). History is lost every week it isn't captured. | **Start capturing now** (weekly) | Low (~30 calls/week) | Start capturing now, if Jack OKs using an undocumented endpoint |
| 2 | **DynastyProcess values git history** (github.com/dynastyprocess/data, GPL-3) | b | Open data | Weekly player and pick value history, so the dynasty pick blend can finally be backtested | Archived | Low (one clone) | Pull now. Note: derived from FantasyPros dynasty ECR. |
| 3 | **SurvivorGrid archive 2010-26** | b | robots allow all; no ToS; "All Rights Reserved" | Pick popularity for survivor (part 26) and the field model for pick'em (part 27) | Archived; capture the rest of 2026 weekly | Low-medium (~300 pages at 5 s spacing) | Pull now, politely. A courtesy email is advised. |
| 4 | **FFC ADP stdev/high/low 2010-26** | b | Help page: free for personal and commercial use, with credit. robots disallows /api/ but allows the HTML pages. | Draft availability odds (part 10) and ADP spread. 12-team only; 2QB stands in for superflex; no TE premium. | Archived; daily drift from June 2027 | Low | Pull now via the allowed HTML pages, or via the API if Jack OKs it despite the robots line |
| 5 | **nflverse trades file** (weekly_rosters already on disk) | c | Open | Camp status for the games model; mid-season moves | Archived | Low | Pull now |
| 6 | **MFL AAV/ADP export** (api.myfantasyleague.com) | b | Documented API, but robots on the API host disallows the year paths; ToS unread; a registered client needs Jack's MFL account | The only public real-league auction-value history, for auction (part 18) and keeper cost (part 19) | Archived; weekly June-Aug 2027 for drift | Low | **Needs Jack's decision** |
| 7 | **2027 season player props** (public articles listing every QB/RB/WR over/under) | b | Article pages; sportsbook pages mostly blocked | The preseason market input for part 3, and props for part 16. No free history exists. | **Must start ~May 1, 2027**, then weekly to week 1 | Medium (manual transcription) | Start capturing May 2027 |
| 8 | **Historical weekly player props 2023-25** (The Odds API) | b | Paid | Three more seasons to tune the anchor weight (proposal 3) and to grade props (part 16) | Archived | Medium (~70k credits) | **Needs Jack's decision (paid)** |
| 9 | Camp-opening PUP/NFI lists | c | NFL.com / PFR terms forbid scraping | Preseason status for the games model | Late July 2027 | ~1 h by hand | Record by hand from news in July 2027 |
| 10 | FantasyPros projections / ECR history | a | Paid commercial plan; terms ban commercial reproduction | Benchmark only | — | — | **Needs Jack's decision.** Benchmark only; not needed for the in-house work. |
| 11 | KTC; ESPN, Yahoo or Sleeper AAV; Yahoo pick'em | b | Login, scraping bans or non-commercial terms | Covered by 1-4 and 6 | — | — | Needs Jack's decision; skip, since alternatives exist |

**In-house check**
- None of these brings outside projections into the numbers.
- FantasyPros would be a benchmark only.
- Season props and ADP spread are market data, the same class as the Vegas lines the engine already uses.

### A5. New product builds: scoped and ranked, none built

**Shared foundations, in build order**

1. **F1, game layer (18-week environments).** Win-total ratings turned into spread, total, plays and pass rate, then Elo-updated; part 17 design. About 1 week.
   - Unlocks: survivor, pick'em, the NFL bracket, playoff-schedule strength, preseason team environments, and later K/DST and IDP.
2. **F2, settings-driven value layer.** VOR from greedy lineup allocation over sim draws, for any scoring, lineup or flex rules. About 2 weeks.
   - Unlocks: draft upgrades, auction, keeper, the trade evaluator, superflex/TE-premium rankings and FAAB.
3. **F3, honest team-score distributions.** Mostly exists already. Needs Questionable players drawn in/out each week, plus the QB dud component. About 3-5 days.
   - Unlocks: guillotine, league and playoff odds, best ball, and start/sit pairwise odds.
4. **F4, field / popularity model.** Needs data pull 3. About 1 week.
   - Unlocks: survivor, pick'em/confidence, brackets and DFS ownership.

**Ranked products**

| Rank | Product | Who it's for / surface | What exists (status) | Missing | Needs first | Engine effort | Evidence of edge | Ready by | In-house fit | Recommendation |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Settings-driven value layer | Every draft, trade and ranking surface | Format VOR tested (parts 21/22, PARTLY) | The module and its wiring | — | ~2 wk | Strong (the format math is exact) | Jul 2027 | Yes | **Build next**, after preseason v1 |
| 2 | Playoff-schedule strength view (wks 15-17) | Site page, best ball helper | Future-totals re-rate (live) | 18-week environments | F1 | Days | Convenience | Mar 2027 (best ball) | Yes | Build after F1 |
| 3 | Draft sim upgrades (availability odds, VOR picks) | Site mock draft; Sleeper, ESPN, Yahoo helpers | Helpers' recommenders (DESIGN) | ADP spread (pull 4) | F2 | ~1 wk | Medium (ADP spread is real data) | Aug 2027 | Yes | Build after F2 |
| 4 | Keeper tool | Site page, helpers | Surplus backtest, r .385 (PARTLY) | Keeper rules engine, pick-value curve | F2 | ~1-2 wk | Medium | **Aug 1, 2027** | Yes | Build after F2 |
| 5 | Best ball tool upgrades | Underdog helper, Sim Lab tab | `simBestBall` exists; shapes tested (PARTLY) | BBM VI advance-odds backtest; stacking turned on | F3 | ~1-2 wk | Can be backtested on BBM VI before launch | **~Mar 1, 2027** | Yes | Build next, in parallel with F2 |
| 6 | Survivor tool | Site page, @jackb933nfl series | Replay backtest (PARTLY) | Pick popularity (pull 3), updated ratings | F1, F4 | ~1 wk | Convenience: greedy picking ≈ season planning; any edge comes only from pick popularity | **Week 1, ~Sep 9, 2027** | Yes (market lines) | Build after F1 and F4 |
| 7 | Pick'em + confidence tool | Site page, picks series | SU/ATS/confidence backtests (FULL / PARTLY) | Field model (pull 3) | F1, F4 | ~1-2 wk | SU/ATS: no edge, convenience only. Confidence weekly prizes: contrarian picks win 1.1-1.8× a fair share (against an assumed field). | Week 1 2027 | Yes | Build after F4 |
| 8 | Auction values + live helper | Site, helpers | Nothing (DESIGN) | Auction-value history (pull 6, Jack's call) | F2 | ~2 wk | Unknown until the data exists | Aug 2027 | Yes | Wait for data |
| 9 | Graded trade evaluator | Site calculator, Sleeper helper | Same-seed Δtitle in the helper (DESIGN) | A trade log plus market history (pull 1) | F2, F3 | ~1-2 wk, plus 8 weeks of logs | None yet | Week ~6 2027 | Yes | Start logging now; build after F2 |
| 10 | FAAB / waiver bid model | Helpers, My Teams | Static ranges (DESIGN) | Bid data (none is public); logged recommendations | F2 | ~1 wk | Weak (no bid history) | Week 1 2027 | Yes | Build a simple version after F2 |
| 11 | Prop-comparison view | Sim Lab LINES view, videos | LINES view exists (PARTLY) | Over/under lean backtest; season props (pull 7) | — | ~1 wk | Edge unproven; information only | Week 1 2027 | Yes | Build after the lean backtest |
| 12 | NFL playoff bracket | Site, NFL channel | Bracket backtest (FULL) | UI | F1 | Days | No strategy edge (chalk ≈ sim); convenience | **~Jan 9, 2027** (tight) or Jan 2028 | Yes | Convenience build for Jan 2028 |
| 13 | Guillotine tool | Helpers | Nothing (DESIGN) | Elimination loop, FAAB logic | F3, F2 | ~2 wk | Can't be backtested (no real guillotine drafts on disk) | Aug 2027 | Yes | Only if Jack plays or covers guillotine |
| 14 | March Madness bracket sim | Hoops channel, site | Nothing (DESIGN; a new basketball module) | Team ratings, lines, pick percentages | F4 | ~2-3 wk | Can be calibrated on past tournaments | **Early Mar 2027** (Selection Sunday ~Mar 14) | Yes (public ratings + market) | Jack's call; would have to start by January 2027 |
| 15 | DFS (projections, optimizer, ownership) | New surface | Distributions and correlation (PARTLY) | Salaries, slates, ownership | F3, F4 | ~3-4 wk | Unproven | 2027 season | Yes | Skip for 2027 |
| 16 | IDP projections | Helpers, site | Nothing (DESIGN) | Role and opponent-plays model | F1, F2 | ~3-4 wk | None | Aug 2027 | Yes | Skip unless the audience asks |

**Risks and limits (facts)**
- Paid contests, pools and betting content are subject to state law. Anything built here is information, not betting advice.
- Several data sources restrict use (see A4).
- Strategy edges in survivor and pick'em are small, so label those tools as convenience tools.

**Natural premium-feature candidates (an input for mff-site-conversion, not a pricing view)**
- Keeper tool.
- Draft availability odds.
- Auction helper.
- Best ball portfolio / advance-odds view.
- Graded trade evaluator with Δtitle.
- Survivor / pick'em season planner.

**Suggested 2027 offseason timeline (from today, 2026-11-21)**

| When | Work |
|---|---|
| Now to Dec 2026 | Games model v2 (isotonic recalibration). In-house per-game model v1, the next weakest piece. Start the FantasyCalc capture and the trade/recommendation logs, if approved. Pre-registered end-of-season grades (week 17 ends ~Jan 3, 2027). |
| Jan 2027 | F1 game layer. F3 sampler fixes (P-20261121-1/2, if approved). March Madness work has to start now if it's wanted. |
| Feb 2027 | Best ball upgrades plus the BBM VI backtest (drafts are already open). F2 value layer starts. |
| Mar 1, 2027 | Best ball prior and playoff-schedule view ready. March Madness by early March, if approved. |
| Apr-May 2027 | NFL draft (late April) → rookie prior (draft capital + JM). Season-prop capture from May 1. |
| Jun-Jul 2027 | F2 done. Draft sim upgrades, keeper tool (by Aug 1), and auction if the auction-value data is approved. F4 field model. |
| Aug 2027 | Survivor and pick'em tools. Final preseason prior. Guillotine only if wanted. |
| Week 1 (~Sep 9, 2027) | All 2027 preseason outputs live, each pending Jack's ship OK. |


### A6. P-20261121-1 (QB dud component): approved, implemented, failed the live-engine check, reverted (2026-11-21)

Jack approved it ("Approve QB dud fix"). It was implemented in engine.js as `QB_DUD = { q: .03, max: .25 }`, QBs only. The dud decision was hashed off the gamma draw, so no extra rng calls were made.

**Checks** (harness `sim_lab/_tmp/qbdud_verify.js`; week 11, same seeds):

| Check | Result |
|---|---|
| Analytic QB means | identical (max diff 0, 46 QBs) |
| Non-QB rows | all 309 byte-identical |
| QB sim means | +0.04% |
| QB-vs-QB pair odds | moved 0.5 points on average, max 1.2 |
| Toy league title odds | moved at most 1.5 points |
| ROS QB p10 | about unchanged |
| QB weekly p10 | fell 1-1.7 points (Burrow 9.5 → 7.8, Allen 11.8 → 10.5) |

**Shape check on the live sampler** (2026 W1-10 QB locks vs real scores, n 286):

| | Real | Before | After |
|---|---|---|---|
| Dud rate | 4.5% | 4.1% | 6.8% |
| p10-p90 coverage | — | 80.8% | 82.9% |

**Failed.** The live engine was already right, so the fix overshoots.

The backtest's 1.4% "gamma" figure came from a pure moment-matched gamma. The engine's draw is a gamma with a factor-shifted mean (floored at .25 of the mean), and that already fattens the left tail. This lesson goes to the rejected hub: test sampler shape changes on the engine's own sampler, not on a replica.

**Restored:**
- `engine.js` was restored from `engine.js.bak_pre_qbdud_20261121`; the two are byte-identical.
- The attempted version is kept as `engine.js.qbdud_attempt_20261121_reverted`.
- Nothing was exported, synced or deployed.


### A7. In-house per-game model v1 (2026-11-21): PARTLY — real progress, still behind ADP

Jack asked to "work on the per-game model" (the next weakest piece named in A2).

**Files**
- Code: `preseason2027/pergame_model.py`.
- Ablation: `pergame_ablation.py`.
- Logs of record:
  - `pergame_model.log` (final run)
  - `pergame_model_v1.log` (first run, before the dev-picked lean stage)
  - `pergame_ablation.log`

  Each log is opened only by its own script's `main()`, so importing a module no longer wipes another script's log. The other review scripts were fixed the same way, and `prop245_tests.log` was regenerated with identical numbers.
- Rows: `data/pergame_rows.parquet`.

**Rules followed**
- In-house only: no outside projections.
- ADP is the benchmark and only defines the grading pool.
- An ADP-anchored variant is reported separately and labelled.
- Walk-forward 2015-25. Every design choice was made on 2015-22 ("dev"); 2023-25 was held back as the final check.
- Pre-2018 FFC ADP is mixed-format (PPR / standard), as flagged before.

**Step 1: diagnosis of the old in-house model.** ADP top 150, games-weighted PPG MAE. "Gap × n" is total excess points of error vs ADP.

| Group | n | MAE old | MAE ADP | Gap | Gap × n |
|---|---|---|---|---|---|
| All | 1,534 | 2.711 | 2.491 | +.221 | +339 |
| **RB** | 572 | 3.161 | 2.839 | **+.322** | **+184** |
| WR | 609 | 2.452 | 2.322 | +.129 | +79 |
| QB | 193 | 2.758 | 2.542 | +.216 | +42 |
| TE | 160 | 2.102 | 1.870 | +.233 | +37 |
| ADP 31-100 | 743 | 2.593 | 2.399 | +.194 | +145 |
| ADP 101-150 | 478 | 2.758 | 2.452 | +.306 | +146 |
| **New QB1 on the team** | 453 | 2.731 | 2.422 | +.309 | **+140** |
| Years 3-5 | 580 | 2.742 | 2.532 | +.210 | +122 |
| Veterans | 582 | 2.484 | 2.290 | +.194 | +113 |
| Changed team | 212 | 2.886 | 2.556 | +.330 | +70 |
| **Rookies** (old model read 18% low) | 157 | 3.180 | 2.794 | +.386 | +61 |
| New head coach | 304 | 2.631 | 2.436 | +.195 | +59 |
| RB vets 28+ | 106 | 3.225 | 2.823 | +.403 | +43 |
| RB rookies | 87 | 3.634 | 3.157 | +.477 | +42 |
| Back from a short season | 52 | 3.575 | 2.821 | **+.754** | +39 |
| Drafted round 1-2 competition | 129 | 2.804 | 2.529 | +.276 | +36 |
| Backup → week-1 starter | 71 | 3.584 | 3.232 | +.352 | +25 |

**Volume vs efficiency** (oracle swaps on the structural model; base MAE 2.651):

| Swap | MAE | Change |
|---|---|---|
| Actual volume in place of projected volume | 1.526 | −42% |
| Actual efficiency in place of projected efficiency | 2.004 | −24% |
| Actual TD rates only | 2.229 | −16% |

- **Volume (who gets the work) is about two-thirds of the miss.**
- For RBs, fixing volume removes 52% of the error.
- TD rates are about two-thirds of the efficiency miss. That is regression already working: the fitted shrink strengths are 300-1,300 opportunities for TD rates vs 80-160 for catch rate.

**Step 2: the rebuild.**

*Structure.* Per-game points = projected volume (targets / carries / pass attempts per game, ridge per position) × efficiency. Efficiency is an empirical-Bayes shrink of each rate toward a prior, with the shrink strength fit per stat on the training seasons. QB rushing is its own component.

*Ablation (MAE / rank rho):*

| Stage | Dev 2015-22 | Final 2023-25 |
|---|---|---|
| Old ridge | 2.747 / .439 | 2.629 / .429 |
| S1 structure + basic | 2.719 / .445 | 2.628 / .406 |
| S2 + team context | 2.727 / .449 | 2.634 / .412 |
| S3 + roster changes | 2.722 / .455 | 2.626 / .414 |
| S4 + experience curves / JM / rookie prior | 2.687 / .459 | 2.576 / .423 |
| S5 + RB specifics | 2.690 / .458 | 2.575 / .422 |
| **S7 lean** (basic + roster changes + rookie pick, picked on dev) | 2.673 / .477 | 2.573 / .440 |
| **S6 = .75 × S7 + .25 × old ridge** (weight picked on dev) | **2.658 / .481** | **2.554 / .446** |
| ADP curve (benchmark) | 2.479 / .554 | 2.519 / .532 |

Roster changes means position-specific vacated volume, arrived volume, round 1-2 draft competition, injury return, and backup → starter.

*Leave-one-out on dev (which pieces held up):*
- **Dropped:**
  - team context (removing it helped: 2.677 vs 2.687)
  - JM (2.682 vs 2.687, a wash; its weights were also tuned on these classes)
  - year-2/year-3 flags (2.685)
  - RB extras (age cliff, heavy-workload, receiving role: no gain)
- **Kept:**
  - roster changes (small: .003)
  - rookie efficiency prior and log pick (S4 vs S3 −.035)
- The 2023-25 final check moved in the same direction on every choice.

**Results, all 11 seasons, ADP top 150:**

| Cut | Old in-house MAE / rho | New in-house (S6) MAE / rho | ADP MAE / rho | New beats ADP (seasons) |
|---|---|---|---|---|
| All | 2.711 / .437 | **2.627 / .472** | 2.491 / .548 | 1/11 |
| QB | 2.758 / .240 | 2.679 / .329 | 2.542 / .454 | 5/10 |
| RB | 3.161 / .511 | 3.058 / .553 | 2.839 / .640 | 2/11 |
| WR | 2.452 / .537 | 2.395 / .554 | 2.322 / .601 | 4/11 |
| TE | 2.102 / .440 | 1.973 / .438 | 1.870 / .489 | 4/6 |
| ADP 1-30 | 2.918 / .317 | 2.870 / .319 | 2.760 / .303 | 5/11 |
| ADP 31-100 | 2.593 / .225 | 2.492 / .264 | 2.399 / .308 | 4/11 |
| ADP 101-150 | 2.758 / .043 | 2.676 / .074 | 2.452 / .124 | 2/11 |
| Rookies | 3.180 | **2.822** | 2.794 | 3/6 |
| Year-2 players | 2.905 / .549 | 2.879 / .500 | 2.702 / .673 | 4/11 |
| RB veterans | 3.081 / .544 | 3.019 / .559 | 2.785 / .654 | 2/11 |

- The MAE gap to ADP closed by 38% (.220 → .136) and the rank gap by 31% (.111 → .076).
- On the 2023-25 final check the MAE gap is only .035 (2.554 vs 2.519), but rank is still .446 vs .532.
- Rookies nearly caught up.
- Year-2 ordering got worse (rho .549 → .500). That is the clearest weak cell.
- Season by season, the new model beat the old in 8 of 11 seasons. It beat ADP only in 2023 (2.466 vs 2.544).

**ADP-anchored variant** (comparison only; ADP is an input): .2 × in-house + .8 × ADP curve.
- MAE 2.464 vs ADP 2.491, **beating ADP in 9/11 seasons** (3/3 in 2023-25). Rank is a tie (.546 vs .548).
- So the in-house model carries information the market doesn't, but only as a small minority weight.
- This is Jack's call for 2027. The live engine's veteran prior is already 75% ADP (A1).

**End to end** (season totals = per-game × the A2 games model; ADP top 150):

| Totals model | MAE | Spearman | Top-24 |
|---|---|---|---|
| Old in-house PPG × new games | 52.35 | .446 | .640 |
| **New in-house PPG × new games** | 51.39 | .467 | .648 |
| ADP-anchored PPG × new games (comparison) | **49.42** | **.514** | **.659** |
| ADP (benchmark) | 49.69 | .501 | .655 |

Season-total p10-p90 coverage is 83.2% (target 80; still slightly wide).

**Where in-house still loses, and whether it can close.**
- The remaining gap is mostly **volume and role**: who gets the carries and targets, especially for RBs, year-2 players and QB ordering.
- The market prices August information the model can't see in-house: camp reports, depth-chart battles, coaching statements on roles, and August injuries.
- Two things could close part of it:
  1. **Preseason (August) depth charts for 2019-24.** Only 2025 has one on disk. Possible sources are Wayback captures of ESPN or Ourlads charts. Their robots.txt and terms must be checked **before any page is read**. Nothing was fetched; this is listed for Jack's approval.
  2. **Better volume modelling of team-level opportunity redistribution.** Projected shares must sum to the team's projected volume; today each player is projected alone.
- The rest is August information the market has. My honest read: in-house can probably close another .03-.05 of MAE. Matching ADP's ordering without market or August role information is unlikely.

**Next weakest piece:** projected volume share for RBs and year-2 players, with team-level consistency (shares summing to team volume). After that, calibration of the games distribution (coverage 83%).

**Data for Jack's approval:** historical August depth charts (source and terms not yet checked, nothing read). No other new source is needed.


### A8. ADP decision recorded and parked; first in-house rankings delivered (2026-11-21)

**Decisions (2026-11-21):**
- Jack approved ADP as an input to the 2027 preseason sims ("Yes, use ADP.").
- Right after, he said: "but lets see what it looks like without adp for now". The ADP-anchored build is **parked**, and the in-house-only model (no ADP input) is the working version.
- Recorded in PENDING P-20261121-7.

**What was delivered:** in-house rankings with ADP as a comparison column only. They come from the final per-game model (A7) multiplied by the games-played model (A2). Scoring is half-PPR (the prototype's native scoring); the overall order is value over replacement for a 12-team 1QB league. Files in `sim_lab/preseason2027/output/`; code in `output_rankings.py`; log in `output/output_rankings.log`.

**A. `2026_inhouse_check.md` / `.csv`: what the model would have said before week 1 of 2026**
- Inputs, all as known before the season:
  - trained on 2012-25
  - 2026 expected wins derived from the frozen preseason game lines (2026-08-26)
  - the ESPN depth chart from the repo's git history (commit c9e33926, 2026-09-11 15:07 ET; earlier pulls had no WR lists, and only the Thursday opener had been played)
  - 2026 rookies and their draft capital
- Comparison ADP: Underdog best ball, 2026-09-03.
- Actuals: weeks 1-10.
- **Biggest-disagreement tally: ADP closer 14, model 12, too few games 4** (a coin flip on a small sample).
- **What it gets right:** the top 8 match the market's top 8. It had McBride as TE1 and Allen as QB1, and it was right on Fannin, Tre Tucker, Freiermuth and Henry.
- **What it gets wrong:**
  - rookie RBs (Love RB9, now RB44)
  - aging RBs (Saquon RB5, now RB38)
  - backup RBs ranked far below ADP, where ADP was mostly right (partly best-ball format)
  - mid-tier TEs and depth WRs (Pitts TE3, now TE20; Jeudy)
  - QB ordering (Lamar and Hurts at QB2/3, Dart and Baker in the top 8)
  - Burrow at only QB16, because one short season drags down his games projection
  - Travis Hunter missing (listed as CB in nflverse)
  - ranges too wide (long absences overstated)

**B. `2027_inhouse_early.md` / `.csv`: PRELIMINARY first look at next season**
- Built from 2026 weeks 1-10, scaled to a 17-game rate, plus today's ESPN depth chart, with age +1.
- Not included: 2027 rookies, free agency, coaching changes, 2027 win totals.
- The top five are Gibbs, Smith-Njigba, Bijan, Chase and Lamb. Projected games run high because a partial season shows fewer misses.

**New fixes this surfaced** (not done; added to next steps):
1. The games model over-penalises one injured season for established starters (Burrow).
2. RB age 28+ with heavy workloads, and backup-RB value, need another look. Best-ball ADP is not the right comparison for depth RBs.
3. Map players whose nflverse position is wrong (e.g. Hunter).
4. Calibrate the games distribution so ranges tighten.

Guard added in `preseason_model.walk_forward` so a test year with no ADP rows runs (2026/27). Backup: `preseason2027/preseason_model.py.bak_pre_guard_20261121`.


### A9. The four fixes the lists exposed (2026-11-21): two kept, one used for ranges only, one "no fix found"

Jack asked "Have it fix the four problems these lists exposed?" and said "Yes, fix them". This pass covers only the in-house prototype, with no ADP input. ADP is approved but parked.

**Rules for this pass**
- Every fix had to hold up on the 2015-25 walk-forward. Choices were made on 2015-22.
- The 2023-25 holdout has now been looked at several times, so it is no longer fully clean. It is reported separately.

**Files** (all in `preseason2027`)
- Code:
  - `fixes_a9.py` (log `fixes_a9.log`)
  - `fix4b_a9.py` and `fix4c_a9.py` (logs `fix4b_a9.log`, `fix4c_a9.log`)
  - `data/position_overrides.csv`
  - `output_rankings.py` v2, with v1 kept as `output_rankings.py.bak_v1_20261121`
  - `movers_a9.py` (log `output/movers_a9.log`)
- Backups:
  - `build_player_weeks.py`, `preseason_model.py` and `games_model.py`: `.bak_pre_posfix_20261121`
  - `data/player_weeks_v1_pre_posfix.parquet`
- engine.js changed today (the 14:25 batched-runs work by another session). Nothing in `preseason2027` reads engine.js, so these results are unaffected. engine.js was not touched.

**Fix 1. Games model: established starters coming off one short season.** Kept (small).
- Definition. Established = a clear starter in both of the two seasons before last (12+ games, plus QB 20+ attempts/g, RB 10+ carries/g, or WR/TE 4.5+ targets/g). Short = under 10 games last season.
- Measured (ADP top 150, n 73): the model predicted 11.2 games vs 11.8 actual.

| Group | Predicted | Actual |
|---|---|---|
| Short season was injury (n 63) | 11.4 | 12.4 (1 game low) |
| Short season was role / benching / off-roster (n 10) | 9.7 | 8.1 (too HIGH) |
| QBs (n 10) | 10.8 | 13.8 (3 games low) |

- Repairs tested (games MAE on the group / on the whole dev pool):

| Repair | Group MAE | Dev pool MAE |
|---|---|---|
| Baseline | 3.06 | 2.78 |
| Multi-season games share | 3.03 | 2.78 |
| **Shrink last season toward his own longer-run rate (40/60), established starters only** | **2.92** | **2.78** |
| Floor at .6 | 3.01 | 2.78 |
| Established × short flag | 3.07 | 2.78 |

- The other direction is not broken. Old RBs (28+) off a short season: MAE 5.02 → 4.85, still predicted below their actual. QBs short for role: 5.90 → 5.85, though still predicted too high (9.5 vs 6.8). Benched QBs are still under-penalised; that is not fixed.
- Worth: season totals are flat (all seasons: Spearman .469 → .468; holdout .513 → .514; holdout top-12 hit .486 → .500).
- **Burrow did not move** (overall 109 → 120, QB16 → QB17). His 2023 was also short, so he does not meet the "established" definition. The model's caution about two short seasons in three years is evidence-based, not a bug.
- It did not help QB ordering (QB totals MAE 65.8 → 65.6; per-game unchanged).

**Fix 2. RBs.** No fix found for the projected average. The take-over chance is kept as an information column.
- **Age × workload:**
  - Tested an age × carries interaction in volume (per-game) and in games played.
  - Per-game RB 28+ got worse: 3.135 → 3.150. Games played for RB 28+ were unchanged.
  - No form held up. The wider-spread idea is answered by fix 4: RB 28+ ranges are already as wide as the data supports.
- **Backups vs the comparison ADP:**
  - Against REDRAFT ADP (the FFC mock drafts used for history), depth-2 RBs (n 163): the model reads them 4.5% low (actual / pred 1.045), while ADP reads them 3.5% high (.965). MAE: model 2.745 vs ADP 2.626.
  - So part of the gap is real error. It is smaller than the 2026 best-ball comparison made it look.
  - No redraft ADP exists on disk for 2026 (Underdog best ball only).
- **Take-over history** (week-1 depth-2 RB becomes the lead back, i.e. 50%+ of team carries in 3+ games; 2015-25, n 373):
  - Overall: **28.4%**.
  - By draft round: round 1-2 **55.9%**, round 3-4 27.0%, later/UDFA 17.8%. Rookie backups: 35.4%.
  - By starter: age 28+ 25.3% vs under 28 28.9%; starter missed time last year 25.7%; committee 28.2% vs clear lead 28.9%. The starter's age, health and committee status carry no signal.
  - Depth 3+: 9.7%.
  - A walk-forward logistic is calibrated (.17 → .16, .25 → .24, .37 → .43; Brier .1972 vs base-rate .2034).
- **As an input:** adding P(take over) to RB volume made per-game error slightly worse (3.051 → 3.056; backups 2.745 → 2.760). It does not improve the mean.
- **Upper range:** backup-specific spread vs pooled RB spread: 79.6% vs 80.3% coverage, above-p90 rate 11.7 vs 10.9. No improvement, so not adopted.
- Kept as an information column (`p_take`) for depth-2 RBs in the 2026 CSV. Top of 2026: TreVeyon Henderson .53, Woody Marks .44, Kamara .39, Najee Harris .35, RJ Harvey .34.

**Fix 3. Position overrides.** Kept.
- `data/position_overrides.csv` (gsis id, season range, position, reason, date). Applied in `build_player_weeks.py`, `preseason_model.build` and `games_model.availability`.
- Scan of 2012-26 for offensive production at a non-offensive listed position: only **Travis Hunter** (CB, 45 targets in 2025) and **Jordan Thomas** (LB, 27 targets as a TE in 2018).
- Season-specific career changes (nflverse `players.csv` carries one position per career):
  - Terrelle Pryor: QB in 2013-15, then WR.
  - Cordarrelle Patterson: WR 2013-20, then RB. This one is a judgement call; platforms dual-listed him in 2019-20.
- Flagged, not changed:
  - Taysom Hill (TE/QB; TE on most platforms)
  - Ty Montgomery (WR listed; RB on platforms 2016-19)
  - WR/RB hybrids: Deebo Samuel, Curtis Samuel, Tavon Austin, Percy Harvin, McCluster
  - Platform disagreement on these is a known limit.
- Worth: per-game 2.627/.472 → 2.621/.477 (A7 data vs rebuilt data). Hunter now appears at WR43 (overall 101).

**Fix 4. Ranges too wide.** Kept, but the cause was not what A2 said.
- **First try failed:** walk-forward isotonic on P(miss 2+/4+/8+), fit on the in-house relevance pool. On the ADP pool, P(8+) only moved .216 → .211 (actual .157), and coverage went 83.3 → 82.8%. The draftable players are healthier than the relevance pool, a selection the in-house model can't see.
- **Second try:** isotonic fit on the model's **own top 150** (by its projected total; no ADP), plus a per-game spread taken from those same draftable rows.

| Version | Pool | p10-p90 | Below / above | p25-p75 |
|---|---|---|---|---|
| Before | ADP top 150 | 83.7% | 4.9 / 11.4 | 52.0% |
| Before | model top 150 | 86.1% | 5.9 / 8.0 | 54.5% |
| After | ADP top 150 | 78.7% | 7.1 / 14.2 | 48.1% |
| After | **model top 150** | **80.2%** | **8.6 / 11.2** | **48.5%** |

- The remaining skew on the ADP pool (more misses above) is the model's level being too low on players the market likes. That is an average problem, not a width problem.
- Examples: Allen's season-total p10 went 59 → 138, Chase 64 → 79, Burrow 42 → 92.

**Before / after (ADP top 150).** Per-game is games-weighted MAE / rank rho. Totals are MAE / Spearman / top-12 hit / top-24 hit.

| Cut | Per-game before (A7) | Per-game after | ADP | Totals before | Totals after (fix 1) | ADP totals |
|---|---|---|---|---|---|---|
| All 2015-25 | 2.627 / .472 (1/11 seasons) | 2.621 / .477 (1/11) | 2.491 / .548 | 51.3 / .469 / .447 / .653 | 51.3 / .468 / .451 / .653 | 49.7 / .501 / .538 / .659 |
| Dev 2015-22 | 2.658 / .481 | 2.649 / .488 | 2.479 / .554 | 50.8 / .452 | 50.8 / .451 | 49.1 / .496 |
| Holdout 2023-25 | 2.554 / .446 | 2.554 / .448 | 2.519 / .532 | 52.5 / .513 / t12 .486 | 52.5 / .514 / t12 .500 | 51.2 / .515 / t12 .542 |
| QB | 2.679 / .329 | 2.664 / .346 | 2.542 / .454 | 65.8 | 65.6 | 63.9 |
| RB | 3.058 / .553 | 3.051 / .556 | 2.839 / .640 | 56.1 / .460 | 55.9 / .462 | 54.4 / .506 |
| WR | 2.395 / .554 | 2.390 / .556 | 2.322 / .601 | 45.8 / .478 | 45.9 / .480 | 44.6 / .497 |
| TE | 1.973 / .438 | 1.972 / .438 | 1.870 / .489 | 37.0 | 37.3 | 34.8 |
| Rookies | 2.822 | 2.800 | 2.794 | 52.8 | 53.0 | 49.4 |
| Range coverage p10-p90 (model top 150) | 86.1% | **80.2%** | | | | |

**Contribution of each fix:**
1. Fix 1: totals about 0; it fixes the group it targets (group games MAE −0.14).
2. Fix 2: none.
3. Fix 3: per-game −0.006 MAE, +.005 rho, and adds Hunter.
4. Fix 4: ranges fixed (86 → 80%), with no effect on the means.

**Lists regenerated.** `output/2026_inhouse_check.md`/`.csv` and `2027_inhouse_early.md`/`.csv` are the v2 files. The v1 files are kept with a `_v1` suffix. Movers are in `output/2026_movers_v1_to_v2.csv` and at the end of the 2026 markdown file.
- Only 5 players moved 10+ overall spots or 3+ position spots: Jayden Reed 142 → 125, Burrow 109 → 120, Kittle 77 → 67, Mike Evans 73 → 63, and Hunter (new at 101).
- Saquon, Jeremiyah Love and the backup RBs (Corum, Allgeier, Keaton Mitchell, Jordan Mason) did not move, because no fix earned the right to move them on history.
- Biggest-disagreements tally (v2): **ADP 16, model 11, too few games 3** (v1: 14 / 12 / 4). Hunter entered the high list, and ADP was closer on him so far.

**What's next:**
1. QB ordering (the worst area; fix 1 didn't help): QB volume, rushing share and benching risk for QBs short for role.
2. RB volume with team-level consistency (A7's next weakest piece).
3. The in-house level is too low on market-favoured players. Only market data fixes that cleanly; that is the ADP decision, parked.
4. A redraft ADP for 2026 comparisons. None is on disk; a data pull would need approval.


### A10. QB ordering (2026-11-21): no in-house fix found; the gap is smaller than it looked; superflex view added

Jack: "Fix QB order first". ADP is still approved but parked; nothing here uses it as an input.

**Code and logs** (all in `preseason2027`):
- `qb_a10.py` → `qb_a10.log` (diagnosis + round 1)
- `qb_a10b.py` → `qb_a10b.log` (round 2)
- `sf_view_a10.py` → `output/sf_view_a10.log`
- `output_rankings.py` v3; v2 is kept as `output_rankings.py.bak_v2_20261121`

**Method.** Choices were made on 2015-22. 2023-25 is reported separately and has been viewed before.

**QB pool (new).** Every week-1 chart QB1, plus every QB with 4+ games of 15+ attempts, 2015-25. That is 463 QB-seasons (343 week-1 starters), against 219 in the old ADP-top-150 QB table.

**The ".346 vs .454" gap was mostly the narrow pool.** On the ADP-top-150 QBs (about 18 per season, all of them good), the in-house rank correlation is only .074, because the spread is so narrow.

| QB set | Model | MAE | Rank rho | Top-12 hit | Top-24 hit | QB1-6 who finish top 12 |
|---|---|---|---|---|---|---|
| Full pool | In-house | 2.727 | .627 | .558 | .783 | .633 |
| Full pool | Naive last-season PPG | 3.497 | .537 | .553 | .777 | .591 |
| QBs with ADP | In-house | 2.635 | .406 | .593 | .940 | **.683** |
| QBs with ADP | ADP | **2.506** | **.486** | **.694** | .944 | .667 |

- On QBs with ADP, in-house beats ADP on rank in 2 of 11 seasons.

**Which component costs the most.** Each row swaps in the actual value of one piece of the structural QB number. Before any swap: MAE 2.720, rank .608.

| Swapped component | MAE | Rank |
|---|---|---|
| **Passing TD rate** | **2.024** | **.784** |
| Pass attempts | 2.288 | .698 |
| Yards per attempt | 2.389 | .719 |
| Rush attempts | 2.579 | .637 |
| Rushing TD | 2.641 | .624 |
| INT | 2.686 | .618 |
| Rush yards per carry | 2.691 | .619 |

- TD rate is the biggest miss on both error and order, then attempts and yards per attempt. Rushing is small.
- On season totals, **games played dominates**: rank .621 with predicted games, .912 with actual games.

**QB types (MAE, act/pred):**

| Type | MAE | Act/pred |
|---|---|---|
| Rookies | 3.119 | 1.033 |
| Second year | 3.187 | .985 |
| **Backups who took over** | 3.087 | **1.126** (model low) |
| Back from a short season | 3.038 | 1.024 |
| **Job threat** (team drafted a round-1 QB) | 3.042 | **.844** (model high, n 17) |
| New team | 2.923 | .957 |
| Established, same team and coach (best) | 2.424 | 1.039 |

**The four 2026 patterns, tested on history:**
1. *Does the model over-rate rushing QBs?* No; it is the other way round. On history the model **under**-rates them: act/pred 1.099, rushing part 1.075. Lamar and Hurts in 2026 are not a pattern.
2. *Does it over-trust one big season?* No. QBs after a +3 PPG jump came in **above** the projection (1.112). Dart and Baker are not a pattern either.
3. *Does it under-rate proven passers off a short year?* Yes, but the sample is tiny (n 16): per-game 1.177, games 10.6 predicted vs 12.2 actual.
4. *QBs who lost time to role last year:* games 7.0 predicted vs 8.9 actual. With this definition the model is too **low**, not too high.

**Candidates, all dropped.** The bar was +.005 rank on dev with MAE no worse. Figures are dev MAE / rank (base 2.740 / .641), then holdout rank (base .592).

| Candidate | Dev MAE / rank | Holdout rank | Result |
|---|---|---|---|
| Team context for QB volume (win totals, team pass/rush volume, new HC, new QB) | 2.785 / .628 | .563 | Worse |
| Rushing age decline | 2.739 / .631 | .592 | Fails |
| One-season-jump flag | 2.734 / .642 | — | Rank +.001, fails the bar |
| More weight on the multi-season ridge (QBs only) | 2.783 / .631 | — | Fails |
| Lighter TD-rate shrink (k 640 / 320 / 160 vs fitted 1,280) | 2.757 / .631 down to 2.779 / .621 | .608 / .615 / .621 | **Dev and holdout disagree; not kept** |
| TD rate scaled by team strength (+.05 per expected win, stable 2016-25) | 2.746 / .634 | .596 | Fails |
| QB level calibration | 3.04+ | — | Much worse; the bias isn't uniform |
| QB-specific games terms (est. × short year, job threat, low prior PPG) | Games MAE 2.78 → 2.76 dev; 3.28 holdout unchanged; est.-off-short group worse (3.56 → 3.69) | — | Not kept |

- The lighter TD-rate shrink is the one to re-check with 2026 added: it is better on the holdout but worse on dev.

**How much of the gap is closable.** On QBs with ADP the gap is .08 in rank and .13 in MAE. In-house is already level with ADP on the top of the order (QB1-6 finishing top 12, top-24 hit). What is left is mostly:
- TD rate, which is largely noise year to year
- games and job outcomes: who wins the job in August, benchings, and rookies starting

That information sits with the market. Closable in-house with data on disk: perhaps a little through contracts (`pbp_cache/otc/historical_contracts.parquet` is on disk and wasn't tested) and through a job-security term once there are more seasons.

**Other positions and the overall list.** Unchanged. Overall top-150 totals MAE 51.31 / rank .468 before and after. QBs keep the same value-over-replacement placement.

**v3 lists.** v1 and v2 are kept.
- **2026 check:** QB order is identical to v2; no QB moved 3+ spots. The QBs that looked wrong (Lamar, Hurts, Dart and Baker high; Burrow at QB17) did not move. History says the model's general tendency is to *under*-rate rushing QBs and one-big-season QBs, so moving them down would have gone against the evidence.
- **2027 look:** data-handling fix. The current ESPN chart lists injured starters behind their backups (Lamar and Hurts were second on 2026-11-21). For 2027 only, each player's chart rank is now the better of his current rank and his 2026 usage rank, and QB1 is the team's 2026 starts leader. Result: Hurts QB35 → QB19, Lamar QB42 → QB30, Winston 33 → 22; other QBs shift 3-4 spots as a result. Matthew Golden enters the overall top 24 (#18) for the same reason.

**Superflex view (new section in both lists).**
- Replacement levels: QB20 / QB24 / QB28 at 10 / 12 / 14 teams. Overall superflex rank for 12 teams, with RB31 / WR41 / TE12.
- **2026 check, superflex QB value (12 teams):** Allen 97 (SF #7 overall), Lamar 71 (#20), Hurts 68 (#23), Maye 64 (#24), Goff 63, Mahomes 53, Dart 51, Baker 50, Herbert 48, Lawrence 47, Caleb 41, Love 38.
- **2027 look:** Allen 102 (SF #7), Maye 70 (#21), Burrow 65 (#22), Goff 62 (#24), Mahomes 60, Lawrence 56, Stafford 50, Love 45, Stroud 40, Nix 39, Daniels 36, Rodgers 34.

**Data for approval:** none new is required. On disk and untested: OTC contracts, for a job-security term. Still listed from before: historical August depth charts, which is where the "who won the job" information lives.

**Next:**
1. Job security from on-disk contracts plus draft capital, fed into QB games.
2. Re-test the lighter TD-rate shrink with the full 2026 season added.
3. RB volume with team-level consistency.
4. The ADP version is still parked.


### A11. QB job security from contracts + draft capital (2026-11-21): KEPT - the first QB fix that holds up

Jack said: "Try job security". ADP stays parked.

**Where it lives:**
- Code: `preseason2027/qb_a11.py`; log: `qb_a11.log`.
- The lists are now v4. Backups: `output_rankings.py` and `sf_view_a10.py` as `.bak_v3_20261121`, and the `*_v3.*` lists are kept.

**Is the contract data usable point-in-time? Yes, with restrictions.**

| Category | Fields |
|---|---|
| Safe (known at signing) | `year_signed`, `years`, `value`, `apy`, `guaranteed`, `apy_cap_pct`, draft year / round / overall, date of birth, `gsis_id`, and `contract_type` from `contract_history` (matched to the deal by year + total) |
| Leaks (never used) | `is_active`; `inflated_*` (restated to today's cap); `season_history` (cash paid, cap number, base / guaranteed salary by year; restructures and cuts rewrite these); `contract_history` status, amount earned, percent earned and effective APY (all outcomes) |

- **Contract in force for season Y:** the latest deal signed in Y-1 or earlier, or one signed in Y if it is an offseason type (Drafted, UFA, RFA, ERFA, Franchise, Transition, SFA, UDFA).
- Extensions dated Y are skipped, because some are signed during the season.
- **Can't be rebuilt point-in-time:** guaranteed money still owed (the yearly schedule lives in `season_history`) and fifth-year option decisions. Only total guarantee share, years left and cap share are usable.
- **Coverage:** 460 of 463 QB-seasons in the A10 pool (99.4%). Missing: Jimmy Clausen 2015, Dwayne Haskins 2019-20.

**Outcome: losing the job while healthy.**
- Definition: a week-1 QB1 sits for 2+ team games where another QB started (most attempts, 15+), while he was not listed Out or Doubtful and not on a reserve list. Being traded or cut counts.
- The injury split is fairly clean: a QB who was hurt and then lost the job counts only for the weeks he was healthy.
- Base rate: **23.1% of 398** week-1 starters, 2013-25. By season it runs 11-29%, and 28-29% in 2022-25.
- Cost: benched QBs played 8.8 games vs 13.9 for the rest, and lost 6.0 healthy weeks on average.

**Mirror: backups who took over.**
- 20.9% of week-1 backups (chart 2-3 or rookies, n 561) made 4+ starts.
- Rookies: 18.4%. **Round-1 rookies not starting in week 1: 70.8% (n 24).**
- First start: median week 5. 46% by week 4, 33% in weeks 5-9, 15% in week 10 or later.

**The probability model.**
- Logistic regression (C .3), walk-forward, on three inputs:
  - Money: the cap share of the deal in force
  - A QB drafted in rounds 1-2 this year or last behind him
  - Team outlook: de-vigged expected wins
- Benched rates by input:

| Group | Benched while healthy |
|---|---|
| Money, bottom third | 38.5% |
| Money, top third | 9.6% |
| High pick behind him (n 28) | **82.1%** |
| No high pick behind | 18.6% |
| Expected wins ≤ 6.5 | 46.4% |
| Expected wins ≥ 9.5 | 6.7% |

- Standardized coefficients: money -.62, high pick behind +.67, expected wins -.50.
- Brier score vs base rate:

| Version | Dev Brier | Holdout Brier |
|---|---|---|
| Base rate | .1733 | .2083 |
| **3 inputs** | **.1225** | **.1752** |
| + prior production | .1210 | .1748 |
| + rookie deal / bridge / years left | .1224 | .1711 |
| + new HC / age | .1237 | .1752 |

  The extra inputs don't clearly earn their place, so the model stays at 3 inputs.
- Calibration: .03→.05, .07→.06, .15→.21, .24→.31, .36→.43, .76→.84. It runs slightly low in the middle bins, because recent seasons bench more.

**Feeding it into QB games played.** Week-1 QB1s only: games share minus (P - base rate) × average games lost when benched / G, all walk-forward.

| Group | MAE before | MAE after | Note |
|---|---|---|---|
| Dev pool | 2.78 (corr .595) | **2.72 (corr .616)** | |
| Holdout | 3.28 | **3.14** | |
| Back from a short season | 3.95 | 3.90 | Not made worse, unlike A10's terms |
| Round-1 job threat | 4.62 | 4.68 | Slightly worse: now overshoots, 4.6 vs 7.7 actual |
| High pick behind | 3.77 | 3.93 | Slightly worse: overshoots, 6.5 vs 8.5 actual |

Used as a games-model feature instead, it was worse (dev 2.88) and was dropped.

**QB season totals** (MAE / rank rho, plus top-12 / top-24 hit rates where shown):

| Pool | Before | After | ADP |
|---|---|---|---|
| Dev | 62.0 / .646 / .560 / .810 | **61.0 / .659 / .560 / .815** | — |
| Holdout | 69.7 / .562 / .500 / .750 | 67.8 / .567 / .444 / .764 | — |
| Dev, QBs with ADP | 63.2 / .359 | 62.4 / .359 | 58.9 / .458 |
| Holdout, QBs with ADP | 75.3 / .200 | **72.6** / .233 | 73.1 / .247 |
| **Superflex band, QB13-28** | 66.3 / .282 | **64.0 / .313** | — |

- On the holdout, in-house error now beats ADP for QBs with ADP (72.6 vs 73.1).
- This clears the A10 bar on 2015-22: rank +.013, error -1.0. **KEPT.**
- Other positions are untouched.

**v4 lists.**
- **2026 check, QB top-24 movers:**
  - Herbert 9→7, Lawrence 10→8, Love 12→10, **Prescott 16→11**, **Burrow 17→15**, Purdy 19→16 (secure starters gain about 1 game).
  - **Dart 7→13** (P .25), **Nix 13→19** (.31), Daniels 21→24 (.32), Stafford 26→27 (.56).
  - Josh Allen enters the overall top 24 at #21.
  - Against 2026 so far, this mostly moved the right way: Prescott is QB4, Burrow QB1, Purdy QB3, Love QB5, Dart QB38.
  - The ugly one: Stafford at P .56 (high pick behind him) is QB11 and still starting.
- **2027 look:** Maye 2→6 (P .24), Stafford 7→18 (.54), Nix 10→15, Stroud 9→12, Daniels 11→16. Purdy 13→8, Herbert 15→9, Prescott 16→10, Hurts 19→14.
- P(lose the job) is a column in both CSVs and in the superflex QB tables.

**Other positions:** the same at-signing fields could support RB/WR job security (veterans on expiring deals, high picks behind them). Not built or tested.

**Next:**
1. A rookie / backup start-date probability (71% for round-1 rookies not starting in week 1, median week 5), fed into their games.
2. A recheck of the calibration drift.
3. RB volume consistency.
4. ADP stays parked.

### A12. Start-date odds for rookie and backup QBs, as one team QB-room model (2026-11-21, Jack "Yes, add them"): NOT KEPT as an input; lists stay v4

The test: for every QB who is not the week-1 starter, the chance he becomes the starter (4+ starts) and when. The room's
expected starts are built to sum to the team's games, using A11's games for the starter and splitting what is left across the
backups by P(take over). The code is in `preseason2027/qb_a12.py` with log `qb_a12.log`, and the examples are in
`qb_a12_examples.py` with log `qb_a12_examples.log`. Choices were made on 2015-22; 2023-25 is shown but was already viewed.
In-house inputs only, and contracts are point-in-time.

**Base rates.** Week-1 non-starters, 2013-25, who got 4+ starts (90% Wilson range):

| type | n | 4+ starts | range | first start (median wk) | share of remaining games he started |
|---|---|---|---|---|---|
| rookie, round 1 | 24 | 70.8% | 54-83 | 4 | .88 |
| rookie, round 2 | 7 | 42.9% | 19-71 | 8 | 1.07 |
| rookie, later | 175 | 10.3% | 7-15 | 6 | .79 |
| veteran backup (cap >= 2%) | 128 | 30.5% | 24-38 | 3 | .67 |
| journeyman backup | 432 | 14.4% | 12-17 | 5 | .68 |
| former starter on reserve wk 1 | 9 | 44.4% | 22-70 | 6 | .79 |
| all | 775 | 18.5% | 16-21 | 5 | .73 |

- Why it happened: in teams where the week-1 starter missed 4+ starts, the cause was a healthy benching, cut or trade in 76
  and an injury in 56.
- Production: backups who took over scored 1.13x their own per-game projection (n 104).

**P(take over).** A small walk-forward logistic on draft pick, rookie, prior starts, cap share and age.
- Brier .1420 vs .1458 for the base rate, a small gain.
- Overconfident at the top: predicted .46 came true .28 of the time, and predicted .73 came true .40.
- Round-1 rookies come out too low (5.25 expected starts vs 7.14 actual). 2025 example: Dart had P .24 and made 10 starts.

**Room model vs before:**

| check | before (A11) | room model |
|---|---|---|
| room add-up, mean abs gap vs team games | 3.9 | **0.10** |
| backups' starts MAE, dev / holdout | 3.05 / 2.88 | **1.98 / 2.07** |
| backups' starts rho, dev / holdout | .287 / .277 | .297 / .323 |
| backups' totals MAE, dev | 37.5 | 27.8 |
| backups' totals rho, dev / holdout | .282 / .302 | **.254** / .343 |
| all QBs, totals rho, dev / holdout | .751 / .732 | **.742** / .751 |
| all QBs, totals MAE, dev / holdout | 46.0 / 48.4 | 39.7 / 44.0 |
| A10 pool MAE, dev / holdout | 62.6 / 69.1 | **65.1 / 73.7** |
| superflex QB13-28 rho, dev / holdout | .375 / .307 | .357 / **.116** |
| superflex QB25-40 rho, dev / holdout | .434 / .617 | **.354** / .617 |
| week-1 starters, games MAE (benching timing by "high pick behind") | 2.81 | 2.82 |

**Decision.**
- The room model is a real calibration gain for backups' starts, and the rooms now add up. But it makes the season-total
  order worse on dev: all-QB rho falls .009, and superflex QB25-40 falls .08. On the holdout, superflex QB13-28 collapses.
- That fails the bar, so it is **not fed into the totals**, and the lists stay v4 (no v5).
- Timing the benching by "high pick behind" adds nothing, so it was dropped.
- Jack's call: P(becomes starter) and expected starts could go on the lists as information columns. They would not change
  totals or ranks. I would fix the overconfidence above .35 first.

**Found along the way.** Rookies who start week 1 (n 18) get an A11 P(bench) of .33, but only .06 were actually benched.
Their cap share on a rookie deal reads as "cheap", so their games are under-projected (11.8 vs 13.8 actual). This is the next
thing to test: treat rookie deals separately in the A11 money term.

**2026 examples.** These come from the preseason chart with P fit on 2013-25; "what happened" covers 2026 weeks 1-10.

| QB | team | P(4+ starts) | 2026 starts (first) |
|---|---|---|---|
| Fernando Mendoza (rookie, #1) | LV | .42 | 1 (wk 10) |
| Marcus Mariota | WAS | .38 | 1 (wk 3) |
| Michael Penix Jr. | ATL | .37 | 8 (wk 3) |
| Joe Flacco | CIN | .34 | 0 |
| Mac Jones | SF | .33 | 0 |
| J.J. McCarthy | MIN | .33 | 3 (wk 7) |
| Carson Wentz | MIN | .33 | 3 (wk 1) |
| Justin Fields | KC | .31 | 0 |
| Jameis Winston | NYG | .30 | 5 (wk 2) |
| Ty Simpson (rookie) | LAR | .28 | 0 |

- 2026 so far: mean P .177 vs 4+ starts .048 through week 10. Part of the gap is the unfinished season. The rest matches the
  overconfidence seen in history.

**2027 note.**
- No 2027 rookies exist yet, so the main use comes after the April draft. A round-1 rookie backup is the 71% case.
- For current backups, the current-chart look is noisy. It lists Daniel Jones (IND, 10 starts), Cousins (MIN, 10) and
  Brissett (BAL, 8) as backups. Any 2027 room column needs the A10 usage-rank fix applied to backups too.

**RB backups (not built).** A9 already showed that backup-RB take-over odds don't improve the mean as an input. The same
room idea would have to split carries rather than starts, so I would not expect a different answer.

### A13. Rookie-deal starters in A11's job security (2026-11-21, Jack "Yes, test it"): KEPT the single "investment" input; lists are v5

**The question.** A11 reads cap share as a QB's hold on the job. Every QB on his rookie deal has a small cap share (median
3.0%, vs 14.4% for veterans), whatever his draft capital. So I widened the check from week-1 rookies to every week-1 starter on
a rookie deal: a drafted QB in deal years 1-4 whose contract in force is his Drafted/UDFA deal. That is 143 of 398 week-1
QB1s, 2013-25. Contract fields are at-signing only, as in A11, with no fifth-year options and no money owed. The code is in
`preseason2027/qb_a13.py`, with log `qb_a13.log` and rows in `data/qb_a13_rows.parquet`.

**Measured bench rates (benched while healthy, 2+ games).** "Actual" uses 2013-25 with 90% ranges. "A11 mean P" uses the
2015-25 walk-forward rows.

| group | n | actual | range | A11 mean P | actual, same rows |
|---|---|---|---|---|---|
| rookie deal, all | 143 | 25.9% | 20-32 | 26.5% | 26.4% |
| rd 1, deal yr 1-2 | 54 | 16.7% | 10-27 | **26.7%** | 15.6% |
| rd 1, deal yr 3-4 | 51 | 27.5% | 19-39 | 19.8% | 22.5% |
| rd 2 | 17 | 23.5% | 11-43 | 26.2% | 33.3% |
| rd 3-7 + UDFA | 21 | 47.6% | 31-65 | 42.4% | 62.5% |
| deal yr 1 | 21 | 4.8% | 1-19 | **33.3%** | 6.2% |
| deal yr 2 | 51 | 33.3% | 24-45 | 28.7% | 33.3% |
| deal yr 3 | 38 | 23.7% | 14-37 | 22.5% | 18.5% |
| deal yr 4 | 33 | 30.3% | 19-45 | **22.6%** | 36.0% |
| veteran deal, all | 255 | 21.6% | 18-26 | 16.8% | 22.9% |
| vet, cap < 5% | 41 | 61.0% | 48-72 | 45.4% | 61.8% |
| vet, cap 5-10% | 24 | 41.7% | 27-58 | 35.5% | 57.1% |
| vet, cap >= 10% | 191 | 11.0% | 8-15 | 9.0% | 12.0% |

**What the table shows.**
- The error is not a blanket rookie-deal error: on the group as a whole, A11 is right on average (26.5% vs 26.4%).
- It is two opposite errors. A11 over-benches first-round picks in years 1-2 (the year-1 case most of all: 33% predicted vs
  6% actual). It under-benches year-4 QBs and mid/late-round picks.
- Veterans on cheap deals are far more benchable (61%) than the same cap share on a rookie deal, so mixing the two blunted
  the money signal for veterans too.
- Rookie-deal rows are 34% of A11's dev rows but carry 45% of its squared error.

**Candidates.** All constants were fixed before seeing results. The other two A11 inputs stay in every version.

| candidate | Brier dev (all / rookie deal / vets) | Brier holdout (all / rookie deal / vets) |
|---|---|---|
| base rate | .1736 | .2075 |
| A11 (cap share) | .1225 / .1611 / .1026 | .1752 / .2042 / .1583 |
| F1 rookie-deal flag (cap share for vets only) | .1219 / .1643 / .1000 | .1760 / .2185 / .1512 |
| F2 flag + draft capital | .1209 / .1604 / .1004 | .1706 / .2056 / .1503 |
| **F3 one investment input** | **.1138 / .1407 / .0999** | **.1636 / .1884 / .1491** |

F3: investment = max(min(1, cap share / .15), draft score x fade).
- Draft score = 1 - log(pick)/log(262), and 0 for UDFA.
- Fade = 1, .8, .6, .4, .2 for years 1-5 (max(0, 1 - exp/5)).
- It replaces cap share for everyone.

**Calibration by sub-group, 2015-25 walk-forward (mean P vs actual):**

| group | A11 | F3 | actual |
|---|---|---|---|
| rd 1, yr 1-2 | 26.7% | 17.6% | 15.6% |
| rd 1, yr 3-4 | 19.8% | 20.4% | 22.5% |
| rd 3-7 + UDFA | 42.4% | 48.9% | 62.5% |
| deal yr 1 | 33.3% | 20.1% | 6.2% |
| deal yr 4 | 22.6% | 26.8% | 36.0% |
| veterans | 16.8% | 18.2% | 22.9% |
| vet, cap < 5% | 45.4% | 53.1% | 61.8% |

- Every sub-group moves toward the truth. The year-1 case is still too high (n 16).
- The "slightly low" calibration elsewhere is smaller but not gone. Veterans are still under-predicted, and the mid bin goes
  from .15 -> .21 to .14 -> .17.
- About 80% of the dev Brier gain comes from the rookie-deal rows.

**Games and totals (A11 form).**

| check | no job security | A11 | F3 |
|---|---|---|---|
| dev pool games MAE | 2.78 | 2.72 | 2.72 |
| holdout pool games MAE | 3.28 | 3.14 | 3.13 |
| rookie-deal starters games MAE | 2.35 | 2.46 | 2.39 |
| rd 1 yr 1-2 games MAE | 2.49 | 2.70 | 2.49 |
| rd 2+ / UDFA games MAE (n 28) | 2.73 | 2.88 | **2.98** |
| veteran starters games MAE | 2.83 | 2.59 | **2.63** |
| team drafted a rd-1 QB / high pick behind / back from short season | 4.62 / 3.77 / 3.95 | 4.68 / 3.93 / 3.90 | 4.80 / 4.01 / 3.94 |
| dev totals MAE / rho | 62.0 / .646 | 61.0 / .659 | 61.0 / .661 |
| holdout totals MAE / rho | 69.7 / .562 | 67.8 / .567 | 68.2 / .573 |
| dev, QBs with ADP: MAE / rho (ADP 58.9 / .458) | 63.2 / .359 | 62.4 / .359 | 62.3 / .356 |
| holdout, QBs with ADP: MAE / rho (ADP 73.1 / .247) | 75.3 / .200 | 72.6 / .233 | 72.9 / **.251** |
| veteran starters totals MAE, dev / holdout | 62.3 / 74.0 | 60.2 / 70.5 | **60.5 / 71.0** |
| superflex QB13-28 rho, dev / holdout | .367 / .044 | .355 / .210 | .354 / **.183** |

**Decision: KEPT F3.**
- It clears the bar: a clear calibration gain for the group (Brier -.020 dev, -.016 holdout), a better overall Brier on both
  splits, and dev season-total rho not worse (.661 vs .659).
- Costs to flag for Jack:
  - Veteran starters' games and totals are a hair worse than A11 (games MAE +.04; totals MAE +.3 dev, +.5 holdout), even
    though their Brier is better. A11's gain over no job security is mostly kept (2.83 -> 2.63 vs 2.59).
  - Holdout superflex QB13-28 rho drops .210 -> .183.
  - Mid/late-round rookie-deal starters' games get worse (n 28).
- F2 had the best dev rho (.668), but it left the round-1 year-1-2 over-benching in place. F1 made the rookie-deal Brier worse.

**v5 lists.** v4 is kept as `output/*_v4.*`, and the scripts are backed up as `.bak_v4_20261121`. The movers are in
`output/movers_a13.log`. Non-QB totals are unchanged (overall ranks move by at most 2 as QBs shift).

2026 check, the young starters (P(bench) v4 -> v5, QB rank v4 -> v5; 2026 weeks 1-10 as examples, not proof):

| QB | P(bench) | QB rank | 2026 so far |
|---|---|---|---|
| Maye | .13 -> .11 | 5 | QB7 |
| Caleb Williams | .15 -> .10 | 12 -> 11 | 6 g |
| Dart | .25 -> .26 | 13 -> 12 | 2 g, Winston started 5 |
| Stroud (yr 4) | .21 -> .24 | 17 -> 18 | QB8 |
| Nix | .31 -> .32 | 19 | — |
| Cam Ward (#1 pick, yr 2) | .30 -> .16 | 20; games 13.5 -> 14.2 | 9 g |
| Bryce Young (yr 4) | .32 -> .35 | 23 -> 24 | QB14, 9 g |
| Daniels | .32 -> .28 | 24 -> 21 | — |

- The round-1 years 1-2 history (16.7% benched) supports Ward and Caleb dropping. The year-4 history (30% benched) supports
  Young and Stroud rising.
- Cheap veterans rise:

| QB | P(bench) | 2026 so far |
|---|---|---|
| Geno | .38 -> .53 | started 10 |
| Tua | .37 -> .54 | 1 g, 0.4 ppg |
| Kyler | .27 -> .41 | 6 g |
| Brissett | .45 -> .54 | — |
| Cousins | .34 -> .44 | QB6 |
| Stafford | .56 -> .47 | QB11 |

- On 31 QBs, the 2026-so-far QB rank correlation is .132 in v4 and .114 in v5: one partial season, noise either way.

2027 early look:
- Mendoza (#1 pick, yr 2): .22 -> .12, QB27 -> 23.
- Ward: .23 -> .17.
- Year-4 QBs rise: Stroud .24 -> .32, Bryce Young .23 -> .31, Nix .27 -> .34, Maye .24 -> .29 (the 2027 fade is one year further on).
- Cheap veterans rise: Kyler .30 -> .45, Geno .28 -> .42, Winston .26 -> .38.
- The 2027 rookie class isn't in it yet. When it is, a round-1 rookie starter would get the full draft score, the case A11
  got most wrong.

**Next.**
- Veterans are still under-predicted on benching (18% vs 23%, worst at cap 5-10%).
- The year-1 rookie starter is still too high (20% vs 6%, n 16). With this little data I would not add a separate term.

### A14. RB volume (2026-11-21, Jack "Yes, RB volume"): KEPT share inputs + a half-way team rescale, and RB ranges by backfield tier; lists are v6

In-house inputs only: no ADP as an input, no outside projections. Choices were made on 2015-22; 2023-25 is the
already-viewed holdout. The redraft ADP curve from A9 is the benchmark.

Code, all in `preseason2027/`:
- `rb_a14_common.py`: goal-line carries from the on-disk pbp, team RB tables, shares, RB investment.
- `rb_a14_diag.py`: diagnosis, log `rb_a14_diag.log`.
- `rb_a14_build.py`: candidates, log `rb_a14_build.log`.
- `rb_a14_judge.py`: judging, log `rb_a14_judge.log`.
- `rb_movers_a14.py`: list comparison, log `output/rb_movers_a14.log`.

**Step 1, diagnosis.** RB per-game error with one piece swapped for the actual. The pool is every RB at chart spots 1-3,
dev 2015-22.

| swap | pool MAE | pool rho | ADP-150 MAE | ADP-150 rho |
|---|---|---|---|---|
| v5 as is | 2.851 | .630 | 3.030 | .533 |
| actual carries/g | 1.992 | .857 | 2.156 | .811 |
| actual targets/g | 2.428 | .757 | 2.639 | .667 |
| carries: actual TEAM total only | 2.825 | .644 | 3.068 | .545 |
| carries: actual SHARE only | **2.200** | **.822** | 2.417 | .732 |
| targets: actual TEAM total only | 2.797 | .637 | 2.981 | .548 |
| targets: actual SHARE only | 2.557 | .737 | 2.774 | .632 |
| goal-line carries actual (league TD rates inside / outside the 10) | 2.592 | .706 | 2.745 | .626 |
| ADP (redraft) | | | 2.793 | .647 |

- **Share, not team total.** The miss is the player's share of his team's RB work. Getting the team total exactly right is
  worth almost nothing (-.03 MAE on carries, -.05 on targets). Getting the share right is worth -.65 on carries and -.29 on
  targets. Rushing share matters most, then receiving.
- **Goal-line work is a real third piece.** Knowing actual goal-line carries is worth -.26 MAE, about 40% of everything rushing
  TDs could be worth.
- **Does it add up today? Yes, on average.**
  - Projected carries per team game for the listed backs sum to 1.00x the team's RB carries (targets 1.07x).
  - Team by team the 10-90% range is .77-1.35, so there is no 120% problem on average.
  - The shares are too FLAT: spot 1 gets .433 of team carries vs .468 actual, spot 2 .233 vs .241, spot 3 .140 vs .113.
  - Summed per game played (no games share), the listed backs come to 2.19x a team's RB carries, because backups' per-game
    roles overlap with the starter's.
- **Situations: where the error sits** (pool 2015-25; carries/g bias, and share of all RB error):
  - lead back returning to the same team: -.07, 21% of the error (his ppg MAE of 3.19 is the highest)
  - team lost its lead back: +.19, 23%
  - new play-caller (OC/HC change, 2019+): +.36, 31% of rows, average error
  - committee: +.25, 16%
  - late-round rookie: +.80, 15%
  - rushing-QB team: +.38, 12%
  - vet facing a new rd 1-3 back: +.27, 11%
  - lead back who changed teams: +.71, 7%, with the worst per-row error (3.52)
  - Overall the model over-projects carries per game played by +.35.
- **Stickiness (r with last season):**
  - team RB carries per game .33, team RB targets .52, RB target share .47, team goal-line carries .26, QB rush share .69
  - a returning lead back's carry share .42 (slope .62), his RB-target share .62, his goal-line share .37
  - Last year's goal-line share adds a little beyond carry share (partial r .18).
  - So the team totals should be regressed hard (about two-thirds toward the league). Shares persist better, and receiving
    share is the stickiest.

**Step 2, candidates.**

Team-total model (walk-forward team ridge on last 2 seasons, expected wins, pass rate, pace, QB rush share, new play-caller):

| team total | ridge | last season | league mean | ridge r |
|---|---|---|---|---|
| RB carries per team game, MAE dev | 2.06 | 2.39 | 2.17 | .28 |
| RB targets per team game, MAE dev | 1.16 | 1.32 | 1.30 | .48 |

Per-game MAE / rho:

| candidate | pool dev | pool holdout | ADP-150 dev | ADP-150 holdout |
|---|---|---|---|---|
| v5 | 2.851 / .630 | 2.808 / .719 | 3.030 / .533 | 3.104 / .619 |
| C1 team rescale, half-way | 2.898 / .637 | 2.859 / .722 | 3.222 / .541 | 3.307 / .614 |
| C1 team rescale, full add-up | 3.104 / .637 | 3.096 / .722 | 3.578 / .539 | 3.700 / .602 |
| C2 share inputs in the RB volume ridge | 2.869 / .628 | 2.793 / .718 | 3.051 / .532 | 3.105 / .613 |
| C3 share inputs + full add-up | 2.857 / .640 | 2.901 / .719 | 3.089 / .545 | 3.287 / .578 |
| **C3 share inputs + half-way rescale (kept)** | **2.825 / .643** | 2.814 / .725 | **3.014 / .550** | 3.141 / .611 |
| C4 goal-line TD rate (EB goal-line carries per carry) | 2.859 / .628 | 2.803 / .719 | 3.039 / .528 | 3.096 / .615 |
| C2 + C4 | 2.877 / .625 | 2.790 / .720 | 3.061 / .524 | 3.101 / .616 |
| ADP (redraft) | 2.785 / .647 | 2.708 / .739 | 2.793 / .647 | 2.956 / .622 |
| naive last season | 3.329 / .554 | 3.111 / .664 | 3.583 / .458 | 3.585 / .465 |

The C2 share inputs are last-season shares of the team's RB carries, RB targets and goal-line carries, RB investment (the
A13 form on an RB cap scale), a rd 1-3 back added, rushing-QB share, new play-caller, and team RB volume last season.

- **The A12 question.** Forcing the shares to add up exactly hurts, as it did for QBs. Full add-up: holdout pool MAE 2.901,
  ADP-150 holdout rho .578.
  - Forcing an exact sum pushes the games model's errors into per-game volume. Crowded charts get deflated and thin ones
    inflated.
  - The team total it is forced to is itself weak (r .28).
  - Moving half-way to the team total is about the weight a team r of ~.3 deserves, and it is the version that helps.
- **Share inputs need the rescale.** On their own they do nothing (2.869 / .628). With the half-way rescale they give the
  dev gain.
- **Goal-line TD rate: dropped.** Goal-line volume matters (step 1), but goal-line history does not predict it better than the
  plain shrunk TD rate already does. The shrink picked k 320-640, i.e. mostly league average.

**Judging the kept candidate (C3, half-way).**

| check | v5 | C3 | ADP | naive |
|---|---|---|---|---|
| pool dev per-game MAE / rho | 2.851 / .630 | 2.825 / .643 | 2.803 / .650 | 3.329 / .554 |
| pool dev season totals MAE / rho | 44.7 / .620 | 43.9 / .637 | 49.4 / .547 | 48.8 / .554 |
| pool dev top 12 / 24 / 36 hits | .448 / .615 / .663 | .438 / .615 / .681 | .615 / .641 / .774 | .406 / .552 / .639 |
| pool holdout per-game MAE / rho | 2.808 / .719 | 2.814 / .725 | 2.913 / .630 | 3.111 / .664 |
| pool holdout top 12 / 24 / 36 | .556 / .722 / .750 | **.444** / .708 / .759 | .611 / .694 / .759 | .500 / .611 / .722 |
| ADP-150 dev per-game MAE / rho | 3.030 / .533 | 3.014 / .550 | 2.793 / .647 | 3.583 / .458 |
| ADP-150 holdout per-game MAE / rho | 3.104 / .619 | **3.141 / .611** | 2.956 / .622 | 3.585 / .465 |

By tier, pool dev (per-game MAE, then rho):

| tier | per-game MAE v5 -> C3 | rho v5 -> C3 | holdout |
|---|---|---|---|
| lead backs | 3.212 -> 3.199 | .570 -> .576 | rho .535 -> .472 |
| committee | 2.687 -> 2.652 | .598 -> .624 | MAE 2.466 -> 2.609 |
| backups | 2.598 -> 2.541 | .302 -> .321 | flat |
| rookies | 2.998 -> 3.026 | .469 -> .484 | MAE 3.024 -> 2.948 |

- **Seasons that beat v5 on pool MAE:** dev 5/8, holdout 2/3.
- **Verdict: KEPT on the stated bar, but weak.** On 2015-22 it gives +.013 rho with lower error (pool) and +.017 on ADP-150.
  The 2023-25 holdout does not confirm it: the pool is flat to slightly better, ADP-150 is slightly worse, and the top-12
  hits drop. It also came out best of six candidates on dev, so part of the dev gain may be selection. v5 is kept as the
  fallback.

**Range by backfield tier: KEPT (does not change the averages).**
- Per-game p10-p90 coverage with one pooled RB spread: lead backs 88-90%, committee 87-90%, backups 79-80%, rookies 74-75%.
- With a spread by tier: 79%, 81%, 83-86% and 79-80%, all near the 80% target.
- By tier, lead backs and committees get about 0.8x the pooled width, and backups and rookies 1.1x. A committee back's per-game
  spread is not wider than a lead back's. What is wider is his season-total range, which comes through games and volume.
- The A9 take-over base rates live in this backup/rookie spread. They still do not help as an average.

**Other positions.**
- WR/TE/QB projections are unchanged: non-RB totals are identical in v6, and overall ranks move by at most 6 in the top 150
  as RBs shift.
- RB targets are rescaled toward the team model's RB target total. The WR/TE targets come from their own ridge and were not
  touched, so a team's projected targets are not forced to sum to its pass attempts. That would be a separate test.

**v6 lists, 2026 check** (`output/rb_movers_a14.log` has the RB top 36 before/after, all 36 movers and the team backfield
table):
- **Up:** Chuba Hubbard 29 -> 19 (2026 so far RB5), Kyren Williams 17 -> 9 (RB11), Chase Brown 20 -> 12 (RB18), Henry
  14 -> 10 (RB8), Josh Jacobs 32 -> 22 (3 g).
- **Down:** Jeremiyah Love 9 -> 17 (RB44), Etienne 18 -> 25 (RB61), Hampton 11 -> 16 (RB27), Judkins 10 -> 14 (RB21),
  Saquon 6 -> 8 (RB38), Kenneth Walker 15 -> 18 (RB3, the wrong way).
- **Why.** Mostly the half-way team rescale. Crowded charts get everyone scaled down: ARI's listed backs summed to 24.2
  carries per team game vs a team model of 20.5, NO 25.3 vs 20.4. Thin charts get scaled up: GB 17.4 vs 22.4, CAR 18.0 vs 22.2.
  This is the same mechanism that held up on history, not a 2026 tweak.
- **The backs that looked wrong in the first list:**
  - Saquon 5 -> 8 (actual RB38).
  - Love 9 -> 17 (actual RB44), moved toward the truth by the ARI crowd rescale.
  - Achane 8 -> 6 (3 games played, injured).
  - Corum 43 -> 37 (actual RB17, ADP 31), the right way.
  - Allgeier 53 -> 62 (actual RB26) and Keaton Mitchell 73 -> 80 (actual RB48), the wrong way: crowded ARI / LAC charts.
  - Jordan Mason 55 -> 51 (actual RB57).
- **2026 so far (examples, not proof):** on the top 48 RBs, rank correlation with the 2026 RB rank goes .523 -> .593. Per game
  for backs with 6+ games, .591 -> .668, vs ADP .670 on the same rows.
- **Disagreement tally:** ADP 14, model 12, too few games 4 (v5: ADP 15, model 12, too few games 3).

**2027 early look.**
- **Movers:** Chase Brown 17 -> 10, Corum 46 -> 38, Montgomery 32 -> 26, Henry 18 -> 14, Saquon 14 -> 21, Breece Hall 8 -> 12,
  Hubbard 13 -> 18, Judkins 12 -> 16.
- **Stability:** the top 36 is the same 36 backs in a different order.
- **Not in it yet:** 2027 rookies, free agency, 2027 coaching changes (the new play-caller input is blank) and the rest of
  2026.

**Missing data that would help:**
- Historical August depth charts (still not approved): the week-1 chart is the only role signal for new arrivals.
- Play-caller history: OC is only a proxy, and coaches.json starts in 2018, so dev rows before 2019 have no play-caller input.
- RB routes and snaps from the on-disk pbp_participation files (2016+): this needs no pull, so it is the next thing to test as
  a share input.

**Next.**
1. Shares are still too flat by chart spot (spot 1 under, spot 3 over). Test a share model that sharpens spot 1 directly.
2. RB route share from the participation files.
3. Team target totals across RB + WR + TE.

**A14 decision (Jack, 2026-11-21: "Yes, ranges only").**
- The RB volume change is dropped from the working version and is to be re-tested after the full 2026 season. It stays in
  the code behind `RB_VOLUME_V6 = False` in `output_rankings.py`.
- The tier-based RB ranges are kept (`RB_TIER_RANGES = True`).
- The lists are **v7 = v5 averages for every position + the A14 RB ranges by tier.** v6 is kept as `output/*_v6.*`, and its
  backfield table as `output/rb_movers_a14_v6_DROPPED.log`. `output/rb_movers_a14.log` is now rebuilt from v7 (v5 RB volumes).

**v7 checks** (`output/check_v7.log`):
- Every row's PPG, games and total matches v5 exactly (0 differing rows, all positions).
- Overall ranks differ only inside the tie at VOR 0 (ranks 97-100: the replacement-level QB/RB/WR/TE all have VOR exactly 0).
  That order was arbitrary and now breaks by total, then name.
- Range columns differ: RBs by design (tier spread), non-RBs by Monte Carlo re-draw (median 0.4-0.9 pts).
  - The ranges in v1-v6 were not reproducible run to run: one shared random stream, drawn in a row order that changes
    between runs. WR/TE ranges moved by up to 10-13 pts from v3 to v4 to v5 with no model change.
  - v7 fixes this with one seeded stream per player and sorted ratio arrays. Two v7 runs now match exactly (0 differing range
    or rank cells).
  - The A9 RB take-over info column (p_take) still moves by up to .03 between runs.

**RB p10-p90 coverage by tier on v5 numbers** (`rb_ranges_a14.log`; target 80%):

| tier | per game, pooled | per game, by tier | totals, pooled | totals, by tier |
|---|---|---|---|---|
| lead back, dev / holdout | 90 / 91% | 77 / 81% | 87 / 86% | 85 / 85% |
| committee, dev / holdout | 91 / 89% | 83 / 78% | 89 / 89% | 83 / 76% |
| backup, dev / holdout | 79 / 80% | 87 / 83% | 81 / 78% | 84 / 83% |
| rookie, dev / holdout | 78 / 66% | 81 / 72% | 82 / 70% | 83 / 79% |

- Totals coverage here uses the games model before the A9 isotonic fix, so it is approximate.
- Rookie widths fitted on v5 numbers come out at x1.07.

### A15. Provisional 2027 rookie class from JM, plus a re-runnable 2027 refresh (2026-11-21, Jack "Yes, add rookies" / "have it update based on new information"): STOPPED at step 1. The JM data is not in usable in-house form. Jack's call needed

Nothing was built or changed: no list, no script, and v7 stays the working version. Everything read was on disk and
read-only: the site's data files, scripts and app.js, its git log, and the Task Scheduler listing.

**What exists.**
- `data/jm_scores.json` (exported 2026-11-17 by `scripts/pull_jm_scores.py`) has a JM score for 137 players with expected
  draft year 2027: 27 QB, 35 RB, 20 TE, 55 WR.
- `combine_data.js` (2026-11-16) gives school and `eligYr`, so class membership = eligYr 2027.
- There is no senior / underclass / declared flag. It would have to be derived from years in college.
- The college stats (`college_stats_devy.js`, 2026-11-16) are mid-season: the 2026 college season, bowls and the January
  declaration deadline are all still ahead.

**Why it is not usable as an in-house, pre-draft score.**
1. **About a quarter of JM is draft capital.** The JM weights (`jm_weights.js`, v4 and later) put roughly 24-30% on "dc".
   For undrafted classes the site fills dc from `data/draft_proj.js`.
   - That file is generated by `scripts/pull_draft_boards.py` from the NFL Mock Draft Database: a consensus mock pick, then a
     consensus big-board rank.
   - app.js (line ~54376) says it directly: draft age is age at the PROJECTED draft, and DC is the consensus draftProj.
   - So every 2027 JM score already contains an outside consensus mock draft. That is a market input of the same kind as
     ADP. The projected 40 times in combine_data are also an outside projection ("NFL Draft Buzz projection").
2. **Past classes' JM includes their ACTUAL draft pick.** A "pre-draft JM" for past classes therefore cannot be rebuilt from
   what is on disk.
   - jm_scores.json has no git history.
   - draft_proj.js history starts 2026-09-30.
   - So the requested test (pre-draft JM vs post-draft prior vs flat average) would grade a score that already knows the
     pick, and the "price of going before the draft" would come out far too small.
3. **A JM without draft capital is not on disk.** JM is computed in the browser (app.js); `pull_jm_scores.py` loads the
   live site in headless Chrome. Re-creating it without dc in preseason2027 would mean re-implementing Jack's model, which
   is the improvised score the brief rules out.

**Options for Jack.**
- **A. Allow the consensus mock as an input.** It is already on disk and already inside JM. Then the 2027 JM can be used
  as is, and the honest test is on the 2026 class only: its JM from the Sept-Nov 2026 draft_proj era is not on disk either,
  so even that test would need a pre-draft snapshot that doesn't exist. The test would therefore be weak. Same family as the
  parked ADP decision.
- **B. A no-draft-capital JM (prospect profile only).** This needs the site's JM engine to export the score with the dc
  term off (or its component scores) for past and current classes. That is a change to the site, and it is the cleanest
  in-house pre-draft score that could also be backtested.
- **C. Wait for the draft.** After late April the real post-draft rookie prior (pick plus landing spot), which the model
  already has, replaces any placeholder. The 2027 early list stays rookie-free until then.

**Refresh command.** Not built: the brief said to build it after the rookie class works. What was found for the
stale-input report:

| input | last updated | refreshed by |
|---|---|---|
| play_by_play_2026, sim_depth.js | 2026-11-21 | "MFF Sim Proj Export" scheduled task, daily / weekly (refresh_data.py) |
| college stats, combine_data, draft_proj | 2026-11-16 | "MFF Devy Weekly Refresh", weekly; its mock CSVs are pulled by hand in Chrome and dropped after 10 days |
| contracts | 2026-11-21 | "MFF Player Contracts", daily. Its target vs pbp_cache/historical_contracts.parquet (2026-07-30) still needs checking |
| **jm_scores.json** | 2026-11-17 | **nothing scheduled** (pull_jm_scores.py by hand, headless Chrome on the live site) |
| **pbp_cache draft_picks.parquet** | 2026-07-30 | **no scheduled refresh found** |
| **coaches.json** | 2026-09-15 | **no scheduled refresh found** |
| **depth_charts_2025.parquet** | 2026-09-16 | **no scheduled refresh found** |
| **win totals** | 2026 frozen preseason lines | **no 2027 source on disk yet** |

The ones without a refresh are the gaps that would stop a 2027 refresh from really updating.

**A15 resumed (Jack 2026-11-23, "Yes, use JM": option A).** The JM scores are used as they are, for undrafted 2027 rookies
only. Veterans stay in-house with no ADP.

The 2026-10-09 memory "2027 read NEUTRAL until 2027-01-12" is about the dynasty rookie-PICK class multiplier (W_CLASS in
build_dynasty_sim.py). It is not about placing 2027 prospects, so there is no conflict. Its caveat carries over: the
mid-season JM runs low for slots 3-16.

**Honest test** (`a15_rookies.py backtest`, log `a15_backtest.log`). There is no pre-draft test: no pre-draft JM or
draft_proj snapshot of any past class is on disk. The stand-in below uses past JM, which includes the REAL pick, so read it
as an UPPER BOUND on pre-draft placement.

Method: K=20 nearest past prospects by JM at the same position, classes 2015-25, leave-one-class-out.

| pos | per-game MAE / rank corr: (a) JM, upper bound | (b) post-draft prior | (c) flat average |
|---|---|---|---|
| QB | 3.85 / .25 | 3.59 / .50 | 3.65 |
| RB | 2.86 / .44 | 2.98 / .37 | 3.22 |
| WR | 2.50 / .52 | 2.48 / .56 | 2.82 |
| TE | 1.77 / .48 | 1.59 / .48 | 1.77 |

| pos | top-6 / top-12 rookie hits: (a) | (b) |
|---|---|---|
| QB | .61 / .78 | .76 / .78 |
| RB | .56 / .64 | .65 / .69 |
| WR | .57 / .64 | .59 / .66 |
| TE | .57 / .74 | .61 / .83 |

- Even with the real pick inside JM, the method trails the post-draft prior for QBs and TEs and ties it for WRs. It beats
  the prior for RBs on per-game, but RB rank hits still trail.
- Pre-draft it will be worse by an amount we cannot measure.

**Ranges.** Season-total p10-p90 come from the 40 nearest prospects (twice the projection window); non-players count as 0.
Coverage on past classes is 83-87% by position (85-89% on 2020-25), deliberately above 80% because pre-draft JM is noisier
than this upper bound. Median widths: QB 112, RB 82, WR 64, TE 48 pts.

**v8 list** (`output/2027_inhouse_early.csv` / `.md`).
- 137 PROVISIONAL rookies: 27 QB, 35 RB, 55 WR, 20 TE.
- Columns: provisional = 1, jm, school, class_status, implied_round, p_drafted; team is blank.
- class_status comes from years in college: 4+ = senior, 3 with JM 60+ = likely to declare, else uncertain. A 4th-year
  redshirt junior counts as "senior" but can still return to school.
- Veterans' ppg, games, totals and ranges are identical to v7. Their ranks move only because rookies slot above them.
- Kept beside it: v7 and `2027_inhouse_early_norookies.csv`.
- Rookies placed: 4 in the overall top 150, 10 in the top 200.
  - Jeremiah Smith: WR31, #69.
  - Jadan Baugh: RB35, #104.
  - Trey'Dez Green: TE26, #138.
  - KJ Duff and Nick Marsh: WR56-57.
  - Arch Manning: QB41.

**Refresh command: `refresh_2027.py`.**
- It fetches nothing and re-tunes nothing.
- It checks inputs and aborts (keeping the last good list) if one is missing or malformed.
- It detects the stage: latest completed 2026 week (pbp game counts vs the schedule), post-draft, win totals, August charts.
- It runs output_rankings.py (`PRE27_LAST_WK`), then sf_view_a10.py, then a15_rookies.py insert, restoring the outputs if a
  step fails.
- Each run writes:
  - sanity checks
  - a dated snapshot in `output/snapshots/`
  - a change log in `output/changelog/` with the driver of each move
  - `output/2027_refresh_status.md`, plus a header on the 2027 md
- Shown working:
  - As of week 9, then week 10: 327 change-log lines (e.g. Anthony Gould WR205 -> WR177, "new 2026 game data").
  - Two reruns with no new data: "no changes: the list matches the previous snapshot exactly".
  - Outputs are rounded to 4 decimals to remove 1e-12 float noise.
- **Gaps:** no scheduled refresh for jm_scores.json (manual: `python scripts\pull_jm_scores.py` from the site repo),
  schedules_games.csv, historical_contracts.parquet, draft_picks.parquet, coaches.json, depth_charts parquet, and win
  totals.
- **Finding:** schedules_games.csv (2026-10-20) has 2026 final scores only through week 6, so the work data has no 2026
  team-game rows for weeks 7+. Re-pulling it, or deriving scores from pbp, is a proposal.
- **Post-draft replacement of the placeholders is not wired yet:** the stage is detected and flagged.
- **Recommended cadence:** weekly on Tuesdays through week 18, then after each milestone. Nothing is scheduled.
