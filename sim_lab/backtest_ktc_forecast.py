#!/usr/bin/env python3
"""
backtest_ktc_forecast.py - can we PREDICT where a player's KTC value goes over the next 1-6 months?
(Jack 2026-11-24: "the goal is to create more accurate ktc values ... more true predictive values
... a big leg up for players that are sell highs or buy lows in season/offseason")

For every tracked full KTC list (date T) and every player in its top 200: everything known ON date T
    price     value / rank that day
    cycle     position, age, experience, draft capital, time of year (the yearly cycle is learned
              from these together: older RBs / WRs bleed in the fall, the draft class pushes vets
              down in spring, ...)
    form      trailing-year PPR / game, games, points over the starter line; last-60-days PPR / game
              vs his trailing rate; team games missed in the last 60 days
    market    KTC's own move over the last 1, 3 and 6 months, distance from his peak
Target: the real change in his KTC value (rank scale) over the next 1 / 2 / 3 / 6 months.

Frozen KTC says "no change", so its skill at this is zero by construction. Graded forward in time
(trained only on moves that had finished before the test year) and leave-one-year-out:
    move corr      rank correlation of predicted vs real move, inside each list
    BUY / SELL     real move of the top / bottom 10% and 20% of predicted moves (KTC top 150)
    built up in steps so we can see what carries it: cycle -> + form -> + market momentum

Usage: python backtest_ktc_forecast.py [--rebuild]
"""
import argparse
import os
import sys
import warnings

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor

warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
WB = os.path.join(HERE, '_dyn_cache', 'ktc_wb')
import ktc_lasting_panel as KP  # noqa: E402
from backtest_ktc_rollforward import KTC2NFL, LAGS  # noqa: E402

SUF = {'1qb': '', 'sf': '_sf'}
CYCLE = ['price', 'krank', 'is_qb', 'is_rb', 'is_wr', 'is_te', 'age', 'exp', 'lpick', 'doy_s', 'doy_c', 'lag']
FORM = ['ppg1', 'g1', 'vor1', 'par1', 'ppgR', 'gR', 'missR', 'surpR', 'vorR', 'tgt_sh', 'car_sh']
MKT = ['m1', 'm3', 'm6', 'dd']
LOG = None


def out(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    LOG.write(s + '\n')


def build(fmt='1qb'):
    P = pd.read_parquet(os.path.join(WB, 'panel.parquet'))
    P = P[P.full & P.age.notna()].copy()
    if fmt == 'sf':      # same code, superflex value / rank columns
        P['n1'], P['k1'], P['n1_m6'], P['n1_peak'] = P['ns'], P['ks'], P['ns_m6'], P['ns_peak']
    full = sorted(P.date.unique())
    W = KP.player_weeks().sort_values('gameday')
    byp = {p: g for p, g in W.groupby('pid')}
    tg = {t: np.sort(g.gameday.unique()) for t, g in W.groupby('team')}
    val = {d: P[P.date == d].set_index('kid').n1 for d in full}

    def back(T, days, tol=12):
        c = [d for d in full if d < T and abs((T - d).days - days) <= tol]
        return min(c, key=lambda d: abs((T - d).days - days)) if c else None

    rows = []
    for T in full:
        A = P[(P.date == T) & (P.k1 <= 200)]
        b1, b3 = back(T, 30), back(T, 91)
        t60 = T - pd.Timedelta(days=60)
        fut = {}
        for lag, tol, lab in LAGS:
            c = [d for d in full if d > T and abs((d - T).days - lag) <= tol]
            if c:
                fut[lab] = min(c, key=lambda d: abs((d - T).days - lag))
        if not fut:
            if T != full[-1]:
                continue
            fut = {lab: None for _, _, lab in LAGS}      # today's list: traits only, no outcome yet
        for r in A.itertuples():
            g = byp.get(r.gsis)
            team = KTC2NFL.get(r.team, r.team)
            gR = 0; ppgR = np.nan; vorR = 0.0
            if g is not None:
                w = g[(g.gameday >= t60) & (g.gameday < T)]
                if len(w):
                    gR = len(w); ppgR = float(w.ppr.mean()); vorR = float((w.ppr - KP.REPL[r.pos]).sum()); team = w.team.iloc[-1]
                else:
                    prev = g[g.gameday < T]
                    if len(prev):
                        team = prev.team.iloc[-1]
            tgd = tg.get(team)
            tgR = int(((tgd >= np.datetime64(t60)) & (tgd < np.datetime64(T))).sum()) if tgd is not None else 0
            tgR = max(tgR, gR)
            base = {'kid': r.kid, 'name': r.name, 'pos': r.pos, 'T': T, 'v0': r.n1, 'krank': r.k1, 'age': r.age, 'exp': r.exp, 'opick': r.opick,
                    'ppg1': r.ppg1, 'g1': r.g1, 'vor1': r.vor1, 'par1': r.par1, 'tgt_sh': r.tgt_sh, 'car_sh': r.car_sh,
                    'ppgR': ppgR, 'gR': gR, 'missR': tgR - gR if tgR else np.nan, 'vorR': vorR if tgR else np.nan,
                    'surpR': (ppgR - r.ppg1) if (gR and r.ppg1 == r.ppg1) else np.nan, 'inseason': int(tgR > 0),
                    'vb1': float(val[b1].get(r.kid, np.nan)) if b1 is not None else np.nan,
                    'vb3': float(val[b3].get(r.kid, np.nan)) if b3 is not None else np.nan,
                    'n1_m6': r.n1_m6, 'n1_peak': r.n1_peak}
            for lab, T2 in fut.items():
                d = dict(base)
                if T2 is None:
                    nd = [l[0] for l in LAGS if l[2] == lab][0]
                    d.update({'lagc': lab, 'T2': T + pd.Timedelta(days=nd), 'lag': nd, 'v1': np.nan})
                else:
                    d.update({'lagc': lab, 'T2': T2, 'lag': (T2 - T).days, 'v1': float(val[T2].get(r.kid, 0.0))})
                rows.append(d)
    X = pd.DataFrame(rows)
    X['price'] = X.v0
    for p in ('QB', 'RB', 'WR', 'TE'):
        X['is_' + p.lower()] = (X.pos == p).astype(float)
    X['lpick'] = np.log(X.opick.clip(1, 262))
    doy = X['T'].dt.dayofyear
    X['doy_s'], X['doy_c'] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
    for c, b in (('m1', 'vb1'), ('m3', 'vb3'), ('m6', 'n1_m6')):
        X[c] = np.log((X.v0 + 300) / (X[b] + 300))
    X['dd'] = X.v0 / np.maximum(X.v0, X.n1_peak.fillna(0)).replace(0, np.nan)
    X['y'] = np.log((X.v1 + 300) / (X.v0 + 300))
    X['yr'] = X['T'].dt.year
    X.to_parquet(os.path.join(WB, 'forecast_rows%s.parquet' % SUF[fmt]), index=False)
    return X


def gb():
    return HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=60, l2_regularization=2.0, random_state=0)


def predict(X, feats, mode):
    pr = pd.Series(np.nan, index=X.index)
    for Y in sorted(X.yr.unique()):
        te = X.yr == Y
        tr = (X.T2 < pd.Timestamp(Y, 1, 1)) if mode == 'forward' else (X.yr != Y)
        if tr.sum() < 3000 or te.sum() < 200:
            continue
        pr[te] = gb().fit(X.loc[tr, feats], X.loc[tr, 'y']).predict(X.loc[te, feats])
    return pr


def pct(x):
    return 100 * (np.exp(x) - 1)


def grade(X, cols, label):
    out('\n  %s' % label)
    out('    %-9s %-11s %5s | %s' % ('horizon', 'season', 'lists', ' | '.join('%-34s' % c[1] for c in cols)))
    out('    %-9s %-11s %5s | %s' % ('', '', '', ' | '.join('%-34s' % 'corr   BUY20  SELL20  BUY10  SELL10' for _ in cols)))
    for lag, tol, lab in LAGS:
        for seas, sl in ((1, 'in season'), (0, 'off season')):
            Z = X[(X.lagc == lab) & (X.inseason == seas) & (X.krank <= 150) & X[cols[-1][0]].notna()]
            if Z.groupby('T').ngroups < 3:
                continue
            cells = []
            for c, _ in cols:
                cr, b20, s20, b10, s10 = [], [], [], [], []
                for T, z in Z.groupby('T'):
                    cr.append(spearmanr(z[c], z.y)[0])
                    q = z[c].quantile([.1, .2, .8, .9]).tolist()
                    b20.append(z[z[c] >= q[2]].y.mean()); s20.append(z[z[c] <= q[1]].y.mean())
                    b10.append(z[z[c] >= q[3]].y.mean()); s10.append(z[z[c] <= q[0]].y.mean())
                cells.append('%+.3f %+5.1f%% %+5.1f%% %+5.1f%% %+5.1f%%  ' % (np.mean(cr), pct(np.mean(b20)), pct(np.mean(s20)), pct(np.mean(b10)), pct(np.mean(s10))))
            out('    %-9s %-11s %5d | %s' % (lab, sl, Z.groupby('T').ngroups, ' | '.join(cells)))


def by_year(X, col):
    out('\n  full model, BUY 20%% minus SELL 20%% real move, by test year (KTC top 150):')
    for lag, tol, lab in LAGS:
        Z = X[(X.lagc == lab) & (X.krank <= 150) & X[col].notna()]
        parts = []
        for y, zy in Z.groupby('yr'):
            sp = []
            for T, z in zy.groupby('T'):
                q = z[col].quantile([.2, .8]).tolist()
                sp.append(z[z[col] >= q[1]].y.mean() - z[z[col] <= q[0]].y.mean())
            parts.append('%d %+5.1f pts (%d lists)' % (y, 100 * np.mean(sp), len(sp)))
        out('    %-9s %s' % (lab, '   '.join(parts)))


def importance(X, feats):
    rng = np.random.default_rng(5)
    lab = {'price': 'price today', 'age': 'age', 'exp': 'experience', 'lpick': 'draft capital', 'doy_s': 'time of year', 'doy_c': 'time of year (2)',
           'ppg1': 'trailing-year PPR/game', 'g1': 'games, trailing year', 'vor1': 'points over starter line, trailing year', 'par1': 'PPR/game over the starter line',
           'ppgR': 'PPR/game, last 60 days', 'gR': 'games, last 60 days', 'missR': 'team games missed, last 60 days', 'surpR': 'last 60 days vs his trailing rate',
           'vorR': 'points over starter line, last 60 days', 'm1': 'KTC move, last month', 'm3': 'KTC move, last 3 months', 'm6': 'KTC move, last 6 months',
           'dd': 'distance from his KTC peak', 'tgt_sh': 'target share', 'car_sh': 'carry share', 'krank': 'KTC rank today'}
    for seas, sl in ((1, 'IN SEASON'), (0, 'OFF SEASON')):
        te = (X.yr >= 2025) & (X.inseason == seas) & (X.lagc == '3 months') & (X.krank <= 150)
        tr = X.T2 < pd.Timestamp(2025, 1, 1)
        if te.sum() < 300:
            continue
        m = gb().fit(X.loc[tr, feats], X.loc[tr, 'y'])
        B = X[te]
        b0 = spearmanr(m.predict(B[feats]), B.y)[0]
        d = {}
        for f in feats:
            C = B.copy(); C[f] = rng.permutation(C[f].to_numpy())
            d[f] = b0 - spearmanr(m.predict(C[feats]), B.y)[0]
        out('\n  what carries the 3-month forecast, %s (2025-26 held out, move corr %.3f): ' % (sl, b0)
            + ', '.join('%s %.3f' % (lab.get(f, f), v) for f, v in sorted(d.items(), key=lambda kv: -kv[1])[:7]))


def main():
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument('--rebuild', action='store_true')
    ap.add_argument('--fmt', default='1qb', choices=('1qb', 'sf'))
    ap.add_argument('--today-only', action='store_true', help='rebuild the rows (with the latest list) and stop')
    a = ap.parse_args()
    sx = SUF[a.fmt]
    LOG = open(os.path.join(WB, ('forecast_today%s.log' if a.today_only else 'forecast%s.log') % sx), 'w', encoding='utf-8')
    f = os.path.join(WB, 'forecast_rows%s.parquet' % sx)
    X = build(a.fmt) if a.rebuild or not os.path.exists(f) else pd.read_parquet(f)
    X[X.v1.isna()].to_parquet(os.path.join(WB, 'forecast_today%s.parquet' % sx), index=False)
    X = X[X.v1.notna()].reset_index(drop=True)
    if a.today_only:
        return
    out('format %s' % a.fmt)
    out('KTC move forecast | %d rows | %d list dates %s..%s | players %d' % (len(X), X['T'].nunique(), X['T'].min().date(), X['T'].max().date(), X.kid.nunique()))
    steps = (('p_cycle', 'cycle only', CYCLE), ('p_form', '+ form / health', CYCLE + FORM), ('p_all', '+ KTC momentum (full)', CYCLE + FORM + MKT))
    for mode, lab in (('forward', 'FORWARD IN TIME (trained only on moves finished before the test year)'), ('loyo', 'LEAVE ONE YEAR OUT')):
        for c, _, feats in steps:
            X[c] = predict(X, feats, mode)
        out('\n=== %s ===   real move of the players the model liked most / least; frozen KTC = 0 on every column' % lab)
        grade(X, [(c, n) for c, n, _ in steps], 'KTC top 150 on the list date')
        by_year(X, 'p_all')
        if mode == 'forward':
            importance(X, CYCLE + FORM + MKT)
            X[['kid', 'name', 'pos', 'T', 'T2', 'lagc', 'v0', 'v1', 'krank', 'y', 'p_cycle', 'p_form', 'p_all', 'inseason']].to_parquet(os.path.join(WB, 'forecast_preds_forward%s.parquet' % sx), index=False)
    LOG.close()


if __name__ == '__main__':
    main()
