#!/usr/bin/env python3
"""
PRIOR-YEAR ROUTES VOLUME as a shadow-prior ingredient (2026-09-16).

Jack: "build the routes volume layer next." research_corr_advanced.py: prior-year routes (PFF volume) is r .48 WR / .53
TE / .36 RB with season PPG and .28-.31 weekly - the strongest pure-opportunity number, below production. Same forms as
the grade study with routes in place of the grade (tercile levels, curve, early weeks, young, residual on the prior). The 2026-09-01 PFF
audit rejected season grades as layers on the CLAY base (Clay prices talent); the shadow's prior is own history +
the market curve, which may not. Tests on WR / TE (RB control) rows with a history prior, LOYO vs shadow v2.6:
  TERCILE   prior x m for the top / bottom route-grade tercile (grade from the prior season, >= 50 routes)
  CURVE     prior' = (1-w) prior + w G, G = E[PPG | route grade, pos] fit on the other seasons (weeks <= 8)
  EARLY     the CURVE blend applied in weeks 1-4 only (before season-to-date evidence)
  YOUNG     top-tercile grade and age <= 25 x m (the breakout read)
  RESID     the grade beyond what the history prior already implies: residual of grade on prior, top / bottom x m
Candidate = passing pieces, forward (2021-25, fits on earlier seasons). Log pff_route_grade_backtest.log;
data/pff_route_grade_backtest.js (SIM_ROUTESVOL_BT), ZONES tab.
"""
import json, os, sys, time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import backtest_rookie_prior as RP
import backtest_rookie_depth_live as RD
import backtest_demoted_vets as DV
import backtest_nochart_vets as NC
import backtest_second_year as SY
import bt_common as B
from backtest_target_area import mse

sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "routes_volume_backtest.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

YEARS, POS4, BANDS = NW.YEARS, NW.POS4, NW.BANDS
FIT_WK = 8; RAMP = [0.7, 0.8]
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "reads": [], "sweeps": [], "candidate": {}, "curve": {}}


def load_grades():
    pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "pff_id"])
    pff2g = {int(r.pff_id): r.gsis_id for r in pl.itertuples(index=False) if pd.notna(r.pff_id) and isinstance(r.gsis_id, str)}
    out = {}
    for Y in range(2018, 2026):
        f = os.path.join(B.CACHE, "pff", f"pff_receiving_{Y}.csv")
        if not os.path.exists(f): continue
        d = pd.read_csv(f)
        for r in d.itertuples(index=False):
            g = pff2g.get(int(r.player_id))
            if g and (r.routes or 0) >= 50 and pd.notna(r.grades_pass_route): out[(Y, g)] = (float(r.grades_pass_route), float(r.routes))
    return out


def main():
    t0 = time.time()
    P("=== Prior-year routes volume on the Clay-free shadow ===")
    S = NW.build_samples(); A = NW.arrays(S); n = len(S)
    act, year, wk, pos, g, ppg, clay, layers = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"]
    is_rookie, pid, team = A["rookie"], A["pid"], A["team"]
    shipped = NW.blend(clay, g, ppg, NW.PRIOR_P) * layers
    games = {Y: B.load_games(Y) for Y in YEARS}
    weekly, dated = RD.load_depth(); weekly_any, dated_any = NC.load_depth_any()
    def string_at(i, w, same_team=True):
        if pid[i] is None: return None
        if year[i] <= 2024:
            if same_team: return weekly.get((year[i], pid[i], team[i], w))
            v = weekly_any.get((year[i], pid[i], w)); return v[0] if v else None
        gm = games[2025].get((team[i], w))
        if not gm: return None
        lst = dated.get((pid[i], team[i])) if same_team else dated_any.get(pid[i])
        if not lst: return None
        before = [q for q in lst if q[0] < gm["date"]]
        return before[-1][1] if before else None
    string = np.array([np.nan if string_at(i, wk[i]) is None else string_at(i, wk[i]) for i in range(n)], dtype=float)
    any_str = np.array([np.nan if string_at(i, wk[i], False) is None else string_at(i, wk[i], False) for i in range(n)], dtype=float)
    str_any = np.where(np.isnan(string), any_str, string); has = ~np.isnan(str_any); strb = np.where(has, np.minimum(str_any, 3), np.nan)
    adp_map = RP.load_adp()
    adp = np.array([adp_map.get((y, NW.cal.norm(nm), ps), np.nan) for y, nm, ps in zip(year, A["name"], pos)])
    has_adp = ~np.isnan(adp); ladp = np.log(np.where(has_adp, adp, RP.ADP_CAP)); lpick = np.log(np.where(np.isnan(A["pick"]), 262.0, A["pick"]))
    h3, l8 = A["h3"], A["l8"]; has_h3, has_l8 = ~np.isnan(h3), ~np.isnan(l8); yr2 = A["exp"] == 1
    hist = np.full(n, np.nan); both = has_h3 & has_l8
    hist[both] = 0.5 * h3[both] + 0.5 * l8[both]; hist[has_h3 & ~has_l8] = h3[has_h3 & ~has_l8]; hist[~has_h3 & has_l8] = l8[~has_h3 & has_l8]
    for i in np.where(~np.isnan(hist))[0]: hist[i] = NW.age_adjust(pos[i], hist[i], A["age"][i])
    oppcal = A["oppcal"]; vet_opp = (~np.isnan(oppcal)) & (A["seg"] != "rookie") & (~is_rookie) & ~np.isnan(hist) & (hist >= 4); hist[vet_opp] = oppcal[vet_opp]
    has_hist = ~np.isnan(hist)
    adp_curve = np.full(n, np.nan)
    for y in YEARS:
        for ps in POS4:
            tr = (year != y) & (pos == ps) & has_adp & (wk <= FIT_WK); ap = (year == y) & (pos == ps) & has_adp
            if tr.sum() >= 60 and ap.any():
                b = np.linalg.lstsq(np.column_stack([np.ones(tr.sum()), ladp[tr]]), act[tr], rcond=None)[0]; adp_curve[ap] = np.maximum(0.5, b[0] + b[1] * ladp[ap])
    mkt_ok = ~is_rookie & ~np.isnan(adp_curve) & has_hist
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
    vet = ~is_rookie & has_hist; buried_rk = is_rookie & ~(strb == 1)
    snaps = SY.load_snaps(); late = np.array([snaps[(year[i] - 1, pid[i])]["late"] if (pid[i] and (year[i] - 1, pid[i]) in snaps) else np.nan for i in range(n)]); yr2lo = yr2 & ~np.isnan(late) & (late < 0.4)
    PPOS0 = {"QB": 12, "RB": 5, "WR": 8, "TE": 8}; Pvec = np.array([PPOS0[ps] for ps in pos], dtype=float)
    def prior_base():
        wv = np.where(yr2, 0.5, 0.75); pr = np.where(mkt_ok, (1 - wv) * hist + wv * adp_curve, hist)
        miss = np.isnan(pr); pr[miss] = fb[miss]
        for ps, d in NC.VETDOCK.items():
            for sb, mm_ in d.items():
                mk = vet & (pos == ps) & (strb == sb); pr[mk] *= mm_
        pr = np.where(yr2lo & vet, pr * 1.2, pr)
        return pr
    pr0 = prior_base()
    def build(pr=None, mask_wk=None):
        pr = pr0 if pr is None else pr
        pr = fb_pos + 0.8 * (pr - fb_pos)
        out = NW.blend(pr, g, ppg, Pvec) * layers
        for gi, m_ in enumerate(RAMP, start=1): out = np.where(buried_rk & (wk == gi), out * m_, out)
        return out
    ref = build()
    pc, w, ny = NW.pct_vs(ref, shipped, act, year)
    # ---- grades ----
    gr = load_grades()
    grade = np.array([gr[(year[i] - 1, pid[i])][1] if (pid[i] and (year[i] - 1, pid[i]) in gr) else np.nan for i in range(n)])   # = prior-year ROUTES
    has_g = ~np.isnan(grade) & vet
    P(f"  {n} player-weeks | shadow v2.6 vs shipped {pc:+.2f}% ({w}/{ny}) | rows with prior-year routes and a history prior: WR {int((has_g & (pos == 'WR')).sum())}, TE {int((has_g & (pos == 'TE')).sum())}, RB {int((has_g & (pos == 'RB')).sum())}")
    # curve G = E[PPG | grade, pos] (other seasons, weeks <= 8), and the residual of grade on the prior
    G = np.full(n, np.nan); resid = np.full(n, np.nan)
    for y in YEARS:
        for ps in ("WR", "TE", "RB"):
            tr = (year != y) & has_g & (pos == ps) & (wk <= FIT_WK); ap = (year == y) & has_g & (pos == ps)
            if tr.sum() < 60 or not ap.any(): continue
            b = np.linalg.lstsq(np.column_stack([np.ones(tr.sum()), grade[tr]]), act[tr], rcond=None)[0]; G[ap] = np.maximum(0.5, b[0] + b[1] * grade[ap])
            c = np.linalg.lstsq(np.column_stack([np.ones(tr.sum()), pr0[tr]]), grade[tr], rcond=None)[0]; resid[ap] = grade[ap] - (c[0] + c[1] * pr0[ap])
    RES["curve"] = {}
    for ps in ("WR", "TE", "RB"):
        tr = has_g & (pos == ps) & (wk <= FIT_WK)
        if tr.sum() >= 60:
            b = np.linalg.lstsq(np.column_stack([np.ones(tr.sum()), grade[tr]]), act[tr], rcond=None)[0]; RES["curve"][ps] = [round(float(b[0]), 4), round(float(b[1]), 4)]
    P("  curve E[PPG | routes] (all seasons): " + json.dumps(RES["curve"]))
    P("\n=== Reads: actual / shadow prior (x shrink) by prior-year routes tercile, weeks 1-8, vets ===")
    shr0 = fb_pos + 0.8 * (pr0 - fb_pos)
    terc = {}
    for ps in ("WR", "TE", "RB"):
        m = has_g & (pos == ps)
        if m.sum() < 60: continue
        q = np.nanpercentile(grade[m], [33.3, 66.7]); terc[ps] = q
        for lab, mm in (("low", m & (grade < q[0])), ("mid", m & (grade >= q[0]) & (grade <= q[1])), ("high", m & (grade > q[1])), ("high & age <= 25", m & (grade > q[1]) & (A["age"] <= 25))):
            e = mm & (wk <= FIT_WK)
            if e.sum() >= 30:
                row = {"pos": ps, "tercile": lab, "n": int(e.sum()), "actOverPrior": round(float(act[e].mean() / shr0[e].mean()), 3), "actOverShadow": round(float(act[e].mean() / ref[e].mean()), 3), "vsShip": round((mse(ref[e], act[e]) / mse(shipped[e], act[e]) - 1) * 100, 2)}
                RES["reads"].append(row); P(f"  {ps} {lab:18s} n={e.sum():5d} act/prior {row['actOverPrior']:.3f} act/shadow {row['actOverShadow']:.3f} shadow vs shipped {row['vsShip']:+6.2f}%  (routes cut {q[0]:.1f} / {q[1]:.1f})")
    # ---- sweeps ----
    P("\n=== Sweeps (LOYO vs shadow v2.6) ===")
    DV.RES["sweeps"] = []
    def mult_on(mask, m_): v = np.ones(n); v[mask] = m_; return v
    for ps in ("WR", "TE", "RB"):
        if ps not in terc: continue
        q = terc[ps]; m = has_g & (pos == ps); hi = m & (grade > q[1]); lo = m & (grade < q[0])
        DV.loyo_vs_ref(A, ref, shipped, [1.0, 1.05, 1.1, 1.15, 1.2], lambda m_, hi=hi: build(pr0 * mult_on(hi, m_)), f"{ps} top-tercile routes x m", hi)
        DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.95, 0.9, 0.85, 0.8], lambda m_, lo=lo: build(pr0 * mult_on(lo, m_)), f"  {ps} bottom-tercile routes x m", lo)
        okG = m & ~np.isnan(G)
        DV.loyo_vs_ref(A, ref, shipped, [0.0, 0.15, 0.3, 0.5, 0.75], lambda w_, okG=okG: build(np.where(okG, (1 - w_) * pr0 + w_ * G, pr0)), f"  {ps} routes CURVE blend weight w", okG)
        early = okG & (wk <= 4)
        DV.loyo_vs_ref(A, ref, shipped, [0.0, 0.15, 0.3, 0.5, 0.75], lambda w_, okG=okG, early=early: np.where(early, build(np.where(okG, (1 - w_) * pr0 + w_ * G, pr0)), ref), f"  {ps} routes CURVE blend, weeks 1-4 only", early)
        yng = hi & (A["age"] <= 25)
        if yng.sum() >= 60: DV.loyo_vs_ref(A, ref, shipped, [1.0, 1.05, 1.1, 1.15, 1.2], lambda m_, yng=yng: build(pr0 * mult_on(yng, m_)), f"  {ps} top-tercile routes & age <= 25 x m", yng)
        okR = m & ~np.isnan(resid)
        if okR.sum() >= 60:
            rq = np.nanpercentile(resid[okR], [33.3, 66.7]); rhi = okR & (resid > rq[1]); rlo = okR & (resid < rq[0])
            DV.loyo_vs_ref(A, ref, shipped, [1.0, 1.05, 1.1, 1.15], lambda m_, rhi=rhi: build(pr0 * mult_on(rhi, m_)), f"  {ps} routes ABOVE what the prior implies x m", rhi)
            DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.95, 0.9, 0.85], lambda m_, rlo=rlo: build(pr0 * mult_on(rlo, m_)), f"  {ps} routes BELOW what the prior implies x m", rlo)
    RES["sweeps"] = DV.RES["sweeps"]
    # ---- candidate: PASS pieces (top/bottom tercile and residual multipliers, curve blend), forward ----
    pieces = [r for r in RES["sweeps"] if r["verdict"] == "PASS"]
    P("\n=== Candidate from PASS pieces: " + (", ".join(f"{r['label'].strip()} = {r['pooledBest']}" for r in pieces) if pieces else "NONE") + " ===")
    def mask_of(label):
        ps = label.strip().split()[0]; q = terc[ps]; m = has_g & (pos == ps)
        if "top-tercile routes & age" in label: return m & (grade > q[1]) & (A["age"] <= 25)
        if "top-tercile routes" in label: return m & (grade > q[1])
        if "bottom-tercile routes" in label: return m & (grade < q[0])
        if "ABOVE" in label or "BELOW" in label:
            okR = m & ~np.isnan(resid); rq = np.nanpercentile(resid[okR], [33.3, 66.7])
            return okR & ((resid > rq[1]) if "ABOVE" in label else (resid < rq[0]))
        if "CURVE" in label: return m & ~np.isnan(G) & ((wk <= 4) if "weeks 1-4" in label else True)
        return np.zeros(n, dtype=bool)
    def cand_pred(cfg):
        pr = pr0.copy(); mult = np.ones(n); early_w = None
        for lab, v in cfg.items():
            mk = mask_of(lab)
            if "CURVE" in lab:
                if "weeks 1-4" in lab: early_w = (v, mk)
                else: pr = np.where(mk, (1 - v) * pr + v * G, pr)
            else: mult[mk] *= v
        out = build(pr * mult)
        if early_w: out = np.where(early_w[1], build(np.where(early_w[1], (1 - early_w[0]) * pr + early_w[0] * G, pr) * mult), out)
        return out
    cfg = {r["label"]: r["pooledBest"] for r in pieces}
    cand = cand_pred(cfg) if pieces else ref
    pc2, w2, ny2 = NW.pct_vs(cand, shipped, act, year); pv, wvv, _ = NW.pct_vs(cand, ref, act, year)
    aff = np.zeros(n, dtype=bool)
    for lab in cfg: aff |= mask_of(lab)
    pa, wa, _ = NW.pct_vs(cand[aff], ref[aff], act[aff], year[aff]) if aff.any() else (0.0, 0, ny2)
    P(f"  ALL rows: vs shipped {pc2:+.2f}% ({w2}/{ny2}) | vs shadow v2.6 {pv:+.2f}% ({wvv}/{ny2}) | affected rows n={aff.sum()} {pa:+.2f}% ({wa}/{ny2})")
    fwd = np.full(n, np.nan); fm = year >= YEARS[2]
    for y in YEARS[2:]:
        cfg_y = {}
        for r in pieces:
            mk = mask_of(r["label"]) & (year < y)
            cfg_y[r["label"]] = min(r["grid"], key=lambda v: mse(cand_pred({r["label"]: v})[mk], act[mk])) if mk.sum() >= 40 else r["grid"][0]
        fwd = np.where(year == y, cand_pred(cfg_y) if pieces else ref, fwd)
    fr, frw, fy = NW.pct_vs(fwd[fm], ref[fm], act[fm], year[fm]); fa, faw, _ = NW.pct_vs(fwd[fm & aff], ref[fm & aff], act[fm & aff], year[fm & aff]) if (fm & aff).any() else (0.0, 0, fy)
    P(f"  FORWARD (2021-25): all rows {fr:+.2f}% vs shadow ({frw}/{fy}) | affected rows {fa:+.2f}% ({faw}/{fy})")
    RES["candidate"] = {"cfg": cfg, "pct": round(pc2, 3), "wins": int(w2), "years": ny2, "vsRef": round(pv, 3), "vsRefWins": int(wvv), "affectedN": int(aff.sum()), "affectedVsRef": round(pa, 3), "affectedWins": int(wa),
                        "forward": {"vsRef": round(fr, 3), "vsRefWins": int(frw), "years": fy, "affectedVsRef": round(fa, 3), "affectedWins": int(faw)}}
    # engine constants: WR residual model (grade ~ prior, all seasons) and the top-tercile residual cut
    mW = has_g & (pos == "WR") & (wk <= FIT_WK)
    cW = np.linalg.lstsq(np.column_stack([np.ones(mW.sum()), pr0[mW]]), grade[mW], rcond=None)[0]
    rW = grade[has_g & (pos == "WR")] - (cW[0] + cW[1] * pr0[has_g & (pos == "WR")])
    RES["engine"] = {"WR": {"c0": round(float(cW[0]), 4), "c1": round(float(cW[1]), 4), "cut": round(float(np.nanpercentile(rW, 66.7)), 3), "note": "routes residual (for the record)"}}
    P("  WR routes-residual constants (routes - (c0 + c1 x prior half-PPR), top-tercile cut): " + json.dumps(RES["engine"]))
    RES["summary"] = ("Prior-year routes volume on the shadow: " + "; ".join(f"{r['label'].strip()} {r['loyoPct']:+.2f}% ({r['wins']}/{r['years']}, {r['verdict']})" for r in RES["sweeps"] if r["verdict"] != "FAIL") +
                      (f". Candidate: affected rows {pa:+.2f}% vs v2.6 ({wa}/{ny2}), forward {fa:+.2f}% ({faw}/{fy})." if pieces else ". No piece passes."))
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "routes_volume_backtest.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_ROUTESVOL_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/routes_volume_backtest.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
