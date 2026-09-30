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
// Games = starts in the window; 0 = benched all season. The per-start rate
// stays Clay's (window length never dilutes it).
//
// Leave a team out to keep the automatic detection (vet opens the season,
// games estimated from Clay's point split).
// ============================================================================
window.QB_ROOM_OVERRIDES = {
  ATL: [['Cooper Rush', 2], ['Michael Penix Jr.', 15], ['Tua Tagovailoa', 0]],   // 2026-09-23 (Jack): Rush started W1-2, Penix announced starter from W3 on; Tua 0 = benched (Penix keeps Clay's per-start rate)
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
  'Sam Darnold': 0,         // 2026-09-27: off the injury report, full practice, "ready to go" W3 (was [2, 6] from the Sep 15 4-6 week report)
  'Jordan Mason': [2, 6],   // 2026-09-16: placed on IR (thumb surgery) — earliest return W7 vs IND (MIN bye W6); Aaron Jones absorbs the RB pool
  'Jaxson Dart': [3, 18],   // 2026-09-23 (Jack): out for the season — Jameis Winston starts (QB 85% next-man-up)
  // ---- 2026-09-27 injury check before the Week 3 league sims (reported = team/insider timeline, est = inferred) ----
  'Puka Nacua': [3, 3],          // hip/groin strain, Doubtful + DNP; could return W4 (est)
  'Nico Collins': [3, 3],        // hamstring, Out W3; next chance W4 (est)
  'Josh Jacobs': [3, 5],         // Commissioner's Exempt List since 8/30; 4-6 game suspension expected, list time counts (est, ruling pending)
  'A.J. Brown': [3, 5],          // high ankle, IR 9/11; earliest W6 (reported minimum, ~6 weeks)
  'Jayden Daniels': [3, 3],      // dislocated non-throwing elbow; team hopeful for W4 in a brace (reported)
  'Alec Pierce': [3, 6],         // heel, IR; earliest W7 (reported)
  'Caleb Williams': [3, 4],      // hamstring, week-to-week (est)
  'Jordyn Tyson': [3, 4],        // hamstring, IR-DTR; eligible W5 (reported minimum)
  'Rico Dowdle': [3, 3],         // toe, Out W3; questionable for W4 (est)
  'Ricky Pearsall': [3, 18],     // PCL surgery, out for the season (reported)
  'Jayden Reed': [3, 8],         // neck, carted off W2; NO timeline, team won't rule out season-ending (pure estimate — revisit)
  'Jayden Higgins': [3, 18],     // torn ACL, out for the season (reported)
  'Caleb Douglas': [3, 3],       // ankle, Out W3, no timeline (est)
  'Omar Cooper Jr.': [3, 5],     // ankle, IR 9/19; eligible W6 (reported)
  'Dallas Goedert': [3, 5],      // MCL sprain, "a few weeks" (est)
  'Jonah Coleman': [3, 6],       // high ankle, IR 9/26; expected back W7 (reported)
  'Jonathon Brooks': [3, 8],     // core muscle surgery, IR 9/23; at least 6 weeks (reported)
  'Chig Okonkwo': [3, 3],        // hamstring, Out W3 (est)
  'Isiah Pacheco': [3, 13],      // back surgery + MCL; ~12 weeks, December return possible (reported)
  'Dylan Sampson': [3, 5],       // knee, IR 9/15; eligible W6 (reported)
  'Eli Stowers': [3, 4],         // quad/hamstring, IR; earliest W5 (reported minimum)
  'James Conner': [3, 4],        // foot, IR-DTR; eligible W5 (reported minimum)
  'Trey Benson': [3, 18],        // meniscus, season over in ARI (reported)
  'Christian Kirk': [3, 4],      // calf, IR-DTR; eligible W5 (reported minimum)
  'Mason Taylor': [3, 4],        // thumb, week-to-week (est)
  'Tank Dell': [3, 5],           // knee recovery, IR-DTR; eligible W5 but GM says he needs time (est)
  'Chris Brazzell II': [3, 18],  // LCL surgery, out for the season (reported)
  'David Njoku': [3, 6],         // fibula, IR 9/21; earliest W7 (reported minimum)
  'Marquise Brown': [3, 3],      // ankle, Out W3 (est)
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
