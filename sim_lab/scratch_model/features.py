#!/usr/bin/env python3
"""
features.py - player-game + team-game tables from the raw nflverse play-by-play cache.

Builds, per season, one row per (player, game) for QB/RB/WR/TE with every raw opportunity and
production stat the scratch model needs, plus one row per (team, game) with team volume, score
context and the closing Vegas line.  Everything is derived from E:\\MyFantasyFootball\\pbp_cache
(play_by_play_{Y}.csv.gz, snap_counts_{Y}.parquet, players.csv, injuries_{Y}.parquet) so the
same code produces 2016-2025 history (model fit) and 2026 (the as-of test).

Output: cache/pg_{Y}.parquet (player-game), cache/tg_{Y}.parquet (team-game), cache/inj_{Y}.parquet.
Nothing here looks across weeks - as-of logic lives in model.py.
"""
import os, re, sys, json
import numpy as np, pandas as pd

CACHE = r"E:\MyFantasyFootball\pbp_cache"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "cache")
POS4 = ("QB", "RB", "WR", "TE")
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI",
         "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}


def tm(t):
    return ALIAS.get(t, t)


def norm(n):
    n = (n or "").lower().replace(".", "").replace("'", "").replace("-", " ").replace("\u2019", "")
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    n = " ".join(t for t in n.split() if len(t) > 1 or not t.isalpha())
    return re.sub(r"\s+", " ", n).strip()


USECOLS = ["game_id", "season", "season_type", "week", "posteam", "defteam", "home_team", "away_team",
           "home_score", "away_score", "spread_line", "total_line", "roof", "wind", "temp", "game_date",
           "play_type", "yardline_100", "down", "qtr", "score_differential", "wp",
           "pass_attempt", "complete_pass", "incomplete_pass", "interception", "sack", "qb_kneel", "qb_spike",
           "qb_dropback", "qb_scramble", "rush_attempt", "touchdown", "pass_touchdown", "rush_touchdown",
           "air_yards", "yards_after_catch", "passing_yards", "rushing_yards", "receiving_yards",
           "passer_player_id", "rusher_player_id", "receiver_player_id",
           "fumble_lost", "fumbled_1_player_id", "two_point_conv_result", "two_point_attempt",
           "aborted_play"]

_PLAYERS = None


def players():
    global _PLAYERS
    if _PLAYERS is None:
        p = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False,
                        usecols=["gsis_id", "display_name", "position", "pfr_id", "rookie_season", "birth_date",
                                 "draft_round", "draft_pick"])
        p = p[p.gsis_id.notna()].drop_duplicates("gsis_id").set_index("gsis_id")
        _PLAYERS = p
    return _PLAYERS


def _masked_sum(df, flag, cond):
    """sum of df[flag] over rows where df[cond]==1, grouped later via a helper column"""
    return (df[flag].values * df[cond].values)


def build_season(Y, force=False):
    fpg = os.path.join(OUT, f"pg_{Y}.parquet"); ftg = os.path.join(OUT, f"tg_{Y}.parquet")
    if not force and os.path.exists(fpg) and os.path.exists(ftg):
        return pd.read_parquet(fpg), pd.read_parquet(ftg)
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), usecols=USECOLS, low_memory=False)
    df = df[df.season_type == "REG"].copy()
    for c in ("posteam", "defteam", "home_team", "away_team"):
        df[c] = df[c].map(lambda t: tm(t) if isinstance(t, str) else t)
    df["week"] = df.week.astype(int)
    for c in ("pass_attempt", "complete_pass", "incomplete_pass", "interception", "sack", "qb_kneel", "qb_spike",
              "qb_dropback", "qb_scramble", "rush_attempt", "touchdown", "pass_touchdown", "rush_touchdown",
              "fumble_lost", "two_point_attempt", "aborted_play"):
        df[c] = df[c].fillna(0).astype(int)
    for c in ("air_yards", "yards_after_catch", "passing_yards", "rushing_yards", "receiving_yards", "yardline_100",
              "wp", "score_differential", "qtr"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # ---- game table
    g = df.groupby("game_id").agg(season=("season", "first"), week=("week", "first"), home=("home_team", "first"),
                                  away=("away_team", "first"), hs=("home_score", "max"), as_=("away_score", "max"),
                                  spread=("spread_line", "first"), total=("total_line", "first"), roof=("roof", "first"),
                                  wind=("wind", "first"), temp=("temp", "first"), date=("game_date", "first")).reset_index()
    # ---- play-level flags
    is_pass = (df.pass_attempt == 1) & (df.sack == 0) & (df.qb_spike == 0) & (df.aborted_play == 0)
    is_rush = (df.rush_attempt == 1) & (df.qb_kneel == 0) & (df.aborted_play == 0)
    df["is_pass"] = is_pass.astype(int); df["is_rush"] = is_rush.astype(int)
    df["is_db"] = ((df.qb_dropback == 1) & (df.qb_spike == 0) & (df.qb_kneel == 0)).astype(int)
    df["tgt"] = (is_pass & df.receiver_player_id.notna()).astype(int)
    yl = df.yardline_100
    df["rz"] = (yl <= 20).astype(int); df["gl"] = (yl <= 5).astype(int); df["i10"] = (yl <= 10).astype(int)
    air = df.air_yards
    df["ez_tgt"] = (df.tgt.astype(bool) & (air >= yl)).astype(int)
    df["tgt_s"] = (df.tgt.astype(bool) & (air < 10)).astype(int)
    df["tgt_m"] = (df.tgt.astype(bool) & (air >= 10) & (air < 20)).astype(int)
    df["tgt_d"] = (df.tgt.astype(bool) & (air >= 20)).astype(int)
    df["tgt_bl"] = (df.tgt.astype(bool) & (air < 0)).astype(int)
    df["twopt"] = (df.two_point_conv_result == "success").astype(int)
    df["garbage"] = ((df.qtr >= 4) & (df.score_differential.abs() >= 17)).astype(int)   # plays with the game decided
    df["nog"] = 1 - df.garbage
    df["comp"] = (df.complete_pass == 1).astype(int) * df.is_pass
    df["ptd"] = df.pass_touchdown * df.is_pass
    df["rtd"] = df.rush_touchdown * df.is_rush
    df["int"] = df.interception * df.is_pass
    df["py"] = df.passing_yards.fillna(0) * df.is_pass
    df["ry"] = df.rushing_yards.fillna(0) * df.is_rush
    df["rcy"] = df.receiving_yards.fillna(0) * df.is_pass
    df["airy"] = air.fillna(0) * df.tgt
    df["yac"] = df.yards_after_catch.fillna(0) * df.comp
    # product columns (so every aggregate is a plain sum)
    df["rz_tgt"] = df.rz * df.tgt; df["rz_car"] = df.rz * df.is_rush; df["gl_car"] = df.gl * df.is_rush
    df["i10_car"] = df.i10 * df.is_rush; df["rz_att"] = df.rz * df.is_pass
    df["car_nog"] = df.nog * df.is_rush; df["tgt_nog"] = df.nog * df.tgt; df["att_nog"] = df.nog * df.is_pass
    df["p_twopt"] = df.twopt * df.is_pass; df["r_twopt"] = df.twopt * df.is_rush; df["c_twopt"] = df.twopt * df.tgt
    # ---- team-game
    key = ["game_id", "posteam"]
    tgm = df[df.posteam.notna()].groupby(key).agg(
        t_att=("is_pass", "sum"), t_db=("is_db", "sum"), t_car=("is_rush", "sum"), t_tgt=("tgt", "sum"),
        t_rz_tgt=("rz_tgt", "sum"), t_rz_car=("rz_car", "sum"), t_gl_car=("gl_car", "sum"), t_i10_car=("i10_car", "sum"),
        t_ez_tgt=("ez_tgt", "sum"), t_ptd=("ptd", "sum"), t_rtd=("rtd", "sum"), t_py=("py", "sum"), t_ry=("ry", "sum"),
        t_airy=("airy", "sum"), t_garbage=("garbage", "sum"), t_sk=("sack", "sum"),
        t_att_nog=("att_nog", "sum"), t_car_nog=("car_nog", "sum"), t_tgt_nog=("tgt_nog", "sum"),
    ).reset_index().rename(columns={"posteam": "team"})
    tgm = tgm.merge(g, on="game_id")
    tgm["is_home"] = (tgm.team == tgm.home).astype(int)
    tgm["opp"] = np.where(tgm.is_home == 1, tgm.away, tgm.home)
    tgm["pts"] = np.where(tgm.is_home == 1, tgm.hs, tgm.as_)
    tgm["opp_pts"] = np.where(tgm.is_home == 1, tgm.as_, tgm.hs)
    # nflverse spread_line: positive = home favored by that many. implied = total/2 +- spread/2
    hi = tgm.total / 2 + tgm.spread / 2; ai = tgm.total / 2 - tgm.spread / 2
    tgm["implied"] = np.where(tgm.is_home == 1, hi, ai); tgm["opp_implied"] = np.where(tgm.is_home == 1, ai, hi)
    tgm["tspread"] = np.where(tgm.is_home == 1, -tgm.spread, tgm.spread)   # team's own spread (negative = favored)
    tgm["indoor"] = tgm.roof.isin(["dome", "closed"]).astype(int)
    tgm["wind"] = pd.to_numeric(tgm.wind, errors="coerce"); tgm["temp"] = pd.to_numeric(tgm.temp, errors="coerce")
    tgm = tgm.drop(columns=["hs", "as_", "home", "away"])
    # ---- player-game
    P = players()

    def agg_role(idcol, cols):
        sub = df[df[idcol].notna()]
        o = sub.groupby(["game_id", "posteam", idcol])[list(cols.values())].sum().reset_index()
        o = o.rename(columns={idcol: "pid", "posteam": "team"}).rename(columns={v: k for k, v in cols.items()})
        return o

    pas = agg_role("passer_player_id", dict(att="is_pass", cmp="comp", py="py", ptd="ptd", int="int", sk="sack", p_air="airy",
                                            p_rz_att="rz_att", p_twopt="p_twopt", att_nog="att_nog"))
    rus = agg_role("rusher_player_id", dict(car="is_rush", ry="ry", rtd="rtd", scr="qb_scramble", gl_car="gl_car", i10_car="i10_car",
                                            rz_car="rz_car", car_nog="car_nog", r_twopt="r_twopt"))
    rec = agg_role("receiver_player_id", dict(tgt="tgt", rec="comp", rcy="rcy", rctd="ptd", airy="airy", yac="yac", ez_tgt="ez_tgt",
                                              rz_tgt="rz_tgt", tgt_s="tgt_s", tgt_m="tgt_m", tgt_d="tgt_d", tgt_bl="tgt_bl",
                                              tgt_nog="tgt_nog", c_twopt="c_twopt"))
    fum = df[(df.fumble_lost == 1) & df.fumbled_1_player_id.notna()].groupby(["game_id", "posteam", "fumbled_1_player_id"]).size()
    fum = fum.reset_index(name="fl").rename(columns={"fumbled_1_player_id": "pid", "posteam": "team"})
    pg = pas.merge(rus, on=["game_id", "team", "pid"], how="outer").merge(rec, on=["game_id", "team", "pid"], how="outer")
    pg = pg.merge(fum, on=["game_id", "team", "pid"], how="outer").fillna(0)
    pg["twopt"] = pg.p_twopt + pg.r_twopt + pg.c_twopt
    # snap counts (pfr id -> gsis)
    pfr2g = {v: k for k, v in P.pfr_id.dropna().items()}
    try:
        sc = pd.read_parquet(os.path.join(CACHE, f"snap_counts_{Y}.parquet"))
        sc = sc[(sc.game_type == "REG")].copy()
        sc["pid"] = sc.pfr_player_id.map(pfr2g); sc["team"] = sc.team.map(tm)
        sc = sc[sc.pid.notna()][["game_id", "team", "pid", "offense_snaps", "offense_pct"]].copy()
        sc["offense_pct"] = sc.offense_pct.astype(float) * 100
        sc = sc.drop_duplicates(["game_id", "pid"])
        pg = pg.merge(sc, on=["game_id", "team", "pid"], how="outer")
    except FileNotFoundError:
        pg["offense_snaps"] = np.nan; pg["offense_pct"] = np.nan
    pg["pos"] = pg.pid.map(P.position); pg["name"] = pg.pid.map(P.display_name)
    pg = pg[pg.pos.isin(POS4) & pg.team.notna()].copy()
    num = [c for c in pg.columns if c not in ("game_id", "team", "pid", "pos", "name")]
    pg[num] = pg[num].fillna(0)
    pg = pg.merge(tgm[["game_id", "team", "season", "week", "opp", "is_home"]], on=["game_id", "team"], how="inner")
    pg["pts_half"] = (pg.py * .04 + pg.ptd * 4 - pg["int"] * 2 + pg.ry * .1 + pg.rtd * 6 + pg.rec * .5 + pg.rcy * .1
                      + pg.rctd * 6 - pg.fl * 2 + pg.twopt * 2).round(2)
    pg["pts_ppr"] = (pg.pts_half + pg.rec * .5).round(2)
    pg["played"] = ((pg.offense_snaps > 0) | (pg.att + pg.car + pg.tgt > 0)).astype(int)
    pg["season"] = Y
    pg.to_parquet(fpg, index=False); tgm.to_parquet(ftg, index=False)
    return pg, tgm


def build_injuries(Y, force=False):
    """(season, week, pid) -> game status as-of the report: Out / Doubtful / Questionable / '' ; 2026 from practice_seq_2026.json."""
    f = os.path.join(OUT, f"inj_{Y}.parquet")
    if not force and os.path.exists(f):
        return pd.read_parquet(f)
    if Y <= 2025:
        i = pd.read_parquet(os.path.join(CACHE, f"injuries_{Y}.parquet"))
        i = i[(i.game_type == "REG") & i.position.isin(POS4)]
        o = i[["week", "gsis_id", "report_status", "practice_status"]].rename(
            columns={"gsis_id": "pid", "report_status": "gs", "practice_status": "pr"}).copy()
        o["gs"] = o.gs.fillna(""); o["pr"] = o.pr.fillna("")
        o["pr"] = o.pr.map(lambda s: "DNP" if s.startswith("Did Not") else "LP" if s.startswith("Limited")
                           else "FP" if s.startswith("Full") else "")
    else:
        seq = json.load(open(r"E:\MyFantasyFootball\sim_lab\data\practice_seq_2026.json", encoding="utf-8"))
        P = players(); by = {}
        for pid, r in P[P.position.isin(POS4)].iterrows():
            by.setdefault((norm(r.display_name), r.position), []).append(pid)
        rows = []
        for wk, d in seq.items():
            for k, r in d.items():
                c = by.get((norm(r.get("name")), r.get("pos")))
                if not c or len(c) > 1:
                    continue
                days = r.get("days") or {}
                last = [v for _, v in sorted(days.items())][-1] if days else ""
                rows.append(dict(week=int(wk), pid=c[0], gs=r.get("gs") or "", pr=last))
        o = pd.DataFrame(rows)
    o["season"] = Y
    o = o.drop_duplicates(["season", "week", "pid"], keep="last")
    o.to_parquet(f, index=False)
    return o


if __name__ == "__main__":
    years = [int(a) for a in sys.argv[1:]] or list(range(2016, 2027))
    for Y in years:
        pg, tg = build_season(Y, force=True)
        inj = build_injuries(Y, force=True)
        print(Y, "player-games", len(pg), "team-games", len(tg), "inj rows", len(inj), "weeks", int(pg.week.max()))
