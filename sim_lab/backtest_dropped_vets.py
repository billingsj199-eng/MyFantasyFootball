#!/usr/bin/env python3
"""
DROPPED-OFF-THE-CHART VETERANS on the Clay-free shadow (2026-09-16).

Jack: "build the dropped-off-the-chart vets layer next." backtest_nochart_vets.py found 177 veteran
player-weeks listed on the same team's chart 1-3 weeks earlier but not this week (actual / shadow prior .90,
shadow +4.2% vs shipped there). Hypothesis: dropping off the chart = hurt / limited, which the LIVE engine already
docks through the injury layer (Doubtful x.5, Questionable + DNP x.75; Out -> 0) on both the shipped mean and
the shadow - the historical harness has no such docks. So: join the official injury reports (pbp_cache/
injuries_Y.parquet), apply the live docks to the harness for everyone, then ask whether the chart drop carries
anything BEYOND the designation.
  reads     actual / shadow prior for dropped rows by designation (none / Q+FP / Q+LP / Q+DNP / Doubtful) vs the
            same designations among listed veterans
  layers    prior x m on dropped rows with no designation; prior x m on dropped rows with a designation (on top
            of the live docks); LOYO vs shadow v2.4 (+ live docks), forward
Log dropped_vets_backtest.log; results -> data/dropped_vets_backtest.js (SIM_DROPPED_BT), ZONES tab.
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
import bt_common as B
from backtest_target_area import mse

sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "dropped_vets_backtest.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

YEARS, POS4, BANDS = NW.YEARS, NW.POS4, NW.BANDS
FIT_WK = 8
LIVE_DOCK = {"Doubtful": 0.5, "Q-DNP": 0.75, "Q-LP": 1.0, "Q-FP": 1.0}   # engine applyInSeasonInjuries (Out -> 0 not applied: an Out who played is a report error)
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "reads": [], "sweeps": [], "candidate": {}}


def load_injuries():
    out = {}
    for Y in YEARS:
        d = pd.read_parquet(os.path.join(B.CACHE, f"injuries_{Y}.parquet"))
        d = d[(d.game_type == "REG") & d.gsis_id.notna()]
        for r in d.itertuples(index=False):
            rs = str(r.report_status or ""); ps = str(r.practice_status or "")
            cls = None
            if rs == "Out": cls = "Out"
            elif rs == "Doubtful": cls = "Doubtful"
            elif rs == "Questionable": cls = "Q-DNP" if ps.startswith("Did Not") else ("Q-LP" if ps.startswith("Limited") else "Q-FP")
            if cls: out[(Y, r.gsis_id, int(r.week))] = cls
    return out


def main():
    t0 = time.time()
    P("=== Dropped-off-the-chart veterans ===")
    S = NW.build_samples(); A = NW.arrays(S); n = len(S)
    act, year, wk, pos, g, ppg, clay, layers = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"]
    is_rookie, pid, team = A["rookie"], A["pid"], A["team"]
    inj = load_injuries()
    desig = np.array([inj.get((year[i], pid[i], wk[i])) if pid[i] else None for i in range(n)], dtype=object)
    dockv = np.array([LIVE_DOCK.get(d, 1.0) if d else 1.0 for d in desig])
    shipped = NW.blend(clay, g, ppg, NW.PRIOR_P) * layers * dockv
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
    str_any = np.where(np.isnan(string), any_str, string); has = ~np.isnan(str_any)
    last_str = np.full(n, np.nan)
    for i in np.where(~has)[0]:
        for lag in (1, 2, 3):
            if wk[i] - lag < 1: break
            s = string_at(i, wk[i] - lag)
            if s is not None: last_str[i] = s; break
    # ---- shadow v2.4 prior ----
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
    strb = np.where(has, np.minimum(str_any, 3), np.nan)
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
    prior24 = prior0.copy()
    for ps, d in NC.VETDOCK.items():
        for sb, m_ in d.items():
            mk = vet & (pos == ps) & (strb == sb); prior24[mk] *= m_
    PPOS = {"QB": 12, "RB": 5, "WR": 8, "TE": 8}; K = 0.8; Pvec = np.array([PPOS[ps] for ps in pos], dtype=float)
    def pred_of(prior): return NW.blend(fb_pos + K * (prior - fb_pos), g, ppg, Pvec) * layers * dockv
    ref = pred_of(prior24); shr = fb_pos + K * (prior24 - fb_pos)
    pc, w, ny = NW.pct_vs(ref, shipped, act, year)
    dropped = vet & ~has & ~np.isnan(last_str)
    P(f"  {n} player-weeks | live injury docks applied to both sides (designated rows: {int((desig != None).sum())}) | shadow v2.4 vs shipped {pc:+.2f}% ({w}/{ny}) | dropped vets: {dropped.sum()}")

    # ---- reads ----
    P("\n=== Dropped rows by designation vs listed veterans with the same designation (actual / shadow prior, after live docks) ===")
    dcls = np.array([d if d else "none" for d in desig], dtype=object)
    for cls in ("none", "Q-FP", "Q-LP", "Q-DNP", "Doubtful", "Out"):
        md = dropped & (dcls == cls); ml = vet & has & (dcls == cls)
        row = {"cls": cls, "droppedN": int(md.sum()), "droppedRatio": round(float(act[md].mean() / (shr[md] * dockv[md]).mean()), 3) if md.sum() else None,
               "listedN": int(ml.sum()), "listedRatio": round(float(act[ml].mean() / (shr[ml] * dockv[ml]).mean()), 3) if ml.sum() else None}
        RES["reads"].append(row)
        P(f"  {cls:9s} dropped n={md.sum():4d} act/prior {row['droppedRatio']}   | listed n={ml.sum():5d} act/prior {row['listedRatio']}")
    P("  dropped rows by position: " + " ".join(f"{ps} n{(dropped & (pos == ps)).sum()} {act[dropped & (pos == ps)].mean() / (shr * dockv)[dropped & (pos == ps)].mean():.2f}" for ps in POS4 if (dropped & (pos == ps)).sum() >= 10))
    P("  dropped rows by last string: " + " ".join(f"str{sb} n{(dropped & (np.minimum(last_str, 3) == sb)).sum()} {act[dropped & (np.minimum(last_str, 3) == sb)].mean() / (shr * dockv)[dropped & (np.minimum(last_str, 3) == sb)].mean():.2f}" for sb in (1, 2, 3) if (dropped & (np.minimum(last_str, 3) == sb)).sum() >= 10))
    P(f"  designated share: dropped {100 * (dropped & (dcls != 'none')).sum() / max(1, dropped.sum()):.0f}% vs listed vets {100 * (vet & has & (dcls != 'none')).sum() / max(1, (vet & has).sum()):.0f}%")

    # ---- layers ----
    P("\n=== Layers: prior x m on dropped rows, LOYO vs shadow v2.4 (+ live docks) ===")
    def dock(m_, mask):
        pr = prior24.copy(); pr[mask] *= m_; return pred_of(pr)
    DV.RES["sweeps"] = []
    grid = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5]
    DV.loyo_vs_ref(A, ref, shipped, grid, lambda m_: dock(m_, dropped), "dropped, all", dropped)
    nd = dropped & (dcls == "none"); wd = dropped & (dcls != "none")
    DV.loyo_vs_ref(A, ref, shipped, grid, lambda m_: dock(m_, nd), "dropped, NO designation", nd)
    DV.loyo_vs_ref(A, ref, shipped, grid, lambda m_: dock(m_, wd), "dropped, WITH a designation (on top of the live dock)", wd)
    for ps in ("RB", "WR", "TE"):
        mk = dropped & (pos == ps)
        if mk.sum() >= 40: DV.loyo_vs_ref(A, ref, shipped, grid, lambda m_, mk=mk: dock(m_, mk), f"  dropped {ps}", mk)
    # the same question for LISTED vets with a designation: is the live dock calibrated on the shadow?
    for cls in ("Q-FP", "Q-LP", "Q-DNP"):
        mk = vet & has & (dcls == cls)
        if mk.sum() >= 60: DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.9, 0.8, 0.7, 1.1], lambda m_, mk=mk: dock(m_, mk), f"  listed vets {cls} extra multiplier (check)", mk)
    RES["sweeps"] = DV.RES["sweeps"]
    # ---- candidate + forward ----
    top = RES["sweeps"][0]; nd_row = RES["sweeps"][1]
    use = nd if nd_row["verdict"] in ("PASS", "lean") and nd_row["loyoPct"] <= top["loyoPct"] else dropped
    use_lab = "no designation only" if use is nd else "all dropped"
    m_c = (nd_row if use is nd else top)["pooledBest"]
    cand = dock(m_c, use)
    pc2, w2, ny2 = NW.pct_vs(cand, shipped, act, year); pv, wvv, _ = NW.pct_vs(cand, ref, act, year)
    P(f"\n=== Candidate: dropped ({use_lab}) x{m_c} ===")
    P(f"  ALL rows: vs shipped {pc2:+.2f}% ({w2}/{ny2}) | vs shadow v2.4 {pv:+.2f}% ({wvv}/{ny2}) | dropped rows: shadow {(mse(ref[dropped], act[dropped]) / mse(shipped[dropped], act[dropped]) - 1) * 100:+.2f}% -> {(mse(cand[dropped], act[dropped]) / mse(shipped[dropped], act[dropped]) - 1) * 100:+.2f}% vs shipped")
    fwd = np.full(n, np.nan)
    for y in YEARS[2:]:
        mk = use & (year < y)
        m_y = min(grid, key=lambda m_: mse(dock(m_, use)[mk], act[mk])) if mk.sum() >= 30 else 1.0
        fwd = np.where(year == y, dock(m_y, use), fwd)
    fm = year >= YEARS[2]; dm = fm & dropped
    fr, frw, fy = NW.pct_vs(fwd[fm], ref[fm], act[fm], year[fm])
    P(f"  FORWARD (2021-25, m picked on earlier seasons): {fr:+.2f}% vs shadow ({frw}/{fy}) | dropped rows {(mse(fwd[dm], act[dm]) / mse(ref[dm], act[dm]) - 1) * 100:+.2f}%")
    RES["candidate"] = {"mask": use_lab, "m": float(m_c), "pct": round(pc2, 3), "wins": int(w2), "years": ny2, "vsRef": round(pv, 3), "vsRefWins": int(wvv),
                        "forward": {"vsRef": round(fr, 3), "vsRefWins": int(frw), "years": fy, "droppedVsRef": round((mse(fwd[dm], act[dm]) / mse(ref[dm], act[dm]) - 1) * 100, 3)},
                        "droppedN": int(dropped.sum()), "designatedShare": round(float((dropped & (dcls != 'none')).sum() / max(1, dropped.sum())), 3)}
    RES["summary"] = (f"Dropped vets n={dropped.sum()}, {100*RES['candidate']['designatedShare']:.0f}% carry an injury designation the live layer already docks. "
                      f"Dock on dropped rows: all {top['loyoPct']:+.2f}% vs shadow ({top['wins']}/{top['years']}, {top['verdict']}); no designation {nd_row['loyoPct']:+.2f}% ({nd_row['wins']}/{nd_row['years']}, {nd_row['verdict']}). "
                      f"Candidate {pv:+.2f}% vs v2.4 ({wvv}/{ny2}), forward {fr:+.2f}% ({frw}/{fy}).")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "dropped_vets_backtest.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_DROPPED_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/dropped_vets_backtest.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
