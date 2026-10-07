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
per-player overrides still win), and since 2026-10-07 its mirror `aboveW`
(WR only — engine ABOVE_GAP 1.0 / ABOVE_POS / ABOVE_MARKET_MAX 12: when
the clean model sits >= 1 pt ABOVE a face-value market under 12 the
engine takes max(w, aboveW), i.e. it only raises the weight; W1-4 the
market was closer on 64-74% of those WR rows in every tier under 12, all
WR3/WR4 pecking-order optimism; on WR1 markets >= 12 the model was closer
5/8 so they are exempt; RB/TE/QB showed no side).
Also since 2026-10-07 `atdJuice[pos]` (anytime-TD devig inside
propImpliedFp replacing the flat PROP_ATD_JUICE 1.06 — J such that Σ
λ(p_raw/J) matches Σ actual rush+rec TDs, Poisson-honest shrink, clamp
1.0-1.35; written for RB + WR per Jack, evidence printed for all four:
W1-4 books ran hot on RB 0.89 / WR 0.91 / QB 0.84 and cold on TE 1.12).
Every lock row stores `tun` (incl. `wa`
= the market weight actually applied, since belowW/aboveW can differ from
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
Mechanics: consensus line = median across books, taken at FACE VALUE ×
per-stat `PROP_LINE_SCALE` (all 1.0) since 2026-10-07 — the original
median→mean gamma divisor (`gammaMedRatio`, median ×1.14) made the market
run +0.6 pts high over W1-4 2026 while face-value lines tied the clean
model; `window.SIM_PROP_GAMMA_RATIO = true` restores it, kickers still use
it; pass TDs
use the posted line; rush+rec TDs come from devigged anytime-TD odds →
Poisson mean, split rush/rec by the model's own ratio; uncovered stats stay
model. Coverage gate: posted lines must cover ≥60% of the player's non-TD
model points or no anchor; K/DST never anchored. Sigma, correlations and
the season shock are untouched — the market moves the center, not the width.

Honest-scoreboard rules: `comps` stay CLEAN everywhere (vsBooks grading and
the LINES view are non-circular — the LINES view compares the clean comps
at face value against the lines since 2026-10-07; it never reads the sim
run's p50/mean, and `window.SIM_PROP_GAMMA_RATIO = true` brings back the
closed-form medianizing). Locks store
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

## Learned combination vs hand-tuned live layers (build_live_layers.py + backtest_learned_combo.py) - 2026-09-16

Jack: "set up the learned combination test". The live stack was rebuilt with
the engine's own constants on the 17,657 context player-weeks: TD luck (RB .75
/ WR-TE 1.0 / QB .5 pass), banged-up cond (played Questionable by practice),
rookie x1.08 (QB/RB), RB snap usage .15, wind docks, opportunity pool (engine
POOL weights by depth), backup-QB .85 inheritance. Not replayable: the 70%
prop anchor, availability of players who sat, forecast wind, TE route trend.

- Ladder (each layer on the previous step): TD luck -.74% (7/7), banged -.10%
  (5/7), rookie -.21% (7/7), RB usage -.05% (4/7), wind -.07% (4/7), pool
  -.68% (6/7), backup QB +.18% (1/7, only 11 rows - reconstruction is crude,
  but worth a look). HAND = -1.65% vs the harness base.
- Refit layer strengths (shippable constants): LOYO -.24% (5/7) but FORWARD
  +.45% -> the hand-tuned constants are fine; don't retune.
- Per-position recalibration of HAND: -.63% (7/7), forward -.64% - almost all
  QB (-2.71%); the harness QB base likely differs from live (tuner + props).
- Learned correction ON TOP of HAND (LightGBM on the layer ingredients):
  -1.07% (7/7), forward -.87% (4/5); QB -2.40, WR -.89, RB -.56, TE -.58;
  helps where layers are active (wind -1.06%, rookies -1.59%, pool -.63%,
  TD luck -.35%) but not on played-Questionable rows (+.32%).
- Learned replacement from base2: -1.22% (7/7), forward -.77%, worse on
  Questionable rows (+2.14%).
- Verdict: PASSES historically, but the harness can't replay the prop anchor,
  so NOT applied. Next step = a live shadow of the learned correction on the
  lock rows (ncMean-style field), graded weekly by score_week.py.

## Learned shadow (build_learned_shadow.py -> engine learnedShadowCorr) - 2026-09-16

Jack: "yes build the live shadow". The learned correction retrained on the 32
features the engine computes the same way live (vacancy shares, pool gains and
dome dropped): LOYO -0.94% (7/7; QB -2.27, WR -.83, TE -.46, RB -.31), forward
-0.78% (4/5) vs the rebuilt hand stack. Final model 133 trees, k 1.0, exported
as JSON trees -> data/learned_shadow_model.js (69 KB).

- engine.js lgbTree / lgbPredict evaluate the trees (LightGBM missing-value
  rules); verify_learned_shadow.js checks 200 Python test vectors (max diff
  8.6e-6). learnedShadowCorr(p, wk, sc, slot, o): half-PPR only, QB/RB/WR/TE,
  week 2+, players with a 2026 game, not zeroed. HAND = jsMean conditioned on
  playing (/ P plays), correction scaled back by P plays.
- weeklyProjection returns lcCorr; simWeek rows carry it; both lock-row
  builders (export_site_proj.js auto-lock, app.js) log lcCorr and lcMean =
  shipped mean + lcCorr. PROJ never reads it.
- score_week.py grades "Learned shadow" (lcMean) and "Learned centered"
  (position-average correction removed = player signal only) next to the
  shipped mean, plus closer-than-shipped counts.
- W2 check: fires on 312 players, live mean / jsMean unchanged on all 461,
  average correction +0.64 (QB +1.19) - mostly a LEVEL shift the harness base
  needed; the centered grade shows whether the player-level part is real.
- Kill: window.SIM_LEARNED_SHADOW = false. Tuning study: tune_learned_shadow.py.

## Learned shadow tuning (tune_learned_shadow.py + seedcheck_learned_shadow.py) - 2026-09-16

Jack: "tinker with the shadow model and try to find the biggest correlation and
what we need to tweak to improve it over a large sample". 17,657 player-weeks
2019-25, LOYO + forward vs the rebuilt hand stack.

- Level vs signal: position-week level only -.33% (6/7), centered player
  signal -.60% (7/7), both -.94%. The player-level part is real.
- Raw correlations with the miss are all tiny (|r| < .04: last-game snap share
  +, week -, team plays -, temperature +, precipitation -, QB inheritance -).
  The model finds interactions, not one big lever.
- Drivers (out-of-fold SHAP): last-game snap share 10% (high snaps -> up, Q5
  +0.34 / Q1 -0.37), the hand number itself 10% (projections 13.9+ shrink
  -0.49: stars over-projected, low projections run 1.09x), team plays/g 8%
  (fast teams -0.28, slow +0.23: early pace regresses), Clay 8%, season snap
  share 7%, QB flag 6% (+), snap trend 6% (rising trend -> down: the snap-trend
  layer runs hot), week 5% (later weeks down), wind 4%, FPA 4%.
- Hand-layer audit (REL vs same-position rows without the layer): big pool
  boosts (x1.35+) run 0.887 -> cap the pool; Q + DNP played (cond .85-.90) runs
  0.836 -> that dock is too soft for players who suit up; strong wind 0.955 ->
  wind dock too soft (refit exponent 1.75 agreed); rookie level 1.021 (fine).
- Sweeps: 7 leaves -1.12/-0.90, L2 60 -1.00/-0.84, Huber worse (-.58/-.48),
  per-position models worse forward (-.28), adding team pace/PROE -1.10/-0.87,
  usage shares -1.20/-0.77, coach / prospect / matchup / OL worse. Drop-one-
  feature "gains" were noise (dropping all of them together: -0.63/-0.34).
- Seed check (3 seeds, noise ~+-0.08): current -0.98/-0.81, 7 leaves
  -1.04/-0.89, + team -1.07/-0.90. ADOPTED 7 leaves only (no new live inputs):
  rebuilt shadow LOYO -1.12% (7/7; QB -2.82, WR -.93, RB -.48, TE -.33),
  forward -0.90% (4/5), 345 trees, JS verified (1.0e-5).
- Candidate hand-layer tweaks to TEST next (not applied): cap pool multiplier,
  deeper Q+DNP cond, stronger wind docks, snap-trend slope below 1.0.

## Hand-layer fixes (backtest_layer_fixes.py) - 2026-09-16

Jack: "yes test those three layer fixes". Graded directly on the rebuilt live
stack (17,657 player-weeks), strength picked LOYO and forward, all rows +
flagged rows. NONE PASS - nothing changed in the engine.

- POOL CAP: boosts x1.35+ do run 0.936 of the hand number (n 349), and a 1.35
  cap is -2.3% on those rows pooled, but LOYO flagged -0.90% (4/7) and FORWARD
  flagged +2.43% (picks drift to 1.20-1.25 and hurt). Shrinking every boost:
  flat. Keep the pool as is.
- Q + DID NOT PRACTICE (played): 108 rows, actual/hand 0.933 - all WR (0.857,
  n 67; RB 1.04, TE 1.01). Extra x0.90 dock: flagged LOYO -1.69% (4/7),
  forward -0.77% (3/5) -> lean, not a pass. Too few rows; WR-only would be
  fishing. Watch it on the live scorecards. Q + limited practice: worse.
- WIND: the audit's 0.955 was a composition artifact - docked rows run 1.016
  (10-15 mph) and 0.997 (15+) of the hand number; QB and TE run ABOVE it
  (TE 1.06), WR 15+ 0.959. Stronger docks are worse every season (0/7).
- Lesson: layer-level REL ratios from the audit mix positions and weeks; grade
  the fix itself before believing them.

## NOTES why lines + matchup edges - 2026-09-16

Jack: "build the per-player why notes for videos ... also highlight players with
the biggest advanced weekly matchups positives and negatives". NOTES tab + the
headless export (export_notes.js -> notes/notes_latest.txt). Intel only.

- engine.js weeklyProjection returns wp.why (every factor in engine order:
  clayPg, jsBase, rookie, RB usage, Vegas, opp, CB shadow, CB1 out, OL out,
  pass rush, wind, snap, route, ramp, availability/pool, TD luck, jsMean).
  Projections unchanged (2,962 rows weeks 2-4 half + PPR, max diff 0).
- WHY line per player (app.js ntWhy): points waterfall that adds up to the
  model exactly, then the market step to PROJ, and the biggest driver.
  Learned shadow drivers (ntShadowWhy): engine learnedShadowExplain = Saabas
  path attribution over the 345 trees (node values now in
  learned_shadow_model.js); contributions + bias = correction (2e-15).
- MATCHUP EDGES board (ntMatchupBoard, top of NOTES + text export): QB 12+ /
  others 6+ PROJ, score in % of projection. PRICED = inside PROJ (opp FPA /
  Clay grade at 25%, soft rush, CB shadow, CB1 out, OL out, wind). INTEL (not
  validated as projection inputs): coverage fit (opp man rate x man/zone YPRR;
  RBs need 60+ routes, 35%), pressure / blitz vs QB splits, run D ypc / YCO /
  missed tackles / heavy boxes vs RBs, target zones leaky/stingy, defensive
  injuries by unit (coverage -> WR/TE, front -> RB, QB half each).
- Early-season shrink: every defense scheme rate = (g x 2026 + 4 x prior) /
  (g + 4) with the playcaller-aware prior (scPrior); run D by carries (prior =
  150 carries). Without it 1-game man rates (PIT 0%, NO 3%) swamped the board.
- Top 15 best / toughest per week; each row shows edge, priced, intel, and
  the reasons with the 2026 value, prior and league.

## Clay-free weekly ladder + shadow v2 (backtest_noclay_weekly.py) - 2026-09-16

Jack: "continue to tweak our sim labs to improve them and eventually remove
Clay's projections." The live Clay-free shadow (ncMean) only gets one scorecard
row a week, so this is the historical version: the shadow prior rebuilt
walk-forward on every Clay-pool player-week 2019-25 (19,064 rows, week 1
included) inside the same P=5 blend x Vegas x FPA, graded vs the shipped Clay
blend. Log noclay_weekly_backtest.log; data/noclay_weekly_backtest.js on ZONES.

- The gap is small and early: v1 shadow (own 3-yr PPG + last-8 prior, age
  curve, opportunity prior, Clay where no history) +0.36% MSE vs shipped;
  fully Clay-free (draft-round rookie mean, position mean) +0.45%. By week:
  wk1 +6.0%, wk2-4 +1.3%, wk5-8 +0.1%, wk9-12 +0.3%, wk13+ -0.75%. QB is
  BETTER without Clay in 7/7 seasons (-1.65%, -2.2% at P=12).
- Rows with no Clay-free prior: 13-15% in weeks 1-4 (rookies), 3% by weeks
  5-8, ~0 after - the last-8-games prior picks a rookie up after 4 games.
- Knobs (LOYO vs shipped): shrink the prior toward the position mean k=.8
  (picked 7/7, +0.45 -> +0.25%); prior strength per position QB 12 / WR 8 /
  TE 8 / RB 5 (QB 7/7); L8 weight .25 vs .5 = noise; team-changer x.95 =
  noise; rookie fallback: log(pick) 41.9 beats draft-round mean 43.9 (MSE of
  the prior alone, weeks 1-4) but Clay 39.6 still knows rookies best; the
  historical depth proxy (returning teammates with a share) added nothing.
- COMBINED (rookie log-pick fallback, shrink .8, per-position P): -0.03% vs
  shipped (2/7), FORWARD 2021-25 with constants from earlier seasons only
  -0.17%; vs the v1 shadow -0.39% (5/7), forward -0.28% (4/5). By position QB
  -2.9 / RB +1.0 / WR +0.6 / TE +0.5. What is left: wk1 +5.9%, wk2-4 +0.7%,
  team-changers +1.5%, 2nd-year +0.9% - Clay still reads rookies and movers
  before they play.
- SHADOW v2 WIRED (engine NC_SHADOW; Clay stays live per Jack 09-15):
  jsBasePg grew an optional prior-strength arg; ncMean now uses the rookie
  a + b ln(pick) fallback (draft pick baked into sleeper_meta.js dp/dy from
  the site's combine_data.js by refresh_data.py; undrafted = pick 262),
  position mean for anyone else without history, shrink k=.8 in half-PPR
  units, P per position; ncSrc gains rookie-pick / rookie-udfa / pos-mean and
  '+shr'. RELEVANCE GATE consensus ADP <= 200: the backtest population is
  Clay's >= 40-pt pool; the live pool's deep backups (Clay 0.5 PPG) were lifted
  to starter numbers by the position mean (UDFA QB3 -> 12.8), so ungated
  players keep the v1 prior unshrunk. verify_noclay_shadow.js: live
  mean/js/prop moved on 0 of 493 rows, v2 - v1 avg +0.04 on 429 rows, gated
  Clay-fallback rows 0. Kill: window.SIM_NC_V2 = false. score_week.py prints
  the prior-source mix. First live read = W2 scorecard (Tue 09-22).

## Market-informed prior: rookies REJECTED, veterans SHIPPED as shadow v2.1 (backtest_rookie_prior.py) - 2026-09-16

Jack: "build the market-informed rookie prior next." Preseason ADP (FFC
12-team 2019-25, half-PPR first then PPR/standard to fill holes ->
data/ffc_adp_hist.json, ~200-250 players a year) + the JM prospect score
(repo jm_scores.json, hindsight-tuned) as Clay-free rookie priors, per
position, fit on the other seasons. Log rookie_prior_backtest.log;
data/rookie_prior_backtest.js on ZONES.

- ROOKIES: every market model loses to the draft pick alone. Prior-alone MSE
  on rookie weeks 1-4 vs Clay: PICK +3.4%, ADP +8.1%, PICK+ADP +7.0%,
  +JM +7.0%, ADP curve (fit on everyone) +5.7%, half curve / half pick +3.6%.
  Rookie TEs blow up on ADP (+46-57%); a third of pool rookies are unlisted
  (actual/Clay 1.32 there - Clay under-projects them too). Inside the shadow
  the fallback barely matters (all within 0.1%). Rookies keep a + b ln(pick).
- VETERANS: E[PPG | ADP, pos] fit on every listed player (a + b ln(adp): QB
  35.4-3.83, RB 22.8-3.15, WR 22.7-3.05, TE 20.0-2.66 half-PPR) blended into
  the history prior. LOYO vs shipped: all listed vets w .75 -0.51% (5/7),
  team-changers w 1.0 -0.86% (6/7), same-team 3+ yr vets -0.68% (6/7), QB
  -1.58% (7/7), WR -0.68% (5/7); RB/TE/2nd-year improve but stay above Clay.
- SHADOW v2.1 = v2 + vets ADP weight .75 (2nd-year .5), rookies by pick:
  -0.66% vs shipped (5/7), vs v2 -0.54% (7/7), FORWARD 2021-25 -0.80% (4/5).
  By week: wk1 +5.3 -> +2.3%, wk2-4 +0.5 -> -0.9%, wk5-8 -0.8%, wk13+ -1.1%.
  Team-changers +1.5 -> +0.4%, 2nd-year +0.9 -> +0.4%. The Clay-free shadow
  now beats the shipped Clay blend historically; the live ledger (W2 on)
  decides whether that transfers through the prop anchor.
- Engine: NC_SHADOW.adpCurve / adpW / adpWYr2 / adpMax 181 (FFC listing
  range; live consensus ADP `a` beyond it = unlisted, no market term); applies
  after age + opportunity and before the shrink, only to non-rookies with a
  history prior (hist/l8); ncSrc '+adp'. Kill: window.SIM_NC_ADP = false.
  Caveat: the curve was fit on FFC ADP; the live number is the site's
  consensus ADP - same 1-180 scale, different drafters.

## Live depth-chart slot for rookies -> shadow v2.2 (backtest_rookie_depth_live.py) - 2026-09-16

Jack: "build the live depth-chart slot for rookies next." The ladder's
historical proxy (returning teammates with a share) had added nothing; the
REAL charts do. nflverse weekly depth charts 2019-25 (pbp_cache/
depth_charts_Y.parquet; 2019-24 NFL.com format depth_team = string, 2025 ESPN
format with a global pos_rank interleaved across slots -> string = ceil(rank /
slots), WR 3 slots) = the same ESPN charts sim_depth.js carries live. Rookie
rows charted 93-100%. Log rookie_depth_live.log; data/rookie_depth_live.js.

- Rookie weeks 1-4, actual / pick prior by string: RB starter 1.39 (n33) /
  2nd .82 / 3rd+ .75; WR 1.18 / .87 / 1.09; QB .96 / .63; TE .99 / .71.
- PICK+STR (a + b ln(pick) + c [2nd] + d [3rd+], per position, LOYO):
  prior-alone MSE -4.56% vs PICK and -1.32% vs CLAY - the first Clay-free
  rookie prior that beats Clay before the rookie plays. RB -11.8% vs pick,
  WR -1.6%, QB flat, TE +3.1% (n small). Multiplicative version -2.3%.
- Inside the shadow v2.1: -0.10% vs v2.1 (6/7), forward -0.03% (4/5), rookie
  rows -0.21% forward; -0.76% vs shipped overall (5/7), forward -0.89%.
- VETERANS by string (weeks 1-8): 2nd-string RB/WR/TE run .84-.88 of the
  shadow prior, but a demoted-vet dock is 1/7 vs shipped (Clay already reads
  demotions; the shadow prior is +4% worse on those rows) - intel, not a layer.
- Engine v2.2: NC_SHADOW.rookieStr (RB/WR) + depthString(p) from
  SIM_DEPTH_2026 (index / slots + 1; unlisted = deep); ncSrc 'rookie-pick+str1'
  / '+str2' / '+str3' / '+strx' (unlisted). QB/TE stay pick-only.
  Kill: window.SIM_NC_DEPTH = false.

## Demoted veterans -> shadow v2.3 (backtest_demoted_vets.py) - 2026-09-16

Jack: "build the demoted veteran layer next." The earlier flat dock had
been graded against Clay; graded against the shadow it changes (v2.2: own
history + ADP market prior, rookie pick + string, shrink .8, per-position
P) on 15,113 veteran player-weeks with a pre-game chart string:
- Reads (actual / shadow prior): RB 1st 1.12 / 2nd .90 / 3rd+ .58; WR 1.05 /
  .81 / .54; TE 1.07 / .90 / .96; QB 2nd .57 (n73).
- DOCK prior x m on string >= 2: -1.73% vs shadow (6/7); by string RB 2nd
  .8 (-0.75%, 5/7) / 3rd+ .4 (-16%, 6/7, n168), WR 2nd .6 (-3.4%, 6/7) /
  3rd+ .6 (-13%, 6/7, n61), TE 2nd .8 (-1.2%, 5/7) / 3rd+ nothing.
- LEVEL blend toward the string mean: weaker (-0.93%). PROMOTION (string 1
  with a low prior): nothing (w=0 every fold; QB/RB .25 = noise).
- Candidate v2.3 = per-position, per-string docks: -0.28% vs shadow v2.2
  (7/7), -1.08% vs shipped (7/7); FORWARD (docks re-picked on earlier
  seasons) -0.15% vs shadow (5/5), demoted rows -1.45%. Demoted vets go from
  +1.95% to -0.64% vs shipped; week 1 +1.6 -> +0.8%.
- Engine: NC_SHADOW.vetDock {RB 2:.8 3:.4, WR 2:.6 3:.6, TE 2:.8} on the
  prior after the ADP blend, before the shrink, non-rookies with a history
  prior and depthString >= 2 (unlisted = no dock); ncSrc '+dock2' /
  '+dock3'. Kill: window.SIM_NC_VETDOCK = false.
- Shadow ladder to date (all vs shipped Clay blend, 2019-25): v1 +0.36% ->
  v2 -0.03% -> v2.1 -0.66% -> v2.2 -0.76% -> v2.3 -1.08% (7/7). Still
  shadow-only per Jack 09-15; the weekly scorecard from W2 decides.

## Veterans without a chart -> shadow v2.4 = current-team lookup (backtest_nochart_vets.py) - 2026-09-16

Jack: "build the vets without a chart layer next." 1,180 veteran
player-weeks (7% of vets) had a history prior but no pre-game string and ran
+2.7% vs shipped. By cause: 464 were listed on ANOTHER team's chart that week
(the harness infers a player's season team from his opponent sequence, so
mid-season movers land on the wrong team - a harness artifact; live, the
engine has Clay's team and Sleeper's sTm), 177 were on the same team's chart
1-3 weeks earlier but not this week (act/prior .90 - dropped = hurt/limited;
carrying the old string HURTS, +1.3% on those rows), 539 were on no chart in
the last 3 weeks (act/prior .96; RB .99, WR .90, TE .92).
- ANYTEAM (read the string wherever he is listed): -2.4% on the 464 rows,
  -0.05% overall (4/7). UNLISTED dock x.9: pooled -1.0% (5/7) but RB 0/7,
  TE worse, forward -0.02% (3/5) -> NOT shipped. CARRY -> NOT shipped.
- Engine: p.tmNow = Sleeper's current team; depthString() looks up Clay's
  team, then tmNow, then any team's chart (0 mismatches today; matters
  after in-season trades). No dock for the truly unlisted.
- Shadow ladder vs shipped Clay blend: v2.3 -1.08% (7/7); the remaining
  no-chart rows are +1.3% (n539) and the "dropped this week" rows +5.6%
  (n177) - the latter is the injury/limited case the live availability layer
  already handles on the Clay side.

## Dropped-off-the-chart veterans (backtest_dropped_vets.py) - REJECTED 2026-09-16

Jack: "build the dropped-off-the-chart vets layer next." The 177 veteran
player-weeks listed on their team's chart 1-3 weeks earlier but not this
week (nochart study: act/prior .90, shadow +4.2% vs shipped there). Official
injury reports (pbp_cache/injuries_Y.parquet) joined; the LIVE injury docks
(Doubtful x.5, Q+DNP x.75) applied to shipped AND shadow in the harness so
the layer is graded on what the drop adds beyond the designation.
- 15% of dropped rows carry a designation (vs 5% of listed vets); those 27
  score .60-.77 of the docked prior (Q-LP dropped .60, n18) but n is tiny.
  The 150 UNDESIGNATED dropped rows score .95 - nearly nothing to dock.
- Dock all dropped x.8: -0.44% vs shadow (3/6) FAIL; undesignated x.8:
  +3.2% FAIL; RB only x.6: -5.0% (4/5, n45) - too thin; WR +1.0% FAIL.
  Candidate forward -0.02% (3/5). NOTHING SHIPS.
- Side check, listed vets with a designation on the shadow: Q-LP extra x.9
  lean (-0.5%, 4/7), Q-DNP x1.1 noise (2/7), Q-FP x.9 fail -> the live docks
  are roughly calibrated for the shadow too; intel only.
- Reading: the drop mostly IS the injury designation the availability layer
  already prices; the residual is small-n noise. Don't re-pitch.

## Week 1 -> shadow v2.5 = chart-defined buried-rookie ramp (backtest_week1.py) - 2026-09-16

Jack: "build the week 1 layer next." Shadow v2.4 was +0.53% vs shipped in
week 1 (n 1,245), the only pure-prior week. Reads: TE act/shadow .88 (every
model runs hot on TEs in week 1, shipped .92), rookies .84, movers .96,
2nd-string vets .91, vets ADP 37-132 +3.7-4.4%; QB/WR/same-team vets fine.
- Global knobs all FAIL: week-1 level (0/7), shrink k (2/7), vets ADP
  weight (3/7), 2nd-year ADP weight (0/7). Rookie x.8 lean (4/7).
- The rookie gap is BURIED rookies only: 2nd-string rookies week 1
  act/shadow .74 (+24.6% vs shipped), 1st-string .98 (a level there FAILS
  0/7). The live engine ramps buried rookies 55/70/85/95% (RAMP.buried, keyed
  on Clay's projection vs the team leader) - the harness has no ramp, and
  the shadow needs a Clay-free definition anyway: string >= 2 or unlisted.
- Chart-defined ramp by week (LOYO vs shadow): wk1 x.7 -10.5% (5/7 PASS),
  wk2 x.8 -1.5% (4/7 lean), wk3 +3.5% FAIL, wk4-8 nothing, wk9+ x1.1 (+0.5%,
  no). Candidate {wk1 .7, wk2 .8}: -0.08% vs v2.4 (5/7), -1.21% vs shipped
  (7/7), week 1 +0.53 -> -0.38% vs shipped, buried rookies wks 1-4 -3.9%;
  FORWARD all rows -0.08% (4/5), buried -4.1% (4/5), week-1 rows -1.05% (4/5).
- TE week-1 x.9: -0.83% on TE rows (5/7) but forward 2/5 alone -> NOT shipped.
- Engine: NC_SHADOW.rookieRamp [.7, .8] by gameIdx for rookies with
  depthString >= 2 or null; inside the shadow ncChain = jsChain / rampF x
  ncRamp (the live Clay-defined ramp is removed from the shadow so no rookie
  is ramped twice); ncSrc '+ramp1' / '+ramp2'. Kill: window.SIM_NC_RAMP =
  false. Ladder vs shipped: v2.4 -1.13% -> v2.5 -1.21% (7/7).

## Second-year role growth -> shadow v2.6 (backtest_second_year.py) - 2026-09-16

Jack: "build the second-year role growth layer next." 2nd-year rows (exp 1,
n 2,952) sat +0.11% vs shipped on v2.5 (the ADP prior had already closed
most of the +0.9% gap). Signals, each LOYO vs shadow v2.5 on the 2nd-year rows:
- LEVEL x m: FAIL (+0.03%, 4/7). RECENCY (rookie-season last-8 weight .75):
  -0.04% (5/7) FAIL on size. 2nd-year ADP weight .75: -0.07% FAIL.
- PROMOTION by chart (last season's modal string weeks 10+ from nflverse
  2018-24 vs this week's): promoted act/shadow 1.06, steady 1.03, still
  buried 1.10, demoted 1.05 - the market prior already prices the
  promotion; multipliers FAIL (0-4/7).
- SNAPS (rookie-season snap counts 2018-24 via players.csv pfr_id):
  LATE SNAP SHARE < 40% (last 4 games) act/shadow 1.18 -> x1.2: -1.36%
  (6/7 PASS), forward its rows -1.31% (4/5), 2nd-year rows -0.20% (4/5).
  Rising trend tercile x1.1: -0.68% (4/7 lean) but forward 2/5 -> NOT
  shipped. Falling trend / high snaps: FAIL.
- Engine v2.6: NC_SHADOW.yr2LowSnap {max .40, mult 1.2} on the prior for
  p.exp === 1 with a history prior; data = SIM_SNAPS_PRIOR in sim_snaps.js
  (refresh_data.py: last season's mean offensive snap % over the player's
  last 4 games with snaps, from the site's snap_counts.js); ncSrc '+yr2lo'.
  Kill: window.SIM_NC_YR2 = false.
- Reading: the part-time rookie whose role grows is the one case the
  history prior structurally misses; everything else about 2nd-year players
  is already in the market curve.

## Tight ends (backtest_te_layer.py) - NOTHING TO SHIP 2026-09-16

Jack: "build the tight end layer next." TE rows (n 3,686) are -0.20% vs
shipped on shadow v2.6 - already below Clay. Reads: week 1 act/shadow .90
(shipped .92 - everyone runs hot on TEs in week 1), weeks 5-8 1.09 (-2.0%
vs shipped), 2nd-year 1.11, high route-participation tercile (> .70 of
the team's pass plays last season, nflverse participation 2018-24) 1.07 vs
low .99, movers -2.2%.
- Every TE-only knob FAILS LOYO vs the shadow: level (3/7), week-1 level
  (4/7, +0.10%), P (0/7, 8 stays), shrink k (0/7), ADP weight (0/7), age
  curve on/off (identical), 2nd-string dock re-check (.8 stays), 3rd+ dock
  (none), low-route dock (0/7), high-route boost x1.1 (-0.57% but 3/7),
  high routes & low prior (0/7), 2nd-year TE (2/7).
- Verdict: no TE layer. The position's residual is week 1 (a league-wide
  TE week-1 effect Clay shares) and noise. Don't re-pitch route
  participation as a TE prior; the in-season route TREND layer (live) is
  where TE information lives.

## Clay-free POOL definition (backtest_pool_definition.py + build_noclay_pool.py) - 2026-09-16

Jack: "build the Clay-free pool definition next." Today the engine projects
exactly Clay's sheet (493 rows; 436 QB/RB/WR/TE). Without Clay, who gets a
projection? Rules from Clay-free sources scored 2019-25 on recall of
fantasy-relevant player-weeks in the FULL weekly DB (STARTER = weekly top
QB12/RB24/WR36/TE12; ROSTERABLE = top 24/48/72/24), preseason and DYN (anyone
with a 10-pt game joins from the next week):
  rule                        size  starter  wk1   DYN   roster  pts%
  CLAY (>= 40 pts, harness)    292   89.9   95.2  94.9   83.9   89.0
  CLAY all                     487   96.2   97.8  98.2   94.8   96.2
  ADP (FFC)                    187   76.3   82.1  90.2   65.2   74.5
  CHART wk1 string <= 2        348   88.2   93.2  95.4   84.0   88.6
  HIST (>= 8 g, >= 4 PPG)      259   78.9   84.7  92.5   72.0   78.5
  ROOKIE rd 1-4                 45    9.9    7.0  80.6   10.2    9.7
  ADP + CHART + HIST + ROOKIE  450   96.4   98.5  97.9   93.7   96.3
- The union rule matches Clay's FULL sheet (96.4 vs 96.2% of starter weeks,
  98.5 vs 97.8% in week 1) at the same size; the depth chart is the
  workhorse (88% alone), ADP + chart 93%, history and rookies close the rest.
  Misses are TE3s / handcuffs who emerge mid-season (Slayton 2019, Mostert,
  Keaton Mitchell, Kimani Vidal) - the in-season add rule picks them up.
- build_noclay_pool.py applies it live (site consensus ADP <= 250, ESPN chart
  string <= 2, player_weekly_sigma history, sleeper_meta draft pick <= 135,
  MUST have a team) -> data/noclay_pool_2026.js (SIM_NOCLAY_POOL): 495
  members vs Clay 436 - both 397, pool-only 98 (Anthony Richardson, Aiyuk,
  Kirk, Dalton, Wentz: players Clay's print skipped), Clay-only 39 (all deep:
  top Clay pts = Kyle Williams WR 51, then fullbacks / TE3s). Alias-aware
  diff (Ken Walker III / Cameron Ward / Chig Okonkwo). Each member carries
  a per-game stat MIX from his last two seasons (358) or the position mean
  (137) - the comps a Clay-free engine needs to turn a half-PPR prior into
  a stat line. Data files are read through node (dump_js_var.js) since the
  Clay file is a JS object literal.
- NOT wired: the engine still builds players from Clay's sheet. Switching the
  pool = new buildPlayers source (members + mix -> comps, priors from the
  shadow's own pieces, K/DST synthesized) - the 2027 offseason job.

## What correlates with scoring: season-long vs weekly, by position (research_corr_horizons.py) - 2026-09-16

Jack: "find the biggest correlation for season long and weekly points
scoring, how it's different between the two and the same - by position."
ctx_features.parquet (17,657 player-weeks 2019-25, 91 pre-kickoff vars) +
FFC ADP + depth strings + last-game / last-3 from the weekly DB. SEASON =
player-season PPG vs preseason-known features (n 1,390); WEEKLY = weekly
points vs everything known pre-kickoff (weeks 2+). Pearson r (Spearman too).
data/corr_horizons.js on ZONES.
- SEASON, every position: prior production dominates - prior-year PPG /
  xFP per game / target (WR/TE) or carry (RB) share r .62-.73, ADP -.49 to
  -.68, week-1 depth string -.29 to -.54 (RB strongest), JM score .28-.51
  (RB strongest), draft pick -.46 RB / -.28 WR / ~0 QB-TE, team change
  -.43 QB / -.23 TE / -.15 WR. Age and experience ~0 everywhere (the age
  curve is a residual, not a headline). Clay's number = the best single
  preseason correlate (.58 QB, .73 RB/WR/TE) = the same info bundled.
- WEEKLY: every correlation roughly HALVES (weekly points are ~half noise):
  the same preseason features fall to r .2-.4. What rises to the top is
  season-to-date usage: RB carry share (last 3) .46, snap share .46, xFP/g
  .46, red-zone carries .41, this week's string -.37; WR/TE target share
  .43, WOPR .41-.42, air-yards share .37, snap share .35; QB the ONLY
  position where a game-level input leads: team implied total .33 (>
  season-to-date PPG .31), game total .24, spread .22 - QB scoring is the
  game environment; RB/WR/TE weekly is the player's role.
- SAME at both horizons: the ordering of the preseason features is
  preserved (prior PPG > shares/xFP > ADP > string > JM > pick), just at half
  the size weekly. Last game alone (.24-.38) < last 3 (.30-.46) <
  season-to-date PPG (.31-.48): more games beat recency for the level.
- DIFFERENT: season = who the player is (production, market, draft slot);
  weekly = what his role is right now (shares, snaps, string) plus, for
  QBs, the Vegas environment. Matchup / weather / injury tags are all
  |r| < .1 weekly - real but small, which is why they live as multipliers
  on a strong base rather than as base inputs.

## QB implied-total layer (backtest_qb_vegas.py) - NO CHANGE 2026-09-16

Jack: "build the QB implied total layer next." The implied total is the top
weekly QB correlate (r .33), and the live Vegas layer (e QB .25) was tuned
on the Clay base, so the shadow (history + market) might want more. QB rows
already sit -4.0% vs shipped on shadow v2.6.
- Reads: QB actual/shadow .92 at implied < 19, .97 at 19-22, ~1.0 above -
  the shadow runs hot on bad offenses, but raising e trades that against
  the high side.
- Elasticity sweep on QB rows LOYO vs the shadow: pooled best .4 but
  +0.24% and 0/7 (FAIL); weeks 2-4 want .5 (-0.52%, 5/7) yet the candidate
  is +0.39% FORWARD (1/5); weeks 5+ and week 1 keep .25 (0/7 for change).
  Spread term: 0 every fold. QB P: 12 stays (16 at e .4 = lean, not used).
  Controls: RB .4 lean (-0.08%), WR/TE .25 stay. Reference on the shipped
  Clay blend: .25 stays (0/7).
- Verdict: the game environment is already in the shadow at the right
  strength; the strong weekly correlation is captured by the existing
  multiplier. NO CHANGE. Don't re-pitch QB Vegas elasticity.

## RB elasticity layer (backtest_rb_vegas.py) - FLAT, NO CHANGE 2026-09-16

Jack: "build the RB elasticity layer next." The QB study's control run had
RB leaning to .4 from the live .5 (-0.08%). Full test on RB rows (n 4,844)
LOYO vs shadow v2.6: pooled best .35, -0.03% (4/7) FAIL; by band week 1 /
2-4 want MORE (.4-.6, 0-2/7), weeks 5-8 want .3 (4/7), 9+ .35 (3/7) - a
flat surface, not a signal; 1st-string .35 (-0.04%), 2nd-string+ .4
(+0.13%); spread term (game script) 0 in every fold at e .5 and .4;
reference on the shipped Clay blend .4 (+0.01%, flat). Candidate e .35:
RB rows -0.07% (4/7), FORWARD -0.02% (3/5). NO CHANGE - .5 stays.
Reads for the record: RB actual/shadow 1.09 at implied < 19 and 1.09 as a
7+ underdog (the shadow is cautious on bad-offense RBs, Clay more so at
1.13 / 1.12), 1.00 for a 1st-string RB favored by 7+.

## Advanced stats / route share / alignment correlations (research_corr_advanced.py) - 2026-09-16

Jack: "did we find the highest correlation in advanced stats by position or
route share or alignments in certain offenses?" Not in the first study -
added here on the same 2019-25 rows: PFF season files (route rate, YPRR,
TPRR, aDOT, route/offense/run grades, slot/wide/inline rates, YAC, drops,
contested; RB YCO, elusive, breakaway, gap share) matched pff_id -> gsis;
route share from participation (season-to-date + last 3, routes/game,
TPRR/YPRR to date); team pass plays / 11 / 12 personnel / shotgun (prior yr
+ to date); alignment x offense interactions. data/corr_advanced.js.
- NOTHING advanced beats the basics at either horizon, any position.
  SEASON: prior-yr PPG .49/.67/.70/.73 (QB/RB/WR/TE); best advanced = WR
  targets volume .66 ~ PFF route grade .65 ~ offense grade .64, YPRR .57,
  TPRR .55; TE targets .65, YPRR .58, route grade .57; RB routes volume
  .36, offense grade .35 (RB rushing efficiency - YCO .19, elusive .18,
  breakaway .18 - is weak: volume, not efficiency); QB elusive rating .35 /
  run grade .26 = mobile QBs score more.
- ALIGNMENT: weak alone. TE inline -.24 / slot +.23 / aDOT +.22; WR slot
  -.10, wide +.11. Team offense context ~0 for skill players (pass plays/g
  .06, 11-personnel -.02, shotgun -.05; TE 11-rate -.14). Interactions:
  route share x pass plays = routes/game (same r); route share x PROE weak;
  slot x 11-personnel and inline x 12-personnel < .1 (not in the top lists).
- WEEKLY: route share to date .31 WR / .35 TE / .38 RB (last 3 the same)
  trails target share (.43) and season PPG (.42-.48); TPRR/YPRR to date
  .30-.32; prior-yr PFF route grade .38 WR / .31 TE = nearly target share
  before the season's own data exists (the one place a grade earns its
  keep - consistent with the PFF audit's "season-level talent = priced in").
  QB "route share" = starter flag (.21), not a signal.
- Read: production (targets, PPG) > opportunity (routes, shares) >
  efficiency grades > alignment > team scheme. Alignment matters only
  through the shipped slot-shield (CB dock graduation), not as a prior.

## Prior-year PFF route grade -> shadow v2.7 (backtest_pff_route_grade.py) - 2026-09-16

Jack: "build the prior-year PFF route grade layer next." The grade is r .38
with weekly WR points (research_corr_advanced.py) and the shadow prior has
no talent read (the 09-01 PFF audit rejected grades on the CLAY base). Tests
on WR / TE / RB rows with a history prior and a prior-season grade (>= 50
routes; PFF id -> gsis), LOYO vs shadow v2.6:
- Reads (actual / shadow prior, weeks 1-8): WR top tercile 1.11, mid 1.02,
  low 1.03; TE 1.06 / 1.03 / .95; RB flat by grade (volume, not grade).
- Tercile multipliers FAIL for WR/TE/RB (0-4/6); curve blend E[PPG | grade]
  FAIL (w 0-.15, 0-2/6); weeks-1-4-only curve: TE lean (-0.18%, 4/6); young
  top-tercile: WR lean (-0.08%), RB lean (-0.41%, 4/5, n323), TE fail.
- PASS: WR grade ABOVE what the prior implies (residual of grade on the
  shadow prior, top tercile) x1.1: -0.43% vs shadow (5/6), forward affected
  rows -0.26% (4/5), all rows -0.04%. "Graded better than he has produced"
  is the talent read the history prior lacks; TE version lean (-0.16%),
  RB nothing. Bottom-residual docks fail everywhere.
- Engine v2.7: NC_SHADOW.wrGrade {c0 56.095, c1 1.9876 (grade ~ prior
  half-PPR), cut 2.649, mult 1.1}, applied after the 2nd-year boost and
  before the shrink for non-rookie WRs with a history prior; data =
  SIM_PFF_ROUTE_PRIOR in sleeper_meta.js (refresh_data.py bakes last
  season's WR grades from pbp_cache/pff/pff_receiving_2025.csv by norm
  name); ncSrc '+grade'. Kill: window.SIM_NC_GRADE = false. Marginal by
  design - the smallest piece in the ladder; watch it on the scorecards.

## TE route grade layer (backtest_te_route_grade.py) - REJECTED 2026-09-16

Jack: "build the TE route grade layer next." The WR study's TE pieces were
lean; tested on their own (TE rows with a prior-season grade >= 50 routes
and a history prior), LOYO vs shadow v2.6:
- Residual top tercile x1.1: -0.16% (4/6) lean -> candidate on affected
  rows -0.48% (4/7) but FORWARD +0.31% (3/5) - reverses. Residual top HALF
  x1.1: -0.44% (4/6) lean. Bottom tercile: 0 every fold. Raw-grade top
  tercile x1.05: -0.09% (4/6) fail. Early-weeks residual: +0.44% (0/6).
  Curve blend: 0 (all weeks), -0.08% (4/6) weeks 1-4. Combo (residual x1.1
  + early curve .15): -0.19% (4/6) lean.
- Verdict: no TE grade layer. TE residual constants for the record: c0
  51.67, c1 2.84 (grade ~ prior half-PPR), cut 2.87 / half -0.36.
- Reading: TE scoring is targets and role (the in-season route TREND
  layer), not the grade; the WR residual (v2.7) stays the only grade piece.

## WR route-grade curve blend (backtest_wr_curve.py) - REJECTED 2026-09-16

Jack: "build the WR curve blend layer next." G = E[PPG | prior-yr route
grade] blended into the WR shadow prior, every form, LOYO vs shadow v2.6:
all rows w .1 -0.02% (4/6); high-residual rows w .1 -0.06% (4/6); age <= 25
w .05 0.00% (3/6); weeks 1-4 only +0.07% (1/6); replacing part of the .75
market weight +0.03% (3/6); curve of grade + routes volume w .15 -0.08%
(4/6) -> candidate affected rows -0.09% (4/7), FORWARD -0.10% (3/5). All
FAIL. The grade's information about WRs is the residual (v2.7); a level
curve on top adds nothing - the market prior and history already carry the
level. Grade layers are DONE: WR residual shipped, TE and WR-curve rejected.

## Prior-year routes volume (backtest_routes_volume.py) - REJECTED 2026-09-16

Jack: "build the routes volume layer next." Last season's PFF routes (>= 50)
as a shadow-prior ingredient, same forms as the grade study, LOYO vs v2.6:
- Reads (actual / shadow prior, weeks 1-8): WR low 1.02 / mid 1.06 / high
  1.09; TE .96 / .99 / 1.08; RB 1.10 / 1.15 / 1.06 - the high-route tercile
  runs a little hot vs the prior, but every multiplier form fails.
- Tercile levels: WR top +0.19% (4/6) FAIL, bottom 0/6; TE top +0.17%
  (2/6), bottom x.9 -0.11% (4/6) lean; RB 0/6. Curve E[PPG | routes]: w = 0
  in every fold, all three positions, all weeks and weeks 1-4. Young top
  tercile: WR x1.1 -0.31% (4/6) lean, TE/RB worse. Residual (routes above /
  below what the prior implies): WR above +0.02% (3/6), below +0.37% (0/6);
  TE/RB nothing. NO PASS.
- Reading: routes volume is opportunity, and the prior (history + market +
  depth string) already carries it; the residual that worked for the WR
  GRADE (skill beyond production) does not exist for routes. Routes stay
  where they live: the in-season TE route TREND layer and the RT% intel.
  Opportunity-volume priors are DONE (routes, snaps as level, chart string
  shipped where it passed).

## Low-route tight ends (backtest_te_lowroute.py) - REJECTED 2026-09-16

Jack: "build the low-route tight end layer next." The routes-volume study's
TE bottom-tercile dock (x.9, -0.11%, 4/6 lean) given every form, LOYO vs v2.6:
- Reads (actual / shadow prior): low routes .97, low route RATE 1.05 (!),
  low routes & low rate 1.04, low routes & low grade .96, low routes weeks
  1-4 .95, low routes & 2nd string+ .92 (already docked by string).
- Forms: low routes x.9 -0.11% (4/6) lean -> candidate affected rows -0.34%
  (4/7), FORWARD +0.19% (2/5) - reverses. Low route RATE: 1.0 every fold
  (the blocking-TE read carries nothing; low-rate TEs run HOT vs the
  prior). Routes & rate: 0/6. Routes & low grade x.85: +0.25% (3/6).
  Weeks 1-4 only x.85: -0.51% (4/6) lean. 1st string: 1/6. 2nd string+ on
  top of the string dock x.8: -0.41% but 3/6. Route-rate curve: w 0.
- Verdict: no low-route TE layer. The string dock (v2.3) already prices the
  backup TE; route volume / rate adds nothing preseason. TE priors are
  DONE (level, grade, routes, rate, string all tested).

## Young high-route WRs (backtest_wr_young_routes.py) - NOT SHIPPED 2026-09-16

Jack: "build the WR young high-route layer next." The routes-volume study's
"top-tercile routes & age <= 25 x1.1" lean (-0.31%, 4/6), every form, LOYO
vs shadow v2.6 (which already carries the age curve for young WRs):
- Reads (actual / shadow prior): high routes all ages 1.06; & age <= 25
  1.13; & 2nd year 1.21 (n155); & 4th+ yr & <= 25 1.19 (n149); & young &
  low prior 1.15; & young & high grade 1.13; high route RATE & young 1.04.
- Forms: high routes & <= 25 x1.1 -0.31% (4/6) lean; high route RATE &
  young: 1.0 every fold; breakout (young, low prior) x1.15 -0.05% (3/6);
  young & HIGH GRADE x1.1 -0.42% (5/6) PASS -> affected rows -0.66% (5/7)
  but FORWARD -0.23% (3/5); 2nd year x1.2 -1.50% (4/6) lean (n155); 3rd
  year +0.52%; weeks 1-4 only +1.55% (worse); all ages (control) +0.19%.
- Verdict: NOT SHIPPED. The only passing form is young receivers with high
  routes AND a high grade - largely the population the v2.7 grade residual
  already boosts (double-count risk), and it misses the forward bar (3/5).
  The route volume itself is not the signal (route rate = nothing); the
  grade is. Young-WR priors are DONE (age curve + grade residual shipped).

## 2nd-year high-route WRs (backtest_wr_yr2_routes.py) - REJECTED 2026-09-16

Jack: "build the 2nd-year high-route WR layer next." The young-WR study's
"high routes & 2nd year x1.2" lean (-1.50%, 4/6) was 155 rows. Every
threshold form, LOYO vs shadow v2.6:
- Reads (actual / shadow prior): top tercile 1.21 (n155), above median
  1.14 (n379), >= 300 routes 1.08 (n693), >= 400 1.10 (n479), route rate
  top tercile 1.01 (n431), ALL 2nd-year WRs with a grade 1.07 (n1084).
- Forms: top tercile x1.2 -1.08% (4/6) lean; above median +0.15%, >= 300
  +0.38%, >= 400 +0.30% (all FAIL - the wider the threshold, the worse);
  route rate: 1.0 every fold; top tercile & high grade +1.18% (0/5); top
  tercile & NOT high grade x1.3 -2.86% (5/5) "PASS" on n 77 but FORWARD
  -0.74% (2/5); 2nd+3rd year -0.17% (4/6); all 2nd-year control +0.18%;
  bottom tercile x.9 -0.20% (4/6) lean.
- Verdict: REJECTED. The lean was a small-sample artifact (the top tercile
  of 2nd-year WRs is ~25 player-seasons); the signal vanishes at any wider
  cut and the route rate carries nothing. 2nd-year WR priors: the v2.6
  low-snap boost (opposite population) stays; nothing for full-timers.

## 2nd-year low-route WRs (backtest_wr_yr2_lowroutes.py) - REJECTED, v2.6 boost confirmed 2026-09-16

Jack: "build the 2nd-year bottom-tercile routes layer next." The 2nd-year
high-route study's "bottom tercile x.9" lean (-0.20%, 4/6, n 533) split by
the v2.6 part-timer boost (x1.2 for < 40% late snaps): 151 of the 533 rows
carry the boost, 382 do not; every boosted 2nd-year WR is in the bottom
tercile (the two definitions overlap one way). LOYO vs shadow v2.6:
- Boosted rows x m: +1.39% (1/5) - any dock on top of the x1.2 hurts, and
  the boost re-check picks .85 pooled but 1/5 -> KEEP x1.2 (the read:
  boosted rows act/prior 1.10, act/shadow 1.01 = the boost is calibrated).
- Not-boosted bottom tercile x.9: -0.01% (2/6) - nothing. Route RATE bottom
  tercile: -0.07% (2/6, and it wants a BOOST 1.1). Routes < 150: +0.92%,
  < 250: +0.82% (worse). Bottom tercile & low grade: -0.19% (3/6, wants
  1.1); & high grade x.8: -1.30% on n 68 (2/3). 2nd+3rd yr: +0.18% (0/6).
  Candidate (whole bottom tercile x.9): -0.25% (4/7), FORWARD -0.09% (3/5).
- Verdict: REJECTED. The lean was the two populations mixed; the v2.6
  low-snap boost is the right piece and stays. 2nd-year WR route work is
  DONE (high routes rejected, low routes rejected, boost confirmed).

## Bottom-tercile low-grade WR boost (backtest_wr_lowgrade_boost.py) - REJECTED, with a PLACEBO 2026-09-16

Jack: "build the bottom-tercile low-grade WR boost layer next." The
2nd-year low-route study's sub-subgroup (2nd year & bottom-tercile routes
& low grade, n 304, "wants 1.1", 3/6). LOYO vs shadow v2.6:
- Target x1.15: +0.43% (3/6) FAIL. Generalisation: same group 3rd+ year
  1.0 every fold (0/6); all WRs 1.0 (0/6). Split by the v2.6 boost: not
  boosted +0.40% (0/6), boosted x1.3 -0.90% (2/4). Low grade any routes
  +0.38% (1/6). Neighbour (mid grade) 1.0. Candidate forward -0.11% (1/5).
- PLACEBO: 20 random 2nd-year WR groups of n 304 through the same LOYO
  multiplier procedure: mean +0.29%, best -1.41%, 30% reach <= -0.3%, 35%
  get >= 4 seasons better, 0% get >= 5. => a "lean" (4/6, -0.2 to -0.5%) on
  a few hundred rows is what NOISE produces; the >= 5-season bar plus the
  forward check is the real gate. This is why the recent chain of leans
  (young high-route, 2nd-year high/low routes, low-route TE) all failed.
- Verdict: REJECTED. Subgroup-of-subgroup layers are DONE; the shadow's
  remaining pieces must come from the live scorecards, not from slicing
  the same 19k rows further.

## W2 outlier read -> shadow v2.8 = backup-QB rule + docks for everyone (outliers_week.js) - 2026-09-16

Jack: "which players are the biggest outliers for week 2 clay vs no clay".
outliers_week.js N runs the engine headlessly and lists |ncMean - mean|
both ways (data/outliers_w{N}.json + data/outliers_week.js -> ZONES panel).
- FIRST RUN EXPOSED A DEFECT: the whole "shadow higher" list was backup QBs
  (Mariota 14.5, Winston 14.1, Mac Jones 13.2, McCarthy 15.0 ... vs live
  0.5): their history is their starting days and the shadow never asked
  whether they start. All were OUTSIDE the ADP gate (ADP > 200 -> v1 path:
  raw history, no docks). The harness cannot see this - backups who did not
  play are never graded; the live scorecard filters on the SHIPPED mean so
  they never showed up there either. Same defect for a no-history deep RB
  (Jordan James 11.5 = position mean, no string dock on pos-mean rows).
- FIX (v2.8, Clay-free): (1) backup QB rule - a QB at chart string 2+ or
  unlisted on a charted team gets a backup-level prior (NC_SHADOW.qbBackupPpg
  1.0 half-PPR) unless the injury layer says he inherits (iA > 1); ncSrc
  '+qb2' / '+qbx'; kill SIM_NC_QB2 = false. (2) the string docks (vetDock)
  now apply to every non-rookie with a Clay-free prior - gated or not, and
  pos-mean rows - not only hist/l8 rows inside the ADP gate. QB mean |diff|
  vs live 4.04 -> 1.55; live mean untouched (verify 0 of 493 rows).
- AFTER THE FIX, the real W2 disagreements: shadow HIGHER on QBs it rates
  (Brissett +4.4, Caleb Williams +3.4, Bryce Young +3.1, Watson +3.0 - QB
  is the shadow's best position, -4% vs Clay historically), a rookie the
  chart lists as a starter (Omar Cooper Jr. +4.9), and ungated vets with
  raw history (Hollins +4.8, Hollywood Brown +3.6). Shadow LOWER on TUA
  (-10.0: the ESPN chart lists Penix first, so the shadow calls Tua the
  backup; the live Clay window says Tua starts weeks 1-8 - a disagreement
  for Jack / QB_ROOM_OVERRIDES, not a bug), age-curve RBs (McCaffrey -3.7,
  Cook -2.9, Barkley -2.6), young stars the market/history read lower
  (Hampton -2.9, Warren -2.5, Kittle -2.5), and string-docked backups
  (Brooks, Dowdle, White). Per position mean |diff|: QB 1.55, RB 1.63, WR
  1.09, TE 1.27.

## Depth chart x availability rule (Jack 2026-09-16) -> engine effectiveString - shadow v2.8b

Jack: "for depth chart situations like Tua or anyone else we can ignore it
for weekly until a player is healthy, or if a player is injured we follow
the depth chart until something is changed - if a player is on IR or PUP or
listed as out we keep them out until we get a report they are playing, and
vice versa." Tua (ATL) was the case: ESPN lists Penix QB1, but Penix is
Questionable and has not played; the shadow's backup-QB rule had capped
Tua at 4.2 (live 14.2).
- engine.js chartAvailable(name, wk): a chart player is unavailable while
  the injury layer zeroes him (Out / IR / PUP / suspended: injAdj 0) OR he
  carries a designation (Questionable / Doubtful / Out tag, or a non-Active
  Sleeper status) AND has no 2026 game yet. Once he plays (jsData g > 0) or
  the tag clears he is available again ("vice versa"). effectiveString(p,
  wk) = the player's string among AVAILABLE chart players (WR 3 slots);
  _poolByNorm (set in buildPlayers) supplies the injFlag by name.
- Every shadow chart read now uses effectiveString: backup-QB rule, string
  docks, rookie string, buried-rookie ramp. depthString (raw chart) stays
  for the pool builder. Result: Tua 14.5 (shadow) vs 14.2 (live); Mariota
  1.0, Flacco 0.8 (backups); QB mean |diff| vs live 1.55 -> 1.25; live mean
  untouched (verify 0 of 493). Players marked Out are already zeroed by the
  live injury layer on both sides.

## Shadow IR / PUP / OUT layer -> v2.9 (engine shadowOut) - 2026-09-16

Jack: "build the IR PUP OUT layer for the shadow next" (his rule: keep IR /
PUP / Out players out until a report says they are playing, and vice
versa). The live injury layer already zeroes them for BOTH numbers, but
only for the 4-week IR minimum (then the projection returns) and it hands
a returning player his full number the moment the zero lifts.
- engine shadowOut(p, wk): Sleeper injury_status IR / PUP / NFI / Out /
  Sus / DNR / COV, or a non-Active roster status -> shadow ncMean = 0 for
  as long as the status persists (the daily Sleeper pull is the report);
  released the day the status changes. IN_SEASON_OUT_OVERRIDES wins (out
  inside its window, playing outside). NA (exempt list) follows the live
  layer's read (zero only when Sleeper's own weekly projection is 0).
  ncSrc '+out:<tag>'. chartAvailable also uses it, so an IR player beyond
  the live 4-week window no longer holds a chart slot. Kill: SIM_NC_OUT.
- W2: 8 skill players held at zero (6 IR incl. A.J. Brown, Jacobs NA,
  Darnold override) - all already zero live; the two layers diverge from
  week 5 on, when the live 4-week IR cap expires but the status has not
  changed. Live mean untouched (verify 0 of 493).
- Not covered on purpose: Questionable / Doubtful game-week tags (live
  docks apply to both), and "reported playing" beyond the status change -
  QB_ROOM_OVERRIDES / IN_SEASON_OUT_OVERRIDES remain the manual levers.

## Questionable / Doubtful on the shadow -> v2.10 returning-player dock (backtest_qd_shadow.py) - 2026-09-16

Jack: "build the questionable doubtful layer for the shadow next." Each
game-week designation (official reports 2019-25) graded on the shadow with
the live docks (Doubtful x.5, Q+DNP x.75, Q+LP/FP x1) already applied, so
every sweep is the EXTRA multiplier the shadow wants:
- Reads (actual / shadow): Q-FP .91, Q-LP .91, Q-DNP 1.10 (the live x.75
  already overshoots on the shadow), Doubtful n 3. Split by last week:
  Questionable & PLAYED last week ~.94-1.00; Questionable & MISSED last
  week .80 (FP) / .84 (LP) - the returning player is the whole effect.
- Sweeps: Q-DNP x m FAIL (+0.77%, wants 1.1 = noise); Q-FP x m FAIL
  (+0.12%); Q-LP x.9 -2.95% (5/7) PASS but forward 3/5; by position only
  WR passes (x.9 / x.85) and forward 3/5, 1/5.
- SHIPPED: Questionable (any practice status) & missed last week x.85:
  -8.12% vs shadow (5/7), affected rows -8.88% (6/7), FORWARD its rows
  -10.06% (5/5), all rows -0.15% (5/5). By position RB -3.4% (4/7), WR
  -10.8% (5/7), TE +3.9% (2/7, n 62) - shipped position-agnostic (the pooled
  and forward tests are what passed). Starter-only x.9 -3.3% (5/7).
- Engine v2.10: NC_SHADOW.qRet {mult .85}: p.injFlag Questionable, wk >= 2,
  and the 2026 record shows no game in wk-1 (sim_2026 players[norm].wks; no
  2026 record = missed) -> ncMean x.85 on top of the live dock; ncSrc
  '+qret'. Bye weeks count as "missed" exactly as in the harness. Kill:
  window.SIM_NC_QRET = false. Doubtful: untestable (n 3) - live x.5 stays.
- Reading: the history prior does not know a player is coming back from an
  injury; the live Clay number runs hot there too (.86) but less. This is
  the shadow's version of Jack's "keep them out until a report says they
  are playing": a returning Questionable player is priced at 85%.

## Doubtful on the shadow (2026-09-16) - ALREADY PRICED, nothing to build

Jack: "build the doubtful layer for the shadow next." The harness cannot
grade Doubtful the usual way (3 played rows in 7 seasons), so the number
was measured as an expected value from the official reports x the weekly
DB, pool players 2019-25 (scratch _doubtful.py, printed in this session):
  class      n     P(play)  pts when played / season PPG   EV multiplier
  Q-FP       309   .786     .959                            .754
  Q-LP      1100   .670     .906                            .607
  Q-DNP      257   .490     .814                            .399
  Doubtful   200   .015     .683 (n 3)                      .010
  Out       1183   .001     -                               .001
- The live engine's BANGED-UP docks (engine BANGED, backtest_banged_up.py
  09-15) already carry exactly this: D play .005-.02 x cond 1.0 (EV ~.01),
  Q-DNP .42-.52 x .88, Q-LP .54-.77 x .94, Q-FP .82-.90 x .95 - and the
  shadow inherits them through iA in the shared chain. A Doubtful player is
  ~1% of his number on BOTH sides. NOTHING TO BUILD.
- Harness note for the record: backtest_dropped_vets / backtest_qd_shadow
  applied LIVE_DOCK {D .5, Q-DNP .75, Q-LP 1, Q-FP 1} (the putDock defaults)
  rather than the banged EV values; on PLAYED rows the difference is the
  P(play) factor, which the scorecard (played rows only) does not grade.
  The v2.10 returning-Questionable x.85 was measured conditional on playing
  vs the class average (.84 vs ~.94) - on live it stacks on the banged EV
  dock, i.e. it is the conditional correction, slightly strong (.85 vs the
  .89 ratio); watch it on the scorecards.

## Out on the shadow (2026-09-16) - ALREADY COMPLETE, nothing to build

Jack: "build the out layer for the shadow next." Measured P(play | Out) =
0.1% (1 of 1,183 pool designations 2019-25). Both halves of an Out are
already on the shadow: (1) the player -> 0: the live injury layer zeroes a
game-week Out (NFL report or Sleeper tag) for both numbers via iA, and
shadowOut (v2.9) holds IR / PUP / Out / non-Active at 0 for as long as the
status persists; (2) the vacated role -> teammates: applyInSeasonInjuries
redistributes the zeroed player's share to the healthy group by depth
rank (iA > 1), and the shadow chain carries the same iA on its own base.
Verified W2 headless: 8 zeroed rows are 0 on both sides (and stay 0 with
SIM_NC_OUT off - the live iA alone covers the current week); 48 teammates
carry iA > 1 on both (Drew Lock iA 26.7 -> live 12.8 / shadow 12.7 - the
backup-QB rule skips its cap when iA > 1, as designed). The availability
family on the shadow is closed: IR / PUP hold, backup-QB rule, chart
availability, returning-Questionable dock, Doubtful (EV .01) and Out (0).

## Vacated role on the shadow -> v2.11 boost^0.75 (backtest_vacated_shadow.py) - 2026-09-16

Jack: "build the vacated role layer for the shadow next." Live, a zeroed
player's share is redistributed to healthy teammates by depth rank
(applyInSeasonInjuries -> iA > 1) and the shadow inherited that multiplier
at full strength - a ratio computed on the Clay base. Graded on the shadow
with build_live_layers.py's share-rebuilt pool_mult (Clay-free by
construction; 5,926 boosted player-weeks of 17,556 joined):
- Reads (actual / shadow WITHOUT the layer): boosted rows 1.06; by size
  x1.00-1.05 1.00 (nothing to add), x1.05-1.15 1.07, x1.15-1.4 1.18, > x1.4
  1.41; RB 1.13, WR 1.03, TE 1.06. The layer is real and biggest where the
  vacancy is biggest.
- Strength sweep shadow x boost^k, LOYO vs shadow: k .75 best, -1.07%
  (6/7) PASS (k 1 = live strength is over-strong on the shadow base); RB k
  .75 -3.96% (5/7); WR k .5 -0.39% (3/7); TE k .5 -0.19% (4/7); boosts <=
  x1.05 k 0 (nothing); x1.05-1.15 -0.75%; > x1.15 -4.20% (6/7). Backup-QB
  inheritance: 11 rows, untestable. Candidate boost^.75: boosted rows
  -1.28% (6/7), all rows -0.38% (6/7), -1.62% vs shipped (7/7); FORWARD
  boosted -1.46% (5/5), all rows -0.44% (5/5).
- Engine v2.11: NC_SHADOW.vacatedK {QB 1, RB/WR/TE .75}: when iA > 1 the
  shadow chain is scaled by iA^(k-1) (docks iA <= 1 untouched); ncSrc
  '+vac'. Kill: window.SIM_NC_VAC = false. Known approximation: the live
  iA is (vacated live points x weight) / live base, applied to the shadow
  base - an exact shadow-unit redistribution would need a team pass over
  shadow numbers; the softened exponent absorbs most of the difference.
- Ladder vs shipped (2019-25): v2.7 -1.28% -> v2.11 ~ -1.62% (7/7).

## Exact shadow-unit redistribution -> v2.12 (engine weeklyProjection) - 2026-09-16

Jack: "build the exact shadow-unit redistribution layer next." v2.11 applied
the LIVE teammate boost (a ratio of Clay-base points) to the shadow base,
softened to ^.75. v2.12 computes the vacated role in the shadow's own units:
- ncFull = the player's shadow number as if healthy (chain without the
  availability factor); ncOwn = ncFull x availability (live docks, zero,
  shadowOut). Per team|position group and week: lost = sum over out /
  docked teammates of ncFull x (1 - availability). QB: 85% of lost to the
  next available QB on the chart (best effective string, tie = higher own;
  no cap - the next man up inherits outright). RB/WR/TE: 60% of lost spread
  over healthy teammates by ncOwn x depth weight (1.6 / 1.0 / .5 by
  effective string, unlisted .25), x strength .75 (vacatedK), gain capped
  at the player's own number (the live share path caps f at 2). Mirrors
  INJ_SHARE and DEPTH_W; the live opportunity-POOL cross-position flow (a
  WR's targets to TEs / RBs) is NOT mirrored - same-position groups only.
- Mechanics: teammates come from a per-(week, scoring) cache (_ncCache,
  key = week + scoring weights) filled by a guarded pass over the pool
  (_ncPass prevents nesting); cache reset in applyInSeasonInjuries and via
  E.ncCacheReset(). Cost: the exact pass ~4x the legacy shadow arithmetic
  (90 vs 21 ms for 429 players) - negligible next to the Monte Carlo. ncSrc
  '+vacx'. Kill: window.SIM_NC_EXACT = false (falls back to v2.11 ^k).
- W2 check: 35 absorbers; exact vs v2.11 mean |diff| ~0.05 pts on all rows
  (the softened ratio was a good approximation for RB/WR/TE); the material
  difference is the QB next-man-up, priced from the OUT QB's shadow number
  instead of the backup's tiny live base; live mean untouched (0 of 493).

## Cross-position target flow on the shadow -> v2.13 (engine weeklyProjection) - 2026-09-16

Jack: "build the cross-position target flow layer next." v2.12 redistributed
a lost shadow number inside the same team|position group only. v2.13 mirrors
the live opportunity POOL rules, in shadow units:
- The guarded pass now covers ALL of a team's pass catchers (RB/WR/TE) for a
  skill player (QB room unchanged: 85% to the next available QB, no cap).
- rf = the player's receiving fraction of production from his Clay stat mix
  (rec + rec yds + rec TD vs rush yds + rush TD; a shape only; default RB .35,
  WR/TE 1). An absent player Z loses lostRec = ncFull x rf x (1 - avail) and
  lostRush = ncFull x (1 - rf) x (1 - avail).
- Rule = POOL[Z.pos][lead | sec], lead = Z had the team's top receiving level
  (ncFull x rf) among its pass catchers. Healthy same-position teammates are
  ranked by effective string (tie = higher own) and the i-th gets
  tgtSame[i] x lostRec x POOL_EFF_T (.92) + carSame[i] x lostRush (RB only).
  If tgtOther > 0, the other NON-RB pass catchers split tgtOther x lostRec in
  proportion to their own receiving level (ncOwn x rf) - a WR's targets reach
  the TEs and the other WRs, a TE's reach the WRs, an RB's reach WR/TE; RBs
  never receive cross-position targets (same as live). Sum over every absent
  Z, x vacatedK .75 (the strength fit on the live pool_mult in
  backtest_vacated_shadow.py, i.e. this POOL form), gain <= own. ncSrc '+vacx'.
- Kill: window.SIM_NC_EXACT = false still falls back to the v2.11 ratio.
- W2 check: 49 absorbers (35 in v2.12). New reach: A.J. Brown (out:ir) now
  lifts Hunter Henry / the NE WRs by the WR.lead rule (Doubs 8.0, Hollins
  6.8, Henry 6.7); GB's absent WR/TE reach Lloyd (8.4 - was 9.5 under the 60%
  form; the RB.sec carSame .28 is what live gives an RB1), CLE's Sampson (IR)
  reaches Judkins 9.4 and Fannin 7.2; Lock 13.4 unchanged. Live mean
  untouched (0 of 493), clay-fallback inside the ADP gate 0.

## Where Clay beats the Clay-free shadow, by player type (research_clay_vs_shadow.py) - 2026-09-16

Jack: "is there any correlation in which type of players clay is more successful
in a large sample vs the non clay shadow." Same 2019-25 harness as the ladder
(19,064 Clay-pool player-weeks, half-PPR, Vegas x FPA on both sides); shipped =
P=5 blend of Clay's season PPG with season-to-date, shadow = the v2.11 harness
form. Per cut: n, shadow MSE vs Clay (negative = shadow better), seasons the
shadow wins of 7, bias act/proj each side. Log clay_vs_shadow_research.log,
data/clay_vs_shadow_research.js (SIM_CLAYSEG), ZONES panel.
- Overall shadow -1.62% (7/7). Clay's ONLY repeatable edges: players with no
  depth-chart entry (n840, +2.65%, shadow 3/7) and week 1 before any data
  (n1407, +0.33%, shadow 2/7) - his preseason information edge lives in the
  first week and in the players the chart does not describe. By position:
  QB string 2+ (n128, +12.8%: backups, small n), WRs with no history (n352,
  +4.2%), WRs with no ADP (+0.5%), TEs Clay is bullish on vs history (n925,
  +1.5%) and cold TEs after 3+ games (+0.6%).
- The shadow's edges are the bottom of the pool and the young: rookies -5.4%
  (6/7; R3+/UDFA -6.2%, R1-2 -5.0%), Clay's lowest PPG quartile -5.0%, no
  history -5.7%, QBs -4.0% (7/7), vacated-role weeks -2.7% (7/7), games 1-3
  -2.7% (7/7), and every row where the shadow sits > 1.25x the Clay blend
  (n2863, -6.4%, 6/7) - when the two disagree upward the shadow is right.
- Caveat: Clay's harness PPG = season points / 17 games, so his blend runs
  low on players who miss games (act/proj 1.13-1.22 on the bottom quartiles,
  1.00 on the top); part of the shadow's bottom-of-pool edge is that
  denominator, not information. On the top half (ADP 1-60, Clay Q3-Q4, string
  1 vets) the two are within ~1% and Clay's bias is ~1.00.
- No player TYPE where Clay wins by a repeatable margin on a big cut. The
  useful residual signal is week 1 / no-chart, i.e. preseason role knowledge,
  which is exactly what the shadow's ADP prior + depth string approximate.

## Beat Clay where he still wins -> v2.14 no-chart veteran dock (backtest_beat_clay.py) - 2026-09-16

Jack: "do we have any way to improve ours to beat clay?" The shadow already
beats the Clay blend overall (-1.62%, 7/7); the segmentation left Clay four
cuts. Five Clay-free fixes, LOYO vs the shadow itself, then forward:
- A. week 1 lean on the ADP curve: FAIL (+0.56%, 2/7; forward +1.47% 1/5).
  Rookies hate it (0/7), veterans 4/7 at a=.5 but not at the bar. B. week 1
  shrink to the position mean: picks 1.0 everywhere (nothing). Clay's week-1
  edge is real preseason role knowledge, not something the market or a shrink
  can buy.
- C. no-chart veterans x m: all rows -1.05% (4/7, lean); split by season
  stage: 4+ games in x1.0 (the data has fixed it), FIRST 4 GAMES x0.8 -9.02%
  (5/7) PASS, n228; forward on that exact subset -14.6% (4/5, picks .9 .85
  .8 .8 .8); placebo 0 of 300 random n228 groups of <4-game vets reach -9%
  and 5/7 (median +0.00%, 5th pct -0.48%). RB 119 rows act/shadow .80, WR 64
  rows .72, TE 38 rows .78 - the shadow over-projects a vet the chart has not
  placed by ~25% until his games say otherwise (late signings, camp bodies,
  returning vets). Late joiners (g<4 after week 4) are the worst (.70).
- D. WRs with no history x m: +0.17% (nothing; the 16 non-rookie rows are the
  whole effect). E. TEs the market rates > 1.2x history, lean to market: 0.0
  picked everywhere (nothing).
- Engine (shadow only): after the blend, ncBaseW x NC_SHADOW.noChart.mult
  (.8) when !rookie, RB/WR/TE (vetDock positions), depthString(p) == null on
  any team, and games played this season (jsData wks < wk) < noChart.games
  (4). ncSrc '+nochart'. Kill: window.SIM_NC_NOCHART = false. W2: 3 rows
  (Gainwell TB 6.1, Marquise Brown PHI 4.2, Palmer BUF 3.6); live untouched
  (0 of 493). Data data/beat_clay_backtest.js (SIM_BEATCLAY_BT), ZONES panel.
- Remaining Clay edge after this: week 1 only (n1407, +0.33%, shadow 2/7) -
  ~0.3% on 7% of the rows. There is no Clay-free lever left for it short of
  a preseason role model; a week-1-only Clay blend would keep it if wanted.

## Season-long harness: Clay's sheet vs Clay-free preseason priors (backtest_season_long.py) - 2026-09-16

Jack: "lets build the season long first and try to beat out clay with all the
data we have including the advanced data." New harness, one row per
player-season 2019-25 on Clay's pool (1,404: QB 202, RB 352, WR 573, TE 277),
target = actual full-season half-PPR PPG over games played (4+), Clay = season
pts / his projected games (the fair per-game number; the /17 form the weekly
harness uses is +16.8% worse and biased 1.12). Games-weighted MSE, seasons
won of 7, Spearman inside season x position, top-24 (TE 12) hit rate. All
candidates walk-forward; learned fits per position leave-one-year-out with
median-impute + missing indicators, then FORWARD 2021-25 on earlier seasons.
- Hand priors all LOSE to Clay season-long: history+age +10.1%, the weekly
  shadow's preseason prior +4.8% (2/7), the ADP curve alone +32.7%, shadow x
  market +6.2%. Clay's preseason edge is real at the season horizon.
- ridge basic (log ADP + no-ADP flag, history, h3, l8, age, exp, rookie, log
  pick, week-1 string dummies, team change, opportunity prior, 2nd-yr late snap
  share; alpha 10): -10.1% vs Clay LOYO (4/7), rho .719 vs .697, bias 1.000.
  FORWARD -5.2% (3/5): WR -14.4% (5/5), TE -2.3% (3/5), RB -0.4%, QB +3.5%;
  veterans -5.0% (4/5), rookies -30.9% (5/5; Clay's rookie MSE 11.7 vs 8.1),
  no-ADP players -25.0% (4/5); top-60 ADP +16.2% (Clay still owns the stars).
- Every richer set overfits 1,400 rows: +ctx (prior-yr shares, xFP, team pass
  rate, coach tendencies, JM, OL grades) -2.1% LOYO but +8.1% forward; +PFF
  advanced (route rate, YPRR, TPRR, aDOT, grades, alignment, YAC, drops, RB
  YPA/YCO/elusive/breakaway/gap share) +4.5% LOYO, +26.3% forward; boosted
  +1.0% / +4.4%. The advanced data does not add season-long signal beyond
  ADP + history + string; it adds variance.
- Ensembles (information only, still Clay): 0.5 ridge basic + 0.5 Clay
  -13.0% forward (5/5), rho .704 - the two disagree usefully.
- Strongest standardized coefficients: QB hist +3.0; RB hist +3.7, xFP/g
  -2.0 (xFP over-states RB level), ADP -1.1; WR hist +4.6, slot +2.6 / wide
  +2.6 (alignment volume), l8 -2.3; TE xFP/g -1.5, h3 +1.4.
- Nothing applied. Next: put ridge basic in as the shadow's preseason prior
  and grade it on the WEEKLY harness (a better season prior should carry the
  first 4-6 weeks); keep Clay for top-60 ADP if the weekly test says so.
  Data data/season_long_backtest.js (SIM_SEASON_BT), ZONES panel;
  season_long_table.parquet has the feature table.
- Ops note: C: filled to 0 bytes mid-run (Bash stdout + sed temp live on C:);
  run with TMP/TEMP pointed at sim_lab/_tmp on E: and output to a file.

## Learned season prior in the weekly shadow, week 1 included -> v2.15 (backtest_learned_prior_weekly.py, build_ridge_prior.py) - 2026-09-16

Jack: "lets continue on sims testing on past seasons and even week 1." The
season-long ridge (ADP, history, age, rookie pick, week-1 string, opportunity
prior, 2nd-year snap share) dropped into the weekly harness in place of the
shadow's hand-built preseason prior; same blend / layers / ramp / vacated
boost on top. Graded vs the shadow and vs the Clay blend by season stage.
- Full replacement, LOYO: all weeks -0.41% vs shadow (5/7), -2.02% vs Clay;
  week 1 -2.27% vs shadow (6/7) and -1.95% vs Clay (4/7) - the first time the
  shadow beats Clay at week 1; games 1-3 -2.33% (5/7); games 4-8 / 9+ flat
  (+0.25 / +0.43: once the season data is in, the prior stops mattering).
  By position all weeks: WR -1.15% (5/7), RB -0.50% (5/7), QB +0.76, TE +0.27.
- Mix sweep a x ridge + (1-a) x hand prior: pooled best .75, LOYO -0.57%
  (6/7) PASS; week 1 wants .75 (-2.70%, 6/7), games 1-3 .75, games 4-8 .5,
  games 9+ .25, QB .25, RB .75, WR .75, TE .5. Prior strength P x k: 1.0
  (RB/WR lean 1.5, QB/TE .75) - left at the v2 strengths.
- FORWARD (ridge fit on earlier seasons only, 2021-25; 46-170 training rows
  per position in the early years): full replacement FAILS (+0.45% all, week
  1 +1.43%, 2021 +5.1% at week 1 - the 2-season fit is noise); the 0.5 mix
  PASSES: all weeks -0.48% (4/5), week 1 -1.35% (5/5) / -1.94% vs Clay (4/5),
  games 1-3 -1.74% (5/5), games 4+ -0.04%; 0.25 mix -0.42% (5/5). Shipped
  at 0.5: the hand prior halves the damage while the fit is small, and the
  LOYO gain at .5 is within 0.01 of .75.
- Engine (shadow only): data/ridge_prior.js (SIM_RIDGE_PRIOR: per-position
  medians, missing-indicator columns, mu/sd, coefficients, intercept; fit on
  all 2019-25, games-weighted, alpha 10, `mover` dropped - no live field,
  LOYO -10.23% vs Clay without it vs -10.07% with). engine ridgePrior(p, wk,
  oppHalf) rebuilds the vector live (consensus ADP > 181 or missing -> 181 +
  flag; hist = 0.5 h3 + 0.5 l8 half-PPR raw; rookie pick else 262; raw chart
  string 1/2/3+/none; opportunity blend when it applied; SIM_SNAPS_PRIOR for
  exp 1). After the '+shr' shrink: ncPrior = ridgeW (.5) x ridge + .5 x hand
  prior (half-PPR, x scale); the backup-QB cap is re-applied. Tag '+ridge';
  kill window.SIM_NC_RIDGE = false. export_site_proj.js loads the file.
- W2 headless: +ridge on 185 of 429 shadow rows (the ADP-gated Clay-free
  ones); mean |move| QB .36 RB .46 WR .43 TE .26, max 1.2 (Love -1.2,
  Tracy +1.1, Kittle +1.1); live mean untouched (0 of 493). Data
  data/learned_prior_weekly.js (SIM_LPRIOR_BT), ZONES panel.

## Clay games divisor -> LIVE (engine clayDiv) - 2026-09-16

Jack: "is there anything that stands out ... lets do it if it actually
improves the numbers." The weekly mean divided Clay's season points by 17 for
everyone; his sheet projects games (gm) per player, and the season sim already
used gm/17 as the games-played probability (re-inflating the /17 mean by
17/gm). Weekly, a player Clay expected to miss time projected low on every
week he did play, and the injury layer docked the absence again.
- Harness 2019-25 (Clay pts/gm instead of pts/W in the shipped blend): 78% of
  player-weeks sat on a season with gm < full; ALL rows -0.74% MSE (6/7),
  affected rows -0.95% (6/7), QB -3.8% (6/7), RB -0.45% (6/7), WR/TE flat;
  gm 11-14 -1.1% (6/7), gm <= 10 -19% (5/6); first 4 games -1.7%; Clay bias
  act/proj 1.047 -> 0.998 (the low bias every comparison this session showed).
- Engine: clayDiv(p) = clayGames when 4 <= gm < 17 else 17; used by
  weeklyProjection's perGameDiv (explicit qbWindow games still win), the
  market-observation window and the RB snap-usage level. Season sim keeps
  pPlay = gm/17 but inf = 1 (the mean is already per game); the reported
  seasonProj = sum of weekly means x pPlay so it equals Clay's season again.
  Kill: window.SIM_CLAY_GM = false.
- Live impact 2026 is small because most gm < 17 players carry an explicit
  window (Charbonnet, Tyson, Pacheco, Kamara, Penix, Bowers, Henderson) which
  already divided by the window's games: only Josh Jacobs (gm 11: W9 9.1 ->
  14.0 when back), Kaleb Johnson and Emanuel Wilson (gm 6) and Minshew move.
  Season sim for Jacobs unchanged (mean 156 / p50 167 / p90 246 before and
  after; seasonProj 162 both). Shadow untouched (scale uses the same divisor).
- Regrade of the shadow vs the CORRECTED (per-game) Clay blend, 2019-25:
  v2.11 form -1.62% (7/7) -> -0.89% (4/7); v2.15 (ridge 50%) -2.27% (7/7) ->
  -1.55% (7/7). By stage vs corrected Clay, v2.15: week 1 -3.60% (6/7), games
  1-3 -2.54% (7/7), 4-8 -0.54% (5/7), 9+ -1.50% (7/7). By position: QB -0.94%
  (3/7, the one soft spot - the per-game fix was worth 3% to Clay's QBs), RB
  -2.25% (5/7), WR -1.58% (7/7), TE -0.79% (5/7). The divisor fix took ~0.7%
  off the shadow's margin; the ridge prior put ~0.65% back. The harness
  "shipped" reference still uses /W - compare against per-game from here on.

## Risers in the top 60-150 (backtest_risers.py) - NOTHING SHIPS; ADP-tier regrade - 2026-09-16

Jack: "why are the top 60 adp so much better for clay?" then "is it because
players fall off or ascending players ... that clay dominates", and the rule
"focus on top 150 but most importantly top 60 to top 100; the higher adp
players are more important to hit on" (memory feedback_projection_focus_top150).
- Inside the top 60 the ridge and Clay are level when they agree (318 rows
  within 2 pts: ridge MSE 8.92 vs Clay 9.04). Clay's whole edge is the 24
  player-seasons he projected 2+ pts ABOVE the ridge: actual 15.2, Clay 15.6,
  ridge 13.0 - Gibbs 2023/24, Bijan 2024, Henry 2019, Kelce 2020, Andrews
  2023, Allen 2021, Chubb 2020. Ascending 2nd/3rd-year players whose role
  grew; NOT decliners (McCaffrey 2021, Stroud 2024 - both missed by both).
  Why ours misses: history is the dominant coefficient (anchors to last
  year) and ADP enters as a log (pick 36 -> 9 barely moves it); slope of
  actual on prediction inside the top 60 is .84 (ridge) vs .91 (Clay), QB
  .46 vs 1.10, TE .59 vs .80 - compressed exactly where the stars separate.
- Fixes tried (LOYO + forward, by tier): +growth (exp-2/3 flags, hist x
  young, age<=25 x hist, ADP x young), +linear ADP inside the top 60, both,
  split young/vet fits, fit on ADP<=150 only. NONE moves the 24 rows (mean
  prediction 13.0-13.3) and every one loses forward in the top 60 (+4 to
  +10% vs the base ridge) and the 61-100 band. The base ridge forward: top
  60 +13.5% vs Clay, 61-100 +5.7%, top 150 +6.1%. Only 0.5 ridge + 0.5 Clay
  beats Clay at the top (top 60 -1.1%, 61-100 -6.9%, top 150 -5.4%, 5/7).
  SEASON-LONG the top 150 is Clay's; the Clay-free edge is below 150.
- WEEKLY regrade by ADP tier (v2.15 shadow vs the corrected per-game Clay
  blend): top 60 -1.05% (6/7; wk1 -1.7, g1-3 -0.9, g4+ -1.0), 61-100 -1.38%
  (5/7; wk1 -3.2), 101-150 -1.24% (4/7), top 150 -1.17% (5/7), 151+ -2.47%.
  Top-150 by position: RB -2.13% (5/7), WR -0.94% (6/7), TE -0.52%, QB
  -0.23% (3/7). A 50/50 weekly ensemble of the two: top 150 -1.10% (7/7).
  Weekly, the shadow beats Clay in the tiers Jack cares about; the QB top-150
  row is the one to work on. Data data/risers_backtest.js (SIM_RISERS_BT).

## Vacated volume x depth chart at the start of the season (backtest_vacated_bump.py) - REJECTED - 2026-09-16

Jack: "can we try to add a vacated volume / depth chart check at the beginning
of seasons to try and give players a bump." Per player-season 2019-25 (pbp via
backtest_opp_prior.load_season): team vacated carry share (RB) / target share
(WR/TE) from players who left; leader-left flag; the player's Y-1 share rank
on the team; week-1 depth string. Tried as ridge features (LIVE + 5) and as
bump rules on the v2.15 shadow prior - x(1 + k string-1 x vacated), x(1 + k
promotion), x(1 + k vacated) - k per position LOYO on top-150 rows; forward.
- Every version loses in the top 150: ridge+vacated +0.56% LOYO / +1.32% fwd
  vs the shadow prior; string-1 x vacated bump +1.65% / +5.67%; promotion
  +1.05% / +3.99%. LOYO k picks are 0 for QB/RB and 0-0.25 for WR/TE.
- Why: the 24 top-60 riser rows Clay got right carry LESS vacated volume than
  the average top-60 player (0.30 vs 0.32), fewer promotions (25% vs 35%),
  same leader-left rate. Aaron Jones 2019 (vac 0), Chubb 2020 (0), Kelce
  2020 (.04), Henry 2019 (.08), Bijan 2024 (.16), Kamara 2024 (.17) rose on
  stable rosters by coaching decision; Gibbs 2024 was string 2 with 0.20
  vacated. The big vacated cases busted (Mike Davis 2021 vac 1.14 -> 5.5
  PPG; Montgomery 2019 .78 -> 9.9). Departures are not the riser signal, and
  the opportunity prior (oppcal) already carried the allocated vacated share.
- Nothing shipped. Data data/vacated_bump.js (SIM_VACBUMP_BT), ZONES panel.

## Top-150, importance-weighted (backtest_top150_weighted.py) - NOTHING SHIPS; weekly regrade under the weights - 2026-09-16

Jack: "lets focus on the top 150 and heavily weight the higher scoring players
since they are more important" (memory feedback_projection_focus_top150).
Weights = games x LEVEL^p, LEVEL = ADP-curve implied PPG, position-relative
(never the actual). The ridge is refit with the weights (p = 1, 2, 3; and
top-150 rows only x LEVEL^2), the mix a in {.5, .75, 1} re-chosen, and every
cell graded with the same importance-weighted MSE vs Clay's season sheet.
- Weighting the FIT changes almost nothing. At the shipped 50/50 mix the
  weighted fits sit within 0.2% of the plain fit LOYO and forward. Best LOYO
  = LEVEL^1, ridge 75%: -1.2% vs v2.15 in the top 150 (3/7) but +3.3% worse
  forward; ridge 100% / top-150-only fits blow up forward (+11 to +18%).
- Season-long under the weights: Clay wins the top 150 (+4.0% LOYO, +1.7%
  forward for the shadow prior); top 60 +6.4% / +4.6%; 61-100 +0.7% / -2.0%;
  101-150 -2.7% / -6.2%. The 50/50 shadow + Clay ensemble beats Clay -3.0% /
  -3.9% (5/7, 4/5). Season-long, top 150 = Clay's; ours only as a partner.
- WEEKLY under the same weights (v2.15 shadow vs the corrected per-game Clay
  blend): top 60 -1.17% (5/7), 61-100 -1.10% (5/7), 101-150 -0.94% (5/7),
  top 150 -1.13% (6/7); by stage top 150 wk1 -2.1, g1-3 -1.8, g4-8 -1.0,
  g9+ -0.7; RB -1.54% (6/7), WR -1.09% (6/7), TE -1.06% (4/7), QB -0.35%
  (3/7). The weekly edge survives the weighting in every tier.
- Data data/top150_weighted.js (SIM_T150_BT), ZONES panel.

## Preseason depth charts + the prospect model (JM) in the season prior -> v2.16 (JM only) - 2026-09-16

Jack: "maybe can we try finding depth charts from before the seasons and
maybe use our prospect model?" (top-150, high-scorer-weighted grading).
- PRESEASON CHARTS: not in the cache for 2019-24. nflverse depth_charts
  2018-24 carry REG/POST weeks only (game_type REG/WC/DIV/CON/SB); only the
  2025 file has ESPN daily charts from Aug 3. The week-1 chart (already the
  harness string) adds nothing season-long (with vs without the string
  dummies: top 150 +0.3% LOYO / +0.7% fwd). Getting August charts for
  2019-24 means scraping Wayback ESPN/Ourlads - not attempted.
- JM PROSPECT SCORE (data/jm_scores.json off the site, 1,372 players; 98%
  coverage exp <= 2, 51% exp 4+; missing -> median + indicator): as a plain
  ridge feature, importance-weighted top 150 vs the v2.15 prior: LOYO
  -1.22% (6/7), young top 150 -2.07% (6/7), 101-150 -3.64% (7/7), top 60
  -1.09% (5/7); FORWARD top 150 -0.93% (4/5), young -1.92% (4/5), 61-100
  +0.34% (2/5). Interactions (jm x young / rookie / yr2-3 / ADP) add
  nothing over plain jm. Hindsight check (JM weights are hand-tuned with
  knowledge of 2019-24 outcomes): the gain holds in the least-hindsight
  seasons (fwd 2024 -1.35% / young -2.02%, 2025 -2.00% / -4.55%) and the
  residual correlation by draft class is flat (.23-.26 for 2018-20, .15-.24
  for 2023-24, ~0 for 2021-22), so it is not a hindsight artifact. Weekly
  effect via the 50% season prior: neutral (top 150 -0.07% LOYO 7/7, fwd
  +0.01%; week 1 -0.6 / -0.7%).
- Shipped shadow-only as v2.16: build_ridge_prior.py LIVE + ["jm"]
  (LOYO -11.36% vs Clay pooled, was -10.23%); data/jm_scores.js (SIM_JM by
  norm name, from repo data/jm_scores.json - regenerate when
  pull_jm_scores.py runs); engine ridgePrior reads window.SIM_JM[p.norm];
  export_site_proj.js loads it. W2 headless: 171 of 186 ridge rows have a
  JM score, mean |move| 0.26, max 1.1 (CMC / Gibbs / Barkley / Bijan / Jeanty
  up ~1.0; Purdy -1.0, Shough -0.75); live untouched (0 of 494).

## Week-1 usage as a preseason-chart stand-in (backtest_week1_usage.py) - NOTHING SHIPS - 2026-09-16

Jack: "lets try it - we can also use route data for week one just to back
test, and next season i can set up the depth charts." The ESPN chart cannot
order receivers (every starter is depth 1 at his slot; 289 of 311 top-150 WR
seasons are string 1) and no August charts exist for 2019-24, so week-1 usage
stands in for a good preseason chart: PFF weekly receiving summary w1 (route
participation, routes / team top route runner, team route rank at WR+TE,
matched 994 of 1,202 non-QB rows) + nflverse snap_counts w1 (snap share, team
rank at the position, 1,291 of 1,404). Target = PPG over the games AFTER the
first game. Importance-weighted, vs the v2.16 prior (LIVE + jm) and Clay.
- Routes: top-150 WR -1.7% LOYO (5/7), forward -0.3%; 61-100 -1.1% / -1.7%;
  101-150 -1.8% / -1.6%; top 60 +0.2% / +0.8%; RB +1.0% / +0.6%; top 150 as
  a whole -0.27% LOYO (5/7) but +0.03% forward (3/5). Snaps similar; both
  together worse (+0.2% / +0.8% top 150). Ridge-heavier mixes fail.
- The 47 top-60 rows Clay projected 2+ above the prior do not move (13.32 ->
  13.27; actual 15.0, Clay 16.0): Aaron Jones 2019 (61% snaps, 40% of the
  top route share), Henry 2019 (61%), Kamara 2020 (66%), Kelce 2019 had
  ordinary week-1 usage - the role grew over the season. A perfect preseason
  chart would not have caught the risers; Clay's edge there is a volume
  call, not a depth-chart read.
- For next season's depth-chart setup: expect value at WR ordering and in
  the 61-150 band (~1-2%), not in the top 60. Data data/week1_usage.js
  (SIM_W1USAGE_BT), ZONES panel.

## Book-anchor weight sweep (anchor_sweep.py) - tool + first read; chained into Tuesday - 2026-09-17

The shipped mean is 70% market / 30% model (engine PROP_W). That weight was a
prior: no prop history exists before 2026, and the anchor has never been tested
with the Clay-free shadow underneath - which is why every shadow-vs-live table
on the board reads red (live = Clay + books, shadow = no books). anchor_sweep.py
runs over every scored lock (data/snapshots/simlab_snapshot_wN.json) against the
actuals (repo weekly_stats_active fpts = half-PPR, same as the lock preset):
market mean backed out of the lock (propMean = .7 market + .3 jsMean, rows with
propSrc 'line'), then w x market + (1-w) x BASE for w = 0..1, BASE = jsMean
(Clay side) and ncMean (shadow), plain and importance-weighted MSE, by
position and by week; anchored-shadow vs anchored-Clay head-to-head.
- W1 only so far (248 lined skill players; the W1 lock predates ncMean, so no
  shadow rows): plain MSE is minimised at w = 0.7 exactly (40.39; market alone
  40.73, model alone 42.03 -> the anchor is worth 3.9% over the model);
  importance-weighted best w = 0.5 but flat (57.63 vs 57.79 at .7). By
  position: QB .7-.8, RB 1.0, WR .8-.9 plain / .2 weighted, TE 0.0 (the model
  alone beat the market for tight ends). Bias act/proj: shipped .979, market
  .948 (books ran 5% hot in W1), model 1.061. One week - nothing changes.
- Chained into tuesday_stats.ps1 right after the scorecard (non-fatal), so it
  re-fits every Tuesday; the W2 lock is the first that stores ncMean, so the
  shadow sweep and the head-to-head start next Tuesday. README's original
  rule stands: revisit PROP_W after ~4 scored weeks. Data
  data/anchor_sweep.js (SIM_ANCHOR_SWEEP), ZONES panel.

## QB compression in the shadow -> v2.17: no ridge half for QBs (backtest_qb_compression.py) - 2026-09-17

Jack: "lets fix the QB compression in the shadow" (W2 read: shadow ~2 pts over
Clay on Mayfield / Stroud / Goff / Dak / Kyler, 2.6 under on Josh Allen). A vet
QB's prior passes through a 75% log-ADP market curve, the 0.8 shrink, the 50%
ridge half and P = 12; each swept for QBs only on the weekly harness (2,014
re-tunable vet-QB weeks of 2,759), graded on the weighted top-150 QBs vs the
current shadow and the corrected Clay blend, LOYO + forward.
- Weekly the shadow is NOT compressed at QB: slope of actual on prediction
  .91 (Clay .76, over-dispersed); level by tier actual/shadow/Clay: elite
  20.8 / 21.8 / 22.0, 61-100 19.5 / 19.4 / 19.4, 101-150 16.7 / 17.0 / 16.7.
  Un-shrinking makes it worse at every step (k .9 +0.18%, 1.0 +0.38%, 1.1
  +0.61%); weaker P worse (P 9 +0.12%, P 6 +0.63%); P 18 flat. The
  "compression" seen season-long is the ridge, not the shrink.
- The ridge half hurts QBs: a = 0 -> top-150 QB weighted -0.65% LOYO (6/7;
  only 2020 worse, +0.58%), forward -1.41% (5/5); elite QBs -1.09% (5/7) /
  -1.76% (4/5); 61-150 -0.30% / -1.09%. vs Clay the QB margin goes -0.28% ->
  -0.93% LOYO and -1.64% forward (4/5). a = .25 is half the gain.
- ADP-curve weight .75 -> .5: more pooled gain with a = 0 (-0.82% LOYO, -1.71%
  fwd 5/5) but it swings by season (2020 +1.5%, 2022 +0.3%, 2023 / 2025
  -2.9%; LOYO 3/7) - NOT applied. QB-rank market curve: no better than ADP.
- Engine (shadow only): NC_SHADOW.ridgeW is now per position { QB: 0, RB .5,
  WR .5, TE .5 }; no '+ridge' tag on QBs. W2 headless: live untouched (0 of
  494); top-150 QB mean |shadow - Clay| 1.07 -> 0.89; Dak +1.6 -> +1.3,
  Allen still -2.9 (that gap is the ADP-curve weight, left alone). Data
  data/qb_compression.js (SIM_QBCOMP_BT), ZONES panel.

## Oracle volume test: is projectable volume the main issue? (2026-09-17, _tmp/oracle_volume.py)

Jack: "so our main issue with the algo is that we dont have the correct
projectable volume for the top players?" RB/WR/TE with pbp volume both years
(565 top-150 rows), importance-weighted MSE. "True volume" = the season's ACTUAL
targets and carries per game x league-average efficiency (LOYO fit), nothing else.
- Volume is half of all the error, for everyone: top 150 Clay 9.73, ours 9.83,
  last year's volume 13.78, half-way to true volume 7.33, TRUE volume 4.81
  (-50.5% vs Clay); top 60 -46.5%, 61-100 -59.9%, 101-150 -67.5%. Error sd
  3.0 PPG (ours and Clay's) -> 2.0 once volume is known; the rest is
  efficiency + touchdowns.
- Clay does NOT forecast volume changes better than we do: corr(volume
  change, Clay - ours) = +0.04; the volume change correlates +.58 with our
  miss and +.57 with his. Top-60 by realised volume move: UP 3+/g (n=31)
  actual 16.3, Clay 14.5, ours 12.9 (MSE 10.6 vs 18.6); FLAT (n=225) actual
  13.2, Clay 13.2, ours 12.4 (8.66 vs 8.85); DOWN 3+/g (n=37) actual 10.8,
  Clay 14.5, ours 13.3 (19.4 vs 13.2). Clay projects the same ~14.5 for the
  future risers and the future fallers - he is simply higher on top-60
  players, which is right on risers, wrong on fallers, calibrated on the
  flat majority. His top-60 "riser edge" is a level effect, not foresight.
- With v2.16/2.17 (JM, QB ridge 0) ours vs Clay on this subset: top 60 +2.1%,
  61-100 -0.2%, 101-150 -4.9%, top 150 +1.0% - close to even.
- The prize: any preseason signal that predicts the volume CHANGE is worth up
  to half the error, and neither side has one (vacated volume, depth chart,
  week-1 usage, coach tendencies, growth terms all failed). In-season the
  volume is observed, which is why the weekly shadow wins.

## In-season usage evidence: the learning curve by games played -> v2.18 (backtest_inseason_usage.py) - 2026-09-17

Jack: "if volume is the issue ... work on the week by week projections and
actually use the previous weeks information (routes run, snaps, target share
etc) and see how the model does as the season goes on" / "if we can be elite in
season that could be very valuable." Walk-forward: week 1 = the preseason prior
alone; every later week sees only the weeks before it. Usage per player-week
from ctx_features.parquet (season + last-3 target / carry share, red-zone,
goal-line and air-yard shares, WOPR, xFP/g, points over xFP, snap share and
trend) + PFF weekly route rate (season + last 3; 15,121 rows). Importance-
weighted top 150, vs the v2.17 shadow and the corrected Clay blend, by games
played, LOYO + forward 2021-25.
- The current shadow vs Clay by stage (the learning curve): 1 game -1.3%
  (4/7), 2 games -1.8%, 3 games -2.5% (6/7), 4-5 -0.5%, 6-8 -2.0% (7/7), 9+
  -0.8%; games 1+ -1.24% (6/7), forward -1.28% (5/5).
- E1 pure usage (xFP/g replaces points/g): -1.3% after ONE game, then worse
  every stage: +3.6%, +0.9%, +5.0%, +9.1%, +18.2% at 9+ games (QB +62%).
  Points carry skill; usage alone is not a projection (matches backtest_xfp).
- E4 learned usage model (ridge per position x games bucket, 22 features):
  +2.9% LOYO, +5.0% forward. 50/50 with the shadow: +0.1% / +0.7%. Overfits.
- E3 recency tilt (last-3 share / season share): no gain over E2.
- E2 lam per position x bucket: -0.30% (6/7) / fwd -0.24% (3/5) - noisy picks.
- E6 ONE smooth schedule per position, lam(g) = max(floor, start - slope x
  (g-1)) on xFP/g inside the evidence: -0.49% LOYO (6/7), -0.45% forward
  (5/5); by stage LOYO -1.8 / -0.3 / -0.8 / -0.4 / -0.6 / -0.2%; RB -0.54%
  (6/7), WR -0.72% (6/7), TE -0.08% (3/7), QB 0. Picks: WR (1.0, .08, .25)
  in 6 of 7 folds; RB (1.0, .3, .25) in 4 of 7; TE scattered. P multiplier
  .75 never chosen. vs Clay: -1.24% -> -1.72% LOYO, -1.28% -> -1.72% fwd.
- Engine (shadow only): NC_SHADOW.usageLam { RB [1,.3,.25], WR [1,.08,.25] };
  shadowUsage(p, wk, sc) reads SIM_XFP_2026 (sim_routes.js, weeks < wk,
  scored to the sheet) and jsBasePg's new 5th arg blends it into the evidence
  for the shadow call only; tag '+xfpNN'; kill window.SIM_NC_USAGE = false.
  W2 headless: live untouched (0 of 494); 95 of 99 top-150 RB/WR carry it,
  mean |move| .51, max 3.2 (Henry -3.2, Swift -2.6, Monangai -2.1: week-1
  points outran volume; Dowdle / Metcalf +0.9: volume outran points).
  Data data/inseason_usage.js (SIM_INSEASON_BT), ZONES panel.

## Does weekly accuracy improve as the season goes on? (2026-09-17, _tmp/curve_abs.py + curve_week.py)

Jack: "did this improve as the season went on in the past seasons for weekly
specific projections ... in individual weeks". Top 150, importance-weighted,
2019-25 pooled, by NFL week; shadow v2.18 vs the per-game Clay blend vs the
SAME preseason prior frozen (never updated in-season).
- ABSOLUTE accuracy does not improve: typical miss (RMSE) 7.2 in week 1,
  7.0-8.1 every week after; correlation with actual .54 in week 1, .49-.56
  after, no trend (weeks 1-4 .526, 5-9 .528, 10-14 .522, 15-18 .512). A single
  game is mostly irreducible variance (touchdowns, script); late weeks add
  injuries, rest and role churn.
- What in-season learning buys is NOT decaying: the frozen prior's r falls
  .524 -> .513 -> .481 -> .477 across the four blocks while the shadow holds
  .526 / .528 / .522 / .512. Shadow vs frozen prior (weighted MSE): weeks 1-4
  0.0%, 5-9 -1.9%, 10-14 -4.5%, 15-18 -4.4% (week 15 -7.2%).
- vs the Clay blend by week: better in 15 of 18 weeks, level in weeks 5, 12,
  15 (+0.2 / +0.1 / -0.1%); blocks -2.4% / -1.7% / -1.6% / -1.6%. Biggest
  margins weeks 2, 4, 6, 13, 17, 18.
- By position, early (games 1-3) vs late (9+): r QB .36 -> .32, RB .48 -> .46,
  WR .35 -> .38, TE .25 -> .39; the frozen prior's late r is .27 / .42 / .30 /
  .29, so updating is worth the most at WR and TE.

## Weekly RANK accuracy by NFL week + start/sit head-to-head (2026-09-17, _tmp/curve_rank.py + curve_disagree.py)

Jack: "what about rank accuracy week by week instead of points" / "its more
weekly in the long run in a big sample". Top 150, within position, 2019-25.
- Spearman (frozen prior / Clay blend / shadow v2.18) by block: weeks 1-4
  .350 / .344 / .355; 5-9 .351 / .358 / .373; 10-14 .349 / .385 / .388; 15-18
  .318 / .378 / .378; all .343 / .366 / .374. Ranking DOES improve a little to
  midseason (.355 -> .388) where points accuracy did not; the frozen prior
  decays. Top-N hit (top 12 QB/TE, 24 RB/WR): .607 / .615 / .619, flat all
  year. All same-position pairs ordered correctly: 63.3 / 63.8 / 64.2%.
  By position rho: QB .31, RB .51, WR .35, TE .34 (RB is the rankable one).
- HEAD TO HEAD where the shadow and Clay order a same-position pair
  differently (13,496 pairs): shadow right 52.35% (6/7 seasons); startable
  players only 52.50%. By block: weeks 1-4 53.9% (7/7), 5-9 52.8% (6/7),
  10-14 50.0% (2/7), 15-18 50.7%. By position: RB 54.6% (6/7), WR 51.7%
  (6/7), TE 50.9%, QB 49.9%. The ordering edge is early-season and RB/WR;
  from week 10 the two agree on most pairs and split the rest.
- Shadow vs its own frozen prior on disagreements: weeks 2-4 49.0% (3/7) -
  the first in-season updates do NOT improve the order (and 1-game MSE is
  +1.1% worse than frozen); weeks 5-9 53.2% (7/7), 10-14 55.9%, 15-18 55.1%.
  Open lever: a stronger prior (or delayed evidence) for the first 1-3 games.
- NOTE: "close pair" columns in curve_rank.py use each model's own pair set
  and are not comparable across models; use the disagreement test.

## Are the shadow's losses to Clay patterned or random? (2026-09-17, _tmp/loss_pattern.py + loss_auc.py)

Jack: "is there any correlation to what players it loses to clay or random".
Top 150, weighted, shadow v2.18 vs the per-game Clay blend, 2019-25.
- NO player type where Clay wins: all 35 cuts (position x ADP tier,
  experience, age, depth string, direction of the disagreement, hot / cold
  form, Clay's projected games, game environment, vacated-role weeks, Clay's
  own level) have the shadow ahead. Weakest: TE 61-150 -0.14%, QB 61-150
  -0.24%, running cold -0.51% (4/7), docked by the layers -0.71%, within 1.5
  pts of Clay -0.69%. Strongest: string 3+ -12.1% (7/7), string 2 -4.6%,
  RB 61-150 -4.6%, rookies -3.7% (7/7), running hot -3.6%, boosted by layers
  -3.3% (7/7), age 30+ -2.5%; when the two differ by 1.5+ the shadow wins
  -7.9% (it is higher) and -6.8% (it is lower).
- NOT persistent by player: per player-season loss, odd vs even weeks r =
  -0.23 (684); same player year to year r = -0.06 (459). No "Clay players".
- Predictability of which model is closer (LOYO logistic): all features AUC
  .561, but player type alone .527 and the projection gap alone .570. It is
  mechanical: weekly scores are right-skewed, 54.9% of rows land BELOW both
  projections (lower one wins, shadow closer 61.4%), 40.6% ABOVE both (higher
  one wins, shadow closer 39.9%), 4.5% between. The shadow is the lower
  projection on 61% of rows.
- Biggest player-seasons each way are the same archetype: Clay better on
  elite booms (Kamara 2020, Kupp 2021, Jefferson 2025, CMC 2019, Kelce 2020,
  Henry 2019, Lamb 2023, Lamar 2019); shadow better on elites who fell short
  (Henry 2025, Tyreek 2021, Chase 2023, Chubb 2021, Elliott 2019, Kamara
  2019, Jefferson 2022, Barkley 2019). Clay sits higher on stars; he wins the
  career years and loses the rest. Random with respect to identity.

## Defensive data / advanced analytics on the weekly RANK objective -> v2.19 QB game-total tilt (backtest_matchup_rank.py) - 2026-09-17

Jack: "lets not worry about season long too much as we are in season now and try
to maximize our in season week specific rankings - do any of the defensive data
or advanced analytics help our weekly data?" (memory
feedback_inseason_rank_objective). Objective = mean within-position-week
Spearman on the top 150 (504 position-weeks a position), pairs ordered correctly
and points MSE alongside; base = shadow v2.18; LOYO per position then forward.
- What the SHIPPED layers are worth for ranking (rho none -> all): QB .2685 ->
  .3070, RB .4864 -> .5047, WR .3389 -> .3475, TE .3249 -> .3352. Vegas implied
  total carries almost all of it (QB .293, RB .5005, WR .3476, TE .3345 alone);
  FPA adds at QB / RB (.284 / .491 alone; together .3071 / .5052); the other
  live layers add nothing to top-150 rank.
- Re-tuning the shipped strengths for rank: nothing passes. QB Vegas x3-4 is
  +.013 rho but 4/7 and +8-11% MSE; WR x2 +.0048 (5/7) fails forward; FPA
  stronger or weaker is worse everywhere.
- 34 new tilts x exp(c z), z standardized within the week, c per position:
  PFF opponent coverage / pass-rush / run-defense grades and pass-rush win
  rate (walk-forward, shrunk to last season; 9,971 of 11,082 rows), opponent
  man rate x the player's man-zone YPRR gap, own OL pass / run-block grade
  and injury drop, spread, game total, wind, dome. Only QB GAME TOTAL is
  credible: c .06 picked in every fold, LOYO +.0163 rho (6/7), pairs +0.48,
  forward +.0120 (4/5). Two other nominal passes (QB vs opponent run-defense
  grade +.006; TE vs own pass-block grade +.004 with pairs DOWN) are small,
  sign-implausible and about what 42 tries produce by chance - not applied.
- QB fixed-strength sweep (no selection): c .02 +.0065 rho / MSE -0.02%; .03
  +.0115 (6/7), pairs +0.42 (6/7), MSE +0.17%; .04 +.0121 (6/7), pairs +0.48
  (7/7), MSE +0.48%; .06 +.0161, MSE +1.54%; .08 +.0147, MSE +3.18%. Opponent
  implied total alone fails (negative from c .04): it is the full game total.
- Engine (shadow only): NC_SHADOW.qbTotalC = .03; gameTotalZ(schedule, wk, tm)
  = the game's implied + oppImplied standardized across the week's games
  (clamped +-2.5, needs 6+ priced games); ncMean x exp(c z) for QBs, tag
  '+tot', kill window.SIM_NC_TOTAL = false. W2 headless: live untouched (0 of
  494); 24 QBs tagged, 18 change shadow rank, max move 1.83 (Allen +1.8 and
  Goff +1.4 on BUF-DET 54.5; Hurts -0.85 on PHI-TEN 39.5).
  Data data/matchup_rank.js (SIM_MATCHUP_RANK_BT), ZONES panel.

## Alignment matchups: slot / outside / inline (backtest_alignment_matchup.py) - NOT APPLIED - 2026-09-17

Jack: "so matchups dont really matter like individually example x z or slot".
Untested until now (shadow corners, player x defense history, depth / side
zones, man-zone x YPRR had all failed). PFF weekly receiving for EVERY WR / TE
(slot_rate, wide_rate, inline_rate, routes, rec, yards, TD) charged to the
defense faced -> each defense's half-PPR points allowed per route by
alignment, walk-forward (weeks before the game, K = 4 shrink to last season),
z across defenses each week; player alignment mix walk-forward (routes-
weighted, last season at .35). Features: mix x opponent alignment z; the
alignment-SPECIFIC part (minus the opponent's overall z); and slot-heavy WR
(55%+), outside WR (65%+ wide), inline TE (45%+) against their own alignment.
Rank objective (mean within-week Spearman, top 150), LOYO + forward; 5,300 of
5,763 WR/TE rows covered.
- Persistence, first half vs second half of a season (224 defense-seasons):
  overall points per route allowed r +.16; alignment-specific part slot +.09,
  wide +.13, inline +.13. There is almost nothing stable to project.
- Direction check (actual / projected, soft vs tough alignment z): slot WR
  1.031 / 0.975 (n 60 / 48); outside WR 1.040 / 1.072 (no signal); inline TE
  1.124 / 0.913 (n 101 / 101).
- Rank: mix x z WR -.0039 (0/7), TE -.0016; alignment-specific WR -.0042, TE
  +.0098 LOYO (5/7) but forward -.0049; slot WR +.0016 (5/7) / fwd +.0017
  (4/5) - right sign, far under the .004 bar; outside WR +.0015 with a
  NEGATIVE pick (noise); inline TE +.0044 (5/7), pairs +0.05, MSE -0.51%, fwd
  +.0027 (3/5) - the only nominal pass of 7, confined to blocking-heavy tight
  ends who are rarely startable. Not applied; would need a weekly 2026
  alignment build for ~0 start/sit value.
- Reading: individual matchups are real on film but at weekly resolution the
  repeatable part is already in the Vegas total + position FPA; the
  alignment-specific remainder does not persist long enough to rank on.
  Data data/alignment_matchup.js (SIM_ALIGN_BT), ZONES panel.

## Backup quarterbacks: do team totals account for it? -> v2.20 WR dock (backtest_qb_out_receivers.py) - 2026-09-17

Jack: "is there any projection change when there are backup qbs or does the team
totals account for that". The engine had NO teammate adjustment: it relied on
the Vegas implied total and the book lines. Harness flag qb_out (ctx_features:
the team's primary QB Out / Doubtful / off the roster that week) marks 1,443 of
15,002 skill-player weeks 2019-25 (9.6%); 760 in the top 150.
- Vegas does move: implied team total 23.09 -> 19.08, Vegas mult 1.009 -> .953.
- It is NOT enough for wide receivers. Top-150 actual / projected with the
  primary QB out: WR 0.897 (shadow) and 0.902 (Clay blend) vs 1.012 / 0.979
  with him in; by season .82 .80 .90 1.02 .91 .96 .82 (6 of 7 under 1.0).
  TE 1.034 and RB 0.999: no effect (checkdowns and the run game hold).
  WR ADP 1-60 .863, ADP 61-150 .939; first game with the backup .861, later
  games .922.
- LOYO dock on QB-out weeks (d per position on weighted MSE): WR picks .15-.20
  in every fold, weighted MSE -0.53% on ALL top-150 WR rows (6/7), -9.2% on
  the QB-out rows, rank rho +.0018; TE picks 0 every fold; RB +0.59% worse.
- Engine (shadow only): NC_SHADOW.qbOutWrDock = .15 (the low LOYO pick);
  teamPrimaryQbOut(tm, wk) = the roster QB with the highest Clay season
  projection fails chartAvailable() (a planned qbWindow is not an outage);
  WR ncMean x .85, tag '+qbout', kill window.SIM_NC_QBOUT = false. W2
  headless: live untouched (0 of 494); only SEA (Darnold Out, Drew Lock
  starts): Smith-Njigba 15.3 -> 13.0, Shaheed 7.8 -> 6.6, Horton, Kupp.
- The LIVE Clay-side mean has the same 10% bias; rows with direct book lines
  are partly protected by the anchor (WR props price the backup), un-lined
  rows are not. Candidate for the live mean - Jack's call.
- Does it help the weekly projections / rankings? (Jack, same day;
  backtest_qb_out_tiers.py) On the 348 affected top-150 WR weeks the typical
  miss falls 7.23 -> 6.90 pts. For RANK the effect is small because only ~8%
  of WR weeks are affected: the 11,259 start/sit pairs with exactly one
  receiver on a backup QB go 60.55% -> 61.06% correct with the flat .15, and
  within-week Spearman +.0036 in the 105 weeks that contain one. The flat
  dock over-docks (mean projection 8.73 vs actual 9.22; top-60 10.35 vs
  10.51 = right). TIERED .15 for ADP <= 60 / .05 for the rest: pairs 61.25%
  (5/7 seasons), weighted MSE -9.26% on those weeks (better in 7/7), mean
  9.20 vs 9.22. Engine updated: NC_SHADOW.qbOutWrDock { star .15, other .05,
  starAdp 60 }, tags '+qboutS' / '+qbout'. W2: Smith-Njigba 13.0 (-15%),
  Shaheed / Kupp / Horton -5%.

## Early-season prior -> v2.21: WR prior x5 after one game (backtest_early_prior.py) - 2026-09-17

Jack: "test the early-season prior". Prompt: vs its own FROZEN preseason number
the shadow's updates ordered pairs correctly 49.0% of the time in weeks 2-4 and
after one game its weighted MSE was +1.07% worse than not updating (then -1.3%,
-2.2%, -2.1%, -3.8% at 2 / 3 / 4-5 / 6+ games). Blend = (P prior + g evidence) /
(P + g), P = QB 12 / RB 5 / WR 8 / TE 8. Families per position on the v2.18
shadow: delay d (g_eff = max(0, g - d)), early boost (P x m while g <= G0), taper
(P x (1 + b exp(-(g-1)/1.5))); 22 settings; top 150, importance-weighted MSE +
the weekly rank objective, by games played, LOYO + forward.
- By position, games 1-3, current shadow vs frozen prior: QB -2.10%, RB -1.68%
  (updating HELPS), WR +0.46%, TE +0.39% (it does not).
- Per-fold selection among the 22 FAILS: games 1-3 +0.18% MSE (3/7), rank
  -.0114; forward +0.06% (3/5). QB every slowdown is worse (+0.3 to +2.2%); RB
  flat (-0.3 to +1.7%); TE scattered picks, rank -.038.
- The stable piece = WR after exactly ONE game. Fixed settings, no selection:
  boost g<=1 x2 -1.24% (7/7), x3 -1.61% (7/7), x5 -1.87% (7/7, rank +.0122,
  pairs +0.72), delay 1 (= ignore week 1) -2.22% (7/7); forward x3 -1.76% (5/5),
  x5 -2.07% (5/5, rank +.0312, pairs +1.20), delay 1 -2.49% (5/5). Monotone:
  the more a WR's week 1 is ignored the better. Delay 1 also touches games 2-3
  (2 games -0.54% 4/7, 3 games +0.02%; forward 3 games +0.43% 2/5) so the
  one-game boost was shipped instead: zero effect from game 2 on.
- Engine (shadow only): NC_SHADOW.earlyP { WR: { mult 5, games 1 } } multiplies
  the prior strength passed to jsBasePg when the player's 2026 games = 1; tag
  '+earlyP'; kill window.SIM_NC_EARLYP = false. W2 headless: live untouched (0
  of 494); 55 of 56 top-150 WRs tagged, mean |move| .32, max 1.1 - quiet
  week 1s pulled back up (Chase +1.0, Rice +0.9, London +0.7, Waddle +0.7),
  big week 1s pulled down (Golden -1.1, Olave -0.7).
  Data data/early_prior.js (SIM_EARLYPRIOR_BT), ZONES panel.

## Is the blend corrected week by week for BOTH sides? The Clay-side blend is under-tuned (backtest_clay_blend_fix.py) - 2026-09-17 - NOT YET APPLIED (live, Jack's call)

Jack: "have we correct the blend throughout the season week by week for both
clay and ours". The shadow got per-position prior strength, usage evidence and
the WR one-game fix today; the LIVE Clay-side blend (jsBasePg, JS_PRIOR_STRENGTH
= 5 for every position, points-per-game evidence) got none of them. That P = 5
was fit when the Clay prior was pts / 17 (biased ~5% low, so the blend wanted off
it fast); with the per-game divisor fix the prior is calibrated and wants MORE
weight. Top 150, importance-weighted, vs the current Clay blend (per-game prior):
- LOYO prior strength per position: QB 16 in every fold, RB 8 in every fold,
  WR 12-16, TE 12-16 (current 5). Alone: ALL -0.82% (7/7); 1 game -2.66% (7/7),
  2 games -0.76%, 3 -0.93%, 4-5 -1.18%, 6-8 -0.87%, 9+ -0.44%.
- Usage evidence (same schedule as the shadow: WR 1/.08/.25, RB 1/.3/.25): ALL
  -0.70% (7/7); 1 game -2.26%, 3 games -1.05%, 6-8 -0.90%.
- WR one-game prior x5: 1 game -1.95% (6/7); nothing after.
- ALL THREE: ALL -1.01% (7/7); 1 game -4.07% (6/7), 2 games -0.73%, 3 -1.23%,
  4-5 -1.33%, 6-8 -1.15%, 9+ -0.44%; by position QB -1.60% (7/7), WR -1.48%
  (7/7), TE -0.80% (5/7), RB -0.49% (5/7). FORWARD (P chosen on earlier seasons):
  ALL -0.90% (5/5), 1 game -3.57% (4/5), games 1-3 -1.72% (3/5), 4+ -0.76%
  (5/5). Rank rho ~flat overall (+.0004), +.009 at 1 game and 4-5 games.
- Reference: shadow v2.21 vs the current Clay blend -1.88% (6/7), so after the
  fix the shadow would lead the Clay side by ~0.9% instead of ~1.9%.
- Live effect would be full on un-lined players and ~30% on book-anchored ones.

## Which base is the most accurate over seven seasons? (backtest_most_accurate_base.py) - 2026-09-17 - DECISION PENDING (live base, Jack)

Jack: "do you think we should add our projections and replace clay blend now?" /
"if we back tested it through 7 seasons shouldnt we go with the most accurate?"
Top 150, 2019-25, importance-weighted; error vs the Clay blend as it runs today:
  A  Clay blend today (P = 5, points evidence)            0.00%         rank rho .3664  pairs 63.78%  miss 7.623
  B  Clay blend fixed (P per position, usage, WR 1-game)  -1.01% (7/7)  .3668            63.71%        7.585
  C  B + QB total tilt + backup-QB WR dock                -1.30% (7/7)  .3696 (5/7)      63.80%        7.574
  D  Shadow v2.21, Clay-free                              -2.09% (6/7)  .3781 (7/7)      64.31%        7.543
  E  C+D, weight chosen LOYO (.75 .75 .75 .75 .6 .6 .75)  -2.19% (7/7)  .3801 (7/7)      64.29%        7.539
  F  fixed 50/50 of C and D                               -2.16% (7/7)  .3810 (7/7)      64.30%        7.540
- The most accurate is the BLEND (E / F), but it and the shadow alone are a
  statistical tie: F vs D by season -0.43 -1.22 +0.25 +0.09 +0.38 +0.45 -0.36%
  (3 better, 4 worse). The data wants ~70% shadow / 30% Clay.
- What the blend buys is QB: C -1.16%, D -0.54%, F -1.19%. RB D -2.45% / F
  -2.12%; WR D -2.61% / F -2.76%; TE D -1.01% / F -1.38%. By stage (C / D / F):
  week 1 0.00 / -2.41 / -2.34; games 1-3 -2.62 / -3.60 / -3.79; 4-8 -1.52 /
  -2.22 / -2.33; 9+ -0.64 / -1.15 / -1.14.
- Unmeasured: all of the above is BEFORE the 70% book anchor; and the live
  engine code has never been scored through a week (first lock with ncMean =
  W2). Replacing the base changes the public site's weekly projections, the
  locks and the season sims, so it waits for Jack's explicit go.

## Week 2 by season, top players first (backtest_week2_top_players.py) - 2026-09-17

Jack: "how many seasons do we beat the clay blend in week 2? and again we want to
prioritize the top players" / "can we see results for top 30 too?" vs the Clay
blend as it runs today; shadow v2.21 / 70-30 blend / fixed Clay blend.
- WEEK 2 seasons better on error: top 30 5/7 / 6/7 / 6/7; top 60 5/7 / 6/7 / 6/7;
  top 100 5/7 / 5/7 / 6/7; top 150 weighted 5/7 / 5/7 / 6/7. The shadow's two
  losing week 2s are 2020 and 2022 in every cut. Pooled week-2 error: top 30
  -5.3 / -6.4 / -7.0%; top 60 -1.3 / -2.8 / -4.1%; top 100 -1.8 / -3.0 / -3.2%;
  top 150 weighted -3.4 / -4.4 / -4.4%. In week 2 itself the FIXED CLAY blend is
  the best for the top players (a stronger prior = more Clay when there is one
  game of data). Week-2 RANK inside the top 60 is noise-to-negative for us
  (shadow better in 1/7 seasons); in the top 150 it is 5/7.
- ALL WEEKS 2-18: top 30 -2.79% (6/7) / -2.90% (7/7) / -2.29% (7/7); top 60
  -1.99 / -2.24 / -1.85% (all 7/7); top 100 -1.90 / -2.09 / -1.32% (7/7); top 150
  weighted -2.12 / -2.26 / -1.38% (7/7). Top 30 by stage (shadow / blend / fixed
  Clay): week 1 -3.3 / -3.0 / 0.0; weeks 2-4 -3.9 / -4.6 / -4.8 (all 7/7); 5-9
  -2.6 / -2.7 / -2.1; 10-18 -2.5 / -2.3 / -1.4.
- Top 30 by position, all weeks: WR -4.5% (7/7), RB -1.8% (7/7), TE -2.2% (4/7,
  n 119), QB -0.5% (n 174). Level: today's Clay blend runs HIGH on the stars (WR
  14.48 vs actual 13.90; RB 16.02 vs 15.45; TE 14.22 vs 12.82); the shadow is
  calibrated (13.88 / 15.41 / 13.36). Everyone is high on top-30 QBs (23.7 vs
  21.8). Top-30 start/sit pairs where we disagree with today's Clay blend: shadow
  right 54.0% of 937 (6/7 seasons), blend 53.9% (5/7).
- Reading for the base decision: the 70/30 blend is the only option better in
  7/7 seasons at top 30, 60, 100 and 150; the fixed Clay side matters most in
  weeks 2-4, which is now.

## Non-overlapping ADP bands + CORRECTION to the Clay-blend fix (backtest_adp_bands.py, backtest_clay_tier.py) - 2026-09-17

Jack: "instead of top 30, top 60 can we see ranges top 30 31-60 etc". Unweighted
MSE vs the Clay blend as it runs today; shadow v2.21 / 70-30 blend / fixed Clay.
- WEEK 2: 1-30 -5.3% (5/7) / -6.4% (6/7) / -7.0% (6/7); 31-60 +4.2% (2/7) / +2.0%
  (2/7) / -0.2% (2/7); 61-100 -3.0% (5/7) / -3.4% (5/7) / -0.9%; 101-150 0.0 / -0.2
  / +2.4%; 151+ -6.6% (6/7) / -5.6% (6/7) / +4.8% (0/7).
- WEEKS 2-4: 1-30 -3.9 / -4.6 / -4.8% (all 7/7); 31-60 -0.2 / -1.2 / -1.3% (5/7);
  61-100 -4.3 / -4.0 / -0.4%; 101-150 -4.5 (6/7) / -3.6 (7/7) / +1.0%; 151+ -3.4 /
  -3.7 / +3.0% (1/7).
- ALL WEEKS 2-18: 1-30 -2.8 (6/7) / -2.9 (7/7) / -2.3 (7/7); 31-60 -0.9 / -1.4 /
  -1.3% (6/7 each); 61-100 -1.7 (5/7) / -1.7 (4/7) / 0.0 (3/7); 101-150 -1.4 (6/7) /
  -1.4 (7/7) / +1.1% (2/7); 151+ -2.4 (6/7) / -2.6 (7/7) / +3.1% (1/7).
- ADP 31-60 is the SOFT band: weakest margin, week 2 worse than today's Clay in
  5 of 7 seasons, start/sit disagreements 49.8% (coin flip) vs 54.0% in 1-30 and
  53.5% in 61-100. Level: shadow runs 2% LOW there (WR 11.39 vs 11.85 actual, TE
  9.82 vs 10.56, RB 11.53 vs 11.77); today's Clay runs +4.7% HIGH on 1-30 and
  -5.6% LOW on 151+; the 70/30 blend is within 2% in every band.
- CORRECTION: the "fixed Clay blend" (strong P for every player) only helps ADP
  <= 60. Unweighted it is +0.17% (3/7) over EVERYONE: 61-100 -0.2%, 101-150 +1.0%
  (2/7), 151+ +2.7% (1/7). The importance-weighted top-150 score hid it. Right
  rule = strong P (QB 16 / RB 8 / WR 12 / TE 12) ONLY for ADP <= 60, P = 5 below:
  1-30 -2.30% (7/7), 31-60 -1.37% (6/7), top 150 -0.92% (7/7), everyone -0.52%
  (7/7). A smooth fade by ADP is equivalent (-0.96% / -0.55%). On the Clay side
  the usage evidence + WR 1-game + extras are slightly NEGATIVE below ADP 100
  (+0.75% at 101-150, +0.45% at 151+).
- 70/30 blend with the tiered Clay side: 1-30 -2.89% (7/7), 31-60 -1.36% (6/7),
  61-100 -1.70% (7/7), 101-150 -1.35% (6/7), 151+ -2.78% (7/7), everyone -2.17%
  (7/7) = better than today in every band, 6+ of 7 seasons in each.

## The ADP 31-60 band (backtest_band3160.py + _diag / _byweek / backtest_blend_schedule.py) - NO Clay-free fix - 2026-09-17

Jack: "lets work on the 31-60 band". 2,492 player-weeks, 175 player-seasons.
- Diagnosis (week-1 rows vs the players' season rate): our prior -4.8% in 31-60
  (hand prior -8.1%, ridge -0.6%, ADP curve -2.2%, raw history +4.6%) vs +0.2% in
  1-30 and -1.5% in 61-100; Clay/gm +2.5% (and +6.8% in 1-30). Log-ADP market
  curve residual by bucket: 1-12 -1.86 (curve 10.6% high), 13-24 0.0, 25-36
  -1.01 (QB / TE -3.0), 37-48 +0.99, 49-60 +0.58 (RB +2.2), 61-150 ~ -0.2.
- Fixes to the hand prior (vets with ADP + history): A flexible piecewise-log
  curve (residuals shrink to -0.11 / +0.67 / +0.32); B shrink toward the market
  value instead of the pool position mean; C k .9 / 1.0 for ADP <= 60; A+B; A+C.
  ALL are within +-0.1% of the current shadow in 31-60 LOYO (best A+C -0.03%,
  4/7) and WORSE forward (+0.1 to +1.0%); level reaches 12.8 vs actual 12.9 and
  the error does not move. Week 2 in the band stays +3.6 to +4.2% vs today's
  Clay blend (1-2 of 7 seasons) under every variant. The level is not the gap.
- By week (typical miss, points): week 1 Clay 7.07 / ours 7.08; week 2 7.52 /
  7.68 (RB 7.22 / 7.51); week 3 6.98 / 7.05; weeks 4-6 7.52 / 7.41; weeks 7-18
  7.41 / 7.37. The weakness is weeks 1-3 = the PRESEASON number: correlation
  with the player's season rate, Clay vs ours: QB .48 vs -.14 (n 26), TE .47 vs
  .27 (22), RB .19 vs .15 (47), WR .13 vs .11 (80); RMSE 2.80 / 3.23, 2.32 / 2.61,
  3.13 / 3.25, 2.57 / 2.64. A 50/50 of the two priors matches or beats Clay's RMSE
  at RB (3.05) and WR (2.56).
- Blend weight by games played (shadow / tiered Clay side): flat 70/30 is picked
  in every held-out season (-2.19% vs today's Clay blend, every season -1.5 to
  -3.5%); "50 early then 70 / 85" gains -0.3% on top-60 weeks 1-3 and loses
  elsewhere. Flat 70/30 by band: 1-30 -2.90% (7/7), 31-60 -1.34% (6/7), 61-100
  -1.81% (6/7), 101-150 -1.43% (7/7), 151+ -2.89% (7/7), top-60 weeks 1-3
  -2.24% (shadow alone -1.30%).
- Conclusion: in rounds 3-5 Clay's preseason read (QB / TE ordering above all)
  is information we do not have Clay-free; our in-season updating overtakes it
  by week 4. The fix for this band is the blend, not the prior.
- ESPN historical projections (Jack, same turn): lm-api-reads.fantasy.espn.com
  kona_player_info with scoringPeriodId returns weekly projections (statSourceId
  1, appliedTotal + stat lines) for 2019 / 2021 / 2024 - a 7-season comparison vs
  ESPN is buildable. Data data/band3160.js (SIM_BAND3160_BT), ZONES panel.

## Us vs ESPN's weekly projections, 2019-25 (pull_espn_hist_proj.py + backtest_vs_espn.py) - 2026-09-17

Jack: "is it possible to see how we do historically vs a fantasy site like espn" /
"build the ESPN comparison". ESPN's fantasy API still serves the projection it
showed for every past scoring period: lm-api-reads.fantasy.espn.com/apis/v3/games/
ffl/seasons/<Y>/segments/0/leaguedefaults/3?view=kona_player_info&scoringPeriodId=<W>
with X-Fantasy-Filter additionalValue ["11<Y><W>", "01<Y><W>"] (projected / actual
weekly). ~590 QB/RB/WR/TE a week with the projected STAT LINE (ids 3 4 20 24 25 42
43 53 72), saved to pbp_cache/espn_proj/espn_proj_<Y>.json (125 requests, ~5 min).
Rescored to our half-PPR (.04 / 4 / -1 INT / .1 / 6 / .5 rec / -2 fumble; fitted
from weekly_stats_active, median residual .03). 18,979 of 19,064 harness
player-weeks matched (99.6%); 403 where ESPN projected ~0 for a player who played
are excluded; 18,576 graded, 10,942 in the top 150.
- TOP 150 typical miss: ESPN 7.11 | Clay blend today 7.21 (+2.9% error, 0/7
  seasons better than ESPN) | shadow v2.21 7.14 (+1.1%, 2/7) | 70/30 blend 7.14
  (+0.9%, 2/7). All rows: 6.43 | 6.54 (+3.5%, 0/7) | 6.47 (+1.2%) | 6.46 (+1.1%).
- By ADP band (blend vs ESPN): 1-30 -0.06%, 31-60 -0.03% = TIED with ESPN in the
  top 60; 61-100 +1.7%, 101-150 +2.5%, 151+ +1.4%. By position: QB +0.6%, WR
  +0.5%, TE +0.1%, RB +1.8%. By part of season: week 1 +2.9%, weeks 2-4 -0.45%
  (4/7), 5-9 -0.09%, 10-14 +0.7%, 15-18 +3.2%. Seasons: we win 2021 and 2022,
  lose 2023 by 3.2%.
- Weekly ranking inside position: ESPN rho .3777 / pairs 64.54%; Clay today .3655
  / 63.70%; shadow .3776 / 64.22%; blend .3782 / 64.22% = tied on rank. Start/sit
  pairs where we disagree with ESPN: blend right 48.9% (top 150), 50.1% in ADP
  1-60, 46.6% in 61-150; Clay blend today 46.9%.
- Level: ESPN is the best calibrated (+0.9% / -0.1% / +1.1% by band); Clay today
  +4.7% high on 1-30; shadow +0.7% / -2.2% / +0.4%.
- FAIRNESS: ESPN's stored number is its final pre-kickoff projection (knows the
  inactives + injury news - visible in weeks 15-18 and the late rounds); ours =
  closing Vegas + known absences, NO book lines (the live 70% anchor cannot be
  backtested). So this is ESPN's finished product vs our base model.
- ESPN and ours carry DIFFERENT information: 0.5 ours + 0.5 ESPN = -0.97% vs ESPN
  alone (6/7) and -1.9% vs our blend alone (typical miss 7.07); .75/.25 -0.38%
  (6/7); .25/.75 -0.84% (7/7); 0.5 Clay today + 0.5 ESPN -0.14% (5/7). ESPN's
  weekly projection is already pulled live for the CONSENSUS board.
- Data data/vs_espn.js (SIM_VS_ESPN_BT), ZONES panel.

## With all our info, what are the most accurate weekly RANKINGS? (backtest_best_rankings.py) - 2026-09-17

Jack: "so with all our info what are the most accurate rankings?" Top 150, ESPN-
graded rows 2019-25, ranking inside each position each week. rho | seasons better
than ESPN | pairs ordered correctly | top-N hit | points captured by the ranked top N:
  ESPN alone                          .3777 | -   | 64.54% | .6200 | 80.49%
  Clay blend as it runs today         .3655 | 1/7 | 63.70% | .6154 | 79.78%
  our shadow (Clay-free)              .3776 | 4/7 | 64.22% | .6220 | 80.67%
  our 70/30 blend                     .3782 | 4/7 | 64.22% | .6189 | 80.38%
  75% ours + 25% ESPN                 .3867 | 5/7 | 64.63% | .6210 | 80.43%
  50% ours + 50% ESPN                 .3881 | 6/7 | 64.84% | .6211 | 80.69%
  25% ours + 75% ESPN                 .3838 | 6/7 | 64.74% | .6190 | 80.55%
  1/3 shadow + 1/3 Clay side + 1/3 ESPN .3880 | 5/7 | 64.68% | .6221 | 80.51%
  50% SHADOW + 50% ESPN (no Clay)     .3874 | 6/7 | 64.86% | .6235 | 80.83%
  weight picked each season (.5 x5, .6, .75) .3849 | 5/7
- The most accurate ranking = an even mix of OUR model and ESPN; it is best at
  every position (QB .324, RB .512, WR .365, TE .349 vs ESPN .313 / .499 / .356 /
  .341) and in every part of the season from week 5 on (weeks 15-18 .398 vs ESPN
  .385 and ours .376); weeks 1-4 it ties ESPN. By band: 1-30 58.30% pairs (ESPN
  57.81, ours 58.11), 31-60 55.16 (ESPN 55.24, ours 53.62), 61-100 62.80 (ESPN
  62.95, ours 61.26), 101-150 63.43 (ESPN 63.26, ours 61.61).
- Once ESPN is in the mix CLAY ADDS NOTHING: shadow + ESPN (.3874, pairs 64.86%,
  hit .6235, captured 80.83%) equals or beats every mix that contains Clay.
- Scale: the whole range from worst to best is rho .366 -> .388 and 63.7% ->
  64.9% of pairs. Weekly ranking is mostly noise; these are real but small edges.
- Not in this test: the book lines (no history). Live inputs already pulled
  weekly for the CONSENSUS board: ESPN, Sleeper, FantasyPros, CBS.


## RANK MIX: a third graded number = 50% Clay-free shadow + 50% ESPN, books on top (engine rmMean / rmFinal) - 2026-09-17

Jack: "build the rankings mix". backtest_best_rankings.py: the most accurate weekly ranking we can build is an even
mix of our shadow and ESPN's weekly projection (rho .3874 vs ESPN .3777, shadow .3776, Clay blend today .3655; better
than ESPN in 6/7 seasons; Clay adds nothing once ESPN is in). Built as a THIRD number beside the live board and the
shadow; it never feeds the live mean.
- Feed: refresh_data.py now writes window.SIM_ESPN_WEEKLY = { week, p: { norm: [half, ppr, std] } } into
  data/sleeper_meta.js from the repo's data/weekly_projections.json key "e" (the same 9am consensus pull that feeds the
  site's CONSENSUS board); 354 players for W2. Week-gated: used only when its week = the projected week.
- Engine (weeklyProjection): espnPts = std + sc.rec x (ppr - std) (+ TE premium); rmMean = NC_SHADOW.rankMixW (.5) x
  ncMean + .5 x espnPts when ESPN > 0.5, else ncMean; rmFinal = propMean + (1 - propW) x (rmMean - baseM) on rows with
  direct book lines (the same market, our base swapped in for the Clay-side base), else rmMean. Returned as rmMean /
  rmFinal / espnPts; week-sim rows carry rmProj / rmFinal / espnPts; the lock stores rmMean / rmFinal / espn.
  Kill: window.SIM_RANKMIX = false.
- Grading: score_week.py grades "Rank mix" and "Rank mix+books" beside SHIPPED / JS Weekly / No-Clay shadow / ESPN /
  consensus every Tuesday (first lock with the fields = W2). rankmix_week.js <week> prints the rankings by position
  beside the live board, the shadow and ESPN, plus the biggest differences.
- W2 headless: live untouched (0 of 494). 140 top-150 players, 137 with an ESPN number, 129 with direct lines. Mean
  |mix+books - live board| 0.44 pts (0.39 on lined players, 1.11 un-lined). Largest: Henry 19.0 -> 17.1, Javonte
  Williams 17.0 -> 15.8, Smith-Njigba 16.2 -> 15.1 (backup QB), McConkey 8.7 -> 10.1, Gainwell 8.8 -> 5.9.
- CORRECTION (same day): weeklyProjection().mean is the RAW CLAY STACK. The number on the live board is engine
  effMean = propMean when book lines exist, else jsMean. Earlier W2 tables today labelled w.mean as "live board";
  those columns were the Clay stack, not the board (Bijan: Clay stack 17.8, board 21.4). The "Clay" (jsMean) and
  "shadow" (ncMean) columns were right. Every headless script from here on must use propMean ?? jsMean ?? mean.


## Shadow v2.22: TD-luck double count fixed (found tracing Jefferson / Flowers W2) - 2026-09-17

Jack: "why is the shadow so low on jefferson and flowers" (shadow 11.2 / 7.5 vs ESPN 15.1 / 12.8). Traced with
_tmp/trace_shadow.js (an in-memory instrumented copy of engine.js; nothing on disk changes) and the kill switches.
- FLOWERS (and McConkey): prior 10.73, blended rate 10.69, Vegas 1.05 - but flagged Questionable -> availability
  iA 0.75. The Clay blend gets the same dock (9.7); ESPN does not dock designations; he has no book lines. Working
  as designed (banged-up / Questionable docks, memory project_banged_up).
- JEFFERSON: no flag. Prior chain 10.75 raw history (3-yr 12.55, LAST-8 8.95 - his 2025 collapse) -> 10.35 after
  regression / age / opportunity -> 14.35 after the ADP market blend -> 13.20 after the shrink -> 13.30 with the
  ridge; week 1 he scored 27.2 on 16.9 xFP; blended 13.39. Then the shadow subtracted 2.2 points of TD luck.
- THE BUG: tdLuckAdj() is sized for the LIVE blend = k x TD value x (xTD - TD)/g x g / (5 + g), i.e. it regresses the
  TD luck that ENTERED through points at the live evidence weight. The shadow's weight on points is (1 - lam) x g /
  (P + g): with the usage evidence (v2.18, lam 1.0 after one game for RB / WR) and the WR one-game prior (v2.21, P
  40) that weight is ~0, and since v2 (P = QB 12 / WR 8 / TE 8) it was already smaller than live. The shadow was
  removing touchdown luck it never added. The backtests of v2.18 / v2.21 contain no luck term, so the live shadow
  had drifted from the graded form.
- FIX (shadow only): ncLuckScale = [(1 - lam) g / (P + g)] / [g / (5 + g)], clamped 0-1.5, applied to the luck term
  in both shadow branches (ncFull and the no-redistribution mean). Kill window.SIM_NC_LUCKFIX = false.
- W2 headless: live untouched (0 of 494). 133 top-150 shadows change, mean 0.26: Coker 6.1 -> 7.8, Henry 14.2 ->
  15.6, Watson 9.3 -> 10.7, St. Brown 13.9 -> 15.2, Jefferson 11.2 -> 12.3, Swift 12.3 -> 13.4, Jeanty 12.3 -> 13.3;
  Golden 7.2 -> 6.3, Shakir 9.7 -> 9.0 (no week-1 TD was being credited back). Mean |shadow - ESPN| 1.27 -> 1.13,
  average shadow - ESPN -0.49 -> -0.38.
- What is left on Jefferson (12.3 vs ESPN 15.1, board 14.3): the last-8 half of the history prior (8.95). ESPN and the
  books price the new quarterback; a history prior cannot. Same blind spot as the preseason risers.


## Shadow audit (audit_shadow.js) + history-window test (backtest_history_window.py) -> v2.23 parity fixes - 2026-09-17

Jack: "are there any other bugs like that in the shadow" / "do we really need a 3 year history maybe we do a game
history or is 3 years the most accurate".
AUDIT (audit_shadow.js <week>: in-memory instrumented engine, every top-150 player):
- Reconstruction: shadow = blended rate x chain + scaled TD luck, then tagged steps -> 0 of 144 players off by > 0.5%
  without a tag explaining it. No Clay fallbacks in the top 150, scoring scale exactly 1, no live role boost (iA > 1)
  leaking into the shadow chain, rank mix always between its two inputs.
- Inputs vs the backtest: 3-season history = prior seasons only in both (2023-25, .5 / .3 / .2); last-8 rolls forward
  through the current season in both. OK.
- BUG 1 (data): the nightly pbp feed keys "kenny gainwell", the pool "kenneth gainwell" -> his xFP usage row AND his RB
  TD-luck row (a LIVE layer) never attached. Fixed at the source (pull_pace_tracker.py PLAYER_ALIAS) and in today's
  sim_routes.js. A scan of every in-season feed found no other mismatch.
- BUG 2 (parity): the HIST + OPP calibration (backtest_opp_prior.py) was fitted on HISTREG = the 3-season history
  after the regression curve, NO last-8; the harness uses that fitted value (SHADOWCAL) both as the vets' hand prior
  and as the ridge's oppcal feature. Live fed it the age-adjusted 50/50 blend of 3-season and last-8. Fixed: opHist =
  shadowAgeAdjust(h3). Kill window.SIM_NC_OPPHIST = false. Effect is tiny (39 top-150 shadows, mean .05) because the
  hand prior rises while the ridge, which uses oppcal as a contrast (negative weight given history), falls.
- By design, not bugs: Questionable -> availability 0.75 (Flowers, McConkey, RJ Harvey, Omar Cooper); single-game
  volume quirks (Rice 2 targets, Metcalf 10 targets).
HISTORY WINDOWS (1,137 veteran seasons, every window on the same rows; MSE after LOYO calibration vs the current
.5 x 3-season + .5 x last-8; all vets | top 150 importance-weighted):
- last season only +5.5% | +9.1%; 2 seasons -0.1% | +1.6%; 3 seasons (.5/.3/.2) -0.9% | +0.6%; 3 seasons equal +1.8% |
  +4.1%; last 4 games +27% | +35%; last 8 +10.9% | +12.6%; last 12 +3.8% | +6.8%; last 16 +2.4% | +5.2%; last 24 0.0% |
  +1.2%; last 32 +0.5% | +1.4%.
- BEST = exponentially decayed games: half-life 10 -2.74% (6/7) | -3.17% (6/7); half-life 16 -2.31% | -2.80% (6/7);
  half-life 6 -0.4%; 24 -1.1%. ADP 1-30 -6.0% (5/7). By position (top 150): QB -1.7%, TE -2.5%, RB -0.1%; WR is best
  on 3 seasons alone (-9.9%, last 8 alone +20%).
- The Jefferson case: when the last 8 sits 3+ below the 3-season level (n 46) the next season comes in at 14.6 vs
  15.2 (3-season) / 11.2 (last 8) - best-fit weight on the last 8 = 0.18; far above (n 103): 13.5 vs 12.3 / 17.0,
  weight 0.30. We use 0.50. Short windows are noise; three years is NOT too long, but a smooth game-decay beats both.
- In the FINAL shadow the raw history carries little weight (75% ADP market curve, 0.8 shrink, 50% ridge): moving
  Jefferson's history-blend output +0.6 moved his final prior 0.0. So the decayed window is a real but small lever
  there; it needs a live game-log feed (refresh_data.py) and a refit of backtest_opp_prior.py - not built.


## Decayed-games history inside the full shadow (backtest_decayed_history.py) - 2026-09-17 - NOT APPLIED

Jack: "lets build the decayed history". backtest_opp_prior.py now also dumps raw OPP / HIST / HISTREG (SHADOWCAL
unchanged on 1982 of 1982). dk = exponentially decayed mean of games before the season (4 prior seasons, 8+ games).
- HIST + OPP blend refit on dk (926 vets, LOYO): MSE 9.36 (regressed 3-season) -> 8.68 (hl 8) / 8.60 (hl 12 and 16), -8%.
  The opportunity coefficient collapses to ~0 (RB .10, WR .04, TE .18 at hl 12): dk already carries what the
  opportunity model knows.
- In the FULL weekly shadow (v2.22 form; top 150 importance-weighted, LOYO | forward 2021-25):
  hand prior on dk -0.00% (4/7) | +0.01% (2/5); ridge hist/h3/l8 -> dk +0.12% (0/7) | +0.07%; both +0.12%; ridge ADDS dk
  +0.01% | +0.04% (0/5). Rank rho .3781 -> .3775 / .3765.
- Giving history more weight vs the ADP market (vet market weight .75 -> .55): dk -0.10% (5/7) | -0.14% (5/5), ADP 1-30
  -0.19% (6/7); today's history at .55 gets -0.06% | -0.13% of that on its own; rho flat/slightly lower. Too small to act on.
- Why: history is a minor input by the time the shadow is finished (75% market curve, 0.8 shrink, 50% ridge that
  already weighs 3-season and last-8 separately, in-season blend). The -3% stand-alone gain is real but has nowhere to go.
- Verdict: no live game-log feed, engine unchanged. ZONES panel SIM_DECAYHIST_BT.


## Fantasy-playoff weeks, final week dropped (backtest_fantasy_playoffs.py) - 2026-09-17 - grading rule; no model change

Jack: "dont worry about the final week of every season usually fantasy seasons are over but the weeks besides last
historically are very important as its fantasy playoffs". RULE from now on: drop the final week (17 in 2019-20, 18 from
2021) from every grade and fit; report a FANTASY PLAYOFFS cut (the three weeks before it).
- Top 150, ESPN-graded rows, final week out (10,403): ESPN 7.11 rho .379 | Clay blend today +2.59% (0/7) .369 | shadow
  +0.91% (2/7) .381 | 70/30 blend +0.72% (3/7) .382 | RANK MIX (50 shadow + 50 ESPN) -0.99% (7/7) .389.
- Playoffs (1,869): ESPN 7.27 rho .409 | Clay +3.34% | shadow +2.64% (2/7) .407 | 70/30 +2.61% | rank mix +0.01% rho .421.
  The final week itself was our worst stage (shadow +4.4%, Clay +8.8%) - rested starters; it was inflating every gap.
- Where the playoff loss sits: last 4 games 3+ below the season rate (n 271): shadow +8.2% vs ESPN, projected 13.20 vs
  actual 12.28 (ESPN 12.48). Hot finishes: shadow BEATS ESPN (-1.9%; ESPN chases them, 14.11 vs 13.36). By position for
  cold players weeks 10+: QB 19.96 vs 18.52, TE 9.30 vs 7.77, RB 13.36 vs 13.09, WR 11.62 vs 11.15. Team implied 24+ +4.0%.
- Fixes (top 150 weighted, vs the shadow): in-season decayed PPG hl 3 / 5 / 8 = +0.97 / +0.36 / +0.12% in the playoffs;
  .4 x last 4 +0.48%; prior x0.5 / x0 / x2 after 10 games all lose; COLD-ONLY recency w .25 = -0.21% playoffs (4/7),
  -0.10% all (4/7), rho +.001; QB+TE only -0.15% (5/7). Right direction, too small - NOT applied.
- Takeaway: late-season edge = the ESPN mix (news we do not have: rest, role changes), not another evidence window.


## Cleaning the in-season evidence (backtest_evidence_clean.py) -> shadow v2.24 Vegas-adjusted evidence - 2026-09-17

Jack: "lets build the in season evidence test". 127,728 past games scanned; final week dropped; top 150 importance-
weighted error vs the current shadow (seasons better of 7), change in weekly rank rho. No fitted numbers.
- A. OPPONENT / ENVIRONMENT-ADJUSTED (each past game / the matchup multiplier the model gave that game ^ k):
  full matchup k=.5 -0.18% (6/7), k=1 -0.30% (6/7). VEGAS half alone k=1 -0.30% (6/7), rho +.0026, ADP 1-60 -0.33% (6/7),
  weeks 5-9 -0.33%, 10-to-playoffs -0.45% (6/7), playoffs -0.37% (5/7); QB -0.69% (6/7), RB -0.43% (6/7), TE -0.20%, WR
  -0.04%. k=1.5 -0.36% (6/7), k=2 -0.36%, k=3 -0.22% (4/7). FPA half alone 0.00% (multiplier too small to matter).
  On the 14% of rows moved 0.3+: -1.36% (6/7); moved DOWN n=1059: actual 16.68, old 17.72, new 17.19.
- B. PARTIAL GAMES (snap share < .50 / .65 of his median in his other games; 2.9% / 5.8% of games): drop +0.19% / +0.21%
  (2/7), rescale +0.06%; on touched rows +2.7% (old 11.16, new 11.93, actual 11.00). The partial game is information.
- C. TEAMMATE CONTEXT (lead star WR/TE ADP<=60 or RB ADP<=100, primary QB; mismatched games weight w): w=.5 -0.02% (3/7),
  w=.25 +0.03%, w=0 +0.10%; rank worse. Side note: with the lead star OUT this week the harness shadow is 1.3 low on
  his position mates (live has the opportunity pool for that; the harness does not).
- SHIPPED shadow-only v2.24: NC_SHADOW.vegEvK = 1, shadowVegasScale() scales the POINTS part of the evidence by
  mean(pts / vegasMult(that week)) / mean(pts), clamp .75-1.35; tag '+vegEv'; kill window.SIM_NC_VEGEV = false.
  Feed: refresh_data.py now writes per-week points wf {week: half-PPR pts} into SIM_2026.players; past weeks' lines
  stay in BETTING_2026.gameTotals. W2: 38 of 144 top-150 shadows move, max 0.09 (one game; grows with games), LIVE 0.
  audit_shadow.js: 0 of 144 unexplained.
- SAME FIX ON THE LIVE CLAY BLEND (not applied - Jack's call): -0.72% vs today's Clay blend (6/7), rho +.0037, ADP 1-60
  -0.89% (7/7), weeks 2-4 -0.29% (6/7), 10-to-playoffs -0.97% (7/7), playoffs -0.76% (5/7); k=1.5 -0.90% (6/7).


## The combined LIVE CANDIDATE (backtest_live_candidate.py) - 2026-09-17 - NOT applied, Jack's decision

Jack: "lets build the combined live candidate". Five pending fixes stacked on today's live pre-book number; top 150
importance-weighted, final week dropped, 10,542 player-weeks; (seasons better of 7) | forward 2021-25 (ridge on earlier seasons).
  0 TODAY                                  0.00%          rho .3697 pairs 63.83% miss 7.197
  1 + Vegas-adjusted evidence             -0.67% (6/7)    .3732                         | fwd -0.72% (4/5)
  2 + tiered Clay prior ADP<=60           -1.27% (7/7)    .3764                         | -1.22% (5/5)
  3 + backup-QB WR dock                   -1.59% (7/7)    .3769 64.02%                  | -1.60% (5/5)
  4 + usage / WR one-game / QB total      -1.62% (7/7)    .3781   (adds nothing - skip) | -1.58%
  5 LIVE CANDIDATE 70/30 shadow + step 4  -2.45% (7/7)    .3857 64.39% miss 7.120       | -2.65% (5/5)
  6 + ESPN 50/50                          -3.34% (7/7)    .3891 64.88% miss 7.067       | -3.53% (5/5)
  shadow v2.24 alone -2.28% (6/7) .3837 | rank mix (shadow + ESPN) -3.34% (7/7) .3890 | ESPN alone -2.20% (7/7) .3803
- Cuts (candidate | + ESPN): week 1 -2.1% | -3.8% (5/7); weeks 2-4 -3.9% (7/7) | -4.5%; 5-9 -2.3% (7/7) | -2.9%; 10-to-playoffs
  -2.6% (7/7) | -3.3%; PLAYOFFS -1.0% (4/7) | -2.8% (6/7); ADP 1-30 -3.4% (7/7); 31-60 -1.3% (6/7) | -2.2%; 61-100 -1.7% |
  -3.4%; 101-150 -1.4% | -3.9%; QB -1.4% (4/7) | -2.4% (6/7); RB -2.7% (7/7); WR -2.8% (7/7); TE -1.5% (4/7) | -2.5% (6/7).
- vs ESPN (ESPN-graded rows): today +2.59% (0/7); candidate +0.46% (3/7), rho .385 vs ESPN .379; candidate + ESPN -1.04%
  (7/7); ADP 1-60 candidate -0.36% (4/7), + ESPN -1.08% (7/7); playoffs candidate +2.3% (1/7), + ESPN -0.02%.
- Once ESPN is in, Clay adds nothing (candidate + ESPN == shadow + ESPN). Step 4 is not worth porting.
- Porting plan if Jack says go: (a) Clay-side steps 1-3 in jsBasePg / weeklyProjection (kill switches), (b) live mean =
  0.7 x ncMean + 0.3 x that, (c) optional ESPN 50/50 (rmMean form) before the book anchor.

## Stat-line usage update (compsU) - 2026-09-20
- Problem: `weeklyProjection().comps` = PRESEASON Clay stat line per game x matchup x availability for all 18 weeks. The
  fantasy mean learns in season; the stat lines graded against the books (vs_books_week.py, prop lists) never did. W2: the
  model faded full-time receivers (Coker, Vele, Douglas, Watson) the August line still priced as part-timers.
- `backtest_comp_usage.py` (log comp_usage.log, data/comp_usage_bt.json): walk-forward 2019-25, per stat
  post = (P x prior + g x (lam x usage-expected/g + (1-lam) x actual/g)) / (P + g). vs the static line: rush yds -13.8% MSE
  (7/7; fwd -15.1% 5/5), receptions -10.9% (7/7; fwd -11.2%), rec yds -8.0% (7/7; fwd -8.4%). After ONE game only -1.7 to
  -2.2% (4-6 of 7); grows every bucket to -11 to -15% by 9+ games. When the two numbers disagree 20%+, the actual lands on
  the updated side of the static median 64-70%. Best P 2-5, flat; lam .25-.5 (RB rec yds .75). CAVEAT: historical Clay
  has no yardage lines - the yardage prior is a proxy (Clay ppg x prior-season stat mix), weaker than the real line, so
  yardage gains are overstated and P biased low; receptions use Clay's real line and still gain 11%.
- Engine: `COMP_USAGE` {P 5, lam ry .25 / rec .5 / rcy RB .75, WR/TE .25} + `compUsage()`; `compsU` returned beside
  `comps` (simWeek rows too) and written into the lock snapshots (export_site_proj.js + app.js). `comps`, the prop
  anchor and every published mean are UNCHANGED (scratch export: 0 of 7,795 weekly rows moved). TDs untouched.
  Kill: `window.SIM_COMP_USAGE = false`.
- Grading: `python vs_books_week.py --week N --usage` grades compsU; without the flag = the static comps. Run both every
  Tuesday; promote compsU into the prop-anchor fill only after it beats static vs the books for ~4 weeks.

## Vacated volume by stat - 2026-09-20 REJECTED
- Question (Jack: why did Aaron Jones' rush line barely rise with Mason on IR - model 41 vs books 59.5): the pool turns
  absorbed carries / targets into ONE factor on every stat component. Should carries go to rush yds and targets to rec?
- `backtest_vacated_mix.py` (vacated_mix.log, data/vacated_mix_bt.json), 1,600 absorber rows / 481 one-absence team-weeks:
  RB out -> other RBs rush yds: actual 50.7, uniform 49.7 (unbiased), by-stat 52.0; MSE by-stat +0.8% vs uniform (3/7),
  k LOYO -0.1% (3/7). No boost at all is +6.2% worse (1/7) - the pool earns its keep on rush yds. The 'leak' is real
  football: RBs who absorb carries also catch more (rec 1.72 -> actual 2.29, uniform said 2.28).
- Receiving lines of absorbers look over-boosted (k .5 picked 7/7; rcy uniform 44.8 vs actual 41.9, no-boost 41.5) but the
  pool is filtered on a trailing 3-game baseline, so part of that is regression to the mean. Not applied; re-test with a
  season-to-date baseline before touching POOL tgt weights.
- Engine unchanged. Jones is a single case where the books price far more than the typical next-RB gain (+31% in history).

## Injury signals - 2026-10-01 SHIPPED (engine.js backup engine.js.bak_pre_injsignals_20261001)
- Ask (Jack): daily practice reports for every team, injury type -> plays this week / timeline, news from the big
  accounts + injury analysts, and whether books have lines up. Data layer `build_injury_signals.py` (end of
  refresh_data.py) -> `data/sim_injury_signals.js`: Sleeper body part + notes, practice report by week with the
  day-by-day sequence (`data/practice_seq_2026.json`, backfilled from the repo's git history - the only daily archive
  that exists), availability read off `camp_news_2026.json`, and `data/lines_signal_log.jsonl`.
- `backtest_injury_type_play.py` (injury_type_play.log), 1,641 Questionable starter rows 2019-25: injury type + recent
  seasons weighted (half-life 3) -> forward Brier -1.26% (4/4), leave-one-season-out -0.86% (5/7). Play rates drifted:
  Q + limited 76% -> 65% since 2023, Q + no practice 44% -> 54%. Engine INJ_PLAY / INJ_TYPE, kill SIM_INJ_TYPE.
- `backtest_avail_recency.py` (avail_recency.log), 1,668 absence states: position + injury on the report -> forward
  Brier next game -2.50%, next four -3.58% (4/4); LOSO -2.34% / -3.82% (6/7). RECENCY REJECTED for the curve (+0.1%;
  missed 4+ -> 80% miss the next in 2019-22, 84% in 2023-25 - long absences are not getting shorter). Engine
  AVAIL_POS / AVAIL_GRP, kill SIM_AVAIL_V2. A corroborated Doubtful now starts the curve too.
- News windows (kill SIM_NEWS_WINDOWS): timeline / season / ruled out / expected to play. Headline-only parser, or the
  routine's own `avail` field (prompt in news_routine_prompt_20261001.md; previous in ..._prev_20260727.md). News never
  acts alone - the player's designation has to agree and a game played since the item voids it (weeks 1-3: two wrong
  timeline items, both on players Sleeper listed healthy). `backtest_news_status.py`: ruled out played 1/25, expected
  to play 15/16, game-time decision 6/6. Manual IN_SEASON_OUT_OVERRIDES wins unless the news is newer than
  IN_SEASON_OUT_OVERRIDES_ASOF (or the entry's own third element); an EXPIRED manual window now falls through to the
  designation (Dowdle was projected 7.6 while ruled out).
- Season-ending diagnosis (kill SIM_DX_SEASON): Sleeper body part ACL / Achilles + played this season + on a reserve
  list or Out -> out through week 18.
- Lines up = INTEL ONLY: `lines_signal_scorecard.py` (Tuesday chain) grades the pre-inactives state only (last log row
  100+ minutes before his kickoff). Weeks 1-3: Questionable with lines at 2+ books played 15/17, no lines 5/17. Wire
  a weight at ~100 Questionable player-weeks. Practice-trend cells are in the same scorecard (n too small to read).
- NOTES chip "INJ: <injury> · practice DNP-LP-LP · lines up at N books · news: ..."; the NOTES sheet now redraws once
  the injury layer arms (first view used to show pre-arm numbers).

## Our own future team totals - 2026-10-02 SHIPPED (build_own_totals.py; old file data/sim_future_totals.bak_pre_own_20261002.js)
- Ask (Jack): the book took the far-out look-ahead lines down and will re-post them week by week, so stop leaning on
  them - build our own future totals from the data, each new week's lines included, with current and future injuries.
- `build_own_totals.py` now writes data/sim_future_totals.js (same shape; refresh_data.py calls it, the 09-29
  build_future_totals.py is the fallback and still writes the site twin from the file). Future game = our team RATING
  (preseason rating fit on the 272 frozen preseason lines) + shift from every in-season line incl. the current week and
  any later week already re-posted (per quarterback, weather out) + results (scoring surprise x .10 / .15 / .20 by
  games played) + quarterback MIX per future week (`dump_team_state.js`: depth chart x availability from the injury
  layer) with a -3.0 dock for a replacement quarterback who has no lines yet.
- `backtest_own_totals.py` (own_totals_backtest.log), 2019-25 closing lines, live timing: rating + QB + weather 2.22
  miss vs the eventual closing line; + results -3.9% (7/7); + new-QB dock -10.2% (7/7); shipped form -14.1% (7/7),
  -30.7% vs a rating that is never updated, points-scored MSE -2.3%.
- SKILL-PLAYER INJURIES REJECTED for team totals: oracle knowledge of every future absence -2.4%, but knowing exactly
  when the players out TODAY return = 0.0% (0/7) and the availability-curve version +0.1% (0/7). Only the quarterback
  moves a team total; skill absences stay in the player-level opportunity pool.
- 2026 walk-forward (`--test`, 312 team-games): the game-specific part of the stale lines is sd 0.55 pts; own rating
  + shift 1.47 = stale game line + shift 1.47, so dropping the book's old lines costs nothing. Results term is a wash on
  2026 so far (1.52; bad from week 2 on one game, better from weeks 3-4).
- Effect when switched on: current week 0 rows; rest-of-season mean |change| 0.8% (LV +3-6%, NE / LAC -1 to -3%).
- Caveat: the preseason QB-room guesses still drive who starts for LV (Mendoza from week 5) and CLE (Sanders from week 8).
- Preseason weight by week (`backtest_own_totals_prior.py`, own_totals_prior.log; Jack 10-02: "early in the season
  factoring the preseason totals more?"): ridge 2 is the leave-one-season-out pick through week 4 and MORE preseason
  weight (4 / 8 / 16) is worse at every checkpoint, week 2 included; from week 6 the preseason should count for LESS
  (ridge 0.5: -1.3% at week 6, -3.8% at week 12). Shipped `ridge_for()`: 2.0 through 4 weeks played, 1.0 at 5, 0.5
  from 6 (-0.74% vs flat 2.0, 6/7). Results weight: dropping it is +2.5% to +9% worse at every checkpoint; the
  .10 / .15 / .20 schedule is the pick at 6 of 7 checkpoints.

## Season sim banks played games - 2026-10-02 SHIPPED (engine.js.bak_pre_bankplayed_20261002)
- Jack: "season sim shouldn't resimulate any games already played". `build_actuals.py` (hooked in refresh_data.py) ->
  data/sim_actuals_2026.js: per week the teams whose game is final (kickoff + 5 h) and every pool player's Sleeper stat
  line. Engine simSeason banks a finished team-week at the real points under the sim's scoring (league-sim formula),
  0 with no stat line; only games still to play are sampled (shock / missed-game draws on those alone). Result rows
  gain banked / bankedWeeks / gamesSim; games = played + to play. Kill: window.SIM_BANK_PLAYED = false; opts.actuals
  = null re-simulates everything.
- App: note under the run names the banked weeks; the drawer lists played weeks as "actual"; the median stat line =
  real stat lines for played games + the projection for the rest. The site export's seasonSim block inherits it
  (file is in export_site_proj.js's list).
- Check: banked half-PPR = the weekly stats file for all 350 skill players (max diff 0.5); a weeks 1-3 run has no
  spread except one team defense with no Sleeper row that week (sampled, not zeroed). Players without a Sleeper id
  use the weekly stats file's half-PPR week.

## Shadow return timing - 2026-10-02 SHIPPED shadow-only (engine.js.bak_pre_shadowreturn_20261002)
- Jack: "add a return timing that we just created with all the injury reports / past data". shadowOut() held anyone
  currently out at zero in EVERY later week (v2.9, a this-week rule), so the Clay-free model had no rest-of-season
  number for injured players and handed their work to teammates all year. For weeks after the current one it now
  defers to the injury layer like the live number: out-windows, news timelines, season-ending diagnosis, availability
  curve v2 (P(plays) scales the week), return ramp. An expired manual window falls through to the status, as live.
- `backtest_shadow_return.py` (shadow_return.log), 1,668 absence states: next-four-games Brier hold .422, back next
  game .578, curve .222 (-47% vs hold); expected games 1.91 vs actual 1.84.
- Check: shipped numbers unchanged on all player-weeks; shadow rest-of-season totals Mayfield 0 -> 185 (live 197),
  Hall 0 -> 127 (138), Etienne 0 -> 106 (131); Jalon Daniels 187 -> 30. Kill window.SIM_NC_RETURN = false.
- Still off for injured players: the ESPN chart drops a player while he is out, so the shadow's demoted-veteran dock
  (dock3) follows him after his return (Etienne, Charbonnet, Mason, Jacobs run 1.6-3.4 a game under live).
- PRE-INJURY CHART SPOT (same day, engine.js.bak_pre_chartpre_20261002): `build_injury_signals.py` adds
  SIM_INJ_SIGNALS.chartPre (the list index each player who is out now held on the ESPN chart going into his last
  game, from the repo's depth-chart history; cache data/chart_pre_2026.json). Engine chartListFor(): for weeks after
  the current one effectiveString reads the chart with those players put back at that spot (no game this season =
  ADP rank in the room); players out for every remaining week are not restored (Dart / Winston would double count).
  Shadow rest-of-season totals: Etienne 106 -> 125 (live 131), Jacobs 101 -> 137 (160), Pierce 80 -> 95 (84),
  Mason 72 -> 84 (102); fill-ins down (K. Miller 58 -> 38, Lloyd 50 -> 38). Live numbers and the current week
  unchanged. Kill window.SIM_NC_CHARTPRE = false.
- BACKTEST of the pre-injury chart spot (`backtest_chart_pre.py`, chart_pre_backtest.log; nflverse weekly depth charts
  2019-24, bt_common base x the shipped return ramp): 1,454 first-three-games-back rows (RB / WR / TE). Returning
  players produce at their pre-injury level whatever the chart showed while they were out: dropped off the chart
  1.02 of base (n 283), listed lower 1.01 (n 60), same spot 1.06 (n 1,084). On the 314 rows where the two rules
  differ: actual 7.97, pre-injury spot predicts 7.97, chart-as-listed 4.94 -> MSE -32.8%, MAE -12.0%, 5/6 seasons
  (RB -39% 6/6, WR -32% 5/6, TE -8% 3/6; missed 4+ games -40% 6/6). The teammate listed first while a starter was
  out (220 cases, mostly WR): 8.8 a game before, 10.0 while he was out, 8.5 after the return - the bump is gone.

## What the Clay-free model still misses in season - 2026-10-02 RESEARCH (nothing shipped)
- `research_shadow_residuals.py` (shadow_residuals.log): shadow v2.24 form on 13,932 in-season player-weeks 2019-25
  (2+ games played), residual by player type + vs 160 pre-kickoff metrics. Harness base = prior/evidence x Vegas x FPA
  only, so snap trend, weather, TD luck and the banged-up docks show up as "misses" there but ARE in the live chain.
- Not covered anywhere yet: (1) usage LEVEL for TE / WR - snap share last game r +.12 TE / +.08 WR, target share
  +.06 / +.05 (TE evidence is points only); (2) QB rushing usage - xFP +.07, red-zone carries +.06; dropbacks -.065;
  (3) QB types: changed teams .896 of projection (0/5 seasons), no ADP .927, team implied under 19 .906;
  (4) WR early (games 2-5): target share under 12% .854, rookies .887, ADP 101-180 .911, team implied under 19 .864,
  scoring below usage .886 (usage evidence weight looks too high early); (5) RB carry share under 30% early .862;
  (6) TE level 1.04 across the board (level fixes failed LOYO before - skew, not a multiplier).
- 2026 weeks 2-3 (409 rows, small): backup QBs are the worst outliers (McCarthy 27.3 projected / 0, Flacco 14.1 / 0)
  = the fill-in double count (own starter prior + 85% inheritance); rows carrying a chart dock still ran .75.
- Next tests, in order: backup-QB double count; TE / WR usage-level evidence; QB rushing usage + mover / no-ADP dock;
  WR early evidence mix + low-volume dock; team-shift signal for bad offenses early.

## Next layers for the Clay-free model - 2026-10-02 TESTED (`backtest_shadow_next.py`, shadow_next.log; nothing wired yet)
- Graded on the shadow itself (v2.24 form, 17,569 player-weeks), setting picked leave-one-season-out and forward
  (earlier seasons only, 2022-25); a narrow layer is judged on the rows it touches, the top-150 weighted error over
  the whole board is the guard. Bar: LOSO touched rows better in 5+ of 7, forward 3+ of 4.
- BACKUP QB (43 fill-in starts for a known regular starter): actual 14.7; his own number 14.3; starter x .85 12.2;
  the average of the two best (-7.7%, 3/4); BOTH ADDED = what the live shadow does = 26.4 (+241% error). Fix = never
  add: the larger (or the average) of his own number and the starter's x .85.
- PASS: snap-share LEVEL WR + TE e .3 (touched -0.60% 6/7, fwd -0.59% 3/4, rank rho +.0034; TE alone fwd -1.6% 4/4);
  QB who changed teams x .90 (-2.97% 5/7, fwd -3.52% 3/4); QB on a team implied under 19, e .75 (-1.68% 6/7, fwd
  -1.02% 3/4); rookie WR games 2-5 x .90 (-1.27% 5/7, fwd -2.47% 3/4); RB under 30% of carries games 2-5 x .90
  (-1.54% 6/7, fwd -2.01% 4/4). Stacked: top-150 weighted -0.21% (5/7), all rows -0.49%, rank rho .3837 -> .3875.
- FAIL (do not re-pitch): TE xFP evidence, target-share level (hurts the top 150), QB xFP / rushing evidence (worse at
  every weight), QB with no ADP, WR on low-total teams, WR evidence mix (shipped schedule is right), WR under 12% of
  targets (4/7, fwd 2/4), WR target trend, team shift (any position).

## Shadow v2.25 "next layers" WIRED (shadow-only) - 2026-10-02
- Jack: "lets do it". The five layers that passed backtest_shadow_next.py plus the backup-QB fix are in `engine.js`
  (`NC_SHADOW.next`), applied to the Clay-free number only (`ncMean`). Live / site projections unchanged: 0 of the
  player-weeks 4-18 moved (scratch shadow_dump.js before / after). Backups `engine.js.bak_pre_shadownext_20261002`,
  `engine.js.bak_pre_snapfar_20261002`.
  - QB who changed teams (`SIM_INJ_SIGNALS.prevTm`, built by build_injury_signals.py from snap_counts_2025) x .90 `+mover`
  - QB on a team implied under 19: x (1 - .75 x (19 - implied) / 19) `+lowtot`
  - rookie WR, games 2-5: x .90 `+rkwr`
  - RB under 30% of team carries, games 2-5: x .90 `+lowcar` (carries from SIM_XFP_2026: index 4 on skill rows,
    index 3 on QB rows - the first cut summed QB rush yards and flagged McCaffrey / Barkley)
  - WR / TE snap-share LEVEL: x clamp(1 + e x (last game snap % - ref[bin]) / 100, .7, 1.4) `+snaplv`; bins on the
    half-PPR weekly number; e .3 for the current week, e .15 (`snapEFar`) for later weeks
  - fill-in QB: the LARGER of his own number and the starter's x .85, never the sum (Mariota wk 4 29.8 -> 15.2)
  Kill switches: `SIM_NC_NEXT = false` (the five layers), `SIM_NC_QBMAX = false` (the QB fix).
- `backtest_snap_level_horizon.py` (snap_level_horizon.log), run after the first wiring docked Justin Jefferson 21% for
  the whole season off a game he left hurt (snaps 92 / 100 / 12):
  - EXIT GAMES (last game under 60% of his prior share, 303 rows): the next game ran .751 of the shadow (everyone else
    1.013). Reading the last game as-is cut the error on those rows 9.6% (6/7); swapping in his season share made it
    worse (+0.8%, 2/7). The exit game stays in the reading.
  - HORIZON: e .3 is -0.70% (7/7) for the next game, -0.19% two games out, flat from three out. e .15 holds -0.10 to
    -0.21% at every distance (4-6 of 7 seasons). So later weeks use e .15. Jefferson ROS 144 -> 128 (was 113).

## Shadow v2.26 REST-OF-SEASON settings (shadow-only) + research screens - 2026-10-02
- Jack: "at this point pre season is not relevant lets focus on in season so rest of season by this point and we should
  be able to improve the model through backtesting". `backtest_shadow_ros.py` (shadow_ros.log; `ROS_MINF=1` writes
  shadow_ros_minf1.log): checkpoint = a player entering a game with 3-10 games played; graded on his per-game average
  over the rest of the season (final week dropped) against the context-free rate x the average of those weeks' layers.
  8,542 checkpoints with 4+ games left, 9,848 with no survivor filter. A change is kept only if it holds in BOTH runs.
- WHERE WE STAND: Clay-free rate vs the Clay blend (P = 5), rest of season: -7.8% (7/7), top-150 weighted -4.1%; no
  filter -5.0% (6/7), weighted -3.4%. QB -17% / -6%, RB -6.5% / -5.7%, WR -4.0% / -3.7%, TE -5.6% / -4.7% (TE top-150
  weighted is a tie). Rank order within position about level (.582 vs .575).
- KEPT AS IS (tested, shipped setting is right): prior weights QB 12 / WR 8 / TE 8; evidence mix (points vs xFP) at
  every position; pulling toward / away from the position average.
- WIRED (engine `NC_SHADOW.next`, weeks after the current one only, kill `SIM_NC_ROS = false`; backup
  `engine.js.bak_pre_shadowros_20261002`; live numbers and current-week shadow numbers unchanged, verified headless):
  - RB snap trend carried through later weeks (`rbSnapCarry`; live snapMult returns 1 once the last snap week is 3+
    weeks behind): -4.0% on RB rows 6/7, forward -4.4% 4/4; no filter -3.5% 6/7, forward -4.6% 4/4.
  - QB who changed teams x.84 for later weeks (`qbMoverFar`; .90 stays for the current week): -27% 6/7, forward -25% 4/4.
  - TE snap-share level e .3 for later weeks, WR 0 (`snapEFar {WR 0, TE .3}`, was .15 for both): TE -1.8% 6/7, forward
    -2.7% 4/4; WR worse at every strength (0/7).
  - TE team pass-rate tilt e .04 (`teTilt`, `+rtilt`; z from rosTiltZ, half strength one week ahead): -0.8% 5/7,
    forward -3.0% 3/4; no filter -0.4% 5/7, forward -1.8% 3/4.
  Stacked on the rest-of-season test: -3.4% vs the shipped shadow (6/7), -10.9% vs the Clay blend (7/7); rank order
  .582 -> .598 (Clay blend .575).
- FAILED one or both runs (do not re-pitch): RB prior weight 8 (forward fails without the filter), TE level x1.06-1.09
  (survivor effect - 1.078 with 4+ games left, 1.054 without), RB level, RB rookies / second year / age slope, TE second
  year / rookies, QB pass-attempt tilt (worse on the top 150), QB rushing-share tilt, WR yards per route vs man, WR
  scoring over usage, WR 25% under his prior, WR rookies, WR / TE snap trend carried (half strength only, not stable).
- `research_next_candidates.py` (next_candidates.log), first look only: game after an early exit RB .79 / WR .74 /
  TE .78 of the shadow (7/7, also on a clean report); Questionable hamstring .715 and illness .78 vs all Questionable
  .883 (groin / hip / quad, foot, back: no drop); WR first game after the bye .903 (7/7). Nothing: quarterback form
  for his receivers, short weeks, RB rest.

## Shadow v2.27 rest-of-season STRUCTURE by draft slot (shadow-only) + weakness map - 2026-10-02
- `backtest_shadow_ros.py` section 6 = WEAKNESS MAP of the model as wired, by type of player (level, size of the miss,
  error and rank order vs the Clay blend). Clay blend still closer on WR ADP 101-150 (+7.2%, rank order .30 vs .48), RBs
  running 25%+ over their preseason level (+4.4%), second-year QBs (+12%), WR ADP 61-100 (+3.6%). Under-projected: TE
  ADP 31-60 1.17, RB rookies 1.13, small-role RBs 1.07-1.085, TE overall 1.055. Over-projected: WR 25%+ under preseason
  level .92, WR with the QB out .93, QB ADP 31-60 .94.
- Section 7 = STRUCTURAL tests (Jack: "lets do it"): prior weight by position x draft band (16 cells), prior weight when
  running hot vs cold (25 pairs per position), late-round receiver inputs (usage weight; target / snap / air-yard share
  tilts; depth string), second-year QB prior, TE ADP 31-60 and small-role RB levels. Fold-picked settings were unstable
  at the grid edges, so each kept setting is a FIXED, more conservative value that beats the shipped one in 5-7 of 7
  seasons in both runs (with and without the 4-games-left filter):
  - RB drafted 61-100: prior weight x2.5 (P 12.5): -4.5% / -4.7% (6/7, 7/7). Rank order inside the band a touch lower.
  - WR drafted 61-100: prior weight x0.6 (P 4.8): -3.1% / -2.5% (6/7, 6/7).
  - second-year QB: prior weight x0.75 (P 9): -2.4% / -2.5% (5/7, 7/7).
  - WR drafted 101-150: usage (xFP) weight capped at .25: -3.1% / -2.7% (5/7, 6/7); rank order in the band .31 -> ~.45
    (Clay blend .48).
  - TE drafted 31-60: x1.10: -24.5% / -17.9% (6/7, 5/7) on 139-165 rows - a small sample.
- WIRED shadow-only: `NC_SHADOW.next.struct`, tags `+rsP`, `+rsLam`, `+rsTE`; weeks after the current one, 3+ games
  played; kill `window.SIM_NC_ROS2 = false`; backup `engine.js.bak_pre_shadowros2_20261002`. Live numbers and
  current-week shadow numbers unchanged (0 player-weeks, headless before / after).
- FAILED (do not re-pitch): hot / cold prior weights at every position, every other position x band prior weight (RB
  ADP 1-60 x1.6 is the closest: -1.5%, 5-6 of 7, fails the top-150 guard), late-round WR target / snap / air-yard tilts and
  depth-string levels, second-year QB prior toward ADP, QB ADP 31-60 level, small-role RB levels.

## Shadow v2.28 - inside the weak spots (shadow-only) - 2026-10-02
- Jack: "can we continue looking into our weaknesses". `backtest_shadow_ros.py` section 8 = inside each weak type of
  player, what the rest-of-season miss lines up with and what lines up with the Clay blend being closer (model as wired
  through v2.27). Section 9 = the leads tested, with and without the 4-games-left filter.
- WIRED shadow-only (`NC_SHADOW.next.struct`: `wrLateColdP .4`, `rbPlays .04`, `rbBackup 1.04`; tags `+rsCold +rsVol
  +rsBk`; later weeks, 3+ games; same kill `SIM_NC_ROS2`; backup `engine.js.bak_pre_shadowros3_20261002`; live and
  current-week shadow numbers unchanged):
  - WR drafted 101-150 running BELOW his preseason level: prior weight x0.4 (-6.9% / -6.2% on those rows, 5-6 of 7,
    forward 3/4 both; rank order +.07 to +.10). With v2.27 the WR ADP 101-150 gap to the Clay blend goes +4% -> ~0.
  - RB team play-volume tilt, e .04 per sd of team plays a game (`rosTiltZ().plays` from SIM_PACE_2026 cur.plays): RBs on
    high-volume offenses come down, low-volume go up. -1.5% / -1.5%, 5-6 of 7, forward 3/4 and 4/4, top-150 weighted
    -2.0% / -1.7%.
  - RB backups drafted in the top 150 (effective string 2+): x1.04. -4.2% / -2.9% at that fixed setting (6/7 both); the
    fold-picked x1.08-1.12 fails without the filter (survivor effect), so this is the weakest of the three.
- FAILED (do not re-pitch): RB JM talent tilt (5/7, forward fails), rookie RB JM tilt and draft-capital levels, coach's
  lead-back history (all RBs and hot RBs), hot-RB scoring-over-usage tilt, WR cold + low snap share docks, WR cold snap
  trend (passes only without the filter), WR ADP 151+ cold prior weight, TE coach target history, TE run-blocking line
  tilt, TE scoring-over-usage, QB JM tilt.
- STILL OPEN: RBs running 25%+ over their preseason level (+2 to +5% vs the Clay blend, nothing Clay-free separates the
  real ones), second-year QBs (228 rows, too few seasons to test), RB rookies (under by 12%, no stable fix), TE level.

## Shadow v2.29 PRUNE after a whole-board ablation (shadow-only) - 2026-10-02
- Jack: "can we continue and take out anything that overall hurts the backtest". Every piece of the Clay-free model
  removed one at a time and graded on the WHOLE board (all rows, top-150 weighted, rank order), not just its own rows.
  - NEXT GAME: `ablate_shadow_next.py` (ablate_shadow_next.log), 17,569 player-weeks. The base now carries the engine's
    snap-trend multiplier (ctx `snapmult`) - the earlier v2.25 tests did not, and that changes two verdicts.
  - REST OF SEASON: `backtest_shadow_ros.py` section 10, both runs. All 15 pieces help or are mixed (rank order within
    +-.0015); nothing removed.
- REMOVED from the shadow (`ncPrune`, restore with `window.SIM_NC_PRUNE = false`; backup `engine.js.bak_pre_prune_20261002`;
  live numbers unchanged on every player-week, only WR shadow rows moved):
  - WR snap TREND in the shadow chain (`ncSM = 1` for WR; the live chain keeps it). Trend and level are substitutes for
    WRs on the shadow base: level only = all rows -0.50%, top-150 weighted -0.26% (5/7), rank order +.0076 vs neither;
    trend only = +0.07%, rank -.0014; both = +0.40%, rank -.0019.
  - rookie WR games 2-5 x.90: -2.1% on its own rows but top-150 weighted +0.01% (worse in 5 of 7 seasons), rank -.0003.
- KEPT, mixed (one of three measures against): QB game-total tilt (weighted +0.02%, rank +.0024), QB low team total,
  RB under 30% of carries, TE snap trend with level (weighted +0.5 pts vs level only, rank +.003), usage evidence at
  the rest-of-season horizon (error -0.7%, rank -.001).
- NEXT-GAME LEADS tested on the same base: game after an early exit - WR / TE gone once the trend / level layers are in
  (1.00), RB .90 left, x.95 only marginal (not wired); first game after the bye FAILS at WR / QB / TE; hamstring
  Questionable on top of a generic x.90 dock: -9.8% LOSO 6/7 but forward +3.9% 2/4 (92 rows) - not wired; groin / hip /
  quad / foot / back Questionable score 1.125 of a x.90-docked number, giving the dock back PASSES (-1.5% 6/7, forward
  3/4). Both injury items belong in the injury layer (shared with the live number), tested against its real docks.

## Shadow v2.30 - JM and the learned prior (shadow-only) - 2026-10-02
- Jack: "do we have the jm model factoring in at all?" JM reaches the shadow only as 1 of 16 features of the learned
  season prior (ridge_prior.js): RB .85 pts per sd (3rd largest feature), QB .62 (unused - QB ridge weight was 0), TE .21,
  WR .09. Not in the live number.
- `backtest_jm_ridge.py` (jm_ridge.log), next game (pruned v2.29 layer set) + rest of season with and without the
  4-games-left filter:
  - JM itself (prior rebuilt WITHOUT the jm feature): worse next game in 7 of 7 seasons (top-150 weighted +0.09%), rest
    of season +0.68% / +0.62%. All of it is RB (+0.27% on RB rows next game, +1.4% / +1.2% rest of season); WR / TE flat
    (WR slightly better without at the long horizon, 4/7). Rookies + second-year: never better without.
  - Weight on the learned prior: RB .75 beats .5 at every horizon (rows -0.25% 6/7, -0.73% / -0.22% 5/7; top-150
    weighted better in 5-6 of 7); WR / TE .5 is right.
  - QBs on the learned prior: hurts QBs drafted in the top 100 (+0.8% next game, +3% rest of season), helps QBs drafted
    after pick 100 (-0.5% next game, -2.5% / -2.1% rest of season at weight .25, 6/7 each; whole-board weighted flat).
- WIRED shadow-only: `NC_SHADOW.ridgeW2 { RB .75, lateQbAdp 100, lateQbW .25 }`, kill `window.SIM_NC_RIDGE2 = false`,
  backup `engine.js.bak_pre_ridge2_20261002`. Live numbers unchanged; 45 RBs and 8 QBs move a point or more rest of season.

## Factor ranking by position - 2026-10-02
- Jack: "can you rank the best factors for each position (most predictive)". `research_factor_rank.py` (factor_rank.log):
  metric_atlas_rows.parquet (live 5+, 3+ games played, 14,871 player-weeks) joined to the harness ADP / history; factors
  grouped into families; per family the multiple R alone (next game, rest-of-season PPG) and the unique share (drop in
  R-squared when removed from the all-family model).
- All families together: next game R .42 QB / .56 RB / .50 WR / .51 TE; rest of season .61 / .74 / .73 / .75.
- QB next game: Vegas .33 (unique 14.6%), history .32, season PPG .32, passing volume .29 (unique 7.2%), ADP .27.
  RB: xFP .51, PPG .51, history .49, workload .49, snaps .48, ADP .44. WR: history .47, xFP .46, PPG .45, target volume
  .44, receiving quality .42, ADP .41. TE: history .46, target volume .44, xFP .44, PPG .43, snaps .39 (unique 3.7%).
- Matchup (points allowed) is last or near last at every position (R .01-.06); Vegas is weak alone for RB / WR / TE
  (.12-.15) but carries unique information (1-3%). PPG shows 0 unique only because xFP + points-over-xFP rebuild it.

## Usage with injury-driven games separated + PPG by games played - 2026-10-02 (research, nothing wired)
- `research_usage_injury.py` (usage_injury.log; Jack: "how important is usage or xfp in season with factoring out usage
  because of injuries"). Per-game xFP rebuilt by differencing ctx running totals; each past game tagged teammate out (RB
  20%+ of carries out, WR 15%+ of WR targets out, TE 15%+ of team targets out), left early, or normal.
  - Usage alone vs the next game: RB .46, WR .41, TE .38 (points .50 / .44 / .39). On top of history + points it adds
    +0.24 / +0.27 / +0.46 pts of R-squared next game, +0.23 / +0.47 / +1.21 rest of season.
  - Teammate-out games: 20% / 23% / 41% of games; usage in them +26% / +16% / +15%. Of that bump, 9% / 22% / 22% carries
    to the next game once the teammate is back, 41% / 32% / 42% while he is still out, 18% / 25% / 28% rest of season.
  - Usage from normal games only is slightly LESS predictive than all games (.451 vs .463, .394 vs .406, .350 vs .376) -
    fewer games costs more than the bias removed. Shadow with the evidence rebuilt from normal games: usage only +0.32%
    (2/7), usage and points +3.4% (0/7). Players with inflated usage and the teammate back: actual / shadow 1.000.
    REJECTED - do not re-pitch "clean usage".
- `research_ppg_by_games.py` (ppg_by_games.log): season PPG vs rest-of-season PPG rises to games 5-7 then flattens (QB
  .38 -> .50, RB .50 -> .72, WR .51 -> .70, TE .42 -> .63); it passes past-seasons history at QB game 5, RB 6-7, WR
  8-10, TE 11+. The dip at 11+ is the shorter remaining schedule: against a fixed next-three-games target it does not
  dip (QB .40 -> .47, RB .63, WR .62, TE .55). Injuries cut it at every stage (RB with a teammate out .52-.56 vs
  .65-.72; Questionable RB .38-.49 vs .64-.69), young players run lower than veterans (WR .49-.54 vs .58-.66).

## Shadow v2.31 - elite players and docks; Jefferson out week 4 - 2026-10-02
- Jack: "elite players like jefferson should not be projected very low if he plays but he is actually out now for this
  week". `overrides.js`: 'Justin Jefferson': [4, 4, '2026-10-02'] (the feed had only a DNP). Live week 4 = 0; the manual
  window also ends the model's hedge on later weeks, so Addison's weeks 5+ drop ~0.8 (Jefferson assumed back week 5).
- `research_elite_docks.py` (elite_docks.log), next game, by draft band:
  - snap-share level DOCK of 5%+ (WR / TE): ADP 1-30 score .998 of the UNDOCKED number (1.112 of the docked one, n 93);
    ADP 31-60 .963 (a wash); ADP 61-150 .875 and later .837 (dock right, 5-7 of 7 seasons).
  - game after an early exit, RB: ADP 1-30 1.03 (n 28), ADP 61-150 .79.
  - first game back after a 3+ week gap: ADP 1-30 .885 (6/7 seasons under; x.92 ramp -6.1%) - the return ramp HOLDS for
    elite players. Listed Questionable and played: ADP 1-30 .841 (7/7 under; x.90 dock -10.5%) - the Questionable dock
    holds for elite players too, more than for ADP 31-150 (.95).
- WIRED shadow-only: `NC_SHADOW.next.snapNoDockAdp 30` - no snap-level dock for players drafted in the top 30 (boost
  side untouched). Kill `window.SIM_NC_ELITE = false`; backup `engine.js.bak_pre_elite_20261002`.

## Shadow v2.32 - blowouts and injury exits vs snap / usage numbers - 2026-10-02
- Jack: "make sure we dont hurt players snap and target share for injuries and blowouts". `research_excused_games.py`
  (excused_games.log), 14,608 RB / WR / TE games: injury exit (under 60% of his prior snap share AND on the report /
  missing games after) 185, blowout rest (21+ final margin, under 85% of his share) 413, role loss (under 60%, no
  excuse) 225.
  - BLOWOUTS, top 150: the next game RB 1.109 of a number the snap trend had docked 7% (carried rest of season +10.1%
    error, 1/6); WR / TE 1.011 with no level dock, 1.053 with it. Later / undrafted players .757 (their dock is right).
  - INJURY EXITS: the next game he plays, top-150 WR / TE run .790 of the undocked number (6/6 seasons); the level dock
    cuts that error 5.6%. Reading the last normal game instead: +9.3% (1/7). Leaving exit games out of the points + usage
    evidence: +1.9% (1/7), next game +4.1%. Not excused (the top-30 exemption from v2.31 stays).
  - Leaving blowout games out of the evidence: +0.3% (2/7) - no gain, evidence untouched. Role-loss control: +1.4%.
- WIRED shadow-only (`NC_SHADOW.next.blowNoDockAdp 150`, `blowMinShare .15`, tag `+blow`, kill `window.SIM_NC_BLOW =
  false`, backup `engine.js.bak_pre_blow_20261002`): the snap-level layer now reads the last game's share on competitive
  plays (the same ctxShare re-measure the live snap trend uses), and for players drafted in the top 150 a last game with
  real garbage time (15%+ of the team's plays, 6+) cannot dock the snap level or the RB snap trend. Live numbers
  unchanged; 8 players move (Stevenson, Henderson, Brian Thomas, Hunter Henry, Strange, Loveland, Washington, Dowdle).

## Shadow v2.33 - are the weights right player by player? - 2026-10-02
- Jack: "do we feel like the weights are correct on each player". `backtest_shadow_ros.py` section 11: the weight the model
  puts on THIS SEASON (games / (prior weight + games)) vs the weight that fits the rest of the season best, by position,
  stage, experience and draft band (no survivor filter): QB 34 / 34%, WR 46 / 45% (matched at every stage); RB 50 / 43%
  and TE 43 / 36% (model a little heavy on the season); ADP 1-60 players 8-12 pts heavy at QB / RB / WR.
  ROOKIES are the clear miss: best-fit weight on the season QB 4% (model 33), RB 18% (49), WR 33% (48), TE 8% (43) - a
  rookie's first games say far less than his draft-capital level.
- Tested prior-weight multipliers by experience group and by stage, both runs. Held up: rookie RB x1.6 (-2.2% / -1.9%,
  5/7 both; x2.5 -3.4% / -3.1% but forward 2/4), rookie TE x2.5 (-1.9% / -1.1% LOSO 5/7, forward 3/4 both). Failed: rookie
  QB and WR, second-year at every position, years 3-5 (QB x2.5 passes with the filter only), 6+ years, and every
  stage-specific weight (3-4 / 5-7 / 8-10 games) at every position.
- WIRED shadow-only: `NC_SHADOW.next.struct.rookieP { RB 1.6, TE 2.5 }` (tag `+rsRk`, later weeks, 3+ games, kill
  `SIM_NC_ROS2`; a rookie RB drafted 61-100 keeps the larger band weight). Backup `engine.js.bak_pre_rookiew_20261002`.
  Live numbers unchanged; four rookies move (Mike Washington, Emmett Johnson, Sadiq, Love).

## Season trend check - 2026-10-02 (nothing wired)
- Jack: "did we in general optimize the beginning and later half of season though every week should be tweaked a little
  different in a general trend throughout the season". `backtest_season_trend.py` (season_trend.log), next game, model as
  wired, 17,569 player-weeks.
  - Through the season vs the Clay blend: week 1 -2.4% (5/7), weeks 2-4 -5.6% (7/7), 5-8 -3.2% (6/7), 9-13 -3.1% (7/7),
    14-17 -3.1% (7/7); rank order ahead in every stretch from week 2 (week 1 .356 vs .362). Soft spots: TE week 1
    (actual .855 of projected, Clay +3.3% better), TE weeks 14-17 (top-150 weighted +3.0%, rank .485 vs .517), QB week 1.
  - The weight on this season already moves every game (games / (prior weight + games)); the best-fit weight by games
    played scatters around that curve with no trend away from it.
  - FAILED (all of them, effects within +-0.3%): a different curve shape (exponent .7-1.5 on games played, each
    position), first two games counting less or more, games from the 9th counting more, matchup and Vegas strength by
    stretch of the season (weeks 2-4 / 5-8 / 9-13 / 14-17), and a level by position x stretch (20 cells).

## Clay-free vs Clay blend by TIER - 2026-10-02
- Jack: "show the top 10 vs top 30 vs top 60 vs top 100". `backtest_vs_clay_tiers.py` (vs_clay_tiers.log), model as wired.
  NEXT GAME by preseason ADP: 1-10 -2.0% (5/7), 11-30 -2.7% (7/7), 31-60 -1.9% (6/7), 61-100 -3.6% (7/7), 101-150 -4.1%.
  By OUR weekly projection rank: top 10 -0.6% (4/7, a tie; Clay's rank order a touch better .139 vs .124), 11-30 -3.9%,
  31-60 -4.7%, 61-100 -4.1% (all 6-7 of 7). By position rank: QB1-6 -1.2% (4/7), TE1-6 -0.6% (2/7) = ties; RB1-12 -3.3%,
  WR1-12 -2.3%; everything below the top tier -3 to -9%.
  REST OF SEASON by ADP: 1-10 +4.1% (Clay better, we win 4/7), 11-30 -12.1% (6/7), 31-60 -5.3%, 61-100 -5.0%, 101-150 -11.3%.
  Pattern: the very top (top 10 / QB1-6 / TE1-6) is a tie or slightly Clay; the edge grows down the board.
