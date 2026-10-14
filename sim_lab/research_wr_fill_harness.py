#!/usr/bin/env python3
"""
WR FILL-INS on the shadow harness (Jack 2026-10-09). Base = research_backup_rb_eff.setup_harness() (shadow replica x NMU x PROMO x
TEAM_VAC, RB pieces as shipped) with the WR/TE pool re-expressed in the engine's v2.13 exact-flow form for team-weeks where a WR
(trailing share >= .10, 2+ of the last 3 team games) has no row:
  own = shadow without the old live-pool multiplier; gained = .75 x (tgtSame[i] x absent rec pts x .92 [+ tgtOther .08 to the TE1 on
  a lead absence]); projection = own + min(own, gained); i = rank among the team's trailing WRs other than the absent one.
Variants: (a) data-fitted rank shares (per fold, from wr_fill.json training seasons) x scale; (b) gain cap max(own, C) for healthy
rank 0; (c) 'slides into the slot' WR multiplier cell (shrunk K 20); (d) sec-rule shares cut (data: h2 .03 / h3 .02 vs .11 / .15).
Grade: squared error first, MAE second; LOYO 7 + forward 4; touched rows + WR board. Log wr_fill_harness.log.
"""
import os, sys, json
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import research_backup_rb_eff as H0
cal, YEARS, FWD = H0.cal, H0.YEARS, H0.FWD
LOG = open(os.path.join(HERE, "wr_fill_harness.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()
ENG = {"lead": [0.09, 0.15, 0.16, 0.10], "sec": [0.00, 0.11, 0.15, 0.10]}


def recpts(nm, Y, weeks):
    rec = next((r for r in cal.WEEKLY.get(nm, []) if r.get("pos") == "WR"), None)
    if rec is None: return None
    rs = [w for w in rec.get("seasons", {}).get(str(Y), []) if cal.played(w) and int(w["wk"]) in weeks]
    if not rs: return None
    return float(np.mean([(w.get("rec") or 0) * 0.5 + (w.get("rcy") or 0) * 0.1 + (w.get("rctd") or 0) * 6 for w in rs]))


def main():
    H = H0.setup_harness()
    n, act, year, wk, pos, name, team, ok, own, lay, SH_new, tg, team_wks = (H[k] for k in ("n", "act", "year", "wk", "pos", "name", "team", "ok", "own", "lay", "SH_new", "tg", "team_wks"))
    pmk = H["pmk"]
    # per team-week WR absences
    cache = {}
    def wrinfo(Y, t, w):
        key = (Y, t, w)
        if key in cache: return cache[key]
        res = None
        prior = [u for u in team_wks.get((Y, t), []) if u < w][-3:]
        if (Y, t, w) in tg and len(prior) >= 2:
            by = defaultdict(float); gp = defaultdict(int); tot = 0.0
            for u in prior:
                for kk, v in tg[(Y, t, u)].items(): by[kk] += v; gp[kk] += 1; tot += v
            if tot >= 30:
                top = max(by.values())
                wrs = sorted([k for k in by if k[1] == "WR" and gp[k] >= 2], key=lambda k: -by[k])
                tes = sorted([k for k in by if k[1] == "TE" and gp[k] >= 2], key=lambda k: -by[k])
                out = [k for k in wrs if by[k] / tot >= 0.10 and k not in tg[(Y, t, w)]]
                if out:
                    Z = []
                    for z in out:
                        lp = recpts(cal.norm(z[0]), Y, set(prior))
                        if lp is None: continue
                        others = [cal.norm(k[0]) for k in wrs if k != z]
                        Z.append(dict(nm=cal.norm(z[0]), lead=by[z] >= top - 1e-9, lost=lp, others=others, orank=wrs.index(z), sh=by[z] / tot))
                    if Z: res = dict(Z=Z, te1=cal.norm(tes[0][0]) if tes else None, nout=len(out))
        cache[key] = res; return res
    WI = [wrinfo(int(year[i]), team[i], int(wk[i])) if (team[i] and pos[i] in ("WR", "TE") and ok[i]) else None for i in range(n)]
    tch = np.array([w is not None for w in WI]) & ok
    hr = np.full(n, -1); slide = np.zeros(n, bool); lead1 = np.zeros(n, bool)
    def gain(i, shares, capC=None, cap_rank0_only=True):
        """v2.13 pool gain for row i under the given share table"""
        W = WI[i]; me = cal.norm(name[i]); g = 0.0
        for z in W["Z"]:
            rule = shares["lead" if z["lead"] else "sec"]
            if pos[i] == "WR" and me in z["others"]:
                j = z["others"].index(me); g += (rule[j] if j < len(rule) else 0.0) * z["lost"] * 0.92
            elif pos[i] == "TE" and z["lead"] and me == W["te1"]:
                g += shares.get("other", 0.08) * z["lost"] * 0.92
        g *= 0.75
        o = own[i]; cap = o
        if capC is not None and pos[i] == "WR" and hr[i] == 0: cap = max(o, capC)
        return o + min(cap, g)
    for i in np.where(tch)[0]:
        me = cal.norm(name[i]); z = WI[i]["Z"][0]
        if pos[i] == "WR" and me in z["others"]:
            hr[i] = z["others"].index(me); slide[i] = hr[i] == z["orank"]; lead1[i] = z["lead"]
    def build(shares, capC=None):
        p = SH_new.copy()
        for i in np.where(tch)[0]: p[i] = gain(i, shares, capC)
        return p * lay
    B = build(ENG)
    B_old = SH_new * lay
    r_ = lambda p, m: act[m].sum() / max(1e-9, p[m].sum())
    P(f"touched WR/TE rows (team had a WR out): {int(tch.sum())} (WR {int((tch & (pos == 'WR')).sum())}, TE {int((tch & (pos == 'TE')).sum())}); WR board rows {int((ok & (pos == 'WR')).sum())}")
    P(f"  actual / projection: old harness pool {r_(B_old, tch):.3f} | engine v2.13 form {r_(B, tch):.3f}")
    one = np.array([bool(w and w['nout'] == 1) for w in WI])
    for lab, m in (("healthy WR rank 1 (h1)", tch & (hr == 0)), ("h2", tch & (hr == 1)), ("h3", tch & (hr == 2)), ("h4+", tch & (hr >= 3)), ("TE", tch & (pos == "TE")),
                   ("  lead out: h1", tch & (hr == 0) & lead1), ("  lead out: h2", tch & (hr == 1) & lead1), ("  sec out: h1", tch & (hr == 0) & ~lead1), ("  sec out: h2", tch & (hr == 1) & ~lead1), ("  sec out: h3", tch & (hr == 2) & ~lead1),
                   ("slides into the absent's slot", tch & slide), ("two+ WRs out", tch & ~one)):
        if m.sum() >= 10:
            P(f"    {lab:30s} n {int(m.sum()):4d}  act {act[m].mean():5.2f}  engine {B[m].mean():5.2f} (gain over own {np.mean(B[m] / lay[m] - own[m]):+.2f})  act/eng {r_(B, m):.3f}  seasons under {sum(r_(B, m & (year == y)) > 1 for y in YEARS if (m & (year == y)).sum())}/7")
    ctrlm = ok & (pos == "WR") & ~tch
    P(f"    reference: WR rows with no WR out  act/eng {r_(B, ctrlm):.3f}")
    mse = lambda p, m: float(np.mean((p[m] - act[m]) ** 2)); mae = lambda p, m: float(np.mean(np.abs(p[m] - act[m])))
    wrb = ok & (pos == "WR")
    def run(title, cand):
        P(f"\n=== {title} ===")
        for label, folds in (("LOYO", [(tuple(y for y in YEARS if y != t), t) for t in YEARS]), ("FORWARD", [(tuple(y for y in YEARS if y < t), t) for t in FWD])):
            w2 = wm = nt = 0; a0 = a1 = c0 = c1 = r0 = r1 = q0 = q1 = 0.0; picks = []
            for tr, te in folds:
                p, pk = cand(tr); picks.append(pk); r = tch & (year == te); wr = wrb & (year == te)
                e0, e1, m0, m1 = mse(B, r), mse(p, r), mae(B, r), mae(p, r); w2 += e1 < e0 - 1e-12; wm += m1 < m0 - 1e-12; nt += 1
                a0 += e0 * r.sum(); a1 += e1 * r.sum(); c0 += m0 * r.sum(); c1 += m1 * r.sum()
                r0 += mse(B, wr) * wr.sum(); r1 += mse(p, wr) * wr.sum(); q0 += mae(B, wr) * wr.sum(); q1 += mae(p, wr) * wr.sum()
            P(f"  {label}: touched MSE {100*(a1/a0-1):+.2f}% ({w2}/{nt}), MAE {100*(c1/c0-1):+.2f}% ({wm}/{nt}) | WR board MSE {100*(r1/r0-1):+.3f}%, MAE {100*(q1/q0-1):+.3f}% | picks {picks}")
    # (a) data-fitted shares per fold
    J = json.load(open(os.path.join(HERE, "data", "wr_fill.json")))["per_season"]
    def data_shares(tr):
        out = {}
        for k in ("lead", "sec"):
            V = sum(J[f"{y}|{k}"]["V"] for y in tr); dt = [sum(J[f"{y}|{k}"]["dt"][j] for y in tr) for j in range(4)]
            out[k] = [max(0.0, d / max(V, 1e-9)) for d in dt]
        out["other"] = 0.08
        return out
    cacheP = {}
    def shares_pred(sh, capC=None):
        key = (json.dumps(sh, sort_keys=True), capC)
        if key not in cacheP: cacheP[key] = build(sh, capC)
        return cacheP[key]
    def cand_a(tr):
        ds = data_shares(tr); best = None
        for s in (0.5, 1.0, 1.5, 2.0):
            sh = {k: [x * s for x in ds[k]] for k in ("lead", "sec")}; sh["other"] = 0.08
            p = shares_pred(sh); e = mse(p, tch & np.isin(year, tr))
            if best is None or e < best[0]: best = (e, p, s)
        return best[1], best[2]
    run("(a) data-fitted healthy-rank shares (training seasons) x scale", cand_a)
    dsf = data_shares(YEARS); P("  full-sample data shares: lead " + str([round(x, 3) for x in dsf["lead"]]) + "  sec " + str([round(x, 3) for x in dsf["sec"]]))
    # (b) cap for the top absorber
    def cand_b(tr):
        best = min((None, 6.0, 8.0, 10.0, 12.0), key=lambda C: mse(shares_pred(ENG, C), tch & np.isin(year, tr)))
        return shares_pred(ENG, best), best
    run("(b) gain cap max(own, C) for healthy WR rank 1", cand_b)
    # (c) slide-into-slot cell, (c2) healthy rank 1 cell
    def cell(mask):
        def f(tr):
            t = mask & np.isin(year, tr); rr = act[t].sum() / B[t].sum(); k = t.sum() / (t.sum() + 20.0); m_ = 1 + k * (rr - 1)
            return np.where(mask, B * m_, B), round(float(m_), 3)
        return f
    run("(c) WR who slides into the absent's slot: shrunk multiplier", cell(tch & slide))
    run("(c2) healthy WR rank 1 when the LEAD is out: shrunk multiplier", cell(tch & (hr == 0) & lead1))
    # (d) cut the sec shares toward the data
    D = {}
    for s2, s3 in ((0.11, 0.15), (0.05, 0.08), (0.03, 0.03), (0.0, 0.0)):
        sh = {"lead": ENG["lead"], "sec": [0.0, s2, s3, 0.10], "other": 0.08}; D[(s2, s3)] = shares_pred(sh)
    run("(d) sec-rule h2/h3 shares cut (grid .11/.15, .05/.08, .03/.03, 0/0)", lambda tr: (lambda k: (D[k], k))(min(D, key=lambda k: mse(D[k], tch & np.isin(year, tr)))))
    P("  fixed (touched MSE / MAE): " + "  ".join(f"{k} {100*(mse(D[k], tch)/mse(B, tch)-1):+.2f}%/{100*(mae(D[k], tch)/mae(B, tch)-1):+.2f}%" for k in D))
    run("(e) lead out: healthy WR rank 1-2 shrunk multiplier (one cell)", cell(tch & (hr <= 1) & (hr >= 0) & lead1))
    E2 = {}
    for s0, s1 in ((0.09, 0.15), (0.05, 0.08), (0.0, 0.0)):
        sh = {"lead": [s0, s1, 0.16, 0.10], "sec": ENG["sec"], "other": 0.08}; E2[(s0, s1)] = shares_pred(sh)
    run("(f) lead-rule h1/h2 shares cut (.09/.15, .05/.08, 0/0)", lambda tr: (lambda k: (E2[k], k))(min(E2, key=lambda k: mse(E2[k], tch & np.isin(year, tr)))))
    P("  fixed (touched MSE / MAE): " + "  ".join(f"{k} {100*(mse(E2[k], tch)/mse(B, tch)-1):+.2f}%/{100*(mae(E2[k], tch)/mae(B, tch)-1):+.2f}% seasons {sum(mse(E2[k], tch & (year == y)) < mse(B, tch & (year == y)) for y in YEARS)}/7" for k in E2))
    m_ = tch & (hr >= 0) & (hr <= 1) & lead1
    P("  lead-out h1/h2 act/eng by season: " + " ".join(f"{y}:{r_(B, m_ & (year == y)):.2f}(n{int((m_ & (year == y)).sum())})" for y in YEARS))
    LOG.close()


if __name__ == "__main__":
    main()
