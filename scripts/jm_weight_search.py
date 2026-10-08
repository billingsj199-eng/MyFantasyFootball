"""jm_weight_search.py - offline weight search in the JM functional form, LOYO-validated.

The live grade is (before the additive adjustments and the stretch) a weighted average
of 0-100 component scores, renormalised over the components a player actually has:

    S = sum_k w_k * c_k / sum_{k present} w_k

This searches w per position (non-negative, sums to 1) by coordinate ascent on the
Spearman of S with the NFL outcome score, with an L1 pull toward the live weights, and
reports the leave-one-draft-year-out result against fixed references (live floor
weights, draft capital alone). It can also add candidate components that are not in
the model yet (percentile-ranked raw inputs) to see whether they would earn weight.

    python scripts/jm_weight_search.py --table scripts/jm_table.json [--cands] [--lam 0.03]
"""
import argparse
import json
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "scripts")
from jm_model_lab import load, spearman  # noqa: E402

POS = ["QB", "RB", "WR", "TE"]
CANDS = {  # name -> (raw column, higher is better)
    "x_careerPpg": ("fptsPerGame", True), "x_tdPg": ("tdPg", True), "x_gp": ("gp", True),
    "x_totFpts": ("totFpts", True), "x_schoolDraft": ("schoolDraftCount", True),
}


def surrogate(C, M, w):
    num = np.nansum(C * w, axis=1)
    den = (M * w).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        s = num / den
    s[den <= 0] = np.nan
    return s


def rho(s, y):
    m = np.isfinite(s)
    if m.sum() < 10:
        return 0.0
    a = pd.Series(s[m]).rank().values
    b = pd.Series(y[m]).rank().values
    return float(np.corrcoef(a, b)[0, 1])


def fit(C, M, y, w0, lam, steps=(0.04, 0.02, 0.01), passes=3, frozen=()):
    w = w0.copy()
    K = len(w)

    def obj(v):
        return rho(surrogate(C, M, v), y) - lam * np.abs(v - w0).sum()
    best = obj(w)
    for st in steps:
        for _ in range(passes):
            improved = False
            for k in range(K):
                if k in frozen:
                    continue
                for d in (st, -st):
                    nv = w[k] + d
                    if nv < 0:
                        continue
                    v = w.copy()
                    v[k] = nv
                    others = [j for j in range(K) if j != k]
                    tot = v[others].sum()
                    if tot <= 0 or nv >= 1:
                        continue
                    v[others] *= (1 - nv) / tot
                    o = obj(v)
                    if o > best + 1e-4:
                        best, w, improved = o, v, True
            if not improved:
                break
    return w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="scripts/jm_table.json")
    ap.add_argument("--cands", action="store_true", help="add candidate (not yet in model) components")
    ap.add_argument("--lam", type=float, default=0.03)
    ap.add_argument("--out")
    a = ap.parse_args()
    df, t = load(a.table)
    result = {}
    for pos in POS:
        d = df[df.pos == pos].reset_index(drop=True)
        comps = [c for c in d.columns if c.startswith("c_") and d[c].notna().sum() >= 20]
        if a.cands:
            for name, (col, hi) in CANDS.items():
                if col in d.columns and pd.to_numeric(d[col], errors="coerce").notna().sum() >= 20:
                    v = pd.to_numeric(d[col], errors="coerce")
                    d[name] = (v.rank(pct=True) * 100) if hi else ((1 - v.rank(pct=True)) * 100)
                    comps.append(name)
        C = d[comps].values.astype(float)
        M = np.isfinite(C).astype(float)
        y = d.o_cs.values.astype(float)
        yrs = d.o_yr.values
        live = t["weights"]["floor"].get(pos, {})
        w_live = np.array([live.get(c[2:], 0.0) if c.startswith("c_") else 0.0 for c in comps])
        w_live = w_live / w_live.sum()
        w_dc = np.array([1.0 if c == "c_dc" else 0.0 for c in comps])

        # fixed references (no fitting)
        ref = {"live floor w": rho(surrogate(C, M, w_live), y), "DC only": rho(surrogate(C, M, w_dc), y),
               "site JM": spearman(d.jm, d.o_cs), "-pick": spearman(-d.pickn, d.o_cs)}
        for mix in (0.45, 0.6, 0.75):
            w = w_live * (1 - mix)
            w[comps.index("c_dc")] = 0
            w = w / w.sum() * (1 - mix)
            w[comps.index("c_dc")] = mix
            ref["live, DC=%d%%" % (mix * 100)] = rho(surrogate(C, M, w), y)

        # LOYO fit
        oos = np.full(len(d), np.nan)
        oos_live = surrogate(C, M, w_live)
        folds = []
        for yr in sorted(set(yrs)):
            tr = yrs != yr
            w = fit(C[tr], M[tr], y[tr], w_live, a.lam)
            oos[~tr] = surrogate(C[~tr], M[~tr], w)
            folds.append(w)
        # per-fold scores are on the same 0-100 scale, so pooling is meaningful
        wy = lambda s: np.nansum([rho(s[yrs == yr], y[yrs == yr]) * (yrs == yr).sum() for yr in set(yrs)]) / len(y)
        w_full = fit(C, M, y, w_live, a.lam)
        print("\n=== %s n=%d comps=%d ===" % (pos, len(d), len(comps)))
        print("  fixed refs (pooled): " + " | ".join("%s %.3f" % kv for kv in ref.items()))
        print("  LOYO pooled: live %.3f -> tuned %.3f   | within-year: live %.3f -> tuned %.3f   | in-sample full fit %.3f" % (
            rho(oos_live, y), rho(oos, y), wy(oos_live), wy(oos), rho(surrogate(C, M, w_full), y)))
        stab = np.array(folds)
        order = np.argsort(-w_full)
        print("  full-fit weights (live -> tuned, fold min..max):")
        for k in order:
            if w_full[k] < 0.005 and w_live[k] < 0.005:
                continue
            print("    %-18s %5.1f -> %5.1f   [%4.1f..%4.1f]" % (comps[k], w_live[k] * 100, w_full[k] * 100, stab[:, k].min() * 100, stab[:, k].max() * 100))
        result[pos] = {"comps": comps, "live": w_live.tolist(), "tuned": w_full.tolist(), "loyo_live": rho(oos_live, y), "loyo_tuned": rho(oos, y)}
    if a.out:
        json.dump(result, open(a.out, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
