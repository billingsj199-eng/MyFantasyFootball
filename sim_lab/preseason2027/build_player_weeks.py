#!/usr/bin/env python3
"""
2027 PRESEASON PROTOTYPE - step 1: player-week and team-game tables from nflverse pbp (2012-2025, REG only).

Read-only on the shared caches (E:\\MyFantasyFootball\\pbp_cache). Writes only inside sim_lab\\preseason2027\\data\\.

player_weeks.parquet  one row per (season, week, gsis_id) for QB/RB/WR/TE with raw stat components and
                      half-PPR (house scoring: pass yd .04, pass TD 4, INT -1, rush/rec yd .1, TD 6, rec .5, FL -2, 2pt 2),
                      full PPR, and DraftKings scoring (PPR, FL -1, 300 pass / 100 rush / 100 rec yd bonuses +3).
                      Usage: targets, carries, team targets/carries/dropbacks that game (for shares).
team_games.parquet    one row per (season, week, team): plays, dropbacks, pass att, rush att, points scored/allowed,
                      closing spread/total (from schedules_games.csv), result.
"""
import os, sys, time
import numpy as np
import pandas as pd

CACHE = r"E:\MyFantasyFootball\pbp_cache"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
YEARS = range(2012, 2026)
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX"}
COLS = ["game_id", "season_type", "week", "posteam", "defteam", "play_type", "qb_kneel", "qb_spike", "pass_attempt", "rush_attempt", "sack",
        "qb_dropback", "complete_pass", "passer_player_id", "passing_yards", "receiver_player_id", "receiving_yards", "rusher_player_id",
        "rushing_yards", "pass_touchdown", "rush_touchdown", "interception", "fumble_lost", "fumbled_1_player_id", "two_point_attempt",
        "two_point_conv_result", "td_player_id"]


def tm(t):
    return ALIAS.get(t, t) if isinstance(t, str) else t


def season(Y):
    d = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), usecols=lambda c: c in COLS, low_memory=False)
    d = d[d.season_type == "REG"].copy()
    d["posteam"] = d.posteam.map(tm); d["defteam"] = d.defteam.map(tm)
    real = (d.two_point_attempt != 1)
    rows = []
    # passing
    p = d[real & d.passer_player_id.notna() & (d.pass_attempt == 1)]
    p = p.assign(att1=(p.sack != 1).astype(int))
    g = p.groupby(["game_id", "week", "posteam", "passer_player_id"]).agg(
        att=("att1", "sum"),
        cmp=("complete_pass", "sum"), pyd=("passing_yards", "sum"), ptd=("pass_touchdown", "sum"), int_=("interception", "sum"))
    g = g.reset_index().rename(columns={"passer_player_id": "pid", "posteam": "team"}); rows.append(g)
    # rushing (kneels excluded from carries, yards kept)
    r = d[real & d.rusher_player_id.notna() & (d.rush_attempt == 1)]
    g = r.assign(car=(r.qb_kneel != 1).astype(int)).groupby(["game_id", "week", "posteam", "rusher_player_id"]).agg(
        car=("car", "sum"), ryd=("rushing_yards", "sum"), rtd=("rush_touchdown", "sum"))
    g = g.reset_index().rename(columns={"rusher_player_id": "pid", "posteam": "team"}); rows.append(g)
    # receiving
    c = d[real & d.receiver_player_id.notna() & (d.pass_attempt == 1) & (d.sack != 1)]
    g = c.groupby(["game_id", "week", "posteam", "receiver_player_id"]).agg(
        tgt=("pass_attempt", "size"), rec=("complete_pass", "sum"), cyd=("receiving_yards", "sum"), ctd=("pass_touchdown", "sum"))
    g = g.reset_index().rename(columns={"receiver_player_id": "pid", "posteam": "team"}); rows.append(g)
    # fumbles lost
    f = d[d.fumble_lost == 1].groupby(["game_id", "week", "posteam", "fumbled_1_player_id"]).size().reset_index(name="fl")
    f = f.rename(columns={"fumbled_1_player_id": "pid", "posteam": "team"}); rows.append(f)
    # two-point conversions (passer, rusher, receiver each get 2)
    t = d[(d.two_point_attempt == 1) & (d.two_point_conv_result == "success")]
    tp = []
    for col in ("passer_player_id", "rusher_player_id", "receiver_player_id"):
        x = t[t[col].notna()].groupby(["game_id", "week", "posteam", col]).size().reset_index(name="tp")
        tp.append(x.rename(columns={col: "pid", "posteam": "team"}))
    rows.append(pd.concat(tp))
    W = pd.concat(rows).groupby(["game_id", "week", "team", "pid"]).sum(numeric_only=True).reset_index()
    for k in ("att", "cmp", "pyd", "ptd", "int_", "car", "ryd", "rtd", "tgt", "rec", "cyd", "ctd", "fl", "tp"):
        if k not in W: W[k] = 0
        W[k] = W[k].fillna(0)
    W["half"] = .04 * W.pyd + 4 * W.ptd - W.int_ + .1 * (W.ryd + W.cyd) + 6 * (W.rtd + W.ctd) + .5 * W.rec - 2 * W.fl + 2 * W.tp
    W["ppr"] = W.half + .5 * W.rec
    W["dk"] = (.04 * W.pyd + 4 * W.ptd - W.int_ + .1 * (W.ryd + W.cyd) + 6 * (W.rtd + W.ctd) + W.rec - W.fl + 2 * W.tp
               + 3 * (W.pyd >= 300) + 3 * (W.ryd >= 100) + 3 * (W.cyd >= 100))
    W["season"] = Y
    # team-game usage totals
    tg = d[real].groupby(["game_id", "week", "posteam"]).agg(
        plays=("play_type", lambda s: int(s.isin(["pass", "run"]).sum())),
        dropbacks=("qb_dropback", "sum"), passatt=("pass_attempt", "sum"), rushatt=("rush_attempt", "sum"), sacks=("sack", "sum"),
        kneels=("qb_kneel", "sum")).reset_index().rename(columns={"posteam": "team"})
    tt = W.groupby(["game_id", "team"]).agg(team_tgt=("tgt", "sum"), team_car=("car", "sum")).reset_index()
    W = W.merge(tt, on=["game_id", "team"], how="left")
    tg["season"] = Y
    return W, tg


def main():
    t0 = time.time()
    pl = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False,
                     usecols=["gsis_id", "display_name", "position", "birth_date", "rookie_season", "draft_year", "draft_round", "draft_pick"])
    pl = pl[pl.gsis_id.notna()].drop_duplicates("gsis_id")
    dp = pd.read_parquet(os.path.join(CACHE, "draft_picks.parquet"), columns=["season", "pick", "gsis_id", "position"])
    dp = dp[dp.gsis_id.notna()].drop_duplicates("gsis_id").rename(columns={"season": "dp_year", "pick": "dp_pick", "position": "dp_pos"})
    PW, TG = [], []
    for Y in YEARS:
        W, tg = season(Y); PW.append(W); TG.append(tg)
        print(f"  {Y}: {len(W)} player-games, {len(tg)} team-games ({time.time()-t0:.0f}s)", flush=True)
    W = pd.concat(PW, ignore_index=True)
    W = W.merge(pl.rename(columns={"gsis_id": "pid"}), on="pid", how="left").merge(dp.rename(columns={"gsis_id": "pid"}), on="pid", how="left")
    W = W[W.position.isin(["QB", "RB", "WR", "TE", "FB"])].copy()
    W.loc[W.position == "FB", "position"] = "RB"
    W.to_parquet(os.path.join(OUT, "player_weeks.parquet"), index=False)
    TG = pd.concat(TG, ignore_index=True)
    S = pd.read_csv(os.path.join(CACHE, "schedules_games.csv"))
    S = S[(S.game_type == "REG") & S.season.between(2012, 2025)]
    rec = []
    for r in S.itertuples(index=False):
        h, a = tm(r.home_team), tm(r.away_team)
        for team, opp, home, pf, pa in ((h, a, 1, r.home_score, r.away_score), (a, h, 0, r.away_score, r.home_score)):
            sp = r.spread_line if home else -r.spread_line   # nflverse spread_line = home margin expected (positive = home favored)
            rec.append({"game_id": r.game_id, "season": r.season, "week": r.week, "team": team, "opp": opp, "home": home, "pf": pf, "pa": pa,
                        "exp_margin": sp, "total_line": r.total_line, "div_game": r.div_game, "roof": r.roof, "wind": r.wind, "temp": r.temp,
                        "overtime": r.overtime, "ml": r.home_moneyline if home else r.away_moneyline, "rest": r.home_rest if home else r.away_rest,
                        "neutral": int(r.location == "Neutral")})
    G = pd.DataFrame(rec)
    G = G.merge(TG.drop(columns=["week", "season"]), on=["game_id", "team"], how="left")
    G.to_parquet(os.path.join(OUT, "team_games.parquet"), index=False)
    print(f"wrote player_weeks {len(W)} rows, team_games {len(G)} rows ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
