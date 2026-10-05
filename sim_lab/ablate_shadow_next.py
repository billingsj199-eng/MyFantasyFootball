#!/usr/bin/env python3
"""
ABLATION of the Clay-free model, NEXT GAME (Jack 2026-10-02: "take out anything that overall hurts the backtest").
The harness shadow (backtest_shadow_next form) plus the v2.25 layers, one piece removed at a time, graded on the WHOLE
board: all rows, top-150 importance-weighted, weekly rank order within position. Negative = having the piece helps.
The rest-of-season pieces are ablated in backtest_shadow_ros.py section 10.

Also three next-game leads from research_next_candidates.py, tested as layers on top of the full model:
  the game after an early exit (RB), receivers the first game after the bye, hamstring on the injury report.
Log ablate_shadow_next.log.
"""
import os, sys
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
from bt_common import load_games
cal = SN.cal; YEARS = SN.YEARS; NW = SN.NW; CACHE = r"E:\MyFantasyFootball\pbp_cache"

def main():
    log = open(os.path.join(HERE, "ablate_shadow_next.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n"); log.flush()
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["team"]
    SH = SN.shadow(X)
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in NW.POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    base = top150 & ~final; allr = ~final & (SH >= 3)
    wm = lambda q, mm: float(np.average((q[mm] - act[mm]) ** 2, weights=wt[mm])) if mm.any() else np.nan
    ms = lambda q, mm: float(np.mean((q[mm] - act[mm]) ** 2)) if mm.any() else np.nan
    def rho(p, m):
        groups = defaultdict(list)
        for i in np.where(m)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
        rh = [np.corrcoef(rankdata(act[ix]), rankdata(p[ix]))[0, 1] for ix in (np.array(x) for x in groups.values()) if len(ix) >= 8]
        return float(np.mean(rh))
    base_lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    # snap-level deviation (same bins as backtest_shadow_next.level_family)
    l1 = X["snap_l1"]; dev = np.zeros(n)
    for ps in ("WR", "TE"):
        m = (pos == ps) & (g >= 1) & ~np.isnan(l1) & allr
        q = np.quantile(SH[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, SH, side="right") - 1, 0, 7)
        for k in range(8):
            mk = m & (b_ == k)
            if mk.sum() >= 30: dev[mk] = l1[mk] - np.nanmean(l1[mk])
    low = np.maximum(0, 19 - np.nan_to_num(X["implied"], nan=19)) / 19
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = X["A"]["pid"]; idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    smx = colv("snapmult"); smx = np.where(np.isnan(smx) | (pos == "QB"), 1.0, smx)   # the engine snap-trend multiplier (in the live chain the shadow shares)

    def full(off=()):
        on = lambda k: k not in off
        lam = base_lam.copy()
        if not on("usage evidence, WR"): lam = np.where(pos == "WR", 0.0, lam)
        if not on("usage evidence, RB"): lam = np.where(pos == "RB", 0.0, lam)
        pts = X["ppg_v"] if on("Vegas-cleaned evidence") else X["ppg"]
        ev = lam * X["xf"] + (1 - lam) * pts
        pr_ = X["prior"] if on("ridge season prior mix") else F["prior"]
        Pw = F["Pvec"] * (np.where((pos == "WR") & (g == 1), 5.0, 1.0) if on("WR one-game prior x5") else 1.0)
        out = (Pw * pr_ + g * ev) / np.maximum(Pw + g, 1e-9) * X["layers"]
        if on("rookie ramp (not first string, weeks 1-2)"):
            for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
        if on("vacated-role pool"): out = np.where(F["on"], out * np.power(F["pm"], 0.75), out)
        if on("QB game-total tilt"): out = np.where(pos == "QB", out * np.exp(0.03 * X["z"]), out)
        if on("WR dock when the QB is out"): out = np.where((pos == "WR") & X["qbo"], out * np.where(adp <= 60, 0.85, 0.95), out)
        for ps_ in ("RB", "WR", "TE"):
            if on(f"snap trend (engine layer), {ps_}"): out = np.where(pos == ps_, out * smx, out)
        if on("v2.25 snap-share level, WR"): out = np.where(pos == "WR", out * np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4), out)
        if on("v2.25 snap-share level, TE"): out = np.where(pos == "TE", out * np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4), out)
        if on("v2.25 QB changed teams x.90"): out = np.where((pos == "QB") & X["mover"], out * 0.90, out)
        if on("v2.25 QB low team total"): out = np.where(pos == "QB", out * (1 - 0.75 * low), out)
        if on("v2.25 rookie WR games 2-5 x.90"): out = np.where((pos == "WR") & X["rookie"] & (g >= 2) & (g <= 5), out * 0.90, out)
        if on("v2.25 RB under 30% of carries, games 2-5 x.90"): out = np.where((pos == "RB") & (g >= 2) & (g <= 5) & (X["car_sh"] < 0.30), out * 0.90, out)
        return out
    PIECES = ["usage evidence, WR", "usage evidence, RB", "Vegas-cleaned evidence", "ridge season prior mix", "WR one-game prior x5", "rookie ramp (not first string, weeks 1-2)", "vacated-role pool", "QB game-total tilt",
              "WR dock when the QB is out", "snap trend (engine layer), RB", "snap trend (engine layer), WR", "snap trend (engine layer), TE", "v2.25 snap-share level, WR", "v2.25 snap-share level, TE", "v2.25 QB changed teams x.90", "v2.25 QB low team total", "v2.25 rookie WR games 2-5 x.90", "v2.25 RB under 30% of carries, games 2-5 x.90"]
    FULL = full()
    P(f"=== ablation, next game: {int(allr.sum()):,} player-weeks ({int(base.sum()):,} top-150); full model rank order {rho(FULL, base):.4f} ===")
    P(f"    {'piece':46s} rows  | all rows (seasons it helps) | top-150 weighted (seasons) | rank order | verdict")
    for k in PIECES:
        WO = full((k,)); tt = allr & (np.abs(WO - FULL) > 1e-9)
        a = 100 * (ms(FULL, allr) / ms(WO, allr) - 1); b = 100 * (wm(FULL, base) / wm(WO, base) - 1); r = rho(FULL, base) - rho(WO, base)
        sa = sum(1 for y in YEARS if ms(FULL, allr & (year == y)) < ms(WO, allr & (year == y)) - 1e-12); sb = sum(1 for y in YEARS if wm(FULL, base & (year == y)) < wm(WO, base & (year == y)) - 1e-12)
        tr = 100 * (ms(FULL, tt) / ms(WO, tt) - 1) if tt.any() else 0.0
        bad = (a > 0) + (b > 0) + (r < 0)
        P(f"    {k:46s} {int(tt.sum()):5d} | {a:+6.2f}% ({sa}/7)            | {b:+6.2f}% ({sb}/7)            | {r:+.4f}    | {'HURTS' if bad >= 2 else 'mixed' if bad == 1 else 'helps'}   (its own rows {tr:+.2f}%)")

    P(); P("  snap TREND (engine layer) vs snap LEVEL (v2.25), by position - the four combinations, on that position's rows (vs neither):")
    for ps_ in ("WR", "TE"):
        tk, lk = f"snap trend (engine layer), {ps_}", f"v2.25 snap-share level, {ps_}"; m = allr & (pos == ps_); mb = base & (pos == ps_)
        NEI = full((tk, lk))
        for lab, off in (("trend only", (lk,)), ("level only", (tk,)), ("both (wired)", ())):
            V = full(off); sw = sum(1 for y in YEARS if wm(V, mb & (year == y)) < wm(NEI, mb & (year == y)) - 1e-12)
            P(f"    {ps_} {lab:13s} all rows {100*(ms(V, m)/ms(NEI, m)-1):+.2f}%  top-150 weighted {100*(wm(V, mb)/wm(NEI, mb)-1):+.2f}% ({sw}/7)  rank order {rho(V, mb) - rho(NEI, mb):+.4f}")
    # ---------------- next-game leads ----------------
    P("\n=== next-game leads on top of the full model (touched rows; LOSO + forward; whole-board top-150 weighted as the guard) ===")
    def test(title, fam):
        names = list(fam); b = fam[names[0]]; touched = np.zeros(n, bool)
        for k in names[1:]: touched |= np.abs(fam[k] - b) > 1e-9
        tm = touched & allr
        pick = lambda yrs: min(names, key=lambda k: ms(fam[k], tm & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = b.copy()
            for tr_, te in folds:
                k = pick(tr_); picks.append(k); m = year == te; pr[m] = fam[k][m]; wins += ms(fam[k], tm & m) < ms(b, tm & m) - 1e-12
            tem = np.isin(year, [te for _, te in folds])
            return pr, 100 * (ms(pr, tm & tem) / ms(b, tm & tem) - 1), 100 * (wm(pr, base & tem) / wm(b, base & tem) - 1), wins, picks
        lo = run([([y for y in YEARS if y != t], t) for t in YEARS]); fw = run([([y for y in YEARS if y < t], t) for t in (2022, 2023, 2024, 2025)])
        sbk = lambda k: sum(1 for y in YEARS if (tm & (year == y)).sum() >= 8 and ms(fam[k], tm & (year == y)) < ms(b, tm & (year == y)) - 1e-12)
        best = pick(YEARS); okk = best != names[0] and lo[1] < -0.3 and lo[3] >= 5 and fw[1] < 0 and fw[3] >= 3 and lo[2] <= 0.02
        P(f"\n  {title}   (rows {int(tm.sum()):,}; actual / projected {act[tm].sum()/max(1e-9, b[tm].sum()):.3f})")
        P("    fixed settings (seasons better): " + "  ".join(f"{k}: {100*(ms(fam[k], tm)/ms(b, tm)-1):+.2f}% ({sbk(k)})" for k in names[1:]))
        P(f"    LEAVE-ONE-SEASON-OUT {lo[1]:+.2f}% {lo[3]}/7 | whole board top-150 weighted {lo[2]:+.3f}%, rank order {rho(lo[0], base) - rho(b, base):+.4f} | picks {lo[4]}")
        P(f"    FORWARD 2022-25      {fw[1]:+.2f}% {fw[3]}/4 | whole board top-150 weighted {fw[2]:+.3f}% | picks {fw[4]}")
        P(f"    -> {'PASS: ' + str(best) if okk else 'FAIL'}")
    mult = lambda m, k, b_=None: np.where(m, (FULL if b_ is None else b_) * k, (FULL if b_ is None else b_))
    # early exit: last game under 60% of the share he had before it (50%+ before)
    seq = defaultdict(list)
    for i in range(n): seq[(name[i], pos[i], int(year[i]))].append(i)
    prev = np.full(n, -1)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i])
        for a_, i in enumerate(ix):
            if a_: prev[i] = ix[a_ - 1]
    std_before = np.where(prev >= 0, X["snap_std"][np.maximum(prev, 0)], np.nan)
    exitm = ~np.isnan(std_before) & (std_before >= 50) & (l1 < 0.6 * std_before)
    for ps in ("RB", "WR", "TE"):
        test(f"the game after an early exit, {ps}", {"1.00 (as is)": FULL, **{f"x{k}": mult(exitm & (pos == ps), k) for k in (0.95, 0.90, 0.85, 0.80)}})
    # rest
    rest = np.full(n, np.nan)
    for Y in YEARS:
        games = load_games(Y); bt = defaultdict(list)
        for (t, w), gm in games.items():
            if isinstance(gm, dict) and gm.get("date"): bt[t].append((w, pd.Timestamp(gm["date"])))
        gap = {}
        for t, L in bt.items():
            L.sort()
            for a_ in range(1, len(L)): gap[(t, L[a_][0])] = (L[a_][1] - L[a_ - 1][1]).days
        for i in np.where(year == Y)[0]:
            v = gap.get((team[i], int(wk[i])))
            if v is not None: rest[i] = v
    for ps in ("WR", "QB", "TE"):
        test(f"first game after the bye, {ps}", {"1.00 (as is)": FULL, **{f"x{k}": mult((pos == ps) & (rest >= 12), k) for k in (0.97, 0.94, 0.91)}})
    # injury report body part
    inj = {}
    for Y in YEARS:
        f = os.path.join(CACHE, f"injuries_{Y}.parquet")
        if not os.path.exists(f): continue
        d = pd.read_parquet(f, columns=["week", "game_type", "full_name", "report_primary_injury", "report_status", "practice_primary_injury"])
        d = d[d.game_type == "REG"]
        for r in d.itertuples(index=False):
            part = r.report_primary_injury if isinstance(r.report_primary_injury, str) and r.report_primary_injury else r.practice_primary_injury
            if isinstance(part, str) and part: inj[(Y, int(r.week), cal.norm(str(r.full_name)))] = (part.split(",")[0].strip().lower(), r.report_status if isinstance(r.report_status, str) else "")
    part = np.array([inj.get((int(year[i]), int(wk[i]), cal.norm(name[i])), ("", ""))[0] for i in range(n)]); stat = np.array([inj.get((int(year[i]), int(wk[i]), cal.norm(name[i])), ("", ""))[1] for i in range(n)])
    skill = np.isin(pos, ["RB", "WR", "TE"]); ham = skill & (part == "hamstring")
    FQ = np.where(skill & (stat == "Questionable"), FULL * 0.90, FULL)   # stand-in for the engine's generic Questionable dock
    P(); P("  (the next ones are on top of a flat x.90 for every Questionable RB / WR / TE - the engine already docks those)")
    test("hamstring, Questionable: EXTRA on top of the generic dock", {"1.00 (as is)": FQ, **{f"x{k}": mult(ham & (stat == "Questionable"), k, FQ) for k in (0.92, 0.85, 0.80, 0.75)}})
    ill = skill & (part == "illness") & (stat == "Questionable")
    test("illness, Questionable: EXTRA on top of the generic dock", {"1.00 (as is)": FQ, **{f"x{k}": mult(ill, k, FQ) for k in (0.92, 0.85)}})
    soft = skill & np.isin(part, ["groin", "hip", "quadricep", "quad", "thigh", "foot", "toe", "back"]) & (stat == "Questionable")
    test("groin / hip / quad / foot / back, Questionable: give the generic dock BACK", {"1.00 (as is)": FQ, **{f"x{k}": mult(soft, k, FQ) for k in (1.05, 1.11)}})
    test("hamstring on the report, Questionable, no generic dock (for scale)", {"1.00 (as is)": FULL, **{f"x{k}": mult(ham & (stat == "Questionable"), k) for k in (0.90, 0.80, 0.72)}})
    test("hamstring on the report, any status", {"1.00 (as is)": FULL, **{f"x{k}": mult(ham, k) for k in (0.95, 0.90, 0.85)}})
    test("Questionable, any injury (RB / WR / TE) - for scale", {"1.00 (as is)": FULL, **{f"x{k}": mult(skill & (stat == "Questionable"), k) for k in (0.95, 0.90, 0.85)}})
    log.close()

if __name__ == "__main__":
    main()
