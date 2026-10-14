#!/usr/bin/env python3
"""
backtest_jm_af.py — is the year-2 JM credit after a GOOD rookie year double-counting
age? (Jack 2026-10-10: "is it not double counting ... draft age is in jm model" -> "run it")

JM_COND['aF'] = weight on the JM kernel for a year-2 player whose rookie year was
NOT slow (shipped .2). JM carries draft age, breakout age and a DC x age composite;
the market and the sim's youth years already credit youth. Rebuild the FAIR pool
(backtest_value_score.build, shipped M3 coef) at aF = .2 / .1 / 0 and score:
  whole board  per-year Spearman vs realized season / 3yr / 5yr+youth rank
  year-2 only  same, within the year-2 players
  sim alone    whole board (the sim's own objective)
plus the year-2 age residual (Sp of youth with beating FAIR rank) that started this.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dyn_common  # noqa: E402
from dyn_common import World, FORMATS, season_rel  # noqa: E402
from backtest_value_score import build  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

YRS = list(range(2016, 2024))


def evaluate(recs, w):
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    m3_ship(recs, c)
    for x in recs:
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
        x['v1'] = w.vor(x['key'], x['Y']) or 0.0
        dr = (w.players.get(x['key']) or {}).get('draft')
        x['cy'] = x['Y'] - dr[0] if dr else None
        if x['cy'] == 1:
            g1, r1 = season_rel(w, x['key'], x['Y'] - 1)
            x['slow'] = g1 < 4 or r1 < 1.0
    out = {}
    for tk, key in (('r1', lambda x: -x['v1']), ('r3', lambda x: x['r_t3']), ('r5', lambda x: x['r_lt'])):
        whole, yr2, yr2g, sim, ys_ok = [], [], [], [], []
        for Y in YRS:
            ys = [x for x in recs if x['Y'] == Y]
            if tk == 'r5' and any(x.get('r_lt') is None for x in ys):
                continue
            tr = {id(x): i + 1 for i, x in enumerate(sorted(ys, key=key))}
            ys_ok.append(Y)
            whole.append(spearman([-x['fz'] for x in ys], [-tr[id(x)] for x in ys]))
            sim.append(spearman([-x['s0'] for x in ys], [-tr[id(x)] for x in ys]))
            g = [x for x in ys if x['cy'] == 1]
            yr2.append(spearman([-x['fz'] for x in g], [-tr[id(x)] for x in g]))
            gg = [x for x in g if not x.get('slow')]
            yr2g.append(spearman([-x['fz'] for x in gg], [-tr[id(x)] for x in gg]))
        out[tk] = {k: np.array(v) for k, v in (('whole', whole), ('yr2', yr2), ('yr2good', yr2g), ('sim', sim))}
    # year-2 good-rookie age residual vs FAIR rank (3yr)
    resid = []
    for Y in YRS:
        ys = [x for x in recs if x['Y'] == Y]
        fr = {id(x): i + 1 for i, x in enumerate(sorted(ys, key=lambda x: x['fz']))}
        tr = {id(x): i + 1 for i, x in enumerate(sorted(ys, key=lambda x: x['r_t3']))}
        resid += [(-x['age'], math.log(fr[id(x)]) - math.log(tr[id(x)])) for x in ys
                  if x['cy'] == 1 and not x.get('slow') and x['age'] is not None]
    out['age_sp'] = spearman([a for a, _ in resid], [b for _, b in resid])
    return out


def main():
    w = World(2025)
    w.rows(FORMATS['1qb'], 2025)
    res = {}
    for aF in (0.2, 0.1, 0.0):
        dyn_common.JM_COND['aF'] = aF
        recs = [x for x in build(True) if x['Y'] in YRS]
        res[aF] = evaluate(recs, w)
        print(f'built aF={aF}: {len(recs)} player-seasons', flush=True)
    dyn_common.JM_COND['aF'] = 0.2
    base = res[0.2]
    print('\nper-year Spearman (mean; wins vs shipped aF .2)')
    for tk, lbl in (('r1', 'season'), ('r3', '3yr'), ('r5', '5yr+y')):
        for part in ('whole', 'yr2', 'yr2good', 'sim'):
            cells = []
            for aF in (0.2, 0.1, 0.0):
                v = res[aF][tk][part]
                wins = '' if aF == 0.2 else f' ({int((v > base[tk][part] + 1e-9).sum())}/{len(v)})'
                cells.append(f'aF {aF}: {v.mean():.4f}{wins}')
            print(f'  {lbl:<7}{part:<9}' + '   '.join(cells))
    print('\nyear-2 good-rookie: Sp(younger, beat FAIR rank 3yr) — the age residual that started this')
    for aF in (0.2, 0.1, 0.0):
        print(f'  aF {aF}: {res[aF]["age_sp"]:+.3f}')


if __name__ == '__main__':
    main()
