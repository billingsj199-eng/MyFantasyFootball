"""jm_robust_lab.py - can anything beat draft capital out-of-year? (robust, low-dof test)

A free re-weighting of ~30 components on ~100-200 players per position overfits
(scripts/jm_weight_search.py: great in-sample, no better leave-one-year-out). This
tests the conservative design instead:

    grade = a * DC score + (1 - a) * INDEX

where INDEX is the plain average (unit weights, no fitting) of the inputs that show
information BEYOND the draft pick, and both the input selection and `a` are chosen on
the training years only. Everything reported is leave-one-draft-year-out.

Views: all drafted players, the top-100-pick subset (where the pick itself says less),
and "top 5 per class by grade" hit rates versus top 5 by pick.

    python scripts/jm_robust_lab.py --table scripts/jm_table.json [--recruit file.json ...]
"""
import argparse
import json
import re
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "scripts")
from jm_model_lab import load, spearman, partial_spearman  # noqa: E402

POS = ["QB", "RB", "WR", "TE"]
EXCLUDE = {"c_dc", "c_dcAgeComposite"}          # DC-derived: they are the anchor, not "beyond DC"
RAW_HI = ["fptsPerGame", "tdPg", "gp", "totFpts", "schoolDraftCount", "bestPpg", "recPg", "speedScore", "bmi", "recruit", "totalLandingAdj", "vert", "broad"]
RAW_LO = ["forty", "breakoutAge", "age"]


def nz(s):
    return re.sub(r"[^a-z]", "", re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", (s or "").lower()))


def add_raw(df, recruit_files):
    raw = open("data/combine_data.js", encoding="utf-8").read()
    cb = json.loads(raw.split("=", 1)[1].strip().rstrip(";"))
    for col in ("forty", "vert", "broad"):
        df[col] = [pd.to_numeric((cb.get(n) or {}).get(col), errors="coerce") for n in df.name]

    def inches(h):
        m = re.match(r"(\d)-(\d{1,2})", str(h or ""))
        return int(m.group(1)) * 12 + int(m.group(2)) if m else np.nan
    df["htIn"] = [inches(h) for h in df.ht]
    df["wt"] = pd.to_numeric(df.wt, errors="coerce")
    df["speedScore"] = df.wt * 200 / (df.forty ** 4)
    df["bmi"] = df.wt / (df.htIn ** 2) * 703
    df["recruit"] = np.nan
    rec = {}
    for f in recruit_files or []:
        for r in json.load(open(f)):
            rt = r.get("rating") or {}
            v = rt.get("consensusRating") or rt.get("rating")
            if v:
                rec[(nz(r["n"]), r["yr"])] = float(v)
    if rec:
        df["recruit"] = [rec.get((nz(n), y), np.nan) for n, y in zip(df.name, df.o_yr)]
    for c in RAW_HI + RAW_LO:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def z(tr, te, col, sign):
    mu, sd = tr[col].mean(), tr[col].std()
    if not np.isfinite(sd) or sd == 0:
        return None, None
    return sign * (tr[col] - mu) / sd, sign * (te[col] - mu) / sd


def run(d, feats, thr, grid=(0.3, 0.45, 0.6, 0.75, 0.9), fixed=None, verbose=False):
    oos = pd.Series(np.nan, index=d.index)
    picks = []
    for yr in sorted(d.o_yr.unique()):
        tr, te = d[d.o_yr != yr], d[d.o_yr == yr]
        sel = []
        for f, sign in feats:
            if tr[f].notna().mean() < 0.5:
                continue
            pr, n = partial_spearman(sign * tr[f], tr.o_cs, -tr.pickn)
            if fixed is not None:
                if f in fixed:
                    sel.append((f, sign))
            elif np.isfinite(pr) and pr >= thr:
                sel.append((f, sign))
        picks.append([f for f, _ in sel])
        dc_tr, dc_te = z(tr, te, "c_dc", 1)
        if not sel:
            oos.loc[te.index] = dc_te
            continue
        Ztr = pd.concat([z(tr, te, f, s)[0] for f, s in sel], axis=1)
        Zte = pd.concat([z(tr, te, f, s)[1] for f, s in sel], axis=1)
        itr, ite = Ztr.mean(axis=1, skipna=True), Zte.mean(axis=1, skipna=True)
        sd = itr.std() or 1.0
        itr, ite = (itr / sd).fillna(0), (ite / sd).fillna(0)
        best, ba = -9, grid[0]
        for a_ in grid:
            s = spearman(a_ * dc_tr + (1 - a_) * itr, tr.o_cs)
            if s > best:
                best, ba = s, a_
        oos.loc[te.index] = ba * dc_te + (1 - ba) * ite
        picks[-1] = (ba, picks[-1])
    return oos, picks


def views(d, col):
    top = d[d.pickn <= 100]
    out = {"all": spearman(d[col], d.o_cs), "top100": spearman(top[col], top.o_cs)}
    # top-5 per class by this grade: how many hits / average outcome
    hits = cs = n = 0
    for yr, g in d.groupby("o_yr"):
        g5 = g.sort_values(col, ascending=False).head(5)
        hits += g5.hit.sum(); cs += g5.o_cs.sum(); n += len(g5)
    out["top5hit"] = hits / n if n else np.nan
    out["top5cs"] = cs / n if n else np.nan
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="scripts/jm_table.json")
    ap.add_argument("--recruit", nargs="*")
    ap.add_argument("--thr", type=float, default=0.12)
    a = ap.parse_args()
    df, t = load(a.table)
    df = add_raw(df, a.recruit)
    comps = [c for c in df.columns if c.startswith("c_") and c not in EXCLUDE]
    for pos in POS:
        d = df[df.pos == pos].copy()
        d["negpick"] = -d.pickn
        feats = [(c, 1) for c in comps if d[c].notna().sum() >= 25] + [(c, 1) for c in RAW_HI if c in d and d[c].notna().sum() >= 25] + [(c, -1) for c in RAW_LO if c in d and d[c].notna().sum() >= 25]
        print("\n=== %s  n=%d  (top-100 picks: %d) ===" % (pos, len(d), (d.pickn <= 100).sum()))
        # full-sample partials for the candidate (new) raw inputs
        news = []
        for c, s in feats:
            if c.startswith("c_"):
                continue
            pr, n = partial_spearman(s * d[c], d.o_cs, -d.pickn)
            if np.isfinite(pr):
                news.append("%s %+.2f(n%d)" % (c, pr, n))
        print("  raw inputs beyond pick: " + ", ".join(news))
        d["oos"], picks = run(d, feats, a.thr)
        d["dcz"] = d.c_dc
        hdr = "  %-34s %8s %8s %9s %9s" % ("", "all", "top100", "top5 hit", "top5 cs")
        print(hdr)
        for label, col in (("draft pick", "negpick"), ("DC score", "dcz"), ("site JM (live)", "jm"), ("robust: DC + unit-weight index", "oos")):
            v = views(d, col)
            print("  %-34s %8.3f %8.3f %9.2f %9.1f" % (label, v["all"], v["top100"], v["top5hit"], v["top5cs"]))
        from collections import Counter
        cnt = Counter(f for p in picks if isinstance(p, tuple) for f in p[1])
        alphas = [p[0] for p in picks if isinstance(p, tuple)]
        print("  DC share chosen per fold: %s" % alphas)
        print("  inputs selected (folds of %d): %s" % (len(picks), ", ".join("%s %d" % kv for kv in cnt.most_common(18))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
