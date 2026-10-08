#!/usr/bin/env python3
"""
LESS REGRESSION FOR PROVEN PRODUCERS (Jack 2026-10-08: "McBride has produced so well the last 3 years he deserves praise").
The shadow prior pulls every player's history 20% toward the position mean (k .8, fit 2019-25 on all players equally). Here,
on the honest next-game replica, top-150 rows, the pull is softened (k .85 / .9 / .95 / 1.0) for:
  A  ADP <= 30 (WR / TE / RB)
  B  proven: 3 seasons of history (h3) and history >= 1.6x the position mean (McBride ~1.96x)
  C  sliding: k = .8 + .2 x clip((history / mean - 1.2) / .8, 0, 1)  (full k 1.0 at 2x the mean)
by position, LOYO + forward vs the wired k .8 (bar 5/7 + 3/4, < -0.3% on the rows, board guard), cubed top-100 bands, rank line.
Log elite_shrink.log.
"""
import os, sys, warnings
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "elite_shrink.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, adp = X["act"], X["year"], X["wk"], X["pos"], X["adp"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & (adpx <= 150)].mean()
    wt2 = np.maximum(0.05, lv) ** 2; wt3 = np.maximum(0.05, lv) ** 3
    TODAY, LV = BR.live_today(X); SH, _ = BR.shadow_current(X)
    base = (adpx <= 150) & ~final & ~LV["inh"] & (SH >= 3)
    fbp = F["fb_pos"]; Fpr = F["prior"]; unshr = fbp + (Fpr - fbp) / 0.8
    mixw = np.where(np.isclose(X["prior"], Fpr), 1.0, 0.5)   # SN.setup mixes the ridge prior 50/50 for non-QBs
    hist = F["hist"]; h3 = np.array(F.get("has_h3", np.zeros(n, bool)), dtype=bool)
    ratio = np.where(fbp > 0, np.nan_to_num(hist, nan=0.0) / fbp, 0.0)
    skill = np.isin(pos, ("WR", "TE", "RB"))
    def with_k(kvec):
        newF = fbp + kvec * (unshr - fbp)
        X2 = dict(X); X2["prior"] = X["prior"] + mixw * (newF - Fpr)
        return BR.shadow_current(X2)[0]
    P(f"=== LESS REGRESSION FOR PROVEN PRODUCERS: {int(base.sum()):,} board rows | proven (h3 & hist >= 1.6x mean) {int((base & skill & h3 & (ratio >= 1.6)).sum()):,} rows | ADP <= 30 skill {int((base & skill & (adpx <= 30)).sum()):,} ===")
    groups = {"A ADP<=30": skill & (adpx <= 30), "B proven 3 seasons": skill & h3 & (ratio >= 1.6)}
    for ps in ("WR", "TE", "RB"):
        for lab, gm in groups.items():
            m0 = gm & (pos == ps)
            P(f"  {ps} {lab:18s} rows {int((base & m0).sum()):5d} | act / shadow {act[base & m0].sum()/max(1e-9, SH[base & m0].sum()):.3f}")
    P("  position level by season (actual half-PPR per game, board rows; the pull target is the fixed 2019-25 pool mean): " + " | ".join(ps + " " + " ".join(f"{y % 100}:{act[base & (pos == ps) & (year == y)].mean():.2f}" for y in YEARS) for ps in ("TE", "WR", "RB")))
    P("  TE top-12 by ADP, actual per game by season: " + " ".join(f"{y % 100}:{act[base & (pos == 'TE') & (adpx <= 120) & (year == y) & (lv >= np.nanpercentile(lv[base & (pos == 'TE') & (year == y)], 75))].mean():.2f}" for y in YEARS))
    w2 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt2[m])) if m.any() else np.nan
    w3 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt3[m])) if m.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    t100 = base & (adpx <= 100)
    def test(title, m, preds):
        b0 = preds["wired k .8"]; names = list(preds)
        pick = lambda yrs: min(names, key=lambda kk: w2(preds[kk], m & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = b0.copy()
            for tr_, te in folds:
                kk = pick(tr_); picks.append(kk); mx = year == te; pr[mx] = preds[kk][mx]; wins += w2(preds[kk], m & mx) < w2(b0, m & mx) - 1e-12
            tem = np.isin(year, [te for _, te in folds]); return 100 * (w2(pr, m & tem) / w2(b0, m & tem) - 1), 100 * (w2(pr, base & tem) / w2(b0, base & tem) - 1), wins, picks, pr
        lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
        okk = best != names[0] and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
        P(f"\n  {title}  (rows {int(m.sum()):,}, act/shadow {act[m].sum()/max(1e-9, SH[m].sum()):.3f})")
        for kk in names[1:]:
            p = preds[kk]
            bands = " ".join(f"{bl}:{100*(w3(p, base & bm)/w3(b0, base & bm)-1):+.2f}" for bl, bm in (("1-12", adpx <= 12), ("13-30", (adpx > 12) & (adpx <= 30)), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100))))
            P(f"    {kk:12s} rows {100*(w2(p, m)/w2(b0, m)-1):+.2f}% ({sum(1 for y in YEARS if w2(p, m & (year == y)) < w2(b0, m & (year == y)) - 1e-12)}/7) | top-100 cubed {100*(w3(p, t100)/w3(b0, t100)-1):+.3f}% | {bands}")
        P("    " + RG.rank_line(dict(preds, off=b0), m, act, year, wk, pos))
        P(f"    LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | top-100 cubed {100*(w3(lo[4], t100)/w3(b0, t100)-1):+.3f}% | picks {lo[3]}")
        P(f"    FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}")
        P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
    kk_list = (0.85, 0.9, 0.95, 1.0)
    for ps in ("TE", "WR", "RB", "skill"):
        pm_ = skill if ps == "skill" else (pos == ps)
        for lab, gm in groups.items():
            sel = pm_ & gm
            preds = {"wired k .8": SH}
            for k in kk_list: preds[f"k {k}"] = with_k(np.where(sel, k, 0.8))
            test(f"{ps}: {lab}", base & sel, preds)
        sel = pm_ & h3
        slide = 0.8 + 0.2 * np.clip((ratio - 1.2) / 0.8, 0, 1)
        preds = {"wired k .8": SH, "sliding": with_k(np.where(sel, slide, 0.8)), "sliding half": with_k(np.where(sel, 0.8 + 0.5 * (slide - 0.8), 0.8))}
        test(f"{ps}: C sliding by track record (3 seasons)", base & sel & (ratio > 1.2), preds)
    P("\nLimitations: honest replica, next game, no book anchor; history = the shadow's weighted multi-season PPG; the ridge half of the prior is untouched (only the history half is un-shrunk).")
    LOG.close()


if __name__ == "__main__":
    main()
