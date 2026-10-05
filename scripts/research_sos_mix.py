"""How should the schedule rank (SOS) weigh the opponent grade against the Vegas side?

app.js blends three things into a team's schedule rank for a position:
  def  the opponent grade of the defenses in the window (_mtMatchupZ)
  tot  the team's implied total in the window RELATIVE to its own season norm
  spr  the team's average spread in the window
with fixed weights: def : tot = 3 : 1 for QB / RB / WR / TE, 1 : 3 for K, 1 : 2 for
D/ST, plus a spread weight per position (POSITION_SPREAD_WEIGHT). None of that
was ever backtested. This does it.

For every season, checkpoint week N and window (weeks 15-17, the next 4 weeks,
the rest of the season) each team gets the three signals built ONLY from what
was known after week N, and a target: the fantasy points its position group
scored in the window MINUS that group's own season average - i.e. how much the
schedule helped or hurt.

  def   the shipped grade: touchdown-neutral, schedule-adjusted points allowed,
        this season x last season at games / (games + k)
  tot / spr   future lines do not exist historically, so they are rebuilt the
        way the site builds its own totals: team offense + defense ratings fit
        on the closing lines of weeks <= N. ("oracle" rows use the real closing
        lines of the window games - an upper bound, not available in advance.)

Mix settings are picked on the other seasons and scored on the held-out one.

Usage:  python scripts/research_sos_mix.py [--seasons 2014-2025]
Prints only.
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from research_dst_opponent_vs_quality import GAMES  # noqa: E402
from research_opp_grade_schemes import all_games, build_rows  # noqa: E402
from research_preseason_fade import player_games as kicker_games  # noqa: E402

K_PRIOR = {'QB': 3, 'RB': 4, 'WR': 6, 'TE': 2, 'DST': 2}
SKILL = ['QB', 'RB', 'WR', 'TE']
POSITIONS = SKILL + ['K', 'DST']
SITE_MIX = {'QB': (3, 1), 'RB': (3, 1), 'WR': (3, 1), 'TE': (3, 1), 'K': (1, 3), 'DST': (1, 2)}
SITE_SPR = {'QB': -0.10, 'RB': 0.25, 'WR': 0.08, 'TE': 0.08, 'K': 0.05, 'DST': 0.15}
TGRID = [round(x, 1) for x in np.arange(0, 1.01, 0.1)]
SGRID = [round(x, 2) for x in np.arange(-0.3, 0.51, 0.1)]


def z(s):
    sd = s.std(ddof=0)
    return (s - s.mean()) / (sd if sd and not np.isnan(sd) else 1.0)


def fit_ratings(rows, K=1.0):
    """rows: (team, opp, implied). implied ~ mu + off[team] + dfn[opp], ridge like _wkSchedAdjust."""
    mu = sum(r[2] for r in rows) / len(rows)
    off, dfn, nO, nD = {}, {}, {}, {}
    for t, o, _ in rows:
        off[t] = 0.0
        dfn[o] = 0.0
        nO[t] = nO.get(t, 0) + 1
        nD[o] = nD.get(o, 0) + 1
    for _ in range(40):
        s = {}
        for t, o, v in rows:
            s[t] = s.get(t, 0.0) + (v - mu - dfn[o])
        for t in off:
            off[t] = s[t] / (nO[t] + K)
        s = {}
        for t, o, v in rows:
            s[o] = s.get(o, 0.0) + (v - mu - off[t])
        for o in dfn:
            dfn[o] = s[o] / (nD[o] + K)
    return mu, off, dfn


def load_lines(seasons):
    g = pd.read_csv(GAMES)
    g = g[(g['game_type'] == 'REG') & g['season'].isin(seasons)].dropna(subset=['spread_line', 'total_line'])
    h = pd.DataFrame({'season': g['season'], 'week': g['week'], 'team': g['home_team'], 'opp': g['away_team'], 'home': 1,
                      'imp': (g['total_line'] + g['spread_line']) / 2.0, 'spr': -g['spread_line']})
    a = pd.DataFrame({'season': g['season'], 'week': g['week'], 'team': g['away_team'], 'opp': g['home_team'], 'home': 0,
                      'imp': (g['total_line'] - g['spread_line']) / 2.0, 'spr': g['spread_line']})
    L = pd.concat([h, a], ignore_index=True)
    L['final'] = L.groupby('season')['week'].transform('max')
    return L[L['week'] < L['final']].drop(columns='final')


def build(seasons):
    G = all_games(seasons)
    R = build_rows(G, seasons)
    R['grade'] = np.nan
    for pos, k in K_PRIOR.items():
        m = R['pos'] == pos
        w = R.loc[m, 'g'] / (R.loc[m, 'g'] + k)
        R.loc[m, 'grade'] = w * R.loc[m, 'in_tdn'] + (1 - w) * R.loc[m, 'p1_tdn']   # higher = allows more = softer
    grade = {key: f.set_index('d')['grade'] for key, f in R.groupby(['season', 'pos', 'N'])}
    scored = G[['season', 'week', 'o', 'pos', 'pts']].rename(columns={'o': 'team'})
    kk = pd.concat([kicker_games(y) for y in seasons], ignore_index=True)
    kk = kk[kk['pos'] == 'K'].rename(columns={'o': 'team', 'v': 'pts'})[['season', 'week', 'team', 'pos', 'pts']]
    kk['final'] = kk.groupby('season')['week'].transform('max')
    scored = pd.concat([scored, kk[kk['week'] < kk['final']].drop(columns='final')], ignore_index=True)
    L = load_lines(seasons)
    out = []
    for y in sorted(R['season'].unique()):
        Ly = L[L['season'] == y]
        Sy = scored[scored['season'] == y]
        norm = Sy.groupby(['pos', 'team'])['pts'].mean()
        last = int(Ly['week'].max())
        for N in range(3, 13):
            early = Ly[Ly['week'] <= N]
            if early.empty:
                continue
            mu, off, dfn = fit_ratings(list(zip(early['team'], early['opp'], early['imp'])))
            hfa = (early[early['home'] == 1]['imp'].mean() - early[early['home'] == 0]['imp'].mean()) / 2.0
            P = Ly.copy()
            pi = mu + P['team'].map(off).fillna(0) + P['opp'].map(dfn).fillna(0) + np.where(P['home'] == 1, hfa, -hfa)
            po = mu + P['opp'].map(off).fillna(0) + P['team'].map(dfn).fillna(0) - np.where(P['home'] == 1, hfa, -hfa)
            fut = P['week'] > N
            P['imp_p'] = np.where(fut, pi, P['imp'])
            P['oimp_p'] = np.where(fut, po, P['imp'] + P['spr'])          # opponent implied = own implied + own spread
            P['spr_p'] = np.where(fut, -(pi - po), P['spr'])
            P['oimp'] = P['imp'] + P['spr']
            base = P.groupby('team')[['imp_p', 'oimp_p', 'spr_p']].median()
            base_or = P.groupby('team')[['imp', 'oimp']].median()
            windows = {'next4': (N + 1, N + 4)}
            if N in (4, 6, 8, 10, 12):
                windows['w15-17'] = (15, 17)
            if N in (4, 6, 8, 10):
                windows['rest'] = (N + 1, last)
            for wname, (a, b) in windows.items():
                W = P[(P['week'] >= max(a, N + 1)) & (P['week'] <= b)]
                if W.empty:
                    continue
                cnt = W.groupby('team').size()
                agg = W.groupby('team')[['imp_p', 'oimp_p', 'spr_p', 'imp', 'oimp', 'spr']].mean()
                for pos in POSITIONS:
                    if pos == 'K':
                        gs = [grade.get((y, p, N)) for p in SKILL]
                        if any(x is None for x in gs):
                            continue
                        gr = pd.concat(gs, axis=1).mean(axis=1)
                    else:
                        gr = grade.get((y, pos, N))
                        if gr is None:
                            continue
                    hdef = (-W['opp'].map(gr)).groupby(W['team']).mean()              # hardness: lower = easier
                    tg = Sy[(Sy['pos'] == pos) & (Sy['week'] >= max(a, N + 1)) & (Sy['week'] <= b)].groupby('team')['pts'].mean()
                    df = pd.DataFrame({'hdef': hdef, 'n': cnt, 'tgt': tg - norm.get(pos, pd.Series(dtype=float))})
                    if pos == 'DST':
                        df['rel'] = agg['oimp_p'] - base['oimp_p']
                        df['rel_or'] = agg['oimp'] - base_or['oimp']
                    else:
                        df['rel'] = agg['imp_p'] - base['imp_p']
                        df['rel_or'] = agg['imp'] - base_or['imp']
                    df['spr'], df['spr_or'] = agg['spr_p'], agg['spr']
                    df['sprr'] = agg['spr_p'] - base['spr_p']      # spread vs the team's own season norm
                    df = df[df['n'] >= min(2, b - max(a, N + 1) + 1)].dropna()
                    if len(df) < 20:
                        continue
                    sign = 1.0 if pos == 'DST' else -1.0                               # more own points = easier; more opp points = harder for a D/ST
                    df['zT'], df['zT_or'] = sign * z(df['rel']), sign * z(df['rel_or'])
                    df['zS'], df['zS_or'] = z(df['spr']), z(df['spr_or'])
                    df['zSr'] = z(df['sprr'])
                    df['hdef_std'] = z(df['hdef'])
                    df['tgt'] = z(df['tgt'])
                    df['season'], df['pos'], df['N'], df['win'] = y, pos, N, wname
                    out.append(df.reset_index().rename(columns={'index': 'team'}))
    return pd.concat(out, ignore_index=True)


def hard(df, t, sw, dcol='hdef', suf='', scol=None):
    return (1 - t) * df[dcol] + t * df['zT' + suf] + sw * df[scol or ('zS' + suf)]


def score(df, h):
    """Mean per-season correlation of EASE (-hardness) with how much the schedule helped."""
    return df.assign(e=-h).groupby('season').apply(lambda f: np.corrcoef(f['e'], f['tgt'])[0, 1]).mean()


def pooled(df, h):
    return np.corrcoef(-h, df['tgt'])[0, 1]


def loso(df, dcol='hdef'):
    s = pd.Series(np.nan, index=df.index)
    picks = []
    for y in sorted(df['season'].unique()):
        tr, te = df[df['season'] != y], df[df['season'] == y]
        best = max(((pooled(tr, hard(tr, t, sw, dcol)), t, sw) for t in TGRID for sw in SGRID), key=lambda x: x[0])
        picks.append((best[1], best[2]))
        s.loc[te.index] = hard(te, best[1], best[2], dcol)
    return s, picks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', default='2014-2025')
    args = ap.parse_args()
    lo, hi = (int(x) for x in args.seasons.split('-'))
    seasons = list(range(lo, hi + 1))
    D = build(seasons)
    print('seasons scored: %d-%d   rows %d' % (D['season'].min(), D['season'].max(), len(D)))
    print('score = mean per-season correlation between the schedule rank (as ease) and points scored in the window vs the team\'s own norm')
    for pos in POSITIONS:
        dp = D[D['pos'] == pos].reset_index(drop=True)
        a, b = SITE_MIX[pos]
        t0, s0 = b / (a + b), SITE_SPR[pos]
        fit, picks = loso(dp)
        fit_std, picks_std = loso(dp, 'hdef_std')
        med = lambda xs: sorted(xs)[len(xs) // 2]  # noqa: E731
        print('\n=== %s ===   site mix: tot share %.2f, spread %+.2f' % (pos, t0, s0))
        print('%-34s   all    w15-17   next4    rest' % 'version')
        rows = [
            ('site mix now', hard(dp, t0, s0)),
            ('opponent grade only', hard(dp, 0, 0)),
            ('implied total only', hard(dp, 1, 0)),
            ('spread only (favored = easier)', dp['zS']),
            ('grade + total, no spread (site mix)', hard(dp, t0, 0)),
            ('fitted mix', fit),
            ('fitted mix, grade re-standardized', fit_std),
            ('site mix with ORACLE closing lines', hard(dp, t0, s0, suf='_or')),
        ]
        for name, h in rows:
            line = '%-34s  %6.3f' % (name, score(dp, h))
            for w in ('w15-17', 'next4', 'rest'):
                m = dp['win'] == w
                line += '  %6.3f' % score(dp[m], h[m])
            print(line)
        print('  fitted picks (tot share, spread):  median %.1f / %+.1f   range tot %.1f-%.1f, spread %+.1f to %+.1f'
              % (med([p[0] for p in picks]), med([p[1] for p in picks]), min(p[0] for p in picks), max(p[0] for p in picks),
                 min(p[1] for p in picks), max(p[1] for p in picks)))
        print('  re-standardized picks:             median %.1f / %+.1f' % (med([p[0] for p in picks_std]), med([p[1] for p in picks_std])))
        base = dp.assign(e=-hard(dp, t0, s0)).groupby('season').apply(lambda f: np.corrcoef(f['e'], f['tgt'])[0, 1])
        new = dp.assign(e=-fit).groupby('season').apply(lambda f: np.corrcoef(f['e'], f['tgt'])[0, 1])
        print('  fitted beats site mix in %d of %d seasons' % (int((new > base).sum()), len(base)))
        # fixed-setting table: how flat is the surface
        print('  fixed settings (all windows):  ' + '  '.join('tot %.1f: %.3f' % (t, score(dp, hard(dp, t, s0))) for t in (0, 0.25, 0.5, 0.75, 1.0)))
        print('  spread weight at site tot share: ' + '  '.join('%+.2f: %.3f' % (sw, score(dp, hard(dp, t0, sw))) for sw in (-0.2, -0.1, 0, 0.1, 0.25, 0.4)))
        print('  SPREAD VS OWN NORM, same weights: ' + '  '.join('%+.2f: %.3f' % (sw, score(dp, hard(dp, t0, sw, scol='zSr'))) for sw in (-0.2, -0.1, 0, 0.1, 0.25, 0.4)))
        per = lambda h: dp.assign(e=-h).groupby('season').apply(lambda f: np.corrcoef(f['e'], f['tgt'])[0, 1])  # noqa: E731
        for label, h in (('no spread term', hard(dp, t0, 0)), ('spread vs own norm at the site weight', hard(dp, t0, s0, scol='zSr')),
                         ('spread vs own norm +0.10', hard(dp, t0, 0.10, scol='zSr')), ('spread vs own norm +0.25', hard(dp, t0, 0.25, scol='zSr')),
                         ('tot share 0.5, no spread', hard(dp, 0.5, 0))):
            v = per(h)
            print('    %-38s %.3f   beats site mix in %d of %d seasons' % (label, v.mean(), int((v > base).sum()), len(base)))


if __name__ == '__main__':
    main()
