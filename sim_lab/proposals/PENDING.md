# Sim proposals - PENDING (approve/reject in chat: "approve P-20261013-1")


## P-20261013-1 - Vacancy ALLOCATION from observed shares (replaces the depth-rank pool boost, CURRENT week)
- What: for a healthy RB/WR/TE whose teammate is out, size the boost from the position-group VOLUME BUDGET instead of the
  depth-rank POOL rule: ratio = budget xFP with next game's availability / budget xFP without availability renorm, applied at e 1
  (clip .6-1.8) on the shadow WITHOUT the pool / vacx boost. Shares are the player's recency-weighted (d .9) share of team
  targets / non-QB carries, each past game normalised to full strength and re-normalised to next game's roster:
  s = u x (1 + rho x missing same-group share / present same-group share), rho targets .25, carries .6. Every body with a snap is
  in the group; an absence already seen in games played is not paid again by construction.
- File / knob: engine.js weeklyProjection shadow vacancy block (SIM_NC_EXACT / vacx / workhorse) -> new budget allocation for the
  current week only; needs per-team-game target / carry shares (pbp 2026 already builds them) in a data file. Later weeks: see -2.
- Size: harness pool rows mean boost 1.10 (RB 1.2); Kamara W6 2026: budget +8% (9.6 xFP vs 8.9) instead of iA 1.486 -> ~7.5
  half instead of 10.35. Miller 7.2 xFP, Donaldson 2.9 xFP.
- Evidence (research_volume_budget.py points, volume_budget.log; next game, top-150 weighted, 2019-25, vs shadow + pool k .75):
  fixed e 1: -0.39% (5/7, fwd 3/4), rank rho .4272 -> .4320; LOYO-picked -0.32% (5/7), forward 2022-25 -0.43% (3/4).
  Folds e1: 2019 +0.02 | 2020 -0.27 | 2021 -0.22 | 2022 +0.38 | 2023 -1.18 | 2024 -0.23 | 2025 -0.99 (%).
  Kamara-size boosts (pool >= 1.3) never-seen absences: act/proj 1.136 under the pool, 1.005 under the allocation (n 49).
  Rest of season FAILS (+0.37%, 2/7) unless decayed - current week only.
- Caveat: harness pool = usage-based replica at k .75, not the engine's exact vacx + workhorse + NMU + TEAM_VAC + promo stack ->
  must be re-graded as an engine port (replay) before wiring. Confidence: medium-low. Expiry: 2026-11-10.

- UPDATE 2026-10-13 (Jack: port OFF + replay on the full stack): engine.js `budgetAllocRatio` + `BUDGET_ALLOC`, switch
  window.SIM_NC_BUDGET_ALLOC === true (default OFF; parity check: 423 current-week rows identical to the pre-change engine).
  Replay vs the wired teammate stack (shadow + pool x NMU x PROMO x TEAM_VAC; research_alloc_fullstack.py / alloc_fullstack.log):
  ALLOC-A (replaces pool/vacx only) e .75 -0.30% (5/7, fwd 3/4), LOYO -0.30% (5/7) fwd -0.30% (2/4) = at the bar's edge;
  e 1 -0.21% (4/7); RB -0.52% (6/7) WR +0.10% TE -0.26% (3/7); ADP 1-60 worse, 61-150 better (-0.51 / -1.61%).
  ALLOC-B (replaces the whole stack) FAILS (LOYO +0.27%, 0/7). Not replicable: workhorse cell, fill-in rescale.
  W6 2026 with it ON (e .75): Kamara 10.65 -> 8.75, Miller 6.11 -> 5.42, Donaldson 2.04 -> 1.67; 132 W6 rows move >= .05
  (Dameon Pierce 6.77 -> 3.65, Brandin Cooks 5.43 -> 3.88: bodies whose vacx gain was larger than their observed-share renorm).
  LOSING SEASONS (ALLOC-A e1 vs stack): 2019 +0.24% - David Johnson ARI wk10/13/15 (Edmonds out; Kenyan Drake traded IN wk9 has no
  history share, so DJ got the room: NEWCOMER gap, fixable), Keenan Allen wk4 (Henry + M. Williams out, scored 7.3: noise),
  Kupp wk11 (Cooks out, Kupp's role was shrinking: role change), Saquon wk7 (first games back: noise); 2021 +0.06% - Zeke wk14,
  Swift wk8, Chubb wk8 (lead RB's backup out, lead scored 5-8: outlier games / own injuries, noise); 2022 +0.57% - Jonathan
  Taylor IND wk3/4/15 (cut WR Dezmon Patmon counted as an ABSENT member; Taylor himself hurt: DEPARTED-MEMBER flaw, fixable),
  Elijah Mitchell SF wk10 (Ra 1.53: Jeff Wilson TRADED away + McCaffrey traded in with no share = both flaws), Ekeler wk13.
  Fixable before any re-test: (1) a member who left the team (cut / traded) is not "absent"; (2) a newcomer gets his share from
  his previous team (or his shadow level) instead of 0. The engine port already drops departed players (pool = current team) but
  credits a newcomer's pre-trade weeks to his new team - fix that too. Recommendation: do NOT ship; re-test with (1)+(2).

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


## P-20261013-4 - (weak) rest-of-season lift after a blowout game x~1.02
- What: players (RB/WR/TE top 150) whose team's LAST game was a blowout (6+ garbage plays, |margin| >= 17) x ~1.02 for later
  weeks. Under-projected next game 1.041 vs ~1.015 board (6/7 seasons) and ROS 1.049 (7/7).
- Evidence (_tmp/vb_c5.py, volume_budget_c5.log): LOYO flag multiplier (fit on training, shrunk 50%) ROS board -0.58% (6/7, fwd
  4/4), flagged rows -2.6%; next game -0.13% (7/7, fwd 4/4) below the -0.3% bar. Down-weighting blowout games in the points
  evidence instead FAILS (LOYO ROS +0.35%). Mechanism unknown (win / loss both under) - may be a harness gap.
- Confidence: low; needs an engine-form re-test before any number. Expiry: 2026-11-10.


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
