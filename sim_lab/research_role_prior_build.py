#!/usr/bin/env python3
"""
PER-GAME ROLE TABLE for research_role_prior.py (Jack 2026-10-20: "is there a way to add the real role that adp covers through
6 weeks" + "does it filter out injury reasoning or outside reasoning based on news?"). Research only - nothing in the engine reads it.

One row per player-game 2019-25 (REG, offense): targets, carries, red-zone / goal-line work, air yards, xFP (same formulas as
build_context_features.pbp_tables), on-field plays and on-field dropbacks (route proxy, nflverse participation), each ALSO on
COMPETITIVE plays only (garbage = Q4 and |score diff| >= 17, or Q3 and >= 28 - the SIM_GAMECTX rule), plus nflverse snap-count
share. Team-game totals the same way (team shares exclude QB carries, as in ctx_features), RB-room carries + targets, the game's
QB (most dropbacks) and the final margin. Status tables: final injury report + weekly roster status (for "absent at week wk").

Output: sim_lab/_tmp/role_games.pkl  {"pg": DataFrame, "tg": DataFrame, "inj": {(Y,t,wk,pid): (report, practice)}, "ros": {...},
"ros_have": set, "pos_of": {pid: pos}}
"""
import os, sys, pickle, time
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_common as B
import build_context_features as BC
from pull_pace_tracker import _xfp_ab, _xtd_rec, _xfp_rush, _xtd, XFP_CATCH, XFP_TGT_YDS
CACHE = B.CACHE; YEARS = list(range(2019, 2026))
OUT = os.path.join(HERE, "_tmp", "role_games.pkl")


def year_tables(Y, pos_of):
    cols = ["game_id", "play_id", "season_type", "week", "posteam", "qtr", "score_differential", "pass_attempt", "rush_attempt", "sack", "qb_dropback",
            "two_point_attempt", "receiver_player_id", "rusher_player_id", "passer_player_id", "yardline_100", "air_yards", "home_team", "away_team",
            "home_score", "away_score"]
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), usecols=cols, low_memory=False)
    df = df[(df.season_type == "REG") & df.posteam.notna() & (df.two_point_attempt.fillna(0) != 1)].copy()
    df["tm"] = df.posteam.map(lambda t: B.tm(str(t))); df["week"] = df.week.astype(int)
    sd = df.score_differential.abs().fillna(0); q = df.qtr.fillna(1)
    df["gar"] = ((q >= 4) & (sd >= 17)) | ((q == 3) & (sd >= 28))
    df["yl"] = df.yardline_100.fillna(50.0)
    # final margin per team-week
    fin = df.groupby("game_id").agg(h=("home_team", "first"), a=("away_team", "first"), hs=("home_score", "max"), as_=("away_score", "max"), wk=("week", "first"))
    margin = {}
    for r in fin.itertuples():
        m = abs(float(r.hs) - float(r.as_)); margin[(B.tm(r.h), int(r.wk))] = m; margin[(B.tm(r.a), int(r.wk))] = m
    P = defaultdict(lambda: defaultdict(float)); T = defaultdict(lambda: defaultdict(float)); ptm = {}
    def add(d, k, v, comp):
        d[k] += v
        if comp: d[k + "_c"] += v
    # targets
    pa = df[(df.pass_attempt == 1) & (df.sack != 1)]
    for r in pa.itertuples(index=False):
        t, wk, c = r.tm, r.week, not r.gar
        rcv = r.receiver_player_id
        if not isinstance(rcv, str): continue
        a = float(r.air_yards) if pd.notna(r.air_yards) else 0.0; y = r.yl
        tt = T[(t, wk)]; add(tt, "tg", 1, c); add(tt, "ay", max(a, 0.0), c); add(tt, "rz_tg", y <= 20, c)
        rp = pos_of.get(rcv)
        if rp == "RB": add(tt, "room_RB", 1, c)
        q_ = P[(rcv, wk)]; ptm[(rcv, wk)] = t
        b = _xfp_ab(a)
        add(q_, "tg", 1, c); add(q_, "ay", a, c); add(q_, "rz_tg", y <= 20, c)
        q_["xfp"] += 0.5 * XFP_CATCH[b] + 0.1 * XFP_TGT_YDS[b] + 6 * _xtd_rec(y, a >= y)
    ru = df[(df.rush_attempt == 1) & df.rusher_player_id.notna()]
    for r in ru.itertuples(index=False):
        t, wk, pid, c, y = r.tm, r.week, r.rusher_player_id, not r.gar, r.yl
        rp = pos_of.get(pid); q_ = P[(pid, wk)]; ptm[(pid, wk)] = t
        add(q_, "car", 1, c); add(q_, "rz_car", y <= 20, c); add(q_, "gl_car", y <= 5, c)
        q_["xfp"] += 0.1 * _xfp_rush(y, False) + 6 * _xtd(y, True)
        if rp != "QB":
            tt = T[(t, wk)]; add(tt, "car", 1, c); add(tt, "rz_car", y <= 20, c); add(tt, "gl_car", y <= 5, c)
            if rp == "RB": add(tt, "room_RB", 1, c)
    db = df[df.qb_dropback == 1]
    qbdb = defaultdict(lambda: defaultdict(float))
    for r in db.itertuples(index=False):
        t, wk, c = r.tm, r.week, not r.gar
        add(T[(t, wk)], "db", 1, c)
        if isinstance(r.passer_player_id, str):
            qbdb[(t, wk)][r.passer_player_id] += 1; ptm.setdefault((r.passer_player_id, wk), t)
            add(P[(r.passer_player_id, wk)], "db", 1, c); P[(r.passer_player_id, wk)]["att"] += (r.pass_attempt == 1 and r.sack != 1)
    pl = df[(df.pass_attempt == 1) | (df.rush_attempt == 1) | (df.qb_dropback == 1)]
    for (t, wk, gar), n_ in pl.groupby(["tm", "week", "gar"]).size().items():
        T[(t, wk)]["pl"] += n_
        if not gar: T[(t, wk)]["pl_c"] += n_
    gameqb = {k: max(v, key=v.get) for k, v in qbdb.items()}
    # participation: on-field plays + on-field dropbacks (all / competitive)
    pp = os.path.join(CACHE, f"pbp_participation_{Y}.parquet")
    part = pd.read_parquet(pp, columns=["nflverse_game_id", "play_id", "offense_players"])
    part = part[part.offense_players.fillna("") != ""]
    key = pl[["game_id", "play_id", "tm", "week", "gar", "qb_dropback"]].rename(columns={"game_id": "nflverse_game_id"})
    m = key.merge(part, on=["nflverse_game_id", "play_id"], how="inner")
    m["db1"] = (m.qb_dropback == 1)
    # team plays WITH participation (denominators for the on-field shares)
    for (t, wk), g_ in m.groupby(["tm", "week"]):
        tt = T[(t, wk)]; tt["ppl"] = len(g_); tt["ppl_c"] = int((~g_.gar).sum()); tt["pdb"] = int(g_.db1.sum()); tt["pdb_c"] = int((g_.db1 & ~g_.gar).sum())
    ex = m[["tm", "week", "gar", "db1", "offense_players"]].copy(); ex["pid"] = ex.offense_players.str.split(";"); ex = ex.explode("pid")
    ex = ex[ex.pid.str.len() > 3]
    ex["one"] = 1; ex["comp"] = (~ex.gar).astype(int); ex["dbi"] = ex.db1.astype(int); ex["dbc"] = (ex.db1 & ~ex.gar).astype(int)
    agg = ex.groupby(["pid", "week", "tm"])[["one", "comp", "dbi", "dbc"]].sum().reset_index()
    for r in agg.itertuples(index=False):
        q_ = P[(r.pid, int(r.week))]; ptm.setdefault((r.pid, int(r.week)), r.tm)
        q_["on"] = float(r.one); q_["on_c"] = float(r.comp); q_["ondb"] = float(r.dbi); q_["ondb_c"] = float(r.dbc)
    rows = []
    for (pid, wk), v in P.items():
        t = ptm.get((pid, wk))
        rows.append(dict(year=Y, pid=pid, wk=int(wk), team=t, pos=pos_of.get(pid), **v))
    pg = pd.DataFrame(rows).fillna(0.0)
    trows = []
    for (t, wk), v in T.items():
        trows.append(dict(year=Y, team=t, wk=int(wk), qb=gameqb.get((t, wk)), margin=margin.get((t, wk), np.nan), **v))
    tg = pd.DataFrame(trows)
    # nflverse snap share (the raw snap_std source)
    sc = pd.read_parquet(os.path.join(CACHE, f"snap_counts_{Y}.parquet"), columns=["week", "game_type", "player", "pfr_player_id", "team", "offense_pct", "offense_snaps"])
    sc = sc[(sc.game_type == "REG") & (sc.offense_snaps > 0)]
    sn = pd.DataFrame({"nm": sc.player.map(BC.norm), "team": sc.team.map(lambda x: B.tm(str(x))), "wk": sc.week.astype(int), "snap_pct": 100 * sc.offense_pct.astype(float)})
    return pg, tg, sn


def main():
    t0 = time.time()
    pos_of, _, _ = BC.load_positions()
    p = pd.read_csv(os.path.join(CACHE, "players.csv"), usecols=["gsis_id", "display_name"], low_memory=False)
    name_of = {r.gsis_id: BC.norm(r.display_name) for r in p.itertuples(index=False) if isinstance(r.gsis_id, str) and isinstance(r.display_name, str)}
    PG, TG, SN_ = [], [], []; INJ, ROS, HAVE = {}, {}, set()
    for Y in YEARS:
        pg, tg, sn = year_tables(Y, pos_of)
        pg["nm"] = pg.pid.map(name_of)
        sn["year"] = Y
        pg = pg.merge(sn, on=["nm", "team", "wk"], how="left")
        PG.append(pg); TG.append(tg)
        inj, _ = BC.injuries(Y); ros, have, _ = BC.rosters(Y)
        for k, v in inj.items(): INJ[(Y,) + k] = v
        for k, v in ros.items(): ROS[(Y,) + k] = v
        for k in have: HAVE.add((Y,) + k)
        print(f"  {Y}: player-games {len(pg):,}  with participation {(pg.on > 0).mean():.2f}  snap pct matched {pg.snap_pct.notna().mean():.2f}  ({time.time()-t0:.0f}s)", flush=True)
    out = {"pg": pd.concat(PG, ignore_index=True), "tg": pd.concat(TG, ignore_index=True), "inj": INJ, "ros": ROS, "ros_have": HAVE, "pos_of": pos_of}
    pickle.dump(out, open(OUT, "wb"))
    print("wrote", OUT, f"{time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
