#!/usr/bin/env python3
"""
Post-game 2026 weekly stats import -> data/weekly_stats_active.js

Runs after every game window (Task Scheduler "MFF Postgame Stats", wrapped
by scripts/postgame_stats.ps1) so game logs, L4 PPG and '26 PPG on the site
fill in the same night instead of waiting for the Tuesday full chain
(sim_lab/tuesday_stats.ps1 -> data/fetch_weekly_stats.py).

What it does
  1. ESPN scoreboard (curl UA only — browser UAs get 403) for every 2026
     regular-season week up to the current one: which games are FINAL and
     who played whom. Only players on a team whose game is final get a row,
     so a run that overlaps a live window never bakes partial box scores
     (Sleeper's stats endpoint is live during games).
  2. Sleeper /v1/stats/nfl/regular/2026/{week} for those weeks, mapped to
     D-array names the same way fetch_weekly_stats.py does. Since 2025
     Sleeper rows no longer carry team/opponent — both come from the
     Sleeper player DB (team) + the ESPN scoreboard pairing (opp).
  3. Merge into weekly_stats_active.js, 2026 season ONLY: a fresh row
     REPLACES the existing row for that player-week (stat corrections land;
     the Tuesday script's merge is existing-wins and never touches this).
     Every other season is passed through byte-for-byte.
  4. (2026-10-27) Provisional usage denominators -> data/snap_counts.js, so the
     card's SNP% / TS% / CAR% (and RT%, re-estimated from snaps by the wrapper)
     land with the box score instead of waiting a day for nflverse: Sleeper
     off_snp / tm_off_snp per board player-week, and team targets / carries
     summed over EVERY Sleeper player on a final team. Fills only what
     nflverse has not posted yet; player-weeks written here are listed in the
     season's `p` and replaced by the morning nflverse rebuild
     (pull_snap_counts.py). W1-7 check: snap % identical in 2107/2146
     player-weeks (max 5 pts), team targets exact in 180/212 (max 6, trades).

Usage
  python scripts/pull_postgame_stats.py            # import + write
  python scripts/pull_postgame_stats.py --dry-run  # report only
  python scripts/pull_postgame_stats.py --week 3   # cap at week 3
Exit 0 = ok (stdout says whether the file changed), 1 = fetch failure.
"""

import argparse
import io
import json
import os
import sys
import time
from collections import defaultdict

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D_JS = os.path.join(ROOT, 'data', 'd.js')
WS_JS = os.path.join(ROOT, 'data', 'weekly_stats_active.js')
# Complete-league fantasy points ALLOWED per defense per week (ALL Sleeper
# QB/RB/WR/TE in FINAL games, half-PPR) -> feeds the site's SOS observed-FPA
# blend (_mtObservedFpa) and Sim Lab's opponent layer (refresh_data.py).
# Added 2026-09-14: the board-only sums from weekly_stats_active undercount
# whenever a defense faces an untracked player (PIT read 0.0 QB allowed in
# W1 because Cooper Rush isn't on the board).
FPA_JS = os.path.join(ROOT, 'data', 'fpa_2026.js')
FPA_JSON = os.path.join(ROOT, 'data', 'fpa_2026.json')   # same object, fetched by the Sleeper/ESPN/Yahoo helpers
SNAP_JS = os.path.join(ROOT, 'data', 'snap_counts.js')     # nflverse build (pull_snap_counts.py) + provisional weeks (step 4)
SNAP_VARS = ('SNAP_COUNTS', 'TEAM_TGT', 'TEAM_CAR')
FPA_POS = ('QB', 'RB', 'WR', 'TE')
# 2026-09-15: the rankings WEEKLY board's OPP PPG column reads this table too,
# so every defense-week also carries PPR / STD variants of the four skill
# positions (`RB_ppr`, `RB_std`; bare `RB` stays half-PPR for the older
# readers) plus the points scored AGAINST that team by opposing kickers (`K`)
# and opposing D/STs (`DST`, Sleeper default DST scoring). For K/DST the
# "defense" key is really the OFFENSE that gave up those points.
FPA_EXTRA_POS = ('K', 'DEF')
FPA_SCORING = (('', 'pts_half_ppr'), ('_ppr', 'pts_ppr'), ('_std', 'pts_std'))
# 2026-10-05: TOUCHDOWN-NEUTRAL twins (`RB_tdn`, `DST_tdn`) - the number the
# site's opponent GRADE is built on (app.js _mtObservedFpa); the bare keys stay
# the actual points the board shows. Actual TDs are swapped for the league TD
# rate on the yards allowed (half-PPR basis); for DST the defensive and return
# TDs are dropped. 2016-25 backtest (research_opp_grade_schemes.py): this beat
# actual points at every position. Same constants as build_fpa_prior.py, which
# builds last season's side of the blend - keep the two in sync.
TDN_PASS, TDN_RUSH, TDN_REC = 0.00626, 0.00759, 0.00623   # league TDs per yard, 2014-25


def td_neutral(s):
    n = lambda k: s.get(k) or 0  # noqa: E731
    return ((s.get('pts_half_ppr') or 0) - 4 * n('pass_td') - 6 * (n('rush_td') + n('rec_td'))
            + 4 * TDN_PASS * n('pass_yd') + 6 * (TDN_RUSH * n('rush_yd') + TDN_REC * n('rec_yd')))
SLEEPER_DB = {}   # sid -> Sleeper player record (filled by sleeper_id_map)

SEASON = 2026
SCOREBOARD = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'
SLEEPER_PLAYERS = 'https://api.sleeper.app/v1/players/nfl'
SLEEPER_STATS = 'https://api.sleeper.app/v1/stats/nfl/regular/{yr}/{wk}'
UA = {'User-Agent': 'curl/8.4.0', 'Accept': '*/*'}
# ESPN -> Sleeper/site abbreviations (only the ones that differ).
ABBR_FIX = {'WSH': 'WAS', 'JAC': 'JAX', 'LA': 'LAR', 'OAK': 'LV', 'SD': 'LAC'}


def log(msg):
    print(msg, flush=True)


def get_json(url, params=None, tries=3, timeout=25):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last = 'HTTP %s' % r.status_code
        except Exception as e:  # noqa: BLE001
            last = str(e)
        time.sleep(1.5 * (i + 1))
    raise RuntimeError('%s -> %s' % (url, last))


# ---------------------------------------------------------------- targets
def normalize(name):
    n = name.lower().strip()
    for ch in ('.', "'", '’'):
        n = n.replace(ch, '')
    return n


SUFFIXES = (' jr', ' sr', ' iii', ' ii', ' iv')


def strip_suffix(n):
    for s in SUFFIXES:
        if n.endswith(s):
            return n[: -len(s)].strip()
    return n


TEAM_ABBR = {
    'Arizona Cardinals': 'ARI', 'Atlanta Falcons': 'ATL', 'Baltimore Ravens': 'BAL',
    'Buffalo Bills': 'BUF', 'Carolina Panthers': 'CAR', 'Chicago Bears': 'CHI',
    'Cincinnati Bengals': 'CIN', 'Cleveland Browns': 'CLE', 'Dallas Cowboys': 'DAL',
    'Denver Broncos': 'DEN', 'Detroit Lions': 'DET', 'Green Bay Packers': 'GB',
    'Houston Texans': 'HOU', 'Indianapolis Colts': 'IND', 'Jacksonville Jaguars': 'JAX',
    'Kansas City Chiefs': 'KC', 'Las Vegas Raiders': 'LV', 'Los Angeles Chargers': 'LAC',
    'Los Angeles Rams': 'LAR', 'Miami Dolphins': 'MIA', 'Minnesota Vikings': 'MIN',
    'New England Patriots': 'NE', 'New Orleans Saints': 'NO', 'New York Giants': 'NYG',
    'New York Jets': 'NYJ', 'Philadelphia Eagles': 'PHI', 'Pittsburgh Steelers': 'PIT',
    'San Francisco 49ers': 'SF', 'Seattle Seahawks': 'SEA', 'Tampa Bay Buccaneers': 'TB',
    'Tennessee Titans': 'TEN', 'Washington Commanders': 'WAS',
}
TARGET_TEAM = {}   # D name -> site team abbr ('' for FA), filled by load_targets
# Sleeper positions that can stand in for a site position (Juszczyk = FB, Travis Hunter = DB).
POS_COMPAT = {'QB': ('QB',), 'RB': ('RB', 'FB'), 'WR': ('WR', 'DB', 'CB', 'S'), 'TE': ('TE',)}
SLEEPER_POOL_POS = ('QB', 'RB', 'WR', 'TE', 'FB', 'DB', 'CB', 'S')


def load_targets():
    with open(D_JS, 'r', encoding='utf-8') as f:
        raw = f.read()
    D = json.loads(raw[raw.index('['):raw.rindex(']') + 1])
    TARGET_TEAM.clear()
    TARGET_TEAM.update({p['n']: TEAM_ABBR.get(p.get('t') or '', '') for p in D
                        if p.get('s') in ('QB', 'RB', 'WR', 'TE')})
    return {p['n']: p['s'] for p in D if p.get('s') in ('QB', 'RB', 'WR', 'TE')}


def sleeper_id_map(targets):
    """D name -> (sleeper_id, team) using the Sleeper player DB.

    Match order per target: exact normalized name -> suffix-stripped / suffix-added
    (Sleeper drops Jr./III; the site keeps them) -> last name + team + position
    (Sleeper first-name nicknames: Kenny Gainwell, Joshua Palmer, Matt Hibner,
    DeaMonte Trayanum...). When several Sleeper records share a name, the one on the
    site's team wins, then the active one, so a suffix-stripped 'Michael Pittman'
    cannot land on the retired Sr.
    """
    db = get_json(SLEEPER_PLAYERS, timeout=60)
    SLEEPER_DB.update(db)
    by_name = defaultdict(list)     # normalized full name -> [(sid, team, pos, active)]
    by_last = defaultdict(list)     # (last name, team) -> same
    for sid, sp in db.items():
        pos = sp.get('position')
        if pos not in SLEEPER_POOL_POS:
            continue
        full = sp.get('full_name') or ('%s %s' % (sp.get('first_name', ''), sp.get('last_name', ''))).strip()
        if not full:
            continue
        rec = (sid, sp.get('team') or '', pos, bool(sp.get('active')))
        key = normalize(full)
        by_name[key].append(rec)
        last = strip_suffix(normalize(sp.get('last_name') or full.split()[-1]))
        if rec[1]:
            by_last[(last, rec[1])].append(rec)

    def pick(cands, name, strict_pos):
        pos_ok = POS_COMPAT[targets[name]] if strict_pos else SLEEPER_POOL_POS
        cands = [c for c in cands if c[2] in pos_ok]
        if not cands:
            return None
        team = TARGET_TEAM.get(name, '')
        cands.sort(key=lambda c: (c[1] == team and bool(team), c[3]), reverse=True)
        return cands[0]

    out, missed = {}, []
    for name in targets:
        key = normalize(name)
        hit = pick(by_name.get(key, []), name, strict_pos=False)
        if not hit:
            st = strip_suffix(key)
            if st != key:
                hit = pick(by_name.get(st, []), name, strict_pos=False)
            if not hit:
                for s in SUFFIXES:
                    hit = pick(by_name.get(key + s, []), name, strict_pos=False)
                    if hit:
                        break
        if not hit and TARGET_TEAM.get(name):
            last = st.split()[-1] if ' ' in st else st
            cands = by_last.get((last, TARGET_TEAM[name]), [])
            cands = [c for c in cands if c[2] in POS_COMPAT[targets[name]]]
            if len(cands) == 1 or (cands and sum(1 for c in cands if c[3]) == 1):
                hit = pick(cands, name, strict_pos=True)
        if hit:
            out[name] = (hit[0], hit[1])
        else:
            missed.append('%s (%s %s)' % (name, targets[name], TARGET_TEAM.get(name) or 'FA'))
    if missed:
        log('  no Sleeper id for: ' + ', '.join(missed))
    return out


# ---------------------------------------------------------------- ESPN
def scoreboard(week=None):
    # No params = ESPN's own "current" week (carries the top-level season).
    # A bare dates=2026 drops the season key and returns a 100-event mix of
    # seasons, so a specific week is always asked for with all three params.
    params = {'dates': SEASON, 'seasontype': 2, 'week': week} if week else None
    return get_json(SCOREBOARD, params=params)


def final_games(sb, week):
    """{team: opp} for every FINAL game in a scoreboard payload; plus counts."""
    finals, total = {}, 0
    for ev in sb.get('events', []):
        es, ew = ev.get('season') or {}, ev.get('week') or {}
        if es.get('year') != SEASON or es.get('type') != 2 or ew.get('number') != week:
            continue
        total += 1
        st = (ev.get('status') or {}).get('type') or {}
        comp = (ev.get('competitions') or [{}])[0]
        teams = [c.get('team', {}).get('abbreviation', '') for c in comp.get('competitors', [])]
        teams = [ABBR_FIX.get(t, t) for t in teams if t]
        if len(teams) != 2:
            continue
        if st.get('completed') or st.get('name') == 'STATUS_FINAL':
            finals[teams[0]] = teams[1]
            finals[teams[1]] = teams[0]
    return finals, total


# ---------------------------------------------------------------- Sleeper rows
def build_row(pos, wk, tm, opp, s):
    fpts = round(s.get('pts_half_ppr', 0) or 0, 1)

    def i(k):
        v = s.get(k, 0) or 0
        return int(v) if float(v).is_integer() else v

    if pos == 'QB':
        return {'wk': wk, 'tm': tm, 'opp': opp, 'fpts': fpts,
                'py': i('pass_yd'), 'ptd': i('pass_td'), 'int': i('pass_int'),
                'pa': i('pass_att'), 'pc': i('pass_cmp'),
                'ry': i('rush_yd'), 'rtd': i('rush_td'), 'ra': i('rush_att'),
                'fl': i('fum_lost')}
    return {'wk': wk, 'tm': tm, 'opp': opp, 'fpts': fpts,
            'ra': i('rush_att'), 'ry': i('rush_yd'), 'rtd': i('rush_td'),
            'rec': i('rec'), 'rcy': i('rec_yd'), 'rctd': i('rec_td'),
            'tgt': i('rec_tgt'), 'fl': i('fum_lost')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--week', type=int, default=None, help='cap at this week (default: ESPN current week)')
    args = ap.parse_args()

    targets = load_targets()
    log('targets: %d QB/RB/WR/TE in d.js' % len(targets))

    cur = scoreboard()
    cur_week = int((cur.get('week') or {}).get('number') or 0)
    season_yr = int(((cur.get('season') or {}).get('year')) or 0)
    season_type = int(((cur.get('season') or {}).get('type')) or 0)
    if season_yr != SEASON or season_type != 2 or cur_week < 1:
        log('ESPN says season %s type %s week %s - not the %d regular season, nothing to import' % (season_yr, season_type, cur_week, SEASON))
        return 0
    last_week = min(cur_week, args.week) if args.week else cur_week
    log('ESPN current week: %d (importing weeks 1-%d)' % (cur_week, last_week))

    idmap = sleeper_id_map(targets)
    log('sleeper ids matched: %d/%d' % (len(idmap), len(targets)))
    by_sid = {sid: (name, team) for name, (sid, team) in idmap.items()}

    # week -> {name: row}
    new_rows = defaultdict(dict)
    fpa_weeks = {}   # week -> {DEF: {'opp': TM, 'QB': pts, 'RB': .., 'WR': .., 'TE': ..}}
    snaps = defaultdict(dict)                         # name -> {wk: (off_snp, tm_off_snp)}
    team_tgt, team_car = defaultdict(dict), defaultdict(dict)   # team -> {wk: total}
    # Sleeper's tm_off_snp runs short some games (PHI W7 2026: 62 while McKee and
    # the line played 66 = nflverse's team total), so the denominator is the most
    # snaps anyone on that team-game played, OL included, when that is higher.
    # Keyed by tm_off_snp as well: a traded player's row carries his old team's game.
    snap_max = {}                                     # (wk, team, tm_off_snp) -> max off_snp
    for wk in range(1, last_week + 1):
        sb = cur if wk == cur_week else scoreboard(wk)
        finals, total = final_games(sb, wk)
        n_final = len(finals) // 2
        if not finals:
            log('  W%d: 0/%d games final - skipped' % (wk, total))
            continue
        stats = get_json(SLEEPER_STATS.format(yr=SEASON, wk=wk))
        kept = skipped_live = 0
        # complete-league points allowed: every Sleeper skill player whose game is FINAL
        for sid, s in stats.items():
            sp = SLEEPER_DB.get(sid) or {}
            pos, team = sp.get('position'), sp.get('team') or ''
            if pos == 'DEF' and not team:
                team = sid   # Sleeper D/ST ids ARE the team abbr
            team = ABBR_FIX.get(team, team)
            if pos != 'DEF' and team in finals:
                # complete-league team targets / carries (TS% / CAR% denominators)
                t, c = s.get('rec_tgt') or 0, s.get('rush_att') or 0
                if t:
                    team_tgt[team][wk] = team_tgt[team].get(wk, 0) + t
                if c:
                    team_car[team][wk] = team_car[team].get(wk, 0) + c
                if s.get('off_snp') and s.get('tm_off_snp'):
                    k = (wk, team, s['tm_off_snp'])
                    snap_max[k] = max(snap_max.get(k, 0), s['off_snp'])
            if (pos not in FPA_POS and pos not in FPA_EXTRA_POS) or team not in finals:
                continue
            pts = s.get('pts_half_ppr') or s.get('pts_std') or 0
            if not pts and not (s.get('gp') or 0):
                continue
            slot = fpa_weeks.setdefault(str(wk), {}).setdefault(finals[team], {'opp': team})
            if pos in FPA_POS:
                for suf, key in FPA_SCORING:
                    slot[pos + suf] = round(slot.get(pos + suf, 0) + (s.get(key) or 0), 2)
                slot[pos + '_tdn'] = round(slot.get(pos + '_tdn', 0) + td_neutral(s), 2)
            else:
                k = 'DST' if pos == 'DEF' else pos
                slot[k] = round(slot.get(k, 0) + (s.get('pts_std') or pts), 2)
                if pos == 'DEF':
                    tds = (s.get('def_td') or 0) + (s.get('def_st_td') or 0) + (s.get('st_td') or 0)
                    slot['DST_tdn'] = round(slot.get('DST_tdn', 0) + (s.get('pts_std') or pts) - 6 * tds, 2)
        for sid, s in stats.items():
            hit = by_sid.get(sid)
            if not hit:
                continue
            name, team = hit
            gp = s.get('gp', 0) or 0
            if not gp and not (s.get('pts_half_ppr') or 0):
                continue
            if team not in finals:
                skipped_live += 1   # game not final yet (or player teamless)
                continue
            new_rows[wk][name] = build_row(targets[name], wk, team, finals[team], s)
            kept += 1
            if (s.get('off_snp') or 0) > 0 and (s.get('tm_off_snp') or 0) > 0:
                sp_tm = (SLEEPER_DB.get(sid) or {}).get('team') or ''
                tm_snaps = max(s['tm_off_snp'], s['off_snp'],
                               snap_max.get((wk, ABBR_FIX.get(sp_tm, sp_tm), s['tm_off_snp']), 0))
                snaps[name][wk] = (s['off_snp'], tm_snaps)
        log('  W%d: %d/%d games final - %d player rows kept, %d held (game not final)' % (wk, n_final, total, kept, skipped_live))
        time.sleep(0.2)

    # ------------------------------------------------------------ merge
    with open(WS_JS, 'r', encoding='utf-8') as f:
        raw = f.read()
    head = raw[:raw.index('{')]
    existing = json.loads(raw[raw.index('{'):raw.rindex('}') + 1])
    yr = str(SEASON)
    added = replaced = unchanged = 0
    for wk, rows in new_rows.items():
        for name, row in rows.items():
            entry = existing.get(name)
            if entry is None:
                entry = existing[name] = {'pos': targets[name], 'seasons': {}}
            weeks = entry['seasons'].setdefault(yr, [])
            idx = next((i for i, w in enumerate(weeks) if w.get('wk') == wk), None)
            if idx is None:
                weeks.append(row)
                added += 1
            elif weeks[idx] != row:
                weeks[idx] = row
                replaced += 1
            else:
                unchanged += 1
            weeks.sort(key=lambda w: w.get('wk', 0))

    out = {k: existing[k] for k in sorted(existing)}
    js = head + json.dumps(out, separators=(',', ':')) + ';'
    changed = js != raw
    log('merge: %d rows added, %d replaced (corrections), %d unchanged -> %s' % (
        added, replaced, unchanged, 'FILE CHANGED' if changed else 'no change'))
    if args.dry_run:
        write_snaps(snaps, team_tgt, team_car, dry_run=True)
        log('dry run - not written (fpa_2026.js / snap_counts.js also skipped)')
        return 0
    if changed:
        with open(WS_JS, 'w', encoding='utf-8') as f:
            f.write(js)
        log('wrote %s (%.1f MB)' % (WS_JS, len(js) / 1048576))
    write_fpa(fpa_weeks)
    write_snaps(snaps, team_tgt, team_car)
    return 0


def write_snaps(snaps, team_tgt, team_car, dry_run=False):
    """Fill data/snap_counts.js with the player-weeks / team-weeks nflverse has not
    posted yet (step 4 in the module doc). A player-week already from nflverse is
    never touched; one this script wrote before (listed in the season's `p`) is
    rewritten, so Sleeper stat corrections land until nflverse takes over. The
    season share `s` of a player with a provisional week is the Sleeper
    season-to-date (same numbers nflverse posts, see the W1-7 check)."""
    if not os.path.exists(SNAP_JS):
        log('snap_counts.js missing - provisional usage skipped')
        return
    raw = open(SNAP_JS, 'r', encoding='utf-8').read()
    objs = {}
    for var in SNAP_VARS:
        i = raw.index('window.%s=' % var) + len('window.%s=' % var)
        objs[var] = json.JSONDecoder().raw_decode(raw, i)[0]
    yr = str(SEASON)
    n_snap = n_tgt = n_car = 0
    for name, wks in snaps.items():
        cur = objs['SNAP_COUNTS'].setdefault(name, {}).setdefault(yr, {'s': None, 'w': {}})
        prov = set(cur.get('p') or [])
        for wk, (off, tm) in wks.items():
            k = str(wk)
            if k in cur['w'] and k not in prov:
                continue   # nflverse already has it
            v = round(100.0 * off / tm)
            if cur['w'].get(k) != v:
                n_snap += 1
            cur['w'][k] = v
            prov.add(k)
        if prov:
            cur['w'] = {k: cur['w'][k] for k in sorted(cur['w'], key=int)}
            cur['p'] = sorted(prov, key=int)
            off_tot, tm_tot = sum(o for o, _ in wks.values()), sum(t for _, t in wks.values())
            cur['s'] = round(100.0 * off_tot / tm_tot, 1)
    for var, src in (('TEAM_TGT', team_tgt), ('TEAM_CAR', team_car)):
        season = objs[var].setdefault(yr, {})
        for team, wks in src.items():
            for wk, tot in wks.items():
                if str(wk) in season.get(team, {}):
                    continue
                season.setdefault(team, {})[str(wk)] = int(tot)
                if var == 'TEAM_TGT':
                    n_tgt += 1
                else:
                    n_car += 1
        for team in season:
            season[team] = {k: season[team][k] for k in sorted(season[team], key=int)}
    js = ''.join('window.%s=%s;\n' % (var, json.dumps(objs[var], separators=(',', ':'))) for var in SNAP_VARS)
    n_prov = sum(1 for p in objs['SNAP_COUNTS'].values() for w in (p.get(yr) or {}).get('p') or [])
    log('snap_counts.js: %d provisional snap weeks changed (%d on file), %d team target weeks + %d team carry weeks added%s' % (
        n_snap, n_prov, n_tgt, n_car, '' if js != raw else ' - no change'))
    if dry_run or js == raw:
        return
    with open(SNAP_JS, 'w', encoding='utf-8') as f:
        f.write(js)
    log('wrote %s' % SNAP_JS)


def load_prior():
    """Last season's side of the opponent grade (data/fpa_prior_<SEASON-1>.js, built by
    build_fpa_prior.py). Carried inside fpa_2026.json as `prior` so the Sleeper / ESPN /
    Yahoo helpers get both halves of the blend in the one fetch they already make."""
    path = os.path.join(ROOT, 'data', 'fpa_prior_%d.js' % (SEASON - 1))
    if not os.path.exists(path):
        return None
    try:
        raw = open(path, 'r', encoding='utf-8').read()
        obj = json.loads(raw[raw.index('{'):raw.rindex('}') + 1])
        return {'season': obj.get('season'), 'pos': obj.get('pos')} if obj.get('pos') else None
    except Exception as e:  # noqa: BLE001
        log('  %s unreadable (%s) - no prior in fpa_2026' % (os.path.basename(path), e))
        return None


def write_fpa(fpa_weeks):
    """Merge this run's complete-league FPA weeks into data/fpa_2026.js
    (fresh week replaces; weeks not recomputed this run are kept)."""
    existing = {}
    if os.path.exists(FPA_JS):
        try:
            raw = open(FPA_JS, 'r', encoding='utf-8').read()
            existing = json.loads(raw[raw.index('{'):raw.rindex('}') + 1])
        except Exception as e:  # noqa: BLE001
            log('  fpa_2026.js unreadable (%s) - rebuilding' % e)
            existing = {}
    weeks = dict(existing.get('weeks') or {})
    for wk, teams in fpa_weeks.items():
        full = {}
        for d, rec in sorted(teams.items()):
            full[d] = {'opp': rec.get('opp', '')}
            for p in FPA_POS:
                for suf, _k in FPA_SCORING:
                    full[d][p + suf] = round(rec.get(p + suf, 0), 1)
                full[d][p + '_tdn'] = round(rec.get(p + '_tdn', 0), 1)
            for p in ('K', 'DST'):
                full[d][p] = round(rec.get(p, 0), 1)
            full[d]['DST_tdn'] = round(rec.get('DST_tdn', 0), 1)
        weeks[wk] = full
    prior = load_prior()
    if weeks == (existing.get('weeks') or {}) and prior == existing.get('prior'):
        log('fpa_2026.js: %d weeks, no change' % len(weeks))
        return
    obj = {'season': SEASON, 'basis': 'half_ppr', 'pos': list(FPA_POS),
           'updated': time.strftime('%Y-%m-%dT%H:%M:%S'),
           'weeks': {k: weeks[k] for k in sorted(weeks, key=int)}}
    if prior:
        obj['prior'] = prior
    out = ('// AUTO-GENERATED by scripts/pull_postgame_stats.py - fantasy points ALLOWED per defense per week\n'
           '// ALL Sleeper QB/RB/WR/TE in FINAL games (half-PPR; _ppr/_std variants alongside), not just board players. opp = offense faced.\n'
           '// K / DST = points scored AGAINST this team by the opposing kicker / D/ST (Sleeper default scoring).\n'
           '// <POS>_tdn = touchdown-neutral twin (TDs swapped for the league rate on the yards; DST: defensive / return TDs out) - the opponent GRADE reads these.\n'
           'window.FPA_2026 = ' + json.dumps(obj, separators=(',', ':')) + ';\n')
    with open(FPA_JS, 'w', encoding='utf-8') as f:
        f.write(out)
    # Plain-JSON twin for the browser extensions (their site fetch proxies
    # parse JSON only). Tracked with `git add -f` — /data/*.json is excluded.
    with open(FPA_JSON, 'w', encoding='utf-8') as f:
        f.write(json.dumps(obj, separators=(',', ':')))
    n = sum(len(v) for v in weeks.values())
    log('wrote %s + %s (%d weeks, %d defense-weeks)' % (FPA_JS, FPA_JSON, len(weeks), n))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        log('FAILED: %s' % e)
        sys.exit(1)
