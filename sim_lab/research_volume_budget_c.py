#!/usr/bin/env python3
"""
VOLUME BUDGET STUDY part C (2026-10-13) - situations / outliers, the KAMARA stacking case, the shipped blowout ctxShare rule,
and the allocation layer on rest of season with the availability decay. Uses research_volume_budget.py's tables + _tmp pickles.
Log volume_budget_c.log. Research only; nothing wired.
"""
import os, sys, pickle, time
from collections import defaultdict, Counter
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import research_volume_budget as VB
from research_volume_budget import (n, act, year, wk, pos, g, adp, name, pid, team, final, top150, WT, S, S0, TODAY, L, GW, TW, TWEEKS, PGAMES,
                                    POSOF, SK, YEARS, FWD, NEXT, ROSM, TR, ros, wmse, mae, fold_table, loyo_pick, H, B0, AX)
LOG = open(os.path.join(HERE, "volume_budget_c.log"), "w", encoding="utf-8")
def P(s=""):
    print(s, flush=True); LOG.write(s + "\n"); LOG.flush()
VB.P = P   # route fold tables into this log
PT = pickle.load(open(os.path.join(HERE, "_tmp", "vb_points.pkl"), "rb"))
Ra, R, BUD = PT["Ra"], PT["R"], PT["BUD"]
Pw = H["Pw"]; on = H["on"]; pm = H["pm"]


def history(i):
    """this player's games this season on his current team before wk, and the team's games"""
    Y, t, w, p_ = int(year[i]), team[i], int(wk[i]), pid[i]
    tw = [k for k in TWEEKS.get((Y, t), []) if k < w]
    mine = [k for k in tw if p_ in GW[(Y, t, k)]]
    return Y, t, w, p_, tw, mine


def members_absent(Y, t, w, tw):
    """regular members (share >= .10 of targets or >= .20 of carries over the games they played) with no row in week w"""
    acc = defaultdict(lambda: [0.0, 0.0, 0]); out = []
    for k in tw:
        Tk = TW[(Y, t, k)]
        for x, r in GW[(Y, t, k)].items():
            if r.pos not in SK: continue
            a = acc[x]; a[0] += r.tg / max(Tk.tg, 1); a[1] += r.car / max(Tk.car, 1); a[2] += 1
    for x, (st, sc, gp) in acc.items():
        if gp >= 1 and (st / gp >= 0.10 or sc / gp >= 0.20) and x not in GW.get((Y, t, w), {}): out.append((x, st / gp, sc / gp))
    return out


def main():
    t0 = time.time()
    m = NEXT & ~np.isnan(BUD); mr = ROSM & ~np.isnan(BUD)
    # ---------------- tags ----------------
    tag = defaultdict(lambda: np.zeros(n, bool)); kseen = np.full(n, -1)
    for i in np.where(m | mr)[0]:
        Y, t, w, p_, tw, mine = history(i)
        if not tw: continue
        ab = members_absent(Y, t, w, tw)
        if ab:
            tag["teammate regular out"][i] = True
            big = max(ab, key=lambda z: z[1] + z[2])[0]
            kseen[i] = sum(1 for k in mine if big not in GW[(Y, t, k)])
            same = [z for z in ab if POSOF.get(z[0]) == pos[i]]
            if same and pos[i] == "RB": tag["RB committee: same-room RB out"][i] = True
        last = TW[(Y, t, tw[-1])]
        if last.garb >= 6 and abs(last.margin) >= 17: tag["blowout last game"][i] = True
        qbs = Counter(TW[(Y, t, k)].qb for k in tw); qn = TW[(Y, t, w)].qb
        if qbs and qn != qbs.most_common(1)[0][0]: tag["QB change (next starter != usual)"][i] = True
        allg = [w_ for (w_, t_) in PGAMES.get((Y, p_), []) if w_ < w]
        if allg and any(k > allg[-1] for k in tw): tag["return from absence"][i] = True
        teams = [t_ for (w_, t_) in PGAMES.get((Y, p_), []) if w_ < w]
        if teams and teams[0] != t: tag["traded / new team in season"][i] = True
        sl, ss = H["snap_l1"][i], H["snap_std"][i]
        if not np.isnan(sl) and not np.isnan(ss) and abs(sl - ss) >= 15: tag["role change (last snap share 15+ off avg)"][i] = True
        if H["rookie"][i]: tag["rookie"][i] = True
    P("=" * 110); P("PART C1 - WHERE THE SHADOW MISSES (next game + rest of season): bias, error share, seasons over / under"); P("=" * 110)
    for hl, T_, mm, tf in (("NEXT GAME", act, m, lambda p: p), ("REST OF SEASON", TR, mr, ros)):
        Sv = tf(S); tot = float(np.sum(WT[mm] * (Sv[mm] - T_[mm]) ** 2)); P(f"\n--- {hl} (n {int(mm.sum())}) ---")
        for k, v in tag.items():
            q = mm & v
            if q.sum() < 30: continue
            err = np.sum(WT[q] * (Sv[q] - T_[q]) ** 2); rel = wmse(Sv, T_, q) / wmse(Sv, T_, mm)
            over = sum(1 for Y in YEARS if (q & (year == Y)).sum() >= 5 and T_[q & (year == Y)].sum() > Sv[q & (year == Y)].sum())
            ny = sum(1 for Y in YEARS if (q & (year == Y)).sum() >= 5)
            P(f"  {k:44s} n{int(q.sum()):5d} share of rows {100*q.sum()/mm.sum():5.1f}% share of error {100*err/tot:5.1f}% | per-row error x{rel:.2f} | act/shadow {T_[q].sum()/Sv[q].sum():.3f} (under-projected {over}/{ny} seasons)")
    P("\n--- biggest single-player rest-of-season misses per season (checkpoint = game 4; top-150) ---")
    for Y in YEARS:
        q = np.where(mr & (year == Y) & (g == 4))[0]
        if not len(q): continue
        Sv = ros(S); err = np.abs(Sv[q] - TR[q]); top = q[np.argsort(-err)[:5]]
        P(f"  {Y}: " + " | ".join(f"{name[i]} {pos[i]} proj {Sv[i]:.1f} act {TR[i]:.1f}" + (" [" + ",".join(k.split(' ')[0] for k, v in tag.items() if v[i]) + "]" if any(v[i] for v in tag.values()) else "") for i in top))
    # ---------------- Kamara: pool boost by games already played without the absent teammate ----------------
    P("\n" + "=" * 110); P("PART C2 - KAMARA CASE: vacancy boost (pool, k .75 as in the shadow replica) by games the absorber ALREADY played without the absent regular"); P("=" * 110)
    pr = m & on & (kseen >= 0)
    for hl, T_, mm, tf in (("NEXT GAME", act, pr, lambda p: p), ("REST OF SEASON", TR, mr & on & (kseen >= 0), ros)):
        P(f"\n--- {hl} ---")
        for lo, hi in ((0, 0), (1, 1), (2, 2), (3, 4), (5, 20)):
            q = mm & (kseen >= lo) & (kseen <= hi)
            if q.sum() < 20: continue
            for ps in ("RB", "WR", "TE", "all"):
                qq = q & ((pos == ps) if ps != "all" else True)
                if qq.sum() < 20: continue
                P(f"  seen-without {lo}-{hi:<2d} {ps:3s} n{int(qq.sum()):5d} mean pool mult {pm[qq].mean():.3f} | act/shadow-with-pool {T_[qq].sum()/tf(S)[qq].sum():.3f} | act/shadow-no-pool {T_[qq].sum()/tf(S0)[qq].sum():.3f} | MSE pool vs no-pool {100*(wmse(tf(S), T_, qq)/wmse(tf(S0), T_, qq)-1):+.2f}%")
    P("\n--- fix candidates: pool boost faded by games already seen without him (pm^(.75 f)), whole top-150 board ---")
    preds, predsR = {"wired": S}, {"wired": S}
    ks = np.maximum(kseen, 0)
    for lab, f in (("f = 1 - seen/(P+g)  (evidence weight of those games)", 1 - ks / np.maximum(Pw + g, 1)), ("f = 0 once seen 1+", np.where(ks >= 1, 0.0, 1.0)),
                   ("f = max(0, 1 - seen/2)", np.maximum(0, 1 - ks / 2)), ("f = max(0, 1 - seen/4)", np.maximum(0, 1 - ks / 4)), ("f = .5 once seen 1+", np.where(ks >= 1, 0.5, 1.0))):
        C = np.where(on & (kseen >= 0), S0 * np.power(pm, 0.75 * np.clip(f, 0, 1)), S); preds[lab] = C; predsR[lab] = C
        fold_table(lab + " (next)", S, C, act, m); fold_table(lab + " (ROS)", S, C, TR, mr, ros)
        fold_table("   pool rows seen 1+ only (next)", S, C, act, m & on & (kseen >= 1))
    loyo_pick(preds, S, act, m, "Kamara fade, next game"); loyo_pick(predsR, S, TR, mr, "Kamara fade, ROS", ros)
    P("\n  budget allocation on the same seen-1+ pool rows (allocation e 1 vs wired pool):")
    for e in (0.75, 1.0):
        C = S0 * np.clip(Ra ** e, 0.6, 1.8)
        fold_table(f"   allocation e {e}, pool rows seen 1+ (next)", S, C, act, m & on & (kseen >= 1)); fold_table(f"   allocation e {e}, pool rows seen 0 (next)", S, C, act, m & on & (kseen == 0))
    # ---------------- ROS allocation with availability decay ----------------
    P("\n" + "=" * 110); P("PART C3 - ALLOCATION LAYER on rest of season with the absence decaying (absent players come back)"); P("=" * 110)
    predsR = {"wired": S}
    for e, c in ((1.0, 0.25), (1.0, 0.5), (0.75, 0.5), (1.0, 0.75)):
        C = S0 * np.clip(1 + c * (Ra ** e - 1), 0.6, 1.8); predsR[f"alloc e {e} x{c}"] = C; fold_table(f"alloc e {e}, ROS decay x{c}", S, C, TR, mr, ros)
    loyo_pick(predsR, S, TR, mr, "allocation ROS with decay", ros)
    # combined: next-game allocation e 1 for this week, decayed for ROS
    pickle.dump(dict(kseen=kseen, tags={k: v for k, v in tag.items()}), open(os.path.join(HERE, "_tmp", "vb_tags.pkl"), "wb"))
    # ---------------- blowout ctxShare rule (shipped, never graded) ----------------
    P("\n" + "=" * 110); P("PART C4 - SHIPPED BLOWOUT RULE (ctxShare): snap / route share re-measured on competitive plays"); P("=" * 110)
    rows = []
    for (Y, p_), gl in PGAMES.items():
        if Y < 2019: continue
        for j in range(1, len(gl)):
            (w0, t0_), (w1, t1_) = gl[j - 1], gl[j]
            if t0_ != t1_: continue
            r0 = GW[(Y, t0_, w0)][p_]; r1 = GW[(Y, t1_, w1)][p_]
            if r0.pos not in SK: continue
            T0 = TW[(Y, t0_, w0)]; T1 = TW[(Y, t1_, w1)]
            if T0.pp_plays <= 0 or T1.pp_plays <= 0: continue
            pct = 100 * r0.on / T0.pp_plays; gar = T0.pp_plays - T0.pp_plays_c; comp = T0.pp_plays_c; cnt = r0.on
            adj = min(100, 100 * cnt / comp) if (gar >= 6 and comp > 0 and cnt <= comp + 0.5) else pct
            adj = adj if (gar >= 6 and cnt >= 0.85 * comp) else pct
            true_c = 100 * r0.on_c / comp if comp > 0 else pct
            dpct = 100 * r0.on_db / max(T0.pp_db, 1); dcomp = T0.pp_db_c; dgar = T0.pp_db - dcomp
            dadj = min(100, 100 * r0.on_db / dcomp) if (dgar >= 6 and dcomp > 0 and r0.on_db <= dcomp + 0.5 and r0.on_db >= 0.85 * dcomp) else dpct
            rows.append((Y, r0.pos, gar >= 6, pct, adj, true_c, 100 * r1.on / T1.pp_plays, dpct, dadj, 100 * r1.on_db / max(T1.pp_db, 1), 100 * r1.on_c / max(T1.pp_plays_c, 1)))
    A = np.array([r[3:] for r in rows], float); yy = np.array([r[0] for r in rows]); bl = np.array([r[2] for r in rows]); pp = np.array([r[1] for r in rows])
    for lab, mm in (("all games", np.ones(len(rows), bool)), ("previous game a blowout (6+ garbage plays)", bl)):
        for ps in ("RB", "WR", "TE"):
            q = mm & (pp == ps)
            e_raw = np.mean((A[q, 0] - A[q, 3]) ** 2); e_adj = np.mean((A[q, 1] - A[q, 3]) ** 2); e_true = np.mean((A[q, 2] - A[q, 3]) ** 2)
            se = sum(1 for Y in YEARS if np.mean((A[q & (yy == Y), 1] - A[q & (yy == Y), 3]) ** 2) < np.mean((A[q & (yy == Y), 0] - A[q & (yy == Y), 3]) ** 2) - 1e-12)
            r_raw = np.mean((A[q, 4] - A[q, 6]) ** 2); r_adj = np.mean((A[q, 5] - A[q, 6]) ** 2)
            P(f"  {lab:44s} {ps} n{int(q.sum()):6d} next snap share MSE: raw {e_raw:7.2f} | ctxShare {e_adj:7.2f} ({100*(e_adj/e_raw-1):+.2f}%, {se}/7) | true competitive share {e_true:7.2f} ({100*(e_true/e_raw-1):+.2f}%)"
              f" || route proxy (dropbacks on field) raw {r_raw:7.2f} ctx {r_adj:7.2f} ({100*(r_adj/r_raw-1):+.2f}%) | adjusted rows {int((np.abs(A[q,1]-A[q,0])>0.5).sum())}")
    P(f"\n[{time.time()-t0:.0f}s] done")


if __name__ == "__main__":
    main()
