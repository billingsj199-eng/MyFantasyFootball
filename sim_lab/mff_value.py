#!/usr/bin/env python3
"""
mff_value.py — Python port of the site's FAIR VALUE / MFF VALUE player order
(app.js _trendGapFor + window._mffValueBoard), for the forward tracker and
research. Keep in step with app.js:
  pool    = non-pick Dynasty SIM players with a KTC rank <= 200 (KTC overall rank
            among KTC's non-pick assets, by value)
  sp / kp = sim / KTC rank within the pool
  M3      = meta.mktNext coef: log next-year market rank ~ log kp + log sp + rookie
            + position + (age - ageCenter) x position
  FAIR z  = 0.5 M3 + 0.3 log sp + 0.5 log kp  (_FAIR_W); fair value = today's KTC
            value at that z-order position; fairDiff = fair / KTC - 1
  calls   = BUY LOW fairDiff >= +10%, SELL HIGH <= -10% (card tags);
            SIM GAP gap = log(sp / kp), BUY / SELL = bottom / top fifth with 3+ spots apart.
  QB TT   = app.js _fairQbTtPrep (2026-10-09): ESPN depth-chart QB1s only, z = (team's
            rest-of-season mean implied total - mean over the pool's QB1s) / 3.0 x age
            weight (1 at 27+, .5 at 25-26, 0 at <= 24); fz -= 0.4 z. qb_team_totals()
            builds the {QB1 name: total} input from the site data files.
"""
import datetime as dt
import json
import math
import os
import re

FAIR_W = {'m3': 0.5, 'sim': 0.3, 'mkt': 0.5}
QB_TT = {'k': 0.4, 'sd': 3.0}
WEEK1_TUE = dt.date(2026, 9, 8)   # schedule week rolls on Tuesday (site _weeklyScheduleWeek)


def _js_var(path, var):
    """window.<var> = {...}; followed by other code -> the object."""
    s = open(path, encoding='utf-8').read()
    m = re.search(r'^window\.' + var + r'\s*=\s*\{', s, re.M)   # line start: header comments repeat it
    return json.JSONDecoder().raw_decode(s, m.end() - 1)[0]


def qb_age_w(age):
    return 0.0 if age is None else 1.0 if age >= 27 else 0.5 if age >= 25 else 0.0


def qb_team_totals(site_data, today=None):
    """{norm(QB1 name): rest-of-season mean implied team total} — ESPN depth chart QB1,
    book lines (betting_lines_2026.js) with our future totals swapped in where the
    book hasn't moved (future_totals_2026.js overlay), from the current week on."""
    today = today or dt.date.today()
    wk0 = max(1, (today - WEEK1_TUE).days // 7 + 1)
    if wk0 > 18:
        return {}
    # JS literal (unquoted keys, comments), one game per line
    G = {m.group(1): {'total': float(m.group(2)), 'spread': float(m.group(3))} for m in re.finditer(
        r"'(W\d+_[A-Z]+_[A-Z]+)':\s*\{\s*total:\s*([-+\d.]+),\s*spread:\s*([-+\d.]+)",
        open(os.path.join(site_data, 'betting_lines_2026.js'), encoding='utf-8').read())}
    try:
        F = _js_var(os.path.join(site_data, 'future_totals_2026.js'), 'FUTURE_TOTALS_2026')
        for k, r in (F.get('games') or {}).items():
            g = G.get(k)
            if g and g.get('total') == r[2] and g.get('spread') == r[3]:
                g['total'], g['spread'] = r[0], r[1]
    except (OSError, ValueError, KeyError):
        pass
    own = {}
    for k, g in G.items():
        m = re.match(r'^W(\d+)_([A-Z]+)_([A-Z]+)$', k)
        if not m or int(m.group(1)) < wk0 or not isinstance(g.get('total'), (int, float)) or not isinstance(g.get('spread'), (int, float)):
            continue
        away, home = m.group(2), m.group(3)
        own.setdefault(home, []).append((g['total'] - g['spread']) / 2)
        own.setdefault(away, []).append((g['total'] + g['spread']) / 2)
    D = _js_var(os.path.join(site_data, 'depth_charts_2026.js'), 'DEPTH_2026')['teams']
    out = {}
    for t, c in D.items():
        if c.get('QB') and own.get(t):
            out[norm(c['QB'][0])] = sum(own[t]) / len(own[t])
    return out


def norm(n):
    s = str(n or '').lower()
    s = re.sub(r'\s+(jr\.?|sr\.?|iii|ii|iv|v)$', '', s)
    s = re.sub(r"[.\-']", '', s)
    return re.sub(r'\s+', ' ', s).strip()


def load_js_json(path, start_token='{'):
    s = open(path, encoding='utf-8').read()
    return json.loads(s[s.index(start_token):s.rstrip().rstrip(';').rindex('}') + 1])


def load_ktc_map(path, var):
    s = open(path, encoding='utf-8').read()
    m = re.search(r'var ' + var + r'=(\{.*?\});', s, re.S)
    return json.loads(m.group(1))


def fair_table(sim_rows, ktc_map, mkt, rbrec=None, qbtt=None):
    """sim_rows: [{n, pos, val, age, rookie}] (non-pick); ktc_map: {name: value};
    mkt: meta.mktNext; qbtt: qb_team_totals() or None (no QB term).
    -> [{n, pos, kv, ko (KTC overall), kp, sp, fair, fd, call, gap, gcall}]"""
    kt = sorted(((k, v) for k, v in ktc_map.items() if v and not re.match(r'^\d{4} ', k)), key=lambda kv: -kv[1])
    kidx = {norm(k): (v, i + 1) for i, (k, v) in enumerate(kt)}
    pool = []
    for r in sim_rows:
        k = kidx.get(norm(r['n']))
        if k and k[1] <= 200 and r.get('val') is not None:
            pool.append(dict(r, kv=k[0], ko=k[1]))
    if len(pool) < 50:
        return []
    for i, r in enumerate(sorted(pool, key=lambda r: -r['val'])):
        r['sp'] = i + 1
    kr = sorted(pool, key=lambda r: r['ko'])
    for i, r in enumerate(kr):
        r['kp'] = i + 1
    vals = [r['kv'] for r in kr]
    b, ac = mkt['coef'], mkt.get('ageCenter', 25)
    qs = [qbtt[norm(r['n'])] for r in pool if qbtt and r['pos'] == 'QB' and norm(r['n']) in qbtt]
    qmu = sum(qs) / len(qs) if len(qs) >= 8 else None
    for r in pool:
        a = (r['age'] if r.get('age') is not None else ac) - ac
        P = r['pos']
        z = b[0] + b[1] * math.log(r['kp']) + b[2] * math.log(r['sp']) + b[3] * (1 if r.get('rookie') else 0) \
            + (b[4] if P == 'RB' else 0) + (b[5] if P == 'WR' else 0) + (b[6] if P == 'TE' else 0) \
            + a * (b[7] if P == 'QB' else b[8] if P == 'RB' else b[9] if P == 'WR' else b[10])
        r['fz'] = FAIR_W['m3'] * z + FAIR_W['sim'] * math.log(r['sp']) + FAIR_W['mkt'] * math.log(r['kp'])
        if rbrec and P == 'RB' and r.get('rbr'):   # RB receiving tilt (app.js _fairRbRec)
            r['fz'] += rbrec.get('k', 0) * r['rbr']
        if qmu is not None and P == 'QB' and norm(r['n']) in qbtt:   # QB team total (app.js _fairQbTt)
            r['fz'] -= QB_TT['k'] * (qbtt[norm(r['n'])] - qmu) / QB_TT['sd'] * qb_age_w(r.get('age'))
        r['gap'] = math.log(r['sp'] / r['kp'])
    for i, r in enumerate(sorted(pool, key=lambda r: r['fz'])):
        r['fair'] = vals[i]
        r['fd'] = vals[i] / r['kv'] - 1
        r['call'] = 'BUY' if r['fd'] >= 0.10 else 'SELL' if r['fd'] <= -0.10 else ''
    g = sorted(r['gap'] for r in pool)
    lo, hi = g[int(0.2 * len(g))], g[min(len(g) - 1, int(0.8 * len(g)))]
    for r in pool:
        far = abs(r['sp'] - r['kp']) >= 3
        r['gcall'] = 'BUY' if far and r['gap'] <= lo else 'SELL' if far and r['gap'] >= hi else ''
    return [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k in
             ('n', 'pos', 'age', 'kv', 'ko', 'kp', 'sp', 'fair', 'fd', 'call', 'gap', 'gcall')} for r in pool]


def ros_y0(sim, site_data, vk='1qb_ppr'):
    """{(norm name, pos): weekly-sim rest-of-2026 mapped onto the sim's y0 scale} — app.js
    _mffRosY0Map (10-10). SIM_PROJ_2026 weeks after the dynasty valuation week summed
    ([half, ppr, std] by the vk scoring), quantile-mapped onto v[4] per position. The
    site maps over its board's players; this maps over the sim's players (same idea)."""
    try:
        SP = _js_var(os.path.join(site_data, 'sim_proj_2026.js'), 'SIM_PROJ_2026')
    except (OSError, ValueError, AttributeError):
        return {}
    weeks = SP.get('weeks') or {}
    fi = {'half': 0, 'ppr': 1, 'std': 2}.get(vk.split('_')[1], 1)
    w0 = int((sim.get('meta') or {}).get('week') or 0) + 1
    wk_norm = {wk: {norm(n): r for n, r in rows.items()} for wk, rows in weeks.items()}
    by_pos = {}
    for e in sim['players'].values():
        v = (e.get('v') or {}).get(vk)
        if e.get('pos') not in ('QB', 'RB', 'WR', 'TE') or not v or len(v) < 9:
            continue
        pts = 0.0
        for wk in range(w0, 19):
            r = wk_norm.get(str(wk), {}).get(norm(e['n']))
            if r and isinstance(r[fi], (int, float)):
                pts += r[fi]
        by_pos.setdefault(e['pos'], []).append(((norm(e['n']), e['pos']), v[4], pts))
    out = {}
    for g in by_pos.values():
        ys = sorted(y for _, y, _ in g)
        for j, (k, _, _) in enumerate(sorted(g, key=lambda t: t[2])):
            out[k] = ys[j]
    return out


def sim_rows_from_file(sim, vk='1qb_ppr', ros=None):
    """ros: ros_y0() map -> val = v[0] - y0 + mapped y0 (the site's BALANCED value since 10-10)."""
    out = []
    for e in sim['players'].values():
        if e.get('pos') == 'PICK' or vk not in (e.get('v') or {}):
            continue
        v = e['v'][vk]
        r0 = (ros or {}).get((norm(e['n']), e['pos'])) if len(v) >= 9 else None
        val = max(0, v[0] - v[4] + r0) if r0 is not None else v[0]
        out.append({'n': e['n'], 'pos': e['pos'], 'val': val, 'age': e.get('age'), 'rookie': bool(e.get('rookie')), 'rbr': e.get('rbr')})
    return out
