#!/usr/bin/env python3
"""
REST-OF-SEASON BLEND WEIGHTS (Jack 2026-10-08: "keep improving until it can be Clay-free for weekly and season long").
The per-position blend (QB .5 / RB .8 / WR .7 / TE 0) was fit on the NEXT GAME. The season-long number (VOR board, trade
calc, playoff odds) is the same weekly projection summed over the remaining weeks, so this grades the same ladder on the
rest-of-season horizon: target = the player's actual average over his remaining games this season (4+ left, final week
dropped), prediction = the pre-book number rescaled from this week's game context to the mean future context (fill-in
harness convention). Error (top-150 importance-weighted) + rank objective, by position; LOYO + forward weight picks.
Reads: how far the shadow alone is from the blend per position on the season horizon = the Clay-free gap. Log ros_blend.log.
"""
import os, sys, warnings
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "ros_blend.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()
WIRED = {"QB": 0.5, "RB": 0.8, "WR": 0.7, "TE": 0.0}
WG = (0.0, 0.3, 0.5, 0.7, 0.8, 0.9, 1.0)


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]
    act, year, wk, pos, g, adp, name = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["name"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; top150 = adp <= 150; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & top150].mean()
    wt = np.maximum(0.05, lv) ** 2
    TODAY, LV = BR.live_today(X); SHADOW, _ = BR.shadow_current(X)
    # rest-of-season target and context (fill-in harness convention)
    seqn = defaultdict(list)
    for i in range(n):
        if not final[i]: seqn[(name[i], pos[i], int(year[i]))].append(i)
    Tr = np.full(n, np.nan); ctx = np.full(n, np.nan); nfut = np.zeros(n, int)
    for ix in seqn.values():
        ix.sort(key=lambda i: wk[i]); a_ = act[ix]; l_ = np.clip(X["layers"][ix], 0.5, 1.8)
        for a, i in enumerate(ix): nfut[i] = len(ix) - a; Tr[i] = a_[a:].mean(); ctx[i] = l_[a:].mean()
    ctx0 = np.nan_to_num(ctx, nan=1.0); ros = lambda p: p / np.maximum(X["layers"], 0.3) * ctx0
    T4 = ros(TODAY); S4 = ros(SHADOW)
    ok = top150 & ~final & ~LV["inh"] & (g >= 1) & (g <= 10) & ~np.isnan(Tr) & (nfut >= 4) & (TODAY >= 3)
    wm = lambda p, m: float(np.average((p[m] - Tr[m]) ** 2, weights=wt[m])) if m.any() else np.nan
    RS = lambda p, m: RG.rank_stats(p, m, Tr, year, wk, pos)
    bl = lambda w: w * S4 + (1 - w) * T4
    bw = np.array([WIRED[p_] for p_ in pos]); WIREDP = bw * S4 + (1 - bw) * T4
    P(f"=== REST-OF-SEASON BLEND: {int(ok.sum()):,} top-150 player-weeks 2019-25 with 4+ games left (games 1-10 played), target = actual average over the remaining games ===")
    P(f"    level actual / projected: TODAY {Tr[ok].sum()/T4[ok].sum():.3f}  shadow {Tr[ok].sum()/S4[ok].sum():.3f}  wired blend {Tr[ok].sum()/WIREDP[ok].sum():.3f}")
    def row(lab, p, ref, m):
        r, pr = RS(p, m); r0, p0 = RS(ref, m); wins = RG.rank_seasons(p, ref, m, Tr, year, wk, pos, YEARS)
        ew = sum(1 for y in YEARS if wm(p, m & (year == y)) < wm(ref, m & (year == y)) - 1e-12)
        P(f"  {lab:34s} error {100*(wm(p, m)/wm(ref, m)-1):+6.2f}% ({ew}/7) | rho {r:.4f} ({r - r0:+.4f}, {wins}/7) | pairs {pr:.2f}% ({pr - p0:+.2f}) | level {Tr[m].sum()/p[m].sum():.3f}")
    P("\n--- 1  LADDER vs TODAY (live form) on the season horizon, whole board ---")
    for w in WG: row(f"blend w {w:.1f}" + (" (shadow alone)" if w == 1.0 else " (TODAY)" if w == 0.0 else ""), bl(w), T4, ok)
    row("wired per-position .5/.8/.7/0", WIREDP, T4, ok)
    P("\n--- 2  BY POSITION: shadow alone and the wired weight vs TODAY; best fixed weight on the season horizon ---")
    for ps in POS4:
        m = ok & (pos == ps); best = min(WG, key=lambda w: wm(bl(w), m)); bestr = max(WG, key=lambda w: RS(bl(w), m)[0])
        P(f"  {ps} (n{int(m.sum())}): best weight on error {best:.1f}, on rank {bestr:.1f}")
        for lab, w in (("shadow alone", 1.0), (f"wired w {WIRED[ps]:.1f}", WIRED[ps]), (f"best on error w {best:.1f}", best)): row("   " + lab, bl(w), T4, m)
    P("\n--- 3  BY ADP BAND and GAMES PLAYED, shadow alone vs TODAY (where is Clay still needed for the season number) ---")
    for lab, cm in (("ADP 1-30", adpx <= 30), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100)), ("101-150", adpx > 100), ("games 1-3", g <= 3), ("games 4-6", (g >= 4) & (g <= 6)), ("games 7-10", g >= 7), ("rookies", X["rookie"])):
        row(lab, S4, T4, ok & cm)
    P("\n--- 4  WEIGHT PICKED LEAVE-ONE-SEASON-OUT and FORWARD per position (error), season horizon ---")
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    for flab, folds in (("LOYO", LOSO), ("forward", FORW)):
        out = T4.copy(); picks = {ps: [] for ps in POS4}
        for tr, te in folds:
            for ps in POS4:
                m = ok & (pos == ps) & np.isin(year, tr); w = min(WG, key=lambda w_: wm(bl(w_), m)); picks[ps].append(w); sel = (pos == ps) & (year == te); out[sel] = bl(w)[sel]
        tem = ok & np.isin(year, [te for _, te in folds]); r, _ = RS(out, tem); r0, _ = RS(T4, tem); rw, _ = RS(WIREDP, tem)
        P(f"  {flab:8s}: error {100*(wm(out, tem)/wm(T4, tem)-1):+.2f}% vs TODAY, {100*(wm(out, tem)/wm(WIREDP, tem)-1):+.2f}% vs the wired weights | rho {r - r0:+.4f} vs TODAY, {r - rw:+.4f} vs wired | picks " + " | ".join(f"{ps} {picks[ps]}" for ps in POS4))
    P("\nLimitations: both forms rescaled from this week's context to the mean future context (same convention for both); book anchor / docks / prior lift not replayed; rest-of-season structure layers (ROS tilt, shadow v2.26-28) not in either replica.")
    LOG.close()


if __name__ == "__main__":
    main()
