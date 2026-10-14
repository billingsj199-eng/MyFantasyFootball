#!/usr/bin/env python3
"""
build_dynasty_sim_history.py — weekly Dynasty SIM history for the player-card trend chart.

Each Dynasty SIM build is a snapshot "as of week W". This keeps one entry per
week in <site>/data/dynasty_sim_history.js:
    window.DYNASTY_SIM_HISTORY = {
      updated, weeks: [{w, date}, ...],
      p: {"Name|POS": {"1qb": [[val, ovr, posRk] | null per week], "sf": [...]}}
    }
PPR values (the card chart follows 1QB / SF, not scoring). Ranks are over
players + picks like the board; positional rank over the player's position.

Usage:
  python build_dynasty_sim_history.py --add <dynasty_sim_2026.js> [--date YYYY-MM-DD]
  python build_dynasty_sim_history.py --backfill      # rebuild weeks 0..W-1 with the generator
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import DATA_DIR  # noqa: E402

OUT = os.path.join(DATA_DIR, 'dynasty_sim_history.js')
SEASON_START = datetime.date(2026, 9, 9)   # week 1 Thursday


def load_js(path, var):
    raw = open(path, encoding='utf-8').read()
    return json.JSONDecoder().raw_decode(raw, raw.index('{"'))[0]


def snapshot(sim):
    """{key: {'1qb': [val, ovr, posRk], 'sf': [...]}} from a dynasty_sim_2026.js payload."""
    out = defaultdict(dict)
    for fmt in ('1qb', 'sf'):
        vk = fmt + '_ppr'
        rows = [(k, e) for k, e in sim['players'].items() if vk in e.get('v', {})]
        rows.sort(key=lambda kv: -kv[1]['v'][vk][0])
        pc = defaultdict(int)
        for i, (k, e) in enumerate(rows):
            pc[e['pos']] += 1
            out[k][fmt] = [e['v'][vk][0], i + 1, pc[e['pos']]]
    return out


def add(hist, sim, date):
    w = sim['meta'].get('week', 0)
    weeks = [x for x in hist.get('weeks', []) if x['w'] != w]
    old_weeks = hist.get('weeks', [])
    snap = snapshot(sim)
    weeks.append({'w': w, 'date': date})
    weeks.sort(key=lambda x: x['w'])
    idx_new = {x['w']: i for i, x in enumerate(weeks)}
    p = {}
    keys = set(hist.get('p', {})) | set(snap)
    for k in keys:
        rec = {}
        for fmt in ('1qb', 'sf'):
            series = [None] * len(weeks)
            for j, x in enumerate(old_weeks):
                if x['w'] == w:
                    continue
                prev = hist.get('p', {}).get(k, {}).get(fmt)
                if prev and j < len(prev):
                    series[idx_new[x['w']]] = prev[j]
            if k in snap and fmt in snap[k]:
                series[idx_new[w]] = snap[k][fmt]
            if any(v is not None for v in series):
                rec[fmt] = series
        if rec:
            p[k] = rec
    return {'updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), 'weeks': weeks, 'p': p}


def write(hist):
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write('// Dynasty SIM weekly history (player-card trend chart) — built by sim_lab/build_dynasty_sim_history.py.\n')
        f.write('window.DYNASTY_SIM_HISTORY = ' + json.dumps(hist, separators=(',', ':'), ensure_ascii=False) + ';\n')
    print(f'wrote {OUT}: {len(hist["weeks"])} weeks, {len(hist["p"])} entries, {os.path.getsize(OUT) // 1024} KB')


def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument('--add')
    ap.add_argument('--date')
    ap.add_argument('--backfill', action='store_true')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    OUT = args.out or OUT
    hist = load_js(OUT, 'DYNASTY_SIM_HISTORY') if os.path.exists(OUT) else {}
    if args.backfill:
        cur = load_js(os.path.join(DATA_DIR, 'dynasty_sim_2026.js'), 'DYNASTY_SIM_2026')
        W = cur['meta'].get('week', 0)
        for w in range(0, W):
            tmp = os.path.join(HERE, '_dyn_cache', f'dynasty_sim_w{w}.js')
            if not os.path.exists(tmp):
                subprocess.run([sys.executable, os.path.join(HERE, 'build_dynasty_sim.py'), '--out', tmp, '--week', str(w)],
                               check=True, capture_output=True)
            date = (SEASON_START + datetime.timedelta(days=7 * w - 2)).isoformat() if w else '2026-09-07'
            hist = add(hist, load_js(tmp, 'DYNASTY_SIM_2026'), date)
            print(f'  week {w} added ({date})')
        hist = add(hist, cur, args.date or datetime.date.today().isoformat())
    elif args.add:
        hist = add(hist, load_js(args.add, 'DYNASTY_SIM_2026'), args.date or datetime.date.today().isoformat())
    else:
        ap.error('--add FILE or --backfill')
    write(hist)


if __name__ == '__main__':
    main()
