"""
SAME-GAME CORRELATION for the live win odds. The per-player spread (liveVar,
backtest_live_variance.py) treats starters as independent; a QB stacked with
his own receiver, or a lineup facing the D/ST that plays its own QB, is not.
This measures the correlation of the standardized residuals z = (rem_actual -
rem_fit) / sd_liveVar for every pair of players in the same game, by
relationship (same team / opponents), position-class pair and game fraction,
on pbp 2019-23, checks the effect on STACKED lineups in 2024-25, and ships the
table as `liveCorr` in live_model.json (v4). The helpers add
2 * sum_{i<j} s_i s_j rho_ij sd_i sd_j (s = +1 my side, -1 theirs) to the
matchup variance.

usage: python backtest_live_corr.py
"""
import itertools, json, math, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_live_remaining as blr  # noqa: E402
import backtest_live_kdst as bk  # noqa: E402

OUT = os.path.join(HERE, "data", "live_model.json")
GRID_V = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
blr.GRID = GRID_V; bk.GRID = GRID_V
LM = json.load(open(OUT))
CLASSES = ("QB", "RB", "REC", "K", "DST")
MIN_N = 300       # pairs per (key, f) bin before the bin's own estimate is trusted
SHRINK = 500      # pseudo-count toward the pooled-over-f value


def coefs(rows, grid, f):
    if f <= grid[0]: return rows[0]
    if f >= grid[-1]: return rows[-1]
    i = 0
    while i < len(grid) - 2 and grid[i + 1] < f: i += 1
    t = (f - grid[i]) / (grid[i + 1] - grid[i])
    return [rows[i][k] + (rows[i + 1][k] - rows[i][k]) * t for k in range(len(rows[i]))]


def rem_fit(cls, f, E, cum, margin, rel):
    if cls in LM["pos"]:
        co = coefs(LM["pos"][cls], LM["grid"], f)
        extra = co[3] * (rel / 10.0) if len(co) > 3 else 0.0
        r = (1 - f) * (co[0] * E + co[1] * (cum / max(f, 0.1)) + co[2] * E * (margin / 10.0) + extra)
        return np.maximum(-4.0 - cum, r) if cls == "DST" else np.maximum(0.0, r)
    pace = np.where(f >= 0.15, cum / max(f, 0.01), E)
    w = 0.25 * f
    return np.maximum(0.0, (1 - f) * ((1 - w) * E + w * pace))


def sd_livevar(cls, f, rem):
    lv = LM["liveVar"]
    c0, c1 = coefs(lv["pos"][cls], lv["grid"], f)
    return np.sqrt(np.maximum(c0 + c1 * np.abs(rem) ** 2, 1e-6))


def build(years):
    cols = ["season", "pos", "E", "cum", "f0", "margin", "rel", "total", "game_id", "team", "pid"]
    s1 = blr.build_samples(years); s1["rel"] = 0.0
    s2 = bk.build(years)
    s = pd.concat([s1[cols], s2[cols]], ignore_index=True)
    s["rem_actual"] = s.total - s.cum
    s["rem_fit"] = 0.0; s["sd"] = 1.0
    for (cls, f0), idx in s.groupby(["pos", "f0"]).groups.items():
        sub = s.loc[idx]
        rf = rem_fit(cls, float(f0), sub.E.values, sub.cum.values, sub.margin.values, sub.rel.values)
        s.loc[idx, "rem_fit"] = rf
        s.loc[idx, "sd"] = sd_livevar(cls, float(f0), rf)
    s["z"] = (s.rem_actual - s.rem_fit) / s.sd
    for c in ("pos", "team", "pid", "game_id"): s[c] = s[c].astype(str)
    return s


def pair_key(rel, a, b):
    return rel + ":" + "|".join(sorted([a, b]))


def measure(s):
    """sum z_i z_j and n per (key, f0) over every pair in the same game."""
    acc = {}
    for (f0, gid), g in s.groupby(["f0", "game_id"]):
        z, pos, team = g.z.values, g.pos.values, g.team.values
        n = len(g)
        if n < 2: continue
        zz = np.outer(z, z)
        for i in range(n):
            for j in range(i + 1, n):
                key = pair_key("same" if team[i] == team[j] else "opp", pos[i], pos[j])
                a = acc.setdefault((key, f0), [0.0, 0])
                a[0] += zz[i, j]; a[1] += 1
    return acc


def table(acc):
    """rho per key x f (shrunk toward the pooled value) + pooled."""
    keys = sorted({k for k, _ in acc})
    pooled = {k: (sum(acc[(k, f)][0] for f in GRID_V if (k, f) in acc), sum(acc[(k, f)][1] for f in GRID_V if (k, f) in acc)) for k in keys}
    out = {}
    for k in keys:
        sp, npool = pooled[k]
        rp = sp / npool if npool else 0.0
        rows = []
        for f in GRID_V:
            sz, n = acc.get((k, f), (0.0, 0))
            rows.append(round((sz + SHRINK * rp) / (n + SHRINK), 4))
        out[k] = {"rho": rows, "pooled": round(rp, 4), "n": int(npool)}
    return out


def evaluate(test, tab, use_f, n_per=6000, seed=11):
    """Matchup calibration on holdout for three lineup shapes, with and without covariance."""
    rng = np.random.default_rng(seed)
    res = {}
    for f0 in GRID_V:
        d = test[test.f0 == f0].reset_index(drop=True)
        by_team = {k: v.index.values for k, v in d.groupby(["game_id", "team"])}
        pools = {c: d.index[d.pos == c].values for c in CLASSES}
        games = d[["game_id", "team"]].drop_duplicates()
        opp_of = {}
        for gid, g in games.groupby("game_id"):
            t = g.team.values
            if len(t) == 2: opp_of[(gid, t[0])] = t[1]; opp_of[(gid, t[1])] = t[0]
        def idx_of(gid, team, cls, k, exclude=()):
            cand = [i for i in by_team.get((gid, team), []) if d.pos[i] == cls and i not in exclude]
            if len(cand) < k: return None
            return list(rng.choice(cand, size=k, replace=False))
        shapes = {"random": [], "stack QB+2REC": [], "stack vs hedge (their DST + their REC of my QB's team)": []}
        for shape in shapes:
            A, B = [], []
            tries = 0
            while len(A) < n_per and tries < n_per * 4:
                tries += 1
                qb = int(rng.choice(pools["QB"]))
                gid, tm = d.game_id[qb], d.team[qb]
                a = [qb]; b = []
                if shape != "random":
                    recs = idx_of(gid, tm, "REC", 3, exclude=a)
                    if recs is None: continue
                    a += recs[:2]
                    if shape.startswith("stack vs"):
                        o = opp_of.get((gid, tm))
                        if o is None: continue
                        dst = idx_of(gid, o, "DST", 1)
                        if dst is None: continue
                        b += dst + [recs[2]]
                else:
                    a += list(rng.choice(pools["REC"], 2))
                a += list(rng.choice(pools["RB"], 2)) + [int(rng.choice(pools["REC"])), int(rng.choice(pools["K"])), int(rng.choice(pools["DST"]))]
                b += [int(rng.choice(pools["QB"]))] + list(rng.choice(pools["RB"], 2)) + list(rng.choice(pools["REC"], 3 if len(b) else 3))
                b += [int(rng.choice(pools["K"]))] + ([] if any(d.pos[i] == "DST" for i in b) else [int(rng.choice(pools["DST"]))])
                A.append(a); B.append(b)
            if not A: continue
            rows = []
            for a, b in zip(A, B):
                ids = a + b; sgn = np.array([1.0] * len(a) + [-1.0] * len(b))
                sub = d.loc[ids]
                live = float((sgn * (sub.cum.values + sub.rem_fit.values)).sum())
                fin = float((sgn * sub.total.values).sum())
                sd = sub.sd.values
                var_ind = float((sd ** 2).sum())
                cov = 0.0
                g_, t_, p_ = sub.game_id.values, sub.team.values, sub.pos.values
                for i in range(len(ids)):
                    for j in range(i + 1, len(ids)):
                        if g_[i] != g_[j] or ids[i] == ids[j]: continue
                        key = pair_key("same" if t_[i] == t_[j] else "opp", p_[i], p_[j])
                        e = tab.get(key)
                        if not e: continue
                        rho = e["rho"][GRID_V.index(f0)] if use_f else e["pooled"]
                        cov += 2 * sgn[i] * sgn[j] * rho * sd[i] * sd[j]
                rows.append((live, fin, var_ind, max(var_ind + cov, 1e-6)))
            r = np.array(rows)
            for lbl, var in (("independent", r[:, 2]), ("with corr", r[:, 3])):
                z = (r[:, 1] - r[:, 0]) / np.sqrt(var)
                p = 0.5 * (1 + np.vectorize(math.erf)(r[:, 0] / np.sqrt(2 * var)))
                won = (r[:, 1] > 0).astype(float)
                ll = float(-(won * np.log(p + 1e-6) + (1 - won) * np.log(1 - p + 1e-6)).mean())
                res.setdefault(shape, {}).setdefault(lbl, []).append((f0, float(z.std()), ll, len(r)))
    print("\n=== HOLDOUT MATCHUPS: std(team z) / log-loss, independent -> with correlation (by lineup shape) ===")
    summary = {}
    for shape, dd in res.items():
        print(f"  {shape}:")
        for lbl in ("independent", "with corr"):
            v = dd[lbl]
            n = sum(x[3] for x in v)
            zs = math.sqrt(sum(x[1] ** 2 * x[3] for x in v) / n); ll = sum(x[2] * x[3] for x in v) / n
            summary.setdefault(shape, {})[lbl] = {"z_std": round(zs, 3), "logloss": round(ll, 4)}
            print(f"    {lbl:<12} std(z) {zs:.3f}  log-loss {ll:.4f}   by f: " + " ".join(f"{x[0]:.1f}:{x[1]:.2f}" for x in v))
    return summary


def main():
    def cached(tag, years):
        pth = os.path.join(HERE, "data", f"live_corr_samples_{tag}.pkl")
        if os.path.exists(pth): return pd.read_pickle(pth)
        d = build(years); d.to_pickle(pth); return d
    print("building samples", flush=True)
    train = cached("fit", blr.FIT_YEARS)
    test = cached("hold", blr.HOLD_YEARS)
    print("measuring pair correlations (2019-23)", flush=True)
    tab = table(measure(train))
    print("\n=== PAIR CORRELATION of standardized remaining residuals (pooled over f; n pairs) — same team / opponents ===")
    for rel in ("same", "opp"):
        for k in sorted(tab):
            if not k.startswith(rel + ":"): continue
            e = tab[k]
            if e["n"] < 2000: continue
            print(f"  {k:<14} rho {e['pooled']:+.3f}  n {e['n']:>7}   by f: " + " ".join(f"{r:+.2f}" for r in e["rho"]))
    summary = evaluate(test, tab, use_f=True)
    full = table(measure(pd.concat([train, test], ignore_index=True)))
    ship = {k: {"rho": e["rho"] + [0.0], "n": e["n"]} for k, e in full.items() if e["n"] >= 2000}
    LM["liveCorr"] = {"grid": GRID_V + [1.0], "pairs": ship, "eval_holdout_2024_25": summary,
                      "desc": "rho of standardized remaining residuals for two players in the same game, key = same|opp:CLS|CLS (classes QB RB REC K DST), rows by game fraction; var(A-B) += 2*sum s_i s_j rho sd_i sd_j"}
    LM["version"] = 4
    LM["built"] = pd.Timestamp.now("UTC").strftime("%Y-%m-%dT%H:%MZ")
    json.dump(LM, open(OUT, "w"), indent=1)
    print("\nwrote liveCorr (", len(ship), "pair keys ) into", OUT)


if __name__ == "__main__":
    main()
