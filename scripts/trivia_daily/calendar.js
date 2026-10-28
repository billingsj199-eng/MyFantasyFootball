// Daily Trivia theme picker — NFL calendar + Eastern-time date helpers.
//
// Every date in this module is a YYYY-MM-DD string in US Eastern time, the
// same day boundary the site uses for the daily board (_triviaTodayStr).
'use strict';

function todayET(now) {
  const d = now || new Date();
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
}

function parse(dateStr) {
  const p = String(dateStr).split('-').map(Number);
  return { y: p[0], m: p[1], d: p[2] };
}

// Date math on the string form (UTC noon avoids DST edge cases).
function addDays(dateStr, n) {
  const p = parse(dateStr);
  const t = Date.UTC(p.y, p.m - 1, p.d, 12) + n * 86400000;
  return new Date(t).toISOString().slice(0, 10);
}

function dayNumber(dateStr) {
  const p = parse(dateStr);
  return Math.floor(Date.UTC(p.y, p.m - 1, p.d) / 86400000);
}

// 0 = Sunday … 6 = Saturday (calendar weekday of the ET date itself).
function weekday(dateStr) {
  const p = parse(dateStr);
  return new Date(Date.UTC(p.y, p.m - 1, p.d, 12)).getUTCDay();
}

function diffDays(a, b) { return dayNumber(a) - dayNumber(b); }

function fmt(y, m, d) {
  return y + '-' + String(m).padStart(2, '0') + '-' + String(d).padStart(2, '0');
}

// n-th weekday (0=Sun) of a month, e.g. nthWeekday(2026, 11, 4, 4) = 4th Thursday of Nov.
function nthWeekday(y, m, wd, n) {
  const first = new Date(Date.UTC(y, m - 1, 1, 12)).getUTCDay();
  const day = 1 + ((wd - first + 7) % 7) + (n - 1) * 7;
  return fmt(y, m, day);
}

// NFL season anchors for a season year (the year the regular season starts).
// Kickoff = Thursday after Labor Day (first Monday of September). Week N runs
// Tuesday → Monday; week 1 Tuesday is the Tuesday before kickoff.
function seasonAnchors(seasonYear) {
  const laborDay = nthWeekday(seasonYear, 9, 1, 1);
  const kickoff = addDays(laborDay, 3);
  const week1Tue = addDays(kickoff, -2);
  // 2026 regular season: 18 weeks (Sep 10 – Jan 10). Trade deadline = the
  // Tuesday after Week 9 (2025: Nov 4; 2026: Nov 3). Verify each August.
  const tradeDeadline = addDays(week1Tue, 9 * 7);
  // Super Bowl: second Sunday of February of the following year (2027-02-14).
  const superBowl = nthWeekday(seasonYear + 1, 2, 0, 2);
  const thanksgiving = nthWeekday(seasonYear, 11, 4, 4);
  return { laborDay, kickoff, week1Tue, tradeDeadline, superBowl, thanksgiving };
}

// Which season year does an ET date belong to (Mar → Feb)?
function seasonYearFor(dateStr) {
  const p = parse(dateStr);
  return p.m >= 3 ? p.y : p.y - 1;
}

// Regular-season week number for a date, or null outside Sep–early Jan.
function nflWeek(dateStr) {
  const sy = seasonYearFor(dateStr);
  const a = seasonAnchors(sy);
  const n = diffDays(dateStr, a.week1Tue);
  if (n < 0) return null;
  const wk = Math.floor(n / 7) + 1;
  return wk >= 1 && wk <= 18 ? wk : null;
}

// Calendar context for a date: flags the theme picker reads. Windows are
// deliberately generous (a few days either side) so the board can lean in
// before and after the event itself.
function calendarContext(dateStr) {
  const p = parse(dateStr);
  const sy = seasonYearFor(dateStr);
  const a = seasonAnchors(sy);
  const wd = weekday(dateStr);
  const wk = nflWeek(dateStr);
  const ctx = {
    date: dateStr, seasonYear: sy, weekday: wd, nflWeek: wk, anchors: a,
    inSeason: wk != null,
    // NFL Draft: late April (2026: Apr 23–25; 2027: Apr 22–24). Window
    // Apr 18 – May 2 covers the build-up and the post-draft chatter.
    draftWindow: (p.m === 4 && p.d >= 18) || (p.m === 5 && p.d <= 2),
    // Combine: late Feb / first days of March.
    combineWindow: (p.m === 2 && p.d >= 24) || (p.m === 3 && p.d <= 4),
    // Free agency legal tampering + first wave: Mar 9–20.
    freeAgencyWindow: p.m === 3 && p.d >= 9 && p.d <= 20,
    // Playoffs: the week after Week 18 through the Super Bowl.
    playoffWindow: wk == null && diffDays(dateStr, a.week1Tue) >= 18 * 7 && diffDays(dateStr, a.superBowl) <= 0,
    superBowlWeek: diffDays(a.superBowl, dateStr) >= 0 && diffDays(a.superBowl, dateStr) <= 6,
    kickoffWeek: diffDays(dateStr, a.kickoff) >= -3 && diffDays(dateStr, a.kickoff) <= 4,
    thanksgivingDay: dateStr === a.thanksgiving,
    blackFriday: dateStr === addDays(a.thanksgiving, 1),
    tradeDeadlineWeek: diffDays(a.tradeDeadline, dateStr) >= 0 && diffDays(a.tradeDeadline, dateStr) <= 6,
    fantasyPlayoffs: wk != null && wk >= 15 && wk <= 17,
    // Mon/Tue/Wed after a Sunday slate: the "big game" window.
    postGameDays: wk != null && (wd === 1 || wd === 2 || wd === 3),
    // College football: Saturdays Sep 1 – Dec 7, the Heisman ceremony week
    // (second Saturday of December, Mon–Sun), and bowl / playoff season.
    cfbSaturday: wd === 6 && ((p.m >= 9 && p.m <= 11) || (p.m === 12 && p.d <= 7)),
    heismanWeek: (() => { const sat = nthWeekday(p.y, 12, 6, 2); const dd = diffDays(sat, dateStr); return p.m === 12 && dd >= 0 && dd <= 6; })(),
    bowlSeason: (p.m === 12 && p.d >= 15) || (p.m === 1 && p.d <= 20),
  };
  // Day index inside a multi-day window so rotations are deterministic.
  ctx.dayIndex = dayNumber(dateStr);
  return ctx;
}

module.exports = { todayET, addDays, dayNumber, weekday, diffDays, nflWeek, seasonAnchors, seasonYearFor, calendarContext };
