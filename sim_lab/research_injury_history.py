#!/usr/bin/env python3
"""
research_injury_history.py — does a player's overall injury history matter for
dynasty value? (Jack 2026-10-09: "what about a players overall injury history"
-> "yes run both")

Injury records: data/injury_history.js (nflverse 2009-2025; per player-season
injury, weeksMissed, major, seasonEnder). History features entering season Y
(seasons Y-3..Y-1): number of injury seasons, weeks missed, major injuries,
soft-tissue injuries (hamstring / groin / calf / quad), any prior major
(knee / ACL / Achilles ...) ever; plus games-played share over the 3 seasons
from the season DB.

1  LONG-TERM (FFC dynasty ADP pool 2016-23, 1QB PPR, veterans only, shipped
   conditional-JM sim): mean log(realized rank / predicted rank) for MARKET,
   SIM, FAIR by history bucket (+ = finished worse than ranked); then a FAIR
   term k * feature chosen leave-one-year-out (as backtest_fair_age_terms.py).
2  MARKET TIMING: the injury-slide events (research_injury_drift.py, regulars,
   LONG + SEASON-ENDING) split by prior history (an injury season in the 2
   seasons before vs none): excess KTC drift +30 / +90 / +180 / +365 days.
"""
import datetime as dt
import json
import math
import os
import re
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import _norm_name, DATA_DIR  # noqa: E402
from backtest_value_score import build, YEARS  # noqa: E402
from backtest_fair_retune_jm import scorer, m3_ship  # noqa: E402
import research_injury_drift as RD  # noqa: E402

SOFT = re.compile(r'hamstring|groin|calf|quad|adductor|abdom|oblique', re.I)


def load_history():
    s = open(os.path.join(DATA_DIR, 'injury_history.js'), encoding='latin-1').read()
    H = defaultdict(list)
    for m in re.finditer(r'INJURY_HISTORY\["(.+?)"\]\s*=\s*(\[.*?\]);', s):
        body = re.sub(r'(\{|,)\s*([A-Za-z]+)\s*:', r'\1"\2":', m.group(2))
        try:
            H[_norm_name(m.group(1))] = json.loads(body)
        except Exception:
            pass
    return H


def feats(H, name, Y, by):
    recs = [r for r in H.get(name, []) if Y - 3 <= r['season'] <= Y - 1]
    allprev = [r for r in H.get(name, []) if r['season'] <= Y - 1]
    gp = sum(min((by.get(y) or {}).get('gp') or 0, 17) for y in range(Y - 3, Y))
    yrs = sum(1 for y in range(Y - 3, Y) if by.get(y))
    return {'inj_seasons': len({r['season'] for r in recs}), 'wk_missed': sum(r.get('weeksMissed') or 0 for r in recs),
            'major3': sum(1 for r in recs if r.get('major')), 'soft3': sum(1 for r in recs if SOFT.search(r.get('injury') or '')),
            'major_ever': float(any(r.get('major') for r in allprev)), 'gp_share': gp / (17.0 * yrs) if yrs else None, 'yrs': yrs}


def part1(H):
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = build(True)
    m3_ship(recs, c)
    from dyn_common import World
    w = World(2025)
    for x in recs:
        x['z0'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
        by = (w.players.get(x['key']) or {}).get('by', {})
        x.update(feats(H, x['key'][0], x['Y'], by))
    for Y in YEARS:
        ys = [x for x in recs if x['Y'] == Y]
        for i, x in enumerate(sorted(ys, key=lambda x: x['z0'])):
            x['f0'] = i + 1
    vets = [x for x in recs if not x['rookie'] and x['yrs'] >= 2]
    print(f'=== 1. LONG-TERM: veterans with 2+ prior seasons, n={len(vets)} player-seasons 2016-23 ===')
    print('   mean log(realized rank / predicted rank): + = finished WORSE than ranked (history under-priced)')
    buckets = [('clean (no injury season)', lambda x: x['inj_seasons'] == 0),
               ('1 injury season', lambda x: x['inj_seasons'] == 1),
               ('2-3 injury seasons', lambda x: x['inj_seasons'] >= 2),
               ('8+ weeks missed (3 yrs)', lambda x: x['wk_missed'] >= 8),
               ('2+ soft-tissue', lambda x: x['soft3'] >= 2),
               ('major injury in 3 yrs', lambda x: x['major3'] >= 1),
               ('games share < 75%', lambda x: x['gp_share'] is not None and x['gp_share'] < 0.75),
               ('games share >= 95%', lambda x: x['gp_share'] is not None and x['gp_share'] >= 0.95)]
    for truth, tl in (('r_t3', 'next 3 seasons'), ('r_lt', '5 seasons + youth')):
        print(f'\n-- truth: {tl} --')
        print(f'{"bucket":<28}{"n":>5}{"MARKET":>9}{"SIM":>9}{"FAIR":>9}')
        for lbl, f in buckets:
            g = [x for x in vets if f(x) and x.get(truth)]
            if len(g) < 15:
                continue
            cells = []
            for key in ('m0', 's0', 'f0'):
                v = [math.log(x[truth] / x[key]) for x in g]
                m = np.mean(v); t = m / (np.std(v) / math.sqrt(len(v)))
                cells.append(f'{m:>+7.2f}{"*" if abs(t) >= 2 else " "} ')
            print(f'{lbl:<28}{len(g):>5}' + ''.join(cells))
        print('   * = |t| >= 2')

    print('\n-- by position (FAIR, 5 seasons + youth): 2+ injury seasons vs clean --')
    for pos in ('QB', 'RB', 'WR', 'TE'):
        row = []
        for lbl, f in (('clean', lambda x: x['inj_seasons'] == 0), ('2+ inj', lambda x: x['inj_seasons'] >= 2)):
            g = [x for x in vets if x['pos'] == pos and f(x) and x.get('r_lt')]
            row.append(f'{lbl} {np.mean([math.log(x["r_lt"] / x["f0"]) for x in g]):+.2f} (n {len(g)})' if len(g) >= 8 else f'{lbl} —')
        print(f'   {pos}: ' + '   '.join(row))

    # LOYO FAIR term
    score = scorer(recs)
    for x in recs:
        x['h_seasons'] = float(x.get('inj_seasons') or 0) if not x['rookie'] else 0.0
        x['h_wk'] = min(float(x.get('wk_missed') or 0), 20.0) / 10.0 if not x['rookie'] else 0.0
        x['h_gp'] = (1.0 - x['gp_share']) if (not x['rookie'] and x.get('gp_share') is not None) else 0.0
    grid = (-0.2, -0.1, -0.05, 0.0, 0.05, 0.1, 0.2, 0.3)

    def order(feat, k):
        return lambda x: -(x['z0'] + k * x[feat])
    print('\n=== FAIR + k * injury-history feature, k chosen leave-one-year-out ===')
    base = {Y: score(order('h_seasons', 0.0), [Y])['avg'] for Y in YEARS}
    for feat, lbl in (('h_seasons', 'injury seasons (0-3)'), ('h_wk', 'weeks missed /10 (cap 2)'), ('h_gp', 'share of games missed')):
        ins = max(grid, key=lambda k: score(order(feat, k))['avg'])
        wins, deltas, ks = 0, [], []
        for Y in YEARS:
            tr = [y for y in YEARS if y != Y]
            k = max(grid, key=lambda k: score(order(feat, k), tr)['avg'])
            ks.append(k)
            d = score(order(feat, k), [Y])['avg'] - base[Y]
            deltas.append(d); wins += d > 1e-9
        print(f'   {lbl:<28} in-sample best k {ins:+.2f} ({score(order(feat, ins))["avg"] - score(order(feat, 0))["avg"]:+.4f})'
              f' | LOYO {np.mean(deltas):+.4f}, wins {wins}/{len(YEARS)}, k {min(ks):+.2f}..{max(ks):+.2f}')


def part2(H):
    w = RD.World(2026)
    K = json.load(open(os.path.join(HERE, '_dyn_cache', 'ktc_alltime.json'), encoding='utf-8'))['players']
    P = {}
    for n, rec in K.items():
        S = RD.series(rec)
        if len(S[0]) > 60:
            P[(_norm_name(n), rec['pos'])] = S
    ev = []
    for key in P:
        for Y, lst in w.weekly.get(key, {}).items():
            if Y not in RD.KICKOFF:
                continue
            wks = sorted(wk for wk, _ in lst)
            for i, wk in enumerate(wks):
                if wk > 15:
                    break
                nxt = wks[i + 1] if i + 1 < len(wks) else None
                gap = (nxt - wk - 1) if nxt else (RD.LAST_WEEK[Y] - wk)
                if gap < 4 or sum(1 for x in wks if wk - 3 <= x <= wk) < 3:
                    continue
                t0 = RD.KICKOFF[Y] + dt.timedelta(days=7 * (wk - 1) + 5)
                if t0 > RD.TODAY - dt.timedelta(days=7):
                    continue
                prior = [r for r in H.get(key[0], []) if Y - 2 <= r['season'] <= Y - 1]
                ev.append({'key': key, 't0': t0, 'prone': bool(prior)})
    evdays = defaultdict(list)
    for e in ev:
        evdays[e['key']].append(e['t0'])

    def change(key, a, b):
        va, vb = RD.val_at(P[key], a), RD.val_at(P[key], b)
        return math.log(vb / va) if va and vb else None

    def excess(e, h):
        c = change(e['key'], e['t0'], e['t0'] + dt.timedelta(days=h))
        if c is None:
            return None
        v0 = RD.val_at(P[e['key']], e['t0'])
        ctl = []
        for k2, S in P.items():
            if k2 == e['key'] or k2[1] != e['key'][1]:
                continue
            v = RD.val_at(S, e['t0'])
            if not v or not (0.75 * v0 <= v <= 1.25 * v0) or any(-21 <= (d - e['t0']).days <= h for d in evdays.get(k2, ())):
                continue
            cc = change(k2, e['t0'], e['t0'] + dt.timedelta(days=h))
            if cc is not None:
                ctl.append(cc)
        return c - float(np.median(ctl)) if len(ctl) >= 3 else None
    print('\n=== 2. MARKET TIMING: KTC excess drift after a 4+ week absence (regulars), by prior injury history ===')
    print(f'{"group":<34}' + ''.join(f'{"+" + str(h) + "d":>14}' for h in (30, 90, 180, 365)))
    for lbl, f in (('injury in the 2 seasons before', lambda e: e['prone']), ('no injury in the 2 seasons before', lambda e: not e['prone'])):
        cells = []
        for h in (30, 90, 180, 365):
            xs = [x for x in (excess(e, h) for e in ev if f(e) and e['t0'] + dt.timedelta(days=h) <= RD.TODAY) if x is not None]
            if xs:
                m = float(np.median(xs)); se = 1.253 * np.std(xs) / math.sqrt(len(xs))
                cells.append(f'{(math.exp(m) - 1) * 100:+.1f}%{"*" if se and abs(m / se) >= 2 else " "}({len(xs)})')
            else:
                cells.append('—')
        print(f'{lbl:<34}' + ''.join(f'{c:>14}' for c in cells))
    print('   * = |median / se| >= 2; same controls as research_injury_drift.py')


if __name__ == '__main__':
    H = load_history()
    print(f'injury history: {len(H)} players, {sum(len(v) for v in H.values())} injury-seasons')
    part1(H)
    part2(H)
