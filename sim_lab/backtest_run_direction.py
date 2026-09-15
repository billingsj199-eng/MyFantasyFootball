#!/usr/bin/env python3
"""
RUN DIRECTION MATCHUP backtest, 2019-2025 (Jack 2026-09-15: "where each
defense gets targeted or what type of runs outside/inside").

nflverse pbp carries run_location (left/middle/right) and run_gap (end/
tackle/guard) on ~95% of designed runs, NIGHTLY. Zones:
  side  : left / middle / right
  lane  : edge (gap = end) / interior (guard, tackle, or middle with no gap)
Per DEFENSE season-to-date (weeks < W, shrunk K=60 carries):
  r_z  yards per carry allowed in zone z / league yards per carry in z
  f_z  share of carries faced in zone z / league share  (funnel)
Per RB (season-to-date, shrunk toward prior season, K=40 carries): w_z = share
of his carries in zone z. Matchup M = sum w_z r_z / r_all (isolates the
direction interaction from the overall run defense, which FPA already prices).
Gates: defense direction residual persistence (early->late, YoY); RB mix
persistence YoY. Then terciles + LOYO on RB rows: shipped x (1 + e x (M - 1)).
Also the same with success rate (yards >= needed proxy: gain >= 4) instead of
yards, since long runs are noisy. Log: run_direction_backtest.log
"""
import numpy as np
import pandas as pd
import os
from collections import defaultdict
from bt_common import iter_samples, to_arrays, loyo, mse, YEARS, LOAD_YEARS, CACHE, tm, P

SIDES = ["left", "middle", "right"]; LANES = ["edge", "interior"]
K_DEF, K_PLR = 60.0, 40.0

def load_runs(Y):
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"),
                     usecols=["season_type", "week", "posteam", "defteam", "rush_attempt", "qb_dropback", "rusher_player_id",
                              "run_location", "run_gap", "yards_gained"], low_memory=False)
    r = df[(df.season_type == "REG") & (df.rush_attempt == 1) & (df.qb_dropback != 1) & df.rusher_player_id.notna()
           & df.run_location.isin(SIDES) & df.defteam.notna()].copy()
    r["side"] = r.run_location
    r["lane"] = np.where(r.run_gap == "end", "edge", "interior")
    r["yds"] = r.yards_gained.fillna(0).clip(-10, 40)     # cap the 80-yarders: matchup is about the typical carry
    r["succ"] = (r.yards_gained.fillna(0) >= 4).astype(float)
    r["def"] = r.defteam.map(tm); r["season"] = Y; r["pid"] = r.rusher_player_id
    return r[["season", "week", "def", "pid", "side", "lane", "yds", "succ"]]

def cum_by_week(df, keys, zcol, zones):
    agg = df.groupby(keys + ["week", zcol]).agg(n=("yds", "count"), y=("yds", "sum"), s=("succ", "sum")).reset_index()
    out = {}
    for key, grp in agg.groupby(keys):
        key = key if isinstance(key, tuple) else (key,)
        cum = {"n": defaultdict(float), "y": defaultdict(float), "s": defaultdict(float), "N": 0.0, "Y": 0.0, "S": 0.0}; lst = []
        for wk, g2 in grp.groupby("week"):
            for r in g2.itertuples(index=False):
                z = getattr(r, zcol); cum["n"][z] += r.n; cum["y"][z] += r.y; cum["s"][z] += r.s; cum["N"] += r.n; cum["Y"] += r.y; cum["S"] += r.s
            lst.append((int(wk), {"n": dict(cum["n"]), "y": dict(cum["y"]), "s": dict(cum["s"]), "N": cum["N"], "Y": cum["Y"], "S": cum["S"]}))
        out[key] = lst
    return out

def before(lst, wk):
    best = None
    for w, c in lst or []:
        if w < wk: best = c
        else: break
    return best

def main():
    frames = {Y: load_runs(Y) for Y in LOAD_YEARS}
    allr = pd.concat(frames.values(), ignore_index=True)
    print(f"  designed RB-group runs with direction: {len(allr)} ({len(allr)/8:.0f}/season)")
    lg = {}
    for (Y, zc), g in allr.groupby(["season", "side"]): lg[(Y, "side", zc)] = (g.yds.mean(), g.succ.mean(), len(g))
    for (Y, zc), g in allr.groupby(["season", "lane"]): lg[(Y, "lane", zc)] = (g.yds.mean(), g.succ.mean(), len(g))
    tot = {Y: (g.yds.mean(), g.succ.mean(), len(g)) for Y, g in allr.groupby("season")}
    print("  league 2025 yds/carry: " + "  ".join(f"{z} {lg[(2025,'side',z)][0]:.2f} ({lg[(2025,'side',z)][2]/tot[2025][2]*100:.0f}%)" for z in SIDES) + " | " +
          "  ".join(f"{z} {lg[(2025,'lane',z)][0]:.2f} ({lg[(2025,'lane',z)][2]/tot[2025][2]*100:.0f}%)" for z in LANES))
    D = {"side": cum_by_week(allr, ["season", "def"], "side", SIDES), "lane": cum_by_week(allr, ["season", "def"], "lane", LANES)}
    Pm = {"side": cum_by_week(allr, ["season", "pid"], "side", SIDES), "lane": cum_by_week(allr, ["season", "pid"], "lane", LANES)}

    print("\n=== GATE 1. defense direction RESIDUAL persistence (zone yds/carry ratio / overall ratio) ===")
    for zc, zones in (("side", SIDES), ("lane", LANES)):
        for z in zones:
            e, l, y0, y1 = [], [], [], []
            for (Y, d), lst in D[zc].items():
                if Y < 2019: continue
                c8 = before(lst, 9); cE = lst[-1][1]
                if not c8: continue
                n8 = c8["n"].get(z, 0); nl = cE["n"].get(z, 0) - n8
                if n8 < 25 or nl < 25: continue
                lgz = lg[(Y, zc, z)][0]; lga = tot[Y][0]
                e.append((c8["y"].get(z, 0) / n8 / lgz) / (c8["Y"] / c8["N"] / lga))
                l.append(((cE["y"].get(z, 0) - c8["y"].get(z, 0)) / nl / lgz) / ((cE["Y"] - c8["Y"]) / (cE["N"] - c8["N"]) / lga))
                nx = D[zc].get((Y + 1, d))
                if nx and nx[-1][1]["n"].get(z, 0) >= 25:
                    cN = nx[-1][1]
                    y0.append((cE["y"].get(z, 0) / cE["n"].get(z, 1) / lgz) / (cE["Y"] / cE["N"] / lga))
                    y1.append((cN["y"].get(z, 0) / cN["n"].get(z, 1) / lg[(Y + 1, zc, z)][0]) / (cN["Y"] / cN["N"] / tot[Y + 1][0]))
            print(f"  {zc} {z:9s} early->late r={np.corrcoef(e,l)[0,1]:+.2f} (n={len(e)}, sd {np.std(e):.3f})   YoY r={np.corrcoef(y0,y1)[0,1]:+.2f}")
    print("  overall run defense (yds/carry vs league) persistence:")
    e, l, y0, y1 = [], [], [], []
    for (Y, d), lst in D["side"].items():
        if Y < 2019: continue
        c8 = before(lst, 9); cE = lst[-1][1]
        if not c8 or c8["N"] < 80 or cE["N"] - c8["N"] < 80: continue
        e.append(c8["Y"] / c8["N"] / tot[Y][0]); l.append((cE["Y"] - c8["Y"]) / (cE["N"] - c8["N"]) / tot[Y][0])
        nx = D["side"].get((Y + 1, d))
        if nx: y0.append(cE["Y"] / cE["N"] / tot[Y][0]); y1.append(nx[-1][1]["Y"] / nx[-1][1]["N"] / tot[Y + 1][0])
    print(f"    early->late r={np.corrcoef(e,l)[0,1]:+.2f}   YoY r={np.corrcoef(y0,y1)[0,1]:+.2f}")
    print("  defense FUNNEL persistence (share of carries faced per zone):")
    for zc, zones in (("side", SIDES), ("lane", LANES)):
        for z in zones:
            e, l = [], []
            for (Y, d), lst in D[zc].items():
                if Y < 2019: continue
                c8 = before(lst, 9); cE = lst[-1][1]
                if not c8 or cE["N"] - c8["N"] < 80: continue
                e.append(c8["n"].get(z, 0) / c8["N"]); l.append((cE["n"].get(z, 0) - c8["n"].get(z, 0)) / (cE["N"] - c8["N"]))
            print(f"    {zc} {z:9s} early->late r={np.corrcoef(e,l)[0,1]:+.2f}")
    print("\n=== GATE 2. RB direction mix persistence YoY (>= 80 carries both seasons) ===")
    for zc, zones in (("side", SIDES), ("lane", LANES)):
        for z in zones:
            a, b = [], []
            for (Y, pid), lst in Pm[zc].items():
                nx = Pm[zc].get((Y + 1, pid))
                if not nx: continue
                c0, c1 = lst[-1][1], nx[-1][1]
                if c0["N"] >= 80 and c1["N"] >= 80: a.append(c0["n"].get(z, 0) / c0["N"]); b.append(c1["n"].get(z, 0) / c1["N"])
            print(f"  {zc} {z:9s} r={np.corrcoef(a,b)[0,1]:+.2f} (n={len(a)}, sd {np.std(a):.3f})")

    # ---- samples: RB only
    S = iter_samples(("RB",)); A = to_arrays(S); years = sorted(set(A["year"]))
    n = len(S); M = {"side": np.full(n, np.nan), "lane": np.full(n, np.nan)}; Ms = {"side": np.full(n, np.nan), "lane": np.full(n, np.nan)}
    F = {"side": np.full(n, np.nan), "lane": np.full(n, np.nan)}; defN = np.zeros(n)
    for i, s in enumerate(S):
        if not s["pid"]: continue
        Y = s["year"]
        for zc, zones in (("side", SIDES), ("lane", LANES)):
            dc = before(D[zc].get((Y, s["opp"])), s["wk"]); pc = before(Pm[zc].get((Y, s["pid"])), s["wk"])
            pr = Pm[zc].get((Y - 1, s["pid"])); pr = pr[-1][1] if pr else None
            if not dc or dc["N"] < 1: continue
            defN[i] = dc["N"]
            lga = tot[Y][0]; lgs = tot[Y][1]
            r_all = (dc["N"] * (dc["Y"] / dc["N"] / lga) + K_DEF) / (dc["N"] + K_DEF)
            s_all = (dc["N"] * (dc["S"] / dc["N"] / lgs) + K_DEF) / (dc["N"] + K_DEF)
            m = ms = f = 0.0; wsum = 0.0
            pn = pc["N"] if pc else 0.0
            for z in zones:
                lgz, lgsz, lgn = lg[(Y, zc, z)]; lgshare = lgn / tot[Y][2]
                dn = dc["n"].get(z, 0.0)
                rz = (dn * ((dc["y"].get(z, 0.0) / dn / lgz) if dn else 1.0) + K_DEF) / (dn + K_DEF)
                sz = (dn * ((dc["s"].get(z, 0.0) / dn / lgsz) if dn else 1.0) + K_DEF) / (dn + K_DEF)
                fz = (dc["N"] * ((dn / dc["N"]) / lgshare) + K_DEF) / (dc["N"] + K_DEF)
                cv = (pc["n"].get(z, 0.0) / pn) if pn else None
                pv = (pr["n"].get(z, 0.0) / pr["N"]) if (pr and pr["N"] >= 40) else lgshare
                w = pv if cv is None else (pn * cv + K_PLR * pv) / (pn + K_PLR)
                m += w * rz; ms += w * sz; f += w * fz; wsum += w
            if wsum > 0:
                M[zc][i] = (m / wsum) / r_all; Ms[zc][i] = (ms / wsum) / s_all; F[zc][i] = f / wsum
    ok = ~np.isnan(M["side"]) & ~np.isnan(M["lane"]) & (defN >= 60)
    act, ship = A["act"], A["shipped"]
    print(f"\n{ok.sum()} RB player-weeks with direction data (defense >= 60 carries faced) | shipped MSE {mse(ship[ok], act[ok]):.4f}")
    print("\n=== 1. actual / shipped by matchup quintile ===")
    for lab, x in (("M side (yds)", M["side"]), ("M lane (yds)", M["lane"]), ("M side (success)", Ms["side"]), ("M lane (success)", Ms["lane"]), ("F side (funnel)", F["side"]), ("F lane (funnel)", F["lane"])):
        q = np.quantile(x[ok], [.2, .4, .6, .8]); edges = [-np.inf] + list(q) + [np.inf]; parts = []
        for k in range(5):
            m = ok & (x >= edges[k]) & (x < edges[k + 1]); parts.append(f"{x[m].mean():.3f}->{act[m].mean()/ship[m].mean():.3f}")
        print(f"  {lab:18s} " + " | ".join(parts) + f"   corr {np.corrcoef(x[ok], (act[ok]-ship[ok])/np.maximum(ship[ok],1))[0,1]:+.3f}")
    print("\n=== 2. LOYO on RB rows: shipped x (1 + e x trust x (X - 1)), trust = min(1, defN/200) ===")
    Sok = {"year": A["year"][ok], "act": act[ok]}; sh = ship[ok]; tr = np.minimum(1.0, defN[ok] / 200.0)
    grid = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]
    for lab, x in (("side yds matchup", M["side"]), ("lane yds matchup", M["lane"]), ("side success matchup", Ms["side"]), ("lane success matchup", Ms["lane"]), ("side funnel", F["side"]), ("lane funnel", F["lane"])):
        xx = x[ok]
        loyo(Sok, years, grid, lambda e, xx=xx: sh * np.clip(1 + e * tr * (xx - 1), 0.8, 1.25), lab)
    loyo(Sok, years, grid, lambda e: sh * np.clip(1 + e * tr * (M["lane"][ok] * F["lane"][ok] - 1), 0.8, 1.25), "lane matchup x lane funnel")

if __name__ == "__main__":
    main()
