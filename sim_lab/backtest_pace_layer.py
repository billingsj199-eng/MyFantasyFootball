#!/usr/bin/env python3
"""
Backtest the pace-tracker MULTIPLIERS (pull_pace_tracker.py -> engine
paceMult): at weeks 5/9/13 of 2019-2025, compute each team's tendency drift
exactly as the tracker would have seen it (weeks < K vs the coach-aware
baseline), apply the shipped multiplier formula to player projections, and
grade rest-of-season PPG accuracy with vs without.

Graded on two bases:
  clay  - preseason Clay pace (where the engine ACTUALLY applies paceMult)
  blend - the JS Weekly P=5 blend (where the engine deliberately does NOT,
          to avoid double-counting realized pace) — if pace helps here too,
          that call was wrong; if it hurts, the call is confirmed.

ELAS sweeps the elasticity scale (0.5x / 1x shipped / 2x) for dose-response.
Also reports the affected subset (|mult-1| >= 2%) where the layer actually
bites, and per-position deltas (the RB sign is the shakiest assumption).
"""
import numpy as np
from backtest_midseason import pool_at, blend, CHECKPOINTS
from pull_pace_tracker import team_weeks, agg, build_baseline, research_metrics
import backtest_sim_calibration as cal
import json, os

ELAS = [0.5, 1.0, 2.0]

def clamp(v, lo, hi):
    return min(hi, max(lo, v))

def pace_mult(pos, cur, base, games, e=1.0):
    """Python replica of engine paceMult with elasticity scale e."""
    if not cur or not games or not base:
        return 1.0
    m = 1.0
    if cur.get("plays") and base.get("plays"):
        m *= clamp(1 + e * 0.5 * (cur["plays"] - base["plays"]) / base["plays"],
                   1 - e * 0.06, 1 + e * 0.06)
    if cur.get("npr") is not None and base.get("npr") is not None:
        dp = cur["npr"] - base["npr"]
        if pos == "RB":
            m *= clamp(1 - e * 0.5 * dp, 1 - e * 0.05, 1 + e * 0.05)
        else:
            m *= clamp(1 + e * 0.8 * dp, 1 - e * 0.05, 1 + e * 0.05)
    if pos == "TE" and cur.get("te2") is not None and base.get("te2") is not None:
        m *= clamp(1 + e * 0.4 * (cur["te2"] - base["te2"]), 1 - e * 0.04, 1 + e * 0.04)
    return 1 + min(1.0, games / 6.0) * (m - 1)

def main():
    R = research_metrics()
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    # team drift state per (season, checkpoint): cur metrics from weeks < K
    drift = {}
    for Y in range(2019, 2026):
        weeks, coach = team_weeks(Y)
        for K in CHECKPOINTS:
            state = {}
            for t, wks in weeks.items():
                base, _ = build_baseline(t, coach.get(t), R, Y)
                cur = agg(wks, lambda w, K=K: w < K)
                state[t] = (cur, base, cur["games"] if cur else 0)
            drift[(Y, K)] = state
        print(f"  {Y} pbp processed")

    for K in CHECKPOINTS:
        rows = []
        for Y in range(2019, 2026):
            if str(Y) not in clay_hist:
                continue
            pool, W = pool_at(Y, K, clay_hist[str(Y)])
            state = drift[(Y, K)]
            for p in pool:
                if p["ros_games"] < 3 or not p["team"] or p["team"] not in state:
                    continue
                cur, base, g = state[p["team"]]
                te2only = 1.0
                if p["pos"] == "TE" and cur and base and g and \
                        cur.get("te2") is not None and base.get("te2") is not None:
                    te2only = 1 + min(1.0, g / 6.0) * \
                        (clamp(1 + 0.4 * (cur["te2"] - base["te2"]), 0.96, 1.04) - 1)
                full = pace_mult(p["pos"], cur, base, g, 1.0)
                rows.append({
                    "pos": p["pos"], "clay": p["clay_pg"], "blend": blend(p, 5),
                    "actual": p["ros_ppg"],
                    "mults": {e: pace_mult(p["pos"], cur, base, g, e) for e in ELAS},
                    "te2only": te2only,
                    "no_te2": 1 + (full - 1) - (te2only - 1),  # volume+mix share only
                })
        print(f"\n=== CHECKPOINT week {K} ({len(rows)} player-seasons) ===")
        for basis in ("clay", "blend"):
            base_mae = np.mean([abs(r[basis] - r["actual"]) for r in rows])
            line = f"  {basis:<5} MAE {base_mae:.4f} |"
            for e in ELAS:
                mae = np.mean([abs(r[basis] * r["mults"][e] - r["actual"]) for r in rows])
                line += f"  x{e}: {mae:.4f} ({(mae-base_mae)/base_mae*100:+.2f}%)"
            print(line)
        # component ablation on TEs: is the TE gain the 2-TE personnel term,
        # or the shared volume/pass-mix terms?
        tes = [r for r in rows if r["pos"] == "TE"]
        if tes:
            b0 = np.mean([abs(r["clay"] - r["actual"]) for r in tes])
            full = np.mean([abs(r["clay"] * r["mults"][1.0] - r["actual"]) for r in tes])
            t2o = np.mean([abs(r["clay"] * r["te2only"] - r["actual"]) for r in tes])
            not2 = np.mean([abs(r["clay"] * r["no_te2"] - r["actual"]) for r in tes])
            print(f"  TE ablation ({len(tes)}): base {b0:.3f}  full {full:.3f} ({(full-b0)/b0*100:+.2f}%)  "
                  f"te2-only {t2o:.3f} ({(t2o-b0)/b0*100:+.2f}%)  vol+mix-only {not2:.3f} ({(not2-b0)/b0*100:+.2f}%)")
        # affected subset + win rate + positions, at shipped elasticity
        aff = [r for r in rows if abs(r["mults"][1.0] - 1) >= 0.02]
        if aff:
            b0 = np.mean([abs(r["clay"] - r["actual"]) for r in aff])
            b1 = np.mean([abs(r["clay"] * r["mults"][1.0] - r["actual"]) for r in aff])
            wins = np.mean([abs(r["clay"] * r["mults"][1.0] - r["actual"]) <
                            abs(r["clay"] - r["actual"]) for r in aff])
            print(f"  affected (|mult-1|>=2%): {len(aff)} players  clay MAE {b0:.3f} -> {b1:.3f} "
                  f"({(b1-b0)/b0*100:+.2f}%)  win rate {wins*100:.1f}%")
        for pos in ("QB", "RB", "WR", "TE"):
            pr = [r for r in rows if r["pos"] == pos]
            if not pr:
                continue
            b0 = np.mean([abs(r["clay"] - r["actual"]) for r in pr])
            b1 = np.mean([abs(r["clay"] * r["mults"][1.0] - r["actual"]) for r in pr])
            print(f"    {pos}: clay {b0:.3f} -> {b1:.3f} ({(b1-b0)/b0*100:+.2f}%)")

if __name__ == "__main__":
    main()
