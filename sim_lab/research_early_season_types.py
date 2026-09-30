#!/usr/bin/env python3
"""
EARLY-SEASON TYPES (Jack 2026-09-29): standing after each player's 3rd game, which
kinds of players went on to beat / miss the forward projection the rest of the way,
2019-25? Forward projection = the live base form, (5 x Clay per game + 3 x points
per game so far) / 8. Rest of season = his later played games, final week excluded
([[feedback_final_week_excluded]]), >= 4 games.

Features come from ctx_features.parquet (as of entering the 4th game) plus the TD
share of his first three games from the weekly DB. Every cut reports the pooled
ratio, a t-stat on the per-player residual and how many of the 7 seasons agree.
Writes data/early_types_hist.pkl for the 2026 candidate pass.
"""
import numpy as np, pandas as pd, os, sys
from backtest_sim_calibration import weekly_rec, played
HERE = os.path.dirname(os.path.abspath(__file__))
YOUNG = {"RB": 23, "WR": 23, "TE": 24, "QB": 25}

def build():
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet"))
    out = []
    for (y, name, pos), g in C.groupby(["year", "name", "pos"]):
        g = g.sort_values("wk")
        cp = g[g.g == 3]
        if cp.empty: continue
        r = cp.iloc[0]
        last = 16 if y <= 2020 else 17
        ros = g[(g.wk >= r.wk) & (g.wk <= last)]            # weeks 17 (2019-20) / 18 are not in play
        if len(ros) < 4: continue
        rec = weekly_rec(name, pos)
        tdsh = td3 = None; first = []
        if rec:
            first = sorted([w for w in rec.get("seasons", {}).get(str(y), []) if played(w) and w["wk"] < r.wk], key=lambda w: w["wk"])[:3]
            pts = sum(w.get("fpts") or 0 for w in first)
            td3 = sum((w.get("rtd") or 0) + (w.get("rctd") or 0) for w in first)
            tdpts = 6 * td3 + 4 * sum(w.get("ptd") or 0 for w in first)
            tdsh = tdpts / pts if pts > 3 else None
        fwd = (5 * r.clay + 3 * r.ppg) / 8
        out.append(dict(year=y, name=name, pos=pos, clay=r.clay, ppg3=r.ppg, fwd=fwd, ros=ros.act.mean(), n_ros=len(ros),
                        start=r.ppg / max(r.clay, 1), xfp=r.xfp_pg, gap=(r.xfp_pg - r.ppg) if pos != "QB" else np.nan,
                        snap=r.snap_std, snap_l1=r.snap_l1, snap_d=r.snap_l1 - r.snap_std, tgt_sh=r.tgt_sh, car_sh=r.car_sh,
                        tgt_py=r.tgt_sh_py, car_py=r.car_sh_py, g_py=r.g_py, ppg_py=r.ppg_py, age=r.age, exp=r.exp, rookie=r.rookie, yr2=r.yr2,
                        team_change=r.team_change, new_pc=r.new_pc, pick=r.draft_pick, tdsh=tdsh, td3=td3,
                        first_pts=[w.get("fpts") or 0 for w in first]))
    d = pd.DataFrame(out)
    d["res"] = d.ros - d.fwd
    d["young"] = [bool(a == a and a <= YOUNG[p] + .999) for a, p in zip(d.age, d.pos)]
    d["vet"] = d.exp.fillna(-1) >= 8
    return d

def line(label, x, years, base_ratio=None):
    if len(x) < 40:
        print(f"  {label:46s} n={len(x):4d}  (too few)"); return
    r = x.ros.sum() / x.fwd.sum(); t = x.res.mean() / (x.res.std() / np.sqrt(len(x)))
    per = [x[x.year == y].ros.sum() / x[x.year == y].fwd.sum() for y in years if (x.year == y).sum() >= 5]
    up = sum(1 for v in per if v > 1)
    flag = "  <<<" if abs(t) >= 2.5 and (up >= len(per) - 1 or up <= 1) else ""
    print(f"  {label:46s} n={len(x):4d}  rest-of-season / projected {r:.3f}  ({x.res.mean():+.2f} pts/g, t {t:+5.1f})  seasons above {up}/{len(per)}  "
          f"avg proj {x.fwd.mean():4.1f}  hit 120%+ {100*(x.ros >= 1.2*x.fwd).mean():3.0f}%  under 80% {100*(x.ros <= .8*x.fwd).mean():3.0f}%{flag}")

def cuts(d, years, title, bins, col, poss=("RB", "WR", "TE", "QB"), extra=None):
    print(f"\n=== {title} ===")
    for pos in poss:
        x = d[d.pos == pos]
        if extra is not None: x = x[extra(x)]
        for lab, lo, hi in bins:
            line(f"{pos} {lab}", x[(x[col] >= lo) & (x[col] < hi)], years)

def main():
    years = list(range(2019, 2026))
    d = build()
    d = d[d.fwd >= 5].copy()
    print(f"player-seasons: {len(d)} (3 games in, forward projection >= 5 half-PPR, >= 4 later games)")
    print("'<<<' = |t| >= 2.5 and at least 6 of 7 seasons on the same side.")
    print("\n=== 0. baseline by position (survivors run a little over by construction) ===")
    for pos in ("QB", "RB", "WR", "TE"): line(pos, d[d.pos == pos], years)
    START = [("cold start (<60% of Clay)", 0, .6), ("cool (60-85%)", .6, .85), ("on pace (85-115%)", .85, 1.15), ("warm (115-150%)", 1.15, 1.5), ("hot start (150%+)", 1.5, 99)]
    cuts(d, years, "1. how he started vs the preseason number", START, "start")
    for tl, lo, hi in (("ELITE preseason (Clay 13+ /g)", 13, 99), ("MID preseason (Clay 8-13)", 8, 13), ("LATE preseason (Clay under 8)", 0, 8)):
        cuts(d, years, f"1b. start x preseason tier: {tl}", START, "start", poss=("RB", "WR", "TE"), extra=lambda x, lo=lo, hi=hi: (x.clay >= lo) & (x.clay < hi))
    cuts(d, years, "1c. start, YOUNG players only", START, "start", poss=("RB", "WR", "TE"), extra=lambda x: x.young)
    cuts(d, years, "1d. start, ROOKIES only", START, "start", poss=("RB", "WR", "TE", "QB"), extra=lambda x: x.rookie == 1)
    cuts(d, years, "1e. start, 2nd-year players only", START, "start", poss=("RB", "WR", "TE", "QB"), extra=lambda x: x.yr2 == 1)
    cuts(d, years, "1f. start, veterans (9th season +) only", START, "start", poss=("RB", "WR", "TE", "QB"), extra=lambda x: x.vet)
    GAP = [("usage says 3+ MORE than his points", 3, 99), ("usage 1-3 more", 1, 3), ("in line", -1, 1), ("points 1-3 above usage", -3, -1), ("points 3+ ABOVE his usage", -99, -3)]
    cuts(d, years, "2. expected points from his usage vs what he actually scored (first 3 games)", GAP, "gap", poss=("RB", "WR", "TE"))
    TD = [("no TDs in the first 3", -1, .001), ("TDs under 25% of points", .001, .25), ("25-40%", .25, .40), ("TDs 40%+ of points", .40, 9)]
    cuts(d, years, "3. how much of the start was touchdowns", TD, "tdsh", poss=("RB", "WR", "TE"), extra=lambda x: x.tdsh.notna())
    SN = [("snaps falling 8+ pts (last game vs avg)", -99, -8), ("steady", -8, 8), ("snaps rising 8+ pts", 8, 99)]
    cuts(d, years, "4. snap share direction", SN, "snap_d", poss=("RB", "WR", "TE"), extra=lambda x: x.snap_d.notna())
    SL = [("under 50% snaps", 0, 50), ("50-70%", 50, 70), ("70-85%", 70, 85), ("85%+", 85, 101)]
    cuts(d, years, "4b. snap share level", SL, "snap", poss=("RB", "WR", "TE"), extra=lambda x: x.snap.notna())
    d["tgt_g"] = d.tgt_sh - d.tgt_py; d["car_g"] = d.car_sh - d.car_py
    RG = [("share DOWN 5+ pts vs last year", -9, -.05), ("about the same", -.05, .05), ("share UP 5+ pts vs last year", .05, 9)]
    cuts(d, years, "5. target share vs last season (players with 6+ games last year)", RG, "tgt_g", poss=("WR", "TE", "RB"), extra=lambda x: x.g_py >= 6)
    cuts(d, years, "5b. carry share vs last season (RB, 6+ games last year)", RG, "car_g", poss=("RB",), extra=lambda x: x.g_py >= 6)
    print("\n=== 6. changed teams / new play-caller ===")
    for pos in ("RB", "WR", "TE", "QB"):
        x = d[d.pos == pos]
        line(f"{pos} changed teams", x[x.team_change == 1], years); line(f"{pos} new play-caller", x[x.new_pc == 1], years)
    print("\n=== 7. consistency of the start: did all three games point the same way? ===")
    def allside(r, above):
        f = r.first_pts
        return len(f) == 3 and all((p > r.clay) == above for p in f)
    for pos in ("RB", "WR", "TE", "QB"):
        x = d[d.pos == pos]
        line(f"{pos} all 3 games ABOVE the preseason number", x[[allside(r, True) for r in x.itertuples()]], years)
        line(f"{pos} all 3 games BELOW the preseason number", x[[allside(r, False) for r in x.itertuples()]], years)
    d.drop(columns=["first_pts"]).to_pickle(os.path.join(HERE, "data", "early_types_hist.pkl"))

if __name__ == "__main__":
    main()
