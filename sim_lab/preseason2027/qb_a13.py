#!/usr/bin/env python3
"""
A13 - rookie-deal starters in A11's job-security model (Jack 2026-11-21 "Yes, test it"). In-house, no ADP input.
A11 reads cap share as the hold on the job; a QB on his rookie deal has a small cap share whatever his draft capital.
Rookie deal = drafted QB in deal years 1-4 (exp 0-3) whose contract in force is his Drafted/UDFA deal or none on disk.
(No fifth-year options or money owed: at-signing fields only, as A11.)
Candidates (fixed constants, chosen before looking at results):
  F0 A11:        money, comp_hi, exp_w
  F1 flag:       money only for veteran deals (0 on rookie deals) + rookie-deal flag, comp_hi, exp_w
  F2 draft cap:  F1 + rookie-deal x draft score (1 - log(pick)/log(262), UDFA = 0)
  F3 investment: inv = max(cap score, draft score x fade), cap score = min(1, money / .15), fade = max(0, 1 - exp/5)
                 (years 1..5 -> 1, .8, .6, .4, .2), replacing money; comp_hi, exp_w
Walk-forward 2015-25 (fit on earlier seasons), choices on 2015-22, 2023-25 is the viewed holdout. Log: qb_a13.log.
"""
import os, sys, time, warnings
import numpy as np, pandas as pd
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
    LOG = open(os.path.join(HERE, "qb_a13.log"), "w", encoding="utf-8"); Q.LOG = LOG; JS.LOG = LOG
    t0 = time.time()
    P("=== A13 rookie-deal starters in the A11 job-security model ===")
    D = PM.build(); AV, wk1 = GM.availability(); D = GM.add_features(D, AV, wk1)
    S = G.stat_seasons(); D = G.add_history(D, S); D = G.add_context(D, S); D = FX.add_fix1_features(D)
    R0 = PM.walk_forward(D)
    for c in ("ridge_stats", "adp_curve_f", "naive_f", "adp_total"): D[c] = R0[c].values
    O = GM.walk(D, [f if f != "gs1" else "gs1_shrunk" for f in GM.GF], "g"); D = pd.concat([D, O], axis=1); D["g_use"] = 0.75 * D.g_ridge + 0.25 * D.g_dist
    s7, _, _ = G.walk(D, Q.LEAN, "S7", use_role_prior=True); D["pg"] = (0.75 * s7 + 0.25 * D.ridge_stats).values
    W = pd.read_parquet(os.path.join(PM.DATA, "player_weeks.parquet"), columns=["season", "week", "pid", "att"])
    W = W[W.week < W.season.map(PM.final_week)]; stc = W[W.att >= 15].groupby(["season", "pid"]).size()
    D["starts"] = [stc.get((y, p), 0) for y, p in zip(D.season, D.pid)]
    pool = (D.pos == "QB") & D.season.isin(PM.TEST_YEARS) & ((D.is_qb1 == 1) | (D.starts >= 4))
    K, _ = JS.contracts_asof(range(2013, 2026))
    for f in ("apy_cap", "rookie_deal"):
        D[f"k_{f}"] = [K.get((y, p), {}).get(f, np.nan) for y, p in zip(D.season, D.pid)]
    D = JS.outcomes(D)
    S1 = (D.pos == "QB") & D.season.between(2013, 2025) & (D.is_qb1 == 1)
    D["benched"] = (D.healthy_lost_wks >= 2).astype(float)
    dp = pd.read_parquet(os.path.join(PM.CACHE, "draft_picks.parquet"), columns=["season", "pick", "team", "position", "gsis_id"]); dp["team"] = dp.team.map(PM.tm)
    hi = {}
    for r in dp[(dp.position == "QB") & (dp.pick <= 64)].itertuples(index=False):
        for yy in (r.season, r.season + 1): hi.setdefault((yy, r.team), set()).add(r.gsis_id)
    D["comp_hi"] = [float(len(hi.get((y, t), set()) - {p}) > 0) for y, t, p in zip(D.season, D.team, D.pid)]
    D["money"] = D.k_apy_cap
    # ---- rookie-deal definition
    drafted = (D.undrafted == 0) if "undrafted" in D else D.lpick.notna()
    D["rk"] = ((D.exp <= 3) & ((D.k_rookie_deal == 1) | D.k_rookie_deal.isna()) & (D.lpick.notna())).astype(float)
    D["deal_yr"] = D.exp + 1
    D["dscore"] = np.where(D.undrafted == 1, 0.0, (1 - D.lpick / np.log(262)).clip(0, 1))
    D["money_vet"] = np.where(D.rk == 1, 0.0, D.money)
    D["rk_draft"] = D.rk * D.dscore
    D["inv"] = np.maximum((D.money / .15).clip(0, 1).fillna(0), D.dscore * (1 - D.exp / 5).clip(lower=0))
    D.loc[D.money.isna() & (D.rk == 0), "inv"] = np.nan    # veteran with no contract on disk -> median impute, as A11
    D["rd"] = np.select([D.undrafted == 1, D.rd1 == 1, D.rd2 == 1, D.lpick <= np.log(96)], ["UDFA", "rd 1", "rd 2", "rd 3"], "rd 4-7")
    P(f"  week-1 QB1s 2013-25: {int(S1.sum())}; on a rookie deal (yrs 1-4): {int((S1 & (D.rk == 1)).sum())}; money missing among rookie-deal: {int((S1 & (D.rk == 1) & D.money.isna()).sum())}, among vets {int((S1 & (D.rk == 0) & D.money.isna()).sum())}")
    P(f"  cap share median: rookie-deal {D.money[S1 & (D.rk == 1)].median()*100:.1f}% | vets {D.money[S1 & (D.rk == 0)].median()*100:.1f}%")
    # ---- walk-forward probabilities
    sets = {"F0 A11 (money, comp_hi, exp_w)": ["money", "comp_hi", "exp_w"],
            "F1 rookie-deal flag": ["money_vet", "rk", "comp_hi", "exp_w"],
            "F2 flag + draft capital": ["money_vet", "rk", "rk_draft", "comp_hi", "exp_w"],
            "F3 one investment input": ["inv", "comp_hi", "exp_w"]}
    base_rate = {Y: D.benched[S1 & (D.season < Y)].mean() for Y in PM.TEST_YEARS}
    probs = {}
    for lab, F in sets.items():
        p = pd.Series(np.nan, index=D.index)
        for Y in PM.TEST_YEARS:
            tr = S1 & (D.season < Y); te = S1 & (D.season == Y)
            if tr.sum() < 60 or te.sum() == 0: continue
            p[te] = JS.logit_fit(D.loc[tr, F].values.astype(float), D.benched[tr].values, D.loc[te, F].values.astype(float))
        probs[lab] = p
    keys = list(sets)
    # ---- STEP 1: measured bench rates by sub-group (all 2013-25) + A11 predicted (2015-25 walk-forward)
    P("\n=== STEP 1. Week-1 QB1s benched while healthy (2+ games), actual 2013-25 with 90% range; A11 predicted on 2015-25 rows ===")
    rk = S1 & (D.rk == 1); vet = S1 & (D.rk == 0)
    cheap_v = vet & (D.money < .05)
    groups = [("rookie-deal, all", rk), ("  rd 1, deal yr 1-2", rk & (D.rd == "rd 1") & (D.deal_yr <= 2)), ("  rd 1, deal yr 3-4", rk & (D.rd == "rd 1") & (D.deal_yr >= 3)),
              ("  rd 2, any yr", rk & (D.rd == "rd 2")), ("  rd 3-7 + UDFA, any yr", rk & D.rd.isin(["rd 3", "rd 4-7", "UDFA"])),
              ("  deal yr 1", rk & (D.deal_yr == 1)), ("  deal yr 2", rk & (D.deal_yr == 2)), ("  deal yr 3", rk & (D.deal_yr == 3)), ("  deal yr 4", rk & (D.deal_yr == 4)),
              ("veteran deal, all", vet), ("  vet, cap < 5% (same cheap money)", cheap_v), ("  vet, cap < 2%", vet & (D.money < .02)), ("  vet, cap 5-10%", vet & D.money.between(.05, .10)), ("  vet, cap >= 10%", vet & (D.money >= .10))]
    P("| group | n | benched actual | 90% range | A11 mean P (n walk-fwd) | A11 actual same rows |")
    P("|---|---|---|---|---|---|")
    for lab, mk in groups:
        n = int(mk.sum()); k = int(D.benched[mk].sum()); lo, hi_ = wilson(k, n)
        mw = mk & probs[keys[0]].notna()
        P(f"| {lab} | {n} | {k/max(n,1)*100:.1f}% | {lo*100:.0f}-{hi_*100:.0f} | {probs[keys[0]][mw].mean()*100:.1f}% ({int(mw.sum())}) | {D.benched[mw].mean()*100:.1f}% |")
    # ---- STEP 2: Brier, calibration by group
    P("\n=== STEP 2. P(bench) Brier (walk-forward) ===")
    for nm, yrs in (("dev 2015-22", Q.DEV), ("holdout 2023-25", Q.HOLD)):
        for lab in keys:
            p = probs[lab]; m = S1 & D.season.isin(yrs) & p.notna()
            b = D.season[m].map(base_rate)
            line = f"  {nm} {lab:32s}: all n {int(m.sum())} Brier {np.mean((p[m]-D.benched[m])**2):.4f} (base {np.mean((b-D.benched[m])**2):.4f})"
            for gl, gm in (("rookie-deal", D.rk == 1), ("vets", D.rk == 0)):
                mm = m & gm
                line += f" | {gl} n {int(mm.sum())} Brier {np.mean((p[mm]-D.benched[mm])**2):.4f} meanP {p[mm].mean():.3f} act {D.benched[mm].mean():.3f}"
            P(line)
    P("\n  calibration by sub-group, all 2015-25 walk-forward rows: mean P per candidate vs actual")
    P("| group | n | actual | " + " | ".join(k.split(" ")[0] for k in keys) + " |")
    P("|---|---|---|" + "---|" * len(keys))
    for lab, mk in groups:
        mw = mk & probs[keys[0]].notna()
        P(f"| {lab} | {int(mw.sum())} | {D.benched[mw].mean()*100:.1f}% | " + " | ".join(f"{probs[k][mw].mean()*100:.1f}%" for k in keys) + " |")
    for lab in keys:
        p = probs[lab]; m = S1 & p.notna()
        t = pd.DataFrame({"p": p[m], "y": D.benched[m]}); t["bin"] = pd.cut(t.p, [0, .05, .1, .2, .3, .5, 1])
        P(f"  bins {lab.split(' ')[0]}: " + " | ".join(f"{r.p:.2f}->{r.y:.2f} (n{r.n})" for r in t.groupby("bin", observed=True).agg(n=("y", "size"), p=("p", "mean"), y=("y", "mean")).itertuples()))
    # how much of A11's Brier came from the rookie-deal group
    p0 = probs[keys[0]]; m = S1 & p0.notna() & D.season.isin(Q.DEV)
    sq = (p0[m] - D.benched[m]) ** 2
    P(f"\n  A11 dev Brier share from rookie-deal rows: {sq[D.rk[m] == 1].sum()/sq.sum()*100:.1f}% of squared error from {(D.rk[m] == 1).mean()*100:.1f}% of rows")
    # ---- STEP 3: feed into games and totals
    P("\n=== STEP 3. Games and totals (A11 form: g = g_use - (P - base) x games lost when benched / 16.5) ===")
    Lfrac = {Y: max(0.0, (D.act_games[S1 & (D.season < Y) & (D.benched == 0)].mean() - D.act_games[S1 & (D.season < Y) & (D.benched == 1)].mean()) / 16.5) for Y in PM.TEST_YEARS}
    gcols = []
    for i, lab in enumerate(keys):
        c = f"g_F{i}"; gcols.append(c)
        D[c] = np.where((D.pos == "QB") & (D.is_qb1 == 1) & probs[lab].notna(), (D.g_use - (probs[lab] - D.season.map(base_rate)) * D.season.map(Lfrac)).clip(.05, 1), D.g_use)
        D[f"tot_{c}"] = D.pg * D[c] * D.G
    D["tot_g_use"] = D.pg * D.g_use * D.G
    allc = ["g_use"] + gcols
    for nm, mk in (("dev pool", pool & D.season.isin(Q.DEV)), ("holdout pool", pool & D.season.isin(Q.HOLD)),
                   ("rookie-deal starters", pool & (D.is_qb1 == 1) & (D.rk == 1)), ("  rd 1 yr 1-2", pool & (D.is_qb1 == 1) & (D.rk == 1) & (D.rd == "rd 1") & (D.deal_yr <= 2)),
                   ("  rd 1 yr 3-4", pool & (D.is_qb1 == 1) & (D.rk == 1) & (D.rd == "rd 1") & (D.deal_yr >= 3)), ("  rd 2+ / UDFA", pool & (D.is_qb1 == 1) & (D.rk == 1) & (D.rd != "rd 1")),
                   ("veteran starters", pool & (D.is_qb1 == 1) & (D.rk == 0)),
                   ("team drafted a rd-1 QB", pool & (D.team_r1qb == 1)), ("high pick behind him", pool & (D.comp_hi == 1) & (D.is_qb1 == 1)), ("back from a short season", pool & (D.short1 == 1))):
        line = f"  games {nm:26s} n {int(mk.sum()):3d} act {D.act_games[mk].mean():4.1f} |"
        for c in allc:
            p = D[c][mk] * D.G[mk]
            line += f" {c} {p.mean():4.1f} MAE {np.mean(np.abs(p - D.act_games[mk])):.2f} |"
        P(line)

    def tgrade(col, mask):
        m = mask & D[col].notna(); rh = []
        for y, g in D[m].groupby("season"):
            if len(g) >= 20: rh.append(spearmanr(g[col], g.act_total).correlation)
        return np.mean(np.abs(D[col][m] - D.act_total[m])), (np.mean(rh) if rh else spearmanr(D[col][m], D.act_total[m]).correlation), int(m.sum())
    P("")
    for nm, yrs in (("dev", Q.DEV), ("holdout", Q.HOLD)):
        mk = pool & D.season.isin(yrs)
        P(f"  totals {nm:7s} pool: " + " | ".join(f"{c} MAE {tgrade('tot_'+c, mk)[0]:.1f} rho {tgrade('tot_'+c, mk)[1]:.3f}" for c in allc) + f" (n {int(mk.sum())})")
        ma = mk & D.adp.notna()
        P(f"  totals {nm:7s} QBs with ADP: " + " | ".join(f"{c} MAE {tgrade('tot_'+c, ma)[0]:.1f} rho {tgrade('tot_'+c, ma)[1]:.3f}" for c in allc) + f" | ADP MAE {tgrade('adp_total', ma)[0]:.1f} rho {tgrade('adp_total', ma)[1]:.3f}")
        for gl, gm in (("rookie-deal starters", (D.is_qb1 == 1) & (D.rk == 1)), ("veteran starters", (D.is_qb1 == 1) & (D.rk == 0))):
            mg = mk & gm
            P(f"  totals {nm:7s} {gl}: " + " | ".join(f"{c} MAE {tgrade('tot_'+c, mg)[0]:.1f}" for c in allc) + f" (n {int(mg.sum())})")
    D["qbrank"] = D[pool].groupby("season").tot_g_use.rank(ascending=False)
    for nm, yrs in (("dev", Q.DEV), ("holdout", Q.HOLD), ("all", PM.TEST_YEARS)):
        band = pool & D.qbrank.between(13, 28) & D.season.isin(yrs)
        P(f"  superflex QB13-28 {nm:7s}: " + " | ".join(f"{c} MAE {np.mean(np.abs(D['tot_'+c][band]-D.act_total[band])):.1f} rho {spearmanr(D['tot_'+c][band], D.act_total[band]).correlation:.3f}" for c in allc) + f" (n {int(band.sum())})")
    out = D[S1][["season", "pid", "name", "team", "rk", "rd", "deal_yr", "money", "dscore", "inv", "comp_hi", "exp_w", "benched", "act_games"]].copy()
    for i, lab in enumerate(keys): out[f"p_F{i}"] = probs[lab][S1].values
    out.to_parquet(os.path.join(HERE, "data", "qb_a13_rows.parquet"), index=False)
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
