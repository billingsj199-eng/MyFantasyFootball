import sys, numpy as np
sys.path.insert(0, ".")
import backtest_noclay_weekly as NW, backtest_season_long as SL
from backtest_target_area import mse
T, F = SL.build_table(return_F=True); A = F["A"]; n = F["n"]
act, year, wk, pos, g, ppg = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"]
ship, ref, prior, layers, Pvec, buried_rk, on, pm = F["shipped"], F["shadow"], F["prior"], F["layers"], F["Pvec"], F["buried_rk"], F["on"], F["pm"]
fw = SL.forward(T, SL.BASIC, "ridge", 10.0)
key = {(int(y), nm, ps): b for y, nm, ps, b in zip(T.year, T.name, T.pos, fw)}
r_fw = np.array([key.get((year[i], A["name"][i], pos[i]), np.nan) for i in range(n)]); hasf = ~np.isnan(r_fw)
def build(pr):
    out = NW.blend(pr, g, ppg, Pvec) * layers
    for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(buried_rk & (wk == gi), out * m_, out)
    return np.where(on, out * np.power(pm, 0.75), out)
YEARS = NW.YEARS
print("FORWARD by mix a (fit on earlier seasons only), vs shadow / vs Clay blend; per-year vs shadow")
for a in (0.25, 0.5, 0.75, 1.0):
    cand = build(np.where(hasf, a * r_fw + (1 - a) * prior, prior)); fm = year >= YEARS[2]
    for lab, m in (("ALL", fm), ("week 1", fm & (g == 0)), ("games 1-3", fm & (g >= 1) & (g <= 3)), ("games 4+", fm & (g >= 4))):
        pv, wv, ny = NW.pct_vs(cand[m], ref[m], act[m], year[m]); pc, wc, _ = NW.pct_vs(cand[m], ship[m], act[m], year[m])
        per = " ".join(f"{y}:{(mse(cand[m & (year == y)], act[m & (year == y)]) / mse(ref[m & (year == y)], act[m & (year == y)]) - 1) * 100:+.1f}" for y in YEARS[2:])
        print(f"  a={a:<4} {lab:10s} n={m.sum():5d} vs shadow {pv:+.2f}% ({wv}/{ny}) vs Clay {pc:+.2f}% ({wc}/{ny}) | by year {per}")
# how big is the training set per position in each forward year
for y in YEARS[2:]: print(f"  train rows before {y}: " + " ".join(f"{ps} {int(((T.pos == ps) & (T.year < y)).sum())}" for ps in ("QB", "RB", "WR", "TE")))
