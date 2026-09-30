import json, os, statistics as st
from collections import defaultdict
D = r"E:\MyFantasyFootball\MyFantasyFootball Files\accuracy\data"
SRC = ['MFF sim', 'JS model', 'Clay', 'Sleeper', 'ESPN', 'CBS', 'FP', 'SiteAvg']

def rank(v):
    o = sorted(range(len(v)), key=lambda i: v[i]); r = [0]*len(v); i = 0
    while i < len(o):
        j = i
        while j+1 < len(o) and v[o[j+1]] == v[o[i]]: j += 1
        for k in range(i, j+1): r[o[k]] = (i+j)/2+1
        i = j+1
    return r
def spear(a, b):
    ra, rb = rank(a), rank(b); ma, mb = st.mean(ra), st.mean(rb)
    n = sum((x-ma)*(y-mb) for x, y in zip(ra, rb))
    d = (sum((x-ma)**2 for x in ra)*sum((y-mb)**2 for y in rb))**.5
    return n/d if d else 0

rows = []
for wk in (1, 2, 3):
    w = json.load(open(os.path.join(D, f"w{wk}.json")))
    for n, p in w['players'].items():
        if p['pos'] not in ('QB', 'RB', 'WR', 'TE') or p.get('act') is None: continue
        s, site = p.get('sim'), p.get('site')
        if not s or not site or s[0] is None: continue
        if any(x is None for x in site[:4]): continue
        half = 0.5*(s[4] or 0)
        v = {'MFF sim': s[0]+half, 'JS model': (s[5] if s[5] is not None else s[0])+half,
             'Clay': (s[6] if s[6] is not None else s[0])+half,
             'Sleeper': site[0], 'ESPN': site[1], 'CBS': site[2], 'FP': site[3]}
        v['SiteAvg'] = sum(site[:4])/4
        if max(v['MFF sim'], v['SiteAvg']) < 5: continue
        # actual half-ppr unknown here; band check uses half-PPR sim quantiles vs PPR act minus rec unknown -> skip
        rows.append(dict(wk=wk, n=n, pos=p['pos'], tm=p['tm'], act=p['act'], **v))

def table(rs, title):
    print(f"\n=== {title}  (n={len(rs)}, full PPR, same rows every source) ===")
    print(f"  {'source':10s} {'MAE':>6s} {'bias':>6s} {'RMSE':>6s}")
    for s in SRC:
        e = [r[s]-r['act'] for r in rs]
        print(f"  {s:10s} {st.mean(abs(x) for x in e):6.2f} {st.mean(e):+6.2f} {(st.mean(x*x for x in e))**.5:6.2f}")

for wk in (1, 2, 3): table([r for r in rows if r['wk'] == wk], f"WEEK {wk}")
table(rows, "CUMULATIVE W1-3")

print("\n=== CUMULATIVE MAE by position ===")
print("  pos    n  " + "".join(f"{s:>9s}" for s in SRC))
for pos in ('QB', 'RB', 'WR', 'TE'):
    rs = [r for r in rows if r['pos'] == pos]
    print(f"  {pos:3s} {len(rs):4d}  " + "".join(f"{st.mean(abs(r[s]-r['act']) for r in rs):9.2f}" for s in SRC))
print("\n=== CUMULATIVE bias (proj - act) by position ===")
for pos in ('QB', 'RB', 'WR', 'TE'):
    rs = [r for r in rows if r['pos'] == pos]
    print(f"  {pos:3s} {len(rs):4d}  " + "".join(f"{st.mean(r[s]-r['act'] for r in rs):+9.2f}" for s in SRC))

print("\n=== weekly rank accuracy: mean Spearman across 3 weeks (within position) ===")
print("  pos       " + "".join(f"{s:>9s}" for s in SRC))
for pos in ('QB', 'RB', 'WR', 'TE'):
    out = []
    for s in SRC:
        vals = []
        for wk in (1, 2, 3):
            rs = [r for r in rows if r['pos'] == pos and r['wk'] == wk]
            vals.append(spear([r[s] for r in rs], [r['act'] for r in rs]))
        out.append(st.mean(vals))
    print(f"  {pos:3s}       " + "".join(f"{x:+9.2f}" for x in out))

print("\n=== head-to-head MFF sim vs each source (row closer, tie within 0.1) ===")
for s in SRC[1:]:
    w = l = t = 0
    for r in rows:
        a, b = abs(r['MFF sim']-r['act']), abs(r[s]-r['act'])
        if abs(a-b) <= .1: t += 1
        elif a < b: w += 1
        else: l += 1
    print(f"  vs {s:9s} {w}-{l}-{t}  ({100*w/(w+l):.0f}% of decided)")

print("\n=== tier (by MFF sim PPR proj): n / bias / MAE sim vs SiteAvg / act÷proj ===")
for lo, hi in ((5, 10), (10, 15), (15, 20), (20, 99)):
    rs = [r for r in rows if lo <= r['MFF sim'] < hi]
    print(f"  [{lo:2d},{hi:2d}) n={len(rs):3d} bias {st.mean(r['MFF sim']-r['act'] for r in rs):+5.2f}  MAE sim {st.mean(abs(r['MFF sim']-r['act']) for r in rs):5.2f} sites {st.mean(abs(r['SiteAvg']-r['act']) for r in rs):5.2f}  act/proj {sum(r['act'] for r in rs)/sum(r['MFF sim'] for r in rs):.3f}")

print("\n=== repeat misses: players off by >=6 PPR pts in the SAME direction in 2+ weeks (shipped sim) ===")
by = defaultdict(list)
for r in rows: by[r['n']].append(r)
rep = []
for n, rs in by.items():
    if len(rs) < 2: continue
    e = [r['MFF sim']-r['act'] for r in rs]
    lo = [x for x in e if x <= -6]; hi = [x for x in e if x >= 6]
    if len(lo) >= 2 or len(hi) >= 2:
        rep.append((st.mean(e), n, rs))
for m, n, rs in sorted(rep):
    print(f"  {n:24s} {rs[0]['pos']} {rs[0]['tm']:3s} avg err {m:+6.1f} | " + "  ".join(f"W{r['wk']} {r['MFF sim']:.1f}->{r['act']:.1f} (sites {r['SiteAvg']:.1f})" for r in rs))

print("\n=== where sim and sites disagreed by >=3 PPR pts: who was right ===")
d = [r for r in rows if abs(r['MFF sim']-r['SiteAvg']) >= 3]
w = sum(1 for r in d if abs(r['MFF sim']-r['act']) < abs(r['SiteAvg']-r['act']))
print(f"  n={len(d)}  sim closer {w} ({100*w/len(d):.0f}%)")
for lab, f in (('sim HIGHER', lambda r: r['MFF sim'] > r['SiteAvg']), ('sim LOWER', lambda r: r['MFF sim'] < r['SiteAvg'])):
    x = [r for r in d if f(r)]
    w = sum(1 for r in x if abs(r['MFF sim']-r['act']) < abs(r['SiteAvg']-r['act']))
    print(f"  {lab}: n={len(x)} sim closer {100*w/max(1,len(x)):.0f}%  avg sim {st.mean(r['MFF sim'] for r in x):.1f} sites {st.mean(r['SiteAvg'] for r in x):.1f} actual {st.mean(r['act'] for r in x):.1f}")
    for pos in ('QB', 'RB', 'WR', 'TE'):
        y = [r for r in x if r['pos'] == pos]
        if y:
            w = sum(1 for r in y if abs(r['MFF sim']-r['act']) < abs(r['SiteAvg']-r['act']))
            print(f"      {pos} n={len(y):2d} sim closer {100*w/len(y):.0f}%")
