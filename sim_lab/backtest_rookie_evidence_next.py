#!/usr/bin/env python3
"""
ROOKIE EVIDENCE, NEXT GAME (Jack 2026-10-08 "run the rookie evidence test and wire it if it passes"; the rest-of-season half
is section 13 of backtest_shadow_ros.py). Rookie rows only, honest shadow replica:
  A  usage weight in the evidence (flat lam) per position           B  prior weight by stage (games 1-3 / 4+) per position
Graded on the rookie rows (top-150 weighted error) with the whole-board guard, LOYO + forward (bar 5/7 + 3/4, LOYO < -0.3%),
rank line. Log rookie_evidence_next.log.
"""
import os, sys, warnings
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "rookie_evidence_next.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    base = top150 & ~final & ~LV["inh"] & (SHADOW >= 3); rk = X["rookie"]; early = g <= 3
    wm = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    P(f"=== ROOKIE EVIDENCE, next game: {int((base & rk).sum()):,} rookie top-150 player-weeks 2019-25 ===")
    for ps in POS4:
        m = base & rk & (pos == ps)
        if m.sum() < 60: continue
        P(f"  {ps} rookies n{int(m.sum())}: act/shadow {act[m].sum()/SHADOW[m].sum():.3f} (games 1-3 {act[m & early].sum()/max(1e-9, SHADOW[m & early].sum()):.3f}, 4+ {act[m & ~early].sum()/max(1e-9, SHADOW[m & ~early].sum()):.3f}) | act/Clay form {act[m].sum()/TODAY[m].sum():.3f} | shadow vs Clay error {100*(wm(SHADOW, m)/wm(TODAY, m)-1):+.2f}%")
    def test(title, preds, m):
        names = list(preds); b0 = preds["off"]; pick = lambda yrs: min(names, key=lambda kk: wm(preds[kk], m & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = b0.copy()
            for tr_, te in folds:
                kk = pick(tr_); picks.append(kk); mm = year == te; pr[mm] = preds[kk][mm]; wins += wm(preds[kk], m & mm) < wm(b0, m & mm) - 1e-12
            tem = np.isin(year, [te for _, te in folds]); return 100 * (wm(pr, m & tem) / wm(b0, m & tem) - 1), 100 * (wm(pr, base & tem) / wm(b0, base & tem) - 1), wins, picks
        lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
        fixed = "  ".join(f"{kk}: {100*(wm(preds[kk], m)/wm(b0, m)-1):+.2f}% ({sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and wm(preds[kk], m & (year == y)) < wm(b0, m & (year == y)) - 1e-12)}/7)" for kk in names[1:])
        okk = best != "off" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
        P(f"\n  {title} (rows {int(m.sum()):,})"); P(f"    fixed: {fixed}")
        P("    " + RG.rank_line(preds, m, act, year, wk, pos))
        P(f"    LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | picks {lo[3]}"); P(f"    FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}"); P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
        return best if okk else None
    for ps in POS4:
        m = base & rk & (pos == ps)
        if m.sum() < 60: continue
        # A usage weight
        lgrid = (0.0, 0.25, 0.5, 0.75, 1.0) if ps in ("RB", "WR") else (0.25, 0.5)
        preds = {"off": SHADOW}
        for l in lgrid:
            lo_ = np.full(n, np.nan); lo_[rk & (pos == ps)] = l; preds[f"lam {l}"] = BR.shadow_current(X, lam_override=lo_)[0]
        test(f"A  {ps} rookies: usage weight in the evidence (flat)", preds, m)
        # B prior weight by stage
        preds = {"off": SHADOW}
        for ke in (0.6, 1.0, 1.6, 2.5, 4.0):
            for kl in (0.6, 1.0, 1.6, 2.5):
                if ke == 1.0 and kl == 1.0: continue
                F2 = dict(F); F2["Pvec"] = np.where(rk & (pos == ps) & early, F["Pvec"] * ke, np.where(rk & (pos == ps) & ~early, F["Pvec"] * kl, F["Pvec"])); X2 = dict(X); X2["F"] = F2
                preds[f"early x{ke} / late x{kl}"] = BR.shadow_current(X2)[0]
        test(f"B  {ps} rookies: prior weight by stage (games 1-3 / 4+)", preds, m)
    P("\nLimitations: honest shadow replica (TD luck, TE docks .5; no book anchor / docks); the shadow already carries rookie prior weights (RB x1.6, TE x2.5) and the rookie WR games 2-5 x.9 dock - the multipliers here stack on them.")
    LOG.close()


if __name__ == "__main__":
    main()
