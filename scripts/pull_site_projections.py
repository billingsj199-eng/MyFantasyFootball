"""Per-site SEASON projections: Sleeper + ESPN + CBS -> data/site_projections.js.

Complements the Phase J weekly consensus feed: this one keeps each site's
full-season fantasy-point projection SEPARATE so the player card can show a
side-by-side "Season Projections" comparison (Books / Clay / Sleeper / ESPN /
CBS) — all scored per format and divided by 17 games in app.js, the same
season-value scale as Book PPG and Clay PPG.

Sources (all keyless):
  Sleeper: api.sleeper.com/projections/nfl/{season} (no week segment =
           season totals; same payload Phase K reads ADP from). pts_half_ppr /
           pts_ppr / pts_std verbatim.
  ESPN:    lm-api-reads kona_player_info on leaguedefaults/3. The
           statSourceId=1 / statSplitTypeId=0 / scoringPeriodId=0 entry is
           the season-total PPR projection; half/std derived off projected
           receptions (stat id 53) — same derivation as the weekly puller.
  CBS:     public season projection pages
           /fantasy/football/stats/{POS}/{season}/season/projections/ppr/
           (server-rendered TableBase, full names in CellPlayerName--long).
           NOT their "Fantasy Points" column — CBS scores passing TDs at 6
           (Josh Allen 419 vs Sleeper 361 / ESPN 370). Rescored from the
           stat components with the house formula (py/25 + ptd*4 + yds/10 +
           td*6 + rec*mult, INT/fumbles uncounted — mirrors app.js
           _clayPpgFor) so all three sites read on one scale. No kicker
           table exists, so CBS covers QB/RB/WR/TE only.

NOT here: FantasyPros (their season projections went login-gated Aug 2026 —
only ~10 anonymous rows — and the partners consensus-rankings API carries no
points field for type=draft; FP stays in the WEEKLY feed via r2p_pts).
Yahoo publishes no projections at all. Mike Clay lives in
mike_clay_projections.js (Phase G); sportsbook-implied comes from
betting_lines (app.js _bookPpgFor).

Names are resolved to d.js-canonical spelling at pull time (inject_rankings
final_key, KTC-phase pattern) so app.js lookup is a plain SITE_PROJ.players[d.n];
feed names with no d.js player are dropped.

Output: window.SITE_PROJ = {updated, season, players:
  {"Name": {sl:[half,ppr,std], es:[...], cb:[...]}}}  (season totals, 1dp)

Any single source failing is a warning (card shows dashes for it); all three
failing aborts without writing. Usage:
  python scripts/pull_site_projections.py [--dry]
Runs as Phase M of the 9am daily job.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'site_projections.js')
STATE_URL = 'https://api.sleeper.app/v1/state/nfl'
SLEEPER_URL = ('https://api.sleeper.com/projections/nfl/{season}'
               '?season_type=regular'
               '&position[]=QB&position[]=RB&position[]=WR&position[]=TE&position[]=K'
               '&order_by=pts_ppr')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/126.0 Safari/537.36'}
ESPN_URL = ('https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}'
            '/segments/0/leaguedefaults/3?view=kona_player_info')
ESPN_POS = {1: 'QB', 2: 'RB', 3: 'WR', 4: 'TE', 5: 'K'}
CBS_URL = ('https://www.cbssports.com/fantasy/football/stats/{pos}/{season}'
           '/season/projections/ppr/')
CBS_POS = ['QB', 'RB', 'WR', 'TE']
CAP = 600

# feed name -> d.js canonical, for spellings normalization can't bridge.
NAME_ALIASES = {
    'Kenny Gainwell': 'Kenneth Gainwell',
    'Joshua Palmer': 'Josh Palmer',
}


def r1(v):
    return round(float(v), 1)


def pull_sleeper(season):
    r = requests.get(SLEEPER_URL.format(season=season), timeout=60)
    r.raise_for_status()
    out = {}
    for row in r.json():
        st = row.get('stats') or {}
        pl = row.get('player') or {}
        p = st.get('pts_ppr')
        if p is None or p <= 0:
            continue
        name = (pl.get('first_name', '') + ' ' + pl.get('last_name', '')).strip()
        if not name or name in out:
            continue
        out[name] = [r1(st.get('pts_half_ppr', p)), r1(p), r1(st.get('pts_std', p))]
        if len(out) >= CAP:
            break
    return out


def pull_espn(season):
    flt = {'players': {'limit': 500,
                       'sortPercOwned': {'sortAsc': False, 'sortPriority': 1}}}
    r = requests.get(ESPN_URL.format(season=season),
                     headers={**UA, 'X-Fantasy-Filter': json.dumps(flt)}, timeout=60)
    r.raise_for_status()
    out = {}
    for p in r.json().get('players', []):
        info = p.get('player') or {}
        name = (info.get('fullName') or '').strip()
        if not name or info.get('defaultPositionId') not in ESPN_POS:
            continue
        for st in info.get('stats', []):
            if (st.get('statSourceId') == 1 and st.get('statSplitTypeId') == 0
                    and st.get('seasonId') == season and st.get('scoringPeriodId') == 0):
                ppr = st.get('appliedTotal')
                if not isinstance(ppr, (int, float)) or ppr <= 0:
                    break
                rec = (st.get('stats') or {}).get('53') or 0
                out[name] = [r1(ppr - rec * 0.5), r1(ppr), r1(ppr - rec)]
                break
    return out


# CBS column header -> stat key for the house rescore.
CBS_COLS = {
    'Passing Yards': 'py', 'Touchdowns Passes': 'ptd',
    'Rushing Yards': 'ry', 'Rushing Touchdowns': 'rtd',
    'Receiving Yards': 'rcy', 'Receiving Touchdowns': 'rctd',
    'Receptions': 'rec',
}


def pull_cbs(season):
    """Season stat components from the projection tables, rescored to the
    house formula so CBS reads on the same scale as Sleeper/ESPN."""
    out = {}
    for pos in CBS_POS:
        try:
            r = requests.get(CBS_URL.format(pos=pos, season=season),
                             headers=UA, timeout=60)
            r.raise_for_status()
            txt = r.text
            thead = re.search(r'<thead>(.*?)</thead>', txt, re.S)
            heads = re.findall(r'<th[^>]*>.*?<div[^>]*>\s*(.*?)\s*</div>',
                               thead.group(1), re.S) if thead else []
            heads = [re.sub(r'<[^>]+>|\s+', ' ', h).strip() for h in heads]
            idx = {key: heads.index(h) for h, key in CBS_COLS.items() if h in heads}
            if not ({'py', 'ry', 'rcy'} & set(idx)):
                print(f'  !! CBS {pos}: no yardage columns found — skipped')
                continue
            n = 0
            for row in re.findall(r'<tr class="TableBase-bodyTr">(.*?)</tr>', txt, re.S):
                name_m = re.search(
                    r'CellPlayerName--long.*?<a href="/nfl/players/\d+/'
                    r'[a-z0-9-]+/[^"]*"[^>]*>([^<]+)</a>', row, re.S)
                cells = re.findall(r'<td[^>]*>\s*([-\d.]+)\s*</td>', row)
                if not name_m or len(cells) != len(heads):
                    continue
                name = name_m.group(1).strip()
                try:
                    c = {k: float(cells[i]) for k, i in idx.items()}
                except ValueError:
                    continue
                base = (c.get('py', 0) / 25 + c.get('ptd', 0) * 4 +
                        c.get('ry', 0) / 10 + c.get('rtd', 0) * 6 +
                        c.get('rcy', 0) / 10 + c.get('rctd', 0) * 6)
                rec = c.get('rec', 0)
                if base <= 0 or name in out:
                    continue
                out[name] = [r1(base + rec * 0.5), r1(base + rec), r1(base)]
                n += 1
            print(f'  CBS {pos}: {n} rows')
            time.sleep(0.4)
        except Exception as e:
            print(f'  !! CBS {pos}: {e} — position skipped')
    return out


def resolve_to_djs(sources):
    """Re-key every source map to d.js-canonical names; drop names d.js
    doesn't carry. Returns {canon_name: {key: [h,p,s]}}."""
    sys.path.insert(0, ROOT)
    from inject_rankings import final_key

    dsrc = open(os.path.join(ROOT, 'data', 'd.js'), encoding='utf-8').read()
    names = re.findall(r'"n":"([^"]+)"', dsrc)
    exact = set(names)
    norm_idx = {}
    for n in names:
        norm_idx.setdefault(final_key(n), n)

    players = {}
    for key, src in sources.items():
        matched = 0
        for name, vals in src.items():
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
    if not season:
        sys.exit(f'!! bad state response: {state}')

    sources = {}
    for key, label, floor, fn in (
            ('sl', 'Sleeper', 300, lambda: pull_sleeper(season)),
            ('es', 'ESPN', 150, lambda: pull_espn(season)),
            ('cb', 'CBS', 150, lambda: pull_cbs(season))):
        try:
            src = fn()
            if len(src) < floor:
                raise ValueError(f'only {len(src)} rows (<{floor})')
            sources[key] = src
            print(f'{len(src)} {label} season projections')
        except Exception as e:
            print(f'!! {label} pull failed ({e}) — card shows dashes for it this run')
    if not sources:
        sys.exit('!! every source failed — refusing to write')

    players = resolve_to_djs(sources)
    if dry:
        for n in list(players)[:8]:
            print(f'  {n}: {players[n]}')
        return

    payload = {
        'updated': datetime.now(timezone.utc).isoformat(),
        'season': season,
        'players': players,
    }
    body = ('// Auto-generated by scripts/pull_site_projections.py — do not hand-edit.\n'
            '// Per-site SEASON fantasy-point projections for the player-card\n'
            '// "Season Projections" comparison. Per player: sl/es/cb =\n'
            '// Sleeper/ESPN/CBS [half, ppr, std] season totals (app.js ÷17 for PPG).\n'
            'window.SITE_PROJ = '
            + json.dumps(payload, separators=(',', ':'), ensure_ascii=False) + ';\n')
    old = open(OUT, encoding='utf-8').read() if os.path.exists(OUT) else ''
    open(OUT, 'w', encoding='utf-8', newline='\n').write(body)
    print(f'data/site_projections.js written ({len(body):,} bytes, '
          f'{len(players)} players, {"changed" if body != old else "no change"})')


if __name__ == '__main__':
    main()
