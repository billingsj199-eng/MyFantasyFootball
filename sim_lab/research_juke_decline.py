#!/usr/bin/env python3
"""
research_juke_decline.py — is a DECLINE in juke rate an early warning for RBs?
(Jack 2026-10-09: "decline in juke rate?")

Juke rate = PFF avoided tackles per touch (carries + receptions), RBs with 75+
carries; also yards after contact per carry and elusive rating. CHANGE = this
season minus last season (both qualifying).
1  PRODUCTION: next-season PPG change (log ratio vs this season, 8+ games both)
   ~ change in the stat + age + this season's production level (rel) + this
   season's stat level. Coefficient on the CHANGE: does a falling juke rate
   predict a further production drop, beyond age and level? 2019-25 pairs.
   Also: next-season collapse rate (under 4 games or below 70% of a replacement
   starter) for the biggest juke decliners vs everyone.
2  VALUE (FFC dynasty pool 2021-23, needs two prior seasons): beyond-FAIR 3yr
   coefficient of the juke change (bootstrap) — does the market miss it?
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, FORMATS, _norm_name, season_rel  # noqa: E402

CACHE = r'E:\MyFantasyFootball\pbp_cache'


def load():
    S = {}
    for y in range(2019, 2026):
        d = pd.read_csv(os.path.join(CACHE, 'pff', f'pff_rushing_{y}.csv'))
        d = d[d.position.isin(['HB', 'RB', 'FB']) & (d.attempts >= 75)]
        for r in d.to_dict('records'):
            tch = (r['attempts'] or 0) + (r.get('receptions') or 0)
            S[((_norm_name(r['player']), 'RB'), y)] = {'juke': (r.get('avoided_tackles') or 0) / tch if tch else None,
                                                      'yco': r['yco_attempt'], 'elusive': r['elusive_rating']}
    return S


def main():
    S = load()
    w = World(2025)
    w.rows(FORMATS['1qb'], 2025)
    print('=== 1. PRODUCTION: next-season PPG change ~ change in stat + age + production level + stat level (RBs) ===')
    for st in ('juke', 'yco', 'elusive'):
        rows = []
        for (k, y), f in S.items():
            p = S.get((k, y - 1))
            if not p or f.get(st) is None or p.get(st) is None or k not in w.players:
                continue
            g0, r0 = season_rel(w, k, y)
            g1, r1 = season_rel(w, k, y + 1)
            if g0 < 8 or r0 <= 0 or y + 1 > 2025:
                continue
            age = w.age(k, y)
            rows.append({'k': k, 'y': y, 'chg': f[st] - p[st], 'lvl': f[st], 'age': age if age is not None else 26, 'rel': math.log(max(r0, 0.05)),
                         'next': math.log(r1 / r0) if (g1 >= 8 and r1 > 0) else None, 'collapse': 1.0 if (g1 < 4 or r1 < 0.7) else 0.0})
        R = [r for r in rows if r['next'] is not None]
        if len(R) < 40:
            continue
        ch = np.array([r['chg'] for r in R]); cz = (ch - ch.mean()) / (ch.std() or 1)
        lv = np.array([r['lvl'] for r in R]); lz = (lv - lv.mean()) / (lv.std() or 1)
        X = np.column_stack([np.ones(len(R)), cz, lz, [r['age'] for r in R], [r['rel'] for r in R]])
        yv = np.array([r['next'] for r in R])
        b = np.linalg.lstsq(X, yv, rcond=None)[0]
        res = yv - X @ b
        cov = (res @ res) / (len(R) - X.shape[1]) * np.linalg.inv(X.T @ X)
        t = b[1] / math.sqrt(cov[1, 1])
        per = []
        for y in sorted({r['y'] for r in R}):
            ii = [i for i, r in enumerate(R) if r['y'] == y]
            if len(ii) >= 12:
                per.append(np.linalg.lstsq(X[ii], yv[ii], rcond=None)[0][1])
        allc = np.array([r['chg'] for r in rows]); q = np.percentile(allc, 20)
        dec = [r for r in rows if r['chg'] <= q]
        print(f'   {st:<8} n {len(R):>3}  per +1 SD of change: next-season PPG {(math.exp(b[1]) - 1) * 100:+.1f}% (t {t:+.1f}), same sign in {sum((c > 0) == (b[1] > 0) for c in per)}/{len(per)} seasons'
              f'  | level {(math.exp(b[2]) - 1) * 100:+.1f}%  | collapse next season: bottom-fifth decliners {np.mean([r["collapse"] for r in dec]):.0%} (n {len(dec)}) vs all {np.mean([r["collapse"] for r in rows]):.0%}')
    print('   (+ change coef = rising stat -> better next season; i.e. a DECLINE predicts a further drop)')

    print('\n=== 2. VALUE: FFC pool 2021-23 RBs — beyond-FAIR 3yr coef of the juke change ===')
    from backtest_value_score import build
    from backtest_fair_retune_jm import m3_ship
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = [x for x in build(True) if 2021 <= x['Y'] <= 2023]
    m3_ship(recs, c)
    for x in recs:
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
    for Y in (2021, 2022, 2023):
        for i, x in enumerate(sorted([x for x in recs if x['Y'] == Y], key=lambda x: x['fz'])):
            x['f0'] = i + 1
    for st in ('juke', 'yco', 'elusive'):
        g = []
        for x in recs:
            if x['pos'] != 'RB' or x['rookie'] or not x.get('r_t3'):
                continue
            a, b_ = S.get((x['key'], x['Y'] - 1)), S.get((x['key'], x['Y'] - 2))
            if a and b_ and a.get(st) is not None and b_.get(st) is not None:
                g.append((x, a[st] - b_[st]))
        if len(g) < 25:
            print(f'   {st}: n {len(g)} — too few'); continue
        ch = np.array([v for _, v in g]); z = (ch - ch.mean()) / (ch.std() or 1)
        X = np.column_stack([np.ones(len(g)), [math.log(x['f0']) for x, _ in g], z])
        yv = np.array([math.log(x['r_t3']) for x, _ in g])
        bb = np.linalg.lstsq(X, yv, rcond=None)[0][2]
        rng = np.random.default_rng(1); bs = []
        for _ in range(300):
            ii = rng.integers(0, len(g), len(g))
            bs.append(np.linalg.lstsq(X[ii], yv[ii], rcond=None)[0][2])
        lo, hi = np.percentile(bs, [2.5, 97.5])
        print(f'   {st:<8} n {len(g):>3}  beyond FAIR per +1 SD of change {bb:+.3f} [{lo:+.2f},{hi:+.2f}]  (< 0 = rising stat beats FAIR; > 0 = decliners beat FAIR)')


if __name__ == '__main__':
    main()
