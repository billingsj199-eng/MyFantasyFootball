#!/usr/bin/env python3
"""Leave-one-piece-out ablation for pergame_model (2026-11-21). Same walk-forward; dev 2015-22 / final 2023-25. Log: pergame_ablation.log."""
import os, sys, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM
import pergame_model as G

LOG = None


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def main():
    global LOG
    LOG = open(os.path.join(HERE, "pergame_ablation.log"), "w", encoding="utf-8")
    t0 = time.time()
    D = PM.build(); S = G.stat_seasons(); D = G.add_history(D, S); D = G.add_context(D, S)
    R0 = PM.walk_forward(D)
    for c in ("ridge_stats", "adp_curve_f"): D[c] = R0[c].values
    pool = D.season.isin(PM.TEST_YEARS) & D.adp.notna() & (D.adp <= 150) & (D.act_games >= 4)
    full = G.BASIC + G.TEAM + G.ROSTER + G.EXPER
    variants = [("S4 full", full, True), ("- team context", G.BASIC + G.ROSTER + G.EXPER, True), ("- roster changes", G.BASIC + G.TEAM + G.EXPER, True),
                ("- JM", [f for f in full if f != "jm_young"], True), ("- yr2/yr3 flags", [f for f in full if f not in ("yr2", "yr3")], True),
                ("- rookie efficiency prior", full, False), ("basic + roster + experience (no team, no RB extras)", G.BASIC + G.ROSTER + G.EXPER, True)]
    P("variant | dev 2015-22 MAE / rho | final 2023-25 MAE / rho   (old in-house ridge dev 2.747/.439, final 2.629/.429; ADP dev 2.479/.554, final 2.519/.532)")
    for lab, feats, rp in variants:
        pr, _, _ = G.walk(D, feats, "v", use_role_prior=rp); D["v"] = pr.values
        res = []
        for yrs in (G.DEV, G.FINAL):
            m = pool & D.season.isin(yrs) & D.v.notna()
            mae = G.wmae(D.v[m], D.act_ppg[m], D.act_games[m])
            rho = np.nanmean([__import__("scipy.stats").stats.spearmanr(g.v, g.act_ppg).correlation for _, g in D[m].groupby(["season", "pos"]) if len(g) >= 12])
            res.append(f"{mae:.3f} / {rho:.3f}")
        P(f"  {lab:52s} | {res[0]} | {res[1]}")
    # JM on rookies + year-2 only (where it is used)
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
