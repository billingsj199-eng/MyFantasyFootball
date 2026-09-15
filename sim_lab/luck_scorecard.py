#!/usr/bin/env python3
"""
Live grading of the TD-luck layers (Jack 2026-09-15: "grade the luck layers
live, not just in backtest").

Every lock row since 2026-09-15 stores `luck` = the TD-luck points inside
jsMean at lock (engine tdLuckAdj x min(1, iA); RB k .75, WR/TE 1.0, QB pass
.5). For each scored week and cumulatively, this prints per position:

  n        rows with |luck| >= 0.05 (the layer actually moved the number)
  MAE js   jsMean vs actual  |  MAE js-luck   (jsMean - luck) vs actual
  MAE ship shipped mean vs actual | shipped with the luck removed
           (shipped = market blend, so only (1 - w) of the luck is inside it;
           w = tun.wa when stored, else 0.70 when a propMean exists, else 0)
  wins     share of rows where the WITH-luck number was closer
  delta    MAE change from the layer (negative = the layer helped)

Backtests said RB -0.36% / WR-TE -0.93% / QB -0.44% MSE; this is the 2026
reality check. Rows without a `luck` field (W1, locked before the layers)
are reported as not instrumented.

Usage: python luck_scorecard.py --week N     (run by weekly_scorecard.py)
       python luck_scorecard.py               (all weeks with actuals, cumulative)
"""
import argparse, glob, json, os, re, sys, io
import numpy as np
from score_week import HERE, norm, load_actuals

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
POS = ("QB", "RB", "WR", "TE")
MIN_LUCK = 0.05

def rows_for(week):
    p = os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{week}.json")
    if not os.path.exists(p):
        return None, None
    snap = json.load(open(p, encoding="utf-8"))
    act = load_actuals(week)
    if not act:
        return snap.get("players", []), None
    return snap.get("players", []), act

def grade(rows, act):
    out = {}
    for pos in POS:
        js, jsn, sh, shn, y = [], [], [], [], []
        instr = 0
        for r in rows:
            if r.get("pos") != pos or r.get("jsMean") is None or r.get("mean") is None:
                continue
            a = act.get(norm(r["name"]))
            if a is None:
                continue
            if "luck" not in r:
                continue
            instr += 1
            l = float(r.get("luck") or 0.0)
            if abs(l) < MIN_LUCK:
                continue
            w = (r.get("tun") or {}).get("wa")
            if w is None:
                w = 0.70 if r.get("propMean") is not None else 0.0
            js.append(r["jsMean"]); jsn.append(r["jsMean"] - l)
            sh.append(r["mean"]); shn.append(r["mean"] - (1 - w) * l)
            y.append(a)
        if not y:
            out[pos] = {"n": 0, "instr": instr}
            continue
        js, jsn, sh, shn, y = map(np.array, (js, jsn, sh, shn, y))
        out[pos] = {"n": len(y), "instr": instr,
                    "mae_js": float(np.abs(js - y).mean()), "mae_jsn": float(np.abs(jsn - y).mean()),
                    "mae_sh": float(np.abs(sh - y).mean()), "mae_shn": float(np.abs(shn - y).mean()),
                    "wins": float((np.abs(js - y) < np.abs(jsn - y)).mean()),
                    "mean_abs_luck": float(np.abs(js - jsn).mean())}
    return out

def report(label, g):
    print(f"--- {label} ---")
    tot_n = sum(v["n"] for v in g.values())
    if not tot_n:
        instr = sum(v.get("instr", 0) for v in g.values())
        print(f"  no rows where the luck layer moved the number (instrumented rows: {instr}; W1 locks predate the layers)")
        return
    print(f"  {'pos':4s} {'n':>4s} {'|luck|':>7s} {'MAE js':>7s} {'js-luck':>8s} {'delta':>7s} | {'MAE ship':>8s} {'ship-luck':>9s} {'delta':>7s} | {'wins':>5s}")
    for pos in POS:
        v = g[pos]
        if not v["n"]:
            print(f"  {pos:4s} {0:>4d}   (no moved rows; instrumented {v.get('instr', 0)})"); continue
        d1 = v["mae_js"] - v["mae_jsn"]; d2 = v["mae_sh"] - v["mae_shn"]
        print(f"  {pos:4s} {v['n']:>4d} {v['mean_abs_luck']:>7.2f} {v['mae_js']:>7.3f} {v['mae_jsn']:>8.3f} {d1:>+7.3f} | {v['mae_sh']:>8.3f} {v['mae_shn']:>9.3f} {d2:>+7.3f} | {v['wins']:>5.0%}")
    print("  (delta < 0 = the luck layer helped; 'wins' = share of rows where the with-luck model mean was closer)")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None)
    a = ap.parse_args()
    weeks = sorted(int(re.search(r"_w(\d+)\.json$", f).group(1))
                   for f in glob.glob(os.path.join(HERE, "data", "snapshots", "simlab_snapshot_w*.json")))
    if a.week is not None:
        weeks = [w for w in weeks if w <= a.week]
    print(f"=== LUCK LAYER LIVE GRADING (RB k .75 / WR-TE 1.0 / QB pass .5; rows with |luck| >= {MIN_LUCK}) ===")
    all_rows, all_act = [], {}
    for w in weeks:
        rows, act = rows_for(w)
        if rows is None or act is None:
            print(f"--- W{w}: no lock snapshot or no actuals yet ---"); continue
        if a.week is None or w == a.week:
            report(f"W{w}", grade(rows, act))
        # cumulative: prefix rows by week so names don't collide across weeks
        for r in rows:
            rr = dict(r); rr["name"] = f"{w}|{r['name']}"; all_rows.append(rr)
        for k, v in act.items():
            all_act[norm(f"{w}|{k}")] = v
    if len(weeks) > 1:
        report(f"CUMULATIVE W{weeks[0]}-W{weeks[-1]}", grade(all_rows, all_act))

if __name__ == "__main__":
    main()
