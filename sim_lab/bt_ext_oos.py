#!/usr/bin/env python3
"""
OUT-OF-SAMPLE CHECK OF THE WIRED SHADOW ON 2012-18 (2026-10-20, Jack: "yes download back to 2012 and rebuild").

Every wired piece of the Clay-free shadow was picked on 2019-25. Run in extended mode (SIM_BT_YEARS=2012-2025) this script
grades each piece, at its WIRED setting (no refitting of the piece), on the seasons it never saw (2012-18) next to the seasons
it was tuned on (2019-25). Same house rules as ablate_shadow_next.py / backtest_shadow_ros.py section 10: the model as wired,
one piece removed at a time; negative % = having the piece helps; whole board all rows, top-150 importance-weighted (ADP
curve level ^2), MAE, weekly rank order within position (top 150), seasons it helps; final week out.

  A  NEXT GAME  pieces of ablate_shadow_next.full() minus the two pruned 10-02 (WR snap trend, rookie WR games 2-5)
  B  REST OF SEASON  pieces of backtest_shadow_ros.py section 10 + v2.33 rookie prior weight (RB 1.6 / TE 2.5)
  C  PRIOR pieces (both horizons): ADP market blend .75, depth-string docks, 2nd-year low-snap x1.2, shrink .8, ridge mix
Base constants (ADP curve, rookie fallback, position means, ridge, opportunity prior) are fit leave-one-season-out over
every season in SIM_BT_YEARS, exactly as the default harness does over 2019-25.
Log: _bt_ext/oos_check<TAG>.log
  SIM_BT_YEARS=2012-2025 python bt_ext_oos.py
"""
import os, sys
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
import backtest_shadow_ros as SR
import backtest_rookie_depth_live as RD   # noqa: F401 (keeps import order identical to the harness)
import backtest_nochart_vets as NC
BX = SN.BX; YEARS = SN.YEARS; POS4 = ("QB", "RB", "WR", "TE")


def main():
    log = open(BX.ext_path("oos_check.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n"); log.flush()
    X = SN.setup(); n = X["n"]; F = X["F"]; A = X["A"]
    act, year, wk, pos, g, name, adp, layers = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["name"], X["adp"], X["layers"]
    ERAS = [(f"{YEARS[0]}-18 (out of sample)", year <= 2018), ("2019-25 (tuned on)", year >= 2019)]
    if YEARS[0] <= 2012:
        ERAS.insert(1, ("2013-18 (no 2012 warm-up)", (year >= 2013) & (year <= 2018)))
    if YEARS[0] <= 2015:   # the injury report changed in 2016 (Probable dropped; Questionable / Doubtful mean less before)
        ERAS.insert(len(ERAS) - 1, ("2016-18 (modern injury report)", (year >= 2016) & (year <= 2018)))
    P(f"=== OOS check of the wired shadow: {BX.describe()} | {n:,} player-weeks ===")
    for lab, m in ERAS: P(f"    {lab:28s} rows {int(m.sum()):,}")

    # ---------------- prior variants (section C) ----------------
    fb_pos, hist, adp_curve, mkt_ok, fb, wv, vet, yr2lo, strb = F["fb_pos"], F["hist_adj"], F["adp_curve"], F["mkt_ok"], F["fb"], F["wv"], F["vet"], F["yr2lo"], F["strb"]
    mixed = (pos != "QB") & (np.abs(X["prior"] - F["prior"]) > 1e-12)
    ridge_half = np.where(mixed, X["prior"] - 0.5 * F["prior"], np.nan)          # = 0.5 x ridge on the mixed rows
    def prior_of(off=()):
        pr = np.where(mkt_ok, (1 - wv) * hist + wv * adp_curve, hist) if "ADP market blend .75" not in off else hist.copy()
        miss = np.isnan(pr); pr = np.where(miss, fb, pr)
        if "depth-string docks (vets)" not in off:
            for ps, d in NC.VETDOCK.items():
                for sb, mm_ in d.items():
                    mk = vet & (pos == ps) & (strb == sb); pr = np.where(mk, pr * mm_, pr)
        if "2nd-year low-snap x1.2" not in off: pr = np.where(yr2lo & vet, pr * 1.2, pr)
        k = 1.0 if "shrink toward position mean .8" in off else 0.8
        fp = fb_pos + k * (pr - fb_pos)
        if "ridge season prior mix" in off: return fp
        return np.where(mixed, ridge_half + 0.5 * fp, fp)
    chk = prior_of()
    P(f"  prior rebuild check: max |rebuilt - harness| = {np.nanmax(np.abs(chk - X['prior'])):.2e}")
    PRIOR_PIECES = ["ADP market blend .75", "depth-string docks (vets)", "2nd-year low-snap x1.2", "shrink toward position mean .8", "ridge season prior mix"]

    C = pd.read_parquet(BX.ext_path("ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = A["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    P(f"  ctx coverage of harness rows: {has.mean():.3f} (week-1 rows have none by design)")

    def grade_table(title, FULLp, wo_fn, pieces, err_rows, base_rows, target, wt, n_min=8):
        ms = lambda q, m: float(np.mean((q[m] - target[m]) ** 2)) if m.any() else np.nan
        ma = lambda q, m: float(np.mean(np.abs(q[m] - target[m]))) if m.any() else np.nan
        wm = lambda q, m: float(np.average((q[m] - target[m]) ** 2, weights=wt[m])) if m.any() else np.nan
        def rho(q, m):
            gr = defaultdict(list)
            for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
            rh = [np.corrcoef(rankdata(target[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= n_min]
            return float(np.mean(rh)) if rh else np.nan
        P(); P(f"=== {title} ===")
        for lab, em in ERAS:
            a_, b_ = err_rows & em, base_rows & em
            P(f"  {lab}: full model rows {int(a_.sum()):,} (top-150 {int(b_.sum()):,}) | MSE {ms(FULLp, a_):.3f} MAE {ma(FULLp, a_):.3f} | top-150 wtd MSE {wm(FULLp, b_):.3f} | rank order {rho(FULLp, b_):.4f} | act/proj {target[a_].sum()/FULLp[a_].sum():.3f}")
        P(f"    {'piece':46s} | " + " | ".join(f"{lab[:7]}: all / top-150 wtd / MAE / rank (seasons wtd)" for lab, _ in ERAS))
        out = {}
        for k in pieces:
            WO = wo_fn(k); cells = []; verdict = []
            for lab, em in ERAS:
                a_, b_ = err_rows & em, base_rows & em
                a = 100 * (ms(FULLp, a_) / ms(WO, a_) - 1); b = 100 * (wm(FULLp, b_) / wm(WO, b_) - 1); mae = 100 * (ma(FULLp, a_) / ma(WO, a_) - 1); r = rho(FULLp, b_) - rho(WO, b_)
                ys = [y for y in YEARS if (b_ & (year == y)).any()]
                sb = sum(1 for y in ys if wm(FULLp, b_ & (year == y)) < wm(WO, b_ & (year == y)) - 1e-12)
                bad = (a > 0) + (b > 0) + (r < 0)
                v = "HURTS" if bad >= 2 else ("mixed" if bad == 1 else "helps")
                if abs(a) < 0.005 and abs(b) < 0.005: v = "no rows"
                cells.append(f"{a:+6.2f}% {b:+6.2f}% {mae:+6.2f}% {r:+.4f} ({sb}/{len(ys)}) {v:5s}"); verdict.append((lab, v, a, b, r, sb, len(ys)))
            touched = int((np.abs(WO - FULLp) > 1e-9)[err_rows].sum())
            P(f"    {k:46s} | " + " | ".join(cells) + f"  [rows touched {touched:,}]")
            P(f"      by season, top-150 wtd %: " + " ".join(f"{y % 100:02d}:{100 * (wm(FULLp, base_rows & (year == y)) / wm(WO, base_rows & (year == y)) - 1):+.2f}" for y in YEARS if (base_rows & (year == y)).any()))
            out[k] = verdict
        return out

    # ================= A  NEXT GAME =================
    SH = SN.shadow(X)
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    base = top150 & ~final; allr = ~final & (SH >= 3)
    base_lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    l1n = X["snap_l1"]; devn = np.zeros(n)
    for ps in ("WR", "TE"):
        m = (pos == ps) & (g >= 1) & ~np.isnan(l1n) & allr
        q = np.quantile(SH[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, SH, side="right") - 1, 0, 7)
        for k in range(8):
            mk = m & (b_ == k)
            if mk.sum() >= 30: devn[mk] = l1n[mk] - np.nanmean(l1n[mk])
    low = np.maximum(0, 19 - np.nan_to_num(X["implied"], nan=19)) / 19
    smx = colv("snapmult"); smx = np.where(np.isnan(smx) | (pos == "QB"), 1.0, smx)
    PRUNED = ("snap trend (engine layer), WR", "v2.25 rookie WR games 2-5 x.90")
    def full_next(off=()):
        off = tuple(off) + PRUNED; on = lambda k: k not in off
        lam = base_lam.copy()
        if not on("usage evidence, WR"): lam = np.where(pos == "WR", 0.0, lam)
        if not on("usage evidence, RB"): lam = np.where(pos == "RB", 0.0, lam)
        pts = X["ppg_v"] if on("Vegas-cleaned evidence") else X["ppg"]
        ev = lam * X["xf"] + (1 - lam) * pts
        pr_ = prior_of(tuple(k for k in off if k in PRIOR_PIECES))
        Pw = F["Pvec"] * (np.where((pos == "WR") & (g == 1), 5.0, 1.0) if on("WR one-game prior x5") else 1.0)
        out = (Pw * pr_ + g * ev) / np.maximum(Pw + g, 1e-9) * X["layers"]
        if on("rookie ramp (not first string, weeks 1-2)"):
            for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
        if on("vacated-role pool"): out = np.where(F["on"], out * np.power(F["pm"], 0.75), out)
        if on("QB game-total tilt"): out = np.where(pos == "QB", out * np.exp(0.03 * X["z"]), out)
        if on("WR dock when the QB is out"): out = np.where((pos == "WR") & X["qbo"], out * np.where(adp <= 60, 0.85, 0.95), out)
        for ps_ in ("RB", "WR", "TE"):
            if on(f"snap trend (engine layer), {ps_}"): out = np.where(pos == ps_, out * smx, out)
        if on("v2.25 snap-share level, WR"): out = np.where(pos == "WR", out * np.clip(1 + 0.3 * devn / 100.0, 0.7, 1.4), out)
        if on("v2.25 snap-share level, TE"): out = np.where(pos == "TE", out * np.clip(1 + 0.3 * devn / 100.0, 0.7, 1.4), out)
        if on("v2.25 QB changed teams x.90"): out = np.where((pos == "QB") & X["mover"], out * 0.90, out)
        if on("v2.25 QB low team total"): out = np.where(pos == "QB", out * (1 - 0.75 * low), out)
        if on("v2.25 RB under 30% of carries, games 2-5 x.90"): out = np.where((pos == "RB") & (g >= 2) & (g <= 5) & (X["car_sh"] < 0.30), out * 0.90, out)
        return out
    NEXT_PIECES = ["usage evidence, WR", "usage evidence, RB", "Vegas-cleaned evidence", "WR one-game prior x5", "rookie ramp (not first string, weeks 1-2)", "vacated-role pool", "QB game-total tilt",
                   "WR dock when the QB is out", "snap trend (engine layer), RB", "snap trend (engine layer), TE", "v2.25 snap-share level, WR", "v2.25 snap-share level, TE", "v2.25 QB changed teams x.90",
                   "v2.25 QB low team total", "v2.25 RB under 30% of carries, games 2-5 x.90"] + PRIOR_PIECES
    FULLN = full_next()
    resA = grade_table("A  NEXT GAME: each wired piece removed (negative = it helps)", FULLN, lambda k: full_next((k,)), NEXT_PIECES, allr, base, act, wt)

    # ================= B  REST OF SEASON =================
    MINF = 4
    seq = defaultdict(list)
    for i in range(n):
        if wk[i] != finw[i]: seq[(name[i], pos[i], int(year[i]))].append(i)
    T = np.full(n, np.nan); ctx = np.full(n, np.nan)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i])
        a_ = act[ix]; l_ = np.clip(layers[ix], 0.5, 1.8)
        for a, i in enumerate(ix):
            if len(ix) - a >= MINF: T[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    R0 = SR.rate(X); ok = ~np.isnan(T) & (g >= 3) & (g <= 10) & (R0 * ctx >= 3)
    pred = lambda r: r * ctx
    SHr = pred(R0)
    def z_of(v, m):
        out = np.zeros(n); mm = m & ok & ~np.isnan(v); ap = m & ~np.isnan(v)
        if mm.sum() > 50: out[ap] = np.clip((v[ap] - v[mm].mean()) / v[mm].std(), -2, 2)
        return out
    rk, y2 = colv("rookie") == 1, colv("yr2") == 1
    sm = colv("snapmult"); sm = np.where(np.isnan(sm), 1.0, sm)
    l1 = colv("snap_l1"); dev = np.zeros(n)
    for ps in ("WR", "TE"):   # bins on the shipped rate (the ROS harness bins on its stacked S5; same idea)
        m = ok & (pos == ps) & ~np.isnan(l1); q = np.quantile(SHr[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, SHr, side="right") - 1, 0, 7)
        for k in range(8):
            mk = m & (b_ == k)
            if mk.sum() >= 30: dev[mk] = l1[mk] - l1[mk].mean()
    zp = z_of(colv("proe_std"), pos == "TE"); zpl10 = z_of(colv("plays_pg_std"), pos == "RB")
    band = {"ADP 61-100": (adp > 60) & (adp <= 100), "ADP 101-150": (adp > 100) & (adp <= 150)}
    t36 = (pos == "TE") & (adp > 30) & (adp <= 60)
    bl = SR.base_lam(pos, g)
    def full_ros(off=()):
        on = lambda k: k not in off
        lam_ = np.zeros(n) if not on("usage evidence (all positions)") else bl.copy()
        if on("WR 101-150 usage cap .25"): lam_ = np.where((pos == "WR") & band["ADP 101-150"], np.minimum(lam_, 0.25), lam_)
        pts = X["ppg_v"] if on("Vegas-cleaned evidence") else X["ppg"]
        ev = lam_ * X["xf"] + (1 - lam_) * pts
        pr_ = prior_of(tuple(k for k in off if k in PRIOR_PIECES))
        pm_ = np.ones(n)
        if on("RB 61-100 prior weight x2.5"): pm_ = np.where((pos == "RB") & band["ADP 61-100"], 2.5, pm_)
        if on("WR 61-100 prior weight x0.6"): pm_ = np.where((pos == "WR") & band["ADP 61-100"], 0.6, pm_)
        if on("second-year QB prior weight x0.75"): pm_ = np.where((pos == "QB") & y2, 0.75, pm_)
        if on("WR 101-150 cold prior weight x0.4"): pm_ = np.where((pos == "WR") & band["ADP 101-150"] & (ev < pr_), pm_ * 0.4, pm_)
        if on("rookie prior weight RB 1.6 / TE 2.5 (v2.33)"): pm_ = np.where(rk & (pos == "RB"), pm_ * 1.6, np.where(rk & (pos == "TE"), pm_ * 2.5, pm_))
        Pw = X["Pw"] * pm_
        out = pred((Pw * pr_ + g * ev) / np.maximum(Pw + g, 1e-9))
        if on("RB snap trend carried"): out = np.where(pos == "RB", out * sm, out)
        if on("QB changed teams x.84"): out = np.where((pos == "QB") & X["mover"], out * 0.84, out)
        if on("TE snap-share level e .3"): out = np.where((pos == "TE") & ~np.isnan(l1), out * np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4), out)
        if on("TE team pass-rate tilt e .04"): out = np.where(pos == "TE", out * (1 - 0.04 * zp), out)
        if on("TE 31-60 x1.10"): out = np.where(t36, out * 1.10, out)
        if on("RB team play-volume tilt e .04"): out = np.where(pos == "RB", out * np.clip(1 - 0.04 * zpl10, 0.8, 1.25), out)
        if on("RB backup (top 150) x1.04"): out = np.where((pos == "RB") & (strb >= 2) & (adp <= 150), out * 1.04, out)
        return out
    ROS_PIECES = ["usage evidence (all positions)", "Vegas-cleaned evidence", "RB snap trend carried", "QB changed teams x.84", "TE snap-share level e .3", "TE team pass-rate tilt e .04",
                  "RB 61-100 prior weight x2.5", "WR 61-100 prior weight x0.6", "second-year QB prior weight x0.75", "WR 101-150 usage cap .25", "TE 31-60 x1.10", "WR 101-150 cold prior weight x0.4",
                  "RB team play-volume tilt e .04", "RB backup (top 150) x1.04", "rookie prior weight RB 1.6 / TE 2.5 (v2.33)"] + PRIOR_PIECES
    FULLR = full_ros()
    lvr = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lvr[m & np.isnan(lvr)] = np.nanmin(lvr[m]); lvr[m] = lvr[m] / lvr[m & top150].mean()
    wtr = np.maximum(0.05, lvr) ** 2
    resB = grade_table("B  REST OF SEASON (3-10 games played, 4+ left): each wired piece removed (negative = it helps)", FULLR, lambda k: full_ros((k,)), ROS_PIECES, ok, ok & top150, T, wtr)

    # ================= summary =================
    P(); P("=== SUMMARY: pieces that help on 2019-25 (where they were tuned) but NOT out of sample ===")
    oos = ERAS[0][0]
    for title, res in (("next game", resA), ("rest of season", resB)):
        for k, v in res.items():
            d = {lab: (vv, a, b, r, sb, ny) for lab, vv, a, b, r, sb, ny in v}
            o, t = d[oos], d["2019-25 (tuned on)"]
            if o[0] in ("HURTS", "mixed") or (o[2] > 0):
                P(f"  {title:15s} {k:46s} OOS {o[0]:5s} (all {o[1]:+.2f}%, top-150 wtd {o[2]:+.2f}%, rank {o[3]:+.4f}, seasons {o[4]}/{o[5]}) | tuned era {t[0]} (wtd {t[2]:+.2f}%, {t[4]}/{t[5]})")
    log.close()


if __name__ == "__main__":
    main()
