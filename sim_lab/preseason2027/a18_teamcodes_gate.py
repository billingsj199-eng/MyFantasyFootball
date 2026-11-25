#!/usr/bin/env python3
"""
A18 gate (2026-11-24) - before / after the team-code mapping fix in preseason_model.ALIAS.

Before = the four backtests (games_model, pergame_model, qb_a11, qb_a13) rerun on the code as it stood
(_gate_teamcodes/pre_*), after = the same four rerun with the mapping in place (_gate_teamcodes/post_*).
Same switches and constants; only ALIAS differs. Two extra per-game runs split the mapping into its two code
families (pfr_only = the draft-pick codes, roster_only = the 2012-15 roster codes) to show where a change comes from.
Prints, per position: pooled numbers, per-season wins and a paired per-season t statistic (season-to-season noise),
so "worse by more than noise" is a number, not a judgement.

Gate (fixed before the after-run was looked at): a position FAILS if the after-run is worse on per-game MAE with a
paired per-season t above +1.81 (one-sided 5%, 10 df) in either the ADP top-150 pool or the all-veterans pool.

  python a18_teamcodes_gate.py   -> a18_teamcodes_gate.log
"""
import os, sys, warnings
import numpy as np, pandas as pd
from scipy.stats import spearmanr
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); G = os.path.join(HERE, "_gate_teamcodes")
POS4 = ("QB", "RB", "WR", "TE"); YEARS = list(range(2015, 2026))
LOG = open(os.path.join(HERE, "a18_teamcodes_gate.log"), "w", encoding="utf-8")
def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n")


def wmae(x, c):
    m = (x.act_games >= 4) & x[c].notna()
    return float(np.sum(x.act_games[m] * np.abs(x[c] - x.act_ppg)[m]) / x.act_games[m].sum()) if m.sum() else np.nan


def rho(x, c):
    m = (x.act_games >= 4) & x[c].notna()
    v = [spearmanr(g[c], g.act_ppg).correlation for _, g in x[m].groupby("season") if len(g) >= 8]
    return float(np.nanmean(v)) if v else np.nan


def paired(a, b, fn, c):
    """per-season metric after minus before: wins (after better), mean diff, t."""
    d = []
    for Y in YEARS:
        xa, xb = a[a.season == Y], b[b.season == Y]
        if ((xa.act_games >= 4) & xa[c].notna()).sum() < 3: continue
        d.append(fn(xb, c) - fn(xa, c))
    d = np.array(d); t = d.mean() / (d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 and d.std(ddof=1) > 0 else 0.0
    return int((d < 0).sum()), len(d), float(d.mean()), float(t)


def pergame_tables(pre, post, tag, fails=None):
    C = "S6 blend"
    for lab, f in (("ADP top 150 (all players, as the per-game log grades)", lambda x: x[(x.adp <= 150)]), ("all veterans", lambda x: x[x.rookie == 0]), ("everyone with a projection", lambda x: x)):
        P(f"\n  [{tag}] per-game S6 blend, {lab}, 2015-25: MAE / rank corr before -> after; seasons after is better; mean per-season change; paired t")
        P("| pos | n (4+ g) | before | after | seasons better | mean change | t |"); P("|---|---|---|---|---|---|---|")
        for ps in POS4 + ("ALL",):
            a = f(pre[pre.season.isin(YEARS) & ((pre.pos == ps) if ps != "ALL" else True) & pre[C].notna()]); b = f(post[post.season.isin(YEARS) & ((post.pos == ps) if ps != "ALL" else True) & post[C].notna()])
            w, n, md, t = paired(a, b, wmae, C)
            P(f"| {ps} | {int((a.act_games >= 4).sum())} | {wmae(a, C):.3f} / {rho(a, C):.3f} | {wmae(b, C):.3f} / {rho(b, C):.3f} | {w}/{n} | {md:+.4f} | {t:+.2f} |")
            if fails is not None and ps != "ALL" and not lab.startswith("everyone") and md > 0 and t > 1.81: fails.append((lab, ps, md, t))


def main():
    pre = pd.read_parquet(os.path.join(G, "pre_pergame_rows.parquet")); post = pd.read_parquet(os.path.join(G, "post_pergame_rows.parquet"))
    P("=== A18 gate: team-code mapping fix, before vs after (same code otherwise) ===")
    P(f"  rows before {len(pre)}, after {len(post)}; veterans flagged drafted_comp 2015-25: before {int(pre[(pre.rookie == 0) & pre.season.isin(YEARS)].drafted_comp.sum())}, after {int(post[(post.rookie == 0) & post.season.isin(YEARS)].drafted_comp.sum())}")
    P(f"  team codes in the rows: before {sorted(set(pre.team.dropna()) - set(post.team.dropna()))} no longer appear after")
    fails = []
    pergame_tables(pre, post, "FULL mapping", fails)
    P("\n  season totals (tot_new = per-game x games model), ADP top 150: MAE / Spearman before -> after")
    P("| pos | n | before | after |"); P("|---|---|---|---|")
    for ps in POS4:
        o = []
        for x in (pre, post):
            y = x[x.season.isin(YEARS) & (x.pos == ps) & (x.adp <= 150) & x.tot_new.notna()]
            o.append(f"{np.mean(np.abs(y.tot_new - y.act_total)):.2f} / {np.nanmean([spearmanr(g.tot_new, g.act_total).correlation for _, g in y.groupby('season') if len(g) >= 8]):.3f}")
        P(f"| {ps} | {len(y)} | {o[0]} | {o[1]} |")
    gpre = pd.read_parquet(os.path.join(G, "pre_games_model_rows.parquet")); gpost = pd.read_parquet(os.path.join(G, "post_games_model_rows.parquet"))
    P("\n  games model (g_main x G vs actual games), ADP top 150: MAE before -> after; rows with team_r1qb = 1 before / after")
    P("| pos | n | before | after | team_r1qb rows before | after |"); P("|---|---|---|---|---|---|")
    for ps in POS4:
        o = []; k = []
        for x in (gpre, gpost):
            y = x[x.season.isin(YEARS) & (x.pos == ps) & (x.adp <= 150) & x.g_main.notna()]
            o.append(f"{np.mean(np.abs(y.g_main * y.G - y.act_games)):.3f}"); k.append(int(x[x.season.isin(YEARS) & (x.pos == ps)].team_r1qb.sum()))
        P(f"| {ps} | {len(y)} | {o[0]} | {o[1]} | {k[0]} | {k[1]} |")
    for nm, cols in (("qb_a11_rows", ["p_bench"]), ("qb_a13_rows", ["p_F0", "p_F3"])):
        a = pd.read_parquet(os.path.join(G, f"pre_{nm}.parquet")); b = pd.read_parquet(os.path.join(G, f"post_{nm}.parquet"))
        P(f"\n  {nm}: week-1 QB1 rows with a walk-forward P(bench): Brier before -> after, all rows and the rows both runs have")
        for c in cols:
            xa = a[a[c].notna() & a.benched.notna()]; xb = b[b[c].notna() & b.benched.notna()]
            m = xa.merge(xb, on=["season", "pid"], suffixes=("_a", "_b"))
            P(f"   {c}: n {len(xa)} -> {len(xb)}; Brier {np.mean((xa[c] - xa.benched) ** 2):.4f} -> {np.mean((xb[c] - xb.benched) ** 2):.4f} | common rows n {len(m)}: {np.mean((m[c + '_a'] - m.benched_a) ** 2):.4f} -> {np.mean((m[c + '_b'] - m.benched_b) ** 2):.4f} (no-skill {np.mean((m.benched_a.mean() - m.benched_a) ** 2):.4f})")
        P(f"   comp_hi = 1 (rd 1-2 QB behind): rows {int(a[a[cols[0]].notna()].comp_hi.sum())} -> {int(b[b[cols[0]].notna()].comp_hi.sum())}")
    P("\n  GATE: " + ("FAIL - " + "; ".join(f"{ps} worse in '{lab}' by {md:+.4f} per season (t {t:+.2f})" for lab, ps, md, t in fails) if fails else "PASS - no position is worse beyond season-to-season noise (paired t <= 1.81 everywhere)"))
    # where the change comes from: each code family alone (per-game model only)
    P("\n## attribution: each code family alone, per-game model only (not part of the gate)")
    for v, lab in (("pfr_only", "PFR draft-pick codes only (GNB KAN NWE NOR SFO TAM LVR SDG)"), ("roster_only", "2012-15 roster codes only (BLT CLV HST SL)")):
        f = os.path.join(G, f"{v}_pergame_rows.parquet")
        if not os.path.exists(f): P(f"  {lab}: not run"); continue
        x = pd.read_parquet(f)
        P(f"\n  {lab}: veterans flagged drafted_comp 2015-25 = {int(x[(x.rookie == 0) & x.season.isin(YEARS)].drafted_comp.sum())}")
        pergame_tables(pre, x, v)


if __name__ == "__main__":
    main()
