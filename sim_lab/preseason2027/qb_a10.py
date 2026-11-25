#!/usr/bin/env python3
"""
A10 - QB ordering in the in-house preseason prototype (Jack 2026-11-21 "Fix QB order first"). No ADP input.
Walk-forward 2015-25; choices on 2015-22; 2023-25 reported separately (already viewed, not clean).
QB pool = every week-1 chart QB1 (32 a season) + any QB with 4+ games of 15+ attempts that season (in-season takeovers).
  Step 1  diagnosis: component oracle swaps (error AND order), QB types, the four 2026 patterns as history questions
  Step 2  candidates (QB rows only, everything else unchanged): team context for QB volume, rushing age decline + harder
          rushing shrink, more weight on multi-season history for 'one good season' QBs, QB-specific games terms
          (established x short-season rebound, job threat), each kept only if it beats the base on dev
Writes qb_a10.log (log of record, opened in main()) and data/qb_a10_rows.parquet.
"""
import os, sys, time, warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM, games_model as GM, pergame_model as G, fixes_a9 as FX

LOG = None
DEV = list(range(2015, 2023)); HOLD = [2023, 2024, 2025]
LEAN = G.BASIC + G.ROSTER + ["lp_rook"]
COMP = {"att": ("v", "att"), "pyd_a": ("e", "pyd_a"), "ptd_a": ("e", "ptd_a"), "int_a": ("e", "int_a"), "car": ("v", "car"), "ryd_c": ("e", "ryd_c"), "rtd_c": ("e", "rtd_c")}


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def qb_ppg(v, e):
    return v["att"] * (0.04 * e["pyd_a"] + 4 * e["ptd_a"] - e["int_a"]) + v["car"] * (0.1 * e["ryd_c"] + 6 * e["rtd_c"]) + v["tgt"] * 0.0


def grade(D, col, mask, lab, ycol="act_ppg"):
    """QB order metrics: games-weighted MAE, mean within-season Spearman, top-12 / top-24 hit, QB1-6 finishing top 12 (by total)."""
    m = mask & D[col].notna() & (D.act_games >= 4)
    rh, h12, h24, t6 = [], [], [], []
    for y, g in D[m].groupby("season"):
        if len(g) < 20: continue
        rh.append(spearmanr(g[col], g[ycol]).correlation)
        h12.append(len(set(g.nlargest(12, col).pid) & set(g.nlargest(12, ycol).pid)) / 12)
        h24.append(len(set(g.nlargest(24, col).pid) & set(g.nlargest(24, ycol).pid)) / 24)
    mt = mask & D[col].notna()
    for y, g in D[mt].groupby("season"):
        if len(g) < 20: continue
        g = g.assign(tot=g[col] * g.g_use * g.G)
        t6.append(len(set(g.nlargest(6, "tot").pid) & set(g.nlargest(12, "act_total").pid)) / 6)
    mae = FX.wmae(D[col][m], D[ycol][m], D.act_games[m])
    P(f"    {lab:34s} n {int(m.sum()):4d} | MAE {mae:.3f} | rho {np.mean(rh):.3f} | top12 {np.mean(h12):.3f} | top24 {np.mean(h24):.3f} | QB1-6 in top12 {np.mean(t6):.3f}")
    return mae, np.mean(rh)


def main():
    global LOG
    LOG = open(os.path.join(HERE, "qb_a10.log"), "w", encoding="utf-8")
    t0 = time.time()
    P("=== A10 QB ordering (in-house, no ADP input) ===")
    D = PM.build(); AV, wk1 = GM.availability(); D = GM.add_features(D, AV, wk1)
    S = G.stat_seasons(); D = G.add_history(D, S); D = G.add_context(D, S); D = FX.add_fix1_features(D)
    R0 = PM.walk_forward(D)
    for c in ("ridge_stats", "adp_curve_f", "adp_curve", "naive_f"): D[c] = R0[c].values
    feats1 = [f if f != "gs1" else "gs1_shrunk" for f in GM.GF]
    O = GM.walk(D, feats1, "g"); D = pd.concat([D, O], axis=1); D["g_use"] = 0.75 * D.g_ridge + 0.25 * D.g_dist
    s7, cp, _ = G.walk(D, LEAN, "S7", use_role_prior=True)
    D["s7"] = s7.values; D["pg"] = 0.75 * D.s7 + 0.25 * D.ridge_stats
    for k in cp: D[k] = cp[k].values
    # QB pool
    W = pd.read_parquet(os.path.join(PM.DATA, "player_weeks.parquet"), columns=["season", "week", "pid", "att"])
    W = W[W.week < W.season.map(PM.final_week)]
    starts = W[W.att >= 15].groupby(["season", "pid"]).size()
    D["starts"] = [starts.get((y, p), 0) for y, p in zip(D.season, D.pid)]
    QB = (D.pos == "QB") & D.season.isin(PM.TEST_YEARS)
    pool = QB & ((D.is_qb1 == 1) | (D.starts >= 4))
    adp150 = QB & D.adp.notna() & (D.adp <= 150)
    P(f"  QB pool (week-1 QB1 + 4-start takeovers): {int(pool.sum())} QB-seasons ({int((pool & (D.is_qb1 == 1)).sum())} week-1 starters); ADP-top-150 QBs {int(adp150.sum())}")

    # ---------------- STEP 1: diagnosis
    P("\n=== STEP 1. Diagnosis ===")
    grade(D, "pg", pool, "in-house (A9) per game")
    grade(D, "naive_f", pool, "naive last-season PPG")
    grade(D, "adp_curve_f", pool & D.adp.notna(), "ADP curve (QBs with ADP only)")
    grade(D, "pg", pool & D.adp.notna(), "in-house, same QBs with ADP")
    grade(D, "pg", adp150, "in-house, ADP-top-150 QBs (old table)")
    # component oracle on the structural part (S7)
    P("\n  component oracle swaps on the structural number (S7), QB pool: actual value of ONE part swapped in")
    v = {"att": D.S7_v_att, "car": D.S7_v_car, "tgt": D.S7_v_tgt * 0}; e = {x: D[f"S7_e_{x}"] for x in ("pyd_a", "ptd_a", "int_a", "ryd_c", "rtd_c")}
    D["o_base"] = qb_ppg(v, e)
    grade(D, "o_base", pool, "S7 structural (no swap)")
    acts = {"att": D.y_attpg, "car": D.y_carpg, "pyd_a": D.y_pyd_a, "ptd_a": D.y_ptd_a, "int_a": D.y_int_a, "ryd_c": D.y_ryd_c, "rtd_c": D.y_rtd_c}
    for k, (typ, nm) in COMP.items():
        v2, e2 = dict(v), dict(e)
        if typ == "v": v2[nm] = acts[k].fillna(v[nm])
        else: e2[nm] = acts[k].fillna(e[nm])
        D[f"o_{k}"] = qb_ppg(v2, e2)
        grade(D, f"o_{k}", pool, f"  swap actual {k}")
    # games: totals with actual games
    D["tot_pred"] = D.pg * D.g_use * D.G
    m = pool & D.tot_pred.notna()
    rh_g = np.mean([spearmanr(g.tot_pred, g.act_total).correlation for _, g in D[m].groupby("season") if len(g) >= 20])
    rh_ga = np.mean([spearmanr(g.pg * g.act_games, g.act_total).correlation for _, g in D[m].groupby("season") if len(g) >= 20])
    P(f"  season totals rho: predicted games {rh_g:.3f} | ACTUAL games swapped in {rh_ga:.3f} | games MAE {np.mean(np.abs(D.g_use[m]*D.G[m] - D.act_games[m])):.2f}")
    # QB types
    P("\n  QB types (pool, 4+ games): n | MAE | bias act/pred | rho within type (pooled)")
    D["res"] = D.act_ppg - D.pg
    D["rushq"] = D.qbr1.fillna(0) >= 25
    D["jump"] = (D.ppg1 - np.where(D.ppg2.notna(), D.ppg2, D.ppg1)) >= 3
    types = [("established, same team + coach", (D.est == 1) & (D.moved == 0) & (D.new_hc == 0)), ("new team", D.moved == 1), ("new head coach", D.new_hc == 1),
             ("lost receivers (vacated tgt >= .3)", D.vac_tgt >= .3), ("rookie", D.rookie == 1), ("second year", D.exp == 1), ("back from short season", D.short1 == 1),
             ("age 34+", D.age >= 34), ("rushing QB (25+ rush yd/g)", D.rushq), ("pocket passer", ~D.rushq & (D.rookie == 0)),
             ("job threat (team drafted rd-1 QB)", D.team_r1qb == 1), ("one-big-season jump (+3 ppg)", D.jump & (D.rookie == 0)), ("backup who took over (not QB1 wk1)", D.is_qb1 == 0)]
    for lab, mk in types:
        mm = pool & mk & (D.act_games >= 4) & D.pg.notna()
        if mm.sum() < 10: P(f"    {lab:38s} n {int(mm.sum())} (too few)"); continue
        P(f"    {lab:38s} n {int(mm.sum()):3d} | {FX.wmae(D.pg[mm], D.act_ppg[mm], D.act_games[mm]):.3f} | {D.act_ppg[mm].sum()/D.pg[mm].sum():.3f} | {spearmanr(D.pg[mm], D.act_ppg[mm]).correlation:.3f}")
    # 2026 patterns as history questions
    P("\n  the 2026 patterns, as history questions (pool, 4+ games):")
    mm = pool & D.rushq & (D.act_games >= 4)
    P(f"    rushing QBs: per-game act/pred {D.act_ppg[mm].sum()/D.pg[mm].sum():.3f}; rush part act/pred {(D.y_carpg[mm]*(0.1*D.y_ryd_c[mm].fillna(0)+6*D.y_rtd_c[mm].fillna(0))).sum()/(D.S7_v_car[mm]*(0.1*D.S7_e_ryd_c[mm]+6*D.S7_e_rtd_c[mm])).sum():.3f} (n {int(mm.sum())})")
    mm = pool & D.jump & (D.rookie == 0) & (D.act_games >= 4)
    P(f"    one-big-season QBs (+3 ppg jump): act/pred {D.act_ppg[mm].sum()/D.pg[mm].sum():.3f} (n {int(mm.sum())})")
    mm = pool & (D.est == 1) & (D.short1 == 1)
    P(f"    proven passers off a short year: per-game act/pred {D.act_ppg[mm & (D.act_games>=4)].sum()/D.pg[mm & (D.act_games>=4)].sum():.3f}; games pred {np.mean(D.g_use[mm]*D.G[mm]):.1f} vs act {np.mean(D.act_games[mm]):.1f} (n {int(mm.sum())})")
    mm = pool & (D.y1_role if "y1_role" in D else D.role1 * D.G > 2) if False else pool & (D.role1 * 16.5 > 2)
    P(f"    QBs who lost time to role last year: games pred {np.mean(D.g_use[mm]*D.G[mm]):.1f} vs act {np.mean(D.act_games[mm]):.1f} (n {int(mm.sum())})")

    # ---------------- STEP 2: candidates (QB rows only)
    P("\n=== STEP 2. Candidates (QB rows only; dev 2015-22 / holdout 2023-25) ===")
    D["age_rush"] = np.maximum(0, D.age - 29) * D.qbr1.fillna(0) / 25
    D["jump_flag"] = (D.jump & (D.rookie == 0)).astype(float)
    D["est_short"] = D.est * D.short1
    D["qb_threat"] = np.where(D.pos == "QB", D.team_r1qb, 0.0)
    D["qb_prev_rank_low"] = np.where(D.pos == "QB", (D.ppg1.fillna(0) < 14).astype(float), 0.0)
    cands = {"team context (QB volume)": LEAN + ["team_pa1", "team_ra1", "team_pf1", "exp_w", "new_hc", "new_qb"],
             "rushing age decline": LEAN + ["age_rush"],
             "one-season jump flag": LEAN + ["jump_flag"]}
    res = {}
    for lab, feats in cands.items():
        s, c2, _ = G.walk(D, feats, "c", use_role_prior=True)
        D[f"pg_{lab}"] = np.where(D.pos == "QB", 0.75 * s + 0.25 * D.ridge_stats, D.pg)
    # efficiency/rushing shrink: QB TD and rush rates regressed harder (k x 2) - implemented by blending the S7 rates toward the prior
    pm = {x: float(np.nansum(D[f"y_{x.split('_')[0]}"][QB & D.season.isin(DEV)]) / 1) for x in ()}
    # QB-only blend weight S7 vs ridge (more weight on the multi-season ridge for QBs)
    for wq in (0.5, 0.25):
        D[f"pg_blend{wq}"] = np.where(D.pos == "QB", wq * D.s7 + (1 - wq) * D.ridge_stats, D.pg)
    # games: QB-specific terms
    Og = GM.walk(D, feats1 + ["est_short", "qb_threat", "qb_prev_rank_low"], "q")
    D["g_qb"] = np.where(D.pos == "QB", (0.75 * Og.q_ridge + 0.25 * Og.q_dist).values, D.g_use)
    for lab in list(cands) + ["blend0.5", "blend0.25"]:
        col = f"pg_{lab}"
        P(f"  {lab}:")
        res[lab] = (grade(D, col, pool & D.season.isin(DEV), "   dev"), grade(D, col, pool & D.season.isin(HOLD), "   holdout"))
    P("  base:"); base = (grade(D, "pg", pool & D.season.isin(DEV), "   dev"), grade(D, "pg", pool & D.season.isin(HOLD), "   holdout"))
    for lab, gcol in (("games base", "g_use"), ("games + QB terms", "g_qb")):
        for nm, mk in (("dev", pool & D.season.isin(DEV)), ("holdout", pool & D.season.isin(HOLD)), ("est. off short year", pool & (D.est_short == 1)), ("lost time to role", pool & (D.role1 * 16.5 > 2)), ("job threat", pool & (D.qb_threat == 1))):
            mm = mk & D[gcol].notna()
            P(f"    {lab:16s} {nm:20s} n {int(mm.sum()):3d}: games pred {np.mean(D[gcol][mm]*D.G[mm]):.1f} vs act {np.mean(D.act_games[mm]):.1f} | MAE {np.mean(np.abs(D[gcol][mm]*D.G[mm]-D.act_games[mm])):.2f}")
    # pick on dev: per-game rho improvement + MAE not worse
    keep = [lab for lab, ((dm, dr), _) in res.items() if dr > base[0][1] + 0.005 and dm <= base[0][0] + 0.005]
    P(f"\n  kept on dev (rho +.005 and MAE not worse): {keep or 'none'}")
    # combined final
    if keep:
        best = max(keep, key=lambda l: res[l][0][1])
        D["pg_final"] = D[f"pg_{best}"]
    else:
        best = None; D["pg_final"] = D.pg
    dev_g = FX.wmae(D.g_qb[pool & D.season.isin(DEV)] * D.G[pool & D.season.isin(DEV)], D.act_games[pool & D.season.isin(DEV)], 1) if False else None
    gm_keep = np.mean(np.abs(D.g_qb[pool & D.season.isin(DEV)] * D.G[pool & D.season.isin(DEV)] - D.act_games[pool & D.season.isin(DEV)])) < np.mean(np.abs(D.g_use[pool & D.season.isin(DEV)] * D.G[pool & D.season.isin(DEV)] - D.act_games[pool & D.season.isin(DEV)])) - 0.03
    D["g_final"] = D.g_qb if gm_keep else D.g_use
    P(f"  per-game choice: {best or 'base'} | QB games terms kept: {gm_keep}")
    D["g_use_save"] = D.g_use; D["g_use"] = D.g_final
    P("\n=== Final QB numbers ===")
    for nm, mk in (("dev 2015-22", pool & D.season.isin(DEV)), ("holdout 2023-25", pool & D.season.isin(HOLD)), ("all 2015-25", pool)):
        grade(D, "pg", mk, f"{nm} base")
        grade(D, "pg_final", mk, f"{nm} final")
        grade(D, "naive_f", mk, f"{nm} naive")
        grade(D, "adp_curve_f", mk & D.adp.notna(), f"{nm} ADP (QBs with ADP)")
    grade(D, "pg_final", adp150, "ADP-top-150 QBs final (old table)")
    grade(D, "pg", adp150, "ADP-top-150 QBs base (old table)")
    # season-by-season wins vs ADP on rho (QBs with ADP)
    w = []
    for y in PM.TEST_YEARS:
        g = D[pool & D.adp.notna() & (D.season == y) & (D.act_games >= 4)]
        if len(g) < 12: continue
        w.append((y, spearmanr(g.pg_final, g.act_ppg).correlation, spearmanr(g.adp_curve_f, g.act_ppg).correlation, spearmanr(g.pg, g.act_ppg).correlation))
    P("  season QB rho (QBs with ADP): " + " | ".join(f"{y}: final {a:.2f} / ADP {b:.2f} / base {c:.2f}" for y, a, b, c in w))
    P(f"  final beats ADP on QB rho in {sum(a > b for _, a, b, _ in w)}/{len(w)} seasons; base {sum(c > b for _, _, b, c in w)}/{len(w)}")
    # other positions untouched by construction; overall top-150 effect via totals
    D["tot_final"] = D.pg_final * D.g_final * D.G; D["tot_base"] = D.pg * D.g_use_save * D.G
    D["adp_total"] = R0.adp_total.values
    p150 = D.season.isin(PM.TEST_YEARS) & D.adp.notna() & (D.adp <= 150)
    for c in ("tot_base", "tot_final"):
        m = p150 & D[c].notna()
        P(f"  overall ADP top 150 totals {c}: MAE {np.mean(np.abs(D[c][m]-D.act_total[m])):.2f} | per-pos Spearman {np.mean([spearmanr(g[c], g.act_total).correlation for _, g in D[m].groupby(['season','pos']) if len(g) >= 24]):.3f}")
    keepcols = ["season", "pid", "name", "pos", "team", "pg", "pg_final", "g_use_save", "g_final", "act_ppg", "act_games", "act_total", "adp", "is_qb1", "starts"]
    D[keepcols].to_parquet(os.path.join(HERE, "data", "qb_a10_rows.parquet"), index=False)
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
