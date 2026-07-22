#!/usr/bin/env python3
"""
backtest_dynasty_model.py — Fit + validate the Dynasty JS Model valuation.

Design (agreed 2026-07-21): dynasty value = multi-year discounted PPG,
    V(player, Y) = sum_{k=0..H-1}  PPG_hat(Y+k) * gamma^k
where PPG_hat(Y+k) chains the (already backtested) one-year core forward:
    PPG_hat(Y+k) = w3g_base(Y) * age_mult(pos, age0+k) * prod_{j=0..k} expf(exp0+j)
- w3g_base: 50/30/20 x games-weighted per-game rates entering Y (frozen).
- age_mult: _JS_AGE_CURVES absolute per-age multiplier (QB exempt — validated).
- expf: per-year experience factor (young jump years 1-5, production-tiered
  vet fade 6+), compounded — each year's jump/fade is a persisting level shift.

Ground truth: realized discounted value over the truth window,
    T(player, Y) = sum_{k=0..TW-1} (fpts(Y+k)/17) * tgamma^k
with fpts/17 = per-slot weekly value (availability priced in) and 0 for
seasons not played (retirement/injury crater IS dynasty downside).

Fit: grid over model gamma x horizon H, per position, maximizing n-weighted
per-season Spearman vs T. Baseline 'oneyr' = the current dynasty behavior
(identical redraft board). Eligibility: pos QB/RB/WR/TE, gp>=1 in Y-1,
known age, and >=6 games in season Y OR any later window season (so pure
immediate-retirees don't dominate; they're unforecastable by any model).

Usage: python scripts/backtest_dynasty_model.py [--scoring half_ppr]
"""

import argparse
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_js_model import (  # noqa: E402
    SCORING, STAT_KEYS, POSITIONS, W3_WEIGHTS, TOP_N,
    load_js_const, season_rates, score_rates, blend_rates,
    age_in_season, spearman, _norm_name,
)

ROSTER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_nflverse_rosters')


def load_roster_birth_years():
    """(norm_name, pos) -> birth year from cached nflverse rosters.

    ALL_PLAYERS_DB carries birthYear for only ~10% of players; dynasty is
    ABOUT age, so we enrich from roster CSVs (2015-2025). Same-name+pos
    collisions across different people are rare enough to ignore for a
    backtest (the map just keeps the most recent sighting).
    """
    import csv
    out = {}
    if not os.path.isdir(ROSTER_DIR):
        return out
    for fn in sorted(os.listdir(ROSTER_DIR)):
        if not fn.startswith('roster_') or not fn.endswith('.csv'):
            continue
        with open(os.path.join(ROSTER_DIR, fn), encoding='utf-8') as f:
            for row in csv.DictReader(f):
                pos = row.get('position')
                bd = row.get('birth_date') or ''
                if pos not in POSITIONS or len(bd) < 4:
                    continue
                out[(_norm_name(row.get('full_name') or ''), pos)] = bd[:7]
    return out

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')

# Shipped experience factors (mirrors app.js _JS_EXP_JUMP / vet fade)
EXP_JUMP = {'QB': {1: 1.12, 2: 1.15, 3: 1.02},
            'RB': {1: 1.11},
            'WR': {1: 1.05, 2: 1.05, 4: 0.96, 5: 0.92},
            'TE': {2: 1.07, 3: 1.05, 4: 0.96, 5: 0.96}}
VET_FADE = {'RB': (0.91, 0.95), 'WR': (0.98, 0.89), 'TE': (0.91, 0.90)}
ELITE_THR = {'RB': 12, 'WR': 12, 'TE': 9}

TRUTH_WINDOW = 3       # years of realized value the target covers
TRUTH_GAMMA = 0.85     # discount inside the target


def exp_factor(pos, e, ppg_for_tier):
    if e >= 6 and pos in VET_FADE:
        return VET_FADE[pos][0 if ppg_for_tier >= ELITE_THR[pos] else 1]
    if 1 <= e <= 5:
        return EXP_JUMP.get(pos, {}).get(e, 1.0)
    return 1.0


def chained_ppg(base, pos, age0, exp0, k, age_curves, with_exp=True):
    """Projected PPG for year Y+k from a frozen base entering Y."""
    mult = 1.0
    if pos != 'QB' and age0 is not None:
        mult = (age_curves.get(pos) or {}).get(str(age0 + k), 1.0)
    v = base * mult
    if with_exp:
        f = 1.0
        for j in range(0, k + 1):
            f *= exp_factor(pos, exp0 + j, base * f)
        v *= f
    return v


def build_rows(db, years, scoring, age_curves, birth_map):
    rows = []
    for p in db:
        pos = p.get('pos')
        if pos not in POSITIONS:
            continue
        career = sorted((s for s in (p.get('career') or []) if s.get('yr')),
                        key=lambda s: s['yr'])
        by_year = {s['yr']: s for s in career}
        birth = p.get('birthYear') or birth_map.get((_norm_name(p['name']), pos))
        for y in years:
            prev = by_year.get(y - 1)
            if not prev or (prev.get('gp') or 0) < 1:
                continue
            age0 = age_in_season(birth, y)
            if age0 is None:
                continue
            # NO future-window eligibility gate: retirements and cliff years
            # are exactly the outcomes a dynasty valuation must price, so
            # they stay in the pool with truth contributions of 0.
            # frozen w3g base entering Y
            rl, wgl = [], []
            for back, w in zip(range(1, 4), W3_WEIGHTS):
                s = by_year.get(y - back)
                r = season_rates(s) if s else None
                if r:
                    rl.append(r)
                    wgl.append(w * min(s.get('gp') or 0, 17))
            if not rl:
                continue
            base = score_rates(blend_rates(rl, wgl), scoring)
            exp0 = y - (p.get('debut') or y)
            # realized discounted truth
            truth = 0.0
            for k in range(TRUTH_WINDOW):
                s = by_year.get(y + k)
                if s and (s.get('gp') or 0) >= 1:
                    fpts = score_rates(season_rates(s), scoring) * min(s['gp'], 17)
                    truth += (fpts / 17.0) * (TRUTH_GAMMA ** k)
            rows.append({'name': p['name'], 'pos': pos, 'year': y,
                         'base': base, 'age0': age0, 'exp0': exp0,
                         'truth': truth})
    return rows


def value(row, gamma, H, age_curves, with_exp=True):
    return sum(chained_ppg(row['base'], row['pos'], row['age0'], row['exp0'],
                           k, age_curves, with_exp) * (gamma ** k)
               for k in range(H))


def eval_model(rows, pred_fn, pos):
    """n-weighted per-season Spearman + top-N hit for one position."""
    sp_num = sp_den = hit_num = hit_den = 0.0
    for y in sorted({r['year'] for r in rows}):
        yr = [r for r in rows if r['year'] == y and r['pos'] == pos]
        if len(yr) < 10:
            continue
        pred = [pred_fn(r) for r in yr]
        act = [r['truth'] for r in yr]
        sp = spearman(pred, act)
        if sp is not None:
            sp_num += sp * len(yr)
            sp_den += len(yr)
        n = min(TOP_N[pos], len(yr))
        tp = set(sorted(range(len(yr)), key=lambda i: -pred[i])[:n])
        ta = set(sorted(range(len(yr)), key=lambda i: -act[i])[:n])
        hit_num += len(tp & ta)
        hit_den += n
    return (sp_num / sp_den if sp_den else None,
            hit_num / hit_den if hit_den else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scoring', default='half_ppr', choices=sorted(SCORING))
    args = ap.parse_args()
    scoring = SCORING[args.scoring]

    print('Loading data...')
    db = load_js_const(os.path.join(DATA_DIR, 'all_players.js'), 'ALL_PLAYERS_DB')
    age_curves = load_js_const(os.path.join(DATA_DIR, 'js_model_data.js'), '_JS_AGE_CURVES')
    birth_map = load_roster_birth_years()
    print(f'roster birth-year map: {len(birth_map)} (name,pos) entries')
    max_yr = max((s.get('yr') or 0) for p in db for s in (p.get('career') or []))
    years = list(range(2018, max_yr - TRUTH_WINDOW + 2))
    print(f'{len(db)} players, latest season {max_yr}, eval years {years[0]}-{years[-1]}, '
          f'truth = {TRUTH_WINDOW}yr realized fpts/17 @ {TRUTH_GAMMA} discount')

    all_rows = build_rows(db, years, scoring, age_curves, birth_map)
    # Dynasty boards only rank rosterable players; a floor on the KNOWN
    # (entering-Y) base keeps the pool honest while cutting deep-roster noise.
    rows = [r for r in all_rows if r['base'] >= 6.0]
    by_pos = {pos: sum(1 for r in rows if r['pos'] == pos) for pos in POSITIONS}
    print(f'{len(all_rows)} rows total; relevant pool (base>=6 PPG): {len(rows)} — ' +
          ', '.join(f'{p} {n}' for p, n in by_pos.items()))

    # Baseline: current dynasty behavior = one-year redraft projection
    print(f'\n{"pos":<4}{"model":<22}{"Spearman":>9}{"topN":>7}')
    results = defaultdict(list)
    for pos in POSITIONS:
        sp, hit = eval_model(rows, lambda r: value(r, 1.0, 1, age_curves), pos)
        results[pos].append(('oneyr (current)', sp, hit))
        sp, hit = eval_model(rows, lambda r: value(r, 0.85, 4, age_curves, with_exp=False), pos)
        results[pos].append(('chain g.85 H4 no-exp', sp, hit))
        for H in (2, 3, 4, 5):
            for g in (0.7, 0.75, 0.8, 0.85, 0.9, 0.95):
                sp, hit = eval_model(
                    rows, lambda r, g=g, H=H: value(r, g, H, age_curves), pos)
                results[pos].append((f'chain g{g:.2f} H{H}', sp, hit))
        best = max(results[pos], key=lambda t: t[1] or -1)
        for name, sp, hit in results[pos]:
            if name.startswith('oneyr') or name == best[0] or 'no-exp' in name:
                star = ' <-- best' if name == best[0] else ''
                print(f'{pos:<4}{name:<22}{sp:>9.3f}{hit*100:>6.0f}%{star}')

    # Full grid dump for the record
    print('\n=== full grid (Spearman) ===')
    header = '     ' + ''.join(f'{f"H{H}":>8}' for H in (2, 3, 4, 5))
    for pos in POSITIONS:
        print(f'\n{pos}  (oneyr = '
              f'{next(sp for n, sp, _ in results[pos] if n.startswith("oneyr")):.3f})')
        print(header)
        for g in (0.7, 0.75, 0.8, 0.85, 0.9, 0.95):
            cells = []
            for H in (2, 3, 4, 5):
                sp = next(s for n, s, _ in results[pos]
                          if n == f'chain g{g:.2f} H{H}')
                cells.append(f'{sp:>8.3f}')
            print(f'g{g:.2f}' + ''.join(cells))


if __name__ == '__main__':
    sys.exit(main())
