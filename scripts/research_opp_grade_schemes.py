"""Which way of building the opponent grade predicts later points allowed best?

Follow-up to research_preseason_fade.py. Every scheme produces one number per
defense per position at each checkpoint (weeks 2-13 played) and is scored on
how well it lines up with what that defense allowed afterwards (next game,
next 4 weeks, rest of season; final week dropped). Schemes:

  now       in-season points allowed, 100% from week 4 (branch state 2026-10-05)
  old       in-season share (weeks - 1) / 4
  in only   in-season only, every week
  last only last season only, every week
  fit pts   weight = games / (games + k), k per position, points allowed
  fit tdn   same, TOUCHDOWN-NEUTRAL points (actual TDs swapped for the league
            TD rate on the yards allowed) on both sides
  fit vol   same, VOLUME: attempts / carries / targets allowed at league value
  +2yr      prior = 2 parts last season, 1 part the season before
  +pool     WR / TE: the defense's QB number mixed into the in-season side

Every fitted setting (k, pool share) is picked on the OTHER seasons and scored
on the held-out one. All inputs are schedule-adjusted (app.js _wkSchedAdjust
port) and z-scored across the league at each checkpoint, like the site.

Usage:  python scripts/research_opp_grade_schemes.py [--seasons 2014-2025]
Prints only (download cache under the system temp dir).
"""
import argparse
import os
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from research_dst_opponent_vs_quality import build as build_dst, fetch as fetch_dst  # noqa: E402
from research_preseason_fade import PLAYER_WEEK, sched_adjust  # noqa: E402

CACHE = os.path.join(tempfile.gettempdir(), 'mff_preseason_fade_cache')
POSITIONS = ['QB', 'RB', 'WR', 'TE', 'DST']
VARS = ['pts', 'tdn', 'vol']
CHECKPOINTS = list(range(2, 14))
KGRID = [0.0, 0.5, 1, 2, 3, 4, 6, 8, 12, 16, 24, 40]
POOLGRID = [0.0, 0.5, 1.0]
SUMCOLS = ['v', 'pyd', 'ptd', 'pint', 'att', 'car', 'ryd', 'rtd', 'tgt', 'rec', 'recyd', 'rectd']


def player_games(year):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, 'pos_games_wide_%d.csv' % year)
    if os.path.exists(path):
        return pd.read_csv(path)
    df = pd.read_csv(PLAYER_WEEK.format(year=year), low_memory=False)
    df = df[df['season_type'] == 'REG'].copy()
    df['pos'] = df['position'].replace({'FB': 'RB'})
    df = df[df['pos'].isin(['QB', 'RB', 'WR', 'TE'])]
    num = lambda c: pd.to_numeric(df[c], errors='coerce').fillna(0.0) if c in df.columns else 0.0  # noqa: E731
    out = pd.DataFrame({
        'week': df['week'], 'd': df['opponent_team'], 'o': df['team'], 'pos': df['pos'],
        'v': (num('fantasy_points') + num('fantasy_points_ppr')) / 2.0,
        'pyd': num('passing_yards'), 'ptd': num('passing_tds'), 'pint': num('passing_interceptions'), 'att': num('attempts'),
        'car': num('carries'), 'ryd': num('rushing_yards'), 'rtd': num('rushing_tds'),
        'tgt': num('targets'), 'rec': num('receptions'), 'recyd': num('receiving_yards'), 'rectd': num('receiving_tds')})
    g = out.groupby(['week', 'd', 'o', 'pos'], as_index=False)[SUMCOLS].sum()
    g['season'] = year
    g.to_csv(path, index=False)
    return g


def all_games(seasons):
    frames = []
    for y in seasons:
        frames.append(player_games(y))
        print('  %d ok' % y, file=sys.stderr)
    g = pd.concat(frames, ignore_index=True)
    T = g[SUMCOLS].sum()
    r_pass, r_rush, r_rec = T['ptd'] / T['pyd'], T['rtd'] / T['ryd'], T['rectd'] / T['recyd']
    g['pts'] = g['v']
    # touchdown-neutral: actual TDs out, league TD rate on the yards in
    g['tdn'] = (g['v'] - 4 * g['ptd'] - 6 * (g['rtd'] + g['rectd'])
                + 4 * r_pass * g['pyd'] + 6 * (r_rush * g['ryd'] + r_rec * g['recyd']))
    # volume: every attempt / carry / target at its league-average value
    per_att = (0.04 * T['pyd'] + 4 * T['ptd'] - 2 * T['pint']) / T['att']
    per_car = (0.1 * T['ryd'] + 6 * T['rtd']) / T['car']
    per_tgt = (0.1 * T['recyd'] + 6 * T['rectd'] + 0.5 * T['rec']) / T['tgt']
    g['vol'] = per_att * g['att'] + per_car * g['car'] + per_tgt * g['tgt']
    g = g[['season', 'week', 'd', 'o', 'pos', 'pts', 'tdn', 'vol']]

    stats, scored = fetch_dst(seasons)
    dst = build_dst(stats, scored).dropna(subset=['dst_fpts'])
    dst['pts'] = dst['dst_fpts']
    dst['tdn'] = dst['dst_fpts'] - 6.0 * (dst['def_tds'] + dst['special_teams_tds'])   # research: D/ST TDs are noise
    dst['vol'] = dst['tdn']
    dst = dst.rename(columns={'opponent_team': 'd', 'team': 'o'})[['season', 'week', 'd', 'o', 'pts', 'tdn', 'vol']]
    dst['pos'] = 'DST'
    g = pd.concat([g, dst], ignore_index=True)
    g['final'] = g.groupby('season')['week'].transform('max')
    return g[g['week'] < g['final']].drop(columns='final')


def adj(frame, col):
    return pd.Series(sched_adjust(list(zip(frame['d'], frame['o'], frame[col]))), dtype=float)


def z(s):
    sd = s.std(ddof=0)
    return (s - s.mean()) / (sd if sd and not np.isnan(sd) else 1.0)


def build_rows(g, seasons):
    full = {}
    for (y, p), f in g.groupby(['season', 'pos']):
        for c in VARS:
            full[(y, p, c)] = adj(f, c)
    rows = []
    for y in seasons[2:]:
        for pos in POSITIONS:
            gy = g[(g['season'] == y) & (g['pos'] == pos)]
            if gy.empty:
                continue
            for N in CHECKPOINTS:
                early, late = gy[gy['week'] <= N], gy[gy['week'] > N]
                if late.empty:
                    continue
                df = pd.DataFrame({'g': early.groupby('d').size()})
                for c in VARS:
                    df['in_' + c] = adj(early, c)
                    df['p1_' + c] = full.get((y - 1, pos, c))
                    df['p2_' + c] = full.get((y - 2, pos, c))
                df['t_next1'] = late[late['week'] == N + 1].groupby('d')['pts'].mean()
                df['t_next4'] = late[late['week'] <= N + 4].groupby('d')['pts'].mean()
                df['t_rest'] = late.groupby('d')['pts'].mean()
                df = df.dropna(subset=['in_pts', 'p1_pts', 'p2_pts', 't_rest'])
                for c in [k for k in df.columns if k != 'g']:
                    df[c] = z(df[c])
                df['season'], df['pos'], df['N'] = y, pos, N
                rows.append(df.reset_index().rename(columns={'index': 'd'}))
    R = pd.concat(rows, ignore_index=True)
    for c in VARS:   # two-season prior, 2 : 1
        R['pp_' + c] = (2 * R['p1_' + c] + R['p2_' + c]) / 3.0
    qb = R[R['pos'] == 'QB'][['season', 'N', 'd', 'in_tdn', 'in_pts']].rename(columns={'in_tdn': 'qb_tdn', 'in_pts': 'qb_pts'})
    return R.merge(qb, on=['season', 'N', 'd'], how='left')


TARGETS = ['t_next1', 't_next4', 't_rest']


def score(df, s):
    """Per-season correlation of the scheme's number with each target."""
    out = {}
    for t in TARGETS:
        ok = df[t].notna() & s.notna()
        out[t] = df[ok].assign(s=s[ok]).groupby('season').apply(lambda f: np.corrcoef(f['s'], f[t])[0, 1])
    return out


def blend(df, var, prior, k=None, w=None, pool=0.0):
    ins = df['in_' + var]
    if pool:
        ins = (ins + pool * df['qb_' + ('tdn' if var != 'pts' else 'pts')]) / (1 + pool)
    if w is None:
        w = df['g'] / (df['g'] + k) if k > 0 else pd.Series(1.0, index=df.index)
    return w * ins + (1 - w) * df[prior + '_' + var]


def obj(df, s):
    r = [np.corrcoef(s[df[t].notna()], df.loc[df[t].notna(), t])[0, 1] for t in ('t_next4', 't_rest')]
    return sum(r) / 2.0


def loso(df, var, prior, pools=(0.0,)):
    """k (and pool share) picked on the other seasons, applied to the held-out one."""
    s = pd.Series(np.nan, index=df.index)
    picks = []
    for y in sorted(df['season'].unique()):
        tr, te = df[df['season'] != y], df[df['season'] == y]
        best = max(((obj(tr, blend(tr, var, prior, k=k, pool=p)), k, p) for k in KGRID for p in pools), key=lambda x: x[0])
        picks.append((best[1], best[2]))
        s.loc[te.index] = blend(te, var, prior, k=best[1], pool=best[2])
    return s, picks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', default='2014-2025')
    args = ap.parse_args()
    lo, hi = (int(x) for x in args.seasons.split('-'))
    seasons = list(range(lo, hi + 1))
    R = build_rows(all_games(seasons), seasons)
    print('seasons scored: %d-%d, checkpoints weeks %d-%d played' % (seasons[2], seasons[-1], CHECKPOINTS[0], CHECKPOINTS[-1]))
    summary = {}
    for pos in POSITIONS:
        df = R[R['pos'] == pos].reset_index(drop=True)
        sch = {}
        sch['now: 100% from week 4'] = (blend(df, 'pts', 'p1', w=np.minimum(1.0, (df['N'] - 1) / 3.0)), None)
        sch['old: (weeks-1)/4'] = (blend(df, 'pts', 'p1', w=np.minimum(1.0, (df['N'] - 1) / 4.0)), None)
        sch['in-season only'] = (df['in_pts'], None)
        sch['last season only'] = (df['p1_pts'], None)
        sch['fit pts'] = loso(df, 'pts', 'p1')
        sch['fit pts +2yr'] = loso(df, 'pts', 'pp')
        sch['fit tdn'] = loso(df, 'tdn', 'p1')
        sch['fit tdn +2yr'] = loso(df, 'tdn', 'pp')
        if pos != 'DST':
            sch['fit vol +2yr'] = loso(df, 'vol', 'pp')
        if pos in ('WR', 'TE'):
            sch['fit tdn +2yr +pool'] = loso(df, 'tdn', 'pp', pools=POOLGRID)
        base = score(df, sch['now: 100% from week 4'][0])
        base_avg = (base['t_next4'] + base['t_rest']) / 2.0
        print('\n=== %s ===' % pos)
        print('%-24s  next game  next 4   rest   avg(4,rest)  seasons >= now   early(2-4) mid(5-8) late(9-13)   picks' % 'scheme')
        for name, (s, picks) in sch.items():
            sc = score(df, s)
            avg = (sc['t_next4'] + sc['t_rest']) / 2.0
            stage = []
            for a, b in ((2, 4), (5, 8), (9, 13)):
                m = (df['N'] >= a) & (df['N'] <= b)
                ss = score(df[m], s[m])
                stage.append(((ss['t_next4'] + ss['t_rest']) / 2.0).mean())
            pk = ''
            if picks:
                ks = sorted(p[0] for p in picks)
                pk = 'k %s' % ks[len(ks) // 2] + (' (%s-%s)' % (ks[0], ks[-1]) if ks[0] != ks[-1] else '')
                if any(p[1] for p in picks):
                    pk += ', pool %s' % sorted(p[1] for p in picks)[len(picks) // 2]
            print('%-24s   %6.3f    %6.3f  %6.3f    %6.3f        %2d/%d          %6.3f    %6.3f    %6.3f     %s'
                  % (name, sc['t_next1'].mean(), sc['t_next4'].mean(), sc['t_rest'].mean(), avg.mean(),
                     int((avg >= base_avg - 1e-12).sum()), len(avg), stage[0], stage[1], stage[2], pk))
            summary[(pos, name)] = avg.mean()
    print('\n=== avg(next 4, rest) by scheme ===')
    S = pd.Series(summary).unstack(0).reindex(columns=POSITIONS)
    S['mean'] = S.mean(axis=1)
    print(S.round(3).sort_values('mean', ascending=False).to_string())


if __name__ == '__main__':
    main()
