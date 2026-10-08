#!/usr/bin/env python3
"""
NEXT MAN UP - layer tests (follow-up to research_next_man_up.py, Jack 2026-10-08). On the honest shadow replica (vacated pool
at .75 inside it), teammates of an absent pass catcher read: absorbers 0.997 when the absent share was .10-.17, 1.071 at
.17-.24, 1.117 at .24+; deep receivers (orig rank 4) 1.15-1.22; the top receiver when #2 / #3 sits 1.08-1.10; #3 when #1 sits
.959 and #2 when #3 sits .927 (over-paid). Matchup showed no interaction (not tested).
Variants (multipliers on the absence-week rows of healthy pass catchers ranked 1-6, top-150, shadow >= 3):
  S  vacated SIZE: x (1 + a x max(0, vacated share - .15)), a .5 / 1 / 1.5
  D  DEEP receivers (orig rank >= 4): x 1.05 / 1.10 / 1.15
  T  TOP receiver (orig rank 1, someone below him out): x 1.04 / 1.08
  SD size + deep, ST size + top, SDT all three (at the middle settings)
  C  per-cell rank multipliers (orig rank 1 / 2-3 / 4+) fit on the training seasons, shrunk 50% toward 1
LOYO + forward vs the wired shadow, bar 5/7 + 3/4, LOYO < -0.3% on the rows, whole-board guard; ADP-band read with cubed
top-100 weights; rank line. Log next_man_up_bt.log.
"""
import os, sys, warnings
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import research_next_man_up as R
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "next_man_up_bt.log"), "w", encoding="utf-8")
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
    base = (adpx <= 150) & ~final & ~LV["inh"] & (SH >= 3)
    idx = {(R.nz(name[i]), int(year[i]), int(wk[i])): i for i in range(n)}
    rk = np.zeros(n, int); vs = np.zeros(n); below = np.zeros(n, bool)
    for r in E:
        i = idx.get((R.nz(r["n"]), r["Y"], r["wk"]))
        if i is None or not base[i] or r["rank"] > 6: continue
        rk[i] = r["rank"]; vs[i] = sum(r["absShare"]); below[i] = any(a > r["rank"] for a in r["abs"])
    rows = rk > 0
    P(f"=== NEXT MAN UP layer tests: {int(rows.sum()):,} absence-week teammate rows on the board (of {int(base.sum()):,}) | act/shadow {act[rows].sum()/SH[rows].sum():.3f} ===")
    for lab, mm in (("vacated share < .17", rows & (vs < .17)), (".17-.24", rows & (vs >= .17) & (vs < .24)), (".24+", rows & (vs >= .24)), ("orig rank 1", rows & (rk == 1)), ("rank 2-3", rows & (rk >= 2) & (rk <= 3)), ("rank 4+", rows & (rk >= 4))):
        P(f"  {lab:20s} n{int(mm.sum()):5d} act/shadow {act[mm].sum()/SH[mm].sum():.3f} | by season " + " ".join(f"{y}:{act[mm & (year == y)].sum()/max(1e-9, SH[mm & (year == y)].sum()):.2f}" for y in YEARS))
    S = lambda a: np.where(rows, 1 + a * np.maximum(0, vs - 0.15), 1.0)
    Dm = lambda k: np.where(rows & (rk >= 4), k, 1.0)
    Tm = lambda k: np.where(rows & (rk == 1) & below, k, 1.0)
    preds = {"off": SH}
    for a in (0.5, 1.0, 1.5): preds[f"S size a {a}"] = SH * S(a)
    for k in (1.05, 1.10, 1.15): preds[f"D deep x{k}"] = SH * Dm(k)
    for k in (1.04, 1.08): preds[f"T top x{k}"] = SH * Tm(k)
    preds["SD"] = SH * S(1.0) * Dm(1.10); preds["ST"] = SH * S(1.0) * Tm(1.04); preds["SDT"] = SH * S(1.0) * Dm(1.10) * Tm(1.04)
    w2 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt2[m])) if m.any() else np.nan
    w3 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt3[m])) if m.any() else np.nan
    # C: per-cell multipliers fit on training seasons (shrunk 50%)
    cells = (rows & (rk == 1), rows & (rk >= 2) & (rk <= 3), rows & (rk >= 4))
    def cell_pred(train):
        p = SH.copy(); tr = np.isin(year, train)
        for c in cells:
            mm = c & tr; k = act[mm].sum() / max(1e-9, SH[mm].sum()) if mm.sum() >= 30 else 1.0
            k = 1 + 0.5 * (k - 1); p[c] = SH[c] * np.clip(k, 0.85, 1.25)
        return p
    m = rows; b0 = SH
    names = list(preds)
    pick = lambda yrs: min(names, key=lambda kk: w2(preds[kk], m & np.isin(year, yrs)))
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    def run(folds, fixed=None):
        wins = 0; picks = []; pr = b0.copy()
        for tr_, te in folds:
            if fixed == "C": pp = cell_pred(tr_); kk = "C"
            else: kk = pick(tr_); pp = preds[kk]
            picks.append(kk); mx = year == te; pr[mx] = pp[mx]; wins += w2(pp, m & mx) < w2(b0, m & mx) - 1e-12
        tem = np.isin(year, [te for _, te in folds]); return 100 * (w2(pr, m & tem) / w2(b0, m & tem) - 1), 100 * (w2(pr, base & tem) / w2(b0, base & tem) - 1), wins, picks, pr
    t100 = base & (adpx <= 100)
    P("\n  fixed variants vs the wired shadow (squared top-150 on the rows | seasons better | top-100 cubed board | bands cubed):")
    for kk in names[1:]:
        p = preds[kk]
        bands = " ".join(f"{lab}:{100*(w3(p, base & bm)/w3(b0, base & bm)-1):+.2f}" for lab, bm in (("1-12", adpx <= 12), ("13-30", (adpx > 12) & (adpx <= 30)), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100)), ("101-150", adpx > 100)))
        P(f"    {kk:16s} rows {100*(w2(p, m)/w2(b0, m)-1):+.2f}% ({sum(1 for y in YEARS if w2(p, m & (year == y)) < w2(b0, m & (year == y)) - 1e-12)}/7) | top-100 cubed {100*(w3(p, t100)/w3(b0, t100)-1):+.3f}% | {bands}")
    P("  " + RG.rank_line(preds, m, act, year, wk, pos))
    lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
    okk = best != "off" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
    P(f"\n  pick-best  LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | top-100 cubed {100*(w3(lo[4], t100)/w3(b0, t100)-1):+.3f}% | picks {lo[3]}")
    P(f"             FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}")
    P(f"  -> {'PASS: ' + best if okk else 'FAIL'}")
    lo = run(LOSO, "C"); fw = run(FORW, "C")
    okc = lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
    P(f"\n  C cell fit LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | FWD {fw[0]:+.2f}% {fw[2]}/4 -> {'PASS' if okc else 'FAIL'}")
    pc = cell_pred(list(YEARS)); preds["C cells (all years)"] = pc
    P("  C fitted on all seasons (shrunk 50%): " + " | ".join(f"{lab} x{(pc[c] / SH[c]).mean():.3f} (raw {act[c].sum()/SH[c].sum():.3f}, n{int(c.sum())})" for lab, c in zip(("orig rank 1", "rank 2-3", "rank 4+"), cells)))
    bands = " ".join(f"{lab}:{100*(w3(pc, base & bm)/w3(b0, base & bm)-1):+.3f}" for lab, bm in (("1-12", adpx <= 12), ("13-30", (adpx > 12) & (adpx <= 30)), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100)), ("101-150", adpx > 100)))
    P(f"  C bands cubed (board): {bands} | top-100 cubed {100*(w3(pc, t100)/w3(b0, t100)-1):+.3f}%")
    P("  C by position on the rows: " + " | ".join(f"{ps} {100*(w2(pc, m & (pos == ps))/w2(b0, m & (pos == ps))-1):+.2f}% (n{int((m & (pos == ps)).sum())})" for ps in ("WR", "TE", "RB")))
    P("  C fitted per season-fold (LOYO multipliers): " + " ; ".join(f"{t}: " + "/".join(f"{(cell_pred([y for y in YEARS if y != t])[c] / SH[c]).mean():.3f}" for c in cells) for t in YEARS))
    P("  " + RG.rank_line({"off": SH, "C": pc}, m, act, year, wk, pos))
    P("\nLimitations: honest replica next game, no book anchor (live, ~35% of WR/TE weeks carry a line that already prices the absence); absences from missing rows; trailing 3-game ranks.")
    LOG.close()


if __name__ == "__main__":
    main()
