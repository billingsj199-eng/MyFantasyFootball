#!/usr/bin/env python3
"""
research_value_atlas.py — every stat we have, one at a time, vs FUTURE dynasty
value (Jack 2026-10-09: "go through 1 by 1 with every stat we know and test it to
see if we have any correlation to future value whether falling or rising").

Pool: FFC dynasty ADP pool (1QB), VETERANS, valuation years 2017-23; stats from
the season before (Y-1), z-scored within position x season. Qualifiers WR/TE 150+
routes, RB 75+ carries, QB 200+ dropbacks (sources without volume: player must be
in the pool with 4+ games in Y-1).

Stat families (Y-1):
  rec.*   PFF premium receiving season (pro_hist rep_receiving, 2018-24), counts per game
  rush.*  PFF premium rushing season (RB + QB)
  pass.*  PFF premium passing season (QB)
  ngs*.*  NGS season (week 0) receiving / rushing / passing rate columns
  ctx.*   our season-to-date context features (ctx_features, last week of Y-1; 2019+)
  tm.*    the player's Y-1 team offense (PFF team_offense passing / rushing / overall)
  bio.*   age, experience, draft pick, RAS / 40 / weight, JM, Y-1 PPG vs replacement,
          games, breakout, injury-shortened, moved
  d.*     year-over-year change (Y-1 minus Y-2) of the PFF rate stats (both seasons
          qualifying at 2/3 of the volume bar)

Targets:
  MOVE    next-year market move beyond expectation: residual of log(m1) ~ log(m0) +
          pos + age-by-pos (m1 = next year's FFC rank, capped 250). coef < 0 = high
          stat -> price ROSE more than typical.
  FAIR3   log(realized 3yr VOR rank) ~ log(FAIR rank) + z   (< 0 = beat FAIR)
  FAIR5   same, 5yr+youth truth (Y <= 2021)
  MKT3    log(realized 3yr rank) ~ log(market rank) + z   (< 0 = beat the price)
Cluster-robust (player) t; seasons-with-same-sign; Benjamini-Hochberg q per target.
SURVIVORS (q < .10 and same sign in >= 70% of seasons) get a LOYO check:
  MOVE  held-out Spearman of predicted vs actual move, base vs base + stat
  FAIR  held-out position Spearman, FAIR vs FAIR + k*z (k fit in training years)
Quintile view: share of top-fifth vs bottom-fifth players whose price ROSE 20%+ /
FELL 25%+ the next year.
Output: _dyn_cache/value_atlas.csv + log.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, FORMATS, _norm_name, DATA_DIR, load_jm, season_rel  # noqa: E402
from backtest_value_score import build, LAST  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

CACHE = r'E:\MyFantasyFootball\pbp_cache'
PRO = os.path.join(CACHE, 'pff', 'pro_hist')
YRS = list(range(2017, 2024))
POSM = {'HB': 'RB', 'FB': 'RB'}
POS = ['QB', 'RB', 'WR', 'TE']
SKIP = {'playerId', 'jerseyNumber', 'franchiseId', 'draftSeason', 'eligibleSeason', 'gamesPlayed', 'playerGameCount',
        'teamId', 'season', 'week', 'player_jersey_number'}
RATE_KEYS = ('Rate', 'Percent', 'grades', 'yprr', 'ypa', 'avg', 'Oe', 'epa', 'Epa', 'Rating', 'accuracy', 'carryShare',
             'PerReception', 'PerPass', 'PerPlay', 'PerRush', 'PerCarry', 'PerAttempt', 'Pct', 'Share', 'adot', 'timeToThrow')


def is_rate(c):
    return any(k in c for k in RATE_KEYS) or c.endswith('Attempt') or c.endswith('Oe')


def _rows(path):
    d = json.load(open(path, encoding='utf-8'))
    cols = [c if isinstance(c, str) else c.get('key') for c in d['columns']]
    return [r if isinstance(r, dict) else dict(zip(cols, r)) for r in d['rows']]


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and not (isinstance(v, float) and math.isnan(v))


def load_pff():
    """{(key, season): {feat: value}} + volume fields; key = (norm name, pos)."""
    S = defaultdict(dict)
    team_of = {}
    for y in range(2016, 2025):
        for kind, pre in (('receiving', 'rec'), ('rushing', 'rush'), ('passing', 'pass')):
            p = os.path.join(PRO, f'rep_{kind}_{y}_season.json')
            if not os.path.exists(p):
                continue
            for r in _rows(p):
                pos = POSM.get(r.get('position'), r.get('position'))
                if pos not in POS:
                    continue
                k = (_norm_name(r['player']), pos)
                g = r.get('gamesPlayed') or r.get('playerGameCount') or 0
                f = S[(k, y)]
                tm = r.get('teamAbbreviation') or r.get('teamName') or r.get('team')
                if tm:
                    team_of.setdefault((k, y), tm)
                if kind == 'receiving':
                    f['_routes'] = r.get('routes') or 0
                elif kind == 'rushing':
                    f['_att'] = r.get('attempts') or 0
                else:
                    f['_db'] = r.get('dropbacks') or 0
                for c, v in r.items():
                    if c in SKIP or not _num(v):
                        continue
                    if is_rate(c):
                        f[f'{pre}.{c}'] = float(v)
                    elif g:
                        f[f'{pre}.{c}_pg'] = float(v) / g
                if kind == 'rushing' and r.get('attempts'):
                    a = r['attempts']
                    for c in ('zoneAttempts', 'gapAttempts', 'breakawayAttempts', 'explosive', 'firstDowns', 'avoidedTackles', 'eluRushMtf', 'touchdowns', 'fumbles'):
                        if _num(r.get(c)):
                            f[f'rush.{c}_per_att'] = r[c] / a
                if kind == 'receiving' and r.get('routes'):
                    rt = r['routes']
                    for c in ('targets', 'touchdowns', 'firstDowns', 'avoidedTackles', 'contestedTargets', 'drops', 'yardsAfterCatch'):
                        if _num(r.get(c)):
                            f[f'rec.{c}_per_route'] = r[c] / rt
                if kind == 'passing' and r.get('dropbacks'):
                    db = r['dropbacks']
                    for c in ('touchdowns', 'interceptions', 'bigTimeThrows', 'turnoverWorthyPlays', 'scrambles', 'sacks', 'yards', 'epa'):
                        if _num(r.get(c)):
                            f[f'pass.{c}_per_db'] = r[c] / db
    return S, team_of


def load_team():
    T = {}
    for y in range(2016, 2025):
        for kind in ('team_offense-passing', 'team_offense-rushing', 'team_offense-overall-success'):
            p = os.path.join(PRO, f'{kind}_{y}_season.json')
            if not os.path.exists(p):
                continue
            for r in _rows(p):
                f = T.setdefault((r.get('abbreviation'), y), {})
                for c, v in r.items():
                    if c in SKIP or c.endswith('Rank') or not _num(v):
                        continue
                    f[f'tm.{c}'] = float(v)
    return T


NGS_COUNT = {'receptions', 'targets', 'yards', 'rec_touchdowns', 'rush_attempts', 'rush_yards', 'expected_rush_yards', 'rush_yards_over_expected',
             'rush_touchdowns', 'attempts', 'pass_yards', 'pass_touchdowns', 'interceptions', 'completions'}


def load_ngs():
    S = defaultdict(dict)
    for kind, pre in (('receiving', 'ngsR'), ('rushing', 'ngsU'), ('passing', 'ngsP')):
        d = pd.read_parquet(os.path.join(CACHE, 'ngs', f'ngs_{kind}.parquet'))
        d = d[(d.week == 0) & (d.season_type == 'REG')]
        for r in d.to_dict('records'):
            pos = POSM.get(r['player_position'], r['player_position'])
            f = S[((_norm_name(r['player_display_name']), pos), int(r['season']))]
            for c, v in r.items():
                if c in SKIP or c in NGS_COUNT or c.startswith('player_') or c in ('season_type', 'team_abbr') or not _num(v):
                    continue
                f[f'{pre}.{c}'] = float(v)
    return S


CTX_COLS = ['tgt_sh', 'car_sh', 'rz_tgt_sh', 'rz_car_sh', 'gl_car_sh', 'ay_sh', 'xfp_pg', 'db_sh', 'att_pg', 'wopr', 'pts_over_xfp',
            'snap_std', 'tgt_trend', 'car_trend', 'snap_trend', 'ppg_over_clay', 'proe_std', 'plays_pg_std', 'new_hc', 'new_pc',
            'pc_seasons', 'pc_proe', 'pc_rb_tgt', 'pc_te_tgt', 'vac_tgt', 'vac_car', 'yprr_man', 'yprr_zone', 'ol_pb_full', 'ol_rb_full']


def load_ctx():
    S = {}
    c = pd.read_parquet(os.path.join(HERE, 'ctx_features.parquet'))
    for r in c.sort_values(['year', 'wk']).groupby(['name', 'pos', 'year']).tail(1).to_dict('records'):
        S[((_norm_name(r['name']), r['pos']), int(r['year']))] = {f'ctx.{k}': float(r[k]) for k in CTX_COLS if _num(r.get(k))}
        f = S[((_norm_name(r['name']), r['pos']), int(r['year']))]
        if 'ctx.yprr_man' in f and 'ctx.yprr_zone' in f:
            f['ctx.man_gap'] = f['ctx.yprr_man'] - f['ctx.yprr_zone']
    return S


def load_combine(w):
    s = open(os.path.join(DATA_DIR, 'combine_data.js'), encoding='utf-8').read()
    d, _ = json.JSONDecoder().raw_decode(s, s.index('{'))
    byname = defaultdict(list)
    for n, v in d.items():
        byname[_norm_name(n)].append(v)
    out = {}
    for key, P in w.players.items():
        cands = byname.get(key[0], [])
        dr = P.get('draft')
        if dr:
            cands = [c for c in cands if c.get('yr') and abs(c['yr'] - dr[0]) <= 1]
        if len(cands) == 1:
            out[key] = {f'bio.{k}': float(v) for k, v in cands[0].items() if k in ('ras', 'wt', 'forty', 'vert', 'broad', 'shuttle', 'cone', 'bench', 'hand', 'arm') and _num(v)}   # NOT pb / ap / hof (career outcomes = future leak)
    return out


def qual(pos, f, frac=1.0):
    if pos in ('WR', 'TE'):
        return (f.get('_routes') or 0) >= 150 * frac
    if pos == 'RB':
        return (f.get('_att') or 0) >= 75 * frac
    return (f.get('_db') or 0) >= 200 * frac


def cluster_t(X, y, groups):
    XtX = np.linalg.inv(X.T @ X)
    b = XtX @ X.T @ y
    e = y - X @ b
    meat = np.zeros((X.shape[1], X.shape[1]))
    gs = defaultdict(list)
    for i, g in enumerate(groups):
        gs[g].append(i)
    for idx in gs.values():
        s = X[idx].T @ e[idx]
        meat += np.outer(s, s)
    G = len(gs)
    V = XtX @ meat @ XtX * (G / max(G - 1, 1))
    return b, b / np.sqrt(np.maximum(np.diag(V), 1e-12))


def bh(ps):
    n = len(ps)
    order = np.argsort(ps)
    q = np.empty(n)
    prev = 1.0
    for rank, i in reversed(list(enumerate(order, 1))):
        prev = min(prev, ps[i] * n / rank)
        q[i] = prev
    return q


def pval(t):
    return math.erfc(abs(t) / math.sqrt(2))


def main():
    w = World(LAST)
    w._repl = w.repl(FORMATS['1qb'])
    pff, team_of = load_pff()
    team = load_team()
    ngs = load_ngs()
    ctx = load_ctx()
    comb = load_combine(w)
    jm = load_jm()
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = [x for x in build(True) if x['Y'] in YRS and not x['rookie']]
    m3_ship(recs, c)
    for x in recs:
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
    for Y in YRS:
        for i, x in enumerate(sorted([x for x in recs if x['Y'] == Y], key=lambda x: x['fz'])):
            x['f0'] = i + 1
    # expected market move: log m1 ~ log m0 + pos + age-by-pos
    def base_row(x):
        a = x['age'] - 25.0
        return [1.0, math.log(x['m0'])] + [1.0 if x['pos'] == p else 0.0 for p in POS[1:]] + [a * (x['pos'] == p) for p in POS] + [a * a * (x['pos'] == p) for p in POS]
    XB = np.array([base_row(x) for x in recs]); yB = np.array([math.log(x['m1']) for x in recs])
    bB = np.linalg.lstsq(XB, yB, rcond=None)[0]
    for x, r in zip(recs, yB - XB @ bB):
        x['mv'] = float(r)

    # features per record (season Y-1)
    for x in recs:
        k, Y, pos = x['key'], x['Y'], x['pos']
        F = {}
        f1 = pff.get((k, Y - 1), {})
        if qual(pos, f1):
            F.update({a: v for a, v in f1.items() if not a.startswith('_') and (pos != 'QB' or not a.startswith('rec.'))})
            f2 = pff.get((k, Y - 2), {})
            if qual(pos, f2, 2 / 3):
                for a, v in f1.items():
                    if not a.startswith('_') and not a.endswith('_pg') and a in f2:
                        F['d.' + a] = v - f2[a]
        g1, rel1 = season_rel(w, k, Y - 1)
        if g1 >= 4 or F:
            F.update(ngs.get((k, Y - 1), {}))
            F.update(ctx.get((k, Y - 1), {}))
            tm = team_of.get((k, Y - 1)) or ((w.players[k]['by'].get(Y - 1) or {}).get('tm') if k in w.players else None)
            F.update(team.get((tm, Y - 1), {}))
        P = w.players.get(k, {})
        dr = P.get('draft')
        F['bio.age'] = x['age']
        F['bio.exp'] = Y - dr[0] if dr else None
        F['bio.pick'] = dr[1] if dr and dr[1] else 260.0
        F.update(comb.get(k, {}))
        if k in jm:
            F['bio.jm'] = jm[k]
        if g1 >= 4:
            F['bio.rel_ppg'] = rel1
            g2, rel2 = season_rel(w, k, Y - 2)
            if g2 >= 4:
                F['bio.rel_change'] = rel1 - rel2
        F['bio.games'] = g1
        F['bio.breakout'] = x['breakout']; F['bio.injured'] = x['injured']; F['bio.moved'] = x['moved']
        x['F'] = {a: v for a, v in F.items() if v is not None and _num(v)}

    # z-score within pos x season
    for pos in POS:
        for Y in YRS:
            g = [x for x in recs if x['pos'] == pos and x['Y'] == Y]
            feats = set(a for x in g for a in x['F'])
            for a in feats:
                v = np.array([x['F'][a] for x in g if a in x['F']])
                if len(v) < 8 or v.std() == 0:
                    for x in g:
                        x['F'].pop(a, None)
                    continue
                mu, sd = v.mean(), v.std()
                for x in g:
                    if a in x['F']:
                        x.setdefault('Z', {})[a] = (x['F'][a] - mu) / sd
    for x in recs:
        x.setdefault('Z', {})

    if os.environ.get('ATLAS_DUMP'):
        import pickle
        pickle.dump([{k: x.get(k) for k in ('key', 'Y', 'pos', 'age', 'm0', 'm1', 's0', 'f0', 'fz', 'r_t3', 'r_lt', 'mv', 'Z')} for x in recs],
                    open(os.path.join(HERE, '_dyn_cache', 'value_atlas_recs.pkl'), 'wb'))
        print('dumped recs'); return
    TG = {'MOVE': ('mv', None), 'FAIR3': ('r_t3', 'f0'), 'FAIR5': ('r_lt', 'f0'), 'MKT3': ('r_t3', 'm0')}
    out = []
    for pos in POS:
        P = [x for x in recs if x['pos'] == pos]
        feats = sorted(set(a for x in P for a in x['Z']))
        for a in feats:
            row = {'pos': pos, 'stat': a}
            for tg, (yk, pk) in TG.items():
                g = [x for x in P if a in x['Z'] and x.get(yk) is not None]
                if len(g) < 40 or len(set(x['Y'] for x in g)) < 3:
                    continue
                z = np.array([x['Z'][a] for x in g])
                y = np.array([x[yk] if tg == 'MOVE' else math.log(x[yk]) for x in g])
                X = np.column_stack([np.ones(len(g)), z] if pk is None else [np.ones(len(g)), [math.log(x[pk]) for x in g], z])
                b, t = cluster_t(X, y, [x['key'] for x in g])
                j = X.shape[1] - 1
                same = 0; ns = 0
                for Y in sorted(set(x['Y'] for x in g)):
                    ii = [i for i, x in enumerate(g) if x['Y'] == Y]
                    if len(ii) < 12:
                        continue
                    bb = np.linalg.lstsq(X[ii], y[ii], rcond=None)[0][j]
                    ns += 1; same += (np.sign(bb) == np.sign(b[j]))
                row[tg] = {'n': len(g), 'b': float(b[j]), 't': float(t[j]), 'p': pval(t[j]), 'cons': f'{same}/{ns}', 'cfrac': same / max(ns, 1)}
            if len(row) > 2:
                out.append(row)
    # BH per target
    for tg in TG:
        rows = [r for r in out if tg in r]
        qs = bh(np.array([r[tg]['p'] for r in rows]))
        for r, q in zip(rows, qs):
            r[tg]['q'] = float(q)
    print(f'{len(out)} stat x position combos tested ({sum(1 for r in out for t in TG if t in r)} tests)\n')

    def surv(r, tg):
        s = r.get(tg)
        return s and s['q'] < 0.10 and s['cfrac'] >= 0.7

    for tg in TG:
        rows = sorted([r for r in out if tg in r], key=lambda r: r[tg]['p'])
        print(f'=== {tg}: top 25 by significance  ({"coef < 0 = price ROSE more than typical" if tg == "MOVE" else "coef < 0 = beat " + ("FAIR" if "FAIR" in tg else "the price")}) ===')
        print(f'{"pos":<4}{"stat":<38}{"n":>5}{"coef":>8}{"t":>7}{"q":>7}{"seasons":>9}')
        for r in rows[:25]:
            s = r[tg]
            print(f'{r["pos"]:<4}{r["stat"]:<38}{s["n"]:>5}{s["b"]:>+8.3f}{s["t"]:>+7.2f}{s["q"]:>7.3f}{s["cons"]:>9}{"  SURVIVES" if surv(r, tg) else ""}')
        print()

    # LOYO: survivors + near-misses (q < .35, same sign in 70%+ of seasons). The stat weight k
    # is fit INSIDE the training years by grid search on the shipped score form
    # (FAIR: fz + k*z, as _fairRbRec; MKT: log m0 + k*z), position-only Spearman.
    print('=== LOYO (k fit in training years; held-out position Spearman gain; SURVIVORS marked *) ===')
    KS = [i / 20 for i in range(-10, 11)]
    def score(x, a, k, pk):
        return (x['fz'] if pk == 'f0' else math.log(x['m0'])) + k * x['Z'].get(a, 0.0)
    def sp(g, a, k, pk, yk):
        return spearman([-score(x, a, k, pk) for x in g], [-x[yk] for x in g])
    loyo_ok = set()
    for r in out:
        for tg in TG:
            s_ = r.get(tg)
            if not s_ or s_['q'] >= 0.35 or s_['cfrac'] < 0.7 or s_['n'] < 50:
                continue
            pos, a = r['pos'], r['stat']
            P = [x for x in recs if x['pos'] == pos]
            yk, pk = TG[tg]
            gains, ks = [], []
            for Y in YRS:
                te = [x for x in P if x['Y'] == Y and x.get(yk) is not None]
                if sum(1 for x in te if a in x['Z']) < 12:
                    continue
                trY = [y for y in YRS if y != Y and sum(1 for x in P if x['Y'] == y and a in x['Z'] and x.get(yk) is not None) >= 12]
                if len(trY) < 2:
                    continue
                if tg == 'MOVE':
                    tr = [x for x in P if x['Y'] in trY and a in x['Z']]
                    k = np.polyfit([x['Z'][a] for x in tr], [x['mv'] for x in tr], 1)[0]
                    tz = [x for x in te if a in x['Z']]
                    gains.append(spearman([k * x['Z'][a] for x in tz], [x['mv'] for x in tz])); ks.append(k)
                    continue
                def trscore(k):
                    return np.mean([sp([x for x in P if x['Y'] == y and x.get(yk) is not None], a, k, pk, yk) for y in trY])
                k = max(KS, key=trscore)
                ks.append(k)
                gains.append(sp(te, a, k, pk, yk) - sp(te, a, 0.0, pk, yk))
            if len(gains) >= 3:
                wins = sum(1 for g in gains if g > 0)
                ok = np.mean(gains) > 0 and wins >= 0.7 * len(gains)
                if ok:
                    loyo_ok.add((pos, a, tg))
                lab = 'held-out Spearman(pred, move)' if tg == 'MOVE' else 'gain vs ' + ('FAIR' if pk == 'f0' else 'market')
                print(f'{"*" if ok else " "} {tg:<6}{pos:<4}{a:<38}{lab} {np.mean(gains):+.4f}  {wins}/{len(gains)}  k {min(ks):+.2f}..{max(ks):+.2f}  [{" ".join(f"{g:+.3f}" for g in gains)}]')
    # quintiles for survivors + notable MOVE stats
    print('\n=== Next-year price: top-fifth vs bottom-fifth of each surviving stat (vs expected for age + price: rose = rank 20%+ better, fell = 25%+ worse) ===')
    for r in out:
        if not any((r['pos'], r['stat'], tg) in loyo_ok or surv(r, tg) for tg in TG):
            continue
        g = [x for x in recs if x['pos'] == r['pos'] and r['stat'] in x['Z']]
        g.sort(key=lambda x: x['Z'][r['stat']])
        q = max(len(g) // 5, 1)
        def rf(s):
            return (100 * sum(1 for x in s if x['mv'] <= -0.223) / len(s), 100 * sum(1 for x in s if x['mv'] >= 0.223) / len(s))
        lo, hi = rf(g[:q]), rf(g[-q:])
        print(f'{r["pos"]:<4}{r["stat"]:<38} top fifth rose {hi[0]:4.0f}% fell {hi[1]:4.0f}%  | bottom fifth rose {lo[0]:4.0f}% fell {lo[1]:4.0f}%  (n {q} each)')
    flat = []
    for r in out:
        d = {'pos': r['pos'], 'stat': r['stat']}
        for tg in TG:
            if tg in r:
                for kk in ('n', 'b', 't', 'q', 'cons'):
                    d[f'{tg}_{kk}'] = r[tg][kk]
        flat.append(d)
    pd.DataFrame(flat).to_csv(os.path.join(HERE, '_dyn_cache', 'value_atlas.csv'), index=False)
    print('\nwrote _dyn_cache/value_atlas.csv')


if __name__ == '__main__':
    main()
