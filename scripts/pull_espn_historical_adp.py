#!/usr/bin/env python3
"""
Pull historical ESPN redraft ADP + actual season fantasy points, aggregate into
positional draft-timing tables, and write data/draft_history.js.

Source: ESPN's public kona_player_info API. For a past season it returns both
that year's final preseason ADP (ownership.averageDraftPosition) and the actual
season total (stats[] where statSourceId==0 and statSplitTypeId==0).

    https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{YEAR}
        /segments/0/leaguedefaults/3?view=kona_player_info

leaguedefaults/3 is the PPR default, so appliedTotal is already PPR-scored.

GOTCHAS (learned the hard way):
  * The x-fantasy-filter header MUST carry a sort or historical seasons 400.
    sortDraftRanks works everywhere; sortAdp only works for the current season.
  * Only 2018 and 2020-2024 retain real ADP. 2019 and 2025 come back with every
    player at averageDraftPosition 0, and 2017 and earlier 404. Alternate
    leaguedefaults ids don't recover them.
  * ADP is capped at 170 -- every undrafted player piles up on that value, so
    anything >= 169.5 is dropped or the last round is meaningless.

Usage:  python scripts/pull_espn_historical_adp.py
Output: data/draft_history.js  (window.DRAFT_HISTORY)
"""

import json
import math
import os
import sys
import time
from collections import defaultdict

import requests

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

SEASONS = [2018, 2020, 2021, 2022, 2023, 2024]

BASE = ('https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/'
        '{year}/segments/0/leaguedefaults/3')
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; MyFantasyFootball/1.0)'}

POS = {1: 'QB', 2: 'RB', 3: 'WR', 4: 'TE', 5: 'K', 16: 'DST'}
POS_ORDER = ['QB', 'RB', 'WR', 'TE']      # positions the round grid covers
STREAM_POS = ['K', 'DST']                 # reported separately, no VOR

TEAM_COUNT = 12          # 12-team league -> 12 picks per round
MAX_ROUND = 13           # round 14+ is the ADP-cap pile, not real draft data
ADP_CAP = 169.5

# Replacement level: the last starter-ish player at each position in a 12-team
# league running 1QB / 2RB / 2WR / 1TE / 1FLEX. RB/WR sit at 30 to absorb the
# flex.
#
# Replacement is measured against EVERY player at the position that season, not
# just the drafted ones. Using the drafted-only pool silently breaks for thin
# positions -- only ~9 kickers per season carry a real ADP, so a rank-24 lookup
# fell off the end of the list and returned the worst drafted kicker, which made
# every drafted K and DST look hugely valuable. The waiver pool is the honest
# baseline.
REPLACEMENT_RANK = {'QB': 13, 'RB': 30, 'WR': 30, 'TE': 13, 'K': 13, 'DST': 13}

# "Startable" finish -- what counts as the pick having worked out.
STARTABLE_RANK = {'QB': 12, 'RB': 24, 'WR': 24, 'TE': 12, 'K': 12, 'DST': 12}

ELITE_RANK = 5           # top-5 finish at the position

MIN_N = 4                # below this a pos x round cell is too thin to quote

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT_JS = os.path.join(REPO, 'data', 'draft_history.js')


# --------------------------------------------------------------------------
# Pull
# --------------------------------------------------------------------------

def pull_season(year):
    """Return (drafted, everyone) for one season.

    `everyone` is every player at a fantasy position regardless of ADP -- it is
    what replacement level and positional finish rank are measured against.
    `drafted` is the subset that carried a real ADP.
    """
    flt = {'players': {'limit': 1500,
                       'sortDraftRanks': {'sortPriority': 100,
                                          'sortAsc': True,
                                          'value': 'STANDARD'}}}
    r = requests.get(BASE.format(year=year),
                     params={'view': 'kona_player_info'},
                     headers={**HEADERS, 'x-fantasy-filter': json.dumps(flt)},
                     timeout=90)
    r.raise_for_status()

    everyone = []
    for item in r.json().get('players', []):
        p = item.get('player', {})
        pos = POS.get(p.get('defaultPositionId'))
        if not pos:
            continue
        pts = 0.0
        for st in p.get('stats') or []:
            if (st.get('statSourceId') == 0
                    and st.get('statSplitTypeId') == 0
                    and st.get('seasonId') == year):
                pts = st.get('appliedTotal') or 0.0
        adp = (p.get('ownership') or {}).get('averageDraftPosition') or 0
        everyone.append({'name': p.get('fullName') or '?',
                         'pos': pos,
                         'adp': round(adp, 2) if 0 < adp < ADP_CAP else None,
                         'pts': round(pts, 1)})

    drafted = sorted((x for x in everyone if x['adp'] is not None),
                     key=lambda x: x['adp'])
    return drafted, everyone


# --------------------------------------------------------------------------
# Aggregate
# --------------------------------------------------------------------------

def enrich(drafted, everyone, year):
    """Add round, positional finish rank, and VOR to each drafted row."""
    by_pos = defaultdict(list)
    for r in everyone:
        by_pos[r['pos']].append(r)

    repl_pts = {}
    for pos, lst in by_pos.items():
        ranked = sorted(lst, key=lambda x: -x['pts'])
        for i, x in enumerate(ranked):
            x['posrank'] = i + 1
        idx = REPLACEMENT_RANK[pos] - 1
        if idx >= len(ranked):
            raise RuntimeError(f'{year} {pos}: only {len(ranked)} players, '
                               f'cannot take replacement at rank {idx + 1}')
        repl_pts[pos] = ranked[idx]['pts']

    for r in drafted:
        r['year'] = year
        r['round'] = max(1, math.ceil(r['adp'] / TEAM_COUNT))
        r['vor'] = round(r['pts'] - repl_pts[r['pos']], 1)
    return drafted


def spearman(pairs):
    """Rank correlation between two rankings. pairs = [(rankA, rankB), ...]."""
    n = len(pairs)
    if n < 4:
        return None
    d2 = sum((a - b) ** 2 for a, b in pairs)
    return 1 - (6 * d2) / (n * (n * n - 1))


def build_predictability(all_rows):
    """How well does draft order predict finish order, within each position?

    Per season, rank that position's drafted players by ADP and by actual
    finish, then take the rank correlation. Averaged across seasons. A value
    near 0 means the draft market has no idea; near 1 means chalk holds.
    """
    out = {}
    for pos in POS_ORDER + STREAM_POS:
        per_season = []
        for year in SEASONS:
            lst = [x for x in all_rows if x['year'] == year and x['pos'] == pos]
            if len(lst) < 4:
                continue
            by_adp = sorted(lst, key=lambda x: x['adp'])
            by_pts = sorted(lst, key=lambda x: -x['pts'])
            pts_rank = {id(x): i + 1 for i, x in enumerate(by_pts)}
            rho = spearman([(i + 1, pts_rank[id(x)])
                            for i, x in enumerate(by_adp)])
            if rho is not None:
                per_season.append(rho)
        if per_season:
            out[pos] = {'rho': round(sum(per_season) / len(per_season), 3),
                        'seasons': len(per_season)}
    return out


def build_stream_positions(all_rows):
    """K and DST get no VOR grid -- just when they go and whether it matters."""
    out = {}
    for pos in STREAM_POS:
        lst = [x for x in all_rows if x['pos'] == pos]
        if not lst:
            continue
        hit = sum(1 for x in lst if x['posrank'] <= STARTABLE_RANK[pos])
        early = [x for x in lst if x['round'] <= 11]
        late = [x for x in lst if x['round'] >= 12]
        rate = lambda g: (round(sum(1 for x in g
                                    if x['posrank'] <= STARTABLE_RANK[pos])
                                / len(g), 3) if g else None)
        out[pos] = {
            'n': len(lst),
            'hit': round(hit / len(lst), 3),
            'earlyHit': rate(early), 'earlyN': len(early),
            'lateHit': rate(late), 'lateN': len(late),
        }
    return out


def build_tables(all_rows):
    """pos x round aggregates plus derived cliff / ranking views."""
    cells = defaultdict(list)
    for r in all_rows:
        if r['round'] <= MAX_ROUND:
            cells[(r['pos'], r['round'])].append(r)

    grid = {}
    for pos in POS_ORDER:
        grid[pos] = {}
        for rnd in range(1, MAX_ROUND + 1):
            lst = cells.get((pos, rnd), [])
            if not lst:
                continue
            n = len(lst)
            grid[pos][rnd] = {
                'n': n,
                'vor': round(sum(x['vor'] for x in lst) / n, 1),
                'hit': round(sum(1 for x in lst
                                 if x['posrank'] <= STARTABLE_RANK[pos]) / n, 3),
                'elite': round(sum(1 for x in lst
                                   if x['posrank'] <= ELITE_RANK) / n, 3),
                'best': max(lst, key=lambda x: x['vor'])['name'],
                'worst': min(lst, key=lambda x: x['vor'])['name'],
            }
    return grid


def build_cliffs(grid):
    """Biggest round-over-round VOR drop per position, thin cells excluded."""
    out = {}
    for pos in POS_ORDER:
        drops = []
        for rnd in range(1, MAX_ROUND):
            a, b = grid[pos].get(rnd), grid[pos].get(rnd + 1)
            if a and b and a['n'] >= MIN_N and b['n'] >= MIN_N:
                drops.append({'after': rnd,
                              'drop': round(a['vor'] - b['vor'], 1),
                              'from': a['vor'], 'to': b['vor']})
        drops.sort(key=lambda d: -d['drop'])
        out[pos] = drops[:3]
    return out


def build_board(grid):
    """Per round, positions ordered by mean VOR (thin cells excluded)."""
    board = {}
    for rnd in range(1, MAX_ROUND + 1):
        ranked = [{'pos': p, 'vor': grid[p][rnd]['vor'], 'n': grid[p][rnd]['n']}
                  for p in POS_ORDER
                  if rnd in grid[p] and grid[p][rnd]['n'] >= MIN_N]
        ranked.sort(key=lambda x: -x['vor'])
        board[rnd] = ranked
    return board


def build_season_winners(all_rows):
    """Which position led each round, season by season -- a stability check."""
    out = {}
    for rnd in range(1, 9):
        row = {}
        for year in SEASONS:
            best, best_v = None, None
            for pos in POS_ORDER:
                lst = [x for x in all_rows
                       if x['year'] == year and x['pos'] == pos
                       and x['round'] == rnd]
                if len(lst) >= 2:
                    v = sum(x['vor'] for x in lst) / len(lst)
                    if best_v is None or v > best_v:
                        best, best_v = pos, v
            row[year] = best
        out[rnd] = row
    return out


def build_extremes(all_rows, k=8):
    """Biggest league-winners and biggest landmines, for page colour."""
    drafted_early = [r for r in all_rows if r['round'] <= MAX_ROUND]
    hits = sorted(drafted_early, key=lambda x: -x['vor'])[:k]
    busts = sorted([r for r in drafted_early if r['round'] <= 5],
                   key=lambda x: x['vor'])[:k]
    trim = lambda r: {'name': r['name'], 'pos': r['pos'], 'year': r['year'],
                      'round': r['round'], 'adp': r['adp'], 'vor': r['vor']}
    return {'hits': [trim(r) for r in hits], 'busts': [trim(r) for r in busts]}


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    all_rows = []
    for year in SEASONS:
        try:
            drafted, everyone = pull_season(year)
            if len(drafted) < 150:
                raise RuntimeError(f'only {len(drafted)} rows with real ADP')
            enrich(drafted, everyone, year)
        except Exception as e:
            print(f'  !! {year}: {e} -- aborting, keeping old file')
            return 1
        all_rows.extend(drafted)
        print(f'  {year}: {len(drafted)} drafted of {len(everyone)} players')
        time.sleep(1)

    grid = build_tables(all_rows)
    payload = {
        'meta': {
            'seasons': SEASONS,
            'teams': TEAM_COUNT,
            'scoring': 'PPR',
            'maxRound': MAX_ROUND,
            'replacement': REPLACEMENT_RANK,
            'startable': STARTABLE_RANK,
            'sample': len(all_rows),
            'source': 'ESPN kona_player_info',
        },
        'grid': grid,
        'cliffs': build_cliffs(grid),
        'board': build_board(grid),
        'seasonWinners': build_season_winners(all_rows),
        'extremes': build_extremes(all_rows),
        'predictability': build_predictability(all_rows),
        'stream': build_stream_positions(all_rows),
    }

    os.makedirs(os.path.dirname(OUT_JS), exist_ok=True)
    with open(OUT_JS, 'w', encoding='utf-8') as f:
        f.write('// Auto-generated by scripts/pull_espn_historical_adp.py\n')
        f.write('// Historical ESPN redraft ADP vs actual PPR finish.\n')
        f.write('// Seasons: ' + ', '.join(str(s) for s in SEASONS) + '\n')
        f.write('// Re-run to refresh; bump the ?v= on the script tag after.\n')
        f.write('window.DRAFT_HISTORY=')
        json.dump(payload, f, separators=(',', ':'))
        f.write(';\n')

    print(f'\nwrote {OUT_JS} ({os.path.getsize(OUT_JS):,} bytes, '
          f'{len(all_rows):,} player-seasons)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
