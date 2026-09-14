"""
Calibrate the LIVE WIN-ODDS variance. The helpers turn each starter's remaining
projection into a normal sd = rem x sigma (sigma = the season sim's per-player
CV, defaults QB .42 / RB .52 / WR .58 / TE .65 / K .55 / DST .60) and sum the
variances for P(win) = Phi(diff / sd). That shrinks the spread linearly with the
remaining projection, but a touchdown is 6 points whether 60% or 10% of the game
is left, so late-game odds are too confident. This fits the residual spread of
the live model's remaining (rem_actual - rem_fit) by class x game fraction on
pbp 2019-23, checks 2024-25, and ships the winner as `liveVar` in live_model.json.

Candidate sd forms per class x f bin (f = 0.0, 0.1 ... 0.9):
  F1 current   sd = sigma_default x rem_fit
  F2 rescaled  sd = k x rem_fit                    k fitted
  F3 poisson   sd = sqrt(a x E x (1-f))            a fitted (variance ~ expected remaining)
  F4 linear    sd = sqrt(c0 + c1 x rem_fit^2)      least squares on resid^2 (floor + scale)
Evaluation: player-level std(z) per bin (want 1.0) and MATCHUP-level: 20k random
9-starter lineups (QB, 2 RB, 3 REC, 1 RB/REC flex, K, DST) per bin from the same
season, P(A beats B) = Phi(diff/sd) vs the actual outcome -> Brier, log-loss,
calibration by predicted-probability bucket, std of the team z.

usage: python backtest_live_variance.py
"""
import json, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_live_remaining as blr  # noqa: E402
import backtest_live_kdst as bk  # noqa: E402

OUT = os.path.join(HERE, "data", "live_model.json")
GRID_V = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
blr.GRID = GRID_V; bk.GRID = GRID_V
SIG_DEFAULT = {"QB": 0.42, "RB": 0.52, "REC": 0.6, "K": 0.55, "DST": 0.6}
LM = json.load(open(OUT))


def coefs(cls, f):
    grid, rows = LM["grid"], LM["pos"][cls]
    if f <= grid[0]: return rows[0]
    if f >= grid[-1]: return rows[-1]
    i = 0
    while i < len(grid) - 2 and grid[i + 1] < f: i += 1
    t = (f - grid[i]) / (grid[i + 1] - grid[i])
    return [rows[i][k] + (rows[i + 1][k] - rows[i][k]) * t for k in range(len(rows[i]))]


def rem_fit(cls, f, E, cum, margin, rel):
    """Exactly what the helpers compute (K: v1 heuristic; DST floor -4-cum)."""
    if cls in LM["pos"]:
        co = coefs(cls, f)
        extra = co[3] * (rel / 10.0) if len(co) > 3 else 0.0
        r = (1 - f) * (co[0] * E + co[1] * (cum / max(f, 0.1)) + co[2] * E * (margin / 10.0) + extra)
        return np.maximum(-4.0 - cum, r) if cls == "DST" else np.maximum(0.0, r)
    pace = np.where(f >= 0.15, cum / max(f, 0.01), E)
    w = 0.25 * f
    return np.maximum(0.0, (1 - f) * ((1 - w) * E + w * pace))


def build(years):
    s1 = blr.build_samples(years)
    s1["rel"] = 0.0
    s2 = bk.build(years)
    s = pd.concat([s1[["season", "pos", "E", "cum", "f0", "margin", "rel", "total"]], s2[["season", "pos", "E", "cum", "f0", "margin", "rel", "total"]]], ignore_index=True)
    s["rem_actual"] = s.total - s.cum
    s["rem_fit"] = 0.0
    for (cls, f0), idx in s.groupby(["pos", "f0"]).groups.items():
        sub = s.loc[idx]
        s.loc[idx, "rem_fit"] = rem_fit(cls, float(f0), sub.E.values, sub.cum.values, sub.margin.values, sub.rel.values)
    s["resid"] = s.rem_actual - s.rem_fit
    return s


def fit_forms(train):
    """Per class x f bin: F2 k, F3 a, F4 (c0, c1)."""
    tab = {}
    for (cls, f0), grp in train.groupby(["pos", "f0"]):
        r2 = grp.resid.values ** 2
        k = float(np.sqrt(r2.sum() / max((grp.rem_fit.values ** 2).sum(), 1e-9)))
        a = float(r2.sum() / max((grp.E.values * (1 - f0)).sum(), 1e-9))
        X = np.column_stack([np.ones(len(grp)), grp.rem_fit.values ** 2])
        c, *_ = np.linalg.lstsq(X, r2, rcond=None)
        c0, c1 = max(float(c[0]), 0.0), max(float(c[1]), 0.0)
        if c0 == 0 and c1 == 0: c0 = float(r2.mean())
        tab[(cls, f0)] = {"F2": k, "F3": a, "F4": (c0, c1)}
    return tab


def sd_of(form, tab, cls, f0, E, rem):
    if form == "F1": return SIG_DEFAULT[cls] * np.maximum(rem, 0)
    p = tab[(cls, f0)]
    if form == "F2": return p["F2"] * np.maximum(rem, 0)
    if form == "F3": return np.sqrt(np.maximum(p["F3"] * E * (1 - f0), 1e-6))
    c0, c1 = p["F4"]; return np.sqrt(np.maximum(c0 + c1 * rem ** 2, 1e-6))


def matchups(test, tab, form, n_per_bin=20000, seed=7):
    """Random lineups from the same season at the same f bin; returns rows of (p, won, z)."""
    rng = np.random.default_rng(seed)
    slots = [("QB", 1), ("RB", 2), ("REC", 3), ("FLEX", 1), ("K", 1), ("DST", 1)]
    out = []
    for f0 in GRID_V:
        d = test[test.f0 == f0]
        for season, ds in d.groupby("season"):
            pools = {cls: ds[ds.pos == cls] for cls in ("QB", "RB", "REC", "K", "DST")}
            pools["FLEX"] = pd.concat([pools["RB"], pools["REC"]])
            if any(len(v) < 10 for v in pools.values()): continue
            n = n_per_bin // d.season.nunique()
            live_a = live_b = fin_a = fin_b = var_a = var_b = 0
            for cls, cnt in slots:
                pool = pools[cls]
                ia = rng.integers(0, len(pool), size=(n, cnt)); ib = rng.integers(0, len(pool), size=(n, cnt))
                cum, rem, tot, E = (np.asarray(pool[k].to_numpy(), dtype=float) for k in ("cum", "rem_fit", "total", "E"))
                c = cls if cls != "FLEX" else None
                pos = np.asarray(pool.pos.astype(str).to_numpy())
                def sd_arr(idx):
                    s = np.zeros(idx.shape)
                    for cc in ("RB", "REC") if c is None else (c,):
                        m = pos[idx] == cc
                        s[m] = sd_of(form, tab, cc, f0, E[idx][m], rem[idx][m])
                    return s
                live_a = live_a + (cum[ia] + rem[ia]).sum(1); live_b = live_b + (cum[ib] + rem[ib]).sum(1)
                fin_a = fin_a + tot[ia].sum(1); fin_b = fin_b + tot[ib].sum(1)
                var_a = var_a + (sd_arr(ia) ** 2).sum(1); var_b = var_b + (sd_arr(ib) ** 2).sum(1)
            sd = np.sqrt(var_a + var_b)
            diff = live_a - live_b
            p = 0.5 * (1 + np.vectorize(lambda z: __import__("math").erf(z / np.sqrt(2)))(diff / np.maximum(sd, 1e-6)))
            won = (fin_a > fin_b).astype(float)
            z = ((fin_a - fin_b) - diff) / np.maximum(sd, 1e-6)
            out.append(pd.DataFrame({"f0": f0, "p": p, "won": won, "z": z}))
    return pd.concat(out, ignore_index=True)


def report(test, tab):
    print("\n=== PLAYER-LEVEL std(z = resid/sd) by class x f (want 1.00): F1 current | F2 | F3 | F4 ===")
    for cls in ("QB", "RB", "REC", "K", "DST"):
        line = []
        for f0 in GRID_V:
            g = test[(test.pos == cls) & (test.f0 == f0)]
            zs = [np.std(g.resid.values / np.maximum(sd_of(fm, tab, cls, f0, g.E.values, g.rem_fit.values), 1e-6)) for fm in ("F1", "F2", "F3", "F4")]
            line.append(f"f={f0:.1f} " + "|".join(f"{z:4.2f}" for z in zs))
        print(f"  {cls}: " + "  ".join(line))
    print("\n=== MATCHUP-LEVEL (random 9-starter lineups, holdout): Brier | log-loss | std(team z) | calibration ===")
    res = {}
    for fm in ("F1", "F2", "F3", "F4"):
        m = matchups(test, tab, fm)
        eps = 1e-6
        brier = float(((m.p - m.won) ** 2).mean())
        ll = float(-(m.won * np.log(m.p + eps) + (1 - m.won) * np.log(1 - m.p + eps)).mean())
        res[fm] = {"brier": round(brier, 4), "logloss": round(ll, 4), "z_std": round(float(m.z.std()), 3)}
        print(f"  {fm}: Brier {brier:.4f}  log-loss {ll:.4f}  std(z) {m.z.std():.3f}")
        m["b"] = pd.cut(m.p, [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001], right=False)
        cal = m.groupby("b", observed=True).agg(pred=("p", "mean"), actual=("won", "mean"), n=("won", "size"))
        print("      " + "  ".join(f"{r.pred:.2f}->{r.actual:.2f}" for _, r in cal.iterrows()))
        byf = m.groupby("f0").apply(lambda d: pd.Series({"brier": ((d.p - d.won) ** 2).mean(), "zstd": d.z.std()}))
        print("      by f: " + "  ".join(f"{f:.1f}:{r.brier:.3f}/{r.zstd:.2f}" for f, r in byf.iterrows()))
    return res


def main():
    print("building samples (skill + K/DST) 2019-23 / 2024-25", flush=True)
    def cached(tag, years):  # the two sample builders take ~5 min; cache per run
        pth = os.path.join(HERE, "data", f"live_var_samples_{tag}.pkl")
        if os.path.exists(pth): return pd.read_pickle(pth)
        d = build(years); d.to_pickle(pth); return d
    train = cached("fit", blr.FIT_YEARS)
    test = cached("hold", blr.HOLD_YEARS)
    tab = fit_forms(train)
    res = report(test, tab)
    best = min(("F2", "F3", "F4"), key=lambda k: res[k]["logloss"])
    print(f"\nbest by holdout log-loss: {best}")
    full = fit_forms(pd.concat([train, test], ignore_index=True))
    rows = {}
    for cls in ("QB", "RB", "REC", "K", "DST"):
        r = []
        for f0 in GRID_V:
            p = full[(cls, f0)]
            r.append([round(p["F4"][0], 3), round(p["F4"][1], 4)] if best == "F4" else [round(p["F2"], 4)] if best == "F2" else [round(p["F3"], 4)])
        r.append([0.0, 0.0] if best == "F4" else [0.0])  # f = 1.0: no variance left
        rows[cls] = r
    LM["liveVar"] = {"form": best, "grid": GRID_V + [1.0], "pos": rows, "eval_holdout_2024_25": res,
                     "desc": {"F2": "sd = k*rem", "F3": "sd = sqrt(a*E*(1-f))", "F4": "sd = sqrt(c0 + c1*rem^2)"}[best]}
    LM["version"] = 3
    LM["built"] = pd.Timestamp.now("UTC").strftime("%Y-%m-%dT%H:%MZ")
    json.dump(LM, open(OUT, "w"), indent=1)
    print("wrote liveVar (", best, ") into", OUT)


if __name__ == "__main__":
    main()
