#!/usr/bin/env python3
"""TE blend weight AFTER the shadow TE core fix (TD-luck term + TE docks halved): can tight ends come back onto the blend?
Grid w on TE rows, next game + rest of season, error + rank vs Clay form (w 0 = today's TE number). Log te_core_blend.log."""
import os, sys, warnings
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import backtest_te_shadow_core as TC
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "te_core_blend.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, g, adp, name, pid = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"], A["pid"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    L = pd.read_parquet(os.path.join(HERE, "ctx_live_layers.parquet")); k = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(L.year, L.pid, L.wk)) if isinstance(b, str)}
    ix = np.array([k.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); tdl = np.where(ix >= 0, L["td_luck_pg"].values[np.maximum(ix, 0)].astype(float), 0.0)
    uimp = np.full(n, np.nan)
    NEW = {"TD luck only": TC.shadow_variant(X, 0.0, True, uimp, tdl), "TD luck + docks halved": TC.shadow_variant(X, 0.0, True, uimp, tdl, dock_k=0.5)}
    TE = pos == "TE"; mTE = top150 & ~final & ~LV["inh"] & TE
    seqn = defaultdict(list)
    for i in range(n):
        if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ixs in seqn.values():
        ixs.sort(key=lambda i: wk[i]); a_ = act[ixs]; l_ = np.clip(X["layers"][ixs], 0.5, 1.8)
        for a, i in enumerate(ixs): nfut[i] = len(ixs) - a; Tr[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    ctx0 = np.nan_to_num(ctx, nan=1.0); ros = lambda p: p / np.maximum(X["layers"], 0.3) * ctx0
    WG = (0.0, 0.2, 0.3, 0.5, 0.7, 1.0)
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    for lab, SH in (("shadow as wired", SHADOW), *NEW.items()):
        P(""); P(f"=== TE blend with {lab} ===")
        for hlab, T, m, tf in (("NEXT GAME", act, mTE, lambda p: p), ("REST OF SEASON", Tr, mTE & (g >= 1) & (g <= 10) & ~np.isnan(Tr) & (nfut >= 4), ros)):
            wm = lambda p, mm: float(np.average((p[mm] - T[mm]) ** 2, weights=wt[mm])) if mm.any() else np.nan
            RS = lambda p, mm: RG.rank_stats(p, mm, T, year, wk, pos)
            bl = {w: tf(w * SH + (1 - w) * TODAY) for w in WG}; b0 = bl[0.0]; r0, p0 = RS(b0, m)
            P(f"  {hlab} (n{int(m.sum())}): " + " | ".join(f"w {w:.1f}: err {100*(wm(bl[w], m)/wm(b0, m)-1):+.2f}% ({sum(1 for y in YEARS if wm(bl[w], m & (year == y)) < wm(b0, m & (year == y)) - 1e-12)}/7) rho {RS(bl[w], m)[0] - r0:+.4f} ({RG.rank_seasons(bl[w], b0, m, T, year, wk, pos, YEARS)}/7)" for w in WG[1:]))
            for obj, pick in (("error", lambda yrs, mm=m: min(WG, key=lambda w: wm(bl[w], mm & np.isin(year, yrs)))), ("rank", lambda yrs, mm=m: max(WG, key=lambda w: RS(bl[w], mm & np.isin(year, yrs))[0]))):
                for flab, folds in (("LOYO", LOSO), ("forward", FORW)):
                    picks = [pick(tr) for tr, te in folds]; pr = b0.copy()
                    for (tr, te), w in zip(folds, picks): pr[year == te] = bl[w][year == te]
                    tem = m & np.isin(year, [te for _, te in folds]); r, _ = RS(pr, tem); r0_, _ = RS(b0, tem)
                    P(f"    picked on {obj:5s} {flab:8s}: {picks} -> err {100*(wm(pr, tem)/wm(b0, tem)-1):+.2f}% rho {r - r0_:+.4f} vs w 0")
    LOG.close()


if __name__ == "__main__":
    main()
