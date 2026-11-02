"""Birth year of the Wikipedia article behind each legend photo -> data/legend_photo_birth_years.js (2026-11-02).

data/legend_headshots.js maps a NAME to a Wikipedia/Commons photo, and a few matches are a
later namesake (the 1970s Bears' George Farmer -> "George Farmer (running back)", a USC photo
from 2012; the Panthers RB Anthony Johnson -> "Anthony Johnson (wide receiver)"). The trivia
face lookup refuses a legend photo whose article subject was not of playing age (19-46) in
the board's year. Birth dates come from Wikidata (P569) via the article title.

Usage (from the checkout root):  python scripts/pull_legend_photo_birth_years.py
Then bump the ?v= on data/legend_photo_birth_years.js in index.html.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SRC = os.path.join(ROOT, 'data', 'legend_headshots.js')
OUT = os.path.join(ROOT, 'data', 'legend_photo_birth_years.js')
WIKIDATA = 'https://www.wikidata.org/w/api.php'
UA = 'MyFantasyFootball-legend-photo-birth-years/1.0 (billingsj199@gmail.com)'


def http_get(url):
    """requests (certifi) when available, else curl — urllib hit an expired-certificate
    error against Wikimedia here (same as build_legend_headshots.py)."""
    try:
        import requests
        try:
            import certifi
            verify = certifi.where()
        except Exception:
            verify = True
        r = requests.get(url, headers={'User-Agent': UA}, timeout=60, verify=verify)
        r.raise_for_status()
        return r.text
    except ImportError:
        cp = subprocess.run(['curl', '-sS', '--fail', '-A', UA, '--max-time', '60', url],
                            capture_output=True, text=True, encoding='utf-8')
        if cp.returncode != 0:
            raise RuntimeError('curl failed: ' + cp.stderr.strip()[:200])
        return cp.stdout


def load_pages():
    with open(SRC, encoding='utf-8') as f:
        txt = f.read()
    body = txt[txt.index('{'):txt.rindex('}') + 1]
    table = json.loads(body)
    pages = {}
    for name, rec in table.items():
        page = (rec or {}).get('page') or ''
        m = re.match(r'https?://en\.wikipedia\.org/wiki/(.+)$', page)
        if m:
            pages[name] = urllib.parse.unquote(m.group(1)).replace('_', ' ')
    return pages


def birth_years(titles):
    out = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        q = urllib.parse.urlencode({'action': 'wbgetentities', 'sites': 'enwiki', 'titles': '|'.join(chunk),
                                    'props': 'claims|sitelinks', 'sitefilter': 'enwiki', 'format': 'json'})
        for attempt in range(4):
            try:
                data = json.loads(http_get(WIKIDATA + '?' + q))
                break
            except Exception as e:
                print('  ! retry', str(e)[:100])
                time.sleep(3 * (attempt + 1))
        else:
            raise RuntimeError('giving up')
        for ent in (data.get('entities') or {}).values():
            title = ((ent.get('sitelinks') or {}).get('enwiki') or {}).get('title')
            for c in (ent.get('claims') or {}).get('P569', []):
                t = (((c.get('mainsnak') or {}).get('datavalue') or {}).get('value') or {}).get('time') or ''
                m = re.match(r'[+-](\d{4})', t)
                if title and m:
                    out[title] = int(m.group(1))
                    break
        print(min(i + 50, len(titles)), '/', len(titles))
        time.sleep(0.5)
    return out


def main():
    pages = load_pages()
    years = birth_years(sorted(set(pages.values())))
    table = {n: years[t] for n, t in sorted(pages.items()) if t in years}
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write('/* Generated ' + time.strftime('%Y-%m-%d') + ' by scripts/pull_legend_photo_birth_years.py — legend name ->\n'
                '   birth year of the Wikipedia article its photo comes from (Wikidata P569). The trivia\n'
                '   face lookup refuses the photo when that person was not 19-46 in the board year. */\n'
                'window.LEGEND_PHOTO_BIRTH_YEARS = ' + json.dumps(table, separators=(',', ':'), ensure_ascii=False) + ';\n')
    print('wrote', OUT, len(table), 'of', len(pages), 'article pages')


if __name__ == '__main__':
    sys.exit(main())
