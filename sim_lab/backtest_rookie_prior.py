#!/usr/bin/env python3
"""
MARKET-INFORMED ROOKIE PRIOR (2026-09-16).

Jack: "build the market-informed rookie prior next." The Clay-free ladder (backtest_noclay_weekly.py) left its
gap in weeks 1-4, where rookies have no history and the shadow's fallback is a + b ln(draft pick). Clay still
knew rookies better (prior-alone MSE weeks 1-4: Clay 39.6 vs log-pick 41.9). The market prices the same things
Clay does (camp reports, depth chart, role) and it is Clay-free:
  ADP   FFC half-PPR 12-team preseason ADP 2019-25 (data/ffc_adp_hist.json, ~200 players a year; a rookie
        outside the top ~180 = "undrafted in fantasy", its own signal)
  JM    the site's prospect score (repo data/jm_scores.json; tuned with hindsight - treated as a caveat)
  pick  NFL draft slot (nflverse draft_picks)
Rookie rows = the ladder's rookie player-weeks (Clay pool, 2019-25). Per position, fit on the OTHER seasons:
  PICK      ppg ~ a + b ln(pick)                                  (= shadow v2 fallback)
  ADP       ppg ~ a + b ln(adp) + c [no ADP]
  PICK+ADP  ppg ~ a + b ln(pick) + c ln(adp) + d [no ADP]
  +JM       ... + e JM + f [no JM]
  CLAY      Clay's own per-game number (the live fallback)
Graded (1) as the prior alone on weeks 1-4 rookie rows (the weeks that matter), (2) inside the full Clay-free
shadow (combined candidate: shrink .8, per-position P) on ALL rows vs shipped and vs the v2 shadow.
Appendix: the same ADP curve as a market prior for VETERANS (blend weight into the history prior, LOYO), since
team-changers (+1.5%) and 2nd-year players (+0.9%) were the other open gaps.
Log rookie_prior_backtest.log; results -> data/rookie_prior_backtest.js (SIM_ROOKIEPRIOR_BT), ZONES tab.
"""
import json, os, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import backtest_sim_calibration as cal
from backtest_target_area import mse

if __name__ == "__main__":   # importable (backtest_rookie_depth_live.py) without truncating this log
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "rookie_prior_backtest.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

YEARS = NW.YEARS; POS4 = NW.POS4; BANDS = NW.BANDS
ADP_CAP = 181.0    # FFC lists ~15 rounds x 12; anyone unlisted = "undrafted", coded at the cap with an indicator
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "priorAlone": [], "blended": [], "vets": [], "coef": {}}


def load_adp():
    d = json.load(open(os.path.join(HERE, "data", "ffc_adp_hist.json"), encoding="utf-8"))
    out = {}
    for y, blk in d.items():
        for p in blk["players"]:
            pos = {"PK": "K", "DEF": "DST"}.get(p["pos"], p["pos"])
            out[(int(y), cal.norm(p["name"]), pos)] = float(p["adp"])
    return out


def load_jm():
    d = json.load(open(os.path.join(cal.REPO, "data", "jm_scores.json"), encoding="utf-8"))["scores"]
    return {(cal.norm(n), v.get("pos")): (float(v["jm"]), v.get("yr")) for n, v in d.items() if isinstance(v.get("jm"), (int, float))}


def lstsq(X, y):
    b, *_ = np.linalg.lstsq(X, y, rcond=None); return b


def main():
    t0 = time.time()
    P("=== Market-informed rookie prior ===")
    S = NW.build_samples(); A = NW.arrays(S); n = len(S)
    adp_map, jm_map = load_adp(), load_jm()
    act, year, wk, pos, g, ppg, clay, layers = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"]
    is_rookie = A["rookie"]; names = A["name"]
    adp = np.array([adp_map.get((y, cal.norm(nm), ps), np.nan) for y, nm, ps in zip(year, names, pos)])
    jm = np.array([jm_map.get((cal.norm(nm), ps), (np.nan, None))[0] for nm, ps in zip(names, pos)])
    has_adp, has_jm = ~np.isnan(adp), ~np.isnan(jm)
    ladp = np.log(np.where(has_adp, adp, ADP_CAP))
    lpick = np.log(np.where(np.isnan(A["pick"]), 262.0, A["pick"]))
    P(f"  {n} player-weeks; rookies {is_rookie.sum()} rows / {len(set(zip(year[is_rookie], names[is_rookie])))} rookie-seasons | "
      f"rookie rows with FFC ADP {int((is_rookie & has_adp).sum())} ({100*(is_rookie & has_adp).mean()/max(1e-9, is_rookie.mean()):.0f}%), with JM {int((is_rookie & has_jm).sum())} ({100*(is_rookie & has_jm).mean()/max(1e-9, is_rookie.mean()):.0f}%) | "
      f"all rows with ADP {100*has_adp.mean():.0f}%")
    shipped = NW.blend(clay, g, ppg, NW.PRIOR_P) * layers

    # ---- design matrices per model ----
    def design(model, m):
        cols = [np.ones(m.sum())]
        if "pick" in model: cols.append(lpick[m])
        if "adp" in model: cols += [ladp[m], (~has_adp[m]).astype(float)]
        if "jm" in model:
            jmf = np.where(has_jm[m], jm[m], 0.0); cols += [jmf, (~has_jm[m]).astype(float)]
        return np.column_stack(cols)

    MODELS = [("PICK", ["pick"]), ("ADP", ["adp"]), ("PICK+ADP", ["pick", "adp"]), ("PICK+ADP+JM", ["pick", "adp", "jm"]), ("ADP+JM", ["adp", "jm"])]
    FIT_WK = 8   # fit the level on rookie rows through week 8 (early role), graded on weeks 1-4

    def fit_apply(model, train_mask, apply_mask):
        out = np.full(n, np.nan)
        for ps in POS4:
            tr = train_mask & is_rookie & (pos == ps) & (wk <= FIT_WK)
            ap = apply_mask & is_rookie & (pos == ps)
            if tr.sum() < 40 or not ap.any():
                continue
            b = lstsq(design(model, tr), act[tr])
            out[ap] = np.maximum(0.5, design(model, ap) @ b)
        return out

    priors = {"CLAY": clay.copy()}
    for lab, model in MODELS:
        pr = np.full(n, np.nan)
        for y in YEARS:
            pr = np.where(year == y, fit_apply(model, year != y, year == y), pr)
        priors[lab] = pr
    # ADP CURVE fit on EVERYONE with an ADP (vets + rookies, other seasons, weeks <= FIT_WK): E[PPG | ADP, pos].
    # Stable (thousands of rows a position) where the rookie-only ADP fit was not (rookie TEs).
    def adp_curve_fit(train_mask):
        cf = {}
        for ps in POS4:
            tr = train_mask & (pos == ps) & has_adp & (wk <= FIT_WK)
            if tr.sum() >= 60:
                cf[ps] = lstsq(np.column_stack([np.ones(tr.sum()), ladp[tr]]), act[tr])
        return cf
    def adp_curve_apply(cf, apply_mask):
        out = np.full(n, np.nan)
        for ps, b in cf.items():
            ap = apply_mask & (pos == ps) & has_adp
            out[ap] = np.maximum(0.5, b[0] + b[1] * ladp[ap])
        return out
    adp_curve = np.full(n, np.nan)
    for y in YEARS:
        adp_curve = np.where(year == y, adp_curve_apply(adp_curve_fit(year != y), year == y), adp_curve)
    RES["adpCurveAll"] = {ps: [round(float(x), 4) for x in b] for ps, b in adp_curve_fit(np.ones(n, dtype=bool)).items()}
    # rookie hybrids: listed rookies take the curve (or half curve / half pick), unlisted keep the pick model
    hyb = priors["PICK"].copy(); m = is_rookie & has_adp & ~np.isnan(adp_curve); hyb[m] = adp_curve[m]; priors["CURVE|PICK"] = hyb
    hyb2 = priors["PICK"].copy(); hyb2[m] = 0.5 * adp_curve[m] + 0.5 * priors["PICK"][m]; priors["CURVE.5+PICK.5"] = hyb2
    MODELS = MODELS + [("CURVE|PICK", ["pick"]), ("CURVE.5+PICK.5", ["pick"])]
    # ---- (1) prior alone, rookie rows weeks 1-4 ----
    rk = is_rookie & (wk <= 4)
    P(f"\n=== Prior alone vs actual, rookie rows weeks 1-4 (n={rk.sum()}; LOYO fits) ===")
    P(f"  {'model':14s} {'MSE':>7s} {'vs Clay':>8s}  QB      RB      WR      TE     | ADP-listed rows | unlisted rows")
    for lab in ["CLAY"] + [m for m, _ in MODELS]:
        pr = priors[lab]; ok = rk & ~np.isnan(pr)
        row = {"model": lab, "n": int(ok.sum()), "mse": round(mse(pr[ok], act[ok]), 3), "vsClay": round((mse(pr[ok], act[ok]) / mse(clay[ok], act[ok]) - 1) * 100, 2), "byPos": {}}
        for ps in POS4:
            mm = ok & (pos == ps); row["byPos"][ps] = round((mse(pr[mm], act[mm]) / mse(clay[mm], act[mm]) - 1) * 100, 2) if mm.sum() >= 30 else None
        la, ua = ok & has_adp, ok & ~has_adp
        row["listed"] = round((mse(pr[la], act[la]) / mse(clay[la], act[la]) - 1) * 100, 2) if la.sum() >= 30 else None
        row["unlisted"] = round((mse(pr[ua], act[ua]) / mse(clay[ua], act[ua]) - 1) * 100, 2) if ua.sum() >= 30 else None
        P(f"  {lab:14s} {row['mse']:7.2f} {row['vsClay']:+7.2f}%  " + " ".join(f"{(row['byPos'][ps] if row['byPos'][ps] is not None else float('nan')):+7.2f}" for ps in POS4)
          + f"   | {row['listed']:+.2f}% (n{la.sum()})" + (f" | {row['unlisted']:+.2f}% (n{ua.sum()})" if row["unlisted"] is not None else " | -"))
        RES["priorAlone"].append(row)
    # calibration read: actual/prior by ADP tercile for the ADP model
    P("\n  actual / prior by ADP bucket (PICK+ADP), rookie weeks 1-4:")
    pr = priors["PICK+ADP"]
    for lab, lo, hi in (("ADP 1-60", 0, 60), ("ADP 61-120", 60, 120), ("ADP 121-180", 120, 181), ("unlisted", 181, 9999)):
        mm = rk & (np.where(has_adp, adp, 999) > lo) & (np.where(has_adp, adp, 999) <= hi) & ~np.isnan(pr)
        if mm.sum() >= 20:
            P(f"    {lab:12s} n={mm.sum():4d}  actual/prior {act[mm].mean()/pr[mm].mean():.3f}  actual/Clay {act[mm].mean()/clay[mm].mean():.3f}  mean actual {act[mm].mean():.2f}")

    # ---- (2) inside the full Clay-free shadow (combined candidate) ----
    P("\n=== Inside the Clay-free shadow (shrink .8, per-position P): fallback swapped, ALL rows vs shipped ===")
    h3, l8 = A["h3"], A["l8"]; has_h3, has_l8 = ~np.isnan(h3), ~np.isnan(l8)
    base = np.full(n, np.nan); both = has_h3 & has_l8
    base[both] = 0.5 * h3[both] + 0.5 * l8[both]; base[has_h3 & ~has_l8] = h3[has_h3 & ~has_l8]; base[~has_h3 & has_l8] = l8[~has_h3 & has_l8]
    for i in np.where(~np.isnan(base))[0]:
        base[i] = NW.age_adjust(pos[i], base[i], A["age"][i])
    oppcal = A["oppcal"]; vet_opp = (~np.isnan(oppcal)) & (A["seg"] != "rookie") & (~is_rookie) & ~np.isnan(base) & (base >= 4)
    base[vet_opp] = oppcal[vet_opp]
    pos_mean = {ps: NW.loyo_const(A, lambda ps=ps: (pos == ps), YEARS) for ps in POS4}
    fb_pos = np.array([pos_mean[ps].get(y, np.nan) for ps, y in zip(pos, year)])
    PPOS = {"QB": 12, "RB": 5, "WR": 8, "TE": 8}; K = 0.8
    Pvec = np.array([PPOS[ps] for ps in pos], dtype=float)
    def shadow_pred(rookie_prior):
        fb = fb_pos.copy(); m = is_rookie & ~np.isnan(rookie_prior); fb[m] = rookie_prior[m]
        pr = base.copy(); miss = np.isnan(pr); pr[miss] = fb[miss]
        pr = fb_pos + K * (pr - fb_pos)
        return NW.blend(pr, g, ppg, Pvec) * layers
    ref = shadow_pred(priors["PICK"])
    P(f"  {'fallback':14s} {'vs shipped':>10s} {'yrs':>4s} {'vs v2 (PICK)':>13s} {'yrs':>4s} | rookie rows | wk1 | wk2-4")
    for lab in ["CLAY"] + [m for m, _ in MODELS]:
        pred = shadow_pred(priors[lab])
        pc, w, ny = NW.pct_vs(pred, shipped, act, year); pv, wv, _ = NW.pct_vs(pred, ref, act, year)
        rr = is_rookie; b1 = wk == 1; b24 = (wk >= 2) & (wk <= 4)
        row = {"model": lab, "pct": round(pc, 3), "wins": int(w), "years": ny, "vsV2": round(pv, 3), "vsV2Wins": int(wv),
               "rookie": round((mse(pred[rr], act[rr]) / mse(shipped[rr], act[rr]) - 1) * 100, 2),
               "wk1": round((mse(pred[b1], act[b1]) / mse(shipped[b1], act[b1]) - 1) * 100, 2), "wk24": round((mse(pred[b24], act[b24]) / mse(shipped[b24], act[b24]) - 1) * 100, 2)}
        P(f"  {lab:14s} {row['pct']:+9.2f}% {w}/{ny} {row['vsV2']:+12.2f}% {wv}/{ny} | {row['rookie']:+.2f}% | {row['wk1']:+.2f}% | {row['wk24']:+.2f}%")
        RES["blended"].append(row)
    # forward check for the best market model
    best = min([m for m, _ in MODELS], key=lambda m: [r for r in RES["blended"] if r["model"] == m][0]["pct"])
    model = dict(MODELS)[best]
    fwd = np.full(n, np.nan)
    for y in YEARS[2:]:
        fwd = np.where(year == y, fit_apply(model, year < y, year == y), fwd)
    fm = ~np.isnan(fwd) & (year >= YEARS[2])
    pf = shadow_pred(np.where(fm, fwd, priors["PICK"]))
    fp, fw, fy = NW.pct_vs(pf[year >= YEARS[2]], shipped[year >= YEARS[2]], act[year >= YEARS[2]], year[year >= YEARS[2]])
    fr, frw, _ = NW.pct_vs(pf[year >= YEARS[2]], ref[year >= YEARS[2]], act[year >= YEARS[2]], year[year >= YEARS[2]])
    P(f"  FORWARD {best} (2021-25, fits from earlier seasons): vs shipped {fp:+.2f}% ({fw}/{fy}) | vs v2 {fr:+.2f}% ({frw}/{fy})")
    RES["best"] = best; RES["forward"] = {"model": best, "pct": round(fp, 3), "wins": int(fw), "years": fy, "vsV2": round(fr, 3), "vsV2Wins": int(frw)}
    # all-years coefficients of the best model for the engine
    for ps in POS4:
        tr = is_rookie & (pos == ps) & (wk <= FIT_WK)
        b = lstsq(design(model, tr), act[tr]); RES["coef"][ps] = [round(float(x), 4) for x in b]
    RES["coefModel"] = model
    P(f"  coefficients ({best}, all seasons, order: 1, " + ", ".join(model) + " [+ 'no' indicators]): " + json.dumps(RES["coef"]))

    # ---- VETERANS: the ADP curve as a market prior blended into the history prior ----
    P("\n=== Veterans: ADP-implied PPG (curve fit on everyone) blended into the Clay-free history prior, LOYO vs shipped ===")
    vet_listed = ~is_rookie & ~np.isnan(adp_curve) & ~np.isnan(base)
    yr2 = (A["exp"] == 1)
    def pred_w(w_vet, w_yr2=None, rookie_prior=None, curve=None):
        curve = adp_curve if curve is None else curve
        rp = priors["PICK"] if rookie_prior is None else rookie_prior
        fb = fb_pos.copy(); m = is_rookie & ~np.isnan(rp); fb[m] = rp[m]
        pr = base.copy(); miss = np.isnan(pr); pr[miss] = fb[miss]
        wv = np.where(yr2, w_vet if w_yr2 is None else w_yr2, w_vet)
        sel = ~is_rookie & ~np.isnan(curve) & ~miss
        pr = np.where(sel, (1 - wv) * pr + wv * curve, pr)
        pr = fb_pos + K * (pr - fb_pos)
        return NW.blend(pr, g, ppg, Pvec) * layers
    for seg_lab, seg_mask in (("all listed vets", vet_listed), ("team-changers", vet_listed & A["mover"]), ("2nd year", vet_listed & yr2), ("vets, same team, 3+ yrs", vet_listed & ~A["mover"] & ~yr2)):
        NW.RES["sweeps"] = []
        NW.loyo_pick(A, shipped, [0.0, 0.25, 0.5, 0.75, 1.0], lambda w, sm=seg_mask: pred_w(w), f"ADP weight, {seg_lab}", "adp_w", mask=seg_mask)
        RES["vets"].append(NW.RES["sweeps"][-1])
    for ps in POS4:
        NW.RES["sweeps"] = []
        NW.loyo_pick(A, shipped, [0.0, 0.25, 0.5, 0.75, 1.0], lambda w: pred_w(w), f"  ADP weight, {ps} vets", "adp_w", mask=vet_listed & (pos == ps))
        RES["vets"].append(NW.RES["sweeps"][-1])
    # v2.1 candidate: vets .75, 2nd-year .5, rookies PICK (unchanged)
    W_VET, W_YR2 = 0.75, 0.5
    cand = pred_w(W_VET, W_YR2)
    pc, w, ny = NW.pct_vs(cand, shipped, act, year); pv, wv, _ = NW.pct_vs(cand, ref, act, year)
    P(f"\n=== v2.1 candidate: vets ADP weight {W_VET}, 2nd-year {W_YR2}, rookies PICK ===")
    P(f"  vs shipped {pc:+.2f}% ({w}/{ny}) | vs shadow v2 {pv:+.2f}% ({wv}/{ny})")
    c21 = {"pct": round(pc, 3), "wins": int(w), "years": ny, "vsV2": round(pv, 3), "vsV2Wins": int(wv), "byPos": {}, "bands": [], "segments": [], "wVet": W_VET, "wYr2": W_YR2}
    for ps in POS4:
        mm = pos == ps; c21["byPos"][ps] = round((mse(cand[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 2)
    P("  by position: " + "  ".join(f"{ps} {c21['byPos'][ps]:+.2f}%" for ps in POS4))
    for lab, lo, hi in BANDS:
        mm = (wk >= lo) & (wk <= hi)
        row = {"band": lab, "n": int(mm.sum()), "pct": round((mse(cand[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 3), "v2": round((mse(ref[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 3)}
        c21["bands"].append(row); P(f"  {lab:7s} v2 {row['v2']:+6.2f}% -> v2.1 {row['pct']:+6.2f}%")
    for lab, mm in (("vet, same team", ~is_rookie & ~A["mover"] & ~np.isnan(base)), ("vet, changed team", ~is_rookie & A["mover"] & ~np.isnan(base)), ("rookie", is_rookie), ("2nd year", yr2 & ~np.isnan(base)), ("vets WITHOUT an ADP", ~is_rookie & np.isnan(adp_curve) & ~np.isnan(base))):
        row = {"seg": lab, "n": int(mm.sum()), "pct": round((mse(cand[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 3), "v2": round((mse(ref[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 3)}
        c21["segments"].append(row); P(f"  {lab:24s} n={mm.sum():5d}  v2 {row['v2']:+6.2f}% -> v2.1 {row['pct']:+6.2f}%")
    # forward: curve from earlier seasons only
    fcurve = np.full(n, np.nan)
    for y in YEARS[2:]:
        fcurve = np.where(year == y, adp_curve_apply(adp_curve_fit(year < y), year == y), fcurve)
    fm = year >= YEARS[2]
    fc = pred_w(W_VET, W_YR2, curve=np.where(fm, fcurve, np.nan))
    fp, fw, fy = NW.pct_vs(fc[fm], shipped[fm], act[fm], year[fm]); fr, frw, _ = NW.pct_vs(fc[fm], ref[fm], act[fm], year[fm])
    P(f"  FORWARD (2021-25, curve from earlier seasons): vs shipped {fp:+.2f}% ({fw}/{fy}) | vs v2 {fr:+.2f}% ({frw}/{fy})")
    for lab, lo, hi in BANDS:
        mm = fm & (wk >= lo) & (wk <= hi); P(f"    {lab:7s} {(mse(fc[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100:+6.2f}%")
    c21["forward"] = {"pct": round(fp, 3), "wins": int(fw), "years": fy, "vsV2": round(fr, 3), "vsV2Wins": int(frw)}
    RES["v21"] = c21
    P(f"  ADP curve coefficients (all seasons, half-PPR, a + b ln(adp)): {json.dumps(RES['adpCurveAll'])}")
    RES["summary"] = (f"Rookie prior alone (weeks 1-4): " + ", ".join(f"{r['model']} {r['vsClay']:+.1f}%" for r in RES['priorAlone'][1:]) +
                      f" vs Clay. Veterans: ADP-market prior blended .75 (2nd-year .5) -> v2.1 {c21['pct']:+.2f}% vs shipped ({c21['wins']}/{c21['years']}), forward {fp:+.2f}%, vs v2 {c21['vsV2']:+.2f}%.")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "rookie_prior_backtest.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_ROOKIEPRIOR_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/rookie_prior_backtest.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
