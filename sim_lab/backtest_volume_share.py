#!/usr/bin/env python3
"""
The VOLUME x SHARE model (Jack's spec): project THIS season's team volume,
then each player's share of it — instead of raw per-game rates or vacated
bumps. RB/WR/TE only (QB core already ties Clay). Backtested 2019-2025.

  team volume (Y):   targets/g and carries/g = league mean + k * (team_{Y-1}
                     - league mean), k = 0.60 same coach / 0.35 new coach
                     (persistence from coach_research.json; new-HC lists too)
  player share (Y):  50/30/20-weighted share of HIS team's pool over Y-1..Y-3
                     x mover contract tier (1.0 / .95 / .86 / .94 unknown —
                     the backtested discount) x young-player growth bump
                     (exp<=2: x1.10, from the residual curves)
  efficiency (Y):    half-PPR receiving pts/target + rushing pts/carry,
                     3yr-weighted, SHRUNK hard toward position mean
                     (efficiency doesn't persist — sweep the shrink)
  PPG = tgt_share x team_tgt/g x pts_per_tgt + car_share x team_car/g x pts_per_car

Team pools are self-consistent: sum of ALL weekly-DB players' targets/carries
per (team, season), teams via opponent-sequence matching. Graded vs actual
PPG (>=6 games) against the 3-yr recency core, plus a 50/50 blend.
"""
import numpy as np
import pandas as pd
import json, os
from collections import defaultdict
from backtest_sim_calibration import (played, WEEKLY, infer_team, POS_KEEP,
                                      SCHEDULES, CHANGES)
import backtest_sim_calibration as cal

CACHE = r"E:\MyFantasyFootball\pbp_cache"
W3 = [0.5, 0.3, 0.2]
POS = ("RB", "WR", "TE")
K_SAME, K_NEW = 0.60, 0.35
EXP_BUMP = 1.10
MOVER_TIER = {"big": 1.0, "mid": 0.95, "cheap": 0.86, "unknown": 0.94}
EFF_SHRINKS = [0.50, 1.00]
BLENDS = [0.4, 0.3, 0.2]   # weight on the volume-share side vs the core

def rows_of(rec, Y):
    return [w for w in rec.get("seasons", {}).get(str(Y), []) if played(w)]

def main():
    # ---- contracts for mover tiers ----
    con = pd.read_parquet(os.path.join(CACHE, "historical_contracts.parquet"),
                          columns=["player", "position", "year_signed", "apy_cap_pct"])
    con["norm"] = con.player.map(cal.norm)
    deals = defaultdict(list)
    for _, r in con.dropna(subset=["apy_cap_pct"]).iterrows():
        deals[(r.norm, int(r.year_signed))].append(float(r.apy_cap_pct))

    recs = []
    for name_norm, lst in WEEKLY.items():
        for rec in lst:
            if rec.get("pos") in POS_KEEP:
                recs.append((name_norm, rec))

    # ---- per (player, season): team, tgt, car, rec-pts, rush-pts, games ----
    P = {}          # (id(rec), Y) -> dict
    team_pool = defaultdict(lambda: [0.0, 0.0])   # (team, Y) -> [tgt, car]
    team_games = {}
    first_seen = {}
    for nk, rec in recs:
        for Ys in rec.get("seasons", {}):
            Y = int(Ys)
            if Y < 2015:
                continue
            first_seen[id(rec)] = min(first_seen.get(id(rec), 9999), Y)
            t = infer_team(rec, Y)
            rws = rows_of(rec, Y)
            if not rws:
                continue
            tgt = sum(w.get("tgt") or 0 for w in rws)
            car = sum(w.get("ra") or 0 for w in rws)
            rpts = sum((w.get("rec") or 0) * 0.5 + (w.get("rcy") or 0) * 0.1 + (w.get("rctd") or 0) * 6 for w in rws)
            cpts = sum((w.get("ry") or 0) * 0.1 + (w.get("rtd") or 0) * 6 for w in rws)
            fpts = [w["fpts"] for w in rws if isinstance(w.get("fpts"), (int, float))]
            P[(id(rec), Y)] = {"team": t, "tgt": tgt, "car": car, "rpts": rpts, "cpts": cpts,
                               "g": len(rws), "ppg": (sum(fpts) / len(fpts)) if fpts else None,
                               "pos": rec["pos"], "norm": nk}
            if t:
                team_pool[(t, Y)][0] += tgt
                team_pool[(t, Y)][1] += car
    for (t, Y), _ in team_pool.items():
        team_games[(t, Y)] = len(SCHEDULES.get(Y, {}).get(t, {})) or (16 if Y <= 2020 else 17)

    # league means per season (per game)
    lg_vol = {}
    for Y in range(2016, 2026):
        ts = [(v[0] / team_games[(t, Y)], v[1] / team_games[(t, Y)])
              for (t, yy), v in team_pool.items() if yy == Y and team_games.get((t, Y))]
        if ts:
            lg_vol[Y] = (float(np.mean([a for a, _ in ts])), float(np.mean([b for _, b in ts])))

    # position-mean efficiencies per season (pooled Y-3..Y-1 handled at use)
    eff_lg = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])  # (pos, Y) -> [rpts, tgt, cpts, car]
    for (rid, Y), d in P.items():
        e = eff_lg[(d["pos"], Y)]
        e[0] += d["rpts"]; e[1] += d["tgt"]; e[2] += d["cpts"]; e[3] += d["car"]

    def lg_eff(pos, Y):
        r = [0.0, 0.0, 0.0, 0.0]
        for yy in (Y - 1, Y - 2, Y - 3):
            e = eff_lg.get((pos, yy))
            if e:
                for i in range(4):
                    r[i] += e[i]
        return (r[0] / max(1, r[1]), r[2] / max(1, r[3]))

    # ---- evaluate ----
    errs = defaultdict(lambda: defaultdict(list))
    for Y in range(2019, 2026):
        lgm = lg_vol.get(Y - 1)
        for nk, rec in recs:
            pos = rec.get("pos")
            if pos not in POS:
                continue
            cur = P.get((id(rec), Y))
            if not cur or cur["ppg"] is None or cur["g"] < 6 or not cur["team"]:
                continue
            # 3yr weighted share + efficiency + core
            sh_t = sh_c = shw = 0.0
            ept = [0.0, 0.0]; epc = [0.0, 0.0]
            core_n = core_d = 0.0
            for i, yy in enumerate((Y - 1, Y - 2, Y - 3)):
                d = P.get((id(rec), yy))
                if not d or d["g"] < 4:
                    continue
                if d["team"] and team_pool.get((d["team"], yy)):
                    tp = team_pool[(d["team"], yy)]
                    if tp[0] > 200:
                        sh_t += W3[i] * (d["tgt"] / tp[0])
                        sh_c += W3[i] * (d["car"] / max(1, tp[1]))
                        shw += W3[i]
                ept[0] += d["rpts"]; ept[1] += d["tgt"]
                epc[0] += d["cpts"]; epc[1] += d["car"]
                if d["ppg"] is not None:
                    core_n += W3[i] * d["ppg"]; core_d += W3[i]
            if shw == 0 or core_d == 0:
                continue
            core = core_n / core_d
            if core < 3:
                continue
            sh_t /= shw; sh_c /= shw
            # team volume prediction
            tm = cur["team"]
            prev_t = None
            pv = team_pool.get((tm, Y - 1))
            if pv and team_games.get((tm, Y - 1)) and lgm:
                gpv = team_games[(tm, Y - 1)]
                k = K_NEW if tm in CHANGES.get(Y, set()) else K_SAME
                prev_t = (lgm[0] + k * (pv[0] / gpv - lgm[0]),
                          lgm[1] + k * (pv[1] / gpv - lgm[1]))
            if not prev_t:
                prev_t = lgm or (33.0, 26.0)
            # mover tier
            moved = False
            pd_ = P.get((id(rec), Y - 1))
            if pd_ and pd_["team"] and pd_["team"] != tm:
                moved = True
                ds = deals.get((nk, Y)) or deals.get((nk, Y - 1))
                cap = max(ds) if ds else None
                tier = "unknown" if cap is None else ("big" if cap >= 0.04 else ("mid" if cap >= 0.015 else "cheap"))
                sh_mult = MOVER_TIER[tier]
            else:
                sh_mult = 1.0
            exp = Y - first_seen.get(id(rec), Y)
            if exp <= 2:
                sh_mult *= EXP_BUMP
            lg_pt, lg_pc = lg_eff(pos, Y)
            for es in EFF_SHRINKS:
                p_t = lg_pt + es * ((ept[0] / max(1, ept[1])) - lg_pt) if ept[1] >= 30 else lg_pt
                p_c = lg_pc + es * ((epc[0] / max(1, epc[1])) - lg_pc) if epc[1] >= 30 else lg_pc
                vs = sh_t * sh_mult * prev_t[0] * p_t + sh_c * sh_mult * prev_t[1] * p_c
                errs[pos][f"vs{es}"].append(abs(vs - cur["ppg"]))
                for b in BLENDS:
                    errs[pos][f"bl{b}_{es}"].append(abs(b * vs + (1 - b) * core - cur["ppg"]))
            errs[pos]["core"].append(abs(core - cur["ppg"]))
        print(f"  {Y} done")

    print("\n=== MAE: volume x share model vs 3yr recency core (2019-25) ===")
    for pos in POS:
        print(f"  {pos} (n={len(errs[pos]['core'])}): core {np.mean(errs[pos]['core']):.3f}")
        for es in EFF_SHRINKS:
            line = f"    shrink {es}: pure {np.mean(errs[pos][f'vs{es}']):.3f}"
            for b in BLENDS:
                line += f"  blend{int(b*100)} {np.mean(errs[pos][f'bl{b}_{es}']):.3f}"
            print(line)

if __name__ == "__main__":
    main()
