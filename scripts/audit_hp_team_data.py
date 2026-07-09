"""Audit + rebuild data/hp.js: complete `_teams` and `_bestByTeam` for every
retired player using the full career data in data/all_players.js.

The Fantasy Game's season mode reads `_bestByTeam[team]` for each pick. Many
HP entries only stored the player's BEST team (e.g. Chris Johnson had Titans
2009 only — his Jets 2014 and Cardinals 2015 weren't there). When a player
gets randomly selected for a team that isn't in their `_bestByTeam`, season
mode returns null and the player card's year range falls back to the overall
`_yrs` string instead of the team-specific window.

This script regenerates `_bestByTeam` for every (player, team) pair the
player actually played for, picking the season with the highest fpts.
"""

import json
import re
import shutil
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
HP_FILE = DATA_DIR / "hp.js"
ALL_PLAYERS_FILE = DATA_DIR / "all_players.js"

TEAM_FULL = {
    'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens',
    'BUF': 'Buffalo Bills', 'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears',
    'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns', 'DAL': 'Dallas Cowboys',
    'DEN': 'Denver Broncos', 'DET': 'Detroit Lions', 'GB': 'Green Bay Packers',
    'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars',
    'JAC': 'Jacksonville Jaguars', 'KC': 'Kansas City Chiefs',
    'LA': 'Los Angeles Rams', 'LAR': 'Los Angeles Rams', 'LAC': 'Los Angeles Chargers',
    'LV': 'Las Vegas Raiders', 'LVR': 'Las Vegas Raiders', 'MIA': 'Miami Dolphins',
    'MIN': 'Minnesota Vikings', 'NE': 'New England Patriots', 'NO': 'New Orleans Saints',
    'NYG': 'New York Giants', 'NYJ': 'New York Jets', 'OAK': 'Las Vegas Raiders',
    'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers',
    'SD': 'Los Angeles Chargers', 'SEA': 'Seattle Seahawks', 'SF': 'San Francisco 49ers',
    'STL': 'Los Angeles Rams', 'TB': 'Tampa Bay Buccaneers', 'TEN': 'Tennessee Titans',
    'WAS': 'Washington Commanders', 'HOIL': 'Tennessee Titans',  # Houston Oilers
    'PHX': 'Arizona Cardinals',  # Phoenix Cardinals
    'STLR': 'Los Angeles Rams', 'BLT': 'Baltimore Ravens',
    'ARZ': 'Arizona Cardinals', 'CLV': 'Cleveland Browns', 'HST': 'Houston Texans',
    'WSH': 'Washington Commanders', 'JAX0': 'Jacksonville Jaguars',
}


def parse_js_array(text: str, var_prefix_re: str) -> list:
    """Strip a `const NAME = [...]` declaration and JSON-parse the array."""
    s = text.strip()
    m = re.match(var_prefix_re, s)
    if not m:
        raise RuntimeError(f"prefix not matched: {var_prefix_re}")
    s = s[m.end():].lstrip()
    # Walk to find balanced array brackets, respecting strings
    depth = 0
    in_str = False
    esc = False
    end = -1
    if s[0] != '[':
        raise RuntimeError("expected '[' after prefix")
    for i in range(len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        raise RuntimeError("array unbalanced")
    return json.loads(s[:end])


def parse_all_players(text: str) -> list:
    """data/all_players.js may declare ALL_PLAYERS as a top-level const or
    assign it to window. Try both."""
    return parse_js_array(text, r'(?:const|let|var)?\s*ALL_PLAYERS_DB\s*=\s*')


def parse_hp(text: str) -> list:
    return parse_js_array(text, r'(?:const|let|var)?\s*HP\s*=\s*')


def build_career_map(all_players: list, year_bounds: dict) -> dict:
    """name -> { team_full -> {best_season_dict} }. Best chosen by max fpts.

    year_bounds: optional {name: (y1, y2)} from hp.js `_yrs`. Used to filter
    out same-name collisions (e.g. there were two NFL players named Antonio
    Brown — one a 2003 FB, the famous WR drafted 2010 — and all_players.js
    merges them into a single 'Antonio Brown' key.)"""
    out = defaultdict(dict)
    for p in all_players:
        name = p.get('name')
        if not name:
            continue
        career = p.get('career') or []
        bounds = year_bounds.get(name)
        per_team = defaultdict(list)
        for s in career:
            tm_abbr = (s.get('tm') or '').upper()
            tm_full = TEAM_FULL.get(tm_abbr)
            if not tm_full or s.get('gp', 0) <= 0:
                continue
            yr = s.get('yr')
            if bounds and yr is not None:
                y1, y2 = bounds
                if yr < y1 or yr > y2:
                    continue
            per_team[tm_full].append(s)
        best = {}
        for tm_full, seasons in per_team.items():
            seasons.sort(key=lambda s: s.get('fpts', 0), reverse=True)
            entry = {k: v for k, v in seasons[0].items() if k != 'tm'}
            best[tm_full] = entry
        out[name] = best
    return out


def parse_yrs(yrs_str: str):
    """Parse '2010-2021' or '2010' style year strings to (y1, y2). Return None
    if unparseable."""
    if not yrs_str:
        return None
    m = re.match(r'(\d{4})(?:-(\d{4}))?', yrs_str)
    if not m:
        return None
    y1 = int(m.group(1))
    y2 = int(m.group(2)) if m.group(2) else y1
    return (y1, y2)


def emit_value(v):
    """Emit a JSON-ish value compatible with the original hp.js (no spaces)."""
    return json.dumps(v, separators=(',', ':'))


def emit_hp(entries: list) -> str:
    parts = []
    for e in entries:
        # Maintain key order: n, s, _teams, _yrs, _retired, _bestByTeam
        ordered = {}
        for key in ('n', 's', '_teams', '_yrs', '_retired', '_bestByTeam'):
            if key in e:
                ordered[key] = e[key]
        # Append any remaining keys not in our preferred order
        for k, v in e.items():
            if k not in ordered:
                ordered[k] = v
        parts.append(emit_value(ordered))
    return 'const HP = [' + ','.join(parts) + '];\n'


def main():
    print(f"Reading {ALL_PLAYERS_FILE}...")
    ap_text = ALL_PLAYERS_FILE.read_text(encoding='utf-8')
    all_players = parse_all_players(ap_text)
    print(f"  {len(all_players)} players in all_players.js")

    print(f"Reading {HP_FILE}...")
    hp_text = HP_FILE.read_text(encoding='utf-8')
    hp = parse_hp(hp_text)
    print(f"  {len(hp)} entries in hp.js")

    # Build year bounds from hp.js _yrs so build_career_map can filter
    # out same-name collisions (the famous Antonio Brown vs the 2003 FB AB).
    year_bounds = {}
    for entry in hp:
        bounds = parse_yrs(entry.get('_yrs') or '')
        if bounds:
            year_bounds[entry['n']] = bounds
    print(f"  {len(year_bounds)} hp entries had parseable _yrs to bound by")

    print("Building career map from all_players.js...")
    career_map = build_career_map(all_players, year_bounds)
    print(f"  {len(career_map)} players have career-derived team breakdowns")

    # Stats
    enriched = 0
    teams_added = 0
    teamlist_corrected = 0
    untouched = 0

    for entry in hp:
        name = entry.get('n')
        new_best = career_map.get(name)
        if not new_best:
            untouched += 1
            continue

        old_best = entry.get('_bestByTeam') or {}
        old_teams = list(entry.get('_teams') or [])
        new_team_list = list(new_best.keys())

        # Count new teams added to _bestByTeam
        added = [t for t in new_team_list if t not in old_best]
        if added:
            teams_added += len(added)
            enriched += 1

        # Replace _bestByTeam with the complete career-derived version. This
        # supersedes the partial data; old entries kept the same chosen
        # best-season anyway (highest fpts), so values match where present.
        entry['_bestByTeam'] = new_best

        # Reconcile _teams. Use the union of (career-derived teams) and
        # (existing _teams), in career order so the player card lists
        # the most-played-for team first when broken across multiple sources.
        union = []
        for t in new_team_list + old_teams:
            if t not in union:
                union.append(t)
        if union != old_teams:
            teamlist_corrected += 1
        entry['_teams'] = union

    print(f"Enriched _bestByTeam for {enriched} players (+{teams_added} team entries)")
    print(f"Corrected _teams for {teamlist_corrected} players")
    print(f"Untouched (no all_players match): {untouched}")

    # Backup and write
    backup = HP_FILE.with_suffix('.js.bak_pre_audit')
    shutil.copy2(HP_FILE, backup)
    print(f"Backup: {backup.name}")

    HP_FILE.write_text(emit_hp(hp), encoding='utf-8')
    print(f"Wrote {HP_FILE}")

    # Spot-check
    print("\nSpot checks:")
    for name in ('Chris Johnson', 'Le\'Veon Bell', 'Frank Gore', 'Antonio Brown', 'DeMarco Murray'):
        for e in hp:
            if e.get('n') == name:
                teams = list((e.get('_bestByTeam') or {}).keys())
                print(f"  {name}: {len(teams)} teams in _bestByTeam: {', '.join(teams)}")
                break
        else:
            print(f"  {name}: not in hp.js")


if __name__ == '__main__':
    main()
