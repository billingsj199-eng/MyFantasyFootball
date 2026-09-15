#!/usr/bin/env python3
"""
DST TD REGRESSION backtest, 2019-2025 (Jack 2026-09-15: "backtest the DST TD
regression next"). Last member of the luck family.

The live DST mean is SYNTHESIZED from the opponent's implied total
(dstWeeklyMean: 16.2 - 0.436 x oppImplied + tuner dstShift) - it has no
realized half, so "TD regression" can only matter if a realized component
carries information the Vegas model lacks. This test decomposes reconstructed
DST weekly points (backtest_k_dst_sigma rules: sack +1, INT +2, FR +2, def/
return TD +6, safety +2, block +2, points-allowed buckets) into components and
asks, per component and season-to-date:

  GATE   does the component's per-game rate persist (early->late, YoY)?
  RESID  actual / shipped by season-to-date tercile of the component rate
  LOYO   shipped + k x (rate_std - league rate) x trust    per component
         realized-PPG blend (P x shipped + g x ppg)/(P+g) at several P, with
         and WITHOUT the TD points (TDs replaced by the league TD pts/g)

Log: dst_regression_backtest.log
"""
import numpy as np
import pandas as pd
import os
from collections import defaultdict
from backtest_target_area import implied_map, mse, loyo, LOAD_YEARS, YEARS, P, CACHE
# (stdout re-wrapped by backtest_target_area on import)

ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS"}
def tm(t): return ALIAS.get(t, t)

def pa_pts(pa):
    if pa == 0: return 10
    if pa <= 6: return 7
    if pa <= 13: return 4
    if pa <= 20: return 1
    if pa <= 27: return 0
    if pa <= 34: return -1
    return -4

COMPS = ["pa", "sack", "to", "td", "misc"]

def load_year(Y):
    cols = ["season_type", "week", "posteam", "defteam", "game_id", "home_team", "away_team", "home_score", "away_score",
            "spread_line", "total_line", "sack", "interception", "fumble_lost", "touchdown", "td_team", "safety",
            "field_goal_result", "punt_blocked"]
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), usecols=cols, low_memory=False)
    df = df[df.season_type == "REG"]
    lines = df.dropna(subset=["spread_line", "total_line", "posteam"]).groupby("game_id").first()
    rows = defaultdict(lambda: {c: 0.0 for c in COMPS})
    def add(team, wk, comp, p):
        if isinstance(team, str) and team: rows[(tm(team), int(wk))][comp] += p
    d = df[df.defteam.notna()]
    for r in d[d.sack == 1][["defteam", "week"]].itertuples(index=False): add(r.defteam, r.week, "sack", 1)
    for r in d[d.interception == 1][["defteam", "week"]].itertuples(index=False): add(r.defteam, r.week, "to", 2)
    for r in d[d.fumble_lost == 1][["defteam", "week"]].itertuples(index=False): add(r.defteam, r.week, "to", 2)
    for r in d[(d.touchdown == 1) & d.td_team.notna()][["defteam", "td_team", "week"]].itertuples(index=False):
        if r.td_team == r.defteam: add(r.defteam, r.week, "td", 6)
    for r in d[d.safety == 1][["defteam", "week"]].itertuples(index=False): add(r.defteam, r.week, "misc", 2)
    for r in d[d.field_goal_result == "blocked"][["defteam", "week"]].itertuples(index=False): add(r.defteam, r.week, "misc", 2)
    for r in d[d.punt_blocked == 1][["defteam", "week"]].itertuples(index=False): add(r.defteam, r.week, "misc", 2)
    games = df.dropna(subset=["home_team"]).groupby("game_id").first()
    opp = {}
    for _, g in games.iterrows():
        wk = int(g.week); h, a = tm(g.home_team), tm(g.away_team)
        add(h, wk, "pa", pa_pts(int(g.away_score))); add(a, wk, "pa", pa_pts(int(g.home_score)))
        opp[(h, wk)] = a; opp[(a, wk)] = h
    out = []
    for (team, wk), c in rows.items():
        if (team, wk) not in opp: continue
        out.append(dict(c, season=Y, team=team, week=wk, opp=opp[(team, wk)], pts=sum(c.values())))
    return pd.DataFrame(out), lines

def main():
    frames, lines_all = {}, {}
    for Y in LOAD_YEARS:
        frames[Y], lines_all[Y] = load_year(Y)
        print(f"  pbp {Y}: {len(frames[Y])} DST team-weeks")
    allw = pd.concat(frames.values(), ignore_index=True)
    lg = {Y: {c: allw[allw.season == Y][c].mean() for c in COMPS + ["pts"]} for Y in LOAD_YEARS}
    print("  league DST pts/g by component 2025: " + "  ".join(f"{c} {lg[2025][c]:.2f}" for c in COMPS + ["pts"]))

    # ---- GATE: persistence
    print("\n=== GATE. component persistence per team-season (per-game rates) ===")
    for c in COMPS + ["pts"]:
        e, l, y0, y1 = [], [], [], []
        for (Y, t), g in allw.groupby(["season", "team"]):
            early = g[g.week <= 8][c]; late = g[g.week >= 9][c]
            if len(early) >= 6 and len(late) >= 6: e.append(early.mean()); l.append(late.mean())
            nxt = allw[(allw.season == Y + 1) & (allw.team == t)]
            if len(nxt) >= 12 and len(g) >= 12: y0.append(g[c].mean()); y1.append(nxt[c].mean())
        print(f"  {c:5s} early->late r={np.corrcoef(e,l)[0,1]:+.2f} (n={len(e)})   YoY r={np.corrcoef(y0,y1)[0,1]:+.2f} (n={len(y0)})")

    # ---- samples: shipped = 16.2 - 0.436 * oppImplied
    S = defaultdict(list)
    for Y in YEARS:
        imp = implied_map(lines_all[Y])
        w = frames[Y].sort_values("week")
        for t, g in w.groupby("team"):
            hist = []
            for r in g.itertuples(index=False):
                oi = imp.get((r.opp, int(r.week)))
                if oi is None: hist.append(r); continue
                if hist:
                    n = len(hist)
                    S["year"].append(Y); S["act"].append(r.pts); S["g"].append(n)
                    S["ship"].append(max(1.0, 16.2 - 0.436 * oi))
                    S["ppg"].append(np.mean([h.pts for h in hist]))
                    for c in COMPS: S[c].append(np.mean([getattr(h, c) for h in hist]) - lg[Y][c])
                    S["ppg_notd"].append(np.mean([h.pts - h.td for h in hist]) + lg[Y]["td"])
                hist.append(r)
    S = {k: np.array(v, float) for k, v in S.items()}; S["year"] = S["year"].astype(int); years = sorted(set(S["year"]))
    act, ship, g = S["act"], S["ship"], S["g"]; wreal = g / (P + g)
    print(f"\n{len(act)} DST team-weeks | shipped (Vegas-only) MSE {mse(ship, act):.4f} | mean act/shipped {act.mean()/ship.mean():.3f}")

    print("\n=== 1. actual / shipped by season-to-date tercile of each component's rate (vs league) ===")
    for c in COMPS + ["ppg"]:
        x = S[c] if c != "ppg" else S["ppg"]
        q = np.quantile(x, [1/3, 2/3]); parts = []
        for lo, hi, lab in ((-np.inf, q[0], "low"), (q[0], q[1], "mid"), (q[1], np.inf, "high")):
            m = (x >= lo) & (x < hi); parts.append(f"{lab} {x[m].mean():+.2f}: {act[m].mean()/ship[m].mean():.3f}")
        print(f"  {c:5s} " + " | ".join(parts) + f"   corr(x, act-ship) {np.corrcoef(x, act-ship)[0,1]:+.3f}")

    print("\n=== 2. LOYO: shipped + k * (component rate - league) * g/(P+g)   (grid[0] = shipped) ===")
    grid = [0.0, 0.25, 0.5, 0.75, 1.0]
    for c in COMPS:
        loyo(S, years, grid, lambda k, c=c: ship + k * S[c] * wreal, f"{c}: season-to-date {c} pts/g over league")
    print("\n=== 3. realized-PPG blend: (P*shipped + g*ppg)/(P+g) - with and WITHOUT the TD points ===")
    loyo(S, years, [1000, 40, 20, 12, 5, 3], lambda Pv: (float(Pv) * ship + g * S["ppg"]) / (float(Pv) + g), "a) full realized PPG (1000 ~ shipped)")
    loyo(S, years, [1000, 40, 20, 12, 5, 3], lambda Pv: (float(Pv) * ship + g * S["ppg_notd"]) / (float(Pv) + g), "b) realized PPG with TDs replaced by the league TD pts/g (TD regression)")
    # explicit TD regression on top of a realized blend at P=12: subtract k * (td rate over league) * weight
    b12 = (12.0 * ship + g * S["ppg"]) / (12.0 + g)
    loyo(S, years, [0.0, 0.25, 0.5, 0.75, 1.0], lambda k: b12 - k * S["td"] * (g / (12.0 + g)), "c) P=12 blend then remove k x TD excess")

if __name__ == "__main__":
    main()
