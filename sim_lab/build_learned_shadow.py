#!/usr/bin/env python3
"""
LEARNED SHADOW MODEL (2026-09-16) - the live shadow of backtest_learned_combo.py's "learned correction on top of
the hand stack" (LOYO -1.07% 7/7, forward -.87% 4/5 vs the rebuilt live layers). Jack: "yes build the live shadow".

Only features the engine can compute LIVE with the same definition are kept (vacancy shares, pool gains and dome
dropped - the engine has no identical number). Target = actual half-PPR - HAND (live: jsMean at half-PPR).
Re-graded LOYO + forward on the restricted set, then one final model on all 2019-25 rows (rounds = median fold
rounds x 1.15, shrink k = median fold k) exported as JSON trees for engine.js learnedShadowCorr():

  data/learned_shadow_model.js   window.SIM_LEARNED_SHADOW = {features, k, trees, grade, built}
  learned_shadow_testvec.json    200 rows: feature vectors + Python predictions (verify_learned_shadow.js checks
                                 the JS evaluator reproduces them)
The engine logs lcCorr / lcMean = shipped mean + lcCorr on every lock row (SHADOW ONLY, never shown as PROJ);
score_week.py grades "Learned shadow" next to the shipped mean every Tuesday. Kill: window.SIM_LEARNED_SHADOW = false.
"""
import json, os, sys, time
import numpy as np
import pandas as pd
import lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
YEARS = list(range(2019, 2026))
K_GRID = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25]
GBM = dict(objective="regression", learning_rate=0.02, num_leaves=7,   # 7 not 15: tune_learned_shadow.py + seed check (3 seeds) LOYO -1.04 vs -0.98, forward -0.89 vs -0.81
           min_data_in_leaf=200, feature_fraction=0.8,
           bagging_fraction=0.8, bagging_freq=1, lambda_l2=20.0, verbose=-1, seed=11, num_threads=4)
FEATS = ["pos_qb", "pos_rb", "pos_wr", "pos_te", "wk", "g", "ppg", "clay", "blend", "veg", "fpa_mult", "snapmult", "snap_std", "snap_l1",
         "snap_trend", "td_luck_pg", "td_luck_adj", "cond_mult", "rep_q", "prac_dnp", "prac_lim", "rookie_mult", "usage_half", "plays_pg_std",
         "weather_mult", "wind", "pool_mult", "qb_inherit_mult", "implied", "spread", "game_total", "HAND"]


def P(*a):
    print(" ".join(str(x) for x in a), flush=True)


def mse(a, b):
    return float(np.mean((np.asarray(a, dtype=float) - np.asarray(b, dtype=float)) ** 2))


POSL = ("QB", "RB", "WR", "TE")
HAND_TH = np.array([1, 1, 1, 1, 1, 1, 0.15, 1, 1, 1, 1, 1], dtype=float)


def stack(d, th):
    """same as backtest_learned_combo.stack (copied: importing that script truncates its log)"""
    e_snap, e_wind, e_cond, e_pool, e_qbi, e_rook, w_u, k_l = th[:8]
    c = np.select([d.pos == p for p in POSL], th[8:12], 1.0)
    b1 = d.blend.values * d.rookie_mult.values ** e_rook
    u = d.usage_half.values
    b1 = np.where(np.isfinite(u), (1 - w_u) * b1 + w_u * np.nan_to_num(u), b1)
    chain = (d.veg.values * d.fpa_mult.values * d.snapmult.values ** e_snap * d.weather_mult.values ** e_wind *
             d.cond_mult.values ** e_cond * d.pool_mult.values ** e_pool * d.qb_inherit_mult.values ** e_qbi)
    return b1 * chain * c + k_l * d.td_luck_adj.values


class LC:
    stack = staticmethod(stack)
    HAND_TH = HAND_TH


def load():
    so = sys.stdout
    F =pd.read_parquet(os.path.join(HERE, "ctx_features.parquet"))
    L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet"))
    df = pd.concat([F.reset_index(drop=True), L.drop(columns=["year", "pid", "wk", "name"]).reset_index(drop=True)], axis=1)
    df = df[df.act.notna() & df.base2.notna()].reset_index(drop=True)
    for c in df.columns:
        if df[c].dtype == bool:
            df[c] = df[c].astype(float)
    df["HAND"] = LC.stack(df, LC.HAND_TH)
    for c in FEATS:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    return df, so


def fold(df, tr, va, te):
    y = (df.act - df.HAND).values
    dtr = lgb.Dataset(df.loc[tr & ~va, FEATS], y[tr & ~va]); dva = lgb.Dataset(df.loc[va, FEATS], y[va], reference=dtr)
    m = lgb.train(GBM, dtr, num_boost_round=1500, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
    rounds = max(m.best_iteration, 20)
    pv = m.predict(df.loc[va, FEATS], num_iteration=rounds)
    k = min(K_GRID, key=lambda kk: mse(df.loc[va, "HAND"].values + kk * pv, df.loc[va, "act"].values))
    m2 = lgb.train(GBM, lgb.Dataset(df.loc[tr, FEATS], y[tr]), num_boost_round=int(rounds * 1.15))
    return df.loc[te, "HAND"].values + k * m2.predict(df.loc[te, FEATS]), k, rounds


def compact(node):
    if "leaf_value" in node:
        return round(float(node["leaf_value"]), 6)
    mt = {"None": 0, "Zero": 1, "NaN": 2}[node.get("missing_type", "None")]
    assert node.get("decision_type", "<=") == "<="
    return [int(node["split_feature"]), float(node["threshold"]), 1 if node.get("default_left") else 0, mt,
            compact(node["left_child"]), compact(node["right_child"])]


def main():
    t0 = time.time()
    df, so = load()
    P(f"{len(df)} player-weeks, {len(FEATS)} live-computable features")
    pred = np.full(len(df), np.nan); ks, rs = [], []
    for T in YEARS:
        V = T + 1 if T < 2025 else T - 1
        tr = (df.year != T).values; va = (df.year == V).values; te = (df.year == T).values
        pred[te], k, r = fold(df, tr, va, te); ks.append(k); rs.append(r)
    e, h = mse(pred, df.act), mse(df.HAND, df.act)
    wins = sum(mse(pred[(df.year == y).values], df.act[df.year == y]) < mse(df.HAND[df.year == y], df.act[df.year == y]) for y in YEARS)
    bypos = {p: round((mse(pred[(df.pos == p).values], df.act[df.pos == p]) / mse(df.HAND[df.pos == p], df.act[df.pos == p]) - 1) * 100, 2) for p in ("QB", "RB", "WR", "TE")}
    P(f"LOYO vs HAND: {(e/h-1)*100:+.2f}% ({wins}/7) by position {bypos} | fold k {ks} rounds {rs}")
    fe = fh = 0.0; fn = 0; fw = 0
    for T in range(2021, 2026):
        tr = (df.year < T).values; va = (df.year == T - 1).values; te = (df.year == T).values
        p_, _, _ = fold(df, tr, va, te)
        a, b = mse(p_, df.act[te]), mse(df.HAND[te], df.act[te])
        fe += a * te.sum(); fh += b * te.sum(); fn += te.sum(); fw += a < b
        P(f"  forward {T}: {(a/b-1)*100:+.2f}%")
    P(f"FORWARD vs HAND: {(fe/fh-1)*100:+.2f}% ({fw}/5)")

    k_final = float(np.median(ks)); rounds_final = int(np.median(rs) * 1.15)
    y = (df.act - df.HAND).values
    m = lgb.train(GBM, lgb.Dataset(df[FEATS], y), num_boost_round=rounds_final)
    dump = m.dump_model()
    trees = [compact(t["tree_structure"]) for t in dump["tree_info"]]
    grade = {"loyoPct": round((e / h - 1) * 100, 3), "loyoWins": int(wins), "forwardPct": round((fe / fh - 1) * 100, 3), "forwardWins": int(fw),
             "byPos": bypos, "n": int(len(df))}
    payload = {"built": time.strftime("%Y-%m-%d %H:%M"), "features": FEATS, "k": k_final, "rounds": rounds_final, "grade": grade,
               "note": "Learned correction on top of the hand-tuned live stack (actual - jsMean, half-PPR). SHADOW ONLY: logged as lcCorr / lcMean on lock rows, graded by score_week.py.",
               "trees": trees}
    with open(os.path.join(HERE, "data", "learned_shadow_model.js"), "w", encoding="utf-8") as fh_:
        fh_.write("// built by build_learned_shadow.py - LightGBM correction on top of the live hand stack (SHADOW ONLY; engine learnedShadowCorr)\n")
        fh_.write("window.SIM_LEARNED_SHADOW = "); json.dump(payload, fh_, separators=(",", ":")); fh_.write(";\n")
    rng = np.random.default_rng(3)
    idx = rng.choice(len(df), 200, replace=False)
    X = df.loc[idx, FEATS]
    # a few NaNs on purpose (live rows often lack snaps / usage)
    X = X.copy(); X.iloc[:20, FEATS.index("usage_half")] = np.nan; X.iloc[20:40, FEATS.index("snap_trend")] = np.nan
    vec = {"features": FEATS, "k": k_final, "rows": [[None if pd.isna(v) else float(v) for v in r] for r in X.values], "pred": [float(v) for v in m.predict(X)]}
    json.dump(vec, open(os.path.join(HERE, "learned_shadow_testvec.json"), "w"))
    size = os.path.getsize(os.path.join(HERE, "data", "learned_shadow_model.js")) / 1024
    P(f"final model: {rounds_final} trees, k {k_final}, {size:.0f} KB -> data/learned_shadow_model.js; test vectors -> learned_shadow_testvec.json ({time.time()-t0:.0f}s)")
    sys.stdout = so


if __name__ == "__main__":
    main()
