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
from scipy.stats import spearmanr
TOPN = {"QB": 12, "RB": 24, "WR": 24, "TE": 12}
MODELS = {"frozen": M["preseason prior only (never updates)"], "Clay": M["Clay blend (per-game)"], "shadow": M["shadow v2.18 (usage evidence)"]}
def week_stats(w_lo, w_hi, pos_filter=None):
    out = {k: {"rho": [], "hit": [], "pw": [0, 0], "pwc": [0, 0]} for k in MODELS}
    for y in sorted(set(year)):
        for w_ in range(w_lo, w_hi + 1):
            for ps in (pos_filter or NW.POS4):
                m = top150 & (year == y) & (wk == w_) & (pos == ps); idx = np.where(m)[0]
                if len(idx) < 8: continue
                a = act[idx]; N = min(TOPN[ps], len(idx) // 2); top_act = set(idx[np.argsort(-a)[:N]])
                for k, p in MODELS.items():
                    pv = p[idx]; out[k]["rho"].append(spearmanr(pv, a).correlation)
                    out[k]["hit"].append(len(top_act & set(idx[np.argsort(-pv)[:N]])) / N)
                    # pairwise: all pairs, and CLOSE pairs (projections within 3 points) = real start/sit decisions
                    d = pv[:, None] - pv[None, :]; o = a[:, None] - a[None, :]; iu = np.triu_indices(len(idx), 1)
                    dd, oo = d[iu], o[iu]; ok = (dd != 0) & (oo != 0)
                    out[k]["pw"][0] += int(((dd > 0) == (oo > 0))[ok].sum()); out[k]["pw"][1] += int(ok.sum())
                    cl = ok & (np.abs(dd) <= 3); out[k]["pwc"][0] += int(((dd > 0) == (oo > 0))[cl].sum()); out[k]["pwc"][1] += int(cl.sum())
    return out
print("RANK ACCURACY by NFL week, top 150, within position, averaged over seasons 2019-25. rho = Spearman; hit = share of the actual top 12 QB/TE, top 24 RB/WR the projection had in its own top group;")
print("pair = % of same-position player pairs ordered correctly; close = same, only pairs projected within 3 points (the real start/sit calls)")
print(f"  {'week':>5s} | {'rho frozen / Clay / shadow':>28s} | {'top-N hit frozen / Clay / shadow':>34s} | {'pair % frozen / Clay / shadow':>30s} | {'close-pair % frozen / Clay / shadow':>36s}")
def line(lab, S):
    f = lambda key: " / ".join(f"{np.mean(S[k][key]):.3f}" for k in MODELS); g2 = lambda key: " / ".join(f"{100*S[k][key][0]/max(1,S[k][key][1]):5.1f}" for k in MODELS)
    print(f"  {lab:>5s} | {f('rho'):>28s} | {f('hit'):>34s} | {g2('pw'):>30s} | {g2('pwc'):>36s}")
for w_ in range(1, 19): line(str(w_), week_stats(w_, w_))
print("  blocks:")
for lab, a_, b_ in (("1-4", 1, 4), ("5-9", 5, 9), ("10-14", 10, 14), ("15-18", 15, 18), ("ALL", 1, 18)): line(lab, week_stats(a_, b_))
print("  by position, all weeks:")
for ps in NW.POS4: line(ps, week_stats(1, 18, [ps]))
S = week_stats(1, 18); n = S["shadow"]["pwc"][1]
print(f"\nclose pairs graded: {n:,}; shadow vs Clay on close pairs: {100*S['shadow']['pwc'][0]/n:.2f}% vs {100*S['Clay']['pwc'][0]/n:.2f}% (a coin flip is 50%)")
