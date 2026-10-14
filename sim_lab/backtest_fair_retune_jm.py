#!/usr/bin/env python3
"""
backtest_fair_retune_jm.py — re-check the FAIR VALUE order after the conditional
JM credit changed the Dynasty SIM for years 1-3 (Jack 2026-10-09: "start with 1").

Pool / truths / scoring = backtest_fair_tune.py (FFC dynasty ADP pool 2016-23,
1QB PPR; per-year Spearman vs next-year market rank, realized 3yr VOR, 5yr +
youth, 3yr within the market top 50). Compared:
  OLD sim  (pre-JM, what FAIR was tuned on) with the shipped M3 coefficients
  NEW sim  (conditional JM, time-honest kernel) with
           (a) the shipped M3 coefficients (what the site does today)
           (b) M3 refit on the new sim ranks, leave-one-year-out
Then the weight grid (wM M3, wS log sim rank, wK log market rank) is re-run on
the new sim with refit M3; the winner is checked season by season against the
shipped weights (0.5 / 0.3 / 0.5) on the same inputs.
"""
import itertools
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from backtest_value_score import build, YEARS, LAST  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

SHIP = (0.5, 0.3, 0.5)


def feats(x):
    a = x['age'] - 25.0; P = x['pos']
    return [1.0, math.log(x['m0']), math.log(x['s0']), x['rookie'], P == 'RB', P == 'WR', P == 'TE',
            a * (P == 'QB'), a * (P == 'RB'), a * (P == 'WR'), a * (P == 'TE')]


def m3_ship(recs, c):
    for x in recs:
        x['m3'] = float(np.dot(c, feats(x)))


def m3_loyo(recs):
    """M3 refit leave-one-year-out (log next-year market rank, capped at 250)."""
    X = np.array([feats(x) for x in recs], float); y = np.array([math.log(x['m1']) for x in recs])
    yrs = np.array([x['Y'] for x in recs])
    coef_all = np.linalg.lstsq(X, y, rcond=None)[0]
    for Y in YEARS:
        tr = yrs != Y
        b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
        for i in np.where(~tr)[0]:
            recs[i]['m3'] = float(X[i] @ b)
    return coef_all


def scorer(recs):
    y5 = [y for y in YEARS if y + 4 <= LAST]

    def score(f, yrs=YEARS):
        out = {}
        for nm, truth, sub, ys in (('next mkt', lambda x: -x['m1'], None, yrs), ('3yr', lambda x: -x['r_t3'], None, yrs),
                                    ('5yr+youth', lambda x: -x['r_lt'], None, [y for y in yrs if y in y5]),
                                    ('top-50 3yr', lambda x: -x['r_t3'], lambda x: x['m0'] <= 50, yrs)):
            num = den = 0.0
            for Y in ys:
                xs = [x for x in recs if x['Y'] == Y and (nm != '5yr+youth' or 'r_lt' in x) and 'r_t3' in x and (sub is None or sub(x))]
                if len(xs) < 10:
                    continue
                s = spearman([f(x) for x in xs], [truth(x) for x in xs])
                if s is not None:
                    num += s * len(xs); den += len(xs)
            out[nm] = num / den if den else float('nan')
        vals = [v for v in out.values() if v == v]
        out['avg'] = sum(vals) / len(vals)
        return out
    return score


def order(wM, wS, wK):
    return lambda x: -(wM * x['m3'] + wS * math.log(x['s0']) + wK * math.log(x['m0']))


def line(nm, s):
    print(f'{nm:<46}{s["next mkt"]:>9.3f}{s["3yr"]:>7.3f}{s["5yr+youth"]:>7.3f}{s["top-50 3yr"]:>7.3f}{s["avg"]:>7.3f}')


def main():
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    print('building OLD sim pool...'); old = build(False)
    print('building NEW sim pool (conditional JM)...'); new = build(True)
    hdr = f'{"":<46}{"next mkt":>9}{"3yr":>7}{"5yr+y":>7}{"top50":>7}{"avg":>7}'

    print('\n=== sim alone + shipped FAIR, old vs new sim ===\n' + hdr)
    m3_ship(old, c); so = scorer(old)
    line('market now', so(lambda x: -x['m0']))
    line('OLD sim alone', so(lambda x: -x['s0']))
    line('OLD sim, shipped FAIR (0.5/0.3/0.5)', so(order(*SHIP)))
    m3_ship(new, c); sn = scorer(new)
    line('NEW sim alone', sn(lambda x: -x['s0']))
    line('NEW sim, shipped FAIR, shipped M3 (= site now)', sn(order(*SHIP)))
    coef_new = m3_loyo(new); sn = scorer(new)
    line('NEW sim, shipped FAIR, M3 refit (LOYO)', sn(order(*SHIP)))
    young = [x for x in new if x['rookie'] or (x['age'] <= 24)]
    print(f'   pool {len(new)} player-seasons, {len(young)} rookies / age <= 24')

    print('\n=== weight grid on NEW sim + refit M3 ===\n' + hdr)
    grid = []
    for wM, wS, wK in itertools.product((0.7, 0.5, 0.3, 0.0), (0.2, 0.3, 0.4, 0.5, 0.6), (0.0, 0.2, 0.35, 0.5, 0.7)):
        if wM + wK == 0:
            continue
        grid.append(((wM, wS, wK), sn(order(wM, wS, wK))))
    grid.sort(key=lambda g: -g[1]['avg'])
    for (wM, wS, wK), s in grid[:8]:
        line(f'M3 {wM} sim {wS} mkt {wK}', s)
    best = grid[0][0]
    wins = 0
    for Y in YEARS:
        a, b = sn(order(*best), [Y])['avg'], sn(order(*SHIP), [Y])['avg']
        wins += a > b
        print(f'   {Y}: best {a:.3f} vs shipped weights {b:.3f}')
    print(f'best {best} beats shipped weights in {wins} of {len(YEARS)} seasons (same new-sim inputs)')
    # neighbourhood of the shipped weights: is it on the plateau?
    near = [g for g in grid if abs(g[0][0] - SHIP[0]) <= 0.2 and abs(g[0][1] - SHIP[1]) <= 0.1 and abs(g[0][2] - SHIP[2]) <= 0.15]
    print('   shipped-weight neighbourhood avg: ' + ', '.join(f'{g[0]} {g[1]["avg"]:.3f}' for g in near[:6]))
    json.dump({'best': best, 'score': grid[0][1], 'm3_refit': [round(float(v), 5) for v in coef_new], 'm3_ship': c},
              open(os.path.join(HERE, '_dyn_cache', 'fair_retune_jm.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
