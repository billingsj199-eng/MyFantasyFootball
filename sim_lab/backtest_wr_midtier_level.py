#!/usr/bin/env python3
"""
WR MID-TIER LEVEL (Jack 2026-10-08: "the middle tier of WR seem overall low"). The honest replica has the shadow 5% low on
WR ADP 31-60 and 4.5% low on 61-100 (tier_treatment.log); the whole band x position multiplier grid failed forward, but that
grid fit 20 cells at once. Here the single cells: a level multiplier on WR 31-60, on WR 61-100, and on WR 31-100 together,
LOYO + forward with the bar (5/7 + 3/4, LOYO < -0.3% on the cell), whole-board guard, rank line, cubed top-100 weights beside
the squared top-150. Log wr_midtier_level.log.
"""
import os, sys, warnings
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "wr_midtier_level.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & (adpx <= 150)].mean()
    wt2 = np.maximum(0.05, lv) ** 2; wt3 = np.maximum(0.05, lv) ** 3
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    base = (adpx <= 150) & ~final & ~LV["inh"] & (SHADOW >= 3)
    w2 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt2[m])) if m.any() else np.nan
    w3 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt3[m])) if m.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    P(f"=== WR MID-TIER LEVEL: level act/shadow by WR band: " + " | ".join(f"{lab} {act[base & (pos == 'WR') & bm].sum()/SHADOW[base & (pos == 'WR') & bm].sum():.3f} (n{int((base & (pos == 'WR') & bm).sum())})" for lab, bm in (("1-12", adpx <= 12), ("13-30", (adpx > 12) & (adpx <= 30)), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100)), ("101-150", adpx > 100))))
    P("    by season, WR 31-100: " + " ".join(f"{y}:{act[base & (pos == 'WR') & (adpx > 30) & (adpx <= 100) & (year == y)].sum()/SHADOW[base & (pos == 'WR') & (adpx > 30) & (adpx <= 100) & (year == y)].sum():.3f}" for y in YEARS))
    def test(title, m):
        preds = {"off": SHADOW}
        for k in (1.02, 1.04, 1.06, 1.08): p = SHADOW.copy(); p[m] = SHADOW[m] * k; preds[f"x{k}"] = p
        names = list(preds); pick = lambda yrs: min(names, key=lambda kk: w2(preds[kk], m & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = SHADOW.copy()
            for tr_, te in folds:
                kk = pick(tr_); picks.append(kk); mm = year == te; pr[mm] = preds[kk][mm]; wins += w2(preds[kk], m & mm) < w2(SHADOW, m & mm) - 1e-12
            tem = np.isin(year, [te for _, te in folds]); return 100 * (w2(pr, m & tem) / w2(SHADOW, m & tem) - 1), 100 * (w2(pr, base & tem) / w2(SHADOW, base & tem) - 1), wins, picks, pr
        lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
        fixed = "  ".join(f"{kk}: {100*(w2(preds[kk], m)/w2(SHADOW, m)-1):+.2f}% ({sum(1 for y in YEARS if w2(preds[kk], m & (year == y)) < w2(SHADOW, m & (year == y)) - 1e-12)}/7)" for kk in names[1:])
        okk = best != "off" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
        P(f"\n  {title} (rows {int(m.sum()):,}, act/shadow {act[m].sum()/SHADOW[m].sum():.3f})"); P(f"    fixed: {fixed}")
        P("    " + RG.rank_line(preds, m, act, year, wk, pos))
        t100 = base & (adpx <= 100); pr = lo[4]
        P(f"    LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | top-100 cubed {100*(w3(pr, t100)/w3(SHADOW, t100)-1):+.3f}% | picks {lo[3]}"); P(f"    FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}"); P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
    WR = base & (pos == "WR")
    test("WR ADP 31-60 level", WR & (adpx > 30) & (adpx <= 60))
    test("WR ADP 61-100 level", WR & (adpx > 60) & (adpx <= 100))
    test("WR ADP 31-100 level (one multiplier)", WR & (adpx > 30) & (adpx <= 100))
    test("WR ADP 13-100 level (one multiplier)", WR & (adpx > 12) & (adpx <= 100))
    P("\nLimitations: honest replica, next game, no book anchor (live the prop anchor pulls ~57% of any model lift back toward the lines).")
    LOG.close()


if __name__ == "__main__":
    main()
