#!/usr/bin/env python3
"""
RATING THE SITUATION BY QB ANALYTICS (Jack 2026-10-07: "is there any correlation with cpoe maybe by qb or any other
analytics we can use to kind of rate situation").  RESEARCH.

For every WR / TE player-week 2019-25 (and QBs for reference), the expected starting QB's season-to-date analytics from
the nflverse play-by-play (weeks before this one; prior season if under 60 attempts):
   CPOE, EPA per dropback, success rate, aDOT, sack rate, attempts per game; plus the team's pass attempts per game.
Questions: (1) does the live number's miss (actual - projection) correlate with any of them? (2) bucketed by quintile
within the week, what is actual / live? (3) as a multiplier 1 + e x z on the live number, does any pass LOYO + forward?
(4) the same for the receiver's own current-season production - is the QB's quality already in his points?
Log qb_situation.log.
"""
import os, sys, re, warnings
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_qb_injury_usage as QI
NW = QI.NW; cal = QI.cal; YEARS = QI.YEARS; POS4 = QI.POS4; FWD = QI.FWD
CACHE = r"E:\MyFantasyFootball\pbp_cache"
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "qb_situation.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
TM_ALIAS = {"LA": "LAR", "OAK": "LV", "SD": "LAC", "STL": "LAR", "WSH": "WAS", "JAC": "JAX", "ARZ": "ARI"}
def abbrev(nm):
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\.?$", "", nm.strip(), flags=re.I).strip(); parts = n.replace(".", "").split()
    return (parts[0][0] + "." + "".join(parts[1:])).lower().replace("'", "") if len(parts) >= 2 else n.lower()


def load_pbp(years):
    qb = defaultdict(lambda: np.zeros(8))   # (Y, passer) -> list of weekly rows; we keep per (Y, passer, wk): [att, air, cpoe_sum, n_cpoe, epa_sum, db, sacks, success]
    rows = defaultdict(dict); team = defaultdict(lambda: np.zeros(3))   # (Y, team, wk): [pass att, plays, dropbacks]
    for Y in years:
        p = os.path.join(CACHE, f"play_by_play_{Y}.csv.gz")
        if not os.path.exists(p): continue
        d = pd.read_csv(p, compression="gzip", usecols=["week", "posteam", "pass_attempt", "air_yards", "cpoe", "epa", "passer_player_name", "season_type", "qb_dropback", "sack", "success", "play_type"], low_memory=False)
        d = d[(d.season_type == "REG") & d.posteam.notna()]
        pl = d[d.play_type.isin(["pass", "run"])]
        for (tm, wk), grp in pl.groupby(["posteam", "week"]):
            t = team[(Y, TM_ALIAS.get(str(tm), str(tm)), int(wk))]; t[0] += grp.pass_attempt.sum(); t[1] += len(grp); t[2] += grp.qb_dropback.sum()
        db = d[(d.qb_dropback == 1) & d.passer_player_name.notna()]
        for (pn, wk), grp in db.groupby(["passer_player_name", "week"]):
            k = (Y, str(pn).lower().replace("'", "").replace(" ", ""), int(wk))
            att = grp.pass_attempt.sum(); cp = grp.cpoe.dropna()
            rows[(Y, k[1])][int(wk)] = np.array([att, grp.air_yards.fillna(0).sum(), cp.sum(), len(cp), grp.epa.fillna(0).sum(), len(grp), grp.sack.sum(), grp.success.fillna(0).sum()])
        P(f"  pbp {Y}: {len(db):,} dropbacks")
    return rows, team


def main():
    rows, team_wk = load_pbp(YEARS)
    def qb_stats(Y, nm, wk, min_att=60):
        pn = abbrev(nm)
        for Yq in (Y, Y - 1):
            acc = np.zeros(8); nwk = 0
            for w, v in rows.get((Yq, pn), {}).items():
                if Yq < Y or w < wk: acc += v; nwk += 1
            if acc[0] >= min_att:
                return dict(cpoe=acc[2] / max(acc[3], 1), epa=acc[4] / max(acc[5], 1), succ=acc[7] / max(acc[5], 1), adot=acc[1] / acc[0], sack=acc[6] / max(acc[5], 1), attpg=acc[0] / max(nwk, 1), src=Yq)
        return None
    X = QI.setup(); n = X["n"]
    act, year, wk, pos, g, adp, name, team, pid = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], X["team"], X["pid"]
    F = X["F"]; finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    games, roster, starter, team_weeks = QI.build_games(X)
    b_, lk_ = QI.live_base(X, X["ppg"], g.astype(float), X["xfp"], X["snap"]); BASE = np.maximum(0.0, b_ * X["chain"] + lk_)
    okN = (g >= 1) & ~final & ~X["inh"] & (BASE >= 3)
    MET = ("cpoe", "epa", "succ", "adot", "sack", "attpg", "team_attpg")
    M = {k: np.full(n, np.nan) for k in MET}; qbname = [None] * n
    for i in range(n):
        if pos[i] not in ("WR", "TE", "QB") or not team[i] or not okN[i]: continue
        Y = int(year[i]); tm_ = team[i]
        prior_w = [w for w in team_weeks.get((Y, tm_), []) if w < wk[i]]
        s = starter.get((Y, tm_, prior_w[-1])) if prior_w else None
        if pos[i] == "QB": s = name[i]
        if s is None: continue
        qbname[i] = s; st = qb_stats(Y, s, int(wk[i]))
        if st:
            for k in ("cpoe", "epa", "succ", "adot", "sack", "attpg"): M[k][i] = st[k]
        tw = [team_wk[(Y, tm_, w)] for w in prior_w if (Y, tm_, w) in team_wk]
        if tw: M["team_attpg"][i] = np.mean([t[0] for t in tw])
    # z-scores within (year, week) across the pool
    Z = {k: np.full(n, np.nan) for k in MET}
    for k in MET:
        for y in YEARS:
            for w in range(1, 19):
                m = okN & (year == y) & (wk == w) & ~np.isnan(M[k]) & np.isin(pos, ("WR", "TE"))
                if m.sum() >= 20 and np.nanstd(M[k][m]) > 0: Z[k][m] = np.clip((M[k][m] - np.nanmean(M[k][m])) / np.nanstd(M[k][m]), -2.5, 2.5)
    resid = act - BASE; ratio = np.where(BASE > 0, act / BASE, np.nan)
    P(f"\n=== rows: WR/TE with a QB rating {int((okN & np.isin(pos, ('WR','TE')) & ~np.isnan(M['cpoe'])).sum()):,} (of {int((okN & np.isin(pos, ('WR','TE'))).sum()):,}); week-1 rows use the QB's prior season ===")
    P("\n--- 1  does the live miss correlate with the QB's analytics?  Spearman of (actual - live) and of (actual / live) with each metric's within-week z; WR, TE, and the QB himself ---")
    P(f"    {'metric':12s} " + " ".join(f"{ps + ' resid':>10s} {ps + ' ratio':>10s} {'n':>5s}" for ps in ("WR", "TE", "QB")))
    for k in MET:
        cells = []
        for ps in ("WR", "TE", "QB"):
            m = okN & (pos == ps) & ~np.isnan(M[k]) & top150
            zz = Z[k] if ps != "QB" else M[k]
            m = m & ~np.isnan(zz)
            if m.sum() < 100: cells.append(f"{'':>10s} {'':>10s} {int(m.sum()):5d}"); continue
            r1 = spearmanr(zz[m], resid[m]).correlation; r2 = spearmanr(zz[m], ratio[m]).correlation
            cells.append(f"{r1:+10.3f} {r2:+10.3f} {int(m.sum()):5d}")
        P(f"    {k:12s} " + " ".join(cells))
    P("    (for reference: Vegas team implied total is already inside the live number; a correlation here is what the QB's play adds beyond it)")
    P("\n--- 2  actual / live by QB-analytic quintile (WR + TE, top 150) ---")
    for k in MET:
        m = okN & np.isin(pos, ("WR", "TE")) & top150 & ~np.isnan(Z[k])
        if m.sum() < 300: continue
        q = np.nanpercentile(Z[k][m], [20, 40, 60, 80]); cells = []
        edges = [-9] + list(q) + [9]
        for a in range(5):
            mm = m & (Z[k] >= edges[a]) & (Z[k] < edges[a + 1])
            cells.append(f"Q{a+1}: {act[mm].sum()/BASE[mm].sum():.3f} (n{int(mm.sum())})")
        P(f"    {k:12s} " + " | ".join(cells) + f"  | metric mean by Q: {np.nanmean(M[k][m & (Z[k] < edges[1])]):.2f} -> {np.nanmean(M[k][m & (Z[k] >= edges[4])]):.2f}")
    P("\n--- 3  as a multiplier on the live number: 1 + e x z (WR + TE), LOYO + forward, ship bar 5/7 + 3/4 ---")
    wm = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    for k in MET:
        m = okN & np.isin(pos, ("WR", "TE")) & top150 & ~np.isnan(Z[k])
        if m.sum() < 300: continue
        sign = -1.0 if k in ("sack", "attpg", "team_attpg") else 1.0   # volume and sacks correlate NEGATIVELY with the miss
        preds = {"off": BASE}
        for e in (0.01, 0.02, 0.04, 0.06):
            p = BASE.copy(); p[m] = BASE[m] * np.clip(1 + sign * e * Z[k][m], 0.8, 1.2); preds[f"e {e}"] = p
        names = list(preds); pick = lambda yrs: min(names, key=lambda kk: wm(preds[kk], m & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = BASE.copy()
            for tr_, te in folds:
                kk = pick(tr_); picks.append(kk); mm = year == te; pr[mm] = preds[kk][mm]; wins += wm(preds[kk], m & mm) < wm(BASE, m & mm) - 1e-12
            tem = np.isin(year, [te for _, te in folds]); return 100 * (wm(pr, m & tem) / wm(BASE, m & tem) - 1), wins, picks
        lo = run(LOSO); fw = run(FORW)
        fixed = "  ".join(f"{kk}: {100*(wm(preds[kk], m)/wm(BASE, m)-1):+.2f}% ({sum(1 for y in YEARS if wm(preds[kk], m & (year == y)) < wm(BASE, m & (year == y)) - 1e-12)}/7)" for kk in names[1:])
        okk = lo[1] >= 5 and lo[0] < -0.3 and fw[1] >= 3 and fw[0] < 0
        P(f"    {k:12s} n{int(m.sum())} | {fixed} | LOYO {lo[0]:+.2f}% {lo[1]}/7 | FWD {fw[0]:+.2f}% {fw[1]}/4 -> {'PASS' if okk else 'FAIL'}")
    P("\n--- 4  is the QB's quality already in the receiver's own numbers?  Spearman of the QB's season-to-date CPOE / EPA with the receiver's season-to-date PPG over his Clay number (WR + TE, 3+ games) ---")
    m = okN & np.isin(pos, ("WR", "TE")) & (g >= 3) & ~np.isnan(M["cpoe"]) & top150
    over = X["ppg"] / np.maximum(QI.np.array(X["clay_gm"]), 1.0)
    for k in ("cpoe", "epa", "succ", "attpg", "team_attpg"):
        mm = m & ~np.isnan(M[k]); P(f"    {k:12s} rho {spearmanr(M[k][mm], over[mm]).correlation:+.3f} (n{int(mm.sum())})")
    P("\n--- 5  QB-change weeks only: replacement's trailing CPOE / EPA (prior seasons) minus the regular's, vs actual / live (WR + TE) ---")
    mchg = np.zeros(n, bool); dcp = np.full(n, np.nan); dep = np.full(n, np.nan)
    for i in range(n):
        if pos[i] not in ("WR", "TE") or not team[i] or not okN[i]: continue
        Y = int(year[i]); tm_ = team[i]; prior_w = [w for w in team_weeks.get((Y, tm_), []) if w < wk[i]]
        s_now = starter.get((Y, tm_, int(wk[i])))
        if s_now is None or not prior_w: continue
        from collections import Counter
        cnt = Counter(starter[(Y, tm_, w)] for w in prior_w); reg = max(cnt, key=lambda q: (cnt[q], max(w for w in prior_w if starter[(Y, tm_, w)] == q)))
        if s_now == reg: continue
        a, b2 = qb_stats(Y, s_now, int(wk[i]), 40), qb_stats(Y, reg, int(wk[i]), 40)
        if a and b2: mchg[i] = True; dcp[i] = a["cpoe"] - b2["cpoe"]; dep[i] = a["epa"] - b2["epa"]
    for lab, dv, cuts in (("CPOE diff", dcp, (-99, -3, -1, 1, 3, 99)), ("EPA/db diff", dep, (-99, -0.15, -0.05, 0.05, 0.15, 99))):
        cells = []
        for a in range(5):
            mm = mchg & (dv >= cuts[a]) & (dv < cuts[a + 1])
            if mm.sum() >= 10: cells.append(f"[{cuts[a]}, {cuts[a+1]}): act/live {act[mm].sum()/BASE[mm].sum():.3f} n{int(mm.sum())}")
        P(f"    {lab:12s} " + " | ".join(cells))
    mm = mchg & ~np.isnan(dcp); P(f"    Spearman replacement-minus-regular CPOE vs act/live: {spearmanr(dcp[mm], ratio[mm]).correlation:+.3f} (n{int(mm.sum())}); EPA: {spearmanr(dep[mm], ratio[mm]).correlation:+.3f}")
    P(chr(10) + "--- 6  GRADED DOCK BY THE REPLACEMENT'S TRAILING PLAY (QB-change weeks, WR + TE): multiplier clip(1 + b x EPA/db diff, .8, 1.2) and clip(1 + c x CPOE diff / 10, .8, 1.2); LOYO + forward ---")
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    mse = lambda p, m: float(np.mean((p[m] - act[m]) ** 2)) if m.any() else np.nan
    for lab, dv, grid in (("EPA/db diff", dep, (0.2, 0.35, 0.5, 0.8)), ("CPOE diff", dcp, (0.1, 0.2, 0.3, 0.5))):
        m = mchg & ~np.isnan(dv)
        preds = {"off": BASE}
        for b in grid:
            p = BASE.copy(); p[m] = BASE[m] * np.clip(1 + b * (dv[m] if lab.startswith("EPA") else dv[m] / 10.0), 0.8, 1.2); preds[f"b {b}"] = p
        names = list(preds); pick = lambda yrs: min(names, key=lambda kk: mse(preds[kk], m & np.isin(year, yrs)))
        def run(folds):
            wins = 0; picks = []; pr = BASE.copy()
            for tr_, te in folds:
                kk = pick(tr_); picks.append(kk); mm = year == te; pr[mm] = preds[kk][mm]; wins += mse(preds[kk], m & mm) < mse(BASE, m & mm) - 1e-12
            tem = np.isin(year, [te for _, te in folds]); return 100 * (mse(pr, m & tem) / mse(BASE, m & tem) - 1), wins, picks
        lo = run(LOSO); fw = run(FORW)
        fixed = "  ".join(f"{kk}: {100*(mse(preds[kk], m)/mse(BASE, m)-1):+.2f}% ({sum(1 for y in YEARS if (m & (year == y)).sum() >= 8 and mse(preds[kk], m & (year == y)) < mse(BASE, m & (year == y)) - 1e-12)}/7)" for kk in names[1:])
        t150 = m & top150; best = pick(YEARS)
        P(f"    {lab:12s} n{int(m.sum())} (top-150 {int(t150.sum())}) | {fixed}")
        P(f"    {'':12s} top-150 rows at best fixed ({best}): {100*(mse(preds[best], t150)/mse(BASE, t150)-1):+.2f}% | LOYO {lo[0]:+.2f}% {lo[1]}/7 picks {lo[2]} | FWD {fw[0]:+.2f}% {fw[1]}/4 -> {'PASS' if (lo[1] >= 5 and lo[0] < -0.3 and fw[1] >= 3 and fw[0] < 0) else 'FAIL'}")
    LOG.close()


if __name__ == "__main__":
    main()
