#!/usr/bin/env python3
"""Refresh d.js "dk" fields (DraftKings best-ball ADP) from Occupy Fantasy's
public JSON API.

Source: https://www.occupyfantasyapi.com/best_ball/adps?site=draftkings
— the feed behind occupyfantasy.com/draftkings-best-ball-adp/ ("sponsored by
DraftKings, powered by SportsData.io", refreshed daily at 2pm ET). One
keyless GET. Found 2026-08-26; DK itself exposes no public ADP endpoint
(draftables carries no ADP, the pre-draft-rankings CSV needs a login — that
manual CSV is where the April "dk" values came from).

The feed's site_player_id matches DK's own player ids from that CSV
(verified: Bijan 1228244 in both), and curr_adp is the raw ADP decimal the
DK draft room shows — same scale d.js "dk" has always stored (2dp).

Skill positions only (QB/RB/WR/TE — DK best ball has no K/DST). Names are
resolved to d.js-canonical spelling via inject_rankings' norm/final_key
(same pattern as the KTC phase) plus a small alias map.

Safety rails (mirrors scripts/update_rosters.py):
  * aborts if the feed returns < 250 entries or its max_date is > 7 days old
  * aborts if < 250 entries resolve to d.js players (name-drift guard)
  * splices "dk" values surgically into the raw d.js text (no re-serialize):
    update in place, insert before the object's closing brace, and REMOVE
    stale "dk" fields on players the feed no longer carries — so one epoch
    of DK ADP is live at a time, never a mix
  * re-parses the result and verifies every change landed before writing

Usage:
  python scripts/update_dk_adp.py            # fetch, apply, bump ?v=
  python scripts/update_dk_adp.py --dry-run  # report only, change nothing
  python scripts/update_dk_adp.py --no-bump  # apply but skip the ?v= bump
                                             # (pipeline mode: caller bumps)

Runs standalone or as Phase L of scripts/pull_consensus_adp.py (9am job).
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

FEED_URL = ('https://www.occupyfantasyapi.com/best_ball/adps'
            '?site=draftkings&contest=all')
HEADERS = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/126.0.0.0 Safari/537.36'),
           'Referer': 'https://occupyfantasy.com/'}
MIN_ENTRIES = 250      # feed sanity floor (normally ~460)
MIN_MATCHED = 250      # d.js resolution floor (normally ~420)
MAX_AGE_DAYS = 7       # stale-feed guard on metadata.max_date
VALID_POS = {'QB', 'RB', 'WR', 'TE'}

# feed name -> d.js canonical name, for spellings normalization can't bridge.
DK_ALIASES = {
    'Kenny Gainwell': 'Kenneth Gainwell',
}

_NUM = r'-?[0-9.eE+]+'


def fetch_feed():
    r = requests.get(FEED_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    j = r.json()
    adps = j.get('adps') or []
    meta = j.get('metadata') or {}
    max_date = meta.get('max_date') or ''
    print(f'  feed: {len(adps)} entries, data through {max_date}')
    if len(adps) < MIN_ENTRIES:
        raise RuntimeError(f'only {len(adps)} entries (<{MIN_ENTRIES}) — aborting')
    try:
        age = (datetime.date.today() - datetime.date.fromisoformat(max_date)).days
    except ValueError:
        raise RuntimeError(f'malformed metadata.max_date {max_date!r} — aborting')
    if age > MAX_AGE_DAYS:
        raise RuntimeError(f'feed data is {age} days old ({max_date}) — aborting')
    return adps


def resolve_targets(adps, src):
    """Map d.js canonical player name -> ADP (2dp float). Lowest ADP wins if
    two feed rows collapse onto one d.js name."""
    sys.path.insert(0, ROOT)
    from inject_rankings import final_key

    names = re.findall(r'"n":"([^"]+)"', src)
    exact = set(names)
    norm_idx = {}
    for n in names:
        norm_idx.setdefault(final_key(n), n)

    targets, unmatched = {}, []
    for e in sorted(adps, key=lambda x: x.get('curr_adp') or 9999):
        name = (e.get('player_name') or '').strip()
        pos = e.get('pos')
        adp = e.get('curr_adp')
        if not name or pos not in VALID_POS or not isinstance(adp, (int, float)):
            continue
        name = DK_ALIASES.get(name, name)
        key = name if name in exact else norm_idx.get(final_key(name))
        if key is None:
            unmatched.append((name, pos))
            continue
        targets.setdefault(key, round(float(adp), 2))
    print(f'  resolved {len(targets)} d.js players '
          f'({len(unmatched)} feed names not in d.js)')
    if len(targets) < MIN_MATCHED:
        raise RuntimeError(
            f'only {len(targets)} matched (<{MIN_MATCHED}) — name drift? aborting')
    return targets


def player_object_spans(src):
    """Char spans of each top-level object in D=[...] (same walker as
    update_rosters.py / inject_rankings.py)."""
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


def parse_d(src):
    return json.JSONDecoder().raw_decode(src, src.index('['))[0]


def apply_dk(src, spans, d_arr, targets):
    """Splice desired "dk" values into every player object, most-offset-first.
    Returns (new_src, stats)."""
    stats = {'updated': 0, 'inserted': 0, 'removed': 0, 'unchanged': 0}
    edits = []  # (span, desired_literal_or_None, current_match)
    for idx, d in enumerate(d_arr):
        name, pos = d.get('n'), d.get('s')
        if pos not in VALID_POS or not name:
            continue
        desired = targets.get(name)
        s, e = spans[idx]
        body = src[s:e]
        m = re.search(r'"dk":' + _NUM, body)
        if desired is None and not m:
            continue
        if desired is not None and m and m.group(0) == f'"dk":{desired:.2f}':
            stats['unchanged'] += 1
            continue
        edits.append(((s, e), name, desired, bool(m)))

    for (s, e), name, desired, has in sorted(edits, key=lambda x: -x[0][0]):
        body = src[s:e]
        if desired is None:
            new_body, n = re.subn(r',"dk":' + _NUM, '', body, count=1)
            if n == 0:
                new_body, n = re.subn(r'"dk":' + _NUM + r',', '', body, count=1)
            if n == 0:
                raise RuntimeError(f'could not remove "dk" from {name}')
            stats['removed'] += 1
        elif has:
            new_body, n = re.subn(r'"dk":' + _NUM, f'"dk":{desired:.2f}', body, count=1)
            if n != 1:
                raise RuntimeError(f'could not update "dk" for {name}')
            stats['updated'] += 1
        else:
            new_body = body[:-1] + f',"dk":{desired:.2f}' + body[-1]
            stats['inserted'] += 1
        src = src[:s] + new_body + src[s:][e - s:]
    return src, stats


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
    args = ap.parse_args()

    print(f'DK best-ball ADP refresh {TODAY} (occupyfantasy feed -> d.js)')
    adps = fetch_feed()
    src = open(D_PATH, encoding='utf-8').read()
    targets = resolve_targets(adps, src)

    d_arr = parse_d(src)
    spans = player_object_spans(src)
    if len(spans) != len(d_arr):
        raise RuntimeError(
            f'object walker found {len(spans)} entries, JSON parse found '
            f'{len(d_arr)} — refusing to splice')

    new_src, stats = apply_dk(src, spans, d_arr, targets)
    print(f'  dk fields: {stats["updated"]} updated, {stats["inserted"]} inserted, '
          f'{stats["removed"]} removed, {stats["unchanged"]} unchanged')
    if new_src == src:
        print('DK ADP already current — no changes.')
        return
    if args.dry_run:
        print('Dry run — d.js not modified.')
        return

    # Verify before writing: re-parse and confirm every target landed.
    new_arr = parse_d(new_src)
    for d in new_arr:
        name, pos = d.get('n'), d.get('s')
        if pos not in VALID_POS or not name:
            continue
        want = targets.get(name)
        got = d.get('dk')
        if want is not None and got != want:
            raise RuntimeError(f'verification failed for {name} '
                               f'(want {want}, got {got}) — d.js not written')
        if want is None and got is not None:
            raise RuntimeError(f'verification failed for {name} '
                               f'(stale dk {got} survived) — d.js not written')

    open(D_PATH, 'w', encoding='utf-8').write(new_src)
    print('Wrote data/d.js')
    if not args.no_bump:
        bump_version()


if __name__ == '__main__':
    main()
