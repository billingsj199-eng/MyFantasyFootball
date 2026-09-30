#!/usr/bin/env python3
"""
SECOND-YEAR ROLE GROWTH on the Clay-free shadow (2026-09-16).

Jack: "build the second-year role growth layer next." Second-year players (exp 1) run +0.4% vs the shipped
Clay blend on shadow v2.5 (-1.2% overall). Their prior is the rookie season (3-yr history = that one season,
last-8 = its back half) blended .5 with the ADP market curve. "Role growth" needs a signal, so four are tested
on the 2nd-year rows, each LOYO vs shadow v2.5:
  LEVEL     prior x m for every 2nd-year player                       (the age curve already carries youth)
  RECENCY   weight of the rookie season's last 8 games in the history mix (v2.5 = .5) - the back half is the role
  PROMOTION last season's late modal depth string (weeks 10+, nflverse charts) vs this week's string:
            promoted (2+ -> 1) x m, steady starter (1 -> 1) x m, still buried (2+ -> 2+) x m
  SNAPS     rookie season's late snap share (last 4 games, nflverse snap counts) and its trend vs the season:
            actual / shadow by tercile, then a multiplier on the rising / high-snap tercile
Candidate = the passing pieces, graded on all rows and forward (2021-25, constants from earlier seasons).
Log second_year_backtest.log; results -> data/second_year_backtest.js (SIM_YR2_BT), ZONES tab.
"""
import json, os, sys, time
from collections import defaultdict, Counter
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

if __name__ == "__main__":   # importable (backtest_te_layer.py) without truncating this log
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "second_year_backtest.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

YEARS, POS4, BANDS = NW.YEARS, NW.POS4, NW.BANDS
FIT_WK = 8
RAMP = [0.7, 0.8]
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "reads": [], "sweeps": [], "candidate": {}}


def load_last_strings():
    """(Y-1, gsis) -> modal string over weeks 10+ of that season (any team), NFL-format charts 2018-24."""
    out = {}
    for Y in range(2018, 2025):
        d = pd.read_parquet(os.path.join(B.CACHE, f"depth_charts_{Y}.parquet"))
        d = d[(d.game_type == "REG") & d.position.isin(POS4) & (d.depth_position == d.position) & d.gsis_id.notna() & (d.week >= 10)]
        best = {}
        for r in d.itertuples(index=False):
            try: s = int(r.depth_team)
            except Exception: continue
            k = (Y, r.gsis_id, int(r.week)); best[k] = min(best.get(k, 99), s)
        by = defaultdict(list)
        for (yy, gid, w), s in best.items(): by[(yy, gid)].append(s)
        for k, lst in by.items(): out[k] = Counter(lst).most_common(1)[0][0]
    return out


def load_snaps():
    """(Y, gsis) -> {late: mean offense_pct last 4 games, season: mean, trend: late - season, g: games} for 2018-24."""
    pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "pfr_id"])
    g2p = {r.pfr_id: r.gsis_id for r in pl.itertuples(index=False) if isinstance(r.pfr_id, str) and isinstance(r.gsis_id, str)}
    out = {}
    for Y in range(2018, 2025):
        d = pd.read_parquet(os.path.join(B.CACHE, f"snap_counts_{Y}.parquet"))
        d = d[(d.game_type == "REG") & d.position.isin(POS4) & (d.offense_snaps > 0)]
        for pid_, grp in d.groupby("pfr_player_id"):
            gid = g2p.get(pid_)
            if not gid: continue
            pct = grp.sort_values("week").offense_pct.values.astype(float)
            if len(pct) < 4: continue
            out[(Y, gid)] = {"late": float(pct[-4:].mean()), "season": float(pct.mean()), "trend": float(pct[-4:].mean() - pct.mean()), "g": int(len(pct))}
    return out


def main():
    t0 = time.time()
    P("=== Second-year role growth on the Clay-free shadow ===")
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
    # ---- v2.5 prior pieces ----
    adp_map = RP.load_adp()
    adp = np.array([adp_map.get((y, NW.cal.norm(nm), ps), np.nan) for y, nm, ps in zip(year, A["name"], pos)])
    has_adp = ~np.isnan(adp); ladp = np.log(np.where(has_adp, adp, RP.ADP_CAP)); lpick = np.log(np.where(np.isnan(A["pick"]), 262.0, A["pick"]))
    h3, l8 = A["h3"], A["l8"]; has_h3, has_l8 = ~np.isnan(h3), ~np.isnan(l8)
    yr2 = A["exp"] == 1
    def hist_mix(w_l8_yr2):
        w = np.where(yr2, w_l8_yr2, 0.5)
        hist = np.full(n, np.nan); both = has_h3 & has_l8
        hist[both] = (1 - w[both]) * h3[both] + w[both] * l8[both]; hist[has_h3 & ~has_l8] = h3[has_h3 & ~has_l8]; hist[~has_h3 & has_l8] = l8[~has_h3 & has_l8]
        for i in np.where(~np.isnan(hist))[0]: hist[i] = NW.age_adjust(pos[i], hist[i], A["age"][i])
        oppcal = A["oppcal"]; vet_opp = (~np.isnan(oppcal)) & (A["seg"] != "rookie") & (~is_rookie) & ~np.isnan(hist) & (hist >= 4); hist[vet_opp] = oppcal[vet_opp]
        return hist
    hist0 = hist_mix(0.5); has_hist = ~np.isnan(hist0)
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
    PPOS = {"QB": 12, "RB": 5, "WR": 8, "TE": 8}; Pvec = np.array([PPOS[ps] for ps in pos], dtype=float)
    def build(hist=None, w_yr2=0.5, mult=None):
        hist = hist0 if hist is None else hist
        wv = np.where(yr2, w_yr2, 0.75)
        pr = np.where(mkt_ok, (1 - wv) * hist + wv * adp_curve, hist)
        miss = np.isnan(pr); pr[miss] = fb[miss]
        for ps, d in NC.VETDOCK.items():
            for sb, mm_ in d.items():
                mk = vet & (pos == ps) & (strb == sb); pr[mk] *= mm_
        if mult is not None: pr = pr * mult
        pr = fb_pos + 0.8 * (pr - fb_pos)
        out = NW.blend(pr, g, ppg, Pvec) * layers
        for gi, m_ in enumerate(RAMP, start=1): out = np.where(buried_rk & (wk == gi), out * m_, out)
        return out
    ref = build()
    pc, w, ny = NW.pct_vs(ref, shipped, act, year)
    y2 = yr2 & has_hist
    P(f"  {n} player-weeks | shadow v2.5 vs shipped {pc:+.2f}% ({w}/{ny}) | 2nd-year rows with a history prior: {y2.sum()} ({(mse(ref[y2], act[y2]) / mse(shipped[y2], act[y2]) - 1) * 100:+.2f}% vs shipped)")

    # ---- features ----
    last_str = load_last_strings(); snaps = load_snaps()
    ls = np.array([last_str.get((year[i] - 1, pid[i]), np.nan) if pid[i] else np.nan for i in range(n)], dtype=float)
    sn = [snaps.get((year[i] - 1, pid[i])) if pid[i] else None for i in range(n)]
    late = np.array([s["late"] if s else np.nan for s in sn]); trend = np.array([s["trend"] if s else np.nan for s in sn])
    has_ls, has_sn = ~np.isnan(ls), ~np.isnan(late)
    P(f"  2nd-year rows with last-season string {int((y2 & has_ls).sum())}, with rookie-season snaps {int((y2 & has_sn).sum())}")
    promoted = y2 & has_ls & (ls >= 2) & (strb == 1); steady = y2 & has_ls & (ls == 1) & (strb == 1); still = y2 & has_ls & (ls >= 2) & (strb >= 2); demoted = y2 & has_ls & (ls == 1) & (strb >= 2)
    P("\n=== Reads on 2nd-year rows (actual / shadow, actual / shipped, shadow vs shipped) ===")
    def read(lab, mm):
        if mm.sum() < 20: P(f"  {lab:40s} n={mm.sum()} too few"); return
        row = {"label": lab, "n": int(mm.sum()), "actOverShadow": round(float(act[mm].mean() / ref[mm].mean()), 3), "actOverShipped": round(float(act[mm].mean() / shipped[mm].mean()), 3), "vsShip": round((mse(ref[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 2)}
        RES["reads"].append(row); P(f"  {lab:40s} n={mm.sum():5d} act/shadow {row['actOverShadow']:.3f} act/shipped {row['actOverShipped']:.3f} shadow vs shipped {row['vsShip']:+6.2f}%")
    read("2nd-year, all", y2)
    for ps in POS4: read(f"  {ps}", y2 & (pos == ps))
    for lab, lo, hi in BANDS: read(f"  {lab}", y2 & (wk >= lo) & (wk <= hi))
    read("  promoted (late string 2+ -> now 1)", promoted); read("  steady starter (1 -> 1)", steady); read("  still buried (2+ -> 2+)", still); read("  demoted (1 -> 2+)", demoted)
    q = np.nanpercentile(trend[y2 & has_sn], [33.3, 66.7]) if (y2 & has_sn).sum() > 30 else [0, 0]
    read(f"  rookie-yr snap trend low (< {q[0]:+.2f})", y2 & has_sn & (trend < q[0])); read("  snap trend mid", y2 & has_sn & (trend >= q[0]) & (trend <= q[1])); read(f"  snap trend high (> {q[1]:+.2f})", y2 & has_sn & (trend > q[1]))
    read("  rookie-yr late snaps < 40%", y2 & has_sn & (late < 0.4)); read("  late snaps 40-70%", y2 & has_sn & (late >= 0.4) & (late < 0.7)); read("  late snaps 70%+", y2 & has_sn & (late >= 0.7))
    read("  l8 / h3 ratio > 1.15 (back half up)", y2 & has_h3 & has_l8 & (l8 / np.maximum(0.5, h3) > 1.15)); read("  l8 / h3 ratio < .85", y2 & has_h3 & has_l8 & (l8 / np.maximum(0.5, h3) < 0.85))

    # ---- sweeps ----
    P("\n=== Sweeps on 2nd-year rows (LOYO vs shadow v2.5) ===")
    DV.RES["sweeps"] = []
    def mult_on(mask, m_): v = np.ones(n); v[mask] = m_; return v
    DV.loyo_vs_ref(A, ref, shipped, [1.0, 0.95, 0.9, 1.05, 1.1, 1.15], lambda m_: build(mult=mult_on(y2, m_)), "LEVEL 2nd-year x m", y2)
    DV.loyo_vs_ref(A, ref, shipped, [0.5, 0.25, 0.75, 1.0], lambda w_: build(hist=hist_mix(w_)), "RECENCY: rookie-season last-8 weight", y2 & has_h3 & has_l8)
    DV.loyo_vs_ref(A, ref, shipped, [0.5, 0.25, 0.75, 1.0], lambda w_: build(w_yr2=w_), "  2nd-year ADP weight (re-check)", y2 & mkt_ok)
    for lab, mk in (("PROMOTION: promoted x m", promoted), ("  steady starter x m", steady), ("  still buried x m", still)):
        if mk.sum() >= 40: DV.loyo_vs_ref(A, ref, shipped, [1.0, 1.1, 1.2, 1.3, 0.9, 0.8], lambda m_, mk=mk: build(mult=mult_on(mk, m_)), lab, mk)
    hi_t = y2 & has_sn & (trend > q[1]); lo_t = y2 & has_sn & (trend < q[0]); hi_l = y2 & has_sn & (late >= 0.7); lo_l = y2 & has_sn & (late < 0.4)
    for lab, mk in (("SNAPS: rising trend tercile x m", hi_t), ("  falling trend tercile x m", lo_t), ("  late snaps 70%+ x m", hi_l), ("  late snaps < 40% x m", lo_l)):
        if mk.sum() >= 40: DV.loyo_vs_ref(A, ref, shipped, [1.0, 1.1, 1.2, 0.9, 0.8], lambda m_, mk=mk: build(mult=mult_on(mk, m_)), lab, mk)
    RES["sweeps"] = DV.RES["sweeps"]

    # ---- candidate: every PASS/lean piece at its pooled best, graded everywhere + forward ----
    pieces = [r for r in RES["sweeps"] if r["verdict"] in ("PASS", "lean")]
    P("\n=== Candidate from the passing pieces: " + (", ".join(f"{r['label'].strip()} = {r['pooledBest']}" for r in pieces) if pieces else "NONE") + " ===")
    masks = {"LEVEL 2nd-year x m": y2, "PROMOTION: promoted x m": promoted, "  steady starter x m": steady, "  still buried x m": still, "SNAPS: rising trend tercile x m": hi_t, "  falling trend tercile x m": lo_t, "  late snaps 70%+ x m": hi_l, "  late snaps < 40% x m": lo_l}
    def cand_pred(cfg):
        hist = hist_mix(cfg.get("RECENCY: rookie-season last-8 weight", 0.5)); mult = np.ones(n)
        for lab, m_ in cfg.items():
            if lab in masks: mult[masks[lab]] *= m_
        return build(hist=hist, w_yr2=cfg.get("  2nd-year ADP weight (re-check)", 0.5), mult=mult)
    cfg = {r["label"]: r["pooledBest"] for r in pieces}
    cand = cand_pred(cfg)
    pc2, w2, ny2 = NW.pct_vs(cand, shipped, act, year); pv, wvv, _ = NW.pct_vs(cand, ref, act, year); py, wy, _ = NW.pct_vs(cand[y2], ref[y2], act[y2], year[y2])
    P(f"  ALL rows: vs shipped {pc2:+.2f}% ({w2}/{ny2}) | vs shadow v2.5 {pv:+.2f}% ({wvv}/{ny2}) | 2nd-year rows {py:+.2f}% vs shadow ({wy}/{ny2}), vs shipped {(mse(cand[y2], act[y2]) / mse(shipped[y2], act[y2]) - 1) * 100:+.2f}% (was {(mse(ref[y2], act[y2]) / mse(shipped[y2], act[y2]) - 1) * 100:+.2f}%)")
    fwd = np.full(n, np.nan)
    for y in YEARS[2:]:
        cfg_y = {}
        for r in pieces:
            mk = (y2 if r["label"].startswith("RECENCY") or r["label"].startswith("  2nd-year ADP") else masks[r["label"]]) & (year < y)
            if mk.sum() < 30: cfg_y[r["label"]] = r["grid"][0]; continue
            cfg_y[r["label"]] = min(r["grid"], key=lambda v: mse(cand_pred({r["label"]: v})[mk], act[mk]))
        fwd = np.where(year == y, cand_pred(cfg_y), fwd)
    fm = year >= YEARS[2]; f2 = fm & y2
    fr, frw, fy = NW.pct_vs(fwd[fm], ref[fm], act[fm], year[fm]); f2r, f2w, _ = NW.pct_vs(fwd[f2], ref[f2], act[f2], year[f2])
    P(f"  FORWARD (2021-25, pieces picked on earlier seasons): all rows {fr:+.2f}% vs shadow ({frw}/{fy}) | 2nd-year rows {f2r:+.2f}% ({f2w}/{fy})")
    RES["candidate"] = {"cfg": cfg, "pct": round(pc2, 3), "wins": int(w2), "years": ny2, "vsRef": round(pv, 3), "vsRefWins": int(wvv), "yr2VsRef": round(py, 3), "yr2Wins": int(wy),
                        "yr2VsShip": round((mse(cand[y2], act[y2]) / mse(shipped[y2], act[y2]) - 1) * 100, 3), "yr2RefVsShip": round((mse(ref[y2], act[y2]) / mse(shipped[y2], act[y2]) - 1) * 100, 3),
                        "forward": {"vsRef": round(fr, 3), "vsRefWins": int(frw), "years": fy, "yr2VsRef": round(f2r, 3), "yr2Wins": int(f2w)}}
    # per-piece forward (each passing piece alone, re-picked on earlier seasons)
    RES["pieceForward"] = []
    for r in pieces:
        fw = np.full(n, np.nan)
        for y in YEARS[2:]:
            mk = (y2 if r["label"].startswith("RECENCY") or r["label"].startswith("  2nd-year ADP") else masks[r["label"]]) & (year < y)
            v = min(r["grid"], key=lambda v: mse(cand_pred({r["label"]: v})[mk], act[mk])) if mk.sum() >= 30 else r["grid"][0]
            fw = np.where(year == y, cand_pred({r["label"]: v}), fw)
        pr_, pw_, py_ = NW.pct_vs(fw[fm], ref[fm], act[fm], year[fm]); p2_, w2_, _ = NW.pct_vs(fw[f2], ref[f2], act[f2], year[f2])
        mk_all = (y2 if r["label"].startswith("RECENCY") or r["label"].startswith("  2nd-year ADP") else masks[r["label"]]); fmk = fm & mk_all
        pm_, wm_, _ = NW.pct_vs(fw[fmk], ref[fmk], act[fmk], year[fmk])
        RES["pieceForward"].append({"label": r["label"].strip(), "allVsRef": round(pr_, 3), "allWins": int(pw_), "yr2VsRef": round(p2_, 3), "yr2Wins": int(w2_), "rowsVsRef": round(pm_, 3), "rowsWins": int(wm_), "years": py_})
        P(f"  FORWARD piece {r['label'].strip():36s}: all rows {pr_:+.2f}% ({pw_}/{py_}) | 2nd-year rows {p2_:+.2f}% ({w2_}/{py_}) | its own rows {pm_:+.2f}% ({wm_}/{py_})")
    RES["summary"] = (f"2nd-year rows (n {y2.sum()}) shadow {RES['candidate']['yr2RefVsShip']:+.2f}% vs shipped. " + "; ".join(f"{r['label'].strip()} {r['loyoPct']:+.2f}% ({r['wins']}/{r['years']}, {r['verdict']})" for r in RES["sweeps"]) +
                      f". Candidate: 2nd-year rows {py:+.2f}% vs v2.5 ({wy}/{ny2}), forward {f2r:+.2f}% ({f2w}/{fy}).")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "second_year_backtest.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_YR2_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/second_year_backtest.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
