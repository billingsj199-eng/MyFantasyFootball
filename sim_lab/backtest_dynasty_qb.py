#!/usr/bin/env python3
"""
backtest_dynasty_qb.py — QB placement on 1QB boards (Jack 2026-10-09).

After the local-linear fix the sim still puts ~0.9 QBs/yr in the 1QB top 36
vs 3.8 realized, and top-3 QBs realize ~1.27x their predicted WIN3.

Variants (QB vet comps only; every other group = shipped LL comps):
  base        shipped: age/2, log rel/.15, gp1/10, local-linear (120, 5)
  age6        QB age scale 2 -> 6 (QB age curve is flat)
  rush        + rushing share of production (rush persists: YoY .81 vs pass .54)
  age6+rush
  +cal        LOYO QB-only multiplier on WIN3 / YOUTH (cross-position placement),
              on top of the best feature variant
Pool: FFC dynasty ADP 2015-2023, 1QB PPR; preseason and week-4 (shipped fold).
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS, WEEKS, SC, STAT_KEYS, score_rates  # noqa: E402
from backtest_dynasty_inseason import ffc_adp, evaluate, START_YEARS  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

LAST_DATA = 2025
YW = 1.5
W = 4
LL = (120, 5.0)


class QBComps(Comps):
    def __init__(self, rows, last_data, age_scale=2.0, rush_scale=None):
        self.age_scale, self.rush_scale = age_scale, rush_scale
        super().__init__(rows, last_data)
        Yv, feats, vm, keys, lst = self.G[('QB', False)]
        self.G[('QB', False)] = (Yv, np.stack([self.fq(r['age0'], r['rel'], r['gp1'], r.get('rush', 0)) for r in lst]),
                                 vm, keys, lst)

    def fq(self, age0, rel, gp1, rush):
        v = [age0 / self.age_scale, math.log(rel) / 0.15, gp1 / 10.0]
        if self.rush_scale:
            v.append(rush / self.rush_scale)
        return np.array(v)


def main():
    w = World(LAST_DATA)
    rows = w.rows(FORMATS['1qb'], START_YEARS[-1])
    repl = w._repl
    idx = {(r['key'], r['Y']): r for r in rows}
    pool = []
    for Y in START_YEARS:
        for name, pos, adp in ffc_adp(Y):
            r = idx.get(((name, pos), Y))
            if r:
                pool.append(dict(r, adp=adp))
    frac = (WEEKS - W) / WEEKS
    for r in pool:
        key, Y, pos = r['key'], r['Y'], r['pos']
        rest = w.rest_pts(key, Y, W)
        if rest is None:
            rest = w.pts[Y].get(key, 0.0) * frac
        r['t3w'] = max(0.0, rest - repl[(Y, pos)] * frac) + sum(v or 0 for v in r['vor'][1:3])
        r['gcur'], r['tot'] = w.cur_season(key, Y, W)
        r['bw'] = w.base_at(key, Y, W, 2.0) if not r['rookie'] else None
    t3 = lambda r: sum(v or 0 for v in r['vor'][:3])
    t5 = lambda r: sum(v or 0 for v in r['vor'][:5])
    tail = lambda r: sum(v or 0 for v in r['vor'][3:5])
    y5 = [y for y in START_YEARS if y + 4 <= LAST_DATA]

    def run(comps):
        for r in pool:
            Y, pos = r['Y'], r['pos']
            for mode in ('pre', 'w4'):
                if r['rookie']:
                    ev = comps.ev(pos, True, Comps.feat_rookie(r['pick'], r['age0']), Y, exclude_key=r['key'], local_linear=LL)
                    if mode == 'w4' and r['gcur'] > 0:
                        base = score_rates({k: r['tot'][k] / r['gcur'] for k in STAT_KEYS}, SC)
                        rel = w.rel(base, Y, pos)
                        g1 = min(17.0, r['gcur'] * 17.0 / W)
                        rsh = 0.0
                        if base > 0:
                            rsh = (r['tot']['ry'] * SC['ry'] + r['tot']['rtd'] * SC['rtd']) / r['gcur'] / base
                        f = comps.fq(r['age0'], rel, g1, rsh) if pos == 'QB' else Comps.feat_vet(r['age0'], rel, g1)
                        ev_v = comps.ev(pos, False, f, Y, exclude_key=r['key'], local_linear=LL)
                        a = r['gcur'] / (r['gcur'] + 2.0)
                        ev = [(1 - a) * x + a * y for x, y in zip(ev, ev_v)]
                else:
                    if mode == 'pre':
                        rel, g1, rsh = r['rel'], r['gp1'], r.get('rush', 0)
                    else:
                        b = r['bw']; rel, g1, rsh = w.rel(b[0], Y, pos), b[1], b[3]
                    f = comps.fq(r['age0'], rel, g1, rsh) if pos == 'QB' else Comps.feat_vet(r['age0'], rel, g1)
                    ev = comps.ev(pos, False, f, Y, exclude_key=r['key'], local_linear=LL)
                r['ev_' + mode] = ev

    def qb_mult(r, part, mode):
        a = p = 0.0
        for t in pool:
            if t['pos'] != 'QB' or t['Y'] == r['Y'] or t['key'] == r['key']:
                continue
            if part == 'w':
                a += t3(t); p += sum(t['ev_pre'][:3])
            elif t['Y'] + 4 <= LAST_DATA:
                a += tail(t); p += sum(t['ev_pre'][3:5])
        return (a + 1500.0) / (p + 1500.0)

    def report(lbl, cal=False):
        for r in pool:
            if cal and r['pos'] == 'QB':
                r['mw'], r['my'] = qb_mult(r, 'w', 'pre'), qb_mult(r, 'y', 'pre')
            else:
                r['mw'] = r['my'] = 1.0
        f3 = lambda r: sum(r['ev_pre'][:3]) * r['mw']
        f5 = lambda r: f3(r) + YW * sum(r['ev_pre'][3:]) * r['my']
        fw = lambda r: (r['ev_w4'][0] * frac + r['ev_w4'][1] + r['ev_w4'][2]) * r['mw']
        a = evaluate(pool, f3, t3); b = evaluate([r for r in pool if r['Y'] in y5], f5, t5)
        c = evaluate(pool, fw, lambda r: r['t3w'])
        qbs = [r for r in pool if r['pos'] == 'QB']
        qsp = evaluate(qbs, f3, t3, 12)[0]
        p = act = 0.0; n36 = 0
        for Y in START_YEARS:
            lst = sorted([r for r in qbs if r['Y'] == Y], key=lambda r: -f3(r))[:3]
            p += sum(f3(r) for r in lst); act += sum(t3(r) for r in lst)
            n36 += sum(r['pos'] == 'QB' for r in sorted([r for r in pool if r['Y'] == Y], key=lambda r: -f3(r))[:36])
        print(f'{lbl:<22}{a[0]:>7.3f}{a[1]*100:>6.1f}%{b[0]:>7.3f}{b[1]*100:>6.1f}%{c[0]:>7.3f}{c[1]*100:>6.1f}%'
              f'{qsp:>8.3f}{act / max(p, 1):>8.2f}{n36 / len(START_YEARS):>8.1f}')

    n36 = sum(sum(r['pos'] == 'QB' for r in sorted([r for r in pool if r['Y'] == Y], key=lambda r: -t3(r))[:36])
              for Y in START_YEARS) / len(START_YEARS)
    print(f'realized QBs in top-36 by T3: {n36:.1f}/yr')
    print(f'{"variant":<22}{"T3 Sp":>7}{"top36":>7}{"T5 Sp":>7}{"top36":>7}{"W4 Sp":>7}{"top36":>7}{"QB Sp":>8}{"QB cal":>8}{"QB/36":>8}')
    m = lambda r: -r['adp']
    a = evaluate(pool, m, t3); b = evaluate([r for r in pool if r['Y'] in y5], m, t5); c = evaluate(pool, m, lambda r: r['t3w'])
    qsp = evaluate([r for r in pool if r['pos'] == 'QB'], m, t3, 12)[0]
    mq = sum(sum(r['pos'] == 'QB' for r in sorted([r for r in pool if r['Y'] == Y], key=lambda r: r['adp'])[:36])
             for Y in START_YEARS) / len(START_YEARS)
    print(f'{"MARKET":<22}{a[0]:>7.3f}{a[1]*100:>6.1f}%{b[0]:>7.3f}{b[1]*100:>6.1f}%{c[0]:>7.3f}{c[1]*100:>6.1f}%{qsp:>8.3f}{"":>8}{mq:>8.1f}')
    best = None
    for lbl, age_s, rush_s in (('age6', 6.0, None), ('age4', 4.0, None), ('age10', 10.0, None),
                               ):
        run(QBComps(rows, LAST_DATA, age_s, rush_s))
        report(lbl)
    for lbl, age_s, rush_s in (('age6 +cal', 6.0, None),):
        run(QBComps(rows, LAST_DATA, age_s, rush_s))
        report(lbl, cal=True)


if __name__ == '__main__':
    main()
