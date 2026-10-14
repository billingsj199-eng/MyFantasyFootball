#!/usr/bin/env python3
"""
backtest_fair_qb_weight.py — should FAIR lean less on the sim for QBs?
(Jack 2026-10-09 QB test: richer QB comps didn't help, and for QBs the market
alone beat even a 50/50 sim x market blend — SF .527 vs .478.)

FAIR z = 0.5 M3 + wS * log sim rank + 0.5 log market rank, with wS = 0.3 for
RB / WR / TE and wS_QB in {0, .1, .2, .3 (shipped)} for QBs. Leave-one-year-out
pick of wS_QB, scored on the whole pool and QB-only:
  1QB  FFC dynasty pool 2016-23 (backtest_value_score.build, shipped JM sim)
       truths: next-year market, 3yr, 5yr+youth
  SF   KTC SF survivor pool 2021-25 (backtest_fair_sf.py machinery)
"""
import json
import math
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from backtest_value_score import build, YEARS, LAST  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

GRID = (0.0, 0.1, 0.2, 0.3)


def per_year(recs, f, tk, years, sub=None):
    out = []
    for Y in years:
        xs = [x for x in recs if x['Y'] == Y and x.get(tk) and (sub is None or sub(x))]
        if len(xs) >= 8:
            v = spearman([f(x) for x in xs], [-x[tk] for x in xs])
            if v is not None:
                out.append(v)
    return float(np.mean(out)) if out else float('nan')


def main():
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = build(True)
    m3_ship(recs, c)

    def order(wq):
        return lambda x: -(0.5 * x['m3'] + (wq if x['pos'] == 'QB' else 0.3) * math.log(x['s0']) + 0.5 * math.log(x['m0']))
    qb = lambda x: x['pos'] == 'QB'
    print('=== 1QB FFC pool 2016-23 (per-year Spearman) ===')
    print(f'{"wS for QBs":<14}{"all next":>9}{"all 3yr":>9}{"all 5y+":>9}{"QB 3yr":>9}{"QB 5y+":>9}')
    y5 = [y for y in YEARS if y + 4 <= LAST]
    print(f'{"market":<14}{per_year(recs, lambda x: -x["m0"], "m1", YEARS):>9.3f}{per_year(recs, lambda x: -x["m0"], "r_t3", YEARS):>9.3f}'
          f'{per_year(recs, lambda x: -x["m0"], "r_lt", y5):>9.3f}{per_year(recs, lambda x: -x["m0"], "r_t3", YEARS, qb):>9.3f}{per_year(recs, lambda x: -x["m0"], "r_lt", y5, qb):>9.3f}')
    for wq in GRID:
        f = order(wq)
        nm = per_year(recs, f, 'm1', YEARS)
        print(f'{wq:<14}{nm:>9.3f}{per_year(recs, f, "r_t3", YEARS):>9.3f}{per_year(recs, f, "r_lt", y5):>9.3f}'
              f'{per_year(recs, f, "r_t3", YEARS, qb):>9.3f}{per_year(recs, f, "r_lt", y5, qb):>9.3f}{"   (shipped)" if wq == 0.3 else ""}')
    # LOYO choice of wS_QB on the all-pool 3yr + 5yr average
    d, picks = [], []
    for Y in YEARS:
        tr = [y for y in YEARS if y != Y]
        best = max(GRID, key=lambda wq: per_year(recs, order(wq), 'r_t3', tr) + per_year(recs, order(wq), 'r_lt', [y for y in tr if y in y5]))
        picks.append(best)
        d.append(per_year(recs, order(best), 'r_t3', [Y]) - per_year(recs, order(0.3), 'r_t3', [Y]))
    print(f'LOYO wS_QB picks {picks}; held-out 3yr change vs shipped {np.mean(d):+.4f}, wins {sum(x > 1e-9 for x in d)}/{len(d)}')


if __name__ == '__main__':
    main()
