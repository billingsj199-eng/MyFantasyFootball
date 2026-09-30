#!/usr/bin/env python3
"""
Two candidates from the signal ledger (Jack 2026-09-30: "go build the qb shrink and carry trend and backtest").

A  QB LEVEL SHRINK. Rest-of-season residuals correlate -.26 with a quarterback's attempts and -.15 with his
   level: the base over-projects high-level quarterbacks and under-projects low ones. Test a shrink of the
   projection toward the week's starting-QB mean:   pred = mu + k x (live - mu),  k picked leave-one-season-out.
   A within-position shrink is monotonic, so weekly ranks are untouched; the gain is in points. Also run the same
   test on RB / WR / TE to confirm it is a quarterback thing.
B  RB CARRY-SHARE TREND. Next-game residual correlates +.085 with car_trend (last-3-game share of team carries
   minus season share) on top of the snap trend. Test mult = clamp(1 + e x car_trend, .8, 1.25) stacked on the
   live stack (which already carries snapMult), e picked LOYO.

Base = ctx_features shipped (P=5 blend x Vegas x FPA) x the rebuilt live layers (ctx_live_layers: rookie, pool,
banged-up, weather, QB inheritance) + TD-luck; for B the snap-trend multiplier is in the base too.
Log qb_shrink_cartrend.log.
"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)

def load():
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet")).set_index(["year", "pid", "wk"])
    C = C.join(L[["td_luck_adj", "pool_mult", "rookie_mult", "cond_mult", "weather_mult", "qb_inherit_mult"]], on=["year", "pid", "wk"])
    lay = C.rookie_mult.fillna(1) * C.pool_mult.fillna(1) * C.cond_mult.fillna(1) * C.weather_mult.fillna(1) * C.qb_inherit_mult.fillna(1)
    C["live"] = (C.shipped * lay + C.td_luck_adj.fillna(0)).clip(lower=0.2)          # no snap trend
    C["live_s"] = (C.base2 * lay + C.td_luck_adj.fillna(0)).clip(lower=0.2)          # with the snap trend (base2 = shipped x snapmult)
    return C

def grade(d, pred, base, years, label, log):
    e0 = (d[base] - d.act) ** 2; e1 = (pred - d.act) ** 2
    w = sum(1 for y in years if (d.year == y).sum() >= 20 and e1[d.year == y].mean() < e0[d.year == y].mean())
    a0 = (d[base] - d.act).abs().mean(); a1 = (pred - d.act).abs().mean()
    log(f"  {label:44s} n={len(d):5d}  MSE {100*(e1.mean()/e0.mean()-1):+6.2f}% ({w}/{len(years)})  MAE {100*(a1/a0-1):+6.2f}%  bias {(d[base]-d.act).mean():+.2f} -> {(pred-d.act).mean():+.2f}")

def part_a(C, years, log):
    log("=== A. level shrink toward the week's positional mean, pred = mu + k (live - mu), k LOYO by MSE ===")
    KS = [1.0, 0.97, 0.94, 0.91, 0.88, 0.85, 0.82, 0.79]
    for pos, top in (("QB", 32), ("RB", 40), ("WR", 60), ("TE", 24)):
        d = C[(C.pos == pos) & (C.live >= 5) & (C.g >= 1)].copy()
        # mu = mean live of the top-N projected at the position that week
        mu = d.groupby(["year", "wk"]).live.apply(lambda s: s.nlargest(top).mean())
        d["mu"] = d.set_index(["year", "wk"]).index.map(mu)
        picks = []; pred = pd.Series(index=d.index, dtype=float)
        for y in years:
            tr = d[d.year != y]
            k = min(KS, key=lambda k: (((tr.mu + k * (tr.live - tr.mu)) - tr.act) ** 2).mean())
            picks.append(k); m = d.year == y; pred[m] = d.mu[m] + k * (d.live[m] - d.mu[m])
        d["pred"] = pred
        grade(d, d.pred, "live", years, f"{pos} shrink (held-out k picks {picks})", log)
        for lo, hi, lab in ((5, 12, "low tier"), (12, 18, "mid"), (18, 99, "top tier")):
            x = d[(d.live >= lo) & (d.live < hi)]
            if len(x) >= 100: log(f"      {lab:9s} n={len(x):4d}  actual/projected {x.act.sum()/x.live.sum():.3f} -> {x.act.sum()/x.pred.sum():.3f}")
    # QB: is the shrink really about attempts / level, or about the in-season evidence? compare a shrink of the PRIOR-only rows vs rows with 5+ games
    d = C[(C.pos == "QB") & (C.live >= 5)].copy()
    log("  QB, split by games played (actual/projected of the top tier, live): " + "  ".join(f"g {lo}-{hi}: {d[(d.g>=lo)&(d.g<=hi)&(d.live>=18)].act.sum()/d[(d.g>=lo)&(d.g<=hi)&(d.live>=18)].live.sum():.3f}" for lo, hi in ((1, 3), (4, 8), (9, 17))))

def part_a2(C, years, log):
    log("\n=== A2. QB: where does the shrink gain come from, and does a one-sided version (raise the floor, leave the top) keep it? ===")
    d = C[(C.pos == "QB") & (C.live >= 5) & (C.g >= 1)].copy()
    mu = d.groupby(["year", "wk"]).live.apply(lambda s: s.nlargest(32).mean()); d["mu"] = d.set_index(["year", "wk"]).index.map(mu)
    KS = [1.0, 0.94, 0.88, 0.82, 0.76, 0.70]
    def fit(dd, form):
        picks = []; pred = pd.Series(index=dd.index, dtype=float)
        for y in years:
            tr = dd[dd.year != y]
            k = min(KS, key=lambda k: ((form(tr, k) - tr.act) ** 2).mean()); picks.append(k)
            m = dd.year == y; pred[m] = form(dd[m], k)
        return pred, picks
    two = lambda x, k: x.mu + k * (x.live - x.mu)
    floor = lambda x, k: np.where(x.live < x.mu, x.mu + k * (x.live - x.mu), x.live)
    cap = lambda x, k: np.where(x.live > x.mu, x.mu + k * (x.live - x.mu), x.live)
    for lab, form in (("two-sided", two), ("floor only (below the mean)", floor), ("cap only (above the mean)", cap)):
        d["pred"], picks = fit(d, form)
        grade(d, d.pred, "live", years, f"{lab} k picks {picks}", log)
        for lo, hi, tl in ((5, 12, "low"), (12, 18, "mid"), (18, 99, "top")):
            x = d[(d.live >= lo) & (d.live < hi)]
            e0 = ((x.live - x.act) ** 2).mean(); e1 = ((x.pred - x.act) ** 2).mean()
            log(f"      {tl:4s} n={len(x):4d}  MSE {100*(e1/e0-1):+6.2f}%  actual/projected {x.act.sum()/x.live.sum():.3f} -> {x.act.sum()/x.pred.sum():.3f}")
    # who are the low-tier QBs? established starters vs fill-ins (games played entering the week)
    lo = d[d.live < 12]
    log("  low-tier QB rows by games played entering the week (actual/live): " + "  ".join(f"g={g}: {lo[lo.g==g].act.sum()/lo[lo.g==g].live.sum():.2f} (n={int((lo.g==g).sum())})" for g in (1, 2, 3, 4, 5)) + f"  g6+: {lo[lo.g>=6].act.sum()/lo[lo.g>=6].live.sum():.2f} (n={int((lo.g>=6).sum())})")
    log("  low-tier by prior (Clay per game): " + "  ".join(f"clay {a}-{b}: {lo[(lo.clay>=a)&(lo.clay<b)].act.sum()/lo[(lo.clay>=a)&(lo.clay<b)].live.sum():.2f} (n={int(((lo.clay>=a)&(lo.clay<b)).sum())})" for a, b in ((0, 6), (6, 10), (10, 14), (14, 30))))

def part_b(C, years, log):
    log("\n=== B. RB carry-share trend on top of the live stack incl. snap trend: mult = clamp(1 + e x car_trend, .8, 1.25), e LOYO ===")
    d = C[(C.pos == "RB") & (C.live_s >= 5) & C.car_trend.notna() & (C.g >= 2)].copy()
    ES = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25]
    f = lambda e: d.live_s * (1 + e * d.car_trend).clip(0.8, 1.25)
    picks = []; pred = pd.Series(index=d.index, dtype=float)
    for y in years:
        tr = d.year != y
        e = min(ES, key=lambda e: ((f(e)[tr] - d.act[tr]) ** 2).mean()); picks.append(e); pred[~tr] = f(e)[~tr]
    d["pred"] = pred
    grade(d, d.pred, "live_s", years, f"all RB rows (held-out e picks {picks})", log)
    for lo, hi, lab in ((-9, -0.05, "share falling 5+ pts"), (-0.05, 0.05, "steady"), (0.05, 9, "share rising 5+ pts")):
        x = d[(d.car_trend >= lo) & (d.car_trend < hi)]
        grade(x, x.pred, "live_s", years, f"   {lab} (actual/live {x.act.sum()/x.live_s.sum():.3f})", log)
    log("  pooled e sweep on all RB rows: " + "  ".join(f"e={e}: {100*(((f(e)-d.act)**2).mean()/((d.live_s-d.act)**2).mean()-1):+.2f}%" for e in ES))
    # does the carry trend add anything once the snap trend is in? compare correlations
    from scipy.stats import spearmanr
    log(f"  residual (actual - live incl. snap trend) vs car_trend: r {spearmanr(d.car_trend, d.act - d.live_s).correlation:+.3f}; vs snap trend: r {spearmanr(d.snap_trend.fillna(0), d.act - d.live_s).correlation:+.3f}")

def main():
    lf = open(os.path.join(HERE, "qb_shrink_cartrend.log"), "w", encoding="utf-8")
    def log(s=""):
        print(s); lf.write(s + "\n")
    C = load(); years = sorted(C.year.unique())
    part_a(C, years, log); part_a2(C, years, log); part_b(C, years, log); lf.close()

if __name__ == "__main__":
    main()
