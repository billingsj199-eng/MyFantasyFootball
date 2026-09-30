#!/usr/bin/env python3
"""
IN-SEASON USAGE MODEL: does the shadow get better, week by week, when the evidence is VOLUME not points? (2026-09-17)

Jack: "if volume is the issue ... work on the week by week projections and actually use the previous weeks
information (routes run, snaps, target share etc) and see how the model does as the season goes on in back tests" /
"if we can be elite in season that could be very valuable." The oracle test said true volume is half of all error and
nobody forecasts it preseason - but in-season it is OBSERVED. Today the shadow's evidence term is season-to-date
POINTS per game (ppg) blended with the prior at strength P. Candidates, all walk-forward (only weeks before the game):
  E1  xFP/g replaces ppg              usage-implied points (targets, air yards, carries, red zone) per game
  E2  lam(g) x xFP/g + (1-lam) x ppg  lam per games-played bucket and position, LOYO  (xFP early, points late)
  E3  E2 with a recency tilt          x (last-3 share / season share)^r  for targets+carries
  E4  learned rate model              ridge per position x games bucket on prior, ppg, xFP/g, shares (season + last 3),
                                      red-zone / goal-line / air-yard shares, WOPR, snap share + trend, PFF route
                                      rate (season + last 3), points over xFP; target = actual / live layers
  E5  0.5 x E4 + 0.5 x shadow
Everything then gets the same layers / ramp / vacated boost as the shadow. Graded importance-weighted on the top 150
(Jack's rule) vs the current shadow (v2.17 form) and vs the corrected per-game Clay blend, BY GAMES PLAYED (the
learning curve), by position, LOYO and forward 2021-25.
Log inseason_usage.log; results -> data/inseason_usage.js (SIM_INSEASON_BT).
"""
import json, os, sys, time, warnings
from collections import defaultdict
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bt_common as B
import backtest_noclay_weekly as NW
import research_clay_vs_shadow as CS
import backtest_season_long as SL
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "inseason_usage.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
YEARS, POS4 = NW.YEARS, NW.POS4
BUCKETS = (("1 game", 1, 1), ("2 games", 2, 2), ("3 games", 3, 3), ("4-5 games", 4, 5), ("6-8 games", 6, 8), ("9+ games", 9, 99))
USE = ["tgt_sh", "car_sh", "rz_tgt_sh", "rz_car_sh", "gl_car_sh", "ay_sh", "wopr", "xfp_pg", "pts_over_xfp", "tgt_sh_l3", "car_sh_l3", "tgt_trend", "car_trend", "snap_std", "snap_l1", "snap_trend", "db_sh", "att_pg"]
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "curve": [], "byPos": [], "forward": [], "lam": {}, "coef": {}}


def route_features(year, pid, wk):
    pl = pd.read_csv(os.path.join(B.CACHE, "players.csv"), low_memory=False, usecols=["gsis_id", "pff_id"])
    pff2g = {int(r.pff_id): r.gsis_id for r in pl.itertuples(index=False) if pd.notna(r.pff_id) and isinstance(r.gsis_id, str)}
    rr = defaultdict(dict)
    for Y in YEARS:
        for w in range(1, 19):
            f = os.path.join(B.CACHE, "pff", "weekly", f"pff_receiving_summary_{Y}_w{w}.csv")
            if not os.path.exists(f): continue
            d = pd.read_csv(f, usecols=["player_id", "route_rate", "routes"])
            for r in d.itertuples(index=False):
                g = pff2g.get(int(r.player_id))
                if g and pd.notna(r.route_rate): rr[(Y, g)][w] = float(r.route_rate)
    n = len(year); std = np.full(n, np.nan); l3 = np.full(n, np.nan)
    for i in range(n):
        d = rr.get((int(year[i]), pid[i]))
        if not d: continue
        prev = [d[w] for w in sorted(d) if w < wk[i]]
        if prev: std[i] = float(np.mean(prev)); l3[i] = float(np.mean(prev[-3:]))
    return std, l3


def main():
    t0 = time.time()
    P("=== In-season usage model: volume as the evidence, graded by games played ===")
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, clay, layers, adp, pid = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"], F["adp"], A["pid"]
    ch = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, A["name"])], dtype=float)
    W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay)
    ship = NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers
    T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]
    def prior_of(fwd):
        lo = (SL.forward if fwd else SL.loyo)(T, LIVE, "ridge", 10.0); key = {(int(y), nm, ps): v for y, nm, ps, v in zip(T.year, T.name, T.pos, lo)}
        r = np.array([key.get((year[i], A["name"][i], pos[i]), np.nan) for i in range(n)])
        return np.where(np.isnan(r) | (pos == "QB"), F["prior"], 0.5 * r + 0.5 * F["prior"])      # v2.17: no ridge half for QBs
    PRI = {False: prior_of(False), True: prior_of(True)}; Pvec = F["Pvec"]
    def finish(rate):
        out = rate * layers
        for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
        return np.where(F["on"], out * np.power(F["pm"], 0.75), out)
    # ---- usage features (walk-forward, from the context build) + PFF routes ----
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(r.year), r.pid, int(r.wk)): i for i, r in enumerate(C[["year", "pid", "wk"]].itertuples(index=False)) if isinstance(r.pid, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    U = {c: np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float) for c in USE}
    U["rt_std"], U["rt_l3"] = route_features(year, pid, wk)
    ev = has & (g >= 1) & ~np.isnan(U["xfp_pg"])
    P(f"  {n} player-weeks | usage rows joined {int(has.sum())} | with games played + xFP {int(ev.sum())} | PFF route history on {int((~np.isnan(U['rt_std'])).sum())}")
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); t = m & (adp <= 150); lv[m] = lv[m] / lv[t].mean()
    wt = np.maximum(0.05, lv) ** 2; top150 = adp <= 150
    def wm(p, m): return float(np.average((p[m] - act[m]) ** 2, weights=wt[m]))
    def bucket_of(gi):
        for k, (_, a, b) in enumerate(BUCKETS):
            if a <= gi <= b: return k
        return -1
    bk = np.array([bucket_of(int(x)) for x in g])

    def build_all(fwd):
        prior = PRI[fwd]; cur = finish(NW.blend(prior, g, ppg, Pvec)); out = {"shadow (ppg evidence)": cur}
        xf = np.where(ev, U["xfp_pg"], ppg)
        out["E1 xFP/g replaces ppg"] = finish(NW.blend(prior, g, xf, Pvec))
        # E2: lam per position x bucket, chosen on training seasons by weighted top-150 MSE
        e2 = cur.copy(); e3 = cur.copy(); lam_tab = {}
        LG = [0.0, 0.25, 0.5, 0.75, 1.0]; RG = [0.0, 0.5, 1.0]
        tw = np.where(pos == "RB", 0.35, 1.0); cw = np.where(pos == "RB", 1.0, np.where(pos == "QB", 0.0, 0.15))
        num = np.nan_to_num(U["tgt_sh_l3"]) * tw + np.nan_to_num(U["car_sh_l3"]) * cw; den = np.nan_to_num(U["tgt_sh"]) * tw + np.nan_to_num(U["car_sh"]) * cw
        ratio = np.where((den > 0.02) & ev, np.clip(num / np.maximum(den, 1e-6), 0.6, 1.6), 1.0)
        cand2 = {lm: finish(NW.blend(prior, g, lm * xf + (1 - lm) * ppg, Pvec)) for lm in LG}
        for ps in POS4:
            for b in range(len(BUCKETS)):
                for y in (YEARS[2:] if fwd else YEARS):
                    tr = (pos == ps) & (bk == b) & top150 & ev & ((year < y) if fwd else (year != y)); te = (pos == ps) & (bk == b) & (year == y)
                    if tr.sum() < 60 or not te.any(): continue
                    best = min(LG, key=lambda lm: wm(cand2[lm], tr)); e2[te] = cand2[best][te]; lam_tab.setdefault(f"{ps} {BUCKETS[b][0]}", []).append(best)
                    evd = best * xf + (1 - best) * ppg
                    c3 = {r: finish(NW.blend(prior, g, evd * np.power(ratio, r), Pvec)) for r in RG}
                    br = min(RG, key=lambda r: wm(c3[r], tr)); e3[te] = c3[br][te]
        out["E2 lam(g) xFP + ppg"] = e2; out["E3 E2 + recency tilt"] = e3
        # E6: ONE smooth schedule per position: lam(g) = max(floor, start - slope x (g - 1)); QB fixed at 0. Chosen on training seasons only.
        FAM = [(st, sl, fl) for st in (1.0, 0.75, 0.5) for sl in (0.08, 0.125, 0.2, 0.3) for fl in (0.0, 0.25)]
        def lam_vec(c): return np.where(pos == "QB", 0.0, np.maximum(c[2], c[0] - c[1] * np.maximum(g - 1, 0)))
        cand6 = {(c, pk): finish(NW.blend(prior, g, lam_vec(c) * xf + (1 - lam_vec(c)) * ppg, np.where(pos == "QB", Pvec, Pvec * pk))) for c in FAM for pk in (1.0, 0.75)}
        e6 = cur.copy(); sched = {}
        for ps in ("RB", "WR", "TE"):
            for y in (YEARS[2:] if fwd else YEARS):
                tr = (pos == ps) & top150 & ev & ((year < y) if fwd else (year != y)); te = (pos == ps) & (year == y)
                if tr.sum() < 200 or not te.any(): continue
                best = min(cand6, key=lambda k: wm(cand6[k], tr)); e6[te] = cand6[best][te]; sched.setdefault(ps, []).append((best[0], best[1]))
        out["E6 smooth lam schedule"] = e6; lam_tab["_schedule (start, slope, floor), P mult"] = {k: [str(x) for x in v] for k, v in sched.items()}
        # E4: ridge per position x bucket on the rate (actual / layers)
        feats = ["prior", "ppg"] + USE + ["rt_std", "rt_l3"]; X = np.column_stack([prior, ppg] + [U[c] for c in USE] + [U["rt_std"], U["rt_l3"]])
        rate_t = act / np.maximum(layers, 0.3); e4 = cur.copy(); coefs = {}
        for ps in POS4:
            for b in range(len(BUCKETS)):
                for y in (YEARS[2:] if fwd else YEARS):
                    tr = (pos == ps) & (bk == b) & ev & ((year < y) if fwd else (year != y)); te = (pos == ps) & (bk == b) & (year == y) & ev
                    if tr.sum() < 120 or not te.any(): continue
                    med = np.nanmedian(X[tr], axis=0); med = np.where(np.isnan(med), 0, med)
                    Atr = np.where(np.isnan(X[tr]), med, X[tr]); Ate = np.where(np.isnan(X[te]), med, X[te]); mu, sd = Atr.mean(0), Atr.std(0); sd[sd == 0] = 1
                    mdl = Ridge(alpha=30.0).fit((Atr - mu) / sd, rate_t[tr], sample_weight=wt[tr]); e4[te] = finish(np.maximum(0.3, mdl.predict((Ate - mu) / sd)))[te] if False else e4[te]
                    rate = np.maximum(0.3, mdl.predict((Ate - mu) / sd)); tmp = np.zeros(n); tmp[te] = rate; e4[te] = finish(np.where(te, tmp, 1.0))[te]
                    if not fwd and y == YEARS[-1]: coefs[f"{ps} {BUCKETS[b][0]}"] = sorted([(feats[j], round(float(mdl.coef_[j]), 2)) for j in range(len(feats))], key=lambda kv: -abs(kv[1]))[:6]
        out["E4 learned usage model"] = e4; out["E5 0.5 E4 + 0.5 shadow"] = 0.5 * e4 + 0.5 * cur
        return out, lam_tab, coefs

    def report(preds, title, store, fm=None):
        cur = preds["shadow (ppg evidence)"]; P(f"\n=== {title}: importance-weighted top 150; cell = vs shadow (seasons won) | vs Clay ===")
        cuts = [(lab, top150 & (g >= a) & (g <= b)) for lab, a, b in BUCKETS] + [("ALL games 1+", top150 & (g >= 1)), ("ALL incl week 1", top150)]
        for nm, p in preds.items():
            cells = []
            for lab, m in cuts:
                mm = m & (fm if fm is not None else True); ys = sorted(set(year[mm]))
                wb = sum(1 for y in ys if wm(p, mm & (year == y)) < wm(cur, mm & (year == y))); wc = sum(1 for y in ys if wm(p, mm & (year == y)) < wm(ship, mm & (year == y)))
                row = {"model": nm, "cut": lab, "n": int(mm.sum()), "vsShadow": round((wm(p, mm) / wm(cur, mm) - 1) * 100, 2), "shadowWins": wb, "vsClay": round((wm(p, mm) / wm(ship, mm) - 1) * 100, 2), "clayWins": wc, "years": len(ys)}
                store.append(row); cells.append(f"{lab}: {row['vsShadow']:+.2f}% ({wb}/{len(ys)}) | {row['vsClay']:+.2f}% ({wc}/{len(ys)})")
            P(f"  {nm:26s} " + "  ||  ".join(cells))

    preds, lam_tab, coefs = build_all(False); report(preds, "LOYO learning curve by games played", RES["curve"])
    P("\n=== By position, games 1+ (top 150 weighted): vs shadow | vs Clay ===")
    cur = preds["shadow (ppg evidence)"]
    for ps in POS4:
        m = top150 & (pos == ps) & (g >= 1); cells = []
        for nm, p in preds.items():
            ys = sorted(set(year[m])); wb = sum(1 for y in ys if wm(p, m & (year == y)) < wm(cur, m & (year == y)))
            RES["byPos"].append({"pos": ps, "model": nm, "vsShadow": round((wm(p, m) / wm(cur, m) - 1) * 100, 2), "shadowWins": wb, "vsClay": round((wm(p, m) / wm(ship, m) - 1) * 100, 2), "years": len(ys)})
            cells.append(f"{nm.split(' ')[0]} {(wm(p, m)/wm(cur, m)-1)*100:+.2f}% ({wb}/{len(ys)}) | {(wm(p, m)/wm(ship, m)-1)*100:+.2f}%")
        P(f"  {ps}: " + "  ||  ".join(cells))
    P("\n  lam picks (weight on xFP/g, by position x games bucket, per held-out season): " + "; ".join(f"{k} {v}" for k, v in lam_tab.items()))
    P("  learned model, strongest standardized coefficients (last fold): " + " | ".join(f"{k}: " + ", ".join(f"{a} {b:+.2f}" for a, b in v) for k, v in list(coefs.items())[:12]))
    RES["lam"] = lam_tab; RES["coef"] = {k: v for k, v in coefs.items()}
    predsf, _, _ = build_all(True); report(predsf, "FORWARD 2021-25 (priors, lam and models from earlier seasons only)", RES["forward"], fm=(year >= YEARS[2]))
    a = [r for r in RES["curve"] if r["cut"] == "ALL games 1+"]; f = [r for r in RES["forward"] if r["cut"] == "ALL games 1+"]
    best = min([r for r in a if not r["model"].startswith("shadow")], key=lambda r: r["vsShadow"]); bf = [r for r in f if r["model"] == best["model"]][0]
    RES["summary"] = (f"Top 150, games 1+: best = {best['model']} {best['vsShadow']:+.2f}% vs the shadow ({best['shadowWins']}/{best['years']}), {best['vsClay']:+.2f}% vs Clay ({best['clayWins']}/{best['years']}); forward {bf['vsShadow']:+.2f}% ({bf['shadowWins']}/{bf['years']}), {bf['vsClay']:+.2f}% vs Clay.")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "inseason_usage.js"), "w", encoding="utf-8") as fh:
        fh.write("window.SIM_INSEASON_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/inseason_usage.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
