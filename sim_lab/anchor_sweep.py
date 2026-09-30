#!/usr/bin/env python3
"""
BOOK-ANCHOR WEIGHT SWEEP over every scored lock, Clay base AND the Clay-free shadow (2026-09-17).

The shipped mean = 70% market / 30% model (engine PROP_W = 0.70; README "Prop anchor"). That weight was a prior, never
fit: no prop history exists before 2026, and the README says to sweep w "after ~4 scored weeks". The shadow (ncMean)
has never been tested with the anchor on top, which is why every shadow-vs-live table on the board reads red.
This tool runs on whatever locks exist (data/snapshots/simlab_snapshot_w*.json) against the actuals
(repo data/weekly_stats_active.js), so it can be re-run every Tuesday:
  market mean  backed out of the lock: propMean = W x market + (1-W) x base  =>  market = (propMean - (1-W) base) / W,
               base = jsMean (the in-season base the engine anchors), rows with propSrc == 'line' only
  sweep        w in 0..1 step .1:  w x market + (1-w) x BASE  for BASE = jsMean (Clay side) and ncMean (shadow), MSE vs actual
  grading      plain and importance-weighted (weight = (projection level / position mean)^2, Jack's top-150 rule),
               by position, and by week so the stability of the best w is visible
Log anchor_sweep.log; results -> data/anchor_sweep.js (SIM_ANCHOR_SWEEP), ZONES tab.
"""
import glob, json, os, re, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from score_week import norm
from diagnose_week import load_rows

W_SHIPPED = 0.70
GRID = [round(x, 1) for x in np.arange(0, 1.01, 0.1)]
OUT = {"updated": time.strftime("%Y-%m-%d %H:%M"), "weeks": [], "clay": [], "shadow": [], "byPos": [], "headToHead": []}


class Tee:
    def __init__(self, *s): self.s = s
    def write(self, x): [f.write(x) for f in self.s]
    def flush(self): [f.flush() for f in self.s]


def main():
    sys.stdout = Tee(sys.stdout, open(os.path.join(HERE, "anchor_sweep.log"), "w", encoding="utf-8"))
    rows = []
    for f in sorted(glob.glob(os.path.join(HERE, "data", "snapshots", "simlab_snapshot_w*.json"))):
        wk = int(re.search(r"_w(\d+)\.json$", f).group(1)); snap = json.load(open(f, encoding="utf-8")); act = load_rows(wk)
        pl = snap["players"]; pl = pl if isinstance(pl, list) else list(pl.values()); n0 = len(rows)
        for p in pl:
            if p.get("pos") not in ("QB", "RB", "WR", "TE") or p.get("propSrc") != "line": continue
            a = act.get(norm(p["name"])); base = p.get("jsMean") if p.get("jsMean") is not None else p.get("clayMean")
            if a is None or base is None or p.get("propMean") is None: continue
            half = a.get("fpts_half") if isinstance(a.get("fpts_half"), (int, float)) else None
            actual = half if half is not None else a.get("fpts")
            if not isinstance(actual, (int, float)): continue
            mkt = (p["propMean"] - (1 - W_SHIPPED) * base) / W_SHIPPED
            rows.append({"wk": wk, "name": p["name"], "pos": p["pos"], "act": float(actual), "base": float(base), "mkt": float(mkt), "nc": p.get("ncMean"), "ship": float(p["mean"])})
        print(f"W{wk}: {len(rows) - n0} lined skill players with actuals (lock preset {snap.get('preset')})")
        OUT["weeks"].append({"wk": wk, "n": len(rows) - n0, "withShadow": sum(1 for r in rows[n0:] if r["nc"] is not None)})
    if not rows: print("no scored lined rows yet"); return
    A = {k: np.array([r[k] for r in rows], dtype=float) for k in ("act", "base", "mkt", "ship")}; pos = np.array([r["pos"] for r in rows]); wk = np.array([r["wk"] for r in rows])
    nc = np.array([np.nan if r["nc"] is None else float(r["nc"]) for r in rows]); has_nc = ~np.isnan(nc)
    lvl = A["ship"].copy()
    for ps in ("QB", "RB", "WR", "TE"):
        m = pos == ps
        if m.any(): lvl[m] = A["ship"][m] / A["ship"][m].mean()
    wt = np.maximum(0.05, lvl) ** 2
    def mse(p, m, w=None): return float(np.average((p[m] - A["act"][m]) ** 2, weights=None if w is None else w[m]))
    note = "actual = weekly_stats_active fpts (half-PPR, same as the lock preset; verified on W1)"
    print(f"\n{len(rows)} rows, {int(has_nc.sum())} with a shadow mean | {note}")
    def sweep(label, basev, mask, store):
        line = []; best = None
        for w in GRID:
            pred = w * A["mkt"] + (1 - w) * basev; e, ew = mse(pred, mask), mse(pred, mask, wt)
            store.append({"base": label, "w": w, "n": int(mask.sum()), "mse": round(e, 3), "wmse": round(ew, 3)}); line.append(f"{w:.1f}:{e:.2f}/{ew:.2f}")
            if best is None or ew < best[1]: best = (w, ew)
        print(f"  {label:26s} n={mask.sum():4d} MSE plain/weighted by w -> " + "  ".join(line) + f"   | best weighted w = {best[0]:.1f}")
        return best[0]
    print("\n=== Anchor weight sweep, Clay-side base (jsMean) ===")
    allm = np.ones(len(rows), bool); bw = sweep("all lined rows", A["base"], allm, OUT["clay"])
    for ps in ("QB", "RB", "WR", "TE"):
        if (pos == ps).sum() >= 20: sweep(ps, A["base"], pos == ps, OUT["byPos"])
    for w_ in sorted(set(wk)):
        if (wk == w_).sum() >= 40 and len(set(wk)) > 1: sweep(f"week {int(w_)}", A["base"], wk == w_, OUT["byPos"])
    ship70 = W_SHIPPED * A["mkt"] + (1 - W_SHIPPED) * A["base"]
    print(f"  shipped 0.7: MSE {mse(ship70, allm):.2f} | market alone {mse(A['mkt'], allm):.2f} | model alone {mse(A['base'], allm):.2f} | bias act/proj shipped {A['act'].mean()/ship70.mean():.3f}, market {A['act'].mean()/A['mkt'].mean():.3f}, model {A['act'].mean()/A['base'].mean():.3f}")
    if has_nc.sum() >= 40:
        print("\n=== Same sweep with the Clay-free SHADOW underneath (rows that carry ncMean) ===")
        sweep("shadow base", nc, has_nc, OUT["shadow"]); sweep("Clay base, same rows", A["base"], has_nc, OUT["shadow"])
        for w in (0.0, 0.5, 0.7, 1.0):
            a = w * A["mkt"] + (1 - w) * nc; b = w * A["mkt"] + (1 - w) * A["base"]
            r = {"w": w, "n": int(has_nc.sum()), "shadowVsClay": round((mse(a, has_nc, wt) / mse(b, has_nc, wt) - 1) * 100, 2), "shadowVsClayPlain": round((mse(a, has_nc) / mse(b, has_nc) - 1) * 100, 2)}
            OUT["headToHead"].append(r); print(f"  w={w:.1f}: anchored shadow vs anchored Clay {r['shadowVsClay']:+.2f}% weighted, {r['shadowVsClayPlain']:+.2f}% plain")
    else:
        print(f"\n(shadow sweep waits for a lock that carries ncMean: {int(has_nc.sum())} rows so far - the W2 lock is the first)")
    OUT["summary"] = (f"{len(rows)} lined player-weeks over {len(OUT['weeks'])} scored week(s): best weighted anchor weight on the Clay-side base = {bw:.1f} (shipped 0.7). "
                      + ("Shadow sweep included." if has_nc.sum() >= 40 else "Shadow sweep starts with the W2 lock (first lock that stores ncMean)."))
    print("\n" + OUT["summary"])
    with open(os.path.join(HERE, "data", "anchor_sweep.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_ANCHOR_SWEEP = " + json.dumps(OUT) + ";\n")
    print("wrote data/anchor_sweep.js")


if __name__ == "__main__":
    main()
