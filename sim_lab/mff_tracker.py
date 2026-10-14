#!/usr/bin/env python3
"""
mff_tracker.py — forward check of MFF VALUE / FAIR calls (Jack 2026-10-09:
"set up the tracker"). Every day the 9am job saves the day's FAIR table (1QB +
SF, PPR) next to KTC; later, eval scores whether KTC moved toward the calls.

  python mff_tracker.py snapshot            # today's table from the site data
  python mff_tracker.py backfill            # weekly 2026 tables from DYNASTY_SIM_HISTORY
                                            # x KTC_HISTORY (preseason .. now)
  python mff_tracker.py eval [--h 30 60 90] # score every snapshot old enough

Snapshots: _dyn_cache/mff_tracker/<date>_<fmt>.json {date, fmt, src, rows:[...]}
(rows = mff_value.fair_table output). Future KTC values come from later
snapshots, else data/ktc_history.js.
EVAL per horizon h: excess = log(KTC at t+h / KTC at t) minus the pool median
change that day (market drift). Reported for BUY LOW / SELL HIGH (fair +-10%),
SIM GAP BUY / SELL and everyone else, plus the Spearman of fairDiff with the
excess change (does a bigger fair gap mean a bigger move toward fair?).
"""
import argparse
import datetime as dt
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mff_value as MV  # noqa: E402

SITE_DATA = os.path.join(os.path.dirname(HERE), 'MyFantasyFootball Files', 'data')
OUT = os.path.join(HERE, '_dyn_cache', 'mff_tracker')
FMTS = (('1qb', 'KTC_1QB', 'v1'), ('sf', 'KTC_SF', 'vsf'))


def save(date, fmt, src, rows):
    os.makedirs(OUT, exist_ok=True)
    json.dump({'date': date, 'fmt': fmt, 'src': src, 'rows': rows},
              open(os.path.join(OUT, f'{date}_{fmt}.json'), 'w', encoding='utf-8'), separators=(',', ':'))


def capture_votes(day):
    """KTC crowd sentiment (Jack 2026-10-09: "add the keep trade cut capture to the
    tracker"): every player's cumulative keep / trade / cut votes + value, 1QB and SF,
    from the KTC rankings page (#ktc-players JSON) -> _dyn_cache/mff_tracker/
    ktc_votes_<date>.json. No history exists anywhere, so this starts the series;
    later test: does a rising keep share / falling cut share lead KTC value moves?
    One polite GET a day; numpy-free (the 9am job's Python)."""
    import re
    import urllib.request
    req = urllib.request.Request('https://keeptradecut.com/dynasty-rankings',
                                 headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36',
                                          'Accept': 'text/html'})
    with urllib.request.urlopen(req, timeout=60) as r:
        h = r.read().decode('utf-8', 'replace')
    m = re.search(r'<script[^>]*id="ktc-players"[^>]*>(\[.*?\])\s*</script>', h, re.S)
    if not m:
        raise RuntimeError('KTC #ktc-players JSON not found (template changed?)')
    out = {}
    for p in json.loads(m.group(1)):
        n = p.get('playerName')
        if not n:
            continue
        rec = {'pos': p.get('position'), 'id': p.get('playerID')}
        for fk, tag in (('oneQBValues', '1qb'), ('superflexValues', 'sf')):
            v = p.get(fk) or {}
            rec[tag] = [v.get('value'), v.get('kept'), v.get('traded'), v.get('cut'), v.get('rank')]
        out[n] = rec
    os.makedirs(OUT, exist_ok=True)
    json.dump({'date': day, 'fields': 'value, kept, traded, cut, rank', 'players': out},
              open(os.path.join(OUT, f'ktc_votes_{day}.json'), 'w', encoding='utf-8'), separators=(',', ':'))
    return len(out)


def snapshot():
    try:
        n = capture_votes(dt.date.today().isoformat())
        print(f'KTC keep/trade/cut votes: {n} players saved')
    except Exception as e:
        print('KTC vote capture FAILED (snapshot continues):', e)
    sim = MV.load_js_json(os.path.join(SITE_DATA, 'dynasty_sim_2026.js'))
    mkt = sim['meta'].get('mktNext')
    today = dt.date.today().isoformat()
    try:
        qbtt = MV.qb_team_totals(SITE_DATA)
    except Exception as e:   # never block the snapshot
        print('QB team totals unavailable (no QB term):', e); qbtt = None
    for fmt, var, _ in FMTS:
        K = MV.load_ktc_map(os.path.join(SITE_DATA, '_bundle_lookups.js'), var)
        try:   # weekly-sim rest-of-2026 (site _mffRosY0Map, 10-10); never block the snapshot
            ros = MV.ros_y0(sim, SITE_DATA, fmt + '_ppr')
        except Exception as e:
            print('weekly-sim y0 unavailable:', e); ros = None
        rows = MV.fair_table(MV.sim_rows_from_file(sim, fmt + '_ppr', ros), K, mkt, sim['meta'].get('rbRec'), qbtt)
        save(today, fmt, 'live', rows)
        print(f'{today} {fmt}: {len(rows)} players, BUY {sum(r["call"] == "BUY" for r in rows)}, SELL {sum(r["call"] == "SELL" for r in rows)}')


def ktc_hist():
    H = MV.load_js_json(os.path.join(SITE_DATA, 'ktc_history.js'))
    return H['dates'], H


def ktc_map_at(H, dates, fk, day, tol=3):
    """{name: value} for the nearest history date within tol days of day."""
    best = None
    for i, d in enumerate(dates):
        g = abs((dt.date.fromisoformat(d) - day).days)
        if g <= tol and (best is None or g < best[0]):
            best = (g, i)
    if best is None:
        return None
    i = best[1]
    return {n: v[i] for n, v in H[fk].items() if i < len(v) and v[i]}


def backfill():
    sim = MV.load_js_json(os.path.join(SITE_DATA, 'dynasty_sim_2026.js'))
    mkt = sim['meta'].get('mktNext')
    meta = {norm_k: e for norm_k, e in ((MV.norm(e['n']) + '|' + e['pos'], e) for e in sim['players'].values())}
    SH = MV.load_js_json(os.path.join(SITE_DATA, 'dynasty_sim_history.js'))
    dates, H = ktc_hist()
    for wi, wk in enumerate(SH['weeks']):
        day = dt.date.fromisoformat(wk['date'])
        for fmt, _, fk in FMTS:
            K = ktc_map_at(H, dates, fk, day)
            if not K:
                print(f'{wk["date"]} {fmt}: no KTC history near that date'); continue
            rows = []
            for key, rec in SH['p'].items():
                n, pos = key.rsplit('|', 1)
                if pos == 'PICK':
                    continue
                pt = (rec.get(fmt) or [None] * (wi + 1))[wi] if wi < len(rec.get(fmt) or []) else None
                if not pt:
                    continue
                e = meta.get(MV.norm(n) + '|' + pos) or {}
                rows.append({'n': n, 'pos': pos, 'val': pt[0], 'age': e.get('age'), 'rookie': bool(e.get('rookie')), 'rbr': e.get('rbr')})
            tab = MV.fair_table(rows, K, mkt, sim['meta'].get('rbRec'))
            save(wk['date'], fmt, 'backfill (sim history week %d x KTC history)' % wk['w'], tab)
            print(f'{wk["date"]} {fmt}: {len(tab)} players, BUY {sum(r["call"] == "BUY" for r in tab)}, SELL {sum(r["call"] == "SELL" for r in tab)}')


def evaluate(horizons):
    import numpy as np   # eval only — the 9am job's Python runs snapshot without numpy
    snaps = {}
    for fp in sorted(glob.glob(os.path.join(OUT, '*.json'))):
        s = json.load(open(fp, encoding='utf-8'))
        snaps[(s['date'], s['fmt'])] = s
    dates, H = ktc_hist()
    today = dt.date.today()

    def future_val(fmt, fk, n, day):
        # later snapshot first (exact daily KTC), else KTC history
        s = snaps.get((day.isoformat(), fmt))
        if s:
            for r in s['rows']:
                if MV.norm(r['n']) == MV.norm(n):
                    return r['kv']
        K = ktc_map_at(H, dates, fk, day)
        if K:
            for k, v in K.items():
                if MV.norm(k) == MV.norm(n):
                    return v
        return None
    print(f'snapshots: {len(snaps)} ({min(d for d, _ in snaps) if snaps else "-"} .. {max(d for d, _ in snaps) if snaps else "-"})')
    for fmt, _, fk in FMTS:
        for h in horizons:
            buckets = {k: [] for k in ('FAIR BUY', 'FAIR SELL', 'SIM GAP BUY', 'SIM GAP SELL', 'no call')}
            sp = []
            used = 0
            for (d, f), s in sorted(snaps.items()):
                if f != fmt:
                    continue
                t0 = dt.date.fromisoformat(d)
                if t0 + dt.timedelta(days=h) > today:
                    continue
                used += 1
                ch = []
                for r in s['rows']:
                    v1 = future_val(fmt, fk, r['n'], t0 + dt.timedelta(days=h))
                    if v1:
                        ch.append((r, math.log(v1 / r['kv'])))
                if len(ch) < 30:
                    continue
                med = float(np.median([c for _, c in ch]))
                fds, exs = [], []
                for r, c in ch:
                    ex = c - med
                    fds.append(r['fd']); exs.append(ex)
                    if r['call'] == 'BUY': buckets['FAIR BUY'].append(ex)
                    if r['call'] == 'SELL': buckets['FAIR SELL'].append(ex)
                    if r['gcall'] == 'BUY': buckets['SIM GAP BUY'].append(ex)
                    if r['gcall'] == 'SELL': buckets['SIM GAP SELL'].append(ex)
                    if not r['call'] and not r['gcall']: buckets['no call'].append(ex)
                from scipy.stats import spearmanr  # noqa: E402
                sp.append(spearmanr(fds, exs).correlation)
            if not used:
                print(f'\n{fmt.upper()} +{h}d: no snapshot old enough yet'); continue
            print(f'\n{fmt.upper()} +{h}d  ({used} snapshots; excess = KTC change minus that day\'s pool median)')
            for k, xs in buckets.items():
                if xs:
                    up = np.mean([x > 0 for x in xs])
                    print(f'   {k:<14} n {len(xs):>4}  mean {(math.exp(np.mean(xs)) - 1) * 100:+5.1f}%  median {(math.exp(np.median(xs)) - 1) * 100:+5.1f}%  beat the market {up:.0%}')
            if sp:
                print(f'   Spearman(fairDiff, excess change): {np.mean(sp):+.3f} (avg over snapshots)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=('snapshot', 'backfill', 'eval'))
    ap.add_argument('--h', nargs='*', type=int, default=[30, 60, 90])
    a = ap.parse_args()
    if a.cmd == 'snapshot':
        snapshot()
    elif a.cmd == 'backfill':
        backfill()
    else:
        evaluate(a.h)


if __name__ == '__main__':
    main()
