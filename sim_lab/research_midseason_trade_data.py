#!/usr/bin/env python3
"""
MID-SEASON TEAM CHANGES - per-game data (Jack 2026-10-20, MHJ ARI -> HOU). Research only, nothing live reads this.

Per-week team from nflverse snap_counts (game-based; roster_weekly fallback), for every QB/RB/WR/TE player-season
2019-2026 that played offensive snaps for 2+ teams in the regular season. Per game: team, offense snap %, route
proxy (on the field for a team dropback / team dropbacks, pbp_participation; 2019-25 only), targets / team targets,
carries / team non-QB carries, xFP (the ctx builder's formula), dropbacks.
Writes _tmp/mst/mover_games.pkl  {(Y, gsis): {"name","pos","weeks": {wk: {...}}, "teams": [...], "events": [(wk_first_new, old, new)]}}
"""
import os, sys, pickle, time
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_common as B
import build_context_features as BCF
CACHE = B.CACHE
OUTD = os.path.join(HERE, "_tmp", "mst"); os.makedirs(OUTD, exist_ok=True)
POS4 = ("QB", "RB", "WR", "TE")

def main():
    t0 = time.time()
    pl = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "pfr_id", "display_name", "position", "birth_date"])
    pfr2g = {r.pfr_id: r.gsis_id for r in pl.itertuples(index=False) if isinstance(r.pfr_id, str) and isinstance(r.gsis_id, str)}
    pos_of, bd_of, rook_of = BCF.load_positions()
    out = {}
    for Y in [int(y) for y in os.environ.get("MST_YEARS", "2019-2026").split("-")] and range(int(os.environ.get("MST_YEARS", "2019-2026").split("-")[0]), int(os.environ.get("MST_YEARS", "2019-2026").split("-")[1]) + 1):
        sc = pd.read_parquet(os.path.join(CACHE, f"snap_counts_{Y}.parquet"), columns=["week", "game_type", "player", "pfr_player_id", "position", "team", "offense_snaps", "offense_pct"])
        sc = sc[(sc.game_type == "REG") & (sc.offense_snaps > 0) & sc.position.isin(list(POS4) + ["FB"])]
        sc["gsis"] = sc.pfr_player_id.map(pfr2g); sc["tm"] = sc.team.map(lambda t: B.tm(str(t)))
        per = defaultdict(dict); nm = {}
        for r in sc.itertuples(index=False):
            k = r.gsis if isinstance(r.gsis, str) else "pfr:" + str(r.pfr_player_id)
            per[k][int(r.week)] = (r.tm, 100.0 * float(r.offense_pct)); nm[k] = (r.player, "RB" if r.position == "FB" else r.position)
        movers = {k: v for k, v in per.items() if len({t for t, _ in v.values()}) >= 2}
        print(f"{Y}: {len(movers)} snap-count players with 2+ teams ({time.time()-t0:.0f}s)")
        if not movers: continue
        pw, ptm, tw = BCF.pbp_tables(Y, pos_of)
        # route proxy from participation (on field on team dropbacks)
        rshare = {}
        pp = os.path.join(CACHE, f"pbp_participation_{Y}.parquet")
        if os.path.exists(pp):
            pa = pd.read_parquet(pp, columns=["nflverse_game_id", "play_id", "offense_players"])
            pb = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), usecols=["game_id", "play_id", "season_type", "week", "posteam", "qb_dropback"], low_memory=False)
            pb = pb[(pb.season_type == "REG") & (pb.qb_dropback == 1) & pb.posteam.notna()]
            pb["tm"] = pb.posteam.map(lambda t: B.tm(str(t)))
            m = pb.merge(pa, left_on=["game_id", "play_id"], right_on=["nflverse_game_id", "play_id"], how="inner")
            want = {k for k in movers if not k.startswith("pfr:")}
            tdb = m.groupby(["tm", "week"]).size().to_dict()
            cnt = defaultdict(int)
            for r in m.itertuples(index=False):
                op = r.offense_players
                if not isinstance(op, str): continue
                for g_ in op.split(";"):
                    if g_ in want: cnt[(g_, int(r.week))] += 1
            for (g_, w), c in cnt.items():
                t = movers[g_].get(w, (None,))[0]
                if t is None: continue
                d = tdb.get((t, w), 0)
                if d: rshare[(g_, w)] = 100.0 * c / d
        for k, v in movers.items():
            name, pos = nm[k]
            if pos not in POS4: continue
            wks = {}
            for w, (t, sp) in sorted(v.items()):
                q = pw.get((k, w), {}); T = tw.get((t, w), {})
                car_den = T.get("car", 0.0)
                wks[w] = dict(team=t, snap=sp, route=rshare.get((k, w), np.nan), tg=q.get("tg", 0.0), team_tg=T.get("tg", 0.0), car=q.get("car", 0.0), team_car=car_den,
                              xfp=q.get("xfp", 0.0), db=q.get("db", 0.0), team_db=T.get("db", 0.0), ay=q.get("ay", 0.0), team_ay=T.get("ay", 0.0))
            seq = [(w, wks[w]["team"]) for w in sorted(wks)]
            ev = [(seq[i][0], seq[i - 1][1], seq[i][1]) for i in range(1, len(seq)) if seq[i][1] != seq[i - 1][1]]
            bd = bd_of.get(k) if not k.startswith("pfr:") else None
            age = ((pd.Timestamp(year=Y, month=9, day=1) - bd).days / 365.25) if (bd is not None and pd.notna(bd)) else np.nan
            out[(Y, k)] = dict(name=name, pos=pos, weeks=wks, events=ev, age=age, rookie=rook_of.get(k))
    pickle.dump(out, open(os.path.join(OUTD, os.environ.get("MST_OUT", "mover_games.pkl")), "wb"))
    print(f"saved {len(out)} mover player-seasons ({time.time()-t0:.0f}s)")

if __name__ == "__main__":
    main()
