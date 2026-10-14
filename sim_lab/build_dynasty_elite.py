#!/usr/bin/env python3
"""
build_dynasty_elite.py - 2026 dynasty ELITE ODDS for the site (PROTOTYPE, beside build_dynasty_sim.py).

Jack 2026-10-09: dynasty version of the upside idea. backtest_dynasty_upside.py (_dyn_cache/upside.log, FFC dynasty pool
2015-23): the comps' share of TOP-12 seasons predicts who delivers difference-making seasons - elite seasons in years 0-2
Spearman .444 vs FFC ADP .386 (8/9 seasons) and the SIM prototype .281 (9/9); ranked 50/50 with the market .468 (9/9 vs
market, forward 2019+ 5/5), top-36 elite capture 62.3% vs 57.6%. Upside-weighted comps and path-to-role FAILED.

ELITE ODDS = the K=30 nearest comps (same features as the SIM prototype: vets age / production vs replacement / games,
rookies log pick / age) -> share of their seasons that finished top-12 at the position, per year ahead.
  e3   = expected top-12 seasons: rest of 2026 (x (18-W)/18) + 2027 + 2028
  e5   = 2029 + 2030 (the youth years)
  hit  = e3 + 1.5 x e5 (the backtested score)
  p    = [P(top-12)] per year
Same in-season fold as the SIM prototype: vets' 2026 weeks 1..W in the core at 2 x games; rookies blend draft comps with
vet-style comps from their own 2026 rate at g / (g + 2). Plain K-nearest comps (what was tested), not local-linear.
Output: <site>/data/dynasty_elite_2026.js (window.DYNASTY_ELITE_2026). Usage: python build_dynasty_elite.py [--out PATH] [--week W]
"""
import argparse, datetime, json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS, WEEKS, SC, STAT_KEYS, score_rates, DATA_DIR, H, POSITIONS  # noqa: E402
from build_dynasty_sim import completed_weeks, Y_NOW, LAST_DATA, C_CUR, R_ROOKIE, UDFA_PICK, YOUTH_W  # noqa: E402
K = 30
ELITE_N = 12


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(DATA_DIR, 'dynasty_elite_2026.js'))
    ap.add_argument('--week', type=int, default=None)
    args = ap.parse_args()
    w = World(LAST_DATA)
    Wk = args.week if args.week is not None else completed_weeks(w)
    frac = (WEEKS - Wk) / WEEKS
    rows = w.rows(FORMATS['1qb'], Y_NOW - 1)   # elite = position rank <= 12 by points: format-independent
    line = {}
    for yr, m in w.pts.items():
        for pos in POSITIONS:
            v = sorted((pts for (n, ps), pts in m.items() if ps == pos), reverse=True)
            line[(yr, pos)] = v[ELITE_N - 1] if len(v) >= ELITE_N else 1e9
    groups = defaultdict(list)
    for r in rows: groups[(r['pos'], r['rookie'])].append(r)
    G = {}
    for g, lst in groups.items():
        Yv = np.array([r['Y'] for r in lst]); age = np.array([r['age0'] for r in lst], float)
        el = np.full((len(lst), H), np.nan)
        for i, r in enumerate(lst):
            for k in range(H):
                yr = r['Y'] + k
                if yr <= LAST_DATA:
                    p_ = w.pts[yr].get(r['key'], 0.0)
                    el[i, k] = 1.0 if (p_ > 0 and p_ >= line[(yr, r['pos'])]) else 0.0
        if g[1]: feats = np.stack([np.log(np.array([r['pick'] for r in lst], float)) / 0.35, age / 1.5], 1)
        else: feats = np.stack([age / 2.0, np.log(np.array([r['rel'] for r in lst])) / 0.15, np.array([r['gp1'] for r in lst], float) / 10.0], 1)
        G[g] = (Yv, feats, el)

    def odds(pos, rookie, f):
        Yv, feats, el = G[(pos, rookie)]
        d = ((feats - f) ** 2).sum(1); out = []
        for k in range(H):
            ok = (Yv + k <= min(Y_NOW - 1, LAST_DATA)) & ~np.isnan(el[:, k])
            idx = np.where(ok)[0]
            nn = idx[np.argsort(d[idx])[:K]]
            out.append(float(el[nn, k].mean()) if len(nn) else 0.0)
        return out

    cands = set()
    for key, P in w.players.items():
        if any(y in P['by'] for y in (2023, 2024, 2025)) or w.weekly.get(key, {}).get(Y_NOW): cands.add(key)
        if P['draft'] and P['draft'][0] == Y_NOW: cands.add(key)
    out = {'meta': {'built': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), 'valuationYear': Y_NOW, 'week': Wk, 'K': K, 'eliteN': ELITE_N,
                    'youthW': YOUTH_W, 'note': 'PROTOTYPE - comps share of top-12 seasons (backtest_dynasty_upside.py)'}, 'players': {}}
    for key in cands:
        pos = key[1]; age0 = w.age(key, Y_NOW)
        if age0 is None: continue
        P = w.players[key]; g_cur, tot = w.cur_season(key, Y_NOW, Wk); dr = P['draft']
        drafted_now = bool(dr and dr[0] == Y_NOW)
        rookie = drafted_now or (not any(y < Y_NOW for y in P['by']) and g_cur > 0 and not dr)
        vet = None
        if g_cur > 0 or not rookie:
            b = w.base_at(key, Y_NOW, Wk, C_CUR) if not rookie else None
            if rookie:
                base = score_rates({k: tot[k] / g_cur for k in STAT_KEYS}, SC); gp1 = min(17.0, g_cur * 17.0 / max(Wk, 1))
            elif b: base, gp1 = b[0], b[1]
            else: base = None
            if base is not None and (pos, False) in G:
                w._repl = getattr(w, '_repl', None) or w.repl(FORMATS['1qb'])
                vet = odds(pos, False, Comps.feat_vet(age0, w.rel(base, Y_NOW, pos), gp1))
        if rookie:
            if (pos, True) not in G: continue
            ro = odds(pos, True, Comps.feat_rookie(dr[1] if drafted_now else UDFA_PICK, age0))
            a = g_cur / (g_cur + R_ROOKIE) if vet else 0.0
            p = [(1 - a) * x + a * (y if vet else 0) for x, y in zip(ro, vet or ro)]
        else:
            if not vet: continue
            p = vet
        p = [p[0] * frac] + p[1:]
        e3, e5 = sum(p[:3]), sum(p[3:5])
        out['players'][P['name'] + '|' + pos] = {'n': P['name'], 'pos': pos, 'age': age0, 'e3': round(e3, 2), 'e5': round(e5, 2),
                                                 'hit': round(e3 + YOUTH_W * e5, 2), 'p': [round(x, 2) for x in p]}
    ranked = sorted(out['players'].values(), key=lambda e: -e['hit'])
    for i, e in enumerate(ranked): e['rk'] = i + 1
    with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write('// Dynasty ELITE ODDS (PROTOTYPE) - built by sim_lab/build_dynasty_elite.py. Do not hand-edit.\n')
        f.write('window.DYNASTY_ELITE_2026 = ' + json.dumps(out, separators=(',', ':')) + ';\n')
    print(f'week {Wk}: wrote {args.out}: {len(out["players"])} players')
    for e in ranked[:25]:
        print(f"{e['rk']:>3} {e['n'][:24]:<25}{e['pos']:<3} age {e['age']:<3} e3 {e['e3']:.2f}  e5 {e['e5']:.2f}  hit {e['hit']:.2f}  p {e['p']}")


if __name__ == '__main__':
    main()
