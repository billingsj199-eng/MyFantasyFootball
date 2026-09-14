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
