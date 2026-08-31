#!/usr/bin/env python3
"""Audit + fix the ESPN headshot ids baked into d.js "_slImg".

The 2026-08-04 boot-cost bake wrote wrong ESPN ids for ~40-83 players
(shuffled across players: Gibbs carried Breece Hall's id, Kenneth Walker III
the retired WR Kenneth Walker's, etc.), so every surface rendering _slImg —
rankings rows, player cards, /p/ SEO pages, the movers OG card — shows the
wrong face. Nothing in the daily pipeline rewrites _slImg, so d.js is the
one place to fix.

Verification contract (Sleeper alone is NOT sufficient — ~341 records lack
espn_id, and Sleeper's own espn_id is occasionally stale):
  * baked id == Sleeper espn_id (name+pos matched, active only)  -> trusted
  * disagreement or no Sleeper id -> ESPN athlete API must confirm the baked
    id resolves to this player (normalized displayName + position match)
  * baked id refuted -> candidate = Sleeper espn_id if present, else ESPN
    search-v2 by name; EVERY candidate is confirmed via the athlete API
    (name+pos) before it is written. Unverifiable players are logged and
    left untouched.

Splicing is surgical (same span walker as update_rosters.py): only the
/full/<id>.png inside each player's own object changes, the result re-parses,
and every change is verified in the re-parse before writing.

Usage:
  python scripts/fix_headshot_ids.py              # dry-run report (default)
  python scripts/fix_headshot_ids.py --write      # apply + bump d.js ?v=
  python scripts/fix_headshot_ids.py --write --no-bump
"""

import argparse
import json
import re
import sys
import time

import requests

from update_rosters import (
    D_PATH, NAME_ALIASES, build_indexes, fetch_sleeper, norm_name, norm_pos,
    parse_d, player_object_spans, bump_version,
)

ATHLETE_URL = ('https://site.web.api.espn.com/apis/common/v3/sports/'
               'football/nfl/athletes/{id}')
SEARCH_URL = ('https://site.web.api.espn.com/apis/search/v2'
              '?region=us&lang=en&limit=10&query={q}')
SLEEP = 0.15
MAX_CHANGES_DEFAULT = 120  # ledger says ~83; abort if wildly more

_athlete_cache = {}


def espn_athlete(eid):
    """(displayName, pos_abbr) or None if the id doesn't resolve."""
    if eid in _athlete_cache:
        return _athlete_cache[eid]
    time.sleep(SLEEP)
    try:
        r = requests.get(ATHLETE_URL.format(id=eid), timeout=15)
        if r.status_code != 200:
            _athlete_cache[eid] = None
            return None
        a = r.json().get('athlete') or {}
        info = (a.get('displayName'),
                ((a.get('position') or {}).get('abbreviation') or '').upper())
        _athlete_cache[eid] = info
        return info
    except Exception:
        _athlete_cache[eid] = None
        return None


def athlete_matches(eid, name, pos):
    info = espn_athlete(eid)
    if not info or not info[0]:
        return False
    dn, ppos = info
    if norm_name(dn) != norm_name(name):
        return False
    # ESPN pos can be blank for long-retired ids — a blank never confirms.
    return norm_pos(ppos) == norm_pos(pos)


def espn_search_id(name, pos):
    """Resolve name -> ESPN id via search-v2; only NFL player hits; the
    winning candidate must still pass athlete_matches()."""
    time.sleep(SLEEP)
    try:
        r = requests.get(SEARCH_URL.format(q=requests.utils.quote(name)),
                         timeout=15)
        if r.status_code != 200:
            return None
        j = r.json()
    except Exception:
        return None
    cands = []
    for sec in j.get('results', []):
        if sec.get('type') != 'player':
            continue
        for item in sec.get('contents', []):
            uid = item.get('uid') or ''
            if '~l:28~' not in uid and not uid.endswith('l:28'):
                # l:28 = NFL; skip college/other-league players
                if 'l:28' not in uid:
                    continue
            m = re.search(r'a:(\d+)', uid)
            if m:
                cands.append((item.get('displayName') or '', m.group(1)))
    # exact normalized name first, then anything else in order
    cands.sort(key=lambda c: 0 if norm_name(c[0]) == norm_name(name) else 1)
    for _dn, eid in cands:
        if athlete_matches(eid, name, pos):
            return eid
    return None


def baked_id(d):
    m = re.search(r'/full/(\d+)\.png', d.get('_slImg') or '')
    return m.group(1) if m else None


def sleeper_espn_id(d, by_name):
    name = NAME_ALIASES.get(d['n'], d['n'])
    cands = by_name.get((norm_name(name), norm_pos(d.get('s'))), [])
    if len(cands) == 1 and cands[0].get('espn_id'):
        return str(cands[0]['espn_id'])
    return None


def audit(d_arr, by_name):
    changes, suspect_unfixed, confirmed_by_espn = [], [], 0
    agree = 0
    for d in d_arr:
        if d.get('s') == 'DST' or not d.get('n'):
            continue
        bid = baked_id(d)
        if not bid:
            continue
        name, pos = d['n'], d.get('s')
        s_eid = sleeper_espn_id(d, by_name)
        if s_eid and s_eid == bid:
            agree += 1
            continue
        # Sleeper disagrees or is silent: the baked id must prove itself.
        if athlete_matches(bid, NAME_ALIASES.get(name, name), pos):
            confirmed_by_espn += 1
            continue
        # Baked id refuted. Find a verified replacement.
        new_id = None
        if s_eid and athlete_matches(s_eid, NAME_ALIASES.get(name, name), pos):
            new_id, how = s_eid, 'sleeper'
        else:
            new_id = espn_search_id(NAME_ALIASES.get(name, name), pos)
            how = 'espn-search'
        if new_id and new_id != bid:
            info = _athlete_cache.get(new_id)
            changes.append({'n': name, 's': pos, 'old': bid, 'new': new_id,
                            'how': how, 'espn_name': info[0] if info else '?'})
        else:
            suspect_unfixed.append((name, pos, bid))
    return changes, suspect_unfixed, agree, confirmed_by_espn


def apply_changes(src, spans, d_arr, changes):
    by_key = {}
    for idx, d in enumerate(d_arr):
        by_key.setdefault((d.get('n'), d.get('s')), idx)
    edits = []
    for ch in changes:
        idx = by_key.get((ch['n'], ch['s']))
        if idx is None or idx >= len(spans):
            raise RuntimeError(f"lost track of {ch['n']} while splicing")
        edits.append((spans[idx], ch))
    for (s, e), ch in sorted(edits, key=lambda x: -x[0][0]):
        body = src[s:e]
        old_lit = f"/full/{ch['old']}.png"
        new_lit = f"/full/{ch['new']}.png"
        if body.count(old_lit) != 1:
            raise RuntimeError(
                f"expected exactly one {old_lit} in {ch['n']}'s object, "
                f"found {body.count(old_lit)}")
        src = src[:s] + body.replace(old_lit, new_lit, 1) + src[e:]
    return src


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--write', action='store_true',
                    help='apply fixes to d.js (default: dry-run report)')
    ap.add_argument('--no-bump', action='store_true',
                    help='with --write: skip the index.html ?v= bump')
    ap.add_argument('--max-changes', type=int, default=MAX_CHANGES_DEFAULT)
    args = ap.parse_args()

    src = open(D_PATH, encoding='utf-8').read()
    d_arr = parse_d(src)
    print(f'  d.js: {len(d_arr)} players')
    by_name, _by_espn = build_indexes(fetch_sleeper())

    changes, unfixed, agree, espn_ok = audit(d_arr, by_name)
    print(f'\n  baked==sleeper agreement : {agree}')
    print(f'  confirmed via ESPN API   : {espn_ok}')
    print(f'  WRONG ids (fix found)    : {len(changes)}')
    print(f'  refuted but unresolvable : {len(unfixed)}')
    for ch in changes:
        print(f"    {ch['n']:<28} {ch['s']:<3} {ch['old']:>8} -> {ch['new']:<8}"
              f" [{ch['how']}] espn={ch['espn_name']}")
    if unfixed:
        print('  UNRESOLVED (left untouched):')
        for n, p, b in unfixed:
            print(f'    {n:<28} {p:<3} baked={b}')

    if not changes:
        print('  nothing to fix')
        return
    if len(changes) > args.max_changes:
        raise RuntimeError(
            f'{len(changes)} changes > --max-changes {args.max_changes} — '
            'refusing (bad payload or matching bug?)')
    if not args.write:
        print('\n  dry-run only — rerun with --write to apply')
        return

    spans = player_object_spans(src)
    new_src = apply_changes(src, spans, d_arr, changes)
    # Verify: re-parse and check every change landed.
    new_arr = parse_d(new_src)
    check = {(d.get('n'), d.get('s')): baked_id(d) for d in new_arr}
    for ch in changes:
        got = check.get((ch['n'], ch['s']))
        if got != ch['new']:
            raise RuntimeError(f"verify failed for {ch['n']}: {got}")
    open(D_PATH, 'w', encoding='utf-8', newline='').write(new_src)
    print(f'\n  wrote {len(changes)} fixes to d.js (re-parse verified)')
    if not args.no_bump:
        bump_version()


if __name__ == '__main__':
    sys.exit(main())
