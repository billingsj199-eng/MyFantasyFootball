#!/usr/bin/env python3
"""
build_dynasty_sim.py — 2026 Dynasty SIM values for the site (PROTOTYPE).

Comparables model shared with the backtests (dyn_common.py):
    SIM DYN = WIN3 + YOUTH_W * YOUTH
    WIN3  = E[VOR] rest of 2026 (x (18-W)/18) + 2027 + 2028
    YOUTH = E[VOR] 2029 + 2030
In-season fold (backtest_dynasty_inseason.py, Jack 2026-10-09 — W4 / W8
whole-pool Spearman .466/.453 -> .553/.572):
  vets    — 2026 weeks 1..W enter the 50/30/20 x games core at C_CUR x games
  rookies — draft-slot comps blended with vet-style comps from their own
            2026 rate, weight g / (g + R_ROOKIE)
W = completed 2026 weeks (auto: weeks with >= 60% of week 1's player count).
PPR / Half / STD x 1QB (QB12/RB30/WR42/TE12) and SF (QB24/...).

Output: <site>/data/dynasty_sim_2026.js  (window.DYNASTY_SIM_2026 = {...})
Usage: python build_dynasty_sim.py [--out PATH] [--week W]
"""
import argparse
import collections
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS, WEEKS, STAT_KEYS, score_rates, DATA_DIR  # noqa: E402
import dyn_picks  # noqa: E402

Y_NOW = 2026
LAST_DATA = 2025
K = 30
YOUTH_W = 1.5
C_CUR = 2.0
R_ROOKIE = 2.0
UDFA_PICK = 262
# Local-linear comps (backtest_dynasty_ll.py, TE fix 2026-10-09): elite TE
# calibration 1.24x -> 1.03x, TEs in top 36 1.3 -> 2.0/yr, whole-pool W4 .553 -> .580.
LL = (120, 5.0)
# Rookie picks: weight on the JM read of the 2027 class vs the historical slot
# baseline. Past classes' JM strength barely tracked what they produced
# (2021 read strongest, under-delivered; 2023 read weak, one of the best), and
# 2027's numbers are mid-season and pre-declaration — so a light nudge.
W_CLASS = 0.25
# QB age scale 6 (backtest_dynasty_qb.py, 1QB QB placement 2026-10-09)
AGE_SCALE = {'QB': 6.0}
# Low-sample guard (query only): a vet whose production level rests on fewer
# than LOW_G games has his production-vs-replacement pulled toward 0.8 with
# weight LOW_G0 / (games + LOW_G0). Not a backtested layer — a global shrink
# was neutral-to-worse (backtest_dynasty_shrink.py) and the market pool has
# only 12 such vets — it stops a 3-game sample (Keenum, 38) reading as elite.
LOW_G, LOW_G0, LOW_TO = 8, 6.0, 0.8


def completed_weeks(w):
    cnt = collections.Counter(wk for yrs in w.weekly.values() for wk, _ in yrs.get(Y_NOW, []))
    if not cnt:
        return 0
    base = cnt.get(1, 0)
    W = 0
    for wk in sorted(cnt):
        if cnt[wk] >= 0.6 * base:
            W = wk
        else:
            break
    return W


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(DATA_DIR, 'dynasty_sim_2026.js'))
    ap.add_argument('--week', type=int, default=None)
    args = ap.parse_args()

    SCORINGS = {'ppr': 'full_ppr', 'half': 'half_ppr', 'std': 'non_ppr'}
    w = World(LAST_DATA)
    W = args.week if args.week is not None else completed_weeks(w)
    frac = (WEEKS - W) / WEEKS
    print(f'2026 valuation after week {W} (year-0 share {frac:.2f})')

    # Compact layout (lazy-loaded by the site): per player
    #   v[<fmt>_<scoring>] = [val, win3, youth, rank, y0..y4]  (ints; y0 = rest of 2026)
    #   c = closest comps for the 1QB PPR year-0 read: [[name, season, VOR], ...]
    out = {'meta': {'built': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), 'valuationYear': Y_NOW,
                    'week': W, 'dataThrough': LAST_DATA, 'K': K, 'youthW': YOUTH_W, 'cCur': C_CUR,
                    'rRookie': R_ROOKIE, 'localLinear': list(LL), 'ageScale': AGE_SCALE,
                    'formats': FORMATS, 'scorings': list(SCORINGS),
                    'v': 'val,win3,youth,rk,y0,y1,y2,y3,y4 (rk 0 on TE-premium keys: the site ranks client-side)',
                    'd': 'points quintiles (10/30/50/70/90) per season from Y_NOW, by scoring[_tep]; site prices VOR vs a league replacement and scales v by (league / 12-team default) — backtest_dynasty_league.py',
                    'frac': round(frac, 4),
                    'note': 'PROTOTYPE — comparables model; 2026 weeks 1-%d folded in' % W},
           'players': {}}

    # TE premium (+0.5 / +1.0 per TE reception, backtest_dynasty_scoring.py --tep):
    # only TE values change, so those jobs value TEs only, stored under
    # '<fmt>_<scoring>_tep<x>'; the site ranks everyone client-side.
    TEPS = (0.5, 1.0)
    jobs = [(k, n, 0.0) for k, n in SCORINGS.items()] + [(k, n, t) for t in TEPS for k, n in SCORINGS.items()]
    out['meta']['teps'] = list(TEPS)
    for sc_key, sc_name, tep in jobs:
        if (sc_key, tep) != ('ppr', 0.0):
            w = World(LAST_DATA, scoring=sc_name, tep=tep)
        cands = set()
        for key, P in w.players.items():
            if tep and key[1] != 'TE':
                continue
            if any(y in P['by'] for y in (2023, 2024, 2025)) or w.weekly.get(key, {}).get(Y_NOW):
                cands.add(key)
            if P['draft'] and P['draft'][0] == Y_NOW:
                cands.add(key)
        if tep:
            cands = {k for k in cands if k[1] == 'TE'}
        for fmt, starters in FORMATS.items():
            vk = fmt + '_' + sc_key + ('_tep%g' % tep if tep else '')
            dk = sc_key + ('_tep%g' % tep if tep else '')       # distribution key (format-free)
            rows = w.rows(starters, Y_NOW - 1)
            comps = Comps(rows, LAST_DATA, AGE_SCALE)
            want_d = fmt == '1qb'
            if want_d:
                tbl = w.repl_table(range(Y_NOW - 5, Y_NOW))
                out['meta'].setdefault('repl', {})[dk] = {'TE': tbl['TE']} if tep else tbl
            vals = {}
            for key in cands:
                pos = key[1]
                age0 = w.age(key, Y_NOW)
                if age0 is None:
                    continue
                P = w.players[key]
                g_cur, tot = w.cur_season(key, Y_NOW, W)
                dr = P['draft']
                drafted_now = bool(dr and dr[0] == Y_NOW)
                # undrafted first-year players: no NFL history before 2026
                rookie = drafted_now or (not any(y < Y_NOW for y in P['by']) and g_cur > 0 and not dr)
                vet_ev = None
                vet_d = None
                g_behind = 99
                if g_cur > 0 or not rookie:
                    b = w.base_at(key, Y_NOW, W, C_CUR) if not rookie else None
                    if rookie:
                        base = score_rates({k: tot[k] / g_cur for k in STAT_KEYS}, w.sc_for(pos))
                        gp1 = min(17.0, g_cur * 17.0 / max(W, 1))
                    elif b:
                        base, gp1 = b[0], b[1]
                        g_behind = b[4]
                    else:
                        base = None
                    if base is not None:
                        rel = w.rel(base, Y_NOW, pos)
                        if not rookie and g_behind < LOW_G:
                            rel = (g_behind * rel + LOW_G0 * LOW_TO) / (g_behind + LOW_G0)
                        fv = comps.feat_v(pos, age0, rel, gp1)
                        vet_ev, vc = comps.ev(pos, False, fv, Y_NOW, K, n_comps=5, local_linear=LL)
                        vet_d = comps.ev_dist(pos, False, fv, Y_NOW, K, local_linear=LL) if want_d else None
                if rookie:
                    pick = dr[1] if drafted_now else UDFA_PICK
                    r_ev, rc = comps.ev(pos, True, Comps.feat_rookie(pick, age0), Y_NOW, K, n_comps=5, local_linear=LL)
                    a = g_cur / (g_cur + R_ROOKIE) if vet_ev else 0.0
                    ev = [(1 - a) * x + a * (y if vet_ev else 0) for x, y in zip(r_ev, vet_ev or r_ev)]
                    cmp = vc if (vet_ev and a >= 0.5) else rc
                    dist = None
                    if want_d:
                        r_d = comps.ev_dist(pos, True, Comps.feat_rookie(pick, age0), Y_NOW, K, local_linear=LL)
                        dist = [[(1 - a) * x + a * y for x, y in zip(rk, vk_)] for rk, vk_ in zip(r_d, vet_d)] if vet_d else r_d
                else:
                    if not vet_ev:
                        continue
                    ev, cmp = vet_ev, vc
                    dist = vet_d
                win3 = ev[0] * frac + ev[1] + ev[2]
                youth = ev[3] + ev[4]
                pk = P['name'] + '|' + pos
                e = out['players'].setdefault(pk, {'n': P['name'], 'pos': pos, 'age': age0, 'rookie': rookie,
                                                   'pick': (dr[1] if drafted_now else None), 'g26': g_cur, 'v': {}})
                if vk == '1qb_ppr':
                    e['c'] = [[w.players[c[0]]['name'], c[1], round(c[2])] for c in cmp]
                # season-points quintiles (league-aware VOR on the site); all-zero ranges dropped
                if want_d and dist and any(q > 0 for row in dist for q in row):
                    e.setdefault('d', {})[dk] = [[round(q) for q in row] for row in dist]
                vals[pk] = (win3 + YOUTH_W * youth, win3, youth, [ev[0] * frac] + list(ev[1:]))
            # Rookie pick entries (dyn_picks.py): historical slot curves under this
            # format/scoring, 2027 nudged by the JM class read at weight W_CLASS.
            # TE-premium keys skip picks (the base value is used for them).
            if not tep:
                curves = dyn_picks.slot_curves(w, LAST_DATA)
                ratio, cinfo = dyn_picks.class_ratio(w, LAST_DATA)
                if vk == '1qb_ppr':
                    out['meta']['picks'] = dict(cinfo, wClass=W_CLASS, baseline='FFC rookie ADP 2015-23, 2025 + NFL order to 48')
                pdist = dyn_picks.pick_dists(w, LAST_DATA, Y_NOW) if want_d else {}
                if pdist:
                    out['meta']['pickPos'] = pdist['_pos']
                for pname, x in dyn_picks.pick_values(curves, ratio, W_CLASS, Y_NOW, frac, YOUTH_W).items():
                    pk = pname + '|PICK'
                    e = out['players'].setdefault(pk, {'n': pname, 'pos': 'PICK', 'age': None, 'rookie': False,
                                                       'pick': None, 'g26': 0, 'v': {}, 'cls': {}})
                    e['cls'][vk] = round(x[4], 3)
                    if pname in pdist:
                        e.setdefault('d', {})[dk] = pdist[pname]
                    vals[pk] = x[:4]
            for i, (pk, x) in enumerate(sorted(vals.items(), key=lambda kv: -kv[1][0])):
                out['players'][pk]['v'][vk] = [round(x[0]), round(x[1]), round(x[2]), 0 if tep else i + 1] + [round(y) for y in x[3]]
            print(f'{vk}: {len(vals)} players valued')

    # Expected market value next year (backtest_dynasty_market_next.py, M3 LOYO):
    # log next-year market rank ~ log market rank + log sim rank + rookie + pos + age x pos.
    mk = os.path.join(HERE, '_dyn_cache', 'market_next_coef.json')
    if os.path.exists(mk):
        out['meta']['mktNext'] = json.load(open(mk, encoding='utf-8'))
    with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write('// Dynasty SIM values (PROTOTYPE) — built by sim_lab/build_dynasty_sim.py. Do not hand-edit.\n')
        f.write('window.DYNASTY_SIM_2026 = ' + json.dumps(out, separators=(',', ':')) + ';\n')
    print(f'wrote {args.out}: {len(out["players"])} players, {os.path.getsize(args.out) // 1024} KB')
    for vk in ('1qb_ppr', '1qb_half', '1qb_std', 'sf_ppr'):
        top = sorted((e for e in out['players'].values() if vk in e['v']), key=lambda e: e['v'][vk][3])[:15]
        print(f'--- {vk} top 15: ' + ', '.join(f"{e['n']} {e['v'][vk][0]}" for e in top))
    for vk in ('1qb_ppr', '1qb_ppr_tep0.5', '1qb_ppr_tep1'):
        te = sorted((e for e in out['players'].values() if e['pos'] == 'TE' and vk in e['v']), key=lambda e: -e['v'][vk][0])[:6]
        print(f'--- TEs {vk}: ' + ', '.join(f"{e['n']} {e['v'][vk][0]}" for e in te))


if __name__ == '__main__':
    main()
