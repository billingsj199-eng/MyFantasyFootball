#!/usr/bin/env python3
"""Backfill full-league fantasy season totals for 1970-1998 (Fantasy Game ANY YEAR filter).

Source: Pro-Football-Reference per-season fantasy pages
    https://www.pro-football-reference.com/years/{Y}/fantasy.htm
PFR answers scripted requests with 403, so each page is fetched from the Internet
Archive's copy (availability API -> raw `id_` snapshot) when the direct request is refused.
Past seasons never change, so any snapshot is current. Raw HTML is cached under
scripts/_cache/pfr_fantasy/ (git-ignored); re-runs parse from the cache.

Output: data/season_totals_1970_1998.js
    const SEASON_TOTALS_7098 = { "<pfr_id>": { n, pos, y: [firstYr, lastYr], by: birthYr?,
        seasons: [ {yr, gp, tm, py, ptd, int, ra, ry, rtd, rc, rcy, rctd, fl, fpts} ] } };
    // zero stats omitted; y spans every PFR row 1970-98 (seasons below --min-fpts are dropped)
    const SEASON_TOTALS_7098_NAMES = { "<name>": ["<pfr_id>", ...] };
    const SEASON_TOTALS_7098_TEAMS = { "<code>": [[y1, y2, "Franchise Name"], ...] };
Keyed by PFR id so same-name players stay separate (the 2026-10-28 retired weekly
merge bug came from name keys).

fpts = the LEGEND_CAREERS basis (half-PPR, INT -1, FL -2), rounded to 0.1:
    py/25 + ptd*4 - int + ry/10 + rtd*6 + rc*0.5 + rcy/10 + rctd*6 - fl*2
Verified against 7,526 of 7,527 pre-1999 LEGEND_CAREERS rows.

Usage:
    python -I scripts/pull_pfr_season_totals.py            # fetch missing years, build file
    python -I scripts/pull_pfr_season_totals.py --years 1975 1988
    python -I scripts/pull_pfr_season_totals.py --min-fpts 10 --no-fetch
"""
import argparse
import json
import os
import re
import sys
import time
from html.parser import HTMLParser

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, '_cache', 'pfr_fantasy')
OUT = os.path.join(ROOT, 'data', 'season_totals_1970_1998.js')
YEARS = list(range(1970, 1999))
PFR_URL = 'https://www.pro-football-reference.com/years/{y}/fantasy.htm'
UA = 'Mozilla/5.0 (compatible; MyFantasyFootball season-totals backfill)'
DELAY = 4.0
# PFR's season fantasy pages have no fumbles-lost column before 1994 (fumbles only). For those
# years fl = round(fumbles * FL_RATE); FL_RATE = league fumbles-lost share measured on the
# 1994-98 pages (1,485 of 2,726 fumbles). LEGEND_CAREERS keeps its own fl for the legends.
FL_RATE = 0.545


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- fetching
def fetch_direct(y):
    r = requests.get(PFR_URL.format(y=y), headers={'User-Agent': UA}, timeout=30)
    if r.status_code == 200 and 'id="fantasy"' in r.text:
        return r.text
    log(f'  direct {y}: HTTP {r.status_code}')
    return None


def fetch_wayback(y):
    url = PFR_URL.format(y=y)
    a = requests.get('https://archive.org/wayback/available', params={'url': url}, timeout=30)
    snap = (a.json().get('archived_snapshots') or {}).get('closest') or {}
    if not snap.get('available'):
        log(f'  wayback {y}: no snapshot')
        return None
    ts = snap['timestamp']
    raw = f'https://web.archive.org/web/{ts}id_/{url}'
    for attempt in range(4):
        try:
            r = requests.get(raw, headers={'User-Agent': UA}, timeout=60)
        except requests.exceptions.ConnectionError as e:  # archive.org refuses bursts; back off
            log(f'  wayback {y}: connection refused (try {attempt + 1}): {str(e)[:80]}')
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code == 200 and 'id="fantasy"' in r.text:
            log(f'  wayback {y}: snapshot {ts} ({len(r.text)//1024} KB)')
            return r.text
        log(f'  wayback {y}: HTTP {r.status_code} (try {attempt + 1})')
        time.sleep(10 * (attempt + 1))
    return None


def get_html(y, allow_fetch=True):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f'{y}.html')
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            return f.read()
    if not allow_fetch:
        return None
    html = None
    try:
        html = fetch_direct(y)
    except Exception as e:  # noqa: BLE001
        log(f'  direct {y}: {e}')
    if html is None:
        time.sleep(1.5)
        try:
            html = fetch_wayback(y)
        except Exception as e:  # noqa: BLE001
            log(f'  wayback {y}: {e}')
    if html:
        with open(p, 'w', encoding='utf-8') as f:
            f.write(html)
    time.sleep(DELAY)
    return html


# ---------------------------------------------------------------- parsing
class FantasyTable(HTMLParser):
    """Collects rows of table#fantasy as {data-stat: {text, href}}."""

    def __init__(self):
        super().__init__()
        self.in_table = False
        self.depth = 0
        self.rows = []
        self.row = None
        self.cell = None
        self.cell_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'table' and a.get('id') == 'fantasy':
            self.in_table = True
            self.depth = 0
        if not self.in_table:
            return
        if tag == 'table':
            self.depth += 1
        elif tag == 'tr':
            self.row = {'_cls': a.get('class', '')}
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = {'stat': a.get('data-stat', ''), 'text': '', 'href': None, 'title': None}
        elif tag == 'a' and self.cell is not None and self.cell['href'] is None:
            self.cell['href'] = a.get('href')
            self.cell['title'] = a.get('title')

    def handle_endtag(self, tag):
        if not self.in_table:
            return
        if tag == 'table':
            if self.depth == 0:
                self.in_table = False
            else:
                self.depth -= 1
        elif tag in ('td', 'th') and self.cell is not None and self.row is not None:
            self.row[self.cell['stat']] = self.cell
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell['text'] += data


def num(cell):
    if not cell:
        return 0
    t = cell['text'].strip().replace(',', '')
    if t in ('', '-'):
        return 0
    try:
        return int(t)
    except ValueError:
        try:
            return float(t)
        except ValueError:
            return 0


def txt(cell):
    return cell['text'].strip() if cell else ''


# PFR renamed data-stat attributes in 2024; accept both generations.
STAT_KEYS = {
    'player': ('player', 'name_display'),
    'team': ('team', 'team_name_abbr'),
    'pos': ('fantasy_pos', 'pos'),
    'age': ('age',),
    'g': ('g', 'games'),
    'pass_yds': ('pass_yds',),
    'pass_td': ('pass_td',),
    'pass_int': ('pass_int',),
    'rush_att': ('rush_att',),
    'rush_yds': ('rush_yds',),
    'rush_td': ('rush_td',),
    'rec': ('rec',),
    'rec_yds': ('rec_yds',),
    'rec_td': ('rec_td',),
    'fumbles_lost': ('fumbles_lost',),
    'fumbles': ('fumbles',),
    'pass_att': ('pass_att',),
    'two_pt_md': ('two_pt_md',),
    'fantasy_points': ('fantasy_points',),
}


def pick(row, key):
    for k in STAT_KEYS[key]:
        if k in row:
            return row[k]
    return None


def fpts_half(s):
    v = (s['py'] / 25 + s['ptd'] * 4 - s['int'] + s['ry'] / 10 + s['rtd'] * 6
         + s['rc'] * 0.5 + s['rcy'] / 10 + s['rctd'] * 6 - s['fl'] * 2)
    return round(v + 1e-9, 1)


def infer_pos(s):
    if s['pa'] >= 20 and s['pa'] > 2 * s['ra']:
        return 'QB'
    if s['rc'] > s['ra']:
        return 'WR'
    return 'RB'


POS_MAP = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'TE': 'TE', 'FB': 'RB', 'HB': 'RB', 'FL': 'WR', 'SE': 'WR', 'E': 'TE'}


def parse_year(y, html, stats):
    p = FantasyTable()
    p.feed(html)
    out = []
    has_fl = any(num(pick(row, 'fumbles_lost')) > 0 for row in p.rows if pick(row, 'player'))
    if not has_fl:
        stats['fl_estimated_years'].append(y)
    for row in p.rows:
        if 'thead' in row['_cls'] or 'player' not in row and 'name_display' not in row:
            continue
        pc = pick(row, 'player')
        if not pc or not pc['href']:
            continue
        m = re.search(r'/players/[A-Za-z]/([A-Za-z0-9.\'-]+)\.htm', pc['href'])
        if not m:
            continue
        pid = m.group(1)
        name = txt(pc).replace('*', '').replace('+', '').strip()
        s = {
            'yr': y,
            'gp': int(num(pick(row, 'g'))),
            'tm': txt(pick(row, 'team')),
            'py': int(num(pick(row, 'pass_yds'))),
            'ptd': int(num(pick(row, 'pass_td'))),
            'int': int(num(pick(row, 'pass_int'))),
            'pa': int(num(pick(row, 'pass_att'))),
            'ra': int(num(pick(row, 'rush_att'))),
            'ry': int(num(pick(row, 'rush_yds'))),
            'rtd': int(num(pick(row, 'rush_td'))),
            'rc': int(num(pick(row, 'rec'))),
            'rcy': int(num(pick(row, 'rec_yds'))),
            'rctd': int(num(pick(row, 'rec_td'))),
            'fl': int(num(pick(row, 'fumbles_lost'))) if has_fl else int(round(num(pick(row, 'fumbles')) * FL_RATE)),
        }
        s['fpts'] = fpts_half(s)
        raw_pos = txt(pick(row, 'pos')).upper()
        pos = POS_MAP.get(raw_pos)
        if raw_pos and pos is None:
            stats['skipped_pos'][raw_pos] = stats['skipped_pos'].get(raw_pos, 0) + 1
            continue
        if pos is None:
            pos = infer_pos(s)
            stats['inferred_pos'] += 1
        age = int(num(pick(row, 'age'))) or None
        tc = pick(row, 'team')
        if tc and tc.get('title') and s['tm'] and not s['tm'].endswith('TM'):
            stats['teams'].setdefault(s['tm'], {}).setdefault(tc['title'], set()).add(y)
        out.append((pid, name, pos, age, s))
    return out


# ---------------------------------------------------------------- build
def build(years, min_fpts, allow_fetch):
    players = {}
    all_years = {}  # every PFR row, including seasons below min_fpts (career span)
    stats = {'skipped_pos': {}, 'inferred_pos': 0, 'rows': 0, 'kept': 0, 'missing_years': [], 'teams': {}, 'fl_estimated_years': []}
    per_year = {}
    for y in years:
        html = get_html(y, allow_fetch)
        if not html:
            stats['missing_years'].append(y)
            continue
        rows = parse_year(y, html, stats)
        per_year[y] = len(rows)
        for pid, name, pos, age, s in rows:
            stats['rows'] += 1
            all_years.setdefault(pid, set()).add(y)
            if s['fpts'] < min_fpts:
                continue
            stats['kept'] += 1
            pl = players.setdefault(pid, {'n': name, 'pos': {}, 'seasons': [], '_ages': []})
            pl['pos'][pos] = pl['pos'].get(pos, 0) + s['fpts']
            if age:
                pl['_ages'].append((y, age))
            pl['seasons'].append(s)
    for pid, pl in players.items():
        pl['y'] = [min(all_years[pid]), max(all_years[pid])]
    return players, stats, per_year


def compact(s):
    o = {'yr': s['yr'], 'gp': s['gp'], 'tm': s['tm']}
    for k in ('py', 'ptd', 'int', 'ra', 'ry', 'rtd', 'rc', 'rcy', 'rctd', 'fl'):
        if s[k]:
            o[k] = s[k]
    o['fpts'] = s['fpts']
    return o


def team_map(teams):
    """code -> [[y1, y2, full franchise name], ...] (codes like BAL/STL/HOU change franchise)."""
    out = {}
    for code, by_name in sorted(teams.items()):
        spans = []
        for full, yrs in by_name.items():
            spans.append([min(yrs), max(yrs), full])
        spans.sort()
        out[code] = spans
    return out


def write_js(players, teams):
    db = {}
    names = {}
    for pid, pl in sorted(players.items()):
        pos = max(pl['pos'].items(), key=lambda kv: kv[1])[0]  # position with the most points
        seasons = sorted(pl['seasons'], key=lambda s: s['yr'])
        entry = {'n': pl['n'], 'pos': pos, 'y': pl['y'], 'seasons': [compact(s) for s in seasons]}
        if pl['_ages']:
            y0, a0 = pl['_ages'][0]
            entry['by'] = y0 - a0  # approximate birth year (season year - listed age)
        db[pid] = entry
        names.setdefault(pl['n'], []).append(pid)
    js = ('// Full-league fantasy season totals 1970-1998 for the Fantasy Game ANY YEAR / ERA\n'
          '// filters (pre-1999 careers were legends-only). Source: Pro-Football-Reference season\n'
          '// fantasy pages; built by scripts/pull_pfr_season_totals.py. Keyed by PFR player id so\n'
          '// same-name players stay separate. fpts = half-PPR (INT -1, FL -2), same basis as\n'
          '// LEGEND_CAREERS; zero stats omitted. tm = PFR team code (2TM = multi-team season).\n'
          '// fl before 1994 = round(fumbles * 0.545): PFR lists no fumbles-lost column for those years.\n'
          'const SEASON_TOTALS_7098=' + json.dumps(db, separators=(',', ':'), ensure_ascii=False) + ';\n'
          'const SEASON_TOTALS_7098_NAMES=' + json.dumps(names, separators=(',', ':'), ensure_ascii=False) + ';\n'
          '// PFR team code -> [[firstYr, lastYr, franchise name that season], ...]\n'
          'const SEASON_TOTALS_7098_TEAMS=' + json.dumps(team_map(teams), separators=(',', ':'), ensure_ascii=False) + ';\n')
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(js)
    return len(db), len(js)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', nargs='*', type=int, default=YEARS)
    ap.add_argument('--min-fpts', type=float, default=10.0, help='drop seasons below this (default 10)')
    ap.add_argument('--no-fetch', action='store_true', help='parse cache only')
    ap.add_argument('--no-write', action='store_true')
    args = ap.parse_args()

    players, stats, per_year = build(args.years, args.min_fpts, not args.no_fetch)
    log('rows per year:', ' '.join(f'{y}:{n}' for y, n in sorted(per_year.items())))
    log(f"parsed {stats['rows']} rows, kept {stats['kept']} (>= {args.min_fpts} fpts), "
        f"{len(players)} players; inferred pos {stats['inferred_pos']}; skipped pos {stats['skipped_pos']}")
    log('fl estimated from total fumbles (no FL column) for:', stats['fl_estimated_years'])
    if stats['missing_years']:
        log('MISSING YEARS (no HTML):', stats['missing_years'])
    if args.no_write:
        return
    n, size = write_js(players, stats['teams'])
    log(f'wrote {OUT}: {n} players, {size/1024/1024:.2f} MB')


if __name__ == '__main__':
    main()
