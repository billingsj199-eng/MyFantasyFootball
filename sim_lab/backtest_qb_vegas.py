#!/usr/bin/env python3
"""
QB IMPLIED-TOTAL LAYER on the Clay-free shadow (2026-09-16).

Jack: "build the QB implied total layer next." research_corr_horizons.py: the team's implied total is the top
weekly QB correlate (r .33, above the QB's own season-to-date PPG). The live engine's Vegas layer is
  veg = clip(1 + e x (implied - league avg) / league avg, .7, 1.35),  e = .25 QB / .50 RB / .25 WR / .25 TE
tuned 2026-07-30 on the CLAY base ("implied totals correlate with team quality Clay already prices; only the matchup
residual is exploitable"). The shadow's base is own history + the market prior, which prices team quality less,
so its elasticity may differ. Tests on QB rows (RB/WR/TE as a control), LOYO vs shadow v2.6:
  ELAS      QB elasticity e in {.25 .4 .5 .6 .75 1.0}: shadow / veg(.25) x veg(e)
  BAND      e by week band (weeks 2-4 prior-heavy vs 5+ evidence-heavy)
  FORM      spread and game total as extra terms (from bt_common's game table) - is it the total or the script?
  P         the QB prior strength (12) re-checked with the new elasticity
Log qb_vegas_backtest.log; results -> data/qb_vegas_backtest.js (SIM_QBVEG_BT), ZONES tab.
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
import backtest_second_year as SY
import bt_common as B
from backtest_target_area import mse

sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "qb_vegas_backtest.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

YEARS, POS4, BANDS = NW.YEARS, NW.POS4, NW.BANDS
FIT_WK = 8; RAMP = [0.7, 0.8]
E0 = {"QB": 0.25, "RB": 0.50, "WR": 0.25, "TE": 0.25}
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "reads": [], "sweeps": [], "candidate": {}}


def main():
    t0 = time.time()
    P("=== QB implied-total layer on the Clay-free shadow ===")
    S = NW.build_samples(); A = NW.arrays(S); n = len(S)
    act, year, wk, pos, g, ppg, clay, layers = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"]
    is_rookie, pid, team = A["rookie"], A["pid"], A["team"]
    shipped = NW.blend(clay, g, ppg, NW.PRIOR_P) * layers
    # game context: implied, opp implied, spread, total from bt_common's game table
    games = {Y: B.load_games(Y) for Y in YEARS}
    avg_imp = {Y: float(np.mean([v["implied"] for v in games[Y].values() if v["implied"] is not None])) for Y in YEARS}
    implied = np.array([(games[y].get((t, w)) or {}).get("implied", np.nan) or np.nan for y, t, w in zip(year, team, wk)], dtype=float)
    oppimp = np.array([(games[y].get((t, w)) or {}).get("oppImplied", np.nan) or np.nan for y, t, w in zip(year, team, wk)], dtype=float)
    lgavg = np.array([avg_imp[y] for y in year])
    x = (implied - lgavg) / lgavg                      # relative implied total
    veg0 = np.array([min(1.35, max(0.7, 1 + E0[p] * xi)) for p, xi in zip(pos, x)])
    total = implied + oppimp; spread = oppimp - implied   # positive = underdog
    # ---- shadow v2.6 ----
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
    PPOS0 = {"QB": 12, "RB": 5, "WR": 8, "TE": 8}
    def build(P_qb=12, e_qb=0.25, e_other=None, e_band=None, spread_k=0.0, total_k=0.0):
        wv = np.where(yr2, 0.5, 0.75); pr = np.where(mkt_ok, (1 - wv) * hist + wv * adp_curve, hist)
        miss = np.isnan(pr); pr[miss] = fb[miss]
        for ps, d in NC.VETDOCK.items():
            for sb, mm_ in d.items():
                mk = vet & (pos == ps) & (strb == sb); pr[mk] *= mm_
        pr = np.where(yr2lo & vet, pr * 1.2, pr)
        pr = fb_pos + 0.8 * (pr - fb_pos)
        Pv = np.array([PPOS0[ps] for ps in pos], dtype=float); Pv = np.where(pos == "QB", P_qb, Pv)
        e = np.array([E0[p] for p in pos]); e = np.where(pos == "QB", e_qb, e)
        if e_other is not None:
            for ps, ev in e_other.items(): e = np.where(pos == ps, ev, e)
        if e_band is not None:   # {(lo, hi): e} for QB rows
            for (lo, hi), ev in e_band.items(): e = np.where((pos == "QB") & (wk >= lo) & (wk <= hi), ev, e)
        veg = np.clip(1 + e * x, 0.7, 1.35)
        extra = np.where(pos == "QB", 1 + spread_k * np.nan_to_num(spread) / 10.0 + total_k * np.nan_to_num(total - 2 * lgavg) / lgavg, 1.0)
        out = NW.blend(pr, g, ppg, Pv) * (layers / veg0) * veg * extra
        for gi, m_ in enumerate(RAMP, start=1): out = np.where(buried_rk & (wk == gi), out * m_, out)
        return out
    ref = build()
    pc, w, ny = NW.pct_vs(ref, shipped, act, year)
    qb = pos == "QB"
    P(f"  {n} player-weeks | shadow v2.6 vs shipped {pc:+.2f}% ({w}/{ny}) | QB rows {qb.sum()}: {(mse(ref[qb], act[qb]) / mse(shipped[qb], act[qb]) - 1) * 100:+.2f}% vs shipped")

    # ---- reads: QB actual / shadow by implied-total bucket ----
    P("\n=== QB reads: actual / shadow (actual / shipped) by team implied total ===")
    for lab, lo, hi in (("implied < 19", 0, 19), ("19-22", 19, 22), ("22-25", 22, 25), ("25-28", 25, 28), ("28+", 28, 99)):
        mm = qb & (implied > lo) & (implied <= hi)
        if mm.sum() >= 40:
            row = {"label": lab, "n": int(mm.sum()), "actOverShadow": round(float(act[mm].mean() / ref[mm].mean()), 3), "actOverShipped": round(float(act[mm].mean() / shipped[mm].mean()), 3), "meanAct": round(float(act[mm].mean()), 2)}
            RES["reads"].append(row); P(f"  {lab:14s} n={mm.sum():5d} act/shadow {row['actOverShadow']:.3f} act/shipped {row['actOverShipped']:.3f} mean pts {row['meanAct']:.1f}")
    for lab, mm in (("favored by 7+", qb & (spread <= -7)), ("favored 0-7", qb & (spread > -7) & (spread <= 0)), ("underdog 0-7", qb & (spread > 0) & (spread <= 7)), ("underdog 7+", qb & (spread > 7))):
        if mm.sum() >= 40:
            row = {"label": lab, "n": int(mm.sum()), "actOverShadow": round(float(act[mm].mean() / ref[mm].mean()), 3), "actOverShipped": round(float(act[mm].mean() / shipped[mm].mean()), 3), "meanAct": round(float(act[mm].mean()), 2)}
            RES["reads"].append(row); P(f"  {lab:14s} n={mm.sum():5d} act/shadow {row['actOverShadow']:.3f} act/shipped {row['actOverShipped']:.3f} mean pts {row['meanAct']:.1f}")

    # ---- sweeps ----
    P("\n=== Sweeps (LOYO vs shadow v2.6) ===")
    DV.RES["sweeps"] = []
    grid_e = [0.25, 0.4, 0.5, 0.6, 0.75, 1.0]
    DV.loyo_vs_ref(A, ref, shipped, grid_e, lambda e_: build(e_qb=e_), "QB Vegas elasticity e (shadow)", qb)
    for lab, lo, hi in (("weeks 2-4", 2, 4), ("weeks 5-8", 5, 8), ("weeks 9+", 9, 18), ("week 1", 1, 1)):
        DV.loyo_vs_ref(A, ref, shipped, grid_e, lambda e_, lo=lo, hi=hi: build(e_band={(lo, hi): e_}), f"  QB e, {lab}", qb & (wk >= lo) & (wk <= hi))
    DV.loyo_vs_ref(A, ref, shipped, [0.0, -0.05, -0.1, 0.05, 0.1], lambda k_: build(e_qb=0.25, spread_k=k_), "QB spread term k (per 10 pts, + = underdog up), on top of e .25", qb)
    DV.loyo_vs_ref(A, ref, shipped, [12, 8, 16, 20], lambda p_: build(P_qb=p_, e_qb=0.25), "QB prior strength P (re-check at e .25)", qb)
    # control: the other positions on the shadow
    for ps in ("RB", "WR", "TE"):
        DV.loyo_vs_ref(A, ref, shipped, [E0[ps], 0.25, 0.4, 0.5, 0.75, 1.0], lambda e_, ps=ps: build(e_other={ps: e_}), f"  control: {ps} elasticity (shadow)", pos == ps)
    # the same sweep on the SHIPPED Clay blend, to confirm the base matters
    def shipped_e(e_):
        e = np.array([E0[p] for p in pos]); e = np.where(pos == "QB", e_, e); return shipped / veg0 * np.clip(1 + e * x, 0.7, 1.35)
    DV.loyo_vs_ref(A, shipped, shipped, grid_e, shipped_e, "  reference: QB e on the SHIPPED Clay blend", qb)
    RES["sweeps"] = DV.RES["sweeps"]
    # ---- candidate: best QB e (pooled), with P re-picked; forward ----
    top = RES["sweeps"][0]; e_best = top["pooledBest"]
    DV.RES["sweeps"] = []
    DV.loyo_vs_ref(A, ref, shipped, [12, 8, 16, 20], lambda p_: build(P_qb=p_, e_qb=e_best), f"QB P at e {e_best}", qb)
    p_row = DV.RES["sweeps"][-1]; RES["sweeps"].append(p_row)
    P_best = p_row["pooledBest"] if p_row["verdict"] in ("PASS", "lean") else 12
    cand = build(P_qb=P_best, e_qb=e_best)
    pc2, w2, ny2 = NW.pct_vs(cand, shipped, act, year); pv, wvv, _ = NW.pct_vs(cand, ref, act, year); pq, wq, _ = NW.pct_vs(cand[qb], ref[qb], act[qb], year[qb])
    P(f"\n=== Candidate: QB e {e_best}, P {P_best} ===")
    P(f"  ALL rows: vs shipped {pc2:+.2f}% ({w2}/{ny2}) | vs shadow v2.6 {pv:+.2f}% ({wvv}/{ny2}) | QB rows {pq:+.2f}% vs shadow ({wq}/{ny2}), vs shipped {(mse(cand[qb], act[qb]) / mse(shipped[qb], act[qb]) - 1) * 100:+.2f}% (was {(mse(ref[qb], act[qb]) / mse(shipped[qb], act[qb]) - 1) * 100:+.2f}%)")
    for lab, lo, hi in BANDS:
        mm = qb & (wk >= lo) & (wk <= hi); P(f"  QB {lab:7s} shadow {(mse(ref[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100:+6.2f}% -> {(mse(cand[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100:+6.2f}% vs shipped")
    fwd = np.full(n, np.nan)
    for y in YEARS[2:]:
        mk = qb & (year < y)
        e_y = min(grid_e, key=lambda e_: mse(build(e_qb=e_)[mk], act[mk]))
        fwd = np.where(year == y, build(P_qb=P_best, e_qb=e_y), fwd)
    fm = year >= YEARS[2]; fq = fm & qb
    fr, frw, fy = NW.pct_vs(fwd[fm], ref[fm], act[fm], year[fm]); fqr, fqw, _ = NW.pct_vs(fwd[fq], ref[fq], act[fq], year[fq])
    P(f"  FORWARD (2021-25, e picked on earlier seasons): all rows {fr:+.2f}% vs shadow ({frw}/{fy}) | QB rows {fqr:+.2f}% ({fqw}/{fy})")
    RES["candidate"] = {"e": float(e_best), "P": float(P_best), "pct": round(pc2, 3), "wins": int(w2), "years": ny2, "vsRef": round(pv, 3), "vsRefWins": int(wvv), "qbVsRef": round(pq, 3), "qbWins": int(wq),
                        "qbVsShip": round((mse(cand[qb], act[qb]) / mse(shipped[qb], act[qb]) - 1) * 100, 3), "qbRefVsShip": round((mse(ref[qb], act[qb]) / mse(shipped[qb], act[qb]) - 1) * 100, 3),
                        "forward": {"vsRef": round(fr, 3), "vsRefWins": int(frw), "years": fy, "qbVsRef": round(fqr, 3), "qbWins": int(fqw)}}
    RES["summary"] = (f"QB rows: shadow {RES['candidate']['qbRefVsShip']:+.2f}% vs shipped. QB Vegas elasticity on the shadow: best {e_best} ({top['loyoPct']:+.2f}% vs shadow, {top['wins']}/{top['years']}, {top['verdict']}); "
                      f"on the shipped Clay blend the .25 stays. Candidate QB rows {pq:+.2f}% vs v2.6 ({wq}/{ny2}), forward {fqr:+.2f}% ({fqw}/{fy}).")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "qb_vegas_backtest.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_QBVEG_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/qb_vegas_backtest.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
