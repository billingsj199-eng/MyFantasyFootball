/* JM_DEVY_CEILING — extracted from index.html for performance */
  var JM_DEVY_CEILING = {
    // Oct 17 2026: QB bigTime + turnoverRate set to 0, others re-spread proportionally (no backtest support; TWP points
    //   the wrong way on the 2017-24 QBs - see jm_weights.js v10.3).
    // (previous) QB: { breakout: 0.22, prod: 0.18, qbRush: 0.10, improve: 0.10, qbIntRate: 0.08, conf: 0.06, age: 0.05, qbAccuracy: 0.05, eff: 0.05, size: 0.03, bigTime: 0.03, turnoverRate: 0.03, pff: 0.02 }  // sum=1.00
    QB:  { breakout: 0.23405, prod: 0.19149, qbRush: 0.10638, improve: 0.10638, qbIntRate: 0.08511, conf: 0.06383, age: 0.05319, qbAccuracy: 0.05319, eff: 0.05319, size: 0.03191, pff: 0.02128 },  // sum=1.00
    RB:  { breakout: 0.24, prod: 0.20, breakaway: 0.09, rbRec: 0.06, conf: 0.06, yaco: 0.06, improve: 0.06, elusive: 0.06, mktShare: 0.05, age: 0.05, forcedMissed: 0.05, size: 0.02 },  // sum=1.00
    WR:  { breakout: 0.27, prod: 0.22, yprr: 0.10, routeGrade: 0.10, age: 0.05, contested: 0.05, yac: 0.05, conf: 0.04, dominator: 0.04, qbCtx: 0.04, dropRate: 0.04 },  // sum=1.00
    TE:  { breakout: 0.22, prod: 0.15, teRec: 0.10, improve: 0.07, age: 0.05, qbCtx: 0.05, eff: 0.05, routeGrade: 0.05, yprr: 0.05, conf: 0.04, contested: 0.04, dominator: 0.04, size: 0.03, yac: 0.03, dropRate: 0.03 }  // sum=1.00
  };
