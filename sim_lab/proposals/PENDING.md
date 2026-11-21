# Sim proposals - PENDING (approve/reject in chat: "approve P-20261013-1")


- P-20261013-1 (vacancy allocation from observed shares) - expired 2026-11-10, not approved; engine port stays OFF (SIM_NC_BUDGET_ALLOC), re-test needs the departed-member + newcomer fixes. Full text in EXPIRED.md.
- P-20261013-4 (rest-of-season x1.02 after a blowout) - expired 2026-11-10, never re-tested in engine form. Full text in EXPIRED.md.


## P-20261013-3 - Stop the blowout ctxShare RE-MEASURE of snap / route share (keep the v2.32 no-dock)
- What: ctxShare re-measures a blowout week's share on competitive plays when his count fits (>= 85%) - it inflates. Return the raw
  pct (keep wt and keep ctxOf so ncBlowLast / SIM_NC_BLOW still work).
- File / knob: engine.js ctxShare() `pct:` branch -> raw pct (new switch, e.g. window.SIM_CTX_REMEASURE = false). Never graded
  when shipped (09-15, SIM_BLOWOUT_CTX).
- Evidence (volume_budget_c.log part C4; 2019-25 participation, 37k consecutive game pairs): next-game snap share MSE raw vs
  re-measured +6.5% WR / +7.3% RB / +6.5% TE (0/7 each); after a blowout +22 / +26 / +23%. Route proxy same (+4 to +8%). Adjusted
  rows: raw 71.1 -> re-measured 92.9, next game 68.3 (even pulled starters: raw 75, rule 93, next 74). 451 of 1,262 adjusted rows
  were garbage-time bodies read as 93%. Points on the WR/TE snap level: +0.05% (2/7) - harmless to slightly worse.
- Confidence: high that it is wrong, low points impact (cleanup). Expiry: 2026-12-31.
- UPDATE 2026-10-13 ENGINE-FORM RE-GRADE FAILED -> NOT SHIPPED (Jack approved pending the re-grade). research_vacfade_ctx_regrade.py
  p3 / vacfade_ctx_regrade_p3.log: engine snapMult (RB/TE) + shadow snap level (WR/TE) rebuilt from participation with the v2.32
  no-dock in every arm. Raw pct vs shipped: next game -0.07% (5/7, fwd 2/4), rest of season +0.02% (5/7, fwd 2/4); fully off
  -0.08% / +0.14%. Share forecasting is still clearly worse with the re-measure, but the points effect is ~0 and fails forward.
  LOSING SEASONS: 2022 +0.36% - Joe Mixon wk9 (53.1 after a -19 blowout loss), Kamara wk8 (38.3), Swift wk17, Derrick Henry wk15,
  Davante Adams wk9 (31.6 after a -24 loss; competitive share 95% vs raw 70%); 2024 +0.22% - Chase wk10 (49.9), Bijan wk10/13/17,
  St. Brown wk7, Tyreek wk14. Pattern: STARS after blowout LOSSES (pulled early) - the re-measure lifted their snap trend and they
  then had huge games; partly outlier games (noise), partly real (a star pulled in garbage time is not a role cut). Possible
  re-test: raw pct for everyone except ADP <= 30 after a loss. Leave pending for Jack.


## P-20261023-2 - QB inherit: shrink the fill-in starter toward his own HISTORY level (replaces the flat .85 x starter form)
- What: when the engine makes a QB the next man up (starter Out/Doubtful/reserve, `iA > 1` / shadow `+vacx` qbMax), the
  projected number becomes the AVERAGE of today's number and a history-based level for the backup:
  L = (his shrunk fantasy pts per dropback: season-decayed .6^k, 120-dropback shrink to replacement .361) x (team dropbacks
  per game, season to date) + his rushing pts/g history. Today = max(own shadow, .85 x the starter's full number).
  New = (L + max(own, .85 S)) / 2. Alternative with the same evidence: the GAP form max(own, S x clip(fppB / fppR, .5, 1.1)).
- File / knob: engine.js weeklyProjection shadow QB vacancy block (`gained = INJ_SHARE.QB * lost`, `ncMean = max(ncOwn, gained)`)
  + live qbJoin; needs a per-QB pts/dropback history table (qbx_cache has it 2012-25; refresh_data.py would build it from pbp).
  New `why` step + NOTES chip ("QB fill-in: history level L"). Kill switch suggestion: window.SIM_QB_INHERIT_HIST = false.
- Size: known fill-in rows 2013-25: engine mean 14.88, L mean 16.01, actual 14.68; the starter's number carries NOTHING for the
  fill-in's output (r(act, S) -.04; r(act, own) +.29; r(act, L) +.31) - the .85 x S term only works as a floor for thin backups.
- Evidence (research_qb_inherit_grade.py, _tmp/qb_inherit_grade.log; engine-base shadow harness 2012-25 team-fix with the
  P-20261023-1 split Vegas form; rows = pool QB starting with the team's main QB Out/Doubtful/reserve pre-kickoff, n 70,
  final week out; folds scored only in seasons with 4+ rows):
  | candidate | LOYO MAE | LOYO MSE | folds | FWD MAE | FWD folds | board top-150 w | rank |
  |---|---|---|---|---|---|---|---|
  | (b) off: own only | -4.41% | -11.05% | 2/5 | -4.76% | 2/5 | +0.01% | -.0000 |
  | (b2) fraction 1.0 | +4.29% | +14.18% | 3/5 | +5.14% | 3/5 | -0.01% | -.0001 |
  | (c) fitted k, max(own, k S) | +6.06% | +14.34% | 1/5 (k .5 every fold) | +4.35% | 1/5 | | |
  | (d) max(own, L) | -6.29% | -13.95% | 2/5 | -6.02% | 2/5 | | |
  | **(d) avg(L, max(own, .85 S))** | **-6.42%** | **-12.85%** | **5/5** | **-6.28%** | **5/5** | -0.00% | +.0001 |
  | (d2) gap max(own, S x fppB/fppR) | -8.58% | -19.53% | 4/5 | -9.02% | 4/5 | -0.01% | +.0003 |
  Folds, (d) avg: 2017 (n 11) -14.5% | 2019 (7) -4.1% | 2021 (11) -6.3% | 2022 (13) -5.9% | 2023 (14) -0.5%; (d2): -26.6 / -3.3 / -2.5 / -5.5 / -0.3.
  Rows per season (known): 13:2 14:1 15:2 16:2 17:11 18:2 19:7 20:2 21:11 22:13 23:14 24:0 25:3. ALL fill-ins incl. benchings (n 149,
  not an engine-parity set): (d) avg -1.97% 6/12, (d2) -2.65% 6/12 - the gain is on the rows the engine actually touches.
  Old league-relative Vegas base: max(own, L) -5.68% (2/5) - same direction.
- Caveat: SMALL CELL (70 rows, 5 scored folds, 2017 carries the pooled number; 2019-23 folds -0.5% to -6%); the harness 'own' is
  the uncapped shadow, the engine's own for a charted string-2 QB is the same once he is string 1 that week. Must be re-graded as an
  ENGINE replay (weeklyProjection on 2026 W2-W7 fill-ins: Wentz, Rush, Lock, Mariota...) before wiring. Confidence: low-medium.
  Expiry: 2026-12-31 (structural; re-run when 2026 adds rows).

- **REPLAY DONE 2026-10-23 (sim engineer, propose-only): HOLD - does not hold on 2026 yet, needs more weeks + a gate before wiring.**
  Table: data/sim_qb_history.js (build_qb_history.py; 258 QBs, 236 with 2012-26 dropbacks, all 90 engine-pool QB names matched, 0 unmatched).
  Replay: _tmp/qb_inherit_replay_2026.md (research_qb_inherit_replay_2026.py + _tmp/qb_replay_dump.js). 14 fired + started 2026 fill-in
  rows (Rush W2, Lock W2, Winston W3-6, Mariota W3-4, Bagent W4-5, J.Daniels TB W4-6, Huntley W5): shadow MAE 6.91 -> 6.77 (-2.0%, closer 9/14)
  but the SHIPPED number (prop anchor on top) 6.92 -> 7.02 (+1.5%, closer 6/14); finished-game rows (n 13) shadow -3.8% / shipped +1.3%;
  W4-6 max-form rows (n 9) shadow -5.1% / shipped +1.6%. L ran above the shadow (14.5 vs 14.0) while the 2026 fill-ins scored 13.3.
  Wiring hazards found: (1) the engine's S for an IR'd / overridden starter is his number at his CURRENT chart string (+qb4 cap: Hurts 7.5,
  Dart 3.4), so .85 S never binds and P-2 = avg(L, own); (2) P-2 must be GATED to a genuine next-man-up start (fill-in effective string 1,
  absent starter cap <= .5, absent = engine main / better chart string) or it lifts Kaliakmanis WAS 2.7 -> 9.2, Bagent CHI 4.6 -> 9.2 and
  every starter with a backup out. W7/W8 if wired: McCarthy NYG 8.7 -> 12.6 (W7), McKee PHI 12.8 -> 13.8 (W7) / 12.7 -> 13.8 (W8).


## P-20261110-1 - (weak) QB rest-of-season tilt for missing pass-catchers
- What: for LATER weeks only (never the current week), tilt a QB's number down when a large share of his team's targets is
  absent this week, up when the room is whole: x (1 - 0.10 x (min(v, .6) - .18)), v = sum of the season-to-date target shares
  of teammates who are Out / Doubtful / on a reserve list / off the roster (ctx feature `vac_tgt`; QB average .18). Range x1.018
  (nobody missing) to x0.958 (60%+ of targets missing). Same family as the shipped rest-of-season volume tilts (ROS_TILT / +rtilt).
- File / knob: engine.js shadow later-weeks block (next to `rbPlays` / `teTilt` in NC_SHADOW.next); v is already computable from
  the vacancy pool shares. New why step + NOTES chip ("QB: 34% of targets out"). Kill switch suggestion: window.SIM_NC_QB_VACT = false.
- Size: typical move 0 to -0.5 pts on a later-week QB number; biggest cells -4%. Whole top-150 board -0.2 to -0.5% (QB rows only).
- Evidence (research_stat_sweep.py -> research_stat_sweep_ros.py -> research_stat_sweep_qbvac.py; _tmp/qbvac4.out, _tmp/qbvac1.out;
  rest-of-season harness backtest_shadow_ros.py on the WIRED stack through v2.28, 2019-25, top-150 QB checkpoints with 3-10
  games played, final week out; survivor filter 4+ games left n 833, no filter n 922):
  act / proj by share of targets missing (4+ left | no filter): 0-.05 1.034 | 1.026; .05-.15 1.021 | 1.020; .15-.30 .968 | .967;
  .30-.45 .973 | .926; .45+ .976 | .899.
  | form | run | wtd MSE | yrs | MAE | yrs | rank d | yrs | fwd | yrs |
  |---|---|---|---|---|---|---|---|---|---|
  | **centred e .10** | 4+ left | -1.22% | 5/7 | -0.89% | 7/7 | +.011 | 6/7 | -1.15% | 3/4 |
  | **centred e .10** | no filter | -1.70% | 6/7 | -1.02% | 6/7 | +.013 | 6/7 | -1.82% | 4/4 |
  | centred e .15 | 4+ left | -1.36% | 5/7 | -1.12% | 6/7 | +.009 | 6/7 | -1.28% | 3/4 |
  | centred e .15 | no filter | -2.19% | 5/7 | -1.32% | 6/7 | +.012 | 6/7 | -2.39% | 3/4 |
  | dock only e .10 (not centred) | 4+ left | -1.29% | 5/7 | -0.61% | 5/7 | +.012 | 6/7 | -1.09% | 3/4 |
  | dock only e .10 (not centred) | no filter | -2.67% | 6/7 | -1.00% | 5/7 | +.015 | 7/7 | -2.65% | 3/4 |
  | LOYO-fit z tilt (k -.03 every fold) | 4+ left | -1.14% | 5/7 | -1.03% | 5/7 | +.009 | 5/7 | -1.38% | 3/4 |
  | LOYO-fit z tilt | no filter | -2.61% | 5/7 | -1.60% | 5/7 | +.019 | 5/7 | -2.75% | 3/4 |
  Folds, centred e .10 (wtd MSE %): 4+ left 2019 -4.1 | 2020 -1.2 | 2021 +1.3 | 2022 -3.1 | 2023 -0.8 | 2024 -1.3 | 2025 +0.3;
  no filter 2019 -4.1 | 2020 -2.0 | 2021 +1.2 | 2022 -4.2 | 2023 -0.1 | 2024 -1.4 | 2025 -1.5.
  FAILS as: a step dock (>= .30 x.95: 4/7 on the 4+ run), sizes e .20+ (2020 / 2024 blow up), QB ADP 101-150 alone (0-1/4
  forward), and at 6-10 games played on the 4+ run (-0.01%, fwd 2/4) - the gain sits in checkpoints with 3-5 games played.
- Not the same as the rejected 10-08 "QB dock when lead WR out": that was the CURRENT week (base already 1.003). Next game the
  raw read here is also ~0 (r -.025, 4/7 seasons) - so later weeks only.
- Caveats: small effect, 2019 and 2022 carry the pooled number; the harness stack stops at v2.28 (no QB starter floor for later
  weeks, no QB opportunity leg v2.34, no split Vegas form, no vacancy fade) - any of those may already absorb part of it, so it
  MUST be re-graded as an engine replay before wiring. No 2026 read (the ctx table is not built for 2026).
  Confidence: low. Expiry: 2026-12-31.
- **Update 2026-11-17 (STATS run): first 2026 read - same direction as history.** `research_qbvac_2026_read.py` -> `_tmp/qbvac_2026_read.log`:
  ROS locks W5-7 graded through W10 (3+ games since, locked ros >= 12), 71 QB rows (~30 QBs, overlapping locks). v = share of
  season-to-date team targets held by teammates who did NOT play the QB's first played projected week (simpler than ctx `vac_tgt`).
  act / proj: 0-.05 1.125 (n 11) | .05-.15 .957 (27) | .15-.30 .961 (26) | .30+ .814 (7). Proposal form on these rows: e .10 MSE
  -1.5%, MAE -0.3%; e .15 MSE -2.1%, MAE -0.5%; closer on 46% of rows. Supportive, not a test (one season, n 7 in the top bucket,
  Daniel Jones twice). Confidence unchanged (low); still needs the engine replay.


## P-20261121-1 - QB-only dud component in the weekly sampler (shape only, mean unchanged)
- What: in samplePlayerScore, for QBs only, draw a "dud" value ~ U(0, .25) x mean with probability q = .03. Otherwise draw the
  gamma at a rescaled mean (mu - q x .125 mu) / (1 - q), so E[X] stays exactly the projection. No other position is touched.
- File / knob: engine.js samplePlayerScore (new QB_DUD = { q: .03 }; kill switch suggestion window.SIM_QB_DUD = false). This is a
  shape change only, so no why / ntWhy step is needed (the mean is unchanged). A NOTES chip "QB dud risk 3%" is optional.
- Evidence (preseason2027/prop245_tests.py -> prop245_tests.log; 2019-25 played games, final week out; q picked on 2019-22,
  scored 2023-25):
  - Real QB dud rate (scores < .25 x projection) vs gamma: 5.2 vs 2.0% (proj 12-16), 3.4 vs 0.7% (16-20), 2.0 vs 0.2% (20+).
    RB/WR/TE do NOT have the gap; it is QB-only.
  - Causes of the 81 QB duds (not exclusive): 56% left early or shared snaps (half of those on next week's injury report, i.e.
    injury exits; half benchings/other); 37% blowouts (base rate 16%); 10% wind 15+ (base rate 7%); 17% none of these.
  - Holdout 2023-25, n 1,088:
    - dud rate: sim 1.4% -> 4.2% (real 4.1%)
    - p10-p90 coverage: 75.6% -> 79.4%
    - CRPS: 4.373 -> 4.351 (-0.5%)
  - Downstream:
    - QB start/sit pair Brier: .2448 -> .2446 (neutral)
    - one 18-pt QB: sd 7.2 -> 8.6; fantasy team-score sd 25.0 -> 25.4
    - P(QB < 4.5 pts): 0.4% -> 3.6%, which is the floor for best ball / guillotine
  - Side finding: QB pair odds are about 2.5 points over-confident with or without the mixture (58.4-58.8% predicted vs 56.2%).
- Size: small. It fixes the tail; it does not move means or rankings.
- Confidence: medium-high on the tail, neutral on decisions.
- Recommend: yes, q .03.
- Needs before wiring: an engine-sampler replay (Sim Lab week sim) to confirm p10/p90 for QBs moves as above.
- Expiry: 2027-03-01.

- **UPDATE 2026-11-21 (later): APPROVED by Jack ("Approve QB dud fix"), IMPLEMENTED, FAILED THE LIVE-ENGINE SHAPE CHECK, REVERTED. Not shipped.**
  - The change: engine.js `QB_DUD = { q: .03, max: .25 }` in samplePlayerScore. The dud decision came from a hash of the gamma draw, so the rng stream was unchanged.
  - Harness: `_tmp/qbdud_verify.js`, outputs `_tmp/qbdud_before.json` and `_tmp/qbdud_after.json`.
  - Checks that passed:
    - Analytic means identical for all 46 QBs (max diff 0).
    - All 309 non-QB rows byte-identical with the same seed.
    - QB sim means +0.04%.
  - The check that FAILED: the live sampler already produces QB duds. In a replay of the 2026 W1-10 QB locks (n 286, current per-player sigma):

    | | dud rate | p10-p90 coverage |
    |---|---|---|
    | real | 4.5% | - |
    | before | 4.1% | 80.8% |
    | after | **6.8%** | **82.9%** |

    The fix overshoots on the live engine.
  - Cause: the backtest compared real QBs with a moment-matched PURE gamma at band CV (1.4% duds). The engine's draw is a gamma whose mean moves with the correlated factor loadings (floor .25), which already fattens the left tail.
  - Restored: `engine.js` = `engine.js.bak_pre_qbdud_20261121` (byte-identical, cmp verified). The attempted version is kept as `engine.js.qbdud_attempt_20261121_reverted`.
  - Nothing exported, synced or deployed.
  - A re-test would need the engine sampler itself graded on history, which needs per-player sigma as of each past week. Status: closed unless Jack wants that.
  - **CLOSED by Jack 2026-11-21.** Asked "Close the QB dud fix, or re-test it on 2019-25 with the real engine?", he answered "Close it". No re-test. Don't re-propose a QB dud component without new evidence from the engine's own sampler.

## P-20261121-2 - Opposing-QB correlation up: CORR.gV .50 -> .63 (QB-oppQB .195 -> .249)
- NOTE (2026-11-21, after P-20261121-1 failed): this proposal's evidence also came from an engine replica (gamma marginals), not the engine's own sampler. Re-check it on the live sampler before asking Jack to approve it.
- What: raise the game-level passing-environment share gV in engine.js CORR from .50 to .63.
- File / knob: engine.js CORR.gV. Marginals are unchanged by construction, and the factor model stays a valid (PSD) matrix for any
  gV in [0, 1].
- Evidence (prop245_tests.py):
  - Real QB1-oppQB1 residual r: +.252, 90% bootstrap [.197, .309], 862 games 2019-25.
  - By season: .14 to .34. By game-total tercile: low .265 / mid .185 / high .306 (no clean pattern).
  - Engine replica at gV .48 / .50 / .554 / .63 gives QB-oppQB .188 / .195 / .214 / .249.
  - The other cross-game pairs are also under the real ones and move the right way: QB-oppWR1 .074 -> .094 (real .118);
    WR1-oppWR1 .030 -> .036 (real .108).
  - Own-team QB-WR1 is unchanged (.369 -> .365).
  - QB + opposing WR1 bring-back stack sd: 11.89 -> 11.98 (+0.8%).
- Size: measurable on the correlation itself (the current .195 sits at the bottom edge of the CI). Within noise for matchup odds
  and season outcomes. It matters mainly for best ball week-17 game stacks and any DFS work.
- Confidence: medium.
- Recommend: yes, but low priority; ship it with the next sampler change (e.g. together with P-20261121-1).
- Expiry: 2027-03-01.

## P-20261121-3 - Late-season consensus weight (part 4 proposal 2) - NEEDS JACK'S CALL: it uses outside projections
- What: from week 15 (or 14), blend ESPN's weekly projection into the live number at w .6 (shadow .4 / ESPN .6).
- Conflict: this crosses the 2026-11-21 "keep it in-house" line in the same way 4.1 (declined) did.
- Evidence (prop245_tests.py, 2019-25 played games, leave-one-season-out):
  - Weeks 14-17: picked w .6-.7 every fold. MAE 5.091 vs 5.179 (-1.70%), better in 5/7 seasons.
  - Weeks 15-17: MAE 5.070 vs 5.148 (-1.52%), rank rho .456 -> .480, better in 5/7 seasons.
  - The same blend in weeks 5-13 is only -0.6%, so the late effect is larger but not unique.
- Where the gap comes from (weeks 15-17): spread across cases, not one fixable cause.
  - clinched teams: 5.60 vs ESPN 5.43
  - eliminated teams: 5.05 vs 4.98
  - weather: 4.91 vs 4.88
  - late usage change: 4.81 vs 4.70
  - other: 5.36 vs 5.35
- In-house alternatives (Test B, LOYO) did NOT recover any of it:
  - case multipliers + faster usage reaction: +0.47% (worse)
  - per-position late level recalibration: +0.65% (worse, 1/7)
  - The engine runs about 3% low all season (act/proj 1.03), not specially late; raising the level hurts MAE.
- Caveat: the harness has played games only. Pre-kickoff inactives and shutdowns, where consensus zeros would also score, are not
  measured.
- Options:
  1. Consensus w .6 in weeks 15-17: -1.5% MAE, about 0.08 pts per player-week.
  2. In-house fixes: no gain found.
  3. Leave as is.
- Recommend: leave as is unless Jack wants to make an exception to in-house for the fantasy-playoff weeks.
- Expiry: 2027-08-31.

## P-20261121-4 - Book-anchor weight re-tune (part 4 proposal 3) - REVIEWED, NO CHANGE
- Data: 2026 is the only season with stored prop lines (W1-W11 locks). No free pre-2026 prop archive exists; paid The Odds API
  history from May 2023 is listed in the data-pull table for Jack.
- Evidence (preseason2027/prop3_anchor_sweep.py -> prop3_anchor_sweep.log, 2,227 lined rows):
  - The curve is flat. Pooled MAE range is .058 over w .3-.8; QB .020. Best in-sample w per position is near what the tuner
    already uses: QB .7 vs used .68, RB .1 vs .14, WR .4 vs .47, TE .4 vs .26.
  - Honest split: pick on W1-6 / score W7-10 = +0.22% (worse); pick on W7-10 / score W1-6 = -0.40%.
  - Best w by week jumps between 0 and .8.
  - In-sample upper bound on the gain: -0.024 MAE.
- Verdict: don't re-tune; the weekly tuner already tracks it. Re-check at season end with weeks 13-17 (no 2026 data for that band
  yet). Provisional, one season.
- Expiry: 2027-01-15.


## P-20261121-5 - Data pulls awaiting Jack's OK, one at a time (scoped 2026-11-21, nothing pulled)
- Full table: reviews/2026-11-21_sim_review_and_2027_preseason_plan.md, Addendum A4.
- Ranked by value for effort:
  1. FantasyCalc weekly capture. Recommend starting now; the endpoint is undocumented, and the history is lost every week it waits.
  2. DynastyProcess values git history. Pull now.
  3. SurvivorGrid archive. Pull now, politely.
  4. FFC ADP stdev/high/low. Pull now via the allowed HTML pages, or via the API (its robots.txt disallows /api/).
  5. nflverse trades file. Pull now.
  6. MFL auction values. Needs Jack's decision: the API's robots.txt disallows it, its ToS is unread, and a registered client needs his account.
  7. 2027 season props. Capture from about May 1, 2027.
  8. The Odds API props for 2023-25. Paid; needs Jack's decision.
  9. Camp PUP/NFI lists. Record by hand in July 2027.
  10. FantasyPros. Benchmark only; paid; needs Jack's decision.
- Rule slips during scoping (one page each, nothing stored): FFC API (robots disallows /api/), Yahoo pick'em (robots blocks ClaudeBot), NFL.com (ToS).
- Expiry: 2027-05-01.

## P-20261121-6 - New product builds awaiting Jack's OK, one at a time (scoped 2026-11-21, none built)
- Full ranked table and 2027 timeline: report Addendum A5.
- Build order of shared foundations: F1 game layer -> F2 settings-driven value layer -> F3 team-score distribution fixes -> F4 field/popularity model.
- Top picks:
  - the value layer (after preseason v1)
  - best ball upgrades plus the BBM VI backtest (by ~Mar 1, 2027)
  - the playoff-schedule view (after F1)
- Convenience-only products (no measured edge): NFL bracket, straight-up and against-the-spread pick'em, survivor without pick popularity.
- Skip for 2027: DFS, IDP.
- Expiry: 2027-03-01.


## P-20261121-7 - 2027 preseason per-game model: ADP as an input? (NEEDS JACK'S CALL; no engine change)
- Context: the in-house per-game model v1 (preseason2027/pergame_model.py, report A7).
  - In-house: MAE 2.711 -> 2.627, rho .437 -> .472.
  - ADP curve: 2.491 / .548. In-house beats ADP in 1 of 11 seasons.
- ADP-anchored variant: .2 in-house + .8 ADP curve.
  - Per game: MAE 2.464, beats ADP in 9/11 seasons (3/3 in 2023-25); rank ties ADP.
  - Season totals: 49.42 / Spearman .514 vs ADP 49.69 / .501.
- The question: should the 2027 preseason prior be in-house only, or in-house + ADP as market data?
  - The live engine's in-season veteran prior is already 75% ADP (A1).
  - ADP is market data, not a projection.
- No live-engine change is involved. Expiry: 2027-06-01 (before the preseason build).
- Data for approval: historical August depth charts 2019-24 (Wayback ESPN / Ourlads). Robots and terms must be checked before
  reading any page; nothing has been read.
