#!/usr/bin/env python3
"""
JOINT CONTEXT MODEL BACKTEST (2026-09-16) - step 2. Research only: nothing here touches the engine.

Every earlier layer was graded ALONE as a bolt-on multiplier. This grades all the context at once, interactions
included, on the table from build_context_features.py (QB/RB/WR/TE player-weeks 2019-25, week 2+).

  target      residual = actual - base2   (base2 = shipped blend x Vegas x FPA x the shipped snap-trend layer)
  models      GBM   LightGBM on every feature group (conservative: 15 leaves, 200+ rows per leaf, L2, lr .02)
              RIDGE standardized linear model, NaN -> train median + missing flags
              CAL   GBM on the base group only (projection, PPG, Clay, week, position...) - separates "recalibrating
                    the shipped number" from real context; the context gain is GBM vs CAL
  protocol    LOYO over 2019-25: for test season T, validation season V (T+1, or T-1 for 2025) is held out of
              training to pick boosting rounds / ridge alpha and a shrink k (0-1.25); refit on all six other seasons;
              prediction = base2 + k x model. FORWARD check: T = 2021-25 trained only on earlier seasons.
  reports     overall + per position (MSE vs base2, seasons better, ship bar <= -0.3% with >= 5/7), new-situation
              subsets (vacancy, inheritance, team change, new playcaller, QB out, OL starters out, OL grade drop,
              rookies, 2nd year, weeks 2-4, own injury tag), group ablation (drop one group, refit), gain importance.
Log context_model_backtest.log; results data/context_model_backtest.js (SIM_CTXMODEL_BT), ZONES tab;
out-of-fold predictions ctx_model_oof.parquet (for the per-player "why" step).
"""
import json, os, sys, time
import numpy as np
import pandas as pd
import lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = open(os.path.join(HERE, "context_model_backtest.log"), "w", encoding="utf-8")


class _Tee:
    def __init__(self, a, b): self.a, self.b = a, b
    def write(self, t): self.a.write(t); self.b.write(t); self.a.flush(); self.b.flush()
    def flush(self): self.a.flush(); self.b.flush()


sys.stdout = _Tee(sys.stdout, LOG)
def P(*a): print(" ".join(str(x) for x in a))

YEARS = list(range(2019, 2026))
SHIP_PCT, SHIP_WINS = -0.30, 5
K_GRID = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25]
GBM = dict(objective="regression", learning_rate=0.02, num_leaves=15, min_data_in_leaf=200, feature_fraction=0.7,
           bagging_fraction=0.8, bagging_freq=1, lambda_l2=20.0, verbose=-1, seed=7, num_threads=4)
RES = {"tests": [], "subsets": [], "ablation": [], "importance": [], "forward": [], "n": 0}


def mse(a, b):
    return float(np.mean((np.asarray(a) - np.asarray(b)) ** 2))


def fit_gbm(Xtr, ytr, Xva, yva):
    dtr = lgb.Dataset(Xtr, ytr, free_raw_data=False); dva = lgb.Dataset(Xva, yva, reference=dtr)
    m = lgb.train(GBM, dtr, num_boost_round=1500, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
    return max(m.best_iteration, 20)


def gbm_fold(df, feats, tr, va, te):
    """-> (test residual prediction x k, k, rounds, model)"""
    y = df["res"].values
    rounds = fit_gbm(df.loc[tr & ~va, feats], y[tr & ~va], df.loc[va, feats], y[va])
    m1 = lgb.train(GBM, lgb.Dataset(df.loc[tr & ~va, feats], y[tr & ~va]), num_boost_round=rounds)
    pv = m1.predict(df.loc[va, feats])
    base_va = df.loc[va, "base2"].values; act_va = df.loc[va, "act"].values
    k = min(K_GRID, key=lambda kk: mse(base_va + kk * pv, act_va))
    m = lgb.train(GBM, lgb.Dataset(df.loc[tr, feats], y[tr]), num_boost_round=int(rounds * 1.15))
    return k * m.predict(df.loc[te, feats]), k, rounds, m


def ridge_fold(df, feats, tr, va, te):
    X = df[feats].astype(float)
    med = X[tr].median()
    miss = [c for c in feats if X[c].isna().any()]
    def prep(mask, mu=None, sd=None):
        Z = X[mask].fillna(med)
        for c in miss:
            Z[c + "_na"] = X.loc[mask, c].isna().astype(float)
        return Z
    y = df["res"].values
    Ztr0 = prep(tr & ~va); mu, sd = Ztr0.mean(), Ztr0.std().replace(0, 1)
    def solve(Z, yy, alpha):
        A = ((Z - mu) / sd).values; A = np.hstack([np.ones((len(A), 1)), A])
        R = alpha * np.eye(A.shape[1]); R[0, 0] = 0
        return np.linalg.solve(A.T @ A + R, A.T @ yy)
    def pred(Z, w):
        A = ((Z - mu) / sd).values; return np.hstack([np.ones((len(A), 1)), A]) @ w
    Zva = prep(va); base_va = df.loc[va, "base2"].values; act_va = df.loc[va, "act"].values
    best = None
    for alpha in (100.0, 1000.0, 10000.0, 100000.0):
        w = solve(Ztr0, y[tr & ~va], alpha); pv = pred(Zva, w)
        for kk in K_GRID:
            e = mse(base_va + kk * pv, act_va)
            if best is None or e < best[0]:
                best = (e, alpha, kk)
    Ztr = prep(tr); mu, sd = Ztr.mean(), Ztr.std().replace(0, 1)
    w = solve(Ztr, y[tr], best[1])
    return best[2] * pred(prep(te), w), best[2]


def grade(df, pred_col, mask, label, family, pos, store=True):
    rows = df[mask]
    ys = [y for y in YEARS if (rows.year == y).any()]
    wins = 0
    for y in ys:
        r = rows[rows.year == y]
        wins += mse(r[pred_col], r.act) < mse(r.base2, r.act)
    b, m = mse(rows.base2, rows.act), mse(rows[pred_col], rows.act)
    pct = (m / b - 1) * 100
    verdict = "PASS" if (pct <= SHIP_PCT and wins >= SHIP_WINS) else ("lean" if (pct <= -0.1 and wins >= 4) else "FAIL")
    rec = {"label": label, "family": family, "pos": pos, "n": int(len(rows)), "base": round(b, 3), "mse": round(m, 3), "pct": round(pct, 3),
           "wins": int(wins), "years": len(ys), "verdict": verdict}
    if store:
        RES["tests"].append(rec)
    return rec


def main():
    t0 = time.time()
    df = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet"))
    groups = json.load(open(os.path.join(HERE, "ctx_features_groups.json")))
    df = df[df.base2.notna() & df.act.notna()].reset_index(drop=True)
    df["res"] = df.act - df.base2
    feats = [c for g in groups.values() for c in g if c in df.columns]
    for c in feats:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    RES["n"] = int(len(df)); RES["features"] = len(feats)
    P(f"{len(df)} player-weeks, {len(feats)} features in {len(groups)} groups; base2 MSE {mse(df.base2, df.act):.3f} (shipped {mse(df.shipped, df.act):.3f})")
    P("feature coverage by group: " + " | ".join(f"{g} {df[[c for c in cs if c in df]].notna().mean().mean():.2f}" for g, cs in groups.items()))

    base_feats = [c for c in groups["base"] if c in df.columns]
    for c in ("GBM", "RIDGE", "CAL"):
        df[c] = np.nan
    imp = {}
    P("\n=== LOYO folds ===")
    for T in YEARS:
        V = T + 1 if T < 2025 else T - 1
        tr = (df.year != T).values; va = (df.year == V).values; te = (df.year == T).values
        g, k, rounds, m = gbm_fold(df, feats, tr, va, te)
        df.loc[te, "GBM"] = df.loc[te, "base2"] + g
        for f_, v in zip(feats, m.feature_importance("gain")):
            imp[f_] = imp.get(f_, 0.0) + float(v)
        c, kc, rc, _ = gbm_fold(df, base_feats, tr, va, te)
        df.loc[te, "CAL"] = df.loc[te, "base2"] + c
        r, kr = ridge_fold(df, feats, tr, va, te)
        df.loc[te, "RIDGE"] = df.loc[te, "base2"] + r
        sub = df[te]
        P(f"  {T}: n {te.sum()} | base2 {mse(sub.base2, sub.act):.3f} | GBM {mse(sub.GBM, sub.act):.3f} (k {k}, {rounds} rounds) | "
          f"CAL {mse(sub.CAL, sub.act):.3f} (k {kc}) | RIDGE {mse(sub.RIDGE, sub.act):.3f} (k {kr}) ({time.time()-t0:.0f}s)")

    allm = np.ones(len(df), dtype=bool)
    P("\n=== overall and by position (vs base2) ===")
    for model, fam in (("GBM", "all context (LightGBM)"), ("RIDGE", "all context (ridge)"), ("CAL", "calibration only (base group)")):
        for pos, m in [("ALL", allm)] + [(p, (df.pos == p).values) for p in ("QB", "RB", "WR", "TE")]:
            r = grade(df, model, m, f"{model} {pos}", fam, pos)
            P(f"  {model:5s} {pos:3s} n {r['n']:5d} base2 {r['base']:.3f} -> {r['mse']:.3f} ({r['pct']:+.2f}%), better {r['wins']}/{r['years']} {r['verdict']}")
    # context over calibration
    ctx_gain = (mse(df.GBM, df.act) / mse(df.CAL, df.act) - 1) * 100
    RES["ctxOverCal"] = round(ctx_gain, 3)
    P(f"  context over calibration-only: {ctx_gain:+.2f}% MSE")

    P("\n=== new-situation subsets (GBM / CAL vs base2) ===")
    subsets = [
        ("teammate vacancy >= 10% share, same position", (df.vac_tgt_same.fillna(0) + df.vac_car_same.fillna(0)) >= 0.10),
        ("expected inheritance >= 5% share", (df.inherit_tgt.fillna(0) + df.inherit_car.fillna(0)) >= 0.05),
        ("changed teams", df.team_change == 1), ("new playcaller", df.new_pc == 1), ("new head coach", df.new_hc == 1),
        ("starting QB out (non-QB rows)", df.qb_out == 1), ("1+ OL starter out", df.ol_out_n >= 1), ("2+ OL starters out", df.ol_out_n >= 2),
        ("OL pass-block grade drop >= 2", df.ol_pb_drop >= 2), ("rookies", df.rookie == 1), ("2nd year", df.yr2 == 1),
        ("weeks 2-4", df.wk <= 4), ("own report Questionable", df.rep_q == 1), ("man-heavy opponent (top quarter)", df.opp_man_std >= df.opp_man_std.quantile(0.75)),
    ]
    for lab, m in subsets:
        m = m.fillna(False).values if hasattr(m, "fillna") else m
        if m.sum() < 150:
            P(f"  {lab}: too few rows ({int(m.sum())})"); continue
        g = grade(df, "GBM", m, lab, "subset", "GBM", store=False); c = grade(df, "CAL", m, lab, "subset", "CAL", store=False)
        RES["subsets"].append({"label": lab, "n": g["n"], "base": g["base"], "gbm": g["mse"], "gbmPct": g["pct"], "gbmWins": g["wins"],
                               "cal": c["mse"], "calPct": c["pct"], "calWins": c["wins"], "years": g["years"], "verdict": g["verdict"],
                               "actOverBase": round(float(df.act[m].mean() / df.base2[m].mean()), 3)})
        P(f"  {lab:48s} n {g['n']:5d} act/base2 {df.act[m].mean()/df.base2[m].mean():.3f} | GBM {g['pct']:+.2f}% ({g['wins']}/{g['years']}) | CAL {c['pct']:+.2f}% ({c['wins']}/{c['years']}) {g['verdict']}")

    P("\n=== gain importance by group (sum over folds, share) ===")
    tot = sum(imp.values()) or 1.0
    for gname, cs in groups.items():
        s = sum(imp.get(c, 0.0) for c in cs)
        top = sorted(((imp.get(c, 0.0), c) for c in cs), reverse=True)[:3]
        RES["importance"].append({"group": gname, "share": round(s / tot, 4), "top": [c for v, c in top if v > 0]})
        P(f"  {gname:10s} {s/tot*100:5.1f}%  top: {', '.join(f'{c} {v/tot*100:.1f}%' for v, c in top if v > 0)}")

    P("\n=== group ablation (GBM refit without one group; + = the group helped) ===")
    full = mse(df.GBM, df.act)
    for gname, cs in groups.items():
        if gname == "base":
            continue
        fs = [c for c in feats if c not in cs]
        pred = np.full(len(df), np.nan)
        for T in YEARS:
            V = T + 1 if T < 2025 else T - 1
            tr = (df.year != T).values; va = (df.year == V).values; te = (df.year == T).values
            g, _, _, _ = gbm_fold(df, fs, tr, va, te)
            pred[te] = df.loc[te, "base2"].values + g
        e = mse(pred, df.act)
        RES["ablation"].append({"group": gname, "mseWithout": round(e, 4), "full": round(full, 4), "helpPct": round((e / full - 1) * 100, 3)})
        P(f"  without {gname:10s} MSE {e:.4f} vs full {full:.4f} -> group worth {(e/full-1)*100:+.3f}% ({time.time()-t0:.0f}s)")

    P("\n=== FORWARD check (train only on earlier seasons) ===")
    fw = []
    for T in range(2021, 2026):
        V = T - 1
        tr = (df.year < T).values; va = (df.year == V).values; te = (df.year == T).values
        g, k, rounds, _ = gbm_fold(df, feats, tr, va, te)
        c, kc, _, _ = gbm_fold(df, base_feats, tr, va, te)
        sub = df[te]; b = mse(sub.base2, sub.act); e = mse(sub.base2 + g, sub.act); ec = mse(sub.base2 + c, sub.act)
        fw.append((b, e, ec, te.sum()))
        RES["forward"].append({"year": T, "n": int(te.sum()), "base": round(b, 3), "gbm": round(e, 3), "cal": round(ec, 3), "k": k})
        P(f"  {T}: base2 {b:.3f} GBM {e:.3f} ({(e/b-1)*100:+.2f}%, k {k}) CAL {ec:.3f} ({(ec/b-1)*100:+.2f}%)")
    n = sum(x[3] for x in fw)
    fb = sum(x[0] * x[3] for x in fw) / n; fe = sum(x[1] * x[3] for x in fw) / n; fc = sum(x[2] * x[3] for x in fw) / n
    RES["forwardSummary"] = {"pct": round((fe / fb - 1) * 100, 3), "calPct": round((fc / fb - 1) * 100, 3), "wins": int(sum(x[1] < x[0] for x in fw)), "years": len(fw)}
    P(f"  forward pooled: GBM {(fe/fb-1)*100:+.2f}% ({RES['forwardSummary']['wins']}/{len(fw)}), CAL {(fc/fb-1)*100:+.2f}%")

    # ---- INCREMENT over what the live engine already ships ----
    # The harness base lacks live layers that the engine has: TD-luck regression (pts_over_xfp), snap trend (snap
    # features), banged-up docks (own injury tags), rookie level, the opportunity pool (vacancy redistribution),
    # the weather multiplier and Vegas (env). REF = base + those signals, so REF -> REF+group is what is genuinely new.
    P("\n=== INCREMENT over shipped-equivalent signals (REF = base + TD luck + snap trend + own injury + rookie + vacancy + Vegas/weather) ===")
    ref_feats = base_feats + ["pts_over_xfp", "snap_std", "snap_l1", "snap_trend", "rookie"] + groups["own_injury"] + groups["vacancy"] + groups["env"]
    ref_feats = [c for c in dict.fromkeys(ref_feats) if c in df.columns]
    usage_rest = [c for c in groups["usage"] if c not in ref_feats]
    variants = [("REF", ref_feats), ("REF + usage shares", ref_feats + usage_rest)]
    for gname in ("prior", "team", "coach", "prospect", "matchup", "oline"):
        variants.append((f"REF + {gname}", ref_feats + [c for c in groups[gname] if c in df.columns]))
    variants.append(("REF + usage + coach + oline + matchup + prospect", ref_feats + usage_rest + [c for g in ("coach", "oline", "matchup", "prospect") for c in groups[g] if c in df.columns]))
    variants.append(("FULL (every group)", feats))
    RES["increment"] = []
    ref_loyo = ref_fw = None
    for lab, fs in variants:
        fs = list(dict.fromkeys(fs))
        pred = np.full(len(df), np.nan)
        for T in YEARS:
            V = T + 1 if T < 2025 else T - 1
            tr = (df.year != T).values; va = (df.year == V).values; te = (df.year == T).values
            g, _, _, _ = gbm_fold(df, fs, tr, va, te)
            pred[te] = df.loc[te, "base2"].values + g
        fpred = np.full(len(df), np.nan)
        for T in range(2021, 2026):
            tr = (df.year < T).values; va = (df.year == T - 1).values; te = (df.year == T).values
            g, _, _, _ = gbm_fold(df, fs, tr, va, te)
            fpred[te] = df.loc[te, "base2"].values + g
        if lab == "REF":
            ref_loyo, ref_fw = pred.copy(), fpred.copy()
        e = mse(pred, df.act); wins = sum(mse(pred[(df.year == y).values], df.act[df.year == y]) < mse(ref_loyo[(df.year == y).values], df.act[df.year == y]) for y in YEARS)
        fm = df.year >= 2021
        ef = mse(fpred[fm.values], df.act[fm]); eref = mse(ref_fw[fm.values], df.act[fm])
        fwins = sum(mse(fpred[(df.year == y).values], df.act[df.year == y]) < mse(ref_fw[(df.year == y).values], df.act[df.year == y]) for y in range(2021, 2026))
        rec = {"label": lab, "features": len(fs), "loyo": round(e, 4), "vsBase2": round((e / mse(df.base2, df.act) - 1) * 100, 3),
               "vsRef": round((e / mse(ref_loyo, df.act) - 1) * 100, 3), "winsVsRef": int(wins),
               "fwdVsRef": round((ef / eref - 1) * 100, 3), "fwdWinsVsRef": int(fwins)}
        rec["verdict"] = "PASS" if (lab != "REF" and rec["vsRef"] <= SHIP_PCT and wins >= SHIP_WINS and rec["fwdVsRef"] < 0) else ("REF" if lab == "REF" else ("lean" if rec["vsRef"] <= -0.1 and wins >= 4 else "FAIL"))
        RES["increment"].append(rec)
        P(f"  {lab:50s} feats {len(fs):3d} | vs base2 {rec['vsBase2']:+.2f}% | vs REF {rec['vsRef']:+.2f}% ({wins}/7) | forward vs REF {rec['fwdVsRef']:+.2f}% ({fwins}/5) {rec['verdict']} ({time.time()-t0:.0f}s)")
    inc_pass = [r for r in RES["increment"] if r["verdict"] == "PASS"]

    df[["year", "name", "pos", "team", "opp", "pid", "wk", "act", "base2", "GBM", "CAL", "RIDGE"]].to_parquet(os.path.join(HERE, "ctx_model_oof.parquet"), index=False)
    main_t = [t for t in RES["tests"] if t["family"].startswith("all context (LightGBM)") and t["pos"] == "ALL"][0]
    RES["updated"] = time.strftime("%Y-%m-%d %H:%M"); RES["years"] = YEARS; RES["bar"] = {"pct": SHIP_PCT, "wins": SHIP_WINS}
    passed = [t for t in RES["tests"] if t["verdict"] == "PASS"]
    RES["summary"] = (f"Joint context model on {RES['n']} player-weeks, {RES['features']} features: all-context GBM {main_t['pct']:+.2f}% MSE vs shipped ({main_t['wins']}/{main_t['years']}), "
                      f"context beyond calibration {ctx_gain:+.2f}%, forward (train on past only) {RES['forwardSummary']['pct']:+.2f}%. "
                      f"Beyond signals the live engine already ships: " + ("; ".join(f"{r['label']} {r['vsRef']:+.2f}% ({r['winsVsRef']}/7, forward {r['fwdVsRef']:+.2f}%)" for r in inc_pass) if inc_pass else "nothing new passes the ship bar"))
    with open(os.path.join(HERE, "data", "context_model_backtest.js"), "w", encoding="utf-8") as fh:
        fh.write("// built by backtest_context_model.py - joint context model (all feature groups at once) vs the shipped projection; ZONES tab\n")
        fh.write("window.SIM_CTXMODEL_BT = "); json.dump(RES, fh, separators=(",", ":")); fh.write(";\n")
    P(f"\nwrote data/context_model_backtest.js: {RES['summary']}")
    P(f"done ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
