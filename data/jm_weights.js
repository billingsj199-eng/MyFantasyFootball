/* JM_WEIGHTS — extracted from index.html for performance */
  var JM_WEIGHTS = {
    // ═══ APR 2026 v4 "TRUE SEPARATION" RECALIBRATION ═══
    // Backtested against BACKTEST_OUTCOMES (2020-2024, 332 matched prospects).
    // Apr 2026 v3 over-concentrated DC (35% across positions) which collapsed the
    // top of the score distribution (max WR ~89, no Generational tier achieved)
    // and made the model unable to differentiate within high-DC players.
    // v4 redistributes DC down to 24-27% and restores weight on production,
    // breakout, RAS, PFF — components with proven discrimination signal.
    // Combined with applied bustAdj/sleeperAdj and the _jmStretch transformation,
    // v4 lifts stud-bust gap (validated end-to-end on modified index.html, 332 prospects):
    //   QB 29.3→39.9 (+10.6), RB 23.3→25.0 (+1.7), WR 25.0→28.9 (+3.9), TE 28.3→35.8 (+7.5).
    // 15 players now score 90+ (was 0 in v1) — Generational tier finally accessible.
    // Known limitation: high-DC busts (Lance, Wilson, Ruggs) still rate highly because
    // their college profile (early breakout + good RAS + decent production) is
    // genuinely good — only post-draft signals would catch them.
    // QB v7 (Apr 23 2026): correlation-driven rebalance. Backtest n=65:
    //   dc r=0.657 (king, kept at 0.27)     breakout r=0.591 (kept at 0.13)
    //   prod r=0.444 (kept)                  qbRush r=0.434 (kept)
    //   age r=0.365 (raised 0.06→0.07)      ras r=0.349 (kept)
    //   totalColFpts r=0.282 (added 0→0.03) pff r=0.234 (raised 0.06→0.07)
    //   qbAccuracy r=0.185 (cut 0.05→0.04 — was 4th-highest weight for 9th-strongest signal)
    //   improve r=-0.179 (kept 0 — negative correlation, should not be weighted)
    //   conf r=0.063 (kept 0.02)             colTrajectory r=0.015 (dropped — noise)
    //   size r=-0.010 (dropped — noise; height handled via flat penalty instead)
    // Predictive correlation improvement: 0.6297 → 0.6442 (+0.0145 Pearson on backtest).
    // QB v8 (Apr 24 2026): conf trimmed 0.02 → 0 (corr 0.03, dead). Redistributed
    //   to pff (0.07 → 0.08, corr 0.24) and breakout (0.13 → 0.14).
    // QB v9 (May 10 2026): in-page coordinate-descent over Floor weights vs combined
    //   monotonicity-of-(hr,ppg,bust)+top-tier-bust-suppression+late-pick-catch
    //   objective on 2017-2024 backtest (n=73 QB). Score 0.5213 → 0.4730 (-9.3%).
    //   Single accepted move: dc 0.27 → 0.30, others rescaled proportionally.
    //   Starter tier: hr 73%→82%, bust 9%→0%, PPG 15.7→16.7.
    QB:  { dc: 0.300, breakout: 0.134, prod: 0.125, pff: 0.077, ras: 0.077, qbRush: 0.067, age: 0.067, bigTime: 0.058, qbAccuracy: 0.038, turnoverRate: 0.029, totalColFpts: 0.029, conf: 0, colTrajectory: 0, size: 0 },  // sum=1.00
    // RB v6 (Apr 2026): regression-driven cleanup — dominator dead (raw 0.09, ridge -2.0), totalColFpts redundant, colTrajectory zero
    // Redistributed to rbRec (raw 0.29, ridge +6.8), breakout (raw 0.39, ridge +6.9), pffRecv (raw 0.26, ridge +5.3)
    // RB v8 (Apr 24 2026): further data-driven tuning from PFF metric correlations.
    //   pffRecv 0.015 → 0.03 (corr r=0.19/0.24, underweighted)
    //   breakaway 0.005 → 0.015 (corr 0.09/0.14)
    //   elusive 0.01 → 0.02 (corr 0.07/0.16)
    //   forcedMissed 0.005 → 0.015 (corr 0.05/0.13)
    //   yaco 0.04 → 0.03 (corr 0.06/0.13 — weaker than expected)
    //   improve, mktShare, totalColFpts, age trimmed to balance.
    //   v7 preserved: pff (rush) 0.05, conf 0, size 0.
    // RB v9 (May 10 2026): in-page coord-descent on the same objective as QB v9
    //   (n=143 RB backtest). Score 0.4505 → 0.3371 (-25.2%, biggest gain of any pos).
    //   Major rebalance: dc +0.03, ras +0.03, improve +0.03 (YoY PPG slope was
    //   under-weighted), prod -0.04. Killed elusive (0.02→0) and forcedMissed
    //   (0.015→0) — v8 had added small weight on PFF rush metrics but the
    //   optimizer says they're already captured by yaco + pff rush grade.
    //   Starter tier: hr 33%→40%, bust 48%→40%, PPG 9.0→9.8. Depth: hr 6%→9%.
    RB:  { dc: 0.291, breakout: 0.115, rbRec: 0.106, ras: 0.110, prod: 0.092, improve: 0.056, age: 0.053, dcAgeComposite: 0.048, pff: 0.048, yaco: 0.029, pffRecv: 0.029, breakaway: 0.014, totalColFpts: 0.005, mktShare: 0.005, elusive: 0, forcedMissed: 0, dominator: 0, conf: 0, size: 0, colTrajectory: 0, tm: 0 },  // sum=1.00
    // WR v7 (Apr 2026): added adot (6%) + slotFit (3%) weighted components from PFF career data.
    //   aDOT: sweet-spot curve — dead zone ≤8.5 (0-for-15 hits), peak 8.5-13.
    //   slotFit: U-curve — peak 60-80% slot (Waddle/Jeff/ARSB/Egbuka), bust zone ≥80%.
    //   All other WR weights rescaled by 0.91 to make room. Sum preserved at 1.00.
    // v6 notes: dominator dead in both eras (raw 0.10), totalColFpts redundant, colTrajectory zero.
    //   Redistributed to breakout (raw 0.39), yprr (recent +0.29), pff (consistent +0.26), dcAgeComposite (raw 0.47).
    // WR v8 (Apr 23 2026): added avoidedTackles (3%) from PFF career data.
    // Backtest r = +0.20 with NFL curveScore (moderate signal, compressed to 3%).
    // 3% trimmed from: contested 0.05→0.04, dcAgeComposite 0.04→0.03, conf 0.02→0.01.
    // WR v9 (Apr 24 2026): major data-driven rebalance. adot killed (career corr
    //   -0.06, best3 -0.05 — was actively NEGATIVE while model weighted it +0.06).
    //   yprr raised 0.08 → 0.11 (corr 0.19/0.31, 2nd-strongest signal after DC).
    //   routeGrade raised 0.045 → 0.08 (corr 0.18/0.32).
    //   breakout +0.01 (corr 0.26/0.26), pff +0.005 (corr 0.30/0.36).
    //   contested trimmed (weaker than expected), conf zeroed (dead).
    // WR v10 (May 10 2026): in-page coord-descent (n=219 WR). Score 0.6769 → 0.5926
    //   (-12.5%). Single accepted move: yprr 0.11 → 0.14 (already the 2nd-strongest
    //   non-DC signal per v9; optimizer says push it further). Top Prospect tier:
    //   hr 54%→58%, bust 23%→17%, PPG 10.9→11.1.
    WR:  { dc: 0.213, breakout: 0.145, yprr: 0.140, prod: 0.135, routeGrade: 0.077, pff: 0.072, ras: 0.058, age: 0.043, dcAgeComposite: 0.029, contested: 0.029, slotFit: 0.029, avoidedTackles: 0.029, dominator: 0, conf: 0, adot: 0, totalColFpts: 0, colTrajectory: 0, tm: 0 },  // sum=1.00
    // TE v8 (Apr 23 2026): added avoidedTackles (5%) + pbGrade (3%) — both new weighted
    // components from PFF career data. Backtest n=83 (avoid) / n=70 (pbGrade):
    //   avoidedPerRec  r = +0.26  (3rd-strongest TE signal)
    //   pbGrade        r = +0.21  (TE blocking QUALITY — stays on field in base personnel)
    // Note: pbRate / inlineRate have NEGATIVE correlation (pure blockers bust) — NOT
    // weighted. We use pbGrade (quality conditional on usage), not usage rate.
    // 8% total new weight trimmed from: eff 0.05→0.02, dominator 0.03→0.02,
    // qbCtx 0.02→0, size 0.02→0.
    // v6 notes: added pff, trimmed ras (era effect). KEPT dominator (era stability).
    // TE v8.1 floor: DC cut from 0.25 → 0.20 (5pts freed).
    //   Rationale: TE DC has lowest correlation with NFL outcome of any position
    //   (r=0.53 vs QB 0.64, RB 0.63, WR 0.55). Late-round TEs hit at 10.7% —
    //   meaningful. Over-weighting DC understates post-DC profile signal.
    //   Redistribution: breakout +0.01, prod +0.02, avoidedTackles +0.01, pbGrade +0.01.
    // TE v10 (Apr 24 2026): yprr raised 0.07 → 0.12 (corr 0.28/0.39, strongest
    //   non-DC TE signal). routeGrade ADDED at 0.06 (corr 0.27/0.37, previously
    //   unweighted despite being computed). Contested, avoidedTackles, teRec,
    //   pbGrade trimmed to fund. Conf zeroed (corr -0.05 dead). Sum preserved.
    // TE v11 (May 10 2026): in-page coord-descent (n=101 TE). Score 0.9576 → 0.9543
    //   (only -0.3% — TE weight tuning is information-limited; the bottom 4 tiers
    //   all have ~5-7% hit rates which is statistical noise on small n's). Single
    //   accepted move: dc 0.20 → 0.22. Real TE improvement came from tier-threshold
    //   tuning (see POS_TIERS in index.html), which dropped score to 0.7871 (-18%).
    TE:  { dc: 0.220, breakout: 0.137, prod: 0.117, yprr: 0.117, pff: 0.068, ras: 0.068, routeGrade: 0.059, teRec: 0.049, contested: 0.039, age: 0.039, avoidedTackles: 0.039, pbGrade: 0.029, dominator: 0.010, eff: 0.010, conf: 0, totalColFpts: 0, size: 0, qbCtx: 0, colTrajectory: 0 }  // sum=1.00
  };
