#!/usr/bin/env python3
"""
Live grading of the 2026-10-07 layers from the lock rows (run by weekly_scorecard.py; first graded week = W5).

Lock rows since 2026-10-07 store:
  bb / jsPre     base blend: jsMean = bb x ncMean + (1 - bb) x jsPre  (jsPre = the Clay-blend model before the blend)
  vol            volume-context multiplier inside jsMean (WR / TE; absent = 1) - from 10-07 evening this includes the box-count factor
  health         banged-up prior lift in points per game (WR / TE; absent = 0)
  useHurt        banged-up games given half weight in the usage inputs (count; absent = 0)
Per week + cumulative:
  BASE BLEND     MAE / bias of the shipped mean, the blended model (jsMean), the Clay-blend model (jsPre) and the shadow
                 (ncMean) on the same rows, by position; share of rows where the blend beat the Clay-blend model.
  VOLUME         rows with vol != 1: act / model with and without the multiplier (jsMean / vol), MAE both ways, wins.
  HEALTH LIFT    rows with a lift: act / model vs the rest of the position (descriptive - the lift is inside the prior).
  HURT USAGE     rows with 1+ hurt game in the usage inputs: act / model vs the rest (descriptive).
Usage: python layers_scorecard.py --week N   |   python layers_scorecard.py  (all weeks)
"""
import argparse, glob, json, os, re, sys, io
import numpy as np
from score_week import HERE, norm, load_actuals
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
POS4 = ("QB", "RB", "WR", "TE")


def collect(week):
    p = os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{week}.json")
    if not os.path.exists(p): return None
    act = load_actuals(week)
    if not act: return None
    out = []
    for r in json.load(open(p, encoding="utf-8")).get("players", []):
        if r.get("pos") not in POS4 or r.get("mean") is None: continue
        a = act.get(norm(r["name"]))
        if a is None: continue
        out.append({"pos": r["pos"], "act": float(a), "ship": float(r["mean"]), "js": r.get("jsMean"), "pre": r.get("jsPre"), "nc": r.get("ncMean"), "bb": r.get("bb") or 0,
                    "vol": float(r.get("vol") or 1.0), "health": float(r.get("health") or 0.0), "useHurt": int(r.get("useHurt") or 0), "name": r["name"]})
    return out


def mae(p, a): return float(np.mean(np.abs(np.asarray(p) - np.asarray(a)))) if len(a) else float("nan")
def bias(p, a): return float(np.mean(np.asarray(p) - np.asarray(a))) if len(a) else float("nan")


def report(label, rows):
    print(f"--- {label} ---")
    if not rows: print("  no rows"); return
    inst = [r for r in rows if r["bb"] and r["pre"] is not None and r["js"] is not None]
    if not inst: print("  BASE BLEND: no instrumented rows (locks before 2026-10-07 carry no bb / jsPre)")
    else:
        print(f"  BASE BLEND ({len(inst)} rows locked with the blend)   {'pos':3s} {'n':>4s} | {'MAE ship':>8s} {'MAE blend':>9s} {'MAE Clay-model':>14s} {'MAE shadow':>10s} | {'bias blend':>10s} {'bias Clay':>9s} {'bias shadow':>11s} | blend beats Clay-model")
        for ps in POS4 + ("ALL",):
            d = [r for r in inst if ps == "ALL" or r["pos"] == ps]
            if len(d) < 5: continue
            a = [r["act"] for r in d]; sh = [r["ship"] for r in d]; js = [r["js"] for r in d]; pre = [r["pre"] for r in d]; nc = [r["nc"] if r["nc"] is not None else r["pre"] for r in d]
            wins = np.mean([abs(r["js"] - r["act"]) < abs(r["pre"] - r["act"]) for r in d])
            print(f"      {ps:3s} {len(d):4d} | {mae(sh, a):8.2f} {mae(js, a):9.2f} {mae(pre, a):14.2f} {mae(nc, a):10.2f} | {bias(js, a):+10.2f} {bias(pre, a):+9.2f} {bias(nc, a):+11.2f} | {100*wins:.0f}%")
    v = [r for r in rows if abs(r["vol"] - 1) > 1e-6 and r["js"] is not None]
    if v:
        print(f"  VOLUME CONTEXT ({len(v)} rows with a multiplier)")
        for ps in ("WR", "TE"):
            d = [r for r in v if r["pos"] == ps]
            if len(d) < 5: continue
            a = np.array([r["act"] for r in d]); js = np.array([r["js"] for r in d]); js0 = js / np.array([r["vol"] for r in d])
            dn = [r for r in d if r["vol"] < 1]; up = [r for r in d if r["vol"] > 1]
            print(f"      {ps}: act/model with {a.sum()/js.sum():.3f} without {a.sum()/js0.sum():.3f} | MAE with {mae(js, a):.2f} without {mae(js0, a):.2f} | closer with: {100*np.mean(np.abs(js-a) < np.abs(js0-a)):.0f}% | docked rows {len(dn)} act/model {sum(r['act'] for r in dn)/max(1e-9, sum(r['js'] for r in dn)):.3f} | boosted rows {len(up)} act/model {sum(r['act'] for r in up)/max(1e-9, sum(r['js'] for r in up)):.3f}")
    h = [r for r in rows if r["health"] > 0 and r["js"] is not None]
    if h:
        print(f"  HEALTH LIFT ({len(h)} lifted rows; descriptive - the lift sits inside the prior)")
        for ps in ("WR", "TE"):
            d = [r for r in h if r["pos"] == ps]; rest = [r for r in rows if r["pos"] == ps and r["health"] <= 0 and r["js"] is not None]
            if len(d) < 3: continue
            print(f"      {ps}: lifted n{len(d)} act/model {sum(r['act'] for r in d)/sum(r['js'] for r in d):.3f} (mean lift {np.mean([r['health'] for r in d]):.2f}/g) | rest n{len(rest)} act/model {sum(r['act'] for r in rest)/max(1e-9, sum(r['js'] for r in rest)):.3f}")
    u = [r for r in rows if r["useHurt"] > 0 and r["js"] is not None]
    if u:
        print(f"  HURT GAMES IN USAGE ({len(u)} rows; descriptive)")
        for ps in ("WR", "TE"):
            d = [r for r in u if r["pos"] == ps]; rest = [r for r in rows if r["pos"] == ps and r["useHurt"] == 0 and r["js"] is not None]
            if len(d) < 3: continue
            print(f"      {ps}: n{len(d)} act/model {sum(r['act'] for r in d)/sum(r['js'] for r in d):.3f} | rest n{len(rest)} act/model {sum(r['act'] for r in rest)/max(1e-9, sum(r['js'] for r in rest)):.3f}")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--week", type=int); a = ap.parse_args()
    weeks = [a.week] if a.week else sorted(int(re.search(r"_w(\d+)\.json$", f).group(1)) for f in glob.glob(os.path.join(HERE, "data", "snapshots", "simlab_snapshot_w*.json")))
    allrows = []
    for w in weeks:
        rows = collect(w)
        if rows is None: print(f"--- week {w}: no snapshot or no actuals ---"); continue
        report(f"week {w}", rows); allrows += rows
    if len(weeks) > 1: report("cumulative", allrows)


if __name__ == "__main__":
    main()
