#!/usr/bin/env python3
"""
backtest_dynasty_market_moves.py — does Dynasty SIM see market moves coming?

Jack 2026-10-09: "I don't think KTC is super accurate but is there anything we
can do to monitor how the value changes by players that can give us an edge."

Market = FFC dynasty startup ADP (annual, 2015-2025). For each start year Y:
  gap(Y)      = log(SIM rank / market rank) within the pool (negative = the
                sim likes him MORE than the market)
  move(Y+1)   = log(market rank Y+1 / market rank Y) (negative = market rose;
                players who fall out of the next year's ADP get rank 250)
  momentum(Y) = log(market rank Y / market rank Y-1) (last year's move)
Questions:
  1. corr(gap, next move) > 0  -> the market drifts toward the sim
  2. does it survive controlling for momentum and age (partial / OLS)?
  3. buy/sell buckets: average next move + realized 3yr VOR for the players
     the sim likes most / least vs the market
SIM = current prototype (local-linear comps, QB age 6), preseason, 1QB PPR.
"""
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
YEARS = list(range(2015, 2024))     # Y; needs ADP at Y+1 (<= 2024) and T3 truth
LL = (120, 5.0)
YW = 1.5
DROP_RANK = 250


def main():
    w = World(LAST_DATA)
    rows = w.rows(FORMATS['1qb'], YEARS[-1])
    comps = Comps(rows, LAST_DATA, {'QB': 6.0})
    idx = {(r['key'], r['Y']): r for r in rows}
    adp = {y: {(n, p): a for n, p, a in ffc_adp(y)} for y in range(2014, 2026)}
    mrank = {}
    for y, m in adp.items():
        for i, (k, a) in enumerate(sorted(m.items(), key=lambda kv: kv[1])):
            mrank[(k, y)] = i + 1

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
        srt = sorted(pool, key=lambda r: -r['_sim'])
        n = len(pool)
        for i, r in enumerate(srt):
            k = r['key']
            m0 = mrank[(k, Y)]
            m1 = mrank.get((k, Y + 1), DROP_RANK)
            mp = mrank.get((k, Y - 1))
            recs.append({'Y': Y, 'name': k[0], 'pos': k[1], 'age': r['age0'], 'rookie': r['rookie'],
                         'sim_rk': i + 1, 'm0': m0, 'm1': m1, 'n': n,
                         'gap': math.log((i + 1) / m0), 'move': math.log(m1 / m0),
                         'mom': math.log(m0 / mp) if mp else None,
                         't3': sum(v or 0 for v in r['vor'][:3])})
    print(f'{len(recs)} player-years, start {YEARS[0]}-{YEARS[-1]}')

    def per_year(f, g, sub=None):
        num = den = 0.0
        for Y in YEARS:
            lst = [x for x in recs if x['Y'] == Y and (sub is None or sub(x))]
            if len(lst) < 15:
                continue
            s = spearman([f(x) for x in lst], [g(x) for x in lst])
            if s is not None:
                num += s * len(lst); den += len(lst)
        return num / den if den else float('nan')

    print('\n=== 1. Does the market drift toward the sim? (per-year Spearman, n-weighted) ===')
    print(f'corr(gap, next-year market move)            {per_year(lambda x: x["gap"], lambda x: x["move"]):+.3f}'
          '   (+ = market moves toward the sim)')
    print(f'corr(momentum, next-year market move)       {per_year(lambda x: x["mom"], lambda x: x["move"], lambda x: x["mom"] is not None):+.3f}'
          '   (+ = risers keep rising; - = they revert)')
    for pos in ('QB', 'RB', 'WR', 'TE'):
        print(f'   {pos}: gap->move {per_year(lambda x: x["gap"], lambda x: x["move"], lambda x, p=pos: x["pos"] == p):+.3f}')
    print(f'   rookies: gap->move {per_year(lambda x: x["gap"], lambda x: x["move"], lambda x: x["rookie"]):+.3f}   '
          f'vets: {per_year(lambda x: x["gap"], lambda x: x["move"], lambda x: not x["rookie"]):+.3f}')

    print('\n=== 2. Controlling for momentum, age, market rank (OLS on next move, vets with a prior-year ADP) ===')
    sub = [x for x in recs if x['mom'] is not None]
    X = np.array([[1.0, x['gap'], x['mom'], x['age'], math.log(x['m0'])] for x in sub])
    yv = np.array([x['move'] for x in sub])
    beta, *_ = np.linalg.lstsq(X, yv, rcond=None)
    res = yv - X @ beta
    s2 = (res @ res) / (len(yv) - X.shape[1])
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    for nm, b, e in zip(('const', 'gap', 'momentum', 'age', 'log mkt rank'), beta, se):
        print(f'   {nm:<14}{b:+.4f}  (t {b / e:+.1f})')

    print('\n=== 3. Buy / sell buckets by gap (within-year quintiles) ===')
    print(f'{"bucket":<26}{"n":>5}{"avg mkt rank":>13}{"next rank":>11}{"mkt moved":>11}{"real T3 VOR":>12}{"T3 vs mkt-peers":>16}')
    buckets = {q: [] for q in range(5)}
    for Y in YEARS:
        lst = sorted([x for x in recs if x['Y'] == Y], key=lambda x: x['gap'])
        for i, x in enumerate(lst):
            buckets[min(4, i * 5 // len(lst))].append(x)
    # mkt-peers: expected T3 for a player at that market rank (same-year rank neighbours)
    for x in recs:
        peers = [z['t3'] for z in recs if z['Y'] == x['Y'] and abs(z['m0'] - x['m0']) <= 6 and z is not x]
        x['peer'] = sum(peers) / len(peers) if peers else x['t3']
    labels = ['Q1 sim likes MOST (buy)', 'Q2', 'Q3', 'Q4', 'Q5 sim likes LEAST (sell)']
    for q in range(5):
        b = buckets[q]
        print(f'{labels[q]:<26}{len(b):>5}{np.mean([x["m0"] for x in b]):>13.0f}{np.mean([x["m1"] for x in b]):>11.0f}'
              f'{np.mean([math.exp(x["move"]) - 1 for x in b]) * 100:>10.0f}%{np.mean([x["t3"] for x in b]):>12.0f}'
              f'{np.mean([x["t3"] - x["peer"] for x in b]):>+16.0f}')

    print('\n=== 4. Biggest buy calls that hit / missed (Q1, top-100 market) ===')
    q1 = sorted([x for x in buckets[0] if x['m0'] <= 100], key=lambda x: x['gap'])
    for x in q1[:12]:
        print(f"   {x['Y']} {x['name']:<22}{x['pos']} age{x['age']} mkt #{x['m0']:<4} sim #{x['sim_rk']:<4} -> next yr mkt #{x['m1']:<4} T3 VOR {x['t3']:.0f}")


if __name__ == '__main__':
    main()
