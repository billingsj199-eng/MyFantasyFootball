import sys, json, os, numpy as np
sys.path.insert(0, ".")
import backtest_noclay_weekly as NW, research_clay_vs_shadow as CS, backtest_season_long as SL
F = CS.build_harness(); A = F["A"]; n = F["n"]
act, year, g, ppg, pos, clay, layers, adp = A["act"], A["year"], A["g"], A["ppg"], A["pos"], A["clay"], A["layers"], F["adp"]
ch = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, A["name"])], dtype=float)
W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay)
ship = NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers
T = SL.build_table(); lo = SL.loyo(T, [f for f in SL.BASIC if f != "mover"], "ridge", 10.0)
key = {(int(y), nm, ps): v for y, nm, ps, v in zip(T.year, T.name, T.pos, lo)}
r_lo = np.array([key.get((year[i], A["name"][i], pos[i]), np.nan) for i in range(n)]); has = ~np.isnan(r_lo)
pr = np.where(has, 0.5 * r_lo + 0.5 * F["prior"], F["prior"]); out = NW.blend(pr, g, ppg, F["Pvec"]) * layers
for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (A["wk"] == gi), out * m_, out)
sh = np.where(F["on"], out * np.power(F["pm"], 0.75), out); ens = 0.5 * sh + 0.5 * ship
# importance weight = LEVEL^2, LEVEL = ADP-curve implied PPG (position-relative within the top 150), unlisted = position floor
lv = F["adp_curve"].copy()
for ps in NW.POS4:
    m = pos == ps; fb = np.nanmin(lv[m]); lv[m & np.isnan(lv)] = fb; t = m & (adp <= 150); lv[m] = lv[m] / lv[t].mean()
wgt = np.maximum(0.05, lv) ** 2
def wmse(p, m): return np.average((p[m] - act[m]) ** 2, weights=wgt[m])
print("WEEKLY, importance-weighted (LEVEL^2) MSE: shadow v2.15 vs corrected Clay blend, by ADP tier; and the 50/50 ensemble")
for lab, m in (("top 60", adp <= 60), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150", (adp > 100) & (adp <= 150)), ("top 150", adp <= 150)):
    ys = sorted(set(year[m])); ws = sum(1 for y in ys if wmse(sh, m & (year == y)) < wmse(ship, m & (year == y))); we = sum(1 for y in ys if wmse(ens, m & (year == y)) < wmse(ship, m & (year == y)))
    st = " | ".join(f"{sl} {(wmse(sh, m & sm) / wmse(ship, m & sm) - 1) * 100:+.1f}%" for sl, sm in (("wk1", g == 0), ("g1-3", (g >= 1) & (g <= 3)), ("g4-8", (g >= 4) & (g <= 8)), ("g9+", g >= 9)))
    print(f"  {lab:12s} n={m.sum():5d} | shadow vs Clay {(wmse(sh, m) / wmse(ship, m) - 1) * 100:+.2f}% ({ws}/{len(ys)}) | ensemble {(wmse(ens, m) / wmse(ship, m) - 1) * 100:+.2f}% ({we}/{len(ys)}) | by stage: {st}")
for ps in NW.POS4:
    m = (adp <= 150) & (pos == ps); ys = sorted(set(year[m])); ws = sum(1 for y in ys if wmse(sh, m & (year == y)) < wmse(ship, m & (year == y)))
    print(f"  top 150 {ps:3s}   n={m.sum():5d} | shadow vs Clay {(wmse(sh, m) / wmse(ship, m) - 1) * 100:+.2f}% ({ws}/{len(ys)}) | ensemble {(wmse(ens, m) / wmse(ship, m) - 1) * 100:+.2f}%")
