#!/usr/bin/env python3
"""A9 follow-up (fix4c = fix4b + per-game spread from draftable rows only): fix 4 (games distribution) second try + fix 2 upside range for backup RBs. Log: fix4b_a9.log (own log).
Finding from fixes_a9.log: isotonic fitted on the in-house relevance pool does not transfer to draftable players (the ADP pool
is healthier than the relevance pool - a selection the in-house model can't see). Here the calibration is fitted on the
model's OWN top-150 (by its projected season total each season; no ADP) and graded on both pools. Walk-forward throughout."""
import os, sys, time
import numpy as np
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM, games_model as GM, pergame_model as G, fixes_a9 as FX

LOG = None


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def main():
    global LOG
    LOG = open(os.path.join(HERE, "fix4c_a9.log"), "w", encoding="utf-8")
    t0 = time.time()
    D = PM.build(); AV, wk1 = GM.availability(); D = GM.add_features(D, AV, wk1)
    S = G.stat_seasons(); D = G.add_history(D, S); D = G.add_context(D, S); D = FX.add_fix1_features(D)
    R0 = PM.walk_forward(D)
    for c in ("ridge_stats", "adp_curve_f", "adp_total"): D[c] = R0[c].values
    feats = [f if f != "gs1" else "gs1_shrunk" for f in GM.GF]          # fix 1 kept
    O = GM.walk(D, feats, "g"); D = pd.concat([D, O], axis=1)
    D["g_mean"] = 0.75 * D.g_ridge + 0.25 * D.g_dist
    br = {k: np.mean(np.digitize(D.miss[D.rel & D.season.isin(PM.TEST_YEARS)], [2, 4, 8]) == k) for k in range(4)}
    pb0 = np.column_stack([0.8 * D[f"g_pb{k}"] + 0.2 * br[k] for k in range(4)])
    s7, _, _ = G.walk(D, G.BASIC + G.ROSTER + ["lp_rook"], "S7", use_role_prior=True)
    D["pg"] = (0.75 * s7 + 0.25 * D.ridge_stats).values
    D["tot"] = D.pg * D.g_mean * D.G
    D["mtop"] = D.groupby("season").tot.rank(ascending=False) <= 150          # model's own top 150 (in-house selection)
    D["gshare"] = (D.act_games / D.G).clip(0, 1)
    adp_pool = D.season.isin(PM.TEST_YEARS) & D.adp.notna() & (D.adp <= 150)
    mpool = D.season.isin(PM.TEST_YEARS) & D.mtop
    P(f"pools: ADP top 150 n {int(adp_pool.sum())}; model top 150 n {int(mpool.sum())}; overlap {int((adp_pool & mpool).sum())}")
    from sklearn.isotonic import IsotonicRegression
    def recal(pb, fit_mask):
        c = {2: pb[:, 1:].sum(1), 4: pb[:, 2:].sum(1), 8: pb[:, 3]}; out = {k: np.full(len(D), np.nan) for k in c}
        for Y in PM.TEST_YEARS:
            tr = (D.season < Y).values & (D.season >= 2015).values & fit_mask.values; te = (D.season == Y).values
            for k in c:
                if tr.sum() < 150: out[k][te] = c[k][te]; continue
                iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(c[k][tr], (D.miss.values[tr] >= k).astype(float))
                out[k][te] = iso.predict(c[k][te])
        a2, a4, a8 = out[2], np.minimum(out[4], out[2]), None
        a8 = np.minimum(out[8], a4)
        pb2 = np.clip(np.column_stack([1 - a2, a2 - a4, a4 - a8, a8]), 1e-4, None); return pb2 / pb2.sum(1, keepdims=True)
    variants = {"A2 distribution (before)": pb0, "isotonic fit on relevance pool": recal(pb0, D.rel), "isotonic fit on model top 150": recal(pb0, D.mtop)}
    ratios = FX.ratio_table(D.assign(pg_base=D.pg), "pg_base", PM.TEST_YEARS)
    for lab, pb in variants.items():
        P(f"\n{lab}:")
        for pl, mk in (("ADP top 150", adp_pool), ("model top 150", mpool)):
            FX.cal_table(D, pb, mk, pl)
            c = FX.mc_cover(D.assign(pg_base=D.pg), "pg_base", pb, mk & D.season.isin(PM.TEST_YEARS[2:]), ratios)
            P(f"      season-total coverage ({pl}): p10-p90 {c[(.1,.9)][0]:.1f}% (below {c[(.1,.9)][1]:.1f} / above {c[(.1,.9)][2]:.1f}) | p25-p75 {c[(.25,.75)][0]:.1f}% (below {c[(.25,.75)][1]:.1f} / above {c[(.25,.75)][2]:.1f}) n {c[(.1,.9)][3]}")
    # backup RB upside: pooled RB ratio quantiles vs backup-specific (walk-forward), coverage on depth-2 RBs
    bk = adp_pool & (D.pos == "RB") & (D.dc == 2)
    rat_bk = {}
    for Y in PM.TEST_YEARS:
        past = (D.season < Y) & (D.season >= 2015) & (D.pos == "RB") & (D.dc == 2) & (D.act_games >= 4) & D.pg.notna()
        r = ((D.act_ppg[past] + 1) / (D.pg[past] + 1)).values
        for ps in PM.POS4: rat_bk[(Y, ps)] = r if len(r) >= 50 else ratios.get((Y, ps))
    for lab, rt in (("pooled RB spread", ratios), ("backup-RB spread", rat_bk)):
        c = FX.mc_cover(D.assign(pg_base=D.pg), "pg_base", variants["isotonic fit on model top 150"], bk & D.season.isin(PM.TEST_YEARS[2:]), rt)
        P(f"\nbackup RBs (depth 2, ADP top 150) with {lab}: p10-p90 {c[(.1,.9)][0]:.1f}% (below {c[(.1,.9)][1]:.1f} / above {c[(.1,.9)][2]:.1f}) n {c[(.1,.9)][3]}")

    # per-game spread from the model's own top-150 rows only (in-house selection), walk-forward
    rat_top = {}
    for Y in PM.TEST_YEARS:
        for ps in PM.POS4:
            past = (D.season < Y) & (D.season >= 2015) & (D.pos == ps) & (D.act_games >= 4) & D.pg.notna() & D.mtop
            rat_top[(Y, ps)] = ((D.act_ppg[past] + 1) / (D.pg[past] + 1)).values
    for lab, pb in (("A2 distribution", pb0), ("isotonic on model top 150", variants["isotonic fit on model top 150"])):
        for pl, mk in (("ADP top 150", adp_pool), ("model top 150", mpool)):
            c = FX.mc_cover(D.assign(pg_base=D.pg), "pg_base", pb, mk & D.season.isin(PM.TEST_YEARS[2:]), rat_top)
            P(f"PER-GAME SPREAD FROM DRAFTABLE ROWS + {lab} ({pl}): p10-p90 {c[(.1,.9)][0]:.1f}% (below {c[(.1,.9)][1]:.1f} / above {c[(.1,.9)][2]:.1f}) | p25-p75 {c[(.25,.75)][0]:.1f}% (below {c[(.25,.75)][1]:.1f} / above {c[(.25,.75)][2]:.1f})")
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
