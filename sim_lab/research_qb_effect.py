#!/usr/bin/env python3
"""
research_qb_effect.py — does QB quality move RB / WR / TE dynasty value, and is it
priced? (Jack 2026-10-09: "does qb play for rb/wr/te have any effect")

Pool: FFC dynasty ADP pool 2020-23 (1QB PPR), RB / WR / TE, shipped JM sim +
FAIR. His team in season Y = ctx_features.parquet (2019-25). QB quality ENTERING
season Y (known pre-season, two reads):
  qb_mkt   the team's best-ranked QB in that year's FFC dynasty ADP (log rank;
           lower = better QB)
  qb_prod  that QB's production vs replacement entering Y (the sim's 3-season
           base, log rel; rookies = 0)
Tests (z-scored, + = better QB):
  1  raw: does a better QB go with a better realized rank (season Y, 3 years)?
  2  priced: does the MARKET rank them higher for a better QB?
  3  beyond price / sim / FAIR: log realized rank ~ log predicted rank + QB
     quality — a coefficient < 0 = better-QB players beat their price (QB
     under-priced); bootstrap by player. By WR / TE / RB.
  4  leave-one-year-out: does adding QB quality to FAIR / the sim rank better?
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
from dyn_common import World, FORMATS, _norm_name  # noqa: E402
from backtest_value_score import build  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_dynasty_inseason import ffc_adp  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

YRS = [2020, 2021, 2022, 2023]


def main():
    ctx = pd.read_parquet(os.path.join(HERE, 'ctx_features.parquet'))
    ctx['key'] = [(_norm_name(n), p) for n, p in zip(ctx['name'], ctx['pos'])]
    team = {}
    for r in ctx.sort_values(['year', 'wk']).groupby(['name', 'pos', 'year']).head(1).to_dict('records'):
        team[(r['key'], r['year'])] = r['team']       # team at his first game that season
    w = World(2025)
    rows = w.rows(FORMATS['1qb'], 2025)
    rel = {(r['key'], r['Y']): r.get('rel') for r in rows if not r['rookie']}
    # team's best QB by FFC dynasty ADP, per year
    qb_of = {}
    for Y in YRS:
        qbs = [(a, (n, p)) for n, p, a in ffc_adp(Y) if p == 'QB']
        qbs.sort()
        for i, (a, k) in enumerate(qbs):
            t = team.get((k, Y))
            if t and t not in qb_of.get(Y, {}):
                qb_of.setdefault(Y, {})[t] = (k, i + 1)
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = [x for x in build(True) if x['Y'] in YRS and x['pos'] in ('RB', 'WR', 'TE')]
    m3_ship(recs, c)
    keep = []
    for x in recs:
        t = team.get((x['key'], x['Y']))
        q = qb_of.get(x['Y'], {}).get(t) if t else None
        if not q:
            continue
        x['qb'] = q[0][0]
        x['qb_mkt'] = -math.log(q[1])                                   # + = better QB
        x['qb_prod'] = math.log(max(rel.get((q[0], x['Y'])) or 0.6, 0.05))
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
        x['v1'] = w.vor(x['key'], x['Y']) or 0.0
        keep.append(x)
    recs = keep
    for Y in YRS:
        ys = [x for x in recs if x['Y'] == Y]
        for key, f in (('f0', lambda x: x['fz']), ('r1', lambda x: -x['v1']), ('mp', lambda x: x['m0']), ('sp', lambda x: x['s0']), ('r3', lambda x: x['r_t3'])):
            for i, x in enumerate(sorted(ys, key=f)):
                x[key] = i + 1
    print(f'pool: {len(recs)} RB/WR/TE player-seasons 2020-23 with a team QB '
          + ' '.join(f'{p} {sum(1 for x in recs if x["pos"] == p)}' for p in ('WR', 'TE', 'RB')))

    def zs(v):
        v = np.array(v, float); return (v - v.mean()) / (v.std() or 1)

    rng = np.random.default_rng(11)
    for feat, flbl in (('qb_mkt', 'QB market rank (better QB = +)'), ('qb_prod', 'QB production entering the season')):
        print(f'\n=== {flbl} ===')
        print(f'{"group":<8}{"n":>5}{"raw->season":>13}{"raw->3yr":>10}{"priced (mkt)":>14}'
              f'{"beyond MKT":>18}{"beyond SIM":>18}{"beyond FAIR":>18}   (season-Y truth; 95% CI)')
        for grp in (('WR',), ('TE',), ('RB',), ('WR', 'TE'), ('WR', 'TE', 'RB')):
            g = [x for x in recs if x['pos'] in grp]
            if len(g) < 30:
                continue
            q = zs([x[feat] for x in g])
            t1 = np.array([math.log(x['r1']) for x in g]); t3 = np.array([math.log(x['r3']) for x in g])
            raw1 = spearman(list(q), list(-t1)); raw3 = spearman(list(q), list(-t3))
            pri = spearman(list(q), [-math.log(x['mp']) for x in g])
            keys = np.array([hash(x['key']) for x in g]); uk = np.unique(keys); byk = {k: np.where(keys == k)[0] for k in uk}
            cells = []
            for pk in ('mp', 'sp', 'f0'):
                pr = np.array([math.log(x[pk]) for x in g])
                X = np.column_stack([np.ones(len(g)), pr, q])
                b = np.linalg.lstsq(X, t1, rcond=None)[0][2]
                bs = []
                for _ in range(300):
                    ii = np.concatenate([byk[k] for k in rng.choice(uk, len(uk))])
                    bs.append(np.linalg.lstsq(X[ii], t1[ii], rcond=None)[0][2])
                lo, hi = np.percentile(bs, [2.5, 97.5])
                cells.append(f'{b:+.3f} [{lo:+.2f},{hi:+.2f}]{"*" if lo > 0 or hi < 0 else " "}')
            print(f'{"+".join(grp):<8}{len(g):>5}{raw1:>+13.3f}{raw3:>+10.3f}{pri:>+14.3f}' + ''.join(f'{c_:>18}' for c_ in cells))
        print('   raw / priced = Spearman with a better rank; beyond X: coef on QB quality in log realized rank ~ log X rank + QB'
              ' (< 0 = better-QB players BEAT that rank = QB under-priced; * = CI excludes 0)')

    print('\n=== leave-one-year-out: FAIR / SIM + k x QB quality (WR + TE + RB), per-year Spearman vs season-Y and 3-yr rank ===')
    for feat in ('qb_mkt', 'qb_prod'):
        for base, bk in (('FAIR', 'f0'), ('SIM', 'sp')):
            for tk, tl in (('r1', 'season Y'), ('r3', '3 years')):
                d0, d1 = [], []
                for Y in YRS:
                    tr = [x for x in recs if x['Y'] != Y]; te = [x for x in recs if x['Y'] == Y]
                    allq = np.array([x[feat] for x in recs]); mu, sd = allq.mean(), allq.std() or 1
                    X = np.column_stack([np.ones(len(tr)), [math.log(x[bk]) for x in tr], [(x[feat] - mu) / sd for x in tr]])
                    b = np.linalg.lstsq(X, np.array([math.log(x[tk]) for x in tr]), rcond=None)[0]
                    pred = [b[1] * math.log(x[bk]) + b[2] * (x[feat] - mu) / sd for x in te]
                    d0.append(spearman([-math.log(x[bk]) for x in te], [-x[tk] for x in te]))
                    d1.append(spearman([-p for p in pred], [-x[tk] for x in te]))
                wins = sum(a > b_ + 1e-9 for a, b_ in zip(d1, d0))
                print(f'   {base} + {feat:<8} vs {tl:<9} {np.mean(d0):.3f} -> {np.mean(d1):.3f} ({wins}/4)')

    print('\n=== examples (season Y): best / worst QB situations among the market top 60 RB/WR/TE ===')
    top = sorted([x for x in recs if x['mp'] <= 60], key=lambda x: -x['qb_mkt'])
    for x in top[:5] + top[-5:]:
        print(f'   {x["Y"]} {x["key"][0]:<22}{x["pos"]:<3} QB {x["qb"]:<18} mkt #{x["mp"]:<4} sim #{x["sp"]:<4} -> season #{x["r1"]:<4} 3yr #{x["r3"]}')


if __name__ == '__main__':
    main()
