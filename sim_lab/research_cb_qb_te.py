#!/usr/bin/env python3
"""
Do the shadow-corner layers extend to QB / TE? 2019-2025.

Same design as backtest_cb_shadow.py / backtest_cb1_boost.py, run per
position: P=5 blend base, per-position in-season FPA (shipped jsOppMult
design), elite-CB active/out/control buckets + CB1 active/out buckets,
MSE sweeps for a dock on elite-active weeks and a boost on CB1-out weeks.

Expectation going in: QB inherits a fraction of the WR effect (QB points
ARE receiver points; ~55-60% of passing value flows to WRs, and slot/TE
targets are shielded), TE sees ~nothing (S/LB coverage, not CBs).
"""
import numpy as np
import json, os
from collections import defaultdict
from backtest_cb_shadow import load_cb_status, ELITE_CBS, YEARS
from backtest_cb1_boost import load_cb1
from backtest_sim_calibration import (played, weekly_rec, POOL_MIN_PTS,
                                      OPP_ALIAS, WEEKLY)
import backtest_sim_calibration as cal

P = 5

def build_samples(pos):
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"),
                               encoding="utf-8"))
    S = []
    for Y in YEARS:
        if str(Y) not in clay_hist:
            continue
        W = 16 if Y <= 2020 else 17
        for name, c in clay_hist[str(Y)].items():
            if c.get("pos") != pos or (c.get("pts") or 0) < POOL_MIN_PTS:
                continue
            wrec = weekly_rec(name, pos)
            if wrec is None:
                continue
            rows = sorted([(w["wk"], w["fpts"], OPP_ALIAS.get(w.get("opp"), w.get("opp")))
                           for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            hist = []
            for wk, fpts, opp in rows:
                if hist and opp:
                    g = len(hist)
                    base = (P * clay_pg + g * (sum(hist) / g)) / (P + g)
                    S.append({"Y": Y, "wk": int(wk), "opp": opp,
                              "base": base, "act": fpts})
                hist.append(fpts)
    return S

def build_fpa(pos):
    weekly_fpa = defaultdict(dict)
    for recs in WEEKLY.values():
        for rec in recs:
            if rec.get("pos") != pos:
                continue
            for y, rows in rec.get("seasons", {}).items():
                Y = int(y)
                if Y < 2018:
                    continue
                for w in rows:
                    if played(w) and w.get("opp"):
                        d = OPP_ALIAS.get(w["opp"], w["opp"])
                        wkk = int(w["wk"])
                        weekly_fpa[(Y, d)][wkk] = weekly_fpa[(Y, d)].get(wkk, 0) + (w["fpts"] or 0)
    lg = defaultdict(list)
    for (Y, d), wks in weekly_fpa.items():
        if len(wks) >= 10:
            lg[Y].append(sum(wks.values()) / len(wks))
    lg = {Y: float(np.mean(v)) for Y, v in lg.items()}
    def mult(Y, d, wk):
        cur = weekly_fpa.get((Y, d), {})
        past = [w for w in cur if w < wk]
        if len(past) < 4 or Y not in lg:
            return 1.0
        ratio = min(1.25, max(0.8, (sum(cur[w] for w in past) / len(past)) / lg[Y]))
        return 1 + 0.25 * min(1, len(past) / 8) * (ratio - 1)
    return mult

def sweep(sub, label, mults):
    if len(sub) < 30:
        print(f"    {label:24s} n={len(sub)} (too small)")
        return
    a = np.array([s["act"] for s in sub]); b = np.array([s["bf"] for s in sub])
    line = f"    {label:24s} n={len(sub):4d} ratio {a.sum()/b.sum():.3f} |"
    best = None
    for d in mults:
        m = float(np.mean((b * d - a) ** 2))
        line += f" x{d:.2f} {m:.2f}"
        if best is None or m < best[1]:
            best = (d, m)
    print(line + f"  <- best x{best[0]:.2f}")

def main():
    active, out, employs, _ = load_cb_status()
    cb1 = load_cb1()
    for pos in ("QB", "TE"):
        S = build_samples(pos)
        fpa = build_fpa(pos)
        for s in S:
            s["bf"] = s["base"] * fpa(s["Y"], s["opp"], s["wk"])
        print(f"\n================ {pos} ({len(S)} player-weeks) ================")
        A = [s for s in S if active.get((s["Y"], s["opp"], s["wk"]))]
        O = [s for s in S if out.get((s["Y"], s["opp"], s["wk"])) and
                             not active.get((s["Y"], s["opp"], s["wk"]))]
        C = [s for s in S if not employs.get((s["Y"], s["opp"]))]
        print("  elite-CB buckets (dock candidate on ACTIVE):")
        sweep(A, "elite ACTIVE", (1.00, 0.98, 0.96, 0.94, 0.92))
        sweep(O, "elite OUT", (0.96, 1.00, 1.04, 1.08))
        sweep(C, "CONTROL", (0.96, 0.98, 1.00, 1.02, 1.04))
        o1, a1 = [], []
        for s in S:
            r = cb1.get((s["Y"], s["opp"]))
            if not r or s["wk"] not in r["team_wks"]:
                continue
            (a1 if s["wk"] in r["act"] else o1).append(s)
        print("  CB1 buckets (boost candidate on OUT):")
        sweep(o1, "CB1 OUT", (1.00, 1.02, 1.04, 1.06, 1.08))
        sweep(a1, "CB1 ACTIVE", (0.96, 0.98, 1.00, 1.02, 1.04))

if __name__ == "__main__":
    main()
