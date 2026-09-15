#!/usr/bin/env python3
"""
Build the 2026 OPPORTUNITY PRIOR for the Clay-free SHADOW base -> data/opp_prior_2026.js (window.SIM_OPP_PRIOR_2026).

Backend only (Clay stays the live base). backtest_opp_prior.py graded it 2019-25: for veterans the opportunity prior
beats the history prior (calibrated MSE 8.46 vs 9.06) and HIST + OPP is better still (8.32); calibrated Clay is still
best (7.08), and for rookies the opportunity prior is worse than Clay (9.28 vs 7.50), so rookies are NOT included -
the shadow keeps its Clay fallback for them.

Per RB / WR / TE with >= 6 games in 2025, from 2025 pbp (targets, carries, site xFP, half-PPR points):
  2026 team         Sleeper export (sim_lab data/sleeper_players.js sTm); players missing from it are treated as gone
  shares            vet model from the backtest's all-season fit: [1, 2025 share, allocated vacated share, mover x share, age-27]
  vacated           2025 shares of each team's RB/WR/TE whose 2026 team differs (or who are gone)
  volume            .5 x the team's 2025 targets / carries per game + .5 x the 2025 league mean
  value             his 2025 xFP per target / carry shrunk to the position mean (K 60); efficiency shrunk n/(n+150), lambda
  half              projected half-PPR points per game
cal[pos] = [a, b, c]: shadow prior (half-PPR) = a + b x history prior + c x half (backtest full fit, HISTREG input).
Run: python build_opp_prior.py   (after backtest_opp_prior.py has written data/opp_prior_backtest.js)
"""
import json, os, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from opp_prior_core import load_positions, load_season, tm, SKILL, K_VAL, K_EFF

OUT = os.path.join(HERE, "data", "opp_prior_2026.js")
SEASON_PREV = 2025


def norm(n):
    import re
    n = str(n).lower().replace(".", "").replace("'", "").replace("-", " ")
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return re.sub(r"\s+", " ", n).strip()


def main():
    raw = open(os.path.join(HERE, "data", "opp_prior_backtest.js"), encoding="utf-8").read()
    R = json.loads(raw[raw.index("{"):raw.rindex(";")])
    coef, cal = R["coef"], R.get("calAll")
    if not cal:
        print("opp_prior_backtest.js has no calAll - rerun backtest_opp_prior.py first"); return 1
    lam = float(R.get("lambdaAll", 1.0))
    pos_of, name_of, bd_of = load_positions()
    pl, teams = load_season(SEASON_PREV, pos_of)
    s = open(os.path.join(HERE, "data", "sleeper_players.js"), encoding="utf-8").read()
    sl = json.loads(s[s.index("{"):s.rindex("}") + 1])["players"]
    team26 = {}
    age26 = {}
    for p in sl:
        if p.get("s") in SKILL and p.get("sTm"):
            team26[(norm(p["n"]), p["s"])] = tm(p["sTm"])
            if isinstance(p.get("age"), (int, float)):
                age26[(norm(p["n"]), p["s"])] = float(p["age"])
    t26 = {}
    for pid, q in pl.items():
        nm = name_of.get(pid)
        t26[pid] = team26.get((norm(nm), q["pos"])) if nm else None
    vac = defaultdict(lambda: {"tg": 0.0, "car": 0.0}); ret = defaultdict(lambda: {"tg": 0.0, "car": 0.0})
    for pid, q in pl.items():
        if t26[pid] != q["tm"]:
            vac[q["tm"]]["tg"] += q["ts"]; vac[q["tm"]]["car"] += q["cs"]
        if t26[pid]:
            ret[t26[pid]]["tg"] += q["ts"]; ret[t26[pid]]["car"] += q["cs"]
    lg_tg = float(np.mean([t["tg_pg"] for t in teams.values()])); lg_car = float(np.mean([t["car_pg"] for t in teams.values()]))
    out = {}
    for pid, q in pl.items():
        t = t26[pid]; p = q["pos"]
        if q["g"] < 6 or not t or t not in teams:
            continue
        c = coef.get(p) or {}
        cts, ccs = c.get("vet_ts"), c.get("vet_cs")
        if not cts or not ccs:
            continue
        nm = name_of.get(pid)
        age = age26.get((norm(nm), p))
        if age is None:
            b = bd_of.get(pid)
            age = ((pd.Timestamp(2026, 9, 1) - b).days / 365.25) if b is not None and not pd.isna(b) else 27.0
        mover = 1.0 if t != q["tm"] else 0.0
        alloc_tg = vac[t]["tg"] * q["ts"] / ret[t]["tg"] if ret[t]["tg"] else 0.0
        alloc_car = vac[t]["car"] * q["cs"] / ret[t]["car"] if ret[t]["car"] else 0.0
        ts = max(0.0, cts[0] + cts[1] * q["ts"] + cts[2] * alloc_tg + cts[3] * mover * q["ts"] + cts[4] * (age - 27.0))
        cs = max(0.0, ccs[0] + ccs[1] * q["cs"] + ccs[2] * alloc_car + ccs[3] * mover * q["cs"] + ccs[4] * (age - 27.0))
        tg_pg = 0.5 * teams[t]["tg_pg"] + 0.5 * lg_tg; car_pg = 0.5 * teams[t]["car_pg"] + 0.5 * lg_car
        vt = (q["xr"] + K_VAL * c["v_tg"]) / (q["tg"] + K_VAL); vc = (q["xc"] + K_VAL * c["v_car"]) / (q["car"] + K_VAL)
        x_prev = q["xr"] + q["xc"]; n = q["tg"] + q["car"]
        eff = ((q["act"] - x_prev) / x_prev) * n / (n + K_EFF) if x_prev > 0 else 0.0
        half = (ts * tg_pg * vt + cs * car_pg * vc) * (1 + lam * eff)
        out[norm(nm)] = {"half": round(half, 2), "ts": round(ts, 3), "cs": round(cs, 3), "tm": t, "tm25": q["tm"], "mover": int(mover),
                         "ppg25": round(q["act"] / q["g"], 2), "g25": q["g"], "pos": p}
    payload = {"updated": time.strftime("%Y-%m-%d %H:%M"), "season": 2026, "from": SEASON_PREV, "lambda": lam, "cal": cal,
               "note": "Clay-free shadow only; veterans (>= 6 games in 2025). Rookies stay on the Clay fallback (opportunity prior graded worse than Clay for rookies).",
               "players": out}
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// built by build_opp_prior.py - 2026 opportunity prior (projected shares x team volume x value per opportunity) for the Clay-free shadow base only\n")
        f.write("window.SIM_OPP_PRIOR_2026 = "); json.dump(payload, f, separators=(",", ":")); f.write(";\n")
    movers = sum(1 for v in out.values() if v["mover"])
    print(f"wrote {OUT}: {len(out)} veterans ({movers} changed teams), cal {cal}")
    top = sorted(out.items(), key=lambda kv: -kv[1]["half"])[:8]
    print("top opportunity priors: " + "; ".join(f"{k} {v['pos']} {v['tm']} {v['half']} (2025 {v['ppg25']})" for k, v in top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
