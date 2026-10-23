#!/usr/bin/env python3
"""
MID-SEASON TEAM CHANGES on the 2012-25 extended harness (Jack 2026-10-20, MHJ ARI -> HOU; coordinator rerun after the
2012 extension + per-game team fix in bt_teams.py). RESEARCH ONLY. Run with SIM_BT_YEARS=2012-2025.
Sections 0-14 = backtest_shadow_ros.py as wired (EXT-aware); 17 preamble from research_return_ramp_ros.py; 22-27 from
research_midseason_trade.py, movers read from the harness's own per-game teams (no patch). Baseline next game includes the
WIRED new-team debut dock (x0.7 RB/WR/TE, newTeamDebutMult). Log _bt_ext/midseason_trade_ext<TAG>.log.
"""
import os, sys
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
NW = SN.NW; YEARS = SN.YEARS; POS4 = ("QB", "RB", "WR", "TE")
BX = SN.BX; NY, FWL, YL = SN.NY, SN.FWL, SN.YL
FWD = SN.FWD   # default (2022, 2023, 2024, 2025)
MINF = int(os.environ.get("ROS_MINF", "4"))   # games left needed for a checkpoint (1 = no survivor filter, noisier)

def base_lam(pos, g):
    return np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))

def rate(X, pscale=None, lam=None, evid=None):
    """context-free shadow rate; pscale = {pos: multiplier on the prior weight}, lam = usage weight per row"""
    pos, g = X["pos"], X["g"]
    Pw = X["Pw"].copy()
    if pscale:
        for ps, k in pscale.items(): Pw = np.where(pos == ps, Pw * k, Pw)
    if lam is None: lam = base_lam(pos, g)
    ev = lam * X["xf"] + (1 - lam) * X["ppg_v"] if evid is None else evid
    return (Pw * X["prior"] + g * ev) / np.maximum(Pw + g, 1e-9)

def main():
    log = open(BX.ext_path("midseason_trade.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n"); log.flush()
    X = SN.setup(); n = X["n"]; F = X["F"]; A = X["A"]
    act, year, wk, pos, g, name, adp, layers = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["name"], X["adp"], X["layers"]
    finw = np.where(year <= 2020, 17, 18)
    # rest-of-season target + context
    seq = defaultdict(list)
    for i in range(n):
        if wk[i] != finw[i]: seq[(name[i], pos[i], int(year[i]))].append(i)
    T = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int); T1 = np.full(n, np.nan); ctx1 = np.full(n, np.nan)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i])
        a_ = act[ix]; l_ = np.clip(layers[ix], 0.5, 1.8)
        for a, i in enumerate(ix):
            nfut[i] = len(ix) - a; T1[i] = a_[a:].mean(); ctx1[i] = l_[a:].mean()
            if nfut[i] >= MINF: T[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    R0 = rate(X); clay_rate = F["shipped"] / np.where(layers > 0, layers, 1.0)
    ok = ~np.isnan(T) & (g >= 3) & (g <= 10) & (R0 * ctx >= 3)
    top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    ms = lambda q, m: float(np.mean((q[m] - T[m]) ** 2)) if m.any() else np.nan
    wm = lambda q, m: float(np.average((q[m] - T[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    def rho(q, m):
        gr = defaultdict(list)
        for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        rh = [np.corrcoef(rankdata(T[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]
        return float(np.mean(rh)) if rh else np.nan
    pred = lambda r: r * ctx
    SH = pred(R0); CL = pred(clay_rate)
    P(f"=== rest-of-season, in season: {int(ok.sum()):,} checkpoints {YL} (3-10 games played, {MINF}+ games left), {int((ok & top150).sum()):,} top-150 ===")

    # ---------------- 0 where we stand ----------------
    P("\n--- 0  WHERE WE STAND: Clay-free rate vs the Clay blend, rest-of-season per-game ---")
    def stand(lab, m):
        m = m & ok
        if m.sum() < 100: return
        w = sum(1 for y in YEARS if ms(SH, m & (year == y)) < ms(CL, m & (year == y)))
        P(f"    {lab:26s} n {int(m.sum()):5d}  actual {T[m].mean():5.2f}  Clay-free {SH[m].mean():5.2f}  Clay blend {CL[m].mean():5.2f}  | Clay-free error vs Clay blend {100*(ms(SH, m)/ms(CL, m)-1):+6.2f}%  seasons better {w}/{NY}"
          f"  top-150 weighted {100*(wm(SH, m & top150)/wm(CL, m & top150)-1):+6.2f}%  | rank order {rho(SH, m & top150):.3f} vs {rho(CL, m & top150):.3f}")
    stand("everyone", np.ones(n, bool))
    for ps in POS4: stand(ps, pos == ps)
    for lab, lo, hi in (("after 3-4 games", 3, 4), ("after 5-7 games", 5, 7), ("after 8-10 games", 8, 10)): stand(lab, (g >= lo) & (g <= hi))
    for lab, lo, hi in (("ADP 1-30", 1, 30), ("ADP 31-60", 31, 60), ("ADP 61-100", 61, 100), ("ADP 101-150", 101, 150)): stand(lab, (adp >= lo) & (adp <= hi))
    for ps in POS4:
        for lab, lo, hi in (("3-4", 3, 4), ("5-7", 5, 7), ("8-10", 8, 10)): stand(f"{ps} after {lab} games", (pos == ps) & (g >= lo) & (g <= hi))

    # ---------------- test machinery ----------------
    PICK = {}
    def test(title, fam, m_rows, key=None):
        names = list(fam); b = fam[names[0]]; touched = np.zeros(n, bool)
        for k_ in names[1:]: touched |= np.abs(fam[k_] - b) > 1e-9
        tm = m_rows & ok & touched
        pick = lambda yrs: min(names, key=lambda k: ms(fam[k], tm & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = b.copy()
            for tr, te in folds:
                k = pick(tr); picks.append(k); m = year == te; pr[m] = fam[k][m]; wins += ms(fam[k], tm & m) < ms(b, tm & m) - 1e-12
            tem = np.isin(year, [te for _, te in folds])
            return pr, 100 * (ms(pr, tm & tem) / ms(b, tm & tem) - 1), 100 * (wm(pr, tm & tem & top150) / wm(b, tm & tem & top150) - 1), wins, picks
        lo = run([([y for y in YEARS if y != t], t) for t in YEARS]); fw = run([([y for y in YEARS if y < t], t) for t in FWD])
        best = pick(YEARS)
        okk = best != names[0] and lo[1] < -0.3 and lo[3] >= 5 and fw[1] < 0 and fw[3] >= 3 and lo[2] <= 0.1
        P(f"\n  {title}   (rows {int(tm.sum()):,})")
        sb = lambda k: sum(1 for y in YEARS if (tm & (year == y)).sum() >= 8 and ms(fam[k], tm & (year == y)) < ms(b, tm & (year == y)) - 1e-12)
        P("    pooled (seasons better at that fixed setting): " + "  ".join(f"{k}: {100*(ms(fam[k], tm)/ms(b, tm)-1):+.2f}% ({sb(k)})" for k in names[1:]))
        P(f"    LEAVE-ONE-SEASON-OUT  {lo[1]:+.2f}%  seasons better {lo[3]}/{NY}  | top-150 weighted {lo[2]:+.2f}%  rank order {rho(lo[0], tm & top150) - rho(b, tm & top150):+.4f}  | picks {lo[4]}")
        P(f"    FORWARD {FWL}       {fw[1]:+.2f}%  seasons better {fw[3]}/{len(FWD)}  | top-150 weighted {fw[2]:+.2f}%  | picks {fw[4]}")
        if best != names[0]:
            rs = [(rho(fam[best], tm & top150 & (year == y)), rho(b, tm & top150 & (year == y))) for y in YEARS]; rs = [q for q in rs if not (np.isnan(q[0]) or np.isnan(q[1]))]
            if rs: P(f"    rank order with {best}: better in {sum(1 for q in rs if q[0] > q[1] + 1e-9)}/{len(rs)} seasons (pooled {rho(fam[best], tm & top150) - rho(b, tm & top150):+.4f})")
        P(f"    -> {'PASS: ' + str(best) if okk else 'FAIL (best pooled: ' + str(best) + ')'}")
        if okk and key: PICK[key] = best
        return okk, best

    # ---------------- 1 prior weight ----------------
    P("\n--- 1  HOW MUCH THE SEASON SO FAR COUNTS (prior weight in games; shipped QB 12, RB 5, WR 8, TE 8) ---")
    P0 = {"QB": 12, "RB": 5, "WR": 8, "TE": 8}; GRID = {"QB": (4, 6, 8, 16, 24), "RB": (2, 3, 8, 12, 16), "WR": (3, 5, 12, 16, 24), "TE": (3, 5, 12, 16, 24)}
    best_p = {}
    for ps in POS4:
        fam = {f"P {P0[ps]} (shipped)": SH}
        for p_ in GRID[ps]: fam[f"P {p_}"] = pred(rate(X, {ps: p_ / P0[ps]}))
        okk, b = test(f"1 {ps}: prior weight", fam, pos == ps, f"P_{ps}")
        best_p[ps] = float(b.split()[1]) / P0[ps] if okk else 1.0
        for lab, lo_, hi_ in (("3-4 games", 3, 4), ("5-7 games", 5, 7), ("8-10 games", 8, 10)):
            m = (pos == ps) & ok & (g >= lo_) & (g <= hi_)
            P(f"      by stage, {lab}: " + "  ".join(f"{k}: {100*(ms(fam[k], m)/ms(SH, m)-1):+.2f}%" for k in list(fam)[1:]))
    R1 = rate(X, best_p); S1 = pred(R1)

    # ---------------- 2 evidence type ----------------
    P("\n--- 2  WHAT COUNTS AS EVIDENCE: points vs usage (xFP), on top of the picks above ---")
    bl = base_lam(pos, g); best_l = {}
    for ps in POS4:
        fam = {"shipped": S1}
        for l in (0.0, 0.25, 0.5, 0.75, 1.0):
            if ps in ("QB", "TE") and l == 0.0: continue
            fam[f"usage weight {l}"] = pred(rate(X, best_p, np.where(pos == ps, l, bl)))
        okk, b = test(f"2 {ps}: usage weight in the evidence (shipped: {'0' if ps in ('QB', 'TE') else 'fades to .25'})", fam, pos == ps, f"lam_{ps}")
        if okk: best_l[ps] = float(b.split()[-1])
    lam2 = bl.copy()
    for ps, l in best_l.items(): lam2 = np.where(pos == ps, l, lam2)
    R2 = rate(X, best_p, lam2); S2 = pred(R2)

    # ---------------- 3 level ----------------
    P("\n--- 3  LEVEL: toward / away from the position average (k < 1 pulls in) ---")
    S3 = S2.copy()
    for ps in POS4:
        mp = (pos == ps) & ok; fam = {"k 1.00 (shipped)": S2}
        mean_y = {y: float(S2[mp & (year != y)].mean()) for y in YEARS}; mu = np.array([mean_y[int(y)] for y in year])
        for k in (0.8, 0.9, 0.95, 1.05, 1.1): fam[f"k {k}"] = np.where(pos == ps, mu + k * (S2 - mu), S2)
        okk, b = test(f"3 {ps}: level", fam, pos == ps, f"lvl_{ps}")
        if okk: S3 = np.where(pos == ps, fam[b], S3)
        for lab, m in (("top third", mp & (S2 >= np.quantile(S2[mp], 2 / 3))), ("middle", mp & (S2 < np.quantile(S2[mp], 2 / 3)) & (S2 >= np.quantile(S2[mp], 1 / 3))), ("bottom third", mp & (S2 < np.quantile(S2[mp], 1 / 3)))):
            P(f"      {lab:13s} n {int(m.sum()):5d}  actual / projected {T[m].sum()/S2[m].sum():.3f}")

    # ---------------- 5 rest-of-season layers ----------------
    P(); P("--- 5  REST-OF-SEASON LAYERS on the Clay-free rate (each judged on the rows it touches, stacked on what passed before it) ---")
    C = pd.read_parquet(BX.ext_path("ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = A["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    S5 = S3.copy()
    def z_of(v, m):
        out = np.zeros(n); mm = m & ok & ~np.isnan(v); ap = m & ~np.isnan(v)
        if mm.sum() > 50: out[ap] = np.clip((v[ap] - v[mm].mean()) / v[mm].std(), -2, 2)
        return out
    def layer(title, key, m, variants):
        nonlocal S5
        fam = {"off (shipped)": S5}
        for lab, mult in variants.items(): fam[lab] = np.where(m, S5 * mult, S5)
        okk, b = test(title, fam, m, key)
        if okk: S5 = fam[b]
        return okk
    rk, y2, age = colv("rookie") == 1, colv("yr2") == 1, colv("age")
    sm = colv("snapmult"); sm = np.where(np.isnan(sm), 1.0, sm)
    for ps in ("RB", "WR", "TE"):
        layer(f"5a {ps}: snap-trend multiplier carried through the rest of the season", f"snapmult_{ps}", pos == ps, {f"strength {e}": np.power(sm, e) for e in (0.5, 1.0, 1.5)})
    layer("5b RB rookies", "rb_rookie", (pos == "RB") & rk, {f"x{k}": k for k in (1.05, 1.10, 1.15)})
    layer("5b RB second year", "rb_yr2", (pos == "RB") & y2, {f"x{k}": k for k in (1.04, 1.08, 1.12)})
    layer("5b RB age slope (per year from 26)", "rb_age", (pos == "RB") & ~np.isnan(age), {f"{e} a year": np.clip(1 - e * (np.nan_to_num(age, nan=26.0) - 26), 0.85, 1.15) for e in (0.01, 0.02, 0.03)})
    layer("5c TE second year", "te_yr2", (pos == "TE") & y2, {f"x{k}": k for k in (1.05, 1.10, 1.15, 1.20)})
    layer("5c TE rookies", "te_rookie", (pos == "TE") & rk, {f"x{k}": k for k in (1.05, 1.10)})
    l1 = colv("snap_l1"); dev = np.zeros(n)
    for ps in ("WR", "TE"):
        m = ok & (pos == ps) & ~np.isnan(l1); q = np.quantile(S5[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, S5, side="right") - 1, 0, 7)
        for k in range(8):
            mk = m & (b_ == k)
            if mk.sum() >= 30: dev[mk] = l1[mk] - l1[mk].mean()
    for ps in ("TE", "WR"):
        layer(f"5c {ps}: snap-share level, rest of season (wired: .15 for later weeks)", f"snaplv_{ps}", (pos == ps) & ~np.isnan(l1), {f"e {e}": np.clip(1 + e * dev / 100.0, 0.7, 1.4) for e in (0.15, 0.3, 0.5)})
    zp = z_of(colv("proe_std"), pos == "TE")
    layer("5c TE: team pass-rate tilt (pass-heavy teams' tight ends come down)", "te_proe", pos == "TE", {f"e {e}": 1 - e * zp for e in (0.04, 0.08, 0.12)})
    layer("5d QB who changed teams (wired today: x.90)", "qb_mover", (pos == "QB") & X["mover"], {f"x{k}": k for k in (0.95, 0.90, 0.86, 0.82, 0.78)})
    za = z_of(colv("att_pg"), pos == "QB")
    layer("5d QB: pass-attempt tilt (high-volume passers come down)", "qb_att", pos == "QB", {f"e {e}": 1 - e * za for e in (0.03, 0.06, 0.09)})
    zc = z_of(colv("car_sh"), pos == "QB")
    layer("5d QB: rushing-share tilt (running quarterbacks go up)", "qb_rush", pos == "QB", {f"e {e}": 1 + e * zc for e in (0.02, 0.04, 0.06)})
    zy = z_of(colv("yprr_man"), pos == "WR")
    layer("5e WR: yards per route vs man tilt", "wr_yprr", pos == "WR", {f"e {e}": 1 + e * zy for e in (0.02, 0.04, 0.06)})
    zx = z_of(colv("pts_over_xfp"), pos == "WR")
    layer("5e WR: scoring over usage tilt", "wr_eff", pos == "WR", {f"e {e}": 1 + e * zx for e in (0.02, 0.04, 0.06)})
    layer("5e WR scoring 25%+ under his prior", "wr_cold", (pos == "WR") & (X["ppg"] <= 0.75 * X["prior"]), {f"x{k}": k for k in (0.97, 0.94, 0.90)})
    layer("5e WR rookies", "wr_rookie", (pos == "WR") & rk, {f"x{k}": k for k in (1.03, 1.06)})
    P(); P("  level check before any level layer (actual / projected): 4+ games left | any games left | next game only")
    for ps in POS4:
        m4 = ok & (pos == ps); m1 = ~np.isnan(T1) & (g >= 3) & (g <= 10) & (pos == ps) & (R0 * ctx1 >= 3); sc = np.where(S3 > 0, S5 / np.where(S3 > 0, S3, 1), 1.0) * (R2 / np.where(R0 > 0, R0, 1))
        P(f"    {ps}: {T[m4].sum()/S5[m4].sum():.3f} | {T1[m1].sum()/(R0[m1]*ctx1[m1]).sum():.3f} (shipped rate) | {act[m1].sum()/(R0[m1]*np.clip(layers[m1], 0.5, 1.8)).sum():.3f} (shipped rate)")
    layer("5f RB level", "rb_level", pos == "RB", {f"x{k}": k for k in (1.02, 1.04, 1.06)})
    layer("5f TE level", "te_level", pos == "TE", {f"x{k}": k for k in (1.03, 1.06, 1.09, 1.12)})

    # ---------------- stacked ----------------
    P("\n--- STACKED: everything that passed vs the shipped Clay-free rate and vs the Clay blend ---")
    P(f"  picks: {PICK}")
    for lab, m in [("everyone", ok)] + [(ps, ok & (pos == ps)) for ps in POS4] + [("top-150", ok & top150)]:
        w1 = sum(1 for y in YEARS if ms(S5, m & (year == y)) < ms(SH, m & (year == y))); w2 = sum(1 for y in YEARS if ms(S5, m & (year == y)) < ms(CL, m & (year == y)))
        P(f"    {lab:10s} vs shipped Clay-free {100*(ms(S5, m)/ms(SH, m)-1):+.2f}% ({w1}/{NY})  vs Clay blend {100*(ms(S5, m)/ms(CL, m)-1):+.2f}% ({w2}/{NY})  | weighted {100*(wm(S5, m & top150)/wm(SH, m & top150)-1):+.2f}% / {100*(wm(S5, m & top150)/wm(CL, m & top150)-1):+.2f}%"
          f"  | rank order {rho(S5, m & top150):.3f} (shipped {rho(SH, m & top150):.3f}, Clay blend {rho(CL, m & top150):.3f})")

    # ---------------- 4 screen ----------------
    P("\n--- 4  WHAT THE REST-OF-SEASON MISS STILL CORRELATES WITH (after the picks above; r of the miss, seasons same sign) ---")
    res = T - S5
    feats = ["tgt_sh", "car_sh", "rz_tgt_sh", "rz_car_sh", "gl_car_sh", "ay_sh", "wopr", "xfp_pg", "pts_over_xfp", "tgt_trend", "car_trend", "snap_std", "snap_l1", "snap_trend", "db_sh", "att_pg",
             "tgt_sh_py", "car_sh_py", "xfp_pg_py", "ppg_py", "g_py", "team_change", "proe_std", "plays_pg_std", "new_hc", "new_pc", "vac_tgt", "vac_car", "draft_pick", "exp", "age", "jm", "rookie", "yr2",
             "implied", "yprr_man", "yprr_zone", "ol_pb_full", "ol_rb_full", "ol_pb_now", "ol_rb_now"]
    extra = {"evidence minus prior (pts)": X["ppg"] - X["prior"], "ADP (log)": np.log(np.where(np.isnan(adp), 300, adp)), "games played": g.astype(float), "week": wk.astype(float)}
    rows = []
    for ps in POS4:
        mp = ok & (pos == ps)
        for f_, v in [(f_, colv(f_)) for f_ in feats] + list(extra.items()):
            m = mp & ~np.isnan(v)
            if m.sum() < 400 or np.nanstd(v[m]) < 1e-9: continue
            r = np.corrcoef(v[m], res[m])[0, 1]
            ys = [np.corrcoef(v[m & (year == y)], res[m & (year == y)])[0, 1] for y in YEARS if (m & (year == y)).sum() >= 40 and np.nanstd(v[m & (year == y)]) > 1e-9]
            side = sum(1 for q in ys if np.sign(q) == np.sign(r))
            rows.append((abs(r), ps, f_, r, side, len(ys), int(m.sum())))
    for ps in POS4:
        P(f"  {ps}:")
        for a_, ps_, f_, r, side, ny, nn in sorted([x for x in rows if x[1] == ps], reverse=True)[:10]:
            P(f"    {f_:28s} r {r:+.3f}  seasons same sign {side}/{ny}  n {nn}")
    P("\n  segments (actual / projected rest of season, after the picks):")
    def seg(lab, m):
        m = m & ok
        if m.sum() < 60: return
        ys = [T[m & (year == y)].sum() / S5[m & (year == y)].sum() for y in YEARS if (m & (year == y)).sum() >= 10]
        r_ = T[m].sum() / S5[m].sum(); side = sum(1 for q in ys if (q > 1) == (r_ > 1))
        P(f"    {lab:44s} n {int(m.sum()):5d}  {r_:.3f}  ({side}/{len(ys)} seasons)")
    tc = colv("team_change") == 1
    for ps in POS4:
        mp = pos == ps
        seg(f"{ps}: all", mp); seg(f"{ps}: rookies", mp & rk); seg(f"{ps}: second year", mp & y2)
        seg(f"{ps}: age 30+", mp & (age >= 30)); seg(f"{ps}: changed teams (off-season)", mp & tc)
        seg(f"{ps}: scoring 25%+ over his prior", mp & (X["ppg"] >= 1.25 * X["prior"])); seg(f"{ps}: scoring 25%+ under his prior", mp & (X["ppg"] <= 0.75 * X["prior"]))
        seg(f"{ps}: ADP 1-60", mp & (adp <= 60)); seg(f"{ps}: ADP 61-150", mp & (adp > 60) & (adp <= 150)); seg(f"{ps}: ADP 151+ / none", mp & ~(adp <= 150))

    # ---------------- 6 weakness map ----------------
    # The model AS WIRED (v2.26: RB snap trend carried, QB mover x.84, TE snap level e .3, TE pass-rate tilt e .04), by type of
    # player: level (actual / projected), size of the typical miss, and whether the Clay blend is closer / orders them better.
    P(); P("--- 6  WEAKNESS MAP, model as wired (Jack: 'what is our current weakness what type of player') ---")
    W = SH.copy()
    W = np.where(pos == "RB", W * sm, W)
    W = np.where((pos == "QB") & X["mover"], W * 0.84, W)
    W = np.where((pos == "TE") & ~np.isnan(l1), W * np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4), W)
    W = np.where(pos == "TE", W * (1 - 0.04 * zp), W)
    strb = F["strb"]; tsh, csh, xo, imp, qbo = colv("tgt_sh"), colv("car_sh"), colv("pts_over_xfp"), colv("implied"), colv("qb_out") == 1
    out_rows = []
    def wk_(lab, m):
        m = m & ok
        if m.sum() < 120: return
        ys = [T[m & (year == y)].sum() / W[m & (year == y)].sum() for y in YEARS if (m & (year == y)).sum() >= 12]
        b = T[m].sum() / W[m].sum(); side = sum(1 for q in ys if (q > 1) == (b > 1))
        wins = sum(1 for y in YEARS if (m & (year == y)).sum() >= 12 and ms(W, m & (year == y)) < ms(CL, m & (year == y))); ny = len(ys)
        rel = np.sqrt(ms(W, m)) / max(1e-9, T[m].mean())
        out_rows.append((lab, int(m.sum()), b, side, ny, rel, 100 * (ms(W, m) / ms(CL, m) - 1), wins, rho(W, m), rho(CL, m)))
    for ps in POS4:
        mp = pos == ps
        wk_(f"{ps}: all", mp)
        for lab, lo_, hi_ in (("ADP 1-30", 1, 30), ("ADP 31-60", 31, 60), ("ADP 61-100", 61, 100), ("ADP 101-150", 101, 150)): wk_(f"{ps}: {lab}", mp & (adp >= lo_) & (adp <= hi_))
        wk_(f"{ps}: ADP 151+ / undrafted", mp & ~(adp <= 150))
        wk_(f"{ps}: rookies", mp & rk); wk_(f"{ps}: second year", mp & y2); wk_(f"{ps}: age 30+", mp & (age >= 30)); wk_(f"{ps}: changed teams in the off-season", mp & tc)
        wk_(f"{ps}: scoring 25%+ over his preseason level", mp & (X["ppg"] >= 1.25 * X["prior"])); wk_(f"{ps}: scoring 25%+ under his preseason level", mp & (X["ppg"] <= 0.75 * X["prior"]))
        wk_(f"{ps}: scoring 2+ a game over his usage", mp & (xo >= 2)); wk_(f"{ps}: scoring 2+ a game under his usage", mp & (xo <= -2))
        wk_(f"{ps}: team implied under 19", mp & (imp < 19)); wk_(f"{ps}: team implied 25+", mp & (imp >= 25))
        if ps != "QB":
            wk_(f"{ps}: listed first string", mp & (strb == 1)); wk_(f"{ps}: listed second string or lower", mp & (strb >= 2)); wk_(f"{ps}: starting quarterback out that week", mp & qbo)
    R = pos == "RB"
    wk_("RB: committee (under 40% of carries)", R & (csh < 0.40)); wk_("RB: workhorse (65%+ of carries)", R & (csh >= 0.65)); wk_("RB: pass-catching (12%+ of targets)", R & (tsh >= 0.12)); wk_("RB: no passing role (under 5% of targets)", R & (tsh < 0.05))
    Wm = pos == "WR"
    wk_("WR: alpha (27%+ of targets)", Wm & (tsh >= 0.27)); wk_("WR: 18-27% of targets", Wm & (tsh >= 0.18) & (tsh < 0.27)); wk_("WR: under 12% of targets", Wm & (tsh < 0.12))
    Tm = pos == "TE"
    wk_("TE: 18%+ of targets", Tm & (tsh >= 0.18)); wk_("TE: under 10% of targets", Tm & (tsh < 0.10)); wk_("TE: under 60% of snaps", Tm & (l1 < 60))
    hdr = f"    {'type of player':46s} {'n':>5s}  act/proj (seasons)  miss as % of avg  error vs Clay blend (seasons better)  rank order ours / Clay"
    def show(title, rows_):
        P(); P(f"  {title}"); P(hdr)
        for lab, nn, b, side, ny, rel, vs, wins, r1, r2 in rows_:
            P(f"    {lab:46s} {nn:5d}  {b:.3f} ({side}/{ny})        {100*rel:5.1f}%            {vs:+6.2f}% ({wins}/{ny})                    {r1:.3f} / {r2:.3f}")
    show("A  most over- or under-projected (level off by 4%+ and the same side in 5+ seasons)", sorted([r for r in out_rows if abs(r[2] - 1) >= 0.04 and r[3] >= 5], key=lambda r: -abs(r[2] - 1)))
    show("B  where the Clay blend is closer than we are, or orders them better", sorted([r for r in out_rows if r[6] > 0 or (r[9] - r[8]) > 0.02], key=lambda r: -(r[9] - r[8])))
    show("C  hardest to project (largest miss relative to what they score), top 12", sorted(out_rows, key=lambda r: -r[5])[:12])
    show("D  every type", out_rows)

    # ---------------- 7 structural ----------------
    # Jack 2026-10-02 "lets do it": the weakness map says Clay is still closer on late-round receivers, hot running backs and
    # second-year quarterbacks. Structural tries on top of the model as wired: how fast the season is believed by draft slot and
    # by hot / cold start, what a late-round receiver's number is built from, the second-year quarterback prior, small-role backs.
    P(); P("--- 7  STRUCTURAL (on top of the model as wired; judged on the rows touched, stacked in order) ---")
    Wmult = np.where(SH > 0, W / np.where(SH > 0, SH, 1.0), 1.0)
    st = dict(pmul=np.ones(n), lam=bl.copy(), prior=X["prior"].copy(), mult=Wmult.copy())
    def build(pmul=None, lam=None, prior=None, mult=None):
        pm_ = st["pmul"] if pmul is None else pmul; lm = st["lam"] if lam is None else lam; pr_ = st["prior"] if prior is None else prior; mu_ = st["mult"] if mult is None else mult
        ev = lm * X["xf"] + (1 - lm) * X["ppg_v"]; Pw = X["Pw"] * pm_
        return pred((Pw * pr_ + g * ev) / np.maximum(Pw + g, 1e-9)) * mu_
    def struct(title, key, m, variants):
        fam = {"shipped": build()}
        for lab, ov in variants.items(): fam[lab] = build(**ov)
        okk, b = test(title, fam, m, key)
        if okk: st.update(variants[b])
        return okk
    band = {"ADP 1-60": adp <= 60, "ADP 61-100": (adp > 60) & (adp <= 100), "ADP 101-150": (adp > 100) & (adp <= 150), "ADP 151+": ~(adp <= 150)}
    P(); P("  7a  prior weight by draft slot (x under 1 = believe the season faster)")
    for ps in POS4:
        for bl_, bm in band.items():
            m = (pos == ps) & bm
            if (m & ok).sum() < 150: continue
            struct(f"7a {ps} {bl_}: prior weight", f"P_{ps}_{bl_}", m, {f"x{k}": dict(pmul=np.where(m, st["pmul"] * k, st["pmul"])) for k in (0.25, 0.4, 0.6, 0.8, 1.25, 1.6, 2.5, 4.0)})
    P(); P("  7b  prior weight when the season so far is above (hot) / below (cold) the preseason level")
    for ps in POS4:
        ev = st["lam"] * X["xf"] + (1 - st["lam"]) * X["ppg_v"]; hot = ev > st["prior"]; m = pos == ps; var = {}
        for kh in (0.5, 0.75, 1.0, 1.5, 2.0):
            for kc in (0.5, 0.75, 1.0, 1.5, 2.0):
                if kh == 1.0 and kc == 1.0: continue
                var[f"hot x{kh} / cold x{kc}"] = dict(pmul=np.where(m & hot, st["pmul"] * kh, np.where(m & ~hot, st["pmul"] * kc, st["pmul"])))
        struct(f"7b {ps}: hot / cold prior weight", f"hc_{ps}", m, var)
    P(); P("  7c  late-round receivers (ADP 101+): what the number is built from")
    for bl_ in ("ADP 101-150", "ADP 151+"):
        m = (pos == "WR") & band[bl_]
        struct(f"7c WR {bl_}: usage weight in the evidence", f"wr_late_lam_{bl_}", m, {f"usage weight {l}": dict(lam=np.where(m, l, st["lam"])) for l in (0.0, 0.25, 0.5, 0.75, 1.0)})
        for lab, v in (("target share", tsh), ("season snap share", colv("snap_std")), ("air-yard share", colv("ay_sh"))):
            z = z_of(v, m)
            struct(f"7c WR {bl_}: {lab} tilt", f"wr_late_{lab}_{bl_}", m, {f"e {e}": dict(mult=np.where(m, st["mult"] * np.clip(1 + e * z, 0.75, 1.3), st["mult"])) for e in (0.03, 0.06, 0.10)})
        struct(f"7c WR {bl_}: listed first string", f"wr_late_s1_{bl_}", m & (strb == 1), {f"x{k}": dict(mult=np.where(m & (strb == 1), st["mult"] * k, st["mult"])) for k in (1.04, 1.08, 0.96)})
        struct(f"7c WR {bl_}: listed second string or lower", f"wr_late_s2_{bl_}", m & (strb >= 2), {f"x{k}": dict(mult=np.where(m & (strb >= 2), st["mult"] * k, st["mult"])) for k in (0.92, 0.96, 1.04)})
    P(); P("  7d  quarterbacks")
    q2 = (pos == "QB") & y2; ac = F["adp_curve"]; hasac = ~np.isnan(ac)
    struct("7d second-year QB: prior weight", "qb_yr2_P", q2, {f"x{k}": dict(pmul=np.where(q2, st["pmul"] * k, st["pmul"])) for k in (0.5, 0.75, 1.5, 2.0)})
    struct("7d second-year QB: prior pulled toward the ADP curve", "qb_yr2_adp", q2 & hasac, {f"w {w}": dict(prior=np.where(q2 & hasac, st["prior"] + w * (np.nan_to_num(ac) - st["prior"]), st["prior"])) for w in (0.25, 0.5, 0.75)})
    q36 = (pos == "QB") & band["ADP 1-60"] & (adp > 30)
    struct("7d QB ADP 31-60: level", "qb_3160", q36, {f"x{k}": dict(mult=np.where(q36, st["mult"] * k, st["mult"])) for k in (0.97, 0.94)})
    P(); P("  7e  tight ends ADP 31-60, small-role running backs")
    t36 = (pos == "TE") & (adp > 30) & (adp <= 60)
    struct("7e TE ADP 31-60: level", "te_3160", t36, {f"x{k}": dict(mult=np.where(t36, st["mult"] * k, st["mult"])) for k in (1.05, 1.10, 1.15, 1.20)})
    r2 = (pos == "RB") & (strb >= 2)
    struct("7e RB listed second string or lower: level", "rb_s2", r2, {f"x{k}": dict(mult=np.where(r2, st["mult"] * k, st["mult"])) for k in (1.03, 1.06, 1.09)})
    rc = (pos == "RB") & (csh < 0.40)
    struct("7e RB committee (under 40% of carries): level", "rb_comm", rc, {f"x{k}": dict(mult=np.where(rc, st["mult"] * k, st["mult"])) for k in (1.03, 1.06)})
    S7 = build()
    P(); P("  STACKED after section 7 (vs the model as wired | vs the Clay blend):")
    P(f"  picks: { {k: v for k, v in PICK.items() if k[:2] in ('P_', 'hc', 'wr', 'qb', 'te', 'rb') and (k.startswith('P_') and '_ADP' in k or k.startswith(('hc_', 'wr_late', 'qb_yr2', 'qb_3160', 'te_3160', 'rb_s2', 'rb_comm')))} }")
    segs = [("everyone", np.ones(n, bool)), ("top-150", top150)] + [(ps, pos == ps) for ps in POS4] + [("WR ADP 101-150", (pos == "WR") & band["ADP 101-150"]), ("WR ADP 61-100", (pos == "WR") & band["ADP 61-100"]),
            ("RB 25%+ over preseason level", (pos == "RB") & (X["ppg"] >= 1.25 * X["prior"])), ("RB scoring 2+ over usage", (pos == "RB") & (xo >= 2)), ("second-year QB", q2),
            ("WR 25%+ under preseason level", (pos == "WR") & (X["ppg"] <= 0.75 * X["prior"])), ("RB rookies", (pos == "RB") & rk), ("TE ADP 31-60", t36)]
    for lab, m in segs:
        m = m & ok
        if m.sum() < 100: continue
        w1 = sum(1 for y in YEARS if ms(S7, m & (year == y)) < ms(W, m & (year == y)) - 1e-12); w2 = sum(1 for y in YEARS if ms(S7, m & (year == y)) < ms(CL, m & (year == y)))
        P(f"    {lab:30s} n {int(m.sum()):5d}  {100*(ms(S7, m)/ms(W, m)-1):+6.2f}% ({w1}/{NY}) | {100*(ms(S7, m)/ms(CL, m)-1):+6.2f}% ({w2}/{NY}; was {100*(ms(W, m)/ms(CL, m)-1):+6.2f}%)  | act/proj {T[m].sum()/S7[m].sum():.3f} (was {T[m].sum()/W[m].sum():.3f})"
          f"  | rank order {rho(S7, m):.3f} (was {rho(W, m):.3f}, Clay blend {rho(CL, m):.3f})")

    # ---------------- 8 inside the weak spots ----------------
    # Jack 2026-10-02 "can we continue looking into our weaknesses". Model as wired through v2.27 (fixed settings). Inside each
    # weak type of player: what the rest-of-season miss lines up with, and what lines up with the Clay blend being closer.
    P(); P("--- 8  INSIDE THE WEAK SPOTS (model as wired through v2.27) ---")
    wired = dict(pmul=np.where((pos == "RB") & band["ADP 61-100"], 2.5, np.where((pos == "WR") & band["ADP 61-100"], 0.6, np.where((pos == "QB") & y2, 0.75, 1.0))),
                 lam=np.where((pos == "WR") & band["ADP 101-150"], np.minimum(bl, 0.25), bl), prior=X["prior"].copy(), mult=np.where(t36, Wmult * 1.10, Wmult))
    M = build(**wired); miss = T - M; cedge = np.abs(M - T) - np.abs(CL - T)   # cedge > 0 = the Clay blend was closer
    F8 = {f_: colv(f_) for f_ in feats + ["inherit_tgt", "inherit_car", "vac_tgt_same", "vac_car_same", "qb_out", "rep_q", "prac_dnp", "prac_lim", "opp_implied", "spread", "pc_proe", "pc_rb1_car", "pc_rb_tgt", "pc_te_tgt"]}
    F8.update(extra); F8.update({"depth string": strb, "preseason level (prior)": X["prior"], "season so far / preseason level": X["ppg"] / np.maximum(X["prior"], 1.0), "Clay blend minus ours": CL - M,
                                 "points minus usage evidence": X["ppg_v"] - X["xf"]})
    SEG8 = [("RB running 25%+ over preseason level", (pos == "RB") & (X["ppg"] >= 1.25 * X["prior"])), ("RB rookies", (pos == "RB") & rk), ("RB listed second string or lower", (pos == "RB") & (strb >= 2)),
            ("RB all", pos == "RB"), ("second-year QB", (pos == "QB") & y2), ("QB all", pos == "QB"), ("WR running 25%+ under preseason level", (pos == "WR") & (X["ppg"] <= 0.75 * X["prior"])),
            ("WR ADP 101-150", (pos == "WR") & band["ADP 101-150"]), ("WR all", pos == "WR"), ("TE all", pos == "TE"), ("TE ADP 61-150", (pos == "TE") & (adp > 60) & (adp <= 150))]
    for lab, m in SEG8:
        m = m & ok
        if m.sum() < 150: continue
        wins = sum(1 for y in YEARS if (m & (year == y)).sum() >= 12 and ms(M, m & (year == y)) < ms(CL, m & (year == y)))
        P(); P(f"  {lab}: n {int(m.sum())}, actual / projected {T[m].sum()/M[m].sum():.3f}, error vs Clay blend {100*(ms(M, m)/ms(CL, m)-1):+.2f}% (better {wins}/{NY}), rank order {rho(M, m):.3f} vs {rho(CL, m):.3f}")
        for what, tgt in (("the miss (+ = scored more than projected)", miss), ("the Clay blend being closer", cedge)):
            out = []
            for f_, v in F8.items():
                mm = m & ~np.isnan(v)
                if mm.sum() < 120 or np.nanstd(v[mm]) < 1e-9: continue
                r = np.corrcoef(v[mm], tgt[mm])[0, 1]
                ys = [np.corrcoef(v[mm & (year == y)], tgt[mm & (year == y)])[0, 1] for y in YEARS if (mm & (year == y)).sum() >= 25 and np.nanstd(v[mm & (year == y)]) > 1e-9]
                out.append((abs(r), f_, r, sum(1 for q in ys if np.sign(q) == np.sign(r)), len(ys)))
            P(f"    lines up with {what}: " + "; ".join(f"{f_} {r:+.2f} ({a}/{b_})" for _, f_, r, a, b_ in sorted(out, reverse=True)[:9]))

    # ---------------- 9 leads from inside the weak spots ----------------
    P(); P("--- 9  LEADS FROM SECTION 8, tested on top of the model as wired through v2.27 ---")
    st.update({k: v.copy() for k, v in wired.items()})
    tilt = lambda m, z, e, lo=0.8, hi=1.25: np.where(m, st["mult"] * np.clip(1 + e * z, lo, hi), st["mult"])
    lvl = lambda m, k: np.where(m, st["mult"] * k, st["mult"])
    RBm, WRm, TEm, QBm = pos == "RB", pos == "WR", pos == "TE", pos == "QB"
    jm, pick, pcr, pct, ppl = colv("jm"), colv("draft_pick"), colv("pc_rb1_car"), colv("pc_te_tgt"), colv("plays_pg_std")
    hotR = RBm & (X["ppg"] >= 1.25 * X["prior"]); coldW = WRm & (X["ppg"] <= 0.75 * X["prior"])
    P(); P("  9a  running backs: talent grade (JM), draft capital, coach's lead-back history, team play volume")
    zj = z_of(jm, RBm); struct("9a RB: JM talent-grade tilt", "rb_jm", RBm & ~np.isnan(jm), {f"e {e}": dict(mult=tilt(RBm & ~np.isnan(jm), zj, e)) for e in (0.02, 0.04, 0.06, 0.09)})
    zjr = z_of(jm, RBm & rk); struct("9a RB rookies: JM tilt", "rb_rk_jm", RBm & rk & ~np.isnan(jm), {f"e {e}": dict(mult=tilt(RBm & rk & ~np.isnan(jm), zjr, e)) for e in (0.04, 0.08, 0.12)})
    for lab, cut in (("top-40 pick", 40), ("top-75 pick", 75)):
        m = RBm & rk & (pick <= cut); struct(f"9a RB rookies, {lab}: level", f"rb_rk_{cut}", m, {f"x{k}": dict(mult=lvl(m, k)) for k in (1.05, 1.10, 1.15, 1.20)})
    m = RBm & (strb >= 2) & (adp <= 150); struct("9a RB backups drafted in the top 150: level", "rb_bk150", m, {f"x{k}": dict(mult=lvl(m, k)) for k in (1.04, 1.08, 1.12)})
    zc = z_of(pcr, RBm); struct("9a RB: coach's lead-back carry history tilt", "rb_pc", RBm & ~np.isnan(pcr), {f"e {e}": dict(mult=tilt(RBm & ~np.isnan(pcr), zc, e)) for e in (0.02, 0.04, 0.06)})
    zch = z_of(pcr, hotR); struct("9a RB running hot: coach's lead-back carry history tilt", "rb_hot_pc", hotR & ~np.isnan(pcr), {f"e {e}": dict(mult=tilt(hotR & ~np.isnan(pcr), zch, e)) for e in (0.03, 0.06, 0.09)})
    zpl = z_of(ppl, RBm); struct("9a RB: team plays-per-game tilt (high-volume offenses come down)", "rb_plays", RBm & ~np.isnan(ppl), {f"e {e}": dict(mult=tilt(RBm & ~np.isnan(ppl), -zpl, e)) for e in (0.02, 0.04, 0.06)})
    zxo = z_of(xo, hotR); struct("9a RB running hot: scoring over usage tilt", "rb_hot_eff", hotR & ~np.isnan(xo), {f"e {e}": dict(mult=tilt(hotR & ~np.isnan(xo), zxo, e)) for e in (0.03, 0.06)})
    P(); P("  9b  receivers who started cold")
    for cut in (50, 65):
        m = coldW & (l1 < cut); struct(f"9b WR cold and under {cut}% of snaps last game: level", f"wr_cold_snap{cut}", m, {f"x{k}": dict(mult=lvl(m, k)) for k in (0.92, 0.85, 0.78)})
    struct("9b WR cold: snap trend carried", "wr_cold_trend", coldW, {f"strength {e}": dict(mult=np.where(coldW, st["mult"] * np.power(sm, e), st["mult"])) for e in (0.5, 1.0)})
    for bl_ in ("ADP 101-150", "ADP 151+"):
        ev = st["lam"] * X["xf"] + (1 - st["lam"]) * X["ppg_v"]; m = WRm & band[bl_] & (ev < st["prior"])
        struct(f"9b WR {bl_} below his preseason level: prior weight", f"wr_late_cold_{bl_}", m, {f"x{k}": dict(pmul=np.where(m, st["pmul"] * k, st["pmul"])) for k in (0.25, 0.4, 0.6, 0.8)})
    P(); P("  9c  tight ends: coach's tight-end target history, run-blocking line, scoring over usage")
    zt = z_of(pct, TEm); struct("9c TE: coach's tight-end target history tilt", "te_pc", TEm & ~np.isnan(pct), {f"e {e}": dict(mult=tilt(TEm & ~np.isnan(pct), zt, e)) for e in (0.02, 0.04, 0.06)})
    olr = colv("ol_rb_now"); zo = z_of(olr, TEm); struct("9c TE: run-blocking line tilt (good run lines' tight ends come down)", "te_olrb", TEm & ~np.isnan(olr), {f"e {e}": dict(mult=tilt(TEm & ~np.isnan(olr), -zo, e)) for e in (0.02, 0.04, 0.06)})
    zte = z_of(xo, TEm); struct("9c TE: scoring over usage comes back", "te_eff", TEm & ~np.isnan(xo), {f"e {e}": dict(mult=tilt(TEm & ~np.isnan(xo), -zte, e)) for e in (0.02, 0.04, 0.06)})
    P(); P("  9d  quarterbacks: talent grade (JM)")
    zq = z_of(jm, QBm); struct("9d QB: JM talent-grade tilt", "qb_jm", QBm & ~np.isnan(jm), {f"e {e}": dict(mult=tilt(QBm & ~np.isnan(jm), zq, e, 0.9, 1.12)) for e in (0.01, 0.02, 0.04)})
    S9 = build()
    P(); P("  STACKED after section 9, fold-picked settings (vs wired through v2.27 | vs the Clay blend):")
    for lab, m in [("everyone", np.ones(n, bool)), ("top-150", top150)] + [(ps, pos == ps) for ps in POS4] + [("RB running hot", hotR), ("RB rookies", RBm & rk), ("WR cold", coldW), ("WR ADP 101-150", WRm & band["ADP 101-150"])]:
        m = m & ok
        w1 = sum(1 for y in YEARS if ms(S9, m & (year == y)) < ms(M, m & (year == y)) - 1e-12); w2 = sum(1 for y in YEARS if ms(S9, m & (year == y)) < ms(CL, m & (year == y)))
        P(f"    {lab:18s} n {int(m.sum()):5d}  {100*(ms(S9, m)/ms(M, m)-1):+6.2f}% ({w1}/{NY}) | {100*(ms(S9, m)/ms(CL, m)-1):+6.2f}% ({w2}/{NY}; was {100*(ms(M, m)/ms(CL, m)-1):+6.2f}%)  | act/proj {T[m].sum()/S9[m].sum():.3f} (was {T[m].sum()/M[m].sum():.3f})  | rank order {rho(S9, m):.3f} (was {rho(M, m):.3f}, Clay blend {rho(CL, m):.3f})")

    # ---------------- 10 ablation ----------------
    # Jack 2026-10-02 "take out anything that overall hurts the backtest". The model as wired (through v2.28), one piece removed at
    # a time, graded on the WHOLE board: all rows, top-150 importance-weighted, rank order. Negative = the piece helps.
    P(); P("--- 10  ABLATION: each wired piece removed, whole-board effect of HAVING it (negative = it helps) ---")
    zpl10 = z_of(colv("plays_pg_std"), pos == "RB")
    def full(off=()):
        on = lambda k: k not in off
        lam_ = np.zeros(n) if not on("usage evidence (all positions)") else bl.copy()
        if on("WR 101-150 usage cap .25"): lam_ = np.where((pos == "WR") & band["ADP 101-150"], np.minimum(lam_, 0.25), lam_)
        pts = X["ppg_v"] if on("Vegas-cleaned evidence") else X["ppg"]
        ev = lam_ * X["xf"] + (1 - lam_) * pts
        pr_ = X["prior"] if on("ridge season prior mix") else F["prior"]
        pm_ = np.ones(n)
        if on("RB 61-100 prior weight x2.5"): pm_ = np.where((pos == "RB") & band["ADP 61-100"], 2.5, pm_)
        if on("WR 61-100 prior weight x0.6"): pm_ = np.where((pos == "WR") & band["ADP 61-100"], 0.6, pm_)
        if on("second-year QB prior weight x0.75"): pm_ = np.where((pos == "QB") & y2, 0.75, pm_)
        if on("WR 101-150 cold prior weight x0.4"): pm_ = np.where((pos == "WR") & band["ADP 101-150"] & (ev < pr_), pm_ * 0.4, pm_)
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
    PIECES = ["usage evidence (all positions)", "Vegas-cleaned evidence", "ridge season prior mix", "RB snap trend carried", "QB changed teams x.84", "TE snap-share level e .3", "TE team pass-rate tilt e .04",
              "RB 61-100 prior weight x2.5", "WR 61-100 prior weight x0.6", "second-year QB prior weight x0.75", "WR 101-150 usage cap .25", "TE 31-60 x1.10", "WR 101-150 cold prior weight x0.4",
              "RB team play-volume tilt e .04", "RB backup (top 150) x1.04"]
    FULL = full(); t150 = ok & top150
    P(f"  full model: all rows vs Clay blend {100*(ms(FULL, ok)/ms(CL, ok)-1):+.2f}%, top-150 weighted {100*(wm(FULL, t150)/wm(CL, t150)-1):+.2f}%, rank order {rho(FULL, t150):.4f} (Clay blend {rho(CL, t150):.4f})")
    P(f"    {'piece':38s} rows  | all rows (seasons it helps) | top-150 weighted (seasons) | rank order | verdict")
    for k in PIECES:
        WO = full((k,)); touched = np.abs(WO - FULL) > 1e-9
        a = 100 * (ms(FULL, ok) / ms(WO, ok) - 1); b = 100 * (wm(FULL, t150) / wm(WO, t150) - 1); r = rho(FULL, t150) - rho(WO, t150)
        sa = sum(1 for y in YEARS if ms(FULL, ok & (year == y)) < ms(WO, ok & (year == y)) - 1e-12); sb_ = sum(1 for y in YEARS if wm(FULL, t150 & (year == y)) < wm(WO, t150 & (year == y)) - 1e-12)
        tt = ok & touched; tr = 100 * (ms(FULL, tt) / ms(WO, tt) - 1) if tt.any() else 0.0
        bad = (a > 0) + (b > 0) + (r < 0)
        P(f"    {k:38s} {int(tt.sum()):5d} | {a:+6.2f}% ({sa}/{NY})            | {b:+6.2f}% ({sb_}/{NY})            | {r:+.4f}    | {'HURTS' if bad >= 2 else 'mixed' if bad == 1 else 'helps'}   (its own rows {tr:+.2f}%)")

    # ---------------- 12 THE SEASON BLEND (Jack 2026-10-08: "what else can we test to get rid of the season blend") ----------------
    # The live later-week number is w x shadow + (1 - w) x Clay form per position (QB .5 / RB .8 / WR .7 / TE 0), weights fit on
    # the NEXT GAME. Here the full rest-of-season shadow (as wired through v2.28) is blended with the Clay blend at this horizon:
    # does any weight beat the shadow alone (w 1) out of sample? Picked LOYO + forward per position; rank order beside it.
    P(); P("--- 12  SEASON BLEND: w x full shadow + (1 - w) x Clay blend, rest of season, per position (w 1 = shadow alone) ---")
    WG12 = (0.0, 0.3, 0.5, 0.7, 0.8, 0.9, 1.0); WIRED12 = {"QB": 0.5, "RB": 0.8, "WR": 0.7, "TE": 0.0}
    bl12 = lambda w: w * FULL + (1 - w) * CL
    bw12 = np.array([WIRED12[p_] for p_ in pos]); WB12 = bw12 * FULL + (1 - bw12) * CL
    for lab12, m12 in (("all rows", ok), ("top 150", t150)):
        P(f"  {lab12}: " + " | ".join(f"w {w:.1f}: {100*(wm(bl12(w), m12)/wm(FULL, m12)-1):+.2f}% ({sum(1 for y in YEARS if wm(bl12(w), m12 & (year == y)) < wm(FULL, m12 & (year == y)) - 1e-12)}/{NY}) rho {rho(bl12(w), m12):.4f}" for w in WG12 if w != 1.0) + f" | shadow alone rho {rho(FULL, m12):.4f} | wired weights {100*(wm(WB12, m12)/wm(FULL, m12)-1):+.2f}% rho {rho(WB12, m12):.4f}")
    for ps in POS4:
        m12 = t150 & (pos == ps); best = min(WG12, key=lambda w: wm(bl12(w), m12))
        P(f"  {ps} (n{int(m12.sum())}): best fixed w {best:.1f} ({100*(wm(bl12(best), m12)/wm(FULL, m12)-1):+.2f}% vs shadow alone) | wired w {WIRED12[ps]:.1f}: {100*(wm(bl12(WIRED12[ps]), m12)/wm(FULL, m12)-1):+.2f}% ({sum(1 for y in YEARS if wm(bl12(WIRED12[ps]), m12 & (year == y)) < wm(FULL, m12 & (year == y)) - 1e-12)}/{NY}) | Clay blend alone {100*(wm(CL, m12)/wm(FULL, m12)-1):+.2f}% | rank shadow {rho(FULL, m12):.4f} wired {rho(WB12, m12):.4f} Clay {rho(CL, m12):.4f}")
    LOSO12 = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW12 = [([y for y in YEARS if y < t], t) for t in FWD]
    for flab, folds in (("LOYO", LOSO12), ("forward", FORW12)):
        out = FULL.copy(); picks = {ps: [] for ps in POS4}
        for tr, te in folds:
            for ps in POS4:
                mm = t150 & (pos == ps) & np.isin(year, tr); w = min(WG12, key=lambda w_: wm(bl12(w_), mm)); picks[ps].append(w); sel = (pos == ps) & (year == te); out[sel] = bl12(w)[sel]
        tem = t150 & np.isin(year, [te for _, te in folds]); wins = sum(1 for _, te in folds if wm(out, tem & (year == te)) < wm(FULL, tem & (year == te)) - 1e-12)
        P(f"  {flab:8s} per-position pick: vs shadow alone {100*(wm(out, tem)/wm(FULL, tem)-1):+.2f}% ({wins}/{len(folds)}), vs wired weights {100*(wm(out, tem)/wm(WB12, tem)-1):+.2f}% | rank {rho(out, tem):.4f} (shadow {rho(FULL, tem):.4f}, wired {rho(WB12, tem):.4f}) | picks " + " | ".join(f"{ps} {picks[ps]}" for ps in POS4))

    # ---------------- 11 are the weights right, player by player? ----------------
    # Jack 2026-10-02: "do we feel like the weights are correct on each player". The weight in question is how much of the number
    # is this season (games / (prior weight + games)) vs the preseason level. (a) the weight the model uses vs the weight that
    # fits best, by position, stage and experience; (b) prior-weight multipliers by experience group and by stage, tested.
    P(); P("--- 11  WEIGHTS: this season vs the preseason level, model vs best fit (model as wired through v2.28) ---")
    ev_w = wired["lam"] * X["xf"] + (1 - wired["lam"]) * X["ppg_v"]
    w28 = dict(pmul=np.where((pos == "WR") & band["ADP 101-150"] & (ev_w < X["prior"]), wired["pmul"] * 0.4, wired["pmul"]), lam=wired["lam"].copy(), prior=X["prior"].copy(),
               mult=wired["mult"] * np.where(pos == "RB", np.clip(1 - 0.04 * zpl10, 0.8, 1.25), 1.0) * np.where((pos == "RB") & (strb >= 2) & (adp <= 150), 1.04, 1.0))
    st.update({k: v.copy() for k, v in w28.items()})
    expy = colv("exp"); EXPG = [("rookie", expy == 0), ("second year", expy == 1), ("years 3-5", (expy >= 2) & (expy <= 4)), ("6+ years", expy >= 5)]
    STG = [("3-4 games", (g >= 3) & (g <= 4)), ("5-7 games", (g >= 5) & (g <= 7)), ("8-10 games", (g >= 8) & (g <= 10))]
    yrate = T / np.where((ctx > 0) & (st["mult"] > 0), ctx * st["mult"], np.nan)      # the rate the rest of the season implies
    modw = g / (X["Pw"] * st["pmul"] + g)
    def fitw(m):
        m = m & ok & ~np.isnan(yrate) & ~np.isnan(ev_w)
        if m.sum() < 120: return None
        A_ = np.column_stack([st["prior"][m], ev_w[m]]); b = np.linalg.lstsq(A_, yrate[m], rcond=None)[0]
        return int(m.sum()), float(modw[m].mean()), float(b[1] / (b[0] + b[1])), float(b[0] + b[1])
    P(f"    {'group':34s} rows   model's weight on this season   best-fit weight   level (sum of the two fitted weights)")
    for ps in POS4:
        for lab, m in [("all", np.ones(n, bool))] + STG + EXPG + [("ADP 1-60", adp <= 60), ("ADP 61-150", (adp > 60) & (adp <= 150)), ("ADP 151+ / undrafted", ~(adp <= 150))]:
            r_ = fitw((pos == ps) & m)
            if r_: P(f"    {ps + ' ' + lab:34s} {r_[0]:5d}        {100*r_[1]:4.0f}%                      {100*r_[2]:4.0f}%            {r_[3]:.3f}")
    P(); P("  11b  prior-weight multipliers, tested (x under 1 = believe the season faster)")
    GR = (0.4, 0.6, 0.8, 1.25, 1.6, 2.5)
    for ps in POS4:
        for lab, m in EXPG:
            mm = (pos == ps) & m
            if (mm & ok).sum() < 150: continue
            struct(f"11b {ps} {lab}: prior weight", f"w_{ps}_{lab}", mm, {f"x{k}": dict(pmul=np.where(mm, st["pmul"] * k, st["pmul"])) for k in GR})
        for lab, m in STG:
            mm = (pos == ps) & m
            struct(f"11b {ps} after {lab}: prior weight", f"w_{ps}_{lab}", mm, {f"x{k}": dict(pmul=np.where(mm, st["pmul"] * k, st["pmul"])) for k in GR})
    # ---------------- 13 ROOKIE EVIDENCE (Jack 2026-10-08: "run the rookie evidence test and wire it if it passes") ----------------
    # Rookies are the largest season-horizon gap left (RB rookies 1.13 under, WR 1.05; model's weight on the season 48% vs best fit
    # 16% for RB rookies). 11b tried one flat prior-weight multiplier per group (RB x2.5 failed forward). Here, rookie rows only:
    #   13a usage weight in the evidence (flat lam) per position     13b prior weight by STAGE (3-4 games / 5+ games) per position
    #   13c the two together. Graded on the rookie rows with the whole-board guard, LOYO + forward (struct = pass -> stacked into st).
    P(); P("--- 13  ROOKIE EVIDENCE: usage weight and prior weight by stage, rookie rows only (model as wired through section 11) ---")
    rk13 = colv("exp") == 0; early13 = g <= 4
    for ps in POS4:
        m = rk13 & (pos == ps)
        if (m & ok).sum() < 120: P(f"  13 {ps} rookies: too few rows ({int((m & ok).sum())})"); continue
        lgrid = (0.0, 0.25, 0.5, 0.75, 1.0) if ps in ("RB", "WR") else (0.25, 0.5)
        struct(f"13a {ps} rookies: usage weight in the evidence (flat)", f"rk_lam_{ps}", m, {f"lam {l}": dict(lam=np.where(m, l, st["lam"])) for l in lgrid})
        var = {}
        for ke in (1.0, 1.6, 2.5, 4.0):
            for kl in (0.6, 1.0, 1.6, 2.5):
                if ke == 1.0 and kl == 1.0: continue
                var[f"early x{ke} / late x{kl}"] = dict(pmul=np.where(m & early13, st["pmul"] * ke, np.where(m & ~early13, st["pmul"] * kl, st["pmul"])))
        struct(f"13b {ps} rookies: prior weight by stage (3-4 games / 5+)", f"rk_P_{ps}", m, var)
    S13 = build(); t150 = ok & top150
    P(); P("  STACKED after section 13 (vs wired through section 11 | vs the Clay blend):")
    for lab, m in (("ALL rows", ok), ("top 150", t150), ("rookies", ok & rk13), ("RB rookies", ok & rk13 & (pos == "RB")), ("WR rookies", ok & rk13 & (pos == "WR")), ("non-rookies", ok & ~rk13)):
        if m.sum() < 60: continue
        w1 = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and ms(S13, m & (year == y)) < ms(M, m & (year == y)) - 1e-12)
        P(f"    {lab:14s} n {int(m.sum()):5d}  vs wired {100*(ms(S13, m)/ms(M, m)-1):+6.2f}% ({w1}/{NY}) | vs Clay blend {100*(ms(S13, m)/ms(CL, m)-1):+6.2f}% | top-150 wtd {100*(wm(S13, m & top150)/wm(M, m & top150)-1):+6.2f}% | rank order {rho(S13, m & top150):.4f} (wired {rho(M, m & top150):.4f})")

    # ---------------- 14 TIGHT ENDS (Jack 2026-10-08: "run all three and wire what passes") ----------------
    # research_te_bias.py: the shadow's TE under-projection sits in (1) tight ends with a real role and no touchdowns yet,
    # (2) full-snap tight ends (lifts), (3) run-heavy offenses (pass rate over expected low). Three layers on the final model,
    # TE rows, LOYO + forward with the whole-board guard (struct = pass -> stacked into st).
    P(); P("--- 14  TIGHT ENDS: TD floor for role players, snap-level lift strength, run-heavy offense tilt (model as wired through section 13) ---")
    te14 = pos == "TE"; tdp14 = np.full(n, np.nan)
    _logs14 = {}
    for i in np.where(te14 & ok)[0]:
        Y = int(year[i]); k_ = (name[i], Y)
        if k_ not in _logs14:
            rec_ = SN.cal.weekly_rec(name[i], "TE"); _logs14[k_] = {int(w["wk"]): 6 * float(w.get("rctd") or 0) + 6 * float(w.get("rtd") or 0) for w in (rec_ or {}).get("seasons", {}).get(str(Y), []) if SN.cal.played(w) and isinstance(w.get("fpts"), (int, float))}
        past = [v for w, v in _logs14[k_].items() if w < wk[i]]
        if past: tdp14[i] = float(np.mean(past))
    role14 = te14 & ((tsh >= 0.15) | (colv("snap_std") >= 70)); gap14 = np.clip(1.8 - np.nan_to_num(tdp14, nan=1.8), 0, 1.8)
    m1 = role14 & ~np.isnan(tdp14) & (g >= 2)
    struct("14a TE with a role and few touchdowns so far: lift per missing TD point", "te_tdfloor", m1, {f"e {e}": dict(mult=np.where(m1, st["mult"] * (1 + e * gap14), st["mult"])) for e in (0.02, 0.04, 0.06, 0.08)})
    m1b = te14 & ~np.isnan(tdp14) & (g >= 2)
    struct("14a' same, no role gate", "te_tdfloor_all", m1b, {f"e {e}": dict(mult=np.where(m1b, st["mult"] * (1 + e * gap14), st["mult"])) for e in (0.02, 0.04, 0.06)})
    M0 = np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4); m2 = te14 & ~np.isnan(l1)
    var2 = {}
    for kl in (1.0, 1.5, 2.0):
        for kd in (0.5, 1.0):
            if kl == 1.0 and kd == 1.0: continue
            var2[f"lift ^{kl} / dock ^{kd}"] = dict(mult=np.where(m2, st["mult"] * np.where(M0 > 1, np.power(M0, kl), np.power(M0, kd)) / np.where(M0 > 0, M0, 1.0), st["mult"]))
    struct("14b TE snap-share level: lift / dock strength (wired e .3 both ways)", "te_snaplift", m2, var2)
    m3 = te14 & ~np.isnan(zp)
    struct("14c TE run-heavy offense tilt (wired e .04 symmetric): run-heavy side only", "te_runheavy", m3, {f"e {e}": dict(mult=np.where(m3, st["mult"] * (1 + e * np.clip(-zp, 0, 2.5)), st["mult"])) for e in (0.03, 0.06, 0.09, 0.12)})
    struct("14c' TE pass-rate tilt symmetric, stronger (on top of the wired .04)", "te_proe2", m3, {f"e {e}": dict(mult=np.where(m3, st["mult"] * (1 - e * zp), st["mult"])) for e in (0.03, 0.06)})
    S14 = build(); t150 = ok & top150
    P(); P("  STACKED after section 14 (vs wired through section 13 | vs the Clay blend):")
    for lab, m in (("ALL rows", ok), ("top 150", t150), ("TE", ok & te14), ("TE top 150", t150 & te14), ("non-TE", ok & ~te14)):
        w1 = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and ms(S14, m & (year == y)) < ms(S13, m & (year == y)) - 1e-12)
        P(f"    {lab:12s} n {int(m.sum()):5d}  vs section 13 {100*(ms(S14, m)/ms(S13, m)-1):+6.2f}% ({w1}/{NY}) | vs Clay blend {100*(ms(S14, m)/ms(CL, m)-1):+6.2f}% | act/proj {T[m].sum()/S14[m].sum():.3f} (was {T[m].sum()/S13[m].sum():.3f}) | rank order {rho(S14, m & top150):.4f} (was {rho(S13, m & top150):.4f})")

    # =====================================================================================================================
    # 17-19 (Jack 2026-10-20: "nabers and chuba are still too low"). Model as wired through section 14 (S14 / st) is the baseline.
    # 17  INJURY-RETURN RAMP (Nabers type): players who missed most of last season, whose usage jumped after the first games of
    #     this season. Ramp games dropped / down-weighted in the evidence, or recent games weighted up.
    # 18  CHUBA LEAD (16B leftover): flat level x1.03-1.06 for RBs whose carry share is up vs last season, ADP 61-150.
    # 19  HOT + HEAVY USAGE: are hot players with a big role under-projected on history, by position (no prop archive exists).
    # Graded ROS (target T, 4+ games left) as everywhere above AND next game (target act, same checkpoints 3-10 games).
    # =====================================================================================================================
    P(); P("=" * 110); P("--- 17-19  Jack 2026-10-20 (Nabers / Hubbard): baseline = model as wired through section 14 ---")
    okN = (g >= 3) & (g <= 10) & (wk != finw) & (S14 >= 3)        # next-game rows
    lay_n = np.clip(layers, 0.5, 1.8)
    msN = lambda q, m: float(np.mean((q[m] - act[m]) ** 2)) if m.any() else np.nan
    wmN = lambda q, m: float(np.average((q[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    def rhoN(q, m):
        gr = defaultdict(list)
        for i in np.where(m)[0]: gr[(int(year[i]), int(wk[i]), pos[i])].append(i)
        rh = [np.corrcoef(rankdata(act[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]
        return float(np.mean(rh)) if rh else np.nan
    def test_next(title, fam, m_rows):
        """same ship bar as test(), target = the next game (act), rows = okN"""
        names = list(fam); b = fam[names[0]]; touched = np.zeros(n, bool)
        for k_ in names[1:]: touched |= np.abs(fam[k_] - b) > 1e-9
        tm = m_rows & okN & touched
        if tm.sum() < 20: P(f"  [next game] {title}: too few rows ({int(tm.sum())})"); return False, names[0]
        pick = lambda yrs: min(names, key=lambda k: msN(fam[k], tm & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = b.copy()
            for tr, te in folds:
                k = pick(tr); picks.append(k); m = year == te; pr[m] = fam[k][m]; wins += msN(fam[k], tm & m) < msN(b, tm & m) - 1e-12
            tem = np.isin(year, [te for _, te in folds])
            return pr, 100 * (msN(pr, tm & tem) / msN(b, tm & tem) - 1), 100 * (wmN(pr, tm & tem & top150) / wmN(b, tm & tem & top150) - 1), wins, picks
        lo = run([([y for y in YEARS if y != t], t) for t in YEARS]); fw = run([([y for y in YEARS if y < t], t) for t in FWD])
        best = pick(YEARS)
        okk = best != names[0] and lo[1] < -0.3 and lo[3] >= 5 and fw[1] < 0 and fw[3] >= 3 and lo[2] <= 0.1
        sb = lambda k: sum(1 for y in YEARS if (tm & (year == y)).sum() >= 8 and msN(fam[k], tm & (year == y)) < msN(b, tm & (year == y)) - 1e-12)
        P(f"  [next game] {title}   (rows {int(tm.sum()):,}, act/proj {act[tm].sum()/b[tm].sum():.3f})")
        P("    pooled: " + "  ".join(f"{k}: {100*(msN(fam[k], tm)/msN(b, tm)-1):+.2f}% ({sb(k)})" for k in names[1:]))
        P(f"    LOYO {lo[1]:+.2f}% {lo[3]}/7 | top-150 wtd {lo[2]:+.2f}% rank {rhoN(lo[0], tm & top150) - rhoN(b, tm & top150):+.4f} | picks {lo[4]}")
        P(f"    FWD  {fw[1]:+.2f}% {fw[3]}/4 | top-150 wtd {fw[2]:+.2f}% | picks {fw[4]}")
        P(f"    -> {'PASS: ' + str(best) if okk else 'FAIL (best pooled: ' + str(best) + ')'}")
        return okk, best
    def rate_of(pmul=None, lam=None, prior=None, xf_=None, pv_=None, g_=None):
        pm_ = st["pmul"] if pmul is None else pmul; lm = st["lam"] if lam is None else lam; pr_ = st["prior"] if prior is None else prior
        xf_ = X["xf"] if xf_ is None else xf_; pv_ = X["ppg_v"] if pv_ is None else pv_; g_ = g if g_ is None else g_
        ev = lm * xf_ + (1 - lm) * pv_; Pw = X["Pw"] * pm_
        return (Pw * pr_ + g_ * ev) / np.maximum(Pw + g_, 1e-9)
    R14 = rate_of()
    ros_of = lambda r, mult=None: r * ctx * (st["mult"] if mult is None else mult)
    chk = ok & ~np.isnan(S14)
    # NEXT GAME baseline = the next-game harness form (backtest_shadow_next.shadow: shipped P, shipped usage schedule, its next-game layers incl.
    # the QB-out WR dock) - the ROS-only struct (RB 61-100 x2.5 etc.) is NOT in the engine's current-week number, so it is not in this baseline.
    lamN0 = base_lam(pos, g)
    def rate_n(pm=None, lam=None, xf_=None, pv_=None, g_=None):
        Pw = X["Pw"] * (1.0 if pm is None else pm); lm = lamN0 if lam is None else lam
        xf_ = X["xf"] if xf_ is None else xf_; pv_ = X["ppg_v"] if pv_ is None else pv_; g_ = g if g_ is None else g_
        return (Pw * X["prior"] + g_ * (lm * xf_ + (1 - lm) * pv_)) / np.maximum(Pw + g_, 1e-9)
    Rn0 = rate_n(); N14 = SN.shadow(X); nratio = np.where(Rn0 > 0, N14 / np.where(Rn0 > 0, Rn0, 1.0), 1.0)
    okN &= N14 >= 3
    P(f"  baseline check: rebuilt ROS == S14 on {int((np.abs(ros_of(R14) - S14) < 1e-6)[chk].sum())}/{int(chk.sum())} rows | ROS act/proj {T[ok].sum()/S14[ok].sum():.3f} | next-game rows {int(okN.sum())} act/proj {act[okN].sum()/N14[okN].sum():.3f} (next-game harness shadow form)")
    def both(title, m, variants, ros_only=False):
        """variants: {label: spec}; spec keys (all optional): pm = prior-weight multiplier array, k = level multiplier array,
        ev = (fl, xf_, pv_, g_) replacement evidence on flagged rows. ROS: on top of the wired ROS model (st); next game: on top of the
        next-game harness shadow. Ship bar as test()."""
        famR = {"wired": S14}; famN = {"wired": N14}
        for lab, sp in variants.items():
            pm = sp.get("pm"); k = sp.get("k", 1.0); ev = sp.get("ev")
            if ev is not None:
                fl, xf_, pv_, g_ = ev
                rR = rate_of(pmul=None if pm is None else st["pmul"] * pm, lam=np.where(fl, lam_for(g_), st["lam"]), xf_=xf_, pv_=pv_, g_=g_)
                rN = rate_n(pm=pm, lam=np.where(fl, base_lam(pos, g_), lamN0), xf_=xf_, pv_=pv_, g_=g_)
            else:
                rR = rate_of(pmul=None if pm is None else st["pmul"] * pm); rN = rate_n(pm=pm)
            famR[lab] = ros_of(rR) * k; famN[lab] = rN * nratio * k
        okR, bR = test(title + " [ROS]", famR, m)
        okX, bX = (False, None) if ros_only else test_next(title, famN, m)
        return okR, bR, okX, bX

    # ---------------- per-game logs from the harness rows: points, Vegas scale, xFP, snap share ----------------
    xfr = colv("xfp_pg"); snl1 = colv("snap_l1"); vegc = colv("veg")
    gp_py = colv("g_py"); expc = colv("exp")
    seqA = defaultdict(list)
    for i in range(n): seqA[(name[i], pos[i], int(year[i]))].append(i)
    gl = {}
    bad_inc = 0
    for k_, ix in seqA.items():
        ix.sort(key=lambda i: wk[i]); out = []
        for a, i in enumerate(ix):
            nxt = ix[a + 1] if a + 1 < len(ix) else None
            xg = np.nan; sn = np.nan
            if nxt is not None:
                if g[nxt] - g[i] == 1:
                    prevx = (xfr[i] * g[i]) if g[i] > 0 else 0.0
                    if not np.isnan(xfr[nxt]) and not np.isnan(prevx): xg = xfr[nxt] * g[nxt] - prevx
                    sn = snl1[nxt]
                else: bad_inc += 1
            vv = vegc[i] if not np.isnan(vegc[i]) else layers[i]
            out.append(dict(i=i, wk=int(wk[i]), pts=float(act[i]), veg=float(np.clip(vv, 0.6, 1.6)), xfp=float(xg), snap=float(sn)))
        gl[k_] = out
    P(f"  per-game logs: {len(gl)} player-seasons, {bad_inc} non-consecutive game steps (left alone)")
    def evid_from(games, wts):
        """evidence pieces (xFP/g, Vegas-cleaned points/g, effective games) from a weighted subset of games"""
        w = np.asarray(wts, float)
        if w.sum() <= 0: return np.nan, np.nan, 0.0
        pts = np.array([q["pts"] for q in games]); vg = np.array([q["veg"] for q in games]); xg = np.array([q["xfp"] for q in games])
        ppg_ = float(np.sum(w * pts) / w.sum()); raw = float(np.sum(w * pts)); tot = float(np.sum(w * pts / vg))
        pv = ppg_ * float(np.clip(tot / raw, 0.75, 1.35)) if raw > 0 else ppg_
        xf_ = float(np.sum(w * xg) / w.sum()) if not np.any(np.isnan(xg[w > 0])) else np.nan
        return xf_, pv, float(w.sum())
    prev_games = {}
    recon_ok = np.zeros(n, bool)
    for k_, games in gl.items():
        for a, q in enumerate(games):
            i = q["i"]; pg_ = games[:a]
            prev_games[i] = pg_
            if not (ok[i] or okN[i]) or len(pg_) != g[i] or len(pg_) == 0: continue
            xf_, pv, ge = evid_from(pg_, np.ones(len(pg_)))
            if not np.isnan(xf_) and abs(xf_ - X["xf"][i]) < 0.15 and abs(pv - X["ppg_v"][i]) < 0.25: recon_ok[i] = True
    P(f"  evidence rebuilt from per-game logs matches the harness on {int((recon_ok & ok).sum())}/{int(ok.sum())} ROS rows, {int((recon_ok & okN).sum())}/{int(okN.sum())} next-game rows (others left at baseline)")

    # =====================================================================================================================
    # 22-26 MID-SEASON TEAM CHANGES (Jack 2026-10-20, MHJ ARI -> HOU: "his usage was bad in game 1 ... needs to learn the
    # playbook"). Harness patched (research_midseason_trade_patch.py): movers keep every game with the team he played for
    # that week; usage is season-to-date over ALL his games (the engine's SIM_XFP / SIM_SNAPS are player-keyed).
    # Baselines: ROS = S14 (model as wired through section 14). NEXT = next-game harness shadow N14 x the engine's snap
    # level (WR/TE e .3 on the last game, engine bins, top-30 exempt) x the shadow pecking dock (WR 3rd+ x.92, RB 2nd+ x.94,
    # fades 4-5, current week only) - the two role docks Jack asked about; the ROS form already carries the TE snap level
    # (e .3) and the RB snap trend (sm).
    # =====================================================================================================================
    import pickle, math
    from collections import Counter
    P(); P("=" * 110); P("--- 22-26  MID-SEASON TEAM CHANGES (MHJ): baseline = model as wired through section 14 ---")
    MG = pickle.load(open(os.path.join(HERE, "_tmp", "mst", "mover_games_ext.pkl"), "rb"))
    pidA = A["pid"]; teamA = X["team"]; agec = colv("age")
    _sa = defaultdict(list)
    for i in range(n): _sa[(int(year[i]), name[i], pos[i])].append(i)
    seqM = {k: sorted(ix, key=lambda i: wk[i]) for k, ix in _sa.items() if len({teamA[j] for j in ix if teamA[j]}) >= 2}
    is_mv = np.zeros(n, bool)
    for ix in seqM.values(): is_mv[ix] = True
    MI = {k: dict(name=k[1], pos=k[2], age=float(np.nanmean(agec[ix])) if not np.all(np.isnan(agec[ix])) else np.nan) for k, ix in seqM.items()}
    P(f"  mover rows in the harness: {int(is_mv.sum())} ({len(seqM)} player-seasons; by position {dict(sorted(__import__('collections').Counter(k[2] for k in seqM).items()))})")
    nnew = np.full(n, -1); nold = np.zeros(n, int); post = np.zeros(n, bool); gidx = np.zeros(n, int)
    first_new = {}; old_team = {}
    for k_, ix in seqM.items():
        t0 = teamA[ix[0]]
        for a, i in enumerate(ix):
            cur = teamA[i]; prev = ix[:a]
            if cur != t0:
                post[i] = True; nnew[i] = sum(1 for j in prev if teamA[j] == cur); nold[i] = sum(1 for j in prev if teamA[j] != cur); gidx[i] = nnew[i] + 1
                first_new.setdefault(k_, int(wk[i])); old_team[k_] = t0
    def mgw(i):
        v_ = MG.get((int(year[i]), pidA[i]))
        return v_["weeks"].get(int(wk[i]), {}) if v_ else {}
    def share(q, a, b): return 100.0 * q[a] / q[b] if q and q.get(b) else np.nan
    snapG = np.array([mgw(i).get("snap", np.nan) if is_mv[i] else np.nan for i in range(n)])
    routeG = np.array([mgw(i).get("route", np.nan) if is_mv[i] else np.nan for i in range(n)])
    tgtG = np.array([share(mgw(i), "tg", "team_tg") if is_mv[i] else np.nan for i in range(n)])
    carG = np.array([share(mgw(i), "car", "team_car") if is_mv[i] else np.nan for i in range(n)])
    # ---- next-game baseline NB: N14 x snap level x peck ----
    SNL = {"WR": ([4.87, 6.22, 7.4, 8.68, 9.93, 11.23, 12.87], [45.9, 59.7, 67.2, 72.6, 79.8, 83.3, 83.7, 85.0]), "TE": ([3.85, 4.66, 5.4, 6.28, 7.17, 8.04, 9.48], [52.6, 57.7, 64.9, 68.2, 71.7, 74.7, 76.9, 83.8])}
    l1c = colv("snap_l1")
    def snaplv(base, l1v, e=0.3):
        out = np.ones(n)
        for ps, (ed, rf) in SNL.items():
            m = (pos == ps) & ~np.isnan(l1v) & (g >= 1)
            b_ = np.searchsorted(np.array(ed), base, side="right"); ref = np.array(rf)[np.clip(b_, 0, 7)]
            mm = np.clip(1 + e * (l1v - ref) / 100.0, 0.7, 1.4)
            mm = np.where((mm < 1) & (adp <= 30), 1.0, mm)
            out = np.where(m, mm, out)
        return out
    SLV0 = snaplv(N14, l1c)
    def peck_of(v):
        out = np.ones(n); grp = defaultdict(list)
        for i in np.where(((pos == "WR") | (pos == "RB")))[0]: grp[(int(year[i]), int(wk[i]), teamA[i], pos[i])].append(i)
        for k_, ix in grp.items():
            for i in ix:
                rk_ = 1 + sum(1 for j in ix if j != i and v[j] >= 0.5 and v[j] > v[i])
                frm, mlt = (3, 0.92) if pos[i] == "WR" else (2, 0.94)
                if rk_ >= frm:
                    fd = max(0.0, min(1.0, v[i] - 4)); out[i] = 1 - (1 - mlt) * fd
        return out
    PK0 = peck_of(N14 * SLV0)
    deb = post & (nnew == 0)
    DOCK = np.where(deb & ((pos == "RB") | (pos == "WR") | (pos == "TE")), 0.7, 1.0)   # WIRED newTeamDebutMult
    NB0 = N14 * SLV0 * PK0; NB = NB0 * DOCK
    finw2 = np.where(year <= 2020, 17, 18)
    rowsN = is_mv & post & (wk != finw2) & (NB >= 3)            # every post-trade next game (no games-played window)
    rowsR = is_mv & post & ~np.isnan(T) & (S14 >= 3)             # post-trade checkpoints with 4+ games left
    ctrlN = ~is_mv & (g >= 3) & (wk != finw2) & (NB >= 3)
    P(f"  NEXT baseline (N14 x snap level x peck): all non-mover rows g3+ act/proj {act[ctrlN].sum()/NB[ctrlN].sum():.3f} (N14 alone {act[ctrlN].sum()/N14[ctrlN].sum():.3f}); "
      f"post-trade next-game rows {int(rowsN.sum())}, ROS checkpoints {int(rowsR.sum())}")

    # ---------------- 22 descriptive ----------------
    P(); P("--- 22  DESCRIPTIVE: new-team games 1, 2, 3, 4+ (usage per game; points vs the wired projection) ---")
    adp_ps = {}; pre = {}
    for k_, ix in seqM.items():
        old_ix = [i for i in ix if not post[i]]
        pre[k_] = dict(snap=np.nanmean(snapG[old_ix]) if old_ix else np.nan, route=np.nanmean(routeG[old_ix]) if old_ix and not np.all(np.isnan(routeG[old_ix])) else np.nan,
                       tgt=np.nanmean(tgtG[old_ix]) if old_ix else np.nan, car=np.nanmean(carG[old_ix]) if old_ix else np.nan, ppg=float(np.mean(act[old_ix])) if old_ix else np.nan, n=len(old_ix))
        adp_ps[k_] = adp[ix[0]]
    kps = np.array([(int(year[i]), name[i], pos[i]) if is_mv[i] else None for i in range(n)], dtype=object)
    preS = np.array([pre[kps[i]]["snap"] if is_mv[i] else np.nan for i in range(n)])
    def desc(lab, sel):
        P(f"  {lab}")
        P(f"    {'new-team game':14s} {'rows':>4s} {'p-s':>4s} | {'snap%':>6s} {'route%':>6s} {'tgt%':>5s} {'car%':>5s} | snap vs old-team | {'pts':>5s} {'wired next':>10s} {'act/proj':>8s} | ROS from here: {'n':>3s} act/proj (wired ROS)")
        for gl_, gh in ((1, 1), (2, 2), (3, 3), (4, 99)):
            m = sel & post & (gidx >= gl_) & (gidx <= gh)
            if m.sum() == 0: continue
            mn = m & rowsN; mr = m & rowsR
            ps_ = len(set(kps[m]))
            rel = np.nanmean(snapG[m] / np.where(preS[m] > 0, preS[m], np.nan))
            P(f"    {('game ' + str(gl_) + ('+' if gh > 4 else '')):14s} {int(m.sum()):4d} {ps_:4d} | {np.nanmean(snapG[m]):6.1f} {np.nanmean(routeG[m]):6.1f} {np.nanmean(tgtG[m]):5.1f} {np.nanmean(carG[m]):5.1f} | x{rel:5.2f}          | "
              f"{act[mn].mean() if mn.any() else np.nan:5.2f} {NB[mn].mean() if mn.any() else np.nan:10.2f} {(act[mn].sum()/NB[mn].sum()) if mn.any() else np.nan:8.3f} | {int(mr.sum()):3d} {(T[mr].sum()/S14[mr].sum()) if mr.any() else np.nan:.3f}")
        mo = sel & is_mv & ~post
        if mo.any(): P(f"    {'old team':14s} {int(mo.sum()):4d} {len(set(kps[mo])):4d} | {np.nanmean(snapG[mo]):6.1f} {np.nanmean(routeG[mo]):6.1f} {np.nanmean(tgtG[mo]):5.1f} {np.nanmean(carG[mo]):5.1f} |")
    relv = lambda ps_list: np.array([is_mv[i] and pos[i] in ps_list for i in range(n)])
    estab = np.array([is_mv[i] and pre[kps[i]]["snap"] >= 50 for i in range(n)])
    desc("ALL pool movers (QB/RB/WR/TE)", is_mv)
    desc("WR + TE", relv(("WR", "TE")))
    desc("RB", relv(("RB",)))
    desc("established role before the trade (50%+ snaps on the old team), all positions", estab)
    desc("established role, WR/TE", estab & relv(("WR", "TE")))
    desc("ADP 1-150 (drafted)", is_mv & (adp <= 150))
    desc("2012-18 only", is_mv & (year <= 2018))
    desc("2019-25 only", is_mv & (year >= 2019))
    # paired ramp: per player-season with 4+ new-team games, game 1 / game 2 usage vs his new-team games 3+ mean
    P(); P("  paired ramp (player-seasons with 4+ new-team games): game-k usage / his own new-team games 3+ average (median, mean, share under 0.9)")
    for lab, arr in (("snap", snapG), ("route", routeG), ("target share", tgtG)):
        for kk in (1, 2):
            r_ = []
            for k_, ix in seqM.items():
                pi = [i for i in ix if post[i]]
                if len(pi) < 4: continue
                gk = [arr[i] for i in pi if gidx[i] == kk]; g3 = [arr[i] for i in pi if gidx[i] >= 3 and not np.isnan(arr[i])]
                if gk and not np.isnan(gk[0]) and g3 and np.mean(g3) > 0: r_.append(gk[0] / np.mean(g3))
            if r_: P(f"    {lab:12s} game {kk}: n {len(r_):2d}  median {np.median(r_):.2f}  mean {np.mean(r_):.2f}  under .9: {sum(1 for q in r_ if q < 0.9)}/{len(r_)}")
    # event list
    P(); P("  EVENT LIST (pool movers in the harness): year pos name old->new first new wk | old g, old snap%, old ppg | new g: snap% by game | pts by game | wired next by game | ADP | age")
    agei = colv("age")
    for k_ in sorted(seqM, key=lambda k: (k[0], k[2], k[1])):
        ix = seqM[k_]; pi = [i for i in ix if post[i]]
        if not pi: continue
        v = MI[k_]
        P(f"    {k_[0]} {v['pos']} {v['name']:24s} {old_team.get(k_, '?')}->{teamA[pi[0]]} wk{first_new.get(k_, 0):2d} | old g {pre[k_]['n']:2d} snap {pre[k_]['snap']:5.1f} ppg {pre[k_]['ppg']:5.1f} | new g {len(pi):2d}: "
          f"{[int(snapG[i]) if not np.isnan(snapG[i]) else None for i in pi][:6]} | {[round(float(act[i]), 1) for i in pi][:6]} | {[round(float(NB[i]), 1) for i in pi][:6]} | ADP {adp_ps[k_] if not np.isnan(adp_ps[k_]) else '-'} | age {v['age']:.1f}")

    # ---------------- testing machinery for mover rows ----------------
    msT = lambda q, m, tg: float(np.mean((q[m] - tg[m]) ** 2)) if m.any() else np.nan
    maT = lambda q, m, tg: float(np.mean(np.abs(q[m] - tg[m]))) if m.any() else np.nan
    wmT = lambda q, m, tg: float(np.average((q[m] - tg[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    def rho_board(q, base_m, tg, groups_from):
        """within (year, wk, pos) rank order over the WHOLE board (top-150 rows) in the weeks the variant touches"""
        keys = {(int(year[i]), int(wk[i]), pos[i]) for i in np.where(groups_from)[0]}
        gr = defaultdict(list)
        for i in np.where(base_m & top150)[0]:
            kk = (int(year[i]), int(wk[i]), pos[i])
            if kk in keys: gr[kk].append(i)
        rh = [np.corrcoef(rankdata(tg[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in gr.values()) if len(ix) >= 8]
        return float(np.mean(rh)) if rh else np.nan
    RES = {}
    def testM(title, fam, rows, tg, board):
        names = list(fam); b = fam[names[0]]; touched = np.zeros(n, bool)
        for k_ in names[1:]: touched |= np.abs(fam[k_] - b) > 1e-9
        tm = rows & touched & ~np.isnan(tg)
        nps = len(set(kps[tm]))
        if tm.sum() < 10: P(f"  {title}: too few rows ({int(tm.sum())})"); return False, names[0]
        ys = [y for y in YEARS if (tm & (year == y)).sum() >= 3]
        pick = lambda yrs: min(names, key=lambda k: msT(fam[k], tm & np.isin(year, yrs), tg))
        def run(folds):
            wins = ny = 0; picks = []; pr = b.copy()
            for tr, te in folds:
                k = pick(tr); picks.append(k); m = year == te; pr[m] = fam[k][m]
                if te in ys:
                    ny += 1; wins += msT(fam[k], tm & m, tg) < msT(b, tm & m, tg) - 1e-12
            tem = np.isin(year, [te for _, te in folds])
            return pr, 100 * (msT(pr, tm & tem, tg) / msT(b, tm & tem, tg) - 1), 100 * (maT(pr, tm & tem, tg) / maT(b, tm & tem, tg) - 1), wins, ny, picks, \
                   (100 * (wmT(pr, tm & tem & top150, tg) / wmT(b, tm & tem & top150, tg) - 1)) if (tm & tem & top150).any() else np.nan
        lo = run([([y for y in YEARS if y != t], t) for t in YEARS]); fw = run([([y for y in YEARS if y < t], t) for t in FWD])
        best = pick(YEARS)
        rk = rho_board(lo[0], board, tg, tm) - rho_board(b, board, tg, tm)
        ok_ = best != names[0] and lo[1] < -0.3 and lo[3] >= max(4, int(np.ceil(0.65 * lo[4]))) and fw[1] < 0 and fw[3] >= max(2, int(np.ceil(0.6 * fw[4]))) and (np.isnan(lo[6]) or lo[6] <= 0.1) and not (rk < -0.002)
        sb = lambda k: sum(1 for y in ys if msT(fam[k], tm & (year == y), tg) < msT(b, tm & (year == y), tg) - 1e-12)
        P(f"\n  {title}   (rows {int(tm.sum())}, {nps} player-seasons, {int((tm & top150).sum())} top-150; act/proj on them {tg[tm].sum()/b[tm].sum():.3f})")
        P("    pooled sq err (seasons better): " + "  ".join(f"{k}: {100*(msT(fam[k], tm, tg)/msT(b, tm, tg)-1):+.1f}% MAE {100*(maT(fam[k], tm, tg)/maT(b, tm, tg)-1):+.1f}% ({sb(k)}/{len(ys)})" for k in names[1:]))
        P(f"    LOYO  sq err {lo[1]:+.2f}%  MAE {lo[2]:+.2f}%  seasons better {lo[3]}/{lo[4]}  top-150 wtd {lo[6]:+.2f}%  board rank rho {rk:+.4f} | picks {lo[5]}")
        P(f"    FWD   sq err {fw[1]:+.2f}%  MAE {fw[2]:+.2f}%  seasons better {fw[3]}/{fw[4]}  top-150 wtd {fw[6]:+.2f}% | picks {fw[5]}")
        e1 = tm & (year <= 2018); e2 = tm & (year >= 2019)
        P(f"    by era (LOYO picks): 2012-18 n {int(e1.sum())} {100*(msT(lo[0], e1, tg)/msT(b, e1, tg)-1) if e1.any() else np.nan:+.2f}% | 2019-25 n {int(e2.sum())} {100*(msT(lo[0], e2, tg)/msT(b, e2, tg)-1) if e2.any() else np.nan:+.2f}%")
        P(f"    -> {'PASS: ' + str(best) if ok_ else 'FAIL (best pooled: ' + str(best) + ')'}")
        RES[title] = dict(ok=ok_, best=best, lo=lo[1], lo_mae=lo[2], wins=lo[3], ny=lo[4], fw=fw[1], fw_w=fw[3], fw_ny=fw[4], rows=int(tm.sum()), ps=nps, rk=rk)
        return ok_, best

    # ---------------- 23 excuse debut games from the role docks ----------------
    P(); P("--- 23  EXCUSE NEW-TEAM DEBUT GAMES FROM THE ROLE DOCKS (snap level, RB snap trend, peck) ---")
    # last old-team game snap per row (for 'read the old game instead')
    lastold = np.full(n, np.nan)
    for k_, ix in seqM.items():
        for i in ix:
            if post[i]:
                ol = [j for j in ix if not post[j] and wk[j] < wk[i]]
                if ol: lastold[i] = snapG[ol[-1]]
    for N_ in (1, 2):
        exc = post & (nnew >= 1) & (nnew <= N_)              # the last game read by the snap level is a new-team game 1..N
        fam = {"wired": NB}
        sl_off = np.where(exc, 1.0, SLV0); fam[f"snap level off after new-team games 1-{N_}"] = N14 * sl_off * peck_of(N14 * sl_off) * DOCK
        sl_old = np.where(exc, snaplv(N14, lastold), SLV0); fam[f"snap level reads the last old-team game"] = N14 * sl_old * peck_of(N14 * sl_old) * DOCK
        pk_off = np.where(post & (nnew <= N_), 1.0, PK0); fam[f"peck off through new-team game {N_+1}"] = N14 * SLV0 * pk_off * DOCK
        fam["both off"] = N14 * sl_off * np.where(post & (nnew <= N_), 1.0, peck_of(N14 * sl_off)) * DOCK
        testM(f"23a NEXT GAME, excuse {N_} debut game(s): WR/TE snap level + RB/WR peck", fam, rowsN & ((pos == "WR") | (pos == "TE") | (pos == "RB")), act, (wk != finw2) & (NB >= 3) & (g >= 1))
        # ROS: TE snap level (st mult carries e .3 on l1) and RB snap trend (sm)
        Wm = st["mult"]
        te_dev_l1 = np.zeros(n); te_dev_old = np.zeros(n)
        mTE = (pos == "TE") & ~np.isnan(l1)
        fac_now = np.where(mTE, np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4), 1.0)
        # dev was built from l1 vs the octile mean; swap l1 for the old-team game on excused rows (same octile mean)
        dev_old = np.where(exc & mTE & ~np.isnan(lastold), dev + (lastold - l1), dev)
        fac_old = np.where(mTE, np.clip(1 + 0.3 * dev_old / 100.0, 0.7, 1.4), 1.0)
        sm_ex = sm.copy()
        for i in np.where(exc & (pos == "RB"))[0]:
            _v = MG.get((int(year[i]), pidA[i]))
            if not _v: continue
            Mw = _v["weeks"]; nw = sorted(w for w in Mw if w < wk[i] and Mw[w]["team"] == teamA[i])[:N_]
            sm_ex[i] = NW_snap_mult({w: Mw[w]["snap"] for w in Mw if w not in nw}, int(wk[i]))
        famR = {"wired": S14,
                "TE snap level off": np.where(exc & mTE, S14 / fac_now, S14),
                "TE snap level reads old game": np.where(exc & mTE, S14 / fac_now * fac_old, S14),
                "RB snap trend without debut games": np.where(exc & (pos == "RB"), S14 / np.where(sm > 0, sm, 1) * sm_ex, S14),
                "RB snap trend off": np.where(exc & (pos == "RB"), S14 / np.where(sm > 0, sm, 1), S14)}
        testM(f"23b ROS, excuse {N_} debut game(s): TE snap level / RB snap trend", famR, rowsR & ((pos == "TE") | (pos == "RB")), T, ~np.isnan(T) & (S14 >= 3))

    # ---------------- 24 old-team evidence discount / new-team games up ----------------
    P(); P("--- 24  OLD-TEAM EVIDENCE: discount old-team games (w), pull them toward the prior (a), or weight new-team games up ---")
    # per-game logs for movers straight from the snap/pbp data (xFP by game), points from the harness rows
    glM = {}
    for k_, ix in seqM.items():
        glM[k_] = [dict(q, team=teamA[q["i"]]) for q in gl.get((k_[1], k_[2], k_[0]), [])]
    rc_ok = np.zeros(n, bool); rc_d = []
    for k_, G_ in glM.items():
        for a, q in enumerate(G_):
            i = q["i"]; pg_ = G_[:a]
            if len(pg_) != g[i] or not pg_: continue
            xf_, pv, ge = evid_from(pg_, np.ones(len(pg_)))
            if not np.isnan(xf_): rc_d.append((abs(xf_ - X["xf"][i]), abs(pv - X["ppg_v"][i])))
            if not np.isnan(xf_) and abs(xf_ - X["xf"][i]) < 0.25 and abs(pv - X["ppg_v"][i]) < 0.25: rc_ok[i] = True
    P(f"  mover evidence rebuilt from per-game logs matches the harness on {int((rc_ok & rowsR).sum())}/{int(rowsR.sum())} ROS rows, {int((rc_ok & rowsN).sum())}/{int(rowsN.sum())} next rows"
      f" (median |dxFP| {np.median([d[0] for d in rc_d]) if rc_d else np.nan:.3f}, |dpts| {np.median([d[1] for d in rc_d]) if rc_d else np.nan:.3f})")
    def ev_var(fl, mode, k):
        xf_ = X["xf"].copy(); pv_ = X["ppg_v"].copy(); g_ = g.astype(float).copy()
        for i in np.where(fl & rc_ok)[0]:
            G_ = [q for q in glM[kps[i]] if q["wk"] < wk[i]]
            cur = teamA[i]; isnew = np.array([q["team"] == cur for q in G_])
            w = np.ones(len(G_))
            if mode == "old_w": w[~isnew] = k
            elif mode == "new_up": w[isnew] = k
            if mode == "shrink":
                pr_ = st["prior"][i]; G2 = [dict(q) for q in G_]
                for a, q in enumerate(G2):
                    if not isnew[a]: q["pts"] = pr_ + k * (q["pts"] - pr_); q["xfp"] = pr_ + k * (q["xfp"] - pr_)
                a_, b_, ge = evid_from(G2, w)
            else:
                a_, b_, ge = evid_from(G_, w)
            if ge <= 0: xf_[i] = pv_[i] = 0.0; g_[i] = 0.0; continue
            if np.isnan(a_): continue
            xf_[i], pv_[i] = a_, b_; g_[i] = ge if mode != "new_up" else g[i]
        return xf_, pv_, g_
    def lam_for(g_):
        return np.where((pos == "WR") & band["ADP 101-150"], np.minimum(base_lam(pos, g_), 0.25), base_lam(pos, g_))
    def fams(fl, horizon):
        famR = {"wired": S14 if horizon == "ROS" else NB}
        for mode, ks in (("old_w", (0.0, 0.25, 0.5)), ("shrink", (0.0, 0.5)), ("new_up", (1.5, 2.0, 3.0))):
            for k in ks:
                xf_, pv_, g_ = ev_var(fl, mode, k)
                lab = {"old_w": f"old-team games x{k}", "shrink": f"old games pulled to prior a{k}", "new_up": f"new-team games x{k}"}[mode]
                if horizon == "ROS":
                    r_ = rate_of(lam=np.where(fl, lam_for(g_), st["lam"]), xf_=xf_, pv_=pv_, g_=g_); famR[lab] = np.where(fl, ros_of(r_), S14)
                else:
                    r_ = rate_n(lam=np.where(fl, base_lam(pos, g_), lamN0), xf_=xf_, pv_=pv_, g_=g_); famR[lab] = np.where(fl, r_ * nratio * SLV0 * PK0 * DOCK, NB)
        return famR
    for lab, fl in (("once 1+ new-team games", post & (nnew >= 1)), ("from the debut game on (incl. 0 new-team games)", post & (nnew >= 0)), ("WR/TE only, once 1+ new-team games", post & (nnew >= 1) & ((pos == "WR") | (pos == "TE"))),
                    ("first 3 new-team games only (nnew 1-3)", post & (nnew >= 1) & (nnew <= 3))):
        testM(f"24 ROS, {lab}", fams(fl, "ROS"), rowsR & fl, T, ~np.isnan(T) & (S14 >= 3))
        testM(f"24 NEXT, {lab}", fams(fl, "NEXT"), rowsN & fl, act, (wk != finw2) & (NB >= 3) & (g >= 1))

    # level check: are post-trade players simply over/under-projected? (flat level, both horizons)
    P(); P("  flat level on post-trade rows (is the wired number just high/low?)")
    for lab, fl in (("all post-trade", post), ("new-team games 1-2 ahead (nnew 0-1)", post & (nnew <= 1)), ("WR/TE", post & ((pos == "WR") | (pos == "TE"))), ("RB", post & (pos == "RB"))):
        testM(f"24L ROS level, {lab}", {"wired": S14, **{f"x{k}": np.where(fl, S14 * k, S14) for k in (0.9, 0.95, 1.05, 1.1)}}, rowsR & fl, T, ~np.isnan(T) & (S14 >= 3))
        testM(f"24L NEXT level, {lab}", {"wired": NB, **{f"x{k}": np.where(fl, NB * k, NB) for k in (0.9, 0.95, 1.05, 1.1)}}, rowsN & fl, act, (wk != finw2) & (NB >= 3) & (g >= 1))

    # ---------------- 25 trade capital / young players ----------------
    P(); P("--- 25  TRADE CAPITAL / AGE: does high capital or age <= 24 predict a usage rise after the trade? ---")
    TR = _read_trades()
    cap = {}
    for k_ in seqM:
        v = MI[k_]; nmk = NW.cal.norm(v["name"]); pi_ = [i for i in seqM[k_] if post[i]]
        if not pi_: continue
        newt = teamA[pi_[0]]
        cands = [t for t in TR if t["season"] == k_[0] and NW.cal.norm(t["name"]) == nmk and t["to"] == newt]
        if cands: cap[k_] = cands[-1]
    P(f"  movers with a trade row in trades.csv: {len(cap)}/{sum(1 for k_ in seqM if any(post[i] for i in seqM[k_]))} (others = waived / released / signed)")
    def tier(c):
        if c is None: return "not traded (waiver/FA)"
        return "R1-R2 pick sent" if c["best_round"] is not None and c["best_round"] <= 2 else ("R3 pick" if c["best_round"] == 3 else "R4+ / swap / none")
    rowsP = []
    for k_, ix in seqM.items():
        pi = [i for i in ix if post[i]]
        if len(pi) < 2: continue
        g1 = [i for i in pi if gidx[i] == 1]; g3 = [i for i in pi if gidx[i] >= 3]
        def mean_(arr, ii): vv = [arr[i] for i in ii if not np.isnan(arr[i])]; return float(np.mean(vv)) if vv else np.nan
        rr = [i for i in pi if rowsR[i]]; ck = rr[0] if rr else None
        rowsP.append(dict(k=k_, name=MI[k_]["name"], pos=MI[k_]["pos"], age=MI[k_]["age"], cap=tier(cap.get(k_)), capd=cap.get(k_), adp=adp_ps[k_],
                          s1=mean_(snapG, g1), s3=mean_(snapG, g3), t1=mean_(tgtG, g1), t3=mean_(tgtG, g3), pre_s=pre[k_]["snap"], pre_t=pre[k_]["tgt"],
                          ros=(T[ck] / S14[ck]) if ck is not None else np.nan, n3=len(g3)))
    for grp_lab, key in (("capital tier", lambda r: r["cap"]), ("age", lambda r: "age <= 24" if r["age"] <= 24.5 else "age 25+")):
        P(f"  by {grp_lab}:")
        gg = defaultdict(list)
        for r in rowsP: gg[key(r)].append(r)
        for kk, rs in sorted(gg.items()):
            sr = [r["s3"] / r["s1"] for r in rs if r["s1"] and r["s1"] > 0 and not np.isnan(r["s3"])]; tr_ = [r["t3"] - r["t1"] for r in rs if not np.isnan(r["t1"]) and not np.isnan(r["t3"])]
            ro = [r["ros"] for r in rs if not np.isnan(r["ros"])]
            P(f"    {kk:24s} n {len(rs):2d} | snap games 3+ / game 1: median {np.median(sr) if sr else np.nan:.2f} (n {len(sr)}) | target share 3+ minus game 1: {np.mean(tr_) if tr_ else np.nan:+.1f} pts (n {len(tr_)}) | ROS act/wired at first post-trade checkpoint: mean {np.mean(ro) if ro else np.nan:.3f} median {np.median(ro) if ro else np.nan:.3f} (n {len(ro)})")
    P("  per event (capital): name year pos age | tier (picks sent) | snap g1 -> g3+ | tgt% g1 -> g3+ | ROS act/wired")
    for r in sorted(rowsP, key=lambda r: (r["k"][0], r["name"])):
        c = r["capd"]
        P(f"    {r['name']:24s} {r['k'][0]} {r['pos']} {r['age']:4.1f} | {r['cap']:22s} {c['picks'] if c else ''} | {r['s1']:5.1f} -> {r['s3']:5.1f} | {r['t1']:5.1f} -> {r['t3']:5.1f} | {r['ros']:.3f}")

    # ---------------- 27 debut-game dock (WIRED 10-20 as newTeamDebutMult x0.7, RB/WR/TE, current week) - re-check on 2012-25 ----------------
    P(); P("--- 27  NEW-TEAM DEBUT GAME: wired dock x0.7 re-checked (baseline NB = docked; NB0 = undocked) ---")
    g2_ = post & (nnew == 1)
    gdate = {}
    for Y in YEARS:
        for (t_, w_), gm in SN.NW.B.load_games(Y).items(): gdate[(Y, t_, w_)] = gm.get("date")
    days = np.full(n, np.nan)
    for k_ in cap:
        d0 = pd.to_datetime(cap[k_]["date"], errors="coerce")
        for i in seqM[k_]:
            if deb[i]:
                gd = pd.to_datetime(gdate.get((int(year[i]), teamA[i], int(wk[i]))), errors="coerce")
                if pd.notna(gd) and pd.notna(d0): days[i] = (gd - d0).days
    # weeks on the new roster before the debut (roster_weekly; 0 = debuted the first week he was listed) - trades AND waiver/FA
    rwk = np.full(n, np.nan); _rw = {}
    for Y in sorted(set(int(year[i]) for i in np.where(deb)[0])):
        pth = os.path.join(SN.NW.B.CACHE, f"roster_weekly_{Y}.parquet")
        if not os.path.exists(pth): continue
        r_ = pd.read_parquet(pth, columns=["game_type", "week", "gsis_id", "team"]); r_ = r_[(r_.game_type == "REG") & r_.gsis_id.notna()]
        for gid, w_, t_ in zip(r_.gsis_id.values, r_.week.values, r_.team.values): _rw.setdefault((Y, gid, SN.NW.B.tm(str(t_))), []).append(int(w_))
    for i in np.where(deb)[0]:
        ws = _rw.get((int(year[i]), pidA[i], teamA[i]))
        if ws: rwk[i] = int(wk[i]) - min(ws)
    traded = deb & np.array([cap.get(kps[i]) is not None if is_mv[i] else False for i in range(n)])
    era1 = year <= 2018; era2 = year >= 2019
    skill = (pos == "RB") | (pos == "WR") | (pos == "TE")
    for lab, m in (("all debut games", deb), ("RB/WR/TE", deb & skill), ("WR/TE", deb & ((pos == "WR") | (pos == "TE"))), ("WR", deb & (pos == "WR")), ("TE", deb & (pos == "TE")), ("RB", deb & (pos == "RB")), ("QB", deb & (pos == "QB")),
                   ("RB/WR/TE 2012-18", deb & skill & era1), ("RB/WR/TE 2019-25", deb & skill & era2), ("RB/WR/TE ADP 1-150", deb & skill & (adp <= 150)), ("RB/WR/TE established 50%+ snaps", deb & skill & estab),
                   ("RB/WR/TE traded (trades.csv)", traded & skill), ("RB/WR/TE waiver / FA / other", deb & skill & ~traded),
                   ("traded, debut <= 7 days after the trade", traded & skill & (days <= 7)), ("traded, debut 8+ days after", traded & skill & (days >= 8)),
                   ("debut the first week on the new roster", deb & skill & (rwk == 0)), ("debut 1+ weeks after joining", deb & skill & (rwk >= 1))):
        mm = m & rowsN
        if mm.sum() < 3: P(f"    {lab:42s} n {int(mm.sum())}"); continue
        ys = [y for y in YEARS if (mm & (year == y)).sum() >= 2]
        fit = float(np.sum(act[mm] * NB0[mm]) / np.sum(NB0[mm] ** 2))
        P(f"    {lab:42s} n {int(mm.sum()):3d} ({len(set(kps[mm]))} p-s)  act {act[mm].mean():5.2f}  undocked {NB0[mm].mean():5.2f}  act/undocked {act[mm].sum()/NB0[mm].sum():.3f}  median {np.median(act[mm]/NB0[mm]):.2f}  LS mult {fit:.2f}  seasons under {sum(1 for y in ys if act[mm & (year == y)].sum() < NB0[mm & (year == y)].sum())}/{len(ys)}")
    DOCKS = (1.0, 0.5, 0.6, 0.8, 0.9)
    for lab, m in (("RB/WR/TE", deb & skill), ("WR/TE", deb & ((pos == "WR") | (pos == "TE"))), ("WR", deb & (pos == "WR")), ("TE", deb & (pos == "TE")), ("RB", deb & (pos == "RB")), ("QB (not wired)", deb & (pos == "QB")),
                   ("RB/WR/TE traded", traded & skill), ("RB/WR/TE waiver/FA/other", deb & skill & ~traded), ("RB/WR/TE ADP 1-150", deb & skill & (adp <= 150)),
                   ("RB/WR/TE first week on roster", deb & skill & (rwk == 0)), ("RB/WR/TE 1+ weeks after joining", deb & skill & (rwk >= 1))):
        isqb = lab.startswith("QB")
        base_ = NB0 if isqb else NB
        fam = {("no dock (wired)" if isqb else "wired x0.7"): base_}
        for k in DOCKS + ((0.7,) if isqb else ()):
            if isqb and k == 1.0: continue
            fam[f"x{k}"] = np.where(m, NB0 * k, base_)
        testM(f"27a NEXT, debut dock size, {lab}", fam, rowsN & m, act, (wk != finw2) & (NB >= 3) & (g >= 1))
    testM("27b ROS level from the debut checkpoint (0 new-team games)", {"wired": S14, **{f"x{k}": np.where(deb, S14 * k, S14) for k in (0.8, 0.85, 0.9, 0.95, 1.05)}}, rowsR & deb, T, ~np.isnan(T) & (S14 >= 3))
    testM("27c NEXT, new-team game 2 lift", {"wired": NB, **{f"x{k}": np.where(g2_, NB * k, NB) for k in (0.9, 1.05, 1.1, 1.15)}}, rowsN & g2_, act, (wk != finw2) & (NB >= 3) & (g >= 1))
    testM("27d NEXT, new-team game 2, RB/WR/TE established", {"wired": NB, **{f"x{k}": np.where(g2_ & estab, NB * k, NB) for k in (0.85, 0.9, 1.05, 1.1)}}, rowsN & g2_ & estab & skill, act, (wk != finw2) & (NB >= 3) & (g >= 1))
    # 27e: the engine's ROS sum already carries the x0.7 debut-week dock on that one week; give the harness ROS the same, then test levels on top
    S14d = np.where(deb & skill, S14 * (1 - 0.3 / np.maximum(nfut, 1)), S14)
    for lab, m in (("all positions", deb), ("RB/WR/TE", deb & skill), ("RB/WR/TE established 50%+", deb & skill & estab)):
        mm = m & rowsR
        if mm.any(): P(f"    27e ROS from the debut checkpoint, {lab}: n {int(mm.sum())}  act/ROS-wired {T[mm].sum()/S14[mm].sum():.3f}  act/ROS-with-debut-week-dock {T[mm].sum()/S14d[mm].sum():.3f}")
        testM(f"27e ROS level from the debut checkpoint on top of the debut-week dock, {lab}", {"wired + debut week dock": S14d, **{f"x{k}": np.where(m, S14d * k, S14d) for k in (0.85, 0.9, 0.95, 1.05)}}, rowsR & m, T, ~np.isnan(T) & (S14 >= 3))
    rj = deb & skill & (rwk >= 1)
    testM("27f NEXT, extend: x0.5 when he has been on the new roster 1+ weeks before the debut (else wired x0.7)", {"wired x0.7": NB, **{f"x{k} if 1+ weeks": np.where(rj, NB0 * k, NB) for k in (0.4, 0.5, 0.6)}}, rowsN & deb & skill, act, (wk != finw2) & (NB >= 3) & (g >= 1))
    rj0 = deb & skill & (rwk == 0)
    testM("27g NEXT, two-tier: first-week debut x0.8 / x0.7, 1+ weeks x0.5", {"wired x0.7": NB, "x0.8 / x0.5": np.where(rj0, NB0 * 0.8, np.where(rj, NB0 * 0.5, NB)), "x0.7 / x0.5": np.where(rj, NB0 * 0.5, NB), "x0.75 / x0.45": np.where(rj0, NB0 * 0.75, np.where(rj, NB0 * 0.45, NB))}, rowsN & deb & skill, act, (wk != finw2) & (NB >= 3) & (g >= 1))
    # engine-equivalent: the engine's debut = first SNAP week for the new team (sim_team_weeks, snap counts); drop harness debut rows where he
    # already logged offensive snaps for the new team in an earlier week without a stat line (the engine would not dock those)
    snapprior = np.zeros(n, bool)
    for i in np.where(deb)[0]:
        v_ = MG.get((int(year[i]), pidA[i]))
        if v_ and any(w < wk[i] and q["team"] == teamA[i] for w, q in v_["weeks"].items()): snapprior[i] = True
    engdeb = deb & skill & ~snapprior
    P(f"    engine-equivalent debuts (no earlier new-team snap week): {int((engdeb & rowsN).sum())} of {int((deb & skill & rowsN).sum())} RB/WR/TE debut rows; 1+ weeks on roster first: {int((engdeb & rowsN & (rwk >= 1)).sum())}")
    for lab, m in (("engine-equivalent, first week on roster", engdeb & (rwk == 0)), ("engine-equivalent, 1+ weeks on roster first", engdeb & (rwk >= 1))):
        mm = m & rowsN
        if mm.sum() >= 3: P(f"    {lab:46s} n {int(mm.sum())}  act/undocked {act[mm].sum()/NB0[mm].sum():.3f}  LS mult {float(np.sum(act[mm]*NB0[mm])/np.sum(NB0[mm]**2)):.2f}")
    rjE = engdeb & (rwk >= 1)
    testM("27h NEXT, engine-equivalent debuts: x0.7 / x0.5 after 1+ weeks on the roster", {"wired x0.7": NB, **{f"x0.7 / x{k}": np.where(rjE, NB0 * k, NB) for k in (0.4, 0.5, 0.6)}}, rowsN & engdeb, act, (wk != finw2) & (NB >= 3) & (g >= 1))
    testM("27i NEXT, engine-equivalent debuts: one dock size", {"wired x0.7": NB, **{f"x{k}": np.where(engdeb, NB0 * k, NB) for k in (0.5, 0.6, 0.8, 1.0)}}, rowsN & engdeb, act, (wk != finw2) & (NB >= 3) & (g >= 1))
    P("  debut games (name year pos | days after trade | wks on roster before | snap% debut vs old | pts | undocked | docked):")
    for i in sorted(np.where(deb & rowsN)[0], key=lambda i: (int(year[i]), name[i])):
        P(f"    {name[i]:24s} {int(year[i])} {pos[i]} | {days[i] if not np.isnan(days[i]) else '-':>4} | {rwk[i] if not np.isnan(rwk[i]) else '-':>3} | {snapG[i]:5.1f} vs {preS[i]:5.1f} | {act[i]:5.1f} | {NB0[i]:5.1f} | {NB[i]:5.1f}")

    # ---------------- 26 summary ----------------
    P(); P("--- 26  SUMMARY: every test (PASS needs LOYO -0.3%+ and most seasons, forward better, top-150 and board rank not worse) ---")
    for t_, r in RES.items():
        P(f"    {'PASS' if r['ok'] else 'fail'}  {t_:80s} rows {r['rows']:4d} ({r['ps']:2d} p-s)  best {r['best']:38s} LOYO {r['lo']:+6.2f}% MAE {r['lo_mae']:+6.2f}% {r['wins']}/{r['ny']}  FWD {r['fw']:+6.2f}% {r['fw_w']}/{r['fw_ny']}  rank {r['rk']:+.4f}")
    pickle.dump(dict(RES=RES, rowsP=rowsP), open(os.path.join(HERE, "_tmp", "mst", "results_ext.pkl"), "wb"))
    log.close()

def _read_trades():
    """trades.csv (nflverse nfldata, in pbp_cache): player rows + the picks the receiving team sent, per trade_id"""
    t = pd.read_csv(os.path.join(SN.NW.B.CACHE, "trades.csv"))
    out = []
    for tid, x in t.groupby("trade_id"):
        pl_ = x[x.pfr_name.notna()]
        for r in pl_.itertuples(index=False):
            sent = x[(x.gave == r.received) & x.pick_round.notna()]
            rounds = sorted(int(q) for q in sent.pick_round.dropna())
            out.append(dict(season=int(r.season), date=r.trade_date, name=str(r.pfr_name), to=SN.NW.B.tm(str(r.received)), frm=SN.NW.B.tm(str(r.gave)),
                            best_round=rounds[0] if rounds else None, picks=",".join(f"{int(q.pick_season) if pd.notna(q.pick_season) else ''}R{int(q.pick_round)}" for q in sent.itertuples(index=False))))
    return out

def NW_snap_mult(wkpct, wk_):
    import build_context_features as BCF
    return BCF.snap_mult(wkpct, wk_)

if __name__ == "__main__":
    main()
