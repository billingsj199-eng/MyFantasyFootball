#!/usr/bin/env python3
"""
Do the PFF premium signals add anything ON TOP of the model we already have?
2019-2025, pbp_cache/pff/*.csv (receiving / rushing / blocking, REG only).

The test that matters: residual analysis. Take the validated baseline (3-yr
recency core, the same one every other backtest uses), then ask whether a PFF
signal from season Y-1 predicts how a player BEATS or MISSES that baseline in
season Y. If it does, it's new information; if not, it's already priced in
(the fate of pace multipliers, prior-season FPA, coach-change variance...).

Signals tested (all from Y-1, predicting Y):
  route_rate        TE/WR route participation — the signal our data lacks
  yprr              yards per route run (efficiency-per-opportunity)
  grades_pass_route PFF route-running grade (talent, not usage)
  yco_attempt       RB yards after contact per attempt
  elusive_rating    RB elusiveness
  team_run_block    team OL run-block grade (snap-weighted) — RB context
  team_pass_block   team OL pass-block grade

For each: correlation with the log residual, and MAE when applied as a
multiplier at the best-fit elasticity (LOYO by season so nothing is fit on
its own test year).
"""
import numpy as np
import pandas as pd
import os
from collections import defaultdict
from backtest_sim_calibration import played, WEEKLY, infer_team, POS_KEEP
import backtest_sim_calibration as cal

PFF = r"E:\MyFantasyFootball\pbp_cache\pff"
W3 = [0.5, 0.3, 0.2]
YEARS = range(2019, 2026)
PFF_TEAM = {"CLV": "CLE", "ARZ": "ARI", "BLT": "BAL", "HST": "HOU", "LA": "LAR",
            "SD": "LAC", "OAK": "LV", "JAC": "JAX", "WAS": "WAS"}

def load(kind):
    out = {}
    for y in YEARS:
        p = os.path.join(PFF, f"pff_{kind}_{y}.csv")
        if os.path.exists(p):
            df = pd.read_csv(p)
            df["norm"] = df.player.map(cal.norm)
            out[y] = df
    return out

def rows_of(rec, Y):
    return [w for w in rec.get("seasons", {}).get(str(Y), []) if played(w)]

def ppg_of(rec, Y):
    pts = [w["fpts"] for w in rows_of(rec, Y) if isinstance(w.get("fpts"), (int, float))]
    return (sum(pts) / len(pts), len(pts)) if pts else (None, 0)

def main():
    recv, rush, block = load("receiving"), load("rushing"), load("blocking")

    # team OL grades per season (snap-weighted over linemen)
    team_ol = {}
    for y, df in block.items():
        d = df[df.position.isin(["T", "G", "C", "LT", "RT", "LG", "RG", "CE"])]
        for tm, g in d.groupby("team_name"):
            w = g.snap_counts_block.fillna(0)
            if w.sum() < 1000:
                continue
            team_ol[(PFF_TEAM.get(tm, tm), y)] = (
                float((g.grades_run_block.fillna(60) * w).sum() / w.sum()),
                float((g.grades_pass_block.fillna(60) * w).sum() / w.sum()))

    # index PFF player rows by (norm, year)
    pidx = {}
    for y, df in recv.items():
        for _, r in df.iterrows():
            pidx[(r["norm"], y, "recv")] = r
    for y, df in rush.items():
        for _, r in df.iterrows():
            pidx[(r["norm"], y, "rush")] = r

    samples = []
    for nk, lst in WEEKLY.items():
        for rec in lst:
            pos = rec.get("pos")
            if pos not in POS_KEEP:
                continue
            for Y in YEARS:
                act, g = ppg_of(rec, Y)
                if act is None or g < 6:
                    continue
                num = den = 0.0
                for i, yy in enumerate((Y - 1, Y - 2, Y - 3)):
                    p, gg = ppg_of(rec, yy)
                    if p is not None and gg >= 4:
                        num += W3[i] * p; den += W3[i]
                if den == 0:
                    continue
                core = num / den
                if core < 3:
                    continue
                s = {"pos": pos, "Y": Y, "core": core, "act": act,
                     "resid": np.log(max(0.2, act) / core)}
                pr = pidx.get((nk, Y - 1, "recv"))
                if pr is not None and (pr.get("routes") or 0) >= 100:
                    s["route_rate"] = pr.get("route_rate")
                    s["yprr"] = pr.get("yprr")
                    s["grades_pass_route"] = pr.get("grades_pass_route")
                ru = pidx.get((nk, Y - 1, "rush"))
                if ru is not None and (ru.get("attempts") or 0) >= 50:
                    s["yco_attempt"] = ru.get("yco_attempt")
                    s["elusive_rating"] = ru.get("elusive_rating")
                tm = infer_team(rec, Y)
                ol = team_ol.get((tm, Y - 1)) if tm else None
                if ol:
                    s["team_run_block"], s["team_pass_block"] = ol
                samples.append(s)
    df = pd.DataFrame(samples)
    print(f"{len(df)} player-seasons; PFF coverage: "
          f"route_rate {df.route_rate.notna().sum()}, yco {df.yco_attempt.notna().sum()}, "
          f"OL {df.team_run_block.notna().sum()}\n")

    SIGNALS = [("route_rate", ("WR", "TE")), ("yprr", ("WR", "TE")),
               ("grades_pass_route", ("WR", "TE")), ("yco_attempt", ("RB",)),
               ("elusive_rating", ("RB",)), ("team_run_block", ("RB",)),
               ("team_pass_block", ("WR", "TE", "QB"))]
    print("=== Does the Y-1 PFF signal predict the Y residual vs the recency core? ===")
    for sig, positions in SIGNALS:
        for pos in positions:
            sel = df[(df.pos == pos) & df[sig].notna()]
            if len(sel) < 60:
                continue
            x = sel[sig].astype(float).values
            r = float(np.corrcoef(x, sel.resid.values)[0, 1])
            # LOYO multiplier test
            errs_base, errs_mod = [], []
            for Y in YEARS:
                tr, te = sel[sel.Y != Y], sel[sel.Y == Y]
                if len(te) < 5 or len(tr) < 40:
                    continue
                b = np.polyfit(tr[sig].astype(float), tr.resid, 1)
                mu = tr[sig].astype(float).mean()
                for _, t in te.iterrows():
                    pred = t.core * np.exp(np.clip(b[0] * (float(t[sig]) - mu), -0.25, 0.25))
                    errs_mod.append(abs(pred - t.act))
                    errs_base.append(abs(t.core - t.act))
            if not errs_base:
                continue
            d = (np.mean(errs_mod) - np.mean(errs_base)) / np.mean(errs_base) * 100
            flag = "  <== HELPS" if d < -0.5 else ("  (hurts)" if d > 0.5 else "  (flat)")
            print(f"  {sig:<18} {pos}: corr {r:+.3f}  MAE {np.mean(errs_base):.3f} -> "
                  f"{np.mean(errs_mod):.3f} ({d:+.2f}%)  n={len(sel)}{flag}")

    # tercile view for the strongest candidates
    print("\n=== Tercile check (mean residual by signal level) ===")
    for sig, pos in [("route_rate", "TE"), ("route_rate", "WR"), ("yprr", "TE"),
                     ("yco_attempt", "RB"), ("team_run_block", "RB")]:
        sel = df[(df.pos == pos) & df[sig].notna()]
        if len(sel) < 60:
            continue
        q = sel[sig].astype(float).quantile([0.33, 0.67]).values
        lo = sel[sel[sig].astype(float) <= q[0]].resid.mean()
        mid = sel[(sel[sig].astype(float) > q[0]) & (sel[sig].astype(float) <= q[1])].resid.mean()
        hi = sel[sel[sig].astype(float) > q[1]].resid.mean()
        print(f"  {sig:<18} {pos}: low {np.exp(lo):.3f}  mid {np.exp(mid):.3f}  high {np.exp(hi):.3f}  (n={len(sel)})")

if __name__ == "__main__":
    main()
