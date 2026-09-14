#!/usr/bin/env python3
"""
Backtest STREAM_TOL — the league sim's D/ST streaming threshold (engine.js:
stream to the best waiver DST when its projected mean beats the rostered
DST's by more than STREAM_TOL points; byes always stream).

Projection = the engine's own dstWeeklyMean on the CLOSING implied total
(16.2 - 0.436*oppImplied, floor 1.0), lines from nflfastR pbp
(backtest_vegas_layer.load_lines), actuals = pbp-reconstructed DST fantasy
weeks (backtest_k_dst_sigma.season_scores). Seasons 2019-2025.

A. EDGE CALIBRATION - for every (held team, week), the alternative is the
   k-th best-projected OTHER team that week (k=1 and k=3). Bucket the
   projected gap, report realized (actual_alt - actual_held). Slope ~1
   means a projected streaming point is worth a realized point.

B. POLICY SWEEP - league-realistic: each season the top 12 DSTs by
   PRIOR-season total points are "rostered" (managers draft perceived-best),
   the other ~20 sit on waivers. Each rostered DST is a manager's week-1
   unit; sweep TOL in {0, .25, .5, .75, 1, 1.5, 2, 3, never} over weeks
   1-14: swap to the best waiver DST when its proj beats the held proj by
   > TOL (bye = forced swap; dropped DST returns to the pool; 'never'
   scores 0 on the bye). Report realized season points + swaps per TOL.
"""
import os
import numpy as np
import pandas as pd

from backtest_k_dst_sigma import season_scores
from backtest_vegas_layer import load_lines, tm

CACHE = r"E:\MyFantasyFootball\pbp_cache"
SEASONS = range(2019, 2026)
REG_TO = 14  # fantasy regular season

def dst_mean(opp_implied):
    return max(1.0, 16.2 - 0.436 * opp_implied)

def load_schedule(year):
    """(team, wk) -> opponent, from pbp game rows (REG only)."""
    cols = ["season_type", "week", "game_id", "home_team", "away_team"]
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{year}.csv.gz"),
                     usecols=cols, low_memory=False)
    df = df[df.season_type == "REG"]
    g = df.groupby("game_id").first()
    sched = {}
    for _, r in g.iterrows():
        wk = int(r.week)
        sched[(tm(r.home_team), wk)] = tm(r.away_team)
        sched[(tm(r.away_team), wk)] = tm(r.home_team)
    return sched

def season_frame(year):
    """Return per-week dicts: proj[(team,wk)], act[(team,wk)] (aliased codes)."""
    lines, corr = load_lines(year)          # (team, wk) -> own implied
    sched = load_schedule(year)
    _, dsts = season_scores(year)           # raw pbp codes
    act = {}
    for team, wks in dsts.items():
        for wk, p in wks.items():
            act[(tm(team), wk)] = p
    proj = {}
    for (team, wk), opp in sched.items():
        oi = lines.get((opp, wk))
        if oi is not None:
            proj[(team, wk)] = dst_mean(oi)
    return proj, act, corr

def main():
    frames = {}
    prior_totals = {}
    years = [SEASONS.start - 1] + list(SEASONS)  # 2018 seeds the first draft order
    for y in years:
        print(f"loading {y}...")
        if y == SEASONS.start - 1:
            _, dsts = season_scores(y)
            prior_totals[y] = {tm(t): sum(w.values()) for t, w in dsts.items()}
        else:
            proj, act, corr = season_frame(y)
            frames[y] = (proj, act)
            tot = {}
            for (t, wk), p in act.items():
                tot[t] = tot.get(t, 0) + p
            prior_totals[y] = tot
            print(f"  implied-vs-score corr {corr:+.3f}, "
                  f"{len(set(t for t, _ in proj))} teams projected")

    # ---------- A. edge calibration ----------
    print("\n=== A. Projected streaming gap vs realized gain ===")
    for K in (1, 3):
        samples = []  # (gap, realized delta)
        for y in SEASONS:
            proj, act = frames[y]
            weeks = sorted(set(wk for _, wk in proj))
            for wk in weeks:
                board = sorted(((p, t) for (t, w), p in proj.items() if w == wk),
                               reverse=True)
                for p_held, held in board:
                    alts = [(p, t) for p, t in board if t != held]
                    if len(alts) < K:
                        continue
                    p_alt, alt = alts[K - 1]
                    gap = p_alt - p_held
                    if gap <= 0:
                        continue
                    a_h = act.get((held, wk))
                    a_a = act.get((alt, wk))
                    if a_h is None or a_a is None:
                        continue
                    samples.append((gap, a_a - a_h))
        g = np.array([s[0] for s in samples])
        d = np.array([s[1] for s in samples])
        slope = (g * d).sum() / (g * g).sum()
        print(f"\n  alt = #{K} best that week  (n={len(g)}, "
              f"through-origin slope {slope:.2f})")
        edges = [0, 0.5, 1.0, 1.5, 2.0, 3.0, 99]
        for lo, hi in zip(edges[:-1], edges[1:]):
            m = (g > lo) & (g <= hi)
            if m.sum() < 20:
                continue
            se = d[m].std() / np.sqrt(m.sum())
            print(f"    gap {lo:>3.1f}-{hi:>4.1f}: n={m.sum():5d}  "
                  f"proj gap {g[m].mean():4.2f}  realized {d[m].mean():+5.2f} "
                  f"(+/-{se:.2f})  ratio {d[m].mean()/g[m].mean():+.2f}")

    # ---------- B. policy sweep ----------
    print("\n=== B. Season policy sweep (12 rostered by prior-yr pts, waivers = rest) ===")
    TOLS = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, None]  # None = never stream
    agg = {t: [] for t in TOLS}   # per (season, startDst): (pts, swaps)
    for y in SEASONS:
        proj, act = frames[y]
        prior = prior_totals[y - 1] if (y - 1) in prior_totals else None
        teams = sorted(set(t for t, _ in proj))
        order = sorted(teams, key=lambda t: -(prior or {}).get(t, 0))
        rostered, waivers0 = order[:12], set(order[12:])
        for start in rostered:
            for tol in TOLS:
                held = start
                pool = set(waivers0)
                pts = 0.0
                swaps = 0
                for wk in range(1, REG_TO + 1):
                    p_held = proj.get((held, wk))          # None = bye
                    avail = sorted(((proj[(t, wk)], t) for t in pool
                                    if (t, wk) in proj), reverse=True)
                    if tol is None:
                        pts += act.get((held, wk), 0.0) if p_held is not None else 0.0
                        continue
                    if avail and (p_held is None or
                                  avail[0][0] - p_held > tol):
                        pool.add(held)
                        held = avail[0][1]
                        pool.discard(held)
                        swaps += 1
                    if proj.get((held, wk)) is not None:
                        pts += act.get((held, wk), 0.0)
                agg[tol].append((pts, swaps))
    print(f"\n  {'TOL':>5}  {'season pts':>10}  {'ppg':>5}  {'swaps':>5}  "
          f"{'vs never':>8}  {'marginal pts/extra swap':>22}")
    base = np.mean([p for p, _ in agg[None]])
    prev = None
    rows = []
    for tol in [None, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.25, 0.0]:
        pts = np.mean([p for p, _ in agg[tol]])
        sw = np.mean([s for _, s in agg[tol]])
        marg = ""
        if prev is not None:
            dp, ds = pts - prev[0], sw - prev[1]
            marg = f"{dp/ds:+.2f}" if ds > 0.01 else "-"
        rows.append((tol, pts, sw))
        label = "never" if tol is None else f"{tol:.2f}"
        print(f"  {label:>5}  {pts:10.1f}  {pts/REG_TO:5.2f}  {sw:5.1f}  "
              f"{pts-base:+8.1f}  {marg:>22}")
        prev = (pts, sw)

if __name__ == "__main__":
    main()
