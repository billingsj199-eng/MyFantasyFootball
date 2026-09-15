#!/usr/bin/env python3
"""
FANTASY POINTS PER ROUTE RUN base + ASCENDING-PLAYER flag (2026-09-15).

Jack: "implement a fantasy points per route run that could help ... a player that
is young and ascending, only good reports, increasing snaps, targets, routes and
scoring a ton over a medium sample (Parker Washington)" -> "lets do it but
obviously if a player isnt increasing their routes when scoring lots per route
then we can assume they will stay a part time player".

So the volume gate is ROUTES ONLY: projected routes come from the player's recent
route level and trend, never from his efficiency. FP/RR prices what happens on
those routes, shrunk toward last season and the position prior.

Data: PFF weekly receiving (pbp_cache/pff/weekly/pff_receiving_summary_<yr>_w<N>.csv,
2018-2025: routes / targets / receptions / yards / TD per player-week), walk-forward;
bt_common samples (WR/TE player-weeks 2019-25, shipped = P=5 blend x Vegas x FPA).

  R1  routes projection: 0.5 x last-3-games routes + 0.5 x season-to-date routes/g
  R2  FP/RR (half-PPR receiving pts / route): season-to-date shrunk to prior season
      (K_PRIOR routes) then to the position prior (K_POS routes)
  R3  fprr_pred = projRoutes x FP/RR x veg x fpa  (+ season-to-date rushing pts/g
      from the weekly DB is NOT available here -> WR rushing ignored; noted)
  LOYO blend: pred = shipped x (1-w) + fprr_pred x w, w in {0..1}, rows with >= 3
  games of route data; others keep shipped.
  Buckets: FP/RR tercile x route-trend tercile (Jack's rule: high FP/RR + flat
  routes should NOT beat the projection; high FP/RR + rising routes should).
  ASCENDING flag: age <= 25, exp <= 3, 3-game route slope > +3/g AND target slope
  > +0.7/g, season-to-date PPG above the Clay prior -> residual + LOYO multiplier.
  Control flags: rising routes only (any age), young+efficient+flat routes.

Ship bar (README): <= -0.3% LOYO MSE with >= 5/7 years better. Log fprr_backtest.log;
results -> data/fprr_backtest.js (SIM_FPRR_BT) for the ZONES backtest block.
"""
import glob, json, os, re, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B
from bt_common import iter_samples, to_arrays, bucket_table
from backtest_target_area import mse
import build_scheme as BS

LOG = open(os.path.join(HERE, "fprr_backtest.log"), "w", encoding="utf-8")


class _Tee:
    def __init__(self, a, b): self.a, self.b = a, b
    def write(self, t): self.a.write(t); self.b.write(t); self.a.flush(); self.b.flush()
    def flush(self): self.a.flush(); self.b.flush()


sys.stdout = _Tee(sys.stdout, LOG)
def P(*a): print(" ".join(str(x) for x in a))

YEARS = list(range(2019, 2026))
K_PRIOR, K_POS = 150.0, 150.0
RES = {"loyo": [], "buckets": [], "flags": {}, "n": 0}
SHIP_PCT, SHIP_WINS = -0.30, 5


def loyo2(S, years, grid, predfn, label, family, pos):
    act = S["act"]; per = {}
    ys = [y for y in years if (S["year"] == y).any()]
    for v in grid:
        pred = predfn(v)
        per[v] = {y: mse(pred[S["year"] == y], act[S["year"] == y]) for y in ys}
    ship = per[grid[0]]; tot = n = wins = 0; picks = []
    for y in ys:
        m = S["year"] == y
        best = min(grid, key=lambda v: sum(per[v][yy] for yy in ys if yy != y))
        picks.append(best); e = mse(predfn(best)[m], act[m])
        tot += e * m.sum(); n += m.sum(); wins += e < ship[y]
    pooled_best = min(grid, key=lambda v: sum(per[v].values()))
    base_mse = sum(ship[y] * (S["year"] == y).sum() for y in ys) / n
    pct = (tot / n / base_mse - 1) * 100
    P(f"  {label}")
    P("    grid pooled MSE: " + "  ".join(f"{v:+.2f}:{sum(per[v].values())/len(ys):.3f}" for v in grid))
    P(f"    pooled best {pooled_best:+.2f} | LOYO MSE {tot/n:.4f} vs shipped {base_mse:.4f} ({pct:+.2f}%), years better {wins}/{len(ys)}, picks {picks}")
    RES["loyo"].append({"label": label, "family": family, "pos": pos, "n": int(n), "best": float(pooled_best), "pct": round(pct, 3),
                        "wins": int(wins), "years": len(ys), "picks": [float(p) for p in picks],
                        "verdict": "PASS" if (pct <= SHIP_PCT and wins >= SHIP_WINS) else ("lean" if (pct <= -0.1 and wins >= 4) else "FAIL")})


def load_pff(Y):
    """{norm name: {wk: (routes, tgt, rec, yds, td)}} for one season (PFF receiving summary)."""
    files = glob.glob(os.path.join(BS.PFF_WEEKLY, f"pff_receiving_summary_{Y}_w*.csv")) or \
            glob.glob(os.path.join(BS.PFF_WEEKLY, f"pff_receiving_{Y}_w*.csv"))
    out = defaultdict(dict)
    for f in files:
        wk = int(re.search(r"_w(\d+)\.csv$", f).group(1))
        d = pd.read_csv(f, low_memory=False, usecols=lambda c: c in ("player", "position", "routes", "targets", "receptions", "yards", "touchdowns"))
        for r in d.itertuples(index=False):
            if r.position not in ("WR", "TE", "HB", "RB", "FB"): continue
            rt = float(r.routes) if pd.notna(r.routes) else 0.0
            out[B.cal.norm(str(r.player))][wk] = (rt, float(r.targets or 0), float(r.receptions or 0), float(r.yards or 0), float(r.touchdowns or 0))
    return out


def pts_of(t):  # half-PPR receiving
    return 0.5 * t[2] + 0.1 * t[3] + 6.0 * t[4]


def main():
    P("loading PFF weekly receiving 2018-2025...")
    pff = {Y: load_pff(Y) for Y in range(2018, 2026)}
    for Y in pff: P(f"  {Y}: {len(pff[Y])} receivers")
    # position priors for FP/RR (pooled 2018-24, per position of the sample)
    pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), usecols=["gsis_id", "display_name", "birth_date", "rookie_season"], low_memory=False)
    bd = {r.gsis_id: r.birth_date for r in pl.itertuples(index=False) if pd.notna(r.gsis_id)}
    rk = {r.gsis_id: r.rookie_season for r in pl.itertuples(index=False) if pd.notna(r.gsis_id)}

    P("\nloading base samples (bt_common)...")
    S = [s for s in iter_samples(("WR", "TE")) if s["pos"] in ("WR", "TE")]
    A = to_arrays(S); n = len(S)
    P(f"  {n} WR/TE player-weeks")
    # position prior FP/RR from the samples' own seasons (pooled, prior years only -> leak-free enough at K=150)
    pos_prior = {}
    for pos in ("WR", "TE"):
        tot_p = tot_r = 0.0
        for Y in range(2018, 2025):
            for nm, wks in pff[Y].items():
                for t in wks.values():
                    tot_p += pts_of(t); tot_r += t[0]
        pos_prior[pos] = tot_p / tot_r if tot_r else 0.45
    P(f"  league FP/RR prior (all receivers pooled 2018-24): {pos_prior['WR']:.3f}")
    # per-position priors
    for pos, tag in (("WR", "WR"), ("TE", "TE")):
        pass

    fprr_pred = np.full(n, np.nan); proj_rt = np.full(n, np.nan); fprr_v = np.full(n, np.nan)
    fprr_notd = np.full(n, np.nan)
    rt_slope = np.full(n, np.nan); tg_slope = np.full(n, np.nan); rt_lvl = np.full(n, np.nan); games = np.zeros(n)
    young = np.zeros(n, dtype=bool); ppg_gt_clay = np.zeros(n, dtype=bool)
    for i, s in enumerate(S):
        Y, wk, nm = s["year"], s["wk"], B.cal.norm(s["name"])
        wks = pff[Y].get(nm, {})
        hist = sorted([(w, t) for w, t in wks.items() if w < wk and t[0] > 0])
        g = len(hist); games[i] = g
        if g >= 3:
            rts = [t[0] for _, t in hist]; tgs = [t[1] for _, t in hist]
            r3 = np.mean(rts[-3:]); rs2d = np.mean(rts)
            prev3 = np.mean(rts[-6:-3]) if g >= 6 else rs2d
            rt_slope[i] = r3 - prev3; tg_slope[i] = np.mean(tgs[-3:]) - (np.mean(tgs[-6:-3]) if g >= 6 else np.mean(tgs))
            rt_lvl[i] = r3
            pr = 0.5 * r3 + 0.5 * rs2d
            sp = sum(pts_of(t) for _, t in hist); sr = sum(rts)
            f_s2d = sp / sr if sr else 0.0
            pw = pff.get(Y - 1, {}).get(nm, {})
            spp = sum(pts_of(t) for t in pw.values()); srp = sum(t[0] for t in pw.values())
            f_pri = (spp / srp) if srp >= 50 else None
            prior = ((srp * (spp / srp) + K_POS * pos_prior["WR"]) / (srp + K_POS)) if f_pri is not None else pos_prior["WR"]
            f = (sr * f_s2d + K_PRIOR * prior) / (sr + K_PRIOR)
            fprr_v[i] = f; proj_rt[i] = pr
            sp_ntd = sum(0.5 * t[2] + 0.1 * t[3] for _, t in hist)
            spp_ntd = sum(0.5 * t[2] + 0.1 * t[3] for t in pw.values())
            pri_ntd = ((srp * (spp_ntd / srp) + K_POS * 0.20) / (srp + K_POS)) if srp >= 50 else 0.20
            fprr_notd[i] = (sr * (sp_ntd / sr if sr else 0.0) + K_PRIOR * pri_ntd) / (sr + K_PRIOR)
            fprr_pred[i] = pr * f * s["veg"] * s["fpa"]
        pid = s["pid"]
        age = None
        if pid and pid in bd and isinstance(bd[pid], str):
            try: age = Y - int(bd[pid][:4])
            except ValueError: age = None
        exp = (Y - int(rk[pid])) if pid and pid in rk and pd.notna(rk[pid]) else None
        young[i] = (age is not None and age <= 25) and (exp is not None and exp <= 3)
        ppg_gt_clay[i] = s["ppg"] > s["clay"]

    ok = np.isfinite(fprr_pred)
    P(f"\nrows with >= 3 games of route data: {ok.sum()} of {n}; young(<=25, exp<=3): {young.sum()}")
    ratio = A["act"] / A["shipped"]
    m = ok
    r_ship = float(np.corrcoef(A["shipped"][m], A["act"][m])[0, 1]); r_fp = float(np.corrcoef(fprr_pred[m], A["act"][m])[0, 1])
    P(f"corr with actual: shipped {r_ship:.3f} | FP/RR base {r_fp:.3f} | MSE shipped {mse(A['shipped'][m], A['act'][m]):.3f} vs FP/RR {mse(fprr_pred[m], A['act'][m]):.3f} (n={m.sum()})")
    P(f"mean actual {A['act'][m].mean():.2f} | shipped {A['shipped'][m].mean():.2f} | FP/RR base {fprr_pred[m].mean():.2f}")

    # ---- buckets: FP/RR x route trend (Jack's rule) ----
    def terc(v, mask):
        q = np.nanquantile(v[mask], [1 / 3, 2 / 3]); return q
    qf = terc(fprr_v, ok); qs = terc(rt_slope, ok)
    sets = []
    for fl, fm in (("lowFPRR", ok & (fprr_v <= qf[0])), ("midFPRR", ok & (fprr_v > qf[0]) & (fprr_v < qf[1])), ("hiFPRR", ok & (fprr_v >= qf[1]))):
        for sl, sm in (("routes falling", rt_slope <= qs[0]), ("routes flat", (rt_slope > qs[0]) & (rt_slope < qs[1])), ("routes rising", rt_slope >= qs[1])):
            sets.append((fl + " x " + sl, fm & sm))
    bucket_table(A, sets, "actual/shipped by FP/RR tercile x 3-game route trend tercile")
    for nm_, mm in sets:
        RES["buckets"].append({"name": nm_, "n": int(mm.sum()), "ratio": round(float(A["act"][mm].mean() / A["shipped"][mm].mean()), 3) if mm.sum() else None})
    P(f"  terciles: FP/RR {qf[0]:.3f}/{qf[1]:.3f}, route slope {qs[0]:+.1f}/{qs[1]:+.1f} routes/g")

    # ---- LOYO: blend shipped with the FP/RR base ----
    P("\n=== LOYO blend: shipped x (1-w) + FP/RR base x w (rows without route data keep shipped) ===")
    years = YEARS
    fp = np.where(ok, fprr_pred, A["shipped"])
    for pos in ("WR", "TE", None):
        pm = (A["pos"] == pos) if pos else np.ones(n, dtype=bool)
        Ssub = {"year": A["year"][pm], "act": A["act"][pm]}; ship = A["shipped"][pm]; fpp = fp[pm]
        loyo2(Ssub, years, [0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0], lambda w: ship * (1 - w) + fpp * w, f"FP/RR blend {pos or 'WR+TE'} (routes-gated; n route rows={int((ok & pm).sum())})", "blend w", pos or "WR+TE")
    # routes-level-only variant (no trend) and trend-heavier variant
    fp_lvl = np.where(ok, np.nan_to_num(rt_lvl) * np.nan_to_num(fprr_v) * A["veg"] * A["fpa"], A["shipped"])
    Ssub = {"year": A["year"], "act": A["act"]}
    loyo2(Ssub, years, [0.0, 0.1, 0.2, 0.3, 0.5], lambda w: A["shipped"] * (1 - w) + fp_lvl * w, "FP/RR blend, routes = last-3 only", "blend w", "WR+TE last3")

    # ---- ASCENDING flag ----
    P("\n=== ASCENDING flag (young, routes AND targets rising, PPG > Clay) ===")
    asc = ok & young & (rt_slope > 3) & (tg_slope > 0.7) & ppg_gt_clay
    rising = ok & (rt_slope > 3) & (tg_slope > 0.7)
    eff_flat = ok & young & (fprr_v >= qf[1]) & (rt_slope <= 1) & (rt_slope >= -1)
    eff_rising = ok & (fprr_v >= qf[1]) & (rt_slope > 3)
    flag_sets = [("ASCENDING (young+routes+tgts up+PPG>Clay)", asc), ("routes+targets rising (any age)", rising),
                 ("young + hi FP/RR + flat routes (part-timer)", eff_flat), ("hi FP/RR + routes rising", eff_rising)]
    bucket_table(A, flag_sets, "flag rows: actual / shipped")
    grid = (1.0, 1.03, 1.06, 1.10, 1.15, 0.97, 0.94)
    for lab, mk in flag_sets:
        RES["flags"][lab] = {"n": int(mk.sum()), "ratio": round(float(A["act"][mk].mean() / A["shipped"][mk].mean()), 3) if mk.sum() else None}
        if mk.sum() < 60:
            P(f"  {lab}: too few flagged rows ({mk.sum()})"); RES["flags"][lab]["verdict"] = "too few"; continue
        loyo2({"year": A["year"], "act": A["act"]}, years, list(grid), lambda mlt: np.where(mk, A["shipped"] * mlt, A["shipped"]), f"{lab} (flagged n={mk.sum()})", "flagged rows x m", lab)
        RES["flags"][lab]["verdict"] = RES["loyo"][-1]["verdict"]; RES["flags"][lab]["pct"] = RES["loyo"][-1]["pct"]; RES["flags"][lab]["best"] = RES["loyo"][-1]["best"]

    # ---- LEVEL terms: shipped x (1 + k z) ----
    P("\n=== LOYO level terms: shipped x (1 + k x z), z standardized within rows with route data ===")
    def zs(v):
        z = np.zeros(n); mm = ok & np.isfinite(v)
        z[mm] = np.clip((v[mm] - np.nanmean(v[mm])) / (np.nanstd(v[mm]) or 1.0), -3, 3); return z
    z_f = zs(fprr_v); z_s = zs(rt_slope); z_t = zs(tg_slope)
    z_n = zs(fprr_notd)
    # FP/RR relative to the player's own prior (hot vs his norm) - the regression candidate
    grid = [0.0, 0.01, 0.02, 0.04, 0.06, -0.01, -0.02, -0.04, -0.06]
    for pos in ("WR", "TE", None):
        pm = (A["pos"] == pos) if pos else np.ones(n, dtype=bool)
        Ssub = {"year": A["year"][pm], "act": A["act"][pm]}; ship = A["shipped"][pm]
        for lab, z in (("FP/RR level", z_f[pm]), ("FP/RR level WITHOUT TDs (rec+yds per route)", z_n[pm]), ("route slope (3g vs prior 3g)", z_s[pm]), ("target slope", z_t[pm]), ("route slope x (1 - FP/RR z)", (z_s * (1 - z_f))[pm])):
            loyo2(Ssub, years, grid, lambda k, z=z, ship=ship: ship * np.clip(1 + k * z, 0.7, 1.3), f"{lab} {pos or 'WR+TE'}", "level (1 + k z)", (pos or "WR+TE") + " " + lab)
    RES["n"] = int(n); RES["years"] = years; RES["updated"] = time.strftime("%Y-%m-%d %H:%M")
    RES["bar"] = {"pct": SHIP_PCT, "wins": SHIP_WINS}
    passed = [r for r in RES["loyo"] if r["verdict"] == "PASS"]
    RES["summary"] = (f"FP/RR base + ascending flag, {n} WR/TE player-weeks 2019-25 LOYO; " +
                      (f"{len(passed)} pass: " + "; ".join(r["pos"] + " " + f"{r['pct']:+.2f}%" for r in passed) if passed else "none pass the ship bar"))
    with open(os.path.join(HERE, "data", "fprr_backtest.js"), "w", encoding="utf-8") as f:
        f.write("// built by backtest_fprr.py - fantasy points per route run base + ascending-player flag LOYO verdicts; shown on the ZONES tab\n")
        f.write("window.SIM_FPRR_BT = "); json.dump(RES, f, separators=(",", ":")); f.write(";\n")
    P(f"\nwrote data/fprr_backtest.js: {RES['summary']}")
    P("done")


if __name__ == "__main__":
    main()
