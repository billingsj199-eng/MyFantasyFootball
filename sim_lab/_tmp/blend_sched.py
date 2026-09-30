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
B70 = 0.7 * SH + 0.3 * FIXX
MODELS = {"shadow (Clay-free)": SH, "70/30 blend": B70, "fixed Clay blend": FIXX}
def w2(cut_mask, label, weighted=True):
    print(f"\n=== WEEK 2, {label}: error vs the Clay blend as it runs today, by season (negative = we are better) ===")
    print(f"  {'season':8s} {'n':>4s} | " + " | ".join(f"{k:>20s}" for k in MODELS) + " | rank rho: Clay today / shadow / blend")
    tally = {k: 0 for k in MODELS}; rt = {k: 0 for k in MODELS}
    for y in NW.YEARS:
        m = cut_mask & (wk == 2) & (year == y); ww = wt if weighted else np.ones(n)
        e = lambda p: float(np.average((p[m] - act[m]) ** 2, weights=ww[m])); cells = []
        for k, p in MODELS.items():
            d = (e(p) / e(CUR) - 1) * 100; tally[k] += int(d < 0); cells.append(f"{d:+19.2f}%")
        def rr(p):
            out = []
            for ps in NW.POS4:
                ix = np.where(m & (pos == ps))[0]
                if len(ix) >= 6: out.append(np.corrcoef(rankdata(act[ix]), rankdata(p[ix]))[0, 1])
            return float(np.mean(out))
        r0, r1, r2 = rr(CUR), rr(SH), rr(B70); rt["shadow (Clay-free)"] += int(r1 > r0); rt["70/30 blend"] += int(r2 > r0); rt["fixed Clay blend"] += int(rr(FIXX) > r0)
        print(f"  {y:<8d} {m.sum():4d} | " + " | ".join(cells) + f" | {r0:.3f} / {r1:.3f} / {r2:.3f}")
    m = cut_mask & (wk == 2); ww = wt if weighted else np.ones(n); e = lambda p: float(np.average((p[m] - act[m]) ** 2, weights=ww[m]))
    print(f"  {'POOLED':8s} {m.sum():4d} | " + " | ".join(f"{(e(p)/e(CUR)-1)*100:+19.2f}%" for p in MODELS.values()))
    print("  seasons better on ERROR: " + ", ".join(f"{k} {v}/7" for k, v in tally.items()) + "  |  seasons better on RANK: " + ", ".join(f"{k} {v}/7" for k, v in rt.items()))
e = lambda q, mm: float(np.mean((q[mm] - act[mm]) ** 2))
Pfix = {"QB": 16.0, "RB": 8.0, "WR": 12.0, "TE": 12.0}; Pstrong = np.array([Pfix[p_] for p_ in pos]); P5 = np.full(n, 5.0)
CL = extras(clay_blend(np.where((pos == "WR") & (g == 1), 5.0, 1.0) * np.where(adp <= 60, Pstrong, P5), evid))   # tiered Clay side: strong P only ADP <= 60
BANDS = (("1-30", adp <= 30), ("31-60", (adp > 30) & (adp <= 60)), ("61-100", (adp > 60) & (adp <= 100)), ("101-150", (adp > 100) & (adp <= 150)), ("151+", ~(adp <= 150)), ("EVERYONE", np.ones(n, bool)), ("TOP 60 wks 1-3", (adp <= 60) & (wk <= 3)))
def sched(w_early, w_late, G):   # weight on the SHADOW: w_early while games played <= G, w_late after
    w_ = np.where(g <= G, w_early, w_late); return w_ * SH + (1 - w_) * CL
CANDS = {"shadow alone (1.0 / 1.0)": SH, "flat 70/30": sched(.7, .7, 0), "flat 50/50": sched(.5, .5, 0),
         "50 early (g<=2) then 70": sched(.5, .7, 2), "50 early (g<=2) then 85": sched(.5, .85, 2), "30 early (g<=2) then 70": sched(.3, .7, 2), "30 early (g<=2) then 85": sched(.3, .85, 2),
         "50 early (g<=1) then 70": sched(.5, .7, 1), "50 early (g<=3) then 85": sched(.5, .85, 3), "tiered Clay side alone (0 / 0)": CL}
print("BLEND weight on the shadow by games played, vs today's Clay blend (negative = better), unweighted by ADP band; all weeks 1-18; seasons better of 7")
print(f"  {'schedule':34s} " + " ".join(f"{lab:>18s}" for lab, _ in BANDS) + "   rank rho top150")
from collections import defaultdict
groups = defaultdict(list)
for i in np.where(adp <= 150)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
groups = {k: np.array(v) for k, v in groups.items() if len(v) >= 8}
for nm, p in CANDS.items():
    cells = []
    for lab, bm in BANDS:
        wins = sum(1 for y in NW.YEARS if e(p, bm & (year == y)) < e(CUR, bm & (year == y)) - 1e-12); cells.append(f"{(e(p, bm)/e(CUR, bm)-1)*100:+6.2f}% ({wins}/7)")
    rh = float(np.mean([np.corrcoef(rankdata(act[ix]), rankdata(p[ix]))[0, 1] for ix in groups.values()]))
    print(f"  {nm:34s} " + " ".join(f"{c:>18s}" for c in cells) + f"   {rh:.4f}")
print("\nForward-style stability: best schedule when chosen on the OTHER six seasons (EVERYONE, unweighted), and its held-out result")
keys = [k for k in CANDS if k not in ("shadow alone (1.0 / 1.0)", "tiered Clay side alone (0 / 0)")]; ev = np.ones(n, bool); held = []; picks = []
for y in NW.YEARS:
    tr = year != y; best = min(keys, key=lambda k: e(CANDS[k], tr)); picks.append(best); te = year == y; held.append((e(CANDS[best], te) / e(CUR, te) - 1) * 100)
print("  picks: " + " | ".join(picks)); print("  held-out vs today's Clay blend by season: " + " ".join(f"{v:+.2f}%" for v in held) + f" | mean {np.mean(held):+.2f}% | flat 70/30 for comparison: " + " ".join(f"{(e(CANDS['flat 70/30'], year == y)/e(CUR, year == y)-1)*100:+.2f}%" for y in NW.YEARS))
