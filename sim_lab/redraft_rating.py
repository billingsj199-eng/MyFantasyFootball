#!/usr/bin/env python3
"""
redraft_rating.py - PROTOTYPE redraft rating = the MFF "rankings" order (Jack 2026-11-24).
Nothing here is wired to the site.

What survived the tests (backtest_redraft_rating.py, backtest_redraft_struct.py; 2019-25, graded on
realized startable value):
  - our weekly projection over replacement already ties ESPN and beats season PPG and ADP
  - the one in-house addition that helps every season is the OPTION: a projection can climb or fall,
    and you ride it when it climbs and bench it when it falls (+.007 rank corr; bench stashes .034 -> .077)
  - injury-report / practice / age / volatility "risk" inputs add nothing to the ORDER; chasing role
    trends hurts; a 37-input model is worse than the plain projection
So:
  VALUE  = this week: max(0, projection - replacement)
           + each later fantasy week (through 17): E[max(0, projection - replacement)] with the real
             spread of how projections move that many weeks ahead (by position)
  RATING = 99 x sqrt(VALUE / best VALUE on the board)
  shown next to it, not in the order: NOW (this week over replacement), FLOOR (share of his games at or
  above replacement), CEILING (share of games 8+ over replacement), UPSIDE (share of VALUE that is option),
  games missed this season.

Reads the live sim export (site data/sim_proj_2026.json, half-PPR column) and this season's games.
Replacement = best non-starter, 12-team: QB13 / RB26 / WR36 / TE13 by that week's projection.
Usage: python redraft_rating.py [--week N]      Output: _dyn_cache/redraft/redraft_rating_now.csv
"""
import argparse
import json
import os
import re
import sys

import numpy as np
import pandas as pd
from scipy.stats import norm

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '_dyn_cache', 'redraft')
SITE = os.path.join(os.path.dirname(HERE), 'MyFantasyFootball Files', 'data')
REPL_N = {'QB': 13, 'RB': 26, 'WR': 36, 'TE': 13}
LAST_WEEK = 17      # fantasy season (the final NFL week is left out, as in every grading rule here)
SC = 0              # export column: 0 half-PPR, 1 PPR, 2 standard


ALIAS = {'ken walker': 'kenneth walker', 'hollywood brown': 'marquise brown', 'chig okonkwo': 'chigoziem okonkwo'}


def nrm(s):
    s = str(s).lower().replace('.', '').replace("'", '').replace('-', ' ')
    s = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return ALIAS.get(s, s)


def consensus_ranks():
    """FantasyPros rest-of-season rank the site already stores (data/d.js fpR) - a benchmark column only."""
    t = open(os.path.join(SITE, 'd.js'), encoding='utf-8').read()
    pos = [(m.start(), m.group(1)) for m in re.finditer(r'"n":"([^"]+)"', t)]
    out = {}
    for i, (a, n) in enumerate(pos):
        seg = t[a:pos[i + 1][0] if i + 1 < len(pos) else len(t)]
        m = re.search(r'"fpR":([0-9.]+)', seg)
        if m:
            out.setdefault(nrm(n), float(m.group(1)))
    return out


def sigma_table():
    """How far a player's base projection moves k weeks ahead, by position (2019-25 harness rows)."""
    f = os.path.join(OUT, 'proj_sigma.json')
    if os.path.exists(f):
        return json.load(open(f))
    M = pd.read_parquet(os.path.join(HERE, 'data', 'metric_atlas_rows.parquet'), columns=['year', 'pid', 'name', 'pos', 'wk', 'base2'])
    M['pk'] = M.pid.fillna(M.name + '|' + M.pos)
    out = {}
    for p, g in M.groupby('pos'):
        piv = g.pivot_table(index=['year', 'pk'], columns='wk', values='base2', aggfunc='first')
        tab = {}
        for k in range(1, 8):
            d = []
            for w in piv.columns:
                if w + k in piv.columns:
                    d.append((piv[w + k] - piv[w]).dropna().to_numpy())
            x = np.concatenate(d)
            tab[str(k)] = float(np.std(x))
        out[p] = tab
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(f, 'w'), indent=1)
    return out


def call(mu, R, sd):
    if sd <= 0:
        return max(0.0, mu - R)
    d = (mu - R) / sd
    return float(sd * norm.pdf(d) + (mu - R) * norm.cdf(d))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--week', type=int, help='first week to value (default: the first week with no games played yet)')
    a = ap.parse_args()
    S = json.load(open(os.path.join(SITE, 'sim_proj_2026.json'), encoding='utf-8'))
    pos = {n: v[0] for n, v in S['luck'].items() if v and v[0] in REPL_N}
    # this season's games (half-PPR) for the floor / ceiling columns
    W = pd.read_parquet(os.path.join(HERE, '_dyn_cache', 'ktc_wb', 'player_weeks_2026.parquet'), columns=['week', 'display_name', 'position', 'half'])
    played = int(W.week.max())
    w0 = a.week or played + 1
    for n, p in zip(W.display_name, W.position):
        pos.setdefault(n, p)
    sig = sigma_table()
    weeks = [w for w in range(w0, LAST_WEEK + 1) if str(w) in S['weeks']]
    proj = {w: {n: (v[SC] or 0.0) for n, v in S['weeks'][str(w)].items() if n in pos and v and v[SC] is not None} for w in weeks}
    R = {}
    for w in weeks:
        for p, N in REPL_N.items():
            v = sorted((x for n, x in proj[w].items() if pos[n] == p), reverse=True)
            R[(w, p)] = v[N - 1] if len(v) >= N else 0.0
    names = sorted({n for w in weeks for n in proj[w]})
    gkey = {}
    for n, g in W.groupby('display_name'):
        gkey[nrm(n)] = g
    rows = []
    for n in names:
        p = pos[n]
        val = intr = 0.0
        now = None
        for k, w in enumerate(weeks):
            mu = proj[w].get(n, 0.0)
            if mu <= 0:            # bye or ruled out that week
                if k == 0:
                    now = 0.0
                continue
            r = R[(w, p)]
            sd = 0.0 if k == 0 else sig[p][str(min(k, 7))]
            c = call(mu, r, sd)
            val += c; intr += max(0.0, mu - r)
            if k == 0:
                now = mu - r
        g = gkey.get(nrm(n))
        r_now = np.mean([R[(w, p)] for w in weeks])
        gp = len(g) if g is not None else 0
        floor = float((g.half >= r_now).mean()) if gp else np.nan
        ceil = float((g.half >= r_now + 8).mean()) if gp else np.nan
        ppg = float(g.half.mean()) if gp else np.nan
        ros = np.mean([proj[w].get(n, 0.0) for w in weeks if proj[w].get(n, 0.0) > 0]) if any(proj[w].get(n, 0.0) > 0 for w in weeks) else 0.0
        rows.append({'name': n, 'pos': p, 'team': S['teamOf'].get(n, ''), 'value': val, 'intrinsic': intr, 'now_or': now if now is not None else 0.0,
                     'ros_ppg': ros, 'ros_or': ros - r_now, 'weeks': sum(1 for w in weeks if proj[w].get(n, 0.0) > 0),
                     'ppg': ppg, 'gp': gp, 'missed': max(0, played - 1 - gp) if gp else np.nan, 'floor': floor, 'ceiling': ceil})
    D = pd.DataFrame(rows)
    fp = consensus_ranks()
    D['fp'] = [fp.get(nrm(n), np.nan) for n in D.name]
    D = D[(D.value > 0) | (D.ros_ppg >= 4)].copy()
    D['rating'] = np.round(99 * np.sqrt(D.value / D.value.max())).astype(int)
    D['upside_sh'] = np.where(D.value > 0, (D.value - D.intrinsic) / D.value, 0.0)
    D['rk'] = D.value.rank(ascending=False, method='first').astype(int)
    D['rk_proj'] = D.ros_or.rank(ascending=False, method='first').astype(int)       # the "simple" order: ROS projection over replacement
    D['pos_rk'] = D.groupby('pos').value.rank(ascending=False, method='first').astype(int)
    D = D.sort_values('rk')
    os.makedirs(OUT, exist_ok=True)
    D.to_csv(os.path.join(OUT, 'redraft_rating_now.csv'), index=False, float_format='%.3f')
    print('sim export updated %s | games played through week %d | valuing weeks %d-%d | %d players' % (S['updated'][:16], played, weeks[0], weeks[-1], len(D)))
    print('replacement this week (half-PPR): ' + ', '.join('%s %.1f' % (p, R[(weeks[0], p)]) for p in REPL_N))
    print('projection spread k weeks ahead: ' + ' | '.join('%s %s' % (p, ' '.join('%.1f' % sig[p][str(k)] for k in (1, 3, 5))) for p in REPL_N))
    print('\n%3s %-24s %-3s %-4s %6s %6s %7s %6s %6s %7s %7s %6s' % ('#', 'player', 'pos', 'team', 'RATING', 'value', 'ROS/g', 'now', 'floor', 'ceiling', 'upside', 'missed'))
    for r in D.head(60).itertuples():
        print('%3d %-24s %-3s %-4s %6d %6.0f %7.1f %+6.1f %5.0f%% %6.0f%% %6.0f%% %6s' % (r.rk, r.name[:24], r.pos + str(r.pos_rk), r.team, r.rating, r.value, r.ros_ppg, r.now_or,
              100 * (r.floor if r.floor == r.floor else 0), 100 * (r.ceiling if r.ceiling == r.ceiling else 0), 100 * r.upside_sh, '-' if r.missed != r.missed else '%d' % r.missed))
    top = D[D.rk <= 150].assign(mv=lambda x: x.rk_proj - x.rk)
    print('\nUP most vs the plain projection order (top 150): ' + ', '.join('%s %s (%d -> %d)' % (r.name, r.pos, r.rk_proj, r.rk) for r in top.sort_values('mv', ascending=False).head(12).itertuples()))
    both = D[D.fp.notna() & ((D.rk <= 100) | (D.fp <= 100))].assign(d=lambda x: x.fp - x.rk)
    c = D[(D.rk <= 150) & D.fp.notna()]
    print('\nconsensus (FantasyPros rest-of-season rank, benchmark only) matched %d of the top 150; rank corr %.3f' % (len(c), c[['rk', 'fp']].corr(method='spearman').iloc[0, 1]))
    print('MFF HIGHER than consensus: ' + ', '.join('%s %s (cons %d -> MFF %d)' % (r.name, r.pos, r.fp, r.rk) for r in both.sort_values('d', ascending=False).head(14).itertuples()))
    print('MFF LOWER than consensus: ' + ', '.join('%s %s (cons %d -> MFF %d)' % (r.name, r.pos, r.fp, r.rk) for r in both.sort_values('d').head(14).itertuples()))
    print('DOWN most vs the plain projection order: ' + ', '.join('%s %s (%d -> %d)' % (r.name, r.pos, r.rk_proj, r.rk) for r in top.sort_values('mv').head(12).itertuples()))


if __name__ == '__main__':
    sys.exit(main())
