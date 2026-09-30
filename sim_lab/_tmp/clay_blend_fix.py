import sys, json, os, numpy as np, pandas as pd
sys.path.insert(0, ".")
import backtest_noclay_weekly as NW, research_clay_vs_shadow as CS, backtest_season_long as SL
from scipy.stats import spearmanr
F = CS.build_harness(); A = F["A"]; n = F["n"]
act, year, wk, pos, g, ppg, clay, layers, adp, pid = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"], F["adp"], A["pid"]
ch = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, A["name"])], dtype=float)
W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay)
T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]; lo = SL.loyo(T, LIVE, "ridge", 10.0)
key = {(int(y), nm, ps): v for y, nm, ps, v in zip(T.year, T.name, T.pos, lo)}; r = np.array([key.get((year[i], A["name"][i], pos[i]), np.nan) for i in range(n)])
prior = np.where(np.isnan(r) | (pos == "QB"), F["prior"], 0.5 * r + 0.5 * F["prior"])
def finish(rate):
    out = rate * layers
    for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
    return np.where(F["on"], out * np.power(F["pm"], 0.75), out)
C = pd.read_parquet("ctx_features.parquet"); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); xfp = np.where(idx >= 0, C.xfp_pg.values[np.maximum(idx, 0)], np.nan)
ev = (idx >= 0) & (g >= 1) & ~np.isnan(xfp); xf = np.where(ev, xfp, ppg)
lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
M = {"preseason prior only (never updates)": finish(prior), "Clay blend (per-game)": NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers,
     "shadow v2.17 (points evidence)": finish(NW.blend(prior, g, ppg, F["Pvec"])), "shadow v2.18 (usage evidence)": finish(NW.blend(prior, g, lam * xf + (1 - lam) * ppg, F["Pvec"]))}
lv = F["adp_curve"].copy()
for ps in NW.POS4:
    m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & (adp <= 150)].mean()
wt = np.maximum(0.05, lv) ** 2; top150 = adp <= 150
from collections import defaultdict
from scipy.stats import rankdata
SH = M["shadow v2.18 (usage evidence)"]; PW = np.where((pos == "WR") & (g == 1), F["Pvec"] * 5, F["Pvec"]); SH21 = finish(NW.blend(prior, g, lam * xf + (1 - lam) * ppg, PW))
evid = lam * xf + (1 - lam) * ppg
def clay_blend(Pv, evidence): return (Pv * clay_gm + g * evidence) / (Pv + g) * layers
P5 = np.full(n, 5.0); CUR = clay_blend(P5, ppg)
groups = defaultdict(list)
for i in np.where(top150)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
groups = {k: np.array(v) for k, v in groups.items() if len(v) >= 8}
def wm(p, m): return float(np.average((p[m] - act[m]) ** 2, weights=wt[m]))
def rho(pred, glo, ghi):
    out = []
    for (y, w, p_), ix in groups.items():
        ix = ix[(g[ix] >= glo) & (g[ix] <= ghi)]
        if len(ix) >= 8: out.append(np.corrcoef(rankdata(act[ix]), rankdata(pred[ix]))[0, 1])
    return float(np.mean(out)) if out else np.nan
# 1) per-position prior strength for the Clay blend, LOYO
PG = [2, 3, 5, 8, 12, 16, 24]; Ppos = np.full(n, 5.0); picks = {}
for ps in NW.POS4:
    picks[ps] = []
    for y in NW.YEARS:
        tr = top150 & (pos == ps) & (year != y) & (g >= 1); best = min(PG, key=lambda P_: wm(clay_blend(np.full(n, float(P_)), ppg), tr)); picks[ps].append(best); Ppos[(pos == ps) & (year == y)] = best
print("CLAY-SIDE blend: LOYO prior strength per position (current = 5 for all): " + " | ".join(f"{ps} {picks[ps]}" for ps in NW.POS4))
PposW = np.where((pos == "WR") & (g == 1), Ppos * 5, Ppos); P5W = np.where((pos == "WR") & (g == 1), 25.0, 5.0)
CANDS = {"current Clay blend (P=5, points)": CUR, "+ per-position P": clay_blend(Ppos, ppg), "+ usage evidence (same schedule)": clay_blend(P5, evid), "+ WR one-game prior x5": clay_blend(P5W, ppg),
         "all three": clay_blend(PposW, evid), "SHADOW v2.21 (for reference)": SH21}
stages = (("week 1", 0, 0), ("1 game", 1, 1), ("2 games", 2, 2), ("3 games", 3, 3), ("4-5", 4, 5), ("6-8", 6, 8), ("9+", 9, 99), ("ALL", 0, 99))
print("\nTop 150, importance-weighted MSE vs the CURRENT Clay blend (seasons better) and change in within-week rank rho, by games played")
for nm, p in CANDS.items():
    cells = []
    for lab, a, b in stages:
        m = top150 & (g >= a) & (g <= b); wins = sum(1 for y in NW.YEARS if wm(p, m & (year == y)) < wm(CUR, m & (year == y)) - 1e-12)
        cells.append(f"{lab}: {(wm(p, m)/wm(CUR, m)-1)*100:+.2f}% ({wins}/7) rho {rho(p, a, b)-rho(CUR, a, b):+.4f}")
    print(f"  {nm:34s} " + " | ".join(cells))
print("\nBy position, games 1+, 'all three' vs the current Clay blend:")
for ps in NW.POS4:
    m = top150 & (pos == ps) & (g >= 1); p = CANDS["all three"]; wins = sum(1 for y in NW.YEARS if wm(p, m & (year == y)) < wm(CUR, m & (year == y)))
    print(f"  {ps}: {(wm(p, m)/wm(CUR, m)-1)*100:+.2f}% ({wins}/7) | per-position P alone {(wm(CANDS['+ per-position P'], m)/wm(CUR, m)-1)*100:+.2f}% | usage alone {(wm(CANDS['+ usage evidence (same schedule)'], m)/wm(CUR, m)-1)*100:+.2f}%")
# forward check of 'all three' with P chosen on earlier seasons
Pf = np.full(n, 5.0)
for ps in NW.POS4:
    for y in NW.YEARS[2:]:
        tr = top150 & (pos == ps) & (year < y) & (g >= 1); Pf[(pos == ps) & (year == y)] = min(PG, key=lambda P_: wm(clay_blend(np.full(n, float(P_)), ppg), tr))
PfW = np.where((pos == "WR") & (g == 1), Pf * 5, Pf); fw = clay_blend(PfW, evid); fm = top150 & (year >= NW.YEARS[2])
for lab, a, b in (("1 game", 1, 1), ("games 1-3", 1, 3), ("games 4+", 4, 99), ("ALL", 0, 99)):
    m = fm & (g >= a) & (g <= b); wins = sum(1 for y in NW.YEARS[2:] if wm(fw, m & (year == y)) < wm(CUR, m & (year == y)))
    print(f"  FORWARD 'all three' {lab:10s}: {(wm(fw, m)/wm(CUR, m)-1)*100:+.2f}% ({wins}/5)")
