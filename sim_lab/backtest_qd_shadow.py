#!/usr/bin/env python3
"""
QUESTIONABLE / DOUBTFUL DOCKS on the Clay-free shadow (2026-09-16).

Jack: "build the questionable doubtful layer for the shadow next." The live game-week docks (Doubtful x.5, Questionable
+ DNP x.75, Q + LP / FP x1) were calibrated on the Clay base and apply to the shadow through the same chain. Here each
designation class is graded on the SHADOW with the live docks already applied (so the sweep is the extra multiplier
the shadow wants), split by position, starter vs backup (chart string), and whether the player played last week
(returning vs banged-up), then forward. Official reports: pbp_cache/injuries_Y.parquet.
Log qd_shadow_backtest.log; results -> data/qd_shadow_backtest.js (SIM_QD_BT), ZONES tab.
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

sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "qd_shadow_backtest.log"), "w", encoding="utf-8"))
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
    P("=== Questionable / Doubtful docks on the Clay-free shadow ===")
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

    # ---- designation classes ----
    dcls = np.array([d if d else "none" for d in desig], dtype=object)
    # played last week? (from the weekly DB)
    cache = {}; prev_played = np.zeros(n, dtype=bool)
    for i in range(n):
        k = (year[i], A["name"][i], pos[i])
        if k not in cache:
            rec = NW.cal.weekly_rec(A["name"][i], pos[i]); cache[k] = {int(r["wk"]) for r in (rec.get("seasons", {}).get(str(year[i]), []) if rec else []) if NW.cal.played(r)}
        prev_played[i] = (wk[i] - 1) in cache[k]
    starter = strb == 1
    P(f"  designated rows: " + ", ".join(f"{c} {int((dcls == c).sum())}" for c in ("Q-FP", "Q-LP", "Q-DNP", "Doubtful")) + f" | live docks in the harness: {LIVE_DOCK}")
    P("\n=== Reads: actual / shadow (live docks applied) by designation ===")
    for cls in ("none", "Q-FP", "Q-LP", "Q-DNP", "Doubtful"):
        for lab, mm in (("all", dcls == cls), ("starters", (dcls == cls) & starter), ("backups", (dcls == cls) & (strb >= 2)), ("played last wk", (dcls == cls) & prev_played & (wk >= 2)), ("missed last wk", (dcls == cls) & ~prev_played & (wk >= 2))):
            if mm.sum() >= 30:
                row = {"cls": cls, "split": lab, "n": int(mm.sum()), "actOverShadow": round(float(act[mm].mean() / ref[mm].mean()), 3), "actOverShipped": round(float(act[mm].mean() / shipped[mm].mean()), 3), "vsShip": round((mse(ref[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 2)}
                RES["reads"].append(row); P(f"  {cls:9s} {lab:15s} n={mm.sum():5d} act/shadow {row['actOverShadow']:.3f} act/shipped {row['actOverShipped']:.3f} shadow vs shipped {row['vsShip']:+6.2f}%")
        for ps in POS4:
            mm = (dcls == cls) & (pos == ps)
            if mm.sum() >= 40 and cls != "none":
                row = {"cls": cls, "split": ps, "n": int(mm.sum()), "actOverShadow": round(float(act[mm].mean() / ref[mm].mean()), 3), "actOverShipped": round(float(act[mm].mean() / shipped[mm].mean()), 3), "vsShip": round((mse(ref[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 2)}
                RES["reads"].append(row); P(f"  {cls:9s} {ps:15s} n={mm.sum():5d} act/shadow {row['actOverShadow']:.3f} act/shipped {row['actOverShipped']:.3f} shadow vs shipped {row['vsShip']:+6.2f}%")
    # ---- sweeps: extra multiplier on the shadow per class ----
    P("\n=== Sweeps: extra multiplier on top of the live dock, LOYO vs shadow ===")
    DV.RES["sweeps"] = []
    def mult(m_, mask): return ref * np.where(mask, m_, 1.0)
    GRIDS = {"Doubtful": [1.0, 0.8, 0.6, 0.4, 0.2, 1.2], "Q-DNP": [1.0, 0.9, 0.8, 0.7, 1.1, 1.2], "Q-LP": [1.0, 0.95, 0.9, 0.85, 0.8, 1.05], "Q-FP": [1.0, 0.95, 0.9, 0.85, 1.05]}
    masks = {}
    for cls in ("Doubtful", "Q-DNP", "Q-LP", "Q-FP"):
        mk = dcls == cls
        if mk.sum() >= 40: masks[f"{cls} x m"] = mk; DV.loyo_vs_ref(A, ref, shipped, GRIDS[cls], lambda m_, mk=mk: mult(m_, mk), f"{cls} x m", mk)
        for lab, sub in (("starters", starter), ("backups", strb >= 2), ("played last wk", prev_played & (wk >= 2)), ("missed last wk", ~prev_played & (wk >= 2))):
            mm = mk & sub
            if mm.sum() >= 60: masks[f"  {cls} & {lab} x m"] = mm; DV.loyo_vs_ref(A, ref, shipped, GRIDS[cls], lambda m_, mm=mm: mult(m_, mm), f"  {cls} & {lab} x m", mm)
        for ps in POS4:
            mm = mk & (pos == ps)
            if mm.sum() >= 80: masks[f"  {cls} {ps} x m"] = mm; DV.loyo_vs_ref(A, ref, shipped, GRIDS[cls], lambda m_, mm=mm: mult(m_, mm), f"  {cls} {ps} x m", mm)
    # the combined returning-player form: Questionable (any practice status) & missed last week
    qret = ((dcls == "Q-LP") | (dcls == "Q-FP") | (dcls == "Q-DNP")) & ~prev_played & (wk >= 2)
    masks["Questionable & missed last wk (any practice) x m"] = qret
    DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7], lambda m_: mult(m_, qret), "Questionable & missed last wk (any practice) x m", qret)
    for ps in POS4:
        mm = qret & (pos == ps)
        if mm.sum() >= 40: masks[f"  Q & missed last wk {ps} x m"] = mm; DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.9, 0.85, 0.8, 0.7], lambda m_, mm=mm: mult(m_, mm), f"  Q & missed last wk {ps} x m", mm)
    qret_st = qret & starter
    if qret_st.sum() >= 40: masks["  Q & missed last wk & starter x m"] = qret_st; DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.9, 0.85, 0.8, 0.7], lambda m_: mult(m_, qret_st), "  Q & missed last wk & starter x m", qret_st)
    RES["sweeps"] = DV.RES["sweeps"]
    passing = [r for r in RES["sweeps"] if r["verdict"] == "PASS" and "missed last wk (any practice)" in r["label"]] or [r for r in RES["sweeps"] if r["verdict"] == "PASS"]
    P("\n=== Candidate from PASS pieces: " + (", ".join(f"{r['label'].strip()} = {r['pooledBest']}" for r in passing) if passing else "NONE") + " ===")
    def cand_pred(cfg):
        out = ref.copy()
        for lab, v in cfg.items(): out = out * np.where(masks[lab], v, 1.0)
        return out
    cfg = {r["label"]: r["pooledBest"] for r in passing}
    cand = cand_pred(cfg) if passing else ref
    aff = np.zeros(n, dtype=bool)
    for lab in cfg: aff |= masks[lab]
    pc2, w2, ny2 = NW.pct_vs(cand, shipped, act, year); pv, wvv, _ = NW.pct_vs(cand, ref, act, year)
    pa, wa, _ = NW.pct_vs(cand[aff], ref[aff], act[aff], year[aff]) if aff.any() else (0.0, 0, ny2)
    P(f"  ALL rows: vs shipped {pc2:+.2f}% ({w2}/{ny2}) | vs shadow {pv:+.2f}% ({wvv}/{ny2}) | affected rows n={aff.sum()} {pa:+.2f}% ({wa}/{ny2})")
    RES["pieceForward"] = []; fm = year >= YEARS[2]
    for r in passing:
        fw = np.full(n, np.nan); mk_all = masks[r["label"]]
        for y in YEARS[2:]:
            mk = mk_all & (year < y)
            v = min(r["grid"], key=lambda v: mse(cand_pred({r["label"]: v})[mk], act[mk])) if mk.sum() >= 40 else r["grid"][0]
            fw = np.where(year == y, cand_pred({r["label"]: v}), fw)
        pa_, wa_, py_ = NW.pct_vs(fw[fm], ref[fm], act[fm], year[fm]); pm_, wm_, _ = NW.pct_vs(fw[fm & mk_all], ref[fm & mk_all], act[fm & mk_all], year[fm & mk_all])
        RES["pieceForward"].append({"label": r["label"].strip(), "allVsRef": round(pa_, 3), "allWins": int(wa_), "rowsVsRef": round(pm_, 3), "rowsWins": int(wm_), "years": py_})
        P(f"  FORWARD piece {r['label'].strip():34s}: all rows {pa_:+.2f}% ({wa_}/{py_}) | its rows {pm_:+.2f}% ({wm_}/{py_})")
    RES["candidate"] = {"cfg": cfg, "pct": round(pc2, 3), "wins": int(w2), "years": ny2, "vsRef": round(pv, 3), "vsRefWins": int(wvv), "affectedN": int(aff.sum()), "affectedVsRef": round(pa, 3), "affectedWins": int(wa)}
    RES["summary"] = ("Questionable / Doubtful on the shadow (extra multiplier on top of the live dock): " + "; ".join(f"{r['label'].strip()} {r['loyoPct']:+.2f}% ({r['wins']}/{r['years']}, {r['verdict']})" for r in RES["sweeps"] if not r["label"].startswith("  ")) +
                      (f". PASS pieces: " + ", ".join(f"{r['label'].strip()} = {r['pooledBest']}" for r in passing) if passing else ". No piece passes; the live docks stand for the shadow."))
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "qd_shadow_backtest.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_QD_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/qd_shadow_backtest.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
