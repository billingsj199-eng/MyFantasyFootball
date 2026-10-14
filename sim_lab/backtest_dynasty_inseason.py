#!/usr/bin/env python3
"""
backtest_dynasty_inseason.py — fold the current season's games into Dynasty SIM.

Jack 2026-10-09: "fold the 2026 games into the inputs first".

Valuation point = after week W of season Y (2026 today: W=4). Truth:
    T3 = VOR(rest of Y, weeks W+1..18) + VOR(Y+1) + VOR(Y+2)
    T5 = T3 + VOR(Y+3) + VOR(Y+4)
rest-of-season VOR = max(0, rest pts - replacement season pts x (18-W)/18).

Model = the prototype's comparables (dyn_common), year-0 scaled by (18-W)/18:
  vets    — season Y weeks 1..W folded into the 50/30/20 x games core at
            weight c x games (c = 0 is the prototype: current season ignored)
  rookies — draft-slot comps blended with vet-style comps built from their
            own Y-to-date rate, weight g / (g + R) (R = inf: draft slot only)
Pool: that year's FFC dynasty ADP players, start years 2015-2023, 1QB PPR.

Usage: python backtest_dynasty_inseason.py [--weeks 4,8]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS, WEEKS, SC, STAT_KEYS, score_rates, _norm_name  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

CACHE = os.path.join(HERE, '_dyn_cache')
START_YEARS = list(range(2015, 2024))
LAST_DATA = 2025
C_GRID = [0.0, 0.25, 0.5, 1.0, 2.0, 4.0]
R_GRID = [None, 8, 4, 2, 1]   # None = draft slot only
YOUTH_W = 1.5


def ffc_adp(y):
    p = os.path.join(CACHE, f'ffc_dynasty_{y}.json')
    d = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
    return [(_norm_name(x['name']), x['position'], x['adp']) for x in d.get('players', [])
            if x['position'] in ('QB', 'RB', 'WR', 'TE')]


def evaluate(pool, pred, truth, topn=36):
    sp_n = sp_d = cap_n = cap_d = 0.0
    for Y in START_YEARS:
        yr = [r for r in pool if r['Y'] == Y]
        if len(yr) < 20:
            continue
        pv = [pred(r) for r in yr]; tv = [truth(r) for r in yr]
        sp = spearman(pv, tv)
        if sp is not None:
            sp_n += sp * len(yr); sp_d += len(yr)
        n = min(topn, len(yr))
        mt = sorted(range(len(yr)), key=lambda i: -pv[i])[:n]
        cap_n += sum(tv[i] for i in mt); cap_d += sum(sorted(tv, reverse=True)[:n])
    return sp_n / sp_d, cap_n / cap_d


def pooled_sp(pool, pred, truth):
    return spearman([pred(r) for r in pool], [truth(r) for r in pool])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--weeks', default='4,8')
    args = ap.parse_args()
    print('Loading...')
    w = World(LAST_DATA)
    rows = w.rows(FORMATS['1qb'], START_YEARS[-1])
    comps = Comps(rows, LAST_DATA)
    repl = w._repl
    idx = {(r['key'], r['Y']): r for r in rows}
    pool = []
    for Y in START_YEARS:
        for name, pos, adp in ffc_adp(Y):
            r = idx.get(((name, pos), Y))
            if r:
                pool.append(dict(r, adp=adp))
    print(f'pool {len(pool)} player-years ({sum(r["rookie"] for r in pool)} rookies)')

    for W in [int(x) for x in args.weeks.split(',')]:
        frac = (WEEKS - W) / WEEKS
        miss = 0
        for r in pool:
            key, Y, pos = r['key'], r['Y'], r['pos']
            rest = w.rest_pts(key, Y, W)
            if rest is None:
                miss += 1
                rest = w.pts[Y].get(key, 0.0) * frac
            vr = max(0.0, rest - repl[(Y, pos)] * frac)
            r['t3'] = vr + sum(v or 0 for v in r['vor'][1:3])
            r['t5'] = r['t3'] + sum(v or 0 for v in r['vor'][3:5])
            r['gcur'], tot = w.cur_season(key, Y, W)
            r['P'] = {}
            if r['rookie']:
                ev_r = comps.ev(pos, True, Comps.feat_rookie(r['pick'], r['age0']), Y, exclude_key=key)
                ev_v = None
                if r['gcur'] > 0:
                    base = score_rates({k: tot[k] / r['gcur'] for k in STAT_KEYS}, SC)
                    gp1 = min(17.0, r['gcur'] * 17.0 / W)
                    ev_v = comps.ev(pos, False, Comps.feat_vet(r['age0'], w.rel(base, Y, pos), gp1), Y, exclude_key=key)
                for R in R_GRID:
                    a = 0.0 if (R is None or ev_v is None) else r['gcur'] / (r['gcur'] + R)
                    ev = [(1 - a) * x + a * (y if ev_v else 0) for x, y in zip(ev_r, ev_v or ev_r)]
                    r['P'][('r', R)] = ev
            else:
                for c in C_GRID:
                    b = w.base_at(key, Y, W, c)
                    ev = comps.ev(pos, False, Comps.feat_vet(r['age0'], w.rel(b[0], Y, pos), b[1]), Y, exclude_key=key)
                    r['P'][('c', c)] = ev
        print(f'\n================ WEEK {W} valuation (year-0 share {frac:.2f}); '
              f'{miss} rows had no weekly record (season-total fallback) ================')

        def score(c, R, yw=0.0):
            def f(r):
                ev = r['P'][('r', R)] if r['rookie'] else r['P'][('c', c)]
                return ev[0] * frac + ev[1] + ev[2] + yw * (ev[3] + ev[4])
            return f

        vets = [r for r in pool if not r['rookie']]
        rks = [r for r in pool if r['rookie']]
        print('\nVETS — current-season weight c (x games; last season = 0.5 x games)')
        print(f'{"c":<8}{"Sp T3":>8}{"top36":>8}{"Sp T5(+Y)":>11}')
        for c in C_GRID:
            a = evaluate(vets, score(c, None), lambda r: r['t3'])
            b = evaluate(vets, score(c, None, YOUTH_W), lambda r: r['t5'])
            print(f'{c:<8}{a[0]:>8.3f}{a[1]*100:>7.1f}%{b[0]:>11.3f}')
        print('\nROOKIES — own-games weight g/(g+R), pooled Spearman (n=%d)' % len(rks))
        print(f'{"R":<8}{"Sp T3":>8}{"Sp T5(+Y)":>11}')
        for R in R_GRID:
            print(f'{str(R):<8}{pooled_sp(rks, score(0, R), lambda r: r["t3"]):>8.3f}'
                  f'{pooled_sp(rks, score(0, R, YOUTH_W), lambda r: r["t5"]):>11.3f}')
        print('\nWHOLE POOL (vets c x rookies R), T3 Spearman / top36 — market = PRESEASON ADP (stale by week %d)' % W)
        a = evaluate(pool, lambda r: -r['adp'], lambda r: r['t3'])
        print(f'{"MARKET (preseason)":<26}{a[0]:>8.3f}{a[1]*100:>7.1f}%')
        for c in (0.0, 0.5, 1.0, 2.0):
            for R in (None, 4, 2):
                a = evaluate(pool, score(c, R), lambda r: r['t3'])
                print(f'{"c=" + str(c) + " R=" + str(R):<26}{a[0]:>8.3f}{a[1]*100:>7.1f}%')


if __name__ == '__main__':
    main()
