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

Output: <site>/data/mff_lasting_edge.js
    window.MFF_LASTING_EDGE = {updated, src, w: {m3, sim, mkt}, k, p: {"<name>|<POS>": [edge 1QB, edge SF]}}
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
    a = ap.parse_args()
    src = None
    if not a.no_rebuild:
        src, hit, n = LR.refresh_today()
        print('today = %s re-priced from the site KTC maps (%d of %d matched)' % (src, hit, n))
    P = {}
    for i, fmt in enumerate(('1qb', 'sf')):
        now = LR.compute(SimpleNamespace(fmt=fmt, rate=12.0, top=300, no_rebuild=True))
        for r in now.itertuples():
            e = float(r.edge)
            if e != e:
                continue
            P.setdefault(site_norm(r.name) + '|' + r.pos, [0.0, 0.0])[i] = round(max(-CLIP, min(CLIP, e)), 3)
        print('%s: %d players, edge mean %+.3f, min %+.3f, max %+.3f' % (fmt, len(now), now.edge.mean(), now.edge.min(), now.edge.max()))
    if len(P) < MIN_PLAYERS:
        print('ABORT: only %d players with an edge (< %d) - file not written' % (len(P), MIN_PLAYERS))
        return 3
    out = {'updated': dt.date.today().isoformat(), 'src': src or 'panel', 'w': W, 'k': K, 'p': dict(sorted(P.items()))}
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
