#!/usr/bin/env python3
"""
Live grading of the PECKING-ORDER DOCKS (Jack 2026-09-29: WR 3rd+ x0.92, RB 2nd+ x0.97,
engine peckDock; backtest_role_age.py said WR 3rd+ .888 of projection 7/7 seasons, RB 2nd
.953 6/7).

Lock rows since 2026-09-29 store `peck` (the multiplier inside jsMean, absent = 1) and
`peckRank` (his rank among teammates at the position that week). Per week + cumulative,
for the docked rows of each position:

  act/proj   actual / model mean WITH the dock, and without it (jsMean / peck)
  MAE js     with vs without; MAE ship = the shipped number, where only (1 - w) of the
             dock is inside (w = tun.wa, the market weight applied at lock)
  wins       share of rows where the docked number was closer

Rows without `peckRank` (locked before the layer) are not instrumented.
Usage: python peck_scorecard.py --week N     (run by weekly_scorecard.py)
       python peck_scorecard.py               (all weeks, cumulative)
"""
import argparse, glob, json, os, re, sys, io
import numpy as np
from score_week import HERE, norm, load_actuals

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
POS = ("WR", "RB")

def collect(week):
    p = os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{week}.json")
    if not os.path.exists(p):
        return None
    act = load_actuals(week)
    if not act:
        return None
    out = []
    for r in json.load(open(p, encoding="utf-8")).get("players", []):
        if r.get("pos") not in POS or r.get("jsMean") is None or r.get("mean") is None or "peckRank" not in r:
            continue
        a = act.get(norm(r["name"]))
        if a is None:
            continue
        m = float(r.get("peck") or 1.0)
        w = (r.get("tun") or {}).get("wa")
        if w is None:
            w = 0.0
        js = float(r["jsMean"]); js0 = js / m if m > 0 else js
        out.append({"pos": r["pos"], "rank": r["peckRank"], "peck": m, "act": float(a), "js": js, "js0": js0,
                    "ship": float(r["mean"]), "ship0": float(r["mean"]) + (1 - w) * (js0 - js)})
    return out

def report(label, rows):
    print(f"--- {label} ---")
    if not rows:
        print("  no instrumented rows (locks before 2026-09-29 carry no peckRank)"); return
    for pos in POS:
        d = [r for r in rows if r["pos"] == pos and r["peck"] < 0.9995]
        rest = [r for r in rows if r["pos"] == pos and r["peck"] >= 0.9995]
        if not d:
            print(f"  {pos}: no docked rows (undocked {len(rest)})"); continue
        a = np.array([r["act"] for r in d]); js = np.array([r["js"] for r in d]); js0 = np.array([r["js0"] for r in d])
        sh = np.array([r["ship"] for r in d]); sh0 = np.array([r["ship0"] for r in d])
        print(f"  {pos} docked n={len(d):3d}  actual/model with dock {a.sum()/js.sum():.3f}, without {a.sum()/js0.sum():.3f} | "
              f"MAE js {np.abs(js-a).mean():.3f} vs {np.abs(js0-a).mean():.3f} without ({np.abs(js-a).mean()-np.abs(js0-a).mean():+.3f}) | "
              f"MAE ship {np.abs(sh-a).mean():.3f} vs {np.abs(sh0-a).mean():.3f} ({np.abs(sh-a).mean()-np.abs(sh0-a).mean():+.3f}) | "
              f"wins {100*(np.abs(js-a) < np.abs(js0-a)).mean():.0f}%")
        if rest:
            ra = np.array([r["act"] for r in rest]); rj = np.array([r["js"] for r in rest])
            print(f"  {pos} undocked n={len(rest):3d}  actual/model {ra.sum()/rj.sum():.3f}")
    print("  (negative MAE change = the dock helped; backtest: WR 3rd+ .888 of projection, RB 2nd .953)")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None)
    a = ap.parse_args()
    weeks = sorted(int(re.search(r"_w(\d+)\.json$", f).group(1))
                   for f in glob.glob(os.path.join(HERE, "data", "snapshots", "simlab_snapshot_w*.json")))
    if a.week is not None:
        weeks = [w for w in weeks if w <= a.week]
    print("=== PECKING-ORDER DOCK LIVE GRADING (WR 3rd+ x0.92, RB 2nd+ x0.97, fading in from 4 to 5 half-PPR) ===")
    allr = []
    for w in weeks:
        rows = collect(w)
        if rows is None:
            print(f"--- W{w}: no lock snapshot or no actuals yet ---"); continue
        if a.week is None or w == a.week:
            report(f"W{w}", rows)
        allr += rows
    if len(weeks) > 1:
        report(f"CUMULATIVE W{weeks[0]}-W{weeks[-1]}", allr)

if __name__ == "__main__":
    main()
