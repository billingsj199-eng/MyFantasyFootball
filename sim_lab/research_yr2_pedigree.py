#!/usr/bin/env python3
"""
research_yr2_pedigree.py — do draft capital and the JM prospect score help MFF VALUE
(FAIR) rank SECOND-YEAR players? (Jack 2026-10-10: "test draft capital for second
year players" + "and jm model")

FAIR here already includes the shipped Dynasty SIM with the conditional JM credit
(year 2: .5 after a slow rookie year, .2 otherwise) and KTC/FFC market rank, which
prices draft capital. So the question is whether MORE pedigree weight helps.

Pool: FFC dynasty pool 2016-23 (1QB PPR), players in career year 2 (Y = draft
year + 1). Features (z within the year-2 group, + = better pedigree):
  dc  = -log(draft pick)
  jm  = JM prospect score (CAVEAT: JM v9 weights were fit on 2017-24 outcomes, so
        past-class JM is partly in-sample — a JM gain here is an upper bound)
Splits: slow rookie year (< 4 games or below replacement per game) vs not.
Tests: (a) within-group Spearman of the feature with beating FAIR rank
(log realized rank - log FAIR rank, ranks within year); (b) whole board per-year
Spearman with fz -= k x z on the group only, k chosen leave-one-year-out.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, FORMATS, load_jm, season_rel  # noqa: E402
from backtest_value_score import build  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

YRS = list(range(2016, 2024))
K = [-0.8, -0.6, -0.5, -0.4, -0.3, -0.2, -0.15, -0.1, -0.05, 0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4]


def main():
    w = World(2025)
    w.rows(FORMATS['1qb'], 2025)
    jm = load_jm()
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = [x for x in build(True) if x['Y'] in YRS]
    m3_ship(recs, c)
    for x in recs:
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
        x['v1'] = w.vor(x['key'], x['Y']) or 0.0
        dr = (w.players.get(x['key']) or {}).get('draft')
        x['cy'] = x['Y'] - dr[0] if dr else None
        x['pk'] = dr[1] if dr else None
        x['jmv'] = jm.get(x['key'])
        if x['cy'] == 1:
            g1, r1 = season_rel(w, x['key'], x['Y'] - 1)
            x['slow'] = g1 < 4 or r1 < 1.0
    TR, FR = {}, {}
    for Y in YRS:
        ys = [x for x in recs if x['Y'] == Y]
        for i, x in enumerate(sorted(ys, key=lambda x: x['fz'])):
            FR[id(x)] = i + 1
        for tk, key in (('r1', lambda x: -x['v1']), ('r3', lambda x: x['r_t3']), ('r5', lambda x: x['r_lt'])):
            if tk == 'r5' and any(x.get('r_lt') is None for x in ys):
                continue
            for i, x in enumerate(sorted(ys, key=key)):
                TR[(tk, id(x))] = i + 1

    def board(k, tk, g, zf, years):
        ids = {id(x): zf(x) for x in g}
        out = []
        for Y in years:
            ys = [x for x in recs if x['Y'] == Y]
            f = lambda x: x['fz'] - k * ids.get(id(x), 0.0)
            out.append(spearman([-f(x) for x in ys], [-TR[(tk, id(x))] for x in ys]))
        return np.array(out)

    yr2 = [x for x in recs if x['cy'] == 1 and x['pk']]
    print(f'pool {len(recs)}; year-2 players {len(yr2)} (with JM {sum(1 for x in yr2 if x["jmv"] is not None)}), '
          f'slow rookie year {sum(1 for x in yr2 if x.get("slow"))}')
    groups = (('all yr2', lambda x: True), ('slow rookie yr', lambda x: x.get('slow')),
              ('good rookie yr', lambda x: not x.get('slow')), ('picks 1-64', lambda x: x['pk'] <= 64),
              ('picks 65+', lambda x: x['pk'] > 64))
    # feature: (needs, value) — 'young' added 10-10 (Jack: "test age for second year players"):
    # - age entering year 2, so + = younger
    FEATS = {'dc': (lambda x: True, lambda x: -math.log(x['pk'])),
             'jm': (lambda x: x['jmv'] is not None, lambda x: x['jmv']),
             'young': (lambda x: x['age'] is not None, lambda x: -x['age'])}
    for feat in (sys.argv[1:] or ['dc', 'jm']):
        need, val = FEATS[feat]
        print(f'\n=== {feat.upper()} ===')
        print(f'{"group":<16}{"n":>4}  {"beat FAIR Sp (season / 3yr / 5yr)":<36}  whole board: LOYO gain (wins) per horizon')
        for lbl, gsel in groups:
            g = [x for x in yr2 if gsel(x) and need(x)]
            if len(g) < 15:
                print(f'{lbl:<16}{len(g):>4}  too few'); continue
            raw = np.array([val(x) for x in g], float)
            mu, sd = raw.mean(), raw.std() or 1
            zmap = {id(x): (v - mu) / sd for x, v in zip(g, raw)}
            zf = lambda x: zmap[id(x)]
            sp = []
            for tk in ('r1', 'r3', 'r5'):
                gg = [x for x in g if (tk, id(x)) in TR]
                beat = [math.log(FR[id(x)]) - math.log(TR[(tk, id(x))]) for x in gg]   # + = finished better than FAIR rank
                sp.append(f'{spearman([zf(x) for x in gg], beat):+.3f}')
            cells = []
            for tk in ('r1', 'r3', 'r5'):
                yrs = [Y for Y in YRS if all((tk, id(x)) in TR for x in recs if x['Y'] == Y)]
                gg = [x for x in g if x['Y'] in yrs]
                S = {k: board(k, tk, gg, zf, yrs) for k in K}
                d = []
                for i in range(len(yrs)):
                    kk = max(K, key=lambda k: np.delete(S[k], i).mean()); d.append(S[kk][i] - S[0][i])
                kb = max(K, key=lambda k: S[k].mean())
                cells.append(f'{tk} k{kb} {np.mean(d):+.4f} ({sum(v > 1e-9 for v in d)}/{len(yrs)})')
            print(f'{lbl:<16}{len(g):>4}  {" / ".join(sp):<36}  ' + ' | '.join(cells))
    print('\n   beat FAIR Sp > 0 = better pedigree finished ABOVE its FAIR rank (FAIR under-credits pedigree).')


if __name__ == '__main__':
    main()
