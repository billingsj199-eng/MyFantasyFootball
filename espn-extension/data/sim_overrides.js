// COPY of ../sim_lab/overrides.js (synced 2026-08-11 09:59:36 by export_sleeper_extension_data.py — edit the sim_lab original)
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
