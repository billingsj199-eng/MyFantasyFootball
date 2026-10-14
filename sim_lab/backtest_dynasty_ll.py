#!/usr/bin/env python3
"""
backtest_dynasty_ll.py — local-linear comps (TE / elite fix) vs plain comps mean.

Jack 2026-10-09 "do the TE fix next". Diagnosis (backtest_dynasty_te.py):
elite TEs realized 1.24x their predicted WIN3 (QB top-3 1.57x) and the sim put
1.1 TEs/yr in the top 36 vs 2.3 realized — the comps MEAN regresses players at
the edge of the data toward the middle. Local-linear reads the comps' trend at
the player instead.

Preseason FFC pool 2015-2023 (1QB PPR) + in-season week-4 check (shipped fold:
vets c=2, rookies g/(g+2)). Reports whole-pool Spearman / top-36 value, T5 with
the 1.5x youth credit, within-position Spearman, top-tier calibration, and the
number of TEs / QBs in the top 36.
"""
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS, WEEKS, SC, STAT_KEYS, score_rates  # noqa: E402
from backtest_dynasty_inseason import ffc_adp, evaluate, START_YEARS  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

LAST_DATA = 2025
YW = 1.5
W = 4
VARIANTS = [('mean K30', None, False)] + [
    (f'LL K{kl} ridge{lam}', (kl, lam), False) for kl in (60, 120, 200) for lam in (1.0, 5.0, 20.0)] + [
    ('LL K120 ridge5 +rookies', (120, 5.0), True)]


def main():
    w = World(LAST_DATA)
    rows = w.rows(FORMATS['1qb'], START_YEARS[-1])
    comps = Comps(rows, LAST_DATA)
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
    y5 = [y for y in START_YEARS if y + 4 <= LAST_DATA]

    def predict(r, ll, ll_rookies, inseason):
        Y, pos = r['Y'], r['pos']
        if r['rookie']:
            ev_r = comps.ev(pos, True, Comps.feat_rookie(r['pick'], r['age0']), Y, exclude_key=r['key'],
                            local_linear=ll if ll_rookies else None)
            if not inseason or r['gcur'] == 0:
                return ev_r
            base = score_rates({k: r['tot'][k] / r['gcur'] for k in STAT_KEYS}, SC)
            ev_v = comps.ev(pos, False, Comps.feat_vet(r['age0'], w.rel(base, Y, pos), min(17.0, r['gcur'] * 17.0 / W)),
                            Y, exclude_key=r['key'], local_linear=ll)
            a = r['gcur'] / (r['gcur'] + 2.0)
            return [(1 - a) * x + a * y for x, y in zip(ev_r, ev_v)]
        if inseason:
            b = r['bw']
            f = Comps.feat_vet(r['age0'], w.rel(b[0], Y, pos), b[1])
        else:
            f = Comps.feat_vet(r['age0'], r['rel'], r['gp1'])
        return comps.ev(pos, False, f, Y, exclude_key=r['key'], local_linear=ll)

    def top36_mix(f):
        te = qb = 0
        for Y in START_YEARS:
            lst = sorted([r for r in pool if r['Y'] == Y], key=lambda r: -f(r))[:36]
            te += sum(r['pos'] == 'TE' for r in lst); qb += sum(r['pos'] == 'QB' for r in lst)
        n = len(START_YEARS)
        return te / n, qb / n

    def top3_cal(f, pos):
        p = a = 0.0
        for Y in START_YEARS:
            lst = sorted([r for r in pool if r['Y'] == Y and r['pos'] == pos], key=lambda r: -f(r))[:3]
            p += sum(sum(r['_ev'][:3]) for r in lst); a += sum(t3(r) for r in lst)
        return a / max(p, 1)

    print(f'pool {len(pool)}; realized TEs/QBs in top-36 by T3: '
          + '{:.1f} / {:.1f}'.format(*top36_mix(t3)))
    hdr = (f'{"variant":<26}{"T3 Sp":>7}{"top36":>7}{"T5 Sp":>7}{"top36":>7}{"W4 Sp":>7}{"top36":>7}'
           f'{"TE/QB in36":>11}{"QB":>7}{"RB":>7}{"WR":>7}{"TE":>7}{"TEcal":>7}{"QBcal":>7}')
    print(hdr)
    m = lambda r: -r['adp']
    a, b = evaluate(pool, m, t3), evaluate([r for r in pool if r['Y'] in y5], m, t5)
    c = evaluate(pool, m, lambda r: r['t3w'])
    tq = top36_mix(m)
    wp = [evaluate([r for r in pool if r['pos'] == p], m, t3, 12)[0] for p in ('QB', 'RB', 'WR', 'TE')]
    print(f'{"MARKET (preseason ADP)":<26}{a[0]:>7.3f}{a[1]*100:>6.1f}%{b[0]:>7.3f}{b[1]*100:>6.1f}%{c[0]:>7.3f}{c[1]*100:>6.1f}%'
          f'{tq[0]:>6.1f}/{tq[1]:<4.1f}' + ''.join(f'{x:>7.3f}' for x in wp))
    for lbl, ll, llr in VARIANTS:
        for r in pool:
            r['_ev'] = predict(r, ll, llr, False)
            r['_evw'] = predict(r, ll, llr, True)
        f = lambda r: sum(r['_ev'][:3]) + YW * sum(r['_ev'][3:])
        f3 = lambda r: sum(r['_ev'][:3])
        fw = lambda r: r['_evw'][0] * frac + r['_evw'][1] + r['_evw'][2]
        a = evaluate(pool, f3, t3); b = evaluate([r for r in pool if r['Y'] in y5], f, t5)
        c = evaluate(pool, fw, lambda r: r['t3w'])
        tq = top36_mix(f3)
        wp = [evaluate([r for r in pool if r['pos'] == p], f3, t3, 12)[0] for p in ('QB', 'RB', 'WR', 'TE')]
        print(f'{lbl:<26}{a[0]:>7.3f}{a[1]*100:>6.1f}%{b[0]:>7.3f}{b[1]*100:>6.1f}%{c[0]:>7.3f}{c[1]*100:>6.1f}%'
              f'{tq[0]:>6.1f}/{tq[1]:<4.1f}' + ''.join(f'{x:>7.3f}' for x in wp)
              + f'{top3_cal(f3, "TE"):>7.2f}{top3_cal(f3, "QB"):>7.2f}')


if __name__ == '__main__':
    main()
