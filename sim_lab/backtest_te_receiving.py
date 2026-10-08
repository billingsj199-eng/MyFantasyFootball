#!/usr/bin/env python3
"""
RECEIVING / ELITE TEs TREATED LIKE WRs (Jack 2026-10-08: "could treating TEs so differently be a cause - maybe the top
receiving TEs should be treated the same as WR but the more regular TEs stay" + "run a back test for those elite TEs").
Today: WR evidence = xFP weight 1.0 after game 1 fading .08/game to a .25 floor, no snap-trend dock (pruned);
TE evidence = points only (xFP weight 0), snap trend + snap level at half strength.
Groups (walk-forward, known before the game):
  R1 receiving TE by share: season-to-date target share >= .18
  R2 receiving TE by usage: xFP per game so far >= 9 (half PPR)
  E  elite TE: ADP <= 60 or proven (3 seasons, history >= 1.6x the TE mean)
Treatments on the group only:
  U   usage like a WR (WR xFP-weight schedule)
  U25 usage at the .25 floor (a light version)
  D0  no snap docks (trend + level off), D1 docks at full strength
  U+D0
Honest next-game replica; LOYO + forward vs as wired (bar 5/7 + 3/4 and < -0.3% on the rows, board guard); ADP bands cubed;
rank line; plus the "scoring 2+ a game under his usage" rows inside each group. Log te_receiving.log.
"""
import os, sys, warnings
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "te_receiving.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, adp, g = X["act"], X["year"], X["wk"], X["pos"], X["adp"], X["g"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & (adpx <= 150)].mean()
    wt2 = np.maximum(0.05, lv) ** 2; wt3 = np.maximum(0.05, lv) ** 3
    TODAY, LV = BR.live_today(X); SH, _ = BR.shadow_current(X)
    base = (adpx <= 150) & ~final & ~LV["inh"] & (SH >= 3)
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = A["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    tsh = colv("tgt_sh"); xfp = colv("xfp_pg"); pox = colv("pts_over_xfp")
    fbp = F["fb_pos"]; hist = F["hist"]; h3 = np.array(F["has_h3"], bool); ratio = np.where(fbp > 0, np.nan_to_num(hist) / fbp, 0)
    TE = base & (pos == "TE") & (g >= 1)
    groups = {"R1 target share >= .18": TE & (np.nan_to_num(tsh) >= 0.18), "R2 xFP/g >= 9": TE & (np.nan_to_num(xfp) >= 9.0),
              "E elite (ADP <= 60 or proven)": TE & ((adpx <= 60) | (h3 & (ratio >= 1.6)))}
    under = np.nan_to_num(pox) <= -2.0
    for lab, m in groups.items():
        P(f"  {lab:32s} rows {int(m.sum()):5d} | act/shadow {act[m].sum()/SH[m].sum():.3f} | scoring 2+ under usage: rows {int((m & under).sum())} act/shadow {act[m & under].sum()/max(1e-9, SH[m & under].sum()):.3f} | over: {act[m & (np.nan_to_num(pox) >= 2)].sum()/max(1e-9, SH[m & (np.nan_to_num(pox) >= 2)].sum()):.3f}")
    wr_lam = np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0))
    def variant(sel, lam=None, dock=None):
        lo = None
        if lam is not None: lo = np.where(sel, lam, np.nan)
        kw = {}
        if dock is not None: kw = dict(te_dock_k=dock, te_lift_k=dock)
        S = BR.shadow_current(X, lam_override=lo, **kw)[0] if (lo is not None or kw) else SH
        return np.where(sel, S, SH)
    w2 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt2[m])) if m.any() else np.nan
    w3 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt3[m])) if m.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    t100 = base & (adpx <= 100)
    def test(title, m, preds):
        b0 = preds["as wired"]; names = list(preds)
        pick = lambda yrs: min(names, key=lambda kk: w2(preds[kk], m & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = b0.copy()
            for tr_, te_ in folds:
                kk = pick(tr_); picks.append(kk); mx = year == te_; pr[mx] = preds[kk][mx]; wins += w2(preds[kk], m & mx) < w2(b0, m & mx) - 1e-12
            tem = np.isin(year, [te_ for _, te_ in folds]); return 100 * (w2(pr, m & tem) / w2(b0, m & tem) - 1), 100 * (w2(pr, base & tem) / w2(b0, base & tem) - 1), wins, picks, pr
        lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
        okk = best != names[0] and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
        P(f"\n  {title}  (rows {int(m.sum()):,})")
        for kk in names[1:]:
            p = preds[kk]
            bands = " ".join(f"{bl}:{100*(w3(p, base & bm)/w3(b0, base & bm)-1):+.2f}" for bl, bm in (("1-12", adpx <= 12), ("13-30", (adpx > 12) & (adpx <= 30)), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100))))
            P(f"    {kk:22s} rows {100*(w2(p, m)/w2(b0, m)-1):+.2f}% ({sum(1 for y in YEARS if w2(p, m & (year == y)) < w2(b0, m & (year == y)) - 1e-12)}/7) | under-usage rows {100*(w2(p, m & under)/w2(b0, m & under)-1):+.2f}% | top-100 cubed {100*(w3(p, t100)/w3(b0, t100)-1):+.3f}% | {bands}")
        P("    " + RG.rank_line(dict(preds, off=b0), m, act, year, wk, pos))
        P(f"    LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | top-100 cubed {100*(w3(lo[4], t100)/w3(b0, t100)-1):+.3f}% | picks {lo[3]}")
        P(f"    FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}")
        P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
        return okk, best
    for lab, sel in groups.items():
        preds = {"as wired": SH, "U usage like WR": variant(sel, lam=wr_lam), "U25 usage .25": variant(sel, lam=np.full(n, 0.25)),
                 "D0 no snap docks": variant(sel, dock=0.0), "D1 docks full": variant(sel, dock=1.0), "U+D0": variant(sel, lam=wr_lam, dock=0.0), "U25+D0": variant(sel, lam=np.full(n, 0.25), dock=0.0)}
        test(lab, sel, preds)
        su = sel & under
        if su.sum() >= 60:
            preds = {"as wired": SH, "U usage like WR": variant(su, lam=wr_lam), "U25 usage .25": variant(su, lam=np.full(n, 0.25)), "usage .5": variant(su, lam=np.full(n, 0.5))}
            test(lab + " | only when scoring 2+ under usage", su, preds)
    P("\nLimitations: honest replica, next game, no book anchor; groups walk-forward from season-to-date target share / xFP (week 1 rows have none and stay as wired).")
    LOG.close()


if __name__ == "__main__":
    main()
