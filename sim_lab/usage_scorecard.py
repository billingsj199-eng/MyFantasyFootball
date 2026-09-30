#!/usr/bin/env python3
"""
Live grading of the LIVE USAGE EVIDENCE (engine liveUsage, 2026-09-29: WR from game 1, TE from game 4;
backtest_usage_live.py said WR MSE -0.76% 7/7, TE -0.58% 5/7).

Lock rows store `useLam` (weight on usage in the evidence), `usePg` (usage-implied points per game) and
`jsNoUse` (the model mean the same row would have had without it). Per week + cumulative, per position,
on the rows the layer moved by 0.05+: MAE / MSE of jsMean vs jsNoUse, and of the shipped number with the
layer's share taken back out (only (1 - w) of the model is inside the shipped number; w = tun.wa).

Usage: python usage_scorecard.py --week N     (run by weekly_scorecard.py)
       python usage_scorecard.py               (all weeks, cumulative)
"""
import argparse, glob, json, os, re, sys, io
import numpy as np
from score_week import HERE, norm, load_actuals
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
POS = ("WR", "TE")

def collect(week):
    p = os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{week}.json")
    if not os.path.exists(p): return None
    act = load_actuals(week)
    if not act: return None
    out = []
    for r in json.load(open(p, encoding="utf-8")).get("players", []):
        if r.get("pos") not in POS or r.get("jsNoUse") is None or r.get("jsMean") is None or r.get("mean") is None: continue
        a = act.get(norm(r["name"]))
        if a is None: continue
        w = (r.get("tun") or {}).get("wa") or 0.0
        if r.get("propMean") is None: w = 0.0
        js, js0 = float(r["jsMean"]), float(r["jsNoUse"])
        out.append({"pos": r["pos"], "act": float(a), "js": js, "js0": js0, "ship": float(r["mean"]), "ship0": float(r["mean"]) + (1 - w) * (js0 - js)})
    return out

def report(label, rows):
    print(f"--- {label} ---")
    if not rows:
        print("  no instrumented rows (locks before 2026-09-29 carry no jsNoUse)"); return
    for pos in POS:
        d = [r for r in rows if r["pos"] == pos and abs(r["js"] - r["js0"]) >= 0.05]
        if not d:
            print(f"  {pos}: no rows moved (TE starts at game 4)"); continue
        a, js, js0, sh, sh0 = (np.array([r[k] for r in d]) for k in ("act", "js", "js0", "ship", "ship0"))
        up = js > js0
        print(f"  {pos} n={len(d):3d} avg |move| {np.abs(js-js0).mean():.2f} | model MAE {np.abs(js-a).mean():.3f} vs {np.abs(js0-a).mean():.3f} without ({np.abs(js-a).mean()-np.abs(js0-a).mean():+.3f}) "
              f"MSE {100*(((js-a)**2).mean()/((js0-a)**2).mean()-1):+.2f}% | shipped MAE {np.abs(sh-a).mean():.3f} vs {np.abs(sh0-a).mean():.3f} ({np.abs(sh-a).mean()-np.abs(sh0-a).mean():+.3f}) | wins {100*(np.abs(js-a) < np.abs(js0-a)).mean():.0f}%")
        for lab, m in (("raised by usage", up), ("lowered by usage", ~up)):
            if m.sum() >= 5:
                print(f"      {lab:17s} n={int(m.sum()):3d}  actual {a[m].mean():.2f}  with {js[m].mean():.2f}  without {js0[m].mean():.2f}")
    print("  (negative change = the usage evidence helped)")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--week", type=int, default=None); a = ap.parse_args()
    weeks = sorted(int(re.search(r"_w(\d+)\.json$", f).group(1)) for f in glob.glob(os.path.join(HERE, "data", "snapshots", "simlab_snapshot_w*.json")))
    if a.week is not None: weeks = [w for w in weeks if w <= a.week]
    print("=== LIVE USAGE EVIDENCE GRADING (targets + routes + snaps as part of the evidence; WR from game 1, TE from game 4) ===")
    allr = []
    for w in weeks:
        rows = collect(w)
        if rows is None:
            print(f"--- W{w}: no lock snapshot or no actuals yet ---"); continue
        if a.week is None or w == a.week: report(f"W{w}", rows)
        allr += rows
    if len(weeks) > 1: report(f"CUMULATIVE W{weeks[0]}-W{weeks[-1]}", allr)

if __name__ == "__main__":
    main()
