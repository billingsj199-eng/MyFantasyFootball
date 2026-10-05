#!/usr/bin/env python3
"""
Should the docks apply to ELITE players? (Jack 2026-10-02: "elite players like jefferson should not be projected
very low if he plays".) Next-game harness, Clay-free model with the v2.29 layer set. By draft band (ADP 1-30 elite,
31-60, 61-150, later):
  1  the game after he left early (last game under 60% of his prior snap share) - with and without the snap-level dock
  2  the snap-share level dock in general (rows it lowers by 5%+)
  3  the first game back after missing games (3+ week gap between games) - the live return ramp is x.95 / .92 / .85
  4  listed Questionable and played
Log elite_docks.log.
"""
import os, sys
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
YEARS = SN.YEARS

def main():
    log = open(os.path.join(HERE, "elite_docks.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n"); log.flush()
    X = SN.setup(); n = X["n"]; A = X["A"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = A["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    smx = colv("snapmult"); smx = np.where(np.isnan(smx), 1.0, smx); repq = colv("rep_q") == 1
    SH = SN.shadow(X); finw = np.where(year <= 2020, 17, 18); allr = (wk != finw) & (SH >= 3)
    l1 = X["snap_l1"]; dev = np.zeros(n)
    for ps in ("WR", "TE"):
        m = (pos == ps) & (g >= 1) & ~np.isnan(l1) & allr
        q = np.quantile(SH[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, SH, side="right") - 1, 0, 7)
        for k in range(8):
            mk = m & (b_ == k)
            if mk.sum() >= 30: dev[mk] = l1[mk] - np.nanmean(l1[mk])
    lvl = np.where(np.isin(pos, ["WR", "TE"]), np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4), 1.0)
    trend = np.where(np.isin(pos, ["RB", "TE"]), smx, 1.0)
    NO = SH * trend; WITH = NO * lvl                      # without / with the snap-level layer (WR + TE)
    seq = defaultdict(list)
    for i in range(n): seq[(name[i], pos[i], int(year[i]))].append(i)
    prev = np.full(n, -1)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i])
        for a, i in enumerate(ix):
            if a: prev[i] = ix[a - 1]
    hasp = prev >= 0; pv = np.maximum(prev, 0)
    std_before = np.where(hasp, X["snap_std"][pv], np.nan); gap = np.where(hasp, wk - wk[pv], 0)
    exitm = ~np.isnan(std_before) & (std_before >= 50) & (l1 < 0.6 * std_before)
    BANDS = [("ADP 1-30 (elite)", adp <= 30), ("ADP 31-60", (adp > 30) & (adp <= 60)), ("ADP 61-150", (adp > 60) & (adp <= 150)), ("later / undrafted", ~(adp <= 150))]
    ms = lambda q, m: float(np.mean((q[m] - act[m]) ** 2))
    def table(title, m0, a_pred, b_pred=None, alab="projected", blab=None, minn=25):
        P(f"\n--- {title} ---")
        for lab, bm in BANDS:
            m = m0 & bm & allr
            if m.sum() < minn: P(f"    {lab:20s} n {int(m.sum()):4d} (too few)"); continue
            ys = [act[m & (year == y)].sum() / a_pred[m & (year == y)].sum() for y in YEARS if (m & (year == y)).sum() >= 5]
            s = f"    {lab:20s} n {int(m.sum()):4d}  actual {act[m].mean():5.2f}  {alab} {a_pred[m].mean():5.2f} -> actual / projected {act[m].sum()/a_pred[m].sum():.3f} (under in {sum(1 for v in ys if v < 1)}/{len(ys)} seasons)"
            if b_pred is not None:
                sb = sum(1 for y in YEARS if (m & (year == y)).sum() >= 5 and ms(b_pred, m & (year == y)) < ms(a_pred, m & (year == y)))
                s += f"  | {blab} {b_pred[m].mean():5.2f} -> {act[m].sum()/b_pred[m].sum():.3f}, error {100*(ms(b_pred, m)/ms(a_pred, m)-1):+.1f}% ({sb}/{len(ys)})"
            P(s)
    sk = np.isin(pos, ["WR", "TE"])
    table("1  THE GAME AFTER HE LEFT EARLY, WR + TE: no dock vs the snap-level dock", exitm & sk, NO, WITH, "no dock", "with the dock")
    table("1b THE GAME AFTER HE LEFT EARLY, RB (snap trend only)", exitm & (pos == "RB"), WITH, None, "projected")
    table("2  SNAP-LEVEL DOCK of 5%+ (WR + TE), any reason: no dock vs with", sk & (lvl <= 0.95), NO, WITH, "no dock", "with the dock", 40)
    table("2b SNAP-LEVEL BOOST of 5%+ (WR + TE): no boost vs with", sk & (lvl >= 1.05), NO, WITH, "no boost", "with the boost", 40)
    table("3  FIRST GAME BACK after a 3+ week gap (RB / WR / TE), no ramp applied", (gap >= 3) & np.isin(pos, ["RB", "WR", "TE"]), WITH, WITH * 0.92, "projected", "with a x.92 ramp")
    table("4  LISTED QUESTIONABLE AND PLAYED (RB / WR / TE), no dock applied", repq & np.isin(pos, ["RB", "WR", "TE"]), WITH, WITH * 0.90, "projected", "with a x.90 dock")
    log.close()

if __name__ == "__main__":
    main()
