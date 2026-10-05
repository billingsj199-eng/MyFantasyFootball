#!/usr/bin/env python3
"""
Is the model tuned across the whole season, with settings that move smoothly week to week? (Jack 2026-10-02: "did we in
general optimize the beginning and later half of season though every week should be tweaked a little different in a
general trend throughout the season".) Next-game harness, Clay-free model with the v2.29 layer set, 2019-25.

  1  how the model does through the season: level, error vs the Clay blend and rank order, by stretch of weeks
  2  the weight on this season by games played (1 ... 14+): what the model uses vs what fits best
  3  the SHAPE of that weight curve: g^a / (P + g^a) - a under 1 moves fast early and slows, over 1 the reverse;
     plus a slower start (first two games) and a faster finish (from game 9)
  4  how hard the matchup (points allowed) and the Vegas layers should push, by stretch of the season
Log season_trend.log.
"""
import os, sys
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
YEARS = SN.YEARS; POS4 = ("QB", "RB", "WR", "TE")

def main():
    log = open(os.path.join(HERE, "season_trend.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n"); log.flush()
    X = SN.setup(); n = X["n"]; F = X["F"]; A = X["A"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = A["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    smx = colv("snapmult"); smx = np.where(np.isnan(smx), 1.0, smx); fpa = colv("fpa_mult"); veg = colv("veg")
    fpa = np.where(np.isnan(fpa) | (fpa <= 0), 1.0, fpa); veg = np.where(np.isnan(veg) | (veg <= 0), 1.0, veg)
    SH = SN.shadow(X); finw = np.where(year <= 2020, 17, 18); final = wk == finw; allr = ~final & (SH >= 3); top150 = adp <= 150; base = top150 & ~final
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    ms = lambda q, m: float(np.mean((q[m] - act[m]) ** 2)) if m.any() else np.nan
    wm = lambda q, m: float(np.average((q[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    def rho(p_, m):
        gr = defaultdict(list)
        for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        rh = [np.corrcoef(rankdata(act[ix]), rankdata(p_[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]
        return float(np.mean(rh)) if rh else np.nan
    base_lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    l1 = X["snap_l1"]; dev = np.zeros(n)
    for ps in ("WR", "TE"):
        m = (pos == ps) & (g >= 1) & ~np.isnan(l1) & allr; q = np.quantile(SH[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, SH, side="right") - 1, 0, 7)
        for k in range(8):
            mk = m & (b_ == k)
            if mk.sum() >= 30: dev[mk] = l1[mk] - np.nanmean(l1[mk])
    low = np.maximum(0, 19 - np.nan_to_num(X["implied"], nan=19)) / 19
    lvl = np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4); lvl = np.where(adp <= 30, np.maximum(1.0, lvl), lvl)
    EX = np.where(np.isin(pos, ["RB", "TE"]), smx, 1.0) * np.where(np.isin(pos, ["WR", "TE"]), lvl, 1.0)
    EX = EX * np.where((pos == "QB") & X["mover"], 0.90, 1.0) * np.where(pos == "QB", 1 - 0.75 * low, 1.0) * np.where((pos == "RB") & (g >= 2) & (g <= 5) & (X["car_sh"] < 0.30), 0.90, 1.0)
    def model(geff=None, layers=None):
        X2 = dict(X)
        if geff is not None: X2["g"] = geff
        if layers is not None: X2["layers"] = layers
        return SN.shadow(X2, base_lam) * EX
    FULL = model(); CL = F["shipped"]

    P(f"=== season trend: {int(allr.sum()):,} player-weeks 2019-25, model as wired (next game) ===")
    P("\n--- 1  THROUGH THE SEASON: level, error vs the Clay blend, rank order ---")
    STR = [("week 1", 1, 1), ("weeks 2-4", 2, 4), ("weeks 5-8", 5, 8), ("weeks 9-13", 9, 13), ("weeks 14-17 (fantasy playoffs)", 14, 17)]
    for ps in ("all",) + POS4:
        P(f"  {ps}:")
        for lab, lo, hi in STR:
            m = allr & (wk >= lo) & (wk <= hi) & ((pos == ps) if ps != "all" else True); mb = m & top150
            if m.sum() < 100: continue
            w = sum(1 for y in YEARS if ms(FULL, m & (year == y)) < ms(CL, m & (year == y)))
            P(f"    {lab:32s} n {int(m.sum()):5d}  actual / projected {act[m].sum()/FULL[m].sum():.3f}  error vs Clay blend {100*(ms(FULL, m)/ms(CL, m)-1):+6.2f}% ({w}/7)  top-150 weighted {100*(wm(FULL, mb)/wm(CL, mb)-1):+6.2f}%  rank order {rho(FULL, mb):.3f} vs {rho(CL, mb):.3f}")

    P("\n--- 2  WEIGHT ON THIS SEASON by games played: model vs best fit (next game) ---")
    lam = base_lam; ev = lam * X["xf"] + (1 - lam) * X["ppg_v"]; modw = g / (X["Pw"] + g); y = act / np.where((X["layers"] > 0) & (EX > 0), X["layers"] * EX, np.nan)
    GB = [("1", 1, 1), ("2", 2, 2), ("3", 3, 3), ("4", 4, 4), ("5", 5, 5), ("6-7", 6, 7), ("8-10", 8, 10), ("11-13", 11, 13), ("14+", 14, 30)]
    for ps in POS4:
        out = []
        for lab, lo, hi in GB:
            m = allr & (pos == ps) & (g >= lo) & (g <= hi) & ~np.isnan(y) & ~np.isnan(ev)
            if m.sum() < 150: continue
            b = np.linalg.lstsq(np.column_stack([X["prior"][m], ev[m]]), y[m], rcond=None)[0]
            out.append(f"{lab}: {100*modw[m].mean():.0f} / {100*b[1]/(b[0]+b[1]):.0f}")
        P(f"    {ps} (model % / best-fit %, by games played)   " + "   ".join(out))

    def test(title, fam, m_rows):
        names = list(fam); b = fam[names[0]]; touched = np.zeros(n, bool)
        for k in names[1:]: touched |= np.abs(fam[k] - b) > 1e-9
        tm = m_rows & allr & touched
        pick = lambda yrs: min(names, key=lambda k: ms(fam[k], tm & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = b.copy()
            for tr, te in folds:
                k = pick(tr); picks.append(k); m = year == te; pr[m] = fam[k][m]; wins += ms(fam[k], tm & m) < ms(b, tm & m) - 1e-12
            tem = np.isin(year, [te for _, te in folds])
            return pr, 100 * (ms(pr, tm & tem) / ms(b, tm & tem) - 1), 100 * (wm(pr, base & tem) / wm(b, base & tem) - 1), wins, picks
        lo = run([([y for y in YEARS if y != t], t) for t in YEARS]); fw = run([([y for y in YEARS if y < t], t) for t in (2022, 2023, 2024, 2025)])
        sb = lambda k: sum(1 for y_ in YEARS if (tm & (year == y_)).sum() >= 8 and ms(fam[k], tm & (year == y_)) < ms(b, tm & (year == y_)) - 1e-12)
        best = pick(YEARS); okk = best != names[0] and lo[1] < -0.2 and lo[3] >= 5 and fw[1] < 0 and fw[3] >= 3 and lo[2] <= 0.02
        P(f"  {title}   (rows {int(tm.sum()):,})")
        P("    fixed settings (seasons better): " + "  ".join(f"{k}: {100*(ms(fam[k], tm)/ms(b, tm)-1):+.2f}% ({sb(k)})" for k in names[1:]))
        P(f"    LOSO {lo[1]:+.2f}% {lo[3]}/7 | whole board top-150 weighted {lo[2]:+.3f}%, rank order {rho(lo[0], base) - rho(b, base):+.4f} | FORWARD {fw[1]:+.2f}% {fw[3]}/4, weighted {fw[2]:+.3f}% -> {'PASS: ' + str(best) if okk else 'FAIL (best pooled: ' + str(best) + ')'}")
        return okk, best

    P("\n--- 3  THE SHAPE OF THE WEIGHT CURVE through the season ---")
    gf = g.astype(float)
    for ps in POS4:
        mp = pos == ps
        test(f"3a {ps}: exponent on games played (1 = shipped; under 1 = quick early then slower; over 1 = slow early then quicker)",
             {"1.0 (shipped)": FULL, **{f"a {a}": model(np.where(mp, np.power(gf, a), gf)) for a in (0.7, 0.85, 1.15, 1.3, 1.5)}}, mp)
        test(f"3b {ps}: first two games count less (x)", {"1.0 (shipped)": FULL, **{f"x{k}": model(np.where(mp & (g <= 2), gf * k, gf)) for k in (0.5, 0.75, 1.25, 1.5)}}, mp)
        test(f"3c {ps}: games from the 9th on count more (the season outruns the preseason level late)", {"1.0 (shipped)": FULL, **{f"x{k}": model(np.where(mp & (g >= 9), gf * k, gf)) for k in (0.75, 1.25, 1.5, 2.0)}}, mp)

    P("\n--- 4  MATCHUP AND VEGAS strength by stretch of the season (exponent on the multiplier; 1 = shipped) ---")
    for lab, lo_, hi_ in (("weeks 2-4", 2, 4), ("weeks 5-8", 5, 8), ("weeks 9-13", 9, 13), ("weeks 14-17", 14, 17)):
        ms_ = (wk >= lo_) & (wk <= hi_)
        test(f"4a matchup (points allowed), {lab}", {"1.0 (shipped)": FULL, **{f"e {e}": model(None, np.where(ms_, X["layers"] * np.power(fpa, e - 1), X["layers"])) for e in (0.0, 0.5, 1.5, 2.0)}}, ms_)
        test(f"4b Vegas, {lab}", {"1.0 (shipped)": FULL, **{f"e {e}": model(None, np.where(ms_, X["layers"] * np.power(veg, e - 1), X["layers"])) for e in (0.5, 0.75, 1.25, 1.5)}}, ms_)
    P(); P("--- 5  LEVEL by stretch of the season (does a position run high or low at a time of year?) ---")
    for ps in POS4:
        for lab, lo_, hi_ in (("week 1", 1, 1), ("weeks 2-4", 2, 4), ("weeks 5-8", 5, 8), ("weeks 9-13", 9, 13), ("weeks 14-17", 14, 17)):
            mm = (pos == ps) & (wk >= lo_) & (wk <= hi_)
            test(f"5 {ps} {lab}: level", {"1.00 (shipped)": FULL, **{f"x{k}": np.where(mm, FULL * k, FULL) for k in (0.92, 0.95, 0.97, 1.03, 1.05, 1.08)}}, mm)
    log.close()

if __name__ == "__main__":
    main()
