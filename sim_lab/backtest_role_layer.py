#!/usr/bin/env python3
"""
Historical validation of the JS Model's ROLE layers (2019-2025) — the
vacated-opportunity boost and the player-movement question, reconstructed
from our own weekly data (targets/carries per player, teams via
opponent-sequence matching).

For each season Y:
  * per player: team_Y, team_{Y-1}, prior-season targets/carries + share of
    his old team's volume
  * per team: NET vacated share = (volume that left - volume that arrived) /
    team volume, split tgt vs carries (mirrors the live _jsVacatedCtx math)
  * core projection = 3-yr recency-weighted PPG (50/30/20, the JS core's
    heart) — the question is whether role adjustments IMPROVE it:
      V incumbent boost: 1 + eV * netVacatedShare(team_Y)   [stayers only]
      M mover effect: measured first (do team-changers beat/miss the core?),
        then tested as a flat per-position multiplier

Graded on season-Y PPG (>=6 games in Y, >=1 game in Y-1, pos RB/WR/TE + QB
reported separately), MAE + the empirical residual curves that justify (or
kill) each elasticity.
"""
import numpy as np
import json, os
from collections import defaultdict
from backtest_sim_calibration import (played, WEEKLY, infer_team, POS_KEEP)
import backtest_sim_calibration as cal

W3 = [0.5, 0.3, 0.2]

def season_rows(rec, Y):
    return [w for w in rec.get("seasons", {}).get(str(Y), []) if played(w)]

def ppg_of(rows):
    pts = [w["fpts"] for w in rows if isinstance(w.get("fpts"), (int, float))]
    return (sum(pts) / len(pts), len(pts)) if pts else (None, 0)

def main():
    # one pass: every player in the weekly DB with usable data
    recs = []
    for name_norm, lst in WEEKLY.items():
        for rec in lst:
            if rec.get("pos") in POS_KEEP:
                recs.append(rec)

    for_report = {"mover_resid": defaultdict(list), "vac_resid": defaultdict(list)}
    results = defaultdict(lambda: defaultdict(list))  # pos -> model -> abs errs
    EVS = [0.0, 0.25, 0.5, 1.0]

    for Y in range(2019, 2026):
        # --- team volume + membership maps for Y-1 and Y ---
        prev_vol = defaultdict(lambda: [0.0, 0.0])   # team -> [tgt, car]
        player_prev = {}                              # id(rec) -> (team_prev, tgt, car)
        team_now = {}
        for rec in recs:
            tp = infer_team(rec, Y - 1)
            tn = infer_team(rec, Y)
            if tn:
                team_now[id(rec)] = tn
            if tp:
                rows = season_rows(rec, Y - 1)
                tgt = sum(w.get("tgt") or 0 for w in rows)
                car = sum(w.get("ra") or 0 for w in rows)
                player_prev[id(rec)] = (tp, tgt, car)
                prev_vol[tp][0] += tgt
                prev_vol[tp][1] += car
        # net vacated per team (who had prev volume and where are they now)
        net = defaultdict(lambda: [0.0, 0.0])        # team -> [netTgt, netCar]
        for rec in recs:
            pp = player_prev.get(id(rec))
            if not pp:
                continue
            tp, tgt, car = pp
            tn = team_now.get(id(rec))
            if tn != tp:
                net[tp][0] += tgt; net[tp][1] += car
                if tn:
                    net[tn][0] -= tgt; net[tn][1] -= car
        vac_share = {}
        for t, (vt, vc) in net.items():
            tot = prev_vol.get(t)
            if tot and tot[0] > 100:
                vac_share[t] = (vt / tot[0], vc / max(100, tot[1]))

        # --- per-player: core projection + adjustments vs actual ---
        for rec in recs:
            pos = rec["pos"]
            act, g = ppg_of(season_rows(rec, Y))
            if act is None or g < 6:
                continue
            prev_rows = season_rows(rec, Y - 1)
            if not prev_rows:
                continue
            num = den = 0.0
            for i, yr in enumerate([Y - 1, Y - 2, Y - 3]):
                p, gg = ppg_of(season_rows(rec, yr))
                if p is not None and gg >= 4:
                    num += W3[i] * p; den += W3[i]
            if den == 0:
                continue
            core = num / den
            if core < 3:
                continue
            tn = team_now.get(id(rec))
            pp = player_prev.get(id(rec))
            moved = bool(tn and pp and pp[0] != tn)
            resid = act / core
            for_report["mover_resid"][(pos, moved)].append(resid)
            vs = vac_share.get(tn) if tn else None
            if vs is not None and not moved:
                share = vs[0] if pos in ("WR", "TE", "QB") else 0.4 * vs[0] + 0.6 * vs[1]
                bucket = "high" if share > 0.10 else ("low" if share < -0.10 else "mid")
                for_report["vac_resid"][(pos, bucket)].append(resid)
            # graded models
            results[pos]["core"].append(abs(core - act))
            for eV in EVS:
                m = 1.0
                if vs is not None and not moved:
                    share = vs[0] if pos in ("WR", "TE", "QB") else 0.4 * vs[0] + 0.6 * vs[1]
                    m = 1 + eV * max(-0.35, min(0.35, share))
                results[pos][f"V{eV}"].append(abs(core * m - act))
        print(f"  {Y} done")

    print("\n=== Mover vs stayer residuals (actual / 3yr-core) ===")
    for pos in ("QB", "RB", "WR", "TE"):
        s = for_report["mover_resid"].get((pos, False), [])
        m = for_report["mover_resid"].get((pos, True), [])
        print(f"  {pos}: stayers {np.mean(s):.3f} (n={len(s)})   MOVERS {np.mean(m):.3f} (n={len(m)})")

    print("\n=== Incumbent residual by team net-vacated share (stayers only) ===")
    for pos in ("QB", "RB", "WR", "TE"):
        line = f"  {pos}:"
        for b in ("low", "mid", "high"):
            r = for_report["vac_resid"].get((pos, b), [])
            line += f"  {b}(<-10%|..|>+10%) {np.mean(r):.3f} (n={len(r)})" if r else f"  {b} —"
        print(line)

    print("\n=== MAE: core vs vacated-boost elasticities (stayers get 1+eV*netShare) ===")
    for pos in ("QB", "RB", "WR", "TE"):
        line = f"  {pos}: core {np.mean(results[pos]['core']):.3f}"
        best = ("core", np.mean(results[pos]["core"]))
        for eV in EVS[1:]:
            v = np.mean(results[pos][f"V{eV}"])
            line += f"  eV{eV} {v:.3f}"
            if v < best[1]:
                best = (f"eV{eV}", v)
        print(line + f"   <- best {best[0]}")

if __name__ == "__main__":
    main()
