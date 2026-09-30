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
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
PC, PS = M["Clay blend (per-game)"], M["shadow v2.18 (usage evidence)"]; eS, eC = (PS - act) ** 2, (PC - act) ** 2; T150 = top150
gap = PS - PC; hot = np.nan_to_num(ppg - prior); W_ = np.where(year <= 2020, 16.0, 17.0); yb = (eS < eC).astype(int)
sets = {"gap only (shadow - Clay, and its size)": [gap, np.abs(gap)],
        "player type only (pos, ADP, exp, age, string, games, Clay games, vacated, layers, form)": [g, hot, np.nan_to_num(A["exp"], nan=3), np.nan_to_num(A["age"], nan=26), np.log(np.where(np.isnan(adp), 181, adp)), layers, np.nan_to_num(F["strb"], nan=4), F["on"].astype(float), (gm < W_ - 1).astype(float)] + [(pos == ps).astype(float) for ps in NW.POS4],
        "level only (the two projections)": [PS, PC]}
for lab, cols in sets.items():
    X = np.column_stack(cols); aucs = []
    for y in sorted(set(year)):
        tr = T150 & (year != y); te = T150 & (year == y); mu, sd = X[tr].mean(0), X[tr].std(0); sd[sd == 0] = 1
        mdl = LogisticRegression(C=0.5, max_iter=500).fit((X[tr] - mu) / sd, yb[tr]); aucs.append(roc_auc_score(yb[te], mdl.predict_proba((X[te] - mu) / sd)[:, 1]))
    print(f"  {lab:88s} mean out-of-sample AUC {np.mean(aucs):.3f}")
# the mechanical reason: whichever model is LOWER wins when the player busts, whichever is HIGHER wins when he booms
lowS = gap < 0; print(f"\n  shadow is the LOWER projection on {lowS[T150].mean()*100:.1f}% of rows. When it is lower it is closer {yb[T150 & lowS].mean()*100:.1f}% of the time; when it is higher, {yb[T150 & ~lowS].mean()*100:.1f}%.")
med = np.zeros(n)
print("  (weekly scores are right-skewed: most weeks land below the mean, so the lower projection is closer more often, whoever owns it)")
for lab, m in (("actual landed BELOW both projections", act < np.minimum(PS, PC)), ("actual landed BETWEEN them", (act >= np.minimum(PS, PC)) & (act <= np.maximum(PS, PC))), ("actual landed ABOVE both", act > np.maximum(PS, PC))):
    mm = T150 & m; print(f"    {lab:38s} {mm.sum()/T150.sum()*100:5.1f}% of rows | shadow closer {yb[mm].mean()*100:5.1f}%")
