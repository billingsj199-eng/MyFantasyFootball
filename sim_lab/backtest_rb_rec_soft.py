#!/usr/bin/env python3
"""
backtest_rb_rec_soft.py — a softer RB receiving dock for the very low receivers?
(Jack 2026-10-10: "test the softer receiving dock for corum")

backtest_rb_rec_groups.py: the shipped linear tilt (FAIR += -0.25 x z, z = prior-season
PFF yards after catch per route) helps RB ranks overall (4/4) but over-docks z <= -1
(residual +.04 -> -.16, n 15). Shapes tried (k = -0.25 throughout, only the z mapping
changes):
  linear   z                         (shipped)
  floor1   max(z, -1)
  floor15  max(z, -1.5)
  half1    z past -1 at half slope   (-1 + 0.5 (z + 1))
  negHalf  negative side at half slope (positive side full)
  posOnly  max(z, 0)                 (reward receivers, never dock)
Pool: FFC dynasty pool 2020-23 (PFF 2019-22 = prior season), shipped JM sim + FAIR.
Scores per year: RB-only and whole-board Spearman vs realized season / 3yr / 5yr+youth
rank; very-low (z <= -1) residual log(realized / predicted RB rank).
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, FORMATS  # noqa: E402
from backtest_value_score import build  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402
from backtest_rb_rec_groups import yac_z  # noqa: E402

YRS = [2020, 2021, 2022, 2023]
K = -0.25
SHAPES = {'linear': lambda z: z, 'floor1': lambda z: max(z, -1.0), 'floor15': lambda z: max(z, -1.5),
          'half1': lambda z: z if z >= -1 else -1 + 0.5 * (z + 1), 'negHalf': lambda z: z if z >= 0 else 0.5 * z,
          'posOnly': lambda z: max(z, 0.0), 'off': lambda z: 0.0}


def main():
    w = World(2025)
    w.rows(FORMATS['1qb'], 2025)
    Z = {Y: yac_z(Y - 1) for Y in YRS}
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = [x for x in build(True) if x['Y'] in YRS]
    m3_ship(recs, c)
    for x in recs:
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
        x['z'] = Z[x['Y']].get(x['key'][0]) if (x['pos'] == 'RB' and not x['rookie']) else None
        x['v1'] = w.vor(x['key'], x['Y']) or 0.0
    truths = (('season', lambda x: -x['v1']), ('3yr', lambda x: x['r_t3']), ('5yr', lambda x: x['r_lt']))

    def sc(x, f):
        return x['fz'] + (K * f(x['z']) if x['z'] is not None else 0.0)

    res = {}
    for name, f in SHAPES.items():
        r = {}
        for tl, tf in truths:
            for sub in ('RB', None):
                v = []
                for Y in YRS:
                    ys = [x for x in recs if x['Y'] == Y and (sub is None or x['pos'] == sub)]
                    if tl == '5yr' and any(x.get('r_lt') is None for x in ys):
                        continue
                    v.append(spearman([-sc(x, f) for x in ys], [-tf(x) for x in ys]))
                r[(tl, sub)] = np.array(v)
            # very-low residual on RB ranks
            resid = []
            for Y in YRS:
                ys = [x for x in recs if x['Y'] == Y and x['pos'] == 'RB']
                if tl == '5yr' and any(x.get('r_lt') is None for x in ys):
                    continue
                pr = {id(x): i + 1 for i, x in enumerate(sorted(ys, key=lambda x: sc(x, f)))}
                tr = {id(x): i + 1 for i, x in enumerate(sorted(ys, key=tf))}
                resid += [math.log(tr[id(x)] / pr[id(x)]) for x in ys if x['z'] is not None and x['z'] <= -1]
            r[(tl, 'resid')] = np.mean(resid) if resid else float('nan')
        res[name] = r
    base = res['linear']
    print('per-year Spearman means (wins vs shipped linear); very-low (z <= -1) residual, + = finished worse than ranked')
    for tl, _ in truths:
        print(f'\n--- {tl} ---')
        print(f'{"shape":<9}{"RB-only":>16}{"whole":>18}{"very-low resid":>16}')
        for name in SHAPES:
            r = res[name]
            cell = lambda key: f'{r[key].mean():.4f}' + ('' if name == 'linear' else f' ({int((r[key] > base[key] + 1e-9).sum())}/{len(r[key])})')
            print(f'{name:<9}{cell((tl, "RB")):>16}{cell((tl, None)):>18}{r[(tl, "resid")]:>+16.2f}')


if __name__ == '__main__':
    main()
