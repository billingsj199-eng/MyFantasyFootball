#!/usr/bin/env python3
"""
GAME-LOG STAT LINES (Jack 2026-10-09: "build the stat lines from game logs"). The engine's per-stat split (comps: pass yds /
pass TD / rush yds / rush TD / rec / rec yds / rec TD) came from Clay's preseason sheet. This builds each player's split from
HIS OWN game logs, as graded in grade_stat_shape.py (V2 2026-10-09, 2026 W1-5 locks):
  line = (g x this season's per-game line + K1 x 3-season own history (2023-25, season weights .5/.3/.2) + 1 x TIERED position
          shape at his level) / (g + K1 + 1), stored PER HALF-PPR POINT (shape only; the engine keeps the level).
  K1 by position (grade picks): QB 16, RB 8, WR 4, TE 16.
Grade vs what ships (Clay + usage, compsU): QB 8.76 vs 8.85 (better; QB rushing usage hurts compsU), RB 6.37 vs 6.21, WR
5.35 vs 5.20, TE 4.09 vs 4.05 (worse) -> `on` = ["QB"] only; RB / WR / TE re-grade after week 8 (grade_stat_shape.py).
Writes data/sim_stat_shape.js (window.SIM_STAT_SHAPE = {on, recipe, players: {engine-norm name: {pos, sh, g, lvl}}}).
Run by refresh_data.py; --dry-run prints a sample.
"""
import json, os, re, sys, time
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_sim_calibration as cal

ON = ["QB"]
K1 = {"QB": 16, "RB": 8, "WR": 4, "TE": 16}; K2 = 1.0
HW = {2025: 0.5, 2024: 0.3, 2023: 0.2}; TIERS = (0, 6, 10, 14, 99)
STATS = ("py", "ptd", "ry", "rtd", "rec", "rcy", "rctd")
VAL = {"py": 0.04, "ptd": 4.0, "ry": 0.1, "rtd": 6.0, "rec": 0.5, "rcy": 0.1, "rctd": 6.0}
POS = ("QB", "RB", "WR", "TE")
pts_of = lambda L: sum(VAL[k] * L.get(k, 0.0) for k in STATS)
tier_of = lambda v: max(i for i in range(len(TIERS) - 1) if v >= TIERS[i])


def jsnorm(n):
    """engine.js norm(): lowercase, drop . and ', - -> space, drop suffixes, squeeze spaces"""
    n = str(n or "").lower().replace(".", "").replace("'", "").replace("-", " ")
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return re.sub(r"\s+", " ", n).strip()


def main():
    dry = "--dry-run" in sys.argv
    tacc = defaultdict(lambda: defaultdict(float)); tpts = defaultdict(float); rows = {}
    for nmk, recs in cal.WEEKLY.items():
        for rec in recs:
            ps = rec.get("pos")
            if ps not in POS: continue
            name = rec.get("name") or nmk
            tot = defaultdict(float); wsum = 0.0
            for Y, wY in HW.items():
                gl = [w for w in (rec.get("seasons") or {}).get(str(Y), []) if cal.played(w)]
                if len(gl) < 4: continue
                pg = {s: float(np.mean([float(w.get(s) or 0) for w in gl])) for s in STATS}
                for s in STATS: tot[s] += wY * pg[s]
                wsum += wY
                lv = pts_of(pg)
                if lv > 0 and len(gl) >= 8:
                    t = tier_of(lv)
                    for w in gl:
                        L = {s: float(w.get(s) or 0) for s in STATS}
                        for s in STATS: tacc[(ps, t)][s] += L[s]
                        tpts[(ps, t)] += pts_of(L)
            g26 = [w for w in (rec.get("seasons") or {}).get("2026", []) if cal.played(w)]
            A = {s: float(np.mean([float(w.get(s) or 0) for w in g26])) for s in STATS} if g26 else None
            H = {s: tot[s] / wsum for s in STATS} if wsum > 0 else None
            if A is None and H is None: continue
            rows[(nmk, ps)] = (name, A, len(g26), H)
    tshape = {k: {s: tacc[k][s] / tpts[k] for s in STATS} for k in tacc if tpts[k] > 0}
    out = {}
    for (nmk, ps), (name, A, g, H) in rows.items():
        k1 = K1[ps]
        num = {s: 0.0 for s in STATS}; den = 0.0
        for L, w in ((A, g), (H, k1 if H else 0)):
            if L is None or w <= 0: continue
            for s in STATS: num[s] += w * L[s]
            den += w
        if den <= 0: continue
        lvl = pts_of({s: num[s] / den for s in STATS})
        if lvl <= 0: continue
        TS = tshape.get((ps, tier_of(lvl)))
        if TS:
            for s in STATS: num[s] += K2 * TS[s] * lvl
            den += K2
        CF = {s: num[s] / den for s in STATS}; p0 = pts_of(CF)
        if p0 <= 0: continue
        out[jsnorm(name)] = {"pos": ps, "sh": {s: round(CF[s] / p0, 5) for s in STATS if CF[s] > 0}, "g": g, "lvl": round(lvl, 2)}
    payload = {"updated": time.strftime("%Y-%m-%d %H:%M"), "on": ON, "recipe": {"K1": K1, "K2": K2, "seasons": HW, "tiers": TIERS}, "players": out}
    byp = defaultdict(int)
    for v in out.values(): byp[v["pos"]] += 1
    print(f"stat shapes: {len(out):,} players ({dict(byp)}); engine uses positions {ON}")
    for nm in ("josh allen", "lamar jackson", "jalen hurts", "jared goff", "cam ward"):
        v = out.get(nm)
        if v: print(f"  {nm:16s} g26 {v['g']} lvl {v['lvl']:5.1f}/g  per half-pt: " + " ".join(f"{s} {v['sh'].get(s, 0):.3f}" for s in ("py", "ptd", "ry", "rtd")))
    if dry: return
    with open(os.path.join(HERE, "data", "sim_stat_shape.js"), "w", encoding="utf-8") as f:
        f.write(f"// AUTO-GENERATED by build_stat_shape.py {payload['updated']} - per-player stat split from own game logs (per half-PPR point)\n")
        f.write("window.SIM_STAT_SHAPE = " + json.dumps(payload, separators=(",", ":")) + ";\n")
    print("wrote data/sim_stat_shape.js")


if __name__ == "__main__":
    main()
