#!/usr/bin/env python3
"""
VOLUME FORECAST STUDY - data builder (Jack 2026-10-13: "for the sims the most important thing is overall usage, carry %,
routes, xFP etc and implement it the best way possible while applying context like injuries, blowouts etc.").

Builds per player-game and per team-game opportunity tables 2018-25 (REG season) from nflverse pbp + participation:
  player-game  tg, car, xfp (same bucket xFP as build_context_features / the harness evidence), on-field plays (snaps),
               on-field dropbacks (route proxy) - each on ALL plays and on COMPETITIVE plays only
               (garbage = Q4 |margin| >= 17 or Q3 >= 28, the engine ctxShare rule)
  team-game    plays, dropbacks, pass att, targets, non-QB carries (all + competitive), garbage plays, starting QB
               (most dropbacks), spread / total / implied from the team's side (spread > 0 = underdog), final margin
Writes _tmp/vf_games.parquet and _tmp/vf_teams.parquet. Research only; nothing wired.
"""
import os, sys, time
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_common as B
from pull_pace_tracker import _xfp_ab, _xtd_rec, _xfp_rush, _xtd, XFP_CATCH, XFP_TGT_YDS
CACHE = B.CACHE
OUTD = os.path.join(HERE, "_tmp"); os.makedirs(OUTD, exist_ok=True)


def pos_map():
    p = pd.read_csv(os.path.join(CACHE, "players.csv"), usecols=["gsis_id", "position"], low_memory=False)
    return {r.gsis_id: ("RB" if r.position == "FB" else r.position) for r in p.itertuples(index=False) if isinstance(r.gsis_id, str)}


def season(Y, pos_of):
    cols = ["game_id", "play_id", "season_type", "week", "posteam", "defteam", "home_team", "away_team", "qtr", "score_differential",
            "pass_attempt", "rush_attempt", "sack", "qb_dropback", "two_point_attempt", "receiver_player_id", "rusher_player_id",
            "passer_player_id", "yardline_100", "air_yards", "spread_line", "total_line", "result"]
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), usecols=cols, low_memory=False)
    df = df[(df.season_type == "REG") & df.posteam.notna() & (df.two_point_attempt.fillna(0) != 1)].copy()
    df = df[(df.pass_attempt == 1) | (df.rush_attempt == 1) | (df.qb_dropback == 1)]
    pp = pd.read_parquet(os.path.join(CACHE, f"pbp_participation_{Y}.parquet"), columns=["nflverse_game_id", "play_id", "offense_players"])
    on = {(g, int(p)): s for g, p, s in zip(pp.nflverse_game_id, pp.play_id, pp.offense_players) if isinstance(s, str) and s}
    sd = df.score_differential.fillna(0).abs(); q = df.qtr.fillna(1)
    df["garb"] = ((q == 4) & (sd >= 17)) | ((q == 3) & (sd >= 28))
    pw = defaultdict(lambda: defaultdict(float)); tw = defaultdict(lambda: defaultdict(float)); ptm = {}
    qbdb = defaultdict(lambda: defaultdict(int)); meta = {}
    for r in df.itertuples(index=False):
        t = B.tm(str(r.posteam)); wk = int(r.week); gb = bool(r.garb); key = (t, wk)
        if key not in meta:
            home = B.tm(str(r.home_team)) == t; sl = float(r.spread_line) if pd.notna(r.spread_line) else np.nan; tl = float(r.total_line) if pd.notna(r.total_line) else np.nan
            spread = -sl if home else sl   # > 0 = underdog (engine convention)
            res = float(r.result) if pd.notna(r.result) else np.nan; margin = res if home else -res
            meta[key] = dict(opp=B.tm(str(r.defteam)), home=int(home), spread=spread, total=tl, implied=(tl - spread) / 2.0 if not np.isnan(tl) else np.nan, margin=margin, gid=r.game_id)
        isp = r.pass_attempt == 1 or r.rush_attempt == 1; isdb = r.qb_dropback == 1
        T = tw[key]
        for suf, use in (("", True), ("_c", not gb)):
            if not use: continue
            if isp: T["plays" + suf] += 1
            if isdb: T["db" + suf] += 1
        if gb and isp: T["garb"] += 1
        if gb and isdb: T["gdb"] += 1
        yl = float(r.yardline_100) if pd.notna(r.yardline_100) else 50.0
        if r.pass_attempt == 1 and r.sack != 1:
            T["att"] += 1; T["att_c"] += (not gb)
            rcv = r.receiver_player_id
            if isinstance(rcv, str):
                a = float(r.air_yards) if pd.notna(r.air_yards) else 0.0; b = _xfp_ab(a)
                x = 0.5 * XFP_CATCH[b] + 0.1 * XFP_TGT_YDS[b] + 6 * _xtd_rec(yl, a >= yl)
                T["tg"] += 1; T["tg_c"] += (not gb); Q = pw[(rcv, wk)]; ptm[(rcv, wk)] = t
                Q["tg"] += 1; Q["xfp"] += x; Q["xfp_rec"] += x
                if not gb: Q["tg_c"] += 1; Q["xfp_c"] += x
        if r.rush_attempt == 1 and isinstance(r.rusher_player_id, str):
            pid = r.rusher_player_id; x = 0.1 * _xfp_rush(yl, False) + 6 * _xtd(yl, True)
            Q = pw[(pid, wk)]; ptm[(pid, wk)] = t; Q["car"] += 1; Q["xfp"] += x; Q["xfp_rush"] += x
            if not gb: Q["car_c"] += 1; Q["xfp_c"] += x
            if pos_of.get(pid) != "QB": T["car"] += 1; T["car_c"] += (not gb)
        if isdb and isinstance(r.passer_player_id, str): qbdb[key][r.passer_player_id] += 1
        s = on.get((r.game_id, int(r.play_id)))
        if s:
            if isp: T["pp_plays"] += 1; T["pp_plays_c"] += (not gb)
            if isdb: T["pp_db"] += 1; T["pp_db_c"] += (not gb)
            for pid in s.split(";"):
                if pos_of.get(pid) not in ("QB", "RB", "WR", "TE"): continue
                Q = pw[(pid, wk)]; ptm.setdefault((pid, wk), t)
                if isp: Q["on"] += 1; Q["on_c"] += (not gb)
                if isdb: Q["on_db"] += 1; Q["on_db_c"] += (not gb)
    rows = []
    for (pid, wk), v in pw.items():
        t = ptm[(pid, wk)]; rows.append(dict(year=Y, pid=pid, wk=wk, team=t, pos=pos_of.get(pid), **{k: v.get(k, 0.0) for k in ("tg", "tg_c", "car", "car_c", "xfp", "xfp_c", "xfp_rec", "xfp_rush", "on", "on_c", "on_db", "on_db_c")}))
    trows = []
    for key, v in tw.items():
        qb = max(qbdb[key].items(), key=lambda kv: kv[1])[0] if qbdb[key] else None
        trows.append(dict(year=Y, team=key[0], wk=key[1], qb=qb, **meta[key], **{k: v.get(k, 0.0) for k in ("plays", "plays_c", "db", "db_c", "att", "att_c", "tg", "tg_c", "car", "car_c", "garb", "gdb", "pp_plays", "pp_plays_c", "pp_db", "pp_db_c")}))
    return pd.DataFrame(rows), pd.DataFrame(trows)


def main():
    t0 = time.time(); pos_of = pos_map(); G = []; T = []
    for Y in range(2018, 2026):
        g, t = season(Y, pos_of); G.append(g); T.append(t); print(Y, len(g), len(t), f"{time.time()-t0:.0f}s", flush=True)
    G = pd.concat(G, ignore_index=True); T = pd.concat(T, ignore_index=True)
    G.to_parquet(os.path.join(OUTD, "vf_games.parquet")); T.to_parquet(os.path.join(OUTD, "vf_teams.parquet"))
    print("participation coverage (plays):", float(T.pp_plays.sum() / T.plays.sum()))


if __name__ == "__main__":
    main()
