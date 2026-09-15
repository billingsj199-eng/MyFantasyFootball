#!/usr/bin/env python3
"""
Advanced stats tables for the admin Research page -> data/adv_stats_<yr>.js

  window.ADV_STATS[2026] = {
    yr, thru,
    QB: {f: [field keys], r: [[row values], ...]},
    RB: {...}, WR: {...}, TE: {...}
  }
  One file per season (2019-2026) plus one per week (adv_stats_<yr>_w<N>.js ->
  window.ADV_STATS["<yr>-w<N>"], same shape + wk; the season file lists `wks`)
  so the page lazy-loads only what is on screen. Column labels / glossary / formats live in app.js (_ADV_COLS) - keep
  the field keys below in sync with it. No build timestamp in the payload, so
  an unchanged season rebuilds byte-identical (no empty daily commits).

Sources (local caches; only the current season's snap counts are fetched live):
  PFF Premium    E:\\MyFantasyFootball\\pbp_cache\\pff
                   pff_receiving_<yr>.csv / pff_rushing_<yr>.csv = official season
                     tables 2019-2025 (routes, grades, alignment, elusive rating)
                   weekly\\pff_<facet>_<yr>_w<N>.csv:
                     passing_pressure   every QB dropback split clean / pressured /
                                        blitz (grades, accuracy, BTT, TWP, TTT)
                     rushing_summary    YCO, missed tackles, breakaway, gap/zone
                     receiving_summary  (2026: pff_receiving_2026_w<N> written by
                                        pull_pff_weekly.py, every player who ran a route)
                     receiving_scheme   man / zone routes, targets, yards
                     receiving_concept  slot + screen
                     receiving_depth    behind LOS / short / medium / deep (20+)
                   The 2018-2025 weekly receiving facets list ONLY players with >= 1
                   target that week, so season route counts come from the season
                   CSV and facet route counts (man/zone/slot) are scaled by
                   season routes / routes in the weeks the facet saw.
  nflverse pbp   play_by_play_<yr>.csv.gz: CPOE, EPA, air yards, target / carry /
                   air-yard shares, red-zone and end-zone looks, success rate,
                   half-PPR points (2-pt conversions not counted)
  nflverse snaps snap_counts_<yr>.parquet: games played, snap share, and the
                   team-weeks each share is measured over (handles trades)
  players.csv    pff_id <-> gsis_id <-> pfr_id crosswalk (name + team fallback)

Run from the project root:
  python scripts/build_adv_stats.py              # every season
  python scripts/build_adv_stats.py --years 2026
"""
import argparse, collections, csv, glob, io, json, math, os, re, sys
import pandas as pd
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
from pull_snap_counts import URL as SNAP_URL, norm_variants, load_d_names  # noqa: E402

CACHE = r'E:\MyFantasyFootball\pbp_cache'
PFF = os.path.join(CACHE, 'pff')
PFF_WEEKLY = os.path.join(PFF, 'weekly')
YEARS = list(range(2019, 2027))
TEAM_FIX = {'LA': 'LAR', 'WSH': 'WAS', 'JAC': 'JAX', 'OAK': 'LV', 'SD': 'LAC', 'STL': 'LAR',
            'ARZ': 'ARI', 'BLT': 'BAL', 'CLV': 'CLE', 'HST': 'HOU'}
PFF_NAME_FIX = {'Joshua Palmer': 'Josh Palmer', 'Chigoziem Okonkwo': 'Chig Okonkwo'}
POS_MAP = {'HB': 'RB', 'FB': 'RB', 'RB': 'RB', 'WR': 'WR', 'TE': 'TE', 'QB': 'QB'}
# Volume floor to make the file: QB dropbacks / RB carries + targets / WR-TE routes.
# Kept near zero so a team filter on the page shows the whole position room
# (shares add up); the page's min-volume input hides fringe players otherwise.
MIN_FLOOR = {'QB': 5, 'RB': 1, 'WR': 1, 'TE': 1}

# Counting stats are SEASON TOTALS (fpt, db, att, ra, ry, tch, scy, hvt, rts, yds,
# td, rz ...); the page's Per game / Totals toggle divides by g client-side.
QB_F = ['n', 'on', 'tm', 'g', 'fpt', 'db', 'att', 'cmpp', 'ypa', 'anya', 'td', 'int',
        'cpoe', 'epa', 'grd', 'acc', 'adot', 'ttt', 'deep', 'btt', 'twp', 'tdp', 'intp',
        'prs', 'p2s', 'skp', 'cgr', 'cacc', 'pgr', 'pacc', 'pypa', 'blz', 'bgr', 'bypa',
        'ra', 'ry', 'rtd', 'scr']
RB_F = ['n', 'on', 'tm', 'g', 'snp', 'fpt', 'att', 'tgt', 'tch', 'scy', 'tds',
        'car', 'tsh', 'rtp', 'i5', 'i10s', 'hvt',
        'ypc', 'yco', 'mtf', 'elu', 'bay', 'exp', 'fdp', 'suc', 'repa', 'rgr', 'gap',
        'rts', 'tprr', 'yprr', 'recg', 'pbg',
        'xt', 'xc', 'xi']
# x* (not displayed) = raw pbp targets / carries / inside-10 carries / air yards while on
# the listed team; with payload `teams` they give the page's team-view season shares
REC_F = ['n', 'on', 'tm', 'g', 'snp', 'fpt', 'rts', 'tgt', 'yds', 'tds',
         'rtp', 'tsh', 'ays', 'wopr', 'tprr', 'rz', 'ez', 'slot', 'wide', 'inl', 'pbr',
         'yprr', 'grd', 'adot', 'racr', 'yac', 'mtfr', 'fdr', 'ctch', 'drp', 'cc', 'ctg',
         'tqbr', 'epat',
         'myprr', 'zyprr', 'mtprr', 'ztprr', 'slyprr', 'scr', 'deep', 'dyd', 'dctch', 'blos',
         'xt', 'xa']


# ---------------------------------------------------------------- helpers
def fnum(v):
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def rnd(x, d=1):
    return None if x is None else round(x, d)


def div(n, d, mult=1.0, dec=1):
    if n is None or not d:
        return None
    return round(n * mult / d, dec)


def team(t):
    t = (t or '').strip()
    return TEAM_FIX.get(t, t)


class Acc:
    """Per-player accumulator for one PFF facet-season."""
    __slots__ = ('s', 'w', 'weeks', 'wk_routes', 'names', 'pos')

    def __init__(self):
        self.s = collections.defaultdict(float)             # summed counts
        self.w = collections.defaultdict(lambda: [0.0, 0.0])  # weighted avg [sum v*wt, sum wt]
        self.weeks = {}                                     # wk -> team
        self.wk_routes = {}                                 # wk -> routes (receiving only)
        self.names = collections.Counter()
        self.pos = collections.Counter()

    def add(self, key, v):
        x = fnum(v)
        if x is not None:
            self.s[key] += x

    def addw(self, key, v, wt):
        x, w = fnum(v), fnum(wt)
        if x is None or not w:
            return
        self.w[key][0] += x * w
        self.w[key][1] += w

    def avg(self, key):
        a = self.w.get(key)
        return a[0] / a[1] if a and a[1] else None


def weekly_weeks(facet, yr):
    out = set()
    for f in glob.glob(os.path.join(PFF_WEEKLY, f'pff_{facet}_{yr}_w*.csv')):
        m = re.search(r'_w(\d+)\.csv$', f)
        if m:
            out.add(int(m.group(1)))
    return sorted(out)


def weekly(facet, yr, only=None):
    """Rows of a PFF weekly facet; only=<week> reads just that week's file."""
    for wk in weekly_weeks(facet, yr):
        if only is not None and wk != only:
            continue
        with open(os.path.join(PFF_WEEKLY, f'pff_{facet}_{yr}_w{wk}.csv'), encoding='utf-8-sig', newline='') as fh:
            for row in csv.DictReader(fh):
                pid = (row.get('player_id') or '').strip()
                if pid:
                    yield wk, pid, row


def touch(acc, wk, row):
    tm = team(row.get('team_name'))
    if tm:
        acc.weeks[wk] = tm
    nm = (row.get('player') or '').strip()
    if nm:
        acc.names[nm] += 1
    ps = (row.get('position') or '').strip()
    if ps:
        acc.pos[ps] += 1


def season_csv(kind, yr):
    p = os.path.join(PFF, f'pff_{kind}_{yr}.csv')
    if not os.path.exists(p):
        return {}
    with open(p, encoding='utf-8-sig', newline='') as fh:
        return {r['player_id'].strip(): r for r in csv.DictReader(fh) if (r.get('player_id') or '').strip()}


# ---------------------------------------------------------------- PFF facets
QB_COUNTS = ['dropbacks', 'attempts', 'completions', 'yards', 'touchdowns', 'interceptions',
             'sacks', 'big_time_throws', 'turnover_worthy_plays', 'aimed_passes', 'drops',
             'scrambles', 'passing_snaps', 'def_gen_pressures']


def agg_passing(yr, only=None):
    out = {}
    for wk, pid, row in weekly('passing_pressure', yr, only):
        a = out.setdefault(pid, Acc())
        touch(a, wk, row)
        # pressure_ + no_pressure_ partition every dropback; blitz_ is a subset
        for c in QB_COUNTS:
            a.add(c, row.get('pressure_' + c))
            a.add(c, row.get('no_pressure_' + c))
            a.add('p_' + c, row.get('pressure_' + c))
            a.add('c_' + c, row.get('no_pressure_' + c))
            a.add('b_' + c, row.get('blitz_' + c))
        pdb = fnum(row.get('pressure_dropbacks')) or 0
        cdb = fnum(row.get('no_pressure_dropbacks')) or 0
        a.addw('grd', row.get('grades_pass'), pdb + cdb)
        a.addw('pgr', row.get('pressure_grades_pass'), pdb)
        a.addw('cgr', row.get('no_pressure_grades_pass'), cdb)
        a.addw('bgr', row.get('blitz_grades_pass'), row.get('blitz_dropbacks'))
        for pre in ('pressure_', 'no_pressure_'):
            a.addw('adot', row.get(pre + 'avg_depth_of_target'), row.get(pre + 'attempts'))
            a.addw('ttt', row.get(pre + 'avg_time_to_throw'), row.get(pre + 'dropbacks'))
    return out


REC_SUM = ['targets', 'receptions', 'yards', 'touchdowns', 'drops', 'contested_targets',
           'contested_receptions', 'yards_after_catch', 'avoided_tackles', 'first_downs',
           'slot_snaps', 'wide_snaps', 'inline_snaps', 'pass_blocks', 'pass_plays']


def agg_receiving(yr, only=None):
    facet = 'receiving' if weekly_weeks('receiving', yr) else 'receiving_summary'
    out = {}
    for wk, pid, row in weekly(facet, yr, only):
        a = out.setdefault(pid, Acc())
        touch(a, wk, row)
        # 2026 file: routes_pff = PFF's targeted-table routes, routes = pass-route
        # snaps for everyone (the zero-target rows only have the latter)
        rt = fnum(row.get('routes_pff'))
        if rt is None:
            rt = fnum(row.get('routes')) or 0.0
        a.s['routes'] += rt
        a.wk_routes[wk] = a.wk_routes.get(wk, 0.0) + rt
        for c in REC_SUM:
            a.add(c, row.get(c))
        a.addw('adot', row.get('avg_depth_of_target'), row.get('targets'))
        a.addw('grd', row.get('grades_pass_route'), rt)
        a.addw('tqbr', row.get('targeted_qb_rating'), row.get('targets'))
    return out


RUSH_SUM = ['attempts', 'yards', 'touchdowns', 'yards_after_contact', 'elu_rush_mtf',
            'explosive', 'breakaway_yards', 'gap_attempts', 'zone_attempts', 'routes',
            'targets', 'receptions', 'rec_yards', 'run_plays']


def agg_rushing(yr, only=None):
    out = {}
    for wk, pid, row in weekly('rushing_summary', yr, only):
        a = out.setdefault(pid, Acc())
        touch(a, wk, row)
        for c in RUSH_SUM:
            a.add(c, row.get(c))
        a.addw('rgr', row.get('grades_run'), row.get('attempts'))
        a.addw('elu', row.get('elusive_rating'), row.get('attempts'))
        a.addw('pbg', row.get('grades_pass_block'), row.get('run_plays'))
        a.addw('recg', row.get('grades_pass_route'), row.get('routes'))
    return out


def agg_facet(facet, yr, cols, only=None):
    out = {}
    for wk, pid, row in weekly(facet, yr, only):
        a = out.setdefault(pid, Acc())
        touch(a, wk, row)
        for c in cols:
            a.add(c, row.get(c))
    return out


# ---------------------------------------------------------------- nflverse
PBP_ID = ['passer_player_id', 'rusher_player_id', 'receiver_player_id', 'fumbled_1_player_id']
PBP_FLAG = ['pass', 'rush_attempt', 'pass_attempt', 'qb_dropback', 'qb_spike', 'qb_kneel',
            'qb_scramble', 'sack', 'complete_pass', 'interception', 'pass_touchdown',
            'rush_touchdown', 'fumble_lost', 'two_point_attempt', 'first_down_rush', 'success',
            'passing_yards', 'rushing_yards', 'receiving_yards', 'yards_gained']
PBP_NUM = ['air_yards', 'yardline_100', 'epa', 'qb_epa', 'cpoe']
PBP_COLS = ['season_type', 'week', 'posteam'] + PBP_ID + PBP_FLAG + PBP_NUM


def load_pbp(yr):
    p = os.path.join(CACHE, f'play_by_play_{yr}.csv.gz')
    if not os.path.exists(p):
        print(f'  {yr}: no pbp cache - nflverse columns empty')
        return None
    hdr = set(pd.read_csv(p, nrows=0).columns)
    df = pd.read_csv(p, usecols=[c for c in PBP_COLS if c in hdr], low_memory=False)
    df = df[df.season_type == 'REG'].copy()
    for c in PBP_COLS:
        if c not in df.columns:
            df[c] = None if c in PBP_ID else (float('nan') if c in PBP_NUM else 0)
    for c in PBP_FLAG:
        df[c] = df[c].fillna(0)
    df['posteam'] = df.posteam.map(lambda t: TEAM_FIX.get(t, t) if isinstance(t, str) else t)
    df['week'] = df.week.astype(int)
    return df


def pbp_agg(df):
    """P[gsis][stat] season sums, T[(team, wk)][stat] team-week totals,
    PT[(gsis, team)][stat] a player's volume while on that team."""
    P = collections.defaultdict(lambda: collections.defaultdict(float))
    T = collections.defaultdict(lambda: collections.defaultdict(float))
    PT = collections.defaultdict(lambda: collections.defaultdict(float))

    def put(series, key):
        for pid, v in series.items():
            if pd.notna(v):
                P[pid][key] += float(v)

    def put_team(series, key):
        for (tm, wk), v in series.items():
            T[(tm, int(wk))][key] += float(v)

    def put_pt(series, key):
        for (pid, tm), v in series.items():
            if pd.notna(v):
                PT[(pid, tm)][key] += float(v)

    x = df[df.two_point_attempt != 1]

    tg = x[x.receiver_player_id.notna()]
    g = tg.groupby('receiver_player_id')
    put(g.size(), 'tgt'); put(g.air_yards.sum(), 'ay'); put(g.complete_pass.sum(), 'rec')
    put(g.receiving_yards.sum(), 'recyds'); put(g.pass_touchdown.sum(), 'rectd'); put(g.epa.sum(), 'tgtepa')
    put(tg[tg.yardline_100 <= 20].groupby('receiver_player_id').size(), 'rz')
    put(tg[tg.air_yards >= tg.yardline_100].groupby('receiver_player_id').size(), 'ez')
    gt = tg.groupby(['posteam', 'week'])
    put_team(gt.size(), 'tgt'); put_team(gt.air_yards.sum(), 'ay')
    gp = tg.groupby(['receiver_player_id', 'posteam'])
    put_pt(gp.size(), 'tgt'); put_pt(gp.air_yards.sum(), 'ay')

    ru = x[(x.rush_attempt == 1) & x.rusher_player_id.notna()]
    g = ru.groupby('rusher_player_id')
    put(g.rushing_yards.sum(), 'ruyds'); put(g.rush_touchdown.sum(), 'rutd'); put(g.qb_scramble.sum(), 'scr')
    car = ru[(ru.qb_scramble != 1) & (ru.qb_kneel != 1)]
    g = car.groupby('rusher_player_id')
    put(g.size(), 'car'); put(g.epa.sum(), 'ruepa'); put(g.success.sum(), 'rusucc'); put(g.first_down_rush.sum(), 'rufd')
    i10 = car[car.yardline_100 <= 10]
    put(i10.groupby('rusher_player_id').size(), 'i10')
    put(car[car.yardline_100 <= 5].groupby('rusher_player_id').size(), 'i5')
    put_team(car.groupby(['posteam', 'week']).size(), 'car')
    put_team(i10.groupby(['posteam', 'week']).size(), 'i10')
    put_pt(car.groupby(['rusher_player_id', 'posteam']).size(), 'car')
    put_pt(i10.groupby(['rusher_player_id', 'posteam']).size(), 'i10')

    pa = x[(x.pass_attempt == 1) & (x.sack != 1) & x.passer_player_id.notna()]
    g = pa.groupby('passer_player_id')
    put(g.cpoe.sum(), 'cpoe_s'); put(g.cpoe.count(), 'cpoe_n')
    put(g.passing_yards.sum(), 'pyds'); put(g.pass_touchdown.sum(), 'ptd'); put(g.interception.sum(), 'int')
    put(pa[pa.air_yards >= 20].groupby('passer_player_id').size(), 'deep'); put(g.air_yards.count(), 'airn')
    sk = x[(x.sack == 1) & x.passer_player_id.notna()]
    put(sk.groupby('passer_player_id').yards_gained.sum(), 'skyds')
    qd = x[x.qb_dropback == 1].copy()
    qd['qb'] = qd.passer_player_id.fillna(qd.rusher_player_id)
    g = qd[qd.qb.notna()].groupby('qb')
    put(g.qb_epa.sum(), 'dbepa'); put(g.qb_epa.count(), 'dbn')

    fl = df[(df.fumble_lost == 1) & df.fumbled_1_player_id.notna()]
    put(fl.groupby('fumbled_1_player_id').size(), 'fl')
    # team dropbacks = pull_route_pct.dropbacks(): pass flag incl. penalty-nullified
    # pass plays, 2-pt tries kept, spikes out (the RT% denominator)
    db = df[((df.qb_dropback == 1) | (df['pass'] == 1)) & (df.qb_spike != 1) & df.posteam.notna()]
    put_team(db.groupby(['posteam', 'week']).size(), 'db')
    return P, T, PT


def half_ppr(p):
    return (p['pyds'] * 0.04 + p['ptd'] * 4 - p['int'] * 2 + p['ruyds'] * 0.1 + p['rutd'] * 6 +
            p['rec'] * 0.5 + p['recyds'] * 0.1 + p['rectd'] * 6 - p['fl'] * 2)


def load_snaps(yr):
    cols = ['game_type', 'week', 'pfr_player_id', 'team', 'offense_snaps', 'offense_pct']
    df = None
    if yr == YEARS[-1]:
        # in-season nflverse updates nightly; the parquet cache is a one-off pull
        try:
            r = requests.get(SNAP_URL.format(yr=yr), timeout=60)
            if r.status_code == 200:
                df = pd.read_csv(io.BytesIO(r.content), usecols=cols)
        except Exception as e:  # noqa: BLE001
            print(f'  {yr}: live snap counts unavailable ({e}) - using cache')
    if df is None:
        p = os.path.join(CACHE, f'snap_counts_{yr}.parquet')
        if not os.path.exists(p):
            return {}
        df = pd.read_parquet(p, columns=cols)
    df = df[(df.game_type == 'REG') & (df.offense_snaps > 0)]
    out = collections.defaultdict(dict)
    for r in df.itertuples(index=False):
        out[r.pfr_player_id][int(r.week)] = (team(r.team), float(r.offense_snaps), float(r.offense_pct))
    return out


def crosswalk():
    df = pd.read_csv(os.path.join(CACHE, 'players.csv'),
                     usecols=['gsis_id', 'display_name', 'pfr_id', 'pff_id', 'position', 'latest_team'], low_memory=False)
    by_pff, by_name = {}, collections.defaultdict(list)
    for r in df.itertuples(index=False):
        ids = {'gsis': r.gsis_id if isinstance(r.gsis_id, str) else None,
               'pfr': r.pfr_id if isinstance(r.pfr_id, str) else None}
        if pd.notna(r.pff_id):
            by_pff[str(int(r.pff_id))] = ids
        if r.position in ('QB', 'RB', 'FB', 'WR', 'TE') and isinstance(r.display_name, str):
            for v in norm_variants(r.display_name):
                by_name[v].append((ids, team(r.latest_team if isinstance(r.latest_team, str) else '')))
    return by_pff, by_name


def ids_for(pid, name, tm, xw):
    by_pff, by_name = xw
    if pid in by_pff:
        return by_pff[pid]
    for v in norm_variants(name):
        cands = {c[0]['gsis']: c for c in by_name.get(v, []) if c[0]['gsis']}
        if len(cands) == 1:
            return next(iter(cands.values()))[0]
        hit = [c for c in cands.values() if c[1] == tm]
        if len(hit) == 1:
            return hit[0][0]
    return {}


# ---------------------------------------------------------------- build
def build_year(yr, xw, dlookup):
    weeks = set()
    for fac in ('passing_pressure', 'rushing_summary', 'receiving', 'receiving_summary'):
        weeks.update(weekly_weeks(fac, yr))
    if not weeks:
        print(f'{yr}: no PFF weekly files - skipped')
        return
    wks = sorted(weeks)
    pbp = load_pbp(yr)      # loaded once, sliced per week
    snaps = load_snaps(yr)
    build_table(yr, xw, dlookup, pbp, snaps, wks[-1], wks=wks)
    written = sum(build_table(yr, xw, dlookup, pbp, snaps, w, week=w) for w in wks)
    print(f'  {yr}: {len(wks)} week files ({written} written)')


def build_table(yr, xw, dlookup, pbp, snaps, thru, week=None, wks=None):
    """One table set -> data/adv_stats_<yr>.js (week=None: whole season) or
    data/adv_stats_<yr>_w<week>.js (that week only). True when the file changed."""
    qb = agg_passing(yr, week)
    rec = agg_receiving(yr, week)
    rush = agg_rushing(yr, week)
    sch = agg_facet('receiving_scheme', yr, ['man_routes', 'man_targets', 'man_yards', 'zone_routes', 'zone_targets', 'zone_yards'], week)
    con = agg_facet('receiving_concept', yr, ['slot_routes', 'slot_yards', 'screen_targets', 'base_targets'], week)
    dep = agg_facet('receiving_depth', yr, ['deep_targets', 'deep_receptions', 'deep_yards', 'medium_yards', 'short_yards',
                                           'behind_los_yards', 'behind_los_targets', 'base_targets'], week)
    # PFF season CSVs are full-season numbers - a week table uses the weekly facets only
    rec_s = season_csv('receiving', yr) if week is None else {}
    rush_s = season_csv('rushing', yr) if week is None else {}
    if week is not None:
        pbp = pbp[pbp.week == week] if pbp is not None else None
        snaps = {k: {w: v for w, v in d.items() if w == week} for k, d in snaps.items()}
        snaps = {k: d for k, d in snaps.items() if d}
    P, T, PT = pbp_agg(pbp) if pbp is not None and len(pbp) else ({}, {}, {})
    empty = collections.defaultdict(float)
    stats = collections.Counter()

    def pos_of(pid):
        c = collections.Counter()
        for acc in (qb.get(pid), rec.get(pid), rush.get(pid)):
            if acc:
                c.update(acc.pos)
        for r in (rec_s.get(pid), rush_s.get(pid)):
            if r and (r.get('position') or '').strip():
                c[r['position'].strip()] += 3
        top = c.most_common(1)
        return POS_MAP.get(top[0][0]) if top else None

    def ctx(pid, accs, srows):
        names = collections.Counter()
        wk_team = {}
        for a in accs:
            if a:
                names.update(a.names)
                wk_team.update(a.weeks)
        for r in srows:
            if r and r.get('player'):
                names[r['player'].strip()] += 1
        name = names.most_common(1)[0][0] if names else '?'
        last_tm = wk_team[max(wk_team)] if wk_team else next((team(r.get('team_name')) for r in srows if r), '')
        ids = ids_for(pid, name, last_tm, xw)
        stats['gsis' if ids.get('gsis') else 'no_gsis'] += 1
        sn = snaps.get(ids.get('pfr')) if ids.get('pfr') else None
        snp = None
        if sn:
            stats['snaps'] += 1
            # snap weeks win; PFF weeks fill any week the snap file doesn't have yet
            tw = dict(wk_team)
            tw.update({wk: v[0] for wk, v in sn.items()})
            games = len(tw)
            tsnaps = sum(v[1] / v[2] for v in sn.values() if v[2] > 0)
            snp = div(sum(v[1] for v in sn.values()), tsnaps, 100)
        else:
            tw = wk_team
            games = max([len(wk_team)] + [int(fnum(r.get('player_game_count')) or 0) for r in srows if r])
        tm = tw[max(tw)] if tw else last_tm
        p = P[ids['gsis']] if ids.get('gsis') and ids['gsis'] in P else empty

        def tt(key):
            return sum(T[(t, wk)].get(key, 0.0) for wk, t in tw.items() if (t, wk) in T)

        disp = PFF_NAME_FIX.get(name, name)
        site = next((dlookup[v] for v in norm_variants(disp) if v in dlookup), None)
        return {'n': site or disp, 'on': 1 if site else 0, 'tm': tm, 'g': games, 'snp': snp,
                'p': p, 'tt': tt, 'fpt': rnd(half_ppr(p)) if ids.get('gsis') else None,
                'x': PT.get((ids['gsis'], tm), {}) if ids.get('gsis') else {}}

    rows = {'QB': [], 'RB': [], 'WR': [], 'TE': []}
    for pid in set(qb) | set(rec) | set(rush) | set(rec_s) | set(rush_s):
        pos = pos_of(pid)
        if pos == 'QB':
            a = qb.get(pid)
            if not a or a.s['dropbacks'] < MIN_FLOOR['QB']:
                continue
            s = a.s
            c = ctx(pid, [a, rush.get(pid)], [])
            p = c['p']
            att, sk, db = s['attempts'], s['sacks'], s['dropbacks']
            ns = s['passing_snaps'] - sk - s['scrambles']
            anya = div(s['yards'] + 20 * s['touchdowns'] - 45 * s['interceptions'] + p['skyds'], att + sk, 1, 2)
            rows['QB'].append([
                c['n'], c['on'], c['tm'], c['g'], c['fpt'], int(db), int(att),
                div(s['completions'], att, 100), div(s['yards'], att, 1, 2), anya,
                int(s['touchdowns']), int(s['interceptions']),
                div(p['cpoe_s'], p['cpoe_n'], 1, 1), div(p['dbepa'], p['dbn'], 1, 3),
                rnd(a.avg('grd')), div(s['completions'] + s['drops'], s['aimed_passes'], 100),
                rnd(a.avg('adot')), rnd(a.avg('ttt'), 2), div(p['deep'], p['airn'], 100),
                div(s['big_time_throws'], ns, 100), div(s['turnover_worthy_plays'], s['passing_snaps'], 100),
                div(s['touchdowns'], att, 100), div(s['interceptions'], att, 100),
                div(s['p_dropbacks'], db, 100), div(sk, s['def_gen_pressures'], 100), div(sk, db, 100),
                rnd(a.avg('cgr')), div(s['c_completions'] + s['c_drops'], s['c_aimed_passes'], 100),
                rnd(a.avg('pgr')), div(s['p_completions'] + s['p_drops'], s['p_aimed_passes'], 100),
                div(s['p_yards'], s['p_attempts'], 1, 2),
                div(s['b_dropbacks'], db, 100), rnd(a.avg('bgr')), div(s['b_yards'], s['b_attempts'], 1, 2),
                int(p['car'] + p['scr']), int(round(p['ruyds'])), int(p['rutd']), int(p['scr']),
            ])
        elif pos == 'RB':
            rw, rs = rush.get(pid), rush_s.get(pid)
            cw, cs = rec.get(pid), rec_s.get(pid)
            ru = rw.s if rw else empty
            # receiving side: season table > weekly receiving > rushing tables
            if cs:
                rts, tgt, recs, ryd = (fnum(cs.get(k)) or 0 for k in ('routes', 'targets', 'receptions', 'yards'))
                recg = fnum(cs.get('grades_pass_route'))
            elif cw:
                rts, tgt, recs, ryd = cw.s['routes'], cw.s['targets'], cw.s['receptions'], cw.s['yards']
                recg = cw.avg('grd')
            elif rs:
                rts, tgt, recs = (fnum(rs.get(k)) or 0 for k in ('routes', 'targets', 'receptions'))
                ryd = None
                recg = fnum(rs.get('grades_pass_route'))
            else:
                rts, tgt, recs, ryd = ru['routes'], ru['targets'], ru['receptions'], ru['rec_yards']
                recg = rw.avg('recg') if rw else None
            att = ru['attempts'] or (fnum(rs.get('attempts')) if rs else 0) or 0
            if att + tgt < MIN_FLOOR['RB']:
                continue
            c = ctx(pid, [rw, cw], [rs, cs])
            p = c['p']
            if ryd is None:
                ryd = p['recyds']
            yds = ru['yards'] if rw else ((fnum(rs.get('yards')) or 0) if rs else 0)
            rgr = fnum(rs.get('grades_run')) if rs else (rw.avg('rgr') if rw else None)
            elu = fnum(rs.get('elusive_rating')) if rs else (rw.avg('elu') if rw else None)
            pbg = fnum(rs.get('grades_pass_block')) if rs else (rw.avg('pbg') if rw else None)
            mtf = ru['elu_rush_mtf'] if ru.get('elu_rush_mtf') is not None else None
            rows['RB'].append([
                c['n'], c['on'], c['tm'], c['g'], c['snp'], c['fpt'], int(att), int(tgt),
                int(att + recs), int(round(yds + (ryd or 0))), int(p['rutd'] + p['rectd']),
                div(p['car'], c['tt']('car'), 100), div(p['tgt'], c['tt']('tgt'), 100),
                div(min(rts, c['tt']('db')) if c['tt']('db') else rts, c['tt']('db'), 100),
                int(p['i5']), div(p['i10'], c['tt']('i10'), 100), int(p['rec'] + p['i10']),
                div(yds, att, 1, 2), div(ru['yards_after_contact'], att, 1, 2), div(mtf, att, 1, 2),
                rnd(elu), div(ru['breakaway_yards'], yds, 100), div(ru['explosive'], att, 100),
                div(p['rufd'], p['car'], 100), div(p['rusucc'], p['car'], 100), div(p['ruepa'], p['car'], 1, 3),
                rnd(rgr), div(ru['gap_attempts'], ru['gap_attempts'] + ru['zone_attempts'], 100),
                int(rts), div(tgt, rts, 1, 2), div(ryd, rts, 1, 2), rnd(recg), rnd(pbg),
                int(c['x'].get('tgt', 0)), int(c['x'].get('car', 0)), int(c['x'].get('i10', 0)),
            ])
        elif pos in ('WR', 'TE'):
            cw, cs = rec.get(pid), rec_s.get(pid)
            if not cw and not cs:
                continue   # WR/TE with rushing rows only (jet sweeps, no target)
            w = cw.s if cw else empty
            if cs:
                rts, tgt, recs, yds, tds, fd, avt = (fnum(cs.get(k)) or 0 for k in
                                                     ('routes', 'targets', 'receptions', 'yards', 'touchdowns', 'first_downs', 'avoided_tackles'))
                grd, adot = fnum(cs.get('grades_pass_route')), fnum(cs.get('avg_depth_of_target'))
                slot, wide, inl = (fnum(cs.get(k)) for k in ('slot_rate', 'wide_rate', 'inline_rate'))
                yac, cc, drp, ctch = (fnum(cs.get(k)) for k in ('yards_after_catch_per_reception', 'contested_catch_rate', 'drop_rate', 'caught_percent'))
            else:
                rts, tgt, recs, yds, tds, fd, avt = (w['routes'], w['targets'], w['receptions'], w['yards'],
                                                     w['touchdowns'], w['first_downs'], w['avoided_tackles'])
                grd, adot = cw.avg('grd'), cw.avg('adot')
                al = w['slot_snaps'] + w['wide_snaps'] + w['inline_snaps']
                slot, wide, inl = div(w['slot_snaps'], al, 100), div(w['wide_snaps'], al, 100), div(w['inline_snaps'], al, 100)
                yac = div(w['yards_after_catch'], recs, 1, 1)
                cc = div(w['contested_receptions'], w['contested_targets'], 100)
                drp = div(w['drops'], w['drops'] + recs, 100)
                ctch = div(recs, tgt, 100)
            if rts < MIN_FLOOR[pos]:
                continue
            ch, cn, cd = sch.get(pid), con.get(pid), dep.get(pid)
            c = ctx(pid, [cw, ch, cn, cd], [cs])
            p = c['p']
            tt_db, tt_tgt, tt_ay = c['tt']('db'), c['tt']('tgt'), c['tt']('ay')
            tsh = div(p['tgt'], tt_tgt, 1, 4)
            ays = div(p['ay'], tt_ay, 1, 4) if tt_ay > 0 else None
            wk_r = cw.wk_routes if cw else {}

            def scale(facet_acc):
                # routes the facet saw (weeks it lists this player) -> season routes
                if not facet_acc:
                    return None
                seen = sum(wk_r.get(wk, 0.0) for wk in facet_acc.weeks)
                return rts / seen if seen else None

            ms, cs_ = scale(ch), scale(cn)
            m = ch.s if ch else empty
            k = cn.s if cn else empty
            d = cd.s if cd else empty
            dy = d['deep_yards'] + d['medium_yards'] + d['short_yards'] + d['behind_los_yards']
            rows[pos].append([
                c['n'], c['on'], c['tm'], c['g'], c['snp'], c['fpt'], int(rts), int(tgt),
                int(round(yds)), int(tds),
                div(min(rts, tt_db), tt_db, 100) if tt_db else None,
                rnd(tsh * 100) if tsh is not None else None, rnd(ays * 100) if ays is not None else None,
                rnd(1.5 * tsh + 0.7 * ays, 2) if tsh is not None and ays is not None else None,
                div(tgt, rts, 1, 2), int(p['rz']), int(p['ez']),
                rnd(slot), rnd(wide), rnd(inl), div(w['pass_blocks'], w['pass_plays'], 100),
                div(yds, rts, 1, 2), rnd(grd), rnd(adot), div(p['recyds'], p['ay'], 1, 2) if p['ay'] > 0 else None,
                rnd(yac), div(avt, recs, 1, 2), div(fd, rts, 1, 3), rnd(ctch), rnd(drp), rnd(cc),
                div(w['contested_targets'], w['targets'], 100), rnd(cw.avg('tqbr')) if cw else None,
                div(p['tgtepa'], p['tgt'], 1, 2),
                div(m['man_yards'], m['man_routes'] * ms, 1, 2) if ms else None,
                div(m['zone_yards'], m['zone_routes'] * ms, 1, 2) if ms else None,
                div(m['man_targets'], m['man_routes'] * ms, 1, 2) if ms else None,
                div(m['zone_targets'], m['zone_routes'] * ms, 1, 2) if ms else None,
                div(k['slot_yards'], k['slot_routes'] * cs_, 1, 2) if cs_ else None,
                div(k['screen_targets'], k['base_targets'], 100),
                div(d['deep_targets'], d['base_targets'], 100), div(d['deep_yards'], dy, 100) if dy > 0 else None,
                div(d['deep_receptions'], d['deep_targets'], 100), div(d['behind_los_targets'], d['base_targets'], 100),
                int(c['x'].get('tgt', 0)), int(round(c['x'].get('ay', 0))),
            ])

    fields = {'QB': QB_F, 'RB': RB_F, 'WR': REC_F, 'TE': REC_F}
    # team totals (season, or that week) for the page's team view: [targets, carries, air yards, inside-10 carries, games]
    teams = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0])
    for (tm, wk), v in T.items():
        if not isinstance(tm, str):
            continue
        t = teams[tm]
        t[0] += v.get('tgt', 0.0); t[1] += v.get('car', 0.0); t[2] += v.get('ay', 0.0); t[3] += v.get('i10', 0.0)
        if v.get('db', 0.0) > 0:
            t[4] += 1
    payload = {'yr': yr, 'thru': thru}
    if week is not None:
        payload['wk'] = week
    if wks:
        payload['wks'] = wks
    payload['teams'] = {tm: [int(round(x)) for x in t] for tm, t in sorted(teams.items())}
    for pos in ('QB', 'RB', 'WR', 'TE'):
        f = fields[pos]
        for r in rows[pos]:
            assert len(r) == len(f), (pos, len(r), len(f), r[0])
        fi = f.index('fpt')
        rows[pos].sort(key=lambda r: -(r[fi] if r[fi] is not None else -99))
        payload[pos] = {'f': f, 'r': rows[pos]}
    body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    if week is None:
        out = os.path.join(ROOT, 'data', f'adv_stats_{yr}.js')
        text = f'window.ADV_STATS=window.ADV_STATS||{{}};window.ADV_STATS[{yr}]={body};\n'
    else:
        out = os.path.join(ROOT, 'data', f'adv_stats_{yr}_w{week}.js')
        text = f'window.ADV_STATS=window.ADV_STATS||{{}};window.ADV_STATS["{yr}-w{week}"]={body};\n'
    old = open(out, encoding='utf-8').read() if os.path.exists(out) else None
    if old != text:
        with open(out, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
    if week is None:
        print(f'{yr}: thru W{thru}  QB {len(rows["QB"])}  RB {len(rows["RB"])}  WR {len(rows["WR"])}  TE {len(rows["TE"])}'
              f'  | ids {stats["gsis"]}/{stats["gsis"] + stats["no_gsis"]}  snaps {stats["snaps"]}'
              f'  | {len(text) // 1024} KB {"(unchanged)" if old == text else "written"}')
    return old != text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', default=None, help='comma list, default 2019-2026')
    args = ap.parse_args()
    years = [int(y) for y in args.years.split(',')] if args.years else YEARS
    xw = crosswalk()
    dlookup = load_d_names()
    for yr in years:
        build_year(yr, xw, dlookup)


if __name__ == '__main__':
    main()
