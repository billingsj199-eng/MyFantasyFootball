#!/usr/bin/env python3
"""
build_lasting_edge.py - the per-player age / health EDGE the re-tuned MFF VALUE order reads
(proposal P-20261124-1, Jack 2026-11-24 "Approve, build it").

MFF VALUE (FAIR) order becomes
    z = 0.25 M3 + 0.15 log sim rank + 0.75 log KTC rank - 1.0 x EDGE      (lower = better)
EDGE = (lasting-value rating total - the average total at the same KTC price) / price,
neutral dial (12 KTC per point), from ktc_lasting_rating.py; clipped to +-0.5.
Backtest: backtest_fair_retune_tr.py + reviews/2026-11-24_ktc_lasting_value_study.md (addendum 2).

The file carries the weights too, so the site (app.js _fairW) and the tracker's Python port
(mff_value.py) read ONE source. No file / empty file = the old shipped weights, no edge.

VALUE FORECAST (Jack 2026-11-24 "Yes, build it"): the same file also carries each player's expected
value change over 3 and 6 months and his window (ktc_value_forecast.py; backtest_ktc_forecast.py).

Output: <site>/data/mff_lasting_edge.js
    window.MFF_LASTING_EDGE = {updated, src, w: {m3, sim, mkt}, k, p: {"<name>|<POS>": [edge 1QB, edge SF]},
        r: {"<name>|<POS>": [rolled rank 1QB, SF]}, rc: {from, asof, lag, share}   only while KTC is frozen in season (ktc_roll.py),
        f: {"<name>|<POS>": [3 mo %, 6 mo %, window, 3 mo % SF, 6 mo % SF, window SF]},   window -1 sell / +1 buy / 0
        fc: {date (the price the forecast starts from), top, q, med: {"1qb": [3 mo, 6 mo], "sf": [...]}}}
    name = app.js _dynSimNorm(name) (lowercase, suffix dropped, . - ' removed)
Usage: python build_lasting_edge.py --site "<repo or worktree>" [--no-rebuild] [--dry-run]
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ktc_lasting_rating as LR  # noqa: E402

W = {'m3': 0.25, 'sim': 0.15, 'mkt': 0.75}
K = 1.0
CLIP = 0.5
MIN_PLAYERS = 200


def site_norm(n):
    """app.js _dynSimNorm."""
    s = str(n or '').lower()
    s = re.sub(r'\s+(jr\.?|sr\.?|iii|ii|iv|v)$', '', s)
    s = re.sub(r"[.\-']", '', s)
    return re.sub(r'\s+', ' ', s).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site', required=True, help='repo / worktree root (writes data/mff_lasting_edge.js)')
    ap.add_argument('--no-rebuild', action='store_true', help='reuse the panel as it is')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--no-forecast', action='store_true', help='edge + weights only')
    a = ap.parse_args()
    if not a.no_rebuild:
        LR.refresh_today()
    try:
        st = json.load(open(os.path.join(LR.WB, 'today_state.json')))
    except (OSError, ValueError):
        st = {'freeze': dt.date.today().isoformat(), 'lag': 0, 'share': 0.0, 'rolled': False}
    print('KTC last changed %s (%d days ago); prices %s' % (st['freeze'], st['lag'],
          ('ROLLED in-house, %.0f%% of the predicted move' % (100 * st['share'])) if st['rolled'] else 'as tracked'))
    P = {}
    for i, fmt in enumerate(('1qb', 'sf')):
        now = LR.compute(SimpleNamespace(fmt=fmt, rate=12.0, top=300, no_rebuild=True))
        for r in now.itertuples():
            e = float(r.edge)
            if e != e:
                continue
            P.setdefault(site_norm(r.name) + '|' + r.pos, [0.0, 0.0])[i] = round(max(-CLIP, min(CLIP, e)), 3)
        print('%s: %d players, edge mean %+.3f, min %+.3f, max %+.3f' % (fmt, len(now), now.edge.mean(), now.edge.min(), now.edge.max()))
    FC, med, fdate = {}, {}, None
    if not a.no_forecast:
        import subprocess
        import ktc_value_forecast as VF
        for i, fmt in enumerate(('1qb', 'sf')):
            try:
                if not a.no_rebuild:
                    subprocess.run([sys.executable, '-I', os.path.join(HERE, 'backtest_ktc_forecast.py'), '--fmt', fmt, '--rebuild', '--today-only'],
                                   check=True, stdout=subprocess.DEVNULL)
                Wd = VF.today(fmt)
            except Exception as e:  # noqa: BLE001 - the edge still ships without a forecast for this format
                print('forecast %s FAILED (left out): %s' % (fmt, e))
                continue
            med[fmt] = [round(Wd.attrs['med3'], 1), round(Wd.attrs['med6'], 1)]
            fdate = Wd.attrs['date']
            for r in Wd.itertuples():
                if r.f3 != r.f3 or r.f6 != r.f6:
                    continue
                x = FC.setdefault(site_norm(r.name) + '|' + r.pos, [None] * 6)
                x[3 * i:3 * i + 3] = [round(float(r.f3), 1), round(float(r.f6), 1), int(r.win)]
            print('forecast %s (%s): %d players, typical top-%d move %+.1f%% / %+.1f%%, sell windows %d, buy windows %d'
                  % (fmt, fdate, len(Wd), VF.TOP, med[fmt][0], med[fmt][1], (Wd.win == -1).sum(), (Wd.win == 1).sum()))
    if len(P) < MIN_PLAYERS:
        print('ABORT: only %d players with an edge (< %d) - file not written' % (len(P), MIN_PLAYERS))
        return 3
    out = {'updated': dt.date.today().isoformat(), 'src': 'rolled' if st['rolled'] else 'tracked', 'w': W, 'k': K, 'p': dict(sorted(P.items()))}
    if FC and med:
        import ktc_value_forecast as VF
        # the forecast starts from today's price only while that price is being rolled; a frozen price keeps its own date
        out['fc'] = {'date': fdate if st['rolled'] else min(fdate, st['freeze']), 'top': VF.TOP, 'q': VF.Q, 'med': med}
        out['f'] = dict(sorted(FC.items()))
    if st['rolled']:
        import pandas as pd
        RR = {}
        for i, fmt in enumerate(('1qb', 'sf')):
            r = pd.read_parquet(os.path.join(LR.WB, 'rolled_%s.parquet' % fmt))
            for x in r.itertuples():
                RR.setdefault(site_norm(x.name) + '|' + x.pos, [0, 0])[i] = int(x.rank)
        out['rc'] = {'from': st['freeze'], 'asof': st['asof'], 'lag': st['lag'], 'share': st['share']}
        out['r'] = dict(sorted(RR.items()))
        print('rolled order written for %d players (frozen %s, %d days, share %.2f)' % (len(RR), st['freeze'], st['lag'], st['share']))
    body = ('/* MFF VALUE age / health edge (sim_lab/build_lasting_edge.py). EDGE = lasting-value rating total vs the\n'
            '   average at the same KTC price, share of price; + holds value, - melts. [1QB, SF]. Weights ride along. */\n'
            'window.MFF_LASTING_EDGE = ' + json.dumps(out, separators=(',', ':')) + ';\n')
    f = os.path.join(a.site, 'data', 'mff_lasting_edge.js')
    if a.dry_run:
        print('dry run: would write %s (%d players, %d bytes)' % (f, len(P), len(body)))
        return 0
    with open(f, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(body)
    print('wrote %s: %d players, %d bytes' % (f, len(P), len(body)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
