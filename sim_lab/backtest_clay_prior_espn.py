#!/usr/bin/env python3
"""
ITEMS 3 + 4 (Jack 2026-10-07 evening: "then run 3 and 4").  Same rows / models as backtest_base_remeasure.py (2019-25,
next game pre-book, top-150 weighted), with the base now = per-position blend of shadow and Clay-blend model
(QB .7 / RB .7 / WR .7 / TE .3 on the shadow, as wired).

  3  CLAY-SIDE PRIOR   the Clay-blend model's prior = 50/50 Clay per game + the player's prior-season PPG (6+ games last
                       season; else Clay) - the breakout study's season-level pass (TE -8%, WR -11% vs Clay alone).
                       Variants: WR/TE; WR/TE/RB; all four; 25/75. Graded on the Clay-blend model alone and inside the blend.
  4  ESPN IN THE SOFT BAND   rank order inside ADP 31-60 is .08-.11. Variants: ESPN 50/50 on every row (the rank mix),
                       ESPN 50/50 only on ADP 31-60, 30% in the band, 50/50 on 31-100. Graded on within-position weekly
                       rank rho (band rows / all), pairs right, weighted error; seasons better of 7, forward 2022-25.
Log clay_prior_espn.log.
"""
import json, os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
SN = BR.SN; NW = BR.NW; cal = NW.cal; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
from backtest_inseason_usage import route_features
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "clay_prior_espn.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
BBW = {"QB": 0.7, "RB": 0.7, "WR": 0.7, "TE": 0.3}


def live_today_with(X, clay_override=None):
    """backtest_base_remeasure.live_today with the Clay per-game prior swappable (copy of its body)"""
    F = X["F"]; A = F["A"]; n = X["n"]
    act, year, wk, pos, g, ppg, clay, layers, adp, pid, name = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["clay"], A["layers"], F["adp"], A["pid"], A["name"]
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8"))
    gm = np.array([(ch[str(y)].get(nm) or {}).get("gm") or 0 for y, nm in zip(year, name)], dtype=float)
    W = np.where(year <= 2020, 16.0, 17.0); clay_gm = np.where(gm >= 4, clay * W / np.maximum(gm, 1), clay)
    if clay_override is not None: clay_gm = clay_override(clay_gm)
    mu_y = {}
    for y in YEARS:
        wy = 16.0 if y <= 2020 else 17.0
        lv = sorted([max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0) / wy for c in ch[str(y)].values() if c.get("pos") == "QB"], reverse=True)[:32]
        mu_y[y] = float(np.mean(lv))
    mu = np.array([mu_y[int(y)] for y in year])
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet"))
    def joiner(D):
        k = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(D.year, D.pid, D.wk)) if isinstance(b, str)}
        ix = np.array([k.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)])
        return lambda c, d=np.nan: np.where(ix >= 0, D[c].values[np.maximum(ix, 0)].astype(float), d), ix >= 0
    cv, hasC = joiner(C); lv_, hasL = joiner(L)
    xfp, snap = cv("xfp_pg"), cv("snap_std"); rt, _ = route_features(year, pid, wk)
    useok = hasC & (g >= 1) & ~np.isnan(xfp) & ~np.isnan(snap) & ~np.isnan(rt)
    lam_wr = np.select([g <= 2, g <= 5, g <= 8], [0.8, 0.6, 0.5], 0.3); lam_te = np.full(n, 0.3)
    lam = np.where(useok & (pos == "WR"), lam_wr, np.where(useok & (pos == "TE"), lam_te, 0.0))
    cw, ct = BR.USE_C["WR"], BR.USE_C["TE"]
    uimp = np.maximum(0.0, np.nan_to_num(np.where(pos == "WR", cw[0] + cw[1] * xfp + cw[2] * rt + cw[3] * snap, ct[0] + ct[1] * xfp + ct[2] * rt + ct[3] * snap), nan=0.0))
    ppg0 = np.maximum(0.0, ppg)
    tdl = np.nan_to_num(lv_("td_luck_pg", 0.0), nan=0.0); tdk = np.array([BR.TDK[p_] for p_ in pos])
    rook = np.nan_to_num(lv_("rookie_mult", 1.0), nan=1.0); cond = np.nan_to_num(lv_("cond_mult", 1.0), nan=1.0)
    wx = np.nan_to_num(lv_("weather_mult", 1.0), nan=1.0); pool = np.nan_to_num(lv_("pool_mult", 1.0), nan=1.0)
    inh = np.nan_to_num(lv_("qb_inherit_mult", 1.0), nan=1.0) > 1.0
    rbu = lv_("usage_half"); rbu = np.where(pos == "RB", rbu, np.nan)
    snapm = np.nan_to_num(cv("snapmult", 1.0), nan=1.0)
    chain = layers * snapm * cond * wx * pool
    PS = np.where((pos == "WR") & (lam > 0) & (np.isnan(adp) | (adp > 60)), 4.0, float(BR.LIVE_P))
    ev = np.where(lam > 0, lam * uimp + (1 - lam) * ppg0, ppg0)
    base = np.where(g > 0, (PS * clay_gm + g * ev) / (PS + g), clay_gm) * rook
    fl = (pos == "QB") & ~inh & (base >= 5) & (base < mu); base = np.where(fl, mu + 0.70 * (base - mu), base)
    base = np.where(~np.isnan(rbu), 0.85 * base + 0.15 * np.nan_to_num(rbu, nan=0.0), base)
    luck = np.where(g > 0, tdk * tdl * g / (BR.LIVE_P + g) * (1 - lam), 0.0)
    return np.maximum(0.0, base * chain + luck), dict(clay_gm=clay_gm, inh=inh)


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = live_today_with(X); SHADOW, _ = BR.shadow_current(X)
    bw = np.array([BBW[p_] for p_ in pos]); blend = lambda live: bw * SHADOW + (1 - bw) * live
    BLEND = blend(TODAY)
    base = top150 & ~final & ~LV["inh"]
    wm = lambda q, mm: float(np.average((q[mm] - act[mm]) ** 2, weights=wt[mm])) if mm.any() else np.nan
    def rank_stats(p, m):
        groups = defaultdict(list)
        for i in np.where(m)[0]: groups[(int(year[i]), int(wk[i]), pos[i])].append(i)
        rh, pw, tot = [], 0, 0
        for ix in (np.array(v) for v in groups.values()):
            if len(ix) < 8: continue
            a, pv = act[ix], p[ix]; rh.append(np.corrcoef(rankdata(a), rankdata(pv))[0, 1])
            d = pv[:, None] - pv[None, :]; o = a[:, None] - a[None, :]; iu = np.triu_indices(len(ix), 1); okp = (d[iu] != 0) & (o[iu] != 0)
            pw += int(((d[iu] > 0) == (o[iu] > 0))[okp].sum()); tot += int(okp.sum())
        return (float(np.mean(rh)) if rh else np.nan), 100.0 * pw / max(1, tot)
    def line(lab, p, ref, m, yrs=YEARS):
        m = m & np.isin(year, list(yrs))
        d = 100 * (wm(p, m) / wm(ref, m) - 1); wins = sum(1 for y in yrs if (m & (year == y)).sum() >= 8 and wm(p, m & (year == y)) < wm(ref, m & (year == y)) - 1e-12)
        rh, pr = rank_stats(p, m); rh0, _ = rank_stats(ref, m)
        return f"{d:+6.2f}% ({wins}/{len(yrs)}) rho {rh0:.3f}->{rh:.3f} pairs {pr:.2f}%"
    P(f"=== base as wired: per-position blend QB/RB/WR .7, TE .3 on the shadow | {int(base.sum()):,} top-150 rows ===")
    P(f"    blend vs the Clay-blend model alone: {line('', BLEND, TODAY, base)}")
    # ---------------------------------------------------------------- 3  Clay-side prior
    prev = np.full(n, np.nan); cache = {}
    for i in range(n):
        k = (name[i], pos[i], int(year[i]))
        if k not in cache:
            rec = cal.weekly_rec(name[i], pos[i]); pts = [float(w["fpts"]) for w in (rec or {}).get("seasons", {}).get(str(int(year[i]) - 1), []) if cal.played(w) and isinstance(w.get("fpts"), (int, float))]
            cache[k] = float(np.mean(pts)) if len(pts) >= 6 else np.nan
        prev[i] = cache[k]
    hasp = ~np.isnan(prev)
    P(f"\n=== 3  CLAY-SIDE PRIOR: 50/50 Clay per game + prior-season PPG (rows with 6+ games last season: {int((base & hasp).sum()):,} of {int(base.sum()):,}) ===")
    P(f"    {'variant':44s} {'Clay-model alone vs today':>40s} | {'inside the blend vs blend':>40s} | touched rows alone | touched rows blend")
    def clay_var(scope_pos, wprev):
        def f(cg):
            m = np.isin(pos, scope_pos) & hasp
            out = cg.copy(); out[m] = (1 - wprev) * cg[m] + wprev * prev[m]; return out
        return f
    VARS = [("WR/TE 50/50", ("WR", "TE"), 0.5), ("WR/TE 25/75 (25% prior-year)", ("WR", "TE"), 0.25), ("WR/TE/RB 50/50", ("WR", "TE", "RB"), 0.5), ("all four 50/50", POS4, 0.5), ("WR only 50/50", ("WR",), 0.5), ("TE only 50/50", ("TE",), 0.5)]
    res3 = {}
    for lab, sp, w in VARS:
        T2, _ = live_today_with(X, clay_var(sp, w)); B2 = blend(T2); tm = base & np.isin(pos, sp) & hasp; res3[lab] = (T2, B2, tm)
        P(f"    {lab:44s} {line('', T2, TODAY, base):>40s} | {line('', B2, BLEND, base):>40s} | {line('', T2, TODAY, tm)} | {line('', B2, BLEND, tm)}")
    P("    -- 2022-25 only --")
    for lab, sp, w in VARS[:4]:
        T2, B2, tm = res3[lab]; P(f"    {lab:44s} {line('', T2, TODAY, base, FWD):>40s} | {line('', B2, BLEND, base, FWD):>40s} | {line('', T2, TODAY, tm, FWD)} | {line('', B2, BLEND, tm, FWD)}")
    T2, B2, tm = res3["WR/TE 50/50"]
    P("    WR/TE 50/50 by cut (inside the blend vs blend): " + " | ".join(f"{cl} {line('', B2, BLEND, tm & cm).split(' rho')[0].strip()}" for cl, cm in (("WR", pos == "WR"), ("TE", pos == "TE"), ("ADP 1-30", adpx <= 30), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100)), ("101-150", adpx > 100), ("weeks 1-4", wk <= 4), ("weeks 5-9", (wk >= 5) & (wk <= 9)), ("weeks 10+", wk >= 10))))
    P("    by season (blend, WR/TE rows): " + "  ".join(f"{y}: {100*(wm(B2, tm & (year == y))/wm(BLEND, tm & (year == y))-1):+.1f}%" for y in YEARS))
    # ---------------------------------------------------------------- 4  ESPN in the soft band
    esp = BR.load_espn(X)
    if esp is None: P("\n=== 4  ESPN: no rows available ==="); LOG.close(); return
    okE = ~np.isnan(esp) & (esp > 0.5)
    band = (adpx > 30) & (adpx <= 60); b100 = (adpx > 30) & (adpx <= 100)
    P(f"\n=== 4  ESPN IN THE SOFT BAND (ESPN rows on {int((base & okE).sum()):,} of {int(base.sum()):,} top-150 rows; band 31-60 rows {int((base & band).sum()):,}, with ESPN {int((base & band & okE).sum()):,}) ===")
    def withE(p, m, w=0.5):
        out = p.copy(); mm = m & okE; out[mm] = (1 - w) * p[mm] + w * esp[mm]; return out
    VARS4 = [("ESPN 50/50 on every row (rank mix)", withE(BLEND, np.ones(n, bool))), ("ESPN 50/50 on ADP 31-60 only", withE(BLEND, band)), ("ESPN 30% on ADP 31-60 only", withE(BLEND, band, 0.3)),
             ("ESPN 50/50 on ADP 31-100", withE(BLEND, b100)), ("ESPN 50/50 on ADP 31-60, WR/TE only", withE(BLEND, band & np.isin(pos, ("WR", "TE"))))]
    P(f"    {'variant':44s} {'band 31-60 rows (error, rho, pairs)':>46s} | {'all top-150 rows':>46s}")
    for lab, p in VARS4:
        P(f"    {lab:44s} {line('', p, BLEND, base & band):>46s} | {line('', p, BLEND, base):>46s}")
    P("    -- 2022-25 only --")
    for lab, p in VARS4:
        P(f"    {lab:44s} {line('', p, BLEND, base & band, FWD):>46s} | {line('', p, BLEND, base, FWD):>46s}")
    p = VARS4[1][1]
    P("    band rows by position (ESPN 50/50 in band): " + " | ".join(f"{ps} {line('', p, BLEND, base & band & (pos == ps))}" for ps in POS4))
    P("    band rho by season (blend -> ESPN in band): " + "  ".join(f"{y}: {rank_stats(BLEND, base & band & (year == y))[0]:.3f}->{rank_stats(p, base & band & (year == y))[0]:.3f}" for y in YEARS))
    P("    reference: ESPN alone on the band rows: " + line('', np.where(okE, esp, BLEND), BLEND, base & band))
    P("\nLimitations: next-game, pre-book; book anchor / docks not replayed; ESPN rows where their weekly file has the player; prior-season PPG from the weekly logs (6+ games).")
    LOG.close()


if __name__ == "__main__":
    main()
