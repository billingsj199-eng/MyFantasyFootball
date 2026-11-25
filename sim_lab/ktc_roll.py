#!/usr/bin/env python3
"""
ktc_roll.py - keep today's prices current while our KTC copy is frozen
(Jack 2026-11-24: "Yes, wire it" - the in-season roll-forward inside the weekly build).

KTC moved its player list behind a robots-disallowed path on 2026-11-24, so data/ktc_rankings.js
stopped updating. This module:
  freeze_date()         the last day our tracked KTC values actually changed (site data/ktc_history.js)
  ensure_frozen_list()  saves that day's list as a normal tracked list (wb_<date>000000.json) so the
                        panel has the freeze date as a real list date
  share(lag, games)     how much of the predicted move to apply - from the backtest
                        (_tmp/roll_shrink.py, forward-tested, KTC top 150, in season):
                            under 3 weeks / under 3 team games : 0    (rolling does not beat frozen yet)
                            3 to 6 weeks                       : 0.5  (rank corr .961 frozen -> .972)
                            past 6 weeks                       : 0.75 (.901 -> .941 at 6-10 weeks, .887 -> .939 at 10-14)
                        off season (no games since the freeze): 0 - the roll adds nothing there.
  roll(fmt, ...)        rolled value + rank for every player on the frozen list (top 250 are moved by the
                        model of backtest_ktc_rollforward.py: games played, points vs his old rate, games
                        missed, share changes; everyone else keeps his frozen value)
  write_live(...)       today's list for the panel (live.json) with the rolled values

--simulate YYYY-MM-DD   plumbing check on a real past list: freeze it, roll to the next real list, compare.
"""
import argparse
import datetime as dt
import glob
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_ktc_rollforward as RF  # noqa: E402
from ktc_lasting_panel import norm  # noqa: E402

WB = RF.WB
SITE_DATA = os.path.join(os.path.dirname(HERE), 'MyFantasyFootball Files', 'data')
MIN_DAYS, LATE_DAYS, MIN_GAMES = 21, 42, 3
S_EARLY, S_LATE = 0.5, 0.75
TOP = 250


def _js_obj(path, var):
    s = open(path, encoding='utf-8').read()
    i = s.index(var)
    return json.JSONDecoder().raw_decode(s, s.index('{', i))[0]


def freeze_date():
    """Last date our tracked KTC values changed. Equal to the last tracked date = not frozen."""
    o = os.environ.get('KTC_ROLL_FREEZE')      # test hook: pretend the copy froze on this (real, tracked) list date
    if o:
        return dt.date.fromisoformat(o), dt.date.today()
    H = _js_obj(os.path.join(SITE_DATA, 'ktc_history.js'), 'KTC_HISTORY')
    names = [k for k in H['v1'] if not k[:4].isdigit()]
    dates = H['dates']
    for i in range(len(dates) - 1, 0, -1):
        a = [(H['v1'][n][i], H['v1'][n][i - 1]) for n in names if H['v1'][n][i] and H['v1'][n][i - 1]]
        if a and np.mean([x != y for x, y in a]) > 0.05:
            return dt.date.fromisoformat(dates[i]), dt.date.fromisoformat(dates[-1])
    return dt.date.fromisoformat(dates[0]), dt.date.fromisoformat(dates[-1])


def _site_maps():
    s = open(os.path.join(SITE_DATA, 'ktc_rankings.js'), encoding='utf-8').read()
    out = {}
    import re
    for var, key in (('KTC_1QB', 'oneQBValues'), ('KTC_SF', 'superflexValues')):
        m = re.search(r'\b' + var + r'\s*=\s*\{', s)
        out[key] = {norm(k): v for k, v in json.JSONDecoder().raw_decode(s, m.end() - 1)[0].items()}
    return out


def ensure_frozen_list(fz):
    """The frozen day's values as a tracked list file. Player fields come from the latest archived list."""
    f = os.path.join(WB, 'wb_%s000000.json' % fz.strftime('%Y%m%d'))
    have = sorted(glob.glob(os.path.join(WB, 'wb_*.json')))
    if os.path.exists(f) or (have and os.path.basename(have[-1])[3:11] >= fz.strftime('%Y%m%d')):
        return f if os.path.exists(f) else have[-1], False
    P = json.load(open(have[-1], encoding='utf-8'))
    maps = _site_maps()
    keep = []
    for p in P:
        k = norm(p.get('playerName'))
        if p.get('position') == 'RDP' or all(k in mp for mp in maps.values()):
            for key, mp in maps.items():
                if k in mp:
                    p.setdefault(key, {})['value'] = mp[k]
            keep.append(p)
    json.dump(keep, open(f, 'w', encoding='utf-8'))
    return f, True


def share(lag_days, team_games):
    if lag_days < MIN_DAYS or team_games < MIN_GAMES:
        return 0.0
    return S_EARLY if lag_days < LATE_DAYS else S_LATE


def roll(fmt, T0, T1, train_before=None):
    """Rolled values for the list frozen at T0, as of T1. train_before: only learn from windows that ended before it."""
    P = pd.read_parquet(os.path.join(WB, 'panel.parquet'))
    P = RF.fmt_cols(P[P.full & P.age.notna()].copy(), fmt)
    A = P[P.date == pd.Timestamp(T0)]
    if not len(A):
        raise RuntimeError('no tracked list on %s' % T0)
    X = pd.read_parquet(os.path.join(WB, 'roll_pairs%s.parquet' % RF.SUF[fmt]))
    X = X[X.y.notna()]
    if train_before is not None:
        X = X[X.T1 < pd.Timestamp(train_before)]
    feats = RF.T0F + RF.WINF
    m = RF.gb().fit(X[feats], X.y)
    Z = RF.finish(pd.DataFrame(RF.pair_rows(A[A.k1 <= TOP], pd.Timestamp(T0), pd.Timestamp(T1), 'live', None, RF.load_ctx())))
    lag = (pd.Timestamp(T1) - pd.Timestamp(T0)).days
    games = float(Z.tgw.median())
    s = share(lag, games)
    Z['pred'] = m.predict(Z[feats])
    out = A[['kid', 'name', 'pos', 'n1', 'k1']].rename(columns={'n1': 'v0', 'k1': 'rank0'}).copy()
    mv = dict(zip(Z.kid, Z.pred))
    out['pred'] = out.kid.map(mv)
    out['vroll'] = np.where(out.pred.notna(), (out.v0 + 300) * np.exp(s * out.pred.fillna(0)) - 300, out.v0)
    out['rank'] = out.vroll.rank(ascending=False, method='first').astype(int)
    out.attrs.update(freeze=str(pd.Timestamp(T0).date()), asof=str(pd.Timestamp(T1).date()), lag=lag, games=games, share=s)
    return out


def write_live(rolled):
    """live.json for the panel: the frozen list's players with today's rolled values ({fmt: roll() frame})."""
    have = sorted(glob.glob(os.path.join(WB, 'wb_*.json')))
    P = json.load(open(have[-1], encoding='utf-8'))
    vals = {key: dict(zip(rolled[fmt].kid, rolled[fmt].vroll)) for fmt, key in (('1qb', 'oneQBValues'), ('sf', 'superflexValues')) if fmt in rolled}
    keep = []
    for p in P:
        if p.get('position') == 'RDP':
            continue
        ok = True
        for key, mp in vals.items():
            v = mp.get(p.get('playerID'))
            if v is None:
                ok = False
                break
            p.setdefault(key, {})['value'] = float(v)
        if ok:
            keep.append(p)
    json.dump(keep, open(os.path.join(WB, 'live.json'), 'w', encoding='utf-8'))
    return len(keep)


def simulate(day, fmt):
    P = pd.read_parquet(os.path.join(WB, 'panel.parquet'))
    P = RF.fmt_cols(P[P.full].copy(), fmt)
    T0 = pd.Timestamp(day)
    later = sorted(d for d in P.date.unique() if d > T0)
    print('%s: freeze the real list of %s, roll with a model that only saw windows ended before %d' % (fmt, T0.date(), T0.year))
    for T1 in later[:3]:
        r = roll(fmt, T0, T1, train_before=pd.Timestamp(T0.year, 1, 1))
        real = P[P.date == T1].set_index('kid').n1
        z = r[r.rank0 <= 150].copy()
        z['real'] = z.kid.map(real).fillna(0)
        e0 = ((z.v0 - z.real).abs() / z.real.clip(lower=500)).median()
        e1 = ((z.vroll - z.real).abs() / z.real.clip(lower=500)).median()
        print('   to %s (%3d days, %.0f team games, share %.2f): order match frozen %.3f -> rolled %.3f | typical miss %.1f%% -> %.1f%%'
              % (T1.date(), r.attrs['lag'], r.attrs['games'], r.attrs['share'], spearmanr(z.v0, z.real)[0], spearmanr(z.vroll, z.real)[0], 100 * e0, 100 * e1))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--simulate')
    ap.add_argument('--fmt', default='1qb')
    a = ap.parse_args()
    if a.simulate:
        simulate(a.simulate, a.fmt)
    else:
        fz, last = freeze_date()
        print('KTC values last changed %s; last tracked date %s; today %s -> %d days frozen' % (fz, last, dt.date.today(), (dt.date.today() - fz).days))
