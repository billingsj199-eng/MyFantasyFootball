#!/usr/bin/env python3
"""
A11 - QB job security from the on-disk OTC contracts + draft capital (Jack 2026-11-21 "Try job security"). No ADP input.

POINT-IN-TIME RULE for season Y (the file describes each deal as it ended up, so only at-signing fields are used):
  * safe at signing: year_signed, years, value, apy, guaranteed, apy_cap_pct, draft_year/round/overall, date_of_birth, gsis_id,
    and contract_type from contract_history (Drafted / UFA / Extension / Franchise / RFA ...), matched by year_signed + total
  * LEAK, never used: is_active, inflated_* (restated to today's cap), season_history (cash_paid, cap_number, base / guaranteed
    salary by year - restructures and cuts rewrite these), contract_history status / amount_earned / percent_earned /
    effective_apy (outcomes), player_page
  * contract in force for Y = the latest deal with year_signed <= Y-1, or year_signed == Y if it is an OFFSEASON-type deal
    (Drafted, UFA, RFA, ERFA, Franchise, Transition, SFA, UDFA, Other). Same-team 'Extension' rows dated Y are skipped (they can
    be in-season extensions, which would leak that he kept the job). Guaranteed money still OWED cannot be rebuilt point-in-time
    (the yearly guarantee schedule lives in season_history, which restructures rewrite) - only total guarantee share and years
    left are used.
OUTCOME: a week-1 chart QB1 who LOSES THE JOB WHILE HEALTHY = 2+ team games where another QB started (most attempts, 15+) while
  he was not on the injury report as Out / Doubtful and not on a reserve list that week (traded / cut counts as lost).
Choices on 2015-22; 2023-25 reported separately (already viewed). Log: qb_a11.log (opened in main()).
"""
import os, sys, time, warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import preseason_model as PM, games_model as GM, pergame_model as G, fixes_a9 as FX, qb_a10 as Q

LOG = None
CACHE = PM.CACHE
OFFSEASON_TYPES = {"Drafted", "UFA", "RFA", "ERFA", "Franchise", "Transition", "SFA", "UDFA", "Other"}


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def contracts_asof(years):
    c = pd.read_parquet(os.path.join(CACHE, "otc", "historical_contracts.parquet"),
                        columns=["player", "position", "gsis_id", "year_signed", "years", "value", "apy", "guaranteed", "apy_cap_pct", "contract_history"])
    c = c[(c.position == "QB") & c.gsis_id.notna()].copy()
    def ctype(r):
        for h in (r.contract_history if r.contract_history is not None else []):
            if h.get("year_signed") == r.year_signed and abs((h.get("total") or 0) - (r.value or 0)) < 0.05: return h.get("contract_type")
        return None
    c["ctype"] = [ctype(r) for r in c.itertuples(index=False)]
    out = {}
    for Y in years:
        ok = (c.year_signed <= Y - 1) | ((c.year_signed == Y) & c.ctype.isin(OFFSEASON_TYPES))
        x = c[ok].sort_values(["year_signed", "apy"]).groupby("gsis_id").tail(1)
        for r in x.itertuples(index=False):
            yl = (r.years or 1) - (Y - r.year_signed)
            out[(Y, r.gsis_id)] = {"apy_cap": r.apy_cap_pct, "years_left": yl, "gtd_share": (r.guaranteed or 0) / r.value if r.value else np.nan,
                                   "rookie_deal": float(r.ctype in ("Drafted", "UDFA")), "bridge": float(r.ctype in ("UFA", "Other", "SFA") and (r.years or 0) <= 2),
                                   "tag": float(r.ctype in ("Franchise", "Transition")), "signed_now": float(r.year_signed == Y), "ctype": r.ctype}
    return out, c


def outcomes(D):
    W = pd.read_parquet(os.path.join(PM.DATA, "player_weeks.parquet"), columns=["season", "week", "pid", "team", "att"])
    W = W[W.week < W.season.map(PM.final_week)]
    st = W[W.att >= 15].sort_values("att", ascending=False).drop_duplicates(["season", "week", "team"])   # team's starter each game
    starter = {(r.season, r.week, r.team): r.pid for r in st.itertuples(index=False)}
    inj, res = set(), set()
    for Y in range(2013, 2026):
        i = pd.read_parquet(os.path.join(CACHE, f"injuries_{Y}.parquet"), columns=["game_type", "week", "gsis_id", "report_status"])
        i = i[(i.game_type == "REG") & i.report_status.isin(["Out", "Doubtful"])]
        inj |= set(zip([Y] * len(i), i.week.astype(int), i.gsis_id))
        r = pd.read_parquet(os.path.join(CACHE, f"roster_weekly_{Y}.parquet"), columns=["week", "gsis_id", "status", "game_type"])
        r = r[(r.game_type == "REG") & r.status.isin(["RES", "PUP", "NFI", "RSN", "SUS"])]
        res |= set(zip([Y] * len(r), r.week.astype(int), r.gsis_id))
    tw = W.groupby(["season", "team"]).week.apply(lambda s: sorted(set(s))).to_dict()
    lost, first_start = [], []
    for r in D.itertuples(index=False):
        weeks = tw.get((r.season, r.team), [])
        hl = sum(1 for w in weeks if starter.get((r.season, w, r.team)) not in (None, r.pid) and (r.season, w, r.pid) not in inj and (r.season, w, r.pid) not in res)
        lost.append(hl)
        fs = [w for w in weeks if starter.get((r.season, w, r.team)) == r.pid]
        first_start.append(min(fs) if fs else np.nan)
    D["healthy_lost_wks"] = lost; D["first_start_wk"] = first_start
    return D


def logit_fit(X, y, Xt, C=0.3):
    from sklearn.linear_model import LogisticRegression
    med = np.nanmedian(X, 0); X = np.where(np.isnan(X), med, X); Xt = np.where(np.isnan(Xt), med, Xt)
    mu, sd = X.mean(0), X.std(0); sd[sd == 0] = 1
    m = LogisticRegression(C=C, max_iter=2000).fit((X - mu) / sd, y)
    return m.predict_proba((Xt - mu) / sd)[:, 1]


def main():
    global LOG
    LOG = open(os.path.join(HERE, "qb_a11.log"), "w", encoding="utf-8"); Q.LOG = LOG
    t0 = time.time()
    P("=== A11 QB job security (contracts + draft capital, point-in-time) ===")
    D = PM.build(); AV, wk1 = GM.availability(); D = GM.add_features(D, AV, wk1)
    S = G.stat_seasons(); D = G.add_history(D, S); D = G.add_context(D, S); D = FX.add_fix1_features(D)
    R0 = PM.walk_forward(D)
    for c in ("ridge_stats", "adp_curve_f", "naive_f", "adp_total"): D[c] = R0[c].values
    O = GM.walk(D, [f if f != "gs1" else "gs1_shrunk" for f in GM.GF], "g"); D = pd.concat([D, O], axis=1); D["g_use"] = 0.75 * D.g_ridge + 0.25 * D.g_dist
    s7, cp, _ = G.walk(D, Q.LEAN, "S7", use_role_prior=True); D["pg"] = (0.75 * s7 + 0.25 * D.ridge_stats).values
    W = pd.read_parquet(os.path.join(PM.DATA, "player_weeks.parquet"), columns=["season", "week", "pid", "att"])
    W = W[W.week < W.season.map(PM.final_week)]; stc = W[W.att >= 15].groupby(["season", "pid"]).size()
    D["starts"] = [stc.get((y, p), 0) for y, p in zip(D.season, D.pid)]
    QBall = (D.pos == "QB") & D.season.between(2013, 2025)
    pool = (D.pos == "QB") & D.season.isin(PM.TEST_YEARS) & ((D.is_qb1 == 1) | (D.starts >= 4))
    # ---------------- contracts point in time
    K, craw = contracts_asof(range(2013, 2026))
    for f in ("apy_cap", "years_left", "gtd_share", "rookie_deal", "bridge", "tag", "signed_now"):
        D[f"k_{f}"] = [K.get((y, p), {}).get(f, np.nan) for y, p in zip(D.season, D.pid)]
    D["k_has"] = [float((y, p) in K) for y, p in zip(D.season, D.pid)]
    P(f"\n  contract coverage of the A10 QB pool: {int((pool & (D.k_has == 1)).sum())}/{int(pool.sum())} ({(D.k_has[pool].mean()*100):.1f}%)")
    P("   by season: " + " ".join(f"{y}:{D.k_has[pool & (D.season == y)].mean()*100:.0f}%" for y in PM.TEST_YEARS))
    miss = D[pool & (D.k_has == 0)]
    P(f"   missing: {len(miss)} - rookies {int((miss.rookie == 1).sum())}, week-1 QB1 {int((miss.is_qb1 == 1).sum())}, takeovers {int((miss.is_qb1 == 0).sum())}; examples: " + ", ".join(f"{r.name} {r.season}" for r in miss.head(8).itertuples()))
    # ---------------- outcomes
    D = outcomes(D)
    S1 = (D.pos == "QB") & D.season.between(2013, 2025) & (D.is_qb1 == 1)
    D["benched"] = (D.healthy_lost_wks >= 2).astype(float)
    P("\n  week-1 QB1 who LOST THE JOB WHILE HEALTHY (2+ team games another QB started while he was not Out/Doubtful/reserve):")
    P("   by season: " + " ".join(f"{y}:{D.benched[S1 & (D.season == y)].mean()*100:.0f}%(n{int((S1 & (D.season == y)).sum())})" for y in range(2013, 2026)))
    b = S1 & (D.benched == 1); nb = S1 & (D.benched == 0)
    P(f"   overall {D.benched[S1].mean()*100:.1f}% of {int(S1.sum())}; games played benched {D.act_games[b].mean():.1f} vs others {D.act_games[nb].mean():.1f}; healthy weeks lost when benched {D.healthy_lost_wks[b].mean():.1f}")
    P(f"   how clean the injury split is: benched QBs on an injury report in some week: {np.mean([1 for _ in []]) if False else 'see note'} - players who were injured AND later lost the job count as benched only for healthy weeks")
    # mirror: week-1 non-QB1 who took over
    S2 = (D.pos == "QB") & D.season.between(2013, 2025) & (D.is_qb1 == 0) & (D.dc.isin([2, 3]) | (D.rookie == 1))
    D["took"] = (D.starts >= 4).astype(float)
    P(f"\n  mirror: week-1 backups (chart 2-3 or rookies) with 4+ starts: {D.took[S2].mean()*100:.1f}% of {int(S2.sum())}; rookies {D.took[S2 & (D.rookie == 1)].mean()*100:.1f}% (n {int((S2 & (D.rookie == 1)).sum())}); rd-1 rookies {D.took[S2 & (D.rookie == 1) & (D.rd1 == 1)].mean()*100:.1f}% (n {int((S2 & (D.rookie == 1) & (D.rd1 == 1)).sum())})")
    fs = D.first_start_wk[S2 & (D.took == 1)]
    P(f"   first start week of those who took over: median {fs.median():.0f}; by quarter: wk1-4 {np.mean(fs <= 4)*100:.0f}%, 5-9 {np.mean(fs.between(5, 9))*100:.0f}%, 10+ {np.mean(fs >= 10)*100:.0f}%")
    # ---------------- inputs
    dp = pd.read_parquet(os.path.join(CACHE, "draft_picks.parquet"), columns=["season", "pick", "team", "position", "gsis_id"])
    dp["team"] = dp.team.map(PM.tm)
    hi = {}
    for r in dp[(dp.position == "QB") & (dp.pick <= 64)].itertuples(index=False):
        for yy in (r.season, r.season + 1): hi.setdefault((yy, r.team), set()).add(r.gsis_id)
    D["comp_hi"] = [float(len(hi.get((y, t), set()) - {p}) > 0) for y, t, p in zip(D.season, D.team, D.pid)]
    D["money"] = D.k_apy_cap
    D["prev_pg_rel"] = D.ppg1 / D.groupby("season").ppg1.transform(lambda s: s[(D.loc[s.index, "pos"] == "QB") & (D.loc[s.index, "is_qb1"] == 1)].median())
    sets = {"base 3: money + high pick behind + team outlook": ["money", "comp_hi", "exp_w"],
            "+ prior production vs starters": ["money", "comp_hi", "exp_w", "prev_pg_rel"],
            "+ rookie deal / bridge / years left": ["money", "comp_hi", "exp_w", "k_rookie_deal", "k_bridge", "k_years_left"],
            "+ new head coach + age": ["money", "comp_hi", "exp_w", "new_hc", "age"]}
    probs = {}
    for lab, F in sets.items():
        p = pd.Series(np.nan, index=D.index)
        for Y in PM.TEST_YEARS:
            tr = S1 & (D.season < Y); te = S1 & (D.season == Y)
            if tr.sum() < 60 or te.sum() == 0: continue
            p[te] = logit_fit(D.loc[tr, F].values.astype(float), D.benched[tr].values, D.loc[te, F].values.astype(float))
        probs[lab] = p
        for nm, yrs in (("dev", Q.DEV), ("holdout", Q.HOLD)):
            m = S1 & D.season.isin(yrs) & p.notna()
            base = D.benched[S1 & (D.season < min(yrs))].mean() if nm == "dev" else D.benched[S1 & (D.season < 2023)].mean()
            P(f"  P(benched) {lab:44s} {nm:7s} n {int(m.sum())}: Brier {np.mean((p[m]-D.benched[m])**2):.4f} vs base-rate {np.mean((base-D.benched[m])**2):.4f}")
    pk = probs["base 3: money + high pick behind + team outlook"]
    D["p_bench"] = pk
    m = S1 & pk.notna()
    t = pd.DataFrame({"p": pk[m], "y": D.benched[m]}); t["bin"] = pd.cut(t.p, [0, .05, .1, .2, .3, .5, 1])
    P("  calibration (base 3): " + " | ".join(f"{r.p:.2f}->{r.y:.2f} (n{r.n})" for r in t.groupby("bin", observed=True).agg(n=("y", "size"), p=("p", "mean"), y=("y", "mean")).itertuples()))
    # coefficient read (full fit)
    from sklearn.linear_model import LogisticRegression
    F = ["money", "comp_hi", "exp_w"]; X = D.loc[S1, F].astype(float); X = X.fillna(X.median()); Z = (X - X.mean()) / X.std()
    cf = LogisticRegression(C=0.3, max_iter=2000).fit(Z, D.benched[S1]).coef_[0]
    P("  standardized logit coefs (full fit): " + ", ".join(f"{f} {c:+.2f}" for f, c in zip(F, cf)))
    for lab, mk in (("money top third", S1 & (D.money >= D.money[S1].quantile(.67))), ("money bottom third", S1 & (D.money <= D.money[S1].quantile(.33))),
                    ("high pick behind him", S1 & (D.comp_hi == 1)), ("no high pick behind", S1 & (D.comp_hi == 0)),
                    ("team exp wins <= 6.5", S1 & (D.exp_w <= 6.5)), ("team exp wins >= 9.5", S1 & (D.exp_w >= 9.5)), ("rookie week-1 QB1", S1 & (D.rookie == 1))):
        P(f"    benched rate {lab:26s} n {int(mk.sum()):3d}: {D.benched[mk].mean()*100:.1f}%")
    # ---------------- feed into QB games
    P("\n=== Feeding P(benched) into QB games played ===")
    Lfrac = {}
    for Y in PM.TEST_YEARS:
        tr = S1 & (D.season < Y)
        Lfrac[Y] = max(0.0, (D.act_games[tr & (D.benched == 0)].mean() - D.act_games[tr & (D.benched == 1)].mean()) / 16.5)
    D["g_mult"] = np.where((D.pos == "QB") & (D.is_qb1 == 1) & D.p_bench.notna(),
                           D.g_use * (1 - D.p_bench * D.season.map(Lfrac).fillna(0) / D.g_use.clip(lower=.3) * 0 + 0) , D.g_use)
    # games share - expected share lost: g_new = g_old - p x (avg games lost when benched)/G, relative to the base-rate already priced in
    base_rate = {Y: D.benched[S1 & (D.season < Y)].mean() for Y in PM.TEST_YEARS}
    D["g_mult"] = np.where((D.pos == "QB") & (D.is_qb1 == 1) & D.p_bench.notna(),
                           (D.g_use - (D.p_bench - D.season.map(base_rate)) * D.season.map(Lfrac)).clip(.05, 1), D.g_use)
    O2 = GM.walk(D.assign(p_bench_f=np.where((D.pos == "QB") & (D.is_qb1 == 1), D.p_bench, 0.0)), [f if f != "gs1" else "gs1_shrunk" for f in GM.GF] + ["p_bench_f"], "pb")
    D["g_feat"] = np.where(D.pos == "QB", 0.75 * O2.pb_ridge + 0.25 * O2.pb_dist, D.g_use)
    for gcol in ("g_use", "g_mult", "g_feat"):
        P(f"  {gcol}:")
        for nm, mk in (("dev pool", pool & D.season.isin(Q.DEV)), ("holdout pool", pool & D.season.isin(Q.HOLD)), ("job threat (round-1 QB)", pool & (D.team_r1qb == 1)),
                       ("high pick behind (rd 1-2, this/last yr)", pool & (D.comp_hi == 1) & (D.is_qb1 == 1)), ("backups who took over", pool & (D.is_qb1 == 0)), ("back from a short season", pool & (D.short1 == 1)),
                       ("actually benched (outcome)", pool & (D.benched == 1))):
            mm = mk & D[gcol].notna()
            p = D[gcol][mm] * D.G[mm]; a = D.act_games[mm]
            P(f"    {nm:40s} n {int(mm.sum()):3d}: pred {p.mean():5.1f} vs act {a.mean():5.1f} | MAE {np.mean(np.abs(p - a)):.2f} | corr {np.corrcoef(p, a)[0,1]:.3f}")
    # season totals (QB)
    P("\n=== QB season totals ===")
    for gcol in ("g_use", "g_mult", "g_feat"):
        D[f"tot_{gcol}"] = D.pg * D[gcol] * D.G
    def tgrade(col, mask, lab):
        m = mask & D[col].notna()
        rh, h12, h24 = [], [], []
        for y, g in D[m].groupby("season"):
            if len(g) < 20: continue
            rh.append(spearmanr(g[col], g.act_total).correlation)
            h12.append(len(set(g.nlargest(12, col).pid) & set(g.nlargest(12, "act_total").pid)) / 12)
            h24.append(len(set(g.nlargest(24, col).pid) & set(g.nlargest(24, "act_total").pid)) / 24)
        P(f"    {lab:44s} n {int(m.sum()):3d} | MAE {np.mean(np.abs(D[col][m]-D.act_total[m])):6.1f} | rho {np.mean(rh):.3f} | top12 {np.mean(h12):.3f} | top24 {np.mean(h24):.3f}")
    for nm, mk in (("dev", pool & D.season.isin(Q.DEV)), ("holdout", pool & D.season.isin(Q.HOLD))):
        for col in ("tot_g_use", "tot_g_mult", "tot_g_feat"): tgrade(col, mk, f"{nm} {col}")
        tgrade("adp_total", mk & D.adp.notna(), f"{nm} ADP (QBs with ADP)")
        tgrade("tot_g_use", mk & D.adp.notna(), f"{nm} base, same QBs with ADP")
        tgrade("tot_g_mult", mk & D.adp.notna(), f"{nm} g_mult, same QBs with ADP")
    # superflex band QB13-28 (by the model's own projected total each season)
    D["qbrank"] = D[pool].groupby("season").tot_g_use.rank(ascending=False)
    band = pool & D.qbrank.between(13, 28)
    for col in ("tot_g_use", "tot_g_mult", "tot_g_feat"):
        m = band & D[col].notna()
        P(f"    superflex band QB13-28 {col:12s}: MAE {np.mean(np.abs(D[col][m]-D.act_total[m])):.1f} | rho (pooled) {spearmanr(D[col][m], D.act_total[m]).correlation:.3f} (n {int(m.sum())})")
    D[["season", "pid", "name", "team", "pos", "is_qb1", "p_bench", "benched", "healthy_lost_wks", "g_use", "g_mult", "g_feat", "comp_hi", "money"]].to_parquet(os.path.join(HERE, "data", "qb_a11_rows.parquet"), index=False)
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
