#!/usr/bin/env python3
"""
DST COMPONENT COUNTS vs opponent implied total, 2019-2025 (Jack 2026-11-21: "fix scoring" - dstWeeklyMean ignored
league scoring, so a 2-pt-sack league got the same D/ST projection as a 1-pt league).

dstWeeklyMean (16.2 - 0.436 x oppImplied) is in points at the default rules it was fit on (sack 1, INT 2, FR 2, def TD 6,
safety 2, blocked kick 2, forced fumble 0, PA buckets 10/7/4/1/0/-1/-4). To rescore it for a league, the engine adds
  sum_k (league_k - default_k) x E[count_k | oppImplied]
so a default-scored league is unchanged to the bit. This script fits E[count_k | oppImplied] = max(floor, a + b x imp)
per stat and the opponent-score distribution (normal: mean a + b x imp, sd s) for the points-allowed buckets, then
checks that the components re-add to the shipped mean. Prints the constants pasted into engine.js DST_COMP.
Log: dst_components_fit.log
"""
import os
import numpy as np
import pandas as pd
from math import erf, sqrt
from backtest_target_area import implied_map, YEARS, CACHE

ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS"}
def tm(t): return ALIAS.get(t, t)
STATS = ["sack", "int", "fum_rec", "ff", "def_td", "safe", "blk_kick"]
DEFAULT = {"sack": 1, "int": 2, "fum_rec": 2, "ff": 0, "def_td": 6, "safe": 2, "blk_kick": 2}
# Sleeper keys, upper bound inclusive (lo, hi, default pts)
PA = [("pts_allow_0", -1, 0, 10), ("pts_allow_1_6", 0, 6, 7), ("pts_allow_7_13", 6, 13, 4), ("pts_allow_14_20", 13, 20, 1),
      ("pts_allow_21_27", 20, 27, 0), ("pts_allow_28_34", 27, 34, -1), ("pts_allow_35p", 34, 999, -4)]

def load(Y):
    cols = ["season_type", "week", "game_id", "posteam", "defteam", "home_team", "away_team", "home_score", "away_score",
            "spread_line", "total_line", "sack", "interception", "fumble_lost", "fumble_forced", "touchdown", "td_team",
            "safety", "field_goal_result", "punt_blocked"]
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), usecols=cols, low_memory=False)
    df = df[df.season_type == "REG"]
    lines = df.dropna(subset=["spread_line", "total_line", "posteam"]).groupby("game_id").first()
    d = df[df.defteam.notna()].copy(); d["defteam"] = d.defteam.map(tm)
    g = d.groupby(["defteam", "week"])
    cnt = pd.DataFrame({
        "sack": g.sack.sum(), "int": g.interception.sum(), "fum_rec": g.fumble_lost.sum(), "ff": g.fumble_forced.sum(),
        "safe": g.safety.sum(),
        "blk_kick": d.assign(b=(d.field_goal_result == "blocked").astype(int) + d.punt_blocked.fillna(0)).groupby(["defteam", "week"]).b.sum(),
        "def_td": d.assign(t=((d.touchdown == 1) & (d.td_team.map(lambda x: tm(x) if isinstance(x, str) else x) == d.defteam)).astype(int)).groupby(["defteam", "week"]).t.sum(),
    }).fillna(0).reset_index()
    games = df.dropna(subset=["home_team"]).groupby("game_id").first()
    opp, pa = {}, {}
    for _, r in games.iterrows():
        w, h, a = int(r.week), tm(r.home_team), tm(r.away_team)
        opp[(h, w)], opp[(a, w)] = a, h; pa[(h, w)], pa[(a, w)] = int(r.away_score), int(r.home_score)
    imp = implied_map(lines)
    rows = []
    for r in cnt.itertuples(index=False):
        k = (r.defteam, int(r.week))
        if k not in opp: continue
        oi = imp.get((opp[k], int(r.week)))
        if oi is None: continue
        rows.append(dict(r._asdict(), season=Y, imp=oi, pa=pa[k]))
    return pd.DataFrame(rows)

def ncdf(x, m, s): return 0.5 * (1 + erf((x - m) / (s * sqrt(2))))
def pa_probs(m, s):
    return [ncdf(hi + 0.5, m, s) - (ncdf(lo + 0.5, m, s) if lo >= 0 else 0.0) for _, lo, hi, _ in PA]

def main():
    df = pd.concat([load(Y) for Y in YEARS], ignore_index=True)
    print(f"{len(df)} DST team-weeks {YEARS[0]}-{YEARS[-1]} | opp implied mean {df.imp.mean():.2f}")
    X = np.c_[np.ones(len(df)), df.imp.values]
    fit = {}
    print("\nE[count | oppImplied] = a + b x imp")
    for s in STATS:
        a, b = np.linalg.lstsq(X, df[s].values, rcond=None)[0]; fit[s] = (a, b)
        print(f"  {s:8s} a {a:+.4f} b {b:+.5f} | mean {df[s].mean():.3f} | at imp 17/22.5/28: " +
              " ".join(f"{a + b * i:.3f}" for i in (17, 22.5, 28)))
    a, b = np.linalg.lstsq(X, df.pa.values, rcond=None)[0]
    sd = float(np.std(df.pa.values - (a + b * df.imp.values)))
    print(f"\nopp score ~ N({a:.3f} + {b:.4f} x imp, sd {sd:.3f})")
    # bucket calibration
    print("PA bucket share, actual vs normal model:")
    pr = np.array([pa_probs(a + b * i, sd) for i in df.imp.values])
    for j, (k, lo, hi, _) in enumerate(PA):
        act = ((df.pa > lo) & (df.pa <= hi)).mean()
        print(f"  {k:16s} actual {act:.4f}  model {pr[:, j].mean():.4f}")
    # consistency: components at default rules vs the shipped mean
    print("\ncomponents re-added at default rules vs shipped 16.2 - 0.436 x imp:")
    for i in (15, 18, 20, 22.5, 25, 28, 31):
        comp = sum(DEFAULT[s] * max(0.0, fit[s][0] + fit[s][1] * i) for s in STATS)
        comp += sum(p * d for p, (_, _, _, d) in zip(pa_probs(a + b * i, sd), PA))
        print(f"  imp {i:5.1f}: components {comp:5.2f} | shipped {16.2 - 0.436 * i:5.2f}")
    act_pts = sum(DEFAULT[s] * df[s] for s in STATS) + df.pa.map(lambda v: next(d for _, lo, hi, d in PA if lo < v <= hi))
    print(f"  realized mean pts {act_pts.mean():.3f} | shipped at realized imps {(16.2 - 0.436 * df.imp).mean():.3f}")
    print("\nengine.js DST_COMP:")
    print("  " + ", ".join(f"{s}: [{fit[s][0]:.4f}, {fit[s][1]:.5f}]" for s in STATS))
    print(f"  pa: [{a:.4f}, {b:.4f}, {sd:.3f}]")

if __name__ == "__main__":
    main()
