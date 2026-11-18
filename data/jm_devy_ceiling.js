/* JM_DEVY_CEILING — extracted from index.html for performance */
  var JM_DEVY_CEILING = {
    // Nov 18 2026 (devy v2): the MAIN ceiling weights (jm_ceiling_weights.js) with draft capital taken out and the
    //   rest re-spread - see jm_devy_floor.js for the backtest. Regenerate when the main tables change.
    // (previous, hand-set June 2026, Oct 17 QB trim):
    //   QB: { breakout: 0.23405, prod: 0.19149, qbRush: 0.10638, improve: 0.10638, qbIntRate: 0.08511, conf: 0.06383, age: 0.05319, qbAccuracy: 0.05319, eff: 0.05319, size: 0.03191, pff: 0.02128 }
    //   RB: { breakout: 0.24, prod: 0.20, breakaway: 0.09, rbRec: 0.06, conf: 0.06, yaco: 0.06, improve: 0.06, elusive: 0.06, mktShare: 0.05, age: 0.05, forcedMissed: 0.05, size: 0.02 }
    //   WR: { breakout: 0.27, prod: 0.22, yprr: 0.10, routeGrade: 0.10, age: 0.05, contested: 0.05, yac: 0.05, conf: 0.04, dominator: 0.04, qbCtx: 0.04, dropRate: 0.04 }
    //   TE: { breakout: 0.22, prod: 0.15, teRec: 0.10, improve: 0.07, age: 0.05, qbCtx: 0.05, eff: 0.05, routeGrade: 0.05, yprr: 0.05, conf: 0.04, contested: 0.04, dominator: 0.04, size: 0.03, yac: 0.03, dropRate: 0.03 }
    QB:  { qbRush: 0.33767, ras: 0.16882, breakout: 0.16882, prod: 0.11689, pff: 0.10391, qbAccuracy: 0.07792, age: 0.02597 },  // sum=1.00
    RB:  { careerPpg: 0.125, pffRecv: 0.125, tdRate: 0.125, rbRec: 0.125, prod: 0.125, pff: 0.125, eff: 0.125, totalColFpts: 0.125 },  // sum=1.00
    WR:  { prod: 0.2, careerPpg: 0.2, tm: 0.1, adot: 0.1, pff: 0.1, conf: 0.1, breakout: 0.1, contested: 0.1 },  // sum=1.00
    TE:  { athl: 0.19831, breakout: 0.14576, yprr: 0.14576, prod: 0.0937, routeGrade: 0.07288, pff: 0.06247, contested: 0.06247, avoidedTackles: 0.05206, ras: 0.05206, teRec: 0.04165, pbGrade: 0.03123, dominator: 0.02082, conf: 0.01041, qbCtx: 0.01041 }  // sum=1.00
  };
