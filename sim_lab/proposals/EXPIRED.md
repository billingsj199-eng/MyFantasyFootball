# Sim proposals - EXPIRED (full text kept for reference; an expired item can be re-queued after a re-test)


<!-- expired 2026-11-10 (reached its expiry date without an approve / reject) -->
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


<!-- expired 2026-11-10 (reached its expiry date without an approve / reject) -->
## P-20261013-4 - (weak) rest-of-season lift after a blowout game x~1.02
- What: players (RB/WR/TE top 150) whose team's LAST game was a blowout (6+ garbage plays, |margin| >= 17) x ~1.02 for later
  weeks. Under-projected next game 1.041 vs ~1.015 board (6/7 seasons) and ROS 1.049 (7/7).
- Evidence (_tmp/vb_c5.py, volume_budget_c5.log): LOYO flag multiplier (fit on training, shrunk 50%) ROS board -0.58% (6/7, fwd
  4/4), flagged rows -2.6%; next game -0.13% (7/7, fwd 4/4) below the -0.3% bar. Down-weighting blowout games in the points
  evidence instead FAILS (LOYO ROS +0.35%). Mechanism unknown (win / loss both under) - may be a harness gap.
- Confidence: low; needs an engine-form re-test before any number. Expiry: 2026-11-10.


