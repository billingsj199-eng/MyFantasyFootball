"""ESPN debut year per athlete id -> data/espn_debut_years.js (2026-11-02).

Trivia / games show ESPN headshots by NAME, and a name can belong to two players
(the 1991 Dolphins' Mark Clayton vs the Ravens Mark Clayton who debuted in 2005,
id 8437). This bakes each id's first NFL season so the face lookup can refuse a
photo of a player who had not debuted by the board's year. Only the debut is
kept: ESPN leaves experience blank for many retired players (Jim Harbaugh reads
as one season), so a last-season bound would reject good photos.

Ids come from every table the site picks a headshot from: fallback_espn_ids.js,
retired_espn_ids.js, daily_retired_pool.js (RETIRED_ESPN_IDS) and
headshot_espn_ids.js. Source: ESPN core API athlete record — debutYear, else
draft year, else birth year + 22.

Usage (from the checkout root):  python scripts/pull_espn_debut_years.py
Re-runs reuse scripts/_espn_debut_years_cache.json and only fetch new ids.
Then bump the ?v= on data/espn_debut_years.js in index.html.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SOURCES = ['data/fallback_espn_ids.js', 'data/retired_espn_ids.js',
           'data/daily_retired_pool.js', 'data/headshot_espn_ids.js']
CACHE = os.path.join(ROOT, 'scripts', '_espn_debut_years_cache.json')
OUT = os.path.join(ROOT, 'data', 'espn_debut_years.js')
API = 'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/athletes/'
PAIR = re.compile(r'''["']([^"'\n]{2,60})["']\s*:\s*["']?(\d{1,8})["']?''')


def collect_ids():
    ids = set()
    for rel in SOURCES:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            print('missing', rel)
            continue
        with open(path, encoding='utf-8') as f:
            ids.update(m.group(2) for m in PAIR.finditer(f.read()))
    return sorted(ids, key=int)


def fetch(aid):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(API + aid, timeout=20) as r:
                d = json.load(r)
            debut = d.get('debutYear') or (d.get('draft') or {}).get('year')
            if not debut and d.get('dateOfBirth'):
                debut = int(d['dateOfBirth'][:4]) + 22
            return aid, ([int(debut), d.get('fullName') or ''] if debut else None)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return aid, None
        except Exception:
            pass
        time.sleep(1 + attempt)
    return aid, 'ERR'


def main():
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, encoding='utf-8') as f:
            cache = json.load(f)
    ids = collect_ids()
    todo = [i for i in ids if i not in cache or cache[i] == 'ERR']
    print(len(ids), 'ids,', len(todo), 'to fetch')
    with ThreadPoolExecutor(max_workers=8) as ex:
        for n, (aid, val) in enumerate(ex.map(fetch, todo), 1):
            cache[aid] = val
            if n % 200 == 0:
                print(n, '/', len(todo))
                with open(CACHE, 'w', encoding='utf-8') as f:
                    json.dump(cache, f)
    with open(CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f)
    debut = {i: cache[i][0] for i in ids if isinstance(cache.get(i), list)}
    errs = sum(1 for i in ids if cache.get(i) == 'ERR')
    body = ('/* Generated ' + time.strftime('%Y-%m-%d') + ' by scripts/pull_espn_debut_years.py — ESPN athlete id ->\n'
            '   first NFL season. The trivia face lookup refuses an ESPN photo of a player who had\n'
            '   not debuted by the board year (same-name players). */\n'
            'window.ESPN_DEBUT_YEARS = ' + json.dumps(debut, separators=(',', ':')) + ';\n')
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(body)
    print('wrote', OUT, len(debut), 'ids;', errs, 'errors;', len(ids) - len(debut) - errs, 'no data')


if __name__ == '__main__':
    sys.exit(main())
