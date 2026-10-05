"""When should the opponent grade stop leaning on past data, by position?

The matchup / SOS grades blend two reads of "how many fantasy points does this
defense allow to a position": what it has allowed THIS season (schedule-adjusted,
same additive fit as app.js _wkSchedAdjust) and a prior from before the season.
This asks, for each position and each week of the season, how much weight the
in-season number deserves.

Method. For every season, position and cutoff week N:
  in-season = schedule-adjusted points allowed per game through week N
  prior     = the same defense's schedule-adjusted number for the whole PRIOR
              season (the stand-in for a preseason grade - "how good they used
              to be"; real preseason grades also know about offseason moves)
  target    = raw points allowed per game in later weeks (next 4 / rest of
              season / weeks 15-17), final regular-season week dropped
All three are z-scored across the league within a season and pooled. The best
weight is the least-squares split between the two predictors; "cost" is the
correlation lost by using the in-season number alone.

K = kicker points allowed by the defense. DST = D/ST points scored against the
OFFENSE (so the "defense" there is really the offense that gives them up).

Usage:  python scripts/research_preseason_fade.py [--seasons 2015-2025]
Writes nothing but a download cache under the system temp dir; prints the tables.
"""
import argparse
import json
import os
import re
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from research_dst_opponent_vs_quality import build as build_dst, fetch as fetch_dst  # noqa: E402

PLAYER_WEEK = ('https://github.com/nflverse/nflverse-data/releases/download/'
               'stats_player/stats_player_week_{year}.csv')
CACHE = os.path.join(tempfile.gettempdir(), 'mff_preseason_fade_cache')
POSITIONS = ['QB', 'RB', 'WR', 'TE', 'K', 'DST']
CUTOFFS = [1, 2, 3, 4, 5, 6, 7, 8, 10]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def player_games(year):
    """One row per (week, defense, offense, position) with half-PPR points."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, 'pos_games_%d.csv' % year)
    if os.path.exists(path):
        return pd.read_csv(path)
    df = pd.read_csv(PLAYER_WEEK.format(year=year), low_memory=False)
    df = df[df['season_type'] == 'REG'].copy()
    df['pos'] = df['position'].replace({'FB': 'RB'})
    num = lambda c: pd.to_numeric(df[c], errors='coerce').fillna(0.0) if c in df.columns else 0.0  # noqa: E731
    df['v'] = (num('fantasy_points') + num('fantasy_points_ppr')) / 2.0
    kick = (3.0 * (num('fg_made_0_19') + num('fg_made_20_29') + num('fg_made_30_39'))
            + 4.0 * num('fg_made_40_49') + 5.0 * (num('fg_made_50_59') + num('fg_made_60_')) + num('pat_made'))
    df.loc[df['pos'] == 'K', 'v'] = kick[df['pos'] == 'K']
    df = df[df['pos'].isin(['QB', 'RB', 'WR', 'TE', 'K'])]
    g = (df.groupby(['week', 'opponent_team', 'team', 'pos'], as_index=False)['v'].sum()
           .rename(columns={'opponent_team': 'd', 'team': 'o'}))
    g['season'] = year
    g.to_csv(path, index=False)
    return g


def all_games(seasons):
    frames = []
    for y in seasons:
        frames.append(player_games(y))
        print('  %d player-weeks ok' % y, file=sys.stderr)
    stats, scored = fetch_dst(seasons)
    dst = build_dst(stats, scored).dropna(subset=['dst_fpts'])
    # D/ST points are scored AGAINST the offense: the "defense" key is the offense.
    dst = dst.rename(columns={'opponent_team': 'd', 'team': 'o', 'dst_fpts': 'v'})[['season', 'week', 'd', 'o', 'v']]
    dst['pos'] = 'DST'
    frames.append(dst)
    g = pd.concat(frames, ignore_index=True)
    g['final'] = g.groupby('season')['week'].transform('max')
    return g[g['week'] < g['final']]   # Jack 09-17: the final week is not football


def sched_adjust(rows, K=1.0):
    """rows: (defense, offense, v). Returns {defense: league mean + defense effect}."""
    if not rows:
        return {}
    mu = sum(r[2] for r in rows) / len(rows)
    dE = {r[0]: 0.0 for r in rows}
    oE = {r[1]: 0.0 for r in rows}
    dN, oN = {}, {}
    for d, o, _ in rows:
        dN[d] = dN.get(d, 0) + 1
        oN[o] = oN.get(o, 0) + 1
    for _ in range(50):
        s = {}
        for d, o, v in rows:
            s[d] = s.get(d, 0.0) + (v - mu - oE[o])
        for d in dE:
            dE[d] = s[d] / (dN[d] + K)
        s = {}
        for d, o, v in rows:
            s[o] = s.get(o, 0.0) + (v - mu - dE[d])
        for o in oE:
            oE[o] = s[o] / (oN[o] + K)
    return {d: mu + dE[d] for d in dE}


def adj(frame):
    return pd.Series(sched_adjust(list(zip(frame['d'], frame['o'], frame['v']))), dtype=float)


def z(s):
    return (s - s.mean()) / (s.std(ddof=0) or 1.0)


def split(A):
    """Least-squares weight on the in-season number vs the prior (clipped 0-1)."""
    X = np.column_stack([A['ins'].values, A['prior'].values])
    beta, *_ = np.linalg.lstsq(X, A['tgt'].values, rcond=None)
    a, b = max(beta[0], 0.0), max(beta[1], 0.0)
    return a / (a + b) if (a + b) > 0 else 0.5


def corr(x, y):
    return float(np.corrcoef(x, y)[0, 1])


def study(g, seasons):
    targets = {'next4': lambda w, N: (w > N) & (w <= N + 4),
               'rest': lambda w, N: w > N,
               'w15-17': lambda w, N: (w >= 15) & (w <= 17)}
    full = {(y, p): adj(f) for (y, p), f in g.groupby(['season', 'pos'])}
    out = []
    for pos in POSITIONS:
        gp = g[g['pos'] == pos]
        for N in CUTOFFS:
            for tname, tfn in targets.items():
                recs = []
                for y in seasons[1:]:
                    gy = gp[gp['season'] == y]
                    prior = full.get((y - 1, pos))
                    if prior is None or gy.empty:
                        continue
                    ins = adj(gy[gy['week'] <= N])
                    tgt = gy[tfn(gy['week'], N)].groupby('d')['v'].mean()
                    df = pd.DataFrame({'ins': ins, 'prior': prior, 'tgt': tgt}).dropna()
                    if len(df) < 24:
                        continue
                    df = df.apply(z)
                    df['season'] = y
                    recs.append(df)
                if not recs:
                    continue
                A = pd.concat(recs)
                w = split(A)
                loo = [split(A[A['season'] != y]) for y in A['season'].unique()]
                r_in, r_pr = corr(A['ins'], A['tgt']), corr(A['prior'], A['tgt'])
                r_best = corr(w * A['ins'] + (1 - w) * A['prior'], A['tgt'])
                out.append(dict(pos=pos, N=N, target=tname, n=len(A), r_in=r_in, r_prior=r_pr, w=w,
                                w_lo=min(loo), w_hi=max(loo), r_best=r_best, cost=r_best - r_in))
    return pd.DataFrame(out)


def show(res):
    for tname in ('next4', 'rest', 'w15-17'):
        print('\n=== target: %s ===' % {'next4': 'next 4 weeks', 'rest': 'rest of season', 'w15-17': 'weeks 15-17'}[tname])
        print('pos  thru   r(in-season)  r(prior)  best in-season weight (range)   r(best)   cost of in-season only')
        for pos in POSITIONS:
            for _, r in res[(res['pos'] == pos) & (res['target'] == tname)].iterrows():
                print('%-4s %4d      %6.3f      %6.3f        %4.0f%%  (%2.0f-%3.0f%%)          %6.3f       %6.3f'
                      % (pos, r['N'], r['r_in'], r['r_prior'], 100 * r['w'], 100 * r['w_lo'], 100 * r['w_hi'], r['r_best'], r['cost']))
            print()
    print('\n=== best in-season weight by weeks played (average of the next-4 and rest-of-season targets) ===')
    piv = (res[res['target'].isin(['next4', 'rest'])].groupby(['pos', 'N'])['w'].mean().unstack('N').reindex(POSITIONS) * 100).round(0)
    print(piv.to_string())
    print('\n=== correlation lost by dropping the prior entirely (same average) ===')
    piv = res[res['target'].isin(['next4', 'rest'])].groupby(['pos', 'N'])['cost'].mean().unstack('N').reindex(POSITIONS).round(3)
    print(piv.to_string())


def check_2026(g):
    """Is last year's number a fair stand-in for the Clay preseason grade? 2026 only (32 teams, small)."""
    fpa_path = os.path.join(ROOT, 'data', 'fpa_2026.js')
    clay_path = os.path.join(ROOT, 'data', 'clay_team_grades_2026.js')
    if not (os.path.exists(fpa_path) and os.path.exists(clay_path)):
        return
    txt = open(fpa_path, encoding='utf8').read()
    fpa = json.loads(txt[txt.index('{'):txt.rindex('}') + 1])
    clay = {}
    for m in re.finditer(r"'([A-Z]{2,3})':\s*\{([^}]*)\}", open(clay_path, encoding='utf8').read()):
        clay[m.group(1)] = {k.strip(): float(v) for k, v in (kv.split(':') for kv in m.group(2).split(',') if ':' in kv)}
    W = {'QB': {'ed': .35, 'cb': .30, 's': .20, 'lb': .10, 'di': .05}, 'RB': {'di': .35, 'lb': .35, 'ed': .25, 's': .05},
         'WR': {'cb': .50, 's': .35, 'lb': .15}, 'TE': {'lb': .40, 's': .35, 'cb': .20, 'di': .05}}
    fix = {'LA': 'LAR', 'WSH': 'WAS', 'JAC': 'JAX'}
    print('\n=== 2026 check: Clay preseason grade vs last season\'s number, against 2026 points allowed so far ===')
    print('pos   r(Clay grade)  r(2025 number)   weeks')
    for pos in ['QB', 'RB', 'WR', 'TE', 'DST']:
        rows = []
        for wk, teams in fpa.get('weeks', {}).items():
            for t, rec in teams.items():
                if isinstance(rec.get(pos), (int, float)) and rec.get('opp'):
                    rows.append((fix.get(t, t), fix.get(str(rec['opp']).upper(), str(rec['opp']).upper()), float(rec[pos])))
        now = pd.Series(sched_adjust(rows), dtype=float)
        last = adj(g[(g['season'] == 2025) & (g['pos'] == pos)])
        last.index = [fix.get(t, t) for t in last.index]
        if pos == 'DST':   # softer offense = more D/ST points: flip the offense grade
            cg = pd.Series({t: -c['offGr'] for t, c in clay.items() if 'offGr' in c})
        else:              # better unit = fewer points allowed: flip the grade
            cg = pd.Series({t: -sum(c.get(u, 0) * w for u, w in W[pos].items()) for t, c in clay.items()})
        df = pd.DataFrame({'now': now, 'clay': cg, 'last': last}).dropna()
        print('%-4s    %6.3f         %6.3f        %s  (n=%d)' % (pos, corr(df['clay'], df['now']), corr(df['last'], df['now']),
                                                                '1-%d' % max(int(k) for k in fpa['weeks']), len(df)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', default='2015-2025')
    args = ap.parse_args()
    lo, hi = (int(x) for x in args.seasons.split('-'))
    seasons = list(range(lo, hi + 1))
    g = all_games(seasons)
    res = study(g, seasons)
    print('seasons scored: %d-%d (prior season = the one before each)' % (seasons[1], seasons[-1]))
    show(res)
    if 2025 in seasons:
        check_2026(g)


if __name__ == '__main__':
    main()
