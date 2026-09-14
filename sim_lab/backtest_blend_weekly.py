#!/usr/bin/env python3
"""
WEEK-TO-WEEK blend backtest: at every week W of 2019-2025, project each
player's week-W score knowing only weeks 1..W-1, sweeping the prior strength
P in blend = (P*clayPerGame + g*ppgSoFar) / (P + g).

Answers: what is the statistically right weighting of the preseason guide vs
in-season results for NEXT-WEEK projections, and how does it move through
the season? (backtest_midseason.py answered the same for rest-of-season
totals: P=5.) Graded on played weeks only (start decisions, not injury
prediction) vs actual half-PPR points.
"""
import numpy as np
from backtest_sim_calibration import (norm, played, weekly_rec, POS_KEEP, POOL_MIN_PTS)
import backtest_sim_calibration as cal
import json, os

PRIORS = [2, 3, 5, 8, 12, 20]
BUCKETS = [(2, 5), (6, 10), (11, 18)]

def main():
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    errs = {}   # (bucket, model) -> [abs err]
    n_pw = 0
    for Y in range(2019, 2026):
        if str(Y) not in clay_hist:
            continue
        W = 16 if Y <= 2020 else 17
        for name, c in clay_hist[str(Y)].items():
            pos = c.get("pos")
            if pos not in POS_KEEP:
                continue
            pts, gm, rec_n = c.get("pts") or 0, c.get("gm") or 0, c.get("rec") or 0
            if pts < POOL_MIN_PTS or gm < 2:
                continue
            wrec = weekly_rec(name, pos)
            if wrec is None:
                continue
            rows = sorted([(w["wk"], w["fpts"]) for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, pts - rec_n / 2.0) / W
            hist = []
            for wk, fpts in rows:
                if wk >= 2 and hist:
                    g = len(hist)
                    ppg = sum(hist) / g
                    bucket = next((b for b in BUCKETS if b[0] <= wk <= b[1]), None)
                    if bucket:
                        n_pw += 1
                        preds = {"clay": clay_pg, "ppg": ppg}
                        for P in PRIORS:
                            preds[f"P{P}"] = (P * clay_pg + g * ppg) / (P + g)
                        for k, v in preds.items():
                            errs.setdefault((bucket, k), []).append(abs(v - fpts))
                hist.append(fpts)
    models = ["clay", "ppg"] + [f"P{P}" for P in PRIORS]
    print(f"=== Week-to-week blend sweep, 2019-25, {n_pw} played player-weeks ===")
    print(f"{'weeks':<8}" + "".join(f"{m:>8}" for m in models))
    overall = {m: [] for m in models}
    for b in BUCKETS:
        line = f"{b[0]}-{b[1]:<6}"
        best = min(models, key=lambda m: np.mean(errs[(b, m)]))
        for m in models:
            v = np.mean(errs[(b, m)])
            overall[m].extend(errs[(b, m)])
            line += ("%7.3f%s" % (v, "*" if m == best else " "))
        print(line)
    best = min(models, key=lambda m: np.mean(overall[m]))
    print(f"{'ALL':<8}" + "".join("%7.3f%s" % (np.mean(overall[m]), "*" if m == best else " ") for m in models))
    print("\n* = best in row. P = games of evidence the preseason guide is worth")
    print("(engine ships P=5 in jsBasePg — JS_PRIOR_STRENGTH).")

if __name__ == "__main__":
    main()
