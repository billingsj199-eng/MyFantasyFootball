#!/usr/bin/env python3
"""
REST / SCHEDULE CONTEXT backtest, 2019-2025 (Jack 2026-09-15: "lets do it").
Does anything about the calendar survive the Vegas line at player level?

Flags per team-week (from pbp game dates / kickoff times):
  short      <= 5 days since the team's previous game (Thursday after Sunday)
  extra      9-12 days (post-Thursday Sunday, Monday->Sunday+)
  offbye     >= 13 days (bye week)
  opp_offbye opponent coming off a bye
  road3      third+ consecutive road game
  west_early West/Mountain team (SEA SF LAR LAC LV ARI DEN) kicking off at or
             before 13:30 ET on the road (body clock 10 a.m.)
  east_late  Eastern-zone team kicking off at/after 20:00 ET on the road out west
  prime      kickoff >= 20:00 ET (any)
Grading: actual / shipped by flag and position; LOYO multiplier on flagged
rows. Log: rest_context_backtest.log
"""
import numpy as np
from collections import defaultdict
from bt_common import iter_samples, to_arrays, load_games, bucket_table, loyo_flag, YEARS, POS4

WEST = {"SEA", "SF", "LAR", "LAC", "LV", "ARI", "DEN"}
EAST = {"NE", "NYJ", "NYG", "BUF", "MIA", "PHI", "PIT", "BAL", "WAS", "CAR", "ATL", "JAX", "TB", "CLE", "CIN", "DET", "IND"}
WESTCOAST = {"SEA", "SF", "LAR", "LAC", "LV"}

def flags_for_year(Y):
    games = load_games(Y)
    by_team = defaultdict(list)
    for (t, wk), g in games.items(): by_team[t].append((wk, g))
    out = {}
    for t, lst in by_team.items():
        lst.sort()
        prev_date = None; road_streak = 0
        for wk, g in lst:
            rest = (g["date"] - prev_date).days if prev_date is not None else None
            road_streak = 0 if g["home"] else road_streak + 1
            hour = g["hour"]
            out[(t, wk)] = {
                "rest": rest,
                "short": rest is not None and rest <= 5,
                "extra": rest is not None and 9 <= rest <= 12,
                "offbye": rest is not None and rest >= 13,
                "road3": (not g["home"]) and road_streak >= 3,
                "west_early": (t in WEST) and (not g["home"]) and hour is not None and hour <= 13.6,
                "east_late": (t in EAST) and (not g["home"]) and (g["opp"] in WESTCOAST) and hour is not None and hour >= 20,
                "prime": hour is not None and hour >= 20,
            }
            prev_date = g["date"]
    for (t, wk), f in out.items():
        o = games[(t, wk)]["opp"]; fo = out.get((o, wk))
        f["opp_offbye"] = bool(fo and fo["offbye"]); f["opp_short"] = bool(fo and fo["short"])
    return out

def main():
    S = iter_samples(POS4)
    A = to_arrays(S)
    years = sorted(set(A["year"]))
    FL = {Y: flags_for_year(Y) for Y in years}
    names = ["short", "extra", "offbye", "opp_offbye", "opp_short", "road3", "west_early", "east_late", "prime"]
    F = {n: np.zeros(len(S), bool) for n in names}
    for i, s in enumerate(S):
        f = FL[s["year"]].get((s["team"], s["wk"]))
        if not f: continue
        for n in names: F[n][i] = bool(f[n])
    print(f"\n{len(S)} player-weeks | shipped MSE {((A['shipped']-A['act'])**2).mean():.4f}")
    print("  flag counts: " + "  ".join(f"{n} {F[n].sum()}" for n in names))
    bucket_table(A, [(n, F[n]) for n in names] + [("normal rest (6-8d) home", (~F["short"]) & (~F["extra"]) & (~F["offbye"]) & A["home"])], "1. actual / shipped by schedule flag")
    print("\n=== 2. LOYO multipliers on flagged rows (grid[0] = shipped) ===")
    for n in names:
        loyo_flag(A, years, F[n], n)
    print("\n  -- per position where the pooled read moved --")
    for n in ("short", "offbye", "west_early", "prime"):
        for p in POS4:
            loyo_flag(A, years, F[n], f"{n} {p}", pos=p)

if __name__ == "__main__":
    main()
