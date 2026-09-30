import io
readme = r"""

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
"""
p = r"E:\MyFantasyFootball\sim_lab\README.md"; s = io.open(p, encoding="utf-8").read()
if "Shadow v2.22: TD-luck double count fixed" not in s: io.open(p, "a", encoding="utf-8", newline="\n").write(readme)
M = r"C:\Users\billi\.claude\projects\E--MyFantasyFootball-MyFantasyFootball-Files\memory"
mem = """---
name: project_shadow_luck_scale
description: 09-17 v2.22 BUG FIX shadow-only - the shadow reused the live TD-luck adjustment (sized for points evidence at g/(5+g)) while its own weight on points is ~0 after v2.18 usage evidence + v2.21 WR P=40; now scaled by the shadow's weight on points; found tracing Jefferson W2; trace_shadow.js instruments the engine in memory
metadata:
  type: project
---

Jack (2026-09-17): "why is the shadow so low on jefferson and flowers". Flowers (and McConkey) = Questionable ->
availability 0.75, working as designed (ESPN does not dock designations; Clay blend docked too). Jefferson had no flag:
prior 13.3, blended 13.4, then -2.2 of TD luck. tdLuckAdj() = k x TD pts x (xTD - TD)/g x g/(5+g) regresses luck that
entered through POINTS at the LIVE weight; the shadow's weight on points is (1 - lam) g / (P + g) = ~0 for RB / WR
after one game (usage lam 1) and with WR P = 40, and smaller than live since v2 (P 12 / 8 / 8). Fix: ncLuckScale =
shadow weight / live weight (clamp 0-1.5) on the luck term in both shadow branches; kill SIM_NC_LUCKFIX=false.
W2: 133 top-150 shadows move, mean .26; Jefferson 11.2 -> 12.3, St. Brown 13.9 -> 15.2, Henry 14.2 -> 15.6;
mean |shadow - ESPN| 1.27 -> 1.13.

**Why:** the harness shadow has NO luck term, so every backtest of v2.18 / v2.21 graded a form the live engine was not
running - a live-vs-harness parity gap, exactly the risk I flagged before any base swap.
**How to apply:** when a shadow layer changes the evidence or the prior strength, re-check every additive term sized
for the live blend. sim_lab/_tmp/trace_shadow.js <week> <names...> prints the shadow's intermediate values from an
in-memory instrumented engine - use it before trusting any single-player shadow number. Jefferson's remaining gap =
last-8 history (2025 collapse), the riser / rebound blind spot. See [[project_inseason_usage]], [[project_early_prior]],
[[project_wr_tdluck]], [[project_banged_up]], [[project_rank_mix]].
"""
io.open(M + r"\project_shadow_luck_scale.md", "w", encoding="utf-8", newline="\n").write(mem)
f = M + r"\MEMORY.md"; t = io.open(f, encoding="utf-8").read()
line = "- [Shadow TD-luck scale v2.22 (bug fix)](project_shadow_luck_scale.md) — 09-17: shadow was subtracting live-sized TD luck it never added (usage evidence + WR P=40); scaled by its own weight on points; trace_shadow.js = in-memory engine tracer\n"
if "project_shadow_luck_scale" not in t: t = t.replace("- [Season-long harness]", line + "- [Season-long harness]", 1)
t = t.replace("WR one-game prior x5 v2.21)", "WR one-game prior x5 v2.21, TD-luck scale fix v2.22)", 1)
io.open(f, "w", encoding="utf-8", newline="\n").write(t); print("docs ok")
