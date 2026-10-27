#!/usr/bin/env python3
"""refit_gbm.py - the first GBM fit overfit (in-sample MAE 3.6 vs forward 6.4). Regularised refit: shallower trees,
fewer rounds, bigger leaves. Forward-checks 2025 again, then refits 2017-25 and overwrites out/gbm*_{pos}.txt."""
import os, json, numpy as np, pandas as pd
from model import load_asof, fit_adp_curve, fit_gbm, gbm_predict, grade_table, struct_predict, apply_cal, POS4, HERE
from fit_history import finalize_rows, TRAIN, FWD

OUT = os.path.join(HERE, "out")
P = json.load(open(os.path.join(OUT, "params.json")))
curve = {k: tuple(v) for k, v in P["curve"].items()}
PRM = dict(learning_rate=0.03, num_leaves=7, min_data_in_leaf=200, feature_fraction=0.5, lambda_l2=20.0)
ROUNDS = 250
import model
_orig = model.fit_gbm


def fit(train, struct=None):
    import lightgbm as lgb
    from model import importance, gbm_frame
    w = importance(train, curve); models = {}
    for p in POS4:
        m = train.pos.values == p
        X = gbm_frame(train[m], curve, None if struct is None else struct[m])
        prm = dict(objective="regression", bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=0, num_threads=4); prm.update(PRM)
        models[p] = lgb.train(prm, lgb.Dataset(X, label=train.act.values[m], weight=np.sqrt(w[m])), num_boost_round=ROUNDS)
    return models


allh = finalize_rows(load_asof(TRAIN + FWD))
train = allh[allh.season.isin(TRAIN)].reset_index(drop=True); fwd = allh[allh.season.isin(FWD)].reset_index(drop=True)
def st(df):
    raw, _ = struct_predict(df, P["prm"], curve, P["tcoef"], P["L"]); return apply_cal(df, raw, {k: tuple(v) for k, v in P["cal"].items()})
g1 = fit(train); g2 = fit(train, st(train))
preds = {"STRUCT": st(fwd), "GBM_reg": gbm_predict(fwd, g1, curve), "STACK_reg": gbm_predict(fwd, g2, curve, st(fwd))}
preds["BLEND_reg"] = 0.5 * preds["STRUCT"] + 0.5 * preds["GBM_reg"]
tab = grade_table(fwd, preds, curve, by_band=False)
print(tab[tab.band == "top150"][["label", "pos", "n", "mae", "bias", "rho", "top12", "pair_acc"]].to_string())
g1 = fit(allh); g2 = fit(allh, st(allh))
for p in POS4:
    g1[p].save_model(os.path.join(OUT, f"gbm_{p}.txt")); g2[p].save_model(os.path.join(OUT, f"gbm2_{p}.txt"))
print("saved regularised GBMs")
