#!/usr/bin/env python3
"""
USAGE AS EVIDENCE ON THE LIVE BASE (Jack 2026-09-29: "we should definitely factor in route share, snap
share etc if we haven't"). What is live today: snap TREND (RB/WR/TE), TE route TREND, RB snap-volume blend
(15%). What is NOT live: the LEVEL of a WR / TE's routes, snaps and targets as evidence - the xFP schedule
(v2.18) only runs inside the Clay-free shadow.

Test, on the live form (P=5 blend of Clay per game and points per game, x the live layers), walk-forward:
  evidence = lam x USAGE-IMPLIED points per game + (1 - lam) x actual points per game
USAGE-IMPLIED candidates (coefficients fit on the training seasons only, per position):
  xfp     expected points from targets / air yards / carries (the site's xFP)
  route   PFF route rate (share of team dropbacks he ran a route on), season to date
  snap    offensive snap share, season to date
  combo   linear mix of the three
lam is one number per position x games-played bucket, picked on the training seasons (LOYO), so every
graded season is out of sample. Graded: MSE, MAE, top-150 weighted MSE (Jack's rule), weekly rank inside
the position; by position and by games played. Log usage_live_backtest.log.
"""
import json, os, sys, warnings
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bt_common as B
import backtest_noclay_weekly as NW
import research_clay_vs_shadow as CS
from backtest_inseason_usage import route_features
warnings.filterwarnings("ignore")
if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "usage_live_backtest.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
YEARS = list(NW.YEARS); POS = ("WR", "TE", "RB")
BUCKETS = (("1 game", 1, 1), ("2 games", 2, 2), ("3 games", 3, 3), ("4-5", 4, 5), ("6-8", 6, 8), ("9+", 9, 99))
LG = [0.0, 0.15, 0.3, 0.5, 0.75, 1.0]

def main():
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, clay, layers, adp, pid = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"], F["adp"], A["pid"]
    ch = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, A["name"])], dtype=float)
    W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay)
    ship = NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet"))
    ck = {(int(r.year), r.pid, int(r.wk)): i for i, r in enumerate(C[["year", "pid", "wk"]].itertuples(index=False)) if isinstance(r.pid, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    U = {c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float) for c in ("xfp_pg", "snap_std", "tgt_sh", "plays_pg_std")}
    U["rt"], _ = route_features(year, pid, wk)
    ok = has & (g >= 1) & ~np.isnan(U["xfp_pg"]) & ~np.isnan(U["snap_std"]) & ~np.isnan(U["rt"]) & np.isin(pos, POS) & (ship >= 5)
    P(f"rows: {int(ok.sum())} player-weeks (WR/TE/RB, live projection >= 5, one game or more played, xFP + snaps + PFF routes all present) of {n}")
    rate = act / np.maximum(layers, 0.2)             # matchup-free points, the thing usage should explain
    bk = np.zeros(n, int) - 1
    for k, (_, a, b) in enumerate(BUCKETS): bk[(g >= a) & (g <= b)] = k
    lv = F["adp_curve"].copy()
    for ps in NW.POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); t = m & (adp <= 150); lv[m] = lv[m] / lv[t].mean()
    wt = np.maximum(0.05, lv) ** 2
    FEATS = {"xfp": ["xfp_pg"], "route": ["rt"], "snap": ["snap_std"], "combo": ["xfp_pg", "rt", "snap_std"]}
    preds = {k: ship.copy() for k in FEATS}; lam_pick = {k: {} for k in FEATS}; coef_log = {}
    for Y in YEARS:
        tr = ok & (year != Y); te = ok & (year == Y)
        for ps in POS:
            for name, cols in FEATS.items():
                mt = tr & (pos == ps)
                X = np.column_stack([np.ones(mt.sum())] + [U[c][mt] for c in cols]); b, *_ = np.linalg.lstsq(X, rate[mt], rcond=None)
                coef_log[(name, ps, Y)] = b
                ma = ok & (pos == ps)
                u = np.maximum(0.0, np.column_stack([np.ones(ma.sum())] + [U[c][ma] for c in cols]) @ b)
                uf = np.zeros(n); uf[ma] = u
                for k in range(len(BUCKETS)):
                    mtr = mt & (bk == k); mte = te & (pos == ps) & (bk == k)
                    if mtr.sum() < 150 or not mte.any(): continue
                    best, bl = None, 0.0
                    for lam in LG:
                        p = NW.blend(clay_gm[mtr], g[mtr], lam * uf[mtr] + (1 - lam) * ppg[mtr], NW.PRIOR_P) * layers[mtr]
                        e = float(np.average((p - act[mtr]) ** 2, weights=wt[mtr]))
                        if best is None or e < best - 1e-9: best, bl = e, lam
                    preds[name][mte] = NW.blend(clay_gm[mte], g[mte], bl * uf[mte] + (1 - bl) * ppg[mte], NW.PRIOR_P) * layers[mte]
                    lam_pick[name].setdefault((ps, k), []).append(bl)
    def sp(p, m):
        v = []
        d = pd.DataFrame({"y": year[m], "w": wk[m], "ps": pos[m], "p": p[m], "a": act[m]})
        for _, x in d.groupby(["y", "w", "ps"]):
            if len(x) >= 8: v.append(np.corrcoef(x.p.rank(), x.a.rank())[0, 1])
        return float(np.mean(v))
    def line(label, p, m):
        if m.sum() < 100: return
        mse0 = np.mean((ship[m] - act[m]) ** 2); mse1 = np.mean((p[m] - act[m]) ** 2)
        mae0 = np.mean(np.abs(ship[m] - act[m])); mae1 = np.mean(np.abs(p[m] - act[m]))
        t = m & (adp <= 150); w0 = np.average((ship[t] - act[t]) ** 2, weights=wt[t]); w1 = np.average((p[t] - act[t]) ** 2, weights=wt[t])
        win = sum(1 for Y in YEARS if (m & (year == Y)).sum() > 20 and np.mean((p[m & (year == Y)] - act[m & (year == Y)]) ** 2) < np.mean((ship[m & (year == Y)] - act[m & (year == Y)]) ** 2))
        P(f"  {label:34s} n={int(m.sum()):5d}  MSE {100*(mse1/mse0-1):+6.2f}% ({win}/7)  MAE {100*(mae1/mae0-1):+6.2f}%  top-150 weighted {100*(w1/w0-1):+6.2f}%  rank {sp(ship, m):.4f} -> {sp(p, m):.4f}  bias {np.mean(ship[m]-act[m]):+.2f} -> {np.mean(p[m]-act[m]):+.2f}")
    for name in FEATS:
        P(f"\n=== usage evidence = {name.upper()} (every season out of sample) ===")
        line("ALL (WR + TE + RB)", preds[name], ok)
        for ps in POS: line(ps, preds[name], ok & (pos == ps))
        for k, (lab, a, b) in enumerate(BUCKETS): line(f"after {lab} game(s)", preds[name], ok & (bk == k))
        for ps in ("WR", "TE"):
            for k, (lab, a, b) in enumerate(BUCKETS[:4]): line(f"   {ps} after {lab}", preds[name], ok & (pos == ps) & (bk == k))
        P("  weight on usage picked (avg across the 7 held-out fits):")
        for ps in POS:
            P("    " + ps + "  " + "  ".join(f"{BUCKETS[k][0]}: {np.mean(lam_pick[name][(ps, k)]):.2f}" for k in range(len(BUCKETS)) if (ps, k) in lam_pick[name]))
    P("\n=== what a unit of usage is worth (2025 held out; matchup-free half-PPR points per game) ===")
    for ps in POS:
        b = coef_log[("combo", ps, 2025)]
        P(f"  {ps}: {b[0]:+.2f}  + {b[1]:.2f} x xFP/g  + {b[2]*10:.2f} per 10 pts of route rate  + {b[3]*10:.2f} per 10 pts of snap share")
        for nm in ("route", "snap"):
            c = coef_log[(nm, ps, 2025)]; P(f"      {nm} alone: {c[0]:+.2f} + {c[1]*10:.2f} per 10 pts")
    P("\n=== the 2026 TE question: usage evidence on TEs only, by season ===")
    for Y in YEARS:
        m = ok & (pos == "TE") & (year == Y)
        P(f"  {Y}: n={int(m.sum()):4d}  live MSE {np.mean((ship[m]-act[m])**2):6.2f}   xfp {100*(np.mean((preds['xfp'][m]-act[m])**2)/np.mean((ship[m]-act[m])**2)-1):+5.2f}%   route {100*(np.mean((preds['route'][m]-act[m])**2)/np.mean((ship[m]-act[m])**2)-1):+5.2f}%   combo {100*(np.mean((preds['combo'][m]-act[m])**2)/np.mean((ship[m]-act[m])**2)-1):+5.2f}%   live bias {np.mean(ship[m]-act[m]):+.2f}")

if __name__ == "__main__":
    main()
