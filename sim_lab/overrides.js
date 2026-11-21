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
// 2026-10-09 (Jack: "use depth charts for the qb starters"): from the current week on the ESPN chart QB1 starts every
// remaining game (engine qbChartWindows); these windows now only describe games ALREADY PLAYED. The LV / CLE future
// handoffs below no longer apply unless the chart changes. Kill: window.SIM_QB_CHART = false (restores these windows).
window.QB_ROOM_OVERRIDES = {
  ATL: [['Cooper Rush', 2], ['Michael Penix Jr.', 15], ['Tua Tagovailoa', 0]],   // 2026-09-23 (Jack): Rush started W1-2, Penix announced starter from W3 on; Tua 0 = benched (Penix keeps Clay's per-start rate). 2026-10-02 (Jack): Penix is the starter the rest of the season barring injury - unchanged
  // 2026-10-02 (Jack): "both browns and raiders starting qbs have played well so I would assume they go further into
  // the season". The preseason guess had Cousins handing off after 4 games and Watson after 7. No switch is announced,
  // so the handoff is moved to each team's BYE (my reading of "further" - Jack gave no week): Cousins starts through
  // week 12 (LV bye 13), Watson through week 10 (CLE bye 11). Set the veteran to 17 / the rookie to 0 if he keeps
  // the job all year, or move the split when a change is announced.
  LV:  [['Kirk Cousins', 12], ['Fernando Mendoza', 5]],
  CLE: [['Deshaun Watson', 10], ['Shedeur Sanders', 7]],
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
//
// 2026-10-01 (injury signals): the news feed now fills these windows by itself
// (data/sim_injury_signals.js: "out 4-6 weeks", "out until week 7", "out for the
// season", "ruled out"), so this list is for what the news cannot say. Rules:
//   - an entry here wins over the news UNLESS the news item is newer than the entry.
//     An entry's date = an optional third element, [from, to, 'YYYY-MM-DD'];
//     entries without one use IN_SEASON_OUT_OVERRIDES_ASOF below.
//   - once a window has ended (to < current week) it no longer speaks for the
//     player: his current designation takes over (it used to read as "healthy").
//   - 2026-10-05 (Jack: IR players don't come back the first week eligible): the
//     weeks AFTER a window get a soft landing - P(plays) .60 / .80 / .90 over his
//     next three games - unless the entry's 4th element says otherwise:
//       [from, to, 'date', 9]       latest expected week -> 50% the first week
//                                   after `to`, rising to 90% by week 9
//       [from, to, 'date', 'firm']  return confirmed (activated / team says he
//                                   plays) -> full strength right after `to`
//     A player practicing (LP / FP) on the current report also lands firm.
//     So `to` = the last week he is surely out (usually the IR minimum).
// Bump the ASOF date whenever the whole list is re-checked.
window.IN_SEASON_OUT_OVERRIDES_ASOF = '2026-11-15';
window.IN_SEASON_OUT_OVERRIDES = {
  // 2026-11-15: full list rechecked for W10 (Sleeper + NFL report 11-13, team / insider / beat reports). 19 expired entries removed:
  // healthy / designation decides (Jefferson, Dowdle, Douglas, M. Brown, Mason, Daniels, C. Williams, Tyson, Goedert, Coleman, Sampson,
  // Stowers, M. Taylor, Dell, A.J. Brown Q, Omar Cooper Q, Njoku Q in window, Henderson illness) or covered by newer news windows
  // (Lamar Jackson thumb = season, Josh Jacobs finger = 2-3 wks, in sim_injury_signals).
  'Jaxson Dart': [3, 18, '2026-11-15'],   // 2026-11-15 recheck: MCL/PCL/meniscus surgery, IR, done for '26 (NBC 9/23, high)
  'Ricky Pearsall': [3, 18, '2026-11-15'],   // 2026-11-15 recheck: PCL reconstruction, IR, season over (PFR / CBS, high)
  'Jayden Reed': [3, 18, '2026-11-15'],   // 2026-11-15 recheck: neck surgery, IR, season-ending (LaFleur 9/30, high)
  'Jayden Higgins': [3, 18, '2026-11-15'],   // 2026-11-15 recheck: torn ACL, IR, season over (NFL Network, high)
  'Trey Benson': [3, 18, '2026-11-15'],   // 2026-11-15 recheck: meniscus, ARI IR, season over (SI, high)
  'Chris Brazzell II': [3, 18, '2026-11-15'],   // 2026-11-15 recheck: torn LCL, IR, season over (ESPN, high)
  // ---- IR / multi-week windows (format: [from, lastSurelyOut, 'date', latestWeek | 'firm']) ----
  'Isiah Pacheco': [3, 13, '2026-11-15', 15],   // 2026-11-15 recheck: back surgery 9/14, still IR, no window; 12-wk recovery = ~Dec 7 (W13), ramp-up likely (Rapoport via ESPN, med)
  'Jonathon Brooks': [3, 10, '2026-11-15', 12],   // 2026-11-15 recheck: core/groin, IR-DTR window opened 11/11 (Kaye, ESPN); Doubtful -> Out W10 (Person, Athletic); back before end of Nov, behind Hubbard (med)
  'Mike Evans': [6, 10, '2026-11-15', 12],   // 2026-11-15 recheck: right Achilles tendinitis (not IR), missed W7 + W9, Out W10 (DNP all week); Shanahan 'sooner than later', 'may return W11' (NBCS Bay Area / 49ers Webzone 11/5, TFF, low-med)
  'Alec Pierce': [3, 11, '2026-11-15', 15],   // 2026-11-15 recheck: heel, IR, rehab (no surgery), window still not opened; Steichen no timetable 11/11 (RotoBaller / 4for4, low)
  'James Conner': [3, 11, '2026-11-15', 14],   // 2026-11-15 recheck: foot, still IR, window not opened, out W9 (RotoWire 11/5); no timeline (low)
  'Christian Kirk': [9, 12, '2026-11-15', 15],   // 2026-11-15 recheck: right meniscus (practice ~11/5), back on IR 11/7 = out W9-W12 min; surgery undecided, SF short on DTR slots (49ers Webzone / NBCS Bay Area, med)
  'Jeremiyah Love': [9, 12, '2026-11-15', 14],   // 2026-11-15 add: high ankle (re-injured W8), IR 11/3, out 4-5 weeks (NFL Network / azfamily 11/3-4, med-high)
  'Brian Robinson Jr.': [9, 12, '2026-11-15'],   // 2026-11-15 add: hamstring, IR 11/7, at least 4 games (AJC / Underdog, med); no timeline past the minimum
  'Romeo Doubs': [7, 11, '2026-11-15', 13],   // 2026-11-15 add: right shoulder, IR 10/19; targeting post-bye return W12 vs LAC (FantasyNerds 10/20), Vrabel no timeline (Boston.com 10/20, low-med)
  'RJ Harvey': [9, 12, '2026-11-15', 13],   // 2026-11-15 add: knee (practice), short-term IR, 'not severe or long term', can't return before W13 vs MIA (Denver Post via TFF, low-med; season dating unclear)
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

// SEASON_SCENARIOS (2026-10-09, Jack: "season sims in and out for very weird situations like the Packers backfield so we can
// see Lloyd with and without Jacobs"): every player listed here gets two extra full rest-of-season worlds in the site export -
// WITH him (back at full strength from `back`, default = his first game week after the current window) and WITHOUT him (out
// for the rest of the season). Each teammate whose numbers move gets weekly rows + a season sim in both, and the site's
// player card shows a WITH / WITHOUT toggle. The normal projections stay the blended read (P(plays) per week).
// Remove an entry once the situation resolves (ruling, return, IR to season-ending).
window.SEASON_SCENARIOS = {
  'Josh Jacobs': { note: "Commissioner's Exempt List - no ruling yet", back: 6 },   // 2026-10-09: WITH = plays from week 6
};
