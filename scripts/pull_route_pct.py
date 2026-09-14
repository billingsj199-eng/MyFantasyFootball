#!/usr/bin/env python3
"""
Route participation (RT%) per player-week -> data/route_pct.js

  window.ROUTE_PCT = {
    "Jaxon Smith-Njigba": { "2025": { "s": 91.3, "w": {"1": 94, "2": 88, ...} }, ... }
  }
  w = % of the team's dropbacks that week the player was on the field for
      (whole numbers, REG season only); s = season share over the weeks he
      appeared (sum plays / sum team dropbacks in those weeks).

Sources
  2016-2025  nflverse pbp_participation (offense_names on every play) joined
             to play_by_play qb_dropback plays -> "on the field for a dropback"
             = the standard public routes proxy (counts pass-blocking snaps for
             RBs/TEs too; PFF's charted routes would run a touch lower).
  2026       nflverse participation is FTN-sourced and published only AFTER
             the postseason (nflreadr schedule: "does not update during the
             season"), so in-season the ONLY live source is Jack's PFF
             receiving export filtered to one week, dropped in
               E:\\MyFantasyFootball\\pbp_cache\\pff\\weekly\\pff_receiving_2026_w<N>.csv
             (the standard PFF receiving_summary CSV: player, team_name,
             routes, ...). RT% = routes / team dropbacks (team dropbacks come
             from the nightly play_by_play_2026). If pbp_participation_2026
             ever appears (post-season) it takes over automatically.

Only players in data/d.js at RB/WR/TE are kept (the card only opens for
D-array players). Names normalized like pull_snap_counts.py.

Run from the project root: python scripts/pull_route_pct.py [--years 2024,2025]
"""
import argparse, csv, glob, io, json, os, re, sys, time
import pandas as pd
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
from pull_snap_counts import norm_variants, load_d_names  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'route_pct.js')
CACHE = r'E:\MyFantasyFootball\pbp_cache'
PFF_WEEKLY = os.path.join(CACHE, 'pff', 'weekly')
PART_URL = 'https://github.com/nflverse/nflverse-data/releases/download/pbp_participation/pbp_participation_{yr}.parquet'
PBP_URL = 'https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{yr}.csv.gz'
YEARS = range(2016, 2027)
POS = {'RB', 'WR', 'TE'}
TEAM_FIX = {'LA': 'LAR', 'WSH': 'WAS', 'JAC': 'JAX', 'OAK': 'LV', 'SD': 'LAC', 'STL': 'LAR',
            'ARZ': 'ARI', 'BLT': 'BAL', 'CLV': 'CLE', 'HST': 'HOU'}
UA = {'User-Agent': 'curl/8.4.0'}


def fetch(url, dest, min_bytes=10000):
    if os.path.exists(dest) and os.path.getsize(dest) > min_bytes:
        return True
    try:
        r = requests.get(url, headers=UA, timeout=180, stream=True)
        if r.status_code != 200:
            return False
        with open(dest, 'wb') as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        return os.path.getsize(dest) > min_bytes
    except Exception as e:  # noqa: BLE001
        print(f'  fetch failed {url}: {e}')
        if os.path.exists(dest):
            os.remove(dest)
        return False


def load_d_pos():
    src = open(os.path.join(ROOT, 'data', 'd.js'), encoding='utf-8').read()
    D = json.loads(src[src.index('['):src.rindex(']') + 1])
    return {p['n']: p['s'] for p in D if p.get('s') in POS}


def dropbacks(yr):
    """REG-season dropback plays: DataFrame[game_id, play_id, week, posteam]"""
    p = os.path.join(CACHE, f'play_by_play_{yr}.csv.gz')
    if not fetch(PBP_URL.format(yr=yr), p, 100000):
        return None
    df = pd.read_csv(p, usecols=['game_id', 'play_id', 'week', 'season_type', 'posteam', 'qb_dropback'], low_memory=False)
    df = df[(df.season_type == 'REG') & (df.qb_dropback == 1) & df.posteam.notna()]
    df['posteam'] = df.posteam.map(lambda t: TEAM_FIX.get(t, t))
    return df[['game_id', 'play_id', 'week', 'posteam']]


_GSIS = None
def gsis_names():
    """{gsis_id: display_name} from nflverse players.csv (cached in pbp_cache)."""
    global _GSIS
    if _GSIS is None:
        p = os.path.join(CACHE, 'players.csv')
        fetch('https://github.com/nflverse/nflverse-data/releases/download/players/players.csv', p, 100000)
        df = pd.read_csv(p, usecols=['gsis_id', 'display_name'], low_memory=False)
        df = df[df.gsis_id.notna()]
        _GSIS = dict(zip(df.gsis_id, df.display_name))
    return _GSIS


def from_participation(yr, lookup):
    """{dname: {wk: (plays, team_db)}} from nflverse participation."""
    part_p = os.path.join(CACHE, f'pbp_participation_{yr}.parquet')
    if not fetch(PART_URL.format(yr=yr), part_p):
        return None
    pbp = dropbacks(yr)
    if pbp is None:
        return None
    import pyarrow.parquet as pq
    cols = pq.ParquetFile(part_p).schema.names
    # 2023+ files carry offense_names; the 2016-2022 (NGS-era) files only carry
    # offense_players = GSIS ids -> map through nflverse players.csv.
    if 'offense_names' in cols:
        part = pd.read_parquet(part_p, columns=['nflverse_game_id', 'play_id', 'offense_names'])
    else:
        gsis = gsis_names()
        part = pd.read_parquet(part_p, columns=['nflverse_game_id', 'play_id', 'offense_players'])
        part['offense_names'] = part.offense_players.map(
            lambda v: ';'.join(gsis.get(i, '') for i in str(v).split(';')) if isinstance(v, str) else None)
    m = part.merge(pbp, left_on=['nflverse_game_id', 'play_id'], right_on=['game_id', 'play_id'], how='inner')
    m = m[m.offense_names.notna() & (m.offense_names != '')]
    team_db, cnt = {}, {}
    for r in m.itertuples(index=False):
        k = (r.posteam, int(r.week))
        team_db[k] = team_db.get(k, 0) + 1
        for nm in str(r.offense_names).split(';'):
            nm = nm.strip()
            if not nm:
                continue
            dn = None
            for v in norm_variants(nm):
                dn = lookup.get(v)
                if dn:
                    break
            if not dn:
                continue
            kk = (dn, r.posteam, int(r.week))
            cnt[kk] = cnt.get(kk, 0) + 1
    out = {}
    for (dn, tm, wk), c in cnt.items():
        db = team_db.get((tm, wk), 0)
        if db >= 10:
            out.setdefault(dn, {})[wk] = (c, db)
    return out


def from_pff_weekly(yr, lookup):
    """{dname: {wk: (routes, team_db)}} from PFF weekly receiving exports."""
    files = sorted(glob.glob(os.path.join(PFF_WEEKLY, f'pff_receiving_{yr}_w*.csv')))
    if not files:
        return None
    pbp = dropbacks(yr)
    if pbp is None:
        return None
    team_db = pbp.groupby(['posteam', 'week']).size().to_dict()
    out = {}
    for f in files:
        wk = int(re.search(r'_w(\d+)\.csv$', f).group(1))
        with open(f, encoding='utf-8-sig') as fh:
            for row in csv.DictReader(fh):
                nm = (row.get('player') or '').strip()
                tm = TEAM_FIX.get((row.get('team_name') or '').strip(), (row.get('team_name') or '').strip())
                try:
                    routes = float(row.get('routes') or 0)
                except ValueError:
                    continue
                dn = None
                for v in norm_variants(nm):
                    dn = lookup.get(v)
                    if dn:
                        break
                if not dn:
                    continue
                db = team_db.get((tm, wk), 0)
                if db >= 10 and routes >= 0:
                    out.setdefault(dn, {})[wk] = (routes, db)
    print(f'  {yr}: PFF weekly exports for weeks {[int(re.search(r"_w(\d+)", f).group(1)) for f in files]}')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', default=None, help='comma list, default 2016-2026')
    a = ap.parse_args()
    years = [int(y) for y in a.years.split(',')] if a.years else list(YEARS)
    dpos = load_d_pos()
    lookup = {}
    for n in dpos:
        for v in norm_variants(n):
            lookup.setdefault(v, n)
    print(f'd.js RB/WR/TE targets: {len(dpos)}')
    os.makedirs(PFF_WEEKLY, exist_ok=True)

    # keep prior years from the existing file when a year is skipped this run
    result = {}
    if os.path.exists(OUT) and a.years:
        raw = open(OUT, encoding='utf-8').read()
        try:
            result = json.loads(raw[raw.index('{'):raw.rindex('}') + 1])
        except Exception:  # noqa: BLE001
            result = {}
    src_used = {}
    for yr in years:
        t0 = time.time()
        data = from_participation(yr, lookup)
        src = 'participation'
        if data is None:
            data = from_pff_weekly(yr, lookup)
            src = 'pff-weekly'
        if data is None:
            print(f'  {yr}: no participation file and no PFF weekly exports - skipped')
            continue
        n = 0
        for dn, wks in data.items():
            plays = sum(c for c, _ in wks.values())
            db = sum(d for _, d in wks.values())
            season = {'s': round(100.0 * plays / db, 1) if db else None,
                      'w': {str(w): int(round(100.0 * c / d)) for w, (c, d) in sorted(wks.items()) if d}}
            for k in list(result.get(dn, {}).keys()):
                pass
            result.setdefault(dn, {})[str(yr)] = season
            n += 1
        src_used[str(yr)] = src
        print(f'  {yr}: {n} players ({src}, {time.time() - t0:.0f}s)')

    # drop empty players, sort
    out = {k: {y: result[k][y] for y in sorted(result[k])} for k in sorted(result) if result[k]}
    js = ('// Route participation % (share of team dropbacks on the field) per player-week.\n'
          '// Built by scripts/pull_route_pct.py: nflverse pbp_participation 2016-2025 (post-season\n'
          '// files); current season from PFF weekly receiving exports in pbp_cache/pff/weekly/.\n'
          '// {name: {year: {s: season %, w: {week: %}}}}\n'
          'window.ROUTE_PCT = ' + json.dumps(out, separators=(',', ':')) + ';\n'
          'window.ROUTE_PCT_SRC = ' + json.dumps(src_used, separators=(',', ':')) + ';\n')
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(js)
    print(f'wrote {OUT}: {len(out)} players, {len(js) // 1024} KB')


if __name__ == '__main__':
    main()
