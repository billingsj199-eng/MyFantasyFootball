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
window.IN_SEASON_OUT_OVERRIDES_ASOF = '2026-09-27';
window.IN_SEASON_OUT_OVERRIDES = {
  // 2026-10-05: full list rechecked (team / insider / injury-doc reports). Expired single-week entries removed -
  // Jefferson, Dowdle, Douglas and Hollywood Brown are W5-uncertain: landing entries below (practicing LP / FP -> the designation decides).
  'Justin Jefferson': [4, 4, '2026-10-05', 7],   // 2026-10-05 recheck: minor ankle sprain W3, missed W4, no practice; O'Connell "unsure" for W5, Fowler says could play (NBC 10/3-4, med) - W6 bye
  'Rico Dowdle': [3, 4, '2026-10-05', 6],        // 2026-10-05 recheck: toe, missed W2-W4; Rapoport "pretty good chance" back W5 after the mini-bye (NBC 10/1, med)
  'Caleb Douglas': [3, 5, '2026-10-05', 7],      // 2026-10-05 recheck: ankle from W2, inactive W3-W4, no practice yet; W6 realistic (NBC 10/4, low-med)
  'Marquise Brown': [3, 5, '2026-10-05', 7],     // 2026-10-05 recheck: ankle, missed W3-W4, no practice; "a bit of a mystery how long" - W6 most likely (Inside the Iggles 10/5, low)
  'Jordan Mason': [2, 6, '2026-10-05', 'firm'],   // 2026-10-05 recheck: thumb, IR 9/16; O'Connell expects only the 4-game minimum, W6 bye -> back W7 vs IND (ESPN, high)
  'Lamar Jackson': [5, 5, '2026-10-07'],   // 2026-10-07 (Jack): ankle, listed Q, but DK/FD/UD/PP pulled his W5 props and post Huntley as starter (173.5 py); BAL@ATL went BAL -6/49.5 -> ATL -3.5/43.5
  'Jaxson Dart': [3, 18, '2026-10-05'],   // 2026-10-05 recheck: MCL/PCL/meniscus surgery, 6-9 months, done for '26 (NBC 9/23); Winston starts
  // ---- IR / multi-week windows (format: [from, lastSurelyOut, 'date', latestWeek | 'firm']) ----
  'Josh Jacobs': [3, 5, '2026-10-05', 8],   // 2026-10-05 recheck: still on the Commissioner's Exempt List, no ruling; 4-6 game ban with time credited floated (low)
  'A.J. Brown': [3, 5, '2026-10-05', 9],   // 2026-10-05 recheck: high ankle W1, IR; team 'hopes' W6 (Garafolo 10/4, far from certain), 6-8 wks (Schefter) = W7-W9 (med)
  'Jayden Daniels': [3, 4, '2026-10-05'],   // 2026-10-05 recheck: elbow, missed W3-W4, limited in a brace; could play W5 if full all week (J. Jones 10/3)
  'Alec Pierce': [3, 6, '2026-10-05', 9],   // 2026-10-05 recheck: heel, IR 9/26, cast + scooter, no timeline; eligible W7, likely later (ESPN, low)
  'Caleb Williams': [3, 5, '2026-10-05', 7],   // 2026-10-05 recheck: Grade 2 hamstring; ruled out W5 (Ben Johnson 10/5), 'at least one more week' -> W6 @ATL possible
  'Jordyn Tyson': [3, 6, '2026-10-05', 9],   // 2026-10-05 recheck: hamstring, IR-DTR, not practicing; unlikely before W7, W9 logical after the W8 bye (Schefter 10/5)
  'Ricky Pearsall': [3, 18, '2026-10-05'],   // 2026-10-05 recheck: PCL reconstruction, ~9 months, season over (PFR / CBS)
  'Jayden Reed': [3, 18, '2026-10-05'],   // 2026-10-05 recheck: neck surgery, season-ending (LaFleur 9/30)
  'Jayden Higgins': [3, 18, '2026-10-05'],   // 2026-10-05 recheck: torn ACL in camp, season over (NFL Network)
  'Omar Cooper Jr.': [3, 5, '2026-10-05'],   // 2026-10-05 recheck: high ankle, IR-DTR 9/19; eligible W6, not expected to miss much beyond the minimum (med)
  'Dallas Goedert': [3, 5, '2026-10-05', 7],   // 2026-10-05 recheck: MCL, 'a few weeks', no practice since; W6 likelier than W5 (low)
  'Jonah Coleman': [3, 6, '2026-10-05'],   // 2026-10-05 recheck: high ankle, IR 9/26; expected back when first eligible, W7 vs ARI (ESPN / 9News, med)
  'Jonathon Brooks': [3, 8, '2026-10-05', 10],   // 2026-10-05 recheck: core muscle surgery, IR 9/23; 6-8 wks (Canales) = W9-W10
  'Isiah Pacheco': [3, 13, '2026-10-05', 15],   // 2026-10-05 recheck: back surgery 9/14, 12-wk recovery, 'chance' by early December (Rapoport); W13 is the optimistic end
  'Dylan Sampson': [3, 5, '2026-10-05', 8],   // 2026-10-05 recheck: knee, IR 9/15, 'significant time' (Fowler); eligible W6, W7+ realistic (low)
  'Eli Stowers': [3, 5, '2026-10-05', 8],   // 2026-10-05 recheck: quad + hamstring, IR 9/12, no practice window, no update (low)
  'James Conner': [3, 5, '2026-10-05', 8],   // 2026-10-05 recheck: foot, IR-DTR, window not opened; LaFleur wants him back at his normal level, not just practicing (10/2, low)
  'Trey Benson': [3, 18, '2026-10-05'],   // 2026-10-05 recheck: meniscus; waived-injured, reverted to ARI IR, season over (SI)
  'Christian Kirk': [3, 6, '2026-10-05', 8],   // 2026-10-05 recheck: calf, IR-DTR; Shanahan hopes to open the window 'in about two weeks' (10/4) -> about W7
  'Mason Taylor': [3, 4, '2026-10-05', 6],   // 2026-10-05 recheck: thumb, missed W3-W4, DNP all week, week-to-week; W5 TBD, W6 safer (low)
  'Tank Dell': [3, 5, '2026-10-05', 7],   // 2026-10-05 recheck: knee, IR-DTR, window opens Wed 10/7 (Ryans 10/5); unlikely W5, W6-W7
  'Chris Brazzell II': [3, 18, '2026-10-05'],   // 2026-10-05 recheck: torn LCL, July surgery, season over (ESPN)
  'David Njoku': [3, 6, '2026-10-05', 9],   // 2026-10-05 recheck: fibula, IR ~9/21; eligible W7, no timeline beyond the minimum (low)
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
