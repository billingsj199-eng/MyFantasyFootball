#!/usr/bin/env python3
"""
Backtest the QB/TE (and K-analog) bye-hole fills — when a league-sim team has
no playable body for a strict slot, the engine claims the best UNROSTERED
player at his engine-projected mean. Two questions:

1. CALIBRATION: does the k-th best waiver player actually score his
   projection? (proj = Clay preseason half-PPR pts / 17 — the level term of
   the engine's weekly mean; Vegas reshuffling is already validated
   separately.) If realized/projected ~= 1 the fill prices honestly; if
   waiver-caliber players systematically underperform their preseason
   projection, fills need a haircut.

2. LEAGUE-SIZE SENSITIVITY: sweep how many players are rostered (10-team
   shallow vs 14-team deep vs superflex-deep rooms). The engine derives its
   pool from the actual league's unrostered list, so this sweep tells us what
   replacement level it will hand each league shape — and whether the
   calibration holds as the pool thins.

Rostered = top-R by Clay projection (managers draft the perceived best).
Available in week wk = has a played stat row that week (managers see
inactives before lock; engine equivalently skips bye/IR/Out).
Actuals = weekly_stats (half-PPR fpts), seasons 2019-2025, weeks 1-14.
Static preseason pools — real waiver pools thin as breakouts get added, so
the late-season split (wks 10-14) is reported as the honesty check.
"""
import json, os
import numpy as np
import backtest_sim_calibration as cal

SEASONS = range(2019, 2026)
REG_TO = 14
SCEN = {
    "QB": [10, 12, 15, 18, 24],   # 10tm light -> 14tm -> superflex-ish
    "TE": [10, 14, 16, 20, 28],
}
KS = [1, 2, 3]

def build_pos_pool(clay, pos, Y):
    pool = []
    unmatched = 0
    for name, c in clay.items():
        if c.get("pos") != pos:
            continue
        pts = c.get("pts") or 0
        if pts <= 0:
            continue
        half = max(0.5, pts - (c.get("rec") or 0) / 2.0)
        rec = cal.weekly_rec(name, pos)
        if rec is None:
            unmatched += 1
            continue
        weeks = {}
        for w in rec.get("seasons", {}).get(str(Y), []):
            if cal.played(w) and isinstance(w.get("fpts"), (int, float)) \
               and isinstance(w.get("wk"), int) and w["wk"] <= REG_TO:
                weeks[w["wk"]] = w["fpts"]
        pool.append({"name": name, "pg": half / 17.0, "weeks": weeks})
    pool.sort(key=lambda p: -p["pg"])
    return pool, unmatched

def main():
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"),
                               encoding="utf-8"))
    for pos in ("QB", "TE"):
        print(f"\n=== {pos} bye-hole fills ===")
        # samples[(R,k)] = list of (proj_pg, realized, wk)
        samples = {(R, k): [] for R in SCEN[pos] for k in KS}
        pool_sizes = []
        for Y in SEASONS:
            clay = clay_hist.get(str(Y))
            if not clay:
                continue
            pool, unmatched = build_pos_pool(clay, pos, Y)
            pool_sizes.append(len(pool))
            for R in SCEN[pos]:
                waiver = pool[R:]
                for wk in range(1, REG_TO + 1):
                    avail = [p for p in waiver if wk in p["weeks"]]
                    for k in KS:
                        if len(avail) >= k:
                            p = avail[k - 1]
                            samples[(R, k)].append((p["pg"], p["weeks"][wk], wk))
        print(f"  pool depth {min(pool_sizes)}-{max(pool_sizes)} projected {pos}s/season "
              f"(waiver = pool minus top-R)")
        print(f"  {'R':>3} {'k':>2}  {'proj pg':>7}  {'realized':>8}  {'ratio':>5}  "
              f"{'late(10-14)':>11}  {'n':>4}")
        for R in SCEN[pos]:
            for k in KS:
                s = samples[(R, k)]
                if not s:
                    continue
                pr = np.array([x[0] for x in s])
                ac = np.array([x[1] for x in s])
                wk = np.array([x[2] for x in s])
                late = ac[wk >= 10]
                se = ac.std() / np.sqrt(len(ac))
                print(f"  {R:>3} {k:>2}  {pr.mean():7.2f}  {ac.mean():5.2f}±{se:4.2f}  "
                      f"{ac.mean()/pr.mean():5.2f}  {late.mean():11.2f}  {len(s):>4}")
            print()

if __name__ == "__main__":
    main()
