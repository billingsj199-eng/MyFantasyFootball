#!/usr/bin/env python3
"""
LEARNED COMBINATION vs HAND-TUNED LIVE LAYERS (2026-09-16). Research only.

backtest_context_model.py found that a model fed only the signals the engine already ships (REF) beat the harness
base by 2.84%, better than any new context. Open question: does a LEARNED combination of those signals beat the
HAND-TUNED way the engine combines them? build_live_layers.py rebuilt the live stack on the same player-weeks.

  HAND        ((blend x rookie) blended .15 with RB snap usage) x Vegas x FPA x snap trend x wind x banged cond x
              opportunity pool x backup-QB inheritance + TD-luck adjustment      (engine constants, engine order)
  ladder      base2 -> +TD luck -> +banged -> +rookie -> +RB usage -> +wind -> +pool -> +backup QB = HAND
  STRENGTH    same formula, layer strengths refit on the training seasons (exponent per multiplier, usage weight,
              TD-luck scale, one scale per position) - shippable as new engine constants
  STRENGTH-NS same without the per-position scale (strengths only, no recalibration)
  CAL         per-position a + b x HAND refit on the training seasons (recalibration only)
  GBM+HAND    LightGBM on actual - HAND from the layer ingredients (a learned correction on top of the hand stack)
  GBM         LightGBM on actual - base2 from the same ingredients (a learned replacement of the hand stack)
Protocol: LOYO 2019-25 (GBM rounds + shrink on a held-out validation season) and FORWARD 2021-25 (train on the
past only). Graded vs HAND: MSE, seasons better, forward. Ship bar: <= -0.3% with >= 5/7 and forward better.
Can't be replayed historically: the 70% player-prop anchor, availability of players who sat (rows are games
played), forecast vs game-time wind, TE route trend, blowout context. A pass here earns a live shadow on the
lock rows (graded by score_week.py), not a direct swap.
Log learned_combo_backtest.log; data/learned_combo_backtest.js (SIM_LEARNED_BT), ZONES tab.
"""
import json, os, sys, time
import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy.optimize import least_squares

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = open(os.path.join(HERE, "learned_combo_backtest.log"), "w", encoding="utf-8")


class _Tee:
    def __init__(self, a, b): self.a, self.b = a, b
    def write(self, t): self.a.write(t); self.b.write(t); self.a.flush(); self.b.flush()
    def flush(self): self.a.flush(); self.b.flush()


sys.stdout = _Tee(sys.stdout, LOG)
def P(*a): print(" ".join(str(x) for x in a))

YEARS = list(range(2019, 2026))
POS = ("QB", "RB", "WR", "TE")
SHIP_PCT, SHIP_WINS = -0.30, 5
K_GRID = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25]
GBM = dict(objective="regression", learning_rate=0.02, num_leaves=15, min_data_in_leaf=200, feature_fraction=0.8,
           bagging_fraction=0.8, bagging_freq=1, lambda_l2=20.0, verbose=-1, seed=11, num_threads=4)
RES = {"ladder": [], "models": [], "subsets": [], "forward": [], "constants": {}}
PNAMES = ["e_snap", "e_wind", "e_cond", "e_pool", "e_qbinh", "e_rookie", "w_usage", "k_luck", "c_QB", "c_RB", "c_WR", "c_TE"]


def mse(a, b):
    return float(np.mean((np.asarray(a, dtype=float) - np.asarray(b, dtype=float)) ** 2))


def stack(d, th):
    e_snap, e_wind, e_cond, e_pool, e_qbi, e_rook, w_u, k_l = th[:8]
    c = np.select([d.pos == p for p in POS], th[8:12], 1.0)
    b1 = d.blend.values * d.rookie_mult.values ** e_rook
    u = d.usage_half.values
    b1 = np.where(np.isfinite(u), (1 - w_u) * b1 + w_u * np.nan_to_num(u), b1)
    chain = (d.veg.values * d.fpa_mult.values * d.snapmult.values ** e_snap * d.weather_mult.values ** e_wind *
             d.cond_mult.values ** e_cond * d.pool_mult.values ** e_pool * d.qb_inherit_mult.values ** e_qbi)
    return b1 * chain * c + k_l * d.td_luck_adj.values


HAND_TH = np.array([1, 1, 1, 1, 1, 1, 0.15, 1, 1, 1, 1, 1], dtype=float)


def fit_strength(d, scale=True):
    lo = [0, 0, 0, 0, 0, 0, 0, 0] + ([0.7] * 4 if scale else [0.999] * 4)
    hi = [3, 4, 4, 3, 2, 4, 0.8, 3] + ([1.4] * 4 if scale else [1.001] * 4)
    x0 = HAND_TH.copy()
    r = least_squares(lambda th: stack(d, th) - d.act.values, x0, bounds=(lo, hi), loss="linear", max_nfev=200)
    return r.x


def gbm_fold(df, feats, target, base_col, tr, va, te):
    y = (df.act - df[base_col]).values
    dtr = lgb.Dataset(df.loc[tr & ~va, feats], y[tr & ~va]); dva = lgb.Dataset(df.loc[va, feats], y[va], reference=dtr)
    m = lgb.train(GBM, dtr, num_boost_round=1500, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
    rounds = max(m.best_iteration, 20)
    pv = m.predict(df.loc[va, feats], num_iteration=rounds)
    k = min(K_GRID, key=lambda kk: mse(df.loc[va, base_col].values + kk * pv, df.loc[va, "act"].values))
    m2 = lgb.train(GBM, lgb.Dataset(df.loc[tr, feats], y[tr]), num_boost_round=int(rounds * 1.15))
    return df.loc[te, base_col].values + k * m2.predict(df.loc[te, feats]), k


def main():
    t0 = time.time()
    F = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet"))
    L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet"))
    assert len(F) == len(L) and (F.year.values == L.year.values).all() and (F.wk.values == L.wk.values).all() and (F.name.values == L.name.values).all()
    df = pd.concat([F.reset_index(drop=True), L.drop(columns=["year", "pid", "wk", "name"]).reset_index(drop=True)], axis=1)   # row-aligned (pid can be missing)
    df = df[df.act.notna() & df.base2.notna()].reset_index(drop=True)
    for c in df.columns:
        if df[c].dtype == bool:
            df[c] = df[c].astype(float)
    P(f"{len(df)} player-weeks (features {len(F)}, layers {len(L)})")

    # ---- ladder ----
    P("\n=== HAND ladder: each live layer added in turn (vs the previous step) ===")
    steps = [("base2 (blend x Vegas x FPA x snap trend)", [1, 0, 0, 0, 0, 0, 0, 0]),
             ("+ TD luck", [1, 0, 0, 0, 0, 0, 0, 1]), ("+ banged-up cond", [1, 0, 1, 0, 0, 0, 0, 1]),
             ("+ rookie level", [1, 0, 1, 0, 0, 1, 0, 1]), ("+ RB snap usage", [1, 0, 1, 0, 0, 1, 0.15, 1]),
             ("+ wind", [1, 1, 1, 0, 0, 1, 0.15, 1]), ("+ opportunity pool", [1, 1, 1, 1, 0, 1, 0.15, 1]),
             ("+ backup QB = HAND", [1, 1, 1, 1, 1, 1, 0.15, 1])]
    prev = None
    for lab, th in steps:
        pr = stack(df, np.array(th + [1, 1, 1, 1], dtype=float))
        e = mse(pr, df.act)
        wins = sum(mse(pr[(df.year == y).values], df.act[df.year == y]) < mse(prev[(df.year == y).values], df.act[df.year == y]) for y in YEARS) if prev is not None else None
        rec = {"step": lab, "mse": round(e, 4), "pct": round((e / mse(prev, df.act) - 1) * 100, 3) if prev is not None else 0.0, "wins": wins}
        RES["ladder"].append(rec)
        P(f"  {lab:44s} MSE {e:.4f}" + (f"  step {rec['pct']:+.3f}% ({wins}/7)" if prev is not None else ""))
        prev = pr
    df["HAND"] = stack(df, HAND_TH)
    P(f"  HAND vs base2 {(mse(df.HAND, df.act)/mse(df.base2, df.act)-1)*100:+.2f}%")

    feats = ["pos_qb", "pos_rb", "pos_wr", "pos_te", "wk", "g", "ppg", "clay", "blend", "veg", "fpa_mult", "snapmult", "snap_std", "snap_l1",
             "snap_trend", "td_luck_pg", "td_luck_adj", "cond_mult", "rep_q", "prac_dnp", "prac_lim", "rookie_mult", "usage_half", "plays_pg_std",
             "weather_mult", "wind", "dome", "pool_gain_tg", "pool_gain_car", "pool_mult", "qb_inherit_mult", "vac_tgt_same", "vac_car_same",
             "implied", "spread", "game_total"]
    feats = [c for c in feats if c in df.columns]
    for c in feats:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    feats_h = feats + ["HAND"]

    models = ["STRENGTH", "STRENGTH-NS", "CAL", "GBM+HAND", "GBM"]
    for m in models:
        df[m] = np.nan
    ths = []
    P("\n=== LOYO ===")
    for T in YEARS:
        V = T + 1 if T < 2025 else T - 1
        tr = (df.year != T).values; va = (df.year == V).values; te = (df.year == T).values
        th = fit_strength(df[tr]); ths.append(th)
        df.loc[te, "STRENGTH"] = stack(df[te], th)
        df.loc[te, "STRENGTH-NS"] = stack(df[te], fit_strength(df[tr], scale=False))
        cal = df.loc[te, "HAND"].values.copy()
        for p in POS:
            mt = tr & (df.pos == p).values; me = te & (df.pos == p).values
            b, a = np.polyfit(df.HAND[mt], df.act[mt], 1)
            cal[me[te]] = a + b * df.HAND[me].values
        df.loc[te, "CAL"] = cal
        df.loc[te, "GBM+HAND"], kh = gbm_fold(df, feats_h, "act", "HAND", tr, va, te)
        df.loc[te, "GBM"], kg = gbm_fold(df, feats, "act", "base2", tr, va, te)
        s = df[te]
        P(f"  {T}: HAND {mse(s.HAND, s.act):.3f} | " + " | ".join(f"{m} {mse(s[m], s.act):.3f}" for m in models) + f" | k {kh}/{kg} ({time.time()-t0:.0f}s)")
    RES["strengthFolds"] = [dict(zip(PNAMES, [round(float(v), 3) for v in th])) for th in ths]

    P("\n=== vs HAND (LOYO) ===")
    allm = np.ones(len(df), dtype=bool)
    for m in models:
        for pos, mk in [("ALL", allm)] + [(p, (df.pos == p).values) for p in POS]:
            s = df[mk]
            e, h = mse(s[m], s.act), mse(s.HAND, s.act)
            wins = sum(mse(s[m][s.year == y], s.act[s.year == y]) < mse(s.HAND[s.year == y], s.act[s.year == y]) for y in YEARS)
            RES["models"].append({"model": m, "pos": pos, "n": int(mk.sum()), "hand": round(h, 3), "mse": round(e, 3), "pct": round((e / h - 1) * 100, 3), "wins": int(wins)})
            P(f"  {m:12s} {pos:3s} n {mk.sum():5d} HAND {h:.3f} -> {e:.3f} ({(e/h-1)*100:+.2f}%) better {wins}/7")

    P("\n=== FORWARD (train on earlier seasons only) vs HAND ===")
    fw = {m: [] for m in models}
    for T in range(2021, 2026):
        tr = (df.year < T).values; va = (df.year == T - 1).values; te = (df.year == T).values
        s = df[te].copy(); h = mse(s.HAND, s.act)
        preds = {"STRENGTH": stack(s, fit_strength(df[tr])), "STRENGTH-NS": stack(s, fit_strength(df[tr], scale=False))}
        cal = s.HAND.values.copy()
        for p in POS:
            mt = tr & (df.pos == p).values
            b, a = np.polyfit(df.HAND[mt], df.act[mt], 1)
            cal[(s.pos == p).values] = a + b * s.HAND[s.pos == p].values
        preds["CAL"] = cal
        preds["GBM+HAND"], _ = gbm_fold(df, feats_h, "act", "HAND", tr, va, te)
        preds["GBM"], _ = gbm_fold(df, feats, "act", "base2", tr, va, te)
        row = {"year": T, "n": int(te.sum()), "hand": round(h, 3)}
        for m in models:
            e = mse(preds[m], s.act); fw[m].append((e, h, te.sum())); row[m] = round((e / h - 1) * 100, 3)
        RES["forward"].append(row)
        P(f"  {T}: HAND {h:.3f} | " + " | ".join(f"{m} {row[m]:+.2f}%" for m in models))
    RES["forwardSummary"] = {}
    for m in models:
        n = sum(x[2] for x in fw[m]); e = sum(x[0] * x[2] for x in fw[m]) / n; h = sum(x[1] * x[2] for x in fw[m]) / n
        RES["forwardSummary"][m] = {"pct": round((e / h - 1) * 100, 3), "wins": int(sum(x[0] < x[1] for x in fw[m]))}
        P(f"  forward pooled {m:12s} {(e/h-1)*100:+.2f}% ({RES['forwardSummary'][m]['wins']}/5)")

    for r in RES["models"]:
        if r["pos"] == "ALL":
            fs = RES["forwardSummary"][r["model"]]
            r["fwdPct"], r["fwdWins"] = fs["pct"], fs["wins"]
            r["verdict"] = "PASS" if (r["pct"] <= SHIP_PCT and r["wins"] >= SHIP_WINS and fs["pct"] < 0) else ("lean" if r["pct"] <= -0.1 and r["wins"] >= 4 else "FAIL")

    P("\n=== where the live layers are active (LOYO, vs HAND) ===")
    subsets = [("TD luck |adj| >= 0.5 pts", df.td_luck_adj.abs() >= 0.5), ("played Questionable", df.cond_mult < 1),
               ("rookie QB/RB", df.rookie_mult > 1), ("RB usage blend active", df.usage_half.notna()),
               ("wind >= 10 (QB/WR/TE)", df.weather_mult < 1), ("opportunity pool boost", df.pool_mult > 1),
               ("backup QB inheriting", df.qb_inherit_mult > 1)]
    for lab, mk in subsets:
        mk = mk.values
        s = df[mk]
        if len(s) < 60:
            P(f"  {lab}: too few ({len(s)})"); continue
        h = mse(s.HAND, s.act)
        rec = {"label": lab, "n": int(len(s)), "actOverHand": round(float(s.act.mean() / s.HAND.mean()), 3), "hand": round(h, 3)}
        for m in models:
            rec[m] = round((mse(s[m], s.act) / h - 1) * 100, 2)
        RES["subsets"].append(rec)
        P(f"  {lab:28s} n {len(s):5d} act/HAND {rec['actOverHand']:.3f} | " + " | ".join(f"{m} {rec[m]:+.2f}%" for m in models))

    th_all = fit_strength(df); th_ns = fit_strength(df, scale=False)
    RES["constants"] = {"hand": dict(zip(PNAMES, HAND_TH.tolist())), "strengthAll": dict(zip(PNAMES, [round(float(v), 3) for v in th_all])),
                        "strengthNoScaleAll": dict(zip(PNAMES, [round(float(v), 3) for v in th_ns]))}
    P("\n  refit strengths, all seasons: " + ", ".join(f"{k} {v}" for k, v in RES["constants"]["strengthAll"].items()))
    P("  refit strengths without position scale: " + ", ".join(f"{k} {v}" for k, v in RES["constants"]["strengthNoScaleAll"].items() if not k.startswith("c_")))

    RES["updated"] = time.strftime("%Y-%m-%d %H:%M"); RES["n"] = int(len(df)); RES["bar"] = {"pct": SHIP_PCT, "wins": SHIP_WINS}
    RES["handVsBase2"] = round((mse(df.HAND, df.act) / mse(df.base2, df.act) - 1) * 100, 3)
    allr = [r for r in RES["models"] if r["pos"] == "ALL"]
    passed = [r for r in allr if r.get("verdict") == "PASS"]
    RES["summary"] = (f"Hand-tuned live stack rebuilt on {RES['n']} player-weeks: {RES['handVsBase2']:+.2f}% vs the harness base. Learned vs hand: " +
                      "; ".join(f"{r['model']} {r['pct']:+.2f}% ({r['wins']}/7, forward {r['fwdPct']:+.2f}%)" for r in allr) +
                      (". Passing: " + ", ".join(r["model"] for r in passed) if passed else ". Nothing beats the hand-tuned stack by the ship bar"))
    with open(os.path.join(HERE, "data", "learned_combo_backtest.js"), "w", encoding="utf-8") as fh:
        fh.write("// built by backtest_learned_combo.py - learned combination vs the hand-tuned live layers; ZONES tab\n")
        fh.write("window.SIM_LEARNED_BT = "); json.dump(RES, fh, separators=(",", ":")); fh.write(";\n")
    P(f"\nwrote data/learned_combo_backtest.js: {RES['summary']}")
    P(f"done ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
