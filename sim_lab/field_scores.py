# BBM full-field scoring: compute every entry's weekly best-ball scores and
# regular-season totals from a BBM pick-by-pick CSV + Sleeper weekly actuals.
# Companion to ingest_bbm_field.py — the day the BBM VII field drops, this is
# the live leaderboard Underdog doesn't publish: pod standings + points-back
# cutlines for the user's entries, field-wide ranks, and the true field score
# distribution (feeds the playoff advance curves).
#
#   python field_scores.py "<rd1.csv>" --season 2026 --weeks 1-14 --user jackb933
#   python field_scores.py "<bbm_vi_rd1.csv>" --season 2025 --weeks 1-14 \
#          --user jackb933 --validate     # BBM VI carries official
#          # roster_points + made_playoffs -> ground-truth check of our scoring
#
# Scoring = Underdog half PPR = Sleeper pts_std + 0.5*rec (Sleeper defaults
# match UD: 4-pt pass TD, -1 INT, -2 fum lost) — same formula the Sim Lab
# banked-weeks pipeline uses. Weekly stats are cached to field_cache/ forever
# (completed weeks are immutable). Lineup: 1QB / 2RB / 3WR / 1TE / 1FLEX.
import argparse
import json
import os
import re
import sys
import urllib.request

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'field_cache')
OUT = os.path.join(HERE, 'field_out')

SUFF = re.compile(r'\b(jr|sr|ii|iii|iv|v)\b')


def norm(n):
    n = str(n or '').lower().replace('.', '').replace("'", '').replace('-', ' ')
    return re.sub(r'\s+', ' ', SUFF.sub('', n)).strip()


def fetch_json(url, cache_name):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, cache_name)
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    with urllib.request.urlopen(url, timeout=60) as r:
        data = json.load(r)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    return data


def sleeper_name_index():
    """Match tiers: norm|pos, collapsed(no-space)|pos (BBM strips hyphens:
    'AmonRa St Brown', 'Jaxon SmithNjigba'), then first-initial+lastname|pos
    when unique (Kenneth vs Kenny Gainwell)."""
    players = fetch_json('https://api.sleeper.app/v1/players/nfl', 'players_nfl.json')
    by_np, by_cp, by_ip = {}, {}, {}
    for pid, p in players.items():
        if not isinstance(p, dict):
            continue
        pos = p.get('position') or ''
        if pos not in ('QB', 'RB', 'WR', 'TE'):
            continue
        nm = norm((p.get('first_name') or '') + ' ' + (p.get('last_name') or ''))
        if not nm:
            continue
        by_np.setdefault(nm + '|' + pos, pid)
        by_cp.setdefault(nm.replace(' ', '') + '|' + pos, pid)
        parts = nm.split(' ')
        if len(parts) >= 2:
            ik = parts[0][0] + '|' + ' '.join(parts[1:]) + '|' + pos
            by_ip.setdefault(ik, []).append(pid)
    by_ip = {k: v[0] for k, v in by_ip.items() if len(v) == 1}
    return by_np, by_cp, by_ip


def week_points(season, wk, cacheable=True):
    """player_id -> UD half-PPR points. The CURRENT week is still accumulating
    (Fri run = through TNF, Mon run = through Sunday) so it is never cached."""
    url = f'https://api.sleeper.app/v1/stats/nfl/regular/{season}/{wk}'
    if cacheable:
        stats = fetch_json(url, f'stats_{season}_{wk}.json')
    else:
        with urllib.request.urlopen(url, timeout=60) as r:
            stats = json.load(r)
    return {pid: (s.get('pts_std') or 0) + 0.5 * (s.get('rec') or 0)
            for pid, s in stats.items() if isinstance(s, dict)}


POS_CODE = {'QB': 0, 'RB': 1, 'WR': 2, 'TE': 3}
STARTERS = {0: 1, 1: 2, 2: 3, 3: 1}  # QB1 RB2 WR3 TE1 (+1 flex RB/WR/TE)


def bestball_week(df, pts_col):
    """Per-entry best-ball points for one week. df: entry, poscode, pts."""
    d = df.sort_values(['entry', 'poscode', pts_col], ascending=[True, True, False])
    rank = d.groupby(['entry', 'poscode'], observed=True).cumcount()
    need = d.poscode.map(STARTERS)
    starter = rank < need
    flex_cand = (~starter) & (d.poscode > 0) & (rank == need)  # next-best RB/WR/TE only
    start_sum = d.loc[starter].groupby('entry', observed=True)[pts_col].sum()
    flex = d.loc[flex_cand].groupby('entry', observed=True)[pts_col].max()
    return start_sum.add(flex, fill_value=0)


def report_user(ent, name, adv_per_pod, n_field):
    """Pod standings + advance summary for ANY username in the field."""
    u = str(name).lower().strip().lstrip('@')
    mine = ent[ent.username.astype(str).str.lower().str.strip() == u].sort_values('pod_rank')
    if not len(mine):
        print(f'\n=== {name}: no entries found ===')
        return
    n_in = int((mine.pod_rank <= adv_per_pod).sum())
    print(f'\n=== {name}: {len(mine)} entries · {n_in} advancing ({100 * n_in / len(mine):.1f}%)'
          f' · avg total {mine.total.mean():.1f} · best field rank #{int(mine.field_rank.min()):,}'
          f' of {n_field:,} ===')
    for _, r in mine.iterrows():
        status = 'IN' if r.pod_rank <= adv_per_pod else f'{r.pts_back:+.1f} back'
        print(f'  pod {str(r.draft_id)[:8]}…  total {r.total:7.1f}  '
              f'pod {int(r.pod_rank):2d} ({status})  field #{int(r.field_rank):,} '
              f'(top {100 * r.field_rank / n_field:.1f}%)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv_path', nargs='?')
    ap.add_argument('--season', type=int, required=True)
    ap.add_argument('--weeks', default='1-14')
    ap.add_argument('--user', nargs='+', default=None, help='username(s) to report pods for')
    ap.add_argument('--lookup', nargs='+', default=None,
                    help='search username(s) in the ALREADY-COMPUTED leaderboard (instant, no CSV needed)')
    ap.add_argument('--validate', action='store_true',
                    help='rd1 roster_points is a WEEK-1 snapshot (frozen at the '
                         'contest-close release) — validate our wk1 scores against it')
    ap.add_argument('--rd2', default=None,
                    help='path to the rd2 (quarterfinals) CSV — validates our computed '
                         'pod top-N advancers against who ACTUALLY reached week 15')
    ap.add_argument('--adv-per-pod', type=int, default=2)
    ap.add_argument('--chunk', type=int, default=1_000_000)
    args = ap.parse_args()

    cur_week = None  # partial (in-progress) week when --weeks auto mid-season
    if args.weeks == 'auto':
        with urllib.request.urlopen('https://api.sleeper.app/v1/state/nfl', timeout=30) as r:
            st = json.load(r)
        if st.get('season_type') != 'regular' or not (st.get('week') or 0) >= 1:
            print('season not underway — nothing to score yet (auto mode)', file=sys.stderr)
            return
        cur_week = min(14, int(st['week']))
        args.weeks = f'1-{cur_week}'
        print(f'auto weeks: 1-{cur_week} (wk {cur_week} PARTIAL — games still to play)',
              file=sys.stderr)

    if args.lookup:
        lb = os.path.join(OUT, f'field_leaderboard_{args.season}.csv')
        if not os.path.exists(lb):
            print(f'no computed leaderboard at {lb} — run the full compute first', file=sys.stderr)
            sys.exit(1)
        ent = pd.read_csv(lb)
        for name in args.lookup:
            report_user(ent, name, args.adv_per_pod, len(ent))
        return
    if not args.csv_path:
        print('csv_path required (or use --lookup)', file=sys.stderr)
        sys.exit(1)
    w_lo, w_hi = (int(x) for x in args.weeks.split('-'))
    weeks = list(range(w_lo, w_hi + 1))
    os.makedirs(OUT, exist_ok=True)

    print('loading field CSV (streaming)…', file=sys.stderr)
    usecols = ['draft_id', 'tournament_entry_id', 'username', 'player_name', 'position_name']
    if args.validate:
        usecols += ['roster_points', 'made_playoffs']
    chunks = []
    for ch in pd.read_csv(args.csv_path, usecols=usecols, chunksize=args.chunk, dtype=str):
        chunks.append(ch)
        print(f'\r  {sum(len(c) for c in chunks):,} rows', end='', file=sys.stderr)
    df = pd.concat(chunks, ignore_index=True)
    print(file=sys.stderr)
    for c in ('draft_id', 'tournament_entry_id', 'username', 'player_name', 'position_name'):
        df[c] = df[c].astype('category')
    df['entry'] = df.tournament_entry_id.cat.codes
    df['poscode'] = df.position_name.map(POS_CODE).fillna(-1).astype(np.int8)
    df = df[df.poscode >= 0].copy()

    print('matching players to Sleeper ids…', file=sys.stderr)
    by_np, by_cp, by_ip = sleeper_name_index()
    name_to_nk = {pn: norm(pn) for pn in df.player_name.cat.categories}
    def pid_of(pn, pos):
        nk = name_to_nk[pn]
        hit = by_np.get(nk + '|' + pos) or by_cp.get(nk.replace(' ', '') + '|' + pos)
        if hit:
            return hit
        parts = nk.split(' ')
        if len(parts) >= 2:
            return by_ip.get(parts[0][0] + '|' + ' '.join(parts[1:]) + '|' + pos)
        return None
    pos_names = {v: k for k, v in POS_CODE.items()}
    df['pid'] = [pid_of(pn, pos_names[pc]) for pn, pc in
                 zip(df.player_name.astype(str), df.poscode)]
    n_unmatched = df.pid.isna().sum()
    if n_unmatched:
        miss = df[df.pid.isna()].player_name.value_counts().head(10)
        print(f'  {n_unmatched:,} picks unmatched to Sleeper '
              f'({100 * n_unmatched / len(df):.2f}%) — top: {dict(miss)}', file=sys.stderr)

    totals = None
    weekly_dists = {}
    wk1_scores = None
    for wk in weeks:
        pts = week_points(args.season, wk, cacheable=(cur_week is None or wk < cur_week))
        df['_p'] = df.pid.map(pts).fillna(0.0)
        wt = bestball_week(df[['entry', 'poscode', '_p']], '_p')
        weekly_dists[wk] = np.percentile(wt.values, [10, 25, 50, 75, 90, 95, 99]).round(1).tolist()
        if wk == 1:
            wk1_scores = wt
        totals = wt if totals is None else totals.add(wt, fill_value=0)
        print(f'  wk {wk}: field median {wt.median():.1f}', file=sys.stderr)

    ent = (df.drop_duplicates('entry')[['entry', 'draft_id', 'tournament_entry_id', 'username']]
           .set_index('entry'))
    ent['total'] = totals
    ent['total'] = ent.total.fillna(0)
    ent['field_rank'] = ent.total.rank(ascending=False, method='min').astype(int)
    ent['pod_rank'] = ent.groupby('draft_id', observed=True).total.rank(
        ascending=False, method='min').astype(int)
    # points back from the pod's Nth place (the advance cutline)
    cut = ent.groupby('draft_id', observed=True).total.transform(
        lambda s: s.nlargest(args.adv_per_pod).min())
    ent['pts_back'] = (cut - ent.total).round(2)

    if args.validate and wk1_scores is not None:
        # rd1's roster_points was frozen at the contest-close publication —
        # i.e. it's each entry's WEEK 1 best-ball score, the one official
        # number we can check our scoring formula + lineup logic against.
        off = df.drop_duplicates('entry').set_index('entry')
        offp = pd.to_numeric(off.roster_points, errors='coerce')
        both = pd.DataFrame({'ours': wk1_scores}).join(offp.rename('official')).dropna()
        both = both[both.official > 0]
        err = both.ours - both.official
        print(f'WK1 VALIDATION vs official snapshot: n={len(both):,}  '
              f'corr={both.ours.corr(both.official):.4f}  MAE={err.abs().mean():.2f} pts  '
              f'bias={err.mean():+.2f}  within 1 pt: {100 * (err.abs() <= 1).mean():.1f}%')
    if args.rd2:
        adv_ids = set(pd.read_csv(args.rd2, usecols=['tournament_entry_id'])
                      .tournament_entry_id.unique())
        truly = ent.tournament_entry_id.astype(str).isin(adv_ids)
        ours = ent.pod_rank <= args.adv_per_pod
        tp = int((truly & ours).sum())
        print(f'ADVANCE VALIDATION vs rd2 presence: real advancers {int(truly.sum()):,}, '
              f'ours {int(ours.sum()):,}, overlap {tp:,} '
              f'({100 * tp / max(1, int(truly.sum())):.2f}% of real advancers identified)')

    ent.sort_values('field_rank').to_csv(os.path.join(OUT, f'field_leaderboard_{args.season}.csv'))
    with open(os.path.join(OUT, f'field_dist_{args.season}.json'), 'w') as f:
        json.dump({'weeks': weekly_dists,
                   'total_pctiles': {p: round(float(np.percentile(ent.total, p)), 1)
                                     for p in (10, 25, 50, 75, 90, 95, 99)}}, f, indent=1)

    if args.user:
        for name in args.user:
            report_user(ent, name, args.adv_per_pod, len(ent))

    print(f'\nwrote {OUT}/field_leaderboard_{args.season}.csv ({len(ent):,} entries) '
          f'+ field_dist_{args.season}.json')


if __name__ == '__main__':
    main()
