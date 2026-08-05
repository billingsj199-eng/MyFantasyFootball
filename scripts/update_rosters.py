#!/usr/bin/env python3
"""Sync d.js player team assignments ("t" field) with live NFL rosters.

Source: Sleeper's public players dump (https://api.sleeper.app/v1/players/nfl)
— one unauthenticated GET, refreshed by Sleeper daily. Team abbreviations are
mapped to the FULL team names d.js uses ("Washington Commanders"); a player
with no Sleeper team becomes "FA". DST rows are never touched.

Matching is name+position FIRST (normalized, Jr/III stripped, FB counted as
RB), against ACTIVE Sleeper records only. The ESPN id baked into _slImg is
only a tiebreaker / last-resort fallback — the 2026-08-04 headshot bake wrote
wrong ESPN ids for ~40 players (e.g. Kenneth Walker III carries the retired
WR Kenneth Walker's id), so it must never be the primary join key.

Contract fields (sal/cyr/out) are deliberately left alone: Sleeper carries no
contract data and ESPN's core contracts endpoint would need ~580 per-athlete
calls keyed by those same unreliable ESPN ids. Contracts stay manual.

Safety rails:
  * aborts if Sleeper returns < 2500 rostered players (bad/partial payload)
  * aborts if the diff proposes more than --max-changes (default 25) moves
  * splices "t" values surgically into the raw d.js text (no re-serialize),
    then re-parses the result and verifies every change landed before writing
  * unmatched / ambiguous players are logged and left untouched

Usage:
  python scripts/update_rosters.py            # fetch, diff, apply, bump ?v=
  python scripts/update_rosters.py --dry-run  # report only, change nothing
  python scripts/update_rosters.py --no-bump  # apply but skip the index.html
                                              # ?v= bump (pipeline mode: the
                                              # caller bumps once at the end)

Runs standalone or as Phase H of scripts/pull_consensus_adp.py (9am job).
"""

import argparse
import datetime
import json
import os
import re
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D_PATH = os.path.join(ROOT, 'data', 'd.js')
INDEX_FILE = os.path.join(ROOT, 'index.html')
TODAY = datetime.date.today().isoformat()

SLEEPER_URL = 'https://api.sleeper.app/v1/players/nfl'
MIN_ROSTERED = 2500  # sanity floor: NFL offseason rosters carry ~2900 players

TEAM_FULL = {
    'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons',
    'BAL': 'Baltimore Ravens', 'BUF': 'Buffalo Bills',
    'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears',
    'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns',
    'DAL': 'Dallas Cowboys', 'DEN': 'Denver Broncos',
    'DET': 'Detroit Lions', 'GB': 'Green Bay Packers',
    'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts',
    'JAX': 'Jacksonville Jaguars', 'KC': 'Kansas City Chiefs',
    'LAC': 'Los Angeles Chargers', 'LAR': 'Los Angeles Rams',
    'LV': 'Las Vegas Raiders', 'MIA': 'Miami Dolphins',
    'MIN': 'Minnesota Vikings', 'NE': 'New England Patriots',
    'NO': 'New Orleans Saints', 'NYG': 'New York Giants',
    'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles',
    'PIT': 'Pittsburgh Steelers', 'SEA': 'Seattle Seahawks',
    'SF': 'San Francisco 49ers', 'TB': 'Tampa Bay Buccaneers',
    'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders',
}

# d.js name -> Sleeper full_name, for spellings that normalization can't bridge.
NAME_ALIASES = {
    'Kenneth Gainwell': 'Kenny Gainwell',
    'Josh Palmer': 'Joshua Palmer',
    'Chip Trayanum': 'DeaMonte Trayanum',
    'Matthew Hibner': 'Matt Hibner',
    'Romelo Brinson': 'Romello Brinson',
}

FANTASY_POS = {'QB', 'RB', 'WR', 'TE', 'K', 'FB'}


def norm_name(n):
    n = n.lower()
    n = re.sub(r"[.'`-]", '', n)
    n = re.sub(r'\s+(jr|sr|ii|iii|iv|v)$', '', n.strip())
    return re.sub(r'\s+', ' ', n)


def norm_pos(p):
    return 'RB' if p == 'FB' else p


def fetch_sleeper():
    resp = requests.get(SLEEPER_URL, timeout=90)
    resp.raise_for_status()
    players = resp.json()
    rostered = sum(1 for p in players.values() if p.get('team'))
    print(f'  Sleeper: {len(players)} players, {rostered} rostered')
    if rostered < MIN_ROSTERED:
        raise RuntimeError(
            f'Sleeper payload suspicious ({rostered} rostered < {MIN_ROSTERED}) — aborting')
    return players


def build_indexes(players):
    """(by_name, by_espn) — active fantasy-position records only.

    Sleeper's dump contains "Duplicate Player" rows and inactive same-name
    retirees (the Kenneth Walker collision class); indexing active-only kills
    both. A d.js player whose only Sleeper record is inactive (mid-offseason
    retirement) simply goes unmatched and is left for manual handling.
    """
    by_name, by_espn = {}, {}
    for p in players.values():
        if not p.get('active') or p.get('full_name') == 'Duplicate Player':
            continue
        pos = p.get('position')
        if pos not in FANTASY_POS:
            continue
        fn = p.get('full_name')
        if fn:
            by_name.setdefault((norm_name(fn), norm_pos(pos)), []).append(p)
        if p.get('espn_id'):
            by_espn.setdefault(str(p['espn_id']), []).append(p)
    return by_name, by_espn


def espn_id_of(d):
    m = re.search(r'/full/(\d+)\.png', d.get('_slImg') or '')
    return m.group(1) if m else None


def match_player(d, by_name, by_espn):
    """Returns (sleeper_record | None, how)."""
    name = NAME_ALIASES.get(d['n'], d['n'])
    cands = by_name.get((norm_name(name), norm_pos(d.get('s'))), [])
    if len(cands) == 1:
        return cands[0], 'name'
    eid = espn_id_of(d)
    if len(cands) > 1:
        hits = [c for c in cands if str(c.get('espn_id')) == eid]
        if len(hits) == 1:
            return hits[0], 'name+espn'
        return None, 'ambiguous'
    if eid:
        hits = by_espn.get(eid, [])
        if len(hits) == 1:
            return hits[0], 'espn'
    return None, 'unmatched'


def compute_changes(d_arr, by_name, by_espn):
    changes, unmatched, ambiguous = [], [], []
    for d in d_arr:
        if d.get('s') == 'DST' or not d.get('n'):
            continue
        p, how = match_player(d, by_name, by_espn)
        if p is None:
            (ambiguous if how == 'ambiguous' else unmatched).append(
                (d['n'], d.get('s'), d.get('t')))
            continue
        abbr = p.get('team')
        new_t = 'FA' if not abbr else TEAM_FULL.get(abbr)
        if new_t is None:  # legacy abbr (OAK etc.) — never write garbage
            print(f"  !! unknown team abbr {abbr!r} for {d['n']} — skipped")
            continue
        if new_t != d.get('t'):
            changes.append({'n': d['n'], 's': d.get('s'), 'old': d.get('t'),
                            'new': new_t, 'how': how})
    return changes, unmatched, ambiguous


def player_object_spans(src):
    """Char spans of each top-level object in D=[...], same brace/string
    walker inject_rankings.py uses."""
    start_m = re.search(r'\bD\s*=\s*\[', src)
    if not start_m:
        raise RuntimeError('Could not locate D=[ start in d.js')
    i = start_m.end()
    spans, depth, in_str, esc, obj_start = [], 0, False, False, None
    while i < len(src):
        c = src[i]
        if esc:
            esc = False
        elif in_str:
            if c == '\\':
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == '{':
            if depth == 0:
                obj_start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                spans.append((obj_start, i + 1))
        elif c == ']' and depth == 0:
            break
        i += 1
    return spans


def apply_changes(src, spans, d_arr, changes):
    """Splice new "t" values into the raw source, most-offset-first so earlier
    spans stay valid. Every change must find its exact "t":"<old>" literal."""
    by_name = {}
    for idx, d in enumerate(d_arr):
        by_name.setdefault((d.get('n'), d.get('s')), idx)
    edits = []
    for ch in changes:
        idx = by_name.get((ch['n'], ch['s']))
        if idx is None or idx >= len(spans):
            raise RuntimeError(f"lost track of {ch['n']} while splicing")
        edits.append((spans[idx], ch))
    for (s, e), ch in sorted(edits, key=lambda x: -x[0][0]):
        body = src[s:e]
        old_lit = '"t":' + json.dumps(ch['old'], ensure_ascii=False)
        new_lit = '"t":' + json.dumps(ch['new'], ensure_ascii=False)
        if body.count(old_lit) != 1:
            raise RuntimeError(
                f"expected exactly one {old_lit} in {ch['n']}'s object, "
                f"found {body.count(old_lit)}")
        src = src[:s] + body.replace(old_lit, new_lit, 1) + src[e:]
    return src


def parse_d(src):
    return json.JSONDecoder().raw_decode(src, src.index('['))[0]


def bump_version(fname=r'data/d\.js'):
    # Read index.html fresh right before bumping — other sessions bump ?v= too.
    html = open(INDEX_FILE, encoding='utf-8').read()
    pat = r'(' + fname + r'\?v=)([\w.-]+)'
    m = re.search(pat, html)
    if not m:
        print(f'  !! {fname} script tag not found in index.html — bump ?v= manually')
        return
    old = m.group(2)
    if old.startswith(TODAY):
        suffix = old[len(TODAY):]
        new = TODAY + ('b' if not suffix else chr(ord(suffix[-1]) + 1))
    else:
        new = TODAY
    html = re.sub(pat, r'\g<1>' + new, html)
    open(INDEX_FILE, 'w', encoding='utf-8').write(html)
    print(f'  index.html: {fname} ?v={old} -> ?v={new}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--dry-run', action='store_true',
                    help='report the diff, change nothing')
    ap.add_argument('--no-bump', action='store_true',
                    help='apply to d.js but skip the index.html ?v= bump')
    ap.add_argument('--max-changes', type=int, default=25,
                    help='abort if the diff proposes more moves than this '
                         '(guards against a bad Sleeper payload; default 25)')
    args = ap.parse_args()

    print(f'Roster sync {TODAY} (Sleeper -> d.js)')
    players = fetch_sleeper()
    by_name, by_espn = build_indexes(players)

    src = open(D_PATH, encoding='utf-8').read()
    d_arr = parse_d(src)
    changes, unmatched, ambiguous = compute_changes(d_arr, by_name, by_espn)

    for who in unmatched:
        print(f'  no Sleeper match (left as-is): {who[0]} {who[1]} [{who[2]}]')
    for who in ambiguous:
        print(f'  ambiguous Sleeper match (left as-is): {who[0]} {who[1]} [{who[2]}]')

    if not changes:
        print('Rosters in sync — no changes.')
        return
    print(f'\n{len(changes)} team change(s):')
    for ch in changes:
        print(f"  {ch['n']} ({ch['s']}): {ch['old']} -> {ch['new']}  [{ch['how']}]")

    if len(changes) > args.max_changes:
        raise RuntimeError(
            f'{len(changes)} changes exceeds --max-changes={args.max_changes} '
            f'— refusing to auto-apply (rerun with a higher limit if real)')
    if args.dry_run:
        print('\nDry run — d.js not modified.')
        return

    spans = player_object_spans(src)
    if len(spans) != len(d_arr):
        raise RuntimeError(
            f'object walker found {len(spans)} entries, JSON parse found '
            f'{len(d_arr)} — refusing to splice')
    new_src = apply_changes(src, spans, d_arr, changes)

    # Verify before writing: re-parse and confirm every change landed.
    new_arr = parse_d(new_src)
    want = {(ch['n'], ch['s']): ch['new'] for ch in changes}
    for d in new_arr:
        key = (d.get('n'), d.get('s'))
        if key in want and d.get('t') != want[key]:
            raise RuntimeError(f'verification failed for {key[0]} — d.js not written')

    open(D_PATH, 'w', encoding='utf-8').write(new_src)
    print(f'\nWrote {len(changes)} change(s) to data/d.js')
    if not args.no_bump:
        bump_version()


if __name__ == '__main__':
    main()
