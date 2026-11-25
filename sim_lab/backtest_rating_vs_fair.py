#!/usr/bin/env python3
"""
backtest_rating_vs_fair.py - should the lasting-value rating replace the MFF VALUE
(FAIR) order?  (Jack 2026-11-24: "Test as MFF VALUE")

Target = TOTAL RETURN of holding a player h years, on full archived KTC lists
(ktc_lasting_panel.py, busts included):
    TR_h = KTC value h years later (rank scale; off the list = 0)
           + RATE x points over the starter line scored while held
    RATE 12 = neutral (what the top-100 market pays per point), 0 = resale only, 24 = contender

Per preseason list Y (2021-25): pool = KTC top-250 players with a Dynasty SIM value.
Orders graded on the SAME pool:
    market      KTC price
    sim         Dynasty SIM (comps, time-honest, shipped conditional JM)
    FAIR        shipped MFF VALUE order: 0.5 M3 + 0.3 log sim rank + 0.5 log KTC rank
                (shipped M3 coef; the small RB YAC/route tilt and QB team-total term are not rebuilt)
    RATING      ktc_lasting_rating.py order, models refit WITHOUT the test year (LOYO)
    RATING fwd  same, trained only on outcomes already known on the list date (2023-25)
    FAIR + k x EDGE   FAIR moved by the rating's age / health edge (edge = rating total vs
                same-price par, share of price); k picked leave-one-year-out

Metric: rank correlation with TR inside each year's pool (n-weighted mean), the same inside
the KTC top 100, and the share of the best-possible total captured by each order's top 50.
Usage: python backtest_rating_vs_fair.py [--fmt 1qb|sf]
"""
import argparse
import json
import math
import os
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
from ktc_lasting_rating import BASE, PTS, gb  # noqa: E402
from dyn_common import World, Comps, FORMATS, _norm_name, JMKernel, JM_COND, load_jm, jm_cond_weight, jm_blend  # noqa: E402

LL = (120, 5.0)
YW = 1.5
LAST = 2025
ANCH = {2021: '2021-07-24', 2022: '2022-08-14', 2023: '2023-10-01', 2024: '2024-08-13', 2025: '2025-08-25'}
SHIP = (0.5, 0.3, 0.5)
KS = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0)
LOG = None


def out(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    LOG.write(s + '\n')


def rating(train, test, rate, min_rows=600):
    """Rating total, same-price par and edge for `test`, models fit on `train`."""
    e, par, used = [], [], []
    for h in (1, 2, 3):
        D = train[train['f%d' % h].notna()]
        if len(D) < min_rows:
            continue
        iso = R.par_fit(D.price, D['f%d' % h])
        m = gb().fit(D[BASE], D['f%d' % h] - iso.predict(D.price))
        p = iso.predict(test.price)
        par.append(p); e.append(np.clip(p + m.predict(test[BASE]), 0, 9998)); used.append(h)
    D = train[train.vf1.notna() & train.vf2.notna()].copy()
    if len(D) < min_rows:
        D = train[train.vf1.notna()].copy(); D['pts'] = D.vf1
    else:
        D['pts'] = (D.vf1 + D.vf2) / 2
    isoP = R.par_fit(D.price, D.pts)
    pts = np.clip(gb().fit(D[PTS], D.pts).predict(test[PTS]), 0, None)
    lv, plv = np.mean(e, axis=0), np.mean(par, axis=0)
    tot = lv + rate * pts
    return tot, (tot - (plv + rate * isoP.predict(test.price))) / test.price.to_numpy(), used


def main():
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument('--fmt', default='1qb', choices=('1qb', 'sf'))
    a = ap.parse_args()
    LOG = open(os.path.join(WB, 'rating_vs_fair_%s.log' % a.fmt), 'w', encoding='utf-8')
    R.LOG = open(os.devnull, 'w')
    P = R.load(a.fmt, 250)
    P = P[P.age.notna()].reset_index(drop=True)
    w = World(LAST)
    rows = w.rows(FORMATS[a.fmt], LAST)
    comps = Comps(rows, LAST, {'QB': 6.0})
    idx = {(r['key'], r['Y']): r for r in rows}
    jm = load_jm(); kern = JMKernel(w, jm)
    coef = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    pools = {}
    for Y, d in ANCH.items():
        T = P[P.date == pd.Timestamp(d)].copy()
        sims = []
        for r in T.itertuples():
            k = (_norm_name(r.name), r.pos)
            x = idx.get((k, Y))
            if not x:
                sims.append(np.nan); continue
            if x['rookie']:
                ev = comps.ev(k[1], True, Comps.feat_rookie(x['pick'], x['age0']), Y, exclude_key=k, local_linear=LL)
            else:
                ev = comps.ev(k[1], False, comps.feat_v(k[1], x['age0'], x['rel'], x['gp1']), Y, exclude_key=k, local_linear=LL)
            if k in jm:
                cy, aj = jm_cond_weight(w, k, Y, JM_COND)
                if aj > 0:
                    ev = jm_blend(ev, kern.ev(k[1], jm[k], Y, range(cy, cy + 5), exclude_key=k), aj)
            sims.append(sum(ev[:3]) + YW * sum(ev[3:]))
        T['sim'] = sims
        n0 = len(T)
        T = T[T.sim.notna()].copy()
        T['m0'] = T.price.rank(ascending=False, method='first')
        T['s0'] = T.sim.rank(ascending=False, method='first')
        g = T.age - 25.0
        X = np.c_[np.ones(len(T)), np.log(T.m0), np.log(T.s0), (T.exp == 0).astype(float), T.pos == 'RB', T.pos == 'WR', T.pos == 'TE',
                  g * (T.pos == 'QB'), g * (T.pos == 'RB'), g * (T.pos == 'WR'), g * (T.pos == 'TE')].astype(float)
        T['m3'] = X @ np.array(coef, float)
        T['fair_z'] = SHIP[0] * T.m3 + SHIP[1] * np.log(T.s0) + SHIP[2] * np.log(T.m0)
        pools[Y] = T
        out('%d list %s: KTC top-250 players %d, with a sim value %d' % (Y, d, n0, len(T)))

    def truth(T, h, rate):
        cols = ['vf%d' % i for i in range(1, h + 1)]
        ok = T['f%d' % h].notna() & T[cols].notna().all(axis=1)
        return ok, T['f%d' % h] + rate * T[cols].sum(axis=1)

    for rate in (12.0, 0.0, 24.0):
        out('\n' + '=' * 110)
        out('RATE %g KTC per point over the starter line  (%s)' % (rate, {12.0: 'neutral team - MAIN', 0.0: 'resale only / rebuild', 24.0: 'contender'}[rate]))
        # orders
        for Y, T in pools.items():
            tr = P[P.yr != Y]
            T['rate_tot'], T['edge'], _ = rating(tr, T, rate)
            fw = P[(P.date < T.date.iloc[0])].copy()
            for h in (1, 2, 3):                      # only outcomes already known on the list date
                late = fw.date + pd.Timedelta(days=365 * h + 45) > T.date.iloc[0]
                fw.loc[late, 'f%d' % h] = np.nan
                if h <= 2:
                    fw.loc[late, 'vf%d' % h] = np.nan
            if fw.f1.notna().sum() >= 600:
                T['rate_fwd'], T['edge_fwd'], used = rating(fw, T, rate)
                T.attrs['fwd'] = used
            else:
                T['rate_fwd'] = np.nan; T['edge_fwd'] = np.nan
        orders = {'market (KTC price)': lambda T: T.price, 'sim (Dynasty SIM)': lambda T: T.sim, 'FAIR = shipped MFF VALUE': lambda T: -T.fair_z,
                  'RATING (LOYO)': lambda T: T.rate_tot, 'RATING forward-trained': lambda T: T.rate_fwd}
        for k in KS[1:]:
            orders['FAIR + %.1f x edge' % k] = (lambda k: lambda T: -(T.fair_z - k * T.edge))(k)
        res = {}
        for h in (1, 2, 3):
            out('\n hold %d year%s' % (h, 's' if h > 1 else ''))
            out('  %-28s %8s %8s %8s   %s' % ('order', 'all', 'top 100', 'top50%', 'rank corr by list year'))
            for nm, f in orders.items():
                sp, sp100, cap, by, ns = [], [], [], [], []
                for Y, T in pools.items():
                    ok, tr = truth(T, h, rate)
                    s = f(T)
                    ok = ok & s.notna()
                    if ok.sum() < 60:
                        continue
                    x, y = s[ok], tr[ok]
                    c = spearmanr(x, y)[0]
                    t100 = (T.m0 <= 100)[ok]
                    sp.append(c); ns.append(ok.sum()); by.append('%d %.3f' % (Y, c))
                    sp100.append(spearmanr(x[t100], y[t100])[0])
                    cap.append(y[x.rank(ascending=False, method='first') <= 50].sum() / y.sort_values(ascending=False).head(50).sum())
                    res[(h, nm, Y)] = c
                if not sp:
                    continue
                res[(h, nm)] = np.average(sp, weights=ns)
                out('  %-28s %8.3f %8.3f %7.1f%%   %s' % (nm, np.average(sp, weights=ns), np.average(sp100, weights=ns), 100 * np.mean(cap), '  '.join(by)))
        # leave-one-year-out choice of k for the blend, on the mean of the 1- and 2-year correlations
        out('\n blend strength picked leave-one-year-out (score = mean of the 1-yr and 2-yr rank corr):')
        def sc(nm, Y):
            v = [res[(h, nm, Y)] for h in (1, 2) if (h, nm, Y) in res]
            return np.mean(v) if v else None
        names = {k: ('FAIR = shipped MFF VALUE' if k == 0 else 'FAIR + %.1f x edge' % k) for k in KS}
        d, picks = [], []
        for Y in pools:
            if sc(names[0], Y) is None:
                continue
            others = [y for y in pools if y != Y and sc(names[0], y) is not None]
            best = max(KS, key=lambda k: np.mean([sc(names[k], y) for y in others]))
            d.append(sc(names[best], Y) - sc(names[0], Y)); picks.append('%d k=%.1f %+.3f' % (Y, best, d[-1]))
        out('   ' + '  '.join(picks))
        out('   blend vs shipped FAIR: %+.4f per year, wins %d of %d' % (np.mean(d), sum(x > 1e-9 for x in d), len(d)))
        dr = [sc('RATING (LOYO)', Y) - sc(names[0], Y) for Y in pools if sc(names[0], Y) is not None]
        out('   RATING (LOYO) vs shipped FAIR: %+.4f per year, wins %d of %d' % (np.mean(dr), sum(x > 1e-9 for x in dr), len(dr)))
        df = [(Y, sc('RATING forward-trained', Y) - sc(names[0], Y)) for Y in pools if sc('RATING forward-trained', Y) is not None]
        if df:
            out('   RATING forward-trained vs shipped FAIR: ' + '  '.join('%d %+.3f' % x for x in df))
        if rate == 12.0:
            # biggest disagreements today's style: who the blend moves, last list
            T = pools[2025]
            out('\n who moved most between FAIR and RATING on the 2025 list (pool rank FAIR -> RATING, then what happened in 1 yr):')
            T = T.assign(rf=T.fair_z.rank(method='first'), rr=T.rate_tot.rank(ascending=False, method='first'))
            ok, tr = truth(T, 1, rate)
            T = T.assign(tr=tr.where(ok), rt=tr.where(ok).rank(ascending=False, method='first'))
            T = T[T.m0 <= 120]
            for lab, x in (('rating higher', T.sort_values('rr').assign(d=T.rf - T.rr).sort_values('d', ascending=False).head(12)),
                           ('rating lower', T.assign(d=T.rf - T.rr).sort_values('d').head(12))):
                out('   %s: ' % lab + ', '.join('%s %s %.0f (%d -> %d; actual %s)' % (r.name, r.pos, r.age, r.rf, r.rr, ('%d' % r.rt) if not math.isnan(r.rt) else '-')
                                                for r in x.rename(columns={'name': 'nm'}).rename(columns={'nm': 'name'}).itertuples(index=False)))
    LOG.close()


if __name__ == '__main__':
    main()
