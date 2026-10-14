#!/usr/bin/env python3
"""
research_age_value.py — how age and dynasty value relate (Jack 2026-10-09:
"can we also look at how age and value correlate?").

A  TODAY: KTC value by position x age (1QB, players KTC lists), and where the
   Dynasty SIM disagrees with KTC by age: within each position, log(sim rank /
   KTC rank) by age band (negative = the sim likes that age more than KTC).
B  HISTORY (FFC dynasty ADP pool 2016-23, 1QB PPR; backtest_value_score.build
   with the shipped conditional-JM sim): for each position x age band, how the
   players actually did vs where each order ranked them —
   mean log(realized rank / predicted rank) for 3yr VOR and 5yr + youth.
   Positive = that age band finished WORSE than ranked (overvalued), negative =
   better (undervalued). Orders: MARKET (ADP), SIM, FAIR (0.5 M3 + 0.3 sim +
   0.5 market). Ranks within the year's pool.
C  KTC's own aging (sim_lab/_dyn_cache/ktc_alltime.json, research_ktc_alltime
   section 3) is printed from that log for reference.
"""
import json
import math
import os
import re
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from backtest_value_score import build, YEARS, LAST  # noqa: E402

SITE = os.path.join(os.path.dirname(HERE), 'MyFantasyFootball Files', 'data')
BANDS = [('<=22', 0, 23), ('23', 23, 24), ('24', 24, 25), ('25', 25, 26), ('26', 26, 27), ('27', 27, 28), ('28-29', 28, 30), ('30+', 30, 99)]


def band(a):
    for lbl, lo, hi in BANDS:
        if lo <= a < hi:
            return lbl
    return None


def load_js_obj(path, var):
    s = open(path, encoding='utf-8').read()
    m = re.search(r'var ' + var + r'=(\{.*?\});', s, re.S)
    return json.loads(m.group(1))


def norm(n):
    return re.sub(r'\s+(jr\.?|sr\.?|iii|ii|iv|v)$', '', str(n).lower()).replace('.', '').replace("'", '').replace('-', '').strip()


def part_a():
    s = open(os.path.join(SITE, 'dynasty_sim_2026.js'), encoding='utf-8').read()
    S = json.loads(s[s.index('{'):s.rstrip().rstrip(';').rindex('}') + 1])['players']
    K = load_js_obj(os.path.join(SITE, '_bundle_lookups.js'), 'KTC_1QB')
    kn = {norm(k): v for k, v in K.items() if not re.match(r'^\d{4} ', k)}
    rows = []
    for e in S.values():
        if e['pos'] not in ('QB', 'RB', 'WR', 'TE') or e.get('age') is None or '1qb_ppr' not in e['v']:
            continue
        kv = kn.get(norm(e['n']))
        if kv:
            rows.append({'n': e['n'], 'pos': e['pos'], 'age': e['age'], 'kv': kv, 'sv': e['v']['1qb_ppr'][0]})
    print('=== A. TODAY (1QB PPR): KTC value by age, and SIM vs KTC by age ===')
    print('   median KTC value of the position\'s top players in each age band (n), then log(sim pos rank / KTC pos rank)')
    print(f'{"pos":<5}' + ''.join(f'{b[0]:>13}' for b in BANDS))
    for pos in ('QB', 'RB', 'WR', 'TE'):
        P = [r for r in rows if r['pos'] == pos]
        for i, r in enumerate(sorted(P, key=lambda r: -r['kv'])):
            r['kr'] = i + 1
        for i, r in enumerate(sorted(P, key=lambda r: -r['sv'])):
            r['sr'] = i + 1
        top = [r for r in P if r['kr'] <= {'QB': 32, 'RB': 48, 'WR': 72, 'TE': 24}[pos]]
        cells, gaps = [], []
        for lbl, lo, hi in BANDS:
            g = [r for r in top if lo <= r['age'] < hi]
            cells.append((f'{int(np.median([r["kv"] for r in g]))} ({len(g)})' if g else '—').rjust(13))
            gaps.append((f'{np.mean([math.log(r["sr"] / r["kr"]) for r in g]):+.2f}' if len(g) >= 3 else '—').rjust(13))
        print(f'{pos:<5}' + ''.join(cells))
        print(f'{"  gap":<5}' + ''.join(gaps))
    print('   gap < 0 = the sim ranks that age band higher than KTC does (sim likes them more)')


def part_b():
    recs = build(True)
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    for x in recs:
        a = x['age'] - 25.0; P = x['pos']
        m3 = c[0] + c[1] * math.log(x['m0']) + c[2] * math.log(x['s0']) + c[3] * x['rookie'] + (c[4] if P == 'RB' else 0) \
            + (c[5] if P == 'WR' else 0) + (c[6] if P == 'TE' else 0) + a * (c[7] if P == 'QB' else c[8] if P == 'RB' else c[9] if P == 'WR' else c[10])
        x['fz'] = 0.5 * m3 + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
    for Y in YEARS:
        ys = [x for x in recs if x['Y'] == Y]
        for i, x in enumerate(sorted(ys, key=lambda x: x['fz'])):
            x['f0'] = i + 1
    print('\n=== B. HISTORY 2016-23 (FFC pool): did each age band finish better or worse than it was ranked? ===')
    print('   mean log(realized rank / predicted rank): + = finished WORSE than ranked (overvalued), - = better (undervalued)')
    for truth, lbl in (('r_t3', 'next 3 seasons VOR'), ('r_lt', '5 seasons + youth')):
        print(f'\n-- truth: {lbl} --')
        print(f'{"pos / order":<16}' + ''.join(f'{b[0]:>9}' for b in BANDS))
        for pos in ('QB', 'RB', 'WR', 'TE', 'ALL'):
            for nm, key in (('MARKET', 'm0'), ('SIM', 's0'), ('FAIR', 'f0')):
                cells = []
                for blbl, lo, hi in BANDS:
                    g = [x for x in recs if (pos == 'ALL' or x['pos'] == pos) and lo <= x['age'] < hi and x.get(truth)]
                    if len(g) < 12:
                        cells.append(f'{"—":>9}'); continue
                    v = np.mean([math.log(x[truth] / x[key]) for x in g])
                    cells.append(f'{v:>+7.2f}' + ('*' if abs(v) / (np.std([math.log(x[truth] / x[key]) for x in g]) / math.sqrt(len(g))) >= 2 else ' ') + ' ')
                n = sum(1 for x in recs if (pos == 'ALL' or x['pos'] == pos) and x.get(truth))
                print(f'{(pos + " " + nm):<16}' + ''.join(cells) + (f'   n={n}' if nm == 'MARKET' else ''))
        print('   * = |t| >= 2')


def part_c():
    lg = os.path.join(HERE, '_dyn_cache', 'ktc_alltime_run1.log')
    if os.path.exists(lg):
        t = open(lg, encoding='utf-8', errors='replace').read()
        i = t.find('=== 3.')
        j = t.find('=== 4.')
        print('\n=== C. KTC\'s own aging (all-time history, research_ktc_alltime.py) ===')
        print(t[i:j].strip())


if __name__ == '__main__':
    part_a()
    part_b()
    part_c()
