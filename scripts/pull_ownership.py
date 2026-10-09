"""% rostered (ESPN + Sleeper + Yahoo) -> data/ownership_2026.js.

Feeds the player card's ROSTERED row (bottom of the FANTASY view). Jack asked
for it 2026-10-09 while building the @myfantasyfootball.co TikTok waiver bot,
whose tiktok_bot/src/ownership.js reads the same ESPN + Sleeper endpoints.

Sources (all keyless):
  ESPN:    lm-api-reads kona_player_info on leaguedefaults/3, sorted by
           percentOwned, QB/RB/WR/TE/DST/K slots, top 1500 ->
           ownership.percentOwned / percentChange. ESPN 403s browser-looking
           UAs from scripts — keep the curl UA.
  Sleeper: api.sleeper.app/players/nfl/research/regular/{season}/{week} ->
           {player_id: {owned, started}}. Players under ~1% rostered are
           simply missing, so a listed-elsewhere player absent here = 0.
           Tries the current week, then the previous one if it's still empty.
  Yahoo:   pub-api-ro public league (470.l.public, same host Phase D reads
           O-Rank from) with the /percent_owned subresource, paged by actual
           rank (sort=AR). No OAuth needed. A row with no `value` = 0%.
           (The site's yahooProxy Cloud Function only allowlists league
           routes, so it isn't used here.)

Names are resolved to d.js-canonical spelling at pull time (same final_key
pattern as pull_site_projections.py) so app.js looks up OWNERSHIP_2026.players[d.n].
Defenses are matched by mascot ("Texans") -> "Houston Texans D/ST".

Output: window.OWNERSHIP_2026 = {updated, season, sleeperWeek, yahooWeek,
  players: {"Name": {espn, espnChg, sleeper, yahoo, yahooChg}}}
  (percent, 1dp; a key is omitted when that source has no read on the player)

Any single source failing is a warning (card shows a dash for it); all three
failing aborts without writing. Usage:
  python scripts/pull_ownership.py [--dry]
Runs as Phase P of the 9am daily job.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'ownership_2026.js')
STATE_URL = 'https://api.sleeper.app/v1/state/nfl'
UA = {'User-Agent': 'curl/8.4.0', 'Accept': 'application/json'}

ESPN_URL = ('https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}'
            '/segments/0/leaguedefaults/3?view=kona_player_info')
ESPN_FILTER = {'players': {'limit': 1500,
                           'sortPercOwned': {'sortPriority': 1, 'sortAsc': False},
                           'filterSlotIds': {'value': [0, 2, 4, 6, 16, 17]}}}
ESPN_POS = {1: 'QB', 2: 'RB', 3: 'WR', 4: 'TE', 5: 'K', 16: 'DST'}

SLEEPER_RESEARCH = 'https://api.sleeper.app/players/nfl/research/regular/{season}/{week}'
SLEEPER_PLAYERS = 'https://api.sleeper.app/v1/players/nfl'
SLEEPER_POS = {'QB', 'RB', 'WR', 'TE', 'K', 'DEF'}

YAHOO_URL = ('https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/league/'
             '470.l.public/players;position=ALL;sort=AR;start={start};count={count}'
             '/percent_owned?format=json_f')
YAHOO_PAGE = 400
YAHOO_MAX = 2400
YAHOO_POS = {'QB', 'RB', 'WR', 'TE', 'K', 'DEF'}

# feed name -> d.js canonical, for spellings normalization can't bridge.
NAME_ALIASES = {
    'Kenny Gainwell': 'Kenneth Gainwell',
    'Joshua Palmer': 'Josh Palmer',
}


def r1(v):
    return round(float(v), 1)


def pull_espn(season):
    r = requests.get(ESPN_URL.format(season=season),
                     headers={**UA, 'X-Fantasy-Filter': json.dumps(ESPN_FILTER)}, timeout=120)
    r.raise_for_status()
    out = {}
    for x in r.json().get('players', []):
        p = x.get('player') or {}
        pos = ESPN_POS.get(p.get('defaultPositionId'))
        own = p.get('ownership')
        name = (p.get('fullName') or '').strip()
        if not pos or not own or not name:
            continue
        if pos == 'DST':
            name = 'DST:' + re.sub(r'\s*D/ST$', '', name).split(' ')[-1]
        if name in out:  # sorted by % owned — first hit is the relevant one
            continue
        out[name] = {'pct': r1(own.get('percentOwned') or 0),
                     'chg': r1(own.get('percentChange') or 0)}
    return out


def pull_sleeper(season, week):
    players = requests.get(SLEEPER_PLAYERS, timeout=120).json()
    res, used = {}, None
    for w in (week, week - 1):
        if w < 1:
            continue
        r = requests.get(SLEEPER_RESEARCH.format(season=season, week=w), timeout=60)
        r.raise_for_status()
        res = r.json() or {}
        if len(res) > 100:
            used = w
            break
    out = {}
    for pid, v in res.items():
        p = players.get(pid)
        if not p or not isinstance(v, dict) or v.get('owned') is None:
            continue
        if p.get('position') not in SLEEPER_POS:
            continue
        if p.get('position') == 'DEF':
            name = 'DST:' + (p.get('last_name') or '')
        else:
            name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        pct = r1(v['owned'])
        if name not in out or pct > out[name]['pct']:
            out[name] = {'pct': pct}
    return out, used


def pull_yahoo():
    out, week = {}, None
    for start in range(0, YAHOO_MAX, YAHOO_PAGE):
        r = requests.get(YAHOO_URL.format(start=start, count=YAHOO_PAGE),
                         headers={'User-Agent': 'Mozilla/5.0'}, timeout=60)
        r.raise_for_status()
        rows = r.json()['fantasy_content']['league'].get('players') or []
        for item in rows:
            pl = item.get('player') or {}
            pos = pl.get('primary_position') or ''
            name = ((pl.get('name') or {}).get('full') or '').strip()
            po = pl.get('percent_owned') or {}
            if pos not in YAHOO_POS or not name:
                continue
            if pos == 'DEF':
                name = 'DST:' + name.split(' ')[-1]
            week = week or po.get('week')
            if name in out:
                continue
            try:
                chg = float(po.get('delta') or 0)
            except ValueError:
                chg = 0.0
            out[name] = {'pct': r1(po.get('value') or 0), 'chg': r1(chg)}
        if len(rows) < YAHOO_PAGE:
            break
    return out, week


def _final_key_fn():
    sys.path.insert(0, ROOT)
    try:
        from inject_rankings import final_key
        return final_key
    except ImportError:
        # inject_rankings.py is a local (untracked) file in the main checkout;
        # worktree test runs fall back to the same normalization minus OVERRIDES.
        def final_key(n):
            s = (n or '').lower().strip()
            for suf in [' jr.', ' jr', ' sr.', ' sr', ' iii', ' ii', ' iv', ' v']:
                if s.endswith(suf):
                    s = s[: -len(suf)].strip()
            s = s.replace("'", '').replace('`', '').replace('’', '')
            s = s.replace('.', '').replace(',', '').replace('-', ' ')
            return re.sub(r'\s+', ' ', s).strip()
        return final_key


def resolve_to_djs(sources):
    """Re-key every source map to d.js-canonical names; drop names d.js
    doesn't carry. Returns {canon_name: {src_key: {pct[, chg]}}}."""
    final_key = _final_key_fn()
    dsrc = open(os.path.join(ROOT, 'data', 'd.js'), encoding='utf-8').read()
    names = re.findall(r'"n":"([^"]+)"', dsrc)
    exact = set(names)
    norm_idx, dst_idx = {}, {}
    for n in names:
        norm_idx.setdefault(final_key(n), n)
        if n.endswith(' D/ST'):
            dst_idx[n[:-5].split(' ')[-1].lower()] = n

    players = {}
    for key, src in sources.items():
        matched = 0
        for name, vals in src.items():
            if name.startswith('DST:'):
                canon = dst_idx.get(name[4:].lower())
            else:
                name = NAME_ALIASES.get(name, name)
                canon = name if name in exact else norm_idx.get(final_key(name))
            if canon is None:
                continue
            players.setdefault(canon, {})[key] = vals
            matched += 1
        print(f'  {key}: {matched}/{len(src)} resolved to d.js players')
    return players


def main():
    dry = '--dry' in sys.argv
    state = requests.get(STATE_URL, timeout=30).json()
    season = int(state.get('season') or 0)
    week = int(state.get('week') or state.get('display_week') or 1)
    if not season:
        sys.exit(f'!! bad state response: {state}')

    sources, meta = {}, {}
    for key, label, floor, fn in (
            ('es', 'ESPN', 500, lambda: (pull_espn(season), None)),
            ('sl', 'Sleeper', 200, lambda: pull_sleeper(season, week)),
            ('yh', 'Yahoo', 300, pull_yahoo)):
        try:
            src, wk = fn()
            if len(src) < floor:
                raise ValueError(f'only {len(src)} rows (<{floor})')
            sources[key] = src
            meta[key] = wk
            print(f'{len(src)} {label} ownership rows' + (f' (week {wk})' if wk else ''))
        except Exception as e:
            print(f'!! {label} pull failed ({e}) — card shows a dash for it this run')
    if not sources:
        sys.exit('!! every source failed — refusing to write')

    resolved = resolve_to_djs(sources)
    players = {}
    for name, srcs in resolved.items():
        row = {}
        if 'es' in srcs:
            row['espn'] = srcs['es']['pct']
            if srcs['es']['chg']:
                row['espnChg'] = srcs['es']['chg']
        # Sleeper drops players under ~1% from the research feed — anyone the
        # other sites list but Sleeper doesn't is effectively 0% there.
        if 'sl' in sources:
            row['sleeper'] = srcs['sl']['pct'] if 'sl' in srcs else 0
        if 'yh' in srcs:
            row['yahoo'] = srcs['yh']['pct']
            if srcs['yh']['chg']:
                row['yahooChg'] = srcs['yh']['chg']
        players[name] = row

    if dry:
        for n in list(players)[:10]:
            print(f'  {n}: {players[n]}')
        print(f'{len(players)} players')
        return

    payload = {
        'updated': datetime.now(timezone.utc).isoformat(),
        'season': season,
        'sleeperWeek': meta.get('sl'),
        'yahooWeek': meta.get('yh'),
        'players': players,
    }
    body = ('// Auto-generated by scripts/pull_ownership.py — do not hand-edit.\n'
            '// % rostered per site for the player-card ROSTERED row. Per player:\n'
            '// espn/espnChg (ESPN % rostered + 7-day change), sleeper, yahoo/yahooChg.\n'
            'window.OWNERSHIP_2026 = '
            + json.dumps(payload, separators=(',', ':'), ensure_ascii=False) + ';\n')
    old = open(OUT, encoding='utf-8').read() if os.path.exists(OUT) else ''
    open(OUT, 'w', encoding='utf-8', newline='\n').write(body)
    print(f'data/ownership_2026.js written ({len(body):,} bytes, '
          f'{len(players)} players, {"changed" if body != old else "no change"})')


if __name__ == '__main__':
    main()
