#!/usr/bin/env python3
"""
backtest_joint_refit.py — re-fit the shipped FAIR / MFF VALUE pieces TOGETHER
(Jack 2026-10-09: "we need to optimize our value" -> "run the joint re-fit").

Each piece was tuned on its own: FAIR order weights (wM expected market M3, wS
log sim rank, wK log market rank — shipped 0.5 / 0.3 / 0.5) and the RB
receiving-efficiency tilt (k x z of prior-season PFF RB receiving YPRR, shipped
-0.25; data from 2019 so it acts on 2020-23). Pool / objective = the FAIR tune:
FFC dynasty pool 2016-23 (1QB PPR), shipped conditional-JM sim, shipped M3;
per-year Spearman vs next-year market rank, realized 3yr, 5yr + youth, and
3yr within the market top 50 — average of the four.
Grid wM x wS x wK x k; LEAVE-ONE-YEAR-OUT: pick the combo on 7 seasons, score
the 8th, compare with the shipped combo on the same season. (Pick blending and
the 2027 class lean have no backtestable history and stay as shipped.)
"""
import itertools
import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import _norm_name  # noqa: E402
from backtest_value_score import build, YEARS, LAST  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

SHIP = (0.5, 0.3, 0.5, -0.25)
CACHE = r'E:\MyFantasyFootball\pbp_cache'


def rb_z():
    """{(key, season): z of PFF RB receiving YPRR among RBs with 75+ carries that season}"""
    out = {}
    for y in range(2019, 2025):
        d = pd.read_csv(os.path.join(CACHE, 'pff', f'pff_rushing_{y}.csv'))
        d = d[d.position.isin(['HB', 'RB', 'FB']) & (d.attempts >= 75) & d.yprr.notna()]
        mu, sd = d.yprr.mean(), d.yprr.std(ddof=0) or 1
        for r in d.to_dict('records'):
            out[((_norm_name(r['player']), 'RB'), y)] = (r['yprr'] - mu) / sd
    return out


def main():
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = build(True)
    m3_ship(recs, c)
    Z = rb_z()
    for x in recs:
        x['rbz'] = Z.get((x['key'], x['Y'] - 1), 0.0) if (x['pos'] == 'RB' and not x['rookie']) else 0.0
        x['lm'], x['ls'] = math.log(x['m0']), math.log(x['s0'])
    y5 = [y for y in YEARS if y + 4 <= LAST]
    by_year = {Y: [x for x in recs if x['Y'] == Y] for Y in YEARS}

    def score(p, yrs):
        wM, wS, wK, k = p
        f = lambda x: -(wM * x['m3'] + wS * x['ls'] + wK * x['lm'] + k * x['rbz'])
        tot = {}
        for nm, truth, sub, ys in (('next', lambda x: -x['m1'], None, yrs), ('3yr', lambda x: -x['r_t3'], None, yrs),
                                    ('5yr', lambda x: -x['r_lt'], None, [y for y in yrs if y in y5]),
                                    ('top50', lambda x: -x['r_t3'], lambda x: x['m0'] <= 50, yrs)):
            num = den = 0.0
            for Y in ys:
                xs = [x for x in by_year[Y] if 'r_t3' in x and (nm != '5yr' or 'r_lt' in x) and (sub is None or sub(x))]
                if len(xs) < 10:
                    continue
                s = spearman([f(x) for x in xs], [truth(x) for x in xs])
                if s is not None:
                    num += s * len(xs); den += len(xs)
            tot[nm] = num / den if den else float('nan')
        v = [t for t in tot.values() if t == t]
        tot['avg'] = sum(v) / len(v)
        return tot

    grid = list(itertools.product((0.3, 0.5, 0.7), (0.2, 0.3, 0.4), (0.35, 0.5, 0.7), (0.0, -0.15, -0.25, -0.35)))
    allsc = {p: score(p, YEARS) for p in grid}
    best = max(grid, key=lambda p: allsc[p]['avg'])
    hdr = f'{"combo (wM, wS, wK, kRB)":<30}{"next":>7}{"3yr":>7}{"5yr+y":>7}{"top50":>7}{"avg":>7}'
    print('=== all seasons (in-sample) ===\n' + hdr)
    for nm, p in (('SHIPPED', SHIP), ('no RB tilt', (0.5, 0.3, 0.5, 0.0)), ('best', best)):
        s = allsc[p]
        print(f'{nm + " " + str(p):<30}{s["next"]:>7.3f}{s["3yr"]:>7.3f}{s["5yr"]:>7.3f}{s["top50"]:>7.3f}{s["avg"]:>7.4f}')
    print('   top 8 combos:')
    for p in sorted(grid, key=lambda p: -allsc[p]['avg'])[:8]:
        s = allsc[p]
        print(f'   {str(p):<27}{s["next"]:>7.3f}{s["3yr"]:>7.3f}{s["5yr"]:>7.3f}{s["top50"]:>7.3f}{s["avg"]:>7.4f}')

    print('\n=== leave-one-year-out: combo chosen on 7 seasons vs SHIPPED on the held-out season ===')
    d, picks = [], []
    for Y in YEARS:
        tr = [y for y in YEARS if y != Y]
        p = max(grid, key=lambda q: score(q, tr)['avg'])
        picks.append(p)
        a, b = score(p, [Y])['avg'], score(SHIP, [Y])['avg']
        d.append(a - b)
        print(f'   {Y}: picked {p} -> {a:.4f} vs shipped {b:.4f} ({a - b:+.4f})')
    print(f'held-out mean change vs shipped {np.mean(d):+.4f}; wins {sum(x > 1e-9 for x in d)}, ties {sum(abs(x) <= 1e-9 for x in d)}, losses {sum(x < -1e-9 for x in d)} of {len(d)}')
    json.dump({'best_in_sample': best, 'loyo_picks': picks, 'loyo_delta': d}, open(os.path.join(HERE, '_dyn_cache', 'joint_refit.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
