#!/usr/bin/env python3
"""
research_market_truth.py — MARKET vs TRUTH decomposition (Jack 2026-10-09: "once
we figure out all the factors on how people value players we come up with true
value for the production and future production to find over and under valued
players").

Pool: FFC dynasty ADP pool 2016-23 (1QB PPR), the factors each player carried
INTO that season (no hindsight):
  age by position (age - 25 x QB/RB/WR/TE), position, rookie, draft capital
  (log pick, rookies and vets separately), production level (log production
  vs replacement, 3-season base — the sim's input), last-season games share,
  breakout (last season's PPG jump over the two before, per replacement PPG),
  injury-shortened last season, changed teams, big new contract, walk year,
  JM prospect score (drafted 2017+), market momentum (log of last year's market
  rank / this year's: + = rising).
1  MARKET MODEL   log market rank ~ factors           -> what the price is made of
2  TRUTH MODEL    log realized rank (3yr, 5yr+youth) ~ factors
3  BEYOND PRICE   log realized rank ~ log market rank + factors: a factor that still
   predicts the outcome once the price is known is MISPRICED (coef < 0 = players
   high on it beat their price = market UNDERpays; > 0 = OVERpays). Bootstrap by
   player (400 reps) for the interval; also leave-one-year-out: does price +
   factors rank outcomes better than the price alone, and than FAIR?
Standardized factors (z) so the coefficients compare; log-rank units.
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, FORMATS, load_jm  # noqa: E402
from backtest_value_score import build, YEARS, LAST  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

FACT = ['age_QB', 'age_RB', 'age_WR', 'age_TE', 'pos_RB', 'pos_WR', 'pos_TE', 'rookie', 'pick_rookie', 'pick_vet',
        'prod', 'games', 'breakout', 'injured', 'moved', 'deal_big', 'walk', 'jm', 'momentum']
LABEL = {'age_QB': 'age (QB)', 'age_RB': 'age (RB)', 'age_WR': 'age (WR)', 'age_TE': 'age (TE)', 'pos_RB': 'is RB', 'pos_WR': 'is WR',
         'pos_TE': 'is TE', 'rookie': 'rookie', 'pick_rookie': 'draft capital (rookies, -log pick)', 'pick_vet': 'draft capital (vets, -log pick)',
         'prod': 'production level (3-yr base)', 'games': 'games played last season', 'breakout': 'breakout last season',
         'injured': 'injury-shortened last season', 'moved': 'changed teams', 'deal_big': 'big new contract', 'walk': 'walk year',
         'jm': 'JM prospect score', 'momentum': 'market momentum (rising)'}


def features():
    recs = build(True)
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    m3_ship(recs, c)
    w = World(LAST)
    rows = w.rows(FORMATS['1qb'], YEARS[-1])
    idx = {(r['key'], r['Y']): r for r in rows}
    jm = load_jm()
    jvals = [v for v in jm.values()]
    jmu, jsd = float(np.mean(jvals)), float(np.std(jvals))
    for x in recs:
        r = idx.get((x['key'], x['Y']), {})
        P, a = x['pos'], x['age'] - 25.0
        dr = w.players[x['key']]['draft']
        f = {('age_' + p): (a if P == p else 0.0) for p in ('QB', 'RB', 'WR', 'TE')}
        f.update({'pos_RB': float(P == 'RB'), 'pos_WR': float(P == 'WR'), 'pos_TE': float(P == 'TE'), 'rookie': float(x['rookie'])})
        lp = -math.log(dr[1]) if dr and dr[1] else -math.log(262)
        f['pick_rookie'] = lp if x['rookie'] else 0.0
        f['pick_vet'] = lp if not x['rookie'] else 0.0
        f['prod'] = math.log(max(r.get('rel', 1.0), 0.05)) if not x['rookie'] else 0.0
        f['games'] = (r.get('gp1') or 0) / 17.0 if not x['rookie'] else 0.0
        f['breakout'] = x['breakout']; f['injured'] = x['injured']; f['moved'] = x['moved']
        f['deal_big'] = x['deal_big']; f['walk'] = x['walk']
        f['jm'] = (jm[x['key']] - jmu) / jsd if x['key'] in jm else 0.0
        f['momentum'] = math.log(x['mp'] / x['m0']) if x.get('mp') else 0.0
        x['f'] = f
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
    return recs


def ols(X, y):
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    res = y - X @ b
    return b, 1 - res.var() / y.var()


def main():
    recs = features()
    R3 = [x for x in recs if x.get('r_t3')]
    X0 = np.array([[x['f'][k] for k in FACT] for x in R3], float)
    mu, sd = X0.mean(0), X0.std(0); sd[sd == 0] = 1
    Z = (X0 - mu) / sd
    one = np.ones((len(R3), 1))
    lm = np.array([math.log(x['m0']) for x in R3]); t3 = np.array([math.log(x['r_t3']) for x in R3])
    keys = np.array([hash(x['key']) for x in R3])
    LT = [i for i, x in enumerate(R3) if x.get('r_lt')]
    lt = np.array([math.log(R3[i]['r_lt']) for i in LT])

    bm, r2m = ols(np.hstack([one, Z]), lm)
    bt, r2t = ols(np.hstack([one, Z]), t3)
    bl, _ = ols(np.hstack([one[LT], Z[LT]]), lt)
    bp, _ = ols(np.hstack([one, lm[:, None], Z]), t3)          # beyond price, 3yr
    bpl, _ = ols(np.hstack([one[LT], lm[LT][:, None], Z[LT]]), lt)  # beyond price, 5yr+youth
    # bootstrap by player for the beyond-price coefficients
    rng = np.random.default_rng(7)
    uk = np.unique(keys); byk = {k: np.where(keys == k)[0] for k in uk}
    boots, bootsl = [], []
    ltset = set(LT)
    for _ in range(400):
        pick = rng.choice(uk, len(uk))
        ii = np.concatenate([byk[k] for k in pick])
        boots.append(ols(np.hstack([one[ii], lm[ii][:, None], Z[ii]]), t3[ii])[0][2:])
        jj = np.array([i for i in ii if i in ltset])
        bootsl.append(ols(np.hstack([one[jj], lm[jj][:, None], Z[jj]]), np.array([math.log(R3[i]['r_lt']) for i in jj]))[0][2:])
    lo, hi = np.percentile(boots, 2.5, 0), np.percentile(boots, 97.5, 0)
    lol, hil = np.percentile(bootsl, 2.5, 0), np.percentile(bootsl, 97.5, 0)

    print(f'pool: {len(R3)} player-seasons 2016-23 ({len(LT)} with 5yr+youth). Market model R2 {r2m:.2f} (factors explain this much of the price);'
          f' truth model R2 {r2t:.2f} (3yr).')
    print('\nCoefficients per 1 SD of the factor, log-rank units (negative = ranked BETTER):')
    print(f'{"factor":<36}{"MARKET":>8}{"TRUTH 3y":>10}{"TRUTH 5y+":>10}{"BEYOND PRICE 3y (95%)":>26}{"5y+ (95%)":>22}  verdict')
    for i, k in enumerate(FACT):
        sig3 = lo[i] > 0 or hi[i] < 0
        sigl = lol[i] > 0 or hil[i] < 0
        v = bp[i + 2]; vl = bpl[i + 2]
        if sig3 or sigl:
            s = vl if sigl else v
            verdict = 'market UNDERPAYS' if s < 0 else 'market OVERPAYS'
        else:
            verdict = 'priced about right'
        print(f'{LABEL[k]:<36}{bm[i + 1]:>+8.2f}{bt[i + 1]:>+10.2f}{bl[i + 1]:>+10.2f}'
              f'{f"{v:+.3f} [{lo[i]:+.2f},{hi[i]:+.2f}]":>26}{f"{vl:+.3f} [{lol[i]:+.2f},{hil[i]:+.2f}]":>22}  {verdict}{" *" if sig3 and sigl else ""}')
    print('   BEYOND PRICE < 0 = players high on the factor finished better than their price said (under-paid); > 0 = over-paid.'
          '\n   verdict from the bootstrap interval excluding 0 (3yr or 5yr; * = both).')

    # LOYO: price + factors vs price alone vs FAIR
    print('\n=== leave-one-year-out: does price + factors rank outcomes better? (per-year Spearman, avg) ===')
    yrs = np.array([x['Y'] for x in R3])
    out = {'price alone': [], 'price + factors': [], 'FAIR (shipped)': [], 'factors alone (truth model)': []}
    out5 = {k: [] for k in out}
    out['FAIR + factors'] = []
    for Y in YEARS:
        tr, te = yrs != Y, yrs == Y
        if te.sum() < 20:
            continue
        b1 = ols(np.hstack([one[tr], lm[tr][:, None], Z[tr]]), t3[tr])[0]
        b2 = ols(np.hstack([one[tr], Z[tr]]), t3[tr])[0]
        p1 = np.hstack([one[te], lm[te][:, None], Z[te]]) @ b1
        p2 = np.hstack([one[te], Z[te]]) @ b2
        xs = [R3[i] for i in np.where(te)[0]]
        out['price alone'].append(spearman(list(-lm[te]), list(-t3[te])))
        out['price + factors'].append(spearman(list(-p1), list(-t3[te])))
        out['factors alone (truth model)'].append(spearman(list(-p2), list(-t3[te])))
        out['FAIR (shipped)'].append(spearman([-x['fz'] for x in xs], list(-t3[te])))
        fzv = np.array([x['fz'] for x in R3])
        b3 = ols(np.hstack([one[tr], fzv[tr][:, None], Z[tr]]), t3[tr])[0]
        out.setdefault('FAIR + factors', []).append(spearman(list(-(np.hstack([one[te], fzv[te][:, None], Z[te]]) @ b3)), list(-t3[te])))
        te5 = [i for i in np.where(te)[0] if R3[i].get('r_lt')]
        if len(te5) >= 20:
            t5 = [-math.log(R3[i]['r_lt']) for i in te5]
            out5['price alone'].append(spearman([-lm[i] for i in te5], t5))
            out5['price + factors'].append(spearman([-float(np.hstack([[1.0], [lm[i]], Z[i]]) @ b1) for i in te5], t5))
            out5['factors alone (truth model)'].append(spearman([-float(np.hstack([[1.0], Z[i]]) @ b2) for i in te5], t5))
            out5['FAIR (shipped)'].append(spearman([-R3[i]['fz'] for i in te5], t5))
    for k in out:
        print(f'   {k:<30} 3yr {np.mean(out[k]):.3f}   5yr+youth {np.mean(out5[k]) if out5.get(k) else float("nan"):.3f}')
    json.dump({'factors': FACT, 'market': list(bm[1:]), 'truth3': list(bt[1:]), 'beyond3': list(bp[2:]), 'beyond5': list(bpl[2:]),
               'ci3': [list(lo), list(hi)], 'ci5': [list(lol), list(hil)], 'mu': list(mu), 'sd': list(sd)},
              open(os.path.join(HERE, '_dyn_cache', 'market_truth.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
