#!/usr/bin/env python3
"""
PFF PRO METRICS ON THE WEEKLY RANK OBJECTIVE (2026-10-05) - stage B after research_pff_pro_screen.py.

Same harness, objective and pass rule as backtest_matchup_rank.py (09-17): base = shadow rate x the live layers,
objective = mean within-position-week Spearman on the top 150 (pair order + MSE as guardrails), each candidate
applied as x exp(c z) with z = the metric standardized within the week, c picked per held-out season (LOYO) on the
other seasons, then forward 2021-25. PASS = LOYO rho gain >= .004 in 5+ of 7 seasons AND forward rho > 0 in 3+ of 5.
With ~30 tests expect one or two false passes: a real one also keeps the same pick across folds and a plausible sign.

Usage:  python backtest_pff_pro_rank.py feat:POS[,POS] [feat:POS ...]
        (features = columns of data/pff_pro_features.parquet)
Log pff_pro_rank.log; results -> data/pff_pro_rank.json.
"""
import json, os, sys, time, warnings
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy.stats import rankdata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B  # noqa: F401  (harness import order matches backtest_matchup_rank)
import backtest_noclay_weekly as NW
import research_clay_vs_shadow as CS
import backtest_season_long as SL
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "pff_pro_rank.log"), "w", encoding="utf-8"))


def P(*a): print(" ".join(str(x) for x in a), flush=True)


YEARS, POS4 = NW.YEARS, NW.POS4


def main(specs):
    t0 = time.time()
    P("=== PFF Pro metrics on the weekly RANK objective (top 150, within position-week, LOYO + forward) ===")
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, layers, adp, pid = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["layers"], F["adp"], A["pid"]
    T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    def col(c): return np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    xfp = col("xfp_pg"); ev = has & (g >= 1) & ~np.isnan(xfp); xf = np.where(ev, xfp, ppg)
    lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    def rate_of(fwd):
        lo = (SL.forward if fwd else SL.loyo)(T, LIVE, "ridge", 10.0); key = {(int(y), nm, ps): v for y, nm, ps, v in zip(T.year, T.name, T.pos, lo)}
        r = np.array([key.get((year[i], A["name"][i], pos[i]), np.nan) for i in range(n)]); prior = np.where(np.isnan(r) | (pos == "QB"), F["prior"], 0.5 * r + 0.5 * F["prior"])
        rate = NW.blend(prior, g, lam * xf + (1 - lam) * ppg, F["Pvec"])
        for gi, m_ in enumerate([0.7, 0.8], start=1): rate = np.where(F["buried_rk"] & (wk == gi), rate * m_, rate)
        return np.where(F["on"], rate * np.power(F["pm"], 0.75), rate)
    RATE = {False: rate_of(False), True: rate_of(True)}
    FT = pd.read_parquet(os.path.join(HERE, "data", "pff_pro_features.parquet"))
    fk = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(FT.year, FT.pid, FT.wk))}
    fidx = np.array([fk.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); fh = fidx >= 0
    def fcol(c): return np.where(fh, FT[c].values[np.maximum(fidx, 0)], np.nan).astype(float) if c in FT.columns else np.full(n, np.nan)
    top150 = adp <= 150
    groups = defaultdict(list)
    for i in np.where(top150)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
    groups = {k: np.array(v) for k, v in groups.items() if len(v) >= 8}
    def zscore_within_week(v):
        out = np.full(n, 0.0); byw = defaultdict(list)
        for i in np.where(~np.isnan(v))[0]: byw[(int(year[i]), int(wk[i]), pos[i])].append(i)
        for k, ix in byw.items():
            ix = np.array(ix); s = v[ix].std()
            if s > 0: out[ix] = (v[ix] - v[ix].mean()) / s
        return out
    def metrics(pred, ps, years):
        rho, pw, tot, se, sn = [], 0, 0, 0.0, 0
        for (y, w, p_), ix in groups.items():
            if p_ != ps or y not in years: continue
            a = act[ix]; pv = pred[ix]; ra, rp = rankdata(a), rankdata(pv); rho.append(np.corrcoef(ra, rp)[0, 1])
            d = pv[:, None] - pv[None, :]; o = a[:, None] - a[None, :]; iu = np.triu_indices(len(ix), 1); dd, oo = d[iu], o[iu]; ok = (dd != 0) & (oo != 0)
            pw += int(((dd > 0) == (oo > 0))[ok].sum()); tot += int(ok.sum()); se += float(((pv - a) ** 2).sum()); sn += len(ix)
        return float(np.mean(rho)), 100.0 * pw / max(1, tot), se / max(1, sn)
    def loyo_tilt(feat, grid, ps, fwd=False):
        rate = RATE[fwd]; ys = YEARS[2:] if fwd else YEARS
        cand = {c: rate * layers * np.exp(c * feat) for c in grid}; stat = {c: {y: metrics(cand[c], ps, {y}) for y in YEARS} for c in grid}
        picks, out_rho, out_pw, out_mse, base_rho, base_pw, base_mse, wins = [], [], [], [], [], [], [], 0
        for y in ys:
            tr = [yy for yy in YEARS if (yy < y if fwd else yy != y)]
            best = max(grid, key=lambda c: np.mean([stat[c][yy][0] for yy in tr])); picks.append(best)
            out_rho.append(stat[best][y][0]); out_pw.append(stat[best][y][1]); out_mse.append(stat[best][y][2]); base_rho.append(stat[0.0][y][0]); base_pw.append(stat[0.0][y][1]); base_mse.append(stat[0.0][y][2])
            wins += int(stat[best][y][0] > stat[0.0][y][0] + 1e-9)
        return {"pos": ps, "picks": picks, "dRho": round(float(np.mean(out_rho) - np.mean(base_rho)), 4), "dPair": round(float(np.mean(out_pw) - np.mean(base_pw)), 3),
                "dMsePct": round(float((np.mean(out_mse) / np.mean(base_mse) - 1) * 100), 2), "wins": wins, "years": len(ys), "baseRho": round(float(np.mean(base_rho)), 4)}
    CG = [-0.10, -0.06, -0.03, 0.0, 0.03, 0.06, 0.10]
    RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "tests": []}
    for spec in specs:
        feat, _, plist = spec.partition(":")
        v = fcol(feat); cover = int((~np.isnan(v) & top150).sum())
        P(f"\n  -- {feat}  (top-150 rows with a value: {cover} of {int(top150.sum())})")
        if cover < 500:
            P("     too few rows - skipped"); continue
        z = zscore_within_week(v)
        for ps in (plist.split(",") if plist else POS4):
            a = loyo_tilt(z, CG, ps); f = loyo_tilt(z, CG, ps, fwd=True)
            a["feat"] = feat; a["fwd"] = {k: f[k] for k in ("dRho", "dPair", "dMsePct", "wins", "years", "picks")}
            a["pass"] = bool(a["dRho"] >= 0.004 and a["wins"] >= 5 and f["dRho"] > 0 and f["wins"] >= 3)
            RES["tests"].append(a)
            P(f"     {ps}: LOYO rho {a['dRho']:+.4f} (base {a['baseRho']:.3f}), pair {a['dPair']:+.2f}, MSE {a['dMsePct']:+.2f}%, better {a['wins']}/{a['years']}, "
              f"picks {sorted(set(a['picks']))} | fwd rho {f['dRho']:+.4f}, pair {f['dPair']:+.2f}, {f['wins']}/{f['years']}{'  <== PASS' if a['pass'] else ''}")
    passed = [t for t in RES["tests"] if t["pass"]]
    P(f"\n{len(RES['tests'])} position-level tests; {len(passed)} pass" + (": " + "; ".join(f"{t['feat']} [{t['pos']}] {t['dRho']:+.4f} picks {sorted(set(t['picks']))}" for t in passed) if passed else ""))
    with open(os.path.join(HERE, "data", "pff_pro_rank.json"), "w", encoding="utf-8") as fh_:
        json.dump(RES, fh_)
    P(f"({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main(sys.argv[1:])
