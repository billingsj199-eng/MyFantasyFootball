#!/usr/bin/env python3
"""
Usage score trend for player cards (admin-only for now) -> data/usage_trend.js

  window.USAGE_TREND = {"<yr>": {"thru": <last week>, "p": {"<name>": [pos, games, season, l3, p3, [[wk, score], ...]]}}}

Scores use the Research page Usage formula: weights in scripts/usage_weights.json (written by
scripts/backtest_usage_score.py; app.js USAGE carries the same numbers - keep them in sync).
  season  usage over every game played this season
  l3      the last 3 games played; p3 = the 3 games before those (None under 4 games)
  week    single-game score
Features are the plain mean of the weekly values, exactly how the backtest was fit. Only
players on the site board (the card only opens for them), latest two seasons with week files.

Trend check (2019-2025 week tables, 2026-09-15): at equal last-3 usage, players who had RISEN
vs the prior 3 games scored fewer next-3-game points and players who had FALLEN scored more
(delta coefficient -0.04 to -0.06 per point for RB / WR / TE; a 3-game change has SD ~15). Usage
mean-reverts, so the card shows the arrow as a description of the change, not a forecast.

  python scripts/build_usage_trend.py
"""
import collections, glob, io, json, os, re, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'usage_trend.js')
WEIGHTS = os.path.join(ROOT, 'scripts', 'usage_weights.json')


def load(p):
    s = open(p, encoding='utf-8').read()
    return json.loads(s[s.index(']=') + 2:].rstrip().rstrip(';'))


def features(o):
    g = o.get('g') or 1
    return {'car': o.get('car') or 0, 'tsh': o.get('tsh') or 0, 'rtp': o.get('rtp') or 0, 'snp': o.get('snp') or 0,
            'ays': o.get('ays') or 0, 'hvtg': (o.get('hvt') or 0) / g, 'rzg': (o.get('rz') or 0) / g}


def score(u, xs):
    if not xs:
        return None
    mean = {k: sum(x[k] for x in xs) / len(xs) for k in xs[0]}
    pred = u['b'] + sum(w * mean.get(k, 0) for k, w in u['w'].items())
    return round(100 * (pred - u['b']) / (u['p99'] - u['b']), 1)


def main():
    weights = json.load(open(WEIGHTS, encoding='utf-8'))
    files = collections.defaultdict(dict)
    for p in glob.glob(os.path.join(ROOT, 'data', 'adv_stats_20??_w*.js')):
        m = re.search(r'_(\d{4})_w(\d+)\.js$', p)
        files[int(m.group(1))][int(m.group(2))] = p
    out = {}
    for yr in sorted(files)[-2:]:
        games = collections.defaultdict(list)   # name -> [(wk, pos, features)]
        for wk in sorted(files[yr]):
            d = load(files[yr][wk])
            for pos in ('RB', 'WR', 'TE'):
                f = d[pos]['f']
                for r in d[pos]['r']:
                    o = dict(zip(f, r))
                    if o.get('g') and o.get('on'):
                        games[o['n']].append((wk, pos, features(o)))
        players = {}
        for name, gl in games.items():
            gl.sort(key=lambda t: t[0])
            pos = collections.Counter(t[1] for t in gl).most_common(1)[0][0]
            u = weights[pos]
            xs = [t[2] for t in gl]
            players[name] = [pos, len(xs), score(u, xs), score(u, xs[-3:]),
                             score(u, xs[-6:-3]) if len(xs) >= 4 else None,
                             [[t[0], score(u, [t[2]])] for t in gl]]
        out[str(yr)] = {'thru': max(files[yr]), 'p': players}
        with_trend = sum(1 for v in players.values() if v[4] is not None)
        print(f'{yr}: thru W{max(files[yr])}  {len(players)} board players  {with_trend} with a 3-vs-3 trend')
    text = 'window.USAGE_TREND=' + json.dumps(out, separators=(',', ':'), ensure_ascii=False, allow_nan=False) + ';\n'
    old = open(OUT, encoding='utf-8').read() if os.path.exists(OUT) else None
    if old != text:
        with open(OUT, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
    print(f'-> data/usage_trend.js ({len(text) // 1024} KB, {"unchanged" if old == text else "written"})')


if __name__ == '__main__':
    main()
