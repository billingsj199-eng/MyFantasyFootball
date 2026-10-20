#!/usr/bin/env python3
"""
ADP ONCE USAGE IS LEGIT (Jack 2026-10-20: "we should only be testing the point where usage becomes legit" / "realistically adp
should fade"). RESEARCH ONLY - nothing here touches engine.js.

Same harness as research_role_prior.py (backtest_no_adp full() at 2+ games played, rest of season + next game), same cleaned
games (injury exits + post-injury ramp games out, competitive plays, fill-in games out unless the regular is absent now,
other-QB games out when 2+ remain).

  1  STABILIZATION: split-half reliability (odd vs even clean games, first 2N clean games of a player-season) of the N-game mean
     of target share, carry share, snap share, route share, xFP/g, per position; N where r >= .70
  2  USAGE-LEGIT FLAG per checkpoint: N_pos+ clean games AND last-3 clean snap within +-S pts and last-3 clean share (target share
     WR/TE, carry share RB, dropback share QB) within +-H of his clean season to date. base S 8 / H .04; loose (N-1, 12, .06);
     strict (N+1, 5, .025)
  3  on flagged rows / the complement: B (no market blend + noAdp ridge), E (no ADP anywhere), H (market blend weight x.5)
  4  SMOOTH FADE of the market-blend weight: w_adp x c / (c + g), g = clean games (F1) or games since the flag first fired (F2);
     c per position picked LOYO / forward over 2, 4, 6, 8, 12, 16, 999 (= wired)
Log usage_legit.log (ROS_MINF=1 -> usage_legit_minf1.log). Data: _tmp/X_cache.pkl, _tmp/role_games.pkl.
"""
import os, sys, pickle
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_shadow_next as SN
YEARS = list(range(2019, 2026)); FWD = (2022, 2023, 2024, 2025); POS4 = ("QB", "RB", "WR", "TE")
MINF = int(os.environ.get("ROS_MINF", "4"))
ABSENT_ROSTER = {"RES", "CUT", "DEV", "RET", "EXE", "PUP", "NFI", "SUS", "TRC", "TRD", "TRT"}
CGRID = (2, 4, 6, 8, 12, 16, 999)


def main():
    log = open(os.path.join(HERE, "usage_legit.log" if MINF != 1 else "usage_legit_minf1.log"), "w", encoding="utf-8")
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
    base_ok = ~np.isnan(T) & (g >= 1) & (g <= 11) & (R00 * ctx >= 3)
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
    later3 = g >= 3
    def parts(prior, off=()):
        on = lambda k: k not in off
        lam_ = bl.copy()
        if on("WR 101-150 usage cap .25"): lam_ = np.where((pos == "WR") & band["ADP 101-150"] & later3, np.minimum(lam_, 0.25), lam_)
        ev = lam_ * X["xf"] + (1 - lam_) * X["ppg_v"]
        pm_ = np.ones(n)
        if on("RB 61-100 prior weight x2.5"): pm_ = np.where((pos == "RB") & band["ADP 61-100"] & later3, 2.5, pm_)
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
    def ros(prior, off=()):
        Pw, ev, mu = parts(prior, off); return blend(Pw, ev, prior) * mu * ctx
    def nxt(prior, off=()):
        Pw, ev, mu = parts(prior, tuple(set(LATER) | set(off))); return blend(Pw, ev, prior) * mu * lay
    WPRIOR = X["prior"]; FULL = ros(WPRIOR); FULLN = nxt(WPRIOR)
    ok = base_ok & (FULL >= 3); okN = (g >= 1) & (g <= 11) & (wk != finw) & (FULLN >= 3)
    # ---- priors: market blend weight scaled by k (array), ridge with / without ADP ----
    yr2a = A["exp"] == 1; fb = F["fb_pos"]; ac = F["adp_curve"]; mk = F["mkt_ok"]; late_ = F["late"]
    mdock = np.ones(n)
    for ps_, d_ in SN.CS.NC.VETDOCK.items():
        for sb_, mm_ in d_.items(): mdock = np.where((pos == ps_) & (strb == sb_), mdock * mm_, mdock)
    mdock = np.where(yr2a & ~np.isnan(late_) & (late_ < 0.4), mdock * 1.2, mdock)
    wv = np.where(yr2a, 0.5, 0.75); prm = (F["prior"] - fb) / 0.8 + fb
    hm = np.where(mk, (prm - mdock * wv * np.nan_to_num(ac)) / (1 - wv), prm)
    mix = lambda rg, pr: np.where(np.isnan(rg) | (pos == "QB"), pr, 0.5 * rg + 0.5 * pr)
    def prior_k(k, ridge="adp"):
        k = np.broadcast_to(np.asarray(k, float), (n,))
        prk = np.where(mk, (1 - wv * k) * hm + mdock * wv * k * np.nan_to_num(ac), prm)
        pf = np.where(mk, fb + 0.8 * (prk - fb), F["prior"])
        return mix(X["r_adp"] if ridge == "adp" else X["r_no"], pf)
    P(f"=== USAGE-LEGIT ADP TEST: {int(ok.sum()):,} ROS checkpoints (2-10 games, {MINF}+ left), next-game rows {int(okN.sum()):,} ===")
    P(f"  check: prior_k(1) == wired on {100*np.mean(np.isclose(prior_k(1.0), WPRIOR, equal_nan=True)):.1f}% of rows; prior_k(0)+noAdp ridge == variant B prior on {100*np.mean(np.isclose(prior_k(0.0,'no'), mix(X['r_no'], np.where(mk, fb + 0.8*(hm - fb), F['prior'])), equal_nan=True)):.1f}%")

    # ---------------- per-game data + cleaning ----------------
    RG = pickle.load(open(os.path.join(HERE, "_tmp", "role_games.pkl"), "rb"))
    pg = RG["pg"].rename(columns={"year_x": "year"}); tg = RG["tg"]; INJ, ROS_, HAVE = RG["inj"], RG["ros"], RG["ros_have"]
    PGD = {(int(r.year), r.pid, int(r.wk)): r for r in pg.itertuples(index=False)}
    TGD = {(int(r.year), r.team, int(r.wk)): r for r in tg.itertuples(index=False)}
    tweeks = defaultdict(list)
    for (Y_, t_, w_) in TGD: tweeks[(Y_, t_)].append(w_)
    for k in tweeks: tweeks[k].sort()
    games_of = defaultdict(list); clay_of = {}; room = defaultdict(set)
    for i in range(n):
        k = (int(year[i]), pid[i]); games_of[k].append(int(wk[i]))
        if k not in clay_of: clay_of[k] = float(A["clay"][i]) if not np.isnan(A["clay"][i]) else 0.0
        room[(int(year[i]), team[i], pos[i])].add(pid[i])
    for k in games_of: games_of[k] = sorted(set(games_of[k]))
    gset = {k: set(v) for k, v in games_of.items()}
    def absent_at(Y_, t_, w_, q):
        rs_ = INJ.get((Y_, t_, w_, q), ("", ""))[0]; rst = ROS_.get((Y_, t_, w_, q))
        return rs_ in ("Out", "Doubtful") or (rst in ABSENT_ROSTER) or ((Y_, t_, w_) in HAVE and rst is None)
    def listed_at(Y_, t_, w_, q):
        r_, p_ = INJ.get((Y_, t_, w_, q), ("", ""))
        return r_ in ("Questionable", "Doubtful", "Out") or ("Did Not" in str(p_)) or ("Limited" in str(p_))
    def snap_raw(r, q):
        if r is None: return np.nan
        sp = r.snap_pct
        if isinstance(sp, float) and np.isnan(sp): sp = 100.0 * r.on / q.ppl if (q is not None and q.ppl) else np.nan
        return sp
    def game_vals(Y_, P_, w_, t_):
        """clean (competitive-play) per-game role values"""
        r = PGD.get((Y_, P_, w_)); q = TGD.get((Y_, t_, w_))
        if r is None or q is None: return None
        d = lambda a, b: a / b if b > 0 else np.nan
        return {"tgt_sh": d(r.tg_c, q.tg_c), "car_sh": d(r.car_c, q.car_c), "snap": 100 * d(r.on_c, q.ppl_c), "route": d(r.ondb_c, q.pdb_c),
                "xfp": r.xfp, "db_sh": d(r.db_c, q.db_c)}
    SHARE = {"QB": "db_sh", "RB": "car_sh", "WR": "tgt_sh", "TE": "tgt_sh"}
    def exit_ramp(Y_, P_, gl, W_lim):
        """indices of games in gl (list of (w, t)) that are injury exits or ramp games, knowing only weeks <= W_lim"""
        snaps = [snap_raw(PGD.get((Y_, P_, w_)), TGD.get((Y_, t_, w_))) for (w_, t_) in gl]; bad = set()
        for j, (w_, t_) in enumerate(gl):
            prev = [s for s in snaps[:j] if not np.isnan(s)]; pm_ = float(np.mean(prev)) if prev else np.nan; sj = snaps[j]
            if np.isnan(pm_) or np.isnan(sj): continue
            tw_ = tweeks[(Y_, t_)]; after = [x for x in tw_ if x > w_]; nx = after[0] if after else None
            if pm_ >= 50 and sj < 0.6 * pm_ and nx is not None and nx <= W_lim:
                if listed_at(Y_, t_, nx, P_) or (nx < W_lim and nx not in gset.get((Y_, P_), ())): bad.add(j)
            if j > 0 and sj < 0.85 * pm_ and len([x for x in tw_ if gl[j - 1][0] < x < w_]) >= 2: bad.add(j)
        return bad

    # ---------------- 1 stabilization (season-level clean tags) ----------------
    P("\n--- 1  STABILIZATION: split-half reliability of the N-clean-game mean (odd vs even clean games), r by N; N* = first N with r >= .70 ---")
    seasons = defaultdict(list)
    for i in range(n): seasons[(int(year[i]), pid[i], pos[i], team[i])].append(int(wk[i]))
    seqs = defaultdict(list)   # pos -> list of per-season clean game value dicts
    qbmode = {}
    for (Y_, t_), wl in tweeks.items():
        qs = [TGD[(Y_, t_, w_)].qb for w_ in wl if TGD[(Y_, t_, w_)].qb]
        if qs: qbmode[(Y_, t_)] = max(set(qs), key=qs.count)
    for (Y_, P_, p_, t_), wl in seasons.items():
        if not P_: continue
        wl = sorted(set(wl)); gl = [(w_, t_) for w_ in wl if PGD.get((Y_, P_, w_)) is not None and PGD[(Y_, P_, w_)].team == t_]
        if len(gl) < 4: continue
        bad = exit_ramp(Y_, P_, gl, 99)
        mine = clay_of.get((Y_, P_), 0.0)
        regs = [q for q in room.get((Y_, t_, p_), ()) if q != P_ and clay_of.get((Y_, q), 0.0) >= 5.0 and clay_of.get((Y_, q), 0.0) > 1.1 * mine]
        vals = []
        for j, (w_, tt) in enumerate(gl):
            if j in bad: continue
            if p_ != "QB" and regs and any(w_ not in gset.get((Y_, q), ()) for q in regs): continue
            if p_ != "QB" and TGD.get((Y_, tt, w_)) is not None and TGD[(Y_, tt, w_)].qb != qbmode.get((Y_, tt)): continue
            v = game_vals(Y_, P_, w_, tt)
            if v: vals.append(v)
        if vals: seqs[p_].append(vals)
    METS = {"QB": ("db_sh", "snap", "xfp"), "RB": ("car_sh", "tgt_sh", "snap", "route", "xfp"), "WR": ("tgt_sh", "snap", "route", "xfp"), "TE": ("tgt_sh", "snap", "route", "xfp")}
    NSTAR = {}
    for p_ in POS4:
        P(f"  {p_} ({len(seqs[p_])} player-seasons with clean games)")
        for met in METS[p_]:
            rs = []
            for N in range(1, 9):
                a_, b_ = [], []
                for vals in seqs[p_]:
                    v = [x[met] for x in vals if not (isinstance(x[met], float) and np.isnan(x[met]))]
                    if len(v) < 2 * N: continue
                    v = v[:2 * N]; a_.append(np.mean(v[0::2])); b_.append(np.mean(v[1::2]))
                rs.append((N, np.corrcoef(a_, b_)[0, 1] if len(a_) >= 40 else np.nan, len(a_)))
            ns = next((N for N, r, _ in rs if not np.isnan(r) and r >= 0.70), None)
            NSTAR[(p_, met)] = ns
            P(f"    {met:7s} " + "  ".join(f"N{N} {r:.2f}({c})" for N, r, c in rs) + f"   -> N* {ns}")
    NPOS = {p_: max([NSTAR.get((p_, m_)) or 8 for m_ in METS[p_]]) for p_ in POS4}            # every role metric incl. xFP/g at .70
    NLOOSE = {p_: max(NSTAR.get((p_, "snap")) or 8, NSTAR.get((p_, SHARE[p_])) or 8) for p_ in POS4}   # snap + primary share only
    P(f"  N_pos (base / strict = all metrics incl xFP at .70): {NPOS}; loose N (snap + primary share {SHARE}): {NLOOSE}")

    # ---------------- 2 checkpoint flags ----------------
    gcl_none = np.zeros(n); gcl_reset = np.zeros(n); gcl_half = np.zeros(n); nret = 0
    nkeep = np.zeros(n); s_all = np.full(n, np.nan); s_l3 = np.full(n, np.nan); h_all = np.full(n, np.nan); h_l3 = np.full(n, np.nan)
    for i in range(n):
        if g[i] < 1 or not pid[i]: continue
        Y_ = int(year[i]); P_ = pid[i]; t0 = team[i]; W = int(wk[i]); p_ = pos[i]
        gl = [(w_, PGD[(Y_, P_, w_)].team if PGD.get((Y_, P_, w_)) is not None else t0) for w_ in games_of[(Y_, P_)] if w_ < W]
        gl = [x for x in gl if x[1] == t0] or gl
        if not gl: continue
        bad = exit_ramp(Y_, P_, gl, W); keep = [x for j, x in enumerate(gl) if j not in bad] or list(gl)
        mine = clay_of.get((Y_, P_), 0.0)
        regs = [q for q in room.get((Y_, t0, p_), ()) if q != P_ and clay_of.get((Y_, q), 0.0) >= 5.0 and clay_of.get((Y_, q), 0.0) > 1.1 * mine]
        if regs and p_ in ("RB", "WR", "TE"):
            fi = [x for x in keep if any(x[0] not in gset.get((Y_, q), ()) for q in regs)]
            if fi and not any(absent_at(Y_, t0, W, q) for q in regs):
                rest = [x for x in keep if x not in fi]
                if rest: keep = rest
        if p_ in ("RB", "WR", "TE"):
            tw_ = [x for x in tweeks[(Y_, t0)] if x < W]; gq = [TGD[(Y_, t0, x)].qb for x in tw_ if TGD[(Y_, t0, x)].qb]
            if gq:
                eq = gq[-1]
                if absent_at(Y_, t0, W, eq):
                    cand = [q for q in gq if not absent_at(Y_, t0, W, q)]; eq = max(set(cand), key=cand.count) if cand else None
                if eq:
                    same = [x for x in keep if TGD.get((Y_, x[1], x[0])) is not None and TGD[(Y_, x[1], x[0])].qb == eq]
                    if len(same) >= 2 and len(same) < len(keep): keep = same
        vals = [v for v in (game_vals(Y_, P_, w_, t_) for (w_, t_) in keep) if v]
        if not vals: continue
        nkeep[i] = len(vals)
        # strict clean-games clock: no exits / ramps, no fill-in games (any regular missing), no other-QB games for WR / TE
        tw0 = [x for x in tweeks[(Y_, t0)] if x < W]; gq0 = [TGD[(Y_, t0, x)].qb for x in tw0 if TGD[(Y_, t0, x)].qb]
        qmode = max(set(gq0), key=gq0.count) if gq0 else None
        cl = [j for j, (w_, t_) in enumerate(gl) if j not in bad
              and not (regs and p_ in ("RB", "WR", "TE") and any(w_ not in gset.get((Y_, q), ()) for q in regs))
              and not (p_ in ("WR", "TE") and qmode and TGD.get((Y_, t_, w_)) is not None and TGD[(Y_, t_, w_)].qb != qmode)]
        jr = 0
        for j in range(1, len(gl)):
            if gl[j][1] == gl[j - 1][1] and len([x for x in tweeks[(Y_, gl[j][1])] if gl[j - 1][0] < x < gl[j][0]]) >= 3: jr = j
        pre = sum(1 for j in cl if j < jr); post = len(cl) - pre
        gcl_none[i] = len(cl); gcl_reset[i] = post; gcl_half[i] = 0.5 * pre + post; nret += jr > 0
        sn = [v["snap"] for v in vals if not np.isnan(v["snap"])]; sh = [v[SHARE[p_]] for v in vals if not np.isnan(v[SHARE[p_]])]
        if sn: s_all[i] = np.mean(sn); s_l3[i] = np.mean(sn[-3:])
        if sh: h_all[i] = np.mean(sh); h_l3[i] = np.mean(sh[-3:])
    Npos = np.array([NPOS[p_] for p_ in pos]); Nlo = np.array([NLOOSE[p_] for p_ in pos])
    def flag(Nv, S, H):
        st = (np.abs(s_l3 - s_all) <= S) & ((np.abs(h_l3 - h_all) <= H) | np.isnan(h_all))
        return (nkeep >= Nv) & st & ~np.isnan(s_all)
    FLAGS = {"base (N all metrics, +-8 snap, +-.04 share)": flag(Npos, 8, 0.04), "loose (N snap+share, +-12, +-.06)": flag(Nlo, 12, 0.06), "strict (N+1, +-5, +-.025)": flag(Npos + 1, 5, 0.025)}
    P("\n--- 2  USAGE-LEGIT FLAG: share of checkpoints flagged, by position x games played ---")
    for lab, fl in FLAGS.items():
        P(f"  {lab}: ROS rows flagged {100*fl[ok].mean():.0f}%  | " + "  ".join(f"{p_} " + "/".join(f"{100*fl[ok & (pos == p_) & (g >= lo) & (g <= hi)].mean():.0f}" for lo, hi in ((2, 3), (4, 5), (6, 7), (8, 10))) for p_ in POS4) + "  (% at 2-3/4-5/6-7/8-10 games)")

    # ---------------- grading ----------------
    def rho(q, m, tgt):
        grp = defaultdict(list)
        for i in np.where(m)[0]: grp[(int(year[i]), int(wk[i]), pos[i])].append(i)
        rh = [np.corrcoef(rankdata(tgt[ix]), rankdata(q[ix]))[0, 1] for ix in (np.array(v) for v in grp.values()) if len(ix) >= 8]
        return float(np.mean(rh)) if rh else np.nan
    def gr(Q, B_, m, tgt):
        if m.sum() < 30: return None
        e = lambda q, mm: float(np.mean((q[mm] - tgt[mm]) ** 2))
        s7 = sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and e(Q, m & (year == y)) < e(B_, m & (year == y)) - 1e-12)
        mf = m & np.isin(year, FWD); s4 = sum(1 for y in FWD if (m & (year == y)).sum() >= 8 and e(Q, m & (year == y)) < e(B_, m & (year == y)) - 1e-12)
        mt = m & top150
        w_ = lambda q, mm: float(np.average((q[mm] - tgt[mm]) ** 2, weights=wt[mm]))
        return dict(n=int(m.sum()), err=100 * (e(Q, m) / e(B_, m) - 1), fe=100 * (e(Q, mf) / e(B_, mf) - 1) if mf.sum() > 20 else np.nan,
                    mae=100 * (np.mean(np.abs(Q[m] - tgt[m])) / np.mean(np.abs(B_[m] - tgt[m])) - 1), w=100 * (w_(Q, mt) / w_(B_, mt) - 1) if mt.sum() > 20 else np.nan,
                    rk=rho(Q, mt, tgt) - rho(B_, mt, tgt), s7=s7, s4=s4)
    def passes(r): return r is not None and r["err"] < -0.3 and r["s7"] >= 5 and r["fe"] < 0 and r["s4"] >= 3 and r["w"] <= 0.1
    fmt = lambda r: "n/a" if r is None else f"n {r['n']:5d} err {r['err']:+6.2f}% ({r['s7']}/7) fwd {r['fe']:+6.2f}% ({r['s4']}/4) MAE {r['mae']:+6.2f}% top150-w {r['w']:+6.2f}% rank {r['rk']:+.4f}{'  PASS' if passes(r) else ''}"

    # ---------------- 3 flagged rows ----------------
    PB = prior_k(0.0, "no"); PH = prior_k(0.5)
    VAR = [("B  no market blend + noAdp ridge", PB, ()), ("E  no ADP anywhere", PB, BANDW + GATES), ("H  market blend weight x.5", PH, ())]
    P("\n--- 3  ADP OFF ON USAGE-LEGIT ROWS (variant applied only to the rows graded; vs wired; negative = better than wired) ---")
    for flab, fl in FLAGS.items():
        P(f"\n  FLAG {flab}")
        for vlab, pr_, off_ in VAR:
            Q = ros(pr_, off_); QN = nxt(pr_, off_)
            for side, msk in (("FLAGGED", fl), ("NOT yet", ~fl)):
                P(f"    {vlab} | {side}")
                P(f"      ROS  all  " + fmt(gr(Q, FULL, ok & msk, T)))
                for p_ in POS4: P(f"      ROS  {p_:3s}  " + fmt(gr(Q, FULL, ok & msk & (pos == p_), T)))
                P(f"      NEXT all  " + fmt(gr(QN, FULLN, okN & msk, act)))
                for p_ in POS4: P(f"      NEXT {p_:3s}  " + fmt(gr(QN, FULLN, okN & msk & (pos == p_), act)))

    # ---------------- 4 smooth fade ----------------
    P("\n--- 4  ADP FADE SCHEDULES on the market-blend weight (k x w_adp; wired k = 1). Schedules: smooth c/(c+G); hold-then-fade (1 through G <= H, then c/(c+G-H));"
      " linear ramp (1 through H, then -r a game, floor f). G = a clock. Scope: market blend only (M) or market blend + ridge ADP twin (MR). Picked per position on ROS (LOYO / forward). ---")
    P(f"  returner rows (3+ team games missed between two of his games, before the checkpoint): {nret:,}")
    CLOCKS = {"clean games": gcl_none, "clean games, reset after 3+ missed": gcl_reset, "clean games, half reset": gcl_half,
              "games played": g.astype(float), "calendar week (wk-1)": (wk - 1).astype(float)}
    SCH = [("wired", None)]
    for c in (2, 4, 6, 8, 12, 16): SCH.append((f"smooth c{c}", ("s", 0, c, 0)))
    for H in range(1, 7):
        for c in (2, 4, 6, 8, 12, 16): SCH.append((f"hold H{H} c{c}", ("h", H, c, 0)))
        for r in (0.05, 0.1, 0.15, 0.25):
            for f in (0.0, 0.25, 0.5): SCH.append((f"ramp H{H} r{r} f{f}", ("r", H, r, f)))
    SPEC = dict(SCH)
    def kof(spec, G):
        if spec is None: return np.ones(n)
        t_, H, c, f = spec
        if t_ == "s": return c / (c + G)
        if t_ == "h": return np.where(G <= H, 1.0, c / (c + np.maximum(G - H, 0)))
        return np.where(G <= H, 1.0, np.maximum(f, 1 - c * (G - H)))
    def prior_sched(k, scope):
        if scope == "M": return prior_k(k)
        kk = np.broadcast_to(k, (n,)); prk = np.where(mk, (1 - wv * kk) * hm + mdock * wv * kk * np.nan_to_num(ac), prm)
        pf = np.where(mk, fb + 0.8 * (prk - fb), F["prior"])
        rg = np.where(np.isnan(X["r_no"]), X["r_adp"], kk * X["r_adp"] + (1 - kk) * X["r_no"])
        return mix(rg, pf)
    e2 = lambda q, m, tgt: float(np.sum((q[m] - tgt[m]) ** 2))
    def sse_tab(Q, mrow, tgt):
        return {(p_, y): (e2(Q, mrow & (pos == p_) & (year == y), tgt), int((mrow & (pos == p_) & (year == y)).sum())) for p_ in POS4 for y in YEARS}
    BEST = {}
    for clab, G in CLOCKS.items():
        cands = []
        for scope in ("M", "MR"):
            for slab, spec in SCH:
                if spec is None and scope == "MR": continue
                pr_ = prior_sched(kof(spec, G), scope) if spec is not None else WPRIOR
                cands.append((f"{scope} {slab}", spec, scope, sse_tab(ros(pr_), ok, T)))
        def pick(p_, yrs):
            return min(cands, key=lambda c_: sum(c_[3][(p_, y)][0] for y in yrs) / max(1, sum(c_[3][(p_, y)][1] for y in yrs)))
        L = FULL.copy(); Fw = FULL.copy(); LN = FULLN.copy(); FN = FULLN.copy(); pk = defaultdict(list); best_all = {}
        cache = {}
        def preds(c_):
            if c_[0] not in cache:
                pr_ = prior_sched(kof(c_[1], G), c_[2]) if c_[1] is not None else WPRIOR; cache[c_[0]] = (ros(pr_), nxt(pr_))
            return cache[c_[0]]
        for p_ in POS4:
            best_all[p_] = pick(p_, YEARS)[0]
            for ty in YEARS:
                c_ = pick(p_, [y for y in YEARS if y != ty]); pk[p_].append(c_[0]); sel = (pos == p_) & (year == ty); r_, n_ = preds(c_); L[sel] = r_[sel]; LN[sel] = n_[sel]
            for ty in FWD:
                c_ = pick(p_, [y for y in YEARS if y < ty]); sel = (pos == p_) & (year == ty); r_, n_ = preds(c_); Fw[sel] = r_[sel]; FN[sel] = n_[sel]
        BEST[clab] = best_all
        P(f"\n  CLOCK: {clab}  | best schedule on all seasons: {best_all}")
        P("    LOYO picks: " + " | ".join(f"{p_} " + ", ".join(sorted(set(pk[p_]), key=pk[p_].count, reverse=True)[:3]) for p_ in POS4))
        for hz, Lq, Fq, BASE, mrow, tgt in (("ROS ", L, Fw, FULL, ok, T), ("NEXT", LN, FN, FULLN, okN, act)):
            for lab, m in [("all", mrow), ("top150", mrow & top150)] + [(p_, mrow & (pos == p_)) for p_ in POS4]:
                r = gr(Lq, BASE, m, tgt); rf = gr(Fq, BASE, m & np.isin(year, FWD), tgt)
                if r is None: continue
                ok_ = r['err'] < -0.3 and r['s7'] >= 5 and rf['err'] < 0 and rf['s4'] >= 3 and r['w'] <= 0.1
                P(f"    {hz} {lab:6s} n {r['n']:5d} LOYO err {r['err']:+6.2f}% ({r['s7']}/7) MAE {r['mae']:+6.2f}% top150-w {r['w']:+6.2f}% rank {r['rk']:+.4f} | FORWARD err {rf['err']:+6.2f}% ({rf['s4']}/4){'  PASS' if ok_ else ''}")
    # ---- error-by-week curves: ADP fully off (B) and the best clean-clock schedule, vs wired ----
    P("\n--- 4b  WHERE ADP STOPS EARNING ITS KEEP: error vs wired by checkpoint week (negative = better without / with less ADP) ---")
    QB_ = ros(PB); QBN = nxt(PB)
    bc = BEST["clean games"]; G = CLOCKS["clean games"]; QS = FULL.copy(); QSN = FULLN.copy()
    for p_ in POS4:
        lab = bc[p_]
        if lab == "M wired": continue
        scope, rest = lab.split(" ", 1); pr_ = prior_sched(kof(SPEC[rest], G), scope); sel = pos == p_
        QS[sel] = ros(pr_)[sel]; QSN[sel] = nxt(pr_)[sel]
    for lab, Q, QN in (("B no ADP in the prior", QB_, QBN), (f"best clean-clock schedule per position (in-sample) {bc}", QS, QSN)):
        P(f"  {lab}")
        for w_ in range(2, 13):
            mw = ok & (wk == w_); mn = okN & (wk == w_)
            r = gr(Q, FULL, mw, T); rn = gr(QN, FULLN, mn, act)
            if r is None or rn is None: continue
            P(f"    week {w_:2d}: ROS n {r['n']:4d} err {r['err']:+6.2f}% ({r['s7']}/7) top150-w {r['w']:+6.2f}% | NEXT err {rn['err']:+6.2f}% ({rn['s7']}/7) | ROS by pos " +
              " ".join(f"{p_} {rr['err']:+.1f}" for p_ in POS4 for rr in [gr(Q, FULL, mw & (pos == p_), T)] if rr))
    log.close()


if __name__ == "__main__":
    main()
