#!/usr/bin/env python3
"""Backfill per-game (weekly) stat lines for every NFL skill player, 1970-1998, from
Pro-Football-Reference box scores, so the Fantasy Game WEEK filter, Elite Pull best-week
pools and the player-card game logs reach back to 1970 (nflverse weekly data starts 1999).

Pages:
    /years/{Y}/games.htm                 schedule -> box-score ids + week numbers
    /boxscores/{YYYYMMDD0}{home}.htm     "Passing, Rushing, & Receiving" table (#player_offense)

PFR answers scripted requests with a Cloudflare challenge (403), so every page is read from
the Internet Archive's copy (availability API -> raw `id_` snapshot, CDX fallback) after one
direct attempt per run. Past seasons never change, so any snapshot that carries the modern
#player_offense table is current. Raw HTML is gzip-cached OUTSIDE the repo
(E:\\MyFantasyFootball\\pfr_cache, override with MFF_PFR_CACHE); parsed games are kept per
season in <cache>/parsed/{Y}.json; progress lives in <cache>/boxscores_state.json. Everything
is resumable: cached pages are never re-fetched, so the fetch can run over several nights.

Output (built from the parsed games, era-split, each <= ~4 MB):
    data/weekly_stats_1970s.js   1970-1979
    data/weekly_stats_1980s.js   1980-1989
    data/weekly_stats_1990s.js   1990-1998
Shape (keyed by PFR id, NOT name — same-name merges were a real bug 2026-10-28):
    window.WEEKLY_STATS_LEGACY["PaytWa00"] = {n:"Walter Payton", pos:"RB", seasons:{
        "1977":[{wk:10, tm:"CHI", opp:"MIN", fpts:34.6, ra:40, ry:275, rtd:1, rec:1, rcy:6}, ...]}}
Rows use the site's weekly basis (same as weekly_stats_retired / ALL_PLAYERS_WEEKLY):
    fpts = py*0.04 + ptd*4 - int*2 + ry*0.1 + rtd*6 + rec*0.5 + rcy*0.1 + rctd*6 - fl*2
(half-PPR, INT -2). Zero stats are omitted; tgt/fl appear only when the box score has the
column. Playoff games are kept but flagged po:1 with wk 19 (WildCard) / 20 (Division) /
21 (ConfChamp) / 22 (SuperBowl) so gwIsRegWeek() keeps them out of the Fantasy Game.
tm/opp use the site's modern franchise abbreviations (Oilers -> TEN, Colts -> IND, ...).

Usage:
    python -I scripts/pull_pfr_boxscores.py --schedules          # 29 schedule pages
    python -I scripts/pull_pfr_boxscores.py --fetch [--limit N] [--years 1977 1984]
    python -I scripts/pull_pfr_boxscores.py --build              # write the data files
    python -I scripts/pull_pfr_boxscores.py --xcheck [--n 50]    # vs season totals
    python -I scripts/pull_pfr_boxscores.py --status
    python -I scripts/pull_pfr_boxscores.py --nightly            # Task Scheduler entry point:
        fetch until --until 06:30 (or --max-minutes), then build if anything changed.
"""
import argparse
import datetime as dt
import gzip
import json
import os
import random
import re
import sys
import time
from html.parser import HTMLParser

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.environ.get('MFF_PFR_CACHE') or r'E:\MyFantasyFootball\pfr_cache'
SCHED_DIR = os.path.join(CACHE, 'schedules')
BOX_DIR = os.path.join(CACHE, 'boxscores')
PARSED_DIR = os.path.join(CACHE, 'parsed')
STATE_PATH = os.path.join(CACHE, 'boxscores_state.json')
LOG_PATH = os.path.join(CACHE, 'boxscores_log.txt')
DATA_DIR = os.path.join(ROOT, 'data')

YEARS = list(range(1970, 1999))
ERAS = [('1970s', 1970, 1979), ('1980s', 1980, 1989), ('1990s', 1990, 1998)]
PFR = 'https://www.pro-football-reference.com'
UA = 'Mozilla/5.0 (compatible; MyFantasyFootball weekly backfill; +https://myfantasyfootball.co)'
DELAY = 4.0           # seconds between page fetches (archive.org and PFR alike)
PLAYOFF_WK = {'WildCard': 19, 'Wild Card': 19, 'Division': 20, 'ConfChamp': 21, 'SuperBowl': 22, 'Super Bowl': 22}

S = requests.Session()
S.headers['User-Agent'] = UA
_direct_blocked = False
_last_fetch = 0.0


def log(*a):
    msg = ' '.join(str(x) for x in a)
    print(msg, flush=True)
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S ') + msg + '\n')
    except OSError:
        pass


# ---------------------------------------------------------------- state
def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {'schedules': {}, 'missing': {}, 'codes': {}, 'runs': []}


def save_state(st):
    os.makedirs(CACHE, exist_ok=True)
    tmp = STATE_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(st, f, indent=1)
    os.replace(tmp, STATE_PATH)


# ---------------------------------------------------------------- fetching
def _pace():
    global _last_fetch
    wait = DELAY - (time.time() - _last_fetch)
    if wait > 0:
        time.sleep(wait)
    _last_fetch = time.time()
    _heartbeat()


def _get(url, **kw):
    """GET with archive.org-friendly retries (429/503 -> back off)."""
    for attempt in range(4):
        try:
            r = S.get(url, timeout=kw.pop('timeout', 90), **kw)
        except requests.RequestException as e:
            log(f'    net error {e.__class__.__name__}; retry {attempt + 1}')
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code in (429, 503, 502, 504):
            log(f'    HTTP {r.status_code} from {url.split("/")[2]}; sleeping {60 * (attempt + 1)}s')
            time.sleep(60 * (attempt + 1))
            continue
        return r
    return None


def fetch_direct(path, validator):
    global _direct_blocked
    if _direct_blocked:
        return None
    _pace()
    r = _get(PFR + path, timeout=30)
    if r is not None and r.status_code == 200 and validator(r.text):
        return r.text
    code = r.status_code if r is not None else 'n/a'
    log(f'  direct PFR {path}: HTTP {code} -> Wayback only for this run')
    _direct_blocked = True
    return None


def wayback_timestamps(url):
    """Newest-first snapshot timestamps: availability API first (1 call), CDX as backup."""
    out = []
    try:
        a = _get('https://archive.org/wayback/available', params={'url': url, 'timestamp': '20260101'}, timeout=60)
        snap = ((a.json().get('archived_snapshots') or {}).get('closest') or {}) if a is not None else {}
        if snap.get('available') and snap.get('timestamp'):
            out.append(snap['timestamp'])
    except (ValueError, AttributeError):
        pass
    return out


def wayback_timestamps_cdx(url):
    try:
        r = _get('https://web.archive.org/cdx/search/cdx',
                 params={'url': url, 'output': 'json', 'fl': 'timestamp,statuscode', 'filter': 'statuscode:200', 'limit': '-8'},
                 timeout=120)
        rows = r.json()[1:] if r is not None and r.status_code == 200 and r.text.strip() else []
        return [x[0] for x in reversed(rows)]
    except (ValueError, AttributeError):
        return []


def cdx_year(prefix_year, st):
    """One CDX listing per calendar year of box-score ids -> newest-first snapshot timestamps.
    (The availability API 429s after a few dozen calls; this is 30 calls for the whole job.)"""
    key = str(prefix_year)
    snaps = st.setdefault('snapshots', {})
    if key in snaps:
        return snaps[key]
    out = {}
    r = _get('https://web.archive.org/cdx/search/cdx',
             params={'url': f'pro-football-reference.com/boxscores/{prefix_year}*', 'output': 'json',
                     'fl': 'original,timestamp', 'filter': 'statuscode:200'}, timeout=180)
    rows = r.json()[1:] if r is not None and r.status_code == 200 and r.text.strip() else []
    for orig, ts in rows:
        m = re.search(r'/boxscores/(\d{9}[a-z]{3})\.htm$', orig.split('?')[0])
        if m:
            out.setdefault(m.group(1), []).append(ts)
    for gid in out:
        out[gid] = sorted(set(out[gid]), reverse=True)[:3]
    log(f'  CDX {prefix_year}: {len(out)} archived box-score ids')
    snaps[key] = out
    save_state(st)
    time.sleep(2)
    return out


def fetch_wayback(path, validator, stamps=None):
    url = PFR + path
    tried = set()
    for stage in ('listed', 'avail', 'cdx'):
        if stage == 'listed':
            stamps_now = list(stamps or [])
        else:
            stamps_now = wayback_timestamps(url) if stage == 'avail' else wayback_timestamps_cdx(url)
        stamps = stamps_now
        for ts in stamps:
            if ts in tried:
                continue
            tried.add(ts)
            _pace()
            r = _get(f'https://web.archive.org/web/{ts}id_/{url}', timeout=120)
            if r is not None and r.status_code == 200 and validator(r.text):
                return r.text, ts
        if stage == 'avail' and not stamps:
            continue
    return None, None


def cached_path(kind, season, gid=None):
    if kind == 'sched':
        return os.path.join(SCHED_DIR, f'{season}.htm.gz')
    return os.path.join(BOX_DIR, str(season), f'{gid}.htm.gz')


def read_cached(p):
    if os.path.exists(p):
        with gzip.open(p, 'rt', encoding='utf-8') as f:
            return f.read()
    return None


def write_cached(p, html):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with gzip.open(p, 'wt', encoding='utf-8') as f:
        f.write(html)


def get_page(path, cache_p, validator, allow_fetch=True, stamps=None):
    """Returns (html, source) where source is 'cache' | 'pfr' | 'wayback:<ts>' | None."""
    html = read_cached(cache_p)
    if html is not None:
        return html, 'cache'
    if not allow_fetch:
        return None, None
    html = fetch_direct(path, validator)
    src = 'pfr'
    if html is None:
        html, ts = fetch_wayback(path, validator, stamps)
        src = f'wayback:{ts}' if html else None
    if html:
        write_cached(cache_p, html)
    return html, src


# ---------------------------------------------------------------- parsing
class TableRows(HTMLParser):
    """Collect rows of <table id=TABLE_ID> as {data-stat: {text, href, cls}} (comment-safe)."""

    def __init__(self, table_id):
        super().__init__()
        self.table_id = table_id
        self.in_table = False
        self.depth = 0
        self.rows = []
        self.row = None
        self.cell = None
        self.header_stats = []
        self.in_thead = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'table' and a.get('id') == self.table_id:
            self.in_table = True
            self.depth = 0
            return
        if not self.in_table:
            return
        if tag == 'table':
            self.depth += 1
        elif tag == 'thead':
            self.in_thead = True
        elif tag == 'tr':
            self.row = {'_cls': a.get('class', '') or ''}
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = {'stat': a.get('data-stat', ''), 'text': '', 'href': None, 'csk': a.get('csk')}
            if self.in_thead and self.cell['stat']:
                self.header_stats.append(self.cell['stat'])
        elif tag == 'a' and self.cell is not None and self.cell['href'] is None:
            self.cell['href'] = a.get('href')

    def handle_endtag(self, tag):
        if not self.in_table:
            return
        if tag == 'table':
            if self.depth == 0:
                self.in_table = False
            else:
                self.depth -= 1
        elif tag == 'thead':
            self.in_thead = False
        elif tag in ('td', 'th') and self.cell is not None and self.row is not None:
            self.row[self.cell['stat']] = self.cell
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            if not self.in_thead:
                self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell['text'] += data


def table_rows(html, table_id):
    if f'id="{table_id}"' not in html:
        return None
    # PFR wraps some tables in HTML comments; strip the markers so the parser sees them.
    html = html.replace('<!--', '').replace('-->', '')
    p = TableRows(table_id)
    p.feed(html)
    return p


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
            return int(float(t))
        except ValueError:
            return 0


def txt(cell):
    return cell['text'].strip() if cell else ''


def sched_valid(html):
    return 'id="games"' in html and 'boxscore' in html


def box_valid(html):
    return 'id="player_offense"' in html


def parse_schedule(season, html):
    p = table_rows(html, 'games')
    games = []
    if not p:
        return games
    for row in p.rows:
        if 'thead' in row['_cls']:
            continue
        wk = txt(row.get('week_num'))
        box = row.get('boxscore_word')
        if not wk or not box or not box.get('href'):
            continue
        m = re.search(r'/boxscores/(\d{9}[a-z]{3})\.htm', box['href'])
        if not m:
            continue
        gid = m.group(1)
        # csk is a sort key (playoff rows carry "zz8"-style keys); trust it only when it is a date
        csk = (row.get('game_date') or {}).get('csk') or ''
        date = csk if re.match(r'\d{4}-\d{2}-\d{2}$', csk) else txt(row.get('game_date'))
        if wk.isdigit():
            week, po = int(wk), 0
        else:
            week, po = PLAYOFF_WK.get(wk, 0), 1
            if not week:
                continue
        loc = txt(row.get('game_location'))
        winner, loser = txt(row.get('winner')), txt(row.get('loser'))
        games.append({'gid': gid, 'wk': week, 'po': po, 'date': date,
                      'home': loser if loc == '@' else winner, 'away': winner if loc == '@' else loser,
                      'neutral': 1 if loc == 'N' else 0})
    return games


STAT_COLS = [('pc', 'pass_cmp'), ('pa', 'pass_att'), ('py', 'pass_yds'), ('ptd', 'pass_td'), ('int', 'pass_int'),
             ('ra', 'rush_att'), ('ry', 'rush_yds'), ('rtd', 'rush_td'),
             ('tgt', 'targets'), ('rec', 'rec'), ('rcy', 'rec_yds'), ('rctd', 'rec_td'),
             ('fmb', 'fumbles'), ('fl', 'fumbles_lost')]


def parse_box(gid, html):
    p = table_rows(html, 'player_offense')
    if not p:
        return None
    cols = set(p.header_stats)
    rows = []
    teams = []
    for row in p.rows:
        if 'thead' in row['_cls'] or 'over_header' in row['_cls']:
            continue
        pl = row.get('player')
        if not pl or not pl.get('href'):
            continue
        m = re.search(r'/players/[A-Za-z]/([A-Za-z0-9.\'-]+)\.htm', pl['href'])
        if not m:
            continue
        tm = txt(row.get('team'))
        if tm and tm not in teams:
            teams.append(tm)
        r = {'id': m.group(1), 'n': txt(pl), 'tm': tm}
        for k, stat in STAT_COLS:
            v = num(row.get(stat))
            if v:
                r[k] = v
        rows.append(r)
    return {'gid': gid, 'teams': teams, 'has_tgt': 'targets' in cols, 'has_fl': 'fumbles_lost' in cols, 'rows': rows}


# ---------------------------------------------------------------- team codes
# PFR box-score tables use its franchise codes (KAN, GNB, RAI, CLT, OTI, CRD, ...), some
# archived pages the era abbreviation (BAL, HOU, STL, OAK, ...). Map both to the site's
# modern franchise abbreviations, the convention the other weekly files use.
FIXED = {'ARI': 'ARI', 'CRD': 'ARI', 'PHO': 'ARI', 'ATL': 'ATL', 'RAV': 'BAL', 'BUF': 'BUF', 'CAR': 'CAR',
         'CHI': 'CHI', 'CIN': 'CIN', 'CLE': 'CLE', 'DAL': 'DAL', 'DEN': 'DEN', 'DET': 'DET', 'GNB': 'GB', 'GB': 'GB',
         'HTX': 'HOU', 'CLT': 'IND', 'IND': 'IND', 'JAX': 'JAX', 'KAN': 'KC', 'KC': 'KC', 'RAI': 'LV', 'OAK': 'LV',
         'LAI': 'LV', 'LVR': 'LV', 'LV': 'LV', 'RAM': 'LAR', 'LAR': 'LAR', 'LA': 'LAR', 'SDG': 'LAC', 'SD': 'LAC',
         'LAC': 'LAC', 'MIA': 'MIA', 'MIN': 'MIN', 'NWE': 'NE', 'NE': 'NE', 'BOS': 'NE', 'NOR': 'NO', 'NO': 'NO',
         'NYG': 'NYG', 'NYJ': 'NYJ', 'OTI': 'TEN', 'TEN': 'TEN', 'PHI': 'PHI', 'PIT': 'PIT', 'SEA': 'SEA',
         'SFO': 'SF', 'SF': 'SF', 'TAM': 'TB', 'TB': 'TB', 'WAS': 'WAS', 'WSH': 'WAS'}


def site_abbr(code, season):
    c = (code or '').upper()
    if c == 'BAL':
        return 'IND' if season <= 1983 else 'BAL'
    if c == 'HOU':
        return 'TEN' if season <= 1996 else 'HOU'
    if c == 'STL':
        return 'ARI' if season <= 1987 else 'LAR'
    return FIXED.get(c, c)


# ---------------------------------------------------------------- fetch driver
def parsed_path(season):
    return os.path.join(PARSED_DIR, f'{season}.json')


def load_parsed(season):
    p = parsed_path(season)
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_parsed(season, games):
    os.makedirs(PARSED_DIR, exist_ok=True)
    tmp = parsed_path(season) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(games, f, separators=(',', ':'))
    os.replace(tmp, parsed_path(season))


def ensure_schedule(season, st, allow_fetch=True):
    if str(season) in st['schedules'] and os.path.exists(cached_path('sched', season)):
        return st['schedules'][str(season)]
    html, src = get_page(f'/years/{season}/games.htm', cached_path('sched', season), sched_valid, allow_fetch)
    if not html:
        log(f'  schedule {season}: NOT FOUND')
        return None
    games = parse_schedule(season, html)
    nreg = sum(1 for g in games if not g['po'])
    log(f'  schedule {season}: {len(games)} games ({nreg} regular, {len(games) - nreg} playoff) via {src}')
    st['schedules'][str(season)] = games
    save_state(st)
    return games


def fetch_boxes(years, st, limit=None, deadline=None):
    """Fetch + parse every missing box score. Returns number of pages newly fetched."""
    fetched = 0
    for season in years:
        games = ensure_schedule(season, st)
        if not games:
            continue
        parsed = load_parsed(season)
        todo = [g for g in games if g['gid'] not in parsed]
        if not todo:
            continue
        log(f'{season}: {len(parsed)}/{len(games)} parsed, {len(todo)} to fetch')
        codes = st['codes'].setdefault(str(season), {})
        # box ids are calendar-dated: January playoff games sit under the next year's prefix
        listed = dict(cdx_year(season, st))
        listed.update(cdx_year(season + 1, st))
        dirty = 0
        for g in todo:
            if deadline and time.time() > deadline:
                log('  deadline reached')
                save_parsed(season, parsed)
                return fetched
            if limit is not None and fetched >= limit:
                save_parsed(season, parsed)
                return fetched
            html, src = get_page(f'/boxscores/{g["gid"]}.htm', cached_path('box', season, g['gid']), box_valid,
                                 stamps=listed.get(g['gid']))
            if src != 'cache':
                fetched += 1
            if not html:
                st['missing'][g['gid']] = {'season': season, 'wk': g['wk'], 'reason': 'no snapshot with #player_offense'}
                log(f'  {g["gid"]} wk{g["wk"]}: MISSING')
                continue
            st['missing'].pop(g['gid'], None)
            box = parse_box(g['gid'], html)
            if not box or not box['rows']:
                st['missing'][g['gid']] = {'season': season, 'wk': g['wk'], 'reason': 'parse: no rows'}
                log(f'  {g["gid"]} wk{g["wk"]}: parse failed ({src})')
                continue
            box.update({'wk': g['wk'], 'po': g['po'], 'date': g['date']})
            for t in box['teams']:
                codes[t] = codes.get(t, 0) + 1
            parsed[g['gid']] = box
            dirty += 1
            if src != 'cache':
                log(f'  {g["gid"]} wk{g["wk"]}{" PO" if g["po"] else ""}: {len(box["rows"])} rows via {src}'
                    f'{" +tgt" if box["has_tgt"] else ""}{" +fl" if box["has_fl"] else ""}')
            if dirty % 10 == 0:
                save_parsed(season, parsed)
                save_state(st)
        save_parsed(season, parsed)
        save_state(st)
    return fetched


def status(st, years=YEARS):
    tot_games = tot_parsed = 0
    lines = []
    for season in years:
        games = st['schedules'].get(str(season))
        parsed = load_parsed(season)
        n = len(games) if games else 0
        tot_games += n
        tot_parsed += len(parsed)
        miss = sum(1 for k, v in st['missing'].items() if v['season'] == season)
        lines.append(f'{season}: {len(parsed)}/{n or "?"}' + (f' ({miss} missing)' if miss else ''))
    log('  '.join(lines))
    left = tot_games - tot_parsed - sum(1 for v in st['missing'].values() if v['season'] in years)
    log(f'TOTAL parsed {tot_parsed}/{tot_games or "?"}; {len(st["missing"])} missing; '
        f'{left} left ~ {left * (DELAY + 2.5) / 3600:.1f} h at {DELAY}s spacing')
    return tot_parsed, tot_games, left


# ---------------------------------------------------------------- build
def fpts_weekly(r):
    v = (r.get('py', 0) * 0.04 + r.get('ptd', 0) * 4 - r.get('int', 0) * 2 + r.get('ry', 0) * 0.1
         + r.get('rtd', 0) * 6 + r.get('rec', 0) * 0.5 + r.get('rcy', 0) * 0.1 + r.get('rctd', 0) * 6
         - r.get('fl', 0) * 2)
    return round(v + 1e-9, 1)


def load_js_json(path, const_name):
    """Read `const NAME=<json>;` from a data file (season totals / legend careers)."""
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        s = f.read()
    m = re.search(r'(?:const|var|let)\s+' + re.escape(const_name) + r'\s*=\s*', s)
    if not m:
        return None
    dec = json.JSONDecoder()
    obj, _ = dec.raw_decode(s, m.end())
    return obj


def season_totals():
    for p in (os.path.join(DATA_DIR, 'season_totals_1970_1998.js'),
              os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(ROOT))), 'data', 'season_totals_1970_1998.js')):
        obj = load_js_json(p, 'SEASON_TOTALS_7098')
        if obj:
            return obj
    return None


def infer_pos(tot):
    if tot['pa'] >= 20 and tot['pa'] > 2 * tot['ra']:
        return 'QB'
    if tot['rec'] > tot['ra']:
        return 'WR'
    return 'RB'


def complete_seasons(years, st=None):
    """Seasons whose every scheduled game is parsed (a partial season would give wrong best weeks)."""
    st = st or load_state()
    out = []
    for season in years:
        games = st['schedules'].get(str(season))
        if not games:
            continue
        parsed = load_parsed(season)
        if all(g['gid'] in parsed for g in games):
            out.append(season)
    return out


def collect(years, complete_only=False):
    """players[id] = {n, seasons:{yr:[rows]}, tot:{...}} from the parsed games."""
    players = {}
    missing_years = []
    if complete_only:
        done = set(complete_seasons(years))
        missing_years = [y for y in years if y not in done]
        years = [y for y in years if y in done]
    for season in years:
        parsed = load_parsed(season)
        if not parsed:
            missing_years.append(season)
            continue
        for gid, box in parsed.items():
            if len(box['teams']) < 2:
                opp_of = {}
            else:
                opp_of = {box['teams'][0]: box['teams'][1], box['teams'][1]: box['teams'][0]}
            for r in box['rows']:
                if not (r.get('pa') or r.get('ra') or r.get('rec') or r.get('tgt')):
                    continue
                pl = players.setdefault(r['id'], {'n': r['n'], 'seasons': {}, 'tot': {'pa': 0, 'ra': 0, 'rec': 0}})
                pl['tot']['pa'] += r.get('pa', 0)
                pl['tot']['ra'] += r.get('ra', 0)
                pl['tot']['rec'] += r.get('rec', 0)
                row = {'wk': box['wk'], 'tm': site_abbr(r['tm'], season), 'opp': site_abbr(opp_of.get(r['tm'], ''), season),
                       'fpts': fpts_weekly(r)}
                if box.get('po'):
                    row['po'] = 1
                for k in ('pc', 'pa', 'py', 'ptd', 'int', 'ra', 'ry', 'rtd', 'tgt', 'rec', 'rcy', 'rctd', 'fl'):
                    if r.get(k):
                        row[k] = r[k]
                row['_d'] = box.get('date', '')
                pl['seasons'].setdefault(str(season), []).append(row)
    for pl in players.values():
        for rows in pl['seasons'].values():
            rows.sort(key=lambda x: (x['wk'], x['_d']))
            for x in rows:
                x.pop('_d', None)
    return players, missing_years


def build(years=YEARS, write=True, complete_only=False):
    players, missing_years = collect(years, complete_only)
    totals = season_totals()
    pos_of = {}
    for pid, pl in players.items():
        pos = (totals or {}).get(pid, {}).get('pos')
        pos_of[pid] = pos or infer_pos(pl['tot'])
    out = []
    for label, y1, y2 in ERAS:
        db = {}
        for pid, pl in players.items():
            seasons = {y: rows for y, rows in pl['seasons'].items() if y1 <= int(y) <= y2}
            if seasons:
                db[pid] = {'n': pl['n'], 'pos': pos_of[pid], 'seasons': seasons}
        # an era with nothing complete yet still gets its (empty) file so the loader never 404s
        js = ('// Per-game stat lines ' + f'{y1}-{y2}' + ' for every NFL skill player (Pro-Football-Reference box\n'
              '// scores; built by scripts/pull_pfr_boxscores.py). Keyed by PFR player id; the merge into\n'
              '// WEEKLY_STATS (index.html _mergeWeeklyStatsLegacy) resolves display names. fpts = half-PPR,\n'
              '// INT -2, FL -2 (the weekly basis); zero stats omitted; po:1 = playoff game (wk 19-22).\n'
              '(function(d){var L=window.WEEKLY_STATS_LEGACY=window.WEEKLY_STATS_LEGACY||{};'
              'for(var k in d){var r=L[k];if(!r){L[k]=d[k];continue;}for(var y in d[k].seasons)r.seasons[y]=d[k].seasons[y];}})('
              + json.dumps(db, separators=(',', ':'), ensure_ascii=False) + ');\n')
        path = os.path.join(DATA_DIR, f'weekly_stats_{label}.js')
        if write:
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(js)
        nrows = sum(len(r) for p in db.values() for r in p['seasons'].values())
        out.append((label, path, len(db), nrows, len(js.encode('utf-8'))))
        log(f'{"wrote" if write else "would write"} {os.path.relpath(path, ROOT)}: {len(db)} players, {nrows} rows, {len(js.encode("utf-8")) / 1024 / 1024:.2f} MB')
    if missing_years:
        log(('seasons left out (incomplete):' if complete_only else 'seasons with no parsed games yet:'), missing_years)
    return out


# ---------------------------------------------------------------- cross-check
def fpts_totals_basis(s):
    """LEGEND_CAREERS / season-totals basis: half-PPR, INT -1, FL -2."""
    v = (s['py'] / 25 + s['ptd'] * 4 - s['int'] + s['ry'] / 10 + s['rtd'] * 6
         + s['rc'] * 0.5 + s['rcy'] / 10 + s['rctd'] * 6 - s['fl'] * 2)
    return round(v + 1e-9, 1)


def xcheck(n=50, seed=7, years=YEARS, min_fpts=40.0, complete_only=False):
    players, _ = collect(years, complete_only)
    totals = season_totals()
    legends = load_js_json(os.path.join(DATA_DIR, 'legend_careers.js'), 'LEGEND_CAREERS') or {}
    src = 'season_totals_1970_1998.js' if totals else 'legend_careers.js'
    # candidate (pid, year, totals row)
    cands = []
    for pid, pl in players.items():
        if totals:
            trow = {s['yr']: s for s in totals.get(pid, {}).get('seasons', [])}
        else:
            trow = {s['yr']: s for s in legends.get(pl['n'], []) if s.get('yr') in years}
        for y, rows in pl['seasons'].items():
            t = trow.get(int(y))
            if t and t.get('fpts', 0) >= min_fpts and not t.get('tm', '').endswith('TM'):
                cands.append((pid, int(y), t))
    if not cands:
        log('xcheck: no overlapping player-seasons (no season totals / legend careers found)')
        return []
    random.seed(seed)
    sample = random.sample(cands, min(n, len(cands)))
    bad = []
    log(f'xcheck: {len(sample)} random player-seasons vs {src} (fpts recomputed on the totals basis, INT -1)')
    for pid, y, t in sample:
        reg = [r for r in players[pid]['seasons'][str(y)] if not r.get('po')]
        s = {k: sum(r.get(k2, 0) for r in reg) for k, k2 in
             (('py', 'py'), ('ptd', 'ptd'), ('int', 'int'), ('ry', 'ry'), ('rtd', 'rtd'), ('rc', 'rec'), ('rcy', 'rcy'), ('rctd', 'rctd'), ('fl', 'fl'))}
        mine = fpts_totals_basis(s)
        diff = round(mine - t['fpts'], 1)
        # Known, explainable gaps: box scores of the era carry no fumbles-lost column (season
        # totals do), and the LEGEND_CAREERS QB rows carry no rushing line. Everything else is real.
        explained = round((t.get('fl', 0) - s['fl']) * 2.0
                          + (s['ry'] - t.get('ry', 0)) * 0.1 + (s['rtd'] - t.get('rtd', 0)) * 6, 1)
        resid = round(diff - explained, 1)
        flag = 'MISMATCH' if abs(resid) > 2.0 else ('ok*' if abs(diff) > 2.0 else 'ok')
        if flag == 'MISMATCH':
            bad.append((pid, y, diff))
        log(f'  {flag:8} {players[pid]["n"]:24} {y} games {len(reg):2} (totals gp {t.get("gp", "?")}): weekly-sum {mine:6.1f} vs totals {t["fpts"]:6.1f} diff {diff:+.1f}'
            f'  [py {s["py"]}/{t.get("py", 0)} ry {s["ry"]}/{t.get("ry", 0)} rcy {s["rcy"]}/{t.get("rcy", 0)} fl {s["fl"]}/{t.get("fl", 0)}]')
    log(f'xcheck: {len(bad)} of {len(sample)} differ by more than 2 fpts after the known gaps '
        f'(fumbles-lost column absent in the box scores, QB rushing absent in legend_careers); '
        f'"ok*" = differs only by those gaps')
    return bad


# ---------------------------------------------------------------- main
LOCK_PATH = os.path.join(CACHE, 'boxscores.lock')


def acquire_lock():
    """One fetcher at a time (nightly task vs. a session run): the lock holds a heartbeat
    timestamp refreshed by _pace(); a lock older than 10 minutes is treated as stale."""
    os.makedirs(CACHE, exist_ok=True)
    if os.path.exists(LOCK_PATH):
        age = time.time() - os.path.getmtime(LOCK_PATH)
        if age < 600:
            log(f'another run holds {LOCK_PATH} (heartbeat {age:.0f}s ago); exiting')
            sys.exit(0)
        log('stale lock; taking over')
    with open(LOCK_PATH, 'w') as f:
        f.write(str(os.getpid()))


def release_lock():
    try:
        os.remove(LOCK_PATH)
    except OSError:
        pass


def _heartbeat():
    try:
        os.utime(LOCK_PATH, None)
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--schedules', action='store_true')
    ap.add_argument('--fetch', action='store_true')
    ap.add_argument('--build', action='store_true')
    ap.add_argument('--xcheck', action='store_true')
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--nightly', action='store_true')
    ap.add_argument('--years', nargs='*', type=int, default=YEARS)
    ap.add_argument('--limit', type=int, default=None, help='max pages to fetch this run')
    ap.add_argument('--n', type=int, default=50)
    ap.add_argument('--until', default='06:30', help='nightly: stop fetching at this local time')
    ap.add_argument('--max-minutes', type=float, default=None)
    ap.add_argument('--no-write', action='store_true')
    ap.add_argument('--complete-only', action='store_true',
                    help='build/xcheck only seasons whose every scheduled game is parsed (default for --nightly)')
    args = ap.parse_args()
    st = load_state()
    os.makedirs(CACHE, exist_ok=True)

    if args.status:
        status(st, args.years)
    if args.schedules or args.fetch or args.nightly:
        acquire_lock()
    try:
        _run(args, st)
    finally:
        if args.schedules or args.fetch or args.nightly:
            release_lock()


def _run(args, st):
    if args.schedules:
        for y in args.years:
            ensure_schedule(y, st)
    if args.fetch:
        n = fetch_boxes(args.years, st, limit=args.limit)
        log(f'fetched {n} pages')
        status(st, args.years)
    if args.nightly:
        start = time.time()
        deadline = None
        if args.max_minutes:
            deadline = start + args.max_minutes * 60
        else:
            hh, mm = (int(x) for x in args.until.split(':'))
            now = dt.datetime.now()
            until = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if until <= now:
                until += dt.timedelta(days=1)
            deadline = until.timestamp()
        log(f'nightly run start; fetching until {dt.datetime.fromtimestamp(deadline):%Y-%m-%d %H:%M}')
        n = fetch_boxes(args.years, st, deadline=deadline)
        parsed, total, left = status(st, args.years)
        st['runs'].append({'at': dt.datetime.now().isoformat(timespec='minutes'), 'fetched': n, 'parsed': parsed, 'left': left})
        save_state(st)
        if n:
            build(args.years, write=not args.no_write, complete_only=True)
        log(f'nightly run end: fetched {n}, {left} left' + ('; ALL DONE' if left <= 0 else ''))
    if args.build:
        build(args.years, write=not args.no_write, complete_only=args.complete_only)
    if args.xcheck:
        xcheck(args.n, years=args.years, complete_only=args.complete_only)
    if not any((args.status, args.schedules, args.fetch, args.build, args.xcheck, args.nightly)):
        ap.print_help()


if __name__ == '__main__':
    main()
