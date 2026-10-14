"""
dyn_picks.py — rookie draft pick values for Dynasty SIM (Jack 2026-10-09).

Shared by build_dynasty_sim.py (site values) and backtest_dynasty_picks.py.

  slot_curves(w)      realized VOR by rookie-draft slot (1..48) and career year
                      k=0..4, from past classes ordered by FFC rookie ADP
                      (2015-23, 2025), extended to 48 by NFL pick; Gaussian
                      kernel over neighbouring slots (bw 2). Uses w's current
                      replacement levels (call after w.rows(starters)).
  class_ratio(w, ...) 2027 class strength by slot: prospects projected to be
                      drafted (data/draft_proj.js) sorted by current JM
                      (data/jm_scores.json), each JM mapped to expected VOR by
                      career year via drafted rookies 2017-25 (kernel on JM);
                      ratio vs the average past class at the same slot.
  pick_values(...)    SIM DYN for the board's pick entries (2027-2030 x
                      Early/Mid/Late 1st-2nd, 3rd, 4th). Rookie season = pick
                      year; window = rest of Y_NOW..Y_NOW+2, youth after.
"""
import json
import math
import os
from collections import defaultdict

from dyn_common import _norm_name, DATA_DIR

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, '_dyn_cache')
NSLOT = 48
CLASSES = [y for y in range(2015, 2026) if y != 2024]   # FFC had no 2024 rookie ADP
GROUPS = {'Early 1st': range(1, 5), 'Mid 1st': range(5, 9), 'Late 1st': range(9, 13),
          'Early 2nd': range(13, 17), 'Mid 2nd': range(17, 21), 'Late 2nd': range(21, 25),
          '3rd': range(25, 37), '4th': range(37, 49)}
PICK_YEARS = (2027, 2028, 2029, 2030)


def ffc_rookie(y):
    p = os.path.join(CACHE, f'ffc_rookie_{y}.json')
    d = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
    return [(_norm_name(x['name']), x['position']) for x in d.get('players', [])
            if x['position'] in ('QB', 'RB', 'WR', 'TE')]


def class_order(w, Y):
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


def slot_curves(w, last_data, bw=2.0):
    raw = defaultdict(lambda: defaultdict(list))
    for Y in CLASSES:
        for s, key in enumerate(class_order(w, Y), 1):
            for k in range(5):
                if Y + k <= last_data:
                    raw[s][k].append(w.vor(key, Y + k))
    cur = {}
    for s in range(1, NSLOT + 1):
        row = []
        for k in range(5):
            num = den = 0.0
            for t in range(1, NSLOT + 1):
                wt = math.exp(-0.5 * ((t - s) / bw) ** 2)
                for v in raw[t][k]:
                    num += wt * v; den += wt
            row.append(num / den if den else 0.0)
        cur[s] = row
    return cur


def pick_dists(w, last_data, y_now, qs=(10, 30, 50, 70, 90)):
    """{pick name: [[points quintiles] per season from y_now]} + '_pos': {pick: pos mix} —
    raw season points of past rookies in the group's slots by career year (busts = 0).
    The site uses these like a player's points range to re-price picks for a league;
    the position mix lets it choose a replacement level (weighted by how often each
    position went in those slots)."""
    import numpy as np
    raw = defaultdict(lambda: defaultdict(list))
    posmix = defaultdict(lambda: defaultdict(int))
    for Y in CLASSES:
        for s, key in enumerate(class_order(w, Y), 1):
            posmix[s][key[1]] += 1
            for k in range(5):
                if Y + k <= last_data:
                    raw[s][k].append(w.pts.get(Y + k, {}).get(key, 0.0))
    out, pmix = {}, {}
    for P in PICK_YEARS:
        for g, rng in GROUPS.items():
            seasons = []
            for i in range(5):
                k = y_now + i - P
                vals = [v for s in rng for v in raw[s][k]] if 0 <= k < 5 else []
                seasons.append([round(float(x)) for x in np.percentile(vals, qs)] if vals else [0] * len(qs))
            out[f'{P} {g}'] = seasons
            tot = defaultdict(int)
            for s in rng:
                for pos, c in posmix[s].items():
                    tot[pos] += c
            n = sum(tot.values()) or 1
            pmix[f'{P} {g}'] = {pos: round(c / n, 2) for pos, c in tot.items()}
    out['_pos'] = None
    # one mix per group name (identical across pick years)
    out['_pos'] = {g: pmix[f'{PICK_YEARS[0]} {g}'] for g in GROUPS}
    return out


def _load_jm():
    d = json.load(open(os.path.join(DATA_DIR, 'jm_scores.json'), encoding='utf-8'))
    return d.get('exported_at'), {(_norm_name(n), v.get('pos')): v for n, v in d['scores'].items() if v.get('jm') is not None}


def _load_draft_proj():
    raw = open(os.path.join(DATA_DIR, 'draft_proj.js'), encoding='utf-8').read()
    d, _ = json.JSONDecoder().raw_decode(raw, raw.index('{'))
    return {_norm_name(n): v for n, v in d.items()}


def class_ratio(w, last_data, cls_year=2027, bw_jm=6.0):
    """-> ({slot: ratio}, info). ratio = class expected value / average past class at that slot."""
    exported, jm = _load_jm()
    proj = _load_draft_proj()
    # JM -> expected VOR by career year (drafted rookies 2017-25 with a JM)
    pts = []
    for key, dr in w.draft.items():
        Y = dr[0]
        if Y < 2017 or Y > last_data or key not in jm:
            continue
        pts.append((jm[key]['jm'], [w.vor(key, Y + k) if Y + k <= last_data else None for k in range(5)]))

    def ev(j):
        tot = 0.0
        for k in range(5):
            num = den = 0.0
            for jj, vs in pts:
                if vs[k] is None:
                    continue
                wt = math.exp(-0.5 * ((jj - j) / bw_jm) ** 2)
                num += wt * vs[k]; den += wt
            tot += (num / den if den else 0.0) * (1.0 if k < 3 else 0.5)   # weight later years less
        return tot

    def curve(jms):
        jms = sorted(jms, reverse=True)[:NSLOT]
        return [ev(j) for j in jms] + [0.0] * (NSLOT - len(jms))

    hist = []
    for Y in range(2017, min(last_data, 2025) + 1):
        js = [jm[k]['jm'] for k, dr in w.draft.items() if dr[0] == Y and k in jm]
        if len(js) >= 30:
            hist.append(curve(js))
    hbar = [sum(c[i] for c in hist) / len(hist) for i in range(NSLOT)]
    cls = [(n, v) for (n, pos), v in jm.items() if v.get('yr') == cls_year
           and isinstance(proj.get(n), (int, float)) and pos in ('QB', 'RB', 'WR', 'TE')]
    cc = curve([v['jm'] for n, v in cls])
    # smooth both over neighbouring slots before the ratio (single prospects are noisy)
    def sm(c, s, bw=2.0):
        num = den = 0.0
        for t in range(NSLOT):
            wt = math.exp(-0.5 * ((t - s) / bw) ** 2)
            num += wt * c[t]; den += wt
        return num / den
    ratio = {}
    for s in range(1, NSLOT + 1):
        h = sm(hbar, s - 1)
        ratio[s] = max(0.6, min(1.6, sm(cc, s - 1) / h)) if h > 1 else 1.0
    top = sorted(cls, key=lambda x: -x[1]['jm'])[:8]
    info = {'jmExported': exported, 'classN': len(cls), 'pastClasses': len(hist),
            'top': [[n, v['jm'], v.get('pos')] for n, v in top]}
    return ratio, info


def pick_values(curves, ratio, w_cls, y_now, frac, youth_w, cls_year=2027):
    """-> {pick name: (val, win3, youth, ev[5 seasons from y_now], groupRatio)}."""
    out = {}
    for P in PICK_YEARS:
        for g, rng in GROUPS.items():
            r = sum(ratio.get(s, 1.0) for s in rng) / len(rng) if P == cls_year else 1.0
            m = 1.0 + w_cls * (r - 1.0)
            ck = [m * sum(curves[s][k] for s in rng) / len(rng) for k in range(5)]
            season = {}
            for k in range(5):
                season[P + k] = ck[k]
            ev = [season.get(y_now + i, 0.0) for i in range(5)]
            win3 = ev[0] * frac + ev[1] + ev[2]
            youth = ev[3] + ev[4]
            out[f'{P} {g}'] = (win3 + youth_w * youth, win3, youth, [ev[0] * frac] + ev[1:], m)
    return out
