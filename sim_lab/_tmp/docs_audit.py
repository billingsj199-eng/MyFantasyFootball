import io
readme = r"""

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
"""
p = r"E:\MyFantasyFootball\sim_lab\README.md"; s = io.open(p, encoding="utf-8").read()
if "Shadow audit (audit_shadow.js) + history-window test" not in s: io.open(p, "a", encoding="utf-8", newline="\n").write(readme)
M = r"C:\Users\billi\.claude\projects\E--MyFantasyFootball-MyFantasyFootball-Files\memory"
mem = """---
name: project_shadow_audit
description: 09-17 shadow audit tool (audit_shadow.js) - all 144 top-150 shadows reconstruct exactly; 2 bugs fixed (kenny/kenneth gainwell feed name, HIST+OPP input parity v2.23); history-window test - decayed games half-life 10-16 beats 3-season+last-8 by 3% (last-8 weight should be ~.2 not .5), short windows are noise
metadata:
  type: project
---

Jack (2026-09-17): "are there any other bugs like that in the shadow" / "do we really need a 3 year history".
- sim_lab/audit_shadow.js <week>: instruments engine.js in memory, rebuilds every top-150 shadow from its pieces, runs
  input invariants, scans feeds for name mismatches. Result W2: 0 unexplained of 144. Run it after any shadow change.
- Bug: pbp feed "kenny gainwell" vs pool "kenneth gainwell" (xFP usage + RB TD luck, the latter LIVE). Fixed via
  PLAYER_ALIAS in pull_pace_tracker.py.
- Parity (v2.23): HIST+OPP calibration was fitted on the regressed 3-SEASON history (no last-8); live fed the 50/50
  blend. Now opHist = shadowAgeAdjust(h3); kill SIM_NC_OPPHIST=false. Tiny net effect: the ridge uses oppcal as a
  contrast with a negative weight, cancelling the hand prior's move.
- sim_lab/backtest_history_window.py: last season only +9%, last 8 games +12.6%, last 4 +35%, 3 seasons +0.6% vs the
  current blend (top 150 weighted); decayed games half-life 10 = -3.2% (6/7), hl 16 -2.8%. When last-8 is 3+ below
  the 3-season level the next season follows the 3-season level (best-fit last-8 weight .18; we use .50).

**Why:** the TD-luck bug showed the live shadow can drift from the graded harness form; an audit tool makes that
checkable instead of trusted.
**How to apply:** decayed-games history is the next prior improvement but is diluted in the final shadow (75% ADP
curve + shrink + 50% ridge) and needs a live game-log feed + a refit of backtest_opp_prior.py. See
[[project_shadow_luck_scale]], [[project_opp_prior]], [[project_season_long_harness]].
"""
io.open(M + r"\project_shadow_audit.md", "w", encoding="utf-8", newline="\n").write(mem)
f = M + r"\MEMORY.md"; t = io.open(f, encoding="utf-8").read()
line = "- [Shadow audit + history windows](project_shadow_audit.md) — 09-17: audit_shadow.js rebuilds every top-150 shadow (0/144 unexplained); fixed gainwell name + HIST+OPP input parity v2.23; decayed-games history (hl 10-16) beats 3yr+last-8 by 3%, last-8 over-weighted\n"
if "project_shadow_audit" not in t: t = t.replace("- [Season-long harness]", line + "- [Season-long harness]", 1)
io.open(f, "w", encoding="utf-8", newline="\n").write(t); print("docs ok")
