import sys, numpy as np
sys.path.insert(0, ".")
import backtest_season_long as SL, backtest_top150_weighted as TW
T = SL.build_table(); LIVE = TW.LIVE
act, g, yr, adp, pos, clay, hand = T.ppg.values, T.games.values.astype(float), T.year.values, T.adp.values, T.pos.values, T.clay.values, T.prior.values
lv = TW.level_of(T); top150 = adp <= 150; rel = lv.copy()
for ps in SL.POS4:
    m = pos == ps; rel[m] = lv[m] / np.average(lv[m & top150], weights=g[m & top150])
wg = g * rel ** 2; wfit = g * rel   # LEVEL^1 fit weights (the best-behaved variant)
young = (T.exp <= 2).astype(float).values; jm = T.jm.values
T["jm_young"] = np.where(np.isnan(jm), np.nan, jm * young); T["jm_rookie"] = np.where(np.isnan(jm), np.nan, jm * T.rookie.values); T["jm_yr23"] = np.where(np.isnan(jm), np.nan, jm * ((T.exp >= 1) & (T.exp <= 2)).astype(float).values)
T["jm_x_ladp"] = np.where(np.isnan(jm), np.nan, jm * T.ladp.values)
def wm(p, m): return SL.wmse(p[m], act[m], wg[m])
def grade(label, pred, base, fm=None):
    out = []
    for lab, m in (("top 60", adp <= 60), ("61-100", (adp > 60) & (adp <= 100)), ("101-150", (adp > 100) & (adp <= 150)), ("top 150", top150), ("young top 150", top150 & (young == 1))):
        mm = m & ~np.isnan(pred) & ~np.isnan(base) & (fm if fm is not None else True); ys = [y for y in SL.YEARS if (mm & (yr == y)).sum() >= 10]
        wb = sum(1 for y in ys if wm(pred, mm & (yr == y)) < wm(base, mm & (yr == y))); wc = sum(1 for y in ys if wm(pred, mm & (yr == y)) < wm(clay, mm & (yr == y)))
        out.append(f"{lab} {(wm(pred, mm)/wm(clay, mm)-1)*100:+5.1f}% vs Clay ({wc}/{len(ys)}) [{(wm(pred, mm)/wm(base, mm)-1)*100:+5.2f}% vs base {wb}/{len(ys)}]")
    print(f"  {label:34s} " + " | ".join(out))
print("Prospect model (JM) in the season prior - importance-weighted MSE, 50/50 mix with the hand prior; base = current v2.15")
lo0 = SL.loyo(T, LIVE, "ridge", 10.0); base = np.where(np.isnan(lo0), hand, 0.5 * lo0 + 0.5 * hand)
print("--- LOYO ---"); grade("v2.15 (no JM)", base, base)
SETS = {"+ jm": LIVE + ["jm"], "+ jm x young (exp<=2)": LIVE + ["jm_young"], "+ jm x rookie": LIVE + ["jm_rookie"], "+ jm x yr2-3": LIVE + ["jm_yr23"], "+ jm + jm x young + jm x ADP": LIVE + ["jm", "jm_young", "jm_x_ladp"]}
for nm, fs in SETS.items():
    lo = SL.loyo(T, fs, "ridge", 10.0); grade(nm, np.where(np.isnan(lo), hand, 0.5 * lo + 0.5 * hand), base)
    lo = TW.loyo_w(T, fs, wfit); grade(nm + " (weighted fit)", np.where(np.isnan(lo), hand, 0.5 * lo + 0.5 * hand), base)
print("--- FORWARD 2021-25 ---"); fm = yr >= SL.YEARS[2]
fw0 = SL.forward(T, LIVE, "ridge", 10.0); basef = np.where(np.isnan(fw0), hand, 0.5 * fw0 + 0.5 * hand); grade("v2.15 (no JM)", basef, basef, fm)
for nm, fs in SETS.items():
    fw = SL.forward(T, fs, "ridge", 10.0); grade(nm, np.where(np.isnan(fw), hand, 0.5 * fw + 0.5 * hand), basef, fm)
# standardized coefficient of JM on the whole sample per position
print("--- JM standardized coefficient (full-sample ridge with LIVE + jm), per position ---")
from sklearn.linear_model import Ridge
for ps in SL.POS4:
    m = (pos == ps) & ~np.isnan(jm); X = T.loc[m, LIVE + ["jm"]].astype(float).values; med = np.nanmedian(X, 0); X = np.where(np.isnan(X), med, X); mu, sd = X.mean(0), X.std(0); sd[sd == 0] = 1
    r = Ridge(alpha=10).fit((X - mu) / sd, act[m], sample_weight=g[m]); print(f"  {ps}: jm coef {r.coef_[-1]:+.2f} (hist {r.coef_[LIVE.index('hist')]:+.2f}, ladp {r.coef_[LIVE.index('ladp')]:+.2f}, lpick {r.coef_[LIVE.index('lpick')]:+.2f}) n={m.sum()}")
