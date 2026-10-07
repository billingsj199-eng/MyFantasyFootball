#!/usr/bin/env python3
"""
BOX COUNT FACED (Jack 2026-10-07 evening: "test the box count on the participation data").  The FTN screen's one lead:
WR / TE on offenses that see heavy boxes out-produce the blended number (1 + .04 z: -0.64%, 4/4 on 2022-25). Here the
same rate comes from nflverse pbp_participation 2019-25 (defenders_in_box on every charted play, number_of_pass_rushers,
was_pressure), so it meets the seven-season bar.  Team season to date (weeks before this one, 2+ team games):
   box      average defenders in the box on run + pass plays       rushers   average pass rushers on dropbacks
   pressure share of dropbacks under pressure                         box_run  box on run plays only (what the run game sees)
Base = blended number as wired (QB/RB/WR .7, TE .3 shadow). Spearman and quintiles by position; multipliers 1 + e x z
(sign from the correlation) for WR/TE, RB, QB; LOYO + forward; ship bar 5/7 + 3/4, whole-board guard. Log box_context.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
SN = BR.SN; NW = BR.NW; cal = NW.cal; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
CACHE = r"E:\MyFantasyFootball\pbp_cache"
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "box_context.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
TM_ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI"}
BBW = {"QB": 0.7, "RB": 0.7, "WR": 0.7, "TE": 0.3}


def load():
    team = defaultdict(lambda: np.zeros(7))   # (Y, team, wk): [plays with box, box sum, run plays with box, run box sum, dropbacks with rushers, rushers sum, pressures]
    for Y in YEARS:
        part = pd.read_parquet(os.path.join(CACHE, f"pbp_participation_{Y}.parquet"), columns=["nflverse_game_id", "play_id", "possession_team", "defenders_in_box", "number_of_pass_rushers", "was_pressure"])
        p = pd.read_csv(os.path.join(CACHE, f"play_by_play_{Y}.csv.gz"), compression="gzip", usecols=["game_id", "play_id", "week", "posteam", "season_type", "play_type", "qb_dropback"], low_memory=False)
        p = p[(p.season_type == "REG") & p.posteam.notna() & p.play_type.isin(["pass", "run"])]
        d = p.merge(part, left_on=["game_id", "play_id"], right_on=["nflverse_game_id", "play_id"], how="inner")
        d["tm"] = d.posteam.map(lambda t: TM_ALIAS.get(str(t), str(t)))
        for (tm, wk), g in d.groupby(["tm", "week"]):
            b = g[g.defenders_in_box.notna()]; br = b[b.play_type == "run"]; db = g[(g.qb_dropback == 1) & g.number_of_pass_rushers.notna()]
            pr = g[(g.qb_dropback == 1) & g.was_pressure.notna()]
            team[(Y, tm, int(wk))] += np.array([len(b), b.defenders_in_box.sum(), len(br), br.defenders_in_box.sum(), len(db), db.number_of_pass_rushers.sum(), pr.was_pressure.astype(float).sum()], dtype=float)
        P(f"  {Y}: {len(d):,} plays joined")
    return team


def main():
    team_wk = load()
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
    MET = ("box", "box_run", "rushers", "pressure"); M = {k: np.full(n, np.nan) for k in MET}
    for i in np.where(ok)[0]:
        Y = int(year[i]); rows = [team_wk[(Y, team[i], w)] for w in range(1, int(wk[i])) if (Y, team[i], w) in team_wk]
        if len(rows) < 2: continue
        a = np.sum(rows, axis=0)
        if a[0] >= 40: M["box"][i] = a[1] / a[0]
        if a[2] >= 20: M["box_run"][i] = a[3] / a[2]
        if a[4] >= 30: M["rushers"][i] = a[5] / a[4]; M["pressure"][i] = a[6] / a[4]
    Z = {}
    for k in MET:
        z = np.full(n, np.nan)
        for y in YEARS:
            for w in range(1, 19):
                m = ok & (year == y) & (wk == w) & ~np.isnan(M[k])
                if m.sum() >= 20 and np.nanstd(M[k][m]) > 0: z[m] = np.clip((M[k][m] - np.nanmean(M[k][m])) / np.nanstd(M[k][m]), -2.5, 2.5)
        Z[k] = z
    ratio = np.where(BASE > 0, act / BASE, np.nan)
    P(f"\n=== BOX COUNT FACED: {int(ok.sum()):,} top-150 player-weeks 2019-25 (participation data), base = blended number as wired ===")
    P("\n--- 1  Spearman of actual / base with each metric's within-week z, and quintiles low -> high ---")
    for k in MET:
        for grp, gm in (("WR+TE", np.isin(pos, ("WR", "TE"))), ("WR", pos == "WR"), ("TE", pos == "TE"), ("RB", pos == "RB"), ("QB", pos == "QB")):
            m = ok & gm & ~np.isnan(Z[k])
            if m.sum() < 200: continue
            r = spearmanr(Z[k][m], ratio[m]).correlation; q = np.nanpercentile(Z[k][m], [20, 40, 60, 80]); e = [-9] + list(q) + [9]
            cells = [f"{act[m & (Z[k] >= e[a]) & (Z[k] < e[a+1])].sum()/BASE[m & (Z[k] >= e[a]) & (Z[k] < e[a+1])].sum():.3f}" for a in range(5)]
            P(f"    {k:9s} {grp:5s} rho {r:+.3f} n{int(m.sum()):5d} | quintiles {' '.join(cells)} | metric {np.nanmean(M[k][m & (Z[k] < e[1])]):.2f} -> {np.nanmean(M[k][m & (Z[k] >= e[4])]):.2f}")
    P("\n--- 2  multipliers 1 + e x z (sign from the correlation), LOYO + forward; ship bar 5/7 + 3/4, whole-board guard ---")
    wm = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    for k in MET:
        for grp, gm in (("WR+TE", np.isin(pos, ("WR", "TE"))), ("WR", pos == "WR"), ("TE", pos == "TE"), ("RB", pos == "RB"), ("QB", pos == "QB")):
            m = ok & gm & ~np.isnan(Z[k])
            if m.sum() < 200: continue
            r = spearmanr(Z[k][m], ratio[m]).correlation; sgn = 1.0 if r > 0 else -1.0
            preds = {"off": BASE}
            for e_ in (0.01, 0.02, 0.03, 0.04, 0.06): p = BASE.copy(); p[m] = BASE[m] * np.clip(1 + sgn * e_ * Z[k][m], 0.85, 1.15); preds[f"e {e_}"] = p
            names = list(preds); pick = lambda yrs: min(names, key=lambda kk: wm(preds[kk], m & np.isin(year, yrs)))
            def run(folds):
                wins = 0; picks = []; pr = BASE.copy()
                for tr_, te in folds:
                    kk = pick(tr_); picks.append(kk); mm = year == te; pr[mm] = preds[kk][mm]; wins += wm(preds[kk], m & mm) < wm(BASE, m & mm) - 1e-12
                tem = np.isin(year, [te for _, te in folds]); return 100 * (wm(pr, m & tem) / wm(BASE, m & tem) - 1), 100 * (wm(pr, ok & tem) / wm(BASE, ok & tem) - 1), wins, picks
            lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
            fixed = "  ".join(f"{kk}: {100*(wm(preds[kk], m)/wm(BASE, m)-1):+.2f}% ({sum(1 for y in YEARS if wm(preds[kk], m & (year == y)) < wm(BASE, m & (year == y)) - 1e-12)}/7)" for kk in names[1:])
            okk = best != "off" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
            P(f"\n  {k} {grp} (rho {r:+.3f}, sign {'+' if sgn > 0 else '-'}, rows {int(m.sum()):,})")
            P(f"    fixed: {fixed}")
            pb = preds[best]
            P(f"    best {best}: ADP<=60 {100*(wm(pb, m & (adpx <= 60))/wm(BASE, m & (adpx <= 60))-1):+.2f}% | 61-150 {100*(wm(pb, m & (adpx > 60))/wm(BASE, m & (adpx > 60))-1):+.2f}% | weeks 3-6 {100*(wm(pb, m & (wk <= 6))/wm(BASE, m & (wk <= 6))-1):+.2f}% | 7+ {100*(wm(pb, m & (wk >= 7))/wm(BASE, m & (wk >= 7))-1):+.2f}% | by season " + " ".join(f"{y}:{100*(wm(pb, m & (year == y))/wm(BASE, m & (year == y))-1):+.1f}" for y in YEARS))
            P(f"    LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | picks {lo[3]}")
            P(f"    FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}")
            P(f"    -> {'PASS: ' + best if okk else 'FAIL'}")
    P("\nLimitations: participation box / rusher counts exist on ~74% of plays 2019-24 (100% 2025); team rates season to date, 2+ team games; the blended base already carries Vegas, FPA and the shadow's context; prop anchor / docks not replayed.")
    LOG.close()


if __name__ == "__main__":
    main()
