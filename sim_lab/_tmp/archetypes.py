import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
import backtest_season_long as SL
T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"]
lo = SL.loyo(T, LIVE, "ridge", 10.0); T["sh"] = np.where(np.isnan(lo), T.prior, 0.5 * lo + 0.5 * T.prior)
d = T[T.adp <= 60].copy()
d["e_sh"] = d.sh - d.ppg; d["e_cl"] = d.clay - d.ppg
d["x"] = (d.e_sh.abs() - d.e_cl.abs()) * d.games   # games-weighted excess absolute error vs Clay (+ = we were worse)
mk = np.where(d.adp_curve.isna(), np.nan, d.adp_curve)   # market-implied PPG from the ADP curve
d["mkt_vs_hist"] = mk - d["hist"].values
def bucket_exp(e): return "rookie" if e == 0 else ("year 2" if e == 1 else ("year 3" if e == 2 else ("years 4-6" if e <= 5 else "year 7+")))
d["expb"] = d.exp.apply(bucket_exp)
d["adpb"] = pd.cut(d.adp, [0, 12, 24, 36, 60], labels=["ADP 1-12", "13-24", "25-36", "37-60"])
d["dir"] = np.where(d.e_sh < -1.5, "we were LOW (player beat us)", np.where(d.e_sh > 1.5, "we were HIGH (player fell short)", "within 1.5"))
d["mh"] = np.where(d.mkt_vs_hist.isna(), "no history (rookie)", np.where(d.mkt_vs_hist >= 2, "market >> history (riser by ADP)", np.where(d.mkt_vs_hist <= -2, "market << history (faller by ADP)", "market ~ history")))
d["mover"] = np.where(d.get("mover", 0) == 1, "changed team", "same team")
d["ageb"] = np.where(d.age >= 30, "age 30+", np.where(d.age <= 24, "age <= 24", "age 25-29"))
tot = d.x.sum()
print(f"top-60 player-seasons {len(d)} | shadow games-weighted MSE {SL.wmse(d.sh, d.ppg, d.games):.2f} vs Clay {SL.wmse(d.clay, d.ppg, d.games):.2f} | total excess abs error vs Clay {tot:.0f} pt-games")
def show(col, title):
    g = d.groupby(col).agg(n=("x", "size"), excess=("x", "sum"), we_low=("e_sh", lambda s: (s < -1.5).mean()), we_high=("e_sh", lambda s: (s > 1.5).mean()), sh_mse=("sh", lambda s: SL.wmse(s.values, d.loc[s.index, "ppg"].values, d.loc[s.index, "games"].values)), cl_mse=("clay", lambda s: SL.wmse(s.values, d.loc[s.index, "ppg"].values, d.loc[s.index, "games"].values)))
    g["share"] = g.excess / tot * 100; g = g.sort_values("excess", ascending=False)
    print(f"\n=== {title} ===")
    for k, r in g.iterrows(): print(f"  {str(k):36s} n={int(r.n):3d} | share of excess error {r.share:+6.0f}% | MSE ours {r.sh_mse:5.2f} vs Clay {r.cl_mse:5.2f} ({(r.sh_mse/r.cl_mse-1)*100:+5.1f}%) | we were low {r.we_low*100:3.0f}%, high {r.we_high*100:3.0f}%")
show("pos", "by position"); show("expb", "by experience"); show("mh", "market vs our history (ADP-implied PPG minus 3yr/last-8 history)"); show("adpb", "by ADP band"); show("ageb", "by age"); show("dir", "direction of our miss")
show(["pos", "expb"], "position x experience (top 8 groups)")
print("\n=== the 15 worst player-seasons for us relative to Clay (top 60) ===")
for r in d.sort_values("x", ascending=False).head(15).itertuples(): print(f"  {r.year} {r.name:22s} {r.pos} {r.expb:9s} adp {r.adp:4.0f} age {r.age:2.0f} hist {getattr(r, "hist"):5.1f} | act {r.ppg:5.1f} ours {r.sh:5.1f} Clay {r.clay:5.1f}")
print("\n=== the 10 where we beat Clay most (top 60) ===")
for r in d.sort_values("x").head(10).itertuples(): print(f"  {r.year} {r.name:22s} {r.pos} {r.expb:9s} adp {r.adp:4.0f} age {r.age:2.0f} hist {getattr(r, "hist"):5.1f} | act {r.ppg:5.1f} ours {r.sh:5.1f} Clay {r.clay:5.1f}")


