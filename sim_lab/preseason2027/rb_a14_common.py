#!/usr/bin/env python3
"""
A14 shared setup (Jack 2026-11-21 "Yes, RB volume"). In-house, no ADP input. Read-only outside preseason2027.
Builds the v5 per-game pieces for every player-season (walk-forward 2015-25) plus team RB totals, goal-line carries
(from the on-disk pbp, inside the 10 and inside the 5), stickiness inputs, and caches them to data/rb_a14_D.parquet.
"""
import os, sys, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM, games_model as GM, pergame_model as G, fixes_a9 as FX, qb_a10 as Q, qb_a11 as JS

CACHE_D = os.path.join(HERE, "data", "rb_a14_D.parquet")
GL_FILE = os.path.join(HERE, "data", "rb_a14_gl.parquet")


def gl_table():
    if os.path.exists(GL_FILE): return pd.read_parquet(GL_FILE)
    rows = []
    for Y in range(2012, 2026):
        d = pd.read_csv(os.path.join(PM.CACHE, f"play_by_play_{Y}.csv.gz"), low_memory=False,
                        usecols=["season_type", "week", "posteam", "yardline_100", "rush_attempt", "two_point_attempt", "rusher_player_id", "rush_touchdown"])
        d = d[(d.season_type == "REG") & (d.rush_attempt == 1) & (d.two_point_attempt != 1) & d.rusher_player_id.notna()]
        d = d[d.week < PM.final_week(Y)]
        d["gl10"] = (d.yardline_100 <= 10).astype(int); d["gl5"] = (d.yardline_100 <= 5).astype(int)
        d["td10"] = d.gl10 * d.rush_touchdown.fillna(0); d["tdout"] = (1 - d.gl10) * d.rush_touchdown.fillna(0)
        g = d.groupby(["rusher_player_id", "posteam"]).agg(gl10=("gl10", "sum"), gl5=("gl5", "sum"), td10=("td10", "sum"), tdout=("tdout", "sum"), car=("gl10", "size")).reset_index()
        g["season"] = Y; rows.append(g)
    T = pd.concat(rows, ignore_index=True).rename(columns={"rusher_player_id": "pid", "posteam": "team"})
    T["team"] = T.team.map(PM.tm)
    T.to_parquet(GL_FILE, index=False)
    return T


def gl_extra(Y, last_wk):
    """goal-line carries for a partial season (weeks <= last_wk) from the on-disk pbp, same columns as gl_table()."""
    d = pd.read_csv(os.path.join(PM.CACHE, f"play_by_play_{Y}.csv.gz"), low_memory=False,
                    usecols=["season_type", "week", "posteam", "yardline_100", "rush_attempt", "two_point_attempt", "rusher_player_id", "rush_touchdown"])
    d = d[(d.season_type == "REG") & (d.rush_attempt == 1) & (d.two_point_attempt != 1) & d.rusher_player_id.notna() & (d.week <= last_wk)]
    d["gl10"] = (d.yardline_100 <= 10).astype(int); d["gl5"] = (d.yardline_100 <= 5).astype(int)
    d["td10"] = d.gl10 * d.rush_touchdown.fillna(0); d["tdout"] = (1 - d.gl10) * d.rush_touchdown.fillna(0)
    g = d.groupby(["rusher_player_id", "posteam"]).agg(gl10=("gl10", "sum"), gl5=("gl5", "sum"), td10=("td10", "sum"), tdout=("tdout", "sum"), car=("gl10", "size")).reset_index()
    g["season"] = Y; g = g.rename(columns={"rusher_player_id": "pid", "posteam": "team"}); g["team"] = g.team.map(PM.tm)
    return g


def team_tables(GLx=None):
    """team-season RB totals per team game, RB target share, QB rush share, pass rate and pace, play-caller change."""
    W = pd.read_parquet(os.path.join(PM.DATA, "player_weeks.parquet"), columns=["season", "week", "team", "pid", "car", "tgt", "position"])
    W = W[W.week < W.season.map(PM.final_week)]
    tg = W.groupby(["season", "team"]).week.nunique().rename("tgames")
    tot = W.groupby(["season", "team"]).agg(car_all=("car", "sum"), tgt_all=("tgt", "sum"))
    rb = W[W.position == "RB"].groupby(["season", "team"]).agg(rb_car=("car", "sum"), rb_tgt=("tgt", "sum"))
    qb = W[W.position == "QB"].groupby(["season", "team"]).agg(qb_car=("car", "sum"))
    T = pd.concat([tg, tot, rb, qb], axis=1).fillna(0).reset_index()
    GL = gl_table() if GLx is None else GLx; posof = W.drop_duplicates("pid").set_index("pid").position
    GL["pos"] = GL.pid.map(posof)
    glt = GL.groupby(["season", "team"]).agg(gl10_all=("gl10", "sum")); glr = GL[GL.pos == "RB"].groupby(["season", "team"]).agg(rb_gl10=("gl10", "sum"))
    glq = GL[GL.pos == "QB"].groupby(["season", "team"]).agg(qb_gl10=("gl10", "sum"))
    T = T.merge(pd.concat([glt, glr, glq], axis=1).fillna(0).reset_index(), on=["season", "team"], how="left")
    TG = pd.read_parquet(os.path.join(PM.DATA, "team_games.parquet"), columns=["season", "week", "team", "plays", "passatt", "rushatt", "dropbacks"])
    TG = TG[TG.week < TG.season.map(PM.final_week)]
    pr = TG.groupby(["season", "team"]).agg(plays=("plays", "sum"), db=("dropbacks", "sum"), ra=("rushatt", "sum")).reset_index()
    T = T.merge(pr, on=["season", "team"], how="left")
    T["T_car"] = T.rb_car / T.tgames; T["T_tgt"] = T.rb_tgt / T.tgames; T["rb_tsh"] = T.rb_tgt / T.tgt_all.replace(0, np.nan)
    T["qb_rsh"] = T.qb_car / T.car_all.replace(0, np.nan); T["pass_rate"] = T.db / (T.db + T.ra).replace(0, np.nan); T["pace"] = T.plays / T.tgames
    T["T_gl"] = T.rb_gl10 / T.tgames; T["qb_glsh"] = T.qb_gl10 / T.gl10_all.replace(0, np.nan)
    c = json.load(open(os.path.join(PM.CACHE, "coaches.json"), encoding="utf-8"))
    oc = {(int(y), PM.tm(t)): (v.get("oc") or v.get("hc")) for y, d in c.items() for t, v in d.items()}
    T["new_oc"] = [np.nan if (y - 1, t) not in oc or (y, t) not in oc else float(oc[(y, t)] != oc[(y - 1, t)]) for y, t in zip(T.season, T.team)]
    return T


def build():
    if os.path.exists(CACHE_D): return pd.read_parquet(CACHE_D)
    D = PM.build(); AV, wk1 = GM.availability(); D = GM.add_features(D, AV, wk1)
    S = G.stat_seasons(); D = G.add_history(D, S); D = G.add_context(D, S); D = FX.add_fix1_features(D)
    R0 = PM.walk_forward(D)
    for c in ("ridge_stats", "adp_curve_f", "naive_f", "adp_total"): D[c] = R0[c].values
    O = GM.walk(D, [f if f != "gs1" else "gs1_shrunk" for f in GM.GF], "g"); D = pd.concat([D, O], axis=1); D["g_use"] = 0.75 * D.g_ridge + 0.25 * D.g_dist
    s7, comp, _ = G.walk(D, Q.LEAN, "S7", use_role_prior=True)
    D["s7"] = s7.values
    for k, v in comp.items(): D[k] = v.values
    D["pg"] = 0.75 * D.s7 + 0.25 * D.ridge_stats
    D = rb_features(D, S)
    keep = [c for c in D.columns if D[c].dtype != object or c in ("name", "pos", "team", "pid", "key")]
    D = D[keep].copy()
    D.to_parquet(CACHE_D, index=False)
    return D


def rb_features(D, S, GLx=None, max_year=2025):
    """A14 RB backfield inputs: goal-line history, team RB tables (Y, Y-1, Y-2), last-season shares, RB investment, rd 1-3 back added."""
    GLall = gl_table() if GLx is None else GLx
    GL = GLall.groupby(["season", "pid"]).agg(gl10=("gl10", "sum"), gl5=("gl5", "sum"), td10=("td10", "sum"), tdout=("tdout", "sum")).reset_index()
    gl = GL.set_index(["season", "pid"])
    for k, lab in ((0, "y"), (1, "h1")):
        sub = gl.reindex(list(zip(D.season - k, D.pid)))
        for c in ("gl10", "gl5", "td10", "tdout"): D[f"{lab}_{c}"] = sub[c].fillna(0).values
    # team tables for Y and Y-1 (player's week-1 team)
    T = team_tables(GLall).set_index(["season", "team"])
    for k, lab in ((0, "t0"), (1, "t1"), (2, "t2")):
        sub = T.reindex(list(zip(D.season - k, D.team)))
        for c in ("T_car", "T_tgt", "T_gl", "rb_tsh", "qb_rsh", "qb_glsh", "pass_rate", "pace", "tgames", "new_oc", "rb_car", "rb_tgt", "rb_gl10"):
            D[f"{lab}_{c}"] = sub[c].values
    # player's last-season shares of his Y-1 team's RB work (per team game), and of RB targets / goal-line carries
    S1 = S.set_index(["season", "pid"]); prev = S1.reindex(list(zip(D.season - 1, D.pid)))
    Tp = T.reindex(list(zip(D.season - 1, prev.team.values)))
    D["q_car1"] = prev.car.values / Tp.rb_car.replace(0, np.nan).values
    D["q_tgt1"] = prev.tgt.values / Tp.rb_tgt.replace(0, np.nan).values
    D["q_gl1"] = D.h1_gl10.values / Tp.rb_gl10.replace(0, np.nan).values
    # this season's actual shares of his week-1 team's RB work
    D["q_car"] = D.y_car / D.t0_rb_car.replace(0, np.nan); D["q_tgt"] = D.y_tgt / D.t0_rb_tgt.replace(0, np.nan); D["q_gl"] = D.y_gl10 / D.t0_rb_gl10.replace(0, np.nan)
    # RB investment (A13 form, RB scale): max(min(1, cap share / .06), draft score x fade)
    K, _ = JS.contracts_asof(range(2013, max_year + 1))
    D["money"] = [K.get((y, p), {}).get("apy_cap", np.nan) for y, p in zip(D.season, D.pid)]
    D["dscore"] = np.where(D.undrafted == 1, 0.0, (1 - D.lpick / np.log(262)).clip(0, 1))
    D["inv"] = np.maximum((D.money / .06).clip(0, 1).fillna(0), D.dscore * (1 - D.exp / 5).clip(lower=0))
    dp = pd.read_parquet(os.path.join(PM.CACHE, "draft_picks.parquet"), columns=["season", "pick", "team", "position", "gsis_id"]); dp["team"] = dp.team.map(PM.tm)
    r13 = {}
    for r in dp[(dp.position == "RB") & (dp.pick <= 100)].itertuples(index=False): r13.setdefault((r.season, r.team), set()).add(r.gsis_id)
    D["team_rb_r13"] = [float(len(r13.get((y, t), set()) - {p}) > 0) for y, t, p in zip(D.season, D.team, D.pid)]
    return D


if __name__ == "__main__":
    D = build(); print(D.shape)
