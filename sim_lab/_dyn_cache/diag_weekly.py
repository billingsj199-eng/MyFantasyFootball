import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dyn_common import World, FORMATS  # noqa: E402
from backtest_dynasty_inseason import ffc_adp  # noqa: E402

w = World(2025)
rows = w.rows(FORMATS['1qb'], 2023)
idx = {(r['key'], r['Y']): r for r in rows}
miss = collections.Counter()
ex = []
for Y in range(2015, 2024):
    for n, p, a in ffc_adp(Y):
        r = idx.get(((n, p), Y))
        if not r:
            continue
        if w.weekly.get(r['key'], {}).get(Y) is None:
            played = w.pts[Y].get(r['key'], 0)
            miss['played' if played > 0 else 'did_not_play'] += 1
            if played > 30 and len(ex) < 25:
                ex.append((Y, n, p, round(played), sorted(w.weekly.get(r['key'], {}).keys())[-3:]))
print(miss)
for e in ex:
    print(e)
