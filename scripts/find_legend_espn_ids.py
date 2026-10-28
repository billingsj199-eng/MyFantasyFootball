#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
find_legend_espn_ids.py — ESPN ids (and whether a headshot exists) for legends in
data/legend_careers.js that have no id in the four ESPN id files.

ESPN's v3 search returns nothing for pre-2000 players, but the v2 site search
(https://site.api.espn.com/apis/search/v2?query=<name>) does: it found Priest
Holmes (1306), Corey Dillon (1196), Trent Green (478), Henry Ellard (6431) on
2026-10-28. Most of those ids have NO headshot on the CDN (404), but some do —
Henry Ellard's exists because he coached. This script sweeps every candidate,
keeps NFL player hits whose name matches, asks the athlete endpoint for the
headshot href, and writes

    scripts/_found_espn_ids.json
    {"generated": ..., "checked": N, "with_headshot": [...], "no_headshot": [...], "unmatched": [...]}

It does NOT edit the id files (retired_espn_ids.js etc. belong to another
session): merge `with_headshot` rows by hand / in that session. Names whose ESPN
headshot would replace a Commons photo are listed too (`has_commons`), so the
merge can prefer the ESPN headshot (transparent silhouette, same look as the
rest of the board) where the site's trivia lookup already favours ESPN.

ESPN answers 403 to a custom User-Agent string (anything with a URL / e-mail in
it), but accepts the requests library's own default and curl's default, so this
sends no custom User-Agent at all.

Usage: python -I scripts/find_legend_espn_ids.py [--all] [--names ...] [--limit N]
  default: only names with no ESPN id AND no Commons photo (the trivia misses)
  --all:   every name with no ESPN id (also the ones a Commons photo covers)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_legend_headshots as blh  # noqa: E402  (careers / id files / name key)

ROOT = blh.ROOT
OUT = os.path.join(ROOT, 'scripts', '_found_espn_ids.json')
SEARCH = 'https://site.api.espn.com/apis/search/v2?query=%s&limit=8'
ATHLETE = 'https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/%s'
SLEEP = 0.2
_session = None


def _get(url):
    """GET -> text (requests + certifi with the library's default headers, curl fallback)."""
    global _session
    try:
        import requests
        if _session is None:
            _session = requests.Session()
            try:
                import certifi
                _session.verify = certifi.where()
            except Exception:
                pass
        r = _session.get(url, timeout=30)
        r.raise_for_status()
        return r.text
    except ImportError:
        pass
    cp = subprocess.run(['curl', '-sS', '--fail', '--max-time', '30', url],
                        capture_output=True, text=True, encoding='utf-8')
    if cp.returncode != 0:
        raise RuntimeError('curl failed: ' + cp.stderr.strip()[:120])
    return cp.stdout


def search_players(name):
    try:
        d = json.loads(_get(SEARCH % urllib.parse.quote(name)))
    except Exception as e:
        return None, str(e)[:100]
    hits = []
    for r in d.get('results', []):
        if r.get('type') != 'player':
            continue
        for c in r.get('contents', []):
            if c.get('sport') != 'football' or c.get('description') != 'NFL':
                continue
            m = re.search(r'/id/(\d+)', (c.get('link') or {}).get('web', ''))
            if not m:
                continue
            hits.append({'id': m.group(1), 'displayName': c.get('displayName', ''), 'team': c.get('subtitle', '')})
    return hits, None


def athlete(eid):
    try:
        d = json.loads(_get(ATHLETE % eid))
    except Exception as e:
        return {'error': str(e)[:100]}
    a = d.get('athlete', d)
    hs = a.get('headshot')
    href = hs.get('href') if isinstance(hs, dict) else (hs if isinstance(hs, str) else None)
    return {'displayName': a.get('displayName', ''), 'age': a.get('age'),
            'position': (a.get('position') or {}).get('abbreviation', ''),
            'headshot': href or ''}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--all', action='store_true', help='every name with no ESPN id, not just the Commons misses')
    ap.add_argument('--names', nargs='*')
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()

    careers = blh.load_careers()
    espn = blh.load_espn_names()
    commons = blh.load_existing()
    notable = {n for n, s in careers.items() if blh.is_notable(s)}
    if args.names:
        names = list(args.names)
    else:
        names = [n for n in careers if n not in espn and (args.all or n not in commons)]
    if args.limit:
        names = names[:args.limit]
    print('checking %d names (%d notable)' % (len(names), sum(1 for n in names if n in notable)), flush=True)

    with_hs, no_hs, unmatched = [], [], []

    def save(i):
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump({'generated': time.strftime('%Y-%m-%d'), 'checked': i, 'with_headshot': with_hs,
                       'no_headshot': no_hs, 'unmatched': unmatched}, f, indent=1)

    for i, n in enumerate(names, 1):
        seasons = careers.get(n, [])
        last = max((s.get('yr') or 0) for s in seasons) if seasons else 0
        hits, err = search_players(n)
        time.sleep(SLEEP)
        if hits is None:
            unmatched.append({'name': n, 'reason': 'search failed: ' + err})
        else:
            match = [h for h in hits if blh._name_key(h['displayName']) == blh._name_key(n)]
            if not match:
                unmatched.append({'name': n, 'reason': 'no NFL player hit' if not hits
                                  else 'name mismatch: ' + ', '.join(h['displayName'] for h in hits[:3])})
            else:
                row = None
                grp = blh.legend_group(seasons)
                for h in match[:3]:           # namesakes: take the first whose position group / age fits
                    a = athlete(h['id'])
                    time.sleep(SLEEP)
                    pos = a.get('position', '')
                    if pos and blh.ESPN_GROUP.get(pos, pos) != grp:
                        continue
                    if isinstance(a.get('age'), (int, float)) and last and a['age'] < (2026 - last) + 21:
                        continue              # too young to have played that last season
                    row = {'name': n, 'id': h['id'], 'displayName': a.get('displayName') or h['displayName'],
                           'team': h['team'], 'position': pos, 'age': a.get('age'), 'lastSeason': last,
                           'notable': n in notable, 'has_commons': n in commons, 'headshot': a.get('headshot', '')}
                    break
                if row is None:
                    unmatched.append({'name': n, 'reason': 'hits failed position/age check: ' + ', '.join(h['id'] for h in match[:3])})
                elif row['headshot']:
                    with_hs.append(row)
                else:
                    no_hs.append(row)
        if i % 25 == 0:
            print('  %d/%d  with headshot %d, id only %d, unmatched %d' % (i, len(names), len(with_hs), len(no_hs), len(unmatched)), flush=True)
            save(i)

    save(len(names))
    print('\n== result ==')
    print('with headshot: %d (%d notable), id but no headshot: %d, unmatched: %d' % (
        len(with_hs), sum(1 for r in with_hs if r['notable']), len(no_hs), len(unmatched)))
    for r in with_hs:
        print('  %-22s %-8s %-3s %s%s' % (r['name'], r['id'], r['position'], r['team'], '  [notable]' if r['notable'] else ''))
    print('-> %s' % os.path.relpath(OUT, ROOT))


if __name__ == '__main__':
    main()
