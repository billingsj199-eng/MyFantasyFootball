#!/usr/bin/env python3
"""
research_ktc_lasting.py - KTC lasting-value study (Jack 2026-11-24).

Question: KTC is the public price. Which players' price LASTS 1-3 years, which
melts, and what known-that-day traits tell them apart - i.e. where can we beat
the market long term (not week-to-week spikes)?

Data: ktc_lasting_panel.py (44 full archived KTC lists 2021-01..2026-11, whole
pool, values put on one scale by rank; off the list later = 0).
Pool: players ranked in the top 250 (players only) on the anchor date.

  A  base rates      what a price is worth 1-5 years later, by price tier
  B  who holds       value kept vs the average player bought at the SAME price
                     ("excess", % of price), by position x age, draft capital,
                     track record, production support, momentum, contract, size...
                     player-clustered bootstrap intervals
  C  can a model beat price?   future value ~ price (par) + traits; held-out by
                     PLAYER (5 folds) and FORWARD in time; rank correlation of
                     the part price does not explain + buy/avoid thirds
  D  what carries it  permutation importance of the held-out model

Usage: python research_ktc_lasting.py [--fmt 1qb|sf] [--top 250]
"""
import argparse
import os
import sys
import warnings

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import GroupKFold

warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.join(HERE, '_dyn_cache', 'ktc_wb')
RNG = np.random.default_rng(7)

FEATS = ['price', 'krank', 'is_qb', 'is_rb', 'is_wr', 'is_te', 'age', 'exp', 'lpick', 'ppg1', 'g1', 'ppg2', 'g2',
         'ppg3', 'g3', 'best_ppg', 'top12', 'top24', 'cg', 'tgt_sh', 'car_sh', 'td_sh', 'rush_sh', 'par1', 'vor1',
         'cap_pct', 'c_left', 'vet_deal', 'm6', 'm12', 'dd', 'keep_sh', 'wt', 'ht', 'bmi', 'phase']
LABEL = {'price': 'KTC price today', 'age': 'age', 'lpick': 'draft capital', 'exp': 'experience',
         'ppg1': 'PPR/game last 12 mo', 'ppg2': 'PPR/game 12-24 mo ago', 'ppg3': 'PPR/game 24-36 mo ago',
         'best_ppg': 'best season PPR/game', 'top12': 'top-12 seasons', 'top24': 'top-24 seasons',
         'cg': 'career games', 'g1': 'games last 12 mo', 'tgt_sh': 'target share', 'car_sh': 'carry share',
         'td_sh': 'TD reliance', 'rush_sh': 'rushing share of points', 'par1': 'PPR/game over replacement',
         'vor1': 'value over replacement last 12 mo', 'cap_pct': 'contract size (cap %)', 'c_left': 'contract years left',
         'm6': 'KTC move last 6 mo', 'm12': 'KTC move last 12 mo', 'dd': 'drop from KTC peak',
         'keep_sh': 'crowd keep share', 'wt': 'weight', 'ht': 'height', 'bmi': 'build (BMI)', 'phase': 'time of year'}


def load(fmt, top):
    P = pd.read_parquet(os.path.join(WB, 'panel.parquet'))
    n, k = ('n1', 'k1') if fmt == '1qb' else ('ns', 'ks')
    P = P[P.full].copy()
    P['price'] = P[n]
    P['krank'] = P[k]
    for h in (1, 2, 3, 4, 5):
        P['f%d' % h] = P['%s_f%d' % (n, h)]
    for p in ('QB', 'RB', 'WR', 'TE'):
        P['is_' + p.lower()] = (P.pos == p).astype(float)
    P['lpick'] = np.log(P.opick.clip(1, 262))
    P['m6'] = np.log((P.price + 300) / (P['%s_m6' % n].fillna(0) + 300)).where(P['%s_m6' % n].notna() | (P.exp > 0))
    P['m12'] = np.log((P.price + 300) / (P['%s_m12' % n].fillna(0) + 300)).where(P['%s_m12' % n].notna() | (P.exp > 1))
    pk = np.maximum(P.price, P['%s_peak' % n].fillna(0))
    P['dd'] = P.price / pk.replace(0, np.nan)
    tot = (P.kept + P.traded + P['cut']).replace(0, np.nan)
    P['keep_sh'] = P.kept / tot
    P['bmi'] = 703 * P.wt / (P.ht ** 2)
    P['phase'] = P.date.dt.month
    P['yr'] = P.date.dt.year
    P = P[P.krank <= top].reset_index(drop=True)
    return P


def thin(P, gap=100):
    """Anchor dates at least `gap` days apart (so dense recent months do not dominate tables)."""
    keep, last = [], None
    for d in sorted(P.date.unique()):
        if last is None or (d - last).days >= gap:
            keep.append(d); last = d
    return P[P.date.isin(keep)]


def par_fit(x, y):
    iso = IsotonicRegression(increasing=True, out_of_bounds='clip')
    iso.fit(x, y)
    return iso


def boot(df, col, n=400):
    """Mean of col with a player-clustered 90% interval."""
    g = df.groupby('kid')[col].agg(['sum', 'count'])
    s, c = g['sum'].to_numpy(), g['count'].to_numpy()
    if len(s) < 5:
        return float(s.sum() / max(1, c.sum())), np.nan, np.nan, len(s)
    idx = RNG.integers(0, len(s), (n, len(s)))
    m = s[idx].sum(1) / c[idx].sum(1)
    return float(s.sum() / c.sum()), float(np.quantile(m, .05)), float(np.quantile(m, .95)), len(s)


def out(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    LOG.write(s + '\n')


def section_a(P):
    out('\n=== A. BASE RATES: what a KTC price is worth later (rank-scaled value kept; off the list = 0) ===')
    T = thin(P)
    tiers = [(1, 12), (13, 24), (25, 50), (51, 100), (101, 175), (176, 250)]
    out('%-10s %s' % ('price rank', ''.join('%22s' % ('+%dy kept / hold80 / lose50 (n)' % h) for h in (1, 2, 3))))
    for a, b in tiers:
        line = '%-10s' % ('%d-%d' % (a, b))
        for h in (1, 2, 3):
            x = T[(T.krank >= a) & (T.krank <= b) & T['f%d' % h].notna()]
            if len(x) < 15:
                line += '%34s' % '-'; continue
            r = x['f%d' % h] / x.price
            line += '   %4.0f%% / %3.0f%% / %3.0f%% (%4d)   ' % (100 * r.mean(), 100 * (r >= .8).mean(), 100 * (r <= .5).mean(), len(x))
        out(line)
    out('\n  long horizon (all anchors with a later list): mean value kept')
    for a, b in tiers[:4]:
        line = '  %-8s' % ('%d-%d' % (a, b))
        for h in (1, 2, 3, 4, 5):
            x = T[(T.krank >= a) & (T.krank <= b) & T['f%d' % h].notna()]
            line += '  +%dy %3.0f%% (%d)' % (h, 100 * (x['f%d' % h] / x.price).mean(), len(x)) if len(x) >= 15 else '  +%dy   -' % h
        out(line)


def add_excess(P):
    """excess_h = (future value - average future value of players at the same price) / price."""
    for h in (1, 2, 3):
        m = P['f%d' % h].notna()
        iso = par_fit(P.loc[m, 'price'], P.loc[m, 'f%d' % h])
        P.loc[m, 'par%d' % h] = iso.predict(P.loc[m, 'price'])
        P['ex%d' % h] = (P['f%d' % h] - P['par%d' % h]) / P.price
    return P


def table(P, name, groups, minp=12):
    out('\n--- %s ---   (excess vs same-price average, %% of price; [90%% interval]; players)' % name)
    for lab, mask in groups:
        line = '  %-34s' % lab
        ok = False
        for h in (1, 2, 3):
            x = P[mask & P['ex%d' % h].notna()]
            m, lo, hi, n = boot(x, 'ex%d' % h)
            if n < minp:
                line += '  +%dy %19s' % (h, '-'); continue
            ok = True
            star = '*' if (lo > 0 or hi < 0) else ' '
            line += '  +%dy %+4.0f%%%s[%+4.0f,%+4.0f] %3d' % (h, 100 * m, star, 100 * lo, 100 * hi, n)
        if ok:
            out(line)


def section_b(P):
    out('\n=== B. WHO HOLDS VALUE vs the average player at the SAME price ===')
    out('    (+ = worth more later than the price implied; * = interval excludes 0)')
    T = thin(P, 60)
    pos = {p: T.pos == p for p in ('QB', 'RB', 'WR', 'TE')}
    table(T, 'position', [(p, pos[p]) for p in pos])
    bands = {'QB': [(0, 24), (24, 27), (27, 30), (30, 33), (33, 50)], 'RB': [(0, 22.5), (22.5, 24), (24, 25.5), (25.5, 27), (27, 50)],
             'WR': [(0, 22.5), (22.5, 24.5), (24.5, 26.5), (26.5, 28.5), (28.5, 50)], 'TE': [(0, 23.5), (23.5, 25.5), (25.5, 27.5), (27.5, 30), (30, 50)]}
    g = []
    for p in pos:
        for a, b in bands[p]:
            g.append(('%s age %s-%s' % (p, a if a else '<', b if b < 50 else '+'), pos[p] & (T.age >= a) & (T.age < b)))
    table(T, 'position x age', g)
    top = T.krank <= 100
    table(T[top], 'position x age, price rank 1-100 only', [(l, m[top]) for l, m in g], minp=8)
    rd = [('round 1 pick 1-16', T.opick <= 16), ('round 1 pick 17-32', (T.opick > 16) & (T.opick <= 32)), ('round 2', (T.opick > 32) & (T.opick <= 64)),
          ('round 3', (T.opick > 64) & (T.opick <= 105)), ('day 3 / undrafted', T.opick > 105)]
    table(T, 'draft capital (all)', rd)
    ex = [('rookie season (exp 0)', T.exp == 0), ('year 2', T.exp == 1), ('year 3', T.exp == 2), ('years 4-6', (T.exp >= 3) & (T.exp <= 5)), ('year 7+', T.exp >= 6)]
    table(T, 'experience', ex)
    table(T, 'draft capital x young (exp <= 2)', [(l + ', exp<=2', m & (T.exp <= 2)) for l, m in rd])
    table(T, 'draft capital x veteran (exp >= 3)', [(l + ', exp>=3', m & (T.exp >= 3)) for l, m in rd])
    vet = T.exp >= 2
    table(T, 'track record (veterans, exp >= 2)', [('0 top-24 seasons', vet & (T.top24 == 0)), ('1 top-24 season', vet & (T.top24 == 1)),
          ('2 top-24 seasons', vet & (T.top24 == 2)), ('3+ top-24 seasons', vet & (T.top24 >= 3)),
          ('0 top-12 seasons', vet & (T.top12 == 0)), ('1 top-12 season', vet & (T.top12 == 1)), ('2+ top-12 seasons', vet & (T.top12 >= 2))])
    # production support: is the price above or below what his production ranks?
    T = T.copy()
    T['prank'] = T.groupby('date').vor1.rank(ascending=False, method='first', na_option='bottom')
    gap = np.log(T.prank.clip(1, 250) / T.krank.clip(1, 250))
    v1 = (T.exp >= 1) & (T.g1 >= 6)
    table(T, 'price vs production (played 6+ games last 12 mo)', [
        ('production WAY above price', v1 & (gap < -0.7)), ('production above price', v1 & (gap >= -0.7) & (gap < -0.25)),
        ('in line', v1 & (gap >= -0.25) & (gap <= 0.25)), ('price above production', v1 & (gap > 0.25) & (gap <= 0.7)),
        ('price WAY above production (hype)', v1 & (gap > 0.7))])
    table(T, 'price vs production, by position', [('%s price way above production' % p, v1 & pos[p] & (gap > 0.7)) for p in pos]
          + [('%s production above price' % p, v1 & pos[p] & (gap < -0.25)) for p in pos])
    hm = T.m12.notna()
    table(T, 'KTC move over the last 12 months', [('fell 40%+', hm & (T.m12 < -0.5)), ('fell 15-40%', hm & (T.m12 >= -0.5) & (T.m12 < -0.16)),
          ('flat', hm & (T.m12 >= -0.16) & (T.m12 <= 0.16)), ('rose 15-50%', hm & (T.m12 > 0.16) & (T.m12 <= 0.4)), ('rose 50%+', hm & (T.m12 > 0.4))])
    table(T, 'distance from his KTC peak', [('at peak (>= 95%)', T.dd >= .95), ('80-95% of peak', (T.dd >= .8) & (T.dd < .95)),
          ('60-80% of peak', (T.dd >= .6) & (T.dd < .8)), ('under 60% of peak', T.dd < .6)])
    table(T, 'availability last 12 months (veterans)', [('0-5 games', vet & (T.g1 <= 5)), ('6-11 games', vet & (T.g1 >= 6) & (T.g1 <= 11)),
          ('12-15 games', vet & (T.g1 >= 12) & (T.g1 <= 15)), ('16+ games', vet & (T.g1 >= 16))])
    td = T.td_sh.notna() & (T.g1 >= 8)
    table(T, 'TD reliance (share of PPR points from TDs, 8+ games)', [('low (< 18%)', td & (T.td_sh < .18)), ('middle', td & (T.td_sh >= .18) & (T.td_sh < .28)), ('high (28%+)', td & (T.td_sh >= .28))])
    c = T.cap_pct.notna() & (T.vet_deal == 1)
    table(T, 'contract (veteran deals, size at signing as cap %)', [('under 2% of cap', c & (T.cap_pct < .02)), ('2-6%', c & (T.cap_pct >= .02) & (T.cap_pct < .06)),
          ('6-10%', c & (T.cap_pct >= .06) & (T.cap_pct < .10)), ('10%+', c & (T.cap_pct >= .10)),
          ('last year of deal', c & (T.c_left == 0)), ('2+ years left', c & (T.c_left >= 2))])
    rb, wr, qb = pos['RB'], pos['WR'], pos['QB']
    table(T, 'size', [('RB under 205 lb', rb & (T.wt < 205)), ('RB 205-219', rb & (T.wt >= 205) & (T.wt < 220)), ('RB 220+', rb & (T.wt >= 220)),
          ('WR under 6-0', wr & (T.ht < 72)), ('WR 6-0 to 6-2', wr & (T.ht >= 72) & (T.ht < 75)), ('WR 6-3+', wr & (T.ht >= 75))])
    q = qb & T.rush_sh.notna() & (T.g1 >= 8)
    table(T, 'QB rushing share of points (8+ games)', [('under 12%', q & (T.rush_sh < .12)), ('12-25%', q & (T.rush_sh >= .12) & (T.rush_sh < .25)), ('25%+', q & (T.rush_sh >= .25))])
    r8 = rb & T.tgt_sh.notna() & (T.g1 >= 8)
    table(T, 'RB receiving role (target share, 8+ games)', [('under 7%', r8 & (T.tgt_sh < .07)), ('7-12%', r8 & (T.tgt_sh >= .07) & (T.tgt_sh < .12)), ('12%+', r8 & (T.tgt_sh >= .12))])
    k = T.keep_sh.notna()
    qs = T.keep_sh.quantile([.33, .67]).tolist()
    table(T, 'KTC crowd "keep" share', [('low third', k & (T.keep_sh < qs[0])), ('middle third', k & (T.keep_sh >= qs[0]) & (T.keep_sh < qs[1])), ('high third', k & (T.keep_sh >= qs[1]))])


def gbm():
    return HistGradientBoostingRegressor(max_depth=3, learning_rate=0.04, max_iter=350, min_samples_leaf=40,
                                         l2_regularization=1.0, random_state=0)


def fit_predict(tr, te, h, feats):
    iso = par_fit(tr.price, tr['f%d' % h])
    rt = tr['f%d' % h] - iso.predict(tr.price)
    m = gbm().fit(tr[feats], rt)
    par = iso.predict(te.price)
    return par, m.predict(te[feats]), m, iso


def score(te, par, res, h, tag):
    y = te['f%d' % h].to_numpy()
    act = y - par
    per = []
    for d, idx in te.groupby('date').indices.items():
        if len(idx) < 40:
            continue
        per.append((spearmanr(par[idx], y[idx])[0], spearmanr(par[idx] + res[idx], y[idx])[0], spearmanr(res[idx], act[idx])[0]))
    per = np.array(per)
    q = np.quantile(res / te.price.to_numpy(), [1 / 3, 2 / 3])
    rr = res / te.price.to_numpy()
    ae = act / te.price.to_numpy()
    lo, mid, hi = ae[rr <= q[0]].mean(), ae[(rr > q[0]) & (rr < q[1])].mean(), ae[rr >= q[1]].mean()
    mae0, mae1 = np.abs(act).mean(), np.abs(act - res).mean()
    out('  %-26s dates %2d | rank corr with future value: price %.3f -> price+traits %.3f | beyond-price corr %+.3f | '
        'model AVOID third %+4.0f%%, middle %+4.0f%%, BUY third %+4.0f%% of price | MAE %.0f -> %.0f'
        % (tag, len(per), per[:, 0].mean(), per[:, 1].mean(), per[:, 2].mean(), 100 * lo, 100 * mid, 100 * hi, mae0, mae1))
    return per[:, 2].mean()


def section_c(P, feats=FEATS):
    out('\n=== C. CAN TRAITS BEAT THE PRICE? (held-out tests) ===')
    out('    par = average future value at that price; model adds traits to predict the gap. "beyond-price corr" > 0 = real edge.')
    imp_models = {}
    for h in (1, 2, 3):
        D = P[P['f%d' % h].notna()].reset_index(drop=True)
        out('\n horizon +%d year%s  (%d rows, %d players, %d anchor dates)' % (h, 's' if h > 1 else '', len(D), D.kid.nunique(), D.date.nunique()))
        # (1) held out by player
        par = np.zeros(len(D)); res = np.zeros(len(D)); res_age = np.zeros(len(D))
        for tr, te in GroupKFold(5).split(D, groups=D.kid):
            p_, r_, _, _ = fit_predict(D.iloc[tr], D.iloc[te], h, feats)
            par[te], res[te] = p_, r_
            _, ra, _, _ = fit_predict(D.iloc[tr], D.iloc[te], h, ['price', 'is_qb', 'is_rb', 'is_wr', 'is_te', 'age'])
            res_age[te] = ra
        score(D, par, res_age, h, 'new players: pos+age only')
        score(D, par, res, h, 'new players: all traits')
        # (2) forward in time: train only on outcomes already known at the test date
        yrs = sorted(D.yr.unique())
        parf, resf, keep = [], [], []
        for Y in yrs[1:]:
            te = D[D.yr == Y]
            cut = pd.Timestamp(Y, 1, 1)
            tr = D[D.date + pd.Timedelta(days=365 * h) < cut]
            if len(tr) < 400 or len(te) < 100:
                continue
            p_, r_, _, _ = fit_predict(tr, te, h, feats)
            parf.append(p_); resf.append(r_); keep.append(te)
        if keep:
            T = pd.concat(keep).reset_index(drop=True)
            score(T, np.concatenate(parf), np.concatenate(resf), h, 'forward in time (%s)' % '/'.join(str(y) for y in sorted(T.yr.unique())))
            for p in ('QB', 'RB', 'WR', 'TE'):
                m = (T.pos == p).to_numpy()
                if m.sum() > 150:
                    a = (T['f%d' % h].to_numpy() - np.concatenate(parf))[m]
                    out('      forward, %s only: beyond-price corr %+.3f (n %d)' % (p, spearmanr(np.concatenate(resf)[m], a)[0], m.sum()))
        else:
            out('  forward in time: not enough history yet for this horizon')
        _, _, m, iso = fit_predict(D, D, h, feats)
        imp_models[h] = (m, iso, D)
    return imp_models


def section_d(P, feats=FEATS):
    out('\n=== D. WHAT CARRIES THE MODEL (held-out-by-player permutation importance, +2 years) ===')
    h = 2
    D = P[P['f%d' % h].notna()].reset_index(drop=True)
    base, drops = [], {f: [] for f in feats}
    for tr, te in GroupKFold(5).split(D, groups=D.kid):
        A, B = D.iloc[tr], D.iloc[te].copy()
        iso = par_fit(A.price, A['f%d' % h])
        m = gbm().fit(A[feats], A['f%d' % h] - iso.predict(A.price))
        act = B['f%d' % h] - iso.predict(B.price)
        b0 = spearmanr(m.predict(B[feats]), act)[0]
        base.append(b0)
        for f in feats:
            C = B.copy()
            C[f] = RNG.permutation(C[f].to_numpy())
            drops[f].append(b0 - spearmanr(m.predict(C[feats]), act)[0])
    out('  beyond-price corr with everything: %.3f' % np.mean(base))
    for f, d in sorted(drops.items(), key=lambda kv: -np.mean(kv[1]))[:16]:
        out('    %-34s loses %.3f when scrambled' % (LABEL.get(f, f), np.mean(d)))


AGE_BANDS = {'QB': [(0, 24), (24, 27), (27, 30), (30, 33), (33, 50)], 'RB': [(0, 22.5), (22.5, 24), (24, 25.5), (25.5, 27), (27, 50)],
             'WR': [(0, 22.5), (22.5, 24.5), (24.5, 26.5), (26.5, 28.5), (28.5, 50)], 'TE': [(0, 23.5), (23.5, 25.5), (25.5, 27.5), (27.5, 30), (30, 50)]}


def age_groups(T):
    g = []
    for p, bands in AGE_BANDS.items():
        for a, b in bands:
            g.append(('%s age %s-%s' % (p, a if a else '<', b if b < 50 else '+'), (T.pos == p) & (T.age >= a) & (T.age < b)))
    return g


def section_b2(P):
    """Same tables, but against players at the same price AND position AND age (cross-fitted)."""
    out('\n=== B2. TRAITS WITH AGE HELD EQUAL: excess vs same price + same position + same age ===')
    base = ['price', 'is_qb', 'is_rb', 'is_wr', 'is_te', 'age']
    for h in (1, 2, 3):
        m = P['f%d' % h].notna() & P.age.notna()
        D = P[m]
        pred = np.zeros(len(D))
        for tr, te in GroupKFold(5).split(D, groups=D.kid):
            pred[te] = gbm().fit(D.iloc[tr][base], D.iloc[tr]['f%d' % h]).predict(D.iloc[te][base])
        P.loc[m, 'ex%d' % h] = (D['f%d' % h].to_numpy() - pred) / D.price.to_numpy()
        P.loc[~m, 'ex%d' % h] = np.nan
    T = thin(P, 60).copy()
    pos = {p: T.pos == p for p in ('QB', 'RB', 'WR', 'TE')}
    vet = T.exp >= 2
    rd = [('round 1 pick 1-16', T.opick <= 16), ('round 1 pick 17-32', (T.opick > 16) & (T.opick <= 32)), ('round 2', (T.opick > 32) & (T.opick <= 64)),
          ('round 3', (T.opick > 64) & (T.opick <= 105)), ('day 3 / undrafted', T.opick > 105)]
    table(T, 'draft capital, young (exp <= 2)', [(l, m & (T.exp <= 2)) for l, m in rd])
    table(T, 'draft capital, veteran (exp >= 3)', [(l, m & (T.exp >= 3)) for l, m in rd])
    table(T, 'track record (veterans)', [('0 top-24 seasons', vet & (T.top24 == 0)), ('1 top-24 season', vet & (T.top24 == 1)),
          ('2 top-24 seasons', vet & (T.top24 == 2)), ('3+ top-24 seasons', vet & (T.top24 >= 3)), ('2+ top-12 seasons', vet & (T.top12 >= 2))])
    T['prank'] = T.groupby('date').vor1.rank(ascending=False, method='first', na_option='bottom')
    gap = np.log(T.prank.clip(1, 250) / T.krank.clip(1, 250))
    v1 = (T.exp >= 1) & (T.g1 >= 6)
    table(T, 'price vs production (6+ games last 12 mo)', [
        ('production WAY above price', v1 & (gap < -0.7)), ('production above price', v1 & (gap >= -0.7) & (gap < -0.25)),
        ('in line', v1 & (gap >= -0.25) & (gap <= 0.25)), ('price above production', v1 & (gap > 0.25) & (gap <= 0.7)),
        ('price WAY above production (hype)', v1 & (gap > 0.7))])
    table(T, 'price vs production by position', [('%s production above price' % p, v1 & pos[p] & (gap < -0.25)) for p in pos]
          + [('%s price above production' % p, v1 & pos[p] & (gap > 0.25)) for p in pos])
    hm = T.m12.notna()
    table(T, 'KTC move over the last 12 months', [('fell 40%+', hm & (T.m12 < -0.5)), ('fell 15-40%', hm & (T.m12 >= -0.5) & (T.m12 < -0.16)),
          ('flat', hm & (T.m12 >= -0.16) & (T.m12 <= 0.16)), ('rose 15-50%', hm & (T.m12 > 0.16) & (T.m12 <= 0.4)), ('rose 50%+', hm & (T.m12 > 0.4))])
    h6 = T.m6.notna()
    table(T, 'KTC move over the last 6 months', [('fell 25%+', h6 & (T.m6 < -0.29)), ('fell 10-25%', h6 & (T.m6 >= -0.29) & (T.m6 < -0.1)),
          ('flat', h6 & (T.m6 >= -0.1) & (T.m6 <= 0.1)), ('rose 10-35%', h6 & (T.m6 > 0.1) & (T.m6 <= 0.3)), ('rose 35%+', h6 & (T.m6 > 0.3))])
    table(T, 'distance from his KTC peak', [('at peak (>= 95%)', T.dd >= .95), ('80-95% of peak', (T.dd >= .8) & (T.dd < .95)),
          ('60-80% of peak', (T.dd >= .6) & (T.dd < .8)), ('under 60% of peak', T.dd < .6)])
    table(T, 'availability last 12 months (veterans)', [('0-5 games', vet & (T.g1 <= 5)), ('6-11 games', vet & (T.g1 >= 6) & (T.g1 <= 11)),
          ('12-15 games', vet & (T.g1 >= 12) & (T.g1 <= 15)), ('16+ games', vet & (T.g1 >= 16))])
    c = T.cap_pct.notna() & (T.vet_deal == 1)
    table(T, 'contract (veteran deals)', [('under 2% of cap', c & (T.cap_pct < .02)), ('2-6%', c & (T.cap_pct >= .02) & (T.cap_pct < .06)),
          ('6-10%', c & (T.cap_pct >= .06) & (T.cap_pct < .10)), ('10%+', c & (T.cap_pct >= .10)),
          ('last year of deal', c & (T.c_left == 0)), ('2+ years left', c & (T.c_left >= 2))])
    rb, wr, qb, te = pos['RB'], pos['WR'], pos['QB'], pos['TE']
    table(T, 'size', [('RB under 205 lb', rb & (T.wt < 205)), ('RB 205-219', rb & (T.wt >= 205) & (T.wt < 220)), ('RB 220+', rb & (T.wt >= 220)),
          ('WR under 6-0', wr & (T.ht < 72)), ('WR 6-0 to 6-2', wr & (T.ht >= 72) & (T.ht < 75)), ('WR 6-3+', wr & (T.ht >= 75)),
          ('WR under 190 lb', wr & (T.wt < 190)), ('WR 210+ lb', wr & (T.wt >= 210))])
    q = qb & T.rush_sh.notna() & (T.g1 >= 8)
    table(T, 'QB rushing share of points', [('under 12%', q & (T.rush_sh < .12)), ('12-25%', q & (T.rush_sh >= .12) & (T.rush_sh < .25)), ('25%+', q & (T.rush_sh >= .25))], minp=10)
    r8 = rb & (T.g1 >= 8)
    table(T, 'RB role (8+ games)', [('target share under 7%', r8 & (T.tgt_sh < .07)), ('target share 7-12%', r8 & (T.tgt_sh >= .07) & (T.tgt_sh < .12)), ('target share 12%+', r8 & (T.tgt_sh >= .12)),
          ('carry share under 35%', r8 & (T.car_sh < .35)), ('carry share 35-55%', r8 & (T.car_sh >= .35) & (T.car_sh < .55)), ('carry share 55%+', r8 & (T.car_sh >= .55))])
    w8 = wr & (T.g1 >= 8)
    table(T, 'WR / TE target share (8+ games)', [('WR under 15%', w8 & (T.tgt_sh < .15)), ('WR 15-22%', w8 & (T.tgt_sh >= .15) & (T.tgt_sh < .22)), ('WR 22%+', w8 & (T.tgt_sh >= .22)),
          ('TE under 12%', te & (T.g1 >= 8) & (T.tgt_sh < .12)), ('TE 12-18%', te & (T.g1 >= 8) & (T.tgt_sh >= .12) & (T.tgt_sh < .18)), ('TE 18%+', te & (T.g1 >= 8) & (T.tgt_sh >= .18))])
    td = T.td_sh.notna() & (T.g1 >= 8)
    table(T, 'TD reliance', [('low (< 18%)', td & (T.td_sh < .18)), ('middle', td & (T.td_sh >= .18) & (T.td_sh < .28)), ('high (28%+)', td & (T.td_sh >= .28))])
    k = T.keep_sh.notna()
    qs = T.keep_sh.quantile([.33, .67]).tolist()
    table(T, 'KTC crowd "keep" share', [('low third', k & (T.keep_sh < qs[0])), ('middle third', k & (T.keep_sh >= qs[0]) & (T.keep_sh < qs[1])), ('high third', k & (T.keep_sh >= qs[1]))])
    table(T, 'experience (age already held equal)', [('rookie season', T.exp == 0), ('year 2', T.exp == 1), ('year 3', T.exp == 2), ('years 4-6', (T.exp >= 3) & (T.exp <= 5)), ('year 7+', T.exp >= 6)])


def section_e(P):
    """Total return: the points he scores while you hold him + what he is still worth."""
    out('\n=== E. TOTAL RETURN: points scored while held + resale value ===')
    out('    Older producers lose price but pay you in points. Exchange rate (KTC value per point over the starter line)')
    out('    is read from the market itself: cell means (position x age band x price tier), price = a x points + b x resale.')
    T0 = thin(P, 60).copy()
    T0['tier'] = np.where(T0.krank <= 36, 0, np.where(T0.krank <= 100, 1, 2))
    T0['band'] = -1
    for p, bands in AGE_BANDS.items():
        for i, (a, b) in enumerate(bands):
            T0.loc[(T0.pos == p) & (T0.age >= a) & (T0.age < b), 'band'] = i
    rates = {}
    for h in (1, 2, 3):
        cols = ['vf%d' % i for i in range(1, h + 1)]
        D = T0[T0['f%d' % h].notna() & T0[cols].notna().all(axis=1) & (T0.band >= 0)].copy()
        D['pts'] = D[cols].sum(axis=1)
        C = D.groupby(['pos', 'band', 'tier']).agg(n=('price', 'size'), price=('price', 'mean'), pts=('pts', 'mean'), res=('f%d' % h, 'mean')).reset_index()
        C = C[C.n >= 15]
        w = np.sqrt(C.n.to_numpy())
        X = np.c_[C.pts, C.res] * w[:, None]
        coef, *_ = np.linalg.lstsq(X, C.price.to_numpy() * w, rcond=None)
        fit = np.c_[C.pts, C.res] @ coef
        r2 = 1 - ((C.price - fit) ** 2 * C.n).sum() / (((C.price - np.average(C.price, weights=C.n)) ** 2) * C.n).sum()
        rates[h] = coef
        out('  +%dy: 1 point over the starter line = %.1f KTC value, resale counts %.2f  (cells %d, fit R2 %.2f)' % (h, coef[0], coef[1], len(C), r2))
    for h in (2, 3):
        a_, b_ = rates[h]
        cols = ['vf%d' % i for i in range(1, h + 1)]
        D = T0[T0['f%d' % h].notna() & T0[cols].notna().all(axis=1)].copy()
        D['pts'] = D[cols].sum(axis=1)
        out('\n  hold %d years - per position x age: resale kept | points/yr over starter line | TOTAL RETURN vs price paid' % h)
        out('    %-18s %8s %12s %12s %24s %6s' % ('', 'resale', 'points/yr', 'total', 'if points worth 30%% less / more', 'n'))
        for lab, mask in age_groups(D):
            x = D[mask]
            if x.kid.nunique() < 12:
                continue
            res = (x['f%d' % h] / x.price).mean()
            tr = {}
            for k, mult in (('mid', 1.0), ('lo', 0.7), ('hi', 1.3)):
                x = x.assign(tr=(mult * a_ * x.pts + b_ * x['f%d' % h]) / x.price - 1)
                tr[k] = boot(x, 'tr')
            m, lo, hi, n = tr['mid']
            star = '*' if (lo > 0 or hi < 0) else ' '
            out('    %-18s %7.0f%% %12.0f %+10.0f%%%s %+11.0f%% / %+.0f%% %10d' % (lab, 100 * res, x.pts.mean() / h, 100 * m, star, 100 * tr['lo'][0], 100 * tr['hi'][0], n))
        D['tr'] = (a_ * D.pts + b_ * D['f%d' % h]) / D.price - 1
        out('    by price tier (total return):  ' + '  '.join('%s %+.0f%%' % (l, 100 * D[(D.krank >= a) & (D.krank <= b)].tr.mean())
                                                               for l, a, b in (('1-24', 1, 24), ('25-50', 25, 50), ('51-100', 51, 100), ('101-175', 101, 175), ('176-250', 176, 250))))
        out('    by position (total return):    ' + '  '.join('%s %+.0f%%' % (p, 100 * D[D.pos == p].tr.mean()) for p in ('QB', 'RB', 'WR', 'TE')))
    return rates


def main():
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument('--fmt', default='1qb')
    ap.add_argument('--top', type=int, default=250)
    ap.add_argument('--skip-b', action='store_true', help='only base rates, total return and the age-equal tables')
    a = ap.parse_args()
    LOG = open(os.path.join(WB, 'lasting_%s_top%d%s.log' % (a.fmt, a.top, '_e' if a.skip_b else '')), 'w', encoding='utf-8')
    P = load(a.fmt, a.top)
    out('KTC lasting-value study | format %s | pool top %d | rows %d | players %d | dates %s..%s'
        % (a.fmt, a.top, len(P), P.kid.nunique(), P.date.min().date(), P.date.max().date()))
    section_a(P)
    P = add_excess(P)
    if not a.skip_b:
        section_b(P)
    section_e(P)
    section_b2(P)
    if not a.skip_b:
        section_c(P)
        section_d(P)
    LOG.close()


if __name__ == '__main__':
    sys.exit(main())
