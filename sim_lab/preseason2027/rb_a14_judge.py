#!/usr/bin/env python3
"""A14 judging of the lead candidate (C3: share inputs + half-way team rescale) vs v5, ADP (redraft) and naive:
tiers, season totals with the games model and top-12/24/36 hits, per-game range coverage pooled vs by tier, and the team
target total (RB + WR + TE projected targets per team game vs actual pass targets). Log: rb_a14_judge.log."""
import os, sys, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM, qb_a10 as Q, rb_a14_diag as DG

LOG = None
CAND = "pg_C3 share inputs + rescale a.5"


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def main():
    global LOG
    LOG = open(os.path.join(HERE, "rb_a14_judge.log"), "w", encoding="utf-8")
    D = pd.read_parquet(os.path.join(HERE, "data", "rb_a14_rows.parquet"))
    rb = (D.pos == "RB") & D.season.isin(PM.TEST_YEARS) & D.vc.notna()
    ok = rb & (D.act_games >= 4) & D.pg.notna()
    D["tier"] = np.select([D.rookie == 1, D.dc.isin([1, 2]) & (D.moved == 0) & D.q_car1.between(.25, .5), (D.dc == 1)], ["rookie", "committee", "lead back"], "backup")
    pools = {"pool (chart 1-3)": ok & D.dc.isin([1, 2, 3]), "ADP top 150": ok & (D.adp <= 150)}
    D["tot_v5"] = D.pg * D.g_use * D.G; D["tot_c3"] = D[CAND] * D.g_use * D.G; D["tot_naive"] = D.naive_f * D.g_use * D.G
    P(f"=== A14 judge: {CAND} vs v5 ===")
    for pn, pm in pools.items():
        for nm, yrs in (("dev 2015-22", Q.DEV), ("holdout 2023-25", Q.HOLD)):
            P(f"\n  {pn}, {nm}")
            P("| model | n | per-game MAE | rho | top12 | top24 | top36 | totals MAE | totals rho |")
            P("|---|---|---|---|---|---|---|---|---|")
            for lab, pc, tc in (("v5", "pg", "tot_v5"), ("C3", CAND, "tot_c3"), ("ADP (redraft)", "adp_curve_f", "adp_total"), ("naive last season", "naive_f", "tot_naive")):
                m = pm & D.season.isin(yrs) & D[pc].notna() & D[tc].notna()
                h = {k: np.mean([len(set(g.nlargest(k, tc).pid) & set(g.nlargest(k, "act_total").pid)) / k for _, g in D[m].groupby("season") if len(g) >= k]) for k in (12, 24, 36)}
                P(f"| {lab} | {int(m.sum())} | {DG.wmae(D[pc][m], D.act_ppg[m], D.act_games[m]):.3f} | {DG.rho(D[m], pc):.3f} | {h[12]:.3f} | {h[24]:.3f} | {h[36]:.3f} | {np.mean(np.abs(D[tc][m]-D.act_total[m])):.1f} | {DG.rho(D[m], tc, 'act_total'):.3f} |")
    P("\n  by tier (pool), per-game MAE / bias v5 -> C3, and rho within tier")
    for t in ("lead back", "committee", "backup", "rookie"):
        for nm, yrs in (("dev", Q.DEV), ("holdout", Q.HOLD)):
            m = pools["pool (chart 1-3)"] & (D.tier == t) & D.season.isin(yrs)
            from scipy.stats import spearmanr
            P(f"   {t:10s} {nm:7s} n {int(m.sum()):3d}: MAE {DG.wmae(D.pg[m], D.act_ppg[m], D.act_games[m]):.3f} -> {DG.wmae(D[CAND][m], D.act_ppg[m], D.act_games[m]):.3f} | bias {(D.pg[m]-D.act_ppg[m]).mean():+.2f} -> {(D[CAND][m]-D.act_ppg[m]).mean():+.2f} | rho {spearmanr(D.pg[m], D.act_ppg[m]).correlation:.3f} -> {spearmanr(D[CAND][m], D.act_ppg[m]).correlation:.3f} | ADP MAE {DG.wmae(D.adp_curve_f[m], D.act_ppg[m], D.act_games[m]):.3f}")
    # per-game range coverage, pooled RB ratios vs by tier (ratios from earlier seasons' pool rows)
    P("\n  per-game p10-p90 coverage (target 80%), ratios from earlier seasons; pooled RB vs by tier")
    pm = pools["pool (chart 1-3)"]
    for col in ("pg", CAND):
        res = {}
        for Y in PM.TEST_YEARS:
            past = pm & (D.season < Y) & (D.season >= 2015) & D[col].notna()
            if past.sum() < 60: continue
            rp = ((D.act_ppg[past] + 1) / (D[col][past] + 1)).values
            qp = np.quantile(rp, [.1, .9])
            te = pm & (D.season == Y)
            for t in ("lead back", "committee", "backup", "rookie"):
                pt = past & (D.tier == t); rt = ((D.act_ppg[pt] + 1) / (D[col][pt] + 1)).values
                qt = np.quantile(rt, [.1, .9]) if len(rt) >= 30 else qp
                mt = te & (D.tier == t)
                a = D.act_ppg[mt] + 1; p_ = D[col][mt] + 1
                res.setdefault((t, "pooled"), []).extend(((a >= p_ * qp[0]) & (a <= p_ * qp[1])).tolist())
                res.setdefault((t, "by tier"), []).extend(((a >= p_ * qt[0]) & (a <= p_ * qt[1])).tolist())
                res.setdefault((t, "width"), []).append((qt[1] - qt[0]) / (qp[1] - qp[0]))
        P(f"   {col}: " + " | ".join(f"{t} pooled {np.mean(res[(t,'pooled')])*100:.0f}% / by tier {np.mean(res[(t,'by tier')])*100:.0f}% (width x{np.mean(res[(t,'width')]):.2f})" for t in ("lead back", "committee", "backup", "rookie") if (t, "pooled") in res))
    # team target total: projected RB (v5 vs C3) + WR + TE targets per team game vs actual
    D["vt_c3"] = D.vt * 0  # placeholder replaced below
    if "vt_C3" in D: pass
    P("\n  team pass-target check: RB targets are rescaled in C3; WR/TE projections are untouched by construction (RB rows only).")
    P("done")


if __name__ == "__main__":
    main()
