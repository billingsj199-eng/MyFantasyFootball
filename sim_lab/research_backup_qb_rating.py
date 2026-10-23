#!/usr/bin/env python3
"""
BACKUP-QB IMPACT RATING vs the flat qboutS dock (2026-10-23; Jack: "backup QBs are not all the same ... some sort of rating
system for each player based on impact"). RESEARCH ONLY - nothing here touches engine.js.

Question: when a team's regular QB is out, can a RATING of the specific backup (his own passing history vs the regular's,
rushing profile, continuity with this team, how this offense's pass volume moved in earlier starter-absent games) size the
WR dock better than the flat engine dock (x.85 ADP <= 60 / x.95 other, NC_SHADOW.qbOutWrDock)?

Two harnesses, as on 10-20 (project_backup_qb_wr_dock):
  (B) ENGINE-BASE shadow harness: X = _bt_ext/X_cache_ext2012_2025_tf.pkl (backtest_shadow_next.setup, SIM_BT_YEARS=2012-2025),
      next game = SN.shadow(X) (carries the flat dock), undocked = / (1 - d_eng); ROS = shadow rate x future context x
      (1 - d x share of future out weeks), target = mean of the remaining games (final week out, 4+ left, 3-10 played).
  (A) pbp WR harness (research_qbout_dock_ext.py rows rebuilt from its _tmp/qbx_cache/wr_<y>.pkl tables, QBX_Y0=2012 form).
Rating features come from _tmp/qbx_cache/qbgame_<y>.pkl (research_backup_qb_features.py) and the (A) team-week table.

Candidates on QB-out WR rows: (a) flat dock as shipped, (b) no dock, (c) rating-sized dock = undocked x r_hat where r_hat is a
ridge prediction of act / undocked from the backup's rating features, fitted on the TRAINING seasons of each fold (true LOYO /
forward), with shrink s toward the fold's flat level; (d) rating as a tilt on the flat dock. Grading: MSE + MAE, top-150
weighted, within-week WR rank rho, LOYO 2013-25 (fold table), forward 2016-25, ADP 1-60 split. Log: _tmp/backup_qb_rating.log
"""
import os, sys, math, pickle
os.environ.setdefault("SIM_BT_YEARS", "2012-2025")
from collections import defaultdict, Counter
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_ext as BX
import backtest_shadow_next as SN
CACHE = os.path.join(HERE, "_tmp", "qbx_cache")
LOG = open(os.path.join(HERE, "_tmp", "backup_qb_rating.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()
YEARS = list(range(2012, 2026)); LOY = [y for y in YEARS if y >= 2013]; FWY = [y for y in YEARS if y >= 2016]
REPL_K = 120   # dropbacks of shrink toward replacement level for every rate
DECAY = 0.6    # weight of a season k years back = DECAY^k (this season = 1)

# ---------------------------------------------------------------- QB histories -> rating features
def load_qbgames():
    Q = pd.concat([pd.read_pickle(os.path.join(CACHE, f"qbgame_{y}.pkl")) for y in YEARS], ignore_index=True)
    Q["t"] = Q.season * 100 + Q.week
    Q["fp"] = 0.04 * Q.pyds + 4 * Q.ptd - 1 * Q["int"] + 0.1 * Q.rush_yds + 6 * Q.rush_td
    Q["fpp"] = 0.04 * Q.pyds + 4 * Q.ptd - 1 * Q["int"]
    Q["posteam"] = Q.posteam.replace({"LA": "LAR", "STL": "LAR", "SD": "LAC", "OAK": "LV"})
    return Q
Q = load_qbgames()
QB_ROWS = {pid: g.sort_values("t") for pid, g in Q.groupby("pid")}
# replacement level = pooled rates of passers with under 300 career dropbacks at the time (computed once on the whole table)
_first = Q.sort_values("t").groupby("pid").cumcount()
_cum = Q.sort_values("t").groupby("pid").db.cumsum() - Q.sort_values("t").db
_low = Q.loc[_cum.index[_cum.values < 300]]
REPL = dict(epa=_low.epa.sum() / _low.db.sum(), fpp=_low.fpp.sum() / _low.db.sum(), yds=_low.pyds.sum() / _low.db.sum(),
            cpoe=(_low.comp.sum() - _low.cp_sum.sum()) / max(1, _low.cp_n.sum()), adot=_low.ay.sum() / max(1, _low.nay.sum()),
            sack=_low.sack.sum() / _low.db.sum(), rush=_low.rush_yds.sum() / max(1, (_low.db >= 10).sum()))
LEAGUE = dict(epa=Q.epa.sum() / Q.db.sum(), fpp=Q.fpp.sum() / Q.db.sum(), yds=Q.pyds.sum() / Q.db.sum(), cpoe=0.0, adot=Q.ay.sum() / Q.nay.sum(), sack=Q.sack.sum() / Q.db.sum())
_hist_cache = {}
def qb_hist(pid, year, wk, tm=None):
    """season-decayed rates from every passer-game BEFORE (year, wk), shrunk toward replacement over REPL_K dropbacks"""
    key = (pid, year, wk)
    if key in _hist_cache: return _hist_cache[key]
    g = QB_ROWS.get(pid)
    out = dict(db=0.0, games=0, epa=REPL["epa"], fpp=REPL["fpp"], yds=REPL["yds"], cpoe=REPL["cpoe"], adot=REPL["adot"], sack=REPL["sack"], rush=REPL["rush"], team_g=0, rec_fp=np.nan, starts_this=0)
    if g is None: _hist_cache[key] = out; return out
    h = g[g.t < year * 100 + wk]
    if not len(h): _hist_cache[key] = out; return out
    w = DECAY ** (year - h.season.values).astype(float)
    db = float(np.sum(w * h.db.values)); dbr = float(h.db.sum())
    sh = lambda num, den, repl: (num + REPL_K * repl) / (den + REPL_K)
    out["db"] = dbr; out["games"] = int((h.db >= 10).sum())
    out["epa"] = sh(float(np.sum(w * h.epa.values)), db, REPL["epa"])
    out["fpp"] = sh(float(np.sum(w * h.fpp.values)), db, REPL["fpp"])
    out["yds"] = sh(float(np.sum(w * h.pyds.values)), db, REPL["yds"])
    cpn = float(np.sum(w * h.cp_n.values)); out["cpoe"] = sh(float(np.sum(w * (h.comp.values - h.cp_sum.values))), cpn, 0.0) if cpn > 0 else 0.0
    nay = float(np.sum(w * h.nay.values)); out["adot"] = sh(float(np.sum(w * h.ay.values)), nay, REPL["adot"]) if nay > 0 else REPL["adot"]
    out["sack"] = sh(float(np.sum(w * h.sack.values)), db, REPL["sack"])
    gm = h[h.db >= 10]; wg = DECAY ** (year - gm.season.values).astype(float)
    out["rush"] = (float(np.sum(wg * gm.rush_yds.values)) + 6 * REPL["rush"]) / (float(wg.sum()) + 6) if len(gm) else REPL["rush"]
    if tm is not None: out["team_g"] = int(((h.posteam == tm) & (h.db >= 10)).sum())
    out["starts_this"] = int(((h.season == year) & (h.db >= 10)).sum())
    # recent form: fantasy points per dropback over his last 4 games with 10+ dropbacks
    last = gm.tail(4)
    out["rec_fp"] = float(last.fpp.sum() / max(1, last.db.sum())) if len(last) >= 2 else np.nan
    _hist_cache[key] = out; return out

def team_out_history(Q, TW):
    """per (year, tm, wk): this team's pass attempts in earlier starter-absent games vs its normal games (this + last season)"""
    team_games = Q[Q.db >= 10].sort_values("t").drop_duplicates(["game_id", "posteam"])[["season", "week", "posteam", "team_att", "team_plays", "t"]]
    twi = {(int(a), str(b), int(c)): bool(d) for a, b, c, d in zip(TW.year, TW.tm, TW.wk, TW.out)}
    team_games["out"] = [twi.get((int(s), str(t), int(w)), False) for s, t, w in zip(team_games.season, team_games.posteam, team_games.week)]
    by_tm = {t: g for t, g in team_games.groupby("posteam")}
    cache = {}
    def f(year, tm, wk):
        key = (year, tm, wk)
        if key in cache: return cache[key]
        g = by_tm.get(tm); r = dict(att_ratio=np.nan, n_out=0)
        if g is not None:
            h = g[(g.t < year * 100 + wk) & (g.season >= year - 1)]
            o = h[h.out]; i_ = h[~h.out]
            r["n_out"] = int(len(o))
            if len(o) >= 1 and len(i_) >= 3: r["att_ratio"] = float(o.team_att.mean() / max(1e-9, i_.team_att.mean()))
        cache[key] = r; return r
    return f

TW = pd.read_pickle(os.path.join(CACHE, "teamweek_2012.pkl"))
TWD = {(int(a), str(b), int(c)): (bool(o), r, s, d, ic) for a, b, c, o, r, s, d, ic in zip(TW.year, TW.tm, TW.wk, TW.out, TW.reg, TW.stq, TW.dq, TW.injc)}
team_hist = team_out_history(Q, TW)
FEATS = ["d_epa", "d_fpp", "d_yds", "d_cpoe", "d_adot", "d_sack", "d_rush", "b_fpp", "b_epa", "b_rush", "b_exp", "b_team_g", "b_starts", "b_rec", "att_ratio", "r_fpp"]
def features(year, tm, wk):
    """rating features for a QB-out team-week; None when the team-week is not a known outage"""
    rec = TWD.get((year, tm, wk))
    if not rec or not rec[0] or not isinstance(rec[1], str) or not isinstance(rec[2], str): return None
    reg, stq = rec[1], rec[2]
    R = qb_hist(reg, year, wk, tm); B = qb_hist(stq, year, wk, tm); th = team_hist(year, tm, wk)
    f = dict(d_epa=B["epa"] - R["epa"], d_fpp=B["fpp"] - R["fpp"], d_yds=B["yds"] - R["yds"], d_cpoe=B["cpoe"] - R["cpoe"], d_adot=B["adot"] - R["adot"], d_sack=B["sack"] - R["sack"],
             d_rush=B["rush"] - R["rush"], b_fpp=B["fpp"], b_epa=B["epa"], b_rush=B["rush"], b_exp=math.log1p(B["db"]), b_team_g=math.log1p(B["team_g"]), b_starts=B["starts_this"],
             b_rec=(B["rec_fp"] - B["fpp"]) if not np.isnan(B["rec_fp"]) else 0.0, att_ratio=th["att_ratio"] if not np.isnan(th["att_ratio"]) else 1.0, r_fpp=R["fpp"])
    f["_names"] = (reg, stq, B["db"], R["db"]); return f

# ---------------------------------------------------------------- grading machinery
def ridge_fit(Xm, y, w, lam):
    mu = np.average(Xm, axis=0, weights=w); sd = np.sqrt(np.average((Xm - mu) ** 2, axis=0, weights=w)) + 1e-9
    Z = (Xm - mu) / sd; ym = np.average(y, weights=w)
    A = (Z * w[:, None]).T @ Z + lam * np.eye(Z.shape[1]); b = (Z * w[:, None]).T @ (y - ym)
    beta = np.linalg.solve(A, b)
    return dict(mu=mu, sd=sd, ym=ym, beta=beta)
def ridge_pred(m, Xm): return m["ym"] + ((Xm - m["mu"]) / m["sd"]) @ m["beta"]

def grade(title, base_fam, mrow, okm, act, year, wt, top150, pos, wk, fitters, star, adp_lo=None):
    """base_fam: {'engine': pred, 'no dock': pred}; fitters: {label: fn(train_years) -> pred array (full length, NaN outside rows)}.
    For fitted candidates the fold prediction is fn(train)[test rows]. Bar: pooled MSE < -0.3%, 70% of folds, forward < 0 and 70%, top-150 <= +0.1%."""
    mse = lambda q, m: float(np.mean((q[m] - act[m]) ** 2)) if m.any() else np.nan
    mae = lambda q, m: float(np.mean(np.abs(q[m] - act[m]))) if m.any() else np.nan
    wms = lambda q, m: float(np.average((q[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    def rho(q, m):
        gr = defaultdict(list)
        for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        rh = [np.corrcoef(rankdata(act[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]
        return float(np.mean(rh)) if rh else np.nan
    b0 = base_fam["engine"]; tm = mrow & okm
    P(); P(f"  {title}   (rows {int(tm.sum())}, {int((tm & star).sum())} ADP 1-60 / prior-top-25; act/engine {act[tm].sum()/b0[tm].sum():.3f}, act/undocked {act[tm].sum()/base_fam['no dock'][tm].sum():.3f})")
    P(f"    {'candidate':38s} {'pooled MSE':>11s} {'MAE':>8s} {'LOYO MSE':>9s} {'folds':>6s} {'LOYO MAE':>9s} {'top150w':>8s} {'rank':>7s} {'FWD MSE':>8s} {'folds':>6s} {'FWD MAE':>8s} {'star MSE':>9s} {'other MSE':>10s}")
    rows_out = {}
    def fold_pred(fn, folds):
        pr = b0.copy()
        for tr, te in folds:
            p_ = fn(tr); m = (year == te) & tm; pr[m] = p_[m]
        return pr
    loyo_folds = [([y for y in YEARS if y != t], t) for t in LOY]; fwd_folds = [([y for y in YEARS if y < t], t) for t in FWY]
    cands = dict(base_fam); cands.update({k: None for k in fitters})
    for lab in cands:
        if lab == "engine": continue
        if cands[lab] is not None:
            fixed = cands[lab]; prL = fixed; prF = fixed
        else:
            prL = fold_pred(fitters[lab], loyo_folds); prF = fold_pred(fitters[lab], fwd_folds)
        temL = np.isin(year, LOY); temF = np.isin(year, FWY)
        wl = sum(1 for t in LOY if (tm & (year == t)).sum() >= 5 and mse(prL, tm & (year == t)) < mse(b0, tm & (year == t)) - 1e-12); nl = sum(1 for t in LOY if (tm & (year == t)).sum() >= 5)
        wf = sum(1 for t in FWY if (tm & (year == t)).sum() >= 5 and mse(prF, tm & (year == t)) < mse(b0, tm & (year == t)) - 1e-12); nf = sum(1 for t in FWY if (tm & (year == t)).sum() >= 5)
        dL = 100 * (mse(prL, tm & temL) / mse(b0, tm & temL) - 1); dLa = 100 * (mae(prL, tm & temL) / mae(b0, tm & temL) - 1)
        dF = 100 * (mse(prF, tm & temF) / mse(b0, tm & temF) - 1); dFa = 100 * (mae(prF, tm & temF) / mae(b0, tm & temF) - 1)
        dW = 100 * (wms(prL, tm & temL & top150) / wms(b0, tm & temL & top150) - 1)
        # rank: the whole top-150 WR board in the LOYO seasons (only out rows move)
        board = okm & top150 & (pos == "WR") & temL
        q_ = b0.copy(); q_[tm] = prL[tm]; dR = rho(q_, board) - rho(b0, board)
        dS = 100 * (mse(prL, tm & temL & star) / mse(b0, tm & temL & star) - 1); dO = 100 * (mse(prL, tm & temL & ~star) / mse(b0, tm & temL & ~star) - 1)
        pooled = 100 * (mse(prL, tm) / mse(b0, tm) - 1) if cands[lab] is not None else float("nan")
        ok = dL < -0.3 and wl >= math.ceil(0.7 * nl) and dF < 0 and wf >= math.ceil(0.7 * nf) and dW <= 0.1
        P(f"    {lab:38s} {pooled:+10.2f}% {dLa:+7.2f}% {dL:+8.2f}% {wl:2d}/{nl:<3d} {dLa:+8.2f}% {dW:+7.2f}% {dR:+7.4f} {dF:+7.2f}% {wf:2d}/{nf:<3d} {dFa:+7.2f}% {dS:+8.2f}% {dO:+9.2f}%   {'PASS' if ok else 'fail'}")
        rows_out[lab] = dict(prL=prL, dL=dL, wl=wl, nl=nl, dF=dF, wf=wf, nf=nf, dW=dW, ok=ok)
    # fold table
    P("    per-season LOYO (MSE vs engine on the out rows; n):")
    labs = [k for k in rows_out]
    P("      " + "year ".rjust(6) + "   n " + " ".join(f"{k[:16]:>17s}" for k in labs))
    for t in LOY:
        m = tm & (year == t)
        if m.sum() < 5: continue
        P("      " + f"{t:>6d} {int(m.sum()):4d} " + " ".join(f"{100*(mse(rows_out[k]['prL'], m)/mse(b0, m)-1):+16.2f}%" for k in labs))
    return rows_out

def univariate(title, feats_m, y, year, mrow):
    P(); P(f"  {title}: act / undocked by tercile of each rating feature (seasons with the top tercile under the bottom)")
    for f in FEATS:
        v = feats_m[f]; m = mrow & ~np.isnan(v) & ~np.isnan(y)
        if m.sum() < 60: continue
        q1, q2 = np.nanquantile(v[m], [1 / 3, 2 / 3]); lo = m & (v <= q1); hi = m & (v > q2); mid = m & ~lo & ~hi
        yrs = [t for t in YEARS if (lo & (year == t)).sum() >= 3 and (hi & (year == t)).sum() >= 3]
        under = sum(1 for t in yrs if y[hi & (year == t)].mean() < y[lo & (year == t)].mean())
        P(f"    {f:10s} low {y[lo].mean():.3f} (n {int(lo.sum())})  mid {y[mid].mean():.3f}  high {y[hi].mean():.3f} (n {int(hi.sum())})  | high < low in {under}/{len(yrs)} seasons | r {np.corrcoef(v[m], y[m])[0,1]:+.3f}")

def make_fitters(Xf, y, w, rows, flat_level, lam_list=(10.0, 40.0), shrink=(0.5, 1.0), tilt=None):
    """fitters on the rows mask: ridge of y (act/undocked) on FEATS, prediction applied as undocked x r_hat (clip .55-1.15).
    flat_level(train_years) -> per-row flat prediction ratio (engine dock) used for the shrink target / tilt."""
    out = {}
    und = rows["und"]; year = rows["year"]; tm = rows["tm"]
    for lam in lam_list:
        for s in shrink:
            def fn(train, lam=lam, s=s):
                mtr = tm & np.isin(year, train) & ~np.isnan(y)
                m = ridge_fit(Xf[mtr], y[mtr], w[mtr], lam)
                r = ridge_pred(m, Xf); fl = flat_level(train)
                r = fl + s * (r - m["ym"]) + (m["ym"] - fl) * s   # shrink the whole rating (level + tilt) toward the flat engine ratio
                return und * np.clip(r, 0.55, 1.15)
            out[f"rating lam {lam:g} s {s}"] = fn
    # tilt on the flat dock: engine x (r_hat / fold mean r_hat)^a
    for lam in (10.0,):
        for a in (0.5, 1.0):
            def fn2(train, lam=lam, a=a):
                mtr = tm & np.isin(year, train) & ~np.isnan(y)
                m = ridge_fit(Xf[mtr], y[mtr], w[mtr], lam); r = ridge_pred(m, Xf)
                return rows["eng"] * np.clip(r / m["ym"], 0.7, 1.3) ** a
            out[f"flat x (rating/mean)^{a}"] = fn2
    # FRAMINGS (Jack 10-23: "Josh Allen to an above-average backup is a larger downgrade than a bad starter to a mid backup"):
    #   c1 = the backup's ABSOLUTE quality only; c2 = the starter-minus-backup GAP only; c3 = gap + continuity; full = everything above
    SUB = {"c1 backup absolute (fpp, epa, rush, exp)": ["b_fpp", "b_epa", "b_rush", "b_exp"],
           "c2 quality GAP only (d_fpp, d_epa, d_rush)": ["d_fpp", "d_epa", "d_rush"],
           "c3 gap + continuity": ["d_fpp", "d_epa", "b_team_g", "b_starts"],
           "c4 gap, linear (d_fpp only, lam 3)": ["d_fpp"]}
    for lab, cols_ in SUB.items():
        cols = [FEATS.index(c) for c in cols_]
        def fn3(train, cols=cols, lam=(3.0 if lab.startswith("c4") else 10.0)):
            mtr = tm & np.isin(year, train) & ~np.isnan(y)
            m = ridge_fit(Xf[mtr][:, cols], y[mtr], w[mtr], lam); r = ridge_pred(m, Xf[:, cols]); fl = flat_level(train)
            return und * np.clip(fl + (r - m["ym"]), 0.55, 1.15)   # fold's flat level + the rating's tilt around its own mean
        out[lab] = fn3
    # c5 STARTER-QUALITY CELLS (the gap where the backup is ~replacement anyway): dock by the LOST starter's fantasy pts per dropback
    # tercile (cuts from the training rows) x star / other; the cell sizes are picked on the training rows (star and other separately).
    star = rows["star"]; rq = Xf[:, FEATS.index("r_fpp")]
    def fn5(train, lam=None):
        mtr = tm & np.isin(year, train) & ~np.isnan(y)
        c1, c2 = np.quantile(rq[mtr], [1 / 3, 2 / 3]); ter = np.where(rq <= c1, 0, np.where(rq <= c2, 1, 2))
        best = {}
        for grp, msk, grid in (("star", star, [(e, m_, w_) for e in (0.15, 0.20, 0.25, 0.30) for m_ in (0.10, 0.15, 0.20) for w_ in (0.0, 0.05, 0.10)]),
                               ("other", ~star, [(e, m_, w_) for e in (0.05, 0.10, 0.15) for m_ in (0.0, 0.05, 0.10) for w_ in (0.0, 0.05)])):
            mm = mtr & msk
            def err(cell):
                d = np.select([ter == 2, ter == 1], [cell[0], cell[1]], cell[2]); pr = und * (1 - d)
                return float(np.average((pr[mm] - (y * und)[mm]) ** 2, weights=w[mm])) if mm.sum() else np.inf
            best[grp] = min(grid, key=err)
        d = np.where(star, np.select([ter == 2, ter == 1], [best["star"][0], best["star"][1]], best["star"][2]), np.select([ter == 2, ter == 1], [best["other"][0], best["other"][1]], best["other"][2]))
        fn5.last = (best, (c1, c2))
        return und * (1 - d)
    out["c5 starter-quality cells (elite/mid/weak x star/other)"] = fn5
    # c6 continuous gap: d = d_eng x clip(1 + k x z(starter fpp), .25, 2.5), k picked on the training rows
    def fn6(train):
        mtr = tm & np.isin(year, train) & ~np.isnan(y)
        mu, sd = rq[mtr].mean(), rq[mtr].std() + 1e-9; z = (rq - mu) / sd
        d0 = 1 - flat_level(train)
        def err(k):
            pr = und * (1 - np.clip(d0 * np.clip(1 + k * z, 0.25, 2.5), 0, 0.5))
            return float(np.average((pr[mtr] - (y * und)[mtr]) ** 2, weights=w[mtr]))
        k = min((0.0, 0.25, 0.5, 0.75, 1.0, 1.5), key=err); fn6.last = k
        return und * (1 - np.clip(d0 * np.clip(1 + k * z, 0.25, 2.5), 0, 0.5))
    out["c6 flat x (1 + k z(starter quality))"] = fn6
    return out

def crosstab(title, Fm, y, year, mrow):
    """act / undocked by the STARTER's quality (r_fpp tercile) x the GAP (d_fpp tercile): does losing an elite starter hurt more?"""
    P(); P(f"  {title}: act / undocked, rows = starter quality (fantasy pts per dropback, history) x downgrade size (backup - starter)")
    r = Fm["r_fpp"]; d = Fm["d_fpp"]; m = mrow & ~np.isnan(r) & ~np.isnan(d) & ~np.isnan(y)
    if m.sum() < 60: return
    rq = np.nanquantile(r[m], [1 / 3, 2 / 3]); dq = np.nanquantile(d[m], [1 / 3, 2 / 3])
    rb = np.where(r <= rq[0], 0, np.where(r <= rq[1], 1, 2)); db = np.where(d <= dq[0], 0, np.where(d <= dq[1], 1, 2))
    P(f"    starter fpp terciles cut at {rq[0]:.3f} / {rq[1]:.3f}; gap terciles cut at {dq[0]:+.3f} / {dq[1]:+.3f} (more negative = bigger downgrade)")
    P("    " + "starter \\ gap".ljust(22) + "".join(f"{lab:>22s}" for lab in ("big downgrade", "mid", "small / upgrade")))
    for a, al in enumerate(("weak starter", "mid starter", "elite starter")):
        cells = []
        for b in range(3):
            mm = m & (rb == a) & (db == b)
            cells.append(f"{y[mm].mean():.3f} (n {int(mm.sum()):3d})" if mm.sum() >= 8 else "   -        ")
        P("    " + al.ljust(22) + "".join(f"{c:>22s}" for c in cells))
    for a, al in enumerate(("weak starter", "mid starter", "elite starter")):
        mm = m & (rb == a); yrs = [t for t in YEARS if (mm & (year == t)).sum() >= 4]
        P(f"    {al:14s} all gaps: act/undocked {y[mm].mean():.3f} (n {int(mm.sum())}); seasons under 1.0: {sum(1 for t in yrs if y[mm & (year == t)].mean() < 1)}/{len(yrs)}")

# ---------------------------------------------------------------- (B) engine-base harness
def harness_B():
    P("=" * 110); P(f"(B) ENGINE-BASE SHADOW HARNESS  {BX.describe()}")
    X = pickle.load(open(BX.ext_path("X_cache.pkl"), "rb")); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["team"]
    pid = X["A"]["pid"]
    C = pd.read_parquet(BX.ext_path("ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    tsh = colv("tgt_sh"); qbo_c = colv("qb_out") == 1
    finw = np.where(year <= 2020, 17, 18); top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in ("QB", "RB", "WR", "TE"):
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    N14 = SN.shadow(X); qbN = X["qbo"]; WR = pos == "WR"; star = adp <= 60
    d_eng = np.where(star, 0.15, 0.05)
    okN = (g >= 1) & (wk != finw) & (N14 >= 3)
    undN = np.where(WR & qbN, N14 / (1 - d_eng), N14)
    # rating features per row
    Fm = {f: np.full(n, np.nan) for f in FEATS}; matched = np.zeros(n, bool); who = {}
    for i in np.where(WR & qbN)[0]:
        f = features(int(year[i]), str(team[i]), int(wk[i]))
        if f is None: continue
        matched[i] = True
        for k in FEATS: Fm[k][i] = f[k]
        who[i] = f["_names"]
    P(f"  WR rows with the starter out, next game: {int((WR & qbN & okN).sum())}; rating matched on {int((matched & okN).sum())} (unmatched rows keep the engine number)")
    yN = np.where(undN > 0, act / np.where(undN > 0, undN, 1), np.nan); yN = np.clip(yN, 0, 3)
    rowsN = WR & qbN & okN & matched
    univariate("(B) next game", Fm, yN, year, rowsN); crosstab("(B) next game", Fm, yN, year, rowsN)
    crosstab("(B) next game, ADP 1-60 only", Fm, yN, year, rowsN & star)
    Xf = np.column_stack([Fm[f] for f in FEATS]); Xf = np.where(np.isnan(Xf), 0.0, Xf)
    # ridge coefficients on every season (design read)
    mtr = rowsN & ~np.isnan(yN); m_all = ridge_fit(Xf[mtr], yN[mtr], wt[mtr], 10.0)
    P("  ridge (all seasons, lam 10, top-150 weights) coefficients on standardized features, target act/undocked: " + ", ".join(f"{f} {b:+.3f}" for f, b in zip(FEATS, m_all["beta"])) + f"; mean {m_all['ym']:.3f}")
    flat_level = lambda train: np.where(star, 0.85, 0.95)
    rows = dict(und=undN, eng=N14, year=year, tm=rowsN, star=star)
    fit = make_fitters(Xf, yN, wt, rows, flat_level)
    resN = grade("(B) NEXT GAME: WR rows with the regular QB out", {"engine": N14, "no dock": undN}, rowsN, okN, act, year, wt, top150, pos, wk, fit, star)
    c5 = fit["c5 starter-quality cells (elite/mid/weak x star/other)"]; c5(YEARS); P(f"  c5 all-seasons pick: cells (elite, mid, weak) star / other = {c5.last[0]}, starter fpp cuts {c5.last[1][0]:.3f} / {c5.last[1][1]:.3f}")
    c6 = fit["c6 flat x (1 + k z(starter quality))"]; c6(YEARS); P(f"  c6 all-seasons pick: k = {c6.last}")
    rq_ = Xf[:, FEATS.index("r_fpp")]
    # ---- ROS: shadow rate x future context, dock x share of future out weeks (as the 10-20 harness) ----
    lam0 = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    rate = (X["Pw"] * X["prior"] + g * (lam0 * X["xf"] + (1 - lam0) * X["ppg_v"])) / np.maximum(X["Pw"] + g, 1e-9)
    seq = defaultdict(list)
    for i in range(n):
        if wk[i] != finw[i]: seq[(name[i], pos[i], int(year[i]))].append(i)
    T = np.full(n, np.nan); ctx = np.full(n, np.nan); futq = np.full(n, np.nan)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(X["layers"][ix], 0.5, 1.8); q_ = qbo_c[ix].astype(float)
        for a, i in enumerate(ix):
            if len(ix) - a >= 4: T[i] = a_[a:].mean(); ctx[i] = l_[a:].mean(); futq[i] = q_[a:].mean()
    okR = ~np.isnan(T) & (g >= 3) & (g <= 10) & (rate * ctx >= 3)
    S0 = rate * ctx; fq = np.nan_to_num(futq)
    rowsR = WR & qbo_c & (fq >= 0.4) & okR & matched
    engR = np.where(WR & qbo_c, S0 * (1 - d_eng * fq), S0)
    yR = np.where(S0 > 0, T / np.where(S0 > 0, S0, 1), np.nan)
    # rating dock for ROS: r_hat from the NEXT-GAME fit (the rating is about the backup, not the horizon), applied x future out share
    def ros_fitters():
        out = {}
        for lam in (10.0, 40.0):
            for s in (0.5, 1.0):
                def fn(train, lam=lam, s=s):
                    mtr_ = rowsN & np.isin(year, train) & ~np.isnan(yN)
                    m = ridge_fit(Xf[mtr_], yN[mtr_], wt[mtr_], lam); r = ridge_pred(m, Xf); fl = flat_level(train)
                    d = np.clip(1 - (fl + s * (r - fl)), 0, 0.45)
                    return np.where(WR & qbo_c, S0 * (1 - d * fq), S0)
                out[f"rating lam {lam:g} s {s}"] = fn
        def fn5r(train):   # starter-quality cells picked on the NEXT-GAME rows, applied x share of future out weeks
            c5(train); best, (c1, c2) = c5.last; ter = np.where(rq_ <= c1, 0, np.where(rq_ <= c2, 1, 2))
            d = np.where(star, np.select([ter == 2, ter == 1], [best["star"][0], best["star"][1]], best["star"][2]), np.select([ter == 2, ter == 1], [best["other"][0], best["other"][1]], best["other"][2]))
            return np.where(WR & qbo_c, S0 * (1 - d * fq), S0)
        out["c5 starter-quality cells (next-game fit)"] = fn5r
        return out
    # the ROS rating needs features on the ROS rows too (same team-week)
    for i in np.where(rowsR & ~matched)[0]: pass
    rows_ros = dict(und=S0, eng=engR, year=year, tm=rowsR)
    actR = act.copy();
    resR = grade("(B) REST OF SEASON (out now, 40%+ of the remaining games): WR rows", {"engine": engR, "no dock": S0}, rowsR, okR, T, year, wt, top150, pos, wk, ros_fitters(), star)
    # examples: 2025 rows with the biggest rating moves (one fit on 2012-24)
    m24 = rowsN & (year <= 2024) & ~np.isnan(yN); m_ = ridge_fit(Xf[m24], yN[m24], wt[m24], 10.0); r25 = ridge_pred(m_, Xf)
    ex = [i for i in np.where(rowsN & (year == 2025))[0]]
    ex.sort(key=lambda i: r25[i])
    P("  2025 examples (fit on 2012-24): rating r_hat (act/undocked predicted) vs flat, lowest / highest:")
    for i in ex[:6] + ex[-6:]:
        reg, stq, bdb, rdb = who[i]
        P(f"    wk {int(wk[i]):2d} {name[i]:22s} {team[i]:4s} ADP {adp[i]:5.0f}  flat {1-d_eng[i]:.2f}  rating {r25[i]:.3f}  undocked {undN[i]:5.2f} -> rating {undN[i]*np.clip(r25[i],.55,1.15):5.2f} (engine {N14[i]:5.2f}, actual {act[i]:5.1f})  backup {stq} db {bdb:.0f} / regular {reg} db {rdb:.0f}")
    return resN, resR

# ---------------------------------------------------------------- (A) pbp WR harness rows (rebuilt from research_qbout_dock_ext.py, QBX_Y0=2012 form)
def harness_A():
    P(); P("=" * 110); P("(A) PBP WR HARNESS 2013-25 (research_qbout_dock_ext.py rows rebuilt from its caches; prior-rank top 25 = star)")
    PBP = r"E:/MyFantasyFootball/pbp_cache"
    pl = pd.read_csv(os.path.join(PBP, "players.csv"), usecols=["gsis_id", "position"], low_memory=False); POS = dict(zip(pl.gsis_id, pl.position))
    S = {y: pd.read_pickle(os.path.join(CACHE, f"wr_{y}.pkl")) for y in YEARS}
    lastppg = {}
    for y in YEARS:
        rec = S[y]["rec"]; rec = rec[rec.pid.map(POS) == "WR"]
        gp = rec.groupby("pid").agg(g=("pts", "size"), ppg=("pts", "mean"))
        for q, r in gp.iterrows(): lastppg[(q, y)] = (r.g, r.ppg)
    wr_mean = float(np.mean([v[1] for k, v in lastppg.items() if v[0] >= 6]))
    rows = []
    for y in YEARS[1:]:
        rec = S[y]["rec"]; st = S[y]["st"]; rec = rec[rec.pid.map(POS) == "WR"].copy()
        starters = {(r.posteam, int(r.week)): (r.qb_id, r.qb_name) for r in st.itertuples()}
        passers = defaultdict(set)
        for r in S[y]["qball"].itertuples(): passers[(r.posteam, int(r.week))].add(r.qb_id)
        team_weeks = defaultdict(list)
        for (tm, w) in starters: team_weeks[tm].append(w)
        for tm in team_weeks: team_weeks[tm].sort()
        reg = {}; out = {}
        for tm, wks in team_weeks.items():
            cnt = defaultdict(int); last = {}
            for w in wks:
                r_ = max(cnt, key=lambda q: (cnt[q], last.get(q, 0))) if cnt and max(cnt.values()) >= 2 else None
                reg[(tm, w)] = r_; s_ = starters[(tm, w)][0]
                out[(tm, w)] = bool(r_ and s_ != r_ and r_ not in passers[(tm, w)])
                cnt[s_] += 1; last[s_] = w
        wkimp = rec.groupby("week").implied.mean().to_dict()
        prior_pts = {}
        for pid in rec.pid.unique():
            g0, p0 = lastppg.get((pid, y - 1), (0, None))
            prior_pts[pid] = (wr_mean + 0.8 * (p0 - wr_mean)) if g0 >= 6 else wr_mean * 0.7
        pr_rank = {pid: i + 1 for i, pid in enumerate(sorted(prior_pts, key=lambda q: -prior_pts[q]))}
        for pid, grp in rec.sort_values("week").groupby("pid"):
            grp = grp.reset_index(drop=True); pts = grp.pts.values; xf = grp.xfp.values; wks = grp.week.values.astype(int); tms = grp.posteam.values
            for a in range(len(grp)):
                w = wks[a]; tm = tms[a]
                vm = 1 + 0.25 * ((grp.implied.values[a] - wkimp.get(w, 22.0)) / wkimp.get(w, 22.0)) if pd.notna(grp.implied.values[a]) else 1.0
                o = out.get((tm, w), False)
                rows.append(dict(year=y, wk=w, pid=pid, name=grp.pname.values[a], tm=tm.replace("LA", "LAR") if tm == "LA" else tm, g=a, act=pts[a],
                                 ppg=float(pts[:a].mean()) if a else np.nan, xpg=float(xf[:a].mean()) if a else np.nan, prior=prior_pts[pid], prank=pr_rank[pid], vm=float(np.clip(vm, 0.7, 1.35)), out=o))
    R = pd.DataFrame(rows); n = len(R)
    g = R.g.values.astype(float); lam = np.maximum(0.25, 1 - 0.08 * np.maximum(g - 1, 0))
    ev = np.where(g > 0, lam * R.xpg.fillna(0).values + (1 - lam) * R.ppg.fillna(0).values, 0)
    rate = (8 * R.prior.values + g * ev) / (8 + g); base = rate * R.vm.values
    finw = np.where(R.year.values <= 2020, 17, 18); final = R.wk.values == finw
    act = R.act.values; year = R.year.values; wk = R.wk.values; outv = R.out.values
    okN = (g >= 1) & ~final & (base >= 3) & (R.prank.values <= 90)
    qin = okN & ~outv; lvl = act[qin].sum() / base[qin].sum(); baseN = base * lvl
    P(f"  WR player-weeks {n:,}; QB-out weeks {int(outv.sum()):,}; global level on QB-in rows {lvl:.3f}")
    star = R.prank.values <= 25; d_eng = np.where(star, 0.15, 0.05)
    engN = np.where(outv, baseN * (1 - d_eng), baseN); undN = baseN
    Fm = {f: np.full(n, np.nan) for f in FEATS}; matched = np.zeros(n, bool)
    tmv = R.tm.values
    for i in np.where(outv)[0]:
        f = features(int(year[i]), str(tmv[i]), int(wk[i]))
        if f is None: continue
        matched[i] = True
        for k in FEATS: Fm[k][i] = f[k]
    yN = np.clip(act / np.where(undN > 0, undN, 1), 0, 3)
    rowsN = outv & okN & matched
    P(f"  QB-out rows next game {int((outv & okN).sum())}, rating matched {int(rowsN.sum())}")
    univariate("(A) next game", Fm, yN, year, rowsN); crosstab("(A) next game", Fm, yN, year, rowsN); crosstab("(A) next game, prior top 25", Fm, yN, year, rowsN & star)
    Xf = np.column_stack([Fm[f] for f in FEATS]); Xf = np.where(np.isnan(Xf), 0.0, Xf)
    wt = np.where(R.prank.values <= 60, 1.0, 0.3)   # (A) has no ADP: prior-rank weight stands in for the top-150 weight
    pos = np.array(["WR"] * n); top = R.prank.values <= 60
    flat_level = lambda train: np.where(star, 0.85, 0.95)
    rows = dict(und=undN, eng=engN, year=year, tm=rowsN, star=star)
    fit = make_fitters(Xf, yN, wt, rows, flat_level)
    grade("(A) NEXT GAME: WR rows with the regular QB out (pbp harness)", {"engine": engN, "no dock": undN}, rowsN, okN, act, year, wt, top, pos, wk, fit, star)
    c5 = fit["c5 starter-quality cells (elite/mid/weak x star/other)"]; c5(YEARS); P(f"  c5 all-seasons pick: cells (elite, mid, weak) star / other = {c5.last[0]}, starter fpp cuts {c5.last[1][0]:.3f} / {c5.last[1][1]:.3f}")
    c6 = fit["c6 flat x (1 + k z(starter quality))"]; c6(YEARS); P(f"  c6 all-seasons pick: k = {c6.last}")

if __name__ == "__main__":
    P(f"backup-QB impact rating study {pd.Timestamp.now():%Y-%m-%d %H:%M}; replacement level: " + ", ".join(f"{k} {v:.3f}" for k, v in REPL.items()) + "; league: " + ", ".join(f"{k} {v:.3f}" for k, v in LEAGUE.items()))
    harness_B()
    harness_A()
    LOG.close()
