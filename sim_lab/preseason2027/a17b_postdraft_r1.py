#!/usr/bin/env python3
"""
A17b (research only, 2026-11-24) - post-draft candidate: does the per-game model react enough once the draft is known?
Walk-forward S7 (same harness as A17) with (1) the drafted-competition input rebuilt with team codes mapped and
(2) a separate round-1 flag on top. Graded on veterans 2015-25. Reads only; writes a17b_postdraft_r1.log.
"""
import os, sys, warnings
import numpy as np, pandas as pd
from scipy.stats import spearmanr
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM, pergame_model as G
import a17_vets_vs_draft as A17
LOG = open(os.path.join(HERE, "a17b_postdraft_r1.log"), "w", encoding="utf-8")
def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n")
D = pd.read_parquet(os.path.join(HERE, "data", "rb_a14_D.parquet")).reset_index(drop=True)
D["tc"] = A17.canon(D.team)
dp = pd.read_parquet(os.path.join(PM.CACHE, "draft_picks.parquet"), columns=["season", "round", "pick", "team", "position", "gsis_id"])
dp = dp[dp.position.isin(PM.POS4)].copy(); dp["tc"] = A17.canon(dp.team)
c64, c32 = {}, {}
for r in dp[dp.pick <= 64].itertuples(index=False): c64.setdefault((r.season, r.tc, r.position), []).append(r.gsis_id)
for r in dp[dp["round"] == 1].itertuples(index=False): c32.setdefault((r.season, r.tc, r.position), []).append(r.gsis_id)
fix = [float(any(g != pid for g in c64.get((y, t, p), []))) for y, t, p, pid in zip(D.season, D.tc, D.pos, D.pid)]
r1 = [float(any(g != pid for g in c32.get((y, t, p), []))) for y, t, p, pid in zip(D.season, D.tc, D.pos, D.pid)]
D1 = D.copy(); D1["drafted_comp"] = fix
D2 = D1.copy(); D2["drafted_r1"] = r1
V = {"AS-IS": D.s7, "codes mapped": G.walk(D1, A17.LEAN, "S7", use_role_prior=True)[0], "codes mapped + round-1 flag": G.walk(D2, A17.LEAN + ["drafted_r1"], "S7", use_role_prior=True)[0]}
for k, s in V.items(): D["pg_" + k] = 0.75 * s.values + 0.25 * D.ridge_stats
X = D[(D.rookie == 0) & D.season.isin(A17.YEARS) & D.pg.notna() & (D.pg <= 30)].copy()
X["r1"] = np.array(r1)[X.index]; X["c64"] = np.array(fix)[X.index]
def mae(x, c):
    m = x.act_games >= 4
    return float(np.sum(x.act_games[m] * np.abs(x[c] - x.act_ppg)[m]) / x.act_games[m].sum())
def bias(x, c):
    m = x.act_games >= 4
    return float(np.sum(x.act_games[m] * (x[c] - x.act_ppg)[m]) / x.act_games[m].sum())
P("=== A17b: post-draft drafted-competition input, walk-forward 2015-25, veterans (per-game, games-weighted) ===")
for lab, sub in (("all veterans", X), ("ADP top 150", X[X.adp <= 150]), ("week-1 team took a round-1 pick at the position", X[X.r1 == 1]), ("week-1 team took a top-64 pick", X[X.c64 == 1])):
    P(f"\n  {lab}: MAE / bias; seasons better than AS-IS")
    P("| pos | n | " + " | ".join(V) + " |"); P("|---|---|" + "---|" * len(V))
    for ps in PM.POS4:
        x = sub[sub.pos == ps]
        if len(x) < 8: continue
        o = []
        for k in V:
            w = sum(mae(x[x.season == Y], "pg_" + k) < mae(x[x.season == Y], "pg_AS-IS") for Y in A17.YEARS if ((x.season == Y) & (x.act_games >= 4)).sum() >= 3) if k != "AS-IS" else "-"
            o.append(f"{mae(x, 'pg_' + k):.3f} / {bias(x, 'pg_' + k):+.2f}; {w}")
        P(f"| {ps} | {len(x)} | " + " | ".join(o) + " |")
