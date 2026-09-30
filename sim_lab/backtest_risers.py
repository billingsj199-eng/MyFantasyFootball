#!/usr/bin/env python3
"""
RISERS INSIDE THE TOP 60-150: can the learned season prior catch what Clay catches? (2026-09-16)

Jack: Clay's season-long edge is the top-60 ADP players, and it lives entirely in the 24 player-seasons he projected
2+ points above our ridge (Gibbs 2023/24, Bijan 2024, Henry 2019, Kelce 2020, Andrews 2023, Allen 2021, Chubb 2020):
ascending 2nd / 3rd-year players whose role grew. Our ridge is anchored to last season (history is the biggest
coefficient) and ADP enters as a log, which barely moves between pick 36 and pick 9. Jack's grading rule (same day):
"focus on top 150 but most importantly top 60 to top 100; the higher ADP players are more important to hit on."
Candidates (all LOYO per position, then forward 2021-25), graded by ADP tier vs Clay and vs the base ridge:
  base        the live ridge (ADP log, history, age, exp, rookie pick, week-1 string, opp prior, 2nd-yr snaps)
  +growth     + exp-2 / exp-3 flags, hist x young (exp <= 2), age <= 25 x hist, ADP log x young
  +linADP     + linear ADP inside the top 60 (60 - adp, floored 0) and a top-60 flag
  +both       growth + linear ADP
  split       separate ridge for exp <= 3 and exp >= 4 (base features)
  top150 fit  base ridge fit ONLY on ADP <= 150 rows (the bottom of the pool no longer steers the coefficients)
Headline metric: ADP-weighted MSE (weight 1/sqrt(adp), unlisted = 181) plus the tier cuts. Log risers_backtest.log;
results -> data/risers_backtest.js (SIM_RISERS_BT), ZONES tab.
"""
import json, os, sys, time, warnings
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import backtest_season_long as SL
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "risers_backtest.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
YEARS, POS4 = NW.YEARS, NW.POS4
LIVE = [f for f in SL.BASIC if f != "mover"]
GROWTH = ["exp2", "exp3", "hist_young", "hist_age25", "ladp_young"]
LIN = ["adp_top60", "top60"]
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "tiers": [], "forward": [], "n": {}}
TIERS = (("top 60", lambda T: (T.adp <= 60).values), ("ADP 61-100", lambda T: ((T.adp > 60) & (T.adp <= 100)).values), ("ADP 101-150", lambda T: ((T.adp > 100) & (T.adp <= 150)).values),
         ("top 150", lambda T: (T.adp <= 150).values), ("ADP-weighted all", lambda T: np.ones(len(T), bool)))


def grade(T, pred, base, clay, label, mask, store, weighted=False):
    m = mask & ~np.isnan(pred) & ~np.isnan(base)
    act, g, year, adp = T.ppg.values, T.games.values.astype(float), T.year.values, T.adp.values
    w = g * (1.0 / np.sqrt(np.where(np.isnan(adp), 181.0, adp))) if weighted else g
    e, eb, ec = SL.wmse(pred[m], act[m], w[m]), SL.wmse(base[m], act[m], w[m]), SL.wmse(clay[m], act[m], w[m])
    ys = [y for y in YEARS if (m & (year == y)).sum() >= 12]
    wb = sum(1 for y in ys if SL.wmse(pred[m & (year == y)], act[m & (year == y)], w[m & (year == y)]) < SL.wmse(base[m & (year == y)], act[m & (year == y)], w[m & (year == y)]))
    wc = sum(1 for y in ys if SL.wmse(pred[m & (year == y)], act[m & (year == y)], w[m & (year == y)]) < SL.wmse(clay[m & (year == y)], act[m & (year == y)], w[m & (year == y)]))
    row = {"label": label, "n": int(m.sum()), "mse": round(e, 3), "vsBase": round((e / eb - 1) * 100, 2), "baseWins": int(wb), "vsClay": round((e / ec - 1) * 100, 2), "clayWins": int(wc), "years": len(ys), "baseVsClay": round((eb / ec - 1) * 100, 2)}
    P(f"  {label:44s} n={m.sum():4d} MSE {e:6.3f} | vs base ridge {row['vsBase']:+6.2f}% ({wb}/{len(ys)}) | vs Clay {row['vsClay']:+6.2f}% ({wc}/{len(ys)})  [base vs Clay {row['baseVsClay']:+.2f}%]")
    store.append(row); return row


def main():
    t0 = time.time()
    P("=== Risers in the top 60-150: growth terms, linear ADP at the top, split fits, top-150-only fit ===")
    T = SL.build_table()
    T["exp2"] = (T.exp == 1).astype(float); T["exp3"] = (T.exp == 2).astype(float)
    young = (T.exp <= 2).astype(float); T["hist_young"] = T["hist"].fillna(T["hist"].median()) * young; T["hist_age25"] = T["hist"].fillna(T["hist"].median()) * (T.age <= 25).astype(float); T["ladp_young"] = T.ladp * young
    T["adp_top60"] = np.maximum(0, 60 - np.where(T.adp.isna(), 181.0, T.adp)); T["top60"] = (T.adp <= 60).astype(float)
    clay = T.clay.values
    RES["n"] = {lab: int(fn(T).sum()) for lab, fn in TIERS}
    P("  player-seasons by tier: " + ", ".join(f"{k} {v}" for k, v in RES["n"].items()))
    SETS = {"base (live ridge)": LIVE, "+growth": LIVE + GROWTH, "+linear ADP top-60": LIVE + LIN, "+growth +linear ADP": LIVE + GROWTH + LIN}
    preds = {lab: SL.loyo(T, fs, "ridge", 10.0) for lab, fs in SETS.items()}
    # split fit: young (exp <= 3) vs vets, base features
    sp = np.full(len(T), np.nan); pos, year, exp = T.pos.values, T.year.values, T.exp.values
    for ps in POS4:
        for y in YEARS:
            for lab, grp in (("young", exp <= 3), ("vet", exp >= 4)):
                tr = (pos == ps) & (year != y) & grp; te = (pos == ps) & (year == y) & grp
                if tr.sum() >= 30 and te.any(): sp[te] = SL.fit_predict(T, LIVE, "ridge", tr, te, 10.0)
    preds["split young / vet"] = np.where(np.isnan(sp), preds["base (live ridge)"], sp)
    # top-150-only fit
    t150 = np.full(len(T), np.nan); in150 = (T.adp <= 150).values
    for ps in POS4:
        for y in YEARS:
            tr = (pos == ps) & (year != y) & in150; te = (pos == ps) & (year == y)
            if tr.sum() >= 30 and te.any(): t150[te] = SL.fit_predict(T, LIVE, "ridge", tr, te, 10.0)
    preds["fit on ADP <= 150 only"] = np.where(np.isnan(t150), preds["base (live ridge)"], t150)
    preds["0.5 base + 0.5 Clay (info)"] = 0.5 * preds["base (live ridge)"] + 0.5 * clay
    base = preds["base (live ridge)"]
    for lab, fn in TIERS:
        P(f"\n=== {lab} (LOYO) ===")
        for nm, pr in preds.items(): grade(T, pr, base, clay, f"{lab}: {nm}", fn(T), RES["tiers"], weighted=(lab == "ADP-weighted all"))
    # forward
    P("\n=== Forward 2021-25 (fit on earlier seasons only), top 150 and ADP-weighted ===")
    fm = (T.year >= YEARS[2]).values
    fbase = SL.forward(T, LIVE, "ridge", 10.0)
    for nm, fs in SETS.items():
        fw = fbase if nm.startswith("base") else SL.forward(T, fs, "ridge", 10.0)
        for lab, fn in TIERS:
            if lab in ("top 60", "ADP 61-100", "top 150", "ADP-weighted all"): grade(T, fw, fbase, clay, f"forward {lab}: {nm}", fm & fn(T), RES["forward"], weighted=(lab == "ADP-weighted all"))
    # the 24 cases: does any candidate move toward Clay on the rows where Clay was 2+ above the base ridge?
    d = (clay - base >= 2) & (T.adp <= 60).values
    P(f"\n=== The rows where Clay sat 2+ above the base ridge inside the top 60 (n={d.sum()}) ===")
    for nm, pr in preds.items():
        w = T.games.values[d].astype(float); P(f"  {nm:28s} mean pred {np.average(pr[d], weights=w):5.2f} (act {np.average(T.ppg.values[d], weights=w):5.2f}, Clay {np.average(clay[d], weights=w):5.2f}) MSE {SL.wmse(pr[d], T.ppg.values[d], w):6.2f} vs Clay {SL.wmse(clay[d], T.ppg.values[d], w):6.2f}")
    best = min([r for r in RES["tiers"] if r["label"].startswith("ADP-weighted") and "Clay" not in r["label"]], key=lambda r: r["mse"])
    RES["summary"] = (f"ADP-weighted (all rows): best Clay-free = {best['label'].split(': ',1)[1]} {best['vsBase']:+.2f}% vs the live ridge ({best['baseWins']}/{best['years']}), {best['vsClay']:+.2f}% vs Clay. " +
                      "; ".join(f"{r['label']} {r['vsBase']:+.1f}% vs base / {r['vsClay']:+.1f}% vs Clay" for r in RES["forward"] if r["label"].startswith("forward top 60") or r["label"].startswith("forward ADP 61-100")))
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "risers_backtest.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_RISERS_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/risers_backtest.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
