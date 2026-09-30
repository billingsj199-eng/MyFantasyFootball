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
from scipy.stats import rankdata
PS = M["shadow v2.18 (usage evidence)"]; PC = M["Clay blend (per-game)"]
qbo = np.where(idx >= 0, C.qb_out.values[np.maximum(idx, 0)], np.nan).astype(float); out = (qbo == 1) & (pos == "WR")
PD = np.where(out, PS * 0.85, PS)
groups = defaultdict(list)
for i in np.where(top150 & (pos == "WR"))[0]: groups[(int(year[i]), int(wk[i]))].append(i)
def pairs(pred, only_mixed):
    res = {}
    for y in NW.YEARS:
        w_ = t_ = 0
        for (yy, w), ix in groups.items():
            if yy != y: continue
            ix = np.array(ix); a = act[ix]; p = pred[ix]; o_ = out[ix]
            d = p[:, None] - p[None, :]; oo = a[:, None] - a[None, :]; mix = o_[:, None] != o_[None, :]; iu = np.triu_indices(len(ix), 1)
            ok = (d[iu] != 0) & (oo[iu] != 0) & (mix[iu] if only_mixed else True)
            w_ += int(((d[iu] > 0) == (oo[iu] > 0))[ok].sum()); t_ += int(ok.sum())
        res[y] = (w_, t_)
    return res
for lab, mixed in (("pairs with exactly ONE receiver on a backup QB (the affected start/sit calls)", True), ("ALL top-150 WR pairs", False)):
    b, a = pairs(PS, mixed), pairs(PD, mixed); tb = sum(v[0] for v in b.values()); ta = sum(v[0] for v in a.values()); n_ = sum(v[1] for v in b.values())
    wins = sum(1 for y in NW.YEARS if a[y][0] / max(1, a[y][1]) > b[y][0] / max(1, b[y][1]))
    print(f"{lab}: {n_:,} pairs | ordered correctly {100*tb/n_:.2f}% -> {100*ta/n_:.2f}% ({100*(ta-tb)/n_:+.2f} pts; {ta-tb:+,d} pairs) | better in {wins}/7 seasons")
# rank correlation in the weeks that contain at least one affected WR, and rank of the affected WRs themselves
rb, ra, nb = [], [], 0
for (y, w), ix in groups.items():
    ix = np.array(ix)
    if out[ix].sum() == 0 or len(ix) < 8: continue
    rb.append(np.corrcoef(rankdata(act[ix]), rankdata(PS[ix]))[0, 1]); ra.append(np.corrcoef(rankdata(act[ix]), rankdata(PD[ix]))[0, 1]); nb += 1
print(f"WR weeks containing at least one backup-QB receiver: {nb} | mean within-week Spearman {np.mean(rb):.4f} -> {np.mean(ra):.4f} ({np.mean(ra)-np.mean(rb):+.4f})")
m = out & top150; e0 = np.sqrt(np.average((PS[m]-act[m])**2, weights=wt[m])); e1 = np.sqrt(np.average((PD[m]-act[m])**2, weights=wt[m])); ec = np.sqrt(np.average((PC[m]-act[m])**2, weights=wt[m]))
print(f"On the {m.sum()} affected receiver-weeks: typical miss {e0:.2f} -> {e1:.2f} points (Clay blend {ec:.2f}); average projection {PS[m].mean():.2f} -> {PD[m].mean():.2f} vs actual {act[m].mean():.2f}")
hi = m & (adp <= 60); print(f"  top-60 receivers among them ({hi.sum()}): projection {PS[hi].mean():.2f} -> {PD[hi].mean():.2f} vs actual {act[hi].mean():.2f}")
