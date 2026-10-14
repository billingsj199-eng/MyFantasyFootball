"""How much do past classes' JM-based strength curves vary around the average (same measure as dyn_picks.class_ratio)?"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dyn_common import World, FORMATS  # noqa: E402
import dyn_picks as dp  # noqa: E402

w = World(2025)
w.rows(FORMATS['1qb'], 2025)
_, jm = dp._load_jm()
pts = []
for key, dr in w.draft.items():
    if 2017 <= dr[0] <= 2025 and key in jm:
        pts.append((jm[key]['jm'], [w.vor(key, dr[0] + k) if dr[0] + k <= 2025 else None for k in range(5)]))


def ev(j):
    tot = 0.0
    for k in range(5):
        num = den = 0.0
        for jj, vs in pts:
            if vs[k] is None:
                continue
            wt = math.exp(-0.5 * ((jj - j) / 6.0) ** 2)
            num += wt * vs[k]; den += wt
        tot += (num / den if den else 0.0) * (1.0 if k < 3 else 0.5)
    return tot


curves, real = {}, {}
for Y in range(2017, 2026):
    js = sorted([jm[k]['jm'] for k, dr in w.draft.items() if dr[0] == Y and k in jm], reverse=True)[:48]
    curves[Y] = [ev(j) for j in js] + [0.0] * (48 - len(js))
    order = dp.class_order(w, Y)
    real[Y] = [sum((w.vor(k, Y + i) or 0) for i in range(3) if Y + i <= 2025) for k in order]
hbar = [sum(c[i] for c in curves.values()) / len(curves) for i in range(48)]
print(f'{"class":<7}' + ''.join(f'{g:>10}' for g in ('Early 1st', 'Mid 1st', 'Late 1st', 'Early 2nd', '3rd')) + '   realized 1st-rd yr1-3 VOR (vs class avg)')
rbar = {}
for Y in curves:
    rbar[Y] = sum(real[Y][:12])
avg_r = sum(v for y, v in rbar.items() if y <= 2023) / len([y for y in rbar if y <= 2023])
for Y, c in curves.items():
    cells = []
    for g in ('Early 1st', 'Mid 1st', 'Late 1st', 'Early 2nd', '3rd'):
        rng = dp.GROUPS[g]
        cells.append(sum(c[s - 1] for s in rng) / max(1e-9, sum(hbar[s - 1] for s in rng)))
    rr = f'{rbar[Y] / avg_r:.2f}' if Y <= 2023 else '(incomplete)'
    print(f'{Y:<7}' + ''.join(f'{x:>10.2f}' for x in cells) + f'   {rr}')
