#!/usr/bin/env python3
"""
QB PRESSURE PROXY + BOX LAYER SCOPE (Jack 2026-10-07 late: "run both").
  1  Pressure rate faced (participation was_pressure) passed for QBs (1 - .03 z: -0.39% 5/7, fwd 3/4) but has no in-season
     source. Proxy from the play-by-play: (sacks + QB hits) / dropbacks, season to date. Checks: team-week correlation with the
     real pressure rate; the same multiplier test on the proxy for QBs (and WR/TE/RB for the record).
  2  Box layer scope: the WR/TE box multiplier (1 + .04 z) helped ADP <= 60 and hurt 61-150. Variants: all rows (wired), ADP <= 60
     only, ADP <= 100 only; graded on all WR/TE rows and the whole board.
Base = blended number as wired (QB/RB/WR .7, TE .3). 2019-25, LOYO + forward, bar 5/7 + 3/4. Log pressure_proxy.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import spearmanr, pearsonr
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import backtest_box_context as BX
SN = BR.SN; NW = BR.NW; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
CACHE = r"E:\MyFantasyFootball\pbp_cache"
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "pressure_proxy.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
TM_ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI"}
BBW = {"QB": 0.7, "RB": 0.7, "WR": 0.7, "TE": 0.3}


def load_proxy():
    team = defaultdict(lambda: np.zeros(3))   # (Y, team, wk): [dropbacks, sacks, hits]
    for Y in YEARS:
        p = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), compression="gzip", usecols=["week", "posteam", "season_type", "qb_dropback", "sack", "qb_hit"], low_memory=False)
        p = p[(p.season_type == "REG") & p.posteam.notna() & (p.qb_dropback == 1)]
        for (tm, wk), g in p.groupby(["posteam", "week"]):
            team[(Y, TM_ALIAS.get(str(tm), str(tm)), int(wk))] += np.array([len(g), g.sack.fillna(0).sum(), g.qb_hit.fillna(0).sum()], dtype=float)
    return team


def main():
    prox = load_proxy(); part = BX.load()
    # team-week agreement: proxy vs real pressure rate (both season to date are averages; compare per team-week raw rates)
    xs, ys = [], []
    for k, a in part.items():
        if k in prox and a[4] >= 15 and prox[k][0] >= 15: xs.append((prox[k][1] + prox[k][2]) / prox[k][0]); ys.append(a[6] / a[4])
    P(f"proxy vs real pressure rate, {len(xs):,} team-weeks: pearson {pearsonr(xs, ys)[0]:.3f}, spearman {spearmanr(xs, ys).correlation:.3f}; mean proxy {np.mean(xs):.3f} vs real {np.mean(ys):.3f}")
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["team"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    bw = np.array([BBW[p_] for p_ in pos]); BASE = bw * SHADOW + (1 - bw) * TODAY
    ok = (g >= 1) & ~final & ~LV["inh"] & top150 & (BASE >= 3)
    def std_rate(tw, idx_num, idx_den, min_den, combine=None):
        M = np.full(n, np.nan)
        for i in np.where(ok)[0]:
            Y = int(year[i]); rows = [tw[(Y, team[i], w)] for w in range(1, int(wk[i])) if (Y, team[i], w) in tw]
            if len(rows) < 2: continue
            a = np.sum(rows, axis=0)
            if a[idx_den] >= min_den: M[i] = (combine(a) if combine else a[idx_num]) / a[idx_den]
        return M
    def zof(M, grp):
        z = np.full(n, np.nan)
        for y in YEARS:
            for w in range(1, 19):
                m = ok & (year == y) & (wk == w) & ~np.isnan(M)   # team-level metric: z across every position's rows that week (QB groups alone are under 20)
                if m.sum() >= 20 and np.nanstd(M[m]) > 0: z[m] = np.clip((M[m] - np.nanmean(M[m])) / np.nanstd(M[m]), -2.5, 2.5)
        return z
    wm = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    def test(title, preds, m, rows_lab="rows"):
        names = list(preds); b0 = preds["off"]; pick = lambda yrs: min(names, key=lambda kk: wm(preds[kk], m & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = b0.copy()
            for tr_, te in folds:
                kk = pick(tr_); picks.append(kk); mm = year == te; pr[mm] = preds[kk][mm]; wins += wm(preds[kk], m & mm) < wm(b0, m & mm) - 1e-12
            tem = np.isin(year, [te for _, te in folds]); return 100 * (wm(pr, m & tem) / wm(b0, m & tem) - 1), 100 * (wm(pr, ok & tem) / wm(b0, ok & tem) - 1), wins, picks
        lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
        fixed = "  ".join(f"{kk}: {100*(wm(preds[kk], m)/wm(b0, m)-1):+.2f}% ({sum(1 for y in YEARS if wm(preds[kk], m & (year == y)) < wm(b0, m & (year == y)) - 1e-12)}/7)" for kk in names[1:])
        okk = best != "off" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
        P(f"\n  {title} ({rows_lab} {int(m.sum()):,})"); P(f"    fixed: {fixed}")
        pb = preds[best]
        P(f"    best {best}: ADP<=60 {100*(wm(pb, m & (adpx <= 60))/wm(b0, m & (adpx <= 60))-1):+.2f}% | 61-150 {100*(wm(pb, m & (adpx > 60))/wm(b0, m & (adpx > 60))-1):+.2f}% | by season " + " ".join(f"{y}:{100*(wm(pb, m & (year == y))/wm(b0, m & (year == y))-1):+.1f}" for y in YEARS))
        P(f"    LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | picks {lo[3]}"); P(f"    FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}"); P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
        return best
    # ---------------- 1  pressure proxy
    P("\n=== 1  QB PRESSURE PROXY: (sacks + QB hits) / dropbacks faced, season to date ===")
    Mp = std_rate(prox, None, 0, 30, combine=lambda a: a[1] + a[2]); Mr = std_rate(part, 6, 4, 30)
    m_both = ok & ~np.isnan(Mp) & ~np.isnan(Mr); P(f"    row-level agreement with the real rate (season to date): spearman {spearmanr(Mp[m_both], Mr[m_both]).correlation:.3f} on {int(m_both.sum()):,} rows")
    ratio = np.where(BASE > 0, act / BASE, np.nan)
    for grp_lab, grp in (("QB", pos == "QB"), ("WR+TE", np.isin(pos, ("WR", "TE"))), ("RB", pos == "RB")):
        z = zof(Mp, grp); m = ok & grp & ~np.isnan(z)
        r = spearmanr(z[m], ratio[m]).correlation; q = np.nanpercentile(z[m], [20, 40, 60, 80]); e = [-9] + list(q) + [9]
        P(f"    {grp_lab}: rho {r:+.3f} n{int(m.sum())} | quintiles " + " ".join(f"{act[m & (z >= e[a]) & (z < e[a+1])].sum()/BASE[m & (z >= e[a]) & (z < e[a+1])].sum():.3f}" for a in range(5)))
        preds = {"off": BASE}
        for e_ in (0.01, 0.02, 0.03, 0.04): p = BASE.copy(); p[m] = BASE[m] * np.clip(1 - e_ * z[m], 0.85, 1.15); preds[f"e {e_}"] = p
        test(f"proxy pressure, {grp_lab}, 1 - e z", preds, m)
    # the real rate again for reference on the same rows (QB)
    zr = zof(Mr, pos == "QB"); m = ok & (pos == "QB") & ~np.isnan(zr); preds = {"off": BASE}
    for e_ in (0.02, 0.03): p = BASE.copy(); p[m] = BASE[m] * np.clip(1 - e_ * zr[m], 0.85, 1.15); preds[f"e {e_}"] = p
    test("reference: REAL pressure rate (participation), QB", preds, m)
    # ---------------- 2  box scope
    P("\n=== 2  BOX LAYER SCOPE (WR + TE, 1 + .04 z(box faced)) ===")
    Mb = std_rate(part, 1, 0, 40); RECV = np.isin(pos, ("WR", "TE")); zb = zof(Mb, RECV); mb = ok & RECV & ~np.isnan(zb)
    def boxed(scope, e_=0.04):
        p = BASE.copy(); mm = mb & scope; p[mm] = BASE[mm] * np.clip(1 + e_ * zb[mm], 0.85, 1.15); return p
    preds = {"off": BASE, "all WR/TE (wired)": boxed(np.ones(n, bool)), "ADP <= 60 only": boxed(adpx <= 60), "ADP <= 100 only": boxed(adpx <= 100), "all, e .03": boxed(np.ones(n, bool), 0.03), "ADP <= 60 e .06": boxed(adpx <= 60, 0.06)}
    test("box scope, graded on ALL WR/TE rows", preds, mb)
    test("box scope, graded on ADP <= 60 WR/TE rows", preds, mb & (adpx <= 60))
    test("box scope, graded on ADP 61-150 WR/TE rows", preds, mb & (adpx > 60))
    P("\nLimitations: proxy counts sacks + hits only (no hurries); team rates season to date, 2+ team games; blended base, pre-book.")
    LOG.close()


if __name__ == "__main__":
    main()
