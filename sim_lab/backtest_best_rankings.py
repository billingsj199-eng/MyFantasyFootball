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
    pass
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
    top = ok & (adp <= 150); TOPN = {"QB": 12, "RB": 24, "WR": 24, "TE": 12}
    groups = defaultdict(list)
    for i in np.where(top)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
    groups = {k: np.array(v) for k, v in groups.items() if len(v) >= 8}
    def stats(p, years=None, positions=None, band=None):
        rho, pw, tot, hit, ndcg = [], 0, 0, [], []
        for (y, w_, ps), ix in groups.items():
            if (years is not None and y not in years) or (positions is not None and ps not in positions): continue
            if band is not None: ix = ix[band[ix]]
            if len(ix) < 6: continue
            a = act[ix]; pv = p[ix]; rho.append(np.corrcoef(rankdata(a), rankdata(pv))[0, 1])
            d = pv[:, None] - pv[None, :]; o = a[:, None] - a[None, :]; iu = np.triu_indices(len(ix), 1); okp = (d[iu] != 0) & (o[iu] != 0); pw += int(((d[iu] > 0) == (o[iu] > 0))[okp].sum()); tot += int(okp.sum())
            N = min(TOPN[ps], len(ix) // 2); hit.append(len(set(np.argsort(-a)[:N]) & set(np.argsort(-pv)[:N])) / N)
            # points captured by starting the projected top N vs the best possible top N (what ranking is FOR)
            ndcg.append(a[np.argsort(-pv)[:N]].sum() / max(1e-9, a[np.argsort(-a)[:N]].sum()))
        return float(np.mean(rho)), 100.0 * pw / max(1, tot), float(np.mean(hit)), float(np.mean(ndcg))
    OURS = B70
    CANDS = {"ESPN alone": esp, "Clay blend as it runs today": CUR, "Our shadow (Clay-free)": SH, "Our 70/30 blend (shadow + Clay)": B70,
             "75% ours + 25% ESPN": 0.75 * OURS + 0.25 * esp, "50% ours + 50% ESPN": 0.5 * OURS + 0.5 * esp, "25% ours + 75% ESPN": 0.25 * OURS + 0.75 * esp,
             "Three-way: 1/3 shadow, 1/3 Clay side, 1/3 ESPN": (SH + CL + esp) / 3.0, "50% shadow + 50% ESPN (no Clay at all)": 0.5 * SH + 0.5 * esp}
    # weight on ours chosen on the other six seasons by rank rho
    WG = [0.0, 0.25, 0.4, 0.5, 0.6, 0.75, 1.0]; per = {w_: {y: stats(w_ * OURS + (1 - w_) * esp, {y})[0] for y in YEARS} for w_ in WG}; picks = []; sel = np.zeros(n)
    for y in YEARS:
        best = max(WG, key=lambda w_: np.mean([per[w_][yy] for yy in YEARS if yy != y])); picks.append(best); te = year == y; sel[te] = best * OURS[te] + (1 - best) * esp[te]
    CANDS[f"ours + ESPN, weight picked each season {picks}"] = sel
    print("WEEKLY RANKING ACCURACY inside each position, top 150, 2019-25 (ESPN-graded rows). rho = rank correlation; pairs = same-position pairs ordered correctly;")
    print("top-N hit = share of the actual top 12 QB/TE, top 24 RB/WR the ranking had in its own top group; captured = points scored by the ranked top N as a share of the best possible top N")
    print(f"  {'ranking':58s} {'rho':>7s} {'seasons>ESPN':>13s} {'pairs':>8s} {'top-N hit':>10s} {'captured':>9s}")
    eY = {y: stats(esp, {y})[0] for y in YEARS}
    for nm, p in CANDS.items():
        r, pw_, h_, c_ = stats(p); wins = sum(1 for y in YEARS if stats(p, {y})[0] > eY[y] + 1e-12)
        print(f"  {nm:58s} {r:7.4f} {wins:>11d}/7 {pw_:7.2f}% {h_:10.4f} {c_*100:8.2f}%")
    BEST = 0.5 * OURS + 0.5 * esp
    print("\nBy position (rho): ESPN | Clay today | our 70/30 | 50/50 ours+ESPN")
    for ps in POS4: print(f"  {ps}: {stats(esp, None, {ps})[0]:.4f} | {stats(CUR, None, {ps})[0]:.4f} | {stats(B70, None, {ps})[0]:.4f} | {stats(BEST, None, {ps})[0]:.4f}   pairs {stats(esp, None, {ps})[1]:.2f}% | {stats(CUR, None, {ps})[1]:.2f}% | {stats(B70, None, {ps})[1]:.2f}% | {stats(BEST, None, {ps})[1]:.2f}%")
    print("\nBy ADP band (pairs ordered correctly, both players inside the band): ESPN | Clay today | our 70/30 | 50/50 ours+ESPN")
    for lab, bm in (("ADP 1-30", adp <= 30), ("ADP 31-60", (adp > 30) & (adp <= 60)), ("ADP 1-60", adp <= 60), ("ADP 61-100", (adp > 60) & (adp <= 100)), ("ADP 101-150", (adp > 100) & (adp <= 150))):
        print(f"  {lab:12s} {stats(esp, None, None, bm)[1]:.2f}% | {stats(CUR, None, None, bm)[1]:.2f}% | {stats(B70, None, None, bm)[1]:.2f}% | {stats(BEST, None, None, bm)[1]:.2f}%   rho {stats(esp, None, None, bm)[0]:.4f} | {stats(CUR, None, None, bm)[0]:.4f} | {stats(B70, None, None, bm)[0]:.4f} | {stats(BEST, None, None, bm)[0]:.4f}")
    print("\nBy part of the season (rho): ESPN | Clay today | our 70/30 | 50/50 ours+ESPN")
    for lab, a_, b_ in (("week 1", 1, 1), ("weeks 2-4", 2, 4), ("weeks 5-9", 5, 9), ("weeks 10-14", 10, 14), ("weeks 15-18", 15, 18)):
        gg = {k: v for k, v in groups.items() if a_ <= k[1] <= b_}; save = dict(groups); groups.clear(); groups.update(gg)
        print(f"  {lab:12s} {stats(esp)[0]:.4f} | {stats(CUR)[0]:.4f} | {stats(B70)[0]:.4f} | {stats(BEST)[0]:.4f}"); groups.clear(); groups.update(save)


if __name__ == "__main__":
    main()
