import sys, math, numpy as np
sys.path.insert(0, r'E:\MyFantasyFootball\sim_lab')
import research_team_totals_value as R
from backtest_js_model import spearman
cap = {}
orig = R.main
# reuse main's pool building by monkeypatching print-heavy parts: rebuild quickly
import json, os
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
def score(grp, k, tk):
    out = []
    for Y in R.YRS:
        ys = [x for x in recs if x['Y']==Y]
        if tk=='r1': tr = {id(x): i for i, x in enumerate(sorted(ys, key=lambda x: -x['v1']))}
        else: tr = {id(x): x['r_t3'] for x in ys}
        g = [x for x in ys if x['pos'] in grp]
        out.append(spearman([-(x['fz'] - k*x['z']) for x in g], [-tr[id(x)] for x in g]))
    return np.array(out)
for grp in (('QB','RB','WR','TE'), ('QB',), ('WR','TE')):
    for tk in ('r1','r3'):
        b = score(grp, 0, tk)
        row = []
        for k in (0.02, 0.05, 0.1, 0.2):
            s = score(grp, k, tk); row.append(f'k{k}: {s.mean():.3f} ({(s>b+1e-9).sum()}/6)')
        print(f'{"+".join(grp):<12}{tk}  base {b.mean():.3f} | ' + '  '.join(row))
print('--- QB-only term, whole pool (+5yr where complete) ---')
def score2(k, tk, centered):
    out = []
    for Y in R.YRS:
        ys = [x for x in recs if x['Y']==Y]
        if tk=='r5' and any(x.get('r_lt') is None for x in ys): continue
        key = {'r1': lambda x: -x['v1'], 'r3': lambda x: x['r_t3'], 'r5': lambda x: x['r_lt']}[tk]
        tr = {id(x): i for i, x in enumerate(sorted(ys, key=key))}
        qz = [x['z'] for x in recs if x['pos']=='QB']; qm = np.mean(qz) if centered else 0
        f = lambda x: x['fz'] - (k*(x['z']-qm) if x['pos']=='QB' else 0)
        out.append(spearman([-f(x) for x in ys], [-tr[id(x)] for x in ys]))
    return np.array(out)
for centered in (True,):
    for tk in ('r1','r3','r5'):
        b = score2(0, tk, centered)
        print(tk, f'base {b.mean():.4f} | ' + '  '.join(f'k{k}: {score2(k,tk,centered).mean():.4f} ({(score2(k,tk,centered)>b+1e-9).sum()}/{len(b)})' for k in (0.05,0.1,0.2,0.3)))
print('--- LOYO-chosen k (QB-only), grid 0..0.8; objective = avg of season+3yr per-year ---')
K = [0,0.05,0.1,0.2,0.3,0.4,0.5,0.6,0.8]
S = {k: (score2(k,'r1',True)+score2(k,'r3',True))/2 for k in K}
for k in K[4:]: print(f'  in-sample k{k}: {S[k].mean():.4f}')
picks, d = [], []
for i in range(6):
    kb = max(K, key=lambda k: np.delete(S[k], i).mean()); picks.append(kb); d.append(S[kb][i]-S[0][i])
print('  picks', picks, 'held-out gain', f'{np.mean(d):+.4f}', f'wins {sum(x>0 for x in d)}/6')
# what does it do today? Mendoza/LV etc: print QB z for 2023 example extremes
