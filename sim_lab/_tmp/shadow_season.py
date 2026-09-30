import sys, numpy as np
sys.path.insert(0, ".")
import backtest_season_long as SL
T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"]
lo = SL.loyo(T, LIVE, "ridge", 10.0); fw = SL.forward(T, LIVE, "ridge", 10.0)
hand = T.prior.values; clay = T.clay.values; act = T.ppg.values; g = T.games.values.astype(float); yr = T.year.values; adp = T.adp.values
def mix(r): return np.where(np.isnan(r), hand, 0.5 * r + 0.5 * hand)
sh_lo, sh_fw = mix(lo), mix(fw)
def row(lab, pred, m):
    m = m & ~np.isnan(pred); ys = [y for y in SL.YEARS if (m & (yr == y)).sum() >= 12]
    e, ec = SL.wmse(pred[m], act[m], g[m]), SL.wmse(clay[m], act[m], g[m]); w = sum(1 for y in ys if SL.wmse(pred[m & (yr == y)], act[m & (yr == y)], g[m & (yr == y)]) < SL.wmse(clay[m & (yr == y)], act[m & (yr == y)], g[m & (yr == y)]))
    print(f"  {lab:34s} n={m.sum():4d} MSE {e:6.2f} vs Clay {ec:6.2f} ({(e/ec-1)*100:+6.2f}%) seasons won {w}/{len(ys)}")
tiers = (("ALL", np.ones(len(T), bool)), ("top 60", adp <= 60), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150", (adp > 100) & (adp <= 150)), ("top 150", adp <= 150), ("ADP 151+ / unlisted", ~(adp <= 150)))
print("SEASON-LONG: the v2.15 shadow preseason prior (0.5 ridge + 0.5 hand prior) vs Clay's season sheet (per-game), 2019-25")
print("--- leave-one-year-out ---")
for lab, m in tiers: row(lab, sh_lo, m)
for ps in SL.POS4: row(f"top 150 {ps}", sh_lo, (adp <= 150) & (T.pos.values == ps))
print("--- forward 2021-25 (ridge fit on earlier seasons only) ---")
fm = yr >= SL.YEARS[2]
for lab, m in tiers: row("forward " + lab, sh_fw, fm & m)
print("--- for reference: hand prior alone / ridge alone / 0.5 shadow + 0.5 Clay, top 150 LOYO ---")
row("hand prior alone, top 150", hand, adp <= 150); row("ridge alone, top 150", lo, adp <= 150); row("0.5 shadow + 0.5 Clay, top 150", 0.5 * sh_lo + 0.5 * clay, adp <= 150); row("0.5 shadow + 0.5 Clay, ALL", 0.5 * sh_lo + 0.5 * clay, np.ones(len(T), bool))
