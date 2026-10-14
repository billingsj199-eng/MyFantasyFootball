#!/usr/bin/env python3
"""
backtest_jm_bounce.py — JM weight for SLOW-ROOKIE-YEAR bounce-backs, through MFF VALUE
(FAIR). (Jack 2026-10-10: "test jm for slow rookie year bounce backs")

Slow rookie year = < 4 games or below replacement per game (dyn_common.season_rel).
  aS  = JM weight in year 2 after a slow rookie year (shipped .5)
  a3s = NEW: JM weight in year 3 after slow years 1 AND 2 (shipped 0 — pedigree expires)
Each swept alone (sim rebuilt, FAIR with shipped M3). Scored per year 2016-23 on the
group itself:
  sp      Spearman FAIR vs realized rank within the group (season / 3yr / 5yr+youth)
  err     placement error on the whole board, mean |log FAIR rank - log realized rank|
  auc     does the FAIR order find the BOUNCE-BACKS: breakout = QB/TE top-12 or RB/WR
          top-24 season in the next 3 seasons (as research_jm_slow_starters.py);
          AUC of -FAIR rank for breakout within the group (all years pooled)
plus the whole-board Spearman, and the value chosen leave-one-year-out on group err.
JM CAVEAT: JM v9 weights fit on 2017-24 outcomes -> past-class JM partly in-sample.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dyn_common  # noqa: E402
import backtest_value_score as bvs  # noqa: E402
from dyn_common import World, FORMATS, season_rel  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

YRS = list(range(2016, 2024))
SHIP = dict(dyn_common.JM_COND)
C = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
_orig_w = dyn_common.jm_cond_weight
EXTRA = {'a3s': 0.0}


def slow(w, key, yr):
    g, r = season_rel(w, key, yr)
    return g < 4 or r < 1.0


def jm_w(w, key, Y, p, g_cur=0):
    cy, a = _orig_w(w, key, Y, p, g_cur)
    dr = w.players[key]['draft']
    if cy == 2 and a == 0.0 and EXTRA['a3s'] and dr and not (key[1] == 'TE' and not p.get('te')) \
            and slow(w, key, dr[0]) and slow(w, key, dr[0] + 1):
        return cy, EXTRA['a3s']
    return cy, a


bvs.jm_cond_weight = jm_w


def auc(scores, labels):
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    if not pos or not neg:
        return float('nan')
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def main():
    w = World(2025)
    w.rows(FORMATS['1qb'], 2025)
    # positional season ranks for the breakout label
    prank = defaultdict(dict)
    for yr, d in w.pts.items():
        byp = defaultdict(list)
        for k, v in d.items():
            byp[k[1]].append((v, k))
        for P, lst in byp.items():
            for i, (_, k) in enumerate(sorted(lst, reverse=True)):
                prank[yr][k] = i + 1
    cut = {'QB': 12, 'TE': 12, 'RB': 24, 'WR': 24}

    def run():
        recs = [x for x in bvs.build(True) if x['Y'] in YRS]
        m3_ship(recs, C)
        for x in recs:
            x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
            x['v1'] = w.vor(x['key'], x['Y']) or 0.0
            dr = (w.players.get(x['key']) or {}).get('draft')
            x['cy'] = x['Y'] - dr[0] if dr else None
            x['grp'] = None
            if x['cy'] == 1 and slow(w, x['key'], dr[0]):
                x['grp'] = 'S'
            elif x['cy'] == 2 and slow(w, x['key'], dr[0]) and slow(w, x['key'], dr[0] + 1):
                x['grp'] = 'SS'
            x['bo'] = any(prank.get(x['Y'] + i, {}).get(x['key'], 999) <= cut[x['pos']] for i in range(3))
        out = {}
        for tk, key in (('r1', lambda x: -x['v1']), ('r3', lambda x: x['r_t3']), ('r5', lambda x: x['r_lt'])):
            res = {'whole': [], 'S': {'sp': [], 'err': []}, 'SS': {'sp': [], 'err': []}}
            for Y in YRS:
                ys = [x for x in recs if x['Y'] == Y]
                if tk == 'r5' and any(x.get('r_lt') is None for x in ys):
                    continue
                tr = {id(x): i + 1 for i, x in enumerate(sorted(ys, key=key))}
                fr = {id(x): i + 1 for i, x in enumerate(sorted(ys, key=lambda x: x['fz']))}
                for x in ys:
                    x['_fr'] = fr[id(x)]
                res['whole'].append(spearman([-x['fz'] for x in ys], [-tr[id(x)] for x in ys]))
                for gk in ('S', 'SS'):
                    g = [x for x in ys if x['grp'] == gk]
                    res[gk]['sp'].append(spearman([-x['fz'] for x in g], [-tr[id(x)] for x in g]) if len(g) >= 5 else float('nan'))
                    res[gk]['err'].append(np.mean([abs(math.log(fr[id(x)]) - math.log(tr[id(x)])) for x in g]) if g else float('nan'))
            out[tk] = res
        for gk in ('S', 'SS'):
            g = [x for x in recs if x['grp'] == gk]
            out['auc_' + gk] = auc([-x['_fr'] for x in g], [x['bo'] for x in g])
            out['n_' + gk] = (len(g), sum(x['bo'] for x in g))
            for P in ('QB', 'RB', 'WR', 'TE'):
                gp = [x for x in g if x['pos'] == P]
                out[f'auc_{gk}_{P}'] = (auc([-x['_fr'] for x in gp], [x['bo'] for x in gp]), len(gp))
        return out

    def report(name, vals, gk, setter):
        R = {}
        for v in vals:
            setter(v)
            R[v] = run()
        setter(None)
        n, nb = R[vals[0]]['n_' + gk]
        print(f'\n=== {name} — group {gk}: {n} player-seasons, {nb} bounced back (breakout within 3 seasons) ===')
        print(f'{"w":<6}{"whole s/3y/5y":>24}{"grp Sp s/3y/5y":>22}{"grp err s/3y/5y":>22}{"bounce AUC":>12}   AUC by pos (n)')
        for v in vals:
            r = R[v]
            wh = '/'.join(f'{np.nanmean(r[t]["whole"]):.4f}' for t in ('r1', 'r3', 'r5'))
            sp = '/'.join(f'{np.nanmean(r[t][gk]["sp"]):.3f}' for t in ('r1', 'r3', 'r5'))
            er = '/'.join(f'{np.nanmean(r[t][gk]["err"]):.3f}' for t in ('r1', 'r3', 'r5'))
            pa = ' '.join(f'{P} {r[f"auc_{gk}_{P}"][0]:.2f}({r[f"auc_{gk}_{P}"][1]})' for P in ('QB', 'RB', 'WR', 'TE'))
            print(f'{v:<6}{wh:>24}{sp:>22}{er:>22}{r["auc_" + gk]:>12.3f}   {pa}')
        return R

    VS = [0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]

    def set_aS(v):
        dyn_common.JM_COND.clear(); dyn_common.JM_COND.update(SHIP if v is None else dict(SHIP, aS=v))
    RS = report('aS (year 2 after slow rookie year; shipped .5)', VS, 'S', set_aS)

    def set_a3s(v):
        EXTRA['a3s'] = 0.0 if v is None else v
    RSS = report('a3s (year 3 after slow years 1+2; shipped 0)', [0.0, 0.1, 0.2, 0.3, 0.5], 'SS', set_a3s)

    for name, R, gk, base in (('aS', RS, 'S', 0.5), ('a3s', RSS, 'SS', 0.0)):
        vals = list(R)
        for tk, lbl in (('r1', 'season'), ('r3', '3yr'), ('r5', '5yr')):
            sc = {v: np.array(R[v][tk][gk]['err']) for v in vals}
            ok = ~np.isnan(sc[base])
            d, picks = [], []
            for i in np.where(ok)[0]:
                vb = min(vals, key=lambda v: np.nanmean(np.delete(sc[v], i))); picks.append(vb)
                d.append(sc[base][i] - sc[vb][i])
            print(f'  LOYO {name} {lbl:<7} group err: picks {picks} gain {np.mean(d):+.4f} ({sum(x > 1e-9 for x in d)}/{len(d)})')
    dyn_common.JM_COND.clear(); dyn_common.JM_COND.update(SHIP)


if __name__ == '__main__':
    main()
