#!/usr/bin/env python3
"""
PFF Premium weekly receiving exports -> E:\\MyFantasyFootball\\pbp_cache\\pff\\weekly\\
    pff_receiving_<season>_w<N>.csv          (one file per completed week)
    pff_<facet>_<season>_w<N>.csv            scheme/alignment facets (see FACETS below)
    pff_<facet>_<season-1>_w<N>.csv          prior-season weekly facets (fetched once; the comparison prior)

These are the files scripts/pull_route_pct.py turns into the REAL current-season
RT% column (routes / team dropbacks). Without them the card shows a ~estimate
built from snap share (see estimate_from_snaps there).

HOW IT WORKS (official PFF Developer API since 2026-10-05; PFF closed the
Premium site's own table API to scripts on 2026-10-03 - it now answers HTTP 403
invalid_client_token to anything but the site's own pages):
  * https://api.pff.com/v1/facet/... mirrors the old site paths and parameters
    exactly (league, season, week; same JSON, key receiving_summary; fields =
    the receiving_summary CSV columns: player, player_id, position, team_name,
    routes, route_rate, targets, ...). Docs: https://developer.pff.com
  * Needs a PFF Pro subscription and an API key (www.pff.com/account/api-keys),
    sent as `Authorization: Bearer <key>`. The key is read from the PFF_API_KEY
    environment variable or from pbp_cache/pff/api_key.txt (outside the repo -
    never commit it, never print it).
  * Every account has a per-minute read budget; the x-ratelimit-* response
    headers are honoured and a 429 waits out its Retry-After.
  * Weeks: --weeks auto (default) walks 1..18 and stops at the first week PFF
    returns no rows. Existing files are kept unless they are one of the
    newest --refetch weeks (PFF re-grades for a day or two) or --all is given.

Run from the project root:
    python scripts/pull_pff_weekly.py                 # current season, auto weeks
    python scripts/pull_pff_weekly.py --weeks 1,2 --all
Exit codes: 0 ok (even if nothing new), 2 = no key / key refused (no files touched), 1 = error.
"""
import argparse, csv, datetime as dt, io, json, os, sys, time
import urllib.error, urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CACHE = r'E:\MyFantasyFootball\pbp_cache'
PFF_DIR = os.path.join(CACHE, 'pff')
PFF_WEEKLY = os.path.join(PFF_DIR, 'weekly')
KEY_FILE = os.path.join(PFF_DIR, 'api_key.txt')
API_BASE = 'https://api.pff.com'
API = API_BASE + '/v1/facet/receiving/summary?league=nfl&season={season}&week={week}'
# receiving/summary only lists players with >= 1 TARGET that week (Ridley 64%
# snaps / 0 targets = no row). offense/summary lists everyone who took a snap
# with snap_counts_pass_route (= routes run) so zero-target route runners get a
# row too (routes only; no route_rate/grades - pull_route_pct.py divides by
# nflverse dropbacks anyway).
API_OFF = API_BASE + '/v1/facet/offense/summary?league=nfl&season={season}&week={week}'
# SCHEME / ALIGNMENT facets (2026-09-15, Jack: "where each defense gets targeted or
# what type of runs outside/inside... maybe pff"). PFF serves these weekly in-season
# (probe 2026-09-15: HTTP 200 for every entry below; rushing/gap_zone,
# passing/time_in_pocket, defense/run_defense, defense/slot_coverage and blocking/*
# are 404 and NOT requested). One CSV per facet per week:
#     pff_<key>_<season>_w<N>.csv
# Consumers: E:\MyFantasyFootball\sim_lab\build_scheme.py (team + player scheme
# cards on the Sim Lab ZONES / NOTES tabs). Nested values (rushing/direction
# "directions") are flattened to <col>_<key>[_<sub>] columns; lists become JSON.
FACET_API = API_BASE + '/v1/facet/{facet}?league=nfl&season={season}&week={week}'
FACETS = [
    ('receiving_scheme', 'receiving/scheme'),          # per receiver man/zone routes, targets, yprr
    ('receiving_depth', 'receiving/depth'),            # per receiver depth x side splits (509 cols)
    ('receiving_concept', 'receiving/concept'),        # per receiver screen / slot splits
    ('rushing_summary', 'rushing/summary'),            # gap vs zone attempts, yco, breakaway, elusive
    ('rushing_direction', 'rushing/direction'),        # carries by direction (left/mid/right end/tackle/guard)
    ('passing_pressure', 'passing/pressure'),          # per QB blitz / pressure dropback splits
    ('defense_summary', 'defense/summary'),            # per defender alignment snaps (box/slot/corner/DL gaps), grades
    ('defense_coverage_scheme', 'defense/coverage_scheme'),  # per defender man vs zone coverage snaps + results
    ('defense_pass_rush', 'defense/pass_rush'),        # per rusher pass-rush win rate / pressures
]
FACET_LEAD = ['season', 'week', 'player', 'player_id', 'position', 'team_name', 'franchise_id', 'player_game_count']
# PFF Pro /v2 single-week tables (2026-10-05, Research additions): league-wide player reports
# (graded-play rates, completion / accuracy / catch over expected, EPA without play action or
# screens, offensive snaps, line pass-block win rate) and team tables (run game, pressure over
# expectation). Same file naming: pff_<key>_<season>_w<N>.csv; player rows get player_id /
# team_name like the facets, team rows team_name. Consumer: scripts/build_adv_stats.py.
V2_API = API_BASE + '/v2/nfl/positions/reports/{report}?season={season}&weekGroup=REG&week={week}'
TEAM_API = API_BASE + '/v2/nfl/teams/stats?season={season}&weekIds={week}&category={cat}'
V2_REPORTS = [('v2_passing', 'passing'), ('v2_receiving', 'receiving'), ('v2_rushing', 'rushing'),
              ('v2_offense', 'offense'), ('v2_pass_blocking', 'pass-blocking')]
TEAM_TABLES = [('team_offense_rushing', 'offense-rushing'), ('team_offense_passing', 'offense-passing'),
               ('team_defense_rushing', 'defense-rushing')]
V2_LEAD = ['season', 'week', 'player', 'player_id', 'position', 'team_name']
TEAM_LEAD = ['season', 'week', 'team_name']
# Column order of the season exports already in pbp_cache/pff (kept identical so
# every consumer can read both shapes); anything else PFF sends is appended.
LEAD_COLS = ['season', 'player', 'player_id', 'position', 'team_name', 'player_game_count', 'routes',
             'route_rate', 'targets', 'receptions', 'yards', 'touchdowns', 'yprr', 'avg_depth_of_target',
             'grades_pass_route', 'grades_offense', 'slot_rate', 'wide_rate', 'inline_rate',
             'yards_after_catch_per_reception', 'contested_catch_rate', 'drop_rate', 'caught_percent',
             'first_downs', 'avoided_tackles']


def _load_key():
    """PFF API key from PFF_API_KEY or pbp_cache/pff/api_key.txt; None when absent."""
    key = (os.environ.get('PFF_API_KEY') or '').strip()
    if not key and os.path.exists(KEY_FILE):
        with open(KEY_FILE, encoding='utf-8-sig') as f:
            key = f.read().strip()
    return key or None


def _api_fetch(key, url, tries=4):
    """GET with the API key. -> (status, text). Waits out the per-minute budget."""
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json',
                                               'User-Agent': 'mff-pff-pull/1.0'})
    status, body = 0, ''
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                status, body, hdr = r.status, r.read().decode('utf-8', 'replace'), r.headers
        except urllib.error.HTTPError as e:
            status, body, hdr = e.code, e.read().decode('utf-8', 'replace'), e.headers
        except (urllib.error.URLError, TimeoutError) as e:
            return 0, str(e)
        if status in (429, 503) and attempt < tries - 1:
            try:
                wait = float(hdr.get('Retry-After') or 20)
            except ValueError:
                wait = 20
            time.sleep(min(max(wait, 1), 90))
            continue
        if hdr.get('x-ratelimit-remaining') == '0':
            try:
                time.sleep(min(max(float(hdr.get('x-ratelimit-reset')) - time.time(), 0), 65))
            except (TypeError, ValueError):
                time.sleep(5)
        break
    return status, body


def _err(body):
    """error.code (+ details.reason) from the API's JSON error envelope, '' when it is not one."""
    try:
        e = json.loads(body).get('error')
    except (ValueError, AttributeError):
        return ''
    if isinstance(e, dict):
        return ' '.join(str(x) for x in (e.get('code'), (e.get('details') or {}).get('reason')) if x)
    return str(e or '')


def _rows(body):
    """Pull the row list out of PFF's response ({receiving_summary:[...]} or a bare list)."""
    try:
        j = json.loads(body)
    except ValueError:
        return None
    if isinstance(j, list):
        return j
    if isinstance(j, dict):
        for k in ('receiving_summary', 'data', 'rows'):
            if isinstance(j.get(k), list):
                return j[k]
        for v in j.values():
            if isinstance(v, list):
                return v
    return None


def _probe(key, season):
    """-> rows for week 1, or None when the key is refused / the account is not
    entitled. An unentitled caller can get HTTP 200 with the box-score columns
    only, so "entitled" = at least one row carries a `routes` key."""
    status, body = _api_fetch(key, API.format(season=season, week=1))
    if status != 200:
        return None, f'{status} {_err(body)}'.strip()
    rows = _rows(body)
    if not isinstance(rows, list) or not any('routes' in r for r in rows if isinstance(r, dict)):
        return None, f'{status} (no premium fields - account not entitled)'
    return rows, status


def _add_zero_target_routes(key, season, week, live):
    """Append players who ran routes but drew no target (absent from
    receiving/summary) using offense/summary snap_counts_pass_route."""
    status, body = _api_fetch(key, API_OFF.format(season=season, week=week))
    if status != 200:
        print(f'  week {week}: offense/summary HTTP {status} - zero-target route runners not added')
        return live
    off = _rows(body) or []
    # One definition for everyone: `routes` = pass-route SNAPS (on the field
    # running a route on any dropback, sacks/scrambles included) - the analog of
    # the 2016-25 nflverse participation proxy and of the nflverse-dropback
    # denominator pull_route_pct.py uses. PFF's targeted-table `routes` (a
    # touch lower: Olave 55 vs 59 in 2026 W1) is kept as routes_pff.
    by_id = {o.get('player_id'): o for o in off}
    have = {r.get('player_id') for r in live}
    swapped = 0
    for r in live:
        o = by_id.get(r.get('player_id'))
        if o and o.get('snap_counts_pass_route'):
            r['routes_pff'] = r.get('routes')
            r['routes'] = o['snap_counts_pass_route']
            swapped += 1
    added = 0
    for o in off:
        rt = o.get('snap_counts_pass_route') or 0
        if o.get('player_id') in have or not rt:
            continue
        live.append({'player': o.get('player'), 'player_id': o.get('player_id'), 'position': o.get('position'),
                     'team_name': o.get('team_name') or o.get('team'), 'player_game_count': o.get('player_game_count'),
                     'routes': rt, 'targets': 0, 'receptions': 0, 'yards': 0, 'touchdowns': 0,
                     'franchise_id': o.get('franchise_id')})
        added += 1
    print(f'  week {week}: routes = pass-route snaps for {swapped} targeted players, +{added} zero-target route runners '
          f'(offense/summary {len(off)} rows)')
    return live


def _flatten(row):
    """One level of nesting -> flat columns (rushing/direction ships a `directions`
    dict); lists are kept as JSON text so nothing is lost."""
    out = {}
    for k, v in row.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                if isinstance(v2, dict):
                    for k3, v3 in v2.items():
                        out[f'{k}_{k2}_{k3}'] = json.dumps(v3) if isinstance(v3, (dict, list)) else v3
                else:
                    out[f'{k}_{k2}'] = json.dumps(v2) if isinstance(v2, list) else v2
        elif isinstance(v, list):
            out[k] = json.dumps(v)
        else:
            out[k] = v
    return out


def pull_prior_season(key, season, force=False):
    """PRIOR season, weeks 1-18, every facet + receiving/summary (saved as
    receiving_summary so pull_route_pct.py's pff_receiving_<yr>_w* glob never sees
    it) -> pff_<facet>_<prior>_w<N>.csv. Skips files already on disk, so after the
    first run this costs one probe. build_scheme.py compares each defense's / player's
    current profile with last season and flags what carried over."""
    prior = season - 1
    done, missing = [], 0
    for wk in range(1, 19):
        for fkey, facet in FACETS + [('receiving_summary', 'receiving/summary')]:
            path = facet_path(fkey, prior, wk)
            if os.path.exists(path) and not force:
                continue
            status, body = _api_fetch(key, FACET_API.format(facet=facet, season=prior, week=wk))
            rows = _rows(body) if status == 200 else None
            if not isinstance(rows, list) or not rows:
                print(f'  {prior} week {wk}: {facet} HTTP {status} - skipped')
                missing += 1
                continue
            _write_csv(path, prior, wk, [_flatten(r) for r in rows if isinstance(r, dict)], lead=FACET_LEAD)
            done.append((wk, fkey))
            time.sleep(0.5)
    if done:
        print(f'  {prior} weekly facets: wrote {len(done)} files' + (f', {missing} skipped' if missing else ''))
    return done


def facet_path(key, season, week):
    return os.path.join(PFF_WEEKLY, f'pff_{key}_{season}_w{week}.csv')


def pull_facets(key, season, week, force=False):
    """Fetch every FACETS entry for one played week; skip files that already exist
    unless force. -> list of (key, rows) written."""
    done = []
    for fkey, facet in FACETS:
        path = facet_path(fkey, season, week)
        if os.path.exists(path) and not force:
            continue
        status, body = _api_fetch(key, FACET_API.format(facet=facet, season=season, week=week))
        if status != 200:
            print(f'  week {week}: {facet} HTTP {status} - skipped')
            continue
        rows = _rows(body)
        if not isinstance(rows, list):
            print(f'  week {week}: {facet} unreadable - skipped')
            continue
        rows = [_flatten(r) for r in rows if isinstance(r, dict)]
        _write_csv(path, season, week, rows, lead=FACET_LEAD)
        done.append((fkey, len(rows)))
        time.sleep(0.6)
    if done:
        print(f'  week {week}: facets ' + ', '.join(f'{k} {n}' for k, n in done))
    return done


def _v2_rows(body, team_table):
    """/v2 {columns, rows} body -> rows with the facet identity columns added."""
    try:
        j = json.loads(body)
    except ValueError:
        return None
    rows = j.get('rows') if isinstance(j, dict) else None
    if not isinstance(rows, list):
        return None
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        r = dict(r)
        if team_table:
            r['team_name'] = r.get('abbreviation')
        else:
            r['player_id'] = r.get('playerId')
            r['team_name'] = r.get('teamAbbreviation') or r.get('team') or r.get('teamName')
        out.append(r)
    return out


def pull_v2(key, season, week, force=False, quiet=False):
    """Every V2_REPORTS + TEAM_TABLES entry for one played week. -> list of (key, rows) written."""
    done = []
    for fkey, rep in V2_REPORTS + TEAM_TABLES:
        team_table = fkey.startswith('team_')
        path = facet_path(fkey, season, week)
        if os.path.exists(path) and not force:
            continue
        url = (TEAM_API.format(season=season, week=week, cat=rep) if team_table
               else V2_API.format(report=rep, season=season, week=week))
        status, body = _api_fetch(key, url)
        rows = _v2_rows(body, team_table) if status == 200 else None
        if rows is None:
            print(f'  {season} week {week}: {rep} HTTP {status} {_err(body)} - skipped')
            continue
        _write_csv(path, season, week, rows, lead=TEAM_LEAD if team_table else V2_LEAD)
        done.append((fkey, len(rows)))
    if done and not quiet:
        print(f'  week {week}: v2 ' + ', '.join(f'{k} {n}' for k, n in done))
    return done


def backfill_v2(key, years):
    """One-off: the /v2 week files for past seasons (Research's Past Seasons view). Six requests
    in flight - each report takes ~5 s server-side, the budget is 100 reads / minute."""
    from concurrent.futures import ThreadPoolExecutor
    jobs = [(y, w) for y in years for w in range(1, (17 if y <= 2020 else 18) + 1)]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, done in enumerate(ex.map(lambda j: pull_v2(key, j[0], j[1], quiet=True), jobs), 1):
            if i % 20 == 0:
                print(f'  backfill {i}/{len(jobs)} weeks ({time.time() - t0:.0f}s)', flush=True)
    print(f'v2 backfill {years[0]}-{years[-1]}: {len(jobs)} weeks checked ({time.time() - t0:.0f}s)')


def _write_csv(path, season, week, rows, lead=None):
    cols = list(lead or LEAD_COLS)
    for r in rows:
        for k in r.keys():
            if k not in cols:
                cols.append(k)
    tmp = path + '.tmp'
    with open(tmp, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            r = dict(r)
            r.setdefault('season', season)
            r.setdefault('week', week)
            w.writerow({k: ('' if r.get(k) is None else r.get(k)) for k in cols})
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, default=None, help='default = current NFL season (Sep-Dec year)')
    ap.add_argument('--weeks', default='auto', help='auto | comma list (1,2,3)')
    ap.add_argument('--all', action='store_true', help='refetch every week, not just the newest --refetch')
    ap.add_argument('--refetch', type=int, default=2, help='always refetch this many newest existing weeks')
    ap.add_argument('--login-wait', type=int, default=300, help='ignored (kept so old job command lines still parse)')
    ap.add_argument('--no-facets', action='store_true', help='skip the scheme/alignment facet files (receiving only)')
    ap.add_argument('--prior-refetch', action='store_true', help='refetch the prior-season weekly facet files')
    ap.add_argument('--v2-backfill', default=None, help='YYYY-YYYY: only fill missing /v2 week files for those seasons')
    a = ap.parse_args()
    today = dt.date.today()
    season = a.season or (today.year if today.month >= 8 else today.year - 1)
    os.makedirs(PFF_WEEKLY, exist_ok=True)

    existing = {}
    for f in os.listdir(PFF_WEEKLY):
        if f.startswith(f'pff_receiving_{season}_w') and f.endswith('.csv'):
            try:
                existing[int(f[len(f'pff_receiving_{season}_w'):-4])] = os.path.join(PFF_WEEKLY, f)
            except ValueError:
                pass
    print(f'PFF weekly {season}: existing weeks {sorted(existing) or "none"}')

    key = _load_key()
    if not key:
        print(f'PFF API KEY MISSING - save a key from www.pff.com/account/api-keys to {KEY_FILE} '
              f'(or set PFF_API_KEY); no files written.')
        return 2
    rows1, status = _probe(key, season)
    if rows1 is None:
        print(f'PFF API REFUSED ({status}) - no files written; the RT% column keeps its snap-share estimate.')
        return 2
    print(f'api key ok: week 1 rows={len(rows1)}')
    if a.v2_backfill:
        y0, _, y1 = a.v2_backfill.partition('-')
        backfill_v2(key, list(range(int(y0), int(y1 or y0) + 1)))
        return 0

    if a.weeks == 'auto':
        todo_all = list(range(1, 19))
    else:
        todo_all = [int(w) for w in a.weeks.split(',')]
    keep_from = (max(existing) - a.refetch + 1) if existing and not a.all else None
    written, kept = [], []
    for wk in todo_all:
        if wk in existing and not a.all and (keep_from is None or wk < keep_from):
            kept.append(wk)
            continue
        if wk == 1:
            rows = rows1
        else:
            status, body = _api_fetch(key, API.format(season=season, week=wk))
            if status != 200:
                print(f'  week {wk}: HTTP {status} - stop')
                break
            rows = _rows(body)
            if rows is None:
                print(f'  week {wk}: unreadable response - stop')
                break
        # PFF returns rows with 0 routes for weeks that have not been played;
        # a week counts as "in" once anyone ran a route.
        live = [r for r in rows if (r.get('routes') or 0)]
        if live:
            live = _add_zero_target_routes(key, season, wk, live)
        if not live:
            if a.weeks == 'auto':
                print(f'  week {wk}: no routes yet - stop')
                break
            print(f'  week {wk}: no routes yet - skipped')
            continue
        _write_csv(os.path.join(PFF_WEEKLY, f'pff_receiving_{season}_w{wk}.csv'), season, wk, live)
        written.append((wk, len(live)))
        print(f'  week {wk}: {len(live)} players with routes -> pff_receiving_{season}_w{wk}.csv')
        if not a.no_facets:
            pull_facets(key, season, wk, force=True)
            pull_v2(key, season, wk, force=True)
        time.sleep(1.0)
    # scheme facets for weeks whose receiving file was kept (first run after
    # the 2026-09-15 facet addition, or a facet PFF was down for)
    if not a.no_facets:
        for wk in kept:
            pull_facets(key, season, wk, force=False)
            pull_v2(key, season, wk, force=False)
        pull_prior_season(key, season, force=a.prior_refetch)
    print(f'done: wrote {[w for w, _ in written]}, kept {kept}')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f'ERROR: {e}')
        sys.exit(1)
