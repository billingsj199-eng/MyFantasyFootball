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
