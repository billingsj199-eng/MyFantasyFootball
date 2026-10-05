#!/usr/bin/env python3
"""
Follow-up to research_pff_pro_screen.py (2026-10-05): are the flagged PFF Pro metrics NEW information, or proxies
for what the projection already prices (its own level, the Vegas implied total, team pass rate)?
Partial Spearman: rank-regress the metric and the residual on the controls, correlate what is left.
Only each position's own families are kept (a WR's 'qb_' row is that WR's own passing - noise).
Log pff_pro_partial.log.
"""
import os, warnings
import numpy as np, pandas as pd
from scipy.stats import rankdata

HERE = os.path.dirname(os.path.abspath(__file__))
warnings.filterwarnings("ignore")
OWN = {"QB": ("qb_", "own_", "opp_", "ol_", "ru_"), "RB": ("ru_", "rec_", "own_", "opp_", "ol_"),
       "WR": ("rec_", "own_", "opp_", "ol_"), "TE": ("rec_", "own_", "opp_", "ol_")}


def prank(x):
    return (rankdata(x) - 0.5) / len(x)


def partial(f, y, Z):
    X = np.column_stack([np.ones(len(f))] + [prank(z) for z in Z])
    rf, ry = prank(f), prank(y)
    ef = rf - X @ np.linalg.lstsq(X, rf, rcond=None)[0]
    ey = ry - X @ np.linalg.lstsq(X, ry, rcond=None)[0]
    return float(np.corrcoef(ef, ey)[0, 1])


def main():
    lf = open(os.path.join(HERE, "pff_pro_partial.log"), "w", encoding="utf-8")

    def P(s=""):
        print(s, flush=True); lf.write(s + "\n")

    M = pd.read_parquet(os.path.join(HERE, "data", "metric_atlas_rows.parquet"))
    F = pd.read_parquet(os.path.join(HERE, "data", "pff_pro_features.parquet"))
    A = pd.read_csv(os.path.join(HERE, "data", "pff_pro_screen.csv"))
    D = M.merge(F, on=["year", "pid", "wk"], how="left")
    base = D[(D.live >= 5) & (D.g >= 2)].copy()
    ctrl_cols = ["live", "implied", "ppg"]
    P("Partial Spearman of each flagged metric vs the residual, controlling for the projection's own level (live), the Vegas implied")
    P("team total and season PPG. 'raw' = screen value; 'partial' = after the controls; halves = 2019-22 / 2023-25 partial.\n")
    for pos in ("QB", "RB", "WR", "TE"):
        x = A[(A.pos == pos) & A.metric.str.startswith(OWN[pos])].copy()
        x = x[(x.r_res.abs() >= 0.045) | (x.r_resRos.abs() >= 0.08)]
        P(f"=== {pos} ===")
        P(f"  {'metric':36s} {'res raw':>8s} {'partial':>8s} [{'19-22':>6s} {'23-25':>6s}]   {'resRos raw':>10s} {'partial':>8s} [{'19-22':>6s} {'23-25':>6s}]")
        for r in x.itertuples():
            d = base[(base.pos == pos) & base[r.metric].notna()].dropna(subset=ctrl_cols)
            pr = partial(d[r.metric].values, d.res.values, [d[c].values for c in ctrl_cols])
            e, l = d[d.year <= 2022], d[d.year >= 2023]
            pe = partial(e[r.metric].values, e.res.values, [e[c].values for c in ctrl_cols])
            pl = partial(l[r.metric].values, l.res.values, [l[c].values for c in ctrl_cols])
            d4 = d[d.resRos.notna()]
            q = partial(d4[r.metric].values, d4.resRos.values, [d4[c].values for c in ctrl_cols])
            e4, l4 = d4[d4.year <= 2022], d4[d4.year >= 2023]
            qe = partial(e4[r.metric].values, e4.resRos.values, [e4[c].values for c in ctrl_cols])
            ql = partial(l4[r.metric].values, l4.resRos.values, [l4[c].values for c in ctrl_cols])
            fw = "*" if abs(pr) >= 0.04 and np.sign(pe) == np.sign(pl) == np.sign(pr) else " "
            fr = "*" if abs(q) >= 0.06 and np.sign(qe) == np.sign(ql) == np.sign(q) else " "
            P(f"  {r.metric:36s} {r.r_res:+8.3f} {pr:+8.3f}{fw}[{pe:+6.3f} {pl:+6.3f}]   {r.r_resRos:+10.3f} {q:+8.3f}{fr}[{qe:+6.3f} {ql:+6.3f}]")
        P("")
    lf.close()


if __name__ == "__main__":
    main()
