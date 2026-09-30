import sys, numpy as np
sys.path.insert(0, ".")
import backtest_season_long as SL, backtest_top150_weighted as TW
T = SL.build_table(); LIVE = TW.LIVE
act, g, yr, adp, pos, clay, hand, exp = T.ppg.values, T.games.values.astype(float), T.year.values, T.adp.values, T.pos.values, T.clay.values, T.prior.values, T.exp.values
lv = TW.level_of(T); top150 = adp <= 150; rel = lv.copy()
for ps in SL.POS4:
    m = pos == ps; rel[m] = lv[m] / np.average(lv[m & top150], weights=g[m & top150])
wg = g * rel ** 2; jm = T.jm.values; young = exp <= 2
def wm(p, m): return SL.wmse(p[m], act[m], wg[m])
fw0 = SL.forward(T, LIVE, "ridge", 10.0); b = np.where(np.isnan(fw0), hand, 0.5 * fw0 + 0.5 * hand)
fw1 = SL.forward(T, LIVE + ["jm"], "ridge", 10.0); j = np.where(np.isnan(fw1), hand, 0.5 * fw1 + 0.5 * hand)
lo0 = SL.loyo(T, LIVE, "ridge", 10.0); lb = np.where(np.isnan(lo0), hand, 0.5 * lo0 + 0.5 * hand)
lo1 = SL.loyo(T, LIVE + ["jm"], "ridge", 10.0); lj = np.where(np.isnan(lo1), hand, 0.5 * lo1 + 0.5 * hand)
print("1) +JM gain by season (importance-weighted MSE change vs v2.15; negative = JM helps). Hindsight is strongest for the oldest classes.")
print(f"  {'season':8s} {'LOYO top150':>12s} {'LOYO young':>11s} {'FWD top150':>11s} {'FWD young':>10s}   n top150 / young")
for y in SL.YEARS:
    m = top150 & (yr == y); my = m & young
    f = lambda a, c, mm: f"{(wm(a, mm)/wm(c, mm)-1)*100:+6.2f}%" if mm.sum() >= 10 else "   -   "
    print(f"  {y:<8d} {f(lj, lb, m):>12s} {f(lj, lb, my):>11s} {f(j, b, m) if y >= SL.YEARS[2] else '     -':>11s} {f(j, b, my) if y >= SL.YEARS[2] else '     -':>10s}   {m.sum()} / {my.sum()}")
print("\n2) Draft-class view: JM's partial correlation with actual PPG after the base prior (residual act - v2.15), young players in the top 150, by DRAFT year")
dy = (yr - exp).astype(int); res = act - lb
for cls in range(2017, 2026):
    m = top150 & young & (dy == cls) & ~np.isnan(jm)
    if m.sum() >= 12: print(f"  class {cls}: n={m.sum():3d} corr(JM, residual) {np.corrcoef(jm[m], res[m])[0,1]:+.3f} | corr(JM, actual) {np.corrcoef(jm[m], act[m])[0,1]:+.3f} | corr(JM, log pick) {np.corrcoef(jm[m], T.lpick.values[m])[0,1]:+.3f}")
print("\n3) Who moves: top-150 young players where +JM shifts the LOYO prior by 1+ PPG")
d = lj - lb; mm = top150 & young & (np.abs(d) >= 1.0)
for i in np.argsort(-np.abs(d * mm))[:14]:
    if not mm[i]: break
    r = T.iloc[i]; print(f"  {int(r.year)} {r['name']:22s} {r.pos} adp {r.adp:4.0f} exp {int(r.exp)} JM {r.jm:5.1f} | v2.15 {lb[i]:5.1f} -> +JM {lj[i]:5.1f} | act {r.ppg:5.1f} Clay {r.clay:5.1f}")
