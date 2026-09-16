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
import numpy as np
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
# Kept at 1 so a team filter shows the whole position room (shares add up) and a
# week range rebuilt from week files keeps the same players as a direct build.
MIN_FLOOR = {'QB': 1, 'RB': 1, 'WR': 1, 'TE': 1}

# Counting stats are SEASON TOTALS (fpt, db, att, ra, ry, tch, scy, hvt, rts, yds,
# td, rz ...); the page's Per game / Totals toggle divides by g client-side.
# Situational usage (RB + WR/TE tables). Displayed: opportunity shares (edo d3o d3lo syo, %),
# 4th-down opportunities (d4c), on-field snap shares in the situation (eds d3s d3ls sys, %,
# participation seasons only). Hidden: player opps o*, team opps t* over games played, player
# on-field plays s*, team plays n*, and x* = opps while on the listed team (team view).
SIT_F = ['edo', 'd3o', 'd3lo', 'syo', 'd4c', 'eds', 'd3s', 'd3ls', 'sys',
         'oed', 'od3', 'od3l', 'osy', 'ted', 'td3', 'td3l', 'tsy',
         'sed', 'sd3', 'sd3l', 'ssy', 'ned', 'nd3', 'nd3l', 'nsy',
         'xed', 'xd3', 'xd3l', 'xsy']


def sit_values(c, p):
    """The SIT_F values for one RB / WR / TE row (c = ctx(), p = its pbp dict)."""
    tt, xx = c['tt'], c['x']
    if c['fpt'] is None:      # no play-by-play identity: nothing situational either
        return [None] * len(SIT_F)
    return [div(p['oed'], tt('oed'), 100), div(p['od3'], tt('od3'), 100), div(p['od3l'], tt('od3l'), 100), div(p['osy'], tt('osy'), 100),
            int(p['od4']),
            div(p['sed'], tt('ned'), 100), div(p['sd3'], tt('nd3'), 100), div(p['sd3l'], tt('nd3l'), 100), div(p['ssy'], tt('nsy'), 100),
            int(p['oed']), int(p['od3']), int(p['od3l']), int(p['osy']), int(tt('oed')), int(tt('od3')), int(tt('od3l')), int(tt('osy')),
            int(p['sed']), int(p['sd3']), int(p['sd3l']), int(p['ssy']), int(tt('ned')), int(tt('nd3')), int(tt('nd3l')), int(tt('nsy')),
            int(xx.get('oed', 0)), int(xx.get('od3', 0)), int(xx.get('od3l', 0)), int(xx.get('osy', 0))]


QB_F = ['n', 'on', 'tm', 'g', 'fpt', 'db', 'att', 'cmpp', 'ypa', 'anya', 'td', 'int',
        'cpoe', 'epa', 'grd', 'acc', 'adot', 'ttt', 'deep', 'btt', 'twp', 'tdp', 'intp',
        'prs', 'p2s', 'skp', 'cgr', 'cacc', 'pgr', 'pacc', 'pypa', 'blz', 'bgr', 'bypa',
        'ra', 'ry', 'rtd', 'scr',
        'sk', 'cpn', 'dbn', 'aim', 'airn', 'ns', 'psn', 'dgp', 'pdb', 'cdb', 'caim', 'paim', 'patt', 'bdb', 'batt',
        'xfpt']
# xfpt = season expected half-PPR points (xFP) - displayed, appended last so the page reads it by key
# Trailing short keys on every table are NOT displayed: they are the denominators the
# page uses to rebuild a multi-week range from week files (each rate re-weighted by its
# own base - see _ADV_AGG in app.js). Keep both sides in sync.
RB_F = ['n', 'on', 'tm', 'g', 'snp', 'fpt', 'att', 'tgt', 'tch', 'scy', 'tds',
        'car', 'tsh', 'rtp', 'i5', 'i10s', 'hvt',
        'ypc', 'yco', 'mtf', 'elu', 'bay', 'exp', 'fdp', 'suc', 'repa', 'rgr', 'gap',
        'rts', 'tprr', 'yprr', 'recg', 'pbg',
        'xt', 'xc', 'xi',
        'tsn', 'ttc', 'tmt', 'tmd', 'tmi', 'rsy', 'pcar', 'gz', 'rpl',
        'xfpt', 'xrec'] + SIT_F
# SIT_F (defined below the tables) = situational usage: displayed shares + hidden counts
# xrec = expected receptions (hidden) so the page can re-score xFP as PPR / STD; actual
# receptions come from tch - att (RB) or the hidden rec field (WR/TE)
# x* (not displayed) = raw pbp targets / carries / inside-10 carries / air yards while on
# the listed team; with payload `teams` they give the page's team-view season shares
REC_F = ['n', 'on', 'tm', 'g', 'snp', 'fpt', 'rts', 'tgt', 'yds', 'tds',
         'rtp', 'tsh', 'ays', 'wopr', 'tprr', 'rz', 'ez', 'slot', 'wide', 'inl', 'pbr',
         'yprr', 'grd', 'adot', 'racr', 'yac', 'mtfr', 'fdr', 'ctch', 'drp', 'cc', 'ctg',
         'tqbr', 'epat',
         'myprr', 'zyprr', 'mtprr', 'ztprr', 'slyprr', 'scr', 'deep', 'dyd', 'dctch', 'blos',
         'xt', 'xa',
         'tsn', 'tmd', 'tmt', 'tma', 'al', 'ppl', 'rec', 'dr', 'ct', 'pry', 'pay', 'mr', 'zr', 'slr', 'cbt', 'dbt', 'dy', 'dtg',
         'xfpt', 'xrec'] + SIT_F
# TEAM table: one row per team (n = team name, tm = code). Offense, tendency and defense from
# nflverse pbp; protection / pressure / man coverage from PFF (defense = what opponents saw).
TM_F = ['n', 'on', 'tm', 'g',
        'pl', 'pa', 'rua', 'npace', 'sg', 'nh',
        'pr', 'npr', 'edpr', 'proe', 'rroe',
        'epa', 'dbepa', 'ruepa', 'sr', 'dbsr', 'rusr', 'xpp', 'xrp', 'adot', 'yac', 'tdc', 'rztd', 'tdd',
        'skp', 'prsa', 'blzf', 'ttt', 'manf',
        'depa', 'ddbepa', 'druepa', 'dsr', 'dxp', 'dskp', 'dprs', 'dblz', 'dman', 'dtdc', 'drztd',
        'pcn', 'npl', 'edn', 'pon', 'ayn', 'cmp', 'tdn', 'rzt', 'drv', 'pdbt', 'tttw', 'mzr',
        'dpl', 'dpa', 'drua', 'dpdbt', 'dmzr', 'dtdn', 'drzt']
TEAM_NAMES = {
    'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens', 'BUF': 'Buffalo Bills',
    'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears', 'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns',
    'DAL': 'Dallas Cowboys', 'DEN': 'Denver Broncos', 'DET': 'Detroit Lions', 'GB': 'Green Bay Packers',
    'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars', 'KC': 'Kansas City Chiefs',
    'LAC': 'Los Angeles Chargers', 'LAR': 'Los Angeles Rams', 'LV': 'Las Vegas Raiders', 'MIA': 'Miami Dolphins',
    'MIN': 'Minnesota Vikings', 'NE': 'New England Patriots', 'NO': 'New Orleans Saints', 'NYG': 'New York Giants',
    'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers', 'SEA': 'Seattle Seahawks',
    'SF': 'San Francisco 49ers', 'TB': 'Tampa Bay Buccaneers', 'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders'}


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
    __slots__ = ('s', 'w', 'weeks', 'wk_routes', 'wk_rec', 'names', 'pos')

    def __init__(self):
        self.s = collections.defaultdict(float)             # summed counts
        self.w = collections.defaultdict(lambda: [0.0, 0.0])  # weighted avg [sum v*wt, sum wt]
        self.weeks = {}                                     # wk -> team
        self.wk_routes = {}                                 # wk -> routes (receiving only)
        self.wk_rec = {}                                    # wk -> [routes, targets, receptions, rec yards]
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
    """Rows of a PFF weekly facet; only=<set of weeks> reads just those weeks' files."""
    for wk in weekly_weeks(facet, yr):
        if only is not None and wk not in only:
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
        line = a.wk_rec.setdefault(wk, [0.0, 0.0, 0.0, 0.0])
        for i, v in enumerate((rt, row.get('targets'), row.get('receptions'), row.get('yards'))):
            line[i] += fnum(v) or 0.0
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
        line = a.wk_rec.setdefault(wk, [0.0, 0.0, 0.0, 0.0])
        for i, v in enumerate((row.get('routes'), row.get('targets'), row.get('receptions'), row.get('rec_yards'))):
            line[i] += fnum(v) or 0.0
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
PBP_STR = ['game_id', 'defteam', 'fixed_drive_result']
PBP_FLAG = ['pass', 'rush', 'rush_attempt', 'pass_attempt', 'qb_dropback', 'qb_spike', 'qb_kneel',
            'qb_scramble', 'sack', 'complete_pass', 'interception', 'pass_touchdown',
            'rush_touchdown', 'fumble_lost', 'two_point_attempt', 'first_down_rush', 'success',
            'passing_yards', 'rushing_yards', 'receiving_yards', 'yards_gained',
            'shotgun', 'no_huddle', 'third_down_converted', 'third_down_failed']
PBP_NUM = ['air_yards', 'yardline_100', 'epa', 'qb_epa', 'cpoe', 'xpass', 'pass_oe', 'down', 'wp',
           'half_seconds_remaining', 'game_seconds_remaining', 'fixed_drive', 'yards_after_catch',
           'cp', 'xyac_mean_yardage', 'ydstogo', 'play_id']

# Situational usage (Jack 2026-09-16): opportunities = carries + targets in the situation, from
# pbp for every season; on-field snaps in the situation need nflverse participation, which is
# published after each season (2019-2025 here; the current season fills in post-season).
SIT = {
    'ed': lambda d: d.down <= 2,                            # early downs
    'd3': lambda d: d.down == 3,                            # 3rd down
    'd3l': lambda d: (d.down == 3) & (d.ydstogo >= 7),      # 3rd and long
    'sy': lambda d: (d.down >= 3) & (d.ydstogo <= 2),       # short yardage: 3rd / 4th and <= 2
    'd4': lambda d: d.down == 4,                            # 4th down (opportunities only)
}


def load_onfield(yr):
    """nflverse participation: [nflverse_game_id, play_id, offense_players (GSIS ids ;-joined)]."""
    p = os.path.join(CACHE, f'pbp_participation_{yr}.parquet')
    if not os.path.exists(p):
        return None
    df = pd.read_parquet(p, columns=['nflverse_game_id', 'play_id', 'offense_players'])
    df = df[df.offense_players.notna() & (df.offense_players != '')].copy()
    df['play_id'] = df.play_id.astype('int64')
    return df

# Expected fantasy points (xFP) - the STANDARD opportunity definition, same tables as
# sim_lab/pull_pace_tracker.build_xfp_2026 (the 2026 player-card column): a target is worth
# nflverse catch probability x (air yards + expected YAC) where those per-play models exist,
# else the pooled 2018-25 air-yards bucket tables; carries and touchdowns come from yardline
# tables. Keep these in step with pull_pace_tracker.py.
XFP_AB_BINS = [-0.01, 4.99, 9.99, 14.99, 19.99, 29.99]            # <0, 0-4, 5-9, 10-14, 15-19, 20-29, 30+
XFP_CATCH = [0.837, 0.755, 0.703, 0.589, 0.547, 0.416, 0.302]
XFP_TGT_YDS = [4.87, 5.39, 6.83, 9.00, 11.42, 11.88, 13.46]
XFP_INT = [0.0077, 0.0107, 0.0188, 0.0318, 0.0416, 0.0557, 0.0692]
XTD_REC_BINS = [5, 10, 20, 40, 100]
XTD_REC_NONEZ = [0.264, 0.213, 0.080, 0.030, 0.007]
XTD_REC_EZ = [0.501, 0.384, 0.330, 0.271, 0.232]
XFP_RUSH_BINS = [5, 10, 20, 40]                                   # <=5, 6-10, 11-20, 21-40, 41+
XFP_RUSH_YDS = [1.10, 2.88, 3.82, 4.45, 4.75]
XFP_RUSH_YDS_QB = [1.07, 3.22, 4.05, 4.48, 4.77]
XTD_BINS = [1, 2, 3, 4, 5, 10, 20, 40, 100]
XTD_RUSH = [0.540, 0.379, 0.339, 0.257, 0.215, 0.105, 0.042, 0.011, 0.003]
XFP_QB_RUSH_TD_BINS = [1, 2, 3, 5, 10, 20, 40]
XFP_QB_RUSH_TD = [0.619, 0.302, 0.366, 0.304, 0.201, 0.059, 0.011, 0.001]


def _lut(vals, bins, table):
    """value <= bins[i] -> table[i]; past the last bin -> table[-1] (the scalar loops in
    pull_pace_tracker, vectorised)."""
    idx = np.searchsorted(np.asarray(bins, float), np.asarray(vals, float), side='left')
    return np.asarray(table, float)[np.minimum(idx, len(table) - 1)]
PBP_COLS = ['season_type', 'week', 'posteam'] + PBP_ID + PBP_STR + PBP_FLAG + PBP_NUM


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
            df[c] = None if c in PBP_ID or c in PBP_STR else (float('nan') if c in PBP_NUM else 0)
    for c in PBP_FLAG:
        df[c] = df[c].fillna(0)
    for c in ('posteam', 'defteam'):
        df[c] = df[c].map(lambda t: TEAM_FIX.get(t, t) if isinstance(t, str) else t)
    df['week'] = df.week.astype(int)
    return df


def pbp_agg(df, part=None):
    """P[gsis][stat] season sums, T[(team, wk)][stat] team-week totals,
    PT[(gsis, team)][stat] a player's volume while on that team.
    part = participation rows (load_onfield) for situational snap shares, or None."""
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

    # situational opportunities (carries + targets) per player, team-week and player-team
    opp = pd.concat([
        tg[(tg.pass_attempt == 1) & (tg.sack != 1)][['receiver_player_id', 'posteam', 'week', 'down', 'ydstogo']].rename(columns={'receiver_player_id': 'pid'}),
        car[['rusher_player_id', 'posteam', 'week', 'down', 'ydstogo']].rename(columns={'rusher_player_id': 'pid'}),
    ])
    for key, fn in SIT.items():
        sub = opp[fn(opp)]
        put(sub.groupby('pid').size(), 'o' + key)
        put_team(sub.groupby(['posteam', 'week']).size(), 'o' + key)
        put_pt(sub.groupby(['pid', 'posteam']).size(), 'o' + key)
    # situational snaps: plays the player was on the field for / team plays in the situation
    if part is not None and len(part):
        plays = x[((x['pass'] == 1) | (x.rush == 1)) & (x.qb_kneel != 1) & (x.qb_spike != 1) & x.posteam.notna() & x.play_id.notna()].copy()
        plays['play_id'] = plays.play_id.astype('int64')
        m = plays.merge(part, left_on=['game_id', 'play_id'], right_on=['nflverse_game_id', 'play_id'], how='inner')
        for key, fn in SIT.items():
            if key == 'd4':
                continue
            sub = m[fn(m)]
            put_team(sub.groupby(['posteam', 'week']).size(), 'n' + key)
            ex = sub[['offense_players']].assign(pid=sub.offense_players.str.split(';')).explode('pid')
            ex = ex[ex.pid.notna() & (ex.pid != '')]
            put(ex.groupby('pid').size(), 's' + key)

    # xFP components (tables above). Rush values are kept in both the RB and QB flavour
    # because a rusher's position is only known once the PFF tables are joined.
    tgx = tg[(tg.pass_attempt == 1) & (tg.sack != 1)]
    if len(tgx):
        yl = tgx.yardline_100.fillna(50.0).to_numpy(float)
        ay = tgx.air_yards.fillna(0.0).to_numpy(float)
        b = np.minimum(np.searchsorted(np.asarray(XFP_AB_BINS, float), ay, side='left'), len(XFP_CATCH) - 1)
        xtd = np.where(ay >= yl, _lut(yl, XTD_REC_BINS, XTD_REC_EZ), _lut(yl, XTD_REC_BINS, XTD_REC_NONEZ))
        cp = tgx.cp.to_numpy(float)
        xyac = tgx.xyac_mean_yardage.to_numpy(float)
        model = ~np.isnan(cp) & ~np.isnan(xyac)
        xr = np.where(model, cp, np.asarray(XFP_CATCH)[b])
        xy = np.where(model, np.nan_to_num(cp) * (ay + np.nan_to_num(xyac)), np.asarray(XFP_TGT_YDS)[b])
        tgx = tgx.assign(_xr=xr, _xy=xy, _xtd=xtd, _xint=np.asarray(XFP_INT)[b])
        g = tgx.groupby('receiver_player_id')
        put(g._xr.sum(), 'xrec'); put(g._xy.sum(), 'xrecyd'); put(g._xtd.sum(), 'xrectd')
        gq = tgx[tgx.passer_player_id.notna()].groupby('passer_player_id')
        put(gq._xy.sum(), 'xpyd'); put(gq._xtd.sum(), 'xptd'); put(gq._xint.sum(), 'xint')
    if len(ru):
        ylr = ru.yardline_100.fillna(50.0).to_numpy(float)
        rx = ru.assign(_yrb=_lut(ylr, XFP_RUSH_BINS, XFP_RUSH_YDS), _yqb=_lut(ylr, XFP_RUSH_BINS, XFP_RUSH_YDS_QB),
                       _trb=_lut(ylr, XTD_BINS, XTD_RUSH), _tqb=_lut(ylr, XFP_QB_RUSH_TD_BINS, XFP_QB_RUSH_TD))
        g = rx.groupby('rusher_player_id')
        put(g._yrb.sum(), 'xruyd'); put(g._yqb.sum(), 'xruyd_qb'); put(g._trb.sum(), 'xrutd'); put(g._tqb.sum(), 'xrutd_qb')
    # team dropbacks = pull_route_pct.dropbacks(): pass flag incl. penalty-nullified
    # pass plays, 2-pt tries kept, spikes out (the RT% denominator)
    db = df[((df.qb_dropback == 1) | (df['pass'] == 1)) & (df.qb_spike != 1) & df.posteam.notna()]
    put_team(db.groupby(['posteam', 'week']).size(), 'db')
    return P, T, PT


def half_ppr(p):
    return (p['pyds'] * 0.04 + p['ptd'] * 4 - p['int'] * 2 + p['ruyds'] * 0.1 + p['rutd'] * 6 +
            p['rec'] * 0.5 + p['recyds'] * 0.1 + p['rectd'] * 6 - p['fl'] * 2)


def half_xfp(p, is_qb):
    """Expected half-PPR points from the xFP components, scored like half_ppr above (an
    expected INT costs 2, matching this table's FPTS; the card scores INTs -1)."""
    if is_qb:
        return 0.04 * p['xpyd'] + 4 * p['xptd'] + 0.1 * p['xruyd_qb'] + 6 * p['xrutd_qb'] - 2 * p['xint']
    return 0.5 * p['xrec'] + 0.1 * (p['xrecyd'] + p['xruyd']) + 6 * (p['xrectd'] + p['xrutd'])


def team_rows(yr, pbp, sel):
    """TEAM table rows (TM_F order). pbp is already sliced to the season / week / span.
    Plays = dropbacks (pass flag: incl. sacks + scrambles) + designed runs, 2-pt tries out.
    Neutral = win probability 20-80% outside the last two minutes of each half.
    PROE = mean nflverse pass_oe (pass minus xpass, pct points) on neutral plays; RROE = -PROE.
    Neutral pace = seconds between consecutive snaps of the same drive (gaps 1-60 s)."""
    if pbp is None or not len(pbp):
        return []
    df = pbp[(pbp.two_point_attempt != 1) & pbp.posteam.notna() & pbp.defteam.notna()]
    S = collections.defaultdict(lambda: collections.defaultdict(float))

    def add(side, key, series):
        for tm, v in series.items():
            if isinstance(tm, str) and pd.notna(v):
                S[(side, tm)][key] += float(v)

    plays = df[((df['pass'] == 1) | (df.rush == 1)) & df.epa.notna()].copy()
    plays['neutral'] = (plays.wp >= 0.2) & (plays.wp <= 0.8) & (plays.half_seconds_remaining > 120)
    plays['xp'] = ((plays['pass'] == 1) & (plays.yards_gained >= 20)).astype(int)
    plays['xr'] = ((plays.rush == 1) & (plays.yards_gained >= 10)).astype(int)
    drives = df[df.fixed_drive.notna()]
    for side, col in (('o', 'posteam'), ('d', 'defteam')):
        g = plays.groupby(col)
        add(side, 'pl', g.size()); add(side, 'epa', g.epa.sum()); add(side, 'suc', g.success.sum())
        add(side, 'xp', g.xp.sum()); add(side, 'xr', g.xr.sum())
        gp = plays[plays['pass'] == 1].groupby(col)
        add(side, 'pa', gp.size()); add(side, 'dbepa', gp.epa.sum()); add(side, 'dbsuc', gp.success.sum()); add(side, 'sk', gp.sack.sum())
        gr = plays[plays.rush == 1].groupby(col)
        add(side, 'rua', gr.size()); add(side, 'ruepa', gr.epa.sum()); add(side, 'rusuc', gr.success.sum())
        gt = df.groupby(col)
        add(side, 'tdc', gt.third_down_converted.sum()); add(side, 'tdf', gt.third_down_failed.sum())
        dr = drives.groupby([col, 'game_id', 'fixed_drive']).agg(yl=('yardline_100', 'min'), res=('fixed_drive_result', 'first')).reset_index()
        dr['td'] = (dr.res == 'Touchdown').astype(int)
        dr['rz'] = (dr.yl <= 20).astype(int)
        gd = dr.groupby(col)
        add(side, 'drv', gd.size()); add(side, 'tdd', gd.td.sum()); add(side, 'rzt', gd.rz.sum())
        add(side, 'rztd', dr[dr.rz == 1].groupby(col).td.sum())
    go = plays.groupby('posteam')
    add('o', 'sg', go.shotgun.sum()); add('o', 'nh', go.no_huddle.sum())
    add('o', 'games', df.groupby('posteam').game_id.nunique())
    neu = plays[plays.neutral]
    add('o', 'npl', neu.groupby('posteam').size()); add('o', 'npass', neu.groupby('posteam')['pass'].sum())
    po = neu[neu.pass_oe.notna()]
    add('o', 'pon', po.groupby('posteam').size()); add('o', 'poe', po.groupby('posteam').pass_oe.sum())
    ed = neu[neu.down <= 2]
    add('o', 'edn', ed.groupby('posteam').size()); add('o', 'edp', ed.groupby('posteam')['pass'].sum())
    att = df[(df.pass_attempt == 1) & (df.sack != 1) & df.air_yards.notna()]
    add('o', 'ay', att.groupby('posteam').air_yards.sum()); add('o', 'ayn', att.groupby('posteam').size())
    cm = df[(df.complete_pass == 1) & df.yards_after_catch.notna()]
    add('o', 'yac', cm.groupby('posteam').yards_after_catch.sum()); add('o', 'cmp', cm.groupby('posteam').size())
    pc = plays.sort_values(['game_id', 'fixed_drive', 'game_seconds_remaining'], ascending=[True, True, False]).copy()
    pc['gap'] = pc.groupby(['game_id', 'fixed_drive']).game_seconds_remaining.shift(1) - pc.game_seconds_remaining
    pc = pc[pc.neutral & (pc.gap > 0) & (pc.gap <= 60)]
    add('o', 'pace', pc.groupby('posteam').gap.sum()); add('o', 'pcn', pc.groupby('posteam').size())

    # PFF: offense = its own QBs / receivers; defense = the opponent they faced that week
    opp = {(tm, int(wk)): d for (tm, wk), d in df.groupby(['posteam', 'week']).defteam.first().items()}
    for wk, _pid, row in weekly('passing_pressure', yr, sel):
        tm = team(row.get('team_name'))
        pdb, cdb = fnum(row.get('pressure_dropbacks')) or 0, fnum(row.get('no_pressure_dropbacks')) or 0
        bdb = fnum(row.get('blitz_dropbacks')) or 0
        for side, t in (('o', tm), ('d', opp.get((tm, wk)))):
            if t:
                S[(side, t)]['pdbt'] += pdb + cdb
                S[(side, t)]['ppdb'] += pdb
                S[(side, t)]['pbdb'] += bdb
        for pre, w in (('pressure_', pdb), ('no_pressure_', cdb)):
            v = fnum(row.get(pre + 'avg_time_to_throw'))
            if v is not None and w:
                S[('o', tm)]['ttts'] += v * w
                S[('o', tm)]['tttw'] += w
    for wk, _pid, row in weekly('receiving_scheme', yr, sel):
        tm = team(row.get('team_name'))
        mr, zr = fnum(row.get('man_routes')) or 0, fnum(row.get('zone_routes')) or 0
        for side, t in (('o', tm), ('d', opp.get((tm, wk)))):
            if t:
                S[(side, t)]['man'] += mr
                S[(side, t)]['mzr'] += mr + zr

    rows = []
    for tm in sorted([t for (side, t) in list(S) if side == 'o' and S[(side, t)]['pl'] > 0]):
        o, d = S[('o', tm)], S[('d', tm)]
        tdn, dtdn = o['tdc'] + o['tdf'], d['tdc'] + d['tdf']
        rows.append([
            TEAM_NAMES.get(tm, tm), 0, tm, int(o['games']),
            int(o['pl']), int(o['pa']), int(o['rua']), div(o['pace'], o['pcn'], 1, 1),
            div(o['sg'], o['pl'], 100), div(o['nh'], o['pl'], 100),
            div(o['pa'], o['pl'], 100), div(o['npass'], o['npl'], 100), div(o['edp'], o['edn'], 100),
            div(o['poe'], o['pon'], 1, 1), div(-o['poe'], o['pon'], 1, 1),
            div(o['epa'], o['pl'], 1, 3), div(o['dbepa'], o['pa'], 1, 3), div(o['ruepa'], o['rua'], 1, 3),
            div(o['suc'], o['pl'], 100), div(o['dbsuc'], o['pa'], 100), div(o['rusuc'], o['rua'], 100),
            div(o['xp'], o['pa'], 100), div(o['xr'], o['rua'], 100), div(o['ay'], o['ayn'], 1, 1), div(o['yac'], o['cmp'], 1, 1),
            div(o['tdc'], tdn, 100), div(o['rztd'], o['rzt'], 100), div(o['tdd'], o['drv'], 100),
            div(o['sk'], o['pa'], 100), div(o['ppdb'], o['pdbt'], 100), div(o['pbdb'], o['pdbt'], 100),
            div(o['ttts'], o['tttw'], 1, 2), div(o['man'], o['mzr'], 100),
            div(d['epa'], d['pl'], 1, 3), div(d['dbepa'], d['pa'], 1, 3), div(d['ruepa'], d['rua'], 1, 3),
            div(d['suc'], d['pl'], 100), div(d['xp'] + d['xr'], d['pl'], 100), div(d['sk'], d['pa'], 100),
            div(d['ppdb'], d['pdbt'], 100), div(d['pbdb'], d['pdbt'], 100), div(d['man'], d['mzr'], 100),
            div(d['tdc'], dtdn, 100), div(d['rztd'], d['rzt'], 100),
            int(o['pcn']), int(o['npl']), int(o['edn']), int(o['pon']), int(o['ayn']), int(o['cmp']),
            int(tdn), int(o['rzt']), int(o['drv']), int(o['pdbt']), int(round(o['tttw'])), int(o['mzr']),
            int(d['pl']), int(d['pa']), int(d['rua']), int(d['pdbt']), int(d['mzr']), int(dtdn), int(d['rzt']),
        ])
    return rows


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
    part = load_onfield(yr)
    universe = {}   # pid -> (pos, name, team) of every season-table player
    build_table(yr, xw, dlookup, pbp, snaps, wks[-1], wks=wks, collect=universe, part=part)
    written = sum(build_table(yr, xw, dlookup, pbp, snaps, w, week=w, forced=universe, part=part) for w in wks)
    print(f'  {yr}: {len(wks)} week files ({written} written)')


def build_table(yr, xw, dlookup, pbp, snaps, thru, week=None, wks=None, span=None, out_path=None,
                collect=None, forced=None, part=None):
    """One table set -> data/adv_stats_<yr>.js (whole season) or data/adv_stats_<yr>_w<week>.js
    (that week only). span=(a, b) + out_path builds weeks a-b directly as JSON - only used to
    check the page's client-side range rebuild. True when the file changed."""
    sel = {week} if week is not None else (set(range(span[0], span[1] + 1)) if span else None)
    qb = agg_passing(yr, sel)
    rec = agg_receiving(yr, sel)
    rush = agg_rushing(yr, sel)
    sch = agg_facet('receiving_scheme', yr, ['man_routes', 'man_targets', 'man_yards', 'zone_routes', 'zone_targets', 'zone_yards'], sel)
    con = agg_facet('receiving_concept', yr, ['slot_routes', 'slot_yards', 'screen_targets', 'base_targets'], sel)
    dep = agg_facet('receiving_depth', yr, ['deep_targets', 'deep_receptions', 'deep_yards', 'medium_yards', 'short_yards',
                                           'behind_los_yards', 'behind_los_targets', 'base_targets'], sel)
    # PFF season CSVs are full-season numbers - week/span tables use the weekly facets only
    rec_s = season_csv('receiving', yr) if sel is None else {}
    rush_s = season_csv('rushing', yr) if sel is None else {}
    if sel is not None:
        pbp = pbp[pbp.week.isin(sel)] if pbp is not None else None
        snaps = {k: {w: v for w, v in d.items() if w in sel} for k, d in snaps.items()}
        snaps = {k: d for k, d in snaps.items() if d}
    P, T, PT = pbp_agg(pbp, part) if pbp is not None and len(pbp) else ({}, {}, {})
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
        # the position's own tables plus any other table listing him (a HB whose only line
        # that week is a pass attempt still gets his name and the game)
        for a in list(accs) + [qb.get(pid), rec.get(pid), rush.get(pid)]:
            if a:
                names.update(a.names)
                wk_team.update(a.weeks)
        for r in srows:
            if r and r.get('player'):
                names[r['player'].strip()] += 1
        if not names and forced and pid in forced:
            names[forced[pid][1]] += 1
        name = names.most_common(1)[0][0] if names else '?'
        last_tm = wk_team[max(wk_team)] if wk_team else next((team(r.get('team_name')) for r in srows if r), '')
        ids = ids_for(pid, name, last_tm, xw)
        stats['gsis' if ids.get('gsis') else 'no_gsis'] += 1
        sn = snaps.get(ids.get('pfr')) if ids.get('pfr') else None
        snp = tsn = None
        if sn:
            stats['snaps'] += 1
            # snap weeks win; PFF weeks fill any week the snap file doesn't have yet
            tw = dict(wk_team)
            tw.update({wk: v[0] for wk, v in sn.items()})
            games = len(tw)
            tsnaps = sum(v[1] / v[2] for v in sn.values() if v[2] > 0)
            snp = div(sum(v[1] for v in sn.values()), tsnaps, 100)
            tsn = int(round(tsnaps))
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
                'x': PT.get((ids['gsis'], tm), {}) if ids.get('gsis') else {}, 'tsn': tsn}

    # Week tables keep every player-week (floor 0), including season players (`forced`, filled
    # by the season build via `collect`) who only took snaps that week, so a range rebuilt on
    # the page counts the same games and team plays as a direct multi-week build.
    floor = MIN_FLOOR if week is None else dict.fromkeys(MIN_FLOOR, 0)
    live = set(qb) | set(rec) | set(rush) | set(rec_s) | set(rush_s)
    extra = {}
    for pid, (fpos, fname, ftm) in (forced or {}).items():
        if pid not in live:
            pfr = ids_for(pid, fname, ftm, xw).get('pfr')
            if pfr and pfr in snaps:
                extra[pid] = (fpos, [{'player': fname, 'team_name': ftm}])
    rows = {'QB': [], 'RB': [], 'WR': [], 'TE': []}
    for pid in live | set(extra):
        # season position wins, so a player PFF lists at QB/HB some weeks stays in one table
        pos = forced[pid][0] if forced and pid in forced else pos_of(pid)
        fake = extra[pid][1] if pid in extra else []
        if pos == 'QB':
            a = qb.get(pid) or (Acc() if forced and pid in forced else None)   # e.g. a rush-only week
            if not a or a.s['dropbacks'] < floor['QB']:
                continue
            s = a.s
            c = ctx(pid, [a, rush.get(pid)], fake)
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
                int(sk), int(p['cpoe_n']), int(p['dbn']), int(s['aimed_passes']), int(p['airn']), int(ns), int(s['passing_snaps']),
                int(s['def_gen_pressures']), int(s['p_dropbacks']), int(s['c_dropbacks']), int(s['c_aimed_passes']),
                int(s['p_aimed_passes']), int(s['p_attempts']), int(s['b_dropbacks']), int(s['b_attempts']),
                rnd(half_xfp(p, True)) if c['fpt'] is not None else None,
            ])
            if collect is not None:
                collect[pid] = (pos, c['n'], c['tm'])
        elif pos == 'RB':
            rw, rs = rush.get(pid), rush_s.get(pid)
            cw, cs = rec.get(pid), rec_s.get(pid)
            ru = rw.s if rw else empty
            # receiving side: season table > weekly receiving > rushing tables
            if cs:
                rts, tgt, recs, ryd = (fnum(cs.get(k)) or 0 for k in ('routes', 'targets', 'receptions', 'yards'))
                recg = fnum(cs.get('grades_pass_route'))
            elif rs and not cw:
                rts, tgt, recs = (fnum(rs.get(k)) or 0 for k in ('routes', 'targets', 'receptions'))
                ryd = None
                recg = fnum(rs.get('grades_pass_route'))
            else:
                # weekly tables: each week use the receiving table's line when it lists him (before
                # 2026 only targeted weeks), else the rushing table's - same rule for any span
                rts = tgt = recs = ryd = 0.0
                for wk in set(cw.wk_rec if cw else ()) | set(rw.wk_rec if rw else ()):
                    line = (cw.wk_rec.get(wk) if cw else None) or rw.wk_rec[wk]
                    rts += line[0]; tgt += line[1]; recs += line[2]; ryd += line[3]
                recg = cw.avg('grd') if cw else (rw.avg('recg') if rw else None)
            att = ru['attempts'] or (fnum(rs.get('attempts')) if rs else 0) or 0
            if att + tgt < floor['RB']:
                continue
            c = ctx(pid, [rw, cw], [rs, cs] + fake)
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
                c['tsn'], int(c['tt']('car')), int(c['tt']('tgt')), int(c['tt']('db')), int(c['tt']('i10')),
                int(round(yds)), int(p['car']), int(ru['gap_attempts'] + ru['zone_attempts']), int(ru['run_plays']),
                rnd(half_xfp(p, False)) if c['fpt'] is not None else None,
                rnd(p['xrec'], 2) if c['fpt'] is not None else None,
            ] + sit_values(c, p))
            if collect is not None:
                collect[pid] = (pos, c['n'], c['tm'])
        elif pos in ('WR', 'TE'):
            cw, cs = rec.get(pid), rec_s.get(pid)
            if not cw and not cs and not (forced and pid in forced):
                continue   # WR/TE with rushing rows only (jet sweeps, no target) - kept for season players
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
                grd, adot = (cw.avg('grd'), cw.avg('adot')) if cw else (None, None)
                al = w['slot_snaps'] + w['wide_snaps'] + w['inline_snaps']
                slot, wide, inl = div(w['slot_snaps'], al, 100), div(w['wide_snaps'], al, 100), div(w['inline_snaps'], al, 100)
                yac = div(w['yards_after_catch'], recs, 1, 1)
                cc = div(w['contested_receptions'], w['contested_targets'], 100)
                drp = div(w['drops'], w['drops'] + recs, 100)
                ctch = div(recs, tgt, 100)
            if rts < floor[pos]:
                continue
            ch, cn, cd = sch.get(pid), con.get(pid), dep.get(pid)
            c = ctx(pid, [cw, ch, cn, cd], [cs] + fake)
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
                c['tsn'], int(tt_db), int(tt_tgt), int(round(tt_ay)),
                int(w['slot_snaps'] + w['wide_snaps'] + w['inline_snaps']), int(w['pass_plays']), int(recs),
                int(w['drops'] + recs), int(w['contested_targets']), int(round(p['recyds'])), int(round(p['ay'])),
                rnd(m['man_routes'] * ms) if ms else None, rnd(m['zone_routes'] * ms) if ms else None,
                rnd(k['slot_routes'] * cs_) if cs_ else None,
                int(k['base_targets']), int(d['base_targets']), int(round(dy)), int(d['deep_targets']),
                rnd(half_xfp(p, False)) if c['fpt'] is not None else None,
                rnd(p['xrec'], 2) if c['fpt'] is not None else None,
            ] + sit_values(c, p))
            if collect is not None:
                collect[pid] = (pos, c['n'], c['tm'])

    rows['TM'] = team_rows(yr, pbp, sel)
    fields = {'QB': QB_F, 'RB': RB_F, 'WR': REC_F, 'TE': REC_F, 'TM': TM_F}
    # team totals (season, or that week) for the page's team view:
    # [targets, carries, air yards, inside-10 carries, games, early-down opps, 3rd-down opps, 3rd&long opps, short-yardage opps]
    teams = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0])
    for (tm, wk), v in T.items():
        if not isinstance(tm, str):
            continue
        t = teams[tm]
        t[0] += v.get('tgt', 0.0); t[1] += v.get('car', 0.0); t[2] += v.get('ay', 0.0); t[3] += v.get('i10', 0.0)
        if v.get('db', 0.0) > 0:
            t[4] += 1
        t[5] += v.get('oed', 0.0); t[6] += v.get('od3', 0.0); t[7] += v.get('od3l', 0.0); t[8] += v.get('osy', 0.0)
    payload = {'yr': yr, 'thru': thru}
    if week is not None:
        payload['wk'] = week
    if span:
        payload['span'] = list(span)
    if wks:
        payload['wks'] = wks
    payload['teams'] = {tm: [int(round(x)) for x in t] for tm, t in sorted(teams.items())}
    for pos in ('QB', 'RB', 'WR', 'TE', 'TM'):
        f = fields[pos]
        for r in rows[pos]:
            assert len(r) == len(f), (pos, len(r), len(f), r[0])
        fi = f.index('fpt') if 'fpt' in f else f.index('epa')
        rows[pos].sort(key=lambda r: -(r[fi] if r[fi] is not None else -99))
        payload[pos] = {'f': f, 'r': rows[pos]}
    body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    if out_path:
        with open(out_path, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(body)
        return True
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
        print(f'{yr}: thru W{thru}  QB {len(rows["QB"])}  RB {len(rows["RB"])}  WR {len(rows["WR"])}  TE {len(rows["TE"])}  TEAM {len(rows["TM"])}'
              f'  | ids {stats["gsis"]}/{stats["gsis"] + stats["no_gsis"]}  snaps {stats["snaps"]}'
              f'  | {len(text) // 1024} KB {"(unchanged)" if old == text else "written"}')
    return old != text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', default=None, help='comma list, default 2019-2026')
    ap.add_argument('--test-span', default=None, help='YYYY:A-B = build weeks A-B directly to --out (JSON) to check the page range rebuild')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    years = [int(y) for y in args.years.split(',')] if args.years else YEARS
    xw = crosswalk()
    dlookup = load_d_names()
    if args.test_span:
        y, ab = args.test_span.split(':')
        y = int(y)
        a, b = (int(x) for x in ab.split('-'))
        pbp, snaps = load_pbp(y), load_snaps(y)
        wks = sorted(set().union(*(weekly_weeks(f, y) for f in ('passing_pressure', 'rushing_summary', 'receiving', 'receiving_summary'))))
        universe = {}   # season positions, exactly as the week files use them
        part = load_onfield(y)
        build_table(y, xw, dlookup, pbp, snaps, wks[-1], wks=wks, collect=universe, out_path=os.devnull, part=part)
        build_table(y, xw, dlookup, pbp, snaps, b, span=(a, b), out_path=args.out, forced=universe, part=part)
        print(f'span {y} W{a}-{b} -> {args.out}')
        return
    for yr in years:
        build_year(yr, xw, dlookup)


if __name__ == '__main__':
    main()
