"""Does the schedule adjustment help the opponent grade? (Jack 2026-11-05)

The live grade (app.js _mtObservedFpa) is  w x this season + (1 - w) x last
season, w = games / (games + k), touchdown-neutral, and BOTH sides
schedule-adjusted (_wkSchedAdjust: pts = mu + defense effect + offense effect,
one-game shrink). This scores that grade with the adjustment on and off, on
each side separately, at the live k (QB 3 / RB 4 / WR 6 / TE 2 / DST 2).

Targets (per defense, after checkpoint week N, final week dropped):
  raw   = points allowed per game in the next 4 weeks / rest of season
  fair  = same, minus the full-season effect of each offense faced (so a
          defense is not credited for an easy later schedule)
Score = per-season correlation, averaged over next-4 and rest; seasons where
the variant beats the live grade are counted.

Usage:  python scripts/research_sched_adjust_backtest.py [--seasons 2014-2025]
Prints only. Reuses research_opp_grade_schemes.py's download cache.
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from research_opp_grade_schemes import all_games, z  # noqa: E402

POSITIONS = ['QB', 'RB', 'WR', 'TE', 'DST']
LIVE_K = {'QB': 3, 'RB': 4, 'WR': 6, 'TE': 2, 'DST': 2}
CHECKPOINTS = list(range(2, 14))
STAGES = ((2, 4), (5, 8), (9, 13))


def fit(frame, col, K=1.0):
    """Port of app.js _wkSchedAdjust. Returns (defense value = mu + dE, offense effect oE)."""
    rows = list(zip(frame['d'], frame['o'], frame[col]))
    if not rows:
        return {}, {}
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
    return {d: mu + dE[d] for d in dE}, oE


def raw_mean(frame, col):
    return frame.groupby('d')[col].mean()


def build(g, seasons):
    full_adj, full_raw, off_eff = {}, {}, {}
    for (y, p), f in g.groupby(['season', 'pos']):
        a, _ = fit(f, 'tdn')
        full_adj[(y, p)] = pd.Series(a, dtype=float)
        full_raw[(y, p)] = raw_mean(f, 'tdn')
        _, oE = fit(f, 'pts')
        off_eff[(y, p)] = oE
    rows = []
    for y in seasons[1:]:
        for pos in POSITIONS:
            gy = g[(g['season'] == y) & (g['pos'] == pos)]
            if gy.empty or (y - 1, pos) not in full_adj:
                continue
            oE = off_eff[(y, pos)]
            gy = gy.assign(fair=gy['pts'] - gy['o'].map(oE).fillna(0.0))
            for N in CHECKPOINTS:
                early, late = gy[gy['week'] <= N], gy[gy['week'] > N]
                if late.empty:
                    continue
                a, _ = fit(early, 'tdn')
                df = pd.DataFrame({'g': early.groupby('d').size()})
                df['in_adj'] = pd.Series(a, dtype=float)
                df['in_raw'] = raw_mean(early, 'tdn')
                df['pr_adj'] = full_adj[(y - 1, pos)]
                df['pr_raw'] = full_raw[(y - 1, pos)]
                nxt = late[late['week'] <= N + 4]
                df['raw4'] = nxt.groupby('d')['pts'].mean()
                df['rawR'] = late.groupby('d')['pts'].mean()
                df['fair4'] = nxt.groupby('d')['fair'].mean()
                df['fairR'] = late.groupby('d')['fair'].mean()
                df = df.dropna()
                for c in [k for k in df.columns if k != 'g']:
                    df[c] = z(df[c])
                df['season'], df['pos'], df['N'] = y, pos, N
                rows.append(df.reset_index().rename(columns={'index': 'd'}))
    return pd.concat(rows, ignore_index=True)


def variants(df, k):
    w = df['g'] / (df['g'] + k)
    b = lambda i, p: w * df['in_' + i] + (1 - w) * df['pr_' + p]  # noqa: E731
    return {
        'LIVE: adj + adj prior': b('adj', 'adj'),
        'raw in-season, adj prior': b('raw', 'adj'),
        'adj in-season, raw prior': b('adj', 'raw'),
        'NO ADJUSTMENT (raw + raw)': b('raw', 'raw'),
        'in-season only, adj': df['in_adj'],
        'in-season only, raw': df['in_raw'],
    }


def per_season(df, s, tgt):
    cols = ('raw4', 'rawR') if tgt == 'raw' else ('fair4', 'fairR')
    r = [df.assign(s=s).groupby('season').apply(lambda f, c=c: np.corrcoef(f['s'], f[c])[0, 1]) for c in cols]
    return (r[0] + r[1]) / 2.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', default='2014-2025')
    args = ap.parse_args()
    lo, hi = (int(x) for x in args.seasons.split('-'))
    seasons = list(range(lo, hi + 1))
    R = build(all_games(seasons), seasons)
    print('seasons scored %d-%d, checkpoints weeks %d-%d, live k %s' % (seasons[1], seasons[-1], CHECKPOINTS[0], CHECKPOINTS[-1], LIVE_K))
    summary = {}
    for pos in POSITIONS:
        df = R[R['pos'] == pos].reset_index(drop=True)
        V = variants(df, LIVE_K[pos])
        print('\n=== %s ===' % pos)
        print('%-28s %s' % ('variant', '  RAW target: all  wks2-4 wks5-8 wks9-13 beats-live | FAIR target: all  wks2-4 wks5-8 wks9-13 beats-live'))
        base = {t: per_season(df, V['LIVE: adj + adj prior'], t) for t in ('raw', 'fair')}
        for name, s in V.items():
            line = '%-28s' % name
            for t in ('raw', 'fair'):
                ps = per_season(df, s, t)
                st = []
                for a, bb in STAGES:
                    m = (df['N'] >= a) & (df['N'] <= bb)
                    st.append(per_season(df[m], s[m], t).mean())
                beats = int((ps > base[t] + 1e-12).sum())
                line += '   %6.3f %6.3f %6.3f %6.3f   %2d/%d  ' % (ps.mean(), st[0], st[1], st[2], beats, len(ps))
                summary[(pos, t, name)] = ps.mean()
            print(line)
    print('\n=== mean score (avg of next-4 and rest) ===')
    S = pd.Series(summary).unstack(0).reindex(columns=POSITIONS)
    print(S.round(3).to_string())


if __name__ == '__main__':
    main()
