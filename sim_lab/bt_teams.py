#!/usr/bin/env python3
"""
TEAM PER GAME for the backtest harness (2026-10-20; used only when bt_ext.TEAMFIX is on - extended mode or SIM_BT_TEAMFIX=1).

The shared harness gives a player ONE team per season (backtest_sim_calibration.infer_team: 70%+ match of the weekly
record's opponents against a schedule) and takes the opponent from the weekly record. That drops most mid-season movers
(21 of 31 pool movers 2019-24) or gives them one team's Vegas lines all season, skips retired-file records (no opponent:
339 pool player-seasons, e.g. Sanders 2019) and misreads 2025 records (they carry the CURRENT team's schedule, Meyers 2025
= JAX all season). Here the team comes from what happened in each game:

  1  play-by-play touches   passer / rusher / receiver id -> posteam that week (REG)
  2  snap counts            pfr id -> gsis, team that week with offensive snaps (2013+)
  3  weekly roster          the team he was on that week (nflverse roster_weekly, any status)
and the opponent / implied totals come from that team's game that week (bt_common.load_games). A player whose gsis id
cannot be resolved keeps the old behaviour (infer_team + the record's opponent).
"""
import os
from collections import defaultdict, Counter
import numpy as np
import pandas as pd

CACHE = r"E:\MyFantasyFootball\pbp_cache"
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
def tm(t): return ALIAS.get(t, t)

_GT = {}
STATS = defaultdict(int)


def game_teams(Y):
    """{(gsis, wk): team} for season Y (REG weeks)."""
    if Y in _GT:
        return _GT[Y]
    out = {}
    p = os.path.join(CACHE, f"play_by_play_{Y}.csv.gz")
    if os.path.exists(p):
        cols = ["season_type", "week", "posteam", "passer_player_id", "rusher_player_id", "receiver_player_id"]
        d = pd.read_csv(p, usecols=cols, low_memory=False)
        d = d[(d.season_type == "REG") & d.posteam.notna()]
        cnt = defaultdict(Counter)
        for c in cols[3:]:
            x = d[d[c].notna()]
            for pid, wk, t in zip(x[c].values, x.week.values, x.posteam.values):
                cnt[(pid, int(wk))][tm(str(t))] += 1
        for k, c in cnt.items():
            out[k] = c.most_common(1)[0][0]
    p = os.path.join(CACHE, f"snap_counts_{Y}.parquet")
    if os.path.exists(p):
        s = pd.read_parquet(p, columns=["game_type", "week", "pfr_player_id", "team", "offense_snaps"])
        if len(s):
            pl = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "pfr_id"])
            g2 = {r.pfr_id: r.gsis_id for r in pl.itertuples(index=False) if isinstance(r.pfr_id, str) and isinstance(r.gsis_id, str)}
            s = s[(s.game_type == "REG") & (s.offense_snaps > 0)]
            for pf, wk, t in zip(s.pfr_player_id.values, s.week.values, s.team.values):
                gid = g2.get(pf)
                if gid: out.setdefault((gid, int(wk)), tm(str(t)))
    p = os.path.join(CACHE, f"roster_weekly_{Y}.parquet")
    if os.path.exists(p):
        r = pd.read_parquet(p, columns=["game_type", "week", "gsis_id", "team"])
        r = r[(r.game_type == "REG") & r.gsis_id.notna()]
        for gid, wk, t in zip(r.gsis_id.values, r.week.values, r.team.values):
            out.setdefault((gid, int(wk)), tm(str(t)))
    _GT[Y] = out
    return out


def team_at(pid, Y, wk):
    if not pid:
        return None
    return game_teams(Y).get((pid, int(wk)))


def first_last_team(pid, Y, weeks, last=False):
    """team of his first (or last) played week in Y that has a per-game team"""
    if not pid:
        return None
    gt = game_teams(Y)
    for w in (sorted(weeks, reverse=True) if last else sorted(weeks)):
        t = gt.get((pid, int(w)))
        if t:
            return t
    return None


def build_fpa_tf(resolve, games_of):
    """backtest_snap_defense.build_fpa with the defense taken from each game's schedule (per-game team) instead of the
    weekly record's opp field; same aggregation (season mean needs 10+ weeks), same output shapes."""
    import backtest_sim_calibration as cal
    import bt_ext as BX
    y0 = min(2018, BX.YEARS[0] - 1)
    weekly_fpa = defaultdict(lambda: defaultdict(float))
    for nk, recs in cal.WEEKLY.items():
        for rec in recs:
            pos = rec.get("pos")
            if pos not in cal.POS_KEEP:
                continue
            for y, rows in rec.get("seasons", {}).items():
                Y = int(y)
                if Y < y0 or Y > 2025:
                    continue
                pid = resolve(nk, pos, Y)
                games = games_of(Y) if os.path.exists(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz")) else {}   # no 2011 pbp: record opp
                for w in rows:
                    if not cal.played(w):
                        continue
                    d = None
                    t = team_at(pid, Y, w["wk"]) if pid else None
                    if t and games.get((t, int(w["wk"]))):
                        d = games[(t, int(w["wk"]))]["opp"]; STATS["fpa_sched"] += 1
                    elif w.get("opp"):
                        d = cal.OPP_ALIAS.get(w["opp"], w["opp"]); STATS["fpa_rec"] += 1
                    if d:
                        weekly_fpa[(Y, d, pos)][int(w["wk"])] += w["fpts"] or 0
    season_fpa = {}
    for (Y, d, pos), wks in weekly_fpa.items():
        if len(wks) >= 10:
            season_fpa[(Y, d, pos)] = sum(wks.values()) / len(wks)
    lg = {}
    for (Y, d, pos), v in season_fpa.items():
        lg.setdefault((Y, pos), []).append(v)
    lg = {k: float(np.mean(v)) for k, v in lg.items()}
    return weekly_fpa, season_fpa, lg
