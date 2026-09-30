#!/usr/bin/env python3
"""
THE COMBINED LIVE CANDIDATE (2026-09-17). Jack: "lets build the combined live candidate".
Five fixes each passed alone and wait on Jack's go; they overlap, so here they are STACKED one at a time on today's live
pre-book number and graded as one decision:
  0  TODAY            Clay per-game prior, P = 5, points evidence, x Vegas x FPA                       (live now)
  1  + Vegas-adjusted evidence       each past game / its own Vegas multiplier                          (v2.24 form, today)
  2  + tiered Clay prior strength    QB16 / RB8 / WR12 / TE12 for ADP <= 60 only, 5 for the rest
  3  + backup-QB WR dock             WR x .85 (ADP <= 60) / .95 when the team's primary QB is out
  4  + shadow-side evidence rules    xFP usage evidence (RB / WR), WR one-game prior x5, QB game-total tilt = "fixed Clay side"
  5  70 / 30 shadow v2.24 + step 4   = LIVE CANDIDATE (no ESPN)
  6  50 / 50 step 5 + ESPN           = LIVE CANDIDATE + ESPN  (ESPN's number where it exists, else step 5)
Also: shadow v2.24 alone, ESPN alone, 50/50 shadow + ESPN (the rank mix).
Rules: final week dropped; top 150 importance-weighted error vs TODAY (seasons better of 7); typical miss vs ESPN on
ESPN-graded rows; weekly within-position rank rho + pairs; by stage (fantasy playoffs), ADP band, position.
Robustness: the same ladder with the shadow's learned season prior fitted FORWARD (earlier seasons only), 2021-25.
The live board then anchors 70% to the books where a line exists - that layer cannot be backtested and sits on top of either base.
Log live_candidate.log; results -> data/live_candidate.js (SIM_LIVECAND_BT).
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
import backtest_vs_espn as VE
cal = NW.cal
warnings.filterwarnings("ignore")

if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "live_candidate.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
YEARS, POS4 = NW.YEARS, NW.POS4
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "ladder": [], "cuts": [], "espn": [], "forward": []}


def main():
    t0 = time.time()
    P("=== The combined live candidate: five pending fixes stacked on today's live pre-book number ===")
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, clay, layers, adp, pid, name = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"], F["adp"], A["pid"], A["name"]
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, name)], dtype=float)
    W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay)
    T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]
    def ridge_rows(v): key = {(int(y), nm, ps): x for y, nm, ps, x in zip(T.year, T.name, T.pos, v)}; return np.array([key.get((year[i], name[i], pos[i]), np.nan) for i in range(n)])
    r_lo, r_fw = ridge_rows(SL.loyo(T, LIVE, "ridge", 10.0)), ridge_rows(SL.forward(T, LIVE, "ridge", 10.0))
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    def colv(c): return np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    xfp = colv("xfp_pg"); ev = has & (g >= 1) & ~np.isnan(xfp); xf = np.where(ev, xfp, ppg); veg = colv("veg")
    lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    gt = colv("game_total"); z = np.zeros(n)
    for y in YEARS:
        for w_ in range(1, 19):
            m = (year == y) & (wk == w_) & ~np.isnan(gt)
            if m.sum() > 20 and gt[m].std() > 0: z[m] = np.clip((gt[m] - gt[m].mean()) / gt[m].std(), -2.5, 2.5)
    qbo = colv("qb_out") == 1
    # ---- Vegas-adjusted points per game (v2.24) ----
    rowof = {(name[i], pos[i], int(year[i]), int(wk[i])): i for i in range(n)}; logs = {}; ppg_v = ppg.copy()
    for i in range(n):
        if g[i] < 1: continue
        k = (name[i], pos[i], int(year[i]))
        if k not in logs:
            wrec = cal.weekly_rec(name[i], pos[i]); logs[k] = sorted((int(w["wk"]), float(w["fpts"])) for w in (wrec or {}).get("seasons", {}).get(str(int(year[i])), []) if cal.played(w) and isinstance(w.get("fpts"), (int, float)))
        L = [x for x in logs[k] if x[0] < wk[i]]
        if not L: continue
        tot = 0.0
        for w_, p_ in L:
            ri = rowof.get((name[i], pos[i], int(year[i]), w_)); v = veg[ri] if ri is not None and not np.isnan(veg[ri]) else (layers[ri] if ri is not None else 1.0)   # week-1 rows have no context row: the matchup multiplier is ~all Vegas there
            tot += p_ / float(np.clip(v, 0.6, 1.6))
        raw = sum(p_ for _, p_ in L)
        if raw > 0: ppg_v[i] = ppg[i] * float(np.clip(tot / raw, 0.75, 1.35))
    P(f"  Vegas-adjusted evidence: rows moved {(np.abs(ppg_v - ppg) > 1e-9).sum():,} of {(g >= 1).sum():,}; mean abs change {np.mean(np.abs(ppg_v - ppg)[g >= 1]):.3f} pts/g")
    # ---- pieces ----
    def dock(p): return np.where((pos == "WR") & qbo, p * np.where(adp <= 60, 0.85, 0.95), p)
    def tilt(p): return np.where(pos == "QB", p * np.exp(0.03 * z), p)
    def finish(rate):
        out = rate * layers
        for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
        return np.where(F["on"], out * np.power(F["pm"], 0.75), out)
    Pfix = {"QB": 16.0, "RB": 8.0, "WR": 12.0, "TE": 12.0}; Ptier = np.where(adp <= 60, np.array([Pfix[p_] for p_ in pos]), 5.0); early = np.where((pos == "WR") & (g == 1), 5.0, 1.0)
    bl = lambda pr, evd, Pw: (Pw * pr + g * evd) / np.maximum(Pw + g, 1e-9)
    evid_v = lam * xf + (1 - lam) * ppg_v
    def build(ridge):
        prior = np.where(np.isnan(ridge) | (pos == "QB"), F["prior"], 0.5 * ridge + 0.5 * F["prior"])
        SH = dock(tilt(finish(bl(prior, evid_v, F["Pvec"] * early))))
        S0 = bl(clay_gm, ppg, 5.0) * layers; S1 = bl(clay_gm, ppg_v, 5.0) * layers; S2 = bl(clay_gm, ppg_v, Ptier) * layers; S3 = dock(S2)
        S4 = dock(tilt(bl(clay_gm, evid_v, Ptier * early) * layers)); S5 = 0.7 * SH + 0.3 * S4
        return SH, [("0 TODAY (live pre-book)", S0), ("1 + Vegas-adjusted evidence", S1), ("2 + tiered Clay prior (ADP <= 60)", S2), ("3 + backup-QB WR dock", S3), ("4 + usage / WR one-game / QB total", S4), ("5 LIVE CANDIDATE: 70/30 shadow + step 4", S5)]
    # ---- ESPN ----
    E = {}
    for Y in YEARS:
        d = json.load(open(os.path.join(VE.ESPN_DIR, f"espn_proj_{Y}.json"), encoding="utf-8"))
        for w_, rows in d["weeks"].items():
            for k, v in rows.items():
                nm, ps = k.rsplit("|", 1); E[(Y, int(w_), VE.nrm(nm), ps)] = VE.espn_half(v.get("s") or {})
    esp = np.array([E.get((int(year[i]), int(wk[i]), VE.nrm(name[i]), pos[i]), np.nan) for i in range(n)], dtype=float); ok = ~np.isnan(esp) & (esp > 0.5)
    # ---- grading ----
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; po = (wk >= finw - 3) & (wk < finw); top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    wm = lambda q, mm: float(np.average((q[mm] - act[mm]) ** 2, weights=wt[mm])); e = lambda q, mm: float(np.mean((q[mm] - act[mm]) ** 2))
    def rank_stats(p, m):
        groups = defaultdict(list)
        for i in np.where(m)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
        rh, pw, tot = [], 0, 0
        for ix in (np.array(x) for x in groups.values()):
            if len(ix) < 8: continue
            a, pv = act[ix], p[ix]; rh.append(np.corrcoef(rankdata(a), rankdata(pv))[0, 1])
            d = pv[:, None] - pv[None, :]; o = a[:, None] - a[None, :]; iu = np.triu_indices(len(ix), 1); okp = (d[iu] != 0) & (o[iu] != 0); pw += int(((d[iu] > 0) == (o[iu] > 0))[okp].sum()); tot += int(okp.sum())
        return float(np.mean(rh)), 100.0 * pw / max(1, tot)
    SH, LAD = build(r_lo); withE = lambda p: np.where(ok, 0.5 * p + 0.5 * esp, p)
    MODELS = LAD + [("6 LIVE CANDIDATE + ESPN (50/50)", withE(LAD[5][1])), ("shadow v2.24 alone", SH), ("rank mix: 50/50 shadow + ESPN", withE(SH)), ("ESPN alone (where it has a row)", np.where(ok, esp, LAD[0][1]))]
    S0 = LAD[0][1]; base = top150 & ~final
    P(f"\n=== LADDER, top 150, all weeks except the final week ({int(base.sum()):,} player-weeks): importance-weighted error vs TODAY (seasons better of 7) | step gain | rank rho | pairs right ===")
    prev = None
    for nm, p in MODELS:
        d = (wm(p, base) / wm(S0, base) - 1) * 100; wins = sum(1 for y in YEARS if wm(p, base & (year == y)) < wm(S0, base & (year == y)) - 1e-12); rh, pr = rank_stats(p, base)
        step = None if prev is None or not nm[0].isdigit() else round(d - prev, 2); prev = d if nm[0].isdigit() else prev
        RES["ladder"].append({"model": nm, "d": round(d, 2), "wins": wins, "step": step, "rho": round(rh, 4), "pairs": round(pr, 2), "rmse": round(float(np.sqrt(e(p, base))), 3)})
        P(f"  {nm:42s} {d:+6.2f}% ({wins}/7) | step {('%+.2f' % step) if step is not None else '   - '} | rho {rh:.4f} | pairs {pr:.2f}% | typical miss {np.sqrt(e(p, base)):.3f}")
    P("\n=== By cut (top 150, final week dropped): error vs TODAY (seasons better) and rank rho change ===")
    cuts = (("week 1", wk == 1), ("weeks 2-4", (wk >= 2) & (wk <= 4)), ("weeks 5-9", (wk >= 5) & (wk <= 9)), ("10 to playoffs", (wk >= 10) & ~po), ("FANTASY PLAYOFFS", po),
            ("ADP 1-30", adp <= 30), ("ADP 31-60", (adp > 30) & (adp <= 60)), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150", adp > 100), ("QB", pos == "QB"), ("RB", pos == "RB"), ("WR", pos == "WR"), ("TE", pos == "TE"))
    show = [MODELS[5], MODELS[6], MODELS[7], MODELS[8]]
    for lab, cm in cuts:
        m = base & cm; rh0, _ = rank_stats(S0, m); cells = []
        for nm, p in show:
            d = (wm(p, m) / wm(S0, m) - 1) * 100; wins = sum(1 for y in YEARS if wm(p, m & (year == y)) < wm(S0, m & (year == y)) - 1e-12); rh, _ = rank_stats(p, m)
            RES["cuts"].append({"cut": lab, "model": nm, "d": round(d, 2), "wins": wins, "drho": round(rh - rh0, 4)}); cells.append(f"{nm.split(':')[0][:28]} {d:+.2f}% ({wins}/7) rho {rh - rh0:+.4f}")
        P(f"  {lab:18s} " + " | ".join(cells))
    P("\n=== vs ESPN on ESPN-graded rows (top 150, final week dropped): typical miss, error vs ESPN (seasons better than ESPN), rank rho ===")
    for lab, cm in (("ALL", np.ones(n, bool)), ("FANTASY PLAYOFFS", po), ("ADP 1-60", adp <= 60)):
        m = base & ok & cm; cells = []
        for nm, p in [("ESPN", esp)] + MODELS[:1] + MODELS[5:9]:
            d = (e(p, m) / e(esp, m) - 1) * 100; wins = sum(1 for y in YEARS if e(p, m & (year == y)) < e(esp, m & (year == y)) - 1e-12); rh, pr = rank_stats(p, m)
            RES["espn"].append({"cut": lab, "model": nm, "rmse": round(float(np.sqrt(e(p, m))), 3), "vsEspn": round(d, 2), "wins": wins, "rho": round(rh, 4), "pairs": round(pr, 2)})
            cells.append(f"{nm.split(':')[0][:26]} {np.sqrt(e(p, m)):.2f} ({d:+.2f}%, {wins}/7) rho {rh:.4f}")
        P(f"  {lab:18s} n={int(m.sum()):5d} | " + " | ".join(cells))
    P("\n=== ROBUSTNESS: the same ladder with the shadow's learned season prior fitted on EARLIER seasons only, graded 2021-25 ===")
    SHf, LADf = build(r_fw); fm = base & (year >= 2021); S0f = LADf[0][1]; ys = [y for y in YEARS if y >= 2021]
    for nm, p in LADf + [("6 LIVE CANDIDATE + ESPN (50/50)", withE(LADf[5][1])), ("shadow v2.24 alone", SHf)]:
        d = (wm(p, fm) / wm(S0f, fm) - 1) * 100; wins = sum(1 for y in ys if wm(p, fm & (year == y)) < wm(S0f, fm & (year == y)) - 1e-12); rh, pr = rank_stats(p, fm)
        RES["forward"].append({"model": nm, "d": round(d, 2), "wins": wins, "rho": round(rh, 4), "pairs": round(pr, 2)}); P(f"  {nm:42s} {d:+6.2f}% ({wins}/5) | rho {rh:.4f} | pairs {pr:.2f}%")
    L = {r_["model"]: r_ for r_ in RES["ladder"]}; c5, c6 = L["5 LIVE CANDIDATE: 70/30 shadow + step 4"], L["6 LIVE CANDIDATE + ESPN (50/50)"]; t_ = L["0 TODAY (live pre-book)"]
    RES["summary"] = (f"Top 150, final week dropped, vs today's live pre-book number: LIVE CANDIDATE {c5['d']:+.2f}% ({c5['wins']}/7), rank rho {t_['rho']:.3f} -> {c5['rho']:.3f}, pairs {t_['pairs']:.2f}% -> {c5['pairs']:.2f}%; "
                      f"with ESPN mixed in {c6['d']:+.2f}% ({c6['wins']}/7), rho {c6['rho']:.3f}, pairs {c6['pairs']:.2f}%.")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "live_candidate.js"), "w", encoding="utf-8") as fh:
        fh.write("window.SIM_LIVECAND_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/live_candidate.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
