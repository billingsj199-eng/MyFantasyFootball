#!/usr/bin/env python3
"""
2026 W1-4 grade of the CLAY-FREE STAT SHAPE against Clay's (the only seasons where Clay's per-stat lines exist = the lock
snapshots' comps / compsU). For every locked player with an actual stat line: Clay shape (comps), Clay + usage (compsU), and the
Clay-free shape (this season before the week x g + last season x K1 + position shape x K2, scaled to the SAME points as the
lock's comps so only the split differs) - per-stat points-weighted absolute error, and the vs-books stat-prop hit rate (raw).
Usage: python grade_stat_shape.py [--k1 4] [--k2 2] [--weeks 1,2,3,4]      -> log grade_stat_shape.log
"""
import argparse, json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_sim_calibration as cal
from vs_books_week import STAT_KEYS, MIN_LINE, consensus, norm
from diagnose_week import load_rows
STATS = ("py", "ptd", "ry", "rtd", "rec", "rcy", "rctd"); VAL = {"py": 0.04, "ptd": 4.0, "ry": 0.1, "rtd": 6.0, "rec": 0.5, "rcy": 0.1, "rctd": 6.0}
POSSTATS = {"QB": ("py", "ptd", "ry", "rtd"), "RB": ("ry", "rtd", "rec", "rcy", "rctd"), "WR": ("ry", "rtd", "rec", "rcy", "rctd"), "TE": ("rec", "rcy", "rctd")}
pts_of = lambda L: sum(VAL[k] * L.get(k, 0.0) for k in STATS)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--k1", type=float, default=4); ap.add_argument("--k2", type=float, default=2); ap.add_argument("--weeks", default="1,2,3,4"); ap.add_argument("--level", default="clay"); a = ap.parse_args()
    LOG = open(os.path.join(HERE, "grade_stat_shape.log"), "w", encoding="utf-8")
    def P(s=""): print(s); LOG.write(s + chr(10)); LOG.flush()
    # position shape from the 2025 pool (8+ games), per half-PPR point
    raw = open(os.path.join(cal.REPO, "data", "weekly_stats_active.js"), encoding="utf-8").read(); d = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    acc = {ps: defaultdict(float) for ps in POSSTATS}; ptsum = defaultdict(float); logs25 = {}; logs26 = {}
    for nm, rec in d.items():
        ps = rec.get("pos")
        if ps not in POSSTATS: continue
        g25 = [w for w in (rec.get("seasons") or {}).get("2025", []) if cal.played(w) and isinstance(w.get("fpts"), (int, float))]
        g26 = [w for w in (rec.get("seasons") or {}).get("2026", []) if cal.played(w) and isinstance(w.get("fpts"), (int, float))]
        key = norm(nm); logs25[key] = [{s: float(w.get(s) or 0) for s in STATS} for w in g25]; logs26[key] = {int(w["wk"]): {s: float(w.get(s) or 0) for s in STATS} for w in g26}
        if len(g25) >= 8:
            for w in logs25[key]:
                for s in STATS: acc[ps][s] += w[s]
                ptsum[ps] += pts_of(w)
    shape = {ps: {s: acc[ps][s] / ptsum[ps] for s in STATS} for ps in POSSTATS if ptsum[ps] > 0}
    P("position shape per half-PPR point (2025 pool): " + " | ".join(f"{ps} " + " ".join(f"{s} {shape[ps][s]:.3f}" for s in POSSTATS[ps]) for ps in POSSTATS))
    # expected components per game (SIM_XFP_2026 in data/sim_routes.js): skill rows [tgt, xRec, xRecYds, xRecTD, car, xRushYds, xRushTD], QB rows [att, xPassYds, xPassTD, car, xRushYds, xRushTD, xInt]
    rj = open(os.path.join(HERE, "data", "sim_routes.js"), encoding="utf-8").read(); i0 = rj.index("SIM_XFP_2026 = ") + len("SIM_XFP_2026 = "); XF = json.JSONDecoder().raw_decode(rj, i0)[0]
    LAM = {"ry": 0.25, "rec": 0.5, "rcy": {"RB": 0.75, "WR": 0.25, "TE": 0.25}}; PU = 5.0
    def usage_update(key, ps, wkn, CF, A_rows, td=False, qbpass=False, P=None):
        xr = XF.get(key) or XF.get(key.title()); rows = [xr["w"][k] for k in (xr or {}).get("w", {}) if int(k) < wkn and xr["w"][k]] if xr else []
        if not rows or not A_rows: return None
        gN = max(len(A_rows), len(rows)); out = dict(CF); A = {s: float(np.mean([r[s] for r in A_rows])) for s in STATS}
        if ps == "QB": u = {"ry": sum(r[4] for r in rows) / gN, "rtd": sum(r[5] for r in rows) / gN, "py": sum(r[1] for r in rows) / gN, "ptd": sum(r[2] for r in rows) / gN}
        else: u = {"rec": sum(r[1] for r in rows) / gN, "rcy": sum(r[2] for r in rows) / gN, "rctd": sum(r[3] for r in rows) / gN, "ry": sum(r[5] for r in rows) / gN, "rtd": sum(r[6] for r in rows) / gN}
        keys = ["ry"] if ps == "QB" else ["ry", "rec", "rcy"]
        if td: keys += (["rtd"] if ps == "QB" else ["rtd", "rctd"])
        if qbpass and ps == "QB": keys += ["py", "ptd"]
        for k in keys:
            if k not in u: continue
            lm = LAM.get(k, 0.5); lm = lm[ps] if isinstance(lm, dict) else lm
            PP = PU if P is None else P; ev = lm * u[k] + (1 - lm) * A[k]; out[k] = (PP * CF[k] + len(A_rows) * ev) / (PP + len(A_rows)) if (PP + len(A_rows)) > 0 else CF[k]
        return out
    CANDS = ("Clay (comps)", "Clay + usage (compsU)", "Clay + usage P5 rebuilt", "Clay + usage P2", "Clay + usage P1", "in-season only (P0, usage-blended)", "hybrid: Clay+usage <3 games, in-season only 3+", f"Clay-free K1 {a.k1:g} K2 {a.k2:g}", "Clay-free + usage (ry/rec/rcy)", "Clay-free A only (this season)")
    E = {c: defaultdict(list) for c in CANDS}; EG = {c: defaultdict(list) for c in CANDS}   # EG keyed by (pos, stat, gbucket)
    calls = defaultdict(lambda: defaultdict(list))   # candidate -> stat -> hits
    nrows = 0
    for wkn in [int(x) for x in a.weeks.split(",")]:
        snap = json.load(open(os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{wkn}.json"), encoding="utf-8")); actw = load_rows(wkn)
        for p in snap["players"]:
            ps = p.get("pos")
            if ps not in POSSTATS or not p.get("comps"): continue
            key = norm(p["name"]); w = actw.get(key)
            if not w: continue
            actual = {s: float(w.get(s) or 0) for s in STATS}; comps = p["comps"]; lvl0 = pts_of(comps)
            if lvl0 <= 0: continue
            lvl = lvl0 if a.level == "clay" else (p.get("ncMean") if a.level == "shadow" else p.get("jsMean"))
            if not isinstance(lvl, (int, float)) or lvl <= 0: continue
            if a.level != "clay": comps = {s: float(comps.get(s, 0) or 0) * lvl / lvl0 for s in STATS}; cu0 = p.get("compsU"); p["compsU"] = ({s: float(cu0.get(s, 0) or 0) * lvl / pts_of(cu0) for s in STATS} if cu0 and pts_of(cu0) > 0 else None)
            A_rows = [logs26.get(key, {})[k] for k in sorted(logs26.get(key, {})) if k < wkn]; B_rows = logs25.get(key, [])
            A = {s: float(np.mean([r[s] for r in A_rows])) for s in STATS} if A_rows else None
            B = {s: float(np.mean([r[s] for r in B_rows])) for s in STATS} if len(B_rows) >= 4 else None
            C = {s: shape[ps][s] * lvl for s in STATS} if ps in shape else None
            num = {s: 0.0 for s in STATS}; den = 0.0
            for L_, w_ in ((A, len(A_rows)), (B, a.k1 if B else 0), (C, a.k2 if C else 0)):
                if L_ is None or w_ <= 0: continue
                for s in STATS: num[s] += w_ * L_[s]
                den += w_
            if den <= 0: continue
            CF = {s: num[s] / den for s in STATS}; p0 = pts_of(CF)
            if p0 <= 0: continue
            CF = {s: CF[s] * lvl / p0 for s in STATS}
            AO = None
            if A and pts_of(A) > 0: AO = {s: A[s] * lvl / pts_of(A) for s in STATS}
            CF0 = {s: num[s] / den for s in STATS}
            def scl(L_):
                if L_ is None: return None
                q = pts_of(L_); return {s: L_[s] * lvl / q for s in STATS} if q > 0 else None
            CU1 = scl(usage_update(key, ps, wkn, CF0, A_rows)); CU2 = scl(usage_update(key, ps, wkn, CF0, A_rows, td=True)); CU3 = scl(usage_update(key, ps, wkn, CF0, A_rows, td=True, qbpass=True))
            compsPG = {s_: float(comps.get(s_, 0) or 0) for s_ in STATS}   # Clay's per-game line at the lock (the compsU prior)
            CP5 = scl(usage_update(key, ps, wkn, compsPG, A_rows, P=5.0)); CP2 = scl(usage_update(key, ps, wkn, compsPG, A_rows, P=2.0)); CP1 = scl(usage_update(key, ps, wkn, compsPG, A_rows, P=1.0)); CP0 = scl(usage_update(key, ps, wkn, compsPG, A_rows, P=0.0))
            gA = len(A_rows); HYB = (CP0 if (gA >= 3 and CP0) else (CP5 or comps))
            cands = {"Clay (comps)": comps, "Clay + usage (compsU)": p.get("compsU") or comps, "Clay + usage P5 rebuilt": CP5 or comps, "Clay + usage P2": CP2 or comps, "Clay + usage P1": CP1 or comps, "in-season only (P0, usage-blended)": CP0 or comps, "hybrid: Clay+usage <3 games, in-season only 3+": HYB, f"Clay-free K1 {a.k1:g} K2 {a.k2:g}": CF, "Clay-free + usage (ry/rec/rcy)": CU1 or CF, "Clay-free A only (this season)": AO}
            gb = "g0" if gA == 0 else ("g1-2" if gA <= 2 else "g3+")
            nrows += 1
            for c, L_ in cands.items():
                if L_ is None: continue
                for s in POSSTATS[ps]: E[c][(ps, s)].append(abs(float(L_.get(s, 0) or 0) - actual[s]) * VAL[s]); EG[c][(ps, s, gb)].append(abs(float(L_.get(s, 0) or 0) - actual[s]) * VAL[s])
                if p.get("lines"):
                    for lk, sk in STAT_KEYS.items():
                        if lk not in STATS: continue
                        line, nb = consensus(p["lines"], lk); mc = L_.get(lk)
                        if line is None or not isinstance(mc, (int, float)) or line < MIN_LINE.get(lk, 0): continue
                        av = actual[sk]
                        if av == line: continue
                        calls[c][lk].append(1 if ((mc > line) == (av > line)) else 0)
    P(f"\n=== 2026 weeks {a.weeks}: {nrows:,} locked player-weeks with an actual line ===")
    for ps in POSSTATS:
        P(f"\n--- {ps}: points-weighted abs error per stat (lower is better) ---")
        for c in E:
            cells = [f"{s} {np.mean(E[c][(ps, s)]):.3f}" for s in POSSTATS[ps] if E[c][(ps, s)]]
            tot = float(np.mean([np.sum([E[c][(ps, s)][i] for s in POSSTATS[ps]]) for i in range(len(E[c][(ps, POSSTATS[ps][0])]))])) if E[c][(ps, POSSTATS[ps][0])] else np.nan
            P(f"  {c:34s} n{len(E[c][(ps, POSSTATS[ps][0])]):4d} | total {tot:.3f} | " + " ".join(cells))
    P("\n--- by GAMES PLAYED at the lock (total points-weighted abs error per row), the Clay-prior question ---")
    for gb in ("g0", "g1-2", "g3+"):
        for ps in POSSTATS:
            line = f"  {gb:5s} {ps:3s}"
            for c in CANDS:
                v = [np.sum([EG[c][(ps, s, gb)][i] for s in POSSTATS[ps]]) for i in range(len(EG[c][(ps, POSSTATS[ps][0], gb)]))] if EG[c][(ps, POSSTATS[ps][0], gb)] else []
                if len(v) >= 20: line += f" | {c[:22]}: {np.mean(v):.3f} (n{len(v)})"
            P(line)
    P("\n--- vs the books: stat-prop call hit rate (raw mean vs line), by candidate ---")
    for c in calls:
        allh = [h for lk in calls[c] for h in calls[c][lk]]
        P(f"  {c:34s} all {100*np.mean(allh):.1f}% (n{len(allh)}) | " + " ".join(f"{lk} {100*np.mean(calls[c][lk]):.1f}% (n{len(calls[c][lk])})" for lk in calls[c]))
    P("\nLimitations: 4 weeks; every candidate scaled to the lock's Clay points (split only); compsU only updates ry / rec / rcy; raw mean-vs-median calls (no skew adjustment).")
    LOG.close()


if __name__ == "__main__":
    main()
