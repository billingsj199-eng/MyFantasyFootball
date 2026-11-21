#!/usr/bin/env python3
"""
2027 PRESEASON (IN-HOUSE) - games-played model, walk-forward 2015-2025. Jack 2026-11-21: "Yes, start it".

In-house rules: no outside projections (ESPN / Clay / FantasyPros); ADP is the BENCHMARK, never an input in the main version
(an ADP-informed variant is printed separately, labelled comparison only). Vegas win totals may stay.

Target: games with a stat line in weeks 1 .. last-1 (same definition as the prototype's PPG, so total = PPG x games).
Missed games are split by cause for the description: INJURY (on a reserve list - RES / PUP / NFI - that week, or listed
Out / Doubtful on the injury report) vs ROLE (on the active roster, not on the report, no stat line = healthy scratch /
no touches / buried) vs OFF-ROSTER (cut, practice squad, not on any roster).

Features, all known before the week-1 kickoff:
  position, age, age^2, experience, rookie, log draft pick, round 1 / 2, undrafted
  prior 1-3 seasons: games share, injury-missed share, role-missed share, weeks on a reserve list, injury-report Out weeks,
       touches per game, snap share in games played, share of team games with a 50%+ snap share
  role: week-1 depth-chart rank (1 / 2 / 3+ / none), team change
  preseason status: week-1 roster status (RES / PUP / NFI / SUS / not on the active roster), week-1 injury-report status
  QB job security: is QB1 on the week-1 chart, team drafted a QB in round 1 this year, his prior PPG
  team: de-vigged win-total expected wins

Models (per position, fit only on seasons before Y):
  FLAT   position mean games share            LAST   last season's games share (rookies: position rookie mean)
  RIDGE  ridge on the features (alpha 30)       GBM    gradient boosting, shallow, big leaves
  DIST   multinomial logistic (L2, C .1) on missed-game bins 0-1 / 2-3 / 4-7 / 8+  -> distribution + expected games
  MAIN = 0.5 RIDGE + 0.5 DIST (picked on the 2015-18 folds only, then frozen for 2019-25)
Then: season total = in-house PPG (ridge_stats from preseason_model) x games, re-graded vs ADP and the old games model.
Writes games_model.log and data/games_model_rows.parquet.
"""
import os, sys, time, warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM

DATA = PM.DATA; CACHE = PM.CACHE; POS4 = PM.POS4
LOG = None   # opened by main(); importing this module never truncates games_model.log
LOG_NAME = "games_model.log"
RNG = np.random.default_rng(17)
BINS = [(0, 1), (2, 3), (4, 7), (8, 99)]


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


# ------------------------------------------------------------------ availability history
def availability():
    """per (season, gsis): team games G, games with a stat, injury-missed, role-missed, off-roster, reserve weeks,
    report-Out weeks, snap share in played games, 50%+ snap games; plus week-1 roster + report status."""
    W = pd.read_parquet(os.path.join(DATA, "player_weeks.parquet"), columns=["season", "week", "pid", "team", "car", "tgt", "att"])
    TG = pd.read_parquet(os.path.join(DATA, "team_games.parquet"), columns=["season", "week", "team"])
    pl = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "pfr_id", "position"])
    pfr2g = dict(zip(pl.pfr_id, pl.gsis_id))
    rows = []; wk1 = {}
    for Y in range(2012, 2026):
        fw = PM.final_week(Y)
        tg = TG[(TG.season == Y) & (TG.week < fw)]
        team_weeks = tg.groupby("team").week.apply(set).to_dict()
        r = pd.read_parquet(os.path.join(CACHE, f"roster_weekly_{Y}.parquet"), columns=["team", "gsis_id", "week", "game_type", "status", "position"])
        r = r[(r.game_type == "REG") & r.gsis_id.notna() & r.position.isin(POS4 + ("FB",)) & (r.week < fw)]
        r["team"] = r.team.map(PM.tm)
        inj = pd.read_parquet(os.path.join(CACHE, f"injuries_{Y}.parquet"), columns=["game_type", "week", "gsis_id", "report_status"])
        inj = inj[(inj.game_type == "REG") & inj.gsis_id.notna()]
        rep = {(a, int(b)): c for a, b, c in zip(inj.gsis_id, inj.week, inj.report_status)}
        sc = pd.read_parquet(os.path.join(CACHE, f"snap_counts_{Y}.parquet"), columns=["game_type", "week", "pfr_player_id", "offense_snaps", "offense_pct"])
        sc = sc[sc.game_type == "REG"]; sc["pid"] = sc.pfr_player_id.map(pfr2g); sc = sc[sc.pid.notna()]
        snap = {(a, int(b)): (c, d) for a, b, c, d in zip(sc.pid, sc.week, sc.offense_snaps, sc.offense_pct)}
        stat = set(zip(W[W.season == Y].pid, W[W.season == Y].week))
        wy = W[W.season == Y]; touch = wy.groupby("pid").apply(lambda d: (d.car.sum() + d.tgt.sum(), len(d))).to_dict()
        st = {(a, int(b)): (c, t) for a, b, c, t in zip(r.gsis_id, r.week, r.status, r.team)}
        # week-1 status
        r1 = r[r.week == r.week.min()]
        for a, s_, t in zip(r1.gsis_id, r1.status, r1.team): wk1[(Y, a)] = (s_, t)
        for a, b, c in zip(inj.gsis_id, inj.week, inj.report_status):
            if b == 1: wk1.setdefault((Y, a), (None, None)); wk1[(Y, a)] = wk1[(Y, a)] + (c,) if len(wk1[(Y, a)]) == 2 else wk1[(Y, a)]
        pids = set(r.gsis_id) | set(wy.pid)
        for p in pids:
            ts = [x for x in r[r.gsis_id == p].team.unique()] if False else None
            # team of record: most frequent team in the roster table, else the stat table
            tms = [st[k][1] for k in st if k[0] == p] if False else None
            rows.append(p)
        # vectorised per player
        rr = r.groupby("gsis_id")
        out = []
        for p, g in rr:
            team = g.team.value_counts().index[0]
            G = len(team_weeks.get(team, set()))
            played = inj_m = role_m = res_w = out_w = 0; snp = []; big = 0
            for wk in team_weeks.get(team, set()):
                s_ = st.get((p, wk), (None, None))[0]
                rp = rep.get((p, wk))
                if rp == "Out": out_w += 1
                if s_ in ("RES", "PUP", "NFI", "RSN"): res_w += 1
                if (p, wk) in stat:
                    played += 1
                    sn = snap.get((p, wk))
                    if sn: snp.append(sn[1]); big += sn[1] >= .5
                elif s_ in ("RES", "PUP", "NFI", "RSN") or rp in ("Out", "Doubtful"):
                    inj_m += 1
                elif s_ == "ACT":
                    role_m += 1
            tch = touch.get(p, (0, 0))
            out.append({"season": Y, "pid": p, "G": G, "gp": played, "inj_m": inj_m, "role_m": role_m, "off_m": max(0, G - played - inj_m - role_m),
                        "res_w": res_w, "out_w": out_w, "snap_pct": np.mean(snp) if snp else np.nan, "big_share": big / G if G else 0,
                        "tpg": tch[0] / tch[1] if tch[1] else 0.0})
        rows = out
        if Y == 2012: AV = pd.DataFrame(out)
        else: AV = pd.concat([AV, pd.DataFrame(out)], ignore_index=True)
        P(f"  availability {Y}: {len(out)} roster players")
    return AV, wk1


def add_features(D, AV, wk1):
    av = AV.set_index(["season", "pid"])
    for k in (1, 2, 3):
        idx = list(zip(D.season - k, D.pid))
        sub = av.reindex(idx)
        G = sub.G.values.astype(float); G[G == 0] = np.nan
        D[f"gs{k}"] = (sub.gp.values / G)
        D[f"inj{k}"] = sub.inj_m.values / G
        D[f"role{k}"] = sub.role_m.values / G
        D[f"resw{k}"] = sub.res_w.values / G
        if k == 1:
            D["snap1"] = sub.snap_pct.values; D["big1"] = sub.big_share.values; D["tpg1x"] = sub.tpg.values; D["outw1"] = sub.out_w.values / G
    D["inj_hist"] = np.nansum(np.column_stack([D.inj1 * 3, D.inj2 * 2, D.inj3 * 1]), axis=1) / np.maximum(1e-9, (D.inj1.notna() * 3 + D.inj2.notna() * 2 + D.inj3.notna() * 1))
    D.loc[(D.inj1.isna()) & (D.inj2.isna()) & (D.inj3.isna()), "inj_hist"] = np.nan
    s1 = [wk1.get((y, p), (None, None)) for y, p in zip(D.season, D.pid)]
    stt = [x[0] for x in s1]; rpt = [x[2] if len(x) > 2 else None for x in s1]
    D["w1_res"] = [float(s in ("RES", "PUP", "NFI", "RSN")) for s in stt]
    D["w1_sus"] = [float(s == "SUS") for s in stt]
    D["w1_off"] = [float(s not in ("ACT", "RES", "PUP", "NFI", "RSN", "SUS", "INA")) for s in stt]   # cut / PS / none
    D["w1_out"] = [float(r in ("Out", "Doubtful")) for r in rpt]
    D["w1_q"] = [float(r == "Questionable") for r in rpt]
    # QB job security: team drafted a QB in round 1 this year
    dp = pd.read_parquet(os.path.join(CACHE, "draft_picks.parquet"), columns=["season", "pick", "team", "position"])
    r1qb = set((y, PM.tm(t)) for y, p_, t, ps in zip(dp.season, dp.pick, dp.team, dp.position) if ps == "QB" and p_ <= 32)
    D["team_r1qb"] = [float((y, t) in r1qb and not rk) for y, t, rk in zip(D.season, D.team, D.rookie)]
    D["G"] = D.season.map(lambda y: PM.final_week(y) - 1)
    # IN-HOUSE relevance (no ADP): on the week-1 chart at 1-2, or a real role last year, or a top-64 rookie
    D["rel"] = ((D.dc <= 2) | ((D.g1 >= 4) & (D.ppg1 >= 6)) | ((D.rookie == 1) & (np.exp(D.lpick) <= 64))).astype(bool)
    D["miss"] = (D.G - D.act_games).clip(lower=0)
    D["gshare"] = (D.act_games / D.G).clip(0, 1)
    return D


GF = ["age", "age2", "exp", "rookie", "lpick", "rd1", "rd2", "undrafted", "gs1", "gs2", "gs3", "inj1", "inj2", "inj3", "inj_hist",
      "role1", "role2", "resw1", "outw1", "snap1", "big1", "tpg1x", "ppg1", "dc1", "dc2", "dcna", "moved", "w1_res", "w1_sus", "w1_off",
      "w1_out", "w1_q", "is_qb1", "team_r1qb", "exp_w"]
GF_NOINJ = [f for f in GF if f not in ("inj1", "inj2", "inj3", "inj_hist", "resw1", "outw1")]


def walk(D, feats, tag):
    from sklearn.linear_model import Ridge, LogisticRegression
    from sklearn.ensemble import HistGradientBoostingRegressor
    out = pd.DataFrame(index=D.index, columns=[f"{tag}_ridge", f"{tag}_gbm", f"{tag}_dist", f"{tag}_flat", f"{tag}_last"] + [f"{tag}_pb{k}" for k in range(4)], dtype=float)
    for Y in PM.TEST_YEARS:
        for ps in POS4:
            tr = (D.season < Y) & (D.pos == ps) & D.rel; te = (D.season == Y) & (D.pos == ps)
            if tr.sum() < 100 or te.sum() == 0: continue
            w = 0.5 ** ((Y - 1 - D.season[tr].values) / 4.0)
            Xtr = D.loc[tr, feats].values.astype(float); Xte = D.loc[te, feats].values.astype(float)
            A, B = PM.prep(Xtr, Xte); mu, sd = A.mean(0), A.std(0); sd[sd == 0] = 1; A = (A - mu) / sd; B = (B - mu) / sd
            y = D.gshare[tr].values
            out.loc[te, f"{tag}_ridge"] = np.clip(Ridge(alpha=30.0).fit(A, y, sample_weight=w).predict(B), 0.02, 1)
            keep = ~np.all(np.isnan(Xtr), axis=0)
            out.loc[te, f"{tag}_gbm"] = np.clip(HistGradientBoostingRegressor(max_iter=150, max_depth=2, learning_rate=0.05, min_samples_leaf=60, random_state=0)
                                                .fit(Xtr[:, keep], y, sample_weight=w).predict(Xte[:, keep]), 0.02, 1)
            m = D.miss[tr].values; lab = np.digitize(m, [2, 4, 8])
            clf = LogisticRegression(C=0.1, max_iter=2000).fit(A, lab, sample_weight=w)
            pr = np.zeros((te.sum(), 4)); pr[:, clf.classes_] = clf.predict_proba(B)
            bm = [np.mean(D.gshare[tr].values[lab == k]) if (lab == k).any() else 0.5 for k in range(4)]
            out.loc[te, f"{tag}_dist"] = pr @ np.array(bm)
            for k in range(4): out.loc[te, f"{tag}_pb{k}"] = pr[:, k]
            out.loc[te, f"{tag}_flat"] = np.average(y, weights=w)
            rk_mean = np.mean(D.gshare[tr & (D.rookie == 1)]) if (tr & (D.rookie == 1)).any() else np.average(y, weights=w)
            last = D.loc[te, "gs1"].values.astype(float)
            out.loc[te, f"{tag}_last"] = np.where(np.isnan(last), rk_mean, last)
    out[f"{tag}_main"] = 0.5 * out[f"{tag}_ridge"] + 0.5 * out[f"{tag}_dist"]
    return out


def grade_games(R, cols, mask, label):
    m = mask.copy()
    for c in cols: m &= R[c].notna()
    a = R.gshare[m].values * R.G[m].values
    P(f"\n  {label} (n {int(m.sum())}): model | games MAE | RMSE | corr | Spearman | mean pred vs actual")
    for c in cols:
        p = R[c][m].values * R.G[m].values
        P(f"    {c:16s} {np.mean(np.abs(p - a)):5.2f} {np.sqrt(np.mean((p - a)**2)):5.2f} {np.corrcoef(p, a)[0,1]:6.3f} {spearmanr(p, a).correlation:6.3f}   {p.mean():5.2f} vs {a.mean():5.2f}")


def main():
    global LOG
    LOG = open(os.path.join(HERE, LOG_NAME), "w", encoding="utf-8")
    t0 = time.time()
    P("=== Games-played model (in-house), walk-forward 2015-25 ===")
    D = PM.build()
    AV, wk1 = availability()
    D = add_features(D, AV, wk1)
    # describe missed-game causes in the ADP top-150 pool (descriptive; ADP only defines the pool)
    pool = D.season.isin(PM.TEST_YEARS) & D.adp.notna() & (D.adp <= 150)
    av = AV.set_index(["season", "pid"]).reindex(list(zip(D.season, D.pid)))
    D["inj_m_now"] = av.inj_m.values; D["role_m_now"] = av.role_m.values; D["off_m_now"] = av.off_m.values
    P("\n  missed games by cause, ADP top 150, 2015-25 (per player-season): injury / role (active, no stat) / off-roster")
    for lab, mk in (("depth 1", D.dc == 1), ("depth 2", D.dc == 2), ("depth 3+ / none", ~D.dc.isin([1, 2]))):
        x = D[pool & mk]
        P(f"    {lab:16s} n {len(x):4d}: {x.inj_m_now.mean():.2f} / {x.role_m_now.mean():.2f} / {x.off_m_now.mean():.2f}  (of {x.G.mean():.1f} games; missed 4+ {np.mean(x.miss >= 4)*100:.0f}%)")
    O = walk(D, GF, "g")
    O2 = walk(D, GF_NOINJ, "noinj")
    R = pd.concat([D, O, O2], axis=1)
    # main mix weight picked on 2015-18 only
    early = pool & (R.season <= 2018)
    best = None
    for wr in (0, .25, .5, .75, 1):
        p = (wr * R.g_ridge + (1 - wr) * R.g_dist)[early] * R.G[early]
        e = np.mean(np.abs(p - R.gshare[early] * R.G[early]))
        if best is None or e < best[0]: best = (e, wr)
    P(f"\n  ridge/dist mix picked on 2015-18 folds: w_ridge {best[1]} (MAE {best[0]:.3f}); frozen for all years")
    R["g_main"] = best[1] * R.g_ridge + (1 - best[1]) * R.g_dist
    # old prototype games model (uses ADP) and an ADP-informed variant: comparison only
    Rold = PM.walk_forward(D)
    R["old_games"] = Rold.games_pred.values
    R["ridge_stats"] = Rold.ridge_stats.values; R["anchor_mix"] = Rold.anchor_mix.values; R["adp_total"] = Rold.adp_total.values
    cols = ["g_main", "g_ridge", "g_gbm", "g_dist", "noinj_main", "g_flat", "g_last", "old_games"]
    grade_games(R, cols, pool, "ADP top-150 pool, 2015-25")
    grade_games(R, cols, pool & (R.season >= 2019), "same, 2019-25 (main mix frozen)")
    for ps in POS4: grade_games(R, ["g_main", "g_flat", "g_last", "old_games"], pool & (R.pos == ps), f"{ps}")
    for lab, mk in (("depth 1", R.dc == 1), ("depth 2", R.dc == 2), ("depth 3+/none", ~R.dc.isin([1, 2]))):
        grade_games(R, ["g_main", "g_flat", "g_last", "old_games"], pool & mk, f"role tier {lab}")
    grade_games(R, ["g_main", "g_flat", "g_last", "old_games"], R.season.isin(PM.TEST_YEARS) & R.rel, "IN-HOUSE relevance pool (chart 1-2 / real role / top-64 rookie; no ADP)")
    # calibration of the distribution: P(miss 4+) = pb2 + pb3
    R["p4raw"] = R.g_pb2 + R.g_pb3; R["y4"] = (R.miss >= 4).astype(float)
    e18 = pool & (R.season <= 2018) & R.p4raw.notna(); base4 = R.y4[R.season.isin(PM.TEST_YEARS) & R.rel].mean()
    best_a = min((np.mean(((a * R.p4raw + (1 - a) * base4)[e18] - R.y4[e18]) ** 2), a) for a in (0, .2, .4, .6, .8, 1.0))[1]
    P("");P(f"  distribution shrink toward the base rate picked on 2015-18: a {best_a} (1 = raw)")
    for k in range(4):
        bk = np.mean(np.digitize(R.miss[R.season.isin(PM.TEST_YEARS) & R.rel], [2, 4, 8]) == k)
        R[f"g_pb{k}"] = best_a * R[f"g_pb{k}"] + (1 - best_a) * bk
    R["p4"] = R.g_pb2 + R.g_pb3
    c = R[pool & R.p4.notna()].copy(); c["bin"] = pd.cut(c.p4, [0, .1, .2, .3, .4, .5, .7, 1.0])
    t = c.groupby("bin", observed=True).agg(n=("y4", "size"), pred=("p4", "mean"), act=("y4", "mean"))
    P("\n  calibration P(miss 4+ games), ADP top 150: " + " | ".join(f"{r.pred:.2f}->{r.act:.2f} (n{r.n})" for r in t.itertuples()))
    P(f"    Brier {np.mean((c.p4 - c.y4)**2):.4f} vs base-rate {np.mean((c.y4.mean() - c.y4)**2):.4f}")
    c["p0"] = c.g_pb0; c["y0"] = (c.miss <= 1).astype(float)
    P(f"  P(full season, 0-1 missed): pred {c.p0.mean():.3f} vs actual {c.y0.mean():.3f}; Brier {np.mean((c.p0 - c.y0)**2):.4f} vs base {np.mean((c.y0.mean() - c.y0)**2):.4f}")
    c["p8"] = c.g_pb3; c["y8"] = (c.miss >= 8).astype(float)
    P(f"  P(long absence, 8+ missed): pred {c.p8.mean():.3f} vs actual {c.y8.mean():.3f}; Brier {np.mean((c.p8 - c.y8)**2):.4f} vs base {np.mean((c.y8.mean() - c.y8)**2):.4f}")
    # which inputs hold up: ridge coefficient read (full fit, all positions pooled) and the no-injury ablation above
    from sklearn.linear_model import Ridge
    fit = R[R.season.isin(PM.TEST_YEARS)]
    X = fit[GF].values.astype(float); med = np.nanmedian(X, 0); med = np.where(np.isnan(med), 0, med); X = np.where(np.isnan(X), med, X)
    mu, sd = X.mean(0), X.std(0); sd[sd == 0] = 1
    cf = Ridge(alpha=30).fit((X - mu) / sd, fit.gshare).coef_
    P("\n  strongest standardized ridge coefficients (games share, pooled): " + ", ".join(f"{f} {c_:+.3f}" for f, c_ in sorted(zip(GF, cf), key=lambda t: -abs(t[1]))[:12]))

    # ---------------- season totals
    P("\n=== Season totals: in-house PPG (ridge_stats, no ADP) x games ===")
    for nm, g in (("inhouse_newG", "g_main"), ("inhouse_oldG", "old_games"), ("inhouse_flatG", "g_flat"), ("inhouse_lastG", "g_last")):
        R[nm] = R.ridge_stats * R[g] * R.G
    R["cmp_anchor_newG"] = R.anchor_mix * R.g_main * R.G          # comparison only: ADP-anchored per game
    R["cmp_anchor_oldG"] = R.anchor_mix * R.old_games * R.G
    tots = ["inhouse_newG", "inhouse_oldG", "inhouse_flatG", "inhouse_lastG", "adp_total", "cmp_anchor_newG", "cmp_anchor_oldG"]
    def gt(mask, label):
        m = mask.copy()
        for c_ in tots: m &= R[c_].notna()
        P(f"\n  {label} (n {int(m.sum())}): model | MAE | Spearman (pos-season) | top-12 | top-24")
        for c_ in tots:
            rh, h12, h24 = [], [], []
            for (y, ps), g in R[m].groupby(["season", "pos"]):
                if len(g) < 24: continue
                rh.append(spearmanr(g[c_], g.act_total).correlation)
                h12.append(len(set(g.nlargest(12, c_).pid) & set(g.nlargest(12, "act_total").pid)) / 12)
                h24.append(len(set(g.nlargest(24, c_).pid) & set(g.nlargest(24, "act_total").pid)) / 24)
            P(f"    {c_:16s} {np.mean(np.abs(R[c_][m] - R.act_total[m])):6.2f} {np.mean(rh):6.3f} {np.mean(h12):6.3f} {np.mean(h24):6.3f}")
    gt(pool, "ADP top 150, 2015-25")
    for lab, mk in (("ADP 1-30", R.adp <= 30), ("ADP 31-100", (R.adp > 30) & (R.adp <= 100)), ("ADP 101-150", (R.adp > 100) & (R.adp <= 150))):
        m = pool & mk & R.inhouse_newG.notna() & R.inhouse_oldG.notna() & R.adp_total.notna()
        P(f"  {lab}: total MAE in-house new {np.mean(np.abs(R.inhouse_newG[m] - R.act_total[m])):.1f} | old {np.mean(np.abs(R.inhouse_oldG[m] - R.act_total[m])):.1f} | ADP {np.mean(np.abs(R.adp_total[m] - R.act_total[m])):.1f} | pooled Spearman new {spearmanr(R.inhouse_newG[m], R.act_total[m]).correlation:.3f} old {spearmanr(R.inhouse_oldG[m], R.act_total[m]).correlation:.3f} ADP {spearmanr(R.adp_total[m], R.act_total[m]).correlation:.3f}")
    # season-total ranges from the games DISTRIBUTION x walk-forward PPG ratio quantiles (Monte Carlo)
    cov_rows = []
    for Y in PM.TEST_YEARS[2:]:
        for ps in POS4:
            past = (R.season < Y) & (R.season >= 2015) & (R.pos == ps) & (R.act_games >= 4) & R.ridge_stats.notna()
            te = pool & (R.season == Y) & (R.pos == ps) & R.g_pb0.notna()
            if past.sum() < 50 or te.sum() == 0: continue
            ratio = ((R.act_ppg[past] + 1) / (R.ridge_stats[past] + 1)).values
            for i in np.where(te.values)[0]:
                r = R.iloc[i]; G = r.G; pb = np.array([r.g_pb0, r.g_pb1, r.g_pb2, r.g_pb3]); pb = pb / pb.sum()
                k = RNG.choice(4, 2000, p=pb)
                lo = np.array([BINS[j][0] for j in k]); hi = np.array([min(BINS[j][1], G) for j in k])
                miss = np.floor(lo + RNG.random(2000) * (hi - lo + 1)); gm = np.clip(G - miss, 0, G)
                ppg = (r.ridge_stats + 1) * RNG.choice(ratio, 2000) - 1
                tot = np.maximum(0, ppg) * gm
                q10, q90 = np.quantile(tot, [.1, .9])
                cov_rows.append((r.act_total >= q10) & (r.act_total <= q90))
    P(f"\n  season-total p10-p90 coverage from the games distribution x PPG ratio draws (2017-25, ADP top 150): {np.mean(cov_rows)*100:.1f}% (n {len(cov_rows)}; target 80)")
    R.to_parquet(os.path.join(DATA, "games_model_rows.parquet"), index=False)
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
