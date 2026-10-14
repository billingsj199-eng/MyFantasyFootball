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

## P-20261014-2 - Out-unconfirmed level: tier it (0 near kickoff / .50 lingering / .20 new) instead of flat x0.75
- What: the engine prices a Sleeper "Out" that Sleeper still projects and the NFL report hasn't called Out/Doubtful at
  x0.75 ('out-unconfirmed', feedback_out_flag_guard). Measured, that state played 34% of the time, and it is really three states:
  (a) within 36 h of HIS kickoff -> 0 (this is the gameday inactive list: Sleeper tags Out ~90 min before kickoff before it
      pulls his projection, so the pre-kickoff export FROZE x0.75 rows for inactives - Puka Nacua W2, Keenan Allen W4,
      Addison + Dowdle W5);
  (b) earlier in the week, he MISSED his previous game (Out lingering from last week) -> 0.50;
  (c) earlier in the week, he PLAYED his previous game (new injury, Sleeper tagged Out after it) -> 0.20.
  Teammates follow automatically (vacancy = 1 - level, since the 10-14 shadowOut fix).
- File / knob: engine.js applyInSeasonInjuries `out-unconfirmed` branch (~3115): mult from hours-to-kickoff (kickoffs are in the
  exporter; engine needs them passed or read from SIM kick data) + played-previous-game (jsData wks / sim_2026). Keep the src
  name + NOTES chip; add the tier to the chip text. Same for 'na-unconfirmed'? (not measured - leave).
- Evidence (research_out_unconfirmed.py, _tmp/out_unconfirmed.log; every committed Sleeper injury snapshot 09-01..10-14 x weekly
  Sleeper proj x NFL practice report, W1-W5 graded on snap counts): 115 player-weeks / 298 export-time states.
    <36 h before kickoff: 0 / 43 played (CI 0-.08)        36-96 h: 0 / 4
    >96 h, missed previous game: 37 / 69 = .54 (CI .42-.65)   >96 h, played previous game: 2 / 11 = .18 (CI .05-.48)
  Brier (state level): flat .75 (live) .386 | flat .33 .229 | tiered .50/.10/0 .178.
  Leave-one-week-out (rates fit on the other weeks, late tier 0): tiered beats flat .75 in 5/5 weeks, pooled .180 vs .386;
  fitted rates stable: lingering .49-.53, new injury .14-.25.
- Not graded: projection POINTS (only availability). Small cells: new-injury n=11. 2026 only (Sleeper tag history doesn't exist
  for older seasons).
- Confidence: high for (a) and for dropping .75; medium for the exact .50 / .20. Note (a) zeroes a player before an NFL "Out"
  - but the inactive list IS out; this is Jack's never-zero-before-Out rule, so his call. Expiry: 2026-12-31.
