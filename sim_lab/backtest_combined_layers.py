#!/usr/bin/env python3
"""
Did the layers shipped 2026-07-30/31 actually improve the model TOGETHER?

Each was validated individually against the same 3-yr recency core, which
means they could be double-counting each other. This stacks them exactly as
engine.js applies them and re-grades on one pool (2019-2025):

  core         3-yr recency-weighted PPG (the JS model's heart, baseline)
  +VS          blend 30% volume x share / 70% core   (RB/WR/TE)
  +MOVER       contract-tiered team-change discount  (non-QB)
  +TEROUTE     TE route-participation mean reversion (TE, PFF)
  ALL          everything stacked, in engine order

Reports per-position MAE, the delta vs core, and a win rate (share of
player-seasons where the stacked model lands closer than the core).
Rookies excluded (no 3-yr history — the room layer is graded separately in
backtest_rookie_share.py).
"""
import numpy as np
import pandas as pd
import os
from collections import defaultdict
from backtest_sim_calibration import (played, WEEKLY, infer_team, POS_KEEP,
                                      SCHEDULES, CHANGES)
import backtest_sim_calibration as cal

CACHE = r"E:\MyFantasyFootball\pbp_cache"
PFF = os.path.join(CACHE, "pff")
W3 = [0.5, 0.3, 0.2]
VS_POS = ("RB", "WR", "TE")
K_SAME, K_NEW = 0.60, 0.35
EXP_BUMP = 1.10
MOVER_TIER = {"big": 1.0, "mid": 0.95, "cheap": 0.86, "unknown": 0.94}
EFF_SHRINK = {"RB": 1.0, "WR": 0.5, "TE": 0.5}
VS_W = 0.30
SHRINK_K = {"QB": 0.60, "RB": 0.90, "WR": 0.90, "TE": 0.90}
TE_SLOPE, TE_MEAN, TE_CLAMP = -0.00657, 85.56, 0.10

def rows_of(rec, Y):
    return [w for w in rec.get("seasons", {}).get(str(Y), []) if played(w)]

def main():
    con = pd.read_parquet(os.path.join(CACHE, "historical_contracts.parquet"),
                          columns=["player", "year_signed", "apy_cap_pct", "date_of_birth"])
    con["norm"] = con.player.map(cal.norm)
    deals = defaultdict(list)
    for _, r in con.dropna(subset=["apy_cap_pct"]).iterrows():
        deals[(r["norm"], int(r.year_signed))].append(float(r.apy_cap_pct))
    born = {}
    for _, r in con.dropna(subset=["date_of_birth"]).iterrows():
        import re
        m = re.search(r"(\d{4})", str(r.date_of_birth))
        if m:
            born[r["norm"]] = int(m.group(1))

    te_route = {}
    for y in range(2018, 2026):
        p = os.path.join(PFF, f"pff_receiving_{y}.csv")
        if not os.path.exists(p):
            continue
        df = pd.read_csv(p)
        for _, r in df[df.position == "TE"].iterrows():
            if (r.get("routes") or 0) >= 100 and pd.notna(r.get("route_rate")):
                te_route[(cal.norm(r.player), y)] = float(r.route_rate)

    recs = []
    for nk, lst in WEEKLY.items():
        for rec in lst:
            if rec.get("pos") in POS_KEEP:
                recs.append((nk, rec))

    P, team_pool, first_seen = {}, defaultdict(lambda: [0.0, 0.0]), {}
    for nk, rec in recs:
        for Ys in rec.get("seasons", {}):
            Y = int(Ys)
            if Y < 2015:
                continue
            first_seen[id(rec)] = min(first_seen.get(id(rec), 9999), Y)
            rws = rows_of(rec, Y)
            if not rws:
                continue
            t = infer_team(rec, Y)
            fpts = [w["fpts"] for w in rws if isinstance(w.get("fpts"), (int, float))]
            d = {"team": t, "tgt": sum(w.get("tgt") or 0 for w in rws),
                 "car": sum(w.get("ra") or 0 for w in rws),
                 "rpts": sum((w.get("rec") or 0) * .5 + (w.get("rcy") or 0) * .1 + (w.get("rctd") or 0) * 6 for w in rws),
                 "cpts": sum((w.get("ry") or 0) * .1 + (w.get("rtd") or 0) * 6 for w in rws),
                 "g": len(rws), "ppg": (sum(fpts) / len(fpts)) if fpts else None}
            P[(id(rec), Y)] = d
            if t:
                team_pool[(t, Y)][0] += d["tgt"]; team_pool[(t, Y)][1] += d["car"]

    def games(t, Y):
        return len(SCHEDULES.get(Y, {}).get(t, {})) or (16 if Y <= 2020 else 17)

    lg_vol = {}
    for Y in range(2016, 2026):
        ts = [(v[0] / games(t, Y), v[1] / games(t, Y)) for (t, yy), v in team_pool.items() if yy == Y]
        if ts:
            lg_vol[Y] = (float(np.mean([a for a, _ in ts])), float(np.mean([b for _, b in ts])))
    eff_lg = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    pos_of = {id(rec): rec.get("pos") for nk, rec in recs}
    for (rid, Y), d in P.items():
        e = eff_lg[(pos_of[rid], Y)]
        e[0] += d["rpts"]; e[1] += d["tgt"]; e[2] += d["cpts"]; e[3] += d["car"]

    def lg_eff(pos, Y):
        r = [0.0] * 4
        for yy in (Y - 1, Y - 2, Y - 3):
            e = eff_lg.get((pos, yy))
            if e:
                for i in range(4):
                    r[i] += e[i]
        return (r[0] / max(1, r[1]), r[2] / max(1, r[3]))

    res = defaultdict(lambda: defaultdict(list))
    for Y in range(2019, 2026):
        lgm = lg_vol.get(Y - 1)
        for nk, rec in recs:
            pos = rec["pos"]
            cur = P.get((id(rec), Y))
            if not cur or cur["ppg"] is None or cur["g"] < 6:
                continue
            sh_t = sh_c = shw = core_n = core_d = 0.0
            ept, epc = [0.0, 0.0], [0.0, 0.0]
            for i, yy in enumerate((Y - 1, Y - 2, Y - 3)):
                d = P.get((id(rec), yy))
                if not d or d["g"] < 4:
                    continue
                if d["team"] and team_pool.get((d["team"], yy)) and team_pool[(d["team"], yy)][0] > 200:
                    tp = team_pool[(d["team"], yy)]
                    sh_t += W3[i] * (d["tgt"] / tp[0]); sh_c += W3[i] * (d["car"] / max(1, tp[1])); shw += W3[i]
                ept[0] += d["rpts"]; ept[1] += d["tgt"]; epc[0] += d["cpts"]; epc[1] += d["car"]
                if d["ppg"] is not None:
                    core_n += W3[i] * d["ppg"]; core_d += W3[i]
            if core_d == 0:
                continue
            core = core_n / core_d
            if core < 3:
                continue
            act = cur["ppg"]

            # --- layer 1: volume x share blend (RB/WR/TE) ---
            vs_out = core
            if pos in VS_POS and shw > 0 and cur["team"]:
                s_t, s_c = sh_t / shw, sh_c / shw
                pv = team_pool.get((cur["team"], Y - 1))
                if pv and lgm:
                    gpv = games(cur["team"], Y - 1)
                    k = K_NEW if cur["team"] in CHANGES.get(Y, set()) else K_SAME
                    tv = (lgm[0] + k * (pv[0] / gpv - lgm[0]), lgm[1] + k * (pv[1] / gpv - lgm[1]))
                else:
                    tv = lgm or (33.0, 26.0)
                mult = 1.0
                pd_ = P.get((id(rec), Y - 1))
                if pd_ and pd_["team"] and pd_["team"] != cur["team"]:
                    ds = deals.get((nk, Y)) or deals.get((nk, Y - 1))
                    cap = max(ds) if ds else None
                    mult = MOVER_TIER["unknown" if cap is None else
                                      ("big" if cap >= .04 else "mid" if cap >= .015 else "cheap")]
                if Y - first_seen.get(id(rec), Y) <= 2:
                    mult *= EXP_BUMP
                es = EFF_SHRINK[pos]
                lpt, lpc = lg_eff(pos, Y)
                p_t = lpt + es * ((ept[0] / max(1, ept[1])) - lpt) if ept[1] >= 30 else lpt
                p_c = lpc + es * ((epc[0] / max(1, epc[1])) - lpc) if epc[1] >= 30 else lpc
                vs = s_t * mult * tv[0] * p_t + s_c * mult * tv[1] * p_c
                if vs > 0.5:
                    vs_out = VS_W * vs + (1 - VS_W) * core

            # --- layer 2: mover discount (non-QB) ---
            def mover_mult():
                pd_ = P.get((id(rec), Y - 1))
                if pos == "QB" or not pd_ or not pd_["team"] or not cur["team"] or pd_["team"] == cur["team"]:
                    return 1.0
                ds = deals.get((nk, Y)) or deals.get((nk, Y - 1))
                cap = max(ds) if ds else None
                m = MOVER_TIER["unknown" if cap is None else
                               ("big" if cap >= .04 else "mid" if cap >= .015 else "cheap")]
                age = (Y - born[nk]) if nk in born else None
                if age is not None and age >= 29:
                    m *= 0.92
                return max(0.80, m)
            mv = mover_mult()

            # --- layer 3: TE route mean reversion ---
            def te_mult():
                if pos != "TE":
                    return 1.0
                rr = te_route.get((nk, Y - 1))
                if rr is None:
                    return 1.0
                return float(np.exp(np.clip(TE_SLOPE * (rr - TE_MEAN), -TE_CLAMP, TE_CLAMP)))
            tm = te_mult()

            res[pos]["_core_vals"].append(core)
            res[pos]["_Y"].append(Y)
            res[pos]["_act"].append(act)
            res[pos]["_allm"].append(vs_out * mv * tm)
            res[pos]["core"].append(abs(core - act))
            res[pos]["vs"].append(abs(vs_out - act))
            res[pos]["mover"].append(abs(core * mv - act))
            res[pos]["teroute"].append(abs(core * tm - act))
            allm = vs_out * mv * tm
            res[pos]["all"].append(abs(allm - act))
            res[pos]["_win"].append(1.0 if abs(allm - act) < abs(core - act) else 0.0)
        print(f"  {Y} done")

    # shrinkage layers, LOYO by season (positional mean fit on other years)
    for pos in ("QB", "RB", "WR", "TE"):
        r = res[pos]
        if not r["_core_vals"]:
            continue
        cv = np.array(r["_core_vals"]); ys = np.array(r["_Y"])
        av = np.array(r["_act"]); am = np.array(r["_allm"])
        k = SHRINK_K[pos]
        for Yv in sorted(set(ys.tolist())):
            te = ys == Yv
            if te.sum() == 0 or (~te).sum() < 40:
                continue
            m = cv[~te].mean()
            shr = m + k * (cv[te] - m)
            r["shrink"].extend(np.abs(shr - av[te]).tolist())
            r["all_shrink"].extend(np.abs(am[te] * (shr / cv[te]) - av[te]).tolist())


    print("\n=== Stacked layer test, 2019-25 (MAE vs 3-yr recency core) ===")
    print(f"{'pos':<5}{'n':>6}{'core':>9}{'+VS':>9}{'+mover':>9}{'+TEroute':>10}{'ALL':>9}{'ALL delta':>11}{'win rate':>10}{'shrinkOnly':>10}{'ALL+shrink':>12}{'delta':>9}")
    tot = defaultdict(list)
    for pos in ("QB", "RB", "WR", "TE"):
        r = res[pos]
        if not r["core"]:
            continue
        c = np.mean(r["core"]); a = np.mean(r["all"])
        for k in ("core", "all", "_win"):
            tot[k].extend(r[k])
        sh = np.mean(r['shrink']) if r['shrink'] else float('nan')
        asr = np.mean(r['all_shrink']) if r['all_shrink'] else float('nan')
        print(f"{pos:<5}{len(r['core']):>6}{c:>9.3f}{np.mean(r['vs']):>9.3f}{np.mean(r['mover']):>9.3f}"
              f"{np.mean(r['teroute']):>10.3f}{a:>9.3f}{(a-c)/c*100:>+10.2f}%{np.mean(r['_win'])*100:>9.1f}%"
              f"{sh:>10.3f}{asr:>12.3f}{(asr-c)/c*100:>+9.2f}%")
        tot['all_shrink'].extend(r['all_shrink'])
    c, a = np.mean(tot["core"]), np.mean(tot["all"])
    asr = np.mean(tot['all_shrink'])
    print(f"{'ALL':<5}{len(tot['core']):>6}{c:>9.3f}{'':>9}{'':>9}{'':>10}{a:>9.3f}{(a-c)/c*100:>+10.2f}%{np.mean(tot['_win'])*100:>9.1f}%{'':>10}{asr:>12.3f}{(asr-c)/c*100:>+9.2f}%")

if __name__ == "__main__":
    main()
