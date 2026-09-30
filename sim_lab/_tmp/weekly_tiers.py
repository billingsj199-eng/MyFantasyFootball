import sys, json, os, numpy as np
sys.path.insert(0, ".")
import backtest_noclay_weekly as NW, research_clay_vs_shadow as CS, backtest_season_long as SL
F = CS.build_harness(); A = F["A"]; n = F["n"]
act, year, g, ppg, pos, clay, layers, adp = A["act"], A["year"], A["g"], A["ppg"], A["pos"], A["clay"], A["layers"], F["adp"]
ch = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, A["name"])], dtype=float)
W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay)
ship_gm = NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers
T = SL.build_table(); lo = SL.loyo(T, [f for f in SL.BASIC if f != "mover"], "ridge", 10.0)
key = {(int(y), nm, ps): v for y, nm, ps, v in zip(T.year, T.name, T.pos, lo)}
r_lo = np.array([key.get((year[i], A["name"][i], pos[i]), np.nan) for i in range(n)]); has = ~np.isnan(r_lo)
pr = np.where(has, 0.5 * r_lo + 0.5 * F["prior"], F["prior"])
out = NW.blend(pr, g, ppg, F["Pvec"]) * layers
for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (A["wk"] == gi), out * m_, out)
ref15 = np.where(F["on"], out * np.power(F["pm"], 0.75), out)
ens = 0.5 * ref15 + 0.5 * ship_gm
print("WEEKLY, shadow v2.15 vs the corrected (per-game) Clay blend, by preseason ADP tier; and a 50/50 ensemble of the two")
tiers = (("top 60", adp <= 60), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150", (adp > 100) & (adp <= 150)), ("top 150", adp <= 150), ("ADP 151+ / unlisted", ~(adp <= 150)))
for lab, m in tiers:
    a, w, ny = NW.pct_vs(ref15[m], ship_gm[m], act[m], year[m]); e, we, _ = NW.pct_vs(ens[m], ship_gm[m], act[m], year[m])
    stage = " | ".join(f"{sl} {NW.pct_vs(ref15[m & sm], ship_gm[m & sm], act[m & sm], year[m & sm])[0]:+.1f}%" for sl, sm in (("wk1", g == 0), ("g1-3", (g >= 1) & (g <= 3)), ("g4+", g >= 4)))
    print(f"  {lab:20s} n={m.sum():5d} | shadow vs Clay {a:+.2f}% ({w}/{ny}) | 50/50 ensemble vs Clay {e:+.2f}% ({we}/{ny}) | by stage: {stage}")
for ps in ("QB", "RB", "WR", "TE"):
    m = (adp <= 150) & (pos == ps); a, w, ny = NW.pct_vs(ref15[m], ship_gm[m], act[m], year[m]); e, we, _ = NW.pct_vs(ens[m], ship_gm[m], act[m], year[m])
    print(f"  top 150 {ps:3s}          n={m.sum():5d} | shadow vs Clay {a:+.2f}% ({w}/{ny}) | ensemble {e:+.2f}% ({we}/{ny})")
