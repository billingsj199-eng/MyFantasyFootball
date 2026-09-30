import sys, json, os, numpy as np, pandas as pd
sys.path.insert(0, ".")
import backtest_noclay_weekly as NW, research_clay_vs_shadow as CS, backtest_season_long as SL
from scipy.stats import spearmanr
F = CS.build_harness(); A = F["A"]; n = F["n"]
act, year, wk, pos, g, ppg, clay, layers, adp, pid = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"], F["adp"], A["pid"]
ch = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, A["name"])], dtype=float)
W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay)
T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]; lo = SL.loyo(T, LIVE, "ridge", 10.0)
key = {(int(y), nm, ps): v for y, nm, ps, v in zip(T.year, T.name, T.pos, lo)}; r = np.array([key.get((year[i], A["name"][i], pos[i]), np.nan) for i in range(n)])
prior = np.where(np.isnan(r) | (pos == "QB"), F["prior"], 0.5 * r + 0.5 * F["prior"])
def finish(rate):
    out = rate * layers
    for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
    return np.where(F["on"], out * np.power(F["pm"], 0.75), out)
C = pd.read_parquet("ctx_features.parquet"); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); xfp = np.where(idx >= 0, C.xfp_pg.values[np.maximum(idx, 0)], np.nan)
ev = (idx >= 0) & (g >= 1) & ~np.isnan(xfp); xf = np.where(ev, xfp, ppg)
lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
M = {"preseason prior only (never updates)": finish(prior), "Clay blend (per-game)": NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers,
     "shadow v2.17 (points evidence)": finish(NW.blend(prior, g, ppg, F["Pvec"])), "shadow v2.18 (usage evidence)": finish(NW.blend(prior, g, lam * xf + (1 - lam) * ppg, F["Pvec"]))}
lv = F["adp_curve"].copy()
for ps in NW.POS4:
    m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & (adp <= 150)].mean()
wt = np.maximum(0.05, lv) ** 2; top150 = adp <= 150
stages = (("week 1 (0 games)", 0, 0), ("1 game", 1, 1), ("2 games", 2, 2), ("3 games", 3, 3), ("4-5", 4, 5), ("6-8", 6, 8), ("9-12", 9, 12), ("13+", 13, 99))
print("Top 150, importance-weighted. RMSE = typical miss in half-PPR points; r = correlation of projection with actual; rank r = Spearman within position")
print(f"  {'stage':18s} {'n':>5s} | " + " | ".join(f"{k[:28]:>28s}" for k in M))
for lab, a, b in stages:
    m = top150 & (g >= a) & (g <= b); cells = []
    for k, p in M.items():
        rmse = np.sqrt(np.average((p[m] - act[m]) ** 2, weights=wt[m])); rr = np.corrcoef(p[m], act[m])[0, 1]
        sp = np.mean([spearmanr(p[m & (pos == ps)], act[m & (pos == ps)]).correlation for ps in NW.POS4])
        cells.append(f"RMSE {rmse:5.2f} r {rr:.3f} rank {sp:.3f}")
    print(f"  {lab:18s} {m.sum():5d} | " + " | ".join(f"{c:>28s}" for c in cells))
print("\nValue of in-season learning = error of the never-updating prior vs the shadow v2.18, by stage (weighted MSE):")
for lab, a, b in stages:
    m = top150 & (g >= a) & (g <= b); e0 = np.average((M["preseason prior only (never updates)"][m] - act[m]) ** 2, weights=wt[m]); e1 = np.average((M["shadow v2.18 (usage evidence)"][m] - act[m]) ** 2, weights=wt[m]); ec = np.average((M["Clay blend (per-game)"][m] - act[m]) ** 2, weights=wt[m])
    print(f"  {lab:18s} shadow vs frozen prior {(e1/e0-1)*100:+6.2f}% | shadow vs Clay blend {(e1/ec-1)*100:+6.2f}%")
print("\nBy position, shadow v2.18 RMSE early (games 1-3) vs late (games 9+), and r:")
for ps in NW.POS4:
    for lab, m in (("games 1-3", top150 & (pos == ps) & (g >= 1) & (g <= 3)), ("games 9+", top150 & (pos == ps) & (g >= 9))):
        p = M["shadow v2.18 (usage evidence)"]; p0 = M["preseason prior only (never updates)"]
        print(f"  {ps} {lab:10s} n={m.sum():4d} RMSE {np.sqrt(np.average((p[m]-act[m])**2, weights=wt[m])):5.2f} r {np.corrcoef(p[m], act[m])[0,1]:.3f} | frozen prior RMSE {np.sqrt(np.average((p0[m]-act[m])**2, weights=wt[m])):5.2f} r {np.corrcoef(p0[m], act[m])[0,1]:.3f}")
