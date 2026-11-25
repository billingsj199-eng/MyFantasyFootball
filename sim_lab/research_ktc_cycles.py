#!/usr/bin/env python3
"""
research_ktc_cycles.py - do dynasty values move in a repeatable yearly cycle?
(Jack 2026-11-24: "dynasty values move up and down cyclically too so if we can create more true
predictive values it can give us a big leg up for players that are sell highs or buy lows in
season/offseason")

Full archived KTC lists 2021-26 (ktc_lasting_panel.py), values on one scale by rank. The year is
cut into four windows using the lists closest to mid-January, mid-May (after the NFL draft),
mid/late August (before week 1) and mid-November:
    WINTER   Jan -> May    free agency + the draft
    SUMMER   May -> Aug    camp / hype season
    FALL     Aug -> Nov    first half of the season
    LATE     Nov -> Jan    second half + fantasy playoffs
For each window and player group: average move in value (KTC top 200 at the start of the window),
year by year, so a pattern only counts if it repeats. Rookie picks are put on the same scale
(value -> the player rank it equals that day).

Then: is the cycle tradeable out of sample? For each window, groups are ranked by their average
move in the OTHER years; "buy" = top third of players by that expected move, "sell" = bottom third;
what happened in the held-out year.

Usage: python research_ktc_cycles.py [--fmt 1qb|sf]
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.join(HERE, '_dyn_cache', 'ktc_wb')
ANCH = (('WINTER Jan->May', (1, 15), (5, 20)), ('SUMMER May->Aug', (5, 20), (8, 20)), ('FALL   Aug->Nov', (8, 20), (11, 15)), ('LATE   Nov->Jan', (11, 15), (13, 15)))
TOL = 40
LOG = None


def out(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    LOG.write(s + '\n')


def nearest(dates, y, md):
    m, d = md
    t = pd.Timestamp(y + (1 if m > 12 else 0), m - 12 if m > 12 else m, d)
    c = [x for x in dates if abs((x - t).days) <= TOL]
    return min(c, key=lambda x: abs((x - t).days)) if c else None


def group(r):
    if r.exp == 0:
        return 'rookie %s' % r.pos
    a = r.age
    if r.pos == 'RB':
        b = 'young (<24)' if a < 24 else 'prime (24-25.5)' if a < 25.5 else 'older (25.5+)'
    elif r.pos == 'WR':
        b = 'young (<24.5)' if a < 24.5 else 'prime (24.5-26.5)' if a < 26.5 else 'older (26.5+)'
    elif r.pos == 'TE':
        b = 'young (<25.5)' if a < 25.5 else 'prime (25.5-27.5)' if a < 27.5 else 'older (27.5+)'
    else:
        b = 'young (<27)' if a < 27 else 'prime (27-30)' if a < 30 else 'older (30+)'
    return '%s %s' % (r.pos, b)


def picks(fmt, ref):
    """Rookie pick values on the player scale: {date: {(years to that draft, round): value}}."""
    key = 'oneQBValues' if fmt == '1qb' else 'superflexValues'
    res = {}
    for f in sorted(glob.glob(os.path.join(WB, 'wb_*.json'))):
        P = json.load(open(f, encoding='utf-8'))
        ts = os.path.basename(f)[3:11]
        d = pd.Timestamp(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))
        pv = np.sort([(p.get(key) or {}).get('value') or 0 for p in P if p.get('position') in ('QB', 'RB', 'WR', 'TE')])[::-1]
        if len(pv) < 300:
            continue
        acc = {}
        for p in P:
            if p.get('position') != 'RDP':
                continue
            nm = str(p.get('playerName'))
            v = (p.get(key) or {}).get('value')
            parts = nm.split()
            if not v or len(parts) < 2 or not parts[0].isdigit():
                continue
            rd = parts[-1]
            if rd not in ('1st', '2nd', '3rd'):
                continue
            if pd.Timestamp(int(parts[0]), 4, 27) <= d:
                continue
            rank = int((pv > v).sum()) + 1
            acc.setdefault((int(parts[0]), rd), []).append(ref[min(rank, len(ref)) - 1])
        res[d] = {k: float(np.mean(v)) for k, v in acc.items()}
    return res


def main():
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument('--fmt', default='1qb')
    a = ap.parse_args()
    LOG = open(os.path.join(WB, 'cycles_%s.log' % a.fmt), 'w', encoding='utf-8')
    n, k = ('n1', 'k1') if a.fmt == '1qb' else ('ns', 'ks')
    P = pd.read_parquet(os.path.join(WB, 'panel.parquet'))
    P = P[P.full & P.age.notna()].copy()
    dates = sorted(P.date.unique())
    ref = json.load(open(os.path.join(WB, 'ref_curve.json')))['v1' if a.fmt == '1qb' else 'vs']
    PK = picks(a.fmt, ref)
    val = {d: P[P.date == d].set_index('kid')[n] for d in dates}
    rows = []
    for y in range(2021, 2027):
        for lab, m0, m1 in ANCH:
            d0, d1 = nearest(dates, y, m0), nearest(dates, y, m1)
            if d0 is None or d1 is None or d1 <= d0:
                continue
            A = P[(P.date == d0) & (P[k] <= 200)]
            v1 = val[d1]
            for r in A.itertuples():
                x0 = getattr(r, n)
                x1 = float(v1.get(r.kid, 0.0))
                rows.append({'win': lab, 'yr': y, 'd0': d0, 'd1': d1, 'kid': r.kid, 'name': r.name, 'grp': group(r), 'v0': x0, 'v1': x1,
                             'mv': np.log((x1 + 300) / (x0 + 300)), 'krank': getattr(r, k)})
            for (dy, rd), x0 in PK.get(d0, {}).items():
                # the same pick at the end of the window (a pick whose draft happened inside the window has no later value)
                x1 = PK.get(d1, {}).get((dy, rd))
                near = (pd.Timestamp(dy, 4, 27) - d0).days <= 365
                if x1 is not None:
                    rows.append({'win': lab, 'yr': y, 'd0': d0, 'd1': d1, 'kid': -1, 'name': '', 'grp': 'PICK %s %s' % ('next draft' if near else 'draft after', rd),
                                 'v0': x0, 'v1': x1, 'mv': np.log((x1 + 300) / (x0 + 300)), 'krank': 0})
    X = pd.DataFrame(rows)
    out('KTC yearly cycle | %s | windows with data:' % a.fmt)
    for lab, _, _ in ANCH:
        z = X[X.win == lab].drop_duplicates(['yr'])
        out('   %s  ' % lab + '  '.join('%d: %s -> %s' % (r.yr, r.d0.strftime('%b %d'), r.d1.strftime('%b %d')) for r in z.itertuples()))
    out('\n=== A. AVERAGE MOVE BY GROUP AND WINDOW (%% change in value; each year, then all years) ===')
    out('    * = same direction in every year with data (3+ years)')
    order = sorted(X.grp.unique(), key=lambda g: (g.startswith('PICK'), g.startswith('rookie'), g))
    tab = {}
    for lab, _, _ in ANCH:
        W = X[X.win == lab]
        yrs = sorted(W.yr.unique())
        out('\n  %s' % lab)
        out('    %-26s %s %9s' % ('group', ''.join('%8d' % y for y in yrs), 'average'))
        for g in order:
            Z = W[W.grp == g]
            per = Z.groupby('yr').mv.mean()
            cnt = Z.groupby('yr').size()
            per = per[cnt >= (1 if g.startswith('PICK') else 6)]
            if len(per) < 2:
                continue
            pct = 100 * (np.exp(per) - 1)
            same = len(per) >= 3 and (all(pct > 1) or all(pct < -1))
            tab[(lab, g)] = (float(pct.mean()), same, len(per))
            out('    %-26s %s %+8.1f%%%s' % (g, ''.join(('%+7.0f%%' % pct[y]) if y in pct.index else '       -' for y in yrs), pct.mean(), ' *' if same else ''))
    out('\n=== B. THE REPEATING PART: groups that moved the same way every year ===')
    for lab, _, _ in ANCH:
        ups = sorted([(v[0], g) for (w, g), v in tab.items() if w == lab and v[1] and v[0] > 0], reverse=True)
        dns = sorted([(v[0], g) for (w, g), v in tab.items() if w == lab and v[1] and v[0] < 0])
        out('  %s' % lab)
        out('     rises:  ' + (', '.join('%s %+.0f%%' % (g, v) for v, g in ups) or '-'))
        out('     falls:  ' + (', '.join('%s %+.0f%%' % (g, v) for v, g in dns) or '-'))
    out('\n=== C. IS THE CYCLE TRADEABLE? held-out year: buy the third of players whose GROUP rose most in the other years, sell the bottom third ===')
    Pl = X[X.kid >= 0]
    for lab, _, _ in ANCH:
        W = Pl[Pl.win == lab]
        yrs = sorted(W.yr.unique())
        res = []
        for y in yrs:
            tr, te = W[W.yr != y], W[W.yr == y].copy()
            if tr.yr.nunique() < 2:
                continue
            exp = tr.groupby(['yr', 'grp']).mv.mean().groupby('grp').mean()
            te['e'] = te.grp.map(exp)
            te = te[te.e.notna()]
            q = te.e.quantile([1 / 3, 2 / 3]).tolist()
            b, s = te[te.e >= q[1]], te[te.e <= q[0]]
            res.append((y, 100 * (np.exp(b.mv.mean()) - 1), 100 * (np.exp(s.mv.mean()) - 1)))
        if res:
            out('  %s  ' % lab + '  '.join('%d: buy %+.0f%% / sell %+.0f%%' % r for r in res)
                + '   | average spread %+.1f pts, right way in %d of %d years' % (np.mean([r[1] - r[2] for r in res]), sum(r[1] > r[2] for r in res), len(res)))
    X.to_parquet(os.path.join(WB, 'cycles_%s.parquet' % a.fmt), index=False)
    LOG.close()


if __name__ == '__main__':
    sys.exit(main())
