#!/usr/bin/env python3
"""
TOP-150, IMPORTANCE-WEIGHTED SEASON PRIOR (2026-09-16).

Jack: "lets focus on the top 150 and heavily weight the higher scoring players since they are more important."
Everything before this was fit and graded games-weighted over the whole 1,404-row pool. Here the learned prior is
refit with importance weights = games x LEVEL^p, LEVEL = the preseason-known scoring level (ADP-curve implied PPG,
position-relative, unlisted = the position's ADP-181 level), and graded with the SAME weighted MSE, top 150 only,
plus the tier cuts. Candidates (LOYO per position, then forward 2021-25):
  weights   p = 0 (current), 1, 2, 3, and "top-150 rows only" x LEVEL^2
  mix       the shadow prior = a x ridge + (1-a) x hand prior, a in {0.5 (v2.15), 0.75, 1.0}, re-chosen under the weights
  ensemble  0.5 x shadow + 0.5 x Clay (info only)
Log top150_weighted.log; results -> data/top150_weighted.js (SIM_T150_BT).
"""
import json, os, sys, time, warnings
import numpy as np
from sklearn.linear_model import Ridge

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import backtest_season_long as SL
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "top150_weighted.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
YEARS, POS4 = NW.YEARS, NW.POS4
LIVE = [f for f in SL.BASIC if f != "mover"]
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "rows": [], "forward": [], "n": {}}


def level_of(T):
    """preseason-known scoring level per row: ADP-curve implied PPG; unlisted = the position's ADP-181 level."""
    lv = T.adp_curve.values.copy()
    for ps in POS4:
        m = (T.pos == ps).values; fb = np.nanmin(lv[m]) if np.isfinite(np.nanmin(lv[m])) else 5.0
        lv[m & np.isnan(lv)] = fb
    return np.maximum(0.5, lv)


def fit_predict_w(T, feats, tr, te, w, alpha=10.0):
    X = T[feats].astype(float).values; y = T.ppg.values
    Xtr, Xte = X[tr], X[te]
    med = np.nanmedian(Xtr, axis=0); med = np.where(np.isnan(med), 0, med)
    miss = [j for j in range(X.shape[1]) if np.isnan(Xtr[:, j]).mean() > 0.02]
    def prep(A):
        F = np.where(np.isnan(A), med, A); ind = np.isnan(A[:, miss]).astype(float) if miss else np.zeros((len(A), 0))
        return np.column_stack([F, ind])
    A, B = prep(Xtr), prep(Xte); mu, sd = A.mean(0), A.std(0); sd[sd == 0] = 1
    mdl = Ridge(alpha=alpha).fit((A - mu) / sd, y[tr], sample_weight=w[tr])
    return np.maximum(0.5, mdl.predict((B - mu) / sd))


def loyo_w(T, feats, w, sel=None):
    out = np.full(len(T), np.nan); pos, yr = T.pos.values, T.year.values
    sel = np.ones(len(T), bool) if sel is None else sel
    for ps in POS4:
        for y in YEARS:
            tr = (pos == ps) & (yr != y) & sel; te = (pos == ps) & (yr == y)
            if tr.sum() >= 30 and te.any(): out[te] = fit_predict_w(T, feats, tr, te, w)
    return out


def forward_w(T, feats, w, sel=None):
    out = np.full(len(T), np.nan); pos, yr = T.pos.values, T.year.values
    sel = np.ones(len(T), bool) if sel is None else sel
    for ps in POS4:
        for y in YEARS[2:]:
            tr = (pos == ps) & (yr < y) & sel; te = (pos == ps) & (yr == y)
            if tr.sum() >= 30 and te.any(): out[te] = fit_predict_w(T, feats, tr, te, w)
    return out


def main():
    t0 = time.time()
    P("=== Top-150, importance-weighted season prior (weights = games x LEVEL^p, LEVEL = ADP-implied PPG) ===")
    T = SL.build_table(); n = len(T)
    act, g, yr, adp, pos, clay, hand = T.ppg.values, T.games.values.astype(float), T.year.values, T.adp.values, T.pos.values, T.clay.values, T.prior.values
    lv = level_of(T); top150 = adp <= 150
    # importance weight for GRADING: games x LEVEL^2, position-relative (so QBs do not dominate)
    rel = lv.copy()
    for ps in POS4:
        m = pos == ps; rel[m] = lv[m] / np.average(lv[m & top150], weights=g[m & top150])
    wg = g * rel ** 2
    RES["n"] = {"top150": int(top150.sum()), "all": n}
    TIERS = (("top 60", adp <= 60), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150", (adp > 100) & (adp <= 150)), ("top 150", top150))
    def wm(p, m): return SL.wmse(p[m], act[m], wg[m])
    def grade(label, pred, base, store, fm=None):
        rows = []
        for lab, m in TIERS:
            mm = m & ~np.isnan(pred) & ~np.isnan(base) & (fm if fm is not None else True)
            ys = [y for y in YEARS if (mm & (yr == y)).sum() >= 12]
            e, eb, ec = wm(pred, mm), wm(base, mm), wm(clay, mm)
            wb = sum(1 for y in ys if wm(pred, mm & (yr == y)) < wm(base, mm & (yr == y))); wc = sum(1 for y in ys if wm(pred, mm & (yr == y)) < wm(clay, mm & (yr == y)))
            plain = (SL.wmse(pred[mm], act[mm], g[mm]) / SL.wmse(clay[mm], act[mm], g[mm]) - 1) * 100
            row = {"label": f"{label} | {lab}", "n": int(mm.sum()), "wmse": round(e, 3), "vsBase": round((e / eb - 1) * 100, 2), "baseWins": int(wb), "vsClay": round((e / ec - 1) * 100, 2), "clayWins": int(wc), "years": len(ys), "plainVsClay": round(plain, 2)}
            store.append(row); rows.append(row)
        P(f"  {label:40s} " + " | ".join(f"{r['label'].split(' | ')[1]}: {r['vsClay']:+6.2f}% ({r['clayWins']}/{r['years']}) [vs v2.15 {r['vsBase']:+5.2f}%]" for r in rows))
    # --- current shadow prior (v2.15): plain-weighted ridge, a = 0.5 ---
    lo0 = SL.loyo(T, LIVE, "ridge", 10.0); base = np.where(np.isnan(lo0), hand, 0.5 * lo0 + 0.5 * hand)
    P("\n--- LOYO, importance-weighted MSE vs Clay (negative = ours better); tiers top 60 / 61-100 / 101-150 / top 150 ---")
    grade("shadow v2.15 (plain fit, a=.5)", base, base, RES["rows"])
    grade("hand prior alone", hand, base, RES["rows"]); grade("ridge alone (plain fit)", lo0, base, RES["rows"])
    fits = {}
    for p in (1, 2, 3):
        w = g * rel ** p; fits[f"ridge, weights LEVEL^{p}"] = loyo_w(T, LIVE, w)
    fits["ridge, top-150 rows only x LEVEL^2"] = loyo_w(T, LIVE, g * rel ** 2, sel=top150)
    for nm, pr in fits.items():
        for a in (0.5, 0.75, 1.0):
            grade(f"{nm}, a={a}", np.where(np.isnan(pr), hand, a * pr + (1 - a) * hand), base, RES["rows"])
    grade("0.5 shadow v2.15 + 0.5 Clay (info)", 0.5 * base + 0.5 * clay, base, RES["rows"])
    # --- forward ---
    P("\n--- FORWARD 2021-25 (fit on earlier seasons only), importance-weighted MSE vs Clay ---")
    fm = yr >= YEARS[2]
    fw0 = SL.forward(T, LIVE, "ridge", 10.0); basef = np.where(np.isnan(fw0), hand, 0.5 * fw0 + 0.5 * hand)
    grade("forward shadow v2.15 (plain, a=.5)", basef, basef, RES["forward"], fm)
    grade("forward ridge alone (plain)", fw0, basef, RES["forward"], fm)
    for p in (1, 2):
        pr = forward_w(T, LIVE, g * rel ** p)
        for a in (0.5, 0.75, 1.0): grade(f"forward ridge LEVEL^{p}, a={a}", np.where(np.isnan(pr), hand, a * pr + (1 - a) * hand), basef, RES["forward"], fm)
    pr = forward_w(T, LIVE, g * rel ** 2, sel=top150)
    for a in (0.5, 0.75, 1.0): grade(f"forward top-150-only LEVEL^2, a={a}", np.where(np.isnan(pr), hand, a * pr + (1 - a) * hand), basef, RES["forward"], fm)
    grade("forward 0.5 shadow + 0.5 Clay (info)", 0.5 * basef + 0.5 * clay, basef, RES["forward"], fm)
    best = min([r for r in RES["rows"] if r["label"].endswith("| top 150") and "Clay" not in r["label"] and "alone" not in r["label"]], key=lambda r: r["wmse"])
    bestf = min([r for r in RES["forward"] if r["label"].endswith("| top 150") and "Clay" not in r["label"] and "alone" not in r["label"]], key=lambda r: r["wmse"])
    RES["summary"] = (f"Importance-weighted top 150, LOYO: best Clay-free = {best['label'].split(' | ')[0]} {best['vsClay']:+.2f}% vs Clay ({best['clayWins']}/{best['years']}), {best['vsBase']:+.2f}% vs shadow v2.15. "
                      f"Forward: best = {bestf['label'].split(' | ')[0]} {bestf['vsClay']:+.2f}% vs Clay ({bestf['clayWins']}/{bestf['years']}), {bestf['vsBase']:+.2f}% vs v2.15.")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "top150_weighted.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_T150_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/top150_weighted.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
