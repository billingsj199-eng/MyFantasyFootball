#!/usr/bin/env python3
"""
FIRST GAME BACK backtest, 2019-2025 (Jack 2026-09-15: "lets do it").
The injury layer zeros a player who is out and says nothing about the game he
returns. Do returning players play / score less in game 1 (and 2) back?

From nflverse snap counts (offense_pct per player-week) + pbp team weeks:
  missed = team played, player has no snap row (or 0%)
  return1 = first game with snaps after >= 2 consecutive missed team games
            (player had played earlier in the season, so not a season debut)
  return2 = the game after return1
  ret_long = return after >= 4 missed games
Grading: snap share in the return game vs his own in-season median; actual /
shipped (base x Vegas x FPA) on return rows; LOYO multiplier on return rows.
Log: return_game_backtest.log
"""
import numpy as np
import pandas as pd
import os
from collections import defaultdict
from bt_common import iter_samples, to_arrays, load_games, bucket_table, loyo_flag, YEARS, POS4, CACHE, tm
import backtest_sim_calibration as cal

def snaps_year(Y):
    df = pd.read_parquet(os.path.join(CACHE, f"snap_counts_{Y}.parquet"), columns=["player", "week", "game_type", "team", "offense_pct"])
    df = df[df.game_type == "REG"].dropna(subset=["offense_pct"])
    out = defaultdict(dict)
    for r in df.itertuples(index=False):
        out[cal.norm(str(r.player))][int(r.week)] = (float(r.offense_pct) * 100, tm(r.team))
    return out

def main():
    S = iter_samples(POS4)
    A = to_arrays(S)
    years = sorted(set(A["year"]))
    ret1 = np.zeros(len(S), bool); ret2 = np.zeros(len(S), bool); retlong = np.zeros(len(S), bool)
    snap_ret, snap_med = [], []
    for Y in years:
        sn = snaps_year(Y); games = load_games(Y)
        team_weeks = defaultdict(set)
        for (t, wk) in games: team_weeks[t].add(wk)
        for i, s in enumerate(S):
            if s["year"] != Y: continue
            p = sn.get(cal.norm(s["name"]))
            if not p: continue
            tw = sorted(team_weeks.get(s["team"], []))
            played = {w: v[0] for w, v in p.items() if v[0] > 0}
            if not played: continue
            # missed streak immediately before this week (team games only)
            prior = [w for w in tw if w < s["wk"]]
            streak = 0
            for w in reversed(prior):
                if w in played: break
                streak += 1
            had_played_before = any(w in played for w in prior)
            if streak >= 2 and had_played_before and s["wk"] in played:
                ret1[i] = True
                if streak >= 4: retlong[i] = True
                med = np.median([played[w] for w in prior if w in played])
                snap_ret.append(played[s["wk"]]); snap_med.append(med)
            # second game back: previous team game was a return1
            if len(prior) >= 1:
                pw = prior[-1]
                pp = [w for w in tw if w < pw]; st2 = 0
                for w in reversed(pp):
                    if w in played: break
                    st2 += 1
                if st2 >= 2 and pw in played and any(w in played for w in pp) and s["wk"] in played:
                    ret2[i] = True
    print(f"\n{len(S)} player-weeks | return1 rows {ret1.sum()} (>=4 missed: {retlong.sum()}) | return2 rows {ret2.sum()}")
    sr, sm = np.array(snap_ret), np.array(snap_med)
    print(f"  return-game snap share: mean {sr.mean():.1f}% vs own prior median {sm.mean():.1f}% (ratio {sr.mean()/sm.mean():.3f}); share of returns below 80% of median: {(sr < 0.8*sm).mean():.0%}")
    bucket_table(A, [("return game 1", ret1), ("return after >=4 missed", retlong), ("return game 2", ret2), ("all other rows", ~ret1 & ~ret2)], "1. actual / shipped")
    print("\n=== 2. LOYO multipliers on return rows (grid[0] = shipped) ===")
    grid = (1.0, 0.95, 0.9, 0.85, 0.8, 0.75)
    loyo_flag(A, years, ret1, "return game 1", grid)
    loyo_flag(A, years, retlong, "return after >=4 missed", grid)
    loyo_flag(A, years, ret2, "return game 2", grid)
    for p in POS4:
        loyo_flag(A, years, ret1, f"return game 1 {p}", grid, pos=p)

if __name__ == "__main__":
    main()
