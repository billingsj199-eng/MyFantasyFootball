#!/usr/bin/env python3
"""
Usage score backtest -> weights for the Research page Usage column (USAGE in app.js).

Question: which mix of usage signals best predicts a player's NEXT 3 games of half-PPR
points, and does it beat his own recent fantasy points?
  data   data/adv_stats_<yr>_w<N>.js week tables 2019-2025 (RB / WR / TE)
  X      mean of the player's last 3 games: shares (%) and per-game counts
  y      mean half-PPR points over his next 3 games played (needs >= 2)
  model  non-negative least squares on the raw signals (a score never drops with more usage);
         leave-one-season-out R2 against unconstrained OLS, each signal alone, recent PPG
  scale  score = 100 * (pred - intercept) / (p99 pred - intercept)

2026-09-15: LOSO R2 RB .539 / WR .466 / TE .523 vs recent PPG .489 / .422 / .436, better
than recent points in every season 2019-2025. Snap% (RB), inside-10 carry share (RB),
end-zone targets and air-yard share (WR) add nothing once the other signals are in, so NNLS
gives them 0. Prints the USAGE constant to paste into app.js.

  python scripts/backtest_usage_score.py
"""
import collections, glob, io, json, os, re, sys
import numpy as np
from scipy.optimize import nnls

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEAT = {
    'RB': ['snp', 'car', 'tsh', 'rtp', 'i10s', 'hvtg'],
    'WR': ['snp', 'rtp', 'tsh', 'ays', 'rzg', 'ezg'],
    'TE': ['snp', 'rtp', 'tsh', 'ays', 'rzg', 'ezg'],
}


def load(p):
    s = open(p, encoding='utf-8').read()
    return json.loads(s[s.index(']=') + 2:].rstrip().rstrip(';'))


def player_games():
    out = {pos: collections.defaultdict(list) for pos in FEAT}
    for p in glob.glob(os.path.join(ROOT, 'data', 'adv_stats_20??_w*.js')):
        m = re.search(r'_(\d{4})_w(\d+)\.js$', p)
        yr, wk = int(m.group(1)), int(m.group(2))
        if yr > 2025:
            continue
        d = load(p)
        for pos in FEAT:
            f = d[pos]['f']
            for r in d[pos]['r']:
                o = dict(zip(f, r))
                if not o.get('g'):
                    continue
                o['hvtg'], o['rzg'], o['ezg'] = o.get('hvt') or 0, o.get('rz') or 0, o.get('ez') or 0
                o['yr'], o['wk'] = yr, wk
                out[pos][(yr, o['n'])].append(o)
    return out


def samples(players, pos):
    X, y, base, yrs = [], [], [], []
    for (yr, _), games in players.items():
        games.sort(key=lambda o: o['wk'])
        for i in range(2, len(games) - 2):
            prev, nxt = games[i - 2:i + 1], games[i + 1:i + 4]
            if len(nxt) < 2:
                continue
            X.append([np.mean([(g.get(k) or 0) for g in prev]) for k in FEAT[pos]])
            y.append(np.mean([(g.get('fpt') or 0) for g in nxt]))
            base.append(np.mean([(g.get('fpt') or 0) for g in prev]))
            yrs.append(yr)
    return np.array(X, float), np.array(y), np.array(base), np.array(yrs)


def r2(y, p):
    return 1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum()


def loso(X, y, yrs, fit, predict):
    pred = np.zeros_like(y)
    for yr in sorted(set(yrs)):
        tr, te = yrs != yr, yrs == yr
        pred[te] = predict(fit(X[tr], y[tr]), X[te])
    return pred


def ols_fit(X, y):
    return np.linalg.lstsq(np.c_[np.ones(len(y)), X], y, rcond=None)[0]


def ols_pred(c, X):
    return np.c_[np.ones(len(X)), X] @ c


def nnls_fit(X, y):
    return nnls(np.c_[X, np.ones(len(y))], y)[0]


def nnls_pred(c, X):
    return np.c_[X, np.ones(len(X))] @ c


def main():
    players = player_games()
    consts = {}
    for pos in FEAT:
        X, y, base, yrs = samples(players[pos], pos)
        p_nn = loso(X, y, yrs, nnls_fit, nnls_pred)
        p_ols = loso(X, y, yrs, ols_fit, ols_pred)
        p_ppg = loso(base[:, None], y, yrs, ols_fit, ols_pred)
        print(f'\n=== {pos}: {len(y)} samples, mean next-3 PPG {y.mean():.2f}')
        print(f'  LOSO R2  usage (non-negative) {r2(y, p_nn):.3f} | unconstrained {r2(y, p_ols):.3f} | recent PPG {r2(y, p_ppg):.3f}')
        for j, k in enumerate(FEAT[pos]):
            print(f'    {k} alone {r2(y, loso(X[:, [j]], y, yrs, ols_fit, ols_pred)):.3f}')
        print('  by season (usage / recent PPG):', '  '.join(
            f'{yr} {r2(y[yrs == yr], p_nn[yrs == yr]):.2f}/{r2(y[yrs == yr], p_ppg[yrs == yr]):.2f}' for yr in sorted(set(yrs))))
        c = nnls_fit(X, y)
        pred = nnls_pred(c, X)
        contrib = c[:-1] * X.mean(0)
        print('  share of score:', ', '.join(f'{k} {100 * v / contrib.sum():.0f}%' for k, v in zip(FEAT[pos], contrib)))
        consts[pos] = {'w': {k: round(float(w), 4) for k, w in zip(FEAT[pos], c[:-1]) if w > 0},
                       'b': round(float(c[-1]), 2), 'p99': round(float(np.percentile(pred, 99)), 1)}
    print('\nconst USAGE = ' + json.dumps(consts) + ';')


if __name__ == '__main__':
    main()
