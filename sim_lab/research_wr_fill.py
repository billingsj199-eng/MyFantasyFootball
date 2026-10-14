#!/usr/bin/env python3
"""
WR FILL-INS (Jack 2026-10-09: "do the same study for wr fill ins"). Weekly DB 2019-25 via research_absence_all_positions.collect()
(same trailing rules; returning-regular weeks dropped; single meaningful absence = the WR; QB healthy).
1 VOLUME: where an absent WR1 / WR2 / WR3's targets go, by HEALTHY WR rank (the engine's i: rank among healthy WRs by trailing
  targets), TE1, RB1, bodies, team totals; control-adjusted by the player's ORIGINAL rank in no-absence weeks; seasons x/7;
  star (>= 15 PPR/g) vs regular. Engine-implied target share = POOL.WR lead/sec tgtSame[i] (+ tgtOther .08 to TEs on lead).
2 EFFICIENCY: WR/TE half-PPR pts/target, catch rate, yds/target, TD/target in fill-in weeks (healthy WR rank 0-2 when a WR is out)
  vs own shrunk season-to-date, vs the absent WR, vs league; volume bins; shrinkage fit.
Writes wr_fill.log, data/wr_fill.json (per-season shares for the harness test in research_wr_fill_harness.py).
"""
import os, sys, json
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
_keep = open(os.path.join(HERE, "absence_all_positions.log"), encoding="utf-8").read()
import research_absence_all_positions as A
A.LOG.close(); open(os.path.join(HERE, "absence_all_positions.log"), "w", encoding="utf-8").write(_keep)
cal = A.cal; YEARS = A.YEARS
LOG = open(os.path.join(HERE, "wr_fill.log"), "w", encoding="utf-8")
def P(s=""): print(s); LOG.write(s + "\n"); LOG.flush()
ENG = {"lead": [0.09, 0.15, 0.16, 0.10], "sec": [0.00, 0.11, 0.15, 0.10]}


def main():
    EV0, CT0 = A.collect()
    EV = [e for e in EV0 if not e["ret"] and len(e["A"]) == 1 and e["A"][0]["role"] in ("WR1", "WR2", "WR3")]
    CT = [c for c in CT0 if not c["ret"]]
    # control: mean dTgt / dPPR by (pos, original rank) for players who played
    cd = defaultdict(list)
    for c in CT:
        for m in c["mem"]:
            if m["pos"] in ("WR", "TE", "RB"): cd[(c["Y"], m["pos"], min(m["rank"], 5))].append((m["at"] - m["bt"], m["act"] - m["own"]))
    ctl = lambda Y, ps, r, j: float(np.mean([x[j] for x in cd[(Y, ps, min(r, 5))]])) if cd[(Y, ps, min(r, 5))] else 0.0
    cb = defaultdict(list)
    for c in CT:
        for ps in ("WR", "TE", "RB"): cb[(c["Y"], ps)].append((c["sl"]["b" + ps]["dt"], c["sl"]["b" + ps]["dp"]))
    cbody = lambda Y, ps, j: float(np.mean([x[j] for x in cb[(Y, ps)]]))
    cteam = {Y: (np.mean([c["N"]["tgt"] - c["T"]["tgt"] for c in CT if c["Y"] == Y]), np.mean([c["N"]["pa"] - c["T"]["pa"] for c in CT if c["Y"] == Y])) for Y in YEARS}
    out = {"shares": {}, "per_season": {}}
    P(f"=== WR FILL-INS 2019-25: {len(EV)} single-WR-absence team-weeks (WR1 {sum(e['A'][0]['role']=='WR1' for e in EV)}, WR2 {sum(e['A'][0]['role']=='WR2' for e in EV)}, WR3 {sum(e['A'][0]['role']=='WR3' for e in EV)}), {len(CT)} control ===")
    P("##### 1. VOLUME - share of the absent WR's trailing targets gained (control-adjusted), by HEALTHY rank; engine share in [ ]")
    groups = [("WR1 out", lambda e: e["A"][0]["role"] == "WR1"), ("WR2 out", lambda e: e["A"][0]["role"] == "WR2"), ("WR3 out", lambda e: e["A"][0]["role"] == "WR3"),
              ("LEAD target-getter out (engine 'lead')", lambda e: e["A"][0]["lead"]), ("not lead (engine 'sec')", lambda e: not e["A"][0]["lead"]),
              ("STAR out (>= 15 PPR/g)", lambda e: e["A"][0]["ppr"] >= 15), ("regular out (< 15)", lambda e: e["A"][0]["ppr"] < 15)]
    for lab, sel in groups:
        L = [e for e in EV if sel(e)]
        if len(L) < 10: continue
        V = sum(e["A"][0]["tgt"] for e in L)
        cells = defaultdict(lambda: [0.0, 0.0, 0, defaultdict(float), defaultdict(float)])   # dt sum, dp sum, n, per-season dt, per-season V
        engsh = defaultdict(float)
        for e in L:
            Y = e["Y"]; a = e["A"][0]; rule = ENG["lead" if a["lead"] else "sec"]
            wrs = sorted([m for m in e["mem"] if m["pos"] == "WR"], key=lambda m: m["rank"])
            for i, m in enumerate(wrs):
                k = f"WR h{min(i, 3) + 1}"
                c = cells[k]; dt = m["at"] - m["bt"] - ctl(Y, "WR", m["rank"], 0); dp = m["act"] - m["own"] - ctl(Y, "WR", m["rank"], 1)
                c[0] += dt; c[1] += dp; c[2] += 1; c[3][Y] += dt
                engsh[k] += (rule[i] if i < len(rule) else 0.0) * a["tgt"]
            for ps, r in (("TE", 1), ("RB", 1)):
                m = next((m for m in e["mem"] if m["pos"] == ps and m["rank"] == r), None)
                if m:
                    k = f"{ps}1"; c = cells[k]; dt = m["at"] - m["bt"] - ctl(Y, ps, 1, 0); dp = m["act"] - m["own"] - ctl(Y, ps, 1, 1)
                    c[0] += dt; c[1] += dp; c[2] += 1; c[3][Y] += dt
                    if ps == "TE" and a["lead"]: engsh[k] += 0.08 * a["tgt"]
            for ps in ("WR", "TE"):
                k = f"bodies {ps}"; c = cells[k]; dt = e["sl"]["b" + ps]["dt"] - cbody(Y, ps, 0); dp = e["sl"]["b" + ps]["dp"] - cbody(Y, ps, 1)
                c[0] += dt; c[1] += dp; c[2] += 1; c[3][Y] += dt
            for k in list(cells): cells[k][4][Y] += 0  # touch
        VY = defaultdict(float)
        for e in L: VY[e["Y"]] += e["A"][0]["tgt"]
        tk = 1 + np.mean([e["N"]["tgt"] - e["T"]["tgt"] - cteam[e["Y"]][0] for e in L]) / (V / len(L))
        pa = np.mean([e["N"]["pa"] - e["T"]["pa"] - cteam[e["Y"]][1] for e in L])
        P(f"\n  {lab}: n {len(L)}, absent {V/len(L):.1f} tgt/g, {np.mean([e['A'][0]['ppr'] for e in L]):.1f} PPR/g | team keeps {tk:.2f} of his targets, pass att {pa:+.1f}")
        P(f"    {'who':10s} {'n':>4s} {'share of V':>10s} {'[engine]':>9s} {'sgn':>4s} {'+PPR':>6s}")
        for k in ["WR h1", "WR h2", "WR h3", "WR h4", "TE1", "RB1", "bodies WR", "bodies TE"]:
            c = cells.get(k)
            if not c or c[2] < 8: continue
            sh = c[0] / V; sg = sum(np.sign(c[3][Y]) == np.sign(sh) for Y in YEARS if VY[Y] > 0)
            P(f"    {k:10s} {c[2]:4d} {sh:+10.2f} {('[' + format(engsh[k] / V, '.2f') + ']') if k in engsh else '':>9s} {sg}/7 {c[1]/c[2]:+6.2f}")
            out["shares"][f"{lab}|{k}"] = dict(n=c[2], share=sh, eng=engsh.get(k, 0) / V, sign=int(sg), dppr=c[1] / c[2])
    # per-season shares by lead/sec x healthy rank for the harness folds
    for Y in YEARS:
        for lead in (True, False):
            L = [e for e in EV if e["Y"] == Y and e["A"][0]["lead"] == lead]; V = sum(e["A"][0]["tgt"] for e in L)
            sh = [0.0] * 4
            for e in L:
                wrs = sorted([m for m in e["mem"] if m["pos"] == "WR"], key=lambda m: m["rank"])
                for i, m in enumerate(wrs[:4]): sh[i] += m["at"] - m["bt"] - ctl(Y, "WR", m["rank"], 0)
            out["per_season"][f"{Y}|{'lead' if lead else 'sec'}"] = dict(V=V, dt=sh, n=len(L))

    # ---------- 2. efficiency
    P("\n##### 2. EFFICIENCY (half-PPR receiving): fill-in = healthy WR rank 1-3 (or TE1) in single-WR-absence weeks")
    wl = defaultdict(dict)   # (norm, pos, Y) -> wk -> row
    for nm, lst in cal.WEEKLY.items():
        for rec in lst:
            ps = rec.get("pos")
            if ps not in ("WR", "TE"): continue
            for Y in YEARS:
                for w in rec.get("seasons", {}).get(str(Y), []):
                    if not cal.played(w): continue
                    wl[(nm, ps, Y)][int(w["wk"])] = dict(t=float(w.get("tgt") or 0), r=float(w.get("rec") or 0), y=float(w.get("rcy") or 0), td=float(w.get("rctd") or 0),
                                                        p=(w.get("rec") or 0) * 0.5 + (w.get("rcy") or 0) * 0.1 + (w.get("rctd") or 0) * 6)
    fill = set(); absk = {}
    for e in EV:
        wrs = sorted([m for m in e["mem"] if m["pos"] == "WR"], key=lambda m: m["rank"])
        for m in wrs[:3]: fill.add((m["n"], "WR", e["Y"], e["wk"])); absk[(m["n"], "WR", e["Y"], e["wk"])] = e["A"][0]["n"]
        te = next((m for m in e["mem"] if m["pos"] == "TE" and m["rank"] == 1), None)
        if te: fill.add((te["n"], "TE", e["Y"], e["wk"]))
    lg = {}
    for Y in YEARS:
        for ps in ("WR", "TE"):
            T = defaultdict(float)
            for (nm, p_, y), d in wl.items():
                if p_ == ps and y == Y:
                    for r in d.values():
                        for k in r: T[k] += r[k]
            lg[(Y, ps)] = {k: T[k] / T["t"] for k in ("p", "r", "y", "td")}
    rows = []
    for (nm, ps, Y), d in wl.items():
        for wk, r in d.items():
            pr = [x for w, x in d.items() if w < wk]
            if len(pr) < 2 or r["t"] < 2: continue
            S = {k: sum(x[k] for x in pr) for k in ("t", "r", "y", "td", "p")}
            rows.append(dict(nm=nm, ps=ps, Y=Y, wk=wk, t=r["t"], p=r["p"], r=r["r"], y=r["y"], td=r["td"], pt=S["t"], pp=S["p"], pr=S["r"], py=S["y"], ptd=S["td"],
                             pg=len(pr), fill=(nm, ps, Y, wk) in fill, lg=lg[(Y, ps)], ab=absk.get((nm, ps, Y, wk))))
    def shr(e, K, f="p"): return (e["p" + f] + e["lg"][f] * K) / (e["pt"] + K)
    for ps in ("WR", "TE"):
        for tag, S in (("all weeks", [e for e in rows if e["ps"] == ps]), ("FILL-IN weeks", [e for e in rows if e["ps"] == ps and e["fill"]])):
            best = None
            for K in (5, 10, 20, 40, 80, 160, 320):
                x = np.array([shr(e, K) for e in S]); yv = np.array([e["p"] / e["t"] for e in S]); wv = np.array([e["t"] for e in S])
                A_ = np.c_[np.ones(len(x)), x] * np.sqrt(wv)[:, None]; co = np.linalg.lstsq(A_, yv * np.sqrt(wv), rcond=None)[0]
                err = float(np.sum(wv * (yv - co[0] - co[1] * x) ** 2) / wv.sum())
                if best is None or err < best[0]: best = (err, K, co[0], co[1], float(np.sum(wv * yv) / np.sum(wv * x)))
            P(f"  {ps} {tag} (n {len(S)}): best shrink K {best[1]} targets; week pts/tgt = {best[2]:.3f} + {best[3]:.2f} x shrunk own; actual / shrunk own {best[4]:.3f}")
    F_ = [e for e in rows if e["ps"] == "WR" and e["fill"]]
    sw = lambda f: sum(f(e) for e in F_)
    # absent WR's own season-to-date rates
    ab_rates = defaultdict(float)
    for e in F_:
        d = wl.get((e["ab"], "WR", e["Y"]), {}); pr = [x for w, x in d.items() if w < e["wk"]]
        for k in ("t", "r", "y", "td", "p"): ab_rates[k] += sum(x[k] for x in pr)
    lgw = lambda k: np.mean([e["lg"][k] for e in F_])
    P(f"\n  WR fill-in weeks n {len(F_)}: {sw(lambda e: e['t'])/len(F_):.1f} tgt (own prior {sw(lambda e: e['pt'])/sw(lambda e: e['pg']):.1f}/g)")
    for k, lab in (("p", "half pts/target"), ("r", "catch rate"), ("y", "yds/target"), ("td", "TD/target")):
        P(f"    {lab:16s} FILL-IN {sw(lambda e: e[k])/sw(lambda e: e['t']):.3f} | own s-t-d {sw(lambda e: e['p' + k])/sw(lambda e: e['pt']):.3f} | ABSENT WR s-t-d {ab_rates[k]/max(1, ab_rates['t']):.3f} | league WR {lgw(k):.3f}")
    P("  volume dependence: week pts/target / shrunk own (K 40), by targets this week / own prior targets per game")
    for tag, S in (("all WR weeks", [e for e in rows if e["ps"] == "WR" and e["pt"] > 0]), ("WR fill-in", [e for e in F_ if e["pt"] > 0]), ("TE1 fill-in", [e for e in rows if e["ps"] == "TE" and e["fill"] and e["pt"] > 0])):
        cells = []
        for lo, hi in ((0, 0.8), (0.8, 1.25), (1.25, 1.75), (1.75, 2.5), (2.5, 99)):
            Sx = [e for e in S if lo <= e["t"] / (e["pt"] / e["pg"]) < hi]
            if len(Sx) < 15: continue
            cells.append(f"{lo}-{hi}x: {sum(e['p'] for e in Sx)/sum(e['t']*shr(e, 40) for e in Sx):.3f} (n {len(Sx)})")
        P(f"    {tag:13s} " + " | ".join(cells))
    for lo, hi in ((0, 20), (20, 50), (50, 999)):
        Sx = [e for e in F_ if lo <= e["pt"] < hi]
        if len(Sx) >= 15: P(f"    WR fill-in, own prior targets {lo}-{hi}: n {len(Sx)} actual {sum(e['p'] for e in Sx)/sum(e['t'] for e in Sx):.3f} pts/tgt vs own raw {sum(e['pp'] for e in Sx)/sum(e['pt'] for e in Sx):.3f} vs league {np.mean([e['lg']['p'] for e in Sx]):.3f}")
    json.dump(out, open(os.path.join(HERE, "data", "wr_fill.json"), "w"), indent=1, default=float)
    LOG.close()


if __name__ == "__main__":
    main()
