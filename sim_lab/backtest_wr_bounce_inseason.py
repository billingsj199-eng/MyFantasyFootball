#!/usr/bin/env python3
"""
backtest_wr_bounce_inseason.py — does week-4 TARGET SHARE add to the IN-SEASON Dynasty
SIM for year-2 WRs coming off a slow rookie year? (Jack 2026-10-10: "run the in-season
test" + "back test too"; follows research_wr_bounce_volume.py.)

Population: every WR drafted 2018-2022 with a slow rookie year (< 4 games or below
replacement per game), valued after WEEK 4 of year 2 (Y = 2019-2023).
SIM @ W4 = the shipped in-season form (build_dynasty_sim.py): vet comps on the
50/30/20 base with year-2 weeks 1-4 folded in at c = 2 x games (World.base_at),
local-linear comps K120 ridge 5, JM conditional credit aS .5 (slow rookie yr,
time-honest kernel), value = y0 x 14/18 + y1 + y2 + 1.5 x (y3 + y4).
SIGNAL = target share weeks 1-4 of year 2 (ctx_features wk-5 row, season-to-date);
no row (didn't play) = 0.
LAYER = rank by log(SIM + 1) + k x z(tgt4); k chosen leave-one-year-out (5 folds)
on the group's per-year Spearman vs T3, then scored held-out.
Truth: T3 = rest-of-Y VOR + Y+1 + Y+2 (1QB PPR); T5 = T3 + 1.5 x (Y+3 + Y+4) where
complete; BOUNCE = top-24 WR season in Y..Y+2.
"""
import math
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dyn_common import (World, Comps, FORMATS, WEEKS, season_rel, load_jm, JMKernel,  # noqa: E402
                        jm_blend, _norm_name)
from backtest_js_model import spearman  # noqa: E402

W = 4
LL = (120, 5.0)
YW = 1.5
AS = 0.5
K = [0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0, 1.5]


def auc(s, y):
    s, y = np.asarray(s, float), np.asarray(y, bool)
    p, n = s[y], s[~y]
    if not len(p) or not len(n):
        return float('nan')
    return float(((p[:, None] > n[None, :]).sum() + 0.5 * (p[:, None] == n[None, :]).sum()) / (len(p) * len(n)))


# Position from argv (Jack 10-10 'test te bounce back volume signals'): WR (default) or TE;
# bounce-back = top-24 WR / top-12 TE season in years 2-4. TEs get no JM credit in the
# shipped sim (JM_COND te False), so the in-season sim skips it for TE.
POS = (sys.argv[1] if len(sys.argv) > 1 else 'WR').upper()
CUT = {'WR': 24, 'TE': 12}[POS]


def main():
    w = World(2025)
    rows = w.rows(FORMATS['1qb'], 2025)
    comps = Comps(rows, 2025, {'QB': 6.0})
    repl = w._repl
    jm = load_jm()
    kern = JMKernel(w, jm)
    age0 = {(r['key'], r['Y']): r['age0'] for r in rows}
    wr_rank = defaultdict(dict)
    for yr, d in w.pts.items():
        for i, (_, k) in enumerate(sorted(((v, k) for k, v in d.items() if k[1] == POS), reverse=True)):
            wr_rank[yr][k] = i + 1
    ctx = pd.read_parquet(os.path.join(HERE, 'ctx_features.parquet'))
    ctx = ctx[(ctx.pos == POS) & (ctx.wk == W + 1)]
    import early_tgt_share   # game logs + pbp team targets (ctx wk-5 rows miss byes / absences)
    cand = [(k, P['draft'][0] + 1) for k, P in w.players.items()
            if k[1] == POS and P.get('draft') and 2018 <= P['draft'][0] <= 2022]
    tgt = {kk: (v[0] or 0.0) for kk, v in early_tgt_share.build(w, cand, W).items()}
    frac = (WEEKS - W) / WEEKS
    out = []
    for k, P in w.players.items():
        dr = P.get('draft')
        if k[1] != POS or not dr or not (2018 <= dr[0] <= 2022):
            continue
        g1, r1 = season_rel(w, k, dr[0])
        if not (g1 < 4 or r1 < 1.0):
            continue
        Y = dr[0] + 1
        a0 = age0.get((k, Y))
        if a0 is None:
            by = P.get('birth')
            a0 = (Y - int(str(by)[:4])) if by else 23   # birth may be 'YYYY' or 'YYYY-MM'
        b = w.base_at(k, Y, W, 2.0)
        if b is None:   # no NFL games at all yet -> no production base (the live build skips these)
            ev = [0.0] * 5
        else:
            ev = comps.ev(POS, False, comps.feat_v(POS, a0, w.rel(b[0], Y, POS), b[1]), Y, exclude_key=k, local_linear=LL)
        if k in jm and POS != 'TE':
            ev = jm_blend(ev, kern.ev(POS, jm[k], Y, range(1, 6), exclude_key=k), AS)
        sim = ev[0] * frac + ev[1] + ev[2] + YW * (ev[3] + ev[4])
        rest = w.rest_pts(k, Y, W)
        if rest is None:
            rest = w.pts[Y].get(k, 0.0) * frac
        vor = lambda yy: max(0.0, w.pts.get(yy, {}).get(k, 0.0) - repl[(yy, POS)]) if (yy, POS) in repl else None
        t3 = max(0.0, rest - repl[(Y, POS)] * frac) + (vor(Y + 1) or 0) + (vor(Y + 2) or 0)
        t5 = t3 + YW * ((vor(Y + 3) or 0) + (vor(Y + 4) or 0)) if Y + 4 <= 2025 else None
        out.append({'key': k, 'Y': Y, 'pick': dr[1], 'sim': sim, 'tgt4': tgt.get((k, Y), 0.0), 't3': t3, 't5': t5,
                    'bo': any(wr_rank.get(Y + i, {}).get(k, 999) <= CUT for i in range(3))})
    df = pd.DataFrame(out)
    YRS = sorted(df.Y.unique())
    print(f'slow-rookie year-2 WRs valued at week {W}: {len(df)} ({YRS[0]}-{YRS[-1]}), bounced back {int(df.bo.sum())}')
    mu, sd = df.tgt4.mean(), df.tgt4.std()
    df['z'] = (df.tgt4 - mu) / sd
    df['ls'] = np.log(df.sim.clip(lower=0) + 1)

    def per_year(k, truth):
        res = []
        for Y in YRS:
            g = df[df.Y == Y]
            if truth == 't5' and g.t5.isna().any():
                continue
            s = spearman(list(g.ls + k * g.z), list(g[truth]))
            res.append(np.nan if s is None else s)   # None = a constant column that year
        return np.array(res, float)

    print('\nper-year Spearman within the group (mean over years) by k:')
    for kk in K:
        print(f"  k {kk:<5} T3 {np.nanmean(per_year(kk, 't3')):.3f}   T5 {np.nanmean(per_year(kk, 't5')):.3f}   "
              f'bounce AUC {auc(df.ls + kk * df.z, df.bo):.3f}')
    print(f'  tgt4 alone: T3 {np.nanmean([np.nan if (v := spearman(list(df[df.Y == Y].tgt4), list(df[df.Y == Y].t3))) is None else v for Y in YRS]):.3f}'
          f'   bounce AUC {auc(df.tgt4, df.bo):.3f}')
    S3 = {kk: per_year(kk, 't3') for kk in K}
    d, picks, preds = [], [], np.zeros(len(df))
    for i, Y in enumerate(YRS):
        kb = max(K, key=lambda kk: np.nanmean(np.delete(S3[kk], i))); picks.append(kb)
        d.append(np.nan_to_num(S3[kb][i] - S3[0][i]))
        m = (df.Y == Y).values
        preds[m] = (df.ls + kb * df.z).values[m]
    print(f'\nLOYO (k picked on T3 of the other years): picks {picks}')
    print(f'  held-out T3 Spearman gain {np.mean(d):+.4f} ({sum(x > 1e-9 for x in d)}/{len(YRS)})')
    y5 = [Y for Y in YRS if not df[df.Y == Y].t5.isna().any()]
    d5 = [(spearman(list(preds[(df.Y == Y).values]), list(df[df.Y == Y].t5)) or 0) - (spearman(list(df[df.Y == Y].ls), list(df[df.Y == Y].t5)) or 0) for Y in y5]
    print(f'  held-out T5 Spearman gain {np.mean(d5):+.4f} ({sum(x > 1e-9 for x in d5)}/{len(y5)})')
    print(f'  bounce AUC: SIM {auc(df.ls, df.bo):.3f} -> SIM + tgt4 (held-out k) {auc(preds, df.bo):.3f}')
    print('\nbounce-backs: SIM rank in group (held-out layer rank) — tgt4')
    for Y in YRS:
        g = df[df.Y == Y].copy()
        g['r0'] = g.ls.rank(ascending=False).astype(int)
        g['r1'] = pd.Series(preds[(df.Y == Y).values], index=g.index).rank(ascending=False).astype(int)
        for r in g[g.bo].itertuples():
            print(f'   {Y} {r.key[0]:<22} pick {r.pick:<4} of {len(g):<3} SIM #{r.r0:<4} layer #{r.r1:<4} tgt4 {r.tgt4:.2f}')


if __name__ == '__main__':
    main()
