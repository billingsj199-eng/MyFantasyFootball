#!/usr/bin/env python3
"""
backtest_redraft_rating.py - the REDRAFT rating = the MFF "rankings" order
(Jack 2026-11-24: "now build the redraft rating" / "this would be the mff 'rankings' order" /
"because it isnt always as simple as proj ppg with risk, upside etc").

Question: before week W, which ORDER of players best matches what each player was actually worth
to a roster for the rest of the season - and do risk and upside signals add to projected points?

Truth = REALIZED STARTABLE VALUE (same definition as backtest_option_vor.py): over the rest of the
fantasy season (final NFL week excluded), sum of (actual points - replacement) in the weeks his
pre-game projection was at or above replacement. Missed games count 0, dud weeks count against him,
spike weeks only count when you would really have started him. Replacement = best non-starter in a
12-team league (QB13 / RB26 / WR36 / TE13 by that week's projection), per Jack 10-05.

Rows = data/metric_atlas_rows.parquet (2019-25, the harness stand-in for the live engine; half-PPR).
Checkpoints: before weeks 3..(final - 4). In-house inputs only; ESPN and ADP are benchmarks.

Orders graded:
    projection        this week's projection over replacement (the "simple" ranking)
    base projection   the matchup-free base over replacement x weeks left
    season PPG        points per game so far over replacement
    ADP / ESPN        outside benchmarks (preseason ADP; ESPN's projection this week)
    RATING mean       model on projection + season PPG + games + weeks left   (no risk, no upside)
    RATING + risk     + injury report, practice status, age, snap share and trend, games missed, dud rate, volatility
    RATING full       + upside: rookie / year 2, draft capital, usage trend, vacated and inherited work,
                        expected points vs actual (luck), red-zone and goal-line role, spike rate, best game
Forward in time (train on earlier seasons, test 2022-25) and leave-one-season-out.

Usage: python backtest_redraft_rating.py
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor

warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'preseason2027'))
OUT = os.path.join(HERE, '_dyn_cache', 'redraft')
REPL_N = {'QB': 13, 'RB': 26, 'WR': 36, 'TE': 13}
MEAN = ['proj_or', 'base_or', 'ppg_or', 'live', 'base2', 'ppg', 'g', 'weeks_left', 'pos_qb', 'pos_rb', 'pos_wr', 'pos_te']
RISK = ['rep_q', 'rep_d', 'prac_dnp', 'prac_lim', 'age', 'snap_std', 'snap_l1', 'snap_trend', 'qb_out', 'missed', 'vol', 'dud_rate', 'start_rate']
UPSIDE = ['rookie', 'yr2', 'draft_pick', 'exp', 'tgt_trend', 'car_trend', 'tgt_sh', 'car_sh', 'tgt_sh_l3', 'car_sh_l3', 'vac_tgt', 'vac_car',
          'inherit_tgt', 'inherit_car', 'xfp_pg', 'pts_over_xfp', 'wopr', 'rz_tgt_sh', 'rz_car_sh', 'gl_car_sh', 'boom_rate', 'best_or', 'l3_or', 'td_luck_adj']
LOG = None


def out(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    LOG.write(s + '\n')


def final_week(y):
    return 17 if y <= 2020 else 18


def load():
    import decisions_backtest as DB
    B = DB.load_rows()[['year', 'wk', 'pid', 'espn', 'adp']].dropna(subset=['pid']).drop_duplicates(['year', 'wk', 'pid'])
    M = pd.read_parquet(os.path.join(HERE, 'data', 'metric_atlas_rows.parquet'))
    M = M.drop_duplicates(['year', 'wk', 'name', 'pos']).merge(B, on=['year', 'wk', 'pid'], how='left')
    M['pk'] = M.pid.fillna(M.name + '|' + M.pos)      # a few rows have no player id
    M['fw'] = M.year.map(final_week)
    M = M[M.wk < M.fw].copy()
    # replacement: the Nth best projection at the position that week, averaged over the season
    r = {}
    for (y, p), g in M.groupby(['year', 'pos']):
        v = [np.sort(x.live.to_numpy())[::-1][REPL_N[p] - 1] for _, x in g.groupby('wk') if len(x) >= REPL_N[p]]
        r[(y, p)] = float(np.mean(v))
    M['R'] = [r[(y, p)] for y, p in zip(M.year, M.pos)]
    M = M.sort_values(['year', 'pk', 'wk']).reset_index(drop=True)
    # startable value from this week on (truth) + plain alternatives
    M['sv_w'] = np.where(M.live >= M.R, M.act - M.R, 0.0)
    M['vor_w'] = M.act - M.R
    g = M.groupby(['year', 'pk'])
    M['SV'] = g.sv_w.transform(lambda s: s[::-1].cumsum()[::-1])
    M['VOR_all'] = g.vor_w.transform(lambda s: s[::-1].cumsum()[::-1])
    M['g_fut'] = g.act.transform(lambda s: np.arange(len(s), 0, -1))
    M['weeks_left'] = M.fw - M.wk
    M['avail'] = M.g_fut / M.weeks_left
    # what was known before this week: volatility, spike / dud / start rates, best game, last 3
    ex = M.act - M.R
    M['_ex'] = ex
    sh = lambda f: g._ex.transform(lambda s: f(s.shift(1)))
    M['vol'] = sh(lambda s: s.expanding(2).std())
    M['best_or'] = sh(lambda s: s.expanding(1).max())
    M['l3_or'] = sh(lambda s: s.rolling(3, min_periods=1).mean())
    M['boom_rate'] = g._ex.transform(lambda s: (s.shift(1) >= 8).expanding(1).mean())
    M['dud_rate'] = g._ex.transform(lambda s: (s.shift(1) <= -4).expanding(1).mean())
    M['start_rate'] = g.sv_w.transform(lambda s: (s.shift(1) != 0).expanding(1).mean())
    first = g.cumcount() == 0
    for c in ('boom_rate', 'dud_rate', 'start_rate'):
        M.loc[first, c] = np.nan
    M['missed'] = (M.wk - 1 - M.g).clip(lower=0)
    M['proj_or'] = M.live - M.R
    M['base_or'] = (M.base2 - M.R) * M.weeks_left
    M['ppg_or'] = M.ppg - M.R
    M['espn_or'] = M.espn - M.R
    M['adp_or'] = -M.adp
    M = M[(M.wk >= 3) & (M.weeks_left >= 4)].reset_index(drop=True)
    return M


def gb():
    return HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=40, l2_regularization=2.0, random_state=0)


def predict(M, feats, mode, target='SV'):
    pr = pd.Series(np.nan, index=M.index)
    for Y in sorted(M.year.unique()):
        te = M.year == Y
        tr = (M.year < Y) if mode == 'forward' else (M.year != Y)
        if tr.sum() < 3000:
            continue
        pr[te] = gb().fit(M.loc[tr, feats], M.loc[tr, target]).predict(M.loc[te, feats])
    return pr


def grade(M, orders, title, truth='SV', mask=None):
    Z = M if mask is None else M[mask]
    Z = Z[Z[orders[-1][0]].notna()]
    out('\n  %s   (%d checkpoints, %d player-weeks)' % (title, Z.groupby(['year', 'wk']).ngroups, len(Z)))
    out('    %-22s %8s %8s %8s %8s %10s %10s' % ('order', 'all', 'RB', 'WR', 'top-100', 'top-24 val', 'top-50 val'))
    res = {}
    for col, name in orders:
        a, rb, wr, t100, c24, c50 = [], [], [], [], [], []
        for _, z in Z.groupby(['year', 'wk']):
            z = z[z[col].notna()]
            if len(z) < 60:
                continue
            y = z[truth]
            a.append(spearmanr(z[col], y)[0])
            for p, acc in (('RB', rb), ('WR', wr)):
                q = z[z.pos == p]
                if len(q) >= 15:
                    acc.append(spearmanr(q[col], q[truth])[0])
            top = z.nlargest(100, 'proj_or')
            t100.append(spearmanr(top[col], top[truth])[0])
            pos = y.clip(lower=0)
            for n, acc in ((24, c24), (50, c50)):
                best = pos.nlargest(n).sum()
                acc.append(pos[z[col].rank(ascending=False, method='first') <= n].sum() / best if best > 0 else np.nan)
        res[name] = np.mean(a)
        out('    %-22s %8.3f %8.3f %8.3f %8.3f %9.1f%% %9.1f%%' % (name, np.mean(a), np.mean(rb), np.mean(wr), np.mean(t100), 100 * np.nanmean(c24), 100 * np.nanmean(c50)))
    return res


def by_year(M, a, b, na, nb):
    parts = []
    for y, zy in M[M[a].notna() & M[b].notna()].groupby('year'):
        d = [spearmanr(z[a], z.SV)[0] - spearmanr(z[b], z.SV)[0] for _, z in zy.groupby('wk') if len(z) >= 60]
        parts.append('%d %+.3f' % (y, np.mean(d)))
    out('    %s minus %s, by season: %s' % (na, nb, '   '.join(parts)))


def importance(M, feats, label):
    rng = np.random.default_rng(11)
    tr, te = M.year < 2024, M.year >= 2024
    m = gb().fit(M.loc[tr, feats], M.loc[tr, 'SV'])
    B = M[te]
    base = np.mean([spearmanr(m.predict(z[feats]), z.SV)[0] for _, z in B.groupby(['year', 'wk'])])
    d = {}
    for f in feats:
        C = B.copy(); C[f] = rng.permutation(C[f].to_numpy())
        d[f] = base - np.mean([spearmanr(m.predict(z[feats]), z.SV)[0] for _, z in C.groupby(['year', 'wk'])])
    lab = {'proj_or': 'projection over replacement', 'base_or': 'base projection x weeks left', 'ppg_or': 'season PPG over replacement', 'weeks_left': 'weeks left',
           'rep_q': 'listed questionable', 'rep_d': 'listed doubtful', 'prac_dnp': 'missed practice', 'prac_lim': 'limited practice', 'age': 'age', 'snap_std': 'snap share',
           'snap_l1': 'snap share last game', 'snap_trend': 'snap share trend', 'missed': 'games missed so far', 'vol': 'week-to-week volatility', 'dud_rate': 'dud-week rate',
           'start_rate': 'share of weeks startable', 'rookie': 'rookie', 'yr2': 'second-year player', 'draft_pick': 'draft capital', 'exp': 'experience',
           'tgt_trend': 'target share trend', 'car_trend': 'carry share trend', 'xfp_pg': 'expected points per game (usage)', 'pts_over_xfp': 'points over expected (luck)',
           'boom_rate': 'spike-week rate', 'best_or': 'best game so far', 'l3_or': 'last 3 games over replacement', 'tgt_sh': 'target share', 'car_sh': 'carry share',
           'rz_car_sh': 'red-zone carry share', 'gl_car_sh': 'goal-line carry share', 'rz_tgt_sh': 'red-zone target share', 'wopr': 'target + air-yard share',
           'vac_tgt': 'vacated targets', 'vac_car': 'vacated carries', 'inherit_tgt': 'inherited targets', 'inherit_car': 'inherited carries', 'td_luck_adj': 'TD luck',
           'tgt_sh_l3': 'target share last 3', 'car_sh_l3': 'carry share last 3', 'qb_out': 'starting QB out', 'g': 'games played', 'ppg': 'season PPG', 'live': 'projection', 'base2': 'base projection'}
    out('\n  what carries %s (2024-25 held out, rank corr %.3f; loss when the input is scrambled):' % (label, base))
    for f, v in sorted(d.items(), key=lambda kv: -kv[1])[:14]:
        grp = 'mean' if f in MEAN else 'risk' if f in RISK else 'upside'
        out('    %-34s %-7s %.4f' % (lab.get(f, f), grp, v))


def main():
    global LOG
    os.makedirs(OUT, exist_ok=True)
    LOG = open(os.path.join(OUT, 'redraft_rating.log'), 'w', encoding='utf-8')
    M = load()
    out('redraft rating backtest | %d player-weeks | seasons %d-%d | checkpoints weeks %d-%d | half-PPR'
        % (len(M), M.year.min(), M.year.max(), M.wk.min(), M.wk.max()))
    out('replacement (points a week): ' + ', '.join('%s %.1f' % (p, M[M.pos == p].R.mean()) for p in ('QB', 'RB', 'WR', 'TE')))
    out('ESPN matched %.0f%%, ADP %.0f%%' % (100 * M.espn.notna().mean(), 100 * M.adp.notna().mean()))
    for mode, lab in (('forward', 'FORWARD IN TIME (train on earlier seasons; tests 2022-25)'), ('loyo', 'LEAVE ONE SEASON OUT (2019-25)')):
        M['r_mean'] = predict(M, MEAN, mode)
        M['r_risk'] = predict(M, MEAN + RISK, mode)
        M['r_full'] = predict(M, MEAN + RISK + UPSIDE, mode)
        orders = [('proj_or', 'projection'), ('base_or', 'base projection'), ('ppg_or', 'season PPG'), ('adp_or', 'ADP (benchmark)'), ('espn_or', 'ESPN (benchmark)'),
                  ('r_mean', 'RATING mean'), ('r_risk', 'RATING + risk'), ('r_full', 'RATING full')]
        out('\n=== %s ===   rank corr with realized startable value; value captured by each order\'s top 24 / 50' % lab)
        grade(M, orders, 'all checkpoints')
        grade(M, orders, 'early season (before weeks 3-6)', mask=M.wk <= 6)
        grade(M, orders, 'mid season (before weeks 7-10)', mask=(M.wk >= 7) & (M.wk <= 10))
        grade(M, orders, 'late season (before weeks 11-14)', mask=M.wk >= 11)
        by_year(M, 'r_full', 'proj_or', 'RATING full', 'projection')
        by_year(M, 'r_full', 'r_mean', 'RATING full', 'RATING mean')
        by_year(M, 'r_full', 'espn_or', 'RATING full', 'ESPN')
        if mode == 'forward':
            grade(M, orders, 'same orders graded on a "must start him every week he plays" truth', truth='VOR_all')
            importance(M, MEAN + RISK + UPSIDE, 'the full rating')
            M[['year', 'wk', 'pid', 'name', 'pos', 'team', 'live', 'R', 'SV', 'VOR_all', 'avail', 'proj_or', 'r_mean', 'r_risk', 'r_full']].to_parquet(
                os.path.join(OUT, 'redraft_preds_forward.parquet'), index=False)
    M.to_parquet(os.path.join(OUT, 'redraft_rows.parquet'), index=False)
    LOG.close()


if __name__ == '__main__':
    main()
