#!/usr/bin/env python3
"""
WEEK 1 on the Clay-free shadow (2026-09-16).

Jack: "build the week 1 layer next." Shadow v2.4 is -1.1% vs the shipped Clay blend over 2019-25 but +0.5% in
week 1 (n 1,245), the only week where the projection IS the prior (no season-to-date evidence). So the question
is how the prior should look before any game: level, regression, market weight, rookie level.
Reads on week 1 (and weeks 2-4 for contrast): actual / shadow, actual / shipped by position, segment, ADP bucket,
depth string. Sweeps, each LOYO vs shadow v2.4 on week-1 rows (and separately on weeks 2-4):
  LEVEL     prior x m in week 1                                   (is the preseason prior too hot / cold?)
  SHRINK    k toward the position mean in week 1 (v2.4 = .8)       (more regression before evidence?)
  ADP       veterans' market weight in week 1 (v2.4 = .75 / .5)    (the market is freshest in week 1)
  ROOKIE    rookie fallback x m in week 1
Then a candidate from the passing knobs, graded on all rows and forward.
Log week1_backtest.log; results -> data/week1_backtest.js (SIM_WEEK1_BT), ZONES tab.
"""
import json, os, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import backtest_rookie_prior as RP
import backtest_rookie_depth_live as RD
import backtest_demoted_vets as DV
import backtest_nochart_vets as NC
import bt_common as B
from backtest_target_area import mse

sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "week1_backtest.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

YEARS, POS4, BANDS = NW.YEARS, NW.POS4, NW.BANDS
FIT_WK = 8
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "reads": [], "sweeps": [], "candidate": {}}


def main():
    t0 = time.time()
    P("=== Week 1 on the Clay-free shadow ===")
    S = NW.build_samples(); A = NW.arrays(S); n = len(S)
    act, year, wk, pos, g, ppg, clay, layers = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"]
    is_rookie, pid, team = A["rookie"], A["pid"], A["team"]
    shipped = NW.blend(clay, g, ppg, NW.PRIOR_P) * layers
    weekly, dated = RD.load_depth(); weekly_any, dated_any = NC.load_depth_any(); games = {Y: B.load_games(Y) for Y in YEARS}
    def string_at(i, w, same_team=True):
        if pid[i] is None: return None
        if year[i] <= 2024:
            if same_team: return weekly.get((year[i], pid[i], team[i], w))
            v = weekly_any.get((year[i], pid[i], w)); return v[0] if v else None
        gm = games[2025].get((team[i], w))
        if not gm: return None
        lst = dated.get((pid[i], team[i])) if same_team else dated_any.get(pid[i])
        if not lst: return None
        before = [x for x in lst if x[0] < gm["date"]]
        return before[-1][1] if before else None
    string = np.array([np.nan if string_at(i, wk[i]) is None else string_at(i, wk[i]) for i in range(n)], dtype=float)
    any_str = np.array([np.nan if string_at(i, wk[i], False) is None else string_at(i, wk[i], False) for i in range(n)], dtype=float)
    str_any = np.where(np.isnan(string), any_str, string); has = ~np.isnan(str_any); strb = np.where(has, np.minimum(str_any, 3), np.nan)
    # ---- v2.4 prior pieces, kept separate so the sweeps can re-weight them ----
    adp_map = RP.load_adp()
    adp = np.array([adp_map.get((y, NW.cal.norm(nm), ps), np.nan) for y, nm, ps in zip(year, A["name"], pos)])
    has_adp = ~np.isnan(adp); ladp = np.log(np.where(has_adp, adp, RP.ADP_CAP)); lpick = np.log(np.where(np.isnan(A["pick"]), 262.0, A["pick"]))
    h3, l8 = A["h3"], A["l8"]; has_h3, has_l8 = ~np.isnan(h3), ~np.isnan(l8)
    hist = np.full(n, np.nan); both = has_h3 & has_l8
    hist[both] = 0.5 * h3[both] + 0.5 * l8[both]; hist[has_h3 & ~has_l8] = h3[has_h3 & ~has_l8]; hist[~has_h3 & has_l8] = l8[~has_h3 & has_l8]
    for i in np.where(~np.isnan(hist))[0]: hist[i] = NW.age_adjust(pos[i], hist[i], A["age"][i])
    oppcal = A["oppcal"]; vet_opp = (~np.isnan(oppcal)) & (A["seg"] != "rookie") & (~is_rookie) & ~np.isnan(hist) & (hist >= 4); hist[vet_opp] = oppcal[vet_opp]
    adp_curve = np.full(n, np.nan)
    for y in YEARS:
        for ps in POS4:
            tr = (year != y) & (pos == ps) & has_adp & (wk <= FIT_WK); ap = (year == y) & (pos == ps) & has_adp
            if tr.sum() >= 60 and ap.any():
                b = np.linalg.lstsq(np.column_stack([np.ones(tr.sum()), ladp[tr]]), act[tr], rcond=None)[0]; adp_curve[ap] = np.maximum(0.5, b[0] + b[1] * ladp[ap])
    yr2 = A["exp"] == 1; has_hist = ~np.isnan(hist); mkt_ok = ~is_rookie & ~np.isnan(adp_curve) & has_hist
    pos_mean = {ps: NW.loyo_const(A, lambda ps=ps: (pos == ps), YEARS) for ps in POS4}
    fb_pos = np.array([pos_mean[ps].get(y, np.nan) for ps, y in zip(pos, year)]); fb = fb_pos.copy()
    for y in YEARS:
        for ps in POS4:
            tr = (year != y) & is_rookie & (pos == ps) & (wk <= FIT_WK); ap = (year == y) & is_rookie & (pos == ps)
            if tr.sum() < 40 or not ap.any(): continue
            def X(m):
                cols = [np.ones(m.sum()), lpick[m]]
                if ps in ("RB", "WR"): cols += [np.where(has[m], (strb[m] == 2).astype(float), 0.0), np.where(has[m], (strb[m] >= 3).astype(float), 1.0)]
                return np.column_stack(cols)
            b = np.linalg.lstsq(X(tr), act[tr], rcond=None)[0]; fb[ap] = np.maximum(0.5, X(ap) @ b)
    vet = ~is_rookie & has_hist
    PPOS = {"QB": 12, "RB": 5, "WR": 8, "TE": 8}; Pvec = np.array([PPOS[ps] for ps in pos], dtype=float)
    def build(w_vet=0.75, w_yr2=0.5, k=0.8, rookie_m=1.0, level=1.0, mask=None):
        """the v2.4 shadow with knobs overridden on `mask` rows (None = everywhere)."""
        m = np.ones(n, dtype=bool) if mask is None else mask
        wv_all = np.where(yr2, 0.5, 0.75); wv_new = np.where(yr2, w_yr2, w_vet); wv = np.where(m, wv_new, wv_all)
        pr = hist.copy(); pr = np.where(mkt_ok, (1 - wv) * pr + wv * adp_curve, pr)
        miss = np.isnan(pr); pr[miss] = fb[miss]
        pr = np.where(m & is_rookie, pr * rookie_m, pr)
        for ps, d in NC.VETDOCK.items():
            for sb, mm_ in d.items():
                mk = vet & (pos == ps) & (strb == sb); pr[mk] *= mm_
        kk = np.where(m, k, 0.8)
        pr = fb_pos + kk * (pr - fb_pos)
        pr = np.where(m, pr * level, pr)
        return NW.blend(pr, g, ppg, Pvec) * layers
    ref = build()
    pc, w, ny = NW.pct_vs(ref, shipped, act, year)
    w1 = wk == 1; w24 = (wk >= 2) & (wk <= 4)
    P(f"  {n} player-weeks | shadow v2.4 vs shipped {pc:+.2f}% ({w}/{ny}) | week 1 rows {w1.sum()}: {(mse(ref[w1], act[w1]) / mse(shipped[w1], act[w1]) - 1) * 100:+.2f}% | weeks 2-4 {(mse(ref[w24], act[w24]) / mse(shipped[w24], act[w24]) - 1) * 100:+.2f}%")

    # ---- reads ----
    P("\n=== Week 1 reads: actual / shadow, actual / shipped, shadow vs shipped MSE ===")
    def read(lab, mm):
        if mm.sum() < 20: return
        row = {"label": lab, "n": int(mm.sum()), "actOverShadow": round(float(act[mm].mean() / ref[mm].mean()), 3), "actOverShipped": round(float(act[mm].mean() / shipped[mm].mean()), 3),
               "vsShip": round((mse(ref[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 2)}
        RES["reads"].append(row); P(f"  {lab:34s} n={mm.sum():5d} act/shadow {row['actOverShadow']:.3f} act/shipped {row['actOverShipped']:.3f} shadow vs shipped {row['vsShip']:+6.2f}%")
    read("week 1, all", w1)
    for ps in POS4: read(f"  week 1 {ps}", w1 & (pos == ps))
    read("  week 1 vets, same team", w1 & vet & ~A["mover"]); read("  week 1 vets, changed team", w1 & vet & A["mover"]); read("  week 1 2nd-year", w1 & yr2 & has_hist); read("  week 1 rookies", w1 & is_rookie)
    for lab, lo, hi in (("ADP 1-36", 0, 36), ("ADP 37-84", 36, 84), ("ADP 85-132", 84, 132), ("ADP 133-180", 132, 181)):
        read(f"  week 1 vets {lab}", w1 & vet & has_adp & (adp > lo) & (adp <= hi))
    read("  week 1 vets, no ADP", w1 & vet & ~has_adp)
    for sb, lab in ((1, "1st string"), (2, "2nd string"), (3, "3rd+")): read(f"  week 1 vets {lab}", w1 & vet & (strb == sb))
    read("weeks 2-4, all", w24)
    for ps in POS4: read(f"  weeks 2-4 {ps}", w24 & (pos == ps))
    read("  weeks 2-4 vets, changed team", w24 & vet & A["mover"]); read("  weeks 2-4 rookies", w24 & is_rookie)

    # ---- sweeps (LOYO vs shadow, on the band's rows) ----
    P("\n=== Sweeps on week 1 (LOYO vs shadow v2.4) ===")
    DV.RES["sweeps"] = []
    DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.95, 0.9, 1.05, 1.1], lambda m_: build(level=m_, mask=w1), "week 1 LEVEL x m", w1)
    for ps in POS4: DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.95, 0.9, 1.05, 1.1], lambda m_, ps=ps: build(level=m_, mask=w1 & (pos == ps)), f"  week 1 level {ps}", w1 & (pos == ps))
    DV.loyo_vs_ref(A, ref, shipped, [0.8, 0.7, 0.6, 0.5, 0.9, 1.0], lambda k_: build(k=k_, mask=w1), "week 1 SHRINK k", w1)
    DV.loyo_vs_ref(A, ref, shipped, [0.75, 0.5, 0.9, 1.0], lambda w_: build(w_vet=w_, mask=w1), "week 1 vets ADP weight", w1 & vet & mkt_ok)
    DV.loyo_vs_ref(A, ref, shipped, [0.5, 0.25, 0.75, 1.0], lambda w_: build(w_yr2=w_, mask=w1), "week 1 2nd-year ADP weight", w1 & yr2 & mkt_ok)
    DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.9, 0.8, 1.1, 1.2], lambda m_: build(rookie_m=m_, mask=w1), "week 1 ROOKIE x m", w1 & is_rookie)
    P("\n=== Same knobs on weeks 2-4 (contrast) ===")
    DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.95, 0.9, 1.05, 1.1], lambda m_: build(level=m_, mask=w24), "weeks 2-4 LEVEL x m", w24)
    DV.loyo_vs_ref(A, ref, shipped, [0.8, 0.7, 0.6, 0.5, 0.9, 1.0], lambda k_: build(k=k_, mask=w24), "weeks 2-4 SHRINK k", w24)
    DV.loyo_vs_ref(A, ref, shipped, [0.75, 0.5, 0.9, 1.0], lambda w_: build(w_vet=w_, mask=w24), "weeks 2-4 vets ADP weight", w24 & vet & mkt_ok)
    DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.9, 0.8, 1.1, 1.2], lambda m_: build(rookie_m=m_, mask=w24), "weeks 2-4 ROOKIE x m", w24 & is_rookie)
    RES["sweeps"] = DV.RES["sweeps"]

    # ---- rookies in week 1 by depth string (the live engine ramps BURIED rookies 55/70/85/95% in weeks 1-4; the harness has no ramp) ----
    P("\n=== Week 1 rookies by string ===")
    for sb, lab in ((1, "1st string"), (2, "2nd string"), (3, "3rd+ / unlisted")):
        mm = w1 & is_rookie & ((strb == sb) if sb < 3 else ((strb >= 3) | ~has))
        read(f"  week 1 rookies {lab}", mm)
    lead = is_rookie & (strb == 1)
    DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.9, 0.8, 0.7, 1.1], lambda m_: build(rookie_m=m_, mask=w1 & lead), "week 1 ROOKIE x m, 1st-string rookies only", w1 & lead)
    DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.9, 0.8, 0.7, 1.1], lambda m_: build(rookie_m=m_, mask=w1 & is_rookie & ~lead), "week 1 ROOKIE x m, buried rookies only", w1 & is_rookie & ~lead)
    RES["sweeps"] = DV.RES["sweeps"]
    # ---- combined pieces: TE week-1 level x.9 + rookie week-1 x m (all / 1st-string), forward ----
    P("\n=== Combined week-1 pieces (TE level + rookie level), LOYO + forward ===")
    def build2(te_m, rk_m, rk_mask):
        pr_full = build()  # unused; compose via level masks instead
        out = build(level=te_m, mask=w1 & (pos == "TE"))
        # rookie multiplier applied on top (prior-level multiplier before blend; week 1 has g=0 so equivalent to scaling the projection)
        out = np.where(w1 & rk_mask, out * rk_m, out)
        return out
    RES["combined"] = []
    for lab, rk_mask in (("all rookies", is_rookie), ("1st-string rookies", lead)):
        for te_m, rk_m in ((0.9, 1.0), (1.0, 0.8), (0.9, 0.8)):
            cnd = build2(te_m, rk_m, rk_mask)
            pv2, wv2, _ = NW.pct_vs(cnd, ref, act, year); p1, w1c, _ = NW.pct_vs(cnd[w1], ref[w1], act[w1], year[w1])
            # forward: re-pick each multiplier on earlier seasons' week-1 rows
            fwd2 = np.full(n, np.nan)
            for y in YEARS[2:]:
                tr = w1 & (year < y)
                tm_ = min([1.0, 0.95, 0.9, 0.85], key=lambda v: mse(build2(v, 1.0, rk_mask)[tr & (pos == "TE")], act[tr & (pos == "TE")])) if te_m < 1 else 1.0
                rm_ = min([1.0, 0.9, 0.8, 0.7], key=lambda v: mse(build2(1.0, v, rk_mask)[tr & rk_mask], act[tr & rk_mask])) if rk_m < 1 else 1.0
                fwd2 = np.where(year == y, build2(tm_, rm_, rk_mask), fwd2)
            fm2 = year >= YEARS[2]; f1 = fm2 & w1
            fr2, frw2, fy2 = NW.pct_vs(fwd2[f1], ref[f1], act[f1], year[f1])
            row = {"rookies": lab, "teM": te_m, "rkM": rk_m, "allVsRef": round(pv2, 3), "allWins": int(wv2), "wk1VsRef": round(p1, 3), "wk1Wins": int(w1c), "years": ny, "fwdWk1VsRef": round(fr2, 3), "fwdWk1Wins": int(frw2), "fwdYears": fy2,
                   "wk1VsShip": round((mse(cnd[w1], act[w1]) / mse(shipped[w1], act[w1]) - 1) * 100, 3)}
            RES["combined"].append(row)
            P(f"  TE x{te_m} + rookies({lab}) x{rk_m}: all rows {pv2:+.2f}% vs shadow ({wv2}/{ny}) | week 1 {p1:+.2f}% ({w1c}/{ny}), vs shipped {row['wk1VsShip']:+.2f}% | FORWARD week 1 {fr2:+.2f}% ({frw2}/{fy2})")
    # ---- BURIED-ROOKIE RAMP by week (chart-defined buried = string >= 2 or unlisted), LOYO vs shadow; the Clay-free twin of the live ramp ----
    P("\n=== Buried rookies (string >= 2 or unlisted) x m by week, LOYO vs shadow ===")
    buried = is_rookie & ~lead
    RES["ramp"] = []
    for lab, lo, hi in (("wk1", 1, 1), ("wk2", 2, 2), ("wk3", 3, 3), ("wk4", 4, 4), ("wk5-8", 5, 8), ("wk9+", 9, 18)):
        mm = buried & (wk >= lo) & (wk <= hi)
        if mm.sum() < 30: P(f"  {lab}: n={mm.sum()} too few"); continue
        r = DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.9, 0.8, 0.7, 0.6, 1.1], lambda m_, mm=mm: np.where(mm, ref * m_, ref), f"  buried rookies {lab}", mm)
        row = dict(DV.RES["sweeps"][-1]); row["band"] = lab; row["actOverShadow"] = round(float(act[mm].mean() / ref[mm].mean()), 3); RES["ramp"].append(row)
    lead_rows = []
    for lab, lo, hi in (("wk1", 1, 1), ("wk2-4", 2, 4), ("wk5-8", 5, 8)):
        mm = lead & (wk >= lo) & (wk <= hi)
        if mm.sum() >= 30: lead_rows.append(f"{lab} n{mm.sum()} act/shadow {act[mm].mean() / ref[mm].mean():.3f}")
    P("  1st-string rookies for contrast: " + " | ".join(lead_rows))
    RES["sweeps"] = DV.RES["sweeps"]
    # candidate ramp = the passing weeks' pooled bests; forward = re-pick each week's multiplier on earlier seasons
    RAMP = {r["band"]: (r["pooledBest"] if r["verdict"] in ("PASS", "lean") else 1.0) for r in RES["ramp"]}
    def apply_ramp(rmp, base_pred):
        out = base_pred.copy()
        for (lab, lo, hi) in (("wk1", 1, 1), ("wk2", 2, 2), ("wk3", 3, 3), ("wk4", 4, 4), ("wk5-8", 5, 8), ("wk9+", 9, 18)):
            m_ = rmp.get(lab, 1.0)
            if m_ != 1.0: mm = buried & (wk >= lo) & (wk <= hi); out = np.where(mm, out * m_, out)
        return out
    cand_r = apply_ramp(RAMP, ref)
    pcr, wr_, nyr = NW.pct_vs(cand_r, shipped, act, year); pvr, wvr, _ = NW.pct_vs(cand_r, ref, act, year)
    b14 = buried & (wk <= 4)
    P(f"\n=== Candidate: buried-rookie ramp {json.dumps(RAMP)} ===")
    P(f"  ALL rows: vs shipped {pcr:+.2f}% ({wr_}/{nyr}) | vs shadow v2.4 {pvr:+.2f}% ({wvr}/{nyr}) | week 1 {(mse(cand_r[w1], act[w1]) / mse(shipped[w1], act[w1]) - 1) * 100:+.2f}% vs shipped (was {(mse(ref[w1], act[w1]) / mse(shipped[w1], act[w1]) - 1) * 100:+.2f}%) | buried rookies wks 1-4 {(mse(cand_r[b14], act[b14]) / mse(ref[b14], act[b14]) - 1) * 100:+.2f}% vs shadow")
    fwd_r = np.full(n, np.nan)
    for y in YEARS[2:]:
        rmp = {}
        for (lab, lo, hi) in (("wk1", 1, 1), ("wk2", 2, 2), ("wk3", 3, 3), ("wk4", 4, 4), ("wk5-8", 5, 8), ("wk9+", 9, 18)):
            if RAMP.get(lab, 1.0) == 1.0: rmp[lab] = 1.0; continue
            tr = buried & (wk >= lo) & (wk <= hi) & (year < y)
            rmp[lab] = min([1.0, 0.9, 0.8, 0.7, 0.6], key=lambda v: mse((ref * v)[tr], act[tr])) if tr.sum() >= 20 else 1.0
        fwd_r = np.where(year == y, apply_ramp(rmp, ref), fwd_r)
    fm = year >= YEARS[2]; fb14 = fm & b14; f1 = fm & w1
    frr, frw, fy = NW.pct_vs(fwd_r[fm], ref[fm], act[fm], year[fm]); fbr, fbw, _ = NW.pct_vs(fwd_r[fb14], ref[fb14], act[fb14], year[fb14]); f1r, f1w, _ = NW.pct_vs(fwd_r[f1], ref[f1], act[f1], year[f1])
    P(f"  FORWARD (2021-25, multipliers picked on earlier seasons): all rows {frr:+.2f}% ({frw}/{fy}) | buried rookies wks 1-4 {fbr:+.2f}% ({fbw}/{fy}) | week-1 rows {f1r:+.2f}% ({f1w}/{fy})")
    RES["rampCandidate"] = {"ramp": RAMP, "pct": round(pcr, 3), "wins": int(wr_), "years": nyr, "vsRef": round(pvr, 3), "vsRefWins": int(wvr), "wk1VsShip": round((mse(cand_r[w1], act[w1]) / mse(shipped[w1], act[w1]) - 1) * 100, 3),
                            "buriedVsRef": round((mse(cand_r[b14], act[b14]) / mse(ref[b14], act[b14]) - 1) * 100, 3), "forward": {"vsRef": round(frr, 3), "vsRefWins": int(frw), "years": fy, "buriedVsRef": round(fbr, 3), "buriedWins": int(fbw), "wk1VsRef": round(f1r, 3), "wk1Wins": int(f1w)}}
    # ---- candidate: the passing week-1 knobs together, forward ----
    def pick(label, default):
        r = [x for x in RES["sweeps"] if x["label"] == label][0]
        return r["pooledBest"] if r["verdict"] in ("PASS", "lean") else default
    lv, kk, wv_, wy_, rm = pick("week 1 LEVEL x m", 1.0), pick("week 1 SHRINK k", 0.8), pick("week 1 vets ADP weight", 0.75), pick("week 1 2nd-year ADP weight", 0.5), pick("week 1 ROOKIE x m", 1.0)
    cand = build(w_vet=wv_, w_yr2=wy_, k=kk, rookie_m=rm, level=lv, mask=w1)
    pc2, w2, ny2 = NW.pct_vs(cand, shipped, act, year); pv, wvv, _ = NW.pct_vs(cand, ref, act, year)
    P(f"\n=== Candidate week-1 knobs: level {lv}, shrink k {kk}, vets ADP {wv_}, 2nd-year ADP {wy_}, rookie x{rm} ===")
    P(f"  ALL rows: vs shipped {pc2:+.2f}% ({w2}/{ny2}) | vs shadow v2.4 {pv:+.2f}% ({wvv}/{ny2}) | week 1: shadow {(mse(ref[w1], act[w1]) / mse(shipped[w1], act[w1]) - 1) * 100:+.2f}% -> {(mse(cand[w1], act[w1]) / mse(shipped[w1], act[w1]) - 1) * 100:+.2f}% vs shipped")
    # forward: knobs re-picked on earlier seasons (pooled best on year < y, week-1 rows)
    grids = {"level": [1.0, 0.95, 0.9, 1.05, 1.1], "k": [0.8, 0.7, 0.6, 0.5, 0.9, 1.0], "w_vet": [0.75, 0.5, 0.9, 1.0], "w_yr2": [0.5, 0.25, 0.75, 1.0], "rookie_m": [1.0, 0.9, 0.8, 1.1, 1.2]}
    fwd = np.full(n, np.nan)
    for y in YEARS[2:]:
        tr = w1 & (year < y); best = {}
        for key, grid in grids.items():
            if key == "level" and lv == 1.0: best[key] = 1.0; continue
            if key == "k" and kk == 0.8: best[key] = 0.8; continue
            if key == "w_vet" and wv_ == 0.75: best[key] = 0.75; continue
            if key == "w_yr2" and wy_ == 0.5: best[key] = 0.5; continue
            if key == "rookie_m" and rm == 1.0: best[key] = 1.0; continue
            best[key] = min(grid, key=lambda v: mse(build(**{key: v}, mask=w1)[tr], act[tr]))
        fwd = np.where(year == y, build(w_vet=best["w_vet"], w_yr2=best["w_yr2"], k=best["k"], rookie_m=best["rookie_m"], level=best["level"], mask=w1), fwd)
    fm = year >= YEARS[2]; f1 = fm & w1
    fr, frw, fy = NW.pct_vs(fwd[fm], ref[fm], act[fm], year[fm]); f1r, f1w, _ = NW.pct_vs(fwd[f1], ref[f1], act[f1], year[f1])
    P(f"  FORWARD (2021-25, knobs picked on earlier seasons): {fr:+.2f}% vs shadow ({frw}/{fy}) | week-1 rows {f1r:+.2f}% ({f1w}/{fy})")
    RES["candidate"] = {"level": float(lv), "k": float(kk), "wVet": float(wv_), "wYr2": float(wy_), "rookieM": float(rm), "pct": round(pc2, 3), "wins": int(w2), "years": ny2, "vsRef": round(pv, 3), "vsRefWins": int(wvv),
                        "wk1VsShip": round((mse(cand[w1], act[w1]) / mse(shipped[w1], act[w1]) - 1) * 100, 3), "wk1RefVsShip": round((mse(ref[w1], act[w1]) / mse(shipped[w1], act[w1]) - 1) * 100, 3),
                        "forward": {"vsRef": round(fr, 3), "vsRefWins": int(frw), "years": fy, "wk1VsRef": round(f1r, 3), "wk1Wins": int(f1w)}}
    rc = RES["rampCandidate"]
    RES["summary"] = (f"Week 1 (n {w1.sum()}): shadow {RES['candidate']['wk1RefVsShip']:+.2f}% vs shipped; the gap is BURIED rookies (2nd string act/shadow .74) and TEs. Chart-defined buried-rookie ramp {json.dumps(rc['ramp'])}: {rc['vsRef']:+.2f}% vs v2.4 ({rc['vsRefWins']}/{rc['years']}), buried rookies wks 1-4 {rc['buriedVsRef']:+.2f}%, forward {rc['forward']['buriedVsRef']:+.2f}% ({rc['forward']['buriedWins']}/{rc['forward']['years']}). Other knobs: " + "; ".join(f"{r['label'].strip()} {r['loyoPct']:+.2f}% ({r['wins']}/{r['years']}, {r['verdict']})" for r in RES["sweeps"] if r["label"].startswith("week 1") and not r["label"].startswith("week 1 level ")) +
                      f". Candidate {pv:+.2f}% vs v2.4 ({wvv}/{ny2}), week 1 -> {RES['candidate']['wk1VsShip']:+.2f}% vs shipped, forward week-1 rows {f1r:+.2f}% ({f1w}/{fy}).")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "week1_backtest.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_WEEK1_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/week1_backtest.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
