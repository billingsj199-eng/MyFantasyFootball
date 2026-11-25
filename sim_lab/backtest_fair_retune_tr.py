#!/usr/bin/env python3
"""
backtest_fair_retune_tr.py - re-tune the MFF VALUE (FAIR) order on TOTAL RETURN
(Jack 2026-11-24: "Yes, re-tune it").

FAIR today:  z = 0.5 M3 + 0.3 log sim rank + 0.5 log KTC rank          (lower = better)
Candidate:   z = wM M3 + wS log sim rank + wK log KTC rank - k x EDGE
  EDGE = the lasting-value rating's age / health gap (rating total vs the same-price
         average, as a share of price), models refit without the test year.

Target (same as backtest_rating_vs_fair.py): KTC value at the end of the hold (rank scale,
off the list = 0) + RATE x points over the starter line scored while held; holds of 1, 2, 3
years; five preseason KTC lists 2021-25, top-250 pool with a Dynasty SIM value.

Objective, fixed before looking: per list-year score = mean over that year's available holds of
(rank corr on the whole pool + rank corr inside the KTC top 100) / 2.
Ship test: weights picked leave-one-year-out must beat the shipped weights on the held-out years.

Usage: python backtest_fair_retune_tr.py [--fmt 1qb|sf] [--rebuild]
"""
import argparse
import itertools
import json
import os
import pickle
import sys
import warnings

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
WB = os.path.join(HERE, '_dyn_cache', 'ktc_wb')
import research_ktc_lasting as R  # noqa: E402
import backtest_rating_vs_fair as B  # noqa: E402

SHIP = (0.5, 0.3, 0.5, 0.0)
RATES = (12.0, 0.0, 24.0)
GRID = [g for g in itertools.product((0.0, 0.25, 0.5, 0.75, 1.0), (0.0, 0.1, 0.2, 0.3, 0.5), (0.0, 0.25, 0.5, 0.75, 1.0),
                                     (0.0, 0.5, 1.0, 1.5, 2.0, 3.0)) if g[0] + g[2] > 0]
LOG = None


def out(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    LOG.write(s + '\n')


def build(fmt):
    from dyn_common import World, Comps, FORMATS, _norm_name, JMKernel, JM_COND, load_jm, jm_cond_weight, jm_blend
    R.LOG = open(os.devnull, 'w')
    P = R.load(fmt, 250)
    P = P[P.age.notna()].reset_index(drop=True)
    w = World(B.LAST)
    rows = w.rows(FORMATS[fmt], B.LAST)
    comps = Comps(rows, B.LAST, {'QB': 6.0})
    idx = {(r['key'], r['Y']): r for r in rows}
    jm = load_jm(); kern = JMKernel(w, jm)
    coef = np.array(json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef'], float)
    pools = {}
    for Y, d in B.ANCH.items():
        T = P[P.date == pd.Timestamp(d)].copy()
        sims = []
        for r in T.itertuples():
            k = (_norm_name(r.name), r.pos)
            x = idx.get((k, Y))
            if not x:
                sims.append(np.nan); continue
            if x['rookie']:
                ev = comps.ev(k[1], True, Comps.feat_rookie(x['pick'], x['age0']), Y, exclude_key=k, local_linear=B.LL)
            else:
                ev = comps.ev(k[1], False, comps.feat_v(k[1], x['age0'], x['rel'], x['gp1']), Y, exclude_key=k, local_linear=B.LL)
            if k in jm:
                cy, aj = jm_cond_weight(w, k, Y, JM_COND)
                if aj > 0:
                    ev = jm_blend(ev, kern.ev(k[1], jm[k], Y, range(cy, cy + 5), exclude_key=k), aj)
            sims.append(sum(ev[:3]) + B.YW * sum(ev[3:]))
        T['sim'] = sims
        T = T[T.sim.notna()].copy()
        T['m0'] = T.price.rank(ascending=False, method='first')
        T['s0'] = T.sim.rank(ascending=False, method='first')
        g = T.age - 25.0
        X = np.c_[np.ones(len(T)), np.log(T.m0), np.log(T.s0), (T.exp == 0).astype(float), T.pos == 'RB', T.pos == 'WR', T.pos == 'TE',
                  g * (T.pos == 'QB'), g * (T.pos == 'RB'), g * (T.pos == 'WR'), g * (T.pos == 'TE')].astype(float)
        T['m3'] = X @ coef
        for rate in RATES:
            _, T['edge_%g' % rate], _ = B.rating(P[P.yr != Y], T, rate)
            fw = P[P.date < T.date.iloc[0]].copy()
            for h in (1, 2, 3):
                late = fw.date + pd.Timedelta(days=365 * h + 45) > T.date.iloc[0]
                fw.loc[late, 'f%d' % h] = np.nan
                if h <= 2:
                    fw.loc[late, 'vf%d' % h] = np.nan
            T['edgef_%g' % rate] = B.rating(fw, T, rate)[1] if fw.f1.notna().sum() >= 600 else np.nan
        pools[Y] = T
    pickle.dump(pools, open(os.path.join(WB, 'pools_%s.pkl' % fmt), 'wb'))
    return pools


def prep(pools, rate, edge='edge'):
    """Per list-year arrays + the truths available for each hold."""
    D = {}
    for Y, T in pools.items():
        e = T['%s_%g' % (edge, rate)].to_numpy()
        if np.isnan(e).all():
            continue
        tr = {}
        for h in (1, 2, 3):
            cols = ['vf%d' % i for i in range(1, h + 1)]
            ok = (T['f%d' % h].notna() & T[cols].notna().all(axis=1)).to_numpy()
            if ok.sum() >= 60:
                tr[h] = (ok, (T['f%d' % h] + rate * T[cols].sum(axis=1)).to_numpy())
        D[Y] = dict(m3=T.m3.to_numpy(), ls=np.log(T.s0.to_numpy()), lm=np.log(T.m0.to_numpy()), e=e, top=(T.m0 <= 100).to_numpy(), tr=tr)
    return D


def year_scores(d, g):
    z = -(g[0] * d['m3'] + g[1] * d['ls'] + g[2] * d['lm'] - g[3] * d['e'])
    res = {}
    for h, (ok, y) in d['tr'].items():
        res[h] = (spearmanr(z[ok], y[ok])[0], spearmanr(z[ok & d['top']], y[ok & d['top']])[0])
    return res


def obj(res):
    return float(np.mean([(a + b) / 2 for a, b in res.values()]))


def run(pools, rate, label, edge='edge', verbose=True):
    D = prep(pools, rate, edge)
    years = sorted(D)
    S = {g: {Y: year_scores(D[Y], g) for Y in years} for g in GRID}
    O = {g: {Y: obj(S[g][Y]) for Y in years} for g in GRID}
    tot = {g: np.mean(list(O[g].values())) for g in GRID}

    def line(nm, g):
        parts = []
        for h in (1, 2, 3):
            a = [S[g][Y][h][0] for Y in years if h in S[g][Y]]
            b = [S[g][Y][h][1] for Y in years if h in S[g][Y]]
            parts.append('%dy %.3f / %.3f' % (h, np.mean(a), np.mean(b)) if a else '%dy   -' % h)
        out('  %-40s obj %.4f | %s | by year %s' % (nm, tot[g], '  '.join(parts), ' '.join('%d %.3f' % (Y, O[g][Y]) for Y in years)))

    out('\n--- %s ---   (each hold: rank corr whole pool / inside KTC top 100)' % label)
    line('SHIPPED 0.5 M3 / 0.3 sim / 0.5 mkt', SHIP)
    line('KTC price only', (0.0, 0.0, 1.0, 0.0))
    best = sorted(GRID, key=lambda g: -tot[g])
    if verbose:
        for g in best[:8]:
            line('M3 %.2f sim %.1f mkt %.2f edge %.1f' % g, g)
        # best without the edge, and best with the shipped weights + edge
        ne = max((g for g in GRID if g[3] == 0), key=lambda g: tot[g])
        line('best with NO edge: M3 %.2f sim %.1f mkt %.2f' % ne[:3], ne)
        se = max((g for g in GRID if g[:3] == SHIP[:3]), key=lambda g: tot[g])
        line('shipped weights + edge %.1f' % se[3], se)
        ns = max((g for g in GRID if g[1] == 0), key=lambda g: tot[g])
        line('best with NO sim: M3 %.2f mkt %.2f edge %.1f' % (ns[0], ns[2], ns[3]), ns)
    # leave-one-year-out choice
    d, picks = [], []
    for Y in years:
        g = max(GRID, key=lambda g: np.mean([O[g][y] for y in years if y != Y]))
        d.append(O[g][Y] - O[SHIP][Y]); picks.append('%d (%.2f,%.1f,%.2f,%.1f) %+.3f' % ((Y,) + g + (d[-1],)))
    out('  LOYO-picked weights vs shipped: %+.4f per year, wins %d of %d   %s' % (np.mean(d), sum(x > 1e-9 for x in d), len(d), '  '.join(picks)))
    # same, restricted to simple families
    for nm, fam in (('LOYO, edge strength only (shipped weights)', [g for g in GRID if g[:3] == SHIP[:3]]),
                    ('LOYO, no-edge weights only', [g for g in GRID if g[3] == 0])):
        dd = []
        for Y in years:
            g = max(fam, key=lambda g: np.mean([O[g][y] for y in years if y != Y]))
            dd.append(O[g][Y] - O[SHIP][Y])
        out('  %-44s %+.4f per year, wins %d of %d  (%s)' % (nm, np.mean(dd), sum(x > 1e-9 for x in dd), len(dd), ' '.join('%+.3f' % x for x in dd)))
    return best[0], tot, O, S, years


def main():
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument('--fmt', default='1qb', choices=('1qb', 'sf'))
    ap.add_argument('--rebuild', action='store_true')
    a = ap.parse_args()
    LOG = open(os.path.join(WB, 'fair_retune_tr_%s.log' % a.fmt), 'w', encoding='utf-8')
    f = os.path.join(WB, 'pools_%s.pkl' % a.fmt)
    pools = build(a.fmt) if a.rebuild or not os.path.exists(f) else pickle.load(open(f, 'rb'))
    out('FAIR re-tune on total return | %s | pools %s' % (a.fmt, ', '.join('%d %d' % (Y, len(T)) for Y, T in pools.items())))
    keep = {}
    for rate, lab in ((12.0, 'NEUTRAL (12 per point) - MAIN'), (0.0, 'REBUILD (resale only)'), (24.0, 'CONTENDER (24 per point)')):
        keep[rate] = run(pools, rate, lab)
    best, tot, O, S, years = keep[12.0]
    out('\n=== the neutral winner on the other dials and on the honest forward-trained edge ===')
    for rate, lab in ((0.0, 'rebuild'), (24.0, 'contender')):
        _, t2, O2, _, y2 = keep[rate]
        out('  %-10s winner obj %.4f vs shipped %.4f (%+.4f); by year %s' % (lab, t2[best], t2[SHIP], t2[best] - t2[SHIP],
                                                                       ' '.join('%d %+.3f' % (Y, O2[best][Y] - O2[SHIP][Y]) for Y in y2)))
    D = prep(pools, 12.0, 'edgef')
    out('  forward-trained edge (2023-25 only): ' + ' '.join('%d %+.3f' % (Y, obj(year_scores(D[Y], best)) - obj(year_scores(D[Y], SHIP))) for Y in sorted(D)))
    out('  neutral winner = M3 %.2f, sim %.1f, market %.2f, edge %.1f' % best)
    json.dump({'fmt': a.fmt, 'best': best, 'obj_best': tot[best], 'obj_ship': tot[SHIP]}, open(os.path.join(WB, 'fair_retune_tr_%s.json' % a.fmt), 'w'))
    LOG.close()


if __name__ == '__main__':
    main()
