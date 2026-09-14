#!/usr/bin/env python3
"""
OL-OUT layer test, 2019-2025 (Jack: "offensive line ranks maybe").

Season-level OL GRADES are already priced (backtest_pff_layers.py: run-block
flat for RB, pass-block flat/hurts) — but OL AVAILABILITY is a weekly
transient, the offensive mirror of the CB1-out boost. Design:

Starting five per (Y, team) = the 5 linemen (C/G/T) with the most games at
offense_pct >= 0.6 (min 6). Each team-week counts how many of the five sat
(offense_pct < 0.5 / absent). Own-offense QB/RB/WR/TE player-weeks graded
vs the P=5 blend base, bucketed by missing-starter count; MSE dock sweep.
"""
import numpy as np
import pandas as pd
import json, os
from collections import defaultdict
from backtest_sim_calibration import (played, weekly_rec, infer_team,
                                      POOL_MIN_PTS, OPP_ALIAS)
import backtest_sim_calibration as cal

CACHE = r"E:\MyFantasyFootball\pbp_cache"
P = 5
YEARS = range(2019, 2026)
TEAM_FIX = {"WSH": "WAS", "LA": "LAR", "OAK": "LV", "SD": "LAC",
            "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}

def load_ol_missing():
    """(Y, team, wk) -> number of season-starting-five OL not playing."""
    missing = {}
    for Y in YEARS:
        df = pd.read_parquet(
            os.path.join(CACHE, f"snap_counts_{Y}.parquet"),
            columns=["week", "game_type", "player", "position", "team", "offense_pct"])
        df = df[df.game_type == "REG"]
        tw = defaultdict(set)
        for t, wk in df[["team", "week"]].drop_duplicates().itertuples(index=False):
            tw[TEAM_FIX.get(t, t)].add(int(wk))
        ol = df[df.position.isin(["C", "G", "T"]) & (df.offense_pct >= 0.6)]
        for t, grp in ol.groupby("team"):
            tm = TEAM_FIX.get(t, t)
            counts = [(len(rows), float(rows.offense_pct.mean()), nm, set(int(w) for w in rows.week))
                      for nm, rows in grp.groupby("player") if len(rows) >= 6]
            five = sorted(counts, reverse=True)[:5]
            if len(five) < 5:
                continue
            for wk in tw[tm]:
                missing[(Y, tm, wk)] = sum(1 for _, _, _, wks in five if wk not in wks)
    return missing

def build_samples(pos):
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"),
                               encoding="utf-8"))
    S = []
    for Y in YEARS:
        if str(Y) not in clay_hist:
            continue
        W = 16 if Y <= 2020 else 17
        for name, c in clay_hist[str(Y)].items():
            if c.get("pos") != pos or (c.get("pts") or 0) < POOL_MIN_PTS:
                continue
            wrec = weekly_rec(name, pos)
            if wrec is None:
                continue
            team = infer_team(wrec, Y)
            if team is None:
                continue
            rows = sorted([(w["wk"], w["fpts"]) for w in
                           wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            hist = []
            for wk, fpts in rows:
                if hist:
                    g = len(hist)
                    base = (P * clay_pg + g * (sum(hist) / g)) / (P + g)
                    S.append({"Y": Y, "wk": int(wk), "tm": team,
                              "base": base, "act": fpts})
                hist.append(fpts)
    return S

def sweep(sub, label, mults):
    if len(sub) < 40:
        print(f"    {label:16s} n={len(sub)} (too small)")
        return
    a = np.array([s["act"] for s in sub]); b = np.array([s["base"] for s in sub])
    line = f"    {label:16s} n={len(sub):5d} ratio {a.sum()/b.sum():.3f} |"
    best = None
    for d in mults:
        m = float(np.mean((b * d - a) ** 2))
        line += f" x{d:.2f} {m:.2f}"
        if best is None or m < best[1]:
            best = (d, m)
    print(line + f"  <- best x{best[0]:.2f}")

def main():
    missing = load_ol_missing()
    for pos in ("QB", "RB", "WR", "TE"):
        S = build_samples(pos)
        for s in S:
            s["m"] = missing.get((s["Y"], s["tm"], s["wk"]))
        S = [s for s in S if s["m"] is not None]
        print(f"\n=== {pos} ({len(S)} own-team player-weeks) ===")
        sweep([s for s in S if s["m"] == 0], "0 OL missing", (0.96, 0.98, 1.00, 1.02, 1.04))
        sweep([s for s in S if s["m"] == 1], "1 OL missing", (0.92, 0.94, 0.96, 0.98, 1.00, 1.02, 1.04))
        sweep([s for s in S if s["m"] >= 2], "2+ OL missing", (0.88, 0.90, 0.92, 0.94, 0.96, 0.98, 1.00, 1.04))

if __name__ == "__main__":
    main()
