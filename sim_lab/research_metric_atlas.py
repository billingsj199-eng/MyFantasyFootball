#!/usr/bin/env python3
"""
METRIC ATLAS (Jack 2026-09-30: "test every underlying metric we can think of and look for general correlation").

Every per-player metric we can build from what is on disk, as it stood BEFORE each game (season to date through
the previous week, plus the prior season's value), correlated with:
  next    the player's points in that game
  ros     his points per game over the rest of that season
  res     what the live projection missed that game (actual - rebuilt live stack)      <- the only one that can
  resRos  what it missed over the rest of the season                                       improve the projection
Spearman by position, 2019-25, rows with a live projection >= 5 half-PPR and 2+ games played.

Metric families
  play-by-play (nflverse): receiving volume / depth / quality / efficiency, rushing volume / efficiency / situation,
  QB volume / accuracy (CPOE) / EPA / sacks / scrambles / depth, team pace and pass rate, EPA per play
  PFF weekly (receiving + rushing summaries): grades, YPRR, route rate, slot rate, drops, contested, YCO, elusive
  ctx_features: snaps, shares, trends, xFP, FPOE, Vegas, OL, age / experience / draft, coach
Log metric_atlas.log; table -> data/metric_atlas.csv.
"""
import os, sys, glob, warnings
import numpy as np, pandas as pd
from collections import defaultdict
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
CACHE = r"E:\MyFantasyFootball\pbp_cache"
warnings.filterwarnings("ignore")
YEARS = range(2019, 2026)

def pbp_metrics():
    """per (year, gsis id, week) season-to-date metrics ENTERING that week (cumulative through week-1) + team context"""
    out = []
    cols = ["season_type", "week", "posteam", "defteam", "play_type", "pass_attempt", "rush_attempt", "complete_pass", "interception", "sack", "qb_scramble",
            "qb_dropback", "shotgun", "no_huddle", "air_yards", "yards_after_catch", "yards_gained", "epa", "qb_epa", "cpoe", "cp", "xyac_mean_yardage", "success",
            "touchdown", "pass_touchdown", "rush_touchdown", "yardline_100", "down", "ydstogo", "score_differential", "wp", "qb_hit", "tackled_for_loss", "first_down",
            "receiver_player_id", "rusher_player_id", "passer_player_id", "fumble_lost"]
    for Y in YEARS:
        d = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), low_memory=False, usecols=cols)
        d = d[(d.season_type == "REG") & d.play_type.isin(["pass", "run"])].copy()
        d["week"] = d.week.astype(int)
        neutral = (d.wp.between(0.2, 0.8)) & (d.score_differential.abs() <= 14)
        # ---- team per week
        tp = d.groupby(["posteam", "week"]).agg(plays=("play_type", "size"), passes=("pass_attempt", "sum"), rushes=("rush_attempt", "sum"),
                                                 epa=("epa", "sum"), nhud=("no_huddle", "sum"))
        tn = d[neutral].groupby(["posteam", "week"]).agg(npass=("pass_attempt", "sum"), nplays=("play_type", "size"))
        tp = tp.join(tn); tp["team_pass_rate"] = tp.passes / tp.plays; tp["team_neutral_pass_rate"] = tp.npass / tp.nplays
        tp["team_epa_play"] = tp.epa / tp.plays; tp["team_nohuddle_rate"] = tp.nhud / tp.plays
        tp = tp.reset_index()
        # ---- receivers
        r = d[(d.pass_attempt == 1) & d.receiver_player_id.notna() & (d.sack != 1)].copy()
        r["deep"] = (r.air_yards >= 20).astype(float); r["rz"] = (r.yardline_100 <= 20).astype(float); r["ez"] = (r.air_yards >= r.yardline_100).astype(float)
        r["td"] = r.pass_touchdown.fillna(0); r["rec"] = r.complete_pass.fillna(0); r["yac"] = r.yards_after_catch.fillna(0) * r.rec
        r["yds"] = r.yards_gained.fillna(0) * r.rec; r["ay"] = r.air_yards.fillna(0); r["first"] = r.first_down.fillna(0)
        r["cpv"] = r.cp.fillna(r.cp.mean()); r["xyac"] = r.xyac_mean_yardage.fillna(0)
        g = r.groupby(["receiver_player_id", "week"]).agg(tgt=("rec", "size"), rec=("rec", "sum"), yds=("yds", "sum"), ay=("ay", "sum"), yac=("yac", "sum"), td=("td", "sum"),
                                                          epa=("epa", "sum"), succ=("success", "sum"), deep=("deep", "sum"), rz=("rz", "sum"), ez=("ez", "sum"), cpv=("cpv", "sum"),
                                                          xyac=("xyac", "sum"), first=("first", "sum"), team=("posteam", "first")).reset_index()
        team_t = r.groupby(["posteam", "week"]).agg(team_tgt=("rec", "size"), team_ay=("ay", "sum"), team_rz_tgt=("rz", "sum")).reset_index()
        g = g.merge(team_t, left_on=["team", "week"], right_on=["posteam", "week"], how="left")
        out.append(("rec", Y, g))
        # ---- rushers
        u = d[(d.rush_attempt == 1) & d.rusher_player_id.notna() & (d.qb_scramble != 1)].copy()
        u["yds"] = u.yards_gained.fillna(0); u["td"] = u.rush_touchdown.fillna(0); u["stuff"] = (u.yds <= 0).astype(float); u["expl"] = (u.yds >= 10).astype(float)
        u["gl"] = (u.yardline_100 <= 5).astype(float); u["rz"] = (u.yardline_100 <= 20).astype(float); u["first"] = u.first_down.fillna(0); u["tfl"] = u.tackled_for_loss.fillna(0)
        u["short"] = ((u.down >= 3) & (u.ydstogo <= 2)).astype(float)
        g2 = u.groupby(["rusher_player_id", "week"]).agg(car=("yds", "size"), ryds=("yds", "sum"), rtd=("td", "sum"), repa=("epa", "sum"), rsucc=("success", "sum"), stuff=("stuff", "sum"),
                                                          expl=("expl", "sum"), gl=("gl", "sum"), rrz=("rz", "sum"), rfirst=("first", "sum"), tfl=("tfl", "sum"), short=("short", "sum"), team=("posteam", "first")).reset_index()
        team_c = u.groupby(["posteam", "week"]).agg(team_car=("yds", "size"), team_gl=("gl", "sum")).reset_index()
        g2 = g2.merge(team_c, left_on=["team", "week"], right_on=["posteam", "week"], how="left")
        out.append(("rush", Y, g2))
        # ---- passers
        q = d[(d.qb_dropback == 1) & d.passer_player_id.notna()].copy()
        q["att"] = (q.pass_attempt.fillna(0) * (1 - q.sack.fillna(0))); q["cmp"] = q.complete_pass.fillna(0); q["pyds"] = q.yards_gained.fillna(0) * (q.pass_attempt.fillna(0))
        q["ptd"] = q.pass_touchdown.fillna(0); q["int"] = q.interception.fillna(0); q["sk"] = q.sack.fillna(0); q["scr"] = q.qb_scramble.fillna(0)
        q["ay"] = q.air_yards.fillna(0); q["deep"] = (q.air_yards >= 20).astype(float); q["hit"] = q.qb_hit.fillna(0); q["cpoe_v"] = q.cpoe; q["shot"] = q.shotgun.fillna(0)
        g3 = q.groupby(["passer_player_id", "week"]).agg(db=("att", "size"), att=("att", "sum"), cmp=("cmp", "sum"), pyds=("pyds", "sum"), ptd=("ptd", "sum"), pint=("int", "sum"),
                                                          sk=("sk", "sum"), scr=("scr", "sum"), qay=("ay", "sum"), qdeep=("deep", "sum"), qepa=("qb_epa", "sum"), qsucc=("success", "sum"),
                                                          cpoe=("cpoe_v", "mean"), hit=("hit", "sum"), shot=("shot", "sum"), team=("posteam", "first")).reset_index()
        out.append(("pass", Y, g3))
        out.append(("team", Y, tp))
        print(f"  pbp {Y} done", flush=True)
    return out

def cumulate(g, idcol, sums, ratios):
    """season-to-date sums entering each week (exclusive) per player; ratios = {name: (num, den)}"""
    g = g.sort_values([idcol, "week"]).copy()
    for c in sums: g[c + "_cum"] = g.groupby(idcol)[c].cumsum() - g[c]     # through the previous game
    g["g_cum"] = g.groupby(idcol).cumcount()
    out = g[[idcol, "week", "g_cum"] + [c + "_cum" for c in sums]].copy()
    for name, (num, den) in ratios.items():
        out[name] = np.where(out[den + "_cum"] > 0, out[num + "_cum"] / out[den + "_cum"], np.nan)
    return out

def pff_weekly(kind, cols):
    """season-to-date (through previous week) game-weighted means of PFF weekly metrics, keyed by pff id"""
    rows = []
    for Y in YEARS:
        for w in range(1, 19):
            f = os.path.join(CACHE, "pff", "weekly", f"pff_{kind}_summary_{Y}_w{w}.csv")
            if not os.path.exists(f): continue
            d = pd.read_csv(f, usecols=["player_id", "position"] + cols); d["year"] = Y; d["week"] = w; rows.append(d)
    d = pd.concat(rows, ignore_index=True).sort_values(["year", "player_id", "week"])
    out = d[["year", "player_id", "week"]].copy()
    for c in cols:
        cs = d.groupby(["year", "player_id"])[c].cumsum() - d[c]; n = d.groupby(["year", "player_id"]).cumcount()
        out["pff_" + c] = np.where(n > 0, cs / n.replace(0, np.nan), np.nan)
    return out

def main():
    lf = open(os.path.join(HERE, "metric_atlas.log"), "w", encoding="utf-8")
    def P(s=""):
        print(s); lf.write(s + "\n")
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet")).set_index(["year", "pid", "wk"])
    C = C.join(L[["td_luck_adj", "pool_mult", "rookie_mult", "cond_mult", "weather_mult", "qb_inherit_mult"]], on=["year", "pid", "wk"])
    C["live"] = (C.shipped * C.rookie_mult.fillna(1) * C.pool_mult.fillna(1) * C.cond_mult.fillna(1) * C.weather_mult.fillna(1) * C.qb_inherit_mult.fillna(1) + C.td_luck_adj.fillna(0)).clip(lower=0.2)
    C["res"] = C.act - C.live
    C = C.sort_values(["year", "pid", "wk"])
    ros, rres = [], []
    for (y, p), g in C.groupby(["year", "pid"], sort=False):
        a = g.act.values; r = g.res.values; n = len(a)
        ros.append(pd.Series([a[i + 1:].mean() if n - i - 1 >= 3 else np.nan for i in range(n)], index=g.index))
        rres.append(pd.Series([r[i + 1:].mean() if n - i - 1 >= 3 else np.nan for i in range(n)], index=g.index))
    C["ros"] = pd.concat(ros); C["resRos"] = pd.concat(rres)
    P("building play-by-play metrics 2019-25 ...")
    parts = pbp_metrics()
    feats = {}
    for kind, Y, g in parts:
        if kind == "rec":
            cu = cumulate(g, "receiver_player_id", ["tgt", "rec", "yds", "ay", "yac", "td", "epa", "succ", "deep", "rz", "ez", "cpv", "xyac", "first", "team_tgt", "team_ay", "team_rz_tgt"],
                          {"tgt_per_g": ("tgt", "g"), "target_share": ("tgt", "team_tgt"), "air_yards_share": ("ay", "team_ay"), "adot": ("ay", "tgt"), "catch_rate": ("rec", "tgt"),
                           "yac_per_rec": ("yac", "rec"), "yds_per_tgt": ("yds", "tgt"), "epa_per_tgt": ("epa", "tgt"), "succ_rate_tgt": ("succ", "tgt"), "deep_tgt_rate": ("deep", "tgt"),
                           "rz_tgt_share": ("rz", "team_rz_tgt"), "endzone_tgt_per_g": ("ez", "g"), "target_quality_cp": ("cpv", "tgt"), "xyac_per_tgt": ("xyac", "tgt"),
                           "first_down_per_tgt": ("first", "tgt"), "rec_td_per_tgt": ("td", "tgt"), "catch_over_exp": ("rec", "cpv")})
            cu["g_cum"] = cu.g_cum.astype(float)
            cu["catch_over_exp"] = cu.rec_cum - cu.cpv_cum
            cu = cu.rename(columns={"receiver_player_id": "pid"}); cu["year"] = Y
            feats.setdefault("rec", []).append(cu)
        elif kind == "rush":
            cu = cumulate(g, "rusher_player_id", ["car", "ryds", "rtd", "repa", "rsucc", "stuff", "expl", "gl", "rrz", "rfirst", "tfl", "short", "team_car", "team_gl"],
                          {"car_per_g": ("car", "g"), "carry_share": ("car", "team_car"), "ypc": ("ryds", "car"), "epa_per_rush": ("repa", "car"), "succ_rate_rush": ("rsucc", "car"),
                           "stuff_rate": ("stuff", "car"), "explosive_rate": ("expl", "car"), "goalline_share": ("gl", "team_gl"), "rz_car_per_g": ("rrz", "g"),
                           "first_down_per_car": ("rfirst", "car"), "tfl_rate": ("tfl", "car"), "short_yd_car_per_g": ("short", "g"), "rush_td_per_car": ("rtd", "car")})
            cu = cu.rename(columns={"rusher_player_id": "pid"}); cu["year"] = Y
            feats.setdefault("rush", []).append(cu)
        elif kind == "pass":
            cu = cumulate(g, "passer_player_id", ["db", "att", "cmp", "pyds", "ptd", "pint", "sk", "scr", "qay", "qdeep", "qepa", "qsucc", "hit", "shot"],
                          {"dropbacks_per_g": ("db", "g"), "comp_pct": ("cmp", "att"), "yds_per_att": ("pyds", "att"), "td_rate": ("ptd", "att"), "int_rate": ("pint", "att"),
                           "sack_rate": ("sk", "db"), "scramble_rate": ("scr", "db"), "qb_adot": ("qay", "att"), "qb_deep_rate": ("qdeep", "att"), "epa_per_db": ("qepa", "db"),
                           "succ_rate_db": ("qsucc", "db"), "hit_rate": ("hit", "db"), "shotgun_rate": ("shot", "db")})
            gm = g.sort_values(["passer_player_id", "week"]).copy(); gm["cpoe_cum"] = gm.groupby("passer_player_id").cpoe.transform(lambda s: s.expanding().mean().shift())
            cu = cu.merge(gm[["passer_player_id", "week", "cpoe_cum"]], on=["passer_player_id", "week"], how="left").rename(columns={"passer_player_id": "pid", "cpoe_cum": "cpoe"})
            cu["year"] = Y; feats.setdefault("pass", []).append(cu)
        else:
            tm = g.sort_values(["posteam", "week"]).copy()
            for c in ("plays", "team_pass_rate", "team_neutral_pass_rate", "team_epa_play", "team_nohuddle_rate"):
                tm[c + "_std"] = tm.groupby("posteam")[c].transform(lambda s: s.expanding().mean().shift())
            tm["year"] = Y; feats.setdefault("team", []).append(tm.rename(columns={"plays_std": "team_plays_per_g"}))
    R = pd.concat(feats["rec"]); U = pd.concat(feats["rush"]); Q = pd.concat(feats["pass"]); T = pd.concat(feats["team"])
    P("loading PFF weekly summaries ...")
    pl = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "pff_id"]).dropna(); pff2g = dict(zip(pl.pff_id.astype(int), pl.gsis_id))
    PR = pff_weekly("receiving", ["grades_offense", "grades_pass_route", "yprr", "route_rate", "slot_rate", "contested_catch_rate", "drop_rate", "avg_depth_of_target", "yards_after_catch_per_reception", "targeted_qb_rating", "grades_hands_drop", "avoided_tackles", "positive_epa_percent"])
    PU = pff_weekly("rushing", ["grades_run", "grades_offense", "yco_attempt", "elusive_rating", "breakaway_percent", "elu_rush_mtf", "explosive", "grades_pass_block", "yprr"])
    for df in (PR, PU): df["pid"] = df.player_id.map(pff2g); df.rename(columns={"week": "wk"}, inplace=True)
    PU = PU.rename(columns={c: c.replace("pff_", "pffr_") for c in PU.columns if c.startswith("pff_")})
    # ---- assemble
    M = C.copy()
    for name, F in (("rec", R), ("rush", U), ("pass", Q)):
        F = F.rename(columns={"week": "wk"}).drop(columns=[c for c in F.columns if c.endswith("_cum") or c == "g_cum"])
        M = M.merge(F, on=["year", "pid", "wk"], how="left")
    T = T.rename(columns={"week": "wk", "posteam": "team"})[["year", "team", "wk", "team_plays_per_g", "team_pass_rate_std", "team_neutral_pass_rate_std", "team_epa_play_std", "team_nohuddle_rate_std"]]
    M["team_k"] = M.team.replace({"LA": "LAR", "WSH": "WAS", "JAC": "JAX", "OAK": "LV", "SD": "LAC"})
    T["team"] = T.team.replace({"LA": "LAR", "WSH": "WAS", "JAC": "JAX", "OAK": "LV", "SD": "LAC"})
    M = M.merge(T, left_on=["year", "team_k", "wk"], right_on=["year", "team", "wk"], how="left", suffixes=("", "_t"))
    M = M.merge(PR.drop(columns=["player_id"]).dropna(subset=["pid"]).drop_duplicates(["year", "pid", "wk"]), on=["year", "pid", "wk"], how="left").merge(PU.drop(columns=["player_id"]).dropna(subset=["pid"]).drop_duplicates(["year", "pid", "wk"]), on=["year", "pid", "wk"], how="left")
    M.to_parquet(os.path.join(HERE, "data", "metric_atlas_rows.parquet"))   # the assembled table, reused by backtest_ros_quality_volume.py
    base = M[(M.live >= 5) & (M.g >= 2)]
    ctx_feats = ["xfp_pg", "pts_over_xfp", "snap_std", "snap_l1", "snap_trend", "tgt_sh", "car_sh", "rz_tgt_sh", "rz_car_sh", "gl_car_sh", "ay_sh", "wopr", "tgt_trend", "car_trend", "db_sh", "att_pg",
                 "ppg", "ppg_py", "xfp_pg_py", "tgt_sh_py", "car_sh_py", "ppg_over_clay", "age", "exp", "draft_pick", "jm", "implied", "spread", "game_total", "ol_pb_now", "ol_rb_now", "ol_out_n", "opp_man_std", "yprr_man", "yprr_zone", "proe_std", "plays_pg_std"]
    pbp_feats = [c for c in M.columns if c in ("tgt_per_g", "target_share", "air_yards_share", "adot", "catch_rate", "yac_per_rec", "yds_per_tgt", "epa_per_tgt", "succ_rate_tgt", "deep_tgt_rate", "rz_tgt_share", "endzone_tgt_per_g", "target_quality_cp", "xyac_per_tgt", "first_down_per_tgt", "rec_td_per_tgt", "catch_over_exp",
                                                "car_per_g", "carry_share", "ypc", "epa_per_rush", "succ_rate_rush", "stuff_rate", "explosive_rate", "goalline_share", "rz_car_per_g", "first_down_per_car", "tfl_rate", "short_yd_car_per_g", "rush_td_per_car",
                                                "dropbacks_per_g", "comp_pct", "yds_per_att", "td_rate", "int_rate", "sack_rate", "scramble_rate", "qb_adot", "qb_deep_rate", "epa_per_db", "succ_rate_db", "hit_rate", "shotgun_rate", "cpoe",
                                                "team_plays_per_g", "team_pass_rate_std", "team_neutral_pass_rate_std", "team_epa_play_std", "team_nohuddle_rate_std")]
    pff_feats = [c for c in M.columns if c.startswith("pff_") or c.startswith("pffr_")]
    allf = [f for f in ctx_feats + pbp_feats + pff_feats if f in base.columns]
    P(f"\nrows: {len(base)} player-weeks (live >= 5, 2+ games); metrics: {len(allf)}")
    P("Spearman r by position: next-game points / rest-of-season PPG  ||  residual next game / residual rest of season   ('*' = |residual r| >= .05, the ones that could improve a projection)")
    recs = []
    for f in allf:
        for pos in ("QB", "RB", "WR", "TE"):
            d = base[(base.pos == pos) & base[f].notna()]
            if len(d) < 300 or d[f].nunique() < 5: continue
            r1 = spearmanr(d[f], d.act).correlation; d2 = d[d.ros.notna()]; r2 = spearmanr(d2[f], d2.ros).correlation if len(d2) >= 300 else np.nan
            r3 = spearmanr(d[f], d.res).correlation; d4 = d[d.resRos.notna()]; r4 = spearmanr(d4[f], d4.resRos).correlation if len(d4) >= 300 else np.nan
            recs.append({"metric": f, "pos": pos, "n": len(d), "r_next": r1, "r_ros": r2, "r_res": r3, "r_resRos": r4})
    A = pd.DataFrame(recs); A.to_csv(os.path.join(HERE, "data", "metric_atlas.csv"), index=False)
    for pos in ("QB", "RB", "WR", "TE"):
        x = A[A.pos == pos].copy(); x["key"] = x.r_res.abs().fillna(0).combine(x.r_resRos.abs().fillna(0), max)
        x = x.sort_values("key", ascending=False)
        P(f"\n=== {pos} ===")
        P(f"  {'metric':30s} {'n':>5s} {'next':>7s} {'ros':>7s} || {'res':>7s} {'resRos':>7s}")
        for r in x.itertuples():
            flag = " *" if (abs(r.r_res) >= 0.05 or (r.r_resRos == r.r_resRos and abs(r.r_resRos) >= 0.05)) else ""
            P(f"  {r.metric:30s} {r.n:5d} {r.r_next:+7.3f} {r.r_ros:+7.3f} || {r.r_res:+7.3f} {r.r_resRos:+7.3f}{flag}" if r.r_ros == r.r_ros else f"  {r.metric:30s} {r.n:5d} {r.r_next:+7.3f}     -   || {r.r_res:+7.3f}     -  {flag}")
    P("\nstrongest RAW predictors of next-game points (all metrics, |r_next| top 12 per position):")
    for pos in ("QB", "RB", "WR", "TE"):
        x = A[A.pos == pos].reindex(A[A.pos == pos].r_next.abs().sort_values(ascending=False).index).head(12)
        P(f"  {pos}: " + ", ".join(f"{r.metric} {r.r_next:+.2f}" for r in x.itertuples()))
    lf.close()

if __name__ == "__main__":
    main()
