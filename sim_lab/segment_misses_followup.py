import json, math, statistics as st, numpy as np
from collections import defaultdict
rows = [r for r in json.load(open("segrows.json")) if r["lim"] is not True]
print("healthy rows", len(rows))
def young(r): return (r["pos"] in ("WR","RB") and r["age"] and r["age"] <= 23) or (r["pos"]=="TE" and r["age"] and r["age"]<=24) or (r["pos"]=="QB" and r["age"] and r["age"]<=25)
def vet(r): return r["exp"] is not None and r["exp"] >= 8
def second(r): return r["pos"] != "QB" and r["rank"] >= 2
# A. multivariate: relative error (proj-act)/proj? use points error
X, y = [], []
for r in rows:
    X.append([1, 1 if second(r) else 0, 1 if young(r) else 0, 1 if vet(r) else 0, 1 if r["proj"] < 9 else 0, 1 if (r["implied"] or 0) >= 26 else 0])
    y.append(r["err"])
X = np.array(X, float); y = np.array(y)
b, *_ = np.linalg.lstsq(X, y, rcond=None)
res = y - X @ b; s2 = res @ res / (len(y) - X.shape[1]); se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
print("\n=== A. which traits survive when tested together (points too high, healthy weeks) ===")
for n, bi, si in zip(["baseline (lead option, prime age, 9+ proj)", "2nd/3rd option on team", "young", "veteran 9+ yrs", "projection under 9", "team implied 26+"], b, se):
    print(f"  {n:44s} {bi:+5.2f}  (t {bi/si:+4.1f})")
print("\n=== B. role x age, act/proj (healthy) ===")
for pos in ("RB", "WR"):
    for lab, f in (("lead", lambda r: r["rank"] == 1), ("2nd/3rd", lambda r: r["rank"] >= 2)):
        for al, g in (("young", young), ("not young", lambda r: not young(r))):
            x = [r for r in rows if r["pos"] == pos and f(r) and g(r)]
            if len(x) >= 6:
                e = [r["err"] for r in x]
                print(f"  {pos} {lab:8s} {al:10s} n={len(x):3d} bias {st.mean(e):+5.2f} (t {st.mean(e)/(st.pstdev(e)/math.sqrt(len(e))):+4.1f}) act/proj {sum(r['act'] for r in x)/sum(r['proj'] for r in x):.2f}")
allr = json.load(open("segrows.json"))
print("\n=== C. do misses PERSIST? W1-2 average error vs W3 error, same player (healthy weeks only) ===")
by = defaultdict(dict)
for r in rows: by[r["name"]][r["wk"]] = r
pairs = [((v[1]["err"] + v[2]["err"]) / 2, v[3]["err"], v[3]) for v in by.values() if 1 in v and 2 in v and 3 in v]
a = np.array([p[0] for p in pairs]); c = np.array([p[1] for p in pairs])
print(f"  n={len(pairs)} players  corr {np.corrcoef(a, c)[0,1]:+.3f}   slope {np.polyfit(a, c, 1)[0]:+.3f} (W3 error per point of W1-2 avg error)")
for lab, lo, hi in (("we were 4+ too HIGH in W1-2", 4, 99), ("within 4", -4, 4), ("we were 4+ too LOW in W1-2", -99, -4)):
    x = [p for p in pairs if lo <= p[0] < hi]
    print(f"    {lab:30s} n={len(x):3d}  W3 bias {st.mean(p[1] for p in x):+5.2f}  W3 act/proj {sum(p[2]['act'] for p in x)/sum(p[2]['proj'] for p in x):.2f}")
for pos in ("QB","RB","WR","TE"):
    x = [p for p in pairs if p[2]["pos"] == pos]
    print(f"    {pos}: n={len(x)} corr {np.corrcoef([p[0] for p in x],[p[1] for p in x])[0,1]:+.3f}")
pairs2 = [(v[1]["err"], v[2]["err"]) for v in by.values() if 1 in v and 2 in v]
print(f"  W1 error vs W2 error: n={len(pairs2)} corr {np.corrcoef([p[0] for p in pairs2],[p[1] for p in pairs2])[0,1]:+.3f}")
print("\n=== D. do TEAM offense misses persist? team act/proj W1-2 vs W3 (healthy rows) ===")
t = defaultdict(lambda: defaultdict(lambda: [0, 0]))
for r in rows:
    k = "early" if r["wk"] < 3 else "w3"; t[r["tm"]][k][0] += r["act"]; t[r["tm"]][k][1] += r["proj"]
tt = [(k, v["early"][0]/v["early"][1], v["w3"][0]/v["w3"][1]) for k, v in t.items() if v["early"][1] > 0 and v["w3"][1] > 0]
e = np.array([x[1] for x in tt]); w = np.array([x[2] for x in tt])
print(f"  n={len(tt)} teams  corr {np.corrcoef(e, w)[0,1]:+.3f}  slope {np.polyfit(e, w, 1)[0]:+.3f}")
tt.sort(key=lambda x: x[1])
print("  coldest 6 offenses W1-2 -> their W3:  " + "  ".join(f"{k} {a:.2f}->{b:.2f}" for k, a, b in tt[:6]))
print("  hottest 6 offenses W1-2 -> their W3:  " + "  ".join(f"{k} {a:.2f}->{b:.2f}" for k, a, b in tt[-6:]))
print(f"  coldest third W3 act/proj {st.mean(x[2] for x in tt[:11]):.2f} | middle {st.mean(x[2] for x in tt[11:21]):.2f} | hottest third {st.mean(x[2] for x in tt[21:]):.2f}")
print("\n=== E. in-game exits / limited weeks: the players (38) ===")
lim = [r for r in allr if r["lim"] is True]
print("  " + ", ".join(f"{r['name']} W{r['wk']} ({r['proj']:.0f}->{r['act']:.0f}, {r['snap']}% snaps)" for r in sorted(lim, key=lambda r: -r["err"])[:20]))
tot = sum(r["err"] for r in allr); print(f"  share of total over-projection explained by these weeks: {sum(r['err'] for r in lim)/tot:.0%} ({len(lim)/len(allr):.0%} of rows)")
print("\n=== F. biggest repeat names inside the flagged groups (healthy weeks, avg error) ===")
for lab, f in (("2nd/3rd options", second), ("young", young), ("veterans 9+", vet)):
    g = defaultdict(list)
    for r in rows:
        if f(r): g[r["name"]].append(r)
    x = sorted(((st.mean(r["err"] for r in v), k, v) for k, v in g.items() if len(v) >= 2))
    print(f"  {lab}: too HIGH on " + ", ".join(f"{k} ({v[0]['pos']} {b:+.1f})" for b, k, v in x[::-1][:7]))
    print(f"  {' '*len(lab)}  too LOW on  " + ", ".join(f"{k} ({v[0]['pos']} {b:+.1f})" for b, k, v in x[:7]))
