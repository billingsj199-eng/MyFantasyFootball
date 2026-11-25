#!/usr/bin/env python3
"""A14 step 1 - RB volume diagnosis on the v5 per-game model. Log: rb_a14_diag.log (opened in main())."""
import os, sys, warnings
import numpy as np, pandas as pd
from scipy.stats import spearmanr, pearsonr
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM, qb_a10 as Q, rb_a14_common as C

LOG = None


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def wmae(p, a, w): return float(np.sum(w * np.abs(p - a)) / np.sum(w))


def rho(R, col, ycol="act_ppg"):
    return float(np.nanmean([spearmanr(g[col], g[ycol]).correlation for _, g in R.groupby("season") if len(g) >= 12]))


def prep(D):
    D = D.copy()
    D["rv"] = 0.1 * D.S7_e_ryd_c + 6 * D.S7_e_rtd_c; D["tv"] = 0.5 * D.S7_e_rec_t + 0.1 * D.S7_e_cyd_t + 6 * D.S7_e_ctd_t
    D["vc"] = D.S7_v_car; D["vt"] = D.S7_v_tgt
    rb = (D.pos == "RB") & D.season.isin(PM.TEST_YEARS) & D.vc.notna() & D.team.notna()
    # implied team totals per team game from the listed RBs (projected carries per game played x projected games share)
    D["vc_tg"] = np.where(rb, D.vc * D.g_use, np.nan); D["vt_tg"] = np.where(rb, D.vt * D.g_use, np.nan)
    D["yc_tg"] = np.where(rb, D.y_car.fillna(0) / D.t0_tgames, np.nan); D["yt_tg"] = np.where(rb, D.y_tgt.fillna(0) / D.t0_tgames, np.nan)
    grp = D[rb].groupby(["season", "team"])
    agg = grp.agg(Pc=("vc_tg", "sum"), Pt=("vt_tg", "sum"), Lc=("yc_tg", "sum"), Lt=("yt_tg", "sum"), Tc=("t0_T_car", "first"), Tt=("t0_T_tgt", "first"), n=("pid", "size")).reset_index()
    agg["cov_c"] = agg.Lc / agg.Tc; agg["cov_t"] = agg.Lt / agg.Tt
    D = D.merge(agg[["season", "team", "Pc", "Pt", "Lc", "Lt", "Tc", "Tt", "cov_c", "cov_t"]], on=["season", "team"], how="left")
    return D, rb.values, agg


def main():
    global LOG
    LOG = open(os.path.join(HERE, "rb_a14_diag.log"), "w", encoding="utf-8")
    D = C.build()
    D, rbm, agg = prep(D)
    rbm = pd.Series(rbm, index=D.index)
    ok = rbm & (D.act_games >= 4) & D.pg.notna()
    pool = ok & D.dc.isin([1, 2, 3]); adp150 = ok & (D.adp <= 150)
    covc, covt = agg.cov_c.median(), agg.cov_t.median()
    P("=== A14 step 1. RB volume diagnosis (v5 per-game model, walk-forward 2015-25) ===")
    P(f"  RB rows: pool (week-1 chart 1-3) {int(pool.sum())}, ADP top 150 {int(adp150.sum())}; listed RBs cover a median {covc*100:.0f}% of team RB carries and {covt*100:.0f}% of RB targets")
    # ---------------- oracle swaps
    D["Tc_full"] = D.Pc / covc; D["Tt_full"] = D.Pt / covt
    yc = D.y_carpg.fillna(0); yt = D.y_tgtpg.fillna(0); ygl = D.y_gl10 / D.y_g.replace(0, np.nan)
    tr = (D.pos == "RB") & (D.y_car > 0)
    r10 = D.y_td10[tr].sum() / D.y_gl10[tr].sum(); rout = D.y_tdout[tr].sum() / (D.y_car[tr] - D.y_gl10[tr]).sum()
    sw = {
        "v5 as is": 0,
        "actual carries/g": (yc - D.vc) * D.rv,
        "actual targets/g": (yt - D.vt) * D.tv,
        "actual carries + targets": (yc - D.vc) * D.rv + (yt - D.vt) * D.tv,
        "carries: actual TEAM total only": (D.vc * D.Tc / D.Tc_full - D.vc) * D.rv,
        "carries: actual SHARE only": (yc * D.Tc_full / D.Tc - D.vc) * D.rv,
        "targets: actual TEAM total only": (D.vt * D.Tt / D.Tt_full - D.vt) * D.tv,
        "targets: actual SHARE only": (yt * D.Tt_full / D.Tt - D.vt) * D.tv,
        "goal-line carries actual (TD = league rate in/out of 10)": 6 * ((ygl.fillna(0) * r10 + (D.vc - ygl.fillna(0)).clip(lower=0) * rout) - D.vc * D.S7_e_rtd_c),
        "rushing TDs actual (bound)": 6 * (D.y_rtd.fillna(0) / D.y_g - D.vc * D.S7_e_rtd_c),
    }
    P(f"  league RB TD rate: inside the 10 {r10:.3f} per carry, outside {rout:.4f}")
    P("\n  ppg error with one piece swapped for the actual (final = v5 per-game + .75 x structural change)")
    P("| swap | pool MAE dev | pool rho dev | pool MAE holdout | pool rho holdout | ADP-150 MAE dev | ADP-150 rho dev |")
    P("|---|---|---|---|---|---|---|")
    for lab, d in sw.items():
        D["_x"] = D.pg + 0.75 * d
        cells = []
        for mk in (pool & D.season.isin(Q.DEV), pool & D.season.isin(Q.HOLD), adp150 & D.season.isin(Q.DEV)):
            m = mk & D._x.notna()
            cells += [f"{wmae(D._x[m], D.act_ppg[m], D.act_games[m]):.3f}", f"{rho(D[m], '_x'):.3f}"]
        P(f"| {lab} | " + " | ".join(cells) + " |")
    for b in ("adp_curve_f", "naive_f"):
        m = adp150 & D.season.isin(Q.DEV) & D[b].notna(); P(f"  benchmark {b} ADP-150 dev: MAE {wmae(D[b][m], D.act_ppg[m], D.act_games[m]):.3f} rho {rho(D[m], b):.3f}")
    # ---------------- add-up
    P("\n  do projected RB carries/targets add up? per team game, listed RBs, projected (carries per game x games share) vs the same players' actual")
    a = agg[agg.season.isin(PM.TEST_YEARS)]
    for v, pc, lc, tc in (("carries", "Pc", "Lc", "Tc"), ("targets", "Pt", "Lt", "Tt")):
        r = a[pc] / a[lc]
        P(f"   {v}: projected / actual for the listed backs: mean {r.mean():.2f}, median {r.median():.2f}, 10-90% {r.quantile(.1):.2f}-{r.quantile(.9):.2f}; projected / whole team RB total: mean {(a[pc]/a[tc]).mean():.2f}")
    D["vcpg_sum"] = D.groupby(["season", "team"]).vc.transform("sum")
    tt = D[rbm].drop_duplicates(["season", "team"])
    P(f"   carries per game PLAYED summed over the listed backs (no games share): {(tt.vcpg_sum/tt.Tc).mean():.2f} x the team's RB carries per game")
    P("   by week-1 chart spot (share of the team's RB carries per team game): projected vs actual")
    for k in (1, 2, 3):
        m = rbm & (D.dc == k)
        P(f"     spot {k}: n {int(m.sum())}: projected {(D.vc_tg[m]/D.Tc[m]).mean():.3f} | actual {(D.yc_tg[m]/D.Tc[m]).mean():.3f} || targets projected {(D.vt_tg[m]/D.Tt[m]).mean():.3f} | actual {(D.yt_tg[m]/D.Tt[m]).mean():.3f} || carries per game played projected {D.vc[m].mean():.1f} vs actual {yc[m & (D.y_g >= 1)].mean():.1f}")
    # ---------------- situations
    P("\n  share miss by situation (pool rows 2015-25): carries/g bias and MAE, targets/g bias and MAE, ppg MAE")
    sits = [("lead back, same team (last-season share >= .5)", (D.dc == 1) & (D.moved == 0) & (D.q_car1 >= .5)),
            ("committee (chart 1-2, last share .25-.5, same team)", D.dc.isin([1, 2]) & (D.moved == 0) & D.q_car1.between(.25, .5)),
            ("lead back who changed teams", (D.dc == 1) & (D.moved == 1) & (D.rookie == 0)),
            ("vet on a team that added a rd 1-3 rookie RB", (D.team_rb_r13 == 1) & (D.rookie == 0)),
            ("team lost its lead back (vacated >= .4)", (D.vac_pos >= .4) & (D.rookie == 0)),
            ("rookie rd 1", (D.rookie == 1) & (D.rd1 == 1)), ("rookie rd 2", (D.rookie == 1) & (D.rd2 == 1)),
            ("rookie rd 3+ / UDFA", (D.rookie == 1) & (D.rd1 == 0) & (D.rd2 == 0)),
            ("back from a long injury", D.inj_return == 1), ("team with a rushing QB (QB >= 20% of carries last yr)", D.t1_qb_rsh >= .2),
            ("new play-caller (OC/HC change, 2019+)", D.t0_new_oc == 1), ("all pool", D.dc.notna())]
    P("| situation | n | carries/g bias | MAE | targets/g bias | MAE | ppg MAE | ppg MAE x n share |")
    P("|---|---|---|---|---|---|---|---|")
    tot_err = np.sum(D.act_games[pool] * np.abs(D.pg[pool] - D.act_ppg[pool]))
    for lab, sm in sits:
        m = pool & sm
        if m.sum() < 8: continue
        P(f"| {lab} | {int(m.sum())} | {(D.vc[m]-yc[m]).mean():+.2f} | {np.mean(np.abs(D.vc[m]-yc[m])):.2f} | {(D.vt[m]-yt[m]).mean():+.2f} | {np.mean(np.abs(D.vt[m]-yt[m])):.2f} | {wmae(D.pg[m], D.act_ppg[m], D.act_games[m]):.3f} | {np.sum(D.act_games[m]*np.abs(D.pg[m]-D.act_ppg[m]))/tot_err*100:.0f}% |")
    # ---------------- stickiness
    P("\n  year-to-year stickiness (r with last season, and the regression slope = how much of last year carries over)")
    T = C.team_tables().set_index(["season", "team"]); T1 = T.reindex(list(zip(T.index.get_level_values(0) - 1, T.index.get_level_values(1))))
    for c in ("T_car", "T_tgt", "rb_tsh", "T_gl", "qb_rsh", "pass_rate", "pace"):
        x, y = T1[c].values, T[c].values; m = ~np.isnan(x) & ~np.isnan(y)
        P(f"   team {c:10s}: r {pearsonr(x[m], y[m])[0]:.2f} | slope {np.polyfit(x[m], y[m], 1)[0]:.2f} (n {int(m.sum())})")
    lead = (D.pos == "RB") & (D.moved == 0) & (D.q_car1 >= .4) & (D.y_g >= 8) & D.season.between(2013, 2025)
    for c, c1 in (("q_car", "q_car1"), ("q_tgt", "q_tgt1"), ("q_gl", "q_gl1")):
        m = lead & D[c].notna() & D[c1].notna()
        P(f"   lead back (last share >= .4, same team, 8+ g) {c:6s}: r {pearsonr(D[c1][m], D[c][m])[0]:.2f} | slope {np.polyfit(D[c1][m], D[c][m], 1)[0]:.2f} | mean {D[c1][m].mean():.2f} -> {D[c][m].mean():.2f} (n {int(m.sum())})")
    allrb = (D.pos == "RB") & (D.moved == 0) & (D.y_g >= 4) & (D.q_car1 > 0) & D.season.between(2013, 2025)
    for c, c1 in (("q_car", "q_car1"), ("q_tgt", "q_tgt1"), ("q_gl", "q_gl1")):
        m = allrb & D[c].notna() & D[c1].notna()
        P(f"   any returning RB {c:6s}: r {pearsonr(D[c1][m], D[c][m])[0]:.2f} | slope {np.polyfit(D[c1][m], D[c][m], 1)[0]:.2f} (n {int(m.sum())})")
    # goal-line share given carry share: does GL share carry information beyond carry share?
    m = lead & D.q_gl.notna() & D.q_gl1.notna() & D.q_car.notna()
    res = D.q_gl[m] - np.polyval(np.polyfit(D.q_car1[m], D.q_gl[m], 1), D.q_car1[m])
    P(f"   goal-line share this year after last year's carry share: partial r with last year's GL share {pearsonr(D.q_gl1[m] - np.polyval(np.polyfit(D.q_car1[m], D.q_gl1[m], 1), D.q_car1[m]), res)[0]:.2f}")
    P("\ndone")


if __name__ == "__main__":
    main()
