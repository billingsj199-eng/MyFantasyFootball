# Automated betting-lines puller for data/betting_lines_2026.js.
#
# Two phases (run either or both):
#   python scripts/pull_betting_lines.py                  # both phases
#   python scripts/pull_betting_lines.py --game-lines     # spreads/totals only (no Chrome)
#   python scripts/pull_betting_lines.py --season-props   # DK season player props only
#
# Phase A — GAME LINES (requests, keyless):
#   ESPN's public core API carries DraftKings spreads + over/unders for every
#   scheduled game, all 18 weeks, even in the offseason. One scoreboard call
#   per week for the schedule, one odds call per game (~272 total, throttled).
#   ESPN "provider" is DraftKings, so source stays 'DK'.
#
# Phase B — SEASON PLAYER PROPS (Selenium, visible Chrome):
#   DraftKings blocks plain requests (403) but a real Chrome passes; we drive
#   the NFL league page and issue same-session in-page fetch() calls against
#   their sportscontent API (same pattern as the PFR scrapers). Category and
#   subcategory IDs are resolved BY NAME each run ("Player Futures" /
#   "Rookie Watch" -> Passing Yards, Rushing TDs, ...) so DK id churn doesn't
#   break the pull. Only the Over line number is kept (odds not needed).
#
# Both phases surgically rewrite their const block inside
# data/betting_lines_2026.js; header comments, the other block, and the
# helper functions at the bottom are preserved byte-for-byte. Manual FD/MGM
# entries in seasonProps are preserved per player — only DK is overwritten.
# Players DK no longer lists keep their old lines (asOf marks staleness).
#
# After a successful write the index.html script tag ?v= is bumped.
#
# Phase D — WEEKLY PLAYER PROPS (Underdog requests + PrizePicks Selenium):
#   fills BETTING_2026.weeklyProps keyed by week -> player -> book. Standard
#   lines only (UD boosts and PP demons/goblins are skipped, as are first-TD
#   and quarter/half markets). Re-run weekly in season; past weeks are kept.
#   DK per-event weekly markets could be added later via Phase B's in-page
#   fetch once they post.

import argparse
import datetime
import json
import os
import re
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(ROOT, 'data', 'betting_lines_2026.js')
INDEX_FILE = os.path.join(ROOT, 'index.html')
TODAY = datetime.date.today().isoformat()

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')

# ---------------------------------------------------------------------------
# Shared: d.js name normalization (same pattern as pull_snap_counts.py)
# ---------------------------------------------------------------------------

def norm_variants(name):
    v = {name}
    v.add(name.replace('.', ''))
    no_suffix = re.sub(r'\s+(Jr\.?|Sr\.?|II|III|IV|V)$', '', name, flags=re.I).strip()
    v.add(no_suffix)
    v.add(no_suffix.replace('.', ''))
    return {x.lower() for x in v}


def load_d_names():
    src = open(os.path.join(ROOT, 'data', 'd.js'), encoding='utf-8').read()
    names = set(re.findall(r'[,{]"n":"([^"]+)"', src))
    if not names:
        names = set(re.findall(r'[,{]n:"([^"]+)"', src))
    lookup = {}
    for n in names:
        for v in norm_variants(n):
            lookup.setdefault(v, n)
    print(f'd.js players: {len(names)} ({len(lookup)} name variants)')
    return lookup


# ---------------------------------------------------------------------------
# Phase A — game lines from ESPN (DraftKings provider)
# ---------------------------------------------------------------------------

# NOTE 2026-08-28: site.api.espn.com/scoreboard started hard-403ing plain
# requests (empty body, any UA) — every week logged "scoreboard failed".
# Week schedules now come from the core API (same host as the odds calls,
# still open); the odds payload itself supplies away/home team ids.
# The 2026s are the season year — bump yearly like the old dates=2026.
WEEK_EVENTS = ('https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/'
               'seasons/2026/types/2/weeks/{wk}/events?limit=100')
TEAMS_LIST = ('https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/'
              'seasons/2026/teams?limit=40')
ODDS = ('https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/'
        'events/{eid}/competitions/{eid}/odds')

# ESPN abbreviation -> site convention (betting_lines keys)
TEAM_FIX = {'WSH': 'WAS', 'JAC': 'JAX', 'LA': 'LAR'}


def _fix(abbr):
    a = (abbr or '').upper()
    return TEAM_FIX.get(a, a)


def _team_abbr_map(sess):
    """One-time ESPN team-id -> site abbr map off the core API (32 small
    fetches at start; the odds payloads only carry team ids in $ref URLs)."""
    m = {}
    try:
        refs = sess.get(TEAMS_LIST, timeout=30).json().get('items', [])
    except Exception as e:
        print(f'  teams list failed ({e})')
        return m
    for r in refs:
        try:
            t = sess.get(str(r.get('$ref', '')), timeout=30).json()
            tid, ab = str(t.get('id', '')), _fix(t.get('abbreviation'))
            if tid and ab:
                m[tid] = ab
        except Exception:
            pass
    return m


def pull_game_lines():
    """Return {key: {'total': float|None, 'spread': float|None, 'source': str}}."""
    sess = requests.Session()
    sess.headers.update({'User-Agent': UA, 'Accept': 'application/json'})
    teams = _team_abbr_map(sess)
    if len(teams) < 32:
        print(f'  WARN: only {len(teams)}/32 team abbrs resolved — expect misses')
    out = {}
    misses = []
    for wk in range(1, 19):
        try:
            evs = sess.get(WEEK_EVENTS.format(wk=wk), timeout=30).json().get('items', [])
        except Exception as e:
            print(f'  W{wk}: events list failed ({e}), skipping week')
            continue
        print(f'  W{wk}: {len(evs)} games')
        for evref in evs:
            em = re.search(r'/events/(\d+)', str(evref.get('$ref', '')))
            if not em:
                continue
            eid = em.group(1)
            away = home = None
            total = spread = None
            source = 'DK'
            try:
                time.sleep(0.2)
                od = sess.get(ODDS.format(eid=eid), timeout=30).json()
                items = od.get('items', [])
                # prefer DraftKings, else first provider with numbers
                items.sort(key=lambda it: 0 if 'draftkings' in
                           str((it.get('provider') or {}).get('name', '')).lower() else 1)
                # away/home from any item's team $refs (same game on every item)
                for it in items:
                    for side in ('awayTeamOdds', 'homeTeamOdds'):
                        ref = str(((it.get(side) or {}).get('team') or {}).get('$ref', ''))
                        tm = re.search(r'/teams/(\d+)', ref)
                        ab = teams.get(tm.group(1)) if tm else None
                        if ab:
                            if side == 'awayTeamOdds':
                                away = ab
                            else:
                                home = ab
                    if away and home:
                        break
                for it in items:
                    ou = it.get('overUnder')
                    sp = it.get('spread')
                    details = it.get('details') or ''
                    pname = str((it.get('provider') or {}).get('name', ''))
                    if not isinstance(ou, (int, float)) and not isinstance(sp, (int, float)):
                        continue
                    if isinstance(ou, (int, float)):
                        total = float(ou)
                    if isinstance(sp, (int, float)):
                        spread = float(sp)
                        # sanity: `details` names the favorite ("NYG -1.5").
                        # File convention: spread is HOME-relative (neg = home fav).
                        m = re.match(r'\s*([A-Z]{2,4})\s*([+-][\d.]+)', details)
                        if m:
                            fav, num = _fix(m.group(1)), float(m.group(2))
                            if fav == away:
                                spread = abs(num)
                            elif fav == home:
                                spread = -abs(num)
                    if 'draftkings' not in pname.lower():
                        source = 'ESPNBET' if 'espn' in pname.lower() else pname[:8]
                    break
            except Exception:
                pass
            if not away or not home:
                misses.append(f'W{wk}_eid{eid}')
                continue
            key = f'W{wk}_{away}_{home}'
            if total is None and spread is None:
                misses.append(key)
                continue
            out[key] = {'total': total, 'spread': spread, 'source': source}
    print(f'  pulled lines for {len(out)} games'
          + (f' — no odds yet for {len(misses)}: {", ".join(misses[:8])}...' if misses else ''))
    return out


def emit_game_totals_block(lines):
    """lines: {key: {...}} merged records ready to print (all with total/spread/asOf/source)."""
    by_week = {}
    for key, rec in lines.items():
        wk = int(re.match(r'W(\d+)_', key).group(1))
        by_week.setdefault(wk, []).append((key, rec))
    parts = ['const _GAME_TOTALS_2026 = {']
    for wk in sorted(by_week):
        parts.append(f'  // ===== Week {wk} =====')
        for key, r in by_week[wk]:
            total = f"{r['total']}" if r.get('total') is not None else 'null'
            sp = r.get('spread')
            spread = ('+' + str(sp) if isinstance(sp, (int, float)) and sp > 0 else str(sp)) \
                if sp is not None else 'null'
            parts.append(f"  '{key}':{' ' * max(1, 22 - len(key))}"
                         f"{{ total: {total}, spread: {spread}, "
                         f"asOf: '{r['asOf']}', source: '{r['source']}' }},")
        parts.append('')
    if parts[-1] == '':
        parts.pop()
    parts.append('};')
    return '\n'.join(parts)


def update_game_lines(src):
    print('Phase A: game lines (ESPN/DraftKings)...')
    pulled = pull_game_lines()
    if len(pulled) < 200:
        print(f'  !! only {len(pulled)} games pulled — refusing to rewrite gameTotals '
              f'(existing block kept)')
        return src, 0
    # merge: keep existing entries ESPN had no odds for
    existing = parse_game_totals(src)
    changed = 0
    merged = {}
    for key, old in existing.items():
        merged[key] = dict(old)
    for key, rec in pulled.items():
        old = existing.get(key)
        rec = {'total': rec['total'], 'spread': rec['spread'],
               'asOf': TODAY, 'source': rec['source']}
        if rec['total'] is None and old:
            rec['total'] = old.get('total')
        if rec['spread'] is None and old:
            rec['spread'] = old.get('spread')
        if not old or old.get('total') != rec['total'] or old.get('spread') != rec['spread']:
            changed += 1
        else:
            rec['asOf'] = old.get('asOf', TODAY)  # unchanged line keeps its date
        merged[key] = rec
    block = emit_game_totals_block(merged)
    new_src = replace_block(src, '_GAME_TOTALS_2026', block)
    print(f'  gameTotals: {len(merged)} games, {changed} lines new/changed')
    return new_src, changed


# ---------------------------------------------------------------------------
# Phase B — DK season player props via Selenium
# ---------------------------------------------------------------------------

DK_LEAGUE_PAGE = 'https://sportsbook.draftkings.com/leagues/football/nfl'
DK_API = 'https://sportsbook-nash.draftkings.com/sites/US-NJ-SB/api/sportscontent/dkusnj/v1'

PROP_CATEGORIES = {'player futures', 'rookie watch'}

# DK full names -> d.js names that norm_variants can't bridge
DK_NAME_FIX = {
    'Cameron Skattebo': 'Cam Skattebo',
    'Cameron Ward': 'Cam Ward',
}
STAT_KEYS = {
    'passing yards': 'py', 'pass yards': 'py',
    'passing tds': 'ptd', 'pass tds': 'ptd',
    'interceptions': 'int',
    'rushing yards': 'ry', 'rush yards': 'ry',
    'rushing tds': 'rtd', 'rush tds': 'rtd',
    'receiving yards': 'rcy', 'rec yards': 'rcy',
    'receiving tds': 'rctd', 'rec tds': 'rctd',
    'receptions': 'rec',
}


def _make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        path = ChromeDriverManager().install()
    except Exception:
        path = None
    opts = Options()
    # Visible window — headless trips DK's bot detection (same as PFR).
    opts.add_argument('--disable-blink-features=AutomationControlled')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--window-size=1400,900')
    opts.add_experimental_option('excludeSwitches', ['enable-automation'])
    opts.add_experimental_option('useAutomationExtension', False)
    drv = webdriver.Chrome(service=Service(path) if path else Service(), options=opts)
    drv.set_page_load_timeout(60)
    drv.set_script_timeout(60)
    return drv


def _page_fetch(driver, url):
    res = driver.execute_async_script("""
        const url = arguments[0], done = arguments[arguments.length-1];
        fetch(url, {headers:{Accept:'application/json'}})
          .then(r => r.text().then(t => done(JSON.stringify({status:r.status, body:t}))))
          .catch(e => done(JSON.stringify({error:String(e)})));
    """, url)
    res = json.loads(res)
    if res.get('status') != 200:
        raise RuntimeError(f"DK API {res.get('status') or res.get('error')} for {url}")
    return json.loads(res['body'])


def _parse_season_over_lines(body, stat, players):
    """Collect 'Over' season lines from one DK subcategory payload into
    players{name: {stat: line}}; returns the number of lines added."""
    markets = {m['id']: m for m in body.get('markets', [])}
    count = 0
    for sel in body.get('selections', []):
        if sel.get('outcomeType') != 'Over':
            continue
        m = markets.get(sel.get('marketId'))
        if not m:
            continue
        # "NFL 2026/27 - Josh Allen Regular Season Passing Yards"
        pm = re.match(r'NFL \d{4}/\d{2}\s*-\s*(.+?)\s+(?:Regular Season|Rookie)',
                      m.get('name', ''))
        lm = re.search(r'Over\s+([\d,]+\.?\d*)', sel.get('label', ''))
        if not pm or not lm:
            continue
        players.setdefault(pm.group(1).strip(), {})[stat] = \
            float(lm.group(1).replace(',', ''))
        count += 1
    return count


def pull_season_props():
    """Return {dk_player_name: {statKey: line}} from DK Player Futures + Rookie Watch."""
    driver = _make_driver()
    try:
        print(f'  loading {DK_LEAGUE_PAGE} (Chrome window will open — ignore it)')
        driver.get(DK_LEAGUE_PAGE)
        time.sleep(8)
        league = _page_fetch(driver, f'{DK_API}/leagues/88808')
        cats = {c['id']: c.get('name', '') for c in league.get('categories', [])}
        subs = []
        for s in league.get('subcategories', []):
            cat_name = cats.get(s.get('categoryId'), '').lower()
            stat = STAT_KEYS.get(s.get('name', '').lower())
            if cat_name in PROP_CATEGORIES and stat:
                subs.append((s.get('categoryId'), s['id'], stat, cats.get(s.get('categoryId')), s.get('name')))
        if not subs:
            raise RuntimeError('no season-prop subcategories found — DK layout changed?')
        print(f'  {len(subs)} prop subcategories resolved by name:')
        players = {}
        for cat_id, sub_id, stat, cat_name, sub_name in subs:
            try:
                body = _page_fetch(driver,
                                   f'{DK_API}/leagues/88808/categories/{cat_id}/subcategories/{sub_id}')
            except Exception as e:
                print(f'    {cat_name} / {sub_name}: FAILED ({e})')
                continue
            count = _parse_season_over_lines(body, stat, players)
            print(f'    {cat_name} / {sub_name} -> {stat}: {count} lines')
            time.sleep(1.0)
        return players
    finally:
        driver.quit()


BOOK_ORDER = ('DK', 'FD', 'MGM', 'UD', 'PP')
STAT_ORDER = ['py', 'ptd', 'int', 'ry', 'rtd', 'ra', 'rec', 'rcy', 'rctd', 'rrtd', 'fgm', 'kpts', 'atd']


def parse_props_entry(raw):
    """Parse one player's raw JS object body into {'DK': 'raw', 'FD': 'raw', ...}."""
    books = {}
    for book in BOOK_ORDER:
        m = re.search(book + r':\s*\{([^}]*)\}', raw)
        if m:
            books[book] = m.group(1).strip()
    m = re.search(r"asOf:\s*'([^']+)'", raw)
    books['asOf'] = m.group(1) if m else TODAY
    return books


def canonize(pulled, lookup, label, drop_unmatched=False):
    """Map pulled {book_name: stats} onto d.js names."""
    canon, unmatched = {}, []
    for name, stats in pulled.items():
        name = DK_NAME_FIX.get(name, name)
        hit = None
        for v in norm_variants(name):
            if v in lookup:
                hit = lookup[v]
                break
        if not hit:
            unmatched.append(name)
            if drop_unmatched:
                continue
            hit = name
        canon[hit] = stats
    if unmatched:
        act = 'dropped' if drop_unmatched else 'kept as-is'
        print(f'  {len(unmatched)} {label} names not in d.js ({act}): '
              + ', '.join(sorted(unmatched)[:12]))
    return canon


# ---------------------------------------------------------------------------
# Season "last seen" stamps (added 2026-09-08)
# ---------------------------------------------------------------------------
# _SEASON_SEEN_2026 = { 'Name': { DK: { ry: '2026-08-26', rec: '2026-09-08' }, … } }
# — the last date each book's season pull CONFIRMED a stat line for the
# player. A book that delists a market keeps its old line in seasonProps
# (Jack's rule: the number is still informative) but its seen date stops
# moving; the site greys a line not seen for 7+ days (vs the player's newest
# stamp) and drops it from the consensus/projection. Seeded once from the
# line-movement history (last change date per book/stat, else the player's
# asOf), then stamped by every successful merge. Exported as seasonSeen.

def parse_season_seen(src):
    try:
        block = extract_block(src, '_SEASON_SEEN_2026')
    except ValueError:
        return None
    out = {}
    for m in re.finditer(r"^\s*(?:'((?:[^'\\]|\\.)*)'|\"([^\"]*)\"):\s*\{(.*)\},?\s*$", block, re.M):
        name = (m.group(1) or m.group(2)).replace("\\'", "'")
        books = {}
        for bm in re.finditer(r"(\w+):\s*\{([^}]*)\}", m.group(3)):
            stats = {sm.group(1): sm.group(2) for sm in re.finditer(r"(\w+):\s*'(\d{4}-\d{2}-\d{2})'", bm.group(2))}
            if stats:
                books[bm.group(1)] = stats
        out[name] = books
    return out


def _seed_season_seen(src):
    """First-time seed: last change date per (book, stat) from the history
    file, else the player's asOf."""
    hist = load_lines_history().get('season', {})
    seen = {}
    block = extract_block(src, '_SEASON_PROPS_2026')
    for m in re.finditer(r"^\s*(?:'((?:[^'\\]|\\.)*)'|\"([^\"]*)\"):\s*\{(.*)\},?\s*$", block, re.M):
        name = (m.group(1) or m.group(2)).replace("\\'", "'")
        books = parse_props_entry(m.group(3))
        as_of = books.get('asOf') or TODAY
        for b in BOOK_ORDER:
            if not books.get(b):
                continue
            for stat in _raw_stats_to_dict(books[b]):
                pts = ((hist.get(name) or {}).get(b) or {}).get(stat)
                date = pts[-1][0][:10] if pts else as_of
                seen.setdefault(name, {}).setdefault(b, {})[stat] = date
    return seen


def emit_season_seen(src, seen):
    lines = []
    for name in sorted(seen):
        parts = []
        for b in BOOK_ORDER:
            stats = seen[name].get(b)
            if not stats:
                continue
            inner = ', '.join(f"{k}: '{v}'" for k, v in sorted(stats.items(), key=lambda kv: STAT_ORDER.index(kv[0]) if kv[0] in STAT_ORDER else 99))
            parts.append(f'{b}: {{ {inner} }}')
        if not parts:
            continue
        q = name.replace("'", "\\'")
        lines.append(f"  '{q}': {{ {', '.join(parts)} }},")
    if lines:
        lines[-1] = lines[-1].rstrip(',')
    new_block = ('const _SEASON_SEEN_2026 = {\n' + '\n'.join(lines) + '\n};')
    try:
        return replace_block(src, '_SEASON_SEEN_2026', new_block)
    except ValueError:
        # first write: place the block right after the season props and wire
        # it into window.BETTING_2026
        s_end = _block_span(src, '_SEASON_PROPS_2026')[1]
        src = (src[:s_end] + '\n\n// Last date each book confirmed a season stat line (see pull_betting_lines.py).\n'
               + new_block + src[s_end:])
        hook = '  seasonProps: _SEASON_PROPS_2026,'
        if hook in src and 'seasonSeen:' not in src:
            src = src.replace(hook, hook + '\n  seasonSeen: _SEASON_SEEN_2026,     // per-book/stat last-seen dates', 1)
        return src


def stamp_season_seen(src, book, canon, stats_only=None):
    """Mark every (book, stat) in `canon` as seen TODAY."""
    seen = parse_season_seen(src)
    if seen is None:
        seen = _seed_season_seen(src)
    for name, stats in canon.items():
        for stat in stats:
            if stats_only is not None and stat not in stats_only:
                continue
            seen.setdefault(name, {}).setdefault(book, {})[stat] = TODAY
    return emit_season_seen(src, seen)


def merge_props_book(src, book, canon, seen_stats=None):
    """Rewrite _SEASON_PROPS_2026 with fresh `canon` lines for `book`;
    all other books' entries are preserved verbatim per player."""
    block = extract_block(src, '_SEASON_PROPS_2026')
    existing = {}   # name -> books dict
    order = []
    for m in re.finditer(r"^\s*(?:'((?:[^'\\]|\\.)*)'|\"([^\"]*)\"):\s*\{(.*)\},?\s*$",
                         block, re.M):
        name = (m.group(1) or m.group(2)).replace("\\'", "'")
        existing[name] = parse_props_entry(m.group(3))
        order.append(name)

    # drop entries a previous run may have written under an alias name
    order = [n for n in order if n not in DK_NAME_FIX]

    changed = 0
    all_names = order + [n for n in canon if n not in existing and n not in order]
    lines = []
    for name in all_names:
        old = existing.get(name, {})
        books = dict(old)
        if name in canon:
            new_raw = ', '.join(f'{k}: {v}' for k, v in
                                sorted(canon[name].items(),
                                       key=lambda kv: STAT_ORDER.index(kv[0])))
            if new_raw != old.get(book, ''):
                changed += 1
                books['asOf'] = TODAY
            books[book] = new_raw
        parts = []
        for b in BOOK_ORDER:
            if books.get(b):
                parts.append(f'{b}: {{ {books[b]} }}')
        parts.append(f"asOf: '{books.get('asOf', TODAY)}'")
        q = name.replace("'", "\\'")
        lines.append(f"  '{q}': {{ {', '.join(parts)} }},")
    lines[-1] = lines[-1].rstrip(',')
    new_block = 'const _SEASON_PROPS_2026 = {\n' + '\n'.join(lines) + '\n};'
    print(f'  seasonProps[{book}]: {len(all_names)} players total, {len(canon)} with '
          f'fresh {book}, {changed} changed')
    src = replace_block(src, '_SEASON_PROPS_2026', new_block)
    src = stamp_season_seen(src, book, canon, seen_stats)
    return src, changed


def update_season_props(src):
    print('Phase B: DK season player props (Selenium)...')
    lookup = load_d_names()
    pulled = pull_season_props()
    if len(pulled) < 30:
        print(f'  !! only {len(pulled)} players pulled — refusing to rewrite seasonProps')
        return src, 0
    canon = canonize(pulled, lookup, 'DK')
    return merge_props_book(src, 'DK', canon)


# ---------------------------------------------------------------------------
# Phase C — Underdog season props (plain requests, no auth)
# ---------------------------------------------------------------------------

# 2026-09-08: the beta/v6 route started answering 426 'upgrade_required'
# (api_code) for every client — v1 serves the same schema (appearances /
# games / players / over_under_lines) and is what the web app reads now.
# Try in order; the first 2xx wins.
UD_URLS = (
    'https://api.underdogfantasy.com/v1/over_under_lines',
    'https://api.underdogfantasy.com/beta/v6/over_under_lines',
)
UD_URL = UD_URLS[0]

UD_STAT_KEYS = {
    'season_pass_yards': 'py', 'season_pass_tds': 'ptd',
    'season_rush_yards': 'ry', 'season_rush_tds': 'rtd',
    'season_receiving_yards': 'rcy', 'season_rec_yards': 'rcy',
    'season_rec_tds': 'rctd', 'season_receptions': 'rec',
    'season_interceptions': 'int',
}


_UD_CACHE = None


def _fetch_ud():
    """Download the Underdog board once per run (season + weekly phases share it)."""
    global _UD_CACHE
    if _UD_CACHE is None:
        last_err = None
        for url in UD_URLS:
            try:
                r = requests.get(url, timeout=60,
                                 headers={'User-Agent': UA, 'Accept': 'application/json'})
                r.raise_for_status()
                _UD_CACHE = r.json()
                print(f'  Underdog board: {url.split("underdogfantasy.com")[1]} '
                      f'({len(_UD_CACHE.get("over_under_lines", []))} lines)')
                break
            except Exception as e:  # 426 upgrade_required, 5xx, bad JSON
                last_err = e
                print(f'  Underdog {url.split("underdogfantasy.com")[1]} failed ({e}) - trying next')
        if _UD_CACHE is None:
            raise last_err
    return _UD_CACHE


def pull_underdog_props():
    """Return {player_name: {statKey: line}} from Underdog pick'em season lines.
    Both 'Season X' and 'Regular Season X' variants exist; 'Regular Season'
    wins when a player has both (matches how sportsbooks grade)."""
    d = _fetch_ud()
    apps = {a['id']: a for a in d.get('appearances', [])}
    players = {p['id']: p for p in d.get('players', [])}
    out = {}       # name -> {stat: line}
    is_reg = {}    # (name, stat) -> bool: current value came from a "Regular Season" market
    n_lines = 0
    for line in d.get('over_under_lines', []):
        ou = line.get('over_under') or {}
        ap_stat = ou.get('appearance_stat') or {}
        stat = UD_STAT_KEYS.get(ap_stat.get('stat') or '')
        if not stat:
            continue
        app = apps.get(ap_stat.get('appearance_id'))
        p = players.get((app or {}).get('player_id'))
        if not p or (p.get('sport_id') or '').upper() != 'NFL':
            continue
        try:
            val = float(line.get('stat_value'))
        except (TypeError, ValueError):
            continue
        name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        reg = 'regular season' in (ap_stat.get('display_stat') or '').lower()
        key = (name, stat)
        if stat in out.get(name, {}) and is_reg.get(key) and not reg:
            continue
        out.setdefault(name, {})[stat] = val
        is_reg[key] = reg
        n_lines += 1
    print(f'  Underdog: {n_lines} season lines across {len(out)} NFL players')
    return out


def update_underdog_props(src):
    print('Phase C: Underdog season player props (requests)...')
    lookup = load_d_names()
    try:
        pulled = pull_underdog_props()
    except Exception as e:
        print(f'  !! Underdog pull failed ({e}) — seasonProps UD untouched')
        return src, 0
    if len(pulled) < 20:
        print(f'  !! only {len(pulled)} players pulled — refusing to rewrite UD props')
        return src, 0
    # UD lists deep rookies/college names; only keep players the site knows
    canon = canonize(pulled, lookup, 'UD', drop_unmatched=True)
    return merge_props_book(src, 'UD', canon)


# ---------------------------------------------------------------------------
# Phase D — WEEKLY player props (Underdog requests + PrizePicks Selenium)
# ---------------------------------------------------------------------------
# First-TD-scorer and quarter/half markets are deliberately skipped.

UD_WEEKLY_STAT_KEYS = {
    'passing_yds': 'py', 'passing_tds': 'ptd', 'passing_ints': 'int',
    'rushing_yds': 'ry', 'receiving_yds': 'rcy', 'rush_rec_tds': 'rrtd',
    'receptions': 'rec', 'receiving_rec': 'rec',  # UD renamed it receiving_rec (v1 board, 2026-09)
    'rushing_rec_yds': None, 'rush_rec_yds': None,  # combined yds: no clean key
    'kicking_points': 'kpts', 'field_goals_made': 'fgm',  # kicker boards, if/when UD posts them
}

PP_STAT_KEYS = {
    'Pass Yards': 'py', 'Pass TDs': 'ptd', 'INT': 'int',
    'Rush Yards': 'ry', 'Receiving Yards': 'rcy', 'Rush+Rec TDs': 'rrtd',
    'Receptions': 'rec',
    'Kicking Points': 'kpts', 'FG Made': 'fgm', 'Field Goals Made': 'fgm',
}

# W1 games start Thu 2026-09-10; weeks roll over on Tuesdays.
SEASON_W1_TUESDAY = datetime.date(2026, 9, 8)


def _week_of(dt):
    wk = (dt.date() - SEASON_W1_TUESDAY).days // 7 + 1
    return wk if 1 <= wk <= 18 else None


def _validated_week(matchup_wk, dt):
    """Resolve a game's NFL week, cross-checking the matchup-derived week
    against the actual kickoff datetime (UTC, naive or aware).

    Preseason games reuse regular-season pairings, so a week_by_matchup hit
    alone is NOT proof (Aug 2026: UD preseason props landed in weeklyProps
    week 15). The kickoff must fall inside the same week's window; a game
    with no parseable kickoff is dropped rather than trusted. UTC → ET-ish
    (-5h) before taking the date, else Monday night games (00:15 UTC Tue)
    land in the next week."""
    dwk = _week_of(dt - datetime.timedelta(hours=5)) if dt else None
    if matchup_wk is not None:
        return matchup_wk if dwk == matchup_wk else None
    return dwk


def pull_ud_weekly(week_by_matchup):
    """Return {wk: {player: {stat: line}}} from Underdog's weekly board.
    Week resolved from the game title ('WAS @ PHI') via the gameTotals
    schedule; falls back to the kickoff date."""
    d = _fetch_ud()
    apps = {a['id']: a for a in d.get('appearances', [])}
    players = {p['id']: p for p in d.get('players', [])}
    games = {g['id']: g for g in d.get('games', [])}
    out = {}
    n = 0
    for line in d.get('over_under_lines', []):
        ou = line.get('over_under') or {}
        ap_stat = ou.get('appearance_stat') or {}
        raw_stat = ap_stat.get('stat') or ''
        if 'season' in raw_stat:
            continue
        stat = UD_WEEKLY_STAT_KEYS.get(raw_stat)
        if not stat:
            continue
        # standard line only — skip boosted/alt ladders
        if ou.get('boost') or line.get('line_type') not in (None, 'balanced'):
            continue
        app = apps.get(ap_stat.get('appearance_id'))
        p = players.get((app or {}).get('player_id'))
        if not p or (p.get('sport_id') or '').upper() != 'NFL':
            continue
        g = games.get((app or {}).get('match_id'))
        if not g:
            continue
        mwk = None
        m = re.match(r'([A-Z]{2,4})\s*@\s*([A-Z]{2,4})', g.get('title') or '')
        if m:
            mwk = week_by_matchup.get((m.group(1), m.group(2)))
        dt = None
        if g.get('scheduled_at'):
            try:
                dt = datetime.datetime.fromisoformat(
                    g['scheduled_at'].replace('Z', '+00:00'))
            except ValueError:
                pass
        wk = _validated_week(mwk, dt)
        if wk is None:
            continue
        try:
            val = float(line.get('stat_value'))
        except (TypeError, ValueError):
            continue
        name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        wkd = out.setdefault(wk, {})
        if stat in wkd.get(name, {}):
            continue
        wkd.setdefault(name, {})[stat] = val
        n += 1
        # UD hides per-side prices behind selection — the API exposes them on
        # every line. For the rush+rec TD 0.5, the HIGHER side's american
        # price ≈ anytime-TD odds (Jack: "they have different odds for the TD
        # scorers even if it doesn't show until you select it").
        if stat == 'rrtd':
            for opt in line.get('options') or []:
                if opt.get('choice') != 'higher':
                    continue
                price = opt.get('american_price')
                if price is None:
                    break
                try:
                    wkd[name]['atd'] = int(str(price).replace('+', ''))
                    n += 1
                except ValueError:
                    pass
                break
    print(f'  Underdog weekly: {n} lines, weeks {sorted(out)}, '
          f'{sum(len(v) for v in out.values())} player-weeks')
    return out


# Season RECEPTIONS watch (Jack, 2026-08-14): no book posts a season
# receptions prop yet, so PPR/Half/STD come out equal for pass-catchers.
# Underdog would flow in through Phase C automatically the day they post one;
# DK needs this check because the daily job skips the slow --season-props
# phase. It piggybacks on the league payload the weekly Anytime-TD pull
# already fetches — zero extra requests until the market actually appears,
# then the lines are merged into seasonProps[DK] the same morning.
_DK_SEASON_REC = None   # set by pull_dk_weekly_atd; {} = checked, none posted


def _check_dk_season_receptions(driver, league):
    global _DK_SEASON_REC
    cats = {c['id']: c.get('name', '') for c in league.get('categories', [])}
    players = {}
    for s in league.get('subcategories', []):
        if cats.get(s.get('categoryId'), '').lower() not in PROP_CATEGORIES:
            continue
        name = (s.get('name') or '').lower()
        if STAT_KEYS.get(name) != 'rec' and 'reception' not in name:
            continue
        body = _page_fetch(driver,
                           f"{DK_API}/leagues/88808/categories/{s.get('categoryId')}/subcategories/{s['id']}")
        n = _parse_season_over_lines(body, 'rec', players)
        print(f"  DK season receptions: subcategory '{s.get('name')}' -> {n} lines")
    _DK_SEASON_REC = players
    if not players:
        print('  DK season receptions: not posted yet (watch continues)')


def apply_dk_season_receptions(src):
    """Merge the receptions lines the watch found into seasonProps[DK],
    preserving each player's other DK stat lines."""
    lookup = load_d_names()
    canon = canonize(_DK_SEASON_REC, lookup, 'DK receptions')
    block = extract_block(src, '_SEASON_PROPS_2026')
    existing = {}
    for m in re.finditer(r"^\s*(?:'((?:[^'\\]|\\.)*)'|\"([^\"]*)\"):\s*\{(.*)\},?\s*$",
                         block, re.M):
        name = (m.group(1) or m.group(2)).replace("\\'", "'")
        existing[name] = parse_props_entry(m.group(3))
    full = {}
    for name, stats in canon.items():
        cur = _raw_stats_to_dict(existing.get(name, {}).get('DK'))
        cur.update(stats)
        full[name] = cur
    # only the receptions line was confirmed by this check — the player's
    # other DK stats ride along unchanged and keep their own seen dates
    return merge_props_book(src, 'DK', full, seen_stats={'rec'})


def _dk_event_weeks(body, week_by_matchup):
    """{eventId: wk} for one DK subcategory payload — matchup-name mapping
    cross-checked against the kickoff date via _validated_week (preseason
    games reuse regular-season pairings; the date is the tiebreaker)."""
    events = {}
    for ev in body.get('events', []):
        mwk = None
        # Event names look like "NE Patriots @ SEA Seahawks" — the
        # abbreviation is the first token on each side of the '@'.
        nm = ev.get('name') or ''
        if '@' in nm:
            away, _, home = nm.partition('@')
            a = (away.strip().split() or [''])[0]
            h = (home.strip().split() or [''])[0]
            mwk = week_by_matchup.get((a, h))
        dt = None
        start = ev.get('startEventDate') or ev.get('startDate')
        if start:
            try:
                dt = datetime.datetime.fromisoformat(
                    str(start).replace('Z', '+00:00')).replace(tzinfo=None)
            except ValueError:
                pass
        wk = _validated_week(mwk, dt)
        if wk is not None:
            events[ev.get('id')] = wk
    return events


# DK weekly O/U player-prop subcategories -> our stat keys, resolved BY NAME
# (subcategory ids drift). Only the clean O/U boards — the ladder markets
# ('160+' at -1440) in the sibling subcategories are alt lines, not medians.
# Kicker boards aren't posted preseason; the names are wired so they flow in
# the day DK posts them (they feed the sim-lab K prop anchor).
DK_WEEKLY_OU_SUBS = {
    'pass yards o/u': 'py', 'passing yards o/u': 'py',
    'pass tds o/u': 'ptd', 'passing tds o/u': 'ptd',
    'rush yards o/u': 'ry', 'rushing yards o/u': 'ry',
    'rec yards o/u': 'rcy', 'receiving yards o/u': 'rcy',
    'receptions o/u': 'rec',
    'kicking points o/u': 'kpts', 'kicking pts o/u': 'kpts',
    'field goals o/u': 'fgm', 'field goals made o/u': 'fgm', 'fg made o/u': 'fgm',
}

# strip the stat suffix off a DK O/U market name to get the player name
_DK_MKT_SUFFIX = re.compile(
    r'\s+(?:passing|rushing|receiving)\s+(?:yards|touchdowns)(?:\s+o/u)?$'
    r'|\s+receptions(?:\s+o/u)?$|\s+kicking\s+(?:points|pts)(?:\s+o/u)?$'
    r'|\s+field\s+goals(?:\s+made)?(?:\s+o/u)?$', re.I)


def pull_dk_weekly_stats(week_by_matchup):
    """Return {wk: {player: {stat: line}}} from DK's weekly O/U player-prop
    boards (pass/rush/rec yards, pass TDs, receptions; kicker markets join
    automatically once posted). One market per player per stat; the line is
    the Over selection's `points`. Same Selenium in-page fetch pattern as
    the Anytime TD pull."""
    driver = _make_driver()
    try:
        print(f'  loading {DK_LEAGUE_PAGE} for weekly O/U props (Chrome window — ignore it)')
        driver.get(DK_LEAGUE_PAGE)
        time.sleep(8)
        league = _page_fetch(driver, f'{DK_API}/leagues/88808')
        subs = [(s, DK_WEEKLY_OU_SUBS[(s.get('name') or '').strip().lower()])
                for s in league.get('subcategories', [])
                if (s.get('name') or '').strip().lower() in DK_WEEKLY_OU_SUBS]
        if not subs:
            print('  DK weekly O/U: no prop subcategories posted (normal in offseason)')
            return {}
        out = {}
        total = 0
        for s, stat in subs:
            try:
                body = _page_fetch(driver,
                                   f"{DK_API}/leagues/88808/categories/{s.get('categoryId')}/subcategories/{s['id']}")
            except Exception as e:
                print(f"  DK weekly {s.get('name')}: FAILED ({e})")
                continue
            events = _dk_event_weeks(body, week_by_matchup)
            markets = {m['id']: m for m in body.get('markets', [])}
            added = 0
            for sel in body.get('selections', []):
                if (sel.get('outcomeType') or '').lower() != 'over':
                    continue
                line = sel.get('points')
                if not isinstance(line, (int, float)) or line <= 0:
                    continue
                mkt = markets.get(sel.get('marketId'))
                if not mkt:
                    continue
                wk = events.get(mkt.get('eventId'))
                if wk is None:
                    continue
                player = _DK_MKT_SUFFIX.sub('', (mkt.get('name') or '').strip()).strip()
                if not player:
                    continue
                wkd = out.setdefault(wk, {})
                if stat in wkd.get(player, {}):
                    continue
                wkd.setdefault(player, {})[stat] = float(line)
                added += 1
            total += added
            print(f"  DK weekly {s.get('name')}: {added} lines")
            time.sleep(1.0)
        print(f'  DK weekly O/U: {total} lines, weeks {sorted(out)}, '
              f'{sum(len(v) for v in out.values())} player-weeks')
        return out
    finally:
        driver.quit()


def pull_dk_weekly_atd(week_by_matchup):
    """Return {wk: {player: {'atd': american_odds}}} from DK's Anytime TD
    Scorer market (per-event, posted a few days before games in season —
    empty in the offseason, which is fine). Odds are the value: every book's
    TD line is 0.5, the juice IS the signal. Same Selenium in-page fetch
    pattern as pull_season_props; subcategory resolved BY NAME."""
    driver = _make_driver()
    try:
        print(f'  loading {DK_LEAGUE_PAGE} for Anytime TD odds (Chrome window — ignore it)')
        driver.get(DK_LEAGUE_PAGE)
        time.sleep(8)
        league = _page_fetch(driver, f'{DK_API}/leagues/88808')
        try:
            _check_dk_season_receptions(driver, league)
        except Exception as e:
            print(f'  DK season receptions check failed ({e})')
        # DK names the league-level subcategory "TD Scorer" (category "TD
        # Scorers"); the per-event markets inside are "Anytime TD Scorer".
        # Exact names only: DK also posts 'Anytime TD Scorer - 1st Quarter' /
        # '- 1st Half' subcategories whose market names contain 'anytime' —
        # a substring match would let a +600 first-quarter price stand in for
        # the full-game number (first subcategory seen wins below).
        subs = [s for s in league.get('subcategories', [])
                if (s.get('name') or '').strip().lower() in ('td scorer', 'anytime td scorer')]
        if not subs:
            print('  DK Anytime TD: no subcategory posted (normal in offseason)')
            return {}
        out = {}
        n = 0
        for s in subs:
            try:
                body = _page_fetch(driver,
                                   f"{DK_API}/leagues/88808/categories/{s.get('categoryId')}/subcategories/{s['id']}")
            except Exception as e:
                print(f"  DK Anytime TD subcategory {s.get('name')}: FAILED ({e})")
                continue
            events = _dk_event_weeks(body, week_by_matchup)
            markets = {m['id']: m for m in body.get('markets', [])}
            for sel in body.get('selections', []):
                mkt = markets.get(sel.get('marketId'))
                if not mkt:
                    continue
                if (mkt.get('name') or '').strip().lower() != 'anytime td scorer':
                    continue  # skips First TD / 2+ TDs / period variants
                wk = events.get(mkt.get('eventId'))
                if wk is None:
                    continue
                player = (sel.get('label') or '').strip()
                if not player and sel.get('participants'):
                    player = (sel['participants'][0].get('name') or '').strip()
                odds = sel.get('oddsAmerican') or (sel.get('displayOdds') or {}).get('american')
                if not player or odds is None:
                    continue
                try:
                    odds = int(str(odds).replace('+', '').replace('−', '-'))
                except ValueError:
                    continue
                wkd = out.setdefault(wk, {})
                if 'atd' in wkd.get(player, {}):
                    continue
                wkd.setdefault(player, {})['atd'] = odds
                n += 1
            time.sleep(1.0)
        print(f'  DK Anytime TD: {n} odds, weeks {sorted(out)}, '
              f'{sum(len(v) for v in out.values())} player-weeks')
        return out
    finally:
        driver.quit()


def pull_pp_weekly():
    """Return {wk: {player: {stat: line}}} from PrizePicks (Selenium in-page
    fetch — DataDome blocks plain requests). Standard squares only."""
    driver = _make_driver()
    try:
        print('  loading app.prizepicks.com (second Chrome window — ignore it)')
        driver.get('https://app.prizepicks.com/')
        time.sleep(10)
        out = {}
        n = 0
        page = 1
        while page <= 12:
            res = driver.execute_async_script("""
                const [page, done] = [arguments[0], arguments[arguments.length-1]];
                fetch(`https://api.prizepicks.com/projections?league_id=9&per_page=250&page=${page}&single_stat=true`,
                      {headers:{Accept:'application/json'}})
                  .then(r => r.json()).then(j => {
                     const players = {};
                     (j.included||[]).forEach(i => {
                        if (i.type === 'new_player' || i.type === 'player')
                          players[i.id] = i.attributes.display_name || i.attributes.name;
                     });
                     const rows = (j.data||[]).map(p => {
                        const a = p.attributes;
                        const rel = p.relationships || {};
                        const pid = (rel.new_player && rel.new_player.data && rel.new_player.data.id)
                                 || (rel.player && rel.player.data && rel.player.data.id) || null;
                        return { stat: a.stat_type, line: a.line_score,
                                 odds: a.odds_type, start: a.start_time || a.board_time,
                                 player: pid ? (players[pid] || null) : null };
                     });
                     done(JSON.stringify({n: rows.length, rows, meta: j.meta || null}));
                  }).catch(e => done(JSON.stringify({error:String(e)})));
            """, page)
            r = json.loads(res)
            if r.get('error'):
                if page == 1:
                    print(f'    page 1: {r["error"]} — no PrizePicks board this run')
                else:
                    print(f'    page {page}: {r["error"]} — keeping the {page - 1} page(s) already read')
                break
            for row in r.get('rows', []):
                stat = PP_STAT_KEYS.get(row.get('stat'))
                if not stat or not row.get('player'):
                    continue
                if row.get('odds') not in (None, 'standard'):
                    continue   # demons/goblins skew the line
                try:
                    val = float(row.get('line'))
                    dt = datetime.datetime.fromisoformat(str(row.get('start'))[:19])
                except (TypeError, ValueError):
                    continue
                wk = _week_of(dt)
                if wk is None:
                    continue
                wkd = out.setdefault(wk, {})
                if stat in wkd.get(row['player'], {}):
                    continue
                wkd.setdefault(row['player'], {})[stat] = val
                n += 1
            # PP ignores per_page/page and returns the whole board in one
            # response (meta.total_pages == 1, ~7k rows in-season). Trust its
            # page count; the old "250+ rows means another page" rule asked for
            # a page 2 that DataDome rate-limited into 'Failed to fetch'.
            total_pages = int((r.get('meta') or {}).get('total_pages') or 1)
            if page >= total_pages or r.get('n', 0) == 0:
                break
            page += 1
            time.sleep(2)
        print(f'  PrizePicks weekly: {n} lines, weeks {sorted(out)}, '
              f'{sum(len(v) for v in out.values())} player-weeks')
        return out
    finally:
        driver.quit()


def _emit_entry(books):
    parts = []
    for b in BOOK_ORDER:
        if books.get(b):
            parts.append(f'{b}: {{ {books[b]} }}')
    parts.append(f"asOf: '{books.get('asOf', TODAY)}'")
    return ', '.join(parts)


def parse_weekly_block(src):
    """Parse _WEEKLY_PROPS_2026 into {wk_str: {name: books-dict}}."""
    block = extract_block(src, '_WEEKLY_PROPS_2026')
    weeks, cur = {}, None
    for ln in block.splitlines():
        mw = re.match(r"\s*'(\d+)':\s*\{\s*$", ln)
        if mw:
            cur = weeks.setdefault(mw.group(1), {})
            continue
        mp = re.match(r"\s*(?:'((?:[^'\\]|\\.)*)'|\"([^\"]*)\"):\s*\{(.*)\},?\s*$", ln)
        if mp and cur is not None:
            name = (mp.group(1) or mp.group(2)).replace("\\'", "'")
            cur[name] = parse_props_entry(mp.group(3))
    return weeks



# ---------------------------------------------------------------------------
# Off-board pruning for WEEKLY props (added 2026-09-08)
# ---------------------------------------------------------------------------
# Season props keep a player's last lines when a book delists him (asOf marks
# the staleness). Weekly props must not: a scratched player kept looking like
# he was playing (TreVeyon Henderson, W1 2026 — DK pulled his markets Tuesday,
# the file still carried +295 anytime TD). Rule: after a book's pull succeeds
# for a week, drop that book's entry for any player missing from the pull IF
#   (a) the book posted lines for someone in the same game (so the slate is
#       up — PP/DK post games progressively early in the week), and
#   (b) the player's game has not kicked off (kickoff cache from the sim
#       exporter; played games keep their lines for the LINES tab history).
# No kickoff cache / unknown team → keep (fail safe).

KICKOFF_CACHE = os.path.join(os.path.dirname(ROOT), 'sim_lab', 'data', 'kickoffs_2026.json')

TEAM_ABBR = {
    'Arizona Cardinals': 'ARI', 'Atlanta Falcons': 'ATL', 'Baltimore Ravens': 'BAL',
    'Buffalo Bills': 'BUF', 'Carolina Panthers': 'CAR', 'Chicago Bears': 'CHI',
    'Cincinnati Bengals': 'CIN', 'Cleveland Browns': 'CLE', 'Dallas Cowboys': 'DAL',
    'Denver Broncos': 'DEN', 'Detroit Lions': 'DET', 'Green Bay Packers': 'GB',
    'Houston Texans': 'HOU', 'Indianapolis Colts': 'IND', 'Jacksonville Jaguars': 'JAX',
    'Kansas City Chiefs': 'KC', 'Las Vegas Raiders': 'LV', 'Los Angeles Chargers': 'LAC',
    'Los Angeles Rams': 'LAR', 'Miami Dolphins': 'MIA', 'Minnesota Vikings': 'MIN',
    'New England Patriots': 'NE', 'New Orleans Saints': 'NO', 'New York Giants': 'NYG',
    'New York Jets': 'NYJ', 'Philadelphia Eagles': 'PHI', 'Pittsburgh Steelers': 'PIT',
    'San Francisco 49ers': 'SF', 'Seattle Seahawks': 'SEA', 'Tampa Bay Buccaneers': 'TB',
    'Tennessee Titans': 'TEN', 'Washington Commanders': 'WAS',
}


def load_d_teams():
    """d.js canonical name -> team abbr (players on FA/unknown teams omitted)."""
    src = open(os.path.join(ROOT, 'data', 'd.js'), encoding='utf-8').read()
    out = {}
    for m in re.finditer(r'"n":"([^"]+)"', src):
        tail = src[m.end():m.end() + 400]
        t = re.search(r'"t":"([^"]+)"', tail)
        if not t:
            continue
        abbr = TEAM_ABBR.get(t.group(1)) or (t.group(1) if t.group(1) in TEAM_ABBR.values() else None)
        if abbr:
            out.setdefault(m.group(1), abbr)
    return out


def load_kickoffs():
    """{wk(str): {abbr: datetime(UTC)}} from the sim exporter's ESPN cache."""
    try:
        raw = json.load(open(KICKOFF_CACHE, encoding='utf-8'))
    except (OSError, ValueError) as e:
        print(f'  kickoff cache unavailable ({e}) — off-board pruning skipped')
        return {}
    out = {}
    for wk, teams in raw.items():
        for abbr, iso in (teams or {}).items():
            try:
                out.setdefault(str(wk), {})[abbr] = datetime.datetime.fromisoformat(
                    str(iso).replace('Z', '+00:00'))
            except ValueError:
                continue
    return out


def prune_off_board(wkd, wk, book, canon, teams, kicks, games_by_team, now=None):
    """Delete `book` from players in week `wk` who are absent from the fresh
    `canon` pull, per the rule above. Returns the list of names pruned."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    covered = set()
    for name in canon:
        g = games_by_team.get(teams.get(name))
        if g:
            covered.add(g)
    kick_wk = kicks.get(str(wk)) or {}
    dropped = []
    for name in list(wkd):
        entry = wkd[name]
        if book not in entry or name in canon:
            continue
        t = teams.get(name)
        g = games_by_team.get(t)
        ko = kick_wk.get(t)
        if not t or not g or g not in covered or not ko or ko <= now:
            continue
        del entry[book]
        entry['asOf'] = TODAY
        dropped.append(name)
        if not any(k != 'asOf' for k in entry):
            del wkd[name]
    return dropped


# ---------------------------------------------------------------------------
# Phase E — FanDuel (plain requests; added 2026-09-08)
# ---------------------------------------------------------------------------
# FanDuel's sportsbook front end reads sbapi.nj.sportsbook.fanduel.com with a
# public app key (_ak) embedded in its JS — no login, no geo gate for odds
# display, no bot wall as of Sep 2026. One content-managed-page call carries
# the season props (REGULAR_SEASON_PROPS_* markets) and the week's events;
# one event-page call per (game, tab) carries the player props. Market types
# end in _HIGH/_MEDIUM/_LOW (FanDuel's player-prominence tiers, NOT alt
# lines — alts are the _ALT_ types and are skipped).

FD_AK = 'FhMFpcPWXMeyZxOx'
FD_BASE = 'https://sbapi.nj.sportsbook.fanduel.com/api'
FD_COMMON = ('betexRegion=GBR&capiJurisdiction=intl&currencyCode=GBP&exchangeLocale=en_GB'
             '&includePrices=true&language=en&regionCode=NAMERICA&timezone=America%2FNew_York')
FD_HEADERS = {'User-Agent': UA, 'Accept': 'application/json',
              'Referer': 'https://sportsbook.fanduel.com/'}
FD_WEEKLY_TABS = ('passing-props', 'rushing-props', 'receiving-props', 'td-scorer-props')
FD_WEEKLY_TYPES = {'PASSING_YARDS': 'py', 'PASSING_TOUCHDOWNS': 'ptd', 'INTERCEPTIONS': 'int',
                   'RUSHING_YARDS': 'ry', 'RECEIVING_YARDS': 'rcy', 'RECEPTIONS': 'rec'}
FD_SEASON_STATS = {
    'passing yards': 'py', 'passing tds': 'ptd', 'passing touchdowns': 'ptd',
    'interceptions': 'int', 'interceptions thrown': 'int',
    'rushing yards': 'ry', 'rushing tds': 'rtd', 'rushing touchdowns': 'rtd',
    'receiving yards': 'rcy', 'receiving tds': 'rctd', 'receiving touchdowns': 'rctd',
    'receptions': 'rec',
}
_FD_PAGE = None


def _fd_get(url):
    r = requests.get(url, headers=FD_HEADERS, timeout=60)
    r.raise_for_status()
    return r.json()


def _fd_nfl_page():
    global _FD_PAGE
    if _FD_PAGE is None:
        _FD_PAGE = _fd_get(f'{FD_BASE}/content-managed-page?{FD_COMMON}&_ak={FD_AK}'
                           '&page=CUSTOM&customPageId=nfl')
    return _FD_PAGE


def _fd_american(runner):
    try:
        return int(((runner.get('winRunnerOdds') or {}).get('americanDisplayOdds') or {})
                   .get('americanOdds'))
    except (TypeError, ValueError):
        return None


def _matchup_from_name(name):
    """'New England Patriots @ Seattle Seahawks' -> ('NE', 'SEA') or None."""
    m = re.match(r'^\s*(.+?)\s*@\s*(.+?)\s*$', name or '')
    if not m:
        return None
    away, home = TEAM_ABBR.get(m.group(1).strip()), TEAM_ABBR.get(m.group(2).strip())
    return (away, home) if away and home else None


def _parse_iso(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def pull_fd_season():
    """{player: {stat: line}} from FanDuel's regular-season player props."""
    page = _fd_nfl_page()
    out = {}
    for m in (page.get('attachments') or {}).get('markets', {}).values():
        if not (m.get('marketType') or '').startswith('REGULAR_SEASON_PROPS'):
            continue
        mm = re.match(r'^(.+?) Regular Season (.+?) 20\d\d-\d\d$', m.get('marketName') or '')
        if not mm:
            continue
        stat = FD_SEASON_STATS.get(mm.group(2).strip().lower())
        if not stat:
            continue
        for r in m.get('runners', []):
            mo = re.search(r'\bOver (\d+(?:\.\d+)?)$', r.get('runnerName') or '')
            if mo:
                out.setdefault(mm.group(1).strip(), {})[stat] = float(mo.group(1))
                break
    print(f'  FanDuel: {sum(len(v) for v in out.values())} season lines across {len(out)} players')
    return out


def update_fanduel_props(src):
    print('Phase E: FanDuel season player props (requests)...')
    lookup = load_d_names()
    try:
        pulled = pull_fd_season()
    except Exception as e:
        print(f'  !! FanDuel pull failed ({e}) — seasonProps FD untouched')
        return src, 0
    if len(pulled) < 20:
        print(f'  !! only {len(pulled)} players pulled — refusing to rewrite FD props')
        return src, 0
    canon = canonize(pulled, lookup, 'FD', drop_unmatched=True)
    return merge_props_book(src, 'FD', canon)


def pull_fd_weekly(week_by_matchup):
    """{wk: {player: {stat: line}}} from FanDuel's per-game prop tabs."""
    page = _fd_nfl_page()
    # FanDuel's NFL page also lists standalone games weeks out (TNF, holiday
    # slates); only the nearest week is worth 4 requests per game.
    slate = []
    for e in (page.get('attachments') or {}).get('events', {}).values():
        mu = _matchup_from_name(e.get('name'))
        if not mu:
            continue
        wk = _validated_week(week_by_matchup.get(mu), _parse_iso(e.get('openDate')))
        if wk is not None:
            slate.append((wk, mu, e))
    cur = min((wk for wk, _, _ in slate), default=None)
    out = {}
    n = games = 0
    for wk, mu, e in slate:
        if wk != cur:
            continue
        games += 1
        wkd = out.setdefault(wk, {})
        for tab in FD_WEEKLY_TABS:
            try:
                body = _fd_get(f'{FD_BASE}/event-page?{FD_COMMON}&_ak={FD_AK}'
                               f'&eventId={e["eventId"]}&tab={tab}')
            except Exception as ex:
                print(f'    FanDuel {mu[0]}@{mu[1]} {tab}: {ex}')
                continue
            for m in (body.get('attachments') or {}).get('markets', {}).values():
                mt = m.get('marketType') or ''
                if mt == 'ANY_TIME_TOUCHDOWN_SCORER':
                    for r in m.get('runners', []):
                        odds = _fd_american(r)
                        player = (r.get('runnerName') or '').strip()
                        if player and odds is not None and 'atd' not in wkd.get(player, {}):
                            wkd.setdefault(player, {})['atd'] = odds
                            n += 1
                    continue
                t = re.match(r'^PLAYER_X_(PASSING_YARDS|PASSING_TOUCHDOWNS|INTERCEPTIONS|'
                             r'RUSHING_YARDS|RECEIVING_YARDS|RECEPTIONS)_(HIGH|MEDIUM|LOW)$', mt)
                if not t:
                    continue   # _ALT_ ladders, milestones, specials
                stat = FD_WEEKLY_TYPES[t.group(1)]
                player = (m.get('marketName') or '').split(' - ')[0].strip()
                for r in m.get('runners', []):
                    if (r.get('runnerName') or '').endswith(' Over') and r.get('handicap') is not None:
                        if player and stat not in wkd.get(player, {}):
                            wkd.setdefault(player, {})[stat] = float(r['handicap'])
                            n += 1
                        break
            time.sleep(0.4)
    print(f'  FanDuel weekly: {n} lines, weeks {sorted(out)}, '
          f'{sum(len(v) for v in out.values())} player-weeks ({games} games)')
    return out


# ---------------------------------------------------------------------------
# Phase F — BetMGM (plain requests; added 2026-09-08)
# ---------------------------------------------------------------------------
# Entain's CDS API (www.nj.betmgm.com/cds-api) answers plain requests once
# the site's access id is supplied. The id is a site constant captured from
# the app's own XHRs; if BetMGM ever rotates it ("Access id is invalid"), the
# script re-captures it by loading the NFL page in Chrome and reading the
# performance log. NFL = sportIds 11 / regionIds 9 / competitionIds 35.
# Season props live in a separate 'Regular season stats' fixture; per-game
# player props are optionMarkets on each PairGame fixture-view. Rushing
# yards are posted only as 25+/50+ ladders (no main line) — skipped.

MGM_ACCESS_ID = 'ZTllNjllODUtOWQwNS00YmU4LWE4NTEtZGZjOTkzMGM5OWU4'
MGM_BASE = 'https://www.nj.betmgm.com/cds-api/bettingoffer'
MGM_COMMON = 'lang=en-us&country=US&userCountry=US&subdivision=US-New%20Jersey'
MGM_HEADERS = {'User-Agent': UA, 'Accept': 'application/json',
               'Referer': 'https://www.nj.betmgm.com/en/sports'}
MGM_NFL_PAGE = 'https://sports.nj.betmgm.com/en/sports/football-11/betting/usa-9/nfl-35'
MGM_HAPPENING = {'PassingYards': 'py', 'TouchdownPass': 'ptd', 'InterceptionThrown': 'int',
                 'RushingYards': 'ry', 'ReceivingYards': 'rcy', 'Reception': 'rec',
                 'KickingPoint': 'kpts', 'FieldGoal': 'fgm'}
MGM_SEASON_STATS = {
    'passing yards': 'py', 'passing touchdowns': 'ptd', 'interceptions': 'int',
    'interceptions thrown': 'int', 'rushing yards': 'ry', 'rushing touchdowns': 'rtd',
    'receiving yards': 'rcy', 'receiving touchdowns': 'rctd', 'receptions': 'rec',
}
_MGM_AID = MGM_ACCESS_ID
_MGM_FIXTURES = None


def _mgm_capture_access_id():
    """Load the NFL page in Chrome and read the access id off the app's own
    cds-api requests (CDP performance log). Returns None on failure."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            path = ChromeDriverManager().install()
        except Exception:
            path = None
        opts = Options()
        opts.add_argument('--disable-blink-features=AutomationControlled')
        opts.add_argument('--no-sandbox')
        opts.add_argument('--window-size=1400,900')
        opts.add_experimental_option('excludeSwitches', ['enable-automation'])
        opts.add_experimental_option('useAutomationExtension', False)
        opts.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
        drv = webdriver.Chrome(service=Service(path) if path else Service(), options=opts)
        try:
            drv.set_page_load_timeout(60)
            drv.get(MGM_NFL_PAGE)
            time.sleep(15)
            for entry in drv.get_log('performance'):
                try:
                    msg = json.loads(entry['message'])['message']
                except (KeyError, ValueError):
                    continue
                if msg.get('method') != 'Network.requestWillBeSent':
                    continue
                mm = re.search(r'x-bwin-accessid=([A-Za-z0-9=_-]+)',
                               msg['params']['request'].get('url', ''))
                if mm:
                    return mm.group(1)
        finally:
            drv.quit()
    except Exception as e:
        print(f'  BetMGM access-id capture failed ({e})')
    return None


def _mgm_get(path, params):
    global _MGM_AID
    for attempt in (1, 2):
        url = f'{MGM_BASE}/{path}?x-bwin-accessid={_MGM_AID}&{MGM_COMMON}&{params}'
        r = requests.get(url, headers=MGM_HEADERS, timeout=60)
        if r.status_code == 400 and 'access id' in r.text.lower() and attempt == 1:
            print('  BetMGM: access id rejected — re-capturing from the site (Chrome)')
            new = _mgm_capture_access_id()
            if new and new != _MGM_AID:
                print(f'  BetMGM: new access id {new[:8]}… (update MGM_ACCESS_ID in the script)')
                _MGM_AID = new
                continue
        r.raise_for_status()
        return r.json()


def _mgm_fixtures():
    global _MGM_FIXTURES
    if _MGM_FIXTURES is None:
        d = _mgm_get('fixtures', 'fixtureTypes=Standard&state=Latest&offerMapping=Filtered'
                     '&offerCategories=Gridable&fixtureCategories=Gridable,NonGridable,Other'
                     '&sportIds=11&regionIds=9&competitionIds=35&skip=0&take=100&sortBy=Tags')
        _MGM_FIXTURES = d.get('fixtures') or []
    return _MGM_FIXTURES


def _mgm_fixture_view(fid):
    d = _mgm_get('fixture-view', f'offerMapping=All&scoreboardMode=Full&fixtureIds={fid}'
                 '&state=Latest&useRegionalisedConfiguration=true&includeRelatedFixtures=false'
                 '&statisticsModes=None')
    return d.get('fixture') or d


def _mgm_name(o):
    n = o.get('name')
    return (n.get('value') if isinstance(n, dict) else n) or ''


def _mgm_params(g):
    return {p.get('key'): p.get('value') for p in (g.get('parameters') or []) if p.get('key')}


def _mgm_over_line(opts):
    """Main O/U line from an options/results list: needs BOTH an 'Over X' and
    an 'Under X' (milestone ladders are Yes-only)."""
    over = under = None
    for o in opts or []:
        nm = _mgm_name(o)
        mo = re.match(r'^Over (\d+(?:\.\d+)?)$', nm)
        mu = re.match(r'^Under (\d+(?:\.\d+)?)$', nm)
        if mo:
            over = float(mo.group(1))
        elif mu:
            under = float(mu.group(1))
    return over if (over is not None and under is not None) else None


def pull_mgm_season():
    """{player: {stat: line}} from BetMGM's 'Regular season stats' fixture."""
    fx = [f for f in _mgm_fixtures() if 'regular season stats' in _mgm_name(f).lower()]
    if not fx:
        raise RuntimeError('no "Regular season stats" fixture in the NFL list')
    view = _mgm_fixture_view(fx[0]['id'])
    out = {}
    for g in (view.get('games') or []) + (view.get('optionMarkets') or []):
        mm = re.match(r'^(.+?) \([A-Z]{2,3}\): Regular season (.+?)$', _mgm_name(g))
        if not mm:
            continue
        stat = MGM_SEASON_STATS.get(mm.group(2).strip().lower())
        if not stat:
            continue
        line = _mgm_over_line(g.get('results') or g.get('options'))
        if line is not None:
            out.setdefault(mm.group(1).strip(), {})[stat] = line
    print(f'  BetMGM: {sum(len(v) for v in out.values())} season lines across {len(out)} players')
    return out


def update_betmgm_props(src):
    print('Phase F: BetMGM season player props (requests)...')
    lookup = load_d_names()
    try:
        pulled = pull_mgm_season()
    except Exception as e:
        print(f'  !! BetMGM pull failed ({e}) — seasonProps MGM untouched')
        return src, 0
    if len(pulled) < 20:
        print(f'  !! only {len(pulled)} players pulled — refusing to rewrite MGM props')
        return src, 0
    canon = canonize(pulled, lookup, 'MGM', drop_unmatched=True)
    return merge_props_book(src, 'MGM', canon)


def pull_mgm_weekly(week_by_matchup):
    """{wk: {player: {stat: line}}} from each NFL game's fixture-view."""
    out = {}
    n = games = 0
    for f in _mgm_fixtures():
        mu = _matchup_from_name(_mgm_name(f))
        if not mu or f.get('fixtureType') not in (None, 'PairGame'):
            continue
        wk = _validated_week(week_by_matchup.get(mu), _parse_iso(f.get('startDate')))
        if wk is None:
            continue
        try:
            view = _mgm_fixture_view(f['id'])
        except Exception as ex:
            print(f'    BetMGM {mu[0]}@{mu[1]}: {ex}')
            continue
        games += 1
        wkd = out.setdefault(wk, {})
        for g in view.get('optionMarkets') or []:
            p = _mgm_params(g)
            period = p.get('Period')
            if period and period not in ('FullTime', 'RegularTime', 'Regular Time'):
                continue
            name = _mgm_name(g)
            if p.get('Happening') == 'Touchdown':
                mm = re.match(r'^(.+?) to score 1\+ TDs?$', name)
                if not mm:
                    continue
                for o in g.get('options') or []:
                    if _mgm_name(o).lower() == 'yes':
                        odds = (o.get('price') or {}).get('americanOdds')
                        if odds is not None and 'atd' not in wkd.get(mm.group(1).strip(), {}):
                            wkd.setdefault(mm.group(1).strip(), {})['atd'] = int(odds)
                            n += 1
                continue
            stat = MGM_HAPPENING.get(p.get('Happening'))
            if not stat:
                continue
            line = _mgm_over_line(g.get('options'))
            if line is None:
                continue   # 25+/50+ ladders etc.
            mm = re.match(r'^(.+?)(?: - |: )(.+)$', name)
            if not mm:
                continue
            player = mm.group(1).strip()
            if stat not in wkd.get(player, {}):
                wkd.setdefault(player, {})[stat] = line
                n += 1
        time.sleep(0.5)
    print(f'  BetMGM weekly: {n} lines, weeks {sorted(out)}, '
          f'{sum(len(v) for v in out.values())} player-weeks ({games} games)')
    return out


def update_weekly_props(src):
    print('Phase D: weekly player props (Underdog + PrizePicks)...')
    lookup = load_d_names()
    week_by_matchup = {}
    for key in parse_game_totals(src):
        m = re.match(r'W(\d+)_([A-Z]+)_([A-Z]+)', key)
        if m:
            week_by_matchup[(m.group(2), m.group(3))] = int(m.group(1))

    pulls = []   # (book, {wk: {name: stats}})
    try:
        pulls.append(('UD', pull_ud_weekly(week_by_matchup)))
    except Exception as e:
        print(f'  !! Underdog weekly failed ({e}) — UD untouched')
    try:
        pulls.append(('PP', pull_pp_weekly()))
    except Exception as e:
        print(f'  !! PrizePicks weekly failed ({e}) — PP untouched')
    try:
        pulls.append(('FD', pull_fd_weekly(week_by_matchup)))
    except Exception as e:
        print(f'  !! FanDuel weekly failed ({e}) — FD untouched')
    try:
        pulls.append(('MGM', pull_mgm_weekly(week_by_matchup)))
    except Exception as e:
        print(f'  !! BetMGM weekly failed ({e}) — MGM untouched')
    dk = {}
    try:
        dk = pull_dk_weekly_atd(week_by_matchup)
    except Exception as e:
        print(f'  !! DK Anytime TD failed ({e}) — DK atd untouched')
    try:
        # merge the O/U stat lines into the same DK dict — update_weekly_props
        # replaces each book's entry wholesale, so DK must arrive as ONE pull
        for wk, players_wk in pull_dk_weekly_stats(week_by_matchup).items():
            for name, stats in players_wk.items():
                dk.setdefault(wk, {}).setdefault(name, {}).update(stats)
    except Exception as e:
        print(f'  !! DK weekly O/U failed ({e}) — DK stat lines untouched')
    if dk:
        pulls.append(('DK', dk))

    weeks = parse_weekly_block(src)
    changed = 0
    teams = load_d_teams()
    kicks = load_kickoffs()
    games_by_team = {}   # (wk, abbr) -> game key
    for (away, home), gwk in week_by_matchup.items():
        games_by_team[(gwk, away)] = games_by_team[(gwk, home)] = f'W{gwk}_{away}_{home}'
    for book, by_week in pulls:
        for wk, pulled in by_week.items():
            if len(pulled) < 10:
                print(f'  !! {book} W{wk}: only {len(pulled)} players — skipped')
                continue
            canon = canonize(pulled, lookup, f'{book} W{wk}', drop_unmatched=True)
            wkd = weeks.setdefault(str(wk), {})
            for name, stats in canon.items():
                raw = ', '.join(f'{k}: {v}' for k, v in
                                sorted(stats.items(), key=lambda kv: STAT_ORDER.index(kv[0])))
                entry = wkd.setdefault(name, {'asOf': TODAY})
                if entry.get(book, '') != raw:
                    entry[book] = raw
                    entry['asOf'] = TODAY
                    changed += 1
            if kicks:
                gbt = {abbr: g for (gwk, abbr), g in games_by_team.items() if gwk == wk}
                dropped = prune_off_board(wkd, wk, book, canon, teams, kicks, gbt)
                if dropped:
                    changed += len(dropped)
                    shown = ', '.join(dropped[:6]) + (' …' if len(dropped) > 6 else '')
                    print(f'  {book} W{wk}: dropped {len(dropped)} off-board pre-kickoff ({shown})')
    if not changed:
        print('  weeklyProps: no changes')
        return src, 0

    parts = ['const _WEEKLY_PROPS_2026 = {']
    for wk in sorted(weeks, key=int):
        parts.append(f'  // ===== Week {wk} =====')
        parts.append(f"  '{wk}': {{")
        entries = list(weeks[wk].items())
        for i, (name, books) in enumerate(entries):
            q = name.replace("'", "\\'")
            comma = ',' if i < len(entries) - 1 else ''
            parts.append(f"    '{q}': {{ {_emit_entry(books)} }}{comma}")
        parts.append('  },')
    parts.append('};')
    new_src = replace_block(src, '_WEEKLY_PROPS_2026', '\n'.join(parts))
    n_players = sum(len(v) for v in weeks.values())
    print(f'  weeklyProps: {len(weeks)} week(s), {n_players} player-weeks, {changed} book-entries changed')
    return new_src, changed


# ---------------------------------------------------------------------------
# JSON mirror — served off the live site so the Chrome extensions can refresh
# their bundled Vegas snapshots (playoff_sos_2026.js overlay) without a
# re-export + reload. Written on every run, even when the JS file is unchanged.
# ---------------------------------------------------------------------------

JSON_FILE = os.path.join(ROOT, 'data', 'betting_lines_2026.json')


def _raw_stats_to_dict(raw):
    # -? for american odds values (atd: -150)
    return {k: float(v) for k, v in re.findall(r'(\w+):\s*(-?[\d.]+)', raw or '')}


def ensure_season_seen(src):
    """Create _SEASON_SEEN_2026 on first run (seeded from history/asOf)."""
    if parse_season_seen(src) is None:
        print('  seasonSeen: seeding per-book/stat last-seen dates')
        src = emit_season_seen(src, _seed_season_seen(src))
    return src


def emit_json_export(src):
    season = {}
    block = extract_block(src, '_SEASON_PROPS_2026')
    for m in re.finditer(r"^\s*(?:'((?:[^'\\]|\\.)*)'|\"([^\"]*)\"):\s*\{(.*)\},?\s*$",
                         block, re.M):
        name = (m.group(1) or m.group(2)).replace("\\'", "'")
        books = parse_props_entry(m.group(3))
        entry = {b: _raw_stats_to_dict(books[b]) for b in BOOK_ORDER if books.get(b)}
        entry['asOf'] = books.get('asOf')
        season[name] = entry
    weekly = {}
    for wk, players in parse_weekly_block(src).items():
        weekly[wk] = {}
        for name, books in players.items():
            entry = {b: _raw_stats_to_dict(books[b]) for b in BOOK_ORDER if books.get(b)}
            entry['asOf'] = books.get('asOf')
            weekly[wk][name] = entry
    out = {
        'generatedAt': TODAY,
        'gameTotals': parse_game_totals(src),
        'seasonProps': season,
        'seasonSeen': parse_season_seen(src) or {},
        'weeklyProps': weekly,
    }
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(out, f, separators=(',', ':'))
    print(f'Wrote data/betting_lines_2026.json ({len(out["gameTotals"])} games, '
          f'{len(season)} season players, '
          f'{sum(len(v) for v in weekly.values())} weekly player-weeks)')


# ---------------------------------------------------------------------------
# Surgical file editing + version bump
# ---------------------------------------------------------------------------

def _block_span(src, const_name):
    start = src.index(f'const {const_name} = {{')
    end = src.index('\n};', start) + len('\n};')
    return start, end


def extract_block(src, const_name):
    s, e = _block_span(src, const_name)
    return src[s:e]


def replace_block(src, const_name, new_block):
    s, e = _block_span(src, const_name)
    return src[:s] + new_block + src[e:]


def parse_game_totals(src):
    block = extract_block(src, '_GAME_TOTALS_2026')
    out = {}
    for m in re.finditer(r"'(W\d+_[A-Z]+_[A-Z]+)':\s*\{\s*total:\s*([\d.]+|null),"
                         r"\s*spread:\s*([+\-\d.]+|null),\s*asOf:\s*'([^']+)',"
                         r"\s*source:\s*'([^']+)'", block):
        out[m.group(1)] = {
            'total': None if m.group(2) == 'null' else float(m.group(2)),
            'spread': None if m.group(3) == 'null' else float(m.group(3)),
            'asOf': m.group(4), 'source': m.group(5),
        }
    return out


def bump_version():
    html = open(INDEX_FILE, encoding='utf-8').read()
    pat = r'(data/betting_lines_2026\.js\?v=)([\w.-]+)'
    m = re.search(pat, html)
    if not m:
        print('  !! script tag not found in index.html — bump ?v= manually')
        return
    old = m.group(2)
    if old.startswith(TODAY):
        suffix = old[len(TODAY):]
        new = TODAY + ('b' if not suffix else chr(ord(suffix[-1]) + 1))
    else:
        new = TODAY
    html = re.sub(pat, r'\g<1>' + new, html)
    open(INDEX_FILE, 'w', encoding='utf-8').write(html)
    print(f'  index.html: ?v={old} -> ?v={new}')


# ---------------------------------------------------------------------------
# Line-movement history (added 2026-09-08)
# ---------------------------------------------------------------------------
# data/lines_history_2026.json — every (week, player, book, stat) keeps a list
# of [stamp, value] points appended ONLY when the value changes, so the site
# can show "opened 41.5 → now 55.5" and the biggest movers. Seeded from the
# git history of betting_lines_2026.json (scripts/backfill_lines_history.py),
# then appended by every pull. Delistings are not recorded (the current file
# no longer carries the row, so nothing renders anyway). Fetched lazily by the
# player card with an hour-stamped ?d= param (never ?v= — sw.js would pin it).

HISTORY_FILE = os.path.join(ROOT, 'data', 'lines_history_2026.json')


def _hist_stamp(dt=None):
    dt = dt or datetime.datetime.now(datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')


def load_lines_history():
    try:
        return json.load(open(HISTORY_FILE, encoding='utf-8'))
    except (OSError, ValueError):
        return {'updated': None, 'weeks': {}, 'season': {}}


def record_lines_into(hist, data, stamp, weeks_only=None):
    """Append changed points from one betting_lines JSON payload. Returns the
    number of points added. `weeks_only` restricts weekly recording (backfill
    skips weeks the current file no longer carries)."""
    added = 0

    def rec(node, book, stat, val):
        nonlocal added
        if not isinstance(val, (int, float)):
            return
        arr = node.setdefault(book, {}).setdefault(stat, [])
        if not arr or arr[-1][1] != val:
            arr.append([stamp, val])
            added += 1

    for wk, players in (data.get('weeklyProps') or {}).items():
        if weeks_only is not None and str(wk) not in weeks_only:
            continue
        for name, books in (players or {}).items():
            node = hist.setdefault('weeks', {}).setdefault(str(wk), {}).setdefault(name, {})
            for book, stats in (books or {}).items():
                if book == 'asOf' or not isinstance(stats, dict):
                    continue
                for stat, val in stats.items():
                    rec(node, book, stat, val)
    for name, books in (data.get('seasonProps') or {}).items():
        node = hist.setdefault('season', {}).setdefault(name, {})
        for book, stats in (books or {}).items():
            if book == 'asOf' or not isinstance(stats, dict):
                continue
            for stat, val in stats.items():
                rec(node, book, stat, val)
    if added:
        hist['updated'] = stamp
    return added


def save_lines_history(hist):
    body = json.dumps(hist, separators=(',', ':'), ensure_ascii=False)
    open(HISTORY_FILE, 'w', encoding='utf-8').write(body)
    return len(body.encode('utf-8'))


def update_lines_history():
    try:
        data = json.load(open(JSON_FILE, encoding='utf-8'))
    except (OSError, ValueError) as e:
        print(f'  lines history: cannot read JSON export ({e}) — skipped')
        return 0
    hist = load_lines_history()
    added = record_lines_into(hist, data, _hist_stamp())
    if added:
        size = save_lines_history(hist)
        print(f'  lines history: +{added} points -> {os.path.relpath(HISTORY_FILE, ROOT)} ({size // 1024} KB)')
    else:
        print('  lines history: no line moved')
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game-lines', action='store_true', help='ESPN spreads/totals only')
    ap.add_argument('--season-props', action='store_true', help='DK season props only')
    ap.add_argument('--underdog', action='store_true', help='Underdog season props only')
    ap.add_argument('--weekly-props', action='store_true',
                    help='UD+PP+DK+FD+MGM weekly props only')
    ap.add_argument('--fanduel', action='store_true', help='FanDuel season props only')
    ap.add_argument('--betmgm', action='store_true', help='BetMGM season props only')
    args = ap.parse_args()
    all_phases = not (args.game_lines or args.season_props or args.underdog
                      or args.weekly_props or args.fanduel or args.betmgm)
    do_fd = args.fanduel or all_phases
    do_mgm = args.betmgm or all_phases
    do_games = args.game_lines or all_phases
    do_props = args.season_props or all_phases
    do_ud = args.underdog or all_phases
    do_weekly = args.weekly_props or all_phases

    src = open(DATA_FILE, encoding='utf-8').read()
    orig = src
    total_changed = 0
    src = ensure_season_seen(src)
    if do_games:
        src, n = update_game_lines(src)
        total_changed += n
    if do_props:
        try:
            src, n = update_season_props(src)
            total_changed += n
        except Exception as e:
            print(f'  !! DK season props failed ({e}) — seasonProps DK untouched')
    if do_ud:
        src, n = update_underdog_props(src)
        total_changed += n
    if do_fd:
        src, n = update_fanduel_props(src)
        total_changed += n
    if do_mgm:
        src, n = update_betmgm_props(src)
        total_changed += n
    if do_weekly:
        src, n = update_weekly_props(src)
        total_changed += n
        if _DK_SEASON_REC:
            print(f'  DK posted a season RECEPTIONS market '
                  f'({len(_DK_SEASON_REC)} players) — merging into seasonProps')
            src, n = apply_dk_season_receptions(src)
            total_changed += n

    # Season-receptions watch banner: fires the first run any book's season
    # `rec` lines land (DK via the check above, UD via Phase C). The daily
    # wrapper greps for this to flag the commit for Jack.
    def _n_season_rec(s):
        return len(re.findall(r'\brec:', extract_block(s, '_SEASON_PROPS_2026')))
    if _n_season_rec(src) and not _n_season_rec(orig):
        print(f'*** SEASON RECEPTIONS PROP POSTED ({_n_season_rec(src)} lines) — '
              f'PPR/Half/STD projections now split for pass-catchers')

    emit_json_export(src)
    update_lines_history()
    if src == orig:
        print('No JS changes — betting_lines_2026.js untouched, no version bump.')
        return
    open(DATA_FILE, 'w', encoding='utf-8').write(src)
    print(f'Wrote {os.path.relpath(DATA_FILE, ROOT)} ({total_changed} lines new/changed)')
    bump_version()


if __name__ == '__main__':
    main()
