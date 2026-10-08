#!/usr/bin/env python3
"""
WHICH TIGHT ENDS DOES THE SHADOW UNDER-PROJECT, AND WHY? (Jack 2026-10-08: "what type of TEs are below - is it because of TDs?
are we not factoring routes enough? are they on good offenses?"). Top-150 TE player-weeks 2019-25, honest shadow replica.
Horizons: next game (actual / shadow) and rest of season (4+ games left; actual average / rescaled shadow).
Cuts: touchdown dependence (season-to-date TD points share, prior-season TD rate), route rate, target share, red-zone target
share, team implied total and pass rate, ADP band, games played, experience, snap level, scoring over usage.
Decomposition: future TD points per game vs own past TD rate, and non-TD points vs own past - is the miss TDs or volume?
Log te_bias.log. Research only.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
SN = BR.SN; cal = SN.NW.cal; YEARS = BR.YEARS; POS4 = BR.POS4
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "te_bias.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, g, adp, name, pid = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], A["pid"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X); L = X["layers"]
    TE = (pos == "TE") & top150 & ~final & ~LV["inh"] & (SHADOW >= 3)
    # rest-of-season target
    seqn = defaultdict(list)
    for i in range(n):
        if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ix in seqn.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(L[ix], 0.5, 1.8)
        for a, i in enumerate(ix): nfut[i] = len(ix) - a; Tr[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    ctx0 = np.nan_to_num(ctx, nan=1.0); SR = SHADOW / np.maximum(L, 0.3) * ctx0; TR = TE & (g >= 1) & (g <= 10) & ~np.isnan(Tr) & (nfut >= 4)
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    cv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    from backtest_inseason_usage import route_features
    rt, _ = route_features(year, pid, wk)
    tsh, rz, imp, proe, snap, xfp, expy = cv("tgt_sh"), cv("rz_tgt_sh"), cv("implied"), cv("proe_std"), cv("snap_std"), cv("xfp_pg"), cv("exp")
    # game logs: TD points vs non-TD points per game, season to date and future
    logs = {}
    def gl(nm, Y):
        k = (nm, Y)
        if k not in logs:
            rec = cal.weekly_rec(nm, "TE"); out = {}
            for w in (rec or {}).get("seasons", {}).get(str(Y), []):
                if cal.played(w) and isinstance(w.get("fpts"), (int, float)): out[int(w["wk"])] = (6 * float(w.get("rctd") or 0) + 6 * float(w.get("rtd") or 0), float(w["fpts"]) - 6 * float(w.get("rctd") or 0) - 6 * float(w.get("rtd") or 0), float(w.get("tgt") or 0))
            logs[k] = out
        return logs[k]
    tdsh = np.full(n, np.nan); td_past = np.full(n, np.nan); td_fut = np.full(n, np.nan); non_past = np.full(n, np.nan); non_fut = np.full(n, np.nan); td_py = np.full(n, np.nan)
    for i in np.where(TE)[0]:
        Y = int(year[i]); g_ = gl(name[i], Y); past = [g_[w] for w in g_ if w < wk[i]]; fut = [g_[w] for w in g_ if w >= wk[i]]
        if past:
            tp = np.mean([p_[0] for p_ in past]); npp = np.mean([p_[1] for p_ in past]); td_past[i] = tp; non_past[i] = npp; tdsh[i] = tp / max(tp + npp, 0.1)
        if fut: td_fut[i] = np.mean([f[0] for f in fut]); non_fut[i] = np.mean([f[1] for f in fut])
        gp = gl(name[i], Y - 1)
        if len(gp) >= 6: td_py[i] = np.mean([v[0] for v in gp.values()])
    def cutline(lab, m):
        mn = TE & m; mr = TR & m
        if mn.sum() < 40: return
        P(f"  {lab:40s} n{int(mn.sum()):5d} | next act/shadow {act[mn].sum()/SHADOW[mn].sum():.3f} (Clay {act[mn].sum()/TODAY[mn].sum():.3f}) | ROS act/shadow {Tr[mr].sum()/SR[mr].sum() if mr.sum() else float('nan'):.3f} n{int(mr.sum())} | TD pts/g past {np.nanmean(td_past[mn]):.2f} -> future {np.nanmean(td_fut[mn]):.2f} | non-TD past {np.nanmean(non_past[mn]):.2f} -> future {np.nanmean(non_fut[mn]):.2f}")
    def q(v, m, k=4):
        qs = np.nanpercentile(v[m & ~np.isnan(v)], np.linspace(0, 100, k + 1)); return [(f"Q{j+1} {qs[j]:.2f}-{qs[j+1]:.2f}", m & (v >= qs[j]) & (v < qs[j + 1] + (1e-9 if j == k - 1 else 0))) for j in range(k)]
    P(f"=== TE BIAS: {int(TE.sum()):,} top-150 TE player-weeks | next act/shadow {act[TE].sum()/SHADOW[TE].sum():.3f} (Clay {act[TE].sum()/TODAY[TE].sum():.3f}) | ROS act/shadow {Tr[TR].sum()/SR[TR].sum():.3f} ===")
    P("\n--- 1  TOUCHDOWN DEPENDENCE ---")
    for lab, m in q(tdsh, TE & (g >= 2)): cutline("TD share of points so far " + lab, m)
    for lab, m in q(td_py, TE & ~np.isnan(td_py)): cutline("prior-season TD pts/g " + lab, m)
    P("\n--- 2  ROUTES / TARGETS / RED ZONE ---")
    for lab, m in q(rt, TE & (g >= 1) & ~np.isnan(rt)): cutline("route rate " + lab, m)
    for lab, m in q(tsh, TE & (g >= 1) & ~np.isnan(tsh)): cutline("target share " + lab, m)
    for lab, m in q(rz, TE & (g >= 2) & ~np.isnan(rz)): cutline("red-zone target share " + lab, m)
    for lab, m in q(snap, TE & (g >= 1) & ~np.isnan(snap)): cutline("snap share " + lab, m)
    P("\n--- 3  OFFENSE QUALITY ---")
    for lab, m in q(imp, TE & ~np.isnan(imp)): cutline("team implied total " + lab, m)
    for lab, m in q(proe, TE & (g >= 2) & ~np.isnan(proe)): cutline("team pass rate over expected " + lab, m)
    P("\n--- 4  PLAYER TYPE ---")
    for lab, m in (("ADP 1-30", adpx <= 30), ("ADP 31-60", (adpx > 30) & (adpx <= 60)), ("ADP 61-100", (adpx > 60) & (adpx <= 100)), ("ADP 101-150", adpx > 100), ("rookies", X["rookie"]), ("2nd year", expy == 1), ("years 3-5", (expy >= 2) & (expy <= 4)), ("6+ years", expy >= 5), ("games 1-3", (g >= 1) & (g <= 3)), ("games 4-8", (g >= 4) & (g <= 8)), ("games 9+", g >= 9)): cutline(lab, m)
    sou = np.where(TE & (g >= 2) & (xfp > 0), X["ppg"] / np.maximum(xfp, 0.1), np.nan)
    for lab, m in q(sou, TE & ~np.isnan(sou)): cutline("scoring over usage " + lab, m)
    P("\n--- 5  DECOMPOSITION of the rest-of-season miss (TE rows with 2+ games, 4+ left): where do the extra points come from? ---")
    m = TR & (g >= 2) & ~np.isnan(td_fut) & ~np.isnan(td_past)
    P(f"  future per game: TD pts {np.nanmean(td_fut[m]):.2f} vs past {np.nanmean(td_past[m]):.2f} ({np.nanmean(td_fut[m]) - np.nanmean(td_past[m]):+.2f}) | non-TD {np.nanmean(non_fut[m]):.2f} vs past {np.nanmean(non_past[m]):.2f} ({np.nanmean(non_fut[m]) - np.nanmean(non_past[m]):+.2f}) | miss (Tr - shadow ROS) {np.nanmean(Tr[m] - SR[m]):+.2f}")
    for lab, mm in (("TD share so far under 25%", m & (tdsh < 0.25)), ("TD share 25-45%", m & (tdsh >= 0.25) & (tdsh < 0.45)), ("TD share 45%+", m & (tdsh >= 0.45))):
        if mm.sum() < 40: continue
        P(f"    {lab:28s} n{int(mm.sum()):4d} | TD {np.nanmean(td_past[mm]):.2f} -> {np.nanmean(td_fut[mm]):.2f} | non-TD {np.nanmean(non_past[mm]):.2f} -> {np.nanmean(non_fut[mm]):.2f} | act/shadow ROS {Tr[mm].sum()/SR[mm].sum():.3f} | miss {np.nanmean(Tr[mm] - SR[mm]):+.2f}")
    P("\nLimitations: replica shadow (TE docks halved on the next-game form); ROS = rescaled next-game number; route rate from route_features; all cuts are correlations, not layer tests.")
    LOG.close()


if __name__ == "__main__":
    main()
