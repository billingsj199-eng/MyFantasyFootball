#!/usr/bin/env python3
"""
TUNING STUDY for the learned shadow (2026-09-16). Jack: "tinker with the shadow model and try to find the biggest
correlation and what we need to tweak to improve it over a large sample (multiple seasons)".

Same rows / target as build_learned_shadow.py (actual - HAND, 17,657 player-weeks 2019-25). Every config is graded
LOYO (7 seasons) AND forward (2021-25, train on the past only) vs HAND; a tweak only counts if both improve on the
current shadow (the risk of picking winners out of many configs is real, so forward is the tiebreaker).

  1 level vs signal    current shadow as-is vs centered (per position x season x week mean correction removed)
  2 correlations       Pearson r of every feature with the residual (actual - HAND), all + per position
  3 attribution        out-of-fold SHAP (pred_contrib): mean |contribution| per feature + direction (r of feature
                       value with its contribution) + quintile table for the top features
  4 hand-layer audit   residual (actual / HAND) by bins of each hand-layer ingredient -> layers set too hot / cold
  5 sweeps             hyperparameters, Huber loss, per-position models, drop-one-feature, add context groups
Log tune_learned_shadow.log; data/learned_shadow_tuning.js (SIM_LSTUNE), ZONES tab.
"""
import json, os, sys, time
import numpy as np
import pandas as pd
import lightgbm as lgb

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
LOG = open(os.path.join(HERE, "tune_learned_shadow.log"), "w", encoding="utf-8")


class _Tee:
    def __init__(self, a, b): self.a, self.b = a, b
    def write(self, t): self.a.write(t); self.b.write(t); self.a.flush(); self.b.flush()
    def flush(self): self.a.flush(); self.b.flush()


import build_learned_shadow as BL   # no stdout side effects at import
sys.stdout = _Tee(sys.stdout, LOG)
def P(*a): print(" ".join(str(x) for x in a))

YEARS = list(range(2019, 2026))
K_GRID = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25]
BASE_PARAMS = dict(BL.GBM)
RES = {"sweeps": [], "corr": [], "shap": [], "audit": [], "dropone": [], "groups": []}
T0 = time.time()


def mse(a, b):
    return float(np.mean((np.asarray(a, dtype=float) - np.asarray(b, dtype=float)) ** 2))


def fold(df, feats, params, tr, va, te, contrib=False):
    y = (df.act - df.HAND).values
    dtr = lgb.Dataset(df.loc[tr & ~va, feats], y[tr & ~va]); dva = lgb.Dataset(df.loc[va, feats], y[va], reference=dtr)
    m = lgb.train(params, dtr, num_boost_round=1500, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
    rounds = max(m.best_iteration, 20)
    pv = m.predict(df.loc[va, feats], num_iteration=rounds)
    k = min(K_GRID, key=lambda kk: mse(df.loc[va, "HAND"].values + kk * pv, df.loc[va, "act"].values))
    m2 = lgb.train(params, lgb.Dataset(df.loc[tr, feats], y[tr]), num_boost_round=int(rounds * 1.15))
    out = k * m2.predict(df.loc[te, feats])
    c = k * m2.predict(df.loc[te, feats], pred_contrib=True) if contrib else None
    return out, c


def evaluate(df, feats, params=None, per_pos=False, contrib=False, forward=True):
    params = params or BASE_PARAMS
    corr = np.full(len(df), np.nan); C = np.zeros((len(df), len(feats) + 1)) if contrib else None
    groups = [(p, (df.pos == p).values) for p in ("QB", "RB", "WR", "TE")] if per_pos else [("ALL", np.ones(len(df), dtype=bool))]
    for _, gm in groups:
        for T in YEARS:
            V = T + 1 if T < 2025 else T - 1
            tr = (df.year != T).values & gm; va = (df.year == V).values & gm; te = (df.year == T).values & gm
            if te.sum() == 0:
                continue
            o, c = fold(df, feats, params, tr, va, te, contrib)
            corr[te] = o
            if contrib:
                C[te] = c
    pred = df.HAND.values + corr
    h = mse(df.HAND, df.act); e = mse(pred, df.act)
    wins = sum(mse(pred[(df.year == y).values], df.act[df.year == y]) < mse(df.HAND[df.year == y], df.act[df.year == y]) for y in YEARS)
    out = {"loyo": round((e / h - 1) * 100, 3), "wins": int(wins), "corr": corr, "C": C}
    if forward:
        fe = fh = 0.0; fw = 0
        for T in range(2021, 2026):
            fc = np.full(len(df), np.nan)
            for _, gm in groups:
                tr = (df.year < T).values & gm; va = (df.year == T - 1).values & gm; te = (df.year == T).values & gm
                if te.sum():
                    fc[te], _ = fold(df, feats, params, tr, va, te)
            te = (df.year == T).values
            a, b = mse(df.HAND.values[te] + fc[te], df.act[te]), mse(df.HAND[te], df.act[te])
            fe += a * te.sum(); fh += b * te.sum(); fw += a < b
        out["fwd"] = round((fe / fh - 1) * 100, 3); out["fwdWins"] = int(fw)
    return out


def main():
    df, _ = BL.load()
    F = list(BL.FEATS)
    ctx = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet"))
    groups = json.load(open(os.path.join(HERE, "ctx_features_groups.json")))
    df["res"] = df.act - df.HAND
    assert len(ctx) == len(df) and (ctx.wk.values == df.wk.values).all()
    P(f"{len(df)} player-weeks, {len(F)} shadow features; HAND MSE {mse(df.HAND, df.act):.3f}")

    # ---- 1 baseline + level vs signal ----
    base = evaluate(df, F, contrib=True)
    RES["current"] = {k: base[k] for k in ("loyo", "wins", "fwd", "fwdWins")}
    P(f"\n=== 1. current shadow: LOYO {base['loyo']:+.2f}% ({base['wins']}/7), forward {base['fwd']:+.2f}% ({base['fwdWins']}/5) ({time.time()-T0:.0f}s)")
    cen = base["corr"] - df.assign(c=base["corr"]).groupby(["pos", "year", "wk"]).c.transform("mean").values
    lvl = base["corr"] - cen
    h = mse(df.HAND, df.act)
    for lab, c in (("level only (per position x week mean correction)", lvl), ("player signal only (centered)", cen), ("both (shipped shadow)", base["corr"])):
        e = mse(df.HAND + c, df.act)
        wins = sum(mse((df.HAND + c)[df.year == y], df.act[df.year == y]) < mse(df.HAND[df.year == y], df.act[df.year == y]) for y in YEARS)
        RES.setdefault("levelSignal", []).append({"label": lab, "pct": round((e / h - 1) * 100, 3), "wins": int(wins)})
        P(f"  {lab:52s} {(e/h-1)*100:+.2f}% ({wins}/7)")
    P(f"  average correction {np.nanmean(base['corr']):+.2f} pts; by position " + ", ".join(f"{p} {np.nanmean(base['corr'][(df.pos == p).values]):+.2f}" for p in ("QB", "RB", "WR", "TE")))

    # ---- 2 correlations with the residual ----
    P("\n=== 2. correlation of each feature with actual - HAND (all rows | QB RB WR TE) ===")
    cand = F + [c for g in ("usage", "prior", "team", "coach", "vacancy", "prospect", "env", "matchup", "oline") for c in groups[g] if c in ctx.columns and c not in F]
    for c in cand:
        if c not in df.columns:
            df[c] = pd.to_numeric(ctx[c], errors="coerce").values
    rows = []
    for c in cand:
        x = pd.to_numeric(df[c], errors="coerce")
        def r_(mask):
            ok = mask & x.notna()
            return float(np.corrcoef(x[ok], df.res[ok])[0, 1]) if ok.sum() > 200 and x[ok].std() > 0 else np.nan
        rr = {"feature": c, "all": r_(pd.Series(True, index=df.index))}
        for p in ("QB", "RB", "WR", "TE"):
            rr[p] = r_(df.pos == p)
        rows.append(rr)
    rows.sort(key=lambda r: -abs(r["all"]) if pd.notna(r["all"]) else 0)
    for rr in rows[:25]:
        P(f"  {rr['feature']:18s} r {rr['all']:+.3f} | " + " ".join(f"{p} {rr[p]:+.3f}" if pd.notna(rr[p]) else f"{p}   -  " for p in ("QB", "RB", "WR", "TE")) + ("" if rr["feature"] in F else "   (not in shadow)"))
    RES["corr"] = [{k: (round(v, 4) if isinstance(v, float) and pd.notna(v) else (v if not isinstance(v, float) else None)) for k, v in rr.items()} for rr in rows[:30]]

    # ---- 3 SHAP attribution ----
    P("\n=== 3. what drives the shadow (out-of-fold SHAP: mean |pts|, direction = r(feature, its contribution)) ===")
    C = base["C"]
    shap = []
    for i, c in enumerate(F):
        x = pd.to_numeric(df[c], errors="coerce"); ok = x.notna().values & np.isfinite(C[:, i])
        d = float(np.corrcoef(x[ok], C[ok, i])[0, 1]) if ok.sum() > 200 and x[ok].std() > 0 and C[ok, i].std() > 0 else np.nan
        shap.append({"feature": c, "meanAbs": float(np.mean(np.abs(C[:, i]))), "dir": d})
    shap.sort(key=lambda s: -s["meanAbs"])
    tot = sum(s["meanAbs"] for s in shap)
    for s in shap[:15]:
        P(f"  {s['feature']:16s} {s['meanAbs']:.3f} pts ({100*s['meanAbs']/tot:4.1f}%)  direction {s['dir']:+.2f}" if pd.notna(s["dir"]) else f"  {s['feature']:16s} {s['meanAbs']:.3f}")
    RES["shap"] = [{"feature": s["feature"], "meanAbs": round(s["meanAbs"], 4), "share": round(s["meanAbs"] / tot, 4), "dir": round(s["dir"], 3) if pd.notna(s["dir"]) else None} for s in shap]
    RES["quintiles"] = []
    for s in shap[:6]:
        c = s["feature"]; x = pd.to_numeric(df[c], errors="coerce")
        ok = x.notna()
        try:
            qb = pd.qcut(x[ok].rank(method="first"), 5, labels=False)
        except ValueError:
            continue
        parts = []
        for q in range(5):
            m = ok.copy(); m[ok] = (qb == q).values
            parts.append({"q": q + 1, "lo": round(float(x[m].min()), 2), "hi": round(float(x[m].max()), 2), "actOverHand": round(float(df.act[m].mean() / df.HAND[m].mean()), 3),
                          "contrib": round(float(C[m.values, F.index(c)].mean()), 3)})
        RES["quintiles"].append({"feature": c, "bins": parts})
        P(f"  {c}: " + " | ".join(f"Q{b['q']} [{b['lo']}..{b['hi']}] act/HAND {b['actOverHand']} shap {b['contrib']:+.2f}" for b in parts))

    # ---- 4 hand-layer audit ----
    P("\n=== 4. hand-layer audit: actual / HAND by layer bins (rows where the layer is active; REL = / same-position rows where it is not) ===")
    audits = [("TD luck adj", "td_luck_adj", [(-9, -0.5), (-0.5, -0.1), (-0.1, 0.1), (0.1, 0.5), (0.5, 9)]),
              ("opportunity pool", "pool_mult", [(1.0001, 1.05), (1.05, 1.15), (1.15, 1.35), (1.35, 9)]),
              ("banged cond", "cond_mult", [(0.85, 0.9), (0.9, 0.95), (0.95, 0.9999)]),
              ("rookie level", "rookie_mult", [(1.0001, 9)]),
              ("wind dock", "weather_mult", [(0, 0.95), (0.95, 0.9999)]),
              ("snap trend", "snapmult", [(0, 0.9), (0.9, 0.97), (1.03, 1.1), (1.1, 9)]),
              ("vegas", "veg", [(0, 0.9), (0.9, 0.97), (1.03, 1.1), (1.1, 9)]),
              ("RB usage blend (usage/blend)", "usage_ratio", [(0, 0.8), (0.8, 1.0), (1.0, 1.25), (1.25, 9)])]
    df["usage_ratio"] = df.usage_half / df.blend
    for lab, col, bins in audits:
        for lo, hi in bins:
            m = (df[col] > lo) & (df[col] <= hi) if col != "rookie_mult" else (df[col] > lo)
            if m.sum() < 80:
                continue
            ratio = float(df.act[m].mean() / df.HAND[m].mean())
            if col in ("veg", "snapmult"):
                neutral = (df[col] - 1).abs() <= 0.03
            elif col == "usage_ratio":
                neutral = df[col].isna()
            else:
                neutral = df[col].isna() | ((df[col] - (0 if col == "td_luck_adj" else 1)).abs() < 1e-9)
            relp = []
            for p in df.pos[m].unique():
                mp = m & (df.pos == p); np_ = neutral & (df.pos == p)
                if mp.sum() >= 30 and np_.sum() >= 30:
                    relp.append((mp.sum(), (df.act[mp].mean() / df.HAND[mp].mean()) / (df.act[np_].mean() / df.HAND[np_].mean())))
            rel = sum(n * r for n, r in relp) / sum(n for n, _ in relp) if relp else np.nan
            RES["audit"].append({"layer": lab, "bin": f"{lo}..{hi}", "n": int(m.sum()), "actOverHand": round(ratio, 3), "rel": round(float(rel), 3) if pd.notna(rel) else None})
            P(f"  {lab:28s} {lo:>7}..{hi:<7} n {int(m.sum()):5d} act/HAND {ratio:.3f} REL {rel:.3f}")

    # ---- 5 sweeps ----
    P("\n=== 5. sweeps (vs HAND; current shadow LOYO {:+.2f}% / forward {:+.2f}%) ===".format(base["loyo"], base["fwd"]))
    def run(label, feats, params=None, per_pos=False, kind="sweep"):
        r = evaluate(df, feats, params, per_pos)
        rec = {"label": label, "kind": kind, "features": len(feats), "loyo": r["loyo"], "wins": r["wins"], "fwd": r["fwd"], "fwdWins": r["fwdWins"],
               "better": bool(r["loyo"] < base["loyo"] and r["fwd"] < base["fwd"])}
        RES["sweeps"].append(rec)
        P(f"  {label:46s} LOYO {r['loyo']:+.2f}% ({r['wins']}/7) forward {r['fwd']:+.2f}% ({r['fwdWins']}/5){'  <- beats current on both' if rec['better'] else ''} ({time.time()-T0:.0f}s)")
        return rec
    for nl, md, l2 in ((7, 200, 20), (31, 200, 20), (15, 100, 20), (15, 400, 20), (15, 200, 5), (15, 200, 60), (7, 400, 60)):
        run(f"leaves {nl}, min rows {md}, L2 {l2}", F, dict(BASE_PARAMS, num_leaves=nl, min_data_in_leaf=md, lambda_l2=float(l2)))
    run("Huber loss (delta 8)", F, dict(BASE_PARAMS, objective="huber", alpha=8.0))
    run("feature_fraction .5", F, dict(BASE_PARAMS, feature_fraction=0.5))
    run("separate model per position", F, per_pos=True)

    P("\n  drop-one-feature (LOYO only; + = the feature helps):")
    for c in F:
        fs = [x for x in F if x != c]
        r = evaluate(df, fs, forward=False)
        RES["dropone"].append({"feature": c, "loyo": r["loyo"], "worth": round(r["loyo"] - base["loyo"], 3)})
    RES["dropone"].sort(key=lambda r: r["worth"])
    P("  " + " | ".join(f"{r['feature']} {r['worth']:+.2f}" for r in RES["dropone"]))
    hurt = [r["feature"] for r in RES["dropone"] if r["worth"] < -0.02]
    if hurt:
        run(f"pruned: without {', '.join(hurt)}", [x for x in F if x not in hurt], kind="prune")

    P("\n  add context groups (would need live builders):")
    for g in ("usage", "prior", "team", "coach", "vacancy", "prospect", "matchup", "oline"):
        add = [c for c in groups[g] if c in df.columns and c not in F]
        if add:
            run(f"+ {g} ({len(add)})", F + add, kind="group")

    better = [s for s in RES["sweeps"] if s["better"]]
    best = min(better, key=lambda s: s["loyo"] + s["fwd"]) if better else None
    RES["best"] = best
    RES["updated"] = time.strftime("%Y-%m-%d %H:%M"); RES["n"] = int(len(df))
    top_c = RES["corr"][0]; top_s = RES["shap"][0]
    RES["summary"] = (f"Current shadow LOYO {base['loyo']:+.2f}% / forward {base['fwd']:+.2f}% vs the hand stack. Level vs signal: " +
                      "; ".join(f"{x['label'].split(' (')[0]} {x['pct']:+.2f}%" for x in RES["levelSignal"]) +
                      f". Biggest raw correlation with the miss: {top_c['feature']} (r {top_c['all']:+.3f}); biggest model driver: {top_s['feature']} ({100*top_s['share']:.0f}% of attribution). " +
                      (f"Best tweak on both LOYO and forward: {best['label']} ({best['loyo']:+.2f}% / {best['fwd']:+.2f}%)." if best else "No tweak beats the current shadow on both LOYO and forward."))
    with open(os.path.join(HERE, "data", "learned_shadow_tuning.js"), "w", encoding="utf-8") as fh:
        fh.write("// built by tune_learned_shadow.py - what drives the learned shadow and which tweaks improve it; ZONES tab\n")
        fh.write("window.SIM_LSTUNE = "); json.dump(RES, fh, separators=(",", ":"), default=lambda o: None); fh.write(";\n")
    P(f"\nwrote data/learned_shadow_tuning.js: {RES['summary']}")
    P(f"done ({time.time()-T0:.0f}s)")


if __name__ == "__main__":
    main()
