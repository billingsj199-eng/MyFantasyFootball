#!/usr/bin/env python3
"""
research_ktc_drivers.py — what moves KTC dynasty values? (Jack 2026-10-09)

"I want to figure out how value works by analyzing ktc values — what makes
players move up or down — signing contracts, on-field performance, trades, etc."

Data
  KTC daily 1QB values, 2026-04-14 .. 2026-10-09 (KTC's own history endpoint,
  cached in _dyn_cache/ktc_probe/histories.json + rankings.html for id -> player).
  Events dated from this repo's daily commits:
    d.js            team (t) + contract fields (cs signing yr, sal, cn yrs, cg gtd)
    injury_updates  Sleeper injury designation per player
  NFL draft 2026 picks (pbp_cache/draft_picks.parquet); Clay preseason PPG
  (data/mike_clay_projections.js); weekly 2026 fantasy points (weekly_stats_active).
Universe: QB/RB/WR/TE (no picks) with a KTC 1QB value >= 1500 at some point.

Sections
  A  When does value move? share of all |daily log change| by calendar phase.
  B  Event effects: abnormal log change from the day before to 7 days after an
     event, vs the median of same-position players of similar value (no event)
     over the same window — trades / new-team signings, contracts with the same
     team, injury designations (IR / out vs questionable), returns.
  C  NFL draft: rookies' value change across draft week by draft capital.
  D  On-field: weekly value change (Tuesday -> Tuesday) vs fantasy points over
     Clay's preseason expectation that week and season-to-date.
  E  Time decay: 6-month change for players with NO event, by position x age.
  F  The 25 biggest 6-month risers and fallers with their events.
"""
import bisect
import datetime as dt
import json
import math
import os
import re
import statistics as stats
import subprocess
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = r'E:\MyFantasyFootball\MyFantasyFootball Files'
PROBE = os.path.join(HERE, '_dyn_cache', 'ktc_probe')
START, END = '2026-04-14', '2026-10-09'
POS = ('QB', 'RB', 'WR', 'TE')
PHASES = [('pre-draft', '2026-04-14', '2026-04-22'), ('NFL draft week', '2026-04-23', '2026-04-28'),
          ('post-draft / OTAs', '2026-04-29', '2026-06-14'), ('summer dead zone', '2026-06-15', '2026-07-20'),
          ('training camp', '2026-07-21', '2026-08-06'), ('preseason', '2026-08-07', '2026-09-08'),
          ('regular season wk1-5', '2026-09-09', '2026-10-09')]


def norm(n):
    n = re.sub(r'\s+(jr\.?|sr\.?|iii|ii|iv|v)$', '', str(n).lower().strip())
    return re.sub(r"[.\-'’]", '', n).strip()


def day(s):
    return dt.date.fromisoformat(s)


def git(*a):
    return subprocess.run(['git', '-C', REPO, *a], capture_output=True, text=True, encoding='utf-8', errors='replace').stdout


def daily_commits(path, since='2026-04-10'):
    out = {}
    for line in reversed(git('log', '--format=%H %cd', '--date=short', f'--since={since}', '--', path).strip().splitlines()):
        h, d = line.split()
        out[d] = h                      # last commit of each day wins
    return dict(sorted(out.items()))


# ---------------------------------------------------------------- KTC panel
def load_ktc():
    h = open(os.path.join(PROBE, 'rankings.html'), encoding='utf-8').read()
    m = re.search(r'<script[^>]*id="ktc-players"[^>]*>(\[.*?\])\s*</script>', h, re.S)
    meta = {p['playerID']: p for p in json.loads(m.group(1))}
    hist = json.load(open(os.path.join(PROBE, 'histories.json'), encoding='utf-8'))
    panel = {}
    for x in hist:
        p = meta.get(x['playerID'])
        if not p or p.get('position') not in POS:
            continue
        ser = {}
        for pt in (x.get('oneQB') or {}).get('valueHistory') or []:
            pt = str(pt)
            ser[f'20{pt[:2]}-{pt[2:4]}-{pt[4:6]}'] = int(pt[6:])
        if not ser or max(ser.values()) < 1500:
            continue
        panel[norm(p['playerName'])] = {'name': p['playerName'], 'pos': p['position'], 'age': p.get('age'),
                                        'draftYear': p.get('draftYear'), 'ser': dict(sorted(ser.items()))}
    return panel


def val_on(ser, d):
    """Value on or just before date d (str)."""
    keys = list(ser)
    i = bisect.bisect_right(keys, d) - 1
    return ser[keys[i]] if i >= 0 else None


def lchg(ser, a, b):
    va, vb = val_on(ser, a), val_on(ser, b)
    return math.log(vb / va) if va and vb else None


# ---------------------------------------------------------------- events
def team_contract_events(names):
    """[(date, key, kind, detail)] from daily d.js: team changes + contract changes."""
    commits = daily_commits('data/d.js')
    prev, ev = {}, []
    for d, h in commits.items():
        txt = git('show', f'{h}:data/d.js')
        i = txt.find('[')
        try:
            arr, _ = json.JSONDecoder().raw_decode(txt, i)
        except Exception:
            continue
        cur = {}
        for p in arr:
            k = norm(p.get('n', ''))
            if k in names and p.get('s') in POS:
                cur[k] = (p.get('t') or '', p.get('cs'), p.get('sal'), p.get('cn'), p.get('cg'))
        if prev and d > START:
            for k, c in cur.items():
                o = prev.get(k)
                if not o:
                    continue
                team_changed = o[0] != c[0] and o[0] and c[0]
                contract_changed = o[1] is not None and o[2] is not None and ((c[1] != o[1] and c[1] is not None) or (c[2] != o[2] and c[2] is not None))
                if team_changed:
                    ev.append((d, k, 'team change', f'{o[0]} -> {c[0]}' + (' (new contract)' if contract_changed else '')))
                elif contract_changed:
                    raise_ = (c[2] or 0) - (o[2] or 0)
                    ev.append((d, k, 'contract, same team', f'signed {c[1]}, ${c[2]}M/yr x{c[3]} ({raise_:+.1f}M/yr)'))
        prev = cur if cur else prev
    # a day with dozens of contract changes is a data refresh, not news
    per_day = defaultdict(int)
    for d, k, kind, det in ev:
        if kind == 'contract, same team':
            per_day[d] += 1
    return [e for e in ev if not (e[2] == 'contract, same team' and per_day[e[0]] > 15)]


def injury_events(names):
    commits = daily_commits('data/injury_updates.js')
    prev, ev = None, []

    def cls(s):
        s = (s or '').lower()
        if not s:
            return 'healthy'
        if 'ir' in re.findall(r'\b\w+\b', s) or 'pup' in s or 'season' in s or 'nfi' in s:
            return 'IR / long-term'
        if re.search(r'\bout\b', s) or 'doubtful' in s:
            return 'out'
        if 'questionable' in s:
            return 'questionable'
        return 'other'
    for d, h in commits.items():
        txt = git('show', f'{h}:data/injury_updates.js')
        try:
            obj, _ = json.JSONDecoder().raw_decode(txt, txt.index('{'))
        except Exception:
            continue
        cur = {norm(n): cls(s) for n, s in obj.get('players', {}).items() if norm(n) in names}
        if prev is not None and d > START:
            for k in names:
                a, b = prev.get(k, 'healthy'), cur.get(k, 'healthy')
                if a == b:
                    continue
                if b == 'IR / long-term':
                    ev.append((d, k, 'injury: IR / long-term', a + ' -> ' + b))
                elif b == 'out' and a in ('healthy', 'questionable', 'other'):
                    ev.append((d, k, 'injury: ruled out', a + ' -> ' + b))
                elif b == 'questionable' and a == 'healthy':
                    ev.append((d, k, 'injury: questionable', a + ' -> ' + b))
                elif b == 'healthy' and a in ('IR / long-term', 'out'):
                    ev.append((d, k, 'injury: return to healthy', a + ' -> ' + b))
        prev = cur
    return ev


# ---------------------------------------------------------------- analyses
def tier_of(v):
    return 0 if v >= 6000 else 1 if v >= 4000 else 2 if v >= 2500 else 3


def abnormal(panel, d, k, ev_days_by_key, pre=1, post=7):
    """log change [d-pre, d+post] minus median of same pos + value tier with no event in the window."""
    a = (day(d) - dt.timedelta(days=pre)).isoformat()
    b = min(END, (day(d) + dt.timedelta(days=post)).isoformat())
    P = panel[k]
    own = lchg(P['ser'], a, b)
    v0 = val_on(P['ser'], a)
    if own is None or not v0:
        return None
    peers = []
    for k2, P2 in panel.items():
        if k2 == k or P2['pos'] != P['pos']:
            continue
        v2 = val_on(P2['ser'], a)
        if not v2 or tier_of(v2) != tier_of(v0):
            continue
        if any(a <= e <= b for e in ev_days_by_key.get(k2, ())):
            continue
        c = lchg(P2['ser'], a, b)
        if c is not None:
            peers.append(c)
    if len(peers) < 5:
        return None
    return own - stats.median(peers), own, v0


def main():
    panel = load_ktc()
    names = set(panel)
    print(f'KTC panel: {len(panel)} QB/RB/WR/TE, {START} .. {END}')

    # ---- A. calendar
    print('\n=== A. When does value move? (share of all absolute daily log changes, top-300 by value) ===')
    tot = defaultdict(float); days_in = {}
    for nm, a, b in PHASES:
        days_in[nm] = (day(b) - day(a)).days + 1
    for P in panel.values():
        ks = list(P['ser'])
        for i in range(1, len(ks)):
            d = ks[i]
            c = abs(math.log(P['ser'][ks[i]] / P['ser'][ks[i - 1]]))
            for nm, a, b in PHASES:
                if a <= d <= b:
                    tot[nm] += c
    T = sum(tot.values())
    print(f'{"phase":<24}{"days":>6}{"share of movement":>19}{"per-day intensity":>19}')
    base = T / sum(days_in.values())
    for nm, a, b in PHASES:
        print(f'{nm:<24}{days_in[nm]:>6}{tot[nm] / T * 100:>18.1f}%{(tot[nm] / days_in[nm]) / base:>18.2f}x')

    # ---- events
    print('\nDating events from the daily commits (d.js, injury_updates)...')
    ev = team_contract_events(names) + injury_events(names)
    ev_days = defaultdict(list)
    for d, k, kind, det in ev:
        ev_days[k].append(d)

    print('\n=== B. Event effects (abnormal log change, day before -> 7 days after, vs same-position same-tier peers) ===')
    by_kind = defaultdict(list)
    for d, k, kind, det in ev:
        r = abnormal(panel, d, k, ev_days)
        if r:
            by_kind[kind].append((r[0], d, k, det, r[2]))
    print(f'{"event":<30}{"n":>5}{"mean":>9}{"median":>9}{"share up":>10}')
    for kind, lst in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        xs = [x[0] for x in lst]
        print(f'{kind:<30}{len(xs):>5}{(math.exp(np.mean(xs)) - 1) * 100:>8.1f}%{(math.exp(np.median(xs)) - 1) * 100:>8.1f}%'
              f'{sum(x > 0 for x in xs) / len(xs) * 100:>9.0f}%')
    for kind in ('team change', 'contract, same team'):
        lst = sorted(by_kind.get(kind, []), key=lambda x: -abs(x[0]))[:8]
        if lst:
            print(f'   biggest {kind}:')
            for a_, d, k, det, v0 in lst:
                print(f'     {d} {panel[k]["name"]:<22}{(math.exp(a_) - 1) * 100:+6.0f}%  ({v0:,} before) {det}')

    print('\n=== B2. Does the reaction hold? abnormal change at +7d vs +30d / +60d / +90d (events with room to look ahead) ===')
    print(f'{"event":<30}{"n":>5}{"+7d":>8}{"+30d":>8}{"+60d":>8}{"+90d":>8}   (median abnormal; same peers)')
    for kind, lst in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        row = []
        for post in (7, 30, 60, 90):
            xs = []
            for a_, d, k, det, v0 in lst:
                if (day(d) + dt.timedelta(days=post)).isoformat() > END:
                    continue
                r = abnormal(panel, d, k, ev_days, post=post)
                if r:
                    xs.append(r[0])
            row.append((len(xs), (math.exp(np.median(xs)) - 1) * 100 if len(xs) >= 5 else None))
        n90 = row[-1][0]
        print(f'{kind:<30}{row[0][0]:>5}' + ''.join(f'{x[1]:>7.1f}%' if x[1] is not None else f'{"—":>8}' for x in row) + f'   (n at +90d: {n90})')

    # ---- C. draft
    print('\n=== C. NFL draft week: 2026 rookies, KTC change Apr 22 -> Apr 28 by draft capital ===')
    import pandas as pd
    dp = pd.read_parquet(r'E:\MyFantasyFootball\pbp_cache\draft_picks.parquet')
    dp = dp[(dp.season == 2026) & dp.position.isin(POS)]
    pick = {norm(r.pfr_player_name): int(r.pick) for r in dp.itertuples()}
    rows = []
    for k, P in panel.items():
        if P.get('draftYear') != 2026:
            continue
        c = lchg(P['ser'], '2026-04-22', '2026-04-28')
        if c is None:
            continue
        rows.append((pick.get(k), c, P['name'], val_on(P['ser'], '2026-04-22')))
    bands = [('picks 1-32', 1, 32), ('33-64', 33, 64), ('65-100', 65, 100), ('101-160', 101, 160), ('161-257', 161, 257), ('undrafted', None, None)]
    print(f'{"capital":<14}{"n":>4}{"median change":>15}{"range":>22}')
    for lbl, lo, hi in bands:
        xs = [r for r in rows if (r[0] is None if lo is None else (r[0] is not None and lo <= r[0] <= hi))]
        if xs:
            cs = sorted(math.exp(r[1]) - 1 for r in xs)
            print(f'{lbl:<14}{len(xs):>4}{np.median(cs) * 100:>14.0f}%{cs[0] * 100:>10.0f}% .. {cs[-1] * 100:+.0f}%')
    # surprise: pre-draft KTC rank among rookies vs pick rank
    rk = sorted([r for r in rows if r[0]], key=lambda r: -r[3])
    pre_rank = {r[2]: i + 1 for i, r in enumerate(rk)}
    pick_rank = {r[2]: i + 1 for i, r in enumerate(sorted(rk, key=lambda r: r[0]))}
    from backtest_js_model import spearman
    surprise = [math.log(pre_rank[r[2]] / pick_rank[r[2]]) for r in rk]
    print(f'   draft "surprise" (taken earlier than his pre-draft KTC rank) vs value change: Spearman '
          f'{spearman(surprise, [r[1] for r in rk]):+.2f} (n={len(rk)})')

    # ---- D. on-field
    print('\n=== D. In-season: weekly value change vs fantasy points over Clay\'s preseason expectation ===')
    clay = {}
    for m in re.finditer(r'"([^"]+)":\s*\{pos:"(\w+)",tm:"\w*",gm:(\d+),pts:(\d+)', open(os.path.join(REPO, 'data', 'mike_clay_projections.js'), encoding='utf-8').read()):
        if int(m.group(3)) > 0:
            clay[norm(m.group(1))] = int(m.group(4)) / int(m.group(3))
    raw = open(os.path.join(REPO, 'data', 'weekly_stats_active.js'), encoding='utf-8').read()
    wk, _ = json.JSONDecoder().raw_decode(raw, raw.index('{"'))
    tues = {1: ('2026-09-08', '2026-09-15'), 2: ('2026-09-15', '2026-09-22'), 3: ('2026-09-22', '2026-09-29'), 4: ('2026-09-29', '2026-10-06')}
    X, Y, info = [], [], []
    for name, rec in wk.items():
        k = norm(name)
        if k not in panel or k not in clay:
            continue
        games = {w['wk']: w for w in rec.get('seasons', {}).get('2026', [])}
        cum = 0.0; ng = 0
        for w, (a, b) in tues.items():
            g = games.get(w)
            c = lchg(panel[k]['ser'], a, b)
            if c is None:
                continue
            played = g and ((g.get('fpts') or 0) != 0 or (g.get('tgt') or 0) or (g.get('ra') or 0) or (g.get('pa') or 0))
            if played:
                ppr = (g.get('py') or 0) * .04 + (g.get('ptd') or 0) * 4 - (g.get('int') or 0) + (g.get('ry') or 0) * .1 + (g.get('rtd') or 0) * 6 \
                    + (g.get('rec') or 0) + (g.get('rcy') or 0) * .1 + (g.get('rctd') or 0) * 6 - (g.get('fl') or 0) * 2
                poe = ppr - clay[k]
                cum += poe; ng += 1
            else:
                poe = None
            prior = (cum - (poe or 0.0)) / max(ng - (1 if poe is not None else 0), 1)
            X.append((poe if poe is not None else 0.0, 1.0 if poe is None else 0.0, prior, math.log(val_on(panel[k]['ser'], a))))
            Y.append(c); info.append((panel[k]['name'], w, poe))
    X = np.array(X); Y = np.array(Y)
    A = np.column_stack([np.ones(len(X)), X])
    b, *_ = np.linalg.lstsq(A, Y, rcond=None)
    pred = A @ b
    r2 = 1 - ((Y - pred) ** 2).sum() / ((Y - Y.mean()) ** 2).sum()
    print(f'   player-weeks: {len(Y)}; R^2 = {r2:.2f} (share of weekly value moves explained)')
    print(f'   +10 PPR pts over expectation THIS week   -> {(math.exp(10 * b[1]) - 1) * 100:+.1f}% value')
    print(f'   +5 pts/game over expectation PRIOR weeks -> {(math.exp(5 * b[3]) - 1) * 100:+.1f}% value (market still catching up)')
    print(f'   did not play that week                    -> {(math.exp(b[2]) - 1) * 100:+.1f}% value')
    print(f'   value level (log)                         -> {b[4]:+.3f} per log unit (higher-valued players drift {"down" if b[4] < 0 else "up"})')
    # by tier
    for lbl, lo, hi in (('value 6000+', 6000, 1e9), ('4000-6000', 4000, 6000), ('<4000', 0, 4000)):
        ix = [i for i in range(len(Y)) if lo <= math.exp(X[i, 3]) < hi and X[i, 1] == 0]
        if len(ix) > 30:
            bb, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(ix)), X[ix, 0]]), Y[ix], rcond=None)
            print(f'   {lbl:<12} +10 pts this week -> {(math.exp(10 * bb[1]) - 1) * 100:+.1f}% (n={len(ix)})')

    # ---- E. time decay
    print('\n=== E. Drift with no event: 6-month change (Apr 14 -> Oct 9) for players with no team / contract / injury event ===')
    big = defaultdict(list)
    for d, k, kind, det in ev:
        if kind != 'injury: questionable':
            big[k].append(d)
    quiet = [k for k in panel if not big.get(k) and panel[k].get('draftYear') != 2026]
    print(f'{"pos":<5}{"age <=24":>10}{"25-27":>10}{"28-30":>10}{"31+":>10}   (median change, n)')
    for pos in POS:
        cells = []
        for lo, hi in ((0, 24.99), (25, 27.99), (28, 30.99), (31, 99)):
            xs = [lchg(panel[k]['ser'], START, END) for k in quiet if panel[k]['pos'] == pos and panel[k]['age'] and lo <= panel[k]['age'] <= hi]
            xs = [x for x in xs if x is not None]
            cells.append(f'{(math.exp(np.median(xs)) - 1) * 100:+.0f}% ({len(xs)})' if len(xs) >= 3 else '—')
        print(f'{pos:<5}' + ''.join(f'{c:>10}' for c in cells))

    # ---- F. biggest movers
    print('\n=== F. Biggest 6-month movers (Apr 14 -> Oct 9, value >= 2000 at either end) and their events ===')
    mv = []
    for k, P in panel.items():
        a, b = val_on(P['ser'], START), val_on(P['ser'], END)
        if a and b and max(a, b) >= 2000:
            mv.append((math.log(b / a), k, a, b))
    mv.sort()
    evk = defaultdict(list)
    for d, k, kind, det in ev:
        if not kind.startswith('injury: questionable'):
            evk[k].append(f'{d[5:]} {kind}: {det}')
    for lbl, lst in (('RISERS', mv[::-1][:25]), ('FALLERS', mv[:25])):
        print(f'  {lbl}')
        for c, k, a, b in lst:
            P = panel[k]
            tags = []
            if P.get('draftYear') == 2026:
                tags.append(f'2026 rookie, pick {pick.get(k, "UDFA")}')
            tags += evk.get(k, [])[:3]
            print(f'    {P["name"]:<24}{P["pos"]:<3} age {P["age"]!s:<5} {a:>5,} -> {b:>5,} ({(math.exp(c) - 1) * 100:+.0f}%)  ' + ' | '.join(tags))


if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'js_model_site', 'scripts'))
    main()
