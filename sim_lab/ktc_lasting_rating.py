#!/usr/bin/env python3
"""
ktc_lasting_rating.py - PROTOTYPE dynasty rating from the KTC lasting-value study
(Jack 2026-11-24). Nothing here is wired to the site.

What survived the study (research_ktc_lasting.py, forward-tested): the public price
is right about almost everything EXCEPT how fast value melts by position x age, and
recent missed games. So the rating is:

  LASTING VALUE = expected KTC value (rank scale) averaged over +1, +2, +3 years
                  model: same-price average + position x age + games in the last 12 months
  POINTS        = expected points over the starter line per year, next 2 years
                  (so older producers get paid for what they score while you hold them)
  TOTAL         = LASTING VALUE + RATE x POINTS      RATE = KTC value per point
                  12 = what the top-100 market pays per point (neutral team)
                  24 = contender, 0 = pure rebuild / resale only
  RATING 0-99   = 99 x sqrt(TOTAL / best TOTAL on the board)
  EDGE          = TOTAL vs the average TOTAL of players at the same KTC price
                  (+ = holds more than his price says, - = melts faster)

Today's list = the latest archived KTC list re-priced with the site's daily KTC pull
(data/ktc_rankings.js).  Usage: python ktc_lasting_rating.py [--fmt 1qb|sf] [--rate 12]
Output: _dyn_cache/ktc_wb/rating_<fmt>.csv
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import warnings

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold

warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.join(HERE, '_dyn_cache', 'ktc_wb')
SITE = os.path.join(os.path.dirname(HERE), 'MyFantasyFootball Files', 'data', 'ktc_rankings.js')
sys.path.insert(0, HERE)
import research_ktc_lasting as R  # noqa: E402
from ktc_lasting_panel import norm  # noqa: E402

BASE = ['price', 'is_qb', 'is_rb', 'is_wr', 'is_te', 'age', 'g1', 'exp']
PTS = BASE + ['vor1', 'ppg1', 'ppg2']


def make_live():
    """Latest archived list (traits) + today's values from the site's daily KTC pull."""
    last = sorted(glob.glob(os.path.join(WB, 'wb_*.json')))[-1]
    P = json.load(open(last, encoding='utf-8'))
    s = open(SITE, encoding='utf-8').read()
    maps = {}
    for var, key in (('KTC_1QB', 'oneQBValues'), ('KTC_SF', 'superflexValues')):
        m = re.search(r'\b' + var + r'\s*=\s*\{', s)
        obj = json.JSONDecoder().raw_decode(s, m.end() - 1)[0]
        maps[key] = {norm(k): v for k, v in obj.items()}
    hit = 0
    for p in P:
        k = norm(p.get('playerName'))
        for key, mp in maps.items():
            if k in mp:
                p.setdefault(key, {})['value'] = mp[k]
                hit += 1
    json.dump(P, open(os.path.join(WB, 'live.json'), 'w', encoding='utf-8'))
    return os.path.basename(last), hit // 2, len(P)


def gb(leaf=60):
    return HistGradientBoostingRegressor(max_depth=3, learning_rate=0.04, max_iter=300, min_samples_leaf=leaf,
                                         l2_regularization=2.0, random_state=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fmt', default='1qb')
    ap.add_argument('--rate', type=float, default=12.0)
    ap.add_argument('--top', type=int, default=300)
    ap.add_argument('--no-rebuild', action='store_true')
    a = ap.parse_args()
    compute(a, verbose=True)


def refresh_today():
    """Today's list (latest stored KTC list re-priced from the site's KTC maps) + panel rebuild."""
    src, hit, n = make_live()
    subprocess.run([sys.executable, '-I', os.path.join(HERE, 'ktc_lasting_panel.py'), '--live'], check=True,
                   stdout=subprocess.DEVNULL)
    return src, hit, n


def compute(a, verbose=False):
    """-> today's rating table (DataFrame). a: fmt, rate, top, no_rebuild."""
    global print
    _p = print
    if not verbose:
        print = lambda *x, **k: None   # noqa: E731
    try:
        return _compute(a)
    finally:
        print = _p


def _compute(a):
    if not a.no_rebuild:
        src, hit, n = refresh_today()
        print('today = %s re-priced from the site KTC pull (%d of %d matched)' % (src, hit, n))
    R.LOG = open(os.devnull, 'w')
    P = R.load(a.fmt, a.top)
    now = P[P.date == P.date.max()].copy()
    H = P[(P.date < P.date.max()) & (P.krank <= 250) & P.age.notna()].copy()
    print('today %s: %d players | history rows %d' % (now.date.max().date(), len(now), len(H)))
    # resale at +1 / +2 / +3 years
    for h in (1, 2, 3):
        D = H[H['f%d' % h].notna()]
        iso = R.par_fit(D.price, D['f%d' % h])
        m = gb().fit(D[BASE], D['f%d' % h] - iso.predict(D.price))
        now['par%d' % h] = iso.predict(now.price)
        now['e%d' % h] = np.clip(now['par%d' % h] + m.predict(now[BASE]), 0, 9998)
    # points over the starter line, per year, next two years
    D = H[H.vf1.notna() & H.vf2.notna()].copy()
    D['pts'] = (D.vf1 + D.vf2) / 2
    cv = np.zeros(len(D))
    for tr, te in GroupKFold(5).split(D, groups=D.kid):
        cv[te] = gb().fit(D.iloc[tr][PTS], D.iloc[tr].pts).predict(D.iloc[te][PTS])
    isoP = R.par_fit(D.price, D.pts)
    print('points model, held out by player: rank corr with actual %.3f (price alone %.3f, last-12-month points alone %.3f)'
          % (spearmanr(cv, D.pts)[0], spearmanr(D.price, D.pts)[0], spearmanr(D.vor1.fillna(0), D.pts)[0]))
    now['pts'] = np.clip(gb().fit(D[PTS], D.pts).predict(now[PTS]), 0, None)
    now['par_pts'] = isoP.predict(now.price)
    now['lv'] = (now.e1 + now.e2 + now.e3) / 3
    now['par_lv'] = (now.par1 + now.par2 + now.par3) / 3
    for lab, rate in (('', a.rate), ('_reb', 0.0), ('_con', 2 * a.rate)):
        tot = now.lv + rate * now.pts
        par = now.par_lv + rate * now.par_pts
        now['total' + lab] = tot
        now['rating' + lab] = np.round(99 * np.sqrt(tot / tot.max())).astype(int)
        now['edge' + lab] = (tot - par) / now.price
        now['rk' + lab] = tot.rank(ascending=False, method='first').astype(int)
    now['keep1'] = now.e1 / now.price
    now['keep3'] = now.e3 / now.price
    now['tag'] = np.where(now.edge >= .08, 'LASTING', np.where(now.edge <= -.08, 'MELTING', ''))
    now['krank'] = now.krank.astype(int)
    cols = ['rk', 'name', 'pos', 'age', 'krank', 'price', 'rating', 'lv', 'pts', 'keep1', 'keep3', 'edge', 'tag',
            'rating_reb', 'rk_reb', 'rating_con', 'rk_con', 'g1', 'team']
    out = now.sort_values('rk')[cols]
    out.to_csv(os.path.join(WB, 'rating_%s.csv' % a.fmt), index=False, float_format='%.3f')
    pd.set_option('display.width', 250)
    show = out.head(60).copy()
    for c in ('keep1', 'keep3', 'edge'):
        show[c] = (100 * show[c]).round(0).astype(int).astype(str) + '%'
    show[['age']] = show[['age']].round(1)
    show[['price', 'lv', 'pts']] = show[['price', 'lv', 'pts']].round(0).astype(int)
    print(show.drop(columns=['g1', 'team']).to_string(index=False))
    for lab, asc in (('BIGGEST "LASTING" EDGES (KTC top 150)', False), ('BIGGEST "MELTING" EDGES (KTC top 150)', True)):
        x = out[out.krank <= 150].sort_values('edge', ascending=asc).head(20)
        print('\n' + lab)
        print('  ' + ', '.join('%s %s %.0f (KTC #%d -> #%d, %+.0f%%)' % (r.nm, r.pos, r.age, r.krank, r.rk, 100 * r.edge)
                               for r in x.rename(columns={'name': 'nm'}).itertuples()))
    return now


if __name__ == '__main__':
    main()
