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
    QB:  { dc: 0.27, ras: 0.13, qbRush: 0.13, breakout: 0.13, prod: 0.09, qbAccuracy: 0.06, bigTime: 0.07, pff: 0.08, age: 0.02, turnoverRate: 0.02 },  // sum=1.00
    // RB v6: dropped dominator (dead, ridge -2.0), redistributed to rbRec (+2) and pffRecv (+2, was 0)
    // RB v7 ceiling (Apr 24 2026): pff (rush grade) ADDED at 0.05 — was missing
    //   from ceiling entirely despite r=0.21/0.27 signal. pffRecv doubled 0.02→0.04.
    //   yaco, breakaway, elusive, conf, mktShare trimmed (correlations weaker than
    //   prior ceiling weights suggested). Sum preserved.
    RB:  { dc: 0.30, rbRec: 0.15, ras: 0.10, prod: 0.08, breakout: 0.08, yaco: 0.06, pff: 0.05, breakaway: 0.05, elusive: 0.04, pffRecv: 0.04, mktShare: 0.03, conf: 0.02, dominator: 0, tm: 0 },  // sum=1.00
    // WR v7 (Apr 2026): added adot (5%) + slotFit (3%). Other ceiling weights rescaled by 0.92.
    // v6: dropped dominator (dead in both eras), redistributed to breakout (+2), yprr (+1), pff (+1).
    // WR v8 ceiling: added avoidedTackles (3%). Trimmed yac (0.04→0.02 — avoidedTackles
    // captures the same translation-critical YAC signal more directly),
    // qbCtx (0.045→0.04), routeGrade (0.025→0.02). Sum preserved.
    // WR v9 ceiling (Apr 24 2026): adot killed (NEGATIVE correlation), yprr + routeGrade
    //   big boosts (top non-DC signals). yac zeroed (corr 0.10 — below threshold).
    //   contested, qbCtx, ras trimmed slightly. Sum preserved.
    WR:  { dc: 0.26, breakout: 0.16, prod: 0.12, yprr: 0.12, pff: 0.09, routeGrade: 0.08, ras: 0.04, contested: 0.04, qbCtx: 0.03, slotFit: 0.03, avoidedTackles: 0.03, dominator: 0, yac: 0, adot: 0, tm: 0 },  // sum=1.00
    // TE v6: added pff (+6, was 0 — recent +0.33 raw), trimmed ras (era effect), trimmed qbCtx and size
    // TE v8.1 ceiling: DC cut 0.28 → 0.23 (5pts freed, same reasoning as floor).
    // Redistribution: avoidedTackles +0.02, breakout +0.01, prod +0.01, pbGrade +0.01.
    // TE v9 ceiling (Apr 24 2026): yprr boosted 0.10→0.14 (corr 0.28/0.39),
    //   routeGrade ADDED at 0.07 (corr 0.27/0.37). Contested, conf, qbCtx, eff,
    //   avoidedTackles, teRec, dominator, pbGrade all trimmed. Sum preserved.
    TE:  { dc: 0.23, breakout: 0.14, yprr: 0.14, prod: 0.09, routeGrade: 0.07, pff: 0.06, contested: 0.06, avoidedTackles: 0.05, ras: 0.05, teRec: 0.04, pbGrade: 0.03, dominator: 0.02, conf: 0.01, qbCtx: 0.01, eff: 0, size: 0 }  // sum=1.00
  };
