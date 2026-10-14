#!/usr/bin/env python3
"""
research_situation_layer.py — offseason situation signals as a Dynasty SIM layer
(Jack 2026-10-09: "test the situation signals as a sim layer next"; signals from
research_yr1_yr2_situation.py: vacated same-position share, new head coach /
playcaller, QB change helped / hurt slow young players' year-2 jumps).

Pool: FFC dynasty ADP pool, valuation years 2020-23 (situation data =
ctx_features.parquet 2019-25), 1QB PPR, shipped conditional-JM sim
(backtest_value_score.build(True)), shipped FAIR order.
Signals entering season Y (from the season-Y and Y-1 rows):
  vac     same-position target share (WR/TE) / carry share (RB) held in Y-1 by
          teammates on his season-Y team who are gone in Y
  new_hc / new_pc / team_change   (ctx flags for season Y)
  qb_chg  team's top dropback QB differs Y-1 -> Y (non-QBs)
Truths: season-Y VOR rank (T1, the year the situation applies) and 3-season
VOR rank (T3). Residual = log(realized rank / sim rank).
1  descriptive: residual by signal (all / young = career years 1-3 / vets)
2  layer: adjusted score = log sim rank - (b . x), b fit by OLS on the residual
   LEAVE-ONE-YEAR-OUT; per-year Spearman of the adjusted sim and of FAIR built
   on the adjusted sim vs the shipped ones.
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
from dyn_common import World, _norm_name, FORMATS  # noqa: E402
from backtest_value_score import build  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

YRS = [2020, 2021, 2022, 2023]
SIG = ['vac', 'new_hc', 'new_pc', 'team_change', 'qb_chg']


def situation():
    ctx = pd.read_parquet(os.path.join(HERE, 'ctx_features.parquet'))
    ctx['key'] = [(_norm_name(n), p) for n, p in zip(ctx['name'], ctx['pos'])]
    ctx = ctx.sort_values(['year', 'wk'])
    last = {}
    for r in ctx.groupby(['name', 'pos', 'year']).tail(1).to_dict('records'):
        last[(r['key'], r['year'])] = r
    flags = {}
    for r in ctx.to_dict('records'):
        f = flags.setdefault((r['key'], r['year']), {'new_hc': 0.0, 'new_pc': 0.0, 'team_change': 0.0})
        for c in f:
            v = r[c]
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                f[c] = max(f[c], float(v))
    room = defaultdict(list)
    for (k, y), r in last.items():
        room[(r['team'], y)].append((k, r['tgt_sh'] or 0, r['car_sh'] or 0))
    qb_top = {}
    for (t, y), lst in room.items():
        qs = [((last[(k, y)]['db_sh'] or 0) * (last[(k, y)]['g'] or 0), k) for k, *_ in lst if k[1] == 'QB']
        if qs:
            qb_top[(t, y)] = max(qs)[1]
    team = {kk: r['team'] for kk, r in last.items()}

    def sig(key, Y):
        t1, t0 = team.get((key, Y)), team.get((key, Y - 1))
        if not t1:
            return None
        here = {k for k, *_ in room.get((t1, Y), [])}
        vt = vc = 0.0
        for k, ts, cs in room.get((t1, Y - 1), []):
            if k != key and k[1] == key[1] and k not in here:
                vt += ts or 0; vc += cs or 0
        f = flags.get((key, Y), {})
        return {'vac': (vc if key[1] == 'RB' else vt if key[1] in ('WR', 'TE') else 0.0),
                'new_hc': f.get('new_hc', 0.0), 'new_pc': f.get('new_pc', 0.0), 'team_change': f.get('team_change', 0.0),
                'qb_chg': float(key[1] != 'QB' and t0 is not None and qb_top.get((t0, Y - 1)) != qb_top.get((t1, Y)))}
    return sig


def main():
    sig = situation()
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = [x for x in build(True) if x['Y'] in YRS]
    m3_ship(recs, c)
    w = World(2025); w.rows(FORMATS['1qb'], 2025)
    for x in recs:
        x['s'] = sig(x['key'], x['Y'])
        x['v1'] = w.vor(x['key'], x['Y']) or 0.0
        dr = w.players[x['key']]['draft']
        x['young'] = bool(dr and 0 <= x['Y'] - dr[0] <= 2)
    recs = [x for x in recs if x['s'] is not None]
    for Y in YRS:
        ys = [x for x in recs if x['Y'] == Y]
        for i, x in enumerate(sorted(ys, key=lambda x: -x['v1'])):
            x['r1'] = i + 1
        for i, x in enumerate(sorted(ys, key=lambda x: x['s0'])):
            x['sp'] = i + 1          # sim rank within the covered pool
        for i, x in enumerate(sorted(ys, key=lambda x: x['m0'])):
            x['mp'] = i + 1
        for i, x in enumerate(sorted(ys, key=lambda x: x['r_t3'])):
            x['r3'] = i + 1
    print(f'pool with situation data: {len(recs)} player-seasons {YRS[0]}-{YRS[-1]} '
          f'(young {sum(x["young"] for x in recs)}); signal rates: ' + ', '.join(f'{s} {np.mean([x["s"][s] > 0 for x in recs]):.0%}' for s in SIG))

    print('\n=== 1. residual log(realized rank / SIM rank) by signal (- = beat the sim) ===')
    print(f'{"signal":<30}' + ''.join(f'{h:>20}' for h in ('T1 all', 'T1 young', 'T3 all', 'T3 young')))
    rows = [('vacated share >= .15', lambda x: x['s']['vac'] >= 0.15), ('vacated share < .05', lambda x: x['s']['vac'] < 0.05),
            ('new head coach', lambda x: x['s']['new_hc'] > 0), ('new playcaller', lambda x: x['s']['new_pc'] > 0),
            ('changed teams', lambda x: x['s']['team_change'] > 0), ('QB change (non-QB)', lambda x: x['s']['qb_chg'] > 0),
            ('none of the above', lambda x: all(x['s'][s] <= 0.05 for s in SIG))]
    for lbl, f in rows:
        cells = []
        for tk, young in (('r1', None), ('r1', True), ('r3', None), ('r3', True)):
            g = [x for x in recs if f(x) and (young is None or x['young'])]
            if len(g) < 10:
                cells.append(f'{"—":>20}'); continue
            v = [math.log(x[tk] / x['sp']) for x in g]
            m, t = np.mean(v), np.mean(v) / (np.std(v) / math.sqrt(len(v)))
            cells.append(f'{m:+.2f}{"*" if abs(t) >= 2 else " "} (n {len(g)})'.rjust(20))
        print(f'{lbl:<30}' + ''.join(cells))

    print('\n=== 2. layer: adjusted sim = log sim rank - b . x, b by OLS on the residual, leave-one-year-out ===')
    X = lambda x, young_only: [x['s']['vac'], x['s']['new_hc'], x['s']['new_pc'], x['s']['team_change'], x['s']['qb_chg']] if (not young_only or x['young']) else [0.0] * 5
    for tk, tl in (('r1', 'season-Y VOR'), ('r3', '3-season VOR')):
        for young_only in (False, True):
            base_sim, adj_sim, base_fair, adj_fair, bs = [], [], [], [], []
            for Y in YRS:
                tr = [x for x in recs if x['Y'] != Y and (not young_only or x['young'])]
                A = np.array([X(x, young_only) for x in tr]); y = np.array([math.log(x[tk] / x['sp']) for x in tr])
                b = np.linalg.lstsq(np.hstack([np.ones((len(A), 1)), A]), y, rcond=None)[0][1:]
                bs.append(b)
                te = [x for x in recs if x['Y'] == Y]
                adj = {id(x): math.log(x['sp']) + float(np.dot(b, X(x, young_only))) for x in te}
                truth = [-x[tk] for x in te]
                base_sim.append(spearman([-math.log(x['sp']) for x in te], truth))
                adj_sim.append(spearman([-adj[id(x)] for x in te], truth))
                fz = lambda x, s: 0.5 * x['m3'] + 0.3 * s + 0.5 * math.log(x['m0'])
                base_fair.append(spearman([-fz(x, math.log(x['sp'])) for x in te], truth))
                adj_fair.append(spearman([-fz(x, adj[id(x)]) for x in te], truth))
            wins_s = sum(a > b + 1e-9 for a, b in zip(adj_sim, base_sim)); wins_f = sum(a > b + 1e-9 for a, b in zip(adj_fair, base_fair))
            print(f'   {tl:<14} {"young only" if young_only else "all players":<12} SIM {np.mean(base_sim):.3f} -> {np.mean(adj_sim):.3f} ({wins_s}/4)'
                  f'   FAIR {np.mean(base_fair):.3f} -> {np.mean(adj_fair):.3f} ({wins_f}/4)'
                  f'   b (vac, hc, pc, team, qb) median: ' + ', '.join(f'{v:+.2f}' for v in np.median(np.array(bs), 0)))
    print('   b < 0 on a signal = it moves players UP (better than the sim ranked them)')


if __name__ == '__main__':
    main()
