#!/usr/bin/env python3
"""
JM in the Clay-free model (Jack 2026-10-02: "do we have the jm model factoring in at all?" / "lets continue").
JM reaches the shadow only through the learned season prior (ridge, 16 features, v2.16), mixed 50 / 50 with the hand
prior for RB / WR / TE and not at all for QB (ridgeW QB 0). Three questions, at both horizons:

  A  what JM itself is worth: the learned prior rebuilt WITHOUT the jm feature vs with it
  B  how much of the learned prior each position should take (weight 0 / .25 / .5 shipped / .75 / 1)
  C  quarterbacks: let them use the learned prior at all (weight 0 shipped / .25 / .5 / .75 / 1), with and without JM

NEXT GAME = the backtest_shadow_next harness with the pruned v2.29 layer set (17,569 player-weeks).
REST OF SEASON = the backtest_shadow_ros checkpoint form (3-10 games played), with and without the 4-games-left filter.
Each variant: error on the rows it changes (seasons better at that fixed setting), whole-board top-150 weighted
error, weekly rank order within position. Log jm_ridge.log.
"""
import os, sys
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
NW = SN.NW; SL = SN.SL; YEARS = SN.YEARS; POS4 = ("QB", "RB", "WR", "TE")

def main():
    log = open(os.path.join(HERE, "jm_ridge.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n"); log.flush()
    X = SN.setup(); n = X["n"]; F = X["F"]; A = X["A"]
    act, year, wk, pos, g, adp, name, layers = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["layers"]
    T_ = SL.build_table(); BASE = [f for f in SL.BASIC if f != "mover"]
    def ridge_for(feats):
        v = SL.loyo(T_, feats, "ridge", 10.0); key = {(int(y), nm, ps): x for y, nm, ps, x in zip(T_.year, T_.name, T_.pos, v)}
        return np.array([key.get((int(year[i]), name[i], pos[i]), np.nan) for i in range(n)])
    r_jm = ridge_for(BASE + ["jm"]); r_no = ridge_for(BASE); Fp = F["prior"]
    SHIP = {"QB": 0.0, "RB": 0.5, "WR": 0.5, "TE": 0.5}
    def prior_of(wd, ridge):
        out = Fp.copy()
        for ps, w in wd.items():
            m = (pos == ps) & ~np.isnan(ridge); out[m] = w * ridge[m] + (1 - w) * Fp[m]
        return out
    p_ship = prior_of(SHIP, r_jm)
    P(f"=== JM / learned prior: shipped prior rebuilt, max difference from the harness prior {np.nanmax(np.abs(p_ship - X['prior'])):.4f}; JM changes the learned prior on {int((np.abs(r_jm - r_no) > 1e-6).sum()):,} rows ===")
    jmcol = pd.Series(T_.jm.values) if "jm" in T_.columns else None
    if jmcol is not None: P(f"  player-seasons with a JM score in the training table: {int(jmcol.notna().sum())} of {len(T_)}")

    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = A["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    smx = colv("snapmult"); smx = np.where(np.isnan(smx), 1.0, smx); y2 = colv("yr2") == 1
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    base_lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))

    # ---------- next game ----------
    SH = SN.shadow(X); l1 = X["snap_l1"]; allr = ~final & (SH >= 3); dev = np.zeros(n)
    for ps in ("WR", "TE"):
        m = (pos == ps) & (g >= 1) & ~np.isnan(l1) & allr
        q = np.quantile(SH[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, SH, side="right") - 1, 0, 7)
        for k in range(8):
            mk = m & (b_ == k)
            if mk.sum() >= 30: dev[mk] = l1[mk] - np.nanmean(l1[mk])
    low = np.maximum(0, 19 - np.nan_to_num(X["implied"], nan=19)) / 19
    EX = np.ones(n)
    EX = np.where(np.isin(pos, ["RB", "TE"]), EX * smx, EX)                                   # snap trend (WR pruned in v2.29)
    EX = np.where(np.isin(pos, ["WR", "TE"]), EX * np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4), EX)
    EX = np.where((pos == "QB") & X["mover"], EX * 0.90, EX); EX = np.where(pos == "QB", EX * (1 - 0.75 * low), EX)
    EX = np.where((pos == "RB") & (g >= 2) & (g <= 5) & (X["car_sh"] < 0.30), EX * 0.90, EX)
    def nxt(prior):
        X2 = dict(X); X2["prior"] = prior
        return SN.shadow(X2) * EX
    # ---------- rest of season ----------
    seq = defaultdict(list)
    for i in range(n):
        if not final[i]: seq[(name[i], pos[i], int(year[i]))].append(i)
    for ix in seq.values(): ix.sort(key=lambda i: wk[i])
    def ros_target(minf):
        T = np.full(n, np.nan); ctx = np.full(n, np.nan)
        for ix in seq.values():
            a_ = act[ix]; l_ = np.clip(layers[ix], 0.5, 1.8)
            for a, i in enumerate(ix):
                if len(ix) - a >= minf: T[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
        return T, ctx
    mid = (adp > 60) & (adp <= 100); late = (adp > 100) & (adp <= 150)
    lam_r = np.where((pos == "WR") & late, np.minimum(base_lam, 0.25), base_lam); ev_r = lam_r * X["xf"] + (1 - lam_r) * X["ppg_v"]
    EXR = np.where(pos == "RB", smx, 1.0) * np.where((pos == "QB") & X["mover"], 0.84, 1.0)
    def ros(prior, ctx):
        pm = np.where((pos == "RB") & mid, 2.5, np.where((pos == "WR") & mid, 0.6, np.where((pos == "QB") & y2, 0.75, 1.0)))
        pm = np.where((pos == "WR") & late & (ev_r < prior), pm * 0.4, pm); Pw = X["Pw"] * pm
        return (Pw * prior + g * ev_r) / np.maximum(Pw + g, 1e-9) * ctx * EXR

    def evaluate(title, model, target, okm):
        base_ = okm & top150
        ms = lambda q, m: float(np.mean((q[m] - target[m]) ** 2)) if m.any() else np.nan
        wm = lambda q, m: float(np.average((q[m] - target[m]) ** 2, weights=wt[m])) if m.any() else np.nan
        def rho(q, m):
            gr = defaultdict(list)
            for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
            rh = [np.corrcoef(rankdata(target[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]
            return float(np.mean(rh)) if rh else np.nan
        B = model(p_ship)
        P(f"\n##### {title}: {int(okm.sum()):,} rows, {int(base_.sum()):,} top-150; shipped rank order {rho(B, base_):.4f} #####")
        def line(lab, V, rows=None):
            tm = okm & (np.abs(V - B) > 1e-9) if rows is None else okm & rows
            if tm.sum() < 50: P(f"    {lab:44s} (too few rows changed)"); return
            sb = sum(1 for y in YEARS if (tm & (year == y)).sum() >= 8 and ms(V, tm & (year == y)) < ms(B, tm & (year == y)) - 1e-12)
            sw = sum(1 for y in YEARS if wm(V, base_ & (year == y)) < wm(B, base_ & (year == y)) - 1e-12)
            P(f"    {lab:44s} rows {int(tm.sum()):5d}  its rows {100*(ms(V, tm)/ms(B, tm)-1):+6.2f}% ({sb}/7)  | whole board: all {100*(ms(V, okm)/ms(B, okm)-1):+6.2f}%  top-150 weighted {100*(wm(V, base_)/wm(B, base_)-1):+6.2f}% ({sw}/7)  rank order {rho(V, base_) - rho(B, base_):+.4f}")
        P("  A  the learned prior WITHOUT the jm feature (positive = JM is helping)")
        line("without JM, RB + WR + TE", model(prior_of(SHIP, r_no)))
        for ps in ("RB", "WR", "TE"): line(f"without JM, {ps} only", model(np.where(pos == ps, prior_of(SHIP, r_no), p_ship)))
        rk_ = np.array(A["rookie"], dtype=bool); yng = rk_ | y2
        line("without JM, rookies + second-year", model(np.where(yng, prior_of(SHIP, r_no), p_ship)))
        line("without JM, veterans (3+ years)", model(np.where(~yng, prior_of(SHIP, r_no), p_ship)))
        P("  B  weight on the learned prior by position (shipped .5)")
        for ps in ("RB", "WR", "TE"):
            for w in (0.0, 0.25, 0.75, 1.0):
                wd = dict(SHIP); wd[ps] = w; line(f"{ps} weight {w}", model(prior_of(wd, r_jm)))
        P("  C  quarterbacks on the learned prior (shipped: weight 0)")
        for w in (0.25, 0.5, 0.75, 1.0):
            wd = dict(SHIP); wd["QB"] = w; line(f"QB weight {w}, with JM", model(prior_of(wd, r_jm)))
        for w in (0.5, 1.0):
            wd = dict(SHIP); wd["QB"] = w; line(f"QB weight {w}, without JM", model(prior_of(wd, r_no)))
        wd = dict(SHIP); wd["QB"] = 0.5; V = model(prior_of(wd, r_jm))
        for lab, m in (("  QB weight .5: rookies + second-year", (pos == "QB") & yng), ("  QB weight .5: veterans", (pos == "QB") & ~yng), ("  QB weight .5: ADP 1-100", (pos == "QB") & (adp <= 100)), ("  QB weight .5: ADP 101+ / none", (pos == "QB") & ~(adp <= 100))):
            line(lab, V, m)

        P("  D  only quarterbacks drafted after pick 100 (or undrafted) on the learned prior; then with RB weight .75")
        lateq = (pos == "QB") & ~(adp <= 100) & ~np.isnan(r_jm)
        def with_lateq(w, rbw=0.5):
            wd = dict(SHIP); wd["RB"] = rbw; pr = prior_of(wd, r_jm); pr = pr.copy(); pr[lateq] = w * r_jm[lateq] + (1 - w) * Fp[lateq]; return pr
        for w in (0.25, 0.5, 0.75, 1.0): line(f"late QB weight {w}", model(with_lateq(w)))
        line("RB weight .75 + late QB weight .5", model(with_lateq(0.5, 0.75)))
        line("RB weight .75 + late QB weight .75", model(with_lateq(0.75, 0.75)))

    evaluate("NEXT GAME", nxt, act, allr)
    for minf in (4, 1):
        T, ctx = ros_target(minf)
        okm = ~np.isnan(T) & (g >= 3) & (g <= 10) & (ros(p_ship, np.nan_to_num(ctx, nan=1.0)) >= 3)
        evaluate(f"REST OF SEASON, {minf}+ games left", lambda pr, ctx=ctx: ros(pr, np.nan_to_num(ctx, nan=1.0)), np.nan_to_num(T, nan=0.0), okm)
    log.close()

if __name__ == "__main__":
    main()
