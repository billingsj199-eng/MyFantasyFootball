#!/usr/bin/env python3
"""TE blend weight on the RANK objective (2026-10-08 follow-up to rank_regrade: TE .3 reads -0.008 rho vs Clay alone).
Grid w 0 .. .5 for TE rows only; rank rho / pairs / weighted error vs w 0; LOYO + forward picks on rank and on error. Log te_blend_rank.log."""
import os, sys, warnings
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "te_blend_rank.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    TE = top150 & ~final & ~LV["inh"] & (pos == "TE")
    wm = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    RS = lambda p, m: RG.rank_stats(p, m, act, year, wk, pos)
    WG = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7)
    bl = {w: w * SHADOW + (1 - w) * TODAY for w in WG}
    P(f"=== TE BLEND WEIGHT on the rank objective: {int(TE.sum()):,} top-150 TE player-weeks 2019-25 (w 0 = Clay-side live form alone) ===")
    r0, p0 = RS(bl[0.0], TE)
    for w in WG:
        r, pr = RS(bl[w], TE); wins = RG.rank_seasons(bl[w], bl[0.0], TE, act, year, wk, pos, YEARS); ew = sum(1 for y in YEARS if wm(bl[w], TE & (year == y)) < wm(bl[0.0], TE & (year == y)) - 1e-12)
        P(f"  w {w:.1f}: rho {r:.4f} ({r - r0:+.4f}, better in {wins}/7) | pairs {pr:.2f}% ({pr - p0:+.2f}) | wtd error {100*(wm(bl[w], TE)/wm(bl[0.0], TE)-1):+.2f}% ({ew}/7) | by season rho " + " ".join(f"{y}:{RS(bl[w], TE & (year == y))[0] - RS(bl[0.0], TE & (year == y))[0]:+.3f}" for y in YEARS))
    for lab, cm in (("ADP <= 60", adpx <= 60), ("ADP 61-150", adpx > 60), ("games 1-3", g <= 3), ("games 4+", g >= 4)):
        m = TE & cm; r0_, _ = RS(bl[0.0], m)
        P(f"  {lab:12s} n{int(m.sum()):4d} | " + "  ".join(f"w {w:.1f}: rho {RS(bl[w], m)[0] - r0_:+.4f} err {100*(wm(bl[w], m)/wm(bl[0.0], m)-1):+.2f}%" for w in (0.1, 0.2, 0.3, 0.5)))
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    for obj, pick in (("rank", lambda yrs: max(WG, key=lambda w: RS(bl[w], TE & np.isin(year, yrs))[0])), ("error", lambda yrs: min(WG, key=lambda w: wm(bl[w], TE & np.isin(year, yrs))))):
        for flab, folds in (("LOYO", LOSO), ("forward", FORW)):
            picks = [pick(tr) for tr, te in folds]; pr = bl[0.0].copy()
            for (tr, te), w in zip(folds, picks): pr[year == te] = bl[w][year == te]
            tem = TE & np.isin(year, [te for _, te in folds]); r, _ = RS(pr, tem); r0_, _ = RS(bl[0.0], tem)
            P(f"  picked on {obj:5s} {flab:8s}: picks {picks} -> rho {r - r0_:+.4f} vs w 0, error {100*(wm(pr, tem)/wm(bl[0.0], tem)-1):+.2f}%")
    LOG.close()


if __name__ == "__main__":
    main()
