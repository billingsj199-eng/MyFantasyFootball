#!/usr/bin/env python3
"""
backtest_value_score.py — what truly changes long-term dynasty value, what the
market over / under-reacts to, and a VALUE SCORE fit on real outcomes.

Jack 2026-10-09: "figure out how much each of those actually truly changes long
term value vs short term value / overreactions and create our value score based
on the data ... obviously being a good or bad player will be the most impactful
along with long term upside".

Pool: FFC dynasty ADP players, preseason Y = 2016-2023 (needs Y-1 ADP for the
market's reaction). Truth: realized VOR, T3 = Y..Y+2, LT = T3 + 1.5 x (Y+3, Y+4)
(the same window + youth credit Dynasty SIM uses; LT on Y <= 2021).

Drivers (all known preseason Y):
  quality    log Dynasty SIM rank (comps on production, age, games; rookies by slot)
  age x pos, rookie, rookie draft slot (log pick)
  breakout   last season's PPG minus his 2-3 seasons before, / position replacement PPG
  injured    played <= 9 games last season
  moved      team in Y differs from Y-1
  new deal   OTC contract signed in Y-1 / Y: cap% (big >= 6%), same vs new team
  walk year  last year of his deal is Y

1. MARKET REACTION vs JUSTIFIED (vets with a Y-1 market rank):
     reaction  : log market rank Y  ~ log market rank Y-1 + driver + controls
     justified : log truth rank     ~ log market rank Y-1 + driver + controls
   (controls: quality, age x pos). reaction / justified > 1 = overreaction,
   < 1 = underreaction, opposite signs = the market moves the wrong way.
   Negative = better (log rank).
2. MISPRICING given today's market: log truth rank ~ log market rank Y + driver
   (+ quality, age x pos): a nonzero driver coefficient = mispriced at the price.
3. VALUE SCORE: LOYO OLS of log truth rank (LT) on market + quality + drivers;
   per-year Spearman vs T3 / LT against KTC-style market, Dynasty SIM, fair value.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS, _norm_name, JMKernel, JM_COND, load_jm, jm_cond_weight, jm_blend  # noqa: E402
from backtest_dynasty_inseason import ffc_adp  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

LAST = 2025
YEARS = list(range(2016, 2024))
LL = (120, 5.0)
YW = 1.5
POS = ('QB', 'RB', 'WR', 'TE')
OUT_COEF = os.path.join(HERE, '_dyn_cache', 'value_score_coef.json')


def load_contracts():
    import pandas as pd
    d = pd.read_parquet(r'E:\MyFantasyFootball\pbp_cache\historical_contracts.parquet')
    d = d[d.position.isin(POS)]
    out = defaultdict(list)
    for r in d.itertuples():
        if r.year_signed and r.years == r.years and r.years:
            out[(_norm_name(r.player or ''), r.position)].append(
                (int(r.year_signed), int(r.years), float(r.apy_cap_pct) if r.apy_cap_pct == r.apy_cap_pct else 0.0, str(r.team or '')))
    return out


def build(jm_cond=False):
    """jm_cond: apply the shipped conditional JM credit (years 1-3, time-honest
    kernel — dyn_common.JM_COND) to the sim, as build_dynasty_sim.py --jm-cond."""
    w = World(LAST)
    rows = w.rows(FORMATS['1qb'], YEARS[-1])
    comps = Comps(rows, LAST, {'QB': 6.0})
    jm = load_jm() if jm_cond else {}
    kern = JMKernel(w, jm) if jm_cond else None
    idx = {(r['key'], r['Y']): r for r in rows}
    con = load_contracts()
    adp = {y: {(n, p): a for n, p, a in ffc_adp(y)} for y in range(2015, 2025)}

    def mranks(y):
        pl = [k for k in adp.get(y, {}) if (k, y) in idx]
        return {k: i + 1 for i, k in enumerate(sorted(pl, key=lambda k: adp[y][k]))}
    recs = []
    for Y in YEARS:
        pool = [idx[(k, Y)] for k in adp[Y] if (k, Y) in idx]
        mr, mp, mn = mranks(Y), mranks(Y - 1), mranks(Y + 1)
        for r in pool:
            if r['rookie']:
                ev = comps.ev(r['pos'], True, Comps.feat_rookie(r['pick'], r['age0']), Y, exclude_key=r['key'], local_linear=LL)
            else:
                ev = comps.ev(r['pos'], False, comps.feat_v(r['pos'], r['age0'], r['rel'], r['gp1']), Y, exclude_key=r['key'], local_linear=LL)
            if kern and r['key'] in jm:
                cy, a = jm_cond_weight(w, r['key'], Y, JM_COND)
                if a > 0:
                    ev = jm_blend(ev, kern.ev(r['pos'], jm[r['key']], Y, range(cy, cy + 5), exclude_key=r['key']), a)
            r['_sim'] = sum(ev[:3]) + YW * sum(ev[3:])
        srank = {r['key']: i + 1 for i, r in enumerate(sorted(pool, key=lambda r: -r['_sim']))}
        for r in pool:
            k, P = r['key'], w.players[r['key']]
            by = P['by']
            s1, s2, s3 = by.get(Y - 1), by.get(Y - 2), by.get(Y - 3)
            rp = max(w._repl.get((Y - 1, k[1]), 100) / 17.0, 1.0)
            ppg = lambda s: (s.get('fpts') or 0) / s['gp'] if s and (s.get('gp') or 0) >= 4 else None   # half-PPR fpts in the DB; fine for a jump
            p1, p2, p3 = ppg(s1), ppg(s2), ppg(s3)
            prior = [p for p in (p2, p3) if p is not None]
            breakout = (p1 - sum(prior) / len(prior)) / rp if (p1 is not None and prior) else 0.0
            injured = 1.0 if (s1 and (s1.get('gp') or 0) <= 9 and not r['rookie']) else 0.0
            t_now = (by.get(Y) or {}).get('tm') or ''
            t_prev = (s1 or {}).get('tm') or ''
            moved = 1.0 if (t_now and t_prev and t_now != t_prev and not r['rookie']) else 0.0
            deals = [c for c in con.get(k, []) if c[0] in (Y - 1, Y)]
            newdeal = max(deals, key=lambda c: c[2]) if deals else None
            dr = P['draft']
            cover = [c for c in con.get(k, []) if c[0] <= Y <= c[0] + c[1] - 1]
            cur = max(cover, key=lambda c: c[0]) if cover else None
            walk = 1.0 if (cur and cur[0] + cur[1] - 1 == Y and not (dr and cur[0] == dr[0])) else 0.0
            vor = r['vor']
            t3 = sum(v or 0 for v in vor[:3])
            lt = t3 + YW * sum(v or 0 for v in vor[3:5]) if Y + 4 <= LAST else None
            recs.append({
                'Y': Y, 'key': k, 'pos': k[1], 'age': r['age0'], 'rookie': int(r['rookie']),
                'pick': (dr[1] if dr and r['rookie'] else None),
                'm0': mr[k], 'mp': mp.get(k), 'm1': min(mn.get(k, 250), 250), 's0': srank[k],
                'breakout': breakout, 'injured': injured, 'moved': moved,
                'deal_big': 1.0 if (newdeal and newdeal[2] >= 0.06 and not r['rookie']) else 0.0,
                'deal_small': 1.0 if (newdeal and newdeal[2] < 0.06 and not r['rookie']) else 0.0,
                'deal_newteam': 1.0 if (newdeal and moved) else 0.0,
                'walk': walk, 't3': t3, 'lt': lt})
    # truth ranks within year
    for Y in YEARS:
        ys = [x for x in recs if x['Y'] == Y]
        for key in ('t3', 'lt'):
            vals = [x for x in ys if x[key] is not None]
            for i, x in enumerate(sorted(vals, key=lambda x: -x[key])):
                x['r_' + key] = i + 1
    return recs


DRIVERS = ['breakout', 'injured', 'moved', 'deal_big', 'deal_small', 'deal_newteam', 'walk']


def ctrl(x):
    a = x['age'] - 25.0
    return [math.log(x['s0'])] + [1.0 if x['pos'] == p else 0.0 for p in POS[1:]] + [a * (1.0 if x['pos'] == p else 0.0) for p in POS]


def ols(X, y):
    X = np.array(X); y = np.array(y)
    lam = 1e-3 * np.eye(X.shape[1]); lam[0, 0] = 0
    b = np.linalg.solve(X.T @ X + lam, X.T @ y)
    res = y - X @ b
    s2 = (res @ res) / max(1, len(y) - X.shape[1])
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X + lam)))
    return b, se


def main():
    recs = build()
    print(f'{len(recs)} player-years, preseason {YEARS[0]}-{YEARS[-1]}')
    print('driver frequency: ' + ', '.join(f'{d} {sum(x[d] != 0 for x in recs)}' for d in DRIVERS))

    # ---------- 1. reaction vs justified
    vets = [x for x in recs if x['mp'] and not x['rookie'] and 'r_t3' in x]
    print(f'\n=== 1. Market reaction vs what the outcome justified (vets with a prior-year market rank, n={len(vets)}) ===')
    print('   log-rank effects (negative = better); controls: last year\'s market rank, sim quality, position x age')
    print(f'{"driver":<14}{"market moved":>14}{"(t)":>7}{"justified 3yr":>15}{"(t)":>7}{"verdict":>34}')
    for dname in DRIVERS:
        Xm = [[1.0, math.log(x['mp']), x[dname]] + ctrl(x) for x in vets]
        bm, sm = ols(Xm, [math.log(x['m0']) for x in vets])
        bt, st = ols(Xm, [math.log(x['r_t3']) for x in vets])
        rm, rt = bm[2], bt[2]
        if abs(rt) < 2 * st[2] and abs(rm) < 2 * sm[2]:
            verdict = 'neither moves much'
        elif abs(rt) < 2 * st[2]:
            verdict = 'OVERREACTION (outcome flat)'
        elif rm * rt < 0:
            verdict = 'market moves the WRONG way'
        elif abs(rm) > abs(rt):
            verdict = f'overreaction ({abs(rm) / abs(rt):.1f}x)'
        else:
            verdict = f'UNDERREACTION ({abs(rm) / abs(rt):.1f}x)'
        print(f'{dname:<14}{rm:>+14.3f}{rm / sm[2]:>7.1f}{rt:>+15.3f}{rt / st[2]:>7.1f}{verdict:>34}')

    # ---------- 2. mispricing given today's price
    print(f'\n=== 2. Mispriced at today\'s price? log truth rank ~ log market rank now + driver + quality + age x pos (all, n={len(recs)}) ===')
    print(f'{"driver":<14}{"3yr coef":>10}{"(t)":>7}{"5yr+youth":>11}{"(t)":>7}   (negative = better than the price says)')
    base3 = [x for x in recs if 'r_t3' in x]
    base5 = [x for x in recs if 'r_lt' in x]
    Xa = lambda x: [1.0, math.log(x['m0'])] + ctrl(x) + [x['rookie'], math.log(x['pick']) if x['pick'] else 0.0] + [x[d] for d in DRIVERS]
    b3, s3 = ols([Xa(x) for x in base3], [math.log(x['r_t3']) for x in base3])
    b5, s5 = ols([Xa(x) for x in base5], [math.log(x['r_lt']) for x in base5])
    names = ['const', 'log market rank', 'log sim rank (quality)', 'RB', 'WR', 'TE', 'age x QB', 'age x RB', 'age x WR', 'age x TE', 'rookie', 'log rookie pick'] + DRIVERS
    for i, nm in enumerate(names):
        if i == 0:
            continue
        print(f'{nm:<24}{b3[i]:>+10.3f}{b3[i] / s3[i]:>7.1f}{b5[i]:>+11.3f}{b5[i] / s5[i]:>7.1f}')

    # ---------- 3. VALUE SCORE (LOYO)
    print('\n=== 3. VALUE SCORE — LOYO OLS on long-term truth (5yr+youth), scored per year (Spearman) ===')
    m3 = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))
    c = m3['coef']

    def fairz(x):
        a = x['age'] - 25.0; P = x['pos']
        z = c[0] + c[1] * math.log(x['m0']) + c[2] * math.log(x['s0']) + c[3] * x['rookie'] + (c[4] if P == 'RB' else 0) + (c[5] if P == 'WR' else 0) \
            + (c[6] if P == 'TE' else 0) + a * (c[7] if P == 'QB' else c[8] if P == 'RB' else c[9] if P == 'WR' else c[10])
        return 0.7 * z + 0.3 * math.log(x['s0'])
    specs = {'quality + upside only': lambda x: [1.0, math.log(x['s0'])] + ctrl(x)[1:] + [x['rookie'], math.log(x['pick']) if x['pick'] else 0.0],
             'market + quality': lambda x: [1.0, math.log(x['m0'])] + ctrl(x) + [x['rookie'], math.log(x['pick']) if x['pick'] else 0.0],
             'market + quality + drivers': Xa}
    preds = {}
    for nm, f in specs.items():
        p = {}
        for Y in YEARS:
            tr = [x for x in base5 if x['Y'] != Y] if any(x['Y'] == Y for x in base5) else base5
            tr3 = [x for x in base3 if x['Y'] != Y]
            # fit on the long-term truth where it exists (Y <= 2021), else the 3yr truth
            use = tr if len(tr) > 200 else tr3
            key = 'r_lt' if use is tr else 'r_t3'
            b, _ = ols([f(x) for x in use], [math.log(x[key]) for x in use])
            for x in recs:
                if x['Y'] == Y:
                    p[id(x)] = float(np.array(f(x)) @ b)
        preds[nm] = p

    def py(order, truth, yrs):
        num = den = 0.0
        for Y in yrs:
            xs = [x for x in recs if x['Y'] == Y and truth in x]
            s = spearman([order(x) for x in xs], [-x[truth] for x in xs])
            if s is not None:
                num += s * len(xs); den += len(xs)
        return num / den
    y5 = [y for y in YEARS if y + 4 <= LAST]
    rows = [('KTC-style market now', lambda x: -x['m0']), ('Dynasty SIM', lambda x: -x['s0']),
            ('SIM x market 50/50', lambda x: -(math.log(x['m0']) + math.log(x['s0']))), ('FAIR value (shipped)', lambda x: -fairz(x))]
    rows += [(f'VALUE SCORE: {nm}', (lambda x, nm=nm: -preds[nm][id(x)])) for nm in specs]
    print(f'{"order":<44}{"3yr":>7}{"5yr+youth":>11}{"top-50 3yr":>12}')
    for nm, f in rows:
        t50 = 0.0; n50 = 0
        for Y in YEARS:
            xs = [x for x in recs if x['Y'] == Y and 'r_t3' in x and x['m0'] <= 50]
            s = spearman([f(x) for x in xs], [-x['r_t3'] for x in xs])
            if s is not None:
                t50 += s * len(xs); n50 += len(xs)
        print(f'{nm:<44}{py(f, "r_t3", YEARS):>7.3f}{py(f, "r_lt", y5):>11.3f}{t50 / n50:>12.3f}')
    bF, _ = ols([Xa(x) for x in base5], [math.log(x['r_lt']) for x in base5])
    json.dump({'names': names, 'coef': [round(float(v), 5) for v in bF], 'years': [YEARS[0], YEARS[-1]], 'truth': 'log rank of realized 5yr+youth VOR'},
              open(OUT_COEF, 'w'), indent=1)


if __name__ == '__main__':
    main()
