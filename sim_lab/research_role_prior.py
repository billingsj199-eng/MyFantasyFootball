#!/usr/bin/env python3
"""
ADP IN SEASON + ROLE PRIOR (Jack 2026-10-20: "now that we are 6 weeks in does adp have any value I feel like it should be removed by
now" / "is there a way to add the real role that adp covers through 6 weeks" / "does it filter out injury reasoning or outside
reasoning based on news?"). RESEARCH ONLY - nothing here touches engine.js.

Harness = backtest_no_adp.py's rest-of-season copy of the wired shadow (full()), extended to checkpoints after 2-10 games, plus a
next-game horizon (current-week chain: usage + Vegas-cleaned evidence + ridge mix + RB snap trend; later-week-only pieces off).
Data: _tmp/X_cache.pkl (SN.setup + ridge twins, _tmp/cache_setup.py) and _tmp/role_games.pkl (research_role_prior_build.py).

  Q1  the 10-10 no-ADP variants (A no market blend, B + ridge without ADP, C ADP-band prior weights off, D = B + C, E = no ADP
      anywhere) split by games played at the checkpoint: 2-3 / 4-5 / 6-7 / 8-10, rest of season + next game.
  Q2  ROLE PRIOR: at each checkpoint the prior is refit from this season's role so far (games BEFORE the checkpoint only) as ridge
      features beside the ADP-free preseason prior, per position x checkpoint bucket. Fit END-TO-END through the shadow blend
      (rate = (P x prior + g x evidence) / (P + g)): the ridge target is the prior that would have made the blended number hit the
      rest-of-season rate, weighted by (P / (P + g) x context)^2, so the role already inside the evidence (xFP) is not double
      counted. Variants:
        a   raw shares, every game (ctx_features style)
        b   CLEANED: injury exits + post-injury ramp games dropped; snap / route / target / carry shares on competitive plays
            (garbage = Q4 |diff| >= 17 or Q3 >= 28); fill-in games (a regular teammate at his position, Clay level >= 5 and
            >= 1.1x his, missing) left out unless that regular is absent at the checkpoint; games with a different QB than the
            one expected to start left out (2+ games kept)
        bc  b + RB share of the backfield (RB carries + RB targets) at full strength vs depleted, matched to the checkpoint room
        bA  b + log ADP   bW  b on top of the WIRED prior (ADP stays through the market blend)   bch  b + depth string at checkpoint
      each with prior weight P x {1, .75, .5, .33}; ADP-band prior weights off (they are ADP) unless named.
Log role_prior.log (ROS_MINF=1 -> role_prior_minf1.log).
"""
import os, sys, pickle
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
YEARS = list(range(2019, 2026)); FWD = (2022, 2023, 2024, 2025); POS4 = ("QB", "RB", "WR", "TE")
MINF = int(os.environ.get("ROS_MINF", "4"))
BUCKETS = (("2-3", 2, 3), ("4-5", 4, 5), ("6-7", 6, 7), ("8-10", 8, 10))
PSCALES = tuple(float(x) for x in os.environ.get("ROLE_PS", "1.0,0.75,0.5,0.33").split(","))
ABSENT_ROSTER = {"RES", "CUT", "DEV", "RET", "EXE", "PUP", "NFI", "SUS", "TRC", "TRD", "TRT"}


def main():
    LOGP = os.path.join(HERE, ("role_prior_diag_" + os.environ["ROLE_DIAG"].replace(",", "_")[:40] + "_a" + os.environ.get("ROLE_ALPHA", "10") + ".log") if os.environ.get("ROLE_DIAG") else ("role_prior.log" if MINF != 1 else "role_prior_minf1.log"))
    log = open(LOGP, "w", encoding="utf-8")
    def P(s=""): print(s, flush=True); log.write(s + "\n"); log.flush()
    X = pickle.load(open(os.path.join(HERE, "_tmp", "X_cache.pkl"), "rb"))
    n = X["n"]; F = X["F"]; A = X["A"]
    act, year, wk, pos, g, name, adp, layers, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["name"], X["adp"], X["layers"], X["team"]
    pid = A["pid"]; finw = np.where(year <= 2020, 17, 18)
    seq = defaultdict(list)
    for i in range(n):
        if wk[i] != finw[i]: seq[(name[i], pos[i], int(year[i]))].append(i)
    T = np.full(n, np.nan); ctx = np.full(n, np.nan)
    for ix in seq.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(layers[ix], 0.5, 1.8)
        for a, i in enumerate(ix):
            if len(ix) - a >= MINF: T[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    lay = np.clip(layers, 0.5, 1.8)
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    colv = lambda c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    bl = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    strb = F["strb"]; y2 = colv("yr2") == 1
    band = {"ADP 61-100": (adp > 60) & (adp <= 100), "ADP 101-150": (adp > 100) & (adp <= 150)}
    t36 = (pos == "TE") & (adp > 30) & (adp <= 60)
    sm = colv("snapmult"); sm = np.where(np.isnan(sm), 1.0, sm); l1 = colv("snap_l1")
    R00 = (X["Pw"] * X["prior"] + g * (bl * X["xf"] + (1 - bl) * X["ppg_v"])) / (X["Pw"] + g)
    base_ok = ~np.isnan(T) & (g >= 2) & (g <= 10) & (R00 * ctx >= 3)
    def z_of(v, m):
        out = np.zeros(n); mm = m & base_ok & ~np.isnan(v); ap = m & ~np.isnan(v)
        if mm.sum() > 50: out[ap] = np.clip((v[ap] - v[mm].mean()) / v[mm].std(), -2, 2)
        return out
    dev = np.zeros(n)
    for ps in ("WR", "TE"):
        m = base_ok & (pos == ps) & ~np.isnan(l1); q = np.quantile(R00[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, R00, side="right") - 1, 0, 7)
        for k in range(8):
            mk = m & (b_ == k)
            if mk.sum() >= 30: dev[mk] = l1[mk] - l1[mk].mean()
    zp = z_of(colv("proe_std"), pos == "TE"); zpl = z_of(colv("plays_pg_std"), pos == "RB")
    BANDW = ("RB 61-100 prior weight x2.5", "WR 61-100 prior weight x0.6", "WR 101-150 cold prior weight x0.4")
    GATES = ("WR 101-150 usage cap .25", "TE 31-60 x1.10", "RB backup (top 150) x1.04")
    LATER = BANDW + GATES + ("second-year QB prior weight x0.75", "QB changed teams x.84", "TE snap-share level e .3", "TE team pass-rate tilt e .04", "RB team play-volume tilt e .04")
    later3 = g >= 3   # the struct pieces need 3+ games (engine)

    def parts(prior, off=(), ps=1.0):
        """-> Pw, ev, mult for the wired chain with pieces in `off` removed; ps = prior-weight scale (array or float)"""
        on = lambda k: k not in off
        lam_ = bl.copy()
        if on("WR 101-150 usage cap .25"): lam_ = np.where((pos == "WR") & band["ADP 101-150"] & later3, np.minimum(lam_, 0.25), lam_)
        ev = lam_ * X["xf"] + (1 - lam_) * X["ppg_v"]
        pm_ = np.ones(n)
        if on("RB 61-100 prior weight x2.5"): pm_ = np.where((pos == "RB") & band["ADP 61-100"] & later3, 2.5, pm_)
        if on("WR 61-100 prior weight x0.6"): pm_ = np.where((pos == "WR") & band["ADP 61-100"] & later3, 0.6, pm_)
        if on("second-year QB prior weight x0.75"): pm_ = np.where((pos == "QB") & y2 & later3, 0.75, pm_)
        if on("WR 101-150 cold prior weight x0.4"): pm_ = np.where((pos == "WR") & band["ADP 101-150"] & (ev < prior) & later3, pm_ * 0.4, pm_)
        Pw = X["Pw"] * pm_ * ps
        mu = np.ones(n)
        mu = np.where(pos == "RB", mu * sm, mu)
        if on("QB changed teams x.84"): mu = np.where((pos == "QB") & X["mover"], mu * 0.84, mu)
        if on("TE snap-share level e .3"): mu = np.where((pos == "TE") & ~np.isnan(l1), mu * np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4), mu)
        if on("TE team pass-rate tilt e .04"): mu = np.where(pos == "TE", mu * (1 - 0.04 * zp), mu)
        if on("TE 31-60 x1.10"): mu = np.where(t36 & later3, mu * 1.10, mu)
        if on("RB team play-volume tilt e .04"): mu = np.where(pos == "RB", mu * np.clip(1 - 0.04 * zpl, 0.8, 1.25), mu)
        if on("RB backup (top 150) x1.04"): mu = np.where((pos == "RB") & (strb >= 2) & (adp <= 150) & later3, mu * 1.04, mu)
        return Pw, ev, mu
    blend = lambda Pw, ev, pr: (Pw * pr + g * ev) / np.maximum(Pw + g, 1e-9)
    def ros(prior, off=(), ps=1.0):
        Pw, ev, mu = parts(prior, off, ps); return blend(Pw, ev, prior) * mu * ctx
    def nxt(prior, ps=1.0):
        Pw, ev, mu = parts(prior, LATER, ps); return blend(Pw, ev, prior) * mu * lay

    WPRIOR = X["prior"]
    FULL = ros(WPRIOR); FULLN = nxt(WPRIOR)
    ok = base_ok & (FULL >= 3)
    okN = (g >= 2) & (g <= 10) & (wk != finw) & (FULLN >= 3)
    P(f"=== ROLE PRIOR / ADP IN SEASON: {int(ok.sum()):,} rest-of-season checkpoints (2-10 games played, {MINF}+ games left), {int((ok & top150).sum()):,} top-150; next game rows {int(okN.sum()):,} ===")

    # ---------------- grading helpers ----------------
    def gr(Q, B_, m, tgt):
        """error %, MAE %, top-150 weighted %, rank delta, seasons better (LOYO 7 / fwd 4)"""
        e = lambda q, mm: float(np.mean((q[mm] - tgt[mm]) ** 2)); a_ = lambda q, mm: float(np.mean(np.abs(q[mm] - tgt[mm])))
        w_ = lambda q, mm: float(np.average((q[mm] - tgt[mm]) ** 2, weights=wt[mm]))
        if m.sum() < 30: return None
        s7 = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and e(Q, m & (year == y)) < e(B_, m & (year == y)) - 1e-12)
        s4 = sum(1 for y in FWD if (m & (year == y)).sum() >= 8 and e(Q, m & (year == y)) < e(B_, m & (year == y)) - 1e-12)
        mt = m & top150
        return dict(n=int(m.sum()), err=100 * (e(Q, m) / e(B_, m) - 1), mae=100 * (a_(Q, m) / a_(B_, m) - 1),
                    w=100 * (w_(Q, mt) / w_(B_, mt) - 1) if mt.sum() > 20 else np.nan, rk=rho(Q, mt, tgt) - rho(B_, mt, tgt), s7=s7, s4=s4)
    def rho(q, m, tgt):
        grp = defaultdict(list)
        for i in np.where(m)[0]: grp[(int(year[i]), int(wk[i]), pos[i])].append(i)
        rh = [np.corrcoef(rankdata(tgt[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in grp.values()) if len(ix) >= 8]
        return float(np.mean(rh)) if rh else np.nan
    fmt = lambda r: "n/a" if r is None else f"n {r['n']:5d} err {r['err']:+6.2f}% ({r['s7']}/7, fwd {r['s4']}/4) MAE {r['mae']:+6.2f}% top150-w {r['w']:+6.2f}% rank {r['rk']:+.4f}"
    BK = [(lab, (g >= lo) & (g <= hi)) for lab, lo, hi in BUCKETS]

    # ---------------- Q1 no-ADP variants by checkpoint ----------------
    P("\n--- Q1  the 10-10 no-ADP variants by games played at the checkpoint (vs the wired shadow; negative = better than wired) ---")
    import backtest_season_long as SL_  # noqa (ridge twins are cached)
    yr2a = A["exp"] == 1; fb = F["fb_pos"]; ac = F["adp_curve"]; mk = F["mkt_ok"]; late_ = F["late"]
    mdock = np.ones(n)
    for ps_, d_ in SN.CS.NC.VETDOCK.items():
        for sb_, mm_ in d_.items(): mdock = np.where((pos == ps_) & (strb == sb_), mdock * mm_, mdock)
    mdock = np.where(yr2a & ~np.isnan(late_) & (late_ < 0.4), mdock * 1.2, mdock)
    wv = np.where(yr2a, 0.5, 0.75); prm = (F["prior"] - fb) / 0.8 + fb
    hm = np.where(mk, (prm - mdock * wv * np.nan_to_num(ac)) / (1 - wv), prm)
    prior_nomkt = np.where(mk, fb + 0.8 * (hm - fb), F["prior"])
    mix = lambda rg, pr: np.where(np.isnan(rg) | (pos == "QB"), pr, 0.5 * rg + 0.5 * pr)
    P(f"  check: rebuilt ridge mix matches the wired prior on {100*np.mean(np.isclose(mix(X['r_adp'], F['prior']), WPRIOR, equal_nan=True)):.1f}% of rows")
    PRA = mix(X["r_adp"], prior_nomkt); PRB = mix(X["r_no"], prior_nomkt)
    V1 = [("A  no market blend", PRA, ()), ("B  A + ridge without ADP", PRB, ()), ("C  ADP-band prior weights off", WPRIOR, BANDW),
          ("D  B + C", PRB, BANDW), ("E  D + ADP-gated tweaks off (no ADP anywhere)", PRB, BANDW + GATES)]
    for lab, pr_, off_ in (V1 if not os.environ.get("ROLE_DIAG") else []):
        Q = ros(pr_, off_); QN = nxt(pr_)
        P(f"\n  {lab}")
        for bl_, bm in [("all 2-10", np.ones(n, bool))] + BK:
            P(f"    ROS  {bl_:8s} " + fmt(gr(Q, FULL, ok & bm, T)))
        for ps in POS4:
            P(f"    ROS  {ps} " + " | ".join(f"{bl_} {r['err']:+.2f}% ({r['s7']}/7)" for bl_, bm in BK for r in [gr(Q, FULL, ok & bm & (pos == ps), T)] if r))
        for bl_, bm in [("all 2-10", np.ones(n, bool))] + BK:
            P(f"    NEXT {bl_:8s} " + fmt(gr(QN, FULLN, okN & bm, act)))

    # ---------------- role features ----------------
    RG = pickle.load(open(os.path.join(HERE, "_tmp", "role_games.pkl"), "rb"))
    pg = RG["pg"].rename(columns={"year_x": "year"}); tg = RG["tg"]; INJ, ROS_, HAVE = RG["inj"], RG["ros"], RG["ros_have"]
    PGD = {(int(r.year), r.pid, int(r.wk)): r for r in pg.itertuples(index=False)}
    TGD = {(int(r.year), r.team, int(r.wk)): r for r in tg.itertuples(index=False)}
    tweeks = defaultdict(list)
    for (Y_, t_, w_) in TGD: tweeks[(Y_, t_)].append(w_)
    for k in tweeks: tweeks[k].sort()
    # player-season game lists (harness weeks = games played) + Clay level (fill-in regulars)
    games_of = defaultdict(list); clay_of = {}; room = defaultdict(set)
    for i in range(n):
        k = (int(year[i]), pid[i]); games_of[k].append(int(wk[i]))
        if k not in clay_of: clay_of[k] = float(A["clay"][i]) if not np.isnan(A["clay"][i]) else 0.0
        room[(int(year[i]), team[i], pos[i])].add(pid[i])
    for k in games_of: games_of[k] = sorted(set(games_of[k]))
    def absent_at(Y_, t_, w_, q):
        rs_ = INJ.get((Y_, t_, w_, q), ("", ""))[0]; rst = ROS_.get((Y_, t_, w_, q))
        return rs_ in ("Out", "Doubtful") or (rst in ABSENT_ROSTER) or ((Y_, t_, w_) in HAVE and rst is None)
    def listed_at(Y_, t_, w_, q):
        r_, p_ = INJ.get((Y_, t_, w_, q), ("", ""))
        return r_ in ("Questionable", "Doubtful", "Out") or ("Did Not" in str(p_)) or ("Limited" in str(p_))
    def played(Y_, q, w_): return w_ in set(games_of.get((Y_, q), ()))
    gset = {k: set(v) for k, v in games_of.items()}
    RAW = ("tgt_sh", "car_sh", "rz_tgt_sh", "rz_car_sh", "gl_car_sh", "ay_sh", "xfp_pg", "snap", "route", "db_sh", "att_pg", "car_pg")
    FA = {k: np.full(n, np.nan) for k in RAW}; FB = {k: np.full(n, np.nan) for k in RAW + ("n_kept", "x_exit", "x_fill", "x_qb", "room_sh")}
    stats = defaultdict(int)
    def shares(gl, Y_, comp):
        s = "_c" if comp else ""; pt = defaultdict(float); tt = defaultdict(float); sn = []; ng = 0
        for (w_, t_) in gl:
            r = PGD.get((Y_, PID, w_)); q = TGD.get((Y_, t_, w_))
            if r is None or q is None: continue
            ng += 1
            for c in ("tg", "car", "rz_tg", "rz_car", "gl_car", "ay", "db"):
                pt[c] += getattr(r, c + s); tt[c] += getattr(q, c + s)
            pt["xfp"] += r.xfp; pt["att"] += r.att; pt["carq"] += r.car
            pt["ondb"] += getattr(r, "ondb" + s); tt["pdb"] += getattr(q, "pdb" + s)
            if comp:
                if q.ppl_c > 0: sn.append(100.0 * r.on_c / q.ppl_c)
            else:
                sp = r.snap_pct if not (isinstance(r.snap_pct, float) and np.isnan(r.snap_pct)) else (100.0 * r.on / q.ppl if q.ppl else np.nan)
                if not np.isnan(sp): sn.append(sp)
        if ng == 0: return None
        d = lambda a, b: pt[a] / tt[b] if tt[b] > 0 else np.nan
        return {"tgt_sh": d("tg", "tg"), "car_sh": d("car", "car"), "rz_tgt_sh": d("rz_tg", "rz_tg"), "rz_car_sh": d("rz_car", "rz_car"), "gl_car_sh": d("gl_car", "gl_car"),
                "ay_sh": d("ay", "ay"), "xfp_pg": pt["xfp"] / ng, "snap": float(np.mean(sn)) if sn else np.nan, "route": d("ondb", "pdb"), "db_sh": d("db", "db"),
                "att_pg": pt["att"] / ng, "car_pg": pt["carq"] / ng}
    for i in range(n):
        if g[i] < 1 or not pid[i]: continue
        Y_ = int(year[i]); PID = pid[i]; t0 = team[i]; W = int(wk[i]); p_ = pos[i]
        gl_all = []
        for w_ in games_of[(Y_, PID)]:
            if w_ >= W: break
            r = PGD.get((Y_, PID, w_)); gl_all.append((w_, r.team if r is not None else t0))
        if not gl_all: continue
        gl_tm = [x for x in gl_all if x[1] == t0] or gl_all
        ra = shares(gl_tm, Y_, False)
        if ra:
            for k in RAW: FA[k][i] = ra[k]
        # ---- cleaned ----
        snaps = []
        for (w_, t_) in gl_tm:
            r = PGD.get((Y_, PID, w_)); q = TGD.get((Y_, t_, w_))
            sp = np.nan
            if r is not None:
                sp = r.snap_pct if not (isinstance(r.snap_pct, float) and np.isnan(r.snap_pct)) else (100.0 * r.on / q.ppl if q is not None and q.ppl else np.nan)
            snaps.append(sp)
        keep = []; nx = nf = nq = 0
        for j, (w_, t_) in enumerate(gl_tm):
            prev = [s for s in snaps[:j] if not np.isnan(s)]; pm_ = float(np.mean(prev)) if prev else np.nan; sj = snaps[j]
            tw_ = tweeks[(Y_, t_)]; after = [x for x in tw_ if x > w_]; nxt_w = after[0] if after else None
            exit_ = False
            if not np.isnan(pm_) and pm_ >= 50 and not np.isnan(sj) and sj < 0.6 * pm_ and nxt_w is not None and nxt_w <= W:
                missed_next = nxt_w < W and not played(Y_, PID, nxt_w)
                exit_ = listed_at(Y_, t_, nxt_w, PID) or missed_next
            ramp = False
            if j > 0 and not np.isnan(pm_) and not np.isnan(sj) and sj < 0.85 * pm_:
                pw_ = gl_tm[j - 1][0]; between = [x for x in tw_ if pw_ < x < w_]
                ramp = len(between) >= 2
            if exit_ or ramp: nx += 1; continue
            keep.append((w_, t_))
        if not keep: keep = list(gl_tm)
        # fill-in: regular same-position teammates (Clay >= 5 and >= 1.1x mine) missing that week
        mine = clay_of.get((Y_, PID), 0.0)
        regs = [q for q in room.get((Y_, t0, p_), ()) if q != PID and clay_of.get((Y_, q), 0.0) >= 5.0 and clay_of.get((Y_, q), 0.0) > 1.1 * mine]
        if regs and p_ in ("RB", "WR", "TE"):
            fi = [(w_, t_) for (w_, t_) in keep if any(w_ not in gset.get((Y_, q), ()) for q in regs)]
            out_now = any(absent_at(Y_, t0, W, q) for q in regs)
            if fi and not out_now:
                rest = [x for x in keep if x not in fi]
                if rest: keep = rest; nf = len(fi)
        # QB expected to start: QB of the team's latest game unless absent now, else the team's most frequent game QB not absent
        if p_ in ("RB", "WR", "TE"):
            tw_ = [x for x in tweeks[(Y_, t0)] if x < W]
            gq = [TGD[(Y_, t0, x)].qb for x in tw_ if TGD[(Y_, t0, x)].qb]
            exp_qb = None
            if gq:
                exp_qb = gq[-1]
                if absent_at(Y_, t0, W, exp_qb):
                    cand = [q for q in gq if not absent_at(Y_, t0, W, q)]
                    exp_qb = max(set(cand), key=cand.count) if cand else None
            if exp_qb:
                same = [x for x in keep if TGD.get((Y_, x[1], x[0])) is not None and TGD[(Y_, x[1], x[0])].qb == exp_qb]
                if len(same) >= 2 and len(same) < len(keep): nq = len(keep) - len(same); keep = same
        rb = shares(keep, Y_, True)
        if rb:
            for k in RAW: FB[k][i] = rb[k]
        FB["n_kept"][i] = len(keep); FB["x_exit"][i] = nx; FB["x_fill"][i] = nf; FB["x_qb"][i] = nq
        stats["rows"] += 1; stats["exit"] += nx > 0; stats["fill"] += nf > 0; stats["qb"] += nq > 0
        # RB backfield share, full strength vs depleted (any other RB with Clay >= 5 missing)
        if p_ == "RB":
            others = [q for q in room.get((Y_, t0, "RB"), ()) if q != PID and clay_of.get((Y_, q), 0.0) >= 5.0]
            full_, depl = [0.0, 0.0], [0.0, 0.0]
            for (w_, t_) in keep:
                r = PGD.get((Y_, PID, w_)); q = TGD.get((Y_, t_, w_))
                if r is None or q is None or q.room_RB_c <= 0: continue
                v = [r.car_c + r.tg_c, q.room_RB_c]
                tgt_ = depl if any(w_ not in gset.get((Y_, o), ()) for o in others) else full_
                tgt_[0] += v[0]; tgt_[1] += v[1]
            now_depl = any(absent_at(Y_, t0, W, o) for o in others)
            sh_f = full_[0] / full_[1] if full_[1] > 0 else np.nan; sh_d = depl[0] / depl[1] if depl[1] > 0 else np.nan
            FB["room_sh"][i] = (sh_d if now_depl and not np.isnan(sh_d) else sh_f if not np.isnan(sh_f) else sh_d)
            stats["rb_depl_now"] += now_depl
    P(f"\n--- role features built: {stats['rows']:,} rows; rows with an injury-exit / ramp game dropped {stats['exit']:,}, fill-in games dropped {stats['fill']:,}, other-QB games dropped {stats['qb']:,}, RB rooms depleted now {stats['rb_depl_now']:,} ---")
    for k in ("tgt_sh", "car_sh", "snap", "route", "xfp_pg"):
        for ps in ("RB", "WR", "TE"):
            m = ok & (pos == ps) & ~np.isnan(FA[k]) & ~np.isnan(FB[k])
            if m.sum() > 50: P(f"    {ps} {k:8s} raw {np.mean(FA[k][m]):.3f} clean {np.mean(FB[k][m]):.3f}  corr {np.corrcoef(FA[k][m], FB[k][m])[0,1]:.3f}  |diff| {np.mean(np.abs(FA[k][m]-FB[k][m])):.3f}")
    # leak check vs ctx_features (same games-before-week definition): raw target share should match closely
    cm = ok & ~np.isnan(FA["tgt_sh"]) & ~np.isnan(colv("tgt_sh"))
    P(f"    leak check: raw tgt_sh vs ctx_features tgt_sh corr {np.corrcoef(FA['tgt_sh'][cm], colv('tgt_sh')[cm])[0,1]:.4f}, mean abs diff {np.mean(np.abs(FA['tgt_sh'][cm]-colv('tgt_sh')[cm])):.4f}")

    # ---------------- Q2 role prior ----------------
    POSF = {"QB": ("db_sh", "att_pg", "car_pg", "rz_car_sh", "xfp_pg", "snap"),
            "RB": ("car_sh", "tgt_sh", "rz_car_sh", "gl_car_sh", "rz_tgt_sh", "xfp_pg", "snap", "route"),
            "WR": ("tgt_sh", "ay_sh", "rz_tgt_sh", "xfp_pg", "snap", "route"),
            "TE": ("tgt_sh", "ay_sh", "rz_tgt_sh", "xfp_pg", "snap", "route")}
    ladp = X["T_ladp"]; noadp = X["T_no_adp"]
    chart = np.column_stack([(strb == 1).astype(float), (strb == 2).astype(float), (strb >= 3).astype(float), np.isnan(strb).astype(float)])
    def feats(var, ps):
        var = var.replace("_r", "").replace("_i", "")
        if var == "null": return np.column_stack([PRB]), ["prior"]
        src = FA if var.startswith("a") else FB
        cols = [PRB if var != "bW" else WPRIOR] + [src[k] for k in POSF[ps]]
        names = ["prior"] + list(POSF[ps])
        if var == "bc" and ps == "RB": cols.append(FB["room_sh"]); names.append("room_sh")
        if var == "bA": cols += [ladp, noadp]; names += ["ladp", "no_adp"]
        if var == "bch": cols += [chart[:, j] for j in range(4)]; names += ["str1", "str2", "str3", "nostr"]
        return np.column_stack(cols), names
    from sklearn.linear_model import Ridge
    def fit_apply(Xm, tr, te, ystar, w):
        Xtr = Xm[tr]; med = np.nanmedian(Xtr, axis=0); med = np.where(np.isnan(med), 0, med)
        miss = [j for j in range(Xm.shape[1]) if np.isnan(Xtr[:, j]).mean() > 0.02]
        prep = lambda M: np.column_stack([np.where(np.isnan(M), med, M)] + ([np.isnan(M[:, miss]).astype(float)] if miss else []))
        A_tr = prep(Xtr); mu, sd = A_tr.mean(0), A_tr.std(0); sd[sd == 0] = 1
        mdl = Ridge(alpha=float(os.environ.get("ROLE_ALPHA", "10"))).fit((A_tr - mu) / sd, ystar[tr], sample_weight=w[tr])
        return np.maximum(0.5, mdl.predict((prep(Xm[te]) - mu) / sd)), mdl.coef_[:Xm.shape[1]], mu, sd
    def fit_apply_r(Xm, tr, te, ystar, w):
        Xtr = Xm[tr]; med = np.nanmedian(Xtr, axis=0); med = np.where(np.isnan(med), 0, med)
        miss = [j for j in range(Xm.shape[1]) if np.isnan(Xtr[:, j]).mean() > 0.02]
        prep = lambda M: np.column_stack([np.where(np.isnan(M), med, M)] + ([np.isnan(M[:, miss]).astype(float)] if miss else []))
        A_tr = prep(Xtr); mu, sd = A_tr.mean(0), A_tr.std(0); sd[sd == 0] = 1
        mdl = Ridge(alpha=float(os.environ.get("ROLE_ALPHA", "10"))).fit((A_tr - mu) / sd, ystar[tr], sample_weight=w[tr])
        return mdl.predict((prep(Xm[te]) - mu) / sd)
    def role_prior(var, ps_scale, off, folds):
        """fitted prior for every row (g 1-10) per position x bucket; folds = 'loyo' | 'fwd'"""
        Pw, ev, mu = parts(PRB, off, ps_scale)   # band pieces off -> parts do not depend on the prior
        cm_ = mu * ctx; yr_ = T / np.where(cm_ > 0, cm_, np.nan)
        ystar = ((Pw + g) * yr_ - g * ev) / Pw; w = (cm_ * Pw / (Pw + g)) ** 2
        if var.endswith("_i"): ystar = yr_.copy(); w = cm_ ** 2      # prior fit in isolation (target = rest-of-season rate), P re-tuned
        out = np.full(n, np.nan); resid = var.endswith("_r")
        base_ = WPRIOR if var.startswith("bW") else PRB
        if resid: ystar = ystar - base_
        for ps in POS4:
            Xm, _ = feats(var, ps)
            if resid: Xm = Xm[:, 1:] if Xm.shape[1] > 1 else np.zeros((n, 1))
            for _, lo, hi in BUCKETS:
                cell = (pos == ps) & (g >= lo) & (g <= hi); trn = cell & ok & ~np.isnan(ystar)
                for ty in (YEARS if folds == "loyo" else FWD):
                    tr = trn & ((year != ty) if folds == "loyo" else (year < ty)); te = cell & (year == ty)
                    if tr.sum() < 60 or not te.any(): continue
                    out[te] = fit_apply(Xm, tr, te, ystar, w)[0] if not resid else fit_apply_r(Xm, tr, te, ystar, w)
        if resid: out = np.maximum(0.5, base_ + out)
        return np.where(np.isnan(out), PRB, out)
    def evaluate(var, off=BANDW, label=None):
        """P scale fixed grid + LOYO-picked scale per position; returns LOYO/fwd ROS + next predictions of the picked version"""
        lab = label or var
        loy = {s: role_prior(var, s, off, "loyo") for s in PSCALES}; fw = {s: role_prior(var, s, off, "fwd") for s in PSCALES}
        R = {s: ros(loy[s], off, s) for s in PSCALES}; RF = {s: ros(fw[s], off, s) for s in PSCALES}
        N = {s: nxt(loy[s], s) for s in PSCALES}; NF = {s: nxt(fw[s], s) for s in PSCALES}
        e = lambda q, m: float(np.mean((q[m] - T[m]) ** 2))
        pickL = FULL.copy(); pickF = FULL.copy(); pickN = FULLN.copy(); pickNF = FULLN.copy(); picks = defaultdict(list)
        for ps in POS4:
            for ty in YEARS:
                tr = ok & (pos == ps) & (year != ty); s = min(PSCALES, key=lambda s_: e(R[s_], tr)); picks[ps].append(s)
                sel = (pos == ps) & (year == ty); pickL[sel] = R[s][sel]; pickN[sel] = N[s][sel]
            for ty in FWD:
                tr = ok & (pos == ps) & (year < ty); s = min(PSCALES, key=lambda s_: e(RF[s_], tr))
                sel = (pos == ps) & (year == ty); pickF[sel] = RF[s][sel]; pickNF[sel] = NF[s][sel]
        P(f"\n  [{lab}] P-scale picks (LOYO by season): " + " | ".join(f"{ps} {picks[ps]}" for ps in POS4))
        for s in PSCALES:
            P(f"    fixed P x{s:<4}  ROS " + fmt(gr(R[s], FULL, ok, T)) + f"  || NEXT err {gr(N[s], FULLN, okN, act)['err']:+.2f}% ({gr(N[s], FULLN, okN, act)['s7']}/7)")
        # combine: LOYO rows for 7-season stats; forward-fit rows for the forward column
        def show(QL, QF, m, tgt, base, tag):
            r = gr(QL, base, m, tgt); rf = gr(QF, base, m & np.isin(year, FWD), tgt)
            if r is None: return
            ef = lambda q, mm: float(np.mean((q[mm] - tgt[mm]) ** 2))
            fwd_err = 100 * (ef(QF, m & np.isin(year, FWD)) / ef(base, m & np.isin(year, FWD)) - 1)
            P(f"    {tag:22s} n {r['n']:5d} LOYO err {r['err']:+6.2f}% ({r['s7']}/7)  MAE {r['mae']:+6.2f}%  top150-w {r['w']:+6.2f}%  rank {r['rk']:+.4f}  | FORWARD err {fwd_err:+6.2f}% ({rf['s4']}/4)")
            return r, fwd_err, rf
        res = {}
        P("    picked P, rest of season:")
        res["ros_all"] = show(pickL, pickF, ok, T, FULL, "ROS all 2-10")
        for bl_, bm in BK: res["ros_" + bl_] = show(pickL, pickF, ok & bm, T, FULL, f"ROS after {bl_}")
        for ps in POS4: res["ros_" + ps] = show(pickL, pickF, ok & (pos == ps), T, FULL, f"ROS {ps}")
        res["ros_top150"] = show(pickL, pickF, ok & top150, T, FULL, "ROS top-150")
        P("    level act/pred ROS: " + " ".join(f"{ps} {T[ok & (pos == ps)].sum()/pickL[ok & (pos == ps)].sum():.3f} (wired {T[ok & (pos == ps)].sum()/FULL[ok & (pos == ps)].sum():.3f})" for ps in POS4))
        P("    picked P, next game:")
        res["nx_all"] = show(pickN, pickNF, okN, act, FULLN, "NEXT all 2-10")
        for bl_, bm in BK: res["nx_" + bl_] = show(pickN, pickNF, okN & bm, act, FULLN, f"NEXT after {bl_}")
        for ps in POS4: res["nx_" + ps] = show(pickN, pickNF, okN & (pos == ps), act, FULLN, f"NEXT {ps}")
        return res, pickL, pickN, loy, picks
    P("\n--- Q2  ROLE PRIOR (fit end-to-end through the blend, per position x checkpoint; vs the wired shadow; negative = better) ---")
    RES = {}
    if os.environ.get("ROLE_DIAG"):
        for var in os.environ["ROLE_DIAG"].split(","):
            RES[var] = evaluate(var)
        return
    for var in ("a", "b", "bc", "bA", "bch", "bW"):
        RES[var] = evaluate(var)
    RES["b_bandON"] = evaluate("b", (), "b with ADP-band prior weights ON")

    # ADP coefficient once role is known (clean role + ADP-free prior + log ADP), all seasons, P x1
    P("\n--- Q2a  does ADP's coefficient go to 0 once the role is in the prior? (standardized ridge coef of log ADP, negative = better ADP -> higher prior; vs the prior's own coef) ---")
    Pw, ev, mu = parts(PRB, BANDW, 1.0); cm_ = mu * ctx; yr_ = T / np.where(cm_ > 0, cm_, np.nan)
    ystar = ((Pw + g) * yr_ - g * ev) / Pw; w = (cm_ * Pw / (Pw + g)) ** 2
    for ps in POS4:
        line = []
        for var in ("noRole", "bA"):
            for bl_, lo, hi in BUCKETS:
                cell = (pos == ps) & (g >= lo) & (g <= hi) & ok & ~np.isnan(ystar)
                if var == "noRole": Xm = np.column_stack([PRB, ladp, noadp]); nm_ = ["prior", "ladp", "no_adp"]
                else: Xm, nm_ = feats("bA", ps)
                _, coef, _, _ = fit_apply(Xm, cell, cell, ystar, w)
                line.append(f"{'prior+ADP' if var == 'noRole' else 'prior+role+ADP'} {bl_}: ladp {coef[nm_.index('ladp')]:+.2f} (prior {coef[0]:+.2f})")
        P(f"  {ps}: " + " | ".join(line))
    P("  incremental value of ADP on top of the clean role prior = row [bA] vs [b] above; per bucket:")
    _, pb_, pbn_, _, _ = RES["b"]; _, pa_, pan_, _, _ = RES["bA"]
    for bl_, bm in [("all", np.ones(n, bool))] + BK:
        P(f"    ADP added, {bl_:5s}  ROS " + fmt(gr(pa_, pb_, ok & bm, T)) + "  || NEXT " + fmt(gr(pan_, pbn_, okN & bm, act)))
        for ps in POS4:
            r = gr(pa_, pb_, ok & bm & (pos == ps), T)
            if r: P(f"        {ps}: ROS {r['err']:+.2f}% ({r['s7']}/7) rank {r['rk']:+.4f}")
    _, pa2, pan2, _, _ = RES["a"]
    P("  does cleaning matter? [b] vs [a] (negative = cleaned better):")
    for bl_, bm in [("all", np.ones(n, bool))] + BK:
        P(f"    {bl_:5s} ROS " + fmt(gr(pb_, pa2, ok & bm, T)) + "  || NEXT " + fmt(gr(pbn_, pan2, okN & bm, act)))
    for ps in POS4:
        P(f"    {ps}: ROS " + fmt(gr(pb_, pa2, ok & (pos == ps), T)))
    _, pc_, pcn_, _, _ = RES["bc"]; _, pch_, pchn_, _, _ = RES["bch"]
    P("  RB backfield share full vs depleted [bc] vs [b], RB rows: ROS " + fmt(gr(pc_, pb_, ok & (pos == "RB"), T)) + " || NEXT " + fmt(gr(pcn_, pbn_, okN & (pos == "RB"), act)))
    P("  depth string at the checkpoint [bch] vs [b]: ROS " + fmt(gr(pch_, pb_, ok, T)) + " || NEXT " + fmt(gr(pchn_, pbn_, okN, act)))
    for ps in POS4: P(f"        {ps}: ROS " + fmt(gr(pch_, pb_, ok & (pos == ps), T)))
    pickle.dump({"RES_keys": list(RES), "FULL": FULL, "FULLN": FULLN, "ok": ok, "okN": okN, "preds": {k: (v[1], v[2]) for k, v in RES.items()}, "picks": {k: dict(v[4]) for k, v in RES.items()}},
                open(os.path.join(HERE, "_tmp", f"role_prior_out_minf{MINF}.pkl"), "wb"))
    log.close()


if __name__ == "__main__":
    main()
