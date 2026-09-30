#!/usr/bin/env python3
"""
SEASON-LONG HARNESS: can a Clay-free preseason prior beat Clay's season sheet? (2026-09-16)

Jack: "lets build the season long first and try to beat out clay with all the data we have including the advanced
data." One row per player-season 2019-25 on the Clay pool (his sheet >= 40 pts), target = the player's ACTUAL
full-season half-PPR points per game over the games he played (>= 4 games), everything on the prediction side known
before week 1. Clay's number is his season points / his projected games (fair per-game, not /17).
Clay-free candidates, all walk-forward (leave-one-year-out for the constants and the learned fits; forward
2021-25 fit on earlier seasons only):
  history      0.5 x 3-yr weighted PPG + 0.5 x last-8, age curve (the shadow's own prior pieces)
  shadow       the weekly shadow's preseason prior (history + opportunity + ADP market blend + string docks)
  market       the ADP curve alone (FFC preseason ADP, half-PPR fill)
  ridge basic  ADP, history, age, experience, draft pick, week-1 string, team change, prior-yr PPG / games
  ridge +ctx   + prior-yr target / carry share, xFP per game, team pass rate + plays, new HC / playcaller and the
               playcaller's tendencies, JM prospect score, OL pass-block / run-block grades (ctx_features.parquet)
  ridge +adv   + prior-yr PFF: route rate, YPRR, TPRR, aDOT, route / offense grade, slot / wide / inline rate, YAC,
               drops, contested catches, routes, targets; RB: YPA, YCO, elusive, breakaway, run grade, gap share
  boosted      gradient boosting on the full set (depth 3, 200 trees, leaf 20)
  ensembles    ridge +adv averaged with the market curve; the learned model averaged with Clay (information only)
Grades per position and pooled: games-weighted MSE of PPG vs Clay, seasons the candidate wins of 7, Spearman rank
correlation inside each season x position, and top-24 hit rate. Log season_long_backtest.log; results ->
data/season_long_backtest.js (SIM_SEASON_BT), ZONES tab.
"""
import json, os, sys, time, warnings
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import research_clay_vs_shadow as CS
import bt_common as B
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "season_long_backtest.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

YEARS, POS4 = NW.YEARS, NW.POS4
MIN_G = 4
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "models": [], "byPos": {}, "forward": [], "features": {}, "n": {}}

PFF_REC = ["route_rate_py", "yprr_py", "tprr_py", "adot_py", "grade_route_py", "grade_off_py", "slot_py", "wide_py", "inline_py", "yac_py", "drop_py", "contested_py", "routes_py", "targets_py"]
PFF_RUSH = ["ypa_py", "yco_py", "elusive_py", "breakaway_py", "grade_run_py", "gap_share_py", "rb_routes_py", "rb_yprr_py"]
CTX = ["tgt_sh_py", "car_sh_py", "xfp_pg_py", "g_py", "team_change", "proe_py", "plays_pg_py", "new_hc", "new_pc", "pc_seasons", "pc_proe", "pc_rb_tgt", "pc_te_tgt", "pc_rb1_car", "pc_plays_pg", "jm", "ol_pb_full", "ol_rb_full"]
BASIC = ["ladp", "no_adp", "hist", "h3", "l8", "age", "exp", "rookie", "lpick", "str1", "str2", "str3", "nostr", "mover", "oppcal", "yr2_late"]


def load_pff():
    pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "pff_id"])
    pff2g = {int(r.pff_id): r.gsis_id for r in pl.itertuples(index=False) if pd.notna(r.pff_id) and isinstance(r.gsis_id, str)}
    rec, rush = {}, {}
    for Y in range(2018, 2026):
        fr = os.path.join(B.CACHE, "pff", f"pff_receiving_{Y}.csv"); fu = os.path.join(B.CACHE, "pff", f"pff_rushing_{Y}.csv")
        if os.path.exists(fr):
            d = pd.read_csv(fr)
            for r in d.itertuples(index=False):
                g = pff2g.get(int(r.player_id))
                if not g or (r.routes or 0) < 50: continue
                rec[(Y, g)] = {"route_rate_py": r.route_rate, "yprr_py": r.yprr, "tprr_py": (r.targets / r.routes) if r.routes else np.nan, "adot_py": r.avg_depth_of_target, "grade_route_py": r.grades_pass_route, "grade_off_py": r.grades_offense,
                               "slot_py": r.slot_rate, "wide_py": r.wide_rate, "inline_py": r.inline_rate, "yac_py": r.yards_after_catch_per_reception, "drop_py": r.drop_rate, "contested_py": r.contested_catch_rate, "routes_py": r.routes, "targets_py": r.targets}
        if os.path.exists(fu):
            d = pd.read_csv(fu)
            for r in d.itertuples(index=False):
                g = pff2g.get(int(r.player_id))
                if not g or (r.attempts or 0) < 40: continue
                ga, za = (r.gap_attempts or 0), (r.zone_attempts or 0)
                rush[(Y, g)] = {"ypa_py": r.ypa, "yco_py": r.yco_attempt, "elusive_py": r.elusive_rating, "breakaway_py": r.breakaway_percent, "grade_run_py": r.grades_run, "gap_share_py": ga / (ga + za) if (ga + za) else np.nan, "rb_routes_py": r.routes, "rb_yprr_py": r.yprr}
    return rec, rush


def build_table(return_F=False):
    F = CS.build_harness(); A = F["A"]
    clay_hist = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    df = pd.DataFrame({"year": A["year"], "name": A["name"], "pos": A["pos"], "team": A["team"], "pid": A["pid"], "wk": A["wk"], "act": A["act"], "g": A["g"],
                       "prior": F["prior"], "hist": F["hist"], "h3": A["h3"], "l8": A["l8"], "age": A["age"], "exp": A["exp"], "rookie": A["rookie"].astype(float), "pick": A["pick"], "mover": A["mover"].astype(float),
                       "oppcal": A["oppcal"], "adp": F["adp"], "adp_curve": F["adp_curve"], "strb": F["strb"], "late": F["late"], "fb_pos": F["fb_pos"]})
    first = df.sort_values("wk").groupby(["year", "name", "pos"]).first().reset_index()
    seas = df.groupby(["year", "name", "pos"]).agg(ppg=("act", "mean"), games=("act", "size")).reset_index()
    T = first.merge(seas, on=["year", "name", "pos"]); T = T[T.games >= MIN_G].copy()
    # Clay: fair per-game (pts / projected games), half-PPR; and the /17 form the weekly harness uses
    def clay_of(y, nm, key):
        c = clay_hist[str(int(y))].get(nm) or {}
        pts = max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0)
        if key == "gm": gm = c.get("gm") or 0; return pts / gm if gm >= 4 else np.nan
        return pts / (16 if y <= 2020 else 17)
    T["clay"] = [clay_of(y, nm, "gm") for y, nm in zip(T.year, T.name)]
    T["clay17"] = [clay_of(y, nm, "17") for y, nm in zip(T.year, T.name)]
    T = T[~T.clay.isna()].copy()
    # context features (week-2 row of ctx_features = prior-year / coach / OL / prospect vars, all preseason-known)
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet"), columns=["year", "name", "pos"] + CTX)
    C = C.sort_values("year").groupby(["year", "name", "pos"]).first().reset_index()
    T = T.merge(C, on=["year", "name", "pos"], how="left")
    # PFF prior year
    rec, rush = load_pff()
    for col in PFF_REC + PFF_RUSH: T[col] = np.nan
    for i, (y, pid) in enumerate(zip(T.year, T.pid)):
        if not isinstance(pid, str): continue
        a = rec.get((int(y) - 1, pid)); b = rush.get((int(y) - 1, pid))
        if a:
            for k, v in a.items(): T.iat[i, T.columns.get_loc(k)] = v
        if b:
            for k, v in b.items(): T.iat[i, T.columns.get_loc(k)] = v
    # derived basics
    T["ladp"] = np.log(np.where(T.adp.isna(), 181.0, T.adp)); T["no_adp"] = T.adp.isna().astype(float)
    T["lpick"] = np.log(np.where(T.pick.isna(), 262.0, T.pick))
    T["str1"] = (T.strb == 1).astype(float); T["str2"] = (T.strb == 2).astype(float); T["str3"] = (T.strb >= 3).astype(float); T["nostr"] = T.strb.isna().astype(float)
    T["yr2_late"] = np.where((T.exp == 1) & ~T.late.isna(), T.late, np.nan)
    T = T.reset_index(drop=True)
    return (T, F) if return_F else T


def wmse(pred, act, w):
    m = ~np.isnan(pred) & ~np.isnan(act)
    return float(np.sum(w[m] * (pred[m] - act[m]) ** 2) / np.sum(w[m]))


def fit_predict(T, feats, kind, train, test, alpha=10.0):
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import HistGradientBoostingRegressor
    X = T[feats].astype(float).values.copy(); y = T.ppg.values; w = T.games.values.astype(float)
    Xtr = X[train]; med = np.nanmedian(Xtr, axis=0); med = np.where(np.isnan(med), 0, med)
    miss_cols = [j for j in range(X.shape[1]) if np.isnan(Xtr[:, j]).mean() > 0.02]
    def prep(M):
        ind = np.isnan(M[:, miss_cols]).astype(float) if miss_cols else np.zeros((len(M), 0))
        Mf = np.where(np.isnan(M), med, M)
        return np.column_stack([Mf, ind])
    A_tr, A_te = prep(Xtr), prep(X[test])
    if kind == "ridge":
        mu, sd = A_tr.mean(0), A_tr.std(0); sd[sd == 0] = 1
        mdl = Ridge(alpha=alpha).fit((A_tr - mu) / sd, y[train], sample_weight=w[train])
        return np.maximum(0.5, mdl.predict((A_te - mu) / sd))
    mdl = HistGradientBoostingRegressor(max_iter=200, max_depth=3, learning_rate=0.05, min_samples_leaf=20, random_state=0).fit(A_tr, y[train], sample_weight=w[train])
    return np.maximum(0.5, mdl.predict(A_te))


def loyo(T, feats, kind, alpha=10.0):
    out = np.full(len(T), np.nan); pos, year = T.pos.values, T.year.values
    for ps in POS4:
        for y in YEARS:
            tr = (pos == ps) & (year != y); te = (pos == ps) & (year == y)
            if tr.sum() < 40 or not te.any(): continue
            out[te] = fit_predict(T, feats, kind, tr, te, alpha)
    return out


def forward(T, feats, kind, alpha=10.0):
    out = np.full(len(T), np.nan); pos, year = T.pos.values, T.year.values
    for ps in POS4:
        for y in YEARS[2:]:
            tr = (pos == ps) & (year < y); te = (pos == ps) & (year == y)
            if tr.sum() < 40 or not te.any(): continue
            out[te] = fit_predict(T, feats, kind, tr, te, alpha)
    return out


def grade(T, pred, base, label, mask=None, store=None):
    m = (np.ones(len(T), bool) if mask is None else mask) & ~np.isnan(pred) & ~np.isnan(base)
    act, w, year, pos = T.ppg.values, T.games.values.astype(float), T.year.values, T.pos.values
    e, eb = wmse(pred[m], act[m], w[m]), wmse(base[m], act[m], w[m])
    ys = [y for y in YEARS if (m & (year == y)).sum() >= 15]
    wins = sum(1 for y in ys if wmse(pred[m & (year == y)], act[m & (year == y)], w[m & (year == y)]) < wmse(base[m & (year == y)], act[m & (year == y)], w[m & (year == y)]))
    rho_p, rho_b, hit_p, hit_b, k = [], [], [], [], 0
    for y in YEARS:
        for ps in POS4:
            mm = m & (year == y) & (pos == ps)
            if mm.sum() < 12: continue
            rho_p.append(spearmanr(pred[mm], act[mm]).correlation); rho_b.append(spearmanr(base[mm], act[mm]).correlation)
            n_top = min(24 if ps != "TE" else 12, mm.sum() // 2)
            top_a = set(np.argsort(-act[mm])[:n_top]); hit_p.append(len(top_a & set(np.argsort(-pred[mm])[:n_top])) / n_top); hit_b.append(len(top_a & set(np.argsort(-base[mm])[:n_top])) / n_top)
    row = {"label": label, "n": int(m.sum()), "mse": round(e, 3), "mseClay": round(eb, 3), "pct": round((e / eb - 1) * 100, 2), "wins": int(wins), "years": len(ys),
           "rho": round(float(np.mean(rho_p)), 3), "rhoClay": round(float(np.mean(rho_b)), 3), "hit": round(float(np.mean(hit_p)), 3), "hitClay": round(float(np.mean(hit_b)), 3),
           "bias": round(float(np.sum(w[m] * act[m]) / np.sum(w[m] * pred[m])), 3)}
    P(f"  {label:34s} n={row['n']:4d} MSE {e:6.3f} vs Clay {eb:6.3f} ({row['pct']:+6.2f}%) wins {wins}/{len(ys)} | rho {row['rho']:.3f} vs {row['rhoClay']:.3f} | top-N hit {row['hit']:.3f} vs {row['hitClay']:.3f} | bias {row['bias']:.3f}")
    if store is not None: store.append(row)
    return row


def main():
    t0 = time.time()
    P("=== Season-long: Clay's sheet vs Clay-free preseason priors, 2019-25 (half-PPR PPG, >= 4 games) ===")
    T = build_table(); n = len(T)
    P(f"  {n} player-seasons | " + " ".join(f"{ps} {int((T.pos == ps).sum())}" for ps in POS4) + f" | Clay fair per-game available on all; features: ADP {int((~T.adp.isna()).sum())}, history {int((~T["hist"].isna()).sum())}, ctx {int((~T.tgt_sh_py.isna()).sum())}, PFF rec {int((~T.yprr_py.isna()).sum())}, PFF rush {int((~T.ypa_py.isna()).sum())}")
    RES["n"] = {ps: int((T.pos == ps).sum()) for ps in POS4}; RES["n"]["all"] = int(n)
    clay = T.clay.values
    # ---- simple priors ----
    hist_age = T.prior.values * 0 + np.nan
    hist_raw = T["hist"].values.copy()
    for i in range(n):
        if not np.isnan(hist_raw[i]): hist_age[i] = NW.age_adjust(T.pos.iat[i], hist_raw[i], T.age.iat[i])
    fbp = T.fb_pos.values
    cands = {"Clay /17 (weekly-harness form)": T.clay17.values, "history + age (shadow piece)": np.where(np.isnan(hist_age), fbp, hist_age),
             "shadow preseason prior": T.prior.values, "market: ADP curve": np.where(np.isnan(T.adp_curve.values), fbp, T.adp_curve.values),
             "0.5 shadow + 0.5 market": 0.5 * T.prior.values + 0.5 * np.where(np.isnan(T.adp_curve.values), fbp, T.adp_curve.values)}
    P("\n=== Hand priors (all walk-forward), pooled ===")
    for lab, v in cands.items(): grade(T, v, clay, lab, store=RES["models"])
    # ---- learned, LOYO ----
    SETS = {"ridge basic": BASIC, "ridge +ctx": BASIC + CTX, "ridge +adv (PFF)": BASIC + CTX + PFF_REC + PFF_RUSH}
    P("\n=== Learned priors, leave-one-year-out per position (features known before week 1) ===")
    preds = {}
    for lab, fs in SETS.items():
        best = None
        for a in (3.0, 10.0, 30.0, 100.0):
            pr = loyo(T, fs, "ridge", a); e = wmse(pr, T.ppg.values, T.games.values.astype(float))
            if best is None or e < best[0]: best = (e, a, pr)
        preds[lab] = best[2]; r = grade(T, best[2], clay, f"{lab} (alpha {best[1]:g})", store=RES["models"]); r["alpha"] = best[1]
    preds["boosted (all features)"] = loyo(T, BASIC + CTX + PFF_REC + PFF_RUSH, "gbm"); grade(T, preds["boosted (all features)"], clay, "boosted (all features)", store=RES["models"])
    mkt = cands["market: ADP curve"]
    preds["0.5 ridge +adv + 0.5 market"] = 0.5 * preds["ridge +adv (PFF)"] + 0.5 * mkt; grade(T, preds["0.5 ridge +adv + 0.5 market"], clay, "0.5 ridge +adv + 0.5 market", store=RES["models"])
    preds["0.5 ridge +adv + 0.5 boosted"] = 0.5 * preds["ridge +adv (PFF)"] + 0.5 * preds["boosted (all features)"]; grade(T, preds["0.5 ridge +adv + 0.5 boosted"], clay, "0.5 ridge +adv + 0.5 boosted", store=RES["models"])
    preds["0.5 learned + 0.5 Clay (info)"] = 0.5 * preds["ridge +adv (PFF)"] + 0.5 * clay; grade(T, preds["0.5 learned + 0.5 Clay (info)"], clay, "0.5 learned + 0.5 Clay (info only)", store=RES["models"])
    # ---- by position ----
    P("\n=== By position: best hand prior, ridge +adv, boosted, ensemble vs Clay ===")
    for ps in POS4:
        mk = (T.pos == ps).values; rows = []
        for lab in ("shadow preseason prior", "market: ADP curve"): grade(T, cands[lab], clay, f"{ps} {lab}", mask=mk, store=rows)
        for lab in ("ridge basic", "ridge +ctx", "ridge +adv (PFF)", "boosted (all features)", "0.5 ridge +adv + 0.5 market", "0.5 ridge +adv + 0.5 boosted"): grade(T, preds[lab], clay, f"{ps} {lab}", mask=mk, store=rows)
        RES["byPos"][ps] = rows
    # ---- segments: veterans vs rookies vs 2nd-year ----
    P("\n=== Segments (ridge basic vs Clay) ===")
    seg_rows = []
    for lab, mk in (("veterans (exp 2+)", (T.exp >= 2).values), ("2nd year", (T.exp == 1).values), ("rookies", (T.rookie == 1).values), ("top-60 ADP", (T.adp <= 60).values), ("ADP 61-180", ((T.adp > 60) & (T.adp <= 180)).values), ("no ADP", T.adp.isna().values)):
        grade(T, preds["ridge basic"], clay, f"ridge basic: {lab}", mask=mk, store=seg_rows)
    RES["segments"] = seg_rows
    # ---- forward ----
    P("\n=== Forward 2021-25 (fit on earlier seasons only) ===")
    for lab, fs, kind in (("ridge basic", BASIC, "ridge"), ("ridge +ctx", BASIC + CTX, "ridge"), ("ridge +adv (PFF)", BASIC + CTX + PFF_REC + PFF_RUSH, "ridge"), ("boosted (all features)", BASIC + CTX + PFF_REC + PFF_RUSH, "gbm")):
        alpha = next((r.get("alpha", 10.0) for r in RES["models"] if r["label"].startswith(lab)), 10.0)
        fw = forward(T, fs, kind, alpha); fm = (T.year >= YEARS[2]).values
        grade(T, fw, clay, f"forward {lab}", mask=fm, store=RES["forward"])
        if lab == "ridge +adv (PFF)": grade(T, 0.5 * fw + 0.5 * mkt, clay, "forward 0.5 ridge +adv + 0.5 market", mask=fm, store=RES["forward"])
        if lab == "ridge basic":
            for ps in POS4: grade(T, fw, clay, f"forward ridge basic, {ps}", mask=fm & (T.pos == ps).values, store=RES["forward"])
            for slab, smk in (("veterans (exp 2+)", (T.exp >= 2).values), ("rookies", (T.rookie == 1).values), ("top-60 ADP", (T.adp <= 60).values), ("no ADP", T.adp.isna().values)): grade(T, fw, clay, f"forward ridge basic, {slab}", mask=fm & smk, store=RES["forward"])
            grade(T, 0.5 * fw + 0.5 * clay, clay, "forward 0.5 ridge basic + 0.5 Clay (info)", mask=fm, store=RES["forward"])
    # ---- which features carry it: ridge +adv standardized coefficients, full fit per position ----
    from sklearn.linear_model import Ridge
    feats = BASIC + CTX + PFF_REC + PFF_RUSH
    for ps in POS4:
        mk = (T.pos == ps).values; X = T.loc[mk, feats].astype(float).values; y = T.ppg.values[mk]; w = T.games.values[mk].astype(float)
        med = np.nanmedian(X, axis=0); med = np.where(np.isnan(med), 0, med); Xf = np.where(np.isnan(X), med, X); mu, sd = Xf.mean(0), Xf.std(0); sd[sd == 0] = 1
        mdl = Ridge(alpha=10.0).fit((Xf - mu) / sd, y, sample_weight=w)
        top = sorted(zip(feats, mdl.coef_), key=lambda t: -abs(t[1]))[:10]
        RES["features"][ps] = [{"feat": f, "coef": round(float(c), 3)} for f, c in top]
        P(f"  {ps} strongest standardized ridge coefficients: " + ", ".join(f"{f} {c:+.2f}" for f, c in top))
    best_free = min([r for r in RES["models"] if "Clay" not in r["label"]], key=lambda r: r["mse"])
    RES["summary"] = (f"Season-long, {n} player-seasons: Clay games-weighted MSE {RES['models'][0]['mseClay']:.2f}. Best Clay-free = {best_free['label']} {best_free['pct']:+.1f}% vs Clay ({best_free['wins']}/{best_free['years']} seasons), rho {best_free['rho']:.3f} vs {best_free['rhoClay']:.3f}. "
                      + "; ".join(f"{r['label']} {r['pct']:+.1f}%" for r in RES["forward"]) + " (forward).")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "season_long_backtest.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_SEASON_BT = " + json.dumps(RES) + ";\n")
    T.to_parquet(os.path.join(HERE, "season_long_table.parquet"), index=False)
    P(f"wrote data/season_long_backtest.js + season_long_table.parquet ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
