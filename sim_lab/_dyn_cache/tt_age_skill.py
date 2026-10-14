"""Team implied total x age for RB / WR / TE (Jack 2026-10-09 "can we do this with rb,wr,tes").
Same pool / truth as tt_age.py. Per position x age group: (a) within-group Spearman of
team total with beating FAIR (season / 3yr realized), (b) whole-board per-year Spearman
when a k x z term is added for that group only (wins of 6), (c) leave-one-year-out k."""
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
TR = {}
for tk, key in (('r1', lambda x: -x['v1']), ('r3', lambda x: x['r_t3'])):
    for Y in R.YRS:
        for i, x in enumerate(sorted([x for x in recs if x['Y'] == Y], key=key)):
            TR[(tk, id(x))] = i + 1


def board(k, tk, sel, years=R.YRS):
    out = []
    for Y in years:
        ys = [x for x in recs if x['Y'] == Y]
        gm = np.mean([x['z'] for x in recs if sel(x)])
        f = lambda x: x['fz'] - (k*(x['z']-gm) if sel(x) else 0)
        out.append(spearman([-f(x) for x in ys], [-TR[(tk, id(x))] for x in ys]))
    return np.array(out)


AGES = {'RB': ((':<=24', 0, 24), (':25-26', 25, 26), (':27+', 27, 99)),
        'WR': ((':<=24', 0, 24), (':25-27', 25, 27), (':28+', 28, 99)),
        'TE': ((':<=25', 0, 25), (':26-28', 26, 28), (':29+', 29, 99))}
K = [0, 0.1, 0.2, 0.3, 0.4]
for pos in ('RB', 'WR', 'TE'):
    for lbl, lo, hi in ((':all', 0, 99),) + AGES[pos]:
        sel = (lambda p, lo, hi: (lambda x: x['pos'] == p and lo <= (x['age'] or 25) <= hi))(pos, lo, hi)
        g = [x for x in recs if sel(x)]
        line = f'{pos+lbl:<10} n{len(g):<4}'
        for tk in ('r1', 'r3'):
            res = [math.log(TR[(tk, id(x))]) - x['fz'] for x in g]
            line += f' {tk} Sp {spearman([x["tt"] for x in g], [-r for r in res]):+.3f}'
        for tk in ('r1', 'r3'):
            b = board(0, tk, sel)
            S = {k: board(k, tk, sel) for k in K}
            kb = max(K, key=lambda k: S[k].mean())
            # LOYO pick
            d = []
            for i in range(len(R.YRS)):
                kk = max(K, key=lambda k: np.delete(S[k], i).mean()); d.append(S[kk][i] - b[i])
            line += f' | {tk} best k{kb} {S[kb].mean()-b.mean():+.4f} ({(S[kb] > b + 1e-9).sum()}/6) LOYO {np.mean(d):+.4f} ({sum(v > 1e-9 for v in d)}/6)'
        print(line)
