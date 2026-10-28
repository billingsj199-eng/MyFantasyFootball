#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_legend_headshots.py — Wikipedia/Wikimedia headshots for retired legends.

ESPN has no headshots for most pre-2000 players, so trivia reveals for names
like Emmitt Smith or Thurman Thomas fell back to initials. This script takes
every name in data/legend_careers.js that has NO ESPN id in any of the four id
files (retired_espn_ids / daily_retired_pool / headshot_espn_ids /
fallback_espn_ids), asks the Wikipedia API for the page's lead image
(prop=pageimages, free-licensed images only — the API default) and writes

    data/legend_headshots.js
    window.LEGEND_HEADSHOTS = {
      "Name": {"url": "...400px thumb...", "credit": "Artist · CC BY-SA 4.0",
               "page": "https://en.wikipedia.org/wiki/...",
               "byTeam": {"LV": {"url": "...", "credit": "..."}, "KC": {...}}}}

Stage A — find the page. Namesake guard: a page is accepted only when its
short description or categories mention American/gridiron football (NFL, AFL,
CFL). Disambiguation pages are skipped. Title variants, in order:
    "<Name> (American football)"  ->  "<Name>"  ->  positional
    "(quarterback)", "(running back)", … (only for names whose plain title
    turned out to be a namesake / disambiguation page).

Stage B — jersey match (Jack, 2026-10-28: show Marcus Allen as a Raider on a
Raiders cell). Every image in the article (prop=images) plus the lead image is
a candidate when its filename / Commons description names the player; each is
tagged with a team when the description or filename names one of the player's
teams, or when its DateTimeOriginal year falls in a season with that team (per
season `tm` in legend_careers.js, gaps filled from the nearest known season;
STL/HOU/BAL resolved by year). The best candidate per team lands in `byTeam`
(team = site abbreviation: LV, LAR, LAC, TEN, ARI, IND … like TEAM_ABBR_MAP).
Teams with no tagged photo are left out — the reveal falls back to `url`.

Stage C — Commons file search for names stage A could not place (article has no
free lead image): list=search in the File namespace for "<Name>"; a hit counts
only when the full name appears in the filename/description AND the file is
dated inside the career, names one of the player's teams, or says football/NFL/
Topps. Best hit becomes the default (`page` = the Commons file page), team-tagged
hits fill byTeam. --skip-file-search turns it off.

Credits (Artist + LicenseShortName) come from prop=imageinfo extmetadata.

Usage (stdlib + `requests` if installed, else curl):
    python -I scripts/build_legend_headshots.py               # resume (default)
    python -I scripts/build_legend_headshots.py --refresh     # re-query everything
    python -I scripts/build_legend_headshots.py --names "Emmitt Smith" "Bart Starr"
    python -I scripts/build_legend_headshots.py --limit 100   # first N candidates (testing)
    python -I scripts/build_legend_headshots.py --skip-teams  # stage A only

Resumable: the output is rewritten after every batch; names already in it are
skipped and names already searched (hit or miss) are remembered in
data/legend_headshots_state.json (git-ignored by the data/*.json rule) so a
re-run only touches new names (--refresh clears both). ~1 request/second.
The ESPN path in app.js is untouched; LEGEND_HEADSHOTS is only consulted after
FALLBACK_IDS / RETIRED_ESPN_IDS miss. NOT used by the Guess Who daily photo
game (modern photos of retired players would give the answer away).
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(DATA, 'legend_headshots.js')
STATE = os.path.join(DATA, 'legend_headshots_state.json')
SUSPECTS = os.path.join(ROOT, 'scripts', '_suspect_espn_ids.json')
ESPN_ATHLETE = 'https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/%s'
CAREERS = os.path.join(DATA, 'legend_careers.js')
ID_FILES = ['retired_espn_ids.js', 'daily_retired_pool.js',
            'headshot_espn_ids.js', 'fallback_espn_ids.js']

API = 'https://en.wikipedia.org/w/api.php'
COMMONS = 'https://commons.wikimedia.org/w/api.php'
UA = 'MyFantasyFootballLegendHeadshots/1.1 (https://myfantasyfootball.co; billingsj199@gmail.com)'
BATCH = 50
IMG_BATCH = 20        # prop=images lists up to 500 files per request; 20 articles keeps it under
SLEEP = 1.0           # seconds between requests
THUMB = 400

VARIANTS = ['{n} (American football)', '{n}', '{n} (quarterback)', '{n} (running back)',
            '{n} (wide receiver)', '{n} (tight end)', '{n} (placekicker)', '{n} (punter)',
            '{n} (fullback)', '{n} (halfback)', '{n} (end)']

FOOTBALL_RE = re.compile(
    r'american football|gridiron|national football league|\bnfl\b|american football league'
    r'|canadian football league|all-america football conference|\bafl\b', re.I)
DISAMBIG_RE = re.compile(r'disambiguation|topics referred to by the same term', re.I)

# ---- teams -----------------------------------------------------------------
CANON = {'ARI', 'ATL', 'BAL', 'BUF', 'CAR', 'CHI', 'CIN', 'CLE', 'DAL', 'DEN', 'DET', 'GB',
         'HOU', 'IND', 'JAX', 'KC', 'LAC', 'LAR', 'LV', 'MIA', 'MIN', 'NE', 'NO', 'NYG', 'NYJ',
         'PHI', 'PIT', 'SF', 'SEA', 'TB', 'TEN', 'WAS'}
TM_FIX = {'RAI': 'LV', 'OAK': 'LV', 'LVR': 'LV', 'SFO': 'SF', 'GNB': 'GB', 'KAN': 'KC',
          'NOR': 'NO', 'NWE': 'NE', 'TAM': 'TB', 'SDG': 'LAC', 'SD': 'LAC', 'LA': 'LAR',
          'RAM': 'LAR', 'LARams': 'LAR', 'PHO': 'ARI', 'PHX': 'ARI', 'CRD': 'ARI', 'BOS': 'NE',
          'NYT': 'NYJ', 'WSH': 'WAS', 'JAC': 'JAX'}
# nickname / historic name -> canonical team (lower-case, matched on word boundaries)
TEAM_WORDS = {
    'cardinals': 'ARI', 'falcons': 'ATL', 'ravens': 'BAL', 'bills': 'BUF', 'panthers': 'CAR',
    'bears': 'CHI', 'bengals': 'CIN', 'browns': 'CLE', 'cowboys': 'DAL', 'broncos': 'DEN',
    'lions': 'DET', 'packers': 'GB', 'green bay': 'GB', 'texans': 'HOU', 'colts': 'IND',
    'jaguars': 'JAX', 'chiefs': 'KC', 'kansas city': 'KC', 'chargers': 'LAC', 'rams': 'LAR',
    'raiders': 'LV', 'dolphins': 'MIA', 'vikings': 'MIN', 'patriots': 'NE', 'saints': 'NO',
    'giants': 'NYG', 'jets': 'NYJ', 'eagles': 'PHI', 'steelers': 'PIT', '49ers': 'SF',
    'niners': 'SF', 'seahawks': 'SEA', 'buccaneers': 'TB', 'bucs': 'TB', 'titans': 'TEN',
    'oilers': 'TEN', 'redskins': 'WAS', 'commanders': 'WAS', 'washington football team': 'WAS',
}
TEAM_WORD_RE = re.compile(r'\b(' + '|'.join(sorted(map(re.escape, TEAM_WORDS), key=len, reverse=True)) + r')\b', re.I)

JUNK_FILE_RE = re.compile(
    r'\b(logo|flag|icon|symbol|map|wordmark|seal|badge|crest|commons|wiki\w*|ambox|nuvola|crystal'
    r'|question|edit|star|check|signature|autograph|stadium|arena|trophy|ring|helmet|jersey'
    r'|stamp|cover|poster|ticket|plaque|statue|bust|grave|house|school|chart|graph|diagram'
    r'|pictogram|disambig|padlock|speaker|sound|audio)\b', re.I)


def canon_tm(tm, yr):
    if not tm:
        return None
    yr = yr or 0
    if tm == 'STL':
        return 'LAR' if yr >= 1995 else 'ARI'
    if tm == 'HOU':
        return 'TEN' if yr <= 1996 else 'HOU'
    if tm == 'BAL':
        return 'IND' if yr <= 1983 else 'BAL'
    t = TM_FIX.get(tm, tm)
    return t if t in CANON else None


def team_by_year(seasons):
    """{year: canonical team}; seasons missing `tm` inherit the nearest known
    (previous first, then next)."""
    rows = sorted(((s.get('yr') or 0, canon_tm(s.get('tm'), s.get('yr'))) for s in seasons if s.get('yr')), key=lambda r: r[0])
    out = {}
    last = None
    for yr, t in rows:
        if t:
            last = t
        out[yr] = t or last
    nxt = None
    for yr, t in reversed(rows):
        if t:
            nxt = t
        if not out.get(yr):
            out[yr] = nxt
    return {y: t for y, t in out.items() if t}


# ---------------------------------------------------------------- HTTP ----
_session = None


def _http_get(url):
    """GET url -> text. requests (certifi CA bundle) when available, else curl.
    (urllib against wikipedia.org hit an expired-certificate error here.)"""
    global _session
    try:
        import requests  # noqa
        if _session is None:
            _session = requests.Session()
            _session.headers['User-Agent'] = UA
            try:
                import certifi
                _session.verify = certifi.where()
            except Exception:
                pass
        r = _session.get(url, timeout=60)
        r.raise_for_status()
        return r.text
    except ImportError:
        pass
    cp = subprocess.run(['curl', '-sS', '--fail', '-A', UA, '--max-time', '60', url],
                        capture_output=True, text=True, encoding='utf-8')
    if cp.returncode != 0:
        raise RuntimeError('curl failed (%s): %s' % (cp.returncode, cp.stderr.strip()[:200]))
    return cp.stdout


def api(params, host=API):
    params = dict(params, format='json', formatversion='2')
    url = host + '?' + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            txt = _http_get(url)
            data = json.loads(txt)
            if 'error' in data:
                raise RuntimeError(data['error'].get('info', 'api error'))
            time.sleep(SLEEP)
            return data
        except Exception as e:
            wait = 3 * (attempt + 1)
            print('  ! request failed (%s) — retry in %ss' % (str(e)[:120], wait), flush=True)
            time.sleep(wait)
    raise RuntimeError('giving up on ' + url[:160])


# ---------------------------------------------------------- data files ----
def load_careers():
    src = open(CAREERS, encoding='utf-8').read()
    m = re.search(r'LEGEND_CAREERS\s*=\s*(\{.*\})\s*;?\s*$', src, re.S)
    if not m:
        raise SystemExit('could not parse ' + CAREERS)
    return json.loads(m.group(1))


def load_espn_ids():
    """{name: (espn id, file)} for every name in the four id files (first file wins,
    in the order _triviaGetHeadshotInfo consults them: FALLBACK first, then RETIRED)."""
    ids = {}
    pat = re.compile(r'''['"]([^'"\n]{2,60})['"]\s*:\s*['"](\d{2,9})['"]''')
    for fn in ['fallback_espn_ids.js', 'daily_retired_pool.js', 'retired_espn_ids.js', 'headshot_espn_ids.js']:
        p = os.path.join(DATA, fn)
        if not os.path.exists(p):
            print('  (missing id file %s)' % fn)
            continue
        src = open(p, encoding='utf-8').read()
        for m in pat.finditer(src):
            ids.setdefault(m.group(1), (m.group(2), fn))
    return ids


def load_espn_names():
    """Every name with an ESPN id in the four id files."""
    return set(load_espn_ids())


# ------------------------------------------------------- ESPN id audit ----
def legend_group(seasons):
    """QB / RB / REC (WR+TE) from career stat shape."""
    py = sum(s.get('py') or 0 for s in seasons)
    ra = sum(s.get('ra') or 0 for s in seasons)
    rc = sum(s.get('rc') or 0 for s in seasons)
    ry = sum(s.get('ry') or 0 for s in seasons)
    rcy = sum(s.get('rcy') or 0 for s in seasons)
    if py > 500 and py >= 2 * max(ry, rcy):
        return 'QB'
    return 'RB' if ra >= rc else 'REC'


ESPN_GROUP = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'HB': 'RB', 'WR': 'REC', 'TE': 'REC'}


def _name_key(n):
    n = re.sub(r"[.'’\-]", '', n or '').lower()
    n = re.sub(r'\b(jr|sr|ii|iii|iv)\b', '', n)
    return re.sub(r'\s+', ' ', n).strip()


def audit_espn_ids(careers, ids, before=2005, min_age=45):
    """Legends whose last season is before `before` and who carry an ESPN id: ask
    ESPN who that id is. Suspect when the athlete is younger than `min_age`, the
    position group differs from the legend's stat shape, or the name differs
    (namesake collisions like the Marcus Allen LB, 2026-10-28). Writes SUSPECTS."""
    rows = []
    names = sorted(n for n, s in careers.items() if n in ids and s
                   and max((x.get('yr') or 0) for x in s) < before)
    print('ESPN id audit: %d legends (last season < %d) carry an ESPN id' % (len(names), before), flush=True)
    for n in names:
        eid, fn = ids[n]
        try:
            d = json.loads(_http_get(ESPN_ATHLETE % eid))
        except Exception as e:
            rows.append({'name': n, 'id': eid, 'file': fn, 'reasons': ['lookup failed: ' + str(e)[:80]]})
            continue
        a = d.get('athlete', d)
        disp = a.get('displayName') or a.get('fullName') or ''
        age = a.get('age')
        pos = (a.get('position') or {}).get('abbreviation') or ''
        grp = legend_group(careers[n])
        reasons = []
        if isinstance(age, (int, float)) and age < min_age:
            reasons.append('age %s < %d' % (age, min_age))
        if pos and ESPN_GROUP.get(pos, pos) != grp:
            reasons.append('position %s vs legend %s' % (pos, grp))
        if disp and _name_key(disp) != _name_key(n):
            reasons.append('name %r' % disp)
        if not disp and age is None and not pos:
            reasons.append('no athlete record')
        if reasons:
            rows.append({'name': n, 'id': eid, 'file': fn, 'displayName': disp, 'age': age,
                         'position': pos, 'legendGroup': grp, 'reasons': reasons})
        time.sleep(0.25)
    with open(SUSPECTS, 'w', encoding='utf-8') as f:
        json.dump({'generated': time.strftime('%Y-%m-%d'),
                   'rule': 'last season < %d; suspect if age < %d, position group mismatch, or name mismatch' % (before, min_age),
                   'checked': len(names), 'suspects': rows}, f, indent=1)
    print('ESPN id audit: %d suspect ids -> %s' % (len(rows), os.path.relpath(SUSPECTS, ROOT)), flush=True)
    for r in rows:
        print('   %-22s %-8s %s' % (r['name'], r['id'], '; '.join(r['reasons'])))
    return {r['name'] for r in rows}


def is_notable(seasons):
    return sum(1 for s in seasons if (s.get('fpts') or 0) >= 150) >= 3


def load_existing():
    if not os.path.exists(OUT):
        return {}
    src = open(OUT, encoding='utf-8').read()
    m = re.search(r'LEGEND_HEADSHOTS\s*=\s*(\{.*\})\s*;?\s*$', src, re.S)
    return json.loads(m.group(1)) if m else {}


def load_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE, encoding='utf-8'))
        except Exception:
            pass
    return {'searched': {}, 'teams_done': {}}


def save_state(state):
    tmp = STATE + '.tmp'
    json.dump(state, open(tmp, 'w', encoding='utf-8'), indent=0, sort_keys=True)
    os.replace(tmp, STATE)


def write_out(table, meta):
    keys = sorted(table)
    n_teams = sum(1 for k in keys if table[k].get('byTeam'))
    lines = []
    lines.append('/* LEGEND_HEADSHOTS — Wikipedia/Wikimedia Commons lead images for retired legends')
    lines.append('   with no ESPN headshot. Generated %s by scripts/build_legend_headshots.py' % meta['date'])
    lines.append('   (%d photos, %d with per-team jersey photos; %d/%d notable legends covered).' % (
        len(keys), n_teams, meta['notable_hit'], meta['notable_total']))
    lines.append('   Free-licensed images only; "credit" = Artist · License (shown as the image')
    lines.append('   tooltip on the Trivia page). byTeam[ABBR] = photo in that team\'s jersey (site')
    lines.append('   abbreviations: LV, LAR, LAC, TEN, ARI, IND …) — the reveal prefers the cell\'s team.')
    lines.append('   preferCommons:true = the name\'s ESPN id failed the audit (scripts/_suspect_espn_ids.json:')
    lines.append('   namesake / wrong position / too young) so the reveal takes this photo FIRST.')
    lines.append('   Otherwise consulted by _triviaGetHeadshotInfo AFTER FALLBACK_IDS / RETIRED_ESPN_IDS miss;')
    lines.append('   never used by the Guess Who daily photo pool (DAILY_RETIRED_POOL). */')
    lines.append('window.LEGEND_HEADSHOTS = {')
    for i, k in enumerate(keys):
        v = table[k]
        rec = {'url': v['url'], 'credit': v['credit'], 'page': v['page']}
        if v.get('preferCommons'):
            rec['preferCommons'] = True
        if v.get('byTeam'):
            rec['byTeam'] = {t: {'url': b['url'], 'credit': b['credit']} for t, b in sorted(v['byTeam'].items())}
        row = json.dumps(k, ensure_ascii=False) + ':' + json.dumps(rec, ensure_ascii=False, separators=(',', ':'))
        lines.append(row + (',' if i < len(keys) - 1 else ''))
    lines.append('};')
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    os.replace(tmp, OUT)


# ----------------------------------------------------------- wikipedia ----
def _strip_html(s):
    return html.unescape(re.sub(r'<[^>]+>', '', s or '')).strip()


def _follow(q):
    """normalized + redirects map (sent title -> final title)."""
    fwd = {}
    for n in q.get('normalized', []):
        fwd[n['from']] = n['to']
    for r in q.get('redirects', []):
        fwd[r['from']] = r['to']

    def f(t):
        seen = 0
        while t in fwd and seen < 5:
            t = fwd[t]
            seen += 1
        return t
    return f


def query_pages(titles):
    """titles -> {title_as_sent: page dict or None}."""
    data = api({'action': 'query', 'prop': 'pageimages|description|categories',
                'pithumbsize': THUMB, 'pilicense': 'free', 'clshow': '!hidden', 'cllimit': 'max',
                'redirects': 1, 'titles': '|'.join(titles)})
    q = data.get('query', {})
    follow = _follow(q)
    pages = {p['title']: p for p in q.get('pages', [])}
    out = {}
    for t in titles:
        p = pages.get(follow(t))
        out[t] = None if (p is None or p.get('missing') or p.get('invalid')) else p
    return out


def page_ok(p):
    desc = p.get('description') or ''
    cats = ' '.join(c.get('title', '') for c in p.get('categories', []))
    if DISAMBIG_RE.search(desc) or DISAMBIG_RE.search(cats):
        return False
    return bool(FOOTBALL_RE.search(desc + ' ' + cats))


def article_images(titles):
    """article titles -> {title: [File:... names]} (prop=images, all namespaces' files)."""
    out = {t: [] for t in titles}
    params = {'action': 'query', 'prop': 'images', 'imlimit': 'max', 'redirects': 1,
              'titles': '|'.join(titles)}
    back = {}
    while True:
        data = api(params)
        q = data.get('query', {})
        follow = _follow(q)
        for t in titles:
            back[follow(t)] = t
        for p in q.get('pages', []):
            sent = back.get(p['title'])
            if sent is None:
                continue
            for im in p.get('images', []) or []:
                out[sent].append(im['title'])
        cont = data.get('continue')
        if not cont:
            break
        params = dict(params, **cont)
    return out


def commons_categories(names):
    """names -> set of names whose 'Category:<name>' exists on Commons (batched)."""
    have = set()
    for i in range(0, len(names), BATCH):
        chunk = names[i:i + BATCH]
        data = api({'action': 'query', 'prop': 'info', 'titles': '|'.join('Category:' + n for n in chunk)}, COMMONS)
        q = data.get('query', {})
        back = {}
        for n in q.get('normalized', []):
            back[n['to']] = n['from']
        for p in q.get('pages', []):
            if p.get('missing'):
                continue
            t = back.get(p['title'], p['title'])
            have.add(t[len('Category:'):])
    return have


def commons_category_files(name, limit=60):
    """Files in Commons 'Category:<name>' (one request; no batching for categorymembers)."""
    data = api({'action': 'query', 'list': 'categorymembers', 'cmtitle': 'Category:' + name,
                'cmtype': 'file', 'cmlimit': limit}, COMMONS)
    return [m['title'] for m in data.get('query', {}).get('categorymembers', [])]


def image_info(file_titles):
    """['File:X.jpg', ...] -> {'File:X.jpg': {thumb, credit, desc, year, shared}}"""
    out = {}
    for i in range(0, len(file_titles), BATCH):
        chunk = file_titles[i:i + BATCH]
        data = api({'action': 'query', 'prop': 'imageinfo', 'iiprop': 'url|extmetadata|mime',
                    'iiurlwidth': THUMB,
                    'iiextmetadatafilter': 'Artist|LicenseShortName|Credit|ImageDescription|DateTimeOriginal|ObjectName',
                    'titles': '|'.join(chunk)}, COMMONS)
        q = data.get('query', {})
        back = {}
        for n in q.get('normalized', []):
            back[n['to']] = n['from']
        for p in q.get('pages', []):
            # Asked on Commons so only free files answer; a file that lives only on
            # enwiki (fair use) is "missing" here with no imageinfo → skipped.
            if not p.get('imageinfo'):
                continue
            ii = (p.get('imageinfo') or [{}])[0]
            md = ii.get('extmetadata') or {}
            artist = _strip_html(md.get('Artist', {}).get('value', ''))
            if not artist:
                artist = _strip_html(md.get('Credit', {}).get('value', ''))
            artist = re.sub(r'\s+', ' ', artist)
            # Commons wraps some authors in two <span lang> copies ("Unknown authorUnknown author").
            h = len(artist) // 2
            if h and artist[:h] == artist[h:]:
                artist = artist[:h]
            artist = artist[:80]
            lic = _strip_html(md.get('LicenseShortName', {}).get('value', ''))
            credit = ' · '.join(x for x in [artist, lic] if x) or 'Wikimedia Commons'
            desc = _strip_html(md.get('ImageDescription', {}).get('value', ''))
            obj = _strip_html(md.get('ObjectName', {}).get('value', ''))
            dt = md.get('DateTimeOriginal', {}).get('value', '') or ''
            ym = re.search(r'\b(19[2-9]\d|20[0-2]\d)\b', _strip_html(dt))
            thumb = (ii.get('thumburl') or ii.get('url') or '').split('?')[0]
            out[back.get(p['title'], p['title'])] = {
                'thumb': thumb, 'credit': credit, 'desc': (desc + ' ' + obj).strip(),
                'year': int(ym.group(1)) if ym else None, 'lic': lic,
                'shared': p.get('imagerepository') in ('shared', 'local'),
                'mime': ii.get('mime', ''),
            }
    return out


# Namesake / not-a-headshot guards for loose Commons files (stage C) and article images.
RELATIVE_RE = re.compile(r'(daughter|son|father|mother|wife|husband|brother|sister|nephew|niece|grandson|granddaughter|widow)\s+of', re.I)
MEMORIAL_RE = re.compile(r'(memorial|plaque|statue|bust|grave|headstone|ring of honor|ring of honour|tombstone)', re.I)
OTHER_SPORT_RE = re.compile(r'(rugby|soccer|baseball|basketball|cricket|hockey|outfielder|infielder|pitcher|shortstop|nrl|second rower|prop forward|australian rules|golfer|boxer|wrestler)', re.I)
FOOTBALL_WORD_RE = re.compile(r'\b(football|nfl|quarterback|running back|halfback|fullback|wide receiver|tight end|topps|fleer|bowman|philadelphia gum|trading card)\b', re.I)


def commons_file_search(name, limit=10):
    """Commons File: namespace search for an exact name phrase -> [File:... titles]."""
    data = api({'action': 'query', 'list': 'search', 'srnamespace': 6, 'srlimit': limit,
                'srsearch': '"%s"' % name}, COMMONS)
    return [h['title'] for h in data.get('query', {}).get('search', [])]


def pick_from_search(name, seasons, files, info):
    """Namesake-guarded pick from loose Commons files: (default {url, credit, file}, byTeam)."""
    by_year = team_by_year(seasons)
    my_teams = set(by_year.values())
    years = {s.get('yr') for s in seasons if s.get('yr')}
    full = name.lower()
    best = None
    by_team = {}
    for ft in files:
        fi = info.get(ft)
        if not fi or not fi['thumb'] or not fi['shared']:
            continue
        if not fi['mime'].startswith('image/') or 'svg' in fi['mime'] or 'gif' in fi['mime']:
            continue
        fname = ft[5:].replace('_', ' ')
        if JUNK_FILE_RE.search(fname):
            continue
        text = (fname + ' ' + fi['desc']).lower()
        if full not in text and _name_key(name) not in _name_key(text):
            continue
        if RELATIVE_RE.search(text) or MEMORIAL_RE.search(text):
            continue                       # "daughter of Brent Jones", Joe Delaney's memorial plaque
        if OTHER_SPORT_RE.search(text) and not FOOTBALL_WORD_RE.search(text):
            continue                       # rugby second-rower / baseball outfielder namesakes
        tags = {}
        for m in TEAM_WORD_RE.finditer(text):
            t = TEAM_WORDS[m.group(1).lower()]
            if t in my_teams:
                tags[t] = tags.get(t, 0) + 2
        in_career = bool(fi['year'] and fi['year'] in years)
        if fi['year'] and fi['year'] not in years and not tags:
            continue                       # dated outside the career and no team word
        if not tags and not FOOTBALL_WORD_RE.search(text):
            continue                       # same name, nothing football about it (a date inside
                                           # the career is not enough: drummers and actors share names)
        if in_career and by_year.get(fi['year']):
            t = by_year[fi['year']]
            tags[t] = tags.get(t, 0) + 1
        score = sum(tags.values()) + (1 if in_career else 0) + (1 if FOOTBALL_WORD_RE.search(text) else 0)
        if best is None or score > best['score']:
            best = {'url': fi['thumb'], 'credit': fi['credit'], 'file': ft, 'score': score}
        for t, sc in tags.items():
            cur = by_team.get(t)
            if cur is None or sc > cur['score']:
                by_team[t] = {'url': fi['thumb'], 'credit': fi['credit'], 'score': sc}
    return best, {t: {'url': b['url'], 'credit': b['credit']} for t, b in by_team.items()}


def file_from_thumb(url):
    m = re.search(r'/commons/thumb/[0-9a-f]/[0-9a-f]{2}/([^/]+)/', url or '')
    return 'File:' + urllib.parse.unquote(m.group(1)).replace('_', ' ') if m else None


def surname(name):
    toks = [t for t in re.split(r'\s+', name.strip()) if not re.match(r'^(jr\.?|sr\.?|ii|iii|iv)$', t, re.I)]
    return toks[-1].lower() if toks else name.lower()


def tag_candidates(name, seasons, files, info):
    """Pick the best photo per team. Returns ({team: {url, credit}}, reason counts)."""
    by_year = team_by_year(seasons)
    my_teams = set(by_year.values())
    sn = surname(name)
    full = name.lower()
    best = {}
    for ft in files:
        fi = info.get(ft)
        if not fi or not fi['thumb'] or not fi['shared']:
            continue
        if not fi['mime'].startswith('image/') or 'svg' in fi['mime'] or 'gif' in fi['mime']:
            continue
        fname = ft[5:].replace('_', ' ')
        if JUNK_FILE_RE.search(fname):
            continue
        text = (fname + ' ' + fi['desc']).lower()
        if sn not in text and full not in text:
            continue                     # someone / something else pictured
        if RELATIVE_RE.search(text) or MEMORIAL_RE.search(text):
            continue                     # a relative, or a plaque / statue of the player
        if fi['year'] and fi['year'] not in by_year:
            continue                     # dated outside the career (alumni events, rallies) → never a jersey shot
        tags = {}
        for m in TEAM_WORD_RE.finditer(text):
            t = TEAM_WORDS[m.group(1).lower()]
            if t in my_teams:
                tags[t] = tags.get(t, 0) + 2
        if fi['year'] and by_year.get(fi['year']):
            t = by_year[fi['year']]
            tags[t] = tags.get(t, 0) + 1
        for t, score in tags.items():
            cur = best.get(t)
            if cur is None or score > cur['score']:
                best[t] = {'url': fi['thumb'], 'credit': fi['credit'], 'score': score}
    return {t: {'url': b['url'], 'credit': b['credit']} for t, b in best.items()}


# ---------------------------------------------------------------- main ----
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--only-missing', action='store_true', default=True,
                    help='skip names already in the output / state file (default)')
    ap.add_argument('--refresh', action='store_true', help='re-query every candidate (clears state)')
    ap.add_argument('--names', nargs='*', help='only these names (still must lack an ESPN id unless --force)')
    ap.add_argument('--force', action='store_true', help='with --names: query even if an ESPN id exists')
    ap.add_argument('--limit', type=int, default=0, help='stop after N candidates (testing)')
    ap.add_argument('--skip-teams', action='store_true', help='stage A only (no per-team candidates)')
    ap.add_argument('--skip-audit', action='store_true', help='skip the ESPN id sanity pass')
    ap.add_argument('--skip-file-search', action='store_true', help='skip stage C (Commons file search)')
    ap.add_argument('--dry-run', action='store_true', help='list candidates, no requests')
    args = ap.parse_args()

    careers = load_careers()
    espn_ids = load_espn_ids()
    espn = set(espn_ids)
    notable = {n for n, s in careers.items() if is_notable(s)}
    no_id = [n for n in careers if n not in espn]
    print('legend_careers: %d names · %d have an ESPN id · %d without' % (len(careers), len(careers) - len(no_id), len(no_id)))
    print('notable (3+ seasons >= 150 fpts): %d · without ESPN id: %d' % (
        len(notable), sum(1 for n in no_id if n in notable)))

    table = load_existing()
    state = load_state()
    if args.refresh:
        table = {}
        state = {'searched': {}, 'teams_done': {}}
    searched = state.setdefault('searched', {})
    teams_done = state.setdefault('teams_done', {})
    # ESPN id sanity pass: names whose id points at the wrong athlete get a Commons
    # photo too, flagged preferCommons so the reveal takes it before the ESPN path.
    suspects = set()
    if not args.skip_audit and not args.dry_run:
        suspects = audit_espn_ids(careers, espn_ids)
    for n in suspects:
        if n in table:
            table[n]['preferCommons'] = True
    if args.names:
        cands = [n for n in args.names if args.force or n not in espn]
        for n in cands:
            searched.pop(n, None)
            teams_done.pop(n, None)
    else:
        cands = [n for n in no_id if not (args.only_missing and (n in table or n in searched))]
        cands += [n for n in sorted(suspects) if n not in table and n not in cands]
    if args.limit:
        cands = cands[:args.limit]
    print('stage A: querying %d names (%d already in output, %d searched before)' % (len(cands), len(table), len(searched)))
    if args.dry_run:
        for n in cands:
            print('  ', n, '(notable)' if n in notable else '')
        return

    meta = {'date': time.strftime('%Y-%m-%d'), 'notable_total': len(notable), 'notable_hit': 0}

    def refresh_meta():
        meta['notable_hit'] = sum(1 for n in notable if n in table or n in espn)

    # ---- Stage A: find the article + lead image ---------------------------
    pending = list(cands)
    found = {}          # name -> page dict
    ambiguous = set()   # plain title existed but was a namesake/disambig → try positional titles
    for vi, variant in enumerate(VARIANTS):
        if vi >= 2:
            pending = [n for n in pending if n in ambiguous]
        if not pending:
            break
        print('pass %d/%d  %-28s %d names' % (vi + 1, len(VARIANTS), variant.format(n='…'), len(pending)), flush=True)
        still = []
        for i in range(0, len(pending), BATCH):
            chunk = pending[i:i + BATCH]
            titles = [variant.format(n=n) for n in chunk]
            res = query_pages(titles)
            for n, t in zip(chunk, titles):
                p = res.get(t)
                if p and page_ok(p) and p.get('thumbnail', {}).get('source'):
                    found[n] = p
                else:
                    if p and vi == 1 and not page_ok(p):
                        ambiguous.add(n)
                    still.append(n)
            print('  %d/%d  hits so far %d' % (min(i + BATCH, len(pending)), len(pending), len(found)), flush=True)
        pending = still
    print('stage A: matched %d of %d candidates' % (len(found), len(cands)))

    for n in cands:
        searched[n] = meta['date']
    for n, p in found.items():
        table[n] = {
            'url': p['thumbnail']['source'].split('?')[0],   # drop utm_* tracking query
            'credit': 'Wikimedia Commons',                   # refined in stage B
            'page': 'https://en.wikipedia.org/wiki/' + urllib.parse.quote(p['title'].replace(' ', '_')),
        }
        if n in suspects:
            table[n]['preferCommons'] = True
    refresh_meta()
    write_out(table, meta)
    save_state(state)

    # ---- Stage C: Commons file search for the names stage A could not place --
    c_searched = state.setdefault('commons_searched', {})
    if args.names:
        todo_c = [n for n in args.names if n not in table and (args.force or n not in espn or n in suspects)]
    else:
        todo_c = [n for n in no_id if n not in table and n not in c_searched]
        todo_c += [n for n in sorted(suspects) if n not in table and n not in todo_c and n not in c_searched]
    if args.skip_file_search:
        todo_c = []
    print('stage C: Commons file search for %d names (%d searched before)' % (len(todo_c), len(c_searched)), flush=True)
    c_hits = 0
    for i in range(0, len(todo_c), IMG_BATCH):
        chunk = todo_c[i:i + IMG_BATCH]
        files = {}
        for n in chunk:
            sn = surname(n)
            hits = commons_file_search(n)
            files[n] = [f for f in hits if re.search(r'\.(jpe?g|png|webp)$', f, re.I)
                        and sn in f.lower() and not JUNK_FILE_RE.search(f.replace('_', ' '))][:10]
        all_files = sorted({f for lst in files.values() for f in lst})
        info = image_info(all_files) if all_files else {}
        for n in chunk:
            c_searched[n] = meta['date']
            best, by_team = pick_from_search(n, careers.get(n, []), files[n], info)
            if not best:
                continue
            table[n] = {
                'url': best['url'], 'credit': best['credit'],
                'page': 'https://commons.wikimedia.org/wiki/' + urllib.parse.quote(best['file'].replace(' ', '_')),
            }
            bt = {t: b for t, b in by_team.items() if b['url'] != best['url']}
            if bt:
                table[n]['byTeam'] = bt
            if n in suspects:
                table[n]['preferCommons'] = True
            teams_done[n] = meta['date']     # stage B reads Wikipedia titles; these are Commons files
            c_hits += 1
        refresh_meta()
        write_out(table, meta)
        save_state(state)
        print('  %d/%d  hits so far %d' % (min(i + IMG_BATCH, len(todo_c)), len(todo_c), c_hits), flush=True)
    if todo_c:
        print('stage C: matched %d of %d' % (c_hits, len(todo_c)))

    # ---- Stage B: candidates per team + credits ---------------------------
    todo = [n for n in sorted(table) if not args.skip_teams and n not in teams_done]
    if args.names:
        todo = [n for n in todo if n in args.names]
    print('stage B: %d names need per-team candidates (%d done before)' % (len(todo), len(teams_done)), flush=True)
    for i in range(0, len(todo), IMG_BATCH):
        chunk = todo[i:i + IMG_BATCH]
        title_of = {n: urllib.parse.unquote(table[n]['page'].rsplit('/', 1)[1]).replace('_', ' ') for n in chunk}
        imgs = article_images([title_of[n] for n in chunk])
        # Commons category (usually named after the article) holds the dated in-uniform
        # shots and PD-era trading cards the article itself does not embed.
        cats = commons_categories(sorted({title_of[n] for n in chunk}))
        files = {}
        for n in chunk:
            lead = file_from_thumb(table[n]['url'])
            lst = list(imgs.get(title_of[n], []))
            if title_of[n] in cats:
                for f in commons_category_files(title_of[n]):
                    if f not in lst:
                        lst.append(f)
            if lead and lead not in lst:
                lst.insert(0, lead)
            # cheap pre-filter before the imageinfo call
            sn = surname(n)
            keep = [f for f in lst if re.search(r'\.(jpe?g|png|webp)$', f, re.I) and not JUNK_FILE_RE.search(f.replace('_', ' '))]
            keep = [f for f in keep if f == lead or sn in f.lower()]
            files[n] = keep[:30]
        all_files = sorted({f for lst in files.values() for f in lst})
        info = image_info(all_files)
        for n in chunk:
            lead = file_from_thumb(table[n]['url'])
            li = info.get(lead) if lead else None
            if li and li['thumb']:
                table[n]['url'] = li['thumb']
                table[n]['credit'] = li['credit']
            by_team = tag_candidates(n, careers.get(n, []), files[n], info)
            if by_team:
                # drop teams whose pick is just the default photo
                by_team = {t: b for t, b in by_team.items() if b['url'] != table[n]['url']} or {}
                if by_team:
                    table[n]['byTeam'] = by_team
            else:
                table[n].pop('byTeam', None)
            teams_done[n] = meta['date']
        write_out(table, meta)
        save_state(state)
        n_bt = sum(1 for n in table if table[n].get('byTeam'))
        print('  %d/%d  (%d files) · %d legends with jersey photos' % (min(i + IMG_BATCH, len(todo)), len(todo), len(all_files), n_bt), flush=True)

    refresh_meta()
    write_out(table, meta)
    save_state(state)

    # ---- Report -------------------------------------------------------------
    miss_notable = sorted(n for n in notable if n not in table and n not in espn)
    n_bt = sum(1 for n in table if table[n].get('byTeam'))
    n_teams = sum(len(table[n].get('byTeam') or {}) for n in table)
    print('\n== coverage ==')
    print('photos in output: %d · with per-team jersey photos: %d (%d team photos) · preferCommons (bad ESPN id): %d' % (
        len(table), n_bt, n_teams, sum(1 for n in table if table[n].get('preferCommons'))))
    print('notable legends: %d · with ESPN id: %d · with Wikipedia photo: %d · still none: %d' % (
        len(notable), sum(1 for n in notable if n in espn),
        sum(1 for n in notable if n in table and n not in espn), len(miss_notable)))
    print('all legends without ESPN id: %d · now with photo: %d' % (
        len(no_id), sum(1 for n in no_id if n in table)))
    if miss_notable:
        print('notable still missing (%d): %s' % (len(miss_notable), ', '.join(miss_notable[:60])
                                                  + (' …' if len(miss_notable) > 60 else '')))


if __name__ == '__main__':
    main()
