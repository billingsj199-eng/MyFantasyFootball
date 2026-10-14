#!/usr/bin/env python3
"""
backtest_rb_rec_groups.py — does the RB receiving tilt hold for backs like Corum (young,
very low receiving) and Henry (old, ~average receiving)? (Jack 2026-10-10: "test rb
receiving signals for corum and henry")

Shipped tilt (build_dynasty_sim.py meta.rbRec, app.js _fairRbRec): FAIR score += -0.25 x z,
z = prior-season PFF yards after catch per route run among RBs with 75+ carries.
Pool: FFC dynasty pool, Y = 2020-23 (PFF 2019-22 = prior season), shipped JM sim + FAIR.
Residual = log(realized rank / predicted rank) within year (+ = finished WORSE than ranked),
for FAIR without the tilt and with it, by group: very low receivers (z <= -1), low
(-1 < z <= 0), high (z > 0); age 28+; young (<= 25) very low. Then LOYO on RB ranks
(within RBs) and the whole pool: linear (shipped) vs z floored at -1 (no extra dock past
one SD) vs no tilt. Truth: 3yr VOR and 5yr + youth.
"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import _norm_name  # noqa: E402
from backtest_value_score import build  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

PFF = r'E:\MyFantasyFootball\pbp_cache\pff'
YRS = [2020, 2021, 2022, 2023]
K = -0.25


def yac_z(season):
    ru = pd.read_csv(os.path.join(PFF, f'pff_rushing_{season}.csv'))
    ru = ru[ru.position.isin(['HB', 'RB', 'FB']) & (ru.attempts >= 75)]
    q = {_norm_name(p) for p in ru.player}
    rc = pd.read_csv(os.path.join(PFF, f'pff_receiving_{season}.csv'))
    rc = rc[rc.position.isin(['HB', 'RB', 'FB']) & (rc.routes > 0)]
    v = {_norm_name(r['player']): float(r['yards_after_catch_per_reception'] or 0) * float(r['receptions'] or 0) / float(r['routes'])
         for r in rc.to_dict('records')}
    vals = [x for k, x in v.items() if k in q and x == x]
    mu, sd = np.mean(vals), np.std(vals) or 1
    return {k: (x - mu) / sd for k, x in v.items() if k in q and x == x}


def main():
    Z = {Y: yac_z(Y - 1) for Y in YRS}
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = [x for x in build(True) if x['Y'] in YRS]
    m3_ship(recs, c)
    for x in recs:
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
        x['z'] = Z[x['Y']].get(x['key'][0]) if (x['pos'] == 'RB' and not x['rookie']) else None
    rbs = [x for x in recs if x['z'] is not None]
    print(f'pool {len(recs)}; RBs with a prior-season YAC/route z: {len(rbs)}')

    def score(x, mode):
        if x['z'] is None or mode == 'off':
            return x['fz']
        z = max(x['z'], -1.0) if mode == 'floor' else x['z']
        return x['fz'] + K * z

    def ranks(mode, tk, sub=None):
        out = {}
        for Y in YRS:
            ys = [x for x in recs if x['Y'] == Y and (sub is None or x['pos'] == sub)]
            if tk == 'r_lt' and any(x.get('r_lt') is None for x in ys):
                continue
            pr = {id(x): i + 1 for i, x in enumerate(sorted(ys, key=lambda x: score(x, mode)))}
            tr = {id(x): i + 1 for i, x in enumerate(sorted(ys, key=lambda x: x[tk]))}
            for x in ys:
                out[id(x)] = (pr[id(x)], tr[id(x)])
        return out

    groups = [('very low rec (z <= -1)', lambda x: x['z'] <= -1),
              ('low rec (-1 < z <= 0)', lambda x: -1 < x['z'] <= 0),
              ('good rec (z > 0)', lambda x: x['z'] > 0),
              ('age 28+', lambda x: (x['age'] or 0) >= 28),
              ('age <= 25 AND z <= -1', lambda x: (x['age'] or 99) <= 25 and x['z'] <= -1)]
    for tk, lbl in (('r_t3', '3yr'), ('r_lt', '5yr+youth')):
        print(f'\n=== residual log(realized / predicted RB rank), {lbl}  (+ = finished worse than ranked) ===')
        R = {m: ranks(m, tk, 'RB') for m in ('off', 'on', 'floor')}
        for name, sel in groups:
            g = [x for x in rbs if sel(x) and id(x) in R['off']]
            if not g:
                continue
            cells = [f'{m}: {np.mean([math.log(R[m][id(x)][1] / R[m][id(x)][0]) for x in g]):+.2f}' for m in ('off', 'on', 'floor')]
            print(f'  {name:<26} n {len(g):<4}' + '   '.join(cells))
    print('\n=== per-year Spearman (held-out style: tilt fixed at shipped k) — RB-only and whole pool ===')
    for tk, lbl in (('r_t3', '3yr'), ('r_lt', '5yr+youth')):
        for sub, sl in (('RB', 'RB-only'), (None, 'whole')):
            res = {}
            for m in ('off', 'on', 'floor'):
                v = []
                for Y in YRS:
                    ys = [x for x in recs if x['Y'] == Y and (sub is None or x['pos'] == sub)]
                    if tk == 'r_lt' and any(x.get('r_lt') is None for x in ys):
                        continue
                    v.append(spearman([-score(x, m) for x in ys], [-x[tk] for x in ys]))
                res[m] = np.array(v)
            w_on = int((res['on'] > res['off'] + 1e-9).sum()); w_fl = int((res['floor'] > res['on'] + 1e-9).sum())
            print(f'  {lbl:<10}{sl:<8} off {res["off"].mean():.4f}  on {res["on"].mean():.4f} ({w_on}/{len(res["on"])} vs off)'
                  f'  floor {res["floor"].mean():.4f} ({w_fl}/{len(res["on"])} vs on)')
    print('\nvery low receivers (z <= -1): FAIR RB rank off / on -> realized 3yr RB rank')
    R0, R1 = ranks('off', 'r_t3', 'RB'), ranks('on', 'r_t3', 'RB')
    for x in sorted([x for x in rbs if x['z'] <= -1], key=lambda x: (x['Y'], R0[id(x)][0])):
        print(f'   {x["Y"]} {x["key"][0]:<24} age {x["age"]}  z {x["z"]:+.2f}  RB#{R0[id(x)][0]:<3} -> RB#{R1[id(x)][0]:<3} realized RB#{R0[id(x)][1]}')


if __name__ == '__main__':
    main()
