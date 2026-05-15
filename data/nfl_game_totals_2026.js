// 2026 NFL game totals (over/under) — DraftKings.
// Initial pull pasted by Jack on 2026-05-15 — covers full season.
//
// Refresh strategy: lines move as the season progresses (injuries,
// standings). For BBM playoff use the values close to game time.
//
// Format:
//   'W{wk}_{AWAY}_{HOME}': { total: 47.5, asOf: '2026-05-15', source: 'DK' }
//
// Bringback color thresholds (per project_bringback_playoffs research):
//   total >= 47   = green (high-total bringback: +10% playoff advance lift)
//   total 43-46.99 = yellow (neutral)
//   total <= 42   = red (low-total bringback: -28% lift)

window.NFL_GAME_TOTALS_2026 = {
  // ===== Week 1 =====
  'W1_NE_SEA':           { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W1_SF_LAR':           { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W1_CHI_CAR':          { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W1_TB_CIN':           { total: 50.5, asOf: '2026-05-15', source: 'DK' },
  'W1_NO_DET':           { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W1_BUF_HOU':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W1_BAL_IND':          { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W1_CLE_JAX':          { total: 40.5, asOf: '2026-05-15', source: 'DK' },
  'W1_ATL_PIT':          { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W1_NYJ_TEN':          { total: 39.5, asOf: '2026-05-15', source: 'DK' },
  'W1_ARI_LAC':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W1_MIA_LV':           { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W1_GB_MIN':           { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W1_WAS_PHI':          { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W1_DAL_NYG':          { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W1_DEN_KC':           { total: 42.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 2 =====
  'W2_DET_BUF':          { total: 52.5, asOf: '2026-05-15', source: 'DK' },
  'W2_CAR_ATL':          { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W2_NO_BAL':           { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W2_MIN_CHI':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W2_CIN_HOU':          { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W2_PIT_NE':           { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W2_GB_NYJ':           { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W2_CLE_TB':           { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W2_PHI_TEN':          { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W2_JAX_DEN':          { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W2_LV_LAC':           { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W2_SEA_ARI':          { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W2_WAS_DAL':          { total: 51.5, asOf: '2026-05-15', source: 'DK' },
  'W2_MIA_SF':           { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W2_IND_KC':           { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W2_NYG_LAR':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 3 =====
  'W3_LAC_BUF':          { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W3_CAR_CLE':          { total: 39.5, asOf: '2026-05-15', source: 'DK' },
  'W3_NYJ_DET':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W3_HOU_IND':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W3_NE_JAX':           { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W3_KC_MIA':           { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W3_TEN_NYG':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W3_CIN_PIT':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W3_SEA_WAS':          { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W3_ARI_SF':           { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W3_MIN_TB':           { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W3_BAL_DAL':          { total: 52.5, asOf: '2026-05-15', source: 'DK' },
  'W3_LV_NO':            { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W3_LAR_DEN':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W3_PHI_CHI':          { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W3_ATL_GB':           { total: 46.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 4 =====
  'W4_IND_WAS':          { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W4_TEN_BAL':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W4_NE_BUF':           { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W4_NYJ_CHI':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W4_JAX_CIN':          { total: 51.5, asOf: '2026-05-15', source: 'DK' },
  'W4_DAL_HOU':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W4_ARI_NYG':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W4_LAR_PHI':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W4_GB_TB':            { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W4_MIA_MIN':          { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W4_KC_LV':            { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W4_LAC_SEA':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W4_DEN_SF':           { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W4_DET_CAR':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W4_ATL_NO':           { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W4_PIT_CLE':          { total: 40.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 5 =====
  'W5_CIN_MIA':          { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W5_LV_NE':            { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W5_MIN_NO':           { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W5_CLE_NYJ':          { total: 39.5, asOf: '2026-05-15', source: 'DK' },
  'W5_IND_PIT':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W5_HOU_TEN':          { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W5_NYG_WAS':          { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W5_DEN_LAC':          { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W5_DET_ARI':          { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W5_CHI_GB':           { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W5_SF_SEA':           { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W5_BAL_ATL':          { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W5_BUF_LAR':          { total: 53.5, asOf: '2026-05-15', source: 'DK' },
  'W5_TB_DAL':           { total: 52.5, asOf: '2026-05-15', source: 'DK' },
  'W5_PHI_JAX':          { total: 44.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 6 =====
  'W6_HOU_JAX':          { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W6_CHI_ATL':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W6_BAL_CLE':          { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W6_TEN_IND':          { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W6_NYJ_NE':           { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W6_NO_NYG':           { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W6_CAR_PHI':          { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W6_PIT_TB':           { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W6_ARI_LAR':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W6_LAC_KC':           { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W6_BUF_LV':           { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W6_DAL_GB':           { total: 51.5, asOf: '2026-05-15', source: 'DK' },
  'W6_WAS_SF':           { total: 50.5, asOf: '2026-05-15', source: 'DK' },
  'W6_SEA_DEN':          { total: 43.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 7 =====
  'W7_PIT_NO':           { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W7_SF_ATL':           { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W7_CIN_BAL':          { total: 52.5, asOf: '2026-05-15', source: 'DK' },
  'W7_TB_CAR':           { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W7_NYG_HOU':          { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W7_IND_MIN':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W7_MIA_NYJ':          { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W7_CLE_TEN':          { total: 40.5, asOf: '2026-05-15', source: 'DK' },
  'W7_DEN_ARI':          { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W7_GB_DET':           { total: 50.5, asOf: '2026-05-15', source: 'DK' },
  'W7_LAR_LV':           { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W7_KC_SEA':           { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W7_DAL_PHI':          { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W7_NE_CHI':           { total: 47.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 8 =====
  'W8_BAL_BUF':          { total: 51.5, asOf: '2026-05-15', source: 'DK' },
  'W8_TEN_CIN':          { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W8_ARI_DAL':          { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W8_MIN_DET':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W8_IND_JAX':          { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W8_LV_NYJ':           { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W8_CLE_PIT':          { total: 39.5, asOf: '2026-05-15', source: 'DK' },
  'W8_ATL_TB':           { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W8_LAC_LAR':          { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W8_KC_DEN':           { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W8_NE_MIA':           { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W8_PHI_WAS':          { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W8_CHI_SEA':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W8_CAR_GB':           { total: 45.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 9 =====
  'W9_JAX_BAL':          { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W9_CIN_ATL':          { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W9_DAL_IND':          { total: 52.5, asOf: '2026-05-15', source: 'DK' },
  'W9_NYJ_KC':           { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W9_DET_MIA':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W9_CLE_NO':           { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W9_NYG_PHI':          { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W9_LAR_WAS':          { total: 50.5, asOf: '2026-05-15', source: 'DK' },
  'W9_HOU_LAC':          { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W9_LV_SF':            { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W9_GB_NE':            { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W9_ARI_SEA':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W9_TB_CHI':           { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W9_BUF_MIN':          { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W9_DEN_CAR':          { total: 42.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 10 =====
  'W10_NE_DET':          { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W10_KC_ATL':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W10_HOU_CLE':         { total: 38.5, asOf: '2026-05-15', source: 'DK' },
  'W10_MIN_GB':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W10_MIA_IND':         { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W10_CAR_NO':          { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W10_BUF_NYJ':         { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W10_JAX_TEN':         { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W10_LAR_ARI':         { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W10_SEA_LV':          { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W10_SF_DAL':          { total: 52.5, asOf: '2026-05-15', source: 'DK' },
  'W10_PIT_CIN':         { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W10_LAC_BAL':         { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W10_WAS_NYG':         { total: 47.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 11 =====
  'W11_MIA_BUF':         { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W11_BAL_CAR':         { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W11_NO_CHI':          { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W11_TEN_DAL':         { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W11_TB_DET':          { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W11_ARI_KC':          { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W11_JAX_NYG':         { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W11_NYJ_LAC':         { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W11_LV_DEN':          { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W11_PIT_PHI':         { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W11_MIN_SF':          { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W11_CIN_WAS':         { total: 52.5, asOf: '2026-05-15', source: 'DK' },
  'W11_IND_HOU':         { total: 45.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 12 =====
  'W12_GB_LAR':          { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W12_CHI_DET':         { total: 51.5, asOf: '2026-05-15', source: 'DK' },
  'W12_PHI_DAL':         { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W12_KC_BUF':          { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W12_DEN_PIT':         { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W12_NO_CIN':          { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W12_LV_CLE':          { total: 39.5, asOf: '2026-05-15', source: 'DK' },
  'W12_BAL_HOU':         { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W12_NYG_IND':         { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W12_NYJ_MIA':         { total: 40.5, asOf: '2026-05-15', source: 'DK' },
  'W12_ATL_MIN':         { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W12_TEN_JAX':         { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W12_WAS_ARI':         { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W12_SEA_SF':          { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W12_NE_LAC':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W12_CAR_TB':          { total: 44.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 13 =====
  'W13_KC_LAR':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W13_DET_ATL':         { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W13_JAX_CHI':         { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W13_CIN_CLE':         { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W13_GB_NO':           { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W13_SF_NYG':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W13_LAC_TB':          { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W13_WAS_TEN':         { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W13_PHI_ARI':         { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W13_MIA_DEN':         { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W13_CAR_MIN':         { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W13_BUF_NE':          { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W13_HOU_PIT':         { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W13_DAL_SEA':         { total: 48.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 14 =====
  'W14_MIN_NE':          { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W14_TB_BAL':          { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W14_NO_CAR':          { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W14_ATL_CLE':         { total: 40.5, asOf: '2026-05-15', source: 'DK' },
  'W14_TEN_DET':         { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W14_CHI_MIA':         { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W14_DEN_NYJ':         { total: 39.5, asOf: '2026-05-15', source: 'DK' },
  'W14_IND_PHI':         { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W14_HOU_WAS':         { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W14_LAC_LV':          { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W14_KC_CIN':          { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W14_NYG_SEA':         { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W14_LAR_SF':          { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W14_BUF_GB':          { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W14_PIT_JAX':         { total: 44.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 15 =====
  'W15_SF_LAC':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W15_SEA_PHI':         { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W15_CHI_BUF':         { total: 51.5, asOf: '2026-05-15', source: 'DK' },
  'W15_CIN_CAR':         { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W15_MIA_GB':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W15_JAX_HOU':         { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W15_CLE_NYG':         { total: 40.5, asOf: '2026-05-15', source: 'DK' },
  'W15_BAL_PIT':         { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W15_NO_TB':           { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W15_IND_TEN':         { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W15_ATL_WAS':         { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W15_NYJ_ARI':         { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W15_DAL_LAR':         { total: 52.5, asOf: '2026-05-15', source: 'DK' },
  'W15_DEN_LV':          { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W15_DET_MIN':         { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W15_NE_KC':           { total: 45.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 16 =====
  'W16_HOU_PHI':         { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W16_GB_CHI':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W16_BUF_DEN':         { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W16_LAR_SEA':         { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W16_CLE_BAL':         { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W16_LAC_MIA':         { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W16_ARI_NO':          { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W16_NE_NYJ':          { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W16_TEN_LV':          { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W16_SF_KC':           { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W16_JAX_DAL':         { total: 51.5, asOf: '2026-05-15', source: 'DK' },
  'W16_NYG_DET':         { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W16_TB_ATL':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W16_CIN_IND':         { total: 52.5, asOf: '2026-05-15', source: 'DK' },
  'W16_WAS_MIN':         { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W16_CAR_PIT':         { total: 41.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 17 =====
  'W17_NO_ATL':          { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W17_SEA_CAR':         { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W17_IND_CLE':         { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W17_NYG_DAL':         { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W17_BUF_MIA':         { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W17_MIN_NYJ':         { total: 40.5, asOf: '2026-05-15', source: 'DK' },
  'W17_PIT_TEN':         { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W17_LV_ARI':          { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W17_DET_CHI':         { total: 49.5, asOf: '2026-05-15', source: 'DK' },
  'W17_PHI_SF':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W17_WAS_JAX':         { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W17_KC_LAC':          { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W17_DEN_NE':          { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W17_LAR_TB':          { total: 48.5, asOf: '2026-05-15', source: 'DK' },
  'W17_BAL_CIN':         { total: 51.5, asOf: '2026-05-15', source: 'DK' },
  'W17_HOU_GB':          { total: 42.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 18 =====
  'W18_SF_ARI':          { total: 44.5, asOf: '2026-05-15', source: 'DK' },
  'W18_PIT_BAL':         { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W18_NYJ_BUF':         { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W18_ATL_CAR':         { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W18_CLE_CIN':         { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W18_LAC_DEN':         { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W18_DET_GB':          { total: 47.5, asOf: '2026-05-15', source: 'DK' },
  'W18_TEN_HOU':         { total: 39.5, asOf: '2026-05-15', source: 'DK' },
  'W18_JAX_IND':         { total: 46.5, asOf: '2026-05-15', source: 'DK' },
  'W18_LV_KC':           { total: 40.5, asOf: '2026-05-15', source: 'DK' },
  'W18_SEA_LAR':         { total: 45.5, asOf: '2026-05-15', source: 'DK' },
  'W18_CHI_MIN':         { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W18_MIA_NE':          { total: 42.5, asOf: '2026-05-15', source: 'DK' },
  'W18_TB_NO':           { total: 43.5, asOf: '2026-05-15', source: 'DK' },
  'W18_PHI_NYG':         { total: 41.5, asOf: '2026-05-15', source: 'DK' },
  'W18_DAL_WAS':         { total: 49.5, asOf: '2026-05-15', source: 'DK' },

};

(function() {
  window.getNflGameTotal = function(wk, away, home) {
    if (!wk || !away || !home) return null;
    const key = 'W' + wk + '_' + String(away).toUpperCase() + '_' + String(home).toUpperCase();
    const rec = window.NFL_GAME_TOTALS_2026[key];
    return (rec && typeof rec.total === 'number') ? rec.total : null;
  };
  window.classifyGameTotal = function(total) {
    if (typeof total !== 'number') return { tier: null, color: null, label: '—' };
    if (total >= 47)   return { tier: 'high', color: '#22c55e', label: total.toFixed(1) };
    if (total <= 42)   return { tier: 'low',  color: '#ef4444', label: total.toFixed(1) };
    return { tier: 'mid', color: '#facc15', label: total.toFixed(1) };
  };
  window.getNflTotalsCount = function() {
    return Object.values(window.NFL_GAME_TOTALS_2026).filter(r => r && typeof r.total === 'number').length;
  };
})();
