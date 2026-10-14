#!/usr/bin/env python3
"""
dyn_film.py — FILM SAYS MORE ROLE flags for the player card (Jack 2026-10-09:
"add the card note"; research_grade_volume.py: at the same volume, PFF grades
predict next-season volume growth — WR routes/game +11% per SD of route grade
(t 8.7, 6/6 seasons), TE +12%, RB carry share +10% per SD of offense grade;
under-used high-graders: WR routes +4% vs -19% for low-graded part-timers, RB
carry share +25% vs -10%).

Season-to-date from the weekly PFF exports in pbp_cache/pff/weekly (one file
per week; the Tuesday chain keeps them current):
  WR / TE  pff_receiving_<yr>_w<N>.csv  -> route grade; volume = MEDIAN weekly route
           participation % (data/route_pct.js, routes / team dropbacks)
           (route-weighted)
  RB       pff_v2_rushing_<yr>_w<N>.csv -> MEDIAN weekly carry share, offense grade (weighted by carries + routes)
Qualifiers scale with the weeks played (full-season study: 100 routes / 40
carries over ~17 games): WR/TE >= 6 routes x weeks, RB >= 2.5 carries x weeks.
Flag = volume in the bottom third of the position AND grade in its top third.
-> {(norm name, pos): {s, w, g, gp, v, vp, vk}}
"""
import glob
import math
import os
import re
import sys
from collections import defaultdict

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import _norm_name, DATA_DIR  # noqa: E402
import json  # noqa: E402

WEEKLY = os.path.join(os.path.dirname(HERE), 'pbp_cache', 'pff', 'weekly')
POSMAP = {'HB': 'RB', 'FB': 'RB'}


def _week_files(prefix, yr, max_w):
    out = {}
    for f in glob.glob(os.path.join(WEEKLY, f'{prefix}_{yr}_w*.csv')):
        m = re.search(r'_w(\d+)\.csv$', f)
        if m and int(m.group(1)) <= max_w:
            out[int(m.group(1))] = f
    return out


def _pct(vals, x):
    s = sorted(vals)
    return 100.0 * sum(1 for v in s if v <= x) / len(s) if s else 0.0


def film_flags(yr, max_w):
    agg = defaultdict(lambda: {'routes': 0.0, 'g_w': 0.0, 'games': 0, 'att': 0.0, 'cs': [], 'go_w': 0.0, 'go_n': 0.0, 'rw': []})
    rec = _week_files('pff_receiving', yr, max_w)
    for wk, f in rec.items():
        for r in pd.read_csv(f).to_dict('records'):
            pos = POSMAP.get(r['position'], r['position'])
            if pos not in ('WR', 'TE'):
                continue
            rt = r.get('routes') or 0
            if not rt or r.get('grades_pass_route') is None or (isinstance(r['grades_pass_route'], float) and math.isnan(r['grades_pass_route'])):
                continue
            a = agg[(_norm_name(r['player']), pos)]
            a['routes'] += rt; a['g_w'] += rt * r['grades_pass_route']; a['games'] += 1; a['rw'].append(rt)
    rush = _week_files('pff_v2_rushing', yr, max_w)
    for wk, f in rush.items():
        for r in pd.read_csv(f).to_dict('records'):
            pos = POSMAP.get(r['position'], r['position'])
            if pos != 'RB':
                continue
            att = r.get('attempts') or 0; rt = r.get('routes') or 0
            go = r.get('gradesOffense')
            if (att + rt) <= 0 or go is None or (isinstance(go, float) and math.isnan(go)):
                continue
            a = agg[(_norm_name(r['player']), 'RB')]
            a['att'] += att; a['games'] += 1
            cs = r.get('carryShare')
            if cs is not None and not (isinstance(cs, float) and math.isnan(cs)):
                a['cs'].append(float(cs))
            a['go_w'] += (att + rt) * go; a['go_n'] += att + rt
    weeks = max(len(rec), len(rush), 1)
    # WR/TE volume = MEDIAN weekly route participation (routes / team dropbacks, the card's RT%,
    # data/route_pct.js) — raw routes follow team pass volume, which made low-volume
    # passing offenses' stars (JSN, Jefferson) look under-used.
    rp = {}
    try:
        src = open(os.path.join(DATA_DIR, 'route_pct.js'), encoding='utf-8').read()
        R, _ = json.JSONDecoder().raw_decode(src, src.index('{', src.index('ROUTE_PCT')))
        for nm, yrs in R.items():
            w = (yrs.get(str(yr)) or {}).get('w') or {}
            vals = [v for k, v in w.items() if int(k) <= max_w and v is not None]
            if vals:
                rp[_norm_name(nm)] = float(pd.Series(vals).median())
    except Exception as e:
        print('route_pct unavailable:', e)
    rows = defaultdict(list)
    for (n, pos), a in agg.items():
        if pos in ('WR', 'TE') and a['routes'] >= 6 * weeks and a['games']:
            if n in rp:
                rows[pos].append((n, rp[n], a['g_w'] / a['routes']))   # median weekly route participation %
        elif pos == 'RB' and a['att'] >= 2.5 * weeks and a['cs'] and a['go_n']:
            rows[pos].append((n, float(pd.Series(a['cs']).median()), a['go_w'] / a['go_n']))
    out = {}
    for pos, lst in rows.items():
        vols = [x[1] for x in lst]; grs = [x[2] for x in lst]
        for n, v, g in lst:
            vp, gp = _pct(vols, v), _pct(grs, g)
            if vp < 33.4 and gp >= 66.7:   # bottom-third volume, top-third grade
                out[(n, pos)] = {'s': yr, 'w': weeks, 'g': round(g, 1), 'gp': round(gp), 'v': round(v, 3 if pos == 'RB' else 1), 'vp': round(vp),
                                 'vk': 'carry share' if pos == 'RB' else 'route participation', 'grade': 'offense grade' if pos == 'RB' else 'route grade'}
    return out, {p: len(v) for p, v in rows.items()}


# ---------------------------------------------------------------------------
# BEATS MAN COVERAGE (Jack 2026-10-09: "add both card notes"; research_efficiency_
# value.py): WR YPRR vs man (prior season, ctx_features, shrunk PFF split) beat the
# market long-term (beyond market 3yr -0.225*, beyond FAIR 5yr -0.353*; the market
# prices zone YPRR .66 > man .50) but failed the year-by-year test as a value term ->
# card note only. Flag = top third of qualifying WRs (150+ routes) that season.
def man_flags(season):
    ctx = pd.read_parquet(os.path.join(HERE, 'ctx_features.parquet'))
    ctx = ctx[(ctx.year == season) & (ctx.pos == 'WR')].sort_values('wk').groupby('name').tail(1)
    rc = pd.read_csv(os.path.join(os.path.dirname(HERE), 'pbp_cache', 'pff', f'pff_receiving_{season}.csv'))
    routes = {_norm_name(r['player']): r['routes'] or 0 for r in rc.to_dict('records') if r['position'] == 'WR'}
    rows = [(_norm_name(r['name']), float(r['yprr_man']), float(r['yprr_zone'])) for r in ctx.to_dict('records')
            if r.get('yprr_man') is not None and not math.isnan(r['yprr_man']) and routes.get(_norm_name(r['name']), 0) >= 150]
    vals = [x[1] for x in rows]
    out = {}
    for n, m, z in rows:
        p = _pct(vals, m)
        if p >= 66.7:
            out[(n, 'WR')] = {'s': season, 'man': round(m, 2), 'zone': round(z, 2), 'pct': round(p)}
    return out, len(rows)


# RB EFFICIENCY FADING (research_juke_decline.py): the biggest season-over-season drops
# in yards after contact per carry or juke rate (avoided tackles per touch) went with
# next-season collapse 41-51% of the time vs 28% for all RBs; already priced (beyond
# FAIR ~0) -> card warning only. This season to date (weekly PFF v2 rushing, 40+
# carries) vs last season (PFF season file, 75+ carries); flag = bottom fifth of the
# change in either stat among qualifiers.
def _rush_totals(yr, max_w):
    """Season(-to-date) RB totals from the weekly PFF v2 rushing exports — the same
    source for both seasons, so the YCO / juke changes compare like with like."""
    cur = defaultdict(lambda: {'att': 0.0, 'rec': 0.0, 'yac': 0.0, 'avt': 0.0})
    files = _week_files('pff_v2_rushing', yr, max_w)
    for wk, f in files.items():
        for r in pd.read_csv(f).to_dict('records'):
            if POSMAP.get(r['position'], r['position']) != 'RB':
                continue
            a = cur[_norm_name(r['player'])]
            a['att'] += r.get('attempts') or 0; a['rec'] += r.get('receptions') or 0
            a['yac'] += r.get('yardsAfterContact') or 0; a['avt'] += r.get('avoidedTackles') or 0
    return cur, files


def fade_flags(yr, max_w):
    prev, _ = _rush_totals(yr - 1, 30)
    P = {n: (a['yac'] / a['att'], a['avt'] / (a['att'] + a['rec'])) for n, a in prev.items() if a['att'] >= 75}
    cur, files = _rush_totals(yr, max_w)
    rows = []
    for n, a in cur.items():
        if a['att'] >= 40 and n in P and P[n][0] is not None:
            yco = a['yac'] / a['att']; juke = a['avt'] / (a['att'] + a['rec'])
            rows.append((n, yco - P[n][0], (juke - P[n][1]) if P[n][1] is not None else None, yco, P[n][0], juke, P[n][1]))
    dy = sorted(x[1] for x in rows); dj = sorted(x[2] for x in rows if x[2] is not None)
    qy = dy[int(0.2 * len(dy))] if dy else -9
    qj = dj[int(0.2 * len(dj))] if dj else -9
    out = {}
    for n, cy, cj, yco, yco0, juke, juke0 in rows:
        hit = []
        if cy <= qy:
            hit.append('yco')
        if cj is not None and cj <= qj:
            hit.append('juke')
        if hit:
            out[(n, 'RB')] = {'s': yr, 'w': len(files), 'yco': round(yco, 2), 'yco0': round(yco0, 2),
                              'juke': round(juke, 3), 'juke0': round(juke0, 3) if juke0 is not None else None, 'hit': hit}
    return out, len(rows)


if __name__ == '__main__':
    f, n = film_flags(int(sys.argv[1]) if len(sys.argv) > 1 else 2026, int(sys.argv[2]) if len(sys.argv) > 2 else 18)
    print('qualifiers', n, '| flagged', len(f))
    for k, v in sorted(f.items(), key=lambda kv: (kv[0][1], -kv[1]['gp'])):
        print(' ', k, v)
