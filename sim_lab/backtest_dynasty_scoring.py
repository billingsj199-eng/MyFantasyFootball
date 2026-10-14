#!/usr/bin/env python3
"""
backtest_dynasty_scoring.py — Dynasty SIM in PPR vs HALF vs STD (Jack 2026-10-09).

Everything so far was tuned/graded in PPR. This reruns the CURRENT prototype
in each scoring (truth = realized VOR in that scoring) and checks that the
PPR-tuned settings still hold there:
  shipped   local-linear comps (120, 5), QB age scale 6, in-season c=2,
            rookies g/(g+2), youth 1.5
  alts      plain comps mean (K30) · QB age scale 2 · c=1 · c=4 · youth 1.0 / 2.0
Pool: FFC dynasty ADP 2015-2023, 1QB. Market = the same ADP in every scoring
(FFC doesn't publish a dynasty ADP per scoring), so only the SIM columns move.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS, WEEKS, STAT_KEYS, score_rates  # noqa: E402
from backtest_dynasty_inseason import ffc_adp, evaluate, START_YEARS  # noqa: E402

LAST_DATA = 2025
W = 4
SCORINGS = (('PPR', 'full_ppr', 0.0), ('HALF', 'half_ppr', 0.0), ('STD', 'non_ppr', 0.0))
TEP_SCORINGS = (('PPR+TEP.5', 'full_ppr', 0.5), ('PPR+TEP1', 'full_ppr', 1.0), ('HALF+TEP.5', 'half_ppr', 0.5))
CONFIGS = [  # label, local_linear, age_scale, c
    ('shipped', (120, 5.0), {'QB': 6.0}, 2.0),
    ('plain mean K30', None, {'QB': 6.0}, 2.0),
    ('QB age scale 2', (120, 5.0), {}, 2.0),
    ('c=1', (120, 5.0), {'QB': 6.0}, 1.0),
    ('c=4', (120, 5.0), {'QB': 6.0}, 4.0),
]


def main():
    print(f'{"scoring":<6}{"config":<17}{"T3 Sp":>7}{"top36":>7}{"T5 Sp":>7}{"y1.0":>7}{"y2.0":>7}'
          f'{"W4 Sp":>7}{"top36":>7}{"QB":>7}{"RB":>7}{"WR":>7}{"TE":>7}')
    tep_only = '--tep' in sys.argv
    for sc_lbl, sc, tep in (TEP_SCORINGS if tep_only else SCORINGS):
        w = World(LAST_DATA, scoring=sc, tep=tep)
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
        t3 = lambda r: sum(v or 0 for v in r['vor'][:3])
        t5 = lambda r: sum(v or 0 for v in r['vor'][:5])
        y5 = [y for y in START_YEARS if y + 4 <= LAST_DATA]
        m = lambda r: -r['adp']
        a = evaluate(pool, m, t3); b = evaluate([r for r in pool if r['Y'] in y5], m, t5)
        c = evaluate(pool, m, lambda r: r['t3w'])
        wp = [evaluate([r for r in pool if r['pos'] == p], m, lambda r: r['t3w'], 12)[0] for p in ('QB', 'RB', 'WR', 'TE')]
        print(f'{sc_lbl:<6}{"MARKET":<17}{a[0]:>7.3f}{a[1]*100:>6.1f}%{b[0]:>7.3f}{"":>14}{c[0]:>7.3f}{c[1]*100:>6.1f}%'
              + ''.join(f'{x:>7.3f}' for x in wp))
        comps_cache = {}
        for lbl, ll, age, cw in (CONFIGS[:2] if tep_only else CONFIGS):
            ck = tuple(sorted(age.items()))
            if ck not in comps_cache:
                comps_cache[ck] = Comps(rows, LAST_DATA, age)
            comps = comps_cache[ck]
            for r in pool:
                key, Y, pos = r['key'], r['Y'], r['pos']
                if r['rookie']:
                    ev = comps.ev(pos, True, Comps.feat_rookie(r['pick'], r['age0']), Y, exclude_key=key, local_linear=ll)
                    r['ev_pre'] = ev
                    if r['gcur'] > 0:
                        base = score_rates({k: r['tot'][k] / r['gcur'] for k in STAT_KEYS}, w.sc_for(pos))
                        f = comps.feat_v(pos, r['age0'], w.rel(base, Y, pos), min(17.0, r['gcur'] * 17.0 / W))
                        ev_v = comps.ev(pos, False, f, Y, exclude_key=key, local_linear=ll)
                        al = r['gcur'] / (r['gcur'] + 2.0)
                        ev = [(1 - al) * x + al * y for x, y in zip(ev, ev_v)]
                    r['ev_w4'] = ev
                else:
                    r['ev_pre'] = comps.ev(pos, False, comps.feat_v(pos, r['age0'], r['rel'], r['gp1']), Y,
                                           exclude_key=key, local_linear=ll)
                    bb = w.base_at(key, Y, W, cw)
                    r['ev_w4'] = comps.ev(pos, False, comps.feat_v(pos, r['age0'], w.rel(bb[0], Y, pos), bb[1]), Y,
                                          exclude_key=key, local_linear=ll)
            f3 = lambda r: sum(r['ev_pre'][:3])
            fy = lambda yw: (lambda r: f3(r) + yw * sum(r['ev_pre'][3:]))
            fw = lambda r: r['ev_w4'][0] * frac + r['ev_w4'][1] + r['ev_w4'][2]
            p5 = [r for r in pool if r['Y'] in y5]
            a = evaluate(pool, f3, t3)
            b = evaluate(p5, fy(1.5), t5); b1 = evaluate(p5, fy(1.0), t5); b2 = evaluate(p5, fy(2.0), t5)
            c = evaluate(pool, fw, lambda r: r['t3w'])
            wp = [evaluate([r for r in pool if r['pos'] == p], fw, lambda r: r['t3w'], 12)[0] for p in ('QB', 'RB', 'WR', 'TE')]
            print(f'{sc_lbl:<6}{lbl:<17}{a[0]:>7.3f}{a[1]*100:>6.1f}%{b[0]:>7.3f}{b1[0]:>7.3f}{b2[0]:>7.3f}'
                  f'{c[0]:>7.3f}{c[1]*100:>6.1f}%' + ''.join(f'{x:>7.3f}' for x in wp))
        print()


if __name__ == '__main__':
    main()
