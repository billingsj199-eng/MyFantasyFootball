#!/usr/bin/env python3
"""
Depth-chart ARCHETYPES for the player card header -> data/player_roles_2026.js

  window.PLAYER_ROLES_2026 = {
    "updated": "...", "season": 2026, "thru": 1,          # last week with usage data
    "p": {
      "Jahmyr Gibbs": {
        "t": "DET", "pos": "RB",
        "role": "RB1", "align": "", "tags": ["BELL COW"],  # current call (last 3 weeks)
        "line": "RB1 · BELL COW",                          # what the header chip row shows
        "dc": 1,                                            # ESPN depth-chart rank (today)
        "w": {"1": "RB1 · BELL COW"},                       # week-by-week trail (week-only)
        "m": {"snap": 71, "tch": 68, "gl": 100, "d3": 60}   # the numbers behind the call
      }, ...
    }
  }

Jack 2026-09-14: "add the depth chart archetypes to player cards ... rb1,
goal-line back, rb2, handcuff, 3rd-down back; for WRs X, Z, slot; TEs te1,
te2, blocking, slot ... based on their roles and alignments in week 1, continue
to check each week; use ESPN depth charts and PFF to help."

SOURCES (all already on disk from the daily jobs)
  ESPN depth charts   data/depth_charts_2026.json  (pull_depth_charts.py, daily)
                      -> QB1/QB2 and the fallback rank for anyone without usage yet
  nflverse pbp 2026   E:\\MyFantasyFootball\\pbp_cache\\play_by_play_2026.csv.gz
                      (pull_pace_tracker.py re-downloads nightly) -> RB room shares:
                      touches, carries inside the 5 (goal line), 3rd-down + two-minute
                      touches (passing downs); WR/TE target shares (rank fallback)
  PFF Premium weekly  pbp_cache/pff/weekly/pff_receiving_2026_w<N>.csv
                      (pull_pff_weekly.py) -> routes (WR/TE rank), slot_rate /
                      wide_rate / inline_rate (alignment), route_rate (blocking TE)
  nflverse snaps      data/snap_counts.js (pull_snap_counts.py) -> snap share
  route pct           data/route_pct.js (pull_route_pct.py, built just before this
                      in route_pct_daily.ps1) -> TE route participation (BLOCKING)

CALLS (season-to-date with the last 3 weeks counting; week-only for the trail)
  RB   rank by share of the team's RB touches -> RB1/RB2/RB3
       BELL COW    RB1 with >= 65% of RB touches and >= 60% snaps
       COMMITTEE   top two both between 30% and 60% of touches
       GOAL LINE   >= 50% of the team's RB carries inside the 5 (>= 2 such carries)
       3RD DOWN    passing-down back: >= 45% of RB 3rd-down/two-minute touches
                   (>= 3 such touches, not the touch leader)
       PASS CATCHER  target share 15 pts above carry share on >= 3 targets (not
                   the touch leader) — receiving role without the down-and-
                   distance usage (Jack 2026-09-14: split from 3RD DOWN)
       HANDCUFF    RB2 with < 25% of touches behind an RB1 at >= 55%
       DEPTH       < 10% of touches
  WR   rank by PFF routes (target share fallback) -> WR1/WR2/WR3/WR4
       SLOT        >= 45% slot snaps (PFF)
       X / Z       outside receivers: X = the team's primary boundary WR (most
                   wide snaps), Z = the next; other outside WRs just OUTSIDE.
                   (No public feed charts split end vs flanker; this is the
                   standard convention, X = boundary #1.)
  TE   rank by PFF routes -> TE1/TE2
       IN-LINE     >= 60% in-line snaps;  SLOT >= 60% slot+wide;  else HYBRID
       BLOCKING    route participation (routes / team dropbacks, data/route_pct.js)
                   < 40% on >= 25% snaps. NOT PFF route_rate: that is routes per
                   pass snap he was on the field for, and blockers still run a
                   route on most of those (Brock Wright 50%, Josh Oliver 75%),
                   so it never fired (2026-09-14 live check).
  QB   ESPN depth chart -> QB1 STARTER / QB2 BACKUP (dropbacks confirm)

Only players in data/d.js are kept (the card only opens for D-array players).

Run from the project root:  python scripts/build_player_roles.py [--dry]
"""
import argparse, glob, io, json, os, re, sys
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
from pull_snap_counts import norm_variants, load_d_names  # noqa: E402

SEASON = 2026
OUT = os.path.join(ROOT, 'data', f'player_roles_{SEASON}.js')
DEPTH = os.path.join(ROOT, 'data', f'depth_charts_{SEASON}.json')
SNAPS = os.path.join(ROOT, 'data', 'snap_counts.js')
ROUTES = os.path.join(ROOT, 'data', 'route_pct.js')
CACHE = r'E:\MyFantasyFootball\pbp_cache'
PBP = os.path.join(CACHE, f'play_by_play_{SEASON}.csv.gz')
PLAYERS = os.path.join(CACHE, 'players.csv')
PFF_WEEKLY = os.path.join(CACHE, 'pff', 'weekly')
TEAM_FIX = {'LA': 'LAR', 'WSH': 'WAS', 'JAC': 'JAX', 'OAK': 'LV', 'SD': 'LAC', 'STL': 'LAR',
            'ARZ': 'ARI', 'BLT': 'BAL', 'CLV': 'CLE', 'HST': 'HOU'}
PFF_NAME_FIX = {'Joshua Palmer': 'Josh Palmer', 'Chigoziem Okonkwo': 'Chig Okonkwo'}
RECENT = 3          # weeks that count for the current call
GL_YARD = 5         # "goal line" = carry from the 5 or closer


def tm(t):
    return TEAM_FIX.get(str(t), str(t))


def resolve(lookup, name):
    name = PFF_NAME_FIX.get(name, name)
    for v in norm_variants(name):
        if v in lookup:
            return lookup[v]
    return None


# ----------------------------------------------------------------- loaders
def load_depth():
    """data/depth_charts_2026.json (gitignored twin) or the tracked .js wrapper."""
    if os.path.exists(DEPTH):
        j = json.load(open(DEPTH, encoding='utf-8'))
        return j.get('teams', {})
    js = DEPTH[:-5] + '.js'
    if not os.path.exists(js):
        return {}
    src = open(js, encoding='utf-8').read()
    m = re.search(r'window\.DEPTH_2026\s*=\s*(\{.*\});', src, re.S)
    return json.loads(m.group(1)).get('teams', {}) if m else {}


def load_snaps(lookup):
    """{dname: {week: snap%}} for the current season."""
    out = {}
    if not os.path.exists(SNAPS):
        return out
    src = open(SNAPS, encoding='utf-8').read()
    m = re.search(r'window\.SNAP_COUNTS\s*=\s*(\{.*?\});\s*\n', src, re.S)
    if not m:
        return out
    for name, seasons in json.loads(m.group(1)).items():
        yr = seasons.get(str(SEASON))
        if not yr:
            continue
        dn = resolve(lookup, name) or name
        out[dn] = {int(w): v for w, v in (yr.get('w') or {}).items()}
    return out


def load_routes(lookup):
    """{dname: {week: route participation %}} for the current season (data/route_pct.js)."""
    out = {}
    if not os.path.exists(ROUTES):
        return out
    src = open(ROUTES, encoding='utf-8').read()
    m = re.search(r'window\.ROUTE_PCT\s*=\s*(\{.*?\});\s*\n', src, re.S)
    if not m:
        return out
    for name, seasons in json.loads(m.group(1)).items():
        yr = seasons.get(str(SEASON))
        if not yr:
            continue
        dn = resolve(lookup, name) or name
        out[dn] = {int(w): v for w, v in (yr.get('w') or {}).items()}
    return out


def load_pff(lookup):
    """{week: {dname: {t, pos, routes, slot, wide, inline, rr, snaps}}}"""
    out = {}
    for path in sorted(glob.glob(os.path.join(PFF_WEEKLY, f'pff_receiving_{SEASON}_w*.csv'))):
        wk = int(re.search(r'_w(\d+)\.csv$', path).group(1))
        df = pd.read_csv(path)
        rows = {}
        for r in df.itertuples(index=False):
            dn = resolve(lookup, str(r.player))
            if not dn:
                continue
            pos = {'HB': 'RB'}.get(str(r.position), str(r.position))
            if pos not in ('RB', 'WR', 'TE', 'FB'):
                continue
            def num(x):
                try:
                    v = float(x)
                    return None if pd.isna(v) else v
                except Exception:  # noqa: BLE001
                    return None
            ws, ss, ins = num(getattr(r, 'wide_snaps', None)), num(getattr(r, 'slot_snaps', None)), num(getattr(r, 'inline_snaps', None))
            rows[dn] = {'t': tm(r.team_name), 'pos': pos, 'routes': num(r.routes) or 0,
                        'slot': num(r.slot_rate), 'wide': num(r.wide_rate), 'inline': num(r.inline_rate),
                        'rr': num(r.route_rate),
                        'wide_snaps': ws or 0, 'slot_snaps': ss or 0, 'inline_snaps': ins or 0}
        out[wk] = rows
    return out


def load_pbp(lookup):
    """Per week per team usage from play-by-play.
    rb[wk][team][dname] = {car, tgt, gl, d3, pos}
    rec[wk][team][dname] = {tgt, pos}   (WR/TE target shares, PFF fallback)
    qb[wk][team][dname] = dropbacks
    """
    rb, rec, qb = {}, {}, {}
    if not os.path.exists(PBP):
        return rb, rec, qb
    pl = pd.read_csv(PLAYERS, low_memory=False, usecols=['gsis_id', 'display_name', 'position'])
    pinfo = {}
    for r in pl.itertuples(index=False):
        if isinstance(r.gsis_id, str) and r.gsis_id.startswith('00-'):
            pinfo[r.gsis_id] = (str(r.display_name), str(r.position))
    cols = ['season_type', 'week', 'posteam', 'rush_attempt', 'pass_attempt', 'qb_dropback',
            'rusher_player_id', 'receiver_player_id', 'passer_player_id', 'yardline_100', 'down',
            'half_seconds_remaining', 'play_type', 'two_point_attempt']
    df = pd.read_csv(PBP, low_memory=False, usecols=cols)
    df = df[(df.season_type == 'REG') & df.posteam.notna()]
    df = df[df.play_type.isin(['run', 'pass'])]
    for r in df.itertuples(index=False):
        wk, team = int(r.week), tm(r.posteam)
        passing_down = (r.down == 3) or (r.down == 4) or (r.half_seconds_remaining is not None and r.half_seconds_remaining <= 120)
        gl = (r.yardline_100 is not None and r.yardline_100 <= GL_YARD)
        if r.rush_attempt == 1 and isinstance(r.rusher_player_id, str):
            info = pinfo.get(r.rusher_player_id)
            if info and info[1] in ('RB', 'FB', 'HB'):
                dn = resolve(lookup, info[0])
                if dn:
                    d = rb.setdefault(wk, {}).setdefault(team, {}).setdefault(dn, {'car': 0, 'tgt': 0, 'gl': 0, 'd3': 0, 'pos': info[1]})
                    d['car'] += 1
                    if gl:
                        d['gl'] += 1
                    if passing_down:
                        d['d3'] += 1
        if r.pass_attempt == 1 and isinstance(r.receiver_player_id, str):
            info = pinfo.get(r.receiver_player_id)
            if info:
                dn = resolve(lookup, info[0])
                if dn and info[1] in ('RB', 'FB', 'HB'):
                    d = rb.setdefault(wk, {}).setdefault(team, {}).setdefault(dn, {'car': 0, 'tgt': 0, 'gl': 0, 'd3': 0, 'pos': info[1]})
                    d['tgt'] += 1
                    if passing_down:
                        d['d3'] += 1
                elif dn and info[1] in ('WR', 'TE'):
                    d = rec.setdefault(wk, {}).setdefault(team, {}).setdefault(dn, {'tgt': 0, 'pos': info[1]})
                    d['tgt'] += 1
        if r.qb_dropback == 1 and isinstance(r.passer_player_id, str):
            info = pinfo.get(r.passer_player_id)
            if info:
                dn = resolve(lookup, info[0])
                if dn:
                    q = qb.setdefault(wk, {}).setdefault(team, {})
                    q[dn] = q.get(dn, 0) + 1
    return rb, rec, qb


# ----------------------------------------------------------------- calls
def pct(a, b):
    return round(100.0 * a / b) if b else None


def call_rb(room, snaps):
    """room = {dname: {car,tgt,gl,d3,pos}} summed over the window; snaps = {dname: snap%}.
    Returns {dname: (role, tags, metrics)}."""
    out = {}
    tot = {k: v['car'] + v['tgt'] for k, v in room.items()}
    team_t = sum(tot.values())
    team_car = sum(v['car'] for v in room.values())
    team_tgt = sum(v['tgt'] for v in room.values())
    team_gl = sum(v['gl'] for v in room.values())
    team_d3 = sum(v['d3'] for v in room.values())
    order = sorted(room, key=lambda k: (-tot[k], -room[k]['car']))
    shares = {k: (tot[k] / team_t if team_t else 0) for k in room}
    lead = order[0] if order else None
    lead_share = shares.get(lead, 0)
    for i, k in enumerate(order):
        v = room[k]
        if v['pos'] == 'FB':
            role, tags = 'FB', []
        else:
            rank = 1 + sum(1 for o in order[:i] if room[o]['pos'] != 'FB')
            role = f'RB{min(rank, 4)}' if rank < 4 else 'RB4+'
            tags = []
        sh = shares[k]
        car_sh = v['car'] / team_car if team_car else 0
        tgt_sh = v['tgt'] / team_tgt if team_tgt else 0
        gl_sh = v['gl'] / team_gl if team_gl else 0
        d3_sh = v['d3'] / team_d3 if team_d3 else 0
        snap = snaps.get(k)
        if v['pos'] != 'FB':
            bell = (k == lead and sh >= 0.65 and (snap is None or snap >= 60))
            if bell:
                tags.append('BELL COW')
            elif len(order) > 1 and k in order[:2] and all(0.30 <= shares[o] <= 0.60 for o in order[:2] if room[o]['pos'] != 'FB'):
                tags.append('COMMITTEE')
            if not bell:
                if v['gl'] >= 2 and gl_sh >= 0.5:
                    tags.append('GOAL LINE')
                if k != lead and v['d3'] >= 3 and d3_sh >= 0.45:
                    tags.append('3RD DOWN')
                elif k != lead and tgt_sh - car_sh >= 0.15 and v['tgt'] >= 3:
                    tags.append('PASS CATCHER')
                if role == 'RB2' and sh < 0.25 and lead_share >= 0.55 and not any(t in tags for t in ('GOAL LINE', '3RD DOWN', 'PASS CATCHER')):
                    tags.append('HANDCUFF')
            if sh < 0.10 and not tags and role != 'RB1':
                tags.append('DEPTH')
        out[k] = (role, tags, {'snap': snap, 'tch': pct(tot[k], team_t), 'gl': pct(v['gl'], team_gl) if team_gl else None,
                               'd3': pct(v['d3'], team_d3) if team_d3 else None})
    return out


def call_wr(room, snaps, routes=None):
    """room = {dname: {routes, tgt, slot, wide, wide_snaps}} summed/averaged over the window."""
    out = {}
    order = sorted(room, key=lambda k: (-(room[k]['routes'] or 0), -(room[k]['tgt'] or 0)))
    outside = [k for k in room if room[k]['slot'] is not None and room[k]['slot'] < 45]
    outside.sort(key=lambda k: -room[k]['wide_snaps'])
    for i, k in enumerate(order):
        v = room[k]
        role = f'WR{i + 1}' if i < 3 else 'WR4+'
        tags = []
        if v['slot'] is None:
            align = ''
        elif v['slot'] >= 45:
            align = 'SLOT'
        elif outside and k == outside[0]:
            align = 'X'
        elif len(outside) > 1 and k == outside[1]:
            align = 'Z'
        else:
            align = 'OUTSIDE'
        out[k] = (role, align, tags, {'snap': snaps.get(k), 'rt': round(v['routes']) if v['routes'] else None,
                                      'slot': round(v['slot']) if v['slot'] is not None else None})
    return out


def call_te(room, snaps, routes=None):
    routes = routes or {}
    out = {}
    order = sorted(room, key=lambda k: (-(room[k]['routes'] or 0), -(room[k]['tgt'] or 0)))
    for i, k in enumerate(order):
        v = room[k]
        role = f'TE{i + 1}' if i < 2 else 'TE3+'
        tags = []
        if v['inline'] is None:
            align = ''
        elif v['inline'] >= 60:
            align = 'IN-LINE'
        elif (v['slot'] or 0) + (v['wide'] or 0) >= 60:
            align = 'SLOT'
        else:
            align = 'HYBRID'
        snap = snaps.get(k)
        rtp = routes.get(k)
        if rtp is not None and rtp < 40 and (snap or 0) >= 25:
            tags.append('BLOCKING')
        out[k] = (role, align, tags, {'snap': snap, 'rt': round(v['routes']) if v['routes'] else None,
                                      'rtp': rtp,
                                      'inl': round(v['inline']) if v['inline'] is not None else None})
    return out


def merge_window(weeks, per_week, team, pos_filter=None):
    """Sum a per-week team room over `weeks`. per_week[wk][team][name] = dict of counters."""
    room = {}
    for wk in weeks:
        for k, v in (per_week.get(wk, {}).get(team, {}) or {}).items():
            d = room.setdefault(k, defaultdict(float))
            for kk, vv in v.items():
                if isinstance(vv, (int, float)):
                    d[kk] += vv
                else:
                    d[kk] = vv
    return room


def rec_room(weeks, pff, rec, team, pos):
    """WR/TE room over a window: PFF routes + alignment (routes-weighted) with pbp target fallback."""
    room = {}
    for wk in weeks:
        for k, v in (pff.get(wk, {}) or {}).items():
            if v['t'] != team or v['pos'] != pos:
                continue
            d = room.setdefault(k, {'routes': 0.0, 'tgt': 0.0, 'wide_snaps': 0.0, 'slot_snaps': 0.0, 'inline_snaps': 0.0, 'rr_n': 0.0, 'rr_w': 0.0})
            d['routes'] += v['routes']
            d['wide_snaps'] += v['wide_snaps']
            d['slot_snaps'] += v['slot_snaps']
            d['inline_snaps'] += v['inline_snaps']
            if v['rr'] is not None:
                d['rr_n'] += v['rr'] * max(v['routes'], 1)
                d['rr_w'] += max(v['routes'], 1)
        for k, v in (rec.get(wk, {}).get(team, {}) or {}).items():
            if v['pos'] != pos:
                continue
            d = room.setdefault(k, {'routes': 0.0, 'tgt': 0.0, 'wide_snaps': 0.0, 'slot_snaps': 0.0, 'inline_snaps': 0.0, 'rr_n': 0.0, 'rr_w': 0.0})
            d['tgt'] += v['tgt']
    for k, d in room.items():
        al = d['wide_snaps'] + d['slot_snaps'] + d['inline_snaps']
        d['slot'] = 100.0 * d['slot_snaps'] / al if al else None
        d['wide'] = 100.0 * d['wide_snaps'] / al if al else None
        d['inline'] = 100.0 * d['inline_snaps'] / al if al else None
        d['rr'] = d['rr_n'] / d['rr_w'] if d['rr_w'] else None
    return room


def fmt_line(role, align, tags):
    parts = [role]
    if align:
        parts.append(align)
    parts += tags
    return ' · '.join(p for p in parts if p)


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()

    lookup = load_d_names()
    depth = load_depth()
    snaps = load_snaps(lookup)
    routes = load_routes(lookup)
    pff = load_pff(lookup)
    rb, rec, qb = load_pbp(lookup)
    weeks = sorted(set(rb) | set(pff))
    thru = max(weeks) if weeks else 0
    print(f'weeks with usage: {weeks}  pff weeks: {sorted(pff)}  snaps: {len(snaps)} players')

    teams = sorted(set(depth) | {t for w in rb.values() for t in w} | {v["t"] for w in pff.values() for v in w.values()})
    players = {}

    def put(name, team, pos, role, align, tags, metrics, week=None):
        p = players.setdefault(name, {'t': team, 'pos': pos, 'role': '', 'align': '', 'tags': [], 'line': '', 'dc': None, 'w': {}, 'm': {}})
        line = fmt_line(role, align, tags)
        if week is None:
            p.update({'t': team, 'pos': pos, 'role': role, 'align': align, 'tags': tags, 'line': line,
                      'm': {k: v for k, v in metrics.items() if v is not None}})
        else:
            p['w'][str(week)] = line

    for team in teams:
        dc = depth.get(team, {})
        # --- ESPN depth ranks (today) + QB calls
        for pos in ('QB', 'RB', 'WR', 'TE'):
            for i, nm in enumerate(dc.get(pos, []) or []):
                dn = resolve(lookup, nm)
                if not dn:
                    continue
                p = players.setdefault(dn, {'t': team, 'pos': pos, 'role': '', 'align': '', 'tags': [], 'line': '', 'dc': None, 'w': {}, 'm': {}})
                p['dc'] = i + 1
                if pos == 'QB':
                    role = f'QB{i + 1}' if i < 3 else 'QB4+'
                    tags = ['STARTER'] if i == 0 else (['BACKUP'] if i == 1 else [])
                    put(dn, team, 'QB', role, '', tags, {})
        # QB trail from dropbacks (week-only)
        for wk in weeks:
            q = qb.get(wk, {}).get(team, {})
            order = sorted(q, key=lambda k: -q[k])
            for i, k in enumerate(order):
                if q[k] < 5:
                    continue
                put(k, team, 'QB', f'QB{i + 1}', '', ['STARTER'] if i == 0 else ['BACKUP'], {}, week=wk)
        # --- RB: current call (recent window) + week trail
        windows = [(None, weeks[-RECENT:])] + [(wk, [wk]) for wk in weeks]
        for week, win in windows:
            room = merge_window(win, rb, team)
            if not room:
                continue
            snap_win = {}
            for k in room:
                vals = [snaps.get(k, {}).get(w) for w in win]
                vals = [v for v in vals if v is not None]
                snap_win[k] = round(sum(vals) / len(vals)) if vals else None
            for k, (role, tags, metrics) in call_rb(room, snap_win).items():
                put(k, team, room[k]['pos'] if room[k]['pos'] != 'HB' else 'RB', role, '', tags, metrics, week=week)
        # --- WR / TE
        for pos, caller in (('WR', call_wr), ('TE', call_te)):
            for week, win in windows:
                room = rec_room(win, pff, rec, team, pos)
                if not room:
                    continue
                snap_win, rt_win = {}, {}
                for k in room:
                    vals = [snaps.get(k, {}).get(w) for w in win]
                    vals = [v for v in vals if v is not None]
                    snap_win[k] = round(sum(vals) / len(vals)) if vals else None
                    rv = [routes.get(k, {}).get(w) for w in win]
                    rv = [v for v in rv if v is not None]
                    rt_win[k] = round(sum(rv) / len(rv)) if rv else None
                for k, (role, align, tags, metrics) in caller(room, snap_win, rt_win).items():
                    put(k, team, pos, role, align, tags, metrics, week=week)

    # players on an ESPN depth chart with no usage yet: rank from the chart
    for team in teams:
        dc = depth.get(team, {})
        for pos in ('RB', 'WR', 'TE'):
            for i, nm in enumerate(dc.get(pos, []) or []):
                dn = resolve(lookup, nm)
                if dn and dn in players and not players[dn]['role']:
                    role = f'{pos}{i + 1}' if i < (3 if pos != 'TE' else 2) else f'{pos}{"3" if pos == "TE" else "4"}+'
                    put(dn, team, pos, role, '', ['DEPTH CHART'], {})

    players = {k: v for k, v in players.items() if v['line']}
    for v in players.values():
        if v['dc'] is None:
            v.pop('dc')
        if not v['w']:
            v.pop('w')
        if not v['m']:
            v.pop('m')
        if not v['align']:
            v.pop('align')
        if not v['tags']:
            v.pop('tags')

    stamp = datetime.now(timezone.utc).isoformat()
    doc = {'updated': stamp, 'season': SEASON, 'thru': thru, 'p': players}
    by = defaultdict(int)
    for v in players.values():
        by[v['pos']] += 1
    print(f'players with a call: {len(players)}  {dict(by)}  thru week {thru}')
    for nm in ('Jahmyr Gibbs', 'David Montgomery', 'Amon-Ra St. Brown', 'Jameson Williams', 'Sam LaPorta',
               'Parker Washington', 'Brian Thomas Jr.', 'Travis Etienne Jr.', 'Bhayshul Tuten', 'Jared Goff'):
        if nm in players:
            print(f'  {nm:22s} {players[nm]["line"]:32s} {players[nm].get("m", {})}  {players[nm].get("w", {})}')
    if args.dry:
        return
    body = json.dumps(doc, separators=(',', ':'), ensure_ascii=False)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('// AUTO-GENERATED by scripts/build_player_roles.py (ESPN depth charts + nflverse pbp + PFF alignment)\n')
        f.write('window.PLAYER_ROLES_2026 = ' + body + ';\n')
    print(f'wrote {OUT} ({os.path.getsize(OUT) // 1024} KB)')


if __name__ == '__main__':
    main()
