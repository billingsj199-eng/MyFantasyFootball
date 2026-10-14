#!/usr/bin/env python3
"""
backtest_contender_ros_swap.py — CONTENDER mode: replace the Dynasty SIM's rest-of-season
piece (comps E[VOR] y0 x (18-W)/18) with the WEEKLY sim's own rest-of-season projection,
which knows a backup's starter is out? (Jack 2026-10-10: "how do we value potential short
term assets example rb2 that turns to rb1 for a couple weeks" -> "test the contender ros swap")

Checkpoints W = 4 and 8, seasons 2019-2023, RB / WR / TE vets on the Clay sheet (the
dynasty in-season harness pool, backtest_dyn_fillin_fold.py, shipped fill-in fold .25).
  COMPS y0  = shipped in-season Dynasty SIM rest-of-season piece
  ROS       = weekly shadow rate (backtest_shadow_ros.rate: prior + evidence through his last
              game <= W, no future context) x his team's remaining games; RB backups whose
              team's top-rate RB did not play week W (he did) add P(starter still out at k)
              x ALPHA x starter rate for each remaining week (P = .65 next game, then x.75 per
              week — research_injury_vacancy.py; ALPHA .318 — backtest_option_vor.py). Points are
              half-PPR; the ROS VOR is quantile-mapped onto the comps y0 scale (rank-preserving,
              per position-year) so it can sit in the same sum.
Truths (1QB PPR, World): T0 = realized rest-of-season VOR; CONTENDER3 = 2 x T0 + 1.5 x Y+1 VOR
+ 1 x Y+2 VOR (the contender weights; later years omitted). Per-year Spearman, whole pool and
the RB-backup-with-starter-out group. Blend weight of ROS vs comps chosen leave-one-year-out.
"""
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS, WEEKS, _norm_name  # noqa: E402
from backtest_js_model import spearman  # noqa: E402
import backtest_shadow_next as SN  # noqa: E402
import backtest_shadow_ros as RS  # noqa: E402
import research_injury_volume_persist as IVP  # noqa: E402
from backtest_dyn_fillin_fold import base_f  # noqa: E402

YRS = [2019, 2020, 2021, 2022, 2023]
LL = (120, 5.0)
SK = ('RB', 'WR', 'TE')
ALPHA, P1, PDECAY = 0.318, 0.65, 0.75
BL = [0, 0.25, 0.5, 0.75, 1.0]


def main():
    X = SN.setup()
    R0 = RS.rate(X)
    yr, wk, pos, name, team = X['year'], X['wk'], X['pos'], X['name'], X['team']
    rows = defaultdict(list)            # (key, Y) -> [(wk, i)]
    teamwk = defaultdict(set)
    for i in range(X['n']):
        if int(yr[i]) in YRS and pos[i] in SK:
            rows[((_norm_name(name[i]), pos[i]), int(yr[i]))].append((int(wk[i]), i))
        teamwk[(int(yr[i]), team[i])].add(int(wk[i]))
    S = IVP.seasons()
    fillwk = {((_norm_name(s['name']), ps), Y): {w_ for w_, _, _, fl in s['g'] if fl} for (nn, ps, Y), s in S.items()}
    w = World(2025)
    wr = w.rows(FORMATS['1qb'], 2025)
    comps = Comps(wr, 2025, {'QB': 6.0})
    repl = w._repl
    idx = {(r['key'], r['Y']): r for r in wr}
    for W in (4, 8):
        frac = (WEEKS - W) / WEEKS
        pool = []
        for (key, Y), r in idx.items():
            if Y not in YRS or key[1] not in SK or r['rookie'] or (key, Y) not in fillwk:
                continue
            fw = {x for x in fillwk[(key, Y)] if x <= W}
            b = base_f(w, key, Y, W, 2.0, fw, 0.25)
            ev = [0.0] * 5 if b is None else comps.ev(key[1], False, comps.feat_v(key[1], r['age0'], w.rel(b[0], Y, key[1]), b[1]), Y, exclude_key=key, local_linear=LL)
            rl = sorted(rows.get((key, Y), []))
            past = [i for x, i in rl if x <= W]
            if not past:
                continue
            i0 = past[-1]
            t = team[i0]
            fin = 17 if Y <= 2020 else 18
            futw = sorted(x for x in teamwk[(Y, t)] if W < x < fin)
            rest = w.rest_pts(key, Y, W)
            if rest is None:
                rest = w.pts[Y].get(key, 0.0) * frac
            t0 = max(0.0, rest - repl[(Y, key[1])] * frac)
            v = r['vor']
            pool.append({'key': key, 'Y': Y, 'pos': key[1], 'team': t, 'rate': float(R0[i0]), 'played_W': rl[-1][0] >= W and any(x == W for x, _ in rl),
                         'futw': futw, 'ev': ev, 't0': t0, 'c3': 2 * t0 + 1.5 * (v[1] or 0) + (v[2] or 0),
                         # BALANCED truths (10-10, "test the balanced ros blend"): shipped weights 1/1/1/1.5/1.5
                         'b3': t0 + (v[1] or 0) + (v[2] or 0),
                         'b5': (t0 + (v[1] or 0) + (v[2] or 0) + 1.5 * ((v[3] or 0) + (v[4] or 0))) if Y + 4 <= 2025 else None})
        # starter-out bump for RB backups: team's top-rate RB (among pool RBs with a row by W) missed week W
        byteam = defaultdict(list)
        for p in pool:
            if p['pos'] == 'RB':
                byteam[(p['Y'], p['team'])].append(p)
        nb = 0
        for (Y, t), lst in byteam.items():
            st = max(lst, key=lambda p: p['rate'])
            if st['played_W']:
                continue
            for p in lst:
                if p is st or not p['played_W']:
                    continue
                bump = sum(P1 * PDECAY ** (k - 1) for k in range(1, len(p['futw']) + 1)) * ALPHA * st['rate']
                p['bump'] = bump; nb += 1
        for p in pool:
            p['ros'] = p['rate'] * len(p['futw']) + p.get('bump', 0.0)
        # ROS VOR (half) -> quantile map onto comps y0 scale within position-year
        for Y in YRS:
            for P in SK:
                g = [p for p in pool if p['Y'] == Y and p['pos'] == P]
                if not g:
                    continue
                y0s = sorted(p['ev'][0] * frac for p in g)
                for j, p in enumerate(sorted(g, key=lambda p: p['ros'])):
                    p['rosv'] = y0s[j]
        print(f'\n================ WEEK {W}: {len(pool)} vet RB/WR/TE player-seasons; {nb} RB backups with the starter out at week {W} ================')
        grp = lambda p: 'bump' in p

        def per_year(pred, truth, sel=None):
            v = []
            for Y in YRS:
                g = [p for p in pool if p['Y'] == Y and (sel is None or sel(p))]
                if len(g) >= 5:
                    s = spearman([pred(p) for p in g], [truth(p) for p in g])
                    if s is not None:
                        v.append(s)
            return np.array(v)
        comps0 = lambda p: p['ev'][0] * frac
        print('rest-of-season VOR (T0):  comps y0 {:.3f} | weekly ROS {:.3f} | RB backups w/ starter out: comps {:.3f} ROS {:.3f}'.format(
            per_year(comps0, lambda p: p['t0']).mean(), per_year(lambda p: p['ros'], lambda p: p['t0']).mean(),
            np.nanmean([spearman([comps0(p) for p in pool if grp(p)], [p['t0'] for p in pool if grp(p)])]) if nb >= 6 else float('nan'),
            np.nanmean([spearman([p['ros'] for p in pool if grp(p)], [p['t0'] for p in pool if grp(p)])]) if nb >= 6 else float('nan')))
        res = {}
        for bw in BL:
            cont = lambda p, bw=bw: 2 * ((1 - bw) * p['ev'][0] * frac + bw * p['rosv']) + 1.5 * p['ev'][1] + p['ev'][2]
            res[bw] = (per_year(cont, lambda p: p['c3']), per_year(lambda p, bw=bw: (1 - bw) * comps0(p) + bw * p['rosv'], lambda p: p['t0']))
        print(f'{"ROS share":<10}{"CONTENDER3 Sp":>15}{"T0 Sp":>9}')
        for bw in BL:
            print(f'{bw:<10}{res[bw][0].mean():>15.4f}{res[bw][1].mean():>9.4f}')
        for j, lbl in ((0, 'CONTENDER3'), (1, 'T0')):
            d, picks = [], []
            for i in range(len(res[0][j])):
                bb = max(BL, key=lambda b: np.delete(res[b][j], i).mean()); picks.append(bb); d.append(res[bb][j][i] - res[0][j][i])
            print(f'  LOYO {lbl}: picks {picks} held-out gain {np.mean(d):+.4f} ({sum(x > 1e-9 for x in d)}/{len(d)})')
        # BALANCED blend: value = y0' + y1 + y2 + 1.5 (y3 + y4), y0' = (1 - s) comps y0 + s ROS
        bal = {}
        for bw in BL:
            val = lambda p, bw=bw: ((1 - bw) * p['ev'][0] * frac + bw * p['rosv']) + p['ev'][1] + p['ev'][2] + 1.5 * (p['ev'][3] + p['ev'][4])
            bal[bw] = {'b3': per_year(val, lambda p: p['b3']),
                       'b5': np.array([s for s in (spearman([val(p) for p in pool if p['Y'] == Y], [p['b5'] for p in pool if p['Y'] == Y])
                                                   for Y in YRS if all(p['b5'] is not None for p in pool if p['Y'] == Y)) if s is not None])}
        print(f'BALANCED  {"ROS share":<10}{"3yr Sp":>9}{"5yr+y Sp":>10}')
        for bw in BL:
            print(f'          {bw:<10}{bal[bw]["b3"].mean():>9.4f}{bal[bw]["b5"].mean():>10.4f}')
        for tk in ('b3', 'b5'):
            d, picks = [], []
            for i in range(len(bal[0][tk])):
                bb = max(BL, key=lambda b: np.delete(bal[b][tk], i).mean()); picks.append(bb); d.append(bal[bb][tk][i] - bal[0][tk][i])
            print(f'  BALANCED LOYO {tk}: picks {picks} held-out gain {np.mean(d):+.4f} ({sum(x > 1e-9 for x in d)}/{len(d)})')
        b = [p for p in pool if grp(p)]
        if b:
            print('  RB backups with the starter out (contender rank in pool at ROS share 0 -> 1, realized CONTENDER3 rank):')
            for Y in YRS:
                g = [p for p in pool if p['Y'] == Y]
                for bw in (0, 1):
                    cont = lambda p, bw=bw: 2 * ((1 - bw) * p['ev'][0] * frac + bw * p['rosv']) + 1.5 * p['ev'][1] + p['ev'][2]
                    for k_, p in enumerate(sorted(g, key=lambda p: -cont(p))):
                        p['_r%d' % bw] = k_ + 1
                for k_, p in enumerate(sorted(g, key=lambda p: -p['c3'])):
                    p['_rt'] = k_ + 1
                for p in sorted([p for p in g if grp(p)], key=lambda p: p['_r0'])[:4]:
                    print(f'     {Y} {p["key"][0]:<22} #{p["_r0"]:<4} -> #{p["_r1"]:<4} realized #{p["_rt"]}')


if __name__ == '__main__':
    main()
