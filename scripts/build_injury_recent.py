#!/usr/bin/env python3
"""
build_injury_recent.py — the last two seasons of each player's injury history
for the player card's INJURY SLIDE sell note (Jack 2026-10-09: "yes add the
repeat injury line").

Why: sim_lab/research_injury_history.py — after a 4+ week absence, players who
were also hurt in the two seasons before slid on KTC about twice as fast early
(-8.2% vs -3.1% at 30 days vs healthy peers, n 12 vs 34). The full history
(data/injury_history.js, nflverse 2009-2025, ~250 KB) isn't loaded on the
site, so this writes just the recent seasons.

Output: data/injury_recent.js
  window.INJURY_RECENT = {seasons: [2024, 2025], built, players: {name: [[season, injury, weeksMissed], ...]}}
Re-run after each season once injury_history.js is rebuilt (seasons = the two
before the current one).

Usage: python scripts/build_injury_recent.py [--last 2025]
"""
import argparse
import datetime
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--last', type=int, default=2025, help='most recent completed season in the history')
    args = ap.parse_args()
    seasons = [args.last - 1, args.last]
    src = open(os.path.join(ROOT, 'data', 'injury_history.js'), encoding='latin-1').read()
    out = {}
    for m in re.finditer(r'INJURY_HISTORY\["(.+?)"\]\s*=\s*(\[.*?\]);', src):
        body = re.sub(r'(\{|,)\s*([A-Za-z]+)\s*:', r'\1"\2":', m.group(2))
        try:
            recs = json.loads(body)
        except Exception:
            continue
        name = m.group(1).encode('latin-1').decode('utf-8', 'replace')
        rec = [[r['season'], r.get('injury') or '', r.get('weeksMissed') or 0] for r in recs if r.get('season') in seasons]
        if rec:
            out[name] = sorted(rec, reverse=True)
    data = {'seasons': seasons, 'built': datetime.date.today().isoformat(), 'source': 'data/injury_history.js (nflverse)', 'players': out}
    path = os.path.join(ROOT, 'data', 'injury_recent.js')
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('// Built by scripts/build_injury_recent.py — do not hand-edit. Card INJURY SLIDE repeat-injury line.\n')
        f.write('window.INJURY_RECENT = ' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n')
    print(f'wrote {path}: {len(out)} players with an injury in {seasons}, {os.path.getsize(path) // 1024} KB')


if __name__ == '__main__':
    main()
