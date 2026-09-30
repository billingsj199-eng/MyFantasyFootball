#!/usr/bin/env python3
"""
DO DEFENSIVE DATA / ADVANCED ANALYTICS HELP THE WEEKLY *RANKINGS*? (2026-09-17)

Jack: "lets not worry about season long too much as we are in season now and try to maximize our in season week
specific rankings - do any of the defensive data or advanced analytics help our weekly data?" Every matchup layer so
far was tuned on points error (MSE). Ranking only cares about ORDER inside a position in a given week, so a matchup
tilt can be worth more (or less) for ranks than its MSE-optimal strength. Base = shadow v2.18 (rate x live layers).
Objective = mean within-position-week Spearman on the top 150 (and pairwise order accuracy), MSE kept as a guardrail.
  1. ablation      what the shipped layers are worth for ranking: none / Vegas only / FPA only / Vegas x FPA / all
  2. re-tune       exponent on the Vegas multiplier and on the FPA multiplier per position (shipped = 1.0)
  3. new tilts     x exp(c z), z = walk-forward standardized opponent / context metric, c per position LOYO:
                   PFF opponent coverage grade, pass-rush grade, pass-rush win rate, run-defense grade (season to
                   date, shrunk to last season, weeks before the game only); opponent man-coverage rate x the
                   player's man/zone YPRR gap; own OL pass-block / run-block grade now; spread, game total, dome, wind
Selection LOYO per position on the rank objective, then forward 2021-25.
Log matchup_rank.log; results -> data/matchup_rank.js (SIM_MATCHUP_RANK_BT).
"""
import json, os, sys, time, warnings
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy.stats import rankdata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B
import backtest_noclay_weekly as NW
import research_clay_vs_shadow as CS
import backtest_season_long as SL
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "matchup_rank.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
YEARS, POS4 = NW.YEARS, NW.POS4
PFF2NFL = {"ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "LA": "LA", "LV": "LV", "OAK": "LV", "SD": "LAC", "SL": "LA"}
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "ablation": [], "retune": [], "tilts": [], "combo": []}


def pff_defense():
    """team-week defensive grades (snap-weighted) -> walk-forward (season to date shrunk to last season), z-scored per season-week."""
    raw = defaultdict(dict)
    for Y in range(YEARS[0] - 1, YEARS[-1] + 1):
        for w in range(1, 19):
            f = os.path.join(B.CACHE, "pff", "weekly", f"pff_defense_summary_{Y}_w{w}.csv"); f2 = os.path.join(B.CACHE, "pff", "weekly", f"pff_defense_pass_rush_{Y}_w{w}.csv")
            if not os.path.exists(f): continue
            d = pd.read_csv(f); d["tm"] = d.team_name.map(lambda t: PFF2NFL.get(t, t))
            wr = None
            if os.path.exists(f2):
                pr = pd.read_csv(f2); pr["tm"] = pr.team_name.map(lambda t: PFF2NFL.get(t, t)); wr = pr
            for tm, gdf in d.groupby("tm"):
                def wavg(col, wcol):
                    if col not in gdf or wcol not in gdf: return np.nan
                    v, ww = gdf[col].values.astype(float), gdf[wcol].values.astype(float); ok = ~np.isnan(v) & ~np.isnan(ww) & (ww > 0)
                    return float(np.average(v[ok], weights=ww[ok])) if ok.sum() >= 3 else np.nan
                row = {"cov": wavg("grades_coverage_defense", "snap_counts_coverage"), "rush": wavg("grades_pass_rush_defense", "snap_counts_pass_rush"),
                       "run": wavg("grades_run_defense", "snap_counts_run_defense" if "snap_counts_run_defense" in gdf else "snap_counts_defense"), "prwr": np.nan}
                if wr is not None:
                    q = wr[wr.tm == tm]
                    if len(q) and "pass_rush_wins" in q and "pass_rush_opp" in q and q.pass_rush_opp.sum() > 0: row["prwr"] = float(q.pass_rush_wins.sum() / q.pass_rush_opp.sum())
                raw[(Y, tm)][w] = row
    return raw


def main():
    t0 = time.time()
    P("=== Do defensive data / advanced analytics help the weekly RANKINGS? (top 150, within position-week) ===")
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
    veg = np.where(has & (col("veg") > 0), col("veg"), 1.0); fpa = np.where(has & (col("fpa_mult") > 0), col("fpa_mult"), 1.0); rest = layers / (veg * fpa)
    opp = np.where(has, C["opp"].values[np.maximum(idx, 0)], None)
    # ---- walk-forward PFF opponent defense ----
    raw = pff_defense(); K = 4.0; D = {k: np.full(n, np.nan) for k in ("cov", "rush", "run", "prwr")}
    for i in range(n):
        if opp[i] is None: continue
        cur = raw.get((int(year[i]), opp[i]), {}); py = raw.get((int(year[i]) - 1, opp[i]), {})
        for k in D:
            std = [cur[w][k] for w in cur if w < wk[i] and not np.isnan(cur[w][k])]; pyv = [py[w][k] for w in py if not np.isnan(py[w][k])]
            if not std and not pyv: continue
            a = np.mean(std) if std else np.nan; b = np.mean(pyv) if pyv else np.nan; ns = len(std)
            D[k][i] = a if np.isnan(b) else (b if np.isnan(a) else (K * b + ns * a) / (K + ns))
    top150 = adp <= 150
    groups = defaultdict(list)
    for i in np.where(top150)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
    groups = {k: np.array(v) for k, v in groups.items() if len(v) >= 8}
    def zscore_within_week(v):
        out = np.full(n, 0.0); byw = defaultdict(list)
        for i in np.where(~np.isnan(v))[0]: byw[(int(year[i]), int(wk[i]))].append(i)
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
    ALLY = set(YEARS)
    # ---- 1. ablation ----
    P("\n=== 1. What are the shipped matchup layers worth for RANKING? (mean Spearman | pair % | MSE), all seasons ===")
    base_rate = RATE[False]
    for lab, mult in (("no layers at all", np.ones(n)), ("Vegas implied-total mult only", veg), ("FPA matchup mult only", fpa), ("Vegas x FPA", veg * fpa), ("ALL live layers (shipped)", layers)):
        cells = []
        for ps in POS4:
            r, pwc, ms = metrics(base_rate * mult, ps, ALLY); cells.append(f"{ps} rho {r:.4f} pair {pwc:.2f}% mse {ms:.2f}"); RES["ablation"].append({"layers": lab, "pos": ps, "rho": round(r, 4), "pair": round(pwc, 2), "mse": round(ms, 2)})
        P(f"  {lab:32s} " + " | ".join(cells))
    # ---- generic LOYO tilt selection on the rank objective ----
    def loyo_tilt(feat, grid, ps, fwd=False, base_mult=None):
        """pred = rate x base_mult x exp(c x feat); choose c per held-out season on the other seasons' mean Spearman."""
        rate = RATE[fwd]; bm = layers if base_mult is None else base_mult; ys = YEARS[2:] if fwd else YEARS
        cand = {c: rate * bm * np.exp(c * feat) for c in grid}; stat = {c: {y: metrics(cand[c], ps, {y}) for y in YEARS} for c in grid}
        picks, out_rho, out_pw, out_mse, base_rho, base_pw, base_mse, wins = [], [], [], [], [], [], [], 0
        for y in ys:
            tr = [yy for yy in YEARS if (yy < y if fwd else yy != y)]
            best = max(grid, key=lambda c: np.mean([stat[c][yy][0] for yy in tr])); picks.append(best)
            out_rho.append(stat[best][y][0]); out_pw.append(stat[best][y][1]); out_mse.append(stat[best][y][2]); base_rho.append(stat[0.0][y][0]); base_pw.append(stat[0.0][y][1]); base_mse.append(stat[0.0][y][2])
            wins += int(stat[best][y][0] > stat[0.0][y][0] + 1e-9)
        return {"pos": ps, "picks": picks, "dRho": round(float(np.mean(out_rho) - np.mean(base_rho)), 4), "dPair": round(float(np.mean(out_pw) - np.mean(base_pw)), 3), "dMsePct": round(float((np.mean(out_mse) / np.mean(base_mse) - 1) * 100), 2), "wins": wins, "years": len(ys), "baseRho": round(float(np.mean(base_rho)), 4)}
    def show(title, feat, grid, positions, store, note=""):
        P(f"  -- {title} {note}")
        for ps in positions:
            a = loyo_tilt(feat, grid, ps); f = loyo_tilt(feat, grid, ps, fwd=True); a["label"] = title; a["fwd"] = {k: f[k] for k in ("dRho", "dPair", "dMsePct", "wins", "years", "picks")}; store.append(a)
            flag = "  <== PASS" if (a["dRho"] >= 0.004 and a["wins"] >= 5 and f["dRho"] > 0 and f["wins"] >= 3) else ""
            P(f"     {ps}: LOYO rho {a['dRho']:+.4f} (base {a['baseRho']:.3f}), pair {a['dPair']:+.2f} pts, MSE {a['dMsePct']:+.2f}%, seasons better {a['wins']}/{a['years']}, picks {sorted(set(a['picks']))} | forward rho {f['dRho']:+.4f}, pair {f['dPair']:+.2f}, MSE {f['dMsePct']:+.2f}%, {f['wins']}/{f['years']}{flag}")
    # ---- 2. re-tune the shipped multipliers for rank ----
    P("\n=== 2. Re-tune the shipped multipliers for ranking: extra exponent c on top of 1.0 (c = 0 keeps the shipped strength; +1 doubles it; -1 removes it) ===")
    EG = [-1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 3.0]
    show("Vegas implied-total multiplier", np.log(np.clip(veg, 0.5, 2.0)), EG, POS4, RES["retune"]); show("FPA matchup multiplier", np.log(np.clip(fpa, 0.5, 2.0)), EG, POS4, RES["retune"])
    # ---- 3. new defensive / advanced tilts ----
    P("\n=== 3. New tilts x exp(c z): z = standardized within the week, + = more of the thing; c per position LOYO on rank ===")
    CG = [-0.10, -0.06, -0.03, 0.0, 0.03, 0.06, 0.10]
    feats = [("PFF opponent COVERAGE grade (season to date)", zscore_within_week(D["cov"]), ("QB", "WR", "TE", "RB")), ("PFF opponent PASS-RUSH grade", zscore_within_week(D["rush"]), ("QB", "WR", "TE")),
             ("PFF opponent pass-rush WIN RATE", zscore_within_week(D["prwr"]), ("QB", "WR", "TE")), ("PFF opponent RUN-DEFENSE grade", zscore_within_week(D["run"]), ("RB", "QB")),
             ("opponent man-coverage rate x player's man-vs-zone YPRR gap", zscore_within_week(col("man_gap_x_opp")), ("WR", "TE")), ("own OL pass-block grade now", zscore_within_week(col("ol_pb_now")), ("QB", "WR", "TE")),
             ("own OL run-block grade now", zscore_within_week(col("ol_rb_now")), ("RB",)), ("own OL pass-block DROP (injuries)", zscore_within_week(col("ol_pb_drop")), ("QB", "WR")),
             ("spread (+ = favored)", zscore_within_week(-col("spread")), POS4), ("game total", zscore_within_week(col("game_total")), POS4), ("wind", zscore_within_week(col("wind")), ("QB", "WR", "TE")), ("dome", zscore_within_week(col("dome")), ("QB", "WR", "TE"))]
    cover = {k: int((~np.isnan(D[k]) & top150).sum()) for k in D}; P(f"  PFF opponent defense coverage on top-150 rows: {cover} of {int(top150.sum())}")
    for title, z, positions in feats: show(title, z, CG, positions, RES["tilts"])
    # ---- 4. QB shootout signal, fine sweep at fixed strength: rank gain vs points-error cost ----
    P("=== 4. QB fine sweep at FIXED c (no selection): game total vs opponent implied total; all seasons and forward-era seasons ===")
    RES["qbFine"] = []
    for title, z in (("game total", zscore_within_week(col("game_total"))), ("opponent implied total", zscore_within_week(col("opp_implied")))):
        b_all = metrics(RATE[False] * layers, "QB", ALLY)
        for c in (0.02, 0.03, 0.04, 0.06, 0.08):
            pr = RATE[False] * layers * np.exp(c * z); m_all = metrics(pr, "QB", ALLY)
            wins = sum(1 for y in YEARS if metrics(pr, "QB", {y})[0] > metrics(RATE[False] * layers, "QB", {y})[0]); winp = sum(1 for y in YEARS if metrics(pr, "QB", {y})[1] > metrics(RATE[False] * layers, "QB", {y})[1])
            row = {"feat": title, "c": c, "dRho": round(m_all[0] - b_all[0], 4), "dPair": round(m_all[1] - b_all[1], 2), "dMsePct": round((m_all[2] / b_all[2] - 1) * 100, 2), "rhoWins": wins, "pairWins": winp}
            RES["qbFine"].append(row); P(f"     {title:24s} c={c:.2f}: rho {row['dRho']:+.4f} ({wins}/7 seasons), pair {row['dPair']:+.2f} pts ({winp}/7), MSE {row['dMsePct']:+.2f}%")
    passed = [t for t in RES["tilts"] + RES["retune"] if (t["dRho"] >= 0.004 and t["wins"] >= 5 and t["fwd"]["dRho"] > 0 and t["fwd"]["wins"] >= 3)]
    RES["passed"] = [{"label": t["label"], "pos": t["pos"], "dRho": t["dRho"], "wins": t["wins"], "picks": t["picks"], "fwd": t["fwd"]} for t in passed]
    RES["summary"] = (f"{len(RES['tilts']) + len(RES['retune'])} position-level tests on the rank objective (LOYO rho gain >= .004 in 5+ of 7 seasons AND positive forward in 3+ of 5): {len(passed)} pass"
                      + (": " + "; ".join(f"{t['label']} [{t['pos']}] rho {t['dRho']:+.4f} ({t['wins']}/7), fwd {t['fwd']['dRho']:+.4f}" for t in passed) if passed else "") + ".")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "matchup_rank.js"), "w", encoding="utf-8") as fh:
        fh.write("window.SIM_MATCHUP_RANK_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/matchup_rank.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
