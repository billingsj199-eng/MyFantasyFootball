#!/usr/bin/env python3
"""
A12 - start-date odds for rookie and backup QBs, as ONE team QB-room model with A11's job security (Jack 2026-11-21
"Yes, add them"). In-house, no ADP input. Point-in-time inputs only (A11 contract rules).

Room model per team-season (2015-25 walk-forward; fits use earlier seasons only):
  starter S (week-1 chart QB1): expected starts E_S = A11 games (games model x job security), with the games lost to a
      benching now depending on WHEN it tends to happen (timing by group, fit on earlier seasons: high pick behind vs not)
  missing starts M = G - E_S go to the team's other QBs in proportion to a take-over weight
      w_i = P(take over | backup i) from a small walk-forward logistic (draft capital, rookie, prior starts, cap share)
  so the room adds up to G in the average.
  backups' per-game number is scaled by the walk-forward act/pred ratio of past backups who took over (A10: 1.13).
Judged on 2015-22 (choices), 2023-25 reported separately (already viewed). Log: qb_a12.log (opened in main()).
"""
import os, sys, time, warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM, games_model as GM, pergame_model as G, fixes_a9 as FX, qb_a10 as Q, qb_a11 as JS

LOG = None


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def wilson(k, n, z=1.645):
    if n == 0: return (np.nan, np.nan)
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def main():
    global LOG
    LOG = open(os.path.join(HERE, "qb_a12.log"), "w", encoding="utf-8"); Q.LOG = LOG; JS.LOG = LOG
    t0 = time.time()
    P("=== A12 start-date odds for non-starting QBs (team QB-room model) ===")
    D = PM.build(); AV, wk1 = GM.availability(); D = GM.add_features(D, AV, wk1)
    S = G.stat_seasons(); D = G.add_history(D, S); D = G.add_context(D, S); D = FX.add_fix1_features(D)
    R0 = PM.walk_forward(D)
    for c in ("ridge_stats", "adp_curve_f", "adp_total"): D[c] = R0[c].values
    O = GM.walk(D, [f if f != "gs1" else "gs1_shrunk" for f in GM.GF], "g"); D = pd.concat([D, O], axis=1); D["g_use"] = 0.75 * D.g_ridge + 0.25 * D.g_dist
    s7, _, _ = G.walk(D, Q.LEAN, "S7", use_role_prior=True); D["pg"] = (0.75 * s7 + 0.25 * D.ridge_stats).values
    QB = (D.pos == "QB") & D.season.between(2013, 2025) & D.team.notna()
    D = D[QB | (D.pos != "QB")].copy()
    # ---- starts (team starter each game = most attempts, 15+)
    W = pd.read_parquet(os.path.join(PM.DATA, "player_weeks.parquet"), columns=["season", "week", "pid", "team", "att"])
    W = W[W.week < W.season.map(PM.final_week)]
    st = W[W.att >= 15].sort_values("att", ascending=False).drop_duplicates(["season", "week", "team"])
    starts = st.groupby(["season", "pid"]).size(); first = st.groupby(["season", "pid"]).week.min()
    D["starts_act"] = [starts.get((y, p), 0) for y, p in zip(D.season, D.pid)]
    D["first_start"] = [first.get((y, p), np.nan) for y, p in zip(D.season, D.pid)]
    team_games = W.groupby(["season", "team"]).week.nunique()
    D["Gt"] = [team_games.get((y, t), 16.5) for y, t in zip(D.season, D.team)]
    # ---- A11 inputs + bench probability for starters (re-fit here, same form)
    K, _ = JS.contracts_asof(range(2013, 2026))
    D["money"] = [K.get((y, p), {}).get("apy_cap", np.nan) for y, p in zip(D.season, D.pid)]
    dp = pd.read_parquet(os.path.join(PM.CACHE, "draft_picks.parquet"), columns=["season", "pick", "team", "position", "gsis_id"]); dp["team"] = dp.team.map(PM.tm)
    hi = {}
    for r in dp[(dp.position == "QB") & (dp.pick <= 64)].itertuples(index=False):
        for yy in (r.season, r.season + 1): hi.setdefault((yy, r.team), set()).add(r.gsis_id)
    D["comp_hi"] = [float(len(hi.get((y, t), set()) - {p}) > 0) for y, t, p in zip(D.season, D.team, D.pid)]
    qbm = (D.pos == "QB")
    Dq = JS.outcomes(D[qbm].copy())
    D.loc[qbm, "healthy_lost_wks"] = Dq.healthy_lost_wks.values
    S1 = qbm & (D.is_qb1 == 1)
    D["benched"] = (D.healthy_lost_wks >= 2).astype(float)
    D["p_bench"] = np.nan
    for Y in PM.TEST_YEARS:
        tr = S1 & (D.season < Y); te = S1 & (D.season == Y)
        if tr.sum() > 60 and te.sum(): D.loc[te, "p_bench"] = JS.logit_fit(D.loc[tr, ["money", "comp_hi", "exp_w"]].values.astype(float), D.benched[tr].values, D.loc[te, ["money", "comp_hi", "exp_w"]].values.astype(float))
    # ---- STEP 1: base rates for non-starters
    BK = qbm & (D.is_qb1 == 0)
    D["took"] = (D.starts_act >= 4).astype(float)
    D["prior_starts"] = D.h1_att.fillna(0) / 30
    D["btype"] = np.select([(D.rookie == 1) & (D.rd1 == 1), (D.rookie == 1) & (D.rd2 == 1), D.rookie == 1, (D.w1_res == 1) & (D.gs1.fillna(0) >= .5),
                            (D.rookie == 0) & (D.money >= .02), (D.rookie == 0)], ["rookie rd 1", "rookie rd 2", "rookie later", "former starter on reserve wk 1", "veteran backup (cap >= 2%)", "journeyman backup"], "other")
    P("\n=== STEP 1. Week-1 non-starters 2013-25: 4+ starts (90% Wilson range), first-start week, how long they keep it ===")
    for t in ["rookie rd 1", "rookie rd 2", "rookie later", "veteran backup (cap >= 2%)", "journeyman backup", "former starter on reserve wk 1", "ALL"]:
        mk = BK & ((D.btype == t) if t != "ALL" else True)
        n = int(mk.sum()); k = int(D.took[mk].sum()); lo, hi_ = wilson(k, n)
        tk = mk & (D.took == 1)
        keep = (D.starts_act[tk] / (D.Gt[tk] - D.first_start[tk] + 1).clip(lower=1)).mean() if tk.any() else np.nan
        P(f"  {t:32s} n {n:4d}: {k/max(n,1)*100:5.1f}% [{lo*100:4.1f}-{hi_*100:4.1f}] | first start median wk {D.first_start[tk].median():.0f} | share of remaining games he started {keep:.2f}")
    # why the change happened (team level, week-1 starter's outcome)
    s_rows = D[S1 & D.season.isin(range(2013, 2026))]
    s_inj = (s_rows.Gt - s_rows.act_games - s_rows.healthy_lost_wks).clip(lower=0)
    team_change = s_rows[(s_rows.Gt - s_rows.starts_act) >= 4]
    if len(team_change):
        why = np.where(team_change.healthy_lost_wks >= 2, "benched / cut / traded (healthy)", "injury")
        P("  teams where the week-1 starter missed 4+ starts: " + " | ".join(f"{k}: {v}" for k, v in pd.Series(why).value_counts().items()))
    # production vs own projection when he took over
    tk = BK & (D.took == 1) & D.pg.notna() & (D.act_games >= 4)
    P(f"  backups who took over: act/pred per game {D.act_ppg[tk].sum()/D.pg[tk].sum():.3f} (n {int(tk.sum())})")

    # ---- STEP 2: room model
    P("\n=== STEP 2. Team QB-room model ===")
    D["p_take"] = np.nan
    F = ["lpick", "rookie", "prior_starts", "money", "age"]
    for Y in PM.TEST_YEARS:
        tr = BK & (D.season < Y); te = BK & (D.season == Y)
        if tr.sum() > 100 and te.sum(): D.loc[te, "p_take"] = JS.logit_fit(D.loc[tr, F].values.astype(float), D.took[tr].values, D.loc[te, F].values.astype(float))
    m = BK & D.p_take.notna() & D.season.isin(PM.TEST_YEARS)
    t = pd.DataFrame({"p": D.p_take[m], "y": D.took[m]}); t["bin"] = pd.cut(t.p, [0, .05, .1, .2, .35, .6, 1])
    base = {Y: D.took[BK & (D.season < Y)].mean() for Y in PM.TEST_YEARS}
    P("  P(take over) calibration: " + " | ".join(f"{r.p:.2f}->{r.y:.2f} (n{r.n})" for r in t.groupby("bin", observed=True).agg(n=("y", "size"), p=("p", "mean"), y=("y", "mean")).itertuples())
      + f" | Brier {np.mean((t.p-t.y)**2):.4f} vs base-rate {np.mean((D.season[m].map(base)-D.took[m])**2):.4f}")
    # timing of a benching by group (games lost), walk-forward
    D["lost_after"] = np.where(D.benched == 1, D.Gt - D.act_games, np.nan)
    Lg = {}
    for Y in PM.TEST_YEARS:
        tr = S1 & (D.season < Y)
        Lg[Y] = {c: (D.act_games[tr & (D.benched == 0) & (D.comp_hi == c)].mean() - D.act_games[tr & (D.benched == 1) & (D.comp_hi == c)].mean()) if (tr & (D.benched == 1) & (D.comp_hi == c)).sum() >= 5 else
                 (D.act_games[tr & (D.benched == 0)].mean() - D.act_games[tr & (D.benched == 1)].mean()) for c in (0.0, 1.0)}
    P("  games lost when benched, by high pick behind (fit on earlier seasons, 2025 fold): " + str({k: round(v, 1) for k, v in Lg[2025].items()}))
    br = {Y: D.benched[S1 & (D.season < Y)].mean() for Y in PM.TEST_YEARS}
    Lflat = {Y: (D.act_games[S1 & (D.season < Y) & (D.benched == 0)].mean() - D.act_games[S1 & (D.season < Y) & (D.benched == 1)].mean()) for Y in PM.TEST_YEARS}
    in_test = D.season.isin(PM.TEST_YEARS)
    D["g_a11"] = np.where(S1 & D.p_bench.notna(), (D.g_use - (D.p_bench - D.season.map(br)) * D.season.map(Lflat) / 16.5).clip(.05, 1), D.g_use)
    D["L_time"] = [Lg.get(y, {}).get(c, np.nan) for y, c in zip(D.season, D.comp_hi)]
    D["g_a12s"] = np.where(S1 & D.p_bench.notna(), (D.g_use - (D.p_bench - D.season.map(br)) * D.L_time / 16.5).clip(.05, 1), D.g_use)
    # starters' expected STARTS (games played ~ starts for starters)
    D["ES"] = D.g_a12s * D.Gt
    # allocate the missing starts to the room
    D["take_ratio"] = np.nan
    for Y in PM.TEST_YEARS:
        tk = BK & (D.took == 1) & (D.season < Y) & (D.act_games >= 4) & D.pg.notna()
        D.loc[qbm & (D.season == Y), "take_ratio"] = float(np.clip(D.act_ppg[tk].sum() / D.pg[tk].sum(), .9, 1.25)) if tk.sum() > 20 else 1.0
    rooms = D[qbm & in_test].groupby(["season", "team"])
    D["E_starts"] = np.where(S1, D.ES, np.nan)
    for (y, tm_), g in rooms:
        s = g[g.is_qb1 == 1]; b = g[(g.is_qb1 == 0) & g.p_take.notna()]
        Es = float(s.ES.sum()) if len(s) else 0.0
        M = max(0.0, float(g.Gt.iloc[0]) - Es)
        if len(b):
            w = b.p_take.values; w = w / w.sum() if w.sum() > 0 else np.ones(len(b)) / len(b)
            D.loc[b.index, "E_starts"] = M * w
    # before: games model share x G for backups (no room logic)
    D["games_before"] = np.where(qbm, np.where(S1, D.g_a11, D.g_use) * D.Gt, np.nan)
    D["games_after"] = np.where(qbm, np.where(S1, D.ES, D.E_starts), np.nan)
    D["tot_before"] = D.pg * D.games_before
    D["pg_after"] = np.where(BK, D.pg * D.take_ratio.fillna(1.0), D.pg)
    D["tot_after"] = D.pg_after * D.games_after
    D["tot_after_noratio"] = D.pg * D.games_after
    # room add-up
    rs = D[qbm & in_test].groupby(["season", "team"]).agg(b=("games_before", "sum"), a=("games_after", "sum"), Gt=("Gt", "first"))
    P(f"  room add-up (sum of QBs' expected games/starts vs team games): before mean {rs.b.mean():.1f} (|gap| {np.mean(np.abs(rs.b - rs.Gt)):.1f}) | after mean {rs.a.mean():.1f} (|gap| {np.mean(np.abs(rs.a - rs.Gt)):.2f}) vs {rs.Gt.mean():.1f}")
    # ---- judge
    P("\n=== Judging ===")
    for nm, yrs in (("dev 2015-22", Q.DEV), ("holdout 2023-25", Q.HOLD)):
        mb = BK & D.season.isin(yrs) & D.games_after.notna()
        for col, gcol in (("before", "games_before"), ("after", "games_after")):
            P(f"  backups {nm} {col:6s}: starts/games pred {D[gcol][mb].mean():4.2f} vs actual starts {D.starts_act[mb].mean():4.2f} | MAE {np.mean(np.abs(D[gcol][mb]-D.starts_act[mb])):.2f} | rho {spearmanr(D[gcol][mb], D.starts_act[mb]).correlation:.3f} (n {int(mb.sum())})")
        for col in ("tot_before", "tot_after_noratio", "tot_after"):
            mm = mb & D[col].notna()
            P(f"  backups {nm} totals {col:18s}: MAE {np.mean(np.abs(D[col][mm]-D.act_total[mm])):5.1f} | rho {spearmanr(D[col][mm], D.act_total[mm]).correlation:.3f}")
    for t_ in ["rookie rd 1", "rookie rd 2", "rookie later", "veteran backup (cap >= 2%)", "journeyman backup"]:
        mm = BK & (D.btype == t_) & D.games_after.notna()
        P(f"    {t_:28s} n {int(mm.sum()):3d}: actual starts {D.starts_act[mm].mean():4.2f} | before {D.games_before[mm].mean():4.2f} | after {D.games_after[mm].mean():4.2f}")
    hp = S1 & (D.comp_hi == 1) & in_test
    P(f"  starters with a high pick behind (A11 weak spot, n {int(hp.sum())}): actual games {D.act_games[hp].mean():.1f} | A11 {(D.g_a11[hp]*D.Gt[hp]).mean():.1f} (MAE {np.mean(np.abs(D.g_a11[hp]*D.Gt[hp]-D.act_games[hp])):.2f}) | A12 timing {D.ES[hp].mean():.1f} (MAE {np.mean(np.abs(D.ES[hp]-D.act_games[hp])):.2f})")
    st_ = S1 & in_test
    P(f"  all week-1 starters: A11 games MAE {np.mean(np.abs(D.g_a11[st_]*D.Gt[st_]-D.act_games[st_])):.2f} | A12 {np.mean(np.abs(D.ES[st_]-D.act_games[st_])):.2f}")
    rk = S1 & (D.rookie == 1) & in_test
    P(f"  rookies who START week 1 (n {int(rk.sum())}): mean P(bench) {D.p_bench[rk].mean():.3f}, actual benched {D.benched[rk].mean():.3f}, games pred {D.ES[rk].mean():.1f} vs actual {D.act_games[rk].mean():.1f}")
    # full QB pool, bands
    W4 = W[W.att >= 15].groupby(["season", "pid"]).size()
    pool = qbm & in_test & ((D.is_qb1 == 1) | (D.starts_act >= 4))
    allq = qbm & in_test
    for nm, yrs in (("dev", Q.DEV), ("holdout", Q.HOLD)):
        for col in ("tot_before", "tot_after"):
            for pl, mk in (("A10 pool", pool), ("all QBs", allq)):
                mm = mk & D.season.isin(yrs) & D[col].notna()
                rh = np.mean([spearmanr(g[col], g.act_total).correlation for _, g in D[mm].groupby("season") if len(g) >= 20])
                h12 = np.mean([len(set(g.nlargest(12, col).pid) & set(g.nlargest(12, "act_total").pid)) / 12 for _, g in D[mm].groupby("season") if len(g) >= 20])
                h24 = np.mean([len(set(g.nlargest(24, col).pid) & set(g.nlargest(24, "act_total").pid)) / 24 for _, g in D[mm].groupby("season") if len(g) >= 20])
                P(f"  {nm:7s} {pl:8s} {col:10s}: MAE {np.mean(np.abs(D[col][mm]-D.act_total[mm])):5.1f} | rho {rh:.3f} | top12 {h12:.3f} | top24 {h24:.3f}")
        for lo_, hi2 in ((13, 28), (25, 40)):
            for col in ("tot_before", "tot_after"):
                D["qrk"] = D[allq].groupby("season")[col].rank(ascending=False)
                mm = allq & D.season.isin(yrs) & D.qrk.between(lo_, hi2)
                P(f"  {nm:7s} band QB{lo_}-{hi2} (by {col}): MAE {np.mean(np.abs(D[col][mm]-D.act_total[mm])):5.1f} | rho {spearmanr(D[col][mm], D.act_total[mm]).correlation:.3f} (n {int(mm.sum())})")
        mm = pool & D.season.isin(yrs) & D.adp.notna()
        for col in ("tot_before", "tot_after", "adp_total"):
            rh = np.mean([spearmanr(g[col], g.act_total).correlation for _, g in D[mm].groupby("season") if len(g) >= 12])
            P(f"  {nm:7s} QBs with ADP {col:10s}: MAE {np.mean(np.abs(D[col][mm]-D.act_total[mm])):5.1f} | rho {rh:.3f}")
    D[qbm][["season", "pid", "name", "team", "is_qb1", "btype", "p_take", "p_bench", "E_starts", "ES", "games_before", "games_after", "starts_act", "first_start", "took", "tot_before", "tot_after"]].to_parquet(os.path.join(HERE, "data", "qb_a12_rows.parquet"), index=False)
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
