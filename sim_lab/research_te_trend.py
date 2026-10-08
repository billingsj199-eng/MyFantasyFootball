#!/usr/bin/env python3
"""
TE TREND (Jack 2026-10-08: "maybe it has to do with more recent TE production and lower WR3 production with increased 12
personnel"). By season 2016-2026: share of targets / receiving half-PPR points to TEs, WR3 (3rd WR by targets in the game) per
team-game, and 12+ personnel rate (2+ TE, 1 RB; nflverse participation, 2016-25 only). Weeks 1-4 for every season (apples to
apples with 2026) and full regular season. Log te_trend.log.
"""
import os, sys, warnings
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_common as B
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "te_trend.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "position"])
POSOF = dict(zip(pl.gsis_id, pl.position))
COLS = ["season", "week", "season_type", "posteam", "game_id", "play_id", "pass_attempt", "receiver_player_id", "complete_pass", "receiving_yards", "pass_touchdown", "sack"]


def season_rows(Y):
    f = os.path.join(B.CACHE, f"play_by_play_{Y}.csv.gz")
    d = pd.read_csv(f, usecols=lambda c: c in COLS, low_memory=False)
    d = d[(d.season_type == "REG") & (d.pass_attempt == 1) & d.receiver_player_id.notna()]
    d["pos"] = d.receiver_player_id.map(POSOF).fillna("?")
    d["pts"] = 0.5 * d.complete_pass.fillna(0) + 0.1 * d.receiving_yards.fillna(0) + 6 * d.pass_touchdown.fillna(0)
    return d


def personnel(Y, wk_max):
    f = os.path.join(B.CACHE, f"pbp_participation_{Y}.parquet")
    if not os.path.exists(f): return None
    p = pd.read_parquet(f, columns=["nflverse_game_id", "offense_personnel"])
    wk = p.nflverse_game_id.str.split("_").str[1].astype(int); p = p[wk <= wk_max]
    s = p.offense_personnel.fillna("")
    te = s.str.extract(r"(\d)\s*TE")[0].astype(float); rb = s.str.extract(r"(\d)\s*RB")[0].astype(float)
    ok = te.notna()
    return float(((te >= 2) & ok).sum() / max(1, ok.sum())), float(((te >= 2) & (rb == 1) & ok).sum() / max(1, ok.sum()))


def main():
    P("season | weeks | TE share of targets | TE share of rec pts | TE pts/team-game | WR3 tgt/g | WR3 pts/g | WR1+2 pts/g | 2+TE personnel | 12 personnel")
    for Y in range(2016, 2027):
        try: d = season_rows(Y)
        except Exception as e: P(f"{Y}: {e}"); continue
        for lab, wmax in (("W1-4", 4), ("full", 18)):
            if Y == 2026 and lab == "full": continue
            x = d[d.week <= wmax]; tg = x.groupby("pos").size(); pt = x.groupby("pos").pts.sum()
            games = x.groupby(["game_id", "posteam"]).ngroups
            wr = x[x.pos == "WR"].groupby(["game_id", "posteam", "receiver_player_id"]).agg(t=("play_id", "size"), p=("pts", "sum")).reset_index()
            wr["r"] = wr.groupby(["game_id", "posteam"]).t.rank(method="first", ascending=False)
            w3 = wr[wr.r == 3]; w12 = wr[wr.r <= 2]
            per = personnel(Y, wmax)
            P(f"{Y} | {lab} | {tg.get('TE', 0)/tg.sum():.3f} | {pt.get('TE', 0)/pt.sum():.3f} | {pt.get('TE', 0)/games:.2f} | {w3.t.sum()/games:.2f} | {w3.p.sum()/games:.2f} | {w12.p.sum()/games:.2f} | "
              + (f"{per[0]:.3f} | {per[1]:.3f}" if per else "n/a | n/a"))
    P("\nRead: a real TE shift = TE share and 12 personnel rising together, WR3 falling; check whether 2026 W1-4 breaks from prior W1-4s.")
    LOG.close()


if __name__ == "__main__":
    main()
