#!/usr/bin/env python3
"""
research_athletic_aging.py — do athletic players age better, and is it priced?
(Jack 2026-10-09: "test athleticism and aging first")

Athleticism: data/combine_data.js (COMBINE_DATA, 1987-2026): RAS (0-10, size-
adjusted composite), 40 time, weight; matched to the season DB by name with the
combine year within 1 of the draft year (name-only collisions dropped).
1  AGING CURVES (2000-25): per position x age, year-over-year change in PPG
   (both seasons 8+ games; log ratio, median) and the COLLAPSE rate (next season
   below replacement level or out), by RAS tercile (within position).
2  VALUE (FFC dynasty pool 2016-23, shipped JM sim + FAIR): older veterans
   (WR 27+, RB 25+, TE 28+, QB 30+): mean log(realized 3yr rank / predicted rank)
   by RAS tercile for MARKET / SIM / FAIR (+ = finished worse than ranked), and
   the beyond-FAIR coefficient of z(RAS) x (age over the threshold), bootstrap.
3  LOYO: FAIR + k * z(RAS) * years-over-threshold, k fit on 7 seasons, scored on
   the 8th vs shipped FAIR.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, FORMATS, DATA_DIR, _norm_name, season_rel  # noqa: E402
from backtest_value_score import build, YEARS  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

THRESH = {'WR': 27, 'RB': 25, 'TE': 28, 'QB': 30}


def load_combine(w):
    s = open(os.path.join(DATA_DIR, 'combine_data.js'), encoding='utf-8').read()
    d, _ = json.JSONDecoder().raw_decode(s, s.index('{'))
    byname = defaultdict(list)
    for n, v in d.items():
        byname[_norm_name(n)].append(v)
    out = {}
    for key, P in w.players.items():
        cands = byname.get(key[0], [])
        dr = P.get('draft')
        if dr:
            cands = [c for c in cands if c.get('yr') and abs(c['yr'] - dr[0]) <= 1]
        if len(cands) != 1:
            continue
        c = cands[0]
        if c.get('ras') is not None:
            out[key] = {'ras': c['ras'], 'forty': c.get('forty'), 'wt': c.get('wt')}
    return out


def main():
    w = World(2025)
    w.rows(FORMATS['1qb'], 2025)
    C = load_combine(w)
    print(f'athleticism matched for {len(C)} players (by position: '
          + ', '.join(f'{p} {sum(1 for k in C if k[1] == p)}' for p in ('QB', 'RB', 'WR', 'TE')) + ')')
    # terciles of RAS within position
    terc = {}
    for pos in ('QB', 'RB', 'WR', 'TE'):
        vals = sorted(v['ras'] for k, v in C.items() if k[1] == pos)
        if vals:
            terc[pos] = (vals[len(vals) // 3], vals[2 * len(vals) // 3])

    def tier(key):
        c = C.get(key)
        if not c or key[1] not in terc:
            return None
        a, b = terc[key[1]]
        return 'low' if c['ras'] < a else 'high' if c['ras'] >= b else 'mid'

    print('\n=== 1. AGING CURVES 2000-25: median year-over-year PPG change (both seasons 8+ games) | collapse rate next season ===')
    bands = {'QB': [(28, 30), (31, 33), (34, 36), (37, 40)], 'RB': [(24, 25), (26, 27), (28, 29), (30, 33)],
             'WR': [(25, 26), (27, 28), (29, 30), (31, 34)], 'TE': [(26, 27), (28, 29), (30, 31), (32, 35)]}
    for pos, bl in bands.items():
        print(f'  {pos}: ' + ' | '.join(f'age {a}-{b}' for a, b in bl))
        for t in ('high', 'mid', 'low'):
            cells = []
            for a, b in bl:
                ch, col = [], []
                for key in C:
                    if key[1] != pos or tier(key) != t:
                        continue
                    for yr in range(2000, 2025):
                        age = w.age(key, yr)
                        if age is None or not (a <= age <= b):
                            continue
                        g0, r0 = season_rel(w, key, yr)
                        if g0 < 8 or r0 < 0.7:
                            continue
                        g1, r1 = season_rel(w, key, yr + 1)
                        col.append(1.0 if (g1 < 4 or r1 < 0.7) else 0.0)
                        if g1 >= 8 and r1 > 0:
                            ch.append(math.log(r1 / r0))
                cells.append(f'{(math.exp(np.median(ch)) - 1) * 100:+4.0f}% / {np.mean(col) * 100:3.0f}% (n{len(col):>3})' if len(col) >= 12 else f'{"—":>22}')
            print(f'    {t:<5} RAS ' + ' | '.join(cells))
    print('   (PPG change among those still playing 8+ games; collapse = under 4 games or below 70% of a replacement starter next season)')

    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = build(True)
    m3_ship(recs, c)
    for x in recs:
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
    for Y in YEARS:
        for i, x in enumerate(sorted([x for x in recs if x['Y'] == Y], key=lambda x: x['fz'])):
            x['f0'] = i + 1
    old = [x for x in recs if not x['rookie'] and x['age'] >= THRESH[x['pos']] and x['key'] in C and x.get('r_t3')]
    print(f'\n=== 2. VALUE: older veterans in the FFC pool 2016-23 (n {len(old)}), by RAS tercile ===')
    print(f'{"group":<12}{"n":>5}{"MARKET":>9}{"SIM":>9}{"FAIR":>9}{"FAIR 5y+":>10}   (mean log realized / predicted rank, + = worse)')
    for t in ('high', 'mid', 'low'):
        g = [x for x in old if tier(x['key']) == t]
        m = lambda pk, tk='r_t3': np.mean([math.log(x[tk] / x[pk]) for x in g if x.get(tk)]) if g else float('nan')
        print(f'{t + " RAS":<12}{len(g):>5}{m("m0"):>+9.2f}{m("s0"):>+9.2f}{m("f0"):>+9.2f}{m("f0", "r_lt"):>+10.2f}')
    for pos in ('WR', 'RB', 'TE', 'QB'):
        row = []
        for t in ('high', 'low'):
            g = [x for x in old if x['pos'] == pos and tier(x['key']) == t]
            row.append(f'{t} {np.mean([math.log(x["r_t3"] / x["f0"]) for x in g]):+.2f} (n {len(g)})' if len(g) >= 6 else f'{t} —')
        print(f'   {pos} vs FAIR: ' + '   '.join(row))
    # interaction term: z(RAS within pos) x years over threshold
    allr = [x for x in recs if x['key'] in C and not x['rookie']]
    zr = {}
    for pos in ('QB', 'RB', 'WR', 'TE'):
        v = np.array([C[x['key']]['ras'] for x in allr if x['pos'] == pos])
        if len(v):
            zr[pos] = (v.mean(), v.std() or 1)
    for x in recs:
        if x['key'] in C and not x['rookie'] and x['pos'] in zr:
            mu, sd = zr[x['pos']]
            x['ia'] = (C[x['key']]['ras'] - mu) / sd * max(0.0, x['age'] - THRESH[x['pos']])
        else:
            x['ia'] = 0.0
    g = [x for x in recs if x.get('r_t3')]
    X = np.column_stack([np.ones(len(g)), [math.log(x['f0']) for x in g], [x['ia'] for x in g]])
    yv = np.array([math.log(x['r_t3']) for x in g])
    b = np.linalg.lstsq(X, yv, rcond=None)[0][2]
    keys = np.array([hash(x['key']) for x in g]); uk = np.unique(keys); byk = {k: np.where(keys == k)[0] for k in uk}
    rng = np.random.default_rng(3); bs = []
    for _ in range(300):
        ii = np.concatenate([byk[k] for k in rng.choice(uk, len(uk))])
        bs.append(np.linalg.lstsq(X[ii], yv[ii], rcond=None)[0][2])
    lo, hi = np.percentile(bs, [2.5, 97.5])
    print(f'   beyond FAIR, z(RAS) x years over the age threshold: {b:+.3f} [{lo:+.3f},{hi:+.3f}]  (< 0 = athletic veterans beat FAIR as they age)')

    print('\n=== 3. LOYO: FAIR + k * z(RAS) * years-over-threshold ===')
    d3, d5, ks = [], [], []
    for Y in YEARS:
        tr = [x for x in recs if x['Y'] != Y and x.get('r_t3')]; te = [x for x in recs if x['Y'] == Y]
        X = np.column_stack([np.ones(len(tr)), [math.log(x['f0']) for x in tr], [x['ia'] for x in tr]])
        k = min(0.0, np.linalg.lstsq(X, np.array([math.log(x['r_t3']) for x in tr]), rcond=None)[0][2]); ks.append(round(float(k), 3))
        for tk, dd in (('r_t3', d3), ('r_lt', d5)):
            xs = [x for x in te if x.get(tk)]
            if len(xs) >= 20:
                dd.append(spearman([-(math.log(x['f0']) + k * x['ia']) for x in xs], [-x[tk] for x in xs]) - spearman([-math.log(x['f0']) for x in xs], [-x[tk] for x in xs]))
    print(f'   k per fold {ks}; held-out vs FAIR: 3yr {np.mean(d3):+.4f} (wins {sum(v > 1e-9 for v in d3)}/{len(d3)}), 5yr+youth {np.mean(d5):+.4f} (wins {sum(v > 1e-9 for v in d5)}/{len(d5)})')


if __name__ == '__main__':
    main()
