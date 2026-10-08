#!/usr/bin/env python3
"""
WHY ARE TIGHT ENDS THE SHADOW'S WEAK POSITION? (Jack 2026-10-08: "can we figure out what the reasoning is with tes being so poor?")
Decomposes the shadow-vs-Clay-form gap on top-150 TE player-weeks 2019-25 (next game, pre-book):
  1  INPUTS the prior can see: share of TE rows with an ADP, a history prior, the ridge, the opportunity prior - vs WR / RB
  2  PRESEASON PRIOR alone (rows with 0 games played): shadow prior / hand prior / ridge / Clay per-game vs the next game
     and the rest of season - which prior is better for TEs, and by ADP / history availability
  3  EVIDENCE alone (4+ games): raw PPG / context-regressed PPG (ppg_v) / xFP vs the next game - which in-season read is best
  4  WHERE THE ERROR SITS: weighted squared-error share by cut, shadow minus Clay by cut (who carries the gap)
  5  LEVEL: actual / shadow and actual / Clay by cut, incl. scoring-over-usage (TD-heavy TEs) and the shadow's docks
  6  COMPONENT SWAPS: shadow with Clay's prior; shadow with the hand prior only; shadow with the ridge only
Log te_gap.log. Research only, nothing wired.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "te_gap.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X); clay_gm = LV["clay_gm"]
    base = top150 & ~final & ~LV["inh"]; TE = pos == "TE"; mTE = base & TE
    hist = F["hist"]; has_hist = ~np.isnan(hist); vet_opp = F["vet_opp"]; mkt = F["mkt_ok"]; hand = F["prior"]; prior = X["prior"]
    ridge_on = np.abs(prior - hand) > 1e-9; ridge = np.where(ridge_on, 2 * prior - hand, np.nan)
    wm = lambda p, m, T=act: float(np.average((p[m] - T[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    # rest-of-season target
    seqn = defaultdict(list)
    for i in range(n):
        if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ix in seqn.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]
        for a, i in enumerate(ix): nfut[i] = len(ix) - a; Tr[i] = a_[a:].mean()
    P(f"=== TE GAP: {int(mTE.sum()):,} top-150 TE player-weeks 2019-25 | shadow vs Clay form error {100*(wm(SHADOW, mTE)/wm(TODAY, mTE)-1):+.2f}% | level act/shadow {act[mTE].sum()/SHADOW[mTE].sum():.3f} act/Clay {act[mTE].sum()/TODAY[mTE].sum():.3f} ===")
    P("\n--- 1  WHAT THE PRIOR CAN SEE (share of top-150 rows) ---")
    for ps in POS4:
        m = base & (pos == ps)
        P(f"  {ps}: ADP {100*(~np.isnan(adp[m])).mean():.0f}% | history prior {100*has_hist[m].mean():.0f}% | ridge {100*ridge_on[m].mean():.0f}% | opportunity prior {100*vet_opp[m].mean():.0f}% | market ok {100*mkt[m].mean():.0f}% | rookies {100*X['rookie'][m].mean():.0f}% | median ADP {np.nanmedian(adp[m]):.0f}")
    P("\n--- 2  PRESEASON PRIOR ALONE (0 games played; x the game's layers so all share the context) vs next game / rest of season ---")
    m0 = mTE & (g == 0); L = X["layers"]
    cands = {"shadow prior (wired)": prior * L, "hand prior": hand * L, "ridge (where it exists)": np.where(ridge_on, ridge, prior) * L, "Clay per game": clay_gm * L, "history prior (where it exists)": np.where(has_hist, hist, prior) * L}
    for lab, T, mm in (("next game", act, m0), ("rest of season 4+", Tr, m0 & ~np.isnan(Tr) & (nfut >= 4))):
        P(f"  {lab} (n{int(mm.sum())}):")
        b0 = cands["Clay per game"]
        for k, p in cands.items():
            wins = sum(1 for y in YEARS if (mm & (year == y)).sum() >= 8 and wm(p, mm & (year == y), T) < wm(b0, mm & (year == y), T) - 1e-12)
            r = RG.rank_stats(p, mm, T, year, wk, pos)[0]
            P(f"    {k:32s} error vs Clay {100*(wm(p, mm, T)/wm(b0, mm, T)-1):+6.2f}% ({wins}/7) | rho {r:.3f} | level {T[mm].sum()/p[mm].sum():.3f}")
        for clab, cm in (("with ADP", ~np.isnan(adp)), ("no ADP", np.isnan(adp)), ("with history", has_hist), ("no history", ~has_hist), ("rookies", X["rookie"]), ("ADP <= 60", adpx <= 60), ("ADP 61-150", (adpx > 60) & (adpx <= 150))):
            mc = mm & cm
            if mc.sum() < 25: continue
            P(f"      {clab:14s} n{int(mc.sum()):4d} | shadow prior vs Clay {100*(wm(cands['shadow prior (wired)'], mc, T)/wm(b0, mc, T)-1):+6.2f}% | hand {100*(wm(cands['hand prior'], mc, T)/wm(b0, mc, T)-1):+6.2f}% | ridge {100*(wm(cands['ridge (where it exists)'], mc, T)/wm(b0, mc, T)-1):+6.2f}% | level shadow {T[mc].sum()/cands['shadow prior (wired)'][mc].sum():.3f} Clay {T[mc].sum()/b0[mc].sum():.3f}")
    P("\n--- 3  IN-SEASON EVIDENCE ALONE (4+ games, x layers): which read of the season so far predicts the next game ---")
    m4 = mTE & (g >= 4)
    ev = {"raw PPG": X["ppg"] * L, "context-regressed PPG (ppg_v, shadow)": X["ppg_v"] * L, "xFP per game": X["xf"] * L, ".3 xFP + .7 ppg_v": (0.3 * X["xf"] + 0.7 * X["ppg_v"]) * L, "shadow (prior + evidence)": SHADOW, "Clay form": TODAY}
    b0 = ev["Clay form"]
    for k, p in ev.items():
        wins = sum(1 for y in YEARS if wm(p, m4 & (year == y)) < wm(b0, m4 & (year == y)) - 1e-12); r = RG.rank_stats(p, m4, act, year, wk, pos)[0]
        P(f"  {k:40s} error vs Clay form {100*(wm(p, m4)/wm(b0, m4)-1):+6.2f}% ({wins}/7) | rho {r:.3f} | level {act[m4].sum()/p[m4].sum():.3f}")
    P("    same for WR (reference):")
    m4w = base & (pos == "WR") & (g >= 4); b0w = TODAY
    for k, p in ev.items():
        if k == "Clay form": continue
        P(f"      {k:38s} {100*(wm(p, m4w)/wm(b0w, m4w)-1):+6.2f}% | level {act[m4w].sum()/p[m4w].sum():.3f}")
    P("\n--- 4  WHERE THE TE ERROR SITS: share of the shadow's weighted squared error by cut, and shadow minus Clay by cut ---")
    tot_s = float(np.sum(wt[mTE] * (SHADOW[mTE] - act[mTE]) ** 2)); tot_c = float(np.sum(wt[mTE] * (TODAY[mTE] - act[mTE]) ** 2))
    cuts = (("ADP 1-30", adpx <= 30), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100)), ("101-150", adpx > 100), ("games 0", g == 0), ("games 1-3", (g >= 1) & (g <= 3)), ("games 4-8", (g >= 4) & (g <= 8)), ("games 9+", g >= 9), ("rookies", X["rookie"]), ("no history", ~has_hist), ("opportunity prior", vet_opp), ("history prior", has_hist & ~vet_opp))
    for lab, cm in cuts:
        m = mTE & cm
        if m.sum() < 20: continue
        es = float(np.sum(wt[m] * (SHADOW[m] - act[m]) ** 2)); ec = float(np.sum(wt[m] * (TODAY[m] - act[m]) ** 2))
        P(f"  {lab:18s} n{int(m.sum()):4d} | share of TE error: shadow {100*es/tot_s:5.1f}%  Clay {100*ec/tot_c:5.1f}% | shadow vs Clay here {100*(es/ec-1):+6.2f}% | of the total gap {100*(es-ec)/max(1e-9, tot_s-tot_c):+6.1f}% | level act/shadow {act[m].sum()/SHADOW[m].sum():.3f} act/Clay {act[m].sum()/TODAY[m].sum():.3f}")
    P("\n--- 5  LEVEL by scoring-over-usage and by the shadow's layers (TE, 2+ games) ---")
    m2 = mTE & (g >= 2) & X["has_x"] & (X["xf"] > 0); sou = np.where(m2, X["ppg"] / np.maximum(X["xf"], 0.1), np.nan)
    q = np.nanpercentile(sou[m2], [25, 50, 75]); e = [-9] + list(q) + [99]
    for a in range(4):
        m = m2 & (sou >= e[a]) & (sou < e[a + 1])
        P(f"  scoring/usage Q{a+1} ({e[a]:.2f}-{e[a+1]:.2f}) n{int(m.sum()):4d} | act/shadow {act[m].sum()/SHADOW[m].sum():.3f} act/Clay {act[m].sum()/TODAY[m].sum():.3f} | shadow vs Clay {100*(wm(SHADOW, m)/wm(TODAY, m)-1):+6.2f}%")
    lay = X["layers"]; shl = SHADOW / np.maximum(SN.shadow(X), 1e-9)   # the as-wired extra layers on top of the harness shadow
    for lab, cm in (("shadow extra layers < .95 (docked)", shl < 0.95), ("extra layers .95-1.05", (shl >= 0.95) & (shl <= 1.05)), ("extra layers > 1.05 (lifted)", shl > 1.05), ("game layers (Vegas/FPA) < .9", lay < 0.9), ("game layers > 1.1", lay > 1.1)):
        m = mTE & (g >= 1) & cm
        if m.sum() < 20: continue
        P(f"  {lab:36s} n{int(m.sum()):4d} | act/shadow {act[m].sum()/SHADOW[m].sum():.3f} act/Clay {act[m].sum()/TODAY[m].sum():.3f} | shadow vs Clay {100*(wm(SHADOW, m)/wm(TODAY, m)-1):+6.2f}%")
    P("\n--- 6  COMPONENT SWAPS: the shadow re-run with a different TE prior (evidence handling unchanged) ---")
    def swap(pr):
        X2 = dict(X); X2["prior"] = np.where(TE, pr, X["prior"]); return BR.shadow_current(X2)[0]
    for lab, pr in (("Clay per game as the TE prior", clay_gm), ("hand prior only", hand), ("ridge only (where it exists)", np.where(ridge_on, ridge, prior)), ("history prior only (where it exists)", np.where(has_hist, hist, prior)), ("shadow prior x 1.05", prior * 1.05)):
        p = swap(pr); wins = sum(1 for y in YEARS if wm(p, mTE & (year == y)) < wm(SHADOW, mTE & (year == y)) - 1e-12)
        r = RG.rank_stats(p, mTE, act, year, wk, pos)[0]; r0 = RG.rank_stats(SHADOW, mTE, act, year, wk, pos)[0]
        P(f"  {lab:36s} vs shadow {100*(wm(p, mTE)/wm(SHADOW, mTE)-1):+6.2f}% ({wins}/7) | vs Clay form {100*(wm(p, mTE)/wm(TODAY, mTE)-1):+6.2f}% | rho {r - r0:+.4f} | level {act[mTE].sum()/p[mTE].sum():.3f} | g 0-3 {100*(wm(p, mTE & (g <= 3))/wm(TODAY, mTE & (g <= 3))-1):+6.2f}% | g 4+ {100*(wm(p, mTE & (g >= 4))/wm(TODAY, mTE & (g >= 4))-1):+6.2f}%")
    P("\nLimitations: harness replicas (no book anchor / docks / prior lift); the 'prior alone' rows are week-1-type rows; ridge recovered from the wired 50/50 mix; nothing here is a layer test.")
    LOG.close()


if __name__ == "__main__":
    main()
