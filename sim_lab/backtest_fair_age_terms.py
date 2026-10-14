#!/usr/bin/env python3
"""
backtest_fair_age_terms.py — do age x position terms improve the FAIR order?
(Jack 2026-10-09: "test the age x position fair terms"; signals from
research_age_value.py: FAIR still overvalues RBs 25-26 and undervalues QBs
<=22 and 30+, WR 30+ mildly overvalued.)

FAIR z = 0.5 M3 + 0.3 log sim rank + 0.5 log market rank (shipped, lower =
better) + sum_g k_g * [player in group g] (k > 0 pushes a group DOWN).
Groups: RB_25_27, QB_U22 (<=22), QB_30, WR_30, and the smooth alternative
RB_SLOPE = max(0, age - 24) for RBs.
Each k is chosen LEAVE-ONE-YEAR-OUT: coordinate search on the other seasons'
average score (next-yr market / 3yr / 5yr+youth / top-50 3yr, as
backtest_fair_tune.py), then scored on the held-out season. Pool / sim = FFC
2016-23 with the shipped conditional-JM sim and the shipped M3 coefficients.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from backtest_value_score import build, YEARS  # noqa: E402
from backtest_fair_retune_jm import scorer, m3_ship  # noqa: E402

GROUPS = {
    'RB_25_27': lambda x: float(x['pos'] == 'RB' and 25 <= x['age'] < 28),
    'QB_U22': lambda x: float(x['pos'] == 'QB' and x['age'] < 23),
    'QB_30': lambda x: float(x['pos'] == 'QB' and x['age'] >= 30),
    'WR_30': lambda x: float(x['pos'] == 'WR' and x['age'] >= 30),
    'RB_SLOPE': lambda x: max(0.0, x['age'] - 24.0) if x['pos'] == 'RB' else 0.0,
}
KGRID = (-0.6, -0.4, -0.25, -0.15, 0.0, 0.15, 0.25, 0.4, 0.6)
SLOPE_GRID = (-0.1, -0.05, 0.0, 0.05, 0.1, 0.15, 0.2)


def main():
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = build(True)
    m3_ship(recs, c)
    for x in recs:
        x['z0'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
        for g, f in GROUPS.items():
            x['g_' + g] = f(x)
    score = scorer(recs)

    def order(ks):
        return lambda x: -(x['z0'] + sum(k * x['g_' + g] for g, k in ks.items()))

    def fit(groups, yrs, passes=2):
        ks = {g: 0.0 for g in groups}
        for _ in range(passes):
            for g in groups:
                grid = SLOPE_GRID if g == 'RB_SLOPE' else KGRID
                best = max(grid, key=lambda v: score(order(dict(ks, **{g: v})), yrs)['avg'])
                ks[g] = best
        return ks

    hdr = f'{"variant":<34}{"next mkt":>9}{"3yr":>7}{"5yr+y":>7}{"top50":>7}{"avg":>7}{"  beats shipped":>16}'
    base = score(order({}))

    def line(nm, s, wins=''):
        print(f'{nm:<34}{s["next mkt"]:>9.3f}{s["3yr"]:>7.3f}{s["5yr+youth"]:>7.3f}{s["top-50 3yr"]:>7.3f}{s["avg"]:>7.3f}{wins:>16}')
    print('=== in-sample fit (all seasons) — what each term WANTS ===')
    for g in GROUPS:
        ks = fit([g], YEARS, passes=1)
        line(f'{g} k={ks[g]:+.2f}', score(order(ks)))
    print('\n=== LEAVE-ONE-YEAR-OUT (k chosen on the other 7 seasons, scored on the held-out one) ===\n' + hdr)
    line('SHIPPED FAIR (no age terms)', base)
    variants = [['RB_25_27'], ['QB_U22'], ['QB_30'], ['WR_30'], ['RB_SLOPE'],
                ['RB_25_27', 'QB_U22', 'QB_30', 'WR_30'], ['RB_SLOPE', 'QB_U22', 'QB_30', 'WR_30']]
    out = {}
    for groups in variants:
        per_year, picks, wins = {}, [], 0
        for Y in YEARS:
            tr = [y for y in YEARS if y != Y]
            ks = fit(groups, tr)
            picks.append(ks)
            s_new = score(order(ks), [Y]); s_old = score(order({}), [Y])
            per_year[Y] = (s_new, s_old)
            wins += s_new['avg'] > s_old['avg'] + 1e-9
        # pooled LOYO score: average the held-out seasons' metrics (weighted like score())
        agg = {m: np.mean([per_year[Y][0][m] for Y in YEARS if per_year[Y][0][m] == per_year[Y][0][m]]) for m in base}
        aggb = {m: np.mean([per_year[Y][1][m] for Y in YEARS if per_year[Y][1][m] == per_year[Y][1][m]]) for m in base}
        name = '+'.join(groups)
        line(name, agg, f'{wins}/{len(YEARS)} ({agg["avg"] - aggb["avg"]:+.4f})')
        kss = {g: [p[g] for p in picks] for g in groups}
        print('      k per fold: ' + '; '.join(f'{g} {min(v):+.2f}..{max(v):+.2f} (median {np.median(v):+.2f})' for g, v in kss.items()))
        out[name] = {'avg_delta': agg['avg'] - aggb['avg'], 'wins': wins, 'k': {g: float(np.median(v)) for g, v in kss.items()}}
    json.dump(out, open(os.path.join(HERE, '_dyn_cache', 'fair_age_terms.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
