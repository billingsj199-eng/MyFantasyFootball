#!/usr/bin/env python3
"""
backtest_dynasty_market_next.py — expected market value next year (Jack 2026-10-09).

Target: a player's dynasty market rank one year later (FFC dynasty startup ADP,
Y -> Y+1; falling out of the next year's ADP = rank 250). Pool = FFC-drafted
players, start years 2015-2023. Within-pool ranks for market and sim (as in
SIM GAP). Models (OLS on log rank, leave-one-year-out):
  M0  no change                       log m1 = log m0
  M1  market drift                    + log m0 (mean reversion / drop-out risk)
  M2  + sim                           + log sim rank
  M3  + age x position + rookie       (+ position dummies)
  M4  + momentum (last year's move)   (players with a prior-year rank)
  M5  M3 + sim youth share            (share of SIM DYN that is the youth credit)
Metrics: Spearman of predicted vs actual next rank; MAE in log rank; and the
part that matters for buy / sell — Spearman of predicted MOVE vs actual move.
SIM = current prototype (local-linear comps, QB age 6), preseason, 1QB PPR.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS  # noqa: E402
from backtest_dynasty_inseason import ffc_adp  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

LAST_DATA = 2025
YEARS = list(range(2015, 2024))
LL = (120, 5.0)
YW = 1.5
DROP = 250
POS = ('QB', 'RB', 'WR', 'TE')


def build():
    w = World(LAST_DATA)
    rows = w.rows(FORMATS['1qb'], YEARS[-1])
    comps = Comps(rows, LAST_DATA, {'QB': 6.0})
    idx = {(r['key'], r['Y']): r for r in rows}
    adp = {y: {(n, p): a for n, p, a in ffc_adp(y)} for y in range(2014, 2026)}
    recs = []
    for Y in YEARS:
        pool = [idx[(k, Y)] for k in adp[Y] if (k, Y) in idx]
        for r in pool:
            if r['rookie']:
                ev = comps.ev(r['pos'], True, Comps.feat_rookie(r['pick'], r['age0']), Y, exclude_key=r['key'], local_linear=LL)
            else:
                ev = comps.ev(r['pos'], False, comps.feat_v(r['pos'], r['age0'], r['rel'], r['gp1']), Y,
                              exclude_key=r['key'], local_linear=LL)
            r['_sim'] = sum(ev[:3]) + YW * sum(ev[3:])
            r['_yshare'] = (YW * sum(ev[3:])) / r['_sim'] if r['_sim'] > 1 else 0.0
        mk = sorted(pool, key=lambda r: adp[Y][r['key']])
        mrank = {r['key']: i + 1 for i, r in enumerate(mk)}
        sk = sorted(pool, key=lambda r: -r['_sim'])
        srank = {r['key']: i + 1 for i, r in enumerate(sk)}
        # next / previous year: rank within that year's matched pool
        def ranks(y):
            pl = [k for k in adp.get(y, {}) if (k, y) in idx]
            return {k: i + 1 for i, k in enumerate(sorted(pl, key=lambda k: adp[y][k]))}
        nxt, prv = ranks(Y + 1), ranks(Y - 1)
        for r in pool:
            k = r['key']
            recs.append({'Y': Y, 'name': k[0], 'pos': k[1], 'age': r['age0'], 'rookie': int(r['rookie']),
                         't3': sum(v or 0 for v in r['vor'][:3]), 't5': sum(v or 0 for v in r['vor'][:5]),
                         'm0': mrank[k], 's0': srank[k], 'm1': min(nxt.get(k, DROP), DROP), 'mp': prv.get(k),
                         'ys': r['_yshare']})
    return recs


def design(recs, spec):
    X = []
    for r in recs:
        row = [1.0, math.log(r['m0'])]
        if spec >= 2:
            row.append(math.log(r['s0']))
        if spec >= 3:
            a = r['age'] - 25.0
            row += [r['rookie']] + [1.0 if r['pos'] == p else 0.0 for p in POS[1:]] + [a * (1.0 if r['pos'] == p else 0.0) for p in POS]
        if spec == 4:
            row.append(math.log(r['m0'] / r['mp']) if r['mp'] else 0.0)
            row.append(1.0 if r['mp'] else 0.0)
        if spec == 5:
            row.append(r['ys'])
        X.append(row)
    return np.array(X)


def main():
    recs = build()
    print(f'{len(recs)} player-years, start {YEARS[0]}-{YEARS[-1]}; '
          f'{sum(r["m1"] == DROP for r in recs)} fell out of the next year\'s ADP')
    yv = np.array([math.log(r['m1']) for r in recs])
    m0 = np.array([math.log(r['m0']) for r in recs])
    preds = {'M0 no change': m0.copy()}
    names = {1: 'M1 market drift', 2: 'M2 + sim rank', 3: 'M3 + age x pos, rookie', 4: 'M4 + momentum', 5: 'M5 + youth share'}
    coefs = {}
    for spec, nm in names.items():
        X = design(recs, spec)
        p = np.zeros(len(recs))
        for Y in YEARS:
            tr = np.array([r['Y'] != Y for r in recs]); te = ~tr
            lam = 1e-3 * np.eye(X.shape[1]); lam[0, 0] = 0
            b = np.linalg.solve(X[tr].T @ X[tr] + lam, X[tr].T @ yv[tr])
            p[te] = X[te] @ b
        preds[nm] = p
        lam = 1e-3 * np.eye(X.shape[1]); lam[0, 0] = 0
        coefs[spec] = np.linalg.solve(X.T @ X + lam, X.T @ yv)
    print(f'\n{"model (LOYO)":<26}{"Sp next rank":>13}{"MAE log":>9}{"Sp move":>9}{"top-50 Sp":>10}')
    for nm, p in preds.items():
        def per_year(a, b, sub=None):
            num = den = 0.0
            for Y in YEARS:
                ix = [i for i, r in enumerate(recs) if r['Y'] == Y and (sub is None or sub(r))]
                if len(ix) < 15:
                    continue
                s = spearman([a[i] for i in ix], [b[i] for i in ix])
                if s is not None:
                    num += s * len(ix); den += len(ix)
            return num / den
        sp = per_year(-p, -yv)
        mae = float(np.mean(np.abs(p - yv)))
        mv = per_year(-(p - m0), -(yv - m0)) if nm != 'M0 no change' else float('nan')
        t50 = per_year(-p, -yv, lambda r: r['m0'] <= 50)
        print(f'{nm:<26}{sp:>13.3f}{mae:>9.3f}{mv:>9.3f}{t50:>10.3f}')
    # FAIR VALUE NOW (Jack: "value players in the moment with the idea they have future value"):
    # order players by M3's predicted next-year market rank (LOYO) and score that ORDER on
    # both the market a year out and realized production, against the alternatives.
    p3 = preds['M3 + age x pos, rookie']
    orders = {'KTC/market now': lambda i: -recs[i]['m0'], 'DYN SIM': lambda i: -recs[i]['s0'],
              'SIM x market 50/50': lambda i: -(math.log(recs[i]['m0']) + math.log(recs[i]['s0'])),
              'FAIR (M3 order)': lambda i: -p3[i]}
    for a_ in (0.3, 0.5, 0.7):
        orders[f'FAIR {a_:.1f} + SIM {1 - a_:.1f}'] = (lambda i, a_=a_: -(a_ * p3[i] + (1 - a_) * math.log(recs[i]['s0'])))
    print(f'\n=== FAIR VALUE NOW — how well each ORDER ranks (per-year Spearman) ===')
    print(f'{"order":<22}{"next-yr market":>15}{"3yr VOR":>9}{"5yr VOR":>9}{"avg":>7}{"top-50 3yr":>11}')
    for lbl, f in orders.items():
        def py(truth, sub=None, yrs=YEARS):
            num = den = 0.0
            for Y in yrs:
                ix = [i for i, r in enumerate(recs) if r['Y'] == Y and (sub is None or sub(r))]
                if len(ix) < 15:
                    continue
                s = spearman([f(i) for i in ix], [truth(i) for i in ix])
                if s is None:
                    continue
                num += s * len(ix); den += len(ix)
            return num / den
        a = py(lambda i: -yv[i]); b = py(lambda i: recs[i]['t3'])
        c = py(lambda i: recs[i]['t5'], yrs=[y for y in YEARS if y + 4 <= LAST_DATA])
        d = py(lambda i: recs[i]['t3'], lambda r: r['m0'] <= 50)
        print(f'{lbl:<22}{a:>15.3f}{b:>9.3f}{c:>9.3f}{(a + b) / 2:>7.3f}{d:>11.3f}')
    # Edge beyond rank drift: M3's predicted extra move over M1 vs the actual move left after M1.
    p1, p3 = preds['M1 market drift'], preds['M3 + age x pos, rookie']
    num = den = 0.0
    for Y in YEARS:
        ix = [i for i, r in enumerate(recs) if r['Y'] == Y]
        s = spearman([-(p3[i] - p1[i]) for i in ix], [-(yv[i] - p1[i]) for i in ix])
        num += s * len(ix); den += len(ix)
    print(f'\nEdge beyond normal drift (M3 - M1 predicted vs actual residual): per-year Spearman {num / den:+.3f}')
    b = coefs[3]
    lbl = ['const', 'log mkt rank', 'log sim rank', 'rookie', 'RB', 'WR', 'TE', 'age*QB', 'age*RB', 'age*WR', 'age*TE']
    print('\nM3 full-sample coefficients (log next rank; negative = rises):')
    print('   ' + ', '.join(f'{l} {v:+.3f}' for l, v in zip(lbl, b)))
    json.dump({'spec': 'M3', 'labels': lbl, 'coef': [round(float(v), 5) for v in b],
               'm1': [round(float(v), 5) for v in coefs[1]], 'drop': DROP,
               'edgeSp': round(num / den, 3), 'nextSp': 0.697, 'naiveSp': 0.663,
               'ageCenter': 25.0, 'years': [YEARS[0], YEARS[-1]], 'n': len(recs)},
              open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json'), 'w'), indent=1)
    # calibration: predicted vs actual move by predicted-move quintile
    p = preds['M3 + age x pos, rookie']
    mv_p, mv_a = p - m0, yv - m0
    order = np.argsort(mv_p)
    print('\nM3 by predicted-move fifth (log-rank move; negative = market rank improves):')
    for q in range(5):
        ix = order[q * len(order) // 5:(q + 1) * len(order) // 5]
        print(f'   Q{q + 1}: predicted {np.mean(mv_p[ix]):+.2f}  actual {np.mean(mv_a[ix]):+.2f}  '
              f'(median rank {int(np.median([recs[i]["m0"] for i in ix]))} -> {int(np.median([recs[i]["m1"] for i in ix]))})')


if __name__ == '__main__':
    main()
