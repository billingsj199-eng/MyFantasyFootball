#!/usr/bin/env python3
"""
backtest_dynasty_sim.py — Dynasty SIM value: 3-season window + youth credit.

Jack 2026-10-09: "realistically in dynasty no reason to project beyond 3
seasons ... but we also have to add value to a guy that is much younger
regardless of the 3 year outlook."

Value (preseason of year Y, PPR, 12-team 1QB starters QB12/RB30/WR42/TE12):
    WIN3  = sum_{k=0..2} E[VOR(Y+k)]          (the 3-year dynasty window)
    YOUTH = sum_{k=3..4} E[VOR(Y+k)]          (what's left after the window)
    SCORE = WIN3 + w * YOUTH
VOR(season) = max(0, season PPR pts - first non-starter's pts), 0 if he didn't play.

E[VOR(Y+k)] = COMPARABLES ("comps"): the mean realized VOR(Y'+k) of the K most
similar past player-seasons —
  vets    same pos; age, production entering Y relative to replacement
          (50/30/20 games-weighted PPR rates = the shipped JS core), games last year
  rookies same pos; draft pick (log), age at draft
Strictly forward: a comp counts only if its Y'+k season finished before Y,
and never the same player. Retirement / cuts / injury craters are in the comps'
outcomes, so availability and survival are priced without a separate model.

Truth: realized VOR, T3 = Y..Y+2 (start 2015-2023), T5 = Y..Y+4 (2015-2021).
Baselines: FFC dynasty startup ADP (the market), one-year comps (k=0 only).
Pool: players in that year's FFC dynasty ADP (the dynasty-relevant set).

Usage: python backtest_dynasty_sim.py [--diag]
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
JS_SCRIPTS = os.path.join(os.path.dirname(HERE), 'js_model_site', 'scripts')
sys.path.insert(0, JS_SCRIPTS)
from backtest_js_model import (  # noqa: E402
    SCORING, POSITIONS, W3_WEIGHTS, load_js_const, season_rates, score_rates,
    blend_rates, age_in_season, spearman, _norm_name,
)
from backtest_dynasty_model import load_roster_birth_years, DATA_DIR  # noqa: E402

CACHE = os.path.join(HERE, '_dyn_cache')
PBP = os.path.join(os.path.dirname(HERE), 'pbp_cache')
SC = SCORING['full_ppr']
STARTERS = {'QB': 12, 'RB': 30, 'WR': 42, 'TE': 12}
TRAIN_FROM = 2003
START_YEARS = list(range(2015, 2024))
LAST_DATA = 2025
H = 5
K_GRID = (15, 30, 60)
K_MAIN = 30
YOUTH_W = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0]


def ffc_adp(y):
    p = os.path.join(CACHE, f'ffc_dynasty_{y}.json')
    if not os.path.exists(p):
        return []
    d = json.load(open(p, encoding='utf-8'))
    return [(_norm_name(x['name']), x['position'], x['adp'])
            for x in d.get('players', []) if x['position'] in POSITIONS]


def season_pts(s):
    r = season_rates(s) if s else None
    return score_rates(r, SC) * s['gp'] if r else 0.0


def load_draft():
    import pandas as pd
    d = pd.read_parquet(os.path.join(PBP, 'draft_picks.parquet'))
    d = d[d.position.isin(POSITIONS)]
    out = {}
    for r in d.itertuples():
        age = float(r.age) if r.age == r.age and r.age else None
        out[(_norm_name(r.pfr_player_name or ''), r.position)] = (int(r.season), int(r.pick), age)
    return out


def load_contracts():
    """(norm name, pos) -> [(year_signed, years, apy_cap_pct, guaranteed share)]."""
    import pandas as pd
    d = pd.read_parquet(os.path.join(PBP, 'historical_contracts.parquet'))
    d = d[d.position.isin(POSITIONS)]
    out = defaultdict(list)
    for r in d.itertuples():
        ys, yrs = r.year_signed, r.years
        if not ys or yrs != yrs or not yrs:
            continue
        cap = r.apy_cap_pct if r.apy_cap_pct == r.apy_cap_pct else 0.0
        val = r.value if r.value == r.value and r.value else 0.0
        gtd = (r.guaranteed / val) if val and r.guaranteed == r.guaranteed else 0.0
        out[(_norm_name(r.player or ''), r.position)].append((int(ys), int(yrs), float(cap), float(gtd)))
    return out


def main():
    print('Loading...')
    db = load_js_const(os.path.join(DATA_DIR, 'all_players.js'), 'ALL_PLAYERS_DB')
    births = load_roster_birth_years()
    draft = load_draft()

    players = {}
    pts_by_year = defaultdict(dict)
    for p in db:
        pos = p.get('pos')
        if pos not in POSITIONS:
            continue
        key = (_norm_name(p['name']), pos)
        by_year = {s['yr']: s for s in (p.get('career') or []) if s.get('yr')}
        dr = draft.get(key)
        birth = p.get('birthYear') or births.get(key)
        if not birth and dr and dr[2]:
            birth = str(int(dr[0] - dr[2]))
        players[key] = {'by': by_year, 'birth': birth, 'debut': p.get('debut'), 'draft': dr}
        for yr, s in by_year.items():
            if (s.get('gp') or 0) >= 1:
                pts_by_year[yr][key] = season_pts(s)
    for key, dr in draft.items():   # drafted, never produced = 0-value outcomes
        if key not in players:
            players[key] = {'by': {}, 'birth': str(int(dr[0] - dr[2])) if dr[2] else None,
                            'debut': None, 'draft': dr}

    repl = {}
    for yr, m in pts_by_year.items():
        for pos in POSITIONS:
            v = sorted((pts for (n, ps), pts in m.items() if ps == pos), reverse=True)
            repl[(yr, pos)] = v[STARTERS[pos]] if len(v) > STARTERS[pos] else 0.0

    def vor(key, yr):
        if yr > LAST_DATA:
            return None
        return max(0.0, pts_by_year[yr].get(key, 0.0) - repl[(yr, key[1])])

    rows = []
    for Y in range(TRAIN_FROM, START_YEARS[-1] + 1):
        for key, P in players.items():
            pos = key[1]
            dr = P['draft']
            rookie = bool(dr and dr[0] == Y)
            prev = P['by'].get(Y - 1)
            if not rookie and not (prev and (prev.get('gp') or 0) >= 1):
                continue
            age0 = age_in_season(P['birth'], Y)
            if age0 is None:
                continue
            row = {'key': key, 'pos': pos, 'Y': Y, 'age0': age0, 'rookie': rookie}
            if rookie:
                row['pick'] = dr[1]
            else:
                rl, wgl = [], []
                for back, w in zip(range(1, 4), W3_WEIGHTS):
                    s = P['by'].get(Y - back)
                    r = season_rates(s) if s else None
                    if r:
                        rl.append(r); wgl.append(w * min(s.get('gp') or 0, 17))
                if not rl or sum(wgl) <= 0:
                    continue
                row['base'] = score_rates(blend_rates(rl, wgl), SC)
                rp = max(repl[(Y - 1, pos)] / 17.0, 1.0)
                row['rel'] = max(row['base'], 0.5) / rp
                row['gp1'] = min(prev.get('gp') or 0, 17)
            row['vor'] = [vor(key, Y + k) for k in range(H)]
            rows.append(row)
    print(f'{len(rows)} rows {TRAIN_FROM}-{START_YEARS[-1]} ({sum(r["rookie"] for r in rows)} rookies)')

    # ---- market pool
    adp_pool, unmatched = [], 0
    for Y in START_YEARS:
        idx = {r['key']: r for r in rows if r['Y'] == Y}
        for name, pos, adp in ffc_adp(Y):
            r = idx.get((name, pos))
            if r:
                r['adp'] = adp; adp_pool.append(r)
            else:
                unmatched += 1
    print(f'ADP pool: {len(adp_pool)} player-years ({unmatched} unmatched)')

    # ---- comps (numpy per pos x rookie group)
    groups = defaultdict(list)
    for r in rows:
        groups[(r['pos'], r['rookie'])].append(r)
    G = {}
    for g, lst in groups.items():
        Y = np.array([r['Y'] for r in lst])
        age = np.array([r['age0'] for r in lst], float)
        vor_m = np.array([[np.nan if v is None else v for v in r['vor']] for r in lst], float)
        keys = np.array([hash(r['key']) for r in lst])
        if g[1]:
            feats = np.stack([np.log(np.array([r['pick'] for r in lst], float)) / 0.35, age / 1.5], 1)
        else:
            feats = np.stack([age / 2.0,
                              np.log(np.array([r['rel'] for r in lst])) / 0.15,
                              np.array([r['gp1'] for r in lst], float) / 10.0], 1)
        G[g] = (Y, feats, vor_m, keys)

    def comps(r, K):
        Y, feats, vor_m, keys = G[(r['pos'], r['rookie'])]
        if r['rookie']:
            f = np.array([math.log(r['pick']) / 0.35, r['age0'] / 1.5])
        else:
            f = np.array([r['age0'] / 2.0, math.log(r['rel']) / 0.15, r['gp1'] / 10.0])
        d = ((feats - f) ** 2).sum(1)
        out = []
        for k in range(H):
            ok = (Y + k <= r['Y'] - 1) & (keys != hash(r['key'])) & ~np.isnan(vor_m[:, k])
            idx = np.where(ok)[0]
            if len(idx) == 0:
                out.append(0.0); continue
            nn = idx[np.argsort(d[idx])[:K]]
            out.append(float(vor_m[nn, k].mean()))
        return out

    preds = {}
    for r in adp_pool:
        for K in K_GRID:
            preds[(id(r), K)] = comps(r, K)

    if '--diag' in sys.argv:
        for Y in (2018, 2021):
            yr = sorted([r for r in adp_pool if r['Y'] == Y], key=lambda r: -sum(preds[(id(r), K_MAIN)][:3]))
            print(f'--- {Y} SIM top 30 (win3 = E[VOR] yrs 0-2 | youth = yrs 3-4 | true3)')
            for r in yr[:30]:
                p = preds[(id(r), K_MAIN)]
                print(f"{r['key'][0][:22]:<23}{r['pos']:<3} age{r['age0']} rk{int(r['rookie'])} "
                      f"base{r.get('base', 0):5.1f} adp{r['adp']:6.1f} win3 {sum(p[:3]):6.1f} "
                      f"[{', '.join(f'{x:.0f}' for x in p[:3])}] youth {sum(p[3:]):5.1f} "
                      f"true3 {sum(v or 0 for v in r['vor'][:3]):6.1f}")
        return

    # ---- evaluation
    def score_fn(K, w):
        return lambda r: sum(preds[(id(r), K)][:3]) + w * sum(preds[(id(r), K)][3:5])

    def tsum(r, a, b):
        return sum(v for v in r['vor'][a:b] if v is not None)
    truth3 = lambda r: tsum(r, 0, 3)
    truth5 = lambda r: tsum(r, 0, 5)
    tail = lambda r: tsum(r, 3, 5)
    mkt = lambda r: -r['adp']

    def evaluate(pool, pred, truth, years, topn=36):
        sp_n = sp_d = cap_n = cap_d = 0.0
        for Y in years:
            yr = [r for r in pool if r['Y'] == Y]
            if len(yr) < 20:
                continue
            pv = [pred(r) for r in yr]; tv = [truth(r) for r in yr]
            sp = spearman(pv, tv)
            if sp is not None:
                sp_n += sp * len(yr); sp_d += len(yr)
            n = min(topn, len(yr))
            mt = sorted(range(len(yr)), key=lambda i: -pv[i])[:n]
            cap_n += sum(tv[i] for i in mt); cap_d += sum(sorted(tv, reverse=True)[:n])
        return (sp_n / sp_d if sp_d else float('nan'), cap_n / cap_d if cap_d else float('nan'))

    def rank_blend(f, wm, years):
        cache = {}
        for Y in years:
            yr = [r for r in adp_pool if r['Y'] == Y]
            ra = {id(r): i for i, r in enumerate(sorted(yr, key=lambda r: -f(r)))}
            rb = {id(r): i for i, r in enumerate(sorted(yr, key=lambda r: r['adp']))}
            for r in yr:
                cache[id(r)] = -((1 - wm) * ra[id(r)] + wm * rb[id(r)])
        return lambda r: cache[id(r)]

    y3 = START_YEARS
    y5 = [y for y in START_YEARS if y + 4 <= LAST_DATA]

    print('\n=== A. 3-season window (T3), FFC dynasty pool, start %d-%d ===' % (y3[0], y3[-1]))
    print(f'{"model":<36}{"Spearman":>9}{"top36 value":>13}')
    lines = [('MARKET (FFC dynasty ADP)', mkt),
             ('one-year comps (k=0 only)', lambda r: preds[(id(r), K_MAIN)][0])]
    lines += [(f'SIM WIN3 comps K{K}', score_fn(K, 0.0)) for K in K_GRID]
    lines += [(f'SIM WIN3 x MARKET {int(wm*100)}% mkt', rank_blend(score_fn(K_MAIN, 0.0), wm, y3))
              for wm in (0.25, 0.5, 0.75)]
    for name, f in lines:
        sp, cap = evaluate(adp_pool, f, truth3, y3)
        print(f'{name:<36}{sp:>9.3f}{cap*100:>12.1f}%')

    print('\n=== B. Does YOUTH (yrs 3-4 comps) predict the realized tail? start %d-%d ===' % (y5[0], y5[-1]))
    for name, f in (('MARKET', mkt),
                    ('SIM WIN3 alone', score_fn(K_MAIN, 0.0)),
                    ('SIM YOUTH alone', lambda r: sum(preds[(id(r), K_MAIN)][3:5]))):
        sp, cap = evaluate(adp_pool, f, tail, y5)
        print(f'{name:<36}{sp:>9.3f}{cap*100:>12.1f}%   (vs realized Y+3..Y+4)')

    print('\n=== C. SCORE = WIN3 + w x YOUTH vs realized 3yr / 5yr (start %d-%d) ===' % (y5[0], y5[-1]))
    print(f'{"w":<26}{"Sp T3":>8}{"top36 T3":>10}{"Sp T5":>8}{"top36 T5":>10}')
    for name, f in [('MARKET', mkt)] + [(f'SIM w={w}', score_fn(K_MAIN, w)) for w in YOUTH_W] \
            + [(f'SIM w={w} x MKT 50%', rank_blend(score_fn(K_MAIN, w), 0.5, y5)) for w in (0.0, 0.5)]:
        a = evaluate(adp_pool, f, truth3, y5); b = evaluate(adp_pool, f, truth5, y5)
        print(f'{name:<26}{a[0]:>8.3f}{a[1]*100:>9.1f}%{b[0]:>8.3f}{b[1]*100:>9.1f}%')

    print('\n=== D. By position (Spearman vs T3 within position, start %d-%d) ===' % (y3[0], y3[-1]))
    print(f'{"pos":<5}{"n":>5}{"MARKET":>9}{"SIM":>8}{"SIM+.5Y":>9}{"50/50":>8}')
    bl = rank_blend(score_fn(K_MAIN, 0.0), 0.5, y3)
    for pos in POSITIONS:
        pool = [r for r in adp_pool if r['pos'] == pos]
        vals = [evaluate(pool, f, truth3, y3, 12)[0]
                for f in (mkt, score_fn(K_MAIN, 0), score_fn(K_MAIN, .5), bl)]
        print(f'{pos:<5}{len(pool):>5}' + ''.join(f'{v:>9.3f}' if i == 0 else f'{v:>8.3f}' if i != 2 else f'{v:>9.3f}'
                                                for i, v in enumerate(vals)))

    print('\n=== E. By age band (pooled Spearman vs T5, start %d-%d) ===' % (y5[0], y5[-1]))
    print(f'{"age":<8}{"n":>5}{"MARKET":>9}{"WIN3":>8}{"+.5Y":>8}{"+1.0Y":>8}')
    for lo, hi, lbl in ((0, 23, '<=23'), (24, 26, '24-26'), (27, 29, '27-29'), (30, 99, '30+')):
        pool = [r for r in adp_pool if lo <= r['age0'] <= hi and r['Y'] in y5]
        tv = [truth5(r) for r in pool]
        cells = [spearman([f(r) for r in pool], tv)
                 for f in (mkt, score_fn(K_MAIN, 0), score_fn(K_MAIN, .5), score_fn(K_MAIN, 1))]
        print(f'{lbl:<8}{len(pool):>5}' + ''.join(f'{c:>8.3f}' if i else f'{c:>9.3f}' for i, c in enumerate(cells)))

    rk = [r for r in adp_pool if r['rookie']]
    vt = [r for r in adp_pool if not r['rookie']]
    for lbl, pool in (('rookies', rk), ('vets', vt)):
        tv = [truth3(r) for r in pool]
        print(f'{lbl}: n={len(pool)}  Spearman vs T3 pooled: MARKET {spearman([mkt(r) for r in pool], tv):.3f}  '
              f'SIM {spearman([score_fn(K_MAIN, 0)(r) for r in pool], tv):.3f}')

    # ================= F. CONTRACT LAYER (Jack 2026-10-09) =================
    # Contract state entering Y, from what was known AT SIGNING only (OTC
    # year_signed / years / apy_cap_pct / guaranteed) — never the per-year
    # 'cols' breakdown, which records what was actually paid (future cuts).
    # Applied as a multiplier on the comps value per (age band x contract bin),
    # separately for WIN3 and YOUTH, fit leave-one-year-out (and never on the
    # same player), shrunk toward 1.
    contracts = load_contracts()
    LAM = 1500.0

    def age_band(a):
        return '<=26' if a <= 26 else '27-29' if a <= 29 else '30+'

    def con_bin(r):
        deals = [c for c in contracts.get(r['key'], []) if c[0] <= r['Y'] <= c[0] + c[1] - 1]
        if not deals:
            return 'none'
        ys, yrs, cap, gtd = max(deals, key=lambda c: c[0])
        dr = players[r['key']]['draft']
        if dr and ys == dr[0]:
            return 'rookie'
        tier = 'low' if cap < 0.02 else 'mid' if cap < 0.06 else 'high'
        return f'vet_{tier}_' + ('exp' if ys + yrs - r['Y'] <= 1 else 'multi')

    vets = [r for r in adp_pool if not r['rookie']]
    for r in vets:
        r['cell'] = (age_band(r['age0']), con_bin(r))
        p = preds[(id(r), K_MAIN)]
        r['pW'], r['pY'] = sum(p[:3]), sum(p[3:5])
    cov = sum(r['cell'][1] != 'none' for r in vets)
    print(f'\n=== F. CONTRACT LAYER — {cov}/{len(vets)} vets have an OTC deal covering season Y ===')

    def mults(r, years):
        aW = pW = aY = pY = 0.0
        for t in vets:
            if t['Y'] == r['Y'] or t['key'] == r['key'] or t['cell'] != r['cell'] or t['Y'] not in years:
                continue
            aW += truth3(t); pW += t['pW']
            if t['Y'] + 4 <= LAST_DATA:
                aY += tail(t); pY += t['pY']
        return (aW + LAM) / (pW + LAM), (aY + LAM) / (pY + LAM)

    for r in vets:
        r['mW'], r['mY'] = mults(r, set(START_YEARS))

    # full-data table for the record (what the layer learned)
    cells = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])
    for t in vets:
        c = cells[t['cell']]; c[0] += 1; c[1] += truth3(t); c[2] += t['pW']
        if t['Y'] + 4 <= LAST_DATA:
            c[3] += tail(t); c[4] += t['pY']
    print(f'{"age":<7}{"contract":<17}{"n":>5}{"WIN3 x":>8}{"YOUTH x":>9}')
    for (ab, cb), c in sorted(cells.items()):
        print(f'{ab:<7}{cb:<17}{c[0]:>5}{(c[1] + LAM) / (c[2] + LAM):>8.2f}{(c[3] + LAM) / (c[4] + LAM):>9.2f}')

    def con_fn(w):
        def f(r):
            if r['rookie']:
                return score_fn(K_MAIN, w)(r)
            return r['pW'] * r['mW'] + w * r['pY'] * r['mY']
        return f

    print(f'\n{"model (T3, start %d-%d)" % (y3[0], y3[-1]):<36}{"Spearman":>9}{"top36 value":>13}')
    for name, f in (('MARKET', mkt), ('SIM comps', score_fn(K_MAIN, 0)), ('SIM + CONTRACTS', con_fn(0)),
                    ('SIM+CON x MARKET 50%', rank_blend(con_fn(0), 0.5, y3)),
                    ('SIM+CON x MARKET 75%', rank_blend(con_fn(0), 0.75, y3))):
        sp, cap = evaluate(adp_pool, f, truth3, y3)
        print(f'{name:<36}{sp:>9.3f}{cap*100:>12.1f}%')

    print(f'\n{"w=1.5 youth (start %d-%d)" % (y5[0], y5[-1]):<26}{"Sp T3":>8}{"top36 T3":>10}{"Sp T5":>8}{"top36 T5":>10}')
    for name, f in (('MARKET', mkt), ('SIM', score_fn(K_MAIN, 1.5)), ('SIM+CON', con_fn(1.5)),
                    ('SIM+CON x MKT 50%', rank_blend(con_fn(1.5), 0.5, y5))):
        a = evaluate(adp_pool, f, truth3, y5); b = evaluate(adp_pool, f, truth5, y5)
        print(f'{name:<26}{a[0]:>8.3f}{a[1]*100:>9.1f}%{b[0]:>8.3f}{b[1]*100:>9.1f}%')

    print(f'\n{"pos":<5}{"MARKET":>8}{"SIM":>8}{"SIM+CON":>9}{"+CON 50/50":>11}   (Spearman vs T3 within pos)')
    blc = rank_blend(con_fn(0), 0.5, y3)
    for pos in POSITIONS:
        pool = [r for r in adp_pool if r['pos'] == pos]
        v = [evaluate(pool, f, truth3, y3, 12)[0] for f in (mkt, score_fn(K_MAIN, 0), con_fn(0), blc)]
        print(f'{pos:<5}{v[0]:>8.3f}{v[1]:>8.3f}{v[2]:>9.3f}{v[3]:>11.3f}')

    print(f'\n{"age":<8}{"n":>5}{"MARKET":>8}{"SIM":>8}{"SIM+CON":>9}   (pooled Spearman vs T5, w=1.5)')
    for lo, hi, lbl in ((0, 23, '<=23'), (24, 26, '24-26'), (27, 29, '27-29'), (30, 99, '30+')):
        pool = [r for r in adp_pool if lo <= r['age0'] <= hi and r['Y'] in y5]
        tv = [truth5(r) for r in pool]
        v = [spearman([f(r) for r in pool], tv) for f in (mkt, score_fn(K_MAIN, 1.5), con_fn(1.5))]
        print(f'{lbl:<8}{len(pool):>5}{v[0]:>8.3f}{v[1]:>8.3f}{v[2]:>9.3f}')

    # strictly-forward check: multipliers fit only on start years whose 3yr
    # window finished before Y (tests 2019-2023)
    fwd = [y for y in y3 if y >= 2019]
    for r in vets:
        tr = {y for y in START_YEARS if y + 2 <= r['Y'] - 1}
        r['mW_f'] = mults(r, tr)[0] if tr else 1.0
    f_fwd = lambda r: score_fn(K_MAIN, 0)(r) if r['rookie'] else r['pW'] * r['mW_f']
    print(f'\nstrictly-forward WIN3 check (start {fwd[0]}-{fwd[-1]}):')
    for name, f in (('MARKET', mkt), ('SIM', score_fn(K_MAIN, 0)), ('SIM+CON fwd', f_fwd)):
        sp, cap = evaluate(adp_pool, f, truth3, fwd)
        print(f'  {name:<14}{sp:>7.3f}{cap*100:>8.1f}%')


if __name__ == '__main__':
    main()
