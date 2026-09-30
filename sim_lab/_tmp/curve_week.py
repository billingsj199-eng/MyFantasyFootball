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
print("TOP 150 by NFL WEEK, all seasons 2019-25 pooled, importance-weighted. RMSE in half-PPR points; r = projection vs actual; last cols = weighted MSE change")
print(f"  {'week':>4s} {'n':>5s} | {'frozen prior':>18s} | {'Clay blend':>18s} | {'shadow v2.18':>18s} | {'shadow vs frozen':>16s} | {'shadow vs Clay':>14s} | seasons shadow beat Clay")
P0, PC, PS = M["preseason prior only (never updates)"], M["Clay blend (per-game)"], M["shadow v2.18 (usage evidence)"]
def st(p, m): return np.sqrt(np.average((p[m] - act[m]) ** 2, weights=wt[m])), np.corrcoef(p[m], act[m])[0, 1]
for w_ in range(1, 19):
    m = top150 & (wk == w_)
    if m.sum() < 100: continue
    a0, r0 = st(P0, m); ac, rc = st(PC, m); a1, r1 = st(PS, m); ys = sorted(set(year[m]))
    wins = sum(1 for y in ys if np.average((PS[m & (year == y)] - act[m & (year == y)]) ** 2, weights=wt[m & (year == y)]) < np.average((PC[m & (year == y)] - act[m & (year == y)]) ** 2, weights=wt[m & (year == y)]))
    print(f"  {w_:4d} {m.sum():5d} | RMSE {a0:5.2f} r {r0:.3f} | RMSE {ac:5.2f} r {rc:.3f} | RMSE {a1:5.2f} r {r1:.3f} | {((a1/a0)**2-1)*100:+15.2f}% | {((a1/ac)**2-1)*100:+13.2f}% | {wins}/{len(ys)}")
for lab, lo_, hi_ in (("weeks 1-4", 1, 4), ("weeks 5-9", 5, 9), ("weeks 10-14", 10, 14), ("weeks 15-18", 15, 18)):
    m = top150 & (wk >= lo_) & (wk <= hi_); a0, r0 = st(P0, m); ac, rc = st(PC, m); a1, r1 = st(PS, m)
    print(f"  {lab:>11s} n={m.sum():5d} | frozen r {r0:.3f} | Clay r {rc:.3f} | shadow r {r1:.3f} | shadow vs frozen {((a1/a0)**2-1)*100:+.2f}% | shadow vs Clay {((a1/ac)**2-1)*100:+.2f}%")
