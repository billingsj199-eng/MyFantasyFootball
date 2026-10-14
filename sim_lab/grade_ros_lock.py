#!/usr/bin/env python3
"""
GRADE THE REST-OF-SEASON LOCKS (2026-10-08). export_site_proj.js freezes, once per week, every player's rest-of-season
per-game number from the next week on (simlab_ros_w<N>.json: model mean `ros`, Clay-form `rosClay`, shadow `rosShadow`,
per-week `w`). This grades each lock against the games actually played since: target = the player's half-PPR average over
his played games in weeks > N (min --games), per position: MAE, bias (actual / projected), weekly-rank rho within position,
and seasons-style wins per week block. Baselines: the player's season-to-date PPG at the lock and the week-N weekly number
from the weekly snapshot. Usage: python grade_ros_lock.py [--week 5] [--games 3]   (no --week = every lock on disk)
"""
import argparse, glob, json, os, re
from collections import defaultdict
import numpy as np
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__))
from score_week import norm
REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--week", type=int); ap.add_argument("--games", type=int, default=3); a = ap.parse_args()
    raw = open(os.path.join(REPO, "data", "weekly_stats_active.js"), encoding="utf-8").read(); d = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    logs = {}
    for nm, rec in d.items():
        if rec.get("pos") not in ("QB", "RB", "WR", "TE"): continue
        logs[norm(nm)] = {int(w["wk"]): float(w["fpts"]) for w in (rec.get("seasons") or {}).get("2026", []) if isinstance(w.get("fpts"), (int, float)) and w.get("opp")}
    files = sorted(glob.glob(os.path.join(HERE, "data", "snapshots", "simlab_ros_w*.json")), key=lambda f: int(re.search(r"_w(\d+)", f).group(1)))
    if a.week: files = [f for f in files if int(re.search(r"_w(\d+)", f).group(1)) == a.week]
    if not files: print("no rest-of-season locks on disk"); return
    for f in files:
        L = json.load(open(f, encoding="utf-8")); N = L["week"]
        snap = {}
        try:
            S = json.load(open(os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{N}.json"), encoding="utf-8"))
            for p in S["players"]: snap[norm(p["name"])] = p.get("mean")
        except Exception: pass
        rows = []
        for p in L["players"]:
            k = norm(p["name"]); gl = logs.get(k, {})
            fut = [v for w, v in gl.items() if w > N]; past = [v for w, v in gl.items() if w <= N]
            if len(fut) < a.games: continue
            # QB FLOOR (2026-10-09): w[wk][3] = shadow floor multiplier inside ncMean (locks from week 6 on); the number without it
            sh0 = None; wv = [v for v in (p.get("w") or {}).values() if isinstance(v, list) and len(v) >= 4 and isinstance(v[2], (int, float)) and v[3]]
            if wv: sh0 = float(np.mean([v[2] / v[3] for v in wv]))
            qbf = p.get("rosQbf")
            ros0 = (p["ros"] - (p["rosShadow"] - sh0)) if (sh0 is not None and isinstance(p.get("rosShadow"), (int, float))) else None
            rows.append(dict(name=p["name"], pos=p["pos"], act=float(np.mean(fut)), n=len(fut), ros=p["ros"], clay=p.get("rosClay"), shadow=p.get("rosShadow"), std=(float(np.mean(past)) if past else None), wkn=snap.get(k), qbf=qbf, ros0=ros0))
        print(f"\n=== ROS lock week {N} (locked {L.get('lockedAt', '')[:16]}, base {L.get('base')}): {len(rows)} players with {a.games}+ games played since ===")
        if not rows: continue
        CANDS = [("model (ros)", "ros"), ("Clay form (rosClay)", "clay"), ("shadow (rosShadow)", "shadow"), ("season-to-date PPG at lock", "std"), ("week-N weekly number", "wkn")]
        for pos in ("ALL", "QB", "RB", "WR", "TE"):
            rs = [r for r in rows if pos == "ALL" or r["pos"] == pos]
            if len(rs) < 8: continue
            line = f"  {pos:4s} n{len(rs):4d} |"
            for lab, key in CANDS:
                v = [(r[key], r["act"]) for r in rs if isinstance(r[key], (int, float))]
                if len(v) < 8: line += f" {lab}: n/a |"; continue
                pr = np.array([x for x, _ in v]); ac = np.array([y for _, y in v])
                rho = spearmanr(pr, ac).correlation if pos != "ALL" else np.nan
                line += f" {lab}: MAE {np.mean(np.abs(pr - ac)):.2f} bias {ac.sum()/pr.sum():.3f}" + (f" rho {rho:.3f}" if pos != "ALL" else "") + " |"
            print(line)
        # QB FLOOR graded on the floored QBs: the locked number with vs without the floor
        fq = [r for r in rows if r["pos"] == "QB" and isinstance(r.get("qbf"), (int, float)) and r["qbf"] > 1.0005 and r.get("ros0") is not None]
        if any(isinstance(r.get("qbf"), (int, float)) for r in rows):
            if fq:
                ac = np.array([r["act"] for r in fq]); w1 = np.array([r["ros"] for r in fq]); w0 = np.array([r["ros0"] for r in fq])
                print(f"  QB FLOOR (shadow, later weeks, k .70) n{len(fq)}: MAE with {np.mean(np.abs(w1 - ac)):.2f} vs without {np.mean(np.abs(w0 - ac)):.2f} "
                      f"({np.mean(np.abs(w1 - ac)) - np.mean(np.abs(w0 - ac)):+.2f}) | bias with {ac.sum()/w1.sum():.3f}, without {ac.sum()/w0.sum():.3f} | "
                      f"floor closer on {100*np.mean(np.abs(w1 - ac) < np.abs(w0 - ac)):.0f}%  (backtest: rest of season -3.1%, 6/7)")
            else:
                print("  QB FLOOR: no floored QBs with enough games played since this lock")
        else:
            print("  QB FLOOR: lock predates the floor fields (locks from week 6 on carry them)")
        # head-to-head model vs Clay form per player
        hh = [(abs(r["ros"] - r["act"]) < abs(r["clay"] - r["act"])) for r in rows if isinstance(r["clay"], (int, float))]
        if hh: print(f"  model closer than the Clay form on {100*np.mean(hh):.1f}% of {len(hh)} players")


if __name__ == "__main__":
    main()
