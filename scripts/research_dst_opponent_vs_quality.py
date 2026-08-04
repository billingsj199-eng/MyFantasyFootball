"""How much of D/ST fantasy scoring is the opponent, and how much is the defense?

Answers the question directly: when you start a D/ST, are you buying a good
defense or a good matchup? The answer sets how much weight the matchup axis
deserves in the D/ST SOS blend (POSITION_SIGNAL_MIX.DST in app.js).

Method. Build a per-game D/ST fantasy line for every team-week from nflverse
team stats (sacks / turnovers / def+ST TDs / safeties) plus the game score
(points allowed). Then predict each game's score two ways:

  DEFENSE signal  = that defense's mean D/ST points in its OTHER games
  OPPONENT signal = the mean D/ST points that opponent ALLOWED in its other games

Both are leave-one-out, so neither predictor contains the game it's scoring —
without that, each side trivially "explains" itself and the comparison is
meaningless. Compare R^2, then fit both together to get the honest split.

Usage:  python scripts/research_dst_opponent_vs_quality.py [--seasons 2019-2025]
Writes nothing; prints the analysis. Pure research, no site data touched.
"""
import argparse
import io
import sys

import numpy as np
import pandas as pd
import requests

TEAM_WEEK = ('https://github.com/nflverse/nflverse-data/releases/download/'
             'stats_team/stats_team_week_{year}.csv')
GAMES = ('https://github.com/nflverse/nflverse-data/releases/download/'
         'schedules/games.csv')


def points_allowed_bonus(pa):
    """Standard ESPN/Yahoo D/ST points-allowed tiers."""
    if pa == 0:
        return 10.0
    if pa <= 6:
        return 7.0
    if pa <= 13:
        return 4.0
    if pa <= 20:
        return 1.0
    if pa <= 27:
        return 0.0
    if pa <= 34:
        return -1.0
    return -4.0


def fetch(seasons):
    frames = []
    for y in seasons:
        df = pd.read_csv(TEAM_WEEK.format(year=y))
        df = df[df['season_type'] == 'REG'].copy()
        df['season'] = y
        frames.append(df)
        print(f'  {y}: {len(df)} team-weeks', file=sys.stderr)
    stats = pd.concat(frames, ignore_index=True)

    games = pd.read_csv(GAMES)
    games = games[games['game_type'] == 'REG']
    # One row per team-week with that team's points scored.
    home = games[['season', 'week', 'home_team', 'home_score']].rename(
        columns={'home_team': 'team', 'home_score': 'pts'})
    away = games[['season', 'week', 'away_team', 'away_score']].rename(
        columns={'away_team': 'team', 'away_score': 'pts'})
    scored = pd.concat([home, away], ignore_index=True).dropna(subset=['pts'])
    return stats, scored


def build(stats, scored):
    cols = ['season', 'week', 'team', 'opponent_team', 'def_sacks',
            'def_interceptions', 'def_tds', 'def_safeties',
            'fumble_recovery_opp', 'special_teams_tds']
    d = stats[[c for c in cols if c in stats.columns]].copy()
    for c in cols[4:]:
        if c not in d.columns:
            d[c] = 0.0
        d[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0)

    # Points the DEFENSE allowed = points its OPPONENT scored that week.
    pa = scored.rename(columns={'team': 'opponent_team', 'pts': 'points_allowed'})
    d = d.merge(pa, on=['season', 'week', 'opponent_team'], how='inner')

    d['dst_fpts'] = (
        d['def_sacks'] * 1.0
        + d['def_interceptions'] * 2.0
        + d['fumble_recovery_opp'] * 2.0
        + d['def_tds'] * 6.0
        + d['special_teams_tds'] * 6.0
        + d['def_safeties'] * 2.0
        + d['points_allowed'].apply(points_allowed_bonus)
    )
    return d


def loo_mean(df, key, value):
    """Leave-one-out mean of `value` within each `key` group, per season."""
    g = df.groupby(['season', key])[value]
    total = g.transform('sum')
    count = g.transform('count')
    return (total - df[value]) / (count - 1)


def r2(y, yhat):
    ss_res = float(((y - yhat) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return 1.0 - ss_res / ss_tot


def ols(X, y):
    """Least squares with intercept. Returns (coefs, intercept, r2)."""
    A = np.column_stack([np.ones(len(X))] + [X[:, i] for i in range(X.shape[1])])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    pred = A @ beta
    return beta[1:], beta[0], r2(pd.Series(y), pd.Series(pred))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', default='2019-2025')
    args = ap.parse_args()
    lo, hi = (int(x) for x in args.seasons.split('-'))
    seasons = list(range(lo, hi + 1))

    print('Fetching nflverse team-week stats...', file=sys.stderr)
    stats, scored = fetch(seasons)
    d = build(stats, scored)
    d = d.dropna(subset=['dst_fpts'])

    # Leave-one-out signals.
    d['def_signal'] = loo_mean(d, 'team', 'dst_fpts')          # this defense's quality
    d['opp_signal'] = loo_mean(d, 'opponent_team', 'dst_fpts')  # this opponent's generosity
    d = d.dropna(subset=['def_signal', 'opp_signal'])

    y = d['dst_fpts'].values
    xd = d['def_signal'].values
    xo = d['opp_signal'].values

    print()
    print('=' * 74)
    print(f'  D/ST SCORING: DEFENSE QUALITY vs OPPONENT  ({lo}-{hi})')
    print('=' * 74)
    print(f'  {len(d):,} team-games   mean {y.mean():.2f} pts   sd {y.std():.2f}')
    print()

    _, _, r2_def = ols(xd.reshape(-1, 1), y)
    _, _, r2_opp = ols(xo.reshape(-1, 1), y)
    coefs, _, r2_both = ols(np.column_stack([xd, xo]), y)

    print('  Variance in a single game explained (leave-one-out):')
    print(f'    defense quality alone   R^2 = {r2_def:6.3f}')
    print(f'    opponent alone          R^2 = {r2_opp:6.3f}')
    print(f'    both together           R^2 = {r2_both:6.3f}')
    print(f'    unexplained (variance)      = {1 - r2_both:6.3f}')
    print()
    share = r2_def / (r2_def + r2_opp) if (r2_def + r2_opp) > 0 else float('nan')
    print(f'  Split of the explained signal: '
          f'{share*100:.0f}% defense / {(1-share)*100:.0f}% opponent')
    print(f'  Slopes: defense {coefs[0]:.2f}, opponent {coefs[1]:.2f} '
          '(1.0 = fully predictive)')
    print()

    # Same question at season level: does defense quality persist year to year?
    print('-' * 74)
    print('  Component detail — which parts are defense, which are opponent?')
    print('-' * 74)
    comps = {
        'sacks': 'def_sacks',
        'interceptions': 'def_interceptions',
        'fumble recoveries': 'fumble_recovery_opp',
        'def/ST TDs': 'def_tds',
        'points allowed': 'points_allowed',
        'TOTAL D/ST pts': 'dst_fpts',
    }
    print(f'  {"component":<20} {"defR2":>7} {"oppR2":>7}  {"defense share":>14}')
    for label, col in comps.items():
        if col not in d.columns:
            continue
        sub = d.dropna(subset=[col]).copy()
        sub['ds'] = loo_mean(sub, 'team', col)
        sub['os'] = loo_mean(sub, 'opponent_team', col)
        sub = sub.dropna(subset=['ds', 'os'])
        yy = sub[col].values
        _, _, rd = ols(sub['ds'].values.reshape(-1, 1), yy)
        _, _, ro = ols(sub['os'].values.reshape(-1, 1), yy)
        sh = rd / (rd + ro) if (rd + ro) > 0 else float('nan')
        print(f'  {label:<20} {rd:7.3f} {ro:7.3f}  {sh*100:13.0f}%')
    print()

    # Year-over-year persistence of defense quality (is "good defense" real?).
    print('-' * 74)
    print('  Year-over-year persistence of team D/ST points per game')
    print('-' * 74)
    season_avg = d.groupby(['season', 'team'])['dst_fpts'].mean().reset_index()
    nxt = season_avg.copy()
    nxt['season'] = nxt['season'] - 1
    pair = season_avg.merge(nxt, on=['season', 'team'], suffixes=('_y1', '_y2'))
    if len(pair) > 10:
        r = np.corrcoef(pair['dst_fpts_y1'], pair['dst_fpts_y2'])[0, 1]
        print(f'  r = {r:.2f} over {len(pair)} team-season pairs '
              f'(R^2 = {r**2:.3f})')
    print()


if __name__ == '__main__':
    main()
