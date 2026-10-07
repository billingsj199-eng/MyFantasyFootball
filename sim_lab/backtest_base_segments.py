#!/usr/bin/env python3
"""
WHO IS THE SHADOW LOWER ON, AND WHERE IS CLAY'S ADVANTAGE?  (Jack 2026-10-07: "can we figure out what types of players
are lower and what the clay advantage is?")  Same rows and models as backtest_base_remeasure.py (live Clay blend and the
Clay-free shadow, both as wired today, next game, pre-book, 2019-25, top 150, final week dropped).

For every player type: how far the shadow sits below / above the live number, which side the actual landed on
(actual / live, actual / shadow), which side was closer (importance-weighted error, shadow vs live, seasons the shadow
is better of 7) and the best blend weight on that cut. Then the same read for the rows where the two models DISAGREE
most, split by direction. Log base_segments.log.
"""
import os, sys
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
SN = BR.SN; NW = BR.NW; YEARS = BR.YEARS; POS4 = BR.POS4
LOG = open(os.path.join(HERE, "base_segments.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
WG = (0.0, 0.3, 0.5, 0.7, 1.0)


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    base = top150 & ~final & ~LV["inh"]
    wm = lambda q, mm: float(np.average((q[mm] - act[mm]) ** 2, weights=wt[mm])) if mm.any() else np.nan
    blend = lambda w: w * SHADOW + (1 - w) * TODAY
    # ---- features for the cuts
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = A["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    new_pc, new_hc, tgt_sh, car_sh, snap_l1, implied, rep_q, strb = colv("new_pc"), colv("new_hc"), colv("tgt_sh"), colv("car_sh"), colv("snap_l1"), colv("implied"), colv("rep_q"), F["strb"]
    exp, age, mover, rookie, h3g, l8g = np.array(A["exp"], float), np.array(A["age"], float), np.array(A["mover"], bool), np.array(A["rookie"], bool), np.array(A["h3g"], float), np.array(A["l8g"], float)
    clay_gm, prior, ppg = LV["clay_gm"], X["prior"], X["ppg"]
    cvh = np.where(prior > 1, clay_gm / prior, np.nan)                      # Clay's preseason number vs the history prior
    hot = np.where((g >= 3) & (clay_gm > 1), ppg / clay_gm, np.nan)           # season so far vs Clay
    thin = ~rookie & (h3g + l8g < 8)
    diff = SHADOW - TODAY
    HDR = f"    {'type':46s} {'n':>5s} {'shadow-live':>11s} {'act/live':>8s} {'act/shad':>8s} | {'shadow err vs live':>19s} | {'best w':>6s}"
    def row(lab, m, out):
        m = m & base
        if m.sum() < 120: return
        d = 100 * (wm(SHADOW, m) / wm(TODAY, m) - 1); wins = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and wm(SHADOW, m & (year == y)) < wm(TODAY, m & (year == y)) - 1e-12)
        ny = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8)
        best = min(WG, key=lambda w: wm(blend(w), m))
        out.append((lab, int(m.sum()), float(diff[m].mean()), act[m].sum() / TODAY[m].sum(), act[m].sum() / SHADOW[m].sum(), d, wins, ny, best))
    def show(title, cuts, sort=None):
        out = []
        for lab, m in cuts: row(lab, m, out)
        if sort == "diff": out.sort(key=lambda r: r[2])
        elif sort == "clay": out.sort(key=lambda r: -r[5])
        P(f"\n--- {title} ---"); P(HDR)
        for r in out:
            P(f"    {r[0]:46s} {r[1]:5d} {r[2]:+11.2f} {r[3]:8.3f} {r[4]:8.3f} | {r[5]:+7.2f}% ({r[6]}/{r[7]}) {'SHADOW' if r[5] < -0.5 else 'CLAY' if r[5] > 0.5 else 'tie':6s} | {r[8]:6.1f}")
        return out
    P(f"=== WHO IS THE SHADOW LOWER ON / WHERE IS CLAY'S ADVANTAGE: {int(base.sum()):,} top-150 player-weeks, next game, 2019-25 ===")
    P("    shadow-live = mean points per game the shadow sits above (+) or below (-) the live Clay blend; act/x = actual over projection (>1 = too low)")
    P("    shadow err vs live = importance-weighted squared error, negative = shadow closer; (seasons shadow closer / seasons with rows); best w = blend weight on the shadow")
    ALL = []
    ALL += show("1  POSITION x ADP BAND", [(f"{ps} ADP {a}-{b}", (pos == ps) & (adp > a - 1) & (adp <= b)) for ps in POS4 for a, b in ((1, 30), (31, 60), (61, 100), (101, 150))])
    ALL += show("2  EXPERIENCE / AGE", [(f"{ps} rookies", (pos == ps) & rookie) for ps in POS4] + [(f"{ps} second year", (pos == ps) & (exp == 1)) for ps in POS4] +
                [(f"{ps} age 30+", (pos == ps) & (age >= 30)) for ps in POS4] + [(f"{ps} thin history (< 8 prior games, not rookie)", (pos == ps) & thin) for ps in POS4])
    ALL += show("3  SITUATION CHANGE", [(f"{ps} changed teams", (pos == ps) & mover) for ps in POS4] + [(f"{ps} new playcaller", (pos == ps) & (new_pc == 1)) for ps in POS4] +
                [(f"{ps} new head coach", (pos == ps) & (new_hc == 1)) for ps in POS4] + [("WR, team's QB out this week", (pos == "WR") & (colv("qb_out") == 1))])
    ALL += show("4  CLAY vs HISTORY PRIOR (preseason disagreement)", [(f"{ps} Clay >= 25% above history", (pos == ps) & (cvh >= 1.25)) for ps in POS4] +
                [(f"{ps} Clay within 25% of history", (pos == ps) & (cvh > 0.75) & (cvh < 1.25)) for ps in POS4] + [(f"{ps} Clay <= 25% below history", (pos == ps) & (cvh <= 0.75)) for ps in POS4])
    ALL += show("5  SEASON SO FAR vs CLAY (3+ games)", [(f"{ps} running hot (>= 1.25x Clay)", (pos == ps) & (hot >= 1.25)) for ps in POS4] +
                [(f"{ps} near Clay (.8-1.25x)", (pos == ps) & (hot > 0.8) & (hot < 1.25)) for ps in POS4] + [(f"{ps} running cold (<= .8x Clay)", (pos == ps) & (hot <= 0.8)) for ps in POS4])
    ALL += show("6  ROLE", [("WR target share >= 25%", (pos == "WR") & (tgt_sh >= 0.25)), ("WR target share 15-25%", (pos == "WR") & (tgt_sh >= 0.15) & (tgt_sh < 0.25)), ("WR target share < 15%", (pos == "WR") & (tgt_sh < 0.15)),
                           ("TE target share >= 18%", (pos == "TE") & (tgt_sh >= 0.18)), ("TE target share < 18%", (pos == "TE") & (tgt_sh < 0.18)),
                           ("RB carry share >= 55%", (pos == "RB") & (car_sh >= 0.55)), ("RB carry share 30-55%", (pos == "RB") & (car_sh >= 0.30) & (car_sh < 0.55)), ("RB carry share < 30%", (pos == "RB") & (car_sh < 0.30)),
                           ("WR/TE last-game snap share < 60%", np.isin(pos, ("WR", "TE")) & (snap_l1 < 60)), ("WR/TE last-game snap share >= 85%", np.isin(pos, ("WR", "TE")) & (snap_l1 >= 85)),
                           ("listed first string", strb == 1), ("listed second string or lower", strb >= 2), ("listed Questionable", rep_q == 1)])
    ALL += show("7  GAME CONTEXT", [("team implied < 19", implied < 19), ("team implied 19-24", (implied >= 19) & (implied < 24)), ("team implied 24+", implied >= 24)])
    ALL += show("8  GAMES PLAYED", [(f"{ps} {a}-{b} games", (pos == ps) & (g >= a) & (g <= b)) for ps in POS4 for a, b in ((1, 2), (3, 6), (7, 17))])
    P("\n=== 9  SUMMARY: where the shadow sits LOWEST vs the live number (and who was right) ===")
    for r in sorted(ALL, key=lambda r: r[2])[:12]: P(f"    {r[0]:46s} n{r[1]:5d} shadow {r[2]:+.2f}/g | act/live {r[3]:.3f} act/shadow {r[4]:.3f} | shadow err {r[5]:+.2f}% ({r[6]}/{r[7]})")
    P("\n=== 10  SUMMARY: where the shadow sits HIGHEST vs the live number ===")
    for r in sorted(ALL, key=lambda r: -r[2])[:10]: P(f"    {r[0]:46s} n{r[1]:5d} shadow {r[2]:+.2f}/g | act/live {r[3]:.3f} act/shadow {r[4]:.3f} | shadow err {r[5]:+.2f}% ({r[6]}/{r[7]})")
    P("\n=== 11  SUMMARY: CLAY'S ADVANTAGE - types where the live Clay blend is closer than the shadow (sorted, 3+ seasons the Clay side won) ===")
    for r in sorted([r for r in ALL if r[5] > 0 and (r[7] - r[6]) >= 4], key=lambda r: -r[5])[:15]: P(f"    {r[0]:46s} n{r[1]:5d} Clay closer by {r[5]:+.2f}% (Clay better {r[7]-r[6]}/{r[7]}) | shadow {r[2]:+.2f}/g | act/live {r[3]:.3f} act/shadow {r[4]:.3f} | best w {r[8]:.1f}")
    P("\n=== 12  SUMMARY: SHADOW'S ADVANTAGE (sorted, 5+ seasons) ===")
    for r in sorted([r for r in ALL if r[5] < 0 and r[6] >= 5], key=lambda r: r[5])[:15]: P(f"    {r[0]:46s} n{r[1]:5d} shadow closer by {r[5]:+.2f}% ({r[6]}/{r[7]}) | shadow {r[2]:+.2f}/g | act/live {r[3]:.3f} act/shadow {r[4]:.3f} | best w {r[8]:.1f}")
    # ---- disagreement rows
    P("\n=== 13  WHEN THE TWO MODELS DISAGREE BY 15%+ (top 150): who was right, by direction and position ===")
    rel = np.where(TODAY > 1, diff / TODAY, 0.0)
    P(f"    {'cut':40s} {'n':>5s} {'shadow-live':>11s} {'act/live':>8s} {'act/shad':>8s} | shadow err vs live | share of the gap the actual closed toward the shadow")
    for lab, m in [("shadow 15%+ LOWER, all", rel <= -0.15), ("shadow 15%+ HIGHER, all", rel >= 0.15)] + [(f"shadow 15%+ LOWER, {ps}", (rel <= -0.15) & (pos == ps)) for ps in POS4] + [(f"shadow 15%+ HIGHER, {ps}", (rel >= 0.15) & (pos == ps)) for ps in POS4] + \
                  [(f"shadow 15%+ LOWER, ADP {a}-{b}", (rel <= -0.15) & (adp > a - 1) & (adp <= b)) for a, b in ((1, 30), (31, 60), (61, 100), (101, 150))] + [(f"shadow 15%+ HIGHER, ADP {a}-{b}", (rel >= 0.15) & (adp > a - 1) & (adp <= b)) for a, b in ((1, 30), (31, 60), (61, 100), (101, 150))]:
        m = m & base
        if m.sum() < 80: continue
        d = 100 * (wm(SHADOW, m) / wm(TODAY, m) - 1); wins = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and wm(SHADOW, m & (year == y)) < wm(TODAY, m & (year == y)) - 1e-12)
        gap = SHADOW[m] - TODAY[m]; closed = float(np.sum((act[m] - TODAY[m]) * np.sign(gap)) / np.sum(np.abs(gap)))
        P(f"    {lab:40s} {int(m.sum()):5d} {diff[m].mean():+11.2f} {act[m].sum()/TODAY[m].sum():8.3f} {act[m].sum()/SHADOW[m].sum():8.3f} | {d:+7.2f}% ({wins}/7) | {100*closed:+.0f}% (100 = actual landed on the shadow, 0 = on live)")
    P("\n=== 14  NAMED: biggest repeat disagreements, player-seasons where the shadow ran 15%+ lower in 4+ weeks (2023-25) ===")
    agg = defaultdict(lambda: [0, 0.0, 0.0, 0.0])
    for i in np.where(base & (rel <= -0.15) & (year >= 2023))[0]:
        a = agg[(name[i], pos[i], int(year[i]))]; a[0] += 1; a[1] += act[i]; a[2] += TODAY[i]; a[3] += SHADOW[i]
    rows = [(k, v) for k, v in agg.items() if v[0] >= 4]; rows.sort(key=lambda kv: -(kv[1][2] - kv[1][3]))
    for (nm, ps, Y), v in rows[:14]: P(f"    {Y} {nm:22s} {ps}  {v[0]} wks | actual {v[1]/v[0]:5.1f}  live {v[2]/v[0]:5.1f}  shadow {v[3]/v[0]:5.1f}  -> {'shadow right' if abs(v[1]-v[3]) < abs(v[1]-v[2]) else 'Clay right'}")
    P("\n    ...and where the shadow ran 15%+ HIGHER in 4+ weeks:")
    agg2 = defaultdict(lambda: [0, 0.0, 0.0, 0.0])
    for i in np.where(base & (rel >= 0.15) & (year >= 2023))[0]:
        a = agg2[(name[i], pos[i], int(year[i]))]; a[0] += 1; a[1] += act[i]; a[2] += TODAY[i]; a[3] += SHADOW[i]
    rows = [(k, v) for k, v in agg2.items() if v[0] >= 4]; rows.sort(key=lambda kv: -(kv[1][3] - kv[1][2]))
    for (nm, ps, Y), v in rows[:14]: P(f"    {Y} {nm:22s} {ps}  {v[0]} wks | actual {v[1]/v[0]:5.1f}  live {v[2]/v[0]:5.1f}  shadow {v[3]/v[0]:5.1f}  -> {'shadow right' if abs(v[1]-v[3]) < abs(v[1]-v[2]) else 'Clay right'}")
    LOG.close()


if __name__ == "__main__":
    main()
