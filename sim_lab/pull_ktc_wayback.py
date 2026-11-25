#!/usr/bin/env python3
"""
pull_ktc_wayback.py - full-pool KTC dynasty snapshots from the Wayback Machine
(Jack 2026-11-24: "do full study on ktc dynasty ratings ... find players that
have lasting value").

Why Wayback: KTC's own all-time history only exists for players still listed
today (survivorship: busts and retirees are gone). An archived rankings page
carries the WHOLE list as it stood that day (playersArray JSON: value, rank,
age, experience, draft round/pick, height/weight, team), so who lost
everything is in the data.

One capture per month (CDX collapse=timestamp:6), polite one-off, cached.
Output: _dyn_cache/ktc_wb/wb_<timestamp>.json  (parsed list only) and
        _dyn_cache/ktc_wb/index.json            ({timestamp: n_players})
Usage: python pull_ktc_wayback.py [--delay 2.0]
"""
import argparse
import json
import os
import re
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '_dyn_cache', 'ktc_wb')
CDX = ('https://web.archive.org/cdx/search/cdx?url=keeptradecut.com/dynasty-rankings&output=json'
       '&filter=statuscode:200&filter=mimetype:text/html&collapse=timestamp:6&fl=timestamp&from=2020&to=2026')
UA = 'Mozilla/5.0 (research script; one-off archive read)'


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                b = r.read()
            if b[:2] == b'\x1f\x8b':      # id_ replays the original bytes: some captures are stored gzipped
                import gzip
                b = gzip.decompress(b)
            return b.decode('utf-8', errors='replace')
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(5 * (i + 1))
    raise err


def parse(html):
    m = re.search(r'var playersArray\s*=\s*(\[.*?\]);\s*\n', html, re.S)
    if not m:
        m = re.search(r'<script[^>]*id="ktc-players"[^>]*>(\[.*?\])\s*</script>', html, re.S)
    if m:
        return json.loads(m.group(1))
    # 2020 / early-2021 pages embed every player's daily history, so the archived body
    # is cut at 1 MB mid-array: salvage the complete objects (the list is value-ordered,
    # so this is the top ~85-105 players of that day - flagged partial by its size).
    i = html.find('var playersArray')
    if i < 0:
        return None
    i = html.find('[', i)
    dec, out, pos = json.JSONDecoder(), [], i + 1
    while True:
        while pos < len(html) and html[pos] in ', \r\n\t':
            pos += 1
        try:
            obj, pos = dec.raw_decode(html, pos)
        except ValueError:
            break
        out.append(obj)
    return out or None


KEEP = ('playerName', 'playerID', 'slug', 'position', 'team', 'rookie', 'age', 'heightFeet', 'heightInches',
        'weight', 'seasonsExperience', 'pickRound', 'pickNum', 'birthday', 'draftYear', 'college', 'injury')


def slim(p):
    o = {k: p.get(k) for k in KEEP if k in p}
    for fmt in ('oneQBValues', 'superflexValues'):
        v = p.get(fmt) or {}
        o[fmt] = {k: v.get(k) for k in ('value', 'rank', 'positionalRank', 'overallTier', 'positionalTier',
                                         'overall7DayTrend', 'kept', 'traded', 'cut') if k in v}
        tep = v.get('tep') or {}
        if tep:
            o[fmt]['tepValue'] = tep.get('value')
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--delay', type=float, default=2.0)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    stamps = [r[0] for r in json.loads(get(CDX))[1:]]
    idx = {}
    for ts in stamps:
        f = os.path.join(OUT, 'wb_%s.json' % ts)
        if os.path.exists(f):
            idx[ts] = len(json.load(open(f, encoding='utf-8')))
            continue
        time.sleep(args.delay)
        try:
            html = get('https://web.archive.org/web/%sid_/https://keeptradecut.com/dynasty-rankings' % ts)
        except Exception as e:  # noqa: BLE001
            print(ts, 'FETCH FAIL', e, flush=True)
            continue
        P = parse(html)
        if not P:
            print(ts, 'no player json (len %d)' % len(html), flush=True)
            continue
        S = [slim(p) for p in P]
        json.dump(S, open(f, 'w', encoding='utf-8'))
        idx[ts] = len(S)
        print(ts, len(S), flush=True)
    json.dump(idx, open(os.path.join(OUT, 'index.json'), 'w'), indent=0)
    print('done:', len(idx), 'snapshots')


if __name__ == '__main__':
    main()
