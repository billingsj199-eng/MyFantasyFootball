#!/usr/bin/env python3
"""
NEXT LAYERS FOR THE CLAY-FREE MODEL (Jack 2026-10-02: "can we test those") - the five candidates out of
research_shadow_residuals.py, each graded on the shadow itself (v2.24 form, 2019-25, half-PPR, final week out):

  1  BACKUP QB       a fill-in starting for the team's regular quarterback: his own number, the starter's
                     number x .85, or the larger / the average of the two (the live engine adds them)
  2  USAGE LEVEL     2a tight-end usage evidence (xFP blended into the evidence, as RB / WR already have)
                     2b snap-share LEVEL for WR / TE (last game vs what players at that projection usually play)
                     2c target-share LEVEL for WR / TE (same construction)
  3  QUARTERBACKS    3a rushing / usage evidence (xFP blend)   3b changed teams   3c no ADP
                     3d teams implied under 19 (QB and WR, extra below-average elasticity)
  4  RECEIVERS       4a evidence mix early (less usage, more points)   4b under 12% of targets
                     4c rookie WR games 2-5   4d target share trending up   4e RB under 30% of carries, games 2-5
  5  TEAM SHIFT      the team's lines this season vs the preseason view (the own-totals shift) -> its players

Grading (the house rules): the setting is picked LEAVE-ONE-SEASON-OUT and again FORWARD (earlier seasons only,
graded 2022-25); error = top-150 importance-weighted squared error (feedback: weight the players that matter),
shown next to the plain error on the rows the layer touches and the weekly within-position rank correlation.
Ship bar: LOSO better in 5+ of 7 seasons AND forward better in 3+ of 4. Log shadow_next.log.
"""
import json, os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import research_clay_vs_shadow as CS
import backtest_season_long as SL
import backtest_future_totals as FT
cal = NW.cal; YEARS = NW.YEARS
warnings.filterwarnings("ignore")

def setup():
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, layers, adp, pid, name = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["layers"], F["adp"], A["pid"], A["name"]
    T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]
    v = SL.loyo(T, LIVE, "ridge", 10.0); key = {(int(y), nm, ps): x for y, nm, ps, x in zip(T.year, T.name, T.pos, v)}
    ridge = np.array([key.get((year[i], name[i], pos[i]), np.nan) for i in range(n)])
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    xfp = colv("xfp_pg"); ev = has & (g >= 1) & ~np.isnan(xfp); xf = np.where(ev, xfp, ppg); veg = colv("veg")
    gt = colv("game_total"); z = np.zeros(n)
    for y in YEARS:
        for w_ in range(1, 19):
            m = (year == y) & (wk == w_) & ~np.isnan(gt)
            if m.sum() > 20 and gt[m].std() > 0: z[m] = np.clip((gt[m] - gt[m].mean()) / gt[m].std(), -2.5, 2.5)
    qbo = colv("qb_out") == 1
    rowof = {(name[i], pos[i], int(year[i]), int(wk[i])): i for i in range(n)}; logs = {}; ppg_v = ppg.copy()
    for i in range(n):
        if g[i] < 1: continue
        k = (name[i], pos[i], int(year[i]))
        if k not in logs:
            wrec = cal.weekly_rec(name[i], pos[i]); logs[k] = sorted((int(w["wk"]), float(w["fpts"])) for w in (wrec or {}).get("seasons", {}).get(str(int(year[i])), []) if cal.played(w) and isinstance(w.get("fpts"), (int, float)))
        L = [x for x in logs[k] if x[0] < wk[i]]
        if not L: continue
        tot = 0.0
        for w_, p_ in L:
            ri = rowof.get((name[i], pos[i], int(year[i]), w_)); vv = veg[ri] if ri is not None and not np.isnan(veg[ri]) else (layers[ri] if ri is not None else 1.0)
            tot += p_ / float(np.clip(vv, 0.6, 1.6))
        raw = sum(p_ for _, p_ in L)
        if raw > 0: ppg_v[i] = ppg[i] * float(np.clip(tot / raw, 0.75, 1.35))
    prior = np.where(np.isnan(ridge) | (pos == "QB"), F["prior"], 0.5 * ridge + 0.5 * F["prior"])
    early = np.where((pos == "WR") & (g == 1), 5.0, 1.0)
    X = dict(F=F, A=A, n=n, act=act, year=year, wk=wk, pos=pos, g=g, ppg=ppg, ppg_v=ppg_v, xf=xf, has_x=ev, layers=layers, adp=adp, name=name, prior=prior, Pw=F["Pvec"] * early, z=z, qbo=qbo, team=A["team"],
             mover=np.array(A["mover"], dtype=bool), rookie=np.array(A["rookie"], dtype=bool))
    for c in ("snap_l1", "snap_std", "tgt_sh", "car_sh", "tgt_trend", "implied"): X[c] = colv(c)
    return X

def shadow(X, lam=None):
    """the shadow with a given usage-evidence weight per row (default = shipped: WR / RB schedules, 0 for QB / TE)"""
    pos, g, F, wk = X["pos"], X["g"], X["F"], X["wk"]
    if lam is None:
        lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    evid = lam * X["xf"] + (1 - lam) * X["ppg_v"]
    rate = (X["Pw"] * X["prior"] + g * evid) / np.maximum(X["Pw"] + g, 1e-9)
    out = rate * X["layers"]
    for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
    out = np.where(F["on"], out * np.power(F["pm"], 0.75), out)
    out = np.where(pos == "QB", out * np.exp(0.03 * X["z"]), out)
    return np.where((pos == "WR") & X["qbo"], out * np.where(X["adp"] <= 60, 0.85, 0.95), out)

def main():
    log = open(os.path.join(HERE, "shadow_next.log"), "w", encoding="utf-8")
    def P(s=""): print(s); log.write(s + "\n"); log.flush()
    X = setup(); n = X["n"]; act, year, wk, pos, g, adp = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"]
    F = X["F"]; SH = shadow(X)
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
    rho0 = rho(SH, base)
    P(f"=== next layers for the Clay-free model: {int(allr.sum()):,} player-weeks ({int(base.sum()):,} top-150), baseline = shadow v2.24 form, rank rho {rho0:.4f} ===")
    PASS = {}
    def test(title, fam, key=None):
        """fam: ordered {setting: prediction}; the first is the baseline. A narrow layer is picked and judged on the
        rows it touches (plain squared error); the top-150 weighted error over the whole board is the guard."""
        names = list(fam); b = fam[names[0]]
        touched = np.zeros(n, bool)
        for k in names[1:]: touched |= np.abs(fam[k] - b) > 1e-9
        tm = touched & allr
        pick = lambda yrs: min(names, key=lambda k: ms(fam[k], tm & np.isin(year, yrs)))
        def run(folds):
            wins = ny = 0; picks = []; pred = b.copy()
            for tr, te in folds:
                k = pick(tr); picks.append(k); m = year == te; pred[m] = fam[k][m]
                if (tm & m).sum() >= 8:
                    ny += 1; wins += ms(fam[k], tm & m) < ms(b, tm & m) - 1e-12
            tem = np.isin(year, [te for _, te in folds])
            return pred, 100 * (wm(pred, base & tem) / wm(b, base & tem) - 1), 100 * (ms(pred, tm & tem) / ms(b, tm & tem) - 1) if (tm & tem).any() else np.nan, wins, picks, ny
        lo = run([([y for y in YEARS if y != t], t) for t in YEARS]); fw = run([([y for y in YEARS if y < t], t) for t in (2022, 2023, 2024, 2025)])
        best = pick(YEARS)
        ok = best != names[0] and lo[2] < -0.3 and lo[3] >= max(5, lo[5] - 2) and fw[2] < 0 and fw[3] >= 3 and lo[1] <= 0.02
        P()
        P(f"  {title}   (rows touched {int(tm.sum()):,}, {int((tm & top150).sum()):,} of them top-150; actual / shadow on them {act[tm].sum()/max(1e-9, b[tm].sum()):.3f})")
        P("    pooled, touched rows: " + "  ".join(f"{k}: {100*(ms(fam[k], tm)/ms(b, tm)-1):+.2f}%" for k in names[1:]))
        P(f"    LEAVE-ONE-SEASON-OUT  touched rows {lo[2]:+.2f}%  seasons better {lo[3]}/{lo[5]}  | whole board, top-150 weighted {lo[1]:+.2f}%  rank rho {rho(lo[0], base) - rho0:+.4f}  | picks {lo[4]}")
        P(f"    FORWARD 2022-25       touched rows {fw[2]:+.2f}%  seasons better {fw[3]}/{fw[5]}  | whole board, top-150 weighted {fw[1]:+.2f}%  | picks {fw[4]}")
        P(f"    -> {'PASS: ' + str(best) if ok else 'FAIL'}")
        if ok and key: PASS[key] = (best, fam[best])
        return ok
    mult = lambda m, k: np.where(m, SH * k, SH)

    # ---------------- 1 backup quarterback ----------------
    P("\n--- 1 BACKUP QUARTERBACK (a quarterback playing while the team's regular one is out) ---")
    lvl = np.full(n, np.nan); team = X["team"]; fill = np.zeros(n, bool)
    byteam = defaultdict(list)
    for i in np.where(pos == "QB")[0]: byteam[(int(year[i]), team[i])].append(i)
    for (y, t), ix in byteam.items():
        names_ = defaultdict(int)
        for i in ix: names_[X["name"][i]] += 1
        main_qb = max(names_, key=names_.get)
        if names_[main_qb] < 4: continue
        rows_m = sorted([i for i in ix if X["name"][i] == main_qb], key=lambda i: wk[i]); wk_m = {int(wk[i]) for i in rows_m}
        for i in ix:
            if X["name"][i] == main_qb or int(wk[i]) in wk_m or not allr[i]: continue
            prev = [j for j in rows_m if wk[j] < wk[i]]
            ref = (SH[prev[-1]] / X["layers"][prev[-1]]) if prev else X["prior"][rows_m[0]]
            lvl[i] = 0.85 * ref * X["layers"][i]; fill[i] = True
    fm = fill & ~np.isnan(lvl)
    if fm.sum() >= 40:
        own = SH; inh = np.where(fm, lvl, SH)
        alts = {"his own number (harness)": own, "starter's x .85": inh, "the larger of the two": np.where(fm, np.maximum(own, inh), SH), "the average": np.where(fm, (own + inh) / 2, SH),
                "the smaller": np.where(fm, np.minimum(own, inh), SH), "BOTH ADDED (live engine today)": np.where(fm, own + inh, SH)}
        P(f"  fill-in starts with a known regular starter: {int(fm.sum())}; actual {act[fm].mean():.2f} a game")
        for k, p in alts.items():
            w = sum(1 for y in YEARS if (fm & (year == y)).sum() >= 4 and ms(p, fm & (year == y)) < ms(own, fm & (year == y)) - 1e-12); ny = sum(1 for y in YEARS if (fm & (year == y)).sum() >= 4)
            P(f"    {k:34s} predicts {p[fm].mean():5.2f}  typical miss {np.sqrt(ms(p, fm)):.2f}  error vs his own number {100*(ms(p, fm)/ms(own, fm)-1):+.1f}%  seasons better {w}/{ny}")
        hi = fm & (own >= 10)
        P(f"    fill-ins with a real number of their own (10+): n {int(hi.sum())}, actual {act[hi].mean():.2f}, own {own[hi].mean():.2f}, starter x .85 {inh[hi].mean():.2f}, added {(own+inh)[hi].mean():.2f}")

    # ---------------- 2 usage level ----------------
    P("\n--- 2 USAGE LEVEL ---")
    te = pos == "TE"
    fam = {"0 (shipped)": SH}
    for l in (0.25, 0.5, 0.75): fam[f"TE xFP weight {l}"] = shadow(X, np.where(te, l, np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))))
    fam["TE xFP like WR (1 fading to .25)"] = shadow(X, np.where(te | (pos == "WR"), np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0)))
    test("2a tight-end usage evidence", fam, "te_xfp")
    def level_family(col, positions, grid, label):
        v = X[col]; dev = np.zeros(n)
        for ps in positions:
            m = (pos == ps) & (g >= 1) & ~np.isnan(v) & allr
            if m.sum() < 200: continue
            q = np.quantile(SH[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, SH, side="right") - 1, 0, 7)
            for k in range(8):
                mk = m & (b_ == k)
                if mk.sum() >= 30: dev[mk] = v[mk] - np.nanmean(v[mk])
        scale = 100.0 if np.nanmax(np.abs(v)) > 2 else 1.0
        return {"0 (shipped)": SH, **{f"{label} e={e}": SH * np.clip(1 + e * dev / scale, 0.7, 1.4) for e in grid}}
    test("2b snap-share LEVEL, WR + TE (last game vs players at the same projection)", level_family("snap_l1", ("WR", "TE"), (0.15, 0.3, 0.5, 0.75), "snap level"), "snap_lvl")
    test("2b' snap-share level, TE only", level_family("snap_l1", ("TE",), (0.15, 0.3, 0.5, 0.75), "snap level"), "snap_lvl_te")
    test("2c target-share LEVEL, WR + TE", level_family("tgt_sh", ("WR", "TE"), (0.5, 1.0, 1.5, 2.5), "target level"), "tgt_lvl")
    test("2c' target-share level, TE only", level_family("tgt_sh", ("TE",), (0.5, 1.0, 1.5, 2.5), "target level"), "tgt_lvl_te")

    # ---------------- 3 quarterbacks ----------------
    P("\n--- 3 QUARTERBACKS ---")
    qb = pos == "QB"; base_lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    test("3a QB usage / rushing evidence (xFP blend)", {"0 (shipped)": SH, **{f"QB xFP weight {l}": shadow(X, np.where(qb, l, base_lam)) for l in (0.15, 0.3, 0.5, 0.75)}}, "qb_xfp")
    test("3b QB who changed teams", {"1.00 (shipped)": SH, **{f"x{k}": mult(qb & X["mover"], k) for k in (0.97, 0.94, 0.90, 0.86)}}, "qb_mover")
    test("3c QB with no ADP", {"1.00 (shipped)": SH, **{f"x{k}": mult(qb & (np.isnan(adp) | (adp > 180)), k) for k in (0.97, 0.94, 0.90, 0.86)}}, "qb_noadp")
    low = np.maximum(0, 19 - np.nan_to_num(X["implied"], nan=19)) / 19
    test("3d team implied under 19: QB", {"0 (shipped)": SH, **{f"e={e}": np.where(qb, SH * (1 - e * low), SH) for e in (0.25, 0.5, 0.75, 1.0)}}, "low_qb")
    test("3d' team implied under 19: WR", {"0 (shipped)": SH, **{f"e={e}": np.where(pos == "WR", SH * (1 - e * low), SH) for e in (0.25, 0.5, 0.75, 1.0)}}, "low_wr")

    # ---------------- 4 receivers / backs ----------------
    P("\n--- 4 RECEIVERS AND BACKS ---")
    wr = pos == "WR"
    def lamwr(l0, sl, fl=0.25): return np.where(wr, np.maximum(fl, l0 - sl * np.maximum(g - 1, 0)), base_lam)
    test("4a WR evidence mix (usage weight: start, fade per game)", {"1.0 fading .08 (shipped)": SH, "0.75 fading .08": shadow(X, lamwr(.75, .08)), "0.5 fading .05": shadow(X, lamwr(.5, .05)), "flat 0.25": shadow(X, lamwr(.25, 0)), "1.0 fading .15": shadow(X, lamwr(1, .15)), "0 (points only)": shadow(X, lamwr(0, 0, 0))}, "wr_lam")
    lowv = wr & (g >= 2) & (X["tgt_sh"] < 0.12)
    test("4b WR under 12% of targets", {"1.00 (shipped)": SH, **{f"x{k}": mult(lowv, k) for k in (0.95, 0.90, 0.85, 0.80)}}, "wr_lowvol")
    test("4c rookie WR, games 2-5", {"1.00 (shipped)": SH, **{f"x{k}": mult(wr & X["rookie"] & (g >= 2) & (g <= 5), k) for k in (0.95, 0.90, 0.85)}}, "wr_rookie")
    test("4d WR target share trending up (last three +4 points)", {"1.00 (shipped)": SH, **{f"x{k}": mult(wr & (X["tgt_trend"] >= 0.04), k) for k in (1.03, 1.06, 1.09)}}, "wr_trend")
    test("4e RB under 30% of carries, games 2-5", {"1.00 (shipped)": SH, **{f"x{k}": mult((pos == "RB") & (g >= 2) & (g <= 5) & (X["car_sh"] < 0.30), k) for k in (0.95, 0.90, 0.85)}}, "rb_lowcar")

    # ---------------- 5 team shift ----------------
    P("\n--- 5 TEAM SHIFT (this season's lines vs the preseason view, known before kickoff) ---")
    L = {Y: FT.long(FT.load_year(Y)) for Y in range(2018, 2026)}; sh_map = {}
    for Y in YEARS:
        cur, prev = L[Y], L[Y - 1]; teams = sorted(set(cur.team))
        tr = pd.concat([prev[prev.wk >= 10].assign(w=0.35), cur[cur.wk == 1].assign(w=1.0)], ignore_index=True); tr = tr[tr.team.isin(teams) & tr.opp.isin(teams)]
        m_ = FT.ridge_od(tr, tr.imp.values, tr.w.values, teams, 1.5)
        cur = cur.copy(); cur["p0"] = FT.predict(m_, cur) + (cur[cur.wk == 1].imp.mean() - FT.predict(m_, cur[cur.wk == 1]).mean()); cur["d"] = cur.imp - cur.p0
        for t, x in cur.groupby("team"):
            x = x.sort_values("wk"); ws, ds = x.wk.values, x.d.values
            for i_, w_ in enumerate(ws):
                past = ds[:i_ + 1][ws[:i_ + 1] >= 2]                      # lines through this week (it is posted before kickoff)
                if len(past): sh_map[(Y, t, int(w_))] = float(np.average(past, weights=0.5 ** ((w_ - ws[:i_ + 1][ws[:i_ + 1] >= 2]) / 2.0)))
    shift = np.array([sh_map.get((int(year[i]), FT.tm(str(X["team"][i])), int(wk[i])), 0.0) for i in range(n)]) / 22.0
    for lab, pm in (("all positions", np.ones(n, bool)), ("QB + WR + TE", pos != "RB"), ("RB", pos == "RB"), ("all positions, games 1-5 only", g <= 5)):
        test(f"5 team shift -> {lab}", {"0 (shipped)": SH, **{f"e={e}": np.where(pm, SH * np.clip(1 + e * shift, 0.8, 1.25), SH) for e in (0.15, 0.3, 0.5, 0.75)}}, "shift_" + lab[:6])

    # ---------------- combined ----------------
    if PASS:
        P("\n=== COMBINED: every layer that passed, stacked (each at its all-seasons setting) ===")
        comb = SH.copy()
        for k, (best, p) in PASS.items(): comb = comb * np.where(SH > 0, p / np.maximum(SH, 1e-9), 1.0)
        wins = sum(wm(comb, base & (year == y)) < wm(SH, base & (year == y)) for y in YEARS)
        P("  layers: " + "; ".join(f"{k} = {b}" for k, (b, _) in PASS.items()))
        P(f"  top-150 weighted {100*(wm(comb, base)/wm(SH, base)-1):+.2f}% ({wins}/7 seasons)   all rows {100*(ms(comb, allr)/ms(SH, allr)-1):+.2f}%   rank rho {rho(comb, base):.4f} vs {rho0:.4f}")
        for lab, cm in (("QB", pos == "QB"), ("RB", pos == "RB"), ("WR", pos == "WR"), ("TE", pos == "TE"), ("ADP 1-30", adp <= 30), ("ADP 31-60", (adp > 30) & (adp <= 60)), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150", (adp > 100) & (adp <= 150)),
                        ("games 1-5", g <= 5), ("games 6+", g >= 6)):
            m = base & cm; w = sum(wm(comb, m & (year == y)) < wm(SH, m & (year == y)) for y in YEARS)
            P(f"    {lab:12s} {100*(wm(comb, m)/wm(SH, m)-1):+.2f}% ({w}/7)")
    else:
        P("\n=== nothing passed the bar ===")
    log.close()

if __name__ == "__main__":
    main()
