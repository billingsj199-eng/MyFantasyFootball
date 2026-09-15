#!/usr/bin/env python3
"""
VARIANCE BY TD-HEAVINESS backtest, 2019-2025 (Jack 2026-09-15: "continue
adding" - item 3 of the post-luck list). The luck layers fixed the MEAN; a
player whose points come from TDs should have fatter tails than one who lives
on receptions, and the engine's sigma (3-yr weekly CV, position defaults,
youth widenings, SIGMA_CAL, tuner sigmaMult) does not look at scoring mix.

Predictor  tdsh = prior-season TD share of points (6 x (rtd + rctd) / fpts,
           >= 8 games; else position mean) - and recsh = receptions per point
           (the PPR floor) as the mirror image.
Base       P=5 Clay/PPG blend x Vegas (pos e) = mean; sd = mean x
           sqrt((0.9 x sigma_entering)^2 + 0.04)  (engine total width);
           gamma(mean, sd) = the engine's weekly distribution.
Grading    CRPS of the gamma forecast (closed form, proper score) + p10-p90
           coverage, per position; LOYO sweep of sigma x (1 + e x tdsh_z) and
           of a per-position coverage-only recalibration for reference.

Log: sigma_tdshare_backtest.log
"""
import numpy as np
import json, os
from collections import defaultdict
from scipy.stats import gamma as G
from scipy.special import beta as Beta
from backtest_sim_calibration import (played, weekly_rec, infer_team, POOL_MIN_PTS, OPP_ALIAS, sigma_entering)
import backtest_sim_calibration as cal
from backtest_target_area import implied_map, mse, LOAD_YEARS, YEARS, VEGAS_E, P, CACHE
# (stdout re-wrapped by backtest_target_area on import)
import pandas as pd

POS_TEST = ("RB", "WR", "TE")
VEG = dict(VEGAS_E)

def load_lines(Y):
    df = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"),
                     usecols=["game_id", "season_type", "week", "posteam", "home_team", "away_team", "home_score", "away_score",
                              "spread_line", "total_line"], low_memory=False)
    df = df[(df.season_type == "REG") & df.posteam.notna()]
    return implied_map(df.dropna(subset=["spread_line", "total_line"]).groupby("game_id").first())

def crps_gamma(mean, sd, y):
    """closed-form CRPS for Gamma(shape a, rate b) at y (Scheuerer & Moller 2015)."""
    a = (mean / sd) ** 2; b = a / mean            # shape, rate
    F1 = G.cdf(y, a, scale=1 / b); F2 = G.cdf(y, a + 1, scale=1 / b)
    return y * (2 * F1 - 1) - (a / b) * (2 * F2 - 1) - 1 / (b * Beta(0.5, a))

def main():
    clay_hist = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    S = defaultdict(list); miss = defaultdict(int)
    for Y in YEARS:
        if str(Y) not in clay_hist: continue
        imp = load_lines(Y); avg = float(np.mean(list(imp.values())))
        W = 16 if Y <= 2020 else 17
        for name, c in clay_hist[str(Y)].items():
            pos = c.get("pos")
            if pos not in POS_TEST or (c.get("pts") or 0) < POOL_MIN_PTS: continue
            wrec = weekly_rec(name, pos)
            if wrec is None: miss["weekly"] += 1; continue
            team = infer_team(wrec, Y)
            if not team: miss["team"] += 1; continue
            prior = [w for w in wrec.get("seasons", {}).get(str(Y - 1), []) if played(w) and isinstance(w.get("fpts"), (int, float))]
            if len(prior) >= 8 and sum(w["fpts"] for w in prior) > 20:
                tds = sum((w.get("rtd") or 0) + (w.get("rctd") or 0) for w in prior)
                tdsh = 6.0 * tds / sum(w["fpts"] for w in prior)
                recsh = sum((w.get("rec") or 0) for w in prior) / sum(w["fpts"] for w in prior)
            else:
                tdsh = None; recsh = None
            sig = sigma_entering(name, pos, Y)
            rows = sorted([(w["wk"], w["fpts"], (w.get("rtd") or 0) + (w.get("rctd") or 0)) for w in wrec.get("seasons", {}).get(str(Y), [])
                           if played(w) and isinstance(w.get("fpts"), (int, float))])
            clay_pg = max(0.2, (c["pts"] or 0) - (c.get("rec") or 0) / 2.0) / W
            hist = []
            for wk, fpts, td in rows:
                li = imp.get((team, wk))
                if li is not None and hist:
                    g = len(hist); ppg = sum(hist) / g
                    base = (P * clay_pg + g * ppg) / (P + g)
                    veg = min(1.35, max(0.7, 1 + VEG[pos] * (li - avg) / avg))
                    S["year"].append(Y); S["pos"].append(pos); S["act"].append(fpts); S["mean"].append(base * veg)
                    S["sig"].append(sig); S["g"].append(g)
                    S["tdsh"].append(np.nan if tdsh is None else tdsh); S["recsh"].append(np.nan if recsh is None else recsh)
                    S["name"].append(name)
                hist.append(fpts)
        print(f"  {Y}: samples so far {len(S['act'])}")
    print(f"  skipped: {dict(miss)}")
    S = {k: (np.array(v) if k in ("pos", "name") else np.array(v, float)) for k, v in S.items()}
    S["year"] = S["year"].astype(int); years = sorted(set(S["year"]))
    pos, act, mean, sig = S["pos"], S["act"], S["mean"], S["sig"]
    # fill missing predictor with position mean; z within position
    tdsh = S["tdsh"].copy(); recsh = S["recsh"].copy()
    tz = np.zeros_like(tdsh); rz = np.zeros_like(tdsh)
    for p in POS_TEST:
        m = pos == p; ok = m & ~np.isnan(tdsh)
        mu, sd = tdsh[ok].mean(), tdsh[ok].std(); tdsh[m & np.isnan(tdsh)] = mu
        tz[m] = np.clip((tdsh[m] - mu) / sd, -2.5, 2.5)
        mu2, sd2 = recsh[ok].mean(), recsh[ok].std(); recsh[m & np.isnan(recsh)] = mu2
        rz[m] = np.clip((recsh[m] - mu2) / sd2, -2.5, 2.5)
        print(f"  {p}: prior TD share of points mean {mu:.2f} sd {sd:.2f} | rec per point mean {mu2:.3f} sd {sd2:.3f} | n={m.sum()}")
    sd_rel = np.sqrt((0.9 * sig) ** 2 + 0.04)
    y = np.maximum(act, 0.0)          # gamma support; negative weeks are rare for RB/WR/TE
    print(f"\n{len(act)} RB/WR/TE player-weeks | engine width CRPS {crps_gamma(mean, mean * sd_rel, y).mean():.4f}")

    # ---- 1. is realized variance actually TD-share dependent, beyond the engine's sigma?
    print("\n=== 1. realized weekly dispersion by prior TD-share tercile (within position) ===")
    for p in POS_TEST:
        m = pos == p; q = np.quantile(tdsh[m], [1/3, 2/3])
        for lo, hi, lab in ((-np.inf, q[0], "low TD-share"), (q[0], q[1], "mid"), (q[1], np.inf, "high TD-share")):
            mm = m & (tdsh >= lo) & (tdsh < hi)
            rel = (act[mm] - mean[mm]) / mean[mm]
            lo10 = G.ppf(0.10, (1 / sd_rel[mm]) ** 2, scale=mean[mm] * sd_rel[mm] ** 2); hi90 = G.ppf(0.90, (1 / sd_rel[mm]) ** 2, scale=mean[mm] * sd_rel[mm] ** 2)
            cov = ((act[mm] >= lo10) & (act[mm] <= hi90)).mean(); above = (act[mm] > hi90).mean()
            print(f"  {p} {lab:13s} n={mm.sum():5d}  realized rel-sd {rel.std():.3f}  engine sd_rel {sd_rel[mm].mean():.3f}  p10-p90 cov {cov:.1%} (above p90 {above:.1%})  CRPS {crps_gamma(mean[mm], mean[mm]*sd_rel[mm], y[mm]).mean():.3f}")
        print(f"     corr(prior TD share, engine sigma) {np.corrcoef(tdsh[m], sig[m])[0,1]:+.2f} | corr(TD share, |rel resid|) {np.corrcoef(tdsh[m], np.abs((act[m]-mean[m])/mean[m]))[0,1]:+.3f} | corr(rec/pt, |rel resid|) {np.corrcoef(recsh[m], np.abs((act[m]-mean[m])/mean[m]))[0,1]:+.3f}")

    # ---- 2. LOYO on CRPS: sigma x (1 + e * tdsh_z) and x (1 - e * recsh_z)
    def loyo_crps(grid, fn, label):
        per = {v: {yy: crps_gamma(mean[S["year"] == yy], (mean * fn(v))[S["year"] == yy], y[S["year"] == yy]).mean() for yy in years} for v in grid}
        ship = per[grid[0]]; tot = n = wins = 0; picks = []
        for yy in years:
            m = S["year"] == yy
            best = min(grid, key=lambda v: sum(per[v][z] for z in years if z != yy)); picks.append(best)
            c = per[best][yy]; tot += c * m.sum(); n += m.sum(); wins += c < ship[yy]
        base_c = sum(ship[yy] * (S["year"] == yy).sum() for yy in years) / n
        print(f"  {label}")
        print("    grid pooled CRPS: " + "  ".join(f"{v:+.2f}:{np.mean(list(per[v].values())):.4f}" for v in grid))
        print(f"    LOYO CRPS {tot/n:.4f} vs engine {base_c:.4f} ({(tot/n/base_c-1)*100:+.2f}%), years better {wins}/{len(years)}, picks {picks}")
    print("\n=== 2. LOYO CRPS sweeps (grid[0] = engine width) ===")
    grid = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30]
    loyo_crps(grid, lambda e: np.sqrt((0.9 * sig * (1 + e * tz)) ** 2 + 0.04), "a) sigma x (1 + e * tdShare_z)")
    loyo_crps(grid, lambda e: np.sqrt((0.9 * sig * (1 - e * rz)) ** 2 + 0.04), "b) sigma x (1 - e * recPerPoint_z)")
    loyo_crps([1.0, 0.85, 0.9, 0.95, 1.05, 1.1, 1.2], lambda k: sd_rel * k, "c) reference: flat width scale")
    for p in POS_TEST:
        m = pos == p
        per = {}
        for e in grid:
            w = np.sqrt((0.9 * sig * (1 + e * tz)) ** 2 + 0.04)
            per[e] = crps_gamma(mean[m], (mean * w)[m], y[m]).mean()
        print(f"   {p} pooled CRPS by e: " + "  ".join(f"{e:.2f}:{per[e]:.4f}" for e in grid))

if __name__ == "__main__":
    main()
