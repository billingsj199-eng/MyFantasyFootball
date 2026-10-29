// Daily Trivia theme picker — turns calendar + news signals into an ordered
// list of board candidates. Each candidate carries the exact structured
// filters the site's own trivia generator takes (_triviaApplyTemplate shape),
// so the board is built from the same data the templates use. No AI.
//
// Priority (highest wins; ties keep list order):
//   100 hard calendar window (draft week, Super Bowl week, kickoff, Thanksgiving)
//    90 NFL trade / signing of a star
//    85 record / milestone headline
//    80 monster single game on the latest slate (Mon–Wed only)
//    70 season-ending injury to a star
//    60 soft calendar window (trade-deadline week, fantasy playoffs, combine, playoffs)
//    50 most-traded player in fantasy leagues this week (in-season)
// A candidate whose theme key was locked in the last 10 days is skipped.
// If nothing qualifies the job locks nothing and the template cycle runs.
'use strict';

const STAT_LABEL = { py: 'Passing Yards', ptd: 'Passing TDs', ry: 'Rushing Yards', rtd: 'Rushing TDs', rcy: 'Receiving Yards', rec: 'Receptions', rctd: 'Receiving TDs', fpts: 'Fantasy Points', totalTd: 'Total TDs', ppg: 'Fantasy PPG' };
const POS_GROUP = { QB: ['QB'], RB: ['RB'], WR: ['WR', 'TE'], TE: ['WR', 'TE'] };
const POS_LABEL = { QB: 'QB', RB: 'RB', WR: 'WR/TE', TE: 'WR/TE' };
const POS_YARDS = { QB: 'py', RB: 'ry', WR: 'rcy', TE: 'rcy' };
const POS_TDS = { QB: 'ptd', RB: 'rtd', WR: 'rctd', TE: 'rctd' };
const ALL_POS = ['QB', 'RB', 'WR', 'TE'];
const REPEAT_DAYS = 10;

const BASE = { year: 'all', count: 20, conf: 'all', team: 'all' };

function nickname(full) {
  if (!full) return '';
  const parts = full.split(' ');
  return parts[parts.length - 1];
}

function short(s, n) {
  s = String(s || '').replace(/\s+/g, ' ').trim();
  if (s.length <= n) return s;
  return s.slice(0, n - 1).replace(/[\s,;:.-]+$/, '') + '…';
}

// --- board variants: each returns {title, filters, kind} ---
// Franchise boards are built in Node from WITH-TEAM totals since 1999
// (scripts/trivia_daily/teamboards.js) — the site's team filter ranks
// primary-team players by full-career totals and misses legends outside
// its main table (the 2026-10-28 Dolphins board). Lazy: built on demand.
let _teamRepo = null;
function setTeamRepo(repoDir, log) { _teamRepo = { repoDir, log }; }
function teamBoard(abbr, full, pos, stat) {
  const nick = nickname(full) || abbr;
  const positions = pos ? POS_GROUP[pos] : null;
  const s = stat || (pos ? POS_YARDS[pos] : 'fpts');
  const key = 'team|' + abbr + '|' + s + '|' + (positions || []).join('');
  return {
    kind: 'list', key,
    title: nick + ' ' + STAT_LABEL[s] + ' Leaders · Since 1999' + (pos ? ' · ' + POS_LABEL[pos] : ''),
    lazy: () => {
      const T = require('./teamboards');
      const ctx = T.context(_teamRepo.repoDir, _teamRepo.log);
      const b = T.teamLeaders(ctx, abbr, nick, s, positions, 20);
      if (!b) return null;
      if (b.thin) { _teamRepo.log && _teamRepo.log('  ' + key + ': thin tail (#16 ' + b.sixteenth.name + ' ' + b.sixteenth.v + ' < floor) — skipped'); return null; }
      if (b.disagreements.length) { _teamRepo.log && _teamRepo.log('  ' + key + ': legends cross-check mismatch — ' + b.disagreements.join('; ')); return null; }
      return b;
    },
  };
}
function careerBoard(pos, stat) {
  const positions = pos ? POS_GROUP[pos] : ALL_POS;
  return {
    kind: 'career', key: 'career|' + stat + '|' + positions.join(''),
    title: 'All-Time ' + STAT_LABEL[stat] + ' Leaders' + (pos ? ' · ' + POS_LABEL[pos] : ''),
    filters: Object.assign({}, BASE, { type: 'career', stat, positions }),
  };
}
function gameBoard(pos, stat) {
  const positions = pos ? POS_GROUP[pos] : ALL_POS;
  return {
    kind: 'game', key: 'game|' + stat + '|' + positions.join(''),
    title: 'Best Single-Game ' + STAT_LABEL[stat] + ' Ever' + (pos ? ' · ' + POS_LABEL[pos] : ''),
    filters: Object.assign({}, BASE, { type: 'game', stat, positions }),
  };
}
function teamGameBoard(abbr, full, pos, stat) {
  const nick = nickname(full) || abbr;
  const positions = pos ? POS_GROUP[pos] : ALL_POS;
  return {
    kind: 'game', key: 'teamgame|' + abbr + '|' + stat + '|' + positions.join(''),
    title: nick + ' Best Single-Game ' + STAT_LABEL[stat] + ' Ever' + (pos ? ' · ' + POS_LABEL[pos] : ''),
    filters: Object.assign({}, BASE, { type: 'game', stat, team: abbr, positions }),
  };
}
function weekBoard(week) {
  return {
    kind: 'week', key: 'week|' + week,
    title: 'Best Week ' + week + ' Games Ever',
    filters: Object.assign({}, BASE, { type: 'game', stat: 'fpts', positions: ALL_POS, week: String(week) }),
  };
}
function postBoard(pos, stat) {
  const positions = pos ? POS_GROUP[pos] : ALL_POS;
  return {
    kind: 'post', key: 'post|' + stat + '|' + positions.join(''),
    title: 'Career Playoff ' + STAT_LABEL[stat] + ' Leaders' + (pos ? ' · ' + POS_LABEL[pos] : ''),
    filters: Object.assign({}, BASE, { type: 'career', stat, positions, seasonType: 'post' }),
  };
}
// Round 1 alone holds only ~11 skill-position picks a year (too few for a
// 4x4 board), so take the first 20 QB/RB/WR/TE picks of the class instead.
function draftBoard(year) {
  return {
    kind: 'draft', key: 'draft|' + year + '|top20',
    title: year + ' NFL Draft · First 20 Skill-Position Picks',
    filters: Object.assign({}, BASE, { type: 'draft', stat: 'fpts', year: String(year), draftRound: 'all', positions: ALL_POS }),
  };
}

// --- list boards (nflverse trade history, not stats) ---
// inject = {name, from, to} adds tonight's trade on top when nflverse does
// not have it yet (it lags real trades by days).
function listBoard(kind, nfl, inject) {
  if (!nfl) return null;
  const T = require('./trades');
  let items, title, desc;
  if (kind === 'tradedForFirst') {
    items = T.itemsTradedForFirst(nfl.tradedForFirst, 20);
    title = 'Traded for a First-Round Pick';
    desc = 'NFL players dealt for a 1st since 2002 — name them';
  } else if (kind === 'top10Traded') {
    items = T.itemsTop10Traded(nfl.top10Traded, 20);
    title = 'Top-10 Picks Who Got Traded';
    desc = 'Drafted in the top 10, then dealt — name them';
  } else return null;
  if (inject && inject.name && !items.some(it => sameName(it.answer, inject.name))) {
    const yr = String(inject.year || new Date().getFullYear());
    const route = inject.from && inject.to && inject.from !== inject.to ? inject.from + ' → ' + inject.to : (inject.to ? 'to ' + inject.to : '');
    items.unshift(kind === 'tradedForFirst'
      ? { rank: '', value: '', headshot: '', answer: inject.name, category: yr, hint: (route ? route + ' ' : '') + 'for a 1st', team: inject.to || inject.from || '' }
      : { rank: '', value: '', headshot: '', answer: inject.name, category: 'Pick #' + inject.pick + ' · ' + inject.draftYear, hint: (route || 'traded') + ' (' + yr + ')', team: inject.to || inject.from || '' });
    items = items.slice(0, 20);
  }
  if (items.length < 16) return null;
  return { kind: 'list', key: 'list|' + kind, title, desc, items };
}
function sameName(a, b) {
  const n = x => String(x || '').split(/[\(\,]/)[0].replace(/\s+(Sr\.?|Jr\.?|II|III|IV)$/i, '').replace(/[^a-z ]/gi, '').replace(/\s+/g, ' ').trim().toLowerCase();
  return n(a) === n(b);
}

// --- college boards (scripts/trivia_daily/college.js) ---
// Built lazily (Wikipedia / ESPN fetches, cached) by build_board when the
// variant's turn comes; `lazy()` returns {title, desc, items} or null.
const CFB_SCHOOLS = ['Alabama', 'Ohio State', 'Georgia', 'LSU', 'Oklahoma', 'Texas', 'USC', 'Michigan', 'Clemson', 'Notre Dame', 'Oregon', 'Penn State', 'Florida', 'Florida State', 'Auburn', 'Wisconsin', 'Tennessee', 'Texas A&M', 'Oklahoma State', 'Miami'];
const CFB_CONFS = ['SEC', 'Big Ten', 'Big 12', 'ACC', 'Pac-12'];
const CFB_STATS = ['ry', 'rcy', 'py']; // yards only: TD / reception columns are too sparse for 16-row boards
function cfbVariant(key, title, lazy) {
  return { kind: 'list', key, title, lazy };
}
// Rotation of college boards for a day index: returns [primary, fallback, fallback].
function cfbRotation(cfb, dayIndex) {
  const C = require('./college');
  const stat = CFB_STATS[dayIndex % CFB_STATS.length];
  const school = CFB_SCHOOLS[dayIndex % CFB_SCHOOLS.length];
  const conf = CFB_CONFS[dayIndex % CFB_CONFS.length];
  const yr = () => cfb().college.maxYear;
  const all = [
    () => cfbVariant('cfb|season|' + stat, 'College season leaders', () => C.seasonLeaders(cfb(), yr(), stat)),
    () => cfbVariant('cfb|school|' + school + '|' + stat, school + ' leaders', () => C.schoolLeaders(cfb(), school, stat)),
    () => cfbVariant('cfb|conf|' + conf + '|' + stat, conf + ' season leaders', () => C.conferenceSeason(cfb(), conf, yr(), stat)),
    () => cfbVariant('cfb|game|' + stat, 'Best college games', () => C.bestGames(cfb(), stat)),
    () => cfbVariant('cfb|career|' + stat, 'College career leaders', () => C.careerLeaders(cfb(), stat)),
  ];
  const n = all.length;
  return [all[dayIndex % n](), all[(dayIndex + 1) % n](), all[(dayIndex + 2) % n]()];
}

// A theme = ordered variants (first that builds + verifies wins) + metadata.
// mustInclude: the player in the news has to be on the board (Jack 10-28).
function theme(kind, score, variants, meta) {
  variants = variants.filter(Boolean);
  if (!variants.length) return null;
  return Object.assign({ kind, score, variants, key: variants[0].key }, meta);
}

// --- news classification (general rules, no player lists) ---
const RX = {
  trade: /\b(trad(e|es|ed|ing)|acquire[sd]?|acquiring|dealt|in exchange for|lands? (with|in)|sent to|swap(s|ped)?)\b/i,
  signing: /\b(sign(s|ed)?|agree[sd]? to (terms|a deal)|extension|contract)\b/i,
  record: /\b(record|nfl history|franchise history|all-time|most ever|most in (nfl|league|franchise)|first (player|qb|quarterback|rb|running back|wr|receiver|te|tight end)|milestone|surpass(es|ed)?|passes [A-Z][a-z]+ .*(list|all-time)|becomes the)\b/i,
  seasonEnding: /\b(out for the season|season-ending|season ending|torn (acl|achilles|patellar)|tore (his )?(acl|achilles|patellar|pectoral)|ruptured|placed on (season-ending )?ir|will miss the (rest of the|remainder of the) season)\b/i,
  rushing: /\brush(ing|ed)?\b|\bcarries\b|\bground\b/i,
  receiving: /\breceiv(ing|er)\b|\bcatch(es)?\b|\breceptions?\b|\btargets?\b/i,
  passing: /\bpass(ing|es|ed)?\b|\bthrows?\b|\bthrew\b|\bcompletions?\b/i,
  td: /\btouchdowns?\b|\btds?\b/i,
  yards: /\byards?\b|\byds\b/i,
};

function statFromHeadline(h, pos) {
  const td = RX.td.test(h), yd = RX.yards.test(h);
  let fam = null;
  if (RX.passing.test(h) && (pos === 'QB' || !RX.receiving.test(h))) fam = 'QB';
  else if (RX.rushing.test(h)) fam = 'RB';
  else if (RX.receiving.test(h)) fam = 'WR';
  else fam = pos;
  if (!fam || !POS_YARDS[fam]) return null;
  if (td && !yd) return POS_TDS[fam];
  return POS_YARDS[fam];
}

function pickThemes(sig) {
  const c = sig.calendar;
  const P = sig.players;
  const out = [];
  const seenKeys = new Set();
  const push = (t) => { if (t && !seenKeys.has(t.key)) { seenKeys.add(t.key); out.push(t); } };
  const rot = (arr) => arr[((c.dayIndex % arr.length) + arr.length) % arr.length];
  setTeamRepo(sig.repoDir, sig.log);
  // College context is loaded only when a college variant is actually built.
  let _cfbCtx = null;
  const cfb = () => (_cfbCtx = _cfbCtx || require('./college').context(sig.repoDir, sig.log));
  const C = require('./college');

  // ---- 100: hard calendar windows ----
  if (c.draftWindow) {
    const years = [2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018];
    const y = rot(years);
    const stat = CFB_STATS[c.dayIndex % 3]; // ry / rcy / py
    const classYear = c.seasonYear; // draft in April 2027 = the 2027 class
    const classBoard = cfbVariant('cfb|class|' + classYear + '|' + stat, classYear + ' class college ' + stat, () => C.draftClassCollege(cfb(), classYear, stat));
    const variants = (c.dayIndex % 2 === 0) ? [draftBoard(y), classBoard, draftBoard(2025)] : [classBoard, draftBoard(y), draftBoard(2025)];
    push(theme('draft', 100, variants, { reason: 'NFL Draft window', desc: 'Draft week · the ' + classYear + ' class by college numbers, and past classes pick by pick', colorway: 'green' }));
  }
  // Heisman week: the ceremony is the second Saturday of December.
  if (c.heismanWeek) {
    push(theme('heisman', 100, [cfbVariant('cfb|heisman', 'Heisman winners', () => C.heismanBoard(cfb(), 20))], { reason: 'Heisman week', desc: 'Heisman week · name the winner for each year', colorway: 'yellow' }));
  }
  // College Saturdays in season, and bowl / playoff season: one college board.
  if (c.cfbSaturday || c.bowlSeason) {
    const v = cfbRotation(cfb, c.dayIndex);
    if (c.bowlSeason && c.dayIndex % 3 === 0) v.unshift(cfbVariant('cfb|heisman', 'Heisman winners', () => C.heismanBoard(cfb(), 20)));
    push(theme('college', c.bowlSeason ? 60 : 55, v, { reason: c.bowlSeason ? 'bowl season' : 'college Saturday', desc: c.bowlSeason ? 'Bowl season · college football board' : 'College Saturday · a college football board', colorway: 'green' }));
  }
  if (c.superBowlWeek || c.playoffWindow) {
    const v = rot([postBoard('QB', 'py'), postBoard('RB', 'ry'), postBoard('WR', 'rcy'), postBoard(null, 'fpts'), postBoard('QB', 'ptd')]);
    push(theme('playoffs', c.superBowlWeek ? 100 : 60, [v, postBoard(null, 'fpts')], { reason: c.superBowlWeek ? 'Super Bowl week' : 'NFL playoffs', desc: (c.superBowlWeek ? 'Super Bowl week' : 'Playoff football') + ' · the all-time postseason leaders', colorway: 'yellow' }));
  }
  if (c.kickoffWeek) {
    push(theme('kickoff', 100, [weekBoard(1), gameBoard(null, 'fpts')], { reason: 'season kickoff week', desc: 'Kickoff week · the biggest Week 1 fantasy games ever', colorway: 'green' }));
  }
  if (c.thanksgivingDay || c.blackFriday) {
    const abbr = c.thanksgivingDay ? 'DET' : 'DAL';
    const full = P.abbrToFull[abbr] || abbr;
    push(theme('thanksgiving', 100, [teamBoard(abbr, full, null, 'fpts'), teamBoard(abbr, full, 'RB', 'ry')], { reason: 'Thanksgiving host', desc: 'Thanksgiving football · the ' + nickname(full) + ' greats', colorway: 'orange' }));
  }

  // ---- news-driven ----
  const news = (sig.news && sig.news.recent) || [];
  const newsThemes = [];
  news.forEach(it => {
    if (!it || !it.player || !it.headline) return;
    const d = P.find(it.player);
    const pos = (d && d.s) || it.pos || '';
    if (!POS_GROUP[pos]) return;
    const star = P.isStar(d);
    const h = it.headline;
    const abbr = (it.team && it.team.length <= 3 ? it.team : '') || P.teamAbbr(d);
    const full = P.abbrToFull[abbr] || '';
    const hook = { player: it.player, headline: it.headline, url: it.url || '', date: it.date, tag: it.tag };
    if (it.tag === 'transaction' && RX.trade.test(h)) {
      // Trade: a list board when the deal fits one ("for a first-round
      // pick", or the player was a top-10 pick), then the new team's
      // all-time list at his position. He must be on whichever wins.
      const nfl = sig.nfl;
      const draft = nfl && nfl.draftByName[it.player];
      const fromAbbr = P.teamAbbr(d);
      const inject = { name: it.player, year: (it.date || '').slice(0, 4), from: fromAbbr !== abbr ? fromAbbr : '', to: abbr, pick: draft && draft.pick, draftYear: draft && draft.year };
      const mentionsFirst = /\b(first|1st)[- ]round(er| pick| selection)?s?\b|\bfor a (first|1st)\b/i.test(h);
      const variants = [];
      if (mentionsFirst) variants.push(listBoard('tradedForFirst', nfl, inject));
      if (draft && draft.pick <= 10) variants.push(listBoard('top10Traded', nfl, inject));
      // He is on his OLD team's all-time list, not (yet) the new one's.
      const oldFull = P.abbrToFull[fromAbbr] || '';
      if (fromAbbr && fromAbbr !== abbr) variants.push(teamBoard(fromAbbr, oldFull, pos, POS_YARDS[pos]), teamBoard(fromAbbr, oldFull, null, 'fpts'));
      variants.push(teamBoard(abbr, full, pos, POS_YARDS[pos]), teamBoard(abbr, full, null, 'fpts'), careerBoard(pos, POS_YARDS[pos]));
      newsThemes.push(theme('trade', 90, variants,
        { reason: 'trade: ' + it.player, hook, mustInclude: it.player, desc: short(it.player + ' on the move — ' + h, 110), colorway: 'orange' }));
    } else if (it.tag === 'transaction' && RX.signing.test(h)) {
      newsThemes.push(theme('signing', 88, [teamBoard(abbr, full, pos, POS_YARDS[pos]), teamBoard(abbr, full, null, 'fpts')],
        { reason: 'signing: ' + it.player, hook, mustInclude: it.player, desc: short(it.player + ' · ' + h, 110), colorway: 'orange' }));
    } else if (RX.record.test(h) && it.tag !== 'injury') {
      const stat = statFromHeadline(h, pos) || POS_YARDS[pos];
      const single = /\b(single-game|in a game|one game|in a single game)\b/i.test(h);
      const variants = single ? [gameBoard(pos, stat), careerBoard(pos, stat)] : [careerBoard(pos, stat), gameBoard(pos, stat)];
      newsThemes.push(theme('record', 85, variants, { reason: 'record/milestone: ' + it.player, hook, mustInclude: it.player, includeSoft: true, desc: short(it.player + ' · ' + h, 110), colorway: 'yellow' }));
    } else if (it.tag === 'injury' && RX.seasonEnding.test(h) && star) {
      newsThemes.push(theme('injury', 70, [teamBoard(abbr, full, pos, POS_YARDS[pos]), teamBoard(abbr, full, null, 'fpts'), careerBoard(pos, POS_YARDS[pos])],
        { reason: 'season-ending injury: ' + it.player, hook, mustInclude: it.player, desc: short(it.player + ' is done for the year — the ' + (nickname(full) || abbr) + ' greats at ' + POS_LABEL[pos], 110), colorway: 'blue' }));
    }
  });
  // Newest first inside the same score so tonight's story beats Monday's.
  newsThemes.sort((a, b) => b.score - a.score || String(b.hook.date).localeCompare(String(a.hook.date)));
  newsThemes.forEach(push);

  // ---- 80: monster game on the latest slate ----
  const bg = sig.bigGames;
  if (bg && bg.games && bg.games.length) {
    const g = bg.games[0];
    const stat = g.stat === 'fpts' ? 'fpts' : g.stat;
    const pos = g.pos;
    const gFull = P.abbrToFull[g.team] || '';
    push(theme('biggame', 80, [gameBoard(POS_GROUP[pos] ? pos : null, stat), g.team ? teamGameBoard(g.team, gFull, POS_GROUP[pos] ? pos : null, stat) : null, g.team ? teamGameBoard(g.team, gFull, null, 'fpts') : null, gameBoard(null, 'fpts')],
      { reason: 'big game: ' + g.name + ' ' + g.value + ' ' + g.label + ' (Wk ' + g.week + ')', mustInclude: g.name, includeSoft: true, hook: { player: g.name, headline: g.name + ' had ' + g.value + ' ' + g.label + (g.opp ? ' vs ' + g.opp : '') + ' in Week ' + g.week, date: sig.date },
        desc: short(g.name + ' went off for ' + g.value + ' ' + g.label + ' in Week ' + g.week + ' — the best single games ever', 110), colorway: 'red' }));
  }

  // ---- 60: soft calendar windows ----
  if (c.fantasyPlayoffs) {
    push(theme('fantasyplayoffs', 60, [weekBoard(c.nflWeek), gameBoard(null, 'fpts')], { reason: 'fantasy playoffs week ' + c.nflWeek, desc: 'Fantasy playoffs · the biggest Week ' + c.nflWeek + ' games ever', colorway: 'red' }));
  }
  if (c.combineWindow) {
    const y = rot([2025, 2024, 2023, 2022]);
    push(theme('combine', 60, [draftBoard(y)], { reason: 'combine week', desc: 'Combine week · the first 20 skill-position picks of the ' + y + ' class, pick by pick', colorway: 'green' }));
  }
  if (c.tradeDeadlineWeek) {
    // Deadline week: real NFL trade history, rotating between the two lists.
    const first = rot(['tradedForFirst', 'top10Traded']);
    const other = first === 'tradedForFirst' ? 'top10Traded' : 'tradedForFirst';
    const a = listBoard(first, sig.nfl), b = listBoard(other, sig.nfl);
    push(theme('deadline', 60, [a, b], { reason: 'trade deadline week', desc: (a || b || {}).desc ? 'Trade deadline week · ' + (a || b).desc : 'Trade deadline week', colorway: 'orange' }));
  }

  // ---- 50: fantasy trade market ----
  if (sig.mostTraded && sig.mostTraded.count >= 15 && POS_GROUP[sig.mostTraded.pos]) {
    const mt = sig.mostTraded;
    const full = P.abbrToFull[mt.team] || '';
    push(theme('mosttraded', 50, [teamBoard(mt.team, full, mt.pos, POS_YARDS[mt.pos]), teamBoard(mt.team, full, null, 'fpts')],
      { reason: 'most-traded in fantasy: ' + mt.name, mustInclude: mt.name, hook: { player: mt.name, headline: mt.name + ' is the most-traded player in fantasy leagues this week (' + mt.count + ' trades)', date: sig.date },
        desc: short(mt.name + ' is the most-traded player in fantasy leagues this week — the ' + (nickname(full) || mt.team) + ' greats', 110), colorway: 'purple' }));
  }

  // ---- repeat guard: skip theme keys locked in the last REPEAT_DAYS ----
  const recentKeys = new Set();
  (sig.history || []).forEach(hx => {
    if (!hx.date) return;
    // The target date's own earlier auto lock is what a re-run replaces —
    // it must not push the picker onto a weaker variant.
    if (hx.date === sig.date) return;
    const age = require('./calendar').diffDays(sig.date, hx.date);
    if (age > 0 && age <= REPEAT_DAYS) {
      if (hx.auto && hx.auto.key) recentKeys.add(hx.auto.key);
      if (hx.title) recentKeys.add('title|' + hx.title);
    }
  });
  out.forEach(t => {
    t.variants = t.variants.filter(v => !recentKeys.has(v.key) && !recentKeys.has('title|' + v.title));
    t.skipped = t.variants.length === 0 ? 'all variants locked in the last ' + REPEAT_DAYS + ' days' : null;
  });

  out.sort((a, b) => b.score - a.score);
  return out;
}

module.exports = { pickThemes, STAT_LABEL, POS_GROUP, teamBoard, careerBoard, gameBoard, teamGameBoard, weekBoard, postBoard, draftBoard, listBoard, REPEAT_DAYS };
