#!/usr/bin/env python3
"""
PFF Premium weekly receiving exports -> E:\\MyFantasyFootball\\pbp_cache\\pff\\weekly\\
    pff_receiving_<season>_w<N>.csv          (one file per completed week)
    pff_<facet>_<season>_w<N>.csv            scheme/alignment facets (see FACETS below)
    pff_<facet>_<season-1>_w<N>.csv          prior-season weekly facets (fetched once; the comparison prior)

These are the files scripts/pull_route_pct.py turns into the REAL current-season
RT% column (routes / team dropbacks). Without them the card shows a ~estimate
built from snap share (see estimate_from_snaps there).

HOW IT WORKS (same in-page fetch recipe as the 2026-07-31 season pull, but in
a dedicated persistent Chrome profile so nobody has to drive Jack's browser):
  * Selenium opens a VISIBLE Chrome with --user-data-dir=<pff/chrome_profile>.
    The FIRST run needs Jack to log in to premium.pff.com in that window (the
    script waits up to --login-wait seconds, polling the API). The profile
    keeps the session cookie, so later runs are unattended until PFF expires
    it - then the log says "PFF LOGIN NEEDED" and the estimate stays in place.
  * The data comes from PFF's own table API behind the Premium Stats pages:
        /api/v1/facet/receiving/summary?league=nfl&season=<Y>&week=<N>
    (JSON, key receiving_summary; fields = the receiving_summary CSV columns:
    player, player_id, position, team_name, routes, route_rate, targets, ...).
    Fetched in-page with credentials so the browser sends the login cookie.
  * Weeks: --weeks auto (default) walks 1..18 and stops at the first week PFF
    returns no rows. Existing files are kept unless they are one of the
    newest --refetch weeks (PFF re-grades for a day or two) or --all is given.

Credentials are NEVER read or stored by this script - only PFF's own browser
session inside the profile directory. Do not copy the profile anywhere.

Run from the project root:
    python scripts/pull_pff_weekly.py                 # current season, auto weeks
    python scripts/pull_pff_weekly.py --login-wait 600  # first run: log in when Chrome opens
    python scripts/pull_pff_weekly.py --weeks 1,2 --all
Exit codes: 0 ok (even if nothing new), 2 = not logged in (no files touched), 1 = error.
"""
import argparse, csv, datetime as dt, io, json, os, sys, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CACHE = r'E:\MyFantasyFootball\pbp_cache'
PFF_DIR = os.path.join(CACHE, 'pff')
PFF_WEEKLY = os.path.join(PFF_DIR, 'weekly')
PROFILE = os.path.join(PFF_DIR, 'chrome_profile')
HOME = 'https://premium.pff.com/nfl/positions/{season}/REG/receiving'
API = 'https://premium.pff.com/api/v1/facet/receiving/summary?league=nfl&season={season}&week={week}'
# receiving/summary only lists players with >= 1 TARGET that week (Ridley 64%
# snaps / 0 targets = no row). offense/summary lists everyone who took a snap
# with snap_counts_pass_route (= routes run) so zero-target route runners get a
# row too (routes only; no route_rate/grades - pull_route_pct.py divides by
# nflverse dropbacks anyway).
API_OFF = 'https://premium.pff.com/api/v1/facet/offense/summary?league=nfl&season={season}&week={week}'
# SCHEME / ALIGNMENT facets (2026-09-15, Jack: "where each defense gets targeted or
# what type of runs outside/inside... maybe pff"). PFF serves these weekly in-season
# (probe 2026-09-15: HTTP 200 for every entry below; rushing/gap_zone,
# passing/time_in_pocket, defense/run_defense, defense/slot_coverage and blocking/*
# are 404 and NOT requested). One CSV per facet per week:
#     pff_<key>_<season>_w<N>.csv
# Consumers: E:\MyFantasyFootball\sim_lab\build_scheme.py (team + player scheme
# cards on the Sim Lab ZONES / NOTES tabs). Nested values (rushing/direction
# "directions") are flattened to <col>_<key>[_<sub>] columns; lists become JSON.
FACET_API = 'https://premium.pff.com/api/v1/facet/{facet}?league=nfl&season={season}&week={week}'
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
# Column order of the season exports already in pbp_cache/pff (kept identical so
# every consumer can read both shapes); anything else PFF sends is appended.
LEAD_COLS = ['season', 'player', 'player_id', 'position', 'team_name', 'player_game_count', 'routes',
             'route_rate', 'targets', 'receptions', 'yards', 'touchdowns', 'yprr', 'avg_depth_of_target',
             'grades_pass_route', 'grades_offense', 'slot_rate', 'wide_rate', 'inline_rate',
             'yards_after_catch_per_reception', 'contested_catch_rate', 'drop_rate', 'caught_percent',
             'first_downs', 'avoided_tackles']


def _make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        path = ChromeDriverManager().install()
    except Exception:  # noqa: BLE001
        path = None
    os.makedirs(PROFILE, exist_ok=True)
    opts = Options()
    opts.add_argument('--user-data-dir=' + PROFILE)
    opts.add_argument('--profile-directory=Default')
    opts.add_argument('--disable-blink-features=AutomationControlled')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--no-first-run')
    opts.add_argument('--window-size=1280,860')
    opts.add_experimental_option('excludeSwitches', ['enable-automation'])
    opts.add_experimental_option('useAutomationExtension', False)
    drv = webdriver.Chrome(service=Service(path) if path else Service(), options=opts)
    drv.set_page_load_timeout(60)
    drv.set_script_timeout(60)
    return drv


def _page_fetch(driver, url):
    """In-page fetch with the profile's cookies. -> (status, text)."""
    res = driver.execute_async_script("""
        const url = arguments[0], done = arguments[arguments.length-1];
        fetch(url, {credentials:'include', headers:{Accept:'application/json'}})
          .then(r => r.text().then(t => done(JSON.stringify({status:r.status, body:t}))))
          .catch(e => done(JSON.stringify({status:0, body:String(e)})));
    """, url)
    res = json.loads(res)
    return res.get('status', 0), res.get('body', '')


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


def _probe(driver, season):
    """-> rows for week 1, or None when the session is not logged in / API changed.

    Logged-out browsers still get HTTP 200 with the box-score columns only
    (player, targets, receptions, yards...); the premium fields (routes,
    route_rate, grades) appear only with a subscriber session. So "logged in"
    = at least one row carries a `routes` key."""
    status, body = _page_fetch(driver, API.format(season=season, week=1))
    if status != 200:
        return None, status
    rows = _rows(body)
    if not isinstance(rows, list) or not any('routes' in r for r in rows if isinstance(r, dict)):
        return None, f'{status} (no premium fields - not signed in)'
    return rows, status


def _add_zero_target_routes(driver, season, week, live):
    """Append players who ran routes but drew no target (absent from
    receiving/summary) using offense/summary snap_counts_pass_route."""
    status, body = _page_fetch(driver, API_OFF.format(season=season, week=week))
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


def pull_prior_season(driver, season, force=False):
    """PRIOR season, weeks 1-18, every facet + receiving/summary (saved as
    receiving_summary so pull_route_pct.py's pff_receiving_<yr>_w* glob never sees
    it) -> pff_<facet>_<prior>_w<N>.csv. Skips files already on disk, so after the
    first run this costs one probe. build_scheme.py compares each defense's / player's
    current profile with last season and flags what carried over."""
    prior = season - 1
    done, missing = [], 0
    for wk in range(1, 19):
        for key, facet in FACETS + [('receiving_summary', 'receiving/summary')]:
            path = facet_path(key, prior, wk)
            if os.path.exists(path) and not force:
                continue
            status, body = _page_fetch(driver, FACET_API.format(facet=facet, season=prior, week=wk))
            rows = _rows(body) if status == 200 else None
            if not isinstance(rows, list) or not rows:
                print(f'  {prior} week {wk}: {facet} HTTP {status} - skipped')
                missing += 1
                continue
            _write_csv(path, prior, wk, [_flatten(r) for r in rows if isinstance(r, dict)], lead=FACET_LEAD)
            done.append((wk, key))
            time.sleep(0.5)
    if done:
        print(f'  {prior} weekly facets: wrote {len(done)} files' + (f', {missing} skipped' if missing else ''))
    return done


def facet_path(key, season, week):
    return os.path.join(PFF_WEEKLY, f'pff_{key}_{season}_w{week}.csv')


def pull_facets(driver, season, week, force=False):
    """Fetch every FACETS entry for one played week; skip files that already exist
    unless force. -> list of (key, rows) written."""
    done = []
    for key, facet in FACETS:
        path = facet_path(key, season, week)
        if os.path.exists(path) and not force:
            continue
        status, body = _page_fetch(driver, FACET_API.format(facet=facet, season=season, week=week))
        if status != 200:
            print(f'  week {week}: {facet} HTTP {status} - skipped')
            continue
        rows = _rows(body)
        if not isinstance(rows, list):
            print(f'  week {week}: {facet} unreadable - skipped')
            continue
        rows = [_flatten(r) for r in rows if isinstance(r, dict)]
        _write_csv(path, season, week, rows, lead=FACET_LEAD)
        done.append((key, len(rows)))
        time.sleep(0.6)
    if done:
        print(f'  week {week}: facets ' + ', '.join(f'{k} {n}' for k, n in done))
    return done


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
    ap.add_argument('--login-wait', type=int, default=300, help='seconds to wait for a manual PFF login')
    ap.add_argument('--no-facets', action='store_true', help='skip the scheme/alignment facet files (receiving only)')
    ap.add_argument('--prior-refetch', action='store_true', help='refetch the prior-season weekly facet files')
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

    driver = _make_driver()
    try:
        driver.get(HOME.format(season=season))
        time.sleep(2)
        rows1, status = _probe(driver, season)
        deadline = time.time() + max(0, a.login_wait)
        warned = False
        while rows1 is None and time.time() < deadline:
            if not warned:
                print(f'PFF LOGIN NEEDED: API returned {status} - log in to premium.pff.com in the Chrome '
                      f'window (waiting up to {a.login_wait}s)...')
                warned = True
            time.sleep(10)
            rows1, status = _probe(driver, season)
        if rows1 is None:
            print(f'PFF LOGIN NEEDED (API {status}) - no files written; the RT% column keeps its snap-share estimate.')
            return 2
        print(f'logged in: week 1 rows={len(rows1)}')

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
                status, body = _page_fetch(driver, API.format(season=season, week=wk))
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
                live = _add_zero_target_routes(driver, season, wk, live)
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
                pull_facets(driver, season, wk, force=True)
            time.sleep(1.0)
        # scheme facets for weeks whose receiving file was kept (first run after
        # the 2026-09-15 facet addition, or a facet PFF was down for)
        if not a.no_facets:
            for wk in kept:
                pull_facets(driver, season, wk, force=False)
            pull_prior_season(driver, season, force=a.prior_refetch)
        print(f'done: wrote {[w for w, _ in written]}, kept {kept}')
        return 0
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f'ERROR: {e}')
        sys.exit(1)
