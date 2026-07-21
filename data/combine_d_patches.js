// === COMBINE_DATA + D[] patches — extracted from index.html inline block (2026-07-20) ===
// Was the last parser-blocking inline consumer of COMBINE_DATA/D. Now loaded with
// defer AFTER combine_data.js and d.js (document order) and BEFORE app.js, so the
// execution order is identical to the old inline placement. Do not load without defer.
// Fix combine data errors from external file
if (typeof COMBINE_DATA !== 'undefined') {
  // Name-audit cleanup: post-rename, the son's record ("Marvin Harrison Jr.") inherited
  // dad's accolades (pb:8, ap:3, hof:1, dt:IND) from the original mixed record.
  // Strip them and restore father's record under the base name.
  if (COMBINE_DATA['Marvin Harrison Jr.'] && COMBINE_DATA['Marvin Harrison Jr.'].hof) {
    // Save dad's career under the base name
    COMBINE_DATA['Marvin Harrison'] = { yr: 1996, school: 'Syracuse', ht: '6-0', wt: 181, draft: 19, dt: 'IND', pb: 8, ap: 3, hof: 1 };
    // Clean the son's record — keep only his draft info
    COMBINE_DATA['Marvin Harrison Jr.'] = { yr: 2024, school: 'Ohio St.', ht: '6-3', wt: 209, draft: 4, dt: 'ARI' };
  }
  // Travis Hunter: 2025 draft, pick 2 overall — 2-way player, WR for fantasy
  if (!COMBINE_DATA['Travis Hunter']) {
    COMBINE_DATA['Travis Hunter'] = { yr: 2025, school: 'Colorado', pos: 'WR', ht: '6-1', wt: 188, draft: 2, dt: 'JAX' };
  } else {
    // Force critical fields — combine_data.js may have stale values
    const th = COMBINE_DATA['Travis Hunter'];
    th.draft = 2;
    th.yr = 2025;
    th.dt = 'JAX';
    th.pos = 'WR';
    if (!th.ht) th.ht = '6-1';
    if (!th.wt) th.wt = 188;
    if (!th.school) th.school = 'Colorado';
  }
  // Travis Hunter combine/pro day measurables + RAS
  (function() {
    const th = COMBINE_DATA['Travis Hunter'];
    if (!th.forty) th.forty = 4.38;
    if (!th.vert) th.vert = 40.5;
    if (!th.broad) th.broad = 131;
    if (!th.cone) th.cone = 6.74;
    if (!th.ras) th.ras = 9.88;
    if (!th.hand) th.hand = 9.25;
    if (!th.arm) th.arm = 32.5;
  })();
  // Travis Hunter college stats set AFTER college_stats.js loads (see below line ~4380)
  // 2026 prospects missing RAS scores — from ras.football CSV
  if (COMBINE_DATA['Elijah Sarratt'] && !COMBINE_DATA['Elijah Sarratt'].ras) COMBINE_DATA['Elijah Sarratt'].ras = 6.30;
  if (COMBINE_DATA['Behren Morton'] && !COMBINE_DATA['Behren Morton'].ras) COMBINE_DATA['Behren Morton'].ras = 5.40;
  if (COMBINE_DATA['Leon Neal'] && !COMBINE_DATA['Leon Neal'].ras) COMBINE_DATA['Leon Neal'].ras = 2.49;
  if (COMBINE_DATA['Roman Hemby'] && !COMBINE_DATA['Roman Hemby'].ras) COMBINE_DATA['Roman Hemby'].ras = 6.24;
  if (COMBINE_DATA['Roydell Williams'] && !COMBINE_DATA['Roydell Williams'].ras) COMBINE_DATA['Roydell Williams'].ras = 7.01;
  if (COMBINE_DATA['Sebastian Brown'] && !COMBINE_DATA['Sebastian Brown'].ras) COMBINE_DATA['Sebastian Brown'].ras = 4.72;
  // NOTE: PFF apostrophe-name alias fixes live in the pff_grades.js patch block
  // (after the script tag loads), not here.
  // [Name audit] Michael Penix Jr. — d.js, combine_data, college_stats, pff_grades
  // now all use "Michael Penix Jr." consistently. Legacy aliasing no longer needed.
  // === TOP 50 DEVY PROSPECTS (from KTC devy rankings) ===
  // Added with pos and school so they appear in the COLLEGE tab.
  // No draft pick = college-only prospect.
  if (!COMBINE_DATA['Jeremiah Smith']) COMBINE_DATA['Jeremiah Smith'] = { school: 'Ohio St.', pos: 'WR', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Malachi Toney']) COMBINE_DATA['Malachi Toney'] = { school: 'Miami (FL)', pos: 'WR', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Cam Coleman']) COMBINE_DATA['Cam Coleman'] = { school: 'Texas', pos: 'WR', devy: true, eligYr: 2027 };
  // Ryan Williams — Alabama WR devy. Force overwrite old Virginia Tech RB (2011) from combine_data.js.
  COMBINE_DATA['Ryan Williams'] = { school: 'Alabama', pos: 'WR', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Bryant Wesco Jr.']) COMBINE_DATA['Bryant Wesco Jr.'] = { school: 'Clemson', pos: 'WR', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Bo Jackson']) COMBINE_DATA['Bo Jackson'] = { school: 'Ohio St.', pos: 'RB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Kewan Lacy']) COMBINE_DATA['Kewan Lacy'] = { school: 'Mississippi', pos: 'RB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Justice Haynes']) COMBINE_DATA['Justice Haynes'] = { school: 'Georgia Tech', pos: 'RB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Hollywood Smothers']) COMBINE_DATA['Hollywood Smothers'] = { school: 'Texas', pos: 'RB', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Dante Moore']) COMBINE_DATA['Dante Moore'] = { school: 'Oregon', pos: 'QB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Arch Manning']) COMBINE_DATA['Arch Manning'] = { school: 'Texas', pos: 'QB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Isaac Brown']) COMBINE_DATA['Isaac Brown'] = { school: 'Louisville', pos: 'RB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Mark Fletcher Jr.']) COMBINE_DATA['Mark Fletcher Jr.'] = { school: 'Miami (FL)', pos: 'RB', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Jordon Davison']) COMBINE_DATA['Jordon Davison'] = { school: 'Oregon', pos: 'RB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Ryan Wingo']) COMBINE_DATA['Ryan Wingo'] = { school: 'Texas', pos: 'WR', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['LJ Martin']) COMBINE_DATA['LJ Martin'] = { school: 'BYU', pos: 'RB', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Eugene Wilson III']) COMBINE_DATA['Eugene Wilson III'] = { school: 'LSU', pos: 'WR', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['LaNorris Sellers']) COMBINE_DATA['LaNorris Sellers'] = { school: 'South Carolina', pos: 'QB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Ahmad Hardy']) COMBINE_DATA['Ahmad Hardy'] = { school: 'Missouri', pos: 'RB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Dallas Wilson']) COMBINE_DATA['Dallas Wilson'] = { school: 'Florida', pos: 'WR', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Jayce Brown']) COMBINE_DATA['Jayce Brown'] = { school: 'LSU', pos: 'WR', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Dakorien Moore']) COMBINE_DATA['Dakorien Moore'] = { school: 'Oregon', pos: 'WR', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA["Trey'Dez Green"]) COMBINE_DATA["Trey'Dez Green"] = { school: 'LSU', pos: 'TE', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Nick Marsh']) COMBINE_DATA['Nick Marsh'] = { school: 'Indiana', pos: 'WR', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Dierre Hill Jr.']) COMBINE_DATA['Dierre Hill Jr.'] = { school: 'Oregon', pos: 'RB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Nyck Harbor']) COMBINE_DATA['Nyck Harbor'] = { school: 'South Carolina', pos: 'WR', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Caleb Hawkins']) COMBINE_DATA['Caleb Hawkins'] = { school: 'Oklahoma St.', pos: 'RB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Brendan Sorsby']) COMBINE_DATA['Brendan Sorsby'] = { school: 'Texas Tech', pos: 'QB', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Terrance Carter Jr.']) COMBINE_DATA['Terrance Carter Jr.'] = { school: 'Texas Tech', pos: 'TE', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['CJ Baxter Jr.']) COMBINE_DATA['CJ Baxter Jr.'] = { school: 'Kentucky', pos: 'RB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Julian Sayin']) COMBINE_DATA['Julian Sayin'] = { school: 'Ohio St.', pos: 'QB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Jaron-Keawe Sagapolutele']) COMBINE_DATA['Jaron-Keawe Sagapolutele'] = { school: 'California', pos: 'QB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Sam Leavitt']) COMBINE_DATA['Sam Leavitt'] = { school: 'LSU', pos: 'QB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Harlem Berry']) COMBINE_DATA['Harlem Berry'] = { school: 'LSU', pos: 'RB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Isaiah Sategna III']) COMBINE_DATA['Isaiah Sategna III'] = { school: 'Oklahoma', pos: 'WR', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Dylan Raiola']) COMBINE_DATA['Dylan Raiola'] = { school: 'Oregon', pos: 'QB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Nate Sheppard']) COMBINE_DATA['Nate Sheppard'] = { school: 'Duke', pos: 'RB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Luke Hasz']) COMBINE_DATA['Luke Hasz'] = { school: 'Mississippi', pos: 'TE', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Raleek Brown']) COMBINE_DATA['Raleek Brown'] = { school: 'Texas', pos: 'RB', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Marcel Reed']) COMBINE_DATA['Marcel Reed'] = { school: 'Texas A&M', pos: 'QB', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Kaliq Lockett']) COMBINE_DATA['Kaliq Lockett'] = { school: 'Texas', pos: 'WR', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['AK Dear']) COMBINE_DATA['AK Dear'] = { school: 'Alabama', pos: 'RB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Tavien St. Clair']) COMBINE_DATA['Tavien St. Clair'] = { school: 'Ohio St.', pos: 'QB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['T.J. Moore']) COMBINE_DATA['T.J. Moore'] = { school: 'Clemson', pos: 'WR', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Gideon Davidson']) COMBINE_DATA['Gideon Davidson'] = { school: 'Clemson', pos: 'RB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Cam Cook']) COMBINE_DATA['Cam Cook'] = { school: 'West Virginia', pos: 'RB', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Bear Bachmeier']) COMBINE_DATA['Bear Bachmeier'] = { school: 'BYU', pos: 'QB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Quincy Porter']) COMBINE_DATA['Quincy Porter'] = { school: 'Notre Dame', pos: 'WR', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Josh Hoover']) COMBINE_DATA['Josh Hoover'] = { school: 'Indiana', pos: 'QB', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Joshua Moore']) COMBINE_DATA['Joshua Moore'] = { school: 'Miami (FL)', pos: 'WR', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Julian Lewis']) COMBINE_DATA['Julian Lewis'] = { school: 'Colorado', pos: 'QB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Luke Reynolds']) COMBINE_DATA['Luke Reynolds'] = { school: 'Virginia Tech', pos: 'TE', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Malik Washington']) COMBINE_DATA['Malik Washington'] = { school: 'Maryland', pos: 'QB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Brandon Inniss']) COMBINE_DATA['Brandon Inniss'] = { school: 'Ohio St.', pos: 'WR', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Jadan Baugh']) COMBINE_DATA['Jadan Baugh'] = { school: 'Florida', pos: 'RB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Cam Edwards']) COMBINE_DATA['Cam Edwards'] = { school: 'William & Mary', pos: 'WR', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Isaiah Horton']) COMBINE_DATA['Isaiah Horton'] = { school: 'Texas A&M', pos: 'WR', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['DJ Lagway']) COMBINE_DATA['DJ Lagway'] = { school: 'Baylor', pos: 'QB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Eric Singleton Jr.']) COMBINE_DATA['Eric Singleton Jr.'] = { school: 'Auburn', pos: 'WR', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Caden Durham']) COMBINE_DATA['Caden Durham'] = { school: 'LSU', pos: 'RB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Kaelan Chudzinski']) COMBINE_DATA['Kaelan Chudzinski'] = { school: 'Boston College', pos: 'TE', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Darian Mensah']) COMBINE_DATA['Darian Mensah'] = { school: 'Miami (FL)', pos: 'QB', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Husan Longstreet']) COMBINE_DATA['Husan Longstreet'] = { school: 'LSU', pos: 'QB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Deuce Knight']) COMBINE_DATA['Deuce Knight'] = { school: 'Mississippi', pos: 'QB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Caleb Cunningham']) COMBINE_DATA['Caleb Cunningham'] = { school: 'Mississippi', pos: 'WR', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['John Mateer']) COMBINE_DATA['John Mateer'] = { school: 'Oklahoma', pos: 'QB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['CJ Carr']) COMBINE_DATA['CJ Carr'] = { school: 'Notre Dame', pos: 'QB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Byrum Brown']) COMBINE_DATA['Byrum Brown'] = { school: 'Auburn', pos: 'QB', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Jordan Marshall']) COMBINE_DATA['Jordan Marshall'] = { school: 'Michigan', pos: 'RB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Danny Scudero']) COMBINE_DATA['Danny Scudero'] = { school: 'Colorado', pos: 'WR', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Talyn Taylor']) COMBINE_DATA['Talyn Taylor'] = { school: 'Georgia', pos: 'WR', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Nico Iamaleava']) COMBINE_DATA['Nico Iamaleava'] = { school: 'UCLA', pos: 'QB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Quinton Martin Jr.']) COMBINE_DATA['Quinton Martin Jr.'] = { school: 'Penn St.', pos: 'RB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Quinten Joyner']) COMBINE_DATA['Quinten Joyner'] = { school: 'USC', pos: 'RB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Linkon Cure']) COMBINE_DATA['Linkon Cure'] = { school: 'Kansas St.', pos: 'TE', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Nic Anderson']) COMBINE_DATA['Nic Anderson'] = { school: 'Kentucky', pos: 'WR', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Naeem Burroughs']) COMBINE_DATA['Naeem Burroughs'] = { school: 'Clemson', pos: 'WR', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Bryce Underwood']) COMBINE_DATA['Bryce Underwood'] = { school: 'Michigan', pos: 'QB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Jayden Maiava']) COMBINE_DATA['Jayden Maiava'] = { school: 'USC', pos: 'QB', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Andrew Marsh']) COMBINE_DATA['Andrew Marsh'] = { school: 'Michigan', pos: 'WR', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Elyiss Williams']) COMBINE_DATA['Elyiss Williams'] = { school: 'Georgia', pos: 'TE', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Dilin Jones']) COMBINE_DATA['Dilin Jones'] = { school: 'LSU', pos: 'RB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Ousmane Kromah']) COMBINE_DATA['Ousmane Kromah'] = { school: 'Florida St.', pos: 'RB', devy: true, eligYr: 2028 };
  if (!COMBINE_DATA['Kenny Johnson']) COMBINE_DATA['Kenny Johnson'] = { school: 'Texas Tech', pos: 'WR', devy: true, eligYr: 2026 };
  if (!COMBINE_DATA['Taylor Tatum']) COMBINE_DATA['Taylor Tatum'] = { school: 'Oklahoma', pos: 'RB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Jerrick Gibson']) COMBINE_DATA['Jerrick Gibson'] = { school: 'Purdue', pos: 'RB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Micah Hudson']) COMBINE_DATA['Micah Hudson'] = { school: 'Texas Tech', pos: 'WR', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Demond Williams Jr.']) COMBINE_DATA['Demond Williams Jr.'] = { school: 'Washington', pos: 'QB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Perry Thompson']) COMBINE_DATA['Perry Thompson'] = { school: 'Minnesota', pos: 'WR', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Nate Frazier']) COMBINE_DATA['Nate Frazier'] = { school: 'Georgia', pos: 'RB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Kam Davis']) COMBINE_DATA['Kam Davis'] = { school: 'Liberty', pos: 'RB', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['Joshisa Trader']) COMBINE_DATA['Joshisa Trader'] = { school: 'NC State', pos: 'WR', devy: true, eligYr: 2027 };
  if (!COMBINE_DATA['CJ Bailey']) COMBINE_DATA['CJ Bailey'] = { school: 'NC State', pos: 'QB', devy: true, eligYr: 2027 };
  // === NFLDRAFTBUZZ 2027 DATA UPDATE ===
  // --- New 2027 devy prospects ---
  if (!COMBINE_DATA['Barion Brown']) COMBINE_DATA['Barion Brown'] = { school: 'Kentucky', pos: 'WR', devy: true, eligYr: 2027, ht: '5-11', wt: 177 };
  if (!COMBINE_DATA['Braylon Staley']) COMBINE_DATA['Braylon Staley'] = { school: 'Tennessee', pos: 'WR', devy: true, eligYr: 2027, ht: '6-0', wt: 190 };
  if (!COMBINE_DATA['Corey Kiner']) COMBINE_DATA['Corey Kiner'] = { school: 'LSU', pos: 'RB', devy: true, eligYr: 2027, ht: '5-9', wt: 209 };
  if (!COMBINE_DATA['Dane Key']) COMBINE_DATA['Dane Key'] = { school: 'Kentucky', pos: 'WR', devy: true, eligYr: 2027, ht: '6-2', wt: 203 };
  if (!COMBINE_DATA['Ian Strong']) COMBINE_DATA['Ian Strong'] = { school: 'Rutgers', pos: 'WR', devy: true, eligYr: 2027, ht: '6-3', wt: 211 };
  if (!COMBINE_DATA['Johntay Cook II']) COMBINE_DATA['Johntay Cook II'] = { school: 'Texas', pos: 'WR', devy: true, eligYr: 2027, ht: '6-0', wt: 198 };
  if (!COMBINE_DATA['Mario Craver']) COMBINE_DATA['Mario Craver'] = { school: 'Mississippi St.', pos: 'WR', devy: true, eligYr: 2027, ht: '5-9', wt: 165 };
  if (!COMBINE_DATA['Mike Matthews']) COMBINE_DATA['Mike Matthews'] = { school: 'Tennessee', pos: 'WR', devy: true, eligYr: 2027, ht: '6-1', wt: 200 };
  // Moliki Matavao — already drafted by NO (Saints), not devy. Do NOT add devy COMBINE_DATA.
  // --- Measurables updates (ht/wt from NFLDraftBuzz) ---
  if (COMBINE_DATA['Arch Manning']) { COMBINE_DATA['Arch Manning'].ht='6-4'; COMBINE_DATA['Arch Manning'].wt=219; }
  if (COMBINE_DATA['Brandon Inniss']) { COMBINE_DATA['Brandon Inniss'].ht='6-0'; COMBINE_DATA['Brandon Inniss'].wt=199; }
  if (COMBINE_DATA['Bryant Wesco Jr.']) { COMBINE_DATA['Bryant Wesco Jr.'].ht='6-2'; COMBINE_DATA['Bryant Wesco Jr.'].wt=185; }
  if (COMBINE_DATA['Cam Coleman']) { COMBINE_DATA['Cam Coleman'].ht='6-3'; COMBINE_DATA['Cam Coleman'].wt=201; }
  if (COMBINE_DATA['DJ Lagway']) { COMBINE_DATA['DJ Lagway'].ht='6-3'; COMBINE_DATA['DJ Lagway'].wt=247; }
  if (COMBINE_DATA['Dante Moore']) { COMBINE_DATA['Dante Moore'].ht='6-3'; COMBINE_DATA['Dante Moore'].wt=206; }
  if (COMBINE_DATA['Dylan Raiola']) { COMBINE_DATA['Dylan Raiola'].ht='6-3'; COMBINE_DATA['Dylan Raiola'].wt=230; }
  if (COMBINE_DATA['Eugene Wilson III']) { COMBINE_DATA['Eugene Wilson III'].ht='5-10'; COMBINE_DATA['Eugene Wilson III'].wt=194; }
  if (COMBINE_DATA['Isaac Brown']) { COMBINE_DATA['Isaac Brown'].ht='5-9'; COMBINE_DATA['Isaac Brown'].wt=190; }
  if (COMBINE_DATA['Jadan Baugh']) { COMBINE_DATA['Jadan Baugh'].ht='6-1'; COMBINE_DATA['Jadan Baugh'].wt=231; }
  if (COMBINE_DATA['Jeremiah Smith']) { COMBINE_DATA['Jeremiah Smith'].ht='6-3'; COMBINE_DATA['Jeremiah Smith'].wt=223; }
  if (COMBINE_DATA['John Mateer']) { COMBINE_DATA['John Mateer'].ht='6-1'; COMBINE_DATA['John Mateer'].wt=224; }
  if (COMBINE_DATA['Jordan Marshall']) { COMBINE_DATA['Jordan Marshall'].ht='5-11'; COMBINE_DATA['Jordan Marshall'].wt=216; }
  if (COMBINE_DATA['Julian Sayin']) { COMBINE_DATA['Julian Sayin'].ht='6-1'; COMBINE_DATA['Julian Sayin'].wt=208; }
  if (COMBINE_DATA['Justice Haynes']) { COMBINE_DATA['Justice Haynes'].ht='5-11'; COMBINE_DATA['Justice Haynes'].wt=210; }
  if (COMBINE_DATA['Kewan Lacy']) { COMBINE_DATA['Kewan Lacy'].ht='5-11'; COMBINE_DATA['Kewan Lacy'].wt=200; }
  if (COMBINE_DATA['LaNorris Sellers']) { COMBINE_DATA['LaNorris Sellers'].ht='6-3'; COMBINE_DATA['LaNorris Sellers'].wt=240; }
  if (COMBINE_DATA['Luke Reynolds']) { COMBINE_DATA['Luke Reynolds'].ht='6-4'; COMBINE_DATA['Luke Reynolds'].wt=250; }
  if (COMBINE_DATA['Nate Frazier']) { COMBINE_DATA['Nate Frazier'].ht='5-10'; COMBINE_DATA['Nate Frazier'].wt=210; }
  if (COMBINE_DATA['Nic Anderson']) { COMBINE_DATA['Nic Anderson'].ht='6-4'; COMBINE_DATA['Nic Anderson'].wt=208; }
  if (COMBINE_DATA['Nick Marsh']) { COMBINE_DATA['Nick Marsh'].ht='6-3'; COMBINE_DATA['Nick Marsh'].wt=203; }
  if (COMBINE_DATA['Nico Iamaleava']) { COMBINE_DATA['Nico Iamaleava'].ht='6-6'; COMBINE_DATA['Nico Iamaleava'].wt=215; }
  if (COMBINE_DATA['Nyck Harbor']) { COMBINE_DATA['Nyck Harbor'].ht='6-5'; COMBINE_DATA['Nyck Harbor'].wt=235; }
  if (COMBINE_DATA['Ryan Williams']) { COMBINE_DATA['Ryan Williams'].ht='6-0'; COMBINE_DATA['Ryan Williams'].wt=175; }
  if (COMBINE_DATA['Ryan Wingo']) { COMBINE_DATA['Ryan Wingo'].ht='6-2'; COMBINE_DATA['Ryan Wingo'].wt=214; }
  if (COMBINE_DATA['Sam Leavitt']) { COMBINE_DATA['Sam Leavitt'].ht='6-2'; COMBINE_DATA['Sam Leavitt'].wt=205; }
  if (COMBINE_DATA['T.J. Moore']) { COMBINE_DATA['T.J. Moore'].ht='6-3'; COMBINE_DATA['T.J. Moore'].wt=200; }
  if (COMBINE_DATA["Trey'Dez Green"]) { COMBINE_DATA["Trey'Dez Green"].ht='6-7'; COMBINE_DATA["Trey'Dez Green"].wt=240; }
  // --- Projected draft capital (NFLDraftBuzz projections → overall pick estimates) ---
  if (COMBINE_DATA['Jeremiah Smith']) COMBINE_DATA['Jeremiah Smith'].draft = 3;
  if (COMBINE_DATA['Julian Sayin']) COMBINE_DATA['Julian Sayin'].draft = 3;
  if (COMBINE_DATA['Dante Moore']) COMBINE_DATA['Dante Moore'].draft = 3;
  if (COMBINE_DATA['Arch Manning']) COMBINE_DATA['Arch Manning'].draft = 7;
  if (COMBINE_DATA['Nate Frazier']) COMBINE_DATA['Nate Frazier'].draft = 7;
  if (COMBINE_DATA['Bryant Wesco Jr.']) COMBINE_DATA['Bryant Wesco Jr.'].draft = 16;
  if (COMBINE_DATA['Cam Coleman']) COMBINE_DATA['Cam Coleman'].draft = 16;
  if (COMBINE_DATA['Ryan Williams']) COMBINE_DATA['Ryan Williams'].draft = 16;
  if (COMBINE_DATA['T.J. Moore']) COMBINE_DATA['T.J. Moore'].draft = 16;
  if (COMBINE_DATA['Mario Craver']) COMBINE_DATA['Mario Craver'].draft = 28;
  if (COMBINE_DATA['Ryan Wingo']) COMBINE_DATA['Ryan Wingo'].draft = 36;
  if (COMBINE_DATA['Mike Matthews']) COMBINE_DATA['Mike Matthews'].draft = 36;
  if (COMBINE_DATA['Kewan Lacy']) COMBINE_DATA['Kewan Lacy'].draft = 48;
  if (COMBINE_DATA['Isaac Brown']) COMBINE_DATA['Isaac Brown'].draft = 58;
  if (COMBINE_DATA['Braylon Staley']) COMBINE_DATA['Braylon Staley'].draft = 58;
  if (COMBINE_DATA['LaNorris Sellers']) COMBINE_DATA['LaNorris Sellers'].draft = 58;
  if (COMBINE_DATA['Ian Strong']) COMBINE_DATA['Ian Strong'].draft = 80;
  if (COMBINE_DATA['Jadan Baugh']) COMBINE_DATA['Jadan Baugh'].draft = 80;
  if (COMBINE_DATA['John Mateer']) COMBINE_DATA['John Mateer'].draft = 80;
  if (COMBINE_DATA['Jordan Marshall']) COMBINE_DATA['Jordan Marshall'].draft = 80;
  if (COMBINE_DATA['Nick Marsh']) COMBINE_DATA['Nick Marsh'].draft = 80;
  if (COMBINE_DATA['Sam Leavitt']) COMBINE_DATA['Sam Leavitt'].draft = 80;
  if (COMBINE_DATA["Trey'Dez Green"]) COMBINE_DATA["Trey'Dez Green"].draft = 80;
  if (COMBINE_DATA['Eugene Wilson III']) COMBINE_DATA['Eugene Wilson III'].draft = 112;
  if (COMBINE_DATA['Justice Haynes']) COMBINE_DATA['Justice Haynes'].draft = 112;
  if (COMBINE_DATA['Nyck Harbor']) COMBINE_DATA['Nyck Harbor'].draft = 112;
  if (COMBINE_DATA['DJ Lagway']) COMBINE_DATA['DJ Lagway'].draft = 144;
  if (COMBINE_DATA['Dylan Raiola']) COMBINE_DATA['Dylan Raiola'].draft = 144;
  if (COMBINE_DATA['Luke Reynolds']) COMBINE_DATA['Luke Reynolds'].draft = 144;
  if (COMBINE_DATA['Nic Anderson']) COMBINE_DATA['Nic Anderson'].draft = 144;
  if (COMBINE_DATA['Nico Iamaleava']) COMBINE_DATA['Nico Iamaleava'].draft = 144;
  if (COMBINE_DATA['Brandon Inniss']) COMBINE_DATA['Brandon Inniss'].draft = 176;
  if (COMBINE_DATA['Corey Kiner']) COMBINE_DATA['Corey Kiner'].draft = 208;
  if (COMBINE_DATA['Dane Key']) COMBINE_DATA['Dane Key'].draft = 208;
  if (COMBINE_DATA['Johntay Cook II']) COMBINE_DATA['Johntay Cook II'].draft = 208;
  if (COMBINE_DATA['Barion Brown']) COMBINE_DATA['Barion Brown'].draft = 'U';
  // Moliki Matavao — in NFL, no draft projection needed
  // --- Projected forty times (NFLDraftBuzz, 44 players) ---
  // These set baseline values. Admin edits via bio editor persist to Firestore
  // and will override these on page load (prospect_bio collection loads after this).
  if (COMBINE_DATA['Jeremiah Smith']) COMBINE_DATA['Jeremiah Smith'].forty = 4.32;
  if (COMBINE_DATA['Cam Coleman']) COMBINE_DATA['Cam Coleman'].forty = 4.42;
  if (COMBINE_DATA['Ryan Williams']) COMBINE_DATA['Ryan Williams'].forty = 4.28;
  if (COMBINE_DATA['Ryan Wingo']) COMBINE_DATA['Ryan Wingo'].forty = 4.36;
  if (COMBINE_DATA['Bryant Wesco Jr.']) COMBINE_DATA['Bryant Wesco Jr.'].forty = 4.40;
  if (COMBINE_DATA['Nick Marsh']) COMBINE_DATA['Nick Marsh'].forty = 4.38;
  if (COMBINE_DATA['Brandon Inniss']) COMBINE_DATA['Brandon Inniss'].forty = 4.38;
  if (COMBINE_DATA['Eugene Wilson III']) COMBINE_DATA['Eugene Wilson III'].forty = 4.43;
  if (COMBINE_DATA['Nyck Harbor']) COMBINE_DATA['Nyck Harbor'].forty = 4.24;
  if (COMBINE_DATA['T.J. Moore']) COMBINE_DATA['T.J. Moore'].forty = 4.42;
  if (COMBINE_DATA['Eric Singleton Jr.']) COMBINE_DATA['Eric Singleton Jr.'].forty = 4.34;
  if (COMBINE_DATA['Nic Anderson']) COMBINE_DATA['Nic Anderson'].forty = 4.52;
  if (COMBINE_DATA['Barion Brown']) COMBINE_DATA['Barion Brown'].forty = 4.40;
  if (COMBINE_DATA['Dane Key']) COMBINE_DATA['Dane Key'].forty = 4.60;
  if (COMBINE_DATA['Mario Craver']) COMBINE_DATA['Mario Craver'].forty = 4.25;
  if (COMBINE_DATA['Braylon Staley']) COMBINE_DATA['Braylon Staley'].forty = 4.34;
  if (COMBINE_DATA['Mike Matthews']) COMBINE_DATA['Mike Matthews'].forty = 4.41;
  if (COMBINE_DATA['Ian Strong']) COMBINE_DATA['Ian Strong'].forty = 4.60;
  if (COMBINE_DATA['Johntay Cook II']) COMBINE_DATA['Johntay Cook II'].forty = 4.40;
  if (COMBINE_DATA['Julian Sayin']) COMBINE_DATA['Julian Sayin'].forty = 4.70;
  if (COMBINE_DATA['Dante Moore']) COMBINE_DATA['Dante Moore'].forty = 4.90;
  if (COMBINE_DATA['Arch Manning']) COMBINE_DATA['Arch Manning'].forty = 4.62;
  if (COMBINE_DATA['Nico Iamaleava']) COMBINE_DATA['Nico Iamaleava'].forty = 4.75;
  if (COMBINE_DATA['LaNorris Sellers']) COMBINE_DATA['LaNorris Sellers'].forty = 4.55;
  if (COMBINE_DATA['John Mateer']) COMBINE_DATA['John Mateer'].forty = 4.65;
  if (COMBINE_DATA['Sam Leavitt']) COMBINE_DATA['Sam Leavitt'].forty = 4.65;
  if (COMBINE_DATA['DJ Lagway']) COMBINE_DATA['DJ Lagway'].forty = 4.65;
  if (COMBINE_DATA['Dylan Raiola']) COMBINE_DATA['Dylan Raiola'].forty = 4.80;
  if (COMBINE_DATA['Josh Hoover']) COMBINE_DATA['Josh Hoover'].forty = 4.90;
  if (COMBINE_DATA['Darian Mensah']) COMBINE_DATA['Darian Mensah'].forty = 4.75;
  if (COMBINE_DATA['CJ Carr']) COMBINE_DATA['CJ Carr'].forty = 4.70;
  if (COMBINE_DATA['Nate Frazier']) COMBINE_DATA['Nate Frazier'].forty = 4.35;
  if (COMBINE_DATA['Justice Haynes']) COMBINE_DATA['Justice Haynes'].forty = 4.49;
  if (COMBINE_DATA['Isaac Brown']) COMBINE_DATA['Isaac Brown'].forty = 4.48;
  if (COMBINE_DATA['Kewan Lacy']) COMBINE_DATA['Kewan Lacy'].forty = 4.48;
  if (COMBINE_DATA['Jordan Marshall']) COMBINE_DATA['Jordan Marshall'].forty = 4.42;
  if (COMBINE_DATA['Jadan Baugh']) COMBINE_DATA['Jadan Baugh'].forty = 4.46;
  if (COMBINE_DATA['Quinten Joyner']) COMBINE_DATA['Quinten Joyner'].forty = 4.47;
  if (COMBINE_DATA['Corey Kiner']) COMBINE_DATA['Corey Kiner'].forty = 4.57;
  if (COMBINE_DATA['Raleek Brown']) COMBINE_DATA['Raleek Brown'].forty = 4.32;
  if (COMBINE_DATA['LJ Martin']) COMBINE_DATA['LJ Martin'].forty = 4.46;
  if (COMBINE_DATA["Trey'Dez Green"]) COMBINE_DATA["Trey'Dez Green"].forty = 4.65;
  if (COMBINE_DATA['Luke Reynolds']) COMBINE_DATA['Luke Reynolds'].forty = 4.50;
  if (COMBINE_DATA['Luke Hasz']) COMBINE_DATA['Luke Hasz'].forty = 4.68;
  // === END NFLDRAFTBUZZ UPDATE ===
  if (!COMBINE_DATA['Keelon Russell']) COMBINE_DATA['Keelon Russell'] = { school: 'Alabama', pos: 'QB', devy: true, eligYr: 2028 };

  // === DEVY DRAFT YEAR CLEANUP ===
  // combine_data.js may have stale data for devy players (missing devy flag, wrong yr).
  // Force devy:true, eligYr, and yr on ALL known devy players regardless of combine_data.js values.
  (function() {
    var cb;
    cb=COMBINE_DATA['Jeremiah Smith']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Malachi Toney']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['Cam Coleman']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Ryan Williams']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Bryant Wesco Jr.']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Bo Jackson']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['Kewan Lacy']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Justice Haynes']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Hollywood Smothers']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['Dante Moore']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Arch Manning']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Isaac Brown']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Mark Fletcher Jr.']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['Jordon Davison']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['Ryan Wingo']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['LJ Martin']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['Eugene Wilson III']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['LaNorris Sellers']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Ahmad Hardy']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Dallas Wilson']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['Jayce Brown']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['Dakorien Moore']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA["Trey'Dez Green"]; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Nick Marsh']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Brandon Inniss']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Brendan Sorsby']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['Terrance Carter Jr.']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['Micah Hudson']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Quinten Joyner']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Jerrick Gibson']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Bryce Underwood']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['Isaiah Sategna III']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['Caden Durham']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Nate Frazier']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Luke Hasz']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['Raleek Brown']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['Marcel Reed']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['Julian Sayin']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Dylan Raiola']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Cam Cook']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['Nico Iamaleava']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Josh Hoover']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['Byrum Brown']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['DJ Lagway']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['John Mateer']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['CJ Bailey']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Demond Williams Jr.']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Isaiah Horton']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['Caleb Cunningham']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['Eric Singleton Jr.']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['Deuce Knight']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['Darian Mensah']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['CJ Carr']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['Julian Lewis']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['Tavien St. Clair']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Keelon Russell']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['T.J. Moore']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Quincy Porter']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['Kaliq Lockett']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['Andrew Marsh']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['Talyn Taylor']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['Jordan Marshall']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Taylor Tatum']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Jadan Baugh']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Dierre Hill Jr.']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Harlem Berry']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['Nate Sheppard']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['Caleb Hawkins']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Ousmane Kromah']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Gideon Davidson']; if(cb){cb.devy=true;cb.eligYr=2028;cb.yr=2028;}
    cb=COMBINE_DATA['Sam Leavitt']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['Jayden Maiava']; if(cb){cb.devy=true;cb.eligYr=2026;cb.yr=2026;}
    cb=COMBINE_DATA['Braylon Staley']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Ian Strong']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Johntay Cook II']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Mario Craver']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
    cb=COMBINE_DATA['Mike Matthews']; if(cb){cb.devy=true;cb.eligYr=2027;cb.yr=2027;}
  })();

  // === NAME COLLISION FIXES: Veterans appearing in wrong draft class ===
  // Deebo Samuel was drafted in 2019 — combine_data.js may have wrong yr
  if (COMBINE_DATA['Deebo Samuel']) COMBINE_DATA['Deebo Samuel'].yr = 2019;

  // === 2026 DRAFT CLASS ADDITIONS ===
  if (!COMBINE_DATA['KC Concepcion']) COMBINE_DATA['KC Concepcion'] = { school: 'Texas A&M', pos: 'WR', yr: 2026 };
  if (COMBINE_DATA['KC Concepcion'] && !COMBINE_DATA['KC Concepcion'].pos) COMBINE_DATA['KC Concepcion'].pos = 'WR';
  if (!COMBINE_DATA['Jaydn Ott']) COMBINE_DATA['Jaydn Ott'] = { school: 'Oklahoma', pos: 'RB', yr: 2026 };
  if (COMBINE_DATA['Jaydn Ott']) COMBINE_DATA['Jaydn Ott'].school = 'Oklahoma';
  if (COMBINE_DATA['Jaydn Ott'] && !COMBINE_DATA['Jaydn Ott'].pos) COMBINE_DATA['Jaydn Ott'].pos = 'RB';
  if (!COMBINE_DATA["Ja'Kobi Lane"]) COMBINE_DATA["Ja'Kobi Lane"] = { school: 'USC', pos: 'WR', yr: 2026, ht: '6-1', wt: 200 };
  if (!COMBINE_DATA['Mike Washington Jr.']) COMBINE_DATA['Mike Washington Jr.'] = { school: 'Arkansas', pos: 'RB', yr: 2026 };
  if (COMBINE_DATA['Mike Washington Jr.'] && !COMBINE_DATA['Mike Washington Jr.'].pos) COMBINE_DATA['Mike Washington Jr.'].pos = 'RB';
  COMBINE_DATA['Justin Joly'] = Object.assign({ school: 'NC State', pos: 'TE', yr: 2026, ht: '6-4', wt: 241 }, COMBINE_DATA['Justin Joly']);
  if (!COMBINE_DATA['John Michael Gyllenborg']) COMBINE_DATA['John Michael Gyllenborg'] = { school: 'Wyoming', pos: 'WR', yr: 2026 };
  if (COMBINE_DATA['John Michael Gyllenborg'] && !COMBINE_DATA['John Michael Gyllenborg'].pos) COMBINE_DATA['John Michael Gyllenborg'].pos = 'WR';
  if (!COMBINE_DATA['Jam Miller']) COMBINE_DATA['Jam Miller'] = { school: 'Alabama', pos: 'RB', yr: 2026 };
  if (COMBINE_DATA['Jam Miller'] && !COMBINE_DATA['Jam Miller'].pos) COMBINE_DATA['Jam Miller'].pos = 'RB';
  // Harold Fannin Jr. — TE, not WR. Fix pos in both name variants.
  if (COMBINE_DATA['Harold Fannin']) COMBINE_DATA['Harold Fannin'].pos = 'TE';
  if (COMBINE_DATA['Harold Fannin Jr.']) COMBINE_DATA['Harold Fannin Jr.'].pos = 'TE';
  if (!COMBINE_DATA['Gunner Gray']) COMBINE_DATA['Gunner Gray'] = { school: 'Buffalo', pos: 'QB', yr: 2026, ht: '6-2', wt: 215 };
  // 2026 class — defaults that fill in missing fields without nuking what
  // data/combine_data.js already provides (draft, dt, ras, etc.). The inline
  // version is a fallback only — anything already in combine_data.js wins.
  COMBINE_DATA['Chris Bell'] = Object.assign({ school: 'Louisville', pos: 'WR', yr: 2026, ht: '6-2', wt: 220 }, COMBINE_DATA['Chris Bell']);
  COMBINE_DATA['Antonio Williams'] = Object.assign({ school: 'Clemson', pos: 'WR', yr: 2026, ht: '5-11', wt: 187, forty: 4.41 }, COMBINE_DATA['Antonio Williams']);
  COMBINE_DATA["De'Zhaun Stribling"] = Object.assign({ school: 'Ole Miss', pos: 'WR', yr: 2026 }, COMBINE_DATA["De'Zhaun Stribling"]);
  COMBINE_DATA['Carson Beck'] = Object.assign({ school: 'Miami', pos: 'QB', yr: 2026, ht: '6-4', wt: 220 }, COMBINE_DATA['Carson Beck']);
  COMBINE_DATA['CJ Daniels'] = Object.assign({ school: 'Miami', pos: 'WR', yr: 2026, ht: '6-2', wt: 202 }, COMBINE_DATA['CJ Daniels']);
  COMBINE_DATA['Seth McGowan'] = Object.assign({ school: 'Kentucky', pos: 'RB', yr: 2026, ht: '5-11', wt: 215 }, COMBINE_DATA['Seth McGowan']);
  COMBINE_DATA['Reggie Virgil'] = Object.assign({ school: 'Texas Tech', pos: 'WR', yr: 2026 }, COMBINE_DATA['Reggie Virgil']);
  COMBINE_DATA['Jack Endries'] = Object.assign({ school: 'Texas', pos: 'TE', yr: 2026, ht: '6-4', wt: 245, forty: 4.62 }, COMBINE_DATA['Jack Endries']);
  COMBINE_DATA['Max Klare'] = Object.assign({ school: 'Ohio State', pos: 'TE', yr: 2026, ht: '6-4', wt: 246 }, COMBINE_DATA['Max Klare']);
  // --- 2026 class additions from PROSPECTS-rankings.csv ---
  if (!COMBINE_DATA['Jeremiyah Love']) COMBINE_DATA['Jeremiyah Love'] = { school: 'Notre Dame', pos: 'RB', ht: '6-0', wt: 214, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Makai Lemon']) COMBINE_DATA['Makai Lemon'] = { school: 'USC', pos: 'WR', ht: '5-11', wt: 195, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Carnell Tate']) COMBINE_DATA['Carnell Tate'] = { school: 'Ohio State', pos: 'WR', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Jordyn Tyson']) COMBINE_DATA['Jordyn Tyson'] = { school: 'Arizona State', pos: 'WR', ht: '6-2', wt: 200, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Kenyon Sadiq']) COMBINE_DATA['Kenyon Sadiq'] = { school: 'Oregon', pos: 'TE', ht: '6-3', wt: 245, devy: true, eligYr: 2026, yr: 2026 };
  // Omar Cooper Jr. lives under "Omar Cooper Jr." in data/combine_data.js with full combine (forty:4.42, ras:8.85, draftProj:25). Removed no-suffix stub (was shadowing).
  if (!COMBINE_DATA['Jadarian Price']) COMBINE_DATA['Jadarian Price'] = { school: 'Notre Dame', pos: 'RB', ht: '5-11', wt: 209, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Denzel Boston']) COMBINE_DATA['Denzel Boston'] = { school: 'Washington', pos: 'WR', ht: '6-4', wt: 209, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Jonah Coleman']) COMBINE_DATA['Jonah Coleman'] = { school: 'Arizona', pos: 'RB', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Fernando Mendoza']) COMBINE_DATA['Fernando Mendoza'] = { school: 'California', pos: 'QB', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Eli Stowers']) COMBINE_DATA['Eli Stowers'] = { school: 'New Mexico State', pos: 'TE', devy: true, eligYr: 2026, yr: 2026 };
  // [REMOVED] 'Chris Brazzell' duplicate — the canonical record is 'Chris Brazzell II' (has CS, weekly, school=Tennessee).
  if (!COMBINE_DATA['Kaytron Allen']) COMBINE_DATA['Kaytron Allen'] = { school: 'Penn State', pos: 'RB', ht: '5-11', wt: 217, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Germie Bernard']) COMBINE_DATA['Germie Bernard'] = { school: 'Alabama', pos: 'WR', ht: '6-1', wt: 204, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Emmett Johnson']) COMBINE_DATA['Emmett Johnson'] = { school: 'Nebraska', pos: 'RB', ht: '5-11', wt: 200, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Zachariah Branch']) COMBINE_DATA['Zachariah Branch'] = { school: 'Georgia', pos: 'WR', ht: '5-10', wt: 180, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Ted Hurst']) COMBINE_DATA['Ted Hurst'] = { school: 'Georgia State', pos: 'WR', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Nicholas Singleton']) COMBINE_DATA['Nicholas Singleton'] = { school: 'Penn State', pos: 'RB', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Skyler Bell']) COMBINE_DATA['Skyler Bell'] = { school: 'UConn', pos: 'WR', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Ty Simpson']) COMBINE_DATA['Ty Simpson'] = { school: 'Alabama', pos: 'QB', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Bryce Lance']) COMBINE_DATA['Bryce Lance'] = { school: 'North Dakota State', pos: 'WR', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Eric McAlister']) COMBINE_DATA['Eric McAlister'] = { school: 'Boise State', pos: 'WR', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Demond Claiborne']) COMBINE_DATA['Demond Claiborne'] = { school: 'Wake Forest', pos: 'RB', ht: '5-10', wt: 195, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Dean Connors']) COMBINE_DATA['Dean Connors'] = { school: 'Houston', pos: 'RB', ht: '6-0', wt: 206, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Oscar Delp']) COMBINE_DATA['Oscar Delp'] = { school: 'Georgia', pos: 'TE', ht: '6-5', wt: 245, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Eli Raridon']) COMBINE_DATA['Eli Raridon'] = { school: 'Notre Dame', pos: 'TE', ht: '6-7', wt: 251, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA["Le'Veon Moss"]) COMBINE_DATA["Le'Veon Moss"] = { school: 'Texas A&M', pos: 'RB', ht: '5-11', wt: 210, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Michael Trigg']) COMBINE_DATA['Michael Trigg'] = { school: 'Baylor', pos: 'TE', ht: '6-4', wt: 240, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA["J'Mari Taylor"]) COMBINE_DATA["J'Mari Taylor"] = { school: 'North Carolina Central', pos: 'RB', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Malachi Fields']) COMBINE_DATA['Malachi Fields'] = { school: 'Notre Dame', pos: 'WR', ht: '6-4', wt: 223, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Eli Heidenreich']) COMBINE_DATA['Eli Heidenreich'] = { school: 'Navy', pos: 'WR', ht: '6-0', wt: 206, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Adam Randall']) COMBINE_DATA['Adam Randall'] = { school: 'Clemson', pos: 'RB', ht: '6-2', wt: 230, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Deion Burks']) COMBINE_DATA['Deion Burks'] = { school: 'Oklahoma', pos: 'WR', ht: '5-9', wt: 188, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Drew Allar']) COMBINE_DATA['Drew Allar'] = { school: 'Penn State', pos: 'QB', ht: '6-5', wt: 235, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Desmond Reid']) COMBINE_DATA['Desmond Reid'] = { school: 'Pittsburgh', pos: 'RB', ht: '5-8', wt: 175, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Brenen Thompson']) COMBINE_DATA['Brenen Thompson'] = { school: 'Mississippi State', pos: 'WR', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Kaelon Black']) COMBINE_DATA['Kaelon Black'] = { school: 'Indiana', pos: 'RB', ht: '5-10', wt: 210, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Garrett Nussmeier']) COMBINE_DATA['Garrett Nussmeier'] = { school: 'LSU', pos: 'QB', ht: '6-1', wt: 205, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Zavion Thomas']) COMBINE_DATA['Zavion Thomas'] = { school: 'LSU', pos: 'WR', ht: '5-10', wt: 192, devy: true, eligYr: 2026, yr: 2026 };
  // [REMOVED] 'Kevin Coleman' duplicate — the canonical record is 'Kevin Coleman Jr.' (has CS, weekly, school=Jackson State).
  if (!COMBINE_DATA['Amare Thomas']) COMBINE_DATA['Amare Thomas'] = { school: 'Houston', pos: 'WR', ht: '6-0', wt: 205, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Cole Payton']) COMBINE_DATA['Cole Payton'] = { school: 'North Dakota State', pos: 'QB', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Jeff Caldwell']) COMBINE_DATA['Jeff Caldwell'] = { school: 'Cincinnati', pos: 'WR', ht: '6-5', wt: 215, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Terion Stewart']) COMBINE_DATA['Terion Stewart'] = { school: 'Bowling Green', pos: 'RB', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Sam Roush']) COMBINE_DATA['Sam Roush'] = { school: 'Stanford', pos: 'TE', ht: '6-5', wt: 260, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Cade Klubnik']) COMBINE_DATA['Cade Klubnik'] = { school: 'Clemson', pos: 'QB', ht: '6-2', wt: 210, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Taylen Green']) COMBINE_DATA['Taylen Green'] = { school: 'Arkansas', pos: 'QB', ht: '6-6', wt: 224, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Diego Pavia']) COMBINE_DATA['Diego Pavia'] = { school: 'New Mexico State', pos: 'QB', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Josh Cameron']) COMBINE_DATA['Josh Cameron'] = { school: 'Baylor', pos: 'WR', ht: '6-1', wt: 224, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Robert Henry Jr.']) COMBINE_DATA['Robert Henry Jr.'] = { pos: 'RB', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Aaron Anderson']) COMBINE_DATA['Aaron Anderson'] = { school: 'Alabama', pos: 'WR', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Malik Benson']) COMBINE_DATA['Malik Benson'] = { school: 'Alabama', pos: 'WR', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Eric Rivers']) COMBINE_DATA['Eric Rivers'] = { school: 'Kansas', pos: 'WR', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Chase Roberts']) COMBINE_DATA['Chase Roberts'] = { school: 'Georgia Tech', pos: 'WR', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Lewis Bond']) COMBINE_DATA['Lewis Bond'] = { school: 'Boston College', pos: 'WR', ht: '5-11', wt: 190, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Tanner Koziol']) COMBINE_DATA['Tanner Koziol'] = { school: 'Ball State', pos: 'TE', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Caleb Douglas']) COMBINE_DATA['Caleb Douglas'] = { school: 'Florida', pos: 'WR', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Jordan Hudson']) COMBINE_DATA['Jordan Hudson'] = { school: 'SMU', pos: 'WR', ht: '6-1', wt: 200, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Rahsul Faison']) COMBINE_DATA['Rahsul Faison'] = { school: 'South Carolina', pos: 'RB', ht: '6-0', wt: 218, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Noah Whittington']) COMBINE_DATA['Noah Whittington'] = { school: 'Oregon', pos: 'RB', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Jamal Haynes']) COMBINE_DATA['Jamal Haynes'] = { school: 'Georgia Tech', pos: 'RB', ht: '5-9', wt: 190, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Colbie Young']) COMBINE_DATA['Colbie Young'] = { school: 'Georgia', pos: 'WR', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Marlin Klein']) COMBINE_DATA['Marlin Klein'] = { school: 'Michigan', pos: 'TE', ht: '6-6', wt: 250, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Jalon Daniels']) COMBINE_DATA['Jalon Daniels'] = { school: 'Kansas', pos: 'QB', ht: '6-0', wt: 220, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Jalen Walthall']) COMBINE_DATA['Jalen Walthall'] = { school: "Hawai'i", pos: 'WR', devy: true, eligYr: 2026, yr: 2026 };
  // [REMOVED] 'Emmanuel Henderson' duplicate — the canonical record is 'Emmanuel Henderson Jr' (has CS, weekly, school=Kansas after transfer).
  if (!COMBINE_DATA['Caullin Lacy']) COMBINE_DATA['Caullin Lacy'] = { school: 'Louisville', pos: 'WR', ht: '5-10', wt: 190, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['CJ Donaldson']) COMBINE_DATA['CJ Donaldson'] = { school: 'Ohio State', pos: 'RB', ht: '6-2', wt: 232, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Kentrel Bullock']) COMBINE_DATA['Kentrel Bullock'] = { school: 'Ole Miss', pos: 'RB', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Chip Trayanum']) COMBINE_DATA['Chip Trayanum'] = { pos: 'RB', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Dallen Bentley']) COMBINE_DATA['Dallen Bentley'] = { school: 'Utah', pos: 'TE', ht: '6-4', wt: 264, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Joe Royer']) COMBINE_DATA['Joe Royer'] = { school: 'Cincinnati', pos: 'TE', ht: '6-5', wt: 250, devy: true, eligYr: 2026, yr: 2026 };
  // [REMOVED] "Dae'quan Wright" duplicate (lowercase q) — canonical is "Dae'Quan Wright" (has CS, weekly, school=Ole Miss).
  if (!COMBINE_DATA['Josh Cuevas']) COMBINE_DATA['Josh Cuevas'] = { school: 'Alabama', pos: 'TE', ht: '6-3', wt: 256, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['RJ Maryland']) COMBINE_DATA['RJ Maryland'] = { pos: 'TE', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Lake McRee']) COMBINE_DATA['Lake McRee'] = { school: 'USC', pos: 'TE', ht: '6-4', wt: 250, devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['J. Michael Sturdivant']) COMBINE_DATA['J. Michael Sturdivant'] = { pos: 'WR', devy: true, eligYr: 2026, yr: 2026 };
  if (!COMBINE_DATA['Kendrick Law']) COMBINE_DATA['Kendrick Law'] = { school: 'Alabama', pos: 'WR', devy: true, eligYr: 2026, yr: 2026 };
  // NOTE: COLLEGE_STATS patches moved BELOW, after college_stats.js loads (see post line ~4563)
  // Travis Hunter college stats also set after college_stats.js loads
  COMBINE_DATA['Elijah Moore'] = { yr: 2021, school: 'Mississippi', pos: 'WR', ht: '5-10', wt: 178, draft: 34, dt: 'NYJ', forty: 4.35, bench: null, vert: 36.5, broad: 126, cone: 6.61, shuttle: 4.09 };
  if (COMBINE_DATA['Kenneth Gainwell']) { if (!COMBINE_DATA['Kenneth Gainwell'].ht) COMBINE_DATA['Kenneth Gainwell'].ht = '5-9'; if (!COMBINE_DATA['Kenneth Gainwell'].wt) COMBINE_DATA['Kenneth Gainwell'].wt = 201; }
  if (COMBINE_DATA['Larry Rountree']) { if (!COMBINE_DATA['Larry Rountree'].ht) COMBINE_DATA['Larry Rountree'].ht = '5-10'; if (!COMBINE_DATA['Larry Rountree'].wt) COMBINE_DATA['Larry Rountree'].wt = 211; }
  if (COMBINE_DATA['Dax Milne']) { if (!COMBINE_DATA['Dax Milne'].ht) COMBINE_DATA['Dax Milne'].ht = '6-1'; if (!COMBINE_DATA['Dax Milne'].wt) COMBINE_DATA['Dax Milne'].wt = 190; }
  if (!COMBINE_DATA['Tyler Huntley']) COMBINE_DATA['Tyler Huntley'] = { yr: 2020, school: 'Utah', pos: 'QB', ht: '6-1', wt: 196, draft: 'U' };
  if (!COMBINE_DATA['P.J. Walker']) COMBINE_DATA['P.J. Walker'] = { yr: 2017, school: 'Temple', pos: 'QB', ht: '5-11', wt: 196, draft: 'U' };
  if (!COMBINE_DATA['Tommy DeVito']) COMBINE_DATA['Tommy DeVito'] = { yr: 2024, school: 'Illinois', pos: 'QB', ht: '6-0', wt: 210, draft: 'U' };
  if (!COMBINE_DATA['Bryce Perkins']) COMBINE_DATA['Bryce Perkins'] = { yr: 2020, school: 'Virginia', pos: 'QB', ht: '6-3', wt: 210, draft: 'U' };
  // Merge Brian Thomas Jr. RAS into Brian Thomas entry
  if (COMBINE_DATA['Brian Thomas'] && COMBINE_DATA['Brian Thomas Jr.']) {
    if (!COMBINE_DATA['Brian Thomas'].ras && COMBINE_DATA['Brian Thomas Jr.'].ras) {
      COMBINE_DATA['Brian Thomas'].ras = COMBINE_DATA['Brian Thomas Jr.'].ras;
    }
  }

  // === DEVY BIO DATA (height/weight from ESPN college rosters) ===
  if (COMBINE_DATA['AK Dear']) { COMBINE_DATA['AK Dear'].ht='6-1'; COMBINE_DATA['AK Dear'].wt=212; }
  if (COMBINE_DATA['Ahmad Hardy']) { COMBINE_DATA['Ahmad Hardy'].ht='5-10'; COMBINE_DATA['Ahmad Hardy'].wt=206; }
  if (COMBINE_DATA['Andrew Marsh']) { COMBINE_DATA['Andrew Marsh'].ht='6-0'; COMBINE_DATA['Andrew Marsh'].wt=190; }
  if (COMBINE_DATA['Arch Manning']) { COMBINE_DATA['Arch Manning'].ht='6-4'; COMBINE_DATA['Arch Manning'].wt=219; }
  if (COMBINE_DATA['Bear Bachmeier']) { COMBINE_DATA['Bear Bachmeier'].ht='6-2'; COMBINE_DATA['Bear Bachmeier'].wt=220; }
  if (COMBINE_DATA['Bo Jackson']) { COMBINE_DATA['Bo Jackson'].ht='6-0'; COMBINE_DATA['Bo Jackson'].wt=217; }
  if (COMBINE_DATA['Brandon Inniss']) { COMBINE_DATA['Brandon Inniss'].ht='6-0'; COMBINE_DATA['Brandon Inniss'].wt=199; }
  if (COMBINE_DATA['CJ Bailey']) { COMBINE_DATA['CJ Bailey'].ht='6-6'; COMBINE_DATA['CJ Bailey'].wt=210; }
  if (COMBINE_DATA['CJ Carr']) { COMBINE_DATA['CJ Carr'].ht='6-3'; COMBINE_DATA['CJ Carr'].wt=210; }
  if (COMBINE_DATA['Caden Durham']) { COMBINE_DATA['Caden Durham'].ht='5-9'; COMBINE_DATA['Caden Durham'].wt=205; }
  if (COMBINE_DATA['Caleb Cunningham']) { COMBINE_DATA['Caleb Cunningham'].ht='6-3'; COMBINE_DATA['Caleb Cunningham'].wt=190; }
  if (COMBINE_DATA['Dakorien Moore']) { COMBINE_DATA['Dakorien Moore'].ht='5-11'; COMBINE_DATA['Dakorien Moore'].wt=195; }
  if (COMBINE_DATA['Dante Moore']) { COMBINE_DATA['Dante Moore'].ht='6-3'; COMBINE_DATA['Dante Moore'].wt=206; }
  if (COMBINE_DATA['Dierre Hill Jr.']) { COMBINE_DATA['Dierre Hill Jr.'].ht='5-11'; COMBINE_DATA['Dierre Hill Jr.'].wt=205; }
  if (COMBINE_DATA['Gideon Davidson']) { COMBINE_DATA['Gideon Davidson'].ht='6-0'; COMBINE_DATA['Gideon Davidson'].wt=200; }
  if (COMBINE_DATA['Harlem Berry']) { COMBINE_DATA['Harlem Berry'].ht='5-11'; COMBINE_DATA['Harlem Berry'].wt=190; }
  if (COMBINE_DATA['Isaac Brown']) { COMBINE_DATA['Isaac Brown'].ht='5-9'; COMBINE_DATA['Isaac Brown'].wt=190; }
  if (COMBINE_DATA['Isaiah Sategna III']) { COMBINE_DATA['Isaiah Sategna III'].ht='5-10'; COMBINE_DATA['Isaiah Sategna III'].wt=182; }
  if (COMBINE_DATA['Jadan Baugh']) { COMBINE_DATA['Jadan Baugh'].ht='6-1'; COMBINE_DATA['Jadan Baugh'].wt=231; }
  if (COMBINE_DATA['Jaron-Keawe Sagapolutele']) { COMBINE_DATA['Jaron-Keawe Sagapolutele'].ht='6-3'; COMBINE_DATA['Jaron-Keawe Sagapolutele'].wt=225; }
  if (COMBINE_DATA['Jayden Maiava']) { COMBINE_DATA['Jayden Maiava'].ht='6-4'; COMBINE_DATA['Jayden Maiava'].wt=230; }
  if (COMBINE_DATA['Jeremiah Smith']) { COMBINE_DATA['Jeremiah Smith'].ht='6-3'; COMBINE_DATA['Jeremiah Smith'].wt=223; }
  if (COMBINE_DATA['John Mateer']) { COMBINE_DATA['John Mateer'].ht='6-1'; COMBINE_DATA['John Mateer'].wt=224; }
  if (COMBINE_DATA['Jordan Marshall']) { COMBINE_DATA['Jordan Marshall'].ht='5-11'; COMBINE_DATA['Jordan Marshall'].wt=216; }
  if (COMBINE_DATA['Jordon Davison']) { COMBINE_DATA['Jordon Davison'].ht='6-0'; COMBINE_DATA['Jordon Davison'].wt=236; }
  if (COMBINE_DATA['Joshua Moore']) { COMBINE_DATA['Joshua Moore'].ht='6-4'; }
  if (COMBINE_DATA['Julian Lewis']) { COMBINE_DATA['Julian Lewis'].ht='6-1'; COMBINE_DATA['Julian Lewis'].wt=190; }
  if (COMBINE_DATA['Julian Sayin']) { COMBINE_DATA['Julian Sayin'].ht='6-1'; COMBINE_DATA['Julian Sayin'].wt=208; }
  if (COMBINE_DATA['Kaelan Chudzinski']) { COMBINE_DATA['Kaelan Chudzinski'].ht='6-3'; COMBINE_DATA['Kaelan Chudzinski'].wt=236; }
  if (COMBINE_DATA['Kaliq Lockett']) { COMBINE_DATA['Kaliq Lockett'].ht='6-2'; COMBINE_DATA['Kaliq Lockett'].wt=185; }
  if (COMBINE_DATA['Kewan Lacy']) { COMBINE_DATA['Kewan Lacy'].ht='5-11'; COMBINE_DATA['Kewan Lacy'].wt=200; }
  if (COMBINE_DATA['LJ Martin']) { COMBINE_DATA['LJ Martin'].ht='6-2'; COMBINE_DATA['LJ Martin'].wt=220; }
  if (COMBINE_DATA['LaNorris Sellers']) { COMBINE_DATA['LaNorris Sellers'].ht='6-3'; COMBINE_DATA['LaNorris Sellers'].wt=240; }
  if (COMBINE_DATA['Linkon Cure']) { COMBINE_DATA['Linkon Cure'].ht='6-5'; COMBINE_DATA['Linkon Cure'].wt=230; }
  if (COMBINE_DATA['Luke Hasz']) { COMBINE_DATA['Luke Hasz'].ht='6-3'; COMBINE_DATA['Luke Hasz'].wt=240; }
  if (COMBINE_DATA['Malik Washington']) { COMBINE_DATA['Malik Washington'].ht='6-5'; COMBINE_DATA['Malik Washington'].wt=231; }
  if (COMBINE_DATA['Marcel Reed']) { COMBINE_DATA['Marcel Reed'].ht='6-1'; COMBINE_DATA['Marcel Reed'].wt=185; }
  if (COMBINE_DATA['Mark Fletcher Jr.']) { COMBINE_DATA['Mark Fletcher Jr.'].ht='6-2'; COMBINE_DATA['Mark Fletcher Jr.'].wt=225; }
  if (COMBINE_DATA['Micah Hudson']) { COMBINE_DATA['Micah Hudson'].ht='6-0'; COMBINE_DATA['Micah Hudson'].wt=195; }
  if (COMBINE_DATA['Nate Frazier']) { COMBINE_DATA['Nate Frazier'].ht='5-10'; COMBINE_DATA['Nate Frazier'].wt=210; }
  if (COMBINE_DATA['Nate Sheppard']) { COMBINE_DATA['Nate Sheppard'].ht='5-10'; COMBINE_DATA['Nate Sheppard'].wt=195; }
  if (COMBINE_DATA['Nico Iamaleava']) { COMBINE_DATA['Nico Iamaleava'].ht='6-6'; COMBINE_DATA['Nico Iamaleava'].wt=215; }
  if (COMBINE_DATA['Nyck Harbor']) { COMBINE_DATA['Nyck Harbor'].ht='6-5'; COMBINE_DATA['Nyck Harbor'].wt=235; }
  if (COMBINE_DATA['Ousmane Kromah']) { COMBINE_DATA['Ousmane Kromah'].ht='6-1'; COMBINE_DATA['Ousmane Kromah'].wt=214; }
  // Quinten Joyner — no DraftBuzz measurables available
  if (COMBINE_DATA['Quinton Martin Jr.']) { COMBINE_DATA['Quinton Martin Jr.'].ht='6-1'; COMBINE_DATA['Quinton Martin Jr.'].wt=206; }
  if (COMBINE_DATA['Ryan Williams']) { COMBINE_DATA['Ryan Williams'].ht='6-0'; COMBINE_DATA['Ryan Williams'].wt=178; }
  if (COMBINE_DATA['T.J. Moore']) { COMBINE_DATA['T.J. Moore'].ht='6-3'; COMBINE_DATA['T.J. Moore'].wt=200; }
  if (COMBINE_DATA['Terrance Carter Jr.']) { COMBINE_DATA['Terrance Carter Jr.'].ht='6-2'; COMBINE_DATA['Terrance Carter Jr.'].wt=245; }
  if (COMBINE_DATA["Trey'Dez Green"]) { COMBINE_DATA["Trey'Dez Green"].ht='6-7'; COMBINE_DATA["Trey'Dez Green"].wt=240; }
  // === ADDITIONAL DEVY BIOS (from CFBD) ===
  if (COMBINE_DATA['Brendan Sorsby']) { COMBINE_DATA['Brendan Sorsby'].ht='6-3'; COMBINE_DATA['Brendan Sorsby'].wt=235; }
  if (COMBINE_DATA['Bryant Wesco Jr.']) { COMBINE_DATA['Bryant Wesco Jr.'].ht='6-2'; COMBINE_DATA['Bryant Wesco Jr.'].wt=185; }
  if (COMBINE_DATA['Bryce Underwood']) { COMBINE_DATA['Bryce Underwood'].ht='6-4'; COMBINE_DATA['Bryce Underwood'].wt=228; }
  if (COMBINE_DATA['Byrum Brown']) { COMBINE_DATA['Byrum Brown'].ht='6-3'; COMBINE_DATA['Byrum Brown'].wt=231; }
  if (COMBINE_DATA['CJ Baxter Jr.']) { COMBINE_DATA['CJ Baxter Jr.'].ht='6-1'; COMBINE_DATA['CJ Baxter Jr.'].wt=227; }
  if (COMBINE_DATA['Caleb Hawkins']) { COMBINE_DATA['Caleb Hawkins'].ht='6-2'; COMBINE_DATA['Caleb Hawkins'].wt=200; }
  if (COMBINE_DATA['Cam Coleman']) { COMBINE_DATA['Cam Coleman'].ht='6-3'; COMBINE_DATA['Cam Coleman'].wt=201; }
  if (COMBINE_DATA['Cam Cook']) { COMBINE_DATA['Cam Cook'].ht='5-11'; COMBINE_DATA['Cam Cook'].wt=195; }
  if (COMBINE_DATA['Cam Edwards']) { COMBINE_DATA['Cam Edwards'].ht='6-4'; COMBINE_DATA['Cam Edwards'].wt=200; }
  if (COMBINE_DATA['Dallas Wilson']) { COMBINE_DATA['Dallas Wilson'].ht='6-3'; COMBINE_DATA['Dallas Wilson'].wt=213; }
  if (COMBINE_DATA['Danny Scudero']) { COMBINE_DATA['Danny Scudero'].ht='5-9'; COMBINE_DATA['Danny Scudero'].wt=174; }
  if (COMBINE_DATA['Darian Mensah']) { COMBINE_DATA['Darian Mensah'].ht='6-3'; COMBINE_DATA['Darian Mensah'].wt=205; }
  if (COMBINE_DATA['Demond Williams Jr.']) { COMBINE_DATA['Demond Williams Jr.'].ht='5-11'; COMBINE_DATA['Demond Williams Jr.'].wt=190; }
  if (COMBINE_DATA['Deuce Knight']) { COMBINE_DATA['Deuce Knight'].ht='6-4'; COMBINE_DATA['Deuce Knight'].wt=217; }
  if (COMBINE_DATA['Dilin Jones']) { COMBINE_DATA['Dilin Jones'].ht='6-0'; COMBINE_DATA['Dilin Jones'].wt=205; }
  if (COMBINE_DATA['Dylan Raiola']) { COMBINE_DATA['Dylan Raiola'].ht='6-3'; COMBINE_DATA['Dylan Raiola'].wt=230; }
  if (COMBINE_DATA['Elyiss Williams']) { COMBINE_DATA['Elyiss Williams'].ht='6-6'; COMBINE_DATA['Elyiss Williams'].wt=255; }
  if (COMBINE_DATA['Eric Singleton Jr.']) { COMBINE_DATA['Eric Singleton Jr.'].ht='5-10'; COMBINE_DATA['Eric Singleton Jr.'].wt=180; }
  if (COMBINE_DATA['Husan Longstreet']) { COMBINE_DATA['Husan Longstreet'].ht='6-0'; COMBINE_DATA['Husan Longstreet'].wt=200; }
  if (COMBINE_DATA['Isaiah Horton']) { COMBINE_DATA['Isaiah Horton'].ht='6-4'; COMBINE_DATA['Isaiah Horton'].wt=208; }
  if (COMBINE_DATA['Jayce Brown']) { COMBINE_DATA['Jayce Brown'].ht='6-0'; COMBINE_DATA['Jayce Brown'].wt=179; }
  if (COMBINE_DATA['Jerrick Gibson']) { COMBINE_DATA['Jerrick Gibson'].ht='5-10'; COMBINE_DATA['Jerrick Gibson'].wt=206; }
  if (COMBINE_DATA['Josh Hoover']) { COMBINE_DATA['Josh Hoover'].ht='6-2'; COMBINE_DATA['Josh Hoover'].wt=200; }
  if (COMBINE_DATA['Joshisa Trader']) { COMBINE_DATA['Joshisa Trader'].ht='6-1'; COMBINE_DATA['Joshisa Trader'].wt=180; }
  if (COMBINE_DATA['Justice Haynes']) { COMBINE_DATA['Justice Haynes'].ht='5-11'; COMBINE_DATA['Justice Haynes'].wt=210; }
  if (COMBINE_DATA['Kam Davis']) { COMBINE_DATA['Kam Davis'].ht='5-10'; COMBINE_DATA['Kam Davis'].wt=217; }
  if (COMBINE_DATA['Keelon Russell']) { COMBINE_DATA['Keelon Russell'].ht='6-3'; COMBINE_DATA['Keelon Russell'].wt=194; }
  if (COMBINE_DATA['Kenny Johnson']) { COMBINE_DATA['Kenny Johnson'].ht='6-1'; COMBINE_DATA['Kenny Johnson'].wt=205; }
  if (COMBINE_DATA['Luke Reynolds']) { COMBINE_DATA['Luke Reynolds'].ht='6-4'; COMBINE_DATA['Luke Reynolds'].wt=250; }
  if (COMBINE_DATA['Malachi Toney']) { COMBINE_DATA['Malachi Toney'].ht='5-11'; }
  if (COMBINE_DATA['Nic Anderson']) { COMBINE_DATA['Nic Anderson'].ht='6-4'; COMBINE_DATA['Nic Anderson'].wt=208; }
  if (COMBINE_DATA['Nick Marsh']) { COMBINE_DATA['Nick Marsh'].ht='6-3'; COMBINE_DATA['Nick Marsh'].wt=203; }
  if (COMBINE_DATA['Perry Thompson']) { COMBINE_DATA['Perry Thompson'].ht='6-3'; COMBINE_DATA['Perry Thompson'].wt=220; }
  if (COMBINE_DATA['Quincy Porter']) { COMBINE_DATA['Quincy Porter'].ht='6-4'; COMBINE_DATA['Quincy Porter'].wt=210; }
  if (COMBINE_DATA['Raleek Brown']) { COMBINE_DATA['Raleek Brown'].ht='5-9'; COMBINE_DATA['Raleek Brown'].wt=195; }
  if (COMBINE_DATA['Ryan Wingo']) { COMBINE_DATA['Ryan Wingo'].ht='6-2'; COMBINE_DATA['Ryan Wingo'].wt=214; }
  if (COMBINE_DATA['Sam Leavitt']) { COMBINE_DATA['Sam Leavitt'].ht='6-2'; COMBINE_DATA['Sam Leavitt'].wt=205; }
  if (COMBINE_DATA['Talyn Taylor']) { COMBINE_DATA['Talyn Taylor'].ht='6-0'; COMBINE_DATA['Talyn Taylor'].wt=190; }
  if (COMBINE_DATA['Tavien St. Clair']) { COMBINE_DATA['Tavien St. Clair'].ht='6-4'; COMBINE_DATA['Tavien St. Clair'].wt=230; }
  // Taylor Tatum — no DraftBuzz measurables available
  if (COMBINE_DATA['Malachi Toney']) { COMBINE_DATA['Malachi Toney'].wt=175; }
  if (COMBINE_DATA['Hollywood Smothers']) { COMBINE_DATA['Hollywood Smothers'].ht='6-1'; COMBINE_DATA['Hollywood Smothers'].wt=215; }
  if (COMBINE_DATA['Eugene Wilson III']) { COMBINE_DATA['Eugene Wilson III'].ht='6-0'; COMBINE_DATA['Eugene Wilson III'].wt=185; }
  if (COMBINE_DATA['Joshua Moore']) { COMBINE_DATA['Joshua Moore'].wt=195; }
  if (COMBINE_DATA['DJ Lagway']) { COMBINE_DATA['DJ Lagway'].ht='6-2'; COMBINE_DATA['DJ Lagway'].wt=228; }
  if (COMBINE_DATA['Naeem Burroughs']) { COMBINE_DATA['Naeem Burroughs'].ht='6-1'; COMBINE_DATA['Naeem Burroughs'].wt=200; }

  // === MISSING DRAFT CAPITAL FIX (2012-2025) ===
  // Players in COMBINE_DATA with NFL teams but missing draft pick
  if (COMBINE_DATA['A.J. Derby'] && !COMBINE_DATA['A.J. Derby'].draft) COMBINE_DATA['A.J. Derby'].draft = 229;
  if (COMBINE_DATA['Aaron Ripkowski'] && !COMBINE_DATA['Aaron Ripkowski'].draft) COMBINE_DATA['Aaron Ripkowski'].draft = 206;
  if (COMBINE_DATA['Adrien Robinson'] && !COMBINE_DATA['Adrien Robinson'].draft) COMBINE_DATA['Adrien Robinson'].draft = 127;
  if (COMBINE_DATA['Alex McGough'] && !COMBINE_DATA['Alex McGough'].draft) COMBINE_DATA['Alex McGough'].draft = 220;
  if (COMBINE_DATA['Andre Debose'] && !COMBINE_DATA['Andre Debose'].draft) COMBINE_DATA['Andre Debose'].draft = 'U';
  if (COMBINE_DATA['Andrew Ogletree'] && !COMBINE_DATA['Andrew Ogletree'].draft) COMBINE_DATA['Andrew Ogletree'].draft = 235;
  if (COMBINE_DATA['Anthony Johnson'] && !COMBINE_DATA['Anthony Johnson'].draft) COMBINE_DATA['Anthony Johnson'].draft = 'U';
  if (COMBINE_DATA['Austin Proehl'] && !COMBINE_DATA['Austin Proehl'].draft) COMBINE_DATA['Austin Proehl'].draft = 'U';
  if (COMBINE_DATA['B.J. Daniels'] && !COMBINE_DATA['B.J. Daniels'].draft) COMBINE_DATA['B.J. Daniels'].draft = 'U';
  if (COMBINE_DATA['Ben Mason'] && !COMBINE_DATA['Ben Mason'].draft) COMBINE_DATA['Ben Mason'].draft = 184;
  if (COMBINE_DATA['Ben Skowronek'] && !COMBINE_DATA['Ben Skowronek'].draft) COMBINE_DATA['Ben Skowronek'].draft = 249;
  if (COMBINE_DATA['Boston Scott'] && !COMBINE_DATA['Boston Scott'].draft) COMBINE_DATA['Boston Scott'].draft = 201;
  if (COMBINE_DATA['Brad Anderson'] && !COMBINE_DATA['Brad Anderson'].draft) COMBINE_DATA['Brad Anderson'].draft = 'U';
  if (COMBINE_DATA['Brad Smelley'] && !COMBINE_DATA['Brad Smelley'].draft) COMBINE_DATA['Brad Smelley'].draft = 175;
  if (COMBINE_DATA['Brian Robinson Jr.'] && !COMBINE_DATA['Brian Robinson Jr.'].draft) COMBINE_DATA['Brian Robinson Jr.'].draft = 98;
  if (COMBINE_DATA['Brian Williams'] && !COMBINE_DATA['Brian Williams'].draft) COMBINE_DATA['Brian Williams'].draft = 'U';
  if (COMBINE_DATA['Brice Butler'] && !COMBINE_DATA['Brice Butler'].draft) COMBINE_DATA['Brice Butler'].draft = 209;
  if (COMBINE_DATA['Brittain Brown'] && !COMBINE_DATA['Brittain Brown'].draft) COMBINE_DATA['Brittain Brown'].draft = 'U';
  if (COMBINE_DATA['Bryce Brown'] && !COMBINE_DATA['Bryce Brown'].draft) COMBINE_DATA['Bryce Brown'].draft = 229;
  if (COMBINE_DATA['Bud Sasser'] && !COMBINE_DATA['Bud Sasser'].draft) COMBINE_DATA['Bud Sasser'].draft = 'U';
  if (COMBINE_DATA['C.J. Uzomah'] && !COMBINE_DATA['C.J. Uzomah'].draft) COMBINE_DATA['C.J. Uzomah'].draft = 164;
  if (COMBINE_DATA['Caleb Lohner'] && !COMBINE_DATA['Caleb Lohner'].draft) COMBINE_DATA['Caleb Lohner'].draft = 'U';
  if (COMBINE_DATA['Cam Miller'] && !COMBINE_DATA['Cam Miller'].draft) COMBINE_DATA['Cam Miller'].draft = 215;
  if (COMBINE_DATA['Casey Washington'] && !COMBINE_DATA['Casey Washington'].draft) COMBINE_DATA['Casey Washington'].draft = 'U';
  if (COMBINE_DATA['Chad Williams'] && !COMBINE_DATA['Chad Williams'].draft) COMBINE_DATA['Chad Williams'].draft = 98;
  if (COMBINE_DATA['Chandler Cox'] && !COMBINE_DATA['Chandler Cox'].draft) COMBINE_DATA['Chandler Cox'].draft = 'U';
  if (COMBINE_DATA['Chris Smith'] && !COMBINE_DATA['Chris Smith'].draft) COMBINE_DATA['Chris Smith'].draft = 'U';
  if (COMBINE_DATA['Chris Warren'] && !COMBINE_DATA['Chris Warren'].draft) COMBINE_DATA['Chris Warren'].draft = 'U';
  if (COMBINE_DATA['Colton Dowell'] && !COMBINE_DATA['Colton Dowell'].draft) COMBINE_DATA['Colton Dowell'].draft = 'U';
  if (COMBINE_DATA['Cullen Gillaspia'] && !COMBINE_DATA['Cullen Gillaspia'].draft) COMBINE_DATA['Cullen Gillaspia'].draft = 220;
  if (COMBINE_DATA['DaeSean Hamilton'] && !COMBINE_DATA['DaeSean Hamilton'].draft) COMBINE_DATA['DaeSean Hamilton'].draft = 113;
  if (COMBINE_DATA['Damion Ratley'] && !COMBINE_DATA['Damion Ratley'].draft) COMBINE_DATA['Damion Ratley'].draft = 175;
  if (COMBINE_DATA['Daniel Braverman'] && !COMBINE_DATA['Daniel Braverman'].draft) COMBINE_DATA['Daniel Braverman'].draft = 230;
  if (COMBINE_DATA['Dareke Young'] && !COMBINE_DATA['Dareke Young'].draft) COMBINE_DATA['Dareke Young'].draft = 233;
  if (COMBINE_DATA['Darius Jackson'] && !COMBINE_DATA['Darius Jackson'].draft) COMBINE_DATA['Darius Jackson'].draft = 216;
  if (COMBINE_DATA['Darwin Thompson'] && !COMBINE_DATA['Darwin Thompson'].draft) COMBINE_DATA['Darwin Thompson'].draft = 214;
  if (COMBINE_DATA['Daryl Richardson'] && !COMBINE_DATA['Daryl Richardson'].draft) COMBINE_DATA['Daryl Richardson'].draft = 252;
  if (COMBINE_DATA['Daurice Fountain'] && !COMBINE_DATA['Daurice Fountain'].draft) COMBINE_DATA['Daurice Fountain'].draft = 159;
  if (COMBINE_DATA['David Moore'] && !COMBINE_DATA['David Moore'].draft) COMBINE_DATA['David Moore'].draft = 'U';
  if (COMBINE_DATA['David Williams'] && !COMBINE_DATA['David Williams'].draft) COMBINE_DATA['David Williams'].draft = 'U';
  if (COMBINE_DATA['DeAndre Washington'] && !COMBINE_DATA['DeAndre Washington'].draft) COMBINE_DATA['DeAndre Washington'].draft = 143;
  if (COMBINE_DATA['DeAngelo Yancey'] && !COMBINE_DATA['DeAngelo Yancey'].draft) COMBINE_DATA['DeAngelo Yancey'].draft = 182;
  if (COMBINE_DATA['DeWayne McBride'] && !COMBINE_DATA['DeWayne McBride'].draft) COMBINE_DATA['DeWayne McBride'].draft = 222;
  if (COMBINE_DATA['Dennis Johnson'] && !COMBINE_DATA['Dennis Johnson'].draft) COMBINE_DATA['Dennis Johnson'].draft = 'U';
  if (COMBINE_DATA['Derek Watt'] && !COMBINE_DATA['Derek Watt'].draft) COMBINE_DATA['Derek Watt'].draft = 198;
  if (COMBINE_DATA['Devante Mays'] && !COMBINE_DATA['Devante Mays'].draft) COMBINE_DATA['Devante Mays'].draft = 247;
  if (COMBINE_DATA['Devin Fuller'] && !COMBINE_DATA['Devin Fuller'].draft) COMBINE_DATA['Devin Fuller'].draft = 'U';
  if (COMBINE_DATA['Devin Lucien'] && !COMBINE_DATA['Devin Lucien'].draft) COMBINE_DATA['Devin Lucien'].draft = 'U';
  if (COMBINE_DATA['Dezmin Lewis'] && !COMBINE_DATA['Dezmin Lewis'].draft) COMBINE_DATA['Dezmin Lewis'].draft = 'U';
  if (COMBINE_DATA['Don Jones'] && !COMBINE_DATA['Don Jones'].draft) COMBINE_DATA['Don Jones'].draft = 'U';
  if (COMBINE_DATA['Dwayne Washington'] && !COMBINE_DATA['Dwayne Washington'].draft) COMBINE_DATA['Dwayne Washington'].draft = 236;
  if (COMBINE_DATA['Dylan Laube'] && !COMBINE_DATA['Dylan Laube'].draft) COMBINE_DATA['Dylan Laube'].draft = 'U';
  if (COMBINE_DATA['EJ Manuel'] && !COMBINE_DATA['EJ Manuel'].draft) COMBINE_DATA['EJ Manuel'].draft = 16;
  if (COMBINE_DATA['Equanimeous St. Brown'] && !COMBINE_DATA['Equanimeous St. Brown'].draft) COMBINE_DATA['Equanimeous St. Brown'].draft = 207;
  if (COMBINE_DATA['Evan Hull'] && !COMBINE_DATA['Evan Hull'].draft) COMBINE_DATA['Evan Hull'].draft = 197;
  if (COMBINE_DATA['Evan Spencer'] && !COMBINE_DATA['Evan Spencer'].draft) COMBINE_DATA['Evan Spencer'].draft = 'U';
  if (COMBINE_DATA['Garrett Gilbert'] && !COMBINE_DATA['Garrett Gilbert'].draft) COMBINE_DATA['Garrett Gilbert'].draft = 214;
  if (COMBINE_DATA['Geoff Swaim'] && !COMBINE_DATA['Geoff Swaim'].draft) COMBINE_DATA['Geoff Swaim'].draft = 246;
  if (COMBINE_DATA['George Farmer'] && !COMBINE_DATA['George Farmer'].draft) COMBINE_DATA['George Farmer'].draft = 'U';
  if (COMBINE_DATA['Gerrid Doaks'] && !COMBINE_DATA['Gerrid Doaks'].draft) COMBINE_DATA['Gerrid Doaks'].draft = 244;
  if (COMBINE_DATA['Greg Bell'] && !COMBINE_DATA['Greg Bell'].draft) COMBINE_DATA['Greg Bell'].draft = 'U';
  if (COMBINE_DATA['Hunter Long'] && !COMBINE_DATA['Hunter Long'].draft) COMBINE_DATA['Hunter Long'].draft = 81;
  if (COMBINE_DATA['Ito Smith'] && !COMBINE_DATA['Ito Smith'].draft) COMBINE_DATA['Ito Smith'].draft = 126;
  if (COMBINE_DATA['J.T. Thomas'] && !COMBINE_DATA['J.T. Thomas'].draft) COMBINE_DATA['J.T. Thomas'].draft = 'U';
  if (COMBINE_DATA['Jacob Harris'] && !COMBINE_DATA['Jacob Harris'].draft) COMBINE_DATA['Jacob Harris'].draft = 141;
  if (COMBINE_DATA['Jacory Croskey-Merritt'] && !COMBINE_DATA['Jacory Croskey-Merritt'].draft) COMBINE_DATA['Jacory Croskey-Merritt'].draft = 245;
  if (COMBINE_DATA['Jake Rudock'] && !COMBINE_DATA['Jake Rudock'].draft) COMBINE_DATA['Jake Rudock'].draft = 240;
  if (COMBINE_DATA['Jakeem Grant'] && !COMBINE_DATA['Jakeem Grant'].draft) COMBINE_DATA['Jakeem Grant'].draft = 186;
  if (COMBINE_DATA['Jalen Camp'] && !COMBINE_DATA['Jalen Camp'].draft) COMBINE_DATA['Jalen Camp'].draft = 250;
  if (COMBINE_DATA['James Wilder'] && !COMBINE_DATA['James Wilder'].draft) COMBINE_DATA['James Wilder'].draft = 'U';
  if (COMBINE_DATA['James Wright'] && !COMBINE_DATA['James Wright'].draft) COMBINE_DATA['James Wright'].draft = 210;
  if (COMBINE_DATA['Jason Huntley'] && !COMBINE_DATA['Jason Huntley'].draft) COMBINE_DATA['Jason Huntley'].draft = 172;
  if (COMBINE_DATA['Jay Prosch'] && !COMBINE_DATA['Jay Prosch'].draft) COMBINE_DATA['Jay Prosch'].draft = 116;
  if (COMBINE_DATA['Jeff George'] && !COMBINE_DATA['Jeff George'].draft) COMBINE_DATA['Jeff George'].draft = 'U';
  if (COMBINE_DATA['Jeff Smith'] && !COMBINE_DATA['Jeff Smith'].draft) COMBINE_DATA['Jeff Smith'].draft = 'U';
  if (COMBINE_DATA['Jeremy Ebert'] && !COMBINE_DATA['Jeremy Ebert'].draft) COMBINE_DATA['Jeremy Ebert'].draft = 235;
  if (COMBINE_DATA['Jimmy Horn'] && !COMBINE_DATA['Jimmy Horn'].draft) COMBINE_DATA['Jimmy Horn'].draft = 'U';
  if (COMBINE_DATA['Joe Mixon'] && !COMBINE_DATA['Joe Mixon'].draft) COMBINE_DATA['Joe Mixon'].draft = 48;
  if (COMBINE_DATA['John Bates'] && !COMBINE_DATA['John Bates'].draft) COMBINE_DATA['John Bates'].draft = 166;
  if (COMBINE_DATA['John Ursua'] && !COMBINE_DATA['John Ursua'].draft) COMBINE_DATA['John Ursua'].draft = 236;
  if (COMBINE_DATA['Jordan Watkins'] && !COMBINE_DATA['Jordan Watkins'].draft) COMBINE_DATA['Jordan Watkins'].draft = 'U';
  if (COMBINE_DATA['Josh Johnson'] && !COMBINE_DATA['Josh Johnson'].draft) COMBINE_DATA['Josh Johnson'].draft = 'U';
  if (COMBINE_DATA['Junior Bergen'] && !COMBINE_DATA['Junior Bergen'].draft) COMBINE_DATA['Junior Bergen'].draft = 'U';
  if (COMBINE_DATA['Justin Watson'] && !COMBINE_DATA['Justin Watson'].draft) COMBINE_DATA['Justin Watson'].draft = 223;
  if (COMBINE_DATA['Juwann Winfree'] && !COMBINE_DATA['Juwann Winfree'].draft) COMBINE_DATA['Juwann Winfree'].draft = 187;
  if (COMBINE_DATA['Kawaan Baker'] && !COMBINE_DATA['Kawaan Baker'].draft) COMBINE_DATA['Kawaan Baker'].draft = 203;
  if (COMBINE_DATA['KeeSean Johnson'] && !COMBINE_DATA['KeeSean Johnson'].draft) COMBINE_DATA['KeeSean Johnson'].draft = 174;
  if (COMBINE_DATA['Keenan Reynolds'] && !COMBINE_DATA['Keenan Reynolds'].draft) COMBINE_DATA['Keenan Reynolds'].draft = 182;
  if (COMBINE_DATA['Kene Nwangwu'] && !COMBINE_DATA['Kene Nwangwu'].draft) COMBINE_DATA['Kene Nwangwu'].draft = 178;
  if (COMBINE_DATA['Kennard Backman'] && !COMBINE_DATA['Kennard Backman'].draft) COMBINE_DATA['Kennard Backman'].draft = 234;
  if (COMBINE_DATA['Kenneth Walker III'] && !COMBINE_DATA['Kenneth Walker III'].draft) COMBINE_DATA['Kenneth Walker III'].draft = 41;
  if (COMBINE_DATA['Kevin Dorsey'] && !COMBINE_DATA['Kevin Dorsey'].draft) COMBINE_DATA['Kevin Dorsey'].draft = 'U';
  if (COMBINE_DATA['Khalfani Muhammad'] && !COMBINE_DATA['Khalfani Muhammad'].draft) COMBINE_DATA['Khalfani Muhammad'].draft = 'U';
  if (COMBINE_DATA['Kiero Small'] && !COMBINE_DATA['Kiero Small'].draft) COMBINE_DATA['Kiero Small'].draft = 'U';
  if (COMBINE_DATA['Ko Kieft'] && !COMBINE_DATA['Ko Kieft'].draft) COMBINE_DATA['Ko Kieft'].draft = 218;
  if (COMBINE_DATA['Kyle Juszczyk'] && !COMBINE_DATA['Kyle Juszczyk'].draft) COMBINE_DATA['Kyle Juszczyk'].draft = 130;
  if (COMBINE_DATA['Kylen Granson'] && !COMBINE_DATA['Kylen Granson'].draft) COMBINE_DATA['Kylen Granson'].draft = 127;
  if (COMBINE_DATA['Latavius Murray'] && !COMBINE_DATA['Latavius Murray'].draft) COMBINE_DATA['Latavius Murray'].draft = 181;
  if (COMBINE_DATA['Luke Willson'] && !COMBINE_DATA['Luke Willson'].draft) COMBINE_DATA['Luke Willson'].draft = 158;
  if (COMBINE_DATA['Malcolm Johnson'] && !COMBINE_DATA['Malcolm Johnson'].draft) COMBINE_DATA['Malcolm Johnson'].draft = 'U';
  if (COMBINE_DATA['Marcus Green'] && !COMBINE_DATA['Marcus Green'].draft) COMBINE_DATA['Marcus Green'].draft = 203;
  if (COMBINE_DATA['Marquez Williams'] && !COMBINE_DATA['Marquez Williams'].draft) COMBINE_DATA['Marquez Williams'].draft = 'U';
  if (COMBINE_DATA['Mason Schreck'] && !COMBINE_DATA['Mason Schreck'].draft) COMBINE_DATA['Mason Schreck'].draft = 245;
  if (COMBINE_DATA['Michael Cox'] && !COMBINE_DATA['Michael Cox'].draft) COMBINE_DATA['Michael Cox'].draft = 'U';
  if (COMBINE_DATA['Michael Pittman Jr.'] && !COMBINE_DATA['Michael Pittman Jr.'].draft) COMBINE_DATA['Michael Pittman Jr.'].draft = 34;
  if (COMBINE_DATA['Michael Smith'] && !COMBINE_DATA['Michael Smith'].draft) COMBINE_DATA['Michael Smith'].draft = 'U';
  if (COMBINE_DATA['Michael Wiley'] && !COMBINE_DATA['Michael Wiley'].draft) COMBINE_DATA['Michael Wiley'].draft = 'U';
  if (COMBINE_DATA['Michael Williams'] && !COMBINE_DATA['Michael Williams'].draft) COMBINE_DATA['Michael Williams'].draft = 245;
  if (COMBINE_DATA['Montrell Washington'] && !COMBINE_DATA['Montrell Washington'].draft) COMBINE_DATA['Montrell Washington'].draft = 162;
  if (COMBINE_DATA['Moritz Boehringer'] && !COMBINE_DATA['Moritz Boehringer'].draft) COMBINE_DATA['Moritz Boehringer'].draft = 180;
  if (COMBINE_DATA['Neal Sterling'] && !COMBINE_DATA['Neal Sterling'].draft) COMBINE_DATA['Neal Sterling'].draft = 242;
  if (COMBINE_DATA['Nick Muse'] && !COMBINE_DATA['Nick Muse'].draft) COMBINE_DATA['Nick Muse'].draft = 229;
  if (COMBINE_DATA['Odell Beckham Jr.'] && !COMBINE_DATA['Odell Beckham Jr.'].draft) COMBINE_DATA['Odell Beckham Jr.'].draft = 12;
  if (COMBINE_DATA['Ray-Ray McCloud'] && !COMBINE_DATA['Ray-Ray McCloud'].draft) COMBINE_DATA['Ray-Ray McCloud'].draft = 187;
  if (COMBINE_DATA['Ricky Jones'] && !COMBINE_DATA['Ricky Jones'].draft) COMBINE_DATA['Ricky Jones'].draft = 'U';
  if (COMBINE_DATA['Ricky White'] && !COMBINE_DATA['Ricky White'].draft) COMBINE_DATA['Ricky White'].draft = 238;
  if (COMBINE_DATA['Rico Gathers'] && !COMBINE_DATA['Rico Gathers'].draft) COMBINE_DATA['Rico Gathers'].draft = 'U';
  if (COMBINE_DATA['Russell Gage'] && !COMBINE_DATA['Russell Gage'].draft) COMBINE_DATA['Russell Gage'].draft = 194;
  if (COMBINE_DATA['Ryan Griffin'] && !COMBINE_DATA['Ryan Griffin'].draft) COMBINE_DATA['Ryan Griffin'].draft = 'U';
  if (COMBINE_DATA['Samori Toure'] && !COMBINE_DATA['Samori Toure'].draft) COMBINE_DATA['Samori Toure'].draft = 258;
  if (COMBINE_DATA['Scott Miller'] && !COMBINE_DATA['Scott Miller'].draft) COMBINE_DATA['Scott Miller'].draft = 208;
  if (COMBINE_DATA['Sean Clifford'] && !COMBINE_DATA['Sean Clifford'].draft) COMBINE_DATA['Sean Clifford'].draft = 149;
  if (COMBINE_DATA['Shi Smith'] && !COMBINE_DATA['Shi Smith'].draft) COMBINE_DATA['Shi Smith'].draft = 204;
  if (COMBINE_DATA['Tahj Washington'] && !COMBINE_DATA['Tahj Washington'].draft) COMBINE_DATA['Tahj Washington'].draft = 'U';
  if (COMBINE_DATA['Taylor Thompson'] && !COMBINE_DATA['Taylor Thompson'].draft) COMBINE_DATA['Taylor Thompson'].draft = 205;
  if (COMBINE_DATA['Ted Bolser'] && !COMBINE_DATA['Ted Bolser'].draft) COMBINE_DATA['Ted Bolser'].draft = 'U';
  if (COMBINE_DATA['Tejhaun Palmer'] && !COMBINE_DATA['Tejhaun Palmer'].draft) COMBINE_DATA['Tejhaun Palmer'].draft = 'U';
  if (COMBINE_DATA['Terrace Marshall Jr.'] && !COMBINE_DATA['Terrace Marshall Jr.'].draft) COMBINE_DATA['Terrace Marshall Jr.'].draft = 59;
  if (COMBINE_DATA['Theo Johnson'] && !COMBINE_DATA['Theo Johnson'].draft) COMBINE_DATA['Theo Johnson'].draft = 100;
  if (COMBINE_DATA['Tommy Mellott'] && !COMBINE_DATA['Tommy Mellott'].draft) COMBINE_DATA['Tommy Mellott'].draft = 'U';
  if (COMBINE_DATA['Toney Clemons'] && !COMBINE_DATA['Toney Clemons'].draft) COMBINE_DATA['Toney Clemons'].draft = 230;
  if (COMBINE_DATA['Tony Jones'] && !COMBINE_DATA['Tony Jones'].draft) COMBINE_DATA['Tony Jones'].draft = 'U';
  if (COMBINE_DATA['Trenton Cannon'] && !COMBINE_DATA['Trenton Cannon'].draft) COMBINE_DATA['Trenton Cannon'].draft = 204;
  if (COMBINE_DATA['Tyler Davis'] && !COMBINE_DATA['Tyler Davis'].draft) COMBINE_DATA['Tyler Davis'].draft = 206;
  if (COMBINE_DATA['Tyreek Hill'] && !COMBINE_DATA['Tyreek Hill'].draft) COMBINE_DATA['Tyreek Hill'].draft = 165;
  if (COMBINE_DATA['Velus Jones Jr.'] && !COMBINE_DATA['Velus Jones Jr.'].draft) COMBINE_DATA['Velus Jones Jr.'].draft = 174;
  if (COMBINE_DATA['Walt Powell'] && !COMBINE_DATA['Walt Powell'].draft) COMBINE_DATA['Walt Powell'].draft = 'U';
  if (COMBINE_DATA['Wayne Capers'] && !COMBINE_DATA['Wayne Capers'].draft) COMBINE_DATA['Wayne Capers'].draft = 'U';
  if (COMBINE_DATA['Willie Snead'] && !COMBINE_DATA['Willie Snead'].draft) COMBINE_DATA['Willie Snead'].draft = 'U';
  if (COMBINE_DATA['Woody Marks'] && !COMBINE_DATA['Woody Marks'].draft) COMBINE_DATA['Woody Marks'].draft = 116;
  if (COMBINE_DATA['Zac Brooks'] && !COMBINE_DATA['Zac Brooks'].draft) COMBINE_DATA['Zac Brooks'].draft = 'U';
  if (COMBINE_DATA['Zach Davidson'] && !COMBINE_DATA['Zach Davidson'].draft) COMBINE_DATA['Zach Davidson'].draft = 168;
  if (COMBINE_DATA['Zander Horvath'] && !COMBINE_DATA['Zander Horvath'].draft) COMBINE_DATA['Zander Horvath'].draft = 260;

  // === 2025 NFL DRAFT — SKILL POSITION PICKS (QB/RB/WR/TE) ===
  // Source: Wikipedia 2025 NFL Draft, verified via NFL.com/CBS/ESPN
  // Helper: set draft pick if player exists and doesn't already have it
  function _sd25(name, pick, team, pos, school) {
    if (!COMBINE_DATA[name]) COMBINE_DATA[name] = { yr: 2025, pos: pos, school: school };
    COMBINE_DATA[name].draft = pick;   // force — this is confirmed draft capital
    COMBINE_DATA[name].yr = 2025;      // force — this is a 2025 drafted player
    if (!COMBINE_DATA[name].dt) COMBINE_DATA[name].dt = team;
  }
  // Round 1
  _sd25('Cam Ward', 1, 'TEN', 'QB', 'Miami (FL)');
  _sd25('Travis Hunter', 2, 'JAX', 'WR', 'Colorado');
  _sd25('Ashton Jeanty', 6, 'LV', 'RB', 'Boise State');
  _sd25('Tetairoa McMillan', 8, 'CAR', 'WR', 'Arizona');
  _sd25('Colston Loveland', 10, 'CHI', 'TE', 'Michigan');
  _sd25('Tyler Warren', 14, 'IND', 'TE', 'Penn State');
  _sd25('Emeka Egbuka', 19, 'TB', 'WR', 'Ohio State');
  _sd25('Omarion Hampton', 22, 'LAC', 'RB', 'North Carolina');
  _sd25('Matthew Golden', 23, 'GB', 'WR', 'Texas');
  _sd25('Jaxson Dart', 25, 'NYG', 'QB', 'Ole Miss');
  // Round 2
  _sd25('Jaylin Noel', 34, 'HOU', 'WR', 'Iowa State');
  _sd25('Quinshon Judkins', 36, 'CLE', 'RB', 'Ohio State');
  _sd25('TreVeyon Henderson', 38, 'NE', 'RB', 'Ohio State');
  _sd25('Luther Burden III', 39, 'CHI', 'WR', 'Missouri');
  _sd25('Tyler Shough', 40, 'NO', 'QB', 'Louisville');
  _sd25('Mason Taylor', 42, 'NYJ', 'TE', 'LSU');
  _sd25('Terrance Ferguson', 46, 'LAR', 'TE', 'Oregon');
  _sd25('Elijah Arroyo', 50, 'SEA', 'TE', 'Miami (FL)');
  _sd25('Tre Harris', 55, 'LAC', 'WR', 'Ole Miss');
  _sd25('Josh Hoover', 58, 'LV', 'WR', 'TCU');
  _sd25('RJ Harvey', 60, 'DEN', 'RB', 'UCF');
  // Round 3
  _sd25('Harold Fannin Jr.', 67, 'CLE', 'TE', 'Bowling Green');
  _sd25('Kyle Williams', 69, 'NE', 'WR', 'Washington State');
  _sd25('Andrew Armstrong', 70, 'DET', 'WR', 'Arkansas');
  _sd25('Zakhari Franklin', 74, 'DEN', 'WR', 'Illinois');
  _sd25('Jayden Higgins', 79, 'HOU', 'WR', 'Iowa State');
  _sd25('Kaleb Johnson', 83, 'PIT', 'RB', 'Iowa');
  _sd25('Savion Williams', 87, 'GB', 'WR', 'TCU');
  _sd25('Jalen Milroe', 92, 'SEA', 'QB', 'Alabama');
  _sd25('Dillon Gabriel', 94, 'CLE', 'QB', 'Oregon');
  _sd25('Tai Felton', 102, 'MIN', 'WR', 'Maryland');
  _sd25('Chimere Dike', 103, 'TEN', 'WR', 'Florida');
  // Round 4
  _sd25('Bhayshul Tuten', 104, 'JAX', 'RB', 'Virginia Tech');
  _sd25('Cam Skattebo', 105, 'NYG', 'RB', 'Arizona State');
  _sd25("Dont'e Thornton Jr.", 108, 'LV', 'WR', 'Tennessee');
  _sd25('Dillon Bell', 110, 'NYJ', 'WR', 'Georgia');
  _sd25('Nate Frazier', 114, 'CAR', 'RB', 'Georgia');
  _sd25('Woody Marks', 116, 'HOU', 'RB', 'USC');
  _sd25('Jarquez Hunter', 117, 'LAR', 'RB', 'Auburn');
  _sd25('Gunnar Helm', 120, 'TEN', 'TE', 'Texas');
  _sd25('Dylan Sampson', 126, 'CLE', 'RB', 'Tennessee');
  _sd25("Da'Quan Felton", 128, 'WAS', 'WR', 'Virginia Tech');
  _sd25('Jalen Royals', 133, 'KC', 'WR', 'Utah State');
  _sd25('Elic Ayomanor', 136, 'TEN', 'WR', 'Stanford');
  _sd25('Juice Wells', 138, 'SF', 'WR', 'Ole Miss');
  // Round 5
  _sd25('Shedeur Sanders', 144, 'CLE', 'QB', 'Colorado');
  _sd25('Jordan James', 147, 'SF', 'RB', 'Oregon');
  _sd25('Jaydon Blue', 149, 'DAL', 'RB', 'Texas');
  _sd25('DJ Giddens', 151, 'IND', 'RB', 'Kansas State');
  _sd25('Camden Brown', 158, 'LAC', 'WR', 'Auburn');
  _sd25('Mitchell Evans', 163, 'CAR', 'TE', 'Notre Dame');
  _sd25('Oronde Gadsden II', 165, 'LAC', 'TE', 'Syracuse');
  _sd25('Tory Horton', 166, 'SEA', 'WR', 'Colorado State');
  // Round 6
  _sd25('Ollie Gordon II', 179, 'MIA', 'RB', 'Oklahoma State');
  _sd25('Kyle McCord', 181, 'PHI', 'QB', 'Syracuse');
  _sd25('Devin Neal', 184, 'NO', 'RB', 'Kansas');
  _sd25('Will Howard', 185, 'PIT', 'QB', 'Ohio State');
  _sd25('Kalel Mullings', 188, 'TEN', 'RB', 'Michigan');
  _sd25('Riley Leonard', 189, 'IND', 'QB', 'Notre Dame');
  _sd25('Tahj Brooks', 193, 'CIN', 'RB', 'Texas Tech');
  _sd25('DJ Lagway', 197, 'HOU', 'QB', 'Florida');
  _sd25('Gavin Bartholomew', 202, 'MIN', 'TE', 'Pittsburgh');
  _sd25('LaJohntay Wester', 203, 'BAL', 'WR', 'Colorado');
  _sd25('Drelon Miller', 208, 'CAR', 'WR', 'Colorado');
  _sd25('Ty Okada', 213, 'LV', 'WR', 'Montana State');
  _sd25('Cam Miller', 215, 'LV', 'QB', 'North Dakota State');
  // Round 7
  _sd25('Thomas Fidone II', 219, 'NYG', 'TE', 'Nebraska');
  _sd25('Mark Fletcher Jr.', 223, 'SEA', 'RB', 'Miami (FL)');
  _sd25('Brashard Smith', 228, 'KC', 'RB', 'SMU');
  _sd25('Quinn Ewers', 231, 'MIA', 'QB', 'Texas');
  _sd25('Kyle Monangai', 233, 'CHI', 'RB', 'Rutgers');
  _sd25('Traeshon Holden', 235, 'TB', 'WR', 'Oregon');
  _sd25('LeQuint Allen Jr.', 236, 'JAX', 'RB', 'Syracuse');
  _sd25('Ricky White III', 238, 'SEA', 'WR', 'UNLV');
  _sd25('Phil Mafah', 239, 'DAL', 'RB', 'Clemson');
  _sd25('Brant Kuithe', 241, 'DEN', 'TE', 'Utah');
  _sd25('Konata Mumpfield', 242, 'LAR', 'WR', 'Pittsburgh');
  _sd25('Dominic Lovett', 244, 'DET', 'WR', 'Georgia');
  _sd25('Jacory Croskey-Merritt', 245, 'WAS', 'RB', 'Arizona');
  _sd25('Moliki Matavao', 248, 'NO', 'TE', 'UCLA');
  _sd25('Aaron Fontes', 252, 'SF', 'WR', 'Montana');
  _sd25('Luke Lachey', 255, 'HOU', 'TE', 'Iowa');

  // === 2025 NOTABLE UDFAs — SKILL POSITIONS ===
  // Players likely in COLLEGE_STATS/COMBINE_DATA who went undrafted
  function _udfa25(name, team, pos, school) {
    if (!COMBINE_DATA[name]) COMBINE_DATA[name] = { yr: 2025, pos: pos, school: school };
    COMBINE_DATA[name].draft = 'U';    // force — confirmed UDFA
    COMBINE_DATA[name].yr = 2025;      // force — 2025 class
    if (!COMBINE_DATA[name].dt) COMBINE_DATA[name].dt = team;
  }
  _udfa25('Xavier Restrepo', 'TB', 'WR', 'Miami (FL)');
  _udfa25('Raheim Sanders', 'LAC', 'RB', 'South Carolina');
  _udfa25('Jacolby George', 'CAR', 'WR', 'Miami (FL)');
  _udfa25('Julian Fleming', 'GB', 'WR', 'Penn State');
  _udfa25('Muhsin Muhammad III', 'CAR', 'WR', 'Texas A&M');
  _udfa25('Seth Henigan', 'JAX', 'QB', 'Memphis');
  _udfa25('Max Brosmer', 'MIN', 'QB', 'Minnesota');
  _udfa25('Quali Conley', 'CIN', 'RB', 'Arizona');
  _udfa25('Silas Bolden', 'MIN', 'WR', 'Texas');
  _udfa25('Nick Nash', 'ARI', 'WR', 'San Jose State');
  _udfa25('DJ Uiagalelei', 'LV', 'QB', 'Florida State');
  _udfa25('Luke Grimm', 'LAC', 'WR', 'Kansas');
  _udfa25('Ethan Garbers', 'CAR', 'QB', 'UCLA');
  _udfa25('Theo Wease Jr.', 'DET', 'WR', 'Memphis');
  _udfa25('Ben Yurosek', 'DET', 'TE', 'Georgia');
  _udfa25('Bryson Nesbit', 'DET', 'TE', 'North Carolina');
  _udfa25('Rocket Sanders', 'LAC', 'RB', 'South Carolina');
  _udfa25('Donovan Edwards', 'NYJ', 'RB', 'Michigan');
  _udfa25('Ahmani Marshall', 'CLE', 'RB', 'Appalachian State');
  _udfa25('Brady Cook', 'NYJ', 'QB', 'Missouri');
  _udfa25('Payton Thorne', 'CIN', 'QB', 'Auburn');
  _udfa25('Connor Bazelak', 'TB', 'QB', 'Bowling Green');
  _udfa25('Marcus Major Jr.', 'MIN', 'RB', 'Minnesota');
  _udfa25('Keleki Latu', 'BUF', 'TE', 'Washington');
  _udfa25('Lan Larison', 'NE', 'RB', 'UC Davis');
  _udfa25('Marcus Yarns', 'NO', 'RB', 'Delaware');
  _udfa25('Tanner Koziol', 'HOU', 'TE', 'Ball State');

  // Sync 2025 draft/UDFA teams from COMBINE_DATA.dt back to D[].t
  // d.js may have pre-draft teams (e.g., Gadsden as MIA instead of LAC)
  // NOTE: cb.dt stores ABBREVIATIONS but the codes are not consistent — most
  // entries use 2-letter codes (TEN, BAL, ATL) while some recent imports use
  // 3-letter codes (TAM, GNB, KAN, LVR, NWE, NOR, SFO). D[].t stores FULL
  // NAMES (e.g., "Tennessee Titans"). We first normalize the 3-letter codes
  // to their 2-letter equivalents, then look up the full team name. Without
  // the normalization step, a player like Emeka Egbuka (cb.dt="TAM") would
  // miss the lookup and have d.t corrupted to the bare abbreviation.
  var _SD25_3TO2 = {GNB:'GB',KAN:'KC',LVR:'LV',NWE:'NE',NOR:'NO',SFO:'SF',TAM:'TB'};
  var _SD25_ABBR_TO_FULL = {
    'ARI':'Arizona Cardinals','ATL':'Atlanta Falcons','BAL':'Baltimore Ravens','BUF':'Buffalo Bills',
    'CAR':'Carolina Panthers','CHI':'Chicago Bears','CIN':'Cincinnati Bengals','CLE':'Cleveland Browns',
    'DAL':'Dallas Cowboys','DEN':'Denver Broncos','DET':'Detroit Lions','GB':'Green Bay Packers',
    'HOU':'Houston Texans','IND':'Indianapolis Colts','JAX':'Jacksonville Jaguars','KC':'Kansas City Chiefs',
    'LAC':'Los Angeles Chargers','LAR':'Los Angeles Rams','LV':'Las Vegas Raiders','MIA':'Miami Dolphins',
    'MIN':'Minnesota Vikings','NE':'New England Patriots','NO':'New Orleans Saints','NYG':'New York Giants',
    'NYJ':'New York Jets','PHI':'Philadelphia Eagles','PIT':'Pittsburgh Steelers','SF':'San Francisco 49ers',
    'SEA':'Seattle Seahawks','TB':'Tampa Bay Buccaneers','TEN':'Tennessee Titans','WAS':'Washington Commanders'
  };
  D.forEach(function(d) {
    var cb = COMBINE_DATA[d.n];
    if (cb && cb.yr === 2025 && cb.dt) {
      // Normalize 3-letter combine-data codes to standard 2-letter codes first
      var abbr = _SD25_3TO2[cb.dt] || cb.dt;
      var fullTeam = _SD25_ABBR_TO_FULL[abbr];
      // Only overwrite d.t if we got a real full name. If lookup misses
      // (unusual abbreviation), keep d.t as-is rather than corrupting it
      // with the raw abbreviation.
      if (fullTeam && fullTeam !== d.t) d.t = fullTeam;
    }
  });

  // === NAME ALIASES: create COMBINE_DATA entries under alternate name spellings ===
  // D[] uses curly apostrophes, COMBINE_DATA uses plain names. Create cross-references.
  var _cbNameAliases = {
    "Tre' Harris": "Tre Harris", "Josh Palmer": "Josh Palmer",
    "Mitchell Tinsley": "Mitchell Tinsley", "Chris Brooks": "Christopher Brooks",
    "John Metchie III": "John Metchie", "Mitch Trubisky": "Mitchell Trubisky"
  };
  Object.keys(_cbNameAliases).forEach(function(alt) {
    var canonical = _cbNameAliases[alt];
    if (COMBINE_DATA[canonical] && !COMBINE_DATA[alt]) COMBINE_DATA[alt] = COMBINE_DATA[canonical];
    if (COMBINE_DATA[alt] && !COMBINE_DATA[canonical]) COMBINE_DATA[canonical] = COMBINE_DATA[alt];
  });

  // === BACKFILL D[] draft capital from COMBINE_DATA ===
  // Many D[] entries are missing the dr field (184 skill players). COMBINE_DATA has
  // draft pick info for most of them. Merge it back so player cards, prospect table DC
  // column, and all other displays have access to draft capital.
  if (typeof D !== 'undefined' && typeof COMBINE_DATA !== 'undefined') {
    // Name alias map: D[] name → COMBINE_DATA name (for known mismatches)
    const _drAliases = {
      "Tre' Harris": "Tre Harris", "Josh Palmer": "Josh Palmer",
      "Mitchell Tinsley": "Mitchell Tinsley", "Chris Brooks": "Christopher Brooks",
      "John Metchie III": "John Metchie", "Mitch Trubisky": "Mitchell Trubisky"
    };
    D.forEach(function(d) {
      if (!d.n) return;
      // Try exact name, then alias, then suffix variations
      var cb = COMBINE_DATA[d.n] || (_drAliases[d.n] ? COMBINE_DATA[_drAliases[d.n]] : null);
      if (!cb) {
        // Try Jr./Sr. suffix variations
        var noSuffix = d.n.replace(/\s+(Jr\.?|Sr\.?|II|III|IV|V)$/i, '').trim();
        var withSuffix = d.n + ' Jr.';
        cb = (noSuffix !== d.n) ? COMBINE_DATA[noSuffix] : (COMBINE_DATA[withSuffix] || COMBINE_DATA[d.n + ' Jr']);
      }
      if (!cb) {
        // Try stripping apostrophes/special chars
        var cleaned = d.n.replace(/[''`]/g, '');
        if (cleaned !== d.n) cb = COMBINE_DATA[cleaned];
      }
      // For 2026 prospects, ALWAYS overwrite d.dr from COMBINE_DATA so post-draft
      // updates flow through. For older years, preserve existing d.dr.
      var force2026 = cb && cb.yr === 2026;
      if (d.dr != null && !force2026) return; // already has dr
      if (cb && cb.draft != null) {
        d.dr = (cb.draft === 'U' || cb.draft === 'u') ? 'U' : parseInt(cb.draft) || cb.draft;
      } else if (cb && cb.draftProj != null) {
        d.dr = (cb.draftProj === 'U' || cb.draftProj === 'u') ? 'U' : parseInt(cb.draftProj) || cb.draftProj;
      }
    });
  }
}
