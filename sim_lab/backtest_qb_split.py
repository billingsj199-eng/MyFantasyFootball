#!/usr/bin/env python3
"""
QB rush/pass decomposition (2019-2025).

QB is the worst-projected position (MAE ~3.0 vs WR 2.0 / TE 1.4) and rushing
is 16% of the average QB's points, 22%+ for the top quartile, up to 43%.
Rushing volume should be far more persistent than passing TDs.

NOTE a naive "split then re-add" is a mathematical no-op: with the SAME
recency weights on both components, sum(weighted) == weighted(sum). The value
can only come from treating the components DIFFERENTLY, so this tests:

  persistence   YoY correlation of each component's per-game rate
  split-k       shrink each component toward its own positional mean with its
                own k (the shipped model shrinks TOTAL PPG with one k=0.80)
  split-w       give each component its own recency weighting (rushing may
                want a longer memory than passing)

All graded on actual season-Y total QB PPG, LOYO by season.
"""
import numpy as np
import pandas as pd
from collections import defaultdict
from backtest_sim_calibration import played, WEEKLY
import backtest_sim_calibration as cal

YEARS = range(2019, 2026)
W3 = [0.5, 0.3, 0.2]
W_LONG = [0.4, 0.33, 0.27]     # flatter = longer memory
W_SHORT = [0.6, 0.27, 0.13]    # steeper = recent-heavy
# half-PPR QB scoring
def pass_pts(w):
    return (w.get("py") or 0) * 0.04 + (w.get("ptd") or 0) * 4 - (w.get("int") or 0)
def rush_pts(w):
    return (w.get("ry") or 0) * 0.1 + (w.get("rtd") or 0) * 6

def main():
    per = {}   # (nk, Y) -> dict
    for nk, lst in WEEKLY.items():
        for rec in lst:
            if rec.get("pos") != "QB":
                continue
            for Ys in rec.get("seasons", {}):
                Y = int(Ys)
                rws = [w for w in rec["seasons"][Ys] if played(w)]
                if len(rws) < 4:
                    continue
                g = len(rws)
                pp = sum(pass_pts(w) for w in rws) / g
                rp = sum(rush_pts(w) for w in rws) / g
                tot = [w["fpts"] for w in rws if isinstance(w.get("fpts"), (int, float))]
                per[(nk, Y)] = {"g": g, "pass": pp, "rush": rp,
                                "tot": (sum(tot) / len(tot)) if tot else pp + rp}
    def core(nk, Y, key, wts):
        num = den = 0.0
        for i, yy in enumerate((Y - 1, Y - 2, Y - 3)):
            d = per.get((nk, yy))
            if d and d["g"] >= 4:
                num += wts[i] * d[key]; den += wts[i]
        return (num / den) if den else None

    rows = []
    for (nk, Y) in list(per):
        if Y not in YEARS:
            continue
        cur = per[(nk, Y)]
        if cur["g"] < 6 or cur["tot"] < 3:
            continue
        c_tot = core(nk, Y, "tot", W3)
        c_p = core(nk, Y, "pass", W3)
        c_r = core(nk, Y, "rush", W3)
        if c_tot is None or c_p is None or c_r is None:
            continue
        rows.append({"nk": nk, "Y": Y, "act": cur["tot"],
                     "act_pass": cur["pass"], "act_rush": cur["rush"],
                     "c_tot": c_tot, "c_pass": c_p, "c_rush": c_r,
                     "c_pass_long": core(nk, Y, "pass", W_LONG),
                     "c_rush_long": core(nk, Y, "rush", W_LONG),
                     "c_pass_short": core(nk, Y, "pass", W_SHORT),
                     "c_rush_short": core(nk, Y, "rush", W_SHORT)})
    df = pd.DataFrame(rows)
    print(f"{len(df)} QB seasons\n")

    print("=== Persistence: how well does each component predict itself? ===")
    for key, lab in (("pass", "passing pts/g"), ("rush", "rushing pts/g"), ("tot", "total pts/g")):
        prev = [per[(r.nk, r.Y - 1)][key] for r in df.itertuples() if (r.nk, r.Y - 1) in per]
        curr = [per[(r.nk, r.Y)][key] for r in df.itertuples() if (r.nk, r.Y - 1) in per]
        c = np.corrcoef(prev, curr)[0, 1]
        print(f"  {lab:<16} YoY corr {c:+.3f}   (n={len(prev)})")

    print("\n=== Component-specific shrinkage vs one k on the total ===")
    KS = [1.00, 0.90, 0.80, 0.70, 0.60, 0.50]
    def loyo(predfn):
        errs = []
        for Y in YEARS:
            tr, te = df[df.Y != Y], df[df.Y == Y]
            if len(tr) < 40 or not len(te):
                continue
            mp, mr = tr.c_pass.mean(), tr.c_rush.mean()
            mt = tr.c_tot.mean()
            for r in te.itertuples():
                errs.append(abs(predfn(r, mp, mr, mt) - r.act))
        return float(np.mean(errs))
    base = loyo(lambda r, mp, mr, mt: r.c_tot)
    print(f"  unified core (k=1):            {base:.4f}")
    best_uni = min(((k, loyo(lambda r, mp, mr, mt, k=k: mt + k*(r.c_tot-mt))) for k in KS), key=lambda x: x[1])
    print(f"  unified shrink  best k={best_uni[0]:.2f}:  {best_uni[1]:.4f}  ({(best_uni[1]-base)/base*100:+.2f}%)")
    grid = []
    for kp in KS:
        for kr in KS:
            v = loyo(lambda r, mp, mr, mt, kp=kp, kr=kr:
                     (mp + kp*(r.c_pass-mp)) + (mr + kr*(r.c_rush-mr)))
            grid.append((kp, kr, v))
    grid.sort(key=lambda x: x[2])
    print(f"  SPLIT shrink    best kPass={grid[0][0]:.2f} kRush={grid[0][1]:.2f}: {grid[0][2]:.4f}"
          f"  ({(grid[0][2]-base)/base*100:+.2f}% vs core, {(grid[0][2]-best_uni[1])/best_uni[1]*100:+.2f}% vs unified shrink)")
    print("  top 5 (kPass, kRush, MAE):", [(a, b, round(c, 4)) for a, b, c in grid[:5]])

    print("\n=== Component-specific recency memory (at the best split k) ===")
    kp, kr = grid[0][0], grid[0][1]
    for lab, pk, rk in (("both 50/30/20", "c_pass", "c_rush"),
                        ("rush LONG memory", "c_pass", "c_rush_long"),
                        ("rush SHORT memory", "c_pass", "c_rush_short"),
                        ("pass LONG memory", "c_pass_long", "c_rush"),
                        ("pass SHORT memory", "c_pass_short", "c_rush")):
        errs = []
        for Y in YEARS:
            tr, te = df[df.Y != Y], df[df.Y == Y]
            if len(tr) < 40 or not len(te):
                continue
            mp, mr = tr[pk].mean(), tr[rk].mean()
            for r in te.itertuples():
                p = mp + kp*(getattr(r, pk) - mp)
                rr = mr + kr*(getattr(r, rk) - mr)
                errs.append(abs(p + rr - r.act))
        v = float(np.mean(errs))
        print(f"  {lab:<20} {v:.4f}  ({(v-grid[0][2])/grid[0][2]*100:+.2f}%)")

if __name__ == "__main__":
    main()
