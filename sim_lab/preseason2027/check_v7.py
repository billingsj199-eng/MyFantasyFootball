#!/usr/bin/env python3
"""v7 vs v5 checks: averages and ranks identical for every row; only RB p10/p90 differ. Log: output/check_v7.log."""
import os
import numpy as np, pandas as pd
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def main():
    log = open(os.path.join(OUT, "check_v7.log"), "w", encoding="utf-8")
    def P(s=""):
        print(s); log.write(s + "\n")
    for base in ("2026_inhouse_check", "2027_inhouse_early"):
        a = pd.read_csv(os.path.join(OUT, f"{base}_v5.csv")); b = pd.read_csv(os.path.join(OUT, f"{base}.csv"))
        m = a.merge(b, on=["name", "pos", "team"], suffixes=("_5", "_7"), how="outer", indicator=True)
        P(f"\n=== {base}: rows v5 {len(a)}, v7 {len(b)}, matched {int((m._merge == 'both').sum())}")
        both = m[m._merge == "both"]
        cols = [c[:-2] for c in both.columns if c.endswith("_5") and c[:-2] + "_7" in both.columns]
        for grp, mk in (("RB", both.pos == "RB"), ("non-RB", both.pos != "RB")):
            diff = {}
            for c in cols:
                x, y = both[c + "_5"][mk], both[c + "_7"][mk]
                if x.dtype == object or y.dtype == object: d = (x.fillna("") != y.fillna(""))
                else: d = ~(np.isclose(x.astype(float), y.astype(float), atol=1e-6, equal_nan=True))
                if d.sum(): diff[c] = int(d.sum())
            P(f"  {grp} rows {int(mk.sum())}: columns that differ -> {diff if diff else 'none'}")
        ex = both[both.pos == "RB"].copy()
        P("  RB range examples (season total p10-p90, v5 -> v7):")
        P("| back | tier | total | p10 v5 -> v7 | p90 v5 -> v7 |")
        P("|---|---|---|---|---|")
        for t in ("lead back", "committee", "backup", "rookie"):
            for r in ex[ex.rb_tier == t].sort_values("rank_7").head(2).itertuples(index=False):
                P(f"| {r.name} | {t} | {r.total_7:.0f} | {r.tot_p10_5:.0f} -> {r.tot_p10_7:.0f} | {r.tot_p90_5:.0f} -> {r.tot_p90_7:.0f} |")
    log.close()


if __name__ == "__main__":
    main()
