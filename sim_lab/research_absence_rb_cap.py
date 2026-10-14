#!/usr/bin/env python3
"""
ABSENCE MAP follow-up C4 (2026-10-09): RB fill-ins behind ANY absent RB (workhorse, committee lead, RB2) - the engine's shadow
flow caps a teammate's gain at his own number ('gain <= own'); only the workhorse-out direct backup has max(own, 6) (WORKHORSE.cap).
Map: RB2 out -> RB3 +4.3 PPR vs engine +0.8 (7/7); workhorse out -> RB2 +5.7 vs +3.1 (7/7).
Weekly-units replica (research_absence_all_positions.eng_proj), rows = healthy RBs with a baseline in single-RB-absence weeks
(returning-regular weeks excluded). Candidate: gain cap max(own, C) for every healthy RB rank 0-2 when a same-team RB is out, carry
shares x s. MAE vs actual PPR; LOYO (fit C, s on 6 seasons) >= 5/7 and forward >= 3/4. Log absence_rb_cap.log.
"""
import os, sys, pickle, copy
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
_keep = open(os.path.join(HERE, "absence_all_positions.log"), encoding="utf-8").read()
import research_absence_all_positions as A
A.LOG.close(); open(os.path.join(HERE, "absence_all_positions.log"), "w", encoding="utf-8").write(_keep)
LOG = open(os.path.join(HERE, "absence_rb_cap.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()
YEARS = A.YEARS


def proj(ev, m, C, s):
    """eng_proj with the RB cap floor C for every RB fill-in, carry shares x s"""
    E = copy.deepcopy(A.ENG)
    for k in ("lead", "sec"): E["POOL"]["RB"][k]["carSame"] = [x * s for x in E["POOL"]["RB"][k]["carSame"]]
    E["WH"] = (A.ENG["WH"][0], A.ENG["WH"][1] * s, A.ENG["WH"][2])
    base = A.eng_proj(ev, m, E)
    if C <= 0: return base
    # re-run the pool part with cap max(own, C): replicate eng_proj's gain to find the uncapped amount
    own = m["own"]; a = ev["A"][0]
    rule = E["POOL"]["RB"]["lead" if a["lead"] else "sec"]
    same = sorted([x for x in ev["mem"] if x["pos"] == "RB"], key=lambda x: x["rank"])
    i = next((j for j, x in enumerate(same) if x is m), -1)
    if i < 0: return base
    wt = rule["tgtSame"][i] if i < len(rule["tgtSame"]) else 0
    cs = rule["carSame"][i] if i < len(rule["carSame"]) else 0
    capx = own
    if i == 0 and a["roomsh"] >= E["WH"][0]: cs = E["WH"][1]; capx = max(own, E["WH"][2])
    g = E["K"] * (wt * a["recp"] * E["EFF_T"] + cs * a["rushp"] * E["EFF_C"])
    old = min(capx, g); new = min(max(capx, C), g)
    mult = base / (own + old) if own + old > 0 else 1.0
    return (own + new) * mult


def main():
    EV, CTRL = pickle.load(open(os.path.join(HERE, "data", "absence_events.pkl"), "rb"))
    rows = []
    for e in EV:
        if e["ret"] or len(e["A"]) != 1 or e["A"][0]["pos"] != "RB": continue
        for m in e["mem"]:
            if m["pos"] == "RB": rows.append((e, m))
    P(f"rows: {len(rows)} healthy RBs in {len(set(id(e) for e, m in rows))} single-RB-absence weeks")
    act = np.array([m["act"] for e, m in rows]); Y = np.array([e["Y"] for e, m in rows])
    role = np.array([e["A"][0]["role"] for e, m in rows]); rk = np.array([m["rank"] for e, m in rows]); own = np.array([m["own"] for e, m in rows])
    b = np.array([proj(e, m, 0, 1.0) for e, m in rows])
    P(f"engine replica mean {b.mean():.2f} vs actual {act.mean():.2f}; MAE {np.mean(np.abs(act-b)):.3f}")
    for R in ("RB_WH", "RB_COMM", "RB2"):
        for lo, hi, lab in ((0, 4, "own < 4"), (4, 8, "own 4-8"), (8, 99, "own 8+")):
            mm = (role == R) & (own >= lo) & (own < hi)
            if mm.sum() >= 8: P(f"  absent {R:7s} healthy RB {lab:8s}: n {int(mm.sum()):3d} actual {act[mm].mean():5.2f} engine {b[mm].mean():5.2f} median act {np.median(act[mm]):.1f}")
    grid = [(C, s) for C in (0, 4, 5, 6, 8) for s in (1.0, 1.25, 1.5)]
    PJ = {g: np.array([proj(e, m, *g) for e, m in rows]) for g in grid}
    mae = lambda p, msk: float(np.mean(np.abs(act[msk] - p[msk])))
    P("  fixed cells (MAE vs engine, seasons better):")
    for g in grid[1:]:
        P(f"    C {g[0]} s {g[1]}: mean {PJ[g].mean():.2f} MAE {100*(mae(PJ[g], Y > 0)/mae(b, Y > 0)-1):+.2f}% {sum(mae(PJ[g], Y == y) < mae(b, Y == y) for y in YEARS)}/7")
    fit = lambda msk: min(grid, key=lambda g: mae(PJ[g], msk))
    w = 0; tb = tn = 0
    for y in YEARS:
        g = fit(Y != y); te = Y == y; a0, a1 = mae(b, te), mae(PJ[g], te); w += a1 < a0 - 1e-12; tb += a0 * te.sum(); tn += a1 * te.sum()
        P(f"  LOYO {y}: fit C {g[0]} s {g[1]}  MAE {a0:.3f} -> {a1:.3f}")
    P(f"  LOYO {w}/7 pooled {100*(tn/tb-1):+.2f}%")
    fw = 0
    for y in YEARS[-4:]:
        g = fit(Y < y); te = Y == y; a0, a1 = mae(b, te), mae(PJ[g], te); fw += a1 < a0 - 1e-12
        P(f"  forward {y}: fit C {g[0]} s {g[1]}  MAE {a0:.3f} -> {a1:.3f}")
    P(f"  forward {fw}/4; full fit {fit(Y > 0)}")
    # REGRESSION CORRECTION: the replica's 'own' is a trailing-3 average; in NORMAL weeks a depth RB with own < 4 scores +2.2 over it
    # (own 12+ -4.3). Base' = replica + the control-week (no absence) mean of actual - own for RBs ranked 2+ at the same own level.
    ctl = [(m["own"], m["act"] - m["own"]) for c in CTRL for m in c["mem"] if m["pos"] == "RB" and m["rank"] >= 2]
    edges = [0, 2, 4, 6, 8, 10, 13, 99]; cx = np.array([c[0] for c in ctl]); cy = np.array([c[1] for c in ctl])
    gtab = [float(np.mean(cy[(cx >= a) & (cx < b)])) if ((cx >= a) & (cx < b)).sum() >= 20 else 0.0 for a, b in zip(edges[:-1], edges[1:])]
    gof = lambda o: gtab[min(len(gtab) - 1, max(0, np.searchsorted(edges, o, side="right") - 1))]
    P("  control regression by own level (RB rank 2+): " + " ".join(f"{a}-{b}: {g:+.2f}" for a, b, g in zip(edges[:-1], edges[1:], gtab)))
    b_raw = b.copy(); b = b_raw + np.array([gof(o) for o in own])
    P(f"  regression-corrected engine replica: mean {b.mean():.2f} vs actual {act.mean():.2f}")
    for R in ("RB_WH", "RB_COMM", "RB2"):
        for lo, hi, lab in ((0, 4, "own < 4"), (4, 8, "own 4-8"), (8, 99, "own 8+")):
            mm = (role == R) & (own >= lo) & (own < hi)
            if mm.sum() >= 8: P(f"    absent {R:7s} healthy RB {lab:8s}: n {int(mm.sum()):3d} actual {act[mm].mean():5.2f} corrected engine {b[mm].mean():5.2f}")
    # C4b additive lift for LOW-baseline fill-ins (own < L) at healthy RB rank 1-2: + c x absent PPR/g; graded on MSE (the harness bar) and MAE
    aP = np.array([e["A"][0]["ppr"] for e, m in rows]); hr = np.array([sorted([x for x in e["mem"] if x["pos"] == "RB"], key=lambda x: x["rank"]).index(m) for e, m in rows])
    G2 = [(c, L) for c in (0.0, 0.1, 0.15, 0.2, 0.3) for L in (4, 6, 8)]
    PJ2 = {g: b + np.where((own < g[1]) & (hr <= 1), g[0] * aP, 0.0) for g in G2}
    mse = lambda p, msk: float(np.mean((act[msk] - p[msk]) ** 2))
    P("  C4b additive lift for low-baseline fill-ins (own < L, healthy RB rank 1-2): + c x absent PPR/g")
    for g in G2:
        if g[0] == 0: continue
        P(f"    c {g[0]} L {g[1]}: touched {int(((own < g[1]) & (hr <= 1)).sum())} MSE {100*(mse(PJ2[g], Y > 0)/mse(b, Y > 0)-1):+.2f}% ({sum(mse(PJ2[g], Y == y) < mse(b, Y == y) for y in YEARS)}/7) MAE {100*(mae(PJ2[g], Y > 0)/mae(b, Y > 0)-1):+.2f}%")
    for nm_, f_ in (("MSE", mse), ("MAE", mae)):
        fit2 = lambda msk: min(G2, key=lambda g: f_(PJ2[g], msk))
        w = 0; tb = tn = 0; picks = []
        for y in YEARS:
            g = fit2(Y != y); picks.append(g); te = Y == y; a0, a1 = f_(b, te), f_(PJ2[g], te); w += a1 < a0 - 1e-12; tb += a0 * te.sum(); tn += a1 * te.sum()
        fw = 0; fp = []
        for y in YEARS[-4:]:
            g = fit2(Y < y); fp.append(g); te = Y == y; fw += f_(PJ2[g], te) < f_(b, te) - 1e-12
        P(f"    {nm_}: LOYO {w}/7 pooled {100*(tn/tb-1):+.2f}% picks {picks}; forward {fw}/4 picks {fp}")
    LOG.close()


if __name__ == "__main__":
    main()
