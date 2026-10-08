#!/usr/bin/env python3
"""
VOLUME CONTEXT ON ELITE RECEIVERS (Jack 2026-10-08: "McBride has great career stats, great usage, 17+ PPG this year, an amazing
matchup - projected only 16.1"). His shadow is 17.7 before the volume-context layer (wired 10-07: 1 - .03 z(script-excess att/g)
for every WR/TE, x 1 - .04 z(att/g) on underdogs, + box 1 + .04 z(box) ADP <= 60) takes 11% off: Arizona throws the most above
game script in the league. That layer was graded on the old Clay-blend live base; the base is now the Clay-free shadow. Here, on
the honest shadow replica, top-150 WR/TE weeks with 2+ prior team games: no layer vs the wired stack vs the stack with the top
ADP exempt (<= 12 / 30 / 60) vs the dock capped for them. LOYO + forward against the WIRED stack (bar 5/7 + 3/4, < -0.3% on the
rows), ADP-band read with cubed top-100 weights. Log volume_elite.log.
"""
import os, sys, warnings
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import backtest_base_remeasure as BR
import backtest_volume_context as VC
import rank_grade as RG
SN = BR.SN; YEARS = BR.YEARS; POS4 = BR.POS4; FWD = (2022, 2023, 2024, 2025)
warnings.filterwarnings("ignore")
LOG = open(os.path.join(HERE, "volume_elite.log"), "w", encoding="utf-8")
def P(s=""):
    print(s); LOG.write(s + chr(10)); LOG.flush()


def main():
    X = SN.setup(); n = X["n"]; F = X["F"]; A = F["A"]
    act, year, wk, pos, g, adp, team = X["act"], X["year"], X["wk"], X["pos"], X["g"], X["adp"], X["team"]
    pid = A["pid"]
    finw = np.where(year <= 2020, 17, 18); final = wk == finw; adpx = np.where(np.isnan(adp), 999.0, adp)
    lv = F["adp_curve"].copy()
    for ps in POS4:
        m = pos == ps; lv[m & np.isnan(lv)] = np.nanmin(lv[m]); lv[m] = lv[m] / lv[m & (adpx <= 150)].mean()
    wt2 = np.maximum(0.05, lv) ** 2; wt3 = np.maximum(0.05, lv) ** 3
    TODAY, LV = BR.live_today(X); SH, _ = BR.shadow_current(X)
    TW = VC.load_team_weeks(YEARS)
    C = pd.read_parquet(os.path.join(HERE, "ctx_features.parquet")); ck = {(int(a), b, int(c)): i for i, (a, b, c) in enumerate(zip(C.year, C.pid, C.wk)) if isinstance(b, str)}
    idx = np.array([ck.get((int(year[i]), pid[i], int(wk[i])), -1) if pid[i] else -1 for i in range(n)]); has = idx >= 0
    spread = np.where(has, C["spread"].values[np.maximum(idx, 0)], np.nan).astype(float)
    RECV = np.isin(pos, ("WR", "TE")); okN = (adpx <= 150) & ~final & ~LV["inh"] & (SH >= 3)
    att = np.full(n, np.nan); exc = np.full(n, np.nan)
    for i in np.where(okN & RECV)[0]:
        if not team[i]: continue
        Y = int(year[i]); rows = [TW[(Y, team[i], w)] for w in range(1, int(wk[i])) if (Y, team[i], w) in TW]
        if len(rows) < 2: continue
        a = np.sum(rows, axis=0); gms = len(rows); nrate = a[3] / max(a[2], 1)
        att[i] = a[1] / gms; exc[i] = a[1] / gms - nrate * a[0] / gms
    zA = np.full(n, np.nan); zE = np.full(n, np.nan)
    for y in YEARS:
        for w in range(1, 19):
            m = okN & RECV & (year == y) & (wk == w) & ~np.isnan(att)
            if m.sum() >= 20:
                zA[m] = np.clip((att[m] - att[m].mean()) / max(att[m].std(), 1e-9), -2.5, 2.5); zE[m] = np.clip((exc[m] - exc[m].mean()) / max(exc[m].std(), 1e-9), -2.5, 2.5)
    rows = okN & RECV & ~np.isnan(zE)
    und = ~np.isnan(spread) & (spread > 0)
    mult = np.ones(n); mult[rows] = np.clip(1 - 0.03 * zE[rows], 0.8, 1.2); mm = rows & und; mult[mm] *= np.clip(1 - 0.04 * zA[mm], 0.8, 1.2)
    OFF = SH.copy(); WIRED = SH * mult
    P(f"=== VOLUME CONTEXT x ELITE on the Clay-free shadow: {int(rows.sum()):,} WR/TE top-150 weeks with 2+ prior team games (box part not in the harness) ===")
    P("  docked rows (mult < .95) act / wired by ADP band: " + " | ".join(f"{lab} {act[rows & (mult < .95) & bm].sum()/max(1e-9, WIRED[rows & (mult < .95) & bm].sum()):.3f} (undocked {act[rows & (mult < .95) & bm].sum()/max(1e-9, OFF[rows & (mult < .95) & bm].sum()):.3f}, n{int((rows & (mult < .95) & bm).sum())})" for lab, bm in (("1-12", adpx <= 12), ("13-30", (adpx > 12) & (adpx <= 30)), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-150", adpx > 60))))
    preds = {"wired": WIRED, "off": OFF}
    for cut in (12, 30, 60):
        p = WIRED.copy(); e = rows & (adpx <= cut); p[e] = OFF[e]; preds[f"exempt ADP<={cut}"] = p
        p = WIRED.copy(); e = rows & (adpx <= cut); p[e] = OFF[e] * np.maximum(mult[e], 0.96); preds[f"cap .96 ADP<={cut}"] = p
        p = WIRED.copy(); e = rows & (adpx <= cut) & (mult < 1); p[e] = OFF[e]; preds[f"no dock (lifts kept) ADP<={cut}"] = p
    for sc_ in (0.5, 0.75, 1.25):
        mu = np.ones(n); mu[rows] = np.clip(1 - 0.03 * sc_ * zE[rows], 0.8, 1.2); mm2 = rows & und; mu[mm2] *= np.clip(1 - 0.04 * sc_ * zA[mm2], 0.8, 1.2)
        preds[f"strength x{sc_}"] = SH * mu
    w2 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt2[m])) if m.any() else np.nan
    w3 = lambda p, m: float(np.average((p[m] - act[m]) ** 2, weights=wt3[m])) if m.any() else np.nan
    names = list(preds); b0 = WIRED; m = rows
    pick = lambda yrs: min(names, key=lambda kk: w2(preds[kk], m & np.isin(year, yrs)))
    LOSO = [([y for y in YEARS if y != t], t) for t in YEARS]; FORW = [([y for y in YEARS if y < t], t) for t in FWD]
    def run(folds):
        wins = 0; picks = []; pr = b0.copy()
        for tr_, te in folds:
            kk = pick(tr_); picks.append(kk); mx = year == te; pr[mx] = preds[kk][mx]; wins += w2(preds[kk], m & mx) < w2(b0, m & mx) - 1e-12
        tem = np.isin(year, [te for _, te in folds]); return 100 * (w2(pr, m & tem) / w2(b0, m & tem) - 1), 100 * (w2(pr, okN & tem) / w2(b0, okN & tem) - 1), wins, picks
    P("\n  fixed, vs WIRED (squared top-150 | cubed top-100 | by band cubed):")
    t100 = rows & (adpx <= 100)
    for kk in names[1:]:
        p = preds[kk]
        bands = " ".join(f"{lab}:{100*(w3(p, rows & bm)/w3(b0, rows & bm)-1):+.2f}" for lab, bm in (("1-12", adpx <= 12), ("13-30", (adpx > 12) & (adpx <= 30)), ("31-60", (adpx > 30) & (adpx <= 60)), ("61-100", (adpx > 60) & (adpx <= 100))))
        P(f"    {kk:30s} {100*(w2(p, m)/w2(b0, m)-1):+.2f}% ({sum(1 for y in YEARS if w2(p, m & (year == y)) < w2(b0, m & (year == y)) - 1e-12)}/7) | top-100 cubed {100*(w3(p, t100)/w3(b0, t100)-1):+.2f}% | {bands}")
    P("    off vs wired is the layer itself on the new base (positive = the layer still helps)")
    P("  " + RG.rank_line(preds, m, act, year, wk, pos))
    lo = run(LOSO); fw = run(FORW); best = pick(YEARS)
    okk = best != "wired" and lo[0] < -0.3 and lo[2] >= 5 and fw[0] < 0 and fw[2] >= 3 and lo[1] <= 0.02
    P(f"  LOYO {lo[0]:+.2f}% {lo[2]}/7 | board {lo[1]:+.3f}% | picks {lo[3]}"); P(f"  FWD  {fw[0]:+.2f}% {fw[2]}/4 | board {fw[1]:+.3f}% | picks {fw[3]}")
    P(f"  -> {'PASS: ' + best if okk else 'FAIL (wired stays)'}")
    P("\nLimitations: honest replica, next game, no book anchor; box-count part (ADP <= 60) not in the harness; team volume from play-by-play season to date.")
    LOG.close()


if __name__ == "__main__":
    main()
