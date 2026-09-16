"""Seed-noise check for the tuning study's top configs (tune_learned_shadow.py): same evaluate(), 3 seeds each."""
import os, sys, json, time
import numpy as np
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import build_learned_shadow as BL
import tune_learned_shadow as TU   # tees stdout into tune_learned_shadow.log: point it at a separate log
TU.LOG.close()
TU.LOG = open(os.path.join(HERE, "seedcheck_learned_shadow.log"), "w", encoding="utf-8")
sys.stdout = TU._Tee(sys.__stdout__, TU.LOG)
df, _ = BL.load()
ctx = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet"))
for c in ("proe_std", "proe_py", "plays_pg_py"):
    df[c] = pd.to_numeric(ctx[c], errors="coerce").values
F = list(BL.FEATS); TEAM = ["proe_std", "proe_py", "plays_pg_py"]
configs = [("current (15 leaves)", F, {}), ("7 leaves", F, {"num_leaves": 7}), ("15 leaves, L2 60", F, {"lambda_l2": 60.0}),
           ("current + team", F + TEAM, {}), ("7 leaves + team", F + TEAM, {"num_leaves": 7}), ("7 leaves, L2 60 + team", F + TEAM, {"num_leaves": 7, "lambda_l2": 60.0})]
out = []
for lab, fs, over in configs:
    L, W = [], []
    for seed in (11, 23, 37):
        r = TU.evaluate(df, fs, dict(BL.GBM, seed=seed, **over))
        L.append(r["loyo"]); W.append(r["fwd"])
    out.append({"label": lab, "loyo": L, "fwd": W, "loyoMean": round(float(np.mean(L)), 3), "fwdMean": round(float(np.mean(W)), 3)})
    print(f"{lab:26s} LOYO {np.mean(L):+.2f}% (seeds {', '.join(f'{x:+.2f}' for x in L)}) | forward {np.mean(W):+.2f}% (seeds {', '.join(f'{x:+.2f}' for x in W)})", flush=True)
json.dump(out, open(os.path.join(HERE, "seedcheck_learned_shadow.json"), "w"))
