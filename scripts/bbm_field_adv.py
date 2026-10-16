"""Full-field Best Ball Mania VII advance rate by player.

Feeds the My Teams > Underdog > DRAFT BOARD "OVERALL ADV RATE" view with the
WHOLE contest (all 672,324 teams / 56,027 draft groups) instead of only the
pools Jack is in (Jack 2026-10-16: "not just my pods?").

Input: the one-time full leaderboard pull (Underdog extension 0.18.22+, v3
schema with draft-group index) kept OUTSIDE the repo — it carries 52k
usernames and must never be committed or hosted:
    E:\\MyFantasyFootball\\bbm_field\\bbm7_field_v3.json
Rosters never change in best ball, so the file is read once per run and
re-scored from Sleeper's weekly stats (pts_half_ppr = Underdog scoring) for
every rostered player — the same source + name resolver Sim Lab validated on
this exact field (weeks 1-3 = Underdog official for all but 10 of 672,324
teams). The site's weekly_stats_active.js is NOT used: it only carries the
site's tracked pool and misses rostered rookies/fringe players. A week counts
only once ESPN shows every game in it FINAL (run Tuesday after MNF).

Scoring: each week every team's best-ball lineup QB / 2 RB / 3 WR / TE / FLEX
(RB/WR/TE), summed over Round 1 weeks (1-14); teams rank inside their own
12-team draft group (competition ranks, so a tie at the cut advances both);
top 2 advance. Per player: n = teams rostering him, adv = those in an
advancing spot. Output has NO usernames — only per-player counts.

Usage:
    python scripts/bbm_field_adv.py            # write data/bbm_field_adv.js
    python scripts/bbm_field_adv.py validate   # rebuild the pull-time points vs Underdog's official
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIELD_DIR = r'E:\MyFantasyFootball\bbm_field'
FIELD_V3 = os.path.join(FIELD_DIR, 'bbm7_field_v3.json')
FIELD_V2 = os.path.join(FIELD_DIR, 'bbm7_field_v2_20261001.json')
CACHE = os.path.join(FIELD_DIR, 'cache')
OUT_JS = os.path.join(ROOT, 'data', 'bbm_field_adv.js')
SEASON = 2026
R1_WEEKS = 14
ADV = 2
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36'}

# Underdog lists a few players under a nickname nobody else uses (Sim Lab
# engine.js BB_NAME_ALIAS).
ALIAS = {
    'hollywood brown': 'marquise brown',
    'bam knight': 'zonovan knight',
    'juice wells': 'antwane wells',
}
SUFFIX = re.compile(r'\b(jr|sr|ii|iii|iv|v)\b')


def norm(name):
    """Sim Lab engine.js norm()."""
    s = str(name or '').lower().replace('.', '').replace("'", '').replace('-', ' ')
    s = SUFFIX.sub('', s)
    return re.sub(r'\s+', ' ', s).strip()


def get_json(url, cache_name=None, max_age=None):
    path = os.path.join(CACHE, cache_name) if cache_name else None
    if path and os.path.exists(path) and (max_age is None or time.time() - os.path.getmtime(path) < max_age):
        return json.load(open(path, encoding='utf-8'))
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                data = json.loads(r.read().decode('utf-8'))
            break
        except Exception as e:  # noqa: BLE001 - transient network, retry
            if attempt == 2:
                raise
            time.sleep(3)
    if path:
        os.makedirs(CACHE, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(data, fh)
    return data


def sleeper_index():
    """Sim Lab engine.js bbSleeperIndex(): name|pos, collapsed name|pos, and
    initial+last|pos candidates; name twins resolve to whoever is on a team /
    active."""
    allp = get_json('https://api.sleeper.app/v1/players/nfl', 'sleeper_players.json', max_age=86400)
    by_np, by_cp, by_ip, by_any = {}, {}, {}, {}
    for pid, p in allp.items():
        if not isinstance(p, dict):
            continue
        nm = norm((p.get('first_name') or '') + ' ' + (p.get('last_name') or ''))
        if not nm:
            continue
        # Any-position fallback: Sleeper files two-way Travis Hunter as a DB
        # while Underdog rosters him at WR.
        if p.get('team'):
            by_any.setdefault(nm, []).append(str(pid))
        pos = 'RB' if p.get('position') == 'FB' else p.get('position')
        if pos not in ('QB', 'RB', 'WR', 'TE'):
            continue
        rec = {'sid': str(pid), 'team': p.get('team'), 'live': (2 if p.get('team') else 0) + (1 if p.get('active') else 0)}
        k1, k2 = nm + '|' + pos, nm.replace(' ', '') + '|' + pos
        if k1 not in by_np or rec['live'] > by_np[k1]['live']:
            by_np[k1] = rec
        if k2 not in by_cp or rec['live'] > by_cp[k2]['live']:
            by_cp[k2] = rec
        parts = nm.split(' ')
        if len(parts) >= 2:
            by_ip.setdefault(parts[0][0] + '|' + ' '.join(parts[1:]) + '|' + pos, []).append(rec)
    return by_np, by_cp, by_ip, by_any


def resolve_sid(index, name, pos):
    """Sim Lab engine.js bbResolveSid(), plus a last-resort unique-name match
    across every position (rostered players only)."""
    by_np, by_cp, by_ip, by_any = index
    pos = 'RB' if pos == 'FB' else pos
    nk = norm(name)
    nk = ALIAS.get(nk, nk)
    hit = by_np.get(nk + '|' + pos) or by_cp.get(nk.replace(' ', '') + '|' + pos)
    if hit:
        return hit['sid']
    parts = nk.split(' ')
    if len(parts) < 2:
        return None
    c = by_ip.get(parts[0][0] + '|' + ' '.join(parts[1:]) + '|' + pos, [])
    if len(c) > 1:
        c = [r for r in c if r['team']]
    if len(c) == 1:
        return c[0]['sid']
    a = by_any.get(nk, [])
    return a[0] if len(a) == 1 else None


def final_weeks():
    """Round 1 weeks whose every game is FINAL on ESPN (all three scoreboard
    params — bare dates=2026 drops the season key)."""
    done = []
    for wk in range(1, R1_WEEKS + 1):
        sb = get_json('https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'
                      '?dates=%d&seasontype=2&week=%d' % (SEASON, wk))
        evs = sb.get('events') or []
        if not evs or not all(((e.get('status') or {}).get('type') or {}).get('completed') for e in evs):
            break
        done.append(wk)
    return done


def week_stats(wk, final):
    """Sleeper weekly stats {sid: half-PPR pts}; finished weeks cached."""
    data = get_json('https://api.sleeper.app/v1/stats/nfl/regular/%d/%d' % (SEASON, wk),
                    ('sleeper_stats_%d_w%02d.json' % (SEASON, wk)) if final else None)
    return {str(k): float(v.get('pts_half_ppr') or 0) for k, v in data.items() if isinstance(v, dict)}


def weekly_matrix(apps, weeks, finals, team_filter=None):
    """pts[app, week_col] (float32) + unresolved names. team_filter =
    {week: set(team abbrs)} limits that week to those teams (pull-time
    validation of a part-played week)."""
    index = sleeper_index()
    sids = [resolve_sid(index, a[0], a[1]) for a in apps]
    unmatched = [apps[i][0] for i, s in enumerate(sids) if s is None]
    teams = {}
    if team_filter:
        allp = get_json('https://api.sleeper.app/v1/players/nfl', 'sleeper_players.json', max_age=86400)
        teams = {s: (allp.get(s) or {}).get('team') for s in sids if s}
    pts = np.zeros((len(apps), len(weeks)), dtype=np.float32)
    for wi, wk in enumerate(weeks):
        st = week_stats(wk, wk in finals)
        for ai, s in enumerate(sids):
            if not s:
                continue
            if team_filter and wk in team_filter and teams.get(s) not in team_filter[wk]:
                continue
            pts[ai, wi] = st.get(s, 0.0)
    return pts, unmatched


def best_ball_totals(rosters, apps, pts):
    """Season best-ball total per team. rosters: int array (teams, 18)."""
    pos = np.array([a[1] for a in apps])
    teams = rosters.shape[0]
    total = np.zeros(teams, dtype=np.float64)
    neg = np.float32(-1e9)
    for w in range(pts.shape[1]):
        # Negative player weeks score 0, as in Sim Lab bbLineup (validated
        # against Underdog's official totals).
        P = np.maximum(pts[rosters, w], 0)        # (teams, 18)
        rpos = pos[rosters]
        def top(p, k):
            m = np.where(rpos == p, P, neg)
            return -np.sort(-m, axis=1)[:, :k]
        qb, rb, wr, te = top('QB', 1), top('RB', 3), top('WR', 4), top('TE', 2)
        fix = lambda a: np.where(a <= neg / 2, 0, a)
        wk = fix(qb[:, 0]) + fix(rb[:, :2]).sum(1) + fix(wr[:, :3]).sum(1) + fix(te[:, 0])
        flex = np.maximum(np.maximum(fix(rb[:, 2]), fix(wr[:, 3])), fix(te[:, 1]))
        total += wk + flex
    return total


def load_field(path):
    f = json.load(open(path, encoding='utf-8'))
    apps = f['apps']
    ents = f['entries']
    roster_col = 5
    rosters = np.array([e[roster_col] for e in ents], dtype=np.int32)
    official = np.array([e[2] for e in ents], dtype=np.float64)
    pods = np.array([e[6] for e in ents], dtype=np.int64) if len(ents[0]) > 6 else None
    return f, apps, rosters, official, pods


def pod_ranks(pods, pts):
    """Competition rank of each team inside its draft group (1 = best)."""
    pts_r = np.round(pts, 2)
    order = np.lexsort((-pts_r, pods))
    sp, sv = pods[order], pts_r[order]
    rank = np.empty(len(pods), dtype=np.int32)
    i, n = 0, len(order)
    while i < n:
        j = i
        while j < n and sp[j] == sp[i]:
            j += 1
        r = 1
        for k in range(i, j):
            if k > i and sv[k] != sv[k - 1]:
                r = k - i + 1
            rank[order[k]] = r
        i = j
    return rank


def validate():
    finals = final_weeks()
    # v2 (pulled 10-01 2:12pm ET, before TNF) = weeks 1-3 exactly.
    _, apps, rosters, official, _ = load_field(FIELD_V2)
    pts, unmatched = weekly_matrix(apps, [1, 2, 3], finals)
    tot = best_ball_totals(rosters, apps, pts)
    d = np.abs(tot - official)
    print('v2 weeks 1-3: teams %d  exact(<=0.05) %.5f  <=1pt %.5f  off>1pt %d  max diff %.2f' %
          (len(d), (d <= 0.05).mean(), (d <= 1.0).mean(), int((d > 1.0).sum()), d.max()))
    print('unresolved names (score 0): %d %s' % (len(unmatched), unmatched[:40]))
    # v3 (pulled 10-02 11:47am ET) = weeks 1-3 + Thursday week 4 (CLE-PIT).
    _, apps, rosters, official, _ = load_field(FIELD_V3)
    pts, _ = weekly_matrix(apps, [1, 2, 3, 4], finals, team_filter={4: {'CLE', 'PIT'}})
    tot = best_ball_totals(rosters, apps, pts)
    d = np.abs(tot - official)
    print('v3 weeks 1-3 + W4 TNF: exact(<=0.05) %.5f  off>1pt %d  max diff %.2f' %
          ((d <= 0.05).mean(), int((d > 1.0).sum()), d.max()))


def build():
    f, apps, rosters, _, pods = load_field(FIELD_V3)
    if pods is None:
        sys.exit('field file has no draft groups (needs the v3 pull)')
    weeks_avail = final_weeks()
    if not weeks_avail:
        sys.exit('no FINAL Round 1 weeks yet')
    pts, unmatched = weekly_matrix(apps, weeks_avail, set(weeks_avail))
    tot = best_ball_totals(rosters, apps, pts)
    rank = pod_ranks(pods, tot)
    adv = rank <= ADV
    # Per player (each app once per roster): n teams, adv teams.
    flat = rosters.ravel()
    adv_flat = np.repeat(adv, rosters.shape[1])
    n_by = np.bincount(flat, minlength=len(apps))
    a_by = np.bincount(flat, weights=adv_flat, minlength=len(apps)).astype(int)
    players = {apps[i][0]: [int(n_by[i]), int(a_by[i])] for i in range(len(apps)) if n_by[i] > 0}
    out = {
        'asOf': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'weeks': weeks_avail,
        'pools': int(len(np.unique(pods))),
        'teams': int(len(pods)),
        'adv': int(adv.sum()),
        'p': players,
    }
    body = json.dumps(out, separators=(',', ':'), ensure_ascii=False)
    js = ('// Full-field Best Ball Mania VII advance rate by player (scripts/bbm_field_adv.py).\n'
          '// p[name] = [teams rostering him, teams in an advancing spot (top 2 of 12, Round 1)].\n'
          'window.BBM_FIELD_ADV = ' + body + ';\n')
    prev = open(OUT_JS, encoding='utf-8').read() if os.path.exists(OUT_JS) else ''
    # asOf alone changing isn't news — only rewrite when the counts/weeks move.
    strip = lambda s: re.sub(r'"asOf":"[^"]*",', '', s)
    if strip(prev) == strip(js):
        print('unchanged (weeks %s) - not rewritten' % weeks_avail)
        return
    with open(OUT_JS, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(js)
    print('wrote %s: weeks %s, %d teams / %d pools, %d advancing, %d players, %d unmatched apps' %
          (os.path.relpath(OUT_JS, ROOT), weeks_avail, out['teams'], out['pools'], out['adv'], len(players), len(unmatched)))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'validate':
        validate()
    else:
        build()
