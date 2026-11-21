#!/usr/bin/env python3
"""
2026-11-21 review, part 27b - CONFIDENCE POOL sims, 2013-2025, from de-vigged closing moneylines.

1. Point assignment: rank by win probability (points 1..n per week). Expected / actual points vs max; cost of a
   calibration error (ranking + side picks made from probabilities stretched or shrunk toward .5, scored on the truth).
2. Pool sim with a MODELLED FIELD (no public pick-percentage history is on disk, so the field is an assumption):
   each rival reads p = closing p + N(0, .07) noise, picks the side his p favours, ranks by |p - .5|.
   My strategies: CHALK (rank by the closing p), UPSET1 / UPSET2 (take the underdog in the 1 / 2 closest games, lowest points),
   DOG_MID (one underdog in the closest game, given mid-table points), FADE_FAV (underdog of the most popular favourite under .70,
   lowest points). Outcomes drawn from the closing p, 300 replays per season; pool sizes 10 / 50 / 500;
   weekly prize = top score that week (ties split); season prize = top season total. Reports prize share vs a fair 1/N.
Writes confidence_pool.log.
"""
import os, time
import numpy as np
import pandas as pd
import team_sims as TS

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = None   # opened by main(); importing this module never truncates confidence_pool.log
LOG_NAME = "confidence_pool.log"
RNG = np.random.default_rng(5)
REPLAYS = 300


def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True)
    if LOG is not None: LOG.write(s + "\n"); LOG.flush()


def imp(o):
    o = np.asarray(o, float)
    with np.errstate(divide="ignore"):
        return np.where(o > 0, 100 / (o + 100), np.where(o < 0, -o / (-o + 100), 0.5))


def entry_points(side, rank, outcome):
    """side: (..., g) 1 = home; rank: (..., g) points; outcome (..., g) 1 = home won (.5 tie gets half)."""
    hit = np.where(side == 1, outcome, 1 - outcome)
    return (hit * rank).sum(-1)


def strategy(p, name):
    n = len(p); side = (p >= .5).astype(int); conf = np.abs(p - .5)
    order = conf.argsort(); rank = np.empty(n); rank[order] = np.arange(1, n + 1)
    if name == "CHALK": return side, rank
    s = side.copy(); r = rank.copy()
    if name in ("UPSET1", "UPSET2"):
        k = 1 if name == "UPSET1" else 2
        for g in order[:k]: s[g] = 1 - s[g]
        return s, r
    if name == "DOG_MID":
        g = order[0]; s[g] = 1 - s[g]
        mid = order[n // 2]; r[g], r[mid] = r[mid], r[g]       # swap its points with a mid-table game
        return s, r
    if name == "FADE_FAV":
        cand = [g for g in order if conf[g] < .20]
        g = cand[-1] if cand else order[0]                     # biggest favourite under .70
        s[g] = 1 - s[g]; low = order[0]; r[g], r[low] = r[low], r[g]
        return s, r
    raise ValueError(name)


def main():
    global LOG
    LOG = open(os.path.join(HERE, LOG_NAME), "w", encoding="utf-8")
    t0 = time.time()
    S = TS.games(); S = S[S.season >= 2013].copy()
    ph, pa = imp(S.home_moneyline.fillna(0)), imp(S.away_moneyline.fillna(0))
    S["p"] = ph / (ph + pa); S["y"] = (S.margin > 0).astype(float) + 0.5 * (S.margin == 0)
    weeks = [(Y, w, g) for (Y, w), g in S.groupby(["season", "week"]) if w < (17 if Y <= 2020 else 18)]
    P(f"=== 1. Point assignment, {len(weeks)} weeks 2013-25 (final week out), points 1..n ===")
    for lab, k in (("closing p (truth)", 1.0), ("over-confident x1.5", 1.5), ("under-confident x0.6", 0.6), ("noisy p +-.07", None)):
        exp_, act_, mx = 0.0, 0.0, 0.0
        for Y, w, g in weeks:
            p = g.p.values
            q = .5 + (p - .5) * k if k is not None else np.clip(p + RNG.normal(0, .07, len(p)), .01, .99)
            side, rank = strategy(np.clip(q, .01, .99), "CHALK")
            pt = np.where(side == 1, p, 1 - p)
            exp_ += (pt * rank).sum(); act_ += entry_points(side, rank, g.y.values); mx += rank.sum()
        P(f"  ranked by {lab:22s}: expected {exp_/mx*100:.2f}% of max, actual {act_/mx*100:.2f}%")
    P("  (a pure stretch / shrink keeps the ORDER, so it costs nothing in a confidence pool; only ordering noise costs points)")
    # upset counts in chalk
    dogs = np.mean([np.sum(np.abs(g.p - .5) < .05) for _, _, g in weeks])
    P(f"  games per week with the favourite under 55%: {dogs:.1f}; under 60%: {np.mean([np.sum(np.abs(g.p - .5) < .10) for _, _, g in weeks]):.1f}")

    P(f"\n=== 2. Pool sims with a modelled field ({REPLAYS} replays per season; prize share vs fair 1/N) ===")
    strats = ["CHALK", "UPSET1", "UPSET2", "DOG_MID", "FADE_FAV"]
    for NP in (10, 50, 500):
        wk_share = {s: [] for s in strats}; sea_share = {s: [] for s in strats}; pts = {s: [] for s in strats}
        for Y in range(2013, 2026):
            W = [(w, g) for (YY, w, g) in weeks if YY == Y]
            field_tot = np.zeros((REPLAYS, NP - 1)); my_tot = {s: np.zeros(REPLAYS) for s in strats}
            wk_wins = {s: np.zeros(REPLAYS) for s in strats}
            for w, g in W:
                p = g.p.values; n = len(p)
                out = (RNG.random((REPLAYS, n)) < p).astype(float)
                # field: noisy reads
                q = np.clip(p + RNG.normal(0, .07, (REPLAYS, NP - 1, n)), .01, .99)
                fs = (q >= .5).astype(int); fr = np.abs(q - .5).argsort(-1).argsort(-1) + 1
                fpts = (np.where(fs == 1, out[:, None, :], 1 - out[:, None, :]) * fr).sum(-1)
                field_tot += fpts; best_f = fpts.max(1)
                for s in strats:
                    side, rank = strategy(p, s)
                    mp = (np.where(side == 1, out, 1 - out) * rank).sum(-1)
                    my_tot[s] += mp; pts[s].append(mp.mean() / rank.sum())
                    nt = (fpts == mp[:, None]).sum(1)
                    wk_wins[s] += np.where(mp > best_f, 1.0, np.where(mp == best_f, 1.0 / (nt + 1), 0.0))
            for s in strats:
                wk_share[s].append(wk_wins[s].mean() / len(W))
                bf = field_tot.max(1); nt = (field_tot == my_tot[s][:, None]).sum(1)
                sea_share[s].append(np.mean(np.where(my_tot[s] > bf, 1.0, np.where(my_tot[s] == bf, 1 / (nt + 1), 0.0))))
        P(f"  pool size {NP} (fair share {1/NP*100:.2f}%):")
        for s in strats:
            ws = np.array(wk_share[s]); ss = np.array(sea_share[s])
            P(f"    {s:9s} points {np.mean(pts[s])*100:.2f}% of max | weekly prize share {ws.mean()*100:.2f}% (season range {ws.min()*100:.1f}-{ws.max()*100:.1f}) = {ws.mean()*NP:.2f}x fair | season prize {ss.mean()*100:.2f}% = {ss.mean()*NP:.2f}x fair")
    P(f"\ndone ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
