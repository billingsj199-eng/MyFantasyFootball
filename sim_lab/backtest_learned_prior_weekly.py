#!/usr/bin/env python3
"""
LEARNED SEASON PRIOR ON THE WEEKLY SHADOW, week 1 included (2026-09-16).

Jack: "lets continue on sims testing on past seasons and even week 1." The season-long harness found a small ridge
(ADP, history, age, draft pick, week-1 string; backtest_season_long.py) that beats Clay's season sheet -10% LOYO /
-5% forward. Here that ridge replaces the shadow's hand-built preseason prior inside the WEEKLY harness (the P-blend
with season-to-date PPG, Vegas x FPA, ramp, vacated boost), graded on every player-week 2019-25 vs the shadow itself
and vs the shipped Clay blend, split by season stage (week 1 / games 1-3 / 4-8 / 9+) and by position; then forward
(the ridge fit on earlier seasons only, 2021-25). Sweeps: the mix a x ridge + (1-a) x shadow prior; the prior
strength P for the ridge prior; and a Clay-vs-ridge comparison on week 1 alone (the last cut Clay still won).
Log learned_prior_weekly.log; results -> data/learned_prior_weekly.js (SIM_LPRIOR_BT), ZONES tab.
"""
import json, os, sys, time, warnings
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import backtest_demoted_vets as DV
import backtest_season_long as SL
from backtest_target_area import mse
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "learned_prior_weekly.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
DV.P = P
YEARS, POS4 = NW.YEARS, NW.POS4
RAMP = [0.7, 0.8]; POOL_K = 0.75
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "stages": [], "sweeps": [], "forward": [], "byPos": [], "week1": []}


def stage_masks(g):
    return (("week 1 (no data)", g == 0), ("games 1-3", (g >= 1) & (g <= 3)), ("games 4-8", (g >= 4) & (g <= 8)), ("games 9+", g >= 9), ("ALL weeks", np.ones(len(g), bool)))


def grade(label, pred, ref, ship, act, year, mask, store):
    m = mask & ~np.isnan(pred)
    pv, wv, ny = NW.pct_vs(pred[m], ref[m], act[m], year[m]); pc, wc, _ = NW.pct_vs(pred[m], ship[m], act[m], year[m]); rc, _, _ = NW.pct_vs(ref[m], ship[m], act[m], year[m])
    row = {"label": label, "n": int(m.sum()), "vsShadow": round(pv, 2), "shadowWins": int(wv), "years": ny, "vsClay": round(pc, 2), "clayWins": int(wc), "shadowVsClay": round(rc, 2)}
    P(f"  {label:36s} n={m.sum():5d} | vs shadow {pv:+6.2f}% ({wv}/{ny}) | vs Clay blend {pc:+6.2f}% ({wc}/{ny})  [shadow alone {rc:+.2f}%]")
    store.append(row); return row


def main():
    t0 = time.time()
    P("=== Learned season prior inside the weekly shadow (week 1 included) ===")
    T, F = SL.build_table(return_F=True); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"]
    ship, ref, prior, layers, Pvec, fb_pos, buried_rk, on, pm = F["shipped"], F["shadow"], F["prior"], F["layers"], F["Pvec"], F["fb_pos"], F["layers"] * 0 + F["Pvec"] * 0 + 0, F["on"], F["pm"]
    buried_rk = F["buried_rk"]
    # ridge basic: LOYO and forward predictions per player-season (fit inside backtest_season_long)
    lo = SL.loyo(T, SL.BASIC, "ridge", 10.0); fw = SL.forward(T, SL.BASIC, "ridge", 10.0)
    key = {(int(y), nm, ps): (a, b) for y, nm, ps, a, b in zip(T.year, T.name, T.pos, lo, fw)}
    r_lo = np.array([key.get((year[i], A["name"][i], pos[i]), (np.nan, np.nan))[0] for i in range(n)])
    r_fw = np.array([key.get((year[i], A["name"][i], pos[i]), (np.nan, np.nan))[1] for i in range(n)])
    has = ~np.isnan(r_lo)
    P(f"  {n} player-weeks, ridge prior available on {has.sum()} ({has.mean()*100:.0f}%; the rest = seasons under 4 games, kept on the shadow prior)")
    def build(pr, Pv=None):
        out = NW.blend(pr, g, ppg, Pvec if Pv is None else Pv) * layers
        for gi, m_ in enumerate(RAMP, start=1): out = np.where(buried_rk & (wk == gi), out * m_, out)
        return np.where(on, out * np.power(pm, POOL_K), out)
    base = build(prior)
    P(f"  rebuilt shadow vs harness shadow: max |diff| {np.nanmax(np.abs(base - ref)):.4f} (must be ~0)")
    def mix(a, Pv=None):
        pr = np.where(has, a * r_lo + (1 - a) * prior, prior); return build(pr, Pv)
    cand = mix(1.0)
    P("\n=== Ridge prior replaces the shadow prior: by season stage (LOYO ridge) ===")
    for lab, m in stage_masks(g): grade(lab, cand, ref, ship, act, year, m, RES["stages"])
    P("\n=== By position, all weeks ===")
    for ps in POS4: grade(ps, cand, ref, ship, act, year, pos == ps, RES["byPos"])
    for ps in POS4: grade(f"{ps} week 1", cand, ref, ship, act, year, (pos == ps) & (g == 0), RES["byPos"])
    # ---- sweeps LOYO vs shadow ----
    P("\n=== Sweeps (LOYO vs the shadow; 0 = current shadow prior) ===")
    DV.RES["sweeps"] = []
    AG = [0.0, 0.25, 0.5, 0.75, 1.0]
    DV.loyo_vs_ref(A, ref, ship, AG, lambda a: mix(a), "mix a x ridge + (1-a) x shadow prior, all rows", has)
    for lab, m in stage_masks(g)[:4]: DV.loyo_vs_ref(A, ref, ship, AG, lambda a: mix(a), f"  mix a, {lab}", has & m)
    for ps in POS4: DV.loyo_vs_ref(A, ref, ship, AG, lambda a: mix(a), f"  mix a, {ps}", has & (pos == ps))
    PG = [1.0, 0.75, 0.5, 1.5, 2.0]   # multiplier on the per-position prior strength when the prior is the ridge
    DV.loyo_vs_ref(A, ref, ship, PG, lambda k: mix(1.0, Pvec * k), "ridge prior, strength P x k (k=1 = QB12/RB5/WR8/TE8)", has)
    for ps in POS4: DV.loyo_vs_ref(A, ref, ship, PG, lambda k: mix(1.0, Pvec * k), f"  P x k, {ps}", has & (pos == ps))
    RES["sweeps"] = DV.RES["sweeps"]
    # ---- week 1 head-to-head: Clay's last cut ----
    P("\n=== Week 1 head-to-head (no season data; prior x layers only) ===")
    w1 = g == 0
    for lab, pred in (("shadow prior (current)", ref), ("ridge prior", cand), ("0.5 ridge + 0.5 shadow prior", mix(0.5)), ("Clay blend (shipped)", ship)):
        grade(f"week 1: {lab}", pred, ref, ship, act, year, w1, RES["week1"])
    for ps in POS4: grade(f"week 1 {ps}: ridge prior", cand, ref, ship, act, year, w1 & (pos == ps), RES["week1"])
    # ---- forward ----
    P("\n=== Forward 2021-25: ridge fit on earlier seasons only ===")
    hasf = ~np.isnan(r_fw); fm = year >= YEARS[2]
    candf = build(np.where(hasf, r_fw, prior))
    for lab, m in stage_masks(g): grade(f"forward {lab}", candf, ref, ship, act, year, fm & m, RES["forward"])
    for ps in POS4: grade(f"forward {ps}", candf, ref, ship, act, year, fm & (pos == ps), RES["forward"])
    top = [r for r in RES["stages"] if r["label"] == "ALL weeks"][0]; f_all = [r for r in RES["forward"] if r["label"] == "forward ALL weeks"][0]; w1r = [r for r in RES["stages"] if r["label"].startswith("week 1")][0]; f_w1 = [r for r in RES["forward"] if r["label"] == "forward week 1 (no data)"][0]
    sw = RES["sweeps"][0]
    RES["summary"] = (f"Ridge season prior in the weekly shadow: all weeks {top['vsShadow']:+.2f}% vs shadow ({top['shadowWins']}/{top['years']}), {top['vsClay']:+.2f}% vs Clay blend; week 1 {w1r['vsShadow']:+.2f}% vs shadow, {w1r['vsClay']:+.2f}% vs Clay ({w1r['clayWins']}/{w1r['years']}). "
                      f"Mix sweep best a {sw['pooledBest']} ({sw['loyoPct']:+.2f}%, {sw['wins']}/{sw['years']}, {sw['verdict']}). Forward: all weeks {f_all['vsShadow']:+.2f}% vs shadow ({f_all['shadowWins']}/{f_all['years']}), week 1 {f_w1['vsShadow']:+.2f}% / {f_w1['vsClay']:+.2f}% vs Clay.")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "learned_prior_weekly.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_LPRIOR_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/learned_prior_weekly.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
