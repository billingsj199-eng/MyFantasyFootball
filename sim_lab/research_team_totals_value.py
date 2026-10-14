#!/usr/bin/env python3
"""
research_team_totals_value.py — does a player's team projected scoring (Vegas
implied team total entering the season) move dynasty value beyond price / sim /
FAIR? (Jack 2026-10-09: "projected team totals being attached to certain
offensive weapons like brock bowers")

Pool: FFC dynasty ADP pool 2018-23 (1QB PPR), QB / RB / WR / TE, shipped JM sim
+ FAIR (same records as research_qb_effect.py). Team = his club on the week-1
depth chart of season Y (nflverse depth_charts). Team total ENTERING Y = mean
implied points over that team's weeks 1-3 closing lines (pbp spread/total) —
the closest pre-season read we have (early-week lines are mostly the summer view).
  tt      implied points/g, weeks 1-3 of Y
  tt_chg  tt minus the same team's weeks 15-17 implied of Y-1 (situation change)
Tests (z-scored, + = higher-scoring offense):
  1  raw: higher team total -> better realized rank (season Y, 3 years)?
  2  priced: does the market rank them higher?
  3  beyond MKT / SIM / FAIR: coef in log realized rank ~ log rank + tt (< 0 =
     players on high-total teams BEAT that rank); player bootstrap CI.
  4  leave-one-year-out: FAIR / SIM + k x tt, per-year Spearman.
"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, FORMATS, _norm_name  # noqa: E402
from backtest_value_score import build  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402
from backtest_vegas_layer import load_lines, tm  # noqa: E402

PBP = r"E:\MyFantasyFootball\pbp_cache"
YRS = [2018, 2019, 2020, 2021, 2022, 2023]


def week1_team(Y):
    d = pd.read_parquet(os.path.join(PBP, f'depth_charts_{Y}.parquet'),
                        columns=['season', 'club_code', 'week', 'game_type', 'position', 'full_name'])
    d = d[(d.game_type == 'REG') & d.position.isin(['QB', 'RB', 'WR', 'TE'])]
    d = d.sort_values('week').groupby(['full_name', 'position']).head(1)
    return {(_norm_name(n), p): tm(t) for n, p, t in zip(d.full_name, d.position, d.club_code)}


def team_tt(Y):
    lines, _ = load_lines(Y)
    early, late = {}, {}
    for (t, wk), v in lines.items():
        if wk <= 3:
            early.setdefault(t, []).append(v)
        if wk >= 15:
            late.setdefault(t, []).append(v)
    return ({t: float(np.mean(v)) for t, v in early.items()},
            {t: float(np.mean(v)) for t, v in late.items()})


def main():
    w = World(2025)
    w.rows(FORMATS['1qb'], 2025)   # sets the replacement table vor() reads
    tt, tt_late, team = {}, {}, {}
    for Y in YRS:
        tt[Y], _ = team_tt(Y)
        _, tt_late[Y - 1] = team_tt(Y - 1)
        team[Y] = week1_team(Y)
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = [x for x in build(True) if x['Y'] in YRS]
    m3_ship(recs, c)
    keep = []
    for x in recs:
        t = team[x['Y']].get(x['key'])
        if not t or t not in tt[x['Y']]:
            continue
        x['team'] = t
        x['tt'] = tt[x['Y']][t]
        x['tt_chg'] = x['tt'] - tt_late[x['Y'] - 1].get(t, x['tt'])
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
        x['v1'] = w.vor(x['key'], x['Y']) or 0.0
        keep.append(x)
    print(f'matched {len(keep)} of {len(recs)} pool player-seasons to a week-1 team')
    recs = keep
    for Y in YRS:
        ys = [x for x in recs if x['Y'] == Y]
        for key, f in (('f0', lambda x: x['fz']), ('r1', lambda x: -x['v1']), ('mp', lambda x: x['m0']),
                       ('sp', lambda x: x['s0']), ('r3', lambda x: x['r_t3']), ('r5', lambda x: x['r_lt'])):
            if key == 'r5' and any(x.get('r_lt') is None for x in ys):
                continue                       # 5-year truth not complete yet
            for i, x in enumerate(sorted(ys, key=f)):
                x[key] = i + 1
    print('pool by pos: ' + ' '.join(f'{p} {sum(1 for x in recs if x["pos"] == p)}' for p in ('QB', 'RB', 'WR', 'TE')))
    a = np.array([x['tt'] for x in recs])
    print(f'team total wks 1-3: mean {a.mean():.1f} sd {a.std():.1f} range {a.min():.1f}-{a.max():.1f}')

    def zs(v):
        v = np.array(v, float); return (v - v.mean()) / (v.std() or 1)

    rng = np.random.default_rng(11)
    groups = (('QB',), ('RB',), ('WR',), ('TE',), ('WR', 'TE'), ('RB', 'WR', 'TE'), ('QB', 'RB', 'WR', 'TE'))
    for feat, flbl in (('tt', 'TEAM IMPLIED TOTAL entering season (higher = +)'), ('tt_chg', 'CHANGE vs last December')):
        for tk, tl in (('r1', 'season Y'), ('r3', '3 years')):
            print(f'\n=== {flbl} — truth {tl} ===')
            print(f'{"group":<12}{"n":>5}{"raw":>8}{"priced":>8}{"beyond MKT":>20}{"beyond SIM":>20}{"beyond FAIR":>20}')
            for grp in groups:
                g = [x for x in recs if x['pos'] in grp]
                if len(g) < 30:
                    continue
                q = zs([x[feat] for x in g])
                t = np.array([math.log(x[tk]) for x in g])
                raw = spearman(list(q), list(-t))
                pri = spearman(list(q), [-math.log(x['mp']) for x in g])
                keys = np.array([hash(x['key']) for x in g]); uk = np.unique(keys)
                byk = {k: np.where(keys == k)[0] for k in uk}
                cells = []
                for pk in ('mp', 'sp', 'f0'):
                    pr = np.array([math.log(x[pk]) for x in g])
                    X = np.column_stack([np.ones(len(g)), pr, q])
                    b = np.linalg.lstsq(X, t, rcond=None)[0][2]
                    bs = []
                    for _ in range(300):
                        ii = np.concatenate([byk[k] for k in rng.choice(uk, len(uk))])
                        bs.append(np.linalg.lstsq(X[ii], t[ii], rcond=None)[0][2])
                    lo, hi = np.percentile(bs, [2.5, 97.5])
                    cells.append(f'{b:+.3f} [{lo:+.2f},{hi:+.2f}]{"*" if lo > 0 or hi < 0 else " "}')
                print(f'{"+".join(grp):<12}{len(g):>5}{raw:>+8.3f}{pri:>+8.3f}' + ''.join(f'{c_:>20}' for c_ in cells))
    print('\n   raw / priced = Spearman with a better rank; beyond X = coef on z(team total) in log realized rank ~ log X rank'
          ' + z (< 0 = high-total players BEAT that rank = under-priced; * = 95% CI excludes 0)')

    print('\n=== leave-one-year-out: FAIR / SIM + k x feature, per-year Spearman (whole pool, and RB/WR/TE) ===')
    for grp in (('QB', 'RB', 'WR', 'TE'), ('RB', 'WR', 'TE'), ('WR', 'TE')):
        for feat in ('tt', 'tt_chg'):
            for base, bk in (('FAIR', 'f0'), ('SIM', 'sp')):
                for tk, tl in (('r1', 'season'), ('r3', '3yr'), ('r5', '5yr+y')):
                    d0, d1 = [], []
                    ys_ok = [Y for Y in YRS if all(tk in x for x in recs if x['Y'] == Y)]
                    for Y in ys_ok:
                        tr = [x for x in recs if x['Y'] != Y and x['Y'] in ys_ok and x['pos'] in grp]
                        te = [x for x in recs if x['Y'] == Y and x['pos'] in grp]
                        mu = np.mean([x[feat] for x in tr]); sd = np.std([x[feat] for x in tr]) or 1
                        X = np.column_stack([np.ones(len(tr)), [math.log(x[bk]) for x in tr], [(x[feat] - mu) / sd for x in tr]])
                        b = np.linalg.lstsq(X, np.array([math.log(x[tk]) for x in tr]), rcond=None)[0]
                        pred = [b[1] * math.log(x[bk]) + b[2] * (x[feat] - mu) / sd for x in te]
                        d0.append(spearman([-math.log(x[bk]) for x in te], [-x[tk] for x in te]))
                        d1.append(spearman([-p for p in pred], [-x[tk] for x in te]))
                    wins = sum(a_ > b_ + 1e-9 for a_, b_ in zip(d1, d0))
                    print(f'   {"+".join(grp):<12}{base:<5}+ {feat:<7} vs {tl:<7} {np.mean(d0):.3f} -> {np.mean(d1):.3f} '
                          f'({wins}/{len(ys_ok)})')

    print('\n=== examples: market top-60 RB/WR/TE on the highest / lowest team totals ===')
    top = sorted([x for x in recs if x['mp'] <= 60 and x['pos'] != 'QB'], key=lambda x: -x['tt'])
    for x in top[:6] + top[-6:]:
        print(f'   {x["Y"]} {x["key"][0]:<22}{x["pos"]:<3} {x["team"]:<4} tt {x["tt"]:.1f}  mkt #{x["mp"]:<4} '
              f'FAIR #{x["f0"]:<4} -> season #{x["r1"]:<4} 3yr #{x["r3"]}')


if __name__ == '__main__':
    main()
