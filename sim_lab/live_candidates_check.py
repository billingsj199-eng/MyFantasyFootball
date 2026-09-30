#!/usr/bin/env python3
"""
LIVE read on the pending base candidates (2026-09-30): the weekly scorecard leaves the blend columns blank
because the auto-lock rows do not store the rank mix, but every piece is on disk - lock rows carry the live
blend (jsMean), the Clay-free shadow (ncMean), the book-anchored number (propMean) and the market weight
applied (tun.wa); the archived consensus file carries ESPN's half-PPR projection.

Each candidate swaps the pre-book BASE and keeps the same book anchor on top, exactly how the engine builds
rmFinal:  final = propMean + (1 - w) x (candidate base - live base)   when the row was line-anchored.

  live            today's shipped number
  shadow          Clay-free shadow as the base
  70/30           0.7 shadow + 0.3 live blend            (tier B of project_live_candidate)
  70/30 + ESPN    half that, half ESPN                   (tier C)
  live + ESPN     half live blend, half ESPN
  ESPN / sites    the sites' own numbers, no anchor      (reference)
Weeks with ncMean on the lock rows and an archived consensus file (W2 on). Half-PPR, shipped mean >= 5.
"""
import json, os, sys, io
import numpy as np
from score_week import HERE, norm, load_actuals
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

def rows_for(wk):
    sp = os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{wk}.json"); cp = os.path.join(HERE, "data", f"weekly_consensus_w{wk}.json")
    if not (os.path.exists(sp) and os.path.exists(cp)): return []
    act = load_actuals(wk); cons = {norm(k): v for k, v in json.load(open(cp, encoding="utf-8"))["players"].items()}
    out = []
    for p in json.load(open(sp, encoding="utf-8"))["players"]:
        if p.get("pos") not in ("QB", "RB", "WR", "TE") or (p.get("mean") or 0) < 5: continue
        a = act.get(norm(p["name"])); c = cons.get(norm(p["name"]))
        if a is None or c is None or p.get("ncMean") is None or p.get("jsMean") is None: continue
        e = (c.get("e") or [None])[0]; h = c.get("h"); f = (c.get("f") or [None])[0]
        if e is None or h is None: continue
        js, nc = float(p["jsMean"]), float(p["ncMean"])
        w = (p.get("tun") or {}).get("wa") if (p.get("propSrc") == "line" and p.get("propMean") is not None) else None
        def fin(base):
            return max(0.0, float(p["propMean"]) + (1 - w) * (base - js)) if w is not None else base
        b73 = 0.7 * nc + 0.3 * js
        out.append({"wk": wk, "pos": p["pos"], "act": float(a), "live": float(p["mean"]), "shadow": fin(nc), "70/30": fin(b73),
                    "70/30 + ESPN": fin(0.5 * b73 + 0.5 * e), "live + ESPN": fin(0.5 * js + 0.5 * e), "shadow + ESPN": fin(0.5 * nc + 0.5 * e),
                    "ESPN (no anchor)": float(e), "site consensus": float(h), "FantasyPros": float(f) if f is not None else float(h)})
    return out

def spear(rs, k):
    v = []
    for wk in sorted(set(r["wk"] for r in rs)):
        for pos in ("QB", "RB", "WR", "TE"):
            x = [r for r in rs if r["wk"] == wk and r["pos"] == pos]
            if len(x) >= 8:
                a = np.argsort(np.argsort([r[k] for r in x])); b = np.argsort(np.argsort([r["act"] for r in x]))
                v.append(np.corrcoef(a, b)[0, 1])
    return float(np.mean(v)) if v else float("nan")

def main():
    rows = []
    for wk in range(1, 19): rows += rows_for(wk)
    wks = sorted(set(r["wk"] for r in rows))
    KEYS = ["live", "shadow", "70/30", "70/30 + ESPN", "shadow + ESPN", "live + ESPN", "ESPN (no anchor)", "site consensus", "FantasyPros"]
    print(f"=== live read on the base candidates: weeks {wks}, {len(rows)} player-weeks (half-PPR, shipped >= 5) ===")
    print(f"  {'number':20s} {'MAE':>6s} {'vs live':>8s} {'bias':>6s} {'RMSE':>6s} {'rank':>6s} {'closer than live':>17s}")
    a = np.array([r["act"] for r in rows]); live = np.array([r["live"] for r in rows])
    for k in KEYS:
        v = np.array([r[k] for r in rows]); e = v - a
        w = int((np.abs(e) < np.abs(live - a) - 0.1).sum()); l = int((np.abs(e) > np.abs(live - a) + 0.1).sum())
        print(f"  {k:20s} {np.abs(e).mean():6.3f} {100*(np.abs(e).mean()/np.abs(live-a).mean()-1):+7.2f}% {e.mean():+6.2f} {np.sqrt((e**2).mean()):6.2f} {spear(rows, k):6.3f} "
              + ("" if k == "live" else f"{w:4d}-{l:<4d} ({100*w/max(1,w+l):.0f}%)"))
    print("\n  by position: MAE | weekly rank correlation")
    print("  " + " " * 20 + "".join(f"{p:>16s}" for p in ("QB", "RB", "WR", "TE")))
    for k in KEYS:
        cells = []
        for pos in ("QB", "RB", "WR", "TE"):
            x = [r for r in rows if r["pos"] == pos]
            cells.append(f"{np.mean([abs(r[k]-r['act']) for r in x]):6.2f} | {spear(x, k):+.2f}")
        print(f"  {k:20s}" + "".join(f"{c:>16s}" for c in cells))
    print("\n  by week: MAE")
    for k in KEYS:
        print(f"  {k:20s}" + "".join(f"  W{wk} {np.mean([abs(r[k]-r['act']) for r in rows if r['wk']==wk]):5.2f}" for wk in wks))
    print("\n  n by position:", {p: sum(1 for r in rows if r["pos"] == p) for p in ("QB", "RB", "WR", "TE")})

if __name__ == "__main__":
    main()
