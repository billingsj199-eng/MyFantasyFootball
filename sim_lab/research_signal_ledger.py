#!/usr/bin/env python3
"""
SIGNAL LEDGER (Jack 2026-09-30: "look at all the analytics we have, even xFP and FP per play, to try to find some
correlation for predicting the future"). One table: every pre-kickoff analytic we hold for a player, correlated with
what the live projection MISSES - next game and rest of season - 2019-25, by position.

  residual (next game)    = actual - live stack (bt_common base x the rebuilt live layers: TD luck, pool, rookie,
                            banged-up, weather, QB inheritance) for that game
  residual (rest of season) = mean of the same over the player's remaining games that season
  r = Spearman correlation of the analytic (known before kickoff) with the residual; |r| >= .05 on 3,000+ rows is
      a real signal, .03 is noise. 'shipped' marks analytics an engine layer already uses.
Analytics from ctx_features.parquet (build_context_features.py) + PFF route rate + derived rates:
  fp/snap, fp/route, FPOE (points over xFP) per game, xFP gap (xFP/g - pts/g), TD share of points.
Log signal_ledger.log.
"""
import os, sys, io
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from backtest_inseason_usage import route_features
from scipy.stats import spearmanr

SHIPPED = {"xfp_pg": "usage evidence (WR/TE) + shadow", "snap_std": "usage evidence (WR/TE); RB snap blend", "snap_trend": "snapMult", "snap_l1": "snapMult",
           "tgt_trend": "-", "car_trend": "-", "rt_std": "usage evidence (WR/TE); TE route trend", "rt_l3": "TE routeMult",
           "pts_over_xfp": "TD half via tdLuckAdj", "td_luck": "tdLuckAdj", "rookie": "rookieLevel", "yr2": "-", "age": "shadow age curve",
           "vac_tgt": "opportunity pool", "vac_car": "opportunity pool", "inherit_tgt": "pool", "inherit_car": "pool", "qb_out": "backup-QB WR dock (shadow)",
           "rep_q": "banged-up", "rep_d": "banged-up", "prac_dnp": "banged-up", "prac_lim": "banged-up", "wind": "weatherMult", "precip": "rejected (marginal)",
           "ol_out_n": "olOutDock", "ol_q_n": "-", "opp_man_std": "rejected", "yprr_man": "rejected", "man_gap_x_opp": "rejected", "new_pc": "rejected (pace)",
           "proe_std": "rejected (pace)", "plays_pg_std": "rejected (pace)", "implied": "vegasMult", "spread": "rejected", "game_total": "shadow QB tilt",
           "ppg_over_clay": "the blend itself", "g": "the blend itself", "jm": "prospect model (rejected as input)", "draft_pick": "shadow rookie prior",
           "team_change": "rejected (mover)", "gl_car_sh": "rejected (context)", "rz_tgt_sh": "rejected (context)", "dome": "rejected"}

def main():
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet"))
    L = L.set_index(["year", "pid", "wk"]); C = C.join(L[["td_luck_adj", "pool_mult", "rookie_mult", "cond_mult", "weather_mult", "qb_inherit_mult"]], on=["year", "pid", "wk"])
    live = C.shipped * C.rookie_mult.fillna(1) * C.pool_mult.fillna(1) * C.cond_mult.fillna(1) * C.weather_mult.fillna(1) * C.qb_inherit_mult.fillna(1) + C.td_luck_adj.fillna(0)
    C["live"] = live.clip(lower=0.2); C["res"] = C.act - C.live
    C["rt_std"], C["rt_l3"] = route_features(C.year.values, C.pid.values, C.wk.values)
    # derived rates (all from games BEFORE this one)
    snaps_g = (C.snap_std / 100.0) * C.plays_pg_std
    C["fp_per_snap"] = np.where(snaps_g > 5, C.ppg / snaps_g, np.nan)
    routes_g = (C.rt_std / 100.0) * C.att_pg.where(C.att_pg > 0, np.nan)
    C["fp_per_route"] = np.where((C.pos != "QB") & (routes_g > 3), C.ppg / routes_g, np.nan)
    C["xfp_gap"] = np.where(C.pos != "QB", C.xfp_pg - C.ppg, np.nan)
    C["fpoe_pg"] = np.where(C.pos != "QB", C.pts_over_xfp, np.nan)
    C["td_luck"] = C.td_luck_adj
    # rest-of-season residual: mean residual over the player's LATER games that season
    C = C.sort_values(["year", "pid", "wk"])
    ros = []
    for (y, p), g in C.groupby(["year", "pid"], sort=False):
        r = g.res.values; n = len(r)
        tail = [r[i + 1:].mean() if i + 1 < n and n - i - 1 >= 3 else np.nan for i in range(n)]
        ros.append(pd.Series(tail, index=g.index))
    C["res_ros"] = pd.concat(ros)
    feats = ["xfp_pg", "xfp_gap", "fpoe_pg", "fp_per_snap", "fp_per_route", "td_luck", "tgt_sh", "car_sh", "rz_tgt_sh", "rz_car_sh", "gl_car_sh", "ay_sh", "wopr",
             "tgt_sh_l3", "car_sh_l3", "tgt_trend", "car_trend", "snap_std", "snap_l1", "snap_trend", "rt_std", "rt_l3", "db_sh", "att_pg",
             "tgt_sh_py", "car_sh_py", "xfp_pg_py", "ppg_py", "ppg_over_clay", "g", "age", "exp", "draft_pick", "rookie", "yr2", "jm", "team_change",
             "new_hc", "new_pc", "proe_std", "plays_pg_std", "vac_tgt", "vac_car", "inherit_tgt", "inherit_car", "qb_out", "rep_q", "prac_dnp", "prac_lim",
             "implied", "opp_implied", "spread", "game_total", "dome", "wind", "temp", "precip", "opp_man_std", "yprr_man", "yprr_zone", "man_gap_x_opp",
             "ol_pb_now", "ol_rb_now", "ol_pb_drop", "ol_rb_drop", "ol_out_n", "ol_q_n"]
    feats = [f for f in feats if f in C.columns]
    base = C[(C.live >= 5) & (C.g >= 2)]
    print(f"rows: {len(base)} player-weeks 2019-25 (live >= 5 half-PPR, 2+ games played); rest-of-season residual on {int(base.res_ros.notna().sum())}")
    print(f"{'analytic':16s} {'shipped?':32s} " + " ".join(f"{p:>13s}" for p in ("QB", "RB", "WR", "TE")) + "   | next-game r / rest-of-season r per position")
    rows = []
    for f in feats:
        cells = []; best = 0
        for pos in ("QB", "RB", "WR", "TE"):
            d = base[(base.pos == pos) & base[f].notna()]
            if len(d) < 300 or d[f].nunique() < 3: cells.append(f"{'-':>13s}"); continue
            r1 = spearmanr(d[f], d.res).correlation
            dd = d[d.res_ros.notna()]; r2 = spearmanr(dd[f], dd.res_ros).correlation if len(dd) >= 300 else np.nan
            cells.append(f"{r1:+.3f}/{r2:+.3f}" if r2 == r2 else f"{r1:+.3f}/  -  ")
            best = max(best, abs(r1), abs(r2) if r2 == r2 else 0)
        rows.append((best, f, cells))
    for best, f, cells in sorted(rows, key=lambda x: -x[0]):
        print(f"{f:16s} {SHIPPED.get(f, '-'):32s} " + " ".join(cells))
    print("\nread: r > 0 = the projection is too LOW when the analytic is high. |r| >= .05 on these samples is real; most of what is real is already a shipped layer.")
    # efficiency persistence: does last season's / early-season FP per snap say anything about the rest of this season?
    print("\nefficiency (FP per snap, FP per route, FPOE) - does it persist? Spearman of the season-to-date value entering game 6 with the value over the rest of the season:")
    for f in ("fp_per_snap", "fp_per_route", "fpoe_pg", "xfp_pg", "ppg"):
        vals = []
        for pos in ("RB", "WR", "TE"):
            d = C[(C.pos == pos) & (C.g == 5) & C[f].notna()]
            fut = []
            for i, r in d.iterrows():
                g = C[(C.year == r.year) & (C.pid == r.pid) & (C.wk > r.wk)]
                fut.append(g[f].iloc[-1] if len(g) >= 4 and f != "ppg" else (g.act.mean() if len(g) >= 4 else np.nan))
            d = d.assign(fut=fut).dropna(subset=["fut"])
            vals.append(f"{pos} {spearmanr(d[f], d.fut).correlation:+.2f} (n={len(d)})" if len(d) >= 100 else f"{pos} -")
        print(f"  {f:14s} " + "   ".join(vals))

if __name__ == "__main__":
    out = sys.stdout   # already re-wrapped utf-8 by the harness import; never wrap the buffer again (the old wrapper closes it on collection)
    lf = open(os.path.join(HERE, "signal_ledger.log"), "w", encoding="utf-8")
    class T:
        def write(s, x): out.write(x); lf.write(x)
        def flush(s): out.flush(); lf.flush()
    sys.stdout = T()
    main()
    lf.close()
