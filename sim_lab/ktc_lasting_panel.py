#!/usr/bin/env python3
"""
ktc_lasting_panel.py - the player x date panel for the KTC lasting-value study
(Jack 2026-11-24: "do full study on ktc dynasty ratings as it is public consensus
and lets try to find players that have lasting value to create a rating" /
"players value isnt just based on solely production" / "we want to be able to
beat the market long term").

Rows = every QB/RB/WR/TE on a FULL archived KTC list (pull_ktc_wayback.py; whole
pool that day, so busts and retirees stay in). For each row:
  price   : KTC value / rank / positional rank that day (1QB and superflex)
  future  : KTC value 1, 2, 3, 4, 5 years later (nearest full list within +-45
            days; off the list = 0)
  traits  : everything known THAT DAY - age, experience, draft capital, size,
            trailing production (PPR per game, games, shares, TD reliance,
            rushing share), track record (top-12 / top-24 seasons, best season),
            contract at signing, KTC's own past path (6 / 12 month move, drop
            from peak), crowd keep / trade / cut votes.
Nothing after the anchor date enters a trait.

Output: _dyn_cache/ktc_wb/panel.parquet (+ panel_now.parquet = today's list,
traits only).  Usage: python ktc_lasting_panel.py [--live]
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
import urllib.request

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.join(HERE, '_dyn_cache', 'ktc_wb')
CACHE = os.path.join(os.path.dirname(HERE), 'pbp_cache')
POS = ('QB', 'RB', 'WR', 'TE')
FULL_N = 300            # a list with fewer players is a cut-off (partial) capture
TOL = 45                # days of slack when matching the later list
REPL = {'QB': 17.0, 'RB': 10.5, 'WR': 10.5, 'TE': 8.0}   # PPR per game, 12-team starter line (1QB)


ALIAS = {'jeffery wilson': 'jeff wilson', 'robby anderson': 'robbie chosen', 'gabriel davis': 'gabe davis',
         'kenneth gainwell': 'kenny gainwell', 'josh palmer': 'joshua palmer', 'chigoziem okonkwo': 'chig okonkwo'}


def norm(n):
    s = str(n or '').lower().strip()
    s = ALIAS.get(s, s)
    s = re.sub(r"[.'`]", '', s)
    s = re.sub(r'\s+(jr|sr|iii|ii|iv|v)$', '', s.strip())
    return re.sub(r'[^a-z]', '', s)


def load_snaps(live=False):
    rows, meta = [], []
    files = sorted(glob.glob(os.path.join(WB, 'wb_*.json')))
    if live and os.path.exists(os.path.join(WB, 'live.json')):
        files.append(os.path.join(WB, 'live.json'))
    for f in files:
        P = json.load(open(f, encoding='utf-8'))
        b = os.path.basename(f)
        if b == 'live.json':
            date = dt.date.fromtimestamp(os.path.getmtime(f))
            if any(m['date'] >= date for m in meta):
                continue
        else:
            ts = b[3:11]
            date = dt.date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))
        n = sum(1 for p in P if p.get('position') in POS)
        meta.append({'date': date, 'n': n, 'full': n >= FULL_N, 'file': b})
        for p in P:
            if p.get('position') not in POS:
                continue
            o, s = p.get('oneQBValues') or {}, p.get('superflexValues') or {}
            bd = p.get('birthday')
            try:
                bd = (dt.datetime(1970, 1, 1) + dt.timedelta(seconds=int(bd))).date() if bd not in (None, '') else None
            except (ValueError, OverflowError):
                bd = None
            rows.append({
                'date': date, 'kid': p.get('playerID'), 'name': p.get('playerName'), 'pos': p.get('position'),
                'team': p.get('team'), 'kage': p.get('age'), 'bd': bd, 'exp': p.get('seasonsExperience'),
                'rd': p.get('pickRound'), 'pick': p.get('pickNum'), 'dyear': p.get('draftYear'),
                'ht': (p.get('heightFeet') or 0) * 12 + (p.get('heightInches') or 0), 'wt': p.get('weight'),
                'v1': o.get('value'), 'r1': o.get('rank'), 'pr1': o.get('positionalRank'),
                'vs': s.get('value'), 'rs': s.get('rank'), 'prs': s.get('positionalRank'),
                'kept': o.get('kept'), 'traded': o.get('traded'), 'cut': o.get('cut'),
            })
    S = pd.DataFrame(rows)
    M = pd.DataFrame(meta).sort_values('date').reset_index(drop=True)
    S['date'] = pd.to_datetime(S['date'])
    M['date'] = pd.to_datetime(M['date'])
    return S, M


def player_weeks():
    """2012-2025 table from the preseason work + 2026 built the same way."""
    sys.path.insert(0, os.path.join(HERE, 'preseason2027'))
    W = pd.read_parquet(os.path.join(HERE, 'preseason2027', 'data', 'player_weeks.parquet'))
    f26 = os.path.join(WB, 'player_weeks_2026.parquet')
    pbp26 = os.path.join(CACHE, 'play_by_play_2026.csv.gz')
    if os.path.exists(pbp26) and (not os.path.exists(f26) or os.path.getmtime(f26) < os.path.getmtime(pbp26)):
        import build_player_weeks as B
        w26, _ = B.season(2026)
        pl = pd.read_csv(os.path.join(CACHE, 'players.csv'), low_memory=False,
                         usecols=['gsis_id', 'display_name', 'position', 'birth_date', 'rookie_season', 'draft_year',
                                  'draft_round', 'draft_pick'])
        pl = pl[pl.gsis_id.notna()].drop_duplicates('gsis_id').rename(columns={'gsis_id': 'pid'})
        w26 = w26.merge(pl, on='pid', how='left')
        POV = B.position_overrides()
        w26['position'] = [POV.get((p, 2026)) or ps for p, ps in zip(w26.pid, w26.position)]
        w26 = w26[w26.position.isin(['QB', 'RB', 'WR', 'TE', 'FB'])].copy()
        w26.loc[w26.position == 'FB', 'position'] = 'RB'
        w26.to_parquet(f26, index=False)
    if os.path.exists(f26):
        W = pd.concat([W, pd.read_parquet(f26)], ignore_index=True)
    G = pd.read_csv(os.path.join(CACHE, 'schedules_games.csv'), usecols=['game_id', 'gameday'])
    W = W.merge(G, on='game_id', how='left')
    W['gameday'] = pd.to_datetime(W['gameday'])
    # fallback date for any game missing from the schedule file
    miss = W.gameday.isna()
    if miss.any():
        W.loc[miss, 'gameday'] = pd.to_datetime(W.loc[miss, 'season'].astype(str) + '-09-08') + pd.to_timedelta(
            (W.loc[miss, 'week'] - 1) * 7, unit='D')
    return W


def link_ids(S, W):
    """KTC playerID -> gsis id by name + position, birth year breaking ties."""
    pl = pd.read_csv(os.path.join(CACHE, 'players.csv'), low_memory=False,
                     usecols=['gsis_id', 'display_name', 'position', 'birth_date', 'rookie_season', 'last_season'])
    pl = pl[pl.gsis_id.notna() & (pl.position.isin(['QB', 'RB', 'WR', 'TE', 'FB', 'HB'])
                                  | pl.display_name.isin(['Travis Hunter']))].copy()
    pl['k'] = pl.display_name.map(norm)
    pl['by'] = pd.to_datetime(pl.birth_date, errors='coerce').dt.year
    by_name = {}
    for r in pl.itertuples(index=False):
        by_name.setdefault(r.k, []).append(r)
    K = S.sort_values('date').drop_duplicates('kid', keep='last')
    out = {}
    for r in K.itertuples(index=False):
        c = by_name.get(norm(r.name), [])
        if len(c) > 1:
            y = r.bd.year if r.bd is not None and not pd.isna(r.bd) else None
            c2 = [x for x in c if y and x.by == y] or [x for x in c if x.position == r.pos] or c
            c2 = sorted(c2, key=lambda x: -(x.last_season if not pd.isna(x.last_season) else 0))
            c = c2
        if c:
            out[r.kid] = c[0].gsis_id
    return out


def season_ranks(W):
    """{(pid, season): (pos rank by PPR total, games, ppg)} for completed seasons."""
    T = W.groupby(['pid', 'season', 'position']).agg(pts=('ppr', 'sum'), g=('ppr', 'size')).reset_index()
    T['rk'] = T.groupby(['season', 'position']).pts.rank(ascending=False, method='min')
    T['ppg'] = T.pts / T.g
    return T


def traits(S, W, gsis):
    global DATA_END
    W = W.sort_values('gameday')
    DATA_END = W.gameday.max()
    byp = {p: g for p, g in W.groupby('pid')}
    SR = season_ranks(W)
    srp = {p: g for p, g in SR.groupby('pid')}
    last_day = W.groupby('season').gameday.max().to_dict()
    C = pd.read_parquet(os.path.join(CACHE, 'historical_contracts.parquet'),
                        columns=['gsis_id', 'year_signed', 'years', 'apy_cap_pct', 'guaranteed', 'value'])
    C = C[C.gsis_id.notna()]
    cbp = {p: g.sort_values('year_signed') for p, g in C.groupby('gsis_id')}
    out = []
    for r in S.itertuples(index=False):
        d = {}
        T = r.date
        bd = pd.Timestamp(r.bd) if r.bd is not None and not pd.isna(r.bd) else None
        d['age'] = (T - bd).days / 365.25 if bd is not None else (float(r.kage) + 0.5 if r.kage else np.nan)
        pid = gsis.get(r.kid)
        d['gsis'] = pid
        g = byp.get(pid)
        repl = REPL[r.pos]
        for k in ('ppg1', 'g1', 'ppg2', 'g2', 'ppg3', 'g3', 'tgt_sh', 'car_sh', 'td_sh', 'rush_sh', 'par1', 'vor1',
                  'best_ppg', 'top12', 'top24', 'cg', 'ppg_car'):
            d[k] = np.nan
        d['g1'] = d['g2'] = d['g3'] = d['cg'] = 0.0
        d['top12'] = d['top24'] = 0.0
        # TARGET side (never a trait): points over the starter line scored in each later
        # 12-month block = what he pays you while you hold him. NaN past the end of the data.
        for i in (1, 2, 3):
            hi = T + pd.Timedelta(days=365 * i)
            if hi > DATA_END:
                d['vf%d' % i] = np.nan; d['gf%d' % i] = np.nan
            elif g is None:
                d['vf%d' % i] = 0.0; d['gf%d' % i] = 0.0
            else:
                w = g[(g.gameday >= T) & (g.gameday < hi) & (g.gameday > T + pd.Timedelta(days=365 * (i - 1)) - pd.Timedelta(days=1))]
                d['vf%d' % i] = float(max(0.0, (w.ppr - repl).sum())); d['gf%d' % i] = float(len(w))
        if g is not None:
            g = g[g.gameday < T]
            if len(g):
                d['cg'] = float(len(g))
                d['ppg_car'] = float(g.ppr.mean())
                for i, (a, b) in enumerate(((0, 365), (365, 730), (730, 1095)), 1):
                    w = g[(g.gameday >= T - pd.Timedelta(days=b)) & (g.gameday < T - pd.Timedelta(days=a))]
                    d['g%d' % i] = float(len(w))
                    if len(w):
                        d['ppg%d' % i] = float(w.ppr.mean())
                    if i == 1 and len(w):
                        tt, tc = w.team_tgt.sum(), w.team_car.sum()
                        d['tgt_sh'] = float(w.tgt.sum() / tt) if tt else np.nan
                        d['car_sh'] = float(w.car.sum() / tc) if tc else np.nan
                        tot = w.ppr.sum()
                        if tot > 0:
                            d['td_sh'] = float((6 * (w.rtd.sum() + w.ctd.sum()) + 4 * w.ptd.sum()) / tot)
                            d['rush_sh'] = float((.1 * w.ryd.sum() + 6 * w.rtd.sum()) / tot)
                        d['par1'] = d['ppg1'] - repl
                        d['vor1'] = max(0.0, d['par1']) * len(w)
            sr = srp.get(pid)
            if sr is not None:
                done = sr[[last_day[s] < T for s in sr.season]]
                if len(done):
                    q = done[done.g >= 6]
                    d['best_ppg'] = float(q.ppg.max()) if len(q) else np.nan
                    d['top12'] = float((done.rk <= 12).sum())
                    d['top24'] = float((done.rk <= 24).sum())
        # contract in force (at-signing fields only; signing year known by the anchor date)
        d['cap_pct'] = np.nan; d['c_left'] = np.nan; d['vet_deal'] = 0.0
        c = cbp.get(pid)
        if c is not None:
            yr = T.year if T.month >= 4 else T.year - 1   # league year
            c = c[c.year_signed <= yr]
            if len(c):
                x = c.iloc[-1]
                yrs = x.years if not pd.isna(x.years) else 1
                d['cap_pct'] = float(x.apy_cap_pct) if not pd.isna(x.apy_cap_pct) else np.nan
                d['c_left'] = float(max(0, x.year_signed + yrs - 1 - yr))
                d['vet_deal'] = float(len(c) > 1)
        out.append(d)
    return pd.concat([S.reset_index(drop=True), pd.DataFrame(out)], axis=1)


def normalize(P, M):
    """KTC's scale drifts (the 300th player: 291 in Jan 2021, 1,781 in Jul 2026), so raw values
    are not comparable across dates. Rank is. n1 / ns = the value KTC gives that RANK (players
    only, picks removed) on the reference curve = mean sorted curve of the 2025-26 full lists.
    Off the list later = 0. k1 / ks = that players-only rank."""
    ref = {}
    for fmt, k, n in (('v1', 'k1', 'n1'), ('vs', 'ks', 'ns')):
        P[k] = P.groupby('date')[fmt].rank(ascending=False, method='first')
        dates = M[M.full & (M.date >= '2025-01-01')].date
        curves = [np.sort(P.loc[P.date == d, fmt].to_numpy())[::-1][:450] for d in dates]
        curves = [c for c in curves if len(c) == 450]
        ref[fmt] = np.mean(curves, axis=0)
        r = P[k].to_numpy().astype(int)
        P[n] = np.where(r <= 450, ref[fmt][np.clip(r, 1, 450) - 1], 0.0)
    P.loc[P.age < 18, 'age'] = np.nan
    P.loc[P.wt <= 0, 'wt'] = np.nan
    P.loc[P.ht <= 0, 'ht'] = np.nan
    pl = pd.read_csv(os.path.join(CACHE, 'players.csv'), low_memory=False, usecols=['gsis_id', 'draft_pick', 'rookie_season'])
    pl = pl[pl.gsis_id.notna()].drop_duplicates('gsis_id').set_index('gsis_id')
    dp = P.gsis.map(pl.draft_pick)
    fb = np.where((P.rd.fillna(0) > 0) & (P['pick'].fillna(0) > 0), (P.rd.fillna(0) - 1) * 32 + P['pick'].fillna(0), np.nan)
    P['opick'] = dp.fillna(pd.Series(fb, index=P.index)).fillna(262.0)
    P['rook_yr'] = P.gsis.map(pl.rookie_season).fillna(P.dyear)
    json.dump({k: [float(x) for x in v] for k, v in ref.items()}, open(os.path.join(WB, 'ref_curve.json'), 'w'))
    return P


def ktc_path(P, M):
    """KTC's own past for each row: value 6 / 12 months back and the peak so far."""
    full = M[M.full].date.tolist()
    P = P.sort_values(['kid', 'date']).reset_index(drop=True)
    piv = {fmt: P.pivot_table(index='kid', columns='date', values=fmt, aggfunc='first') for fmt in ('n1', 'ns')}

    def nearest(target, before=None):
        c = [x for x in full if abs((x - target).days) <= TOL and (before is None or x < before)]
        return min(c, key=lambda x: abs((x - target).days)) if c else None

    for fmt in ('n1', 'ns'):
        tab = piv[fmt]
        cols = sorted(tab.columns)
        for lab, days in (('m6', 182), ('m12', 365)):
            res = np.full(len(P), np.nan)
            for dte, idx in P.groupby('date').groups.items():
                nb = nearest(dte - pd.Timedelta(days=days), before=dte)
                if nb is None or nb not in tab.columns:
                    continue
                prev = tab[nb].reindex(P.loc[idx, 'kid']).to_numpy()
                res[idx] = prev
            P['%s_%s' % (fmt, lab)] = res      # NaN = not on that earlier list (or no list)
        pk = np.full(len(P), np.nan)
        for dte, idx in P.groupby('date').groups.items():
            past = [c for c in cols if c < dte]
            if past:
                pk[idx] = tab[past].max(axis=1).reindex(P.loc[idx, 'kid']).to_numpy()
        P['%s_peak' % fmt] = pk
    return P


def futures(P, M):
    full = M[M.full].date.tolist()
    for fmt in ('n1', 'ns'):
        tab = P.pivot_table(index='kid', columns='date', values=fmt, aggfunc='first')
        rk = P.pivot_table(index='kid', columns='date', values='k1' if fmt == 'n1' else 'ks', aggfunc='first')
        for h in (1, 2, 3, 4, 5):
            res = np.full(len(P), np.nan)
            rres = np.full(len(P), np.nan)
            for dte, idx in P.groupby('date').groups.items():
                tgt = dte + pd.Timedelta(days=365 * h)
                c = [x for x in full if abs((x - tgt).days) <= TOL]
                if not c:
                    continue
                nb = min(c, key=lambda x: abs((x - tgt).days))
                res[idx] = tab[nb].reindex(P.loc[idx, 'kid']).fillna(0).to_numpy()
                rres[idx] = rk[nb].reindex(P.loc[idx, 'kid']).to_numpy()
            P['%s_f%d' % (fmt, h)] = res
            P['%s_fr%d' % (fmt, h)] = rres
    return P


def fetch_live():
    req = urllib.request.Request('https://keeptradecut.com/dynasty-rankings',
                                 headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36',
                                          'Accept': 'text/html'})
    html = urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'replace')
    sys.path.insert(0, HERE)
    import pull_ktc_wayback as PW
    P = PW.parse(html)
    json.dump([PW.slim(p) for p in P], open(os.path.join(WB, 'live.json'), 'w', encoding='utf-8'))
    return len(P)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--live', action='store_true', help='also pull today\'s KTC list for the "now" table')
    a = ap.parse_args()
    if a.live and not os.path.exists(os.path.join(WB, 'live.json')):
        print('live KTC list:', fetch_live(), 'entries')
    S, M = load_snaps(live=a.live)
    print(M.assign(date=M.date.dt.date).to_string())
    W = player_weeks()
    gsis = link_ids(S, W)
    print('KTC ids %d, linked to nflverse %d' % (S.kid.nunique(), len(gsis)))
    P = traits(S, W, gsis)
    P = normalize(P, M)
    P = ktc_path(P, M)
    P = futures(P, M)
    P = P.merge(M[['date', 'full']], on='date', how='left')
    P['bd'] = pd.to_datetime(P['bd'])
    P.to_parquet(os.path.join(WB, 'panel.parquet'), index=False)
    print('panel rows %d (full-list rows %d), dates %d' % (len(P), int(P.full.sum()), P.date.nunique()))
    for h in (1, 2, 3, 4, 5):
        x = P[P.full & P['n1_f%d' % h].notna()]
        print('  horizon %dy: %d rows, %d anchor dates, %d players' % (h, len(x), x.date.nunique(), x.kid.nunique()))
    unl = P[P.gsis.isna() & (P.v1 > 3000)].drop_duplicates('kid')[['name', 'pos', 'date', 'v1']]
    print('unlinked with value > 3000:', len(unl))
    print(unl.head(25).to_string())


if __name__ == '__main__':
    main()
