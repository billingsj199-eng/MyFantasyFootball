#!/usr/bin/env python3
"""
2026-11-21 review, part 28a - NFL PLAYOFF BRACKET sims, postseasons 2013-2025 (13 brackets; tiny sample - read ranges).

Ratings at bracket time (all known before the wild-card round): ridge fit of every regular-season CLOSING spread
(team ratings + home field) toward the preseason market rating (win totals), i.e. the market's own end-of-season view.
Bracket: the real seeds (from the real playoff games), NFL re-seeding (top seed plays the lowest remaining), bye for seed 1
(seeds 1-2 before 2020), home field to the higher seed, neutral Super Bowl. 20,000 sims per postseason.
Strategies scored on the real results with 1-2-4-8 points (WC, DIV, CONF, SB):
  CHALK   higher seed wins every game
  MOSTL   each round's most likely winners given the sim (rating favourite every game, re-seeded)
  EXPPTS  for each round pick the teams with the highest P(reach the next round) (max expected points, bracket-consistent)
Also: P(advance) calibration of the sim on the real playoff games played, and expected games played per team
(the input for playoff fantasy / one-and-done pools).
"""
import os, time
import numpy as np
import pandas as pd
from scipy.stats import norm as N
import team_sims as TS

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = None   # opened by main(); importing this module never truncates nfl_bracket.log
LOG_NAME = "nfl_bracket.log"
CACHE = r"E:\MyFantasyFootball\pbp_cache"
RNG = np.random.default_rng(3)
NS = 20000


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def seeds_from_postseason(Y):
    s = pd.read_csv(os.path.join(CACHE, "schedules_games.csv"))
    s = s[(s.season == Y) & (s.game_type != "REG")].copy()
    s["home_team"] = s.home_team.map(TS.tm); s["away_team"] = s.away_team.map(TS.tm)
    return s


def main():
    global LOG
    LOG = open(os.path.join(HERE, LOG_NAME), "w", encoding="utf-8")
    t0 = time.time()
    G = TS.games(); WT = TS.win_totals()
    res = []; cal = []
    for Y in range(2013, 2026):
        reg = G[G.season == Y]
        sd = float((G[G.season < Y].margin - G[G.season < Y].spread_line).std())
        mr, hfa0 = TS.market_ratings(G, WT[WT.season == Y], Y, sd)
        rt, hfa = TS.fit_spread_ratings(reg, mr, lam=3.0)
        post = seeds_from_postseason(Y)
        if len(post) == 0: continue
        # seeds: rank playoff teams per conference by regular-season wins + tiebreak by rating (approximation of NFL seeding)
        w_act, made, divw = TS.actual_outcomes(G, Y)
        teams = sorted(set(post.home_team) | set(post.away_team))
        nseed = 7 if Y >= 2020 else 6
        seeds = {}
        for conf in ("AFC", "NFC"):
            ct = [t for t in teams if TS.TEAM_DIV[t].startswith(conf)]
            dw = sorted([t for t in ct if t in divw], key=lambda t: (-w_act[t], -rt[t]))
            wc = sorted([t for t in ct if t not in divw], key=lambda t: (-w_act[t], -rt[t]))
            seeds[conf] = (dw + wc)[:nseed]
        # actual round reached (rounds: 1 WC, 2 DIV, 3 CONF, 4 SB, 5 champion)
        wins = {t: 0 for t in teams}
        for x in post.itertuples(index=False):
            if np.isnan(x.home_score): continue
            wnr = x.home_team if x.home_score > x.away_score else x.away_team
            wins[wnr] += 1
        nbye = 1 if Y >= 2020 else 2
        def reached(t, conf):
            sd_ = seeds[conf].index(t) + 1
            return wins[t] + (2 if sd_ <= nbye else 1)          # round index reached (1 = played WC / 2 = in DIV ...)
        actual_round = {t: reached(t, c) for c in seeds for t in seeds[c]}
        # simulate
        def game(a, b, home, neutral=False):
            mu = rt[a] - rt[b] + (0 if neutral else (hfa if home == a else -hfa))
            pa = N.cdf(mu / sd)
            return pa
        reach = {t: np.zeros(6) for c in seeds for t in seeds[c]}
        champs = {}
        for _ in range(NS // 1000):
            pass
        # vectorised over sims per conference with re-seeding
        conf_w = {}
        for conf in ("AFC", "NFC"):
            sdl = seeds[conf]; n = len(sdl)
            alive = np.ones((NS, n), bool)
            for i in range(n): reach[sdl[i]][1 if i >= nbye else 2] += NS   # round reached at entry
            # round 1 (WC): byes skip
            rounds = []
            cur = [list(range(nbye, n))] * NS
            # do it with explicit loops by sims (n small) - acceptable: 20k x 3 rounds
            winners = np.zeros(NS, int)
            for s_ in range(NS):
                live = list(range(n)); byes = list(range(nbye))
                wc = [i for i in live if i >= nbye]
                adv = byes[:]
                while wc:
                    hi, lo = wc[0], wc[-1]; wc = wc[1:-1]
                    p = game(sdl[hi], sdl[lo], sdl[hi])
                    adv.append(hi if RNG.random() < p else lo)
                for t in adv:
                    if t >= nbye: reach[sdl[t]][2] += 1
                live = sorted(adv)
                rnd = 3
                while len(live) > 1:
                    nxt = []
                    l2 = live[:]
                    while l2:
                        hi, lo = l2[0], l2[-1]; l2 = l2[1:-1]
                        p = game(sdl[hi], sdl[lo], sdl[hi]); nxt.append(hi if RNG.random() < p else lo)
                    for t in nxt: reach[sdl[t]][rnd] += 1
                    live = sorted(nxt); rnd += 1
                winners[s_] = live[0]
            conf_w[conf] = winners
        a_w, n_w = conf_w["AFC"], conf_w["NFC"]
        for s_ in range(NS):
            ta, tn = seeds["AFC"][a_w[s_]], seeds["NFC"][n_w[s_]]
            p = game(ta, tn, None, neutral=True)
            ch = ta if RNG.random() < p else tn
            reach[ch][5] += 1
        for t in reach:
            for r in (1, 2, 3, 4, 5): reach[t][r] /= NS
            reach[t][1] = 1.0
            reach[t][2] = max(reach[t][2], 1.0 if seeds[TS.TEAM_DIV[t][:3]].index(t) < nbye else reach[t][2])
        # calibration on real advancement
        for t, rr in reach.items():
            for r in (3, 4, 5):
                if rr[r - 1] > 0:
                    cal.append({"season": Y, "team": t, "round": r, "p": rr[r], "y": float(actual_round[t] >= r)})
        # strategies -> predicted round reached per team, scored 1-2-4-8 (points for each correct winner of round r: reach r+1)
        pts_r = {2: 1, 3: 2, 4: 4, 5: 8}
        def score(pred_round):
            sc = 0
            for t, pr in pred_round.items():
                for r in (2, 3, 4, 5):
                    if pr >= r and actual_round[t] >= r and not (r == 2 and seeds[TS.TEAM_DIV[t][:3]].index(t) < nbye):
                        sc += pts_r[r]
            return sc
        def bracket(pick):
            out = {}
            fin = {}
            for conf in ("AFC", "NFC"):
                sdl = seeds[conf]; n = len(sdl)
                for i, t in enumerate(sdl): out[t] = 2 if i < nbye else 1
                wc = list(range(nbye, n)); adv = list(range(nbye))
                while wc:
                    hi, lo = wc[0], wc[-1]; wc = wc[1:-1]; w = pick(sdl[hi], sdl[lo], hi, lo); adv.append(w)
                for i in adv: out[sdl[i]] = 2
                live = sorted(adv); rnd = 3
                while len(live) > 1:
                    nxt = []; l2 = live[:]
                    while l2:
                        hi, lo = l2[0], l2[-1]; l2 = l2[1:-1]; nxt.append(pick(sdl[hi], sdl[lo], hi, lo))
                    for i in nxt: out[sdl[i]] = rnd
                    live = sorted(nxt); rnd += 1
                fin[conf] = sdl[live[0]]
            a, b = fin["AFC"], fin["NFC"]
            ch = a if pick(a, b, 0, 1, final=True) == 0 else b
            out[ch] = 5
            return out
        def chalk(a, b, hi, lo, final=False): return hi if not final else (0 if rt[a] >= rt[b] else 1)
        def mostl(a, b, hi, lo, final=False):
            if final: return 0 if rt[a] >= rt[b] else 1
            return hi if game(a, b, a) >= .5 else lo
        def exppts(a, b, hi, lo, final=False):
            ka = reach[a][5]; kb = reach[b][5]
            if final: return 0 if reach[a][5] >= reach[b][5] else 1
            return hi if ka >= kb else lo
        row = {"season": Y}
        for nm, f in (("CHALK", chalk), ("MOSTL", mostl), ("EXPPTS", exppts)):
            br = bracket(f); row[nm] = score(br)
            # expected score of the bracket under the sim
        mx = sum(pts_r[r] * (4 if r == 2 else (2 if r == 3 else (1 if r == 4 else 0.5))) for r in (2, 3, 4, 5)) * 2
        row["max"] = 2 * ((nseed - nbye) // 2 * 1 + 2 * 2 + 1 * 4) + 8
        row["games_exp_top"] = max(sum(reach[t][2:5]) + 1 for t in reach)
        res.append(row)
        P(f"  {Y}: CHALK {row['CHALK']} | MOSTL {row['MOSTL']} | EXPPTS {row['EXPPTS']} of {row['max']} | sim favourite title odds {max(reach[t][5] for t in reach)*100:.0f}%")
    R = pd.DataFrame(res)
    for nm in ("CHALK", "MOSTL", "EXPPTS"):
        P(f"  {nm:6s}: mean {R[nm].mean():.1f} pts ({(R[nm]/R['max']).mean()*100:.0f}% of max), range {R[nm].min()}-{R[nm].max()}")
    C = pd.DataFrame(cal)
    C["bin"] = pd.cut(C.p, [0, .2, .4, .6, .8, 1.0])
    t = C.groupby("bin", observed=True).agg(n=("y", "size"), pred=("p", "mean"), act=("y", "mean"))
    P("  advance-odds calibration (unconditional P(reach CONF / SB / title) at bracket time): " + " | ".join(f"{r.pred:.2f}->{r.act:.2f} (n{r.n})" for r in t.itertuples()))
    P(f"  Brier {np.mean((C.p - C.y)**2):.4f} (n {len(C)})")
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
