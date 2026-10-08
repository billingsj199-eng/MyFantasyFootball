"""jm_model_lab.py - offline lab on the JM modelling table (scripts/jm_extract_table.js).

Answers, per position, with leave-one-draft-year-out (LOYO) validation:
  1. baselines   - how well do pick alone, the DC score alone and the live JM rank outcomes?
  2. increments  - which components / raw inputs add information BEYOND draft capital
                   (partial Spearman after removing DC)?
  3. headroom    - what does a regularised linear model on the same component scores reach
                   out-of-year? (the live model is a weighted average, so this is its ceiling)
  4. curves      - outcome by raw draft age / breakout age bucket (to refit the sub-scores)

    python scripts/jm_model_lab.py --table scripts/jm_table.json [--section all]
"""
import argparse
import json
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
POS = ["QB", "RB", "WR", "TE"]


def spearman(a, b):
    a, b = pd.Series(a), pd.Series(b)
    m = a.notna() & b.notna()
    if m.sum() < 8:
        return np.nan
    return float(np.corrcoef(a[m].rank(), b[m].rank())[0, 1])


def partial_spearman(x, y, z):
    """Spearman of x and y after removing rank-linear dependence on z."""
    d = pd.DataFrame({"x": x, "y": y, "z": z}).dropna()
    if len(d) < 15:
        return np.nan, len(d)
    r = d.rank()
    rx = r.x - np.polyval(np.polyfit(r.z, r.x, 1), r.z)
    ry = r.y - np.polyval(np.polyfit(r.z, r.y, 1), r.z)
    return float(np.corrcoef(rx, ry)[0, 1]), len(d)


def load(path):
    t = json.load(open(path, encoding="utf-8"))
    rows = []
    for r in t["rows"]:
        if r["o_verdict"] == "pending" or r.get("o_cs") is None:
            continue
        d = {k: v for k, v in r.items() if k not in ("comps", "o_raw")}
        for k, v in (r.get("comps") or {}).items():
            d["c_" + k] = v
        rows.append(d)
    df = pd.DataFrame(rows)
    df["pickn"] = pd.to_numeric(df["o_pick"], errors="coerce").fillna(300)
    df["hit"] = df["o_verdict"].isin(["stud", "hit"]).astype(int)
    return df, t


def ridge_loyo(d, feats, lam, target="o_cs", add_missing=True):
    """LOYO predictions from ridge on z-scored features (train stats), mean-imputed."""
    pred = pd.Series(np.nan, index=d.index)
    for yr in sorted(d.o_yr.unique()):
        tr, te = d[d.o_yr != yr], d[d.o_yr == yr]
        cols, Xtr, Xte = [], [], []
        for f in feats:
            mu, sd = tr[f].mean(), tr[f].std()
            if not np.isfinite(sd) or sd == 0 or tr[f].notna().sum() < 15:
                continue
            Xtr.append(((tr[f] - mu) / sd).fillna(0).values)
            Xte.append(((te[f] - mu) / sd).fillna(0).values)
            cols.append(f)
            if add_missing and 0.08 < tr[f].isna().mean() < 0.92:
                m_mu = tr[f].isna().mean()
                Xtr.append(tr[f].isna().values.astype(float) - m_mu)
                Xte.append(te[f].isna().values.astype(float) - m_mu)
                cols.append(f + "__missing")
        Xtr, Xte = np.array(Xtr).T, np.array(Xte).T
        y = tr[target].rank().values
        y = (y - y.mean()) / y.std()
        A = Xtr.T @ Xtr + lam * np.eye(Xtr.shape[1])
        w = np.linalg.solve(A, Xtr.T @ y)
        pred.loc[te.index] = Xte @ w
    return pred


def within_year_spearman(d, col, target="o_cs"):
    """Mean of per-year Spearman (weights = n) - the LOYO tuner's held-out view."""
    tot, n = 0.0, 0
    for yr, g in d.groupby("o_yr"):
        if len(g) < 8:
            continue
        s = spearman(g[col], g[target])
        if np.isfinite(s):
            tot += s * len(g)
            n += len(g)
    return tot / n if n else np.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="scripts/jm_table.json")
    ap.add_argument("--section", default="all")
    a = ap.parse_args()
    df, t = load(a.table)
    comp_cols = [c for c in df.columns if c.startswith("c_")]
    raw_cols = ["age", "breakoutAge", "breakoutPpg", "bestPpg", "fptsPerGame", "totFpts", "ras", "gp", "numSeasons",
                "mktShare", "domRate", "improvSlope", "pffGrade", "pffRush", "ypc", "ypr", "recPg", "tdPg",
                "qbRushFppg", "qbCompPct", "qbIntRate", "teRecPg", "schoolDraftCount", "tmCompShare", "wt",
                "bustAdj", "sleeperAdj", "dataCoverage"]
    raw_cols = [c for c in raw_cols if c in df.columns]
    for c in raw_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    print("rows %d (non-pending) | hit rate %.2f" % (len(df), df.hit.mean()))
    for pos in POS:
        d = df[df.pos == pos].copy()
        if a.section in ("all", "base"):
            print("\n=== %s  n=%d  hits %d ===" % (pos, len(d), d.hit.sum()))
            print("  pooled Spearman vs outcome:  -pick %.3f | DC score %.3f | floor %.3f | ceiling %.3f | JM %.3f" % (
                spearman(-d.pickn, d.o_cs), spearman(d.c_dc, d.o_cs), spearman(d.jmFloor, d.o_cs), spearman(d.jmCeil, d.o_cs), spearman(d.jm, d.o_cs)))
            print("  within-year (n-weighted):    -pick %.3f | JM %.3f" % (within_year_spearman(d.assign(np_=-d.pickn), "np_"), within_year_spearman(d, "jm")))
        if a.section in ("all", "incr"):
            out = []
            for c in comp_cols + raw_cols:
                r0 = spearman(d[c], d.o_cs)
                pr, n = partial_spearman(d[c], d.o_cs, -d.pickn)
                if np.isfinite(pr):
                    out.append((c, n, r0, pr))
            out.sort(key=lambda x: -abs(x[3]))
            w = (t["weights"]["floor"].get(pos) or {})
            print("  beyond draft pick (partial Spearman | raw | n | live floor w):")
            for c, n, r0, pr in out[:22]:
                k = c[2:] if c.startswith("c_") else None
                print("    %-20s %+.3f  %+.3f  n=%-3d %s" % (c, pr, r0, n, ("w=%.3f" % w.get(k, 0)) if k else "(raw)"))
        if a.section in ("all", "head"):
            feats = comp_cols
            base = spearman(d.jm, d.o_cs)
            line = "  LOYO ridge on component scores:"
            for lam in (3, 10, 30, 100, 300):
                p = ridge_loyo(d, feats, lam)
                line += "  lam%-3d %.3f" % (lam, spearman(p, d.o_cs))
            print(line + "   | live JM %.3f" % base)
            p2 = ridge_loyo(d, feats + raw_cols, 100)
            print("  LOYO ridge comps+raw lam100: %.3f" % spearman(p2, d.o_cs))
            p3 = ridge_loyo(d, ["c_dc"], 1, add_missing=False)
            print("  LOYO DC score alone: %.3f" % spearman(p3, d.o_cs))
        if a.section in ("all", "curve"):
            for col, bins in (("age", [0, 20.5, 21.0, 21.5, 22.0, 22.5, 23.0, 23.5, 30]), ("breakoutAge", [0, 18.5, 19.5, 20.5, 21.5, 22.5, 30])):
                g = d.dropna(subset=[col]).copy()
                g["b"] = pd.cut(g[col], bins)
                # residual of outcome rank after pick
                r = g[["o_cs", "pickn"]].rank()
                g["res"] = r.o_cs - np.polyval(np.polyfit(-r.pickn, r.o_cs, 1), -r.pickn)
                s = g.groupby("b", observed=True).agg(n=("hit", "size"), hit=("hit", "mean"), cs=("o_cs", "mean"), res=("res", "mean"), pick=("pickn", "median"))
                print("  %s buckets (n, hit rate, mean outcome, outcome-rank residual after pick, median pick):" % col)
                for b, x in s.iterrows():
                    print("    %-14s n=%-3d hit %.2f  cs %5.1f  resid %+6.1f  pick %3.0f" % (str(b), x.n, x.hit, x.cs, x.res, x.pick))
    return 0


if __name__ == "__main__":
    sys.exit(main())
