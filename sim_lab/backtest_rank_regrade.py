#!/usr/bin/env python3
"""
RANK RE-GRADE of the 2026-10-07 shipped layers (Jack 2026-10-08: "run 1 and 2").  Every pass yesterday was judged on
importance-weighted squared error; the standing objective is weekly within-position RANK order in the top 150
(feedback_inseason_rank_objective). This re-reads the base blend, the volume context and the box count on the rank
objective (mean Spearman over (season, week, position) groups of 8+ rows, and % of pairs ordered right), whole board
and by position / season. Layers already carrying a rank reading in their own logs (banged-up prior lift, hurt games in
usage, TE usage from game 1: qb_injury_usage*.log 'rank' column) are not recomputed; the two shadow harnesses get the
same line via patch_rank_grade.py. Log rank_regrade.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import backtest_volume_context as VC
import backtest_box_context as BX
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "rank_regrade.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
BBW = {"QB": 0.5, "RB": 0.8, "WR": 0.7, "TE": 0.3}


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, team, pid = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["team"], F["A"]["pid"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    bw = np.array([BBW[p_] for p_ in pos]); BLENDP = bw * SHADOW + (1 - bw) * TODAY; BLEND7 = 0.7 * SHADOW + 0.3 * TODAY
    base = top150 & ~final & ~LV["inh"]
    wm = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    RS = lambda p, m: RG.rank_stats(p, m, act, year, wk, pos)
    def row(lab, p, ref, m):
        r, pr = RS(p, m); r0, p0 = RS(ref, m); wins = RG.rank_seasons(p, ref, m, act, year, wk, pos, YEARS)
        ew = sum(1 for y in YEARS if wm(p, m & (year == y)) < wm(ref, m & (year == y)) - 1e-12)
        P(f"  {lab:44s} rho {r:.4f} ({r - r0:+.4f}, better in {wins}/7) | pairs {pr:.2f}% ({pr - p0:+.2f}) | wtd error {100*(wm(p, m)/wm(ref, m)-1):+.2f}% ({ew}/7)")
    P(f"=== RANK RE-GRADE: {int(base.sum()):,} top-150 player-weeks 2019-25, final week dropped, next game pre-book ===")
    P("\n--- 1  BASE BLEND (vs TODAY = live form before the blend) ---")
    for lab, p in (("TODAY (live pre-book)", TODAY), ("shadow alone", SHADOW), ("blend flat .7", BLEND7), ("blend per position .5/.8/.7/.3 (wired)", BLENDP)): row(lab, p, TODAY, base)
    for ps in POS4:
        P(f"  {ps}:")
        for lab, p in (("shadow alone", SHADOW), ("blend flat .7", BLEND7), ("blend per position (wired)", BLENDP)): row("   " + lab, p, TODAY, base & (pos == ps))
    P("  by ADP band, blend per position vs TODAY:")
    for lab, cm in (("ADP 1-30", adpx <= 30), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100)), ("101-150", adpx > 100)): row("   " + lab, BLENDP, TODAY, base & cm)
    # ---------------- 2 volume context on the blended base (shipped: script excess .03 all WR/TE, att/g .04 underdogs, clip .8-1.2)
    TW = VC.load_team_weeks(YEARS)
    okN = base & (g >= 1) & (BLENDP >= 3); RECV = np.isin(pos, ("WR", "TE"))
    attpg = np.full(n, np.nan); exc = np.full(n, np.nan)
    for i in range(n):
        if not okN[i] or not team[i]: continue
        Y = int(year[i]); rows = [TW[(Y, team[i], w)] for w in range(1, int(wk[i])) if (Y, team[i], w) in TW]
        if len(rows) < 2: continue
        a = np.sum(rows, axis=0); gms = len(rows); attpg[i] = a[1] / gms; nrate = a[3] / max(a[2], 1); exc[i] = attpg[i] - nrate * (a[0] / gms)
    def zweek(M, grp):
        z = np.full(n, np.nan)
        for y in YEARS:
            for w in range(1, 19):
                m = okN & (year == y) & (wk == w) & ~np.isnan(M) & grp
                if m.sum() >= 20 and np.nanstd(M[m]) > 0: z[m] = np.clip((M[m] - np.nanmean(M[m])) / np.nanstd(M[m]), -2.5, 2.5)
        return z
    za, zb = zweek(attpg, RECV), zweek(exc, RECV)
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    spread = np.where(has, C["spread"].values[np.maximum(idx, 0)], np.nan).astype(float); und = ~np.isnan(spread) & (spread > 0)
    def vol(p0, eb=0.03, ef=0.04):
        p = p0.copy(); mm = okN & RECV & ~np.isnan(zb); p[mm] = p[mm] * np.clip(1 - eb * zb[mm], 0.8, 1.2)
        mm2 = okN & RECV & und & ~np.isnan(za); p[mm2] = p[mm2] * np.clip(1 - ef * za[mm2], 0.8, 1.2); return p
    # box count faced (shipped: 1 + .04 z, WR/TE ADP <= 60, clip .85-1.15)
    part = BX.load(); boxr = np.full(n, np.nan)
    for i in np.where(okN)[0]:
        Y = int(year[i]); rows = [part[(Y, team[i], w)] for w in range(1, int(wk[i])) if (Y, team[i], w) in part]
        if len(rows) < 2: continue
        a = np.sum(rows, axis=0)
        if a[0] >= 40: boxr[i] = a[1] / a[0]
    zbox = zweek(boxr, RECV)
    def box(p0, e=0.04, maxadp=60):
        p = p0.copy(); mm = okN & RECV & ~np.isnan(zbox) & (adpx <= maxadp); p[mm] = p[mm] * np.clip(1 + e * zbox[mm], 0.85, 1.15); return p
    VOL = vol(BLENDP); BOX = box(BLENDP); BOTH = box(vol(BLENDP))
    P("\n--- 2  VOLUME CONTEXT + BOX COUNT on the wired blend (vs the blend alone) ---")
    mv = okN & RECV & ~np.isnan(zb); mb = okN & RECV & ~np.isnan(zbox) & (adpx <= 60)
    P(f"  rows touched: volume {int(mv.sum()):,} WR/TE, box {int(mb.sum()):,} WR/TE ADP<=60")
    P("  whole top-150 board:")
    for lab, p in (("volume (script excess .03 + att/g .04 underdogs)", VOL), ("box (.04 z, ADP<=60)", BOX), ("volume + box (as wired)", BOTH)): row("   " + lab, p, BLENDP, base)
    P("  WR / TE rows only:")
    for lab, p in (("volume", VOL), ("box", BOX), ("volume + box", BOTH)): row("   " + lab, p, BLENDP, base & RECV)
    for ps in ("WR", "TE"):
        for lab, p in (("volume", VOL), ("box", BOX), ("volume + box", BOTH)): row(f"   {ps} {lab}", p, BLENDP, base & (pos == ps))
    P("  by ADP band (WR/TE), volume + box:")
    for lab, cm in (("ADP 1-30", adpx <= 30), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100)), ("101-150", adpx > 100)): row("   " + lab, BOTH, BLENDP, base & RECV & cm)
    P("  forward seasons 2022-25, whole board:")
    for lab, p in (("blend per position vs TODAY", (BLENDP, TODAY)), ("volume + box vs blend", (BOTH, BLENDP))):
        m = base & (year >= 2022); r, pr = RS(p[0], m); r0, p0 = RS(p[1], m); wins = sum(1 for y in FWD if RS(p[0], m & (year == y))[0] > RS(p[1], m & (year == y))[0] + 1e-12)
        P(f"   {lab:44s} rho {r:.4f} ({r - r0:+.4f}, better in {wins}/4) | pairs {pr:.2f}% ({pr - p0:+.2f})")
    P("\n--- 3  FULL STACK vs the live form: TODAY -> blend -> + volume + box, by season (rank rho) ---")
    P("  " + f"{'season':8s}" + "".join(f"{lab:>14s}" for lab in ("TODAY", "blend", "+vol+box")))
    for y in YEARS:
        m = base & (year == y); P(f"  {y:<8d}" + "".join(f"{RS(p, m)[0]:>14.4f}" for p in (TODAY, BLENDP, BOTH)))
    P("\nNot in this replica: book anchor, pecking dock, banged-up prior lift, QB window fix (no history test), shadow healthy history / shadow volume (see shadow_*_rank.log).")
    LOG.close()


if __name__ == "__main__":
    main()
