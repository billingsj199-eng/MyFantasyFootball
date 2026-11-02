"""Permanent local archive of every ESPN headshot the site shows (2026-11-02).

Trivia, games and player profiles load faces straight from ESPN's CDN. If ESPN
swaps or deletes a headshot the site loses that face, so this keeps a copy of
every one OUTSIDE the repo (no git, no repo bloat):

    E:\\MyFantasyFootball\\headshot_archive\\
        nfl\\<id>.png                current NFL headshot
        nfl\\<id>.<YYYY-MM-DD>.png   older version, kept (dated the day it was
                                     replaced) when ESPN served a new one
        college\\<id>.png            CFB (devy) headshot, same layout
        manifest.json                one entry per "<kind>:<id>"
        changes.log                  JSON line per new / changed / gone / back event

Ids come from every table the site picks a headshot from:
  NFL      data/fallback_espn_ids.js (FALLBACK_IDS), data/retired_espn_ids.js
           (_BASE_RETIRED_IDS), data/daily_retired_pool.js (RETIRED_ESPN_IDS),
           data/headshot_espn_ids.js (BAKED_ESPN_IDS), the _slImg urls baked
           into data/d.js and the headshot urls in the p/*.html profile pages
  college  data/devy_headshots.js (DEVY_HEADSHOTS) + college _slImg urls in d.js
Active players the site resolves at runtime from ESPN rosters are covered by
BAKED_ESPN_IDS; names in BAKED_ESPN_MISSES have no id and are only counted.

Incremental: each fetch sends the stored ETag, so unchanged images come back
304 and are skipped; a 200 with the same sha256 is also a no-op. A different
image moves the old file to <id>.<date>.png first. A 404 for an id archived
before sets gone_since and never deletes the file; ids that never had an image
are kept as status "no_image" and re-checked each run. ESPN answers some ids
with a 200 fully transparent placeholder PNG: that counts as no image (or as
gone, if a real face was archived) and is never saved over a face.

Usage (from the checkout root):  python scripts/archive_headshots.py
  --archive DIR   archive folder (default E:\\MyFantasyFootball\\headshot_archive)
  --limit N       only the first N ids (testing)
  --workers N     parallel downloads (default 12)
"""
import argparse
import bisect
import datetime
import glob
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image  # hard dependency: without it blank placeholders would overwrite faces

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DEFAULT_ARCHIVE = r'E:\MyFantasyFootball\headshot_archive'
URLS = {
    'nfl': 'https://a.espncdn.com/i/headshots/nfl/players/full/{}.png',
    'college': 'https://a.espncdn.com/i/headshots/college-football/players/full/{}.png',
}
# name -> id tables: (file, variable whose object literal holds the pairs)
NFL_TABLES = [
    ('data/fallback_espn_ids.js', 'FALLBACK_IDS'),
    ('data/retired_espn_ids.js', '_BASE_RETIRED_IDS'),
    ('data/daily_retired_pool.js', 'RETIRED_ESPN_IDS'),
    ('data/headshot_espn_ids.js', 'BAKED_ESPN_IDS'),
]
PAIR = re.compile(r'''["']([^"'\n]{2,60})["']\s*:\s*["']?(\d{1,8})["']?''')
DEVY = re.compile(r'''"([^"\n]{2,60})"\s*:\s*\{\s*"id"\s*:\s*"?(\d{1,9})''')
HS_URL = re.compile(r'headshots/(nfl|college-football)/players/full/(\d{1,9})\.png')
D_NAME = re.compile(r'\{"n":"((?:[^"\\]|\\.)*)"')
TITLE = re.compile(r'<title>([^<(·]+)')
UA = 'Mozilla/5.0 (MFF headshot archive)'


def read(rel):
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        print('missing', rel)
        return ''
    with open(path, encoding='utf-8') as f:
        return f.read()


def object_body(src, var):
    """Text of the `var NAME = { ... }` literal (brace-matched; skips strings
    and comments, which hold apostrophes like "each id's headshot")."""
    m = re.search(r'\b' + re.escape(var) + r'\s*=\s*\{', src)
    if not m:
        return ''
    i, depth, quote, j = m.end() - 1, 0, None, m.end() - 1
    while j < len(src):
        c = src[j]
        if quote:
            if c == '\\':
                j += 1
            elif c == quote:
                quote = None
        elif src.startswith('//', j):
            j = src.find('\n', j)
            if j < 0:
                break
        elif src.startswith('/*', j):
            j = src.find('*/', j)
            if j < 0:
                break
            j += 1
        elif c in '"\'':
            quote = c
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    return src[i:]


def collect():
    """{(kind, id): {'names': set, 'sources': set}} plus the no-id name list."""
    found = {}

    def add(kind, aid, name, source):
        e = found.setdefault((kind, str(int(aid))), {'names': set(), 'sources': set()})
        if name:
            e['names'].add(name.strip())
        e['sources'].add(source)

    for rel, var in NFL_TABLES:
        body = object_body(read(rel), var)
        if not body:
            print('no', var, 'in', rel)
        for m in PAIR.finditer(body):
            add('nfl', m.group(2), m.group(1), var)

    devy = object_body(read('data/devy_headshots.js'), 'DEVY_HEADSHOTS')
    for m in DEVY.finditer(devy):
        add('college', m.group(2), m.group(1), 'DEVY_HEADSHOTS')

    d = read('data/d.js')
    starts = [(m.start(), m.group(1)) for m in D_NAME.finditer(d)]
    keys = [s for s, _ in starts]
    for m in HS_URL.finditer(d):
        k = bisect.bisect_right(keys, m.start()) - 1
        name = json.loads('"' + starts[k][1] + '"') if k >= 0 else ''
        add('nfl' if m.group(1) == 'nfl' else 'college', m.group(2), name, 'd.js')

    for path in glob.glob(os.path.join(ROOT, 'p', '*.html')):
        with open(path, encoding='utf-8') as f:
            html = f.read()
        t = TITLE.search(html)
        name = t.group(1).strip() if t else ''
        for m in HS_URL.finditer(html):
            add('nfl' if m.group(1) == 'nfl' else 'college', m.group(2), name, 'p/')

    misses = re.search(r'BAKED_ESPN_MISSES\s*=\s*(\[[^\]]*\])', read('data/headshot_espn_ids.js'))
    misses = json.loads(misses.group(1)) if misses else []
    return found, misses


def fetch(url, etag):
    """-> (status, body, etag, last_modified); status 'ERR' after 3 tries."""
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    if etag:
        req.add_header('If-None-Match', etag)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
                if not r.headers.get('Content-Type', '').startswith('image/') or not body:
                    return 404, None, None, None
                return 200, body, r.headers.get('ETag'), r.headers.get('Last-Modified')
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return 304, None, etag, None
            if e.code in (403, 404, 410):
                return 404, None, None, None
        except Exception:
            pass
        time.sleep(1 + 2 * attempt)
    return 'ERR', None, None, None


def is_blank(body):
    """ESPN answers some ids with a 200 fully transparent (or one-color) PNG."""
    try:
        im = Image.open(io.BytesIO(body))
        ext = im.getextrema()
    except Exception:
        return False
    if not isinstance(ext[0], tuple):
        ext = (ext,)
    if 'A' in im.getbands() and ext[im.getbands().index('A')][1] == 0:
        return True
    return all(lo == hi for lo, hi in ext)


def write_atomic(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


def version_path(folder, aid, day):
    path = os.path.join(folder, '{}.{}.png'.format(aid, day))
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, '{}.{}-{}.png'.format(aid, day, n))
        n += 1
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--archive', default=DEFAULT_ARCHIVE)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--workers', type=int, default=12)
    args = ap.parse_args()

    arch = args.archive
    for kind in URLS:
        os.makedirs(os.path.join(arch, kind), exist_ok=True)
    man_path = os.path.join(arch, 'manifest.json')
    manifest = {'entries': {}}
    if os.path.exists(man_path):
        with open(man_path, encoding='utf-8') as f:
            manifest = json.load(f)
    entries = manifest['entries']

    found, misses = collect()
    keys = sorted(found, key=lambda k: (k[0] != 'nfl', int(k[1])))
    if args.limit:
        keys = keys[:args.limit]
    by_kind = {k: sum(1 for x in keys if x[0] == k) for k in URLS}
    print('ids: {} ({})'.format(len(keys), ', '.join('{} {}'.format(n, k) for k, n in by_kind.items())))

    now = datetime.datetime.now()
    day, stamp = now.strftime('%Y-%m-%d'), now.isoformat(timespec='seconds')

    def work(key):
        kind, aid = key
        e = entries.get('{}:{}'.format(kind, aid), {})
        path = os.path.join(arch, kind, aid + '.png')
        etag = e.get('etag') if os.path.exists(path) else None
        url = URLS[kind].format(aid)
        return key, url, fetch(url, etag)

    counts = dict.fromkeys(['new', 'changed', 'unchanged', 'gone', 'back', 'no_image', 'error'], 0)
    events = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for (kind, aid), url, (status, body, etag, lastmod) in ex.map(work, keys):
            done += 1
            if done % 250 == 0:
                print('  {}/{}'.format(done, len(keys)))
            mk = '{}:{}'.format(kind, aid)
            info = found[(kind, aid)]
            e = entries.setdefault(mk, {'id': aid, 'kind': kind, 'url': url})
            e['names'] = sorted(set(e.get('names', [])) | info['names'])
            e['name'] = e['names'][0] if e['names'] else ''
            e['sources'] = sorted(set(e.get('sources', [])) | info['sources'])
            e['last_checked'] = stamp
            folder = os.path.join(arch, kind)
            path = os.path.join(folder, aid + '.png')
            had_file = os.path.exists(path)

            if status == 'ERR':
                counts['error'] += 1
                continue
            blank = status == 200 and is_blank(body)
            if status == 404 or blank:
                reason = 'blank' if blank else '404'
                if had_file:
                    if not e.get('gone_since'):
                        e['gone_since'] = day
                        events.append({'event': 'gone', 'key': mk, 'name': e['name'],
                                       'reason': reason})
                    e['status'] = 'gone'
                    e['gone_reason'] = reason
                    counts['gone'] += 1
                else:
                    e['status'] = 'no_image'
                    e['no_image_reason'] = reason
                    e.setdefault('no_image_since', day)
                    counts['no_image'] += 1
                continue

            if e.pop('gone_since', None):
                events.append({'event': 'back', 'key': mk, 'name': e['name']})
                counts['back'] += 1
            for k in ('no_image_since', 'no_image_reason', 'gone_reason'):
                e.pop(k, None)
            e['status'] = 'ok'
            if status == 304:
                e['last_seen'] = stamp
                counts['unchanged'] += 1
                continue

            sha = hashlib.sha256(body).hexdigest()
            if had_file and e.get('sha256') == sha:
                counts['unchanged'] += 1
            elif had_file:
                with open(path, 'rb') as f:
                    prev = f.read()
                old = version_path(folder, aid, day)
                os.replace(path, old)
                e.setdefault('versions', []).append({
                    'file': os.path.basename(old), 'sha256': hashlib.sha256(prev).hexdigest(),
                    'bytes': len(prev), 'first_seen': e.get('first_seen'),
                    'replaced': stamp})
                write_atomic(path, body)
                e['first_seen'] = stamp
                counts['changed'] += 1
                events.append({'event': 'changed', 'key': mk, 'name': e['name'],
                               'old': os.path.basename(old), 'sha256': sha})
            else:
                write_atomic(path, body)
                e['first_seen'] = stamp
                counts['new'] += 1
                events.append({'event': 'new', 'key': mk, 'name': e['name']})
            e.update(sha256=sha, bytes=len(body), last_seen=stamp,
                     etag=etag, last_modified=lastmod, file='{}/{}.png'.format(kind, aid))

    # Ids dropped from the site tables stay archived; flag them so they are not
    # mistaken for current.
    current = {'{}:{}'.format(*k) for k in found}
    for mk, e in entries.items():
        e['in_site_tables'] = mk in current

    archived = sum(1 for e in entries.values()
                   if e.get('file') and os.path.exists(os.path.join(arch, e['file'])))
    total_bytes = sum(e.get('bytes') or 0 for e in entries.values() if e.get('file'))
    manifest.update(updated=stamp, counts=counts, archived=archived,
                    no_id_names=sorted(misses))
    manifest['runs'] = (manifest.get('runs') or [])[-49:] + [
        {'at': stamp, 'checked': len(keys), 'archived': archived, **counts}]
    write_atomic(man_path, json.dumps(manifest, indent=1, sort_keys=True).encode('utf-8'))
    if events:
        with open(os.path.join(arch, 'changes.log'), 'a', encoding='utf-8') as f:
            for ev in events:
                f.write(json.dumps({'at': stamp, **ev}) + '\n')

    print('archived (on disk): {}  ({:.0f} MB)'.format(archived, total_bytes / 1e6))
    print('this run: new {new}, changed {changed}, unchanged {unchanged}, '
          'gone {gone}, back {back}, no image {no_image}, errors {error}'.format(**counts))
    print('names with no ESPN id (BAKED_ESPN_MISSES): {}'.format(len(misses)))
    lost = ['{} ({})'.format(ev['name'], ev['key']) for ev in events if ev['event'] == 'gone']
    print('newly gone this run: {}{}'.format(len(lost), ' - ' + ', '.join(lost) if lost else ''))
    if counts['error']:
        print('re-run to retry the {} errors'.format(counts['error']))
    return 1 if counts['error'] else 0


if __name__ == '__main__':
    sys.exit(main())
