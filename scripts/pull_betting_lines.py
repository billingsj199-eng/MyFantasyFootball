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

SCOREBOARD = ('https://site.api.espn.com/apis/site/v2/sports/football/nfl/'
              'scoreboard?seasontype=2&week={wk}&dates=2026')
ODDS = ('https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/'
        'events/{eid}/competitions/{eid}/odds')

# ESPN abbreviation -> site convention (betting_lines keys)
TEAM_FIX = {'WSH': 'WAS', 'JAC': 'JAX', 'LA': 'LAR'}


def _fix(abbr):
    a = (abbr or '').upper()
    return TEAM_FIX.get(a, a)


def pull_game_lines():
    """Return {key: {'total': float|None, 'spread': float|None, 'source': str}}."""
    sess = requests.Session()
    sess.headers.update({'User-Agent': UA, 'Accept': 'application/json'})
    out = {}
    misses = []
    for wk in range(1, 19):
        try:
            sb = sess.get(SCOREBOARD.format(wk=wk), timeout=30).json()
        except Exception as e:
            print(f'  W{wk}: scoreboard failed ({e}), skipping week')
            continue
        events = sb.get('events', [])
        print(f'  W{wk}: {len(events)} games')
        for ev in events:
            eid = ev.get('id')
            comp = (ev.get('competitions') or [{}])[0]
            away = home = None
            for c in comp.get('competitors', []):
                abbr = _fix(((c.get('team') or {}).get('abbreviation')))
                if c.get('homeAway') == 'home':
                    home = abbr
                elif c.get('homeAway') == 'away':
                    away = abbr
            if not away or not home:
                continue
            key = f'W{wk}_{away}_{home}'
            total = spread = None
            source = 'DK'
            try:
                time.sleep(0.2)
                od = sess.get(ODDS.format(eid=eid), timeout=30).json()
                items = od.get('items', [])
                # prefer DraftKings, else first provider with numbers
                items.sort(key=lambda it: 0 if 'draftkings' in
                           str((it.get('provider') or {}).get('name', '')).lower() else 1)
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
            markets = {m['id']: m for m in body.get('markets', [])}
            count = 0
            for sel in body.get('selections', []):
                if sel.get('outcomeType') != 'Over':
                    continue
                m = markets.get(sel.get('marketId'))
                if not m:
                    continue
                # "NFL 2026/27 - Josh Allen Regular Season Passing Yards"
                name = m.get('name', '')
                pm = re.match(r'NFL \d{4}/\d{2}\s*-\s*(.+?)\s+(?:Regular Season|Rookie)', name)
                lm = re.search(r'Over\s+([\d,]+\.?\d*)', sel.get('label', ''))
                if not pm or not lm:
                    continue
                player = pm.group(1).strip()
                line = float(lm.group(1).replace(',', ''))
                players.setdefault(player, {})[stat] = line
                count += 1
            print(f'    {cat_name} / {sub_name} -> {stat}: {count} lines')
            time.sleep(1.0)
        return players
    finally:
        driver.quit()


BOOK_ORDER = ('DK', 'FD', 'MGM', 'UD', 'PP')
STAT_ORDER = ['py', 'ptd', 'int', 'ry', 'rtd', 'ra', 'rec', 'rcy', 'rctd', 'rrtd', 'atd']


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


def merge_props_book(src, book, canon):
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
    return replace_block(src, '_SEASON_PROPS_2026', new_block), changed


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

UD_URL = 'https://api.underdogfantasy.com/beta/v6/over_under_lines'

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
        r = requests.get(UD_URL, timeout=60,
                         headers={'User-Agent': UA, 'Accept': 'application/json'})
        r.raise_for_status()
        _UD_CACHE = r.json()
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
    'receptions': 'rec', 'rushing_rec_yds': None,  # combined yds: no clean key
}

PP_STAT_KEYS = {
    'Pass Yards': 'py', 'Pass TDs': 'ptd', 'INT': 'int',
    'Rush Yards': 'ry', 'Receiving Yards': 'rcy', 'Rush+Rec TDs': 'rrtd',
    'Receptions': 'rec',
}

# W1 games start Thu 2026-09-10; weeks roll over on Tuesdays.
SEASON_W1_TUESDAY = datetime.date(2026, 9, 8)


def _week_of(dt):
    wk = (dt.date() - SEASON_W1_TUESDAY).days // 7 + 1
    return wk if 1 <= wk <= 18 else None


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
        wk = None
        m = re.match(r'([A-Z]{2,4})\s*@\s*([A-Z]{2,4})', g.get('title') or '')
        if m:
            wk = week_by_matchup.get((m.group(1), m.group(2)))
        if wk is None and g.get('scheduled_at'):
            try:
                wk = _week_of(datetime.datetime.fromisoformat(
                    g['scheduled_at'].replace('Z', '+00:00')))
            except ValueError:
                pass
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
        # DK names the league-level subcategory "TD Scorer" (category "TD
        # Scorers"); the per-event markets inside are "Anytime TD Scorer".
        subs = [s for s in league.get('subcategories', [])
                if (s.get('name') or '').lower() in ('td scorer', 'anytime td scorer')
                or 'anytime td' in (s.get('name') or '').lower()]
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
            events = {}
            for ev in body.get('events', []):
                wk = None
                # Event names look like "NE Patriots @ SEA Seahawks" — the
                # abbreviation is the first token on each side of the '@'.
                nm = ev.get('name') or ''
                if '@' in nm:
                    away, _, home = nm.partition('@')
                    a = (away.strip().split() or [''])[0]
                    h = (home.strip().split() or [''])[0]
                    wk = week_by_matchup.get((a, h))
                if wk is None:
                    start = ev.get('startEventDate') or ev.get('startDate')
                    if start:
                        try:
                            # UTC → ET-ish before taking the date, else Monday
                            # night games (00:15 UTC Tue) land in the next week.
                            dt = datetime.datetime.fromisoformat(
                                str(start).replace('Z', '+00:00')).replace(tzinfo=None)
                            wk = _week_of(dt - datetime.timedelta(hours=5))
                        except ValueError:
                            pass
                if wk is not None:
                    events[ev.get('id')] = wk
            markets = {m['id']: m for m in body.get('markets', [])}
            for sel in body.get('selections', []):
                mkt = markets.get(sel.get('marketId'))
                if not mkt:
                    continue
                if 'anytime' not in (mkt.get('name') or '').lower():
                    continue  # subcategory may later carry First TD etc.
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
                     done(JSON.stringify({n: rows.length, rows}));
                  }).catch(e => done(JSON.stringify({error:String(e)})));
            """, page)
            r = json.loads(res)
            if r.get('error'):
                print(f'    page {page}: {r["error"]} — stopping')
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
            if r.get('n', 0) < 250:
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
        pulls.append(('DK', pull_dk_weekly_atd(week_by_matchup)))
    except Exception as e:
        print(f'  !! DK Anytime TD failed ({e}) — DK untouched')

    weeks = parse_weekly_block(src)
    changed = 0
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game-lines', action='store_true', help='ESPN spreads/totals only')
    ap.add_argument('--season-props', action='store_true', help='DK season props only')
    ap.add_argument('--underdog', action='store_true', help='Underdog season props only')
    ap.add_argument('--weekly-props', action='store_true', help='UD+PP weekly props only')
    args = ap.parse_args()
    all_phases = not (args.game_lines or args.season_props or args.underdog
                      or args.weekly_props)
    do_games = args.game_lines or all_phases
    do_props = args.season_props or all_phases
    do_ud = args.underdog or all_phases
    do_weekly = args.weekly_props or all_phases

    src = open(DATA_FILE, encoding='utf-8').read()
    orig = src
    total_changed = 0
    if do_games:
        src, n = update_game_lines(src)
        total_changed += n
    if do_props:
        src, n = update_season_props(src)
        total_changed += n
    if do_ud:
        src, n = update_underdog_props(src)
        total_changed += n
    if do_weekly:
        src, n = update_weekly_props(src)
        total_changed += n

    emit_json_export(src)
    if src == orig:
        print('No JS changes — betting_lines_2026.js untouched, no version bump.')
        return
    open(DATA_FILE, 'w', encoding='utf-8').write(src)
    print(f'Wrote {os.path.relpath(DATA_FILE, ROOT)} ({total_changed} lines new/changed)')
    bump_version()


if __name__ == '__main__':
    main()
