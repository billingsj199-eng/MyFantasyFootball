"""Which signal actually predicts D/ST scoring: season-long opponent quality
or the game's Vegas line?

This is the direct calibration test for POSITION_SIGNAL_MIX.DST in app.js.
For a D/ST both SOS axes point at the opponent, so the real question is not
"defense or opponent" (answered by research_dst_opponent_vs_quality.py --
opponent wins 73/27) but "reputation or market":

  QUALITY signal = the opponent offense's season-long scoring, leave-one-out.
                   Stands in for a preseason unit grade like Mike Clay's.
  MARKET signal  = the opponent's Vegas implied total for THAT game
                   (total_line / 2 - spread/2), the live estimate.

Both are then measured baseline-relative (minus the defense's own season norm)
because that is what the site's SOS actually blends -- a raw opponent implied
total is contaminated by the defense's own quality (a good defense drags every
opponent's line down), which is the bug this analysis exists to keep fixed.

Usage:  python scripts/research_dst_signal_weights.py [--seasons 2019-2025]
Prints the analysis; writes nothing.
"""
import argparse
import sys

import numpy as np
import pandas as pd

TEAM_WEEK = ('https://github.com/nflverse/nflverse-data/releases/download/'
             'stats_team/stats_team_week_{year}.csv')
GAMES = ('https://github.com/nflverse/nflverse-data/releases/download/'
         'schedules/games.csv')


def pa_bonus(pa):
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


def r2(y, yhat):
    ss_res = float(((y - yhat) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return 1.0 - ss_res / ss_tot


def ols(X, y):
    A = np.column_stack([np.ones(len(X))] + [X[:, i] for i in range(X.shape[1])])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    return beta[1:], beta[0], r2(pd.Series(y), pd.Series(A @ beta))


def loo(df, key, value):
    g = df.groupby(['season', key])[value]
    return (g.transform('sum') - df[value]) / (g.transform('count') - 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', default='2019-2025')
    args = ap.parse_args()
    lo, hi = (int(x) for x in args.seasons.split('-'))
    seasons = list(range(lo, hi + 1))

    frames = []
    for y in seasons:
        df = pd.read_csv(TEAM_WEEK.format(year=y))
        df = df[df['season_type'] == 'REG'].copy()
        df['season'] = y
        frames.append(df)
        print(f'  {y}: {len(df)} team-weeks', file=sys.stderr)
    stats = pd.concat(frames, ignore_index=True)

    g = pd.read_csv(GAMES)
    g = g[(g['game_type'] == 'REG') & g['season'].isin(seasons)]

    # Per-team-week: points scored, and this team's Vegas implied total.
    # spread_line is quoted from the HOME team's perspective, positive = home
    # favored, so home implied = total/2 + spread/2.
    home = g[['season', 'week', 'home_team', 'home_score', 'total_line', 'spread_line']].copy()
    home.columns = ['season', 'week', 'team', 'pts', 'total_line', 'spread']
    home['implied'] = home['total_line'] / 2.0 + home['spread'] / 2.0
    away = g[['season', 'week', 'away_team', 'away_score', 'total_line', 'spread_line']].copy()
    away.columns = ['season', 'week', 'team', 'pts', 'total_line', 'spread']
    away['implied'] = away['total_line'] / 2.0 - away['spread'] / 2.0
    teamweek = pd.concat([home, away], ignore_index=True).dropna(subset=['pts'])

    cols = ['season', 'week', 'team', 'opponent_team', 'def_sacks',
            'def_interceptions', 'def_tds', 'def_safeties',
            'fumble_recovery_opp', 'special_teams_tds']
    d = stats[[c for c in cols if c in stats.columns]].copy()
    for c in cols[4:]:
        d[c] = pd.to_numeric(d.get(c, 0.0), errors='coerce').fillna(0.0)

    # Attach the OPPONENT's points scored (= points allowed) and implied total.
    opp = teamweek.rename(columns={
        'team': 'opponent_team', 'pts': 'points_allowed',
        'implied': 'opp_implied'})[
        ['season', 'week', 'opponent_team', 'points_allowed', 'opp_implied']]
    d = d.merge(opp, on=['season', 'week', 'opponent_team'], how='inner')

    d['dst_fpts'] = (d['def_sacks'] + 2 * d['def_interceptions']
                     + 2 * d['fumble_recovery_opp'] + 6 * d['def_tds']
                     + 6 * d['special_teams_tds'] + 2 * d['def_safeties']
                     + d['points_allowed'].apply(pa_bonus))

    # QUALITY: opponent's season-long scoring (leave-one-out), a stand-in for a
    # preseason offensive unit grade.
    opp_pts = teamweek.rename(columns={'team': 'opponent_team', 'pts': 'opp_pts'})[
        ['season', 'week', 'opponent_team', 'opp_pts']]
    d = d.merge(opp_pts, on=['season', 'week', 'opponent_team'], how='left')
    d['quality'] = loo(d, 'opponent_team', 'opp_pts')

    d = d.dropna(subset=['dst_fpts', 'quality', 'opp_implied'])

    # Baseline-relative versions: subtract the DEFENSE's own season norm, which
    # is what the site's SOS blend uses.
    for src, out in (('opp_implied', 'market_rel'), ('quality', 'quality_rel')):
        base = d.groupby(['season', 'team'])[src].transform('median')
        d[out] = d[src] - base

    y = d['dst_fpts'].values
    print()
    print('=' * 74)
    print(f'  D/ST SIGNALS: SEASON-LONG QUALITY vs VEGAS MARKET  ({lo}-{hi})')
    print('=' * 74)
    print(f'  {len(d):,} team-games')
    print()

    tests = [
        ('opponent quality (season-long, LOO)', ['quality']),
        ('opponent implied total (Vegas, raw)', ['opp_implied']),
        ('opponent implied, baseline-relative', ['market_rel']),
        ('quality + Vegas implied', ['quality', 'opp_implied']),
    ]
    print(f'  {"signal":<40} {"R^2":>8}')
    for label, cs in tests:
        _, _, rr = ols(d[cs].values.reshape(len(d), len(cs)), y)
        print(f'  {label:<40} {rr:8.4f}')
    print()

    # Head-to-head: both in one model, whose slope survives?
    coefs, _, both = ols(d[['quality', 'opp_implied']].values, y)
    print(f'  Together: quality slope {coefs[0]:+.3f}, Vegas slope {coefs[1]:+.3f}')
    print('  (the larger surviving slope is the signal carrying real information)')
    print()

    # The contamination check that motivated the baseline fix.
    print('-' * 74)
    print('  Contamination: is a RAW opponent implied total a proxy for the')
    print("  defense's own quality rather than its schedule?")
    print('-' * 74)
    season = d.groupby(['season', 'team']).agg(
        med_opp_implied=('opp_implied', 'median'),
        own_dst=('dst_fpts', 'mean')).reset_index()
    r = np.corrcoef(season['med_opp_implied'], season['own_dst'])[0, 1]
    print(f'  corr(season median opponent implied, own D/ST ppg) = {r:+.2f}')
    print(f'  over {len(season)} team-seasons. Strongly negative means the market')
    print('  prices offenses DOWN against good defenses, so the raw number encodes')
    print('  defense quality -- subtract the baseline before ranking schedules.')
    print()


if __name__ == '__main__':
    main()
