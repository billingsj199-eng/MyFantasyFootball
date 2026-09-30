#!/usr/bin/env python3
"""
REST-OF-SEASON: volume regression + quality tilt (Jack 2026-09-30, from the metric atlas).

Standing at every in-season week (2+ games played, 3+ later games), the per-game live projection is compared with
the player's points per game over the REST of the season. Candidates, every knob picked leave-one-season-out
on rest-of-season MSE (plain and level-weighted, weight = the live number, Jack's "high scorers matter more"):

  QB  (a) level shrink toward the week's top-32 mean      pred = mu + k (live - mu)
      (b) dropback tilt                                    pred = live x (1 - e x z(dropbacks per game))
      (c) both
  TE  (a) team pass-rate tilt                              pred = live x (1 - e x z(team neutral pass rate))
      (b) level shrink
  WR / TE quality tilt                                     pred = live x (1 + e x z(quality)), quality = PRIOR-season
      PFF yards per route run, prior-season PFF receiving grade, season-to-date PFF YPRR (z within position-season)
Weekly numbers are untouched by design: this is about the horizon. Log ros_quality_volume.log.
"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); CACHE = r"E:\MyFantasyFootball\pbp_cache"

def prior_pff():
    pl = pd.read_csv(os.path.join(CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "pff_id"]).dropna(); pff2g = dict(zip(pl.pff_id.astype(int), pl.gsis_id))
    rows = []
    for Y in range(2018, 2025):
        f = os.path.join(CACHE, "pff", f"pff_receiving_{Y}.csv")
        if not os.path.exists(f): continue
        d = pd.read_csv(f)
        cols = [c for c in ("yprr", "grades_offense", "grades_pass_route", "routes", "route_rate", "targets") if c in d.columns]
        d = d[["player_id"] + cols].copy(); d["pid"] = d.player_id.map(pff2g); d["year"] = Y + 1
        d = d[d.pid.notna() & (d.routes >= 100)] if "routes" in cols else d[d.pid.notna()]
        rows.append(d.rename(columns={c: "py_" + c for c in cols}))
    return pd.concat(rows, ignore_index=True).drop(columns=["player_id"])

def zscore(d, col, by):
    g = d.groupby(by)[col]
    return (d[col] - g.transform("mean")) / g.transform("std").replace(0, np.nan)

def loyo(d, forms, years, log, label, base="live", target="ros"):
    """forms: {name: (grid, fn(d, v) -> pred)}; prints plain + level-weighted ROS MSE change and seasons better"""
    for name, (grid, fn) in forms.items():
        picks = []; s1 = s0 = w1 = w0 = 0.0; wins = 0; wwins = 0
        for Y in years:
            tr = d.year != Y; te = ~tr
            if te.sum() < 20: continue
            v = min(grid, key=lambda v: ((fn(d[tr], v) - d[tr][target]) ** 2).mean()); picks.append(v)
            p = fn(d[te], v); a = d[te][target]; b = d[te][base]; w = d[te].live
            e1 = ((p - a) ** 2); e0 = ((b - a) ** 2)
            s1 += e1.sum(); s0 += e0.sum(); w1 += (e1 * w).sum(); w0 += (e0 * w).sum(); wins += e1.mean() < e0.mean(); wwins += (e1 * w).sum() < (e0 * w).sum()
        log(f"  {label} {name:34s} picks {picks}  ROS MSE {100*(s1/s0-1):+6.2f}% ({wins}/{len(picks)})  level-weighted {100*(w1/w0-1):+6.2f}% ({wwins}/{len(picks)})")

def main():
    lf = open(os.path.join(HERE, "ros_quality_volume.log"), "w", encoding="utf-8")
    def log(s=""):
        print(s); lf.write(s + "\n")
    M = pd.read_parquet(os.path.join(HERE, "data", "metric_atlas_rows.parquet"))
    M = M[(M.live >= 5) & (M.g >= 2) & M.ros.notna()].copy()
    years = sorted(M.year.unique())
    P = prior_pff(); M = M.merge(P, on=["year", "pid"], how="left")
    log(f"=== rest-of-season tests: {len(M)} checkpoints (live >= 5, 2+ games played, 3+ later games); prior-season PFF on {int(M.py_yprr.notna().sum())} ===")
    for pos in ("QB", "RB", "WR", "TE"):
        x = M[M.pos == pos]; log(f"  {pos}: rest-of-season / live = {x.ros.sum()/x.live.sum():.3f}  (top third by live {x[x.live >= x.live.quantile(2/3)].ros.sum()/x[x.live >= x.live.quantile(2/3)].live.sum():.3f}, bottom third {x[x.live <= x.live.quantile(1/3)].ros.sum()/x[x.live <= x.live.quantile(1/3)].live.sum():.3f})")
    # ---- QB
    q = M[M.pos == "QB"].copy()
    q["mu"] = q.set_index(["year", "wk"]).index.map(q.groupby(["year", "wk"]).live.apply(lambda s: s.nlargest(32).mean()))
    q["zdb"] = zscore(q, "dropbacks_per_g", ["year", "wk"]).clip(-2, 2).fillna(0)
    q["zatt"] = zscore(q, "att_pg", ["year", "wk"]).clip(-2, 2).fillna(0)
    log("\n--- QB, rest of season ---")
    KS = [1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7]; ES = [0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12]
    loyo(q, {"level shrink (two-sided)": (KS, lambda d, k: d.mu + k * (d.live - d.mu)),
             "level floor (below mean only)": (KS, lambda d, k: np.where(d.live < d.mu, d.mu + k * (d.live - d.mu), d.live)),
             "level cap (above mean only)": (KS, lambda d, k: np.where(d.live > d.mu, d.mu + k * (d.live - d.mu), d.live)),
             "dropback tilt": (ES, lambda d, e: d.live * (1 - e * d.zdb)),
             "pass-attempt tilt": (ES, lambda d, e: d.live * (1 - e * d.zatt)),
             "floor k.70 + dropback tilt": (ES, lambda d, e: np.where(d.live < d.mu, d.mu + 0.7 * (d.live - d.mu), d.live) * (1 - e * d.zdb))}, years, log, "QB")
    for lo, hi, lab in ((-9, -0.5, "few dropbacks"), (-0.5, 0.5, "average"), (0.5, 9, "many dropbacks")):
        x = q[(q.zdb >= lo) & (q.zdb < hi)]; log(f"      {lab:15s} n={len(x):4d}  ROS/live {x.ros.sum()/x.live.sum():.3f}")
    # ---- TE
    t = M[M.pos == "TE"].copy()
    t["mu"] = t.set_index(["year", "wk"]).index.map(t.groupby(["year", "wk"]).live.apply(lambda s: s.nlargest(24).mean()))
    t["zpr"] = zscore(t, "team_neutral_pass_rate_std", ["year", "wk"]).clip(-2, 2).fillna(0)
    log("\n--- TE, rest of season ---")
    loyo(t, {"team pass-rate tilt": (ES, lambda d, e: d.live * (1 - e * d.zpr)),
             "level shrink (two-sided)": (KS, lambda d, k: d.mu + k * (d.live - d.mu)),
             "level floor": (KS, lambda d, k: np.where(d.live < d.mu, d.mu + k * (d.live - d.mu), d.live))}, years, log, "TE")
    for lo, hi, lab in ((-9, -0.5, "run-heavy team"), (-0.5, 0.5, "average"), (0.5, 9, "pass-heavy team")):
        x = t[(t.zpr >= lo) & (t.zpr < hi)]; log(f"      {lab:15s} n={len(x):4d}  ROS/live {x.ros.sum()/x.live.sum():.3f}")
    # ---- WR / TE quality tilt
    log("\n--- WR / TE quality tilt on the rest-of-season number ---")
    for pos in ("WR", "TE"):
        d = M[M.pos == pos].copy()
        for col in ("py_yprr", "py_grades_offense", "py_grades_pass_route", "pff_yprr", "pff_grades_offense", "yprr_man"):
            if col not in d.columns: continue
            dd = d[d[col].notna()].copy(); dd["zq"] = zscore(dd, col, ["year"]).clip(-2.5, 2.5)
            if len(dd) < 300: continue
            n = f"{col} (n={len(dd)})"
            loyo(dd, {n: (ES, lambda d, e: d.live * (1 + e * d.zq))}, years, log, pos)
            for lo, hi, lab in ((-9, -0.5, "low"), (-0.5, 0.5, "mid"), (0.5, 9, "high")):
                x = dd[(dd.zq >= lo) & (dd.zq < hi)]; log(f"        {col} {lab:4s} n={len(x):4d}  ROS/live {x.ros.sum()/x.live.sum():.3f}")
    # does prior-season quality still matter for the NEXT game (not just ROS)?
    log("\n--- same quality tilt graded on the NEXT game instead of the rest of season (sanity) ---")
    for pos in ("WR", "TE"):
        d = M[(M.pos == pos) & M.py_yprr.notna()].copy(); d["zq"] = zscore(d, "py_yprr", ["year"]).clip(-2.5, 2.5)
        loyo(d, {"prior-season YPRR tilt, next game": (ES, lambda d, e: d.live * (1 + e * d.zq))}, years, log, pos, target="act")
    lf.close()

if __name__ == "__main__":
    main()
