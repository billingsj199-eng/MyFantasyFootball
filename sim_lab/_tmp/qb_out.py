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
from scipy.stats import rankdata
from collections import defaultdict
PC, PS = M["Clay blend (per-game)"], M["shadow v2.18 (usage evidence)"]
qbo = np.where(idx >= 0, C.qb_out.values[np.maximum(idx, 0)], np.nan).astype(float); veg = np.where(idx >= 0, C.veg.values[np.maximum(idx, 0)], np.nan).astype(float); imp = np.where(idx >= 0, C.implied.values[np.maximum(idx, 0)], np.nan).astype(float)
out = (qbo == 1); inn = (qbo == 0); sk = np.isin(pos, ["RB", "WR", "TE"])
print(f"Skill-player weeks with the team's primary QB OUT: {int((out & sk).sum())} of {int(((out | inn) & sk).sum())} ({(out & sk).sum()/((out|inn)&sk).sum()*100:.1f}%); top 150: {int((out & sk & top150).sum())}")
print(f"Does Vegas move? mean implied team total: QB in {np.nanmean(imp[inn & sk]):.2f}, QB out {np.nanmean(imp[out & sk]):.2f} | mean Vegas multiplier {np.nanmean(veg[inn & sk]):.3f} vs {np.nanmean(veg[out & sk]):.3f}")
print("\n1) CALIBRATION, top 150: actual / projected when the primary QB is out vs in (1.00 = the total already accounts for it)")
for ps in ("WR", "TE", "RB"):
    for lab, m in (("QB in ", inn), ("QB OUT", out)):
        mm = m & top150 & (pos == ps); ys = sorted(set(year[mm]))
        print(f"   {ps} {lab} n={mm.sum():5d} | actual {act[mm].mean():5.2f} | shadow {PS[mm].mean():5.2f} ratio {act[mm].mean()/PS[mm].mean():.3f} | Clay blend {PC[mm].mean():5.2f} ratio {act[mm].mean()/PC[mm].mean():.3f} | per-season shadow ratio " + " ".join(f"{act[mm & (year==y)].mean()/PS[mm & (year==y)].mean():.2f}" for y in ys if (mm & (year==y)).sum() >= 15))
print("\n2) By how long the backup has been in: first game without the starter vs later games (shadow ratio)")
key_prev = {(int(year[i]), pid[i], int(wk[i])): out[i] for i in range(n) if pid[i]}
first = np.array([bool(out[i]) and not any(key_prev.get((int(year[i]), pid[i], int(wk[i]) - d), False) for d in (1, 2)) for i in range(n)]); later = out & ~first
for ps in ("WR", "TE", "RB"):
    for lab, m in (("first game with the backup", first), ("backup already playing", later)):
        mm = m & top150 & (pos == ps)
        if mm.sum() >= 40: print(f"   {ps} {lab:28s} n={mm.sum():4d} | actual/shadow {act[mm].mean()/PS[mm].mean():.3f} | actual/Clay {act[mm].mean()/PC[mm].mean():.3f}")
print("\n3) By player tier when the QB is out (shadow ratio): does it hit the WR1 or the secondary options?")
for ps in ("WR", "TE", "RB"):
    for lab, m in (("ADP 1-60", adp <= 60), ("ADP 61-150", (adp > 60) & (adp <= 150))):
        mm = out & m & (pos == ps)
        if mm.sum() >= 40: print(f"   {ps} {lab:10s} n={mm.sum():4d} | actual/shadow {act[mm].mean()/PS[mm].mean():.3f} (QB in: {act[inn & m & (pos==ps)].mean()/PS[inn & m & (pos==ps)].mean():.3f})")
# 4) rank + MSE test of a dock: pred x (1 - d) on QB-out rows, d per position LOYO
groups = defaultdict(list)
for i in np.where(top150)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
groups = {k: np.array(v) for k, v in groups.items() if len(v) >= 8}
def metrics(pred, ps, years):
    rho, se, sn = [], 0.0, 0
    for (y, w, p_), ix in groups.items():
        if p_ != ps or y not in years: continue
        rho.append(np.corrcoef(rankdata(act[ix]), rankdata(pred[ix]))[0, 1]); se += float((wt[ix] * (pred[ix] - act[ix]) ** 2).sum()); sn += float(wt[ix].sum())
    return float(np.mean(rho)), se / sn
print("\n4) A dock on QB-out weeks, d per position chosen leave-one-season-out (on weighted MSE), reported on rank and MSE")
DG = [0.0, 0.03, 0.06, 0.09, 0.12, 0.15, 0.20]
for ps in ("WR", "TE", "RB"):
    cand = {d: np.where(out & (pos == ps), PS * (1 - d), PS) for d in DG}; st = {d: {y: metrics(cand[d], ps, {y}) for y in NW.YEARS} for d in DG}
    picks, o_r, b_r, o_m, b_m, wins = [], [], [], [], [], 0
    for y in NW.YEARS:
        tr = [yy for yy in NW.YEARS if yy != y]; best = min(DG, key=lambda d: np.mean([st[d][yy][1] for yy in tr])); picks.append(best)
        o_r.append(st[best][y][0]); b_r.append(st[0.0][y][0]); o_m.append(st[best][y][1]); b_m.append(st[0.0][y][1]); wins += int(st[best][y][1] < st[0.0][y][1] - 1e-12)
    mq = out & top150 & (pos == ps); e0 = np.average((PS[mq] - act[mq]) ** 2, weights=wt[mq]); pooled = min(DG, key=lambda d: np.average((PS[mq] * (1 - d) - act[mq]) ** 2, weights=wt[mq]))
    print(f"   {ps}: picks {picks} | all rows: rank rho {np.mean(o_r)-np.mean(b_r):+.4f}, weighted MSE {(np.mean(o_m)/np.mean(b_m)-1)*100:+.3f}% ({wins}/7) | on the QB-out rows alone the best dock is {pooled:.2f} = {(np.average((PS[mq]*(1-pooled)-act[mq])**2, weights=wt[mq])/e0-1)*100:+.2f}% MSE")
