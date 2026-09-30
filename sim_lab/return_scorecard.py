#!/usr/bin/env python3
"""
Live grading of the RETURN RAMP (engine returnDock, 2026-09-30: QB x0.95 after one missed game; x0.90 first
game back after 2-3; x0.85 / x0.92 / x0.96 after 4+; QB/RB/WR) and of the QB STARTER FLOOR (engine qbFloor:
quarterbacks projected under the starting-QB mean pulled 30% of the way up). Lock rows store `ret` / `qbf` (absent = 1).
Per week + cumulative: the ramp rows' actual / model with and without the ramp, MAE both ways, wins.
Usage: python return_scorecard.py --week N     (run by weekly_scorecard.py)
"""
import argparse, glob, json, os, re, sys, io
import numpy as np
from score_week import HERE, norm, load_actuals
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

FIELDS = (("ret", "RETURN RAMP", ("QB", "RB", "WR")), ("qbf", "QB STARTER FLOOR", ("QB",)))

def collect(week, field="ret", poss=("QB", "RB", "WR")):
    p = os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{week}.json")
    if not os.path.exists(p): return None
    act = load_actuals(week)
    if not act: return None
    out = []
    for r in json.load(open(p, encoding="utf-8")).get("players", []):
        if r.get("pos") not in poss or r.get("jsMean") is None or r.get("mean") is None: continue
        m = r.get(field)
        if m is None or abs(m - 1) < 0.0005: continue
        a = act.get(norm(r["name"]))
        if a is None: continue
        w = (r.get("tun") or {}).get("wa") or 0.0
        if r.get("propMean") is None: w = 0.0
        js = float(r["jsMean"]); js0 = js / m
        out.append({"pos": r["pos"], "name": r["name"], "ret": m, "act": float(a), "js": js, "js0": js0, "ship": float(r["mean"]), "ship0": float(r["mean"]) + (1 - w) * (js0 - js)})
    return out

def report(label, rows, what="ramp"):
    print(f"--- {label} ---")
    if not rows:
        print(f"  no {what} rows (locks before 2026-09-30 carry none, or nothing applied)"); return
    a, js, js0, sh, sh0 = (np.array([r[k] for r in rows]) for k in ("act", "js", "js0", "ship", "ship0"))
    print(f"  n={len(rows)}  actual/model with ramp {a.sum()/js.sum():.3f}, without {a.sum()/js0.sum():.3f} | model MAE {np.abs(js-a).mean():.3f} vs {np.abs(js0-a).mean():.3f} ({np.abs(js-a).mean()-np.abs(js0-a).mean():+.3f}) | shipped MAE {np.abs(sh-a).mean():.3f} vs {np.abs(sh0-a).mean():.3f} ({np.abs(sh-a).mean()-np.abs(sh0-a).mean():+.3f}) | wins {100*(np.abs(js-a) < np.abs(js0-a)).mean():.0f}%")
    for r in sorted(rows, key=lambda r: -r["js0"])[:10]:
        print(f"    {r['name']:22s} {r['pos']} x{r['ret']:.2f}  model {r['js0']:.1f} -> {r['js']:.1f}  actual {r['act']:.1f}")
    print(f"  (negative MAE change = the {what} helped; backtest: ramp -2.8% MSE on its rows 7/7, floor -2.33% on QB rows 7/7)")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--week", type=int, default=None); a = ap.parse_args()
    weeks = sorted(int(re.search(r"_w(\d+)\.json$", f).group(1)) for f in glob.glob(os.path.join(HERE, "data", "snapshots", "simlab_snapshot_w*.json")))
    if a.week is not None: weeks = [w for w in weeks if w <= a.week]
    for field, title, poss in FIELDS:
        print(f"=== {title} LIVE GRADING ===")
        allr = []
        for w in weeks:
            rows = collect(w, field, poss)
            if rows is None: print(f"--- W{w}: no lock snapshot or no actuals yet ---"); continue
            if a.week is None or w == a.week: report(f"W{w}", rows, title.lower())
            allr += rows
        if len(weeks) > 1: report(f"CUMULATIVE W{weeks[0]}-W{weeks[-1]}", allr, title.lower())

if __name__ == "__main__":
    main()
