#!/usr/bin/env python3
"""
generate_js_model_data.py — Regenerate data/js_model_data.js from ALL_PLAYERS_DB.

Builds the _JS_MODEL_DATA per-game rate table the JS Model engine (app.js)
projects from. Rates are 50/30/20 recency-weighted over the last three league
seasons (anchor = latest season in ALL_PLAYERS_DB, weights renormalized over
the seasons the player actually appeared in), with each season's weight ALSO
scaled by games played (min(gp,17)) — an 8-game injury season shouldn't
dominate two healthy 17-game ones just because it's most recent. NOT career
averages. The scripts/backtest_js_model.py harness showed career-average
rates lose to even a naive prior-year baseline at WR; 50/30/20 is the best
core at every position, and the games-played scaling ("w3g") matches or
beats it everywhere (2018-2025 backtest, 2026-07-21).

Players included: pos QB/RB/WR/TE who played in the anchor season or the one
before it (missing one full season to injury is draftable; anyone out longer
is effectively retired — a looser cutoff resurfaced Tom Brady as QB4 via the
last-played fallback). Keeps the file small and every row inside the 50/30/20
calendar window.

Preserves the _JS_AGE_CURVES and _JS_ROOKIE_TEMPLATES lines of the existing
file untouched.

Row format (consumed by _jsBuildProj in app.js — do not reorder):
  [name, pos, team, gp, pass_yds, pass_td, ints, rush_yds, rush_td,
   rec, rec_yds, rec_td, fumbles]     (all per-game except gp)

Usage:  python scripts/generate_js_model_data.py
        # then bump the ?v= on the js_model_data.js script tag in index.html
"""

import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(ROOT, 'data')
OUT_PATH = os.path.join(DATA_DIR, 'js_model_data.js')

POSITIONS = {'QB', 'RB', 'WR', 'TE'}
WEIGHTS = [0.5, 0.3, 0.2]  # anchor year, anchor-1, anchor-2
# ALL_PLAYERS_DB key -> output slot (per-game); output order after gp:
STAT_KEYS = ['py', 'ptd', 'int', 'ry', 'rtd', 'rc', 'rcy', 'rctd', 'fl']


def load_js_const(path, const_name):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    m = re.search(r'const\s+' + re.escape(const_name) + r'\s*=\s*', text)
    if not m:
        raise ValueError(f'{const_name} not found in {path}')
    start = m.end()
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


def raw_js_line(path, const_name):
    """Return the existing `const NAME=...;`-style line verbatim."""
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.lstrip().startswith('const ' + const_name):
                return line.rstrip('\n')
    raise ValueError(f'{const_name} line not found in {path}')


def weighted_rates(seasons, years):
    """50/30/20 x games-played per-game rates over `years` (renormalized)."""
    by_year = {s['yr']: s for s in seasons}
    rates, weights, gps = [], [], []
    for yr, w in zip(years, WEIGHTS):
        s = by_year.get(yr)
        gp = (s or {}).get('gp') or 0
        if not s or gp < 1:
            continue
        rates.append({k: (s.get(k) or 0) / gp for k in STAT_KEYS})
        weights.append(w * min(gp, 17))
        gps.append(gp)
    if not rates:
        return None
    tw = sum(weights)
    blended = {k: sum(r[k] * w for r, w in zip(rates, weights)) / tw
               for k in STAT_KEYS}
    gp = sum(g * w for g, w in zip(gps, weights)) / tw
    return blended, gp


def fmt(x, dp):
    v = round(x, dp)
    if v == int(v):
        return f'{v:.1f}' if dp >= 1 else str(int(v))
    return f'{v:.{dp}f}'.rstrip('0').rstrip('.')


def main():
    db = load_js_const(os.path.join(DATA_DIR, 'all_players.js'), 'ALL_PLAYERS_DB')
    anchor = max((s.get('yr') or 0) for p in db for s in (p.get('career') or []))
    window = [anchor, anchor - 1, anchor - 2]
    print(f'ALL_PLAYERS_DB: {len(db)} players, anchor season {anchor}')

    # Dedupe by name: the engine keys _jsNameMap by name only, so on a name
    # collision keep the more recently active player.
    candidates = {}
    for p in db:
        if p.get('pos') not in POSITIONS:
            continue
        seasons = [s for s in (p.get('career') or [])
                   if s.get('yr') and (s.get('gp') or 0) >= 1]
        if not seasons:
            continue
        last = max(s['yr'] for s in seasons)
        if last < anchor - 1:
            continue  # out of the league 2+ seasons: effectively retired
        prev = candidates.get(p['name'])
        if prev and prev[1] >= last:
            continue
        candidates[p['name']] = (p, last, seasons)

    rows = []
    fallback_n = 0
    for name in sorted(candidates):
        p, last, seasons = candidates[name]
        wr = weighted_rates(seasons, window)
        if wr is None:
            # No games in the calendar window: last three played seasons
            played = sorted({s['yr'] for s in seasons}, reverse=True)[:3]
            wr = weighted_rates(seasons, played)
            fallback_n += 1
        rates, gp = wr
        team = max(seasons, key=lambda s: s['yr']).get('tm') or ''
        rows.append('[' + ','.join([
            json.dumps(p['name']), json.dumps(p['pos']), json.dumps(team),
            fmt(gp, 1),
            fmt(rates['py'], 1), fmt(rates['ptd'], 2), fmt(rates['int'], 2),
            fmt(rates['ry'], 1), fmt(rates['rtd'], 2),
            fmt(rates['rc'], 2), fmt(rates['rcy'], 1), fmt(rates['rctd'], 2),
            fmt(rates['fl'], 2),
        ]) + ']')

    age_line = raw_js_line(OUT_PATH, '_JS_AGE_CURVES')
    tmpl_line = raw_js_line(OUT_PATH, '_JS_ROOKIE_TEMPLATES')

    header = (f'// Generated by scripts/generate_js_model_data.py — 50/30/20 '
              f'recency-weighted per-game rates, anchor season {anchor}. '
              f'Do not hand-edit; rerun the script after all_players.js updates.')
    out = '\n'.join([header,
                     'const _JS_MODEL_DATA=[' + ','.join(rows) + '];',
                     age_line, tmpl_line, ''])
    with open(OUT_PATH, 'w', encoding='utf-8', newline='\n') as f:
        f.write(out)
    print(f'Wrote {len(rows)} rows ({fallback_n} via last-played fallback) '
          f'-> {os.path.relpath(OUT_PATH, ROOT)} '
          f'({os.path.getsize(OUT_PATH) // 1024} KB)')

    # Diagnostic: how many current rankings players match by exact name
    d_path = os.path.join(DATA_DIR, 'd.js')
    if os.path.exists(d_path):
        with open(d_path, encoding='utf-8') as f:
            d_text = f.read()
        d_names = set(re.findall(r'[{,]\s*"?n"?\s*:\s*"([^"]+)"', d_text))
        if d_names:
            row_names = set(candidates)
            matched = sum(1 for n in d_names if n in row_names)
            print(f'D array: {len(d_names)} names found, '
                  f'{matched} exact-match a _JS_MODEL_DATA row '
                  f'(engine also does normalized fallback matching)')


if __name__ == '__main__':
    sys.exit(main())
