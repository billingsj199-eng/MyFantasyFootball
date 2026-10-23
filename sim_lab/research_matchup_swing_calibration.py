#!/usr/bin/env python3
"""
MATCHUP SWING CALIBRATION (2026-10-23). Jack: "Look into weekly matchups and how much they should be increased or
decreased based on their season-long projections. Are we being too conservative on decreasing or increasing their
weekly projected points on matchup?"

A CALIBRATION question, not an MSE one. Harness = research_clay_vs_shadow.build_harness() (the clay-free shadow,
2019-25 default; SIM_BT_YEARS=2012-2025 = extended pool). In the harness the weekly number is
    shadow = baseline x veg x fpa
where baseline = the player's level entering the game (history / ADP-market prior blended with season-to-date PPG,
string docks, vacated-role pool mult) and veg x fpa = the two game-specific layers the engine ships
(vegasMult: 1 + e_pos x (implied - avg) / avg, clip .7-1.35, e QB/WR/TE .25 RB .50; jsOppMult: 1 + .25 x (clip(FPA
ratio, .8, 1.25) - 1) x min(1, g/8)). Pace is intel-only in the engine (not applied) so there is no pace part.

    swing      = shadow - baseline                  (what the matchup moved the weekly number, in points)
    swing_veg  = baseline x (veg - 1)               Vegas part
    swing_opp  = baseline x (fpa - 1)               opponent part
    swing_x    = remainder (interaction, tiny)

Calibration regression on top-150 rows (preseason ADP <= 150), final week excluded:
    act - baseline = a + b x swing        b = 1 sized right, b > 1 too conservative, b < 1 too aggressive
plus the multivariate form a + bV x swing_veg + bO x swing_opp, by position, by swing decile, by week bucket, by ADP
band; CI = cluster bootstrap over (season, week); per-season b for the "consistent across seasons" read.
Output: research_matchup_swing_calibration.log (+ _ext tag in extended mode).
"""
import os, sys, time, json
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_noclay_weekly as NW
import bt_common as B
import bt_ext as BX
import research_clay_vs_shadow as CVS

LOG = BX.ext_path("research_matchup_swing_calibration.log")
if __name__ == "__main__":
    sys.stdout = NW._Tee(sys.stdout, open(LOG, "w", encoding="utf-8"))
def P(*a): print(" ".join(str(x) for x in a))

YEARS, POS4 = NW.YEARS, NW.POS4
RNG = np.random.default_rng(7)
NBOOT = int(os.environ.get("SIM_CAL_NBOOT", "400"))


def ols(X, y, w=None):
    if w is None: w = np.ones(len(y))
    sw = np.sqrt(w)
    b, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    return b


def fit_b(y, cols, clusters, w=None, nboot=NBOOT):
    """OLS of y on [1, cols...]; returns coefs + cluster-bootstrap 90% CI (5-95) per coef."""
    X = np.column_stack([np.ones(len(y))] + list(cols))
    b = ols(X, y, w)
    uniq, inv = np.unique(clusters, return_inverse=True)
    K = len(uniq); idx_by = [np.where(inv == k)[0] for k in range(K)]
    bs = []
    for _ in range(nboot):
        pick = RNG.integers(0, K, K)
        ii = np.concatenate([idx_by[k] for k in pick])
        bs.append(ols(X[ii], y[ii], None if w is None else w[ii]))
    bs = np.array(bs)
    lo, hi = np.percentile(bs, 5, axis=0), np.percentile(bs, 95, axis=0)
    return b, lo, hi


def per_season(y, cols, year, w=None):
    out = {}
    for Y in YEARS:
        m = year == Y
        if m.sum() < 80: continue
        X = np.column_stack([np.ones(m.sum())] + [c[m] for c in cols])
        out[Y] = ols(X, y[m], None if w is None else w[m])
    return out


def fmt_ci(b, lo, hi): return f"{b:+.2f} [{lo:+.2f},{hi:+.2f}]"


def spearman_pw(pred, act, pos, year, wk, mask):
    """mean within position-week Spearman (rank objective)."""
    from scipy.stats import spearmanr
    rhos = []
    for ps in POS4:
        for Y in YEARS:
            for W in range(1, 19):
                m = mask & (pos == ps) & (year == Y) & (wk == W)
                if m.sum() < 8: continue
                r = spearmanr(pred[m], act[m]).correlation
                if np.isfinite(r): rhos.append(r)
    return float(np.mean(rhos)) if rhos else np.nan


def main():
    t0 = time.time()
    P(f"=== MATCHUP SWING CALIBRATION ({YEARS[0]}-{YEARS[-1]}, pool {BX.POOL}, teamfix {BX.TEAMFIX}) ===")
    F = CVS.build_harness(); A = F["A"]; n = F["n"]
    act, year, wk, pos, g, team, pid = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["team"], A["pid"]
    shadow, layers, adp = F["shadow"], F["layers"], F["adp"]
    BASE = os.environ.get("SIM_CAL_BASE", "shadow")
    if BASE == "clay": shadow = F["shipped"]; P("  BASE = shipped Clay blend (P=5 Clay season PPG x season-to-date) instead of the shadow")
    # --- recompute the Vegas part exactly as the harness did (implied vs season-average implied, position elasticity) ---
    veg = np.full(n, np.nan)
    for Y in YEARS:
        games = B.load_games(Y)
        imps = [v["implied"] for v in games.values() if v["implied"] is not None]; avg = float(np.mean(imps))
        for i in np.where(year == Y)[0]:
            gm = games.get((team[i], wk[i]))
            if gm and gm["implied"] is not None:
                veg[i] = min(1.35, max(0.7, 1 + B.VEG[pos[i]] * (gm["implied"] - avg) / avg))
    ok = ~np.isnan(veg)
    fpa = np.where(ok, layers / np.where(ok, veg, 1), np.nan)
    P(f"  rows {n}; veg recovered on {ok.sum()}; fpa range {np.nanmin(fpa):.3f}-{np.nanmax(fpa):.3f} (engine clip 0.95-1.0625), veg range {np.nanmin(veg):.3f}-{np.nanmax(veg):.3f}")
    baseline = shadow / layers
    swing = shadow - baseline
    sv = baseline * (veg - 1); so = baseline * (fpa - 1); sx = swing - sv - so
    y = act - baseline
    final_wk = np.where(year <= 2020, 17, 18)
    base_m = ok & (wk < final_wk) & ~np.isnan(act) & (baseline > 0)
    top = base_m & ~np.isnan(adp) & (adp <= 150)
    clusters = year * 100 + wk
    P(f"  graded rows (final week out): {base_m.sum()}; top-150 by preseason ADP: {top.sum()}")
    P(f"  swing size (top-150): mean |swing| {np.abs(swing[top]).mean():.2f} pts, |Vegas part| {np.abs(sv[top]).mean():.2f}, |opp part| {np.abs(so[top]).mean():.2f}, |interaction| {np.abs(sx[top]).mean():.3f}")
    P(f"  swing spread: p5 {np.percentile(swing[top],5):+.2f}  p25 {np.percentile(swing[top],25):+.2f}  p75 {np.percentile(swing[top],75):+.2f}  p95 {np.percentile(swing[top],95):+.2f}")

    P("\n=== A. b by position: act - baseline = a + b x swing (top-150, unweighted | level-weighted) ===")
    P("  read: b = 1 sized right; > 1 we are too conservative; < 1 too aggressive. CI = 90% cluster bootstrap over season-week.")
    P(f"  {'cut':8s} {'n':>6s}  {'b total':22s} {'bV Vegas':22s} {'bO opp':22s} | weighted b / bV / bO | per-season b (total)")
    RES = {}
    for lab, m in [("ALL", top)] + [(ps, top & (pos == ps)) for ps in POS4]:
        b1, lo1, hi1 = fit_b(y[m], [swing[m]], clusters[m])
        b2, lo2, hi2 = fit_b(y[m], [sv[m], so[m]], clusters[m])
        wb1, _, _ = fit_b(y[m], [swing[m]], clusters[m], w=baseline[m], nboot=1)
        wb2, _, _ = fit_b(y[m], [sv[m], so[m]], clusters[m], w=baseline[m], nboot=1)
        ps_b = per_season(y[m], [swing[m]], year[m])
        seas = " ".join(f"{Y % 100:02d}:{v[1]:+.2f}" for Y, v in ps_b.items())
        n_over = sum(1 for v in ps_b.values() if v[1] > 1)
        P(f"  {lab:8s} {m.sum():6d}  {fmt_ci(b1[1],lo1[1],hi1[1]):22s} {fmt_ci(b2[1],lo2[1],hi2[1]):22s} {fmt_ci(b2[2],lo2[2],hi2[2]):22s} | {wb1[1]:+.2f} / {wb2[1]:+.2f} / {wb2[2]:+.2f} | {seas}  (b>1 in {n_over}/{len(ps_b)})")
        RES[lab] = dict(n=int(m.sum()), b=float(b1[1]), b_lo=float(lo1[1]), b_hi=float(hi1[1]), bV=float(b2[1]), bV_lo=float(lo2[1]), bV_hi=float(hi2[1]),
                        bO=float(b2[2]), bO_lo=float(lo2[2]), bO_hi=float(hi2[2]), wb=float(wb1[1]), wbV=float(wb2[1]), wbO=float(wb2[2]), seasons={int(Y): float(v[1]) for Y, v in ps_b.items()})
    # multiplicative cross-check: act / baseline - 1 = a + b x (layers - 1), level-weighted
    P("\n  multiplicative form act/baseline - 1 = a + b x (veg - 1) + c x (fpa - 1), level-weighted (cross-check):")
    for lab, m in [("ALL", top)] + [(ps, top & (pos == ps)) for ps in POS4]:
        r = act[m] / baseline[m] - 1
        b, lo, hi = fit_b(r, [veg[m] - 1, fpa[m] - 1], clusters[m], w=baseline[m], nboot=200)
        P(f"    {lab:8s} bV {fmt_ci(b[1],lo[1],hi[1])}  bO {fmt_ci(b[2],lo[2],hi[2])}")

    P("\n=== B. by swing decile (top-150, pooled positions): does a +2 pt bump play out as +2? ===")
    a_all = fit_b(y[top], [swing[top]], clusters[top], nboot=1)[0][0]
    qs = np.percentile(swing[top], np.linspace(0, 100, 11))
    P(f"  intercept (overall bias act - baseline, removed below) a = {a_all:+.2f}")
    P(f"  {'decile':6s} {'n':>6s} {'swing':>8s} {'realized':>9s} {'ratio':>6s} | {'Vegas part':>10s} {'opp part':>9s}")
    for d in range(10):
        m = top & (swing >= qs[d]) & (swing <= qs[d + 1] if d == 9 else swing < qs[d + 1])
        ms, my = swing[m].mean(), y[m].mean() - a_all
        P(f"  D{d+1:<4d} {m.sum():6d} {ms:+8.2f} {my:+9.2f} {(my/ms if abs(ms) > 0.15 else np.nan):6.2f} | {sv[m].mean():+10.2f} {so[m].mean():+9.2f}")
    # same by position, top / bottom 20%
    P("  by position, bottom 20% / top 20% of that position's swing:")
    for ps in POS4:
        m = top & (pos == ps); q20, q80 = np.percentile(swing[m], 20), np.percentile(swing[m], 80)
        a_p = fit_b(y[m], [swing[m]], clusters[m], nboot=1)[0][0]
        for lab, mm in (("low", m & (swing <= q20)), ("high", m & (swing >= q80))):
            P(f"    {ps} {lab:4s} n {mm.sum():5d} swing {swing[mm].mean():+6.2f} -> realized {y[mm].mean() - a_p:+6.2f}")

    P("\n=== C. by week bucket (opponent trust ramps to game 8) ===")
    P(f"  {'cut':14s} {'n':>6s}  {'b total':22s} {'bV Vegas':22s} {'bO opp':22s}")
    for lab, m in (("wk 1-4", top & (wk <= 4)), ("wk 5-9", top & (wk >= 5) & (wk <= 9)), ("wk 10+", top & (wk >= 10)), ("playoffs 15-17", top & (wk >= np.where(year <= 2020, 14, 15)))):
        b1, lo1, hi1 = fit_b(y[m], [swing[m]], clusters[m])
        b2, lo2, hi2 = fit_b(y[m], [sv[m], so[m]], clusters[m])
        P(f"  {lab:14s} {m.sum():6d}  {fmt_ci(b1[1],lo1[1],hi1[1]):22s} {fmt_ci(b2[1],lo2[1],hi2[1]):22s} {fmt_ci(b2[2],lo2[2],hi2[2]):22s}")
    P("  by position x week bucket (b total, bO opp):")
    for ps in POS4:
        row = []
        for lab, m in (("1-4", top & (pos == ps) & (wk <= 4)), ("5-9", top & (pos == ps) & (wk >= 5) & (wk <= 9)), ("10+", top & (pos == ps) & (wk >= 10))):
            b2, lo2, hi2 = fit_b(y[m], [sv[m], so[m]], clusters[m], nboot=150)
            b1, lo1, hi1 = fit_b(y[m], [swing[m]], clusters[m], nboot=150)
            row.append(f"wk {lab}: b {fmt_ci(b1[1],lo1[1],hi1[1])} bO {fmt_ci(b2[2],lo2[2],hi2[2])}")
        P(f"    {ps}: " + " | ".join(row))

    P("\n=== D. by ADP band ===")
    P(f"  {'cut':14s} {'n':>6s}  {'b total':22s} {'bV Vegas':22s} {'bO opp':22s}")
    for lab, m in (("ADP 1-60", top & (adp <= 60)), ("ADP 61-150", top & (adp > 60)), ("ADP 151+/none", base_m & ~top)):
        b1, lo1, hi1 = fit_b(y[m], [swing[m]], clusters[m])
        b2, lo2, hi2 = fit_b(y[m], [sv[m], so[m]], clusters[m])
        P(f"  {lab:14s} {m.sum():6d}  {fmt_ci(b1[1],lo1[1],hi1[1]):22s} {fmt_ci(b2[1],lo2[1],hi2[1]):22s} {fmt_ci(b2[2],lo2[2],hi2[2]):22s}")
    P("  by position x ADP band (b total):")
    for ps in POS4:
        row = []
        for lab, m in (("1-60", top & (pos == ps) & (adp <= 60)), ("61-150", top & (pos == ps) & (adp > 60))):
            b1, lo1, hi1 = fit_b(y[m], [swing[m]], clusters[m], nboot=150)
            row.append(f"ADP {lab}: n {m.sum()} b {fmt_ci(b1[1],lo1[1],hi1[1])}")
        P(f"    {ps}: " + " | ".join(row))

    P("\n=== E. Vegas part split: implied-total ABOVE vs BELOW average (is the dock or the bump the miscalibrated side?) ===")
    for ps in POS4:
        m = top & (pos == ps)
        for lab, mm in (("below avg (dock)", m & (veg < 1)), ("above avg (bump)", m & (veg > 1))):
            b1, lo1, hi1 = fit_b(y[mm], [sv[mm]], clusters[mm], nboot=150)
            P(f"    {ps} {lab:17s} n {mm.sum():5d} mean Vegas part {sv[mm].mean():+5.2f} -> bV {fmt_ci(b1[1],lo1[1],hi1[1])}")
    P("  opponent part split: soft (fpa > 1) vs tough (fpa < 1), games 4+ only:")
    for ps in POS4:
        m = top & (pos == ps) & (g >= 4)
        for lab, mm in (("tough (dock)", m & (fpa < 0.995)), ("soft (bump)", m & (fpa > 1.005))):
            if mm.sum() < 100: continue
            b1, lo1, hi1 = fit_b(y[mm], [so[mm]], clusters[mm], nboot=150)
            P(f"    {ps} {lab:13s} n {mm.sum():5d} mean opp part {so[mm].mean():+5.2f} -> bO {fmt_ci(b1[1],lo1[1],hi1[1])}")

    # ---------------- G. Vegas split: team-level (season-to-date avg implied vs league) vs game-specific deviation ----------------
    P("\n=== G. Vegas split: TEAM level (this team's walk-forward avg implied vs league, shrunk 2 games) vs GAME deviation (this implied - team avg) ===")
    P("  read: if the team-level part has b < 1 late in the season the baseline (season-to-date PPG) already prices team quality; the game part is the true matchup.")
    tavg = np.full(n, np.nan); lgavg = np.full(n, np.nan)
    for Y in YEARS:
        games = B.load_games(Y)
        imps = [v["implied"] for v in games.values() if v["implied"] is not None]; avg = float(np.mean(imps))
        byteam = {}
        for (t, w), v in games.items():
            if v["implied"] is not None: byteam.setdefault(t, {})[w] = v["implied"]
        for i in np.where(year == Y)[0]:
            hist = [v for w, v in byteam.get(team[i], {}).items() if w < wk[i]]
            tavg[i] = (sum(hist) + 2 * avg) / (len(hist) + 2); lgavg[i] = avg
    e_pos = np.array([B.VEG[p] for p in pos])
    imp_i = np.where(ok, lgavg * (1 + (veg - 1) / e_pos), np.nan)   # back out the implied total (inside the clip range)
    sv_game = baseline * e_pos * (imp_i - tavg) / lgavg; sv_team = baseline * e_pos * (tavg - lgavg) / lgavg
    P(f"  {'cut':14s} {'n':>6s}  {'b GAME dev':22s} {'b TEAM level':22s} {'bO opp':22s}")
    for lab, m in [("ALL", top)] + [(ps, top & (pos == ps)) for ps in POS4] + [("wk 1-4", top & (wk <= 4)), ("wk 5-9", top & (wk >= 5) & (wk <= 9)), ("wk 10+", top & (wk >= 10))]:
        b3, lo3, hi3 = fit_b(y[m], [sv_game[m], sv_team[m], so[m]], clusters[m], nboot=200)
        P(f"  {lab:14s} {m.sum():6d}  {fmt_ci(b3[1],lo3[1],hi3[1]):22s} {fmt_ci(b3[2],lo3[2],hi3[2]):22s} {fmt_ci(b3[3],lo3[3],hi3[3]):22s}")
    P("  by position x week bucket (b GAME / b TEAM):")
    for ps in POS4:
        row = []
        for lab, m in (("1-4", top & (pos == ps) & (wk <= 4)), ("5-9", top & (pos == ps) & (wk >= 5) & (wk <= 9)), ("10+", top & (pos == ps) & (wk >= 10))):
            b3, lo3, hi3 = fit_b(y[m], [sv_game[m], sv_team[m], so[m]], clusters[m], nboot=120)
            row.append(f"wk {lab}: {fmt_ci(b3[1],lo3[1],hi3[1])} / {fmt_ci(b3[2],lo3[2],hi3[2])}")
        P(f"    {ps}: " + " | ".join(row))

    # ---------------- F. LOYO rescale test (only meaningful if some b is clear of 1) ----------------
    P("\n=== F. LOYO rescale test: elasticity x b (b fit on the other seasons), top-150 next game, MAE + rank ===")
    from scipy.stats import spearmanr
    def grade(pred, m):
        mae = float(np.abs(pred[m] - act[m]).mean())
        wm = float((baseline[m] * np.abs(pred[m] - act[m])).sum() / baseline[m].sum())
        ms = float(((pred[m] - act[m]) ** 2).mean()); m60 = m & (adp <= 60)
        return mae, wm, ms, float(np.abs(pred[m60] - act[m60]).mean())
    VARS = ["baseline (shipped e)", "rescale total b (all pos)", "rescale bV,bO (all pos)", "rescale bV,bO by pos", "rescale bO only by pos", "rescale bV only by pos",
            "RB Vegas e .50 -> .25", "QB Vegas e .25 -> .375", "RB .25 + QB .375", "RB .25 + QB .375 + RB opp x1.35", "Vegas game/team split by pos", "game/team split + opp by pos"]
    rows = {k: [] for k in VARS}
    for Y in YEARS:
        tr = top & (year != Y); te = top & (year == Y)
        if te.sum() < 100: continue
        bt = fit_b(y[tr], [swing[tr]], clusters[tr], nboot=1)[0][1]
        bvo = fit_b(y[tr], [sv[tr], so[tr]], clusters[tr], nboot=1)[0]
        bpos = {ps: fit_b(y[tr & (pos == ps)], [sv[tr & (pos == ps)], so[tr & (pos == ps)]], clusters[tr & (pos == ps)], nboot=1)[0] for ps in POS4}
        bV_p = np.array([bpos[p][1] for p in pos]); bO_p = np.array([bpos[p][2] for p in pos])
        bsp = {ps: fit_b(y[tr & (pos == ps)], [sv_game[tr & (pos == ps)], sv_team[tr & (pos == ps)], so[tr & (pos == ps)]], clusters[tr & (pos == ps)], nboot=1)[0] for ps in POS4}
        bG_p = np.array([bsp[p][1] for p in pos]); bT_p = np.array([bsp[p][2] for p in pos]); bO2_p = np.array([bsp[p][3] for p in pos])
        rb, qb = pos == "RB", pos == "QB"
        veg_rb25 = np.where(rb, np.clip(1 + 0.25 * (imp_i - lgavg) / lgavg, 0.7, 1.35), veg)
        veg_qb375 = np.where(qb, np.clip(1 + 0.375 * (imp_i - lgavg) / lgavg, 0.7, 1.35), veg)
        veg_both = np.where(rb, veg_rb25, veg_qb375)
        veg_split = 1 + (sv_game * bG_p + sv_team * bT_p) / baseline
        preds = {"RB Vegas e .50 -> .25": baseline * veg_rb25 * fpa, "QB Vegas e .25 -> .375": baseline * veg_qb375 * fpa, "RB .25 + QB .375": baseline * veg_both * fpa,
                 "RB .25 + QB .375 + RB opp x1.35": baseline * veg_both * np.where(rb, 1 + 1.35 * (fpa - 1), fpa),
                 "Vegas game/team split by pos": baseline * veg_split * fpa, "game/team split + opp by pos": baseline * veg_split * (1 + bO2_p * (fpa - 1))}
        preds.update({"baseline (shipped e)": shadow,
                 "rescale total b (all pos)": baseline + bt * swing,
                 "rescale bV,bO (all pos)": baseline * (1 + bvo[1] * (veg - 1)) * (1 + bvo[2] * (fpa - 1)),
                 "rescale bV,bO by pos": baseline * (1 + bV_p * (veg - 1)) * (1 + bO_p * (fpa - 1)),
                 "rescale bO only by pos": baseline * veg * (1 + bO_p * (fpa - 1)),
                 "rescale bV only by pos": baseline * (1 + bV_p * (veg - 1)) * fpa})
        for k in VARS:
            pr = preds[k]; mae, wm, ms, m60 = grade(pr, te); rho = spearman_pw(pr, act, pos, year, wk, te)
            rows[k].append((Y, mae, wm, rho, ms, m60))
        P(f"  fold {Y}: fitted b total {bt:+.2f}; bV {bvo[1]:+.2f} bO {bvo[2]:+.2f}; by pos bV/bO " + " ".join(f"{ps} {bpos[ps][1]:+.2f}/{bpos[ps][2]:+.2f}" for ps in POS4)
          + " | game/team " + " ".join(f"{ps} {bsp[ps][1]:+.2f}/{bsp[ps][2]:+.2f}" for ps in POS4))
    base = {r[0]: r for r in rows["baseline (shipped e)"]}
    P(f"\n  {'variant':32s} {'MAE':>7s} {'wMAE':>7s} {'rho':>7s} | vs baseline: dMAE% (wins) dwMAE% (wins) drho (wins) dMSE% (wins) dMAE top-60% (wins)")
    def W(v, lt=True): return f"({sum(1 for x in v if (x < 0 if lt else x > 0))}/{len(v)})"
    for k, rs in rows.items():
        mae = np.mean([r[1] for r in rs]); wm = np.mean([r[2] for r in rs]); rho = np.mean([r[3] for r in rs])
        dm = [(r[1] / base[r[0]][1] - 1) * 100 for r in rs]; dw = [(r[2] / base[r[0]][2] - 1) * 100 for r in rs]; dr = [r[3] - base[r[0]][3] for r in rs]
        ds = [(r[4] / base[r[0]][4] - 1) * 100 for r in rs]; d6 = [(r[5] / base[r[0]][5] - 1) * 100 for r in rs]
        P(f"  {k:32s} {mae:7.3f} {wm:7.3f} {rho:7.4f} | {np.mean(dm):+6.2f}% {W(dm)} {np.mean(dw):+6.2f}% {W(dw)} {np.mean(dr):+.4f} {W(dr, False)} {np.mean(ds):+6.2f}% {W(ds)} {np.mean(d6):+6.2f}% {W(d6)}")
    for kv in ("rescale bV,bO by pos", "RB .25 + QB .375", "game/team split + opp by pos"):
        P(f"  per-fold table (MAE, rho, MSE) {kv} vs baseline:")
        for r0, r1 in zip(rows["baseline (shipped e)"], rows[kv]):
            P(f"    {r0[0]}: MAE {r0[1]:.3f} -> {r1[1]:.3f} ({(r1[1]/r0[1]-1)*100:+.2f}%)  rho {r0[3]:.4f} -> {r1[3]:.4f} ({r1[3]-r0[3]:+.4f})  MSE {r0[4]:.2f} -> {r1[4]:.2f} ({(r1[4]/r0[4]-1)*100:+.2f}%)")
    # ---------------- H. ENGINEERED split variants (fixed round numbers, nothing fitted) + forward check + ROS proxy ----------------
    P("\n=== H. Engineered Vegas split (no fitting): veg' = 1 + e' x (implied - teamAvg_k) / lgAvg, teamAvg_k = walk-forward team avg implied shrunk k games to league ===")
    P("  (k small = team-level tilt drops out fast; e' = elasticity on the GAME deviation; TEAM-level part dropped entirely once teamAvg is known)")
    def team_avg(k):
        out = np.full(n, np.nan)
        for Y in YEARS:
            games = B.load_games(Y)
            imps = [v["implied"] for v in games.values() if v["implied"] is not None]; avg = float(np.mean(imps))
            byteam = {}
            for (t, w), v in games.items():
                if v["implied"] is not None: byteam.setdefault(t, {})[w] = v["implied"]
            for i in np.where(year == Y)[0]:
                hist = [v for w, v in byteam.get(team[i], {}).items() if w < wk[i]]
                out[i] = (sum(hist) + k * avg) / (len(hist) + k)
        return out
    TA = {k: team_avg(k) for k in (1, 2, 4, 8)}
    E_SETS = {"e as shipped (.25/.50/.25/.25)": {"QB": .25, "RB": .50, "WR": .25, "TE": .25},
              "e' QB .50 RB .50 WR .375 TE .375": {"QB": .50, "RB": .50, "WR": .375, "TE": .375},
              "e' .50 all": {"QB": .50, "RB": .50, "WR": .50, "TE": .50},
              "e' QB .50 RB .50 WR .50 TE .375": {"QB": .50, "RB": .50, "WR": .50, "TE": .375}}
    def veg_split(k, es):
        ev = np.array([es[p] for p in pos]); return np.clip(1 + ev * (imp_i - TA[k]) / lgavg, 0.7, 1.35)
    HV = {"baseline (shipped)": shadow}
    for k in (1, 2, 4, 8):
        for lab, es in E_SETS.items():
            if k != 2 and lab not in ("e as shipped (.25/.50/.25/.25)", "e' QB .50 RB .50 WR .375 TE .375"): continue
            HV[f"split k={k}, {lab}"] = baseline * veg_split(k, es) * fpa
    # team-level part kept but faded: veg' = 1 + e x game/avg + e x (1 - min(1, g/8)) x team/avg  (k=2 shrink on the team avg)
    ev0 = np.array([B.VEG[p] for p in pos]); fade = 1 - np.minimum(1, g / 8.0)
    HV["split k=2 + team part faded by g/8"] = baseline * np.clip(1 + ev0 * ((imp_i - TA[2]) + fade * (TA[2] - lgavg)) / lgavg, 0.7, 1.35) * fpa
    ev1 = np.array([E_SETS["e' QB .50 RB .50 WR .375 TE .375"][p] for p in pos])
    HV["split k=2 e' + team part faded by g/8 (e shipped)"] = baseline * np.clip(1 + (ev1 * (imp_i - TA[2]) + ev0 * fade * (TA[2] - lgavg)) / lgavg, 0.7, 1.35) * fpa
    def grade_rows(pred):
        out = []
        for Y in YEARS:
            te = top & (year == Y)
            if te.sum() < 100: continue
            mae, wm, ms, m60 = grade(pred, te); rho = spearman_pw(pred, act, pos, year, wk, te); out.append((Y, mae, wm, rho, ms, m60))
        return out
    HR = {k: grade_rows(v) for k, v in HV.items()}; base = {r[0]: r for r in HR["baseline (shipped)"]}
    P(f"  {'variant':52s} {'MAE':>7s} {'rho':>7s} | dMAE% (wins) dwMAE% (wins) drho (wins) dMSE% (wins) dMAE top-60% (wins) | FWD {BX.FWD[0]}+ dMAE% (wins) drho (wins)")
    for k, rs in HR.items():
        mae = np.mean([r[1] for r in rs]); rho = np.mean([r[3] for r in rs])
        dm = [(r[1] / base[r[0]][1] - 1) * 100 for r in rs]; dw = [(r[2] / base[r[0]][2] - 1) * 100 for r in rs]; dr = [r[3] - base[r[0]][3] for r in rs]
        ds = [(r[4] / base[r[0]][4] - 1) * 100 for r in rs]; d6 = [(r[5] / base[r[0]][5] - 1) * 100 for r in rs]
        fm = [(r[1] / base[r[0]][1] - 1) * 100 for r in rs if r[0] in BX.FWD]; fr = [r[3] - base[r[0]][3] for r in rs if r[0] in BX.FWD]
        P(f"  {k:52s} {mae:7.3f} {rho:7.4f} | {np.mean(dm):+6.2f}% {W(dm)} {np.mean(dw):+6.2f}% {W(dw)} {np.mean(dr):+.4f} {W(dr, False)} {np.mean(ds):+6.2f}% {W(ds)} {np.mean(d6):+6.2f}% {W(d6)} | {np.mean(fm):+6.2f}% {W(fm)} {np.mean(fr):+.4f} {W(fr, False)}")
    PICK = "split k=2, e' QB .50 RB .50 WR .375 TE .375"
    P(f"  per-fold {PICK} vs baseline:")
    for r0, r1 in zip(HR["baseline (shipped)"], HR[PICK]):
        P(f"    {r0[0]}: MAE {r0[1]:.3f} -> {r1[1]:.3f} ({(r1[1]/r0[1]-1)*100:+.2f}%)  top-60 MAE {r0[5]:.3f} -> {r1[5]:.3f} ({(r1[5]/r0[5]-1)*100:+.2f}%)  rho {r0[3]:.4f} -> {r1[3]:.4f} ({r1[3]-r0[3]:+.4f})  MSE {r0[4]:.2f} -> {r1[4]:.2f} ({(r1[4]/r0[4]-1)*100:+.2f}%)")
    P(f"  {PICK} by position (all seasons pooled, top-150): dMAE% / drho / dMSE%")
    for ps in POS4:
        m = top & (pos == ps); pr = HV[PICK]
        P(f"    {ps}: MAE {np.abs(shadow[m]-act[m]).mean():.3f} -> {np.abs(pr[m]-act[m]).mean():.3f} ({(np.abs(pr[m]-act[m]).mean()/np.abs(shadow[m]-act[m]).mean()-1)*100:+.2f}%)  rho {spearman_pw(shadow, act, pos, year, wk, m):.4f} -> {spearman_pw(pr, act, pos, year, wk, m):.4f}  MSE {((shadow[m]-act[m])**2).mean():.2f} -> {((pr[m]-act[m])**2).mean():.2f} ({(((pr[m]-act[m])**2).mean()/((shadow[m]-act[m])**2).mean()-1)*100:+.2f}%)")
    P(f"  {PICK} by week bucket: dMAE% / drho")
    for lab, m in (("wk 1-4", top & (wk <= 4)), ("wk 5-9", top & (wk >= 5) & (wk <= 9)), ("wk 10+", top & (wk >= 10)), ("playoffs", top & (wk >= np.where(year <= 2020, 14, 15)))):
        pr = HV[PICK]; P(f"    {lab:9s} MAE {np.abs(shadow[m]-act[m]).mean():.3f} -> {np.abs(pr[m]-act[m]).mean():.3f} ({(np.abs(pr[m]-act[m]).mean()/np.abs(shadow[m]-act[m]).mean()-1)*100:+.2f}%)  rho {spearman_pw(shadow, act, pos, year, wk, m):.4f} -> {spearman_pw(pr, act, pos, year, wk, m):.4f}")
    # re-calibration check: b on the new swing (should sit near 1)
    pr = HV[PICK]; sw2 = pr - baseline
    for lab, m in [("ALL", top)] + [(ps, top & (pos == ps)) for ps in POS4]:
        b1, lo1, hi1 = fit_b(y[m], [sw2[m]], clusters[m], nboot=200)
        P(f"    recalibrated b on {lab:4s}: {fmt_ci(b1[1],lo1[1],hi1[1])}  (mean |swing| {np.abs(sw2[m]).mean():.2f} vs shipped {np.abs(swing[m]).mean():.2f})")
    # ROS proxy: target = player's mean actual over his remaining games (final week out), >= 3 games; prediction = baseline x ROS Vegas tilt
    P("\n  ROS proxy (target = mean actual over the player's remaining games this season, 3+ games, final week out; pred = baseline x season-level Vegas tilt x fpa):")
    P("    shipped form: ROS tilt = 1 + e x (teamAvg_wf - lgAvg) / lgAvg (the team-level part the engine carries into every future week); split form: tilt = 1 (team level already in the baseline)")
    key = {}
    for i in range(n):
        if ok[i] and wk[i] < final_wk[i] and not np.isnan(act[i]): key.setdefault((year[i], pid[i] if pid[i] else A["name"][i]), []).append((wk[i], act[i]))
    ros_act = np.full(n, np.nan)
    for i in range(n):
        lst = key.get((year[i], pid[i] if pid[i] else A["name"][i]), [])
        fut = [a for w, a in lst if w > wk[i]]
        if len(fut) >= 3: ros_act[i] = float(np.mean(fut))
    mr = top & ~np.isnan(ros_act)
    tilt_ship = 1 + ev0 * (TA[2] - lgavg) / lgavg; tilt_faded = 1 + ev0 * fade * (TA[2] - lgavg) / lgavg
    for lab, pr in (("ROS shipped-form tilt", baseline * tilt_ship * fpa), ("ROS no team tilt (split)", baseline * fpa), ("ROS team tilt faded g/8", baseline * tilt_faded * fpa), ("ROS baseline only", baseline)):
        per = []
        for Y in YEARS:
            m = mr & (year == Y)
            if m.sum() < 100: continue
            per.append((Y, float(np.abs(pr[m] - ros_act[m]).mean()), spearman_pw(pr, ros_act, pos, year, wk, m)))
        P(f"    {lab:28s} n {mr.sum():5d} MAE {np.mean([x[1] for x in per]):.3f} rho {np.mean([x[2] for x in per]):.4f} | per-season MAE " + " ".join(f"{x[0]%100:02d}:{x[1]:.3f}" for x in per))
    with open(BX.ext_path("research_matchup_swing_calibration.json"), "w", encoding="utf-8") as f: json.dump(RES, f, indent=1)
    P(f"\ndone {time.time()-t0:.0f}s -> {LOG}")


if __name__ == "__main__":
    main()
