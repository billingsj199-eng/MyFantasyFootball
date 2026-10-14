#!/usr/bin/env python3
"""
backtest_fair_tune.py — tune the shipped FAIR VALUE order (Jack 2026-10-09:
"test the tuned fair value").

Shipped:  z = 0.7 * M3(expected next-year market rank) + 0.3 * log sim rank
Variants: z = wM * M3 + wS * log sim rank + wK * log market rank now
          + kWR * (age - 25) for WRs   (WR aging = the one long-term driver the
          market underprices at today's price, backtest_value_score.py t 3.1)
Scored per year (Spearman) on: next-year market rank, realized 3yr VOR,
realized 5yr+youth VOR, and 3yr within the market's top 50. Because the winner
is picked from a grid, it is also scored season by season against the shipped
order (how many of the 8 seasons it beats it on the average of the four).
"""
import itertools
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from backtest_value_score import build, YEARS, LAST  # noqa: E402
from backtest_js_model import spearman  # noqa: E402


def main():
    recs = build()
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    for x in recs:
        a = x['age'] - 25.0; P = x['pos']
        x['m3'] = c[0] + c[1] * math.log(x['m0']) + c[2] * math.log(x['s0']) + c[3] * x['rookie'] + (c[4] if P == 'RB' else 0) \
            + (c[5] if P == 'WR' else 0) + (c[6] if P == 'TE' else 0) + a * (c[7] if P == 'QB' else c[8] if P == 'RB' else c[9] if P == 'WR' else c[10])
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

    def order(wM, wS, wK, kWR):
        return lambda x: -(wM * x['m3'] + wS * math.log(x['s0']) + wK * math.log(x['m0']) + (kWR * (x['age'] - 25.0) if x['pos'] == 'WR' else 0.0))
    shipped = order(0.7, 0.3, 0.0, 0.0)
    base = score(shipped)
    rows = [('SHIPPED fair (0.7 M3 + 0.3 sim)', base), ('market now', score(lambda x: -x['m0'])),
            ('SIM x market 50/50', score(lambda x: -(math.log(x['m0']) + math.log(x['s0']))))]
    grid = []
    for wM, wS, wK, kWR in itertools.product((0.7, 0.5, 0.3, 0.0), (0.3, 0.4, 0.5), (0.0, 0.2, 0.35, 0.5), (0.0, 0.02, 0.04, 0.06)):
        if wM + wK == 0:
            continue
        grid.append(((wM, wS, wK, kWR), score(order(wM, wS, wK, kWR))))
    grid.sort(key=lambda g: -g[1]['avg'])
    print(f'{"order":<44}{"next mkt":>9}{"3yr":>7}{"5yr+y":>7}{"top50":>7}{"avg":>7}')
    for nm, s in rows:
        print(f'{nm:<44}{s["next mkt"]:>9.3f}{s["3yr"]:>7.3f}{s["5yr+youth"]:>7.3f}{s["top-50 3yr"]:>7.3f}{s["avg"]:>7.3f}')
    print('--- best 8 tuned (wM M3, wS sim, wK market, kWR WR age) ---')
    for (wM, wS, wK, kWR), s in grid[:8]:
        print(f'{f"M3 {wM} sim {wS} mkt {wK} WRage {kWR}":<44}{s["next mkt"]:>9.3f}{s["3yr"]:>7.3f}{s["5yr+youth"]:>7.3f}{s["top-50 3yr"]:>7.3f}{s["avg"]:>7.3f}')
    # WR-age effect alone on top of shipped
    for k in (0.02, 0.04, 0.06):
        s = score(order(0.7, 0.3, 0.0, k))
        print(f'{f"shipped + WR age {k}":<44}{s["next mkt"]:>9.3f}{s["3yr"]:>7.3f}{s["5yr+youth"]:>7.3f}{s["top-50 3yr"]:>7.3f}{s["avg"]:>7.3f}')
    best = grid[0][0]
    wins = 0
    for Y in YEARS:
        a, b = score(order(*best), [Y])['avg'], score(shipped, [Y])['avg']
        wins += a > b
        print(f'   {Y}: best {a:.3f} vs shipped {b:.3f}')
    print(f'best {best} beats shipped in {wins} of {len(YEARS)} seasons')
    json.dump({'best': best, 'score': grid[0][1], 'shipped': base}, open(os.path.join(HERE, '_dyn_cache', 'fair_tune.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
