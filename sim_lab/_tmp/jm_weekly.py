import sys, json, os, numpy as np
sys.path.insert(0, ".")
import backtest_noclay_weekly as NW, research_clay_vs_shadow as CS, backtest_season_long as SL
F = CS.build_harness(); A = F["A"]; n = F["n"]
act, year, g, ppg, pos, clay, layers, adp = A["act"], A["year"], A["g"], A["ppg"], A["pos"], A["clay"], A["layers"], F["adp"]
ch = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, A["name"])], dtype=float)
W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay)
ship = NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers
T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"]
def shadow_with(feats, fwd=False):
    lo = (SL.forward if fwd else SL.loyo)(T, feats, "ridge", 10.0)
    key = {(int(y), nm, ps): v for y, nm, ps, v in zip(T.year, T.name, T.pos, lo)}
    r = np.array([key.get((year[i], A["name"][i], pos[i]), np.nan) for i in range(n)]); has = ~np.isnan(r)
    pr = np.where(has, 0.5 * r + 0.5 * F["prior"], F["prior"]); out = NW.blend(pr, g, ppg, F["Pvec"]) * layers
    for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (A["wk"] == gi), out * m_, out)
    return np.where(F["on"], out * np.power(F["pm"], 0.75), out)
lv = F["adp_curve"].copy()
for ps in NW.POS4:
    m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); t = m & (adp <= 150); lv[m] = lv[m] / lv[t].mean()
wgt = np.maximum(0.05, lv) ** 2
def wmse(p, m): return np.average((p[m] - act[m]) ** 2, weights=wgt[m])
for fwd in (False, True):
    b = shadow_with(LIVE, fwd); j = shadow_with(LIVE + ["jm"], fwd); fm = (year >= NW.YEARS[2]) if fwd else np.ones(n, bool)
    print(("FORWARD" if fwd else "LOYO") + " weekly, importance-weighted: shadow with +JM season prior vs current v2.15, and vs corrected Clay")
    for lab, m in (("top 60", adp <= 60), ("61-100", (adp > 60) & (adp <= 100)), ("101-150", (adp > 100) & (adp <= 150)), ("top 150", adp <= 150), ("top 150 wk1", (adp <= 150) & (g == 0)), ("top 150 g1-3", (adp <= 150) & (g >= 1) & (g <= 3)), ("top 150 young", (adp <= 150) & (F["A"]["exp"] <= 2))):
        m = m & fm; ys = sorted(set(year[m])); w = sum(1 for y in ys if wmse(j, m & (year == y)) < wmse(b, m & (year == y)))
        print(f"  {lab:14s} n={m.sum():5d} | +JM vs v2.15 {(wmse(j, m)/wmse(b, m)-1)*100:+.2f}% ({w}/{len(ys)}) | +JM vs Clay {(wmse(j, m)/wmse(ship, m)-1)*100:+.2f}% (v2.15 {(wmse(b, m)/wmse(ship, m)-1)*100:+.2f}%)")
