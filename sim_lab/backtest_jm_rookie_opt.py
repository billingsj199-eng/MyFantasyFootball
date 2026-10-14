#!/usr/bin/env python3
"""
backtest_jm_rookie_opt.py — optimal ROOKIE JM weight through MFF VALUE (FAIR).
(Jack 2026-10-10: "test rookie jm optimal", after backtest_jm_fade.py showed rookies
rank better among themselves at aR .3 than the shipped .5.)

aR = weight on the JM kernel in a drafted rookie's preseason sim value (the rest =
comps on draft pick + draft age); TE stays off. Swept 0 .. .8, overall and per
position (QB / RB / WR — the other positions held at shipped .5), sim rebuilt each
time (backtest_value_score.build), FAIR re-ordered with the shipped M3.
Scores per year (2016-23):
  whole   whole-board Spearman (FAIR vs realized rank)
  rk_sp   rookies-only Spearman
  rk_err  rookies' placement error on the WHOLE board = mean |log FAIR rank -
          log realized rank| (lower = better) — where the rookie lands vs everyone
Truths: season, 3yr, 5yr+youth. Choice leave-one-year-out on rk_err (season+3yr),
with the whole-board change reported alongside. JM CAVEAT: JM v9 weights were fit
on 2017-24 outcomes -> past-class JM partly in-sample (gains are an upper bound).
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dyn_common  # noqa: E402
import backtest_value_score as bvs  # noqa: E402
from dyn_common import World, FORMATS  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

YRS = list(range(2016, 2024))
SHIP = dict(dyn_common.JM_COND)
C = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
_orig_w = dyn_common.jm_cond_weight
POS_AR = {}


def jm_w(w, key, Y, p, g_cur=0):
    cy, a = _orig_w(w, key, Y, p, g_cur)
    if cy == 0 and key[1] in POS_AR:
        return cy, POS_AR[key[1]]
    return cy, a


bvs.jm_cond_weight = jm_w


def run(w):
    recs = [x for x in bvs.build(True) if x['Y'] in YRS]
    m3_ship(recs, C)
    for x in recs:
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
        x['v1'] = w.vor(x['key'], x['Y']) or 0.0
    out = {}
    for tk, key in (('r1', lambda x: -x['v1']), ('r3', lambda x: x['r_t3']), ('r5', lambda x: x['r_lt'])):
        res = {'whole': [], 'rk_sp': [], 'rk_err': {}, 'pos_err': {}}
        for Y in YRS:
            ys = [x for x in recs if x['Y'] == Y]
            if tk == 'r5' and any(x.get('r_lt') is None for x in ys):
                continue
            tr = {id(x): i + 1 for i, x in enumerate(sorted(ys, key=key))}
            fr = {id(x): i + 1 for i, x in enumerate(sorted(ys, key=lambda x: x['fz']))}
            res['whole'].append(spearman([-x['fz'] for x in ys], [-tr[id(x)] for x in ys]))
            rk = [x for x in ys if x['rookie']]
            res['rk_sp'].append(spearman([-x['fz'] for x in rk], [-tr[id(x)] for x in rk]))
            res['rk_err'][Y] = np.mean([abs(math.log(fr[id(x)]) - math.log(tr[id(x)])) for x in rk])
            for P in ('QB', 'RB', 'WR'):
                g = [x for x in rk if x['pos'] == P]
                res['pos_err'].setdefault(P, {})[Y] = np.mean([abs(math.log(fr[id(x)]) - math.log(tr[id(x)])) for x in g]) if g else float('nan')
        out[tk] = res
    out['n'] = {P: sum(1 for x in recs if x['rookie'] and x['pos'] == P) for P in ('QB', 'RB', 'WR', 'TE')}
    return out


def loyo(scores, base, lower_better=True):
    """scores: {val: array per year}; pick per held-out year on the other years."""
    vals = list(scores)
    n = len(base)
    d, picks = [], []
    for i in range(n):
        f = (lambda v: -np.delete(scores[v], i).mean()) if lower_better else (lambda v: np.delete(scores[v], i).mean())
        vb = max(vals, key=f); picks.append(vb)
        d.append((base[i] - scores[vb][i]) if lower_better else (scores[vb][i] - base[i]))
    return picks, np.mean(d), sum(x > 1e-9 for x in d)


def main():
    w = World(2025)
    w.rows(FORMATS['1qb'], 2025)
    VALS = [0.0, 0.1, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6, 0.8]
    POS_AR.clear()
    R = {}
    for v in VALS:
        dyn_common.JM_COND.clear(); dyn_common.JM_COND.update(dict(SHIP, aR=v))
        R[v] = run(w)
    print(f'rookies in pool: {R[0.5]["n"]}')
    print('\n=== ALL POSITIONS (TE off) ===')
    print(f'{"aR":<6}' + ''.join(f'{h:>27}' for h in ('season  whole/rkSp/rkErr', '3yr  whole/rkSp/rkErr', '5yr  whole/rkSp/rkErr')))
    for v in VALS:
        cells = []
        for tk in ('r1', 'r3', 'r5'):
            r = R[v][tk]
            cells.append(f'{np.mean(r["whole"]):.4f}/{np.mean(r["rk_sp"]):.3f}/{np.mean(list(r["rk_err"].values())):.3f}')
        print(f'{v:<6}' + ''.join(f'{c:>27}' for c in cells))
    for tk, lbl in (('r1', 'season'), ('r3', '3yr'), ('r5', '5yr')):
        ys = sorted(R[0.5][tk]['rk_err'])
        sc = {v: np.array([R[v][tk]['rk_err'][Y] for Y in ys]) for v in VALS}
        picks, g, wins = loyo(sc, sc[0.5])
        wh = {v: np.array(R[v][tk]['whole']) for v in VALS}
        wp, wg, ww = loyo(wh, wh[0.5], lower_better=False)
        print(f'  LOYO {lbl:<7} rookie placement err: picks {picks} gain {g:+.4f} ({wins}/{len(ys)})'
              f' | whole board: picks {wp} gain {wg:+.4f} ({ww}/{len(ys)})')
    print('\n=== PER POSITION (one position swept, others .5) — rookie placement error ===')
    for P in ('QB', 'RB', 'WR'):
        RP = {}
        for v in VALS:
            POS_AR.clear(); POS_AR[P] = v
            dyn_common.JM_COND.clear(); dyn_common.JM_COND.update(SHIP)
            RP[v] = run(w)
        POS_AR.clear()
        line = f'{P} (n {R[0.5]["n"][P]}): '
        for tk, lbl in (('r1', 'season'), ('r3', '3yr'), ('r5', '5yr')):
            ys = sorted(RP[0.5][tk]['pos_err'][P])
            sc = {v: np.array([RP[v][tk]['pos_err'][P][Y] for Y in ys]) for v in VALS}
            ok = [i for i, Y in enumerate(ys) if not math.isnan(sc[0.5][i])]
            sc = {v: a[ok] for v, a in sc.items()}
            best = min(VALS, key=lambda v: sc[v].mean())
            picks, g, wins = loyo(sc, sc[0.5])
            line += f'| {lbl} best {best} ({sc[best].mean():.3f} vs .5 {sc[0.5].mean():.3f}) LOYO {g:+.4f} ({wins}/{len(ok)}) '
        print(line)
    dyn_common.JM_COND.clear(); dyn_common.JM_COND.update(SHIP)


if __name__ == '__main__':
    main()
