#!/usr/bin/env python3
"""
SNAP-SHARE LEVEL layer (shadow v2.25) - two follow-up checks before it is trusted for REST OF SEASON (2026-10-02).
backtest_shadow_next.py passed the layer for the NEXT game only, reading the last game's snap share as-is. Wired into
the engine it rode every remaining week, and a game a player LEFT HURT reads as a part-time role (Justin Jefferson
92 / 100 / 12 -> docked 21% for the whole season).

  1  EXIT GAMES   last game far under his own season share (under 60% of the share he had before it): what did he do
                  the next game he played, and which reading is better - the last game as-is, his season share, the
                  season share only when the last game looks like an exit, the larger of his last two games
  2  HORIZON      the same reading made h games ahead (1 = the tested case, 2, 3, 4-6, 7+): base = his rate at the
                  time x that week's layers, with and without the snap-level multiplier at e .3 / .15

Same harness and scoring as backtest_shadow_next.py (touched rows, plain squared error, seasons better).
Log snap_level_horizon.log.
"""
import os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
YEARS = SN.YEARS

def main():
    log = open(os.path.join(HERE, "snap_level_horizon.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n"); log.flush()
    X = SN.setup(); n = X["n"]; act, year, wk, pos, g, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["name"]
    SH = SN.shadow(X); layers = X["layers"]; l1 = X["snap_l1"]; sstd = X["snap_std"]
    finw = np.where(year <= 2020, 17, 18); allr = (wk != finw) & (SH >= 3)
    ms = lambda q, m: float(np.mean((q[m] - act[m]) ** 2)) if m.any() else np.nan
    # each player's rows in week order -> the row k games earlier
    seq = defaultdict(list)
    for i in range(n): seq[(name[i], pos[i], int(year[i]))].append(i)
    back = {}
    for k_, ix in seq.items():
        ix.sort(key=lambda i: wk[i])
        for a, i in enumerate(ix): back[i] = ix[:a]
    prev1 = np.array([back[i][-1] if back[i] else -1 for i in range(n)])
    l2 = np.where(prev1 >= 0, l1[np.maximum(prev1, 0)], np.nan)            # snap share two games ago
    std_before = np.where(prev1 >= 0, sstd[np.maximum(prev1, 0)], np.nan)  # season share before the last game
    wrte = np.isin(pos, ["WR", "TE"]) & (g >= 1) & ~np.isnan(l1)

    def dev_of(v, sh, rows):
        """deviation of v from the average of players at the same projection (8 bins per position), on `rows`"""
        d = np.zeros(n)
        for ps in ("WR", "TE"):
            m = rows & (pos == ps) & ~np.isnan(v)
            if m.sum() < 200: continue
            q = np.quantile(sh[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, sh, side="right") - 1, 0, 7)
            for k in range(8):
                mk = m & (b_ == k)
                if mk.sum() >= 30: d[mk] = v[mk] - np.nanmean(v[mk])
        return d
    mult = lambda d, e: np.clip(1 + e * d / 100.0, 0.7, 1.4)
    def line(lab, pred, base, m):
        if m.sum() < 30: P(f"    {lab:44s} n {int(m.sum())} (too few)"); return
        w = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and ms(pred, m & (year == y)) < ms(base, m & (year == y)) - 1e-12); ny = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8)
        P(f"    {lab:44s} n {int(m.sum()):5d}  actual {act[m].mean():5.2f}  base {base[m].mean():5.2f}  with layer {pred[m].mean():5.2f}  | error {100*(ms(pred, m)/ms(base, m)-1):+.2f}%  seasons better {w}/{ny}")

    # ---------------- 1 exit games ----------------
    P("=== 1 EXIT GAMES: last game under 60% of the snap share he had before it (WR + TE, had 50%+ before) ===")
    rows = wrte & allr
    exitm = rows & ~np.isnan(std_before) & (std_before >= 50) & (l1 < 0.6 * std_before)
    P(f"  rows {int(exitm.sum())} of {int(rows.sum())} ({100*exitm.sum()/rows.sum():.1f}%); share before {np.nanmean(std_before[exitm]):.0f}%, last game {np.nanmean(l1[exitm]):.0f}%, actual / shadow {act[exitm].sum()/SH[exitm].sum():.3f}  (everyone else {act[rows & ~exitm].sum()/SH[rows & ~exitm].sum():.3f})")
    guard = np.where(exitm, std_before, l1); two = np.fmax(l1, l2)
    readings = {"last game as-is (wired today)": l1, "season share": sstd, "season share when the last game is an exit": guard, "larger of his last two games": two}
    for lab, v in readings.items():
        d = dev_of(v, SH, rows)
        P(f"  reading = {lab}")
        for e in (0.3,):
            pr = SH * mult(d, e)
            line(f"e {e}: all WR / TE rows", pr, SH, rows & (np.abs(pr - SH) > 1e-9))
            line(f"e {e}: exit rows only", pr, SH, exitm)
            line(f"e {e}: top-100 ADP rows", pr, SH, rows & (X['adp'] <= 100) & (np.abs(pr - SH) > 1e-9))

    # ---------------- 2 horizon ----------------
    P("\n=== 2 HORIZON: the reading made h games ahead (base = his rate then x that week's layers) ===")
    for lab, v in (("last game as-is", l1), ("season share when the last game is an exit", guard)):
        d0 = dev_of(v, SH, rows)
        P(f"  reading = {lab}")
        for hlab, hs in (("1 game ahead (tested case)", [1]), ("2 games ahead", [2]), ("3 games ahead", [3]), ("4-6 games ahead", [4, 5, 6]), ("7+ games ahead", list(range(7, 17)))):
            src = np.full(n, -1)
            base = np.full(n, np.nan); m = np.zeros(n, bool)
            preds = {e: np.full(n, np.nan) for e in (0.3, 0.15)}
            for i in np.where(wrte & allr)[0]:
                bk = back[i]
                for h in hs:
                    if h == 1: j = i
                    elif len(bk) >= h - 1: j = bk[-(h - 1)]
                    else: continue
                    if not rows[j] or layers[j] <= 0: continue
                    b = SH[j] / layers[j] * layers[i]
                    base[i] = b; m[i] = abs(d0[j]) > 1e-9
                    for e in preds: preds[e][i] = b * mult(d0, e)[j]
                    break
            for e in (0.3, 0.15): line(f"{hlab}, e {e}", preds[e], base, m & ~np.isnan(base))
    log.close()

if __name__ == "__main__":
    main()
