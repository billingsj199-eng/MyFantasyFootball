#!/usr/bin/env python3
"""
backtest_redraft_struct.py - risk and upside added to the redraft order ONE PIECE AT A TIME
(Jack 2026-11-24: "it isnt always as simple as proj ppg with risk, upside etc").

backtest_redraft_rating.py showed a 37-input model ranks WORSE than the plain projection. Here each
idea gets its own small model and enters the value formula where it belongs:

    value = sum over the weeks left of  P(he plays)  x  E[ max(0, projection that week - replacement) ]

    AVAILABILITY  P(plays): share of the remaining weeks he will play - from the injury report, practice
                  status, games already missed, age, position
    ROLE DRIFT    where his projection is heading: future base projection minus today's - from rookie /
                  year 2, usage trend, snap trend, points vs expected (luck), last 3 games vs his base
    OPTION        projections move, and you bench a player who falls below replacement but ride one who
                  climbs: E[max(0, x - R)] with the real spread of projection changes (by position, weeks ahead)

Truth, pool and grading are the same as backtest_redraft_rating.py (realized startable value, 2019-25,
forward in time and leave-one-season-out).

Usage: python backtest_redraft_struct.py
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd
from scipy.stats import norm, spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor

warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_redraft_rating as B  # noqa: E402

OUT = B.OUT
AV_F = ['rep_q', 'rep_d', 'prac_dnp', 'prac_lim', 'missed', 'age', 'g', 'weeks_left', 'snap_std', 'pos_qb', 'pos_rb', 'pos_wr', 'pos_te']
DR_F = ['gap_ppg', 'gap_l3', 'rookie', 'yr2', 'exp', 'tgt_trend', 'car_trend', 'snap_trend', 'pts_over_xfp', 'td_luck_adj', 'wk', 'base_rel',
        'pos_qb', 'pos_rb', 'pos_wr', 'pos_te']


def small():
    return HistGradientBoostingRegressor(max_depth=2, learning_rate=0.05, max_iter=200, min_samples_leaf=80, l2_regularization=5.0, random_state=0)


def call(mu, R, sd):
    d = (mu - R) / sd
    return sd * norm.pdf(d) + (mu - R) * norm.cdf(d)


def prep(M):
    M = M.sort_values(['year', 'pk', 'wk']).reset_index(drop=True)
    g = M.groupby(['year', 'pk'])
    # mean base projection over his LATER games this season (what the projection became)
    rev_sum = g.base2.transform(lambda s: s[::-1].cumsum()[::-1]) - M.base2
    n_fut = M.g_fut - 1
    M['fut_base'] = (rev_sum / n_fut.replace(0, np.nan))
    M['drift'] = M.fut_base - M.base2
    M['gap_ppg'] = M.ppg - M.base2
    M['gap_l3'] = (M.l3_or + M.R) - M.base2
    M['base_rel'] = M.base2 / M.R
    return M


def fit_predict(M, mode):
    A = pd.Series(np.nan, index=M.index); Dr = pd.Series(np.nan, index=M.index); SD = pd.Series(np.nan, index=M.index)
    for Y in sorted(M.year.unique()):
        te = M.year == Y
        tr = (M.year < Y) if mode == 'forward' else (M.year != Y)
        if tr.sum() < 3000:
            continue
        T = M[tr]
        A[te] = np.clip(small().fit(T[AV_F], T.avail).predict(M.loc[te, AV_F]), 0.05, 1.0)
        Td = T[T.drift.notna()]
        md = small().fit(Td[DR_F], Td.drift)
        Dr[te] = md.predict(M.loc[te, DR_F])
        # spread of "what the projection became" around today's base + predicted drift, by position and weeks left
        res = Td.drift - md.predict(Td[DR_F])
        tab = pd.DataFrame({'pos': Td.pos, 'b': pd.cut(Td.weeks_left, [0, 6, 10, 20], labels=False), 'r': res}).groupby(['pos', 'b']).r.std()
        bb = pd.cut(M.loc[te, 'weeks_left'], [0, 6, 10, 20], labels=False)
        SD[te] = [tab.get((p, b), np.nan) for p, b in zip(M.loc[te, 'pos'], bb)]
    return A, Dr, SD


def diag(M, col, target, name):
    c = [spearmanr(z[col], z[target])[0] for _, z in M[M[col].notna() & M[target].notna()].groupby(['year', 'wk']) if len(z) >= 60]
    B.out('    %-58s rank corr %.3f' % (name, np.mean(c)))


def main():
    B.LOG = open(os.path.join(OUT, 'redraft_struct.log'), 'w', encoding='utf-8')
    M = prep(B.load())
    B.out('structured redraft value | %d player-weeks 2019-25' % len(M))
    B.out('actual share of remaining weeks played: mean %.2f | by status: healthy %.2f, questionable %.2f, doubtful %.2f, missed practice %.2f'
          % (M.avail.mean(), M[(M.rep_q == 0) & (M.rep_d == 0)].avail.mean(), M[M.rep_q == 1].avail.mean(), M[M.rep_d == 1].avail.mean(), M[M.prac_dnp == 1].avail.mean()))
    for mode, lab in (('forward', 'FORWARD IN TIME (tests 2022-25)'), ('loyo', 'LEAVE ONE SEASON OUT')):
        A, Dr, SD = fit_predict(M, mode)
        M['A'], M['Dr'], M['SD'] = A, Dr, SD
        wl = M.weeks_left
        M['e_base'] = (M.base2 - M.R) * wl
        M['e_floor'] = (M.base2 - M.R).clip(lower=0) * wl
        M['e_opt'] = call(M.base2, M.R, M.SD) * wl
        M['e_av'] = (M.base2 - M.R) * wl * M.A
        M['e_opt_av'] = call(M.base2, M.R, M.SD) * wl * M.A
        M['e_dr'] = (M.base2 + M.Dr - M.R) * wl
        M['e_all'] = call(M.base2 + M.Dr, M.R, M.SD) * wl * M.A
        # this week's projection is known exactly, later weeks carry the drift + option
        now = np.where(M.live >= M.R, M.live - M.R, 0.0)
        M['e_all2'] = now + call(M.base2 + M.Dr, M.R, M.SD) * (wl - 1) * M.A
        M['e_mix'] = now + (M.base2 - M.R).clip(lower=0) * (wl - 1) * M.A
        B.out('\n=== %s ===' % lab)
        B.out('  can each piece be predicted at all?')
        diag(M, 'A', 'avail', 'AVAILABILITY model vs share of remaining weeks played')
        diag(M, 'Dr', 'drift', 'ROLE DRIFT model vs how his base projection changed')
        M['e_now'] = (M.live - M.R) + (M.base2 - M.R) * (wl - 1)                       # this week's matchup + base after
        M['e_now_opt'] = np.where(M.live >= M.R, M.live - M.R, 0.0) + call(M.base2, M.R, M.SD) * (wl - 1) * M.A
        rk = lambda c: M.groupby(['year', 'wk'])[c].rank(pct=True)
        M['e_mkt'] = rk('e_base') + rk('espn_or')                                           # benchmark only: our base + ESPN, equal ranks
        # every row graded on the SAME checkpoints: only where the small models exist
        orders = [('proj_or', 'projection'), ('e_base', 'base projection'), ('e_now', 'this wk + base after'), ('espn_or', 'ESPN (benchmark)'),
                  ('e_mkt', 'base + ESPN (benchmark)'), ('e_av', '+ availability'), ('e_opt', '+ option'), ('e_dr', '+ role drift'),
                  ('e_now_opt', 'this wk + option x avail'), ('e_opt_av', '+ option + avail')]
        ok = M.A.notna()
        B.grade(M, orders, 'all checkpoints', mask=ok)
        B.grade(M, orders, 'late season (before weeks 11-14)', mask=ok & (M.wk >= 11))
        B.grade(M, orders, 'bench zone only (projected below replacement)', mask=ok & (M.base2 < M.R))
        for p_ in ('QB', 'TE'):
            c0 = [spearmanr(z.e_base, z.SV)[0] for _, z in M[ok & (M.pos == p_)].groupby(['year', 'wk']) if len(z) >= 10]
            c1 = [spearmanr(z.e_opt_av, z.SV)[0] for _, z in M[ok & (M.pos == p_)].groupby(['year', 'wk']) if len(z) >= 10]
            B.out('    %s only: base projection %.3f, + option + avail %.3f' % (p_, np.mean(c0), np.mean(c1)))
        for a, na in (('e_opt_av', '+ option + avail'), ('e_av', '+ availability'), ('e_opt', '+ option'), ('e_dr', '+ role drift'), ('e_mkt', 'base + ESPN')):
            B.by_year(M, a, 'e_base', na, 'base projection')
        if mode == 'forward':
            M[['year', 'wk', 'pk', 'name', 'pos', 'base2', 'live', 'R', 'SV', 'avail', 'A', 'Dr', 'drift', 'SD', 'e_base', 'e_all', 'e_all2']].to_parquet(
                os.path.join(OUT, 'redraft_struct_forward.parquet'), index=False)
    B.LOG.close()


if __name__ == '__main__':
    main()
