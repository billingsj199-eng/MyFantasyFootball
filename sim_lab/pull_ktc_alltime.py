#!/usr/bin/env python3
"""
pull_ktc_alltime.py — KTC all-time player histories (Jack 2026-10-09).

Each KTC player page embeds that player's full daily history since 2021-03-21
(`<script id="pd-oneqb">` / `pd-superflex`: overallValue, overallRankHistory,
positionalRankHistory). Pages are ~4 MB (the whole player list rides along), so
this is a polite one-off: the top N current QB/RB/WR/TE by 1QB value, one page
every DELAY seconds, keeping only the histories.

Output: _dyn_cache/ktc_alltime.json
  {fetched, players: {name: {id, pos, slug, oneQB: {d: [...], v: [...], ovr: [...], pos: [...]}, superflex: {...}}}}
Usage: python pull_ktc_alltime.py [--top 150] [--delay 2.0]
"""
import argparse
import datetime
import json
import os
import re
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '_dyn_cache', 'ktc_alltime.json')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode('utf-8', errors='replace')


def series(o):
    vals = o.get('overallValue') or []
    ovr = {x['d']: x['v'] for x in o.get('overallRankHistory') or []}
    pos = {x['d']: x['v'] for x in o.get('positionalRankHistory') or []}
    d = [x['d'] for x in vals]
    return {'d': d, 'v': [x['v'] for x in vals], 'ovr': [ovr.get(k) for k in d], 'pos': [pos.get(k) for k in d]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=150)
    ap.add_argument('--delay', type=float, default=2.0)
    args = ap.parse_args()
    html = get('https://keeptradecut.com/dynasty-rankings')
    m = re.search(r'<script[^>]*id="ktc-players"[^>]*>(\[.*?\])\s*</script>', html, re.S)
    players = [p for p in json.loads(m.group(1)) if p.get('position') in ('QB', 'RB', 'WR', 'TE')]
    players.sort(key=lambda p: -((p.get('oneQBValues') or {}).get('value') or 0))
    players = players[:args.top]
    out = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {'players': {}}
    done = 0
    for i, p in enumerate(players):
        name = p['playerName']
        if name in out['players']:
            continue
        time.sleep(args.delay)
        try:
            h = get('https://keeptradecut.com/dynasty-rankings/players/' + p['slug'])
            rec = {'id': p['playerID'], 'pos': p['position'], 'slug': p['slug']}
            for fmt, tag in (('oneQB', 'pd-oneqb'), ('superflex', 'pd-superflex')):
                mm = re.search(r'id="' + tag + r'"[^>]*>(.*?)</script>', h, re.S)
                if mm:
                    rec[fmt] = series(json.loads(mm.group(1)))
            out['players'][name] = rec
            done += 1
        except Exception as e:
            print(f'  {name}: {e}')
        if done and done % 10 == 0:
            out['fetched'] = datetime.datetime.now().isoformat(timespec='seconds')
            json.dump(out, open(OUT, 'w', encoding='utf-8'), separators=(',', ':'))
            print(f'{i + 1}/{len(players)} pages ({done} new)', flush=True)
    out['fetched'] = datetime.datetime.now().isoformat(timespec='seconds')
    json.dump(out, open(OUT, 'w', encoding='utf-8'), separators=(',', ':'))
    print(f'done: {len(out["players"])} players in {OUT}')


if __name__ == '__main__':
    main()
