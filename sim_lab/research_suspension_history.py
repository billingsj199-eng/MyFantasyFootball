#!/usr/bin/env python3
"""
research_suspension_history.py — is the market's discount for suspensions
justified? (Jack 2026-10-09: "test the suspension history next"; follows the
admin OFF-FIELD flag + Suspended caution on the card.)

Suspensions: nflverse weekly rosters (pbp_cache/roster_weekly_2019..2025.parquet),
status_description_abbr R40 (Reserve/Suspended) or R30 (indefinite — Gordon,
Ridley's 2022 gambling ban). QB/RB/WR/TE only.
1  VALUE (FFC dynasty ADP pool 2020-23, shipped JM sim + FAIR): mean
   log(realized rank / predicted rank) for MARKET, SIM, FAIR — suspended in
   season Y (usually announced before ADP season) vs suspended in Y-1 / Y-2 vs
   everyone else; truths = season-Y VOR rank and 3-season VOR rank.
   + = finished WORSE than ranked.
2  MARKET PATH (KTC 1QB daily, today's top 150 — survivorship): excess KTC
   change vs same-position / +-25% value controls from Aug 1 of the suspension
   season to +90 / +180 / +365 days.
Tiny samples — descriptive, not a model input.
"""
import datetime as dt
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, FORMATS, _norm_name  # noqa: E402
from backtest_value_score import build  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
import research_injury_drift as RD  # noqa: E402

CACHE = r'E:\MyFantasyFootball\pbp_cache'


def suspensions():
    d = pd.concat([pd.read_parquet(os.path.join(CACHE, f'roster_weekly_{y}.parquet')) for y in range(2019, 2026)])
    x = d[d.status_description_abbr.isin(['R40', 'R30']) & d.position.isin(['QB', 'RB', 'WR', 'TE'])]
    S = defaultdict(dict)
    for (n, pos, yr), g in x.groupby(['full_name', 'position', 'season']):
        S[(_norm_name(n), pos)][int(yr)] = int(g.week.nunique())
    return S


def main():
    S = suspensions()
    print(f'{sum(len(v) for v in S.values())} suspension seasons (QB/RB/WR/TE, 2019-25), {len(S)} players')
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = [x for x in build(True) if 2020 <= x['Y'] <= 2023]
    m3_ship(recs, c)
    w = World(2025); w.rows(FORMATS['1qb'], 2025)
    for x in recs:
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
        x['v1'] = w.vor(x['key'], x['Y']) or 0.0
        h = S.get(x['key'], {})
        x['sus_now'] = h.get(x['Y'], 0)
        x['sus_prior'] = sum(h.get(y, 0) for y in (x['Y'] - 1, x['Y'] - 2))
    for Y in range(2020, 2024):
        ys = [x for x in recs if x['Y'] == Y]
        for key, f in (('f0', lambda x: x['fz']), ('r1', lambda x: -x['v1'])):
            for i, x in enumerate(sorted(ys, key=f)):
                x[key] = i + 1
    print('\n=== 1. VALUE: mean log(realized rank / predicted rank), + = finished worse than ranked ===')
    print(f'{"group":<34}{"n":>4}' + ''.join(f'{h:>12}' for h in ('MKT Y', 'SIM Y', 'FAIR Y', 'MKT 3y', 'SIM 3y', 'FAIR 3y')))
    for lbl, f in (('suspended this season', lambda x: x['sus_now'] > 0), ('suspended in the 2 seasons before', lambda x: x['sus_prior'] > 0),
                   ('never suspended (2019+)', lambda x: not x['sus_now'] and not x['sus_prior'])):
        g = [x for x in recs if f(x)]
        cells = []
        for tk in ('r1', 'r_t3'):
            for pk in ('m0', 's0', 'f0'):
                v = [math.log(x[tk] / x[pk]) for x in g if x.get(tk)]
                cells.append(f'{np.mean(v):+.2f}' if v else '—')
        print(f'{lbl:<34}{len(g):>4}' + ''.join(f'{c_:>12}' for c_ in cells))
    for x in sorted([x for x in recs if x['sus_now'] or x['sus_prior']], key=lambda x: (x['Y'], x['key'][0])):
        print(f'   {x["key"][0]:<20}{x["pos"]:<3}{x["Y"]} {"NOW " + str(x["sus_now"]) + "wk" if x["sus_now"] else "prior":<9} mkt #{x["m0"]:<4} sim #{x["s0"]:<4} '
              f'FAIR #{x["f0"]:<4} -> season-Y #{x["r1"]:<4} 3yr #{x.get("r_t3", "-")}')

    print('\n=== 2. MARKET PATH: KTC excess change from Aug 1 of the suspension season (vs same-pos +-25% controls) ===')
    K = json.load(open(os.path.join(HERE, '_dyn_cache', 'ktc_alltime.json'), encoding='utf-8'))['players']
    P = {}
    for n, rec in K.items():
        s_ = RD.series(rec)
        if len(s_[0]) > 60:
            P[(_norm_name(n), rec['pos'])] = s_
    sus_keys = {k for k in S}
    rows = []
    for key, yrs in S.items():
        if key not in P:
            continue
        for yr, wks in yrs.items():
            t0 = dt.date(yr, 8, 1)
            row = [key[0], yr, wks]
            for h in (90, 180, 365):
                t1 = t0 + dt.timedelta(days=h)
                if t1 > RD.TODAY:
                    row.append(None); continue
                v0, v1 = RD.val_at(P[key], t0), RD.val_at(P[key], t1)
                if not v0 or not v1:
                    row.append(None); continue
                ctl = []
                for k2, s2 in P.items():
                    if k2 == key or k2[1] != key[1] or k2 in sus_keys:
                        continue
                    a, b = RD.val_at(s2, t0), RD.val_at(s2, t1)
                    if a and b and 0.75 * v0 <= a <= 1.25 * v0:
                        ctl.append(math.log(b / a))
                row.append(math.log(v1 / v0) - float(np.median(ctl)) if len(ctl) >= 3 else None)
            rows.append(row)
    for r in sorted(rows, key=lambda r: r[1]):
        print(f'   {r[0]:<20}{r[1]} ({r[2]} wks)  ' + '  '.join(f'+{h}d {(math.exp(v) - 1) * 100:+5.0f}%' if v is not None else f'+{h}d    —' for h, v in zip((90, 180, 365), r[3:])))
    for i, h in enumerate((90, 180, 365)):
        vs = [r[3 + i] for r in rows if r[3 + i] is not None]
        if vs:
            print(f'   median +{h}d: {(math.exp(np.median(vs)) - 1) * 100:+.1f}% (n {len(vs)})')


if __name__ == '__main__':
    main()
