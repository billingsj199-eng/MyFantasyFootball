#!/usr/bin/env python3
"""
backtest_jm_fade.py — JM fade timing through MFF VALUE (FAIR). (Jack 2026-10-10:
"how is jm involved does it decrease per year and eventually fade" -> "test the jm
fade timing")

Shipped schedule (dyn_common.JM_COND, tuned 10-09 on the SIM objective):
  rookie aR .5 | year 2 after slow rookie yr aS .5 | year 2 after good yr aF .2 |
  year 3 a3 .15 (0 if years 1+2 both slow) | year 4+ 0 | TE off.
Here each knob is swept alone (others shipped), the sim rebuilt (build(True)),
FAIR re-ordered with the shipped M3, and scored per year on the whole board and on
that knob's own career-year group. a4 = new year-4 weight (same rule as a3: 0 if
years 1-3 were all slow). The value per knob is picked leave-one-year-out on the
whole-board average of season + 3yr Spearman; held-out gain vs shipped reported.
Preseason only — the in-season rookie fade (2 / (games + 2)) was tuned separately
(backtest_dynasty_inseason.py, R = 2).
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
from dyn_common import World, FORMATS, season_rel  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

YRS = list(range(2016, 2024))
SHIP = dict(dyn_common.JM_COND)
_orig_w = dyn_common.jm_cond_weight


def jm_w(w, key, Y, p, g_cur=0):
    """shipped rule + optional year-4 weight p['a4'] (0 if years 1-3 all slow)."""
    dr = w.players[key]['draft']
    if dr and Y - dr[0] == 3 and p.get('a4') and not (key[1] == 'TE' and not p.get('te')):
        slow = [(lambda g, r: g < 4 or r < 1.0)(*season_rel(w, key, dr[0] + i)) for i in range(3)]
        return 3, 0.0 if all(slow) else p['a4']
    return _orig_w(w, key, Y, p, g_cur)


bvs.jm_cond_weight = jm_w
C = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']


def run(cfg, w):
    dyn_common.JM_COND.clear(); dyn_common.JM_COND.update(cfg)
    recs = [x for x in bvs.build(True) if x['Y'] in YRS]
    m3_ship(recs, C)
    for x in recs:
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
        x['v1'] = w.vor(x['key'], x['Y']) or 0.0
        dr = (w.players.get(x['key']) or {}).get('draft')
        x['cy'] = x['Y'] - dr[0] if dr else None
        x['slow1'] = None
        if x['cy'] is not None and x['cy'] >= 1:
            g1, r1 = season_rel(w, x['key'], dr[0])
            x['slow1'] = g1 < 4 or r1 < 1.0
    out = {}
    for tk, key in (('r1', lambda x: -x['v1']), ('r3', lambda x: x['r_t3']), ('r5', lambda x: x['r_lt'])):
        res = {'whole': [], 'cy0': [], 'cy1s': [], 'cy1g': [], 'cy2': [], 'cy3': []}
        for Y in YRS:
            ys = [x for x in recs if x['Y'] == Y]
            if tk == 'r5' and any(x.get('r_lt') is None for x in ys):
                continue
            tr = {id(x): i + 1 for i, x in enumerate(sorted(ys, key=key))}
            sp = lambda g: spearman([-x['fz'] for x in g], [-tr[id(x)] for x in g]) if len(g) >= 8 else float('nan')
            res['whole'].append(sp(ys))
            res['cy0'].append(sp([x for x in ys if x['cy'] == 0]))
            res['cy1s'].append(sp([x for x in ys if x['cy'] == 1 and x['slow1']]))
            res['cy1g'].append(sp([x for x in ys if x['cy'] == 1 and x['slow1'] is False]))
            res['cy2'].append(sp([x for x in ys if x['cy'] == 2]))
            res['cy3'].append(sp([x for x in ys if x['cy'] == 3]))
        out[tk] = {k: np.array(v) for k, v in res.items()}
    return out


def main():
    w = World(2025)
    w.rows(FORMATS['1qb'], 2025)
    knobs = [('aR', 'cy0', [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]),
             ('aS', 'cy1s', [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]),
             ('aF', 'cy1g', [0.0, 0.1, 0.2, 0.3, 0.4]),
             ('a3', 'cy2', [0.0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4]),
             ('a4', 'cy3', [0.0, 0.05, 0.1, 0.15, 0.2, 0.3])]
    cache = {}
    base = run(dict(SHIP), w)
    for knob, grp, vals in knobs:
        print(f'\n=== {knob} (shipped {SHIP.get(knob, 0.0)}) — group {grp} ===', flush=True)
        R = {}
        for v in vals:
            cfg = dict(SHIP); cfg[knob] = v
            ck = json.dumps(cfg, sort_keys=True)
            R[v] = cache[ck] = cache.get(ck) or run(cfg, w)
            r = R[v]
            print(f'  {knob}={v:<5} whole season {np.nanmean(r["r1"]["whole"]):.4f} 3yr {np.nanmean(r["r3"]["whole"]):.4f} '
                  f'5yr {np.nanmean(r["r5"]["whole"]):.4f} | {grp} season {np.nanmean(r["r1"][grp]):.3f} '
                  f'3yr {np.nanmean(r["r3"][grp]):.3f} 5yr {np.nanmean(r["r5"][grp]):.3f}', flush=True)
        obj = {v: (R[v]['r1']['whole'] + R[v]['r3']['whole']) / 2 for v in vals}
        b0 = (base['r1']['whole'] + base['r3']['whole']) / 2
        picks, d = [], []
        for i in range(len(YRS)):
            vb = max(vals, key=lambda v: np.delete(obj[v], i).mean()); picks.append(vb); d.append(obj[vb][i] - b0[i])
        g5 = []
        for i in range(len(R[vals[0]]['r5']['whole'])):
            o5 = {v: R[v]['r5']['whole'] for v in vals}
            vb = max(vals, key=lambda v: np.delete(o5[v], i).mean()); g5.append(o5[vb][i] - base['r5']['whole'][i])
        print(f'  LOYO picks {picks}  held-out gain season+3yr {np.mean(d):+.4f} ({sum(x > 1e-9 for x in d)}/8)'
              f'  5yr {np.mean(g5):+.4f} ({sum(x > 1e-9 for x in g5)}/{len(g5)})', flush=True)
    dyn_common.JM_COND.clear(); dyn_common.JM_COND.update(SHIP)


if __name__ == '__main__':
    main()
