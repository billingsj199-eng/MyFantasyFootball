"""2026 read for P-20261110-1 (QB rest-of-season tilt for missing pass-catchers). READ-ONLY research, writes _tmp/ only.
For each graded ROS lock (simlab_ros_w5..w7: 3+ games since), the QB's team share of season-to-date targets (weeks before the
lock's first projected week) held by players who did NOT play that first projected week = 'vacated targets'. Grade = QB's actual
PPG over weeks he played from the first projected week through the last scored week vs the locked 'ros' number.
Not a test (one season, few rows): compares act/proj by bucket with the history pattern (1.03 -> .97 -> .93) and checks what the
proposed centred e .10 tilt would have done to MAE on these rows."""
import json, os, sys, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = r"E:\MyFantasyFootball\MyFantasyFootball Files"
raw = open(os.path.join(REPO, "data", "weekly_stats_active.js"), encoding="utf-8").read(); D = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
LAST = int(sys.argv[1]) if len(sys.argv) > 1 else 10
def games(name):
    p = D.get(name); return {g["wk"]: g for g in (p or {}).get("seasons", {}).get("2026", [])} if p else {}
def played(g): return g is not None and (g.get("ra", 0) or g.get("tgt", 0) or g.get("fpts", 0) or g.get("pa", 0) or g.get("py", 0))
# team target totals per player
tgt = {}  # tm -> {name: {wk: tgt}}
for nm, p in D.items():
    if p.get("pos") not in ("WR", "TE", "RB"): continue
    for g in p.get("seasons", {}).get("2026", []):
        if g.get("tm"): tgt.setdefault(g["tm"], {}).setdefault(nm, {})[g["wk"]] = g.get("tgt", 0) or 0
rows = []
for L in range(5, 11):
    f = os.path.join(HERE, "data", "snapshots", f"simlab_ros_w{L}.json")
    if not os.path.exists(f): continue
    S = json.load(open(f, encoding="utf-8")); first = min(int(k) for p in S["players"] for k in p.get("w", {})) if S["players"] else L + 1
    if LAST - first + 1 < 3: continue
    for p in S["players"]:
        if p.get("pos") != "QB" or not isinstance(p.get("ros"), (int, float)) or p["ros"] < 12: continue
        G = games(p["name"]); wk = [w for w in range(first, LAST + 1) if played(G.get(w))]
        if len(wk) < 3: continue
        tm = p.get("tm"); T = tgt.get(tm, {}); tot = vac = 0.0
        for nm, by in T.items():
            f0 = wk[0]  # QB's first played projected week (skips byes)
            s = sum(v for w, v in by.items() if w < f0); tot += s
            if s and not played(games(nm).get(f0)): vac += s
        if tot <= 0: continue
        act = float(np.mean([G[w]["fpts"] for w in wk]))
        rows.append(dict(lock=L, name=p["name"], tm=tm, ros=p["ros"], act=act, vac=vac / tot, n=len(wk)))
print(f"2026 QB ROS rows (locks with 3+ graded weeks through W{LAST}, ros >= 12): {len(rows)}")
B = [(0, .05), (.05, .15), (.15, .30), (.30, 1.01)]
for lo, hi in B:
    r = [x for x in rows if lo <= x["vac"] < hi]
    if r: print(f"  vac [{lo:.2f},{hi:.2f}) n {len(r):3d}  act/proj {sum(x['act'] for x in r) / sum(x['ros'] for x in r):.3f}")
v = np.array([x["vac"] for x in rows]); a = np.array([x["act"] for x in rows]); pr = np.array([x["ros"] for x in rows])
if len(rows):
    for e in (0.0, 0.10, 0.15):  # proposal form: x (1 - e x (min(v, .6) - .18))
        c = pr * (1 - e * (np.minimum(v, .6) - .18))
        print(f"  proposal tilt e {e:.2f}: MAE {np.mean(np.abs(a - c)):.3f}  MSE {np.mean((a - c) ** 2):.2f}  closer on {np.mean(np.abs(a - c) < np.abs(a - pr)) if e else float('nan'):.0%}")
    print("  largest vacated:")
    for x in sorted(rows, key=lambda x: -x["vac"])[:10]:
        print(f"    W{x['lock']} {x['name']:24s} {x['tm']:4s} vac {x['vac']:.2f}  ros {x['ros']:5.1f}  act {x['act']:5.1f} ({x['n']} g)")
