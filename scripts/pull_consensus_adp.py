# Automated consensus-ADP / rankings puller for the Site Rankings CSVs.
#
# Replaces the manual "download CSVs and re-run inject_rankings.py" routine
# for every source that has a public keyless endpoint:
#
#   Phase A — FantasyPros consensus rankings (4 modes) from the inline
#             `var ecrData = {...}` JSON on the public rankings pages:
#               ppr-cheatsheets.php            -> FantasyPros_2026_Draft1QB.csv
#               ppr-superflex-cheatsheets.php  -> FantasyPros_2026_DraftSF.csv
#               dynasty-overall.php            -> FantasyPros_2026_Dynasty1QB.csv
#               dynasty-superflex.php          -> FantasyPros_2026_DynastySF.csv
#   Phase B — ESPN staff draft rank (draftRanksByRankType.PPR) from the
#             public fantasy kona_player_info API -> ESPN1QB.csv
#   Phase C — CBS expert-consensus rank from the public PPR top200
#             rankings page -> CBS1QB.csv
#   Phase D — Yahoo O-Rank (editorial overall rank, sort=OR) from the public
#             pub-api-ro fantasy API (keyless) -> Yahoo1QB.csv
#   Phase E — KeepTradeCut dynasty values from the playersArray JSON embedded
#             in keeptradecut.com/dynasty-rankings -> spliced straight into
#             data/_bundle_lookups.js + data/ktc_rankings.js (KTC_1QB/KTC_SF),
#             replacing the manual League-Analyzer-XLSX + build_ktc.py flow.
#   Phase F — Underdog ADP (BBM + Superflex) from the shared/ud_adp_latest
#             Firestore mirror doc (public read; written by Jack's site
#             session whenever the Draft Helper extension applies its daily
#             ADP refresh) -> UnderdogADP.csv (udA) + UnderdogSFADP.csv (sfa)
#             + rolls data/ud_adp_history.json (30-day feed the extension
#             fetches to show ADP risers/fallers).
#   Phase G — Mike Clay projections: re-downloads ESPN's draft-kit PDF from
#             its stable CDN URL; when the bytes change, re-runs
#             extract_clay_projections.py -> data/mike_clay_projections.js.
#   Phase K — Sleeper per-mode ADP ranks (added 2026-08-26): runs repo-root
#             pull_sleeper_adp.py (git-excluded local tooling, same as
#             inject_rankings.py) against Sleeper's keyless projections API
#             (api.sleeper.com, adp_ppr/adp_2qb/adp_dynasty_ppr/adp_dynasty_2qb)
#             -> Sleeper1QBADP.csv + SleeperSFADP.csv + SleeperDynasty1QB.csv
#             + SleeperDynastySF.csv. Rows encode the RANK slot in that
#             format's ADP ordering (== Sleeper's draft-room RK column),
#             per Jack 2026-08-07 "use rank and not adp".
#   Phase L — DraftKings best-ball ADP (added 2026-08-26): runs
#             scripts/update_dk_adp.py, which reads Occupy Fantasy's public
#             JSON feed (DK-sponsored, SportsData.io-powered, daily 2pm ET)
#             and splices raw ADP decimals into d.js "dk" fields directly —
#             no CSV/inject step, since inject_rankings.py never parsed the
#             manual DkPreDraftRankings.csv (its April values were a one-off).
#
# ESPN/CBS/Yahoo values are stored as SEQUENTIAL RANK ORDER (1..N by that
# site's own EDITORIAL rank — the order its player list displays, not crowd
# ADP; switched 2026-08-06) — emitted as round.pick so inject_rankings.py's
# parse_pickadp reproduces the rank as an int. K/DST are included at their
# verbatim list slots (2026-08-06 pm) — no position stripping, every rank is
# the player's true position in that site's full list. Underdog (and Sleeper)
# have no editorial ranks, so those stay ADP-based.
#
# Underdog needs a logged-in session, but Phase F closes that loop via the
# extension: Jack's browser captures live UD ADP, the site mirrors it to a
# public Firestore doc, and this script folds it back into d.js.
#
# Phase H syncs d.js "t" team assignments against Sleeper's public players
# dump (scripts/update_rosters.py) so FA signings/trades no longer need
# manual edits; contract fields (sal/cyr/out) stay manual — no free source.
#
# CSVs are written in the exact formats inject_rankings.py already parses,
# then inject_rankings.py is run to rewrite data/d.js, and the d.js ?v= tag
# in index.html is bumped. A source that returns fewer rows than its sanity
# minimum is skipped (old CSV kept) rather than clobbering good data.
#
#   python scripts/pull_consensus_adp.py            # all phases + inject + bump
#   python scripts/pull_consensus_adp.py --no-inject  # CSVs only

import argparse
import csv
import datetime
import json
import os
import re
import subprocess
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR_DIR = os.path.join(ROOT, 'Site Rankings')
INDEX_FILE = os.path.join(ROOT, 'index.html')
TODAY = datetime.date.today().isoformat()

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
HEADERS = {'User-Agent': UA}

TEAM_SIZE = 12  # round.pick emission matches inject_rankings.py's assumption

FP_PAGES = {
    'FantasyPros_2026_Draft1QB.csv':   'https://www.fantasypros.com/nfl/rankings/ppr-cheatsheets.php',
    'FantasyPros_2026_DraftSF.csv':    'https://www.fantasypros.com/nfl/rankings/ppr-superflex-cheatsheets.php',
    'FantasyPros_2026_Dynasty1QB.csv': 'https://www.fantasypros.com/nfl/rankings/dynasty-overall.php',
    'FantasyPros_2026_DynastySF.csv':  'https://www.fantasypros.com/nfl/rankings/dynasty-superflex.php',
}
FP_MIN_ROWS = 300

ESPN_URL = ('https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/'
            '2026/segments/0/leaguedefaults/3')
ESPN_MIN_ROWS = 150
ESPN_POS = {1: 'QB', 2: 'RB', 3: 'WR', 4: 'TE', 5: 'K', 16: 'DST'}
ESPN_TEAMS = {
    1: 'ATL', 2: 'BUF', 3: 'CHI', 4: 'CIN', 5: 'CLE', 6: 'DAL', 7: 'DEN',
    8: 'DET', 9: 'GB', 10: 'TEN', 11: 'IND', 12: 'KC', 13: 'LV', 14: 'LAR',
    15: 'MIA', 16: 'MIN', 17: 'NE', 18: 'NO', 19: 'NYG', 20: 'NYJ',
    21: 'PHI', 22: 'ARI', 23: 'PIT', 24: 'LAC', 25: 'SF', 26: 'SEA',
    27: 'TB', 28: 'WAS', 29: 'CAR', 30: 'JAX', 33: 'BAL', 34: 'HOU',
}
# abbr -> full team name, for building d.js-canonical D/ST names
# ("Denver Broncos D/ST") from ESPN's "Broncos D/ST" / Yahoo's "Denver".
TEAM_FULL = {
    'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens',
    'BUF': 'Buffalo Bills', 'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears',
    'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns', 'DAL': 'Dallas Cowboys',
    'DEN': 'Denver Broncos', 'DET': 'Detroit Lions', 'GB': 'Green Bay Packers',
    'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars',
    'KC': 'Kansas City Chiefs', 'LAC': 'Los Angeles Chargers', 'LAR': 'Los Angeles Rams',
    'LV': 'Las Vegas Raiders', 'MIA': 'Miami Dolphins', 'MIN': 'Minnesota Vikings',
    'NE': 'New England Patriots', 'NO': 'New Orleans Saints', 'NYG': 'New York Giants',
    'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers',
    'SEA': 'Seattle Seahawks', 'SF': 'San Francisco 49ers', 'TB': 'Tampa Bay Buccaneers',
    'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders',
}

# 2026-08-06: switched from the draft-averages page (crowd ADP) to the PPR
# top200 expert-consensus rankings — the "RK" list CBS itself shows. Names on
# the page are abbreviated ("J. Gibbs"); full names are recovered from the
# /nfl/players/<id>/<slug>/ URL slug (norm_name in inject_rankings.py treats
# hyphens as spaces, so slug-derived names still match d.js).
CBS_URL = 'https://www.cbssports.com/fantasy/football/rankings/ppr/top200/'
CBS_MIN_ROWS = 100

# Yahoo public fantasy API (no auth/cookies/crumb needed). 470 = 2026 NFL
# game key; bump yearly. 2026-08-06: sort switched from average_pick (crowd
# ADP) to OR — Yahoo's editorial O-Rank, the default order of their player
# list. The response order IS the rank; no per-player rank field needed.
YAHOO_URL = ('https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/league/'
             '470.l.public/players;position=ALL;start=0;count=400;'
             'sort=OR/draft_analysis?format=json_f')
YAHOO_MIN_ROWS = 150

# Underdog ADP mirror: shared/ud_adp_latest is written by Jack's site session
# whenever the Draft Helper extension applies its daily ADP refresh (see
# _mffSetAdpSnapshot in app.js). Public-read per firestore.rules, so this
# fetch needs no credentials — the ?key= is the public web API key.
UD_MIRROR_URL = ('https://firestore.googleapis.com/v1/projects/jackb933-website/'
                 'databases/(default)/documents/shared/ud_adp_latest'
                 '?key=AIzaSyD9D_Rhb5hEpz2cBWqQr7hcFCDoluwq6uY')
UD_MIRROR_MAX_AGE_DAYS = 14   # older snapshot = extension hasn't run; keep old CSVs
UD_MIN_ROWS = 100
UD_HISTORY_FILE = os.path.join(ROOT, 'data', 'ud_adp_history.json')
UD_HISTORY_DAYS = 30

# Mike Clay projections: ESPN republishes the draft-kit PDF at a stable URL
# as Clay updates it through the summer. We re-download daily, and only when
# the bytes change re-run extract_clay_projections.py -> mike_clay_projections.js.
CLAY_PDF_URL = 'https://g.espncdn.com/s/ffldraftkit/26/NFLDK2026_CS_ClayProjections2026.pdf'
CLAY_PDF = os.path.join(SR_DIR, 'NFLDK2026_CS_ClayProjections2026.pdf')
CLAY_OUT = os.path.join(ROOT, 'data', 'mike_clay_projections.js')
CLAY_MIN_ENTRIES = 400

KTC_URL = 'https://keeptradecut.com/dynasty-rankings'
KTC_MIN_ROWS = 400
KTC_BUNDLE = os.path.join(ROOT, 'data', '_bundle_lookups.js')
KTC_ORPHAN = os.path.join(ROOT, 'data', 'ktc_rankings.js')
# KTC display name -> d.js canonical name, for cases inject_rankings.py's
# norm_name/OVERRIDES can't bridge (kept from scripts/refresh_ktc.py).
KTC_ALIASES = {
    'Jamarion Miller': 'Jam Miller',
}

VALID_POS = {'QB', 'RB', 'WR', 'TE'}


def overall_to_round_pick(pick):
    r = (pick - 1) // TEAM_SIZE + 1
    p = (pick - 1) % TEAM_SIZE + 1
    return f'{r}.{p}'


def write_csv(fname, header_line, rows):
    """Write a Site Rankings CSV. header_line is written verbatim so the
    column-sniffing in inject_rankings.py keeps matching."""
    path = os.path.join(SR_DIR, fname)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(header_line + '\n')
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        for row in rows:
            w.writerow(row)
    print(f'  wrote {fname}: {len(rows)} rows')


# ---------------------------------------------------------------------------
# Phase A — FantasyPros consensus rankings (ecrData inline JSON)
# ---------------------------------------------------------------------------

def pull_fantasypros():
    ok = 0
    for fname, url in FP_PAGES.items():
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            m = re.search(r'var ecrData = (\{.*?\});', r.text)
            if not m:
                print(f'  !! {fname}: no ecrData on {url} — kept old file')
                continue
            players = json.loads(m.group(1)).get('players', [])
            rows = []
            for p in players:
                name = (p.get('player_name') or '').strip()
                rank = p.get('rank_ecr')
                if not name or rank is None:
                    continue
                rows.append([rank, name,
                             p.get('player_team_id') or '',
                             p.get('pos_rank') or p.get('player_position_id') or ''])
            rows.sort(key=lambda x: x[0])
            if len(rows) < FP_MIN_ROWS:
                print(f'  !! {fname}: only {len(rows)} rows (<{FP_MIN_ROWS}) — kept old file')
                continue
            write_csv(fname, '"RK","PLAYER NAME","TEAM","POS"', rows)
            ok += 1
        except Exception as e:
            print(f'  !! {fname}: {e} — kept old file')
    return ok


# ---------------------------------------------------------------------------
# Phase B — ESPN staff draft rank (public kona_player_info API)
# ---------------------------------------------------------------------------
# 2026-08-06: switched from ownership.averageDraftPosition (crowd ADP) to
# draftRanksByRankType.PPR.rank — ESPN's editorial rank, the order their
# draft-lobby player list actually shows. Jack wants each platform column to
# mirror what that platform's own list displays; only Underdog (no editorial
# ranks) stays ADP.

def pull_espn():
    try:
        flt = {'players': {'limit': 400,
                           'sortDraftRanks': {'sortPriority': 100,
                                              'sortAsc': True, 'value': 'PPR'}}}
        r = requests.get(ESPN_URL, params={'view': 'kona_player_info'},
                         headers={**HEADERS, 'x-fantasy-filter': json.dumps(flt)},
                         timeout=30)
        r.raise_for_status()
        entries = []
        for item in r.json().get('players', []):
            pl = item.get('player') or {}
            pos = ESPN_POS.get(pl.get('defaultPositionId'))
            rank = ((pl.get('draftRanksByRankType') or {}).get('PPR') or {}).get('rank')
            name = (pl.get('fullName') or '').strip()
            team = ESPN_TEAMS.get(pl.get('proTeamId'), '')
            if pos not in VALID_POS and pos not in ('K', 'DST'):
                continue
            if not name or not rank or rank <= 0:
                continue
            if pos == 'DST':
                # ESPN names defenses "Broncos D/ST" — rebuild the d.js-canonical
                # "Denver Broncos D/ST" from the pro team id.
                if team not in TEAM_FULL:
                    continue
                name = TEAM_FULL[team] + ' D/ST'
            entries.append((rank, name, team, pos))
        entries.sort(key=lambda x: x[0])
        n_skill = sum(1 for e in entries if e[3] in VALID_POS)
        if n_skill < ESPN_MIN_ROWS:
            print(f'  !! ESPN1QB.csv: only {n_skill} skill rows (<{ESPN_MIN_ROWS}) — kept old file')
            return 0
        # Verbatim full-list ranks for EVERYONE (K/DST included) since
        # 2026-08-06 pm — each rank is the player's true slot in ESPN's own
        # displayed list order, no K/DST stripping.
        rows = [[name, team, pos, overall_to_round_pick(i + 1), '0']
                for i, (_, name, team, pos) in enumerate(entries)]
        write_csv('ESPN1QB.csv',
                  '"Player Name", "Player Team", "Player Position", ESPN: Redraft 1 PPR ADP, "Market Index 1",',
                  rows)
        return 1
    except Exception as e:
        print(f'  !! ESPN1QB.csv: {e} — kept old file')
        return 0


# ---------------------------------------------------------------------------
# Phase C — CBS expert-consensus rank (public PPR top200 rankings page)
# NOTE: the top200 list is skill-only (verified 2026-08-06 — zero K/DST rows),
# so the CBS column stays blank for K/DST. CBS's separate K/DST pages only
# publish POSITIONAL ranks, which don't fit the overall-rank column scale.
# ---------------------------------------------------------------------------

def pull_cbs():
    try:
        r = requests.get(CBS_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        # The page carries several 200-row lists (consensus + one per expert).
        # The first player-wrapper is the consensus "RK" list — parse only it.
        wrappers = r.text.split('<div class="player-wrapper">')
        if len(wrappers) < 2:
            print('  !! CBS1QB.csv: no player-wrapper found — kept old file')
            return 0
        entries = []
        for chunk in wrappers[1].split('<div class="player-row')[1:]:
            rk = re.search(r'<div class="rank">(\d+)</div>', chunk)
            slug = re.search(r'/nfl/players/\d+/([a-z0-9-]+)/', chunk)
            pm = re.search(r'class="team position">\s*([A-Z]+)', chunk)
            if not rk or not slug or not pm:
                continue  # D/ST rows have no player link — dropped here
            pos = pm.group(1)
            if pos not in VALID_POS:
                continue
            name = ' '.join(w.capitalize() for w in slug.group(1).split('-'))
            entries.append((int(rk.group(1)), name, '', pos))
        entries.sort(key=lambda x: x[0])
        if len(entries) < CBS_MIN_ROWS:
            print(f'  !! CBS1QB.csv: only {len(entries)} rows (<{CBS_MIN_ROWS}) — kept old file')
            return 0
        rows = [[name, team, pos, overall_to_round_pick(i + 1), '0']
                for i, (_, name, team, pos) in enumerate(entries)]
        write_csv('CBS1QB.csv',
                  '"Player Name", "Player Team", "Player Position", CBS: Redraft 1 PPR ADP, "Market Index 1",',
                  rows)
        return 1
    except Exception as e:
        print(f'  !! CBS1QB.csv: {e} — kept old file')
        return 0


# ---------------------------------------------------------------------------
# Phase D — Yahoo O-Rank (public pub-api-ro fantasy API, sort=OR)
# ---------------------------------------------------------------------------

def pull_yahoo():
    try:
        r = requests.get(YAHOO_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        players = r.json()['fantasy_content']['league'].get('players', [])
        entries = []
        for item in players:
            pl = item.get('player') or {}
            name = ((pl.get('name') or {}).get('full') or '').strip()
            pos = pl.get('primary_position') or pl.get('display_position') or ''
            team = (pl.get('editorial_team_abbr') or '').upper()
            if pos == 'DEF':
                # Yahoo names defenses by nickname ("Texans") — rebuild the
                # d.js-canonical "Houston Texans D/ST" from the team abbr.
                if team not in TEAM_FULL:
                    continue
                name, pos = TEAM_FULL[team] + ' D/ST', 'DST'
            elif pos not in VALID_POS and pos != 'K':
                continue
            if not name:
                continue
            entries.append((name, team, pos))  # API order = O-Rank order
        n_skill = sum(1 for e in entries if e[2] in VALID_POS)
        if n_skill < YAHOO_MIN_ROWS:
            print(f'  !! Yahoo1QB.csv: only {n_skill} skill rows (<{YAHOO_MIN_ROWS}) — kept old file')
            return 0
        # Same convention as ESPN: verbatim full O-Rank list slots for
        # everyone, K/DST included — no stripping.
        rows = [[name, team, pos, overall_to_round_pick(i + 1), '0']
                for i, (name, team, pos) in enumerate(entries)]
        write_csv('Yahoo1QB.csv',
                  '"Player Name", "Player Team", "Player Position", Yahoo: Redraft 1 STD ADP, "Market Index 1",',
                  rows)
        return 1
    except Exception as e:
        print(f'  !! Yahoo1QB.csv: {e} — kept old file')
        return 0


# ---------------------------------------------------------------------------
# Phase K — Sleeper per-mode ADP ranks (repo-root pull_sleeper_adp.py)
# ---------------------------------------------------------------------------

def pull_sleeper():
    """Run pull_sleeper_adp.py to rebuild the 4 Sleeper CSVs from Sleeper's
    keyless projections API. Returns the number of CSVs refreshed (0-4).
    The script aborts (nonzero exit) on a thin payload, keeping old files —
    same fail-safe convention as the other phases. It lives at repo root as
    git-excluded local tooling (beside inject_rankings.py), so skip politely
    on a checkout that doesn't have it."""
    script = os.path.join(ROOT, 'pull_sleeper_adp.py')
    if not os.path.exists(script):
        print('  !! pull_sleeper_adp.py not found (local tooling) — kept old Sleeper CSVs')
        return 0
    res = subprocess.run([sys.executable, script],
                         cwd=ROOT, capture_output=True, text=True)
    print((res.stdout or '').rstrip())
    if res.returncode != 0:
        print((res.stderr or '').strip()[-500:])
        print('  !! Sleeper pull failed — previous Sleeper CSVs kept')
        return 0
    return (res.stdout or '').count('wrote ')


# ---------------------------------------------------------------------------
# Phase F — Underdog ADP from the extension's Firestore mirror
# ---------------------------------------------------------------------------

def _fs_val(f):
    """Unwrap a Firestore REST field value."""
    if 'doubleValue' in f:
        return float(f['doubleValue'])
    if 'integerValue' in f:
        return int(f['integerValue'])
    if 'stringValue' in f:
        return f['stringValue']
    if 'mapValue' in f:
        return {k: _fs_val(v) for k, v in (f['mapValue'].get('fields') or {}).items()}
    return None


def pull_underdog_mirror():
    """Read shared/ud_adp_latest, regenerate UnderdogADP.csv (udA/BBM) +
    UnderdogSFADP.csv (sfa/Superflex) and roll data/ud_adp_history.json
    (the site-hosted feed the Draft Helper extension reads for ADP-movement
    arrows). Returns number of CSVs refreshed (0-2)."""
    try:
        r = requests.get(UD_MIRROR_URL, headers=HEADERS, timeout=30)
        if r.status_code == 404:
            print('  !! UD mirror doc not found yet — open an Underdog tab with the '
                  'extension (as Jack) once so the site can mirror a snapshot. Kept old CSVs.')
            return 0
        r.raise_for_status()
        fields = r.json().get('fields') or {}
        snap_date = _fs_val(fields.get('date', {})) or ''
        adps = _fs_val(fields.get('adps', {})) or {}
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', snap_date) or not adps:
            print(f'  !! UD mirror: malformed doc (date={snap_date!r}, {len(adps)} players) — kept old CSVs')
            return 0
        age = (datetime.date.today() - datetime.date.fromisoformat(snap_date)).days
        if age > UD_MIRROR_MAX_AGE_DAYS:
            print(f'  !! UD mirror: snapshot is {age} days old ({snap_date}) — kept old CSVs')
            return 0

        bbm, sf = [], []
        for name, ent in adps.items():
            if not isinstance(ent, dict) or not name.strip():
                continue
            b, s = ent.get('bbm'), ent.get('sf')
            if isinstance(b, (int, float)) and 0 < b < 300:
                bbm.append((float(b), name))
            if isinstance(s, (int, float)) and 0 < s < 300:
                sf.append((float(s), name))
        print(f'  UD mirror {snap_date} (age {age}d): {len(bbm)} BBM / {len(sf)} SF ADPs')

        def emit(fname, entries):
            if len(entries) < UD_MIN_ROWS:
                print(f'  !! {fname}: only {len(entries)} rows (<{UD_MIN_ROWS}) — kept old file')
                return 0
            entries.sort(key=lambda x: x[0])
            rows = []
            for adp, name in entries:
                parts = name.split(' ', 1)
                first, last = parts[0], (parts[1] if len(parts) > 1 else '')
                rows.append(['', first, last, adp, '', '', '', '', '', ''])
            write_csv(fname,
                      '"id","firstName","lastName","adp","projectedPoints","positionRank",'
                      '"slotName","teamName","lineupStatus","byeWeek"', rows)
            return 1

        n = emit('UnderdogADP.csv', bbm) + emit('UnderdogSFADP.csv', sf)

        # Roll the site-hosted history feed (extension reads this for ▲▼).
        hist = {'updated': '', 'days': []}
        if os.path.exists(UD_HISTORY_FILE):
            try:
                hist = json.load(open(UD_HISTORY_FILE, encoding='utf-8'))
            except Exception:
                pass
        days = [d for d in hist.get('days', []) if d.get('date') != snap_date]
        days.append({'date': snap_date, 'adps': adps})
        days.sort(key=lambda d: d.get('date', ''))
        hist = {'updated': datetime.datetime.now(datetime.timezone.utc)
                           .strftime('%Y-%m-%dT%H:%M:%SZ'),
                'days': days[-UD_HISTORY_DAYS:]}
        with open(UD_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(hist, f, separators=(',', ':'))
        print(f'  ud_adp_history.json: {len(hist["days"])} day(s) through {snap_date}')
        return n
    except Exception as e:
        print(f'  !! UD mirror: {e} — kept old CSVs')
        return 0


# ---------------------------------------------------------------------------
# Phase E — KeepTradeCut dynasty values -> _bundle_lookups.js + ktc_rankings.js
# ---------------------------------------------------------------------------

def _ktc_js_literal(varname, m):
    body = ','.join(f'{json.dumps(k, ensure_ascii=False)}:{int(v)}' for k, v in m.items())
    return f'var {varname}={{{body}}};'


def _ktc_splice(path, varname, literal):
    src = open(path, encoding='utf-8').read()
    pat = re.compile(r'var ' + varname + r'=\{.*?\};', re.S)
    if not pat.search(src):
        raise RuntimeError(f'{varname} definition not found in {path}')
    open(path, 'w', encoding='utf-8').write(pat.sub(lambda _: literal, src, count=1))


def pull_ktc():
    """Returns True if the bundle changed (caller bumps its ?v=)."""
    try:
        # inject_rankings' name normalization lives at repo root.
        sys.path.insert(0, ROOT)
        from inject_rankings import norm_name, final_key

        r = requests.get(KTC_URL, headers={**HEADERS, 'Accept': 'text/html,application/xhtml+xml'},
                         timeout=30)
        r.raise_for_status()
        m = re.search(r'var\s+playersArray\s*=\s*(\[.*?\])\s*;', r.text, re.DOTALL)
        if not m:
            print('  !! KTC: playersArray not found — template changed? Kept old maps.')
            return False
        arr = json.loads(m.group(1))
        if len(arr) < KTC_MIN_ROWS:
            print(f'  !! KTC: only {len(arr)} players (<{KTC_MIN_ROWS}) — kept old maps')
            return False

        # d.js name index so KTC keys land under d.js-canonical names.
        dsrc = open(os.path.join(ROOT, 'data', 'd.js'), encoding='utf-8').read()
        dnames = re.findall(r'"n":"([^"]+)"', dsrc)
        exact = set(dnames)
        norm_idx = {}
        for n in dnames:
            norm_idx.setdefault(norm_name(n), n)

        def resolve(raw):
            raw = KTC_ALIASES.get(raw, raw)
            if raw in exact:
                return raw
            k = final_key(raw)
            return norm_idx.get(k, raw)  # picks / deep dynasty keep KTC name

        one_qb, sf = {}, {}
        for p in arr:
            name = p.get('playerName') or ''
            if not name:
                continue
            key = resolve(name)
            oqb = (p.get('oneQBValues') or {}).get('value')
            sfv = (p.get('superflexValues') or {}).get('value')
            if oqb is not None and key not in one_qb:
                one_qb[key] = oqb
            if sfv is not None and key not in sf:
                sf[key] = sfv
        one_qb = dict(sorted(one_qb.items(), key=lambda kv: -kv[1]))
        sf = dict(sorted(sf.items(), key=lambda kv: -kv[1]))
        covered = len([n for n in one_qb if n in exact])
        print(f'  KTC_1QB: {len(one_qb)} entries, KTC_SF: {len(sf)} '
              f'(d.js players covered: {covered})')
        if covered < 200:
            print('  !! KTC: d.js coverage suspiciously low — kept old maps')
            return False

        before = open(KTC_BUNDLE, 'rb').read()
        lit1 = _ktc_js_literal('KTC_1QB', one_qb)
        litsf = _ktc_js_literal('KTC_SF', sf)
        for path in (KTC_BUNDLE, KTC_ORPHAN):
            _ktc_splice(path, 'KTC_1QB', lit1)
            _ktc_splice(path, 'KTC_SF', litsf)
        changed = open(KTC_BUNDLE, 'rb').read() != before
        print(f'  spliced KTC maps into _bundle_lookups.js + ktc_rankings.js'
              f' ({"changed" if changed else "no change"})')
        return changed
    except Exception as e:
        print(f'  !! KTC: {e} — kept old maps')
        return False


# ---------------------------------------------------------------------------
# Phase G — Mike Clay projections (ESPN draft-kit PDF)
# ---------------------------------------------------------------------------

def pull_clay():
    """Returns True if data/mike_clay_projections.js changed (caller bumps ?v=)."""
    try:
        r = requests.get(CLAY_PDF_URL, headers=HEADERS, timeout=120)
        r.raise_for_status()
        pdf = r.content
        if pdf[:5] != b'%PDF-' or len(pdf) < 1_000_000:
            print(f'  !! Clay PDF: response not a plausible PDF ({len(pdf):,} bytes) — skipped')
            return False
        old_pdf = open(CLAY_PDF, 'rb').read() if os.path.exists(CLAY_PDF) else b''
        if pdf == old_pdf:
            print('  Clay PDF unchanged — extraction skipped')
            return False
        open(CLAY_PDF, 'wb').write(pdf)
        print(f'  downloaded Clay PDF: {len(pdf):,} bytes (was {len(old_pdf):,})')

        before = open(CLAY_OUT, 'rb').read() if os.path.exists(CLAY_OUT) else b''
        res = subprocess.run([sys.executable, 'extract_clay_projections.py'],
                             cwd=ROOT, capture_output=True, text=True)
        for ln in (res.stdout or '').strip().splitlines()[-3:]:
            print('  ' + ln)
        if res.returncode != 0:
            print((res.stderr or '').strip()[-500:])
            raise RuntimeError(f'extract_clay_projections.py failed (exit {res.returncode})')
        after = open(CLAY_OUT, 'rb').read()
        n_entries = after.count(b'pos:"')
        if n_entries < CLAY_MIN_ENTRIES:
            print(f'  !! Clay extract: only {n_entries} entries (<{CLAY_MIN_ENTRIES}) — restoring previous file')
            if before:
                open(CLAY_OUT, 'wb').write(before)
            return False
        changed = after != before
        print(f'  mike_clay_projections.js: {n_entries} entries '
              f'({"changed" if changed else "no change"})')
        return changed
    except Exception as e:
        print(f'  !! Clay: {e} — kept old projections')
        return False


# ---------------------------------------------------------------------------
# Inject + version bump
# ---------------------------------------------------------------------------

def pull_rosters():
    """Phase H — run update_rosters.py (Sleeper -> d.js team sync, --no-bump
    so main() bumps d.js's ?v= once at the end). Returns True if d.js changed.
    Failures are non-fatal: teams just stay as-is until the next run."""
    d_path = os.path.join(ROOT, 'data', 'd.js')
    before = open(d_path, 'rb').read()
    res = subprocess.run(
        [sys.executable, os.path.join(ROOT, 'scripts', 'update_rosters.py'),
         '--no-bump'],
        cwd=ROOT, capture_output=True, text=True)
    print(res.stdout)
    if res.returncode != 0:
        print(res.stderr)
        print('  !! roster sync failed — team assignments left as-is')
        return False
    return open(d_path, 'rb').read() != before


def pull_dk_adp():
    """Phase L — run update_dk_adp.py (Occupy Fantasy DK feed -> d.js "dk"
    fields, --no-bump so main() bumps d.js's ?v= once at the end). Returns
    True if d.js changed. Non-fatal: a dead feed keeps yesterday's values
    (the script's own max-age guard refuses stale data beyond 7 days)."""
    d_path = os.path.join(ROOT, 'data', 'd.js')
    before = open(d_path, 'rb').read()
    res = subprocess.run(
        [sys.executable, os.path.join(ROOT, 'scripts', 'update_dk_adp.py'),
         '--no-bump'],
        cwd=ROOT, capture_output=True, text=True)
    print(res.stdout)
    if res.returncode != 0:
        print(res.stderr)
        print('  !! DK ADP refresh failed — previous dk values kept')
        return False
    return open(d_path, 'rb').read() != before


def pull_injuries():
    """Phase I — run pull_injuries.py (Sleeper injury tags ->
    data/injury_updates.js). Returns True if the file changed. Non-fatal:
    the app.js merge has an 8-day staleness guard, so a dead phase fails
    safe (old tags stop applying) rather than lingering."""
    out_path = os.path.join(ROOT, 'data', 'injury_updates.js')
    before = open(out_path, 'rb').read() if os.path.exists(out_path) else b''
    res = subprocess.run(
        [sys.executable, os.path.join(ROOT, 'scripts', 'pull_injuries.py')],
        cwd=ROOT, capture_output=True, text=True)
    print(res.stdout)
    if res.returncode != 0:
        print(res.stderr)
        print('  !! injury pull failed — previous injury_updates.js kept')
        return False
    after = open(out_path, 'rb').read() if os.path.exists(out_path) else b''
    return after != before


def pull_weekly_projections():
    """Phase J — run pull_weekly_projections.py (Sleeper weekly consensus ->
    data/weekly_projections.js). Returns True if the file changed. Non-fatal:
    _weeklyAdjustPpg only uses the feed when its week matches the active
    week, so a stale file quietly yields to the heuristic."""
    out_path = os.path.join(ROOT, 'data', 'weekly_projections.js')
    before = open(out_path, 'rb').read() if os.path.exists(out_path) else b''
    res = subprocess.run(
        [sys.executable, os.path.join(ROOT, 'scripts', 'pull_weekly_projections.py')],
        cwd=ROOT, capture_output=True, text=True)
    print(res.stdout)
    if res.returncode != 0:
        print(res.stderr)
        print('  !! weekly projections pull failed — previous file kept')
        return False
    after = open(out_path, 'rb').read() if os.path.exists(out_path) else b''
    return after != before


def run_inject():
    """Run inject_rankings.py; return True if data/d.js actually changed
    (a quiet morning re-injects identical values -> no bump, no commit)."""
    d_path = os.path.join(ROOT, 'data', 'd.js')
    before = open(d_path, 'rb').read()
    print('\nRunning inject_rankings.py ...')
    res = subprocess.run([sys.executable, 'inject_rankings.py'],
                         cwd=ROOT, capture_output=True, text=True)
    print(res.stdout)
    if res.returncode != 0:
        print(res.stderr)
        raise RuntimeError(f'inject_rankings.py failed (exit {res.returncode})')
    return open(d_path, 'rb').read() != before


def bump_version(fname=r'data/d\.js'):
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
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-inject', action='store_true',
                    help='refresh CSVs only; skip inject + version bump')
    args = ap.parse_args()

    print(f'Consensus ADP pull {TODAY}')
    print('\nPhase A — FantasyPros consensus rankings:')
    n_fp = pull_fantasypros()
    print('\nPhase B — ESPN staff rank:')
    n_espn = pull_espn()
    print('\nPhase C — CBS consensus rank:')
    n_cbs = pull_cbs()
    print('\nPhase D — Yahoo O-Rank:')
    n_yah = pull_yahoo()
    print('\nPhase K — Sleeper ADP ranks:')
    n_sl = pull_sleeper()
    print('\nPhase E — KeepTradeCut dynasty values:')
    ktc_changed = pull_ktc()
    if ktc_changed:
        bump_version(r'data/_bundle_lookups\.js')
    print('\nPhase F — Underdog ADP (extension mirror):')
    n_ud = pull_underdog_mirror()
    print('\nPhase G — Mike Clay projections:')
    clay_changed = pull_clay()
    if clay_changed:
        bump_version(r'data/mike_clay_projections\.js')

    roster_changed = dk_changed = False
    if not args.no_inject:
        print('\nPhase H — NFL roster sync (Sleeper -> d.js teams):')
        roster_changed = pull_rosters()
        print('\nPhase L — DraftKings best-ball ADP (Occupy Fantasy feed):')
        dk_changed = pull_dk_adp()

    print('\nPhase I — Sleeper injury tags:')
    inj_changed = pull_injuries()
    if inj_changed:
        bump_version(r'data/injury_updates\.js')

    print('\nPhase J — Sleeper weekly projections:')
    wp_changed = pull_weekly_projections()
    if wp_changed:
        bump_version(r'data/weekly_projections\.js')

    total = n_fp + n_espn + n_cbs + n_yah + n_ud + n_sl
    print(f'\nCSV sources refreshed: {total}/13 (FP {n_fp}/4, ESPN {n_espn}/1, '
          f'CBS {n_cbs}/1, Yahoo {n_yah}/1, Sleeper {n_sl}/4, UD {n_ud}/2) '
          f'+ KTC {"updated" if ktc_changed else "unchanged/skipped"}'
          f' + Clay {"updated" if clay_changed else "unchanged/skipped"}'
          f' + rosters {"updated" if roster_changed else "unchanged/skipped"}'
          f' + DK {"updated" if dk_changed else "unchanged/skipped"}'
          f' + injuries {"updated" if inj_changed else "unchanged/skipped"}'
          f' + weeklyproj {"updated" if wp_changed else "unchanged/skipped"}')
    if (total == 0 and not ktc_changed and not roster_changed and not dk_changed
            and not inj_changed and not wp_changed):
        print('Nothing refreshed — aborting before inject.')
        sys.exit(1)

    d_changed = roster_changed or dk_changed
    if not args.no_inject and total > 0:
        d_changed = run_inject() or d_changed
    if d_changed:
        bump_version()
    else:
        print('d.js unchanged — skipping ?v= bump.')
    print('\nDone.')


if __name__ == '__main__':
    main()
