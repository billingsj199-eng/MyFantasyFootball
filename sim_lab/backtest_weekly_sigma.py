#!/usr/bin/env python3
"""
Backtest the WEEKLY SIGMA layer (PLAYER_WEEKLY_SIGMA + engine widenings +
the gamma family), 2019-2025, decomposed into three separate questions:

A. PREDICTION: does the engine's per-player sigma (3-yr weighted weekly CV +
   low-sample/rookie widenings) predict each player's REALIZED weekly CV in
   season Y better than the position default alone? (corr + MAE + bias by
   position, on players with >=8 played games in Y.)

B. WIDTH: plug in the REALIZED season PPG as the mean (removing mean-drift,
   which the season shock owns at season level) — with the engine's total
   weekly sd (sqrt((0.9*sigma)^2 + 0.04), what the sampler actually
   produces), what global sigma SCALE makes p10-p90 coverage hit 80% and
   p25-p75 hit 50%? Tails reported separately (below-p10 vs above-p90).

C. SHAPE: plug in realized mean AND realized same-season CV (self-consistent
   parameters — cheating on purpose): if coverage still misses, the gamma
   family itself is wrong (real weeks more kurtotic), and no sigma tuning
   can fix it.

Caveat: realized weekly CV includes true matchup-to-matchup mean variation
(Vegas/defense), which the engine models in the mean, not sigma — that
inflates realized CV by ~1-2% relative var, small vs sigma^2 ~ 0.25.
"""
import numpy as np
from backtest_sim_calibration import (played, weekly_rec, sigma_entering,
                                      POS_KEEP, POOL_MIN_PTS, POS_SIGMA, SIGMA_WTS)
import backtest_sim_calibration as cal
import json, os

MIN_G = 8
SCALES = [1.0, 1.1, 1.2, 1.3]
NDRAW = 4000

def raw3yr_cv(name, pos, season):
    """The unwidened 3-yr weighted CV (None if no usable history)."""
    rec = weekly_rec(name, pos)
    if not rec:
        return None
    num = den = 0.0
    total_g = 0
    for i, yr in enumerate([season - 1, season - 2, season - 3]):
        pts = [w["fpts"] for w in rec.get("seasons", {}).get(str(yr), [])
               if played(w) and isinstance(w.get("fpts"), (int, float))]
        if len(pts) < 4:
            continue
        m = sum(pts) / len(pts)
        if m <= 1:
            continue
        sd = (sum((p - m) ** 2 for p in pts) / (len(pts) - 1)) ** 0.5
        num += SIGMA_WTS[i] * (sd / m)
        den += SIGMA_WTS[i]
        total_g += len(pts)
    if den == 0 or total_g < 8:
        return None
    return num / den

def main():
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    rng = np.random.default_rng(99)
    rows = []
    for Y in range(2019, 2026):
        if str(Y) not in clay_hist:
            continue
        for name, c in clay_hist[str(Y)].items():
            pos = c.get("pos")
            if pos not in POS_KEEP or (c.get("pts") or 0) < POOL_MIN_PTS:
                continue
            wrec = weekly_rec(name, pos)
            if wrec is None:
                continue
            pts = [w["fpts"] for w in wrec.get("seasons", {}).get(str(Y), [])
                   if played(w) and isinstance(w.get("fpts"), (int, float))]
            if len(pts) < MIN_G:
                continue
            mu = float(np.mean(pts))
            if mu < 3:
                continue
            cv = float(np.std(pts, ddof=1) / mu)
            rows.append({"pos": pos, "mu": mu, "cv": cv, "pts": pts,
                         "eng": sigma_entering(name, pos, Y),
                         "raw": raw3yr_cv(name, pos, Y)})
    print(f"{len(rows)} player-seasons with >= {MIN_G} played games\n")

    # ---- A. prediction quality ----
    print("=== A. Does per-player sigma predict realized weekly CV? ===")
    hist_rows = [r for r in rows if r["raw"] is not None]
    for tag, pred in (("engine sigma", lambda r: r["eng"]),
                      ("pos default", lambda r: POS_SIGMA[r["pos"]]),
                      ("raw 3yr CV ", lambda r: r["raw"] if r["raw"] else POS_SIGMA[r["pos"]])):
        p = np.array([pred(r) for r in hist_rows])
        a = np.array([r["cv"] for r in hist_rows])
        print(f"  {tag}: corr {np.corrcoef(p, a)[0,1]:+.3f}  MAE {np.abs(p-a).mean():.3f}  "
              f"mean pred {p.mean():.3f} vs realized {a.mean():.3f}  (n={len(hist_rows)}, history players)")
    print("  bias by position (realized CV / engine TOTAL sd incl env):")
    for pos in ("QB", "RB", "WR", "TE"):
        pr = [r for r in rows if r["pos"] == pos]
        tot = np.array([np.sqrt((0.9 * r["eng"]) ** 2 + 0.04) for r in pr])
        a = np.array([r["cv"] for r in pr])
        print(f"    {pos}: realized {a.mean():.3f} / engine-total {tot.mean():.3f} = ratio {a.mean()/tot.mean():.2f}  (n={len(pr)})")

    # ---- B. width calibration with realized mean ----
    print("\n=== B. Width (mean = REALIZED ppg; engine total sd x scale) ===")
    for s in SCALES:
        inside80 = inside50 = below = above = n = 0
        for r in rows:
            sd = r["mu"] * np.sqrt((0.9 * r["eng"]) ** 2 + 0.04) * s
            k = (r["mu"] / sd) ** 2
            th = sd * sd / r["mu"]
            d = np.sort(rng.gamma(k, th, NDRAW))
            lo10, hi90 = d[int(NDRAW*.1)], d[int(NDRAW*.9)]
            lo25, hi75 = d[int(NDRAW*.25)], d[int(NDRAW*.75)]
            for a in r["pts"]:
                n += 1
                if lo10 <= a <= hi90: inside80 += 1
                elif a < lo10: below += 1
                else: above += 1
                if lo25 <= a <= hi75: inside50 += 1
        print(f"  scale {s:.2f}: p10-p90 {inside80/n*100:5.1f}% (target 80)  "
              f"below-p10 {below/n*100:4.1f}%  above-p90 {above/n*100:4.1f}%  "
              f"p25-p75 {inside50/n*100:5.1f}% (target 50)")

    # ---- B2. per-position scale sweep (the shippable numbers) ----
    print("\n=== B2. Per-position sigma scale (mean = realized ppg) ===")
    for pos in ("QB", "RB", "WR", "TE"):
        pr = [r for r in rows if r["pos"] == pos]
        line = f"  {pos}:"
        for s in (0.9, 1.0, 1.1, 1.15, 1.2, 1.3):
            inside = n = 0
            for r in pr:
                sd = r["mu"] * np.sqrt((0.9 * r["eng"]) ** 2 + 0.04) * s
                k = (r["mu"] / sd) ** 2
                d = np.sort(rng.gamma(k, sd * sd / r["mu"], NDRAW))
                lo, hi = d[int(NDRAW*.1)], d[int(NDRAW*.9)]
                for a in r["pts"]:
                    n += 1
                    if lo <= a <= hi: inside += 1
            line += f"  x{s}: {inside/n*100:.1f}%"
        print(line + "   (target 80)")

    # ---- C. gamma shape with self-consistent parameters ----
    print("\n=== C. Shape (mean AND cv = realized — isolates the gamma family) ===")
    inside80 = inside50 = below = above = n = 0
    for r in rows:
        sd = r["mu"] * r["cv"]
        k = (r["mu"] / sd) ** 2
        th = sd * sd / r["mu"]
        d = np.sort(rng.gamma(k, th, NDRAW))
        lo10, hi90 = d[int(NDRAW*.1)], d[int(NDRAW*.9)]
        lo25, hi75 = d[int(NDRAW*.25)], d[int(NDRAW*.75)]
        for a in r["pts"]:
            n += 1
            if lo10 <= a <= hi90: inside80 += 1
            elif a < lo10: below += 1
            else: above += 1
            if lo25 <= a <= hi75: inside50 += 1
    print(f"  p10-p90 {inside80/n*100:5.1f}% (target 80)  below-p10 {below/n*100:4.1f}%  "
          f"above-p90 {above/n*100:4.1f}%  p25-p75 {inside50/n*100:5.1f}% (target 50)")

if __name__ == "__main__":
    main()
