#!/usr/bin/env python3
"""
REST-OF-SEASON tilts from the PFF Pro screen (2026-10-05), same harness and grading as backtest_ros_quality_volume.py
(rest-of-season PPG vs the frozen per-game live number, LOYO, plain + level-weighted MSE):
  WR / TE  pred = live x (1 + e x z(PFF positively graded play rate, season to date shrunk to last season))
           TE also graded ON TOP OF the shipped team pass-rate tilt (e .08, SIM_ROS_TILT)
  RB       pred = live x (1 - e x z(own offense blitzed rate))   and   x (1 - e x z(own offense success rate))
Features from data/pff_pro_features.parquet (research_pff_pro_screen.py). Log ros_pff_pro.log.
"""
import os
import numpy as np, pandas as pd
from backtest_ros_quality_volume import loyo, zscore

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    lf = open(os.path.join(HERE, "ros_pff_pro.log"), "w", encoding="utf-8")

    def log(s=""):
        print(s, flush=True); lf.write(s + "\n")

    M = pd.read_parquet(os.path.join(HERE, "data", "metric_atlas_rows.parquet"))
    M = M[(M.live >= 5) & (M.g >= 2) & M.ros.notna()].copy()
    F = pd.read_parquet(os.path.join(HERE, "data", "pff_pro_features.parquet"))
    M = M.merge(F, on=["year", "pid", "wk"], how="left")
    years = sorted(M.year.unique())
    ES = [0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12]
    log(f"=== rest-of-season PFF Pro tilts: {len(M)} checkpoints ===")
    for pos in ("WR", "TE"):
        d = M[(M.pos == pos) & M.rec_pos_graded.notna()].copy()
        d["zq"] = zscore(d, "rec_pos_graded", ["year", "wk"]).clip(-2.5, 2.5)
        d["zpr"] = zscore(d, "team_neutral_pass_rate_std", ["year", "wk"]).clip(-2, 2).fillna(0)
        log(f"\n--- {pos}: positively graded play rate (n={len(d)}) ---")
        forms = {"graded-play-rate tilt": (ES, lambda d, e: d.live * (1 + e * d.zq))}
        if pos == "TE":
            d["shipped"] = d.live * (1 - 0.08 * d.zpr)
            forms["shipped pass-rate tilt alone (e .08)"] = ([0.0], lambda d, e: d.shipped)
            forms["graded tilt ON TOP of shipped tilt"] = (ES, lambda d, e: d.shipped * (1 + e * d.zq))
        loyo(d, forms, years, log, pos)
        if pos == "TE":
            log("  (vs the shipped tilt as the base:)")
            loyo(d, {"graded tilt ON TOP of shipped tilt": (ES, lambda d, e: d.shipped * (1 + e * d.zq))}, years, log, pos, base="shipped")
        for lo, hi, lab in ((-9, -0.5, "low"), (-0.5, 0.5, "mid"), (0.5, 9, "high")):
            x = d[(d.zq >= lo) & (d.zq < hi)]
            log(f"      graded-play rate {lab:4s} n={len(x):4d}  ROS/live {x.ros.sum() / x.live.sum():.3f}")
    d = M[(M.pos == "RB") & M.own_blitzRateAgainst.notna()].copy()
    d["zb"] = zscore(d, "own_blitzRateAgainst", ["year", "wk"]).clip(-2, 2)
    d["zs"] = zscore(d, "own_successRate", ["year", "wk"]).clip(-2, 2)
    log(f"\n--- RB: own offense (n={len(d)}) ---")
    loyo(d, {"blitzed-rate tilt": (ES, lambda d, e: d.live * (1 - e * d.zb)),
             "offense success-rate tilt": (ES, lambda d, e: d.live * (1 - e * d.zs))}, years, log, "RB")
    for col, lab in (("zb", "blitzed"), ("zs", "success")):
        for lo, hi, b in ((-9, -0.5, "low"), (-0.5, 0.5, "mid"), (0.5, 9, "high")):
            x = d[(d[col] >= lo) & (d[col] < hi)]
            log(f"      {lab} {b:4s} n={len(x):4d}  ROS/live {x.ros.sum() / x.live.sum():.3f}")
    lf.close()


if __name__ == "__main__":
    main()
