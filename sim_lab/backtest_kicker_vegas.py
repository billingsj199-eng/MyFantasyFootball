#!/usr/bin/env python3
"""
CLAY-FREE KICKER (Jack 2026-10-08 "run the kicker test"). The sim's kicker number = Clay's season FG / XP line x the tuner's
kLevel x the game chain (Vegas / weather / availability), with the kpts book line as the anchor. Candidate Clay-free kicker
rates, fit on kicker_weekly.js (2020, 2022-25) joined to the team's implied total that week (ctx_features team-week implied):
  V1  a + b x implied                                  V2  V1 + c x (kicker's prior-season ppg - league), shrunk
  V3  V2 + dome                                        (all LOYO by season)
Then graded on the 2026 W1-4 lock rows (32 kickers / week): MAE + rank rho vs actual kicker points for the lock's jsMean
(Clay x kLevel x chain), mean (anchored), the kpts book line, and the Clay-free candidates at the lock's implied.
Log kicker_vegas.log.
"""
import json, os, sys, warnings
from collections import defaultdict
import numpy as np
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_sim_calibration as cal
import pandas as pd
from diagnose_week import load_k
from vs_books_week import consensus, norm
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "kicker_vegas.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
TM_ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI"}


def main():
    raw = open(os.path.join(cal.REPO, "data", "kicker_weekly.js"), encoding="utf-8").read(); K = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); imp = {}; dome = {}
    for y, t, w, v, dm in zip(C.year, C.team, C.wk, C.implied, C.dome):
        if isinstance(t, str) and pd.notna(v): imp[(int(y), t, int(w))] = float(v); dome[(int(y), t, int(w))] = float(dm) if pd.notna(dm) else 0.0
    def team_of(Y, w, opp):
        o = opp.replace("@", "").strip(); o = cal.OPP_ALIAS.get(o, o)
        for t, s in cal.SCHEDULES.get(Y, {}).items():
            if s.get(str(w)) == o: return t
        return None
    rows = []   # (Y, name, wk, fpts, implied, dome, prior_ppg)
    ppg_y = defaultdict(dict)
    for nm, yrs in K.items():
        for y, gl in yrs.items():
            Y = int(y); pts = [g["fpts"] for g in gl if isinstance(g.get("fpts"), (int, float))]
            if len(pts) >= 6: ppg_y[Y][nm] = float(np.mean(pts))
    for nm, yrs in K.items():
        for y, gl in yrs.items():
            Y = int(y)
            if Y >= 2026: continue
            for g in gl:
                if not isinstance(g.get("fpts"), (int, float)) or not g.get("opp"): continue
                t = team_of(Y, int(g["wk"]), g["opp"]); k = (Y, t, int(g["wk"]))
                if t and k in imp: rows.append((Y, nm, int(g["wk"]), float(g["fpts"]), imp[k], dome.get(k, 0.0), ppg_y[Y - 1].get(nm)))
    R = pd.DataFrame(rows, columns=["Y", "nm", "wk", "fpts", "implied", "dome", "prior"]); YEARS = sorted(R.Y.unique())
    lg = {Y: R[R.Y == Y - 1].fpts.mean() if (R.Y == Y - 1).any() else R.fpts.mean() for Y in YEARS}
    R["pdev"] = [(p_ - lg[Y]) if p_ is not None and not np.isnan(p_ if p_ is not None else np.nan) else 0.0 for p_, Y in zip(R.prior, R.Y)]
    P(f"kicker-weeks with an implied total: {len(R):,} over {YEARS}; mean {R.fpts.mean():.2f} pts, implied corr {np.corrcoef(R.implied, R.fpts)[0,1]:.3f}, prior-ppg corr {np.corrcoef(R.pdev, R.fpts)[0,1]:.3f}")
    def fit(df, cols):
        A = np.column_stack([np.ones(len(df))] + [df[c].values for c in cols]); b = np.linalg.lstsq(A, df.fpts.values, rcond=None)[0]; return b
    def pred(b, df, cols): return b[0] + sum(b[i + 1] * df[c].values for i, c in enumerate(cols))
    VARS = {"V1 implied": ["implied"], "V2 implied + prior ppg": ["implied", "pdev"], "V3 + dome": ["implied", "pdev", "dome"]}
    P("\n--- LOYO on history: MAE and rank rho (within week) vs a constant (league mean) ---")
    out = {}
    for lab, cols in VARS.items():
        pr = np.zeros(len(R)); base = np.zeros(len(R))
        for Y in YEARS:
            tr = R[R.Y != Y]; te = R.Y == Y; b = fit(tr, cols); pr[te.values] = pred(b, R[te], cols); base[te.values] = tr.fpts.mean()
        rh = [spearmanr(pr[(R.Y == Y) & (R.wk == w)], R.fpts[(R.Y == Y) & (R.wk == w)]).correlation for Y in YEARS for w in range(1, 19) if ((R.Y == Y) & (R.wk == w)).sum() >= 12]
        rb = [spearmanr(R.implied[(R.Y == Y) & (R.wk == w)], R.fpts[(R.Y == Y) & (R.wk == w)]).correlation for Y in YEARS for w in range(1, 19) if ((R.Y == Y) & (R.wk == w)).sum() >= 12]
        out[lab] = fit(R, cols)
        P(f"  {lab:26s} MAE {np.mean(np.abs(pr - R.fpts)):.3f} (constant {np.mean(np.abs(base - R.fpts)):.3f}) | rank rho {np.nanmean(rh):.3f} (implied alone {np.nanmean(rb):.3f}) | full-fit coefs {np.round(out[lab], 3)}")
    # ---- 2026 W1-4 locks
    P("\n--- 2026 W1-4 lock rows: MAE / rank rho vs actual kicker points ---")
    lg26 = R[R.Y == 2025].fpts.mean(); ppg25 = ppg_y[2025]
    acc = defaultdict(list); rk = defaultdict(list)
    for wkn in (1, 2, 3, 4):
        snap = json.load(open(os.path.join(HERE, "data", "snapshots", f"simlab_snapshot_w{wkn}.json"), encoding="utf-8")); actk = load_k(wkn); week = defaultdict(list)
        for p in snap["players"]:
            if p.get("pos") != "K": continue
            a = actk.get(norm(p["name"]))
            if a is None or not isinstance(p.get("implied"), (int, float)): continue
            kp, _ = consensus(p.get("lines") or {}, "kpts") if p.get("lines") else (None, 0)
            nmK = next((k for k in K if norm(k) == norm(p["name"])), None); pdev = (ppg25.get(nmK, lg26) - lg26) if nmK else 0.0
            gm_ = p.get("game"); dm = 1.0 if (isinstance(gm_, dict) and gm_.get("dome")) or (isinstance(gm_, str) and "dome" in gm_.lower()) else 0.0
            c = {"jsMean (Clay x kLevel x chain)": p.get("jsMean"), "mean (anchored)": p.get("mean"), "book kpts line": kp,
                 "V1 implied": out["V1 implied"][0] + out["V1 implied"][1] * p["implied"], "V2 implied + prior ppg": out["V2 implied + prior ppg"][0] + out["V2 implied + prior ppg"][1] * p["implied"] + out["V2 implied + prior ppg"][2] * pdev,
                 "V3 + dome": out["V3 + dome"][0] + out["V3 + dome"][1] * p["implied"] + out["V3 + dome"][2] * pdev + out["V3 + dome"][3] * dm}
            for lab, v in c.items():
                if isinstance(v, (int, float)): acc[lab].append(abs(v - a)); week[lab].append((v, a))
        for lab, pairs in week.items():
            if len(pairs) >= 12: rk[lab].append(spearmanr([x for x, _ in pairs], [y for _, y in pairs]).correlation)
    for lab in acc: P(f"  {lab:32s} n{len(acc[lab]):4d} | MAE {np.mean(acc[lab]):.3f} | weekly rank rho {np.nanmean(rk[lab]):.3f}")
    P("\nLimitations: 2026 read is 4 weeks x 32 kickers; history fit = implied + prior-season ppg (+ dome) with no weather; the lock's jsMean carries kLevel and the game chain, the candidates carry only the fitted terms.")
    LOG.close()


if __name__ == "__main__":
    main()
