#!/usr/bin/env python3
"""
PRESSURE PROXY backtest, 2018-2025 — re-derives the soft-pass-rush QB boost
(backtest_pressure.py) on a pressure rate the engine can actually see
IN-SEASON.

Why: the shipped layer read `was_pressure` from nflverse pbp_participation,
which (2023+) is FTN-sourced and published only AFTER the postseason — so
SIM_PRESSURE_2026 stays empty all year. Play-by-play, which updates nightly,
carries per-play `qb_hit` and `sack` flags; (qb_hit OR sack) / dropbacks is
the standard public pressure proxy.

Steps
  1. per defense-week: TRUE pressure (was_pressure) and PROXY (hit|sack),
     league rates, def-season correlation proxy vs true (does the proxy
     rank defenses the same way?)
  2. GATE A for the proxy: in-season wk1-8 -> wk9+ and YoY stability
  3. LAYER: same harness as backtest_pressure.py (QB weekly residual vs
     P=5 Bayesian base x QB-FPA), predictor = opp proxy rate to date minus
     league avg; one-sided boost sweep over threshold x boost, and the
     same sweep on TRUE pressure for the identical rows (apples to apples).

Usage: python backtest_pressure_proxy.py  (~2 min; reads 8 pbp csv.gz)
"""
import numpy as np
import pandas as pd
import json, os
from collections import defaultdict
from backtest_sim_calibration import (played, weekly_rec, POOL_MIN_PTS, OPP_ALIAS)
import backtest_sim_calibration as cal
from backtest_pressure import TEAM_FIX, CACHE, P, YEARS

def build_both(year):
    """dtrue[(def,wk)]=[pressured,dropbacks] (participation), dprox[(def,wk)]=
    [hit-or-sack, dropbacks] (pbp only), plus dhit / dsack components."""
    pbp = pd.read_csv(os.path.join(CACHE, f"play_by_play_{year}.csv.gz"),
                      usecols=["game_id", "play_id", "week", "season_type", "defteam",
                               "qb_dropback", "qb_hit", "sack"],
                      low_memory=False)
    pbp = pbp[(pbp.season_type == "REG") & (pbp.qb_dropback == 1) & pbp.defteam.notna()]
    pbp["hit"] = (pbp.qb_hit.fillna(0) == 1) | (pbp.sack.fillna(0) == 1)
    pbp["d"] = pbp.defteam.map(lambda t: TEAM_FIX.get(t, t))
    dprox = defaultdict(lambda: [0, 0]); dhit = defaultdict(lambda: [0, 0]); dsack = defaultdict(lambda: [0, 0])
    for r in pbp.itertuples(index=False):
        k = (r.d, int(r.week))
        dprox[k][1] += 1; dhit[k][1] += 1; dsack[k][1] += 1
        if r.hit: dprox[k][0] += 1
        if r.qb_hit == 1: dhit[k][0] += 1
        if r.sack == 1: dsack[k][0] += 1
    part = pd.read_parquet(os.path.join(CACHE, f"pbp_participation_{year}.parquet"),
                           columns=["nflverse_game_id", "play_id", "was_pressure"])
    part = part[part.was_pressure.notna()]
    m = part.merge(pbp[["game_id", "play_id", "week", "d"]],
                   left_on=["nflverse_game_id", "play_id"], right_on=["game_id", "play_id"], how="inner")
    dtrue = defaultdict(lambda: [0, 0])
    for r in m.itertuples(index=False):
        k = (r.d, int(r.week))
        dtrue[k][1] += 1
        if bool(r.was_pressure): dtrue[k][0] += 1
    return dtrue, dprox, dhit, dsack

def season_rates(dweek, min_n=250):
    a = defaultdict(lambda: [0, 0])
    for (d, wk), (p, n) in dweek.items():
        a[d][0] += p; a[d][1] += n
    return {d: v[0] / v[1] for d, v in a.items() if v[1] >= min_n}

def gate_a(DW, label):
    xs, ys = [], []
    for Y, dweek in DW.items():
        e = defaultdict(lambda: [0, 0]); l = defaultdict(lambda: [0, 0])
        for (d, wk), (p, n) in dweek.items():
            t = e if wk <= 8 else l
            t[d][0] += p; t[d][1] += n
        for d in e:
            if d in l and e[d][1] >= 120 and l[d][1] >= 120:
                xs.append(e[d][0] / e[d][1]); ys.append(l[d][0] / l[d][1])
    xs, ys = np.array(xs), np.array(ys)
    seas = {Y: season_rates(dw) for Y, dw in DW.items()}
    x2, y2 = [], []
    for Y in YEARS:
        if Y + 1 in seas:
            for d, r in seas[Y].items():
                if d in seas[Y + 1]:
                    x2.append(r); y2.append(seas[Y + 1][d])
    print(f"  {label}: in-season wk1-8->wk9+ corr {np.corrcoef(xs, ys)[0,1]:+.3f} "
          f"(rate mean {xs.mean():.3f}, sd {xs.std():.3f}, n={len(xs)}) | YoY corr "
          f"{np.corrcoef(np.array(x2), np.array(y2))[0,1]:+.3f} (n={len(x2)})")

def layer_rows(DW, pos="QB"):
    """Same construction as backtest_pressure.py: one row per QB player-week
    with base, base*FPA, actual, dev (opp rate to date - league), trust."""
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    from research_cb_qb_te import build_fpa
    fpa = build_fpa(pos)
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
                        S.append({"key": (Y, name, wk), "bf": base * fpa(Y, opp, wk), "act": fpts,
                                  "dev": pr / n - lgp, "trust": min(1.0, n / 250.0)})
                hist.append(fpts)
    return {s["key"]: s for s in S}

def sweep(rows, label, thrs, boosts):
    bf = np.array([r["bf"] for r in rows]); act = np.array([r["act"] for r in rows])
    dev = np.array([r["dev"] for r in rows]); tr = np.array([r["trust"] for r in rows])
    mse0 = float(np.mean((bf - act) ** 2))
    print(f"\n  {label}: {len(rows)} QB player-weeks, dev sd {dev.std():.3f}, base*FPA MSE {mse0:.3f}")
    print("    one-sided boost (dev <= thr): MSE change % (negative = better)")
    hdr = "    thr     " + "".join(f"  x{b:.2f}" for b in boosts) + "   share"
    print(hdr)
    best = None
    for thr in thrs:
        soft = dev <= thr
        line = f"    {thr:+.3f}  "
        for b in boosts:
            mult = np.where(soft, 1 + (b - 1) * tr, 1.0)
            v = float(np.mean((bf * mult - act) ** 2))
            pct = 100 * (v - mse0) / mse0
            line += f" {pct:+6.2f}"
            if best is None or v < best[2]:
                best = (thr, b, v, pct)
        print(line + f"   {100*soft.mean():5.1f}%")
    print(f"    <- best thr {best[0]:+.3f} x{best[1]:.2f} ({best[3]:+.2f}%)")
    # dose-response buckets (in units of dev sd)
    sd = dev.std()
    print("    buckets (dev in sd units): act/(base*FPA)")
    for lo, hi in [(-9, -1.5), (-1.5, -1.0), (-1.0, -0.5), (-0.5, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 9)]:
        m = (dev >= lo * sd) & (dev < hi * sd)
        if m.sum() < 100:
            continue
        print(f"      [{lo:+.1f},{hi:+.1f})  dev {dev[m].mean():+.3f}  ratio {act[m].sum()/bf[m].sum():.3f}  n={m.sum()}")
    return best

def main():
    DT, DP, DH, DS = {}, {}, {}, {}
    for Y in YEARS:
        DT[Y], DP[Y], DH[Y], DS[Y] = build_both(Y)
        nt = sum(v[1] for v in DT[Y].values()); pt = sum(v[0] for v in DT[Y].values())
        npx = sum(v[1] for v in DP[Y].values()); pp = sum(v[0] for v in DP[Y].values())
        print(f"  {Y}: true {pt/nt:.3f} ({nt} db) | proxy hit|sack {pp/npx:.3f} ({npx} db) | "
              f"hit {sum(v[0] for v in DH[Y].values())/npx:.3f} sack {sum(v[0] for v in DS[Y].values())/npx:.3f}")

    print("\n=== proxy vs TRUE pressure, defense-season rates (>=250 db) ===")
    for lab, D in (("hit|sack", DP), ("hit only", DH), ("sack only", DS)):
        xs, ys = [], []
        for Y in YEARS:
            t = season_rates(DT[Y]); p = season_rates(D[Y])
            for d in t:
                if d in p:
                    xs.append(t[d]); ys.append(p[d])
        xs, ys = np.array(xs), np.array(ys)
        zt = (xs - xs.mean()) / xs.std(); zp = (ys - ys.mean()) / ys.std()
        print(f"  {lab:9s}: corr {np.corrcoef(xs, ys)[0,1]:+.3f} (n={len(xs)} def-seasons) | "
              f"sd true {xs.std():.3f} vs proxy {ys.std():.3f} | soft-side agreement "
              f"(true z<=-1 vs proxy z<=-1): {np.mean(zp[zt <= -1] <= -1):.2f}")

    print("\n=== GATE A: stability ===")
    gate_a(DT, "TRUE  ")
    gate_a(DP, "PROXY ")

    print("\n=== LAYER TEST: QB vs opp pressure deviation, same rows ===")
    RT = layer_rows(DT); RP = layer_rows(DP)
    common = sorted(set(RT) & set(RP))
    print(f"  common QB player-weeks: {len(common)} (true-only {len(set(RT)-set(RP))}, proxy-only {len(set(RP)-set(RT))})")
    rt = [RT[k] for k in common]; rp = [RP[k] for k in common]
    boosts = (1.03, 1.05, 1.08, 1.10, 1.12)
    sweep(rt, "TRUE was_pressure", (-0.02, -0.03, -0.04, -0.05), boosts)
    bp = sweep(rp, "PROXY hit|sack   ", (-0.015, -0.02, -0.025, -0.03, -0.035, -0.04, -0.05), boosts)
    # overlap of the two "soft" sets at the chosen thresholds
    dt = np.array([r["dev"] for r in rt]); dp = np.array([r["dev"] for r in rp])
    st = dt <= -0.03; sp = dp <= bp[0]
    print(f"\n  soft-set overlap: true(thr -0.03) {st.mean()*100:.1f}% | proxy(thr {bp[0]:+.3f}) {sp.mean()*100:.1f}% | "
          f"jaccard {np.sum(st & sp)/max(1,np.sum(st | sp)):.2f} | of true-soft rows, proxy flags {np.mean(sp[st]):.2f}")
    # by-year robustness at the chosen proxy threshold/boost
    print("\n  proxy pick by season (MSE change %):")
    for Y in range(2019, 2026):
        rr = [r for r in rp if r["key"][0] == Y]
        if len(rr) < 100:
            continue
        bf = np.array([r["bf"] for r in rr]); act = np.array([r["act"] for r in rr])
        dev = np.array([r["dev"] for r in rr]); tr = np.array([r["trust"] for r in rr])
        mult = np.where(dev <= bp[0], 1 + (bp[1] - 1) * tr, 1.0)
        m0 = np.mean((bf - act) ** 2); m1 = np.mean((bf * mult - act) ** 2)
        print(f"    {Y}: {100*(m1-m0)/m0:+.2f}%  (soft share {100*np.mean(dev <= bp[0]):.1f}%, n={len(rr)})")

if __name__ == "__main__":
    main()
