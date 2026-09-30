#!/usr/bin/env python3
"""
VETERANS WITHOUT A CHART on the Clay-free shadow (2026-09-16).

Jack: "build the vets without a chart layer next." backtest_demoted_vets.py left 1,180 veteran player-weeks
with a history prior but no pre-game depth-chart string, running +2.7% vs the shipped Clay blend (shadow v2.3
is -1.1% overall). Before a layer: WHO are they? For each such row, look for the player on ANY team's chart that
week (team mismatch on our side), on the same team's chart in the previous 1-3 weeks (dropped this week = the
chart missed him or he was hurt / just back), or nowhere in the last 3 weeks (truly unlisted).
Layers, graded vs shadow v2.3 (LOYO, forward):
  CARRY     use the last known string within 3 weeks (then the v2.3 dock applies as if listed)
  ANYTEAM   use the string from whichever team lists him this week (fixes our team inference)
  UNLISTED  prior x m for veterans on no chart in the last 3 weeks
Log nochart_vets_backtest.log; results -> data/nochart_vets_backtest.js (SIM_NOCHART_BT), ZONES tab.
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
import bt_common as B
from backtest_target_area import mse

if __name__ == "__main__":   # importable (backtest_dropped_vets.py) without truncating this log
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "nochart_vets_backtest.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

YEARS, POS4, BANDS = NW.YEARS, NW.POS4, NW.BANDS
FIT_WK = 8
VETDOCK = {"RB": {2: 0.8, 3: 0.4}, "WR": {2: 0.6, 3: 0.6}, "TE": {2: 0.8}}
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "causes": [], "reads": [], "sweeps": [], "candidate": {}}


def load_depth_any():
    """string by (Y, gsis, wk) on ANY team (2019-24), and by (gsis) dated list (2025) - team-agnostic."""
    weekly_any, dated_any = {}, {}
    for Y in YEARS:
        d = pd.read_parquet(os.path.join(B.CACHE, f"depth_charts_{Y}.parquet"))
        if "depth_team" in d.columns:
            d = d[(d.game_type == "REG") & d.position.isin(POS4) & (d.depth_position == d.position) & d.gsis_id.notna()]
            for r in d.itertuples(index=False):
                try: s = int(r.depth_team)
                except Exception: continue
                k = (Y, r.gsis_id, int(r.week)); weekly_any[k] = min(weekly_any.get(k, (99, None))[0], s), B.tm(str(r.club_code))
        else:
            d = d[d.pos_abb.isin(POS4) & d.gsis_id.notna()].copy()
            d["dt"] = pd.to_datetime(d.dt, utc=True).dt.tz_localize(None)
            for r in d.itertuples(index=False):
                dated_any.setdefault(r.gsis_id, []).append((r.dt, int(np.ceil(int(r.pos_rank) / RD.SLOTS[r.pos_abb])), B.tm(str(r.team))))
            for k in dated_any: dated_any[k].sort()
    return weekly_any, dated_any


def main():
    t0 = time.time()
    P("=== Veterans without a chart ===")
    S = NW.build_samples(); A = NW.arrays(S); n = len(S)
    act, year, wk, pos, g, ppg, clay, layers = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"]
    is_rookie, pid, team = A["rookie"], A["pid"], A["team"]
    shipped = NW.blend(clay, g, ppg, NW.PRIOR_P) * layers
    weekly, dated = RD.load_depth(); weekly_any, dated_any = load_depth_any(); games = {Y: B.load_games(Y) for Y in YEARS}
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
    has = ~np.isnan(string); strb = np.where(has, np.minimum(string, 3), np.nan)
    # ---- shadow v2.3 prior ----
    adp_map = RP.load_adp()
    adp = np.array([adp_map.get((y, NW.cal.norm(nm), ps), np.nan) for y, nm, ps in zip(year, A["name"], pos)])
    has_adp = ~np.isnan(adp); ladp = np.log(np.where(has_adp, adp, RP.ADP_CAP)); lpick = np.log(np.where(np.isnan(A["pick"]), 262.0, A["pick"]))
    h3, l8 = A["h3"], A["l8"]; has_h3, has_l8 = ~np.isnan(h3), ~np.isnan(l8)
    base = np.full(n, np.nan); both = has_h3 & has_l8
    base[both] = 0.5 * h3[both] + 0.5 * l8[both]; base[has_h3 & ~has_l8] = h3[has_h3 & ~has_l8]; base[~has_h3 & has_l8] = l8[~has_h3 & has_l8]
    for i in np.where(~np.isnan(base))[0]: base[i] = NW.age_adjust(pos[i], base[i], A["age"][i])
    oppcal = A["oppcal"]; vet_opp = (~np.isnan(oppcal)) & (A["seg"] != "rookie") & (~is_rookie) & ~np.isnan(base) & (base >= 4); base[vet_opp] = oppcal[vet_opp]
    adp_curve = np.full(n, np.nan)
    for y in YEARS:
        for ps in POS4:
            tr = (year != y) & (pos == ps) & has_adp & (wk <= FIT_WK); ap = (year == y) & (pos == ps) & has_adp
            if tr.sum() >= 60 and ap.any():
                b = np.linalg.lstsq(np.column_stack([np.ones(tr.sum()), ladp[tr]]), act[tr], rcond=None)[0]; adp_curve[ap] = np.maximum(0.5, b[0] + b[1] * ladp[ap])
    yr2 = A["exp"] == 1; wv = np.where(yr2, 0.5, 0.75); sel = ~is_rookie & ~np.isnan(adp_curve) & ~np.isnan(base)
    base = np.where(sel, (1 - wv) * base + wv * adp_curve, base); has_hist = ~np.isnan(base)
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
    prior0 = base.copy(); miss = np.isnan(prior0); prior0[miss] = fb[miss]
    vet = ~is_rookie & has_hist
    def dock_by(strv, pr):
        pr = pr.copy()
        for ps, d in VETDOCK.items():
            for sb, m_ in d.items():
                mk = vet & (pos == ps) & (np.minimum(np.where(np.isnan(strv), 0, strv), 3) == sb); pr[mk] *= m_
        return pr
    prior23 = dock_by(string, prior0)
    PPOS = {"QB": 12, "RB": 5, "WR": 8, "TE": 8}; K = 0.8; Pvec = np.array([PPOS[ps] for ps in pos], dtype=float)
    def pred_of(prior): return NW.blend(fb_pos + K * (prior - fb_pos), g, ppg, Pvec) * layers
    ref = pred_of(prior23)
    pc, w, ny = NW.pct_vs(ref, shipped, act, year)
    nochart = vet & ~has
    P(f"  {n} player-weeks | shadow v2.3 vs shipped {pc:+.2f}% ({w}/{ny}) | veterans without a chart: {nochart.sum()} ({100*nochart.sum()/vet.sum():.1f}% of vets)")

    # ---- causes ----
    any_str = np.array([np.nan if string_at(i, wk[i], False) is None else string_at(i, wk[i], False) for i in range(n)], dtype=float)
    last_str = np.full(n, np.nan); last_lag = np.full(n, np.nan)
    for i in np.where(nochart)[0]:
        for lag in (1, 2, 3):
            if wk[i] - lag < 1: break
            s = string_at(i, wk[i] - lag)
            if s is not None: last_str[i] = s; last_lag[i] = lag; break
    on_any = nochart & ~np.isnan(any_str); carried = nochart & np.isnan(any_str) & ~np.isnan(last_str); truly = nochart & np.isnan(any_str) & np.isnan(last_str)
    P("\n=== Causes (actual / shadow prior, actual / shipped) ===")
    for lab, mm in (("listed on ANOTHER team this week", on_any), ("same team, listed 1-3 weeks ago, not this week", carried), ("on no chart in the last 3 weeks", truly), ("week 1 (no earlier chart possible)", truly & (wk == 1))):
        pr23 = fb_pos + K * (prior23 - fb_pos)
        row = {"cause": lab, "n": int(mm.sum()), "actOverPrior": round(float(act[mm].mean() / pr23[mm].mean()), 3) if mm.sum() else None, "actOverShipped": round(float(act[mm].mean() / shipped[mm].mean()), 3) if mm.sum() else None,
               "vsShip": round((mse(ref[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 2) if mm.sum() >= 20 else None}
        RES["causes"].append(row); P(f"  {lab:48s} n={mm.sum():5d} act/prior {row['actOverPrior']} act/shipped {row['actOverShipped']} shadow vs shipped {row['vsShip']}")
    P("  by position (truly unlisted): " + " ".join(f"{ps} n{(truly & (pos == ps)).sum()} act/prior {act[truly & (pos == ps)].mean() / (fb_pos + K * (prior23 - fb_pos))[truly & (pos == ps)].mean():.2f}" for ps in POS4 if (truly & (pos == ps)).sum() >= 20))
    P("  by week band (truly unlisted): " + " ".join(f"{lab} n{(truly & (wk >= lo) & (wk <= hi)).sum()}" for lab, lo, hi in BANDS))
    P("  carried rows by last string: " + " ".join(f"str{sb} n{(carried & (np.minimum(last_str, 3) == sb)).sum()} act/prior {act[carried & (np.minimum(last_str, 3) == sb)].mean() / (fb_pos + K * (prior23 - fb_pos))[carried & (np.minimum(last_str, 3) == sb)].mean():.2f}" for sb in (1, 2, 3) if (carried & (np.minimum(last_str, 3) == sb)).sum() >= 15))

    # ---- layers, graded vs v2.3 ----
    P("\n=== Layers (LOYO vs shadow v2.3) ===")
    str_carry = string.copy(); str_carry[carried] = last_str[carried]
    str_any = string.copy(); str_any[on_any] = any_str[on_any]
    str_both = str_carry.copy(); str_both[on_any] = any_str[on_any]
    def with_str(strv): return pred_of(dock_by(strv, prior0))
    for lab, strv, mm in (("CARRY last string (1-3 wks)", str_carry, carried), ("ANYTEAM string", str_any, on_any), ("CARRY + ANYTEAM", str_both, carried | on_any)):
        pred = with_str(strv)
        pv, wvv, _ = NW.pct_vs(pred, ref, act, year)
        sub = (mse(pred[mm], act[mm]) / mse(ref[mm], act[mm]) - 1) * 100 if mm.sum() else float("nan")
        P(f"  {lab:32s} all rows {pv:+.2f}% vs shadow ({wvv}/{ny}) | affected rows n={mm.sum()} {sub:+.2f}%")
        RES["sweeps"].append({"label": lab, "n": int(mm.sum()), "loyoPct": round(pv, 3), "wins": int(wvv), "years": ny, "affectedPct": round(sub, 3), "picks": [], "verdict": "PASS" if (sub <= -1 and wvv >= 5) else ("lean" if sub < 0 and wvv >= 4 else "FAIL")})
    def dock_unlisted(m_, mask):
        pr = dock_by(str_both, prior0).copy(); pr[mask] *= m_; return pred_of(pr)
    ref2 = with_str(str_both)
    DV.RES["sweeps"] = []
    DV.loyo_vs_ref(A, ref2, shipped, [1.0, 0.9, 0.8, 0.7, 0.6, 0.5], lambda m_: dock_unlisted(m_, truly), "UNLISTED dock, vets on no chart in 3 wks (after CARRY+ANYTEAM)", truly)
    for ps in POS4:
        mk = truly & (pos == ps)
        if mk.sum() >= 60: DV.loyo_vs_ref(A, ref2, shipped, [1.0, 0.9, 0.8, 0.7, 0.6, 0.5], lambda m_, mk=mk: dock_unlisted(m_, mk), f"  UNLISTED dock {ps}", mk)
    mk = truly & (wk >= 2)
    DV.loyo_vs_ref(A, ref2, shipped, [1.0, 0.9, 0.8, 0.7, 0.6, 0.5], lambda m_, mk=mk: dock_unlisted(m_, mk), "  UNLISTED dock, weeks 2+ only", mk)
    RES["sweeps"] += DV.RES["sweeps"]
    # ---- candidate: CARRY + ANYTEAM (+ unlisted dock if it passed) ----
    ud = [r for r in DV.RES["sweeps"] if r["label"].startswith("UNLISTED dock, vets")][0]
    # the unlisted dock passes pooled but fails RB (0/7) and TE and is flat forward; CARRY hurts -> candidate = ANYTEAM only
    m_un = 1.0
    cand = with_str(str_any)
    pc, w, ny = NW.pct_vs(cand, shipped, act, year); pv, wvv, _ = NW.pct_vs(cand, ref, act, year)
    P(f"\n=== Candidate v2.4: ANYTEAM string only (CARRY hurts; unlisted dock fails by position and forward) ===")
    P(f"  ALL rows: vs shipped {pc:+.2f}% ({w}/{ny}) | vs shadow v2.3 {pv:+.2f}% ({wvv}/{ny})")
    c = {"unlistedDock": float(m_un), "pct": round(pc, 3), "wins": int(w), "years": ny, "vsRef": round(pv, 3), "vsRefWins": int(wvv), "segments": [], "bands": []}
    for lab, mm in (("no-chart vets (all causes)", nochart), ("listed elsewhere", on_any), ("carried", carried), ("truly unlisted", truly)):
        row = {"seg": lab, "n": int(mm.sum()), "vsShip": round((mse(cand[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 3), "refVsShip": round((mse(ref[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 3)}
        c["segments"].append(row); P(f"  {lab:28s} n={mm.sum():5d} shadow {row['refVsShip']:+6.2f}% -> {row['vsShip']:+6.2f}% vs shipped")
    for lab, lo, hi in BANDS:
        mm = (wk >= lo) & (wk <= hi)
        row = {"band": lab, "n": int(mm.sum()), "vsShip": round((mse(cand[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 3), "refVsShip": round((mse(ref[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 3)}
        c["bands"].append(row); P(f"  {lab:7s} shadow {row['refVsShip']:+6.2f}% -> {row['vsShip']:+6.2f}% vs shipped")
    # forward for the unlisted dock (strings need no fitting)
    if True:   # forward read of the unlisted dock, for the record
        fwd = np.full(n, np.nan)
        for y in YEARS[2:]:
            mk = truly & (year < y)
            m_y = min([1.0, 0.9, 0.8, 0.7, 0.6, 0.5], key=lambda m_: mse(dock_unlisted(m_, truly)[mk], act[mk]))
            fwd = np.where(year == y, dock_unlisted(m_y, truly), fwd)
        fm = year >= YEARS[2]
        fr, frw, fy = NW.pct_vs(fwd[fm], ref2[fm], act[fm], year[fm])
        P(f"  FORWARD unlisted dock (2021-25, picked on earlier seasons): {fr:+.2f}% vs CARRY+ANYTEAM shadow ({frw}/{fy})")
        c["forward"] = {"vsRef": round(fr, 3), "vsRefWins": int(frw), "years": fy}
    RES["candidate"] = c
    RES["summary"] = (f"No-chart vets: {on_any.sum()} listed on another team (our team inference), {carried.sum()} listed 1-3 weeks earlier, {truly.sum()} on no chart. "
                      f"CARRY + ANYTEAM {[r for r in RES['sweeps'] if r['label']=='CARRY + ANYTEAM'][0]['affectedPct']:+.2f}% on affected rows; unlisted dock {ud['loyoPct']:+.2f}% ({ud['wins']}/{ud['years']}, {ud['verdict']}). "
                      f"Unlisted dock fails RB 0/7 and forward -> not shipped. Candidate v2.4 = current-team chart lookup only: {pv:+.2f}% vs v2.3 ({wvv}/{ny}), {pc:+.2f}% vs shipped.")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "nochart_vets_backtest.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_NOCHART_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/nochart_vets_backtest.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
