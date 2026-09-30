#!/usr/bin/env python3
"""
FANTASY-PLAYOFF WEEKS (2026-09-17). Jack: "dont worry about the final week of every season usually fantasy seasons are
over but the weeks besides last historically are very important as its fantasy playoffs".
Final week = 17 (2019-20) / 18 (2021+): dropped from every grade here. Playoffs = the three weeks before it.
  1. Regrade by stage with the final week out: ESPN, Clay blend today, shadow, 70/30 blend, rank mix (50 shadow + 50 ESPN).
  2. Diagnose the playoff weeks (top 150): position, ADP band, level bias, players who missed time, hot / cold finish.
  3. Late-season fixes on the shadow's evidence (no fitted parameters; graded by season): in-season decayed PPG
     (half-life 3 / 5 / 8 games), last-4 blend, lighter prior late. Graded in the playoffs and over all non-final weeks.
Log fantasy_playoffs.log; results -> data/fantasy_playoffs.js (SIM_FPLAYOFF_BT).
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
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "fantasy_playoffs.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
YEARS, POS4 = NW.YEARS, NW.POS4
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "stage": [], "diag": [], "fix": []}


def main():
    t0 = time.time()
    P("=== Fantasy-playoff weeks: final week dropped, weeks before it graded on their own ===")
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, clay, layers, adp, pid = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"], F["adp"], A["pid"]
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, A["name"])], dtype=float)
    W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay)
    T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]; lo = SL.loyo(T, LIVE, "ridge", 10.0)
    key = {(int(y), nm, ps): v for y, nm, ps, v in zip(T.year, T.name, T.pos, lo)}; r = np.array([key.get((year[i], A["name"][i], pos[i]), np.nan) for i in range(n)])
    prior = np.where(np.isnan(r) | (pos == "QB"), F["prior"], 0.5 * r + 0.5 * F["prior"])
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    def colv(c): return np.where(has, C[c].values[np.maximum(idx, 0)], np.nan).astype(float)
    xfp = colv("xfp_pg"); ev = has & (g >= 1) & ~np.isnan(xfp); xf = np.where(ev, xfp, ppg)
    lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    gt = colv("game_total"); z = np.zeros(n)
    for y in YEARS:
        for w_ in range(1, 19):
            m = (year == y) & (wk == w_) & ~np.isnan(gt)
            if m.sum() > 20 and gt[m].std() > 0: z[m] = np.clip((gt[m] - gt[m].mean()) / gt[m].std(), -2.5, 2.5)
    qbo = colv("qb_out") == 1
    def extras(p): p = np.where(pos == "QB", p * np.exp(0.03 * z), p); return np.where((pos == "WR") & qbo, p * np.where(adp <= 60, 0.85, 0.95), p)
    def finish(rate):
        out = rate * layers
        for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
        return np.where(F["on"], out * np.power(F["pm"], 0.75), out)
    PW = np.where((pos == "WR") & (g == 1), F["Pvec"] * 5, F["Pvec"])
    def shadow(points_ev, Pw=PW): return extras(finish(NW.blend(prior, g, lam * xf + (1 - lam) * points_ev, Pw)))
    SH = shadow(ppg); CUR = NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers
    Pfix = {"QB": 16.0, "RB": 8.0, "WR": 12.0, "TE": 12.0}; Pcl = np.where(adp <= 60, np.array([Pfix[p_] for p_ in pos]), 5.0) * np.where((pos == "WR") & (g == 1), 5.0, 1.0)
    CL = extras((Pcl * clay_gm + g * (lam * xf + (1 - lam) * ppg)) / (Pcl + g) * layers); B70 = 0.7 * SH + 0.3 * CL
    # ESPN
    E = {}
    for Y in YEARS:
        d = json.load(open(os.path.join(VE.ESPN_DIR, f"espn_proj_{Y}.json"), encoding="utf-8"))
        for w_, rows in d["weeks"].items():
            for k, v in rows.items():
                nm, ps = k.rsplit("|", 1); E[(Y, int(w_), VE.nrm(nm), ps)] = VE.espn_half(v.get("s") or {})
    esp = np.array([E.get((int(year[i]), int(wk[i]), VE.nrm(A["name"][i]), pos[i]), np.nan) for i in range(n)], dtype=float); ok = ~np.isnan(esp) & (esp > 0.5)
    MIX = 0.5 * SH + 0.5 * np.where(ok, esp, SH)
    # ---- stage masks ----
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; po = (wk >= finw - 3) & (wk < finw); top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    e = lambda q, mm: float(np.mean((q[mm] - act[mm]) ** 2)); wm = lambda q, mm: float(np.average((q[mm] - act[mm]) ** 2, weights=wt[mm]))
    def rho(p, m):
        groups = defaultdict(list)
        for i in np.where(m)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
        v = [np.corrcoef(rankdata(act[ix]), rankdata(p[ix]))[0, 1] for ix in (np.array(x) for x in groups.values()) if len(ix) >= 8]
        return float(np.mean(v)) if v else np.nan
    MODELS = {"ESPN": esp, "Clay blend today": CUR, "shadow": SH, "70/30 blend": B70, "rank mix (shadow + ESPN)": MIX}
    P(f"  rows {n} | final-week rows dropped {int(final.sum())} | playoff-week rows {int(po.sum())} (top 150 with an ESPN row: {int((po & top150 & ok).sum())})")
    P("\n=== 1. By stage, top 150, ESPN-graded rows: typical miss (error vs ESPN, seasons better than ESPN) | weekly rank rho ===")
    stages = (("ALL non-final weeks", ~final), ("week 1", wk == 1), ("weeks 2-4", (wk >= 2) & (wk <= 4)), ("weeks 5-9", (wk >= 5) & (wk <= 9)), ("weeks 10 to playoffs", (wk >= 10) & ~po & ~final), ("FANTASY PLAYOFFS", po), ("final week (ignored)", final))
    for lab, sm in stages:
        m = sm & top150 & ok; out = {"stage": lab, "n": int(m.sum())}; cells = []
        for nm, p in MODELS.items():
            ys = [y for y in YEARS if (m & (year == y)).sum() >= 15]; wins = sum(1 for y in ys if e(p, m & (year == y)) < e(esp, m & (year == y)) - 1e-12)
            out[nm] = {"rmse": round(float(np.sqrt(e(p, m))), 3), "vsEspn": round((e(p, m) / e(esp, m) - 1) * 100, 2), "wins": wins, "years": len(ys), "rho": round(rho(p, m), 4)}
            cells.append(f"{nm} {np.sqrt(e(p, m)):.2f}" + ("" if nm == "ESPN" else f" ({out[nm]['vsEspn']:+.2f}%, {wins}/{len(ys)})") + f" rho {out[nm]['rho']:.3f}")
        RES["stage"].append(out); P(f"  {lab:22s} n={m.sum():5d} | " + " | ".join(cells))
    # ---- 2. diagnosis ----
    P("\n=== 2. Playoff weeks, top 150: where does the shadow lose to ESPN? (error vs ESPN; mean projection vs actual) ===")
    weeks_el = wk - 1; missed = weeks_el - g - 1   # a bye is normal
    seasons = {}
    def game_log(i):
        k = (A["name"][i], pos[i], int(year[i]))
        if k not in seasons:
            wrec = cal.weekly_rec(A["name"][i], pos[i]); seasons[k] = sorted((int(w["wk"]), float(w["fpts"])) for w in (wrec or {}).get("seasons", {}).get(str(int(year[i])), []) if cal.played(w) and isinstance(w.get("fpts"), (int, float)))
        return [p_ for w_, p_ in seasons[k] if w_ < wk[i]]
    logs = [game_log(i) for i in range(n)]
    def dec(pts, hl):
        if not pts: return np.nan
        a = np.array(pts); k = np.arange(len(a))[::-1]; w_ = 0.5 ** (k / hl); return float(np.sum(w_ * a) / np.sum(w_))
    l4 = np.array([np.mean(x[-4:]) if len(x) >= 4 else np.nan for x in logs]); myppg = np.array([np.mean(x) if x else np.nan for x in logs])
    mm = ~np.isnan(myppg) & (g >= 1); P(f"  sanity: my game-log PPG vs the harness PPG corr {np.corrcoef(myppg[mm], ppg[mm])[0,1]:.4f}, mean abs diff {np.mean(np.abs(myppg[mm]-ppg[mm])):.3f}")
    hot = l4 - ppg
    cuts = [("all", np.ones(n, bool))] + [(ps, pos == ps) for ps in POS4] + [("ADP 1-30", adp <= 30), ("ADP 31-60", (adp > 30) & (adp <= 60)), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150", (adp > 100) & (adp <= 150)),
            ("missed 0-1 games", missed <= 1), ("missed 2-4", (missed >= 2) & (missed <= 4)), ("missed 5+", missed >= 5),
            ("last 4 HOT (+3 vs season)", hot >= 3), ("last 4 near season", np.abs(hot) < 3), ("last 4 COLD (-3)", hot <= -3),
            ("Questionable / Doubtful", (colv("rep_q") == 1) | (colv("rep_d") == 1)), ("team implied < 19", colv("implied") < 19), ("team implied 24+", colv("implied") >= 24)]
    for lab, cm in cuts:
        m = cm & po & top150 & ok
        if m.sum() < 60: continue
        d = {"cut": lab, "n": int(m.sum()), "shVsEspn": round((e(SH, m) / e(esp, m) - 1) * 100, 2), "act": round(float(act[m].mean()), 2), "sh": round(float(SH[m].mean()), 2), "espn": round(float(esp[m].mean()), 2), "clay": round(float(CUR[m].mean()), 2)}
        RES["diag"].append(d); P(f"  {lab:28s} n={d['n']:5d} | shadow vs ESPN {d['shVsEspn']:+6.2f}% | actual {d['act']:5.2f} | shadow {d['sh']:5.2f} | ESPN {d['espn']:5.2f} | Clay blend {d['clay']:5.2f}")
    # ---- 3. fixes ----
    P("\n=== 3. Late-season evidence fixes on the shadow (no fitted parameters): importance-weighted top-150 error vs the shadow (seasons better) | rank rho ===")
    V = {"shadow (today)": SH}
    for hl in (3, 5, 8):
        dk = np.array([dec(x, hl) for x in logs]); V[f"in-season decayed PPG, half-life {hl} (6+ games)"] = shadow(np.where((g >= 6) & ~np.isnan(dk), dk, ppg))
    for a_ in (0.2, 0.4): V[f"{a_} x last 4 + {1-a_:.1f} x season PPG (6+ games)"] = shadow(np.where((g >= 6) & ~np.isnan(l4), a_ * l4 + (1 - a_) * ppg, ppg))
    for s_ in (0.5, 0.0): V[f"prior weight x{s_} after 10 games"] = shadow(ppg, np.where(g >= 10, PW * s_, PW))
    V["prior weight x2 after 10 games"] = shadow(ppg, np.where(g >= 10, PW * 2, PW))
    for nm, p in V.items():
        row = {"variant": nm}; cells = []
        for lab, sm in (("playoffs", po), ("weeks 10+ (no final)", (wk >= 10) & ~final), ("all non-final", ~final)):
            m = sm & top150; d = (wm(p, m) / wm(SH, m) - 1) * 100; wins = sum(1 for y in YEARS if wm(p, m & (year == y)) < wm(SH, m & (year == y)) - 1e-12); rr = rho(p, m)
            row[lab] = {"d": round(d, 2), "wins": wins, "rho": round(rr, 4)}; cells.append(f"{lab}: {d:+.2f}% ({wins}/7) rho {rr:.4f}")
        RES["fix"].append(row); P(f"  {nm:52s} " + " | ".join(cells))
    P("=== 4. ASYMMETRIC recency: only a COLD last 4 moves the evidence (hot streaks untouched). Found in the playoff cut, so weeks 5-9 and 10-to-playoffs are the out-of-cut check ===")
    RES["asym"] = []; cold = np.where((g >= 6) & ~np.isnan(l4), np.minimum(0.0, l4 - ppg), 0.0); hotv = np.where((g >= 6) & ~np.isnan(l4), np.maximum(0.0, l4 - ppg), 0.0)
    V4 = {}
    for a_ in (0.25, 0.5, 0.75): V4[f"cold only, weight {a_}"] = shadow(ppg + a_ * cold)
    for thr in (2.0, 3.0): V4[f"cold only beyond -{thr:.0f}, weight 0.5"] = shadow(ppg + 0.5 * np.minimum(0.0, cold + thr))
    V4["cold 0.5 AND hot 0.5 (symmetric, for contrast)"] = shadow(ppg + 0.5 * cold + 0.5 * hotv)
    qt = (pos == "QB") | (pos == "TE")
    for a_ in (0.25, 0.5): V4[f"cold only, QB + TE only, weight {a_}"] = shadow(ppg + a_ * np.where(qt, cold, 0.0))
    V4["cold only, RB + WR only, weight 0.25"] = shadow(ppg + 0.25 * np.where(~qt, cold, 0.0))
    V4["hot only, weight 0.5 (contrast)"] = shadow(ppg + 0.5 * hotv)
    for nm, p in V4.items():
        row = {"variant": nm}; cells = []
        for lab, sm in (("weeks 5-9", (wk >= 5) & (wk <= 9)), ("10 to playoffs", (wk >= 10) & ~po & ~final), ("playoffs", po), ("all non-final", ~final)):
            m = sm & top150; d = (wm(p, m) / wm(SH, m) - 1) * 100; wins = sum(1 for y in YEARS if wm(p, m & (year == y)) < wm(SH, m & (year == y)) - 1e-12); rr = rho(p, m) - rho(SH, m)
            row[lab] = {"d": round(d, 2), "wins": wins, "drho": round(rr, 4)}; cells.append(f"{lab}: {d:+.2f}% ({wins}/7) rho {rr:+.4f}")
        mE = po & top150 & ok; row["poVsEspn"] = round((e(p, mE) / e(esp, mE) - 1) * 100, 2)
        RES["asym"].append(row); P(f"  {nm:48s} " + " | ".join(cells) + f" | playoffs vs ESPN {row['poVsEspn']:+.2f}%")
    P("  cold players by position (playoffs + weeks 10+, top 150, last 4 at least 3 below season): actual vs shadow")
    for ps in POS4:
        m = (pos == ps) & top150 & (wk >= 10) & ~final & (hot <= -3); P(f"    {ps}: n={m.sum():4d} actual {act[m].mean():5.2f} | shadow {SH[m].mean():5.2f} | season PPG {ppg[m].mean():5.2f} | last 4 {l4[m].mean():5.2f} | snap share last game vs season {np.nanmean(colv('snap_l1')[m]):.3f} / {np.nanmean(colv('snap_std')[m]):.3f}")
    s = {r_["stage"]: r_ for r_ in RES["stage"]}; a_, p_ = s["ALL non-final weeks"], s["FANTASY PLAYOFFS"]
    RES["summary"] = (f"Final week dropped, top 150: shadow vs ESPN {a_['shadow']['vsEspn']:+.2f}% ({a_['shadow']['wins']}/7), 70/30 blend {a_['70/30 blend']['vsEspn']:+.2f}%, rank mix {a_['rank mix (shadow + ESPN)']['vsEspn']:+.2f}% ({a_['rank mix (shadow + ESPN)']['wins']}/7). "
                      f"Fantasy playoffs: shadow {p_['shadow']['vsEspn']:+.2f}% ({p_['shadow']['wins']}/7), Clay blend today {p_['Clay blend today']['vsEspn']:+.2f}%, rank mix {p_['rank mix (shadow + ESPN)']['vsEspn']:+.2f}% ({p_['rank mix (shadow + ESPN)']['wins']}/7); rank rho shadow {p_['shadow']['rho']:.3f} / ESPN {p_['ESPN']['rho']:.3f} / mix {p_['rank mix (shadow + ESPN)']['rho']:.3f}.")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "fantasy_playoffs.js"), "w", encoding="utf-8") as fh:
        fh.write("window.SIM_FPLAYOFF_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/fantasy_playoffs.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
