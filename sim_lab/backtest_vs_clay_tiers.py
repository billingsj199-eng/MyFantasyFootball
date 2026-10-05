#!/usr/bin/env python3
"""
Clay-free model vs the Clay blend by TIER (Jack 2026-10-02: "show the top 10 vs top 30 vs top 60 vs top 100 after top
100 players arent very important"). 2019-25, next game (weeks 2-17) and rest of season (3-10 games played).
Tiers two ways: by preseason ADP (picks 1-10, 11-30, 31-60, 61-100) and by the model's own weekly projection rank
across all positions (top 10, 11-30, 31-60, 61-100 that week). Then by position rank (QB1-6 ...).
Per tier: typical miss (points), error vs the Clay blend (%, seasons better), level (actual / projected) for both,
rank order within position. Log vs_clay_tiers.log.
"""
import os, sys
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
YEARS = SN.YEARS; POS4 = ("QB", "RB", "WR", "TE")

def main():
    log = open(os.path.join(HERE, "vs_clay_tiers.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n"); log.flush()
    X = SN.setup(); n = X["n"]; F = X["F"]; A = X["A"]
    act, year, wk, pos, g, adp, name, layers = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["layers"]
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = A["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    smx = colv("snapmult"); smx = np.where(np.isnan(smx), 1.0, smx); y2 = colv("yr2") == 1
    SH = SN.shadow(X); finw = np.where(year <= 2020, 17, 18); final = wk == finw
    l1 = X["snap_l1"]; dev = np.zeros(n); allr0 = ~final & (SH >= 3)
    for ps in ("WR", "TE"):
        m = (pos == ps) & (g >= 1) & ~np.isnan(l1) & allr0; q = np.quantile(SH[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, SH, side="right") - 1, 0, 7)
        for k in range(8):
            mk = m & (b_ == k)
            if mk.sum() >= 30: dev[mk] = l1[mk] - np.nanmean(l1[mk])
    low = np.maximum(0, 19 - np.nan_to_num(X["implied"], nan=19)) / 19
    lvl = np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4); lvl = np.where(adp <= 30, np.maximum(1.0, lvl), lvl)
    EX = np.where(np.isin(pos, ["RB", "TE"]), smx, 1.0) * np.where(np.isin(pos, ["WR", "TE"]), lvl, 1.0) * np.where((pos == "QB") & X["mover"], 0.90, 1.0) * np.where(pos == "QB", 1 - 0.75 * low, 1.0) * np.where((pos == "RB") & (g >= 2) & (g <= 5) & (X["car_sh"] < 0.30), 0.90, 1.0)
    NX = SH * EX; CL = F["shipped"]
    # rest of season
    seq = defaultdict(list)
    for i in range(n):
        if not final[i]: seq[(name[i], pos[i], int(year[i]))].append(i)
    T = np.full(n, np.nan); ctx = np.full(n, np.nan)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(layers[ix], 0.5, 1.8)
        for a, i in enumerate(ix):
            if len(ix) - a >= 3: T[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    base_lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    mid = (adp > 60) & (adp <= 100); late = (adp > 100) & (adp <= 150)
    lam_r = np.where((pos == "WR") & late, np.minimum(base_lam, 0.25), base_lam); ev_r = lam_r * X["xf"] + (1 - lam_r) * X["ppg_v"]
    pm = np.where((pos == "RB") & mid, 2.5, np.where((pos == "WR") & mid, 0.6, np.where((pos == "QB") & y2, 0.75, 1.0))); pm = np.where((pos == "WR") & late & (ev_r < X["prior"]), pm * 0.4, pm)
    Pw = X["Pw"] * pm; rate = (Pw * X["prior"] + g * ev_r) / np.maximum(Pw + g, 1e-9)
    RS = rate * ctx * np.where(pos == "RB", smx, 1.0) * np.where((pos == "QB") & X["mover"], 0.84, 1.0) * np.where(pos == "TE", lvl, 1.0)
    CR = CL / np.where(layers > 0, layers, 1.0) * ctx
    okR = ~np.isnan(T) & (g >= 3) & (g <= 10) & (RS >= 3)
    # weekly projection rank across all positions (by our number) and by Clay's
    prank = np.full(n, 9999); crank = np.full(n, 9999)
    for (y_, w_), ix in pd.DataFrame({"y": year, "w": wk}).groupby(["y", "w"]).groups.items():
        ix = np.array(list(ix)); m = ix[~final[ix]]
        prank[m] = rankdata(-NX[m], method="ordinal"); crank[m] = rankdata(-CL[m], method="ordinal")
    def rho(p_, m, tgt):
        gr = defaultdict(list)
        for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        rh = [np.corrcoef(rankdata(tgt[ix]), rankdata(p_[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 6]
        return float(np.mean(rh)) if rh else np.nan
    def block(title, tiers, ours, clay, tgt, okm):
        P(f"\n--- {title} ---")
        P(f"    {'tier':30s} rows  | typical miss ours / Clay | error vs Clay (seasons better) | level ours / Clay | rank order ours / Clay")
        for lab, m in tiers:
            m = m & okm
            if m.sum() < 60: P(f"    {lab:30s} n {int(m.sum()):4d} (too few)"); continue
            e1 = (ours[m] - tgt[m]) ** 2; e2 = (clay[m] - tgt[m]) ** 2
            w = sum(1 for y_ in YEARS if (m & (year == y_)).sum() >= 10 and ((ours - tgt) ** 2)[m & (year == y_)].mean() < ((clay - tgt) ** 2)[m & (year == y_)].mean()); ny = sum(1 for y_ in YEARS if (m & (year == y_)).sum() >= 10)
            P(f"    {lab:30s} {int(m.sum()):5d} |     {np.sqrt(e1.mean()):5.2f} / {np.sqrt(e2.mean()):5.2f}        |   {100*(e1.mean()/e2.mean()-1):+6.2f}% ({w}/{ny})            |  {tgt[m].sum()/ours[m].sum():.3f} / {tgt[m].sum()/clay[m].sum():.3f}  |  {rho(ours, m, tgt):.3f} / {rho(clay, m, tgt):.3f}")
    ADP = [("ADP 1-10", adp <= 10), ("ADP 11-30", (adp > 10) & (adp <= 30)), ("ADP 31-60", (adp > 30) & (adp <= 60)), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150 (less important)", (adp > 100) & (adp <= 150))]
    PR = [("our top 10 that week", prank <= 10), ("our 11-30", (prank > 10) & (prank <= 30)), ("our 31-60", (prank > 30) & (prank <= 60)), ("our 61-100", (prank > 60) & (prank <= 100)), ("our 101-150", (prank > 100) & (prank <= 150))]
    CPR = [("Clay's top 10 that week", crank <= 10), ("Clay's 11-30", (crank > 10) & (crank <= 30)), ("Clay's 31-60", (crank > 30) & (crank <= 60)), ("Clay's 61-100", (crank > 60) & (crank <= 100))]
    okN = ~final & (wk >= 2) & (np.maximum(NX, CL) >= 3)
    P(f"=== Clay-free model (as wired) vs the Clay blend, by tier; 2019-25; typical miss = root mean squared error in points ===")
    block("NEXT GAME, by preseason ADP", ADP, NX, CL, act, okN)
    block("NEXT GAME, by OUR weekly projection rank (all positions)", PR, NX, CL, act, okN)
    block("NEXT GAME, by CLAY'S weekly projection rank", CPR, NX, CL, act, okN)
    block("REST OF SEASON (3-10 games played), by preseason ADP", ADP, RS, CR, np.nan_to_num(T), okR)
    POSR = []
    for ps, cuts in (("QB", (6, 12, 24)), ("RB", (12, 24, 48)), ("WR", (12, 24, 48)), ("TE", (6, 12, 24))):
        pr_ = np.full(n, 9999)
        for (y_, w_), ix in pd.DataFrame({"y": year, "w": wk}).groupby(["y", "w"]).groups.items():
            ix = np.array(list(ix)); m = ix[(~final[ix]) & (pos[ix] == ps)]
            if len(m): pr_[m] = rankdata(-NX[m], method="ordinal")
        lo_ = 0
        for c in cuts: POSR.append((f"{ps}{lo_+1}-{c} (our rank)", (pos == ps) & (pr_ > lo_) & (pr_ <= c))); lo_ = c
    block("NEXT GAME, by OUR position rank that week", POSR, NX, CL, act, okN)
    log.close()

if __name__ == "__main__":
    main()
