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
PC, PS, P0 = M["Clay blend (per-game)"], M["shadow v2.18 (usage evidence)"], M["preseason prior only (never updates)"]
def disagree(w_lo, w_hi, positions, A_, B_, startable=False):
    win = tot = 0; per_year = {}
    for y in sorted(set(year)):
        wy = ty = 0
        for w_ in range(w_lo, w_hi + 1):
            for ps in positions:
                m = top150 & (year == y) & (wk == w_) & (pos == ps); idx = np.where(m)[0]
                if len(idx) < 8: continue
                if startable:
                    N = {"QB": 16, "RB": 36, "WR": 40, "TE": 16}[ps]; keep = np.argsort(-(A_[idx] + B_[idx]))[:N]; idx = idx[keep]
                a = act[idx]; da = A_[idx][:, None] - A_[idx][None, :]; db = B_[idx][:, None] - B_[idx][None, :]; o = a[:, None] - a[None, :]; iu = np.triu_indices(len(idx), 1)
                da, db, o = da[iu], db[iu], o[iu]; dis = (np.sign(da) != np.sign(db)) & (da != 0) & (db != 0) & (o != 0)
                wy += int(((da > 0) == (o > 0))[dis].sum()); ty += int(dis.sum())
        per_year[y] = (wy, ty); win += wy; tot += ty
    yrs = sum(1 for y, (a_, b_) in per_year.items() if b_ and a_ / b_ > 0.5)
    return win, tot, yrs, len([1 for v in per_year.values() if v[1]])
print("HEAD TO HEAD ON START/SIT: same-position pairs in the same week where the shadow and the Clay blend order the two players DIFFERENTLY. % = how often the shadow's order was right (50% = coin flip).")
for lab, a_, b_ in (("weeks 1-4", 1, 4), ("weeks 5-9", 5, 9), ("weeks 10-14", 10, 14), ("weeks 15-18", 15, 18), ("ALL weeks", 1, 18)):
    w, t, ys, ny = disagree(a_, b_, NW.POS4, PS, PC); w2, t2, ys2, _ = disagree(a_, b_, NW.POS4, PS, PC, startable=True)
    print(f"  {lab:12s} all top-150 pairs: shadow right {100*w/t:5.2f}% of {t:6,d} disagreements ({ys}/{ny} seasons > 50%) | startable players only: {100*w2/t2:5.2f}% of {t2:6,d} ({ys2}/{ny})")
for ps in NW.POS4:
    w, t, ys, ny = disagree(1, 18, [ps], PS, PC); w2, t2, ys2, _ = disagree(1, 18, [ps], PS, PC, startable=True)
    print(f"  {ps:12s} all pairs: {100*w/t:5.2f}% of {t:6,d} ({ys}/{ny}) | startable: {100*w2/t2:5.2f}% of {t2:6,d} ({ys2}/{ny})")
print("\nSame test, shadow vs its own FROZEN preseason prior (what the in-season updating is worth for ordering):")
for lab, a_, b_ in (("weeks 2-4", 2, 4), ("weeks 5-9", 5, 9), ("weeks 10-14", 10, 14), ("weeks 15-18", 15, 18)):
    w, t, ys, ny = disagree(a_, b_, NW.POS4, PS, P0); print(f"  {lab:12s} shadow right {100*w/t:5.2f}% of {t:6,d} disagreements ({ys}/{ny} seasons)")
