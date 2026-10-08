/* JM_CEILING_WEIGHTS — extracted from index.html for performance */
  var JM_CEILING_WEIGHTS = {
    // ═══ APR 2026 v4 CEILING — UPSIDE-SKEWED ═══
    // Re-balanced after v3 ELITE-CURVE recalibration over-concentrated DC (33-42%)
    // and zeroed legitimate ceiling signals (yprr, routeGrade, dominator). v4 restores
    // them. DC stays meaningful (27-30%) but no longer dominates. Boosts RAS, breakout,
    // and position-specific upside markers (qbRush for QB, rbRec/yaco for RB, contested+pff
    // for WR, yprr+contested for TE). Backtest gap improvements verified end-to-end.
    // QB v7 (Apr 23 2026): correlation-driven rebalance — largest change is qbAccuracy
    // ceiling cut from 0.10 → 0.06. At 10% weight it was the 4th-biggest ceiling
    // input but correlates with NFL outcomes at only r=0.185 (9th-strongest signal).
    // Weight shifted to pff (r=0.234, raised 0.05→0.08) and prod (raised 0.08→0.09).
    // age added (r=0.365, was 0 on ceiling) to reward young studs at the top end.
    // v10.2 (Oct 1 2026): QB rushing weight DOUBLED (others scaled down). From the bust / late-hit study:
    //   first-50 QB busts averaged 3.8 college rushing points a game against 6.9 for the successes (AUC .23),
    //   RAS 7.0 vs 9.05. Chosen in all eight leave-one-year-out folds; vs graded career outcome, top-100
    //   picks .664 -> .703, all QBs .731 -> .738. CEILING track.
    // (previous) QB:  { dc: 0.27, ras: 0.13, qbRush: 0.13, breakout: 0.13, prod: 0.09, qbAccuracy: 0.06, bigTime: 0.07, pff: 0.08, age: 0.02, turnoverRate: 0.02 },  // sum=1.00
    QB:  { dc: 0.23894, qbRush: 0.23009, ras: 0.11504, breakout: 0.11504, prod: 0.07965, pff: 0.0708, bigTime: 0.06195, qbAccuracy: 0.0531, age: 0.0177, turnoverRate: 0.0177 },  // sum=1.00
    // RB v6: dropped dominator (dead, ridge -2.0), redistributed to rbRec (+2) and pffRecv (+2, was 0)
    // RB v7 ceiling (Apr 24 2026): pff (rush grade) ADDED at 0.05 — was missing
    //   from ceiling entirely despite r=0.21/0.27 signal. pffRecv doubled 0.02→0.04.
    //   yaco, breakaway, elusive, conf, mktShare trimmed (correlations weaker than
    //   prior ceiling weights suggested). Sum preserved.
    // RB v8 ceiling (May 10 2026): in-page coord-descent. pff (rush grade) raised
    //   0.05 → 0.08 — was the single biggest accepted ceiling move. dc trimmed
    //   slightly (0.30 → 0.29), everything else absorbed small proportional cuts.
    // v10 (Sep 30 2026) - re-derived on corrected birth dates with leave-one-draft-year-out validation
    // (scripts/jm_robust_lab.py, jm_eval_cfgs.js). Draft capital plus an UNWEIGHTED average of the eight inputs
    // that add information beyond the pick, selected on training years only. Age, breakout age and RAS add
    // nothing for RBs once the pick is known. Out-of-year vs the v9 weights: Spearman .620 -> .634,
    // top-100 picks .520 -> .581, per-class .583 -> .638.
    // CEILING track: draft capital 35% (the profile gets more say).
    // (previous) RB:  { dc: 0.291, rbRec: 0.145, ras: 0.097, pff: 0.080, prod: 0.077, breakout: 0.077, yaco: 0.058, breakaway: 0.048, elusive: 0.039, pffRecv: 0.039, mktShare: 0.029, conf: 0.019, dominator: 0, tm: 0 },  // sum=1.00
    RB:  { dc: 0.35, careerPpg: 0.08125, pffRecv: 0.08125, tdRate: 0.08125, rbRec: 0.08125, prod: 0.08125, pff: 0.08125, eff: 0.08125, totalColFpts: 0.08125 },  // sum=1.00
    // WR v7 (Apr 2026): added adot (5%) + slotFit (3%). Other ceiling weights rescaled by 0.92.
    // v6: dropped dominator (dead in both eras), redistributed to breakout (+2), yprr (+1), pff (+1).
    // WR v8 ceiling: added avoidedTackles (3%). Trimmed yac (0.04→0.02 — avoidedTackles
    // captures the same translation-critical YAC signal more directly),
    // qbCtx (0.045→0.04), routeGrade (0.025→0.02). Sum preserved.
    // WR v9 ceiling (Apr 24 2026): adot killed (NEGATIVE correlation), yprr + routeGrade
    //   big boosts (top non-DC signals). yac zeroed (corr 0.10 — below threshold).
    //   contested, qbCtx, ras trimmed slightly. Sum preserved.
    // v10 (Sep 30 2026) - re-derived on corrected birth dates with leave-one-draft-year-out validation
    // Draft capital plus an UNWEIGHTED average of the eight inputs that add information beyond the pick
    // (teammate quality, production, aDOT, film grade, conference, breakout, contested catch, career PPG).
    // Out-of-year vs the v9 weights: Spearman .553 -> .576, top-100 picks .456 -> .502, top-5-per-class hit rate .50 -> .53.
    // CEILING track: draft capital 30% (the profile gets more say).
    // (previous) WR:  { dc: 0.26, breakout: 0.16, prod: 0.12, yprr: 0.12, pff: 0.09, routeGrade: 0.08, ras: 0.04, contested: 0.04, qbCtx: 0.03, slotFit: 0.03, avoidedTackles: 0.03, dominator: 0, yac: 0, adot: 0, tm: 0 },  // sum=1.00
    // v10.1 (Oct 1 2026): production and career PPG count DOUBLE (2 of 10 units each). Accuracy is a wash vs equal
    // weights (all .597 -> .590, top-100 picks .513 -> .530) but no first-round WR in the backtest graded 90+ with
    // production as thin as Carnell Tate's; known first-round hits +0.2, busts -0.2. CEILING track.
    // (equal-weight v10) WR:  { dc: 0.3, tm: 0.0875, prod: 0.0875, adot: 0.0875, pff: 0.0875, conf: 0.0875, breakout: 0.0875, contested: 0.0875, careerPpg: 0.0875 },  // sum=1.00
    WR:  { dc: 0.3, prod: 0.14, careerPpg: 0.14, tm: 0.07, adot: 0.07, pff: 0.07, conf: 0.07, breakout: 0.07, contested: 0.07 },  // sum=1.00
    // TE v6: added pff (+6, was 0 — recent +0.33 raw), trimmed ras (era effect), trimmed qbCtx and size
    // TE v8.1 ceiling: DC cut 0.28 → 0.23 (5pts freed, same reasoning as floor).
    // Redistribution: avoidedTackles +0.02, breakout +0.01, prod +0.01, pbGrade +0.01.
    // TE v9 ceiling (Apr 24 2026): yprr boosted 0.10→0.14 (corr 0.28/0.39),
    //   routeGrade ADDED at 0.07 (corr 0.27/0.37). Contested, conf, qbCtx, eff,
    //   avoidedTackles, teRec, dominator, pbGrade all trimmed. Sum preserved.
    // v10 (Sep 30 2026) - re-derived on corrected birth dates with leave-one-draft-year-out validation
    // v9 weights scaled to 84% plus athl (raw forty / vertical / broad composite) at 16%: the one TE input
    // selected in all eight leave-one-year-out folds (partial +.3 beyond the pick; RAS alone +.12).
    // Spearman .536 -> .574, per-class .562 -> .611; top-100 picks unchanged (.672 -> .674).
    // (previous) TE:  { dc: 0.23, breakout: 0.14, yprr: 0.14, prod: 0.09, routeGrade: 0.07, pff: 0.06, contested: 0.06, avoidedTackles: 0.05, ras: 0.05, teRec: 0.04, pbGrade: 0.03, dominator: 0.02, conf: 0.01, qbCtx: 0.01, eff: 0, size: 0 }  // sum=1.00
    TE:  { dc: 0.1932, breakout: 0.1176, yprr: 0.1176, prod: 0.0756, routeGrade: 0.0588, pff: 0.0504, contested: 0.0504, avoidedTackles: 0.042, ras: 0.042, teRec: 0.0336, pbGrade: 0.0252, dominator: 0.0168, conf: 0.0084, qbCtx: 0.0084, athl: 0.16 }  // sum=1.00
  };
