#!/usr/bin/env python3
"""
research_grade_volume.py — do PFF film grades lead to increased volume?
(Jack 2026-10-09: "or does like pff film grades lead ito increased volume")

Pairs: player-season y -> y+1 (2019-24 -> 2020-25), same position.
Volume (season-to-date at his last game, ctx_features; PFF season files):
  WR/TE  target share, routes per game (PFF routes / games)
  RB     carry share, target share
Grade (season y, PFF): WR/TE route grade + offense grade; RB run grade +
offense grade (and receiving route grade).
1  VOLUME MODEL  vol_{y+1} ~ vol_y + z(grade) + age + draft capital + changed team,
   by position: does film predict volume GROWTH beyond current volume? (OLS t,
   per-season stability of the grade coefficient)
2  UNDERUSED HIGH-GRADERS  bottom-half volume, top-third grade vs bottom-half
   volume, bottom-third grade: share whose volume rose 25%+ next season,
   median volume change.
3  VALUE  FFC dynasty pool 2020-23 veterans: does grade x low volume (the
   underused high-grader) beat FAIR over 3 years? (log realized / FAIR rank)
"""
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

CACHE = r'E:\MyFantasyFootball\pbp_cache'
POSMAP = {'HB': 'RB', 'FB': 'RB'}


def load():
    V = defaultdict(dict)
    for y in range(2019, 2026):
        rc = pd.read_csv(os.path.join(CACHE, 'pff', f'pff_receiving_{y}.csv'))
        for r in rc.to_dict('records'):
            pos = POSMAP.get(r['position'], r['position'])
            if pos not in ('WR', 'TE', 'RB'):
                continue
            f = V[((_norm_name(r['player']), pos), y)]
            g = r['player_game_count'] or 0
            f.update({'routes': r['routes'] or 0, 'rpg': (r['routes'] or 0) / g if g else None, 'g_route': r['grades_pass_route'],
                      'g_off_rec': r['grades_offense'], 'team': r['team_name']})
        ru = pd.read_csv(os.path.join(CACHE, 'pff', f'pff_rushing_{y}.csv'))
        for r in ru.to_dict('records'):
            pos = POSMAP.get(r['position'], r['position'])
            if pos != 'RB':
                continue
            f = V[((_norm_name(r['player']), 'RB'), y)]
            f.update({'att': r['attempts'] or 0, 'g_run': r['grades_run'], 'g_off_rb': r['grades_offense'], 'team': r['team_name']})
    ctx = pd.read_parquet(os.path.join(HERE, 'ctx_features.parquet'))
    ctx['key'] = [(_norm_name(n), p) for n, p in zip(ctx['name'], ctx['pos'])]
    for r in ctx.sort_values(['year', 'wk']).groupby(['name', 'pos', 'year']).tail(1).to_dict('records'):
        f = V[(r['key'], int(r['year']))]
        f.update({'tgt_sh': r['tgt_sh'], 'car_sh': r['car_sh'], 'ctx_team': r['team']})
    return V


def main():
    V = load()
    w = World(2025)
    specs = {'WR': [('tgt_sh', 'target share'), ('rpg', 'routes / game')], 'TE': [('tgt_sh', 'target share'), ('rpg', 'routes / game')],
             'RB': [('car_sh', 'carry share'), ('tgt_sh', 'target share')]}
    grades = {'WR': ['g_route', 'g_off_rec'], 'TE': ['g_route', 'g_off_rec'], 'RB': ['g_run', 'g_off_rb', 'g_route']}
    print('=== 1. VOLUME MODEL: vol(y+1) ~ vol(y) + z(grade) + age + draft capital + changed team ===')
    print('   grade coef = change in next-season volume per 1 SD of grade, at the same current volume')
    out = {}
    for pos, vols in specs.items():
        for vk, vl in vols:
            for gk in grades[pos]:
                rows = []
                for (k, y), f in V.items():
                    if k[1] != pos or y > 2024:
                        continue
                    n = V.get((k, y + 1))
                    if not n or f.get(vk) is None or n.get(vk) is None or f.get(gk) is None:
                        continue
                    if isinstance(f[vk], float) and math.isnan(f[vk]) or isinstance(n[vk], float) and math.isnan(n[vk]):
                        continue
                    minw = (f.get('routes') or 0) >= 100 if pos in ('WR', 'TE') else (f.get('att') or 0) >= 40 or (f.get('routes') or 0) >= 100
                    if not minw:
                        continue
                    age = w.age(k, y + 1) if k in w.players else None
                    dr = (w.players.get(k) or {}).get('draft')
                    rows.append({'y': y, 'k': k, 'v0': f[vk], 'v1': n[vk], 'g': f[gk], 'age': age if age is not None else 26,
                                 'dc': -math.log(dr[1]) if dr and dr[1] else -math.log(262),
                                 'moved': float(bool(f.get('team')) and bool(n.get('team')) and f.get('team') != n.get('team'))})
                if len(rows) < 60:
                    continue
                g = np.array([r['g'] for r in rows], float); gz = (g - g.mean()) / (g.std() or 1)
                X = np.column_stack([np.ones(len(rows)), [r['v0'] for r in rows], gz, [r['age'] for r in rows], [r['dc'] for r in rows], [r['moved'] for r in rows]])
                yv = np.array([r['v1'] for r in rows], float)
                b = np.linalg.lstsq(X, yv, rcond=None)[0]
                res = yv - X @ b
                se = math.sqrt((res @ res) / (len(rows) - X.shape[1]) * np.linalg.inv(X.T @ X)[2, 2])
                per = []
                for y in range(2019, 2025):
                    ii = [i for i, r in enumerate(rows) if r['y'] == y]
                    if len(ii) >= 15:
                        per.append(np.linalg.lstsq(X[ii], yv[ii], rcond=None)[0][2])
                mean_v = float(np.mean(yv))
                print(f'   {pos} {vl:<14} {gk:<10} n {len(rows):>4}  grade coef {b[2]:+.4f} (t {b[2] / se:+.1f}) = {b[2] / mean_v * 100:+.1f}% of avg volume per SD'
                      f'  | positive in {sum(c > 0 for c in per)}/{len(per)} seasons')
                out[(pos, vk, gk)] = (rows, gz)

    print('\n=== 2. UNDERUSED HIGH-GRADERS: below-median volume; top-third vs bottom-third grade ===')
    for (pos, vk, gk), (rows, gz) in out.items():
        if gk not in ('g_route', 'g_run'):
            continue
        v0 = np.array([r['v0'] for r in rows]); med = np.median(v0)
        lo = [i for i in range(len(rows)) if v0[i] < med]
        if len(lo) < 30:
            continue
        gl = np.array([gz[i] for i in lo]); t1, t2 = np.percentile(gl, [33.3, 66.7])
        def stat(ids):
            ch = [(rows[i]['v1'] - rows[i]['v0']) / max(rows[i]['v0'], 1e-3) for i in ids]
            return np.mean([c >= 0.25 for c in ch]), float(np.median(ch)), len(ids)
        hi_ids = [i for i in lo if gz[i] >= t2]; lo_ids = [i for i in lo if gz[i] <= t1]
        a, b = stat(hi_ids), stat(lo_ids)
        print(f'   {pos} {vk:<8} by {gk:<8} high grade: volume up 25%+ {a[0]:.0%} (median {a[1]:+.0%}, n {a[2]})   low grade: {b[0]:.0%} (median {b[1]:+.0%}, n {b[2]})')

    # 3. value: underused high-graders vs FAIR
    from backtest_value_score import build
    from backtest_fair_retune_jm import m3_ship
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = [x for x in build(True) if 2020 <= x['Y'] <= 2023 and not x['rookie']]
    m3_ship(recs, c)
    for x in recs:
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
    for Y in range(2020, 2024):
        for i, x in enumerate(sorted([x for x in recs if x['Y'] == Y], key=lambda x: x['fz'])):
            x['f0'] = i + 1
    print('\n=== 3. VALUE: underused high-graders (prior season) vs FAIR — mean log(realized 3yr rank / FAIR rank), + = worse ===')
    for pos, vk, gk in (('WR', 'tgt_sh', 'g_route'), ('TE', 'tgt_sh', 'g_route'), ('RB', 'car_sh', 'g_run'), ('RB', 'tgt_sh', 'g_route')):
        pool = []
        for x in recs:
            if x['pos'] != pos:
                continue
            f = V.get((x['key'], x['Y'] - 1), {})
            if f.get(vk) is None or f.get(gk) is None or not x.get('r_t3'):
                continue
            pool.append((x, f[vk], f[gk]))
        if len(pool) < 30:
            continue
        vm = np.median([p[1] for p in pool]); gm = np.percentile([p[2] for p in pool], 66.7)
        under = [p[0] for p in pool if p[1] < vm and p[2] >= gm]
        rest = [p[0] for p in pool if not (p[1] < vm and p[2] >= gm)]
        m = lambda L: np.mean([math.log(x['r_t3'] / x['f0']) for x in L]) if L else float('nan')
        print(f'   {pos} (low {vk}, high {gk}): underused high-graders {m(under):+.2f} (n {len(under)})  vs everyone else {m(rest):+.2f} (n {len(rest)})')


if __name__ == '__main__':
    main()
