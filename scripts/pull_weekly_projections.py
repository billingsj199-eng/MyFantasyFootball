"""Weekly consensus projections: Sleeper + ESPN + FantasyPros -> data/weekly_projections.js.

The weekly PROJ PPG chain (app.js _weeklyAdjustPpg) scores posted prop lines
first (books are primary, Jack's rule); players WITHOUT a prop board fell to
the position-blind heuristic (season PPG x team-total x opp-defense). This
feed gives those players a real per-week number instead.

Week selection: Sleeper /v1/state/nfl. During the regular season, the live
week; preseason/offseason, regular-season week 1 (Sleeper publishes W1
projections in August). Values are Sleeper's pts_half_ppr / pts_ppr /
pts_std per player, top 600 by half-PPR. DEF is skipped - the DST branch in
_weeklyAdjustPpg returns before the consensus slot.

Sleeper stays the consensus source _weeklyAdjustPpg scores from (h/p/s keys,
format unchanged). ESPN and FantasyPros ride along as reference-only keys on
each player — 'e' and 'f', both [half, ppr, std] — shown on the player card
WEEKLY tab. Either side source failing is a warning, not an abort: the card
renders '—' for a missing source. Yahoo is absent by necessity: their fantasy
API exposes no projections and their site numbers sit behind a league login.

  ESPN: lm-api-reads kona_player_info on leaguedefaults/3 (PPR scoring).
        appliedTotal for statSourceId=1/statSplitTypeId=1/scoringPeriodId=wk
        is the PPR projection; half/std derived off projected receptions
        (stat id 53).
  FP:   partners.fantasypros.com consensus-rankings API, type=weekly, r2p_pts
        field (FP's rank-to-points projection — the number their Start/Sit
        tools show). The projections .php pages cap anonymous visitors at 10
        rows per position (login-gated Aug 2026), so the partners API is the
        only full-pool number available; one request per position x scoring.

Usage: python scripts/pull_weekly_projections.py [--dry]
Runs as Phase J of the 9am daily job.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'weekly_projections.js')
OUT_JSON = os.path.join(ROOT, 'data', 'weekly_projections.json')
STATE_URL = 'https://api.sleeper.app/v1/state/nfl'
PROJ_URL = ('https://api.sleeper.com/projections/nfl/{season}/{week}'
            '?season_type=regular'
            '&position[]=QB&position[]=RB&position[]=WR&position[]=TE&position[]=K'
            '&order_by=pts_half_ppr')
CAP = 600

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/126.0 Safari/537.36'}
ESPN_URL = ('https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}'
            '/segments/0/leaguedefaults/3?view=kona_player_info')
ESPN_POS = {1: 'QB', 2: 'RB', 3: 'WR', 4: 'TE', 5: 'K'}  # 16=DST skipped
FP_URL = ('https://partners.fantasypros.com/api/v1/consensus-rankings.php'
          '?sport=NFL&year={season}&week={week}&position={pos}&type=weekly&scoring={sc}')
FP_POS = ['QB', 'RB', 'WR', 'TE', 'K']


def norm_name(n):
    n = n.lower()
    n = re.sub(r"[.'`-]", '', n)
    n = re.sub(r'\s+(jr|sr|ii|iii|iv|v)$', '', n.strip())
    return re.sub(r'\s+', ' ', n)


def clean_display(n):
    """Site convention drops generational suffixes ("Marvin Harrison")."""
    return re.sub(r'\s+(Jr\.?|Sr\.?|II|III|IV|V)$', '', n.strip())


def pull_sleeper(season, week):
    r = requests.get(PROJ_URL.format(season=season, week=week), timeout=60)
    r.raise_for_status()
    players = {}
    for row in r.json():
        st = row.get('stats') or {}
        pl = row.get('player') or {}
        h = st.get('pts_half_ppr')
        if h is None:
            continue
        name = (pl.get('first_name', '') + ' ' + pl.get('last_name', '')).strip()
        if not name or name in players:
            continue
        players[name] = {
            'h': round(h, 1),
            'p': round(st.get('pts_ppr', h), 1),
            's': round(st.get('pts_std', h), 1),
        }
        if len(players) >= CAP:
            break
    return players


def pull_espn(season, week):
    """{name: [half, ppr, std]} from ESPN weekly projections (PPR base)."""
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
            if (st.get('statSourceId') == 1 and st.get('statSplitTypeId') == 1
                    and st.get('seasonId') == season and st.get('scoringPeriodId') == week):
                ppr = st.get('appliedTotal')
                if not isinstance(ppr, (int, float)) or ppr <= 0:
                    break
                rec = (st.get('stats') or {}).get('53') or 0
                out[name] = [round(ppr - rec * 0.5, 1), round(ppr, 1), round(ppr - rec, 1)]
                break
    return out


def pull_fp(season, week):
    """{name: [half, ppr, std]} from FantasyPros weekly r2p_pts, per scoring."""
    out = {}
    for sc_i, sc in enumerate(('HALF', 'PPR', 'STD')):
        for pos in FP_POS:
            r = requests.get(FP_URL.format(season=season, pos=pos, week=week, sc=sc),
                             headers=UA, timeout=60)
            r.raise_for_status()
            for p in r.json().get('players', []):
                name = (p.get('player_name') or '').strip()
                try:
                    v = round(float(p.get('r2p_pts')), 1)
                except (TypeError, ValueError):
                    continue
                if name and v > 0:
                    out.setdefault(name, [None, None, None])[sc_i] = v
            time.sleep(0.4)
    # keep only players with all three formats (partial rows render inconsistently)
    return {n: v for n, v in out.items() if all(x is not None for x in v)}


def attach(players, source, key):
    """Merge {name: [h,p,s]} onto the Sleeper-keyed dict (norm-name fallback)."""
    idx = {norm_name(n): n for n in players}
    matched = added = 0
    for name, vals in source.items():
        canon = name if name in players else idx.get(norm_name(name))
        if canon:
            players[canon][key] = vals
            matched += 1
        else:
            disp = clean_display(name)
            players.setdefault(disp, {})[key] = vals
            added += 1
    return matched, added


def main():
    dry = '--dry' in sys.argv
    state = requests.get(STATE_URL, timeout=30).json()
    season = state.get('season')
    week = state.get('week') if state.get('season_type') == 'regular' else 1
    if not season or not week:
        sys.exit(f'!! bad state response: {state}')
    season, week = int(season), int(week)

    players = pull_sleeper(season, week)
    if len(players) < 100:
        sys.exit(f'!! only {len(players)} Sleeper projections parsed — refusing to write')
    print(f'{len(players)} Sleeper weekly projections (season {season} week {week})')

    for label, key, fn in (('ESPN', 'e', lambda: pull_espn(season, week)),
                           ('FantasyPros', 'f', lambda: pull_fp(season, week))):
        try:
            src = fn()
            if len(src) < 50:
                raise ValueError(f'only {len(src)} rows parsed')
            m, a = attach(players, src, key)
            print(f'{len(src)} {label} projections ({m} matched, {a} new names)')
        except Exception as e:
            print(f'!! {label} pull failed ({e}) — card shows dashes for it this run')

    if dry:
        for n in list(players)[:8]:
            v = players[n]
            print(f"  {n}: sleeper {v.get('h')} espn {v.get('e')} fp {v.get('f')}")
        return
    payload = {
        'updated': datetime.now(timezone.utc).isoformat(),
        'src': 'sleeper+espn+fp',
        'season': season,
        'week': week,
        'players': players,
    }
    body = ('// Auto-generated by scripts/pull_weekly_projections.py — do not hand-edit.\n'
            '// Consensus weekly projections consumed by _weeklyAdjustPpg in app.js.\n'
            "// Per player: h/p/s = Sleeper (scoring source); e/f = ESPN/FantasyPros\n"
            '// reference-only [half, ppr, std] for the player-card WEEKLY tab.\n'
            'window.WEEKLY_PROJ = '
            + json.dumps(payload, separators=(',', ':'), ensure_ascii=False) + ';\n')
    old = open(OUT, encoding='utf-8').read() if os.path.exists(OUT) else ''
    open(OUT, 'w', encoding='utf-8', newline='\n').write(body)
    print(f'data/weekly_projections.js written ({len(body):,} bytes, '
          f'{"changed" if body != old else "no change"})')
    # Pure-JSON twin for the helper extensions (the .js twin gets minified at
    # deploy into unquoted-key JS they can't JSON.parse) — betting_lines pattern.
    jbody = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    open(OUT_JSON, 'w', encoding='utf-8', newline='\n').write(jbody)
    print(f'data/weekly_projections.json written ({len(jbody):,} bytes)')


if __name__ == '__main__':
    main()
