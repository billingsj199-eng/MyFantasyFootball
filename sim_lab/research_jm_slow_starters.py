#!/usr/bin/env python3
"""
research_jm_slow_starters.py — high-JM players who produce little early: do
they break out later, or does hype keep their value inflated? (Jack 2026-10-09)

Cohort: drafted QB/RB/WR/TE 2017-23 with a JM score. SLOW START = rookie
season PPR points per game below the position's replacement-starter rate
(rel < 1; rel from the World's 1QB replacement levels) or < 4 games.
JM bands: 75+ / 60-75 / <60. Pick bands as the control (JM ~ draft capital).

For each group (after year 1; and SLOW TWICE = years 1 and 2 both slow):
  1  BREAKOUT  share with a starter season later (QB/TE top-12, RB/WR top-24
     PPR points) in career yrs 2-4 (or 3-5), mean VOR over those years.
  2  vs SIM   the Dynasty SIM's production-only read at the next preseason
     (vet comps on the rookie season) vs what they actually did: mean
     (actual - predicted) VOR yrs 2-4 — positive = pedigree the sim misses.
  3  vs MARKET  FFC dynasty startup ADP at the next preseason: within-pool
     market rank vs realized rank (VOR yrs 2-4 among the same ADP pool) and
     vs the sim rank; median log(market rank / realized rank): negative = the
     market rated them better than they turned out (hype premium). Also the
     next year's market move (do they keep sliding?).
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS, _norm_name, DATA_DIR  # noqa: E402
from backtest_dynasty_inseason import ffc_adp  # noqa: E402

LAST_DATA = 2025
LL = (120, 5.0)
CLASSES = list(range(2017, 2024))
DROP = 250
TOPN = {'QB': 12, 'RB': 24, 'WR': 24, 'TE': 12}


def main():
    w = World(LAST_DATA)
    rows = w.rows(FORMATS['1qb'], LAST_DATA)
    comps = Comps(rows, LAST_DATA, {'QB': 6.0})
    idx = {(r['key'], r['Y']): r for r in rows}
    jm = json.load(open(os.path.join(DATA_DIR, 'jm_scores.json'), encoding='utf-8'))['scores']
    jmk = {(_norm_name(n), v['pos']): v['jm'] for n, v in jm.items() if v.get('jm') is not None}
    adp = {y: {(n, p): a for n, p, a in ffc_adp(y)} for y in range(2016, 2026)}

    # positional finish by season
    fin = {}
    for yr, d in w.pts.items():
        by = defaultdict(list)
        for k, v in d.items():
            by[k[1]].append((v, k))
        for pos, lst in by.items():
            for i, (v, k) in enumerate(sorted(lst, reverse=True)):
                fin[(k, yr)] = i + 1

    def starter(k, yr):
        return fin.get((k, yr), 999) <= TOPN[k[1]]

    # market + sim ranks per preseason year over the ADP pool
    mk, sm, real3 = {}, {}, {}
    for Y in range(2018, 2026):
        pool = [idx[(k, Y)] for k in adp.get(Y, {}) if (k, Y) in idx]
        for r in pool:
            if r['rookie']:
                ev = comps.ev(r['pos'], True, Comps.feat_rookie(r['pick'], r['age0']), Y, exclude_key=r['key'], local_linear=LL)
            else:
                ev = comps.ev(r['pos'], False, comps.feat_v(r['pos'], r['age0'], r['rel'], r['gp1']), Y, exclude_key=r['key'], local_linear=LL)
            r['_ev'] = ev
            r['_sim'] = sum(ev[:3]) + 1.5 * sum(ev[3:])
        for i, r in enumerate(sorted(pool, key=lambda r: adp[Y][r['key']])):
            mk[(r['key'], Y)] = i + 1
        for i, r in enumerate(sorted(pool, key=lambda r: -r['_sim'])):
            sm[(r['key'], Y)] = (i + 1, r['_ev'])
        if Y + 2 <= LAST_DATA:
            for i, r in enumerate(sorted(pool, key=lambda r: -sum(v or 0 for v in r['vor'][:3]))):
                real3[(r['key'], Y)] = i + 1

    P = []
    for key, dr in w.draft.items():
        Y = dr[0]
        if Y not in CLASSES or key not in jmk:
            continue
        g1 = (w.players[key]['by'].get(Y) or {}).get('gp') or 0
        r2 = idx.get((key, Y + 1))   # sophomore row: rel = rookie-year production vs replacement
        rel1 = r2['rel'] if r2 else 0.0
        g2 = (w.players[key]['by'].get(Y + 1) or {}).get('gp') or 0
        r3 = idx.get((key, Y + 2))
        P.append({'key': key, 'Y': Y, 'pos': key[1], 'pick': dr[1], 'jm': jmk[key], 'g1': g1, 'rel1': rel1,
                  'slow1': g1 < 4 or rel1 < 1.0, 'r2': r2, 'r3': r3, 'g2': g2,
                  'st1': starter(key, Y), 'st2': starter(key, Y + 1)})
    for p in P:
        p['slow2'] = p['slow1'] and not p['st2'] and (p['g2'] < 4 or (p['r3'] is not None and p['r3']['rel'] < 1.0) or p['r3'] is None)

    def jb(p):
        return 'JM 75+' if p['jm'] >= 75 else 'JM 60-75' if p['jm'] >= 60 else 'JM <60'

    def report(title, cohort, start_k, last_class):
        print(f'\n=== {title} ===')
        print(f'{"group":<22}{"n":>4}{"breakout":>10}{"VOR/yr":>8}{"sim pred":>10}{"act-pred":>10}'
              f'{"mkt n":>7}{"mkt/real":>10}{"sim/real":>10}{"mkt 1y move":>13}')
        groups = defaultdict(list)
        for p in cohort:
            if p['Y'] > last_class:
                continue
            groups[jb(p)].append(p)
            groups[('R1' if p['pick'] <= 32 else 'R2' if p['pick'] <= 64 else 'R3+') + ' pick'].append(p)
            groups[jb(p) + ' / ' + ('top-64' if p['pick'] <= 64 else '65+')].append(p)
            groups['ALL'].append(p)
        order = ['ALL', 'JM 75+', 'JM 60-75', 'JM <60', 'R1 pick', 'R2 pick', 'R3+ pick',
                 'JM 75+ / top-64', 'JM 60-75 / top-64', 'JM <60 / top-64', 'JM 60-75 / 65+', 'JM <60 / 65+']
        for g in order:
            lst = groups.get(g, [])
            if len(lst) < 5:
                continue
            bo = np.mean([any(starter(p['key'], p['Y'] + k) for k in range(start_k, start_k + 3)) for p in lst])
            vor = np.mean([np.mean([w.vor(p['key'], p['Y'] + k) or 0 for k in range(start_k, start_k + 3)]) for p in lst])
            Yq = lambda p: p['Y'] + start_k   # the preseason we judge from
            preds, diffs, lm, ls, mv = [], [], [], [], []
            for p in lst:
                y0 = Yq(p)
                s = sm.get((p['key'], y0))
                act = np.mean([w.vor(p['key'], y0 + k) or 0 for k in range(3)])
                if s:
                    pr = np.mean(s[1][:3]); preds.append(pr); diffs.append(act - pr)
                m = mk.get((p['key'], y0)); rr = real3.get((p['key'], y0))
                if m and rr:
                    lm.append(math.log(m / rr)); ls.append(math.log(s[0] / rr) if s else np.nan)
                    m1 = mk.get((p['key'], y0 + 1), DROP)
                    mv.append(math.log(m1 / m))
            f = lambda xs: f'{np.nanmedian(xs):+.2f}' if xs else '—'
            print(f'{g:<22}{len(lst):>4}{bo:>10.0%}{vor:>8.1f}{(np.mean(preds) if preds else float("nan")):>10.1f}'
                  f'{(np.mean(diffs) if diffs else float("nan")):>+10.1f}{len(lm):>7}{f(lm):>10}{f(ls):>10}'
                  + (f'{(math.exp(np.median(mv)) - 1) * 100:>+12.0f}%' if mv else f'{"—":>13}'))
        print('   breakout = a starter season (QB/TE top-12, RB/WR top-24) in the 3 seasons judged; VOR/yr = mean realized;'
              ' sim pred = production-only Dynasty SIM at that preseason; mkt/real & sim/real = median log(rank / realized rank)'
              ' in the FFC ADP pool (negative = rated better than they turned out); 1y move = median market-rank change over the next year'
              ' (rank up = negative %).')

    report('AFTER A SLOW ROOKIE YEAR -> career yrs 2-4 (classes 2017-22)', [p for p in P if p['slow1']], 1, 2022)
    report('FAST ROOKIE YEAR (reference) -> career yrs 2-4', [p for p in P if not p['slow1']], 1, 2022)
    report('SLOW YEARS 1 AND 2 -> career yrs 3-5 (classes 2017-21)', [p for p in P if p['slow2']], 2, 2021)

    print('\n=== Named: JM 75+ slow rookie years, what happened (yrs 2-4 finishes) ===')
    for p in sorted([p for p in P if p['slow1'] and p['jm'] >= 75 and p['Y'] <= 2022], key=lambda p: (p['Y'], p['pick'])):
        fs = [fin.get((p['key'], p['Y'] + k)) for k in range(0, 4)]
        print(f'   {p["key"][0]:<22}{p["pos"]:<4}{p["Y"]} pick {p["pick"]:>3} JM {p["jm"]:>5.1f} rel1 {p["rel1"]:.2f} g1 {p["g1"]:>2}  '
              f'finishes yr1-4: ' + ' '.join(f'{p["pos"]}{f}' if f else '—' for f in fs)
              + f'   mkt rank next pre: {mk.get((p["key"], p["Y"] + 1), "—")} -> {mk.get((p["key"], p["Y"] + 2), "—")}')


if __name__ == '__main__':
    main()
