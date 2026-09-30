#!/usr/bin/env python3
"""
THE ADP 31-60 BAND (2026-09-17). Jack: "lets work on the 31-60 band".

Band view (backtest_adp_bands.py): 31-60 is the shadow's soft band - week 2 worse than today's Clay blend in 5 of 7
seasons, start/sit disagreements a coin flip, level 2% low. Diagnosis (week-1 rows vs the players' season rate): our
prior is -4.8% in 31-60 (hand prior -8.1%, ridge -0.6%, ADP curve -2.2%) vs +0.2% in 1-30 and -1.5% in 61-100.
Two causes: (1) the hand prior shrinks every player 20% toward the mean of the WHOLE position pool (backups included),
which bites hardest in rounds 3-5; (2) the market curve is log-linear in ADP and is the wrong shape - +10.6% too high
at ADP 1-12, -7.8% at 37-48, -4.9% at 49-60 (RB / WR 1-2 pts low).
Candidates for the hand prior of veterans with ADP + history (rookies and no-ADP rows untouched):
  A  flexible market curve      piecewise-linear in log ADP per position (knots ADP 12 / 24 / 36 / 60 / 100), LOYO
  B  shrink target = market     prior = curve + k (pr - curve) instead of posmean + k (pr - posmean)
  C  lighter shrink top 60      k = .9 / 1.0 for ADP <= 60 (position-mean target)
  and the combinations A+B, A+C.
Everything else (ridge half, usage evidence, WR one-game prior, QB tilt, backup-QB dock, layers) as in v2.21.
Graded vs the current shadow and vs today's Clay blend by non-overlapping ADP band (unweighted), weighted top 150,
weekly rank; forward 2021-25. Log band3160.log; results -> data/band3160.js (SIM_BAND3160_BT).
"""
import json, os, sys, time, warnings
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy.stats import rankdata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import research_clay_vs_shadow as CS
import backtest_season_long as SL
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "band3160.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
YEARS, POS4 = NW.YEARS, NW.POS4
KNOTS = np.log(np.array([12.0, 24.0, 36.0, 60.0, 100.0]))
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "curve": [], "bands": [], "forward": [], "week2": []}


def basis(ladp):
    return np.column_stack([np.ones(len(ladp)), ladp] + [np.maximum(0.0, ladp - k) for k in KNOTS])


def main():
    t0 = time.time()
    P("=== The ADP 31-60 band: market-curve shape and shrink target in the shadow's hand prior ===")
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, clay, layers, adp, pid = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"], F["adp"], A["pid"]
    ch = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, A["name"])], dtype=float)
    W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay); CUR = NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers
    T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    def colv(c): return np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    xfp = colv("xfp_pg"); ev = has & (g >= 1) & ~np.isnan(xfp); xf = np.where(ev, xfp, ppg)
    lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0)); evid = lam * xf + (1 - lam) * ppg
    gt = colv("game_total"); z = np.zeros(n)
    for y in YEARS:
        for w_ in range(1, 19):
            m = (year == y) & (wk == w_) & ~np.isnan(gt)
            if m.sum() > 20 and gt[m].std() > 0: z[m] = np.clip((gt[m] - gt[m].mean()) / gt[m].std(), -2.5, 2.5)
    qbo = colv("qb_out") == 1; PW = np.where((pos == "WR") & (g == 1), F["Pvec"] * 5, F["Pvec"])
    def ridge_rows(fwd):
        lo = (SL.forward if fwd else SL.loyo)(T, LIVE, "ridge", 10.0); key = {(int(y), nm, ps): v for y, nm, ps, v in zip(T.year, T.name, T.pos, lo)}
        return np.array([key.get((year[i], A["name"][i], pos[i]), np.nan) for i in range(n)])
    RR = {False: ridge_rows(False), True: ridge_rows(True)}
    def shadow(hand, fwd=False):
        r = RR[fwd]; prior = np.where(np.isnan(r) | (pos == "QB"), hand, 0.5 * r + 0.5 * hand); out = NW.blend(prior, g, evid, PW) * layers
        for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
        out = np.where(F["on"], out * np.power(F["pm"], 0.75), out); out = np.where(pos == "QB", out * np.exp(0.03 * z), out)
        return np.where((pos == "WR") & qbo, out * np.where(adp <= 60, 0.85, 0.95), out)
    # ---- rebuild the hand prior's pieces for veterans with ADP + history ----
    hand0, fb_pos, curve0 = F["prior"], F["fb_pos"], F["adp_curve"]
    hist_adj = np.array([NW.age_adjust(pos[i], F["hist"][i], A["age"][i]) if not np.isnan(F["hist"][i]) else np.nan for i in range(n)])
    tun = F["mkt_ok"] & ~np.isnan(hist_adj) & ~np.isnan(curve0); wv = np.where(A["exp"] == 1, 0.5, 0.75)
    pr0 = fb_pos + (hand0 - fb_pos) / 0.8; base0 = (1 - wv) * hist_adj + wv * curve0; mult = np.where(tun & (base0 > 0), pr0 / base0, 1.0)
    # ---- A: flexible market curve, LOYO (fwd: earlier seasons only), fit like the harness curve on weeks <= 4 ----
    ladp = np.log(np.where(np.isnan(adp), 181.0, adp)); has_adp = ~np.isnan(adp)
    def flex_curve(fwd):
        out = curve0.copy()
        for y in (YEARS[2:] if fwd else YEARS):
            for ps in POS4:
                tr = ((year < y) if fwd else (year != y)) & (pos == ps) & has_adp & (wk <= 4); ap = (year == y) & (pos == ps) & has_adp
                if tr.sum() < 200 or not ap.any(): continue
                rate = act[tr] / np.maximum(layers[tr], 0.3); X = basis(ladp[tr]); b = np.linalg.solve(X.T @ X + 2.0 * np.eye(X.shape[1]) * np.r_[0, 0, np.ones(len(KNOTS))], X.T @ rate)
                out[ap] = np.maximum(0.5, basis(ladp[ap]) @ b)
        return out
    FLEX = {False: flex_curve(False), True: flex_curve(True)}
    def hand_of(curve, k60=0.8, target="posmean"):
        pr = np.where(tun, mult * ((1 - wv) * hist_adj + wv * curve), pr0); kk = np.where(adp <= 60, k60, 0.8)
        tg = np.where(tun & (target == "market"), curve, fb_pos)
        return np.where(tun, tg + kk * (pr - tg), hand0)
    P("\n=== Market curve fit residual by ADP bucket, weeks 1-4 (actual rate minus curve): log-linear (current) vs flexible (LOYO) ===")
    for lo_, hi_ in ((1, 12), (13, 24), (25, 36), (37, 48), (49, 60), (61, 80), (81, 100), (101, 150)):
        m = (adp >= lo_) & (adp <= hi_) & (wk <= 4) & ~np.isnan(curve0); rate = act[m] / np.maximum(layers[m], 0.3)
        r = {"band": f"{lo_}-{hi_}", "n": int(m.sum()), "log": round(float(rate.mean() - curve0[m].mean()), 2), "flex": round(float(rate.mean() - FLEX[False][m].mean()), 2)}; RES["curve"].append(r)
        P(f"   ADP {lo_:3d}-{hi_:3d} n={m.sum():4d} | log-linear residual {r['log']:+5.2f} | flexible residual {r['flex']:+5.2f}")
    def variants(fwd):
        fx = FLEX[fwd]
        return {"current shadow (v2.21)": shadow(hand0, fwd), "A flexible market curve": shadow(hand_of(fx), fwd), "B shrink toward the market value": shadow(hand_of(curve0, target="market"), fwd),
                "C k=.9 for ADP<=60": shadow(hand_of(curve0, k60=0.9), fwd), "C k=1.0 for ADP<=60": shadow(hand_of(curve0, k60=1.0), fwd), "A+B flexible curve + market target": shadow(hand_of(fx, target="market"), fwd),
                "A+C flexible curve + k=1.0 top 60": shadow(hand_of(fx, k60=1.0), fwd)}
    BANDS = (("ADP 1-30", adp <= 30), ("ADP 31-60", (adp > 30) & (adp <= 60)), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150", (adp > 100) & (adp <= 150)), ("ADP 151+", ~(adp <= 150)), ("EVERYONE", np.ones(n, bool)))
    e = lambda q, mm: float(np.mean((q[mm] - act[mm]) ** 2))
    groups = defaultdict(list)
    for i in np.where(adp <= 150)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
    groups = {k: np.array(v) for k, v in groups.items() if len(v) >= 8}
    def rho(pred, ys):
        return float(np.mean([np.corrcoef(rankdata(act[ix]), rankdata(pred[ix]))[0, 1] for (y, w_, p_), ix in groups.items() if y in ys]))
    def report(V, store, title, ys, fm):
        base = V["current shadow (v2.21)"]; P(f"\n=== {title}: error vs the CURRENT shadow (seasons better) by ADP band | vs today's Clay blend in 31-60 | weekly rank rho, top 150 ===")
        for nm, p in V.items():
            cells = []
            for lab, bm in BANDS:
                m = bm & fm; wins = sum(1 for y in ys if e(p, m & (year == y)) < e(base, m & (year == y)) - 1e-12); d = (e(p, m) / e(base, m) - 1) * 100
                store.append({"variant": nm, "band": lab, "vsShadow": round(d, 2), "wins": wins, "years": len(ys), "vsClay": round((e(p, m) / e(CUR, m) - 1) * 100, 2)}); cells.append(f"{lab.replace('ADP ', '')}: {d:+.2f}% ({wins}/{len(ys)})")
            m36 = BANDS[1][1] & fm; wc = sum(1 for y in ys if e(p, m36 & (year == y)) < e(CUR, m36 & (year == y)))
            P(f"  {nm:36s} " + " | ".join(cells) + f" || 31-60 vs Clay {(e(p, m36)/e(CUR, m36)-1)*100:+.2f}% ({wc}/{len(ys)}), level {p[m36].mean():.2f} vs actual {act[m36].mean():.2f} || rho {rho(p, set(ys)):.4f}")
    V = variants(False); report(V, RES["bands"], "LOYO, all weeks", YEARS, np.ones(n, bool))
    P("\n=== WEEK 2 only, ADP 31-60: error vs today's Clay blend by season (negative = we are better) ===")
    m2 = (adp > 30) & (adp <= 60) & (wk == 2)
    for nm, p in V.items():
        per = [(e(p, m2 & (year == y)) / e(CUR, m2 & (year == y)) - 1) * 100 for y in YEARS]; wins = sum(1 for v in per if v < 0)
        RES["week2"].append({"variant": nm, "pooled": round((e(p, m2) / e(CUR, m2) - 1) * 100, 2), "wins": wins}); P(f"  {nm:36s} pooled {(e(p, m2)/e(CUR, m2)-1)*100:+6.2f}% | seasons better {wins}/7 | " + " ".join(f"{y}:{v:+.1f}" for y, v in zip(YEARS, per)))
    report(variants(True), RES["forward"], "FORWARD 2021-25 (ridge + flexible curve fit on earlier seasons only)", YEARS[2:], year >= YEARS[2])
    b36 = [r for r in RES["bands"] if r["band"] == "ADP 31-60" and r["variant"] != "current shadow (v2.21)"]; best = min(b36, key=lambda r: r["vsShadow"]); ev_ = [r for r in RES["bands"] if r["band"] == "EVERYONE" and r["variant"] == best["variant"]][0]
    fb = [r for r in RES["forward"] if r["band"] == "ADP 31-60" and r["variant"] == best["variant"]][0]
    RES["summary"] = (f"ADP 31-60: best = {best['variant']} {best['vsShadow']:+.2f}% vs the current shadow ({best['wins']}/7), {best['vsClay']:+.2f}% vs today's Clay blend; everyone {ev_['vsShadow']:+.2f}% ({ev_['wins']}/7); forward 31-60 {fb['vsShadow']:+.2f}% ({fb['wins']}/5).")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "band3160.js"), "w", encoding="utf-8") as fh:
        fh.write("window.SIM_BAND3160_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/band3160.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
