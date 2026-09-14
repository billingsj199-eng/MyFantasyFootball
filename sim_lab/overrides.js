// ============================================================================
// MANUAL OVERRIDES — edit this file as camp/season news breaks, then reload.
//
// QB_ROOM_OVERRIDES: force a team's QB starter sequence instead of the
// auto-detected Clay point-split. Ordered [name, games] pairs from Week 1's
// starter onward. Game counts are TEAM GAMES (byes skipped automatically).
// Example:
//   LV:  [['Kirk Cousins', 4], ['Fernando Mendoza', 13]],
//   ATL: [['Tua Tagovailoa', 9], ['Michael Penix Jr.', 8]],
//
// Leave a team out to keep the automatic detection (vet opens the season,
// games estimated from Clay's point split).
// ============================================================================
window.QB_ROOM_OVERRIDES = {
};

// INJURY_WINDOW_OVERRIDES: correct a start-of-season injury window when news
// breaks. Value = games missed at the START of the season; 0 = confirmed
// healthy for Week 1 (kills the auto-window). Examples:
//   'Malik Nabers': 0,        // cleared — plays the full season
//   'Zach Charbonnet': 8,     // setback — now out the first 8 games
window.INJURY_WINDOW_OVERRIDES = {
};

// IN_SEASON_OUT_OVERRIDES (used by export_site_proj.js, in-season only):
// force a mid-season absence window when the news has a real timeline —
// value = [fromWeek, toWeek] (inclusive), 0 or null = confirmed healthy
// (kills the automatic designation-based window). The zeroed player's
// projected points partially redistribute to his position group for those
// weeks (QB 85% to the next man up; RB/WR/TE 60% across the group).
// Examples:
//   'Puka Nacua': [5, 6],     // "out ~2 weeks" — weeks 5-6 zeroed
//   'Bijan Robinson': 0,      // tag is stale — confirmed playing
window.IN_SEASON_OUT_OVERRIDES = {
  'Brock Bowers': [1, 1],   // 2026-09-09: ruled out for Week 1 (Jack)
};

// ELITE_CBS_2026: the shadow-corner list (backtest_cb_shadow.py — an elite
// CB on the field is worth ~6% of an opposing-WR week, and the FPA layer
// doesn't catch it). Opposing WRs get a flat ×0.96 while the listed CB's
// team defense has him available. Names must match SLEEPER full names
// (refresh_data.py resolves team + weekly injury status from the Sleeper
// dump into SIM_CB_STATUS — a CB who is Out/Doubtful/IR docks nothing).
// Edit as reputations change; kill switch: window.SIM_CB_DOCK = false.
window.ELITE_CBS_2026 = [
  'Pat Surtain',        // DEN
  'Derek Stingley',     // HOU
  'Sauce Gardner',      // IND (traded from NYJ Nov 2025)
  'Christian Gonzalez', // NE
  'Quinyon Mitchell',   // PHI
  'Jaylon Johnson',     // CHI
];

// PROP_ANCHOR_OVERRIDES: per-player prop-anchor weight (PROP_ANCHOR_SPEC.md).
// 0 = don't anchor this player this week (his lines are stale — late scratch,
// role news the books haven't repriced); 0..1 = custom market weight (engine
// default PROP_W = 0.70, i.e. 70% market / 30% model). Examples:
//   'Bijan Robinson': 0,      // ruled out late — books pulled his lines
//   'Puka Nacua': 0.4,        // trust the model more this week
window.PROP_ANCHOR_OVERRIDES = {
};
