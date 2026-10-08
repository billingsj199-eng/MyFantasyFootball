# Pull NFL snap counts (nflverse, 2012+) + team weekly target totals (1999+)
# and build data/snap_counts.js for the player card's SNP% and TS% columns.
#
# Output format:
#   window.SNAP_COUNTS = {
#     "Josh Allen": { "2025": { "s": 98.5, "w": {"1": 100, "2": 87, ...} }, ... }
#   }
#   window.TEAM_TGT = { "2025": { "CIN": { "2": 43, ... }, ... }, ... }
#   window.TEAM_CAR = { "2025": { "CIN": { "2": 17, ... }, ... }, ... }
# s = season offensive snap % (snap-weighted: sum(snaps)/sum(team snaps))
# w = per-week offensive snap % (whole numbers, REG season only)
# TEAM_TGT = exact team pass targets per week (REG), the TS% denominator.
# TEAM_CAR = exact team rush attempts per week (REG), the CAR% denominator.
#
# Only players present in data/d.js are kept (the player card only opens for
# D-array players). nflverse names are normalized to d.js names (dots/suffixes).
# Team codes are normalized to the site's convention (LA -> LAR); era codes
# (SD/OAK/STL) are kept as-is to match historical rows.

import io
import json
import os
import re
import sys
import time

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'snap_counts.js')
URL = 'https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{yr}.csv'
TEAM_URL = 'https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{yr}.csv'
YEARS = range(2012, 2027)
TEAM_YEARS = range(1999, 2027)
# PFR lists some backs as HB (2026: Chase Brown, Samaje Perine) - without it
# their SNP% column is blank all season.
POSITIONS = {'QB', 'RB', 'HB', 'WR', 'TE', 'FB'}
TEAM_FIX = {'LA': 'LAR'}  # nflverse "LA" = modern Rams; site uses "LAR"


def norm_variants(name):
    """Yield lookup variants for a name (dots stripped, suffix stripped,
    apostrophes stripped: d.js "Tre' Harris" is "Tre Harris" on nflverse)."""
    v = {name}
    v.add(name.replace('.', ''))
    no_suffix = re.sub(r'\s+(Jr\.?|Sr\.?|II|III|IV|V)$', '', name, flags=re.I).strip()
    v.add(no_suffix)
    v.add(no_suffix.replace('.', ''))
    v |= {re.sub(r"['’`]", '', x) for x in v}
    return {x.lower() for x in v}


def _surname(name):
    n = re.sub(r"\s+(Jr\.?|Sr\.?|II|III|IV|V)$", '', name or '', flags=re.I)
    n = re.sub(r"[.'’`]", '', n).strip().lower()
    return n.split(' ')[-1] if n else ''


def onfield_maps(players_csv):
    """(gsis -> display_name, lowercase display_name -> gsis) from nflverse players.csv;
    a name shared by several players goes to the most recent one."""
    df = pd.read_csv(players_csv, usecols=['gsis_id', 'display_name', 'last_season'], low_memory=False)
    df = df[df.gsis_id.notna() & df.display_name.notna()].sort_values('last_season', na_position='first')
    return dict(zip(df.gsis_id, df.display_name)), dict(zip(df.display_name.str.lower(), df.gsis_id))


def onfield_slots(ids, names, gsis_name, name_gsis):
    """[(gsis, [names to try])] for one nflverse participation row - the ONE matcher behind the
    card's RT% (pull_route_pct.py) and the Research Route% (build_adv_stats.py).

    The file has two faults (2026-09-29 audit): offense_names carries legal names some weeks
    ("Nathaniel Dell" 2023 W1-11, id right) and offense_players carries another player's id
    some weeks (Khalil Shakir 2025 W12 = Brandin Cooks's id, name right). Same surname ->
    the id stands and the name comes from players.csv; different surname -> the name wins."""
    ids = [x.strip() for x in str(ids).split(';')] if isinstance(ids, str) else []
    nms = [x.strip() for x in str(names).split(';')] if isinstance(names, str) else []
    if len(nms) != len(ids):
        nms = [''] * len(ids) if ids else nms
        ids = ids or [''] * len(nms)
    out = []
    for i, nm in zip(ids, nms):
        disp = gsis_name.get(i, '')
        if nm and (not disp or _surname(nm) != _surname(disp)):
            i, disp = name_gsis.get(nm.lower(), ''), nm
        if i or disp:
            # both spellings: d.js may follow either ("Kenneth Gainwell" in the file,
            # "Kenny Gainwell" in players.csv)
            out.append((i, [x for x in dict.fromkeys((nm, disp)) if x]))
    return out


def load_d_names():
    src = open(os.path.join(ROOT, 'data', 'd.js'), encoding='utf-8').read()
    names = set(re.findall(r'[,{]"n":"([^"]+)"', src))
    if not names:  # unquoted-key fallback
        names = set(re.findall(r'[,{]n:"([^"]+)"', src))
    lookup = {}
    for n in names:
        for v in norm_variants(n):
            lookup.setdefault(v, n)
    print(f'd.js players: {len(names)} ({len(lookup)} name variants)')
    return lookup


def main():
    lookup = load_d_names()
    result = {}   # canonical name -> {year: {'off': int, 'team': float, 'w': {wk: pct}}}
    for yr in YEARS:
        r = requests.get(URL.format(yr=yr), timeout=60)
        if r.status_code != 200:
            print(f'{yr}: HTTP {r.status_code}, skipped')
            continue
        df = pd.read_csv(io.BytesIO(r.content))
        df = df[(df.game_type == 'REG') & (df.position.isin(POSITIONS)) & (df.offense_snaps > 0)]
        matched = 0
        for row in df.itertuples(index=False):
            canon = None
            for v in norm_variants(str(row.player)):
                if v in lookup:
                    canon = lookup[v]
                    break
            if not canon:
                continue
            matched += 1
            pct = float(row.offense_pct)
            if pct <= 0:
                continue
            yrs = result.setdefault(canon, {}).setdefault(str(yr), {'off': 0, 'team': 0.0, 'w': {}})
            yrs['off'] += int(row.offense_snaps)
            yrs['team'] += row.offense_snaps / pct
            yrs['w'][str(int(row.week))] = round(pct * 100)
        print(f'{yr}: {len(df)} rows, {matched} matched to d.js players')
        time.sleep(0.5)

    out = {}
    for name, years in result.items():
        out[name] = {}
        for yr, agg in years.items():
            if not agg['team']:
                continue
            out[name][yr] = {
                's': round(100.0 * agg['off'] / agg['team'], 1),
                'w': agg['w'],
            }

    # Team weekly target + carry totals (exact TS% / CAR% denominators)
    team_tgt = {}
    team_car = {}
    for yr in TEAM_YEARS:
        r = requests.get(TEAM_URL.format(yr=yr), timeout=60)
        if r.status_code != 200:
            print(f'team {yr}: HTTP {r.status_code}, skipped')
            continue
        df = pd.read_csv(io.BytesIO(r.content))
        df = df[df.season_type == 'REG']
        y = team_tgt.setdefault(str(yr), {})
        yc = team_car.setdefault(str(yr), {})
        for row in df.itertuples(index=False):
            tm = TEAM_FIX.get(str(row.team), str(row.team))
            wk = str(int(row.week))
            if not pd.isna(row.targets):
                y.setdefault(tm, {})[wk] = int(row.targets)
            if not pd.isna(row.carries):
                yc.setdefault(tm, {})[wk] = int(row.carries)
        print(f'team {yr}: {len(y)} teams')
        time.sleep(0.3)

    js = ('window.SNAP_COUNTS=' + json.dumps(out, separators=(',', ':')) + ';\n'
          + 'window.TEAM_TGT=' + json.dumps(team_tgt, separators=(',', ':')) + ';\n'
          + 'window.TEAM_CAR=' + json.dumps(team_car, separators=(',', ':')) + ';\n')
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(js)
    print(f'wrote {OUT}: {len(out)} players, {len(team_tgt)} team seasons, {os.path.getsize(OUT)/1024:.0f} KB')


if __name__ == '__main__':
    sys.exit(main())
