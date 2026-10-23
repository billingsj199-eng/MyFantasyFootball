#!/usr/bin/env python3
"""
MATCHUP SWING CALIBRATION - 2026 LOCK ROWS (2026-10-23). Companion to research_matchup_swing_calibration.py.
Weekly locks data/snapshots/simlab_snapshot_w<N>.json (per player: mean = final sim with props, jsMean = JS model,
ncMean = clay-free shadow, implied, opp). The locks carry no explicit pre-matchup baseline, so it is RECOVERED the way
the harness defines it: baseline = weekly / (vegasMult x jsOppMult) with vegasMult from the locked implied total vs
that week's average implied (engine elasticities), jsOppMult from fpa_2026.json points allowed entering the week
(ratio clip .8-1.25, elasticity .25, trust g/8; week 1 = 1, the engine's Clay unit prior cannot be rebuilt here).
Caveat: the live engine stacks more game-specific layers (snap / route / CB shadow / weather / usage) inside the
weekly number; those sit in the recovered baseline, not the swing. Top-150 = preseason Underdog ADP (accuracy/data/
preseason_2026.json ranks.ud, Sleeper rank fallback). Actuals = data/weekly_stats_active.js (half-PPR). Small n.
"""
import os, sys, json, glob, re
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from score_week import norm
REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"
POS4 = ("QB", "RB", "WR", "TE"); VEG = {"QB": 0.25, "RB": 0.50, "WR": 0.25, "TE": 0.25}
RNG = np.random.default_rng(3)
def P(*a): print(" ".join(str(x) for x in a))


def ols(X, y):
    b, *_ = np.linalg.lstsq(X, y, rcond=None); return b


def fit(y, cols, nboot=400):
    X = np.column_stack([np.ones(len(y))] + list(cols)); b = ols(X, y)
    bs = np.array([ols(X[i], y[i]) for i in (RNG.integers(0, len(y), len(y)) for _ in range(nboot))])
    return b, np.percentile(bs, 5, axis=0), np.percentile(bs, 95, axis=0)


def ci(b, lo, hi): return f"{b:+.2f} [{lo:+.2f},{hi:+.2f}]"


def main():
    raw = open(os.path.join(REPO, "data", "weekly_stats_active.js"), encoding="utf-8").read(); d = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    logs = {}
    for nm, rec in d.items():
        if rec.get("pos") not in POS4: continue
        logs[norm(nm)] = {int(w["wk"]): float(w["fpts"]) for w in (rec.get("seasons") or {}).get("2026", []) if isinstance(w.get("fpts"), (int, float)) and w.get("opp")}
    pre = json.load(open(os.path.join(REPO, "accuracy", "data", "preseason_2026.json"), encoding="utf-8"))["ranks"]
    adp = {}
    for nm, r in pre.items():
        v = r.get("ud") if isinstance(r.get("ud"), (int, float)) else r.get("sl")
        if isinstance(v, (int, float)): adp[norm(nm)] = float(v)
    fpa = json.load(open(os.path.join(REPO, "data", "fpa_2026.json"), encoding="utf-8"))["weeks"]
    rows = []
    for f in sorted(glob.glob(os.path.join(HERE, "data", "snapshots", "simlab_snapshot_w*.json")), key=lambda f: int(re.search(r"_w(\d+)", f).group(1))):
        S = json.load(open(f, encoding="utf-8")); W = int(S["week"])
        if W > 6: continue
        imp_by_team = {p["tm"]: p["implied"] for p in S["players"] if isinstance(p.get("implied"), (int, float))}
        avg = float(np.mean(list(imp_by_team.values())))
        # league FPA entering W
        past = [w for w in fpa if int(w) < W]
        lg = {ps: float(np.mean([t[ps] for w in past for t in fpa[w].values() if isinstance(t.get(ps), (int, float))])) for ps in POS4} if past else {}
        for p in S["players"]:
            ps = p.get("pos")
            if ps not in POS4 or not isinstance(p.get("implied"), (int, float)): continue
            k = norm(p["name"]); a = logs.get(k, {}).get(W)
            if a is None: continue
            weekly = p.get("ncMean") if isinstance(p.get("ncMean"), (int, float)) else p.get("jsMean")
            if not isinstance(weekly, (int, float)) or weekly <= 0.5: continue
            veg = min(1.35, max(0.7, 1 + VEG[ps] * (p["implied"] - avg) / avg))
            opp = p.get("opp"); vals = [fpa[w][opp][ps] for w in past if opp in fpa[w] and isinstance(fpa[w][opp].get(ps), (int, float))]
            fp = 1.0
            if vals and lg.get(ps):
                fp = 1 + 0.25 * (min(1.25, max(0.8, np.mean(vals) / lg[ps])) - 1) * min(1, len(vals) / 8)
            rows.append(dict(wk=W, pos=ps, name=p["name"], weekly=float(weekly), final=float(p["mean"]), veg=veg, fpa=fp, act=float(a), adp=adp.get(k, np.nan), src="nc" if isinstance(p.get("ncMean"), (int, float)) else "js"))
    n = len(rows); P(f"=== 2026 W1-6 lock rows: {n} (shadow ncMean where present else jsMean; weekly source counts: {sum(1 for r in rows if r['src']=='nc')} nc / {sum(1 for r in rows if r['src']=='js')} js) ===")
    A = {k: np.array([r[k] for r in rows]) for k in ("wk", "weekly", "final", "veg", "fpa", "act", "adp")}; pos = np.array([r["pos"] for r in rows], dtype=object)
    layers = A["veg"] * A["fpa"]; base = A["weekly"] / layers; swing = A["weekly"] - base; sv = base * (A["veg"] - 1); so = base * (A["fpa"] - 1); y = A["act"] - base
    top = ~np.isnan(A["adp"]) & (A["adp"] <= 150)
    P(f"  top-150 rows {top.sum()}; mean |swing| {np.abs(swing[top]).mean():.2f} (Vegas {np.abs(sv[top]).mean():.2f}, opp {np.abs(so[top]).mean():.2f}); act/weekly bias {A['act'][top].mean()/A['weekly'][top].mean():.3f}")
    P(f"  {'cut':8s} {'n':>5s}  {'b total':22s} {'bV Vegas':22s} {'bO opp':22s}  (row bootstrap 90% CI; weeks pooled, n small)")
    for lab, m in [("ALL", top)] + [(ps, top & (pos == ps)) for ps in POS4]:
        if m.sum() < 25: P(f"  {lab:8s} {m.sum():5d}  too few"); continue
        b1, lo1, hi1 = fit(y[m], [swing[m]]); b2, lo2, hi2 = fit(y[m], [sv[m], so[m]])
        P(f"  {lab:8s} {m.sum():5d}  {ci(b1[1],lo1[1],hi1[1]):22s} {ci(b2[1],lo2[1],hi2[1]):22s} {ci(b2[2],lo2[2],hi2[2]):22s}")
    P("  by week bucket (ALL positions):")
    for lab, m in (("wk 1-3", top & (A["wk"] <= 3)), ("wk 4-6", top & (A["wk"] >= 4))):
        b1, lo1, hi1 = fit(y[m], [swing[m]]); b2, lo2, hi2 = fit(y[m], [sv[m], so[m]])
        P(f"    {lab:8s} {m.sum():5d}  b {ci(b1[1],lo1[1],hi1[1])}  bV {ci(b2[1],lo2[1],hi2[1])}  bO {ci(b2[2],lo2[2],hi2[2])}")
    P("  swing terciles (top-150, pooled): swing -> realized (bias removed)")
    a0 = fit(y[top], [swing[top]], nboot=1)[0][0]; q = np.percentile(swing[top], [33, 67])
    for lab, m in (("low", top & (swing <= q[0])), ("mid", top & (swing > q[0]) & (swing < q[1])), ("high", top & (swing >= q[1]))):
        P(f"    {lab:4s} n {m.sum():4d} swing {swing[m].mean():+5.2f} -> realized {y[m].mean()-a0:+5.2f}")
    # final sim number (props blended) instead of the shadow: same recovery
    base2 = A["final"] / layers; y2 = A["act"] - base2; sw2 = A["final"] - base2
    b1, lo1, hi1 = fit(y2[top], [sw2[top]]); P(f"  same on the FINAL sim number (props blended): b {ci(b1[1],lo1[1],hi1[1])} (n {top.sum()})")
    # cross-check for week 6 against the week-5 rest-of-season lock (true pre-week ROS level, every layer inside the weekly number)
    try:
        L = json.load(open(os.path.join(HERE, "data", "snapshots", "simlab_ros_w5.json"), encoding="utf-8"))
        ros = {norm(p["name"]): p.get("rosShadow") or p.get("ros") for p in L["players"]}
        yy, ss = [], []
        for r in rows:
            if r["wk"] != 6 or not (r["adp"] <= 150): continue
            rs = ros.get(norm(r["name"]))
            if isinstance(rs, (int, float)) and rs > 0: yy.append(r["act"] - rs); ss.append(r["weekly"] - rs)
        yy, ss = np.array(yy), np.array(ss); b, lo, hi = fit(yy, [ss])
        P(f"  week 6 vs the week-5 ROS lock (swing = week-6 shadow - locked ROS shadow, ALL layers): n {len(yy)} mean |swing| {np.abs(ss).mean():.2f} b {ci(b[1],lo[1],hi[1])}")
    except Exception as e: P("  ROS lock cross-check skipped:", e)


if __name__ == "__main__":
    main()
