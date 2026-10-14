#!/usr/bin/env python3
"""
backtest_fair_sf.py — does superflex want its own FAIR weights? (Jack 2026-10-09:
"test the superflex fair tune next")

FAIR was tuned on 1QB (FFC dynasty ADP 2016-23) and is applied to SF as-is.
There is no FFC SF history, so the market here is KTC's own daily SF value
(_dyn_cache/ktc_alltime.json, today's top ~150, 2021-26) at Aug 1 of each year.
SURVIVORSHIP: only players KTC still lists today — everyone looks better than
they were; read results RELATIVE (same pool for every order), and against the
1QB control run on the same pool (--fmt 1qb).

Per year Y (2021-25): pool = KTC players with a value at Aug 1 Y and a Dynasty
SIM value (comps under the format's lineup — SF = QB24 replacement — QB age
scale 6, local-linear, shipped conditional JM; time-honest). Ranks within pool.
Truths: next-year market = KTC rank at Aug 1 Y+1 (gone = 250); realized VOR
over Y..Y+2 under the same format (Y <= 2023).
Orders: market, sim, FAIR shipped (shipped M3 coef, weights 0.5/0.3/0.5), and a
weight grid; M3 also refit on this pool leave-one-year-out. Winner checked
season by season against the shipped weights.
"""
import argparse
import datetime as dt
import itertools
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS, _norm_name, JMKernel, JM_COND, load_jm, jm_cond_weight, jm_blend  # noqa: E402
from backtest_js_model import spearman  # noqa: E402
import research_injury_drift as RD  # noqa: E402

LL = (120, 5.0)
YW = 1.5
LAST = 2025
YEARS = [2021, 2022, 2023, 2024, 2025]
SHIP = (0.5, 0.3, 0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fmt', default='sf', choices=('sf', '1qb'))
    a = ap.parse_args()
    fk = 'superflex' if a.fmt == 'sf' else 'oneQB'
    K = json.load(open(os.path.join(HERE, '_dyn_cache', 'ktc_alltime.json'), encoding='utf-8'))['players']
    S = {}
    for n, rec in K.items():
        o = rec.get(fk) or {}
        pts = sorted((dt.date(2000 + int(d[:2]), int(d[2:4]), int(d[4:6])), v) for d, v in zip(o.get('d', []), o.get('v', [])) if v)
        if pts:
            S[(_norm_name(n), rec['pos'])] = ([p[0] for p in pts], [p[1] for p in pts])
    w = World(LAST)
    rows = w.rows(FORMATS[a.fmt], LAST)
    comps = Comps(rows, LAST, {'QB': 6.0})
    idx = {(r['key'], r['Y']): r for r in rows}
    jm = load_jm(); kern = JMKernel(w, jm)
    coef = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = []
    mk = {}
    for Y in YEARS + [2026]:
        day = dt.date(Y, 8, 1)
        vals = {k: RD.val_at(s, day) for k, s in S.items()}
        mk[Y] = {k: v for k, v in vals.items() if v}
    for Y in YEARS:
        pool = []
        for k, v in mk[Y].items():
            r = idx.get((k, Y))
            if not r:
                continue
            if r['rookie']:
                ev = comps.ev(k[1], True, Comps.feat_rookie(r['pick'], r['age0']), Y, exclude_key=k, local_linear=LL)
            else:
                ev = comps.ev(k[1], False, comps.feat_v(k[1], r['age0'], r['rel'], r['gp1']), Y, exclude_key=k, local_linear=LL)
            if k in jm:
                cy, aj = jm_cond_weight(w, k, Y, JM_COND)
                if aj > 0:
                    ev = jm_blend(ev, kern.ev(k[1], jm[k], Y, range(cy, cy + 5), exclude_key=k), aj)
            pool.append({'key': k, 'pos': k[1], 'Y': Y, 'age': r['age0'], 'rookie': int(r['rookie']), 'kv': v,
                         'sim': sum(ev[:3]) + YW * sum(ev[3:]), 't3': sum((w.vor(k, Y + j) or 0) for j in range(3)) if Y + 2 <= LAST else None})
        for i, x in enumerate(sorted(pool, key=lambda x: -x['kv'])):
            x['m0'] = i + 1
        for i, x in enumerate(sorted(pool, key=lambda x: -x['sim'])):
            x['s0'] = i + 1
        nxt = sorted(mk.get(Y + 1, {}).items(), key=lambda kv: -kv[1])
        nr = {k: i + 1 for i, (k, _) in enumerate(nxt)}
        for x in pool:
            x['m1'] = min(nr.get(x['key'], 250), 250)
        t3s = [x for x in pool if x['t3'] is not None]
        for i, x in enumerate(sorted(t3s, key=lambda x: -x['t3'])):
            x['r_t3'] = i + 1
        recs += pool
    print(f'{a.fmt.upper()} pool: ' + ', '.join(f'{Y} {sum(1 for x in recs if x["Y"] == Y)}' for Y in YEARS)
          + f' | QBs {sum(1 for x in recs if x["pos"] == "QB")}')

    def feats(x):
        g = x['age'] - 25.0; P = x['pos']
        return [1.0, math.log(x['m0']), math.log(x['s0']), x['rookie'], P == 'RB', P == 'WR', P == 'TE',
                g * (P == 'QB'), g * (P == 'RB'), g * (P == 'WR'), g * (P == 'TE')]
    for x in recs:
        x['m3s'] = float(np.dot(coef, feats(x)))
    X = np.array([feats(x) for x in recs], float); yv = np.array([math.log(x['m1']) for x in recs]); yrs = np.array([x['Y'] for x in recs])
    for Y in YEARS:
        tr = yrs != Y
        b = np.linalg.lstsq(X[tr], yv[tr], rcond=None)[0]
        for i in np.where(~tr)[0]:
            recs[i]['m3r'] = float(X[i] @ b)

    def score(f, yrs_=YEARS):
        out = {}
        for nm, truth, ys in (('next mkt', lambda x: -x['m1'], [y for y in yrs_ if y <= 2025]), ('3yr', lambda x: -x['r_t3'], [y for y in yrs_ if y <= 2023]),
                              ('QB 3yr', None, [y for y in yrs_ if y <= 2023])):
            num = den = 0.0
            for Y in ys:
                xs = [x for x in recs if x['Y'] == Y and (nm == 'next mkt' or x.get('r_t3'))]
                if nm == 'QB 3yr':
                    xs = [x for x in xs if x['pos'] == 'QB']
                    s = spearman([f(x) for x in xs], [-x['r_t3'] for x in xs]) if len(xs) >= 8 else None
                else:
                    s = spearman([f(x) for x in xs], [truth(x) for x in xs]) if len(xs) >= 10 else None
                if s is not None:
                    num += s * len(xs); den += len(xs)
            out[nm] = num / den if den else float('nan')
        v = [out['next mkt'], out['3yr']]
        out['avg'] = sum(v) / 2
        return out

    def order(wM, wS, wK, m='m3s'):
        return lambda x: -(wM * x[m] + wS * math.log(x['s0']) + wK * math.log(x['m0']))

    def line(nm, s):
        print(f'{nm:<44}{s["next mkt"]:>9.3f}{s["3yr"]:>7.3f}{s["QB 3yr"]:>8.3f}{s["avg"]:>7.3f}')
    print(f'{"order":<44}{"next mkt":>9}{"3yr":>7}{"QB 3yr":>8}{"avg":>7}')
    line('market (KTC)', score(lambda x: -x['m0']))
    line('sim', score(lambda x: -x['s0']))
    line('SHIPPED FAIR (0.5/0.3/0.5, shipped M3)', score(order(*SHIP)))
    line('shipped weights, M3 refit on this pool (LOYO)', score(order(*SHIP, m='m3r')))
    grid = []
    for wM, wS, wK in itertools.product((0.0, 0.3, 0.5, 0.7), (0.1, 0.2, 0.3, 0.4, 0.5, 0.6), (0.0, 0.25, 0.5, 0.75)):
        if wM + wK == 0:
            continue
        grid.append(((wM, wS, wK), score(order(wM, wS, wK))))
    grid.sort(key=lambda g: -g[1]['avg'])
    print('--- best 6 weights (shipped M3) ---')
    for (wM, wS, wK), s in grid[:6]:
        line(f'M3 {wM} sim {wS} mkt {wK}', s)
    best = grid[0][0]
    wins = 0
    for Y in YEARS:
        b_, s_ = score(order(*best), [Y])['avg'], score(order(*SHIP), [Y])['avg']
        wins += b_ > s_ + 1e-9
        print(f'   {Y}: best {b_:.3f} vs shipped {s_:.3f}')
    print(f'best {best} beats shipped in {wins} of {len(YEARS)} seasons')
    # leave-one-year-out weight choice
    d = []
    for Y in YEARS:
        tr = [y for y in YEARS if y != Y]
        bw = max(grid, key=lambda g: score(order(*g[0]), tr)['avg'])[0]
        d.append(score(order(*bw), [Y])['avg'] - score(order(*SHIP), [Y])['avg'])
    print(f'LOYO-chosen weights vs shipped: {np.mean(d):+.4f} avg per season, wins {sum(x > 1e-9 for x in d)}/{len(d)}')


if __name__ == '__main__':
    main()
