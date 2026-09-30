#!/usr/bin/env python3
"""
QB COMPRESSION IN THE SHADOW (2026-09-17). Jack: "lets fix the QB compression in the shadow."

Week-2 read: the shadow sits ~2 pts above Clay on the mid-tier passers (Mayfield, Stroud, Goff, Dak, Kyler) and 2.6
below on Josh Allen; season-long the top-60 QB slope of actual on our prior was .46 (Clay 1.10). A veteran QB's shadow
prior passes through four squeezes: (1) 75% weight on a log-ADP market curve (QBs are drafted late, so the curve is
flat where the elite separate), (2) the 0.8 shrink toward the position mean, (3) the 50% ridge half, (4) prior
strength P = 12 (the prior dominates the season-to-date PPG for longer than at any other position).
Each is swept for QBs ONLY on the weekly harness (vet QBs with ADP + history; other QB rows untouched), one at a
time, then the LOYO-selected combination, then forward 2021-25. Graded on QB rows: plain and importance-weighted,
elite (ADP <= 60) vs the rest, by stage, vs the current shadow and vs the corrected (per-game) Clay blend.
Log qb_compression.log; results -> data/qb_compression.js (SIM_QBCOMP_BT).
"""
import json, os, sys, time, warnings
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import research_clay_vs_shadow as CS
import backtest_season_long as SL
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "qb_compression.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
YEARS = NW.YEARS
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "diag": [], "sweeps": [], "final": [], "forward": []}


def main():
    t0 = time.time()
    P("=== QB compression in the shadow: ADP-curve weight, shrink k, ridge mix, prior strength (QBs only) ===")
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, clay, layers, adp = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"], F["adp"]
    ch = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, A["name"])], dtype=float)
    W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay)
    ship = NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers
    T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]
    def ridge_rows(fwd):
        lo = (SL.forward if fwd else SL.loyo)(T, LIVE, "ridge", 10.0); key = {(int(y), nm, ps): v for y, nm, ps, v in zip(T.year, T.name, T.pos, lo)}
        return np.array([key.get((year[i], A["name"][i], pos[i]), np.nan) for i in range(n)])
    R = {False: ridge_rows(False), True: ridge_rows(True)}
    qb = pos == "QB"; fb_pos, hand0, Pvec0 = F["fb_pos"], F["prior"], F["Pvec"]
    hist_adj = np.array([NW.age_adjust(pos[i], F["hist"][i], A["age"][i]) if not np.isnan(F["hist"][i]) else np.nan for i in range(n)])
    tun = qb & F["mkt_ok"] & ~np.isnan(hist_adj) & ~np.isnan(F["adp_curve"])          # vet QBs with ADP + history: the rows we re-tune
    wv0 = np.where(A["exp"] == 1, 0.5, 0.75); pr_final0 = fb_pos + (hand0 - fb_pos) / 0.8
    base0 = (1 - wv0) * hist_adj + wv0 * F["adp_curve"]; mult = np.where(tun & (base0 > 0), pr_final0 / base0, 1.0)   # docks / 2nd-year boost carried over
    # alternative market curve: log of the QB's ADP RANK among QBs that season (LOYO fit)
    qrank = np.full(n, np.nan)
    for y in YEARS:
        m = qb & (year == y) & ~np.isnan(adp); names = {}
        for i in np.where(m)[0]: names[A["name"][i]] = adp[i]
        order = {nm: k + 1 for k, (nm, _) in enumerate(sorted(names.items(), key=lambda kv: kv[1]))}
        for i in np.where(m)[0]: qrank[i] = order[A["name"][i]]
    rank_curve = np.full(n, np.nan)
    for y in YEARS:
        tr = qb & (year != y) & ~np.isnan(qrank) & (wk <= 4); ap = qb & (year == y) & ~np.isnan(qrank)
        if tr.sum() >= 60 and ap.any():
            X = np.column_stack([np.ones(tr.sum()), np.log(qrank[tr])]); b = np.linalg.lstsq(X, act[tr], rcond=None)[0]; rank_curve[ap] = np.maximum(0.5, b[0] + b[1] * np.log(qrank[ap]))
    def shadow(w=None, k=0.8, a=0.5, pk=1.0, curve="adp", fwd=False):
        cv = F["adp_curve"] if curve == "adp" else np.where(np.isnan(rank_curve), F["adp_curve"], rank_curve)
        ww = wv0 if w is None else np.where(A["exp"] == 1, min(w, 0.5), w)
        pr = mult * ((1 - ww) * hist_adj + ww * cv); hand = np.where(tun, fb_pos + k * (pr - fb_pos), hand0)
        r = R[fwd]; aa = np.where(qb, a, 0.5); prior = np.where(np.isnan(r), hand, aa * r + (1 - aa) * hand)
        Pv = np.where(qb, Pvec0 * pk, Pvec0); out = NW.blend(prior, g, ppg, Pv) * layers
        for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
        return np.where(F["on"], out * np.power(F["pm"], 0.75), out)
    lv = F["adp_curve"].copy(); lv[qb & np.isnan(lv)] = np.nanmin(lv[qb]); t150 = qb & (adp <= 150); lvq = lv / lv[t150].mean(); wt = np.maximum(0.05, lvq) ** 2
    def wm(p, m, weighted=True): return float(np.average((p[m] - act[m]) ** 2, weights=wt[m] if weighted else None))
    CUTS = (("all QB", qb), ("QB top 150 (weighted)", t150), ("elite QB, ADP <= 60", qb & (adp <= 60)), ("QB ADP 61-150", qb & (adp > 60) & (adp <= 150)), ("QB week 1", t150 & (g == 0)), ("QB games 1-3", t150 & (g >= 1) & (g <= 3)), ("QB games 4+", t150 & (g >= 4)))
    def grade(label, pred, base, store, fm=None, quiet=False):
        cells = []
        for lab, m in CUTS:
            mm = m & (fm if fm is not None else True); ys = sorted(set(year[mm])); wtd = lab != "all QB"
            wb = sum(1 for y in ys if wm(pred, mm & (year == y), wtd) < wm(base, mm & (year == y), wtd)); wc = sum(1 for y in ys if wm(pred, mm & (year == y), wtd) < wm(ship, mm & (year == y), wtd))
            row = {"label": label, "cut": lab, "n": int(mm.sum()), "vsShadow": round((wm(pred, mm, wtd) / wm(base, mm, wtd) - 1) * 100, 2), "shadowWins": wb, "vsClay": round((wm(pred, mm, wtd) / wm(ship, mm, wtd) - 1) * 100, 2), "clayWins": wc, "years": len(ys)}
            store.append(row); cells.append(f"{lab}: {row['vsShadow']:+.2f}% ({wb}/{len(ys)}) | Clay {row['vsClay']:+.2f}% ({wc}/{len(ys)})")
        if not quiet: P(f"  {label:34s} " + "  ||  ".join(cells[:4]))
        return store[-len(CUTS):]
    cur = shadow()
    P(f"  {int(qb.sum())} QB player-weeks, {int(tun.sum())} re-tunable (vet, ADP + history) | rebuilt current shadow vs harness+ridge form: QB rows only differ by construction")
    # --- diagnostics: dispersion of the current shadow on QBs ---
    P("\n=== Diagnostics: slope of actual on prediction (1.0 = right spread; > 1 = compressed) and level by ADP tier, QB rows ===")
    for lab, m in (("elite ADP <= 60", qb & (adp <= 60)), ("ADP 61-100", qb & (adp > 60) & (adp <= 100)), ("ADP 101-150", qb & (adp > 100) & (adp <= 150)), ("ADP 151+ / none", qb & ~(adp <= 150))):
        if m.sum() < 50: continue
        d = {"cut": lab, "n": int(m.sum()), "act": round(float(act[m].mean()), 2), "shadow": round(float(cur[m].mean()), 2), "clay": round(float(ship[m].mean()), 2)}
        RES["diag"].append(d); P(f"  {lab:18s} n={m.sum():4d} | actual {d['act']:5.2f} | shadow {d['shadow']:5.2f} | Clay blend {d['clay']:5.2f}")
    for lab, p in (("shadow", cur), ("Clay blend", ship)):
        m = t150; P(f"  slope act~{lab} on top-150 QBs: {np.polyfit(p[m], act[m], 1)[0]:.2f} | sd of prediction {p[m].std():.2f} (actual player-mean sd is what matters: see tiers)")
    # --- one-at-a-time sweeps ---
    P("\n=== One-at-a-time sweeps (QB rows; cell = vs current shadow (seasons) | vs Clay (seasons)) ===")
    for w in (0.75, 0.5, 0.25, 0.0): grade(f"ADP-curve weight w={w}", shadow(w=w), cur, RES["sweeps"])
    for w in (0.75, 0.5, 0.25): grade(f"QB-rank curve, w={w}", shadow(w=w, curve="rank"), cur, RES["sweeps"])
    for k in (0.8, 0.9, 1.0, 1.1): grade(f"shrink k={k}", shadow(k=k), cur, RES["sweeps"])
    for a in (0.5, 0.25, 0.0): grade(f"ridge mix a={a}", shadow(a=a), cur, RES["sweeps"])
    for pk in (1.0, 0.75, 0.5, 1.5): grade(f"prior strength P x {pk} (12 -> {12*pk:g})", shadow(pk=pk), cur, RES["sweeps"])
    # --- LOYO-selected combination on the weighted top-150 QB metric ---
    P("\n=== LOYO-selected combination (grid w x k x a x P, chosen on the other six seasons, top-150 QB weighted MSE) ===")
    GRID = [(w, k, a, pk) for w in (0.75, 0.5, 0.25, 0.0) for k in (0.8, 0.9, 1.0) for a in (0.5, 0.25, 0.0) for pk in (1.0, 0.75, 0.5)]
    preds = {c: shadow(w=c[0], k=c[1], a=c[2], pk=c[3]) for c in GRID}
    combo = cur.copy(); picks = []
    for y in YEARS:
        tr = t150 & (year != y); best = min(GRID, key=lambda c: wm(preds[c], tr)); picks.append(best); te = qb & (year == y); combo[te] = preds[best][te]
    pooled = min(GRID, key=lambda c: wm(preds[c], t150)); P(f"  picks by held-out season (w, k, a, Pmult): {picks} | pooled best {pooled}")
    grade("LOYO-selected combo", combo, cur, RES["final"]); grade(f"pooled best {pooled}", preds[pooled], cur, RES["final"])
    # --- forward: constants chosen on earlier seasons only, ridge forward ---
    P("\n=== Forward 2021-25 (ridge fit and constants chosen on earlier seasons only) ===")
    fm = year >= YEARS[2]; curf = shadow(fwd=True); predsf = {c: shadow(w=c[0], k=c[1], a=c[2], pk=c[3], fwd=True) for c in GRID}
    combof = curf.copy(); picksf = []
    for y in YEARS[2:]:
        tr = t150 & (year < y); best = min(GRID, key=lambda c: wm(preds[c], tr)); picksf.append(best); te = qb & (year == y); combof[te] = predsf[best][te]
    P(f"  forward picks: {picksf}")
    grade("forward selected combo", combof, curf, RES["forward"], fm); grade(f"forward pooled best {pooled}", predsf[pooled], curf, RES["forward"], fm)
    for lab, c in (("forward ridge a=0 only", (0.75, 0.8, 0.0, 1.0)), ("forward ridge a=0.25 only", (0.75, 0.8, 0.25, 1.0)), ("forward ADP w=0.5 only", (0.5, 0.8, 0.5, 1.0)), ("forward a=0 + w=0.5", (0.5, 0.8, 0.0, 1.0)), ("forward a=0.25 + w=0.5", (0.5, 0.8, 0.25, 1.0))):
        grade(lab, predsf[c], curf, RES["forward"], fm)
    P("=== Per-season, top-150 QBs weighted, vs the current shadow (LOYO ridge): a=0 only | a=0 + w=0.5 ===")
    for y in YEARS:
        m = t150 & (year == y); P(f"  {y}: a=0 only {(wm(preds[(0.75, 0.8, 0.0, 1.0)], m)/wm(cur, m)-1)*100:+.2f}% | a=0 + w=.5 {(wm(preds[(0.5, 0.8, 0.0, 1.0)], m)/wm(cur, m)-1)*100:+.2f}% | a=.25 + w=.5 {(wm(preds[(0.5, 0.8, 0.25, 1.0)], m)/wm(cur, m)-1)*100:+.2f}%  (n={int(m.sum())})")
    grade("a=0.25 + w=0.5 (LOYO ridge)", preds[(0.5, 0.8, 0.25, 1.0)], cur, RES["final"]); grade("a=0 only (LOYO ridge)", preds[(0.75, 0.8, 0.0, 1.0)], cur, RES["final"])
    RES["pooled"] = {"w": pooled[0], "k": pooled[1], "a": pooled[2], "pk": pooled[3]}; RES["picks"] = [list(c) for c in picks]
    f150 = [r for r in RES["final"] if r["cut"] == "QB top 150 (weighted)"]; ff = [r for r in RES["forward"] if r["cut"] == "QB top 150 (weighted)"]
    RES["summary"] = (f"Top-150 QBs (weighted): LOYO-selected combo {f150[0]['vsShadow']:+.2f}% vs the current shadow ({f150[0]['shadowWins']}/{f150[0]['years']}), {f150[0]['vsClay']:+.2f}% vs Clay ({f150[0]['clayWins']}/{f150[0]['years']}); "
                      f"pooled best (w {pooled[0]}, k {pooled[1]}, ridge {pooled[2]}, P x {pooled[3]}) {f150[1]['vsShadow']:+.2f}% / {f150[1]['vsClay']:+.2f}% vs Clay. Forward: selected {ff[0]['vsShadow']:+.2f}% ({ff[0]['shadowWins']}/{ff[0]['years']}), pooled {ff[1]['vsShadow']:+.2f}% ({ff[1]['shadowWins']}/{ff[1]['years']}), vs Clay {ff[1]['vsClay']:+.2f}%.")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "qb_compression.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_QBCOMP_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/qb_compression.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
