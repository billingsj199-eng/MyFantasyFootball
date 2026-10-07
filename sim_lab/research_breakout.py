#!/usr/bin/env python3
"""
BREAKOUTS: does Clay's projected JUMP land, is it a position thing (TE later breakout), and is there a statistical
predictor of a breakout from the data on disk?  (Jack 2026-10-07: "are there certain types of players like tes that
maybe are just a position to have a later breakout that he projects a jump with improvement / maybe we can get past
data or find some statistical predictor of breakout?")  RESEARCH ONLY.

Rows: player-seasons 2019-25 on the Clay pool (backtest_season_long.build_table), with a prior season of 6+ games.
  prev      = his half-PPR points per game the season before (games played)
  clay      = Clay's preseason per-game number (fair per-game)
  act       = his actual points per game this season (6+ games)
  Clay JUMP = clay / prev >= 1.20       BREAKOUT = act / prev >= 1.25 and act >= positional floor (QB 16 RB 10 WR 10 TE 8)
  1  by position: how often Clay projects a jump, how often it lands (precision), how many breakouts he catches
     (recall), act / clay for jump players vs the rest
  2  by experience year: breakout rate, Clay's jump rate, hit rate - is TE the late-breakout position?
  3  one signal at a time (prior-year usage, late-season trend, routes, draft capital, age, market, playcaller):
     breakout rate by bucket, and act / prev by bucket
  4  LOYO logistic model of BREAKOUT per position (with and without Clay's own call) - AUC and lift; LOYO ridge on
     log(act / prev) vs Clay's log(clay / prev) and vs 'no change' - can anything beat Clay at calling the jump?
Log research_breakout.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_season_long as SL
import backtest_noclay_weekly as NW
cal = NW.cal; YEARS = list(NW.YEARS); POS4 = ("QB", "RB", "WR", "TE")
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "research_breakout.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
FLOOR = {"QB": 16.0, "RB": 10.0, "WR": 10.0, "TE": 8.0}
JUMP = 1.20; BREAK = 1.25


def prev_ppg(nm, ps, Y):
    rec = cal.weekly_rec(nm, ps)
    if not rec: return np.nan, 0, np.nan
    pts = [float(w["fpts"]) for w in rec.get("seasons", {}).get(str(Y - 1), []) if cal.played(w) and isinstance(w.get("fpts"), (int, float))]
    if len(pts) < 1: return np.nan, 0, np.nan
    late = np.mean(pts[-5:]) if len(pts) >= 5 else np.nan
    return float(np.mean(pts)), len(pts), late


def main():
    T = SL.build_table(); T = T[T.pos.isin(POS4)].copy().reset_index(drop=True)
    T["act"] = T["ppg"].astype(float)   # season PPG over the games he played (the table's 'act' is the first week's score)
    P(f"season-long table: {len(T):,} player-seasons 2019-25")
    pp = [prev_ppg(nm, ps, int(y)) for nm, ps, y in zip(T.name, T.pos, T.year)]
    T["prev"] = [x[0] for x in pp]; T["prev_g"] = [x[1] for x in pp]; T["prev_late5"] = [x[2] for x in pp]
    # prior-year late-season usage from the context rows (last week of the prior season): share last 3 vs season
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet"))
    last = C.sort_values(["year", "pid", "wk"]).groupby(["year", "pid"]).tail(1).set_index(["year", "pid"])
    def lastcol(c):
        return np.array([last[c].get((int(y) - 1, p), np.nan) if isinstance(p, str) else np.nan for y, p in zip(T.year, T.pid)], dtype=float)
    T["tgt_l3_py"] = lastcol("tgt_sh_l3"); T["tgt_full_py"] = lastcol("tgt_sh"); T["snap_py"] = lastcol("snap_std"); T["xfp_py"] = lastcol("xfp_pg"); T["snap_l1_py"] = lastcol("snap_l1")
    T["tgt_trend_py"] = T.tgt_l3_py - T.tgt_full_py
    ok = (T.prev_g >= 6) & (T.games >= 6) & (T.prev >= 2.0) & ~T.clay.isna() & ~T.act.isna()
    D = T[ok].copy()
    D["jump"] = D.clay / D.prev >= JUMP
    D["floor"] = D.pos.map(FLOOR)
    D["brk"] = (D.act / D.prev >= BREAK) & (D.act >= D.floor)
    D["drop"] = D.act / D.prev <= 0.80
    D["r_act"] = D.act / D.prev; D["r_clay"] = D.clay / D.prev
    D["mkt"] = D.adp_curve / D.prev
    P(f"rows with a prior season of 6+ games and 6+ games this season: {len(D):,}  (" + " ".join(f"{ps} {int((D.pos == ps).sum())}" for ps in POS4) + ")")
    P(f"definitions: Clay JUMP = Clay/prev >= {JUMP}; BREAKOUT = actual/prev >= {BREAK} and actual >= floor (QB 16 / RB 10 / WR 10 / TE 8 half-PPR per game); DROP = actual/prev <= .80")

    # ---------------------------------------------------------------- 1 by position
    P("\n=== 1  CLAY'S PROJECTED JUMPS BY POSITION ===")
    P(f"    {'pos':3s} {'n':>4s} {'breakouts':>9s} {'rate':>5s} | {'Clay jumps':>10s} {'rate':>5s} | {'precision':>9s} {'recall':>6s} | {'act/clay jump':>13s} {'act/clay rest':>13s} | {'act/prev jump':>13s} {'rest':>6s} | {'drop rate jump':>14s} {'rest':>5s}")
    for ps in POS4:
        d = D[D.pos == ps]; j = d[d.jump]; r = d[~d.jump]
        prec = j.brk.mean() if len(j) else np.nan; rec = (j.brk.sum() / d.brk.sum()) if d.brk.sum() else np.nan
        P(f"    {ps:3s} {len(d):4d} {int(d.brk.sum()):9d} {d.brk.mean():5.2f} | {len(j):10d} {len(j)/len(d):5.2f} | {prec:9.2f} {rec:6.2f} | {j.act.sum()/j.clay.sum():13.3f} {r.act.sum()/r.clay.sum():13.3f} | {j.r_act.mean():13.2f} {r.r_act.mean():6.2f} | {j['drop'].mean():14.2f} {r['drop'].mean():5.2f}")
    P("    read: precision = share of Clay's jump calls that became breakouts; act/clay < 1 on jump players = he projected the jump too big")
    P("\n    jump size: act/prev by how big a jump Clay called")
    for ps in POS4:
        d = D[D.pos == ps]; cells = []
        for lo, hi in ((0.0, 0.9), (0.9, 1.1), (1.1, 1.2), (1.2, 1.4), (1.4, 9.9)):
            m = (d.r_clay >= lo) & (d.r_clay < hi)
            cells.append(f"Clay {lo:.1f}-{hi:.1f}x: n{int(m.sum()):3d} act {d.r_act[m].mean():.2f}x act/clay {d.act[m].sum()/max(1e-9, d.clay[m].sum()):.2f}" if m.sum() >= 8 else f"Clay {lo:.1f}-{hi:.1f}x: n{int(m.sum())}")
        P(f"    {ps}: " + " | ".join(cells))

    # ---------------------------------------------------------------- 2 by experience
    P("\n=== 2  BY EXPERIENCE YEAR (exp = seasons before this one): is the breakout later for TEs? ===")
    P(f"    {'pos':3s} {'exp':>5s} {'n':>4s} {'break rate':>10s} {'drop rate':>9s} {'act/prev':>8s} | {'Clay jump rate':>14s} {'Clay precision':>14s} {'act/clay':>8s} | {'market/prev':>11s}")
    for ps in POS4:
        for lab, lo, hi in (("yr2", 1, 1), ("yr3", 2, 2), ("yr4", 3, 3), ("yr5-6", 4, 5), ("yr7+", 6, 30)):
            d = D[(D.pos == ps) & (D.exp >= lo) & (D.exp <= hi)]
            if len(d) < 12: continue
            j = d[d.jump]
            P(f"    {ps:3s} {lab:>5s} {len(d):4d} {d.brk.mean():10.2f} {d['drop'].mean():9.2f} {d.r_act.mean():8.2f} | {d.jump.mean():14.2f} {(j.brk.mean() if len(j) >= 5 else np.nan):14.2f} {d.act.sum()/d.clay.sum():8.3f} | {np.nanmean(d.mkt):11.2f}")

    # ---------------------------------------------------------------- 3 single signals
    P("\n=== 3  ONE SIGNAL AT A TIME: breakout rate and act/prev by bucket (TE first, then WR / RB for contrast) ===")
    def buckets(d, col, edges, labels):
        v = d[col].values.astype(float); out = []
        for k in range(len(edges) - 1):
            m = (v >= edges[k]) & (v < edges[k + 1])
            if m.sum() >= 10: out.append(f"{labels[k]}: n{int(m.sum()):3d} brk {d.brk[m].mean():.2f} act/prev {d.r_act[m].mean():.2f} act/clay {d.act[m].sum()/max(1e-9, d.clay[m].sum()):.2f}")
        return " | ".join(out) if out else "n/a"
    SIG = [("draft round", "pick", (0, 33, 65, 110, 300), ("R1", "R2", "R3", "R4+")),
           ("age", "age", (0, 24, 26, 28, 31, 50), ("<24", "24-25", "26-27", "28-30", "31+")),
           ("prior-yr target share", "tgt_full_py", (0, 0.10, 0.15, 0.20, 0.25, 1), ("<10%", "10-15", "15-20", "20-25", "25%+")),
           ("prior-yr late trend (last 3 games share - season share)", "tgt_trend_py", (-1, -0.05, -0.01, 0.01, 0.05, 1), ("< -5pt", "-5..-1", "flat", "+1..+5", "+5pt+")),
           ("prior-yr last-5-games ppg / season ppg", "late_ratio", (0, 0.8, 0.95, 1.1, 1.3, 9), ("<.8", ".8-.95", ".95-1.1", "1.1-1.3", "1.3+")),
           ("prior-yr snap share", "snap_py", (0, 50, 65, 80, 101), ("<50", "50-65", "65-80", "80+")),
           ("prior-yr PFF route rate", "route_rate_py", (0, 50, 65, 80, 101), ("<50", "50-65", "65-80", "80+")),
           ("prior-yr routes run", "routes_py", (0, 200, 350, 450, 2000), ("<200", "200-350", "350-450", "450+")),
           ("prior-yr yards per route (PFF)", "yprr_py", (0, 1.2, 1.6, 2.0, 9), ("<1.2", "1.2-1.6", "1.6-2.0", "2.0+")),
           ("prior-yr targets per route", "tprr_py", (0, 0.15, 0.20, 0.25, 1), ("<.15", ".15-.20", ".20-.25", ".25+")),
           ("market: ADP curve / prev", "mkt", (0, 0.9, 1.1, 1.3, 9), ("<.9", ".9-1.1", "1.1-1.3", "1.3+")),
           ("new playcaller", "new_pc", (-0.5, 0.5, 1.5), ("no", "yes")),
           ("playcaller TE target share tendency", "pc_te_tgt", (0, 0.17, 0.21, 0.25, 1), ("<17%", "17-21", "21-25", "25%+")),
           ("changed teams", "mover", (-0.5, 0.5, 1.5), ("no", "yes")),
           ("JM prospect score", "jm", (0, 55, 65, 75, 101), ("<55", "55-65", "65-75", "75+")),
           ("week-1 depth chart string", "strb", (0.5, 1.5, 2.5, 9), ("1st", "2nd", "3rd+"))]
    D["late_ratio"] = D.prev_late5 / D.prev
    for ps in ("TE", "WR", "RB"):
        P(f"\n  --- {ps} (n {int((D.pos == ps).sum())}, base breakout rate {D.brk[D.pos == ps].mean():.2f}) ---")
        d = D[D.pos == ps]
        for lab, col, edges, labels in SIG:
            if col not in d.columns or d[col].notna().sum() < 30: continue
            P(f"    {lab:52s} {buckets(d, col, edges, labels)}")

    # ---------------------------------------------------------------- 4 models
    P("\n=== 4  CAN A MODEL CALL THE BREAKOUT? LOYO per position ===")
    from sklearn.linear_model import LogisticRegression, Ridge
    FEATS = ["exp_yr2", "exp_yr3", "exp_yr4", "lpick", "age", "tgt_full_py", "tgt_trend_py", "late_ratio", "snap_py", "snap_l1_py", "route_rate_py", "yprr_py", "tprr_py", "lmkt", "new_pc", "pc_te_tgt", "mover", "strb_num", "lprev"]
    D["exp_yr2"] = (D.exp == 1).astype(float); D["exp_yr3"] = (D.exp == 2).astype(float); D["exp_yr4"] = (D.exp == 3).astype(float)
    D["lmkt"] = np.log(np.clip(D.mkt.fillna(1.0), 0.3, 3.0)); D["strb_num"] = D.strb.fillna(2.0); D["lprev"] = np.log(D.prev)
    D["lclay"] = np.log(np.clip(D.r_clay, 0.3, 3.0)); D["lact"] = np.log(np.clip(D.r_act, 0.2, 4.0))
    def auc(y, s):
        y = np.asarray(y, bool); s = np.asarray(s, float)
        if y.sum() == 0 or (~y).sum() == 0: return np.nan
        from scipy.stats import rankdata
        r = rankdata(s); return (r[y].sum() - y.sum() * (y.sum() + 1) / 2) / (y.sum() * (~y).sum())
    def fill(df, cols):
        X = df[cols].astype(float).copy()
        for c in cols: X[c] = X[c].fillna(X[c].median() if X[c].notna().any() else 0.0)
        return X.values
    for ps in POS4:
        d = D[D.pos == ps].copy()
        if len(d) < 60: continue
        y = d.brk.values.astype(bool); yrs = d.year.values
        res = {}
        for lab, cols in (("signals only", FEATS), ("Clay's call only", ["lclay"]), ("signals + Clay's call", FEATS + ["lclay"]), ("market only", ["lmkt"])):
            cols = [c for c in cols if c in d.columns]
            pr = np.zeros(len(d)); rg = np.zeros(len(d))
            for Y in YEARS:
                tr = yrs != Y; te = yrs == Y
                if te.sum() == 0 or y[tr].sum() < 5: continue
                Xtr, Xte = fill(d[tr], cols), fill(d[te], cols)
                mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9; Xtr = (Xtr - mu) / sd; Xte = (Xte - mu) / sd
                lg = LogisticRegression(C=0.3, max_iter=2000).fit(Xtr, y[tr]); pr[te] = lg.predict_proba(Xte)[:, 1]
                rd = Ridge(alpha=10.0).fit(Xtr, d.lact.values[tr]); rg[te] = rd.predict(Xte)
            top = pr >= np.quantile(pr, 0.8)
            mse = float(np.mean((rg - d.lact.values) ** 2))
            res[lab] = (auc(y, pr), y[top].mean(), mse)
        base_mse = float(np.mean(d.lact.values ** 2)); clay_mse = float(np.mean((d.lclay.values - d.lact.values) ** 2))
        P(f"\n  {ps}: n {len(d)}, breakouts {int(y.sum())} ({y.mean():.2f})")
        P(f"    {'model':24s} {'AUC':>5s} {'breakout rate in top 20%':>24s} {'LOYO ridge MSE of log(act/prev)':>31s}")
        for lab, (a, l, m) in res.items(): P(f"    {lab:24s} {a:5.2f} {l:24.2f} {m:31.3f}")
        P(f"    {'no change (act = prev)':24s} {'':5s} {'':24s} {base_mse:31.3f}")
        P(f"    {'Clay as is (act = clay)':24s} {'':5s} {'':24s} {clay_mse:31.3f}")
        # coefficients of the signals-only logistic on all years, for reading
        cols = [c for c in FEATS if c in d.columns]; X = fill(d, cols); mu, sd = X.mean(0), X.std(0) + 1e-9
        lg = LogisticRegression(C=0.3, max_iter=2000).fit((X - mu) / sd, y)
        co = sorted(zip(cols, lg.coef_[0]), key=lambda t: -abs(t[1]))[:7]
        P("    strongest signals (standardized logistic coefficients): " + ", ".join(f"{c} {v:+.2f}" for c, v in co))
    P("\n=== 5  TE BREAKOUTS NAMED (2019-25): actual >= 1.25x prev and >= 8 half-PPR/g ===")
    d = D[(D.pos == "TE") & D.brk].sort_values("year")
    for _, r in d.iterrows():
        P(f"    {int(r.year)} {r['name']:22s} exp {int(r.exp) if not np.isnan(r.exp) else -1:2d} pick {int(r.pick) if not np.isnan(r.pick) else 0:3d} | prev {r.prev:5.1f} -> act {r.act:5.1f} ({r.r_act:.2f}x) | Clay {r.clay:5.1f} ({r.r_clay:.2f}x) {'JUMP' if r.jump else '    '} | market {r.mkt:.2f}x | prior-yr tgt {r.tgt_full_py*100 if not np.isnan(r.tgt_full_py) else -1:4.0f}% trend {r.tgt_trend_py*100 if not np.isnan(r.tgt_trend_py) else 0:+4.0f} late5 {r.late_ratio if not np.isnan(r.late_ratio) else 0:.2f} routes {r.routes_py if not np.isnan(r.routes_py) else 0:4.0f}")
    P("\n    ...and Clay's TE JUMP calls that did NOT break out (act/clay):")
    d = D[(D.pos == "TE") & D.jump & ~D.brk].sort_values("r_clay", ascending=False)
    for _, r in d.head(20).iterrows():
        P(f"    {int(r.year)} {r['name']:22s} exp {int(r.exp) if not np.isnan(r.exp) else -1:2d} | prev {r.prev:5.1f} Clay {r.clay:5.1f} ({r.r_clay:.2f}x) -> act {r.act:5.1f} ({r.r_act:.2f}x, act/clay {r.act/r.clay:.2f}) | market {r.mkt:.2f}x | late5 {r.late_ratio if not np.isnan(r.late_ratio) else 0:.2f}")
    LOG.close()


if __name__ == "__main__":
    main()
