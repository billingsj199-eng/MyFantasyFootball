#!/usr/bin/env python3
"""
HOW DO WE DO HISTORICALLY AGAINST ESPN'S WEEKLY PROJECTIONS? (2026-09-17)

Jack: "is it possible to see how we do historically vs a fantasy site like espn" / "build the ESPN comparison".
ESPN side: pbp_cache/espn_proj/espn_proj_<year>.json (pull_espn_hist_proj.py) - the projection ESPN showed for each
past week, as a projected STAT LINE, rescored here to the harness scoring (half-PPR: .04 pass yd, 4 pass TD, -1 INT,
.1 rush / rec yd, 6 rush / rec TD, .5 reception, -2 fumble lost - fitted from weekly_stats_active, median residual .03).
Our side, on the same player-weeks (2019-25 weekly harness, walk-forward):
  Clay blend as it runs today | shadow v2.21 (Clay-free) | 70/30 blend (shadow + tiered Clay side)
Rows = harness player-weeks (the player played) that ESPN projected above zero; zero / missing ESPN rows are counted
and reported separately (a zero usually means ESPN had him out or on bye and he played).
FAIRNESS NOTE: ESPN's stored number is its final pre-kickoff projection, so it already knows the week's inactives and
injury news; ours uses closing Vegas lines and known absences but no beat-writer news. That favours ESPN.
Graded by non-overlapping ADP band (Jack's priority: the top players), position, part of season, by season; points
error, weekly rank inside position, start/sit pairs where we disagree with ESPN, level bias; and whether ESPN adds
information on top of ours (a 50/50 of the 70/30 blend with ESPN).
Log vs_espn.log; results -> data/vs_espn.js (SIM_VS_ESPN_BT).
"""
import json, os, re, sys, time, warnings
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
    sys.stdout = NW._Tee(sys.stdout, open(os.path.join(HERE, "vs_espn.log"), "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))
YEARS, POS4 = NW.YEARS, NW.POS4
ESPN_DIR = r"E:\MyFantasyFootball\pbp_cache\espn_proj"
RES = {"updated": time.strftime("%Y-%m-%d %H:%M"), "coverage": {}, "overall": [], "bands": [], "pos": [], "stage": [], "season": [], "pairs": [], "bias": [], "info": []}


def nrm(s):
    s = str(s).lower().replace(".", "").replace("'", "").replace("-", " "); s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s); return re.sub(r"\s+", " ", s).strip()


def espn_half(s):
    g = lambda k: float(s.get(k, 0) or 0)
    return 0.04 * g("3") + 4 * g("4") - 1 * g("20") + 0.1 * g("24") + 6 * g("25") + 0.1 * g("42") + 6 * g("43") + 0.5 * g("53") - 2 * g("72")


def main():
    t0 = time.time()
    P("=== Us vs ESPN's weekly projections, 2019-25, same player-weeks, half-PPR ===")
    F = CS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, ppg, clay, layers, adp, pid = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"], F["adp"], A["pid"]
    ch = json.load(open(os.path.join(NW.cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, A["name"])], dtype=float)
    W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay)
    T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]; lo = SL.loyo(T, LIVE, "ridge", 10.0)
    key = {(int(y), nm, ps): v for y, nm, ps, v in zip(T.year, T.name, T.pos, lo)}; r = np.array([key.get((year[i], A["name"][i], pos[i]), np.nan) for i in range(n)])
    prior = np.where(np.isnan(r) | (pos == "QB"), F["prior"], 0.5 * r + 0.5 * F["prior"])
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
    qbo = colv("qb_out") == 1
    def extras(p): p = np.where(pos == "QB", p * np.exp(0.03 * z), p); return np.where((pos == "WR") & qbo, p * np.where(adp <= 60, 0.85, 0.95), p)
    def finish(rate):
        out = rate * layers
        for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
        return np.where(F["on"], out * np.power(F["pm"], 0.75), out)
    PW = np.where((pos == "WR") & (g == 1), F["Pvec"] * 5, F["Pvec"]); SH = extras(finish(NW.blend(prior, g, evid, PW)))
    CUR = NW.blend(clay_gm, g, ppg, NW.PRIOR_P) * layers
    Pfix = {"QB": 16.0, "RB": 8.0, "WR": 12.0, "TE": 12.0}; Pcl = np.where(adp <= 60, np.array([Pfix[p_] for p_ in pos]), 5.0) * np.where((pos == "WR") & (g == 1), 5.0, 1.0)
    CL = extras((Pcl * clay_gm + g * evid) / (Pcl + g) * layers); B70 = 0.7 * SH + 0.3 * CL
    # ---- ESPN ----
    E = {}
    for Y in YEARS:
        f = os.path.join(ESPN_DIR, f"espn_proj_{Y}.json")
        if not os.path.exists(f): P(f"  MISSING {f}"); continue
        d = json.load(open(f, encoding="utf-8"))
        for w_, rows in d["weeks"].items():
            for k, v in rows.items():
                nm, ps = k.rsplit("|", 1); E[(Y, int(w_), nrm(nm), ps)] = (espn_half(v.get("s") or {}), v.get("ppr"))
    esp = np.full(n, np.nan); esp_ppr = np.full(n, np.nan)
    for i in range(n):
        v = E.get((int(year[i]), int(wk[i]), nrm(A["name"][i]), pos[i]))
        if v: esp[i], esp_ppr[i] = v
    matched = ~np.isnan(esp); zero = matched & (esp <= 0.5); ok = matched & ~zero
    RES["coverage"] = {"rows": int(n), "matched": int(matched.sum()), "espnZero": int(zero.sum()), "used": int(ok.sum()), "top150used": int((ok & (adp <= 150)).sum())}
    P(f"  harness player-weeks {n} | ESPN row found {matched.sum()} ({matched.mean()*100:.1f}%) | ESPN projected ~0 for a player who played {zero.sum()} | graded {ok.sum()} (top 150: {(ok & (adp <= 150)).sum()})")
    P("  by season graded: " + " ".join(f"{y}:{int((ok & (year == y)).sum())}" for y in YEARS))
    P(f"  sanity: ESPN half-PPR rescored vs its own PPR total (should sit a bit below): mean {np.nanmean(esp[ok]):.2f} vs {np.nanmean(esp_ppr[ok]):.2f}")
    MODELS = {"ESPN": esp, "Clay blend today": CUR, "shadow v2.21 (Clay-free)": SH, "70/30 blend": B70}
    e = lambda q, mm: float(np.mean((q[mm] - act[mm]) ** 2))
    def row(label, m, store):
        m = m & ok
        if m.sum() < 80: return
        out = {"cut": label, "n": int(m.sum())}; cells = []
        for nm, p in MODELS.items():
            ys = [y for y in YEARS if (m & (year == y)).sum() >= 15]; wins = sum(1 for y in ys if e(p, m & (year == y)) < e(esp, m & (year == y)) - 1e-12)
            out[nm] = {"rmse": round(float(np.sqrt(e(p, m))), 3), "vsEspn": round((e(p, m) / e(esp, m) - 1) * 100, 2), "wins": wins, "years": len(ys)}
            cells.append(f"{nm} {np.sqrt(e(p, m)):5.2f}" + ("" if nm == "ESPN" else f" ({out[nm]['vsEspn']:+.2f}%, {wins}/{len(ys)})"))
        store.append(out); P(f"  {label:22s} n={m.sum():5d} | " + " | ".join(cells))
    P("\n=== Typical miss (RMSE, half-PPR points); in brackets: error vs ESPN (negative = better than ESPN), seasons better than ESPN ===")
    row("ALL graded rows", np.ones(n, bool), RES["overall"]); row("TOP 150", adp <= 150, RES["overall"])
    P(" -- by ADP band")
    for lab, bm in (("ADP 1-30", adp <= 30), ("ADP 31-60", (adp > 30) & (adp <= 60)), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150", (adp > 100) & (adp <= 150)), ("ADP 151+ / undrafted", ~(adp <= 150))): row(lab, bm, RES["bands"])
    P(" -- by position (top 150)")
    for ps in POS4: row(ps, (adp <= 150) & (pos == ps), RES["pos"])
    P(" -- by part of the season (top 150)")
    for lab, sm in (("week 1", wk == 1), ("weeks 2-4", (wk >= 2) & (wk <= 4)), ("weeks 5-9", (wk >= 5) & (wk <= 9)), ("weeks 10-14", (wk >= 10) & (wk <= 14)), ("weeks 15-18", wk >= 15)): row(lab, (adp <= 150) & sm, RES["stage"])
    P(" -- by season (top 150)")
    for y in YEARS: row(str(y), (adp <= 150) & (year == y), RES["season"])
    # ---- rank + pairs ----
    top = ok & (adp <= 150); groups = defaultdict(list)
    for i in np.where(top)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
    groups = {k: np.array(v) for k, v in groups.items() if len(v) >= 8}
    P("\n=== Weekly ranking inside each position (top 150, ESPN-graded rows): mean Spearman and pairs ordered correctly ===")
    for nm, p in MODELS.items():
        rho, pw, tot = [], 0, 0; per = defaultdict(list)
        for (y, w_, ps), ix in groups.items():
            a = act[ix]; pv = p[ix]; c = np.corrcoef(rankdata(a), rankdata(pv))[0, 1]; rho.append(c); per[y].append(c)
            d = pv[:, None] - pv[None, :]; o = a[:, None] - a[None, :]; iu = np.triu_indices(len(ix), 1); okp = (d[iu] != 0) & (o[iu] != 0); pw += int(((d[iu] > 0) == (o[iu] > 0))[okp].sum()); tot += int(okp.sum())
        MODELS_R = {"model": nm, "rho": round(float(np.mean(rho)), 4), "pairs": round(100.0 * pw / tot, 2), "bySeason": {int(y): round(float(np.mean(v)), 4) for y, v in per.items()}}; RES["pairs"].append(MODELS_R)
        P(f"  {nm:26s} rank rho {MODELS_R['rho']:.4f} | pairs right {MODELS_R['pairs']:.2f}% | by season " + " ".join(f"{y}:{v:.3f}" for y, v in sorted(MODELS_R['bySeason'].items())))
    P("\n=== Start/sit pairs where we and ESPN order two same-position players differently: who was right ===")
    for nm in ("Clay blend today", "shadow v2.21 (Clay-free)", "70/30 blend"):
        p = MODELS[nm]
        for lab, bm in (("top 150", adp <= 150), ("ADP 1-60", adp <= 60), ("ADP 61-150", (adp > 60) & (adp <= 150))):
            w_ = t_ = 0; ys = defaultdict(lambda: [0, 0])
            for (y, wk_, ps), ix in groups.items():
                ix = ix[bm[ix]]
                if len(ix) < 3: continue
                a = act[ix]; da = p[ix][:, None] - p[ix][None, :]; db = esp[ix][:, None] - esp[ix][None, :]; o = a[:, None] - a[None, :]; iu = np.triu_indices(len(ix), 1)
                dis = (np.sign(da[iu]) != np.sign(db[iu])) & (da[iu] != 0) & (db[iu] != 0) & (o[iu] != 0); c = int(((da[iu] > 0) == (o[iu] > 0))[dis].sum()); w_ += c; t_ += int(dis.sum()); ys[y][0] += c; ys[y][1] += int(dis.sum())
            sw = sum(1 for v in ys.values() if v[1] and v[0] / v[1] > 0.5); RES["pairs"].append({"model": nm, "cut": lab, "right": round(100.0 * w_ / max(1, t_), 2), "n": t_, "seasons": sw})
            P(f"  {nm:26s} {lab:10s} we were right {100.0*w_/max(1,t_):5.2f}% of {t_:6,d} disagreements | seasons above 50%: {sw}/7")
    P("\n=== Level: average projection vs actual (top 150, graded rows) ===")
    for lab, bm in (("ADP 1-30", adp <= 30), ("ADP 31-60", (adp > 30) & (adp <= 60)), ("ADP 61-150", (adp > 60) & (adp <= 150))):
        m = bm & ok; b = {"cut": lab, "actual": round(float(act[m].mean()), 2)}
        for nm, p in MODELS.items(): b[nm] = round(float(p[m].mean()), 2)
        RES["bias"].append(b); P(f"  {lab:10s} actual {b['actual']:5.2f} | " + " | ".join(f"{nm} {b[nm]:5.2f} ({(b[nm]/b['actual']-1)*100:+.1f}%)" for nm in MODELS))
    P("\n=== Does ESPN know something we do not? blends with ESPN (top 150; error vs ESPN alone, seasons better) ===")
    m = top
    for lab, p in (("70/30 blend alone", B70), ("0.75 ours + 0.25 ESPN", 0.75 * B70 + 0.25 * esp), ("0.5 ours + 0.5 ESPN", 0.5 * B70 + 0.5 * esp), ("0.25 ours + 0.75 ESPN", 0.25 * B70 + 0.75 * esp), ("0.5 Clay today + 0.5 ESPN", 0.5 * CUR + 0.5 * esp)):
        wins = sum(1 for y in YEARS if e(p, m & (year == y)) < e(esp, m & (year == y))); RES["info"].append({"mix": lab, "vsEspn": round((e(p, m) / e(esp, m) - 1) * 100, 2), "wins": wins})
        P(f"  {lab:26s} {(e(p, m)/e(esp, m)-1)*100:+6.2f}% ({wins}/7) | typical miss {np.sqrt(e(p, m)):.3f}")
    o = RES["overall"][1]
    RES["summary"] = (f"Top 150, {o['n']} player-weeks 2019-25, typical miss: ESPN {o['ESPN']['rmse']:.2f}, Clay blend today {o['Clay blend today']['rmse']:.2f} ({o['Clay blend today']['vsEspn']:+.1f}% error vs ESPN, {o['Clay blend today']['wins']}/7 seasons), "
                      f"shadow {o['shadow v2.21 (Clay-free)']['rmse']:.2f} ({o['shadow v2.21 (Clay-free)']['vsEspn']:+.1f}%, {o['shadow v2.21 (Clay-free)']['wins']}/7), 70/30 blend {o['70/30 blend']['rmse']:.2f} ({o['70/30 blend']['vsEspn']:+.1f}%, {o['70/30 blend']['wins']}/7).")
    P("\n" + RES["summary"])
    with open(os.path.join(HERE, "data", "vs_espn.js"), "w", encoding="utf-8") as fh:
        fh.write("window.SIM_VS_ESPN_BT = " + json.dumps(RES) + ";\n")
    P(f"wrote data/vs_espn.js ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
