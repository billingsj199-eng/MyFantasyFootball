"""Team usage shares for the player card TEAM tab (Jack 2026-10-08).

Per player-week and per team-week counts from nflverse play-by-play, so the card can
show where every player stands in his own offense: target share, air-yard share,
aDOT, carry share, red-zone targets / carries, goal-line carries, dropbacks.

  p[name] = {t, pos, w: {wk: [team, tgt, air, car, rzT, rzC, glC, db]}}
  t[team] = {wk: [tgt, air, car, rzT, rzC, glC, db]}

Definitions (REG season, run/pass plays, two-point tries excluded):
  tgt  pass attempts with a receiver (incl. incompletions)
  air  air_yards on those targets (negative kept, nflverse convention)
  car  rush attempts (QB scrambles count as carries the way nflverse logs them)
  rzT / rzC  targets / carries snapped at the opponent 20 or closer
  glC  carries from the 5 or closer
  db   dropbacks as the passer (QB only)
Snap % and route % stay in data/snap_counts.js / data/route_pct.js.

Only players in data/d.js are kept (the card only opens for D-array players).
Run from the project root:  python scripts/build_team_usage.py [--dry]
"""
import argparse, json, os, sys
from datetime import datetime, timezone

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
from build_player_roles import CACHE, PLAYERS, TEAM_FIX, resolve  # noqa: E402  (also wraps stdout as utf-8)
from pull_snap_counts import load_d_names  # noqa: E402

SEASON = 2026
OUT = os.path.join(ROOT, 'data', f'team_usage_{SEASON}.js')
PBP = os.path.join(CACHE, f'play_by_play_{SEASON}.csv.gz')
RZ_YARD, GL_YARD = 20, 5


def tm(t):
    return TEAM_FIX.get(str(t), str(t))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()
    if not os.path.exists(PBP):
        print(f'missing {PBP}')
        sys.exit(1)
    lookup = load_d_names()
    pl = pd.read_csv(PLAYERS, low_memory=False, usecols=['gsis_id', 'display_name', 'position'])
    pinfo = {r.gsis_id: (str(r.display_name), str(r.position)) for r in pl.itertuples(index=False)
             if isinstance(r.gsis_id, str) and r.gsis_id.startswith('00-')}
    cols = ['season_type', 'week', 'posteam', 'play_type', 'rush_attempt', 'pass_attempt', 'qb_dropback',
            'rusher_player_id', 'receiver_player_id', 'passer_player_id', 'yardline_100', 'air_yards',
            'two_point_attempt']
    df = pd.read_csv(PBP, low_memory=False, usecols=cols)
    df = df[(df.season_type == 'REG') & df.posteam.notna() & df.play_type.isin(['run', 'pass'])]
    df = df[df.two_point_attempt.fillna(0) != 1]

    players, teams, miss = {}, {}, set()
    # row slots: 0 tgt, 1 air, 2 car, 3 rzT, 4 rzC, 5 glC, 6 db
    def bump(name, pos, team, wk, idx, n=1):
        p = players.setdefault(name, {'t': team, 'pos': pos, 'w': {}})
        row = p['w'].setdefault(wk, [team, 0, 0, 0, 0, 0, 0, 0])
        row[0] = team
        row[idx + 1] += n

    def who(gid):
        info = pinfo.get(gid) if isinstance(gid, str) else None
        if not info:
            return None, None
        dn = resolve(lookup, info[0])
        if not dn:
            miss.add(info[0])
        pos = {'HB': 'RB', 'FB': 'RB'}.get(info[1], info[1])
        return dn, pos

    for r in df.itertuples(index=False):
        wk, team = str(int(r.week)), tm(r.posteam)
        T = teams.setdefault(team, {}).setdefault(wk, [0, 0, 0, 0, 0, 0, 0])
        yl = r.yardline_100 if r.yardline_100 == r.yardline_100 else None
        rz, gl = (yl is not None and yl <= RZ_YARD), (yl is not None and yl <= GL_YARD)
        if r.pass_attempt == 1 and isinstance(r.receiver_player_id, str):
            ay = r.air_yards if r.air_yards == r.air_yards else 0
            T[0] += 1; T[1] += ay
            if rz:
                T[3] += 1
            dn, pos = who(r.receiver_player_id)
            if dn:
                bump(dn, pos, team, wk, 0)
                bump(dn, pos, team, wk, 1, ay)
                if rz:
                    bump(dn, pos, team, wk, 3)
        if r.rush_attempt == 1 and isinstance(r.rusher_player_id, str):
            T[2] += 1
            if rz:
                T[4] += 1
            if gl:
                T[5] += 1
            dn, pos = who(r.rusher_player_id)
            if dn:
                bump(dn, pos, team, wk, 2)
                if rz:
                    bump(dn, pos, team, wk, 4)
                if gl:
                    bump(dn, pos, team, wk, 5)
        if r.qb_dropback == 1:
            T[6] += 1
            dn, pos = who(r.passer_player_id)
            if dn:
                bump(dn, pos, team, wk, 6)

    for p in players.values():
        last = max(p['w'], key=int)
        p['t'] = p['w'][last][0]
        for row in p['w'].values():
            row[2] = round(row[2])
    for t in teams.values():
        for row in t.values():
            row[1] = round(row[1])
    thru = max((int(w) for t in teams.values() for w in t), default=0)
    doc = {'updated': datetime.now(timezone.utc).isoformat(), 'season': SEASON, 'thru': thru,
           't': teams, 'p': players}
    print(f'thru week {thru}: {len(players)} players, {len(teams)} teams, {len(miss)} names not in d.js')
    for nm in ('Antonio Williams', 'Terry McLaurin', 'Jacory Croskey-Merritt', 'Jayden Daniels', "Ja'Marr Chase"):
        if nm in players:
            print(f'  {nm:24s} {players[nm]["t"]} {players[nm]["w"]}')
    if args.dry:
        return
    body = json.dumps(doc, separators=(',', ':'), ensure_ascii=False)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('// AUTO-GENERATED by scripts/build_team_usage.py (nflverse pbp: targets, air yards, carries, red zone)\n')
        f.write('window.TEAM_USAGE_2026 = ' + body + ';\n')
    print(f'wrote {OUT} ({os.path.getsize(OUT) // 1024} KB)')


if __name__ == '__main__':
    main()
