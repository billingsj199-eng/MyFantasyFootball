#!/usr/bin/env python3
"""
research_injury_drift.py — short-term KTC drift after injuries (Jack 2026-10-09:
"test the short-term injury drift next").

Earlier (research_ktc_drivers.py, 2026 only): KTC under-reacts to injuries — an
IR move is -3.8% after 7 days but -12.9% after 30. Is that a usable edge (a
SELL-NOW tag / FAIR shade), and does the value come back later (BUY the dip)?

EVENTS (2020-2026 seasons): from the weekly game logs, a player who played in
week w and then missed 2+ consecutive weeks (2 weeks so a bye can't fake one),
weeks 1-15. Types by the absence that followed: SHORT 2-3 weeks, LONG 4+ weeks
(returned the same season), SEASON-ENDING (no more games that season, 4+ left).
The type is known after the fact; in practice the injury news (IR, season-
ending) gives it away within days — read LONG / SEASON-ENDING as 'an IR-level
injury'. Event day t0 = the Tuesday after his last game (news + injury report).
VALUES: KTC 1QB daily history (_dyn_cache/ktc_alltime.json — today's top 150,
so SURVIVORSHIP: players who never recovered are missing -> recovery reads
too rosy, the slide too mild).
EXCESS DRIFT: log value change t0 -> t0+h minus the median change of CONTROLS
(same position, KTC value within +/-25% at t0, no event in [t0-21, t0+h]).
Horizons 7 / 30 / 60 / 90 / 180 / 365 days; also the pre-event reaction
(t0-3 -> t0).
"""
import bisect
import datetime as dt
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, _norm_name  # noqa: E402

KICKOFF = {2020: dt.date(2020, 9, 10), 2021: dt.date(2021, 9, 9), 2022: dt.date(2022, 9, 8), 2023: dt.date(2023, 9, 7),
           2024: dt.date(2024, 9, 5), 2025: dt.date(2025, 9, 4), 2026: dt.date(2026, 9, 10)}
LAST_WEEK = {y: (17 if y <= 2020 else 18) for y in KICKOFF}
HORIZONS = (7, 30, 60, 90, 180, 365)
TODAY = dt.date(2026, 10, 9)


def series(rec):
    o = rec.get('oneQB') or {}
    pts = sorted((dt.date(2000 + int(d[:2]), int(d[2:4]), int(d[4:6])), v) for d, v in zip(o.get('d', []), o.get('v', [])) if v and v > 0)
    return [p[0] for p in pts], [p[1] for p in pts]


def val_at(S, day, tol=6):
    ks, vs = S
    i = bisect.bisect_right(ks, day) - 1
    if i < 0 or (day - ks[i]).days > tol:
        return None
    return vs[i]


def main():
    w = World(2026)
    K = json.load(open(os.path.join(HERE, '_dyn_cache', 'ktc_alltime.json'), encoding='utf-8'))['players']
    P = {}
    for n, rec in K.items():
        key = (_norm_name(n), rec['pos'])
        S = series(rec)
        if len(S[0]) > 60:
            P[key] = S
    print(f'{len(P)} KTC players with history; matched to weekly logs: {sum(1 for k in P if k in w.weekly)}')

    # events
    ev = []
    for key in P:
        for Y, lst in w.weekly.get(key, {}).items():
            if Y not in KICKOFF:
                continue
            wks = sorted(wk for wk, _ in lst)
            last = LAST_WEEK[Y]
            for i, wk in enumerate(wks):
                if wk > 15:
                    break
                nxt = wks[i + 1] if i + 1 < len(wks) else None
                gap = (nxt - wk - 1) if nxt else (last - wk)
                if gap < 2:
                    continue
                kind = 'SEASON-ENDING' if nxt is None and gap >= 4 else 'LONG 4+' if gap >= 4 else 'SHORT 2-3'
                if nxt is None and gap < 4:
                    continue
                # REGULARS ONLY (--regulars): played 3+ of the 4 weeks before the
                # gap (a bye can cost one) — drops benched / inactive backups.
                if '--regulars' in sys.argv and sum(1 for x in wks if wk - 3 <= x <= wk) < 3:
                    continue
                t0 = KICKOFF[Y] + dt.timedelta(days=7 * (wk - 1) + 5)   # Tuesday after his last game
                if t0 > TODAY - dt.timedelta(days=7):
                    continue
                ev.append({'key': key, 'Y': Y, 'wk': wk, 'gap': gap, 'kind': kind, 't0': t0})
    print(f'{len(ev)} absence events: ' + ', '.join(f'{k} {sum(1 for e in ev if e["kind"] == k)}' for k in ('SHORT 2-3', 'LONG 4+', 'SEASON-ENDING')))
    evdays = defaultdict(list)
    for e in ev:
        evdays[e['key']].append(e['t0'])

    def change(key, a, b):
        va, vb = val_at(P[key], a), val_at(P[key], b)
        return math.log(vb / va) if va and vb else None

    def controls(e, h):
        v0 = val_at(P[e['key']], e['t0'])
        out = []
        for k2, S in P.items():
            if k2 == e['key'] or k2[1] != e['key'][1]:
                continue
            v = val_at(S, e['t0'])
            if not v or not (0.75 * v0 <= v <= 1.25 * v0):
                continue
            if any(-21 <= (d - e['t0']).days <= h for d in evdays.get(k2, ())):
                continue
            c = change(k2, e['t0'], e['t0'] + dt.timedelta(days=h))
            if c is not None:
                out.append(c)
        return out

    print('\n=== excess KTC drift after an injury absence (event - matched controls), median % ===')
    print(f'{"type":<16}{"pre t0-3>t0":>12}' + ''.join(f'{"+" + str(h) + "d":>10}' for h in HORIZONS))
    res = defaultdict(dict)
    for kind in ('SHORT 2-3', 'LONG 4+', 'SEASON-ENDING', 'ALL LONG+SEASON'):
        E = [e for e in ev if (e['kind'] == kind or (kind == 'ALL LONG+SEASON' and e['kind'] != 'SHORT 2-3'))]
        cells = []
        pre = [change(e['key'], e['t0'] - dt.timedelta(days=3), e['t0']) for e in E]
        pre = [x for x in pre if x is not None]
        cells.append(f'{(math.exp(np.median(pre)) - 1) * 100:+.1f}% ({len(pre)})' if pre else '—')
        for h in HORIZONS:
            xs = []
            for e in E:
                if e['t0'] + dt.timedelta(days=h) > TODAY:
                    continue
                c = change(e['key'], e['t0'], e['t0'] + dt.timedelta(days=h))
                if c is None:
                    continue
                ctl = controls(e, h)
                if len(ctl) >= 3:
                    xs.append(c - float(np.median(ctl)))
            if xs:
                m = float(np.median(xs)); se = 1.253 * np.std(xs) / math.sqrt(len(xs))
                res[kind][h] = (m, len(xs), m / se if se > 0 else 0)
                cells.append(f'{(math.exp(m) - 1) * 100:+.1f}%{"*" if abs(m / se) >= 2 else " "}({len(xs)})')
            else:
                cells.append('—')
        print(f'{kind:<16}{cells[0]:>12}' + ''.join(f'{c:>10}' for c in cells[1:]))
    print('   * = |median / se| >= 2. Controls: same position, KTC value +/-25% at t0, no absence event in the window.')

    print('\n=== by value tier (LONG + SEASON-ENDING), excess drift +30d / +90d / +180d ===')
    for lbl, lo, hi in (('KTC 7000+', 7000, 99999), ('4500-7000', 4500, 7000), ('< 4500', 0, 4500)):
        E = [e for e in ev if e['kind'] != 'SHORT 2-3' and lo <= (val_at(P[e['key']], e['t0']) or 0) < hi]
        row = []
        for h in (30, 90, 180):
            xs = []
            for e in E:
                if e['t0'] + dt.timedelta(days=h) > TODAY:
                    continue
                c = change(e['key'], e['t0'], e['t0'] + dt.timedelta(days=h))
                ctl = controls(e, h) if c is not None else []
                if c is not None and len(ctl) >= 3:
                    xs.append(c - float(np.median(ctl)))
            row.append(f'{(math.exp(np.median(xs)) - 1) * 100:+.1f}% ({len(xs)})' if xs else '—')
        print(f'   {lbl:<12}' + ''.join(f'{r:>16}' for r in row))

    print('\n=== by position (LONG + SEASON-ENDING), excess drift +30d / +90d / +180d ===')
    for pos in ('QB', 'RB', 'WR', 'TE'):
        E = [e for e in ev if e['kind'] != 'SHORT 2-3' and e['key'][1] == pos]
        row = []
        for h in (30, 90, 180):
            xs = []
            for e in E:
                if e['t0'] + dt.timedelta(days=h) > TODAY:
                    continue
                c = change(e['key'], e['t0'], e['t0'] + dt.timedelta(days=h))
                ctl = controls(e, h) if c is not None else []
                if c is not None and len(ctl) >= 3:
                    xs.append(c - float(np.median(ctl)))
            row.append(f'{(math.exp(np.median(xs)) - 1) * 100:+.1f}% ({len(xs)})' if xs else '—')
        print(f'   {pos:<12}' + ''.join(f'{r:>16}' for r in row))

    print('\n=== examples: biggest LONG / SEASON-ENDING slides (+30d raw) and where they were at +180d ===')
    rows = []
    for e in ev:
        if e['kind'] == 'SHORT 2-3' or e['t0'] + dt.timedelta(days=30) > TODAY:
            continue
        c30 = change(e['key'], e['t0'], e['t0'] + dt.timedelta(days=30))
        c180 = change(e['key'], e['t0'], e['t0'] + dt.timedelta(days=180)) if e['t0'] + dt.timedelta(days=180) <= TODAY else None
        if c30 is not None:
            rows.append((c30, c180, e))
    for c30, c180, e in sorted(rows, key=lambda r: r[0])[:12]:
        print(f'   {e["key"][0]:<24}{e["key"][1]:<3}{e["Y"]} wk{e["wk"]:<3}{e["kind"]:<14} +30d {(math.exp(c30) - 1) * 100:+5.0f}%   +180d '
              + (f'{(math.exp(c180) - 1) * 100:+5.0f}%' if c180 is not None else '   —'))
    json.dump({k: {str(h): v for h, v in d.items()} for k, d in res.items()}, open(os.path.join(HERE, '_dyn_cache', 'injury_drift.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
