import sys, math, json, os
import numpy as np
sys.path.insert(0, r'E:\MyFantasyFootball\sim_lab')
import research_team_totals_value as R
from backtest_js_model import spearman
from dyn_common import World, FORMATS
from backtest_value_score import build
from backtest_fair_retune_jm import m3_ship

w = World(2025); w.rows(FORMATS['1qb'], 2025)
tt, team = {}, {}
for Y in R.YRS:
    tt[Y], _ = R.team_tt(Y); team[Y] = R.week1_team(Y)
c = json.load(open(os.path.join(R.HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
recs = [x for x in build(True) if x['Y'] in R.YRS]; m3_ship(recs, c)
recs = [x for x in recs if team[x['Y']].get(x['key']) in tt[x['Y']]]
for x in recs:
    x['tt'] = tt[x['Y']][team[x['Y']][x['key']]]
    x['fz'] = 0.5*x['m3'] + 0.3*math.log(x['s0']) + 0.5*math.log(x['m0'])
    x['v1'] = w.vor(x['key'], x['Y']) or 0.0
mu, sd = np.mean([x['tt'] for x in recs]), np.std([x['tt'] for x in recs])
for x in recs: x['z'] = (x['tt']-mu)/sd
qm = np.mean([x['z'] for x in recs if x['pos'] == 'QB'])


def score(k, tk, sel):
    out = []
    for Y in R.YRS:
        ys = [x for x in recs if x['Y'] == Y]
        key = {'r1': lambda x: -x['v1'], 'r3': lambda x: x['r_t3']}[tk]
        tr = {id(x): i for i, x in enumerate(sorted(ys, key=key))}
        f = lambda x: x['fz'] - (k*(x['z']-qm) if x['pos'] == 'QB' and sel(x) else 0)
        out.append(spearman([-f(x) for x in ys], [-tr[id(x)] for x in ys]))
    return np.array(out)


groups = (('age<=24', lambda x: (x['age'] or 30) <= 24),
          ('age 25-29', lambda x: 25 <= (x['age'] or 30) <= 29),
          ('age 30+', lambda x: (x['age'] or 30) >= 30),
          ('rookie', lambda x: bool(x['rookie'])))
for lbl, sel in groups:
    n = sum(1 for x in recs if x['pos'] == 'QB' and sel(x))
    for tk in ('r1', 'r3'):
        b = score(0, tk, sel)
        cells = []
        for k in (0.2, 0.4):
            s = score(k, tk, sel); cells.append(f'k{k}: {s.mean():.4f} ({(s > b + 1e-9).sum()}/6)')
        print(f'{lbl:<10} n{n:<4}{tk} base {b.mean():.4f} | ' + '  '.join(cells))
for lbl, sel in groups:
    g = [x for x in recs if x['pos'] == 'QB' and sel(x)]
    for tk in ('r1', 'r3'):
        tr = {}
        for Y in R.YRS:
            ys = [x for x in recs if x['Y'] == Y]
            key = {'r1': lambda x: -x['v1'], 'r3': lambda x: x['r_t3']}[tk]
            for i, x in enumerate(sorted(ys, key=key)): tr[id(x)] = i + 1
        res = [math.log(tr[id(x)]) - x['fz'] for x in g]
        print(f'{lbl:<10} {tk} Sp(team total, beat FAIR) {spearman([x["tt"] for x in g], [-r for r in res]):+.3f}')
