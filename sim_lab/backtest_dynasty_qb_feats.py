#!/usr/bin/env python3
"""
backtest_dynasty_qb_feats.py — better QB comparables for the Dynasty SIM
(Jack 2026-10-09: "run the QB test"; backtest_fair_sf.py: the sim ranks SF QBs
worse than the market, QB 3yr Spearman .333 vs KTC .440).

Veteran QB comps today match on (age / 6, log production vs replacement / .15,
last-season games / 10). Candidates add:
  RUSH   share of fantasy production from rushing (the row's `rush`, / s)
  DC     draft capital, -log(NFL pick) / s (undrafted = pick 262) — team
         investment / job security
SF lineup (QB24 replacement) and 1QB both run; local-linear comps (120, ridge
5), time-honest, leave-the-player-out — same machinery as the shipped sim.
QB-only scores (per-year Spearman within QBs, averaged):
  A  FFC dynasty ADP QBs 2016-23 (veterans): truth = realized VOR over Y..Y+2
     (and Y..Y+4 + youth for Y <= 2021); market = FFC ADP order among QBs
  B  KTC SF survivor pool 2021-23 (backtest_fair_sf.py's pool): QB 3yr
"""
import datetime as dt
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS, _norm_name  # noqa: E402
from backtest_dynasty_inseason import ffc_adp  # noqa: E402
from backtest_js_model import spearman  # noqa: E402
import research_injury_drift as RD  # noqa: E402

LL = (120, 5.0)
LAST = 2025
YW = 1.5


def variants():
    v = [('BASE (age, prod, games)', None, None)]
    for rs in (0.10, 0.20):
        v.append((f'+ RUSH (scale {rs})', rs, None))
    for ds in (0.7, 1.5):
        v.append((f'+ DC (scale {ds})', None, ds))
    for rs, ds in ((0.10, 0.7), (0.10, 1.5), (0.20, 1.5)):
        v.append((f'+ RUSH {rs} + DC {ds}', rs, ds))
    return v


def run(fmt):
    w = World(LAST)
    rows = w.rows(FORMATS[fmt], LAST)
    comps = Comps(rows, LAST, {'QB': 6.0})
    Yv, feats0, vm, keys, lst = comps.G[('QB', False)]
    pick = lambda k: (w.players[k]['draft'] or (None, 262))[1] or 262
    rush = np.array([r.get('rush', 0.0) or 0.0 for r in lst]); dc = np.array([-math.log(pick(r['key'])) for r in lst])
    idx = {(r['key'], r['Y']): r for r in rows if r['pos'] == 'QB' and not r['rookie']}

    def ev_for(r, rs, ds):
        f0 = comps.feat_v('QB', r['age0'], r['rel'], r['gp1'])
        cols, f = [feats0], [f0]
        if rs:
            cols.append((rush / rs)[:, None]); f.append(np.array([(r.get('rush') or 0.0) / rs]))
        if ds:
            cols.append((dc / ds)[:, None]); f.append(np.array([-math.log(pick(r['key'])) / ds]))
        comps.G[('QB', False)] = (Yv, np.hstack(cols), vm, keys, lst)
        ev = comps.ev('QB', False, np.concatenate(f), r['Y'], exclude_key=r['key'], local_linear=LL)
        comps.G[('QB', False)] = (Yv, feats0, vm, keys, lst)
        return ev

    # A: FFC ADP QBs (veterans) 2016-23
    A = []
    for Y in range(2016, 2024):
        qs = [(a, (n, p)) for n, p, a in ffc_adp(Y) if p == 'QB' and ((n, p), Y) in idx]
        for i, (a, k) in enumerate(sorted(qs)):
            r = idx[(k, Y)]
            A.append({'r': r, 'Y': Y, 'mk': i + 1, 't3': sum((w.vor(k, Y + j) or 0) for j in range(3)),
                      't5': (sum((w.vor(k, Y + j) or 0) for j in range(3)) + YW * sum((w.vor(k, Y + j) or 0) for j in (3, 4))) if Y + 4 <= LAST else None})
    # B: KTC SF survivor pool QBs 2021-23
    K = json.load(open(os.path.join(HERE, '_dyn_cache', 'ktc_alltime.json'), encoding='utf-8'))['players']
    B = []
    for n, rec in K.items():
        if rec['pos'] != 'QB':
            continue
        o = rec.get('superflex') or {}
        pts = sorted((dt.date(2000 + int(d[:2]), int(d[2:4]), int(d[4:6])), v) for d, v in zip(o.get('d', []), o.get('v', [])) if v)
        if not pts:
            continue
        S = ([p[0] for p in pts], [p[1] for p in pts])
        k = (_norm_name(n), 'QB')
        for Y in (2021, 2022, 2023):
            v = RD.val_at(S, dt.date(Y, 8, 1))
            if v and (k, Y) in idx:
                B.append({'r': idx[(k, Y)], 'Y': Y, 'kv': v, 't3': sum((w.vor(k, Y + j) or 0) for j in range(3))})

    def per_year(rows_, f, tk):
        out = []
        for Y in sorted({x['Y'] for x in rows_}):
            xs = [x for x in rows_ if x['Y'] == Y and x[tk] is not None]
            if len(xs) >= 8:
                out.append(spearman([f(x) for x in xs], [x[tk] for x in xs]))
        return float(np.mean(out)) if out else float('nan'), len(out)

    print(f'\n===== {fmt.upper()} lineup — QB-only per-year Spearman =====')
    print(f'{"variant":<30}{"A: 3yr":>9}{"A: 5yr+y":>10}{"A: 50/50 w mkt":>16}{"B: KTC-SF 3yr":>15}')
    s3, _ = per_year(A, lambda x: -x['mk'], 't3'); s5, _ = per_year(A, lambda x: -x['mk'], 't5'); sb, _ = per_year(B, lambda x: x['kv'], 't3')
    print(f'{"MARKET (FFC ADP / KTC SF)":<30}{s3:>9.3f}{s5:>10.3f}{"":>16}{sb:>15.3f}')
    for lbl, rs, ds in variants():
        for x in A + B:
            ev = ev_for(x['r'], rs, ds)
            x['sim'] = sum(ev[:3]) + YW * sum(ev[3:])
        for Y in sorted({x['Y'] for x in A}):
            xs = [x for x in A if x['Y'] == Y]
            for i, x in enumerate(sorted(xs, key=lambda x: -x['sim'])):
                x['sr'] = i + 1
        a3, n3 = per_year(A, lambda x: x['sim'], 't3'); a5, _ = per_year(A, lambda x: x['sim'], 't5')
        ab, _ = per_year(A, lambda x: -(math.log(x['sr']) + math.log(x['mk'])), 't3')
        b3, _ = per_year(B, lambda x: x['sim'], 't3')
        print(f'{lbl:<30}{a3:>9.3f}{a5:>10.3f}{ab:>16.3f}{b3:>15.3f}')
    print(f'   A: {len(A)} QB-seasons ({n3} years); B: {len(B)} QB-seasons')


if __name__ == '__main__':
    run('sf')
    run('1qb')
