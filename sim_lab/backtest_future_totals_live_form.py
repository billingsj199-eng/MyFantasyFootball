#!/usr/bin/env python3
"""
The EXACT live form of build_future_totals.py on past seasons, injuries included (Jack 2026-09-30:
"make sure we test update team totals with past seasons and include injuries").

Same data and grading as backtest_future_totals.py (2019-25 closing lines, proxy preseason view), but
the shift is fit the way the live builder fits it:
  * offense shift per TEAM x QUARTERBACK (the quarterback = whoever threw the team's first pass that
    game), defense shift per team, ridge 2.0, recency half-life 2 weeks, cap 4 points per side
  * a future game takes the shift measured with the quarterback who plays it; a quarterback with no
    lines of his own yet gets none
  * the weather discount (-0.7 wind 15+, -0.5 wind 10-15 / rain / snow, outdoors) is taken out of a
    line before the shift is measured
Future quarterbacks are the ones who actually started (live uses the injury windows instead).
Compared with: no shift, the shift WITHOUT quarterback context (v1), and the live form.
Log future_totals_live_form.log.
"""
import os, sys, re
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_future_totals as F
import build_future_totals as B
LAM, HL, CAP = B.LAM, B.HL, B.CAP

def ctx(Y):
    cp = os.path.join(HERE, "data", f"_linesqb_{Y}.pkl")
    if os.path.exists(cp): return pd.read_pickle(cp)
    d = pd.read_csv(os.path.join(F.CACHE, f"play_by_play_{Y}.csv.gz"), low_memory=False,
                    usecols=["game_id", "play_id", "season_type", "week", "posteam", "home_team", "roof", "wind", "weather", "passer_player_name", "pass_attempt"])
    d = d[d.season_type == "REG"]
    p = d[(d.pass_attempt == 1) & d.passer_player_name.notna()].sort_values(["game_id", "play_id"]).groupby(["posteam", "week"]).first().reset_index()
    qb = pd.DataFrame({"team": p.posteam.map(F.tm), "wk": p.week.astype(int), "qb": p.passer_player_name.map(B.qkey)})
    g = d.dropna(subset=["home_team"]).groupby("game_id").first().reset_index()
    wind = pd.to_numeric(g.wind, errors="coerce").fillna(0)
    wet = g.weather.astype(str).str.contains(r"rain|snow|shower|sleet|storm", case=False, regex=True)
    indoor = g.roof.astype(str).isin(["dome", "closed"])
    wx = pd.DataFrame({"hteam": g.home_team.map(F.tm), "wk": g.week.astype(int),
                       "wx": np.where(indoor, 0.0, np.where(wind >= 15, B.WX_WIND15, np.where((wind >= 10) | wet, B.WX_MILD, 0.0)))})
    out = (qb, wx); pd.to_pickle(out, cp); return out

def fit(obs, d, w, qbaware):
    ent = (obs.team + "|" + obs.qb).values if qbaware else obs.team.values
    ents = sorted(set(ent)); teams = sorted(set(obs.opp) | set(obs.team)); ne, n = len(ents), len(teams)
    ei = {e: i for i, e in enumerate(ents)}; ix = {t: i for i, t in enumerate(teams)}
    X = np.zeros((len(obs), ne + n)); r = np.arange(len(obs))
    X[r, [ei[e] for e in ent]] = 1; X[r, ne + obs.opp.map(ix).values] = 1
    A = X * np.sqrt(w)[:, None]; b = d * np.sqrt(w)
    beta = np.clip(np.linalg.solve(A.T @ A + LAM * np.eye(ne + n), A.T @ b), -CAP, CAP)
    O = dict(zip(ents, beta[:ne])); D = dict(zip(teams, beta[ne:]))
    def pred(rows):
        e = (rows.team + "|" + rows.qb).values if qbaware else rows.team.values
        return np.array([O.get(x, 0.0) for x in e]) + np.array([D.get(x, 0.0) for x in rows.opp.values])
    return pred

def fit_hier(obs, d, w, lam_q, lam_t=LAM):
    """offense = TEAM shift (shared by all his quarterbacks) + a deviation per quarterback; defense per team."""
    ent = (obs.team + "|" + obs.qb).values
    ents = sorted(set(ent)); teams = sorted(set(obs.opp) | set(obs.team)); ne, n = len(ents), len(teams)
    ei = {e: i for i, e in enumerate(ents)}; ix = {t: i for i, t in enumerate(teams)}
    X = np.zeros((len(obs), n + ne + n)); r = np.arange(len(obs))
    X[r, obs.team.map(ix).values] = 1; X[r, [n + ei[e] for e in ent]] = 1; X[r, n + ne + obs.opp.map(ix).values] = 1
    pen = np.r_[np.full(n, lam_t), np.full(ne, lam_q), np.full(n, LAM)]
    A = X * np.sqrt(w)[:, None]; b = d * np.sqrt(w)
    beta = np.linalg.solve(A.T @ A + np.diag(pen), A.T @ b)
    T = dict(zip(teams, beta[:n])); Q = dict(zip(ents, beta[n:n + ne])); D = dict(zip(teams, beta[n + ne:]))
    def pred(rows):
        e = (rows.team + "|" + rows.qb).values
        o = np.clip(np.array([T.get(a, 0.0) for a in rows.team.values]) + np.array([Q.get(x, 0.0) for x in e]), -CAP, CAP)
        return o + np.clip(np.array([D.get(x, 0.0) for x in rows.opp.values]), -CAP, CAP)
    return pred

HIER = (0.25, 0.5, 1.0, 2.0, 4.0)
def main():
    sys.stdout = F.Tee(sys.__stdout__, open(os.path.join(HERE, "future_totals_live_form.log"), "w", encoding="utf-8"))
    print("=== live form of the future-totals re-rate on 2019-25 (team x quarterback shifts, weather taken out) ===")
    L = {Y: F.long(F.load_year(Y)) for Y in range(2018, 2026)}
    years = list(range(2019, 2026)); rec = []
    for Y in years:
        cur, prev = L[Y], L[Y - 1]; teams = sorted(set(cur.team))
        tr = pd.concat([prev[prev.wk >= 10].assign(w=0.35), cur[cur.wk == 1].assign(w=1.0)], ignore_index=True)
        tr = tr[tr.team.isin(teams) & tr.opp.isin(teams)]
        m = F.ridge_od(tr, tr.imp.values, tr.w.values, teams, 1.5)
        cur = cur.copy(); cur["p0"] = F.predict(m, cur) + (cur[cur.wk == 1].imp.mean() - F.predict(m, cur[cur.wk == 1]).mean())
        qb, wx = ctx(Y)
        cur = cur.merge(qb, on=["team", "wk"], how="left"); cur["qb"] = cur.qb.fillna("x")
        cur["hteam"] = np.where(cur.home == 1, cur.team, cur.opp)
        cur = cur.merge(wx, on=["hteam", "wk"], how="left"); cur["wx"] = cur.wx.fillna(0.0)
        opener = cur[cur.wk == cur.groupby("team").wk.transform("min")].set_index("team").qb
        cur["is_opener"] = cur.qb.values == cur.team.map(opener).values
        for W in (2, 3, 4, 6, 8, 10, 12):
            obs = cur[(cur.wk >= 2) & (cur.wk <= W)]; fut = cur[cur.wk > W].copy()
            if obs.empty or fut.empty: continue
            w = 0.5 ** ((W - obs.wk.values) / HL); d = (obs.imp - obs.p0).values
            seen = set((obs.team + "|" + obs.qb).values)
            had_other = set(obs[~obs.is_opener].team)
            fut["v1"] = fut.p0.values + fit(obs, d, w, False)(fut)
            fut["live"] = fut.p0.values + fit(obs, d - obs.wx.values, w, True)(fut)
            for lq in HIER: fut[f"h{lq}"] = fut.p0.values + fit_hier(obs, d - obs.wx.values, w, lq)(fut)
            fut["case"] = np.where(~fut.is_opener, np.where((fut.team + "|" + fut.qb).isin(seen), "backup / new QB, already has lines", "backup / new QB, no lines yet"),
                                   np.where(fut.team.isin(had_other), "opening starter back after other QBs played", "opening starter all along"))
            fut["year"] = Y; fut["W"] = W; rec.append(fut)
    R = pd.concat(rec, ignore_index=True)
    def table(title, x):
        if len(x) < 120: print(f"\n  {title}: n={len(x)} (too few)"); return
        a0 = np.abs(x.p0 - x.imp).mean(); q0 = ((x.p0 - x.pts) ** 2).mean()
        print(f"\n  {title}  (n={len(x)} team-games)")
        print(f"    {'no shift (preseason view)':34s} miss vs closing line {a0:.3f}")
        for name, lab in [("v1", "shift, no quarterback context"), ("live", "separate per quarterback")] + [(f"h{lq}", f"TEAM + quarterback deviation, lam {lq}") for lq in HIER]:
            a = np.abs(x[name] - x.imp).mean(); q = ((x[name] - x.pts) ** 2).mean()
            w0 = sum(1 for Y in years if (x.year == Y).sum() > 15 and np.abs(x[x.year == Y][name] - x[x.year == Y].imp).mean() < np.abs(x[x.year == Y].p0 - x[x.year == Y].imp).mean())
            ny = sum(1 for Y in years if (x.year == Y).sum() > 15)
            extra = ""
            if name != "v1":
                a1 = np.abs(x.v1 - x.imp).mean(); q1 = ((x.v1 - x.pts) ** 2).mean()
                w1 = sum(1 for Y in years if (x.year == Y).sum() > 15 and np.abs(x[x.year == Y][name] - x[x.year == Y].imp).mean() < np.abs(x[x.year == Y].v1 - x[x.year == Y].imp).mean())
                extra = f" | vs no-context shift {100*(a/a1-1):+.1f}% ({w1}/{ny}), points MSE {100*(q/q1-1):+.2f}%"
            print(f"    {lab:34s} miss vs closing line {a:.3f}  {100*(a/a0-1):+.1f}% ({w0}/{ny} seasons) | points-scored MSE {100*(q/q0-1):+.2f}%{extra}")
    table("ALL future games, every checkpoint", R)
    for W in (2, 4, 8, 12): table(f"standing after week {W}", R[R.W == W])
    for c in ("opening starter back after other QBs played", "backup / new QB, already has lines", "backup / new QB, no lines yet", "opening starter all along"):
        table(f"quarterback case: {c}", R[R.case == c])
    table("standing after week 4: opening starter back after other QBs played (the Bears case)", R[(R.W == 4) & (R.case == "opening starter back after other QBs played")])
    print("\n  by how far ahead the game is (live form vs no shift):")
    R["h"] = R.wk - R.W
    for lab, lo, hi in (("next week", 1, 1), ("2-4 weeks ahead", 2, 4), ("5-8 weeks ahead", 5, 8), ("9+ weeks ahead", 9, 99)):
        x = R[(R.h >= lo) & (R.h <= hi)]
        print(f"    {lab:16s} n={len(x):5d}  {np.abs(x.p0-x.imp).mean():.2f} -> {np.abs(x.live-x.imp).mean():.2f} ({100*(np.abs(x.live-x.imp).mean()/np.abs(x.p0-x.imp).mean()-1):+.1f}%)   no-context shift {np.abs(x.v1-x.imp).mean():.2f}")

if __name__ == "__main__":
    main()
