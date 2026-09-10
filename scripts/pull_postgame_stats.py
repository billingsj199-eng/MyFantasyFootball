#!/usr/bin/env python3
"""
Post-game 2026 weekly stats import -> data/weekly_stats_active.js

Runs after every game window (Task Scheduler "MFF Postgame Stats", wrapped
by scripts/postgame_stats.ps1) so game logs, L4 PPG and '26 PPG on the site
fill in the same night instead of waiting for the Tuesday full chain
(sim_lab/tuesday_stats.ps1 -> data/fetch_weekly_stats.py).

What it does
  1. ESPN scoreboard (curl UA only — browser UAs get 403) for every 2026
     regular-season week up to the current one: which games are FINAL and
     who played whom. Only players on a team whose game is final get a row,
     so a run that overlaps a live window never bakes partial box scores
     (Sleeper's stats endpoint is live during games).
  2. Sleeper /v1/stats/nfl/regular/2026/{week} for those weeks, mapped to
     D-array names the same way fetch_weekly_stats.py does. Since 2025
     Sleeper rows no longer carry team/opponent — both come from the
     Sleeper player DB (team) + the ESPN scoreboard pairing (opp).
  3. Merge into weekly_stats_active.js, 2026 season ONLY: a fresh row
     REPLACES the existing row for that player-week (stat corrections land;
     the Tuesday script's merge is existing-wins and never touches this).
     Every other season is passed through byte-for-byte.

Usage
  python scripts/pull_postgame_stats.py            # import + write
  python scripts/pull_postgame_stats.py --dry-run  # report only
  python scripts/pull_postgame_stats.py --week 3   # cap at week 3
Exit 0 = ok (stdout says whether the file changed), 1 = fetch failure.
"""

import argparse
import io
import json
import os
import sys
import time
from collections import defaultdict

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D_JS = os.path.join(ROOT, 'data', 'd.js')
WS_JS = os.path.join(ROOT, 'data', 'weekly_stats_active.js')

SEASON = 2026
SCOREBOARD = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'
SLEEPER_PLAYERS = 'https://api.sleeper.app/v1/players/nfl'
SLEEPER_STATS = 'https://api.sleeper.app/v1/stats/nfl/regular/{yr}/{wk}'
UA = {'User-Agent': 'curl/8.4.0', 'Accept': '*/*'}
# ESPN -> Sleeper/site abbreviations (only the ones that differ).
ABBR_FIX = {'WSH': 'WAS', 'JAC': 'JAX', 'LA': 'LAR', 'OAK': 'LV', 'SD': 'LAC'}


def log(msg):
    print(msg, flush=True)


def get_json(url, params=None, tries=3, timeout=25):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last = 'HTTP %s' % r.status_code
        except Exception as e:  # noqa: BLE001
            last = str(e)
        time.sleep(1.5 * (i + 1))
    raise RuntimeError('%s -> %s' % (url, last))


# ---------------------------------------------------------------- targets
def normalize(name):
    n = name.lower().strip()
    for ch in ('.', "'", '’'):
        n = n.replace(ch, '')
    return n


SUFFIXES = (' jr', ' sr', ' iii', ' ii', ' iv')


def strip_suffix(n):
    for s in SUFFIXES:
        if n.endswith(s):
            return n[: -len(s)].strip()
    return n


def load_targets():
    with open(D_JS, 'r', encoding='utf-8') as f:
        raw = f.read()
    D = json.loads(raw[raw.index('['):raw.rindex(']') + 1])
    return {p['n']: p['s'] for p in D if p.get('s') in ('QB', 'RB', 'WR', 'TE')}


def sleeper_id_map(targets):
    """D name -> (sleeper_id, team) using the Sleeper player DB."""
    db = get_json(SLEEPER_PLAYERS, timeout=60)
    by_name = {}
    for sid, sp in db.items():
        if sp.get('position') not in ('QB', 'RB', 'WR', 'TE'):
            continue
        full = sp.get('full_name') or ('%s %s' % (sp.get('first_name', ''), sp.get('last_name', ''))).strip()
        if not full:
            continue
        key = normalize(full)
        if key not in by_name or sp.get('active'):
            by_name[key] = (sid, sp.get('team') or '')
    out = {}
    for name in targets:
        key = normalize(name)
        hit = by_name.get(key)
        if not hit:
            st = strip_suffix(key)
            hit = by_name.get(st) if st != key else None
            if not hit:
                for s in SUFFIXES:
                    if (key + s) in by_name:
                        hit = by_name[key + s]
                        break
        if hit:
            out[name] = hit
    return out


# ---------------------------------------------------------------- ESPN
def scoreboard(week=None):
    # No params = ESPN's own "current" week (carries the top-level season).
    # A bare dates=2026 drops the season key and returns a 100-event mix of
    # seasons, so a specific week is always asked for with all three params.
    params = {'dates': SEASON, 'seasontype': 2, 'week': week} if week else None
    return get_json(SCOREBOARD, params=params)


def final_games(sb, week):
    """{team: opp} for every FINAL game in a scoreboard payload; plus counts."""
    finals, total = {}, 0
    for ev in sb.get('events', []):
        es, ew = ev.get('season') or {}, ev.get('week') or {}
        if es.get('year') != SEASON or es.get('type') != 2 or ew.get('number') != week:
            continue
        total += 1
        st = (ev.get('status') or {}).get('type') or {}
        comp = (ev.get('competitions') or [{}])[0]
        teams = [c.get('team', {}).get('abbreviation', '') for c in comp.get('competitors', [])]
        teams = [ABBR_FIX.get(t, t) for t in teams if t]
        if len(teams) != 2:
            continue
        if st.get('completed') or st.get('name') == 'STATUS_FINAL':
            finals[teams[0]] = teams[1]
            finals[teams[1]] = teams[0]
    return finals, total


# ---------------------------------------------------------------- Sleeper rows
def build_row(pos, wk, tm, opp, s):
    fpts = round(s.get('pts_half_ppr', 0) or 0, 1)

    def i(k):
        v = s.get(k, 0) or 0
        return int(v) if float(v).is_integer() else v

    if pos == 'QB':
        return {'wk': wk, 'tm': tm, 'opp': opp, 'fpts': fpts,
                'py': i('pass_yd'), 'ptd': i('pass_td'), 'int': i('pass_int'),
                'pa': i('pass_att'), 'pc': i('pass_cmp'),
                'ry': i('rush_yd'), 'rtd': i('rush_td'), 'ra': i('rush_att'),
                'fl': i('fum_lost')}
    return {'wk': wk, 'tm': tm, 'opp': opp, 'fpts': fpts,
            'ra': i('rush_att'), 'ry': i('rush_yd'), 'rtd': i('rush_td'),
            'rec': i('rec'), 'rcy': i('rec_yd'), 'rctd': i('rec_td'),
            'tgt': i('rec_tgt'), 'fl': i('fum_lost')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--week', type=int, default=None, help='cap at this week (default: ESPN current week)')
    args = ap.parse_args()

    targets = load_targets()
    log('targets: %d QB/RB/WR/TE in d.js' % len(targets))

    cur = scoreboard()
    cur_week = int((cur.get('week') or {}).get('number') or 0)
    season_yr = int(((cur.get('season') or {}).get('year')) or 0)
    season_type = int(((cur.get('season') or {}).get('type')) or 0)
    if season_yr != SEASON or season_type != 2 or cur_week < 1:
        log('ESPN says season %s type %s week %s - not the %d regular season, nothing to import' % (season_yr, season_type, cur_week, SEASON))
        return 0
    last_week = min(cur_week, args.week) if args.week else cur_week
    log('ESPN current week: %d (importing weeks 1-%d)' % (cur_week, last_week))

    idmap = sleeper_id_map(targets)
    log('sleeper ids matched: %d/%d' % (len(idmap), len(targets)))
    by_sid = {sid: (name, team) for name, (sid, team) in idmap.items()}

    # week -> {name: row}
    new_rows = defaultdict(dict)
    for wk in range(1, last_week + 1):
        sb = cur if wk == cur_week else scoreboard(wk)
        finals, total = final_games(sb, wk)
        n_final = len(finals) // 2
        if not finals:
            log('  W%d: 0/%d games final - skipped' % (wk, total))
            continue
        stats = get_json(SLEEPER_STATS.format(yr=SEASON, wk=wk))
        kept = skipped_live = 0
        for sid, s in stats.items():
            hit = by_sid.get(sid)
            if not hit:
                continue
            name, team = hit
            gp = s.get('gp', 0) or 0
            if not gp and not (s.get('pts_half_ppr') or 0):
                continue
            if team not in finals:
                skipped_live += 1   # game not final yet (or player teamless)
                continue
            new_rows[wk][name] = build_row(targets[name], wk, team, finals[team], s)
            kept += 1
        log('  W%d: %d/%d games final - %d player rows kept, %d held (game not final)' % (wk, n_final, total, kept, skipped_live))
        time.sleep(0.2)

    # ------------------------------------------------------------ merge
    with open(WS_JS, 'r', encoding='utf-8') as f:
        raw = f.read()
    head = raw[:raw.index('{')]
    existing = json.loads(raw[raw.index('{'):raw.rindex('}') + 1])
    yr = str(SEASON)
    added = replaced = unchanged = 0
    for wk, rows in new_rows.items():
        for name, row in rows.items():
            entry = existing.get(name)
            if entry is None:
                entry = existing[name] = {'pos': targets[name], 'seasons': {}}
            weeks = entry['seasons'].setdefault(yr, [])
            idx = next((i for i, w in enumerate(weeks) if w.get('wk') == wk), None)
            if idx is None:
                weeks.append(row)
                added += 1
            elif weeks[idx] != row:
                weeks[idx] = row
                replaced += 1
            else:
                unchanged += 1
            weeks.sort(key=lambda w: w.get('wk', 0))

    out = {k: existing[k] for k in sorted(existing)}
    js = head + json.dumps(out, separators=(',', ':')) + ';'
    changed = js != raw
    log('merge: %d rows added, %d replaced (corrections), %d unchanged -> %s' % (
        added, replaced, unchanged, 'FILE CHANGED' if changed else 'no change'))
    if args.dry_run:
        log('dry run - not written')
        return 0
    if changed:
        with open(WS_JS, 'w', encoding='utf-8') as f:
            f.write(js)
        log('wrote %s (%.1f MB)' % (WS_JS, len(js) / 1048576))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        log('FAILED: %s' % e)
        sys.exit(1)
