#!/usr/bin/env python3
"""
backtest_dynasty_league.py — league-aware Dynasty SIM (Jack 2026-10-09:
"we can have the vor change with synced leagues").

The site can't rerun the comps for every synced league, so the generator would
ship each player's comps POINTS distribution (deciles, local-linear-shifted —
Comps.ev_dist) and the site prices VOR against the league's own replacement
level from a historical "n-th best at the position" table. This checks that
the client-side method ranks as well as a model trained per league.

For each league (starters per position = first non-starter at n+1):
  A  shipped approach trained for that league: local-linear on that league's VOR
  B  client approach: deciles of comps points (one model for every league) ->
     mean(max(0, q - r)), r = avg n+1-th best season pts over Y-5..Y-1
Truth: realized VOR with that league's per-season replacement. FFC pool
2015-2023, preseason, PPR, QB age 6, youth 1.5.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS  # noqa: E402
from backtest_dynasty_inseason import ffc_adp, evaluate, START_YEARS  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

LAST_DATA = 2025
LL = (120, 5.0)
AGE = {'QB': 6.0}
YW = 1.5
LEAGUES = {
    '12-team 1QB': {'QB': 12, 'RB': 30, 'WR': 42, 'TE': 12},
    '12-team SF':  {'QB': 24, 'RB': 30, 'WR': 42, 'TE': 12},
    '10-team 1QB': {'QB': 10, 'RB': 25, 'WR': 35, 'TE': 10},
    '14-team 1QB': {'QB': 14, 'RB': 35, 'WR': 49, 'TE': 14},
}


def main():
    w = World(LAST_DATA)
    base_rows = w.rows(FORMATS['1qb'], START_YEARS[-1])   # features normalised on the 12-team 1QB scale
    comps_b = Comps(base_rows, LAST_DATA, AGE)
    idx = {(r['key'], r['Y']): r for r in base_rows}
    pool = []
    for Y in START_YEARS:
        for name, pos, adp in ffc_adp(Y):
            r = idx.get(((name, pos), Y))
            if r:
                pool.append(dict(r, adp=adp))
    for r in pool:
        if r['rookie']:
            f = Comps.feat_rookie(r['pick'], r['age0'])
        else:
            f = comps_b.feat_v(r['pos'], r['age0'], r['rel'], r['gp1'])
        r['dist'] = comps_b.ev_dist(r['pos'], r['rookie'], f, r['Y'], exclude_key=r['key'], local_linear=LL)
        r['f'] = f
    tables = {Y: w.repl_table(range(Y - 5, Y)) for Y in START_YEARS}
    # H (hybrid): the shipped 12-team value per season, scaled by how the decile read
    # moves from the 12-team replacement to the league's: A12_k x B_L,k / B12_k.
    for r in pool:
        a12 = comps_b.ev(r['pos'], r['rookie'], r['f'], r['Y'], exclude_key=r['key'], local_linear=LL)
        rep12 = tables[r['Y']][r['pos']][LEAGUES['12-team 1QB'][r['pos']]]
        b12 = [Comps.vor_from_dist(q, rep12) for q in r['dist']]
        r['a12'], r['b12'] = a12, b12
    y5 = [y for y in START_YEARS if y + 4 <= LAST_DATA]
    print(f'{"league":<14}{"method":<26}{"T3 Sp":>7}{"top36":>8}{"T5 Sp":>7}{"top36":>8}{"corr A,B":>10}')
    for lg, st in LEAGUES.items():
        rows_l = w.rows(st, START_YEARS[-1])                # sets w._repl for this league's truth
        comps_a = Comps(rows_l, LAST_DATA, AGE)
        il = {(r['key'], r['Y']): r for r in rows_l}
        for r in pool:
            rl = il.get((r['key'], r['Y']))
            r['t3'] = sum(v or 0 for v in rl['vor'][:3]); r['t5'] = sum(v or 0 for v in rl['vor'][:5])
            fa = Comps.feat_rookie(r['pick'], r['age0']) if r['rookie'] else comps_a.feat_v(r['pos'], r['age0'], rl['rel'], rl['gp1'])
            ev = comps_a.ev(r['pos'], r['rookie'], fa, r['Y'], exclude_key=r['key'], local_linear=LL)
            r['A3'], r['A5'] = sum(ev[:3]), sum(ev[:3]) + YW * sum(ev[3:])
            rep = tables[r['Y']][r['pos']][st[r['pos']]]          # (n+1)-th best = index n
            vb = [Comps.vor_from_dist(q, rep) for q in r['dist']]
            r['B3'], r['B5'] = sum(vb[:3]), sum(vb[:3]) + YW * sum(vb[3:])
            # hybrid: scale the 12-team value; where the 12-team decile read is ~0
            # (deep players) fall back to the decile read itself
            vh = [a * (b / b12) if b12 > 1.0 else b for a, b, b12 in zip(r['a12'], vb, r['b12'])]
            r['H3'], r['H5'] = sum(vh[:3]), sum(vh[:3]) + YW * sum(vh[3:])
        p5 = [r for r in pool if r['Y'] in y5]
        for lbl, k3, k5 in (('A trained for the league', 'A3', 'A5'), ('B client-side (quintiles)', 'B3', 'B5'),
                            ('H hybrid (12-team x ratio)', 'H3', 'H5')):
            a = evaluate(pool, lambda r, k=k3: r[k], lambda r: r['t3'])
            b = evaluate(p5, lambda r, k=k5: r[k], lambda r: r['t5'])
            c = spearman([r['A5'] for r in pool], [r[k5] for r in pool]) if not lbl.startswith('A') else None
            print(f'{lg:<14}{lbl:<26}{a[0]:>7.3f}{a[1]*100:>7.1f}%{b[0]:>7.3f}{b[1]*100:>7.1f}%'
                  + (f'{c:>10.3f}' if c is not None else ''))


if __name__ == '__main__':
    main()
