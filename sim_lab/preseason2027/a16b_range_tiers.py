#!/usr/bin/env python3
"""
A16b (research only, 2026-11-24) - follow-up tables on the A16 rows (data/a16_backtest_rows.parquet, classes 2021-24):
flat-average baseline on the same rows, and p10-p90 coverage for the rookies that matter (each class's top 12 by the
pre-draft projection, and drafted players) under wider range rules. Reads only; writes a16b_range_tiers.log.
"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
LOG = open(os.path.join(HERE, "a16b_range_tiers.log"), "w", encoding="utf-8")
def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n")
B = pd.read_parquet(os.path.join(HERE, "data", "a16_backtest_rows.parquet"))
A15 = pd.read_parquet(os.path.join(HERE, "data", "a15_backtest_rows.parquet"))   # carries the A15 flat columns c_ppg / c_tot (earlier classes only)
flat = A15.set_index(["yr", "name"])[["c_ppg", "c_tot"]]
POS4 = ("QB", "RB", "WR", "TE")
real = B[B.scenario == "real"]; e = B[B.scenario == "nov_live_nocomb"]; b = B[B.scenario == "nov_live"]
P("=== A16b: flat baseline + range coverage by tier (classes 2021-2024, real November boards) ===")
P("\n## 1. Is the pre-draft placement still better than a flat position average? (same rows)")
P("| pos | n (4+ g) | per-game MAE: real pick | Nov + no combine | flat average | n | totals MAE: real pick | Nov + no combine | flat average |"); P("|---|---|---|---|---|---|---|---|---|")
for p in POS4:
    o = []
    for X in (real, e):
        x = X[X.pos == p].join(flat, on=["yr", "name"])
        m = (x.games >= 4) & x.b_ppg.notna() & x.a_ppg.notna()
        o.append((int(m.sum()), np.sum(x.games[m] * np.abs(x.a_ppg - x.act_ppg)[m]) / x.games[m].sum(), np.sum(x.games[m] * np.abs(x.c_ppg - x.act_ppg)[m]) / x.games[m].sum(),
                  len(x), np.mean(np.abs(x.a_tot - x.total)), np.mean(np.abs(x.c_tot - x.total))))
    P(f"| {p} | {o[0][0]} | {o[0][1]:.2f} | {o[1][1]:.2f} | {o[1][2]:.2f} | {o[0][3]} | {o[0][4]:.1f} | {o[1][4]:.1f} | {o[1][5]:.1f} |")
RULES = (("K2 40, p10-p90 (live)", "lo", "hi"), ("K2 80, p10-p90", "lo_k80", "hi_k80"), ("K2 120, p10-p90", "lo_k120", "hi_k120"), ("K2 60, p7.5-p92.5", "lo_k60q", "hi_k60q"),
         ("K2 40, p10-p95 (top only)", "lo", "hi_q0595"), ("K2 40, p5-p95", "lo_q0595", "hi_q0595"), ("K2 80, p5-p95", "lo_k80q", "hi_k80q"))
def cov(x, lo, hi): return ((x.total >= x[lo]) & (x.total <= x[hi])).mean() * 100, (x.total < x[lo]).mean() * 100, (x.total > x[hi]).mean() * 100, np.median(x[hi] - x[lo])
for title, sel in (("each class's top 12 at the position by the PRE-DRAFT projection (the rookies that show on the board)", lambda x: x[x.groupby(["yr"]).a_tot.rank(ascending=False, method="first") <= 12]),
                   ("drafted players only", lambda x: x[x["round"] <= 7]), ("every scored prospect", lambda x: x)):
    P(f"\n## coverage of season totals, {title}: coverage % (below / above), median width; target 80")
    P("| pos | n | rule | real pick (upper bound) | Nov + no combine (pre-draft) | width pre-draft |"); P("|---|---|---|---|---|---|")
    for p in POS4:
        xr = sel(real[real.pos == p]); xe = sel(e[e.pos == p])
        for nm, lo, hi in RULES:
            a = cov(xr, lo, hi); c = cov(xe, lo, hi)
            P(f"| {p} | {len(xe)} | {nm} | {a[0]:.0f} ({a[1]:.0f} / {a[2]:.0f}) | {c[0]:.0f} ({c[1]:.0f} / {c[2]:.0f}) | {c[3]:.0f} |")
P("\n## pooled over the four positions (pre-draft, Nov + no combine)")
P("| group | n | " + " | ".join(r[0] for r in RULES) + " |"); P("|---|---|" + "---|" * len(RULES))
for title, sel in (("top 12 per class and position", lambda x: x[x.groupby(["yr", "pos"]).a_tot.rank(ascending=False, method="first") <= 12]), ("drafted", lambda x: x[x["round"] <= 7]), ("all", lambda x: x)):
    x = sel(e)
    P(f"| {title} | {len(x)} | " + " | ".join(f"{cov(x, lo, hi)[0]:.0f} ({cov(x, lo, hi)[1]:.0f} / {cov(x, lo, hi)[2]:.0f})" for _, lo, hi in RULES) + " |")
x = sel = None
P("\n## who lands above the pre-draft p90 (top 12 by projection, live rule): actual round of those players")
t = e[e.groupby(["yr", "pos"]).a_tot.rank(ascending=False, method="first") <= 12]
ab = t[t.total > t.hi]
P(f"  {len(ab)} of {len(t)}: " + "; ".join(f"{r.yr} {r['name']} ({r.pos}, rd {int(r['round']) if r['round'] <= 7 else 'UDFA'}, JM pre {r.jm_q:.0f} vs real {r.jm_real:.0f}): {r.total:.0f} vs p90 {r.hi:.0f}" for _, r in ab.sort_values('total', ascending=False).head(14).iterrows()))
