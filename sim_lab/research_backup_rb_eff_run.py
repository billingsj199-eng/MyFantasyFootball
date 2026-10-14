#!/usr/bin/env python3
"""
BACKUP RB EFFICIENCY when the RB1 is out (Jack 2026-10-09: "if we increase volume on backups we can maybe assume they become
slightly less efficient if that's what it says in historical tests"). The shadow prices the vacated carries at the ABSENT starter's
rushing points (lostRush = cz.full x (1 - cz.rf)); alternative = vacated carries x the BACKUP's shrunk own pts/carry x factor f.
1  efficiency study (weekly DB 2019-25, all RB weeks + direct-backup fill-in weeks): week pts/carry vs shrunk season-to-date own,
   vs the absent starter, vs league; volume dependence.
2  harness (research_backup_rb_eff.setup_harness = shadow replica x NMU x PROMO x TEAM_VAC with the v2.13 flow), re-set to TONIGHT's
   engine (every direct backup .40 of vacated carries, cap max(own, 8)); variants graded MSE (primary) + MAE, LOYO 7 + forward 4,
   touched rows + RB board. Log backup_rb_eff.log (shared with setup).
"""
import os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import research_backup_rb_eff as H0
cal, YEARS, FWD, P = H0.cal, H0.YEARS, H0.FWD, H0.P


def rbrec(nm):
    return next((r for r in cal.WEEKLY.get(nm, []) if r.get("pos") == "RB"), None)


def wkrows(nm, Y):
    r = rbrec(nm)
    if r is None: return {}
    out = {}
    for w in r.get("seasons", {}).get(str(Y), []):
        if not cal.played(w): continue
        out[int(w["wk"])] = dict(c=float(w.get("ra") or 0), rp=(w.get("ry") or 0) * 0.1 + (w.get("rtd") or 0) * 6, y=float(w.get("ry") or 0), td=float(w.get("rtd") or 0),
                                 t=float(w.get("tgt") or 0), cp=(w.get("rec") or 0) * 0.5 + (w.get("rcy") or 0) * 0.1 + (w.get("rctd") or 0) * 6)
    return out


def std(rows, wk, weeks=None):
    S = dict(c=0.0, rp=0.0, y=0.0, td=0.0, t=0.0, cp=0.0, g=0)
    for w, r in rows.items():
        if w < wk and (weeks is None or w in weeks):
            S["g"] += 1
            for k in ("c", "rp", "y", "td", "t", "cp"): S[k] += r[k]
    return S


def efficiency_study(fill_keys):
    L = []; lg = {}
    rbnames = [nm for nm, lst in cal.WEEKLY.items() if any(r.get("pos") == "RB" for r in lst)]
    for Y in YEARS:
        tc = tr = tt = tcp = 0.0; R = {}
        for nm in rbnames:
            R[nm] = wkrows(nm, Y)
            for r in R[nm].values(): tc += r["c"]; tr += r["rp"]; tt += r["t"]; tcp += r["cp"]
        lg[Y] = (tr / tc, tcp / tt)
        for nm, rows in R.items():
            for wk, r in rows.items():
                S = std(rows, wk)
                if S["g"] < 2: continue
                L.append(dict(nm=nm, Y=Y, wk=wk, c=r["c"], rp=r["rp"], t=r["t"], cp=r["cp"], pc=S["c"], prp=S["rp"], pt=S["t"], pcp=S["cp"], pg=S["g"],
                              fill=(nm, Y, wk) in fill_keys, lgc=lg[Y][0], lgt=lg[Y][1]))
    return L, lg


def fitK(S, kind):
    best = None
    for K0 in (5, 10, 20, 40, 60, 80, 120, 200, 400):
        if kind == "c": x = np.array([(e["prp"] + e["lgc"] * K0) / (e["pc"] + K0) for e in S]); yv = np.array([e["rp"] / e["c"] for e in S]); wv = np.array([e["c"] for e in S])
        else: x = np.array([(e["pcp"] + e["lgt"] * K0) / (e["pt"] + K0) for e in S]); yv = np.array([e["cp"] / e["t"] for e in S]); wv = np.array([e["t"] for e in S])
        A_ = np.c_[np.ones(len(x)), x] * np.sqrt(wv)[:, None]; co = np.linalg.lstsq(A_, yv * np.sqrt(wv), rcond=None)[0]
        err = float(np.sum(wv * (yv - (co[0] + co[1] * x)) ** 2) / wv.sum())
        if best is None or err < best[0]: best = (err, K0, co[0], co[1], float(np.sum(wv * yv) / np.sum(wv * x)))
    return best


def main():
    H = H0.setup_harness()
    n, okd, db, act, year, name, wk, own, lay, SH_new, ok, pos, INF, absn, Rr, Rc = (H[k] for k in ("n", "okd", "db", "act", "year", "name", "wk", "own", "lay", "SH_new", "ok", "pos", "INF", "absn", "Rr", "Rc"))
    bk = {}
    for i in np.where(db)[0]:
        Y, w = int(year[i]), int(wk[i]); me = cal.norm(name[i]); I = INF[i]
        mr, ar = wkrows(me, Y), wkrows(absn[i], Y)
        if w not in mr: continue
        bk[i] = dict(me=std(mr, w), now=mr[w], ab=std(ar, w), abtr=std(ar, w, set(I["prior"])))
    fill_keys = {(cal.norm(name[i]), int(year[i]), int(wk[i])) for i in bk}
    L, lg = efficiency_study(fill_keys)
    P(f"\n##### 1. EFFICIENCY STUDY: {len(L)} RB player-weeks with 2+ prior games (2019-25); {sum(e['fill'] for e in L)} are harness direct-backup fill-in weeks")
    P("  league RB rush pts/carry: " + " ".join(f"{y}:{lg[y][0]:.3f}" for y in YEARS) + " | rec half pts/target: " + " ".join(f"{y}:{lg[y][1]:.2f}" for y in YEARS))
    for kind, lab, mn, mv in (("c", "RUSH pts/carry", "c", 5), ("t", "REC half pts/target", "t", 2)):
        S_all = [e for e in L if e[mn] >= mv]
        for tag, S in (("all RB weeks", S_all), ("FILL-IN weeks", [e for e in S_all if e["fill"]])):
            err, K0, a, b, ratio = fitK(S, kind)
            P(f"  {lab}, {tag} (n {len(S)}): best shrink K {K0} {'carries' if kind == 'c' else 'targets'} toward league; week eff = {a:.3f} + {b:.2f} x shrunk own; actual / shrunk own = {ratio:.3f}")
    R = [v for v in bk.values() if v["now"]["c"] >= 1]
    sw = lambda f: sum(f(v) for v in R)
    lgY = np.mean([lg[int(year[i])][0] for i in bk])
    P(f"\n  HARNESS fill-in rows n {len(R)}: {sw(lambda v: v['now']['c'])/len(R):.1f} carries (own prior {sw(lambda v: v['me']['c'])/max(1, sw(lambda v: v['me']['g'])):.1f}/g; absent starter {sw(lambda v: v['abtr']['c'])/max(1, sw(lambda v: v['abtr']['g'])):.1f}/g)")
    P(f"    rush pts/carry: FILL-IN {sw(lambda v: v['now']['rp'])/sw(lambda v: v['now']['c']):.3f} | own s-t-d {sw(lambda v: v['me']['rp'])/max(1,sw(lambda v: v['me']['c'])):.3f} | ABSENT starter s-t-d {sw(lambda v: v['ab']['rp'])/max(1,sw(lambda v: v['ab']['c'])):.3f} | league {lgY:.3f}")
    P(f"    ypc: FILL-IN {sw(lambda v: v['now']['y'])/sw(lambda v: v['now']['c']):.2f} | own {sw(lambda v: v['me']['y'])/max(1,sw(lambda v: v['me']['c'])):.2f} | absent {sw(lambda v: v['ab']['y'])/max(1,sw(lambda v: v['ab']['c'])):.2f};  TD/carry: FILL-IN {sw(lambda v: v['now']['td'])/sw(lambda v: v['now']['c']):.3f} | own {sw(lambda v: v['me']['td'])/max(1,sw(lambda v: v['me']['c'])):.3f} | absent {sw(lambda v: v['ab']['td'])/max(1,sw(lambda v: v['ab']['c'])):.3f}")
    P(f"    rec half pts/target: FILL-IN {sw(lambda v: v['now']['cp'])/max(1,sw(lambda v: v['now']['t'])):.2f} | own {sw(lambda v: v['me']['cp'])/max(1,sw(lambda v: v['me']['t'])):.2f} | absent {sw(lambda v: v['ab']['cp'])/max(1,sw(lambda v: v['ab']['t'])):.2f}")
    P("  volume dependence: week rush pts/carry / shrunk own (K 80), by carries this week / own prior carries per game")
    for tag, S in (("all RB weeks", [e for e in L if e["c"] >= 5 and e["pc"] > 0]), ("fill-in weeks", [e for e in L if e["c"] >= 5 and e["pc"] > 0 and e["fill"]])):
        cells = []
        for lo, hi in ((0, 0.8), (0.8, 1.25), (1.25, 2), (2, 3), (3, 99)):
            Sx = [e for e in S if lo <= e["c"] / (e["pc"] / e["pg"]) < hi]
            if len(Sx) < 15: continue
            num = sum(e["rp"] for e in Sx); den = sum(e["c"] * (e["prp"] + e["lgc"] * 80) / (e["pc"] + 80) for e in Sx)
            cells.append(f"{lo}-{hi}x: {num/den:.3f} (n {len(Sx)})")
        P(f"    {tag:14s} " + " | ".join(cells))
    # by own prior carries (does a small sample of great efficiency hold up?)
    S = [e for e in L if e["c"] >= 5 and e["fill"]]
    for lo, hi in ((0, 30), (30, 80), (80, 999)):
        Sx = [e for e in S if lo <= e["pc"] < hi]
        if len(Sx) >= 8:
            P(f"    fill-in, own prior carries {lo}-{hi}: n {len(Sx)} actual {sum(e['rp'] for e in Sx)/sum(e['c'] for e in Sx):.3f} pts/carry vs own raw {sum(e['prp'] for e in Sx)/max(1,sum(e['pc'] for e in Sx)):.3f} vs league {np.mean([e['lgc'] for e in Sx]):.3f}")

    # ---- 2. projection variants at TONIGHT's engine
    absC = np.zeros(n); ownC = np.zeros(n); ownR = np.zeros(n); lgv = np.zeros(n); have = np.zeros(n, bool)
    for i, v in bk.items():
        absC[i] = v["abtr"]["c"] / max(1, v["abtr"]["g"]); ownC[i] = v["me"]["c"]; ownR[i] = v["me"]["rp"]; lgv[i] = lg[int(year[i])][0]; have[i] = v["abtr"]["g"] > 0
    okd2 = okd & have
    def proj(rush):
        g = 0.75 * (0.40 * rush + 0.28 * Rc * 0.92)
        return np.where(db & have, own + np.minimum(np.maximum(own, 8.0), g), SH_new) * lay
    BT = proj(Rr)
    P(f"\n##### 2. HARNESS at TONIGHT's engine (.40 of vacated carries, cap max(own, 8), absent's rush pts): rows {int(okd2.sum())}, actual/proj {act[okd2].sum()/BT[okd2].sum():.3f}; by season " + " ".join(f"{y}:{act[okd2 & (year == y)].sum()/max(1e-9, BT[okd2 & (year == y)].sum()):.2f}" for y in YEARS))
    P(f"  absent trailing rush pts/carry (what the engine prices) {Rr[okd2].sum()/max(1e-9, absC[okd2].sum()):.3f} vs backups' shrunk own K 80 {np.sum(absC[okd2]*(ownR[okd2]+lgv[okd2]*80)/(ownC[okd2]+80))/absC[okd2].sum():.3f}")
    GRID = [(K0, f) for K0 in (20, 40, 80, 160, 400) for f in (0.80, 0.90, 1.00, 1.10)]
    PV = {g: proj(absC * g[1] * (ownR + lgv * g[0]) / (ownC + g[0])) for g in GRID}
    PH = {(K0, f): proj(0.5 * Rr + 0.5 * absC * f * (ownR + lgv * K0) / (ownC + K0)) for K0 in (40, 80, 160) for f in (0.9, 1.0)}
    PL = {(f,): proj(absC * f * lgv) for f in (0.9, 1.0, 1.1)}
    mse = lambda p, m: float(np.mean((p[m] - act[m]) ** 2)); mae = lambda p, m: float(np.mean(np.abs(p[m] - act[m])))
    rbb = ok & (pos == "RB")
    def run(title, D):
        P(f"\n=== {title} ===")
        for label, folds in (("LOYO", [(tuple(y for y in YEARS if y != t), t) for t in YEARS]), ("FORWARD", [(tuple(y for y in YEARS if y < t), t) for t in FWD])):
            w2 = wm = nt = 0; a0 = a1 = c0 = c1 = r0 = r1 = q0 = q1 = 0.0; picks = []
            for tr, te in folds:
                g = min(D, key=lambda g: mse(D[g], okd2 & np.isin(year, tr))); picks.append(g); p = D[g]
                r = okd2 & (year == te); wr = rbb & (year == te)
                if not r.sum(): continue
                e0, e1, m0, m1 = mse(BT, r), mse(p, r), mae(BT, r), mae(p, r); w2 += e1 < e0 - 1e-12; wm += m1 < m0 - 1e-12; nt += 1
                a0 += e0 * r.sum(); a1 += e1 * r.sum(); c0 += m0 * r.sum(); c1 += m1 * r.sum()
                r0 += mse(BT, wr) * wr.sum(); r1 += mse(p, wr) * wr.sum(); q0 += mae(BT, wr) * wr.sum(); q1 += mae(p, wr) * wr.sum()
            P(f"  {label}: touched MSE {100*(a1/a0-1):+.2f}% ({w2}/{nt}), MAE {100*(c1/c0-1):+.2f}% ({wm}/{nt}) | RB board MSE {100*(r1/r0-1):+.3f}%, MAE {100*(q1/q0-1):+.3f}% | picks {picks}")
        gb = min(D, key=lambda g: mse(D[g], okd2))
        P(f"  full-sample pick {gb}: mean proj {D[gb][okd2].mean():.2f} vs tonight {BT[okd2].mean():.2f} vs actual {act[okd2].mean():.2f}")
        return gb
    run("(A) vacated carries x BACKUP's shrunk own pts/carry x f (K, f per fold)", PV)
    P("  fixed (touched MSE / MAE / seasons better on MSE): " + "  ".join(f"K{g[0]} f{g[1]} {100*(mse(PV[g], okd2)/mse(BT, okd2)-1):+.1f}%/{100*(mae(PV[g], okd2)/mae(BT, okd2)-1):+.1f}% {sum(mse(PV[g], okd2 & (year == y)) < mse(BT, okd2 & (year == y)) for y in YEARS)}/7" for g in GRID if g[1] in (0.9, 1.0)))
    run("(B) 50/50: absent's rush pts and backup-priced carries", PH)
    run("(C) vacated carries x LEAGUE pts/carry x f", PL)
    H0.LOG.close()


if __name__ == "__main__":
    main()
