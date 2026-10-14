#!/usr/bin/env python3
"""
backtest_dyn_fillin_fold.py — should the IN-SEASON Dynasty SIM down-weight games a player
played as a FILL-IN (a regular ahead of him sat)? (Jack 2026-10-10: "test the in-season
fill-in fold", after research_injury_volume_persist.py found fill-in surges mostly blip.)

Shipped fold (dyn_common.World.base_at, c = 2): the current season's weeks 1..W enter the
50/30/20 production base at weight c x games, every game alike. Variant: the current
season's FILL-IN games count at f x that weight (f = 1 shipped, .75, .5, .25, 0);
non-fill-in games unchanged. Fill-in weeks from research_injury_volume_persist.seasons()
(regulars = same team + pos, higher Clay preseason projection, >= 5 half-PPR — known
before the season).

Pool: vets (not rookies) on the Clay sheet, RB / WR / TE, Y = 2019-2023, valued after
week W = 4 and 8 with the shipped comps (local-linear K120 ridge 5).
Value = y0 x (18 - W)/18 + y1 + y2 (+ 1.5 x (y3 + y4) for the 5-yr read).
Truth T3 = rest-of-Y VOR + Y+1 + Y+2 (1QB PPR), T5 adds 1.5 x (Y+3 + Y+4) where complete.
Scored per year: whole-pool Spearman; the AFFECTED group (1+ fill-in game by week W)
Spearman + mean |log value rank - log truth rank| on the whole-pool ranks.
f chosen leave-one-year-out on the affected group's T3 placement error.
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dyn_common as dc  # noqa: E402
from dyn_common import World, Comps, FORMATS, WEEKS, STAT_KEYS, _norm_name  # noqa: E402
from backtest_js_model import spearman  # noqa: E402
import research_injury_volume_persist as IVP  # noqa: E402

YRS = [2019, 2020, 2021, 2022, 2023]
LL = (120, 5.0)
FS = [1.0, 0.75, 0.5, 0.25, 0.0]
SK = ('RB', 'WR', 'TE')


def base_f(w, key, Y, W, c, fill_wks, f):
    """dc.World.base_at with the current season's fill-in weeks at f x weight."""
    P = w.players[key]
    rl, wgl = [], []
    for back, wt in zip(range(1, 4), dc.W3_WEIGHTS):
        s = P['by'].get(Y - back)
        r = dc.season_rates(s) if s else None
        if r:
            rl.append(r); wgl.append(wt * min(s.get('gp') or 0, 17))
    lst = [(wk, s) for wk, s in w.weekly.get(key, {}).get(Y, []) if wk <= W]
    for grp, wf in ((False, 1.0), (True, f)):
        g = [s for wk, s in lst if (wk in fill_wks) == grp]
        if g and wf > 0:
            rl.append({k: sum(s[k] for s in g) / len(g) for k in STAT_KEYS}); wgl.append(c * wf * len(g))
    if not rl or sum(wgl) <= 0:
        return None
    prev = P['by'].get(Y - 1)
    gp1 = min((prev.get('gp') or 0), 17) if prev else 0
    return dc.score_rates(dc.blend_rates(rl, wgl), w.sc_for(key[1])), gp1


def main():
    S = IVP.seasons()
    fillwk = {}
    for (nn, ps, Y), s in S.items():
        fillwk[((_norm_name(s['name']), ps), Y)] = {wk for wk, _, _, fl in s['g'] if fl}
    w = World(2025)
    rows = w.rows(FORMATS['1qb'], 2025)
    comps = Comps(rows, 2025, {'QB': 6.0})
    repl = w._repl
    idx = {(r['key'], r['Y']): r for r in rows}
    for W in (4, 8):
        frac = (WEEKS - W) / WEEKS
        pool = []
        for (key, Y), r in idx.items():
            if Y not in YRS or key[1] not in SK or r['rookie'] or (key, Y) not in fillwk:
                continue
            fw = {wk for wk in fillwk[(key, Y)] if wk <= W}
            rest = w.rest_pts(key, Y, W)
            if rest is None:
                rest = w.pts[Y].get(key, 0.0) * frac
            vor = r['vor']
            t3 = max(0.0, rest - repl[(Y, key[1])] * frac) + sum(v or 0 for v in vor[1:3])
            t5 = (t3 + 1.5 * sum(v or 0 for v in vor[3:5])) if Y + 4 <= 2025 else None
            val = {}
            for f in (FS if fw else [1.0]):
                b = base_f(w, key, Y, W, 2.0, fw, f)
                if b is None:
                    ev = [0.0] * 5
                else:
                    ev = comps.ev(key[1], False, comps.feat_v(key[1], r['age0'], w.rel(b[0], Y, key[1]), b[1]), Y, exclude_key=key, local_linear=LL)
                val[f] = (ev[0] * frac + ev[1] + ev[2], 1.5 * (ev[3] + ev[4]))
            for f in FS:
                val.setdefault(f, val[1.0])
            pool.append({'key': key, 'Y': Y, 'fw': len(fw), 't3': t3, 't5': t5, 'val': val})
        aff = [p for p in pool if p['fw']]
        print(f'\n================ WEEK {W}: pool {len(pool)} vet RB/WR/TE player-seasons, {len(aff)} with 1+ fill-in game by week {W} ================')
        res = {}
        for f in FS:
            out = {'whole3': [], 'whole5': [], 'aff3': [], 'aff5': [], 'err3': [], 'err5': []}
            for Y in YRS:
                ys = [p for p in pool if p['Y'] == Y]
                for tk, vk in (('3', 0), ('5', 1)):
                    if tk == '5' and any(p['t5'] is None for p in ys):
                        continue
                    v = lambda p: p['val'][f][0] + (p['val'][f][1] if tk == '5' else 0)
                    t = lambda p: p['t' + tk]
                    vr = {id(p): i + 1 for i, p in enumerate(sorted(ys, key=lambda p: -v(p)))}
                    tr = {id(p): i + 1 for i, p in enumerate(sorted(ys, key=lambda p: -t(p)))}
                    out['whole' + tk].append(spearman([v(p) for p in ys], [t(p) for p in ys]))
                    a = [p for p in ys if p['fw']]
                    out['aff' + tk].append(spearman([v(p) for p in a], [t(p) for p in a]))
                    out['err' + tk].append(np.mean([abs(math.log(vr[id(p)]) - math.log(tr[id(p)])) for p in a]))
            res[f] = {k: np.array(x, float) for k, x in out.items()}
        print(f'{"f":<6}{"whole T3":>10}{"whole T5":>10}{"fill-in grp T3":>16}{"T5":>7}{"place err T3":>14}{"T5":>7}')
        for f in FS:
            r = res[f]
            print(f'{f:<6}{r["whole3"].mean():>10.4f}{r["whole5"].mean():>10.4f}{r["aff3"].mean():>16.3f}{r["aff5"].mean():>7.3f}{r["err3"].mean():>14.3f}{r["err5"].mean():>7.3f}')
        for tk in ('3', '5'):
            sc = {f: res[f]['err' + tk] for f in FS}
            d, picks = [], []
            for i in range(len(sc[1.0])):
                fb = min(FS, key=lambda f: np.delete(sc[f], i).mean()); picks.append(fb)
                d.append(sc[1.0][i] - sc[fb][i])
            wh = {f: res[f]['whole' + tk] for f in FS}
            dw = [wh[picks[i]][i] - wh[1.0][i] for i in range(len(picks))]
            print(f'  LOYO T{tk}: picks {picks}  fill-in group placement gain {np.mean(d):+.4f} ({sum(x > 1e-9 for x in d)}/{len(d)})'
                  f'  whole-pool Spearman {np.mean(dw):+.4f} ({sum(x > 1e-9 for x in dw)}/{len(dw)})')
        # biggest fill-in-game counts: value rank shift at f = .5 vs 1
        if W == 8:
            print('\n  most fill-in games by week 8 (value pos-rank at f=1 -> f=.5 -> realized T3 pos rank):')
            for Y in YRS:
                ys = [p for p in pool if p['Y'] == Y]
                for P in SK:
                    g = [p for p in ys if p['key'][1] == P]
                    r1 = {id(p): i + 1 for i, p in enumerate(sorted(g, key=lambda p: -p['val'][1.0][0]))}
                    r5 = {id(p): i + 1 for i, p in enumerate(sorted(g, key=lambda p: -p['val'][0.5][0]))}
                    rt = {id(p): i + 1 for i, p in enumerate(sorted(g, key=lambda p: -p['t3']))}
                    for p in sorted([p for p in g if p['fw'] >= 4], key=lambda p: r1[id(p)])[:3]:
                        print(f'     {Y} {P} {p["key"][0]:<24} fill-in g {p["fw"]}  #{r1[id(p)]} -> #{r5[id(p)]}  realized #{rt[id(p)]}')


if __name__ == '__main__':
    main()
