#!/usr/bin/env python3
"""
model.py - the scratch weekly projection models, built on the as-of table (asof.py).

Two models, same inputs:
  STRUCT  a transparent opportunity x efficiency model: expected team volume (as-of pace + Vegas tilt) x the
          player's share (short/long EWMAs, vacated-share redistribution) x shrunk per-opportunity efficiency,
          touchdowns from the team's expected TDs x the player's end-zone / goal-line share, opponent zone rates
          as-of (def_zones rebuilt leak-free), blended with a preseason prior (ADP curve + last season) by
          effective games, then the injury-status multiplier and a per-position calibration.  ~25 constants, all
          fitted on 2017-2024 and checked forward on 2025 before touching 2026.
  GBM     LightGBM per position on the same as-of features (what a pure ML read of the data gives).

grade(): Jack's grading - importance weights from the preseason ADP curve (cubed, top 100 dominant), MAE,
within-position-week Spearman, top-12/24/36 hit rates, pairwise start/sit order, all by ADP band.
"""
import os, sys, json, math
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata, spearmanr
from scipy.optimize import minimize

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
POS4 = ("QB", "RB", "WR", "TE")
BANDS = (("1-12", 0, 12), ("13-30", 12, 30), ("31-60", 30, 60), ("61-100", 60, 100), ("101-150", 100, 150), ("151+", 150, 9999))


def load_asof(years):
    return pd.concat([pd.read_parquet(os.path.join(CACHE, f"asof_{Y}.parquet")) for Y in years], ignore_index=True)


# ----------------------------------------------------------------------------- priors
def fit_adp_curve(df):
    """half-PPR ppg (played games) as a function of overall ADP, per position: ppg = a * exp(-b * ln(adp)) ... fitted as
    log-linear on log(adp); returns {pos: (a, b, floor)}"""
    out = {}
    for p in POS4:
        m = (df.pos == p) & df.adp.notna() & (df.adp <= 250)
        x = np.log(df.adp[m].values); y = df.act[m].values
        A = np.vstack([np.ones_like(x), x]).T
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        floor = float(df.act[(df.pos == p) & (df.adp.isna() | (df.adp > 250))].mean())
        out[p] = (float(coef[0]), float(coef[1]), floor)
    return out


def adp_ppg(df, curve):
    v = np.full(len(df), np.nan)
    for p, (a, b, fl) in curve.items():
        m = (df.pos == p).values
        adp = df.adp.values
        v[m] = np.where(np.isnan(adp[m]) | (adp[m] > 250), fl, a + b * np.log(np.clip(adp[m], 1, 250)))
    return v


# ----------------------------------------------------------------------------- team volume
def fit_team_volume(df):
    """OLS: team pass attempts (and carries) this game ~ as-of EWMA + Vegas spread/total. One row per team-game."""
    t = df.drop_duplicates(["season", "week", "team"])
    t = t[t.tm_games.fillna(0) >= 2]
    out = {}
    for tgt, base in (("t_att", "tm_t_att"), ("t_car", "tm_t_car")):
        pass
    return out


def team_volume_model(all_pg):
    """fit on raw team-game rows: t_att, t_car ~ EWMA levels (built in asof) + tspread + total. all_pg = as-of rows."""
    t = all_pg.drop_duplicates(["season", "week", "team"]).copy()
    t = t[(t.tm_games.fillna(0) >= 2) & t.tspread.notna() & t.total.notna()]
    # need the realised team totals of that game: pulled from team-game cache
    tg = pd.concat([pd.read_parquet(os.path.join(CACHE, f"tg_{Y}.parquet"))[["season", "week", "team", "t_att", "t_car", "t_tgt", "t_ptd", "t_rtd"]]
                    for Y in sorted(t.season.unique())])
    t = t.merge(tg, on=["season", "week", "team"], how="inner")
    coefs = {}
    for y, base in (("t_tgt", "tm_t_tgt"), ("t_car", "tm_t_car"), ("t_att", "tm_t_att")):
        X = np.vstack([np.ones(len(t)), t[base].values, t.tspread.values, t.total.values]).T
        c, *_ = np.linalg.lstsq(X, t[y].values, rcond=None)
        coefs[y] = [float(v) for v in c]
    # team touchdowns ~ implied total (pass / rush split by as-of pass-td share)
    X = np.vstack([np.ones(len(t)), t.implied.fillna(22).values]).T
    for y in ("t_ptd", "t_rtd"):
        c, *_ = np.linalg.lstsq(X, t[y].values, rcond=None)
        coefs[y] = [float(v) for v in c]
    return coefs


def team_pred(df, coefs, key):
    c = coefs[key]
    base = {"t_tgt": "tm_t_tgt", "t_car": "tm_t_car", "t_att": "tm_t_att"}[key]
    b = df[base].values
    sp = df.tspread.fillna(0).values; tot = df.total.fillna(44).values
    v = c[0] + c[1] * b + c[2] * sp + c[3] * tot
    # no as-of team games yet (week 1): league average attempts with the Vegas tilt
    lg = {"t_tgt": 33.0, "t_car": 26.0, "t_att": 34.0}[key]
    v = np.where(np.isnan(b), c[0] + c[1] * lg + c[2] * sp + c[3] * tot, v)
    return np.maximum(v, 5.0)


# ----------------------------------------------------------------------------- STRUCT
DEFAULT = dict(
    # share blend (short vs long EWMA) and vacated redistribution
    a_short=0.5, a_vac=0.5,
    # efficiency shrinkage (pseudo-opportunities)
    k_cr=40.0, k_ypt=60.0, k_ypc=80.0, k_ypa=150.0, k_int=200.0,
    # touchdown share: weight of the end-zone / goal-line share vs the plain share
    w_ez=0.5, w_gl=0.5, k_td=6.0,
    # opponent elasticities
    e_def=0.5, e_td=0.5,
    # prior strength in games (per position) and prior-season weight vs ADP
    P_QB=4.0, P_RB=3.0, P_WR=3.0, P_TE=3.0, w_prev=0.5,
    # injury status multipliers
    m_q=0.85, m_lp=0.95,
    # QB
    qb_rush_k=30.0,
)
LEAGUE = {}   # filled by fit_league(): position-level per-opportunity rates


def fit_league(df):
    L = {}
    for p in POS4:
        m = df.pos == p
        s = df[m]
        L[p] = dict(cr=s.sum_rec.sum() / max(1, s.sum_tgt.sum()), ypt=s.sum_rcy.sum() / max(1, s.sum_tgt.sum()),
                    ypc=s.sum_ry.sum() / max(1, s.sum_car.sum()), ypa=s.sum_py.sum() / max(1, s.sum_att.sum()),
                    intr=s.sum_int.sum() / max(1, s.sum_att.sum()), tdt=s.sum_rctd.sum() / max(1, s.sum_tgt.sum()),
                    tdc=s.sum_rtd.sum() / max(1, s.sum_car.sum()))
    return L


def struct_predict(df, prm, curve, tcoef, L):
    """returns the STRUCT projection (half-PPR) for every row of df; df must be an as-of table"""
    n = len(df); pos = df.pos.values
    g = df.g.fillna(0).values.astype(float)
    nan = lambda c: df[c].values.astype(float) if c in df else np.full(n, np.nan)
    def blend(a, b):
        a = nan(a); b = nan(b); w = prm["a_short"]
        out = w * a + (1 - w) * b
        out = np.where(np.isnan(a), b, np.where(np.isnan(b), a, out))
        return out
    # --- team volume for this game
    T_tgt = team_pred(df, tcoef, "t_tgt"); T_car = team_pred(df, tcoef, "t_car"); T_att = team_pred(df, tcoef, "t_att")
    imp = df.implied.fillna(22).values
    T_ptd = np.maximum(0.2, tcoef["t_ptd"][0] + tcoef["t_ptd"][1] * imp); T_rtd = np.maximum(0.1, tcoef["t_rtd"][0] + tcoef["t_rtd"][1] * imp)
    # as-of team pass/rush TD lean (how this offense scores), shrunk toward the Vegas-implied split
    tmg = df.tm_games.fillna(0).values
    lean_p = np.where(tmg > 0, (nan("tm_t_ptd") * tmg + T_ptd * 4) / (tmg + 4), T_ptd)
    lean_r = np.where(tmg > 0, (nan("tm_t_rtd") * tmg + T_rtd * 4) / (tmg + 4), T_rtd)
    T_ptd = T_ptd * np.where(tmg > 0, (lean_p / np.maximum(0.05, lean_p + lean_r)) / (T_ptd / (T_ptd + T_rtd)), 1.0) ** 0.5
    T_rtd = T_rtd * np.where(tmg > 0, (lean_r / np.maximum(0.05, lean_p + lean_r)) / (T_rtd / (T_ptd + T_rtd)), 1.0) ** 0.5
    # --- shares
    vac_t = df.vac_tsh.fillna(0).values; vac_c = df.vac_csh.fillna(0).values
    tsh = blend("tsh_s", "tsh_l") * (1 + prm["a_vac"] * vac_t)
    csh = blend("csh_s", "csh_l") * (1 + prm["a_vac"] * vac_c)
    ezt = blend("ezt_s", "ezt_l"); glc = blend("glc_s", "glc_l")
    # TD shares: blend of the end-zone / goal-line share (noisy) with the plain share, shrunk by opportunities seen
    s_ez = df.sum_ez_tgt.fillna(0).values; s_gl = df.sum_i10_car.fillna(0).values
    w_ez = prm["w_ez"] * s_ez / (s_ez + prm["k_td"]); w_gl = prm["w_gl"] * s_gl / (s_gl + prm["k_td"])
    tdsh_p = np.where(np.isnan(ezt), tsh, w_ez * ezt + (1 - w_ez) * tsh)
    tdsh_r = np.where(np.isnan(glc), csh, w_gl * glc + (1 - w_gl) * csh)
    # --- efficiency, shrunk toward the position rate
    def shrink(num, den, k, lkey):
        num = df[num].fillna(0).values; den = df[den].fillna(0).values
        lg = np.array([L[p][lkey] for p in pos])
        return (num + k * lg) / (den + k)
    cr = shrink("sum_rec", "sum_tgt", prm["k_cr"], "cr"); ypt = shrink("sum_rcy", "sum_tgt", prm["k_ypt"], "ypt")
    ypc = shrink("sum_ry", "sum_car", prm["k_ypc"], "ypc"); ypa = shrink("sum_py", "sum_att", prm["k_ypa"], "ypa")
    intr = shrink("sum_int", "sum_att", prm["k_int"], "intr")
    # --- opponent (as-of zone rates; 1.0 = league)
    e = prm["e_def"]; et = prm["e_td"]
    z_rec = np.where(pos == "RB", nan("z_rb_ypt"), np.where(pos == "TE", nan("z_te_ypt"), nan("z_wr_s")))
    z_rec = np.nan_to_num(z_rec, nan=1.0) ** e
    z_run = np.nan_to_num(nan("z_rb_ypc"), nan=1.0) ** e; z_pass = np.nan_to_num(nan("z_qb_ypa"), nan=1.0) ** e
    z_ptd = np.nan_to_num(nan("z_ptd"), nan=1.0) ** et; z_rtd = np.nan_to_num(nan("z_rtd"), nan=1.0) ** et
    # --- evidence points
    exp_tgt = np.nan_to_num(tsh, nan=0.0) * T_tgt; exp_car = np.nan_to_num(csh, nan=0.0) * T_car
    rec_pts = exp_tgt * (0.5 * cr + 0.1 * ypt * z_rec) + 6 * np.nan_to_num(tdsh_p, nan=0.0) * T_ptd * z_ptd
    run_pts = exp_car * 0.1 * ypc * z_run + 6 * np.nan_to_num(tdsh_r, nan=0.0) * T_rtd * z_rtd
    ev = rec_pts + run_pts
    # QB: pass attempts = his as-of share of team attempts (starter ~ 1) x team attempts
    qb = pos == "QB"
    attsh = blend("attsh_s", "attsh_l"); attsh = np.where(np.isnan(attsh), 1.0, np.clip(attsh, 0, 1))
    exp_att = attsh * T_att
    qb_rush = np.nan_to_num(blend("car_s", "car_l"), nan=0.0) * 0.1 * ypc * z_run + 6 * np.nan_to_num(tdsh_r, nan=0.0) * T_rtd * z_rtd
    qb_pts = exp_att * (0.04 * ypa * z_pass - 2 * intr) + 4 * attsh * T_ptd * z_ptd + qb_rush
    ev = np.where(qb, qb_pts, ev)
    # --- prior: ADP curve blended with last season's per-game level (same team, >= 6 games)
    pr_adp = adp_ppg(df, curve)
    p_ppg = nan("p_ppg"); p_g = nan("p_g")
    ok = (~np.isnan(p_ppg)) & (p_g >= 6)
    wp = prm["w_prev"] * np.where(df.same_team.values == 1, 1.0, 0.6)
    prior = np.where(ok, wp * p_ppg + (1 - wp) * pr_adp, pr_adp)
    has_adp = ~np.isnan(df.adp.values) & (df.adp.values <= 250)
    prior = np.where(ok | has_adp, prior, np.minimum(prior, 4.0))   # unknown player with no history: low
    # --- combine by effective games (long EWMA weight mass)
    Pv = np.array([prm["P_" + p] for p in pos])
    geff = np.array([sum(0.5 ** (i / 10.0) for i in range(int(x))) for x in g])
    proj = (Pv * prior + geff * ev) / (Pv + geff)
    proj = np.where(g == 0, prior, proj)
    # --- injury status
    gs = df.gs.fillna("").values; pr_ = df.pr.fillna("").values
    proj = proj * np.where(gs == "Questionable", prm["m_q"], 1.0) * np.where((gs == "") & (pr_ == "LP"), prm["m_lp"], 1.0)
    return np.maximum(proj, 0.3), dict(ev=ev, prior=prior, exp_tgt=exp_tgt, exp_car=exp_car, T_tgt=T_tgt, T_car=T_car)


# ----------------------------------------------------------------------------- grading
def importance(df, curve):
    """Jack's weights: the ADP-curve level (preseason, never the actual) cubed, normalised within position; unknown ADP = low"""
    lv = adp_ppg(df, curve)
    w = np.zeros(len(df))
    for p in POS4:
        m = (df.pos == p).values
        ref = np.nanmean(lv[m & (df.adp.values <= 150)]) if (m & (df.adp.values <= 150)).any() else np.nanmean(lv[m])
        w[m] = np.maximum(0.05, lv[m] / ref) ** 3
    return w


def band_of(adp):
    a = np.where(np.isnan(adp), 9999, adp)
    out = np.full(len(a), "151+", dtype=object)
    for name, lo, hi in BANDS:
        out[(a > lo) & (a <= hi)] = name
    return out


def grade(df, pred, w=None, min_rows=8, label=""):
    """one grading row: weighted MAE/MSE, Spearman per (season, week, pos) averaged, top-N hit rates, pairwise order."""
    act = df.act.values; pred = np.asarray(pred, float)
    m = ~np.isnan(pred) & ~np.isnan(act)
    w = np.ones(len(df)) if w is None else w
    out = dict(label=label, n=int(m.sum()))
    if m.sum() == 0 or w[m].sum() == 0:
        out.update(mae=np.nan, mae_raw=np.nan, bias=np.nan, rho=np.nan, groups=0, top6=np.nan, top12=np.nan, top24=np.nan, top36=np.nan, pair_acc=np.nan, pairs=0)
        return out
    out["mae"] = float(np.average(np.abs(pred[m] - act[m]), weights=w[m]))
    out["mae_raw"] = float(np.mean(np.abs(pred[m] - act[m])))
    out["bias"] = float(np.average(pred[m] - act[m], weights=w[m]))
    rhos = []; hits = defaultdict(list); pair_ok = pair_n = 0
    keys = list(zip(df.season.values, df.week.values, df.pos.values))
    groups = defaultdict(list)
    for i in np.where(m)[0]:
        groups[keys[i]].append(i)
    for k, ix in groups.items():
        if len(ix) < min_rows:
            continue
        ix = np.array(ix)
        a = act[ix]; p = pred[ix]
        r = spearmanr(a, p).correlation
        if not np.isnan(r):
            rhos.append(r)
        ra = rankdata(-a); rp = rankdata(-p)
        for N in (6, 12, 24, 36):
            if len(ix) >= N:
                top_a = set(np.where(ra <= N)[0]); top_p = set(np.where(rp <= N)[0])
                hits[N].append(len(top_a & top_p) / N)
        # pairwise order among the top half by projection (start/sit pairs)
        order = np.argsort(-p)[: max(2, len(ix) // 2)]
        for i_ in range(len(order)):
            for j_ in range(i_ + 1, len(order)):
                x, y = order[i_], order[j_]
                if abs(p[x] - p[y]) < 1.0 or a[x] == a[y]:
                    continue
                pair_n += 1; pair_ok += int((p[x] > p[y]) == (a[x] > a[y]))
    out["rho"] = float(np.mean(rhos)) if rhos else np.nan
    out["groups"] = len(rhos)
    for N in (6, 12, 24, 36):
        out[f"top{N}"] = float(np.mean(hits[N])) if hits[N] else np.nan
    out["pair_acc"] = pair_ok / pair_n if pair_n else np.nan; out["pairs"] = pair_n
    return out


def grade_table(df, preds, curve, by_band=True):
    """preds = {label: array}; rows for every pos (and band) x model"""
    w = importance(df, curve)
    rows = []
    band = band_of(df.adp.values)
    for lab, p in preds.items():
        for pos in POS4 + ("ALL",):
            m = (df.pos.values == pos) if pos != "ALL" else np.ones(len(df), bool)
            r = grade(df[m], p[m], w[m], label=lab); r["pos"] = pos; r["band"] = "all"; rows.append(r)
            top = m & (df.adp.values <= 150)
            r = grade(df[top], p[top], w[top], label=lab); r["pos"] = pos; r["band"] = "top150"; rows.append(r)
            if by_band:
                for name, lo, hi in BANDS:
                    mm = m & (band == name)
                    if mm.sum() >= 30:
                        r = grade(df[mm], p[mm], w[mm], min_rows=4, label=lab); r["pos"] = pos; r["band"] = name; rows.append(r)
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- fitting STRUCT
def fit_struct(train, curve, tcoef, L, start=None, maxiter=400, verbose=True):
    prm = dict(DEFAULT); prm.update(start or {})
    w = importance(train, curve)
    top = (train.adp.values <= 150)
    keys = [k for k in prm if k not in ()]
    x0 = np.array([math.log(max(1e-6, prm[k])) for k in keys])
    hist = []

    def loss(x):
        p = {k: math.exp(v) for k, v in zip(keys, x)}
        for k in ("a_short", "a_vac", "w_ez", "w_gl", "e_def", "e_td", "w_prev", "m_q", "m_lp"):
            p[k] = min(p[k], 1.0) if k != "a_vac" else min(p[k], 1.5)
        pred, _ = struct_predict(train, p, curve, tcoef, L)
        err = (pred - train.act.values) ** 2
        return float(np.average(err[top], weights=w[top]))

    best = minimize(loss, x0, method="Powell", options=dict(maxiter=maxiter, xtol=1e-2, ftol=1e-4, disp=False))
    p = {k: math.exp(v) for k, v in zip(keys, best.x)}
    for k in ("a_short", "a_vac", "w_ez", "w_gl", "e_def", "e_td", "w_prev", "m_q", "m_lp"):
        p[k] = min(p[k], 1.0) if k != "a_vac" else min(p[k], 1.5)
    if verbose:
        print("fit loss", round(loss(x0), 4), "->", round(best.fun, 4))
    return p


def calibrate(train, pred, curve):
    """per-position linear calibration (slope, intercept) fitted with importance weights on the top-150"""
    w = importance(train, curve); cal = {}
    for p in POS4:
        m = (train.pos.values == p) & (train.adp.values <= 150)
        X = np.vstack([np.ones(m.sum()), pred[m]]).T * np.sqrt(w[m])[:, None]
        y = train.act.values[m] * np.sqrt(w[m])
        c, *_ = np.linalg.lstsq(X, y, rcond=None)
        cal[p] = (float(c[0]), float(c[1]))
    return cal


def apply_cal(df, pred, cal):
    out = pred.copy()
    for p, (a, b) in cal.items():
        m = df.pos.values == p
        out[m] = a + b * pred[m]
    return np.maximum(out, 0.3)


# ----------------------------------------------------------------------------- GBM
GBM_FEATS = ["g", "adp", "rookie", "same_team", "implied", "opp_implied", "total", "tspread", "is_home", "indoor", "wind",
             "p_g", "p_ppg", "p_ppg8", "p_tgt", "p_car", "p_att", "p_snap", "p_tsh", "p_csh", "p_adot", "p_ypt", "p_ypc",
             "tm_games", "tm_t_att", "tm_t_car", "tm_t_tgt", "tm_t_rz_tgt", "tm_t_gl_car", "tm_t_ez_tgt", "tm_t_ptd", "tm_t_rtd", "tm_pts",
             "tm_implied", "tm_pass_rate", "tm_plays",
             "def_qb_rel", "def_rb_rel", "def_wr_rel", "def_te_rel", "z_rb_ypc", "z_rb_ypt", "z_wr_s", "z_te_ypt", "z_qb_ypa", "z_ptd", "z_rtd",
             "def_games", "vac_tsh", "vac_csh",
             "tsh_s", "csh_s", "rzt_s", "glc_s", "ezt_s", "ash_s", "snap_s", "ppg_s", "tgt_s", "car_s", "att_s", "attsh_s", "tshn_s", "cshn_s",
             "tsh_l", "csh_l", "rzt_l", "glc_l", "ezt_l", "ash_l", "snap_l", "ppg_l", "tgt_l", "car_l", "att_l", "attsh_l", "tshn_l", "cshn_l",
             "sum_tgt", "sum_rec", "sum_rcy", "sum_rctd", "sum_airy", "sum_car", "sum_ry", "sum_rtd", "sum_att", "sum_py", "sum_ptd", "sum_int",
             "sum_ez_tgt", "sum_i10_car", "sum_rz_tgt", "last_pts", "last_snap", "weeks_since", "gs_q", "pr_lp", "pr_dnp", "adp_ppg", "struct"]


def gbm_frame(df, curve, struct=None):
    X = df.copy()
    X["gs_q"] = (X.gs == "Questionable").astype(int); X["pr_lp"] = (X.pr == "LP").astype(int); X["pr_dnp"] = (X.pr == "DNP").astype(int)
    X["adp_ppg"] = adp_ppg(X, curve)
    X["struct"] = struct if struct is not None else np.nan
    for c in GBM_FEATS:
        if c not in X:
            X[c] = np.nan
    return X[GBM_FEATS].astype(float)


def fit_gbm(train, curve, struct_train=None, seed=0, params=None):
    import lightgbm as lgb
    models = {}
    w = importance(train, curve)
    for p in POS4:
        m = (train.pos.values == p)
        X = gbm_frame(train[m], curve, None if struct_train is None else struct_train[m])
        prm = dict(objective="regression", learning_rate=0.03, num_leaves=15, min_data_in_leaf=60, feature_fraction=0.7,
                   bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, verbose=-1, seed=seed, num_threads=4)
        prm.update(params or {})
        ds = lgb.Dataset(X, label=train.act.values[m], weight=np.sqrt(w[m]))
        models[p] = lgb.train(prm, ds, num_boost_round=600)
    return models


def gbm_predict(df, models, curve, struct=None):
    out = np.full(len(df), np.nan)
    for p, mdl in models.items():
        m = (df.pos.values == p)
        if m.any():
            out[m] = mdl.predict(gbm_frame(df[m], curve, None if struct is None else struct[m]))
    return np.maximum(out, 0.3)
