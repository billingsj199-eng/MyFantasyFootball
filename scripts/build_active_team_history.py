"""Rebuild data/active_team_history.js from nflverse roster CSVs + d.js.

Why: ACTIVE_TEAM_HISTORY had only ~72 entries, leaving most active players
without team history. The Fantasy Game's per-team filter falls back to a
player's current team only, so anyone who's changed teams (Justin Fields,
DJ Moore, etc.) only appears in the game for their CURRENT team — never
their previous one. This script builds a complete history for every active
fantasy player using nflverse roster data 2021-2025 + d.js for 2026.

Pre-2021 history is preserved from the existing hand-curated entries so
veterans like Mike Evans / Davante Adams keep their full career arc.
"""

import csv
import json
import re
import shutil
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
ROSTER_DIR = Path(__file__).parent / "_nflverse_rosters"
DATA_DIR = ROOT / "data"
OUT_FILE = DATA_DIR / "active_team_history.js"
D_JS = DATA_DIR / "d.js"

# Modern team full-name lookup. Includes legacy abbreviations so a 2014
# Oakland Raiders entry maps to the modern Las Vegas Raiders name (matches
# the runtime TEAM_ALIASES in index.html).
TEAM_FULL = {
    'ARI': 'Arizona Cardinals',
    'ATL': 'Atlanta Falcons',
    'BAL': 'Baltimore Ravens',
    'BUF': 'Buffalo Bills',
    'CAR': 'Carolina Panthers',
    'CHI': 'Chicago Bears',
    'CIN': 'Cincinnati Bengals',
    'CLE': 'Cleveland Browns',
    'DAL': 'Dallas Cowboys',
    'DEN': 'Denver Broncos',
    'DET': 'Detroit Lions',
    'GB':  'Green Bay Packers',
    'HOU': 'Houston Texans',
    'IND': 'Indianapolis Colts',
    'JAX': 'Jacksonville Jaguars',
    'JAC': 'Jacksonville Jaguars',
    'KC':  'Kansas City Chiefs',
    'LA':  'Los Angeles Rams',
    'LAR': 'Los Angeles Rams',
    'LAC': 'Los Angeles Chargers',
    'LV':  'Las Vegas Raiders',
    'LVR': 'Las Vegas Raiders',
    'MIA': 'Miami Dolphins',
    'MIN': 'Minnesota Vikings',
    'NE':  'New England Patriots',
    'NO':  'New Orleans Saints',
    'NYG': 'New York Giants',
    'NYJ': 'New York Jets',
    'OAK': 'Las Vegas Raiders',
    'PHI': 'Philadelphia Eagles',
    'PIT': 'Pittsburgh Steelers',
    'SD':  'Los Angeles Chargers',
    'SEA': 'Seattle Seahawks',
    'SF':  'San Francisco 49ers',
    'STL': 'Los Angeles Rams',
    'TB':  'Tampa Bay Buccaneers',
    'TEN': 'Tennessee Titans',
    'WAS': 'Washington Commanders',
}

FANTASY_POS = {'QB', 'RB', 'WR', 'TE', 'FB'}


def normalize(name: str) -> str:
    """Strip periods, apostrophes, suffixes, lowercase. Used to bridge
    'D.J. Moore' (d.js) with 'DJ Moore' (some other sources) and similar."""
    n = re.sub(r'\s+(Jr\.?|Sr\.?|II|III|IV|V)$', '', name, flags=re.IGNORECASE)
    n = re.sub(r"[.'`]", '', n).lower().strip()
    return n


def load_d_players(d_text: str) -> dict:
    """Parse the D array out of d.js. File starts with `const D = [...]` and
    may have trailing window-export lines after the array literal."""
    # Find the array spanning from the first '[' after `D =` to its matching ']'
    start = d_text.find('=')
    if start == -1:
        raise RuntimeError("d.js missing '=' before array")
    arr_start = d_text.find('[', start)
    if arr_start == -1:
        raise RuntimeError("d.js missing '[' for D array")
    # Walk to find the matching closing bracket, respecting strings.
    depth = 0
    in_str = False
    esc = False
    end = -1
    for i in range(arr_start, len(d_text)):
        ch = d_text[i]
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
        raise RuntimeError("d.js array brackets unbalanced")
    arr = json.loads(d_text[arr_start:end])
    out = {}
    for entry in arr:
        name = entry.get('n')
        if not name:
            continue
        out[name] = {'t': entry.get('t', ''), 's': entry.get('s', '')}
    return out


def load_csv_seasons(roster_dir: Path) -> dict:
    """name -> set of (season, full_team_name). Filters to fantasy positions."""
    out = defaultdict(set)
    for csv_path in sorted(roster_dir.glob("roster_*.csv")):
        season_str = csv_path.stem.split("_")[1]
        try:
            season = int(season_str)
        except ValueError:
            continue
        with csv_path.open(encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("full_name") or "").strip()
                team = (row.get("team") or "").strip()
                pos = (row.get("position") or "").strip().upper()
                if not name or not team or pos not in FANTASY_POS:
                    continue
                full = TEAM_FULL.get(team.upper())
                if not full:
                    continue
                out[name].add((season, full))
    return out


def parse_existing(out_path: Path) -> dict:
    """Parse the existing JS file (regex; file is plain JS literal)."""
    if not out_path.exists():
        return {}
    text = out_path.read_text(encoding="utf-8")
    out = {}
    # Match: 'Name': [...],
    for m in re.finditer(r"'((?:[^'\\]|\\.)+)':\s*\[(.*?)\](?:,)?\s*\n", text):
        name = m.group(1).replace("\\'", "'")
        body = m.group(2)
        ranges = []
        for rm in re.finditer(r"\{t:'((?:[^'\\]|\\.)+)',y1:(\d+),y2:(\d+)\}", body):
            ranges.append({
                't': rm.group(1).replace("\\'", "'"),
                'y1': int(rm.group(2)),
                'y2': int(rm.group(3)),
            })
        if ranges:
            out[name] = ranges
    return out


def compress(seasons_set: set) -> list:
    """Set of (season, team) -> sorted list of compressed ranges. Mid-season
    trades (same season → multiple teams) emit one range per team for that
    year. Open-ended last range (covering 2026) becomes y2=2099."""
    by_season = defaultdict(set)
    for s, t in seasons_set:
        by_season[s].add(t)
    ranges = []
    for season in sorted(by_season.keys()):
        teams = by_season[season]
        if len(teams) == 1:
            t = next(iter(teams))
            if ranges and ranges[-1]['t'] == t and ranges[-1]['y2'] == season - 1:
                ranges[-1]['y2'] = season
            else:
                ranges.append({'t': t, 'y1': season, 'y2': season})
        else:
            # Mid-season trade — emit each team for that single season
            for t in sorted(teams):
                ranges.append({'t': t, 'y1': season, 'y2': season})
    # Open-end the most recent range so the player keeps appearing for the
    # current team in future seasons.
    if ranges and ranges[-1]['y2'] == 2026:
        ranges[-1]['y2'] = 2099
    return ranges


def merge_with_existing(generated: dict, existing: dict) -> dict:
    """Preserve pre-2021 ranges from existing entries (CSV only covers 2021+).
    For ranges that span the seam (e.g. Davante Adams Packers 2014-2021), cap
    the existing range at 2020 and let the generated 2021+ entry pick up. If
    the seam-spanning team matches between existing and generated, fold them
    back into one continuous range."""
    out = {}
    for name in set(generated.keys()) | set(existing.keys()):
        gen = list(generated.get(name, []))
        ex = list(existing.get(name, []))
        if not gen:
            out[name] = ex
            continue
        if not ex:
            out[name] = gen
            continue
        # Keep any existing range that started before 2021. Cap its y2 at 2020
        # so the CSV-derived (more accurate) entries own 2021+.
        pre = []
        for r in ex:
            if r['y1'] < 2021:
                pre.append({'t': r['t'], 'y1': r['y1'], 'y2': min(r['y2'], 2020)})
        # Seam fold: if pre's last entry ends 2020 on team X and gen's first
        # entry starts 2021 on team X, merge into one continuous range so we
        # don't show "Packers 2014-2020 -> Packers 2021-2021" awkwardly.
        if pre and gen and pre[-1]['t'] == gen[0]['t'] and pre[-1]['y2'] == 2020 and gen[0]['y1'] == 2021:
            pre[-1] = {'t': pre[-1]['t'], 'y1': pre[-1]['y1'], 'y2': gen[0]['y2']}
            gen = gen[1:]
        out[name] = pre + gen
    return out


def emit(result: dict) -> str:
    lines = ["const ACTIVE_TEAM_HISTORY = {"]
    for name in sorted(result.keys()):
        ranges_str = ",".join(
            f"{{t:'{r['t']}',y1:{r['y1']},y2:{r['y2']}}}" for r in result[name]
        )
        name_escaped = name.replace("'", "\\'")
        lines.append(f"    '{name_escaped}': [{ranges_str}],")
    lines.append("};")
    return "\n".join(lines) + "\n"


def main():
    print(f"Reading CSVs from {ROSTER_DIR}...")
    csv_seasons = load_csv_seasons(ROSTER_DIR)
    print(f"  {len(csv_seasons)} unique players in CSVs (fantasy positions only)")

    print(f"Reading {D_JS}...")
    d_text = D_JS.read_text(encoding="utf-8")
    d_players = load_d_players(d_text)
    print(f"  {len(d_players)} entries in D")

    # Build normalized -> canonical name map from D, so CSV "DJ Moore" maps to D's "D.J. Moore"
    d_norm_to_name = {}
    for n in d_players.keys():
        d_norm_to_name[normalize(n)] = n

    # Re-key CSV entries to D's canonical name when there's a normalized match
    canonical_seasons = defaultdict(set)
    unmatched = 0
    for csv_name, seasons in csv_seasons.items():
        nkey = normalize(csv_name)
        if nkey in d_norm_to_name:
            canonical = d_norm_to_name[nkey]
            canonical_seasons[canonical].update(seasons)
        else:
            unmatched += 1
    print(f"  {len(canonical_seasons)} CSV players matched to D, {unmatched} unmatched (likely retired or never in D)")

    # Add 2026 season from D's current team for any active fantasy player
    added_2026 = 0
    for name, info in d_players.items():
        if info['s'] not in FANTASY_POS:
            continue
        team_full = info['t']
        if team_full not in TEAM_FULL.values():
            continue
        canonical_seasons[name].add((2026, team_full))
        added_2026 += 1
    print(f"  Added 2026 current-team entries for {added_2026} D players")

    # Compress (season, team) into ranges
    generated = {}
    for name, seasons in canonical_seasons.items():
        ranges = compress(seasons)
        if ranges:
            generated[name] = ranges

    # Backup the old file before overwriting
    if OUT_FILE.exists():
        backup = OUT_FILE.with_suffix(".js.bak_pre_audit")
        shutil.copy2(OUT_FILE, backup)
        print(f"Backed up existing file to {backup.name}")

    existing = parse_existing(OUT_FILE)
    print(f"  Parsed {len(existing)} entries from existing file")

    merged = merge_with_existing(generated, existing)
    print(f"Final: {len(merged)} ACTIVE_TEAM_HISTORY entries (was {len(existing)})")

    OUT_FILE.write_text(emit(merged), encoding="utf-8")
    print(f"Wrote {OUT_FILE}")

    # Quick sanity check: report a few high-profile players
    for player in ["D.J. Moore", "Justin Fields", "DK Metcalf", "Davante Adams", "Stefon Diggs"]:
        if player in merged:
            ranges = merged[player]
            summary = " -> ".join(f"{r['t']} ({r['y1']}-{r['y2']})" for r in ranges)
            print(f"  {player}: {summary}")
        else:
            print(f"  {player}: NOT IN OUTPUT")


if __name__ == "__main__":
    main()
