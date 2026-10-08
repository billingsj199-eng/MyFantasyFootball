#!/usr/bin/env python3
"""
REST-OF-SEASON backtest for the Clay-free model, in season (Jack 2026-10-02: "pre season is not relevant lets focus on
in season so rest of season by this point and we should be able to improve the model through backtesting").

Checkpoint = a player entering a game with 3-10 games already played that season. What is graded is the per-game
number the model carries for the REST of his season: target = his average over the games he plays from that week on
(final week dropped, 4+ games needed); prediction = the model's context-free rate x the average of those weeks'
context layers (Vegas / matchup), so both models see the same schedule and only the RATE is graded.

  0  where we stand: Clay-free rate vs the Clay blend (P = 5) at this horizon, by position and games played
  1  how much the season so far should count (prior weight in games, by position) for the rest of the season
  2  what the evidence should be: points, or usage (xFP), by position
  3  level: pull toward / push away from the position average
  4  what the rest-of-season miss still correlates with (screen for the next round)

Picked leave-one-season-out and forward (earlier seasons only, 2022-25). Error = squared, on the rows of the position
being tuned; the top-150 importance-weighted error and the within-position rank order are reported beside it.
Log shadow_ros.log.
"""
import os, sys
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
NW = SN.NW; YEARS = SN.YEARS; POS4 = ("QB", "RB", "WR", "TE")
FWD = (2022, 2023, 2024, 2025)
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
    log = open(os.path.join(HERE, "shadow_ros.log" if MINF == 4 else f"shadow_ros_minf{MINF}.log"), "w", encoding="utf-8")
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
    P(f"=== rest-of-season, in season: {int(ok.sum()):,} checkpoints 2019-25 (3-10 games played, {MINF}+ games left), {int((ok & top150).sum()):,} top-150 ===")

    # ---------------- 0 where we stand ----------------
    P("\n--- 0  WHERE WE STAND: Clay-free rate vs the Clay blend, rest-of-season per-game ---")
    def stand(lab, m):
        m = m & ok
        if m.sum() < 100: return
        w = sum(1 for y in YEARS if ms(SH, m & (year == y)) < ms(CL, m & (year == y)))
        P(f"    {lab:26s} n {int(m.sum()):5d}  actual {T[m].mean():5.2f}  Clay-free {SH[m].mean():5.2f}  Clay blend {CL[m].mean():5.2f}  | Clay-free error vs Clay blend {100*(ms(SH, m)/ms(CL, m)-1):+6.2f}%  seasons better {w}/7"
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
        P(f"    LEAVE-ONE-SEASON-OUT  {lo[1]:+.2f}%  seasons better {lo[3]}/7  | top-150 weighted {lo[2]:+.2f}%  rank order {rho(lo[0], tm & top150) - rho(b, tm & top150):+.4f}  | picks {lo[4]}")
        P(f"    FORWARD 2022-25       {fw[1]:+.2f}%  seasons better {fw[3]}/4  | top-150 weighted {fw[2]:+.2f}%  | picks {fw[4]}")
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
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
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
        P(f"    {lab:10s} vs shipped Clay-free {100*(ms(S5, m)/ms(SH, m)-1):+.2f}% ({w1}/7)  vs Clay blend {100*(ms(S5, m)/ms(CL, m)-1):+.2f}% ({w2}/7)  | weighted {100*(wm(S5, m & top150)/wm(SH, m & top150)-1):+.2f}% / {100*(wm(S5, m & top150)/wm(CL, m & top150)-1):+.2f}%"
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
        P(f"    {lab:30s} n {int(m.sum()):5d}  {100*(ms(S7, m)/ms(W, m)-1):+6.2f}% ({w1}/7) | {100*(ms(S7, m)/ms(CL, m)-1):+6.2f}% ({w2}/7; was {100*(ms(W, m)/ms(CL, m)-1):+6.2f}%)  | act/proj {T[m].sum()/S7[m].sum():.3f} (was {T[m].sum()/W[m].sum():.3f})"
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
        P(); P(f"  {lab}: n {int(m.sum())}, actual / projected {T[m].sum()/M[m].sum():.3f}, error vs Clay blend {100*(ms(M, m)/ms(CL, m)-1):+.2f}% (better {wins}/7), rank order {rho(M, m):.3f} vs {rho(CL, m):.3f}")
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
        P(f"    {lab:18s} n {int(m.sum()):5d}  {100*(ms(S9, m)/ms(M, m)-1):+6.2f}% ({w1}/7) | {100*(ms(S9, m)/ms(CL, m)-1):+6.2f}% ({w2}/7; was {100*(ms(M, m)/ms(CL, m)-1):+6.2f}%)  | act/proj {T[m].sum()/S9[m].sum():.3f} (was {T[m].sum()/M[m].sum():.3f})  | rank order {rho(S9, m):.3f} (was {rho(M, m):.3f}, Clay blend {rho(CL, m):.3f})")

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
        P(f"    {k:38s} {int(tt.sum()):5d} | {a:+6.2f}% ({sa}/7)            | {b:+6.2f}% ({sb_}/7)            | {r:+.4f}    | {'HURTS' if bad >= 2 else 'mixed' if bad == 1 else 'helps'}   (its own rows {tr:+.2f}%)")

    # ---------------- 12 THE SEASON BLEND (Jack 2026-10-08: "what else can we test to get rid of the season blend") ----------------
    # The live later-week number is w x shadow + (1 - w) x Clay form per position (QB .5 / RB .8 / WR .7 / TE 0), weights fit on
    # the NEXT GAME. Here the full rest-of-season shadow (as wired through v2.28) is blended with the Clay blend at this horizon:
    # does any weight beat the shadow alone (w 1) out of sample? Picked LOYO + forward per position; rank order beside it.
    P(); P("--- 12  SEASON BLEND: w x full shadow + (1 - w) x Clay blend, rest of season, per position (w 1 = shadow alone) ---")
    WG12 = (0.0, 0.3, 0.5, 0.7, 0.8, 0.9, 1.0); WIRED12 = {"QB": 0.5, "RB": 0.8, "WR": 0.7, "TE": 0.0}
    bl12 = lambda w: w * FULL + (1 - w) * CL
    bw12 = np.array([WIRED12[p_] for p_ in pos]); WB12 = bw12 * FULL + (1 - bw12) * CL
    for lab12, m12 in (("all rows", ok), ("top 150", t150)):
        P(f"  {lab12}: " + " | ".join(f"w {w:.1f}: {100*(wm(bl12(w), m12)/wm(FULL, m12)-1):+.2f}% ({sum(1 for y in YEARS if wm(bl12(w), m12 & (year == y)) < wm(FULL, m12 & (year == y)) - 1e-12)}/7) rho {rho(bl12(w), m12):.4f}" for w in WG12 if w != 1.0) + f" | shadow alone rho {rho(FULL, m12):.4f} | wired weights {100*(wm(WB12, m12)/wm(FULL, m12)-1):+.2f}% rho {rho(WB12, m12):.4f}")
    for ps in POS4:
        m12 = t150 & (pos == ps); best = min(WG12, key=lambda w: wm(bl12(w), m12))
        P(f"  {ps} (n{int(m12.sum())}): best fixed w {best:.1f} ({100*(wm(bl12(best), m12)/wm(FULL, m12)-1):+.2f}% vs shadow alone) | wired w {WIRED12[ps]:.1f}: {100*(wm(bl12(WIRED12[ps]), m12)/wm(FULL, m12)-1):+.2f}% ({sum(1 for y in YEARS if wm(bl12(WIRED12[ps]), m12 & (year == y)) < wm(FULL, m12 & (year == y)) - 1e-12)}/7) | Clay blend alone {100*(wm(CL, m12)/wm(FULL, m12)-1):+.2f}% | rank shadow {rho(FULL, m12):.4f} wired {rho(WB12, m12):.4f} Clay {rho(CL, m12):.4f}")
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
        P(f"    {lab:14s} n {int(m.sum()):5d}  vs wired {100*(ms(S13, m)/ms(M, m)-1):+6.2f}% ({w1}/7) | vs Clay blend {100*(ms(S13, m)/ms(CL, m)-1):+6.2f}% | top-150 wtd {100*(wm(S13, m & top150)/wm(M, m & top150)-1):+6.2f}% | rank order {rho(S13, m & top150):.4f} (wired {rho(M, m & top150):.4f})")

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
            rec_ = cal.weekly_rec(name[i], "TE"); _logs14[k_] = {int(w["wk"]): 6 * float(w.get("rctd") or 0) + 6 * float(w.get("rtd") or 0) for w in (rec_ or {}).get("seasons", {}).get(str(Y), []) if cal.played(w) and isinstance(w.get("fpts"), (int, float))}
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
        P(f"    {lab:12s} n {int(m.sum()):5d}  vs section 13 {100*(ms(S14, m)/ms(S13, m)-1):+6.2f}% ({w1}/7) | vs Clay blend {100*(ms(S14, m)/ms(CL, m)-1):+6.2f}% | act/proj {T[m].sum()/S14[m].sum():.3f} (was {T[m].sum()/S13[m].sum():.3f}) | rank order {rho(S14, m & top150):.4f} (was {rho(S13, m & top150):.4f})")

    log.close()

if __name__ == "__main__":
    main()
