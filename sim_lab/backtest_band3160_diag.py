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
e = lambda q, mm: float(np.mean((q[mm] - act[mm]) ** 2)); B = (adp > 30) & (adp <= 60); exp_ = A["exp"]; age_ = A["age"]
hand = F["prior"]; ridge_r = r; curve = F["adp_curve"]; hist = F["hist"]
print(f"ADP 31-60 band: {int(B.sum())} player-weeks, {len(set(zip(year[B], A['name'][B])))} player-seasons")
print("\n1) WHICH PIECE OF OUR PRIOR IS OFF? week-1 rows only (pure prior x layers), mean vs actual SEASON ppg of those players; and the same for the neighbours")
for lab, bm in (("ADP 1-30", adp <= 30), ("ADP 31-60", B), ("ADP 61-100", (adp > 60) & (adp <= 100))):
    m = bm & (g == 0); nm = list(zip(year[m], A["name"][m])); seas = {}
    for i in np.where(bm)[0]: seas.setdefault((year[i], A["name"][i]), []).append(act[i] / max(layers[i], 0.3))
    sp = np.array([np.mean(seas[k]) for k in nm])
    print(f"  {lab:11s} n={m.sum():4d} | actual season rate {sp.mean():5.2f} | Clay/gm {clay_gm[m].mean():5.2f} ({(clay_gm[m].mean()/sp.mean()-1)*100:+.1f}%) | our prior {prior[m].mean():5.2f} ({(prior[m].mean()/sp.mean()-1)*100:+.1f}%) | hand prior {hand[m].mean():5.2f} ({(hand[m].mean()/sp.mean()-1)*100:+.1f}%) | ridge {np.nanmean(ridge_r[m]):5.2f} ({(np.nanmean(ridge_r[m])/sp.mean()-1)*100:+.1f}%) | ADP curve {np.nanmean(curve[m]):5.2f} ({(np.nanmean(curve[m])/sp.mean()-1)*100:+.1f}%) | raw history {np.nanmean(hist[m]):5.2f} ({(np.nanmean(hist[m])/sp.mean()-1)*100:+.1f}%)")
print("\n2) ADP curve fit residual by finer ADP bucket (actual weekly pts / layers minus the log-ADP curve), all positions, weeks 1-4: is the log curve bent wrong in the middle?")
for lo_, hi_ in ((1, 12), (13, 24), (25, 36), (37, 48), (49, 60), (61, 80), (81, 100), (101, 150)):
    m = (adp >= lo_) & (adp <= hi_) & (wk <= 4) & ~np.isnan(curve); rate = act[m] / np.maximum(layers[m], 0.3)
    print(f"   ADP {lo_:3d}-{hi_:3d} n={m.sum():4d} | actual {rate.mean():5.2f} | curve {curve[m].mean():5.2f} | residual {rate.mean()-curve[m].mean():+5.2f} ({(rate.mean()/curve[m].mean()-1)*100:+.1f}%) | by pos: " + " ".join(f"{ps} {(act[m&(pos==ps)]/np.maximum(layers[m&(pos==ps)],0.3)).mean()-curve[m&(pos==ps)].mean():+.2f}" for ps in NW.POS4 if (m & (pos == ps)).sum() >= 25))
print("\n3) WHO do we miss in 31-60? shadow vs today's Clay blend, weeks 2-18, by type (negative = we are better), with level")
late = wk >= 2
def line(lab, m):
    m = m & B & late
    if m.sum() < 120: return
    wins = sum(1 for y in NW.YEARS if (m & (year == y)).sum() >= 10 and e(SH, m & (year == y)) < e(CUR, m & (year == y)))
    print(f"   {lab:40s} n={int(m.sum()):4d} | shadow {(e(SH, m)/e(CUR, m)-1)*100:+6.2f}% ({wins}/7) | blend {(e(B70, m)/e(CUR, m)-1)*100:+6.2f}% | actual {act[m].mean():5.2f} Clay {CUR[m].mean():5.2f} shadow {SH[m].mean():5.2f}")
for ps in NW.POS4: line(f"{ps}", pos == ps)
for lab, m in (("rookie", exp_ == 0), ("2nd year", exp_ == 1), ("3rd year", exp_ == 2), ("years 4-6", (exp_ >= 3) & (exp_ <= 5)), ("year 7+", exp_ >= 6)): line(lab, m)
for lab, m in (("age <= 24", age_ <= 24), ("age 25-28", (age_ > 24) & (age_ <= 28)), ("age 29+", age_ > 28)): line(lab, m)
gap = SH - CUR
for lab, m in (("shadow LOWER than Clay by 1+", gap <= -1), ("within 1", np.abs(gap) < 1), ("shadow HIGHER than Clay by 1+", gap >= 1)): line(lab, m)
mk = curve - hist
for lab, m in (("market >> history (ADP curve 2+ over history)", mk >= 2), ("market ~ history", np.abs(mk) < 2), ("market << history", mk <= -2), ("no history (rookies)", np.isnan(hist))): line(lab, m)
for lab, m in (("weeks 2-4", (wk >= 2) & (wk <= 4)), ("weeks 5-9", (wk >= 5) & (wk <= 9)), ("weeks 10-18", wk >= 10)): line(lab, m)
print("\n4) Same type table for ADP 1-30 (for contrast): direction only")
for lab, m in (("shadow LOWER than Clay by 1+", gap <= -1), ("within 1", np.abs(gap) < 1), ("shadow HIGHER than Clay by 1+", gap >= 1)):
    mm = m & (adp <= 30) & late; print(f"   {lab:40s} n={int(mm.sum()):4d} | shadow {(e(SH, mm)/e(CUR, mm)-1)*100:+6.2f}% | actual {act[mm].mean():5.2f} Clay {CUR[mm].mean():5.2f} shadow {SH[mm].mean():5.2f}")
