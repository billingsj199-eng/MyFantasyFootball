import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
import backtest_season_long as SL
T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"]; NOSTR = [f for f in LIVE if f not in ("str1", "str2", "str3", "nostr")]
clay, act, g, yr, adp, pos, strb = T.clay.values, T.ppg.values, T.games.values.astype(float), T.year.values, T.adp.values, T.pos.values, T.strb.values
def mk(lo): return np.where(np.isnan(lo), T.prior.values, 0.5 * lo + 0.5 * T.prior.values)
sh, sh0 = mk(SL.loyo(T, LIVE, "ridge", 10.0)), mk(SL.loyo(T, NOSTR, "ridge", 10.0))
fw, fw0 = mk(SL.forward(T, LIVE, "ridge", 10.0)), mk(SL.forward(T, NOSTR, "ridge", 10.0))
def cmp(lab, a, b, m):
    ys = [y for y in SL.YEARS if (m & (yr == y)).sum() >= 12]; w = sum(1 for y in ys if SL.wmse(a[m & (yr == y)], act[m & (yr == y)], g[m & (yr == y)]) < SL.wmse(b[m & (yr == y)], act[m & (yr == y)], g[m & (yr == y)]))
    print(f"  {lab:40s} n={m.sum():4d} with chart {SL.wmse(a[m], act[m], g[m]):6.2f} vs without {SL.wmse(b[m], act[m], g[m]):6.2f} ({(SL.wmse(a[m], act[m], g[m])/SL.wmse(b[m], act[m], g[m])-1)*100:+5.2f}%, chart wins {w}/{len(ys)})")
print("1) Does the week-1 depth string help OUR season prior? (v2.15 form, with vs without the string dummies)")
fm = yr >= SL.YEARS[2]
for lab, m in (("top 60", adp <= 60), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150", (adp > 100) & (adp <= 150)), ("top 150", adp <= 150), ("ALL", np.ones(len(T), bool))):
    cmp("LOYO " + lab, sh, sh0, m); cmp("forward " + lab, fw, fw0, fm & m)
for ps in ("RB", "WR", "TE"): cmp(f"LOYO top 150 {ps}", sh, sh0, (adp <= 150) & (pos == ps))
print("\n2) Does Clay follow the chart? Top-150 RB/WR/TE by week-1 string: Clay's level vs the chart, and who is right")
for ps in ("RB", "WR", "TE"):
    for s in (1, 2, 3):
        m = (adp <= 150) & (pos == ps) & (strb == s)
        if m.sum() < 15: continue
        print(f"  {ps} string {s}: n={m.sum():3d} | act {np.average(act[m], weights=g[m]):5.2f} | Clay {np.average(clay[m], weights=g[m]):5.2f} (MSE {SL.wmse(clay[m], act[m], g[m]):5.2f}) | ours {np.average(sh[m], weights=g[m]):5.2f} (MSE {SL.wmse(sh[m], act[m], g[m]):5.2f})")
print("\n3) Where Clay OVERRIDES the chart: chart string 2+ but Clay projects a starter-level number (>= his own string-1 median for the position)")
for ps in ("RB", "WR", "TE"):
    s1 = (adp <= 150) & (pos == ps) & (strb == 1); lvl = np.median(clay[s1])
    m = (adp <= 150) & (pos == ps) & (strb >= 2) & (clay >= lvl); n = (adp <= 150) & (pos == ps) & (strb >= 2) & (clay < lvl)
    for lab, mm in ((f"{ps} string 2+, Clay >= starter level {lvl:.1f}", m), (f"{ps} string 2+, Clay below it", n)):
        if mm.sum() < 8: continue
        print(f"  {lab:46s} n={mm.sum():3d} | act {np.average(act[mm], weights=g[mm]):5.2f} | Clay {np.average(clay[mm], weights=g[mm]):5.2f} MSE {SL.wmse(clay[mm], act[mm], g[mm]):5.2f} | ours {np.average(sh[mm], weights=g[mm]):5.2f} MSE {SL.wmse(sh[mm], act[mm], g[mm]):5.2f}")
    if m.sum():
        for r in T[m].sort_values("adp").head(6).itertuples(): print(f"      {r.year} {r.name:20s} adp {r.adp:4.0f} string {int(r.strb)} | act {r.ppg:5.1f} Clay {r.clay:5.1f} ours {sh[r.Index]:5.1f}")
print("\n4) Where Clay goes BELOW the chart: string 1 but Clay under his string-1 25th percentile")
for ps in ("RB", "WR", "TE"):
    s1 = (adp <= 150) & (pos == ps) & (strb == 1); q = np.percentile(clay[s1], 25); m = s1 & (clay < q)
    print(f"  {ps} string 1, Clay < {q:.1f}: n={m.sum():3d} | act {np.average(act[m], weights=g[m]):5.2f} | Clay {np.average(clay[m], weights=g[m]):5.2f} MSE {SL.wmse(clay[m], act[m], g[m]):5.2f} | ours {np.average(sh[m], weights=g[m]):5.2f} MSE {SL.wmse(sh[m], act[m], g[m]):5.2f}")
