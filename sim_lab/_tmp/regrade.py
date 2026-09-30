import sys, json, os, numpy as np
sys.path.insert(0, ".")
import backtest_noclay_weekly as NW, research_clay_vs_shadow as CS, backtest_season_long as SL
F = CS.build_harness(); A = F["A"]; n = F["n"]
act, year, g, ppg, pos, clay, layers = A["act"], A["year"], A["g"], A["ppg"], A["pos"], A["clay"], A["layers"]
ch = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, A["name"])], dtype=float)
W = np.where(year <= 2020, 16.0, 17.0); ok = gm >= 4
clay_gm = np.where(ok, clay * W / np.maximum(gm, 1), clay)
ship17 = F["shipped"]; ship_gm = NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers
ref = F["shadow"]   # v2.11 harness form
# v2.15 form: 50/50 ridge + hand prior
T = SL.build_table(); lo = SL.loyo(T, [f for f in SL.BASIC if f != "mover"], "ridge", 10.0)
key = {(int(y), nm, ps): v for y, nm, ps, v in zip(T.year, T.name, T.pos, lo)}
r_lo = np.array([key.get((year[i], A["name"][i], pos[i]), np.nan) for i in range(n)]); has = ~np.isnan(r_lo)
prior = F["prior"]; pr = np.where(has, 0.5 * r_lo + 0.5 * prior, prior)
out = NW.blend(pr, g, ppg, F["Pvec"]) * layers
for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (A["wk"] == gi), out * m_, out)
ref15 = np.where(F["on"], out * np.power(F["pm"], 0.75), out)
print("Shadow vs the Clay blend, per-17 (old reference) -> per-game (corrected reference); negative = shadow better")
for lab, m in (("ALL", np.ones(n, bool)), ("week 1", g == 0), ("games 1-3", (g >= 1) & (g <= 3)), ("games 4-8", (g >= 4) & (g <= 8)), ("games 9+", g >= 9), ("QB", pos == "QB"), ("RB", pos == "RB"), ("WR", pos == "WR"), ("TE", pos == "TE")):
    a17, w17, ny = NW.pct_vs(ref[m], ship17[m], act[m], year[m]); agm, wgm, _ = NW.pct_vs(ref[m], ship_gm[m], act[m], year[m])
    b17, v17, _ = NW.pct_vs(ref15[m], ship17[m], act[m], year[m]); bgm, vgm, _ = NW.pct_vs(ref15[m], ship_gm[m], act[m], year[m])
    print(f"  {lab:10s} n={m.sum():5d} | shadow v2.11: {a17:+.2f}% ({w17}/{ny}) -> {agm:+.2f}% ({wgm}/{ny}) | shadow v2.15 (ridge 50%): {b17:+.2f}% ({v17}/{ny}) -> {bgm:+.2f}% ({vgm}/{ny})")
