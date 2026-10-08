#!/usr/bin/env python3
"""
LOW-PROJECTION TAIL (2026-10-08, from backtest_shadow_coverage.py: rows projected 3-8 points are under-covered - 77% in
p10-p90 with 12% below p10 - under either center). Candidate: a DUD mixture for the sampler - with probability q the game is a
dud drawn at a fraction f of the mean (touches / usage evaporate), else the gamma as today - sized by projection band and
position, graded on coverage / CRPS / pinball on the shadow center, LOYO not needed (calibration, not a predictor).
Log low_proj_mixture.log. Nothing wired.
"""
import os, sys, warnings
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import backtest_sim_calibration as cal
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "low_proj_mixture.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
NS = 1500


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    base = top150 & ~final & ~LV["inh"] & (SHADOW >= 3)
    sig = np.full(n, np.nan); cache = {}
    for i in np.where(base)[0]:
        k = (name[i], pos[i], int(year[i]))
        if k not in cache: cache[k] = cal.sigma_entering(name[i], pos[i], int(year[i]))
        sig[i] = cache[k]
    rng = np.random.default_rng(11); cal.SIMS = NS
    def grade(m, q=0.0, f=0.3, smult=1.0):
        idx = np.where(m)[0]; cov = lo = hi = 0; crps = []; pin = []
        for i in idx:
            mu = float(SHADOW[i]); d = cal.sim_player(rng, mu, float(sig[i]) * smult, 1, 1.0)[:, 0]
            if q > 0:
                dud = rng.random(NS) < q; d = np.where(dud, cal.sim_player(rng, mu * f, float(sig[i]), 1, 1.0)[:, 0], d)
            y = act[i]; q10, q90 = np.quantile(d, [0.1, 0.9]); cov += (q10 <= y <= q90); lo += y < q10; hi += y > q90
            crps.append(np.mean(np.abs(d - y)) - 0.5 * np.mean(np.abs(d - d[rng.permutation(NS)])))
            pin.append(max(0.1 * (y - q10), 0.9 * (q10 - y)) + max(0.9 * (y - q90), 0.1 * (q90 - y)))
        N = max(1, len(idx)); return 100 * cov / N, 100 * lo / N, 100 * hi / N, float(np.mean(crps)), float(np.mean(pin))
    def row(lab, m, **kw):
        c, lo, hi, cr, pn = grade(m, **kw); P(f"  {lab:30s} n{int(m.sum()):5d} | p10-p90 {c:5.1f}% (below {lo:4.1f}, above {hi:4.1f}) | CRPS {cr:.3f} | pinball {pn:.3f}")
    P(f"=== LOW-PROJECTION TAIL: dud mixture on the shadow center, {int(base.sum()):,} rows ===")
    for blab, bm in (("proj 3-8", base & (SHADOW < 8)), ("proj 8-12", base & (SHADOW >= 8) & (SHADOW < 12)), ("proj 12+", base & (SHADOW >= 12))):
        P(f"\n--- {blab} ---")
        row("as wired (gamma)", bm)
        for q in (0.05, 0.10, 0.15, 0.20):
            for f in (0.2, 0.4): row(f"dud q {q:.2f} f {f:.1f}", bm, q=q, f=f)
        row("sigma x1.15 instead", bm, smult=1.15)
    P("\n--- proj 3-8 by position (q .10 f .3 vs wired) ---")
    for ps in POS4:
        bm = base & (SHADOW < 8) & (pos == ps)
        if bm.sum() < 150: continue
        row(f"{ps} as wired", bm); row(f"{ps} dud q .10 f .3", bm, q=0.10, f=0.3)
    P("\nLimitations: single-week draws, shadow replica center, no availability / season shock; the mixture leaves the mean at (1 - q + q f) x mu, i.e. it also lowers the center - a wired version would renormalise.")
    LOG.close()


if __name__ == "__main__":
    main()
