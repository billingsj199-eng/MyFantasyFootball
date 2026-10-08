#!/usr/bin/env python3
"""
DISTRIBUTION COVERAGE UNDER THE SHADOW MEAN (Jack 2026-10-08 "what else can we test"; the sigma was calibrated in July
against Clay's center, the published mean is now the shadow's). For every top-150 player-week 2019-25 the engine's own
sampler (backtest_sim_calibration.sim_player: gamma draws, sigma = 3-yr weighted CV entering the season, RESID_SHRINK,
ENV_BETA) is run around three centers - Clay's live form, the shadow, the retired blend - and graded on the actual:
  p10-p90 coverage (target 80%), share below p10 / above p90 (target 10 / 10), CRPS, pinball loss at .1 / .9, by position,
  by projection size and by games played; then sigma multipliers x.8 .. x1.2 on the shadow center to see whether the
  width wants re-fitting. Log shadow_coverage.log. Nothing wired.
"""
import os, sys, warnings
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import backtest_sim_calibration as cal
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "shadow_coverage.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
BBW = {"QB": 0.5, "RB": 0.8, "WR": 0.7, "TE": 0.0}
NS = 1500


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    bw = np.array([BBW[p_] for p_ in pos]); BLEND = bw * SHADOW + (1 - bw) * TODAY
    base = top150 & ~final & ~LV["inh"] & (TODAY >= 3) & (SHADOW >= 3)
    sig = np.full(n, np.nan); cache = {}
    for i in np.where(base)[0]:
        k = (name[i], pos[i], int(year[i]))
        if k not in cache: cache[k] = cal.sigma_entering(name[i], pos[i], int(year[i]))
        sig[i] = cache[k]
    P(f"=== COVERAGE: {int(base.sum()):,} top-150 player-weeks 2019-25; sigma = engine's entering-season CV (median {np.nanmedian(sig[base]):.3f}), sampler = engine gamma replica, {NS} draws ===")
    rng = np.random.default_rng(7); cal.SIMS = NS
    def grade(mean, m, smult=1.0):
        idx = np.where(m)[0]; cov = lo = hi = 0; crps = []; pin = []
        for i in idx:
            d = cal.sim_player(rng, float(mean[i]), float(sig[i]) * smult, 1, 1.0)[:, 0]; y = act[i]
            q10, q90 = np.quantile(d, [0.1, 0.9]); cov += (q10 <= y <= q90); lo += y < q10; hi += y > q90
            crps.append(np.mean(np.abs(d - y)) - 0.5 * np.mean(np.abs(d - d[rng.permutation(NS)])))
            pin.append(max(0.1 * (y - q10), 0.9 * (q10 - y)) + max(0.9 * (y - q90), 0.1 * (q90 - y)))
        N = max(1, len(idx)); return 100 * cov / N, 100 * lo / N, 100 * hi / N, float(np.mean(crps)), float(np.mean(pin))
    def row(lab, mean, m, smult=1.0):
        c, lo, hi, cr, pn = grade(mean, m, smult)
        P(f"  {lab:34s} n{int(m.sum()):5d} | p10-p90 {c:5.1f}% (below {lo:4.1f}, above {hi:4.1f}) | CRPS {cr:.3f} | pinball {pn:.3f} | level act/mean {act[m].sum()/mean[m].sum():.3f}")
    for lab, mm in (("ALL", base), *[(ps, base & (pos == ps)) for ps in POS4], ("proj >= 15", base & (SHADOW >= 15)), ("proj 8-15", base & (SHADOW >= 8) & (SHADOW < 15)), ("proj 3-8", base & (SHADOW < 8)), ("games 0-3", base & (g <= 3)), ("games 4+", base & (g >= 4))):
        P(f"\n--- {lab} ---")
        for clab, c in (("Clay form (July center)", TODAY), ("shadow (live center)", SHADOW), ("retired blend", BLEND)): row(clab, c, mm)
    P("\n--- sigma multipliers on the SHADOW center (whole board) ---")
    for sm in (0.8, 0.9, 1.0, 1.1, 1.2): row(f"shadow, sigma x{sm:.1f}", SHADOW, base, sm)
    P("\n--- sigma multipliers on the shadow center, by position ---")
    for ps in POS4:
        for sm in (0.9, 1.0, 1.1): row(f"{ps} sigma x{sm:.1f}", SHADOW, base & (pos == ps), sm)
    P("\nLimitations: single-week draws (no season shock, no availability), replica centers (no book anchor / docks), sigma from the python replica of the engine build; ~1,500 draws per row.")
    LOG.close()


if __name__ == "__main__":
    main()
