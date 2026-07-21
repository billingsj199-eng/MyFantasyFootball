#!/usr/bin/env python3
"""
backtest_js_model.py — Backtest the JS Model's core projection engine.

The JS Model (app.js "JS MODEL ENGINE") projects season PPG from historical
per-game component rates (data/js_model_data.js) + age curves, then layers
injury discounts, JM blending, and a Mike Clay blend on top. The Clay/injury
layers can't be reconstructed for past seasons, so this backtests the CORE
PRIOR — the part js_model_data.js + _JS_AGE_CURVES are responsible for —
against naive baselines, using ALL_PLAYERS_DB (data/all_players.js) as both
input (seasons < Y) and ground truth (season Y).

Models compared (all predict half-PPR PPG for season Y using only seasons < Y):
  prior       PPG of season Y-1 (naive baseline)
  w3          per-game component rates, 50/30/20 weighted over Y-1..Y-3
  career      per-game component rates averaged over the ENTIRE career < Y
              (this is what js_model_data.js appears to be)
  career_age  career x _JS_AGE_CURVES multiplier for age at season Y
  w3_age      w3 x age multiplier

Eligibility per (player, Y): pos in QB/RB/WR/TE, season Y with gp >= 6,
and season Y-1 with gp >= 1 (so every model is scored on the same set).
Rookies are excluded — the rookie-template path is a separate exercise.

Metrics: MAE / RMSE of PPG (pooled), Spearman rank correlation and top-N
hit rate computed within each (pos, season) then n-weighted averaged.

Also runs a diagnostic inferring which weighting js_model_data.js was built
with, by comparing its stored rates to career-avg vs recency-weighted rates
recomputed from ALL_PLAYERS_DB.

Usage:  python scripts/backtest_js_model.py [--years 2018 2025] [--scoring half_ppr]
"""

import argparse
import json
import math
import os
import re
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), 'data')

SCORING = {
    'half_ppr': {'py': 0.04, 'ptd': 4, 'int': -1, 'ry': 0.1, 'rtd': 6,
                 'rc': 0.5, 'rcy': 0.1, 'rctd': 6, 'fl': -2},
    'full_ppr': {'py': 0.04, 'ptd': 4, 'int': -1, 'ry': 0.1, 'rtd': 6,
                 'rc': 1.0, 'rcy': 0.1, 'rctd': 6, 'fl': -2},
    'non_ppr':  {'py': 0.04, 'ptd': 4, 'int': -1, 'ry': 0.1, 'rtd': 6,
                 'rc': 0.0, 'rcy': 0.1, 'rctd': 6, 'fl': -2},
}
STAT_KEYS = ['py', 'ptd', 'int', 'ry', 'rtd', 'rc', 'rcy', 'rctd', 'fl']
POSITIONS = ['QB', 'RB', 'WR', 'TE']
TOP_N = {'QB': 12, 'RB': 24, 'WR': 24, 'TE': 12}
W3_WEIGHTS = [0.5, 0.3, 0.2]  # Y-1, Y-2, Y-3


def load_js_const(path, const_name):
    """Parse `const NAME = <json>;` (possibly multi-const file) into Python."""
    with open(path, encoding='utf-8') as f:
        text = f.read()
    m = re.search(r'const\s+' + re.escape(const_name) + r'\s*=\s*', text)
    if not m:
        raise ValueError(f'{const_name} not found in {path}')
    start = m.end()
    # Find the matching end: scan to the semicolon/newline that closes the literal
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in '[{':
            depth += 1
        elif c in ']}':
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError(f'Unbalanced literal for {const_name} in {path}')


def season_rates(season):
    """Per-game component rates for one season row (needs gp >= 1)."""
    gp = season.get('gp') or 0
    if gp < 1:
        return None
    return {k: (season.get(k) or 0) / gp for k in STAT_KEYS}


def score_rates(rates, scoring):
    return sum(rates.get(k, 0) * scoring[k] for k in STAT_KEYS)


def blend_rates(rate_list, weights):
    total_w = sum(weights)
    return {k: sum(r[k] * w for r, w in zip(rate_list, weights)) / total_w
            for k in STAT_KEYS}


def age_in_season(birth, year):
    """Age as of ~Sep 1 of `year`. birth is 'YYYY-MM-DD' or 'YYYY' or None."""
    if not birth:
        return None
    m = re.match(r'(\d{4})(?:-(\d{2}))?', str(birth))
    if not m:
        return None
    by = int(m.group(1))
    bm = int(m.group(2) or 6)
    return year - by - (1 if bm > 8 else 0)


def rankdata(values):
    """Average ranks (1-based), ties averaged."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(a, b):
    if len(a) < 3:
        return None
    ra, rb = rankdata(a), rankdata(b)
    n = len(a)
    ma = sum(ra) / n
    mb = sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    if va == 0 or vb == 0:
        return None
    return cov / (va * vb)


def build_predictions(db, years, scoring, age_curves):
    """Returns rows: {name,pos,year,actual,preds:{model:ppg}}"""
    rows = []
    for p in db:
        pos = p.get('pos')
        if pos not in POSITIONS:
            continue
        career = sorted((s for s in (p.get('career') or []) if s.get('yr')),
                        key=lambda s: s['yr'])
        by_year = {s['yr']: s for s in career}
        for y in years:
            tgt = by_year.get(y)
            prev = by_year.get(y - 1)
            if not tgt or (tgt.get('gp') or 0) < 6:
                continue
            if not prev or (prev.get('gp') or 0) < 1:
                continue
            actual_rates = season_rates(tgt)
            actual = score_rates(actual_rates, scoring)

            preds = {}
            # prior: last season PPG
            preds['prior'] = score_rates(season_rates(prev), scoring)

            # w3: 50/30/20 over available of Y-1..Y-3
            # w3g: same, but each season's weight also scaled by games played
            # (an 8-game injury season shouldn't dominate two healthy 17-game
            # seasons just because it's the most recent)
            rl, wl, wgl = [], [], []
            for back, w in zip(range(1, 4), W3_WEIGHTS):
                s = by_year.get(y - back)
                r = season_rates(s) if s else None
                if r:
                    rl.append(r)
                    wl.append(w)
                    wgl.append(w * min(s.get('gp') or 0, 17))
            w3 = blend_rates(rl, wl)
            preds['w3'] = score_rates(w3, scoring)
            w3g = blend_rates(rl, wgl)
            preds['w3g'] = score_rates(w3g, scoring)

            # career: totals across all seasons < Y over total gp
            tot = {k: 0.0 for k in STAT_KEYS}
            tot_gp = 0
            for s in career:
                if s['yr'] >= y:
                    continue
                gp = s.get('gp') or 0
                if gp < 1:
                    continue
                tot_gp += gp
                for k in STAT_KEYS:
                    tot[k] += s.get(k) or 0
            car = {k: tot[k] / tot_gp for k in STAT_KEYS}
            preds['career'] = score_rates(car, scoring)

            # age-adjusted variants
            age = age_in_season(p.get('birthYear'), y)
            mult = 1.0
            if age is not None:
                mult = (age_curves.get(pos) or {}).get(str(age), 1.0)
            preds['career_age'] = preds['career'] * mult
            preds['w3_age'] = preds['w3'] * mult
            preds['w3g_age'] = preds['w3g'] * mult

            # 'shipped': emulates the engine's own layers as deployed
            # 2026-07-21 — w3g rates, age curve for non-QB only, experience
            # jump (exp 1-5), production-tiered vet fade (exp 6+). The live
            # Clay/Vegas/vacated/JM/injury layers can't be reconstructed
            # historically, so this is the model's own-data floor.
            shipped = preds['w3g'] * (1.0 if pos == 'QB' else mult)
            exp_jump = {'QB': {1: 1.12, 2: 1.15, 3: 1.02},
                        'RB': {1: 1.11},
                        'WR': {1: 1.05, 2: 1.05, 4: 0.96, 5: 0.92},
                        'TE': {2: 1.07, 3: 1.05, 4: 0.96, 5: 0.96}}
            vet_fade = {'RB': (0.91, 0.95), 'WR': (0.98, 0.89), 'TE': (0.91, 0.90)}
            elite_thr = {'RB': 12, 'WR': 12, 'TE': 9}
            exp = y - (p.get('debut') or y)
            if exp >= 6 and pos in vet_fade:
                shipped *= vet_fade[pos][0 if preds['w3g'] >= elite_thr[pos] else 1]
            elif 1 <= exp <= 5:
                shipped *= exp_jump.get(pos, {}).get(exp, 1.0)
            preds['shipped'] = shipped

            rows.append({'name': p['name'], 'pos': pos, 'year': y,
                         'actual': actual, 'preds': preds})
    return rows


def evaluate(rows, models):
    """Per-position pooled MAE/RMSE + n-weighted per-season Spearman & topN hit."""
    out = {}
    for pos in POSITIONS:
        pos_rows = [r for r in rows if r['pos'] == pos]
        if not pos_rows:
            continue
        res = {}
        for m in models:
            errs = [r['preds'][m] - r['actual'] for r in pos_rows]
            mae = sum(abs(e) for e in errs) / len(errs)
            rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
            # per-season rank metrics
            sp_num = sp_den = hit_num = hit_den = 0.0
            for y in sorted({r['year'] for r in pos_rows}):
                yr_rows = [r for r in pos_rows if r['year'] == y]
                if len(yr_rows) < 10:
                    continue
                pred = [r['preds'][m] for r in yr_rows]
                act = [r['actual'] for r in yr_rows]
                sp = spearman(pred, act)
                if sp is not None:
                    sp_num += sp * len(yr_rows)
                    sp_den += len(yr_rows)
                n = min(TOP_N[pos], len(yr_rows))
                top_pred = set(sorted(range(len(yr_rows)),
                                      key=lambda i: -pred[i])[:n])
                top_act = set(sorted(range(len(yr_rows)),
                                     key=lambda i: -act[i])[:n])
                hit_num += len(top_pred & top_act)
                hit_den += n
            res[m] = {
                'n': len(pos_rows), 'mae': mae, 'rmse': rmse,
                'spearman': sp_num / sp_den if sp_den else None,
                'topn_hit': hit_num / hit_den if hit_den else None,
            }
        out[pos] = res
    return out


def print_results(results, models, years, scoring_name):
    print(f'\n=== JS Model core backtest — seasons {years[0]}-{years[-1]}, '
          f'{scoring_name}, eligibility gp>=6 in Y and gp>=1 in Y-1 ===')
    for pos, res in results.items():
        n = res[models[0]]['n']
        print(f'\n{pos}  (n={n} player-seasons, top-{TOP_N[pos]} hit rate)')
        print(f'  {"model":<12}{"MAE":>7}{"RMSE":>8}{"Spearman":>10}{"topN hit":>10}')
        best_mae = min(res[m]['mae'] for m in models)
        for m in models:
            r = res[m]
            star = ' *' if abs(r['mae'] - best_mae) < 1e-9 else ''
            sp = f"{r['spearman']:.3f}" if r['spearman'] is not None else '—'
            th = f"{r['topn_hit']*100:.0f}%" if r['topn_hit'] is not None else '—'
            print(f'  {m:<12}{r["mae"]:>7.2f}{r["rmse"]:>8.2f}{sp:>10}{th:>10}{star}')


def per_season_summary(rows, model='shipped'):
    """Season-by-season rank quality — how stable is the model year to year?"""
    print(f"\n=== '{model}': per-season Spearman / top-N hits ===")
    for y in sorted({r['year'] for r in rows}):
        parts = []
        for pos in POSITIONS:
            yr = [r for r in rows if r['year'] == y and r['pos'] == pos]
            if len(yr) < 10:
                continue
            pred = [r['preds'][model] for r in yr]
            act = [r['actual'] for r in yr]
            sp = spearman(pred, act)
            n = min(TOP_N[pos], len(yr))
            tp = set(sorted(range(len(yr)), key=lambda i: -pred[i])[:n])
            ta = set(sorted(range(len(yr)), key=lambda i: -act[i])[:n])
            parts.append(f'{pos} {sp:.2f} {len(tp & ta)}/{n}')
        print(f'  {y}:  ' + '   '.join(parts))


def residuals_by_experience(db, rows, model='w3_age'):
    """How much do players out/under-perform the core projection by pos x exp?

    exp = years since debut entering season Y (1 = second season). Positive
    mean relative residual for low exp = 'young players take a jump' that the
    historical-rates core misses. Used to calibrate _JS_EXP_JUMP in app.js.
    """
    debut = {p['name']: p.get('debut') for p in db}
    buckets = defaultdict(list)
    for r in rows:
        deb = debut.get(r['name'])
        if not deb:
            continue
        exp = r['year'] - deb
        if exp < 1:
            continue
        key = (r['pos'], exp if exp <= 5 else 6)
        pred = r['preds'][model]
        if pred >= 3:  # relative residual is meaningless near zero
            buckets[key].append((r['actual'] - pred) / pred)
    print(f'\n=== Mean relative residual (actual vs {model}) by pos x years-of-experience ===')
    print('    positive = players at this experience level BEAT the core projection')
    for pos in POSITIONS:
        parts = []
        for exp in range(1, 7):
            v = buckets.get((pos, exp))
            if not v:
                continue
            mean = sum(v) / len(v)
            label = f'{exp}' if exp <= 5 else '6+'
            parts.append(f'exp{label}: {mean:+.1%} (n={len(v)})')
        print(f'  {pos:<3} ' + '  '.join(parts))

    # Veteran fade by production tier: does the exp-6+ fade apply to ELITE
    # producers too, or only to the mid-tier vets falling off cliffs?
    # Tier = projected PPG (the core's own estimate, so it's known pre-season).
    elite_thr = {'QB': 17, 'RB': 12, 'WR': 12, 'TE': 9}
    tier_buckets = defaultdict(list)
    for r in rows:
        deb = debut.get(r['name'])
        if not deb or r['year'] - deb < 6:
            continue
        pred = r['preds'][model]
        if pred < 3:
            continue
        tier = 'elite' if pred >= elite_thr[r['pos']] else 'rest'
        tier_buckets[(r['pos'], tier)].append((r['actual'] - pred) / pred)
    print(f'\n=== exp6+ veteran residual split by projected-PPG tier '
          f'(elite thr: {elite_thr}) ===')
    for pos in POSITIONS:
        parts = []
        for tier in ('elite', 'rest'):
            v = tier_buckets.get((pos, tier))
            if v:
                parts.append(f'{tier}: {sum(v)/len(v):+.1%} (n={len(v)})')
        if parts:
            print(f'  {pos:<3} ' + '  '.join(parts))


def diagnose_file_weighting(db, js_model_data, scoring):
    """Which weighting does js_model_data.js match: career-avg or recency (w3)?"""
    # file row: [name,pos,team,gp,pass_yds,pass_td,ints,rush_yds,rush_td,rec,rec_yds,rec_td,fum]
    file_keys = ['py', 'ptd', 'int', 'ry', 'rtd', 'rc', 'rcy', 'rctd', 'fl']
    by_name = {}
    for p in db:
        by_name.setdefault(p['name'], p)
    diffs = {'career': [], 'w3': [], 'w3g': []}
    matched = 0
    for row in js_model_data:
        name, pos = row[0], row[1]
        p = by_name.get(name)
        if not p or p.get('pos') != pos:
            continue
        career = sorted((s for s in (p.get('career') or [])
                         if s.get('yr') and (s.get('gp') or 0) >= 1),
                        key=lambda s: s['yr'])
        if len(career) < 2:
            continue
        file_rates = dict(zip(file_keys, row[4:13]))
        last_yr = career[-1]['yr']
        # career-avg hypothesis
        tot = {k: 0.0 for k in STAT_KEYS}
        tot_gp = 0
        for s in career:
            tot_gp += s['gp']
            for k in STAT_KEYS:
                tot[k] += s.get(k) or 0
        car = {k: tot[k] / tot_gp for k in STAT_KEYS}
        # w3 / w3g hypotheses anchored on last played season
        rl, wl, wgl = [], [], []
        for back, w in zip(range(0, 3), W3_WEIGHTS):
            s = next((x for x in career if x['yr'] == last_yr - back), None)
            r = season_rates(s) if s else None
            if r:
                rl.append(r)
                wl.append(w)
                wgl.append(w * min(s.get('gp') or 0, 17))
        w3 = blend_rates(rl, wl)
        w3g = blend_rates(rl, wgl)
        diffs['career'].append(abs(score_rates(car, scoring) - score_rates(file_rates, scoring)))
        diffs['w3'].append(abs(score_rates(w3, scoring) - score_rates(file_rates, scoring)))
        diffs['w3g'].append(abs(score_rates(w3g, scoring) - score_rates(file_rates, scoring)))
        matched += 1
    print(f'\n=== js_model_data.js weighting diagnostic ({matched} matched players, '
          f'PPG-space MAE vs each hypothesis) ===')
    for h in ('career', 'w3', 'w3g'):
        d = diffs[h]
        if d:
            print(f'  {h:<8} MAE {sum(d)/len(d):.2f} ppg   '
                  f'(median {sorted(d)[len(d)//2]:.2f})')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', nargs=2, type=int, default=[2018, 2025],
                    metavar=('FROM', 'TO'))
    ap.add_argument('--scoring', default='half_ppr', choices=sorted(SCORING))
    args = ap.parse_args()

    scoring = SCORING[args.scoring]
    years = list(range(args.years[0], args.years[1] + 1))

    print('Loading data files...')
    db = load_js_const(os.path.join(DATA_DIR, 'all_players.js'), 'ALL_PLAYERS_DB')
    js_path = os.path.join(DATA_DIR, 'js_model_data.js')
    age_curves = load_js_const(js_path, '_JS_AGE_CURVES')
    js_model_data = load_js_const(js_path, '_JS_MODEL_DATA')

    max_yr = max((s.get('yr') or 0) for p in db for s in (p.get('career') or []))
    print(f'ALL_PLAYERS_DB: {len(db)} players, latest season {max_yr}')
    years = [y for y in years if y <= max_yr]

    rows = build_predictions(db, years, scoring, age_curves)
    models = ['prior', 'w3', 'w3g', 'career', 'career_age', 'w3_age', 'w3g_age', 'shipped']
    results = evaluate(rows, models)
    print_results(results, models, years, args.scoring)
    per_season_summary(rows)
    residuals_by_experience(db, rows)
    diagnose_file_weighting(db, js_model_data, scoring)

    # Overall summary line
    print('\n=== Overall (all positions pooled) ===')
    print(f'  {"model":<12}{"MAE":>7}{"RMSE":>8}')
    for m in models:
        errs = [r['preds'][m] - r['actual'] for r in rows]
        mae = sum(abs(e) for e in errs) / len(errs)
        rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
        print(f'  {m:<12}{mae:>7.2f}{rmse:>8.2f}')


if __name__ == '__main__':
    sys.exit(main())
