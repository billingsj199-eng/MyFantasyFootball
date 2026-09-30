#!/usr/bin/env python3
"""
CONTEXT for the future-totals re-rate (Jack 2026-09-29: "make sure there is context of injuries - the
Bears had a bad weather week 2 and their QB got hurt and is out weeks 4-5").

A line posted for a backup quarterback, or for a game in wind / rain, says little about the same team
with its starter back in normal weather. Tested on 2019-25 closing lines (same proxy preseason view and
grading as backtest_future_totals.py):

  A  shift from every in-season line                      (what build_future_totals.py did)
  B  QB-aware: the offense shift is kept separately for "starter playing" and "backup playing"
     (starter = the team's opening-day quarterback; he counts as playing if he threw a pass), plus one
     league-wide backup effect for a backup who has no lines of his own yet
  C  weather-aware: lines for games in wind 15+ mph are dropped, wind 10-15 or rain / snow count half
  D  B + C
Future games use the quarterback who actually played (live: the injury windows). Graded on all future
games and on the cases that matter: the starter is back after backup weeks, and backup games.
Log future_totals_context.log.
"""
import os, sys, re
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_future_totals as F
CACHE = F.CACHE

def ctx_year(Y):
    cp = os.path.join(HERE, "data", f"_linesctx_{Y}.pkl")
    if os.path.exists(cp) and Y < 2026: return pd.read_pickle(cp)
    d = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), low_memory=False,
                    usecols=["game_id", "season_type", "week", "posteam", "home_team", "roof", "wind", "weather", "passer_player_name", "pass_attempt"])
    d = d[d.season_type == "REG"]
    q = d[(d.pass_attempt == 1) & d.passer_player_name.notna()].groupby(["posteam", "week", "passer_player_name"]).size().rename("att").reset_index()
    q["team"] = q.posteam.map(F.tm)
    first = q[q.week == q.groupby("team").week.transform("min")].sort_values("att", ascending=False).drop_duplicates("team").set_index("team").passer_player_name
    rows = []
    for (t, w), x in q.groupby(["team", "week"]):
        rows.append({"team": t, "wk": int(w), "starter": int(first.get(t) in set(x.passer_player_name))})
    qs = pd.DataFrame(rows)
    g = d.dropna(subset=["home_team"]).groupby("game_id").first().reset_index()
    wx = pd.DataFrame({"wk": g.week.astype(int), "hteam": g.home_team.map(F.tm), "wind": pd.to_numeric(g.wind, errors="coerce"),
                       "wet": g.weather.astype(str).str.contains(r"rain|snow|shower|sleet|storm", case=False, regex=True),
                       "indoor": g.roof.astype(str).isin(["dome", "closed"])})
    out = (qs, wx)
    if Y < 2026: pd.to_pickle(out, cp)
    return out

def attach(cur, Y):
    qs, wx = ctx_year(Y)
    cur = cur.merge(qs, on=["team", "wk"], how="left")
    cur["starter"] = cur.starter.fillna(1).astype(int)
    cur["hteam"] = np.where(cur.home == 1, cur.team, cur.opp)
    cur = cur.merge(wx, on=["wk", "hteam"], how="left")
    wind = cur.wind.fillna(0); wet = cur.wet.fillna(False) & ~cur.indoor.fillna(False)
    cur["wxw"] = np.where(cur.indoor.fillna(False), 1.0, np.where(wind >= 15, 0.0, np.where((wind >= 10) | wet, 0.5, 1.0)))
    return cur

def fit(obs, delta, w, teams, lam, qb, wxcov=False):
    """delta ~ O[team (|state)] + D[opp] (+ b x backup). Returns predictor(rows)."""
    n = len(teams); ix = {t: i for i, t in enumerate(teams)}
    k = (3 * n + 1) if qb else 2 * n
    k0 = k
    if wxcov: k += 2
    X = np.zeros((len(obs), k)); ti = obs.team.map(ix).values; oi = obs.opp.map(ix).values; st = obs.starter.values
    r = np.arange(len(obs))
    if qb:
        X[r, np.where(st == 1, ti, 2 * n + ti)] = 1; X[r, n + oi] = 1; X[:, 3 * n] = (st == 0)
    else:
        X[r, ti] = 1; X[r, n + oi] = 1
    if wxcov: X[:, k0] = (obs.wxw.values == 0); X[:, k0 + 1] = (obs.wxw.values == 0.5)   # weather absorbed, never carried forward
    pen = np.full(k, lam)
    if wxcov: pen[k0:] = 0.25
    if qb: pen[3 * n] = 0.25
    A = X * np.sqrt(w)[:, None]; b = delta * np.sqrt(w)
    beta = np.linalg.solve(A.T @ A + np.diag(pen), A.T @ b)
    def pred(rows):
        ti = rows.team.map(ix).values; oi = rows.opp.map(ix).values; st = rows.starter.values
        if qb: return np.where(st == 1, beta[ti], beta[2 * n + ti] + beta[3 * n]) + beta[n + oi]
        return beta[ti] + beta[n + oi]
    return pred, (beta[3 * n] if qb else None)

def main():
    sys.stdout = F.Tee(sys.__stdout__, open(os.path.join(HERE, "future_totals_context.log"), "w", encoding="utf-8"))
    print("=== context for the future-totals shift, 2019-25 closing lines ===")
    L = {Y: F.long(F.load_year(Y)) for Y in range(2018, 2026)}
    years = list(range(2019, 2026)); P0 = {}
    for Y in years:
        cur, prev = L[Y], L[Y - 1]; teams = sorted(set(cur.team))
        tr = pd.concat([prev[prev.wk >= 10].assign(w=0.35), cur[cur.wk == 1].assign(w=1.0)], ignore_index=True)
        tr = tr[tr.team.isin(teams) & tr.opp.isin(teams)]
        m = F.ridge_od(tr, tr.imp.values, tr.w.values, teams, 1.5)
        cur = cur.copy(); cur["p0"] = F.predict(m, cur) + (cur[cur.wk == 1].imp.mean() - F.predict(m, cur[cur.wk == 1]).mean())
        P0[Y] = attach(cur, Y)
    allr = pd.concat(P0.values())
    print(f"  team-games: {len(allr)}; backup quarterback played in {100*(allr.starter==0).mean():.1f}%; wind 15+ {100*(allr.wxw==0).mean():.1f}%, wind 10-15 or wet {100*(allr.wxw==0.5).mean():.1f}%")
    d0 = allr[allr.wk >= 2]
    print(f"  closing line minus preseason view: starter games {(d0[d0.starter==1].imp-d0[d0.starter==1].p0).mean():+.2f}, backup games {(d0[d0.starter==0].imp-d0[d0.starter==0].p0).mean():+.2f}; "
          f"wind 15+ {(d0[d0.wxw==0].imp-d0[d0.wxw==0].p0).mean():+.2f}, wind 10-15 / wet {(d0[d0.wxw==.5].imp-d0[d0.wxw==.5].p0).mean():+.2f}, clean {(d0[d0.wxw==1].imp-d0[d0.wxw==1].p0).mean():+.2f}")
    LAM, HL = 1.0, 2.0
    VAR = {"A all lines": (False, False), "B QB-aware": (True, False), "C weather-aware": (False, True), "D both": (True, True), "E QB-aware + weather absorbed": (True, "cov")}
    rec = []; bk = []
    for Y in years:
        cur = P0[Y]; teams = sorted(set(cur.team))
        for W in (2, 3, 4, 6, 8, 10, 12):
            obs = cur[(cur.wk >= 2) & (cur.wk <= W)]; fut = cur[cur.wk > W].copy()
            if obs.empty or fut.empty: continue
            had_backup = set(obs[obs.starter == 0].team)
            fut["case"] = np.where(fut.starter == 0, "backup plays", np.where(fut.team.isin(had_backup), "starter back after backup weeks", "starter all along"))
            fut["opp_case"] = fut.opp.isin(had_backup)
            base = 0.5 ** ((W - obs.wk.values) / HL); d = (obs.imp - obs.p0).values
            for name, (qb, wx) in VAR.items():
                w = base * (obs.wxw.values if wx is True else 1.0); keep = w > 0
                pred, b = fit(obs[keep], d[keep], w[keep], teams, LAM, qb, wxcov=(wx == 'cov'))
                fut[name] = fut.p0.values + pred(fut)
                if qb and not wx: bk.append(b)
            fut["year"] = Y; fut["W"] = W; rec.append(fut)
    R = pd.concat(rec, ignore_index=True)
    print(f"  league-wide backup effect fitted: {np.mean(bk):+.2f} points of implied total (avg over checkpoints)")
    def table(title, x):
        if len(x) < 150: print(f"\n  {title}: n={len(x)} (too few)"); return
        print(f"\n  {title}  (n={len(x)} team-games)")
        a0 = np.abs(x.p0 - x.imp).mean()
        print(f"    {'preseason view, no shift':26s} miss vs closing line {a0:.3f}")
        ref = None
        for name in VAR:
            a = np.abs(x[name] - x.imp).mean(); q = ((x[name] - x.pts) ** 2).mean()
            if ref is None: ref = (a, q, name)
            wins = sum(1 for Y in years if (x.year == Y).sum() > 20 and np.abs(x[x.year == Y][name] - x[x.year == Y].imp).mean() < np.abs(x[x.year == Y][ref[2]] - x[x.year == Y].imp).mean())
            tail = "" if name == ref[2] else f"   vs A: {100*(a/ref[0]-1):+.1f}% ({wins}/7 seasons), points-scored MSE {100*(q/ref[1]-1):+.2f}%"
            print(f"    {name:26s} miss vs closing line {a:.3f}  ({100*(a/a0-1):+.1f}% vs no shift){tail}")
    table("ALL future games", R)
    for c in ("starter back after backup weeks", "backup plays", "starter all along"): table(f"offense case: {c}", R[R.case == c])
    table("standing after week 4, all future games", R[R.W == 4])
    table("standing after week 4, starter back after backup weeks", R[(R.W == 4) & (R.case == "starter back after backup weeks")])

if __name__ == "__main__":
    main()
