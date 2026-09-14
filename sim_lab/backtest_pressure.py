#!/usr/bin/env python3
"""
OPPONENT PRESSURE-RATE layer backtest, 2018-2025.

Defense pressure rate = pressured dropbacks / dropbacks (participation
was_pressure joined to pbp qb_dropback plays).

GATE A: is defense pressure rate a stable identity (early->late in-season,
        YoY)?
GATE B: does QB pressure-RESISTANCE persist (qb_epa pressured vs clean,
        YoY)? Decides whether a per-QB interaction is allowed or defense-
        side only (the man/zone lesson).
LAYER:  QB weekly residual vs P=5 base x QB-FPA layer, predictor = opp
        pressure rate to date minus league avg. MSE sweep. WR secondary.
"""
import numpy as np
import pandas as pd
import json, os
from collections import defaultdict
from backtest_sim_calibration import (played, weekly_rec, POOL_MIN_PTS, OPP_ALIAS)
import backtest_sim_calibration as cal

CACHE = r"E:\MyFantasyFootball\pbp_cache"
P = 5
YEARS = range(2018, 2026)
TEAM_FIX = {"WSH": "WAS", "LA": "LAR", "OAK": "LV", "SD": "LAC",
            "JAC": "JAX", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}

def build_pressure(year):
    """returns dweek[(def,wk)]=[pressured,dropbacks], qbsplit[qbid]=[epaP,nP,epaC,nC]"""
    pbp = pd.read_csv(os.path.join(CACHE, f"play_by_play_{year}.csv.gz"),
                      usecols=["game_id", "play_id", "week", "season_type", "defteam",
                               "qb_dropback", "passer_player_id", "qb_epa"],
                      low_memory=False)
    pbp = pbp[(pbp.season_type == "REG") & (pbp.qb_dropback == 1)]
    part = pd.read_parquet(os.path.join(CACHE, f"pbp_participation_{year}.parquet"),
                           columns=["nflverse_game_id", "play_id", "was_pressure"])
    part = part[part.was_pressure.notna()]
    m = part.merge(pbp, left_on=["nflverse_game_id", "play_id"],
                   right_on=["game_id", "play_id"], how="inner")
    dweek = defaultdict(lambda: [0, 0])
    qbs = defaultdict(lambda: [0.0, 0, 0.0, 0])
    for r in m.itertuples(index=False):
        d = TEAM_FIX.get(r.defteam, r.defteam)
        pr = bool(r.was_pressure)
        dweek[(d, int(r.week))][1] += 1
        if pr:
            dweek[(d, int(r.week))][0] += 1
        if isinstance(r.passer_player_id, str) and isinstance(r.qb_epa, float) and not np.isnan(r.qb_epa):
            q = qbs[r.passer_player_id]
            if pr:
                q[0] += r.qb_epa; q[1] += 1
            else:
                q[2] += r.qb_epa; q[3] += 1
    return dweek, qbs

def main():
    DW = {}    # Y -> dweek
    QS = {}    # Y -> qb splits
    for Y in YEARS:
        DW[Y], QS[Y] = build_pressure(Y)
        n = sum(v[1] for v in DW[Y].values())
        pr = sum(v[0] for v in DW[Y].values())
        print(f"  {Y}: {n} dropbacks, lg pressure rate {pr/n:.3f}")

    # GATE A: defense stability
    print("\n=== GATE A: defense pressure-rate stability ===")
    xs, ys = [], []
    for Y, dweek in DW.items():
        agg_e = defaultdict(lambda: [0, 0]); agg_l = defaultdict(lambda: [0, 0])
        for (d, wk), (p, n) in dweek.items():
            t = agg_e if wk <= 8 else agg_l
            t[d][0] += p; t[d][1] += n
        for d in agg_e:
            if d in agg_l and agg_e[d][1] >= 120 and agg_l[d][1] >= 120:
                xs.append(agg_e[d][0] / agg_e[d][1]); ys.append(agg_l[d][0] / agg_l[d][1])
    xs, ys = np.array(xs), np.array(ys)
    print(f"  in-season wk1-8 -> wk9+: {len(xs)} def-seasons, corr {np.corrcoef(xs,ys)[0,1]:+.3f}, "
          f"rate sd {xs.std():.3f} (mean {xs.mean():.3f})")
    xs2, ys2 = [], []
    seas = {}
    for Y, dweek in DW.items():
        a = defaultdict(lambda: [0, 0])
        for (d, wk), (p, n) in dweek.items():
            a[d][0] += p; a[d][1] += n
        seas[Y] = {d: v[0] / v[1] for d, v in a.items() if v[1] >= 250}
    for Y in YEARS:
        if Y + 1 in seas:
            for d, r in seas.get(Y, {}).items():
                if d in seas[Y + 1]:
                    xs2.append(r); ys2.append(seas[Y + 1][d])
    print(f"  YoY: {len(xs2)} pairs, corr {np.corrcoef(np.array(xs2), np.array(ys2))[0,1]:+.3f}")

    # GATE B: QB pressure-resistance persistence (epa gap clean-vs-pressured)
    print("\n=== GATE B: QB pressure-resistance persistence ===")
    gaps = {}
    for Y, qbs in QS.items():
        for qid, (ep, np_, ec, nc) in qbs.items():
            if np_ >= 60 and nc >= 120:
                gaps[(Y, qid)] = ep / np_ - ec / nc   # less negative = resistant
    xs3, ys3 = [], []
    for (Y, qid), g in gaps.items():
        if (Y + 1, qid) in gaps:
            xs3.append(g); ys3.append(gaps[(Y + 1, qid)])
    xs3, ys3 = np.array(xs3), np.array(ys3)
    print(f"  {len(gaps)} QB-seasons (>=60 pressured, >=120 clean dropbacks)")
    print(f"  {len(xs3)} consecutive pairs: corr = {np.corrcoef(xs3, ys3)[0,1]:+.3f}"
          f"   gap mean {np.array(list(gaps.values())).mean():+.3f} epa/dropback, sd {np.array(list(gaps.values())).std():.3f}")

    # LAYER: QB weekly, opp pressure rate to date vs league, on base and base*FPA
    print("\n=== LAYER TEST: QB (and WR) vs opp pressure-rate deviation ===")
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    # per-pos FPA (jsOppMult design) reused from cb harness style
    from backtest_cb_shadow import build_wr_fpa  # WR version; QB needs its own
    from research_cb_qb_te import build_fpa
    for pos in ("QB", "WR"):
        fpa = build_fpa(pos) if pos == "QB" else build_wr_fpa()
        S = []
        for Y in range(2019, 2026):
            if str(Y) not in clay_hist:
                continue
            dweek = DW[Y]
            lgp = sum(v[0] for v in dweek.values()) / sum(v[1] for v in dweek.values())
            for name, c in clay_hist[str(Y)].items():
                if c.get("pos") != pos or (c.get("pts") or 0) < POOL_MIN_PTS:
                    continue
                wrec = weekly_rec(name, pos)
                if wrec is None:
                    continue
                rows = sorted([(w["wk"], w["fpts"], OPP_ALIAS.get(w.get("opp"), w.get("opp")))
                               for w in wrec.get("seasons", {}).get(str(Y), [])
                               if played(w) and isinstance(w.get("fpts"), (int, float))])
                W = 16 if Y <= 2020 else 17
                clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
                hist = []
                for wk, fpts, opp in rows:
                    if hist and opp:
                        g = len(hist)
                        base = (P * clay_pg + g * (sum(hist) / g)) / (P + g)
                        pr = n = 0
                        for w in range(1, wk):
                            v = dweek.get((opp, w))
                            if v:
                                pr += v[0]; n += v[1]
                        if n >= 80:
                            S.append({"base": base, "bf": base * fpa(Y, opp, wk),
                                      "act": fpts, "dev": pr / n - lgp,
                                      "trust": min(1.0, n / 250.0)})
                    hist.append(fpts)
        base = np.array([s["base"] for s in S]); bf = np.array([s["bf"] for s in S])
        act = np.array([s["act"] for s in S])
        dev = np.array([s["dev"] for s in S]); tr = np.array([s["trust"] for s in S])
        print(f"\n  {pos}: {len(S)} player-weeks, dev sd {dev.std():.3f}")
        for tag, arr in (("raw base ", base), ("base*FPA ", bf)):
            line = f"    {tag}"
            best = None
            for e in (0.0, 0.25, 0.5, 1.0, 1.5):
                mult = np.clip(1 - e * tr * dev, 0.85, 1.15)
                v = float(np.mean((arr * mult - act) ** 2))
                line += f"  e{e:.2f} {v:.3f}"
                if best is None or v < best[1]:
                    best = (e, v)
            print(line + f"  <- best e={best[0]}")
        for lo, hi in [(-1, -0.05), (-0.05, -0.02), (-0.02, 0.02), (0.02, 0.05), (0.05, 1)]:
            m = (dev >= lo) & (dev < hi)
            if m.sum() < 150:
                continue
            print(f"    dev {dev[m].mean():+.3f}: act/(base*FPA) {act[m].sum()/bf[m].sum():.3f} (n={m.sum()})")

if __name__ == "__main__":
    main()
