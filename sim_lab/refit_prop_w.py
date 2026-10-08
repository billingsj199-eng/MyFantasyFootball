# Re-fit the market weight on the CLAY-FREE shadow (ncMean at lock) - W1-4 2026 lock rows. Market reconstructed as the tuner does.
import json, glob, os, re, numpy as np
import tune_weekly as TW
W = np.round(np.arange(0, 1.01, 0.05), 2)
out = {}
for f in sorted(glob.glob(os.path.join(TW.HERE, "data", "snapshots", "simlab_snapshot_w*.json"))):
    wk = int(re.search(r"_w(\d+)\.json$", f).group(1)); act = TW.load_rows(wk)
    if not act: continue
    for p in json.load(open(f, encoding="utf-8"))["players"]:
        if p.get("pos") not in ("QB", "RB", "WR", "TE") or (p.get("mean") or 0) < TW.MIN_PROJ: continue
        a = act.get(TW.norm(p["name"])); tun = p.get("tun") or {}
        if a is None or p.get("propSrc") != "line" or not isinstance(p.get("propMean"), (int, float)) or not isinstance(p.get("jsMean"), (int, float)) or not isinstance(p.get("ncMean"), (int, float)): continue
        wl = tun.get("wa") or tun.get("w") or TW.PRIOR_W
        if not (0 < wl <= 1) or abs(p["propMean"] - p["jsMean"]) <= 0.05: continue
        mk = (p["propMean"] - (1 - wl) * p["jsMean"]) / wl
        out.setdefault(p["pos"], []).append((wk, float(a["fpts"]), p["ncMean"], mk, p["name"]))
for pos, rs in out.items():
    wk = np.array([r[0] for r in rs]); act = np.array([r[1] for r in rs]); nc = np.array([r[2] for r in rs]); mk = np.array([r[3] for r in rs])
    mae = lambda w, m=None: float(np.mean(np.abs((1 - w) * nc[m] + w * mk[m] - act[m]))) if m is not None else float(np.mean(np.abs((1 - w) * nc + w * mk - act)))
    mse = lambda w: float(np.mean(((1 - w) * nc + w * mk - act) ** 2))
    best = W[int(np.argmin([mae(w) for w in W]))]; bestS = W[int(np.argmin([mse(w) for w in W]))]
    byw = " ".join(f"W{k}:{W[int(np.argmin([mae(w, wk == k) for w in W]))]:.2f}(n{int((wk == k).sum())})" for k in sorted(set(wk)))
    print(f"{pos}: n {len(rs)} | actual {act.mean():.2f} model {nc.mean():.2f} market {mk.mean():.2f} | model closer {np.mean(np.abs(nc-act) < np.abs(mk-act)):.0%} | MAE-best w {best:.2f} (MAE {mae(best):.3f} vs w .1 {mae(0.1):.3f}, w .3 {mae(0.3):.3f}, w .5 {mae(0.5):.3f}) | MSE-best w {bestS:.2f} | by week {byw}")
    if pos == "TE":
        gap = mk - nc; big = gap >= 1.5
        print(f"   TE rows where the books sit 1.5+ above us: n {int(big.sum())} | actual {act[big].mean():.2f} model {nc[big].mean():.2f} market {mk[big].mean():.2f} | MAE-best w there {W[int(np.argmin([mae(w, big) for w in W]))]:.2f}")
        top = nc >= 9
        print(f"   TE starters (model >= 9): n {int(top.sum())} | actual {act[top].mean():.2f} model {nc[top].mean():.2f} market {mk[top].mean():.2f} | MAE-best w {W[int(np.argmin([mae(w, top) for w in W]))]:.2f}")
