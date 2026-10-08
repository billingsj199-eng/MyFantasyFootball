#!/usr/bin/env python3
"""
CLAY-FREE ENSEMBLE + PRIOR STRENGTH BY TIER (Jack 2026-10-08: "what else can we test to get rid of the blend").
Part of the blend's edge over the shadow alone is plain ensembling: two models with different evidence handling averaged.
The Clay-side live form differs from the shadow in structure (prior strength 5, calibrated usage-implied evidence, TD luck
sized for P 5, QB floor, RB snap mix, rookie level) - not only in its prior. So:
  A  LIVE FORM ON THE SHADOW'S PRIOR: the live machinery with Clay's per-game number replaced by the shadow's preseason
     prior (history + ADP + ridge + opportunity). Clay-free. Graded alone and blended with the shadow (w .3 .. .7) against
     the shadow alone and against the wired Clay blend, next game + rest of season, error + rank, LOYO + forward per position.
  B  SHADOW PRIOR STRENGTH BY ADP TIER: P x k per (position, ADP band), k .5 / 1 / 1.5 / 2, picked LOYO / forward.
Log clayfree_ensemble.log.
"""
import json, os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; cal = SN.NW.cal; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "clayfree_ensemble.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
BBW = {"QB": 0.5, "RB": 0.8, "WR": 0.7, "TE": 0.0}
LIVE_P = BR.LIVE_P; TDK = BR.TDK; USE_C = BR.USE_C


def live_form(X, prior_pg):
    """BR.live_today with the per-game prior supplied (Clay's number or the shadow's prior); everything else as wired"""
    F = X["F"]; A = F["A"]; n = X["n"]
    act, year, wk, pos, g, ppg, layers, adp, pid, name = A["act"], A["year"], A["wk"], A["pos"], A["g"], A["ppg"], A["layers"], F["adp"], A["pid"], A["name"]
    ch = json.load(open(os.path.join(cal.REPO, "data", "clay_history.json"), encoding="utf-8")); mu_y = {}
    for y in YEARS:
        wy = 16.0 if y <= 2020 else 17.0
        lv = sorted([max(0.2, (c.get("pts") or 0) - (c.get("rec") or 0) / 2.0) / wy for c in ch[str(y)].values() if c.get("pos") == "QB"], reverse=True)[:32]; mu_y[y] = float(np.mean(lv))
    mu = np.array([mu_y[int(y)] for y in year])
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet"))
    def joiner(D):
        k = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(D.year, D.pid, D.wk)) if isinstance(b, str)}
        ix = np.array([k.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)])
        return lambda c, d=np.nan: np.where(ix >= 0, D[c].values[np.maximum(ix, 0)].astype(float), d), ix >= 0
    cv, hasC = joiner(C); lv_, hasL = joiner(L)
    from backtest_inseason_usage import route_features
    xfp, snap = cv("xfp_pg"), cv("snap_std"); rt, _ = route_features(year, pid, wk)
    useok = hasC & (g >= 1) & ~np.isnan(xfp) & ~np.isnan(snap) & ~np.isnan(rt)
    lam_wr = np.select([g <= 2, g <= 5, g <= 8], [0.8, 0.6, 0.5], 0.3); lam_te = np.full(n, 0.3)
    lam = np.where(useok & (pos == "WR"), lam_wr, np.where(useok & (pos == "TE"), lam_te, 0.0))
    cw, ct = USE_C["WR"], USE_C["TE"]
    uimp = np.maximum(0.0, np.nan_to_num(np.where(pos == "WR", cw[0] + cw[1] * xfp + cw[2] * rt + cw[3] * snap, ct[0] + ct[1] * xfp + ct[2] * rt + ct[3] * snap), nan=0.0))
    ppg0 = np.maximum(0.0, ppg)
    tdl = np.nan_to_num(lv_("td_luck_pg", 0.0), nan=0.0); tdk = np.array([TDK[p_] for p_ in pos])
    rook = np.nan_to_num(lv_("rookie_mult", 1.0), nan=1.0); cond = np.nan_to_num(lv_("cond_mult", 1.0), nan=1.0)
    wx = np.nan_to_num(lv_("weather_mult", 1.0), nan=1.0); pool = np.nan_to_num(lv_("pool_mult", 1.0), nan=1.0)
    inh = np.nan_to_num(lv_("qb_inherit_mult", 1.0), nan=1.0) > 1.0
    rbu = lv_("usage_half"); rbu = np.where(pos == "RB", rbu, np.nan)
    snapm = np.nan_to_num(cv("snapmult", 1.0), nan=1.0)
    chain = layers * snapm * cond * wx * pool
    PS = np.where((pos == "WR") & (lam > 0) & (np.isnan(adp) | (adp > 60)), 4.0, float(LIVE_P))
    ev = np.where(lam > 0, lam * uimp + (1 - lam) * ppg0, ppg0)
    base = np.where(g > 0, (PS * prior_pg + g * ev) / (PS + g), prior_pg) * rook
    fl = (pos == "QB") & ~inh & (base >= 5) & (base < mu); base = np.where(fl, mu + 0.70 * (base - mu), base)
    base = np.where(~np.isnan(rbu), 0.85 * base + 0.15 * np.nan_to_num(rbu, nan=0.0), base)
    luck = np.where(g > 0, tdk * tdl * g / (LIVE_P + g) * (1 - lam), 0.0)
    return np.maximum(0.0, base * chain + luck)


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    bw = np.array([BBW[p_] for p_ in pos]); BLEND = bw * SHADOW + (1 - bw) * TODAY
    LFS = live_form(X, X["prior"])                                   # live machinery on the shadow's prior (Clay-free)
    chk = live_form(X, LV["clay_gm"]); P(f"replica check: live form with Clay's prior vs BR.live_today max |diff| {np.nanmax(np.abs(chk - TODAY)):.4f}")
    base = top150 & ~final & ~LV["inh"]
    seqn = defaultdict(list)
    for i in range(n):
        if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ix in seqn.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(X["layers"][ix], 0.5, 1.8)
        for a, i in enumerate(ix): nfut[i] = len(ix) - a; Tr[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    ctx0 = np.nan_to_num(ctx, nan=1.0); ros = lambda p: p / np.maximum(X["layers"], 0.3) * ctx0
    baseR = base & (g >= 1) & (g <= 10) & ~np.isnan(Tr) & (nfut >= 4) & (TODAY >= 3)
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    WG = (0.0, 0.3, 0.5, 0.7, 1.0)
    P(f"=== A  CLAY-FREE ENSEMBLE: shadow x live-form-on-shadow-prior, {int(base.sum()):,} top-150 player-weeks ===")
    for hlab, T, m, tf in (("NEXT GAME", act, base, lambda p: p), ("REST OF SEASON (4+ left)", Tr, baseR, ros)):
        S, L_, C, B = tf(SHADOW), tf(LFS), tf(TODAY), tf(BLEND)
        wm = lambda p, mm: float(np.average((p[mm] - T[mm]) ** 2, weights=wt[mm])) if mm.any() else np.nan
        RS = lambda p, mm: RG.rank_stats(p, mm, T, year, wk, pos)
        ens = lambda w: w * S + (1 - w) * L_
        P(f"\n--- {hlab} ---")
        P(f"  level act/number: shadow {T[m].sum()/S[m].sum():.3f}  live-on-shadow-prior {T[m].sum()/L_[m].sum():.3f}  Clay form {T[m].sum()/C[m].sum():.3f}  wired blend {T[m].sum()/B[m].sum():.3f}")
        r_s, p_s = RS(S, m); r_b, p_b = RS(B, m)
        for lab, p in (("live form on the shadow prior (alone)", L_), ("ensemble w .3 shadow", ens(0.3)), ("ensemble w .5", ens(0.5)), ("ensemble w .7", ens(0.7)), ("wired Clay blend (reference)", B), ("Clay form (reference)", C)):
            wins = sum(1 for y in YEARS if wm(p, m & (year == y)) < wm(S, m & (year == y)) - 1e-12); wb = sum(1 for y in YEARS if wm(p, m & (year == y)) < wm(B, m & (year == y)) - 1e-12); r, pr = RS(p, m)
            P(f"  {lab:40s} vs shadow {100*(wm(p, m)/wm(S, m)-1):+6.2f}% ({wins}/7) | vs wired blend {100*(wm(p, m)/wm(B, m)-1):+6.2f}% ({wb}/7) | rho {r:.4f} ({r - r_s:+.4f} vs shadow, {r - r_b:+.4f} vs blend) | pairs {pr - p_s:+.2f}")
        P("  by position, ensemble w .5 vs shadow | vs wired blend:")
        for ps in POS4:
            mm = m & (pos == ps); best = min(WG, key=lambda w: wm(ens(w), mm))
            P(f"    {ps}: best w {best:.1f} | w .5 vs shadow {100*(wm(ens(0.5), mm)/wm(S, mm)-1):+6.2f}%, vs blend {100*(wm(ens(0.5), mm)/wm(B, mm)-1):+6.2f}% | live-on-prior alone vs shadow {100*(wm(L_, mm)/wm(S, mm)-1):+6.2f}% | best w vs blend {100*(wm(ens(best), mm)/wm(B, mm)-1):+6.2f}%")
        for flab, folds in (("LOYO", LOSO), ("forward", FORW)):
            out = S.copy(); picks = {ps: [] for ps in POS4}
            for tr, te in folds:
                for ps in POS4:
                    mm = m & (pos == ps) & np.isin(year, tr); w = min(WG, key=lambda w_: wm(ens(w_), mm)); picks[ps].append(w); sel = (pos == ps) & (year == te); out[sel] = ens(w)[sel]
            tem = m & np.isin(year, [te for _, te in folds]); r, _ = RS(out, tem); r0, _ = RS(S, tem); rb, _ = RS(B, tem)
            wins = sum(1 for _, te in folds if wm(out, tem & (year == te)) < wm(S, tem & (year == te)) - 1e-12); wb = sum(1 for _, te in folds if wm(out, tem & (year == te)) < wm(B, tem & (year == te)) - 1e-12)
            P(f"  {flab:8s} per-position pick: vs shadow {100*(wm(out, tem)/wm(S, tem)-1):+.2f}% ({wins}/{len(folds)}), vs wired blend {100*(wm(out, tem)/wm(B, tem)-1):+.2f}% ({wb}/{len(folds)}) | rho {r - r0:+.4f} vs shadow, {r - rb:+.4f} vs blend | picks " + " | ".join(f"{ps} {picks[ps]}" for ps in POS4))
    # ---------------- B prior strength by tier
    P(f"\n=== B  SHADOW PRIOR STRENGTH BY ADP TIER (P x k per position x band) ===")
    BANDS = (("1-30", adpx <= 30), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100)), ("101-150", (adpx > 100) & (adpx <= 150)))
    KG = (0.5, 1.0, 1.5, 2.0)
    def shadow_k(kmap):
        F2 = dict(F); Pv = F["Pvec"].copy()
        for (ps, blab), k in kmap.items():
            bm = dict(BANDS)[blab]; Pv = np.where((pos == ps) & bm, Pv * k, Pv)
        F2["Pvec"] = Pv; X2 = dict(X); X2["F"] = F2; return BR.shadow_current(X2)[0]
    cache = {k: shadow_k({(ps, b): k for ps in POS4 for b, _ in BANDS}) for k in KG}   # one global k per run, read per cell
    for hlab, T, m, tf in (("NEXT GAME", act, base, lambda p: p), ("REST OF SEASON (4+ left)", Tr, baseR, ros)):
        wm = lambda p, mm: float(np.average((p[mm] - T[mm]) ** 2, weights=wt[mm])) if mm.any() else np.nan
        S = tf(SHADOW); B = tf(BLEND); SK = {k: tf(v) for k, v in cache.items()}
        P(f"\n--- {hlab}: error vs shadow (P x 1) per cell; k picked LOYO / forward per cell ---")
        for ps in POS4:
            cells = []
            for blab, bm in BANDS:
                mm = m & (pos == ps) & bm
                if mm.sum() < 60: cells.append(f"{blab}: n{int(mm.sum())}"); continue
                best = min(KG, key=lambda k: wm(SK[k], mm)); cells.append(f"{blab}: " + " ".join(f"k{k:g} {100*(wm(SK[k], mm)/wm(S, mm)-1):+.1f}%" for k in KG if k != 1.0) + f" (best {best:g})")
            P(f"  {ps}: " + " | ".join(cells))
        for flab, folds in (("LOYO", LOSO), ("forward", FORW)):
            out = S.copy(); nmoved = 0
            for tr, te in folds:
                for ps in POS4:
                    for blab, bm in BANDS:
                        mm = m & (pos == ps) & bm & np.isin(year, tr)
                        if mm.sum() < 60: continue
                        k = min(KG, key=lambda k_: wm(SK[k_], mm)); sel = (pos == ps) & bm & (year == te); out[sel] = SK[k][sel]; nmoved += int(k != 1.0)
            tem = m & np.isin(year, [te for _, te in folds]); r, _ = RG.rank_stats(out, tem, T, year, wk, pos); r0, _ = RG.rank_stats(S, tem, T, year, wk, pos)
            wins = sum(1 for _, te in folds if wm(out, tem & (year == te)) < wm(S, tem & (year == te)) - 1e-12)
            P(f"  {flab:8s} per-cell pick: vs shadow {100*(wm(out, tem)/wm(S, tem)-1):+.2f}% ({wins}/{len(folds)}), vs wired blend {100*(wm(out, tem)/wm(B, tem)-1):+.2f}% | rho {r - r0:+.4f} | cells off k 1: {nmoved}")
    P("\nLimitations: replicas (honest shadow; live form without the book anchor / docks / prior lift); the live-form-on-shadow-prior keeps the live form's usage coefficients (fit on these seasons).")
    LOG.close()


if __name__ == "__main__":
    main()
