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
#   Phase B — ESPN redraft ADP from the public fantasy kona_player_info API
#             -> ESPN1QB.csv
#   Phase C — CBS redraft ADP from the public draft-averages page
#             -> CBS1QB.csv
#
# Sleeper (Sleeper*.csv) and Underdog (UnderdogADP.csv) have NO public
# endpoint — those files are left untouched and re-injected as-is, so the
# manual refresh cadence for them still works (live Underdog ADP already
# reaches the site via the extension's daily Firestore snapshots anyway).
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

# PPR path first; h2h fallback keeps the pull alive if CBS reshuffles URLs.
CBS_URLS = [
    'https://www.cbssports.com/fantasy/football/draft/averages/both/ppr/all/',
    'https://www.cbssports.com/fantasy/football/draft/averages/both/h2h/all/',
]
CBS_MIN_ROWS = 100

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
# Phase B — ESPN ADP (public kona_player_info API)
# ---------------------------------------------------------------------------

def pull_espn():
    try:
        flt = {'players': {'limit': 400,
                           'sortAdp': {'sortAsc': True, 'sortPriority': 1}}}
        r = requests.get(ESPN_URL, params={'view': 'kona_player_info'},
                         headers={**HEADERS, 'x-fantasy-filter': json.dumps(flt)},
                         timeout=30)
        r.raise_for_status()
        entries = []
        for item in r.json().get('players', []):
            pl = item.get('player') or {}
            pos = ESPN_POS.get(pl.get('defaultPositionId'))
            adp = (pl.get('ownership') or {}).get('averageDraftPosition')
            name = (pl.get('fullName') or '').strip()
            if pos not in VALID_POS or not name or not adp or adp <= 0:
                continue
            entries.append((adp, name, ESPN_TEAMS.get(pl.get('proTeamId'), ''), pos))
        entries.sort(key=lambda x: x[0])
        if len(entries) < ESPN_MIN_ROWS:
            print(f'  !! ESPN1QB.csv: only {len(entries)} rows (<{ESPN_MIN_ROWS}) — kept old file')
            return 0
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
# Phase C — CBS ADP (public draft-averages page)
# ---------------------------------------------------------------------------

def pull_cbs():
    for url in CBS_URLS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code != 200:
                continue
            trs = re.findall(r'<tr class="TableBase-bodyTr">(.*?)</tr>', r.text, re.S)
            entries = []
            for tr in trs:
                nm = re.search(
                    r'CellPlayerName--long.*?<a[^>]*>\s*([^<]+?)\s*</a>(.*?)(?:CellPlayerName--short|$)',
                    tr, re.S)
                if not nm:
                    continue
                name = nm.group(1).strip()
                meta = re.sub(r'<[^>]+>', ' ', nm.group(2))
                pm = re.search(r'\b(QB|RB|WR|TE|K|DST)\b', meta)
                tm = re.search(r'\b([A-Z]{2,3})\b', meta.replace(pm.group(1), '', 1) if pm else meta)
                pos = pm.group(1) if pm else ''
                if pos not in VALID_POS:
                    continue
                tds = [re.sub(r'<[^>]+>', '', c).strip()
                       for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
                avg = None
                for c in tds:
                    if re.fullmatch(r'\d+(\.\d+)?', c) and float(c) >= 1:
                        avg = float(c)
                        break
                if avg is None:
                    continue
                entries.append((avg, name, tm.group(1) if tm else '', pos))
            entries.sort(key=lambda x: x[0])
            if len(entries) < CBS_MIN_ROWS:
                print(f'  !! CBS1QB.csv: only {len(entries)} rows from {url}')
                continue
            rows = [[name, team, pos, overall_to_round_pick(i + 1), '0']
                    for i, (_, name, team, pos) in enumerate(entries)]
            write_csv('CBS1QB.csv',
                      '"Player Name", "Player Team", "Player Position", CBS: Redraft 1 PPR ADP, "Market Index 1",',
                      rows)
            return 1
        except Exception as e:
            print(f'  !! CBS1QB.csv: {e} ({url})')
    print('  !! CBS1QB.csv: all sources failed — kept old file')
    return 0


# ---------------------------------------------------------------------------
# Inject + version bump
# ---------------------------------------------------------------------------

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


def bump_version():
    html = open(INDEX_FILE, encoding='utf-8').read()
    pat = r'(data/d\.js\?v=)([\w.-]+)'
    m = re.search(pat, html)
    if not m:
        print('  !! d.js script tag not found in index.html — bump ?v= manually')
        return
    old = m.group(2)
    if old.startswith(TODAY):
        suffix = old[len(TODAY):]
        new = TODAY + ('b' if not suffix else chr(ord(suffix[-1]) + 1))
    else:
        new = TODAY
    html = re.sub(pat, r'\g<1>' + new, html)
    open(INDEX_FILE, 'w', encoding='utf-8').write(html)
    print(f'  index.html: d.js ?v={old} -> ?v={new}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-inject', action='store_true',
                    help='refresh CSVs only; skip inject + version bump')
    args = ap.parse_args()

    print(f'Consensus ADP pull {TODAY}')
    print('\nPhase A — FantasyPros consensus rankings:')
    n_fp = pull_fantasypros()
    print('\nPhase B — ESPN ADP:')
    n_espn = pull_espn()
    print('\nPhase C — CBS ADP:')
    n_cbs = pull_cbs()

    total = n_fp + n_espn + n_cbs
    print(f'\nSources refreshed: {total}/6 (FP {n_fp}/4, ESPN {n_espn}/1, CBS {n_cbs}/1)')
    if total == 0:
        print('Nothing refreshed — aborting before inject.')
        sys.exit(1)

    if not args.no_inject:
        if run_inject():
            bump_version()
        else:
            print('d.js unchanged — skipping ?v= bump.')
    print('\nDone.')


if __name__ == '__main__':
    main()
