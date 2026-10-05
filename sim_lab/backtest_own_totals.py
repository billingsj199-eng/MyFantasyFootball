#!/usr/bin/env python3
"""
OUR OWN FUTURE TEAM TOTALS (Jack 2026-10-02: "those totals aren't necessarily true anymore as the books took them
down ... we need to make our own future team totals now based on data including each new week's team totals and
take into account current and future injuries").

Same harness as backtest_future_totals_live_form.py (2019-25 closing lines from the play-by-play, standing after
week W, grade the lines the book eventually closed at for every later game). The 2019-25 "preseason view" is
already a pure RATING (last season's final nine weeks + the week-1 lines) - no stale game lines exist for those
seasons - so the base here is exactly "our own totals": team offense / defense ratings moved by each new week's
lines, per quarterback, weather taken out. On top of that base this tests

  SKILL INJURIES   starters (preseason guide 8+ half-PPR a game, RB / WR / TE) who are out. The lines the book
                   posted while they were out are lifted back to healthy before the ratings are fit
                   (+ k x missing value), and every future game is docked by k x the value EXPECTED to be missing
                   that week:
                     oracle     who actually missed that game (ceiling - not knowable in advance)
                     realistic  players out as of the checkpoint x P(still out) from the shipped availability
                                curve by position; everyone else assumed healthy
  RESULTS          does what teams actually SCORED (points minus the implied total, recency-weighted) tell us
                   where the book's lines go next, beyond the lines already posted?

k and the results weight are picked leave-one-season-out. Log own_totals_backtest.log.
"""
import json, os, sys
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import backtest_future_totals as F
import backtest_future_totals_live_form as LF
import build_future_totals as B
import backtest_sim_calibration as cal
from backtest_sim_calibration import played, weekly_rec, infer_team
YEARS = list(range(2019, 2026)); CHECK = (2, 3, 4, 6, 8, 10, 12)
LAM_Q = 0.5
AVAIL_POS = {"RB": [0.677, 0.694, 0.719, 0.722, 0.765, 0.863, 0.821, 0.909], "WR": [0.609, 0.712, 0.764, 0.746, 0.727, 0.868, 0.874, 0.926],
             "TE": [0.634, 0.772, 0.799, 0.805, 0.720, 0.857, 0.843, 0.867]}

def absences():
    """rows: year, team, wk (a team game he missed after playing), name, pos, pg (guide half-PPR per game), k (missed so far incl. this one)"""
    cp = os.path.join(HERE, "data", "_own_totals_abs.pkl")
    if os.path.exists(cp): return pd.read_pickle(cp)
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8")); out = []
    for Y in YEARS:
        W = 16 if Y <= 2020 else 17
        for name, c in ch[str(Y)].items():
            pos = c.get("pos")
            if pos not in ("RB", "WR", "TE"): continue
            pg = max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2) / W
            if pg < 8: continue
            rec = weekly_rec(name, pos)
            if rec is None: continue
            team = infer_team(rec, Y)
            if not team: continue
            gw = sorted(int(w) for w in cal.SCHEDULES.get(Y, {}).get(team, {}) if 1 <= int(w) <= W + 1)
            pl = set(w["wk"] for w in rec.get("seasons", {}).get(str(Y), []) if played(w))
            seen = False; k = 0
            for w in gw:
                if w in pl: seen = True; k = 0; continue
                if not seen: continue
                k += 1
                out.append(dict(year=Y, team=F.tm(team), wk=w, name=name, pos=pos, pg=pg, k=k))
    d = pd.DataFrame(out); d.to_pickle(cp); return d

def base_rows():
    L = {Y: F.long(F.load_year(Y)) for Y in range(2018, 2026)}; A = absences(); out = {}
    for Y in YEARS:
        cur, prev = L[Y], L[Y - 1]; teams = sorted(set(cur.team))
        tr = pd.concat([prev[prev.wk >= 10].assign(w=0.35), cur[cur.wk == 1].assign(w=1.0)], ignore_index=True)
        tr = tr[tr.team.isin(teams) & tr.opp.isin(teams)]
        m = F.ridge_od(tr, tr.imp.values, tr.w.values, teams, 1.5)
        cur = cur.copy(); cur["p0"] = F.predict(m, cur) + (cur[cur.wk == 1].imp.mean() - F.predict(m, cur[cur.wk == 1]).mean())
        qb, wx = LF.ctx(Y)
        cur = cur.merge(qb, on=["team", "wk"], how="left"); cur["qb"] = cur.qb.fillna("x")
        cur["hteam"] = np.where(cur.home == 1, cur.team, cur.opp)
        cur = cur.merge(wx, on=["hteam", "wk"], how="left"); cur["wx"] = cur.wx.fillna(0.0)
        opener = cur[cur.wk == cur.groupby("team").wk.transform("min")].set_index("team").qb
        cur["is_opener"] = cur.qb.values == cur.team.map(opener).values
        a = A[A.year == Y]
        ms = a.groupby(["team", "wk"]).pg.sum().rename("miss").reset_index()
        cur = cur.merge(ms, on=["team", "wk"], how="left"); cur["miss"] = cur.miss.fillna(0.0)
        out[Y] = (cur, a)
    return out

def expected_missing(a, cur, W):
    """{(team, wk): expected missing value} for wk > W from the players out in week W (curve by position)"""
    exp = defaultdict(float)
    gw = {t: sorted(g.wk.unique()) for t, g in cur.groupby("team")}
    for r in a[a.wk == W].itertuples(index=False):
        surv = 1.0; j = 0
        for w in [x for x in gw.get(r.team, []) if x > W]:
            surv *= AVAIL_POS[r.pos][min(8, r.k + j) - 1]; j += 1
            exp[(r.team, w)] += r.pg * surv
            if j >= 8: break
    return exp

LIVE = False
def run():
    print()
    print("=== our own future team totals, 2019-25: ratings + quarterback + weather (shipped form) vs + skill injuries / + results"
          f" - {'LIVE TIMING (next week already lined)' if LIVE else 'lines through the checkpoint week only'} ===")
    BR = base_rows()
    allc = pd.concat([c for c, _ in BR.values()], ignore_index=True)
    print(f"  team-games: {len(allc)}; with a skill starter out: {100*(allc.miss>0).mean():.0f}%, average value missing when any {allc[allc.miss>0].miss.mean():.1f} pts")
    # raw read: how much lower is the closing line when starters are out (vs the preseason view + nothing else)?
    x = allc[allc.wk >= 2]; r = (x.imp - x.p0).values
    print("  closing line minus the preseason view, by skill value missing: " + "  ".join(
        f"{lab} {r[(x.miss.values >= lo) & (x.miss.values < hi)].mean():+.2f} (n {((x.miss >= lo) & (x.miss < hi)).sum()})" for lab, lo, hi in (("none", 0, .01), ("8-12", 8, 12), ("12-20", 12, 20), ("20+", 20, 999))))
    KS = (0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.13); GS = (0.0, 0.05, 0.10, 0.15, 0.20, 0.30); GB = (0.0, -1.0, -2.0, -3.0, -4.0)
    rec = []
    for Y in YEARS:
        cur, a = BR[Y]
        for W in CHECK:
            # LIVE TIMING: standing after week W the book has already posted week W + 1 (it has seen week W's
            # results), so the lines observed run through W + 1 and the games graded start at W + 2
            LW = W + (1 if LIVE else 0)
            obs = cur[(cur.wk >= 2) & (cur.wk <= LW)]; fut = cur[cur.wk > LW].copy()
            if obs.empty or fut.empty: continue
            w = 0.5 ** ((LW - obs.wk.values) / B.HL); d = (obs.imp - obs.p0).values - obs.wx.values
            em = expected_missing(a, cur, W)
            fut["emiss"] = [em.get((t, wk), 0.0) for t, wk in zip(fut.team, fut.wk)]
            # timelines known: the players out in week W, docked for exactly the later games they did miss in that
            # same absence (what a reported timeline would give us; no knowledge of injuries that have not happened)
            outW = a[a.wk == W]; kn = defaultdict(float)
            if len(outW):
                later = a[a.wk > W].merge(outW[["team", "name", "k"]].rename(columns={"k": "k0"}), on=["team", "name"])
                gwT = {t: sorted(g.wk.unique()) for t, g in cur.groupby("team")}
                for r in later.itertuples(index=False):
                    games_between = sum(1 for x in gwT.get(r.team, []) if W < x <= r.wk)
                    if r.k == r.k0 + games_between: kn[(r.team, r.wk)] += r.pg     # same unbroken absence
            fut["kmiss"] = [kn.get((t, wk), 0.0) for t, wk in zip(fut.team, fut.wk)]
            fut["none"] = fut.p0.values
            fut["base"] = fut.p0.values + LF.fit_hier(obs, d, w, LAM_Q)(fut)
            for k in KS[1:]:
                sh = LF.fit_hier(obs, d + k * obs.miss.values, w, LAM_Q)(fut)
                fut[f"or{k}"] = fut.p0.values + sh - k * fut.miss.values
                fut[f"re{k}"] = fut.p0.values + sh - k * fut.emiss.values
                fut[f"kn{k}"] = fut.p0.values + sh - k * fut.kmiss.values
            # a quarterback who is not the opening starter and has no lines of his own yet (the weak cell of the
            # quarterback context: he takes the team shift and nothing else) - flat dock on his offense
            seen = set((obs.team + "|" + obs.qb).values)
            fut["newqb"] = ((~fut.is_opener) & ~(fut.team + "|" + fut.qb).isin(seen)).astype(float)
            for g in GB[1:]: fut[f"gb{g}"] = fut["base"].values + g * fut.newqb.values
            # results: recency-weighted scoring surprise, offense and defense (games PLAYED = weeks <= W)
            obs_l = obs; w_l = w
            obs = obs[obs.wk <= W]; w = 0.5 ** ((W - obs.wk.values) / B.HL)
            so = (obs.assign(s=(obs.pts - obs.imp) * w, ww=w).groupby("team")[["s", "ww"]].sum()); so = (so.s / (so.ww + 1.0)).to_dict()
            sd = (obs.assign(s=(obs.pts - obs.imp) * w, ww=w).groupby("opp")[["s", "ww"]].sum()); sd = (sd.s / (sd.ww + 1.0)).to_dict()
            surp = fut.team.map(so).fillna(0).values + fut.opp.map(sd).fillna(0).values
            for g in GS[1:]: fut[f"res{g}"] = fut["base"].values + g * surp
            rw = 0.10 if W < 3 else (0.15 if W < 8 else 0.20)      # the leave-one-season-out pick at each checkpoint
            fut["final"] = fut["base"].values + rw * surp - 3.0 * fut.newqb.values
            fut["year"] = Y; fut["W"] = W; rec.append(fut)
    R = pd.concat(rec, ignore_index=True)
    mae = lambda x, c: np.abs(x[c] - x.imp).mean()
    def loyo(prefix, grid, x):
        """per-season pick of the grid value on the other seasons; returns pooled MAE, wins vs base, picks"""
        tot = n = wins = 0; picks = []
        for Y in YEARS:
            tr, te = x[x.year != Y], x[x.year == Y]
            if te.empty: continue
            best = min(grid, key=lambda g: mae(tr, "base" if g == 0 else f"{prefix}{g}"))
            c = "base" if best == 0 else f"{prefix}{best}"; picks.append(best)
            tot += np.abs(te[c] - te.imp).sum(); n += len(te); wins += mae(te, c) < mae(te, "base") - 1e-12
        return tot / n, wins, picks
    def block(title, x):
        b = mae(x, "base"); n0 = mae(x, "none"); ny = sum(1 for Y in YEARS if (x.year == Y).any())
        print(f"\n  {title}  (n={len(x)} team-games)")
        print(f"    preseason rating, never updated          miss vs the closing line {n0:.3f}")
        print(f"    OUR TOTALS (ratings + QB + weather)      {b:.3f}  ({100*(b/n0-1):+.1f}%)   points-scored MSE {100*(((x.base-x.pts)**2).mean()/((x.none-x.pts)**2).mean()-1):+.2f}%")
        for pre, lab in (("or", "+ skill injuries, ORACLE future (ceiling)"), ("kn", "+ skill injuries, TIMELINES KNOWN (out now)"), ("re", "+ skill injuries, REALISTIC (out now x curve)")):
            m, wn, pk = loyo(pre, KS, x)
            print(f"    {lab:44s} {m:.3f}  ({100*(m/b-1):+.2f}% vs our totals, {wn}/{ny} seasons)  k picks {pk}   pooled: " + " ".join(f"{k}:{100*(mae(x, f'{pre}{k}')/b-1):+.2f}%" for k in KS[1:]))
        m, wn, pk = loyo("gb", GB, x)
        print(f"    {'+ flat dock, new QB with no lines yet':44s} {m:.3f}  ({100*(m/b-1):+.2f}% vs our totals, {wn}/{ny} seasons)  picks {pk}   pooled: " + " ".join(f"{g}:{100*(mae(x, f'gb{g}')/b-1):+.2f}%" for g in GB[1:]))
        fm = mae(x, "final"); fw = sum(1 for Y in YEARS if (x.year == Y).any() and mae(x[x.year == Y], "final") < mae(x[x.year == Y], "base"))
        print(f"    {'SHIPPED FORM (results .10/.15/.20 + new QB -3)':44s} {fm:.3f}  ({100*(fm/b-1):+.2f}% vs our totals, {fw}/{ny} seasons; {100*(fm/n0-1):+.1f}% vs never updated)   points-scored MSE {100*(((x.final-x.pts)**2).mean()/((x.base-x.pts)**2).mean()-1):+.2f}% vs our totals")
        m, wn, pk = loyo("res", GS, x)
        print(f"    {'+ results (scoring surprise)':44s} {m:.3f}  ({100*(m/b-1):+.2f}% vs our totals, {wn}/{ny} seasons)  weight picks {pk}   pooled: " + " ".join(f"{g}:{100*(mae(x, f'res{g}')/b-1):+.2f}%" for g in GS[1:]))
    block("ALL future games, every checkpoint", R)
    for W in (2, 4, 8, 12): block(f"standing after week {W}", R[R.W == W])
    block("future games started by a quarterback who is not the opening starter and had no lines yet", R[R.newqb > 0])
    block("future games where the team has a skill starter out AT THE CHECKPOINT (expected missing > 0)", R[R.emiss > 0])
    block("future games where a skill starter actually missed that game", R[R.miss > 0])
    R["h"] = R.wk - R.W
    block("next 1-4 weeks only", R[R.h <= 4])
    return R

if __name__ == "__main__":
    sys.stdout = F.Tee(sys.__stdout__, open(os.path.join(HERE, "own_totals_backtest.log"), "w", encoding="utf-8"))
    run()
    LIVE = True
    run()
