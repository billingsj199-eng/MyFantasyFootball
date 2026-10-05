#!/usr/bin/env python3
"""
OWN TEAM TOTALS - how much should the PRESEASON rating count, and does it deserve MORE weight early?
(Jack 2026-10-02: "did we backtest future team totals based on results of past weeks and early in the season
factoring the preseason totals more?")

The shipped form (backtest_own_totals.py: ratings + quarterback + weather + results + new-QB dock, live timing)
re-run with the pull toward the preseason rating varied:
  ridge       0.5 / 1 / 2 (shipped) / 4 / 8 / 16      bigger = the preseason rating counts for more
  results     x0 / x0.5 / x1 (shipped schedule .10 / .15 / .20) / x1.5
by checkpoint (standing after week 2 / 3 / 4 / 6 / 8 / 10 / 12), graded against the lines the book eventually closed
at and against the points actually scored. The best setting per checkpoint is picked leave-one-season-out.
2019-25 caveat: the "preseason rating" is a proxy (last season's final nine weeks + the week-1 lines); the real
2026 preseason lines are sharper, so 2026 walk-forward is printed too. Log own_totals_prior.log.
"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_future_totals as F
import backtest_future_totals_live_form as LF
import backtest_own_totals as OT
import build_future_totals as B
YEARS = OT.YEARS; CHECK = OT.CHECK
LAMS = (0.5, 1.0, 2.0, 4.0, 8.0, 16.0); RMS = (0.0, 0.5, 1.0, 1.5)

def main():
    sys.stdout = F.Tee(sys.__stdout__, open(os.path.join(HERE, "own_totals_prior.log"), "w", encoding="utf-8"))
    BR = OT.base_rows(); rec = []
    for Y in YEARS:
        cur, a = BR[Y]
        for W in CHECK:
            LW = W + 1
            obs = cur[(cur.wk >= 2) & (cur.wk <= LW)]; fut = cur[cur.wk > LW].copy()
            if obs.empty or fut.empty: continue
            w = 0.5 ** ((LW - obs.wk.values) / B.HL); d = (obs.imp - obs.p0).values - obs.wx.values
            seen = set((obs.team + "|" + obs.qb).values)
            newqb = ((~fut.is_opener) & ~(fut.team + "|" + fut.qb).isin(seen)).astype(float).values
            po = obs[obs.wk <= W]; pw = 0.5 ** ((W - po.wk.values) / B.HL)
            so = po.assign(s=(po.pts - po.imp) * pw, ww=pw).groupby("team")[["s", "ww"]].sum(); so = (so.s / (so.ww + 1.0)).to_dict()
            sd = po.assign(s=(po.pts - po.imp) * pw, ww=pw).groupby("opp")[["s", "ww"]].sum(); sd = (sd.s / (sd.ww + 1.0)).to_dict()
            surp = fut.team.map(so).fillna(0).values + fut.opp.map(sd).fillna(0).values
            rw = 0.10 if W < 3 else (0.15 if W < 8 else 0.20)
            # share of the in-season shift that survives the ridge = how far the rating has moved off preseason
            for lam in LAMS:
                LF.LAM = lam
                sh = LF.fit_hier(obs, d, w, OT.LAM_Q, lam_t=lam)(fut)
                for rm in RMS:
                    fut[f"L{lam}_R{rm}"] = fut.p0.values + sh + rm * rw * surp - 3.0 * newqb
            LF.LAM = B.LAM
            fut["none"] = fut.p0.values; fut["year"] = Y; fut["W"] = W; rec.append(fut)
    R = pd.concat(rec, ignore_index=True)
    cols = [f"L{l}_R{r}" for l in LAMS for r in RMS]
    mae = lambda x, c: np.abs(x[c] - x.imp).mean()
    mse = lambda x, c: ((x[c] - x.pts) ** 2).mean()
    print("=== own team totals: weight of the preseason rating by point in the season (2019-25, live timing) ===")
    print("\n  miss vs the eventual closing line, results at the shipped schedule; ridge across (bigger = more preseason):")
    print("    standing after   never updated   " + "   ".join(f"ridge {l:<4}" for l in LAMS) + "   best (LOSO picks)")
    for W in CHECK:
        x = R[R.W == W]
        picks = [min(LAMS, key=lambda l: mae(x[x.year != Y], f"L{l}_R1.0")) for Y in YEARS]
        print(f"    week {W:<2}          {mae(x, 'none'):.3f}           " + "   ".join(f"{mae(x, f'L{l}_R1.0'):.3f}     " for l in LAMS) + f"  {picks}")
    print("\n  same, graded on POINTS ACTUALLY SCORED (MSE vs the shipped ridge 2, %):")
    for W in CHECK:
        x = R[R.W == W]; b = mse(x, "L2.0_R1.0")
        picks = [min(LAMS, key=lambda l: mse(x[x.year != Y], f"L{l}_R1.0")) for Y in YEARS]
        print(f"    week {W:<2}   " + "   ".join(f"ridge {l}: {100*(mse(x, f'L{l}_R1.0')/b-1):+.2f}%" for l in LAMS) + f"   picks {picks}")
    print("\n  results weight (x the shipped schedule), ridge 2 - miss vs closing line / points MSE vs shipped:")
    for W in CHECK:
        x = R[R.W == W]; b = mae(x, "L2.0_R1.0"); bq = mse(x, "L2.0_R1.0")
        picks = [min(RMS, key=lambda r: mae(x[x.year != Y], f"L2.0_R{r}")) for Y in YEARS]
        print(f"    week {W:<2}   " + "   ".join(f"x{r}: {100*(mae(x, f'L2.0_R{r}')/b-1):+.2f}% / {100*(mse(x, f'L2.0_R{r}')/bq-1):+.2f}%" for r in RMS) + f"   picks {picks}")
    # a schedule: per-checkpoint LOSO-picked (ridge, results) vs the flat shipped setting
    tot_s = tot_b = n = 0; wins = 0
    for Y in YEARS:
        es = eb = m = 0
        for W in CHECK:
            tr, te = R[(R.W == W) & (R.year != Y)], R[(R.W == W) & (R.year == Y)]
            if te.empty: continue
            c = min(cols, key=lambda c: mae(tr, c))
            es += np.abs(te[c] - te.imp).sum(); eb += np.abs(te["L2.0_R1.0"] - te.imp).sum(); m += len(te)
        tot_s += es; tot_b += eb; n += m; wins += es < eb
    print(f"\n  a week-by-week schedule (ridge and results weight re-picked at every checkpoint, leave-one-season-out) vs the flat shipped setting: "
          f"{tot_s/n:.3f} vs {tot_b/n:.3f} ({100*(tot_s/tot_b-1):+.2f}%, {wins}/7 seasons)")
    for lam in (1.0, 4.0):
        t = sum(np.abs(R[f'L{lam}_R1.0'] - R.imp).sum() for _ in [0]) / len(R)
        ws = sum(mae(R[R.year == Y], f"L{lam}_R1.0") < mae(R[R.year == Y], "L2.0_R1.0") for Y in YEARS)
        print(f"  flat ridge {lam} everywhere: {t:.3f} ({100*(t/mae(R, 'L2.0_R1.0')-1):+.2f}% vs shipped, {ws}/7 seasons)")

if __name__ == "__main__":
    main()
