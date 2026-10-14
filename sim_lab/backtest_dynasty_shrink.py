#!/usr/bin/env python3
"""
backtest_dynasty_shrink.py — small-sample guard for Dynasty SIM (2026-10-09).

Found during the QB fix: Case Keenum (38, no 2024-25, 2 games 2023 + one big
2026 game) valued #68 in 1QB — a 3-game production level is read as real
and his comps are elite QBs returning from injury. Guard: production vs
replacement (rel) pulled toward 0.8 with weight g0 / (games behind it + g0),
in the training rows and the query alike.

Model = current prototype: local-linear comps (120, 5), QB age scale 6,
in-season fold c=2 / rookies g/(g+2). Pool: FFC ADP 2015-2023, 1QB PPR.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS, WEEKS, SC, STAT_KEYS, score_rates  # noqa: E402
from backtest_dynasty_inseason import ffc_adp, evaluate, START_YEARS  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

LAST_DATA = 2025
YW = 1.5
W = 4
LL = (120, 5.0)
AGE = {'QB': 6.0}


def run(g0):
    w = World(LAST_DATA, shrink_g0=g0)
    rows = w.rows(FORMATS['1qb'], START_YEARS[-1])
    comps = Comps(rows, LAST_DATA, AGE)
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
        gcur, tot = w.cur_season(key, Y, W)
        if r['rookie']:
            r['ev_pre'] = ev = comps.ev(pos, True, Comps.feat_rookie(r['pick'], r['age0']), Y, exclude_key=key, local_linear=LL)
            if gcur > 0:
                base = score_rates({k: tot[k] / gcur for k in STAT_KEYS}, SC)
                f = comps.feat_v(pos, r['age0'], w.rel(base, Y, pos, gcur), min(17.0, gcur * 17.0 / W))
                ev_v = comps.ev(pos, False, f, Y, exclude_key=key, local_linear=LL)
                a = gcur / (gcur + 2.0)
                ev = [(1 - a) * x + a * y for x, y in zip(ev, ev_v)]
            r['ev_w4'] = ev
        else:
            r['ev_pre'] = comps.ev(pos, False, comps.feat_v(pos, r['age0'], r['rel'], r['gp1']), Y,
                                   exclude_key=key, local_linear=LL)
            b = w.base_at(key, Y, W, 2.0)
            r['ev_w4'] = comps.ev(pos, False, comps.feat_v(pos, r['age0'], w.rel(b[0], Y, pos, b[4]), b[1]), Y,
                                  exclude_key=key, local_linear=LL)
    t3 = lambda r: sum(v or 0 for v in r['vor'][:3])
    t5 = lambda r: sum(v or 0 for v in r['vor'][:5])
    y5 = [y for y in START_YEARS if y + 4 <= LAST_DATA]
    f3 = lambda r: sum(r['ev_pre'][:3])
    f5 = lambda r: f3(r) + YW * sum(r['ev_pre'][3:])
    fw = lambda r: r['ev_w4'][0] * frac + r['ev_w4'][1] + r['ev_w4'][2]
    a = evaluate(pool, f3, t3); b = evaluate([r for r in pool if r['Y'] in y5], f5, t5)
    c = evaluate(pool, fw, lambda r: r['t3w'])
    wp = [evaluate([r for r in pool if r['pos'] == p], fw, lambda r: r['t3w'], 12)[0] for p in ('QB', 'RB', 'WR', 'TE')]
    # low-sample vets: players with < 8 games behind their week-4 base
    low = [r for r in pool if not r['rookie'] and w.base_at(r['key'], r['Y'], W, 2.0)[4] < 8]
    lo = spearman([fw(r) for r in low], [r['t3w'] for r in low]) if len(low) > 5 else float('nan')
    print(f'g0={g0:<5}{a[0]:>7.3f}{a[1]*100:>6.1f}%{b[0]:>7.3f}{b[1]*100:>6.1f}%{c[0]:>7.3f}{c[1]*100:>6.1f}%'
          + ''.join(f'{x:>7.3f}' for x in wp) + f'   low-sample vets n={len(low)} W4 Sp (pooled) {lo:.3f}')


def main():
    print(f'{"":<8}{"T3 Sp":>7}{"top36":>7}{"T5 Sp":>7}{"top36":>7}{"W4 Sp":>7}{"top36":>7}{"QB":>7}{"RB":>7}{"WR":>7}{"TE":>7}')
    for g0 in (0.0, 3.0, 6.0, 12.0):
        run(g0)


if __name__ == '__main__':
    main()
