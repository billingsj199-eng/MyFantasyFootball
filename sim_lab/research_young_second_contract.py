#!/usr/bin/env python3
"""
research_young_second_contract.py — do young players on big second contracts beat
MFF VALUE (FAIR)? (Jack 2026-10-10: "test the young second contract group")

The 10-09 contract layer (backtest_dynasty_sim.py section F) found young players
on big second deals (<= 26, cap >= 6%, multi-year) beat the sim's comps x1.28
WIN3 / x1.52 YOUTH, but the whole-pool layer had zero forward gain. Here: that
one group only, as a FAIR order term, same harness as the QB team-total test.

Pool: FFC dynasty pool 2016-23 (1QB PPR), shipped JM sim + FAIR. Contract state
entering Y from OTC at-signing fields (year_signed / years / apy_cap_pct), the
latest deal covering Y that is NOT his rookie deal (signed in his draft year).
  strict: deal signed <= Y-1 (known before that year's March for sure);
  loose : deal signed <= Y (most signings land Feb-Aug, before FFC ADP).
Group variants: age <= 26 / <= 27, cap >= 6% / >= 4%, years left >= 2.
Truth: realized VOR rank season Y, 3 years, 5 years + youth.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, FORMATS  # noqa: E402
from backtest_value_score import build  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402
from backtest_dynasty_sim import load_contracts  # noqa: E402

YRS = list(range(2016, 2024))
K = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8]


def main():
    w = World(2025)
    w.rows(FORMATS['1qb'], 2025)
    con = load_contracts()
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = [x for x in build(True) if x['Y'] in YRS]
    m3_ship(recs, c)
    for x in recs:
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
        x['v1'] = w.vor(x['key'], x['Y']) or 0.0
        dr = (w.players.get(x['key']) or {}).get('draft')
        x['dy'] = dr[0] if dr else None
        for mode, lag in (('strict', 1), ('loose', 0)):
            deals = [d for d in con.get(x['key'], []) if d[0] <= x['Y'] - lag and d[0] + d[1] - 1 >= x['Y']
                     and not (x['dy'] is not None and d[0] == x['dy'])]
            x['deal_' + mode] = max(deals, key=lambda d: d[0]) if deals else None
    TR = {}
    for tk, key in (('r1', lambda x: -x['v1']), ('r3', lambda x: x['r_t3']), ('r5', lambda x: x['r_lt'])):
        for Y in YRS:
            ys = [x for x in recs if x['Y'] == Y]
            if tk == 'r5' and any(x.get('r_lt') is None for x in ys):
                continue
            for i, x in enumerate(sorted(ys, key=key)):
                TR[(tk, id(x))] = i + 1

    def flag(x, mode, amax, cmin, left):
        d = x['deal_' + mode]
        return bool(d and x['age'] is not None and x['age'] <= amax and d[2] >= cmin
                    and d[0] + d[1] - x['Y'] >= left and x['pos'] in ('RB', 'WR', 'TE', 'QB'))

    def board(k, tk, sel, years):
        out = []
        for Y in years:
            ys = [x for x in recs if x['Y'] == Y]
            f = lambda x: x['fz'] - (k if sel(x) else 0)
            out.append(spearman([-f(x) for x in ys], [-TR[(tk, id(x))] for x in ys]))
        return np.array(out)

    print(f'pool {len(recs)} player-seasons {YRS[0]}-{YRS[-1]}')
    print(f'{"variant":<34}{"n":>4}  {"beat FAIR (mean log rank resid, - = beat)":<44}  whole-board per-year Spearman')
    for mode in ('strict', 'loose'):
        for amax in (26, 27):
            for cmin in (0.06, 0.04):
                for left in (2, 1):
                    sel = (lambda m, a, cm, l: (lambda x: flag(x, m, a, cm, l)))(mode, amax, cmin, left)
                    g = [x for x in recs if sel(x)]
                    lbl = f'{mode} age<={amax} cap>={int(cmin*100)}% left>={left}'
                    if len(g) < 10:
                        print(f'{lbl:<34}{len(g):>4}  too few'); continue
                    res = []
                    for tk in ('r1', 'r3', 'r5'):
                        rr = [math.log(TR[(tk, id(x))]) - x['fz'] for x in g if (tk, id(x)) in TR]
                        # FAIR's typical residual for the same FAIR rank: compare to pool mean residual
                        pool_rr = [math.log(TR[(tk, id(x))]) - x['fz'] for x in recs if (tk, id(x)) in TR]
                        res.append(f'{tk} {np.mean(rr) - np.mean(pool_rr):+.2f}')
                    cells = []
                    for tk in ('r1', 'r3', 'r5'):
                        yrs = [Y for Y in YRS if all((tk, id(x)) in TR for x in recs if x['Y'] == Y)]
                        S = {k: board(k, tk, sel, yrs) for k in K}
                        b = S[0]
                        d = []
                        for i in range(len(yrs)):
                            kk = max(K, key=lambda k: np.delete(S[k], i).mean()); d.append(S[kk][i] - b[i])
                        kb = max(K, key=lambda k: S[k].mean())
                        cells.append(f'{tk} k{kb} LOYO {np.mean(d):+.4f} ({sum(v > 1e-9 for v in d)}/{len(yrs)})')
                    print(f'{lbl:<34}{len(g):>4}  {"  ".join(res):<44}  ' + ' | '.join(cells))
    # who is in the main group
    g = [x for x in recs if flag(x, 'strict', 26, 0.06, 2)]
    print('\nstrict age<=26 cap>=6% left>=2 — examples (FAIR rank in year -> realized season / 3yr rank):')
    fr = {}
    for Y in YRS:
        for i, x in enumerate(sorted([x for x in recs if x['Y'] == Y], key=lambda x: x['fz'])):
            fr[id(x)] = i + 1
    for x in sorted(g, key=lambda x: (x['Y'], fr[id(x)])):
        d = x['deal_strict']
        print(f'   {x["Y"]} {x["key"][0]:<22}{x["pos"]:<3} age {x["age"]}  deal {d[0]} {d[1]}y {d[2]*100:.1f}% cap'
              f'  FAIR #{fr[id(x)]:<4} -> season #{TR[("r1", id(x))]:<4} 3yr #{TR[("r3", id(x))]}')


if __name__ == '__main__':
    main()
