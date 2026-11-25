#!/usr/bin/env python3
"""
backtest_ktc_rollforward.py - can we roll FROZEN KTC values forward in-house?
(Jack 2026-11-24: "can we use the ktc values we tracked" -> "Yes, test it")

Setup: KTC's page stopped carrying the player list on 2026-11-24. Take a tracked KTC list at T0,
pretend it is the last one we ever get, and predict the list at T0 + 1 / 2 / 3 / 6 months from
things we hold ourselves:
    drift     price, position, age, experience, draft capital, trailing production (known at T0)
    played    games played vs team games since T0, PPR per game since T0 vs his trailing rate,
              points vs "every game at his old rate", target / carry share change
    draft     if an NFL draft fell in the window: draft capital his team spent at his position
Rookies (not on the list before the draft) are priced from draft slot + position (+ JM).

Graded against what KTC actually did (full archived lists 2021-26, rank-scaled values):
    FROZEN  = leave the T0 values alone          DRIFT = T0 info only          ROLL = everything
Forward in time (train on windows that ended before the test year) and leave-one-year-out.
Then the downstream check: MFF VALUE accuracy with a fresh / frozen / rolled price.

Usage: python backtest_ktc_rollforward.py [--rebuild]
"""
import argparse
import json
import os
import pickle
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
CACHE = os.path.join(os.path.dirname(HERE), 'pbp_cache')
import ktc_lasting_panel as KP  # noqa: E402

LAGS = ((30, 12, '1 month'), (61, 12, '2 months'), (91, 12, '3 months'), (190, 35, '6 months'))
DRAFTS = {2021: '2021-04-29', 2022: '2022-04-28', 2023: '2023-04-27', 2024: '2024-04-25', 2025: '2025-04-24', 2026: '2026-04-23'}
KTC2NFL = {'GBP': 'GB', 'JAC': 'JAX', 'KCC': 'KC', 'LVR': 'LV', 'NEP': 'NE', 'NOS': 'NO', 'SFO': 'SF', 'TBB': 'TB'}
PFR2NFL = {'GNB': 'GB', 'KAN': 'KC', 'LVR': 'LV', 'NWE': 'NE', 'NOR': 'NO', 'SFO': 'SF', 'TAM': 'TB'}
RW = {1: 1.0, 2: 0.6, 3: 0.35}
T0F = ['price', 'krank', 'is_qb', 'is_rb', 'is_wr', 'is_te', 'age', 'exp', 'lpick', 'ppg1', 'g1', 'vor1', 'm6', 'dd', 'lag', 'month', 'draft_in']
WINF = ['gw', 'tgw', 'miss', 'ppgw', 'surprise', 'gap', 'vorw', 'd_tgt', 'd_car', 'comp', 'played_sh']
LOG = None


def out(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    LOG.write(s + '\n')


def load_ctx():
    """Game tables + draft capital by team / position, shared by the backtest and the live roll (ktc_roll.py)."""
    W = KP.player_weeks().sort_values('gameday')
    byp = {p: g for p, g in W.groupby('pid')}
    tg = {t: np.sort(g.gameday.unique()) for t, g in W.groupby('team')}
    D = pd.read_parquet(os.path.join(CACHE, 'draft_picks.parquet'), columns=['season', 'round', 'team', 'position'])
    D = D[D.season >= 2021]
    D['team'] = D.team.map(lambda t: PFR2NFL.get(t, t))
    D['w'] = D['round'].map(lambda r: RW.get(int(r), 0.1))
    comp = D.groupby(['season', 'team', 'position']).w.sum().to_dict()
    return byp, tg, comp


def pair_rows(A, T0, T1, lab, v1, ctx):
    """One row per player of list A (frozen at T0): what happened on the field between T0 and T1."""
    byp, tg, comp = ctx
    rows = []
    dy = [y for y, dd in DRAFTS.items() if T0 < pd.Timestamp(dd) <= T1]
    for r in A.itertuples():
        g = byp.get(r.gsis)
        team = KTC2NFL.get(r.team, r.team)
        gw = tgw = 0
        ppgw = d_tgt = d_car = np.nan
        tot = vorw = 0.0
        if g is not None:
            w = g[(g.gameday >= T0) & (g.gameday < T1)]
            if len(w):
                team = w.team.iloc[-1]
                gw = len(w); tot = float(w.ppr.sum()); ppgw = tot / gw
                vorw = float((w.ppr - KP.REPL[r.pos]).sum())
                tt, tc = w.team_tgt.sum(), w.team_car.sum()
                if tt and r.tgt_sh == r.tgt_sh:
                    d_tgt = float(w.tgt.sum() / tt) - r.tgt_sh
                if tc and r.car_sh == r.car_sh:
                    d_car = float(w.car.sum() / tc) - r.car_sh
            else:
                prev = g[g.gameday < T0]
                if len(prev):
                    team = prev.team.iloc[-1]
        tgd = tg.get(team)
        if tgd is not None:
            tgw = int(((tgd >= np.datetime64(T0)) & (tgd < np.datetime64(T1))).sum())
        tgw = max(tgw, gw)
        rows.append({'kid': r.kid, 'name': r.name, 'pos': r.pos, 'T0': T0, 'T1': T1, 'lagc': lab, 'lag': (T1 - T0).days,
                     'v0': r.n1, 'v1': float(v1.get(r.kid, 0.0)) if v1 is not None else np.nan, 'krank': r.k1, 'age': r.age, 'exp': r.exp, 'opick': r.opick,
                     'ppg1': r.ppg1, 'g1': r.g1, 'vor1': r.vor1, 'n1_m6': r.n1_m6, 'n1_peak': r.n1_peak,
                     'gw': gw, 'tgw': tgw, 'miss': tgw - gw, 'ppgw': ppgw, 'vorw': vorw,
                     'surprise': (ppgw - r.ppg1) if (gw and r.ppg1 == r.ppg1) else np.nan,
                     'gap': (tot - r.ppg1 * tgw) if (tgw and r.ppg1 == r.ppg1) else np.nan,
                     'd_tgt': d_tgt, 'd_car': d_car, 'played_sh': gw / tgw if tgw else np.nan,
                     'draft_in': float(bool(dy)), 'comp': float(sum(comp.get((y, team, r.pos), 0.0) for y in dy))})
    return rows


def finish(X):
    X['price'] = X.v0
    for p in ('QB', 'RB', 'WR', 'TE'):
        X['is_' + p.lower()] = (X.pos == p).astype(float)
    X['lpick'] = np.log(X.opick.clip(1, 262))
    X['m6'] = np.log((X.v0 + 300) / (X.n1_m6.fillna(0) + 300)).where(X.n1_m6.notna())
    X['dd'] = X.v0 / np.maximum(X.v0, X.n1_peak.fillna(0)).replace(0, np.nan)
    X['month'] = X.T0.dt.month
    X['y'] = np.log((X.v1 + 300) / (X.v0 + 300))
    X['yr'] = X.T0.dt.year
    X['inseason'] = (X.tgw > 0).astype(int)
    return X


SUF = {'1qb': '', 'sf': '_sf'}


def fmt_cols(P, fmt):
    """Superflex runs through the same code on the superflex value / rank columns."""
    if fmt == 'sf':
        P = P.copy()
        P['n1'], P['k1'], P['n1_m6'], P['n1_peak'] = P['ns'], P['ks'], P['ns_m6'], P['ns_peak']
    return P


def build(fmt='1qb'):
    P = pd.read_parquet(os.path.join(WB, 'panel.parquet'))
    P = fmt_cols(P[P.full].copy(), fmt)
    full = sorted(P.date.unique())
    ctx = load_ctx()
    val = {d: P[P.date == d].set_index('kid').n1 for d in full}
    rows = []
    for T0 in full:
        A = P[(P.date == T0) & (P.k1 <= 250)]
        for lag, tol, lab in LAGS:
            c = [d for d in full if d > T0 and abs((d - T0).days - lag) <= tol]
            if not c:
                continue
            T1 = min(c, key=lambda d: abs((d - T0).days - lag))
            rows += pair_rows(A, T0, T1, lab, val[T1], ctx)
    X = finish(pd.DataFrame(rows))
    X.to_parquet(os.path.join(WB, 'roll_pairs%s.parquet' % SUF[fmt]), index=False)
    return X


def gb():
    return HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=50, l2_regularization=1.0, random_state=0)


def predict(X, feats, mode):
    """Out-of-sample predicted move for every row it can cover."""
    pr = pd.Series(np.nan, index=X.index)
    for Y in sorted(X.yr.unique()):
        te = X.yr == Y
        tr = (X.T1 < pd.Timestamp(Y, 1, 1)) if mode == 'forward' else (X.yr != Y)
        if tr.sum() < 3000 or te.sum() < 200:
            continue
        pr[te] = gb().fit(X.loc[tr, feats], X.loc[tr, 'y']).predict(X.loc[te, feats])
    return pr


def grade(X, pr_cols, mask, label):
    out('\n  %s' % label)
    out('    %-10s %6s | %-34s | %-34s | %-34s' % ('age', 'pairs', 'rank corr with real KTC', 'typical miss (median)', 'players within 10% of real'))
    out('    %-10s %6s | %-34s | %-34s | %-34s' % ('', '', '  frozen   drift    roll', '  frozen   drift    roll', '  frozen   drift    roll'))
    for lag, tol, lab in LAGS:
        Z = X[mask & (X.lagc == lab) & (X.krank <= 150) & X[pr_cols[-1]].notna()]
        if len(Z) < 300:
            continue
        acc = {k: [[], [], []] for k in ['frozen'] + pr_cols}
        for (t0, t1), z in Z.groupby(['T0', 'T1']):
            preds = {'frozen': z.v0}
            for c in pr_cols:
                preds[c] = (z.v0 + 300) * np.exp(z[c]) - 300
            for k, p in preds.items():
                err = (p - z.v1).abs() / z.v1.clip(lower=500)
                acc[k][0].append(spearmanr(p, z.v1)[0]); acc[k][1].append(err.median()); acc[k][2].append((err <= .10).mean())
        n = len(acc['frozen'][0])
        cells = ['  '.join('%7.3f' % np.mean(acc[k][0]) for k in acc), '  '.join('%6.1f%%' % (100 * np.mean(acc[k][1])) for k in acc),
                 '  '.join('%6.0f%%' % (100 * np.mean(acc[k][2])) for k in acc)]
        out('    %-10s %6d | %-34s | %-34s | %-34s' % (lab, n, cells[0], cells[1], cells[2]))


def movers(X, col):
    out('\n  does ROLL call the big moves? (in-season windows, KTC top 150 at the start, forward-tested)')
    for lag, tol, lab in LAGS[:3]:
        Z = X[(X.inseason == 1) & (X.lagc == lab) & (X.krank <= 150) & X[col].notna()].copy()
        if len(Z) < 300:
            continue
        Z['act'] = Z.v1 / Z.v0.clip(lower=1) - 1
        Z['prd'] = ((Z.v0 + 300) * np.exp(Z[col]) - 300) / Z.v0.clip(lower=1) - 1
        up, dn = Z[Z.prd >= .10], Z[Z.prd <= -.10]
        bu, bd = Z[Z.act >= .15], Z[Z.act <= -.15]
        out('    %-9s move corr %.3f | ROLL said up 10%%+: %4d rows, real move %+5.1f%% | said down 10%%+: %4d rows, real move %+5.1f%% | of real 15%%+ risers ROLL had the direction right %2.0f%%, fallers %2.0f%%'
            % (lab, spearmanr(Z.prd, Z.act)[0], len(up), 100 * up.act.mean(), len(dn), 100 * dn.act.mean(), 100 * (bu.prd > 0).mean(), 100 * (bd.prd < 0).mean()))


def importance(X, feats):
    rng = np.random.default_rng(3)
    te = (X.yr >= 2025) & (X.inseason == 1) & (X.lagc == '2 months') & (X.krank <= 150)
    tr = X.T1 < pd.Timestamp(2025, 1, 1)
    m = gb().fit(X.loc[tr, feats], X.loc[tr, 'y'])
    B = X[te]
    b0 = spearmanr(m.predict(B[feats]), B.y)[0]
    out('\n  what carries the in-season roll (2-month windows, 2025-26 held out; move corr %.3f):' % b0)
    d = {}
    for f in feats:
        C = B.copy(); C[f] = rng.permutation(C[f].to_numpy())
        d[f] = b0 - spearmanr(m.predict(C[feats]), B.y)[0]
    lab = {'gap': 'points vs "every game at his old rate"', 'surprise': 'PPR/game since vs trailing', 'miss': 'games missed since', 'ppgw': 'PPR/game since',
           'vorw': 'points over starter line since', 'd_tgt': 'target share change', 'd_car': 'carry share change', 'played_sh': 'share of team games played',
           'price': 'price at the freeze', 'age': 'age', 'm6': 'KTC move before the freeze', 'comp': 'draft capital spent at his position', 'ppg1': 'trailing PPR/game'}
    for f, v in sorted(d.items(), key=lambda kv: -kv[1])[:9]:
        out('    %-44s %.3f' % (lab.get(f, f), v))


def rookies():
    out('\n=== ROOKIES: price a drafted rookie with no KTC value (first full list after each draft) ===')
    P = pd.read_parquet(os.path.join(WB, 'panel.parquet'))
    P = P[P.full]
    first = {2021: '2021-07-24', 2022: '2022-05-16', 2024: '2024-06-22', 2025: '2025-05-10', 2026: '2026-05-19'}
    try:
        from dyn_common import load_jm, _norm_name
        jm = load_jm()
    except Exception:  # noqa: BLE001
        jm, _norm_name = {}, None
    R = []
    for y, d in first.items():
        z = P[(P.date == pd.Timestamp(d)) & (P.exp == 0) & (P.rook_yr == y) & (P.opick < 262)].copy()
        z['cls'] = y
        R.append(z)
    R = pd.concat(R)
    R['lpick'] = np.log(R.opick)
    for p in ('QB', 'RB', 'WR', 'TE'):
        R['is_' + p.lower()] = (R.pos == p).astype(float)
    R['jm'] = [jm.get((_norm_name(n), p), np.nan) if jm else np.nan for n, p in zip(R.name, R.pos)]
    R['ly'] = np.log(R.n1 + 300)
    out('  classes: ' + ', '.join('%d n=%d' % (y, (R.cls == y).sum()) for y in sorted(R.cls.unique())) + ' | JM matched %d of %d' % (R.jm.notna().sum(), len(R)))
    F0 = ['lpick', 'is_qb', 'is_rb', 'is_wr', 'is_te', 'age']
    res = {'slot + position': [], 'slot + position + JM': []}
    for y in sorted(R.cls.unique()):
        tr, te = R[R.cls != y], R[R.cls == y]
        for nm, F in (('slot + position', F0), ('slot + position + JM', F0 + ['jm'])):
            m = HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=8, random_state=0).fit(tr[F], tr.ly)
            p = np.exp(m.predict(te[F])) - 300
            err = (p - te.n1).abs() / te.n1.clip(lower=500)
            res[nm].append((y, spearmanr(p, te.n1)[0], err.median(), (err <= .2).mean(), len(te)))
            if nm == 'slot + position':
                R.loc[te.index, 'pred'] = p
    for nm, v in res.items():
        out('  %-22s rank corr %.3f | typical miss %.0f%% | within 20%% of real: %.0f%% | by class: %s'
            % (nm, np.mean([x[1] for x in v]), 100 * np.mean([x[2] for x in v]), 100 * np.mean([x[3] for x in v]), '  '.join('%d %.2f' % (x[0], x[1]) for x in v)))
    return R


def downstream(X, R):
    out('\n=== DOWNSTREAM: MFF VALUE accuracy when the KTC price is 6-7 months old (crosses the draft) ===')
    out('    same total-return grading as the re-tune; price = fresh / frozen / rolled in-house (veterans rolled, rookies from draft slot)')
    pools = pickle.load(open(os.path.join(WB, 'pools_1qb.pkl'), 'rb'))
    coef = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    feats = T0F + WINF
    L = X[X.lagc == '6 months']
    acc = {}
    for Y, T in pools.items():
        d1 = T.date.iloc[0]
        z = L[L.T1 == d1]
        if not len(z):
            continue
        t0 = z.T0.max(); z = z[z.T0 == t0]
        tr = X[X.yr != Y]
        if len(tr) < 3000:
            continue
        m = gb().fit(tr[feats], tr.y)
        rolled = dict(zip(z.kid, (z.v0 + 300) * np.exp(m.predict(z[feats])) - 300))
        frozen = dict(zip(z.kid, z.v0))
        rk = R[R.cls == Y]
        rook = dict(zip(rk.kid, rk.pred))
        cover = np.mean([k in rolled or k in rook for k in T.kid])
        def ranks(src, extra):
            v = np.array([src.get(k, extra.get(k, -1.0)) for k in T.kid], float)
            return np.log(pd.Series(v).rank(ascending=False, method='first').to_numpy())
        P_ = {'fresh': np.log(T.m0.to_numpy()), 'frozen': ranks(frozen, {}), 'rolled': ranks(rolled, rook)}
        ls = np.log(T.s0.to_numpy())
        for k, lm in P_.items():
            m3 = T.m3.to_numpy() + coef[1] * (lm - np.log(T.m0.to_numpy()))
            Z = {'KTC price alone': lm, 'new mix': .25 * m3 + .15 * ls + .75 * lm - T.edge_12.to_numpy(), 'old mix': .5 * m3 + .3 * ls + .5 * lm}
            for h in (1, 2, 3):
                cols = ['vf%d' % i for i in range(1, h + 1)]
                ok = (T['f%d' % h].notna() & T[cols].notna().all(axis=1)).to_numpy()
                if ok.sum() < 60:
                    continue
                yv = (T['f%d' % h] + 12 * T[cols].sum(axis=1)).to_numpy()
                for nm, zz in Z.items():
                    acc.setdefault((nm, k), []).append(spearmanr(-zz[ok], yv[ok])[0])
            acc.setdefault(('match', k), []).append(spearmanr(-lm, -np.log(T.m0.to_numpy()))[0])
        out('    list %d: frozen at %s (%d days old), %.0f%% of the board priced after the roll' % (Y, t0.date(), (d1 - t0).days, 100 * cover))
    out('    %-18s %10s %10s %10s' % ('', 'fresh', 'frozen', 'rolled'))
    for nm in ('match', 'KTC price alone', 'new mix', 'old mix'):
        out('    %-18s %10.3f %10.3f %10.3f' % ('order vs real KTC' if nm == 'match' else nm, *[np.mean(acc[(nm, k)]) for k in ('fresh', 'frozen', 'rolled')]))


def main():
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument('--rebuild', action='store_true')
    ap.add_argument('--fmt', default='1qb', choices=('1qb', 'sf'))
    a = ap.parse_args()
    LOG = open(os.path.join(WB, 'rollforward%s.log' % SUF[a.fmt]), 'w', encoding='utf-8')
    f = os.path.join(WB, 'roll_pairs%s.parquet' % SUF[a.fmt])
    X = build(a.fmt) if a.rebuild or not os.path.exists(f) else pd.read_parquet(f)
    out('format %s' % a.fmt)
    out('roll-forward test | %d rows | %d freeze dates | players %d | windows: %s' % (len(X), X.T0.nunique(), X.kid.nunique(),
        ', '.join('%s %d' % (l[2], X[X.lagc == l[2]].groupby(['T0', 'T1']).ngroups) for l in LAGS)))
    for mode, lab in (('forward', 'FORWARD IN TIME (trained only on windows that ended before the test year; tests 2023-26)'),
                      ('loyo', 'LEAVE ONE YEAR OUT (all years tested)')):
        X['p_drift'] = predict(X, T0F, mode)
        X['p_roll'] = predict(X, T0F + WINF, mode)
        out('\n=== %s ===' % lab)
        grade(X, ['p_drift', 'p_roll'], X.inseason == 1, 'IN SEASON (games were played in the window) - KTC top 150 at the freeze')
        grade(X, ['p_drift', 'p_roll'], X.inseason == 0, 'OFF SEASON (no games in the window)')
        if mode == 'forward':
            movers(X, 'p_roll')
            importance(X, T0F + WINF)
    if a.fmt == '1qb':
        R = rookies()
        downstream(X, R)
    LOG.close()


if __name__ == '__main__':
    main()
