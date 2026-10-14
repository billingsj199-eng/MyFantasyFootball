#!/usr/bin/env python3
"""
backtest_old_rb_productive.py — do PRODUCTIVE older RBs beat MFF VALUE (FAIR)? (Jack
2026-10-10: "test the productive older rb signal", after backtest_rb_rec_groups.py found
RBs 28+ finished better than their FAIR rank, -0.17 log 3yr, n 24 — Henry's case.)

The 10-09 age test (backtest_fair_age_terms.py) only tried pushing RBs DOWN (RB 25-27 dock,
RB age slope) and picked k = 0 every fold. This is the other direction, limited to backs
still producing: flag = RB, age >= A, prior season >= G games and PPR per game >= R x the
replacement starter (dyn_common.season_rel). FAIR score -= k x flag (moves them up).
Pool: FFC dynasty pool 2016-23 (1QB PPR), shipped JM sim + FAIR (no RB receiving tilt —
PFF only covers 2019+). k chosen leave-one-year-out on the average of 3yr + season
whole-board per-year Spearman; also RB-only and the flagged group's residual.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, FORMATS, season_rel  # noqa: E402
from backtest_value_score import build  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

YRS = list(range(2016, 2024))
K = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.75]


def main():
    w = World(2025)
    w.rows(FORMATS['1qb'], 2025)
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = [x for x in build(True) if x['Y'] in YRS]
    m3_ship(recs, c)
    for x in recs:
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
        x['v1'] = w.vor(x['key'], x['Y']) or 0.0
        x['g1'], x['rel1'] = season_rel(w, x['key'], x['Y'] - 1) if x['pos'] == 'RB' else (0, 0.0)
    TR = {}
    for tk, key in (('r1', lambda x: -x['v1']), ('r3', lambda x: x['r_t3']), ('r5', lambda x: x['r_lt'])):
        for Y in YRS:
            ys = [x for x in recs if x['Y'] == Y]
            if tk == 'r5' and any(x.get('r_lt') is None for x in ys):
                continue
            for i, x in enumerate(sorted(ys, key=key)):
                TR[(tk, id(x))] = i + 1
    FR = {}
    for Y in YRS:
        for i, x in enumerate(sorted([x for x in recs if x['Y'] == Y], key=lambda x: x['fz'])):
            FR[id(x)] = i + 1

    def board(k, sel, tk, sub=None):
        out = []
        for Y in YRS:
            ys = [x for x in recs if x['Y'] == Y and (sub is None or x['pos'] == sub)]
            if any((tk, id(x)) not in TR for x in ys):
                continue
            out.append(spearman([-(x['fz'] - (k if sel(x) else 0)) for x in ys], [-TR[(tk, id(x))] for x in ys]))
        return np.array(out)

    print(f'pool {len(recs)} player-seasons {YRS[0]}-{YRS[-1]}')
    print(f'{"flag":<34}{"n":>4}  {"resid 3yr/5yr (+ = worse than FAIR)":<38} LOYO whole (season+3yr)   whole 5yr   RB-only 3yr')
    for A in (27, 28, 29, 30):
        for R in (1.0, 1.3):
            for G in (8,):
                sel = (lambda A, R, G: (lambda x: x['pos'] == 'RB' and (x['age'] or 0) >= A and x['g1'] >= G and x['rel1'] >= R))(A, R, G)
                g = [x for x in recs if sel(x)]
                if len(g) < 8:
                    print(f'RB age>={A} rel>={R} g>={G}: n {len(g)} too few'); continue
                rs = []
                for tk in ('r3', 'r5'):
                    gg = [x for x in g if (tk, id(x)) in TR]
                    rs.append(f'{np.mean([math.log(TR[(tk, id(x))] / FR[id(x)]) for x in gg]):+.2f} (n {len(gg)})')
                S1 = {k: board(k, sel, 'r1') for k in K}
                S3 = {k: board(k, sel, 'r3') for k in K}
                obj = {k: (S1[k] + S3[k]) / 2 for k in K}
                d, picks = [], []
                for i in range(len(YRS)):
                    kb = max(K, key=lambda k: np.delete(obj[k], i).mean()); picks.append(kb); d.append(obj[kb][i] - obj[0][i])
                S5 = {k: board(k, sel, 'r5') for k in K}
                d5 = []
                for i in range(len(S5[0])):
                    kb = max(K, key=lambda k: np.delete(S5[k], i).mean()); d5.append(S5[kb][i] - S5[0][i])
                SR = {k: board(k, sel, 'r3', 'RB') for k in K}
                dr = []
                for i in range(len(SR[0])):
                    kb = max(K, key=lambda k: np.delete(SR[k], i).mean()); dr.append(SR[kb][i] - SR[0][i])
                print(f'RB age>={A} rel>={R} g>={G}{"":<6}{len(g):>4}  {" / ".join(rs):<38} '
                      f'{np.mean(d):+.4f} ({sum(v > 1e-9 for v in d)}/8) k{sorted(set(picks))}   {np.mean(d5):+.4f} ({sum(v > 1e-9 for v in d5)}/{len(d5)})'
                      f'   {np.mean(dr):+.4f} ({sum(v > 1e-9 for v in dr)}/{len(dr)})')
    sel = lambda x: x['pos'] == 'RB' and (x['age'] or 0) >= 28 and x['g1'] >= 8 and x['rel1'] >= 1.0
    print('\nflagged (age 28+, productive): FAIR overall rank -> realized 3yr rank')
    for x in sorted([x for x in recs if sel(x)], key=lambda x: (x['Y'], FR[id(x)])):
        print(f'   {x["Y"]} {x["key"][0]:<22} age {x["age"]}  prior rel {x["rel1"]:.2f}  FAIR #{FR[id(x)]:<4} -> realized #{TR[("r3", id(x))]}')


if __name__ == '__main__':
    main()
