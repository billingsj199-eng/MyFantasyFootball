import sys, numpy as np
sys.path.insert(0, ".")
import backtest_season_long as SL
T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"]
clay, act, g, yr, adp, pos = T.clay.values, T.ppg.values, T.games.values.astype(float), T.year.values, T.adp.values, T.pos.values
lo = SL.loyo(T, LIVE, "ridge", 10.0); hand = T.prior.values; sh = np.where(np.isnan(lo), hand, 0.5 * lo + 0.5 * hand)
tiers = (("top 60", adp <= 60), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150", (adp > 100) & (adp <= 150)), ("top 150", adp <= 150), ("151+ / unlisted", ~(adp <= 150)), ("ALL", np.ones(len(T), bool)))
print("1) Bias by tier = games-weighted actual / prediction (1.00 = calibrated; > 1 = we are low)")
print(f"  {'tier':16s} {'hand prior':>11s} {'ridge':>8s} {'shadow v2.15':>13s} {'Clay':>7s}")
for lab, m in tiers:
    f = lambda p: np.average(act[m], weights=g[m]) / np.average(p[m], weights=g[m])
    print(f"  {lab:16s} {f(hand):11.3f} {f(lo):8.3f} {f(sh):13.3f} {f(clay):7.3f}")
print("\n   by position, top 150:")
for ps in SL.POS4:
    m = (adp <= 150) & (pos == ps); f = lambda p: np.average(act[m], weights=g[m]) / np.average(p[m], weights=g[m])
    print(f"  {ps:16s} {f(hand):11.3f} {f(lo):8.3f} {f(sh):13.3f} {f(clay):7.3f}")
print("\n2) Slope of actual on prediction (1.0 = right spread; < 1 = predictions too spread; > 1 = too compressed), all rows per position")
for ps in SL.POS4:
    m = pos == ps; w = np.sqrt(g[m])
    print(f"  {ps}: hand {np.polyfit(hand[m], act[m], 1, w=w)[0]:.2f} | ridge {np.polyfit(lo[m], act[m], 1, w=w)[0]:.2f} | shadow {np.polyfit(sh[m], act[m], 1, w=w)[0]:.2f} | Clay {np.polyfit(clay[m], act[m], 1, w=w)[0]:.2f}")
# 3) LOYO recalibration: per position fit act = a + b*shadow on the other years (all rows / top-150 rows), apply to held-out year
def recal(pred, sel):
    out = pred.copy()
    for ps in SL.POS4:
        for y in SL.YEARS:
            tr = (pos == ps) & (yr != y) & sel; te = (pos == ps) & (yr == y)
            b, a = np.polyfit(pred[tr], act[tr], 1, w=np.sqrt(g[tr])); out[te] = np.maximum(0.5, a + b * pred[te])
    return out
def recal_tier(pred):
    out = pred.copy(); bands = ((adp <= 60), (adp > 60) & (adp <= 150), ~(adp <= 150))
    for ps in SL.POS4:
        for bm in bands:
            for y in SL.YEARS:
                tr = (pos == ps) & (yr != y) & bm; te = (pos == ps) & (yr == y) & bm
                if tr.sum() < 25: continue
                b, a = np.polyfit(pred[tr], act[tr], 1, w=np.sqrt(g[tr])); out[te] = np.maximum(0.5, a + b * pred[te])
    return out
cands = {"shadow v2.15 as is": sh, "recal on all rows": recal(sh, np.ones(len(T), bool)), "recal on top-150 rows": recal(sh, adp <= 150), "recal by ADP band (1-60 / 61-150 / 151+)": recal_tier(sh)}
print("\n3) LOYO linear recalibration of the shadow prior (per position), graded by tier vs Clay")
for lab, m in tiers[:4]:
    print(f"  --- {lab}")
    ec = SL.wmse(clay[m], act[m], g[m])
    for nm, p in cands.items():
        e = SL.wmse(p[m], act[m], g[m]); ys = [y for y in SL.YEARS if (m & (yr == y)).sum() >= 12]; w = sum(1 for y in ys if SL.wmse(p[m & (yr == y)], act[m & (yr == y)], g[m & (yr == y)]) < SL.wmse(clay[m & (yr == y)], act[m & (yr == y)], g[m & (yr == y)]))
        print(f"     {nm:42s} MSE {e:6.2f} vs Clay {ec:6.2f} ({(e/ec-1)*100:+6.2f}%, {w}/{len(ys)}) | bias {np.average(act[m], weights=g[m])/np.average(p[m], weights=g[m]):.3f}")
