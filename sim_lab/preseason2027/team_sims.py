#!/usr/bin/env python3
"""
2027 PRESEASON PROTOTYPE - step 3: NFL GAME + TEAM SEASON sims, backtested 2013-2025 (no engine change).

Part A - game layer vs the closing market (what the engine takes as given today):
  closing spread -> win prob (normal, sd fit walk-forward), Brier / log loss / calibration bins; margin and total error vs
  the closing spread / total; implied team total error; key numbers / OT / blowout + shootout frequency real vs a normal sim;
  game script: pass rate and plays vs expected margin and implied total (the elasticity the player layer needs).
Part B - preseason team season sim, three ratings (all known before week 1):
  MARKET  ratings solved so that the de-vigged win totals hold over the real schedule (covers.com / SportsOddsHistory lines)
  ELO     538-style Elo (K 20, ln(MOV+1) multiplier, 1/3 regression to 1505 each offseason, home 48 Elo), no market
  BLEND   2/3 market + 1/3 Elo (538's 2019+ preseason form)
  10,000 sims of the real schedule per season with 'hot' in-sim rating updates; outputs wins mean / p10 / p90,
  P(playoffs) (7 seeds per conference from 2020, 6 before; division winners first; ties broken by a random draw),
  P(division). Graded vs actual: wins MAE, coverage of p10-p90, Brier on P(over the win total), Brier / log loss on
  playoffs and division, and vs a no-information baseline.
Part C - in-season update (week 4 / 8 / 12): banked real results + rest simulated from (i) the preseason market rating
  (no update), (ii) Elo updated on results, (iii) market ratings re-fit from the closing spreads seen so far (the market's
  own current view) blended with the preseason prior. Grades ROS wins + playoffs.
"""
import os, time
import numpy as np
import pandas as pd
from scipy.stats import norm as N
from scipy.optimize import minimize_scalar

HERE = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(HERE, "data")
LOG = None   # opened in main() so importing this module never truncates the log
CACHE = r"E:\MyFantasyFootball\pbp_cache"
ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX"}
DIV = {"AFC East": ["BUF", "MIA", "NE", "NYJ"], "AFC North": ["BAL", "CIN", "CLE", "PIT"], "AFC South": ["HOU", "IND", "JAX", "TEN"],
       "AFC West": ["DEN", "KC", "LV", "LAC"], "NFC East": ["DAL", "NYG", "PHI", "WAS"], "NFC North": ["CHI", "DET", "GB", "MIN"],
       "NFC South": ["ATL", "CAR", "NO", "TB"], "NFC West": ["ARI", "LAR", "SF", "SEA"]}
TEAM_DIV = {t: d for d, ts in DIV.items() for t in ts}
SIMS = 10000
RNG = np.random.default_rng(7)


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def tm(t): return ALIAS.get(t, t)


def games():
    S = pd.read_csv(os.path.join(CACHE, "schedules_games.csv"))
    S = S[(S.game_type == "REG") & S.season.between(2012, 2025)].copy()
    S["home_team"] = S.home_team.map(tm); S["away_team"] = S.away_team.map(tm)
    S["neutral"] = (S.location == "Neutral").astype(int)
    S["margin"] = S.home_score - S.away_score
    return S.sort_values(["season", "week", "gameday"]).reset_index(drop=True)


def brier(p, y): return float(np.mean((p - y) ** 2))
def logloss(p, y): p = np.clip(p, 1e-4, 1 - 1e-4); return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


# ------------------------------------------------------------------ Part A
def part_a(S):
    P("=== Part A: game layer vs the closing market, REG 2013-2025 ===")
    A = S[S.season >= 2013].copy()
    y = (A.margin > 0).astype(float) + 0.5 * (A.margin == 0)
    res = A.margin - A.spread_line
    P(f"  games {len(A)} | margin - closing spread: mean {res.mean():+.2f}, sd {res.std():.2f}, MAE {res.abs().mean():.2f} | total - closing total: mean {(A.total - A.total_line).mean():+.2f}, sd {(A.total - A.total_line).std():.2f}, MAE {(A.total - A.total_line).abs().mean():.2f}")
    # walk-forward sd and win prob
    out = []
    for Y in range(2014, 2026):
        tr = A[A.season < Y]; te = A[A.season == Y]
        sd = (tr.margin - tr.spread_line).std()
        p = N.cdf(te.spread_line / sd)
        out.append(pd.DataFrame({"p": p, "y": ((te.margin > 0) + 0.5 * (te.margin == 0)).values, "season": Y}))
    O = pd.concat(out)
    base = np.full(len(O), O.y.mean())
    P(f"  closing-spread win prob (normal, walk-forward sd ~13.5): Brier {brier(O.p, O.y):.4f} | log loss {logloss(O.p, O.y):.4f} | coin-flip-at-home-rate Brier {brier(base, O.y):.4f}")
    O["bin"] = pd.cut(O.p, [0, .2, .3, .4, .5, .6, .7, .8, 1.0])
    cal = O.groupby("bin", observed=True).agg(n=("y", "size"), pred=("p", "mean"), act=("y", "mean"))
    P("  calibration (pred -> actual): " + " | ".join(f"{r.pred:.2f}->{r.act:.2f} (n{r.n})" for r in cal.itertuples()))
    # moneyline de-vig vs spread
    m = A.home_moneyline.notna() & A.away_moneyline.notna()
    def imp(o): return np.where(o > 0, 100 / (o + 100), -o / (-o + 100))
    ph, pa = imp(A.home_moneyline[m].values), imp(A.away_moneyline[m].values)
    pm = ph / (ph + pa); ym = y[m].values
    P(f"  de-vigged moneyline (multiplicative) Brier {brier(pm, ym):.4f}, log loss {logloss(pm, ym):.4f}, avg hold {np.mean(ph + pa - 1)*100:.1f}% (n {int(m.sum())})")
    # key numbers & tails: real vs normal(spread, sd)
    sd = res.std()
    absm = A.margin.abs()
    sim = RNG.normal(A.spread_line.values[:, None], sd, (len(A), 20)).round()
    P(f"  margin = 3: real {np.mean(absm == 3)*100:.1f}% vs normal sim {np.mean(np.abs(sim) == 3)*100:.1f}% | =7: real {np.mean(absm == 7)*100:.1f}% vs {np.mean(np.abs(sim) == 7)*100:.1f}% | ties/OT {A.overtime.mean()*100:.1f}% games to OT")
    P(f"  blowouts |margin| >= 21: real {np.mean(absm >= 21)*100:.1f}% vs sim {np.mean(np.abs(sim) >= 21)*100:.1f}% | upset of 7+ pt fav: real {np.mean((A.spread_line.abs() >= 7) & (np.sign(A.margin) == -np.sign(A.spread_line)))/np.mean(A.spread_line.abs() >= 7)*100:.1f}%")
    tsd = (A.total - A.total_line).std(); simt = RNG.normal(A.total_line.values[:, None], tsd, (len(A), 20))
    P(f"  totals: shootouts (total >= line + 14) real {np.mean(A.total >= A.total_line + 14)*100:.1f}% vs normal {np.mean(simt >= A.total_line.values[:, None] + 14)*100:.1f}% | duds (<= line - 14) real {np.mean(A.total <= A.total_line - 14)*100:.1f}% vs {np.mean(simt <= A.total_line.values[:, None] - 14)*100:.1f}%")
    skew = pd.Series((A.total - A.total_line).values).skew()
    P(f"  total residual skew {skew:+.2f} (normal 0); margin residual kurtosis {pd.Series(res.values).kurt():+.2f}")
    # implied team totals
    G = pd.read_parquet(os.path.join(DATA, "team_games.parquet")); G = G[G.season >= 2013]
    G["implied"] = G.total_line / 2 + G.exp_margin / 2
    e = G.pf - G.implied
    P(f"  implied team total vs points scored: bias {e.mean():+.2f}, MAE {e.abs().mean():.2f}, sd {e.std():.2f}, r {np.corrcoef(G.implied, G.pf)[0,1]:.3f}")
    for lo, hi in ((0, 18), (18, 21), (21, 24), (24, 27), (27, 40)):
        mm = (G.implied >= lo) & (G.implied < hi)
        P(f"    implied {lo}-{hi}: n {mm.sum()}, actual/implied {G.pf[mm].mean()/G.implied[mm].mean():.3f}, sd {G.pf[mm].std():.1f}")
    # game script elasticities (what flows to players)
    G["prate"] = G.dropbacks / G.plays.replace(0, np.nan)
    from numpy.linalg import lstsq
    X = np.column_stack([np.ones(len(G)), G.exp_margin, G.implied - G.implied.mean()]); ok = G.prate.notna() & G.plays.notna()
    b1, *_ = lstsq(X[ok], G.prate[ok], rcond=None); b2, *_ = lstsq(X[ok], G.plays[ok], rcond=None)
    P(f"  pregame script: dropback rate = {b1[0]:.3f} {b1[1]:+.4f} x exp_margin {b1[2]:+.4f} x (implied - avg) | plays = {b2[0]:.1f} {b2[1]:+.3f} x exp_margin {b2[2]:+.3f} x (implied - avg)")
    G["live_mar"] = G.pf - G.pa
    X2 = np.column_stack([np.ones(ok.sum()), G.exp_margin[ok], (G.live_mar - G.exp_margin)[ok]])
    b3, *_ = lstsq(X2, G.prate[ok], rcond=None)
    P(f"  realized script: dropback rate {b3[0]:.3f} {b3[1]:+.4f} x exp_margin {b3[2]:+.4f} x (final margin surprise) -> a 14-pt surprise moves pass rate {14*b3[2]*100:+.1f} pts")
    P(f"  team plays per game sd {G.plays.std():.1f}; dropback rate sd {G.prate.std():.3f}; corr(plays, opp plays) {G.merge(G[['game_id','team','plays']].rename(columns={'team':'opp','plays':'oplays'}), on=['game_id','opp']).pipe(lambda d: np.corrcoef(d.plays.fillna(d.plays.mean()), d.oplays.fillna(d.oplays.mean()))[0,1]):.3f}")


# ------------------------------------------------------------------ ratings
def elo_history(S):
    """538-style Elo. Returns {season: {team: preseason elo}} and per-game pre-game elos."""
    elo = {}; pre = {}; rows = []
    for Y in range(2012, 2026):
        for t in TEAM_DIV: elo[t] = 1505 + (elo.get(t, 1505) - 1505) * (2 / 3)
        pre[Y] = dict(elo)
        for r in S[S.season == Y].itertuples(index=False):
            h, a = r.home_team, r.away_team
            hfa = 0 if r.neutral else 48
            d = elo[h] + hfa - elo[a]
            p = 1 / (1 + 10 ** (-d / 400))
            rows.append((r.game_id, Y, r.week, elo[h], elo[a], p))
            if np.isnan(r.margin): continue
            s = 1.0 if r.margin > 0 else (0.5 if r.margin == 0 else 0.0)
            mult = np.log(abs(r.margin) + 1) * 2.2 / ((d if r.margin > 0 else -d) * 0.001 + 2.2)
            k = 20 * mult * (s - p)
            elo[h] += k; elo[a] -= k
    return pre, pd.DataFrame(rows, columns=["game_id", "season", "week", "eh", "ea", "p"])


def market_ratings(S, WT, Y, sd):
    """team ratings (points vs average) solving E[wins] over the real schedule = de-vigged win totals."""
    g = S[S.season == Y]; teams = sorted(TEAM_DIV)
    tgt = WT.set_index("team").exp_w.to_dict()
    r = {t: 0.0 for t in teams}
    hfa = 2.0 if Y >= 2018 else 2.5
    for _ in range(60):
        ew = {t: 0.0 for t in teams}
        for x in g.itertuples(index=False):
            p = N.cdf((r[x.home_team] - r[x.away_team] + (0 if x.neutral else hfa)) / sd)
            ew[x.home_team] += p; ew[x.away_team] += 1 - p
        for t in teams: r[t] += 0.9 * (tgt.get(t, ew[t]) - ew[t]) / (len(g) * 2 / 32) * sd * 2.5
        m = np.mean(list(r.values())); r = {t: v - m for t, v in r.items()}
    return r, hfa


def win_totals():
    w = pd.read_csv(os.path.join(DATA, "win_totals_2012_2025.csv")); w["team"] = w.team.map(tm)
    def dec(o):
        o = float(str(o).replace("+", "")); return 1 + (o / 100 if o > 0 else 100 / -o)
    po = 1 / w.over_odds.map(dec); pu = 1 / w.under_odds.map(dec)
    w["p_over"] = po / (po + pu); w["hold"] = po + pu - 1
    w["exp_w"] = w.win_total + 2.0 * N.ppf(w.p_over.clip(.02, .98))
    games = w.season.map(lambda y: 16 if y <= 2020 else 17)
    w["exp_w"] = w.exp_w + (games * 16 - w.groupby("season").exp_w.transform("sum")) / 32
    return w


# ------------------------------------------------------------------ season sim
def sim_season(g, rating, hfa, sd, banked=None, hot_k=0.0, n=SIMS):
    """g = schedule rows; rating {team: pts}; banked = {game_id: home_win (1/0/.5)}; hot_k = in-sim rating update per point of surprise."""
    teams = sorted(TEAM_DIV); ix = {t: i for i, t in enumerate(teams)}
    W = np.zeros((n, 32)); R = np.tile(np.array([rating[t] for t in teams]), (n, 1))
    PF = np.zeros((n, 32))
    for x in g.itertuples(index=False):
        h, a = ix[x.home_team], ix[x.away_team]
        if banked is not None and x.game_id in banked:
            res = banked[x.game_id]
            W[:, h] += res; W[:, a] += 1 - res; PF[:, h] += x.margin; PF[:, a] -= x.margin
            continue
        mu = R[:, h] - R[:, a] + (0 if x.neutral else hfa)
        m = mu + RNG.normal(0, sd, n)
        hw = (m > 0).astype(float)
        W[:, h] += hw; W[:, a] += 1 - hw; PF[:, h] += m; PF[:, a] -= m
        if hot_k:
            sur = (m - mu) * hot_k; R[:, h] += sur; R[:, a] -= sur
    # playoffs: division winners + wild cards per conference (6 seeds before 2020, 7 from 2020); tiebreak = point diff + noise
    Y = int(g.season.iloc[0]); nseeds = 7 if Y >= 2020 else 6
    key = W + PF * 1e-4 + RNG.random((n, 32)) * 1e-6
    po = np.zeros((n, 32)); dv = np.zeros((n, 32))
    for conf in ("AFC", "NFC"):
        cidx = [ix[t] for t in teams if TEAM_DIV[t].startswith(conf)]
        winners = []
        for d in [d for d in DIV if d.startswith(conf)]:
            di = [ix[t] for t in DIV[d]]
            w = np.array(di)[np.argmax(key[:, di], axis=1)]
            dv[np.arange(n), w] = 1; winners.append(w)
        winners = np.stack(winners, 1)
        k2 = key[:, cidx].copy()
        for j in range(4):
            col = np.searchsorted(cidx, winners[:, j]); k2[np.arange(n), col] = -1e9
        nwc = nseeds - 4
        wc = np.argsort(-k2, axis=1)[:, :nwc]
        po[np.arange(n)[:, None], np.array(cidx)[wc]] = 1
        po[dv == 1] = 1
    return teams, W, po, dv


def actual_outcomes(S, Y):
    g = S[S.season == Y]; teams = sorted(TEAM_DIV)
    w = {t: 0.0 for t in teams}; pdiff = {t: 0.0 for t in teams}
    for x in g.itertuples(index=False):
        if np.isnan(x.margin): continue
        s = 1.0 if x.margin > 0 else (0.5 if x.margin == 0 else 0.0)
        w[x.home_team] += s; w[x.away_team] += 1 - s; pdiff[x.home_team] += x.margin; pdiff[x.away_team] -= x.margin
    post = pd.read_csv(os.path.join(CACHE, "schedules_games.csv"))
    post = post[(post.season == Y) & (post.game_type != "REG")]
    made = set(post.home_team.map(tm)) | set(post.away_team.map(tm))
    divw = {}
    for d, ts in DIV.items():
        best = max(ts, key=lambda t: (w[t], pdiff[t]))
        divw[d] = best
    return w, made, set(divw.values())


def part_b(S, WT):
    P("\n=== Part B: preseason NFL team season sims 2013-2025 (10k sims, real schedule, hot ratings) ===")
    pre_elo, EG = elo_history(S)
    rows = []
    for Y in range(2013, 2026):
        g = S[S.season == Y]
        sd = float((S[S.season < Y].margin - S[S.season < Y].spread_line).std())
        wt = WT[WT.season == Y]
        mr, hfa = market_ratings(S, wt, Y, sd)
        er = {t: (pre_elo[Y][t] - 1505) / 25.0 for t in TEAM_DIV}   # 25 Elo per point
        br = {t: 2 / 3 * mr[t] + 1 / 3 * er[t] for t in TEAM_DIV}
        w_act, made, divw = actual_outcomes(S, Y)
        line = wt.set_index("team")
        for lab, rt, hk in (("MARKET", mr, 0.0), ("MARKET_hot", mr, 0.08), ("ELO", er, 0.08), ("BLEND", br, 0.08)):
            teams, W, po, dv = sim_season(g, rt, hfa, sd, hot_k=hk)
            for i, t in enumerate(teams):
                wl = line.win_total.get(t, np.nan)
                rows.append({"season": Y, "team": t, "model": lab, "ew": W[:, i].mean(), "p10": np.quantile(W[:, i], .1), "p90": np.quantile(W[:, i], .9),
                             "p_over": float(np.mean(W[:, i] > wl)), "p_push": float(np.mean(W[:, i] == wl)), "p_po": po[:, i].mean(), "p_div": dv[:, i].mean(),
                             "act_w": w_act[t], "line": wl, "mkt_p_over": line.p_over.get(t, np.nan), "made": float(t in made), "divwin": float(t in divw),
                             "rating": rt[t]})
        P(f"  {Y}: sd {sd:.2f}, hfa {hfa}, market rating range {min(mr.values()):+.1f}..{max(mr.values()):+.1f}")
    R = pd.DataFrame(rows)
    R.to_parquet(os.path.join(DATA, "team_sim_rows.parquet"), index=False)
    P("\n  model        winsMAE  RMSE  p10-p90cov  Brier(over)  Brier(playoffs) LL(playoffs) Brier(div)  sum P(po)/season")
    for lab in ("MARKET", "MARKET_hot", "ELO", "BLEND"):
        m = R[R.model == lab]
        ov = m[m.act_w != m.line]; yo = (ov.act_w > ov.line).astype(float)
        p_over_cond = ov.p_over / (1 - ov.p_push).clip(1e-6)
        P(f"  {lab:12s} {np.mean(np.abs(m.ew - m.act_w)):6.3f} {np.sqrt(np.mean((m.ew - m.act_w)**2)):6.3f} {np.mean((m.act_w >= m.p10) & (m.act_w <= m.p90))*100:8.1f}%"
          f"   {brier(p_over_cond, yo):.4f}      {brier(m.p_po, m.made):.4f}        {logloss(m.p_po, m.made):.4f}      {brier(m.p_div, m.divwin):.4f}     {m.groupby('season').p_po.sum().mean():.2f}")
    mk = R[R.model == "MARKET"]; ov = mk[mk.act_w != mk.line]
    P(f"  market's own de-vigged P(over) Brier {brier(ov.mkt_p_over, (ov.act_w > ov.line).astype(float)):.4f}; coin flip .2500; actual over rate {np.mean(ov.act_w > ov.line):.3f}")
    base_po = mk.groupby("season").made.transform("mean")
    P(f"  no-information playoff Brier (league base rate) {brier(base_po, mk.made):.4f}; division {brier(np.full(len(mk), .25), mk.divwin):.4f}")
    # calibration of playoff odds
    mk = R[R.model == "MARKET_hot"].copy(); mk["bin"] = pd.cut(mk.p_po, [0, .1, .25, .4, .6, .75, .9, 1.0])
    cal = mk.groupby("bin", observed=True).agg(n=("made", "size"), pred=("p_po", "mean"), act=("made", "mean"))
    P("  MARKET_hot playoff calibration: " + " | ".join(f"{r.pred:.2f}->{r.act:.2f} (n{r.n})" for r in cal.itertuples()))
    return R


def fit_spread_ratings(g_seen, prior, lam=3.0):
    """ratings from closing spreads seen so far (ridge toward the prior): spread = r_h - r_a + hfa."""
    teams = sorted(TEAM_DIV); ix = {t: i for i, t in enumerate(teams)}
    X = np.zeros((len(g_seen), 33)); y = g_seen.spread_line.values.astype(float)
    for k, x in enumerate(g_seen.itertuples(index=False)):
        X[k, ix[x.home_team]] = 1; X[k, ix[x.away_team]] = -1; X[k, 32] = 0 if x.neutral else 1
    pr = np.array([prior[t] for t in teams] + [0.0])
    A = X.T @ X + lam * np.diag([1] * 32 + [0.01]); b = X.T @ (y - X @ pr)
    beta = np.linalg.solve(A, b) + pr
    return {t: beta[ix[t]] for t in teams}, beta[32]


def part_c(S, WT):
    P("\n=== Part C: in-season update from week 4 / 8 / 12 (banked results + simulated rest), 2013-2025 ===")
    pre_elo, _ = elo_history(S)
    out = []
    for Y in range(2013, 2026):
        g = S[S.season == Y]; sd = float((S[S.season < Y].margin - S[S.season < Y].spread_line).std())
        mr, hfa = market_ratings(S, WT[WT.season == Y], Y, sd)
        w_act, made, divw = actual_outcomes(S, Y)
        for wk in (4, 8, 12):
            seen = g[g.week <= wk]; banked = {x.game_id: (1.0 if x.margin > 0 else (0.5 if x.margin == 0 else 0.0)) for x in seen.itertuples(index=False)}
            # Elo updated through week wk (replay)
            elo = {t: 1505 + (pre_elo[Y][t] - 1505) for t in TEAM_DIV}
            for x in seen.itertuples(index=False):
                d = elo[x.home_team] + (0 if x.neutral else 48) - elo[x.away_team]; p = 1 / (1 + 10 ** (-d / 400))
                s = 1.0 if x.margin > 0 else (0.5 if x.margin == 0 else 0.0)
                k = 20 * np.log(abs(x.margin) + 1) * 2.2 / ((d if x.margin > 0 else -d) * 0.001 + 2.2) * (s - p)
                elo[x.home_team] += k; elo[x.away_team] -= k
            er = {t: (elo[t] - 1505) / 25 for t in TEAM_DIV}
            # market's current view: closing spreads of games through week wk+1 (the next week's lines are posted before it)
            seen_lines = g[g.week <= wk + 1]
            sr, h2 = fit_spread_ratings(seen_lines, mr, lam=3.0)
            # pure results ratings (points margin, shrunk to prior)
            rem_w = {t: w_act_t for t, w_act_t in w_act.items()}
            for lab, rt, hk in (("PRESEASON_MKT", mr, 0.08), ("ELO_upd", er, 0.08), ("SPREADS_upd", sr, 0.08)):
                teams, W, po, dv = sim_season(g, rt, hfa, sd, banked=banked, hot_k=hk, n=5000)
                bw = {t: 0.0 for t in teams}
                for x in seen.itertuples(index=False):
                    s = banked[x.game_id]; bw[x.home_team] += s; bw[x.away_team] += 1 - s
                for i, t in enumerate(teams):
                    out.append({"season": Y, "wk": wk, "model": lab, "team": t, "ros_pred": W[:, i].mean() - bw[t], "ros_act": w_act[t] - bw[t],
                                "p_po": po[:, i].mean(), "made": float(t in made), "p_div": dv[:, i].mean(), "divwin": float(t in divw)})
    O = pd.DataFrame(out); O.to_parquet(os.path.join(DATA, "team_sim_inseason_rows.parquet"), index=False)
    P("  week  model           ROS-wins MAE   Brier(playoffs)  LL(playoffs)  Brier(div)")
    for wk in (4, 8, 12):
        for lab in ("PRESEASON_MKT", "ELO_upd", "SPREADS_upd"):
            m = O[(O.wk == wk) & (O.model == lab)]
            P(f"  {wk:4d}  {lab:14s}   {np.mean(np.abs(m.ros_pred - m.ros_act)):6.3f}        {brier(m.p_po, m.made):.4f}          {logloss(m.p_po, m.made):.4f}      {brier(m.p_div, m.divwin):.4f}")
    # per-season wins for SPREADS vs ELO at week 8
    a = O[(O.wk == 8) & (O.model == "SPREADS_upd")].groupby("season").apply(lambda d: brier(d.p_po, d.made))
    b = O[(O.wk == 8) & (O.model == "ELO_upd")].groupby("season").apply(lambda d: brier(d.p_po, d.made))
    P(f"  week 8 playoff Brier, market-spread ratings better than Elo in {int((a < b).sum())}/{len(a)} seasons")
    return O


def main():
    global LOG
    LOG = open(os.path.join(HERE, "team_sims.log"), "w", encoding="utf-8")
    t0 = time.time()
    S = games(); WT = win_totals()
    P(f"  win-total hold: mean {WT.hold.mean()*100:.1f}%; de-vigged P(over) mean {WT.p_over.mean():.3f}")
    part_a(S)
    part_b(S, WT)
    part_c(S, WT)
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
