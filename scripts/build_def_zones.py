"""Defense zone heat map for the player-card MATCHUP tab (Jack 2026-10-27).

Fantasy points each defense allowed per game, split into eight zones from nflverse
play-by-play, plus every pass catcher's targets by depth so the card can put him
in his lane:

  zones  0 QB_PASS   passing yards .04 / pass TD 4 / INT -1 (QB passers)
         1 QB_RUSH   QB rushing yards .1 / rush TD 6 (scrambles included)
         2 RB_RUSH   RB rushing
         3 RB_REC    RB receiving (all depths)
         4 WR_SHORT  WR targets under 10 air yards (behind the line included)
         5 WR_MID    WR targets 10-19 air yards
         6 WR_DEEP   WR targets 20+ air yards
         7 TE        TE receiving (all depths)
  receiving = .5 per catch + yards .1 + TD 6 (half-PPR); r = catches per zone so the
  card can shift to PPR (+.5) / STD (-.5). Fumbles and two-point tries left out.

  g[DEF][wk]  = [opp, z0..z7 (half-PPR pts), r0..r7 (catches)]
  p[name]     = [t, pos, tgtShort, tgtMid, tgtDeep, airYds]   (d.js names only)

The card schedule-adjusts each zone the same way SOS / the weekly OPP color do
(window._wkSchedAdjust: defense + offense effects solved together).

Run from the project root:  python scripts/build_def_zones.py [--dry]
"""
import argparse, json, os, sys
from datetime import datetime, timezone

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
from build_player_roles import CACHE, PLAYERS, TEAM_FIX, resolve  # noqa: E402  (also wraps stdout as utf-8)
from pull_snap_counts import load_d_names  # noqa: E402

SEASON = 2026
OUT = os.path.join(ROOT, 'data', f'def_zones_{SEASON}.js')
PBP = os.path.join(CACHE, f'play_by_play_{SEASON}.csv.gz')
ZONES = ['QB_PASS', 'QB_RUSH', 'RB_RUSH', 'RB_REC', 'WR_SHORT', 'WR_MID', 'WR_DEEP', 'TE']
SHORT_MAX, DEEP_MIN = 10, 20


def tm(t):
    return TEAM_FIX.get(str(t), str(t))


def num(v):
    return 0.0 if v != v or v is None else float(v)


def depth_idx(ay):
    ay = num(ay)
    return 0 if ay < SHORT_MAX else (2 if ay >= DEEP_MIN else 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()
    if not os.path.exists(PBP):
        print(f'missing {PBP}')
        sys.exit(1)
    lookup = load_d_names()
    pl = pd.read_csv(PLAYERS, low_memory=False, usecols=['gsis_id', 'display_name', 'position'])
    pinfo = {r.gsis_id: (str(r.display_name), {'HB': 'RB', 'FB': 'RB'}.get(str(r.position), str(r.position)))
             for r in pl.itertuples(index=False) if isinstance(r.gsis_id, str) and r.gsis_id.startswith('00-')}
    cols = ['season_type', 'week', 'posteam', 'defteam', 'play_type', 'two_point_attempt', 'air_yards',
            'passer_player_id', 'passing_yards', 'interception', 'pass_touchdown',
            'receiver_player_id', 'receiving_yards', 'complete_pass',
            'rusher_player_id', 'rushing_yards', 'rush_touchdown']
    df = pd.read_csv(PBP, low_memory=False, usecols=cols)
    df = df[(df.season_type == 'REG') & df.posteam.notna() & df.defteam.notna() & df.play_type.isin(['run', 'pass'])]
    df = df[df.two_point_attempt.fillna(0) != 1]

    games, players, miss = {}, {}, set()

    def slot(d, wk, o):
        row = games.setdefault(d, {}).setdefault(wk, [o] + [0.0] * 8 + [0] * 8)
        return row

    def pos_of(gid):
        info = pinfo.get(gid) if isinstance(gid, str) else None
        return info[1] if info else None

    for r in df.itertuples(index=False):
        wk, d, o = str(int(r.week)), tm(r.defteam), tm(r.posteam)
        row = slot(d, wk, o)
        if r.play_type == 'pass':
            if pos_of(r.passer_player_id) == 'QB':
                row[1] += num(r.passing_yards) * .04 + 4 * num(r.pass_touchdown) - num(r.interception)
            rp = pos_of(r.receiver_player_id)
            if rp in ('RB', 'WR', 'TE'):
                di = depth_idx(r.air_yards)
                z = {'RB': 3, 'TE': 7}.get(rp, 4 + di)
                c = num(r.complete_pass)
                row[1 + z] += .5 * c + num(r.receiving_yards) * .1 + 6 * num(r.pass_touchdown)
                row[9 + z] += int(c)
                info = pinfo.get(r.receiver_player_id)
                dn = resolve(lookup, info[0]) if info else None
                if dn:
                    p = players.setdefault(dn, [o, rp, 0, 0, 0, 0])
                    p[0] = o
                    p[2 + di] += 1
                    p[5] += num(r.air_yards)
                elif info:
                    miss.add(info[0])
        else:
            rp = pos_of(r.rusher_player_id)
            if rp in ('QB', 'RB'):
                row[1 + (1 if rp == 'QB' else 2)] += num(r.rushing_yards) * .1 + 6 * num(r.rush_touchdown)

    g = {d: {wk: [v[0]] + [round(x, 2) for x in v[1:9]] + v[9:] for wk, v in sorted(w.items(), key=lambda kv: int(kv[0]))}
         for d, w in sorted(games.items())}
    for p in players.values():
        p[5] = round(p[5], 1)
    thru = int(df.week.max()) if len(df) else 0
    payload = {'season': SEASON, 'basis': 'half_ppr', 'thru': thru, 'zones': ZONES,
               'updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
               'g': g, 'p': dict(sorted(players.items()))}
    n_games = sum(len(w) for w in g.values())
    print(f'{len(g)} defenses, {n_games} team-games thru W{thru}, {len(players)} pass catchers ({len(miss)} unmatched)')
    # league per-game average by zone, half-PPR (sanity line)
    avg = [round(sum(v[1 + i] for w in g.values() for v in w.values()) / max(1, n_games), 1) for i in range(8)]
    print('avg/g ' + ' '.join(f'{z} {a}' for z, a in zip(ZONES, avg)))
    if args.dry:
        return
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write('// AUTO-GENERATED by scripts/build_def_zones.py (nflverse pbp) - player-card MATCHUP tab.\n')
        f.write('// g[DEF][wk] = [opp, 8 zone half-PPR pts, 8 zone catches]; p[name] = [team, pos, tgt <10 / 10-19 / 20+ air yds, air yds]\n')
        f.write('window.DEF_ZONES_2026=' + json.dumps(payload, separators=(',', ':')) + ';\n')
    print(f'wrote {OUT} ({os.path.getsize(OUT) // 1024} KB)')


if __name__ == '__main__':
    main()
