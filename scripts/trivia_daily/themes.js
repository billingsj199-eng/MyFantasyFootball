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
function teamBoard(abbr, full, pos, stat) {
  const nick = nickname(full) || abbr;
  const positions = pos ? POS_GROUP[pos] : ALL_POS;
  const s = stat || (pos ? POS_YARDS[pos] : 'fpts');
  return {
    kind: 'team', key: 'team|' + abbr + '|' + s + '|' + positions.join(''),
    title: nick + ' All-Time ' + STAT_LABEL[s] + ' Leaders' + (pos ? ' · ' + POS_LABEL[pos] : ''),
    filters: Object.assign({}, BASE, { type: 'career', stat: s, team: abbr, positions }),
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

// A theme = ordered variants (first that builds + verifies wins) + metadata.
function theme(kind, score, variants, meta) {
  return Object.assign({ kind, score, variants, key: variants[0].key }, meta);
}

// --- news classification (general rules, no player lists) ---
const RX = {
  trade: /\b(traded|trade[sd]?\s+(to|for|with)|acquire[sd]?|acquiring|dealt|in exchange for|lands? (with|in)|sent to)\b/i,
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

  // ---- 100: hard calendar windows ----
  if (c.draftWindow) {
    const years = [2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018];
    const y = rot(years);
    push(theme('draft', 100, [draftBoard(y), draftBoard(2025)], { reason: 'NFL Draft window', desc: 'Draft week · the first 20 skill-position picks of the ' + y + ' class, pick by pick', colorway: 'green' }));
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
    if (it.tag === 'transaction' && RX.trade.test(h) && star) {
      newsThemes.push(theme('trade', 90, [teamBoard(abbr, full, pos, POS_YARDS[pos]), teamBoard(abbr, full, null, 'fpts'), careerBoard(pos, POS_YARDS[pos])],
        { reason: 'trade: ' + it.player, hook, desc: short(it.player + ' on the move — where would he rank among the ' + (nickname(full) || abbr) + ' greats?', 110), colorway: 'orange' }));
    } else if (it.tag === 'transaction' && RX.signing.test(h) && star) {
      newsThemes.push(theme('signing', 88, [teamBoard(abbr, full, pos, POS_YARDS[pos]), teamBoard(abbr, full, null, 'fpts')],
        { reason: 'signing: ' + it.player, hook, desc: short(it.player + ' · ' + h, 110), colorway: 'orange' }));
    } else if (RX.record.test(h) && it.tag !== 'injury') {
      const stat = statFromHeadline(h, pos) || POS_YARDS[pos];
      const single = /\b(single-game|in a game|one game|in a single game)\b/i.test(h);
      const variants = single ? [gameBoard(pos, stat), careerBoard(pos, stat)] : [careerBoard(pos, stat), gameBoard(pos, stat)];
      newsThemes.push(theme('record', 85, variants, { reason: 'record/milestone: ' + it.player, hook, desc: short(it.player + ' · ' + h, 110), colorway: 'yellow' }));
    } else if (it.tag === 'injury' && RX.seasonEnding.test(h) && star) {
      newsThemes.push(theme('injury', 70, [teamBoard(abbr, full, pos, POS_YARDS[pos]), teamBoard(abbr, full, null, 'fpts'), careerBoard(pos, POS_YARDS[pos])],
        { reason: 'season-ending injury: ' + it.player, hook, desc: short(it.player + ' is done for the year — the ' + (nickname(full) || abbr) + ' greats at ' + POS_LABEL[pos], 110), colorway: 'blue' }));
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
    push(theme('biggame', 80, [gameBoard(POS_GROUP[pos] ? pos : null, stat), gameBoard(null, 'fpts')],
      { reason: 'big game: ' + g.name + ' ' + g.value + ' ' + g.label + ' (Wk ' + g.week + ')', hook: { player: g.name, headline: g.name + ' had ' + g.value + ' ' + g.label + (g.opp ? ' vs ' + g.opp : '') + ' in Week ' + g.week, date: sig.date },
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
  if (c.tradeDeadlineWeek && sig.mostTraded && sig.mostTraded.count >= 10 && POS_GROUP[sig.mostTraded.pos]) {
    const mt = sig.mostTraded;
    const full = P.abbrToFull[mt.team] || '';
    push(theme('deadline', 60, [teamBoard(mt.team, full, mt.pos, POS_YARDS[mt.pos]), teamBoard(mt.team, full, null, 'fpts')],
      { reason: 'trade deadline week · most-traded in fantasy: ' + mt.name, hook: { player: mt.name, headline: mt.name + ' is the most-traded player in fantasy leagues this week (' + mt.count + ' trades)', date: sig.date },
        desc: short('Trade deadline week · ' + mt.name + ' is the most-traded player in fantasy leagues — the ' + (nickname(full) || mt.team) + ' greats', 110), colorway: 'orange' }));
  }

  // ---- 50: fantasy trade market ----
  if (sig.mostTraded && sig.mostTraded.count >= 15 && POS_GROUP[sig.mostTraded.pos]) {
    const mt = sig.mostTraded;
    const full = P.abbrToFull[mt.team] || '';
    push(theme('mosttraded', 50, [teamBoard(mt.team, full, mt.pos, POS_YARDS[mt.pos]), teamBoard(mt.team, full, null, 'fpts')],
      { reason: 'most-traded in fantasy: ' + mt.name, hook: { player: mt.name, headline: mt.name + ' is the most-traded player in fantasy leagues this week (' + mt.count + ' trades)', date: sig.date },
        desc: short(mt.name + ' is the most-traded player in fantasy leagues this week — the ' + (nickname(full) || mt.team) + ' greats', 110), colorway: 'purple' }));
  }

  // ---- repeat guard: skip theme keys locked in the last REPEAT_DAYS ----
  const recentKeys = new Set();
  (sig.history || []).forEach(hx => {
    if (!hx.date) return;
    const age = require('./calendar').diffDays(sig.date, hx.date);
    if (age >= 0 && age <= REPEAT_DAYS) {
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

module.exports = { pickThemes, STAT_LABEL, POS_GROUP, teamBoard, careerBoard, gameBoard, weekBoard, postBoard, draftBoard, REPEAT_DAYS };
