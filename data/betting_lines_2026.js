// ============================================================================
// ALL BETTING / SPORTSBOOK LINES — single source of truth.
// Manually pasted by Jack. Everything line-related lives here.
//
//   window.BETTING_2026 = {
//     gameTotals:  { 'W1_AWAY_HOME': { total, spread, asOf, source } },  // WEEKLY
//     seasonProps: { 'Player Name': { DK, FD, MGM, asOf } },             // SEASON-LONG
//     weeklyProps: { }   // reserved for future weekly player props
//   }
//
// The two datasets keep their own format docs in the section comments below.
// Game-total helper fns (getNflGameTotal, getNflTeamImpliedTotal, …) are kept
// at the bottom and read from BETTING_2026.gameTotals.
// ============================================================================


// ===== WEEKLY GAME TOTALS + SPREADS (DraftKings) ============================
// 2026 NFL game totals + spreads (over/under, home spread) — DraftKings.
// Pasted by Jack on 2026-05-15 — covers full season.
//
// Format:
//   'W{wk}_{AWAY}_{HOME}': { total: 47.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' }
//   spread = HOME team's spread. Negative = home favored.
//
// Bringback color thresholds (per project_bringback_playoffs research):
//   total >= 47   = green (+10% playoff advance lift)
//   total 43-46.99 = yellow (neutral)
//   total <= 42   = red (-28% lift)

const _GAME_TOTALS_2026 = {
  // ===== Week 1 =====
  'W1_NE_SEA':           { total: 44.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W1_SF_LAR':           { total: 48.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W1_CHI_CAR':          { total: 44.5, spread: +2.5, asOf: '2026-05-15', source: 'DK' },
  'W1_TB_CIN':           { total: 50.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W1_NO_DET':           { total: 48.5, spread: -7, asOf: '2026-05-15', source: 'DK' },
  'W1_BUF_HOU':          { total: 45.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W1_BAL_IND':          { total: 49.5, spread: +3.5, asOf: '2026-05-15', source: 'DK' },
  'W1_CLE_JAX':          { total: 40.5, spread: -7, asOf: '2026-05-15', source: 'DK' },
  'W1_ATL_PIT':          { total: 42.5, spread: -3, asOf: '2026-05-15', source: 'DK' },
  'W1_NYJ_TEN':          { total: 39.5, spread: -3, asOf: '2026-05-15', source: 'DK' },
  'W1_ARI_LAC':          { total: 45.5, spread: -11.5, asOf: '2026-05-15', source: 'DK' },
  'W1_MIA_LV':           { total: 41.5, spread: -3, asOf: '2026-05-15', source: 'DK' },
  'W1_GB_MIN':           { total: 44.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W1_WAS_PHI':          { total: 46.5, spread: -5.5, asOf: '2026-05-15', source: 'DK' },
  'W1_DAL_NYG':          { total: 48.5, spread: +2.5, asOf: '2026-05-15', source: 'DK' },
  'W1_DEN_KC':           { total: 42.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 2 =====
  'W2_DET_BUF':          { total: 52.5, spread: -3, asOf: '2026-05-15', source: 'DK' },
  'W2_CAR_ATL':          { total: 43.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W2_NO_BAL':           { total: 46.5, spread: -7.5, asOf: '2026-05-15', source: 'DK' },
  'W2_MIN_CHI':          { total: 45.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W2_CIN_HOU':          { total: 46.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W2_PIT_NE':           { total: 43.5, spread: -4.5, asOf: '2026-05-15', source: 'DK' },
  'W2_GB_NYJ':           { total: 42.5, spread: +6.5, asOf: '2026-05-15', source: 'DK' },
  'W2_CLE_TB':           { total: 42.5, spread: -5.5, asOf: '2026-05-15', source: 'DK' },
  'W2_PHI_TEN':          { total: 42.5, spread: +4.5, asOf: '2026-05-15', source: 'DK' },
  'W2_JAX_DEN':          { total: 43.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W2_LV_LAC':           { total: 42.5, spread: -8.5, asOf: '2026-05-15', source: 'DK' },
  'W2_SEA_ARI':          { total: 44.5, spread: +10, asOf: '2026-05-15', source: 'DK' },
  'W2_WAS_DAL':          { total: 51.5, spread: -4.5, asOf: '2026-05-15', source: 'DK' },
  'W2_MIA_SF':           { total: 46.5, spread: -10.5, asOf: '2026-05-15', source: 'DK' },
  'W2_IND_KC':           { total: 47.5, spread: -5.5, asOf: '2026-05-15', source: 'DK' },
  'W2_NYG_LAR':          { total: 47.5, spread: -8.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 3 =====
  'W3_LAC_BUF':          { total: 48.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W3_CAR_CLE':          { total: 39.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W3_NYJ_DET':          { total: 45.5, spread: -9.5, asOf: '2026-05-15', source: 'DK' },
  'W3_HOU_IND':          { total: 45.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W3_NE_JAX':           { total: 45.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W3_KC_MIA':           { total: 44.5, spread: +7, asOf: '2026-05-15', source: 'DK' },
  'W3_TEN_NYG':          { total: 45.5, spread: -3, asOf: '2026-05-15', source: 'DK' },
  'W3_CIN_PIT':          { total: 47.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W3_SEA_WAS':          { total: 46.5, spread: +3.5, asOf: '2026-05-15', source: 'DK' },
  'W3_ARI_SF':           { total: 46.5, spread: -11.5, asOf: '2026-05-15', source: 'DK' },
  'W3_MIN_TB':           { total: 44.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W3_BAL_DAL':          { total: 52.5, spread: +2.5, asOf: '2026-05-15', source: 'DK' },
  'W3_LV_NO':            { total: 42.5, spread: -3, asOf: '2026-05-15', source: 'DK' },
  'W3_LAR_DEN':          { total: 45.5, spread: +2.5, asOf: '2026-05-15', source: 'DK' },
  'W3_PHI_CHI':          { total: 46.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W3_ATL_GB':           { total: 46.5, spread: -7.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 4 =====
  'W4_IND_WAS':          { total: 48.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W4_TEN_BAL':          { total: 47.5, spread: -8.5, asOf: '2026-05-15', source: 'DK' },
  'W4_NE_BUF':           { total: 49.5, spread: -3, asOf: '2026-05-15', source: 'DK' },
  'W4_NYJ_CHI':          { total: 45.5, spread: -8.5, asOf: '2026-05-15', source: 'DK' },
  'W4_JAX_CIN':          { total: 51.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W4_DAL_HOU':          { total: 47.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W4_ARI_NYG':          { total: 45.5, spread: -7, asOf: '2026-05-15', source: 'DK' },
  'W4_LAR_PHI':          { total: 47.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W4_GB_TB':            { total: 47.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W4_MIA_MIN':          { total: 43.5, spread: -7.5, asOf: '2026-05-15', source: 'DK' },
  'W4_KC_LV':            { total: 43.5, spread: +5.5, asOf: '2026-05-15', source: 'DK' },
  'W4_LAC_SEA':          { total: 45.5, spread: -3, asOf: '2026-05-15', source: 'DK' },
  'W4_DEN_SF':           { total: 46.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W4_DET_CAR':          { total: 47.5, spread: +3, asOf: '2026-05-15', source: 'DK' },
  'W4_ATL_NO':           { total: 45.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W4_PIT_CLE':          { total: 40.5, spread: +2.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 5 =====
  'W5_CIN_MIA':          { total: 49.5, spread: +5.5, asOf: '2026-05-15', source: 'DK' },
  'W5_LV_NE':            { total: 44.5, spread: -8.5, asOf: '2026-05-15', source: 'DK' },
  'W5_MIN_NO':           { total: 44.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W5_CLE_NYJ':          { total: 39.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W5_IND_PIT':          { total: 47.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W5_HOU_TEN':          { total: 43.5, spread: +3.5, asOf: '2026-05-15', source: 'DK' },
  'W5_NYG_WAS':          { total: 48.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W5_DEN_LAC':          { total: 44.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W5_DET_ARI':          { total: 49.5, spread: +8.5, asOf: '2026-05-15', source: 'DK' },
  'W5_CHI_GB':           { total: 49.5, spread: -3, asOf: '2026-05-15', source: 'DK' },
  'W5_SF_SEA':           { total: 48.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W5_BAL_ATL':          { total: 48.5, spread: +4.5, asOf: '2026-05-15', source: 'DK' },
  'W5_BUF_LAR':          { total: 53.5, spread: -3, asOf: '2026-05-15', source: 'DK' },
  'W5_TB_DAL':           { total: 52.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W5_PHI_JAX':          { total: 44.5, spread: +2.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 6 =====
  'W6_HOU_JAX':          { total: 41.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W6_CHI_ATL':          { total: 47.5, spread: +3, asOf: '2026-05-15', source: 'DK' },
  'W6_BAL_CLE':          { total: 44.5, spread: +6.5, asOf: '2026-05-15', source: 'DK' },
  'W6_TEN_IND':          { total: 48.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W6_NYJ_NE':           { total: 42.5, spread: -9.5, asOf: '2026-05-15', source: 'DK' },
  'W6_NO_NYG':           { total: 45.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W6_CAR_PHI':          { total: 43.5, spread: -6.5, asOf: '2026-05-15', source: 'DK' },
  'W6_PIT_TB':           { total: 45.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W6_ARI_LAR':          { total: 47.5, spread: -13.5, asOf: '2026-05-15', source: 'DK' },
  'W6_LAC_KC':           { total: 46.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W6_BUF_LV':           { total: 47.5, spread: +6.5, asOf: '2026-05-15', source: 'DK' },
  'W6_DAL_GB':           { total: 51.5, spread: -3, asOf: '2026-05-15', source: 'DK' },
  'W6_WAS_SF':           { total: 50.5, spread: -5.5, asOf: '2026-05-15', source: 'DK' },
  'W6_SEA_DEN':          { total: 43.5, spread: +2.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 7 =====
  'W7_PIT_NO':           { total: 42.5, spread: +2.5, asOf: '2026-05-15', source: 'DK' },
  'W7_SF_ATL':           { total: 47.5, spread: +4.5, asOf: '2026-05-15', source: 'DK' },
  'W7_CIN_BAL':          { total: 52.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W7_TB_CAR':           { total: 45.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W7_NYG_HOU':          { total: 43.5, spread: -5.5, asOf: '2026-05-15', source: 'DK' },
  'W7_IND_MIN':          { total: 47.5, spread: -3, asOf: '2026-05-15', source: 'DK' },
  'W7_MIA_NYJ':          { total: 41.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W7_CLE_TEN':          { total: 40.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W7_DEN_ARI':          { total: 43.5, spread: +7.5, asOf: '2026-05-15', source: 'DK' },
  'W7_GB_DET':           { total: 50.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W7_LAR_LV':           { total: 46.5, spread: +7.5, asOf: '2026-05-15', source: 'DK' },
  'W7_KC_SEA':           { total: 45.5, spread: -3, asOf: '2026-05-15', source: 'DK' },
  'W7_DAL_PHI':          { total: 48.5, spread: -3, asOf: '2026-05-15', source: 'DK' },
  'W7_NE_CHI':           { total: 47.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 8 =====
  'W8_BAL_BUF':          { total: 51.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W8_TEN_CIN':          { total: 49.5, spread: -6.5, asOf: '2026-05-15', source: 'DK' },
  'W8_ARI_DAL':          { total: 49.5, spread: -10.5, asOf: '2026-05-15', source: 'DK' },
  'W8_MIN_DET':          { total: 47.5, spread: -4.5, asOf: '2026-05-15', source: 'DK' },
  'W8_IND_JAX':          { total: 49.5, spread: -4.5, asOf: '2026-05-15', source: 'DK' },
  'W8_LV_NYJ':           { total: 41.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W8_CLE_PIT':          { total: 39.5, spread: -5.5, asOf: '2026-05-15', source: 'DK' },
  'W8_ATL_TB':           { total: 46.5, spread: -4.5, asOf: '2026-05-15', source: 'DK' },
  'W8_LAC_LAR':          { total: 48.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W8_KC_DEN':           { total: 43.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W8_NE_MIA':           { total: 45.5, spread: +7, asOf: '2026-05-15', source: 'DK' },
  'W8_PHI_WAS':          { total: 46.5, spread: +2.5, asOf: '2026-05-15', source: 'DK' },
  'W8_CHI_SEA':          { total: 47.5, spread: -4.5, asOf: '2026-05-15', source: 'DK' },
  'W8_CAR_GB':           { total: 45.5, spread: -7, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 9 =====
  'W9_JAX_BAL':          { total: 49.5, spread: -4.5, asOf: '2026-05-15', source: 'DK' },
  'W9_CIN_ATL':          { total: 48.5, spread: +4.5, asOf: '2026-05-15', source: 'DK' },
  'W9_DAL_IND':          { total: 52.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W9_NYJ_KC':           { total: 41.5, spread: -9.5, asOf: '2026-05-15', source: 'DK' },
  'W9_DET_MIA':          { total: 47.5, spread: +6.5, asOf: '2026-05-15', source: 'DK' },
  'W9_CLE_NO':           { total: 41.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W9_NYG_PHI':          { total: 44.5, spread: -5.5, asOf: '2026-05-15', source: 'DK' },
  'W9_LAR_WAS':          { total: 50.5, spread: +4.5, asOf: '2026-05-15', source: 'DK' },
  'W9_HOU_LAC':          { total: 43.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W9_LV_SF':            { total: 46.5, spread: -8.5, asOf: '2026-05-15', source: 'DK' },
  'W9_GB_NE':            { total: 46.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W9_ARI_SEA':          { total: 45.5, spread: -13.5, asOf: '2026-05-15', source: 'DK' },
  'W9_TB_CHI':           { total: 48.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W9_BUF_MIN':          { total: 48.5, spread: +3, asOf: '2026-05-15', source: 'DK' },
  'W9_DEN_CAR':          { total: 42.5, spread: +3, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 10 =====
  'W10_NE_DET':          { total: 48.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W10_KC_ATL':          { total: 45.5, spread: +4.5, asOf: '2026-05-15', source: 'DK' },
  'W10_HOU_CLE':         { total: 38.5, spread: +4.5, asOf: '2026-05-15', source: 'DK' },
  'W10_MIN_GB':          { total: 45.5, spread: -4.5, asOf: '2026-05-15', source: 'DK' },
  'W10_MIA_IND':         { total: 47.5, spread: -6.5, asOf: '2026-05-15', source: 'DK' },
  'W10_CAR_NO':          { total: 43.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W10_BUF_NYJ':         { total: 46.5, spread: +7, asOf: '2026-05-15', source: 'DK' },
  'W10_JAX_TEN':         { total: 45.5, spread: +2.5, asOf: '2026-05-15', source: 'DK' },
  'W10_LAR_ARI':         { total: 47.5, spread: +10.5, asOf: '2026-05-15', source: 'DK' },
  'W10_SEA_LV':          { total: 43.5, spread: +7, asOf: '2026-05-15', source: 'DK' },
  'W10_SF_DAL':          { total: 52.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W10_PIT_CIN':         { total: 47.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W10_LAC_BAL':         { total: 48.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W10_WAS_NYG':         { total: 47.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 11 =====
  'W11_MIA_BUF':         { total: 47.5, spread: -11.5, asOf: '2026-05-15', source: 'DK' },
  'W11_BAL_CAR':         { total: 46.5, spread: +4.5, asOf: '2026-05-15', source: 'DK' },
  'W11_NO_CHI':          { total: 46.5, spread: -6.5, asOf: '2026-05-15', source: 'DK' },
  'W11_TEN_DAL':         { total: 48.5, spread: -6.5, asOf: '2026-05-15', source: 'DK' },
  'W11_TB_DET':          { total: 49.5, spread: -4.5, asOf: '2026-05-15', source: 'DK' },
  'W11_ARI_KC':          { total: 44.5, spread: -11.5, asOf: '2026-05-15', source: 'DK' },
  'W11_JAX_NYG':         { total: 46.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W11_NYJ_LAC':         { total: 41.5, spread: -9.5, asOf: '2026-05-15', source: 'DK' },
  'W11_LV_DEN':          { total: 41.5, spread: -8.5, asOf: '2026-05-15', source: 'DK' },
  'W11_PIT_PHI':         { total: 42.5, spread: -5.5, asOf: '2026-05-15', source: 'DK' },
  'W11_MIN_SF':          { total: 46.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W11_CIN_WAS':         { total: 52.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W11_IND_HOU':         { total: 45.5, spread: -5.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 12 =====
  'W12_GB_LAR':          { total: 49.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W12_CHI_DET':         { total: 51.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W12_PHI_DAL':         { total: 49.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W12_KC_BUF':          { total: 49.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W12_DEN_PIT':         { total: 41.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W12_NO_CIN':          { total: 48.5, spread: -6.5, asOf: '2026-05-15', source: 'DK' },
  'W12_LV_CLE':          { total: 39.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W12_BAL_HOU':         { total: 45.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W12_NYG_IND':         { total: 47.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W12_NYJ_MIA':         { total: 40.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W12_ATL_MIN':         { total: 43.5, spread: -4.5, asOf: '2026-05-15', source: 'DK' },
  'W12_TEN_JAX':         { total: 45.5, spread: -5.5, asOf: '2026-05-15', source: 'DK' },
  'W12_WAS_ARI':         { total: 47.5, spread: +4.5, asOf: '2026-05-15', source: 'DK' },
  'W12_SEA_SF':          { total: 46.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W12_NE_LAC':          { total: 45.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W12_CAR_TB':          { total: 44.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 13 =====
  'W13_KC_LAR':          { total: 47.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W13_DET_ATL':         { total: 48.5, spread: +3.5, asOf: '2026-05-15', source: 'DK' },
  'W13_JAX_CHI':         { total: 47.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W13_CIN_CLE':         { total: 45.5, spread: +4.5, asOf: '2026-05-15', source: 'DK' },
  'W13_GB_NO':           { total: 45.5, spread: +4.5, asOf: '2026-05-15', source: 'DK' },
  'W13_SF_NYG':          { total: 47.5, spread: +3, asOf: '2026-05-15', source: 'DK' },
  'W13_LAC_TB':          { total: 46.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W13_WAS_TEN':         { total: 46.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W13_PHI_ARI':         { total: 43.5, spread: +8.5, asOf: '2026-05-15', source: 'DK' },
  'W13_MIA_DEN':         { total: 42.5, spread: -9.5, asOf: '2026-05-15', source: 'DK' },
  'W13_CAR_MIN':         { total: 42.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W13_BUF_NE':          { total: 48.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W13_HOU_PIT':         { total: 41.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W13_DAL_SEA':         { total: 48.5, spread: -4.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 14 =====
  'W14_MIN_NE':          { total: 43.5, spread: -4.5, asOf: '2026-05-15', source: 'DK' },
  'W14_TB_BAL':          { total: 48.5, spread: -6, asOf: '2026-05-15', source: 'DK' },
  'W14_NO_CAR':          { total: 43.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W14_ATL_CLE':         { total: 40.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W14_TEN_DET':         { total: 47.5, spread: -7.5, asOf: '2026-05-15', source: 'DK' },
  'W14_CHI_MIA':         { total: 46.5, spread: +5.5, asOf: '2026-05-15', source: 'DK' },
  'W14_DEN_NYJ':         { total: 39.5, spread: +5.5, asOf: '2026-05-15', source: 'DK' },
  'W14_IND_PHI':         { total: 46.5, spread: -5.5, asOf: '2026-05-15', source: 'DK' },
  'W14_HOU_WAS':         { total: 44.5, spread: +2.5, asOf: '2026-05-15', source: 'DK' },
  'W14_LAC_LV':          { total: 43.5, spread: +5.5, asOf: '2026-05-15', source: 'DK' },
  'W14_KC_CIN':          { total: 48.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W14_NYG_SEA':         { total: 45.5, spread: -7.5, asOf: '2026-05-15', source: 'DK' },
  'W14_LAR_SF':          { total: 49.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W14_BUF_GB':          { total: 49.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W14_PIT_JAX':         { total: 44.5, spread: -3, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 15 =====
  'W15_SF_LAC':          { total: 47.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W15_SEA_PHI':         { total: 43.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W15_CHI_BUF':         { total: 51.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W15_CIN_CAR':         { total: 47.5, spread: +2.5, asOf: '2026-05-15', source: 'DK' },
  'W15_MIA_GB':          { total: 45.5, spread: -10.5, asOf: '2026-05-15', source: 'DK' },
  'W15_JAX_HOU':         { total: 43.5, spread: -3, asOf: '2026-05-15', source: 'DK' },
  'W15_CLE_NYG':         { total: 40.5, spread: -4.5, asOf: '2026-05-15', source: 'DK' },
  'W15_BAL_PIT':         { total: 45.5, spread: +2.5, asOf: '2026-05-15', source: 'DK' },
  'W15_NO_TB':           { total: 45.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W15_IND_TEN':         { total: 47.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W15_ATL_WAS':         { total: 46.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W15_NYJ_ARI':         { total: 41.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W15_DAL_LAR':         { total: 52.5, spread: -5.5, asOf: '2026-05-15', source: 'DK' },
  'W15_DEN_LV':          { total: 41.5, spread: +4.5, asOf: '2026-05-15', source: 'DK' },
  'W15_DET_MIN':         { total: 46.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W15_NE_KC':           { total: 45.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 16 =====
  'W16_HOU_PHI':         { total: 41.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W16_GB_CHI':          { total: 47.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W16_BUF_DEN':         { total: 46.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W16_LAR_SEA':         { total: 47.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W16_CLE_BAL':         { total: 43.5, spread: -9.5, asOf: '2026-05-15', source: 'DK' },
  'W16_LAC_MIA':         { total: 44.5, spread: +7, asOf: '2026-05-15', source: 'DK' },
  'W16_ARI_NO':          { total: 44.5, spread: -5.5, asOf: '2026-05-15', source: 'DK' },
  'W16_NE_NYJ':          { total: 41.5, spread: +6.5, asOf: '2026-05-15', source: 'DK' },
  'W16_TEN_LV':          { total: 42.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W16_SF_KC':           { total: 46.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W16_JAX_DAL':         { total: 51.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W16_NYG_DET':         { total: 48.5, spread: -5.5, asOf: '2026-05-15', source: 'DK' },
  'W16_TB_ATL':          { total: 45.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W16_CIN_IND':         { total: 52.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W16_WAS_MIN':         { total: 46.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W16_CAR_PIT':         { total: 41.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 17 =====
  'W17_NO_ATL':          { total: 44.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W17_SEA_CAR':         { total: 42.5, spread: +5.5, asOf: '2026-05-15', source: 'DK' },
  'W17_IND_CLE':         { total: 43.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W17_NYG_DAL':         { total: 49.5, spread: -4.5, asOf: '2026-05-15', source: 'DK' },
  'W17_BUF_MIA':         { total: 47.5, spread: +7.5, asOf: '2026-05-15', source: 'DK' },
  'W17_MIN_NYJ':         { total: 40.5, spread: +3.5, asOf: '2026-05-15', source: 'DK' },
  'W17_PIT_TEN':         { total: 42.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W17_LV_ARI':          { total: 42.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W17_DET_CHI':         { total: 49.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W17_PHI_SF':          { total: 45.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W17_WAS_JAX':         { total: 48.5, spread: -3.5, asOf: '2026-05-15', source: 'DK' },
  'W17_KC_LAC':          { total: 45.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W17_DEN_NE':          { total: 42.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W17_LAR_TB':          { total: 48.5, spread: +3.5, asOf: '2026-05-15', source: 'DK' },
  'W17_BAL_CIN':         { total: 51.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W17_HOU_GB':          { total: 42.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },

  // ===== Week 18 =====
  'W18_SF_ARI':          { total: 44.5, spread: +8.5, asOf: '2026-05-15', source: 'DK' },
  'W18_PIT_BAL':         { total: 43.5, spread: -5.5, asOf: '2026-05-15', source: 'DK' },
  'W18_NYJ_BUF':         { total: 43.5, spread: -10, asOf: '2026-05-15', source: 'DK' },
  'W18_ATL_CAR':         { total: 41.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W18_CLE_CIN':         { total: 43.5, spread: -7.5, asOf: '2026-05-15', source: 'DK' },
  'W18_LAC_DEN':         { total: 41.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W18_DET_GB':          { total: 47.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W18_TEN_HOU':         { total: 39.5, spread: -7, asOf: '2026-05-15', source: 'DK' },
  'W18_JAX_IND':         { total: 46.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W18_LV_KC':           { total: 40.5, spread: -8.5, asOf: '2026-05-15', source: 'DK' },
  'W18_SEA_LAR':         { total: 45.5, spread: -2.5, asOf: '2026-05-15', source: 'DK' },
  'W18_CHI_MIN':         { total: 43.5, spread: -1.5, asOf: '2026-05-15', source: 'DK' },
  'W18_MIA_NE':          { total: 42.5, spread: -10.5, asOf: '2026-05-15', source: 'DK' },
  'W18_TB_NO':           { total: 43.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },
  'W18_PHI_NYG':         { total: 41.5, spread: +3, asOf: '2026-05-15', source: 'DK' },
  'W18_DAL_WAS':         { total: 49.5, spread: +1.5, asOf: '2026-05-15', source: 'DK' },

};

// ===== SEASON-LONG PLAYER PROPS (DraftKings / FanDuel / BetMGM) =============
// 2026 NFL SEASON-LONG player prop lines — for the player-card LINES tab.
// Manually pasted by Jack (same workflow as nfl_game_totals_2026.js).
//
// FULL-SEASON over/under totals (e.g. 4000.5 passing yds, 32.5 passing TDs),
// NOT weekly. Projection sums O/U lines into a season fantasy total, ÷17 = PPG.
//
//   BETTING_2026.seasonProps = { 'Player Name': { DK:{...}, FD:{...}, MGM:{...}, asOf } }
//
// Stat keys (season O/U line numbers):
//   py=pass yds · ptd=pass TDs · int=INTs · ry=rush yds · rtd=rush TDs
//   ra=rush att · rec=receptions · rcy=rec yds · rctd=rec TDs
// The O/U line is used directly as the expected value (odds not needed).
// Scoring: py/25 · ptd*4 · int*-2 · ry/10 · rtd*6 · rcy/10 · rctd*6 · rec*{1/.5/0}. PPG = total/17.
//
// NOTE: no book posts a season RECEPTIONS prop, so 'rec' is absent — PPR/Half/STD
// come out equal for pass-catchers until a receptions line is added.
// As of 2026-06-08: DraftKings + FanDuel + BetMGM loaded across QB/RB/WR/TE.

const _SEASON_PROPS_2026 = {
  'Joe Burrow': { DK: { py: 3999.5, ptd: 32.5 }, FD: { ptd: 32.5 }, MGM: { py: 4000.5, ptd: 32.5 }, asOf: '2026-06-08' },
  'Matthew Stafford': { DK: { py: 3999.5, ptd: 30.5 }, FD: { py: 3925.5, ptd: 29.5 }, MGM: { py: 4000.5, ptd: 30.5 }, asOf: '2026-06-08' },
  'Dak Prescott': { DK: { py: 3999.5, ptd: 27.5 }, FD: { py: 4050.5, ptd: 27.5 }, MGM: { py: 4000.5, ptd: 27.5 }, asOf: '2026-06-08' },
  'Drake Maye': { DK: { py: 3799.5, ptd: 26.5, ry: 424.5 }, FD: { py: 3800.5, ptd: 25.5, ry: 400.5, rtd: 3.5 }, MGM: { py: 3750.5, ptd: 26.5, ry: 400.5, rtd: 4.5 }, asOf: '2026-06-08' },
  'Trevor Lawrence': { DK: { py: 3749.5, ptd: 25.5 }, FD: { py: 3725.5, ptd: 25.5 }, MGM: { py: 3725.5, ptd: 25.5 }, asOf: '2026-06-08' },
  'Josh Allen': { DK: { py: 3549.5, ptd: 24.5, ry: 499.5, rtd: 11.5 }, FD: { py: 3575.5, ptd: 24.5, ry: 500.5, rtd: 10.5 }, MGM: { py: 3600.5, ptd: 24.5, ry: 500.5, rtd: 10.5 }, asOf: '2026-06-08' },
  'Justin Herbert': { DK: { py: 3574.5, ptd: 24.5 }, FD: { py: 3600.5, ptd: 25.5 }, MGM: { py: 3600.5, ptd: 24.5 }, asOf: '2026-06-08' },
  'Caleb Williams': { DK: { py: 3624.5, ptd: 24.5 }, FD: { py: 3575.5, ptd: 24.5 }, MGM: { py: 3600.5, ptd: 24.5 }, asOf: '2026-06-08' },
  'Tyler Shough': { DK: { py: 3649.5, ptd: 20.5 }, FD: { py: 3600.5, ptd: 19.5 }, MGM: { py: 3600.5, ptd: 20.5 }, asOf: '2026-06-08' },
  'Jordan Love': { DK: { py: 3549.5, ptd: 24.5 }, FD: { py: 3525.5, ptd: 24.5 }, MGM: { py: 3525.5, ptd: 24.5 }, asOf: '2026-06-08' },
  'Jayden Daniels': { DK: { py: 3249.5, ptd: 21.5, ry: 549.5 }, FD: { py: 3200.5, ptd: 20.5 }, MGM: { py: 3350.5, ptd: 21.5, rtd: 4.5 }, asOf: '2026-06-08' },
  'Lamar Jackson': { DK: { py: 3249.5, ptd: 24.5, ry: 574.5 }, FD: { py: 3200.5, ptd: 24.5, ry: 575.5, rtd: 3.5 }, MGM: { py: 3225.5, ptd: 24.5, ry: 575.5, rtd: 3.5 }, asOf: '2026-06-08' },
  'Fernando Mendoza': { DK: { py: 2499.5, ptd: 12.5 }, FD: { py: 2350.5, ptd: 12.5 }, MGM: { py: 2450.5, ptd: 12.5 }, asOf: '2026-06-08' },
  'Jared Goff': { DK: { py: 4099.5, ptd: 29.5 }, FD: { py: 4050.5, ptd: 29.5 }, MGM: { ptd: 29.5 }, asOf: '2026-06-08' },
  'Brock Purdy': { DK: { py: 3799.5, ptd: 27.5 }, FD: { py: 3650.5, ptd: 27.5 }, MGM: { ptd: 27.5 }, asOf: '2026-06-08' },
  'Baker Mayfield': { DK: { py: 3599.5, ptd: 25.5 }, FD: { py: 3500.5, ptd: 25.5 }, MGM: { ptd: 25.5 }, asOf: '2026-06-08' },
  'Bo Nix': { DK: { py: 3499.5, ptd: 24.5 }, MGM: { ptd: 24.5 }, asOf: '2026-06-08' },
  'Sam Darnold': { DK: { py: 3749.5, ptd: 23.5 }, FD: { py: 3700.5, ptd: 23.5 }, MGM: { ptd: 23.5 }, asOf: '2026-06-08' },
  'C.J. Stroud': { DK: { py: 3649.5, ptd: 22.5 }, FD: { py: 3550.5, ptd: 22.5 }, MGM: { ptd: 22.5 }, asOf: '2026-06-08' },
  'Jalen Hurts': { DK: { py: 3249.5, ptd: 22.5, ry: 399.5, rtd: 8.5 }, FD: { py: 3150.5, ptd: 22.5, ry: 400.5, rtd: 7.5 }, MGM: { ptd: 22.5, ry: 400.5, rtd: 8.5 }, asOf: '2026-06-08' },
  'Bryce Young': { DK: { py: 3074.5, ptd: 20.5 }, FD: { py: 3000.5, ptd: 20.5 }, MGM: { ptd: 20.5 }, asOf: '2026-06-08' },
  'Aaron Rodgers': { DK: { py: 3199.5, ptd: 21.5 }, FD: { py: 3025.5 }, MGM: { ptd: 20.5 }, asOf: '2026-06-08' },
  'Jaxson Dart': { DK: { py: 3150.5, ptd: 19.5, ry: 449.5 }, FD: { py: 2950.5, ptd: 19.5, ry: 425.5, rtd: 4.5 }, MGM: { ptd: 19.5, ry: 425.5, rtd: 5.5 }, asOf: '2026-06-08' },
  'Cam Ward': { DK: { py: 3299.5, ptd: 18.5 }, FD: { py: 3200.5, ptd: 19.5 }, MGM: { ptd: 18.5 }, asOf: '2026-06-08' },
  'Malik Willis': { DK: { py: 3050.5, ptd: 15.5 }, MGM: { ptd: 15.5 }, asOf: '2026-06-08' },
  'Jonathan Taylor': { DK: { ry: 1249.5, rtd: 11.5 }, FD: { ry: 1250.5, rtd: 11.5 }, MGM: { ry: 1250.5, rtd: 11.5 }, asOf: '2026-06-08' },
  'James Cook': { DK: { ry: 1249.5, rtd: 10.5 }, FD: { ry: 1225.5, rtd: 10.5 }, MGM: { ry: 1250.5, rtd: 10.5 }, asOf: '2026-06-08' },
  'Derrick Henry': { DK: { ry: 1274.5, rtd: 12.5 }, FD: { ry: 1250.5, rtd: 13.5 }, MGM: { ry: 1250.5, rtd: 12.5 }, asOf: '2026-06-08' },
  'Jahmyr Gibbs': { DK: { ry: 1249.5, rtd: 12.5 }, FD: { ry: 1175.5, rtd: 11.5 }, MGM: { ry: 1225.5, rtd: 12.5, rctd: 3.5 }, asOf: '2026-06-08' },
  'Bijan Robinson': { DK: { ry: 1174.5, rtd: 8.5 }, FD: { ry: 1175.5, rtd: 10.5 }, MGM: { ry: 1200.5, rtd: 8.5, rctd: 3.5 }, asOf: '2026-06-08' },
  'Saquon Barkley': { DK: { ry: 1099.5, rtd: 7.5 }, FD: { ry: 1075.5, rtd: 7.5 }, MGM: { ry: 1100.5, rtd: 7.5 }, asOf: '2026-06-08' },
  'Ashton Jeanty': { DK: { ry: 1024.5, rtd: 7.5 }, FD: { ry: 950.5, rtd: 7.5 }, MGM: { ry: 1000.5, rtd: 7.5 }, asOf: '2026-06-08' },
  "De'Von Achane": { DK: { ry: 999.5 }, FD: { ry: 1000.5 }, MGM: { ry: 1000.5, rtd: 5.5 }, asOf: '2026-06-08' },
  'Kyren Williams': { DK: { ry: 999.5, rtd: 9.5 }, MGM: { ry: 1000.5, rtd: 9.5 }, asOf: '2026-06-08' },
  'Christian McCaffrey': { DK: { ry: 974.5, rtd: 8.5 }, FD: { ry: 925.5, rtd: 8.5 }, MGM: { ry: 950.5, rtd: 8.5, rctd: 4.5 }, asOf: '2026-06-08' },
  'Kenneth Walker III': { DK: { ry: 924.5, rtd: 7.5 }, FD: { ry: 925.5, rtd: 7.5 }, MGM: { ry: 925.5, rtd: 7.5 }, asOf: '2026-06-08' },
  'Omarion Hampton': { DK: { ry: 949.5, rtd: 7.5 }, FD: { ry: 900.5, rtd: 7.5 }, MGM: { ry: 925.5, rtd: 7.5 }, asOf: '2026-06-08' },
  'Jeremiyah Love': { DK: { ry: 899.5, rtd: 5.5 }, FD: { ry: 875.5, rtd: 5.5 }, MGM: { ry: 900.5, rtd: 5.5 }, asOf: '2026-06-08' },
  'Breece Hall': { DK: { ry: 899.5 }, FD: { ry: 900.5, rtd: 5.5 }, MGM: { ry: 900.5, rtd: 5.5 }, asOf: '2026-06-08' },
  'Tony Pollard': { DK: { ry: 799.5 }, FD: { ry: 800.5, rtd: 5.5 }, MGM: { ry: 800.5, rtd: 5.5 }, asOf: '2026-06-08' },
  'David Montgomery': { DK: { ry: 774.5 }, FD: { ry: 800.5, rtd: 7.5 }, MGM: { ry: 775.5, rtd: 8.5 }, asOf: '2026-06-08' },
  'Javonte Williams': { DK: { ry: 999.5, rtd: 9.5 }, FD: { ry: 975.5, rtd: 9.5 }, MGM: { rtd: 9.5 }, asOf: '2026-06-08' },
  'Chase Brown': { DK: { ry: 824.5, rtd: 5.5 }, FD: { ry: 825.5, rtd: 5.5 }, MGM: { rtd: 6.5 }, asOf: '2026-06-08' },
  "D'Andre Swift": { DK: { ry: 799.5 }, FD: { ry: 800.5, rtd: 5.5 }, MGM: { rtd: 6.5 }, asOf: '2026-06-08' },
  'Rhamondre Stevenson': { FD: { rtd: 5.5 }, MGM: { rtd: 6.5 }, asOf: '2026-06-08' },
  'Bhayshul Tuten': { DK: { ry: 699.5 }, MGM: { rtd: 5.5 }, asOf: '2026-06-08' },
  'Blake Corum': { DK: { ry: 674.5 }, MGM: { rtd: 5.5 }, asOf: '2026-06-08' },
  'Bucky Irving': { MGM: { rtd: 5.5 }, asOf: '2026-06-08' },
  'J.K. Dobbins': { MGM: { rtd: 5.5 }, asOf: '2026-06-08' },
  'Jadarian Price': { MGM: { rtd: 5.5 }, asOf: '2026-06-08' },
  'Travis Etienne': { FD: { rtd: 5.5 }, MGM: { rtd: 5.5 }, asOf: '2026-06-08' },
  'TreVeyon Henderson': { FD: { rtd: 5.5 }, MGM: { rtd: 5.5 }, asOf: '2026-06-08' },
  'Chuba Hubbard': { MGM: { rtd: 4.5 }, asOf: '2026-06-08' },
  'Isiah Pacheco': { MGM: { rtd: 4.5 }, asOf: '2026-06-08' },
  'Jordan Mason': { MGM: { rtd: 4.5 }, asOf: '2026-06-08' },
  'Kyle Monangai': { MGM: { rtd: 4.5 }, asOf: '2026-06-08' },
  'Puka Nacua': { DK: { rcy: 1324.5, rctd: 7.5 }, FD: { rcy: 1375.5 }, MGM: { rcy: 1350.5, rctd: 8.5 }, asOf: '2026-06-08' },
  'Jaxon Smith-Njigba': { DK: { rcy: 1324.5, rctd: 8.5 }, FD: { rcy: 1350.5 }, MGM: { rcy: 1325.5, rctd: 8.5 }, asOf: '2026-06-08' },
  "Ja'Marr Chase": { DK: { rcy: 1324.5, rctd: 10.5 }, FD: { rcy: 1350.5 }, MGM: { rcy: 1300.5, rctd: 9.5 }, asOf: '2026-06-08' },
  'Amon-Ra St. Brown': { DK: { rcy: 1249.5, rctd: 9.5 }, FD: { rcy: 1225.5 }, MGM: { rcy: 1250.5, rctd: 9.5 }, asOf: '2026-06-08' },
  'CeeDee Lamb': { DK: { rcy: 1199.5, rctd: 7.5 }, FD: { rcy: 1225.5 }, MGM: { rcy: 1175.5, rctd: 7.5 }, asOf: '2026-06-08' },
  'Drake London': { DK: { rcy: 1149.5, rctd: 7.5 }, FD: { rcy: 1100.5 }, MGM: { rcy: 1150.5, rctd: 7.5 }, asOf: '2026-06-08' },
  'Justin Jefferson': { DK: { rcy: 1149.5, rctd: 6.5 }, FD: { rcy: 1150.5 }, MGM: { rcy: 1150.5, rctd: 7.5 }, asOf: '2026-06-08' },
  'A.J. Brown': { DK: { rcy: 1124.5 }, FD: { rcy: 1100.5 }, MGM: { rcy: 1075.5, rctd: 7.5 }, asOf: '2026-06-08' },
  'Nico Collins': { DK: { rcy: 1074.5, rctd: 6.5 }, FD: { rcy: 1050.5 }, MGM: { rcy: 1050.5, rctd: 6.5 }, asOf: '2026-06-08' },
  'Chris Olave': { DK: { rcy: 1024.5, rctd: 5.5 }, FD: { rcy: 1050.5 }, MGM: { rcy: 1025.5, rctd: 5.5 }, asOf: '2026-06-08' },
  'DeVonta Smith': { DK: { rcy: 1049.5 }, MGM: { rcy: 1000.5, rctd: 5.5 }, asOf: '2026-06-08' },
  'Trey McBride': { DK: { rcy: 999.5, rctd: 6.5 }, FD: { rcy: 1025.5 }, MGM: { rcy: 1000.5, rctd: 6.5 }, asOf: '2026-06-08' },
  'Garrett Wilson': { DK: { rcy: 999.5 }, FD: { rcy: 975.5 }, MGM: { rcy: 975.5, rctd: 4.5 }, asOf: '2026-06-08' },
  'Zay Flowers': { DK: { rcy: 974.5 }, FD: { rcy: 1000.5 }, MGM: { rcy: 975.5, rctd: 5.5 }, asOf: '2026-06-08' },
  'Terry McLaurin': { DK: { rcy: 949.5 }, MGM: { rcy: 950.5, rctd: 5.5 }, asOf: '2026-06-08' },
  'Mike Evans': { DK: { rcy: 899.5 }, MGM: { rcy: 925.5, rctd: 6.5 }, asOf: '2026-06-08' },
  'Tetairoa McMillan': { DK: { rcy: 949.5, rctd: 6.5 }, FD: { rcy: 925.5 }, MGM: { rcy: 925.5, rctd: 6.5 }, asOf: '2026-06-08' },
  'Brock Bowers': { DK: { rcy: 899.5, rctd: 7.5 }, FD: { rcy: 875.5 }, MGM: { rcy: 900.5, rctd: 7.5 }, asOf: '2026-06-08' },
  'Alec Pierce': { DK: { rcy: 899.5 }, FD: { rcy: 925.5 }, MGM: { rcy: 900.5, rctd: 5.5 }, asOf: '2026-06-08' },
  'Jameson Williams': { DK: { rcy: 899.5 }, FD: { rcy: 925.5 }, MGM: { rcy: 900.5, rctd: 5.5 }, asOf: '2026-06-08' },
  'Emeka Egbuka': { DK: { rcy: 874.5 }, FD: { rcy: 875.5 }, MGM: { rcy: 875.5, rctd: 6.5 }, asOf: '2026-06-08' },
  'Jaylen Waddle': { DK: { rcy: 874.5 }, FD: { rcy: 850.5 }, MGM: { rcy: 875.5, rctd: 5.5 }, asOf: '2026-06-08' },
  'Tee Higgins': { DK: { rcy: 874.5, rctd: 8.5 }, FD: { rcy: 875.5 }, MGM: { rcy: 875.5, rctd: 7.5 }, asOf: '2026-06-08' },
  'Ladd McConkey': { DK: { rcy: 849.5 }, FD: { rcy: 850.5 }, MGM: { rcy: 850.5, rctd: 5.5 }, asOf: '2026-06-08' },
  'Marvin Harrison Jr.': { DK: { rcy: 824.5 }, FD: { rcy: 825.5 }, MGM: { rcy: 825.5, rctd: 4.5 }, asOf: '2026-06-08' },
  'Luther Burden III': { DK: { rcy: 824.5 }, FD: { rcy: 800.5 }, MGM: { rcy: 800.5, rctd: 4.5 }, asOf: '2026-06-08' },
  'Carnell Tate': { DK: { rcy: 774.5 }, FD: { rcy: 775.5 }, MGM: { rcy: 775.5, rctd: 4.5 }, asOf: '2026-06-08' },
  'Jordyn Tyson': { DK: { rcy: 774.5 }, FD: { rcy: 800.5 }, MGM: { rcy: 775.5, rctd: 4.5 }, asOf: '2026-06-08' },
  'Davante Adams': { DK: { rcy: 774.5, rctd: 9.5 }, FD: { rcy: 800.5 }, MGM: { rcy: 775.5, rctd: 9.5 }, asOf: '2026-06-08' },
  'Christian Watson': { DK: { rcy: 799.5 }, FD: { rcy: 775.5 }, MGM: { rcy: 775.5, rctd: 6.5 }, asOf: '2026-06-08' },
  'Rome Odunze': { DK: { rcy: 799.5 }, FD: { rcy: 800.5 }, MGM: { rcy: 775.5, rctd: 7.5 }, asOf: '2026-06-08' },
  'D.J. Moore': { DK: { rcy: 799.5 }, MGM: { rcy: 750.5 }, asOf: '2026-06-08' },
  'Michael Pittman Jr.': { DK: { rcy: 774.5 }, MGM: { rcy: 750.5, rctd: 3.5 }, asOf: '2026-06-08' },
  'Colston Loveland': { DK: { rcy: 749.5 }, FD: { rcy: 750.5 }, MGM: { rcy: 750.5, rctd: 5.5 }, asOf: '2026-06-08' },
  'Kyle Pitts': { DK: { rcy: 774.5 }, FD: { rcy: 725.5 }, MGM: { rcy: 750.5, rctd: 3.5 }, asOf: '2026-06-08' },
  'Tyler Warren': { DK: { rcy: 724.5 }, FD: { rcy: 750.5 }, MGM: { rcy: 725.5, rctd: 4.5 }, asOf: '2026-06-08' },
  'Travis Kelce': { DK: { rcy: 674.5, rctd: 4.5 }, FD: { rcy: 675.5 }, MGM: { rcy: 675.5, rctd: 4.5 }, asOf: '2026-06-08' },
  'Makai Lemon': { DK: { rcy: 649.5 }, FD: { rcy: 650.5 }, MGM: { rcy: 650.5 }, asOf: '2026-06-08' },
  'KC Concepcion': { DK: { rcy: 624.5 }, FD: { rcy: 600.5 }, MGM: { rcy: 600.5 }, asOf: '2026-06-08' },
  'Romeo Doubs': { MGM: { rcy: 600.5, rctd: 4.5 }, asOf: '2026-06-08' },
  'Omar Cooper Jr.': { DK: { rcy: 549.5 }, FD: { rcy: 525.5 }, MGM: { rcy: 550.5, rctd: 3.5 }, asOf: '2026-06-08' },
  'Kenyon Sadiq': { FD: { rcy: 450.5 }, MGM: { rcy: 475.5, rctd: 3.5 }, asOf: '2026-06-08' },
  'George Pickens': { DK: { rcy: 999.5, rctd: 6.5 }, FD: { rcy: 1050.5 }, MGM: { rctd: 7.5 }, asOf: '2026-06-08' },
  'Courtland Sutton': { DK: { rcy: 799.5 }, MGM: { rctd: 7.5 }, asOf: '2026-06-08' },
  'DK Metcalf': { DK: { rcy: 824.5 }, MGM: { rctd: 6.5 }, asOf: '2026-06-08' },
  'Chris Godwin': { MGM: { rctd: 5.5 }, asOf: '2026-06-08' },
  'Dallas Goedert': { DK: { rcy: 574.5 }, MGM: { rctd: 5.5 }, asOf: '2026-06-08' },
  'Jakobi Meyers': { MGM: { rctd: 5.5 }, asOf: '2026-06-08' },
  'Mark Andrews': { DK: { rcy: 524.5 }, MGM: { rctd: 5.5 }, asOf: '2026-06-08' },
  'Quentin Johnston': { MGM: { rctd: 5.5 }, asOf: '2026-06-08' },
  'Brian Thomas Jr.': { DK: { rcy: 699.5 }, MGM: { rctd: 4.5 }, asOf: '2026-06-08' },
  'Parker Washington': { MGM: { rctd: 4.5 }, asOf: '2026-06-08' },
  'Sam LaPorta': { MGM: { rctd: 4.5 }, asOf: '2026-06-08' },
  'Tucker Kraft': { MGM: { rctd: 4.5 }, asOf: '2026-06-08' },
  'Xavier Worthy': { MGM: { rctd: 4.5 }, asOf: '2026-06-08' },
  'Calvin Ridley': { MGM: { rctd: 3.5 }, asOf: '2026-06-08' },
  'Dalton Kincaid': { DK: { rcy: 549.5 }, MGM: { rctd: 3.5 }, asOf: '2026-06-08' },
  'Isaiah Likely': { MGM: { rctd: 3.5 }, asOf: '2026-06-08' },
  'Rashid Shaheed': { MGM: { rctd: 3.5 }, asOf: '2026-06-08' },
  'Khalil Shakir': { DK: { rcy: 674.5 }, asOf: '2026-06-08' },
  'Jake Ferguson': { DK: { rcy: 524.5 }, asOf: '2026-06-08' },
  'Jayden Reed': { DK: { rcy: 649.5 }, asOf: '2026-06-08' },
  'Josh Downs': { DK: { rcy: 649.5 }, asOf: '2026-06-08' },
  'Jordan Addison': { DK: { rcy: 674.5 }, asOf: '2026-06-08' },
  'Denzel Boston': { DK: { rcy: 474.5 }, asOf: '2026-06-08' }
};

// ===== UNIFIED NAMESPACE ===================================================
window.BETTING_2026 = {
  gameTotals:  _GAME_TOTALS_2026,   // weekly game O/U + spreads
  seasonProps: _SEASON_PROPS_2026,  // season-long player props
  weeklyProps: {}                   // reserved: future weekly player props
};

(function() {
  window.getNflGameTotal = function(wk, away, home) {
    if (!wk || !away || !home) return null;
    const key = 'W' + wk + '_' + String(away).toUpperCase() + '_' + String(home).toUpperCase();
    const rec = window.BETTING_2026.gameTotals[key];
    return (rec && typeof rec.total === 'number') ? rec.total : null;
  };
  // Returns home-team spread (negative if home favored, positive if home underdog).
  window.getNflGameSpread = function(wk, away, home) {
    if (!wk || !away || !home) return null;
    const key = 'W' + wk + '_' + String(away).toUpperCase() + '_' + String(home).toUpperCase();
    const rec = window.BETTING_2026.gameTotals[key];
    return (rec && typeof rec.spread === 'number') ? rec.spread : null;
  };
  // Team-relative spread: returns the spread from `team`'s perspective.
  // Negative = team is favored, positive = team is underdog.
  window.getNflTeamSpread = function(wk, team, opp, isHome) {
    const away = isHome ? opp : team;
    const home = isHome ? team : opp;
    const homeSpread = window.getNflGameSpread(wk, away, home);
    if (typeof homeSpread !== 'number') return null;
    return isHome ? homeSpread : -homeSpread;
  };
  // Team-implied total: the points the given team is expected to score in
  // their game that week. Derived from O/U and spread:
  //   implied = (total - team_spread) / 2
  // When team is favored (negative team_spread), implied total goes UP.
  // E.g. KC -7 vs LAC, O/U 47 → KC implied 27, LAC implied 20.
  // More direct than raw O/U for individual skill-player scoring environment.
  window.getNflTeamImpliedTotal = function(wk, team, opp, isHome) {
    const away = isHome ? opp : team;
    const home = isHome ? team : opp;
    const total = window.getNflGameTotal(wk, away, home);
    const teamSpread = window.getNflTeamSpread(wk, team, opp, isHome);
    if (typeof total !== 'number' || typeof teamSpread !== 'number') return null;
    return (total - teamSpread) / 2;
  };
  window.classifyGameTotal = function(total) {
    if (typeof total !== 'number') return { tier: null, color: null, label: '—' };
    if (total >= 47)   return { tier: 'high', color: '#22c55e', label: total.toFixed(1) };
    if (total <= 42)   return { tier: 'low',  color: '#ef4444', label: total.toFixed(1) };
    return { tier: 'mid', color: '#facc15', label: total.toFixed(1) };
  };
  window.getNflTotalsCount = function() {
    return Object.values(window.BETTING_2026.gameTotals).filter(r => r && typeof r.total === 'number').length;
  };
})();
