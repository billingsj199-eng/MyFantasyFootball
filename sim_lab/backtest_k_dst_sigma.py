#!/usr/bin/env python3
"""
Backtest the K and DST weekly sigmas — the two position defaults
(POS_SIGMA K 0.45, DST 0.75) that have never been checked, because our
fantasy weekly data has neither. Both are RECONSTRUCTED from cached nflverse
play-by-play (2019-2025):

  K   - FG made by distance (0-39 +3, 40-49 +4, 50+ +5), FG miss/block -1,
        XP +1 / miss -1, grouped per kicker per week.
  DST - sack +1, INT +2, fumble recovery +2, def/return TD +6, safety +2,
        blocked kick +2, points-allowed buckets (Sleeper default:
        0:+10, 1-6:+7, 7-13:+4, 14-20:+1, 21-27:0, 28-34:-1, 35+:-4),
        per team per week.

Then the same width test as backtest_weekly_sigma part B: mean = realized
season mean, sd = mean x engine TOTAL width x scale, gamma draws -> p10-p90
coverage vs actual weeks, sweeping the scale. Engine total widths:
  K   sqrt((0.9*0.45)^2 + 0.10^2) = 0.417
  DST sqrt((0.9*0.75)^2 + 0.25^2) = 0.720
DST extra: real DST weeks go NEGATIVE (a gamma never can), so a SHIFTED
gamma (draw around mean+4, subtract 4) is tested as an alternative family.
"""
import numpy as np
import pandas as pd
import os

CACHE = r"E:\MyFantasyFootball\pbp_cache"
SEASONS = range(2019, 2026)
# FINAL engine widths (post SIGMA_CAL.K 1.28 x the 1.10 no-history mult, and
# DST_SIGMA_CAL 1.34) — scale 1.0 = the engine as deployed
K_TOTAL = np.sqrt((0.9 * 0.45 * 1.10 * 1.28) ** 2 + 0.10 ** 2)
DST_TOTAL = np.sqrt((0.9 * 0.75 * 1.34) ** 2 + 0.25 ** 2)
SCALES = [0.9, 1.0, 1.1]
NDRAW = 4000

def pa_pts(pa):
    if pa == 0: return 10
    if pa <= 6: return 7
    if pa <= 13: return 4
    if pa <= 20: return 1
    if pa <= 27: return 0
    if pa <= 34: return -1
    return -4

def season_scores(year):
    cols = ["season_type", "week", "posteam", "defteam", "game_id",
            "home_team", "away_team", "home_score", "away_score",
            "sack", "interception", "fumble_lost", "touchdown", "td_team",
            "safety", "field_goal_result", "kick_distance",
            "extra_point_result", "kicker_player_name", "punt_blocked"]
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{year}.csv.gz"),
                     usecols=cols, low_memory=False)
    df = df[df.season_type == "REG"]

    # ---- kickers ----
    k_pts = {}
    fg = df[df.field_goal_result.notna()]
    for _, r in fg.iterrows():
        key = (r.kicker_player_name, int(r.week))
        if r.field_goal_result == "made":
            d = r.kick_distance or 0
            p = 3 if d < 40 else (4 if d < 50 else 5)
        else:
            p = -1
        k_pts[key] = k_pts.get(key, 0) + p
    xp = df[df.extra_point_result.notna()]
    for _, r in xp.iterrows():
        key = (r.kicker_player_name, int(r.week))
        k_pts[key] = k_pts.get(key, 0) + (1 if r.extra_point_result == "good" else -1)
    kickers = {}
    for (name, wk), p in k_pts.items():
        if name and isinstance(name, str):
            kickers.setdefault(name, {})[wk] = p

    # ---- DST ----
    d_pts = {}
    def add(team, wk, p):
        if isinstance(team, str) and team:
            d_pts[(team, wk)] = d_pts.get((team, wk), 0) + p
    for _, r in df[(df.sack == 1)].iterrows(): add(r.defteam, int(r.week), 1)
    for _, r in df[(df.interception == 1)].iterrows(): add(r.defteam, int(r.week), 2)
    for _, r in df[(df.fumble_lost == 1)].iterrows(): add(r.defteam, int(r.week), 2)
    for _, r in df[(df.touchdown == 1) & df.td_team.notna()].iterrows():
        if r.td_team == r.defteam: add(r.defteam, int(r.week), 6)
    for _, r in df[(df.safety == 1)].iterrows(): add(r.defteam, int(r.week), 2)
    for _, r in df[(df.field_goal_result == "blocked")].iterrows(): add(r.defteam, int(r.week), 2)
    for _, r in df[(df.punt_blocked == 1)].iterrows(): add(r.defteam, int(r.week), 2)
    # points allowed per team-game (opponent final score) — also ensures every
    # played week exists even with zero defensive events
    games = df.dropna(subset=["home_team"]).groupby("game_id").first()
    for _, g in games.iterrows():
        wk = int(g.week)
        add(g.home_team, wk, pa_pts(int(g.away_score)))
        add(g.away_team, wk, pa_pts(int(g.home_score)))
    dsts = {}
    for (team, wk), p in d_pts.items():
        dsts.setdefault(team, {})[wk] = p
    return kickers, dsts

def width_test(rows, total, label, shift=0.0):
    rng = np.random.default_rng(5)
    print(f"  {label} (shift {shift:g}):")
    for s in SCALES:
        inside = below = above = n = 0
        for mu, pts in rows:
            sd = max(0.5, mu) * total * s
            m2 = mu + shift
            if m2 <= 0.3:
                continue
            k = (m2 / sd) ** 2
            d = np.sort(rng.gamma(k, sd * sd / m2, NDRAW)) - shift
            lo, hi = d[int(NDRAW * .1)], d[int(NDRAW * .9)]
            for a in pts:
                n += 1
                if lo <= a <= hi: inside += 1
                elif a < lo: below += 1
                else: above += 1
        print(f"    x{s:.1f}: p10-p90 {inside/n*100:5.1f}% (target 80)  "
              f"below {below/n*100:4.1f}%  above {above/n*100:4.1f}%")

def main():
    k_rows, d_rows = [], []
    k_cvs, d_cvs = [], []
    d_all = []
    for y in SEASONS:
        kickers, dsts = season_scores(y)
        for name, wks in kickers.items():
            pts = list(wks.values())
            if len(pts) < 8:
                continue
            mu = float(np.mean(pts))
            if mu < 3:
                continue
            k_rows.append((mu, pts))
            k_cvs.append(float(np.std(pts, ddof=1) / mu))
        for team, wks in dsts.items():
            pts = list(wks.values())
            if len(pts) < 10:
                continue
            mu = float(np.mean(pts))
            d_rows.append((mu, pts))
            d_all.extend(pts)
            if mu > 1:
                d_cvs.append(float(np.std(pts, ddof=1) / mu))
        print(f"{y}: {len(kickers)} kickers, {len(dsts)} DSTs")

    print(f"\n=== K ({len(k_rows)} kicker-seasons) ===")
    print(f"  realized weekly CV: mean {np.mean(k_cvs):.3f}  (engine total width {K_TOTAL:.3f})")
    width_test(k_rows, K_TOTAL, "gamma, engine width x scale")

    print(f"\n=== DST ({len(d_rows)} team-seasons) ===")
    arr = np.array(d_all)
    print(f"  realized weekly: mean {arr.mean():.2f}  sd {arr.std():.2f}  "
          f"negative weeks {np.mean(arr < 0)*100:.1f}%  (engine total width {DST_TOTAL:.3f})")
    print(f"  realized weekly CV (per team-season): mean {np.mean(d_cvs):.3f}")
    width_test(d_rows, DST_TOTAL, "plain gamma (floor 0)")
    width_test(d_rows, DST_TOTAL, "SHIFTED gamma", shift=4.0)

if __name__ == "__main__":
    main()
