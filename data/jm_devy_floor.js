/* JM_DEVY_FLOOR — extracted from index.html for performance */
  var JM_DEVY_FLOOR = {
    // Nov 18 2026 (devy v2): the MAIN floor weights (jm_weights.js) with draft capital taken out and the rest
    //   re-spread. Used only for devy prospects with no pick / projected pick (26 players, 2028 class).
    //   Backtest: every 2017-24 drafted player graded as a no-pick devy prospect (window._JM_EXP.asDevy,
    //   node scripts/jm_optimize.js --devy), Spearman vs graded career: QB .508 -> .561, RB .453 -> .486,
    //   WR .459 -> .503, TE .467 -> .478; won 31 of 32 position folds (choose on 7 classes, score the 8th).
    //   Re-tuning the old tables gained almost nothing (QB .510, RB .470, WR .451, TE .471).
    //   When jm_weights.js changes, regenerate these (main table minus dc, renormalised).
    // (previous, hand-set June 2026, Oct 17 QB trim):
    //   QB: { prod: 0.20835, breakout: 0.1875, qbRush: 0.10417, age: 0.08333, conf: 0.08333, improve: 0.08333, qbIntRate: 0.08333, size: 0.05208, eff: 0.05208, qbAccuracy: 0.05208, pff: 0.01042 }
    //   RB: { prod: 0.22, breakout: 0.20, rbRec: 0.08, age: 0.08, conf: 0.08, yaco: 0.06, mktShare: 0.05, improve: 0.05, forcedMissed: 0.05, elusive: 0.05, breakaway: 0.05, size: 0.03 }
    //   WR: { prod: 0.24, breakout: 0.24, yprr: 0.10, age: 0.08, routeGrade: 0.07, conf: 0.06, contested: 0.05, dominator: 0.04, qbCtx: 0.04, dropRate: 0.04, yac: 0.04 }
    //   TE: { breakout: 0.20, prod: 0.17, teRec: 0.10, age: 0.08, improve: 0.07, conf: 0.06, size: 0.05, eff: 0.05, qbCtx: 0.05, yprr: 0.04, dominator: 0.04, contested: 0.03, dropRate: 0.02, routeGrade: 0.02, yac: 0.02 }
    QB:  { breakout: 0.19678, qbRush: 0.19678, prod: 0.18355, pff: 0.11307, ras: 0.11307, age: 0.09837, qbAccuracy: 0.05581, totalColFpts: 0.04258 },  // sum=1.00
    RB:  { careerPpg: 0.125, pffRecv: 0.125, tdRate: 0.125, rbRec: 0.125, prod: 0.125, pff: 0.125, eff: 0.125, totalColFpts: 0.125 },  // sum=1.00
    WR:  { prod: 0.2, careerPpg: 0.2, tm: 0.1, adot: 0.1, pff: 0.1, conf: 0.1, breakout: 0.1, contested: 0.1 },  // sum=1.00
    TE:  { athl: 0.19608, breakout: 0.14102, prod: 0.12044, yprr: 0.12044, pff: 0.06999, ras: 0.06999, routeGrade: 0.06073, teRec: 0.05044, contested: 0.04014, age: 0.04014, avoidedTackles: 0.04014, pbGrade: 0.02985, dominator: 0.01029, eff: 0.01029 }  // sum=1.00
  };
