# Sim Lab — private projection + Monte Carlo engine

**PRIVATE research tool. Lives outside the MFF repo and is never deployed.**
Goal: build our own weekly projections, sim every week ~100x (or more), track
accuracy vs actuals AND vs sportsbook lines all season, and only consider
shipping anything to the site once the beat-rate proves out.

## Run it

```bash
python refresh_data.py    # pull the latest data out of the repo (run after the daily pulls)
```

Then open `index.html` over http (Sleeper fetches work fine from file:// too,
but a local server is safest):

```bash
python -m http.server 8798
```

…or reuse the `jsmodel-site` launch config which serves the whole
`E:\MyFantasyFootball\` parent on :8798 → `http://localhost:8798/sim_lab/`.

## Online (unlisted)

Live at **https://jb-simlab-2026.web.app** — Firebase Hosting site
`jb-simlab-2026` in the `jackb933-website` project (separate from the MFF
GitHub Pages site; noindex, linked nowhere). Redeploy after any change:

```bash
cd E:\MyFantasyFootball
python sim_lab/refresh_data.py
npx firebase-tools deploy --only hosting:simlab --project jackb933-website
```

NOTE: localStorage (snapshots, accuracy history) is per-device/per-origin —
the hosted site and localhost don't share it. Do the weekly LOCK/SCORE ritual
on one of them, or move history with EXPORT ALL.

## Data sources (all already auto-refreshed by existing pipelines)

| File | Source | What we use |
|---|---|---|
| `data/mike_clay_projections.js` | repo (daily Clay pull) | season stat components + full-PPR pts (the baseline mean) |
| `data/player_weekly_sigma.js` | repo (`build_player_sigma.py`) | per-player 3-yr weighted weekly σ%, trend-corrected |
| `data/betting_lines_2026.js` | repo (auto betting pull) | DK game totals/spreads (272 games) → schedule, byes, implied totals; UD/PP weekly prop lines for the accuracy grading |
| `data/sleeper_players.js` | sleeper-extension `players.json` | Sleeper IDs (roster matching) + Underdog ADP (demo league) |
| `data/sleeper_meta.js` | Sleeper `/players/nfl` (pulled by refresh_data.py) | `years_exp` — TRUE rookie detection (exp 0); a 2nd-year player with a thin sample is not a rookie |

## Model

- **Weekly mean** = Clay season pts (rescored to league scoring via stat
  components — rec value, pass TD value, TE premium all exact) / 17 ×
  Vegas multiplier (team implied total vs league avg, elasticity 0.5, clamped ±35%).
- **DST** is synthesized from opponent implied total (`15.5 − 0.42·oppImp`).
- **Opponent defense adjustment** (Clay unit grades, `clay_team_grades_2026.js`):
  position-specific — QB/WR keyed off CB/S/ED, RB off DI/LB/ED, TE off S/LB/CB.
  ±2% per grade point vs league average, capped ±8%. Deliberately small: Vegas
  lines already price overall defense; this is the positional residual (e.g.
  LAR's coverage-led defense docks WRs ~3% but RBs only ~0.5%).
  NOTE: `team_def_data.js` in the repo was evaluated and rejected — orphaned,
  no generator or consumer, undocumented columns.
- **Variance**: gamma distribution (non-negative, right-skewed) with each
  player's own `sigma_pct`; position defaults for rookies/no-history players.
- **Correlation (QB-hub, backtested 2019-25 — backtest_correlations.py)**:
  the old uniform team-environment factor was wrong in shape (QB↔receivers
  2x too weak, non-QB teammate pairs far too positive, RB-vs-opp-RB sign
  wrong). Now: per-team passing environment **V** (correlated across each
  game, gV=.50), **per-receiver draws** that flow into the QB via
  receiving-share weights (QB points ARE receiver points → links QB to each
  receiver at r ~.27-.36 without linking receivers to each other),
  antisymmetric **rush-script** game factor (RB-vs-opp-RB negative), DST
  loads negatively on the opponent's V. Loadings are fractions of each
  player's total weekly sd, so marginal distributions are EXACTLY unchanged.
  Fit vs empirical pair correlations: mean |error| same-team .128→.042,
  opponent .042→.020 (browser-verified live: QB-WR1 .32, QB-oppQB .19,
  WR1-WR2 .06, RB1-oppRB1 -.06). League sims share the factors league-wide,
  so H2H matchups and same-game stacks price correctly.
- **QB starter windows**: Clay's `gm` is 17 for nearly every QB — the real
  starter split lives in his POINT totals (committee rooms have two QBs ≥40
  pts; pure backups sit at 7–11). Detected rooms get sequenced: the veteran
  opens Week 1 (Cousins → Mendoza, Tua → Penix), the other takes over when the
  vet's estimated games (closed-form from the point split, backup at 85% of
  the leader's per-start rate) run out. Inside his window a QB projects at his
  true per-start rate instead of a diluted season/17; outside it he projects
  DNP. Override any room as news breaks in `overrides.js`
  (`QB_ROOM_OVERRIDES = { LV: [['Kirk Cousins', 4], ['Fernando Mendoza', 13]] }`).
- **Rookie ramps**: only rookies BURIED on the depth chart (age ≤ 24, no NFL
  sample, <60% of the team's position leader's points) start slow — games 1-4
  at 55/70/85/95%, then a renormalized tail so season totals are preserved
  exactly. Projected lead rookies (Love/Jeanty types) are full-go from Week 1.
- **Youth volatility**: rookies get position-default σ ×1.20; thin histories
  (<30 games) widen up to +25%; age ≤23 ×1.10. Gamma is floored at zero, so
  the extra σ mostly fattens the boom tail — the breakout case.
- **Injury start-of-season windows**: any player carrying a current injury/
  suspension designation whom Clay ALSO projects for <17 games misses the
  START of the season — window = the last `gm` games at his true per-game
  rate (Charbonnet PUP+gm11 → games 7-17, Kittle PUP+gm15 → 3-17, Nabers
  Questionable+gm15 → 3-17). Both signals must agree: camp PUP with gm 17 =
  no window; healthy gm<17 hedges (backup QB mop-up) stay spread. In-season
  PUP exclusion defers to these windows. Correct per news in `overrides.js`:
  `INJURY_WINDOW_OVERRIDES['Malik Nabers'] = 0` (healthy) or `= 4` (out first 4).
- **In-season snap usage trend** (self-activates once the season starts):
  `refresh_data.py` trims the site's snap-count pull to 2026-only
  (`sim_snaps.js`, empty preseason). For RB/WR/TE, weighted recent snap share
  (last 3 recorded games BEFORE the projected week, 0.5/0.3/0.2) vs
  season-to-date average → ±0.8%/snap-pt, clamped [0.75, 1.30]. Catches
  committee shifts and rookie takeovers between Clay updates. Stale data
  (last game >3 weeks back = injured) → no adjustment, the injury layer owns
  absences. Never reads snaps from the projected week or later (no hindsight).
  IN-SEASON: re-run `pull_snap_counts.py` in the repo, then `refresh_data.py`,
  then redeploy.

## JS Weekly — the in-season model

**2026-09-14 — complete-league FPA.** The opponent layer's fantasy points
allowed used to be summed from the site's board-only game logs
(weekly_stats_active), so any defense that faced an UNTRACKED player read
as a shutout (W1: PIT 0.0 QB allowed — Cooper Rush isn't on the board; NE
0.5 — Drew Lock isn't; league-wide 4-10% of position points were missing,
concentrated on a handful of defenses). `refresh_data.py` now prefers the
repo's `data/fpa_2026.js` (EVERY Sleeper QB/RB/WR/TE in FINAL games,
half-PPR, per defense per week, written by scripts/pull_postgame_stats.py
after each game window) and falls back to the board-only sum when the file
is missing. The site's SOS blend (`_mtObservedFpa`) reads the same file.
**Slow weekly tuner (Jack 2026-09-14: "slowly implement each week") —
`tune_weekly.py`**, run by weekly_scorecard.py after each Tuesday scorecard.
Re-fits two knobs on EVERY scored week so far and shrinks toward the
preseason prior with a 4-week-equivalent weight (one week moves a knob
~1/5 of the way; five agreeing weeks move it most of the way; a wild week
barely registers): per-position market-anchor weight `propW[pos]` (prior
PROP_W .70; evidence = MAE-minimising w with the market reconstructed from
the stored propMean/jsMean) and `sigmaMult[pos]` on SIGMA_CAL from p10-p90
coverage (target 80%), and — added the same day at Jack's ask —
`tdMult[pos][stat]` (TD-rate multipliers on the Clay prior's ptd/rtd/rctd
components, evidence = Σ actual TDs / Σ raw projected TDs with a prior worth
4 weeks of projected TDs, clamp .70-1.40, applied in buildPlayers with
ptsPPR kept consistent) and `kLevel` (kicker prior level, Σ actual / Σ raw
clean mean) + `sigmaMult.K`, and `dstShift` (additive DST level in
dstWeeklyMean, evidence = mean(actual − raw model), shrunk to 0, clamp ±3)
+ `sigmaMult.DST`, and `belowW` (a SEPARATE market weight used only when
the clean model sits >= 3 pts under a market-implied mean of >= 8 —
engine BELOW_GAP / BELOW_STARTER_MIN in propAnchorMean; pooled across
positions, evidence = MAE-minimising w on those rows, shrunk to PROP_W;
per-player overrides still win). Every lock row stores `tun` (incl. `wa`
= the market weight actually applied, since belowW can differ from
propW[pos]) = the values live
at lock (export_site_proj.js), and the tuner divides them back out so the
loop measures against the RAW prior and converges instead of compounding.
Output `data/sim_tuning.js` → `window.SIM_TUNING`,
read by engine.js `propWeight()` (after per-player / console overrides,
before PROP_W) and buildPlayers (after SIGMA_CAL); loaded by index.html
AND export_site_proj.js. Comps / jsMean / clayMean stay CLEAN. Kill: delete
the file or `window.SIM_TUNING = null`. Helpers' sim packs never see it
(priors). W1 step: propW QB .73 / RB .59 / WR .57 / TE .63; sigma ×1.00 /
.98 / 1.00 / 1.02 / K .99; TD QB ptd 1.03 rtd 1.12, RB rtd 1.09 rctd 1.10,
WR rctd 1.01, TE rctd 1.14; kLevel 1.027. Backup engine.js.bak_pre_tuning_20260914.

`vs_books_week.py --week N` (also in the Tuesday log) grades the CLEAN comps
vs the lock's pregame lines: stat-prop calls (raw AND median-adjusted —
comps are means, lines are medians, so the raw call leans OVER ~63/37 on
yardage), edge buckets, anytime-TD Brier + direction split (beware the
base-rate trap: the model sits under the books on most players and 77%
don't score, so "model side right" is inflated), JS-vs-market fantasy mean
by disagreement size, coin-flip band + per-player clustering. Junk 0.5-yd
novelty lines are dropped (MIN_LINE). W1 2026: stat props 51.4% (coin band
46-54), no edge-size signal; TD Brier books .154 < model .160; fantasy
mean MAE model 4.93 < market 5.06 (53% closer, p .35), and when the model
sat 3+ pts from the market the actual landed on the model's side 15/19.
`weekly_scorecard.py` (Tuesday chain, 8:30) archives the consensus file and
writes `scorecards/wN.log` = score_week + diagnose_week (bias by position,
K/DST grade, PROP_W sweep, JS×consensus blend, tier/implied buckets, rank
accuracy, stat-component bias, band-by-tier). W1 2026 read: JS 5.61 <
shipped 5.69 < consensus 5.70; PROP_W sweep best .30 overall but QB wants
.70-.90 and RB/WR/TE 0-.30 (n=163, one week — NOT retuned; revisit at 4
weeks per the prop-anchor plan, and test a per-position PROP_W); TD
components under-projected everywhere (rtd +45-60%, TE rctd +68%); K
Spearman −0.08 (no rank skill W1), DST +0.33 with bands 93% inside.
`score_week.py --week N` is the headless twin of the TRACKING SCORE ritual
(copy the week's weekly_projections.json to data/weekly_consensus_wN.json
before the 9am job flips it). W1 2026 (170 played, mean>=5): JS Weekly MAE
5.61 < shipped 5.69 < consensus 5.70; p10-p90 coverage 80.6%.


Second projection engine racing Clay all season. Preseason it EQUALS Clay by
design — the 2021-25 backtest (`backtest_hybrid.py`, using clay_history.json
+ weekly_stats_active actuals) showed pure Clay (MAE 2.267) beats every
history blend (hybrid 2.335, pure history 2.671, monotonic weight sweep), so
no preseason second-guessing. Once 2026 games exist it becomes its own model
from LIVE factors:

- **Base**: Bayesian shrink of Clay's per-game rate toward actual 2026 PPG —
  `(5·clayPg + g·actualPpg) / (5 + g)`. Clay's prior is worth ~5 games of
  evidence; by midseason the season outweighs the summer guide.
- **Opponent**: actual fantasy points ALLOWED per game by position (clamped
  [0.8, 1.25] vs league avg), blended over the Clay unit grades by
  `min(1, defenseGames/8)` — small early samples don't get full trust.
- **Shared live layers**: Vegas implied totals, snap-count trend, starter/
  injury windows, byes.
- Player efficiency + target/carry usage are embedded in realized PPG, the
  per-game stat mix (used for exact league rescoring), and the snap trend;
  an explicit usage-share model (tgt%/carry% × team volume) is the v4 step.

Data: `refresh_data.py` extracts the 2026 season from weekly_stats_active.js
into `data/sim_2026.js` (empty preseason). IN-SEASON: run the repo's
fetch_weekly_stats.py, then refresh_data.py, then deploy — worth adding to
the Tuesday routine. Every lock stores both means; every SCORE grades both
(tracking shows MAE JS + a JS-vs-Clay head-to-head record). If JS sustains a
better MAE + >50% head-to-head by ~Week 6, it earns the baseline job. Books
remain grading-only for the CLEAN models (Clay stack + JS Weekly); the
SHIPPED weekly mean may anchor to prop lines — see Prop anchor below.

## Prop anchor (market-anchored weekly mean) — 2026-08-31

Third weekly mean `propMean` (full spec: PROP_ANCHOR_SPEC.md): where weekly
prop lines exist (`BETTING_2026.weeklyProps` — UD/PP stat medians + DK
anytime-TD odds, auto-pulled pregame in-season), the shipped mean blends
**70% market / 30% model** (base = JS Weekly in-season, Clay preseason).
Mechanics: consensus line = median across books; lines are medians, so
they're converted to mean scale with the player's closed-form gamma
median/mean ratio (from his own sampled shape — no sim needed); pass TDs
use the posted line; rush+rec TDs come from devigged anytime-TD odds →
Poisson mean, split rush/rec by the model's own ratio; uncovered stats stay
model. Coverage gate: posted lines must cover ≥60% of the player's non-TD
model points or no anchor; K/DST never anchored. Sigma, correlations and
the season shock are untouched — the market moves the center, not the width.

Honest-scoreboard rules: `comps` stay CLEAN everywhere (vsBooks grading and
the LINES view are non-circular — the LINES view now medianizes with the
closed-form ratio instead of the sim run's p50/mean). Locks store
clayMean/jsMean/propMean; SCORE grades all three (report field `propModel`)
plus head-to-heads PROP-vs-Clay and PROP-vs-JS in the TRACKING table.
PROP_W is retroactively tunable: every lock has clean comps + lines +
actuals, so sweep w over the accumulated history after ~4 scored weeks.
Kill switch `window.SIM_PROP_ANCHOR = false`; per-player weight/disable in
`PROP_ANCHOR_OVERRIDES` (overrides.js). Preseason (weeklyProps empty) the
layer is a provable no-op — fixed-seed sims are byte-identical.

**Market rate track (Phase 4, 2026-08-31):** weeks with NO direct lines —
future weeks in the season/league sims, un-lined players — fall back to the
market's standing per-game rate: every observed week's prop-implied mean ÷
that week's multipliers = a matchup-free neutral rate; EWMA'd (half-life 3
wks) and blended into the JS base rate at `PROP_W × confidence`
(confidence 1.0 at 2 effective observations — one slate = half weight, so
preseason W1 props already market-inform 3k future player-weeks at mw .35).
Direct lines always take precedence (`propSrc 'line'` vs `'rate'`, stored
in locks for offline splits). Props are conditional on playing, so this
anchors RATE only — the wreck mixture, injury windows and byes keep owning
games, which is why this beats season futures at season-long (futures
entangle rate × games and double-count the availability layers). Kill
switch `window.SIM_MKT_RATE = false`.

## Season sim backtest (backtest_sim_calibration.py)

Backtests the DISTRIBUTIONS (backtest_hybrid.py already did the means): for
each season 2019-25, rebuilds the pool from that year's preseason Clay guide
(clay_history.json), reconstructs sigma exactly as the engine does, runs the
engine's sampling math and grades vs actuals (weekly_stats_active + retired
splits — no survivor bias): weekly band coverage, season-total band coverage,
and top-3/12/24 finish-odds Brier + reliability buckets.

Findings (pooled 2019-25, ~1,640 player-seasons): engine-as-shipped weekly
p10-p90 coverage 69% (target 80) — a touch narrow, mostly mean-drift the
in-season layers absorb; but season-total coverage was 31% with 44% of real
seasons BELOW p10, and top-12 reliability read 97%-predicted → 69%-realized.
Independent weekly draws shrink season CV ~1/√17; real seasons carry
persistent shocks. Fix v1: per-player per-season gamma shock (mean 1, cv .45)
scaling every week's mean+sd, plus Bernoulli games-played from Clay's own gm
at the true per-game rate → 74% coverage, best Brier. Residual: ASYMMETRY
(below-p10 19% vs above-p90 7% — gamma is up-skewed, reality is
downside-fat).

Fix v2 (SHIPPED 2026-07-30, replaces the gamma): **wrecked-season mixture** —
with prob 20% the season multiplier is U(0.05, 0.50) (major injury / role
collapse), else gamma cv 0.30 scaled so E[shock]=1 exactly. Swept q/tau/wreck
bounds: q=.20 + deep wrecks won — **82.5% p10-p90 coverage, below-p10 10.3%
(on target), above-p90 7.2%, Brier12 .1154 (best)**. `drawSeasonShock()` in
engine.js, shared by simSeason AND simLeague (QB/RB/WR/TE).

Fix v3 (SHIPPED same day, on top of v2): **projection-scaled upside trim** —
shock draws above 1 keep only u of their excess, u = clamp(1.05 −
halfPts/400, 0.40, 1.0): a 350-pt stud keeps 40% of shock upside, a 140-pt
flyer ~70%, sub-100 keeps ~all. Renormalized exactly (SHOCK_EPLUS=.19414 =
E[(shock−1)+] of the untrimmed mixture). Swept global u .40-.75 + two proj
scales: global trims trade the tails against each other via renormalization;
the proj-scale won — above-p90 7.3→8.0%, below-p10 10.5%, cov 81.5%, and the
BEST top-12 AND top-24 Briers of every config tested all session
(.1145/.1480). Browser-verified: Allen p90/mean 1.44 vs mid-tier WR 1.56 —
elite ceilings compressed, flyer ceilings kept. Remaining above-p90 gap
(8.0 vs 10) is the floor of what mean-preserving trims can reach; further
would need to touch the weekly gamma itself — not worth it at current Brier.

## Weekly sigma backtest (backtest_weekly_sigma.py)

Audits the weekly-width layer, decomposed three ways (2019-25, 1,327
player-seasons with ≥8 games):

- **Prediction**: the 3-yr player-specific sigma VALIDATED — corr +.52 with
  realized weekly CV vs +.41 for position defaults. PLAYER_WEEKLY_SIGMA
  earns its keep. (The low-sample widenings add slight over-prediction bias
  on history players; absorbed by the position calibration below.)
- **Width** (realized-mean basis, so mean-drift — owned by the season shock —
  doesn't contaminate): QB ran ~10% WIDE (the QB-hub env var covers it),
  RB/WR ~5% narrow, TE on. Plus:
- **Shape**: even with self-consistent (cheating) parameters the gamma is
  mildly thin-tailed BOTH sides (77.3% vs 80) — real weeks are more
  kurtotic; sigma must overcompensate slightly.

SHIPPED: `SIGMA_CAL = {QB 1.00, RB 1.15, WR 1.15, TE 1.10}` applied to
sigmaPct in buildPlayers (before the clamp; mirrored in the python harness's
sigma_entering). Post-cal every position reads 79.8-81.4% coverage at scale
1.0. Season-level calibration re-verified after: shipped shock config stays
on target (cov 82.0, below-p10 10.6, Brier12 .1145).

**K + DST** (backtest_k_dst_sigma.py): no weekly actuals in our fantasy data,
so both were RECONSTRUCTED from cached pbp 2019-25 (K: FG by distance + XP,
223 kicker-seasons; DST: sacks/INT/FR/TDs/safeties/blocks + Sleeper PA
buckets, 224 team-seasons). Both defaults were way narrow: K realized CV
.572 vs engine .417 → `SIGMA_CAL.K = 1.28` (on top of the 1.10 no-history
mult all kickers get). DST realized CV .93 vs .72 AND **8.3% of real DST
weeks are negative**, which a floor-at-zero gamma cannot produce — DST now
samples a SHIFTED gamma (draw around mean+4, subtract 4; `DST_SHIFT`) with
`DST_SIGMA_CAL = 1.34`: shifted beat plain gamma at every scale with
symmetric tails (~80% coverage at the shipped width). Live-verified: DST
p10 ≈ −0.2 (negative weeks exist), K bands realistically wide.

## Mid-season backtest (backtest_midseason.py)

Stands at week 5/9/13 of each season 2019-25 knowing only weeks 1..K-1 and
projects the rest of the season. Findings:

- **JS_PRIOR_STRENGTH=5 is validated**: the (5·clay + g·ppg)/(5+g) blend
  beats pure Clay AND pure season-to-date PPG at every checkpoint (wk9 MAE
  2.60 vs 2.93 both), and P=5 beats P=2/8/12. The hand-picked constant stays.
- **The season shock does NOT decay**: cv .45 stays Brier-optimal for
  rest-of-season outcomes at weeks 5, 9 AND 13 (cv .55 hits 80% coverage at
  ~.001 Brier cost) — future injuries/role churn don't shrink just because
  part of the season is observed. Per-remaining-game uncertainty is roughly
  constant all year.
- **Absence rule is time-dependent**: zeroing players who missed the last 2+
  weeks HURTS at wk5 (they come back), is a wash at wk9, and clearly helps at
  wk13 (late absences are season-enders). The live sims' real Sleeper IR/Out
  designations are strictly better info than this proxy.
- SHIPPED from this: **League sim now draws the same per-player season shock**
  (cv .45, QB/RB/WR/TE, persistent across each sim's remaining weeks +
  playoffs, lineups still picked by mean) — playoff/title odds run cooler and
  honester; previously it had no shock and was overconfident at any week.

## Team pace / play-calling tracker (pull_pace_tracker.py + TEAM PACE tab)

Season-to-date team tendencies (plays/gm, neutral pass rate, PROE, no-huddle,
2+TE personnel) vs a **coach-aware baseline**: same coach → the team's own
2025 identity; new coach → HIS most recent pace/no-huddle/2TE identity (those
travel — see the coach research) but the roster's 2025 pass mix (the QB
decides that). Coaches auto-detected from 2026 pbp once games exist;
preseason = baselines only, multipliers 1.0.

**Validated before shipping** (`--validate`, 224 team-seasons 2019-25): drift
shown by week 8 vs this baseline persists to weeks 9+ — no-huddle r .78,
2+TE .75, PROE .61, neutral pass .57, plays .44.

**Multipliers backtested NEGATIVE and turned OFF** (`backtest_pace_layer.py`,
wks 5/9/13 of 2019-25, ~1,300 player-seasons/checkpoint): applying the drift
to player means was +0.2-0.5% WORSE MAE, ~49% win rate, monotonically worse
at 2x elasticity, and worse still on the JS-blend basis (confirming the
double-count worry). TE-only looked faintly positive but the component
ablation flipped between checkpoints — noise. Vegas totals + realized PPG
already price team tendencies at player level. `paceMult()` still exists for
the tab display but weeklyProjection does NOT apply it; do not re-enable
without a passing backtest. The tab is INTEL: spotting a new coordinator's
real identity by ~wk 3, weeks before Clay/consensus react.

`backtest_blend_weekly.py` (19,565 played player-weeks 2019-25): the
week-to-week prior sweep — **P=5 is best in every bucket** (wks 2-5, 6-10,
11-18), same as the rest-of-season sweep. The preseason guide is worth
exactly ~5 games of in-season evidence at both horizons; JS_PRIOR_STRENGTH=5
is the statistically right blend, twice-validated.

Refresh: `python pull_pace_tracker.py` re-downloads 2026 pbp+participation
into pbp_cache each run and rewrites `data/pace_2026.js` — wired into
update_simlab.bat (daily 9:45, non-fatal on failure).

## Vegas layer backtest (backtest_vegas_layer.py)

Historical closing lines come free from nflfastR pbp (spread_line/total_line
per game, already in pbp_cache; implied-total sign convention auto-validated
against actual scores, corr ~+.38-.43 per season). 17,599 player-weeks
2019-25, base = the validated P=5 blend:

- **VEGAS_ELASTICITY 0.5 was twice too hot for pass positions.** Empirical
  elasticity (bucketed actual/base vs implied deviation) = **0.20**;
  MSE-optimal per position: QB/WR/TE 0.25, **RB 0.50** (game script is real —
  favorites feed their backs, trailing teams abandon the run). SHIPPED
  `VEGAS_ELAS = {QB .25, RB .50, WR .25, TE .25, K .50}` (K untested — no K
  history in Clay data; kicker points are nearly a direct share of team
  points, left at .50). vegasMult() now takes pos. Why 0.5 was wrong:
  implied totals correlate with team quality Clay already prices into the
  player projections; only the matchup residual is exploitable.
- **DST mean model validated + refit**: realized regression on 3,625
  pbp-reconstructed DST weeks = 16.2 − 0.436·oppImplied vs the synthesized
  15.5 − 0.42 — slope was dead on, intercept ~0.35 pts low. dstWeeklyMean
  updated to the fitted numbers.

Visible effect: high-implied teams' QBs/WRs get about half the schedule
uplift they used to (Allen season Δ vs Clay pace +23 → +7) — that surplus
was double-counted team quality, not real matchup edge.

## Snap + defense layer backtest (backtest_snap_defense.py)

Historical snap counts from nflverse (snap_counts_YYYY.parquet in pbp_cache).
17.9k player-weeks 2019-25, base = the P=5 blend:

- **Snap trend VALIDATED — the engine's only undersized layer.** Real MSE
  gains on affected weeks (38.75→37.98), monotonic dose-response (-16 snap
  pts → 0.87x actual, +17 → 1.24x), empirical slope 1.09%/snap-pt vs the
  0.8 shipped → **bumped to 1.0%/pt** (clamps unchanged).
- **Preseason defense identity: NO signal.** Prior-season positional FPA
  (the testable analog of the Clay-unit-grades layer — no historical grade
  archive exists) grades best at e=0, slope 0.11, non-monotonic. Clay's
  personnel grades are plausibly better than that proxy but untestable →
  **defenseAdj halved to 1%/grade-pt, cap ±4%** (was 2%/±8%), not zeroed.
- **In-season FPA: real signal at 25% strength.** The jsOppMult design
  (clamped ratio, trust min(1,g/8)) applied full-strength graded WORSE than
  no adjustment; e=0.25 is optimal → **JS_FPA_ELASTICITY 0.25** now shrinks
  the deviation before the trust blend.

## Elite shadow-corner backtest (backtest_cb_shadow.py) — SHIPPED 2026-09-01

Does an elite CB (the corner himself, not the WR facing him) suppress
opposing WR points beyond the shipped layers? 45 curated elite-CB
defense-seasons 2019-25 (All-Pro / consensus lockdown reps), weekly on/off
from nflverse DEFENSIVE snap counts (defense_pct ≥ .5; ≥4 games to "belong"
to a defense so trades split), graded on 7.3k WR player-weeks vs the P=5
blend base:

- **Real signal, and it's the corner, not the reputation of the defense**:
  vs elite-CB defenses with the CB ACTIVE, WRs hit 0.954 of expectation vs
  1.054 control (~9-10% suppression); weeks the SAME defenses played without
  him, 1.049 — indistinguishable from control. Paired within-defense-season
  (16 defenses with ≥2 out-weeks): active 1.021 vs out 1.084 → the CB alone
  is worth ~6% of an opposing-WR week (10 of 16 pairs agree in direction).
- **The shipped in-season FPA layer does NOT capture it** (e=0.25 + trust
  ramp is too small/slow): ratios barely move on the FPA-adjusted base
  (0.959 vs 1.050). Flat dock on CB-active weeks is MSE-optimal at ×0.94
  (all-WR AND WR1-only), worth ~0.7% MSE on those weeks.
- **No WR1-shadow refinement**: WR1s are NOT hit harder than the rest of the
  corps (0.965 vs 0.954) — it reads as a whole-secondary effect, and no
  public per-route assignment data exists to know who was shadowed (PFF
  WR/CB matchup charts are premium; not in our cache).
Follow-ups (research_cb_field.py + research_cb_wr_side.py, 2026-09-01):

- **Individual CB impacts are NOT differentiable**: across 500 CB-seasons
  (≥8 active gms), a corner's suppression ratio persists year-over-year at
  r=.10 — the scariest quartile (0.81) regresses to 1.01 the next season.
  One flat per-defense dock is right; do NOT tier docks per corner or add
  list members off single-season outcome ratios (reputation/film is the
  operative criterion, which is why the list lives in overrides.js).
- **The on/off effect is NOT elite-specific**: 118 non-elite CB1
  defense-seasons with ≥2 out-weeks show active 1.028 vs out 1.083 — losing
  an ORDINARY CB1 boosts opposing WRs +5.5%, nearly the elite list's +6.3%.
  What IS elite-specific is the suppression while whole (0.954 vs 1.028).

## CB1-out boost (backtest_cb1_boost.py) — SHIPPED 2026-09-01

Sized from 855 CB1-out WR-weeks vs 6,331 CB1-active (2019-25; CB1 = the
CB with the most games at def_pct ≥ .6 that season): out-weeks run +7.5%
over base×FPA, MSE-optimal flat ×1.04; CB1-ACTIVE weeks need nothing
(×1.00-1.02 flat — baseline holds). The slot pattern INVERTS vs the dock:
slot WRs gain most (+15.5%, opt ×1.10), outside least (×1.02) — the depth
chart cascades and the backup lands in the slot. Holds for elite CB1s too
(n=36, +11.9%), so it composes with the dock: elite CB1 out ⇒ dock off AND
boost on.

- SHIPPED as `cb1OutBoost()` (engine.js), WR only, slight shave under the
  optima: **outside ×1.02, mixed ×1.04, slot ×1.08, unknown ×1.04**; same
  three chains as the dock (factor, jsChain, marketRate). Kill switch:
  `window.SIM_CB1_BOOST = false`.
- CB1 identity + status = `SIM_CB1_2026` (sleeper_meta.js, refresh_data.py):
  in-season, top-snap CB per team from the nflverse snap_counts_2026
  parquet (auto-downloaded when stale; 404 preseason is harmless); until
  ≥20 teams have 2026 data, 2025 snap profiles (games summed across trade
  stints) mapped through each player's CURRENT Sleeper team — 30/32 teams
  resolve preseason (KC + CHI lost their 2025 CBs to churn; they pick up a
  CB1 automatically once 2026 snaps land). `out` = Sleeper Out/Doubtful or
  off the active roster; current status applies to every projected week
  (same limitation as the dock). PFR→Sleeper name bridging: exact norm,
  then first-3-chars+lastname (ambiguous short keys dropped).
- Verified headless over 7,301 player-weeks with injected scenarios: DEN
  CB1 out + Surtain active = dock×boost (outside ×0.969), Sauce (elite AND
  CB1) out = boost only, healthy defenses = dock only, exact per slot tier.

## PFF season-signal audit (backtest_pff_layers.py, run 2026-09-01)

Y-1 PFF signals vs the recency-core residual, 1,509 player-seasons: ALL
effectively priced in already. yprr (+1.9% MAE), route grades (+1.2%), RB
yco/elusiveness (+3-4%), team pass-block (flat/hurts), team run-block
(flat) — real correlations, but Clay + realized PPG already carry them.
Lone marginal helper: TE route_rate fade (-0.7% MAE) — below the ship bar.
Season-level talent/OL GRADES are a dead end; week-resolution transients
(injuries, roles, availability) are where the un-priced signal lives.

## OL-availability dock (backtest_ol_out.py) — SHIPPED 2026-09-01

Jack asked "offensive line ranks" — grades are priced (above), but OL
AVAILABILITY is the offensive mirror of the CB1-out layer. Starting five
= top-5 C/G/T by games at off_pct≥.6; 15k own-team player-weeks 2019-25.
Raw buckets confound with week-of-season (injuries accumulate late while
the blend base tightens), so ratios were re-computed within week bands:
RB dose-responsive (full five +5.5% rel, 1 missing -8%, 2+ -12%);
QB/WR/TE flat at 0-1, -3-5% at 2+ missing.

- SHIPPED `olOutDock()` (engine.js), own-team, DOCKS ONLY (no full-line
  boost — preseason everyone reads healthy and a uniform boost would bias
  the baseline): **RB ×0.98 (1 missing) / ×0.95 (2+); QB/WR/TE ×0.97
  (2+)**. Same three chains, kill switch `window.SIM_OL_DOCK = false`.
- `SIM_OL_2026` (sleeper_meta.js via refresh_data.py): {team: missing
  count}. In-season five from 2026 snaps; preseason from 2025 profiles →
  current Sleeper teams — only 11/32 teams resolve preseason (OL churn +
  rookie starters have no profile; absent team = no adjustment) and the
  map self-completes once 2026 snaps land. Sleeper OL positions:
  OL/T/G/C/OT.
- Verified headless 7,301 player-weeks with injected counts: 2-missing
  team RB ×0.95 / QB ×0.97, 1-missing RB ×0.98, everything else exact 1.

## TE route-participation trend (backtest_route_trend.py) — SHIPPED 2026-09-01

Weekly route participation = share of team dropbacks the player is on the
field for (nflverse participation offense_names × pbp qb_dropback, joined
on game+play id). Backtested 2023-25 (the full-name seasons — the same
path the live 2026 build uses), 6,761 player-weeks with BOTH route and
snap trends, same trend construction as snapMult:

- route delta correlates .92 with snap delta — **WR: e=0 best on top of
  snaps (nothing to add), RB: noise (e=.25, -0.08%)**. Do not ship those.
- **TE: real increment** — TEs block, so snap % overstates a blocking
  TE's usage. On top of shipped snapMult: TE MSE 27.90 → 27.58 at e=1.0
  (monotone to the optimum, stacking beats route-only replacing snap).
  Dose-response: +15 route-pt risers beat even the snap-adjusted base by
  29% — route share is the leading indicator for TE role changes.
- SHIPPED `routeMult()` (engine.js): TE only, 1.0%/route-pt, weighted
  last-3 vs season avg, ≥2 past games, stale >3 wks no-op, clamp
  [0.75, 1.30]; stacked with snapMult in all three chains. Kill switch:
  `window.SIM_ROUTE_TREND = false`.
- Data: `data/sim_routes.js` (SIM_ROUTES_2026, norm-keyed TE weekly
  route %) built by pull_pace_tracker.py from the 2026 pbp+participation
  it already re-downloads daily — empty preseason, so the layer is a
  provable no-op until Week 1 data lands. Loaded by index.html AND
  export_site_proj.js (site projections inherit).

## Soft-pass-rush QB boost (backtest_pressure.py) — SHIPPED 2026-09-01

**2026-09-14 — PROXY REWIRE (backtest_pressure_proxy.py).** The original
signal (`was_pressure` in nflverse `pbp_participation`) is FTN-sourced from
2023 on and is published only AFTER the postseason ("does not update during
the season" — nflreadr schedule), so SIM_PRESSURE_2026 was empty all year
and the layer a silent no-op. The same is true of the TE route layer
(routes need the per-play lineups from that file) — it stays inert until
the post-season rebuild; the TE snap trend carries the usage signal.
Replacement signal, pbp only (nightly): **(qb_hit OR sack) / dropbacks**.
- Proxy vs true, defense-season rates 2018-25 (n=256): corr +0.68 (hit
  only +0.67, sack only +0.44); proxy rate mean .145, sd .023 vs true .299
  / .034. Stability is the same non-identity as before (in-season +0.35,
  YoY +0.29 — season-to-date with trust ramp, never priors).
- Layer sweep on the IDENTICAL 2,263 QB player-weeks: true best thr -0.03
  x1.08 = -0.46% MSE; proxy best thr -0.02 x1.08 = -0.37%. Thresholds are
  the same ~0.65 sd depth (proxy dev sd .030 vs .047). Shipped x1.05 at
  thr -0.020: -0.36%, bootstrap 90% CI [-0.68, -0.04], P(improve) .97
  (true-flag shipped: -0.39%, .98). 5 of 7 seasons improve (2021 +0.65,
  2023 +0.23 the misses); the soft sets overlap only ~half (jaccard .34),
  so this is a cousin of the original layer, not a copy.
- SHIPPED: `PRESSURE_THR = -0.02` (proxy units), boost/gates unchanged.
  pull_pace_tracker.py now builds SIM_PRESSURE_2026 from pbp alone
  (participation no longer required); routes still wait on participation.
  With ~35-40 dropbacks/game the n>=80 opp gate means first boosts land
  around Week 3. Log: pressure_proxy_backtest.log.


Opponent pressure rate (participation was_pressure × pbp dropbacks,
~18-20k/season 2018-25). Findings, 2,263 QB player-weeks:

- **The effect is ONE-SIDED**: QBs facing the softest pass rushes (rate
  ≥3pts under league avg season-to-date) beat the FPA-adjusted base by
  ~+10% (raw MSE optimum ×1.08, -0.46% — the largest single-layer MSE
  gain of the matchup family, consistent at every opp sample depth).
  High-pressure defenses show NO suppression beyond FPA/Vegas — partly
  because QB pressure-RESISTANCE is a real persistent skill (r=+0.44)
  already embedded in realized PPG. No dock side exists.
- Defense pressure rate is NOT a stable identity (in-season early→late
  r=+0.31, YoY +0.31 — unlike man rate's +0.80) → the layer reads
  season-to-date rates with a trust ramp, never priors.
- WR: e=0 best, non-monotone buckets — nothing. QB only.
- SHIPPED `pressureMult()` (engine.js): QB ×1.05 (shaved from ×1.08 for
  Vegas overlap) when opp season-to-date pressure rate ≤ league −3pts,
  trust min(1, dropbacks/250), gate ≥80 dropbacks + ≥1000 league
  dropbacks; league avg computed from the live map itself. All three
  chains. Kill switch: `window.SIM_PRESSURE_BOOST = false`.
- Data: `SIM_PRESSURE_2026` {def: [pressured, dropbacks]} added to
  data/sim_routes.js by pull_pace_tracker.py (same daily pbp+participation
  join as the TE routes) — empty preseason, provable no-op.

## Weather (wind) docks (backtest_weather.py) — SHIPPED 2026-09-01

Game weather from pbp (roof/temp/wind, 97% outdoor coverage 2019-25).
Wind dose-response survives BOTH tests that kill weaker layers: a
Vegas-adjusted base (books underprice wind for player scoring — raw and
Vegas-adj ratios nearly identical) and week-of-season control (windy games
cluster late; the OL-layer confound). Week-controlled relative ratios:
wind 15+ QB 0.906 / WR 0.875 / TE 0.926; 10-15 mph ~0.965-0.975.
RB immune (better in wind/cold — teams run). K (pbp-reconstructed weeks
vs own season mean): ~-0.5 pts in any 10+ wind.

- **NO dome boost**: indoor buckets read +3-4% but that is venue-mix
  composition — dome-team players' own baselines already contain their
  dome games. Wind docks are event-rare (~2-3 games/season) vs each
  player's mixed baseline, so they are safe. Cold skipped v1
  (wind-correlated; would double-dock).
- SHIPPED `weatherMult()` (engine.js), shaved: **wind ≥15mph QB ×0.94 /
  WR ×0.93 / TE ×0.95; 10-15mph ×0.97/×0.97/×0.98; K ×0.95 at ≥10mph**.
  Applies to BOTH teams of the game (home stadium's forecast). All three
  chains. Kill switch: `window.SIM_WEATHER = false`.
- Data: `data/sim_weather.js` (SIM_WEATHER_2026 {homeTeam: {wk: {wind,
  temp}}}) built by refresh_data.py — Open-Meteo (free, no key) hourly
  forecasts per OUTDOOR stadium (21-entry static lat/lon table;
  retractables/domes get no entry), sampled as the mean of kickoff hour
  +3h from kickoffs_2026.json, 16-day horizon. Runs in the daily chain
  AND every pregame slot, so game-day forecasts are fresh. Missing entry
  (dome / beyond horizon / preseason) = no-op. Verified headless 7,845
  player-weeks incl. K with injected 18mph/12mph forecasts — exact tiers,
  both teams docked, RB untouched.

## Man/zone matchup layer (backtest_man_zone.py) — REJECTED 2026-09-01

Tested the full product: per-play coverage labels (participation
defense_man_zone_type, ~17k labeled targets/season 2018-25) joined to pbp
targets → player man/zone splits × opponent man-rate deviation.

- **GATE 1 FAILED — player man/zone splits are noise**: YoY persistence
  r=+0.05 (342 consecutive pairs, ≥25 tgts each side); "man-beaters"
  (+0.69 pts/tgt) and "zone-beaters" (−0.41) both regress to ~+0.15.
  There is no such thing as a projectable individual man-beater.
- Gate 2 passed for the record: defense man rate IS a stable scheme
  identity (early→late same season r=+0.80, spread sd 11.7pts around 36%;
  YoY r=+0.36) — real identity, no exploitable player interaction.
- Layer MSE: e=0 best, every elasticity hurts; deviation buckets flat
  (1.017/1.026/1.016).
- Profile-level salvage also empty: slot/outside/deep/short WR groups all
  perform identically vs man-heavy, neutral and zone-heavy defenses
  (±2%, non-monotone).

NOT SHIPPED — joins the rejected-with-evidence pile (pace multipliers,
coach-change variance, prior-season FPA, season-level PFF signals). Do not
rebuild without new per-route matchup data (e.g. PFF premium charting).

## QB/TE extension (research_cb_qb_te.py) — QB SHIPPED, TE REJECTED 2026-09-01

Same harness per position. **QB inherits ~the full corner effect**: elite-
CB-active weeks 0.949 vs 1.075 control (raw MSE opt ×0.94, same as WR),
and it VANISHES when the corner sits (out-weeks 1.122) — corner-driven.
CB1-out also transfers (1.116 vs 1.048 active, +6.5% relative, opt ×1.08).
SHIPPED: QB flat **dock ×0.96** + **CB1-out boost ×1.04** in the same two
functions (no slot dimension — the QB aggregates the whole route tree; no
double count vs the WR docks, marginal projections aren't summed).
**TE gets NOTHING, on evidence**: TEs vs elite-CB defenses look suppressed
(1.017 vs control 1.093) but stay equally suppressed with the elite CB OUT
(1.026) — a team pass-defense effect Clay grades + FPA already price, not
the corner; TE CB1-out boost is only ~+2% relative, below the ship bar.
Verified headless: QB ×0.96 vs healthy elite-CB defenses, ×0.9984
(0.96×1.04) in the DEN CB1-out scenario, TE/RB byte-identical.
- **Slot receivers are immune** (the WR-side moderator): normalized dock by
  same-season PFF slot_rate = ×0.874 outside (<30%), ×0.900 mixed, ×0.983
  slot (>60%); aDOT agrees (deep ×0.864, short ×0.965). Per-bucket MSE
  optima ×0.92 / ×0.96 / ×1.00. The per-WR "immune" list is just the slot/
  YAC guys (Waddle, Deebo, Godwin, JuJu) — mechanism, not magic.

- SHIPPED as `cbShadowMult()` (engine.js): **WR only, slot-graduated** —
  after the same live-overlap attenuation as the flat version, outside
  (<30% slot rate) ×0.95, mixed (30-60%) ×0.97, slot (≥60%) NO dock,
  unknown (rookies/thin routes) ×0.96. Slot rates = latest PFF receiving
  season baked by refresh_data.py → `SIM_WR_SLOT` (187 WRs). Applied
  in both the Clay factor chain and the JS chain (and marketRate's factor
  rebuild). Docks sit below the raw MSE optima because the live stack
  overlaps — Vegas totals + the Clay CB-unit grade (±4% cap) already price
  part of elite-defense quality, and the P=5 measurement base had neither.
  List: `ELITE_CBS_2026` in overrides.js (SLEEPER full names — 'Pat
  Surtain', no suffixes); refresh_data.py resolves each name to current
  team + injury/roster status from the Sleeper dump it already pulls →
  `SIM_CB_STATUS` in sleeper_meta.js. A CB who is Out/Doubtful or off the
  active roster (IR/PUP/Sus) docks nothing until he's back; Questionable
  still docks. Kill switch: `window.SIM_CB_DOCK = false`. Verified headless
  over 7,301 player-weeks: exactly WR-vs-elite-CB-defense weeks move by
  their slot tier (mean AND jsMean), everything else unchanged.

## Coach play-calling research (research_coach_tendencies.py)

nflverse pbp 2018-2025 (pbp_cache\ outside this folder, ~150MB) → per
team-season: plays/gm, neutral-script pass rate, PROE, EPA/dropback,
EPA/rush, no-huddle rate, 2+TE personnel rate (participation data), HC from
pbp coach fields (public data has no OC/play-caller). Findings:

- **Coach-owned tendencies** (sticky with same coach, travel on moves, vanish
  when he leaves): no-huddle pace identity (r .80 same-coach, .00 team-keeps),
  2+TE personnel (r .46 / -.13 team-keeps / +.51 follows the coach, n=11
  moves). plays/gm follows movers too (r .62) but is weak year-to-year (.23).
- **Roster-owned**: neutral pass rate + PROE (~.5 same-coach but only ~.1-.2
  across moves — the QB decides, not the coach). Efficiency (EPA) barely
  persists at all — don't project it.
- Coach change adds volatility: |YoY change| ×1.9 no-huddle, ×1.2 EPA/rush &
  2TE vs stable rooms.
- **Variant D experiment (NEGATIVE — not shipped)**: wider season shock for
  new-HC teams (players mapped to teams by opponent-sequence matching, ~90%
  match rate). All (stable, changed) splits ≤ ±.001 Brier vs uniform cv .45
  with slightly worse coverage — player-level injury/role variance dwarfs the
  team-level coaching uncertainty. Uniform shock stays.
- Where this data WILL pay: the in-season pace/PROE/personnel tracker (team
  tendency drift is observable by ~W3, weeks before Clay's guide updates) —
  slot alongside the snap trend in JS Weekly.

## Season sim (full season outcome)

SEASON SIM tab: every player's entire schedule simulated week by week — byes,
Vegas implied totals, opponent defense, QB/injury windows, rookie ramps and
the snap trend shape each week's mean, and each simulated season shares its
game-environment draws league-wide (booms line up with shootouts). Output per
player: season-total distribution (mean/p10/p50/p90), Δ vs Clay's naive pace
(season/17 × games in range, so the schedule layer's effect is isolated), and
**positional finish odds** — avg finish, P(#1/top-3/top-12/top-24), ranked
against everyone else *within the same sim* so correlations price into the
odds; a **Model odds / Sportsbook toggle** shows those four columns as
futures-style prices instead (same vig + board rounding as the league sim's
weekly board; the detail drawer's finish distribution stays in %). Any week range works (`Weeks 15–17` = the fantasy-playoff stretch).
Click a row for the week-by-week projected path + full finish distribution.
"Median stat line" view: the range's weekly component means (Vegas/defense/
windows included) scaled so pass/rush/rec yards, TDs, receptions and
estimated targets re-score to EXACTLY the sim's median season points, plus
FPPG (median ÷ scheduled games — the injury layer means played games can be
fewer). Same recipe as the weekly stat view; K/DST show points only. Note
the median season sits ABOVE the mean now (wreck-mixture left skew), so
these stat lines read as healthy-season paces — that's the correct
interpretation of "median outcome".

## League sim (Sleeper)

Paste a league ID → pulls league settings, scoring, lineup slots, rosters,
users, and **the real week-by-week matchup pairings**. Sims the remaining
regular-season weeks (carries actual W/L/PF mid-season), seeds the playoff
bracket per league settings (4/6/8 teams, top-2 byes at 6), and plays the
bracket in the league's actual playoff weeks against those weeks' Vegas
slates. Offseason (no matchups published yet): synthesizes a round-robin and
labels it as such — reload once Sleeper generates the schedule.

**Injuries (definitive only, no Questionable/Doubtful guessing):** on league
load we pull Sleeper's player DB (trimmed to our pool, cached 12h in
localStorage). IR / Suspended / NFI → excluded from every remaining week;
regular-season PUP (4-game minimum) → same; camp PUP in the preseason is
deliberately IGNORED (those players are usually active by Week 1); ruled
"Out" → benched for the upcoming week only, next-best player starts. League
IR/taxi slots are dropped outright. Each league re-load re-pulls status, so
activations come back automatically. Flags are shown per team in the Rosters
table and counted in the load status line.

Not yet handled: 2-week championship rounds, median-vs-league extra game, IDP.

**D/ST streaming + bye-hole fills (2026-08-31):** rosters are no longer locked
for the whole sim. (a) D/ST: the model already prices DST as pure matchup
(dstWeeklyMean = f(opp implied)), so each week any team whose rostered DST
projects >1.0 pt (STREAM_TOL) below the best D/ST still on waivers — or whose
DST is on bye — claims a DISTINCT waiver DST (worst rostered unit claims
first, mirroring waiver priority; close calls keep the rostered unit; pool =
truly unrostered DSTs, so deep leagues get a thinner baseline automatically).
Controlled test: worst-schedule DST locked = 14.1 ppg vs streamed = 19.1 on a
QB+DEF lineup. **STREAM_TOL=1.0 backtested** (`backtest_stream_tol.py`,
2019-25 closing lines + pbp-reconstructed DST actuals): the projected gap is
CALIBRATED — realized gain tracks it at slope ~1.07 whether the alternative
is the #1 or #3 matchup on waivers (sub-0.5-pt gaps are noise, +0.11±0.76);
the 14-week policy sweep says streaming beats holding by ~+37 pts/season
(6.7→9.3 DST ppg) and is FLAT from TOL 1.5 down to 0 (max +39.3 at 0.75 vs
+37.0 at 1.0 — inside noise; TOL 0.5's negative marginal confirms it), so
1.0 keeps ~95% of the streaming value while modeling that managers don't
churn for slivers. TOL 2.0 already captures +34.5. (b) lineup-hole fills, EVERY slot (Jack's rule: a team that
wouldn't have a starting lineup is always protected): any slot the roster
literally cannot fill this week — QB with no backup, TE hole, empty RB/WR
or FLEX after bye clusters and IR/Out exclusions — claims the best eligible
unrostered player for that week instead of starting a zero. No upgrade
streaming: rostered players always keep their jobs; only genuinely
unfillable slots trigger claims, distinct across teams per week
(unfilledSlots mirrors pickLineup's greedy assignment exactly). Controlled
test: a 2-man roster in a 7-slot lineup fields 110 ppg with waivers open vs
21 with the pool emptied. Kill switch for A/B: `window.SIM_WAIVER_FILLS =
false` reverts to fully roster-locked lineups. Rville A/B (5000 sims each):
deep dynasty rosters mute the layers exactly as designed — every team +0.2
to +2.4 PPG (thinnest roster gains most), contender odds shift within noise,
one mid team's playoff odds -4.5pp (its edge had been opponents' phantom
holes).
**Bye fills backtested** (`backtest_bye_fills.py`, Clay 2019-25 preseason
guides vs weekly actuals, top-R rostered sweep = league-size proxy): the
k-th best waiver player REALIZES ≥ his projection at every depth — QB ratios
1.05-1.45 (rostered-18 waiver QB projects 14.6, scores 17.6 — a waiver QB
who's actually starting that week beats his preseason number; the engine's
qbWindow per-start rates capture exactly this), TE 0.99-1.28 — so fills are
honest-to-conservative, no haircut, and the conservatism also covers the
static-pool caveat (real pools thin as breakouts get added; late-season
split shows no degradation). League-size sensitivity quantified: best-waiver
realized falls QB 18.9→15.6 / TE 8.9→4.8 ppg from shallow (top-10 rostered)
to deep (24-28 rostered) — the engine inherits this automatically because
its pool is the loaded league's ACTUAL unrostered list, so 10-vs-14-team and
14-vs-20-slot rosters price their own replacement level. Both run in
the deterministic lineup-prep pass (claimed players are real player objects,
so sigma/correlations price normally) and apply to playoff weeks too. Demo
league effect: every team +2-3 PPG, spread tightens slightly (phantom
DST-schedule edges wash out).

**Weekly breakdown** (below the standings): pick any simmed week → every
matchup that week, sorted closest game first (GAME OF THE WEEK tag; TOP TOTAL
flags the shootout). Two views via the **Model odds / Sportsbook toggle**:
Model = win %, exact fair (no-vig) ML, projected scores, total, margin;
Sportsbook = a book-style board — ML with a standard ~20-cent vig (coin flip
posts −110/−110, ±100 posts EVEN) and graduated board rounding (+1266 →
+1300), spread to the half point (PK = pick'em), O/U. The toggle also flips
the STANDINGS table's Playoffs/Bye/Finals/Title columns into futures-style
prices (same vig; — = zero sims), and a **Season futures board** below the
standings prices every season market per team — Most PF (scoring title, new
per-sim pfLead tally in simLeague), Reg-season 1st, Playoffs, Bye, Finals,
Title, Last place: Model view = raw % + exact fair line (mlFair, no weekly
clamp so long shots read +19900), Sportsbook view = vigged board; rows click
through to the team drawer. In Sportsbook mode the standings' MED W, AVG PF and
MED FIN become O/U MARKETS at .5 lines (MED W = win-total line from
winCounts, same balanced-.5 construction, over = more wins): PF line = per-sim season-PF median
(new pfDist Float64Array in simLeague results) snapped to the .5 grid —
prices out −110/−110 by construction; finish line = the k.5 where the
finish distribution splits closest to 50/50, juice skewing where discrete
places can't balance (e.g. 4.5 o−120/uEVEN). Under = that place or better.
The toggle itself lives in the top control bar next to RUN SEASON SIM. All numbers come straight from the same
season sims (`r.weekly` tallies), so correlations, byes, injury windows and
the season shock are already priced in. Click a team name to open its full
week-by-week drawer. Playoff rounds aren't fixed matchups, so they stay in
the team drawer only.

## Tracking & accuracy loop (the whole point)

1. **LOCK PER GAME** before each kickoff — check the game(s) and LOCK SELECTED
   (TNF Thursday, the Sunday slate Sunday morning after inactives, MNF Monday),
   or LOCK ALL REMAINING for everything still open. Each lock freezes 2000-sim
   projections + component means + the prop lines AS OF THAT MOMENT for just
   those games, merged into one weekly snapshot (localStorage + JSON download).
   Locked games are frozen — no re-locking. The week's first lock fixes the
   scoring preset for consistency.
2. **SCORE WEEK** after the games — pulls actuals from
   `api.sleeper.app/v1/stats/nfl/regular/2026/{wk}`, grades:
   - MAE / RMSE / bias of our point projections — computed for BOTH the mean
     and the median (p50). A sportsbook line is the market's *median*, so the
     median columns are the apples-to-apples read; mean vs median bias also
     shows how much our right-skew assumption is worth.
   - calibration: % of actuals inside our p10–p90 band (target ~80%)
   - **beat-the-books rate**: per stat (pass/rush/rec yds, pass TD), was our
     number closer to the actual than the books' line? Tallied twice — once
     with component means, once with median-scaled components (comp ×
     p50/mean). The MEDIAN tally is the fair fight; sustained >52–55% there
     before anything ships publicly.
3. **EXPORT ALL** dumps the full season history as JSON.

## Files

- `engine.js` — projection model, RNG (seedable), gamma sampler, correlation,
  week sim, player season sim (simSeason), league/season sim, lineup optimizer.
- `app.js` — UI, Sleeper API client, demo league (12-team ADP snake), tracking.
- `refresh_data.py` — copies fresh data in from the repo + extension.

## Whole-board verification (backtest_full_board.py, 2026-07-31)

The combined harness grades PPG on veterans-with-history, so it structurally
cannot see the rookie no-Clay layer (rookies excluded) or the availability
layer (a games adjustment, invisible to a per-game metric). This grades
SEASON POINTS across BOTH populations — the currency the board ranks in,
where "never played" and "missed 6 games" count as the failures they are.

VETERANS (1,509 player-seasons, LOYO)      base -> +VS/mover/TEroute -> +avail -> +shrink
  QB   85.3 -> 85.3 -> 77.0 -> 74.2   -13.08%
  RB   59.6 -> 57.4 -> 56.6 -> 56.3    -5.48%
  WR   47.9 -> 45.6 -> 45.1 -> 44.8    -6.36%
  TE   40.2 -> 37.1 -> 36.9 -> 36.6    -8.88%
  ALL  54.9 ----------------> 50.5     -7.99%

ROOKIES (543 drafted, LOYO, round-bucket baseline)
  RB 45.0 -> 39.9 (-11.4%) | WR 38.2 -> 31.5 (-17.7%) | TE 23.5 -> 18.9 (-19.8%)
  ALL 36.9 -> 31.1 (-15.7%)

The availability layer is where QB's big number comes from (85.3 -> 77.0):
per-game rate metrics can't see missed games at all, so it was invisible
until this harness existed.

RERUN 2026-07-31 with shrinkage SHIPPED (harness mirrors the engine exactly:
Clay-mean target, QB/RB down-only, k .80/.85/.90/.90):
  QB   85.3 -> 85.3 -> 77.0 -> 75.0   -12.11%
  RB   59.6 -> 57.4 -> 56.6 -> 55.4    -7.10%
  WR   47.9 -> 45.6 -> 45.1 -> 45.1    -5.83%
  TE   40.2 -> 37.1 -> 36.9 -> 36.7    -8.79%
  ALL  54.9 ----------------> 50.5     -8.02%
RB improves vs the earlier proposal (-5.48% -> -7.10%) because down-only
regression is strictly better there; WR gives a little back (-6.36% ->
-5.83%) since its symmetric k moved 0.90 either way. Pooled is flat at ~8%.

## Context-adjusted PPG — TESTED AND REJECTED (2026-08-03)

Idea: the recency core averages every game, mixing games played hurt (30%
snaps), games with a backup QB, and games with a teammate out. Compute PPG in
"clean" contexts instead. `backtest_context_ppg.py` reconstructs all three
(nflverse snap %, per-week primary QB from pbp, teammate availability) and
tests each as a replacement per-game rate, 1,491 player-seasons 2019-25:

| variant | QB | RB | WR | TE |
|---|---|---|---|---|
| healthy-games only (snap% >= 80% of own median) | +0.2% | +8.6% | +5.9% | +3.7% |
| starting-QB games only | +10.6% | +2.3% | +3.3% | +1.8% |
| both filters | +9.6% | +9.5% | +10.1% | +2.3% |
| teammate-availability re-weighting (no games dropped) | +1.2% | +0.1% | +0.4% | +0.3% |

ALL WORSE than raw PPG. Two mechanisms, both measured:
1. **Sample cost** — the healthy filter drops 12-21% of games, and the noise
   added to a ~13-game estimate exceeds the bias removed.
2. **Bad context REPEATS** — limited-snap share has YoY corr +0.31 (players
   who play hurt keep playing hurt: 19.9% vs 12.9% the next year) and
   backup-QB exposure +0.11. Filtering those games out systematically
   OVER-projects fragile players and players in bad QB rooms — the exact
   error the availability layer and mover discount exist to correct.

The teammate re-weighting result is the cleanest evidence: it drops NO games
(pure re-weighting) and is still slightly worse, so this isn't only a
sample-size artifact — the adjustment itself carries no predictive value.
Same lesson as season-total vs per-game shares: what looks like context noise
is usually persistent signal about the player.

## QB rush/pass split — TESTED, NOT SHIPPED (2026-08-03)

`backtest_qb_split.py`, 215 QB seasons 2019-25. QB is the worst-projected
position and rushing is 16% of the average QB's points (22%+ top quartile,
max 43%), so the hypothesis was that the components deserve different
treatment.

**The mechanism is real and large:**
  passing pts/g  YoY corr +0.538
  rushing pts/g  YoY corr **+0.806**   <- far more persistent
  total pts/g    YoY corr +0.520

A naive "split and re-add" is a mathematical no-op (same weights => same
sum), so the value has to come from treating them differently. Optimal
shrinkage splits exactly as the persistence predicts — passing regresses
hard, rushing barely at all:

| | raw core | in-stack (Clay blend) |
|---|---|---|
| unified core (k=1) | 3.2302 | 2.8261 |
| unified shrink | k=0.50, -14.88% | k=0.50, -5.88% |
| SPLIT shrink | kPass .50 / kRush .90, -15.74% | kPass .50 / kRush .75, **-0.52%** |
| nested LOYO (honest) | — | **-1.23%** vs unified |

Component-specific RECENCY memory was also tested (longer/shorter windows per
component) and is a wash (+/-0.06%) — one fewer knob.

NOT SHIPPED YET: the honest in-stack gain is ~0.5-1.2% on one position, and
the engine currently shrinks TOTAL fpts_pg at a single point in the pipeline
(before the Clay blend). Splitting requires carrying pass/rush components
separately through the layer stack, which is a real refactor of the QB path.
Worth doing, but as a deliberate change rather than a bolt-on — the payoff is
small enough that a subtle plumbing bug would erase it.

## RB role decomposition (backtest_rb_role.py) — GAME-SCRIPT ROLES REJECTED, TD-LUCK PASSED 2026-09-14

Jack: "backtest the RB role decomposition first." Role metrics rebuilt from
nflverse pbp SEASON-TO-DATE (weeks < W, shrunk toward the prior-season profile
with a 30-touch prior; RB = players.csv position; shares of the team's RB room):
touch_share, pass_role (tgt share − carry share), tilt (touch share leading −
trailing, pre-snap score diff; tilt7 at ±7), d3_gap (3rd-down + two-minute
share − touch share), rz_gap (inside-10 carry share − carry share), td_luck
(xTD from touch yardline − actual TD, per game; league xTD rates by
yardline bucket pooled 2018-25, targets inside the 5 one bucket). 4,405 RB
player-weeks 2019-25, base = P=5 blend × shipped Vegas e=.50, LOYO sweeps.
Log: rb_role_backtest.log.

- **Every game-script interaction is dead.** Role-dependent implied
  elasticity (e = .50 ± e1·tilt_z or ·pass_role_z): ±0.05%, 3-4/7 years.
  Spread × tilt, spread × pass_role, spread × d3_gap: MSE worse at every
  elasticity, monotone, 0/7 years. Closers do NOT gain when favored and
  passing-down backs do NOT gain as underdogs beyond what the implied total
  already carries. Goal-line share multiplier (rz_gap): worse at every r,
  0/7 — a back's realized PPG already embeds his goal-line role.
- Empirical elasticity note: pass-role backs are MORE implied-elastic
  (.55 vs .24 low tercile) and low-share backs most of all (.61) — high
  totals mean more passing and more garbage volume, not the spread story.
  Whole-RB slope .39 vs shipped .50 — consistent with the Vegas backtest.
- **TD luck is real, per-player mean reversion**: unlucky-so-far tercile
  (xTD−TD +0.16/g) runs actual/shipped 1.134, lucky tercile 0.996;
  corr(luck, act−shipped) +.078. Additive correction
  `+ k · 6 · (xTD−TD)/g · g/(P+g)` (i.e. luck removed from the realized
  half of the blend): pooled best k=.75, **LOYO −0.36%, 5/7 years**, picks
  .5-1.0 every fold. Centering luck per season gives the identical −0.36%
  → not a level effect. Gain holds in every season-to-date touch bucket.
  Same size class as the pressure boost (−0.46%), the largest shipped layer.
- Side finding: a flat +0.65 RB level shift is worth −0.86% on this base —
  the RB TD under-projection the weekly tuner's tdMult (RB rtd 1.09 / rctd
  1.10) already handles live; the backtest base has no tuner. Luck adds on
  top of the level fix (−1.26% combined vs −0.86% level alone).
- SHIPPED 2026-09-14 (Jack: "wire it up"). `tdLuckAdj(p, sc)` (engine.js,
  before the weather block): RB only, `TDLUCK_K = 0.75` x avg(rush_td,
  rec_td value) x (xTD-TD)/g x g/(P+g), g = the SIM_2026 games in the blend.
  Applied AFTER the chain (the backtest added it to base x Vegas) as an
  additive term scaled by availability iA (zeroed/docked backs get nothing
  back), floored at 0; the market-rate fallback adds (1-mw) x the same term.
  Kill switch `window.SIM_TD_LUCK = false`. Data `SIM_RB_TDLUCK_2026`
  {norm: {xtd, td, g, n}} appended to data/sim_routes.js by
  pull_pace_tracker.py `build_rb_tdluck_2026()` (nightly pbp; xTD rates
  baked as XTD_RUSH/XTD_TGT constants; players.csv refetched weekly for the
  RB filter) - already loaded by index.html AND export_site_proj.js, so site
  projections inherit at the next exporter run. Smoke (W2, half-PPR, 74 RBs
  mapped after W1): 64 RBs move, 0 non-RB, 0 zeroed; Henry 3 TD on 1.08 xTD
  -> -1.44 (21.67 -> 20.23), Allgeier 0 TD on 0.64 xTD -> +0.48; formula
  check exact. Backups engine.js.bak_pre_tdluck_20260914,
  pull_pace_tracker.py.bak_pre_tdluck_20260914.

## Target-area matchup (backtest_target_area.py) - REJECTED as a layer, SHIPPED as the ZONES tab 2026-09-14

Jack: "backtest the target-area matchup next" + "regardless ... note the
strengths and weaknesses of players and defenses that I can mention in
videos". Zones from nflverse pbp: depth by air yards (behind LOS / 0-9 /
10-19 / 20+) and side (pass_location left / middle / right); half-PPR
receiving pts per target. Defense r_z = pts/tgt allowed in zone vs league
(shrunk, K=60 tgts), funnel s_z = share of targets faced in zone vs league;
receiver w_z = his target mix season-to-date shrunk toward prior season
(K=40). Matchup M = sum w_z r_z / r_all (isolates the zone interaction from
position FPA). 10,598 WR/TE player-weeks 2019-25, base = P=5 x Vegas .25 x
shipped in-season FPA layer, LOYO. Log: target_area_backtest.log.

- **Gate 1 PASSED - receiver profiles are real**: target-mix YoY r: behind
  LOS .88, deep .75, intermediate .75, short .57; sides .34-.45.
- **Gate 2 FAILED - defense per-zone efficiency is noise**: residual
  pts/tgt ratio (zone / overall) early->late r -.01..+.03 every depth zone,
  YoY .00-.07. "Bad vs deep passes" does not exist as an identity; the
  overall rate (what position FPA prices) is all there is.
- Defense FUNNEL (share of targets faced per zone) is a soft identity:
  early->late r behind-LOS .37, middle .53, deep .23, short .15.
- Bucket table: deep-share WR tercile x defense deep-ratio tercile has NO
  diagonal (high-deep vs leaky .941, vs stingy .950). Sweeps: depth matchup
  +0.03% (2/7), side +0.01%, depth funnel +0.02% (4/7), matchup x funnel
  -0.02% (5/7, e=.25 - below the ship bar), zone-aware defense REPLACING
  position FPA +0.02%. WR-only and TE-only identical. NOT SHIPPED as a
  multiplier - joins man/zone in the rejected pile (same failure mode).
- Side finding worth its own test: actual/shipped by receiver DEEP SHARE
  tercile = low 1.09 / mid 1.04 / high 0.95 - the model under-projects
  short-area receivers and over-projects deep-ball receivers as a LEVEL.
  Candidate layer: player aDOT as a level predictor on the P=5 base.
- **ZONES tab (Sim Lab, intel only)** - pull_pace_tracker.py
  `build_zones_2026()` -> data/zones_2026.js (`SIM_ZONES_2026`: league,
  per-defense and per-receiver zone counts for 2026 + 2025 prior, nightly);
  app.js `renderZonesTab()`: league table of all defenses (funnel share vs
  lg per depth zone + middle/left/right, pts/tgt allowed shrunk to 1.0x with
  a NOISY tooltip), and a per-game matchup view (week + game selectors):
  defense zone card next to the opposing WR/TE/RB target mixes (aDOT, depth,
  side, 2026 + 2025 targets) with auto-generated READ callouts ("Deep 20+
  guy (28%, lg 13%)", "D funnels int 10-19", "D leaky deep so far (1.4x,
  noisy)"). Receivers come from the engine board grouped by team.
  Backups app.js/index.html .bak_pre_zones_20260914.

## Run-vs-pass snap split (backtest_snap_split.py) - REJECTED 2026-09-14 (TE route feed revived)

Jack: "backtest the run vs pass snap split next (rbs most important but wrs
and tes useful too)". Per player-week PASS-play snaps vs designed-RUN snaps
from participation offense_players x pbp play type, plus targets/carries and
team totals, season-to-date. 13,694 RB/WR/TE player-weeks 2019-25, base =
P=5 x Vegas x in-season FPA x participation-twin snapMult (total, 1.0%/pt)
= shipped; LOYO. Log: snap_split_backtest.log.

- GATE: targets-per-pass-snap is a real skill (YoY r RB .53 / WR .65 /
  TE .65; early->late .57/.65/.70); RB carries-per-run-snap YoY .90.
- A. ROLE-vs-USAGE GAP (expected target share from pass snaps x his anchor
  TPRR minus actual target share -> "under-targeted for his routes"):
  WR -0.10% (5/7, e=.02-.04 on z), RB -0.06% (4/7), TE +0.11% (0/7).
  RB run gap (run snaps vs carries): worse at every e, 0/7. Real but tiny -
  below the ship bar (pressure -0.36%, TD luck -0.36%).
- B. TREND DECOMPOSITION (separate pass-snap / run-snap trend elasticities
  replacing the total-snap trend): RB +0.13% worse (2/7), WR -0.03%, TE
  +0.14% worse. Pass-snap trend ALONE ~= the total trend for every position
  (the components are collinear); adding (passTrend - runTrend) on top of
  the total: TE -0.11% (5/7, c=.5) = the shipped TE routeMult in another
  form, WR -0.07%, RB nothing.
- NOT SHIPPED as a layer. Practical outcome: the TE route trend we already
  ship has been a silent no-op all 2026 (participation postseason-only).
  pull_pace_tracker.py `route_pct_fallback()` now fills SIM_ROUTES_2026 from
  the repo's data/route_pct.js (PFF Premium weekly routes / team dropbacks,
  same definition as the participation proxy; `est` seasons skipped) so
  routeMult goes live from Week 3 (needs >=2 past games). Live twin for a
  run/pass split intel column would be PFF offense/summary
  snap_counts_pass_play / run_play (the weekly puller keeps only
  snap_counts_pass_route today).

## aDOT level layer (backtest_adot_level.py) - REJECTED 2026-09-14

Follow-up to the target-area side finding (actual/shipped by deep-share
tercile 1.09 / 1.04 / 0.95). aDOT = air yards per target season-to-date
shrunk toward the prior season (K=40), z-scored within position. 10,598
WR/TE player-weeks 2019-25, base = P=5 x Vegas .25 x in-season FPA, LOYO.
Log: adot_level_backtest.log.

- Direction is real and one-sided: low-aDOT WRs beat the shipped mean 6-7%
  in EVERY season (terciles 1.03-1.09), the high-aDOT side is ~1.00 and
  flips sign year to year. TE noisier, same shape.
- Where it lives: Clay's prior runs 7-14% under for ALL WRs (a level the
  weekly tuner owns); the realized-PPG half carries the tilt (act/ownPPG
  1.05 low-aDOT -> 0.95 high-aDOT, also at g>=8) - deep-ball receivers
  under-run their own season-to-date mean, short-area receivers beat it.
  Games 1-4 buckets are flat (pure Clay level); the tilt appears once the
  realized half has weight.
- Sweeps: whole-mean x(1 - .02*adot_z) LOYO -0.07% (5/7); prior-only inside
  the blend -0.04%; deep-share z -0.05%; behind-LOS 0; prior-season aDOT
  only -0.01%. WR-only -0.06%, TE-only -0.06%. Flat WR/TE level x1.041 is
  WORSE (+0.17%, skew: mean ratio != MSE optimum).
- Mechanism test - shrink noisy players harder (P_i = 5 x sigrel^k): worse
  at every k, 0/7; the engine's sigma correlates with aDOT at only +.06, so
  volatility is not what the tilt is. Flat P re-swept on WR/TE alone picks
  6-7 (-0.06%, 5/7) - noise-level vs the twice-validated P=5; not changed.
- NOT SHIPPED. A ~2%/sd aDOT multiplier is real but a fifth of the ship
  bar; revisit only if a mechanism turns up (candidate: TD share of points -
  deep receivers' PPG is TD-heavier, and TDs regress).

## Receiver TD-share regression (backtest_wr_tdluck.py) - SHIPPED 2026-09-14

Jack: "backtest the receiver TD-share regression next". The RB TD-luck
mechanism on WR/TE. xTD per TARGET = league TD rate by yardline bucket
(<=5/10/20/40/100) x END-ZONE-THROW flag (air_yards >= yardline_100), pooled
pbp 2018-25 - depth matters: EZ throw from inside 5 = .50, from 20-40 = .27;
non-EZ inside 5 = .26, 20-40 = .03. WR/TE carries use the RB rush table.
luck = (xTD - TD)/g season-to-date. 10,597 WR/TE player-weeks 2019-25, base
= P=5 x Vegas .25 x in-season FPA, LOYO. Log: wr_tdluck_backtest.log.

- Unlucky tercile (xTD-TD +0.19/g) runs actual/shipped WR 1.112 / TE 1.186;
  lucky tercile 0.954 / 0.974; corr(luck, resid) +.10/+.11. Present in
  every games-into-season bucket (strongest games 1-4: WR 0.95 vs 1.17).
- **Additive correction + k x 6 x luck x g/(P+g): LOYO -0.93% (WR -0.79%,
  TE -1.26%), 7/7 years, k=1.0 in EVERY fold (1.5 worse).** Centered per
  season x position: -0.94% (pure regression). Multiplicative form -0.92%.
  Largest single-layer gain in the lab (pressure -0.46%, RB TD luck -0.36%).
  By games: 1-4 -1.22%, 5-9 -1.11%, 10+ -0.31%. Every season -0.57..-1.68%.
- TD SHARE of realized points alone (weekly-DB predictor, no pbp) is a
  weaker twin: -0.77% at k=.6 - fallback if pbp ever goes dark.
- Does NOT explain the aDOT/xTD-level tilt (low-xTD/g receivers still 1.14
  after the correction) - that level puzzle stays open.
- SHIPPED: engine `tdLuckAdj` generalised - WR/TE read `SIM_REC_TDLUCK_2026`
  with `TDLUCK_K_REC = 1.0` x rec_td value (RB unchanged: SIM_RB_TDLUCK_2026,
  k .75); same additive-after-chain, x availability, floor 0 placement; kill
  `window.SIM_TD_LUCK_REC = false` (SIM_TD_LUCK = false kills both). Data:
  pull_pace_tracker.py `build_rec_tdluck_2026()` (XTD_REC_NONEZ / XTD_REC_EZ
  constants) appended to data/sim_routes.js nightly. Smoke W2 half-PPR
  (182 WR/TE mapped after W1): 171 move, 0 RB/QB/K move on the REC switch,
  0 zeroed move, master kill verified; Coker 2 TD on .29 xTD -1.71
  (10.62 -> 8.91), Golden 0 on .90 +0.90, LaPorta 0 on .78 +0.78; formula
  exact. Backups engine.js / pull_pace_tracker.py .bak_pre_wrtdluck_20260914.

## QB passing-TD luck (backtest_qb_tdluck.py) - SHIPPED 2026-09-14 (passing only)

Jack: "backtest the QB passing-TD luck next" - last member of the TD-luck
family. xPassTD = sum over his targeted attempts of the receiver table
(yardline x end-zone-throw; throwaways 0); xRushTD from a QB-specific rush
table (sneaks at the 1 convert 62% vs RB 54%). 2,554 QB player-weeks
2019-25, base = P=5 x Vegas .25 x in-season QB FPA, LOYO. Log:
qb_tdluck_backtest.log.

- PASS luck: unlucky tercile actual/shipped 1.097, lucky 0.991; corr +.08.
  Additive + k x 4 x luck x g/(P+g): **LOYO -0.44% (5/7), k=.5, folds pick
  .5-.75**. By games 1-4 / 5-9 / 10+: -0.46 / -0.89 / -0.41%. 2020 hurt
  (+1.1%), 2021 flat, the other five -0.5..-2.1%.
- RUSH luck: nothing (+0.02%, 3/7) - QB rushing TDs are not luck in this
  sense (designed goal-line usage is the identity). Excluded.
- Combined pass+rush -0.31% (rush drags it). Centering per season with
  hindsight -0.45%; centering on the LIVE season-to-date league mean -0.34%
  -> shipped UNCENTERED, same form as RB and WR/TE.
- SHIPPED: `tdLuckAdj` QB branch, `TDLUCK_K_QB = 0.5` x pass_td value,
  reads `SIM_QB_TDLUCK_2026` (pull_pace_tracker.py `build_qb_tdluck_2026()`,
  nightly into data/sim_routes.js); kill `window.SIM_TD_LUCK_QB = false`
  (SIM_TD_LUCK kills all four). Smoke W2 half-PPR (34 QBs after W1): 29
  move, 0 non-QB, 0 zeroed, master kill OK, formula exact; Lawrence 4 TD on
  1.39 xTD -0.87 (18.11 -> 17.24), Mayfield 0 on .85 +0.28; the additive term is now scaled by min(1, iA) - iA carries the next-man-up boost (Rush x210) which had zeroed him. Backups
  engine.js / pull_pace_tracker.py .bak_pre_qbtdluck_20260914.

TD-luck family status: RB k .75 (-0.36%), WR/TE k 1.0 (-0.93%), QB pass
k .5 (-0.44%) - all additive after the chain, x availability, floor 0.
Watch the weekly tuner's tdMult (league-level TD multiplier) for drift now
that per-player luck sits under it.

## Morning schedule retime (2026-09-15)

Jack: run the checks before he gets on. Constraint found: nflverse publishes
the play-by-play containing Monday night's game at ~06:20 ET Tuesday (observed
2026-09-15 10:20 GMT), Sleeper finals import at 00:45 / Tue 01:45, weekly
projection sources keep updating through Tuesday morning. New times:
`MFF Sim Lab Daily` 06:45 (was 09:45; wake-to-run ON), `MFF Weekly Stats
Tuesday` 07:00 (was 08:30; already wake-to-run), Claude drift check 07:15
(was 09:30; read-only, no shell). Left alone: 08:00 betting pull, 09:00
consensus/weekly projections (sources still updating earlier), 10:00 export.
Watch the 06:45 refresh for two or three Tuesdays - if nflverse is late, the
Tuesday chain's own update_simlab.bat call (~07:05) is the safety net.

## NOTES tab - TD-luck leaderboard + per-game notes sheet (2026-09-15)

Jack: "build the LUCK leaderboard and per-game notes sheet" (video prep).
app.js `renderNotesTab()`, pane `#pane-notes` (tab after ZONES). No new data
files - reads the shipped luck maps in sim_routes.js, pace_2026.js,
sim_weather.js, sleeper_meta.js (CB1 / OL), sim_2026.js (FPA), zones_2026.js.

- LEADERBOARD: per position, DUE UP (unlucky, luck > 0) and DUE DOWN
  (lucky, luck < 0) top 8, min touches QB 30 / RB 10 / WR-TE 8; columns G,
  touches, xTD, TD, luck/g and ADJ = engine `tdLuckAdj(p, sc)` = the points
  the layer adds to THIS week's mean (grows with g/(P+g)).
- GAME SHEET (week + game selectors, "All games" for the full slate): line,
  spread, implied totals, weather (+ whether a wind dock is live), per side
  pace drift vs baseline, opp FPA by position vs league, opp pass-rush proxy
  vs league (soft = QB boost live), opp CB1 name/status, own OL starters
  out; every player of both teams with PROJ (effMean), model (jsMean),
  market (propMean) and WHY chips computed from the same engine functions
  weeklyProjection uses (injAdj OUT/docked/role boost, tdLuckAdj x min(1,iA),
  weatherMult, pressureMult, cbShadowMult, cb1OutBoost, olOutDock, snapMult,
  routeMult, market-vs-model gap >= 1.5) plus the ZONES read; then both
  defenses' zone cards.
- PLAIN TEXT: the whole sheet as text in a textarea; COPY NOTES copies it
  (clipboard API with execCommand fallback).
Intel only. Backups app.js/index.html .bak_pre_notes_20260915.

## Kicker FG-distance luck (backtest_k_fgluck.py) - NOT A LAYER, K section in NOTES 2026-09-15

Jack: "backtest the kicker FG-distance luck next". Kicker weekly points
rebuilt from pbp (FG 3/4/5 by distance, miss -1, XP +1/-1); xPts per attempt
= league make rate by distance (<30 .979 / 30-39 .932 / 40-49 .784 / 50-54
.712 / 55+ .576, XP .946) x points - miss. Base = P=5 blend of the kicker's
prior-season pts/g toward season-to-date x Vegas (K e=.50); 3,291 kicker-
weeks 2019-25, LOYO. Log: k_fgluck_backtest.log.

- GATE: accuracy over expected does NOT persist - YoY r +.09, early->late
  +.13. FG attempts/game YoY r +.05. Kicker points are team + luck.
- Luck on the realized half: + .75 x luck x g/(P+g) LOYO -0.98% (7/7).
  Unlucky tercile actual/base 1.036, lucky 0.919.
- BUT the realized half itself is the problem: prior strength P=12 beats
  P=5 (-1.11%, 6/7), and a LEAGUE-mean prior with P=40 beats everything
  (-3.15%, 7/7, picks 40 every fold) - a kicker's own prior season and his
  season-to-date barely carry information; luck on top of P=12 adds only
  -0.21%.
- LIVE RELEVANCE: none as a layer. K is not in weekly_stats_active, so
  SIM_2026 has no kicker rows and jsBasePg returns pure Clay; the live K
  mean = Clay fgm/xpm x tuner kLevel x Vegas x kicking-points market. There
  is no realized half to correct, and the backtest says there should not be
  one (or a heavily shrunk, league-anchored one at most). Do NOT add a K
  realized-PPG blend at P=5.
- SHIPPED AS INTEL: pull_pace_tracker.py `build_k_luck_2026()` ->
  `SIM_K_LUCK_2026` {norm: {name, xpts, pts, g, att, xp}} in sim_routes.js
  (rates baked as K_FG_RATE / K_XP_RATE); NOTES tab leaderboard gets a K
  section (DUE UP = missed kicks the distances say he makes, DUE DOWN =
  the reverse; threshold +-0.5 pts/g, >= 4 attempts) with the persistence
  caveat printed under it, and K lines in the COPY NOTES text. Backups
  pull_pace_tracker.py / app.js .bak_pre_kluck_20260915.

## DST TD regression (backtest_dst_regression.py) - REJECTED, Vegas-only DST mean confirmed 2026-09-15

Jack: "backtest the DST TD regression next" - last of the luck family. DST
weekly points rebuilt from pbp (sack 1, INT/FR 2, def+return TD 6, safety/
block 2, PA buckets) and split into components; shipped = dstWeeklyMean
16.2 - 0.436 x oppImplied (Vegas only). 3,518 team-weeks 2019-25, LOYO.
Log: dst_regression_backtest.log.

- Persistence (early->late / YoY): PA .22/.28, sacks .21/.21, turnovers
  .09/.20, TDs .06/.11, misc 0, total .22/.30. TDs are noise, as the D/ST
  research said; even the sticky parts are weak.
- NO realized component adds information over the Vegas-only mean: PA
  +0.11% worse, sacks +0.08%, turnovers -0.00%, TDs +0.01%, misc +0.03%
  (best k = 0 or a hair above, no year pattern).
- Realized-PPG blend at ANY strength is worse (P=1000 ~ shipped picked in
  every fold; P=5 is +5.8% worse). Replacing TD points by the league rate
  helps only relative to that blend (c: -0.38% at P=12) - i.e. TD regression
  is real but the correct amount of realized DST history to use is zero.
- NOT SHIPPED. The engine's DST mean stays opponent-implied-total only (+
  tuner dstShift). Do not add a DST realized half.
- INTEL: pull_pace_tracker.py `build_dst_luck_2026()` -> `SIM_DST_LUCK_2026`
  {TEAM: {g, pts, td, sack, to, pa, misc}}; NOTES leaderboard "DST - RIDING
  TDs" table (TD pts/g >= 3 vs league .73) with the noise caveat + a COPY
  NOTES line. Backups pull_pace_tracker.py / app.js .bak_pre_dstluck_20260915.

LUCK FAMILY - FINAL: shipped RB k .75 (-0.36%), WR/TE k 1.0 (-0.93%), QB
pass k .5 (-0.44%); intel-only K (accuracy = luck, own history ~worthless)
and DST (TDs = noise, Vegas-only mean is right); QB rush luck flat.

## Luck-layer live grading + morning NOTES export (2026-09-15)

Jack: "grade the luck layers live, not just in backtest" and "write the notes
sheet to a file every morning".

- **Live grading.** weeklyProjection now returns `luckAdj`; simWeek rows carry
  `luck` (TD-luck points inside jsProj); both lock writers (export_site_proj.js
  auto-lock, app.js LOCK) store `luck` per row. `luck_scorecard.py --week N`
  (added to the weekly_scorecard.py script list -> scorecards/wN.log) prints
  per position and cumulatively: n rows the layer moved (|luck| >= .05),
  MAE of jsMean vs jsMean-minus-luck, MAE of the shipped mean vs shipped with
  (1-w) x luck removed (w = tun.wa, else .70 with a propMean, else 0), win
  share, delta (negative = layer helped). W1 rows predate the layers and
  report as not instrumented; first real read = W2 (Tue 09-22 chain).
  Backtest expectations: RB -0.36% / WR-TE -0.93% / QB -0.44% MSE.
- **Morning notes file.** `export_notes.js` = headless twin of the NOTES tab
  (Playwright chromium from the site repo's tests/node_modules + a local
  static server over E:\MyFantasyFootball; Windows gotcha: path guard must
  compare path.resolve'd paths). Waits for the injury layer to arm, selects
  "All games", saves #nt-text to notes/notes_w<N>_half.txt + notes/
  notes_latest.txt (~39k chars / 16 games, ~1s). Hooked into update_simlab.bat
  after pull_pace_tracker.py (06:45 daily, non-fatal), so the sheet exists
  before Jack's morning; notes/ deploys with hosting ->
  https://jb-simlab-2026.web.app/notes/notes_latest.txt. Flags:
  --week N, --scoring half|ppr|std.
Backups engine.js / app.js / export_site_proj.js .bak_pre_luckgrade_20260915.

## Variance by TD-heaviness (backtest_sigma_tdshare.py) - REJECTED 2026-09-15

Does a player's scoring mix (prior-season TD share of points; receptions per
point as the mirror) predict weekly dispersion beyond the engine's sigma? 15,106
RB/WR/TE player-weeks 2019-25, gamma(mean = P=5 blend x Vegas, sd = engine
total width), graded by closed-form gamma CRPS + p10-p90 coverage, LOYO.
Log: sigma_tdshare_backtest.log.

- corr(TD share, |relative residual|) RB -.05 / WR +.03 / TE +.03 - nothing;
  the engine sigma already correlates with TD share (WR +.20, TE +.26)
  because TD-heavy players have higher historical weekly CV.
- sigma x (1 + e x tdShare_z): CRPS worse at every e, 0/7. Rec-per-point
  version: 0/7. Flat width x0.95: -0.05% (5/7) - the engine width is
  already about right (coverage 68-80% across terciles, tails symmetric).
- NOT SHIPPED. Scoring mix is not a variance signal once historical CV is in.

## Receiver yardage / catch luck (backtest_yds_luck.py) - REJECTED 2026-09-15

Does yardage or catch "luck" regress like TD luck? xYds and catch rate per
target by air-yards bucket (pooled 2018-25); luck = (expected - actual)/g
season-to-date, half-PPR 0.1/yd and 0.5/rec, tested ON TOP of the shipped
WR/TE TD-luck term. 10,592 WR/TE player-weeks 2019-25, LOYO. Log:
yds_luck_backtest.log.

- GATE says why it fails: yards over expected per target persists YoY at
  r +.34 and catch rate over expected at +.32 - those are SKILLS (YAC,
  hands), unlike TD over expected at +.09 (luck). Skills don't regress.
- Terciles flat (WR 1.02 / 1.05 / 1.06 - all under-projection level, no
  slope); sweeps worse at every k for yards, catches and combined, 0/7;
  per position 0/7; centered per season -0.01%.
- NOT SHIPPED. The luck family is exactly the TD family: TD conversion is
  luck, yardage and catch efficiency are talent already embedded in PPG.

## Site player-card TD LUCK / FG LUCK box (2026-09-15)

Jack: "do item 5 in a worktree". export_site_proj.js now adds `luck` to the
SIM_PROJ_2026 payload: `luck[name] = [pos, expected, actual, games,
adjThisWeekHalf|null]` - RB/WR/TE/QB from the SIM_*_TDLUCK_2026 maps with
E.tdLuckAdj(p, half) (the points the layer adds this week), kickers from
SIM_K_LUCK_2026 with adj null (intel). Site (repo branch
worktree-worktree-card-luck-chip, commit f0eaab8, ?v=2026-09-15a):
`_simLuckRow` / `_simLuckBoxHtml` in app.js, box under WEATHER in
buildWeeklyCardView when |adj| >= 0.1 (K: |luck| >= 0.5 pts/g); tooltip says
the regression is already priced in. Site picks it up once the branch is
merged AND the exporter's next scheduled run writes the luck map (the extra
key is ignored by the old app.js, so order does not matter). Backup
export_site_proj.js.bak_pre_cardluck_20260915.

## Expected fantasy points (xFP) for the site card (2026-09-15)

Jack: "maybe we should create an expected fantasy points to remove luck" ->
"use the standard definition" after reviewing PFF / Fantasy Points Data /
ESPN / Open Source Football: every target, carry and attempt valued at what
the AVERAGE player produces from that spot, summed; FPOE = actual - xFP.

- pull_pace_tracker.py `build_xfp_2026()` -> `SIM_XFP_2026` {norm: {pos, w:
  {wk: components}}} in sim_routes.js. Tables pooled nflverse pbp 2018-25:
  targets by air-yards bucket (<0/0-4/5-9/10-14/15-19/20-29/30+): catch rate
  .837/.755/.703/.589/.547/.416/.302, yards 4.9/5.4/6.8/9.0/11.4/11.9/13.5;
  TD by yardline x end-zone throw (the receiver xTD table); carries by yardline
  (<=5/6-10/11-20/21-40/41+): RB-group 1.10/2.88/3.82/4.45/4.75, QB
  1.07/3.22/4.05/4.48/4.77; rush TD by yardline (RB table; QB own table).
  QB attempts: targeted attempts use the target tables, throwaways 0.
  Components: RB/WR/TE [tg, xrec, xrecyd, xrectd, car, xruyd, xrutd]; QB
  [att, xpyd, xptd, car, xruyd, xrutd]. Fumbles / INTs ignored (standard).
- export_site_proj.js payload `xfp[name][wk]` (board players; 287 after W1)
  next to `luck` (which also carries [5] = weekly xtd/td for the TD box).
  Header comment must stay brace-free (indexOf('{') readers).
- Site (branch worktree-worktree-card-luck-chip, ?v=2026-09-15c): app.js
  `_xfpRow` / `_xfpFor` / `_xfpCell` + `_XFP_HDR`; xFP column right after
  FPTS on the 2026 game log (QB/RB/WR/TE builder buildWeeklyTable), scored in
  the viewer's format (rec .5/1/0, 0.1/yd, TD 6, pass TD 4, 0.04/pass yd);
  cell colour: green = scored UNDER expected (due up), red = over; tooltip
  splits FPOE into TD luck (regresses, YoY r .09) and yards/catches (skill,
  r .34/.32); totals row carries season xFP with the same split.
  Coker W1: 29.8 actual vs 12.2 xFP = +17.6 (TD +10.3, yards/catches +7.4).
Backups pull_pace_tracker.py .bak_pre_xfp_20260915 / .bak_pre_xfpstd_20260915.

## xFP/g + FPOE/g columns in the NOTES game sheet (2026-09-15)

Jack: "add xFP to the NOTES sheet". app.js `ntXfp(p, sc)`: season-to-date
expected fantasy points per game from SIM_XFP_2026 components scored in the
sheet's format, and FPOE/g = actual PPG (SIM_2026 ppg re-scored like
jsBasePg) minus xFP/g. Two columns after Market (green FPOE <= -1.5 = under
expected / due up, red >= +1.5) and " · xFP 22.2/g (+13.5 over expected)" in
the COPY NOTES text and the 06:45 notes file. Backup app.js
.bak_pre_notesxfp_20260915.

## xFP leaderboard in NOTES (2026-09-15)

Jack: "add the xFP leaderboard to NOTES". Below the TD-luck / K / DST tables:
per position UNDER EXPECTED (FPOE/g <= -1.5, scoring below usage = due up)
and OVER EXPECTED (>= +1.5) top 8 with PPG, xFP/g, FPOE/g and the split into
TD part (from the TD-luck maps, regresses) and skill part (yards/catches,
mostly repeats). Text lines "XFP UNDER/OVER <pos>: ..." in COPY NOTES and
the 06:45 file. W1 read: OVER RB Henry +17.5 (TD +11.5), WR Coker +17.6 (TD
+10.2); UNDER WR Metcalf -9.0 (TD -2.1), Golden -6.8 (TD -5.4). Backup app.js
.bak_pre_xfpboard_20260915.

## Game-context backtests (rest / return / garbage time / precipitation) - 2026-09-15

Jack: "lets do it" - four backtests on a shared harness (`bt_common.py`:
iter_samples = P=5 blend x Vegas(pos) x in-season FPA = shipped; NOTE the
harness does NOT include the wind dock or CB/OL/pressure layers). 17,657
QB/RB/WR/TE player-weeks 2019-25, LOYO. Nothing wired yet - engine changes
wait for the Week 2 live grades (Tue 09-22).

**1. Rest / schedule (backtest_rest_context.py) - REJECTED.** Short week,
extra rest, off bye, opponent off bye / short, 3rd straight road game, West
team at 1pm ET, East team late out West, primetime: pooled multipliers all
within +-0.02% (0-5/7). Per-position scatter (TE primetime x1.06 -0.41% 6/7,
WR off-bye x0.91 -0.06%) is the multiple-comparisons tax across 9 flags x 4
positions - not shippable. Vegas prices the calendar. Log: rest_context_backtest.log.

**2. First game back (backtest_return_game.py) - PASSED (rare-event dock,
same class as CB1-out / OL-out).** Return game = first game with snaps after
>= 2 consecutive missed team games (nflverse snap counts; player had played
earlier that season). 425 return rows (2.4%), 142 after >= 4 missed.
- Snap share in the return game = 88% of the player's own prior median; 38%
  of returns play under 80% of it.
- actual / shipped: return game 1 0.878 (QB .858 RB .842 WR .865 TE 1.063)
  vs 1.054 on all other rows (~ -17% relative); after >= 4 missed 0.835 (WR
  .725); return game 2 0.964 (mostly recovered).
- LOYO: x0.85 on return rows -0.09% (5/7, picks .85-.90); >= 4 missed x0.80
  -0.06% (6/7); game 2 nothing. Per position: QB x0.85 -0.16% (4/7), RB x0.80
  -0.11% (4/7), WR x0.85 -0.05% (5/7), TE nothing (0/7). Small pooled % because
  the event is rare; on the flagged rows it is a ~15% correction.
- SHIP PLAN (after W2 grades): `returnDock(p, wk)` in engine.js from
  SIM_SNAPS_2026 weeks vs the team's game weeks: >= 2 consecutive missed team
  games immediately before wk and an earlier played game -> x0.85 (>= 4 missed
  x0.80), QB/RB/WR only, second game back untouched, kill switch
  `window.SIM_RETURN_DOCK`. Also a NOTES chip ("1st game back, 3 missed").
  Log: return_game_backtest.log.

**3. Garbage time (backtest_garbage_time.py) - REJECTED.** 4Q |diff|>=17
(6.1% of all fantasy points) or 2H |diff|>=21. Share persistence YoY .12 /
early->late .13 (noise), but removing garbage points from the realized half
is WORSE at every k (0/7), all positions; centered +0.00%. Garbage-time points
are as predictive as any other points. Log: garbage_time_backtest.log.

**4. Precipitation / cold (backtest_precip.py) - MARGINAL, needs a re-test on
top of the wind dock.** pbp weather strings, 12,087 outdoor player-weeks
parsed: rain 763, snow 175, cold (<=32F) 692, freezing 212.
- Rain: QB 0.902 / WR 0.890 after Vegas, identical without Vegas -> the line
  does NOT price rain (same as wind). RB 1.005 (unaffected, like wind). LOYO
  rain x0.91 pooled -0.06% (5/7); QB x0.88 -0.20% (4/7), WR x0.88 -0.09%
  (4/7), TE +0.05%, RB 0.
- Snow: nothing (n small, RB 1.25 = noise). Cold / freezing: nothing (0/7).
- CAVEAT: rainy games are often windy and the shipped weatherMult already
  docks wind 10+/15+; this harness has no wind dock, so part of the rain
  effect is already live. Re-run with weatherMult in the base before deciding;
  if it survives, QB/WR x0.93 on rain (not RB/TE) is the shape. Data live:
  Open-Meteo `pop` (precip probability) is already in sim_weather.js.
  Log: precip_backtest.log.

## Player x defense pairing history (backtest_pairing_history.py) - REJECTED 2026-09-15

Jack: "find specific players that do great or horrible against specific
defenses". Walk-forward residual r = actual/shipped - 1 per player-week;
predictors from EARLIER games only: mean residual of prior meetings vs THIS
defense (8,643 rows with >= 1 prior meeting, 4,599 with >= 2), the same-season
rematch (game 1 -> game 2, 2,384), and as control the player's recent residual
vs OTHER defenses. 17,657 player-weeks 2019-25. Log: pairing_history_backtest.log.

- Pairing history predicts NOTHING: r = -0.000 (n>=1), +0.020 (n>=2),
  rematch +0.012; pairing excess over general form -0.018. Terciles flat:
  players who "flopped before" vs a defense run 1.032 now, "crushed before"
  1.050 - both the ordinary under-projection level. LOYO worse at every k
  (0/7) for pairing, excess and rematch.
- The CONTROL is the only signal: recent form vs other defenses r +.054,
  x(1 + .1 x form) -0.09% (5/7) - that is player momentum the P=5 blend only
  partly carries, not a matchup effect. Small; not shipped.
- Home/away: home 1.061 vs away 1.035 after Vegas (~2.5% relative); home
  x1.04 -0.07% (4/7). Marginal, below bar; Vegas spread carries most of it.
- CONCLUSION for the "alignments / strengths vs weaknesses" question: at the
  player x defense level there is no season-long memory to exploit. What
  survives testing is (1) defense position-level points allowed (shipped FPA
  layer, e=.25), (2) elite/CB1 corner presence (shipped CB layers), (3) the
  player's own profile (target depth mix is sticky - ZONES intel), and (4)
  luck regression (TD family). Defense-by-zone efficiency, man/zone, pressure
  docks, pairing history and rematches all graded as noise. True alignment
  data (who lined up where, coverage type) is FTN/participation and only
  arrives after the season - a 2026 in-season alignment layer is not
  possible; a post-season research pass could use PFF slot/wide snaps
  (weekly, available now) vs defense slot/wide allowed if participation lands.

## Run direction matchup (backtest_run_direction.py) - REJECTED as a layer 2026-09-15

Jack: "where each defense gets targeted or what type of runs outside/inside".
nflverse pbp run_location (left/middle/right) + run_gap (end = edge vs
interior) on ~95% of designed runs, NIGHTLY. 102k RB-group carries 2018-25;
per defense yds/carry (capped -10..40) and success (>= 4 yds) ratios by zone
vs league, shrunk K=60; funnel = share of carries faced by zone; RB mix
season-to-date shrunk toward prior season (K=40). Matchup M = sum w_z r_z /
r_all on 3,802 RB player-weeks (defense >= 60 carries faced), LOYO.
Log: run_direction_backtest.log.

- Persistence: defense per-direction EFFICIENCY residual is noise (early->late
  r .11 left / .16 middle / -.03 right / .09 edge / .10 interior; YoY <= .17),
  while overall run defense persists (.34 / .28) - the run-game twin of the
  passing-zone finding. Direction FUNNELS persist (left .41, middle .61,
  right .41, edge/interior .52) and RB direction mix persists (.42-.60).
- Every matchup multiplier flat or worse: side/lane x yards 0/7, x success
  0/7, funnels 0/7 and 4/7 at +0.04%; quintiles have no slope.
- NOT SHIPPED. Same conclusion as zones: identities exist (where a defense
  gets run at, where a back runs), no exploitable interaction. INTEL value
  only ("KC gets run at left edge 30% of the time, lg 22%"; "Henry: 46%
  interior right") - candidate RUN LANES card for the ZONES tab.

## Scheme & alignment intel (build_scheme.py, PFF weekly facets) - SHIPPED 2026-09-15

Jack: "we can definitely find alignments and where each defense gets targeted
or what type of runs outside/inside zone etc somewhere maybe pff" -> "do it".
PFF Premium serves its scheme facets WEEKLY in-season (the nflverse
participation "postseason only" blocker does not apply), so:

- Repo `scripts/pull_pff_weekly.py` (daily 06:15 route_pct_daily.ps1) now
  saves nine facet CSVs per played week next to the receiving file,
  `pbp_cache/pff/weekly/pff_<facet>_<season>_w<N>.csv`: receiving_scheme
  (man/zone), receiving_depth, receiving_concept (screen/slot),
  rushing_summary (gap/zone, yco, breakaway), rushing_direction (lanes
  LE LT LG ML MR RG RT RE; JS-*/EA-* folded into the edges, QB* ignored),
  passing_pressure (blitz/pressure splits), defense_summary (alignment snaps,
  grades), defense_coverage_scheme (man/zone snaps), defense_pass_rush (win
  rate). Nested JSON is flattened; `--no-facets` skips them; kept weeks are
  backfilled. rushing/gap_zone, passing/time_in_pocket, defense/run_defense,
  defense/slot_coverage, blocking/* are 404 in-season.
- `build_scheme.py` (called from pull_pace_tracker.build(), 06:45) ->
  `data/scheme_2026.js` (`SIM_SCHEME_2026`): per DEFENSE man rate, blitz %
  and pressure % (from the QBs it faced via the nflverse pbp opponent map),
  rusher win rate, safety-in-box, DB/LB rush share, missed-tackle rate, run D
  faced (ypc, after contact, gap share, edge share, explosive, MTF, per-lane
  att/yds; QB carries excluded), slot share of rec yds, PFF grades; per
  OFFENSE gap/zone + lanes + man seen + screens + blitz/pressure faced; per
  PLAYER: receivers man/zone routes-targets-yards-rec-TD + slot/wide/inline
  snaps + screen; rushers gap/zone/yco/explosive/MTF/breakaway/lanes/elusive;
  QBs blitz/pressure/no-pressure dropbacks, yards, TD, INT, sacks, TWP and
  PFF grades. League means in `lg`. PFF codes ARZ/BLT/CLV/HST/LA mapped.
- app.js: ZONES game view gets a "Scheme & alignment (PFF)" section (defense
  scheme card with value / vs lg / rank + "gets run at" lane line, opposing
  offense profiles table with auto READS: man-/zone-beater, slot, screen guy,
  gap/power vs zone back, bounces outside, contact balance, makes people
  miss, QB falls apart / holds up under pressure, punishes / struggles vs
  blitz, GOOD SPOT / TOUGH SPOT vs the opponent's man rate, blitz rate,
  pressure, missed tackles, heavy boxes). League view gets a sortable
  "Defense scheme" table. NOTES team block gets "<opp> D scheme" + "<team> O
  style" lines and the read column appends the scheme read (notes_latest.txt
  carries them). Backups app.js/index.html .bak_pre_scheme_20260915.
- Honest labels: man rate / blitz / lanes / run style are identities that
  persist; per-lane and per-zone EFFICIENCY, per-player man/zone splits are
  noise as layers (backtest_run_direction.py, backtest_target_area.py,
  backtest_man_zone.py) - INTEL ONLY, nothing moves a projection.

## Scheme prior season + reliability (2026-09-15)

Jack: "get the info from last season and see if there are any similarities to
week 1 because then that team defense or offensive players will be somewhat
reliable". PFF serves full-season totals without a week param, but those have
no opponent dimension, so the puller instead fetches the PRIOR season's weekly
facets once (pull_prior_season: weeks 1-18 x 9 facets + receiving/summary saved
as receiving_summary_<yr>; 180 files, ~2 min) and build_scheme.py aggregates
2025 with the same code (defPrior/offPrior/recPrior/rbPrior/qbPrior/lgPrior)
plus `persist` = league-wide r of each defense metric, 2026-to-date vs 2025.

- W1 2026 vs 2025 (32 D): blitz .64, DB/LB rush share .88, man .38, edge-run
  share .39, gap share .33, MTF/att faced .32, S-in-box .25; pressure -.03,
  rusher win .03, ypc -.03, yco -.06, every PFF grade ~0. One game of results is
  noise; one game of scheme CHOICES already says who a defense is.
- app.js: defense card shows the 2025 value + a check / flip / ~ agreement
  cell per metric and an `r` tag (green >= .30) on each metric name; header
  "RELIABLE / MIXED / NEW LOOK vs 2025 (k/n)" over the identity metrics
  (SC_IDENTITY: man, blitz, dbRush, sBox, prwr, gap/edge/MTF faced). League
  table gets a "vs 2025" column + the persistence line. Player profiles are
  BLENDED (2026 counts + 2025 scaled to <= 200 routes / 100 carries / 200
  dropbacks, SC_K_*), reads tag "(2025 too)" / "(new vs 2025)". NOTES defense
  line carries the reliability tag and 2025 values.
- scheme backtest: backtest_scheme.py (PFF weekly facets 2019-25 pulled once
  via the scratch history puller) grades every card interaction LOYO - see the
  next section for the verdicts.

## Coaches / playcallers in the scheme cards (2026-09-15)

Jack: "make sure we are aware of coaches and playcallers at this time and we
can maybe assign tendencies or strengths/weakness potentially offensively and
defensively".

- pull_coaches.py -> pbp_cache/coaches.json: HC / OC / DC per team-season
  2018-2026 from Pro-Football-Reference team pages via Selenium. PFR fronts a
  JS challenge (~28 KB page) that beats headless Chrome, a fake user-agent, and
  an immediate page_source read - the window stays VISIBLE (own temp profile,
  no collision with the PFF profile), no UA override, and the puller polls up
  to 20 s for "Coordinator" in the HTML. 3.5 s between pages (PFR 429s faster).
  Re-run after in-season firings (only missing team-seasons are fetched;
  --years 2026 --force to refresh the current staffs).
- Playcaller = OC / DC unless sim_lab/coach_overrides.json says the HC calls
  it: {"2026": {"LAR": {"oc_play": "Sean McVay"}}}. PFR does not carry this;
  Jack maintains the file (HC playcallers are common on offense).
- build_scheme.py: the DEFENSE prior travels with the defensive playcaller
  (coach_prior): same DC as last season -> team prior; new DC -> his most
  recent defense up to 3 seasons back (priorSrc mode "coach", from/season);
  no history -> team prior flagged weak. Same for the OFFENSE prior via the
  OC. defPriorTeam/offPriorTeam keep the plain franchise prior; coaches =
  current staff + last year's playcallers; coachHist = every season each
  playcaller has in the data (man/blitz/pressure/S-box/gap/edge...);
  persistSplit = W-vs-prior r for same-DC vs new-DC teams.
- app.js: defense card header line "DC <name> (3rd yr here)" / "(new; prior =
  DEN 2025 under him, replaced X)" / "(new, no playcalling history - prior =
  team 2025, weak)", the prior column is labelled with the source season, and
  a Tendencies line shows the playcaller's seasons side by side. Offense block
  gets the OC line + his history. League table: DC / playcaller column (new =
  red). NOTES: coach lines under each D scheme / O style line.
- backtest_scheme.py uses the same coach-aware defense priors and reports YoY
  persistence three ways: same-DC, new-DC vs the old team, new-DC vs HIS last
  defense - the evidence that tendencies travel with the coach.

## xFP accuracy backtest (backtest_xfp.py, 2026-09-15)

Jack: "how accurate is our xFP?" Rebuilt the site's xFP (same tables /
functions as build_xfp_2026) for 36k QB/RB/WR/TE player-weeks 2019-25 and
graded it. Log: xfp_backtest.log.
- Descriptive (weekly xFP vs actual, rows xFP >= 5): r .57-.68 (RB best,
  TE worst), MAE 3.6-4.8 pts/g, bias within +-0.12/g every position (level is
  calibrated; QB reads -1.5/g under full scoring because INTs are ignored by
  the standard definition). TD half r ~.46-.53 = the noise.
- Predictive vs actual PPG: xFP/g wins EARLY for RB/WR/TE (3 games: RB r
  .60 vs .54, WR .53 vs .52, TE .41 vs .41 ~tie), ties at 5 games, LOSES by
  8 games (skill efficiency accumulates). Best blend weight on xFP ~.6-.7 at
  3 games -> ~.3 by 8. QB: xFP worse at every horizon (w=0) - QB efficiency
  over expected is skill. Next-game r: identical within .01.
- YoY: FPOE/g persists r .23-.40 (skill), TD luck/g only .07-.15 -> the
  tooltip split (TD = regresses, yards/catches = repeats) is right.
- WR/TE carries use the RB rush-yards table and run 1.1-1.5x hot (jet
  sweeps); tiny component, left as is.
Verdict: a good USAGE stat, not a projection - do not feed it to the sims
(they already regress the TD half). Same conclusion as yds_luck_backtest.

## xFP variants backtest (backtest_xfp_variants.py, 2026-09-15)

Jack: "how else can we improve our xFP on games that already happened?"
Play-level harness, every table refit LEAVE-ONE-YEAR-OUT 2019-25 (V0 =
site tables refit honestly: r .623 vs .624 in-sample -> no overfit).
Cumulative variants: V1 receiver position, V2 + yardline bucket for
catch%/yards, V3 + nflfastR cp / xyac_mean_yardage per play, V4 + rush
context (scramble, distance, shotgun, goal-to-go TD), V5 + garbage-time /
2-min situation, V6 = expected INT (QB).
- Everything is within +-0.015 r. Only WR moves consistently: V3 +0.013
  weekly r, +0.014 rest-of-season r from 3 games, +0.012 YoY. RB/QB/TE flat
  (TE +-0.012 is noise, n=174 seasons). Position split, rush context and
  situation buckets add NOTHING.
- V6 xINT (by air-yards bucket) fixes the QB full-scoring bias -1.33/g ->
  +0.10/g; xINT/g 0.71 vs actual 0.70.
Reading: opportunity context is already ~all the signal a usage stat can
carry; the residual (weekly r ~.6) is TD/yardage outcome variance, which no
amount of pbp history removes without adding the player's own skill (= a
projection, which the sims are). Worth shipping if Jack wants: cp/xyac for
receivers (+ yardline fallback) and xINT for QB - both are columns already
in the nightly pbp. Log: xfp_variants_backtest.log.

## xFP upgrade SHIPPED: nflfastR cp/xYAC per target + QB expected INTs (2026-09-15)

Jack: "lets add them" (the two keepers from the variants backtest).
- pull_pace_tracker.py build_xfp_2026: each target's xrec = nflfastR `cp`,
  xrecyd = cp x (air_yards + xyac_mean_yardage) when both are present (~93%
  of targets; the rest, mostly goal-line throws, fall back to the air-yards
  bucket tables). QB xpyd uses the same per-target value. New QB component
  [6] = xint (XFP_INT by air-yards bucket, pooled 2018-25). RB/WR/TE arrays
  unchanged.
- export_site_proj.js: header comment only (payload passes the arrays).
- Sim Lab app.js ntXfp: QB xFP nets 1 x xint (SIM_2026 ppg = Sleeper fpts,
  INT -1) so NOTES FPOE/g is consistent.
- Site app.js (?v=2026-09-15g): _xfpFor QB subtracts 1 x c[6]; tooltip and
  season totals show "INTs +/-" as its own luck part for QBs; header gloss +
  rankings xFP button title reworded. Josh Allen W1: xFP 22.4, +13.3 over =
  TD +10.0, INTs +0.9, yards +2.4. Coker W1 unchanged at 12.2.
Old data (6-element QB rows) and old site code (ignores c[6]) are mutually
compatible, so deploy order doesn't matter. sim_routes.js rebuilt; the
10:00 / 20:15 export task ships the new components to data/sim_proj_2026.js.

## FPOE stability + rankings Luck tail (2026-09-15, follow-up)

Split-half r of per-game FPOE, first G games vs next G (same season, xFP/g
>= 5, 2019-25): G=4 QB .16 RB .13 WR .12 TE .14; G=8 QB .37 RB .36 WR .28
TE .10 (n=75). TD-luck half ~0 at G<=4, .14-.26 at 8; skill half .34-.45 at
8 for QB/RB. Spearman-Brown: FPOE reaches half-reliable at ~14 games (QB/RB),
~18 (WR) - i.e. not within a season. Both site xFP glosses now say so.
Site (?v=2026-09-15h): rankings xFP mode tail "TD Luck" -> "Luck" = TD luck
+ INT luck for QBs (_xfpAgg int/luck/luckg; sort + colour follow).

## Scheme matchup backtest (backtest_scheme.py) - 2026-09-15

Jack: "backtest the whole algo or look for correlation with everything we are
building in 2025 and even previous years" / "can we try to find any correlation".
PFF weekly facets 2018-2025 (scratch pull_pff_history.py, 1,430 files) ->
build_scheme.aggregate() walk-forward per week + prior season (defense K=4 gm,
player K=200 rt / 100 car / 200 db, the app's blend), coach-aware defense priors
from coaches.json. 17,657 QB/RB/WR/TE player-weeks 2019-25 on the shipped base
(bt_common), LOYO. Log scheme_backtest.log; verdicts + persistence + scan ship to
data/scheme_backtest.js (SIM_SCHEME_BT) and render at the bottom of the ZONES
league view. Ship bar <= -0.3% MSE with >= 5/7 years better.

- 31 interactions graded, NONE pass. Matchup families (coverage fit R1, lane fit
  B1, pressure fit Q1, GOOD/TOUGH SPOT flags, slot leak, yco/MTF flags, defense
  man/blitz/pressure levels): all within +-0.15%. Closest: D blitz rate -> RB
  -0.14% 6/7 (RBs a touch worse vs blitz-heavy D), D man rate -> RB -0.10% 4/7.
- Correlation scan (230/251/146/146 features + cross terms per position): the
  only |r| > .08 are QB EFFICIENCY LEVELS with a NEGATIVE sign - PFF pass grade
  under pressure r -.12, clean-pocket YPA -.09, no-blitz YPA -.11: QBs whose
  recent efficiency is high are OVER-projected (mean reversion), not a matchup.
  LOYO as (1 + k z): pGr -0.33% 4/7, nbYpa -0.23% 5/7, nYpa -0.23% 5/7 = "lean",
  one year short of the bar. WR/TE YPRR shows the same sign at r -.05/-.06
  (-0.10% 5/7 WR). CANDIDATE next study: QB efficiency mean-reversion layer
  (YPA / grade vs the QB's own multi-year level), analogous to the TD-luck
  family - NOT a scheme layer.
- Persistence (224 team-seasons): man early->late .73 / YoY .55, blitz .76/.60,
  DB-LB rush share .77/.53, S-in-box .67/.43, edge share faced .45/.44, rusher
  win .45/.40, pressure .42/.31; grades, missed tackles, slot yds, ypc, yco,
  explosive: .05-.3. Same-DC YoY beats new-DC YoY everywhere (man .71 vs .49,
  blitz .79 vs .54, edge faced .75 vs .37, slot yds .58 vs .12) - tendencies
  travel with the playcaller. "new DC vs HIS last D" needs the full coaches.json
  (first run had 2018-21 only; re-run after pull_coaches.py finishes).

- Coach split with the FULL coaches.json (rerun 13:55): same-DC YoY man .68 /
  blitz .76 / S-box .64 / DB-LB rush .64 (n=129); new-DC vs OLD TEAM .35 / .32
  / .15 / .36 (n=95); new-DC vs HIS LAST DEFENSE (n=21): blitz .67, DB-LB rush
  .59, edge faced .47, rusher win .34 - the pressure STRUCTURE travels with
  the coordinator; man rate does not (.17) and S-in-box barely (.22). So the
  coach-aware prior is right for blitz / rush-share / lanes and the cards say
  "weak" for a new DC's coverage lean.
- Conclusion (same as zones / lanes / pairings): the scheme data describes
  WHO a defense is and WHAT a player does - reliable enough to quote, and the
  coach-aware prior makes the Week-1 read trustworthy - but no scheme x player
  interaction moves a projection beyond the shipped base. Intel only.

## Out-flag guard: never zero before he is out (2026-09-15)

Jack: "make sure not to 0 anyone out before they are out or at least doubtful"
/ "maybe check who sleeper has 0s for". Tuesday's export had zeroed Murray,
Tua, Flowers, Henderson, McMillan and Grupe for Week 2 on Sleeper's
injury_status "Out" - a flag that lingers from Sunday's inactives (McMillan,
Grupe) or lands Monday before any Week-2 designation exists (Murray, Tua).

- refresh_data.py now appends `window.SIM_SLEEPER_WEEKLY` to sleeper_meta.js:
  Sleeper's OWN projection for the current week per player (repo
  data/weekly_projections.json 'h'; absent = Sleeper has him at 0).
- engine applyInSeasonInjuries: a Sleeper "Out" zeroes only when Sleeper's
  weekly projection is absent/0 too, or the NFL report (sim_practice.js,
  week-scoped) says Out; NFL Doubtful -> x0.5; otherwise x0.75
  `out-unconfirmed` (handled like Questionable + DNP: no prop anchor). IR /
  PUP / NFI / suspension still zero (multi-week by nature); Sleeper
  "Doubtful" still x0.5. Kill: SIM_INJ_LAYER=false as before. Backup
  engine.js.bak_pre_outguard_20260915.
- Result W2: Darnold, Stribling, Penix, McCarthy, Beck, Bagent, Sampson,
  Leonard, Ewers, Allar, Lane = zero (Sleeper agrees); Murray, Tua, Flowers,
  Henderson, McMillan, Grupe, Kamara, Najee Harris, Atwell, Tolbert ... =
  x0.75 unconfirmed. NOTES chip: "OUT flag unconfirmed (Sleeper still projects
  him) x0.75". The Wednesday/Thursday NFL report flips them either way.

## FP per route run base + ascending flag (backtest_fprr.py) - 2026-09-15

Jack: "young and ascending, only good reports, increasing snaps/targets/routes,
scoring a ton over a medium sample (Parker Washington) ... fantasy points per
route run" -> "lets do it but if a player isnt increasing their routes when
scoring lots per route then we can assume they will stay a part time player".
PFF weekly routes 2018-25 (pff_receiving_summary_<yr>_w<N>.csv), 10,611 WR/TE
player-weeks 2019-25 LOYO on the shipped base. Routes projected from ROUTES
ONLY (0.5 x last-3 + 0.5 x season/g); FP/RR = half-PPR rec pts / route,
shrunk to last season (K=150 routes) then the position prior (.269).
Log fprr_backtest.log; data/fprr_backtest.js (SIM_FPRR_BT) on the ZONES tab.

- FP/RR base as a REPLACEMENT is worse than the shipped base (MSE 37.99 vs
  36.92, corr .471 vs .492). As a blend: WR +0.01%, TE -0.45% 4/7 (w=.3),
  WR+TE -0.04%. Not shipped.
- Jack's rule confirmed and then some: actual/shipped by FP/RR tercile x route
  trend - LOW FP/RR + rising routes 1.20, low + flat 1.18; HIGH FP/RR 0.95 /
  0.98 / 0.99 (falling / flat / rising). Hot efficiency does not persist;
  the PPG blend already prices it and it regresses. Rising routes with LOW
  efficiency is where the model lags (volume arrives before points).
- ASCENDING flag (age <= 25, exp <= 3, 3-game route slope > +3 and target
  slope > +0.7, PPG > Clay): 474 rows at 1.093 actual/shipped, but the LOYO
  multiplier is flat (+0.01%, 3/7) - the flagged rows are too noisy for a
  fixed bump. "young + high FP/RR + flat routes" (the part-timer) 1.069 on 306
  rows, x1.06 -0.00% 5/7. Rising routes any age (1,329 rows) 1.066, +0.03%.
- LEVEL terms (shipped x (1 + k z)): FP/RR z with k = -0.04 -> WR -0.18% 6/7,
  TE -0.72% 4/7, WR+TE -0.28% 6/7 (one tick under the -0.3% bar). WITHOUT
  TDs (rec + yds per route): WR -0.09% 5/7, WR+TE -0.13% 6/7 -> about half of
  the efficiency-regression signal is the TD luck the engine already
  regresses (bt_common's base has no TD-luck term). Route slope / target
  slope as level terms: -0.02 to -0.05%, noise.
- Verdict: nothing ships. The one lead is the same efficiency-regression
  family the scheme scan found for QBs (hot YPA / grade over-projected);
  a unified "efficiency luck" study (QB clean-pocket YPA, WR/TE non-TD FP/RR,
  vs the player's own multi-year level) is the candidate that could pass.

## Shadow flags: REPORTS + ASCENDING (2026-09-15)

Intel only, logged so the Tuesday scorecard can grade them. engine.js
newsFlags(p, days) counts riser / faller / injury / role items for the player
in the last 10 days from data/sim_news.js (refresh_data.py copies the repo's
camp_news_2026.json, the cloud beat-report routine, 269 items with in-season
tags); ascendingFlag(p, wk) = age <= 25, exp <= 3, snapMult >= 1.05 and
routeMult >= 1.03. NOTES chips "REPORTS +2 riser (10d) - shadow" /
"ASCENDING (age 24, yr 2, snaps+routes up) - shadow" (blue; fallers red); lock
rows carry `rep` (riser minus faller) and `asc` (0/1) in both the exporter
and the app so score_week / luck_scorecard can split by flag. No multiplier.

## Blowout context for snap + route trends (2026-09-15)

Jack: "if a team is getting blown out or blowing out another team in the 4th
we dont penalize them". pull_pace_tracker.build_context_2026() ->
data/sim_context.js (SIM_GAMECTX_2026 = {TEAM: {wk: {pl, gp, db, gdb}}}:
offensive plays / dropbacks and the garbage subset, Q4 |margin| >= 17 or Q3
>= 28; W1 2026: 11 of 32 team-games had 6+ garbage plays, CLE 26 of 49).
engine ctxShare(): a blowout week's snap (or route) share is re-measured
against COMPETITIVE plays when the player's count fits inside them and is at
least 85% of them (a pulled starter: 42 of 42 competitive snaps, not 42 of
66), and the week's weight in snapMult / routeMult is scaled by its
competitive share. Never penalizes, never inflates a part-timer. NOTES chip
"blowout wk1: role read on competitive snaps". Kill: SIM_BLOWOUT_CTX=false.

## Clay-free SHADOW base in the Tuesday scorecard (2026-09-15)

Jack: "continuously improve our sims so we dont even need a clay projections
as a base next season". Clay's leverage is the P=5 prior in jsBasePg (5
games of evidence vs the player's own 2026 PPG - under half the blend by
week 5). weeklyProjection now also returns ncMean / ncSrc: the SAME blend
and chain with the prior = the player's own 3-yr weighted PPG
(player_weekly_sigma mean_ppg, half-PPR, rescaled to the sheet by the Clay
stat mix; needs >= 8 games of history) instead of Clay; no history ->
Clay prior flagged 'clay-fallback'. Sim rows carry ncProj/ncSrc, lock rows
(app + exporter) carry ncMean/ncSrc plus the shadow flags rep/asc, and
score_week.py grades "No-Clay shadow" next to SHIPPED / JS Weekly / Clay
stack, prints the fallback count and actual/shipped for the REPORTS and
ASCENDING flag rows. W2 sample: Jacobs 15.8 vs JS 9.4 (history says more),
Parker Washington 6.3 vs 8.9 (history drags an ascending player - the case
the ledger has to settle), Chase 13.6 vs 13.4, Allen 28.0 vs 26.3. Nothing
shipped changes; the season ledger decides.

- 14:20 follow-ups (Jack): (1) prior = 0.5 x 3-yr weighted PPG + 0.5 x LAST 8
  PLAYED GAMES (refresh_data players26 l8/l8g, 2024-26 tail, also for players
  without a 2026 game yet) - Parker Washington shadow 6.3 -> 9.0 (JS 8.9),
  Chase 12.2, Allen 25.8; ncSrc hist+l8 / l8 / hist / clay-fallback (132 of
  428 W2 rows still fall back = rookies + no history). (2) Sleeper
  injury_status "NA" (commissioner's exempt list / personal - Josh Jacobs)
  never matched Out/IR: engine zeroes NA for a 4-week window when Sleeper's
  weekly projection is also 0 (src 'na'), else x0.75 'na-unconfirmed'.
  Jacobs wk2-5 zero, exported + pushed.

## Defense availability (backtest_def_avail.py) - NOT SHIPPED as a layer, live INTEL 2026-09-15

Jack: "injuries ... how that impacts ... even on defense" -> "start on the defense
availability layer". Regular defenders found WALK-FORWARD from PFF weekly snap
shares 2018-25 (share >= .5 in >= 60% of prior team games, graded weeks 4+),
weighted by PFF unit grade above 55 (coverage / pass rush / run D / overall,
season-to-date blended with last season, 300-snap cap) x avg snap share.
Absence sets: realized (share < .2 - includes benchings), and KNOWN BEFORE LOCK
= final injury report Out/Doubtful (nflverse injuries_<yr>) OR weekly roster
status RES / PUP / EXE / SUS / NFI / INA (nflverse roster_weekly_<yr>, joined on
pff_id). The report alone missed IR players (31% of absences); the known set
covers 70-80% and almost never played anyway (0-4 a season). 17,657 QB/RB/WR/TE
player-weeks + 3,070 DST team-weeks, LOYO 2019-25 on bt_common's base (no CB1
boost in base, so coverage tests also run "beyond CB1"). 50 tests, NONE pass.
Log def_avail_backtest.log; data/def_avail_backtest.js on the ZONES tab.

- Direction is consistent: depleted defenses help RB / TE / QB, not WR. Known
  before lock, same position + week band: RB 2+ front-7 out 1.042 REL (n 295),
  3+ regulars out 1.052; TE 3+ out 1.10 (n 227), quality DB beyond CB1 1.057;
  QB quality DB beyond CB1 1.09 (n 73), 2+ DBs out 1.056. WR 0.98-0.99 across
  the board (the shipped CB1 boost is the WR piece; nothing beyond it).
- Best LOYO (known): RB x front-7 starters out +3%/starter -0.19% 6/7; TE x pass
  rush quality out -0.19% 5/7; TE x total quality out -0.18% 5/7; RB x total
  quality -0.15% 4/7. Flag multipliers flat (-0.08% to +0.21%). Realized-absence
  versions similar or worse (benchings dilute).
- DST (own defense): 3+ regulars known out -0.64 pts, heavy quality loss -1.36
  (n 23); additive LOYO best -0.25% 5/7 on realized, -0.10% on known. Not shipped.
- LIVE INTEL (refresh_data.py -> sleeper_meta.js SIM_DEF_AVAIL_2026): each team's
  regular defenders (PFF 2026 weeks + 2025 regulars on their current Sleeper team),
  grade, share, Sleeper status, NFL report status; NOTES team block line
  "<OPP> D availability: S Brian Branch (67, PUP) ... quality lost 1.2 [intel]"
  (confirmed = IR/PUP/NA/Sus or the current week's NFL report; Sleeper Out alone
  shown with "?"). Revisit as a layer only with a new angle (e.g. RB front-7 +
  TE combined, or in-season sample grows); the effects are real-looking but under
  the bar at +3-10% on a few hundred rows.

## Banged-up docks (backtest_banged_up.py) - CALIBRATED + SHIPPED 2026-09-15

Jack: "banged up playing or missing actual time" -> "start on the banged up layer
next". The 09-09 practice-report docks (Doubtful x0.5, Questionable + DNP x0.75,
Questionable + Limited/Full = nothing) were judgment calls, never backtested.
nflverse injuries_<yr> (final report status + latest practice) x snap_counts_<yr>,
2019-25, skill players averaging 40%+ of snaps. Log banged_up_backtest.log;
data/banged_up_backtest.js on the ZONES tab.

- PLAY RATE (the dominant factor, direct frequencies): Doubtful 1% (n 195),
  Q+DNP 48% (n 268; QB 26%, RB 41%, WR 54%), Q+LP 72% (n 1,105; QB 47% n 130),
  Q+FP 87% (n 264), no designation + DNP 81% (QB 33%), no designation + LP 97%,
  Out 0%.
- WHEN THEY PLAY (bt_common base, vs healthy same position + week band): snap
  share Q+FP .96 / Q+LP .92 / Q+DNP .90; production Q+FP .91 (n 197), Q+LP .88
  (n 596), Q+DNP .78 (n 110; x0.85 picked in 7/7 held-out years), soft-tissue
  Q+LP .82, no designation + DNP .86, + LP .94. LOYO pooled over 17,657 rows
  stays within -0.12% (rare flags dilute) - same situation as CB1-out / OL-out.
- TEAMMATES of players who played hurt: TE teammate x1.06 5/7 (-0.12%), RB
  same-group REL 1.06 (3/7), WR QB-hurt REL 1.07 (n 81); not shipped.
- SHIPPED (engine BANGED table, applyInSeasonInjuries putDock): mult = play x
  cond per class x position; play shrunk K=50 to the pooled rate, cond shrunk
  K=150 then shaved halfway (lines carry part of it):
    Doubtful  .01 QB / .01 RB / .02 WR / .01 TE          (was x0.50)
    Q + DNP   .38 / .39 / .46 / .44                       (was x0.75)
    Q + LP    .51 / .67 / .72 / .71                       (was none)
    Q + FP    .78 / .85 / .85 / .82                       (was none)
  Fires ONLY when the current week's NFL report carries the status (the Friday
  final report - the population measured); Sleeper Doubtful alone gets the
  near-zero dock only when Sleeper has also pulled the weekly projection,
  else x0.5 'doubtful-unconfirmed'; Sleeper Questionable alone = old rules.
  No-designation practice statuses: NOT docked (Wednesday rest days).
- Prop anchor: _inj.play / injPlay(p, wk) carries the play probability; the
  direct-line anchor undoes only that (lines posted after the designation
  price playing hurt), the market-rate fallback keeps the full dock (healthy-
  week rates). Vacated EV flows to teammates through the opportunity pool as
  before (McCaffrey Q+DNP x0.39 -> Kaelon Black x1.76 in the scenario check).
- NOTES chip "Q + LP (plays 72%, x0.94 if he plays) x0.68" / "DOUBTFUL (plays
  2%) x0.02". Kill: window.SIM_BANGED = false restores the 09-09 docks.
  Backup engine.js.bak_pre_banged_20260915. Scorecard note: score_week.py
  grades played rows only, so docked players who play will read under-
  projected there by design (the dock is an expected value).

## Age x experience workload curves (backtest_age_exp.py) - 2026-09-15

Jack: "projecting trends of increase workload or decrease workload throughout
the seasons based on age/experience" -> "start on the age and experience
workload curves next". Log age_exp_backtest.log; data/age_exp_backtest.js
on the ZONES tab. 68 LOYO tests.

IN-SEASON (bt_common base x the shipped snap trend rebuilt from nflverse snap
counts, 17,657 player-weeks 2019-25):
- Every SLOPE term fails: rookie x week, 2nd-year x week, old x late, age x
  week interaction (best RB age x week -0.13%). Age level: WR -0.10% 6/7.
- Workload trajectories are real (same player vs his weeks 2-6): rookie RB
  snaps +28% / +34% and touches +31% / +38% by weeks 7-12 / 13-18, rookie TE
  snaps +31% / +47%, rookie WR snaps +19% / +30%; 2nd-year RB touches +37% late;
  vets flat, WR 30+ touches -7%. The shipped snap trend absorbs most of it.
- ROOKIE LEVEL gap remains in every band (QB 1.13-1.15, RB 1.08-1.12, TE
  1.01-1.17, WR 1.02-1.12). LOYO flag: QB x1.12-1.15 -0.50% 6/7 PASS, RB x1.12
  -0.35% 5/7 PASS, TE -0.16% 6/7 lean, WR -0.06%, 2nd-year nothing.
  SHIPPED: engine ROOKIE_LEVEL {QB 1.08, RB 1.08} via rookieLevel(p), model
  side only (Clay stack mean and JS base; never the market rate), only once
  the rookie has a 2026 game. NOTES chip "rookie level x1.08". Kill:
  window.SIM_ROOKIE_LEVEL = false.

SEASON OVER SEASON (1,513 player-season pairs 2016-25, >= 6 games both, prior =
the shadow's 3-yr weighted PPG >= 4):
- Raw curves on the prior pass everywhere (age -7.3% 7/7) but that was graded
  against the raw prior. CONTROLS: flat position shrink -0.6%; log regression
  toward the position mean -3.7% (4/7, lean; QB slope .51). Graded against the
  regression: + residual AGE curve -4.97% 7/7 PASS (RB -4.2% 6/7, WR -8.6% 5/7,
  QB -1.3% 5/7, TE -2.7% lean); + experience -3.0% 5/7 but + age + exp is worse
  than + age (they overlap).
- Residual age curve (x on top of regression): RB 22 1.03, 24 .97, 26 .91, 28
  .87, 30 .86; WR 22 1.12, 24 1.03, 26 .92, 28 .85, 31 .82, 33 .79; QB 23 1.04,
  26 .92, 27 .91, 30 1.01, 35 .96. Keep-a-role rate falls with age (RB 88% at
  22-23 to 68% at 30; QB 84% to 65% by 29-30).
- SHADOW ONLY (Clay stays the live base): engine SHADOW_AGE + shadowAgeAdjust
  apply regression + residual age curve to history-based shadow priors >= 4
  half-PPR (ncSrc gains "+reg+age"); refreshed from this file by scratch
  patch_shadow_age.py. Kill: window.SIM_SHADOW_AGE = false. The Tuesday
  scorecard grades the result as "No-Clay shadow".

## Usage in context (backtest_usage_context.py) - 2026-09-15

Jack: "projections need to heavily take into consideration not just past
production but snap counts / routes run, what game scripts these happen in,
where on the field (snaps near the goal line are more valuable), playing more
snaps in 2WR sets vs just slot usage, team totals" + "and spreads".
nflverse pbp_participation 2018-25 (on-field players + personnel per play,
published after the season) x play_by_play. 12 context cells = zone (goal line
<= 5 / red zone / field) x dropback / run x neutral (score within 8) /
lopsided. League half-PPR points per on-field snap per cell, fit on the other
seasons. Graded on bt_common base x shipped snap trend, LOYO 2019-25. Log
usage_context_backtest.log; data/usage_context_backtest.js on ZONES.

- VALUE per on-field snap: RB goal-line run 1.77 (neutral) / 1.92 vs 0.315
  overall; RB red-zone run .57-.60, field run .41; WR goal-line dropback .56
  vs .175 overall; TE goal-line dropback .56-.58 vs .123. Goal-line snaps ARE
  worth 3-6x a normal snap.
- But as predictors beyond production: every LEVEL term fails (red-zone share,
  goal-line share, neutral-script share, 2-or-fewer-WR-set share, dropback
  share, context richness). Context-rich RBs / TEs land slightly UNDER
  projection (terciles 1.12 -> 1.03) - realized PPG already embeds the role
  and the goal-line TDs regress (same as the RB role study and TD luck).
- SPREAD beyond the implied total: fails for QB / RB / WR / TE and RB x role
  (again - see the RB role study). Underdogs by 7+ ran 1.10 (QB) / 1.11 (RB)
  but the continuous term does not hold out of sample.
- USAGE BLEND (1-w) base2 + w x usage projection: RB flat snaps -0.65% 6/7
  (w .2-.3) PASS, RB context-valued -0.48% 6/7 (worse than flat); WR context
  -0.27% 7/7 / flat -0.25% 5/7 (lean); TE -0.12 / -0.19%.
- SHIPPED: engine RB_USAGE {w .15, ptsPerSnap .315, minWeeks 3} / rbUsagePg:
  jsPg = .85 jsPg + .15 x (season-to-date snap share x team plays per game
  [SIM_PACE_2026] x .315, rescaled to the sheet by the Clay stat mix) once the
  back has 3+ games of 2026 snaps (SIM_SNAPS_2026). Plain snaps because the
  context version was worse AND participation is post-season only. NOTES chip
  "snap usage 60% x 62 plays = 11.7 half-PPR/g (15% blend)". Kill:
  window.SIM_RB_USAGE = false. Backup engine.js.bak_pre_rbusage_20260915.

## Ascending / descending players (backtest_role_change.py) - REJECTED as a layer 2026-09-15

Jack: "if a player's career average is 6 points on 50% of snaps but in the
last 10 games he averages 12 PPG on 85%, that recent sample should be way more
accurate, especially if it is not due to an injury to a player in front of
him". Last 10 played games (any season) vs the career window (3 prior seasons
before them), snap share (nflverse snap counts) and PPG; vacated = a teammate
who out-snapped him sat those games and later played for the team again
(departures count as organic). 10,355 RB/WR/TE player-weeks, base = shipped x
snap trend, LOYO 2019-25, 17 tests, none pass. Log role_change_backtest.log;
data/role_change_backtest.js on ZONES.

- The shipped projection ALREADY follows the recent sample: organic ascending
  RBs (snap share +20, PPG x1.5; 6.1 career -> 12.5 last 10) projected 11.2,
  scored 11.3. Organic ascending WRs 0.97 and TEs 0.96 of projection (slightly
  over-projected); descending organic RB 4.9 vs 4.9, WR 1.02, TE 1.03.
- Pushing harder toward last-10 PPG: RB +0.04%, WR +0.01%, TE -0.05% (all
  rows, organic only, or ascending/descending only - never better). Flags and
  snap-jump level terms flat.
- Ascents while a teammate ahead was hurt fade (WR 0.94, n 43) - direction as
  Jack expected, too few rows to grade; the live opportunity pool already
  removes that boost when the teammate returns.
- Why: the preseason prior already sees last season's breakout, the P=5 blend
  gives 2026 games most of the weight by week 5, and the snap trend adds the
  rest. The ASCENDING shadow chip stays as intel.

## Opportunity prior (backtest_opp_prior.py) - 2026-09-15

Jack: "start on the opportunity prior next" (roadmap step 5 for the Clay-free
shadow). Preseason season-PPG projection for RB / WR / TE from our own inputs:
projected target and carry shares (last season's share, allocated vacated work,
team change, age; rookies by log draft pick + vacated share) x team volume (.5
last season + .5 league) x value per opportunity (his site-xFP per target /
carry, shrunk K 60) x efficiency (shrunk, lambda 1.0 every fold). pbp 2016-25,
2,523 player-seasons; test seasons 2019-25 with every fit refit without the
test season. Log opp_prior_backtest.log; data/opp_prior_backtest.js on ZONES.

- Raw MSE made the opportunity prior look better than Clay everywhere - but
  Clay's per-game number is season points / scheduled games (it carries missed
  games), so raw MSE punished Clay for SCALE. With a per-position linear
  calibration fit on the training seasons for every model:
    overall  calibrated Clay 7.15 | Clay-free shadow 8.48 | Clay + OPP 7.05 (5/7)
    vets     calibrated Clay 7.08 | history 9.06 | OPP 8.46 | HIST + OPP 8.32 | Clay + OPP 6.96
    movers   calibrated Clay 7.14 | HIST + OPP 8.49 | Clay + OPP 6.90 (6/7)
    rookies  calibrated Clay 7.50 | OPP 9.28 | Clay + OPP 7.57
  Clay still ranks players best (r .78 vs .73) and beats every Clay-free prior
  in every segment - consistent with Jack keeping Clay live.
- The opportunity prior DOES beat the history prior for veterans (8.46 vs
  9.06, HIST + OPP 8.32), so it upgrades the shadow; for rookies it is worse
  than Clay, so the shadow keeps its Clay fallback there.
- Clay + OPP beats calibrated Clay (-1.3% overall 5/7, team-changers -3.3% 6/7)
  - that would change the LIVE base and is Jack's call; NOT wired.
- Share models (all seasons): target share = .02-.03 + .67 (RB) / .78 (WR/TE) x
  last share + small vacated allocation - .08 to .16 x last share when he
  changes teams; rookies .19-.26 - .03-.04 x log(pick). Value per target 1.13
  RB / 1.43 WR / 1.38 TE, per carry .57-.75.
- SHADOW WIRING: build_opp_prior.py -> data/opp_prior_2026.js (262 vets with
  >= 6 games in 2025, 2026 team from Sleeper sTm, full-fit calAll). engine.js
  blends it into the Clay-free ncMean prior after the age curve: a + b x
  history + c x opp (RB -.42/.22/.82, WR -.97/.37/.74, TE -.50/.41/.67);
  ncSrc gains "+opp". Only when the history prior is >= 4 half PPG (the
  calibration lifted deep backups: Kaleb Johnson .8 -> 2.9). Rookies stay on
  the Clay fallback. Live mean untouched (checked: 0 of 366 changed wk 2).
  Kill: window.SIM_SHADOW_OPP = false. Rerun backtest then build after trades.

## Opportunity prior on the weekly projection (backtest_opp_weekly.py) - 2026-09-16

Does Clay + OPP (the preseason winner) help the WEEKLY projection we ship?
The Clay per-game number inside the P=5 blend is scaled by the out-of-sample
season ratio (CLAY+OPP / CLAYCAL)^k, k picked LOYO. 15,103 RB/WR/TE
player-weeks 2019-25 (94% matched; out-of-sample preds from
opp_prior_preds.json, written by backtest_opp_prior.py).

- 12 tests, NONE pass: every variant is within +-0.05% of shipped (all
  +0.01% 5/7, vets +0.01%, movers +0.13%, rookies 0/7, RB vets -0.01% 5/7).
- Why: the ratio is small (p10 .94, median 1.00, p90 1.05) and the blend
  gives the season-to-date PPG most of the weight after a few games.
  Week bands at k=1: wk2-4 +.15%, wk5-8 -.11%, later ~0.
- Verdict: Clay stays the live base with no OPP adjustment; the opportunity
  prior stays shadow-only (and is a preseason/draft-season tool).

## Joint context model (build_context_features.py + backtest_context_model.py) - 2026-09-16

Jack: "create the ultimate projections ... context to all players" -> steps 1-2,
"backtest it all before we actually apply it". Research only, nothing live.

Step 1 - ctx_features.parquet: 17,657 QB/RB/WR/TE player-weeks 2019-25 (week
2+, same rows as every layer test), 91 pre-kickoff variables in 11 groups:
usage (shares, RZ/GL, WOPR, xFP, trends, snaps, QB dropback share), prior
season, team PROE / plays, coach (new HC / playcaller + the playcaller's own
history: PROE, RB/TE target share, RB1 carry share), injury vacancy (Out /
Doubtful / IR / gone teammates' shares, expected inheritance, starting QB out),
own injury tag, prospect (pick, JM score, age, exp), env (implied, spread,
total, dome, precip, wind, temp, kickoff), coverage matchup (opp man rate x the
player's man vs zone YPRR), and the OFFENSIVE LINE lineman by lineman (expected
starting five from prior-week snaps, each graded by LAST season's PFF pass /
run block grade shrunk to replacement, starters on the final report as Out /
Doubtful swapped for replacement; 2019 has no prior grades).

Step 2 - LightGBM on actual - (shipped x snap trend), LOYO with a held-out
validation season for rounds + shrink, plus ridge, a calibration-only model,
group ablation, and a forward (train on the past only) check.
- All context: -2.38% MSE vs shipped (7/7), forward -2.12% (5/5).
- BUT calibration-only (projection-level variables) is -1.61%, and the
  groups that help (usage +.60, vacancy +.32, env +.23) are signals the live
  engine already ships (TD luck, snap trend, vacancy pool, weather/Vegas,
  banged-up docks, rookie level). Individual OL -.31% (hurts), prior / team /
  coach / prospect / matchup / own tag ~noise.
- INCREMENT test: REF = base + those already-shipped signals = -2.84% vs
  shipped. Adding ANY new group on top is worse than REF (usage shares +.13%,
  coach +.10%, prospect +.09%, matchup +.20%, OL +.47%, every group +.48%;
  forward worse for all). Nothing new passes.
- Verdict: do NOT apply the context model. The new variables (coach, OL,
  coverage, prospect) add nothing beyond what ships. Open question worth a
  test: whether a learned combination of the ALREADY-shipped signals beats the
  hand-tuned live layers (REF's -2.84% is vs the harness base, which lacks
  them, and the live props anchor can't be replayed historically).
