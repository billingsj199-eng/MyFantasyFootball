#!/usr/bin/env python3
"""
BEAT CLAY WHERE HE STILL WINS (2026-09-16).

Jack: "do we have any way to improve ours to beat clay?" The segmentation (research_clay_vs_shadow.py) left Clay two
repeatable edges: week 1 (no season data; n1407, +0.33%, shadow wins 2/7) and players with no depth-chart entry
(n840, +2.65%, 3/7), plus WRs with no history (n352) and TEs Clay is bullish on vs history (n925). Each has an obvious
Clay-free fix, tested here LOYO vs the shadow itself (verdict PASS <= -0.3% and >= 5/7), then forward:
  A. week 1: lean harder on the preseason market - shadow1 = (1-a) x shadow + a x ADP-curve x layers, a in 0..1
  B. week 1: plain shrink toward the position mean (the shadow over-projects week 1: bias .970)
  C. no-chart veterans: multiplier (shadow over-projects them: bias .932)
  D. WRs with no history: multiplier
  E. TEs whose history is far below the market (ADP curve / history > 1.2): pull toward the ADP curve
Log beat_clay_backtest.log; results -> data/beat_clay_backtest.js (SIM_BEATCLAY_BT), ZONES tab.
"""
import json, os, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import backtest_demoted_vets as DV
import research_clay_vs_shadow as CS
from backtest_target_area import mse

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "beat_clay_backtest.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
DV.P = P
YEARS, POS4 = NW.YEARS, NW.POS4
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "sweeps": [], "forward": [], "gaps": []}


def forward(A, ref, act, year, grid, predfn, mask, label):
    """multiplier / weight picked on earlier seasons only (2021-25)."""
    fwd = ref.copy(); fm = (year >= YEARS[2]) & mask
    for y in YEARS[2:]:
        tr = mask & (year < y)
        if tr.sum() < 60: continue
        v = min(grid, key=lambda v: mse(predfn(v)[tr], act[tr])); fwd = np.where(mask & (year == y), predfn(v), fwd)
    pc, w, ny = NW.pct_vs(fwd[fm], ref[fm], act[fm], year[fm])
    P(f"    FORWARD {label}: rows n={fm.sum()} {pc:+.2f}% vs shadow ({w}/{ny})")
    RES["forward"].append({"label": label, "n": int(fm.sum()), "pct": round(pc, 3), "wins": int(w), "years": ny})
    return pc, w, ny


def main():
    t0 = time.time()
    P("=== Beat Clay where he still wins: week 1, no chart, WR no-history, TE market-vs-history ===")
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g = A["act"], A["year"], A["wk"], A["pos"], A["g"]
    ship, ref, adp_curve, fb_pos, layers, strb, hist, adp = F["shipped"], F["shadow"], F["adp_curve"], F["fb_pos"], F["layers"], F["strb"], F["hist"], F["adp"]
    rookie = A["rookie"]
    pc, w, ny = NW.pct_vs(ref, ship, act, year)
    P(f"  {n} player-weeks | shadow vs shipped {pc:+.2f}% ({w}/{ny})")
    wk1 = g == 0; has_mkt = ~np.isnan(adp_curve)
    nochart = np.isnan(strb) & ~rookie
    wr_nohist = (pos == "WR") & np.isnan(hist)
    mkt_hist = np.where(~np.isnan(hist) & (hist > 0) & has_mkt, adp_curve / np.where(np.isnan(hist) | (hist <= 0), 1, hist), np.nan)
    te_bull = (pos == "TE") & (mkt_hist > 1.2) & ~rookie
    for lab, m in (("week 1", wk1), ("week 1 with an ADP", wk1 & has_mkt), ("no-chart vets", nochart), ("WR no history", wr_nohist), ("TE market > 1.2x history", te_bull)):
        r = CS.seg_row(lab, m, act, ship, ref, year, min_n=50)
        if r: P(CS.fmt(r)); RES["gaps"].append(r)
    # ---- A: week-1 market lean ----
    P("\n=== A. Week 1: shadow -> (1-a) shadow + a x ADP curve x layers (a = 0 is the current shadow) ===")
    AG = [0.0, 0.15, 0.3, 0.5, 0.7, 1.0]
    mkt = np.where(has_mkt, adp_curve * layers, ref)
    def lean(a, m): return np.where(m, (1 - a) * ref + a * mkt, ref)
    m1 = wk1 & has_mkt
    DV.RES["sweeps"] = []
    DV.loyo_vs_ref(A, ref, ship, AG, lambda a: lean(a, m1), "week 1 market lean a, all positions", m1)
    for ps in POS4:
        mm = m1 & (pos == ps)
        if mm.sum() >= 100: DV.loyo_vs_ref(A, ref, ship, AG, lambda a, mm=mm: lean(a, mm), f"  week 1 market lean, {ps}", mm)
    DV.loyo_vs_ref(A, ref, ship, AG, lambda a: lean(a, m1 & ~rookie), "  week 1 market lean, veterans only", m1 & ~rookie)
    DV.loyo_vs_ref(A, ref, ship, AG, lambda a: lean(a, m1 & rookie), "  week 1 market lean, rookies only", m1 & rookie)
    forward(A, ref, act, year, AG, lambda a: lean(a, m1), m1, "week 1 market lean")
    # ---- B: week-1 shrink to the position mean ----
    P("\n=== B. Week 1: shrink toward the position mean, shadow -> mean + s x (shadow - mean) ===")
    SG = [1.0, 0.95, 0.9, 0.85, 0.8, 0.7]
    def shrink(s, m): return np.where(m, fb_pos * layers + s * (ref - fb_pos * layers), ref)
    DV.loyo_vs_ref(A, ref, ship, SG, lambda s: shrink(s, wk1), "week 1 shrink s, all positions", wk1)
    for ps in POS4:
        mm = wk1 & (pos == ps)
        if mm.sum() >= 100: DV.loyo_vs_ref(A, ref, ship, SG, lambda s, mm=mm: shrink(s, mm), f"  week 1 shrink, {ps}", mm)
    forward(A, ref, act, year, SG, lambda s: shrink(s, wk1), wk1, "week 1 shrink")
    # ---- C: no-chart veterans ----
    P("\n=== C. No-chart veterans: multiplier (they carry no string dock) ===")
    MG = [1.0, 0.95, 0.9, 0.85, 0.8, 0.7]
    def mult(m_, m): return np.where(m, ref * m_, ref)
    DV.loyo_vs_ref(A, ref, ship, MG, lambda v: mult(v, nochart), "no-chart vets x m, all positions", nochart)
    for ps in POS4:
        mm = nochart & (pos == ps)
        if mm.sum() >= 80: DV.loyo_vs_ref(A, ref, ship, MG, lambda v, mm=mm: mult(v, mm), f"  no-chart vets x m, {ps}", mm)
    DV.loyo_vs_ref(A, ref, ship, MG, lambda v: mult(v, nochart & (g >= 4)), "  no-chart vets x m, 4+ games in (data should have fixed it)", nochart & (g >= 4))
    DV.loyo_vs_ref(A, ref, ship, MG, lambda v: mult(v, nochart & (g < 4)), "  no-chart vets x m, first 4 games", nochart & (g < 4))
    forward(A, ref, act, year, MG, lambda v: mult(v, nochart), nochart, "no-chart vets x m")
    # ---- D: WR no history ----
    P("\n=== D. WRs with no history: multiplier ===")
    DV.loyo_vs_ref(A, ref, ship, MG, lambda v: mult(v, wr_nohist), "WR no-history x m", wr_nohist)
    DV.loyo_vs_ref(A, ref, ship, MG, lambda v: mult(v, wr_nohist & ~rookie), "  WR no-history x m, non-rookies", wr_nohist & ~rookie)
    forward(A, ref, act, year, MG, lambda v: mult(v, wr_nohist), wr_nohist, "WR no-history x m")
    # ---- E: TE market far above history -> lean to the market ----
    P("\n=== E. TEs the market rates > 1.2x their history: lean toward the ADP curve (a = 0 current) ===")
    def lean_te(a): return np.where(te_bull, (1 - a) * ref + a * mkt, ref)
    DV.loyo_vs_ref(A, ref, ship, AG, lean_te, "TE market > 1.2x history, lean a", te_bull)
    forward(A, ref, act, year, AG, lean_te, te_bull, "TE market lean")
    RES["sweeps"] = DV.RES["sweeps"]
    passes = [r for r in RES["sweeps"] if r["verdict"] == "PASS"]
    RES["summary"] = ("PASS: " + "; ".join(f"{r['label'].strip()} best {r['pooledBest']} {r['loyoPct']:+.2f}% ({r['wins']}/{r['years']})" for r in passes) if passes else "Nothing passes: none of the five Clay-free fixes for the week-1 / no-chart gap beats the shadow LOYO at -0.3% and 5/7.") + \
        " | forward: " + "; ".join(f"{f['label']} {f['pct']:+.2f}% ({f['wins']}/{f['years']})" for f in RES["forward"])
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "beat_clay_backtest.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_BEATCLAY_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/beat_clay_backtest.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
