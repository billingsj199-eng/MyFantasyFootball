#!/usr/bin/env python3
"""
A9 fixes to the in-house preseason prototype (Jack 2026-11-21 "Yes, fix them"). No ADP input; ADP only as the benchmark.
Every fix must earn its place on the 2015-25 walk-forward. Dev = 2015-22, holdout 2023-25 (looked at several times already,
so no longer fully clean - reported separately, choices made on dev only).

 1  games model: established starters coming off ONE short season (measure, then repairs: multi-season games share /
    shrink last season toward the player's own longer-run rate / floor on its effect)
 2  RBs: age x workload forms (volume, games, spread); backup RB value vs best-ball AND redraft ADP; week-1 backup RB
    TAKEOVER probability (walk-forward logistic) as an explicit input to volume / games and the upper range
 3  position overrides (data/position_overrides.csv, applied when the player tables are built)
 4  games distribution recalibration (walk-forward isotonic on P(miss 2+ / 4+ / 8+))
Writes fixes_a9.log (log of record, opened by main()) and data/fixes_a9_rows.parquet. Reusable helpers for output_rankings.py.
"""
import os, sys, time, warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM
import games_model as GM
import pergame_model as G

LOG = None
LOG_NAME = "fixes_a9.log"
DEV = list(range(2015, 2023)); HOLD = [2023, 2024, 2025]
BINS = [(0, 1), (2, 3), (4, 7), (8, 99)]


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


# ------------------------------------------------------------------ shared pipeline pieces
def established(D):
    """2+ of the two seasons before last as a clear starter-level player (12+ games and a real role)."""
    def clear(k):
        gs = D[f"gs{k}"]; role = np.where(D.pos == "QB", D[f"h{k}_att"] / D[f"h{k}_g"].replace(0, np.nan) >= 20,
                                         np.where(D.pos == "RB", D[f"h{k}_car"] / D[f"h{k}_g"].replace(0, np.nan) >= 10,
                                                  D[f"h{k}_tgt"] / D[f"h{k}_g"].replace(0, np.nan) >= 4.5))
        return (gs >= 12 / 16.5) & role
    return (clear(2).astype(int) + clear(3).astype(int)) >= 2


def add_fix1_features(D):
    # multi-season games share (weights 3/2/1 over the seasons present)
    num = sum(w * D[f"gs{k}"].fillna(0) for k, w in ((1, 3), (2, 2), (3, 1)))
    den = sum(w * D[f"gs{k}"].notna() for k, w in ((1, 3), (2, 2), (3, 1)))
    D["gs_multi"] = num / den.replace(0, np.nan)
    D["est"] = established(D).astype(float)
    lr = (D.gs2.fillna(0) * 2 + D.gs3.fillna(0)) / ((D.gs2.notna() * 2 + D.gs3.notna()).replace(0, np.nan))
    D["gs1_shrunk"] = np.where(D.est == 1, 0.4 * D.gs1 + 0.6 * lr, D.gs1)
    D["gs1_floor"] = np.where(D.est == 1, np.maximum(D.gs1, 0.6), D.gs1)
    D["short1"] = (D.gs1 < 10 / 16.5).astype(float)
    return D


def takeover_table(D):
    """week-1 depth-2 RBs: did he become the lead back (50%+ of team carries in 3+ games) during the season?"""
    W = pd.read_parquet(os.path.join(PM.DATA, "player_weeks.parquet"), columns=["season", "week", "pid", "team", "car", "team_car"])
    W = W[W.week < W.season.map(PM.final_week)]
    lead = W[(W.team_car > 0) & (W.car / W.team_car >= 0.5)].groupby(["season", "pid"]).size()
    D["took_over"] = [float(lead.get((y, p), 0) >= 3) for y, p in zip(D.season, D.pid)]
    # team's week-1 RB1: age and prior games share
    rb1 = D[(D.pos == "RB") & (D.dc == 1)].groupby(["season", "team"]).agg(s_age=("age", "first"), s_gs1=("gs1", "first"), s_csh1=("csh1", "first")).reset_index()
    D = D.merge(rb1, on=["season", "team"], how="left")
    return D


def fit_takeover(D, Y):
    from sklearn.linear_model import LogisticRegression
    m = (D.pos == "RB") & (D.dc == 2)
    tr = m & (D.season < Y); te = m & (D.season == Y)
    F = ["lpick", "rookie", "age", "s_age", "s_gs1", "s_csh1", "cpg1", "tpg1"]
    if tr.sum() < 60 or te.sum() == 0: return pd.Series(np.nan, index=D.index[te])
    X = D.loc[tr, F].astype(float); med = X.median(); X = X.fillna(med); mu, sd = X.mean(), X.std().replace(0, 1)
    clf = LogisticRegression(C=0.3, max_iter=2000).fit((X - mu) / sd, D.took_over[tr])
    Xt = (D.loc[te, F].astype(float).fillna(med) - mu) / sd
    return pd.Series(clf.predict_proba(Xt)[:, 1], index=D.index[te])


def calibrate_dist(D, years):
    """walk-forward isotonic recalibration of the cumulative P(miss 2+ / 4+ / 8+); returns adjusted bin probabilities."""
    from sklearn.isotonic import IsotonicRegression
    c2 = D.g_pb1 + D.g_pb2 + D.g_pb3; c4 = D.g_pb2 + D.g_pb3; c8 = D.g_pb3
    out = {k: pd.Series(np.nan, index=D.index) for k in ("c2", "c4", "c8")}
    for Y in years:
        tr = (D.season < Y) & (D.season >= 2015) & D.rel & c2.notna(); te = D.season == Y
        if tr.sum() < 200:
            for k, c in (("c2", c2), ("c4", c4), ("c8", c8)): out[k][te] = c[te]
            continue
        for k, c, thr in (("c2", c2, 2), ("c4", c4, 4), ("c8", c8, 8)):
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(c[tr], (D.miss[tr] >= thr).astype(float))
            out[k][te] = iso.predict(c[te].fillna(c[tr].mean()))
    a2 = out["c2"].values; a4 = np.minimum(out["c4"].values, a2); a8 = np.minimum(out["c8"].values, a4)
    pb = np.column_stack([1 - a2, a2 - a4, a4 - a8, a8]); pb = np.clip(pb, 1e-4, None); pb = pb / pb.sum(1, keepdims=True)
    bm = np.array([np.mean(D.gshare[(D.miss >= lo) & (D.miss <= hi) & D.rel]) for lo, hi in BINS])
    return pb, pb @ bm


def wmae(p, a, w): return float(np.sum(w * np.abs(p - a)) / np.sum(w))


def games_grade(D, col, mask, lab):
    m = mask & D[col].notna()
    p = D[col][m] * D.G[m]; a = D.gshare[m] * D.G[m]
    P(f"    {lab:40s} n {int(m.sum()):4d} | pred {p.mean():5.2f} vs actual {a.mean():5.2f} | MAE {np.mean(np.abs(p - a)):.2f} | corr {np.corrcoef(p, a)[0,1]:.3f}")


def cal_table(D, pb, mask, lab):
    m = mask & ~np.isnan(pb[:, 0])
    parts = []
    for name, cut, pk in (("1+", 1, None), ("2+", 2, 1), ("4+", 4, 2), ("8+", 8, 3)):
        if cut == 1: continue
        p = pb[m][:, pk:].sum(1); y = (D.miss[m] >= cut).astype(float)
        parts.append(f"P(miss {name}) {p.mean():.3f} vs {y.mean():.3f} (Brier {np.mean((p - y.values) ** 2):.4f})")
    whole = (D.miss[m] <= 1).astype(float); pw = pb[m][:, 0]
    parts.append(f"full season {pw.mean():.3f} vs {whole.mean():.3f}")
    P(f"    {lab:22s} n {int(m.sum()):4d}: " + " | ".join(parts))


def mc_cover(D, ppgcol, pb, mask, ratios, levels=((.1, .9), (.25, .75)), seed=5):
    rng = np.random.default_rng(seed); hits = {l: [] for l in levels}; below = {l: [] for l in levels}; above = {l: [] for l in levels}
    for i in np.where(mask.values)[0]:
        r = D.iloc[i]; Gm = r.G; p = pb[i]
        if np.isnan(p).any() or np.isnan(r[ppgcol]): continue
        ra = ratios.get((r.season, r.pos))
        if ra is None or len(ra) < 50: continue
        k = rng.choice(4, 2000, p=p / p.sum()); lo = np.array([BINS[j][0] for j in k]); hi = np.array([min(BINS[j][1], Gm) for j in k])
        gm = np.clip(Gm - np.floor(lo + rng.random(2000) * (hi - lo + 1)), 0, Gm)
        tot = np.maximum(0, (r[ppgcol] + 1) * rng.choice(ra, 2000) - 1) * gm
        for l in levels:
            q1, q2 = np.quantile(tot, l)
            hits[l].append(q1 <= r.act_total <= q2); below[l].append(r.act_total < q1); above[l].append(r.act_total > q2)
    return {l: (np.mean(hits[l]) * 100, np.mean(below[l]) * 100, np.mean(above[l]) * 100, len(hits[l])) for l in levels}


def ratio_table(D, ppgcol, years):
    out = {}
    for Y in years:
        for ps in PM.POS4:
            past = (D.season < Y) & (D.season >= 2015) & (D.pos == ps) & (D.act_games >= 4) & D[ppgcol].notna()
            out[(Y, ps)] = ((D.act_ppg[past] + 1) / (D[ppgcol][past] + 1)).values
    return out


def per_game_grade(D, cols, mask, lab):
    m = mask & (D.act_games >= 4)
    for c in cols: m &= D[c].notna()
    res = []
    for c in cols:
        rh = [spearmanr(g[c], g.act_ppg).correlation for _, g in D[m].groupby(["season", "pos"]) if len(g) >= 12]
        yrs = [y for y in sorted(D[m].season.unique()) if (m & (D.season == y)).sum() >= 15]
        wins = sum(wmae(D[c][m & (D.season == y)], D.act_ppg[m & (D.season == y)], D.act_games[m & (D.season == y)]) <
                   wmae(D.adp_curve_f[m & (D.season == y)], D.act_ppg[m & (D.season == y)], D.act_games[m & (D.season == y)]) for y in yrs)
        res.append(f"{c} {wmae(D[c][m], D.act_ppg[m], D.act_games[m]):.3f}/{np.nanmean(rh):.3f} ({wins}/{len(yrs)})")
    P(f"    {lab:26s} n {int(m.sum()):4d}: " + " | ".join(res))


def total_grade(D, cols, mask, lab):
    m = mask.copy()
    for c in cols: m &= D[c].notna()
    res = []
    for c in cols:
        rh, h12, h24 = [], [], []
        for _, g in D[m].groupby(["season", "pos"]):
            if len(g) < 24: continue
            rh.append(spearmanr(g[c], g.act_total).correlation)
            h12.append(len(set(g.nlargest(12, c).pid) & set(g.nlargest(12, "act_total").pid)) / 12)
            h24.append(len(set(g.nlargest(24, c).pid) & set(g.nlargest(24, "act_total").pid)) / 24)
        res.append(f"{c} {np.mean(np.abs(D[c][m] - D.act_total[m])):.1f}/{np.mean(rh):.3f}/t12 {np.mean(h12):.3f}/t24 {np.mean(h24):.3f}")
    P(f"    {lab:26s} n {int(m.sum()):4d}: " + " | ".join(res))


def main():
    global LOG
    LOG = open(os.path.join(HERE, LOG_NAME), "w", encoding="utf-8")
    t0 = time.time()
    P("=== A9 fixes: walk-forward 2015-25 (dev 2015-22 / holdout 2023-25, holdout already viewed several times) ===")
    D = PM.build()
    AV, wk1 = GM.availability()
    D = GM.add_features(D, AV, wk1)
    S = G.stat_seasons(); D = G.add_history(D, S); D = G.add_context(D, S)
    D = add_fix1_features(D)
    R0 = PM.walk_forward(D)
    for c in ("ridge_stats", "adp_curve_f", "adp_curve", "adp_total"): D[c] = R0[c].values
    pool = D.season.isin(PM.TEST_YEARS) & D.adp.notna() & (D.adp <= 150)
    pdev = pool & D.season.isin(DEV); phold = pool & D.season.isin(HOLD)

    # ---------------- baseline games model (A2 form)
    O = GM.walk(D, GM.GF, "base"); D = pd.concat([D, O], axis=1)
    D["g_base"] = 0.75 * D.base_ridge + 0.25 * D.base_dist
    base_rates = {k: np.mean(np.digitize(D.miss[D.rel & D.season.isin(PM.TEST_YEARS)], [2, 4, 8]) == k) for k in range(4)}
    pb_base = np.column_stack([0.8 * D[f"base_pb{k}"] + 0.2 * base_rates[k] for k in range(4)])

    # ================= FIX 1
    P("\n=== FIX 1. Established starters coming off one short season ===")
    grp = pool & (D.est == 1) & (D.short1 == 1)
    av = AV.set_index(["season", "pid"]).reindex(list(zip(D.season - 1, D.pid)))
    D["y1_inj"] = av.inj_m.values; D["y1_role"] = av.role_m.values; D["y1_off"] = av.off_m.values
    games_grade(D, "g_base", grp, "baseline: est. starter, short last season")
    games_grade(D, "g_base", grp & (D.y1_inj >= D.y1_role + D.y1_off), "  ...short because of injury")
    games_grade(D, "g_base", grp & (D.y1_inj < D.y1_role + D.y1_off), "  ...short for role/benching/off-roster")
    for ps in PM.POS4: games_grade(D, "g_base", grp & (D.pos == ps), f"  ...{ps}")
    games_grade(D, "g_base", pool & (D.est == 1) & (D.short1 == 0), "est. starter, full last season (control)")
    variants = {"multi-season share": [f if f != "gs1" else "gs_multi" for f in GM.GF],
                "shrink last season (est.)": [f if f != "gs1" else "gs1_shrunk" for f in GM.GF],
                "floor last season at .6 (est.)": [f if f != "gs1" else "gs1_floor" for f in GM.GF],
                "add est x short flag": GM.GF + ["est", "short1"]}
    for lab, feats in variants.items():
        O = GM.walk(D, feats, "v"); g = 0.75 * O.v_ridge + 0.25 * O.v_dist; D[f"g_{lab}"] = g.values
        res = []
        for nm, mk in (("dev pool", pdev), ("hold pool", phold), ("group", grp), ("old RB 28+ short", pool & (D.pos == "RB") & (D.age >= 28) & (D.short1 == 1)), ("QB short for role", pool & (D.pos == "QB") & (D.short1 == 1) & (D.y1_role > 2))):
            m = mk & D[f"g_{lab}"].notna()
            res.append(f"{nm} {np.mean(np.abs(D[f'g_{lab}'][m] * D.G[m] - D.gshare[m] * D.G[m])):.2f} (base {np.mean(np.abs(D.g_base[m] * D.G[m] - D.gshare[m] * D.G[m])):.2f}; pred {np.mean(D[f'g_{lab}'][m] * D.G[m]):.1f} act {np.mean(D.gshare[m] * D.G[m]):.1f})")
        P(f"  {lab:30s}: " + " | ".join(res))

    # ================= FIX 2
    P("\n=== FIX 2. RBs: age x workload, backup value, takeover probability ===")
    D = takeover_table(D)
    bk = (D.pos == "RB") & (D.dc == 2) & D.season.isin(PM.TEST_YEARS)
    P(f"  week-1 depth-2 RBs 2015-25: n {int(bk.sum())}, took over the lead (3+ games at 50%+ of team carries): {D.took_over[bk].mean()*100:.1f}%")
    for lab, mk in (("drafted rd 1-2", D.lpick <= np.log(64)), ("rd 3-4", (D.lpick > np.log(64)) & (D.lpick <= np.log(140))), ("later / UDFA", D.lpick > np.log(140)),
                    ("starter 28+", D.s_age >= 28), ("starter < 28", D.s_age < 28), ("starter missed time last yr (<.7 games)", D.s_gs1 < .7),
                    ("committee (starter carry share < .5)", D.s_csh1 < .5), ("clear lead (>= .5)", D.s_csh1 >= .5), ("rookie backup", D.rookie == 1)):
        m = bk & mk
        P(f"    {lab:42s} n {int(m.sum()):4d} take-over {D.took_over[m].mean()*100:5.1f}%")
    P(f"  week-1 depth-3+ RBs: n {int(((D.pos == 'RB') & (D.dc >= 3) & D.season.isin(PM.TEST_YEARS)).sum())}, took over {D.took_over[(D.pos == 'RB') & (D.dc >= 3) & D.season.isin(PM.TEST_YEARS)].mean()*100:.1f}%")
    D["p_take"] = np.nan
    for Y in PM.TEST_YEARS:
        s = fit_takeover(D, Y); D.loc[s.index, "p_take"] = s.values
    m = bk & D.p_take.notna()
    D["pt_bin"] = pd.cut(D.p_take, [0, .1, .2, .3, .5, 1])
    t = D[m].groupby("pt_bin", observed=True).agg(n=("took_over", "size"), pred=("p_take", "mean"), act=("took_over", "mean"))
    P("  walk-forward P(take over) calibration: " + " | ".join(f"{r.pred:.2f}->{r.act:.2f} (n{r.n})" for r in t.itertuples()) + f" | Brier {np.mean((D.p_take[m] - D.took_over[m])**2):.4f} vs base {np.mean((D.took_over[m].mean() - D.took_over[m])**2):.4f}")
    D["p_take_f"] = np.where((D.pos == "RB") & (D.dc == 2), D.p_take.fillna(0), 0.0)
    D["rb_age_x_load"] = np.where(D.pos == "RB", np.maximum(0, D.age - 26) * D.cpg1.fillna(0) / 15, 0.0)
    # per-game baseline (A7 final) and variants
    lean = G.BASIC + G.ROSTER + ["lp_rook"]
    s7, comp7, _ = G.walk(D, lean, "S7", use_role_prior=True); D["s7"] = s7.values; D["pg_base"] = 0.75 * D.s7 + 0.25 * D.ridge_stats
    for lab, feats in (("+takeover prob", lean + ["p_take_f"]), ("+RB age x load", lean + ["rb_age_x_load"])):
        s, _, _ = G.walk(D, feats, "x", use_role_prior=True); D[f"pg_{lab}"] = (0.75 * s + 0.25 * D.ridge_stats).values
    Og = GM.walk(D, GM.GF + ["rb_age_x_load", "p_take_f"], "g2"); D["g_rbfix"] = (0.75 * Og.g2_ridge + 0.25 * Og.g2_dist).values
    for lab, mk in (("RB all (ADP top 150)", pool & (D.pos == "RB")), ("RB 28+", pool & (D.pos == "RB") & (D.age >= 28)), ("RB 28+ heavy (15+ car/g)", pool & (D.pos == "RB") & (D.age >= 28) & (D.cpg1 >= 15)),
                    ("RB depth-2 backups", pool & (D.pos == "RB") & (D.dc == 2)), ("whole pool dev", pdev), ("whole pool holdout", phold)):
        per_game_grade(D, ["pg_base", "pg_+takeover prob", "pg_+RB age x load", "adp_curve_f"], mk, lab)
    games_grade(D, "g_base", pool & (D.pos == "RB") & (D.age >= 28), "games base: RB 28+")
    games_grade(D, "g_rbfix", pool & (D.pos == "RB") & (D.age >= 28), "games +age x load +takeover: RB 28+")
    games_grade(D, "g_base", pool & (D.pos == "RB") & (D.dc == 2), "games base: RB backups")
    games_grade(D, "g_rbfix", pool & (D.pos == "RB") & (D.dc == 2), "games +age x load +takeover: RB backups")
    # backups vs which ADP: FFC is redraft (mock drafts); the 2026 comparison was Underdog best ball
    bkp = pool & (D.pos == "RB") & (D.dc == 2) & (D.act_games >= 4)
    P(f"  depth-2 RBs vs REDRAFT ADP (FFC mock drafts, history): model bias act/pred {D.act_ppg[bkp].sum()/D.pg_base[bkp].sum():.3f} vs ADP curve {D.act_ppg[bkp].sum()/D.adp_curve_f[bkp].sum():.3f}; MAE model {wmae(D.pg_base[bkp], D.act_ppg[bkp], D.act_games[bkp]):.3f} vs ADP {wmae(D.adp_curve_f[bkp], D.act_ppg[bkp], D.act_games[bkp]):.3f} (n {int(bkp.sum())})")
    # upside for backups: is the p90 high enough? ratio quantiles pooled vs backup-specific
    ratios = ratio_table(D, "pg_base", PM.TEST_YEARS)

    # ================= FIX 4
    P("\n=== FIX 4. Games distribution recalibration (walk-forward isotonic) ===")
    D["gshare"] = (D.act_games / D.G).clip(0, 1)
    pb_cal, g_cal = calibrate_dist(D.assign(g_pb0=pb_base[:, 0], g_pb1=pb_base[:, 1], g_pb2=pb_base[:, 2], g_pb3=pb_base[:, 3]), PM.TEST_YEARS)
    D["g_cal"] = g_cal
    for lab, pbx in (("before (A2)", pb_base), ("after recalibration", pb_cal)):
        P(f"  {lab}:")
        cal_table(D, pbx, pool, "ADP top 150")
        for ps in PM.POS4: cal_table(D, pbx, pool & (D.pos == ps), ps)
        for al, mk in (("age <= 25", D.age <= 25), ("26-28", D.age.between(25.01, 28.99)), ("29+", D.age >= 29)): cal_table(D, pbx, pool & mk, al)
    for lab, pbx in (("before", pb_base), ("after", pb_cal)):
        c = mc_cover(D.assign(G=D.G), "pg_base", pbx, pool & D.season.isin(PM.TEST_YEARS[2:]), ratios)
        P(f"  season-total coverage {lab}: p10-p90 {c[(.1,.9)][0]:.1f}% (below {c[(.1,.9)][1]:.1f} / above {c[(.1,.9)][2]:.1f}) | p25-p75 {c[(.25,.75)][0]:.1f}% (below {c[(.25,.75)][1]:.1f} / above {c[(.25,.75)][2]:.1f}) | n {c[(.1,.9)][3]}")

    # ================= COMBINED + each fix alone (before / after table)
    P("\n=== Before / after (each fix alone, then all) ===")
    best1 = "g_shrink last season (est.)"
    D["tot_base"] = D.pg_base * D.g_base * D.G
    D["tot_fix1"] = D.pg_base * D[best1] * D.G
    D["tot_fix2"] = D["pg_+takeover prob"] * D.g_rbfix * D.G
    D["tot_fix4"] = D.pg_base * D.g_cal * D.G
    # all: fix1 games features + fix2 + calibration of that games model
    Oa = GM.walk(D, [f if f != "gs1" else "gs1_shrunk" for f in GM.GF] + ["rb_age_x_load", "p_take_f"], "all")
    pb_all_raw = np.column_stack([0.8 * Oa[f"all_pb{k}"] + 0.2 * base_rates[k] for k in range(4)])
    pb_all, g_all = calibrate_dist(D.assign(g_pb0=pb_all_raw[:, 0], g_pb1=pb_all_raw[:, 1], g_pb2=pb_all_raw[:, 2], g_pb3=pb_all_raw[:, 3]), PM.TEST_YEARS)
    D["g_all"] = 0.75 * (0.75 * Oa.all_ridge + 0.25 * Oa.all_dist).values + 0.25 * g_all   # ridge mean kept, distribution recalibrated
    D["tot_all"] = D["pg_+takeover prob"] * D.g_all * D.G
    D["pg_all"] = D["pg_+takeover prob"]
    for lab, mk in (("dev 2015-22", pdev), ("holdout 2023-25", phold), ("all 2015-25", pool)):
        per_game_grade(D, ["pg_base", "pg_all", "adp_curve_f"], mk, f"per-game {lab}")
        total_grade(D, ["tot_base", "tot_fix1", "tot_fix2", "tot_fix4", "tot_all", "adp_total"], mk, f"totals {lab}")
    for ps in PM.POS4:
        per_game_grade(D, ["pg_base", "pg_all", "adp_curve_f"], pool & (D.pos == ps), f"per-game {ps}")
        total_grade(D, ["tot_base", "tot_all", "adp_total"], pool & (D.pos == ps), f"totals {ps}")
    per_game_grade(D, ["pg_base", "pg_all", "adp_curve_f"], pool & (D.rookie == 1), "per-game rookies")
    total_grade(D, ["tot_base", "tot_all", "adp_total"], pool & (D.rookie == 1), "totals rookies")
    ratios_all = ratio_table(D, "pg_all", PM.TEST_YEARS)
    for lab, col, pbx in (("base", "pg_base", pb_base), ("all fixes", "pg_all", pb_all)):
        c = mc_cover(D, col, pbx, pool & D.season.isin(PM.TEST_YEARS[2:]), ratios_all if col == "pg_all" else ratios)
        P(f"  coverage {lab}: p10-p90 {c[(.1,.9)][0]:.1f}% (below {c[(.1,.9)][1]:.1f} / above {c[(.1,.9)][2]:.1f}) | p25-p75 {c[(.25,.75)][0]:.1f}%")
    P("  QB ordering (fix 1 is the only one that touches QBs): per-game rho unchanged by construction; totals:")
    total_grade(D, ["tot_base", "tot_fix1", "adp_total"], pool & (D.pos == "QB"), "QB totals")
    keep = ["season", "pid", "name", "pos", "est", "short1", "p_take", "took_over", "g_base", best1, "g_rbfix", "g_cal", "g_all", "pg_base", "pg_all", "tot_base", "tot_all", "adp_total", "act_total", "act_ppg", "act_games"]
    D[keep].to_parquet(os.path.join(HERE, "data", "fixes_a9_rows.parquet"), index=False)
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
