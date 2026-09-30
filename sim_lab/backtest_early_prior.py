#!/usr/bin/env python3
"""
EARLY-SEASON PRIOR: is the shadow over-reacting to the first few games? (2026-09-17)

Jack: "test the early-season prior". Finding that prompted it: against its own FROZEN preseason number the shadow's
in-season updates ordered same-position pairs correctly only 49.0% of the time in weeks 2-4 (53-56% later), and after
one game the weighted MSE was +1.1% WORSE than not updating. The blend is  (P x prior + g x evidence) / (P + g)  with
P = QB 12 / RB 5 / WR 8 / TE 8, so after one game the evidence already carries 1/13 (QB) to 1/6 (RB) of the number.
Families, per position, on the v2.18 shadow (usage evidence for RB / WR):
  delay d        g_eff = max(0, g - d),  d in 0 / .5 / 1 / 1.5 / 2 / 3     (evidence only counts after d games)
  early boost    P x m while g <= G0,    m in 1.5 / 2 / 3 / 5, G0 in 1 / 2 / 3
  taper          P x (1 + b x exp(-(g-1)/1.5)),  b in 0.5 / 1 / 2 / 4          (smooth version of the boost)
Selection leave-one-season-out per position on the top-150 importance-weighted MSE, reported on the weekly RANK
objective (mean within-position-week Spearman, pairs ordered correctly) and MSE, by games played; then forward.
Log early_prior.log; results -> data/early_prior.js (SIM_EARLYPRIOR_BT).
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
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "early_prior.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
YEARS, POS4 = NW.YEARS, NW.POS4
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "diag": [], "byPos": [], "stages": [], "forward": []}
STAGES = (("1 game", 1, 1), ("2 games", 2, 2), ("3 games", 3, 3), ("4-5 games", 4, 5), ("6+ games", 6, 99), ("games 1-3", 1, 3), ("ALL (incl week 1)", 0, 99))


def main():
    t0 = time.time()
    P("=== Early-season prior: delay / early boost / taper on the prior strength, per position ===")
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, clay, layers, adp, pid = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"], F["adp"], A["pid"]
    ch = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, A["name"])], dtype=float)
    W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay); ship = NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers
    T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    xfp = np.where(has, C["xfp_pg"].values[np.maximum(idx, 0)], np.nan).astype(float); ev = has & (g >= 1) & ~np.isnan(xfp); xf = np.where(ev, xfp, ppg)
    lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0)); evid = lam * xf + (1 - lam) * ppg
    def prior_of(fwd):
        lo = (SL.forward if fwd else SL.loyo)(T, LIVE, "ridge", 10.0); key = {(int(y), nm, ps): v for y, nm, ps, v in zip(T.year, T.name, T.pos, lo)}
        r = np.array([key.get((year[i], A["name"][i], pos[i]), np.nan) for i in range(n)]); return np.where(np.isnan(r) | (pos == "QB"), F["prior"], 0.5 * r + 0.5 * F["prior"])
    PRI = {False: prior_of(False), True: prior_of(True)}; Pv = F["Pvec"]
    def finish(rate):
        out = rate * layers
        for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
        return np.where(F["on"], out * np.power(F["pm"], 0.75), out)
    def model(prior, kind, a, b=None):
        if kind == "delay": ge = np.maximum(0.0, g - a); Pe = Pv
        elif kind == "boost": ge = g.astype(float); Pe = np.where(g <= b, Pv * a, Pv)
        else: ge = g.astype(float); Pe = Pv * (1 + a * np.exp(-np.maximum(g - 1, 0) / 1.5))
        return finish((Pe * prior + ge * evid) / (Pe + ge))
    CANDS = [("delay", 0.0, None)] + [("delay", d, None) for d in (0.5, 1.0, 1.5, 2.0, 3.0)] + [("boost", m, G0) for m in (1.5, 2.0, 3.0, 5.0) for G0 in (1, 2, 3)] + [("taper", b_, None) for b_ in (0.5, 1.0, 2.0, 4.0)]
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & (adp <= 150)].mean()
    wt = np.maximum(0.05, lv) ** 2; top150 = adp <= 150
    groups = defaultdict(list)
    for i in np.where(top150)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
    groups = {k: np.array(v) for k, v in groups.items() if len(v) >= 8}
    def wm(p, m): return float(np.average((p[m] - act[m]) ** 2, weights=wt[m])) if m.sum() else np.nan
    def rank_stats(pred, ps, years, glo=0, ghi=99):
        rho, pw, tot = [], 0, 0
        for (y, w, p_), ix in groups.items():
            if p_ != ps or y not in years: continue
            ix = ix[(g[ix] >= glo) & (g[ix] <= ghi)]
            if len(ix) < 8: continue
            a = act[ix]; pv = pred[ix]; rho.append(np.corrcoef(rankdata(a), rankdata(pv))[0, 1]); d = pv[:, None] - pv[None, :]; o = a[:, None] - a[None, :]; iu = np.triu_indices(len(ix), 1); ok = (d[iu] != 0) & (o[iu] != 0)
            pw += int(((d[iu] > 0) == (o[iu] > 0))[ok].sum()); tot += int(ok.sum())
        return (float(np.mean(rho)) if rho else np.nan), (100.0 * pw / tot if tot else np.nan)
    # ---- diagnostic: current blend vs the frozen prior vs Clay, by games played ----
    cur = model(PRI[False], "delay", 0.0); frozen = finish(PRI[False])
    P("\n=== Diagnostic (top 150, weighted MSE): the current shadow vs its frozen prior and vs the Clay blend, by games played ===")
    for lab, a, b in STAGES[:5]:
        m = top150 & (g >= a) & (g <= b); r = {"stage": lab, "n": int(m.sum()), "vsFrozen": round((wm(cur, m) / wm(frozen, m) - 1) * 100, 2), "vsClay": round((wm(cur, m) / wm(ship, m) - 1) * 100, 2)}; RES["diag"].append(r)
        P(f"  {lab:10s} n={m.sum():5d} | shadow vs frozen prior {r['vsFrozen']:+6.2f}% | shadow vs Clay blend {r['vsClay']:+6.2f}%")
    for ps in POS4:
        m = top150 & (pos == ps) & (g >= 1) & (g <= 3); P(f"    {ps} games 1-3: shadow vs frozen {(wm(cur, m)/wm(frozen, m)-1)*100:+.2f}% | rank rho shadow {rank_stats(cur, ps, set(YEARS), 1, 3)[0]:.4f} vs frozen {rank_stats(frozen, ps, set(YEARS), 1, 3)[0]:.4f}")
    # ---- per-position selection ----
    def run(fwd):
        prior = PRI[fwd]; base = model(prior, "delay", 0.0); preds = {c: model(prior, *c) for c in CANDS}; out = base.copy(); picks = {}
        ys = YEARS[2:] if fwd else YEARS
        for ps in POS4:
            picks[ps] = []
            for y in ys:
                tr = top150 & (pos == ps) & ((year < y) if fwd else (year != y)); te = (pos == ps) & (year == y)
                best = min(CANDS, key=lambda c: wm(preds[c], tr)); picks[ps].append(best); out[te] = preds[best][te]
        return base, out, picks, preds
    base, sel, picks, preds = run(False)
    P("\n=== LOYO selection per position (chosen on weighted top-150 MSE); picks by held-out season ===")
    for ps in POS4: P(f"  {ps}: " + ", ".join(f"{k}{'' if b is None else '@g<=' + str(b)} {a:g}" for (k, a, b) in picks[ps]))
    def report(base, sel, store, title, ys, fm):
        P(f"\n=== {title}: selected early-prior vs the current shadow; cell = weighted MSE change (seasons better) | rank rho change | pairs pts | vs Clay ===")
        for ps in list(POS4) + ["ALL"]:
            cells = []
            for lab, a, b in STAGES:
                m = top150 & (g >= a) & (g <= b) & fm & ((pos == ps) if ps != "ALL" else True)
                if m.sum() < 60: continue
                wins = sum(1 for y in ys if wm(sel, m & (year == y)) < wm(base, m & (year == y)) - 1e-12)
                if ps != "ALL": r1, p1 = rank_stats(sel, ps, set(ys), a, b); r0, p0 = rank_stats(base, ps, set(ys), a, b)
                else:
                    rr = [(rank_stats(sel, q, set(ys), a, b), rank_stats(base, q, set(ys), a, b)) for q in POS4]; r1, p1 = np.nanmean([x[0][0] for x in rr]), np.nanmean([x[0][1] for x in rr]); r0, p0 = np.nanmean([x[1][0] for x in rr]), np.nanmean([x[1][1] for x in rr])
                row = {"pos": ps, "stage": lab, "n": int(m.sum()), "mse": round((wm(sel, m) / wm(base, m) - 1) * 100, 2), "wins": wins, "years": len(ys), "dRho": round(float(r1 - r0), 4), "dPair": round(float(p1 - p0), 2), "vsClay": round((wm(sel, m) / wm(ship, m) - 1) * 100, 2), "baseVsClay": round((wm(base, m) / wm(ship, m) - 1) * 100, 2)}
                store.append(row); cells.append(f"{lab}: {row['mse']:+.2f}% ({wins}/{len(ys)}) rho {row['dRho']:+.4f} pairs {row['dPair']:+.2f} | Clay {row['vsClay']:+.2f}% (was {row['baseVsClay']:+.2f}%)")
            P(f"  {ps:3s} " + "  ||  ".join(cells))
    report(base, sel, RES["stages"], "LOYO", YEARS, np.ones(n, bool))
    # fixed candidates for transparency (no selection), games 1-3, all positions pooled and by position
    P("\n=== Every candidate at FIXED settings, games 1-3, top 150 (weighted MSE vs current | seasons better) by position ===")
    for c in CANDS[1:]:
        lab = f"{c[0]}{'' if c[2] is None else ' g<=' + str(c[2])} {c[1]:g}"; cells = []
        for ps in POS4:
            m = top150 & (pos == ps) & (g >= 1) & (g <= 3); wins = sum(1 for y in YEARS if wm(preds[c], m & (year == y)) < wm(base, m & (year == y)))
            m6 = top150 & (pos == ps) & (g >= 4); cells.append(f"{ps} {(wm(preds[c], m)/wm(base, m)-1)*100:+.2f}% ({wins}/7), games 4+ {(wm(preds[c], m6)/wm(base, m6)-1)*100:+.2f}%")
            RES["byPos"].append({"cand": lab, "pos": ps, "early": round((wm(preds[c], m) / wm(base, m) - 1) * 100, 2), "wins": wins, "late": round((wm(preds[c], m6) / wm(base, m6) - 1) * 100, 2)})
        P(f"  {lab:18s} " + " | ".join(cells))
    P("=== WR ONLY, fixed settings (no selection), by stage: weighted MSE vs current (seasons better) | rank rho | pairs; LOYO prior then FORWARD prior ===")
    RES["wrFixed"] = []
    for fwd in (False, True):
        prior = PRI[fwd]; b0 = model(prior, "delay", 0.0); ys = YEARS[2:] if fwd else YEARS; fmask = (year >= YEARS[2]) if fwd else np.ones(n, bool)
        for c in (("boost", 2.0, 1), ("boost", 3.0, 1), ("boost", 5.0, 1), ("delay", 0.5, None), ("delay", 1.0, None)):
            pr = model(prior, *c); lab = ("FWD " if fwd else "LOYO ") + c[0] + ("" if c[2] is None else " g<=" + str(c[2])) + " " + str(c[1]); cells = []
            for sl, a, b in STAGES:
                m = top150 & (pos == "WR") & (g >= a) & (g <= b) & fmask; wins = sum(1 for y in ys if wm(pr, m & (year == y)) < wm(b0, m & (year == y)) - 1e-12)
                r1, p1 = rank_stats(pr, "WR", set(ys), a, b); r0, p0 = rank_stats(b0, "WR", set(ys), a, b)
                row = {"cand": lab, "stage": sl, "mse": round((wm(pr, m) / wm(b0, m) - 1) * 100, 2), "wins": wins, "years": len(ys), "dRho": round(float(r1 - r0), 4), "dPair": round(float(p1 - p0), 2), "vsClay": round((wm(pr, m) / wm(ship, m) - 1) * 100, 2)}
                RES["wrFixed"].append(row); cells.append(sl + ": " + format(row["mse"], "+.2f") + "% (" + str(wins) + "/" + str(len(ys)) + ") rho " + format(row["dRho"], "+.4f") + " pairs " + format(row["dPair"], "+.2f"))
            P("  " + lab.ljust(22) + " " + "  ||  ".join(cells))
    basef, self_, picksf, _ = run(True)
    P("\n  forward picks: " + " | ".join(f"{ps}: " + ", ".join(f"{k}{'' if b is None else '@g<=' + str(b)} {a:g}" for (k, a, b) in picksf[ps]) for ps in POS4))
    report(basef, self_, RES["forward"], "FORWARD 2021-25", YEARS[2:], year >= YEARS[2])
    RES["picks"] = {ps: [list(map(lambda v: v if v is not None else "", c)) for c in picks[ps]] for ps in POS4}
    a13 = [r for r in RES["stages"] if r["pos"] == "ALL" and r["stage"] == "games 1-3"][0]; aall = [r for r in RES["stages"] if r["pos"] == "ALL" and r["stage"].startswith("ALL")][0]
    f13 = [r for r in RES["forward"] if r["pos"] == "ALL" and r["stage"] == "games 1-3"][0]; fall = [r for r in RES["forward"] if r["pos"] == "ALL" and r["stage"].startswith("ALL")][0]
    RES["summary"] = (f"Early-season prior, top 150: games 1-3 {a13['mse']:+.2f}% MSE ({a13['wins']}/7), rank {a13['dRho']:+.4f}; all weeks {aall['mse']:+.2f}% ({aall['wins']}/7), rank {aall['dRho']:+.4f}. "
                      f"Forward: games 1-3 {f13['mse']:+.2f}% ({f13['wins']}/5), rank {f13['dRho']:+.4f}; all weeks {fall['mse']:+.2f}% ({fall['wins']}/5).")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "early_prior.js"), "w", encoding="utf-8") as fh:
        fh.write("window.SIM_EARLYPRIOR_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/early_prior.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
