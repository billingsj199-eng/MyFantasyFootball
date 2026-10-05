#!/usr/bin/env python3
"""
Does this season's points per game get more predictive as the season goes on? (Jack 2026-10-02)
Shadow harness rows 2019-25 (projection 3+, final week dropped). By games already played: the correlation of
season-to-date PPG with (a) the next game and (b) the per-game average over the rest of the season (3+ games left),
beside past-seasons history, ADP and usage-based expected points at the same stage. Log ppg_by_games.log.
"""
import os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN

def main():
    log = open(os.path.join(HERE, "ppg_by_games.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n"); log.flush()
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    SH = SN.shadow(X); finw = np.where(year <= 2020, 17, 18); ok = (wk != finw) & (SH >= 3)
    seq = defaultdict(list)
    for i in range(n):
        if wk[i] != finw[i]: seq[(name[i], pos[i], int(year[i]))].append(i)
    T = np.full(n, np.nan)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]
        for a, i in enumerate(ix):
            if len(ix) - a >= 3: T[i] = a_[a:].mean()
    ppg, hist, xf = X["ppg"], F["hist"], np.where(X["has_x"], X["xf"], np.nan); ladp = -np.log(np.where(np.isnan(adp), 260.0, adp))
    def r(a, b, m):
        m = m & ~np.isnan(a) & ~np.isnan(b)
        return np.corrcoef(a[m], b[m])[0, 1] if m.sum() >= 60 else np.nan
    f = lambda v: "  -  " if np.isnan(v) else f"{v:.2f}"
    B = [("1", 1, 1), ("2", 2, 2), ("3", 3, 3), ("4", 4, 4), ("5", 5, 5), ("6-7", 6, 7), ("8-10", 8, 10), ("11+", 11, 30)]
    for ps in ("QB", "RB", "WR", "TE"):
        P(f"\n##### {ps} #####")
        P("  games    rows |  NEXT GAME: season PPG   history   ADP    usage (xFP) |  REST OF SEASON: season PPG   history   ADP    usage (xFP)")
        for lab, lo, hi in B:
            m = ok & (pos == ps) & (g >= lo) & (g <= hi)
            if m.sum() < 80: continue
            P(f"  {lab:5s}  {int(m.sum()):5d} |             {f(r(ppg, act, m))}        {f(r(hist, act, m))}     {f(r(ladp, act, m))}     {f(r(xf, act, m))}     |                  {f(r(ppg, T, m))}        {f(r(hist, T, m))}     {f(r(ladp, T, m))}     {f(r(xf, T, m))}")
    # ---- why does the rest-of-season correlation dip late? (Jack: "late season breakouts or injuries") ----
    # Same question with the target held to a FIXED length (the next three games), so a shorter remaining schedule cannot be
    # the reason; then split by who the player is (young = rookie / second year) and by whether a teammate at his position
    # is out, or he is on the injury report, somewhere in those three games.
    import pandas as pd
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a_), b_, int(c_)): i for i, (a_, b_, c_) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b_, str)}
    pid = X["A"]["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    vcs, vts, vt, repq, y2 = colv("vac_car_same"), colv("vac_tgt_same"), colv("vac_tgt"), colv("rep_q") == 1, colv("yr2") == 1
    out_now = np.where(pos == "RB", vcs >= 0.20, np.where(pos == "WR", vts >= 0.15, np.where(pos == "TE", vt >= 0.15, False)))
    young = np.array(X["rookie"], dtype=bool) | y2
    T3 = np.full(n, np.nan); tm_out3 = np.zeros(n, bool); hurt3 = np.zeros(n, bool); nleft = np.zeros(n, int)
    for ix in seq.values():
        for a, i in enumerate(ix):
            nleft[i] = len(ix) - a
            if len(ix) - a >= 3:
                w3 = ix[a:a + 3]; T3[i] = act[w3].mean(); tm_out3[i] = out_now[w3].any(); hurt3[i] = repq[w3].any()
    B2 = [("3-5", 3, 5), ("6-7", 6, 7), ("8-10", 8, 10), ("11+", 11, 30)]
    P(); P("=== WHY THE LATE DIP? season PPG vs the NEXT THREE GAMES (fixed-length target) ===")
    for ps in ("QB", "RB", "WR", "TE"):
        P(f"  {ps}:  games   rows | next 3, everyone | young (rookie / 2nd year) | veterans | a teammate out in those games | none out | he is Questionable in them | healthy | games left (avg)")
        for lab, lo, hi in B2:
            m = ok & (pos == ps) & (g >= lo) & (g <= hi) & ~np.isnan(T3)
            if m.sum() < 80: continue
            P(f"        {lab:5s} {int(m.sum()):5d} |      {f(r(ppg, T3, m))}        |          {f(r(ppg, T3, m & young))}             |   {f(r(ppg, T3, m & ~young))}   |             {f(r(ppg, T3, m & tm_out3))}              |  {f(r(ppg, T3, m & ~tm_out3))}    |            {f(r(ppg, T3, m & hurt3))}            |  {f(r(ppg, T3, m & ~hurt3))}   |   {nleft[ok & (pos == ps) & (g >= lo) & (g <= hi) & ~np.isnan(T)].mean():.1f}")
    P(); P("  how much players move late: share of players whose next-3 average is 50%+ above / below their season PPG (season PPG 5+)")
    for ps in ("QB", "RB", "WR", "TE"):
        out = []
        for lab, lo, hi in B2:
            m = ok & (pos == ps) & (g >= lo) & (g <= hi) & ~np.isnan(T3) & (ppg >= 5)
            if m.sum() < 80: continue
            out.append(f"{lab}: up {100*(T3[m] >= 1.5 * ppg[m]).mean():.0f}% / down {100*(T3[m] <= 0.5 * ppg[m]).mean():.0f}% (young up {100*(T3[m & young] >= 1.5 * ppg[m & young]).mean():.0f}%)")
        P(f"    {ps}: " + "   ".join(out))
    log.close()

if __name__ == "__main__":
    main()
