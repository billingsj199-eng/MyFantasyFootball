import sys, numpy as np
sys.path.insert(0, ".")
import backtest_season_long as SL, backtest_top150_weighted as TW, backtest_opp_prior as OP
OP.P = lambda *a: None
T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]
pos_of, _, _ = OP.load_positions(); SEAS = {Y: OP.load_season(Y, pos_of)[0] for Y in range(SL.YEARS[0] - 1, SL.YEARS[-1] + 1)}
n = len(T); tg = np.full(n, np.nan); car = np.full(n, np.nan); tgp = np.full(n, np.nan); carp = np.full(n, np.nan)
for i, r in enumerate(T.itertuples(index=False)):
    c = SEAS[int(r.year)].get(r.pid); p = SEAS[int(r.year) - 1].get(r.pid)
    if c and c["g"] >= 4: tg[i] = c["tg"] / c["g"]; car[i] = c["car"] / c["g"]
    if p and p["g"] >= 4: tgp[i] = p["tg"] / p["g"]; carp[i] = p["car"] / p["g"]
act, g, yr, adp, pos, clay, hand = T.ppg.values, T.games.values.astype(float), T.year.values, T.adp.values, T.pos.values, T.clay.values, T.prior.values
lo = SL.loyo(T, LIVE, "ridge", 10.0); ours = np.where(np.isnan(lo), hand, np.where(pos == "QB", hand, 0.5 * lo + 0.5 * hand))
lv = TW.level_of(T); top150 = adp <= 150; rel = lv.copy()
for ps in SL.POS4:
    m = pos == ps; rel[m] = lv[m] / np.average(lv[m & top150], weights=g[m & top150])
wg = g * rel ** 2
def wm(p, m): return SL.wmse(p[m], act[m], wg[m])
# league-average efficiency model: ppg = a + b*targets/g + c*carries/g, fit LOYO per position on ACTUAL volume
oracle = np.full(n, np.nan); lastyr = np.full(n, np.nan); half = np.full(n, np.nan)
for ps in ("RB", "WR", "TE"):
    for y in SL.YEARS:
        tr = (pos == ps) & (yr != y) & ~np.isnan(tg); te = (pos == ps) & (yr == y)
        X = np.column_stack([np.ones(tr.sum()), tg[tr], car[tr]]); b = np.linalg.lstsq(X * np.sqrt(g[tr])[:, None], act[tr] * np.sqrt(g[tr]), rcond=None)[0]
        ok = te & ~np.isnan(tg); oracle[ok] = b[0] + b[1] * tg[ok] + b[2] * car[ok]
        okp = te & ~np.isnan(tgp); lastyr[okp] = b[0] + b[1] * tgp[okp] + b[2] * carp[okp]
        okh = ok & okp; half[okh] = b[0] + b[1] * (0.5 * tg[okh] + 0.5 * tgp[okh]) + b[2] * (0.5 * car[okh] + 0.5 * carp[okh])
sk = (pos != "QB") & ~np.isnan(oracle) & ~np.isnan(lastyr)
print("ORACLE TEST, RB/WR/TE with volume both years. Importance-weighted MSE; lower = better. 'true volume' uses the season's ACTUAL targets and carries per game with league-average efficiency only.")
print(f"  {'cut':22s} {'n':>4s} {'Clay':>7s} {'ours':>7s} {'last yr vol':>12s} {'half-way vol':>13s} {'TRUE volume':>12s} | ours vs Clay | true-vol vs Clay")
for lab, m in (("top 60", sk & (adp <= 60)), ("ADP 61-100", sk & (adp > 60) & (adp <= 100)), ("ADP 101-150", sk & (adp > 100) & (adp <= 150)), ("top 150", sk & top150), ("top 60 RB", sk & (adp <= 60) & (pos == "RB")), ("top 60 WR", sk & (adp <= 60) & (pos == "WR")), ("top 150 TE", sk & top150 & (pos == "TE"))):
    print(f"  {lab:22s} {m.sum():4d} {wm(clay, m):7.2f} {wm(ours, m):7.2f} {wm(lastyr, m):12.2f} {wm(half, m):13.2f} {wm(oracle, m):12.2f} | {(wm(ours, m)/wm(clay, m)-1)*100:+11.1f}% | {(wm(oracle, m)/wm(clay, m)-1)*100:+.1f}%")
# how much did volume actually move, and who saw it coming
m = sk & (adp <= 60); dv = (tg - tgp) + (car - carp)
print(f"\nTop-60 RB/WR/TE: |change in touches+targets per game| mean {np.abs(dv[m]).mean():.2f}; corr of the volume change with (Clay - ours) {np.corrcoef(dv[m], (clay - ours)[m])[0,1]:+.2f}; with (actual - ours) {np.corrcoef(dv[m], (act - ours)[m])[0,1]:+.2f}; with (actual - Clay) {np.corrcoef(dv[m], (act - clay)[m])[0,1]:+.2f}")
up = m & (dv >= 3); dn = m & (dv <= -3); fl = m & (np.abs(dv) < 3)
for lab, mm in (("volume UP 3+/g", up), ("volume flat", fl), ("volume DOWN 3+/g", dn)):
    print(f"  {lab:18s} n={mm.sum():3d} | actual {np.average(act[mm], weights=g[mm]):5.2f} | Clay {np.average(clay[mm], weights=g[mm]):5.2f} | ours {np.average(ours[mm], weights=g[mm]):5.2f} | MSE Clay {wm(clay, mm):5.2f} ours {wm(ours, mm):5.2f}")
# residual after true volume = efficiency + TDs
res = act - oracle; print(f"\nWhat is left once volume is known (top 150): sd of the residual {np.sqrt(np.average(res[sk & top150]**2, weights=g[sk & top150])):.2f} PPG vs sd of our current error {np.sqrt(np.average((act-ours)[sk & top150]**2, weights=g[sk & top150])):.2f} and Clay's {np.sqrt(np.average((act-clay)[sk & top150]**2, weights=g[sk & top150])):.2f}")
