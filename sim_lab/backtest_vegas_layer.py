#!/usr/bin/env python3
"""
Backtest the VEGAS layer with historical closing lines (2019-2025).

Lines come from nflfastR pbp itself (spread_line/total_line = closing Vegas
numbers per game — already in pbp_cache, no new pull). Implied team totals
reconstructed exactly like the engine's buildSchedule, sign convention
auto-checked against actual points scored.

1. PLAYER MEAN ELASTICITY: at every week, base = the validated P=5 blend
   per-game (clay prior + season-to-date). Prediction = base x
   clamp(1 + e*(implied - lgAvg)/lgAvg, 0.7, 1.35). Sweep e in
   {0, .25, .5, .75, 1.0} (engine ships VEGAS_ELASTICITY = 0.5), grade MAE +
   MSE vs actual weekly points, overall and per position.
2. EMPIRICAL ELASTICITY: bucket player-weeks by implied deviation; realized
   mean(actual)/mean(base) per bucket -> the slope IS the true elasticity.
3. DST MEAN MODEL: engine synthesizes DST mean = 15.5 - 0.42*oppImplied.
   Regress realized DST weekly points (reconstructed by
   backtest_k_dst_sigma.season_scores) on opponent implied -> compare.
"""
import numpy as np
import pandas as pd
import json, os
from backtest_sim_calibration import (played, weekly_rec, infer_team,
                                      POS_KEEP, POOL_MIN_PTS)
import backtest_sim_calibration as cal
from backtest_k_dst_sigma import season_scores

CACHE = r"E:\MyFantasyFootball\pbp_cache"
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS"}
def tm(t): return ALIAS.get(t, t)
ES = [0.0, 0.25, 0.5, 0.75, 1.0]
P = 5

def load_lines(year):
    """(team, week) -> implied total; sign convention validated on scores."""
    cols = ["season_type", "week", "game_id", "home_team", "away_team",
            "spread_line", "total_line", "home_score", "away_score"]
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{year}.csv.gz"),
                     usecols=cols, low_memory=False)
    df = df[df.season_type == "REG"].dropna(subset=["spread_line", "total_line"])
    g = df.groupby("game_id").first()
    for sign in (1, -1):
        hi = (g.total_line + sign * g.spread_line) / 2
        ai = (g.total_line - sign * g.spread_line) / 2
        c = np.corrcoef(np.concatenate([hi, ai]),
                        np.concatenate([g.home_score, g.away_score]))[0, 1]
        if sign == 1:
            best = (c, 1)
        elif c > best[0]:
            best = (c, -1)
    sign = best[1]
    out = {}
    for gid, r in g.iterrows():
        hi = (r.total_line + sign * r.spread_line) / 2
        ai = (r.total_line - sign * r.spread_line) / 2
        out[(tm(r.home_team), int(r.week))] = hi
        out[(tm(r.away_team), int(r.week))] = ai
    return out, best[0]

def main():
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    samples = []   # (pos, base, implied_dev, actual)
    for Y in range(2019, 2026):
        if str(Y) not in clay_hist:
            continue
        lines, corr = load_lines(Y)
        avg = float(np.mean(list(lines.values())))
        W = 16 if Y <= 2020 else 17
        for name, c in clay_hist[str(Y)].items():
            pos = c.get("pos")
            if pos not in POS_KEEP or (c.get("pts") or 0) < POOL_MIN_PTS:
                continue
            wrec = weekly_rec(name, pos)
            if wrec is None:
                continue
            team = infer_team(wrec, Y)
            if not team:
                continue
            rows = sorted([(w["wk"], w["fpts"]) for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            hist = []
            for wk, fpts in rows:
                imp = lines.get((team, wk))
                if imp is not None and hist:
                    g = len(hist)
                    base = (P * clay_pg + g * (sum(hist) / g)) / (P + g)
                    samples.append((pos, base, (imp - avg) / avg, fpts))
                hist.append(fpts)
        print(f"  {Y}: implied-vs-score corr {corr:+.3f}, lgAvg implied {avg:.1f}")

    pos_a = np.array([s[0] for s in samples])
    base = np.array([s[1] for s in samples], float)
    dev = np.array([s[2] for s in samples], float)
    act = np.array([s[3] for s in samples], float)
    print(f"\n{len(samples)} player-weeks with lines + base\n")

    print("=== 1. MAE / MSE by elasticity (engine ships 0.5) ===")
    for e in ES:
        pred = base * np.clip(1 + e * dev, 0.7, 1.35)
        print(f"  e={e:.2f}: MAE {np.abs(pred-act).mean():.4f}   MSE {((pred-act)**2).mean():.3f}")
    for pos in ("QB", "RB", "WR", "TE"):
        m = pos_a == pos
        line = f"    {pos}:"
        best = None
        for e in ES:
            pred = base[m] * np.clip(1 + e * dev[m], 0.7, 1.35)
            mse = ((pred - act[m]) ** 2).mean()
            line += f"  e{e:.2f} {mse:.3f}"
            if best is None or mse < best[0]:
                best = (mse, e)
        print(line + f"   <- best e={best[1]}")

    print("\n=== 2. Empirical elasticity (bucketed by implied deviation) ===")
    edges = [-1, -.15, -.08, -.03, .03, .08, .15, 1]
    xs, ys = [], []
    for i in range(len(edges) - 1):
        m = (dev >= edges[i]) & (dev < edges[i + 1])
        if m.sum() < 500:
            continue
        ratio = act[m].mean() / base[m].mean()
        xs.append(dev[m].mean()); ys.append(ratio)
        print(f"  implied dev {dev[m].mean():+.3f}: actual/base {ratio:.3f}  (n={m.sum()})")
    slope = np.polyfit(xs, ys, 1)[0]
    print(f"  fitted slope (TRUE elasticity) = {slope:.2f}   (engine: 0.5)")

    print("\n=== 3. DST mean model: engine 15.5 - 0.42*oppImplied ===")
    X, Yv = [], []
    for Y2 in range(2019, 2026):
        lines, _ = load_lines(Y2)
        _, dsts = season_scores(Y2)
        # opponent implied = the OTHER team's implied that week
        sched = {}
        for (t, wk), imp in lines.items():
            sched.setdefault(wk, {})[t] = imp
        for team, wks in dsts.items():
            for wk, pts in wks.items():
                # find opponent: the game partner — approximate via cal SCHEDULES
                opp = cal.SCHEDULES.get(Y2, {}).get(team, {}).get(str(wk))
                if opp and (opp, wk) in lines:
                    X.append(lines[(opp, wk)]); Yv.append(pts)
    X, Yv = np.array(X), np.array(Yv)
    b, a = np.polyfit(X, Yv, 1)
    print(f"  realized: DST pts = {a:.1f} + {b:.3f} * oppImplied   (n={len(X)}, corr {np.corrcoef(X,Yv)[0,1]:+.3f})")
    print(f"  engine:   DST pts = 15.5 - 0.420 * oppImplied")

if __name__ == "__main__":
    main()
