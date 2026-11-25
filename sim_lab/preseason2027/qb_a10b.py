#!/usr/bin/env python3
"""A10 round 2 - the diagnosis said passing TD RATE is the biggest miss for QBs (error and order), then attempts. Round 1
candidates all failed. Here, QB rows only: (a) lighter TD-rate shrink (k caps), (b) TD-rate prior scaled by team strength
(de-vigged win totals, market data already in the prototype), (c) a QB level calibration (the model runs ~3-10% low on most
QB groups), each fit walk-forward on earlier seasons; choices on dev 2015-22. Log: qb_a10b.log."""
import os, sys, time
import numpy as np
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM, games_model as GM, pergame_model as G, fixes_a9 as FX, qb_a10 as Q

LOG = None


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def main():
    global LOG
    LOG = open(os.path.join(HERE, "qb_a10b.log"), "w", encoding="utf-8"); Q.LOG = LOG
    t0 = time.time()
    D = PM.build(); AV, wk1 = GM.availability(); D = GM.add_features(D, AV, wk1)
    S = G.stat_seasons(); D = G.add_history(D, S); D = G.add_context(D, S); D = FX.add_fix1_features(D)
    R0 = PM.walk_forward(D)
    for c in ("ridge_stats", "adp_curve_f", "naive_f"): D[c] = R0[c].values
    O = GM.walk(D, [f if f != "gs1" else "gs1_shrunk" for f in GM.GF], "g"); D = pd.concat([D, O], axis=1); D["g_use"] = 0.75 * D.g_ridge + 0.25 * D.g_dist
    s7, cp, _ = G.walk(D, Q.LEAN, "S7", use_role_prior=True)
    D["s7"] = s7.values; D["pg"] = 0.75 * D.s7 + 0.25 * D.ridge_stats
    for k in cp: D[k] = cp[k].values
    W = pd.read_parquet(os.path.join(PM.DATA, "player_weeks.parquet"), columns=["season", "week", "pid", "att"])
    W = W[W.week < W.season.map(PM.final_week)]; st = W[W.att >= 15].groupby(["season", "pid"]).size()
    D["starts"] = [st.get((y, p), 0) for y, p in zip(D.season, D.pid)]
    QB = (D.pos == "QB") & D.season.isin(PM.TEST_YEARS); pool = QB & ((D.is_qb1 == 1) | (D.starts >= 4))
    dev = pool & D.season.isin(Q.DEV); hold = pool & D.season.isin(Q.HOLD)
    def assemble(ptd):
        return D.S7_v_att * (0.04 * D.S7_e_pyd_a + 4 * ptd - D.S7_e_int_a) + D.S7_v_car * (0.1 * D.S7_e_ryd_c + 6 * D.S7_e_rtd_c)
    D["s7_check"] = assemble(D.S7_e_ptd_a)
    P(f"check: rebuilt structural QB number vs S7 max diff {np.nanmax(np.abs((D.s7_check - D.s7)[QB])):.4f} (fumbles/2pt constants explain small gaps)")
    base_const = (D.s7 - D.s7_check)[QB].median()
    # walk-forward prior TD rate + team-strength slope
    prior = pd.Series(np.nan, index=D.index); slope = {}
    for Y in PM.TEST_YEARS:
        tr = (D.pos == "QB") & (D.season < Y) & (D.y_att >= 150)
        pm = D.y_ptd[tr].sum() / D.y_att[tr].sum()
        prior[(D.season == Y) & (D.pos == "QB")] = pm
        x = (D.exp_w[tr] - 8.5).fillna(0).values; y = (D.y_ptd_a[tr] / pm - 1).values; w = D.y_att[tr].values
        slope[Y] = float(np.sum(w * x * y) / np.sum(w * x * x))
    D["prior_ptd"] = prior; D["b_team"] = D.season.map(slope)
    P("team-strength slope on TD rate (relative change per expected win, fit on earlier seasons): " + " ".join(f"{y}:{b:+.3f}" for y, b in slope.items()))
    out = {}
    for k in (1280, 640, 320, 160):
        ptd = (D.num_ptd_a + k * D.prior_ptd) / (D.den_ptd_a + k)
        D[f"pg_k{k}"] = np.where(D.pos == "QB", 0.75 * (assemble(ptd) + base_const) + 0.25 * D.ridge_stats, D.pg)
        prior_t = D.prior_ptd * (1 + D.b_team * (D.exp_w - 8.5).fillna(0))
        ptd_t = (D.num_ptd_a + k * prior_t) / (D.den_ptd_a + k)
        D[f"pg_k{k}_team"] = np.where(D.pos == "QB", 0.75 * (assemble(ptd_t) + base_const) + 0.25 * D.ridge_stats, D.pg)
    # QB level calibration (walk-forward ratio of act to pred on earlier seasons' pool rows)
    lev = pd.Series(1.0, index=D.index)
    for Y in PM.TEST_YEARS:
        tr = pool & (D.season < Y) & (D.season >= 2015) & (D.act_games >= 4)
        if tr.sum() >= 60: lev[(D.season == Y) & (D.pos == "QB")] = float(np.clip((D.act_ppg[tr] * D.act_games[tr]).sum() / (D.pg[tr] * D.act_games[tr]).sum(), .9, 1.12))
    D["pg_level"] = np.where(D.pos == "QB", D.pg * lev, D.pg)
    P("QB level factor (walk-forward): " + " ".join(f"{y}:{lev[(D.season == y) & (D.pos == 'QB')].iloc[0]:.3f}" for y in PM.TEST_YEARS))
    cols = ["pg", "pg_k640", "pg_k320", "pg_k160", "pg_k1280_team", "pg_k640_team", "pg_k320_team", "pg_level"]
    res = {}
    for c in cols:
        P(f"  {c}:"); res[c] = (Q.grade(D, c, dev, "   dev"), Q.grade(D, c, hold, "   holdout"))
    base = res["pg"]
    keep = [c for c in cols[1:] if res[c][0][1] > base[0][1] + 0.005 and res[c][0][0] <= base[0][0] + 0.005]
    keep_mae = [c for c in cols[1:] if res[c][0][0] < base[0][0] - 0.02 and res[c][0][1] >= base[0][1] - 0.002]
    P(f"\nkept on dev for ORDER (rho +.005, MAE not worse): {keep or 'none'} | kept for ERROR only (MAE -.02, rho not worse): {keep_mae or 'none'}")
    # ADP comparison on QBs with ADP for the kept ones
    for c in ["pg"] + keep + keep_mae:
        Q.grade(D, c, pool & D.adp.notna(), f"{c} on QBs with ADP (all years)")
    Q.grade(D, "adp_curve_f", pool & D.adp.notna(), "ADP curve on QBs with ADP (all years)")
    D[["season", "pid", "pos"] + cols].to_parquet(os.path.join(HERE, "data", "qb_a10b_rows.parquet"), index=False)
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
