#!/usr/bin/env python3
"""
ADP MARKET-BLEND FADE BY GAMES PLAYED (2026-11-17, Jack via the Chuba Hubbard / Blake Corum ROS traces). RESEARCH ONLY - nothing
here touches engine.js / overrides.js / the export.

Question: the shadow's v2.1 market prior  prior = (1-wA) hist + wA (a + b ln ADP)  (wA .75 vets / .5 2nd-year) uses the same weight
all season. Should wA fade as 2026 games pile up?

Harness = research_usage_legit.py (backtest_no_adp full() rows, ROS + next game, X_cache), minus the role cleaning, with two
changes to match the CURRENT live base:
  * RB ROS prior weight = v2.35 smooth curve 1 + exp(-.5((ADP-70)/25)^2) (3+ games) in place of the RB 61-100 x2.5 band
  * rows run to 16 games played (weeks 13-18 phase) instead of 11
Fade shapes on wA (g = games played before the projected week; scope = market blend only, the ridge ADP twin stays):
  lin k  : max(0, 1 - g/k)          k 4..24
  hyp k  : k / (k + g)              k 2..24
  offwk N: 0 once the current (checkpoint) week > N     N 4..14
  offg N : 0 once g >= N            N 4..12
TE held at wired in every variant (TE is ADP-free live). Also ADP 1-30-only fades. Graded vs the wired shadow: MSE % (neg = better), seasons won, forward folds, MAE, ADP-weighted top-150 and top-100, rank rho.
Then LOYO / forward picks of k inside each shape (global and per position), phase (checkpoint wk 2-6 / 7-12 / 13+) and ADP-band
splits, ROS vs next-game.
Log: adp_fade.log (default 2019-25), _bt_ext/adp_fade_ext2012_2025_tf.log with SIM_BT_YEARS=2012-2025.
"""
import os, sys, pickle
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
import bt_ext as BX
ALLY = list(BX.YEARS); TRAINY = [y for y in ALLY if y >= 2013] if BX.EXT else ALLY
YEARS = TRAINY; FWD = tuple(y for y in BX.FWD if y in YEARS) if BX.EXT else (2022, 2023, 2024, 2025)
NY, NF = len(YEARS), len(FWD); NEED7, NEED4 = int(np.ceil(0.70 * NY)), int(np.ceil(0.75 * NF))
POS4 = ("QB", "RB", "WR", "TE")
MINF = int(os.environ.get("ROS_MINF", "4")); GMAX = int(os.environ.get("GMAX", "16"))


def main():
    log = open(BX.ext_path("adp_fade" + ("" if MINF == 4 else f"_minf{MINF}") + ".log"), "w", encoding="utf-8")
    def P(s=""): print(s, flush=True); log.write(s + "\n"); log.flush()
    X = pickle.load(open(BX.ext_path("X_cache.pkl") if BX.EXT else os.path.join(HERE, "_tmp", "X_cache.pkl"), "rb"))
    P(f"harness: {BX.describe()} | graded {YEARS[0]}-{YEARS[-1]} ({NY}), forward {FWD[0]}-{FWD[-1]} ({NF}); bar err < -0.3%, LOYO {NEED7}/{NY}, fwd < 0 & {NEED4}/{NF}, top150-w <= +0.1%")
    n = X["n"]; F = X["F"]; A = X["A"]
    act, year, wk, pos, g, name, adp, layers = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["name"], X["adp"], X["layers"]
    pid = A["pid"]; finw = np.where(year <= 2020, 17, 18)
    seq = defaultdict(list)
    for i in range(n):
        if wk[i] != finw[i]: seq[(name[i], pos[i], int(year[i]))].append(i)   # final week excluded
    T = np.full(n, np.nan); ctx = np.full(n, np.nan)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(layers[ix], 0.5, 1.8)
        for a, i in enumerate(ix):
            if len(ix) - a >= MINF: T[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    lay = np.clip(layers, 0.5, 1.8)
    C = pd.read_parquet(BX.ext_path("ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    bl = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    top150 = adp <= 150; top100 = adp <= 100
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    strb = F["strb"]; y2 = colv("yr2") == 1
    band = {"ADP 61-100": (adp > 60) & (adp <= 100), "ADP 101-150": (adp > 100) & (adp <= 150)}
    t36 = (pos == "TE") & (adp > 30) & (adp <= 60)
    sm = colv("snapmult"); sm = np.where(np.isnan(sm), 1.0, sm); l1 = colv("snap_l1")
    R00 = (X["Pw"] * X["prior"] + g * (bl * X["xf"] + (1 - bl) * X["ppg_v"])) / (X["Pw"] + g)
    base_ok = ~np.isnan(T) & (g >= 1) & (g <= GMAX) & (R00 * ctx >= 3)
    def z_of(v, m):
        out = np.zeros(n); mm = m & base_ok & ~np.isnan(v); ap = m & ~np.isnan(v)
        if mm.sum() > 50: out[ap] = np.clip((v[ap] - v[mm].mean()) / v[mm].std(), -2, 2)
        return out
    dev = np.zeros(n)
    for ps in ("WR", "TE"):
        m = base_ok & (pos == ps) & ~np.isnan(l1); q = np.quantile(R00[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, R00, side="right") - 1, 0, 7)
        for k in range(8):
            mk_ = m & (b_ == k)
            if mk_.sum() >= 30: dev[mk_] = l1[mk_] - l1[mk_].mean()
    zp = z_of(colv("proe_std"), pos == "TE"); zpl = z_of(colv("plays_pg_std"), pos == "RB")
    rbcurve = 1 + 1.0 * np.exp(-.5 * ((np.nan_to_num(adp, nan=999.0) - 70) / 25) ** 2)   # v2.35 (wired 11-02)
    LATER = ("RB prior weight curve", "WR 61-100 prior weight x0.6", "WR 101-150 cold prior weight x0.4", "WR 101-150 usage cap .25", "TE 31-60 x1.10",
             "RB backup (top 150) x1.04", "second-year QB prior weight x0.75", "QB changed teams x.84", "TE snap-share level e .3", "TE team pass-rate tilt e .04", "RB team play-volume tilt e .04")
    later3 = g >= 3
    def parts(prior, off=()):
        on = lambda k: k not in off
        lam_ = bl.copy()
        if on("WR 101-150 usage cap .25"): lam_ = np.where((pos == "WR") & band["ADP 101-150"] & later3, np.minimum(lam_, 0.25), lam_)
        ev = lam_ * X["xf"] + (1 - lam_) * X["ppg_v"]
        pm_ = np.ones(n)
        if on("RB prior weight curve"): pm_ = np.where((pos == "RB") & later3, rbcurve, pm_)
        if on("WR 61-100 prior weight x0.6"): pm_ = np.where((pos == "WR") & band["ADP 61-100"] & later3, 0.6, pm_)
        if on("second-year QB prior weight x0.75"): pm_ = np.where((pos == "QB") & y2 & later3, 0.75, pm_)
        if on("WR 101-150 cold prior weight x0.4"): pm_ = np.where((pos == "WR") & band["ADP 101-150"] & (ev < prior) & later3, pm_ * 0.4, pm_)
        Pw = X["Pw"] * pm_
        mu = np.ones(n); mu = np.where(pos == "RB", mu * sm, mu)
        if on("QB changed teams x.84"): mu = np.where((pos == "QB") & X["mover"], mu * 0.84, mu)
        if on("TE snap-share level e .3"): mu = np.where((pos == "TE") & ~np.isnan(l1), mu * np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4), mu)
        if on("TE team pass-rate tilt e .04"): mu = np.where(pos == "TE", mu * (1 - 0.04 * zp), mu)
        if on("TE 31-60 x1.10"): mu = np.where(t36 & later3, mu * 1.10, mu)
        if on("RB team play-volume tilt e .04"): mu = np.where(pos == "RB", mu * np.clip(1 - 0.04 * zpl, 0.8, 1.25), mu)
        if on("RB backup (top 150) x1.04"): mu = np.where((pos == "RB") & (strb >= 2) & (adp <= 150) & later3, mu * 1.04, mu)
        return Pw, ev, mu
    blend = lambda Pw, ev, pr: (Pw * pr + g * ev) / np.maximum(Pw + g, 1e-9)
    def ros(prior):
        Pw, ev, mu = parts(prior); return blend(Pw, ev, prior) * mu * ctx
    def nxt(prior):
        Pw, ev, mu = parts(prior, LATER); return blend(Pw, ev, prior) * mu * lay
    WPRIOR = X["prior"]; FULL = ros(WPRIOR); FULLN = nxt(WPRIOR)
    ok = base_ok & (FULL >= 3) & np.isin(year, TRAINY); okN = (g >= 1) & (g <= GMAX) & (wk != finw) & (FULLN >= 3) & np.isin(year, TRAINY)
    # ---- the market blend with a per-row weight multiplier k ----
    yr2a = A["exp"] == 1; fb = F["fb_pos"]; ac = F["adp_curve"]; mk = F["mkt_ok"]; late_ = F["late"]
    mdock = np.ones(n)
    for ps_, d_ in SN.CS.NC.VETDOCK.items():
        for sb_, mm_ in d_.items(): mdock = np.where((pos == ps_) & (strb == sb_), mdock * mm_, mdock)
    mdock = np.where(yr2a & ~np.isnan(late_) & (late_ < 0.4), mdock * 1.2, mdock)
    wv = np.where(yr2a, 0.5, 0.75); prm = (F["prior"] - fb) / 0.8 + fb
    hm = np.where(mk, (prm - mdock * wv * np.nan_to_num(ac)) / (1 - wv), prm)
    mix = lambda rg, pr: np.where(np.isnan(rg) | (pos == "QB"), pr, 0.5 * rg + 0.5 * pr)
    def prior_k(k):
        k = np.broadcast_to(np.asarray(k, float), (n,))
        prk = np.where(mk, (1 - wv * k) * hm + mdock * wv * k * np.nan_to_num(ac), prm)
        pf = np.where(mk, fb + 0.8 * (prk - fb), F["prior"])
        return mix(X["r_adp"], pf)
    chk = np.isclose(prior_k(1.0), WPRIOR, equal_nan=True)
    mshift = mk & ok
    P(f"=== ADP FADE: {int(ok.sum()):,} ROS checkpoints (1-{GMAX} games, {MINF}+ left, final week out), next-game rows {int(okN.sum()):,}; market-blend rows {100*mshift.sum()/ok.sum():.0f}% of ROS rows ===")
    P(f"  check: prior_k(1) == wired prior on {100*chk.mean():.1f}% of rows; mean |hist - mkt| on blended ROS rows {np.nanmean(np.abs(hm - mdock*np.nan_to_num(ac))[mshift]):.2f} half PPG")

    # ---------------- grading ----------------
    def rho(q, m, tgt):
        grp = defaultdict(list)
        for i in np.where(m)[0]: grp[(int(year[i]), int(wk[i]), pos[i])].append(i)
        rh = [np.corrcoef(rankdata(tgt[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in grp.values()) if len(ix) >= 8]
        return float(np.mean(rh)) if rh else np.nan
    def gr(Q, B_, m, tgt, rank=True):
        if m.sum() < 30: return None
        e = lambda q, mm: float(np.mean((q[mm] - tgt[mm]) ** 2))
        s7 = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and e(Q, m & (year == y)) < e(B_, m & (year == y)) - 1e-12)
        n7 = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and abs(e(Q, m & (year == y)) - e(B_, m & (year == y))) > 1e-12)
        mf = m & np.isin(year, FWD); s4 = sum(1 for y in FWD if (m & (year == y)).sum() >= 8 and e(Q, m & (year == y)) < e(B_, m & (year == y)) - 1e-12)
        w_ = lambda q, mm: float(np.average((q[mm] - tgt[mm]) ** 2, weights=wt[mm]))
        mt = m & top150; mh = m & top100
        return dict(n=int(m.sum()), err=100 * (e(Q, m) / e(B_, m) - 1), fe=100 * (e(Q, mf) / e(B_, mf) - 1) if mf.sum() > 20 else np.nan,
                    mae=100 * (np.mean(np.abs(Q[m] - tgt[m])) / np.mean(np.abs(B_[m] - tgt[m])) - 1),
                    w=100 * (w_(Q, mt) / w_(B_, mt) - 1) if mt.sum() > 20 else np.nan, w100=100 * (w_(Q, mh) / w_(B_, mh) - 1) if mh.sum() > 20 else np.nan,
                    rk=(rho(Q, mt, tgt) - rho(B_, mt, tgt)) if rank else np.nan, s7=s7, n7=n7, s4=s4)
    def passes(r): return r is not None and r["err"] < -0.3 and r["s7"] >= NEED7 and r["fe"] < 0 and r["s4"] >= NEED4 and r["w"] <= 0.1
    fmt = lambda r: "n/a" if r is None else (f"n {r['n']:5d} err {r['err']:+6.2f}% ({r['s7']}/{NY}) fwd {r['fe']:+6.2f}% ({r['s4']}/{NF}) MAE {r['mae']:+6.2f}% "
                                             f"top150-w {r['w']:+6.2f}% top100-w {r['w100']:+6.2f}% rank {r['rk']:+.4f}{'  PASS' if passes(r) else ''}")
    short = lambda r: "   n/a      " if r is None else f"{r['err']:+6.2f}% ({r['s7']}/{NY})"

    # ---------------- fade family ----------------
    gf = g.astype(float); wkf = wk.astype(float)
    FAM = [("wired", lambda: np.ones(n))]
    for k in (4, 6, 8, 10, 12, 16, 24): FAM.append((f"lin k{k}", (lambda k=k: np.maximum(0.0, 1 - gf / k))))
    for k in (2, 4, 6, 8, 12, 16, 24): FAM.append((f"hyp k{k}", (lambda k=k: k / (k + gf))))
    for N in (4, 6, 8, 10, 12, 14): FAM.append((f"offwk N{N}", (lambda N=N: np.where(wkf > N, 0.0, 1.0))))
    for N in (4, 6, 8, 10, 12): FAM.append((f"offg N{N}", (lambda N=N: np.where(gf >= N, 0.0, 1.0))))
    FAM.append(("ADP off (k=0)", lambda: np.zeros(n)))
    # ADP 1-30 only (the band where section 3 leaned toward fading): fade inside the top 30, wired elsewhere
    a30 = adp <= 30
    for k in (8, 12, 16): FAM.append((f"top30 lin k{k}", (lambda k=k: np.where(a30, np.maximum(0.0, 1 - gf / k), 1.0))))
    for k in (4, 8, 16): FAM.append((f"top30 hyp k{k}", (lambda k=k: np.where(a30, k / (k + gf), 1.0))))
    # TE is ADP-free live (NC_SHADOW.noAdpPos TE) -> a fade cannot touch live TEs; keep TE at wired so the pooled numbers are QB/RB/WR effects only
    PRED = {}
    for lab, fn in FAM:
        pr_ = prior_k(np.where(pos == "TE", 1.0, fn())); PRED[lab] = (ros(pr_), nxt(pr_))
    P("\n--- 1  FIXED SCHEDULES vs wired, every row (in-sample choice of k; negative = better than wired) ---")
    for lab, _ in FAM[1:]:
        Q, QN = PRED[lab]
        P(f"  {lab:14s} ROS  " + fmt(gr(Q, FULL, ok, T)))
        P(f"  {'':14s} NEXT " + fmt(gr(QN, FULLN, okN, act, rank=False)))
        P(f"  {'':14s} ROS by pos " + "  ".join(f"{p_} {short(gr(Q, FULL, ok & (pos == p_), T, False))}" for p_ in POS4) +
          " | NEXT by pos " + "  ".join(f"{p_} {short(gr(QN, FULLN, okN & (pos == p_), act, False))}" for p_ in POS4))

    # ---------------- LOYO / forward pick inside each shape ----------------
    PIX = np.array([POS4.index(p_) if p_ in POS4 else 0 for p_ in pos]); YIX = {y: k for k, y in enumerate(ALLY)}
    GI = PIX * len(ALLY) + np.array([YIX[int(y)] for y in year]); NG = 4 * len(ALLY)
    def sse_tab(Q, mrow, tgt):
        mm = mrow & ~np.isnan(Q) & ~np.isnan(tgt); se = np.bincount(GI[mm], weights=(Q[mm] - tgt[mm]) ** 2, minlength=NG); cn = np.bincount(GI[mm], minlength=NG)
        return {(p_, y): (float(se[POS4.index(p_) * len(ALLY) + YIX[y]]), int(cn[POS4.index(p_) * len(ALLY) + YIX[y]])) for p_ in POS4 for y in TRAINY}
    SSE = {lab: (sse_tab(PRED[lab][0], ok, T), sse_tab(PRED[lab][1], okN, act)) for lab, _ in FAM}
    SHAPES = {"lin": [l for l, _ in FAM if l.startswith("lin")], "hyp": [l for l, _ in FAM if l.startswith("hyp")], "top30": [l for l, _ in FAM if l.startswith("top30")],
              "offwk": [l for l, _ in FAM if l.startswith("offwk")], "offg": [l for l, _ in FAM if l.startswith("offg")]}
    P("\n--- 2  HONEST OUT-OF-SAMPLE: k picked on the training seasons inside each shape (wired always a candidate); global k or per-position k; "
      "ROS picks judged on ROS, NEXT picks on next game ---")
    OOS = {}
    for shp, labs in SHAPES.items():
        cands = ["wired"] + labs
        for scope in ("global", "per-pos"):
            for hz, hi, B_, mrow, tgt in (("ROS ", 0, FULL, ok, T), ("NEXT", 1, FULLN, okN, act)):
                def pick(yrs, ps_):
                    pp = POS4 if ps_ is None else (ps_,)
                    return min(cands, key=lambda c_: sum(SSE[c_][hi][(p_, y)][0] for p_ in pp for y in yrs) / max(1, sum(SSE[c_][hi][(p_, y)][1] for p_ in pp for y in yrs)))
                L = B_.copy(); Fw = B_.copy(); picks = defaultdict(list)
                for ty in YEARS:
                    for p_ in POS4:
                        c_ = pick([y for y in TRAINY if y != ty], None if scope == "global" else p_); picks[p_].append(c_)
                        sel = (pos == p_) & (year == ty); L[sel] = PRED[c_][hi][sel]
                for ty in FWD:
                    for p_ in POS4:
                        c_ = pick([y for y in TRAINY if y < ty], None if scope == "global" else p_); sel = (pos == p_) & (year == ty); Fw[sel] = PRED[c_][hi][sel]
                r = gr(L, B_, mrow, tgt, rank=(hi == 0)); rf = gr(Fw, B_, mrow & np.isin(year, FWD), tgt, rank=False)
                ok_ = r["err"] < -0.3 and r["s7"] >= NEED7 and rf["err"] < 0 and rf["s4"] >= NEED4 and r["w"] <= 0.1
                OOS[(shp, scope, hz)] = (L, Fw)
                pk = " | ".join(f"{p_} " + ",".join(f"{c}x{picks[p_].count(c)}" for c in sorted(set(picks[p_]), key=picks[p_].count, reverse=True)[:2]) for p_ in POS4) if scope == "per-pos" else ",".join(f"{c}x{picks['QB'].count(c)}" for c in sorted(set(picks['QB']), key=picks['QB'].count, reverse=True)[:3])
                P(f"  {shp:5s} {scope:7s} {hz} LOYO err {r['err']:+6.2f}% ({r['s7']}/{NY}) MAE {r['mae']:+6.2f}% top150-w {r['w']:+6.2f}% top100-w {r['w100']:+6.2f}% rank {r['rk']:+.4f} | FWD {rf['err']:+6.2f}% ({rf['s4']}/{NF}){'  PASS' if ok_ else ''}  picks: {pk}")

    # ---------------- splits for the best fixed variants ----------------
    def best_of(labs, hi):
        B_, mrow, tgt = (FULL, ok, T) if hi == 0 else (FULLN, okN, act)
        return min(labs, key=lambda l: float(np.mean((PRED[l][hi][mrow] - tgt[mrow]) ** 2)))
    SHOW = sorted(set([best_of(v, 0) for v in SHAPES.values()] + [best_of(v, 1) for v in SHAPES.values()] + ["lin k12", "hyp k8", "offwk N8", "top30 hyp k8", "ADP off (k=0)"]),
                  key=lambda l: [x for x, _ in FAM].index(l))
    PH = [("wk 2-6", (wk >= 2) & (wk <= 6)), ("wk 7-12", (wk >= 7) & (wk <= 12)), ("wk 13+", wk >= 13)]
    BANDS = [("ADP 1-30", adp <= 30), ("ADP 31-60", (adp > 30) & (adp <= 60)), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150", (adp > 100) & (adp <= 150)), ("ADP 151+/none", ~(adp <= 150))]
    GB = [("g 1-3", g <= 3), ("g 4-6", (g >= 4) & (g <= 6)), ("g 7-9", (g >= 7) & (g <= 9)), ("g 10+", g >= 10)]
    P("\n--- 3  SPLITS (fixed schedules; err % vs wired (seasons won)); ROS by checkpoint week / games played / ADP band / position; NEXT the same ---")
    P(f"  best fixed by MSE: ROS {[best_of(v, 0) for v in SHAPES.values()]} | NEXT {[best_of(v, 1) for v in SHAPES.values()]}")
    for lab in SHOW:
        Q, QN = PRED[lab]; P(f"\n  {lab}")
        for hz, Qh, B_, mrow, tgt in (("ROS ", Q, FULL, ok, T), ("NEXT", QN, FULLN, okN, act)):
            P(f"    {hz} phase   " + "  ".join(f"{l} {short(gr(Qh, B_, mrow & m, tgt, False))} n{int((mrow & m).sum())}" for l, m in PH))
            P(f"    {hz} games   " + "  ".join(f"{l} {short(gr(Qh, B_, mrow & m, tgt, False))}" for l, m in GB))
            P(f"    {hz} ADP     " + "  ".join(f"{l} {short(gr(Qh, B_, mrow & m, tgt, False))}" for l, m in BANDS))
            for p_ in POS4:
                P(f"    {hz} {p_} phase " + "  ".join(f"{l} {short(gr(Qh, B_, mrow & m & (pos == p_), tgt, False))}" for l, m in PH) + " | ADP " +
                  "  ".join(f"{l[4:]} {short(gr(Qh, B_, mrow & m & (pos == p_), tgt, False))}" for l, m in BANDS[:4]))
    # ---- level check on the Chuba cell: hot mid-ADP RBs, ROS act/pred wired vs faded ----
    P("\n--- 4  LEVEL CHECK, Chuba / Corum-type cells (ROS act / pred; >1 = the model runs low) ---")
    ev_ = parts(WPRIOR)[1]
    cells = [("RB ADP 61-100, 7+ g, evidence >= prior+3", (pos == "RB") & band["ADP 61-100"] & (g >= 7) & (ev_ >= WPRIOR + 3)),
             ("RB ADP 61-100, 7+ g, all", (pos == "RB") & band["ADP 61-100"] & (g >= 7)),
             ("RB ADP 61-120, 7+ g, evidence <= prior", (pos == "RB") & (adp > 60) & (adp <= 120) & (g >= 7) & (ev_ <= WPRIOR)),
             ("all positions ADP 1-150, 7+ g, evidence >= prior+3", top150 & (g >= 7) & (ev_ >= WPRIOR + 3)),
             ("all positions ADP 1-150, 7+ g, evidence <= prior-3", top150 & (g >= 7) & (ev_ <= WPRIOR - 3))]
    for lab_, m in cells:
        m = ok & m & mk
        if m.sum() < 20: continue
        P(f"  {lab_:52s} n {int(m.sum()):4d} ({len(set(zip(year[m], name[m])))} p-s)  wired {T[m].sum()/FULL[m].sum():.3f}  " +
          "  ".join(f"{l} {T[m].sum()/PRED[l][0][m].sum():.3f} ({short(gr(PRED[l][0], FULL, m, T, False))})" for l in ("lin k12", "hyp k8", "offwk N8", "ADP off (k=0)")))

    # ================= 5  JACK 11-17: "through week 10 how much does ADP actually matter" =================
    P("\n--- 5  ADP VALUE BY CHECKPOINT (Jack 11-17). Checkpoint 'after week W' = projecting from week W+1 on. err = MSE % of the variant vs WIRED"
      " (positive = removing ADP HURTS by that much). M0 = market blend off (wA 0), ridge ADP kept; B = all ADP out of the prior (wA 0 + ADP-free ridge twin)."
      " TE is ADP-free live already - TE rows here measure what the harness's TE ADP would do, not a live effect. ---")
    PM0 = prior_k(0.0); kk0 = np.zeros(n)
    prB = mix(X["r_no"], np.where(mk, fb + 0.8 * (hm - fb), F["prior"]))
    VV = {"M0": (ros(PM0), nxt(PM0)), "B": (ros(prB), nxt(prB))}
    CKW = (2, 4, 6, 8, 10)
    for vlab, (Qr, Qn) in VV.items():
        P(f"\n  {vlab}: removing ADP, error change vs wired (seasons where removal hurt / {NY})")
        for W in CKW:
            mr = ok & (wk == W + 1); mn = okN & (wk == W + 1)
            def cell(Q_, B_, m_, tgt):
                r = gr(Q_, B_, m_, tgt, False)
                return "   n/a        " if r is None else f"{r['err']:+6.2f}% ({NY - r['s7'] if r['n7'] == NY else r['n7'] - r['s7']}/{r['n7']})"
            rr = gr(Qr, FULL, mr, T, False); rn = gr(Qn, FULLN, mn, act, False)
            P(f"    after wk {W:2d}  ROS  all {cell(Qr, FULL, mr, T)} top150-w {rr['w']:+6.2f}% | " + "  ".join(f"{p_} {cell(Qr, FULL, mr & (pos == p_), T)}" for p_ in POS4) + f"   (n {int(mr.sum())})")
            P(f"                NEXT all {cell(Qn, FULLN, mn, act)} top150-w {rn['w']:+6.2f}% | " + "  ".join(f"{p_} {cell(Qn, FULLN, mn & (pos == p_), act)}" for p_ in POS4) + f"   (n {int(mn.sum())})")
        # pooled through week 10
        mr = ok & (wk >= 3) & (wk <= 11); mn = okN & (wk >= 3) & (wk <= 11)
        rr = gr(Qr, FULL, mr, T, False); rn = gr(Qn, FULLN, mn, act, False)
        P(f"    POOLED after wks 2-10: ROS {rr['err']:+.2f}% (removal better in {rr['s7']}/{NY}) top150-w {rr['w']:+.2f}% top100-w {rr['w100']:+.2f}% | NEXT {rn['err']:+.2f}% ({rn['s7']}/{NY}) top150-w {rn['w']:+.2f}%")
    # best-fit wA per checkpoint (pooled seasons) + leave-one-season-out stability
    KGRID = np.round(np.arange(0, 1.3401, 1 / 15), 4)   # k x .75 -> wA 0 .. 1.0 in .05 steps
    PK = {k: ros(prior_k(k)) for k in KGRID}; PKN = {k: nxt(prior_k(k)) for k in KGRID}
    P("\n  BEST-FIT vet wA (= .75 x k; 2nd-year = .5 x k) by checkpoint, pooled seasons; [range of the per-held-out-season LOYO picks]; gain = MSE of best vs wA 0")
    for W in CKW + (12,):
        line = f"    after wk {W:2d}"
        for hz, PKx, B_, mrow, tgt in (("ROS", PK, FULL, ok, T), ("NEXT", PKN, FULLN, okN, act)):
            for p_ in ("all",) + POS4[:3]:
                m_ = mrow & (wk == W + 1) & (True if p_ == "all" else (pos == p_))
                if m_.sum() < 30: continue
                se = {k: float(np.mean((PKx[k][m_] - tgt[m_]) ** 2)) for k in KGRID}; kb = min(se, key=se.get)
                lo = [min(KGRID, key=lambda k: float(np.mean((PKx[k][m_ & (year != y)] - tgt[m_ & (year != y)]) ** 2))) for y in YEARS]
                line += f" | {hz} {p_} wA {0.75*kb:.2f} [{0.75*min(lo):.2f}-{0.75*max(lo):.2f}] gain {100*(se[kb]/se[0.0]-1):+.1f}%"
        P(line)
    # partial value: ROS rate ~ season pts/g + xFP/g + ADP-free history prior (+ games) vs the same + ln ADP; LOYO per position, vets with ADP
    P("\n  PARTIAL VALUE OF ADP once 2026 points, xFP and history are known: LOYO OLS of ROS half PPG (weighted by ROS games) on [pts/g, xFP/g, ADP-free history prior, g]"
      " vs the same + ln(ADP). MSE change from adding ADP (negative = ADP still explains something), seasons improved, ln ADP coef (t).")
    lnadp = np.log(np.clip(adp, 1, 300))
    for W in (6, 8, 10):
        line = f"    after wk {W:2d}"
        for p_ in POS4:
            m_ = ok & (wk == W + 1) & (pos == p_) & mk & ~np.isnan(X["xf"]) & ~np.isnan(X["ppg_v"]) & ~np.isnan(hm) & ~np.isnan(lnadp)
            if m_.sum() < 60: continue
            ix = np.where(m_)[0]
            Xa = np.column_stack([np.ones(len(ix)), X["ppg_v"][ix], X["xf"][ix], hm[ix], g[ix]]); Xb = np.column_stack([Xa, lnadp[ix]]); y_ = T[ix]
            yy = year[ix]; e_a = np.zeros(len(ix)); e_b = np.zeros(len(ix)); win = 0; nf = 0
            for y in YEARS:
                tr = yy != y; te = yy == y
                if te.sum() < 5: continue
                ba = np.linalg.lstsq(Xa[tr], y_[tr], rcond=None)[0]; bb = np.linalg.lstsq(Xb[tr], y_[tr], rcond=None)[0]
                e_a[te] = (Xa[te] @ ba - y_[te]) ** 2; e_b[te] = (Xb[te] @ bb - y_[te]) ** 2; nf += 1; win += e_b[te].mean() < e_a[te].mean()
            bfull, res, *_ = np.linalg.lstsq(Xb, y_, rcond=None); rr_ = y_ - Xb @ bfull; s2 = rr_ @ rr_ / (len(y_) - Xb.shape[1])
            se_ = np.sqrt(s2 * np.linalg.inv(Xb.T @ Xb)[-1, -1])
            line += f" | {p_} n {len(ix)} ADP adds {100*(e_b.mean()/e_a.mean()-1):+.1f}% ({win}/{nf}) coef {bfull[-1]:+.2f} (t {bfull[-1]/se_:+.1f})"
        P(line)
    log.close()


if __name__ == "__main__":
    main()
