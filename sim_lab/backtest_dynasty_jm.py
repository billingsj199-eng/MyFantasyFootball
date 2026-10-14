#!/usr/bin/env python3
"""
backtest_dynasty_jm.py — does the JM prospect score improve Dynasty SIM values
for young players? (Jack 2026-10-09: "is jm model involved for younger players?"
-> "run the JM rookie backtest")

Today the sim values a drafted rookie from rookie comps on (NFL pick, age)
(C), blended toward his own production in-season at g / (g + 2); JM only
nudges the 2027 pick entries. Population: drafted QB/RB/WR/TE 2017-23 with a
JM score (data/jm_scores.json). Truth T3 = realized VOR rookie yr + next 2
(1QB PPR); T5Y = T3 + 1.5 x (yr 4 + yr 5) for 2017-21 (the sim's own units).

Candidates for the preseason rookie value (all on the VOR scale):
  J      JM kernel: Gaussian kernel on JM (bw 6) within position over rookies
         from OTHER classes (leave-one-class-out); E[VOR] by career year
  B(w)   (1-w) C + w J
  R      C x exp(beta * JM residual), residual = JM - E[JM | log pick, pos]
         (kernel on other classes), beta fit leave-one-class-out on
         log((T3+5)/(C3+5)) — "JM beyond what the pick already says"
Honesty checks: PAST-ONLY (J / beta from earlier classes only) and the
LEAKAGE note — the live JM weights were tuned on 2017-24 outcomes (LOYO in
selection, final fit on all), so its past-class scores are partly in-sample.

Also: WEEK 8 rookies (prior blended with own rate at g/(g+2), as live) and
YEAR 2 (sophomore preseason: vet comps on production vs blend with J's
career-year 2..4 read).
Metrics: mean per-class Spearman (rank within class — what a rookie board
does), pooled Spearman, by pick band / position, top-24 hit overlap per class.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS, _norm_name, DATA_DIR, score_rates  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

LAST_DATA = 2025
LL = (120, 5.0)
CLASSES = list(range(2017, 2024))
BW_JM = 6.0
BW_PICK = 0.35
R_ROOKIE = 2.0
W8 = 8
WS = (0.0, 0.25, 0.5, 0.75, 1.0)


def main():
    w = World(LAST_DATA)
    rows = w.rows(FORMATS['1qb'], LAST_DATA)
    comps = Comps(rows, LAST_DATA, {'QB': 6.0})
    jm = json.load(open(os.path.join(DATA_DIR, 'jm_scores.json'), encoding='utf-8'))['scores']
    jmk = {(_norm_name(n), v['pos']): v['jm'] for n, v in jm.items() if v.get('jm') is not None}

    # every drafted rookie 2017-23 with JM + VOR path
    R = []
    for key, dr in w.draft.items():
        Y = dr[0]
        if Y not in CLASSES or key not in jmk or key[1] not in ('QB', 'RB', 'WR', 'TE'):
            continue
        age0 = w.age(key, Y)
        if age0 is None:
            continue
        vor = [w.vor(key, Y + k) for k in range(5)]
        vor = [v if v is not None else None for v in vor]
        R.append({'key': key, 'Y': Y, 'pos': key[1], 'pick': dr[1], 'age0': age0, 'jm': jmk[key], 'vor': vor,
                  'C': comps.ev(key[1], True, Comps.feat_rookie(dr[1], age0), Y, exclude_key=key, local_linear=LL)})
    for r in R:
        r['T3'] = sum((r['vor'][k] or 0) for k in range(3))
        r['T5Y'] = r['T3'] + 1.5 * sum((r['vor'][k] or 0) for k in (3, 4)) if r['Y'] + 4 <= LAST_DATA else None
    print(f'n = {len(R)} drafted rookies 2017-23 with a JM score  '
          + ' '.join(f'{p}:{sum(1 for r in R if r["pos"] == p)}' for p in ('QB', 'RB', 'WR', 'TE')))

    def train(r, past_only):
        return [q for q in R if q['pos'] == r['pos'] and (q['Y'] < r['Y'] if past_only else q['Y'] != r['Y'])]

    def jm_kernel(r, past_only=False, ks=range(5), j=None):
        tr = train(r, past_only)
        j = r['jm'] if j is None else j
        out = []
        for k in ks:
            num = den = 0.0
            for q in tr:
                if q['Y'] + k > LAST_DATA or q['vor'][k] is None:
                    continue
                wt = math.exp(-0.5 * ((q['jm'] - j) / BW_JM) ** 2)
                num += wt * q['vor'][k]; den += wt
            out.append(num / den if den > 1e-9 else None)
        return out

    def jm_resid(r, past_only=False):
        tr = train(r, past_only)
        num = den = 0.0
        lp = math.log(r['pick'])
        for q in tr:
            wt = math.exp(-0.5 * ((math.log(q['pick']) - lp) / BW_PICK) ** 2)
            num += wt * q['jm']; den += wt
        return r['jm'] - num / den if den > 1e-9 else 0.0

    for r in R:
        for po in (False, True):
            J = jm_kernel(r, po)
            r['J' + ('p' if po else '')] = [c if j is None else j for c, j in zip(r['C'], J)]
            r['res' + ('p' if po else '')] = jm_resid(r, po)

    def beta_fit(rs, rk='res'):
        x = np.array([q[rk] for q in rs]); y = np.array([math.log((q['T3'] + 5) / (sum(q['C'][:3]) + 5)) for q in rs])
        return float((x * (y - y.mean())).sum() / max((x * x).sum(), 1e-9)) if len(rs) > 10 else 0.0

    for r in R:
        b = beta_fit([q for q in R if q['Y'] != r['Y']])
        bp = beta_fit([q for q in R if q['Y'] < r['Y']], 'resp')
        r['beta'], r['betap'] = b, bp
        r['Rv'] = [c * math.exp(b * r['res']) for c in r['C']]
        r['Rvp'] = [c * math.exp(bp * r['resp']) for c in r['C']]
    print(f'JM residual beta (all classes): {beta_fit(R):+.4f} per JM point  '
          f'(+10 JM over the pick norm -> x{math.exp(10 * beta_fit(R)):.2f} value)')

    def val(v, horizon):
        return sum(v[:3]) if horizon == 'T3' else sum(v[:3]) + 1.5 * (v[3] + v[4])

    CANDS = [('C  comps(pick,age) LIVE', lambda r: r['C']),
             ('J  JM kernel', lambda r: r['J'])] + \
            [(f'B  {1 - x:.2f}C + {x:.2f}J', (lambda x: lambda r: [(1 - x) * c + x * j for c, j in zip(r['C'], r['J'])])(x)) for x in WS[1:-1]] + \
            [('R  C x JM residual', lambda r: r['Rv']),
             ('Jp past-only kernel', lambda r: r['Jp']),
             ('Bp 0.50C+0.50Jp past-only', lambda r: [0.5 * c + 0.5 * j for c, j in zip(r['C'], r['Jp'])]),
             ('Rp past-only residual', lambda r: r['Rvp'])]

    def score(f, horizon='T3', sub=None):
        lst = [r for r in R if (sub is None or sub(r)) and r[horizon] is not None]
        pooled = spearman([val(f(r), horizon) for r in lst], [r[horizon] for r in lst])
        per = []
        for Y in CLASSES:
            c = [r for r in lst if r['Y'] == Y]
            if len(c) >= 8:
                s = spearman([val(f(r), horizon) for r in c], [r[horizon] for r in c])
                if s is not None:
                    per.append(s)
        hits = []
        for Y in CLASSES:
            c = [r for r in lst if r['Y'] == Y]
            if len(c) >= 30:
                pt = set(id(r) for r in sorted(c, key=lambda r: -val(f(r), horizon))[:24])
                at = set(id(r) for r in sorted(c, key=lambda r: -r[horizon])[:24])
                hits.append(len(pt & at) / 24)
        mae = np.mean([abs(val(f(r), horizon) - r[horizon]) for r in lst])
        return pooled, (np.mean(per) if per else float('nan')), (np.mean(hits) if hits else float('nan')), mae, len(lst)

    for horizon in ('T3', 'T5Y'):
        print(f'\n=== PRESEASON rookie value vs {horizon} ({"rookie yr + 2" if horizon == "T3" else "T3 + 1.5 x yrs 4-5, classes 2017-21"}) ===')
        print(f'{"candidate":<30}{"pooled":>8}{"per-class":>11}{"top24 hit":>11}{"MAE":>8}')
        for name, f in CANDS:
            p, c, h, m, n = score(f, horizon)
            print(f'{name:<30}{p:>+8.3f}{c:>+11.3f}{h:>10.0%}{m:>8.1f}')
        print(f'   n={n}')

    print('\n=== Fair past-only comparison: classes 2020-23 only (3+ earlier classes to learn from) ===')
    late = lambda r: r['Y'] >= 2020
    for name in ('C  comps(pick,age) LIVE', 'J  JM kernel', 'B  0.50C + 0.50J', 'R  C x JM residual', 'Jp past-only kernel', 'Bp 0.50C+0.50Jp past-only', 'Rp past-only residual'):
        f = dict(CANDS)[name]
        p_, c_, h_, m_, n_ = score(f, 'T3', late)
        e = score(f, 'T3', lambda r: late(r) and r['pick'] <= 64)
        print(f'   {name:<30} pooled {p_:+.3f}  per-class {c_:+.3f}  MAE {m_:5.1f}   picks 1-64 pooled {e[0]:+.3f}  (n={n_}/{e[4]})')

    print('\n=== By segment (T3 per-class Spearman unless n small -> pooled) — LIVE C vs J vs 50/50 vs R ===')
    segs = [('picks 1-32', lambda r: r['pick'] <= 32), ('picks 33-64', lambda r: 32 < r['pick'] <= 64),
            ('picks 1-64', lambda r: r['pick'] <= 64), ('picks 65-128', lambda r: 64 < r['pick'] <= 128),
            ('picks 129+', lambda r: r['pick'] > 128)] + [(p, (lambda p: lambda r: r['pos'] == p)(p)) for p in ('QB', 'RB', 'WR', 'TE')] + \
           [(p + ' 1-64', (lambda p: lambda r: r['pos'] == p and r['pick'] <= 64)(p)) for p in ('QB', 'RB', 'WR', 'TE')]
    pick = {n: f for n, f in CANDS}
    show = ['C  comps(pick,age) LIVE', 'J  JM kernel', 'B  0.50C + 0.50J', 'B  0.75C + 0.25J', 'R  C x JM residual', 'Bp 0.50C+0.50Jp past-only']
    print(f'{"segment":<14}{"n":>5}' + ''.join(f'{s.split()[0] + (" " + s.split()[1] if s.startswith("B") else ""):>14}' for s in show))
    for lbl, sub in segs:
        cells = [score(pick[s], 'T3', sub) for s in show]
        n = cells[0][4]
        use = 0 if n < 60 else 1   # pooled for small segments
        print(f'{lbl:<14}{n:>5}' + ''.join(f'{c[use]:>+14.3f}' for c in cells) + ('  (pooled)' if use == 0 else ''))

    # ---------- WEEK 8 rookies ----------
    print(f'\n=== WEEK {W8} rookies: prior blended with own rate at g/(g+{R_ROOKIE:g}) (as live) — prior = C vs 50/50 C+J vs R ===')
    wk = []
    for r in R:
        g, tot = w.cur_season(r['key'], r['Y'], W8)
        vet = None
        if g > 0:
            base = score_rates({k: tot[k] / g for k in tot}, w.sc_for(r['pos']))
            rel = w.rel(base, r['Y'], r['pos'])
            fv = comps.feat_v(r['pos'], r['age0'], rel, min(17.0, g * 17.0 / W8))
            vet = comps.ev(r['pos'], False, fv, r['Y'], exclude_key=r['key'], local_linear=LL)
        a = g / (g + R_ROOKIE) if vet else 0.0
        wk.append((r, a, vet))
    print(f'   {sum(1 for x in wk if x[1] > 0)} of {len(wk)} played by week {W8}')
    for name, pf in (('prior C (LIVE)', lambda r: r['C']), ('prior 0.50C+0.50J', lambda r: [0.5 * c + 0.5 * j for c, j in zip(r['C'], r['J'])]),
                     ('prior 0.75C+0.25J', lambda r: [0.75 * c + 0.25 * j for c, j in zip(r['C'], r['J'])]), ('prior R', lambda r: r['Rv'])):
        vals = [(sum(((1 - a) * p + a * (v[i] if v else p)) for i, p in enumerate(pf(r)[:3])), r) for r, a, v in wk]
        pooled = spearman([v for v, _ in vals], [r['T3'] for _, r in vals])
        per = [spearman([v for v, r in vals if r['Y'] == Y], [r['T3'] for v, r in vals if r['Y'] == Y]) for Y in CLASSES]
        e64 = [(v, r) for v, r in vals if r['pick'] <= 64]
        print(f'   {name:<20} pooled {pooled:+.3f}  per-class {np.mean(per):+.3f}  picks 1-64 pooled {spearman([v for v, _ in e64], [r["T3"] for _, r in e64]):+.3f}')

    # ---------- YEAR 2 ----------
    print('\n=== YEAR 2 (sophomore preseason): vet comps on rookie production vs blend with JM kernel (career yrs 2-4) ===')
    rowmap = {(x['key'], x['Y']): x for x in rows if not x['rookie']}
    so = []
    for r in R:
        Y2 = r['Y'] + 1
        x = rowmap.get((r['key'], Y2))
        if not x or Y2 + 2 > LAST_DATA:
            continue
        V = comps.ev(r['pos'], False, comps.feat_v(r['pos'], x['age0'], x['rel'], x['gp1']), Y2, exclude_key=r['key'], local_linear=LL)
        t = sum((w.vor(r['key'], Y2 + k) or 0) for k in range(3))
        so.append({'r': r, 'V': V, 'J': r['J'][1:4], 'Jp': r['Jp'][1:4], 'C': r['C'][1:4], 't': t, 'gp': x['gp1']})
    print(f'   n={len(so)} sophomores with a rookie-year row')
    for src in ('C', 'J', 'Jp'):
        print(f'   -- blend source: {src} ({"pick comps = draft-capital control" if src == "C" else "JM kernel, other classes" if src == "J" else "JM kernel, earlier classes only"})')
        for x_ in (0.1, 0.3, 0.5):
            lst = so
            v = [sum((1 - x_) * a + x_ * b for a, b in zip(s['V'][:3], s[src][:3])) for s in lst]
            e = [s for s in lst if s['r']['pick'] <= 64]
            ve = [sum((1 - x_) * a + x_ * b for a, b in zip(s['V'][:3], s[src][:3])) for s in e]
            l2 = [s for s in lst if s['r']['Y'] >= 2020]
            v2 = [sum((1 - x_) * a + x_ * b for a, b in zip(s['V'][:3], s[src][:3])) for s in l2]
            v20 = [sum(s['V'][:3]) for s in l2]
            print(f'      w {x_:.1f}: all {spearman(v, [s["t"] for s in lst]):+.3f}   picks 1-64 {spearman(ve, [s["t"] for s in e]):+.3f}'
                  f'   classes 2020+ {spearman(v2, [s["t"] for s in l2]):+.3f} (w0 {spearman(v20, [s["t"] for s in l2]):+.3f}, n={len(l2)})')
    for x_ in (0.0, 0.1, 0.2, 0.3, 0.5):
        for lbl, sub in (('all', lambda s: True), ('picks 1-64', lambda s: s['r']['pick'] <= 64), ('rookie gp<8', lambda s: s['gp'] < 8)):
            lst = [s for s in so if sub(s)]
            v = [sum((1 - x_) * a + x_ * b for a, b in zip(s['V'][:3], s['J'][:3])) for s in lst]
            per = [spearman([vv for vv, s in zip(v, lst) if s['r']['Y'] == Y], [s['t'] for s in lst if s['r']['Y'] == Y]) for Y in CLASSES[:-1]]
            per = [p for p in per if p is not None]
            print(f'   JM weight {x_:.1f} {lbl:<12} n={len(lst):<4} pooled {spearman(v, [s["t"] for s in lst]):+.3f}' + (f'  per-class {np.mean(per):+.3f}' if lbl == 'all' else ''))

    # biggest movers under 50/50 (most recent classes) for a sanity read
    print('\n=== Biggest JM movers (50/50 vs live, T3 units), 2021-23 classes ===')
    mv = sorted(((sum(0.5 * c + 0.5 * j for c, j in zip(r['C'][:3], r['J'][:3])) - sum(r['C'][:3]), r) for r in R if r['Y'] >= 2021), key=lambda x: x[0])
    for d, r in mv[:8] + mv[-8:]:
        print(f'   {r["key"][0]:<24}{r["pos"]:<4}{r["Y"]} pick {r["pick"]:>3} JM {r["jm"]:>5.1f}  live {sum(r["C"][:3]):>6.1f} -> {sum(r["C"][:3]) + d:>6.1f}  actual {r["T3"]:>6.1f}')


if __name__ == '__main__':
    main()
