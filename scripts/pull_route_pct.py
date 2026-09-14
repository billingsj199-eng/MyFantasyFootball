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
             season"), so in-season the ONLY live source is PFF Premium's
             weekly receiving table, pulled by scripts/pull_pff_weekly.py into
               E:\\MyFantasyFootball\\pbp_cache\\pff\\weekly\\pff_receiving_2026_w<N>.csv
             (the standard PFF receiving_summary columns: player, team_name,
             routes, route_rate, ...). RT% = routes / team dropbacks (team
             dropbacks from the nightly play_by_play_2026; PFF's own
             route_rate is the fallback when pbp lacks the week). Weeks with
             no PFF file yet stay ESTIMATED from snap share (per-week `est`
             list) until the file lands. If pbp_participation_2026 ever
             appears (post-season) it takes over automatically.

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
                elif row.get('route_rate') not in (None, ''):
                    # pbp for the week not downloaded yet: PFF's own route_rate,
                    # weighted like one game (~35 dropbacks) for the season sum.
                    try:
                        out.setdefault(dn, {})[wk] = (float(row['route_rate']) * 0.35, 35.0)
                    except ValueError:
                        pass
    print(f'  {yr}: PFF weekly exports for weeks {[int(re.search(r"_w(\d+)", f).group(1)) for f in files]}')
    return out


def _snap_counts():
    """window.SNAP_COUNTS from data/snap_counts.js -> {name: {yr: {s, w:{wk}}}}"""
    p = os.path.join(ROOT, 'data', 'snap_counts.js')
    raw = open(p, encoding='utf-8').read()
    i = raw.index('window.SNAP_COUNTS')
    i = raw.index('=', i) + 1
    obj, _ = json.JSONDecoder().raw_decode(raw, i + (len(raw[i:]) - len(raw[i:].lstrip())))
    return obj


def estimate_from_snaps(yr, result, dpos):
    """Current-season fallback (no participation, no PFF weekly): RT% ~=
    weekly snap share x the player's own routes-per-snap ratio from his most
    recent season with both numbers (position median for rookies / no
    history). Marked est:1 so the card renders it as an estimate. Replaced by
    real numbers as soon as a PFF weekly export exists for the week."""
    try:
        snaps = _snap_counts()
    except Exception as e:  # noqa: BLE001
        print(f'  snap_counts.js unreadable ({e})')
        return {}
    # position median ratio (RT season share / SNP season share), latest prior season
    ratios_by_pos = {}
    player_ratio = {}
    for dn, yrs in result.items():
        pos = dpos.get(dn)
        if not pos:
            continue
        for y in sorted((int(k) for k in yrs if int(k) < yr), reverse=True):
            rt = yrs[str(y)].get('s')
            sn = (snaps.get(dn, {}).get(str(y)) or {}).get('s')
            if rt and sn and sn >= 20 and not yrs[str(y)].get('est'):
                r = max(0.25, min(1.2, rt / sn))
                player_ratio[dn] = r
                ratios_by_pos.setdefault(pos, []).append(r)
                break
    import statistics
    pos_default = {p: statistics.median(v) for p, v in ratios_by_pos.items() if v}
    out = {}
    for dn, pos in dpos.items():
        cur = (snaps.get(dn) or {}).get(str(yr))
        if not cur or not cur.get('w'):
            continue
        r = player_ratio.get(dn) or pos_default.get(pos)
        if not r:
            continue
        w = {wk: int(round(min(100.0, v * r))) for wk, v in cur['w'].items() if isinstance(v, (int, float))}
        if not w:
            continue
        out[dn] = {'s': round(min(100.0, (cur.get('s') or 0) * r), 1) if cur.get('s') is not None else None, 'w': w, 'est': 1}
    print(f'  {yr}: ratio medians by pos {{' + ', '.join(f"{k}: {v:.2f}" for k, v in sorted(pos_default.items())) + '}')
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
            i = raw.index('window.ROUTE_PCT = ') + len('window.ROUTE_PCT = ')
            result, _ = json.JSONDecoder().raw_decode(raw, i)
        except Exception as e:  # noqa: BLE001
            print(f'  existing route_pct.js unreadable ({e}) - rebuilding from scratch')
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
            est = estimate_from_snaps(yr, result, dpos)
            if est:
                for dn, season in est.items():
                    result.setdefault(dn, {})[str(yr)] = season
                src_used[str(yr)] = 'snap-estimate'
                print(f'  {yr}: no participation file and no PFF weekly exports - ESTIMATED from snap share for {len(est)} players')
            else:
                print(f'  {yr}: no participation file, no PFF weekly exports, no snaps - skipped')
            continue
        # PFF files lag the games by a day or so: weeks (and players) the
        # files do not cover yet keep the snap-share estimate, flagged per
        # week in `est` (list of week strings); a season with only estimated
        # weeks keeps est:1. The season share `s` counts real weeks only.
        est = estimate_from_snaps(yr, result, dpos) if src == 'pff-weekly' else {}
        n = n_mixed = 0
        for dn, wks in data.items():
            plays = sum(c for c, _ in wks.values())
            db = sum(d for _, d in wks.values())
            season = {'s': round(100.0 * plays / db, 1) if db else None,
                      'w': {str(w): int(round(100.0 * c / d)) for w, (c, d) in sorted(wks.items()) if d}}
            e = est.get(dn)
            if e:
                extra = {w: v for w, v in e['w'].items() if w not in season['w']}
                if extra:
                    season['w'] = {w: season['w'].get(w, extra.get(w)) for w in sorted(set(season['w']) | set(extra), key=int)}
                    season['est'] = sorted(extra, key=int)
                    n_mixed += 1
            result.setdefault(dn, {})[str(yr)] = season
            n += 1
        n_est = 0
        for dn, e in est.items():
            if dn not in data:
                result.setdefault(dn, {})[str(yr)] = e
                n_est += 1
        src_used[str(yr)] = src
        print(f'  {yr}: {n} players ({src}, {time.time() - t0:.0f}s)'
              + (f'; {n_mixed} with estimated weeks pending PFF, {n_est} estimate-only' if est else ''))

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
