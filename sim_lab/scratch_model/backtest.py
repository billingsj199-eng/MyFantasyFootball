#!/usr/bin/env python3
"""
backtest.py - 2026 Weeks 1-7, as-of: scratch models vs the LIVE Sim Lab number that was actually published vs the books.

Inputs
  cache/asof_2026.parquet          as-of features (asof.py) + actual half-PPR from pbp
  out/params.json, out/gbm_*.txt   models fitted on 2017-2025 (fit_history.py) - nothing here is fitted on 2026
  sim_lab/data/snapshots/simlab_snapshot_w{N}.json   the live lock: mean (half-PPR), propMean, prop lines at lock, implied
  accuracy/data/w{N}.json          site consensus locks (Sleeper / ESPN / CBS / FP, full PPR) + rec comps for the half-PPR conversion

Universe: players the live sim published a number for AND who played (actual exists). Everything graded half-PPR.
Market = consensus of the books' lines at lock, FACE VALUE (house rule), anytime-TD devigged 1.06 -> Poisson mean.
Blend weights (scratch x market) are leave-one-week-out so the blended number is honest too.

Outputs out/bt_rows.csv (every graded row with every model), out/bt_tables.md (the report tables), out/disagree.csv.
"""
import os, sys, json, math
from collections import defaultdict
import numpy as np, pandas as pd
from features import norm
from model import (struct_predict, apply_cal, gbm_predict, grade, grade_table, importance, band_of, adp_ppg, POS4, HERE, GBM_FEATS, gbm_frame)
import lightgbm as lgb

OUT = os.path.join(HERE, "out"); CACHE = os.path.join(HERE, "cache")
SNAP = r"E:\MyFantasyFootball\sim_lab\data\snapshots"
ACC = r"E:\MyFantasyFootball\MyFantasyFootball Files\accuracy\data"
WEEKS = list(range(1, 8))
NAME_ALIAS = {"kenny gainwell": "kenneth gainwell", "chig okonkwo": "chigoziem okonkwo", "josh palmer": "joshua palmer",
              "hollywood brown": "marquise brown", "gabe davis": "gabriel davis", "cam ward": "cameron ward", "mike woods": "michael woods",
              "ken walker": "kenneth walker", "jaxson smith njigba": "jaxon smith njigba", "tim patrick": "timothy patrick",
              "aj barner": "aj barner", "demario douglas": "demario douglas"}


def amer_prob(o):
    o = float(o)
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def market_points(lines, pos):
    """face-value half-PPR mean from the books' lines at lock. None unless the position's core lines are all there."""
    if not lines:
        return None, 0
    stat = defaultdict(list); atd = []
    for book, L in lines.items():
        if not isinstance(L, dict):
            continue
        for k in ("py", "ptd", "ry", "rec", "rcy", "int"):
            if k in L and L[k] is not None:
                stat[k].append(float(L[k]))
        if L.get("atd") is not None:
            atd.append(amer_prob(L["atd"]))
    med = {k: float(np.median(v)) for k, v in stat.items()}
    nb = max((len(v) for v in stat.values()), default=0)
    lam = None
    if atd:
        p = min(0.97, float(np.median(atd)) / 1.06)
        lam = -math.log(1 - p)
    if pos == "QB":
        if "py" not in med or "ptd" not in med:
            return None, nb
        ints = med.get("int", 0.5)
        e_int = 0.75 if ints <= 0.5 else ints          # a 0.5 line is the usual; ~0.75 expected
        rtd = lam if lam is not None else 0.15
        return med["py"] * .04 + med["ptd"] * 4 - e_int * 2 + med.get("ry", 10.0) * .1 + rtd * 6, nb
    need = ("ry", "rec", "rcy") if pos == "RB" else ("rec", "rcy")
    if any(k not in med for k in need):
        return None, nb
    td = lam if lam is not None else (0.35 if pos == "RB" else 0.3)
    return med.get("ry", 0.0) * .1 + med["rec"] * .5 + med["rcy"] * .1 + td * 6, nb


def load_live():
    rows = []
    for w in WEEKS:
        d = json.load(open(os.path.join(SNAP, f"simlab_snapshot_w{w}.json"), encoding="utf-8"))
        for p in d["players"]:
            if p.get("pos") not in POS4:
                continue
            mk, nb = market_points(p.get("lines"), p["pos"])
            comps = p.get("comps") or {}
            rows.append(dict(week=w, key=NAME_ALIAS.get(norm(p["name"]), norm(p["name"])), pos=p["pos"], tm=p.get("tm"), live=p.get("mean"),
                             live_js=p.get("jsMean"), live_clay=p.get("clayMean"), live_prop=p.get("propMean"), live_nc=p.get("ncMean"),
                             prop_src=p.get("propSrc"), implied_live=p.get("implied"), market=mk, n_books=nb, rec_comp=comps.get("rec"),
                             bookcapped=int(bool(p.get("_bookCapped"))), live_p10=p.get("p10"), live_p90=p.get("p90")))
    return pd.DataFrame(rows)


def load_consensus():
    rows = []
    for w in WEEKS:
        d = json.load(open(os.path.join(ACC, f"w{w}.json"), encoding="utf-8"))
        for n, r in d["players"].items():
            s = r.get("site")
            if not s:
                continue
            vals = [x for x in s[:4] if isinstance(x, (int, float))]
            rows.append(dict(week=w, key=NAME_ALIAS.get(norm(n), norm(n)), pos=r["pos"], cons_ppr=float(np.mean(vals)) if vals else np.nan,
                             sleeper_ppr=s[0], espn_ppr=s[1], fp_ppr=s[3], act_tracker=r.get("act"),
                             sim_tracker=(r.get("sim") or [None])[0]))
    return pd.DataFrame(rows)


def load_models():
    P = json.load(open(os.path.join(OUT, "params.json")))
    gbm = {p: lgb.Booster(model_file=os.path.join(OUT, f"gbm_{p}.txt")) for p in POS4}
    gbm2 = {p: lgb.Booster(model_file=os.path.join(OUT, f"gbm2_{p}.txt")) for p in POS4}
    return P, gbm, gbm2


def lowo_blend(df, a, b, w_grid=np.linspace(0, 1, 21)):
    """leave-one-week-out blend weight per position: w*a + (1-w)*b minimising importance-weighted MSE on the other weeks"""
    out = np.full(len(df), np.nan); chosen = {}
    wt = df["w"].values; act = df.act.values
    for pos in POS4:
        for wk in WEEKS:
            tr = (df.pos.values == pos) & (df.week.values != wk) & ~np.isnan(a) & ~np.isnan(b)
            te = (df.pos.values == pos) & (df.week.values == wk)
            if tr.sum() < 20:
                continue
            best = min(w_grid, key=lambda w: np.average((w * a[tr] + (1 - w) * b[tr] - act[tr]) ** 2, weights=wt[tr]))
            chosen[(pos, wk)] = float(best)
            out[te] = best * a[te] + (1 - best) * b[te]
    return out, chosen


def main():
    P, gbm, gbm2 = load_models()
    curve = {k: tuple(v) for k, v in P["curve"].items()}
    df = pd.read_parquet(os.path.join(CACHE, "asof_2026.parquet"))
    df = df[df.week.isin(WEEKS)].reset_index(drop=True)
    df["key"] = [NAME_ALIAS.get(norm(n), norm(n)) for n in df.name]
    raw, parts = struct_predict(df, P["prm"], curve, P["tcoef"], P["L"])
    df["STRUCT"] = apply_cal(df, raw, {k: tuple(v) for k, v in P["cal"].items()})
    df["GBM"] = gbm_predict(df, gbm, curve, None)
    df["STACK"] = gbm_predict(df, gbm2, curve, df.STRUCT.values)
    df["exp_rec"] = parts["exp_tgt"] * np.array([P["L"][p]["cr"] for p in df.pos])
    live = load_live(); cons = load_consensus()
    m = df.merge(live, on=["week", "key", "pos"], how="inner").merge(cons, on=["week", "key", "pos"], how="left")
    unmatched = live[~live.set_index(["week", "key", "pos"]).index.isin(m.set_index(["week", "key", "pos"]).index)]
    print(f"live rows {len(live)}, matched to a played as-of row {len(m)}, live rows without a match {len(unmatched)} "
          f"(did not play / name mismatch) e.g. {unmatched.key.head(12).tolist()}")
    m = m[m.live.notna()].reset_index(drop=True)
    # consensus to half-PPR using the sim's expected receptions (the tracker's conversion, reversed)
    rec = np.where(m.rec_comp.notna(), m.rec_comp, m.exp_rec)
    m["CONS"] = m.cons_ppr - 0.5 * rec
    m["SLEEPER"] = m.sleeper_ppr - 0.5 * rec
    m["LIVE"] = m.live.astype(float); m["MARKET"] = m.market.astype(float)
    m["w"] = importance(m, curve); m["band"] = band_of(m.adp.values)
    # market blends, leave-one-week-out
    m["STRUCT+MKT"], wsm = lowo_blend(m, m.MARKET.values, m.STRUCT.values)
    m["GBM+MKT"], wgm = lowo_blend(m, m.MARKET.values, m.GBM.values)
    m["STACK+MKT"], wkm = lowo_blend(m, m.MARKET.values, m.STACK.values)
    m["LIVE+MKT"], wlm = lowo_blend(m, m.MARKET.values, m.LIVE.values)
    m["STRUCT+LIVE"], wsl = lowo_blend(m, m.STRUCT.values, m.LIVE.values)
    m["STACK+LIVE"], wkl = lowo_blend(m, m.STACK.values, m.LIVE.values)
    m["STRUCT+LIVE+MKT"], _ = lowo_blend(m, m["STRUCT+LIVE"].values, m.MARKET.values)
    m["GBM+LIVE+MKT"], _ = lowo_blend(m, m["GBM+MKT"].values, m.LIVE.values)
    m["GBM+LIVE"], wgl = lowo_blend(m, m.GBM.values, m.LIVE.values)
    m["STRUCT+CONS"], _ = lowo_blend(m, m.STRUCT.values, m.CONS.values)
    m["CONS+MKT"], _ = lowo_blend(m, m.CONS.values, m.MARKET.values)
    m.to_csv(os.path.join(OUT, "bt_rows.csv"), index=False)
    # sanity: our pbp actual vs the tracker's actual
    ok = m.act_tracker.notna()
    print("actual check: ppr(pbp) vs tracker act corr", round(np.corrcoef(m.act_ppr[ok], m.act_tracker[ok])[0, 1], 4),
          "mean |diff|", round(float(np.mean(np.abs(m.act_ppr[ok] - m.act_tracker[ok]))), 3))
    ok2 = m.sim_tracker.notna()
    print("live check: snapshot mean vs tracker sim mean |diff|", round(float(np.mean(np.abs(m.live[ok2] - m.sim_tracker[ok2]))), 3))

    MODELS = ["LIVE", "STRUCT", "GBM", "STACK", "MARKET", "CONS", "STRUCT+MKT", "GBM+MKT", "STACK+MKT", "LIVE+MKT", "STRUCT+LIVE", "GBM+LIVE",
              "STACK+LIVE", "STRUCT+LIVE+MKT", "GBM+LIVE+MKT", "CONS+MKT"]
    L = []
    def P_(s=""):
        print(s); L.append(s)
    P_("# Scratch-model backtest, 2026 Weeks 1-7 (half-PPR, as-of)\n")
    P_(f"Universe: {len(m)} player-weeks the live Sim Lab published and who played; market available for {int(m.MARKET.notna().sum())}, "
       f"consensus for {int(m.CONS.notna().sum())}. Importance weights = preseason ADP curve cubed (Jack's rule).\n")
    P_("Blend weights (STRUCT+MKT etc.) are leave-one-week-out, so every blended number is as honest as the pure ones.\n")

    def table(sub, title, models=MODELS, min_rows=8):
        P_(f"\n## {title}  (n={len(sub)})\n")
        P_("| model | MAE (wtd) | MAE raw | bias | Spearman | top-6 | top-12 | top-24 | pair acc | pairs |")
        P_("|---|---|---|---|---|---|---|---|---|---|")
        res = {}
        for lab in models:
            if lab not in sub:
                continue
            p = sub[lab].values.astype(float)
            if np.isnan(p).all():
                continue
            r = grade(sub, p, sub.w.values, min_rows=min_rows, label=lab)
            res[lab] = r
            P_(f"| {lab} | {r['mae']:.3f} | {r['mae_raw']:.3f} | {r['bias']:+.2f} | {r['rho']:.3f} | {r['top6']:.3f} | {r['top12']:.3f} | {r['top24']:.3f} | {r['pair_acc']:.3f} | {r['pairs']} |")
        return res

    # 1. headline: common universe where every model has a number (market rows)
    mk = m[m.MARKET.notna()].reset_index(drop=True)
    table(mk[mk.adp <= 150], "HEADLINE: top-150 ADP, rows where the books posted full lines (live + scratch + market)", [x for x in MODELS if "CONS" not in x])
    table(mk, "All rows where the books posted full lines", [x for x in MODELS if "CONS" not in x])
    mc = m[m.MARKET.notna() & m.CONS.notna()].reset_index(drop=True)
    table(mc[mc.adp <= 150], "Site consensus comparison: top-150 rows with lines AND a consensus lock (no W5 - the site locks were not archived that week)", MODELS)
    # 2. full live universe (no market requirement) - pure models only
    pure = ["LIVE", "STRUCT", "GBM", "STACK", "CONS", "STRUCT+LIVE", "GBM+LIVE", "STACK+LIVE"]
    table(m[m.adp <= 150], "Full live universe, top-150 ADP (no market requirement)", pure)
    table(m, "Full live universe, all rows", pure)
    # 3. by position (top-150, market rows)
    for pos in POS4:
        table(mk[(mk.pos == pos) & (mk.adp <= 150)], f"{pos}, top-150, full-line rows", MODELS)
    # 4. by ADP band
    for band, lo, hi in (("1-12", 0, 12), ("13-30", 12, 30), ("31-60", 30, 60), ("61-100", 60, 100), ("101-150", 100, 150)):
        sub = m[(m.adp > lo) & (m.adp <= hi)]
        table(sub, f"ADP band {band} (all live rows; market models on the subset with lines)", pure + ["MARKET", "STRUCT+MKT", "LIVE+MKT", "STRUCT+LIVE+MKT"], min_rows=4)
    # 5. by week
    P_("\n## By week, top-150 (weighted MAE / Spearman)\n")
    P_("| week | n | LIVE | STRUCT | GBM | STACK | MARKET | CONS | STRUCT+LIVE | STRUCT+LIVE+MKT |")
    P_("|---|---|---|---|---|---|---|---|---|---|")
    for wk in WEEKS:
        sub = m[(m.week == wk) & (m.adp <= 150)]
        cells = []
        for lab in ("LIVE", "STRUCT", "GBM", "STACK", "MARKET", "CONS", "STRUCT+LIVE", "STRUCT+LIVE+MKT"):
            r = grade(sub, sub[lab].values.astype(float), sub.w.values, label=lab)
            cells.append(f"{r['mae']:.2f} / {r['rho']:.3f}")
        P_(f"| {wk} | {len(sub)} | " + " | ".join(cells) + " |")
    # 6. who is right when STRUCT and LIVE disagree
    P_("\n## Disagreements: scratch STRUCT vs LIVE (top-150, |gap| >= 3 pts)\n")
    d = m[(m.adp <= 150)].copy()
    d["gap"] = d.STRUCT - d.LIVE
    d["struct_closer"] = (np.abs(d.STRUCT - d.act) < np.abs(d.LIVE - d.act)).astype(int)
    big = d[np.abs(d.gap) >= 3]
    P_("| cut | n | STRUCT closer | mean |err| STRUCT | mean |err| LIVE | actual vs midpoint (+ = STRUCT side) |")
    P_("|---|---|---|---|---|---|")
    def dcut(sub, name):
        if len(sub) == 0:
            return
        side = np.sign(sub.gap) * (sub.act - (sub.STRUCT + sub.LIVE) / 2)
        P_(f"| {name} | {len(sub)} | {sub.struct_closer.mean():.0%} | {np.mean(np.abs(sub.STRUCT - sub.act)):.2f} | {np.mean(np.abs(sub.LIVE - sub.act)):.2f} | {side.mean():+.2f} |")
    dcut(big, "all gaps >= 3"); dcut(big[big.gap > 0], "STRUCT higher"); dcut(big[big.gap < 0], "STRUCT lower")
    for pos in POS4:
        dcut(big[big.pos == pos], f"{pos}, all"); dcut(big[(big.pos == pos) & (big.gap > 0)], f"{pos}, STRUCT higher"); dcut(big[(big.pos == pos) & (big.gap < 0)], f"{pos}, STRUCT lower")
    for band in ("1-12", "13-30", "31-60", "61-100", "101-150"):
        dcut(big[big.band == band], f"ADP {band}")
    dcut(big[big.gs == "Questionable"], "Questionable"); dcut(big[big.vac_tsh >= 0.15], "teammate(s) out, vacated tgt share >= 15%")
    dcut(big[big.g == 0], "week 1 (no in-season games)"); dcut(big[big.g >= 3], "3+ games of evidence")
    P_("\nLargest 40 disagreements (top-150):\n")
    P_("| wk | player | pos | ADP | STRUCT | LIVE | MARKET | CONS | actual | closer |")
    P_("|---|---|---|---|---|---|---|---|---|---|")
    for r in big.reindex(np.abs(big.gap).sort_values(ascending=False).index).head(40).itertuples():
        mk_ = f"{r.MARKET:.1f}" if not np.isnan(r.MARKET) else "-"; cs = f"{r.CONS:.1f}" if not np.isnan(r.CONS) else "-"
        P_(f"| {r.week} | {r.name} | {r.pos} | {r.adp:.0f} | {r.STRUCT:.1f} | {r.LIVE:.1f} | {mk_} | {cs} | {r.act:.1f} | {'STRUCT' if r.struct_closer else 'LIVE'} |")
    big.sort_values("gap", key=np.abs, ascending=False)[["week", "name", "pos", "team", "opp", "adp", "STRUCT", "GBM", "LIVE", "MARKET", "CONS", "act", "gap", "struct_closer", "g", "gs", "vac_tsh"]].to_csv(os.path.join(OUT, "disagree.csv"), index=False)
    # 7. lineup decision test: start/sit pairs inside the top-24 by consensus where the two models order differently
    P_("\n## Start/sit decision test: same-position pairs where STRUCT and LIVE pick different starters\n")
    P_("Pairs drawn from the week's top-24 by live projection (top-12 QB/TE); both players played; the models disagree on order by >= 0.5 pt each way.\n")
    P_("| position | pairs | STRUCT right | LIVE right | MARKET right (when priced) | CONS right |")
    P_("|---|---|---|---|---|---|")
    tot = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    for (wk, pos), sub in m.groupby(["week", "pos"]):
        N = 12 if pos in ("QB", "TE") else 24
        sub = sub.sort_values("LIVE", ascending=False).head(N)
        rows_ = list(sub.itertuples())
        for i in range(len(rows_)):
            for j in range(i + 1, len(rows_)):
                a, b = rows_[i], rows_[j]
                ds = a.STRUCT - b.STRUCT; dl = a.LIVE - b.LIVE
                if ds * dl >= 0 or abs(ds) < 0.5 or abs(dl) < 0.5 or a.act == b.act:
                    continue
                truth = np.sign(a.act - b.act)
                t = tot[pos]; t[0] += 1
                t[1] += int(np.sign(ds) == truth); t[2] += int(np.sign(dl) == truth)
                if not (np.isnan(a.MARKET) or np.isnan(b.MARKET)) and abs(a.MARKET - b.MARKET) >= 0.01:
                    t[3] += 1; t[4] += int(np.sign(a.MARKET - b.MARKET) == truth)
                if not (np.isnan(a.CONS) or np.isnan(b.CONS)):
                    t[5] += int(np.sign(a.CONS - b.CONS) == truth)
    allp = [0] * 6
    for pos in POS4:
        t = tot[pos]
        for i in range(6):
            allp[i] += t[i]
        if t[0]:
            P_(f"| {pos} | {t[0]} | {t[1] / t[0]:.0%} | {t[2] / t[0]:.0%} | {t[4] / t[3]:.0%} (n={t[3]}) | {t[5] / t[0]:.0%} |" if t[3] else f"| {pos} | {t[0]} | {t[1] / t[0]:.0%} | {t[2] / t[0]:.0%} | - | {t[5] / t[0]:.0%} |")
    if allp[0]:
        P_(f"| ALL | {allp[0]} | {allp[1] / allp[0]:.0%} | {allp[2] / allp[0]:.0%} | {allp[4] / max(1, allp[3]):.0%} (n={allp[3]}) | {allp[5] / allp[0]:.0%} |")
    # 8. blend weights chosen
    P_("\n## Leave-one-week-out blend weights (weight on the FIRST model)\n")
    for name, ch in (("STRUCT+MKT (w on MARKET)", wsm), ("LIVE+MKT (w on MARKET)", wlm), ("STRUCT+LIVE (w on STRUCT)", wsl), ("GBM+LIVE (w on GBM)", wgl), ("STACK+LIVE (w on STACK)", wkl)):
        P_(f"- {name}: " + ", ".join(f"{pos} {np.mean([v for (p_, _), v in ch.items() if p_ == pos]):.2f}" for pos in POS4))
    # 9. the live model's own pieces for context
    P_("\n## Live engine pieces (top-150, full-line rows) for context\n")
    sub = mk[mk.adp <= 150].copy()
    for lab, col in (("live clean JS (jsMean)", "live_js"), ("live Clay-free shadow (ncMean)", "live_nc"), ("live propMean (anchored)", "live_prop"), ("live Clay (clayMean)", "live_clay")):
        p = sub[col].values.astype(float)
        if np.isnan(p).all():
            continue
        r = grade(sub, p, sub.w.values, label=lab)
        P_(f"- {lab}: MAE {r['mae']:.3f} rho {r['rho']:.3f} pair {r['pair_acc']:.3f} (n {r['n']})")
    open(os.path.join(OUT, "bt_tables.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\nwrote out/bt_tables.md, out/bt_rows.csv, out/disagree.csv")


if __name__ == "__main__":
    main()
