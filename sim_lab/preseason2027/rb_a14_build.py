#!/usr/bin/env python3
"""
A14 step 2 - RB volume candidates on the v5 per-game model (walk-forward 2015-25; choices on 2015-22, 2023-25 viewed holdout).
In-house only, no ADP input. Each candidate changes only RB rows; final per-game = v5 + .75 x structural change.
  B0  replicate the v5 RB volume ridge (check)
  C1  team backfield total: walk-forward team ridge for RB carries / targets per team game; listed backs rescaled to it (alpha .5 / 1)
  C2  share inputs in the RB volume ridge: last-season shares of team RB carries / RB targets / goal-line carries, investment,
      team added a rd 1-3 back, rushing-QB share, new play-caller, team RB volume last season
  C3  C2 + C1 rescale (shares forced to sum to the team total: the A12 question)
  C4  goal-line TD rate: rushing TD per carry = GL carries per carry (EB-shrunk own history) x league TD rate inside the 10
      + the rest x the rate outside (replaces the plain EB rushing-TD rate; 50/50 blend also tested)
  spread: per-game p10-p90 coverage with RB ratios pooled vs by backfield tier
Log: rb_a14_build.log (opened in main()). Rows: data/rb_a14_rows.parquet.
"""
import os, sys, warnings
import numpy as np, pandas as pd
from scipy.stats import spearmanr
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM, qb_a10 as Q, rb_a14_common as C, rb_a14_diag as DG

LOG = None
EXTRA = ["q_car1", "q_tgt1", "q_gl1", "inv", "team_rb_r13", "t1_qb_rsh", "t0_new_oc", "t1_T_car", "t1_T_tgt"]


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def ridge_vol(D, feats, ycol):
    from sklearn.linear_model import Ridge
    out = pd.Series(np.nan, index=D.index)
    for Y in PM.TEST_YEARS:
        tr = (D.season < Y) & (D.pos == "RB") & (D.y_g >= 4); te = (D.season == Y) & (D.pos == "RB")
        w = D.y_g[tr].values * 0.5 ** ((Y - 1 - D.season[tr].values) / 4.0)
        A, B = PM.prep(D.loc[tr, feats].values.astype(float), D.loc[te, feats].values.astype(float))
        mu, sd = A.mean(0), A.std(0); sd[sd == 0] = 1
        out[te] = np.maximum(0, Ridge(alpha=10.0).fit((A - mu) / sd, D[ycol][tr].fillna(0).values, sample_weight=w).predict((B - mu) / sd))
    return out


def team_model(D, keep_year=None, quiet=False):
    """walk-forward team ridge for RB carries / targets per team game; returns per-row T_hat for the player's team.
    keep_year: a target season whose actual team totals are not on disk yet (2027) is kept for prediction."""
    from sklearn.linear_model import Ridge
    T = D[(D.pos == "RB") & D.team.notna() & (D.t0_T_car.notna() | (D.season == keep_year))].groupby(["season", "team"]).agg(
        T_car=("t0_T_car", "first"), T_tgt=("t0_T_tgt", "first"), c1=("t1_T_car", "first"), c2=("t2_T_car", "first"), t1=("t1_T_tgt", "first"), t2=("t2_T_tgt", "first"),
        ew=("exp_w", "mean"), pr=("t1_pass_rate", "first"), pc=("t1_pace", "first"), qr=("t1_qb_rsh", "first"), oc=("t0_new_oc", "first")).reset_index()
    F = ["c1", "c2", "t1", "t2", "ew", "pr", "pc", "qr", "oc"]
    for v in ("T_car", "T_tgt"):
        T[f"{v}_hat"] = np.nan; T[f"{v}_naive"] = np.nan; T[f"{v}_mean"] = np.nan
        for Y in PM.TEST_YEARS:
            tr = (T.season < Y) & (T.season >= 2013); te = T.season == Y
            A, B = PM.prep(T.loc[tr, F].values.astype(float), T.loc[te, F].values.astype(float)); mu, sd = A.mean(0), A.std(0); sd[sd == 0] = 1
            T.loc[te, f"{v}_hat"] = Ridge(alpha=10.0).fit((A - mu) / sd, T.loc[tr, v].values).predict((B - mu) / sd)
            T.loc[te, f"{v}_mean"] = T.loc[tr, v].mean()
            T.loc[te, f"{v}_naive"] = T.loc[te, "c1" if v == "T_car" else "t1"].fillna(T.loc[tr, v].mean())
    m = T.season.isin(PM.TEST_YEARS) & T.T_car.notna()
    for v in ("T_car", "T_tgt") if not quiet else ():
        for nm, yrs in (("dev", Q.DEV), ("holdout", Q.HOLD)):
            mm = m & T.season.isin(yrs)
            P(f"  team {v} per game {nm}: MAE ridge {np.mean(np.abs(T[f'{v}_hat'][mm]-T[v][mm])):.2f} | last season {np.mean(np.abs(T[f'{v}_naive'][mm]-T[v][mm])):.2f} | league mean {np.mean(np.abs(T[f'{v}_mean'][mm]-T[v][mm])):.2f} | r ridge {np.corrcoef(T[f'{v}_hat'][mm], T[v][mm])[0,1]:.2f}")
    return D.merge(T[["season", "team", "T_car_hat", "T_tgt_hat"]], on=["season", "team"], how="left")


def rescale(D, vc, vt, alpha):
    pc = (vc * D.g_use).groupby([D.season, D.team]).transform("sum"); pt = (vt * D.g_use).groupby([D.season, D.team]).transform("sum")
    fc = (D.T_car_hat / pc.replace(0, np.nan)).clip(.5, 2).fillna(1) ** alpha; ft = (D.T_tgt_hat / pt.replace(0, np.nan)).clip(.5, 2).fillna(1) ** alpha
    return vc * fc, vt * ft


def gl_rate(D):
    """EB-shrunk goal-line carries per carry (history 1/.7/.5), walk-forward; league TD rates inside / outside the 10 from train."""
    GL = C.gl_table().groupby(["season", "pid"]).agg(gl10=("gl10", "sum"), car=("car", "sum"), td10=("td10", "sum"), tdout=("tdout", "sum"))
    num = np.zeros(len(D)); den = np.zeros(len(D))
    for k, w in ((1, 1.0), (2, .7), (3, .5)):
        sub = GL.reindex(list(zip(D.season - k, D.pid)))
        num += w * sub.gl10.fillna(0).values; den += w * sub.car.fillna(0).values
    D["gl_num"], D["gl_den"] = num, den
    D["y_glc"] = D.y_gl10 / D.y_car.replace(0, np.nan)
    D["rtd_gl"] = np.nan
    for Y in PM.TEST_YEARS:
        tr = (D.season < Y) & (D.pos == "RB") & (D.y_car >= 10); te = (D.season == Y) & (D.pos == "RB")
        prior = D.y_gl10[tr].sum() / D.y_car[tr].sum(); r10 = D.y_td10[tr].sum() / D.y_gl10[tr].sum(); rout = D.y_tdout[tr].sum() / (D.y_car[tr] - D.y_gl10[tr]).sum()
        best = None
        for k in (5, 10, 20, 40, 80, 160, 320, 640):
            est = (D.gl_num[tr] + k * prior) / (D.gl_den[tr] + k); err = np.sum(D.y_car[tr] * (est - D.y_glc[tr]) ** 2)
            if best is None or err < best[0]: best = (err, k)
        glc = (D.gl_num[te] + best[1] * prior) / (D.gl_den[te] + best[1])
        D.loc[te, "rtd_gl"] = glc * r10 + (1 - glc) * rout
        if Y in (2015, 2022, 2025): P(f"  goal-line rate {Y}: prior {prior:.3f} GL carries per carry, k {best[1]}, TD rate in 10 {r10:.3f}, outside {rout:.4f}")
    return D


def grade(D, cols, mask, lab):
    P(f"\n  {lab}")
    P("| model | n | MAE | rho | top12 | top24 | top36 (season totals) | totals MAE |")
    P("|---|---|---|---|---|---|---|---|")
    for c in cols:
        m = mask & D[c].notna()
        tot = D[c] * D.g_use * D.G if c not in ("adp_curve_f",) else D.adp_total
        if c == "naive_f": tot = D.naive_f * D.g_use * D.G
        h = {k: np.mean([len(set(g.assign(t=tot[g.index]).nlargest(k, "t").pid) & set(g.nlargest(k, "act_total").pid)) / k for _, g in D[m].groupby("season") if len(g) >= k]) for k in (12, 24, 36)}
        P(f"| {c} | {int(m.sum())} | {DG.wmae(D[c][m], D.act_ppg[m], D.act_games[m]):.3f} | {DG.rho(D[m], c):.3f} | {h[12]:.3f} | {h[24]:.3f} | {h[36]:.3f} | {np.mean(np.abs(tot[m]-D.act_total[m])):.1f} |")


def main():
    global LOG
    LOG = open(os.path.join(HERE, "rb_a14_build.log"), "w", encoding="utf-8")
    P("=== A14 step 2. RB volume candidates ===")
    D = C.build(); D, _, _ = DG.prep(D)
    rb = (D.pos == "RB") & D.season.isin(PM.TEST_YEARS) & D.vc.notna()
    LEAN = Q.LEAN
    b_c = ridge_vol(D, LEAN, "y_carpg"); b_t = ridge_vol(D, LEAN, "y_tgtpg")
    P(f"  B0 replication of the v5 RB volume ridge: corr with v5 carries {np.corrcoef(b_c[rb], D.vc[rb])[0,1]:.4f}, targets {np.corrcoef(b_t[rb], D.vt[rb])[0,1]:.4f}")
    D = team_model(D)
    x_c = ridge_vol(D, LEAN + EXTRA, "y_carpg"); x_t = ridge_vol(D, LEAN + EXTRA, "y_tgtpg")
    D = gl_rate(D)
    V = {"v5": (D.vc, D.vt)}
    V["C1 team rescale a.5"] = rescale(D, D.vc, D.vt, .5); V["C1 team rescale a1"] = rescale(D, D.vc, D.vt, 1.0)
    V["C2 share inputs"] = (D.vc + (x_c - b_c), D.vt + (x_t - b_t))
    V["C3 share inputs + rescale a1"] = rescale(D, *V["C2 share inputs"], 1.0)
    V["C3 share inputs + rescale a.5"] = rescale(D, *V["C2 share inputs"], .5)
    yc = D.y_carpg.fillna(0); yt = D.y_tgtpg.fillna(0)
    ok = rb & (D.act_games >= 4) & D.pg.notna(); pool = ok & D.dc.isin([1, 2, 3]); adp150 = ok & (D.adp <= 150)
    P("\n  volume itself (pool, per game played): carries MAE / rho | targets MAE / rho ; and team add-up |gap| (projected per team game vs team RB total)")
    for lab, (vc, vt) in V.items():
        line = f"  {lab:32s}"
        for nm, yrs in (("dev", Q.DEV), ("hold", Q.HOLD)):
            m = pool & D.season.isin(yrs)
            line += f" | {nm} car {np.mean(np.abs(vc[m]-yc[m])):.2f}/{DG.rho(D[m].assign(_v=vc[m]), '_v', 'y_carpg'):.3f} tgt {np.mean(np.abs(vt[m]-yt[m])):.3f}/{DG.rho(D[m].assign(_v=vt[m]), '_v', 'y_tgtpg'):.3f}"
        pc = (vc * D.g_use)[rb].groupby([D.season[rb], D.team[rb]]).sum(); tc = D[rb].groupby(["season", "team"]).t0_T_car.first()
        line += f" | add-up carries |gap| {np.mean(np.abs(pc/tc-1)):.3f}"
        P(line)
    # goal-line volume check
    glp = D.vc * (D.gl_num + 1e-9) / (D.gl_den + 1e-9)
    # per-game candidates
    for lab, (vc, vt) in V.items():
        D[f"pg_{lab}"] = D.pg + 0.75 * ((vc - D.vc) * D.rv + (vt - D.vt) * D.tv)
    D["pg_C4 GL TD rate"] = D.pg + 0.75 * 6 * D.vc * (D.rtd_gl - D.S7_e_rtd_c)
    D["pg_C4 GL TD 50/50"] = D.pg + 0.75 * 6 * D.vc * (0.5 * D.rtd_gl + 0.5 * D.S7_e_rtd_c - D.S7_e_rtd_c)
    D["pg_C2+C4"] = D["pg_C2 share inputs"] + (D["pg_C4 GL TD rate"] - D.pg)
    D["pg_C2+C4 50/50"] = D["pg_C2 share inputs"] + (D["pg_C4 GL TD 50/50"] - D.pg)
    cands = [c for c in D.columns if c.startswith("pg_")]
    P("\n  RB per-game, every candidate: MAE / rho (pool = week-1 chart 1-3; ADP-150 = redraft ADP top 150)")
    P("| candidate | pool dev | pool holdout | ADP-150 dev | ADP-150 holdout |")
    P("|---|---|---|---|---|")
    for c in ["pg"] + cands + ["adp_curve_f", "naive_f"]:
        cells = []
        for mk in (pool & D.season.isin(Q.DEV), pool & D.season.isin(Q.HOLD), adp150 & D.season.isin(Q.DEV), adp150 & D.season.isin(Q.HOLD)):
            m = mk & D[c].notna(); cells.append(f"{DG.wmae(D[c][m], D.act_ppg[m], D.act_games[m]):.3f} / {DG.rho(D[m], c):.3f}")
        P(f"| {c} | " + " | ".join(cells) + " |")
    # per-season wins vs v5 on dev for the main candidates
    P("\n  seasons where the candidate beats v5 per-game MAE (pool), dev / holdout")
    for c in cands:
        w = [DG.wmae(D[c][pool & (D.season == y)], D.act_ppg[pool & (D.season == y)], D.act_games[pool & (D.season == y)]) < DG.wmae(D.pg[pool & (D.season == y)], D.act_ppg[pool & (D.season == y)], D.act_games[pool & (D.season == y)]) for y in PM.TEST_YEARS]
        P(f"   {c:36s}: dev {sum(w[:8])}/8, holdout {sum(w[8:])}/3")
    D.to_parquet(os.path.join(HERE, "data", "rb_a14_rows.parquet"), index=False)
    P("\ndone")


if __name__ == "__main__":
    main()
