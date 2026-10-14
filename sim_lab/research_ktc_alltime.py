#!/usr/bin/env python3
"""
research_ktc_alltime.py — KTC's own 5-year history (2021-03 .. 2026-10): does the
market overreact, how does value age, and is there a calendar? (Jack 2026-10-09)

Data: _dyn_cache/ktc_alltime.json (pull_ktc_alltime.py: today's top ~150
QB/RB/WR/TE, daily 1QB value). SURVIVORSHIP: these are players KTC lists today,
so 2021-23 busts / retirees are missing — continuation ("momentum") reads too
strong and declines too weak. Every section prints the bias direction.

1  Overreaction vs momentum: value change over the past 30 / 90 days vs the
   NEXT 90 / 180 / 365 days (monthly sampling, players with history on both
   sides). Negative slope = reversal (overreaction), positive = momentum.
   Split by the size / sign of the first move and by position.
2  Season reactions: change from Sep 1 to Feb 1 (the in-season re-price) vs the
   change from Feb 1 to the next Feb 1 — does the season's move hold?
3  Aging: median yearly log change by position x age (KTC's own decay curve).
4  Calendar: median monthly log change by calendar month (seasonality).
"""
import datetime as dt
import json
import math
import os
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '_dyn_cache', 'ktc_alltime.json')
RK = os.path.join(HERE, '_dyn_cache', 'ktc_probe', 'rankings.html')


def series(rec):
    o = rec.get('oneQB') or {}
    out = {}
    for d, v in zip(o.get('d', []), o.get('v', [])):
        if v and v > 0:
            out[dt.date(2000 + int(d[:2]), int(d[2:4]), int(d[4:6]))] = v
    return dict(sorted(out.items()))


def val_at(s, keys, day):
    import bisect
    i = bisect.bisect_right(keys, day) - 1
    if i < 0 or (day - keys[i]).days > 10:
        return None
    return s[keys[i]]


def main():
    import re
    data = json.load(open(SRC, encoding='utf-8'))['players']
    h = open(RK, encoding='utf-8').read()
    meta = {p['playerName']: p for p in json.loads(re.search(r'<script[^>]*id="ktc-players"[^>]*>(\[.*?\])\s*</script>', h, re.S).group(1))}
    P = {}
    for n, rec in data.items():
        s = series(rec)
        if len(s) > 60:
            bd = meta.get(n, {}).get('birthday')
            birth = dt.date.fromtimestamp(int(bd)) if bd and str(bd).isdigit() else None
            P[n] = {'pos': rec['pos'], 's': s, 'k': list(s), 'birth': birth}
    print(f'{len(P)} players with history; first date {min(min(p["k"]) for p in P.values())}')
    first = dt.date(2021, 4, 1); last = max(max(p['k']) for p in P.values())
    months = []
    d = first
    while d <= last:
        months.append(d)
        d = (d.replace(day=1) + dt.timedelta(days=32)).replace(day=1)

    print('\n=== 1. Overreaction vs momentum (monthly samples; slope of NEXT change on PAST change, log value) ===')
    print('   SURVIVORSHIP: today\'s top players -> continuation reads too strong.')
    print(f'{"past window":<12}{"next 90d":>10}{"next 180d":>11}{"next 365d":>11}{"n (365d)":>10}')
    for past in (30, 90):
        cells = []
        for nxt in (90, 180, 365):
            X, Y = [], []
            for p in P.values():
                for m in months:
                    a, b, c = val_at(p['s'], p['k'], m - dt.timedelta(days=past)), val_at(p['s'], p['k'], m), val_at(p['s'], p['k'], m + dt.timedelta(days=nxt))
                    if a and b and c and b >= 1000:
                        X.append(math.log(b / a)); Y.append(math.log(c / b))
            X, Y = np.array(X), np.array(Y)
            slope = np.polyfit(X, Y, 1)[0] if len(X) > 30 else float('nan')
            cells.append((slope, len(X)))
        print(f'{past:>4} days   ' + ''.join(f'{c[0]:>+10.2f}' if i == 0 else f'{c[0]:>+11.2f}' for i, c in enumerate(cells)) + f'{cells[-1][1]:>10}')
    print('   by size of the past-90d move -> median next-180d change:')
    buckets = defaultdict(list)
    for p in P.values():
        for m in months:
            a, b, c = val_at(p['s'], p['k'], m - dt.timedelta(days=90)), val_at(p['s'], p['k'], m), val_at(p['s'], p['k'], m + dt.timedelta(days=180))
            if a and b and c and b >= 1000:
                x = math.log(b / a)
                key = 'fell 30%+' if x < -0.36 else 'fell 10-30%' if x < -0.11 else 'flat (+/-10%)' if x < 0.10 else 'rose 10-30%' if x < 0.26 else 'rose 30%+'
                buckets[key].append(math.log(c / b))
    for key in ('fell 30%+', 'fell 10-30%', 'flat (+/-10%)', 'rose 10-30%', 'rose 30%+'):
        xs = buckets[key]
        if xs:
            print(f'     {key:<15} next 180d {(math.exp(np.median(xs)) - 1) * 100:+5.0f}%   (n={len(xs)})')
    print('   by position (past 90d -> next 180d slope):')
    for pos in ('QB', 'RB', 'WR', 'TE'):
        X, Y = [], []
        for p in P.values():
            if p['pos'] != pos:
                continue
            for m in months:
                a, b, c = val_at(p['s'], p['k'], m - dt.timedelta(days=90)), val_at(p['s'], p['k'], m), val_at(p['s'], p['k'], m + dt.timedelta(days=180))
                if a and b and c and b >= 1000:
                    X.append(math.log(b / a)); Y.append(math.log(c / b))
        if len(X) > 30:
            print(f'     {pos}: {np.polyfit(X, Y, 1)[0]:+.2f} (n={len(X)})')

    print('\n=== 2. Season reactions: Sep 1 -> Feb 1 (the season re-price) vs the following year (Feb 1 -> Feb 1) ===')
    X, Y, rows = [], [], []
    for n, p in P.items():
        for yr in (2021, 2022, 2023, 2024):
            a = val_at(p['s'], p['k'], dt.date(yr, 9, 1)); b = val_at(p['s'], p['k'], dt.date(yr + 1, 2, 1)); c = val_at(p['s'], p['k'], dt.date(yr + 2, 2, 1))
            if a and b and c and max(a, b) >= 1500:
                X.append(math.log(b / a)); Y.append(math.log(c / b)); rows.append((n, yr, a, b, c))
    if len(X) > 20:
        X, Y = np.array(X), np.array(Y)
        print(f'   slope of next-year change on the season move: {np.polyfit(X, Y, 1)[0]:+.2f} (n={len(X)}; -1 = full reversal, 0 = holds, + = keeps going)')
        for lbl, lo, hi in (('season move up 25%+', 0.22, 9), ('up 0-25%', 0, 0.22), ('down 0-25%', -0.29, 0), ('down 25%+', -9, -0.29)):
            ys = [y for x, y in zip(X, Y) if lo <= x < hi]
            if ys:
                print(f'     {lbl:<22} next year {(math.exp(np.median(ys)) - 1) * 100:+5.0f}% (n={len(ys)})')

    print('\n=== 3. KTC aging: median yearly change (Feb 1 -> next Feb 1) by position x age on Feb 1 ===')
    print('   SURVIVORSHIP: players who collapsed out of KTC are missing -> declines read too mild.')
    cells = defaultdict(list)
    for p in P.values():
        if not p['birth']:
            continue
        for yr in range(2022, 2026):
            a, b = val_at(p['s'], p['k'], dt.date(yr, 2, 1)), val_at(p['s'], p['k'], dt.date(yr + 1, 2, 1))
            if a and b and a >= 1000:
                age = (dt.date(yr, 2, 1) - p['birth']).days / 365.25
                band = '<=23' if age < 24 else '24-25' if age < 26 else '26-27' if age < 28 else '28-29' if age < 30 else '30+'
                cells[(p['pos'], band)].append(math.log(b / a))
    bands = ['<=23', '24-25', '26-27', '28-29', '30+']
    print(f'{"pos":<5}' + ''.join(f'{b:>13}' for b in bands))
    for pos in ('QB', 'RB', 'WR', 'TE'):
        print(f'{pos:<5}' + ''.join((f'{(math.exp(np.median(cells[(pos, b)])) - 1) * 100:+6.0f}% ({len(cells[(pos, b)])})' if len(cells[(pos, b)]) >= 4 else '—').rjust(13) for b in bands))

    print('\n=== 4. Calendar: median month-over-month change by calendar month (all players, all years) ===')
    mon = defaultdict(list)
    for p in P.values():
        for m in months:
            a, b = val_at(p['s'], p['k'], m), val_at(p['s'], p['k'], (m + dt.timedelta(days=32)).replace(day=1))
            if a and b and a >= 1000:
                mon[m.month].append(math.log(b / a))
    names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    print('   ' + '  '.join(f'{names[i - 1]} {(math.exp(np.median(mon[i])) - 1) * 100:+.1f}%' for i in range(1, 13) if mon[i]))


if __name__ == '__main__':
    main()
