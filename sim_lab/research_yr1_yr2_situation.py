#!/usr/bin/env python3
"""
research_yr1_yr2_situation.py — what changed between year 1 and year 2 for the
rookies who improved? (Jack 2026-10-09: "did they improve around them or was
it a change in volume, coaching staff etc" + "is it different for rookies that
played well at the end of the previous season")

Cohort: drafted QB/RB/WR/TE, rookie seasons 2019-24 (year 2 <= 2025), JM score.
Season production rel = PPR points per game vs the year's replacement starter
per game (dyn_common.season_rel). SLOW = rel < 1 or < 4 games. IMPROVED =
year-2 rel >= 1 with 4+ games.

Situation per player-season (ctx_features.parquet — season-to-date values at
his last game row; 2019-25 projection pool): snap %, target / carry share,
xFP per game (opportunity), points over xFP per game (efficiency), team
implied total (offense quality), PROE; year-2 rows: new head coach, new
playcaller, team change. Derived: offseason VACATED same-position target /
carry share (teammates on his team in year 1 who are not in year 2) and QB
change (team's top dropback QB differs).
LATE = rookie-season weeks 10+ (rel over those games, 3+ games) vs weeks 1-9.

A  Slow rookies: improved vs not — what moved (volume vs efficiency) and how
   often each situation change was present.
B  Pre-season-knowable signals among slow rookies: improvement rate with /
   without each (new playcaller, vacated share, QB change, team change, late
   surge, JM band).
C  Late-season form, all rookies: does weeks 10+ predict year 2 beyond the
   full season? partial correlation + the sim's miss by late-form group.
"""
import math
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS, load_jm, season_rel, score_rates, _norm_name  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

LAST_DATA = 2025
LL = (120, 5.0)
ROOKIE_YEARS = range(2019, 2025)


def main():
    w = World(LAST_DATA)
    rows = w.rows(FORMATS['1qb'], LAST_DATA)
    comps = Comps(rows, LAST_DATA, {'QB': 6.0})
    idx = {(r['key'], r['Y']): r for r in rows}
    jm = load_jm()
    ctx = pd.read_parquet(os.path.join(HERE, 'ctx_features.parquet'))
    ctx['key'] = [(_norm_name(n), p) for n, p in zip(ctx['name'], ctx['pos'])]
    ctx = ctx.sort_values(['year', 'wk'])
    LAST = {}
    for r in ctx.groupby(['name', 'pos', 'year']).tail(1).to_dict('records'):
        LAST[(r['key'], r['year'])] = r
    MEANS, FLAGS = defaultdict(list), {}
    for r in ctx.to_dict('records'):
        kk = (r['key'], r['year'])
        MEANS[kk].append(r['implied'])
        f = FLAGS.setdefault(kk, {'new_hc': 0.0, 'new_pc': 0.0, 'team_change': 0.0})
        for c in f:
            v = r[c]
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                f[c] = max(f[c], float(v))
    team_of = {kk: r['team'] for kk, r in LAST.items()}
    room = defaultdict(list)
    for (k, y), r in LAST.items():
        room[(r['team'], y)].append((k, r['tgt_sh'] or 0, r['car_sh'] or 0, k[1]))
    qb_top = {}
    for (t, y), lst in room.items():
        qs = [((LAST[(k, y)]['db_sh'] or 0) * (LAST[(k, y)]['g'] or 0), k) for k, _, _, p in lst if p == 'QB']
        if qs:
            qb_top[(t, y)] = max(qs)[1]

    def vacated(key, y1, pos):
        t1, t2 = team_of.get((key, y1)), team_of.get((key, y1 + 1))
        if not t1 or not t2:
            return None, None
        here2 = {k for k, *_ in room.get((t2, y1 + 1), [])}
        vt = vc = 0.0
        for k, ts, cs, p in room.get((t2, y1), []):   # his year-2 team's year-1 room
            if k != key and k not in here2 and p == pos:
                vt += ts; vc += cs
        return vt, vc

    def late_rel(key, Y):
        wk = w.weekly.get(key, {}).get(Y) or []
        sc = w.sc_for(key[1])
        lt = [score_rates(s, sc) for wn, s in wk if wn >= 10]
        er = [score_rates(s, sc) for wn, s in wk if wn < 10]
        rp = max(w._repl[(Y, key[1])] / 17.0, 1.0)
        return (np.mean(lt) / rp if len(lt) >= 3 else None), (np.mean(er) / rp if len(er) >= 3 else None), len(lt)

    P = []
    for key, dr in w.draft.items():
        Y = dr[0]
        if Y not in ROOKIE_YEARS or key not in jm:
            continue
        g1, r1 = season_rel(w, key, Y)
        g2, r2 = season_rel(w, key, Y + 1)
        lr, er, gl = late_rel(key, Y)
        x = {'key': key, 'Y': Y, 'pos': key[1], 'pick': dr[1], 'jm': jm[key], 'g1': g1, 'r1': r1, 'g2': g2, 'r2': r2,
             'late': lr, 'early': er, 'gl': gl, 'slow': g1 < 4 or r1 < 1.0, 'imp': g2 >= 4 and r2 >= 1.0}
        for yy, tag in ((Y, '1'), (Y + 1, '2')):
            if (key, yy) in LAST:
                L = LAST[(key, yy)]
                x.update({'snap' + tag: L['snap_std'], 'tgt' + tag: L['tgt_sh'], 'car' + tag: L['car_sh'],
                          'xfp' + tag: L['xfp_pg'], 'eff' + tag: L['pts_over_xfp'], 'ppg' + tag: L['ppg'],
                          'imp_tot' + tag: float(np.nanmean(MEANS[(key, yy)])), 'team' + tag: L['team']})
        if (key, Y + 1) in FLAGS:
            F = FLAGS[(key, Y + 1)]
            x.update({'new_hc': F['new_hc'], 'new_pc': F['new_pc'], 'team_change': F['team_change']})
        vt, vc = vacated(key, Y, key[1])
        x['vac'] = None if vt is None else (vt if key[1] in ('WR', 'TE') else vc if key[1] == 'RB' else None)
        t1, t2 = x.get('team1'), x.get('team2')
        if key[1] != 'QB' and t1 and t2:
            x['qb_change'] = float(qb_top.get((t1, Y)) != qb_top.get((t2, Y + 1)))
        # sim's production-only read entering year 2 (rookie season = base) vs year-2 VOR
        r_ = idx.get((key, Y + 1))
        if r_:
            ev = comps.ev(key[1], False, comps.feat_v(key[1], r_['age0'], r_['rel'], r_['gp1']), Y + 1, exclude_key=key, local_linear=LL)
            x['sim2'] = ev[0]; x['vor2'] = w.vor(key, Y + 1) or 0.0
        P.append(x)
    print(f'cohort {len(P)} rookies {ROOKIE_YEARS[0]}-{ROOKIE_YEARS[-1]}; with ctx yr1+yr2 rows: '
          f'{sum(1 for p in P if "snap1" in p and "snap2" in p)}')

    def m(lst, f):
        v = [f(p) for p in lst]
        v = [x for x in v if x is not None and not (isinstance(x, float) and math.isnan(x))]
        return (np.mean(v), len(v)) if v else (float('nan'), 0)

    slow = [p for p in P if p['slow']]
    print(f'\n=== A. SLOW rookies: improved in year 2 vs not (n slow {len(slow)}, improved {sum(p["imp"] for p in slow)}) ===')
    both = lambda p, a: (p[a + '2'] - p[a + '1']) if (a + '1' in p and a + '2' in p and p[a + '1'] is not None and p[a + '2'] is not None) else None
    feats = [('snap % change', lambda p: both(p, 'snap')), ('target share change', lambda p: both(p, 'tgt') if p['pos'] in ('WR', 'TE', 'RB') else None),
             ('carry share change (RB)', lambda p: both(p, 'car') if p['pos'] == 'RB' else None),
             ('xFP/g change (volume)', lambda p: both(p, 'xfp')), ('pts over xFP/g change (eff.)', lambda p: both(p, 'eff')),
             ('PPG change', lambda p: both(p, 'ppg')), ('team implied total change', lambda p: both(p, 'imp_tot')),
             ('new head coach', lambda p: p.get('new_hc')), ('new playcaller', lambda p: p.get('new_pc')),
             ('changed teams', lambda p: p.get('team_change')), ('QB change (non-QB)', lambda p: p.get('qb_change')),
             ('vacated same-pos share', lambda p: p.get('vac')),
             ('late rel (wk 10+) yr 1', lambda p: p['late']), ('full rel yr 1', lambda p: p['r1']), ('JM', lambda p: p['jm'])]
    print(f'{"":<32}{"improved":>12}{"stayed":>12}')
    for lbl, f in feats:
        a, na = m([p for p in slow if p['imp']], f); b, nb = m([p for p in slow if not p['imp']], f)
        print(f'{lbl:<32}{a:>9.3f} ({na:>2}){b:>9.3f} ({nb:>3})')
    imp = [p for p in slow if p['imp'] and both(p, 'xfp') is not None and both(p, 'eff') is not None]
    if imp:
        dv = np.mean([both(p, 'xfp') for p in imp]); de = np.mean([both(p, 'eff') for p in imp])
        print(f'   improvers: PPG gain split  volume (xFP) {dv:+.2f} / efficiency {de:+.2f}  -> {dv / (dv + de):.0%} volume')
        for pos in ('QB', 'RB', 'WR', 'TE'):
            ip = [p for p in imp if p['pos'] == pos]
            if len(ip) >= 3:
                dv = np.mean([both(p, 'xfp') for p in ip]); de = np.mean([both(p, 'eff') for p in ip])
                print(f'      {pos} (n={len(ip)}): volume {dv:+.2f}, efficiency {de:+.2f}')

    print('\n=== B. SLOW rookies — year-2 improvement rate with / without a pre-season-knowable signal ===')
    sigs = [('new playcaller', lambda p: p.get('new_pc')), ('new head coach', lambda p: p.get('new_hc')),
            ('changed teams', lambda p: p.get('team_change')), ('QB change (non-QB)', lambda p: p.get('qb_change')),
            ('vacated same-pos share >= .15', lambda p: None if p.get('vac') is None else float(p['vac'] >= 0.15)),
            ('late surge: wk 10+ rel >= 1', lambda p: None if p['late'] is None else float(p['late'] >= 1.0)),
            ('late rel > early rel by .3+', lambda p: None if p['late'] is None or p['early'] is None else float(p['late'] - p['early'] >= 0.3)),
            ('JM 70+', lambda p: float(p['jm'] >= 70)), ('top-64 pick', lambda p: float(p['pick'] <= 64))]
    print(f'{"signal":<32}{"with":>16}{"without":>16}')
    for lbl, f in sigs:
        yes = [p for p in slow if f(p) == 1.0]; no = [p for p in slow if f(p) == 0.0]
        rate = lambda l: (np.mean([p['imp'] for p in l]) if l else float('nan'))
        print(f'{lbl:<32}{rate(yes):>9.0%} ({len(yes):>3}){rate(no):>9.0%} ({len(no):>3})')
    print('   within JM 70+ / top-64 slow rookies (the pedigree group):')
    ped = [p for p in slow if p['jm'] >= 70 or p['pick'] <= 64]
    for lbl, f in sigs[:7]:
        yes = [p for p in ped if f(p) == 1.0]; no = [p for p in ped if f(p) == 0.0]
        rate = lambda l: (np.mean([p['imp'] for p in l]) if l else float('nan'))
        print(f'   {lbl:<29}{rate(yes):>9.0%} ({len(yes):>3}){rate(no):>9.0%} ({len(no):>3})')

    print('\n=== C. LATE-SEASON FORM (all rookies with 3+ games in weeks 10+) ===')
    L = [p for p in P if p['late'] is not None and p['g2'] >= 4]
    r1 = np.array([p['r1'] for p in L]); lt = np.array([p['late'] for p in L]); y2 = np.array([p['r2'] for p in L])
    print(f'   n={len(L)}  Spearman yr-2 rel with: full yr-1 rel {spearman(list(r1), list(y2)):+.3f}, late rel {spearman(list(lt), list(y2)):+.3f}, '
          f'early rel {spearman([p["early"] or 0 for p in L], list(y2)):+.3f}')
    X = np.column_stack([np.ones(len(L)), np.log(np.maximum(r1, .05)), np.log(np.maximum(lt, .05))])
    b = np.linalg.lstsq(X, np.log(np.maximum(y2, .05)), rcond=None)[0]
    print(f'   log yr-2 rel ~ {b[1]:+.2f} log full + {b[2]:+.2f} log late   (late weight share {b[2] / (b[1] + b[2]):.0%}; '
          f'the sim weights every rookie game equally)')
    for lbl, sub in (('late >= early + .3 (surged)', lambda p: p['early'] is not None and p['late'] - p['early'] >= 0.3),
                     ('flat (+/- .3)', lambda p: p['early'] is not None and abs(p['late'] - p['early']) < 0.3),
                     ('late <= early - .3 (faded)', lambda p: p['early'] is not None and p['late'] - p['early'] <= -0.3)):
        g = [p for p in L if sub(p)]
        s = [p for p in g if 'sim2' in p]
        print(f'   {lbl:<30} n={len(g):>3}  yr-1 rel {np.mean([p["r1"] for p in g]):.2f}  yr-2 rel {np.mean([p["r2"] for p in g]):.2f}'
              f'  improved/held {np.mean([p["r2"] >= 1 for p in g]):.0%}  sim yr-2 VOR {np.mean([p["sim2"] for p in s]):5.1f} vs actual {np.mean([p["vor2"] for p in s]):5.1f}')
    print('   slow full season but late surge (late rel >= 1):')
    g = [p for p in L if p['slow'] and p['late'] >= 1.0]
    for p in sorted(g, key=lambda p: -p['r2'])[:14]:
        print(f'      {p["key"][0]:<24}{p["pos"]:<3}{p["Y"]} JM {p["jm"]:>5.1f}  full {p["r1"]:.2f} late {p["late"]:.2f} ({p["gl"]}g) -> yr2 {p["r2"]:.2f}')
    if g:
        print(f'      improved in yr 2: {np.mean([p["imp"] for p in g]):.0%} of {len(g)} vs slow without a late surge '
              f'{np.mean([p["imp"] for p in L if p["slow"] and p["late"] < 1.0]):.0%}')


if __name__ == '__main__':
    main()
