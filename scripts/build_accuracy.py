#!/usr/bin/env python3
"""
build_accuracy.py — data build for the admin-only ACCURACY tracker (/accuracy/).

Tracks, against real full-PPR results (QB/RB/WR/TE only):
  * Jack's ORIGINAL season-long board + every site's preseason rank/ADP
    (Sleeper, FantasyPros, Underdog, ESPN, CBS, Yahoo) — one frozen snapshot
    taken from data/cons_rank_history.json on the day of the W1 opener.
  * Preseason SEASON projections (MFF sim, Mike Clay, Sleeper, ESPN, CBS) —
    frozen from the last commit before the W1 opener (PRESEASON_COMMIT).
  * WEEKLY projections per site (Sleeper/ESPN/CBS/FantasyPros + FP expert
    consensus ranks) — every daily version of data/weekly_projections.json is
    archived here (accuracy/data/locks_2026.json) so each player is graded on
    the LAST version published before his game's kickoff.
  * MFF weekly sim — the Sim Lab pre-kickoff lock
    (sim_lab/data/snapshots/simlab_snapshot_w{N}.json, half-PPR + rec comps).
  * Actuals — data/weekly_stats_active.js 2026 rows (postgame importer),
    full PPR recomputed from raw components (the stored fpts is half-PPR).

Jack's WEEKLY boards are NOT built here: the page reads them straight from
Firestore rankings_history (admin-read) so nothing private lands in the repo.

Outputs (all consumed by accuracy/index.html):
  accuracy/data/season_2026.json      player index + preseason locks + season-to-date actuals
  accuracy/data/w{N}.json             one per week: kickoffs, site locks, sim lock, actuals
  accuracy/data/locks_2026.json       raw archive of weekly_projections.json versions
  accuracy/data/preseason_2026.json   cached preseason extraction (git show of PRESEASON_COMMIT)

Usage:
  python scripts/build_accuracy.py                 archive current weekly_projections.json + rebuild
  python scripts/build_accuracy.py --backfill-git  also archive every committed version since Sep 8
Chained at the end of scripts/postgame_stats.ps1 (runs after every final-game import).
"""
import argparse, json, os, re, subprocess, sys
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# sim_lab sits beside the MAIN checkout (E:\MyFantasyFootball\sim_lab); worktrees live
# deeper under .claude/worktrees/, so walk up until it is found.
def _find_sim_lab():
    d = ROOT
    for _ in range(6):
        cand = os.path.join(d, 'sim_lab')
        if os.path.isdir(os.path.join(cand, 'data')):
            return cand
        d = os.path.dirname(d)
    return r'E:\MyFantasyFootball\sim_lab'
SIM_LAB = _find_sim_lab()
OUT_DIR = os.path.join(ROOT, 'accuracy', 'data')
SEASON = 2026
POS = ('QB', 'RB', 'WR', 'TE')
# Last data commit before the 2026 W1 opener (Wed Sep 9, 8:20pm ET). Everything
# "preseason" is read from this commit so the lock never drifts.
PRESEASON_COMMIT = '7db795c'
PRESEASON_CONS_DAY = '2026-09-09'
BACKFILL_SINCE = '2026-09-08'

TEAM_ABBR = {
    'Arizona Cardinals': 'ARI', 'Atlanta Falcons': 'ATL', 'Baltimore Ravens': 'BAL', 'Buffalo Bills': 'BUF',
    'Carolina Panthers': 'CAR', 'Chicago Bears': 'CHI', 'Cincinnati Bengals': 'CIN', 'Cleveland Browns': 'CLE',
    'Dallas Cowboys': 'DAL', 'Denver Broncos': 'DEN', 'Detroit Lions': 'DET', 'Green Bay Packers': 'GB',
    'Houston Texans': 'HOU', 'Indianapolis Colts': 'IND', 'Jacksonville Jaguars': 'JAX', 'Kansas City Chiefs': 'KC',
    'Las Vegas Raiders': 'LV', 'Los Angeles Chargers': 'LAC', 'Los Angeles Rams': 'LAR', 'Miami Dolphins': 'MIA',
    'Minnesota Vikings': 'MIN', 'New England Patriots': 'NE', 'New Orleans Saints': 'NO', 'New York Giants': 'NYG',
    'New York Jets': 'NYJ', 'Philadelphia Eagles': 'PHI', 'Pittsburgh Steelers': 'PIT', 'San Francisco 49ers': 'SF',
    'Seattle Seahawks': 'SEA', 'Tampa Bay Buccaneers': 'TB', 'Tennessee Titans': 'TEN', 'Washington Commanders': 'WAS',
}
ABBR_ALIAS = {'ARZ': 'ARI', 'WSH': 'WAS', 'JAC': 'JAX', 'LA': 'LAR', 'OAK': 'LV', 'SD': 'LAC', 'STL': 'LAR', 'GNB': 'GB',
              'KAN': 'KC', 'NWE': 'NE', 'NOR': 'NO', 'SFO': 'SF', 'TAM': 'TB', 'LVR': 'LV'}
# Nickname / spelling aliases (normalized form -> normalized d.js form)
NAME_ALIAS = {
    'kenny gainwell': 'kenneth gainwell', 'demario douglas': 'demario douglas', 'pop douglas': 'demario douglas',
    'chig okonkwo': 'chigoziem okonkwo', 'chigoziem okonkwo': 'chig okonkwo', 'josh palmer': 'joshua palmer',
    'joshua palmer': 'josh palmer', 'hollywood brown': 'marquise brown', 'gabe davis': 'gabriel davis',
    'gabriel davis': 'gabe davis', 'tim patrick': 'timothy patrick', 'cam ward': 'cameron ward',
    'cameron ward': 'cam ward', 'mike woods': 'michael woods', 'jeff wilson': 'jeffery wilson',
    'ken walker': 'kenneth walker', 'nate adkins': 'nathaniel adkins', 'jaxson smith njigba': 'jaxon smith njigba',
}


def norm(s):
    s = (s or '').lower().replace('.', '').replace("'", '').replace('-', ' ').replace('’', '')
    s = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', s)
    s = ' '.join(t for t in s.split() if len(t) > 1 or not t.isalpha())  # drop middle initials
    return re.sub(r'\s+', ' ', s).strip()


def abbr(t):
    if not t:
        return None
    t = TEAM_ABBR.get(t, t)
    return ABBR_ALIAS.get(t, t)


def js_obj(text):
    return json.loads(text[text.index('{'):text.rindex('}') + 1])


def js_arr(text):
    return json.loads(text[text.index('['):text.rindex(']') + 1])


def read(p):
    return open(p, encoding='utf-8').read()


def git_show(commit, relpath):
    r = subprocess.run(['git', 'show', f'{commit}:{relpath}'], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    if r.returncode != 0:
        raise RuntimeError(f'git show {commit}:{relpath} failed: {r.stderr.strip()}')
    return r.stdout


def ppr(r):
    return round(r.get('py', 0) * 0.04 + r.get('ptd', 0) * 4 - r.get('int', 0) * 2
                 + r.get('ry', 0) * 0.1 + r.get('rtd', 0) * 6
                 + r.get('rec', 0) * 1 + r.get('rcy', 0) * 0.1 + r.get('rctd', 0) * 6
                 - r.get('fl', 0) * 2, 2)


def parse_iso(s):
    s = s.replace('Z', '+00:00')
    if re.search(r'T\d\d:\d\d\+', s):
        s = s.replace('+00:00', ':00+00:00')
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- player index
class Index:
    def __init__(self, D, ws):
        self.by_norm = {}
        for p in D:
            if p.get('s') in POS:
                self.by_norm[norm(p['n'])] = {'n': p['n'], 'pos': p['s'], 'tm': abbr(p.get('t'))}
        for name, rec in ws.items():
            k = norm(name)
            if k not in self.by_norm and rec.get('pos') in POS:
                self.by_norm[k] = {'n': name, 'pos': rec['pos'], 'tm': None}
        self.unmatched = {}

    def get(self, name, src=''):
        k = norm(name)
        hit = self.by_norm.get(k) or self.by_norm.get(NAME_ALIAS.get(k, ''))
        if not hit:
            self.unmatched.setdefault(src, set()).add(name)
        return hit


# ---------------------------------------------------------------- lock archive
def load_locks():
    p = os.path.join(OUT_DIR, f'locks_{SEASON}.json')
    if os.path.exists(p):
        return json.load(open(p, encoding='utf-8'))
    return {'season': SEASON, 'versions': {}}


def archive_version(locks, wp, idx, label):
    """Archive one weekly_projections.json dict under its `updated` stamp (dedup)."""
    upd = wp.get('updated')
    wk = wp.get('week')
    if not upd or not wk or wp.get('season') != SEASON:
        return False
    if upd in locks['versions']:
        return False
    players = {}
    for name, v in (wp.get('players') or {}).items():
        hit = idx.get(name, 'weekly_projections')
        if not hit:
            continue
        e = v.get('e') or [None, None, None]
        c = v.get('c') or [None, None, None]
        f = v.get('f') or [None, None, None]
        fe = v.get('fe') or [None, None, None]
        fx = v.get('fx') or [None, None, None]
        row = [v.get('p'), e[1], c[1], f[1], fe[1], fx[1]]
        if all(x is None for x in row):
            continue
        players[hit['n']] = row
    locks['versions'][upd] = {'week': wk, 'src': wp.get('src'), 'players': players, 'from': label}
    print(f'  archived weekly_projections version {upd} (week {wk}, {len(players)} players) [{label}]')
    return True


def backfill_git(locks, idx):
    r = subprocess.run(['git', 'log', '--format=%H', f'--since={BACKFILL_SINCE}', '--', 'data/weekly_projections.json'],
                       cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    hashes = [h for h in r.stdout.split() if h]
    print(f'backfill: {len(hashes)} commits touch data/weekly_projections.json since {BACKFILL_SINCE}')
    n = 0
    for h in reversed(hashes):
        try:
            wp = json.loads(git_show(h, 'data/weekly_projections.json'))
        except Exception as ex:
            print(f'  skip {h[:7]}: {ex}')
            continue
        if archive_version(locks, wp, idx, f'git {h[:7]}'):
            n += 1
    print(f'backfill: {n} new versions archived')


# ---------------------------------------------------------------- preseason
def build_preseason(idx):
    p = os.path.join(OUT_DIR, f'preseason_{SEASON}.json')
    if os.path.exists(p):
        pre = json.load(open(p, encoding='utf-8'))
        if pre.get('commit') == PRESEASON_COMMIT and pre.get('consDay') == PRESEASON_CONS_DAY:
            return pre
    print(f'preseason: extracting from commit {PRESEASON_COMMIT} + cons day {PRESEASON_CONS_DAY}')
    cons = json.load(open(os.path.join(ROOT, 'data', f'cons_rank_history.json'), encoding='utf-8'))
    day = next((d for d in cons['days'] if d['date'] == PRESEASON_CONS_DAY), None)
    if not day:
        raise SystemExit(f'cons_rank_history has no day {PRESEASON_CONS_DAY}')
    fields = cons['fields']  # ['a','slR','fpR','udA','espnAdp','cbsAdp','yahooAdp']
    src_keys = {'a': 'jack', 'slR': 'sl', 'fpR': 'fp', 'udA': 'ud', 'espnAdp': 'espn', 'cbsAdp': 'cbs', 'yahooAdp': 'yahoo'}
    ranks = {}
    for name, vals in day['f'].items():
        hit = idx.get(name, 'cons_rank_history')
        if not hit:
            continue
        rec = {}
        for fld, v in zip(fields, vals):
            if fld in src_keys and isinstance(v, (int, float)):
                rec[src_keys[fld]] = v
        if rec:
            ranks[hit['n']] = rec

    site = js_obj(git_show(PRESEASON_COMMIT, 'data/site_projections.js'))['players']
    sim = json.loads(git_show(PRESEASON_COMMIT, 'data/sim_proj_2026.json'))
    clay_txt = git_show(PRESEASON_COMMIT, 'data/mike_clay_projections.js')
    clay = {}
    for m in re.finditer(r'"([^"]+)":\s*\{([^}]*)\}', clay_txt):
        body = m.group(2)
        pts = re.search(r'\bpts:\s*(-?[\d.]+)', body)
        gm = re.search(r'\bgm:\s*(\d+)', body)
        if pts:
            clay[m.group(1)] = (float(pts.group(1)), int(gm.group(1)) if gm else 17)
    proj = {}
    # A site leg is season TOTALS unless its largest value is < 60, in which case that
    # pull stored per-game numbers already (CBS was PPG in the 09-09 commit).
    per_game = {}
    for k in ('sl', 'es', 'cb'):
        mx = max((v[k][1] for v in site.values() if v.get(k) and isinstance(v[k][1], (int, float))), default=0)
        per_game[k] = mx < 60
    for name, v in site.items():
        hit = idx.get(name, 'site_projections')
        if not hit:
            continue
        rec = {}
        for k in ('sl', 'es', 'cb'):
            a = v.get(k)
            if a and isinstance(a[1], (int, float)):
                rec[{'sl': 'sl', 'es': 'espn', 'cb': 'cbs'}[k]] = round(a[1] if per_game[k] else a[1] / 17, 2)
        if rec:
            proj[hit['n']] = rec
    for name, a in (sim.get('seasonPpg') or {}).items():
        hit = idx.get(name, 'sim_proj')
        if hit and a and isinstance(a[1], (int, float)):
            proj.setdefault(hit['n'], {})['sim'] = round(a[1], 2)
    for name, (pts, gm) in clay.items():
        hit = idx.get(name, 'clay')
        if hit and gm:
            proj.setdefault(hit['n'], {})['clay'] = round(pts / gm, 2)
    pre = {'commit': PRESEASON_COMMIT, 'consDay': PRESEASON_CONS_DAY, 'simUpdated': sim.get('updated'),
           'ranks': ranks, 'proj': proj}
    json.dump(pre, open(p, 'w', encoding='utf-8'), separators=(',', ':'))
    print(f'preseason: {len(ranks)} ranked players, {len(proj)} projected -> cached')
    return pre


# ---------------------------------------------------------------- actuals
def build_actuals(ws, idx):
    """name -> {wk: {pts, tm, opp}} for 2026 rows that represent a played game."""
    out, zero_rows = {}, 0
    for name, rec in ws.items():
        rows = (rec.get('seasons') or {}).get(str(SEASON)) or []
        if not rows:
            continue
        hit = idx.get(name, 'weekly_stats')
        if not hit:
            continue
        for r in rows:
            if not r.get('tm'):
                continue
            pts = ppr(r)
            if pts == 0 and not any(r.get(k) for k in ('pa', 'ra', 'tgt', 'rec')):
                zero_rows += 1
            out.setdefault(hit['n'], {})[int(r['wk'])] = {'pts': pts, 'tm': abbr(r.get('tm')), 'opp': abbr(r.get('opp'))}
    print(f'actuals: {len(out)} players with {SEASON} rows ({zero_rows} zero-touch rows kept)')
    return out


# ---------------------------------------------------------------- weekly
def load_kickoffs():
    p = os.path.join(SIM_LAB, 'data', f'kickoffs_{SEASON}.json')
    if not os.path.exists(p):
        print('WARN no kickoff cache', p)
        return {}
    raw = json.load(open(p, encoding='utf-8'))
    return {int(w): {abbr(t): iso for t, iso in teams.items()} for w, teams in raw.items()}


def load_snapshot(week):
    p = os.path.join(SIM_LAB, 'data', 'snapshots', f'simlab_snapshot_w{week}.json')
    if not os.path.exists(p):
        return None
    return json.load(open(p, encoding='utf-8'))


def pick_lock(versions_sorted, week, kickoff_iso):
    """Latest archived version for `week` whose `updated` < kickoff (None -> latest for week)."""
    best = None
    ko = parse_iso(kickoff_iso) if kickoff_iso else None
    for upd, ver in versions_sorted:
        if ver['week'] != week:
            continue
        if ko is not None and parse_iso(upd) >= ko:
            continue
        best = upd
    return best


def build_week(week, idx, actuals, locks, kick, snap):
    versions_sorted = sorted(locks['versions'].items())
    week_versions = [u for u, v in versions_sorted if v['week'] == week]
    players = {}
    simmap = {}
    if snap:
        for p in snap.get('players') or []:
            if p.get('pos') in POS:
                hit = idx.get(p['name'], 'snapshot')
                if hit:
                    simmap[hit['n']] = p
    # universe: anyone with an actual row, a sim lock, or a site lock this week
    names = set(simmap)
    for n, wk in actuals.items():
        if week in wk:
            names.add(n)
    for u in week_versions:
        names.update(locks['versions'][u]['players'].keys())
    for n in names:
        meta = idx.by_norm.get(norm(n))
        if not meta:
            continue
        a = actuals.get(n, {}).get(week)
        sp = simmap.get(n)
        tm = (a or {}).get('tm') or (sp or {}).get('tm') or meta.get('tm')
        tm = abbr(tm)
        ko = kick.get(tm) if tm else None
        if ko is None and kick:
            ko = min(kick.values())  # unknown team -> lock at the week's first kickoff (conservative)
        lv = pick_lock(versions_sorted, week, ko)
        site = locks['versions'][lv]['players'].get(n) if lv else None
        rec = {'pos': meta['pos'], 'tm': tm, 'opp': (a or {}).get('opp') or (sp or {}).get('opp'),
               'act': a['pts'] if a else None, 'ko': ko}
        if site:
            rec['site'] = site
            rec['lv'] = week_versions.index(lv)
        if sp:
            comps = sp.get('comps') or {}
            rec['sim'] = [sp.get('mean'), sp.get('p10'), sp.get('p50'), sp.get('p90'), comps.get('rec', 0) or 0,
                          sp.get('jsMean'), sp.get('clayMean')]
        players[n] = rec
    return {'season': SEASON, 'week': week, 'kick': kick, 'lockVersions': week_versions,
            'sim': ({'lockedAt': snap.get('lockedAt'), 'preset': snap.get('preset'), 'sims': snap.get('sims'),
                     'games': len(snap.get('lockedGames') or {})} if snap else None),
            'players': players}


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--backfill-git', action='store_true', help='archive every committed weekly_projections.json since Sep 8')
    a = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)

    D = js_arr(read(os.path.join(ROOT, 'data', 'd.js')))
    ws = js_obj(read(os.path.join(ROOT, 'data', 'weekly_stats_active.js')))
    idx = Index(D, ws)
    print(f'index: {len(idx.by_norm)} QB/RB/WR/TE names')

    locks = load_locks()
    if a.backfill_git:
        backfill_git(locks, idx)
    cur_p = os.path.join(ROOT, 'data', 'weekly_projections.json')
    if os.path.exists(cur_p):
        archive_version(locks, json.load(open(cur_p, encoding='utf-8')), idx, 'disk')
    json.dump(locks, open(os.path.join(OUT_DIR, f'locks_{SEASON}.json'), 'w', encoding='utf-8'), separators=(',', ':'))
    print(f'locks: {len(locks["versions"])} archived versions')

    pre = build_preseason(idx)
    actuals = build_actuals(ws, idx)
    kicks = load_kickoffs()

    weeks = set()
    for v in locks['versions'].values():
        weeks.add(v['week'])
    for wk in actuals.values():
        weeks.update(wk.keys())
    for f in os.listdir(os.path.join(SIM_LAB, 'data', 'snapshots')) if os.path.isdir(os.path.join(SIM_LAB, 'data', 'snapshots')) else []:
        m = re.match(r'simlab_snapshot_w(\d+)\.json$', f)
        if m:
            weeks.add(int(m.group(1)))
    weeks = sorted(w for w in weeks if 1 <= w <= 18)

    week_meta = []
    for w in weeks:
        snap = load_snapshot(w)
        wd = build_week(w, idx, actuals, locks, kicks.get(w, {}), snap)
        json.dump(wd, open(os.path.join(OUT_DIR, f'w{w}.json'), 'w', encoding='utf-8'), separators=(',', ':'))
        played = sum(1 for p in wd['players'].values() if p['act'] is not None)
        kv = list(wd['kick'].values())
        week_meta.append({'week': w, 'played': played, 'sim': bool(snap), 'locks': len(wd['lockVersions']),
                          'first': min(kv) if kv else None, 'last': max(kv) if kv else None})
        print(f'week {w}: {len(wd["players"])} players, {played} played, sim lock {"yes" if snap else "no"}, {len(wd["lockVersions"])} site versions')

    players = {}
    for k, meta in idx.by_norm.items():
        n = meta['n']
        rec = {'pos': meta['pos'], 'tm': meta['tm']}
        if n in pre['ranks']:
            rec['pre'] = pre['ranks'][n]
        if n in pre['proj']:
            rec['pj'] = pre['proj'][n]
        if n in actuals:
            wk = actuals[n]
            rec['act'] = {'wk': {str(w): v['pts'] for w, v in sorted(wk.items())}}
        if len(rec) > 2:
            players[n] = rec
    season = {'season': SEASON, 'updated': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'preseason': {'commit': pre['commit'], 'consDay': pre['consDay'], 'simUpdated': pre.get('simUpdated')},
              'weeks': week_meta, 'players': players}
    json.dump(season, open(os.path.join(OUT_DIR, f'season_{SEASON}.json'), 'w', encoding='utf-8'), separators=(',', ':'))
    print(f'season_{SEASON}.json: {len(players)} players, weeks {[w["week"] for w in week_meta]}')
    for src, names in idx.unmatched.items():
        print(f'  unmatched names [{src}]: {len(names)} e.g. {sorted(names)[:8]}')


if __name__ == '__main__':
    main()
