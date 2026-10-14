#!/usr/bin/env python3
"""
(backup_rb_eff) Built from research_absence_backup_rb.py. DIRECT-BACKUP RB when the RB1 is out - re-test on the shadow harness WITH today's shipped changes (2026-10-09, Jack "do both").
Base = backtest_base_remeasure shadow replica x NMU (absent RBs do not trigger) x PROMO x TEAM_VAC (WR/TE absences only), and:
  * the v2.13 exact-flow form for the direct backup (trailing RB2 by carries, last 3 team games, when the trailing RB1 has no row):
    own + min(cap, .75 x (carSh x absent rush pts + .28 x absent rec pts x .92)), own = shadow without the old pool multiplier;
    WORKHORSE cell: absent RB1 >= .60 of the room's carries -> carSh .30, cap max(own, 6); else carSh .28, cap own.
  * RB tgtOther = 0: WR/TE rows whose only vacancy is an RB lose the old pool multiplier.
Then candidates on top: (a) flat direct-backup multiplier fitted per fold; (b) 2-3 room-pattern cells (shrunk toward 1, K 20);
(c) a larger gain cap for every direct backup. Bar: touched rows LOYO >= 5/7 and forward >= 3/4 (MSE, house metric; MAE shown),
whole board and RB board MAE not worse. Log backup_rb_eff.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import backtest_team_vacated_boost as TVB
cal = BR.cal; YEARS = BR.YEARS; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "backup_rb_eff.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()
SK = ("RB", "WR", "TE"); PROMO = {"RB": 1.034, "WR": 1.071, "TE": 1.207}
WH_SHARE, WH_CAR, WH_CAP, CAR0, TGT0, EFF_T, K = 0.60, 0.30, 6.0, 0.28, 0.28, 0.92, 0.75


def wk_pts(norm_name, Y, weeks):
    """absent RB's mean half-PPR rush pts and rec pts over the given weeks he played"""
    rec = next((r for r in cal.WEEKLY.get(norm_name, []) if r.get("pos") == "RB"), None)
    if rec is None: return None
    rs = [w for w in rec.get("seasons", {}).get(str(Y), []) if cal.played(w) and int(w["wk"]) in weeks]
    if not rs: return None
    rp = np.mean([(w.get("ry") or 0) * 0.1 + (w.get("rtd") or 0) * 6 for w in rs])
    cp = np.mean([(w.get("rec") or 0) * 0.5 + (w.get("rcy") or 0) * 0.1 + (w.get("rctd") or 0) * 6 for w in rs])
    return rp, cp


def setup_harness():
    X = BR.SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, name, adp, team = X["act"], X["year"], X["wk"], X["pos"], X["name"], X["adp"], X["team"]
    pick = np.array(X["A"]["pick"], dtype=float)
    SH, _ = BR.shadow_current(X)
    finw = np.where(year <= 2020, 17, 18)
    nlog = os.path.join(HERE, "next_man_up.log"); keep = open(nlog, encoding="utf-8").read() if os.path.exists(nlog) else None
    import research_next_man_up as R
    if keep is not None: R.LOG.close(); open(nlog, "w", encoding="utf-8").write(keep)
    Ev, _c = R.events(); TODAY, LV = BR.live_today(X)
    adpx = np.where(np.isnan(adp), 999.0, adp); nbase = (adpx <= 150) & (wk != finw) & ~LV["inh"] & (SH >= 3)
    idx = {(R.nz(name[i]), int(year[i]), int(wk[i])): i for i in range(n)}
    NMU = np.ones(n)
    for r in Ev:
        i = idx.get((R.nz(r["n"]), r["Y"], r["wk"]))
        if i is None or not nbase[i] or r["rank"] > 6: continue
        if all(p_ == "RB" for p_ in r["absPos"]): continue
        NMU[i] = 1.04 if r["rank"] == 1 else 0.99 if r["rank"] <= 3 else 1.03
    tg, promo, cg = TVB.tables()
    PR = np.ones(n)
    for i in range(n):
        if pos[i] in PROMO and (cal.norm(name[i]), int(year[i]), int(wk[i])) in promo: PR[i] = PROMO[pos[i]]
    team_wks = defaultdict(list)
    for (Y, t, w) in tg: team_wks[(Y, t)].append(w)
    for k in team_wks: team_wks[k].sort()
    cache = {}
    def info(Y, t, w):
        key = (Y, t, w)
        if key in cache: return cache[key]
        res = None
        if (Y, t, w) in tg:
            prior = [u for u in team_wks.get((Y, t), []) if u < w][-3:]
            if len(prior) >= 2:
                tot = 0.0; by = defaultdict(float); gp = defaultdict(int); car = defaultdict(float)
                for u in prior:
                    for kk, v in tg[(Y, t, u)].items(): tot += v; by[kk] += v; gp[kk] += 1
                    for kk, v in cg.get((Y, t, u), {}).items(): car[kk] += v
                if tot >= 30:
                    vac = defaultdict(float)
                    for kk, v in by.items():
                        if gp[kk] >= 2 and v / tot >= 0.10 and kk not in tg[(Y, t, w)]: vac[kk[1]] += v / tot
                    rbo = sorted([kk for kk in car if kk[1] == "RB"], key=lambda k: -car[k])
                    room = sum(car[k] for k in rbo)
                    top_out = bool(rbo) and gp.get(rbo[0], 0) >= 2 and rbo[0] not in tg[(Y, t, w)] and rbo[0] not in cg.get((Y, t, w), {})
                    res = dict(vac=vac, prior=prior, order=[cal.norm(k[0]) for k in rbo], car={cal.norm(k[0]): car[k] / len(prior) for k in rbo},
                               tgt={cal.norm(k[0]): by.get(k, 0.0) / len(prior) for k in rbo}, room=room / len(prior),
                               top_out=top_out, top_room=(car[rbo[0]] / room) if rbo and room > 0 else 0.0)
        cache[key] = res; return res
    INF = [info(int(year[i]), team[i], int(wk[i])) if (team[i] and pos[i] in SK) else None for i in range(n)]
    hasI = np.array([I is not None for I in INF])
    vac = np.array([(I["vac"].get("WR", 0.0) + I["vac"].get("TE", 0.0)) if I else 0.0 for I in INF])
    TV = np.where(hasI & np.isin(pos, SK), 1 + 0.2 * vac, 1.0)
    on = np.asarray(F["on"]) & np.isfinite(F["pm"]); pmk = np.where(on, np.power(np.where(on, F["pm"], 1.0), 0.75), 1.0)
    ok = np.isin(pos, SK) & (wk != finw) & (SH >= 1) & np.isfinite(act) & hasI
    # ---- direct backups
    db = np.zeros(n, bool); whf = np.zeros(n, bool); room_sh = np.full(n, np.nan); tpg = np.full(n, np.nan); gap = np.full(n, np.nan)
    Rr = np.zeros(n); Rc = np.zeros(n); absn = [None] * n
    for i, I in enumerate(INF):
        if I is None or pos[i] != "RB" or not I["top_out"]: continue
        o = I["order"]; me = cal.norm(name[i])
        if len(o) < 2 or o[1] != me: continue
        ap = wk_pts(o[0], int(year[i]), set(I["prior"]))
        if ap is None: continue
        db[i] = True; whf[i] = I["top_room"] >= WH_SHARE; Rr[i], Rc[i] = ap; absn[i] = o[0]
        room_sh[i] = I["car"][me] / max(1e-9, I["room"]); tpg[i] = I["tgt"].get(me, 0.0)
        gap[i] = I["car"][me] - (I["car"][o[2]] if len(o) > 2 else 0.0)
    own = SH / pmk
    def v213(carsh_wh=WH_CAR, cap_wh=WH_CAP, carsh=CAR0, cap_all=None, wh_on=True):
        g = K * (np.where(whf & wh_on, carsh_wh, carsh) * Rr + TGT0 * Rc * EFF_T)
        cap = np.where(whf & wh_on, np.maximum(own, cap_wh), own)
        if cap_all is not None: cap = np.maximum(cap, cap_all)
        return own + np.minimum(cap, g)
    SH_old = SH.copy()
    SH_pre = np.where(db, v213(wh_on=False), SH)                        # v2.13 flow as it ran YESTERDAY (no workhorse cell)
    SH_new = np.where(db, v213(), SH)                                    # + today's WORKHORSE cell
    # RB tgtOther = 0: WR/TE rows whose team's RB1 is out and no WR/TE vacancy lose the old pool multiplier
    rbonly = np.array([bool(I and I["top_out"]) for I in INF]) & np.isin(pos, ("WR", "TE")) & (vac == 0) & on
    SH_new = np.where(rbonly, SH_new / pmk, SH_new); SH_pre2 = np.where(rbonly, SH_pre / pmk, SH_pre)
    lay = NMU * PR * TV
    B_old, B_pre, B = SH_old * lay, SH_pre2 * lay, SH_new * lay
    okd = ok & db
    r_ = lambda p, m: act[m].sum() / max(1e-9, p[m].sum())
    P(f"rows {ok.sum()} RB/WR/TE; direct backups with the trailing RB1 out: {int(okd.sum())} (workhorse-out {int((okd & whf).sum())}); WR/TE rows de-pooled (RB tgtOther 0): {int((ok & rbonly).sum())}")
    P(f"  direct backup actual / projection: harness pool (old) {r_(B_old, okd):.3f} | v2.13 flow, no WORKHORSE {r_(B_pre, okd):.3f} | + WORKHORSE (TODAY) {r_(B, okd):.3f}")
    for lab, m in (("workhorse out", okd & whf), ("committee out", okd & ~whf)):
        P(f"    {lab:14s} n {int(m.sum()):3d}: old {r_(B_old, m):.3f}  v2.13 {r_(B_pre, m):.3f}  today {r_(B, m):.3f}  | mean act {act[m].mean():.2f} today {B[m].mean():.2f}")
    P("    by season (today): " + " ".join(f"{y}:{r_(B, okd & (year == y)):.2f}(n{int((okd & (year == y)).sum())})" for y in YEARS))
    P("    by projection level (today): " + " | ".join(f"{lo}-{hi}: n {int((okd & (B >= lo) & (B < hi)).sum())} {r_(B, okd & (B >= lo) & (B < hi)):.2f}" for lo, hi in ((0, 5), (5, 8), (8, 11), (11, 99))))
    P(f"    WR/TE de-pooled rows: actual / today {r_(B, ok & rbonly):.3f} (old {r_(B_old, ok & rbonly):.3f})")
    for lab, m in (("room share >= .30", room_sh >= .30), ("room share < .30", room_sh < .30), ("tgt/g >= 2.5", tpg >= 2.5), ("tgt/g < 2.5", tpg < 2.5),
                   ("clear (gap >= 5 car)", gap >= 5), ("not clear", gap < 5), ("round 1-2 (pick <= 64)", pick <= 64), ("pick 65+ / UDFA", ~(pick <= 64))):
        mm = okd & m
        P(f"    cell {lab:24s} n {int(mm.sum()):3d} actual/today {r_(B, mm):.3f}  seasons under {sum(r_(B, mm & (year == y)) > 1 for y in YEARS if (mm & (year == y)).sum())}/{len({int(y) for y in year[mm]})}")

    return locals()
