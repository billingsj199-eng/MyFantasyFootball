#!/usr/bin/env python3
"""
Deep-dive on one scored week — WHERE the weekly model's error comes from,
so tuning decisions rest on evidence. Builds on score_week.py's data.

Sections
  1. bias + MAE by position, every model                (systematic lean?)
  2. K + DST scoring (kicker_weekly / dst_weekly logs)   (fitted Vegas models, first live grade)
  3. PROP_W sweep — market anchor weight, reconstructed  (market = (prop − .3·base)/.7)
  4. JS × consensus blend sweep                          (is a blend better than either?)
  5. tier buckets by shipped mean                        (studs vs mid vs flyers)
  6. team implied-total terciles                         (Vegas elasticity check)
  7. rank accuracy: Spearman + top-12 overlap per pos    (start/sit usefulness)
  8. stat-component bias (comps vs actual stat lines)    (which stat drives the miss)
  9. band calibration by tier                            (sigma scaling)

Usage: python diagnose_week.py --week 1 [--min-proj 5]
"""
import argparse, json, os, re
import numpy as np
from score_week import REPO, HERE, norm, load_consensus, stats

def load_rows(week):
    raw = open(os.path.join(REPO, "data", "weekly_stats_active.js"), encoding="utf-8").read()
    d = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    out = {}
    for name, rec in d.items():
        for w in (rec.get("seasons") or {}).get("2026") or []:
            if w.get("wk") == week and isinstance(w.get("fpts"), (int, float)):
                out[norm(name)] = w
    return out

def load_k(week):
    raw = open(os.path.join(REPO, "data", "kicker_weekly.js"), encoding="utf-8").read()
    d = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    out = {}
    for name, yrs in d.items():
        for w in (yrs.get("2026") or []):
            if w.get("wk") == week and isinstance(w.get("fpts"), (int, float)):
                out[norm(name)] = float(w["fpts"])
    return out

def load_dst(week):
    raw = open(os.path.join(REPO, "data", "dst_weekly.js"), encoding="utf-8").read()
    d = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    out = {}
    for tm, yrs in d.items():
        rows = yrs.get("2026") if isinstance(yrs, dict) else None
        for w in (rows or []):
            if w.get("wk") == week and isinstance(w.get("fpts"), (int, float)):
                out[tm.upper()] = float(w["fpts"])
    return out

def spearman(a, b):
    a, b = np.array(a, float), np.array(b, float)
    ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1]) if len(a) > 2 else float("nan")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--min-proj", type=float, default=5.0)
    a = ap.parse_args()
    snap = json.load(open(os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{a.week}.json"), encoding="utf-8"))
    act = load_rows(a.week); cons, _ = load_consensus(a.week)
    kact, dact = load_k(a.week), load_dst(a.week)

    rows = []
    for p in snap["players"]:
        if p["pos"] not in ("QB", "RB", "WR", "TE") or (p.get("mean") or 0) < a.min_proj:
            continue
        k = norm(p["name"]); w = act.get(k)
        if not w:
            continue
        c = cons.get(k) or {}
        rows.append(dict(p, act=float(w["fpts"]), stat=w, cons=c.get("h"), espn=(c.get("e") or [None])[0]))
    print(f"W{a.week}: {len(rows)} skill rows scored (mean >= {a.min_proj})")

    MODELS = [("mean", "SHIPPED"), ("jsMean", "JS"), ("clayMean", "Clay"), ("propMean", "prop"), ("cons", "consensus"), ("espn", "ESPN")]
    def col(rs, key): return [(r[key], r["act"]) for r in rs if isinstance(r.get(key), (int, float))]

    print("\n=== 1. bias (proj − act) and MAE by position ===")
    print("  pos   n  " + "  ".join(f"{lab:>14s}" for _, lab in MODELS))
    for pos in ("QB", "RB", "WR", "TE", "ALL"):
        rs = rows if pos == "ALL" else [r for r in rows if r["pos"] == pos]
        line = f"  {pos:3s} {len(rs):3d}  "
        for key, _ in MODELS:
            pr = col(rs, key)
            if len(pr) >= 5:
                n, mae, bias, _ = stats([x for x, _ in pr], [y for _, y in pr]); line += f"  {bias:+5.2f} / {mae:5.2f}"
            else:
                line += "  " + " " * 14
        print(line)

    print("\n=== 2. K + DST (fitted Vegas models, first live grade) ===")
    for pos, amap in (("K", kact), ("DST", dact)):
        rs = []
        for p in snap["players"]:
            if p["pos"] != pos:
                continue
            key = norm(p["name"]) if pos == "K" else (p.get("tm") or "").upper()
            if key in amap:
                c = cons.get(norm(p["name"])) or {}
                rs.append(dict(p, act=amap[key], cons=c.get("h")))
        if not rs:
            print(f"  {pos}: no actuals matched ({len(amap)} logs)"); continue
        line = f"  {pos:3s} n={len(rs):2d}  "
        for key, lab in (("mean", "SHIPPED"), ("clayMean", "model"), ("propMean", "prop"), ("cons", "consensus")):
            pr = col(rs, key)
            if len(pr) >= 5:
                n, mae, bias, _ = stats([x for x, _ in pr], [y for _, y in pr]); line += f"{lab} bias {bias:+5.2f} MAE {mae:5.2f} | "
        band = [r for r in rs if isinstance(r.get("p10"), (int, float))]
        if band:
            inside = sum(1 for r in band if r["p10"] <= r["act"] <= r["p90"])
            line += f"band inside {100*inside/len(band):.0f}%"
        print(line)
        print("    proj mean {:.2f} vs actual mean {:.2f}; Spearman {:+.2f}".format(
            np.mean([r["mean"] for r in rs]), np.mean([r["act"] for r in rs]), spearman([r["mean"] for r in rs], [r["act"] for r in rs])))

    print("\n=== 3. PROP_W sweep (market anchor weight; shipped .70) ===")
    anch = [r for r in rows if r.get("propSrc") == "line" and isinstance(r.get("propMean"), (int, float)) and isinstance(r.get("jsMean"), (int, float)) and abs(r["propMean"] - r["jsMean"]) > 0.05]
    print(f"  {len(anch)} rows with a direct-line anchor that moved the mean")
    if anch:
        base = np.array([r["jsMean"] for r in anch]); prop = np.array([r["propMean"] for r in anch]); act_ = np.array([r["act"] for r in anch])
        market = (prop - 0.3 * base) / 0.7
        print(f"  market-implied MAE {np.mean(np.abs(market-act_)):.3f} | model base MAE {np.mean(np.abs(base-act_)):.3f}")
        print("  w:   " + "  ".join(f"{w:.2f}" for w in (0, .3, .5, .6, .7, .8, .9, 1.0)))
        print("  MAE: " + "  ".join(f"{np.mean(np.abs((1-w)*base + w*market - act_)):.2f}" for w in (0, .3, .5, .6, .7, .8, .9, 1.0)))
        for pos in ("QB", "RB", "WR", "TE"):
            m = np.array([r["pos"] == pos for r in anch])
            if m.sum() >= 8:
                print(f"    {pos} n={m.sum():3d}: " + "  ".join(f"{np.mean(np.abs((1-w)*base[m] + w*market[m] - act_[m])):.2f}" for w in (0, .3, .5, .7, .9, 1.0)))

    print("\n=== 4. JS × consensus blend (MAE) ===")
    bl = [r for r in rows if isinstance(r.get("cons"), (int, float))]
    js = np.array([r["jsMean"] for r in bl]); cn = np.array([r["cons"] for r in bl]); ac = np.array([r["act"] for r in bl]); sh = np.array([r["mean"] for r in bl])
    print("  w(cons): " + "  ".join(f"{w:.1f}" for w in (0, .25, .5, .75, 1)) + "   | shipped")
    print("  MAE:     " + "  ".join(f"{np.mean(np.abs((1-w)*js + w*cn - ac)):.2f}" for w in (0, .25, .5, .75, 1)) + f"   | {np.mean(np.abs(sh-ac)):.2f}")

    print("\n=== 5. tier buckets by shipped mean: bias / MAE / act÷proj ===")
    for lo, hi in ((5, 9), (9, 13), (13, 17), (17, 99)):
        rs = [r for r in rows if lo <= r["mean"] < hi]
        if len(rs) < 6:
            continue
        pr = np.array([r["mean"] for r in rs]); ac = np.array([r["act"] for r in rs])
        print(f"  [{lo:2d},{hi:2d}) n={len(rs):3d}  bias {np.mean(pr-ac):+5.2f}  MAE {np.mean(np.abs(pr-ac)):5.2f}  act/proj {ac.sum()/pr.sum():.3f}")

    print("\n=== 6. team implied-total terciles: act÷proj (Vegas elasticity check) ===")
    imp = sorted(set(r["implied"] for r in rows if isinstance(r.get("implied"), (int, float))))
    if len(imp) >= 6:
        t1, t2 = imp[len(imp) // 3], imp[2 * len(imp) // 3]
        for lab, f in (("low ", lambda x: x < t1), ("mid ", lambda x: t1 <= x < t2), ("high", lambda x: x >= t2)):
            rs = [r for r in rows if isinstance(r.get("implied"), (int, float)) and f(r["implied"])]
            pr = np.array([r["mean"] for r in rs]); ac = np.array([r["act"] for r in rs])
            print(f"  {lab} implied (n={len(rs):3d}, avg {np.mean([r['implied'] for r in rs]):.1f}): act/proj {ac.sum()/pr.sum():.3f}  bias {np.mean(pr-ac):+5.2f}")

    print("\n=== 7. rank accuracy per position: Spearman | top-12 overlap (of 12) ===")
    print("  pos   " + "  ".join(f"{lab:>14s}" for _, lab in MODELS))
    for pos in ("QB", "RB", "WR", "TE"):
        rs = [r for r in rows if r["pos"] == pos]
        line = f"  {pos:3s}   "
        for key, _ in MODELS:
            sub = [r for r in rs if isinstance(r.get(key), (int, float))]
            if len(sub) < 12:
                line += " " * 16; continue
            sp = spearman([r[key] for r in sub], [r["act"] for r in sub])
            top_p = set(r["name"] for r in sorted(sub, key=lambda r: -r[key])[:12]); top_a = set(r["name"] for r in sorted(sub, key=lambda r: -r["act"])[:12])
            line += f"  {sp:+.2f} | {len(top_p & top_a):2d}/12   "
        print(line)

    print("\n=== 8. stat-component bias: projected comps vs actual stat line (per game, played rows) ===")
    CMAP = {"py": "py", "ptd": "ptd", "ry": "ry", "rtd": "rtd", "rec": "rec", "rcy": "rcy", "rctd": "rctd"}
    for pos in ("QB", "RB", "WR", "TE"):
        rs = [r for r in rows if r["pos"] == pos and isinstance(r.get("comps"), dict)]
        if len(rs) < 8:
            continue
        parts = []
        for ck, sk in CMAP.items():
            pv = [r["comps"].get(ck) for r in rs]; av = [r["stat"].get(sk) for r in rs]
            pairs = [(p, s) for p, s in zip(pv, av) if isinstance(p, (int, float)) and isinstance(s, (int, float))]
            if len(pairs) >= 8 and sum(p for p, _ in pairs) > 0:
                pm = np.mean([p for p, _ in pairs]); am = np.mean([s for _, s in pairs])
                parts.append(f"{ck} {pm:.1f}→{am:.1f} ({(am/pm-1)*100:+.0f}%)")
        print(f"  {pos}: " + " | ".join(parts))

    print("\n=== 9. band calibration by tier (inside / below p10 / above p90) ===")
    for lo, hi in ((5, 9), (9, 13), (13, 17), (17, 99)):
        rs = [r for r in rows if lo <= r["mean"] < hi and isinstance(r.get("p10"), (int, float))]
        if len(rs) < 8:
            continue
        b = sum(1 for r in rs if r["act"] < r["p10"]); u = sum(1 for r in rs if r["act"] > r["p90"])
        w = np.mean([(r["p90"] - r["p10"]) / r["mean"] for r in rs])
        print(f"  [{lo:2d},{hi:2d}) n={len(rs):3d}  inside {100*(len(rs)-b-u)/len(rs):4.0f}%  below {100*b/len(rs):4.0f}%  above {100*u/len(rs):4.0f}%   avg (p90−p10)/mean {w:.2f}")

if __name__ == "__main__":
    main()
