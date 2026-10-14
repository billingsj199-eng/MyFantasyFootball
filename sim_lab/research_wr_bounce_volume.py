#!/usr/bin/env python3
"""
research_wr_bounce_volume.py — which VOLUME / ROLE signals pick slow-rookie-year WR
bounce-backs? (Jack 2026-10-10: "test the wr bounce back volume signals", after
backtest_jm_bounce.py found MFF VALUE's WR bounce-back AUC = .50.)

Population: every WR drafted 2018-2022 (draft_picks) whose rookie year was slow
(< 4 games or below replacement per game, dyn_common.season_rel); year 2 = 2019-2023
(ctx_features.parquet coverage). BOUNCE-BACK = a top-24 WR PPR season in year 2, 3 or 4.
Signals (+ = expected to help):
  pedigree   pk = -log pick, jm = JM score
  PRESEASON (known before year 2): vac = team vacated target share, vac_same = vacated
             WR/TE share at his slot, new_hc, new_pc (play-caller), moved (team change),
             dc1 = week-1 depth chart starter (depth_team 1)
  EARLY YEAR 2 (through week 4, ctx row for week 5 = season-to-date before it):
             tgt4 target share, snap4 snap % in week 4, xfp4 expected PPR/g, wopr4
Tests: AUC of each signal alone; leave-one-year-out logistic AUC of pedigree vs
pedigree + signal; then inside MFF VALUE's FFC pool (slow-rookie WRs 2019-23):
AUC of FAIR rank vs FAIR + the best early signal.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import World, FORMATS, season_rel, load_jm, _norm_name  # noqa: E402

PBP = r'E:\MyFantasyFootball\pbp_cache'


def auc(s, y):
    s, y = np.asarray(s, float), np.asarray(y, bool)
    ok = ~np.isnan(s)
    s, y = s[ok], y[ok]
    p, n = s[y], s[~y]
    if not len(p) or not len(n):
        return float('nan')
    return float(((p[:, None] > n[None, :]).sum() + 0.5 * (p[:, None] == n[None, :]).sum()) / (len(p) * len(n)))


def logit_fit(X, y, lam=1.0):
    b = np.zeros(X.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-X @ b))
        g = X.T @ (y - p) - lam * np.r_[0, b[1:]]
        H = -(X.T * (p * (1 - p))) @ X - lam * np.diag(np.r_[0, np.ones(len(b) - 1)])
        b = b - np.linalg.solve(H, g)
    return b


# Position from argv (Jack 10-10 'test te bounce back volume signals'): WR (default) or TE;
# bounce-back = top-24 WR / top-12 TE season in years 2-4. TEs get no JM credit in the
# shipped sim (JM_COND te False), so the in-season sim skips it for TE.
POS = (sys.argv[1] if len(sys.argv) > 1 else 'WR').upper()
CUT = {'WR': 24, 'TE': 12}[POS]


def main():
    w = World(2025)
    w.rows(FORMATS['1qb'], 2025)
    jm = load_jm()
    # WR season ranks
    wr_rank = defaultdict(dict)
    for yr, d in w.pts.items():
        lst = sorted(((v, k) for k, v in d.items() if k[1] == POS), reverse=True)
        for i, (_, k) in enumerate(lst):
            wr_rank[yr][k] = i + 1
    ctx = pd.read_parquet(os.path.join(HERE, 'ctx_features.parquet'))
    ctx = ctx[ctx.pos == POS]
    ctx['key'] = [(_norm_name(n), POS) for n in ctx.name]
    first = {(r.key, r.year): r for r in ctx.sort_values('wk').groupby(['key', 'year']).head(1).itertuples()}
    # first row from week 5 on = season-to-date through week 4 (a week-5 bye / absence has no wk-5 row)
    wk5 = {(r.key, r.year): r for r in ctx[ctx.wk >= 5].sort_values('wk').groupby(['key', 'year']).head(1).itertuples()}
    dc1 = {}
    for Y in range(2019, 2024):
        d = pd.read_parquet(os.path.join(PBP, f'depth_charts_{Y}.parquet'), columns=['week', 'game_type', 'position', 'depth_team', 'full_name'])
        d = d[(d.game_type == 'REG') & (d.position == POS)]
        d = d[d.week == d.week.min()]
        for n, t in zip(d.full_name, d.depth_team):
            k = (_norm_name(n), POS)
            dc1[(k, Y)] = min(dc1.get((k, Y), 9), int(t) if str(t).isdigit() else 9)
    import early_tgt_share
    cand = [(k, P['draft'][0] + 1) for k, P in w.players.items()
            if k[1] == POS and P.get('draft') and 2018 <= P['draft'][0] <= 2022]
    esh = early_tgt_share.build(w, cand, 4)   # target share from game logs + pbp team targets
    rows = []
    for k, P in w.players.items():
        dr = P.get('draft')
        if k[1] != POS or not dr or not (2018 <= dr[0] <= 2022):
            continue
        g1, r1 = season_rel(w, k, dr[0])
        if not (g1 < 4 or r1 < 1.0):
            continue
        Y = dr[0] + 1
        bo = any(wr_rank.get(Y + i, {}).get(k, 999) <= CUT for i in range(3))
        f, e = first.get((k, Y)), wk5.get((k, Y))
        rows.append({'key': k, 'Y': Y, 'pick': dr[1], 'bo': bo, 'rel1': r1, 'g1': g1,
                     'pk': -math.log(dr[1]), 'jm': jm.get(k, np.nan),
                     'vac': f.vac_tgt if f is not None else np.nan, 'vac_same': f.vac_tgt_same if f is not None else np.nan,
                     'new_hc': f.new_hc if f is not None else np.nan, 'new_pc': f.new_pc if f is not None else np.nan,
                     'moved': f.team_change if f is not None else np.nan,
                     'dc1': (1.0 if dc1.get((k, Y), 9) == 1 else 0.0) if (k, Y) in dc1 else 0.0,
                     'tgt4': (esh.get((k, Y)) or (None,))[0] or 0.0, 'snap4': e.snap_l1 if e is not None else 0.0,
                     'xfp4': e.xfp_pg if e is not None else 0.0, 'wopr4': e.wopr if e is not None else 0.0})
    df = pd.DataFrame(rows)
    print(f'slow-rookie WRs drafted 2018-22: {len(df)}, bounced back {int(df.bo.sum())} '
          f'({df.bo.mean():.0%}); picks 1-64: {int((df.pick <= 64).sum())} ({df[df.pick <= 64].bo.mean():.0%} bounced)')
    sig = ['pk', 'jm', 'vac', 'vac_same', 'new_hc', 'new_pc', 'moved', 'dc1', 'tgt4', 'snap4', 'xfp4', 'wopr4']
    print('\n=== signal alone: AUC for bounce-back (all / picks 1-100) ===')
    for s in sig:
        top = df[df.pick <= 100]
        print(f'  {s:<9} all {auc(df[s], df.bo):.3f}   picks<=100 {auc(top[s], top.bo):.3f}   n {int(df[s].notna().sum())}')
    print('\n=== beyond pedigree: leave-one-year-out logistic AUC, base = pk + jm (jm missing -> group mean) ===')
    d = df.copy()
    d['jm'] = d.jm.fillna(d.jm.mean())
    for s in sig[2:]:
        d[s] = d[s].fillna(d[s].mean())
    def loyo(cols):
        pred = np.zeros(len(d))
        for Y in sorted(d.Y.unique()):
            tr, te = d.Y != Y, d.Y == Y
            mu, sd = d.loc[tr, cols].mean(), d.loc[tr, cols].std().replace(0, 1)
            X = np.c_[np.ones(tr.sum()), ((d.loc[tr, cols] - mu) / sd).values]
            b = logit_fit(X, d.loc[tr, 'bo'].values.astype(float))
            Xt = np.c_[np.ones(te.sum()), ((d.loc[te, cols] - mu) / sd).values]
            pred[te.values] = Xt @ b
        return auc(pred, d.bo)
    base = loyo(['pk', 'jm'])
    print(f'  base pk+jm: {base:.3f}')
    for s in sig[2:]:
        print(f'  + {s:<9} {loyo(["pk", "jm", s]):.3f}')
    print(f'  + early (tgt4+snap4+xfp4): {loyo(["pk", "jm", "tgt4", "snap4", "xfp4"]):.3f}')
    print(f'  + preseason (vac+vac_same+new_pc+dc1): {loyo(["pk", "jm", "vac", "vac_same", "new_pc", "dc1"]):.3f}')
    print('\n=== bounce-back rate by early target share (through week 4 of year 2) ===')
    for lo, hi in ((0, 0.05), (0.05, 0.12), (0.12, 0.18), (0.18, 1.0)):
        g = df[(df.tgt4 >= lo) & (df.tgt4 < hi)]
        print(f'  tgt share {lo:.2f}-{hi:.2f}: n {len(g):<3} bounced {g.bo.mean():.0%}  ' + ', '.join(
            f'{k[0]} {Y}' for k, Y, b in zip(g.key, g.Y, g.bo) if b)[:160])
    df.to_pickle(os.path.join(HERE, '_dyn_cache', POS.lower() + '_bounce_rows.pkl'))


if __name__ == '__main__':
    main()
