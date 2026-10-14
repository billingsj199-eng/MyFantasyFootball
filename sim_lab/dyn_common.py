"""
dyn_common.py — shared Dynasty SIM machinery (comparables model).

Used by backtest_dynasty_inseason.py and build_dynasty_sim.py so the site's
numbers come from exactly the code that was backtested.

  load()                    -> World (players, season pts, weekly PPR pts)
  World.repl(starters)      -> {(yr, pos): first non-starter's season pts}
  World.rows(starters, ...) -> comps training rows (preseason, 2003+)
  Comps(rows).ev(...)       -> E[VOR(Y+k)] k=0..4 for a feature vector
  World.base_at(key, Y, W, c) -> (base PPG, games-last-season, cur games)
       with season Y weeks 1..W folded in at weight c x games (c relative to
       the 0.5 weight of last season in the 50/30/20 core).
"""
import json
import math
import os
import re
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'js_model_site', 'scripts'))
from backtest_js_model import (  # noqa: E402
    SCORING, POSITIONS, W3_WEIGHTS, load_js_const, season_rates, score_rates,
    blend_rates, age_in_season, _norm_name,
)
from backtest_dynasty_model import load_roster_birth_years, DATA_DIR  # noqa: E402

PBP = os.path.join(os.path.dirname(HERE), 'pbp_cache')
SC = SCORING['full_ppr']
STAT_KEYS = ['py', 'ptd', 'int', 'ry', 'rtd', 'rc', 'rcy', 'rctd', 'fl']
FORMATS = {'1qb': {'QB': 12, 'RB': 30, 'WR': 42, 'TE': 12},
           'sf':  {'QB': 24, 'RB': 30, 'WR': 42, 'TE': 12}}
TRAIN_FROM = 2003
H = 5
WEEKS = 18


def load_draft():
    import pandas as pd
    d = pd.read_parquet(os.path.join(PBP, 'draft_picks.parquet'))
    d = d[d.position.isin(POSITIONS)]
    out = {}
    for r in d.itertuples():
        age = float(r.age) if r.age == r.age and r.age else None
        out[(_norm_name(r.pfr_player_name or ''), r.position)] = (int(r.season), int(r.pick), age)
    return out


def season_pts(s, sc=None):
    r = season_rates(s) if s else None
    return score_rates(r, sc or SC) * s['gp'] if r else 0.0


def week_stats(w):
    """Weekly row -> component dict on the season-DB keys (rec -> rc)."""
    return {'py': w.get('py') or 0, 'ptd': w.get('ptd') or 0, 'int': w.get('int') or 0,
            'ry': w.get('ry') or 0, 'rtd': w.get('rtd') or 0, 'rc': w.get('rec') or 0,
            'rcy': w.get('rcy') or 0, 'rctd': w.get('rctd') or 0, 'fl': w.get('fl') or 0}


def week_played(w):
    return (w.get('fpts') or 0) != 0 or (w.get('pa') or 0) > 0 or (w.get('ra') or 0) > 0 or (w.get('tgt') or 0) > 0


class World:
    def __init__(self, last_data, shrink_g0=0.0, shrink_to=0.8, scoring='full_ppr', tep=0.0):
        """shrink_g0: small-sample guard — production vs replacement (rel) is
        pulled toward shrink_to with weight g0 / (games behind it + g0), in the
        training rows and the query alike (Keenum: 3 games -> elite comps)."""
        self.last_data = last_data
        self.shrink_g0, self.shrink_to = shrink_g0, shrink_to
        self.sc = SCORING[scoring]
        # TE premium: + tep points per TE reception (season + weekly + rates)
        self.tep = float(tep or 0.0)
        self._sc_te = dict(self.sc, rc=self.sc['rc'] + self.tep) if self.tep else self.sc
        db = load_js_const(os.path.join(DATA_DIR, 'all_players.js'), 'ALL_PLAYERS_DB')
        births = load_roster_birth_years()
        self.draft = load_draft()
        self.players = {}
        self.pts = defaultdict(dict)
        for p in db:
            pos = p.get('pos')
            if pos not in POSITIONS:
                continue
            key = (_norm_name(p['name']), pos)
            by_year = {s['yr']: s for s in (p.get('career') or []) if s.get('yr')}
            dr = self.draft.get(key)
            birth = p.get('birthYear') or births.get(key)
            if not birth and dr and dr[2]:
                birth = str(int(dr[0] - dr[2]))
            self.players[key] = {'name': p['name'], 'by': by_year, 'birth': birth, 'draft': dr}
            for yr, s in by_year.items():
                if (s.get('gp') or 0) >= 1 and yr <= last_data:
                    self.pts[yr][key] = season_pts(s, self.sc_for(pos))
        for key, dr in self.draft.items():
            if key not in self.players:
                self.players[key] = {'name': key[0].title(), 'by': {},
                                     'birth': str(int(dr[0] - dr[2])) if dr[2] else None, 'draft': dr}
        # weekly: key -> {yr: [(wk, comps dict)]} for played weeks
        self.weekly = defaultdict(dict)
        for f in ('weekly_stats_active.js', 'weekly_stats_retired_1.js',
                  'weekly_stats_retired_2.js', 'weekly_stats_retired_3.js'):
            raw = open(os.path.join(DATA_DIR, f), encoding='utf-8').read()
            # retired_1 opens with `window.X=window.X||{};...Object.assign(X,{...})`:
            # the first '{' is that empty fallback object — start at the first '{"'.
            d, _ = json.JSONDecoder().raw_decode(raw, raw.index('{"'))
            for name, rec in d.items():
                pos = rec.get('pos')
                if pos not in POSITIONS:
                    continue
                key = (_norm_name(name), pos)
                if key not in self.players:
                    continue
                for y, ws in rec.get('seasons', {}).items():
                    lst = [(w['wk'], week_stats(w)) for w in ws if week_played(w) and isinstance(w.get('wk'), int)]
                    if lst:
                        self.weekly[key][int(y)] = lst

    def sc_for(self, pos):
        return self._sc_te if pos == 'TE' else self.sc

    def age(self, key, Y):
        return age_in_season(self.players[key]['birth'], Y)

    def repl(self, starters):
        out = {}
        for yr, m in self.pts.items():
            for pos in POSITIONS:
                v = sorted((pts for (n, ps), pts in m.items() if ps == pos), reverse=True)
                out[(yr, pos)] = v[starters[pos]] if len(v) > starters[pos] else 0.0
        return out

    def repl_table(self, years, n_max=80):
        """{pos: [avg season points of the n-th best at pos, n = 1..n_max]} over `years` —
        lets the site place replacement at any league's first non-starter."""
        out = {}
        for pos in POSITIONS:
            cols = [sorted((p for (n, ps), p in self.pts.get(yr, {}).items() if ps == pos), reverse=True) for yr in years]
            row = []
            for i in range(n_max):
                vals = [c[i] for c in cols if len(c) > i]
                row.append(round(sum(vals) / len(vals), 1) if vals else 0.0)
            out[pos] = row
        return out

    def cur_season(self, key, Y, W):
        """(games, summed component stats) for season Y weeks 1..W."""
        lst = [s for wk, s in self.weekly.get(key, {}).get(Y, []) if wk <= W]
        tot = {k: sum(s[k] for s in lst) for k in STAT_KEYS}
        return len(lst), tot

    def rest_pts(self, key, Y, W):
        """PPR points in season Y after week W (weekly data; None if no weekly record)."""
        wk = self.weekly.get(key, {}).get(Y)
        if wk is None:
            return None
        sc = self.sc_for(key[1])
        return sum(score_rates(s, sc) for w, s in wk if w > W)

    def base_at(self, key, Y, W=0, c=0.0, fill_wks=None, f=1.0):
        """50/30/20 x games core entering Y, with Y weeks 1..W at weight c x games.
        fill_wks / f (10-10, backtest_dyn_fillin_fold.py): season-Y weeks he played as a
        FILL-IN (a regular ahead sat) count at f x that weight; None = every game alike."""
        P = self.players[key]
        rl, wgl = [], []
        g_tot = 0
        for back, w in zip(range(1, 4), W3_WEIGHTS):
            s = P['by'].get(Y - back)
            r = season_rates(s) if s else None
            if r:
                rl.append(r); wgl.append(w * min(s.get('gp') or 0, 17)); g_tot += min(s.get('gp') or 0, 17)
        g_cur = 0
        if W > 0 and c > 0 and fill_wks:
            lst = [(wk, s) for wk, s in self.weekly.get(key, {}).get(Y, []) if wk <= W]
            g_cur = len(lst)
            for grp, wf in ((False, 1.0), (True, f)):
                g = [s for wk, s in lst if (wk in fill_wks) == grp]
                if g and wf > 0:
                    rl.append({k: sum(s[k] for s in g) / len(g) for k in STAT_KEYS}); wgl.append(c * wf * len(g))
            g_tot += g_cur
        elif W > 0 and c > 0:
            g_cur, tot = self.cur_season(key, Y, W)
            if g_cur > 0:
                rl.append({k: tot[k] / g_cur for k in STAT_KEYS}); wgl.append(c * g_cur); g_tot += g_cur
        if not rl or sum(wgl) <= 0:
            return None
        prev = P['by'].get(Y - 1)
        gp1 = min((prev.get('gp') or 0), 17) if prev else 0
        br = blend_rates(rl, wgl)
        sc = self.sc_for(key[1])
        tot = score_rates(br, sc)
        rush = (br['ry'] * sc['ry'] + br['rtd'] * sc['rtd']) / tot if tot > 0 else 0.0
        return tot, gp1, g_cur, max(0.0, min(1.0, rush)), g_tot

    def rows(self, starters, y_last):
        """Preseason comps rows for Y in TRAIN_FROM..y_last (outcomes = full-season VOR)."""
        repl = self.repl(starters)
        self._repl = repl
        rows = []
        for Y in range(TRAIN_FROM, y_last + 1):
            for key, P in self.players.items():
                dr = P['draft']
                rookie = bool(dr and dr[0] == Y)
                prev = P['by'].get(Y - 1)
                if not rookie and not (prev and (prev.get('gp') or 0) >= 1):
                    continue
                age0 = self.age(key, Y)
                if age0 is None:
                    continue
                row = {'key': key, 'pos': key[1], 'Y': Y, 'age0': age0, 'rookie': rookie}
                if rookie:
                    row['pick'] = dr[1]
                else:
                    b = self.base_at(key, Y)
                    if not b:
                        continue
                    row['base'], row['gp1'], row['rush'] = b[0], b[1], b[3]
                    row['rel'] = self.rel(b[0], Y, key[1], b[4])
                row['vor'] = [self.vor(key, Y + k) for k in range(H)]
                row['pts'] = [self.pts[Y + k].get(key, 0.0) if Y + k <= self.last_data else None for k in range(H)]
                rows.append(row)
        return rows

    def rel(self, base, Y, pos, games=None):
        r = max(base, 0.5) / max(self._repl[(Y - 1, pos)] / 17.0, 1.0)
        if self.shrink_g0 and games is not None:
            r = (games * r + self.shrink_g0 * self.shrink_to) / (games + self.shrink_g0)
        return max(r, 0.03)

    def vor(self, key, yr):
        if yr > self.last_data:
            return None
        return max(0.0, self.pts[yr].get(key, 0.0) - self._repl[(yr, key[1])])


class Comps:
    """K-nearest past player-seasons; E[VOR(Y+k)] = mean of their realized VOR(Y'+k)."""

    def __init__(self, rows, last_data, age_scale=None):
        """age_scale: {pos: scale} for the vet age feature (default 2.0).
        QB 6.0 = backtest_dynasty_qb.py (QB age curve is flat): top-QB
        realized/pred 1.27 -> 1.07, W4 whole-pool .580 -> .583."""
        self.last_data = last_data
        self.age_scale = dict(age_scale or {})
        groups = defaultdict(list)
        for r in rows:
            groups[(r['pos'], r['rookie'])].append(r)
        self.G = {}
        self.P = {}
        for g, lst in groups.items():
            Yv = np.array([r['Y'] for r in lst])
            age = np.array([r['age0'] for r in lst], float)
            vm = np.array([[np.nan if v is None else v for v in r['vor']] for r in lst], float)
            keys = np.array([hash(r['key']) for r in lst])
            if g[1]:
                feats = np.stack([np.log(np.array([r['pick'] for r in lst], float)) / 0.35, age / 1.5], 1)
            else:
                feats = np.stack([age / self.age_scale.get(g[0], 2.0), np.log(np.array([r['rel'] for r in lst])) / 0.15,
                                  np.array([r['gp1'] for r in lst], float) / 10.0], 1)
            self.G[g] = (Yv, feats, vm, keys, lst)
            # raw season points (0 = didn't play) for the league-aware distribution read
            if all('pts' in r for r in lst):
                self.P[g] = np.array([[np.nan if v is None else v for v in r['pts']] for r in lst], float)

    QS = (10, 30, 50, 70, 90)

    def ev_dist(self, pos, rookie, f, Y, K=30, exclude_key=None, local_linear=None):
        """Per season k: deciles of the K nearest comps' realized POINTS, shifted so
        their mean matches the local-linear read of points (same pull-to-the-
        middle fix as ev()). VOR for ANY replacement level r is then
        mean(max(0, q - r)) over the deciles — what lets a synced league's own
        replacement levels price every player client-side."""
        Yv, feats, vm, keys, lst = self.G[(pos, rookie)]
        pm = self.P[(pos, rookie)]
        d = ((feats - f) ** 2).sum(1)
        ex = hash(exclude_key) if exclude_key is not None else None
        out = []
        for k in range(H):
            ok = (Yv + k <= min(Y - 1, self.last_data)) & ~np.isnan(pm[:, k])
            if ex is not None:
                ok &= keys != ex
            idx = np.where(ok)[0]
            if not len(idx):
                out.append([0.0] * len(self.QS)); continue
            nn = idx[np.argsort(d[idx])[:K]]
            base = pm[nn, k]
            shift = 0.0
            if local_linear and len(idx) > feats.shape[1] + 5:
                kl, lam = local_linear
                nl = idx[np.argsort(d[idx])[:kl]]
                X = np.hstack([np.ones((len(nl), 1)), feats[nl] - f])
                R = lam * np.eye(X.shape[1]); R[0, 0] = 0.0
                beta = np.linalg.solve(X.T @ X + R, X.T @ pm[nl, k])
                shift = float(beta[0]) - float(base.mean())
            out.append([max(0.0, float(v)) for v in np.percentile(base + shift, self.QS)])
        return out

    @staticmethod
    def vor_from_dist(qs, r):
        return sum(max(0.0, q - r) for q in qs) / len(qs)

    @staticmethod
    def feat_vet(age0, rel, gp1):
        return np.array([age0 / 2.0, math.log(rel) / 0.15, gp1 / 10.0])

    def feat_v(self, pos, age0, rel, gp1):
        """Vet feature vector with this instance's per-position age scale."""
        return np.array([age0 / self.age_scale.get(pos, 2.0), math.log(rel) / 0.15, gp1 / 10.0])

    @staticmethod
    def feat_rookie(pick, age0):
        return np.array([math.log(pick) / 0.35, age0 / 1.5])

    def ev(self, pos, rookie, f, Y, K=30, exclude_key=None, n_comps=0, local_linear=None):
        """[E[VOR(Y+k)]] k=0..H-1 using comps whose Y'+k finished before Y.

        local_linear = (K_ll, ridge): instead of the plain comps mean, fit a
        ridge-regularized linear trend of the outcome on (comp features - f)
        over the K_ll nearest comps and read it at the player (intercept).
        Removes the pull-to-the-middle an average has at the edges of the
        data (elite TEs / QBs have few true peers). Floored at 0.
        """
        Yv, feats, vm, keys, lst = self.G[(pos, rookie)]
        d = ((feats - f) ** 2).sum(1)
        out, comps = [], []
        ex = hash(exclude_key) if exclude_key is not None else None
        for k in range(H):
            ok = (Yv + k <= min(Y - 1, self.last_data)) & ~np.isnan(vm[:, k])
            if ex is not None:
                ok &= keys != ex
            idx = np.where(ok)[0]
            if local_linear and len(idx) > feats.shape[1] + 5:
                kl, lam = local_linear
                nl = idx[np.argsort(d[idx])[:kl]]
                X = np.hstack([np.ones((len(nl), 1)), feats[nl] - f])
                R = lam * np.eye(X.shape[1]); R[0, 0] = 0.0
                beta = np.linalg.solve(X.T @ X + R, X.T @ vm[nl, k])
                out.append(max(0.0, float(beta[0])))
                if k == 0 and n_comps:
                    nn = idx[np.argsort(d[idx])[:K]]
                    comps = [(lst[i]['key'], lst[i]['Y'], float(vm[i, 0])) for i in nn[:n_comps]]
                continue
            nn = idx[np.argsort(d[idx])[:K]]
            out.append(float(vm[nn, k].mean()) if len(nn) else 0.0)
            if k == 0 and n_comps:
                comps = [(lst[i]['key'], lst[i]['Y'], float(vm[i, 0])) for i in nn[:n_comps]]
        return (out, comps) if n_comps else out


# ---------------------------------------------------------------------------
# Conditional JM credit for young players (backtest_dynasty_jm.py,
# research_jm_slow_starters.py, backtest_dynasty_jm_cond.py — Jack 2026-10-09).
# Year 1: rookie prior = (1 - aR) pick comps + aR JM kernel (TE: none).
# Year 2: production comps blended with the JM kernel at aS after a slow rookie
#         season (rel < 1 or < 4 games), aF after a productive one.
# Year 3: a3 unless BOTH earlier seasons were slow (pedigree expired -> 0).
# In-season the year-2/3 weight decays by G0 / (G0 + games this season).
# ---------------------------------------------------------------------------
def load_jm(data_dir=None):
    d = json.load(open(os.path.join(data_dir or DATA_DIR, 'jm_scores.json'), encoding='utf-8'))
    return {(_norm_name(n), v['pos']): v['jm'] for n, v in d['scores'].items() if v.get('jm') is not None}


def season_rel(w, key, yr):
    """(games, PPR points per game vs the year's replacement starter per game) for one season."""
    s = w.players[key]['by'].get(yr) or {}
    g = min(s.get('gp') or 0, 17)
    if g <= 0 or (yr, key[1]) not in w._repl:
        return 0, 0.0
    return g, (w.pts[yr].get(key, 0.0) / g) / max(w._repl[(yr, key[1])] / 17.0, 1.0)


class JMKernel:
    """E[VOR] by career year (0 = rookie season) for a JM score: Gaussian
    kernel on JM within position over drafted classes >= first_class.
    Time-honest by default: only seasons <= Y - 1 are read."""

    def __init__(self, w, jm, first_class=2017, bw=6.0):
        self.w, self.bw = w, bw
        self.recs = defaultdict(list)
        for key, dr in w.draft.items():
            if dr and dr[0] >= first_class and key in jm:
                self.recs[key[1]].append((dr[0], jm[key], key))

    def ev(self, pos, j, Y, ks, exclude_key=None, exclude_class=None, honest=True):
        out = []
        for k in ks:
            num = den = 0.0
            for cls, jj, key in self.recs.get(pos, ()):
                if key == exclude_key or cls == exclude_class:
                    continue
                yr = cls + k
                if yr > self.w.last_data or (honest and yr > Y - 1):
                    continue
                wt = math.exp(-0.5 * ((jj - j) / self.bw) ** 2)
                num += wt * self.w.vor(key, yr); den += wt
            out.append(num / den if den > 0.5 else None)
        return out


# Picked by backtest_dynasty_jm_cond.py (time-honest kernel, FFC pool 2018-23):
# whole-pool T3 .541 -> .554, top-36 73.7% -> 75.2%, T5+youth .533 -> .539,
# week 8 .620 -> .624, SIM x market .591 -> .594. G0 0 = no in-season decay
# (decay tested 2..16: slightly worse). TE: no effect either way -> off.
JM_COND = {'aR': 0.5, 'aS': 0.5, 'aF': 0.2, 'a3': 0.15, 'G0': 0.0, 'te': False}


def jm_cond_weight(w, key, Y, p, g_cur=0):
    """(career year index 0.., weight on the JM kernel) for valuing `key` entering season Y."""
    dr = w.players[key]['draft']
    if not dr:
        return None, 0.0
    cy = Y - dr[0]
    if cy < 0 or cy > 2 or (key[1] == 'TE' and not p.get('te')):
        return cy, 0.0
    if cy == 0:
        return 0, p['aR']
    g1, r1 = season_rel(w, key, dr[0])
    slow1 = g1 < 4 or r1 < 1.0
    if cy == 1:
        a = p['aS'] if slow1 else p['aF']
    else:
        g2, r2 = season_rel(w, key, dr[0] + 1)
        a = 0.0 if (slow1 and (g2 < 4 or r2 < 1.0)) else p['a3']
    if g_cur and p.get('G0'):
        a *= p['G0'] / (p['G0'] + g_cur)
    return cy, a


def jm_blend(ev, J, a):
    return [x if (j is None or a <= 0) else (1 - a) * x + a * j for x, j in zip(ev, J)]
