#!/usr/bin/env python3
"""
research_efficiency_value.py — do efficiency / usage stats improve a player's
long-term dynasty outlook beyond his price, the Dynasty SIM and FAIR?
(Jack 2026-10-09: "look through and test any stats that can improve a players
long term outlook like yprr or other efficiency stats")

Pool: FFC dynasty ADP pool, valuation years 2020-23 (1QB PPR), VETERANS with a
qualifying prior season (stats from Y-1; WR/TE 150+ routes, RB 75+ carries, QB
200+ attempts). Shipped conditional-JM sim + FAIR (0.5 M3 + 0.3 sim + 0.5 mkt).
Stats (season Y-1; 2-yr route-weighted for YPRR / TPRR where Y-2 exists):
  WR/TE  PFF: YPRR, targets per route, route rate, route grade, offense grade,
         aDOT, YAC/rec, contested-catch %, drop %, first downs per route, slot
         rate; NGS: separation, YAC over expected, air-yards share; ctx: target
         share, WOPR, xFP/g, points over xFP/g
  RB     PFF: yards after contact / att, elusive rating, breakaway %, YPC, run
         grade, offense grade, RB YPRR, targets per route; NGS: rush yards over
         expected / att, % vs 8+ box; ctx: carry share, target share, xFP/g,
         points over xFP/g
  QB     NGS: CPOE, aggressiveness, time to throw, air-yards differential; ctx:
         points over xFP/g
1  BEYOND: log(realized rank) ~ log(predicted rank) + z(stat), predicted = market
   / sim / FAIR; truths 3yr (Y..Y+2) and 5yr+youth (Y <= 2021). Player
   bootstrap CI. coef < 0 = high-stat players beat that rank.
2  LOYO: within each training set pick each position's stats whose BEYOND-FAIR
   3yr coef is < 0 with |t| >= 2, fit FAIR + those stats, score the held-out year
   (whole pool) vs FAIR. Stats are chosen inside the fold — no selection leakage.
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
from dyn_common import World, FORMATS, _norm_name  # noqa: E402
from backtest_value_score import build, LAST  # noqa: E402
from backtest_fair_retune_jm import m3_ship  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

CACHE = r'E:\MyFantasyFootball\pbp_cache'
YRS = [2020, 2021, 2022, 2023]
POS_MAP = {'HB': 'RB', 'FB': 'RB'}


def load_stats():
    S = defaultdict(dict)   # (key, season) -> {stat: value}
    for y in range(2019, 2024):
        rc = pd.read_csv(os.path.join(CACHE, 'pff', f'pff_receiving_{y}.csv'))
        for r in rc.to_dict('records'):
            pos = POS_MAP.get(r['position'], r['position'])
            if pos not in ('WR', 'TE', 'RB'):
                continue
            k = (_norm_name(r['player']), pos)
            rt = r.get('routes') or 0
            f = S[(k, y)]
            f['_routes'] = rt
            if rt:
                f.update({'yprr': r['yprr'], 'tprr': (r['targets'] or 0) / rt, 'route_rate': r['route_rate'],
                          'grade_route': r['grades_pass_route'], 'grade_off': r['grades_offense'], 'adot': r['avg_depth_of_target'],
                          'yac_rec': r['yards_after_catch_per_reception'], 'contested': r['contested_catch_rate'],
                          'drop': r['drop_rate'], 'fd_route': (r['first_downs'] or 0) / rt, 'slot': r['slot_rate'],
                          '_rec_yards': r['yards'] or 0, '_targets': r['targets'] or 0,
                          'juke_rec': (r.get('avoided_tackles') or 0) / r['receptions'] if r.get('receptions') else None})
        ru = pd.read_csv(os.path.join(CACHE, 'pff', f'pff_rushing_{y}.csv'))
        for r in ru.to_dict('records'):
            pos = POS_MAP.get(r['position'], r['position'])
            if pos != 'RB':
                continue
            k = (_norm_name(r['player']), 'RB')
            f = S[(k, y)]
            f['_att'] = r['attempts'] or 0
            rt = r.get('routes') or 0
            tch = (r['attempts'] or 0) + (r.get('receptions') or 0)
            f['juke'] = (r.get('avoided_tackles') or 0) / tch if tch else None   # juke rate: avoided tackles per touch (Player Profiler style)
            f.update({'yco': r['yco_attempt'], 'elusive': r['elusive_rating'], 'breakaway': r['breakaway_percent'], 'ypc': r['ypa'],
                      'grade_run': r['grades_run'], 'grade_off_rb': r['grades_offense'], 'rb_yprr': r['yprr'],
                      'rb_tprr': (r['targets'] or 0) / rt if rt else None})
        for kind in ('receiving', 'rushing', 'passing'):
            n = pd.read_csv(os.path.join(CACHE, 'ngs', f'ngs_{y}_{kind}.csv.gz'))
            n = n[(n.week == 0) & (n.season_type == 'REG')]
            for r in n.to_dict('records'):
                pos = POS_MAP.get(r['player_position'], r['player_position'])
                k = (_norm_name(r['player_display_name']), pos)
                f = S[(k, y)]
                if kind == 'receiving':
                    f.update({'separation': r['avg_separation'], 'yac_oe': r['avg_yac_above_expectation'], 'ay_share_ngs': r['percent_share_of_intended_air_yards']})
                elif kind == 'rushing':
                    f.update({'ryoe_att': r['rush_yards_over_expected_per_att'], 'box8': r['percent_attempts_gte_eight_defenders']})
                else:
                    f['_qb_att'] = r['attempts']
                    f.update({'cpoe': r['completion_percentage_above_expectation'], 'aggr': r['aggressiveness'], 'ttt': r['avg_time_to_throw'],
                              'ay_diff': r['avg_air_yards_differential']})
    ctx = pd.read_parquet(os.path.join(HERE, 'ctx_features.parquet'))
    ctx['key'] = [(_norm_name(n), p) for n, p in zip(ctx['name'], ctx['pos'])]
    for r in ctx.sort_values(['year', 'wk']).groupby(['name', 'pos', 'year']).tail(1).to_dict('records'):
        f = S[(r['key'], int(r['year']))]
        f.update({'tgt_sh': r['tgt_sh'], 'car_sh': r['car_sh'], 'wopr': r['wopr'], 'xfp_pg': r['xfp_pg'], 'poxfp': r['pts_over_xfp'],
                  # man vs zone (PFF YPRR by coverage, ctx_features, shrunk): beating man = route-running 'win' proxy
                  'yprr_man': r.get('yprr_man'), 'yprr_zone': r.get('yprr_zone'),
                  'man_gap': (r['yprr_man'] - r['yprr_zone']) if (r.get('yprr_man') is not None and r.get('yprr_zone') is not None) else None})
    # 2-yr route-weighted YPRR / TPRR
    for (k, y), f in list(S.items()):
        p = S.get((k, y - 1))
        if f.get('_routes') and p and p.get('_routes'):
            R = f['_routes'] + p['_routes']
            f['yprr2'] = (f['_rec_yards'] + p.get('_rec_yards', 0)) / R
            f['tprr2'] = (f['_targets'] + p.get('_targets', 0)) / R
    return S


STATS = {
    'WR': ['yprr_man', 'yprr_zone', 'man_gap', 'juke_rec', 'yprr', 'yprr2', 'tprr', 'tprr2', 'route_rate', 'grade_route', 'grade_off', 'adot', 'yac_rec', 'contested', 'drop', 'fd_route', 'slot',
           'separation', 'yac_oe', 'ay_share_ngs', 'tgt_sh', 'wopr', 'xfp_pg', 'poxfp'],
    'RB': ['juke', 'yco', 'elusive', 'breakaway', 'ypc', 'grade_run', 'grade_off_rb', 'rb_yprr', 'rb_tprr', 'ryoe_att', 'box8', 'car_sh', 'tgt_sh', 'xfp_pg', 'poxfp'],
    'QB': ['cpoe', 'aggr', 'ttt', 'ay_diff', 'poxfp'],
}
STATS['TE'] = STATS['WR']


def qualifies(pos, f):
    if pos in ('WR', 'TE'):
        return (f.get('_routes') or 0) >= 150
    if pos == 'RB':
        return (f.get('_att') or 0) >= 75
    return (f.get('_qb_att') or 0) >= 200


def main():
    S = load_stats()
    c = json.load(open(os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')))['coef']
    recs = [x for x in build(True) if x['Y'] in YRS and not x['rookie']]
    m3_ship(recs, c)
    for x in recs:
        x['fz'] = 0.5 * x['m3'] + 0.3 * math.log(x['s0']) + 0.5 * math.log(x['m0'])
        f = S.get((x['key'], x['Y'] - 1), {})
        x['st'] = f if qualifies(x['pos'], f) else {}
    for Y in YRS:
        ys = [x for x in build.__globals__['build'].__defaults__ or []] if False else [x for x in recs if x['Y'] == Y]
        for i, x in enumerate(sorted(ys, key=lambda x: x['fz'])):
            x['f0'] = i + 1
    rng = np.random.default_rng(5)
    results = {}
    for pos, stats in STATS.items():
        P = [x for x in recs if x['pos'] == pos and x['st']]
        print(f'\n=== {pos}: {len(P)} veteran player-seasons 2020-23 with a qualifying prior season ===')
        print(f'{"stat":<14}{"n":>4}{"raw 3y":>8}{"priced":>8}{"beyond MKT 3y":>16}{"beyond SIM 3y":>16}{"beyond FAIR 3y":>22}{"beyond FAIR 5y+":>17}')
        for st in stats:
            g = [x for x in P if x['st'].get(st) is not None and not (isinstance(x['st'][st], float) and math.isnan(x['st'][st])) and x.get('r_t3')]
            if len(g) < 25:
                continue
            v = np.array([x['st'][st] for x in g], float); z = (v - v.mean()) / (v.std() or 1)
            t3 = np.array([math.log(x['r_t3']) for x in g])
            raw = spearman(list(z), list(-t3)); pri = spearman(list(z), [-math.log(x['m0']) for x in g])
            keys = np.array([hash(x['key']) for x in g]); uk = np.unique(keys); byk = {k: np.where(keys == k)[0] for k in uk}
            cells = []
            for pk, tk in (('m0', 'r_t3'), ('s0', 'r_t3'), ('f0', 'r_t3'), ('f0', 'r_lt')):
                idx = [i for i, x in enumerate(g) if x.get(tk)]
                if len(idx) < 20:
                    cells.append('—'); continue
                y_ = np.array([math.log(g[i][tk]) for i in idx]); pr = np.array([math.log(g[i][pk]) for i in idx]); zz = z[idx]
                X = np.column_stack([np.ones(len(idx)), pr, zz])
                b = np.linalg.lstsq(X, y_, rcond=None)[0][2]
                pos_of = {i: j for j, i in enumerate(idx)}
                bs = []
                for _ in range(300):
                    ii = [pos_of[i] for k_ in rng.choice(uk, len(uk)) for i in byk[k_] if i in pos_of]
                    if len(ii) > 10:
                        bs.append(np.linalg.lstsq(X[ii], y_[ii], rcond=None)[0][2])
                lo, hi = np.percentile(bs, [2.5, 97.5])
                sig = lo > 0 or hi < 0
                cells.append(f'{b:+.3f}{"*" if sig else " "}[{lo:+.2f},{hi:+.2f}]' if pk == 'f0' and tk == 'r_t3' else f'{b:+.3f}{"*" if sig else " "}')
                results[(pos, st, pk, tk)] = (b, lo, hi)
            print(f'{st:<14}{len(g):>4}{raw:>+8.2f}{pri:>+8.2f}{cells[0]:>16}{cells[1]:>16}{cells[2]:>22}{cells[3]:>17}')
    print('\n   coef per 1 SD of the stat in log(realized rank) ~ log(predicted rank) + stat: < 0 = high-stat players BEAT that rank (* = 95% CI excludes 0).'
          '\n   raw = Spearman with the realized 3yr rank; priced = Spearman with the market rank.')

    # LOYO: FAIR + in-fold selected stats, whole pool
    print('\n=== LOYO: FAIR + stats selected inside each training fold (beyond-FAIR 3yr coef < 0, |t| >= 2) ===')
    allrecs = recs
    d3, d5, picks = [], [], []
    for Y in YRS:
        tr = [x for x in allrecs if x['Y'] != Y]; te = [x for x in allrecs if x['Y'] == Y]
        chosen = {}
        for pos, stats in STATS.items():
            for st in stats:
                g = [x for x in tr if x['pos'] == pos and x['st'].get(st) is not None and not (isinstance(x['st'][st], float) and math.isnan(x['st'][st])) and x.get('r_t3')]
                if len(g) < 25:
                    continue
                v = np.array([x['st'][st] for x in g], float); mu, sd = v.mean(), v.std() or 1
                X = np.column_stack([np.ones(len(g)), [math.log(x['f0']) for x in g], (v - mu) / sd])
                yv = np.array([math.log(x['r_t3']) for x in g])
                b, res = np.linalg.lstsq(X, yv, rcond=None)[:2]
                resid = yv - X @ b
                se = math.sqrt((resid @ resid) / max(len(g) - 3, 1) * np.linalg.inv(X.T @ X)[2, 2])
                if b[2] < 0 and abs(b[2] / se) >= 2:
                    chosen.setdefault(pos, []).append((st, b[2], mu, sd))
        picks.append({p: [s[0] for s in v] for p, v in chosen.items()})
        def score(x):
            s = math.log(x['f0'])
            for st, b, mu, sd in chosen.get(x['pos'], []):
                val = x['st'].get(st)
                if val is not None and not (isinstance(val, float) and math.isnan(val)):
                    s += b * (val - mu) / sd / max(len(chosen[x['pos']]), 1)   # average the picked stats' tilts
            return s
        for tk, dd in (('r_t3', d3), ('r_lt', d5)):
            xs = [x for x in te if x.get(tk)]
            if len(xs) >= 20:
                dd.append(spearman([-score(x) for x in xs], [-x[tk] for x in xs]) - spearman([-math.log(x['f0']) for x in xs], [-x[tk] for x in xs]))
    print(f'   picks per fold: {picks}')
    print(f'   held-out change vs FAIR: 3yr {np.mean(d3):+.4f} (wins {sum(v > 1e-9 for v in d3)}/{len(d3)}), 5yr+youth {np.mean(d5) if d5 else float("nan"):+.4f} (wins {sum(v > 1e-9 for v in d5)}/{len(d5)})')


if __name__ == '__main__':
    main()
