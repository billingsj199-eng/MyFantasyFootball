#!/usr/bin/env python3
"""
GARBAGE-TIME REGRESSION backtest, 2019-2025 (Jack 2026-09-15: "lets do it").
Points scored down (or up) big late are game-script luck. Does a player whose
season-to-date average leans on them regress, the way TD luck does?

Garbage time = 4th quarter with |score differential| >= 17 (also tested: 2nd
half with |diff| >= 21). Fantasy points per play from pbp (half-PPR: rec .5,
yds .1, TD 6; passing .04/yd, 4/TD). Per player season-to-date (weeks < W):
  gt_ppg   garbage-time points per game
  gt_share gt points / all pbp points
Gate: gt_share persistence early->late and YoY. LOYO: shipped - k x gt_ppg x
g/(P+g)  (remove a fraction of the garbage points from the realized half).
Log: garbage_time_backtest.log
"""
import numpy as np
import pandas as pd
import os
from collections import defaultdict
from bt_common import iter_samples, to_arrays, loyo, mse, YEARS, LOAD_YEARS, POS4, CACHE, P

def load_points(Y):
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"),
                     usecols=["season_type", "week", "qtr", "score_differential", "pass_attempt", "rush_attempt", "sack", "complete_pass",
                              "yards_gained", "pass_touchdown", "rush_touchdown", "passer_player_id", "receiver_player_id", "rusher_player_id"],
                     low_memory=False)
    df = df[df.season_type == "REG"]
    sd = df.score_differential.fillna(0).abs()
    gt = (df.qtr == 4) & (sd >= 17)
    gt2 = (df.qtr >= 3) & (sd >= 21)
    rows = []
    comp = df.complete_pass.fillna(0); yg = df.yards_gained.fillna(0)
    # receivers
    m = (df.pass_attempt == 1) & (df.sack != 1) & df.receiver_player_id.notna()
    rec_pts = 0.5 * comp + 0.1 * yg * comp + 6 * df.pass_touchdown.fillna(0)
    rows.append(pd.DataFrame({"pid": df.receiver_player_id[m], "week": df.week[m], "pts": rec_pts[m], "isgt": gt[m], "isgt2": gt2[m]}))
    # rushers
    m = (df.rush_attempt == 1) & df.rusher_player_id.notna()
    ru_pts = 0.1 * yg + 6 * df.rush_touchdown.fillna(0)
    rows.append(pd.DataFrame({"pid": df.rusher_player_id[m], "week": df.week[m], "pts": ru_pts[m], "isgt": gt[m], "isgt2": gt2[m]}))
    # passers
    m = (df.pass_attempt == 1) & (df.sack != 1) & df.passer_player_id.notna()
    pa_pts = 0.04 * yg * comp + 4 * df.pass_touchdown.fillna(0)
    rows.append(pd.DataFrame({"pid": df.passer_player_id[m], "week": df.week[m], "pts": pa_pts[m], "isgt": gt[m], "isgt2": gt2[m]}))
    t = pd.concat(rows, ignore_index=True); t["season"] = Y
    t["gtp"] = t.pts * t.isgt; t["gtp2"] = t.pts * t.isgt2
    return t.groupby(["season", "pid", "week"]).agg(pts=("pts", "sum"), gtp=("gtp", "sum"), gtp2=("gtp2", "sum")).reset_index()

def main():
    pw = pd.concat([load_points(Y) for Y in LOAD_YEARS], ignore_index=True)
    print(f"  garbage-time share of all fantasy points (pbp basis): {pw.gtp.sum()/pw.pts.sum():.1%} (4Q |diff|>=17) | {pw.gtp2.sum()/pw.pts.sum():.1%} (2H |diff|>=21)")
    look = {}; season = {}
    for (s, pid), grp in pw.sort_values("week").groupby(["season", "pid"]):
        cum = {"pts": 0.0, "gtp": 0.0, "gtp2": 0.0, "g": 0}; lst = []
        for r in grp.itertuples(index=False):
            cum["pts"] += r.pts; cum["gtp"] += r.gtp; cum["gtp2"] += r.gtp2; cum["g"] += 1
            lst.append((int(r.week), dict(cum)))
        look[(s, pid)] = lst; season[(s, pid)] = dict(cum)
    print("\n=== GATE. garbage-time share persistence ===")
    a, b = [], []
    for (Y, pid), c in season.items():
        n = season.get((Y + 1, pid))
        if n and c["g"] >= 10 and n["g"] >= 10 and c["pts"] >= 60 and n["pts"] >= 60:
            a.append(c["gtp"] / c["pts"]); b.append(n["gtp"] / n["pts"])
    print(f"  YoY r = {np.corrcoef(a,b)[0,1]:+.2f} (n={len(a)}, mean share {np.mean(a):.1%})")
    a, b = [], []
    for (Y, pid), lst in look.items():
        c8 = None
        for w, c in lst:
            if w <= 8: c8 = c
        cE = lst[-1][1]
        if c8 and c8["g"] >= 5 and cE["g"] - c8["g"] >= 5 and c8["pts"] >= 30 and cE["pts"] - c8["pts"] >= 30:
            a.append(c8["gtp"] / c8["pts"]); b.append((cE["gtp"] - c8["gtp"]) / (cE["pts"] - c8["pts"]))
    print(f"  early->late r = {np.corrcoef(a,b)[0,1]:+.2f} (n={len(a)})")

    S = iter_samples(POS4)
    A = to_arrays(S)
    years = sorted(set(A["year"]))
    gtppg = np.full(len(S), np.nan); gtsh = np.full(len(S), np.nan); gtppg2 = np.full(len(S), np.nan)
    for i, s in enumerate(S):
        if not s["pid"]: continue
        prev = None
        for w, c in look.get((s["year"], s["pid"]), []):
            if w < s["wk"]: prev = c
            else: break
        if prev and prev["g"]:
            gtppg[i] = prev["gtp"] / prev["g"]; gtppg2[i] = prev["gtp2"] / prev["g"]
            gtsh[i] = prev["gtp"] / prev["pts"] if prev["pts"] > 0 else 0.0
    ok = ~np.isnan(gtppg)
    print(f"\n{ok.sum()} player-weeks with garbage-time history | shipped MSE {mse(A['shipped'][ok], A['act'][ok]):.4f}")
    act, ship = A["act"], A["shipped"]; wreal = A["g"] / (P + A["g"])
    print("\n=== 1. actual / shipped by garbage-time points-per-game tercile (per position) ===")
    for p in POS4:
        m = ok & (A["pos"] == p); x = gtppg[m]; q = np.quantile(x, [1/3, 2/3]); parts = []
        for lo, hi, lab in ((-np.inf, q[0], "low"), (q[0], q[1], "mid"), (q[1], np.inf, "high")):
            mm = m & (gtppg >= lo) & (gtppg < hi)
            parts.append(f"{lab} {gtppg[mm].mean():.2f}/g: {act[mm].mean()/ship[mm].mean():.3f} (n={mm.sum()})")
        print(f"  {p}: " + " | ".join(parts) + f"   corr(gt ppg, act-ship) {np.corrcoef(x, act[m]-ship[m])[0,1]:+.3f}")
    print("\n=== 2. LOYO: shipped - k * gt_ppg * g/(P+g)  (grid[0] = shipped) ===")
    Sok = {"year": A["year"][ok], "act": act[ok]}; sh = ship[ok]; g1 = np.nan_to_num(gtppg[ok]); g2 = np.nan_to_num(gtppg2[ok]); wr = wreal[ok]
    grid = [0.0, 0.25, 0.5, 0.75, 1.0]
    loyo(Sok, years, grid, lambda k: sh - k * g1 * wr, "a) 4Q |diff|>=17 garbage points removed from the realized half")
    loyo(Sok, years, grid, lambda k: sh - k * g2 * wr, "b) 2H |diff|>=21 variant")
    for p in POS4:
        m = (A["pos"][ok] == p)
        Sp = {"year": Sok["year"][m], "act": Sok["act"][m]}
        loyo(Sp, years, grid, lambda k, m=m: (sh - k * g1 * wr)[m], f"   {p} (a)")
    # centered control
    gc = g1.copy()
    for y in years:
        for p in POS4:
            m = (Sok["year"] == y) & (A["pos"][ok] == p); gc[m] = g1[m] - g1[m].mean()
    loyo(Sok, years, grid, lambda k: sh - k * gc * wr, "c) (a) centered per season x position (pure regression, no level)")

if __name__ == "__main__":
    main()
