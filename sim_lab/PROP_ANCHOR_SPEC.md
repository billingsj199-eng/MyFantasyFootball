# PROP ANCHOR — market-anchored weekly mean

**PHASE 1 IMPLEMENTED 2026-08-31** (engine.js + app.js + overrides.js +
README; verified via node harness — 17 checks — and a live UI lock).
Deviations from the spec below: (1) the staleness guard shipped in v1 after
all — `PROP_MAX_AGE_DAYS = 8` skips entries whose asOf is older, because the
REAL weeklyProps already carried 13 preseason-game lines mis-keyed to W15
(asOf 08-20; pull bug — week_by_matchup maps preseason games onto
regular-season pairings, fix belongs in pull_betting_lines.py); (2) locks
now also store `clayMean` (the raw Clay-layer mean) because `sp.mean` is the
SHIPPED sim mean — in-season it centers on JS/prop, so head-to-heads graded
against it would have degenerated to self-comparison (latent pre-existing
bug for JS-vs-Clay too; both now grade vs clayMean).

Goal: maximize weekly projection accuracy for fantasy decisions by anchoring
each player's weekly mean toward the books' player prop lines where they
exist, while keeping the clean model + JS Weekly fully tracked underneath so
the scoreboard stays readable. This deliberately relaxes the founding
"books are grading-only" rule for the SHIPPED number — the clean model keeps
racing in every lock, exactly like JS-vs-Clay does today.

## Why this is safe to do

- The lock snapshots already freeze the clean comps + the prop lines + the
  actuals pipeline. That means the anchored number at ANY weight w can be
  reconstructed offline from history — the weight is retroactively tunable,
  so a wrong initial w costs nothing but that week's decisions.
- `effMean()` in engine.js is the single choke point: sampling
  (samplePlayerScore), lineup picking (pickLineup candidates sort), DST
  streaming claims, and playoff projections all read it. One change point,
  one kill switch.
- vsBooks grading uses the CLEAN comps stored in the snapshot. As long as
  comps stay untouched (they do — see rule 1 below), beat-the-books remains
  a fair fight and keeps measuring whether the model has independent signal.

## Data in (already flowing, no pull changes needed for v1)

`BETTING_2026.weeklyProps[String(wk)][playerName]` =
`{ asOf, UD: {py,ptd,int,ry,rtd,ra,rec,rcy,rctd,atd?}, PP: {...}, DK: {atd} }`

- UD/PP entries are stat MEDIANS (the O/U line). DK contributes anytime-TD
  american odds only.
- Consensus line per stat = median across books — same rule the LINES view
  and scoreWeek grading already use. Name matching via `E.norm` both sides.
- weeklyProps only ever holds the current slate in practice, so the anchor
  self-limits to the upcoming week; future weeks in simSeason/simLeague fall
  back to the model automatically (empty dict → no anchor).

## The blend (engine.js)

New module-level function, cached per (wk, scoring preset):

```
propAnchorMean(p, wk, sc, cleanWkMean, jsWkMean, comps, sigmaPct)
  -> number | null      // null = no anchor, caller keeps model mean
```

1. **Covered stats**: {py, ptd, ry, rec, rcy} — score each consensus line
   with the league preset (line_py × sc.pass_yd, line_rec × sc.rec + TE
   premium, etc.). `int`, `ra`, and raw 0.5 `rtd`/`rctd`/`rrtd` novelty
   lines are IGNORED (no scoring value / pure juice).
2. **TDs via anytime-TD odds**: devig implied prob p = amToProb(atd) /
   PROP_ATD_JUICE (flat 1.06 overround for v1; the LINES view's
   slate-median centering is the fancier alternative, not needed yet).
   λ = −ln(1−p) = mean rush+rec TDs; split λ into rtd/rctd by the model's
   own comps ratio, score with the preset. No atd → use the model's TD
   comps unchanged (Clay TD rates are fine; TD lines are the noisiest).
   Pass TDs come from the ptd line when posted, else model.
3. **Coverage gate**: the covered stat components (excluding TDs) must be
   ≥ PROP_COVERAGE_MIN (0.60) of the model's non-TD weekly points. Below
   that (one stray rec line on a WR4) → return null, pure model. K and DST
   are never anchored (no market). Players outside their qbWindow / on bye
   never reach here (weeklyProjection returns null first).
4. **Median → mean**: prop lines are medians; the engine lives in means.
   Convert with the player's own gamma shape, closed form — k = (m/sd)²
   with sd = m × sigmaPct (post-SIGMA_CAL), medRatio ≈ (3k−0.8)/(3k+0.2),
   clamped [0.75, 1.0]. propImpliedMean = propFPmedian / medRatio. Same
   shape assumption both directions ⇒ no systematic drift, no sim needed.
5. **Blend**: `propMean = PROP_W × propImpliedMean + (1−PROP_W) × base`
   where base = jsWkMean in-season, cleanWkMean preseason (i.e. whatever
   effMean would have returned). PROP_W = 0.70 to start.

### Constants (top of engine.js, next to VEGAS_ELAS)

```
var PROP_W            = 0.70;   // market weight; retroactively tunable from locks
var PROP_COVERAGE_MIN = 0.60;   // covered non-TD share of model points required
var PROP_ATD_JUICE    = 1.06;   // flat devig on anytime-TD implied prob
```

Overrides (overrides.js): `PROP_ANCHOR_OVERRIDES = { 'Player Name': 0 }` —
per-player weight override (0 = don't anchor him; news says his line is
stale). `window.PROP_W_OVERRIDE` for quick console A/B.

## Plumbing rules

1. **comps stay clean.** weeklyProjection's returned `comps` are never
   touched by the anchor. They feed the LINES divergence view, the median
   stat lines, and the vsBooks grading — all three must keep reading the
   model, or the grading goes circular and the divergence view compares the
   market to itself.
2. **weeklyProjection** grows one field: `propMean` (null when no anchor),
   computed after jsMean. Nothing else in its signature changes.
3. **effMean** becomes:
   ```
   anchor ON && propMean != null ? propMean
     : (useJs && jsMean != null) ? jsMean : mean
   ```
   Kill switch: `window.SIM_PROP_ANCHOR = false` (default ON — the stated
   goal is accuracy). Because effMean feeds sampling, lineup sort, DST
   streaming, and playoff totals, the anchored mean flows everywhere with
   no other edits. sigmaPct, correlations, season shock: UNCHANGED — the
   market gives a center, not a width.
4. **LINES view fix**: it currently medianizes comps with the sim run's
   p50/mean ratio; on an anchored run that ratio is the blend's, so edges
   would shrink by (1−w) and the intel goes soft. Switch its ratio to the
   same closed-form gamma medRatio from step 4 (pure function of sigmaPct)
   so the view always shows CLEAN model vs market, regardless of mode.

## Tracking (app.js)

- **Lock**: store `propMean` per player (same pattern as `jsMean`). Lines
  are already stored.
- **Score**: third grader — MAE/RMSE/bias for propMean + two head-to-head
  records: anchored-vs-clean and anchored-vs-JS (same W/L tally shape as
  the existing jsModel block). Report field: `propModel`.
- **Weight tuning**: after ~4 scored weeks, sweep w ∈ {0, .3, .5, .6, .7,
  .8, .9, 1.0} offline over the accumulated snapshots (every lock has clean
  comps + lines + actuals — recompute the anchored mean at each w and grade
  it). Small python script `tune_prop_weight.py` reading the EXPORT ALL
  JSON, or a TRACKING-tab table. Move PROP_W to the empirical argmin.
  This replaces the impossible historical backtest (no free archive of
  weekly prop lines exists — validation is necessarily forward-only).

## Edge cases / known limitations

- **Stale lines**: `asOf` per book updates only when the LINE MOVES, so it
  can't distinguish "unchanged" from "pulled by the book / player ruled
  out". v1 accepts this — Sleeper Out/IR handling still benches players in
  the league sim, and locks happen post-inactives per the ritual. Phase 2
  (pull_betting_lines.py): stamp a week-level `pulledAt` and mark entries
  absent from the latest pull `stale: true`; engine skips stale anchors.
- **Props disagree with a qbWindow DNP** (books post lines for a QB the
  model says isn't the starter yet): books know news faster — surface as a
  warning chip in the WEEK tab ("props exist for windowed-out player"),
  never auto-override; fix the room in QB_ROOM_OVERRIDES as news breaks.
- **Season sim consistency**: with props only existing for the current
  slate, a mid-run simSeason has week N anchored and weeks N+1..18 pure
  model. Accepted — it's strictly the best available number per week.
- **UD/PP shading**: DFS-style lines run slightly juiced vs sharp books'
  mains; the flat medians are still the best free per-player number, and
  the w-sweep will price any systematic shade into the weight.

## Build order

1. engine.js: constants + `amToProb`/`gammaMedRatio` helpers +
   `propAnchorMean` + weeklyProjection `propMean` field + effMean branch +
   LINES-ratio fix. (~90 LOC)
2. app.js: lock stores propMean; scoreWeek grades it + head-to-heads;
   TRACKING table shows the three-way MAE. (~40 LOC)
3. overrides.js: `PROP_ANCHOR_OVERRIDES = {}` stub + comment.
4. README: new "Prop anchor" section under JS Weekly; amend the "books are
   grading-only" line to "…for the CLEAN models; the shipped number may
   anchor to props (PROP_ANCHOR_SPEC.md)".
5. Verify: preseason (weeklyProps empty) the whole thing is a provable
   no-op — effMean identical, sims byte-identical under a fixed seed.
   In-season W1: console A/B `window.SIM_PROP_ANCHOR=false` re-run, check
   anchored means land between model and lines, comps unchanged.
6. Phase 2 (optional, after first scored weeks): pulledAt/stale flag in the
   pull; tune_prop_weight.py; per-position weights if the sweep says QB and
   RB want different w (plausible — RB lines lean juicier).

## Historical evidence — salary-proxy backtest (backtest_salary_proxy.py, 2026-08-31)

No free archive of historical weekly prop LINES exists (The Odds API sells
2023+), so the closest free market proxy was backtested instead: RotoGuru's
DK DFS salary archive (2019-21 — the site died after 2021), joined to the
standard harness (clay_history + weekly actuals), salary → fpts via a
per-position linear map trained only on past weeks + prior season (no
hindsight), blended into the P5 base at swept weights.

ON THE ANCHORED POPULATION (salary ≥ $5k ≈ players books actually line;
3,962 player-weeks): blending HELPS at every horizon, front-loaded exactly
as designed —
  W1     base 5.970 -> w=.7 5.810  (-2.7%; salary ALONE beats pure Clay)
  wk2-5  base 6.311 -> w=.7 6.175  (-2.2%)
  wk6-10 base 6.020 -> w=.5 5.972  (-0.8%)
  wk11+  base 6.068 -> w=.4 6.041  (-0.4%)
The optimal weight declines .7 -> .4 as the in-season sample grows — the
shipped PROP_W=0.70 matches the early-season optimum of even this blunt
proxy. Pooled with floor-priced bench players the effect washes out (w=.1,
-0.1%) — the market only prices the relevant segment, which is exactly the
population the coverage gate restricts the anchor to.

Read as a LOWER BOUND: salaries are Tuesday-priced, stat-blind, and mapped
through 2 parameters; real props are fresher, stat-level market medians.
Supports: anchor helps, most in Week 1; and PROP_W should probably DECAY
over the season (w-sweep on real lock history will set the schedule).

## Phase 3 — more markets (ranked by value per effort)

**Items 1+2 IMPLEMENTED 2026-08-31** (repo commit 37a1065 + sim_lab): DK's
weekly O/U boards (Pass/Rush/Rec Yards O/U, Pass TDs O/U, Receptions O/U —
subcategories resolved BY NAME, ladder markets skipped, event weeks
kickoff-date validated via `_validated_week`) now merge into weeklyProps[DK]
alongside atd. Live W1: 268 DK lines / 136 players → real-data anchored
count rose 155 → 190 of 452. Kicker path: `kpts`/`fgm` stat keys wired in
DK (Kicking Points O/U / Field Goals O/U) + UD/PP maps — DK doesn't post
kicker boards preseason, so it self-activates in season; engine K branch
anchors directly on kpts (no coverage gate; fgm fallback = 3/FG + model XP);
LINES view + vsBooks grading gained fgm.

1. **DK full weekly prop board** — DONE, see above.
2. **Kicker props** — DONE (engine live; waits on DK posting the boards).
3. **Line-movement intel** (pull stores `open` alongside current):
   WEEK-tab warning chip when a total/spread moved ≥ 2 pts since open —
   news the model hasn't absorbed (QB out, weather). Intel only, points at
   overrides.js before locking; the sim already reads latest lines.
4. **Direct team totals**: only if the ESPN odds API returns them free —
   marginally sharper than (total∓spread)/2.

NOT worth it: alt lines / 2+TD markets (distribution shape — weekly sigma
already at 80% band coverage, vigged tails can't beat it), SGP pricing
(embeds QB-WR correlation but inaccessible; CORR already fit to 2019-25
empirical pairs), season futures (entangle rate × games; double-counts the
availability layers — see the 08-31 discussion).

## Phase 4 — market rate track (weekly props → season-long)

**IMPLEMENTED 2026-08-31** (engine.js): `marketRate(p, wk, sc, schedule)` —
per observed week (any weeklyProps week ≠ the projected one; asOf freshness
deliberately NOT required, past lines are archival observations), rebuild
that week's factor (Vegas × defense × snap × ramp), compute the prop-implied
mean via the shared `propImpliedFp`, divide the factor out → neutral rate;
EWMA with `MKT_HALF_LIFE = 3` wks anchored at the newest observation;
confidence = min(1, Σweights / `MKT_FULL_TRUST` = 2). In weeklyProjection,
weeks with no direct anchor get `propMean = (propWeight·conf·M + (1−…)·jsPg)
× jsChain` and `propSrc: 'rate'` (direct lines set `'line'`; locks store the
src for offline splits). Kill switch `window.SIM_MKT_RATE = false`,
independent of SIM_PROP_ANCHOR; PROP_ANCHOR_OVERRIDES 0 kills both. With
only W1 props live: single obs → conf 0.5 → mw 0.35, and 3,008 future
player-weeks across the season sims are already market-informed (~28ms
total). Verified: neutral rate == fp/factor exactly, EWMA weights exact,
projected week excluded from its own observations, empty-props no-op holds.
Design notes below were the plan; deviations: none material.

A weekly prop is not a 1-week sample; it's the market's CURRENT estimate of
the per-game rate, conditional on playing. The engine is rate × weekly
multipliers, so the anchor propagates:

- **Neutral rate recovery**: propPg = propImpliedMean_wk / factor_wk
  (divide out that week's vegasMult × defenseAdj × snapMult × ramp — all
  known at anchor time). This is the market's matchup-free per-game rate.
- **Propagation**: blend propPg into the player's base per-game rate (next
  to Clay and jsBasePg) → flows through EVERY future week, simSeason and
  simLeague automatically; each future week re-applies its own multipliers.
- **Separation of concerns**: weekly props are conditional on playing, so
  they anchor the RATE while the wreck mixture + injury windows keep owning
  GAMES — structurally cleaner season-long info than season futures, which
  entangle rate × expected games and double-count injuries.
- **Accumulation**: each slate adds an observation → recency-weighted
  running market rate (EWMA, suggest half-life ~3 wks), a third base-rate
  source beside Clay and realized PPG. Role changes (rookie takeover) show
  up in props weeks before Clay's guide updates — same gap the snap trend
  patches, but sharper. Blend weights tunable retroactively from lock
  history exactly like PROP_W.
- Build AFTER Phase 1 has a few scored weeks: the three-way grading tells
  you whether the market rate earns base-rate weight before it touches the
  season sim.
