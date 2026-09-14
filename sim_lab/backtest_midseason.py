#!/usr/bin/env python3
"""
Mid-season backtest: stand at week K of each past season (2019-2025) knowing
ONLY weeks 1..K-1 — season-to-date PPG, who's been missing, the preseason
Clay guide — project the REST of the season and grade it. Checkpoints 5/9/13.

Part A (means, PPG basis): rest-of-season per-game accuracy of
    clay   = preseason Clay pace (halfPts / W)
    ppg    = pure season-to-date per-game
    blend  = (P*clay + g*ppg)/(P+g)  <- the JS Weekly base; P swept.
  Grades players with >=3 remaining played games. Validates JS_PRIOR_STRENGTH
  (engine ships P=5).

Part B (distributions, totals basis): for team-matched players, project
  rest-of-season TOTALS over the player's actual remaining schedule using the
  P=5 blend, with the engine's gamma sampling + a season shock of cv TAU on
  the remaining stretch. Availability rule (knowable in real time): a player
  who hasn't played in the last 2+ weeks before K (or hasn't played at all)
  projects ZERO ("inj-aware"; the naive column keeps projecting him).
  Grades: totals MAE naive vs inj-aware, p10-p90 coverage & below-p10 among
  ACTIVE players, rest-of-season top-12 Brier. TAU swept — the preseason
  backtest tuned cv 0.45 for a full season; mid-season the role/health
  uncertainty is partly resolved, so the right TAU should be smaller and
  shrinking with K.

Uses the pool build, sigma reconstruction, team inference and sampler from
backtest_sim_calibration.py.
"""
import numpy as np
from backtest_sim_calibration import (
    norm, played, weekly_rec, sigma_entering, infer_team, sim_player,
    SCHEDULES, POS_KEEP, POOL_MIN_PTS, SEASONS, rank_within)
import backtest_sim_calibration as cal
import json, os

CHECKPOINTS = [5, 9, 13]
SHOCKS = {"none": None, "shipped": cal.SHIPPED_SHOCK}
PRIORS = [2, 5, 8, 12]
SIMS = 800
SEED = 20260731
cal.SIMS = SIMS  # sim_player sizes its draws from the cal module global

def pool_at(Y, K, clay):
    W = 16 if Y <= 2020 else 17
    out = []
    for name, c in clay.items():
        pos = c.get("pos")
        if pos not in POS_KEEP:
            continue
        pts, gm, rec_n = c.get("pts") or 0, c.get("gm") or 0, c.get("rec") or 0
        if pts < POOL_MIN_PTS or gm < 2:
            continue
        wrec = weekly_rec(name, pos)
        if wrec is None:
            continue
        rows = wrec.get("seasons", {}).get(str(Y), [])
        past = [(w["wk"], w["fpts"]) for w in rows
                if played(w) and isinstance(w.get("fpts"), (int, float)) and w["wk"] < K]
        future = [(w["wk"], w["fpts"]) for w in rows
                  if played(w) and isinstance(w.get("fpts"), (int, float)) and w["wk"] >= K]
        g = len(past)
        ppg = sum(f for _, f in past) / g if g else 0.0
        last = max((wk for wk, _ in past), default=0)
        team = infer_team(wrec, Y)
        sched = SCHEDULES.get(Y, {}).get(team, {}) if team else {}
        remaining = sum(1 for wk in sched if int(wk) >= K)
        out.append({
            "name": name, "pos": pos, "half": max(0.2, pts - rec_n / 2.0),
            "clay_pg": max(0.2, (pts - rec_n / 2.0)) / W,
            "g": g, "ppg": ppg,
            "inactive": g == 0 or last <= K - 3,   # missed the last 2+ weeks
            "sigma": sigma_entering(name, pos, Y),
            "team": team, "remaining": remaining,
            "ros_games": len(future), "ros_ppg": (sum(f for _, f in future) / len(future)) if future else None,
            "ros_total": sum(f for _, f in future),
        })
    return out, W

def blend(p, P):
    return (P * p["clay_pg"] + p["g"] * p["ppg"]) / (P + p["g"])

def main():
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    for K in CHECKPOINTS:
        maes = {"clay": [], "ppg": []}
        maes.update({f"P{P}": [] for P in PRIORS})
        tot_naive, tot_inj = [], []
        cov = {t: [] for t in SHOCKS}
        blo = {t: [] for t in SHOCKS}
        briers = {t: [] for t in SHOCKS}
        n_pool = n_inactive = 0
        for Y in SEASONS:
            if str(Y) not in clay_hist:
                continue
            pool, W = pool_at(Y, K, clay_hist[str(Y)])
            rng = np.random.default_rng(SEED + Y * 100 + K)
            n_pool += len(pool)
            n_inactive += sum(p["inactive"] for p in pool)

            # ---- Part A: rest-of-season PPG accuracy ----
            for p in pool:
                if p["ros_games"] < 3:
                    continue
                a = p["ros_ppg"]
                maes["clay"].append(abs(p["clay_pg"] - a))
                maes["ppg"].append(abs((p["ppg"] if p["g"] else p["clay_pg"]) - a))
                for P in PRIORS:
                    maes[f"P{P}"].append(abs(blend(p, P) - a))

            # ---- Part B: rest-of-season totals, distributions ----
            teamed = [p for p in pool if p["team"] and p["remaining"] > 0]
            for p in teamed:
                pg = blend(p, 5)
                p["_proj"] = pg * p["remaining"]
                tot_naive.append(abs(p["_proj"] - p["ros_total"]))
                tot_inj.append(abs((0 if p["inactive"] else p["_proj"]) - p["ros_total"]))
            for tau, cfg in SHOCKS.items():
                totals = np.zeros((len(teamed), SIMS))
                for i, p in enumerate(teamed):
                    if p["inactive"]:
                        continue
                    shock = cal.draw_shock(rng, cfg, p["half"]) if cfg else None
                    totals[i] = sim_player(rng, blend(p, 5), p["sigma"], p["remaining"], 1.0,
                                           shock=shock).sum(axis=1)
                act = np.array([p["ros_total"] for p in teamed])
                active = np.array([not p["inactive"] for p in teamed])
                lo = np.percentile(totals, 10, axis=1)
                hi = np.percentile(totals, 90, axis=1)
                cov[tau].extend(((act >= lo) & (act <= hi))[active].tolist())
                blo[tau].extend((act < lo)[active].tolist())
                for pos in POS_KEEP:
                    idx = [i for i, p in enumerate(teamed) if p["pos"] == pos]
                    if len(idx) <= 13:
                        continue
                    sub = totals[idx]
                    sim_ranks = np.argsort(-sub, axis=0).argsort(axis=0) + 1
                    prob = (sim_ranks <= 12).mean(axis=1)
                    real = (rank_within(act[idx]) <= 12).astype(float)
                    briers[tau].extend(((prob - real) ** 2).tolist())

        print(f"\n=== CHECKPOINT week {K} (pooled 2019-25: {n_pool} player-seasons, "
              f"{n_inactive} flagged inactive) ===")
        print("  A. rest-of-season PPG MAE:  " + "  ".join(
            f"{k} {np.mean(v):.3f}" for k, v in maes.items()))
        print(f"  B. totals MAE: naive {np.mean(tot_naive):.1f}  inj-aware {np.mean(tot_inj):.1f}")
        for tau in SHOCKS:
            print(f"     shock {tau:<8}: p10-p90 cov {np.mean(cov[tau])*100:5.1f}%  "
                  f"below-p10 {np.mean(blo[tau])*100:5.1f}%  Brier12 {np.mean(briers[tau]):.4f}")

if __name__ == "__main__":
    main()
