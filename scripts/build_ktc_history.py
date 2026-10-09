#!/usr/bin/env python3
"""
build_ktc_history.py — daily KeepTradeCut value history for the dynasty TREND view.

The 9am consensus job commits data/ktc_rankings.js every day (since
2026-06-17), so git already holds a daily KTC history. This rebuilds it in full
on every run (self-healing — a missed day fills in next run): the last commit
of each day + today's working-tree file.

Output: data/ktc_history.js (lazy-loaded by the rankings TREND view)
    window.KTC_HISTORY = {
      updated, dates: ['2026-06-17', ...],
      v1:  {name: [value per date | null]},   # 1QB
      vsf: {name: [...]},                     # Superflex
    }
Players kept: anyone in the top KEEP of either format on any day (picks and
devy entries included — they are on the dynasty boards too).
Also bumps <meta name="mff-ktc-hist-v"> in index.html when the file changes.

Usage: python scripts/build_ktc_history.py [--keep 450]
"""
import argparse
import datetime
import json
import os
import re
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = 'data/ktc_rankings.js'
OUT = os.path.join(REPO, 'data', 'ktc_history.js')
IDX = os.path.join(REPO, 'index.html')


def parse_maps(text):
    out = {}
    for var in ('KTC_1QB', 'KTC_SF'):
        m = re.search(r'\bvar\s+' + var + r'\s*=\s*', text)
        if not m:
            continue
        obj, _ = json.JSONDecoder().raw_decode(text, m.end())
        out[var] = {k: v for k, v in obj.items() if isinstance(v, (int, float))}
    return out


def merge_ktc_site_history(snaps):
    """Fold KTC's /dynasty-rankings/histories into snaps[date][KTC_1QB|KTC_SF][name]."""
    import sys
    import urllib.request
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, REPO)
    # Same fetch + name resolution as the 9am KTC pull (Phase E), so history keys
    # match data/ktc_rankings.js exactly (d.js-canonical names; picks keep KTC's).
    import pull_consensus_adp as pca
    from inject_rankings import norm_name, final_key
    players = pca._ktc_fetch_players(pca.KTC_URL)
    if not players:
        raise RuntimeError('KTC players list not found')
    dsrc = open(os.path.join(REPO, 'data', 'd.js'), encoding='utf-8').read()
    dnames = re.findall(r'"n":"([^"]+)"', dsrc)
    exact, norm_idx = set(dnames), {}
    for n_ in dnames:
        norm_idx.setdefault(norm_name(n_), n_)

    def resolve(raw):
        raw = pca.KTC_ALIASES.get(raw, raw)
        return raw if raw in exact else norm_idx.get(final_key(raw), raw)
    names = {p['playerID']: resolve(p['playerName']) for p in players if p.get('playerName')}
    req = urllib.request.Request('https://keeptradecut.com/dynasty-rankings/histories',
                                 headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
                                          'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        hist = json.loads(resp.read().decode('utf-8'))
    n = 0
    for h in hist:
        name = names.get(h.get('playerID'))
        if not name:
            continue
        n += 1
        for fmt, var in (('oneQB', 'KTC_1QB'), ('superflex', 'KTC_SF')):
            for pt in (h.get(fmt) or {}).get('valueHistory') or []:
                pt = str(pt)
                if len(pt) < 7 or not pt[:6].isdigit():
                    continue
                day = f'20{pt[:2]}-{pt[2:4]}-{pt[4:6]}'
                snaps.setdefault(day, {}).setdefault(var, {})[name] = int(pt[6:])
    return n


def git(*args):
    return subprocess.run(['git', '-C', REPO, *args], capture_output=True, text=True, encoding='utf-8', check=True).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', type=int, default=450)
    args = ap.parse_args()

    log = git('log', '--format=%H %cd', '--date=short', '--', SRC).strip().splitlines()
    by_day = {}
    for line in reversed(log):              # oldest -> newest; later commits overwrite the day
        sha, day = line.split()
        by_day[day] = sha
    snaps = {}
    for day, sha in sorted(by_day.items()):
        try:
            maps = parse_maps(git('show', f'{sha}:{SRC}'))
        except (subprocess.CalledProcessError, ValueError):
            continue
        if maps.get('KTC_1QB'):
            snaps[day] = maps
    today = datetime.date.today().isoformat()
    cur = parse_maps(open(os.path.join(REPO, SRC), encoding='utf-8').read())
    if cur.get('KTC_1QB'):
        snaps[today] = cur

    # KTC's own daily history (Jack 2026-10-09: "we can also look at ktc back from their
    # site"): the rankings page loads every player's value history in ONE request
    # (/dynasty-rankings/histories, ~6 months daily, points packed "YYMMDD"+value).
    # Two requests a day (that + the rankings page for playerID -> name); KTC's numbers
    # win where they overlap our own snapshots. Non-fatal: git snapshots alone on failure.
    try:
        n_ktc = merge_ktc_site_history(snaps)
        print(f'KTC site history merged: {n_ktc} players')
    except Exception as e:   # network / template change
        print(f'KTC site history unavailable ({e}) - git snapshots only')

    dates = sorted(snaps)
    # Size: every day for the last 45, every 3rd day before that (3- and 6-month
    # charts don't need daily points; ~halves the lazy-loaded file).
    if dates:
        last = datetime.date.fromisoformat(dates[-1])
        old = [d for d in dates if (last - datetime.date.fromisoformat(d)).days > 45]
        dates = old[::3] + [d for d in dates if (last - datetime.date.fromisoformat(d)).days <= 45]
    keep = set()
    for d in dates:
        for var in ('KTC_1QB', 'KTC_SF'):
            m = snaps[d].get(var) or {}
            keep.update(k for k, _ in sorted(m.items(), key=lambda kv: -kv[1])[:args.keep])
    hist = {'updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), 'dates': dates, 'v1': {}, 'vsf': {}}
    for out_key, var in (('v1', 'KTC_1QB'), ('vsf', 'KTC_SF')):
        for name in sorted(keep):
            series = [(snaps[d].get(var) or {}).get(name) for d in dates]
            if any(v is not None for v in series):
                hist[out_key][name] = [int(v) if v is not None else None for v in series]

    body = ('// KTC daily value history — built by scripts/build_ktc_history.py from the daily\n'
            '// data/ktc_rankings.js commits. Do not hand-edit.\n'
            'window.KTC_HISTORY = ' + json.dumps(hist, separators=(',', ':'), ensure_ascii=False) + ';\n')
    old = open(OUT, encoding='utf-8').read() if os.path.exists(OUT) else ''
    # ignore the 'updated' stamp when deciding whether anything changed
    strip = lambda s: re.sub(r'"updated":"[^"]*",', '', s)
    if strip(old) == strip(body):
        print(f'ktc history unchanged ({len(dates)} days)')
        return
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(body)
    html = open(IDX, encoding='utf-8').read()
    # date + time: a second rebuild the same day must still bust the cached file
    stamp = datetime.datetime.now().strftime('%Y-%m-%d-%H%M')
    new = re.sub(r'(<meta name="mff-ktc-hist-v" content=")[^"]*(")', r'\g<1>' + stamp + r'\g<2>', html)
    if new != html:
        with open(IDX, 'w', encoding='utf-8', newline='') as f:
            f.write(new)
    print(f'wrote {OUT}: {len(dates)} days ({dates[0]} .. {dates[-1]}), '
          f'{len(hist["v1"])} 1QB / {len(hist["vsf"])} SF players, {os.path.getsize(OUT) // 1024} KB')


if __name__ == '__main__':
    main()
