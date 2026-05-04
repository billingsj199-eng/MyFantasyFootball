// Auto-generated from scripts/_bbm_stack_x_round.json
// Stack composition rates with QF/SF/Finals per cell.
// Source: 5 BBMs (II-VI), n=2,629,295 teams.
// Baselines: QF=0.16668  SF=0.01320  Fin=0.00082.

// compKey -> {qf, sf, fin, n} for primary stacking patterns.
// Cohort definitions are same-team-as-QB1 patterns in draft order:
//   wr1_only      = QB1's same-team WR1 stacked, no other mate
//   wr1_and_wr2   = QB1's WR1 + WR2 same team (over-concentration)
//   wr1_and_rb1   = QB1's WR1 + RB1 same team (diversified)
//   wr1_and_te1   = QB1's WR1 + TE1 same team
//   wr2_no_wr1    = QB1's WR2 stacked but not WR1 (skipped primary)
//   te1_only      = TE1 stacked, no other mate
//   rb1_only      = RB1 stacked, no other mate
//   no_stack      = naked QB (no same-team mate)
const BBM_STACK_COMP_MULTI = {
    "wr1_only": {
      "qf": 0.19096,
      "sf": 0.01485,
      "fin": 0.00092,
      "n": 270423
    },
    "wr1_and_wr2": {
      "qf": 0.13510,
      "sf": 0.00875,
      "fin": 0.00056,
      "n": 37579
    },
    "wr1_and_rb1": {
      "qf": 0.17227,
      "sf": 0.00943,
      "fin": 0.00091,
      "n": 25356
    },
    "wr1_and_te1": {
      "qf": 0.17365,
      "sf": 0.01730,
      "fin": 0.00091,
      "n": 46247
    },
    "no_stack": {
      "qf": 0.16390,
      "sf": 0.01247,
      "fin": 0.00078,
      "n": 929842
    },
    "te1_only": {
      "qf": 0.16951,
      "sf": 0.01545,
      "fin": 0.00071,
      "n": 397312
    },
    "rb1_only": {
      "qf": 0.15958,
      "sf": 0.01238,
      "fin": 0.00069,
      "n": 158801
    },
    "wr2_no_wr1": {
      "qf": 0.14956,
      "sf": 0.01097,
      "fin": 0.00075,
      "n": 363231
    }
  };

// Stack-size fallback (count of QB1 same-team mates) -> {qf, sf, fin, n}.
// Used when compKey is unavailable (e.g. team has no QB drafted yet).
const BBM_MAX_STACK_MULTI = {
    0: {
      "qf": 0.16482,
      "sf": 0.01167,
      "fin": 0.00068,
      "n": 539176
    },
    1: {
      "qf": 0.16644,
      "sf": 0.01300,
      "fin": 0.00084,
      "n": 935085
    },
    2: {
      "qf": 0.16943,
      "sf": 0.01412,
      "fin": 0.00087,
      "n": 763572
    },
    3: {
      "qf": 0.16688,
      "sf": 0.01426,
      "fin": 0.00085,
      "n": 308825
    },
    4: {
      "qf": 0.15529,
      "sf": 0.01291,
      "fin": 0.00083,
      "n": 82637
    }
  };
