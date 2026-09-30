#!/usr/bin/env python3
"""
LIVE DEPTH-CHART SLOT FOR ROOKIES (2026-09-16).

Jack: "build the live depth-chart slot for rookies next." The ladder's historical depth proxy (returning
teammates with a share) added nothing to the draft-pick rookie prior, but that proxy was crude. nflverse
publishes the real weekly depth charts (pbp_cache/depth_charts_{Y}.parquet: 2019-24 NFL.com format with
depth_team = string; 2025 ESPN format with a global pos_rank interleaved across slots) - the same ESPN charts
the engine reads live (data/sim_depth.js, flattened slot-by-depth by scripts/pull_depth_charts.py).

Feature per rookie player-week, PRE-GAME: string = depth level at his position (1 starter, 2 second string,
3+ deep). WR has 3 slots, so string = ceil(rank / 3); QB/RB/TE one slot. 2019-24: the week's chart (nflverse
scrapes during the game week); 2025: the latest chart dated before the game. Rookie rows = the ladder's rookie
player-weeks (Clay pool). Models per position, fit on the other seasons, graded as the prior alone on weeks 1-4
and inside the full Clay-free shadow v2.1 (shrink .8, per-position P, vets ADP .75 / 2nd-year .5):
  PICK          a + b ln(pick)                           (= shadow v2 fallback)
  PICK+STR      a + b ln(pick) + c [string 2] + d [string 3+]
  PICKxSTR      PICK x (actual / PICK) ratio by string bucket, from the other seasons
Also a read for VETERANS: actual / shadow prior by string (is a demoted veteran priced?).
Log rookie_depth_live.log; results -> data/rookie_depth_live.js (SIM_ROOKIEDEPTH_BT), ZONES tab.
"""
import json, os, sys, time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import bt_common as B
from backtest_target_area import mse

if __name__ == "__main__":   # importable (backtest_demoted_vets.py) without truncating this log
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "rookie_depth_live.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

YEARS, POS4, BANDS = NW.YEARS, NW.POS4, NW.BANDS
SLOTS = {"QB": 1, "RB": 1, "WR": 3, "TE": 1}
FIT_WK = 8
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "coverage": {}, "buckets": [], "priorAlone": [], "blended": [], "vets": []}


def load_depth():
    """{(Y, gsis, team, wk): string} for 2019-24; 2025 -> {(gsis, team): [(date, string), ...]}."""
    weekly, dated = {}, {}
    for Y in YEARS:
        d = pd.read_parquet(os.path.join(B.CACHE, f"depth_charts_{Y}.parquet"))
        if "depth_team" in d.columns:
            d = d[(d.game_type == "REG") & d.position.isin(POS4) & (d.depth_position == d.position) & d.gsis_id.notna()]
            for r in d.itertuples(index=False):
                try: s = int(r.depth_team)
                except Exception: continue
                k = (Y, r.gsis_id, B.tm(str(r.club_code)), int(r.week))
                weekly[k] = min(weekly.get(k, 99), s)
        else:
            d = d[d.pos_abb.isin(POS4) & d.gsis_id.notna()].copy()
            d["dt"] = pd.to_datetime(d.dt, utc=True).dt.tz_localize(None)
            for r in d.itertuples(index=False):
                s = int(np.ceil(int(r.pos_rank) / SLOTS[r.pos_abb]))
                dated.setdefault((r.gsis_id, B.tm(str(r.team))), []).append((r.dt, s))
            for k in dated: dated[k].sort()
    return weekly, dated


def main():
    t0 = time.time()
    P("=== Live depth-chart slot for rookies ===")
    S = NW.build_samples(); A = NW.arrays(S); n = len(S)
    weekly, dated = load_depth()
    act, year, wk, pos, g, ppg, clay, layers = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"]
    is_rookie, pid, team = A["rookie"], A["pid"], A["team"]
    games25 = B.load_games(2025)
    string = np.full(n, np.nan)
    for i in range(n):
        if pid[i] is None: continue
        if year[i] <= 2024:
            s = weekly.get((year[i], pid[i], team[i], wk[i]))
        else:
            gm = games25.get((team[i], wk[i])); lst = dated.get((pid[i], team[i]))
            s = None
            if gm and lst:
                before = [x for x in lst if x[0] < gm["date"]]
                s = before[-1][1] if before else None
        if s is not None: string[i] = s
    has = ~np.isnan(string)
    strb = np.where(has, np.minimum(string, 3), np.nan)   # 1, 2, 3+
    for ps in POS4:
        m = is_rookie & (pos == ps)
        RES["coverage"][ps] = {"rows": int(m.sum()), "withChart": int((m & has).sum())}
    P("  rookie rows with a pre-game chart: " + ", ".join(f"{ps} {RES['coverage'][ps]['withChart']}/{RES['coverage'][ps]['rows']}" for ps in POS4)
      + f" | all rows {100*has.mean():.0f}%")
    shipped = NW.blend(clay, g, ppg, NW.PRIOR_P) * layers
    lpick = np.log(np.where(np.isnan(A["pick"]), 262.0, A["pick"]))

    # ---- PICK model (LOYO) and the string buckets ----
    def fit_pick(tr):
        cf = {}
        for ps in POS4:
            m = tr & is_rookie & (pos == ps) & (wk <= FIT_WK)
            if m.sum() >= 40:
                cf[ps] = np.linalg.lstsq(np.column_stack([np.ones(m.sum()), lpick[m]]), act[m], rcond=None)[0]
        return cf
    pick_pr = np.full(n, np.nan)
    for y in YEARS:
        cf = fit_pick(year != y)
        for ps, b in cf.items():
            m = (year == y) & is_rookie & (pos == ps); pick_pr[m] = np.maximum(0.5, b[0] + b[1] * lpick[m])
    rk = is_rookie & (wk <= 4) & ~np.isnan(pick_pr)
    P(f"\n=== Rookie weeks 1-4 by depth string (n={rk.sum()}): actual / PICK prior, actual / Clay ===")
    for ps in POS4 + ("ALL",):
        line = f"  {ps:4s}"
        for lab, lo, hi in (("1st", 1, 1), ("2nd", 2, 2), ("3rd+", 3, 9), ("no chart", 0, 0)):
            mm = rk & ((pos == ps) if ps != "ALL" else True) & (((strb >= lo) & (strb <= hi)) if lo else ~has)
            if mm.sum() >= 15:
                line += f"  {lab}: n={mm.sum():3d} act/PICK {act[mm].mean()/pick_pr[mm].mean():.2f} act/Clay {act[mm].mean()/clay[mm].mean():.2f} act {act[mm].mean():4.1f} |"
                RES["buckets"].append({"pos": ps, "string": lab, "n": int(mm.sum()), "actOverPick": round(float(act[mm].mean() / pick_pr[mm].mean()), 3), "actOverClay": round(float(act[mm].mean() / clay[mm].mean()), 3), "act": round(float(act[mm].mean()), 2)})
            else:
                line += f"  {lab}: n={mm.sum():3d} |"
        P(line)

    # ---- models ----
    def design(m, kind):
        cols = [np.ones(m.sum()), lpick[m]]
        if kind == "PICK+STR":
            s2 = np.where(has[m], (strb[m] == 2).astype(float), 0.0); s3 = np.where(has[m], (strb[m] >= 3).astype(float), 0.0)
            cols += [s2, s3, (~has[m]).astype(float)]
        return np.column_stack(cols)
    def fit_apply(kind, tr, ap):
        out = np.full(n, np.nan)
        for ps in POS4:
            m = tr & is_rookie & (pos == ps) & (wk <= FIT_WK); a = ap & is_rookie & (pos == ps)
            if m.sum() < 40 or not a.any(): continue
            if kind == "PICKxSTR":
                b = np.linalg.lstsq(design(m, "PICK"), act[m], rcond=None)[0]
                base_m = np.maximum(0.5, design(m, "PICK") @ b); base_a = np.maximum(0.5, design(a, "PICK") @ b)
                ratio = {}
                for sb in (1, 2, 3):
                    mm = has[m] & (strb[m] == sb)
                    ratio[sb] = float(act[m][mm].sum() / base_m[mm].sum()) if mm.sum() >= 15 else 1.0
                mult = np.array([ratio.get(int(s), 1.0) if not np.isnan(s) else 1.0 for s in strb[a]])
                out[a] = base_a * mult
            else:
                b = np.linalg.lstsq(design(m, kind), act[m], rcond=None)[0]
                out[a] = np.maximum(0.5, design(a, kind) @ b)
        return out
    priors = {"CLAY": clay.copy(), "PICK": pick_pr}
    for kind in ("PICK+STR", "PICKxSTR"):
        pr = np.full(n, np.nan)
        for y in YEARS: pr = np.where(year == y, fit_apply(kind, year != y, year == y), pr)
        priors[kind] = pr
    P(f"\n=== Prior alone vs actual, rookie rows weeks 1-4 (LOYO) ===")
    P(f"  {'model':10s} {'MSE':>7s} {'vs Clay':>8s} {'vs PICK':>8s}  QB      RB      WR      TE    | charted rows | 2nd/3rd string rows")
    for lab in ("CLAY", "PICK", "PICK+STR", "PICKxSTR"):
        pr = priors[lab]; ok = rk & ~np.isnan(pr)
        row = {"model": lab, "n": int(ok.sum()), "mse": round(mse(pr[ok], act[ok]), 3), "vsClay": round((mse(pr[ok], act[ok]) / mse(clay[ok], act[ok]) - 1) * 100, 2),
               "vsPick": round((mse(pr[ok], act[ok]) / mse(pick_pr[ok], act[ok]) - 1) * 100, 2), "byPos": {}}
        for ps in POS4:
            mm = ok & (pos == ps); row["byPos"][ps] = round((mse(pr[mm], act[mm]) / mse(pick_pr[mm], act[mm]) - 1) * 100, 2) if mm.sum() >= 30 else None
        ch = ok & has; deep = ok & has & (strb >= 2)
        row["charted"] = round((mse(pr[ch], act[ch]) / mse(pick_pr[ch], act[ch]) - 1) * 100, 2) if ch.sum() >= 30 else None
        row["deep"] = round((mse(pr[deep], act[deep]) / mse(pick_pr[deep], act[deep]) - 1) * 100, 2) if deep.sum() >= 30 else None
        P(f"  {lab:10s} {row['mse']:7.2f} {row['vsClay']:+7.2f}% {row['vsPick']:+7.2f}%  " + " ".join(f"{(row['byPos'][ps] if row['byPos'][ps] is not None else float('nan')):+7.2f}" for ps in POS4)
          + f"  | {row['charted']} (n{ch.sum()}) | {row['deep']} (n{deep.sum()})")
        RES["priorAlone"].append(row)

    # ---- inside the Clay-free shadow v2.1 ----
    P("\n=== Inside the Clay-free shadow v2.1 (vets ADP .75 / 2nd-year .5, shrink .8, per-position P), ALL rows vs shipped ===")
    import backtest_rookie_prior as RP
    adp_map = RP.load_adp()
    adp = np.array([adp_map.get((y, NW.cal.norm(nm), ps), np.nan) for y, nm, ps in zip(year, A["name"], pos)])
    has_adp = ~np.isnan(adp); ladp = np.log(np.where(has_adp, adp, RP.ADP_CAP))
    h3, l8 = A["h3"], A["l8"]; has_h3, has_l8 = ~np.isnan(h3), ~np.isnan(l8)
    base = np.full(n, np.nan); both = has_h3 & has_l8
    base[both] = 0.5 * h3[both] + 0.5 * l8[both]; base[has_h3 & ~has_l8] = h3[has_h3 & ~has_l8]; base[~has_h3 & has_l8] = l8[~has_h3 & has_l8]
    for i in np.where(~np.isnan(base))[0]: base[i] = NW.age_adjust(pos[i], base[i], A["age"][i])
    oppcal = A["oppcal"]; vet_opp = (~np.isnan(oppcal)) & (A["seg"] != "rookie") & (~is_rookie) & ~np.isnan(base) & (base >= 4)
    base[vet_opp] = oppcal[vet_opp]
    adp_curve = np.full(n, np.nan)
    for y in YEARS:
        for ps in POS4:
            tr = (year != y) & (pos == ps) & has_adp & (wk <= FIT_WK); ap = (year == y) & (pos == ps) & has_adp
            if tr.sum() >= 60 and ap.any():
                b = np.linalg.lstsq(np.column_stack([np.ones(tr.sum()), ladp[tr]]), act[tr], rcond=None)[0]
                adp_curve[ap] = np.maximum(0.5, b[0] + b[1] * ladp[ap])
    yr2 = A["exp"] == 1
    wv = np.where(yr2, 0.5, 0.75); sel = ~is_rookie & ~np.isnan(adp_curve) & ~np.isnan(base)
    base = np.where(sel, (1 - wv) * base + wv * adp_curve, base)
    pos_mean = {ps: NW.loyo_const(A, lambda ps=ps: (pos == ps), YEARS) for ps in POS4}
    fb_pos = np.array([pos_mean[ps].get(y, np.nan) for ps, y in zip(pos, year)])
    PPOS = {"QB": 12, "RB": 5, "WR": 8, "TE": 8}; K = 0.8; Pvec = np.array([PPOS[ps] for ps in pos], dtype=float)
    def shadow_pred(rp):
        fb = fb_pos.copy(); m = is_rookie & ~np.isnan(rp); fb[m] = rp[m]
        pr = base.copy(); miss = np.isnan(pr); pr[miss] = fb[miss]
        pr = fb_pos + K * (pr - fb_pos)
        return NW.blend(pr, g, ppg, Pvec) * layers
    ref = shadow_pred(priors["PICK"])
    P(f"  {'fallback':10s} {'vs shipped':>10s} {'yrs':>4s} {'vs v2.1':>9s} {'yrs':>4s} | rookie rows | wk1 | wk2-4")
    for lab in ("CLAY", "PICK", "PICK+STR", "PICKxSTR"):
        pred = shadow_pred(priors[lab])
        pc, w, ny = NW.pct_vs(pred, shipped, act, year); pv, wvv, _ = NW.pct_vs(pred, ref, act, year)
        rr = is_rookie; b1 = wk == 1; b24 = (wk >= 2) & (wk <= 4)
        row = {"model": lab, "pct": round(pc, 3), "wins": int(w), "years": ny, "vsRef": round(pv, 3), "vsRefWins": int(wvv),
               "rookie": round((mse(pred[rr], act[rr]) / mse(shipped[rr], act[rr]) - 1) * 100, 2),
               "wk1": round((mse(pred[b1], act[b1]) / mse(shipped[b1], act[b1]) - 1) * 100, 2), "wk24": round((mse(pred[b24], act[b24]) / mse(shipped[b24], act[b24]) - 1) * 100, 2)}
        P(f"  {lab:10s} {row['pct']:+9.2f}% {w}/{ny} {row['vsRef']:+8.2f}% {wvv}/{ny} | {row['rookie']:+.2f}% | {row['wk1']:+.2f}% | {row['wk24']:+.2f}%")
        RES["blended"].append(row)
    # forward for the string models
    for kind in ("PICK+STR", "PICKxSTR"):
        fwd = np.full(n, np.nan)
        for y in YEARS[2:]: fwd = np.where(year == y, fit_apply(kind, year < y, year == y), fwd)
        fm = year >= YEARS[2]
        pf = shadow_pred(np.where(fm, fwd, priors["PICK"]))
        fp, fw, fy = NW.pct_vs(pf[fm], shipped[fm], act[fm], year[fm]); fr, frw, _ = NW.pct_vs(pf[fm], ref[fm], act[fm], year[fm])
        rr = fm & is_rookie
        P(f"  FORWARD {kind} (2021-25): vs shipped {fp:+.2f}% ({fw}/{fy}) | vs v2.1 {fr:+.2f}% ({frw}/{fy}) | rookie rows vs v2.1 {(mse(pf[rr], act[rr]) / mse(ref[rr], act[rr]) - 1) * 100:+.2f}%")
        for r in RES["blended"]:
            if r["model"] == kind: r["forward"] = {"pct": round(fp, 3), "wins": int(fw), "years": fy, "vsRef": round(fr, 3), "vsRefWins": int(frw)}

    # ---- veterans read: actual / v2.1 prior by string ----
    P("\n=== Veterans (weeks 1-8): actual / shadow v2.1 prior by pre-game depth string ===")
    vp = fb_pos + K * (np.where(np.isnan(base), fb_pos, base) - fb_pos)
    vm = ~is_rookie & ~np.isnan(base) & (wk <= 8)
    for ps in POS4:
        line = f"  {ps:4s}"
        for lab, lo, hi in (("1st", 1, 1), ("2nd", 2, 2), ("3rd+", 3, 9)):
            mm = vm & (pos == ps) & has & (strb >= lo) & (strb <= hi)
            if mm.sum() >= 30:
                line += f"  {lab}: n={mm.sum():4d} act/prior {act[mm].mean()/vp[mm].mean():.2f} act/shipped {act[mm].mean()/shipped[mm].mean():.2f} |"
                RES["vets"].append({"pos": ps, "string": lab, "n": int(mm.sum()), "actOverPrior": round(float(act[mm].mean() / vp[mm].mean()), 3), "actOverShipped": round(float(act[mm].mean() / shipped[mm].mean()), 3)})
        P(line)
    # LOYO dock for demoted vets (string >= 2, prior >= 6) on the v2.1 shadow
    demoted = ~is_rookie & has & (strb >= 2) & ~np.isnan(base)
    NW.RES["sweeps"] = []
    NW.loyo_pick(A, shipped, [1.0, 0.9, 0.8, 0.7, 0.6, 1.1], lambda m_: shadow_pred(priors["PICK"]) * np.where(demoted, m_, 1.0), "demoted-vet multiplier on the v2.1 shadow (string >= 2)", "vetdock", mask=demoted)
    RES["vetDock"] = NW.RES["sweeps"][-1]
    for ps in POS4:
        NW.RES["sweeps"] = []
        NW.loyo_pick(A, shipped, [1.0, 0.9, 0.8, 0.7, 0.6, 1.1], lambda m_: shadow_pred(priors["PICK"]) * np.where(demoted, m_, 1.0), f"  demoted {ps}", "vetdock", mask=demoted & (pos == ps))
        RES["vetDock" + ps] = NW.RES["sweeps"][-1]

    # all-seasons coefficients for the engine: [a, b ln(pick), c string2, d string3+, e no-chart]
    RES["coefStr"] = {}
    for ps in POS4:
        m = is_rookie & (pos == ps) & (wk <= FIT_WK)
        if m.sum() >= 40:
            RES["coefStr"][ps] = [round(float(x), 4) for x in np.linalg.lstsq(design(m, "PICK+STR"), act[m], rcond=None)[0]]
    P("  PICK+STR coefficients (all seasons; a, b ln(pick), string2, string3+, no chart): " + json.dumps(RES["coefStr"]))
    best = min(("PICK+STR", "PICKxSTR"), key=lambda k: [r for r in RES["priorAlone"] if r["model"] == k][0]["mse"])
    pa = [r for r in RES["priorAlone"] if r["model"] == best][0]; bl = [r for r in RES["blended"] if r["model"] == best][0]
    RES["best"] = best
    RES["summary"] = (f"Depth string on top of the draft pick, rookie weeks 1-4: {best} {pa['vsPick']:+.2f}% vs PICK ({pa['vsClay']:+.2f}% vs Clay); "
                      f"inside the shadow {bl['vsRef']:+.2f}% vs v2.1 ({bl['vsRefWins']}/{bl['years']}), forward {bl.get('forward', {}).get('vsRef', float('nan')):+.2f}%.")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "rookie_depth_live.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_ROOKIEDEPTH_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/rookie_depth_live.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
