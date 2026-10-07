#!/usr/bin/env python3
"""
Team pass-VOLUME parts for the live volume-context layer (backtest_volume_context.py, 2026-10-07): season-to-date per
team from the nflverse play-by-play - pass attempts per game, plays per game (pass + run), neutral-script pass rate
(quarters 1-3, score within 8) and SCRIPT EXCESS = att/g - neutral rate x plays/g.  Injected into data/pace_2026.js as
teams[t].cur.vol = {games, att, plays, nrate, exc}; pull_pace_tracker.py calls inject() at the end of its pace build so
the daily task carries it, and this file can be run alone after a fresh play_by_play_2026.csv.gz.
"""
import json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = r"E:\MyFantasyFootball\pbp_cache"
PACE = os.path.join(HERE, "data", "pace_2026.js")
TM_ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI"}


def team_vol(season=2026):
    p = os.path.join(CACHE, f"play_by_play_{season}.csv.gz")
    if not os.path.exists(p): return {}
    d = pd.read_csv(p, compression="gzip", usecols=["week", "posteam", "pass_attempt", "play_type", "qtr", "score_differential", "season_type"], low_memory=False)
    d = d[(d.season_type == "REG") & d.posteam.notna() & d.play_type.isin(["pass", "run"])]
    d["neutral"] = (d.qtr <= 3) & (d.score_differential.abs() <= 8)
    out = {}
    for tm, g in d.groupby("posteam"):
        t = TM_ALIAS.get(str(tm), str(tm)); games = g.week.nunique()
        if games < 1: continue
        nt = g[g.neutral]; att = g.pass_attempt.sum() / games; plays = len(g) / games
        nrate = float(nt.pass_attempt.sum() / len(nt)) if len(nt) >= 20 else None
        out[t] = {"games": int(games), "att": round(float(att), 2), "plays": round(float(plays), 2), "nrate": round(nrate, 4) if nrate is not None else None,
                  "exc": round(float(att - nrate * plays), 2) if nrate is not None else None}
    return out


def inject(pace_path=PACE, season=2026):
    vol = team_vol(season)
    if not vol: print("no play-by-play for the season - vol not injected"); return 0
    s = open(pace_path, encoding="utf-8").read(); i = s.index("{"); head = s[:i]
    obj, end = json.JSONDecoder().raw_decode(s[i:])
    n = 0
    for t, rec in obj.get("teams", {}).items():
        v = vol.get(t)
        if rec.get("cur") is None: rec["cur"] = {"games": 0}
        if v: rec["cur"]["vol"] = v; n += 1
        else: rec["cur"].pop("vol", None)
    with open(pace_path, "w", encoding="utf-8") as f:
        f.write(head + json.dumps(obj, separators=(",", ":")) + ";\n")
    print(f"pace vol injected for {n} teams: " + ", ".join(f"{t} att {vol[t]['att']} exc {vol[t]['exc']}" for t in sorted(vol)[:6]) + " ...")
    return n


if __name__ == "__main__":
    inject()
