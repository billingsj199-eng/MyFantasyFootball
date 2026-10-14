#!/usr/bin/env python3
"""
backtest_dynasty_picks.py — rookie pick values for Dynasty SIM (Jack 2026-10-09).

"build the rookie pick values ... based on historical value and the actual
class JM model knowing the numbers aren't complete"

Part 1  SLOT CURVES: what each rookie-draft slot actually turned into.
        Class order = FFC rookie ADP (2015-23, 2025; 32-46 deep), extended to
        48 by NFL draft order of the remaining QB/RB/WR/TE. Realized VOR by
        career year k (k=0 rookie season), 1QB PPR; slot curve = Gaussian-
        kernel average over neighbouring slots (bw 2) across classes.
Part 2  JM vs NFL PICK: does the JM prospect score (data/jm_scores.json,
        2017-25 classes) rank rookies' realized value (rookie yr + next 2)
        beyond NFL draft slot? Spearman of pick, JM, and a rank blend; plus
        JM's partial signal on the residual after the rookie comps (pick, age).
Part 3  CLASS STRENGTH: per class, the comps value of its top-24 prospects
        (by actual pick) vs realized — is a class read worth anything?
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, Comps, FORMATS, _norm_name, DATA_DIR  # noqa: E402
from backtest_js_model import spearman  # noqa: E402

CACHE = os.path.join(HERE, '_dyn_cache')
LAST_DATA = 2025
CLASSES = [y for y in range(2015, 2026) if y != 2024]
NSLOT = 48
LL = (120, 5.0)


def ffc_rookie(y):
    p = os.path.join(CACHE, f'ffc_rookie_{y}.json')
    d = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
    return [(_norm_name(x['name']), x['position']) for x in d.get('players', [])
            if x['position'] in ('QB', 'RB', 'WR', 'TE')]


def class_order(w, Y):
    """[key] for slots 1..NSLOT: FFC rookie ADP, then remaining drafted skill players by NFL pick."""
    seen, order = set(), []
    drafted = {k: dr for k, dr in w.draft.items() if dr[0] == Y}
    for k in ffc_rookie(Y):
        if k in drafted and k not in seen:
            seen.add(k); order.append(k)
    for k, dr in sorted(drafted.items(), key=lambda kv: kv[1][1]):
        if len(order) >= NSLOT:
            break
        if k not in seen:
            seen.add(k); order.append(k)
    return order[:NSLOT]


def main():
    w = World(LAST_DATA)
    rows = w.rows(FORMATS['1qb'], 2025)
    comps = Comps(rows, LAST_DATA, {'QB': 6.0})
    w_vor = lambda k, yr: w.vor(k, yr)

    # ---------- Part 1 ----------
    slots = defaultdict(lambda: defaultdict(list))   # s -> k -> [vor]
    ffc_depth = {}
    for Y in CLASSES:
        order = class_order(w, Y)
        ffc_depth[Y] = len([k for k in ffc_rookie(Y) if k in w.draft and w.draft[k][0] == Y])
        for s, key in enumerate(order, 1):
            for k in range(5):
                v = w_vor(key, Y + k)
                if v is not None:
                    slots[s][k].append(v)
    print('FFC-ordered depth per class: ' + ', '.join(f'{y}:{n}' for y, n in ffc_depth.items()))

    def curve(s, k, bw=2.0):
        num = den = 0.0
        for t in range(1, NSLOT + 1):
            wt = math.exp(-0.5 * ((t - s) / bw) ** 2)
            for v in slots[t][k]:
                num += wt * v; den += wt
        return num / den if den else 0.0

    print('\n=== Part 1: realized VOR by rookie-draft slot and career year (1QB PPR, kernel-smoothed) ===')
    print(f'{"slot":<7}' + ''.join(f'{"yr" + str(k + 1):>8}' for k in range(5)) + f'{"n(yr1)":>8}{"raw yr1-3":>11}')
    for s in (1, 2, 3, 4, 6, 8, 10, 12, 15, 18, 21, 24, 30, 36, 42, 48):
        raw = [sum(slots[s][k][i] for k in range(3)) for i in range(min(len(slots[s][k]) for k in range(3)))]
        print(f'{"%d.%02d" % ((s - 1) // 12 + 1, (s - 1) % 12 + 1):<7}' + ''.join(f'{curve(s, k):>8.0f}' for k in range(5))
              + f'{len(slots[s][0]):>8}{(np.mean(raw) if raw else float("nan")):>11.0f}')
    # pick-entry values (2026 valuation; rookie season = pick year)
    groups = {'Early 1st': range(1, 5), 'Mid 1st': range(5, 9), 'Late 1st': range(9, 13),
              'Early 2nd': range(13, 17), 'Mid 2nd': range(17, 21), 'Late 2nd': range(21, 25),
              '3rd': range(25, 37), '4th': range(37, 49)}
    print('\n=== Pick entries (SIM DYN units: window 2026-28 + 1.5 x 2029-30), 1QB PPR, historical baseline ===')
    print(f'{"pick":<11}' + ''.join(f'{y:>8}' for y in (2027, 2028, 2029, 2030)))
    for g, rng in groups.items():
        ck = [np.mean([curve(s, k) for s in rng]) for k in range(5)]
        vals = []
        for P in (2027, 2028, 2029, 2030):
            win = sum(ck[k] for k in range(5) if 2026 <= P + k <= 2028)
            yth = sum(ck[k] for k in range(5) if 2029 <= P + k <= 2030)
            vals.append(win + 1.5 * yth)
        print(f'{g:<11}' + ''.join(f'{v:>8.0f}' for v in vals))

    # ---------- Part 2 ----------
    jm = json.load(open(os.path.join(DATA_DIR, 'jm_scores.json'), encoding='utf-8'))['scores']
    jmk = {(_norm_name(n), v['pos']): v for n, v in jm.items() if v.get('jm') is not None}
    recs = []
    for Y in range(2017, 2024):
        for key, dr in w.draft.items():
            if dr[0] != Y or key not in jmk:
                continue
            age0 = w.age(key, Y)
            if age0 is None:
                continue
            ev = comps.ev(key[1], True, Comps.feat_rookie(dr[1], age0), Y, exclude_key=key, local_linear=LL)
            t3 = sum((w_vor(key, Y + k) or 0) for k in range(3))
            recs.append({'Y': Y, 'pos': key[1], 'pick': dr[1], 'jm': jmk[key]['jm'], 'comp': sum(ev[:3]), 't3': t3})
    print(f'\n=== Part 2: JM vs NFL pick for drafted rookies 2017-23 with a JM score (n={len(recs)}) ===')

    def sp(f, sub=None):
        lst = [r for r in recs if sub is None or sub(r)]
        return spearman([f(r) for r in lst], [r['t3'] for r in lst]), len(lst)
    for lbl, sub in (('all', None), ('QB', lambda r: r['pos'] == 'QB'), ('RB', lambda r: r['pos'] == 'RB'),
                     ('WR', lambda r: r['pos'] == 'WR'), ('TE', lambda r: r['pos'] == 'TE'),
                     ('picks 1-64', lambda r: r['pick'] <= 64), ('picks 65+', lambda r: r['pick'] > 64)):
        a, n = sp(lambda r: -r['pick'], sub); b, _ = sp(lambda r: r['jm'], sub); c, _ = sp(lambda r: r['comp'], sub)
        # rank blend: mean of within-group ranks of pick (low better) and JM (high better)
        lst = [r for r in recs if sub is None or sub(r)]
        rp = {id(r): i for i, r in enumerate(sorted(lst, key=lambda r: r['pick']))}
        rj = {id(r): i for i, r in enumerate(sorted(lst, key=lambda r: -r['jm']))}
        d_, _ = sp(lambda r: -(rp[id(r)] + rj[id(r)]), sub)
        e_, _ = sp(lambda r: -(0.7 * rp[id(r)] + 0.3 * rj[id(r)]), sub)
        print(f'   {lbl:<11} n={n:<4} pick {a:+.3f}   JM {b:+.3f}   comps(pick,age) {c:+.3f}   50/50 {d_:+.3f}   70/30 {e_:+.3f}')
    # residual: does JM explain what comps(pick, age) miss?
    res = [r['t3'] - r['comp'] for r in recs]
    print(f'   JM vs residual after comps: Spearman {spearman([r["jm"] for r in recs], res):+.3f}')

    # ---------- Part 3 ----------
    print('\n=== Part 3: class strength — top-24 comps value (actual picks) vs realized, by class ===')
    print(f'{"class":<7}{"pred top24":>11}{"real top24":>11}{"JM top24 mean":>15}')
    cls = []
    for Y in range(2017, 2024):
        prs = []
        for key, dr in w.draft.items():
            if dr[0] != Y:
                continue
            age0 = w.age(key, Y)
            if age0 is None:
                continue
            ev = comps.ev(key[1], True, Comps.feat_rookie(dr[1], age0), Y, exclude_key=key, local_linear=LL)
            prs.append((sum(ev[:3]), sum((w_vor(key, Y + k) or 0) for k in range(3)), jmk.get(key, {}).get('jm')))
        prs.sort(key=lambda x: -x[0])
        top = prs[:24]
        jms = [x[2] for x in top if x[2] is not None]
        cls.append((Y, sum(x[0] for x in top), sum(sorted([x[1] for x in prs], reverse=True)[:24]), np.mean(jms) if jms else float('nan')))
        print(f'{Y:<7}{cls[-1][1]:>11.0f}{cls[-1][2]:>11.0f}{cls[-1][3]:>15.1f}')
    print(f'   corr(pred, real) across {len(cls)} classes: {spearman([c[1] for c in cls], [c[2] for c in cls]):+.2f}   '
          f'corr(JM mean, real): {spearman([c[3] for c in cls], [c[2] for c in cls]):+.2f}  (7 classes — weak evidence either way)')


if __name__ == '__main__':
    main()
