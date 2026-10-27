#!/usr/bin/env python3
"""
fit_history.py - fit the scratch models on history and check them FORWARD before 2026 is touched.

  1. fit everything (ADP curve, league rates, team-volume OLS, STRUCT constants, calibration, GBM) on 2017-2024
  2. grade 2025 forward (never seen by the fit) - this is the honest read of the model design
  3. refit on 2017-2025 and save out/params.json + out/gbm_{pos}.txt for the 2026 backtest

Writes out/fit_history.log and out/history_grades.csv.
"""
import os, sys, json, time
import numpy as np, pandas as pd
from model import (load_asof, fit_adp_curve, team_volume_model, fit_league, struct_predict, fit_struct, calibrate, apply_cal,
                   fit_gbm, gbm_predict, grade_table, importance, POS4, HERE, DEFAULT)

OUT = os.path.join(HERE, "out")
TRAIN = list(range(2017, 2025)); FWD = [2025]


def finalize_rows(df):
    """grade on the rows a weekly model is judged on: the player played, not the final week of the season"""
    finw = np.where(df.season <= 2020, 17, 18)
    return df[(df.week.values < finw)].reset_index(drop=True)


def fit_all(train, log, do_gbm=True):
    curve = fit_adp_curve(train)
    L = fit_league(train)
    tcoef = team_volume_model(train)
    log(f"ADP curve {json.dumps({k: [round(x, 3) for x in v] for k, v in curve.items()})}")
    log(f"team volume OLS {json.dumps({k: [round(x, 3) for x in v] for k, v in tcoef.items()})}")
    t0 = time.time()
    prm = fit_struct(train, curve, tcoef, L)
    log(f"STRUCT params ({time.time() - t0:.0f}s): {json.dumps({k: round(v, 3) for k, v in prm.items()})}")
    raw, _ = struct_predict(train, prm, curve, tcoef, L)
    cal = calibrate(train, raw, curve)
    log(f"calibration {json.dumps({k: [round(x, 3) for x in v] for k, v in cal.items()})}")
    st = apply_cal(train, raw, cal)
    gbm = fit_gbm(train, curve, None) if do_gbm else None
    gbm2 = fit_gbm(train, curve, st) if do_gbm else None     # GBM with the STRUCT number as a feature (stacked)
    return dict(curve=curve, L=L, tcoef=tcoef, prm=prm, cal=cal, gbm=gbm, gbm2=gbm2)


def predict_all(df, F):
    raw, parts = struct_predict(df, F["prm"], F["curve"], F["tcoef"], F["L"])
    st = apply_cal(df, raw, F["cal"])
    out = {"STRUCT": st, "STRUCT_raw": raw}
    if F.get("gbm") is not None:
        out["GBM"] = gbm_predict(df, F["gbm"], F["curve"], None)
        out["STACK"] = gbm_predict(df, F["gbm2"], F["curve"], st)
        out["BLEND"] = 0.5 * st + 0.5 * out["GBM"]
    # naive baselines for scale
    out["naive_ppg"] = np.where(df.g.values > 0, df.ppg_l.fillna(0).values, np.nan_to_num(parts["prior"]))
    out["prior_only"] = parts["prior"]
    return out


def main():
    logf = open(os.path.join(OUT, "fit_history.log"), "w", encoding="utf-8")
    def log(s=""):
        print(s); logf.write(s + "\n"); logf.flush()
    allh = finalize_rows(load_asof(TRAIN + FWD))
    train = allh[allh.season.isin(TRAIN)].reset_index(drop=True)
    fwd = allh[allh.season.isin(FWD)].reset_index(drop=True)
    log(f"train rows {len(train)} (2017-24)  forward rows {len(fwd)} (2025)")
    F = fit_all(train, log)
    preds = predict_all(fwd, F)
    tab = grade_table(fwd, preds, F["curve"])
    tab.to_csv(os.path.join(OUT, "history_grades.csv"), index=False)
    log("\n=== FORWARD 2025 (fit on 2017-24), top-150 importance-weighted ===")
    for pos in POS4 + ("ALL",):
        t = tab[(tab.pos == pos) & (tab.band == "top150")]
        log(f"-- {pos}")
        for r in t.itertuples():
            log(f"   {r.label:12s} n {r.n:5d} MAE {r.mae:6.3f} raw {r.mae_raw:6.3f} bias {r.bias:+6.2f} rho {r.rho:.3f} top6 {r.top6:.3f} top12 {r.top12:.3f} top24 {r.top24:.3f} pair {r.pair_acc:.3f}")
    log("\n=== FORWARD 2025 by ADP band (ALL positions) ===")
    for band in ("1-12", "13-30", "31-60", "61-100", "101-150"):
        t = tab[(tab.pos == "ALL") & (tab.band == band)]
        log(f"-- {band}")
        for r in t.itertuples():
            log(f"   {r.label:12s} n {r.n:5d} MAE {r.mae:6.3f} bias {r.bias:+6.2f} rho {r.rho:.3f} pair {r.pair_acc:.3f}")
    # in-sample for reference
    tab_in = grade_table(train, predict_all(train, F), F["curve"], by_band=False)
    log("\n=== IN-SAMPLE 2017-24 top150 (reference only) ===")
    for r in tab_in[(tab_in.pos == "ALL") & (tab_in.band == "top150")].itertuples():
        log(f"   {r.label:12s} MAE {r.mae:6.3f} rho {r.rho:.3f} pair {r.pair_acc:.3f}")
    # final fit on everything through 2025 for the 2026 test
    log("\n=== refit on 2017-25 for the 2026 backtest ===")
    F2 = fit_all(allh, log)
    json.dump(dict(curve=F2["curve"], L=F2["L"], tcoef=F2["tcoef"], prm=F2["prm"], cal=F2["cal"], train_years=TRAIN + FWD),
              open(os.path.join(OUT, "params.json"), "w"), indent=1)
    for p, m in F2["gbm"].items():
        m.save_model(os.path.join(OUT, f"gbm_{p}.txt"))
    for p, m in F2["gbm2"].items():
        m.save_model(os.path.join(OUT, f"gbm2_{p}.txt"))
    log("saved out/params.json + gbm models")


if __name__ == "__main__":
    main()
