#!/usr/bin/env python3
"""
research_ktc_pick_classes.py — how does KTC price the 2027 rookie class vs past
classes at the same point before their draft? (Jack 2026-10-09: "the consensus
is that 2027 class is supposed to be very good" -> "can we see how ktc ranks
2027 vs previous historically")

Step 1 (--find): locate KTC pick assets for past classes. KTC lists only the
current three pick years; each pick has a page /dynasty-rankings/players/<slug>
with its all-time value history (pd-oneqb / pd-superflex JSON), so past picks
are found by id. Ids are sequential per class (2027 Early/Mid/Late 1st =
1702/1703/1704, 2028 = 1882.., 2029 = 2126..).
Step 2: per class, value of the Early / Mid / Late 1st on the same calendar
days before its draft (Oct 9 of the prior year = now for 2027, plus Jan 15 and
Apr 1), absolute and relative to the market (that day's value of KTC's #12
and #24 overall player, from _dyn_cache/ktc_alltime.json) — so KTC inflation
over the years cancels.
Polite: 1 request every --delay seconds, cached in _dyn_cache/ktc_picks/.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, '_dyn_cache', 'ktc_picks')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36'


def get(url, tries=5):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html'})
    for t in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
                if raw[:2] == b'\x1f\x8b':   # Wayback sometimes serves the archived gzip body as-is
                    import gzip
                    raw = gzip.decompress(raw)
                return raw.decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            if e.code != 429 or t == tries - 1:
                raise
            time.sleep(150 * (t + 1))   # Wayback / KTC rate limit: back off
        except (TimeoutError, OSError):
            if t == tries - 1:
                raise
            time.sleep(30)


def page(slug, delay):
    os.makedirs(CACHE, exist_ok=True)
    fp = os.path.join(CACHE, slug + '.json')
    if os.path.exists(fp):
        return json.load(open(fp, encoding='utf-8'))
    try:
        h = get('https://keeptradecut.com/dynasty-rankings/players/' + slug)
    except Exception as e:
        rec = {'err': str(e)[:80]}
    else:
        rec = {}
        for fmt, tag in (('oneQB', 'pd-oneqb'), ('superflex', 'pd-superflex')):
            m = re.search(r'<script[^>]*id="' + tag + r'"[^>]*>(.*?)</script>', h, re.S)
            if m:
                try:
                    j = json.loads(m.group(1))
                    hist = j.get('overallValue') or []
                    rec[fmt] = {'d': [x['d'] for x in hist], 'v': [x['v'] for x in hist]}
                except Exception:
                    pass
        t = re.search(r'<title>(.*?)</title>', h, re.S)
        rec['title'] = t.group(1).strip() if t else ''
    json.dump(rec, open(fp, 'w', encoding='utf-8'))
    time.sleep(delay)
    return rec


def players_of(h):
    m = re.search(r'<script[^>]*id="ktc-players"[^>]*>(\[.*?\])\s*</script>', h, re.S)
    if m:
        return json.loads(m.group(1))
    m = re.search(r'var\s+playersArray\s*=\s*(\[.*?\]);', h, re.S)
    return json.loads(m.group(1)) if m else []


def val(p, fmt):
    v = p.get('oneQBValues' if fmt == '1qb' else 'superflexValues') or {}
    return v.get('value') if isinstance(v, dict) else None


def compare(stamps):
    """Next class's 1sts / 2nds at each snapshot vs that day's market (#12 / #24 player)."""
    srcs = [(ts, open(os.path.join(CACHE, 'wb_' + ts + '.html'), encoding='utf-8').read()) for ts in stamps]
    srcs.append(('today', open(os.path.join(HERE, '_dyn_cache', 'ktc_probe', 'rankings.html'), encoding='utf-8').read()))
    for fmt in ('1qb', 'sf'):
        print(f'\n=== {fmt.upper()}: next rookie class priced ~6 months before its draft ===')
        print(f'{"snapshot":<16}{"class":>6}{"#12 plyr":>9}{"#24 plyr":>9}  ' + ''.join(f'{g:>22}' for g in ('Early 1st', 'Mid 1st', 'Late 1st', 'Mid 2nd')))
        for ts, h in srcs:
            arr = players_of(h)
            yr = (dt.date.today().year if ts == 'today' else int(ts[:4])) + 1
            if ts != 'today' and int(ts[4:6]) < 6:
                yr = int(ts[:4])
            pl = sorted([val(p, fmt) for p in arr if not re.match(r'^\d{4} ', p.get('playerName') or '') and val(p, fmt)], reverse=True)
            allv = sorted([val(p, fmt) for p in arr if val(p, fmt)], reverse=True)
            if len(pl) < 30:
                print(f'{ts:<16} parse failed ({len(arr)} rows)'); continue
            b12, b24 = pl[11], pl[23]
            cells = []
            for g in ('Early 1st', 'Mid 1st', 'Late 1st', 'Mid 2nd'):
                p = next((p for p in arr if (p.get('playerName') or '') == f'{yr} {g}'), None)
                v = val(p, fmt) if p else None
                if not v:
                    cells.append(f'{"—":>22}'); continue
                rk = 1 + sum(1 for x in allv if x > v)
                cells.append(f'{v:>6} #{rk:<4} {v / b12:>5.2f}x12 {v / b24:>4.2f}x24'.rjust(22))
            print(f'{ts:<16}{yr:>6}{b12:>9}{b24:>9}  ' + ''.join(cells))
        print('   (#rank = overall rank among all KTC assets incl. picks; x12 / x24 = value / that day\'s #12 / #24 player)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--delay', type=float, default=4.0)
    ap.add_argument('--probe', nargs='*', default=[])
    ap.add_argument('--cdx', action='store_true', help='list Wayback snapshots of the rankings page')
    ap.add_argument('--snap', nargs='*', default=[], help='Wayback timestamps: pull pick names / ids / values')
    ap.add_argument('--compare', nargs='*', default=[], help='snapshot timestamps (cached) to compare + today')
    args = ap.parse_args()
    if args.cdx:
        u = ('http://web.archive.org/cdx/search/cdx?url=keeptradecut.com/dynasty-rankings&output=json'
             '&from=2021&to=2026&collapse=timestamp:6&fl=timestamp&limit=200')
        rows = json.loads(get(u))
        print(' '.join(r[0] for r in rows[1:]))
    for ts in args.snap:
        fp = os.path.join(CACHE, 'wb_' + ts + '.html')
        os.makedirs(CACHE, exist_ok=True)
        if not os.path.exists(fp) or os.path.getsize(fp) < 1000:
            body = get('http://web.archive.org/web/' + ts + 'id_/https://keeptradecut.com/dynasty-rankings')
            open(fp, 'w', encoding='utf-8').write(body)   # only after a successful fetch
            time.sleep(args.delay)
        h = open(fp, encoding='utf-8').read()
        m = re.search(r'<script[^>]*id="ktc-players"[^>]*>(\[.*?\])\s*</script>', h, re.S)
        arr = json.loads(m.group(1)) if m else None
        if arr is None:
            m = re.search(r'var\s+playersArray\s*=\s*(\[.*?\]);', h, re.S)
            arr = json.loads(m.group(1)) if m else []
        pk = [(p.get('playerName'), p.get('playerID'), p.get('slug'), (p.get('oneQBValues') or {}).get('value')) for p in arr if re.match(r'^\d{4} ', p.get('playerName') or '')]
        print(ts, len(arr), 'players;', ' | '.join(f'{n} {i} {v}' for n, i, s, v in pk if '1st' in n))
    if args.compare:
        compare(args.compare)
    for slug in args.probe:
        r = page(slug, args.delay)
        o = r.get('oneQB') or {}
        print(slug, r.get('err') or r.get('title', '')[:60], len(o.get('d', [])), (o.get('d') or [''])[0], (o.get('d') or [''])[-1])


if __name__ == '__main__':
    main()
