#!/usr/bin/env python3
"""
DYNASTY UPSIDE (Jack 2026-10-09, after the redraft UPSIDE VOR: "the same will go for the dynasty rankings" / "start the dynasty
upside version"). RESEARCH ONLY - builds on the dynasty SIM prototype (backtest_dynasty_sim.py / dyn_common.py: comps E[VOR]
WIN3 = years 0-2 + 1.5 x YOUTH = years 3-4, 12-team PPR 1QB starters QB12 / RB30 / WR42 / TE12, pool = FFC dynasty ADP).

The prototype already averages the comps' realized VOR (max(0, pts - replacement) per season, so a comp's bust counts 0 and his
elite year counts in full). Two upside ideas on top, neither changes a projection:
  U  UPSIDE WEIGHT on the comps: value = mean + lam x (mean of the comps' top third - mean), per season (lam .25 / .5 / 1 / 2);
     HIT = expected number of elite seasons (comps' share of seasons >= the position's top-12 VOR line)
  O  PATH TO ROLE (young players only, age <= 25 incl. rookies): opening = share of his team's prior-season production at his
     position that belonged to OTHER players who have since left the team or are old (RB >= 28, WR / TE >= 30, QB >= 34);
     value x (1 + beta x opening), beta .25 / .5 / 1
Truths (start years 2015-2023, T5 needs 2015-2021): T3 = sum VOR years 0-2, T5 = years 0-4, ELITE3 = number of top-12
seasons in years 0-2 (the difference-making seasons dynasty rosters are built for). Spearman per start year (pool-weighted)
and top-36 value captured; seasons better than the prototype score; also the 75% market blend (the prototype's best).
Log _dyn_cache/upside.log.
"""
import math, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import dyn_common as DC
import backtest_dynasty_sim as BDS
START = BDS.START_YEARS; LAST = BDS.LAST_DATA; K = BDS.K_MAIN; STARTERS = BDS.STARTERS
OLD = {'RB': 28, 'WR': 30, 'TE': 30, 'QB': 34}
os.makedirs(os.path.join(HERE, '_dyn_cache'), exist_ok=True)
LOG = open(os.path.join(HERE, '_dyn_cache', 'upside.log'), 'w', encoding='utf-8')
def P(s=''):
    print(s); LOG.write(s + '\n'); LOG.flush()


def spearman(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 6 or a.std() == 0 or b.std() == 0: return None
    from scipy.stats import rankdata   # tie-averaged ranks (most truths are 0 for many players)
    return float(np.corrcoef(rankdata(a), rankdata(b))[0, 1])


def main():
    W = DC.World(LAST)
    rows = W.rows(STARTERS, START[-1])
    P(f'{len(rows)} rows {DC.TRAIN_FROM}-{START[-1]}')
    # elite line per (year, pos) = the 12th-best VOR at the position
    elite = {}
    for yr, m in W.pts.items():
        for pos in DC.POSITIONS:
            v = sorted((pts for (n, ps), pts in m.items() if ps == pos), reverse=True)
            elite[(yr, pos)] = max(0.0, (v[11] if len(v) > 11 else 0.0) - W._repl.get((yr, pos), 0.0))
    # comps with the full per-season VOR matrix (top-third + elite share need the comps, not only their mean)
    groups = defaultdict(list)
    for r in rows: groups[(r['pos'], r['rookie'])].append(r)
    G = {}
    for g, lst in groups.items():
        Yv = np.array([r['Y'] for r in lst]); age = np.array([r['age0'] for r in lst], float)
        vm = np.array([[np.nan if v is None else v for v in r['vor']] for r in lst], float)
        el = np.array([[np.nan if r['vor'][k] is None else float(r['vor'][k] >= elite.get((r['Y'] + k, r['pos']), 1e9) and r['vor'][k] > 0) for k in range(DC.H)] for r in lst], float)
        keys = np.array([hash(r['key']) for r in lst])
        if g[1]: feats = np.stack([np.log(np.array([r['pick'] for r in lst], float)) / 0.35, age / 1.5], 1)
        else: feats = np.stack([age / 2.0, np.log(np.array([r['rel'] for r in lst])) / 0.15, np.array([r['gp1'] for r in lst], float) / 10.0], 1)
        G[g] = (Yv, feats, vm, el, keys)

    def comp_stats(r):
        Yv, feats, vm, el, keys = G[(r['pos'], r['rookie'])]
        f = DC.Comps.feat_rookie(r['pick'], r['age0']) if r['rookie'] else DC.Comps.feat_vet(r['age0'], r['rel'], r['gp1'])
        d = ((feats - f) ** 2).sum(1); out = []
        for k in range(DC.H):
            ok = (Yv + k <= r['Y'] - 1) & (keys != hash(r['key'])) & ~np.isnan(vm[:, k])
            idx = np.where(ok)[0]
            if not len(idx): out.append((0.0, 0.0, 0.0)); continue
            nn = idx[np.argsort(d[idx])[:K]]; v = np.sort(vm[nn, k])[::-1]
            top = v[:max(1, len(v) // 3)].mean()
            out.append((float(v.mean()), float(top), float(np.nanmean(el[nn, k]))))
        return out

    # market pool + path-to-role opening
    pool = []
    for Y in START:
        idx = {r['key']: r for r in rows if r['Y'] == Y}
        for name, pos, adp in BDS.ffc_adp(Y):
            r = idx.get((name, pos))
            if r: r['adp'] = adp; pool.append(r)
    P(f'FFC dynasty pool: {len(pool)} player-years {START[0]}-{START[-1]}')
    team_of = lambda key, yr: (W.players[key]['by'].get(yr) or {}).get('tm')
    room = defaultdict(list)   # (yr, tm, pos) -> [(key, pts)]
    for yr, m in W.pts.items():
        for key, pts in m.items():
            tm = team_of(key, yr)
            if tm: room[(yr, tm, key[1])].append((key, pts))
    for r in pool:
        r['cs'] = comp_stats(r)
        key, Y, pos = r['key'], r['Y'], r['pos']
        tm = team_of(key, Y - 1) if not r['rookie'] else (team_of(key, Y) or team_of(key, Y - 1))
        op = 0.0
        if tm and r['age0'] <= 25:
            mates = room.get((Y - 1, tm, pos), [])
            tot = sum(p for _, p in mates)
            if tot > 0:
                gone = 0.0
                for k2, p2 in mates:
                    if k2 == key: continue
                    a2 = W.age(k2, Y); left = team_of(k2, Y) not in (None, tm) or (W.players[k2]['by'].get(Y) is None and Y <= LAST)
                    if left or (a2 is not None and a2 >= OLD[pos]): gone += p2
                op = gone / tot
        r['open'] = op

    tsum = lambda r, a, b: sum(v for v in r['vor'][a:b] if v is not None)
    T3 = lambda r: tsum(r, 0, 3); T5 = lambda r: tsum(r, 0, 5)
    E3 = lambda r: sum(1 for k in range(3) if r['vor'][k] is not None and r['vor'][k] > 0 and r['vor'][k] >= elite.get((r['Y'] + k, r['pos']), 1e9))
    def score(lam=0.0, beta=0.0, hit=False, wy=1.5):
        def f(r):
            cs = r['cs']
            per = [(c[2] * 100.0 if hit else c[0] + lam * (c[1] - c[0])) for c in cs]
            v = sum(per[:3]) + wy * sum(per[3:5])
            if beta and r['age0'] <= 25: v *= 1 + beta * r['open']
            return v
        return f
    base = score()
    mkt = lambda r: -r['adp']
    def blend(f, wm, years):
        cache = {}
        for Y in years:
            yr = [r for r in pool if r['Y'] == Y]
            ra = {id(r): i for i, r in enumerate(sorted(yr, key=lambda r: -f(r)))}
            rb = {id(r): i for i, r in enumerate(sorted(yr, key=lambda r: r['adp']))}
            for r in yr: cache[id(r)] = -((1 - wm) * ra[id(r)] + wm * rb[id(r)])
        return lambda r: cache[id(r)]

    def per_year(pred, truth, years, sub=None):
        out = {}
        for Y in years:
            yr = [r for r in pool if r['Y'] == Y and (sub is None or sub(r))]
            if len(yr) < 20: continue
            pv = [pred(r) for r in yr]; tv = [truth(r) for r in yr]
            sp = spearman(pv, tv); n = min(36, len(yr))
            mt = sorted(range(len(yr)), key=lambda i: -pv[i])[:n]
            cap = sum(tv[i] for i in mt) / max(1e-9, sum(sorted(tv, reverse=True)[:n]))
            out[Y] = (sp, cap, len(yr))
        return out
    def line(lab, pred, truth, years, ref=None, sub=None):
        a = per_year(pred, truth, years, sub)
        if not a: return
        sp = sum(v[0] * v[2] for v in a.values() if v[0] is not None) / sum(v[2] for v in a.values() if v[0] is not None)
        cap = np.mean([v[1] for v in a.values()])
        txt = f'    {lab:<44}{sp:8.3f}{100 * cap:9.1f}%'
        if ref is not None:
            b = per_year(ref, truth, years, sub)
            w = sum(1 for Y in a if Y in b and a[Y][0] is not None and b[Y][0] is not None and a[Y][0] > b[Y][0] + 1e-9)
            txt += f'   better {w}/{len(a)}'
        P(txt)

    y3 = START; y5 = [y for y in START if y + 4 <= LAST]; fwd = [y for y in START if y >= 2019]
    young = lambda r: r['age0'] <= 25
    for tname, truth, years in (('T3 (VOR years 0-2)', T3, y3), ('T5 (VOR years 0-4)', T5, y5), ('ELITE3 (top-12 seasons in years 0-2)', E3, y3)):
        P(f'\n=== {tname}, start {years[0]}-{years[-1]} ===   (Spearman, top-36 value captured, seasons better than the SIM prototype)')
        line('MARKET (FFC dynasty ADP)', mkt, truth, years)
        line('SIM prototype (comps mean, WIN3 + 1.5 YOUTH)', base, truth, years)
        for lam in (0.25, 0.5, 1.0, 2.0): line(f'U  upside weight lam {lam}', score(lam=lam), truth, years, base)
        line('U  HIT (expected elite seasons)', score(hit=True), truth, years, base)
        for beta in (0.25, 0.5, 1.0): line(f'O  path-to-role beta {beta}', score(beta=beta), truth, years, base)
        for lam, beta in ((0.5, 0.5), (1.0, 0.5)): line(f'U+O lam {lam} beta {beta}', score(lam=lam, beta=beta), truth, years, base)
        P('    -- 75% market blends --')
        line('SIM prototype x MARKET 75%', blend(base, 0.75, years), truth, years)
        for lam in (0.5, 1.0): line(f'U lam {lam} x MARKET 75%', blend(score(lam=lam), 0.75, years), truth, years, blend(base, 0.75, years))
        line('O beta .5 x MARKET 75%', blend(score(beta=0.5), 0.75, years), truth, years, blend(base, 0.75, years))
        P('    -- HIT (elite odds) vs / with the market --')
        line('HIT vs MARKET (better = beats market)', score(hit=True), truth, years, mkt)
        for wm in (0.5, 0.75): line(f'HIT x MARKET {int(wm*100)}% (vs market)', blend(score(hit=True), wm, years), truth, years, mkt)
        line('HIT x MARKET 50% fwd 2019+ (vs market)', blend(score(hit=True), 0.5, [y for y in years if y >= 2019]), truth, [y for y in years if y >= 2019], mkt)
        P('    -- young players only (age <= 25 incl. rookies) --')
        line('MARKET', mkt, truth, years, None, young)
        line('SIM prototype', base, truth, years, None, young)
        for lam in (0.5, 1.0): line(f'U lam {lam}', score(lam=lam), truth, years, base, young)
        for beta in (0.5, 1.0): line(f'O beta {beta}', score(beta=beta), truth, years, base, young)
        P('    -- forward check, start 2019+ --')
        line('SIM prototype', base, truth, [y for y in years if y >= 2019])
        for lam in (0.5, 1.0): line(f'U lam {lam}', score(lam=lam), truth, [y for y in years if y >= 2019], base)
        line('O beta .5', score(beta=0.5), truth, [y for y in years if y >= 2019], base)
    op = [r['open'] for r in pool if r['age0'] <= 25]
    P(f'\n  opening among young pool players: mean {np.mean(op):.3f}, share > .3: {np.mean(np.array(op) > 0.3):.1%}')
    LOG.close()


if __name__ == '__main__':
    main()
