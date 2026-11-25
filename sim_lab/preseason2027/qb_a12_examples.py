#!/usr/bin/env python3
"""A12 examples: P(becomes the starter) for 2026 week-1 non-starting QBs (preseason chart, fit on 2013-25) and what happened
through the 2026 weeks on disk, plus the same for the 2027 early look (current backups; no 2027 rookies yet).
Read-only on everything outside preseason2027. Log: qb_a12_examples.log (opened in main())."""
import os, sys, time, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import output_rankings as OR, preseason_model as PM, games_model as GM, fixes_a9 as FX, qb_a11 as JS

LOG = None
CAP = {}


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def main():
    global LOG
    LOG = open(os.path.join(HERE, "qb_a12_examples.log"), "w", encoding="utf-8"); OR.LOG = LOG
    t0 = time.time()
    orig = FX.takeover_table
    def grab(D):
        CAP[int(D.season.max())] = D.copy(); return orig(D)
    FX.takeover_table = grab
    W26 = OR.build_work_data(); idx = OR.name_index(); recent = W26.groupby("pid").week.max().to_dict()
    ch26 = OR.load_chart(os.path.join(OR.WORK, "depth_charts_2026_preseason.js"), r"window\.DEPTH_2026")
    ch27 = OR.load_chart(os.path.join(PM.SIM, "data", "sim_depth.js"), r"window\.SIM_DEPTH_2026")
    dc26, qb26 = OR.chart_maps(ch26, idx, recent); dc27, qb27 = OR.chart_maps(ch27, idx, recent)
    use = W26.groupby(["pid", "team"]).agg(starts=("att", lambda x: int((x >= 15).sum()))).reset_index()
    for t_, g_ in use.sort_values("starts", ascending=False).drop_duplicates("team")[["team", "pid"]].values:
        if use[use.team == t_].starts.max() >= 3 and g_ in dc27 and dc27[g_][0] == t_: qb27[t_] = g_
    first_team = W26.sort_values("week").groupby("pid").team.first().to_dict(); last_team = W26.sort_values("week").groupby("pid").team.last().to_dict()
    team26 = {g: t for g, (t, r) in dc26.items()}
    for g, t in first_team.items(): team26.setdefault(g, t)
    team27 = {g: t for g, (t, r) in dc27.items()}
    for g, t in last_team.items(): team27.setdefault(g, t)
    OR.patch(dc26, qb26, dc27, qb27, team26, team27)
    D_all = PM.build(); AV, wk1 = GM.availability()
    tg = W26.groupby("team").week.nunique()
    ph = W26.groupby("pid").agg(g=("week", "nunique"), team=("team", "last"), tch=("tgt", "sum"), car=("car", "sum")).reset_index()
    ph["tgames"] = ph.team.map(tg); ph["gshare"] = (ph.g / ph.tgames).clip(0, 1); ph["tpg"] = (ph.tch + ph.car) / ph.g; ph["scale"] = 17 / ph.tgames
    OR.run_year(D_all, 2026, AV, wk1, ph)
    OR.run_year(D_all, 2027, AV, wk1, ph)
    # history: week-1 non-starters 2013-25, took over = 4+ starts (team starter = most attempts, 15+)
    W = pd.read_parquet(os.path.join(PM.DATA, "player_weeks.parquet"), columns=["season", "week", "pid", "team", "att"])
    W = W[W.week < W.season.map(PM.final_week)]
    st = W[W.att >= 15].sort_values("att", ascending=False).drop_duplicates(["season", "week", "team"])
    starts = st.groupby(["season", "pid"]).size()
    K, _ = JS.contracts_asof(range(2013, 2028))
    F = ["lpick", "rookie", "prior_starts", "money", "age"]
    st26 = W26[W26.att >= 15].sort_values("att", ascending=False).drop_duplicates(["week", "team"])
    s26 = st26.groupby("pid").size(); f26 = st26.groupby("pid").week.min(); wk_last = int(W26.week.max())
    for Y in (2026, 2027):
        D = CAP[Y]
        D["money"] = [K.get((y, p), {}).get("apy_cap", np.nan) for y, p in zip(D.season, D.pid)]
        D["prior_starts"] = D.h1_att.fillna(0) / 30
        BK = (D.pos == "QB") & (D.is_qb1 == 0) & D.team.notna()
        H = D[BK & D.season.between(2013, 2025)].copy()
        H["took"] = [float(starts.get((y, p), 0) >= 4) for y, p in zip(H.season, H.pid)]
        T = D[BK & (D.season == Y)].copy()
        T["p_take"] = JS.logit_fit(H[F].values.astype(float), H.took.values, T[F].values.astype(float))
        T["starts26"] = T.pid.map(s26).fillna(0).astype(int); T["first26"] = T.pid.map(f26)
        T = T.sort_values("p_take", ascending=False)
        lab = "2026 preseason chart (what happened = 2026 weeks 1-%d on disk)" % wk_last if Y == 2026 else "2027 early look, current backups (2026 starts so far shown for context)"
        P(f"\n=== {lab}: highest P(becomes starter, 4+ starts) | base rate {H.took.mean():.3f} (n {len(H)}) ===")
        P("| name | team | rookie | draft pick | cap share | P(4+ starts) | 2026 starts | first 2026 start |")
        P("|---|---|---|---|---|---|---|---|")
        for r in T.head(15).itertuples(index=False):
            pk = int(round(np.exp(r.lpick))) if pd.notna(r.lpick) and r.lpick < 6 else "-"
            P(f"| {r.name} | {r.team} | {int(r.rookie)} | {pk} | {'' if pd.isna(r.money) else f'{r.money*100:.1f}%'} | {r.p_take:.2f} | {r.starts26} | {'' if pd.isna(r.first26) else int(r.first26)} |")
        if Y == 2026:
            T["took26"] = (T.starts26 >= 4).astype(float)
            for lo, hi in ((0, .1), (.1, .2), (.2, .35), (.35, 1)):
                m = T.p_take.between(lo, hi, inclusive="left")
                if m.any(): P(f"  2026 bin {lo:.2f}-{hi:.2f}: n {int(m.sum())}, mean P {T.p_take[m].mean():.2f}, 4+ starts so far {T.took26[m].mean():.2f}")
            P(f"  2026 all non-starters: mean P {T.p_take.mean():.3f} vs 4+ starts so far {T.took26.mean():.3f} (season not finished: wk {wk_last})")
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
