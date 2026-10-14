#!/usr/bin/env python3
"""
backtest_dynasty_te.py — TE diagnosis + fix for Dynasty SIM (Jack 2026-10-09).

Part 1 CALIBRATION: by position x predicted tier, mean predicted WIN3 vs
       realized T3 (preseason, FFC pool 2015-2023, 1QB PPR). Tells whether
       TEs are placed too low ACROSS positions.
Part 2 WITHIN-TE ORDER: TE-specific comps variants vs the shipped comps and
       the market (pooled + per-year Spearman vs T3 / T5).
         - age scale (memory: TE age curve inverts, old TEs hold value)
         - K (TE pool is thin)
         - draft capital as a vet feature for young TEs (exp <= 3)
Part 3 CROSS-POSITION FIX: LOYO per-position calibration multiplier on the
       comps value; whole-pool Spearman / top-36 / TE share of top-36.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS, H  # noqa: E402
from backtest_dynasty_inseason import ffc_adp, evaluate, START_YEARS  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

LAST_DATA = 2025
YW = 1.5


class TEComps(Comps):
    """Comps with per-position feature scales + optional draft-pick dim for vets."""

    def __init__(self, rows, last_data, age_scale=2.0, pick_dim=None):
        self.age_scale = age_scale
        self.pick_dim = pick_dim   # None or scale for log(pick) on exp<=3 vets
        super().__init__(rows, last_data)
        # rebuild the TE vet group with the variant features
        Yv, feats, vm, keys, lst = self.G[('TE', False)]
        self.G[('TE', False)] = (Yv, np.stack([self._f(r) for r in lst]), vm, keys, lst)

    def _f(self, r):
        v = [r['age0'] / self.age_scale, math.log(r['rel']) / 0.15, r['gp1'] / 10.0]
        if self.pick_dim:
            v.append(math.log(r.get('pick_any') or 262) / self.pick_dim if r.get('exp', 9) <= 3 else 0.0)
        return np.array(v)

    def ev_row(self, r, Y, K):
        if r['rookie']:
            return self.ev(r['pos'], True, Comps.feat_rookie(r['pick'], r['age0']), Y, K, exclude_key=r['key'])
        if r['pos'] == 'TE':
            return self.ev('TE', False, self._f(r), Y, K, exclude_key=r['key'])
        return self.ev(r['pos'], False, Comps.feat_vet(r['age0'], r['rel'], r['gp1']), Y, K, exclude_key=r['key'])


def main():
    w = World(LAST_DATA)
    rows = w.rows(FORMATS['1qb'], START_YEARS[-1])
    for r in rows:   # draft capital + experience for the TE pick dim
        dr = w.players[r['key']]['draft']
        r['pick_any'] = dr[1] if dr else None
        r['exp'] = (r['Y'] - dr[0]) if dr else 9
    idx = {(r['key'], r['Y']): r for r in rows}
    pool = []
    for Y in START_YEARS:
        for name, pos, adp in ffc_adp(Y):
            r = idx.get(((name, pos), Y))
            if r:
                pool.append(dict(r, adp=adp))
    t3 = lambda r: sum(v or 0 for v in r['vor'][:3])
    t5 = lambda r: sum(v or 0 for v in r['vor'][:5])

    base = TEComps(rows, LAST_DATA)
    for r in pool:
        r['ev'] = base.ev_row(r, r['Y'], 30)
    win3 = lambda r: sum(r['ev'][:3])

    print('=== Part 1: CALIBRATION — mean predicted WIN3 vs realized T3, by position x predicted tier ===')
    print(f'{"pos":<4}{"tier":<10}{"n":>5}{"pred":>8}{"real":>8}{"real/pred":>10}')
    for pos in ('QB', 'RB', 'WR', 'TE'):
        pp = sorted([r for r in pool if r['pos'] == pos], key=lambda r: -win3(r))
        # tiers by within-year predicted position rank
        byY = defaultdict(list)
        for r in pp:
            byY[r['Y']].append(r)
        tiers = defaultdict(list)
        for Y, lst in byY.items():
            lst.sort(key=lambda r: -win3(r))
            for i, r in enumerate(lst):
                tiers['top3' if i < 3 else 'top4-8' if i < 8 else 'top9-16' if i < 16 else 'rest'].append(r)
        for t in ('top3', 'top4-8', 'top9-16', 'rest'):
            lst = tiers[t]
            if not lst:
                continue
            p = sum(win3(r) for r in lst) / len(lst); a = sum(t3(r) for r in lst) / len(lst)
            print(f'{pos:<4}{t:<10}{len(lst):>5}{p:>8.0f}{a:>8.0f}{a / max(p, 1):>10.2f}')

    print('\n=== Part 2: WITHIN-TE ORDER (pooled Spearman, TE pool; per-year n-weighted in brackets) ===')
    te = [r for r in pool if r['pos'] == 'TE']
    print(f'TE player-years: {len(te)} ({sum(r["rookie"] for r in te)} rookies)')

    def per_year(f, truth):
        num = den = 0.0
        for Y in START_YEARS:
            lst = [r for r in te if r['Y'] == Y]
            if len(lst) < 8:
                continue
            s = spearman([f(r) for r in lst], [truth(r) for r in lst])
            if s is not None:
                num += s * len(lst); den += len(lst)
        return num / den

    def report(lbl, f):
        print(f'{lbl:<34}T3 {spearman([f(r) for r in te], [t3(r) for r in te]):.3f} [{per_year(f, t3):.3f}]'
              f'   T5 {spearman([f(r) for r in te], [t5(r) for r in te]):.3f} [{per_year(f, t5):.3f}]')
    report('MARKET', lambda r: -r['adp'])
    report('SIM shipped (age/2, K30)', lambda r: sum(r['ev'][:3]) + YW * sum(r['ev'][3:]))
    variants = {}
    for age_s in (2.0, 3.0, 4.0, 6.0):
        for K in (30, 60):
            for pdim in (None, 0.5):
                c = TEComps(rows, LAST_DATA, age_s, pdim)
                key = (age_s, K, pdim)
                variants[key] = {id(r): c.ev_row(r, r['Y'], K) for r in te}
                if key == (2.0, 30, None):
                    continue
                ev = variants[key]
                report(f'age/{age_s:g} K{K} pick{"" if pdim is None else pdim}',
                       lambda r, ev=ev: sum(ev[id(r)][:3]) + YW * sum(ev[id(r)][3:]))

    print('\n=== Part 3: CROSS-POSITION — LOYO calibration multiplier per position (on WIN3 and YOUTH) ===')
    LAM = 2000.0

    def mult(r, part):
        a = p = 0.0
        for t in pool:
            if t['pos'] != r['pos'] or t['Y'] == r['Y'] or t['key'] == r['key']:
                continue
            if part == 'w':
                a += t3(t); p += sum(t['ev'][:3])
            elif t['Y'] + 4 <= LAST_DATA:
                a += sum(v or 0 for v in t['vor'][3:5]); p += sum(t['ev'][3:5])
        return (a + LAM) / (p + LAM)
    for r in pool:
        r['mw'], r['my'] = mult(r, 'w'), mult(r, 'y')
    cal = lambda r: sum(r['ev'][:3]) * r['mw'] + YW * sum(r['ev'][3:]) * r['my']
    raw = lambda r: sum(r['ev'][:3]) + YW * sum(r['ev'][3:])
    full = defaultdict(lambda: [0.0, 0.0])
    for t in pool:
        full[t['pos']][0] += t3(t); full[t['pos']][1] += sum(t['ev'][:3])
    print('full-data WIN3 multiplier: ' + ', '.join(f'{p} {a / b:.2f}' for p, (a, b) in full.items()))
    y5 = [y for y in START_YEARS if y + 4 <= LAST_DATA]
    for lbl, f in (('MARKET', lambda r: -r['adp']), ('SIM raw', raw), ('SIM calibrated', cal)):
        a = evaluate(pool, f, t3); b = evaluate([r for r in pool if r['Y'] in y5], f, t5)
        te36 = []
        for Y in START_YEARS:
            lst = sorted([r for r in pool if r['Y'] == Y], key=lambda r: -f(r))[:36]
            te36.append(sum(r['pos'] == 'TE' for r in lst))
        print(f'{lbl:<18} T3 Sp {a[0]:.3f} top36 {a[1]*100:.1f}%   T5 Sp {b[0]:.3f} top36 {b[1]*100:.1f}%   '
              f'TEs in top-36: {sum(te36) / len(te36):.1f}/yr')
    real36 = []
    for Y in START_YEARS:
        lst = sorted([r for r in pool if r['Y'] == Y], key=lambda r: -t3(r))[:36]
        real36.append(sum(r['pos'] == 'TE' for r in lst))
    print(f'{"REALIZED (truth)":<18} TEs in top-36 by realized T3: {sum(real36) / len(real36):.1f}/yr')


if __name__ == '__main__':
    main()
