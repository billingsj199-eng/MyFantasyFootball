#!/usr/bin/env python3
"""
backtest_dynasty_jm_cond.py — conditional JM credit in the whole Dynasty SIM
pool (Jack 2026-10-09: "wire the conditional version and backtest it").

Rule (dyn_common.jm_cond_weight / JMKernel):
  year 1  rookie prior = (1 - aR) pick comps + aR JM kernel   (TE: only if te)
  year 2  production comps blended with the JM kernel at aS after a slow
          rookie season (rel < 1 or < 4 games), aF after a productive one
  year 3  a3 unless both earlier seasons were slow (pedigree expired -> 0)
  in-season the year-2/3 weight decays by G0 / (G0 + games this season)
JM kernel TIME-HONEST: only seasons before the valuation year are read
(LOCO = leave-one-class-out, future seasons allowed — optimistic bound).

Pool: FFC dynasty ADP pool 2015-23 (1QB PPR), live comps (LL 120/5, QB age 6).
Metrics on years 2018-23 (JM classes start 2017): whole-pool Spearman / top-36
capture for T3, T5+youth (<= 2021), week-8 rest-of-window; the young subset
(JM players in career yrs 1-3); and SIM x market 50/50 rank blend (what FAIR
and SIM GAP use).
"""
import itertools
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import (World, Comps, FORMATS, WEEKS, STAT_KEYS, score_rates, JMKernel,  # noqa: E402
                        load_jm, jm_cond_weight, jm_blend)
from backtest_dynasty_inseason import ffc_adp, evaluate  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

LAST_DATA = 2025
LL = (120, 5.0)
YW = 1.5
WK = 8
EVAL_YEARS = list(range(2018, 2024))


def main():
    w = World(LAST_DATA)
    rows = w.rows(FORMATS['1qb'], 2023)
    comps = Comps(rows, LAST_DATA, {'QB': 6.0})
    repl = w._repl
    jm = load_jm()
    kern = JMKernel(w, jm)
    idx = {(r['key'], r['Y']): r for r in rows}
    pool = []
    for Y in EVAL_YEARS:
        for name, pos, adp in ffc_adp(Y):
            r = idx.get(((name, pos), Y))
            if r:
                pool.append(dict(r, adp=adp))
    frac = (WEEKS - WK) / WEEKS
    for r in pool:
        key, Y, pos = r['key'], r['Y'], r['pos']
        rest = w.rest_pts(key, Y, WK)
        if rest is None:
            rest = w.pts[Y].get(key, 0.0) * frac
        r['t3'] = sum(v or 0 for v in r['vor'][:3])
        r['t5'] = r['t3'] + YW * sum(v or 0 for v in r['vor'][3:5]) if Y + 4 <= LAST_DATA else None
        r['t3w'] = max(0.0, rest - repl[(Y, pos)] * frac) + sum(v or 0 for v in r['vor'][1:3])
        g, tot = w.cur_season(key, Y, WK)
        r['g'] = g
        if r['rookie']:
            r['C'] = comps.ev(pos, True, Comps.feat_rookie(r['pick'], r['age0']), Y, exclude_key=key, local_linear=LL)
            r['Vw'] = None
            if g > 0:
                base = score_rates({k: tot[k] / g for k in STAT_KEYS}, w.sc_for(pos))
                r['Vw'] = comps.ev(pos, False, comps.feat_v(pos, r['age0'], w.rel(base, Y, pos), min(17.0, g * 17.0 / WK)),
                                   Y, exclude_key=key, local_linear=LL)
        else:
            r['V'] = comps.ev(pos, False, comps.feat_v(pos, r['age0'], r['rel'], r['gp1']), Y, exclude_key=key, local_linear=LL)
            b = w.base_at(key, Y, WK, 2.0)
            r['Vw'] = comps.ev(pos, False, comps.feat_v(pos, r['age0'], w.rel(b[0], Y, pos), b[1]), Y,
                               exclude_key=key, local_linear=LL) if b else r['V']
        dr = w.players[key]['draft']
        r['cy'] = (Y - dr[0]) if dr else None
        r['jm'] = jm.get(key)
        r['young'] = r['jm'] is not None and r['cy'] is not None and 0 <= r['cy'] <= 2
        if r['young']:
            ks = range(r['cy'], r['cy'] + 5)
            r['J'] = kern.ev(pos, r['jm'], Y, ks, exclude_key=key)
            r['Jl'] = kern.ev(pos, r['jm'], Y, ks, exclude_key=key, exclude_class=dr[0], honest=False)
    young = [r for r in pool if r['young']]
    print(f'pool {len(pool)} (years {EVAL_YEARS[0]}-{EVAL_YEARS[-1]}); young JM players {len(young)} '
          f'(yr1 {sum(r["cy"] == 0 for r in young)}, yr2 {sum(r["cy"] == 1 for r in young)}, yr3 {sum(r["cy"] == 2 for r in young)})')

    def apply(p, jkey='J'):
        for r in pool:
            if r['rookie']:
                a0 = p['aR'] if r['young'] and (r['pos'] != 'TE' or p['te']) else 0.0
                prior = jm_blend(r['C'], r[jkey], a0) if r['young'] else r['C']
                r['_ev'] = prior
                if r['Vw'] is not None:
                    a = r['g'] / (r['g'] + 2.0)
                    r['_evw'] = [(1 - a) * x + a * y for x, y in zip(prior, r['Vw'])]
                else:
                    r['_evw'] = prior
            else:
                if r['young']:
                    _, a = jm_cond_weight(w, r['key'], r['Y'], p)
                    _, aw = jm_cond_weight(w, r['key'], r['Y'], p, g_cur=r['g'])
                    r['_ev'] = jm_blend(r['V'], r[jkey], a)
                    r['_evw'] = jm_blend(r['Vw'], r[jkey], aw)
                else:
                    r['_ev'], r['_evw'] = r['V'], r['Vw']

    f3 = lambda r: sum(r['_ev'][:3])
    f5 = lambda r: sum(r['_ev'][:3]) + YW * sum(r['_ev'][3:])
    fw = lambda r: r['_evw'][0] * frac + r['_evw'][1] + r['_evw'][2]
    p5 = [r for r in pool if r['t5'] is not None]

    def blend_sp():
        out = []
        for Y in EVAL_YEARS:
            yr = [r for r in pool if r['Y'] == Y]
            sr = {id(r): i for i, r in enumerate(sorted(yr, key=lambda r: -f5(r)))}
            mr = {id(r): i for i, r in enumerate(sorted(yr, key=lambda r: r['adp']))}
            out.append(spearman([-(sr[id(r)] + mr[id(r)]) for r in yr], [r['t3'] for r in yr]))
        return np.mean(out)

    def young_sp(fn, tk):
        out = []
        for Y in EVAL_YEARS:
            yr = [r for r in young if r['Y'] == Y and r[tk] is not None]
            if len(yr) >= 10:
                out.append(spearman([fn(r) for r in yr], [r[tk] for r in yr]))
        return np.mean(out)

    def metrics():
        a = evaluate(pool, f3, lambda r: r['t3']); b = evaluate(p5, f5, lambda r: r['t5'])
        c = evaluate(pool, fw, lambda r: r['t3w'])
        return (a[0], a[1], b[0], c[0], young_sp(f3, 't3'), young_sp(fw, 't3w'), blend_sp(),
                young_sp(f3, 't3') if False else None)

    hdr = f'{"variant":<44}{"T3 Sp":>7}{"top36":>7}{"T5Y":>7}{"W8":>7}{"young T3":>9}{"young W8":>9}{"SIMxMKT":>8}'

    def show(lbl, m):
        print(f'{lbl:<44}{m[0]:>7.3f}{m[1] * 100:>6.1f}%{m[2]:>7.3f}{m[3]:>7.3f}{m[4]:>9.3f}{m[5]:>9.3f}{m[6]:>8.3f}')

    print(hdr)
    base = {'aR': 0.0, 'aS': 0.0, 'aF': 0.0, 'a3': 0.0, 'G0': 8.0, 'te': False}
    apply(base); m0 = metrics(); show('LIVE (no JM)', m0)
    for r in pool:
        r['_mk'] = -r['adp']
    a = evaluate(pool, lambda r: r['_mk'], lambda r: r['t3'])
    print(f'{"MARKET (ADP)":<44}{a[0]:>7.3f}{a[1] * 100:>6.1f}%')
    refs = [('rookie only aR .5', dict(base, aR=0.5)),
            ('flat yr-2 .3 (aS=aF=.3)', dict(base, aS=0.3, aF=0.3)),
            ('flat yr-2 .3 + rookie .5', dict(base, aR=0.5, aS=0.3, aF=0.3))]
    for lbl, p in refs:
        apply(p); show(lbl, metrics())

    print('\n--- grid (time-honest kernel), sorted by mean of T3 / T5Y / W8 / SIMxMKT ---')
    res = []
    for aR, aS, aF, a3, te in itertools.product((0.0, 0.5), (0.3, 0.5, 0.7, 1.0), (0.0, 0.1, 0.2), (0.0, 0.15), (False, True)):
        p = dict(base, aR=aR, aS=aS, aF=aF, a3=a3, te=te)
        apply(p); m = metrics()
        res.append((np.mean([m[0], m[2], m[3], m[6]]), p, m))
    res.sort(key=lambda x: -x[0])
    for s, p, m in res[:12]:
        show(f'aR {p["aR"]} aS {p["aS"]} aF {p["aF"]} a3 {p["a3"]} te {"Y" if p["te"] else "N"}', m)
    print('   ...worst:')
    for s, p, m in res[-3:]:
        show(f'aR {p["aR"]} aS {p["aS"]} aF {p["aF"]} a3 {p["a3"]} te {"Y" if p["te"] else "N"}', m)

    best = res[0][1]
    print(f'\n--- in-season decay G0 for the best ({best}) ---')
    for G0 in (2.0, 4.0, 8.0, 16.0, 1e9):
        apply(dict(best, G0=G0)); show(f'G0 {G0:g}', metrics())

    print('\n--- leakage check: best rule with the LOCO kernel (future seasons allowed) ---')
    apply(best, 'Jl'); show('best, LOCO kernel', metrics())

    print('\n--- per evaluation year, T3 whole-pool Spearman: LIVE vs best ---')
    for Y in EVAL_YEARS:
        yr = [r for r in pool if r['Y'] == Y]
        apply(base); s0 = spearman([f3(r) for r in yr], [r['t3'] for r in yr])
        apply(best); s1 = spearman([f3(r) for r in yr], [r['t3'] for r in yr])
        print(f'   {Y}: {s0:.3f} -> {s1:.3f} ({s1 - s0:+.3f})  n={len(yr)}, young {sum(r["young"] for r in yr)}')

    print('\n--- by career year (young subset, pooled T3 Spearman within year, averaged) ---')
    for cy in (0, 1, 2):
        sub = [r for r in young if r['cy'] == cy]
        for lbl, p in (('LIVE', base), ('best', best)):
            apply(p)
            sps = [spearman([f3(r) for r in sub if r['Y'] == Y], [r['t3'] for r in sub if r['Y'] == Y]) for Y in EVAL_YEARS]
            sps = [s for s in sps if s is not None]
            print(f'   yr{cy + 1} {lbl:<5} {np.mean(sps):.3f}  (n={len(sub)})')


if __name__ == '__main__':
    main()
