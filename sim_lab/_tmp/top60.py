import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
import backtest_season_long as SL
from scipy.stats import spearmanr
T = pd.read_parquet("season_long_table.parquet")
lo = SL.loyo(T, [f for f in SL.BASIC if f != "mover"], "ridge", 10.0)
T["ridge"] = lo; T = T[~T.ridge.isna()]
def rep(m, lab):
    d = T[m]; w = d.games.values.astype(float); y = d.ppg.values
    for nm in ("clay", "ridge"):
        p = d[nm].values; e = SL.wmse(p, y, w)
        b = np.polyfit(p, y, 1, w=np.sqrt(w))   # slope of actual on prediction: >1 = predictions too compressed
        print(f"  {lab:18s} {nm:5s} MSE {e:6.2f} | mean pred {np.average(p, weights=w):5.2f} vs act {np.average(y, weights=w):5.2f} | sd pred {p.std():4.2f} vs act {y.std():4.2f} | slope act~pred {b[0]:.2f} | rho {spearmanr(p, y).correlation:.3f}")
top = T.adp <= 60
rep(top, "top-60 ADP")
rep(top & (T.rookie == 0), "top-60 vets")
rep(top & (T.rookie == 1), "top-60 rookies")
rep((T.adp > 60) & (T.adp <= 180), "ADP 61-180")
print("\ntop-60 by position (MSE clay / ridge, slope act~ridge):")
for ps in ("QB", "RB", "WR", "TE"):
    m = top & (T.pos == ps); d = T[m]
    if len(d) < 20: continue
    w = d.games.values.astype(float); print(f"  {ps} n={len(d):3d} clay {SL.wmse(d.clay.values, d.ppg.values, w):5.2f} ridge {SL.wmse(d.ridge.values, d.ppg.values, w):5.2f} | ridge slope {np.polyfit(d.ridge.values, d.ppg.values, 1, w=np.sqrt(w))[0]:.2f} clay slope {np.polyfit(d.clay.values, d.ppg.values, 1, w=np.sqrt(w))[0]:.2f}")
# where inside the top 60 does Clay win: players Clay projects ABOVE the ridge vs below
d = T[top].copy(); d["gap"] = d.clay - d.ridge
for lab, m in (("Clay > ridge by 2+", d.gap >= 2), ("within 2", d.gap.abs() < 2), ("Clay < ridge by 2+", d.gap <= -2)):
    s = d[m]; w = s.games.values.astype(float)
    if len(s) < 15: continue
    print(f"  {lab:20s} n={len(s):3d} act {np.average(s.ppg, weights=w):5.2f} clay {np.average(s.clay, weights=w):5.2f} ridge {np.average(s.ridge, weights=w):5.2f} | MSE clay {SL.wmse(s.clay.values, s.ppg.values, w):5.2f} ridge {SL.wmse(s.ridge.values, s.ppg.values, w):5.2f}")
print("\nbiggest top-60 cases where Clay was right and the ridge was not (|clay-act| small, |ridge-act| large):")
d["win"] = (d.ridge - d.ppg).abs() - (d.clay - d.ppg).abs()
for r in d.sort_values("win", ascending=False).head(10).itertuples(): print(f"  {r.year} {r.name:22s} {r.pos} adp {r.adp:5.1f} exp {r.exp:3.0f} hist {r.hist if not np.isnan(r.hist) else float('nan'):5.1f} | act {r.ppg:5.1f} clay {r.clay:5.1f} ridge {r.ridge:5.1f}")
