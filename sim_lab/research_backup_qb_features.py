#!/usr/bin/env python3
"""
BACKUP-QB IMPACT RATING - feature build (2026-10-23, Jack: "backup QBs are not all the same ... a rating system for each
player based on impact"). Step 1 of research_backup_qb_rating.py: per passer-game QB stat lines 2012-25 straight from the
nflverse play-by-play cache, so a backup's own passing history (fantasy points / EPA / yards per dropback, CPOE, aDOT,
sack rate, rushing) can be compared with the regular starter's before the game is played.

Writes _tmp/qbx_cache/qbgame_<year>.pkl: one row per (game, team, passer) with
  db, epa, att, comp, cp_sum, pyds, ptd, int, sack, ay (air yards on attempts), nay (attempts with air yards),
  rush_att, rush_yds, rush_td (the same player as rusher, scrambles included), team_att, team_plays, home/away, spread, total
Read-only on everything else. Run once; later runs reuse the cache.
"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); PBP = r"E:/MyFantasyFootball/pbp_cache"
CACHE = os.path.join(HERE, "_tmp", "qbx_cache"); os.makedirs(CACHE, exist_ok=True)
COLS = ["game_id", "season", "week", "season_type", "posteam", "home_team", "away_team", "spread_line", "total_line", "passer_player_id", "passer_player_name",
        "rusher_player_id", "pass_attempt", "sack", "complete_pass", "passing_yards", "rushing_yards", "pass_touchdown", "rush_touchdown", "interception",
        "air_yards", "cp", "two_point_attempt", "epa", "qb_dropback", "play_type", "rush_attempt", "qb_scramble"]

def build(y):
    fp = os.path.join(CACHE, f"qbgame_{y}.pkl")
    if os.path.exists(fp): return pd.read_pickle(fp)
    d = pd.read_csv(os.path.join(PBP, f"play_by_play_{y}.csv.gz"), usecols=COLS, low_memory=False)
    d = d[(d.season_type == "REG") & (d.two_point_attempt != 1)].copy()
    pa = d[(d.pass_attempt == 1) | (d.sack == 1)].dropna(subset=["passer_player_id"]).copy()
    pa["att"] = (pa.pass_attempt == 1) & (pa.sack != 1)
    pa["ay_ok"] = pa.air_yards.notna() & pa.att
    pa["ay_v"] = np.where(pa.ay_ok, pa.air_yards, 0.0)
    pa["cp_v"] = np.where(pa.cp.notna() & pa.att, pa.cp, np.nan)
    q = pa.groupby(["game_id", "week", "posteam", "passer_player_id"]).agg(
        name=("passer_player_name", "first"), db=("pass_attempt", "size"), epa=("epa", "sum"), att=("att", "sum"), comp=("complete_pass", "sum"),
        cp_sum=("cp_v", "sum"), cp_n=("cp_v", "count"), pyds=("passing_yards", "sum"), ptd=("pass_touchdown", "sum"), int=("interception", "sum"),
        sack=("sack", "sum"), ay=("ay_v", "sum"), nay=("ay_ok", "sum")).reset_index().rename(columns={"passer_player_id": "pid"})
    ru = d[(d.play_type == "run") & d.rusher_player_id.notna()].groupby(["game_id", "rusher_player_id"]).agg(
        rush_att=("rush_attempt", "sum"), rush_yds=("rushing_yards", "sum"), rush_td=("rush_touchdown", "sum"), scr=("qb_scramble", "sum")).reset_index().rename(columns={"rusher_player_id": "pid"})
    q = q.merge(ru, on=["game_id", "pid"], how="left").fillna({"rush_att": 0, "rush_yds": 0, "rush_td": 0, "scr": 0})
    tm = d[d.play_type.isin(["pass", "run"])].groupby(["game_id", "posteam"]).agg(team_plays=("play_type", "size"), team_att=("pass_attempt", "sum")).reset_index()
    q = q.merge(tm, on=["game_id", "posteam"], how="left")
    g = d.drop_duplicates("game_id")[["game_id", "home_team", "away_team", "spread_line", "total_line"]]
    q = q.merge(g, on="game_id", how="left")
    q["home"] = q.posteam == q.home_team
    q["season"] = y
    pd.to_pickle(q, fp)
    return q

if __name__ == "__main__":
    y0 = int(sys.argv[1]) if len(sys.argv) > 1 else 2012; y1 = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
    for y in range(y0, y1 + 1):
        q = build(y); print(f"{y}: {len(q):,} passer-games, {q.pid.nunique()} passers", flush=True)
    print("done")
