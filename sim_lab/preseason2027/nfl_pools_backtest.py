#!/usr/bin/env python3
"""
2026-11-21 review - NFL game pools from the closing market (pick'em straight-up / confidence / ATS, survivor), 2013-2025.
Only what was known at pick time: the closing line of the week being picked (nflverse schedules: spread_line, moneylines),
Elo through the previous week, preseason market ratings (win totals) for weeks with no line yet.
Writes nfl_pools.log. Read-only on everything else.
"""
import os, time
import numpy as np
import pandas as pd
from scipy.stats import norm as N
from scipy.optimize import linear_sum_assignment
import team_sims as TS

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = None   # opened by main(); importing this module never truncates nfl_pools.log
LOG_NAME = "nfl_pools.log"
RNG = np.random.default_rng(11)


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def imp(o): return np.where(o > 0, 100 / (o + 100), np.where(o < 0, -o / (-o + 100), 0.5))


def main():
    global LOG
    LOG = open(os.path.join(HERE, LOG_NAME), "w", encoding="utf-8")
    t0 = time.time()
    S = TS.games(); WT = TS.win_totals()
    S = S[S.season >= 2013].copy()
    ph, pa = imp(S.home_moneyline.fillna(0).values), imp(S.away_moneyline.fillna(0).values)
    S["p_ml"] = ph / (ph + pa)
    G0 = TS.games(); sdm = {Y: float((G0[G0.season < Y].margin - G0[G0.season < Y].spread_line).std()) for Y in range(2013, 2026)}
    S["sd"] = S.season.map(sdm)
    S["p_sp"] = N.cdf(S.spread_line / S.sd)
    # Elo pre-game probabilities (no market)
    _, EG = TS.elo_history(TS.games()); S = S.merge(EG[["game_id", "p"]].rename(columns={"p": "p_elo"}), on="game_id", how="left")
    S["home_win"] = (S.margin > 0).astype(float) + 0.5 * (S.margin == 0)
    P("=== Pick'em, 2013-2025 regular season ===")
    for lab, c in (("de-vigged moneyline", "p_ml"), ("closing spread (normal)", "p_sp"), ("Elo (no market)", "p_elo")):
        fav = np.where(S[c] >= .5, S.home_win, 1 - S.home_win)
        per = pd.Series(fav).groupby(S.season.values).mean()
        P(f"  straight-up, pick the {lab} favourite: {fav.mean()*100:.1f}% (season range {per.min()*100:.1f}-{per.max()*100:.1f}%) | Brier {np.mean((S[c]-S.home_win)**2):.4f}")
    # confidence pool: points = rank within week (1..n), expected vs actual
    rows = []
    for (Y, w), g in S.groupby(["season", "week"]):
        n = len(g)
        for lab, c in (("ml", "p_ml"), ("elo", "p_elo")):
            conf = np.maximum(g[c], 1 - g[c]).values; correct = np.where(g[c] >= .5, g.home_win, 1 - g.home_win)
            rk = conf.argsort().argsort() + 1
            rows.append({"season": Y, "week": w, "model": lab, "exp": float(np.sum(rk * conf)), "act": float(np.sum(rk * correct)), "max": n * (n + 1) / 2})
    C = pd.DataFrame(rows)
    for lab in ("ml", "elo"):
        x = C[C.model == lab]
        P(f"  confidence pool ranked by {lab}: expected {x.exp.sum()/x['max'].sum()*100:.1f}% of max points, actual {x.act.sum()/x['max'].sum()*100:.1f}% | per-week sd of actual {(x.act/x['max']).std()*100:.1f} pts of %")
    d = C.pivot_table(index=["season", "week"], columns="model", values="act")
    P(f"  ML-ranked beats Elo-ranked in {np.mean(d.ml > d.elo)*100:.0f}% of weeks, ties {np.mean(d.ml == d.elo)*100:.0f}%; season totals ML ahead in {int((d.groupby(level=0).sum().pipe(lambda t: t.ml > t.elo)).sum())}/13")
    # ATS: does Elo's margin beat the closing spread?
    S["elo_margin"] = np.log10(S.p_elo / (1 - S.p_elo)) * 400 / 25    # Elo diff in points
    ok = S.spread_line.notna() & (S.margin != S.spread_line)
    edge = S.elo_margin - S.spread_line
    pick_home = edge > 0; cover = S.margin > S.spread_line
    hit = (pick_home == cover)[ok]
    P(f"  ATS: Elo side vs closing spread {hit.mean()*100:.1f}% (n {int(ok.sum())}, break-even 52.4% at -110)")
    for th in (1.5, 3, 5):
        m = ok & (edge.abs() >= th)
        P(f"    |Elo - close| >= {th}: {((pick_home == cover)[m]).mean()*100:.1f}% (n {int(m.sum())})")
    per = (pick_home == cover)[ok].groupby(S.season[ok]).mean()
    P(f"    by season: " + " ".join(f"{y}:{v*100:.0f}" for y, v in per.items()))
    P(f"  home team ATS {cover[ok].mean()*100:.1f}%; favourite ATS {((S.spread_line > 0) == cover)[ok & (S.spread_line != 0)].mean()*100:.1f}%")

    # ---------------- survivor
    P("\n=== Survivor 2013-2025 (one team per week, each team once; weeks 1 to last-1) ===")
    res = []
    for Y in range(2013, 2026):
        g = S[S.season == Y]; weeks = sorted(g.week.unique())[:-1]
        sd = float(g.sd.iloc[0]); mr, hfa = TS.market_ratings(G0, WT[WT.season == Y], Y, sd)
        # probability table: team x week. closing line for the week being picked; preseason market rating for later weeks
        teams = sorted(TS.TEAM_DIV); ix = {t: i for i, t in enumerate(teams)}
        Pclose = np.zeros((32, len(weeks))); Ppre = np.zeros((32, len(weeks))); WIN = np.full((32, len(weeks)), np.nan)
        for j, w in enumerate(weeks):
            for x in g[g.week == w].itertuples(index=False):
                h, a = ix[x.home_team], ix[x.away_team]
                Pclose[h, j], Pclose[a, j] = x.p_ml, 1 - x.p_ml
                pp = N.cdf((mr[x.home_team] - mr[x.away_team] + (0 if x.neutral else hfa)) / sd); Ppre[h, j], Ppre[a, j] = pp, 1 - pp
                WIN[h, j], WIN[a, j] = x.home_win, 1 - x.home_win
        for strat in ("greedy", "plan"):
            used = set(); alive = True; wk_out = len(weeks); logp = 0.0; picks = []
            for j in range(len(weeks)):
                avail = [i for i in range(32) if i not in used and Pclose[i, j] > 0]
                if strat == "greedy":
                    pick = max(avail, key=lambda i: Pclose[i, j])
                else:
                    # assignment over remaining weeks: this week = closing line, later = preseason market ratings
                    rem = list(range(j, len(weeks))); cand = [i for i in range(32) if i not in used]
                    M = np.full((len(cand), len(rem)), 50.0)
                    for a_, i in enumerate(cand):
                        for b_, jj in enumerate(rem):
                            p = Pclose[i, jj] if jj == j else Ppre[i, jj]
                            if p > 0: M[a_, b_] = -np.log(max(p, 1e-3))
                    r_, c_ = linear_sum_assignment(M)
                    pick = cand[r_[list(c_).index(0)]]
                used.add(pick); picks.append(pick); logp += np.log(Pclose[pick, j])
                if alive and WIN[pick, j] < 1:
                    alive = False; wk_out = j
            res.append({"season": Y, "strat": strat, "weeks_survived": wk_out, "exp_logp": logp, "picks": picks, "n_weeks": len(weeks)})
    R = pd.DataFrame(res)
    for strat in ("greedy", "plan"):
        x = R[R.strat == strat]
        P(f"  {strat:6s}: weeks survived (actual results) mean {x.weeks_survived.mean():.1f}, median {x.weeks_survived.median():.0f}, by season {list(x.weeks_survived)}")
        P(f"          P(survive all weeks) from the closing lines: mean {np.mean(np.exp(x.exp_logp))*100:.2f}%; P(survive 10 weeks) see below")
    # replay with simulated outcomes (5000 per season) to measure expected survival length per strategy
    sims = []
    for r in R.itertuples(index=False):
        g = S[S.season == r.season]; weeks = sorted(g.week.unique())[:-1]
        teams = sorted(TS.TEAM_DIV); ix = {t: i for i, t in enumerate(teams)}
        pv = []
        for j, w in enumerate(weeks):
            pk = r.picks[j]
            row = g[(g.week == w) & ((g.home_team == teams[pk]) | (g.away_team == teams[pk]))].iloc[0]
            pv.append(row.p_ml if row.home_team == teams[pk] else 1 - row.p_ml)
        pv = np.array(pv); u = RNG.random((5000, len(pv))) < pv
        surv = np.argmin(np.column_stack([u, np.zeros((5000, 1), bool)]), axis=1)
        sims.append({"season": r.season, "strat": r.strat, "exp_weeks": surv.mean(), "p10": np.mean(surv >= 10), "p_all": np.mean(surv >= len(pv))})
    Q = pd.DataFrame(sims)
    for strat in ("greedy", "plan"):
        x = Q[Q.strat == strat]
        P(f"  {strat:6s} simulated (5000 x 13 seasons, outcomes drawn from the closing line): expected weeks {x.exp_weeks.mean():.2f}, P(10+ weeks) {x.p10.mean()*100:.1f}%, P(all) {x.p_all.mean()*100:.2f}%")
    a = Q[Q.strat == "plan"].set_index("season").exp_weeks; b = Q[Q.strat == "greedy"].set_index("season").exp_weeks
    P(f"  plan beats greedy on expected weeks in {int((a > b).sum())}/13 seasons (avg +{(a - b).mean():.2f} weeks)")
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
