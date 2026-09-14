#!/usr/bin/env python3
"""
Follow-ups to backtest_cb_shadow.py ("anyone else? same impacts?"):

1. FIELD SCAN — every CB-season 2019-25 with >=8 active games (def_pct>=.6):
   opposing-WR act/base with him active. Distribution + 2024/25 leaders.
2. PERSISTENCE — does a CB's suppression ratio in year Y predict year Y+1?
   If r ~ 0, individual dock sizes are unfittable — one flat dock is right.
3. NON-ELITE CONTROL — paired on/off for each team's top-snap CB NOT on the
   elite list: does losing an ordinary CB1 also cost ~6%? If yes, the effect
   is "any CB1 out", not elite-specific.
4. 2026 CANDIDATES — recent numbers for named candidates not on the list.
"""
import numpy as np
import pandas as pd
import os
from collections import defaultdict
from backtest_cb_shadow import build_wr_samples, ELITE_CBS, team_norm, ratio, CACHE, YEARS
import backtest_sim_calibration as cal

CANDIDATES = ["Trent McDuffie", "Devon Witherspoon", "Denzel Ward",
              "DaRon Bland", "Charvarius Ward", "Marshon Lattimore",
              "A.J. Terrell", "Jaycee Horn", "Joey Porter Jr.",
              "Cooper DeJean", "Tariq Woolen", "Garrett Williams",
              "Jaire Alexander", "Marlon Humphrey", "Jalen Ramsey",
              "Sauce Gardner", "Patrick Surtain II", "Derek Stingley Jr.",
              "Christian Gonzalez", "Quinyon Mitchell", "Jaylon Johnson"]

def main():
    S = build_wr_samples()
    byDW = defaultdict(list)             # (Y, def, wk) -> samples
    for s in S:
        byDW[(s["Y"], s["opp"], s["wk"])].append(s)

    # every CB-season: active weeks per (Y, team, cb)
    cb_seasons = []                      # dicts: Y, cb, tm, act_wks, team_wks
    for Y in YEARS:
        df = pd.read_parquet(
            os.path.join(CACHE, f"snap_counts_{Y}.parquet"),
            columns=["week", "game_type", "player", "position", "team", "defense_pct"])
        df = df[df.game_type == "REG"]
        tw = defaultdict(set)
        for t, wk in df[["team", "week"]].drop_duplicates().itertuples(index=False):
            tw[team_norm(t)].add(int(wk))
        d = df[(df.position == "CB") & (df.defense_pct >= 0.6)]
        g = d.groupby(["player", "team"])
        for (nm, t), rows in g:
            wks = sorted(set(int(w) for w in rows.week))
            if len(wks) >= 8:
                tm = team_norm(t)
                cb_seasons.append({"Y": Y, "cb": nm, "tm": tm, "act": set(wks),
                                   "team_wks": tw[tm],
                                   "snap": float(rows.defense_pct.mean())})

    # per-CB-season active ratio
    for r in cb_seasons:
        sub = [s for wk in r["act"] for s in byDW.get((r["Y"], r["tm"], wk), [])]
        r["ratio"], r["n"] = ratio(sub)
    field = [r for r in cb_seasons if r["ratio"] is not None and r["n"] >= 15]
    rats = np.array([r["ratio"] for r in field])
    print(f"=== 1. FIELD: {len(field)} CB-seasons (>=8 active gms, n>=15 WR-wks) ===")
    print(f"  mean {rats.mean():.3f}  sd {rats.std():.3f}  "
          f"p10 {np.percentile(rats,10):.3f}  p90 {np.percentile(rats,90):.3f}")

    # 2. persistence Y -> Y+1 (same CB, any team)
    byCb = defaultdict(dict)
    for r in field:
        byCb[cal.norm(r["cb"])][r["Y"]] = r
    xs, ys = [], []
    for nm, yrs in byCb.items():
        for Y in yrs:
            if Y + 1 in yrs:
                xs.append(yrs[Y]["ratio"]); ys.append(yrs[Y + 1]["ratio"])
    xs, ys = np.array(xs), np.array(ys)
    r_yoy = float(np.corrcoef(xs, ys)[0, 1]) if len(xs) > 10 else float("nan")
    print(f"\n=== 2. PERSISTENCE: {len(xs)} consecutive CB-season pairs ===")
    print(f"  corr(ratio_Y, ratio_Y+1) = {r_yoy:.3f}")
    lo = xs <= np.percentile(xs, 25); hi = xs >= np.percentile(xs, 75)
    print(f"  best-quartile CBs (Y ratio {xs[lo].mean():.3f}) -> next yr {ys[lo].mean():.3f}")
    print(f"  worst-quartile   (Y ratio {xs[hi].mean():.3f}) -> next yr {ys[hi].mean():.3f}")

    # 3. non-elite CB1 on/off control (paired, >=2 out weeks with samples)
    elite_norm = {(Y, cal.norm(n)) for Y, ns in ELITE_CBS.items() for n in ns}
    print("\n=== 3. NON-ELITE CB1 ON/OFF CONTROL ===")
    top = {}
    for r in cb_seasons:
        if (r["Y"], cal.norm(r["cb"])) in elite_norm:
            continue
        k = (r["Y"], r["tm"])
        if k not in top or len(r["act"]) * r["snap"] > len(top[k]["act"]) * top[k]["snap"]:
            top[k] = r
    pa = po = wa = wo = 0
    kept = 0
    for r in top.values():
        outw = r["team_wks"] - r["act"]
        so = [s for wk in outw for s in byDW.get((r["Y"], r["tm"], wk), [])]
        sa = [s for wk in r["act"] for s in byDW.get((r["Y"], r["tm"], wk), [])]
        ow = len({s["wk"] for s in so})
        if ow < 2 or not sa:
            continue
        kept += 1
        pa += sum(s["act"] for s in sa); wa += sum(s["base"] for s in sa)
        po += sum(s["act"] for s in so); wo += sum(s["base"] for s in so)
    print(f"  {kept} non-elite CB1 defense-seasons w/ >=2 out-weeks:")
    print(f"  active {pa/wa:.3f}   out {po/wo:.3f}   -> CB1 worth {100*(po/wo-pa/wa):+.1f}%")

    # 4. named candidates, recent seasons
    print("\n=== 4. NAMED CANDIDATES (2023-25 active ratios; * = on elite list that yr) ===")
    cand_norm = {cal.norm(n): n for n in CANDIDATES}
    rows = [r for r in field if cal.norm(r["cb"]) in cand_norm and r["Y"] >= 2023]
    for r in sorted(rows, key=lambda r: (cal.norm(r["cb"]), r["Y"])):
        star = "*" if (r["Y"], cal.norm(r["cb"])) in elite_norm else " "
        print(f"  {r['Y']} {r['cb']:22s}{star} {r['tm']:4s} {len(r['act']):2d} gms  "
              f"ratio {r['ratio']:.3f} (n={r['n']:3d})  snap {r['snap']:.2f}")

if __name__ == "__main__":
    main()
