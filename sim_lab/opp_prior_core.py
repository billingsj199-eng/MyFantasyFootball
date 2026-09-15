#!/usr/bin/env python3
"""
Shared season loaders for the OPPORTUNITY PRIOR (backtest_opp_prior.py grades it, build_opp_prior.py builds the
live 2026 file). Same logic as the backtest's load_positions / load_season, kept import-safe: no log file, no stdout
wrapping at import. Half-PPR receiving + rushing points, site xFP tables from pull_pace_tracker.
"""
import os
from collections import defaultdict, Counter
import pandas as pd

from pull_pace_tracker import _xfp_ab, _xtd_rec, _xfp_rush, _xtd, XFP_CATCH, XFP_TGT_YDS

CACHE = r"E:\MyFantasyFootball\pbp_cache"
SKILL = ("RB", "WR", "TE")
K_VAL, K_EFF = 60.0, 150.0
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}


def tm(t):
    return ALIAS.get(t, t)


def load_positions():
    p = pd.read_csv(os.path.join(CACHE, "players.csv"), usecols=["gsis_id", "position", "display_name", "birth_date"], low_memory=False)
    pos, name, bd = {}, {}, {}
    for r in p.itertuples(index=False):
        if not isinstance(r.gsis_id, str):
            continue
        ps = "RB" if r.position == "FB" else r.position
        pos[r.gsis_id] = ps; name[r.gsis_id] = r.display_name
        bd[r.gsis_id] = pd.to_datetime(r.birth_date, errors="coerce") if isinstance(r.birth_date, str) else pd.NaT
    return pos, name, bd


def load_season(Y, pos_of):
    """-> (players {gsis: {pos, tm, g, tg, car, xr, xc, act, ts, cs}}, teams {tm: {tg_pg, car_pg, g}})"""
    cols = ["season_type", "week", "posteam", "pass_attempt", "rush_attempt", "sack", "receiver_player_id", "rusher_player_id",
            "yardline_100", "air_yards", "complete_pass", "receiving_yards", "rushing_yards", "pass_touchdown", "rush_touchdown", "td_player_id"]
    pbp = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), usecols=cols, low_memory=False)
    pbp = pbp[(pbp.season_type == "REG") & pbp.posteam.notna()]
    pl = defaultdict(lambda: {"tg": 0, "car": 0, "xr": 0.0, "xc": 0.0, "act": 0.0, "weeks": set(), "tm": Counter()})
    tm_ = defaultdict(lambda: {"tg": 0, "car": 0, "weeks": set()})
    pa = pbp[(pbp.pass_attempt == 1) & (pbp.sack != 1) & pbp.receiver_player_id.notna()]
    for r in pa.itertuples(index=False):
        t = tm(str(r.posteam)); wk = int(r.week)
        tm_[t]["tg"] += 1; tm_[t]["weeks"].add(wk)
        rcv = r.receiver_player_id
        if pos_of.get(rcv) not in SKILL:
            continue
        yl = float(r.yardline_100) if pd.notna(r.yardline_100) else 50.0
        a = float(r.air_yards) if pd.notna(r.air_yards) else 0.0
        b = _xfp_ab(a)
        q = pl[rcv]; q["tg"] += 1; q["weeks"].add(wk); q["tm"][t] += 1
        q["xr"] += 0.5 * XFP_CATCH[b] + 0.1 * XFP_TGT_YDS[b] + 6 * _xtd_rec(yl, a >= yl)
        if r.complete_pass == 1:
            q["act"] += 0.5 + 0.1 * (float(r.receiving_yards) if pd.notna(r.receiving_yards) else 0.0)
            if r.pass_touchdown == 1 and (pd.isna(r.td_player_id) or r.td_player_id == rcv):
                q["act"] += 6
    ru = pbp[(pbp.rush_attempt == 1) & pbp.rusher_player_id.notna()]
    for r in ru.itertuples(index=False):
        pid = r.rusher_player_id
        if pos_of.get(pid) == "QB":
            continue
        t = tm(str(r.posteam)); wk = int(r.week)
        tm_[t]["car"] += 1; tm_[t]["weeks"].add(wk)
        if pos_of.get(pid) not in SKILL:
            continue
        yl = float(r.yardline_100) if pd.notna(r.yardline_100) else 50.0
        q = pl[pid]; q["car"] += 1; q["weeks"].add(wk); q["tm"][t] += 1
        q["xc"] += 0.1 * _xfp_rush(yl, False) + 6 * _xtd(yl, True)
        q["act"] += 0.1 * (float(r.rushing_yards) if pd.notna(r.rushing_yards) else 0.0)
        if r.rush_touchdown == 1 and (pd.isna(r.td_player_id) or r.td_player_id == pid):
            q["act"] += 6
    teams = {t: {"tg_pg": v["tg"] / len(v["weeks"]), "car_pg": v["car"] / len(v["weeks"]), "g": len(v["weeks"])} for t, v in tm_.items() if v["weeks"]}
    players = {}
    for pid, q in pl.items():
        g = len(q["weeks"])
        t = q["tm"].most_common(1)[0][0]
        tv = teams.get(t)
        if not g or not tv:
            continue
        players[pid] = {"pos": pos_of[pid], "tm": t, "g": g, "tg": q["tg"], "car": q["car"], "xr": q["xr"], "xc": q["xc"], "act": q["act"],
                        "ts": (q["tg"] / g) / tv["tg_pg"] if tv["tg_pg"] else 0.0, "cs": (q["car"] / g) / tv["car_pg"] if tv["car_pg"] else 0.0}
    return players, teams
