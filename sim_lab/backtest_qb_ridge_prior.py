#!/usr/bin/env python3
"""
QB PRESEASON PRIOR FROM THE RIDGE (Jack 2026-10-08 "what else can we improve to get rid of the blend").
research_pos_gap.py QB: the shadow's remaining QB gap to the blend is the PRIOR - at 0 games the hand prior is +3.7% worse
than Clay's number next game and +12.8% on the rest of season (second-year QBs +14%, ADP 31-60 +6.6%). Every other position
mixes the season-long ridge (ADP + history + string, backtest_season_long.py) into its prior at 50%; quarterbacks were left
out on 09-16 because the ridge lost to Clay's season sheet for QBs (+3.5%). The hand prior loses by far more, so: QB prior =
w x ridge + (1 - w) x hand, w 0 / .25 / .5 / .75 / 1; also a QB ridge with an explicit second-year term re-fit per fold.
Graded on QB rows next game + rest of season vs the shadow (and vs Clay's form / the blend), LOYO + forward, error + rank.
Log qb_ridge_prior.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; SL = SN.SL; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "qb_ridge_prior.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
BBW = {"QB": 0.5, "RB": 0.8, "WR": 0.7, "TE": 0.0}


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    bw = np.array([BBW[p_] for p_ in pos]); BLEND = bw * SHADOW + (1 - bw) * TODAY
    QB = pos == "QB"; base = top150 & ~final & ~LV["inh"]; mQ = base & QB
    # the season-long ridge for every row (SN.setup keeps it off QB rows)
    T = SL.build_table(); LIVE = [f for f in SL.BASIC if f != "mover"] + ["jm"]
    v = SL.loyo(T, LIVE, "ridge", 10.0); key = {(int(y), nm, ps): x for y, nm, ps, x in zip(T.year, T.name, T.pos, v)}
    ridge = np.array([key.get((int(year[i]), name[i], pos[i]), np.nan) for i in range(n)])
    hand = F["prior"]; hasR = QB & ~np.isnan(ridge)
    # QB-only ridge (fit on QB rows alone, same features) - the pooled fit may be WR-shaped
    Tq = T[T.pos == "QB"].reset_index(drop=True); vq = SL.loyo(Tq, LIVE, "ridge", 10.0); keyq = {(int(y), nm): x for y, nm, x in zip(Tq.year, Tq.name, vq)}
    ridgeq = np.array([keyq.get((int(year[i]), name[i]), np.nan) if pos[i] == "QB" else np.nan for i in range(n)]); hasRq = QB & ~np.isnan(ridgeq)
    P(f"=== QB RIDGE PRIOR: {int(mQ.sum()):,} top-150 QB player-weeks; pooled ridge on {int((mQ & hasR).sum()):,} rows, QB-only ridge on {int((mQ & hasRq).sum()):,} ===")
    m0 = mQ & (g == 0) & hasR; L = X["layers"]; clay_gm = LV["clay_gm"]
    wm = lambda p, m, Tt=act: float(np.average((p[m] - Tt[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    P(f"  prior alone at 0 games (n{int(m0.sum())}), error vs Clay per game, next game: hand {100*(wm(hand*L, m0)/wm(clay_gm*L, m0)-1):+.2f}% | pooled ridge {100*(wm(ridge*L, m0)/wm(clay_gm*L, m0)-1):+.2f}% | QB-only ridge {100*(wm(np.where(hasRq, ridgeq, hand)*L, m0)/wm(clay_gm*L, m0)-1):+.2f}% | 50/50 hand+ridge {100*(wm(0.5*(hand+ridge)*L, m0)/wm(clay_gm*L, m0)-1):+.2f}%")
    P(f"  level act/prior at 0 games: hand {act[m0].sum()/(hand*L)[m0].sum():.3f} pooled ridge {act[m0].sum()/(ridge*L)[m0].sum():.3f} QB-only {act[m0].sum()/(np.where(hasRq, ridgeq, hand)*L)[m0].sum():.3f} Clay {act[m0].sum()/(clay_gm*L)[m0].sum():.3f}")
    def swap(pr):
        X2 = dict(X); X2["prior"] = np.where(QB, pr, X["prior"]); return BR.shadow_current(X2)[0]
    V = {"shadow (hand prior)": SHADOW}
    for w in (0.25, 0.5, 0.75, 1.0): V[f"pooled ridge w {w:.2f}"] = swap(np.where(hasR, w * ridge + (1 - w) * hand, hand))
    for w in (0.5, 1.0): V[f"QB-only ridge w {w:.2f}"] = swap(np.where(hasRq, w * ridgeq + (1 - w) * hand, hand))
    # rest-of-season target / context
    seqn = defaultdict(list)
    for i in range(n):
        if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ix in seqn.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(L[ix], 0.5, 1.8)
        for a, i in enumerate(ix): nfut[i] = len(ix) - a; Tr[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    ctx0 = np.nan_to_num(ctx, nan=1.0); ros = lambda p: p / np.maximum(L, 0.3) * ctx0
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    names = [k for k in V if k != "shadow (hand prior)"]
    for hlab, Tt, m, tf in (("NEXT GAME", act, mQ, lambda p: p), ("REST OF SEASON (4+ games left)", Tr, mQ & (g >= 1) & (g <= 10) & ~np.isnan(Tr) & (nfut >= 4), ros)):
        preds = {k: tf(p) for k, p in V.items()}; b0 = preds["shadow (hand prior)"]; clay = tf(TODAY); bl = tf(BLEND)
        RS = lambda p, mm: RG.rank_stats(p, mm, Tt, year, wk, pos)
        P(f"\n--- {hlab}: {int(m.sum()):,} QB rows | shadow vs Clay form {100*(wm(b0, m, Tt)/wm(clay, m, Tt)-1):+.2f}%, vs blend {100*(wm(b0, m, Tt)/wm(bl, m, Tt)-1):+.2f}% ---")
        r0, p0 = RS(b0, m); rb, _ = RS(bl, m)
        for k in names:
            p = preds[k]; wins = sum(1 for y in YEARS if wm(p, m & (year == y), Tt) < wm(b0, m & (year == y), Tt) - 1e-12); r, pr = RS(p, m); rw = RG.rank_seasons(p, b0, m, Tt, year, wk, pos, YEARS)
            fw = 100 * (wm(p, m & (year >= 2022), Tt) / wm(b0, m & (year >= 2022), Tt) - 1); fwins = sum(1 for y in FWD if wm(p, m & (year == y), Tt) < wm(b0, m & (year == y), Tt) - 1e-12)
            P(f"  {k:24s} vs shadow {100*(wm(p, m, Tt)/wm(b0, m, Tt)-1):+6.2f}% ({wins}/7) fwd {fw:+6.2f}% ({fwins}/4) | vs Clay {100*(wm(p, m, Tt)/wm(clay, m, Tt)-1):+6.2f}% | vs BLEND {100*(wm(p, m, Tt)/wm(bl, m, Tt)-1):+6.2f}% | rho {r:.4f} ({r - r0:+.4f} vs shadow, {r - rb:+.4f} vs blend, {rw}/7) | pairs {pr - p0:+.2f} | level {Tt[m].sum()/p[m].sum():.3f}")
        P("  cuts, pooled ridge w .50 vs shadow / vs blend:")
        p = preds["pooled ridge w 0.50"]
        for clab, cm in (("ADP <= 60", adpx <= 60), ("ADP 61-150", adpx > 60), ("games 0-3", g <= 3), ("games 4-8", (g >= 4) & (g <= 8)), ("games 9+", g >= 9), ("2nd year", (~X["rookie"]) & (np.array(A["exp"], float) == 1)), ("rookies", X["rookie"]), ("vets 3+ yrs", np.array(A["exp"], float) >= 2)):
            mm = m & cm
            if mm.sum() < 30: continue
            P(f"    {clab:12s} n{int(mm.sum()):4d} | vs shadow {100*(wm(p, mm, Tt)/wm(b0, mm, Tt)-1):+6.2f}% | vs blend {100*(wm(p, mm, Tt)/wm(bl, mm, Tt)-1):+6.2f}% (shadow was {100*(wm(b0, mm, Tt)/wm(bl, mm, Tt)-1):+6.2f}%)")
        pick = lambda yrs: min(["shadow (hand prior)"] + names, key=lambda k: wm(preds[k], m & np.isin(year, yrs), Tt))
        for flab, folds in (("LOYO", LOSO), ("forward", FORW)):
            pr_ = b0.copy(); picks = []; wins = 0
            for tr, te in folds:
                k = pick(tr); picks.append(k); mm = year == te; pr_[mm] = preds[k][mm]; wins += wm(preds[k], m & mm, Tt) < wm(b0, m & mm, Tt) - 1e-12
            tem = m & np.isin(year, [te for _, te in folds]); r, _ = RS(pr_, tem); r0_, _ = RS(b0, tem)
            P(f"  pick {flab:8s}: error {100*(wm(pr_, tem, Tt)/wm(b0, tem, Tt)-1):+.2f}% vs shadow ({wins}/{len(folds)}), {100*(wm(pr_, tem, Tt)/wm(bl, tem, Tt)-1):+.2f}% vs blend | rho {r - r0_:+.4f} | picks {picks}")
    P("\nLimitations: ridge = backtest_season_long LOYO predictions (each season held out, so the prior is honest); shadow replica (no book anchor / docks / QB window); the QB-only ridge uses the same feature list on ~1/6 of the rows.")
    LOG.close()


if __name__ == "__main__":
    main()
