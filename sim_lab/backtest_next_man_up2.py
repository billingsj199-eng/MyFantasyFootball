#!/usr/bin/env python3
"""
NEXT MAN UP by TARGETS, not rank (Jack 2026-10-08: "should we instead of looking at target 1, 2 etc look at % of targets or
average targets per game that is out?"). Wired today: rank cells (#1 x1.04, #2-3 x.99, #4-6 x1.03) on top of the vacated pool
(.75) inside the shadow. Here the missing VOLUME drives it: each healthy pass catcher gets
  a x (vacated targets / g) x (his share of the healthy group's trailing targets) x (his trailing receiving pts per target)
added to the shadow, with the pool layer either kept (on top) or removed (replacing it). Also the share-scaled multiplier
1 + b x vacated share, and the rank cells split by the size of the hole (vacated < 6 / >= 6 tgt per game).
Reference = the WIRED rank cells (a variant must beat them: LOYO 5/7 and < -0.3% on the rows, forward 3/4, board guard).
Log next_man_up2.log.
"""
import os, sys, warnings
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import research_next_man_up as R
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "next_man_up2.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    E, CTRL = R.events()
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["adp"], X["name"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & (adpx <= 150)].mean()
    wt2 = np.maximum(0.05, lv) ** 2; wt3 = np.maximum(0.05, lv) ** 3
    TODAY, LV = BR.live_today(X); SH, _ = BR.shadow_current(X)
    pm = np.where(F["on"], np.power(np.maximum(F["pm"], 1e-9), 0.75), 1.0); SH0 = SH / pm   # shadow without the vacated pool
    base = (adpx <= 150) & ~final & ~LV["inh"] & (SH >= 3)
    idx = {(R.nz(name[i]), int(year[i]), int(wk[i])): i for i in range(n)}
    rk = np.zeros(n, int); arp = np.zeros(n); vac = np.zeros(n); vsh = np.zeros(n); hs = np.zeros(n); ppt = np.zeros(n)
    for r in E:
        i = idx.get((R.nz(r["n"]), r["Y"], r["wk"]))
        if i is None or not base[i] or r["rank"] > 6: continue
        rk[i] = r["rank"]; arp[i] = r["absRp"]; vac[i] = r["vac"]; vsh[i] = r["vac"] / max(r["teamTgt"], 1); hs[i] = r["hshare"]
        ppt[i] = r["tr_rp"] / r["tr_tgt"] if r["tr_tgt"] > 0.5 else 0.0
    rows = rk > 0
    cellm = np.where(rk == 1, 1.04, np.where((rk >= 2) & (rk <= 3), 0.99, np.where(rk >= 4, 1.03, 1.0)))
    WIRED = np.where(rows, SH * cellm, SH)
    gain = vac * hs * ppt   # points if he caught ALL his share of the vacated targets at his usual rate
    P(f"=== NEXT MAN UP by targets: {int(rows.sum()):,} absence-week rows | vacated {np.mean(vac[rows]):.1f} tgt/g (share {np.mean(vsh[rows]):.2f}) | full-share gain {np.mean(gain[rows]):.2f} pts | pool lift inside the shadow {np.mean(SH[rows]-SH0[rows]):+.2f} pts ===")
    P("  act - shadow by vacated targets per game: " + " | ".join(f"{lab}: {np.mean(act[mm]-SH[mm]):+.2f} pts vs wired cells {np.mean(act[mm]-WIRED[mm]):+.2f} (n{int(mm.sum())})" for lab, mm in (("< 5", rows & (vac < 5)), ("5-7", rows & (vac >= 5) & (vac < 7)), ("7-9", rows & (vac >= 7) & (vac < 9)), ("9+", rows & (vac >= 9)))))
    P("  act - wired by his share of the healthy group: " + " | ".join(f"{lab}: {np.mean(act[mm]-WIRED[mm]):+.2f} (n{int(mm.sum())})" for lab, mm in (("< .12", rows & (hs < .12)), (".12-.2", rows & (hs >= .12) & (hs < .2)), (".2-.3", rows & (hs >= .2) & (hs < .3)), (".3+", rows & (hs >= .3)))))
    preds = {"wired cells": WIRED, "off (pool only)": SH}
    for a in (0.15, 0.25, 0.35, 0.5):
        preds[f"tgt a {a} + pool"] = np.where(rows, SH + a * gain, SH)
        preds[f"tgt a {a}, no pool"] = np.where(rows, SH0 + a * gain, SH)
        preds[f"tgt a {a} + pool + cells"] = np.where(rows, SH * cellm + a * gain, SH)
    for b in (0.25, 0.5):
        preds[f"share x(1+{b} vsh)"] = np.where(rows, SH * (1 + b * vsh), SH)
    big = vac >= 6
    cm2 = np.where(rk == 1, np.where(big, 1.06, 1.02), np.where((rk >= 2) & (rk <= 3), np.where(big, 1.0, 0.98), np.where(rk >= 4, np.where(big, 1.05, 1.01), 1.0)))
    preds["cells split by hole size"] = np.where(rows, SH * cm2, SH)
    w2 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt2[m])) if m.any() else np.nan
    w3 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt3[m])) if m.any() else np.nan
    m = rows; b0 = WIRED; t100 = base & (adpx <= 100)
    P("\n  fixed, vs the WIRED rank cells (rows squared | seasons better | top-100 cubed board | bands cubed):")
    for kk, p in preds.items():
        if kk == "wired cells": continue
        bands = " ".join(f"{lab}:{100*(w3(p, base & bm)/w3(b0, base & bm)-1):+.2f}" for lab, bm in (("1-12", adpx <= 12), ("13-30", (adpx > 12) & (adpx <= 30)), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100))))
        P(f"    {kk:28s} {100*(w2(p, m)/w2(b0, m)-1):+.2f}% ({sum(1 for y in YEARS if w2(p, m & (year == y)) < w2(b0, m & (year == y)) - 1e-12)}/7) | top-100 {100*(w3(p, t100)/w3(b0, t100)-1):+.3f}% | {bands}")
    P("  " + RG.rank_line(dict(preds, off=WIRED), m, act, year, wk, pos))
    names = list(preds); pick = lambda yrs: min(names, key=lambda kk: w2(preds[kk], m & np.isin(year, yrs)))
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    def run(folds):
        wins = 0; picks = []; pr = b0.copy()
        for tr_, te in folds:
            kk = pick(tr_); picks.append(kk); mx = year == te; pr[mx] = preds[kk][mx]; wins += w2(preds[kk], m & mx) < w2(b0, m & mx) - 1e-12
        tem = np.isin(year, [te for _, te in folds]); return 100 * (w2(pr, m & tem) / w2(b0, m & tem) - 1), 100 * (w2(pr, base & tem) / w2(b0, base & tem) - 1), wins, picks
    # ---- TIER (Jack: "Tee Higgins should get a bigger boost as WR2 than Wicks from DeVonta Smith being out"): absorber quality / absent quality
    good = adpx <= 60; star = arp >= 7.0
    P("\n  act / WIRED by absorber tier x rank group and by the absent player's level (trailing half-PPR receiving pts/g):")
    for lab, gm in (("absorber ADP <= 60", rows & good), ("absorber ADP 61-150", rows & ~good)):
        P(f"    {lab:22s} " + " | ".join(f"{cl} {act[gm & cm].sum()/max(1e-9, WIRED[gm & cm].sum()):.3f} (n{int((gm & cm).sum())})" for cl, cm in (("#1", rk == 1), ("#2-3", (rk >= 2) & (rk <= 3)), ("#4-6", rk >= 4))))
    for lab, gm in (("absent >= 7 pts/g (star)", rows & star), ("absent < 7 pts/g", rows & ~star)):
        P(f"    {lab:22s} " + " | ".join(f"{cl} {act[gm & cm].sum()/max(1e-9, WIRED[gm & cm].sum()):.3f} (n{int((gm & cm).sum())})" for cl, cm in (("#1", rk == 1), ("#2-3", (rk >= 2) & (rk <= 3)), ("#4-6", rk >= 4))))
    P("    by season, ADP<=60 absorbers with a star out: " + " ".join(f"{y}:{act[rows & good & star & (year == y)].sum()/max(1e-9, WIRED[rows & good & star & (year == y)].sum()):.2f}" for y in YEARS))
    rgrp = np.where(rk == 1, 0, np.where(rk <= 3, 1, 2))
    def cellfit(key, train):
        p = WIRED.copy(); tr = np.isin(year, train)
        for kv in np.unique(key[rows]):
            c = rows & (key == kv); mm = c & tr
            k = act[mm].sum() / max(1e-9, WIRED[mm].sum()) if mm.sum() >= 30 else 1.0
            p[c] = WIRED[c] * np.clip(1 + 0.5 * (k - 1), 0.85, 1.2)
        return p
    for lab, key in (("absorber tier (ADP<=60 vs not) x rank group", rgrp * 2 + good.astype(int)), ("absent level (star vs not) x rank group", rgrp * 2 + star.astype(int)),
                     ("absorber tier x absent level", good.astype(int) * 2 + star.astype(int)), ("absorber tier only", good.astype(int))):
        def runc(folds):
            wins = 0; pr = WIRED.copy()
            for tr_, te in folds:
                pp = cellfit(key, tr_); mx = year == te; pr[mx] = pp[mx]; wins += w2(pp, m & mx) < w2(WIRED, m & mx) - 1e-12
            tem = np.isin(year, [te for _, te in folds]); return 100 * (w2(pr, m & tem) / w2(WIRED, m & tem) - 1), 100 * (w2(pr, base & tem) / w2(WIRED, base & tem) - 1), wins, pr
        lo_ = runc(LOSO); fw_ = runc(FORW); pa = cellfit(key, list(YEARS))
        ok_ = lo_[0] < -0.3 and lo_[2] >= 5 and fw_[0] < 0 and fw_[2] >= 3 and lo_[1] <= 0.02
        bands = " ".join(f"{bl}:{100*(w3(pa, base & bm)/w3(WIRED, base & bm)-1):+.2f}" for bl, bm in (("1-12", adpx <= 12), ("13-30", (adpx > 12) & (adpx <= 30)), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100))))
        mults = " ".join(f"{int(kv)}:x{(pa[rows & (key == kv)] / WIRED[rows & (key == kv)]).mean():.3f}(n{int((rows & (key == kv)).sum())})" for kv in np.unique(key[rows]))
        P(f"\n  TIER fit [{lab}] LOYO {lo_[0]:+.2f}% {lo_[2]}/7 | board {lo_[1]:+.3f}% | FWD {fw_[0]:+.2f}% {fw_[2]}/4 | bands {bands} -> {'PASS' if ok_ else 'FAIL'}")
        P(f"    cell multipliers on top of the wired cells (all seasons): {mults}")
    lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
    okk = best != "wired cells" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
    P(f"\n  pick-best vs wired  LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | picks {lo[3]}")
    P(f"                     FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}")
    P(f"  -> {'PASS: ' + best if okk else 'FAIL (wired rank cells stay)'}")
    P("\nLimitations: honest replica next game, no book anchor; trailing 3-game shares; receiving points per target (half PPR) as the value of an absorbed target; the 'cells split by hole size' variant is a hand-set guess, not fit.")
    LOG.close()


if __name__ == "__main__":
    main()
