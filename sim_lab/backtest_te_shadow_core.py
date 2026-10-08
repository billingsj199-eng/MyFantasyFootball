#!/usr/bin/env python3
"""
TE SHADOW CORE: port the live form's two in-season pieces the shadow lacks (Jack 2026-10-08, after research_te_gap.py).
The TE gap is NOT the preseason prior (the shadow's prior beats Clay's at 0 games, -5.4% next game); it is the in-season
core on rows where no extra layer fires (+4.75% vs Clay's form, 76% of the gap in games 4-8). Clay's live form carries two
things the shadow's TE core does not: (a) CALIBRATED usage-implied evidence (uimp = -1.87 + .47 xFP + .023 route rate +
.057 snap share, lam .3 from game 1) - the shadow's earlier TE xFP test used RAW xFP, which runs 10% low for tight ends;
(b) the receiver TD-luck regression (k 6.0 x luck per game x g / (P + g) x (1 - lam)).
Variants on TE rows (shadow replica as wired, everything else identical): +uimp lam .3 / .5; +TD luck; both; both with the
WR-style usage fade. Graded vs the shadow AND vs Clay's form, next game + rest of season, error + rank, LOYO + forward,
ship bar 5/7 + 3/4. Log te_shadow_core.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "te_shadow_core2.log"), "w", encoding="utf-8") if __name__ == "__main__" else None
def P(s=""):
    print(s)
    if LOG: LOG.write(s + chr(10)); LOG.flush()


def shadow_variant(X, lam_te, luck_te, uimp, tdl, ev_raw=0.0, dock_k=1.0):
    """BR.shadow_current with a TE usage weight (on the calibrated usage-implied number) and an optional TD-luck term"""
    F = X["F"]; n = X["n"]; pos, g, wk, adp, act = X["pos"], X["g"], X["wk"], X["adp"], X["act"]
    finw = np.where(X["year"] <= 2020, 17, 18); final = wk == finw
    SH0 = SN.shadow(X); allr = ~final & (SH0 >= 3)
    base_lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
    lam = np.where(pos == "TE", lam_te, base_lam)
    xf = np.where(pos == "TE", np.where(np.isnan(uimp), X["ppg_v"], uimp), X["xf"])
    l1 = X["snap_l1"]; dev = np.zeros(n)
    for ps in ("WR", "TE"):
        m = (pos == ps) & (g >= 1) & ~np.isnan(l1) & allr
        q = np.quantile(SH0[m], np.linspace(0, 1, 9)); b_ = np.clip(np.searchsorted(q, SH0, side="right") - 1, 0, 7)
        for k in range(8):
            mk = m & (b_ == k)
            if mk.sum() >= 30: dev[mk] = l1[mk] - np.nanmean(l1[mk])
    low = np.maximum(0, 19 - np.nan_to_num(X["implied"], nan=19)) / 19
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    pid = X["A"]["pid"]; year = X["year"]
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    smx = np.where(has, C["snapmult"].values[np.maximum(idx, 0)], np.nan).astype(float); smx = np.where(np.isnan(smx) | (pos == "QB"), 1.0, smx)
    pts = np.where(pos == "TE", ev_raw * X["ppg"] + (1 - ev_raw) * X["ppg_v"], X["ppg_v"])
    ev = lam * xf + (1 - lam) * pts
    Pw = F["Pvec"] * np.where((pos == "WR") & (g == 1), 5.0, 1.0)
    Pw = Pw * np.where(X["rookie"] & (pos == "RB"), 1.6, np.where(X["rookie"] & (pos == "TE"), 2.5, 1.0))
    core = (Pw * X["prior"] + g * ev) / np.maximum(Pw + g, 1e-9)
    if luck_te: core = core + np.where((pos == "TE") & (g > 0), 6.0 * np.nan_to_num(tdl, nan=0.0) * g / np.maximum(Pw + g, 1e-9) * (1 - lam), 0.0)
    out = np.maximum(0.0, core) * X["layers"]
    for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
    out = np.where(F["on"], out * np.power(F["pm"], 0.75), out)
    out = np.where(pos == "QB", out * np.exp(0.03 * X["z"]), out)
    out = np.where((pos == "WR") & X["qbo"], out * np.where(adp <= 60, 0.85, 0.95), out)
    out = np.where(pos == "RB", out * smx, out); out = np.where(pos == "TE", out * np.power(smx, dock_k), out)
    out = np.where(pos == "WR", out * np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4), out)
    out = np.where(pos == "TE", out * np.power(np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4), dock_k), out)
    out = np.where((pos == "QB") & X["mover"], out * 0.90, out)
    out = np.where(pos == "QB", out * (1 - 0.75 * low), out)
    out = np.where((pos == "WR") & X["rookie"] & (g >= 2) & (g <= 5), out * 0.90, out)
    out = np.where((pos == "RB") & (g >= 2) & (g <= 5) & (X["car_sh"] < 0.30), out * 0.90, out)
    return np.maximum(0.0, out)


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, g, adp, name, pid = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], A["pid"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    # calibrated usage-implied number + TD luck per game, as the live form builds them
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet"))
    def joiner(D):
        k = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(D.year, D.pid, D.wk)) if isinstance(b, str)}
        ix = np.array([k.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)])
        return lambda c, d=np.nan: np.where(ix >= 0, D[c].values[np.maximum(ix, 0)].astype(float), d), ix >= 0
    cv, hasC = joiner(C); lv_, _ = joiner(L)
    from backtest_inseason_usage import route_features
    xfp, snap = cv("xfp_pg"), cv("snap_std"); rt, _ = route_features(year, pid, wk)
    ct = BR.USE_C["TE"]; useok = hasC & (g >= 1) & ~np.isnan(xfp) & ~np.isnan(snap) & ~np.isnan(rt)
    uimp = np.where(useok & (pos == "TE"), np.maximum(0.0, ct[0] + ct[1] * xfp + ct[2] * rt + ct[3] * snap), np.nan)
    tdl = lv_("td_luck_pg", 0.0)
    TE = pos == "TE"; base = top150 & ~final & ~LV["inh"]; mTE = base & TE
    P(f"=== TE SHADOW CORE: {int(mTE.sum()):,} top-150 TE player-weeks; usage-implied available on {int((mTE & ~np.isnan(uimp)).sum()):,} rows (g >= 1: {100*(mTE & (g >= 1) & ~np.isnan(uimp)).sum()/max(1, (mTE & (g >= 1)).sum()):.0f}%) ===")
    m4 = mTE & (g >= 4) & ~np.isnan(uimp)
    P(f"    level actual / number, TE 4+ games: raw xFP {act[m4].sum()/X['xf'][m4].sum():.3f}  usage-implied {act[m4].sum()/uimp[m4].sum():.3f}  ppg_v {act[m4].sum()/X['ppg_v'][m4].sum():.3f}  shadow {act[m4].sum()/SHADOW[m4].sum():.3f}  Clay form {act[m4].sum()/TODAY[m4].sum():.3f}")
    fade = np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0))
    V = {"shadow (wired)": SHADOW,
         "uimp lam .3": shadow_variant(X, 0.3, False, uimp, tdl), "uimp lam .5": shadow_variant(X, 0.5, False, uimp, tdl),
         "TD luck only": shadow_variant(X, 0.0, True, uimp, tdl),
         "uimp .3 + TD luck": shadow_variant(X, 0.3, True, uimp, tdl), "uimp .5 + TD luck": shadow_variant(X, 0.5, True, uimp, tdl),
         "uimp WR-fade + TD luck": shadow_variant(X, fade, True, uimp, tdl),
         "TD luck + raw ppg evidence": shadow_variant(X, 0.0, True, uimp, tdl, ev_raw=1.0), "TD luck + half raw ppg": shadow_variant(X, 0.0, True, uimp, tdl, ev_raw=0.5),
         "TD luck + TE docks halved": shadow_variant(X, 0.0, True, uimp, tdl, dock_k=0.5), "TD luck + raw ppg + docks halved": shadow_variant(X, 0.0, True, uimp, tdl, ev_raw=1.0, dock_k=0.5),
         "raw ppg evidence only": shadow_variant(X, 0.0, False, uimp, tdl, ev_raw=1.0)}
    # rest-of-season target / context
    seqn = defaultdict(list)
    for i in range(n):
        if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ix in seqn.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(X["layers"][ix], 0.5, 1.8)
        for a, i in enumerate(ix): nfut[i] = len(ix) - a; Tr[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    ctx0 = np.nan_to_num(ctx, nan=1.0); ros = lambda p: p / np.maximum(X["layers"], 0.3) * ctx0
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    names = [k for k in V if k != "shadow (wired)"]
    for hlab, T, m, tf in (("NEXT GAME", act, mTE, lambda p: p), ("REST OF SEASON (4+ games left)", Tr, mTE & (g >= 1) & (g <= 10) & ~np.isnan(Tr) & (nfut >= 4), ros)):
        preds = {k: tf(v) for k, v in V.items()}; b0 = preds["shadow (wired)"]; clay = tf(TODAY)
        wm = lambda p, mm: float(np.average((p[mm] - T[mm]) ** 2, weights=wt[mm])) if mm.any() else np.nan
        RS = lambda p, mm: RG.rank_stats(p, mm, T, year, wk, pos)
        P(f"\n--- {hlab}: {int(m.sum()):,} TE rows | shadow vs Clay form here {100*(wm(b0, m)/wm(clay, m)-1):+.2f}% ---")
        r0, p0 = RS(b0, m); rc, _ = RS(clay, m)
        for k in names:
            p = preds[k]; wins = sum(1 for y in YEARS if wm(p, m & (year == y)) < wm(b0, m & (year == y)) - 1e-12); r, pr = RS(p, m); rw = RG.rank_seasons(p, b0, m, T, year, wk, pos, YEARS)
            fw = 100 * (wm(p, m & (year >= 2022)) / wm(b0, m & (year >= 2022)) - 1); fwins = sum(1 for y in FWD if wm(p, m & (year == y)) < wm(b0, m & (year == y)) - 1e-12)
            P(f"  {k:26s} vs shadow {100*(wm(p, m)/wm(b0, m)-1):+6.2f}% ({wins}/7) fwd {fw:+6.2f}% ({fwins}/4) | vs Clay form {100*(wm(p, m)/wm(clay, m)-1):+6.2f}% | rho {r:.4f} ({r - r0:+.4f} vs shadow, {r - rc:+.4f} vs Clay, {rw}/7) | pairs {pr - p0:+.2f} | level {T[m].sum()/p[m].sum():.3f}")
        P("  cuts (vs shadow / vs Clay), TD luck + raw ppg evidence:")
        p = preds["TD luck + raw ppg evidence"]
        for clab, cm in (("ADP <= 60", adpx <= 60), ("ADP 61-150", adpx > 60), ("games 1-3", (g >= 1) & (g <= 3)), ("games 4-8", (g >= 4) & (g <= 8)), ("games 9+", g >= 9), ("rookies", X["rookie"])):
            mm = m & cm
            if mm.sum() < 30: continue
            P(f"    {clab:12s} n{int(mm.sum()):4d} | vs shadow {100*(wm(p, mm)/wm(b0, mm)-1):+6.2f}% | vs Clay {100*(wm(p, mm)/wm(clay, mm)-1):+6.2f}% (shadow was {100*(wm(b0, mm)/wm(clay, mm)-1):+6.2f}%)")
        pick = lambda yrs: min(["shadow (wired)"] + names, key=lambda k: wm(preds[k], m & np.isin(year, yrs)))
        for flab, folds in (("LOYO", LOSO), ("forward", FORW)):
            pr_ = b0.copy(); picks = []; wins = 0
            for tr, te in folds:
                k = pick(tr); picks.append(k); mm = year == te; pr_[mm] = preds[k][mm]; wins += wm(preds[k], m & mm) < wm(b0, m & mm) - 1e-12
            tem = m & np.isin(year, [te for _, te in folds]); r, _ = RS(pr_, tem); r0_, _ = RS(b0, tem)
            P(f"  pick {flab:8s}: error {100*(wm(pr_, tem)/wm(b0, tem)-1):+.2f}% vs shadow ({wins}/{len(folds)}), {100*(wm(pr_, tem)/wm(clay, tem)-1):+.2f}% vs Clay form | rho {r - r0_:+.4f} | picks {picks}")
    P("\nLimitations: shadow replica (harness form + as-wired layers); the usage-implied coefficients are the live form's (fit on these seasons - the LOYO / forward picks are the honest read); book anchor / docks / prior lift not replayed.")
    LOG.close()


if __name__ == "__main__":
    main()
