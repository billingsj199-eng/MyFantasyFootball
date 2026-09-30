#!/usr/bin/env python3
"""
DEMOTED / PROMOTED VETERANS on the Clay-free shadow (2026-09-16).

Jack: "build the demoted veteran layer next." backtest_rookie_depth_live.py read veterans by pre-game depth
string: 2nd-string RB/WR/TE score .84-.88 of the shadow prior, 1st-string RBs 1.16x. A flat dock cut the
shadow's error on demoted rows (+4.3% -> +2.0% vs Clay) but was graded against Clay, not against the shadow it
improves. Here every layer is graded vs SHADOW v2.2 (own history + ADP market prior, rookie pick + string,
shrink .8, per-position P) - the number it would change - with the shipped Clay blend as context.

Veterans = non-rookies with a history prior and a pre-game chart string (nflverse depth charts 2019-25, the
ESPN charts sim_depth.js carries live). Layers act on the PRIOR (half-PPR), so season-to-date evidence still
overrides through the blend:
  DOCK      prior x m for string >= 2                                (m per position, LOYO)
  LEVEL     prior' = (1-w) prior + w L(pos, string), L = mean PPG of veterans at that string from the other
            seasons (weeks <= 8); w separately for demoted (string >= 2) and promoted (string 1) rows
  LEVEL-GAP as LEVEL but only when |prior - L| is large (> 3 half-PPR): "the chart disagrees with the history"
Log demoted_vets_backtest.log; results -> data/demoted_vets_backtest.js (SIM_DEMOTED_BT), ZONES tab.
"""
import json, os, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import backtest_rookie_prior as RP
import backtest_rookie_depth_live as RD
import bt_common as B
from backtest_target_area import mse

if __name__ == "__main__":   # importable (backtest_nochart_vets.py) without truncating this log
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "demoted_vets_backtest.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

YEARS, POS4, BANDS = NW.YEARS, NW.POS4, NW.BANDS
FIT_WK = 8
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "levels": {}, "reads": [], "sweeps": [], "candidate": {}}


def loyo_vs_ref(A, ref, shipped, grid, predfn, label, mask):
    """LOYO pick graded vs the shadow (ref); also reports vs shipped."""
    act, year = A["act"][mask], A["year"][mask]
    ys = [y for y in YEARS if (year == y).any()]
    per = {v: {y: mse(predfn(v)[mask][year == y], act[year == y]) for y in ys} for v in grid}
    tot = n = wins = 0; picks = []
    for y in ys:
        my = year == y
        best = min(grid, key=lambda v: sum(per[v][yy] for yy in ys if yy != y))
        picks.append(best); e = per[best][y]; tot += e * my.sum(); n += my.sum(); wins += e < mse(ref[mask][my], act[my])
    ref_mse, ship_mse = mse(ref[mask], act), mse(shipped[mask], act)
    pooled_best = min(grid, key=lambda v: sum(per[v].values()))
    P(f"  {label} (n={n})")
    P("    grid pooled MSE: " + "  ".join(f"{v}:{sum(per[v].values())/len(ys):.3f}" for v in grid))
    P(f"    LOYO {tot/n:.4f} vs shadow {ref_mse:.4f} ({(tot/n/ref_mse-1)*100:+.2f}%), seasons better than shadow {wins}/{len(ys)}, picks {picks}, pooled best {pooled_best} | shadow vs shipped {(ref_mse/ship_mse-1)*100:+.2f}% -> {(tot/n/ship_mse-1)*100:+.2f}%")
    row = {"label": label, "n": int(n), "grid": [float(v) for v in grid], "loyoPct": round((tot / n / ref_mse - 1) * 100, 3), "wins": int(wins), "years": len(ys),
           "picks": [float(p) for p in picks], "pooledBest": float(pooled_best), "shadowVsShip": round((ref_mse / ship_mse - 1) * 100, 3), "newVsShip": round((tot / n / ship_mse - 1) * 100, 3)}
    row["verdict"] = "PASS" if (row["loyoPct"] <= -0.3 and wins >= 5) else ("lean" if (row["loyoPct"] <= -0.1 and wins >= 4) else "FAIL")
    RES["sweeps"].append(row)
    return pooled_best


def main():
    t0 = time.time()
    P("=== Demoted / promoted veterans on the Clay-free shadow ===")
    S = NW.build_samples(); A = NW.arrays(S); n = len(S)
    act, year, wk, pos, g, ppg, clay, layers = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"]
    is_rookie, pid, team = A["rookie"], A["pid"], A["team"]
    shipped = NW.blend(clay, g, ppg, NW.PRIOR_P) * layers
    # depth string (same construction as backtest_rookie_depth_live)
    weekly, dated = RD.load_depth(); games25 = B.load_games(2025)
    string = np.full(n, np.nan)
    for i in range(n):
        if pid[i] is None: continue
        if year[i] <= 2024: s = weekly.get((year[i], pid[i], team[i], wk[i]))
        else:
            gm = games25.get((team[i], wk[i])); lst = dated.get((pid[i], team[i])); s = None
            if gm and lst:
                before = [x for x in lst if x[0] < gm["date"]]; s = before[-1][1] if before else None
        if s is not None: string[i] = s
    has = ~np.isnan(string); strb = np.where(has, np.minimum(string, 3), np.nan)
    # ---- shadow v2.2 prior (half-PPR) ----
    adp_map = RP.load_adp()
    adp = np.array([adp_map.get((y, NW.cal.norm(nm), ps), np.nan) for y, nm, ps in zip(year, A["name"], pos)])
    has_adp = ~np.isnan(adp); ladp = np.log(np.where(has_adp, adp, RP.ADP_CAP))
    lpick = np.log(np.where(np.isnan(A["pick"]), 262.0, A["pick"]))
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
    has_hist = ~np.isnan(base)
    # rookie fallback (pick + string, LOYO) and the position-mean fallback
    pos_mean = {ps: NW.loyo_const(A, lambda ps=ps: (pos == ps), YEARS) for ps in POS4}
    fb_pos = np.array([pos_mean[ps].get(y, np.nan) for ps, y in zip(pos, year)])
    fb = fb_pos.copy()
    for y in YEARS:
        for ps in POS4:
            tr = (year != y) & is_rookie & (pos == ps) & (wk <= FIT_WK); ap = (year == y) & is_rookie & (pos == ps)
            if tr.sum() < 40 or not ap.any(): continue
            def X(m):
                cols = [np.ones(m.sum()), lpick[m]]
                if ps in ("RB", "WR"):
                    cols += [np.where(has[m], (strb[m] == 2).astype(float), 0.0), np.where(has[m], (strb[m] >= 3).astype(float), 1.0)]
                return np.column_stack(cols)
            b = np.linalg.lstsq(X(tr), act[tr], rcond=None)[0]; fb[ap] = np.maximum(0.5, X(ap) @ b)
    prior0 = base.copy(); miss = np.isnan(prior0); prior0[miss] = fb[miss]
    PPOS = {"QB": 12, "RB": 5, "WR": 8, "TE": 8}; K = 0.8; Pvec = np.array([PPOS[ps] for ps in pos], dtype=float)
    def pred_of(prior):
        return NW.blend(fb_pos + K * (prior - fb_pos), g, ppg, Pvec) * layers
    ref = pred_of(prior0)
    pc, w, ny = NW.pct_vs(ref, shipped, act, year)
    P(f"  {n} player-weeks | shadow v2.2 vs shipped {pc:+.2f}% ({w}/{ny}) | veterans with history + chart: {int((~is_rookie & has_hist & has).sum())}")

    # ---- string levels L(pos, string) from the other seasons (vets, weeks <= 8) ----
    vet = ~is_rookie & has_hist & has
    L = np.full(n, np.nan)
    for y in YEARS:
        for ps in POS4:
            for sb in (1, 2, 3):
                tr = (year != y) & vet & (pos == ps) & (strb == sb) & (wk <= FIT_WK); ap = (year == y) & vet & (pos == ps) & (strb == sb)
                if tr.sum() >= 30 and ap.any(): L[ap] = act[tr].mean()
    RES["levels"] = {ps: {str(sb): round(float(act[vet & (pos == ps) & (strb == sb) & (wk <= FIT_WK)].mean()), 3) for sb in (1, 2, 3) if (vet & (pos == ps) & (strb == sb) & (wk <= FIT_WK)).sum() >= 30} for ps in POS4}
    P("  string levels (all seasons, half-PPR, vets weeks <= 8): " + json.dumps(RES["levels"]))
    P("\n=== Reads: actual / shadow prior (x shrink) by position x string, veterans, all weeks ===")
    shr0 = fb_pos + K * (prior0 - fb_pos)
    for ps in POS4:
        line = f"  {ps:4s}"
        for sb, lab in ((1, "1st"), (2, "2nd"), (3, "3rd+")):
            mm = vet & (pos == ps) & (strb == sb)
            if mm.sum() >= 30:
                gap = mm & ~np.isnan(L) & (np.abs(shr0 - L) > 3)
                line += f"  {lab}: n={mm.sum():4d} act/prior {act[mm].mean()/shr0[mm].mean():.2f} act/shipped {act[mm].mean()/shipped[mm].mean():.2f} (chart disagrees >3: n={gap.sum()} act/prior {act[gap].mean()/shr0[gap].mean() if gap.sum() else float('nan'):.2f}) |"
                RES["reads"].append({"pos": ps, "string": lab, "n": int(mm.sum()), "actOverPrior": round(float(act[mm].mean() / shr0[mm].mean()), 3), "actOverShipped": round(float(act[mm].mean() / shipped[mm].mean()), 3),
                                     "gapN": int(gap.sum()), "gapActOverPrior": round(float(act[gap].mean() / shr0[gap].mean()), 3) if gap.sum() else None})
        P(line)

    # ---- layers ----
    demoted = vet & (strb >= 2) & ~np.isnan(L); promoted = vet & (strb == 1) & ~np.isnan(L)
    P("\n=== DOCK: prior x m on demoted veterans (string >= 2), LOYO vs shadow ===")
    def dock(m_, mask):
        pr = prior0.copy(); pr[mask] *= m_; return pred_of(pr)
    loyo_vs_ref(A, ref, shipped, [1.0, 0.9, 0.8, 0.7, 0.6, 0.5], lambda m_: dock(m_, demoted), "dock, all demoted vets", demoted)
    for ps in ("RB", "WR", "TE"):
        loyo_vs_ref(A, ref, shipped, [1.0, 0.9, 0.8, 0.7, 0.6, 0.5], lambda m_, ps=ps: dock(m_, demoted & (pos == ps)), f"  dock, demoted {ps}", demoted & (pos == ps))
    P("\n=== LEVEL: prior' = (1-w) prior + w L(pos, string), LOYO vs shadow ===")
    def level(w_, mask):
        pr = prior0.copy(); pr[mask] = (1 - w_) * pr[mask] + w_ * L[mask]; return pred_of(pr)
    loyo_vs_ref(A, ref, shipped, [0.0, 0.25, 0.5, 0.75, 1.0], lambda w_: level(w_, demoted), "level, demoted (string >= 2)", demoted)
    for ps in ("RB", "WR", "TE"):
        loyo_vs_ref(A, ref, shipped, [0.0, 0.25, 0.5, 0.75, 1.0], lambda w_, ps=ps: level(w_, demoted & (pos == ps)), f"  level, demoted {ps}", demoted & (pos == ps))
    loyo_vs_ref(A, ref, shipped, [0.0, 0.25, 0.5, 0.75, 1.0], lambda w_: level(w_, promoted), "level, promoted (string 1)", promoted)
    for ps in POS4:
        loyo_vs_ref(A, ref, shipped, [0.0, 0.25, 0.5, 0.75, 1.0], lambda w_, ps=ps: level(w_, promoted & (pos == ps)), f"  level, string-1 {ps}", promoted & (pos == ps))
    P("\n=== LEVEL-GAP: only where the chart disagrees with the history by > 3 half-PPR ===")
    gapD = demoted & (np.abs(shr0 - L) > 3); gapP = promoted & (np.abs(shr0 - L) > 3)
    loyo_vs_ref(A, ref, shipped, [0.0, 0.25, 0.5, 0.75, 1.0], lambda w_: level(w_, gapD), "level-gap, demoted", gapD)
    loyo_vs_ref(A, ref, shipped, [0.0, 0.25, 0.5, 0.75, 1.0], lambda w_: level(w_, gapP), "level-gap, promoted", gapP)

    # ---- DOCK by string (2 vs 3+) per position ----
    P("\n=== DOCK by string: prior x m, string 2 and string 3+ separately, LOYO vs shadow ===")
    DOCK = {}
    for ps in ("RB", "WR", "TE"):
        DOCK[ps] = {}
        for sb, lab in ((2, "2nd"), (3, "3rd+")):
            mk = vet & (pos == ps) & (strb == sb)
            if mk.sum() < 60:
                P(f"  {ps} {lab}: n={mk.sum()} too few"); DOCK[ps][sb] = 1.0; continue
            DOCK[ps][sb] = float(loyo_vs_ref(A, ref, shipped, [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4], lambda m_, mk=mk: dock(m_, mk), f"  dock {ps} {lab}", mk))
    RES["dock"] = {ps: {str(k): v for k, v in d.items()} for ps, d in DOCK.items()}
    # ---- candidate v2.3: per-position, per-string docks on demoted veterans ----
    def cand_pred(D):
        pr = prior0.copy()
        for ps, d in D.items():
            for sb, m_ in d.items():
                mk = vet & (pos == ps) & (strb == sb); pr[mk] *= m_
        return pred_of(pr)
    cand = cand_pred(DOCK)
    pc, w, ny = NW.pct_vs(cand, shipped, act, year); pv, wvv, _ = NW.pct_vs(cand, ref, act, year)
    P(f"\n=== Candidate v2.3: demoted-vet docks {json.dumps(RES['dock'])} ===")
    P(f"  ALL rows: vs shipped {pc:+.2f}% ({w}/{ny}) | vs shadow v2.2 {pv:+.2f}% ({wvv}/{ny})")
    c = {"dock": RES["dock"], "pct": round(pc, 3), "wins": int(w), "years": ny, "vsRef": round(pv, 3), "vsRefWins": int(wvv), "byPos": {}, "bands": [], "segments": []}
    for ps in POS4:
        mm = pos == ps; c["byPos"][ps] = {"vsShip": round((mse(cand[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 2), "vsRef": round((mse(cand[mm], act[mm]) / mse(ref[mm], act[mm]) - 1) * 100, 2)}
    P("  by position (vs shipped | vs shadow): " + "  ".join(f"{ps} {c['byPos'][ps]['vsShip']:+.2f}% | {c['byPos'][ps]['vsRef']:+.2f}%" for ps in POS4))
    for lab, lo, hi in BANDS:
        mm = (wk >= lo) & (wk <= hi)
        row = {"band": lab, "n": int(mm.sum()), "vsShip": round((mse(cand[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 3), "refVsShip": round((mse(ref[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 3)}
        c["bands"].append(row); P(f"  {lab:7s} shadow {row['refVsShip']:+6.2f}% -> {row['vsShip']:+6.2f}% vs shipped")
    for lab, mm in (("demoted vets", demoted), ("string-1 vets", promoted), ("vets without a chart", ~is_rookie & has_hist & ~has), ("rookies", is_rookie)):
        row = {"seg": lab, "n": int(mm.sum()), "vsShip": round((mse(cand[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 3), "refVsShip": round((mse(ref[mm], act[mm]) / mse(shipped[mm], act[mm]) - 1) * 100, 3)}
        c["segments"].append(row); P(f"  {lab:26s} n={mm.sum():5d} shadow {row['refVsShip']:+6.2f}% -> {row['vsShip']:+6.2f}% vs shipped")
    # forward: docks re-picked on earlier seasons only (per position x string, same grid)
    fwd = np.full(n, np.nan)
    for y in YEARS[2:]:
        Dy = {}
        for ps in ("RB", "WR", "TE"):
            Dy[ps] = {}
            for sb in (2, 3):
                mk = vet & (pos == ps) & (strb == sb) & (year < y)
                if mk.sum() < 60: Dy[ps][sb] = 1.0; continue
                Dy[ps][sb] = min([1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4], key=lambda m_: mse(dock(m_, vet & (pos == ps) & (strb == sb))[mk], act[mk]))
        fwd = np.where(year == y, cand_pred(Dy), fwd)
    fm = year >= YEARS[2]
    fp, fw, fy = NW.pct_vs(fwd[fm], shipped[fm], act[fm], year[fm]); fr, frw, _ = NW.pct_vs(fwd[fm], ref[fm], act[fm], year[fm])
    dm = fm & demoted
    P(f"  FORWARD (2021-25, docks picked on earlier seasons): vs shipped {fp:+.2f}% ({fw}/{fy}) | vs shadow {fr:+.2f}% ({frw}/{fy}) | demoted rows vs shadow {(mse(fwd[dm], act[dm]) / mse(ref[dm], act[dm]) - 1) * 100:+.2f}%")
    c["forward"] = {"pct": round(fp, 3), "wins": int(fw), "years": fy, "vsRef": round(fr, 3), "vsRefWins": int(frw), "demotedVsRef": round((mse(fwd[dm], act[dm]) / mse(ref[dm], act[dm]) - 1) * 100, 3)}
    RES["candidate"] = c
    dd = [r for r in RES['sweeps'] if r['label'] == 'dock, all demoted vets'][0]
    RES["summary"] = (f"Demoted vets (string >= 2): flat dock {dd['loyoPct']:+.2f}% vs shadow ({dd['wins']}/{dd['years']}), level blend weaker, promotion side nothing. "
                      f"Candidate v2.3 (per-position, per-string docks): {pv:+.2f}% vs shadow v2.2 ({wvv}/{ny}), {pc:+.2f}% vs shipped, forward {fr:+.2f}% vs shadow ({frw}/{fy}), demoted rows forward {c['forward']['demotedVsRef']:+.2f}%.")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "demoted_vets_backtest.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_DEMOTED_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/demoted_vets_backtest.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
