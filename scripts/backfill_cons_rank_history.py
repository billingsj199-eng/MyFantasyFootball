#!/usr/bin/env python3
"""
One-off backfill of data/cons_rank_history.json from git.

The consensus redraft board is a client-side blend (_computeConsensusBoard in
app.js) of Jack's board + seven per-player source inputs that live in d.js:
  a (market ADP) · slR (Sleeper) · fpR (FantasyPros) · udA (Underdog) ·
  espnAdp · cbsAdp · yahooAdp
The 9am job commits d.js daily, so every day's last commit touching data/d.js
is a snapshot of those inputs. The site rebuilds the board for any snapshot
with the same function (RANKINGS MOVERS, free/anon sessions).

File: {updated, fields:[...], days:[{date, f:{name:[a, slR, fpR, udA, espnAdp,
cbsAdp, yahooAdp]}}]} — players with at least one input, capped at the top
--top by market ADP. pull_consensus_adp.py rolls it forward every morning.

    python scripts/backfill_cons_rank_history.py [--days 45] [--top 400]
"""
import argparse, datetime, json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'cons_rank_history.json')
FIELDS = ['a', 'slR', 'fpR', 'udA', 'espnAdp', 'cbsAdp', 'yahooAdp']


def fields_from_djs(src, top):
    body = src[src.index('['):src.rindex(']') + 1]
    D = json.loads(body)
    rows = []
    for p in D:
        if not p.get('n') or p.get('s') in ('K', 'DST'):
            continue
        vals = [p.get(f) if isinstance(p.get(f), (int, float)) else None for f in FIELDS]
        if all(v is None for v in vals):
            continue
        rows.append((p['n'], vals))
    rows.sort(key=lambda r: (r[1][0] if r[1][0] is not None else 9999))
    return {n: v for n, v in rows[:top]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=45)
    ap.add_argument('--top', type=int, default=400)
    a = ap.parse_args()
    since = (datetime.date.today() - datetime.timedelta(days=a.days)).isoformat()
    log = subprocess.run(['git', 'log', f'--since={since}', '--format=%ad %H', '--date=short', '--', 'data/d.js'],
                         cwd=ROOT, capture_output=True, text=True, encoding='utf-8').stdout.split('\n')
    last_by_day = {}
    for ln in log:
        ln = ln.strip()
        if not ln:
            continue
        day, sha = ln.split()
        last_by_day.setdefault(day, sha)   # newest-first log: first seen = last commit that day
    days = []
    for day in sorted(last_by_day):
        sha = last_by_day[day]
        src = subprocess.run(['git', 'show', f'{sha}:data/d.js'], cwd=ROOT, capture_output=True, text=True, encoding='utf-8').stdout
        try:
            f = fields_from_djs(src, a.top)
        except Exception as e:  # noqa: BLE001
            print(f'  {day} {sha[:7]}: unreadable ({e})')
            continue
        days.append({'date': day, 'f': f})
        print(f'  {day} {sha[:7]}: {len(f)} players')
    hist = {'updated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'fields': FIELDS, 'days': days}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(hist, f, separators=(',', ':'))
    print(f'wrote {OUT}: {len(days)} days ({os.path.getsize(OUT) // 1024} KB)')


if __name__ == '__main__':
    sys.exit(main())
