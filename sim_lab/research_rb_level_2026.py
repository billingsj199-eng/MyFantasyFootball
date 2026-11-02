#!/usr/bin/env python3
"""
RB LEVEL 2026 (Jack 2026-11-02, after the W5 / W6 rest-of-season locks graded RBs at actual / projected 1.14 / 1.18).
A) league totals by season 2016-2026 from play-by-play, per team-game: RB half-PPR points (rush + receiving), carries,
   targets, TDs, yards per carry, RB share of all skill-position half-PPR points; weeks 1-5, 6-8 (the lock windows) and the
   W6-8 / W1-5 ramp, so 2026 is compared apples to apples. Log rb_level_2026.log.
"""
import os, sys, warnings
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_common as B
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "rb_level_2026.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "position"])
POSOF = dict(zip(pl.gsis_id, pl.position))
COLS = ["season", "week", "season_type", "posteam", "game_id", "play_id", "rush_attempt", "rusher_player_id", "rushing_yards", "rush_touchdown",
        "pass_attempt", "receiver_player_id", "complete_pass", "receiving_yards", "pass_touchdown", "two_point_attempt"]


def season(Y):
    d = pd.read_csv(os.path.join(B.CACHE, f"play_by_play_{Y}.csv.gz"), usecols=lambda c: c in COLS, low_memory=False)
    d = d[(d.season_type == "REG") & (d.two_point_attempt.fillna(0) != 1)]
    ru = d[(d.rush_attempt == 1) & d.rusher_player_id.notna()].copy()
    ru["pos"] = ru.rusher_player_id.map(POSOF).fillna("?"); ru["pts"] = 0.1 * ru.rushing_yards.fillna(0) + 6 * ru.rush_touchdown.fillna(0)
    ru["car"] = 1; ru["tgt"] = 0; ru["td"] = ru.rush_touchdown.fillna(0); ru["ry"] = ru.rushing_yards.fillna(0)
    re_ = d[(d.pass_attempt == 1) & d.receiver_player_id.notna()].copy()
    re_["pos"] = re_.receiver_player_id.map(POSOF).fillna("?")
    re_["pts"] = 0.5 * re_.complete_pass.fillna(0) + 0.1 * re_.receiving_yards.fillna(0) + 6 * re_.pass_touchdown.fillna(0)
    re_["car"] = 0; re_["tgt"] = 1; re_["td"] = re_.pass_touchdown.fillna(0); re_["ry"] = 0
    x = pd.concat([ru[["week", "game_id", "posteam", "pos", "pts", "car", "tgt", "td", "ry"]], re_[["week", "game_id", "posteam", "pos", "pts", "car", "tgt", "td", "ry"]]])
    return x


def block(x):
    g = x.groupby(["game_id", "posteam"]).ngroups
    r = x[x.pos == "RB"]; sk = x[x.pos.isin(["RB", "WR", "TE", "QB"])]
    return dict(pts=r.pts.sum() / g, car=r.car.sum() / g, tgt=r.tgt.sum() / g, td=r.td.sum() / g, ypc=r.ry.sum() / max(1, r.car.sum()), share=r.pts.sum() / sk.pts.sum(), skill=sk.pts.sum() / g, games=g)


def main():
    P("RB per team-game (half-PPR, rush + receiving; QB rushing counted in skill total) | W1-5 vs W6-8")
    P("season | W1-5: RB pts  car   tgt   TD    ypc  RBshare skill/g | W6-8: RB pts  car   tgt   TD    ypc  RBshare skill/g | ramp RB pts  skill  share")
    R = {}
    for Y in range(2016, 2027):
        try: x = season(Y)
        except Exception as e: P(f"{Y}: {e}"); continue
        a = block(x[x.week <= 5]); b = block(x[(x.week >= 6) & (x.week <= 8)]); R[Y] = (a, b)
        f = lambda q: f"{q['pts']:6.2f} {q['car']:5.1f} {q['tgt']:5.2f} {q['td']:5.2f} {q['ypc']:5.2f} {q['share']:.3f} {q['skill']:6.2f}"
        P(f"{Y}   | {f(a)}       | {f(b)}       | {b['pts']/a['pts']:.3f}   {b['skill']/a['skill']:.3f}  {b['share']/a['share']:.3f}")
    hist = [Y for Y in R if Y < 2026]
    for k in ("pts", "share", "td", "ypc", "car"):
        h1 = np.array([R[Y][0][k] for Y in hist]); h2 = np.array([R[Y][1][k] for Y in hist]); rp = h2 / h1
        P(f"  {k:5s} 2016-25 W1-5 mean {h1.mean():.3f} sd {h1.std():.3f} | W6-8 mean {h2.mean():.3f} sd {h2.std():.3f} | ramp mean {rp.mean():.3f} sd {rp.std():.3f}"
          + (f" || 2026 W1-5 {R[2026][0][k]:.3f} (z {(R[2026][0][k]-h1.mean())/max(h1.std(),1e-9):+.1f}) W6-8 {R[2026][1][k]:.3f} (z {(R[2026][1][k]-h2.mean())/max(h2.std(),1e-9):+.1f}) ramp {R[2026][1][k]/R[2026][0][k]:.3f} (z {(R[2026][1][k]/R[2026][0][k]-rp.mean())/max(rp.std(),1e-9):+.1f})" if 2026 in R else ""))
    LOG.close()


if __name__ == "__main__":
    main()
