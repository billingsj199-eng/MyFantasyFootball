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
from collections import defaultdict
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
PC, PS = M["Clay blend (per-game)"], M["shadow v2.18 (usage evidence)"]
eS, eC = (PS - act) ** 2, (PC - act) ** 2; T150 = top150
def seg(lab, m):
    m = m & T150
    if m.sum() < 150: return
    ys = sorted(set(year[m])); w = sum(1 for y in ys if np.average(eS[m & (year == y)], weights=wt[m & (year == y)]) < np.average(eC[m & (year == y)], weights=wt[m & (year == y)]))
    pct = (np.average(eS[m], weights=wt[m]) / np.average(eC[m], weights=wt[m]) - 1) * 100
    flag = "  <-- CLAY WINS" if (pct > 0.5 and w <= len(ys) / 2) else ("  (shadow strong)" if pct < -2.5 and w >= 5 else "")
    print(f"    {lab:44s} n={m.sum():5d} | shadow vs Clay {pct:+6.2f}% | seasons shadow better {w}/{len(ys)}{flag}")
exp, age = A["exp"], A["age"]; strb, mkt = F["strb"], F["adp_curve"]; gap = PS - PC; hot = ppg - prior
W_ = np.where(year <= 2020, 16.0, 17.0)
print("1) WHERE does the shadow lose? top 150, importance-weighted MSE vs the per-game Clay blend, by player type (negative = shadow better)")
fams = [
 ("position x ADP tier", [(f"{ps} ADP {lab}", (pos == ps) & mm) for ps in NW.POS4 for lab, mm in (("1-60", adp <= 60), ("61-150", (adp > 60) & (adp <= 150)))]),
 ("experience", [("rookie", exp == 0), ("2nd year", exp == 1), ("3rd year", exp == 2), ("years 4-6", (exp >= 3) & (exp <= 5)), ("year 7+", exp >= 6)]),
 ("age", [("age <= 23", age <= 23), ("24-26", (age > 23) & (age <= 26)), ("27-29", (age > 26) & (age <= 29)), ("30+", age > 29)]),
 ("depth chart string this week", [("string 1", strb == 1), ("string 2", strb == 2), ("string 3+", strb >= 3), ("not on the chart", np.isnan(strb))]),
 ("which way we differ from Clay", [("shadow HIGHER than Clay by 1.5+", gap >= 1.5), ("within 1.5", np.abs(gap) < 1.5), ("shadow LOWER than Clay by 1.5+", gap <= -1.5)]),
 ("season-to-date form vs our prior (3+ games)", [("running HOT: ppg 3+ over prior", (g >= 3) & (hot >= 3)), ("near prior", (g >= 3) & (np.abs(hot) < 3)), ("running COLD: ppg 3+ under prior", (g >= 3) & (hot <= -3))]),
 ("Clay's projected games", [("Clay projects a full season", gm >= W_ - 1), ("Clay projects 2+ missed games", (gm >= 4) & (gm < W_ - 1))]),
 ("game environment (live layers)", [("layers boost the player (> 1.08)", layers > 1.08), ("neutral", (layers >= 0.93) & (layers <= 1.08)), ("layers dock the player (< 0.93)", layers < 0.93)]),
 ("vacated-role week", [("teammate out, role redistributed", F["on"]), ("normal week", ~F["on"])]),
 ("Clay's own level", [("Clay top quartile at the position", np.zeros(n, bool)), ]),
]
cq = np.zeros(n, bool); cl = np.zeros(n, bool)
for ps in NW.POS4:
    m = (pos == ps) & T150; q75, q25 = np.percentile(clay_gm[m], 75), np.percentile(clay_gm[m], 25); cq |= (pos == ps) & (clay_gm >= q75); cl |= (pos == ps) & (clay_gm <= q25)
fams[-1] = ("Clay's own preseason level", [("Clay top quartile at the position", cq), ("Clay middle half", ~cq & ~cl), ("Clay bottom quartile", cl)])
for title, segs in fams:
    print(f"  -- {title}")
    for lab, m in segs: seg(lab, m)
# 2) persistence: is there such a thing as a 'Clay player'?
print("\n2) Does the SAME player keep losing? per player-season mean loss (shadow err - Clay err), odd weeks vs even weeks; and player in season Y vs Y+1")
d = (eS - eC) * wt; acc = defaultdict(lambda: [[], []]); py = defaultdict(list)
for i in np.where(T150)[0]:
    k = (int(year[i]), A["name"][i], pos[i]); acc[k][int(wk[i]) % 2].append(d[i]); py[k].append(d[i])
odd = []; even = []
for k, (e_, o_) in acc.items():
    if len(e_) >= 5 and len(o_) >= 5: even.append(np.mean(e_)); odd.append(np.mean(o_))
print(f"    within a season, odd vs even weeks: r = {np.corrcoef(odd, even)[0,1]:+.3f} over {len(odd)} player-seasons (0 = random, 1 = the same players always lose)")
a_, b_ = [], []
for (y, nm, ps), v in py.items():
    v2 = py.get((y + 1, nm, ps))
    if v2 and len(v) >= 8 and len(v2) >= 8: a_.append(np.mean(v)); b_.append(np.mean(v2))
print(f"    same player, season Y vs Y+1:       r = {np.corrcoef(a_, b_)[0,1]:+.3f} over {len(a_)} player pairs")
# 3) predictability: can anything known beforehand predict which model wins the row?
print("\n3) Can we PREDICT which model will be closer? logistic model, leave-one-season-out, on everything known before the game")
X = np.column_stack([gap, np.abs(gap), PS, PC, g, np.nan_to_num(hot), np.nan_to_num(exp, nan=3), np.nan_to_num(age, nan=26), np.nan_to_num(np.log(np.where(np.isnan(adp), 181, adp))), layers, np.nan_to_num(strb, nan=4), F["on"].astype(float), (gm < W_ - 1).astype(float)] + [(pos == ps).astype(float) for ps in NW.POS4])
yb = (eS < eC).astype(int); aucs = []
for y in sorted(set(year)):
    tr = T150 & (year != y); te = T150 & (year == y); mu, sd = X[tr].mean(0), X[tr].std(0); sd[sd == 0] = 1
    mdl = LogisticRegression(C=0.5, max_iter=500).fit((X[tr] - mu) / sd, yb[tr], sample_weight=wt[tr]); aucs.append(roc_auc_score(yb[te], mdl.predict_proba((X[te] - mu) / sd)[:, 1]))
print(f"    out-of-sample AUC by season: {[round(a, 3) for a in aucs]} | mean {np.mean(aucs):.3f}  (0.500 = cannot be predicted; 0.55+ would be usable)")
print(f"    base rate: the shadow is the closer of the two on {yb[T150].mean()*100:.1f}% of top-150 player-weeks")
# 4) the biggest individual player-seasons each way
print("\n4) Largest player-season swings (sum of weighted loss; + = Clay better). Top 8 each way:")
tot = sorted(((np.sum(v), len(v), k) for k, v in py.items() if len(v) >= 8), key=lambda t: t[0])
for s_, n_, k in tot[-8:][::-1]: print(f"    Clay better   {k[0]} {k[1]:22s} {k[2]} weeks {n_:2d} | summed loss {s_:+8.1f}")
for s_, n_, k in tot[:8]: print(f"    shadow better {k[0]} {k[1]:22s} {k[2]} weeks {n_:2d} | summed loss {s_:+8.1f}")
