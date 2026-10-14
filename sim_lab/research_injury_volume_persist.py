#!/usr/bin/env python3
"""
research_injury_volume_persist.py — when a player's volume jumps because the starter
ahead of him got hurt, does it change his career or is it a blip? (Jack 2026-10-10:
"see how improved volume because injury ahead of them changes their future career or
was just a blip")

Seasons Y = 2019-2023 (outcomes through 2025), RB / WR / TE.
FILL-IN GAMES: games he played while a REGULAR ahead of him sat — same team + position,
higher Clay preseason projection per game and >= 5.0 half-PPR (the promoted-backup /
fill-in study definition, research_promoted_backup.absences, copied here so importing
that script doesn't truncate its log).
SURGE SEASON: PPR per game >= 1.3 x his Clay preseason projection and >= 8 PPR/g, 6+ games.
  INJURY-DRIVEN surge: >= 3 fill-in games and >= 60% of his points above projection came
                       in fill-in games
  ORGANIC surge:       < 25% of the surplus in fill-in games (or none)
Outcomes: next season PPR/g vs the surge season (all games / healthy-regular games / fill-in
games), next-season Clay projection (what the market's projector believed), realized VOR
rank Y+1..Y+2 vs the Dynasty SIM's preseason rank for Y+1 (comps on the 50/30/20 base —
does the sim over-credit fill-in production?), and FFC dynasty ADP rank residual where drafted.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_sim_calibration as cal  # noqa: E402
from dyn_common import World, Comps, FORMATS, _norm_name  # noqa: E402
from backtest_dynasty_inseason import ffc_adp  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

SK = ('RB', 'WR', 'TE')
REG_MIN = 5.0
YRS = [2019, 2020, 2021, 2022, 2023]
LL = (120, 5.0)


def week_team(Y, w, opp):
    o = cal.OPP_ALIAS.get(opp, opp)
    for t, s in cal.SCHEDULES.get(Y, {}).items():
        if s.get(str(w)) == o:
            return t
    return None


def seasons():
    """{(norm, pos, Y): dict(team, cpg, games=[(wk, ppr, opp_n, fillin)])} — PPR from half-PPR fpts + rec/2."""
    ch = json.load(open(os.path.join(cal.REPO, 'data', 'clay_history.json'), encoding='utf-8'))
    tcache, roster, games = {}, defaultdict(list), {}
    for Y in range(min(YRS), max(YRS) + 3):
        if str(Y) not in ch:
            continue
        W = 16 if Y <= 2020 else 17
        for nm, c in ch[str(Y)].items():
            ps = c.get('pos')
            if ps not in SK:
                continue
            rec = cal.weekly_rec(nm, ps)
            if rec is None:
                continue
            team = cal.infer_team(rec, Y)
            gmv = c.get('gm') or 0
            half = max(0.2, (c.get('pts') or 0) - (c.get('rec') or 0) / 2.0)
            cpg = half / gmv if gmv >= 4 else half / W
            cppr = (half + (c.get('rec') or 0) / 2.0) / (gmv if gmv >= 4 else W)
            gl = {}
            for wrow in rec.get('seasons', {}).get(str(Y), []):
                if cal.played(wrow) and wrow.get('opp'):
                    k = (Y, int(wrow['wk']), wrow['opp'])
                    if k not in tcache:
                        tcache[k] = week_team(Y, int(wrow['wk']), wrow['opp'])
                    ppr = (wrow.get('fpts') or 0) + 0.5 * (wrow.get('rec') or 0)
                    opp_n = (wrow.get('tgt') or 0) + (wrow.get('ra') or 0)
                    gl[int(wrow['wk'])] = (tcache[k], ppr, opp_n)
            games[(nm, ps, Y)] = (team, cpg, cppr, gl)
            if team:
                roster[(Y, team, ps)].append((nm, cpg))
    out = {}
    for (nm, ps, Y), (team, cpg, cppr, gl) in games.items():
        if not team:
            continue
        regs = [r for r, rc in roster[(Y, team, ps)] if r != nm and rc > cpg and rc >= REG_MIN]
        rplay = {r: {w for w, v in games[(r, ps, Y)][3].items() if v[0] == team} for r in regs}
        g = []
        for wk, (t, ppr, opp_n) in sorted(gl.items()):
            if t != team:
                continue
            g.append((wk, ppr, opp_n, any(wk not in rplay[r] for r in regs)))
        out[(cal.norm(nm), ps, Y)] = {'name': nm, 'team': team, 'cpg': cpg, 'cppr': cppr, 'g': g, 'nregs': len(regs)}
    return out


def main():
    S = seasons()
    w = World(2025)
    rows = w.rows(FORMATS['1qb'], 2025)
    comps = Comps(rows, 2025, {'QB': 6.0})
    idx = {(r['key'], r['Y']): r for r in rows}
    # Dynasty SIM preseason value per (key, Y) for skill positions, and realized 2-yr VOR
    simv, real = {}, {}
    for (key, Y), r in idx.items():
        if Y not in [y + 1 for y in YRS] or key[1] not in SK:
            continue
        if r['rookie']:
            ev = comps.ev(key[1], True, Comps.feat_rookie(r['pick'], r['age0']), Y, exclude_key=key, local_linear=LL)
        else:
            ev = comps.ev(key[1], False, comps.feat_v(key[1], r['age0'], r['rel'], r['gp1']), Y, exclude_key=key, local_linear=LL)
        simv[(key, Y)] = ev[0] + ev[1]
        real[(key, Y)] = sum(v or 0 for v in r['vor'][:2])
    # position ranks within year
    simrk, realrk = {}, {}
    for Y in set(y for _, y in simv):
        for P in SK:
            ks = [k for k in simv if k[1] == Y and k[0][1] == P]
            for i, k in enumerate(sorted(ks, key=lambda k: -simv[k])):
                simrk[k] = i + 1
            for i, k in enumerate(sorted(ks, key=lambda k: -real[k])):
                realrk[k] = i + 1
    ffc = {}
    for Y in [y + 1 for y in YRS]:
        lst = ffc_adp(Y)
        for P in SK:
            for i, (n, p, a) in enumerate(sorted([x for x in lst if x[1] == P], key=lambda x: x[2])):
                ffc[((n, p), Y)] = i + 1

    recs = []
    for (nn, ps, Y), s in S.items():
        if Y not in YRS or len(s['g']) < 6:
            continue
        g = s['g']
        ppg = np.mean([x[1] for x in g])
        if not (ppg >= 8 and ppg >= 1.3 * s['cppr']):
            continue
        surplus = [x[1] - s['cppr'] for x in g]
        tot = sum(v for v in surplus if v > 0) or 1e-9
        fill = sum(v for v, x in zip(surplus, g) if x[3] and v > 0) / tot
        gF = sum(1 for x in g if x[3])
        typ = 'INJURY' if (gF >= 3 and fill >= 0.6) else 'ORGANIC' if fill < 0.25 else 'MIXED'
        nxt = S.get((nn, ps, Y + 1))
        key = (_norm_name(s['name']), ps)
        rec = {'name': s['name'], 'pos': ps, 'Y': Y, 'typ': typ, 'gF': gF, 'gN': len(g) - gF, 'fill': fill,
               'cppr': s['cppr'], 'ppg': ppg,
               'ppg_F': np.mean([x[1] for x in g if x[3]]) if gF else np.nan,
               'ppg_N': np.mean([x[1] for x in g if not x[3]]) if len(g) > gF else np.nan,
               'opp_F': np.mean([x[2] for x in g if x[3]]) if gF else np.nan,
               'opp_N': np.mean([x[2] for x in g if not x[3]]) if len(g) > gF else np.nan,
               'n_ppg': np.mean([x[1] for x in nxt['g']]) if nxt and len(nxt['g']) >= 4 else np.nan,
               'n_opp': np.mean([x[2] for x in nxt['g']]) if nxt and len(nxt['g']) >= 4 else np.nan,
               'n_cppr': nxt['cppr'] if nxt else np.nan, 'n_g': len(nxt['g']) if nxt else 0,
               'n_fillg': sum(1 for x in nxt['g'] if x[3]) if nxt else 0,
               'simrk': simrk.get((key, Y + 1)), 'realrk': realrk.get((key, Y + 1)), 'ffc': ffc.get((key, Y + 1))}
        recs.append(rec)
    print(f'surge seasons (PPR/g >= 8 and >= 1.3x Clay projection, 6+ games), 2019-23: {len(recs)}')
    for t in ('INJURY', 'MIXED', 'ORGANIC'):
        g = [r for r in recs if r['typ'] == t]
        print(f'  {t:<8} {len(g):>3}  ' + ' '.join(f'{P} {sum(1 for r in g if r["pos"] == P)}' for P in SK))

    def m(g, k):
        v = [r[k] for r in g if r[k] == r[k] and r[k] is not None]
        return (np.mean(v), len(v)) if v else (float('nan'), 0)

    print('\n=== does it last? (means; next season = 4+ games) ===')
    print(f'{"group":<16}{"n":>4}{"proj Y":>8}{"PPR/g Y":>9}{"  w/ reg":>9}{"  fill-in":>9}{"next PPR/g":>12}{"keep %":>8}{"next proj":>11}{"opp/g Y fill":>14}{"healthy":>9}{"next":>7}')
    for P in ('ALL',) + SK:
        for t in ('INJURY', 'ORGANIC'):
            g = [r for r in recs if r['typ'] == t and (P == 'ALL' or r['pos'] == P)]
            if len(g) < 5:
                continue
            gn = [r for r in g if r['n_ppg'] == r['n_ppg']]
            keep = np.mean([r['n_ppg'] / r['ppg'] for r in gn]) if gn else float('nan')
            print(f'{P + " " + t:<16}{len(g):>4}{m(g, "cppr")[0]:>8.1f}{m(g, "ppg")[0]:>9.1f}{m(g, "ppg_N")[0]:>9.1f}{m(g, "ppg_F")[0]:>9.1f}'
                  f'{m(g, "n_ppg")[0]:>12.1f}{keep * 100:>7.0f}%{m(g, "n_cppr")[0]:>11.1f}{m(g, "opp_F")[0]:>14.1f}{m(g, "opp_N")[0]:>9.1f}{m(g, "n_opp")[0]:>7.1f}')
    print('   proj = Clay preseason PPR/g; w/ reg = his games with every regular ahead active; keep % = next PPR/g / surge PPR/g;'
          ' opp = targets + carries per game')
    inj = [r for r in recs if r['typ'] == 'INJURY' and r['n_ppg'] == r['n_ppg']]
    if len(inj) >= 8:
        print('\nINJURY-driven: which surge-year split predicts next season? Spearman with next PPR/g')
        for k in ('ppg', 'ppg_F', 'ppg_N', 'cppr', 'n_cppr'):
            g = [r for r in inj if r[k] == r[k]]
            print(f'  {k:<7} {spearman([r[k] for r in g], [r["n_ppg"] for r in g]):+.3f}  (n {len(g)})')
        g = [r for r in inj if r['n_g'] >= 4]
        print(f'  next season: avg {np.mean([r["n_fillg"] for r in g]):.1f} of {np.mean([r["n_g"] for r in g]):.1f} games again as a fill-in')

    print('\n=== does the Dynasty SIM / market over-credit it? log(realized 2-yr VOR pos rank / predicted pos rank), + = finished WORSE than predicted ===')
    for t in ('INJURY', 'MIXED', 'ORGANIC'):
        g = [r for r in recs if r['typ'] == t and r['simrk'] and r['realrk']]
        gm = [r for r in g if r['ffc']]
        rs = [math.log(r['realrk'] / r['simrk']) for r in g]
        rm = [math.log(r['realrk'] / r['ffc']) for r in gm]
        print(f'  {t:<8} SIM: {np.mean(rs):+.2f} (n {len(rs)})   FFC market: {np.mean(rm) if rm else float("nan"):+.2f} (n {len(rm)})')
    print('\nINJURY-driven surges (name, year, games as fill-in, PPR/g w/ regular -> fill-in -> next season):')
    for r in sorted([r for r in recs if r['typ'] == 'INJURY'], key=lambda r: (r['pos'], r['Y'])):
        print(f'   {r["pos"]} {r["Y"]} {r["name"]:<24} fill-in {r["gF"]:>2}/{r["gF"] + r["gN"]:<2} '
              f'{r["ppg_N"]:>5.1f} -> {r["ppg_F"]:>5.1f} | next {r["n_ppg"]:>5.1f} ({r["n_g"]} g, {r["n_fillg"]} fill-in)  proj {r["cppr"]:.1f} -> {r["n_cppr"]:.1f}')


if __name__ == '__main__':
    main()
