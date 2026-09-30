#!/usr/bin/env python3
"""
WHERE CLAY WINS vs THE CLAY-FREE SHADOW, by player type (2026-09-16).

Jack: "is there any correlation in which type of players clay is more successful in a large sample vs the non clay
shadow." Same harness as the shadow ladder (19k Clay-pool player-weeks 2019-25, half-PPR, Vegas x FPA layers on
both sides): shipped = P=5 blend of Clay's season PPG with season-to-date, shadow = the harness copy of the v2.11
ladder (history + ADP market prior + string docks + 2nd-year boost + ramp + vacated ^.75; no route grade, no
questionable dock - those are small). For every player-type cut the table reports n, MSE of each side, the shadow's
MSE vs shipped (negative = shadow better), how many of the 7 seasons the shadow wins, and each side's bias
(actual / projected). A Clay edge that repeats across seasons on a big cut is a player type where his information
beats history + market; the reverse says where the shadow already carries the same information.
Log clay_vs_shadow_research.log; results -> data/clay_vs_shadow_research.js (SIM_CLAYSEG), ZONES tab.
"""
import json, os, sys, time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import backtest_rookie_prior as RP
import backtest_rookie_depth_live as RD
import backtest_nochart_vets as NC
import backtest_second_year as SY
import bt_common as B
from backtest_target_area import mse

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "clay_vs_shadow_research.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

YEARS, POS4 = NW.YEARS, NW.POS4
FIT_WK = 8; RAMP = [0.7, 0.8]; POOL_K = 0.75
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "families": [], "byPos": {}}


def build_harness():
    """shadow build copied from backtest_vacated_shadow.main (the v2.11 harness form) + the vacated ^.75 layer."""
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
    hist_raw = hist.copy()
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
    wv = np.where(yr2, 0.5, 0.75); pr = np.where(mkt_ok, (1 - wv) * hist + wv * adp_curve, hist)
    miss = np.isnan(pr); pr[miss] = fb[miss]
    for ps, d in NC.VETDOCK.items():
        for sb, mm_ in d.items():
            mk = vet & (pos == ps) & (strb == sb); pr[mk] *= mm_
    pr = np.where(yr2lo & vet, pr * 1.2, pr)
    prior = fb_pos + 0.8 * (pr - fb_pos)
    ref = NW.blend(prior, g, ppg, Pvec) * layers
    for gi, m_ in enumerate(RAMP, start=1): ref = np.where(buried_rk & (wk == gi), ref * m_, ref)
    L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet"), columns=["year", "pid", "wk", "pool_mult"])
    key = {(int(r.year), r.pid, int(r.wk)): float(r.pool_mult) for r in L.itertuples(index=False) if isinstance(r.pid, str)}
    pm = np.array([key.get((year[i], pid[i], wk[i]), np.nan) if pid[i] else np.nan for i in range(n)])
    on = ~np.isnan(pm) & (pm > 1.0); shadow = np.where(on, ref * np.power(pm, POOL_K), ref)
    F = dict(A=A, n=n, shipped=shipped, shadow=shadow, prior=prior, hist=hist_raw, adp=adp, strb=strb, late=late, mkt_ok=mkt_ok, vet_opp=vet_opp, on=on, pm=pm, has_h3=has_h3, has_l8=has_l8, adp_curve=adp_curve, fb_pos=fb_pos, layers=layers, Pvec=Pvec, buried_rk=buried_rk)
    return F


def seg_row(label, m, act, ship, shad, year, min_n=150):
    n = int(m.sum())
    if n < min_n: return None
    ms, md = mse(ship[m], act[m]), mse(shad[m], act[m])
    ys = [y for y in YEARS if (year[m] == y).sum() >= 20]
    wins = sum(1 for y in ys if mse(shad[m & (year == y)], act[m & (year == y)]) < mse(ship[m & (year == y)], act[m & (year == y)]))
    return {"label": label, "n": n, "mseShip": round(ms, 3), "mseShad": round(md, 3), "pct": round((md / ms - 1) * 100, 2), "wins": int(wins), "years": len(ys),
            "biasShip": round(float(act[m].mean() / ship[m].mean()), 3), "biasShad": round(float(act[m].mean() / shad[m].mean()), 3), "actMean": round(float(act[m].mean()), 2)}


def fmt(r):
    tag = "CLAY" if (r["pct"] > 0.5 and r["wins"] <= r["years"] // 2) else ("SHADOW" if (r["pct"] < -0.5 and r["wins"] > r["years"] // 2) else "even")
    return f"  {r['label']:34s} n={r['n']:5d} act {r['actMean']:5.2f} | shadow vs Clay {r['pct']:+6.2f}% ({r['wins']}/{r['years']}) | bias act/proj Clay {r['biasShip']:.3f} shadow {r['biasShad']:.3f}  {tag}"


def main():
    t0 = time.time()
    P("=== Where Clay wins vs the Clay-free shadow, by player type (2019-25, half-PPR) ===")
    F = build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, clay = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"]
    ship, shad, hist, adp, strb, late, prior = F["shipped"], F["shadow"], F["hist"], F["adp"], F["strb"], F["late"], F["prior"]
    exp, age, rookie, mover, rnd, h3g, l8g = A["exp"], A["age"], A["rookie"], A["mover"], A["rnd"], A["h3g"], A["l8g"]
    pc, w, ny = NW.pct_vs(shad, ship, act, year)
    P(f"  {n} player-weeks | harness shadow (v2.11 form) vs shipped Clay blend: {pc:+.2f}% MSE, shadow better in {w}/{ny} seasons")
    P("  Read: negative % = shadow better; 'CLAY' tag = Clay better by > 0.5% and in most seasons; 'SHADOW' = the reverse.")
    ratio = np.where(~np.isnan(hist) & (hist > 0), clay / np.where(np.isnan(hist) | (hist <= 0), 1, hist), np.nan)   # Clay season PPG vs the player's own history
    surprise = np.where(g > 0, ppg / np.maximum(clay, 0.5), np.nan)                                                   # season-to-date vs Clay
    disagree = shad / np.maximum(ship, 0.5)                                                                           # this week: shadow vs Clay blend
    # per-position quartile of Clay's own number and of history
    def pos_q(v, k=4):
        out = np.full(n, np.nan)
        for ps in POS4:
            m = (pos == ps) & ~np.isnan(v)
            if m.sum() < 40: continue
            qs = np.quantile(v[m], np.linspace(0, 1, k + 1)[1:-1]); out[m] = np.searchsorted(qs, v[m]) + 1
        return out
    clay_q, hist_q = pos_q(clay), pos_q(hist)
    all_m = np.ones(n, dtype=bool)
    FAM = []
    FAM.append(("Position", [(ps, pos == ps) for ps in POS4]))
    FAM.append(("Experience", [("rookie", rookie), ("2nd year", exp == 1), ("years 3-5", (exp >= 2) & (exp <= 4)), ("years 6-9", (exp >= 5) & (exp <= 8)), ("year 10+", exp >= 9)]))
    FAM.append(("Age", [("<= 24", age <= 24), ("25-27", (age > 24) & (age <= 27)), ("28-30", (age > 27) & (age <= 30)), ("31+", age > 30)]))
    FAM.append(("Preseason ADP", [("ADP 1-24", adp <= 24), ("ADP 25-60", (adp > 24) & (adp <= 60)), ("ADP 61-120", (adp > 60) & (adp <= 120)), ("ADP 121-180", (adp > 120) & (adp <= 180)), ("undrafted / no ADP", np.isnan(adp))]))
    FAM.append(("Depth-chart string", [("string 1", strb == 1), ("string 2", strb == 2), ("string 3+", strb >= 3), ("no chart", np.isnan(strb))]))
    FAM.append(("Clay's season PPG (pos quartile)", [(f"Clay Q{q} ({'low' if q == 1 else 'high' if q == 4 else 'mid'})", clay_q == q) for q in (1, 2, 3, 4)]))
    FAM.append(("Own history PPG (pos quartile)", [(f"history Q{q}", hist_q == q) for q in (1, 2, 3, 4)] + [("no history (rookie / thin)", np.isnan(hist))]))
    FAM.append(("Clay vs own history (season PPG ratio)", [("Clay bearish < 0.8x", ratio < 0.8), ("Clay 0.8-0.95x", (ratio >= 0.8) & (ratio < 0.95)), ("Clay ~ history 0.95-1.05x", (ratio >= 0.95) & (ratio <= 1.05)),
                                                          ("Clay 1.05-1.25x", (ratio > 1.05) & (ratio <= 1.25)), ("Clay bullish > 1.25x", ratio > 1.25)]))
    FAM.append(("Games into the season", [("week 1 (no data)", g == 0), ("games 1-3", (g >= 1) & (g <= 3)), ("games 4-8", (g >= 4) & (g <= 8)), ("games 9+", g >= 9)]))
    FAM.append(("Season-to-date vs Clay (after 3+ games)", [("cold < 0.7x Clay", (g >= 3) & (surprise < 0.7)), ("0.7-0.9x", (g >= 3) & (surprise >= 0.7) & (surprise < 0.9)), ("on track 0.9-1.1x", (g >= 3) & (surprise >= 0.9) & (surprise <= 1.1)),
                                                             ("1.1-1.3x", (g >= 3) & (surprise > 1.1) & (surprise <= 1.3)), ("hot > 1.3x Clay", (g >= 3) & (surprise > 1.3))]))
    FAM.append(("This week's disagreement (shadow / Clay blend)", [("shadow < 0.8x", disagree < 0.8), ("0.8-0.95x", (disagree >= 0.8) & (disagree < 0.95)), ("agree 0.95-1.05x", (disagree >= 0.95) & (disagree <= 1.05)),
                                                                   ("1.05-1.25x", (disagree > 1.05) & (disagree <= 1.25)), ("shadow > 1.25x", disagree > 1.25)]))
    FAM.append(("Situation", [("changed team", mover & ~rookie), ("same team vet", ~mover & ~rookie), ("rookie R1-2", rookie & (rnd <= 2)), ("rookie R3+ / UDFA", rookie & (rnd >= 3)),
                              ("vacated-role week", F["on"]), ("2nd-yr low-snap", (exp == 1) & ~np.isnan(late) & (late < 0.4)), ("thin history (< 8 prior games)", ~rookie & (h3g + l8g < 8)), ("opportunity prior used", F["vet_opp"])]))
    FAM.append(("Vegas / FPA layer", [("layers < 0.9", A["layers"] < 0.9), ("0.9-1.1", (A["layers"] >= 0.9) & (A["layers"] <= 1.1)), ("layers > 1.1", A["layers"] > 1.1)]))
    for fam, cuts in FAM:
        P(f"\n--- {fam} ---")
        rows = []
        for lab, m in cuts:
            r = seg_row(lab, m & all_m, act, ship, shad, year)
            if r: rows.append(r); P(fmt(r))
        RES["families"].append({"name": fam, "rows": rows})
    # position x the two most diagnostic families
    P("\n=== By position: Clay vs own history, and season-to-date vs Clay ===")
    for ps in POS4:
        pm_ = pos == ps; rows = []
        for lab, m in (("Clay bearish < 0.9x hist", ratio < 0.9), ("Clay ~ hist 0.9-1.1x", (ratio >= 0.9) & (ratio <= 1.1)), ("Clay bullish > 1.1x hist", ratio > 1.1), ("no history", np.isnan(hist)),
                       ("cold < 0.8x Clay (3+ g)", (g >= 3) & (surprise < 0.8)), ("on track (3+ g)", (g >= 3) & (surprise >= 0.8) & (surprise <= 1.2)), ("hot > 1.2x Clay (3+ g)", (g >= 3) & (surprise > 1.2)),
                       ("string 1", strb == 1), ("string 2+", strb >= 2), ("ADP top-60", adp <= 60), ("ADP 61-180", (adp > 60) & (adp <= 180)), ("no ADP", np.isnan(adp))):
            r = seg_row(lab, pm_ & m, act, ship, shad, year, min_n=100)
            if r: rows.append(r); P(f"{ps} " + fmt(r))
        RES["byPos"][ps] = rows
    # headline: the strongest repeatable Clay edges and shadow edges (n >= 300)
    allrows = [dict(r, fam=f["name"]) for f in RES["families"] for r in f["rows"] if r["n"] >= 300]
    clay_edge = sorted([r for r in allrows if r["pct"] > 0 and r["wins"] <= r["years"] // 2], key=lambda r: -r["pct"])[:8]
    shad_edge = sorted([r for r in allrows if r["pct"] < 0 and r["wins"] > r["years"] // 2], key=lambda r: r["pct"])[:8]
    P("\n=== Strongest repeatable CLAY edges (n >= 300, Clay wins most seasons) ===")
    for r in clay_edge: P(f"  {r['fam']} / {r['label']}: n {r['n']}, Clay better by {r['pct']:+.2f}% MSE, shadow wins {r['wins']}/{r['years']} seasons")
    P("=== Strongest repeatable SHADOW edges ===")
    for r in shad_edge: P(f"  {r['fam']} / {r['label']}: n {r['n']}, shadow better by {r['pct']:+.2f}% MSE, wins {r['wins']}/{r['years']} seasons")
    RES["clayEdges"], RES["shadowEdges"] = clay_edge, shad_edge
    RES["overall"] = {"n": int(n), "pct": round(pc, 2), "wins": int(w), "years": ny}
    RES["summary"] = (f"Harness shadow vs Clay blend {pc:+.2f}% ({w}/{ny}). Clay's repeatable edges: " + "; ".join(f"{r['label']} {r['pct']:+.1f}% (n{r['n']}, shadow {r['wins']}/{r['years']})" for r in clay_edge[:5]) +
                      ". Shadow's: " + "; ".join(f"{r['label']} {r['pct']:+.1f}% (n{r['n']}, {r['wins']}/{r['years']})" for r in shad_edge[:5]) + ".")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "clay_vs_shadow_research.js"), "w", encoding="utf-8") as f:
        f.write("window.SIM_CLAYSEG = " + json.dumps(RES) + ";\n")
    P(f"wrote data/clay_vs_shadow_research.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
