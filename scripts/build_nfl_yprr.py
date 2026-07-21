"""
Backfill per-season NFL Y/RR (yards per route run) into data/d.js career
arrays for WR/TE/RB.

The 2023-25 values already in d.js came from manual PFF exports. PFF
routes aren't freely available for older seasons, so this script builds a
routes-run PROXY from nflverse participation data (2016-2023): a route is
counted as any REG-season QB dropback (excl. spikes/kneels) where the
player was on the field. The numerator is the season's receiving yards
already stored in the d.js row (rcy), so the displayed ratio always
matches the row it sits in.

Never overwrites an existing yrr value (PFF > proxy). Seasons before 2016
and after 2023 have no participation data and are left untouched.

Run from repo root:
  python scripts/build_nfl_yprr.py --validate   # compare proxy vs PFF 2023, no writes
  python scripts/build_nfl_yprr.py --write      # surgically insert missing yrr into data/d.js

Downloads are cached in --cache (default .nflverse_cache/, gitignored).
"""

import argparse, io, json, os, re, sys, unicodedata
import urllib.request

try:
    import pyarrow.parquet as pq
except ImportError:
    sys.exit('pyarrow required: pip install pyarrow')

REL = 'https://github.com/nflverse/nflverse-data/releases/download'
PART_YEARS = range(2016, 2026)   # 404s (no participation post-2023) are skipped
MIN_ROUTES = 20                  # below this the ratio is noise; leave the dash

# Position-level calibration proxy->PFF, filled in by --validate and then
# hard-coded here. PFF only counts actual routes; the participation proxy
# counts every on-field dropback (incl. pass-block snaps), so it OVERcounts
# routes and deflates Y/RR — worst for RBs who stay in to block.
# From --validate vs PFF (stable per-year 2023/2024/2025): WR 0.99/0.99/0.99,
# TE 1.02/1.04/1.06, RB 1.20/1.19/1.19 — corr 0.94-0.98.
CALIBRATION = {'WR': 1.0, 'TE': 1.04, 'RB': 1.19}


def fetch(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    print(f'GET {url}')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=300) as r, open(dest + '.part', 'wb') as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f'  404 (skipping)')
            return None
        raise
    os.replace(dest + '.part', dest)
    return dest


def norm_name(n):
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode()
    n = re.sub(r"\s+(Jr\.?|Sr\.?|II|III|IV|V)$", '', n.strip(), flags=re.I)
    n = n.replace('.', '').replace("'", '').replace('-', ' ')
    return re.sub(r'\s+', ' ', n).lower()


def build_routes(cache):
    """{(gsis_id, season): route_count} from participation x pbp."""
    routes = {}
    for yr in PART_YEARS:
        part_f = fetch(f'{REL}/pbp_participation/pbp_participation_{yr}.parquet',
                       os.path.join(cache, f'part_{yr}.parquet'))
        if not part_f:
            continue
        pbp_f = fetch(f'{REL}/pbp/play_by_play_{yr}.parquet',
                      os.path.join(cache, f'pbp_{yr}.parquet'))
        pbp = pq.read_table(pbp_f, columns=['game_id', 'play_id', 'season_type',
                                            'qb_dropback', 'qb_spike', 'qb_kneel'])
        drop = set()
        cols = [c.to_pylist() for c in pbp.columns]
        for gid, pid, st, db, sp, kn in zip(*cols):
            if st == 'REG' and db == 1 and sp != 1 and kn != 1:
                drop.add((gid, pid))
        part = pq.read_table(part_f)
        gid_col = 'nflverse_game_id' if 'nflverse_game_id' in part.column_names else 'game_id'
        g = part.column(gid_col).to_pylist()
        p = part.column('play_id').to_pylist()
        off = part.column('offense_players').to_pylist()
        n = 0
        for gid, pid, players in zip(g, p, off):
            if (gid, pid) not in drop or not players:
                continue
            n += 1
            for gsis in players.split(';'):
                if gsis:
                    k = (gsis, yr)
                    routes[k] = routes.get(k, 0) + 1
        print(f'  {yr}: {n:,} dropbacks tallied')
    return routes


def build_rosters(cache, years):
    """{(norm_name, season): [(gsis_id, position)]}"""
    idx = {}
    for yr in years:
        f = fetch(f'{REL}/rosters/roster_{yr}.parquet',
                  os.path.join(cache, f'roster_{yr}.parquet'))
        if not f:
            continue
        t = pq.read_table(f, columns=['season', 'full_name', 'gsis_id', 'position'])
        for name, gsis, pos in zip(t.column('full_name').to_pylist(),
                                   t.column('gsis_id').to_pylist(),
                                   t.column('position').to_pylist()):
            if not name or not gsis:
                continue
            k = (norm_name(name), yr)
            v = (gsis, pos)
            idx.setdefault(k, [])
            if v not in idx[k]:
                idx[k].append(v)
    return idx


def load_d(path):
    src = open(path, encoding='utf-8').read()
    m = re.search(r'const D = (\[.*?\]);', src, re.S)
    return src, json.loads(m.group(1))


def resolve_gsis(name, pos, yr, rosters, routes):
    """gsis id for this d.js player-season, or None."""
    cands = rosters.get((norm_name(name), yr), [])
    grp = {'WR', 'TE', 'RB', 'FB', 'HB'}
    cands = [c for c in cands if (c[1] or '') in grp] or cands
    if len(cands) > 1:
        # same name + season + skill position: pick the one who actually
        # played (most routes); ties are genuinely ambiguous -> skip
        cands = sorted(cands, key=lambda c: routes.get((c[0], yr), 0), reverse=True)
        if routes.get((cands[0][0], yr), 0) == routes.get((cands[1][0], yr), 0):
            return None
    return cands[0][0] if cands else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--validate', action='store_true')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--cache', default='.nflverse_cache')
    args = ap.parse_args()
    os.makedirs(args.cache, exist_ok=True)

    routes = build_routes(args.cache)
    part_years = sorted({yr for (_, yr) in routes})
    rosters = build_rosters(args.cache, part_years)
    src, players = load_d('data/d.js')

    if args.validate:
        # proxy vs the PFF values already in d.js (2023 overlap year)
        diffs = {}
        for p in players:
            if p.get('s') not in ('WR', 'TE', 'RB'):
                continue
            for s in p.get('career') or []:
                yr = s.get('yr')
                if yr not in part_years or s.get('yrr') is None:
                    continue
                gsis = resolve_gsis(p['n'], p['s'], yr, rosters, routes)
                if not gsis:
                    continue
                r = routes.get((gsis, yr), 0)
                if r < MIN_ROUTES or not s.get('rcy'):
                    continue
                proxy = s['rcy'] / r
                diffs.setdefault(p['s'], []).append((p['n'], yr, s['yrr'], proxy))
        for pos, rows in sorted(diffs.items()):
            ratios = sorted(pff / proxy for _, _, pff, proxy in rows)
            med = ratios[len(ratios) // 2]
            import statistics
            corr = statistics.correlation([r[2] for r in rows], [r[3] for r in rows]) if len(rows) > 2 else 0
            print(f'{pos}: n={len(rows)}  median PFF/proxy={med:.3f}  '
                  f'p10={ratios[len(ratios)//10]:.3f} p90={ratios[-max(1,len(ratios)//10)]:.3f}  corr={corr:.3f}')
            worst = sorted(rows, key=lambda r: abs(r[2] - r[3] * med), reverse=True)[:5]
            for n, yr, pff, proxy in worst:
                print(f'   {n} {yr}: PFF {pff:.2f} vs calibrated proxy {proxy*med:.2f}')
        return

    # collect fills: (player_name, yr) -> value
    fills = []
    skipped_ambig, skipped_routes = [], []
    for p in players:
        if p.get('s') not in ('WR', 'TE', 'RB'):
            continue
        for s in p.get('career') or []:
            yr = s.get('yr')
            if yr not in part_years or 'yrr' in s:
                continue
            gsis = resolve_gsis(p['n'], p['s'], yr, rosters, routes)
            if not gsis:
                skipped_ambig.append((p['n'], yr))
                continue
            r = routes.get((gsis, yr), 0)
            if r < MIN_ROUTES:
                skipped_routes.append((p['n'], yr, r))
                continue
            val = round((s.get('rcy') or 0) / r * CALIBRATION[p['s']], 2)
            fills.append((p['n'], yr, val, r))

    print(f'\nFills: {len(fills)}   no-roster-match/ambiguous: {len(skipped_ambig)}   '
          f'<{MIN_ROUTES} routes: {len(skipped_routes)}')
    from collections import Counter
    print('  by year:', dict(sorted(Counter(yr for _, yr, _, _ in fills).items())))
    if skipped_ambig[:15]:
        print('  unmatched sample:', skipped_ambig[:15])

    if not args.write:
        print('\nDry run (use --write to modify data/d.js)')
        return

    # surgical insertion: find each player's career block in the raw text
    # and add "yrr":V before the closing brace of the matching season obj
    new_src = src
    applied = 0
    by_player = {}
    for n, yr, val, r in fills:
        by_player.setdefault(n, {})[yr] = val
    for name, yrs in by_player.items():
        esc = re.escape(json.dumps(name)[1:-1])
        m = re.search(r'"n":"' + esc + r'".*?"career":\[(.*?)\](?=[,}])', new_src)
        if not m:
            print(f'  !! career block not found for {name}')
            continue
        block, b0, b1 = m.group(1), m.start(1), m.end(1)
        def add_yrr(mo):
            o = mo.group(0)
            yr = int(re.search(r'"yr":(\d+)', o).group(1))
            if yr in yrs and '"yrr"' not in o:
                return o[:-1] + f',"yrr":{yrs[yr]}}}'
            return o
        new_block, cnt = re.subn(r'\{[^{}]*\}', add_yrr, block), None
        new_src = new_src[:b0] + new_block[0] + new_src[b1:]
        applied += sum(1 for yr in yrs if f'"yrr":{yrs[yr]}' in new_block[0])
    open('data/d.js', 'w', encoding='utf-8', newline='').write(new_src)
    print(f'\nWrote data/d.js — {applied} season rows updated')


if __name__ == '__main__':
    main()
