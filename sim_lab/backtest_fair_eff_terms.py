#!/usr/bin/env python3
"""
backtest_fair_eff_terms.py — targeted LOYO check of the two efficiency signals
that held up in research_efficiency_value.py (beyond-FAIR, stable across folds):
  RB receiving: YPRR / targets per route (prior season, 75+ carries)
  WR points over expected per game (ctx_features, prior season, 150+ routes)
FAIR log-rank score + k * z(stat) for that position only (missing = 0); k fit by
OLS on the training years' 3yr residual, scored on the held-out year (whole
pool and that position).
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from backtest_value_score import build  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402
import research_efficiency_value as RE  # noqa: E402

YRS = RE.YRS


def main():
    S = RE.load_stats()
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = [x for x in build(True) if x['Y'] in YRS]
    m3_ship(recs, c)
    for x in recs:
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
        f = S.get((x['key'], x['Y'] - 1), {})
        x['st'] = f if (not x['rookie'] and RE.qualifies(x['pos'], f)) else {}
    for Y in YRS:
        for i, x in enumerate(sorted([x for x in recs if x['Y'] == Y], key=lambda x: x['fz'])):
            x['f0'] = i + 1
    for pos, st in (('RB', 'rb_yprr'), ('WR', 'yprr_man'), ('WR', 'man_gap'), ('TE', 'yprr_zone')):
        d_all, d_pos, d5, ks = [], [], [], []
        for Y in YRS:
            tr = [x for x in recs if x['Y'] != Y]; te = [x for x in recs if x['Y'] == Y]
            g = [x for x in tr if x['pos'] == pos and x['st'].get(st) is not None and x.get('r_t3') and not (isinstance(x['st'][st], float) and math.isnan(x['st'][st]))]
            v = np.array([x['st'][st] for x in g], float); mu, sd = v.mean(), v.std() or 1
            X = np.column_stack([np.ones(len(g)), [math.log(x['f0']) for x in g], (v - mu) / sd])
            b = np.linalg.lstsq(X, np.array([math.log(x['r_t3']) for x in g]), rcond=None)[0]
            k = min(0.0, b[2]); ks.append(round(k, 3))
            def sc(x):
                s = math.log(x['f0'])
                if x['pos'] == pos:
                    val = x['st'].get(st)
                    if val is not None and not (isinstance(val, float) and math.isnan(val)):
                        s += k * (val - mu) / sd
                return s
            for tk, dd, sub in (('r_t3', d_all, None), ('r_t3', d_pos, pos), ('r_lt', d5, None)):
                xs = [x for x in te if x.get(tk) and (sub is None or x['pos'] == sub)]
                if len(xs) >= 15:
                    dd.append(spearman([-sc(x) for x in xs], [-x[tk] for x in xs]) - spearman([-math.log(x['f0']) for x in xs], [-x[tk] for x in xs]))
        print(f'{pos} {st:<11} k per fold {ks}  held-out vs FAIR: whole pool 3yr {np.mean(d_all):+.4f} ({sum(v > 1e-9 for v in d_all)}/{len(d_all)}),'
              f' {pos}-only 3yr {np.mean(d_pos):+.4f} ({sum(v > 1e-9 for v in d_pos)}/{len(d_pos)}), whole 5yr+y {np.mean(d5) if d5 else float("nan"):+.4f} ({sum(v > 1e-9 for v in d5)}/{len(d5)})')


if __name__ == '__main__':
    main()
