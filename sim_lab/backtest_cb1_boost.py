#!/usr/bin/env python3
"""
Size the CB1-OUT BOOST layer, 2019-2025. Follow-up to backtest_cb_shadow.py's
control finding: losing an ORDINARY CB1 lifts opposing WRs ~+5.5% on/off.

CB1 per (Y, team) = the CB with the most games at def_pct >= 0.6 that season
(ties -> higher avg snap share; >=8 games to qualify). Full-season identity is
mild lookahead, but the LIVE version identifies CB1 from season-to-date snaps
+ current rosters, which converges on the same guy.

Graded on the same P=5 blend base (x the shipped jsOppMult-style FPA layer)
as every other backtest. Sweeps a flat boost on CB1-out WR-weeks:
  - all defenses pooled
  - elite-list defenses vs ordinary (the dock already returns elite outs
    to neutral - do they need MORE?)
  - slot tiers (the dock's slot shield inverted?)
"""
import numpy as np
import pandas as pd
import os
from collections import defaultdict
from backtest_cb_shadow import (build_wr_samples, build_wr_fpa, ELITE_CBS,
                                team_norm, CACHE, YEARS)
import backtest_sim_calibration as cal

PFF = r"E:\MyFantasyFootball\pbp_cache\pff"

def load_cb1():
    """(Y, team) -> {name, act: set(wks), team_wks: set(wks)}"""
    out = {}
    for Y in YEARS:
        df = pd.read_parquet(
            os.path.join(CACHE, f"snap_counts_{Y}.parquet"),
            columns=["week", "game_type", "player", "position", "team", "defense_pct"])
        df = df[df.game_type == "REG"]
        tw = defaultdict(set)
        for t, wk in df[["team", "week"]].drop_duplicates().itertuples(index=False):
            tw[team_norm(t)].add(int(wk))
        d = df[(df.position == "CB") & (df.defense_pct >= 0.6)]
        best = {}
        for (nm, t), rows in d.groupby(["player", "team"]):
            tm = team_norm(t)
            wks = set(int(w) for w in rows.week)
            key = (len(wks), float(rows.defense_pct.mean()))
            if len(wks) >= 8 and (tm not in best or key > best[tm][0]):
                best[tm] = (key, nm, wks)
        for tm, (_, nm, wks) in best.items():
            out[(Y, tm)] = {"name": nm, "act": wks, "team_wks": tw[tm]}
    return out

def load_slot():
    out = {}
    for y in YEARS:
        df = pd.read_csv(os.path.join(PFF, f"pff_receiving_{y}.csv"))
        df = df[(df.position == "WR") & (df.routes >= 100)]
        for r in df.itertuples(index=False):
            out[(y, cal.norm(r.player))] = r.slot_rate
    return out

def sweep(sub, label, boosts=(1.00, 1.02, 1.04, 1.06, 1.08, 1.10)):
    if len(sub) < 30:
        print(f"  {label:28s} n={len(sub)} (too small)")
        return
    a = np.array([s["act"] for s in sub]); b = np.array([s["bf"] for s in sub])
    ratio = a.sum() / b.sum()
    line = f"  {label:28s} n={len(sub):4d} ratio {ratio:.3f} |"
    best = None
    for d in boosts:
        m = float(np.mean((b * d - a) ** 2))
        line += f" x{d:.2f} {m:.2f}"
        if best is None or m < best[1]:
            best = (d, m)
    print(line + f"  <- best x{best[0]:.2f}")

def main():
    cb1 = load_cb1()
    slot = load_slot()
    fpa = build_wr_fpa()
    S = build_wr_samples()
    elite_norm = {(Y, cal.norm(n)) for Y, ns in ELITE_CBS.items() for n in ns}
    out_s, act_s = [], []
    for s in S:
        r = cb1.get((s["Y"], s["opp"]))
        if not r or s["wk"] not in r["team_wks"]:
            continue
        s["bf"] = s["base"] * fpa(s["Y"], s["opp"], s["wk"])
        s["elite"] = (s["Y"], cal.norm(r["name"])) in elite_norm
        s["slot"] = slot.get((s["Y"], cal.norm(s["name"])))
        (act_s if s["wk"] in r["act"] else out_s).append(s)
    print(f"{len(act_s)} CB1-active WR-weeks, {len(out_s)} CB1-out WR-weeks\n")

    print("=== flat boost sweep on CB1-OUT weeks (base x shipped FPA) ===")
    sweep(out_s, "ALL defenses")
    sweep([s for s in out_s if not s["elite"]], "ordinary CB1 out")
    sweep([s for s in out_s if s["elite"]], "elite-list CB1 out")

    print("\n=== slot tiers, ordinary-CB1-out only ===")
    ordinary = [s for s in out_s if not s["elite"]]
    sweep([s for s in ordinary if s["slot"] is not None and s["slot"] < 30], "outside <30%")
    sweep([s for s in ordinary if s["slot"] is not None and 30 <= s["slot"] < 60], "mixed 30-60%")
    sweep([s for s in ordinary if s["slot"] is not None and s["slot"] >= 60], "slot >60%")
    sweep([s for s in ordinary if s["slot"] is None], "no PFF")

    # sanity: CB1-active weeks should need no adjustment (baseline holds)
    print("\n=== control: CB1-ACTIVE weeks (should be ~x1.00) ===")
    sweep(act_s, "ALL active", boosts=(0.96, 0.98, 1.00, 1.02, 1.04))

if __name__ == "__main__":
    main()
