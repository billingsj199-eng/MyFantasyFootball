#!/usr/bin/env python3
"""
analyze_model_vs_clay.py — player-level autopsy: where the JS Model beat
Clay's projections and where it lost, on the 2019-2025 Clay-intersection pool.

Two comparisons:
  shipped vs clay — the model's OWN core (no Clay inside) head-to-head vs Clay.
    This is the "does the model know anything Clay doesn't" question.
  full vs clay    — the deployed ensemble (core + divergence-weighted Clay
    blend) vs Clay alone. This is what users actually get.

Output: per-player aggregates (players with >= MIN_N seasons), biggest single
season wins/losses, and win-rate patterns by experience / age / position.

Usage: python scripts/analyze_model_vs_clay.py [--min-n 3] [--scoring half_ppr]
"""

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_js_model import (  # noqa: E402
    SCORING, load_js_const, build_predictions, age_in_season, _norm_name,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-n', type=int, default=3)
    ap.add_argument('--scoring', default='half_ppr', choices=sorted(SCORING))
    args = ap.parse_args()
    scoring = SCORING[args.scoring]

    db = load_js_const(os.path.join(DATA_DIR, 'all_players.js'), 'ALL_PLAYERS_DB')
    age_curves = load_js_const(os.path.join(DATA_DIR, 'js_model_data.js'), '_JS_AGE_CURVES')
    with open(os.path.join(DATA_DIR, 'clay_history.json'), encoding='utf-8') as f:
        clay_hist = {int(y): {_norm_name(n): v for n, v in ps.items()}
                     for y, ps in json.load(f).items()}

    years = sorted(clay_hist)
    rows = [r for r in build_predictions(db, years, scoring, age_curves, clay_hist)
            if 'clay' in r['preds'] and 'full' in r['preds']]
    print(f'{len(rows)} player-seasons with both model + Clay predictions '
          f'({years[0]}-{years[-1]}, {args.scoring})')

    meta = {p['name']: p for p in db}

    # per-row deltas: positive = model closer to actual than Clay
    for r in rows:
        a = r['actual']
        r['d_shipped'] = abs(r['preds']['clay'] - a) - abs(r['preds']['shipped'] - a)
        r['d_full'] = abs(r['preds']['clay'] - a) - abs(r['preds']['full'] - a)

    # ---- per-player aggregates (pure core vs Clay) ----
    per = defaultdict(list)
    for r in rows:
        per[(r['name'], r['pos'])].append(r)
    agg = []
    for (name, pos), rs in per.items():
        if len(rs) < args.min_n:
            continue
        agg.append({
            'name': name, 'pos': pos, 'n': len(rs),
            'd_shipped': sum(r['d_shipped'] for r in rs) / len(rs),
            'd_full': sum(r['d_full'] for r in rs) / len(rs),
            'yrs': ','.join(str(r['year']) for r in sorted(rs, key=lambda x: x['year'])),
        })

    def show(title, items, key):
        print(f'\n=== {title} ===')
        print(f'  {"player":<24}{"pos":<5}{"n":>2}  {"avg edge (ppg)":>14}   seasons')
        for a in items:
            print(f'  {a["name"]:<24}{a["pos"]:<5}{a["n"]:>2}  {a[key]:>+14.2f}   {a["yrs"]}')

    agg.sort(key=lambda a: -a['d_shipped'])
    show(f'MODEL BEAT CLAY the most (pure core, players with >={args.min_n} seasons)',
         agg[:15], 'd_shipped')
    show('CLAY BEAT THE MODEL the most (pure core)', agg[-15:][::-1], 'd_shipped')

    agg.sort(key=lambda a: -a['d_full'])
    show('DEPLOYED ENSEMBLE beat Clay the most', agg[:10], 'd_full')
    show('Clay beat the DEPLOYED ENSEMBLE the most', agg[-10:][::-1], 'd_full')

    # ---- biggest single-season swings (pure core) ----
    rows.sort(key=lambda r: -r['d_shipped'])

    def show_rows(title, rr):
        print(f'\n=== {title} ===')
        print(f'  {"player":<22}{"pos":<4}{"yr":<6}{"actual":>7}{"clay":>7}{"model":>7}{"edge":>7}')
        for r in rr:
            print(f'  {r["name"]:<22}{r["pos"]:<4}{r["year"]:<6}{r["actual"]:>7.1f}'
                  f'{r["preds"]["clay"]:>7.1f}{r["preds"]["shipped"]:>7.1f}{r["d_shipped"]:>+7.1f}')

    show_rows('Biggest single-season MODEL wins', rows[:12])
    show_rows('Biggest single-season CLAY wins', rows[-12:][::-1])

    # ---- pattern analysis: who wins where ----
    def bucket_stats(bucket_fn, label):
        b = defaultdict(lambda: [0, 0, 0.0])  # wins, total, sum-delta
        for r in rows:
            k = bucket_fn(r)
            if k is None:
                continue
            b[k][1] += 1
            b[k][2] += r['d_shipped']
            if r['d_shipped'] > 0:
                b[k][0] += 1
        print(f'\n=== Model-vs-Clay win rate by {label} (pure core; >50% = model wins) ===')
        for k in sorted(b, key=str):
            w, t, s = b[k]
            print(f'  {str(k):<12} {w}/{t} = {w/t*100:.0f}%   avg edge {s/t:+.2f} ppg')

    debut = {p['name']: p.get('debut') for p in db}
    bucket_stats(lambda r: r['pos'], 'position')
    bucket_stats(lambda r: (lambda e: '1-2' if e <= 2 else '3-5' if e <= 5 else '6+')
                 (r['year'] - debut[r['name']]) if debut.get(r['name']) else None,
                 'years of experience')
    bucket_stats(lambda r: (lambda a: '<=24' if a <= 24 else '25-28' if a <= 28 else '29+')
                 (age_in_season(meta[r['name']].get('birthYear'), r['year']))
                 if meta.get(r['name'], {}).get('birthYear') else None,
                 'age (where known)')


if __name__ == '__main__':
    sys.exit(main())
