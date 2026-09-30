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
evid = lam * xf + (1 - lam) * ppg
# shadow v2.21 full: WR one-game prior x5, QB game-total tilt, backup-QB WR dock
PW = np.where((pos == "WR") & (g == 1), F["Pvec"] * 5, F["Pvec"]); SH = finish(NW.blend(prior, g, evid, PW))
def colv(c): return np.where(idx >= 0, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
gt = colv("game_total"); z = np.zeros(n)
for y in NW.YEARS:
    for w_ in range(1, 19):
        m = (year == y) & (wk == w_) & ~np.isnan(gt)
        if m.sum() > 20 and gt[m].std() > 0: z[m] = np.clip((gt[m] - gt[m].mean()) / gt[m].std(), -2.5, 2.5)
qbo = colv("qb_out") == 1
def extras(p): 
    p = np.where(pos == "QB", p * np.exp(0.03 * z), p); return np.where((pos == "WR") & qbo, p * np.where(adp <= 60, 0.85, 0.95), p)
SH = extras(SH)
# Clay blend: current, and fixed (per-position P chosen LOYO, usage evidence, WR one-game x5)
def clay_blend(Pv, e): return (Pv * clay_gm + g * e) / (Pv + g) * layers
def wm(p, m): return float(np.average((p[m] - act[m]) ** 2, weights=wt[m]))
CUR = clay_blend(np.full(n, 5.0), ppg); PG = [2, 3, 5, 8, 12, 16, 24]; Ppos = np.full(n, 5.0)
for ps in NW.POS4:
    for y in NW.YEARS:
        tr = top150 & (pos == ps) & (year != y) & (g >= 1); Ppos[(pos == ps) & (year == y)] = min(PG, key=lambda P_: wm(clay_blend(np.full(n, float(P_)), ppg), tr))
FIX = clay_blend(np.where((pos == "WR") & (g == 1), Ppos * 5, Ppos), evid); FIXX = extras(FIX)
# ensemble weight chosen LOYO
WG = [0.0, 0.25, 0.4, 0.5, 0.6, 0.75, 1.0]; ENS = np.zeros(n); picks = []
for y in NW.YEARS:
    tr = top150 & (year != y); best = min(WG, key=lambda w_: wm(w_ * SH + (1 - w_) * FIXX, tr)); picks.append(best); te = year == y; ENS[te] = best * SH[te] + (1 - best) * FIXX[te]
groups = defaultdict(list)
for i in np.where(top150)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
groups = {k: np.array(v) for k, v in groups.items() if len(v) >= 8}
def rank(pred, years=None):
    rho, pw, tot = [], 0, 0
    for (y, w_, p_), ix in groups.items():
        if years is not None and y not in years: continue
        a = act[ix]; pv = pred[ix]; rho.append(np.corrcoef(rankdata(a), rankdata(pv))[0, 1]); d = pv[:, None] - pv[None, :]; o = a[:, None] - a[None, :]; iu = np.triu_indices(len(ix), 1); ok = (d[iu] != 0) & (o[iu] != 0)
        pw += int(((d[iu] > 0) == (o[iu] > 0))[ok].sum()); tot += int(ok.sum())
    return float(np.mean(rho)), 100.0 * pw / tot
CANDS = {"A. Clay blend, as it runs today": CUR, "B. Clay blend, fixed (P per position, usage, WR 1-game)": FIX, "C. B + the QB total tilt and backup-QB WR dock": FIXX, "D. Shadow v2.21 (Clay-free)": SH, f"E. Blend of C and D, weight chosen each season {picks}": ENS, "F. Fixed 50/50 of C and D": 0.5 * SH + 0.5 * FIXX}
print("TOP 150, 2019-25, importance-weighted. Error = vs option A (negative = better); seasons = seasons better than A; rank rho and pairs = weekly ordering within position")
print(f"  {'option':74s} {'error vs A':>10s} {'seasons':>8s} {'typical miss':>13s} {'rank rho':>9s} {'rho seasons':>11s} {'pairs right':>12s}")
rA = {y: rank(CUR, {y})[0] for y in NW.YEARS}
for nm, p in CANDS.items():
    wins = sum(1 for y in NW.YEARS if wm(p, top150 & (year == y)) < wm(CUR, top150 & (year == y)) - 1e-12); r, pw = rank(p); rw = sum(1 for y in NW.YEARS if rank(p, {y})[0] > rA[y] + 1e-12)
    print(f"  {nm:74s} {(wm(p, top150)/wm(CUR, top150)-1)*100:+9.2f}% {wins:>6d}/7 {np.sqrt(wm(p, top150)):12.3f} {r:9.4f} {rw:>9d}/7 {pw:11.2f}%")
print("\nHead to head between the two finalists, by season (weighted error, D shadow vs F 50/50; negative = the 50/50 blend better):")
print("  " + " | ".join(f"{y}: {(wm(0.5*SH+0.5*FIXX, top150 & (year==y))/wm(SH, top150 & (year==y))-1)*100:+.2f}%" for y in NW.YEARS))
print("By position, error vs A:  " + " | ".join(f"{ps}: C {(wm(FIXX, top150&(pos==ps))/wm(CUR, top150&(pos==ps))-1)*100:+.2f}%  D {(wm(SH, top150&(pos==ps))/wm(CUR, top150&(pos==ps))-1)*100:+.2f}%  F {(wm(0.5*SH+0.5*FIXX, top150&(pos==ps))/wm(CUR, top150&(pos==ps))-1)*100:+.2f}%" for ps in NW.POS4))
print("By stage, error vs A:     " + " | ".join(f"{lab}: C {(wm(FIXX, top150&(g>=a)&(g<=b))/wm(CUR, top150&(g>=a)&(g<=b))-1)*100:+.2f}% D {(wm(SH, top150&(g>=a)&(g<=b))/wm(CUR, top150&(g>=a)&(g<=b))-1)*100:+.2f}% F {(wm(0.5*SH+0.5*FIXX, top150&(g>=a)&(g<=b))/wm(CUR, top150&(g>=a)&(g<=b))-1)*100:+.2f}%" for lab, a, b in (("wk1", 0, 0), ("g1-3", 1, 3), ("g4-8", 4, 8), ("g9+", 9, 99))))
