import io
readme = r"""

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
"""
p = r"E:\MyFantasyFootball\sim_lab\README.md"; s = io.open(p, encoding="utf-8").read()
if "RANK MIX: a third graded number" not in s: io.open(p, "a", encoding="utf-8", newline="\n").write(readme)
M = r"C:\Users\billi\.claude\projects\E--MyFantasyFootball-MyFantasyFootball-Files\memory"
mem = """---
name: project_rank_mix
description: 09-17 RANK MIX live as a third graded number - engine rmMean = 50% Clay-free shadow + 50% ESPN weekly, rmFinal = same book anchor on top; SIM_ESPN_WEEKLY feed via refresh_data.py; graded Tuesdays by score_week; GOTCHA weeklyProjection().mean is the raw Clay stack, the live board = propMean ?? jsMean
metadata:
  type: project
---

Jack (2026-09-17): "build the rankings mix". Most accurate weekly ranking in the 7-season test = even mix of our
shadow and ESPN ([[project_vs_espn]]); built as a THIRD number beside the live board and the shadow, never feeds live.
- Feed: refresh_data.py writes window.SIM_ESPN_WEEKLY {week, p:{norm:[half,ppr,std]}} into data/sleeper_meta.js from
  repo data/weekly_projections.json key "e" (9am consensus pull). Week-gated.
- Engine: espnPts = std + sc.rec x (ppr - std); rmMean = .5 ncMean + .5 espnPts (NC_SHADOW.rankMixW); rmFinal =
  propMean + (1 - propW)(rmMean - baseM) on book-lined rows else rmMean. Lock stores rmMean / rmFinal / espn. Kill
  window.SIM_RANKMIX = false.
- score_week.py grades "Rank mix" and "Rank mix+books" every Tuesday; rankmix_week.js <week> prints the rankings.
- W2: mix+books within 0.44 pts of the live board on average (0.39 lined, 1.11 un-lined).

**GOTCHA (cost me a mislabeled column all day 09-17):** weeklyProjection().mean is the RAW CLAY STACK. The live board
number is engine effMean = propMean when book lines exist, else jsMean. In headless scripts always use
propMean ?? jsMean ?? mean for "live".
**How to apply:** promotion of the mix (or any base swap) waits on Tuesday grades + Jack's call
([[project_most_accurate_base]], [[feedback_clay_stays_base]]). See [[project_weekly_proj_sources]].
"""
io.open(M + r"\project_rank_mix.md", "w", encoding="utf-8", newline="\n").write(mem)
f = M + r"\MEMORY.md"; t = io.open(f, encoding="utf-8").read()
line = "- [Rank mix (3rd graded number)](project_rank_mix.md) — 09-17: engine rmMean = 50% shadow + 50% ESPN, rmFinal = books on top; SIM_ESPN_WEEKLY feed; Tuesday-graded; GOTCHA weeklyProjection().mean = raw Clay stack, live board = propMean ?? jsMean\n"
if "project_rank_mix" not in t: t = t.replace("- [Season-long harness]", line + "- [Season-long harness]", 1)
io.open(f, "w", encoding="utf-8", newline="\n").write(t); print("docs ok")
