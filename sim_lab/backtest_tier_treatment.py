#!/usr/bin/env python3
"""
TIER TREATMENT (Jack 2026-10-08: "grade them separately - bottom players can't be as projectable as top finishers, treat
different preseason ADPs differently"). The top-100 cubed-weight ablation (ablate_shadow_next_top100_p3.log) showed the
model's level differs by band (31-60 under by 2.6%, 13-30 QBs over by 5%) and that two layers help the middle while costing
the top 30 (RB snap trend +0.25% on the top 30, QB game-total tilt +0.12%). Honest replica, next game:
  T1  band x position level multipliers (ADP 1-12 / 13-30 / 31-60 / 61-100), picked per cell LOYO + forward, whole-board guard
  T2  RB snap-trend DOCKS switched off for ADP <= 30 (lifts kept)       T3  QB game-total tilt off for ADP <= 30
Grading reported by band (top 30 / 31-100) with cubed ADP weights on the top 100, plus the old top-150 squared weights.
Log tier_treatment.log.
"""
import os, sys, warnings
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "tier_treatment.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def shadow_variant(X, rb_nodock_adp=None, qb_tilt_min_adp=None):
    """BR.shadow_current with two tier switches: RB snap-trend docks off under an ADP, QB game-total tilt off under an ADP"""
    F = X["F"]; n = X["n"]; pos, g, wk, adp, act = X["pos"], X["g"], X["wk"], X["adp"], X["act"]
    finw = np.where(X["year"] <= 2020, 17, 18); final = wk == finw
    SH0 = SN.shadow(X); allr = ~final & (SH0 >= 3)
    base_lam = np.where(pos == "WR", np.maximum(.25, 1 - .08 * np.maximum(g - 1, 0)), np.where(pos == "RB", np.maximum(.25, 1 - .3 * np.maximum(g - 1, 0)), 0.0))
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
    if rb_nodock_adp is not None: smx = np.where((pos == "RB") & (adp <= rb_nodock_adp) & (smx < 1), 1.0, smx)
    ev = base_lam * X["xf"] + (1 - base_lam) * X["ppg_v"]
    Pw = F["Pvec"] * np.where((pos == "WR") & (g == 1), 5.0, 1.0)
    Pw = Pw * np.where(X["rookie"] & (pos == "RB"), 1.6, np.where(X["rookie"] & (pos == "TE"), 2.5, 1.0))
    out = (Pw * X["prior"] + g * ev) / np.maximum(Pw + g, 1e-9) * X["layers"]
    L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet")); lk = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(L.year, L.pid, L.wk)) if isinstance(b, str)}
    lix = np.array([lk.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); tdl = np.where(lix >= 0, L["td_luck_pg"].values[np.maximum(lix, 0)].astype(float), 0.0)
    tdk = np.array([BR.TDK[p_] for p_ in pos]); luckT = np.where(g > 0, tdk * np.nan_to_num(tdl, nan=0.0) * g / np.maximum(Pw + g, 1e-9) * (1 - base_lam), 0.0)
    for gi, m_ in enumerate([0.7, 0.8], start=1): out = np.where(F["buried_rk"] & (wk == gi), out * m_, out)
    out = np.where(F["on"], out * np.power(F["pm"], 0.75), out)
    tilt = np.exp(0.03 * X["z"])
    if qb_tilt_min_adp is not None: tilt = np.where(adp <= qb_tilt_min_adp, 1.0, tilt)
    out = np.where(pos == "QB", out * tilt, out)
    out = np.where((pos == "WR") & X["qbo"], out * np.where(adp <= 60, 0.85, 0.95), out)
    tek = lambda M: np.where(M < 1, np.sqrt(M), np.sqrt(M))
    out = np.where(pos == "RB", out * smx, out); out = np.where(pos == "TE", out * tek(smx), out)
    out = np.where(pos == "WR", out * np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4), out)
    out = np.where(pos == "TE", out * tek(np.clip(1 + 0.3 * dev / 100.0, 0.7, 1.4)), out)
    out = np.where((pos == "QB") & X["mover"], out * 0.90, out)
    out = np.where(pos == "QB", out * (1 - 0.75 * low), out)
    out = np.where((pos == "RB") & (g >= 2) & (g <= 5) & (X["car_sh"] < 0.30), out * 0.90, out)
    return np.maximum(0.0, out + luckT)


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & (adpx <= 150)].mean()
    wt2 = np.maximum(0.05, lv) ** 2; wt3 = np.maximum(0.05, lv) ** 3
    TODAY, LV = BR.live_today(X); SHADOW = shadow_variant(X)
    chk = BR.shadow_current(X)[0]; P(f"replica check vs BR.shadow_current: max |diff| {np.nanmax(np.abs(chk - SHADOW)):.4f}")
    base100 = (adpx <= 100) & ~final & ~LV["inh"] & (SHADOW >= 3); base150 = (adpx <= 150) & ~final & ~LV["inh"] & (SHADOW >= 3)
    BANDS = (("ADP 1-12", adpx <= 12), ("13-30", (adpx > 12) & (adpx <= 30)), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100)), ("101-150", (adpx > 100) & (adpx <= 150)))   # 101-150 added (Jack 10-08)
    w3 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt3[m])) if m.any() else np.nan
    w2 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt2[m])) if m.any() else np.nan
    RS = lambda p, m: RG.rank_stats(p, m, act, year, wk, pos)
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    def report(lab, p, m):
        r, pr = RS(p, m); r0, p0 = RS(SHADOW, m); wins = sum(1 for y in YEARS if w3(p, m & (year == y)) < w3(SHADOW, m & (year == y)) - 1e-12)
        P(f"  {lab:46s} top-100 cubed {100*(w3(p, base100)/w3(SHADOW, base100)-1):+6.2f}% ({wins}/7 on its rows) | top-30 {100*(w3(p, base100 & (adpx <= 30))/w3(SHADOW, base100 & (adpx <= 30))-1):+6.2f}% | 31-100 {100*(w3(p, base100 & (adpx > 30))/w3(SHADOW, base100 & (adpx > 30))-1):+6.2f}% | top-150 sq {100*(w2(p, base150)/w2(SHADOW, base150)-1):+6.2f}% | rank {r - r0:+.4f} pairs {pr - p0:+.2f}")
    P(f"=== TIER TREATMENT: {int(base100.sum()):,} top-100 player-weeks (cubed ADP weights) ===")
    P("  level by band, shadow (act/proj): " + " | ".join(f"{bl} {act[base150 & bm].sum()/SHADOW[base150 & bm].sum():.3f} (" + " ".join(f"{ps} {act[base150 & bm & (pos == ps)].sum()/max(1e-9, SHADOW[base150 & bm & (pos == ps)].sum()):.3f}" for ps in POS4 if (base150 & bm & (pos == ps)).sum() >= 30) + ")" for bl, bm in BANDS))
    P("  pairs ordered right by band: " + " | ".join(f"{bl} {RS(SHADOW, base150 & bm)[1]:.1f}%" for bl, bm in BANDS))
    P("\n--- T2 / T3: tier switches on the layers that cost the top 30 ---")
    for lab, p in (("T2 RB snap-trend docks off, ADP <= 30", shadow_variant(X, rb_nodock_adp=30)), ("T2' RB snap-trend docks off, ADP <= 60", shadow_variant(X, rb_nodock_adp=60)), ("T3 QB game-total tilt off, ADP <= 30", shadow_variant(X, qb_tilt_min_adp=30)), ("T2 + T3", shadow_variant(X, rb_nodock_adp=30, qb_tilt_min_adp=30))):
        report(lab, p, base100)
        m = base100 & ((pos == "RB") & (adpx <= 30) if lab.startswith("T2 RB") else (pos == "QB") & (adpx <= 30) if lab.startswith("T3") else (adpx <= 30))
        pr = SHADOW.copy(); wins = 0; picks = []
        for tr, te in LOSO:
            kk = "on" if w3(p, m & np.isin(year, tr)) < w3(SHADOW, m & np.isin(year, tr)) else "off"; picks.append(kk); mm = year == te
            if kk == "on": pr[mm] = p[mm]
            wins += w3(p, m & mm) < w3(SHADOW, m & mm) - 1e-12
        fw = sum(1 for y in FWD if w3(p, m & (year == y)) < w3(SHADOW, m & (year == y)) - 1e-12)
        P(f"      on its own rows (n{int(m.sum())}): fixed {100*(w3(p, m)/w3(SHADOW, m)-1):+.2f}% | LOYO wins {wins}/7 picks {picks} | forward wins {fw}/4")
    P("\n--- T1: band x position level multipliers, picked per cell LOYO / forward; applied together ---")
    GR = (0.94, 0.97, 1.03, 1.06, 1.09)
    def cellpick(ps, bm, yrs):
        m = base150 & bm & (pos == ps) & np.isin(year, yrs)
        if m.sum() < 80: return 1.0
        return min(GR + (1.0,), key=lambda k: w3(SHADOW * k, m))
    for flab, folds in (("LOYO", LOSO), ("forward", FORW)):
        out = SHADOW.copy(); picks = {}
        for tr, te in folds:
            for bl, bm in BANDS:
                for ps in POS4:
                    k = cellpick(ps, bm, tr); picks.setdefault((bl, ps), []).append(k); sel = bm & (pos == ps) & (year == te); out[sel] = SHADOW[sel] * k
        tem = base100 & np.isin(year, [te for _, te in folds]); tem150 = base150 & np.isin(year, [te for _, te in folds]); wins = sum(1 for _, te in folds if w3(out, tem & (year == te)) < w3(SHADOW, tem & (year == te)) - 1e-12)
        r, pr = RS(out, tem); r0, p0 = RS(SHADOW, tem)
        P(f"  {flab:8s}: top-100 cubed {100*(w3(out, tem)/w3(SHADOW, tem)-1):+.2f}% ({wins}/{len(folds)}) | top-30 {100*(w3(out, tem & (adpx <= 30))/w3(SHADOW, tem & (adpx <= 30))-1):+.2f}% | 31-100 {100*(w3(out, tem & (adpx > 30))/w3(SHADOW, tem & (adpx > 30))-1):+.2f}% | 101-150 {100*(w2(out, tem150 & (adpx > 100))/w2(SHADOW, tem150 & (adpx > 100))-1):+.2f}% | top-150 sq {100*(w2(out, tem150)/w2(SHADOW, tem150)-1):+.2f}% | rank {r - r0:+.4f} pairs {pr - p0:+.2f}")
        P("      picks: " + " | ".join(f"{bl} {ps} {picks[(bl, ps)]}" for bl, _ in BANDS for ps in POS4 if (bl, ps) in picks and any(k != 1.0 for k in picks[(bl, ps)])))
    P("\nLimitations: honest replica (no book anchor / docks / prior lift); level multipliers are the crudest tier treatment - a pass here says the bias is stable by band, a fail says it is not.")
    LOG.close()


if __name__ == "__main__":
    main()
