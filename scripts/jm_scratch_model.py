"""jm_scratch_model.py - build the prospect model FROM SCRATCH and compare it with the site model.

Forgets every existing weight, curve and adjustment. Uses only raw pre-draft inputs
(draft pick, college production, age, testing, PFF charting, alignment, teammates) from
scripts/jm_study_table.json and the graded career outcome (0-100) as the target.

Every number reported is leave-one-draft-year-out: the 2021 class is predicted by a model
that saw 2017-2020 and 2022-2024 only, and so on. The site grades (v9 and live) are
shown beside them; note those were tuned on all years, which flatters them.

Models
  pick      monotone curve of the draft pick alone (isotonic, per position)
  ridge     linear model on z-scored raw inputs + missing flags, penalty chosen by inner CV
  resid     pick curve + ridge fitted to what the pick leaves unexplained
  index     pick share + UNWEIGHTED average of inputs that beat the pick on training years
  gbm       gradient-boosted depth-2 trees (non-linear, interactions), per position
  pooled    one gbm for all positions on within-position z-scores + position flags
  blend     average of the rank-normalised resid, index and pooled predictions

    python scripts/jm_scratch_model.py --table scripts/jm_study_table.json [--out file.json]
"""
import argparse
import json
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
POS = ["QB", "RB", "WR", "TE"]
RAW = ["age", "breakoutAge", "breakoutPpg", "bestPpg", "fptsPerGame", "totFpts", "gp", "numSeasons", "tdPg", "recPg", "ypc", "ypr",
       "mktShare", "domRate", "improvSlope", "pffGrade", "pffRush", "ras", "htIn", "wt", "bmi", "t_forty", "t_vert", "t_broad", "t_bench",
       "t_cone", "t_shuttle", "speedScore", "schoolDraftCount", "tm", "tmCompShare", "confScore", "k_adot", "k_slotRate", "k_wideRate",
       "k_inlineRate", "k_yprr", "k_contestedRate", "k_dropRate", "k_yacPerRec", "qbRushFppg", "qbCompPct", "qbIntRate", "teRecPg",
       "pasYpg", "rushYpg", "recYpg", "totalTd"]


def load(path):
    d = pd.DataFrame(json.load(open(path, encoding="utf-8"))["rows"])
    d = d[d.career.notna()].reset_index(drop=True)
    d["pickn"] = pd.to_numeric(d.o_pick, errors="coerce").fillna(280).clip(1, 280)
    d["lpick"] = np.log(d.pickn)

    def inches(h):
        m = pd.Series(h).astype(str).str.extract(r"(\d)-(\d{1,2})")
        return pd.to_numeric(m[0], errors="coerce") * 12 + pd.to_numeric(m[1], errors="coerce")
    d["htIn"] = inches(d.ht)
    for c in ["wt", "tm", "tmCompShare"] + [c for c in RAW if c in d.columns]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["bmi"] = d.wt / d.htIn ** 2 * 703
    d["speedScore"] = d.wt * 200 / d.t_forty ** 4
    d["confScore"] = pd.to_numeric(d.get("c_conf"), errors="coerce")
    d["w"] = d.elapsed.map({4: 1.0, 3: 0.85, 2: 0.7}).fillna(0.6)
    return d


def spearman(a, b):
    a, b = pd.Series(np.asarray(a, float)), pd.Series(np.asarray(b, float))
    m = a.notna() & b.notna()
    return float(np.corrcoef(a[m].rank(), b[m].rank())[0, 1]) if m.sum() > 7 else np.nan


def pava(y, w):
    y, w = list(map(float, y)), list(map(float, w))
    blocks = [[v, ww, 1] for v, ww in zip(y, w)]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] < blocks[i + 1][0] - 1e-12:     # want non-increasing in pick
            a, b = blocks[i], blocks[i + 1]
            tot = a[1] + b[1]
            blocks[i] = [(a[0] * a[1] + b[0] * b[1]) / tot, tot, a[2] + b[2]]
            del blocks[i + 1]
            i = max(i - 1, 0)
        else:
            i += 1
    out = []
    for v, _, n in blocks:
        out += [v] * n
    return np.array(out)


def pick_curve(tr, te):
    o = tr.sort_values("pickn")
    sm = o.career.rolling(max(7, len(o) // 10), center=True, min_periods=3).mean()
    fit = pava(sm.fillna(o.career).values, o.w.values)
    return np.interp(te.pickn.values, o.pickn.values, fit), np.interp(tr.pickn.values, o.pickn.values, fit)


def design(tr, te, feats, flags=True):
    Xa, Xb, names = [], [], []
    for f in feats:
        if f not in tr or tr[f].notna().sum() < max(12, 0.25 * len(tr)):
            continue
        mu, sd = tr[f].mean(), tr[f].std()
        if not np.isfinite(sd) or sd == 0:
            continue
        Xa.append(((tr[f] - mu) / sd).clip(-3, 3).fillna(0).values); Xb.append(((te[f] - mu) / sd).clip(-3, 3).fillna(0).values); names.append(f)
        miss = tr[f].isna().mean()
        if flags and 0.1 < miss < 0.9:
            Xa.append(tr[f].isna().values - miss); Xb.append(te[f].isna().values - miss); names.append(f + "?")
    return np.array(Xa).T, np.array(Xb).T, names


def ridge_fit(X, y, w, lam):
    W = w[:, None]
    A = X.T @ (X * W) + lam * np.eye(X.shape[1])
    return np.linalg.solve(A, X.T @ (y * w))


def ridge_cv(tr, feats, ycol, lams=(3, 10, 30, 100, 300)):
    best = (-9, lams[-1])
    for lam in lams:
        pred = pd.Series(np.nan, index=tr.index)
        for yr in tr.o_yr.unique():
            a, b = tr[tr.o_yr != yr], tr[tr.o_yr == yr]
            Xa, Xb, _ = design(a, b, feats)
            if Xa.size == 0:
                continue
            mu = np.average(a[ycol], weights=a.w)
            pred.loc[b.index] = Xb @ ridge_fit(Xa, (a[ycol] - mu).values, a.w.values, lam) + mu
        s = spearman(pred, tr[ycol])
        if s > best[0]:
            best = (s, lam)
    return best[1]


class GBM:
    def __init__(self, n=140, lr=0.05, depth=2, sub=0.8, min_leaf=8, seed=7):
        self.n, self.lr, self.depth, self.sub, self.min_leaf, self.rng = n, lr, depth, sub, min_leaf, np.random.default_rng(seed)

    def _split(self, X, r, w, idx):
        best = (0.0, None)
        tot_w, tot_r = w[idx].sum(), (r[idx] * w[idx]).sum()
        base = tot_r ** 2 / tot_w if tot_w else 0
        for j in range(X.shape[1]):
            x = X[idx, j]
            for t in self.cuts[j]:
                L = x <= t
                nl = L.sum()
                if nl < self.min_leaf or len(idx) - nl < self.min_leaf:
                    continue
                wl, rl = w[idx][L].sum(), (r[idx][L] * w[idx][L]).sum()
                gain = rl ** 2 / wl + (tot_r - rl) ** 2 / (tot_w - wl) - base
                if gain > best[0]:
                    best = (gain, (j, t))
        return best[1]

    def _tree(self, X, r, w, idx, depth):
        sp = self._split(X, r, w, idx) if depth > 0 and len(idx) >= 2 * self.min_leaf else None
        if sp is None:
            return float((r[idx] * w[idx]).sum() / w[idx].sum())
        j, t = sp
        L = X[idx, j] <= t
        return (j, t, self._tree(X, r, w, idx[L], depth - 1), self._tree(X, r, w, idx[~L], depth - 1))

    def _pred(self, node, X):
        if not isinstance(node, tuple):
            return np.full(len(X), node)
        j, t, a, b = node
        out = np.empty(len(X)); L = X[:, j] <= t
        out[L] = self._pred(a, X[L]); out[~L] = self._pred(b, X[~L])
        return out

    def fit(self, X, y, w):
        self.cuts = [np.unique(np.quantile(X[:, j], np.linspace(0.08, 0.92, 12))) for j in range(X.shape[1])]
        self.f0 = float(np.average(y, weights=w)); f = np.full(len(y), self.f0); self.trees = []
        for _ in range(self.n):
            idx = np.sort(self.rng.choice(len(y), int(self.sub * len(y)), replace=False))
            tree = self._tree(X, y - f, w, idx, self.depth)
            f += self.lr * self._pred(tree, X); self.trees.append(tree)
        return self

    def predict(self, X):
        f = np.full(len(X), self.f0)
        for t in self.trees:
            f += self.lr * self._pred(t, X)
        return f

    def importance(self, n_feat):
        imp = np.zeros(n_feat)

        def walk(node):
            if isinstance(node, tuple):
                imp[node[0]] += 1; walk(node[2]); walk(node[3])
        for t in self.trees:
            walk(t)
        return imp / max(imp.sum(), 1)


def partial(x, y, z):
    d = pd.DataFrame({"x": x, "y": y, "z": z}).dropna()
    if len(d) < 15:
        return np.nan
    r = d.rank()
    rx = r.x - np.polyval(np.polyfit(r.z, r.x, 1), r.z); ry = r.y - np.polyval(np.polyfit(r.z, r.y, 1), r.z)
    return float(np.corrcoef(rx, ry)[0, 1])


def rankz(v):
    r = pd.Series(v).rank(pct=True)
    return (r - 0.5).values


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="scripts/jm_study_table.json")
    ap.add_argument("--site", help="json with {name|yr: {v9, live}} site grades for the comparison")
    ap.add_argument("--out")
    ap.add_argument("--fast", action="store_true")
    a = ap.parse_args()
    d = load(a.table)
    feats = [f for f in RAW if f in d.columns]
    years = sorted(d.o_yr.unique())
    P = {m: pd.Series(np.nan, index=d.index) for m in ("pick", "ridge", "resid", "index", "gbm", "pooled")}
    chosen = {p: {} for p in POS}
    gimp = {p: np.zeros(len(feats) + 1) for p in POS}
    for yr in years:
        for pos in POS:
            tr, te = d[(d.o_yr != yr) & (d.pos == pos)], d[(d.o_yr == yr) & (d.pos == pos)]
            if not len(te):
                continue
            pc_te, pc_tr = pick_curve(tr, te)
            P["pick"].loc[te.index] = pc_te
            lam = ridge_cv(tr, ["lpick"] + feats, "career")
            Xa, Xb, _ = design(tr, te, ["lpick"] + feats)
            mu = np.average(tr.career, weights=tr.w)
            P["ridge"].loc[te.index] = Xb @ ridge_fit(Xa, (tr.career - mu).values, tr.w.values, lam) + mu
            tr2 = tr.assign(res=tr.career - pc_tr)
            lam2 = ridge_cv(tr2, feats, "res")
            Xa, Xb, _ = design(tr, te, feats)
            P["resid"].loc[te.index] = pc_te + Xb @ ridge_fit(Xa, tr2.res.values - np.average(tr2.res, weights=tr.w), tr.w.values, lam2)
            # unit-weight index of inputs that beat the pick on the training years
            sel = []
            for f in feats:
                if tr[f].notna().mean() < 0.5:
                    continue
                pr = partial(tr[f], tr.career, -tr.pickn)
                if np.isfinite(pr) and abs(pr) >= 0.12:
                    sel.append((f, 1 if pr > 0 else -1))
            for f, _s in sel:
                chosen[pos][f] = chosen[pos].get(f, 0) + 1
            if sel:
                za = pd.concat([s * ((tr[f] - tr[f].mean()) / tr[f].std()) for f, s in sel], axis=1).mean(axis=1, skipna=True).fillna(0)
                zb = pd.concat([s * ((te[f] - tr[f].mean()) / tr[f].std()) for f, s in sel], axis=1).mean(axis=1, skipna=True).fillna(0)
                sdz = za.std() or 1
                pz_tr, pz_te = (pc_tr - pc_tr.mean()) / (pc_tr.std() or 1), (pc_te - pc_tr.mean()) / (pc_tr.std() or 1)
                best = (-9, 0.5)
                for sh in (0.3, 0.45, 0.6, 0.75):
                    s_ = spearman(sh * pz_tr + (1 - sh) * za / sdz, tr.career)
                    if s_ > best[0]:
                        best = (s_, sh)
                P["index"].loc[te.index] = best[1] * pz_te + (1 - best[1]) * zb / sdz
            else:
                P["index"].loc[te.index] = pc_te
            if not a.fast:
                Xa, Xb, _ = design(tr, te, ["lpick"] + feats, flags=False)
                g = GBM(n=120, depth=2, min_leaf=max(6, len(tr) // 18)).fit(Xa, tr.career.values, tr.w.values)
                P["gbm"].loc[te.index] = g.predict(Xb)
        if not a.fast:   # pooled across positions: within-position z-scores + position flags
            tr, te = d[d.o_yr != yr], d[d.o_yr == yr]
            cols = ["lpick"] + feats
            Za, Zb = [], []
            for c in cols:
                za, zb = pd.Series(0.0, index=tr.index), pd.Series(0.0, index=te.index)
                for pos in POS:
                    m, s = tr.loc[tr.pos == pos, c].mean(), tr.loc[tr.pos == pos, c].std()
                    if np.isfinite(s) and s > 0:
                        za[tr.pos == pos] = ((tr.loc[tr.pos == pos, c] - m) / s).clip(-3, 3).fillna(0)
                        zb[te.pos == pos] = ((te.loc[te.pos == pos, c] - m) / s).clip(-3, 3).fillna(0)
                Za.append(za.values); Zb.append(zb.values)
            for pos in POS:
                Za.append((tr.pos == pos).values.astype(float)); Zb.append((te.pos == pos).values.astype(float))
            g = GBM(n=160, depth=2, min_leaf=14).fit(np.array(Za).T, tr.career.values, tr.w.values)
            P["pooled"].loc[te.index] = g.predict(np.array(Zb).T)
        print("  fold %d done" % yr, flush=True)
    for m in P:
        d["p_" + m] = P[m]
    d["p_blend"] = np.nan
    for pos in POS:
        m = d.pos == pos
        parts = [rankz(d.loc[m, "p_resid"]), rankz(d.loc[m, "p_index"])] + ([rankz(d.loc[m, "p_pooled"])] if not a.fast else [])
        d.loc[m, "p_blend"] = np.mean(parts, axis=0)
    site = json.load(open(a.site)) if a.site else {}
    d["s_v9"] = [site.get("%s|%d" % (n, y), {}).get("v9") for n, y in zip(d["name"], d.o_yr)]
    d["s_live"] = [site.get("%s|%d" % (n, y), {}).get("live") for n, y in zip(d["name"], d.o_yr)]
    d["negpick"] = -d.pickn

    def trio(g, col):
        top = g[g.pickn <= 100]
        ys = [(spearman(x[col], x.career), len(x)) for _, x in g.groupby("o_yr") if len(x) >= 8]
        ys = [(s, n) for s, n in ys if np.isfinite(s)]
        return spearman(g[col], g.career), spearman(top[col], top.career), (sum(s * n for s, n in ys) / sum(n for _, n in ys)) if ys else np.nan
    models = [("draft pick alone", "negpick"), ("site v9 (old)", "s_v9"), ("site live (v10.1)", "s_live"), ("scratch: pick curve", "p_pick"),
              ("scratch: ridge", "p_ridge"), ("scratch: pick + ridge residual", "p_resid"), ("scratch: pick + unit index", "p_index")]
    if not a.fast:
        models += [("scratch: boosted trees", "p_gbm"), ("scratch: pooled boosted trees", "p_pooled")]
    models += [("scratch: blend", "p_blend")]
    res = {}
    for pos in POS + ["ALL"]:
        g = d if pos == "ALL" else d[d.pos == pos]
        print("\n=== %s  n=%d ===  %-34s %6s %7s %6s" % (pos, len(g), "", "all", "top100", "class"))
        res[pos] = {}
        for label, col in models:
            if g[col].notna().sum() < 10:
                continue
            if pos == "ALL":   # rank within position first so scales are comparable
                gg = g.assign(_r=g.groupby("pos")[col].rank(pct=True), _c=g.groupby("pos").career.rank(pct=True))
                t = (spearman(gg._r, gg._c), spearman(gg[gg.pickn <= 100]._r, gg[gg.pickn <= 100]._c), np.nan)
            else:
                t = trio(g, col)
            res[pos][label] = t
            print("  %-46s %6.3f %7.3f %6s" % (label, t[0], t[1], ("%.3f" % t[2]) if np.isfinite(t[2]) else "  -"))
    for pos in POS:
        top = sorted(chosen[pos].items(), key=lambda kv: -kv[1])
        print("\n%s inputs that beat the pick (training folds of %d): %s" % (pos, len(years), ", ".join("%s %d" % kv for kv in top[:16])))
    if a.out:
        keep = ["name", "pos", "o_yr", "pickn", "career"] + ["p_" + m for m in list(P) + ["blend"]] + ["s_v9", "s_live"]
        json.dump({"rows": json.loads(d[keep].to_json(orient="records")), "metrics": {p: {k: [None if not np.isfinite(x) else round(float(x), 3) for x in v] for k, v in r.items()} for p, r in res.items()},
                   "chosen": chosen}, open(a.out, "w"), separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
