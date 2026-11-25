#!/usr/bin/env python3
"""
ktc_value_forecast.py - today's 3- and 6-month value forecast per player (Jack 2026-11-24:
"Yes, build it" - sell-high / buy-low windows on the review branch).

Model = backtest_ktc_forecast.py's full model (cycle + form / health + KTC momentum), fit on every
tracked move with a known outcome, applied to today's list. Backtest (forward in time, KTC top 150):
the 20% it liked least lost 6.9% in 3 months and 12.4% in 6 (in season) vs 1.6% / 4.7% for the 20% it
liked most; positive in every test year. It finds sells far better than buys.

today(fmt) -> DataFrame [name, pos, krank, f3, f6 (expected % move in value), rel (avg of the two,
              vs the median top-150 player), win (+1 buy window = top 20% of rel inside the KTC
              top 150, -1 sell window = bottom 20%, else 0)], plus med3 / med6 in .attrs.
Needs the forecast rows built with today's list:  python backtest_ktc_forecast.py --fmt <fmt> --rebuild --today-only
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_ktc_forecast as F  # noqa: E402
from ktc_lasting_panel import norm  # noqa: E402

WB = F.WB
SITE_HIST = os.path.join(os.path.dirname(HERE), 'MyFantasyFootball Files', 'data', 'ktc_history.js')
TOP = 150
Q = 0.20


def last_month_from_history(T, fmt):
    """KTC's move over the last month from OUR daily tracked values (the archive rarely has a list 30 days back)."""
    try:
        s = open(SITE_HIST, encoding='utf-8').read()
        H = json.JSONDecoder().raw_decode(s, s.index('{'))[0]
    except (OSError, ValueError):
        return None
    dts = pd.to_datetime(H['dates'])
    day = pd.Timestamp(T['T'].iloc[0]) - pd.Timedelta(days=30)
    i = int(np.argmin(np.abs((dts - day).days)))
    if abs((dts[i] - day).days) > 12:
        return None
    key = 'v1' if fmt == '1qb' else 'vsf'
    ref = json.load(open(os.path.join(WB, 'ref_curve.json')))['v1' if fmt == '1qb' else 'vs']
    old = {k: v[i] for k, v in H[key].items() if not k[:4].isdigit() and v[i]}
    rk = pd.Series(old).rank(ascending=False, method='first').astype(int)
    return {norm(k): ref[min(r, len(ref)) - 1] for k, r in rk.items()}


def today(fmt='1qb'):
    sx = F.SUF[fmt]
    X = pd.read_parquet(os.path.join(WB, 'forecast_rows%s.parquet' % sx))
    T = X[X.v1.isna()].copy()
    X = X[X.v1.notna()]
    if not len(T):
        raise RuntimeError('no rows for the latest list - rebuild with: backtest_ktc_forecast.py --fmt %s --rebuild --today-only' % fmt)
    old = last_month_from_history(T, fmt)
    if old is not None:
        T['vb1'] = [old.get(norm(n), np.nan) for n in T.name]
        T['m1'] = np.log((T.v0 + 300) / (T.vb1 + 300))
    feats = F.CYCLE + F.FORM + F.MKT
    m = F.gb().fit(X[feats], X.y)
    T['pct'] = 100 * (np.exp(m.predict(T[feats])) - 1)
    W = T.pivot_table(index=['kid', 'name', 'pos', 'krank'], columns='lagc', values='pct').reset_index()
    W = W.rename(columns={'3 months': 'f3', '6 months': 'f6'})[['kid', 'name', 'pos', 'krank', 'f3', 'f6']]
    top = W[W.krank <= TOP]
    med3, med6 = float(top.f3.median()), float(top.f6.median())
    W['rel'] = ((W.f3 - med3) + (W.f6 - med6)) / 2
    lo, hi = W[W.krank <= TOP].rel.quantile([Q, 1 - Q]).tolist()
    W['win'] = np.where((W.krank <= TOP) & (W.rel <= lo), -1, np.where((W.krank <= TOP) & (W.rel >= hi), 1, 0))
    W.attrs.update(med3=med3, med6=med6, date=str(pd.Timestamp(T['T'].iloc[0]).date()), m1=old is not None)
    return W.sort_values('rel').reset_index(drop=True)


if __name__ == '__main__':
    for fmt in sys.argv[1:] or ['1qb']:
        W = today(fmt)
        print('%s %s: %d players | typical top-%d move %+.1f%% (3 mo) %+.1f%% (6 mo) | sell windows %d, buy windows %d'
              % (fmt, W.attrs['date'], len(W), TOP, W.attrs['med3'], W.attrs['med6'], (W.win == -1).sum(), (W.win == 1).sum()))
        print('  sell: ' + ', '.join('%s %+.0f/%+.0f' % (r.name, r.f3, r.f6) for r in W[W.win == -1].head(12).itertuples(index=False)))
        print('  buy:  ' + ', '.join('%s %+.0f/%+.0f' % (r.name, r.f3, r.f6) for r in W[W.win == 1].sort_values('rel', ascending=False).head(12).itertuples(index=False)))
